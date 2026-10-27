"""P0 NOSTALGIA REWORK W2 (source-2026-10-27, NOST-05/06/08/10/11/12) —
смысловая релевантность, тематический поиск, повторы/разнообразие, большой
архив, админка/диагностика.

Покрытие (по свойствам результата, не по ожидаемым фразам — NOST-15/16):
* NOST-05 — объём ≠ интересность (ранжирование без счётчика сообщений);
  исторический пул не гейтится весом происхождения (решение — вердикт
  модели); контекстный сценарий видит содержание текущего разговора
  (секция payload), окно «последних 5 отдельных слов» расширено.
* NOST-06 — тематический режим находит эпизод вне календарной годовщины
  (тот же движок реконструкции, второй движок не создавался); календарное
  совпадение не предпочитается гарантированно (обе группы в payload,
  тематическая выше).
* NOST-08 — повтор контролируется ИДЕНТИЧНОСТЬЮ эпизода (message_key/границы,
  не текст); тот же эпизод не публикуется повторно (молчание, честный
  reason=repeat); старая публикация за окном — не повтор; разнообразие
  периодов между тиками без фиксированных квот (второй эпизод всплывает).
* NOST-10 — маршрут через существующий Decision/Initiative: контракт
  nostalgia_due не изменялся (цепочка разрешена, кандидат несёт trigger).
* NOST-11 — плотные окна стратифицируются (выборка покрывает период, честный
  truncated); тематический режим поэтапный (семена → отбор → ≤N деталей);
  ошибка тематического поиска деградирует честно (флаг в meta, календарь
  живёт); ошибка границ архива — честный archive_error.
* NOST-12 — глубина поиска (memory.nostalgia_history_depth_years: 0 = весь
  архив, N = последние N лет); диагностика прогона в nostalgia_log.meta
  (режим, найдено/показано, повторы, периоды, секции payload, episode_ids);
  админ-крутилки на месте (новая + прежние).

LLM/бот замоканы; время фиксировано (NOW = 2027-01-15 11:00 локально,
Asia/Yekaterinburg). Семантическое качество модели моками НЕ объявляется —
моки проверяют МАРШРУТ иpayload (NOST-16).
"""
import asyncio
import datetime
import json
import logging

import pytest

from config.settings import settings
from services import hot_config as hot
from services import nostalgia_worker as nw
from services.database import DatabaseService
from services.nostalgia_prompts import build_nostalgia_user

logging.getLogger("services.worker_settings").setLevel(logging.CRITICAL)
logging.getLogger("services.param_catalog").setLevel(logging.CRITICAL)
logging.getLogger("services.mca_events").setLevel(logging.CRITICAL)

CHAT_ID = -1002661910336
BOT_ID = 12345
USER_ID = 55
NOW = 1_800_000_000          # 2027-01-15 11:00 Asia/Yekaterinburg (+05)


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class _FakeLLM:
    def __init__(self, answer="UNCHANGED"):
        self.answer = answer
        self.calls = []

    async def generate(self, messages, temperature=None):
        self.calls.append((messages, temperature))
        return self.answer

    async def generate_worker(self, role, messages, temperature=None):
        return await self.generate(messages, temperature=temperature)


class _FakeBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, chat_id, text):
        self.calls.append((int(chat_id), str(text)))


def _hot_cache(monkeypatch, values: dict | None = None):
    class _FakeHotCache:
        def __init__(self, vals):
            self._values = dict(vals or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


def _worker(d, llm=None, *, monkeypatch=None, values=None, bot=None):
    w = nw.NostalgiaWorker(d, memory=None, store=None,
                           llm=llm if llm is not None else _FakeLLM(),
                           bot=bot if bot is not None else _FakeBot(),
                           bot_id=BOT_ID)
    _hot_cache(monkeypatch, values if values is not None else
               {"memory.nostalgia_enabled": True})
    return w


def _worker_time(monkeypatch, now=NOW):
    monkeypatch.setattr(nw, "_now_ts", lambda: now)
    monkeypatch.setattr(nw, "_local_hour", lambda ts, tz=None: 12)


def _ts_local(y, m, d, hour, minute=0) -> int:
    tz = nw._zone(settings.SUMMARY_TIMEZONE)
    return int(datetime.datetime(y, m, d, hour, minute,
                                 tzinfo=tz).timestamp())


async def _msg(d, text, ts, *, uid=USER_ID, name="Вася", reply_to=None,
               is_forward=False, forward_source="", tg=None):
    return await d.save_smart_message(
        uid, CHAT_ID, text, reply_to, int(ts), "text", name,
        is_forward=is_forward, forward_source=forward_source,
        message_id=tg)


async def _log_rows(d):
    return await d.recent_nostalgia_log(chat_id=CHAT_ID, limit=50)


# ═══ NOST-05: интересность ≠ активность; контекст беседы ════════════════════

class TestInterestNotActivity:
    @pytest.mark.asyncio
    async def test_volume_does_not_rank_or_drop_episodes(self, db,
                                                         monkeypatch):
        """T21/NOST-05.2: длинный эпизод одного года и короткий
        характерный другого — ОБА в пуле; порядок технический (свежесть),
        объём (число сообщений) порядок не меняет и отбором не является."""
        _worker_time(monkeypatch)
        # короткий характерный эпизод 2025 (1 сообщение)
        await _msg(db, "экспедиция нашла клад под мостом",
                   _ts_local(2025, 1, 15, 12))
        # длинный (объёмный) эпизод 2026 (8 сообщений подряд)
        for i in range(8):
            await _msg(db, f"обсуждение погоды продолжается {i}",
                       _ts_local(2026, 1, 15, 12, i))
        await _msg(db, "в чате тоскливо", NOW - 30 * 3600)
        w = _worker(db, monkeypatch=monkeypatch)
        candidate, info = await w._pick_candidate(CHAT_ID, NOW)
        assert candidate is not None
        assert candidate["kind"] == "year_back"
        years = [e["year"] for e in candidate["episodes"]]
        # оба эпизода предъявлены: свежий первым, объём порядок не меняет
        assert years == [2026, 2025]
        assert info["episodes_found"] == 2
        assert info["episodes_shown"] == 2
        texts = " ".join(candidate["year_lines"])
        assert "экспедиция нашла клад" in texts
        assert "обсуждение погоды" in texts

    def test_rank_key_has_no_volume_term(self):
        """Технический ранг предъявления не содержит счётчика сообщений
        (объём ≠ интересность на уровне механизма, не только канона)."""
        short = {"year": 2024, "topical": False, "messages": 1}
        long_ep = {"year": 2023, "topical": False, "messages": 500}
        ranked = nw._rank_episodes([long_ep, short])
        assert ranked[0]["year"] == 2024          # только свежесть/тема
        same_year = [dict(short, year=2023), dict(long_ep, year=2023)]
        ranked2 = nw._rank_episodes(same_year)
        assert ranked2[0]["messages"] == 1        # при равенстве — входной
        assert ranked2[1]["messages"] == 500      # порядок, не пересортировка

    @pytest.mark.asyncio
    async def test_short_characteristic_episode_presented(self, db,
                                                          monkeypatch):
        """T20: эпизод из одной краткой характерной реплики не отбрасывается
        за размер (минимума сообщений нет, NOST-04/05)."""
        _worker_time(monkeypatch)
        await _msg(db, "— ты опять споришь с фанатом? — всегда",
                   _ts_local(2025, 1, 15, 12))
        await _msg(db, "в чате тоскливо", NOW - 30 * 3600)
        w = _worker(db, monkeypatch=monkeypatch)
        candidate, info = await w._pick_candidate(CHAT_ID, NOW)
        assert candidate is not None
        assert candidate["episodes"][0]["messages"] == 1
        assert info["episodes_shown"] == 1

    @pytest.mark.asyncio
    async def test_context_section_shows_current_burst(self, db,
                                                       monkeypatch):
        """NOST-05.3: контекстный сценарий видит содержание текущего
        разговора (секция «Текущий разговор» в payload), а годовалые
        сообщения тихого чата НЕ попадают в «текущий разговор» (всплеск
        беседы ограничен разрывом времени)."""
        _worker_time(monkeypatch)
        await _msg(db, "обсуждаем рельсы узкой колеи", NOW - 3600)
        await _msg(db, "и шпалы тоже обсуждаем", NOW - 1800)
        await _msg(db, "рельсы широкие забыли год назад",
                   _ts_local(2026, 1, 15, 12))
        w = _worker(db, monkeypatch=monkeypatch)
        context_rows, topic_words = await w._recent_context(CHAT_ID)
        assert len(context_rows) == 2             # только всплеск беседы
        assert "рельс" in " ".join(topic_words)
        payload = build_nostalgia_user(
            ["[Вася 2026-01-15]: рельсы широкие забыли год назад"], [],
            context_lines=["[Вася]: обсуждаем рельсы узкой колеи"])
        assert "Текущий разговор:" in payload
        assert "обсуждаем рельсы узкой колеи" in payload


# ═══ NOST-06: тематический поиск по всей истории ════════════════════════════

class TestThematicSearch:
    @pytest.mark.asyncio
    async def test_episode_outside_anniversary_surfaced(self, db,
                                                        monkeypatch):
        """T17: тема текущего разговора находит старый эпизод вне
        календарной годовщины (июнь 2024 при тике 15 января 2027)."""
        _worker_time(monkeypatch)
        # архив: эпизод про гитару в июне 2024 (не годовщина 15 января)
        await _msg(db, "вася зажигал на гитаре у костра",
                   _ts_local(2024, 6, 10, 21))
        await _msg(db, "и второй куплет про гитару был",
                   _ts_local(2024, 6, 10, 21, 20))
        # текущая беседа о гитаре (всплеск час назад)
        await _msg(db, "давайте про гитару вспомним", NOW - 3600)
        await _msg(db, "кто там опять про гитару спрашивал", NOW - 600)
        llm = _FakeLLM("UNCHANGED")
        w = _worker(db, llm, monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert len(llm.calls) == 1                # кандидат дошёл до модели
        user_text = llm.calls[0][0][1]["content"]
        assert "гитаре у костра" in user_text     # июнь 2024 предъявлен
        rows = await _log_rows(db)
        skip = [r for r in rows if r["status"] == "skipped"]
        assert skip
        meta = json.loads(skip[-1]["meta"])
        assert meta["reason"] == "unchanged"      # вердикт модели
        assert meta.get("mode") == "thematic"

    @pytest.mark.asyncio
    async def test_calendar_not_guaranteed_over_thematic(self, db,
                                                         monkeypatch):
        """NOST-06: при обоих режимах тематическая связь предъявляется выше
        календарной (технический порядок, финальное решение — модель)."""
        _worker_time(monkeypatch)
        # годовщина 2026: эпизод про «балет» (не о теме беседы)
        await _msg(db, "ходили всей толпой на балет",
                   _ts_local(2026, 1, 15, 12))
        # тематический эпизод 2024: «гитара» (вне годовщины)
        await _msg(db, "вася зажигал на гитаре у костра",
                   _ts_local(2024, 6, 10, 21))
        await _msg(db, "и второй куплет про гитару был",
                   _ts_local(2024, 6, 10, 21, 20))
        # беседа о гитаре
        await _msg(db, "давайте про гитару вспомним", NOW - 3600)
        await _msg(db, "кто там опять про гитару спрашивал", NOW - 600)
        llm = _FakeLLM("UNCHANGED")
        w = _worker(db, llm, monkeypatch=monkeypatch)
        await w._process_chat(CHAT_ID, NOW, manual=True)
        user_text = llm.calls[0][0][1]["content"]
        assert "гитаре у костра" in user_text
        assert "на балет" in user_text
        thematic_idx = user_text.find("гитаре у костра")
        calendar_idx = user_text.find("на балет")
        assert thematic_idx < calendar_idx        # тематическая выше
        rows = await _log_rows(db)
        sent_or_skip = [r for r in rows if r["status"] in
                        ("skipped", "sent")]
        meta = json.loads(sent_or_skip[-1]["meta"])
        assert meta.get("mode") == "mixed"

    @pytest.mark.asyncio
    async def test_thematic_select_then_detail_bounded(self, db,
                                                       monkeypatch):
        """NOST-11.1/11.2: поэтапность — семена по всей истории, детализация
        ограниченного числа перспективных периодов (≤_THEMATIC_DETAIL_MAX);
        сырой архив в LLM не идёт."""
        _worker_time(monkeypatch)
        # четыре разных периода о «гитаре» в разные годы
        for y, m, d in ((2023, 5, 4), (2024, 6, 10), (2025, 3, 2),
                        (2026, 8, 17)):
            await _msg(db, f"вася зажигал на гитаре ({y})",
                       _ts_local(y, m, d, 21))
            await _msg(db, f"и куплет про гитару ({y})",
                       _ts_local(y, m, d, 21, 20))
        await _msg(db, "давайте про гитару вспомним", NOW - 3600)
        await _msg(db, "кто там опять про гитару спрашивал", NOW - 600)
        w = _worker(db, monkeypatch=monkeypatch)
        context_rows, topic_words = await w._recent_context(CHAT_ID)
        episodes, error = await w._thematic_episodes(
            CHAT_ID, topic_words, NOW, context_rows)
        assert error is False
        assert 0 < len(episodes) <= nw._THEMATIC_DETAIL_MAX
        assert all(e.get("topical") for e in episodes)

    @pytest.mark.asyncio
    async def test_thematic_source_error_degrades_honestly(self, db,
                                                           monkeypatch):
        """NOST-11.4: недоступность тематического поиска не останавливает
        систему — календарный пул живёт, ошибка честно в meta."""
        _worker_time(monkeypatch)
        await _msg(db, "год назад ровно открыли офис",
                   _ts_local(2026, 1, 15, 12))
        await _msg(db, "в чате тоскливо", NOW - 30 * 3600)

        async def _boom(*a, **kw):
            raise RuntimeError("fts unavailable")
        monkeypatch.setattr(db, "search_messages_fts", _boom)
        llm = _FakeLLM("UNCHANGED")
        w = _worker(db, llm, monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert len(llm.calls) == 1                # календарный пул дошёл
        user_text = llm.calls[0][0][1]["content"]
        assert "открыли офис" in user_text
        rows = await _log_rows(db)
        skip = [r for r in rows if r["status"] == "skipped"]
        meta = json.loads(skip[-1]["meta"])
        assert meta.get("thematic_error") is True

    @pytest.mark.asyncio
    async def test_archive_bounds_error_honest(self, db, monkeypatch):
        """NOST-11.4/NOST-12: недоступность границ архива — честный
        archive_error в диагностике, без фиктивного «успеха»."""
        _worker_time(monkeypatch)
        await _msg(db, "в чате тоскливо", NOW - 30 * 3600)

        async def _boom(chat_id):
            raise RuntimeError("pg down")
        monkeypatch.setattr(db, "get_chat_history_bounds", _boom)
        llm = _FakeLLM("UNCHANGED")
        w = _worker(db, llm, monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert len(llm.calls) == 0
        rows = await _log_rows(db)
        assert rows and rows[-1]["kind"] == "none"
        meta = json.loads(rows[-1]["meta"])
        assert meta.get("archive_error") is True


# ═══ NOST-08: повторы и разнообразие ════════════════════════════════════════

class TestRepeatsAndDiversity:
    @pytest.mark.asyncio
    async def test_same_episode_not_republished(self, db, monkeypatch):
        """T/NOST-08.2: один и тот же эпизод не публикуется повторно —
        второй тик распознаёт повтор по ИДЕНТИЧНОСТИ (журнал отправки),
        причина repeat честно в логе; искусственной новизны нет."""
        _worker_time(monkeypatch)
        await _msg(db, "экспедиция нашла клад под мостом",
                   _ts_local(2026, 1, 15, 12))
        await _msg(db, "в чате тоскливо", NOW - 30 * 3600)
        llm = _FakeLLM("SAY\nа помните клад под мостом")
        bot = _FakeBot()
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 1 and bot.calls
        rows = await _log_rows(db)
        sent = [r for r in rows if r["status"] == "sent"]
        meta = json.loads(sent[-1]["meta"])
        assert meta.get("episode_ids"), "идентичности эпизодов в meta"

        # тик 2: cooldown прошёл, эпизод тот же → repeat
        later = NOW + 13 * 3600
        _worker_time(monkeypatch, later)
        llm2 = _FakeLLM("SAY\nснова про клад")
        bot2 = _FakeBot()
        w2 = _worker(db, llm2, monkeypatch=monkeypatch, bot=bot2)
        out2 = await w2._process_chat(CHAT_ID, later, manual=True)
        assert out2["sent"] == 0 and bot2.calls == []
        assert len(llm2.calls) == 0               # модель даже не звалась
        rows2 = await _log_rows(db)
        skip = [r for r in rows2 if r["status"] == "skipped"
                and r["ts"] >= later - 60]
        assert skip
        last = json.loads(skip[-1]["meta"])
        assert last["reason"] == "repeat"
        assert last.get("repeats_skipped", 0) >= 1

    @pytest.mark.asyncio
    async def test_old_told_episode_allowed_again(self, db, monkeypatch):
        """NOST-08.2: публикация ЗА окном «недавно» (30 дней) — не повтор:
        самостоятельный новый повод допускает повторный рассказ."""
        _worker_time(monkeypatch)
        await _msg(db, "экспедиция нашла клад под мостом",
                   _ts_local(2026, 1, 15, 12))
        await _msg(db, "в чате тоскливо", NOW - 30 * 3600)
        # старая публикация того же эпизода (meta — как пишет воркер)
        identity = {"first": "", "last": "",
                    "start_ts": int(_ts_local(2026, 1, 15, 12)),
                    "end_ts": int(_ts_local(2026, 1, 15, 12)),
                    "year": 2026}
        await db.log_nostalgia(
            CHAT_ID, NOW - 40 * 86400, kind="year_back", status="sent",
            meta=json.dumps({"episode_ids": [identity],
                             "reason": "sent"}))
        llm = _FakeLLM("SAY\nа помните клад под мостом")
        bot = _FakeBot()
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert len(llm.calls) == 1                # повтор не заблокирован

    @pytest.mark.asyncio
    async def test_diversity_across_ticks_no_quota(self, db, monkeypatch):
        """NOST-08.1: при сопоставимых кандидатах периоды меняются между
        тиками (свежий рассказал → следующий тик всплывает более старый) —
        без фиксированных квот на годы."""
        _worker_time(monkeypatch)
        await _msg(db, "экспедиция нашла клад под мостом",
                   _ts_local(2025, 1, 15, 12))
        await _msg(db, "квантовый физик выступал в клубе",
                   _ts_local(2026, 1, 15, 12))
        await _msg(db, "в чате тоскливо", NOW - 30 * 3600)
        # SAY 1 → выбран первый блок (свежий 2026); журнал получает
        # идентичность ТОЛЬКО выбранного эпизода (протокольный суффикс)
        llm = _FakeLLM("SAY 1\nа помните физика в клубе")
        bot = _FakeBot()
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 1
        first_text = bot.calls[0][1]
        rows = await _log_rows(db)
        sent = [r for r in rows if r["status"] == "sent"]
        meta = json.loads(sent[-1]["meta"])
        ids = meta.get("episode_ids") or []
        assert len(ids) == 1 and ids[0]["year"] == 2026   # выбран, не пул

        later = NOW + 13 * 3600
        _worker_time(monkeypatch, later)
        llm2 = _FakeLLM("SAY 1\nа клад под мостом помните")
        bot2 = _FakeBot()
        w2 = _worker(db, llm2, monkeypatch=monkeypatch, bot=bot2)
        out2 = await w2._process_chat(CHAT_ID, later, manual=True)
        assert out2["sent"] == 1
        assert "клад под мостом" in bot2.calls[0][1]
        assert first_text != bot2.calls[0][1]     # период сменился

    def test_identity_is_keys_not_text(self):
        """NOST-08.2: идентичность — ключи/границы, не текст. Пересказ
        другими словами (тот же ряд message_key) остаётся тем же эпизодом;
        другой год с тем же текстом — НЕ тот эпизод."""
        rows = [{"message_key": f"{CHAT_ID}:db:1",
                 "timestamp": 1000},
                {"message_key": f"{CHAT_ID}:db:2",
                 "timestamp": 2000}]
        ep = {"rows": rows, "start_ts": 1000, "end_ts": 2000, "year": 2025}
        ident = nw._episode_identity(ep)
        assert ident["first"].endswith(":db:1")
        assert ident["last"].endswith(":db:2")
        assert nw._same_episode(ep, dict(ident)) is True
        # пересказ другими словами: identity тот же → тот же эпизод
        assert nw._same_episode(ep, ident) is True
        # другой год, диапазоны не пересекаются → не тот эпизод
        other = {"rows": [], "start_ts": 3000, "end_ts": 4000, "year": 2026}
        assert nw._same_episode(other, ident) is False
        # другой год с пересекающимися ts → не тот эпизод (год разный)
        overlap_other_year = {"rows": [], "start_ts": 1500, "end_ts": 1800,
                              "year": 2026}
        assert nw._same_episode(overlap_other_year, ident) is False

    def test_say_slot_protocol_deterministic(self):
        """NOST-08.2: слот-суффикс вердикта — детерминированный протокольный
        маркер (не смысловой анализ): SAY/UNCHANGED/legacy совместимы."""
        from services.nostalgia_prompts import parse_nostalgia_answer, \
            parse_say_slot
        # SAY 2 / SAY #2 — say + слот
        assert parse_nostalgia_answer("SAY 2\nреплика") == ("say", "реплика")
        assert parse_nostalgia_answer("say #2\nреплика") == ("say", "реплика")
        assert parse_say_slot("SAY 2\nреплика") == 2
        assert parse_say_slot("say #2\nреплика") == 2
        # голый SAY — совместим, слота нет
        assert parse_nostalgia_answer("SAY\nреплика") == ("say", "реплика")
        assert parse_say_slot("SAY\nреплика") is None
        # UNCHANGED — отказ, слота нет
        assert parse_nostalgia_answer("UNCHANGED") == ("unchanged", "")
        assert parse_say_slot("UNCHANGED") is None
        # не-слоты не трактуются как SAY (не словесный матчинг)
        assert parse_nostalgia_answer("SAY 123\nx") == ("legacy", "SAY 123\nx")
        assert parse_nostalgia_answer("говорит 2\nx") == ("legacy",
                                                          "говорит 2\nx")
        assert parse_say_slot("SAY два") is None

    def test_episode_block_slot_marker(self):
        """NOST-08.2: блок эпизода с назначенным слотом нумеруется «№k»;
        без слота — прежний рендер без номера (совместимость)."""
        ep = {"slot": 2, "years_ago": 3, "start_ts": 0, "end_ts": 0,
              "lines": ["[Вася 2024-01-01]: текст"]}
        block = build_nostalgia_user([], [], episodes=[ep])
        assert "№2" in block
        ep2 = {"years_ago": 3, "start_ts": 0, "end_ts": 0,
               "lines": ["[Вася 2024-01-01]: текст"]}
        block2 = build_nostalgia_user([], [], episodes=[ep2])
        assert "№" not in block2


# ═══ NOST-11: большой архив ═════════════════════════════════════════════════

class TestBigArchive:
    @pytest.mark.asyncio
    async def test_dense_window_stratified_coverage(self, db, monkeypatch):
        """NOST-11.3: плотное окно (>лимита) не прижимается к голове
        периода — стратификация по времени покрывает весь период, truncated
        честен."""
        _worker_time(monkeypatch)
        monkeypatch.setattr(nw, "_WINDOW_FETCH_LIMIT", 4)
        for h in range(12):                       # 12 сообщений в течение дня
            await _msg(db, f"плотный день сообщение {h}",
                       _ts_local(2026, 1, 15, h * 2))
        w = _worker(db, monkeypatch=monkeypatch)
        seen: set = set()
        lo = int(_ts_local(2026, 1, 15, 0))
        hi = int(_ts_local(2026, 1, 16, 0))
        rows, truncated = await w._fetch_window_rows(
            CHAT_ID, (lo, hi), seen)
        assert truncated is True
        assert 4 <= len(rows) <= 4                # кап соблюдён
        ts = sorted(int(r["timestamp"]) for r in rows)
        # покрытие периода: головы страт разнесены по всему дню (4 страты
        # по 6 ч — крайние головы не ближе 16 ч друг к другу)
        assert ts[-1] - ts[0] >= 16 * 3600
        assert ts[0] <= _ts_local(2026, 1, 15, 4)
        assert ts[-1] >= _ts_local(2026, 1, 15, 16)

    @pytest.mark.asyncio
    async def test_sparse_window_unstratified(self, db, monkeypatch):
        """Разрежённое окно (≤лимита) — прежняя сплошная выборка, без
        страт (поведение W1 для обычных чатов не меняется)."""
        _worker_time(monkeypatch)
        for h in range(3):
            await _msg(db, f"разрежённый день {h}",
                       _ts_local(2026, 1, 15, 8 + h))
        w = _worker(db, monkeypatch=monkeypatch)
        seen: set = set()
        rows, truncated = await w._fetch_window_rows(
            CHAT_ID, (int(_ts_local(2026, 1, 15, 0)),
                      int(_ts_local(2026, 1, 16, 0))), seen)
        assert truncated is False
        assert len(rows) == 3


# ═══ NOST-12: глубина, диагностика, админка ═════════════════════════════════

class TestDepthAndDiagnostics:
    @pytest.mark.asyncio
    async def test_depth_knobs_limit_years(self, db, monkeypatch):
        """NOST-12: depth>0 ограничивает глубину последними N годами;
        depth=0 (дефолт) — весь доступный архив."""
        _worker_time(monkeypatch)
        for y in (2022, 2023, 2024, 2025, 2026):
            await _msg(db, f"январь {y} архив",
                       _ts_local(y, 1, 15, 12))
        await _msg(db, "в чате тоскливо", NOW - 30 * 3600)
        w = _worker(db, monkeypatch=monkeypatch)
        episodes = await w._calendar_episodes(CHAT_ID, NOW)
        assert sorted(e["year"] for e in episodes) == \
            [2022, 2023, 2024, 2025, 2026]
        assert w._pool_flags["calendar_years"] == \
            [2022, 2023, 2024, 2025, 2026]
        # ограничение: последние 2 года
        w2 = _worker(db, monkeypatch=monkeypatch,
                     values={"memory.nostalgia_enabled": True,
                             "memory.nostalgia_history_depth_years": 2})
        episodes2 = await w2._calendar_episodes(CHAT_ID, NOW)
        assert sorted(e["year"] for e in episodes2) == [2025, 2026]
        assert w2._pool_flags["calendar_years"] == [2025, 2026]

    @pytest.mark.asyncio
    async def test_run_diagnostics_meta_full(self, db, monkeypatch):
        """NOST-12: диагностика фактического прогона в nostalgia_log.meta —
        режим, найдено/показано, периоды, секции payload, episode_ids,
        идентичность для контроля повторов."""
        _worker_time(monkeypatch)
        await _msg(db, "экспедиция нашла клад под мостом",
                   _ts_local(2026, 1, 15, 12))
        await _msg(db, "в чате тоскливо", NOW - 30 * 3600)
        llm = _FakeLLM("SAY\nа помните клад под мостом")
        bot = _FakeBot()
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 1
        rows = await _log_rows(db)
        sent = [r for r in rows if r["status"] == "sent"]
        meta = json.loads(sent[-1]["meta"])
        assert meta.get("mode") == "calendar"
        assert meta.get("episodes_found") == 1
        assert meta.get("episodes_shown") == 1
        assert meta.get("periods", {}).get("years") == [2026]
        assert "episodes" in meta.get("payload_sections", [])
        assert meta.get("calendar_years") == [2026]
        ids = meta.get("episode_ids") or []
        assert ids and ids[0]["year"] == 2026 and ids[0]["first"]

    @pytest.mark.asyncio
    async def test_admin_knobs_present(self):
        """NOST-12: новые и прежние настройки раздела «Ностальгия» в
        каталоге админки (одна система конфигурации, без рестарта — hot)."""
        from services.param_catalog import REGISTRY
        legacy = ("NOSTALGIA_ENABLED", "NOSTALGIA_LAYER_A_ENABLED",
                  "NOSTALGIA_TICK_MINUTES", "NOSTALGIA_MIN_SILENCE_MINUTES",
                  "NOSTALGIA_QUIET_START_HOUR", "NOSTALGIA_QUIET_END_HOUR",
                  "NOSTALGIA_COOLDOWN_HOURS", "NOSTALGIA_PAUSE_HOURS",
                  "NOSTALGIA_UNANSWERED_MAX", "NOSTALGIA_MAX_PER_DAY",
                  "NOSTALGIA_GOLDEN_MIN_DAYS",
                  "NOSTALGIA_GOLDEN_MIN_IMPORTANCE",
                  "NOSTALGIA_LAYER_A_MAX_HINTS", "NOSTALGIA_HINT_MAX_CHARS",
                  "NOSTALGIA_YEAR_BACK_DAYS_WINDOW",
                  "NOSTALGIA_AGGRESSIVENESS", "NOSTALGIA_MAX_SEND_CHARS")
        for key in legacy:
            spec = REGISTRY.get(key)
            assert spec is not None, key
            assert spec.group == "memory_nostalgia", key
        depth = REGISTRY.get("NOSTALGIA_HISTORY_DEPTH_YEARS")
        assert depth is not None
        assert depth.group == "memory_nostalgia"
        assert depth.settings_field == "NOSTALGIA_HISTORY_DEPTH_YEARS"
        # дефолт: весь доступный архив (ограничение опционально)
        assert settings.NOSTALGIA_HISTORY_DEPTH_YEARS == 0

    @pytest.mark.asyncio
    async def test_max_send_chars_respected_honest(self, db, monkeypatch):
        """NOST-09.2: единственный слот длины — ПОЛЬЗОВАТЕЛЬСКАЯ настройка
        nostalgia_max_send_chars (скрытой квоты слов больше нет)."""
        _worker_time(monkeypatch)
        await _msg(db, "экспедиция нашла клад под мостом",
                   _ts_local(2026, 1, 15, 12))
        await _msg(db, "в чате тоскливо", NOW - 30 * 3600)
        long_text = "клад " * 200
        llm = _FakeLLM("SAY\n" + long_text)
        bot = _FakeBot()
        _hot_cache(monkeypatch, {"memory.nostalgia_enabled": True,
                                 "memory.nostalgia_max_send_chars": 100})
        w = nw.NostalgiaWorker(db, memory=None, store=None, llm=llm,
                               bot=bot, bot_id=BOT_ID)
        w._tz_name = settings.SUMMARY_TIMEZONE
        monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
        monkeypatch.setattr(nw, "_local_hour", lambda ts, tz=None: 12)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 1
        assert len(bot.calls[0][1]) <= 100

    @pytest.mark.asyncio
    async def test_system_prompt_has_no_hidden_quota(self, db,
                                                     monkeypatch):
        """NOST-09.2: системный промпт воркера не содержит скрытой квоты
        {max_words} ни в одном режиме композера."""
        _worker_time(monkeypatch)
        await _msg(db, "экспедиция нашла клад под мостом",
                   _ts_local(2026, 1, 15, 12))
        await _msg(db, "в чате тоскливо", NOW - 30 * 3600)
        llm = _FakeLLM("UNCHANGED")
        w = _worker(db, llm, monkeypatch=monkeypatch)
        await w._process_chat(CHAT_ID, NOW, manual=True)
        assert llm.calls
        system_text = llm.calls[0][0][0]["content"]
        assert "{max_words}" not in system_text


# ═══ NOST-10: существующий Decision/Initiative ══════════════════════════════

class TestDecisionRouting:
    def test_nostalgia_due_chain_contract_unchanged(self):
        """NOST-10: кандидат ностальгии выражается через СУЩЕСТВУЮЩИЙ
        контракт инициативы (trigger nostalgia_due разрешён в цепочке,
        кандидат несёт тот же trigger/source — второй маршрутизатор не
        создавался)."""
        from services import mca_intents as mi
        assert mi.chain_allowed(
            trigger_kind="nostalgia_due", new_human_event=False,
            new_result=False) is True
        cand = mi.candidate_from_trigger(
            trigger_kind="nostalgia_due", chat_id=CHAT_ID,
            source="nostalgia", prepared_text_ref="nostalgia:year_back",
            reason_code="default")
        assert cand is not None
        assert getattr(cand, "trigger_kind", "") == "nostalgia_due"

    @pytest.mark.asyncio
    async def test_delegation_single_send_path(self, db, monkeypatch):
        """NOST-10 (K1+K3 ON): готовая реплика делегируется в единый
        Decision/транспорт — параллельного send-пути нет; double-send
        исключён (маршрут-проверка моком)."""
        _worker_time(monkeypatch)
        await _msg(db, "экспедиция нашла клад под мостом",
                   _ts_local(2026, 1, 15, 12))
        await _msg(db, "в чате тоскливо", NOW - 30 * 3600)
        calls = {"initiative": 0, "bot": 0}

        async def _fake_handle_initiative(*, bot, chat_id, situation,
                                          candidates, prepared_text, db):
            calls["initiative"] += 1
            return {"status": "sent"}

        from services import mca_gates
        monkeypatch.setattr(mca_gates, "intents_enabled", lambda: True)
        monkeypatch.setattr(mca_gates, "intent_decision_enabled",
                            lambda: True)
        monkeypatch.setattr(
            "services.direct_chat_service.handle_initiative",
            _fake_handle_initiative)
        bot = _FakeBot()
        w = _worker(db, _FakeLLM("SAY\nа помните клад"),
                    monkeypatch=monkeypatch, bot=bot)
        orig_send = bot.send_message

        async def _count_send(chat_id, text):
            calls["bot"] += 1
            return await orig_send(chat_id, text)
        bot.send_message = _count_send
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 1
        assert calls == {"initiative": 1, "bot": 0}   # единый транспорт
        rows = await _log_rows(db)
        sent = [r for r in rows if r["status"] == "sent"]
        assert sent and json.loads(sent[-1]["meta"]).get("path") == \
            "initiative"


# ═══ NOST-15/16: свойства результата, инвариантность к фразам ═══════════════

class TestScenarioInvariants:
    @pytest.mark.asyncio
    async def test_rename_dates_subjects_invariant(self, db, monkeypatch):
        """NOST-16: смена имён/дат/предметов не меняет общую логику отбора
        (свойство маршрута, не совпадение подготовленных фраз)."""
        scenarios = [
            ("вася", "гитара", _ts_local(2025, 1, 15, 12),
             "давайте про гитару вспомним"),
            ("оля", "аквариум", _ts_local(2024, 1, 15, 12),
             "помнится про аквариум вопрос"),
        ]
        for name, topic, ts, burst in scenarios:
            d = DatabaseService(":memory:")
            await d.initialize()
            try:
                await _msg(d, f"{name} рассказывал про {topic}", ts,
                           name=name)
                await _msg(d, burst, NOW - 30 * 3600)
                monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
                monkeypatch.setattr(nw, "_local_hour",
                                    lambda t, tz=None: 12)
                w = _worker(d, monkeypatch=monkeypatch)
                candidate, info = await w._pick_candidate(CHAT_ID, NOW)
                assert candidate is not None, (name, topic)
                assert candidate["kind"] == "year_back"
                # календарный и тематический режимы нашли один и тот же
                # эпизод → дедуп: предъявлен один (mode=mixed/диагностика)
                assert info.get("episodes_shown") == 1
                assert len(candidate["episodes"]) == 1
            finally:
                await d.close()

    @pytest.mark.asyncio
    async def test_random_chatter_can_stay_silent(self, db, monkeypatch):
        """T19 (W2-грань): разрозненные случайные сообщения без связного
        эпизода на годовщину и без тематической связи — молчание (отказ
        нормальный исход; мок вердикта не нужен — кандидата нет)."""
        _worker_time(monkeypatch)
        await _msg(db, "случайная реплика про кофе", NOW - 40 * 3600)
        await _msg(db, "и ещё одна случайная про погоду", NOW - 39 * 3600)
        w = _worker(db, monkeypatch=monkeypatch)
        candidate, info = await w._pick_candidate(CHAT_ID, NOW)
        assert candidate is None
        assert info["reason"] == "no_candidates"
