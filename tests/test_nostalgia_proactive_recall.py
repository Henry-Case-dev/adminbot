"""Проактивная ностальгия (owner corrective 2026-11-10) — четыре сценария.

Владелец: ностальгия НЕ является историческим поиском по вопросу. Бот сам
замечает смысловую связь текущей темы/участников/событий с долговременной
памятью и может вспомнить эпизод прямо в живом разговоре, а также инициировать
воспоминание автономно. Слова-триггеры, словари тем и регулярные выражения
решением не являются; публикацию решает существующий механизм инициативы;
молчание — легальный исход.

Покрытие по свойствам результата (не по ожидаемым фразам):
* (a) живая дискуссия + реальный старый эпизод → воспоминание через
  СУЩЕСТВУЮЩИЙ Observer/Decision и Writer: текст собран из фактических
  сообщений БД, запись памяти указана в журнале;
* (b) автономный тик вспоминает без вопроса пользователя;
* (c) обычный вопрос о прошлом без ключевых слов находит релевантный ответ
  через существующий инструмент L1 (`dig_into_lore`) — пре-гейт не нужен;
* (d) нет подходящей связи → публикации нет;
* (e) повтор того же эпизода не публикуется; все процитированные источники
  реально существуют в БД (нет выдуманных связей);
* взвешенный отбор: релевантность важнее «свежего года», объём не участвует;
  квантовое направление (RandomSource) влияет только на порядок предъявления.

LLM/бот/транспорт замоканы: проверяется маршрут и источники, а не «качество
модели». TEST-LIFECYCLE: CONTRACT owner=nostalgia-proactive-2026-11-10
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from services import chat_params
from services import direct_chat_service as dcs
from services import hot_config
from services import initiative_observer as obs
from services import mca_events
from services import nostalgia_worker as nw
from services import semantic_schedule as sched
from services.database import DatabaseService
from services.mca_episodes import (
    EpisodeRepository,
    message_key,
    segment_key,
)

CHAT = -2701
BOT_ID = 999
USER = 42
YEAR = 365 * 24 * 3600


# ── инфраструктура ──────────────────────────────────────────────────────────


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeChatParams:
    def __init__(self, by_chat=None):
        self._by_chat = dict(by_chat or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}


def _caches(settings: dict | None = None):
    """Глобальные значения (hot) + чатовые overrides — один набор значений."""
    values = dict(settings or {})
    values.setdefault("flags.nostalgia_enabled", True)
    hot_config.set_config_cache(_FakeHot(values))
    chat_params.set_chat_params_cache(
        _FakeChatParams({CHAT: dict(settings or {})}))


def _reset_caches():
    hot_config.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


async def _observe_event(db, **kwargs):
    """QND-NONDET §2: живое сообщение будит Observer немедленно.

    Плановый тик исполняет только наступившие сроки, поэтому тест, чей предмет
    — обнаружение повода в ЖИВОМ разговоре, идёт событийным путём (тот же
    Observer, тот же Writer/Decision/SendRecheck).
    """
    await sched.request_event(db, chat_id=CHAT, reason="live_message",
                              dispatch=False)
    return await obs.observe_tick(db, trigger="event", only_chat=CHAT,
                                  **kwargs)


class _FakeBot:
    def __init__(self):
        self.id = BOT_ID
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((int(chat_id), str(text)))

        class _Msg:
            message_id = 9000 + len(self.sent)

        return _Msg()


class _FakeLLM:
    """Очередь ответов: сначала вердикт оценщика, затем ответ писателя."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.calls = 0
        self.prompts: list = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.prompts.append([dict(m) for m in messages])
        if self.answers:
            return self.answers.pop(0)
        return json.dumps({"opportunity": False})

    async def generate_worker(self, role, messages, **kwargs):
        return await self.generate(messages, **kwargs)


def _verdict(**kw) -> str:
    base = {"opportunity": True, "kind": "development", "action": "say",
            "horizon": "now", "addressee_user_id": None,
            "memory_slot": None, "topic_key": "tema",
            "goal": "участники вспоминают прошлое",
            "rationale": "есть смысловая связь"}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


def _limits(**kw) -> dict:
    base = {"initiative.frequency_profile": "active",
            "initiative.eval_min_messages": 4,
            "initiative.eval_min_interval_seconds": 0,
            "initiative.min_gap_seconds": 0,
            "initiative.max_replies_per_day": 10,
            "initiative.eval_llm_budget_per_day": 10,
            "memory.nostalgia_enabled": True}
    base.update(kw)
    return base


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    service = DatabaseService(":memory:")
    loop.run_until_complete(service.initialize())
    yield service
    loop.run_until_complete(service.close())
    loop.close()


@pytest.fixture(autouse=True)
def _clean():
    mca_events.reset_pending()
    _reset_caches()
    yield
    mca_events.reset_pending()
    _reset_caches()


async def _msg(service, text, ts, *, uid=USER, name="Вася", chat_id=CHAT) -> int:
    return await service.save_smart_message(
        uid, chat_id, text, None, int(ts), "text", name)


async def _archive_story(service, *, lines, start_ts, title, summary):
    """Реальный архив: сообщения + запись памяти (mca_episodes + mca_stories).

    Возврат (story_id, episode_id, ключи сообщений)."""
    ids = [await _msg(service, text, start_ts + i * 60)
           for i, text in enumerate(lines)]
    rows = []
    for mid in ids:
        cursor = await service.db.execute(
            "SELECT * FROM smart_messages WHERE id = ?", (mid,))
        rows.append(dict(await cursor.fetchone()))
    keys = [message_key(row) for row in rows]
    repo = EpisodeRepository(service)
    episode_id = await repo.insert_episode(
        chat_id=CHAT, title=title, summary=summary,
        participants=[str(USER)], claims=[],
        event_start=int(start_ts),
        event_end=int(start_ts) + (len(ids) - 1) * 60,
        outcome="", outcome_known=False, open_questions=[],
        message_keys=keys, seg_key=segment_key(keys),
        extraction_version="test-nostalgia", now=int(start_ts))
    story_id, _version, _created = await repo.upsert_story(
        chat_id=CHAT, title=title, summary=summary,
        participants=[str(USER)], claims=[],
        event_start=int(start_ts),
        event_end=int(start_ts) + (len(ids) - 1) * 60,
        outcome="", state="open", verification="tentative",
        open_questions=[], episode_ids=[episode_id],
        extractor_version="test-nostalgia", now=int(start_ts))
    return story_id, episode_id, keys


async def _nostalgia_log(service):
    cursor = await service.db.execute(
        "SELECT ts, kind, status, meta FROM nostalgia_log ORDER BY id")
    return [dict(r) for r in await cursor.fetchall()]


async def _all_messages(service, chat_id=CHAT) -> str:
    cursor = await service.db.execute(
        "SELECT text FROM smart_messages WHERE chat_id = ?", (chat_id,))
    return "\n".join(str(r["text"] or "") for r in await cursor.fetchall())


def _patch_transport(monkeypatch) -> dict:
    """Единый транспорт инициативы: перехватываем готовый текст (никаких
    отправок в реальный Telegram). Гейты K1/K3 включены, как на проде."""
    seen: dict = {"texts": [], "triggers": []}

    async def _fake_handle_initiative(*, bot, chat_id, situation, candidates,
                                      prepared_text, db, publish_guard=None):
        seen["texts"].append(prepared_text)
        seen["triggers"].append(getattr(situation, "trigger_kind", ""))
        return {"status": "sent"}

    from services import mca_gates
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "intent_decision_enabled", lambda: True)
    monkeypatch.setattr(dcs, "handle_initiative", _fake_handle_initiative)
    return seen


# ── (a) живая дискуссия: модель сама вспоминает реальный эпизод ──────────────


@pytest.mark.asyncio
async def test_in_conversation_recall_uses_real_memory_sources(db, monkeypatch):
    """Живая дискуссия + релевантный старый эпизод → воспоминание уходит
    через существующий единый транспорт, текст собран из реальных сообщений."""
    now = int(time.time())
    story_id, episode_id, _keys = await _archive_story(
        db, lines=["на даче пели под гитару у костра",
                   "гитара была расстроена, но пели всё равно"],
        start_ts=now - 2 * YEAR,
        title="Гитара у костра на даче",
        summary="пели под гитару у костра на даче")
    for i in range(6):
        await _msg(db, "а помните гитара и костёр на даче, %d" % i,
                   now - 120 + i)
    _caches(_limits())
    bot = _FakeBot()
    llm = _FakeLLM([
        _verdict(kind="memory_recall", memory_slot=1,
                 goal="уместно вспомнить гитару у костра"),
        "SAY\nа помните, как пели под гитару у костра на даче",
    ])
    seen = _patch_transport(monkeypatch)

    status = await _observe_event(db, bot=bot, writer_service=None, llm=llm)
    assert status in ("completed", "not_due", "running")
    # Воспоминание ушло единым транспортом и несёт текст писателя ностальгии.
    assert seen["texts"] == [
        "а помните, как пели под гитару у костра на даче"]
    # Текст опирается на реальные сообщения: источник существует в БД.
    archive = await _all_messages(db)
    assert "пели под гитару у костра" in archive
    # Промпт писателя содержал ФАКТИЧЕСКИЕ строки эпизода (источник — БД).
    writer_prompts = [p for p in llm.prompts
                      if "Эпизоды из истории чата" in p[-1]["content"]]
    assert writer_prompts, "писатель не получил эпизод из памяти"
    assert "гитара была расстроена" in writer_prompts[0][-1]["content"]
    # Журнал: запись памяти указана (контроль повторов и честная диагностика).
    rows = await _nostalgia_log(db)
    sent = [r for r in rows if r["status"] == "sent"]
    assert len(sent) == 1
    meta = json.loads(sent[0]["meta"])
    assert sent[0]["kind"] == "memory_recall"
    assert meta.get("memory_refs") == ["story:%s" % story_id]
    assert meta.get("episodes", [{}])[0].get("memory_ref") == \
        "story:%s" % story_id
    assert (meta.get("episode_ids") or [{}])[0].get("ref") == \
        "story:%s" % story_id


# ── (b) автономный тик: воспоминание без вопроса пользователя ───────────────


@pytest.mark.asyncio
async def test_autonomous_tick_recalls_without_user_question(db, monkeypatch):
    """Тишина в чате, никто ничего не спрашивал — тик сам вспоминает эпизод."""
    now = int(time.time())
    await _msg(db, "экспедиция нашла клад под старым мостом",
               now - YEAR - 3 * 3600)
    await _msg(db, "в чате давно тихо", now - 30 * 3600)
    _caches(_limits())
    monkeypatch.setattr(nw, "_now_ts", lambda: now)
    monkeypatch.setattr(nw, "_local_hour", lambda ts, tz=None: 12)
    bot = _FakeBot()
    llm = _FakeLLM(["SAY\nкстати, был же клад под мостом"])
    _patch_transport(monkeypatch)
    worker = nw.NostalgiaWorker(db, memory=None, store=None, llm=llm,
                                bot=bot, bot_id=BOT_ID)
    out = await worker._process_chat(CHAT, now, manual=False)
    assert out["candidates"] == 1 and out["sent"] == 1
    # Пользователь ничего не спрашивал: последнее сообщение — старое.
    last_ts = await db.get_last_user_message_ts(CHAT, BOT_ID)
    assert now - int(last_ts) >= 45 * 60


# ── (c) обычный вопрос о прошлом без ключевых слов (L1 → dig_into_lore) ─────


@pytest.mark.asyncio
async def test_past_question_without_markers_finds_relevant_answer(db):
    """Вопрос о прошлом без «помнишь/год назад/2024» получает релевантный
    ответ существующим инструментом L1 — пре-гейт для этого не нужен."""
    from services.tool_router import ToolContext, ToolDeps, ToolRouter
    from services.summary_memory import build_fts_query

    class _SearchMemory:
        """Тонкий адаптер к существующему FTS чата (как MemoryManager)."""

        def __init__(self, service):
            self._service = service

        async def search_long_term(self, chat_id, terms, limit, *,
                                   since_ts=0, until_ts=0, author_ids=None):
            words = [str(t) for t in (terms or ()) if str(t).strip()]
            match = build_fts_query(words)
            if not match:
                return []
            rows = await self._service.search_messages_fts(
                chat_id, match, limit, since_ts=since_ts, until_ts=until_ts,
                author_ids=author_ids, source_kind="any")
            return [dict(r) for r in rows]

    now = int(time.time())
    await _msg(db, "тогда мы весь вечер чинили старый велосипед",
               now - 2 * YEAR)
    router = ToolRouter(ToolDeps(search=None, memory=_SearchMemory(db),
                                 aliases=None, db=db))
    question = "чем мы занимались в тот вечер"
    ctx = ToolContext(CHAT, question, user_id=USER)
    raw = await router._dig_into_lore({"query": question,
                                       "mode": "messages"}, ctx)
    assert "велосипед" in raw                     # реальная строка из архива
    for marker in ("помнишь", "год назад", "2024", "раньше"):
        assert marker not in question


# ── (d) молчание: нет подходящей связи → нет публикации ─────────────────────


@pytest.mark.asyncio
async def test_no_relevant_link_keeps_silence(db, monkeypatch):
    """Воспоминание не выдумывается: записей памяти нет → публикации нет."""
    now = int(time.time())
    for i in range(6):
        await _msg(db, "случайная болтовня про кофе, %d" % i, now - 120 + i)
    _caches(_limits())
    bot = _FakeBot()
    llm = _FakeLLM([_verdict(kind="memory_recall", memory_slot=1)])
    worker = nw.NostalgiaWorker(db, memory=None, store=None, llm=llm,
                                bot=bot, bot_id=BOT_ID)
    result = await worker.recall_in_conversation(
        CHAT, memory_refs=(), context_rows=[])
    assert result["status"] == "skipped"
    assert result["reason_code"] == "no_relevant_memory"
    assert bot.sent == []
    assert llm.calls == 0                          # генерации не было вовсе
    assert await _nostalgia_log(db) == []
    # Тот же сценарий через общий Observer: вердикт «вспомнить» без реальной
    # записи памяти не публикует ничего.
    seen = _patch_transport(monkeypatch)
    observer_llm = _FakeLLM([_verdict(kind="memory_recall", memory_slot=1)])
    status = await obs.observe_tick(db, bot=bot, writer_service=None,
                                    llm=observer_llm)
    assert status in ("completed", "not_due", "running")
    assert seen["texts"] == []
    assert await _nostalgia_log(db) == []


# ── (e) повторов нет; источники реальные ────────────────────────────────────


@pytest.mark.asyncio
async def test_same_episode_not_repeated_and_sources_exist(db, monkeypatch):
    """Тот же эпизод второй раз не публикуется (журнал), все источники — в БД."""
    now = int(time.time())
    story_id, _episode_id, _keys = await _archive_story(
        db, lines=["гитара у костра на даче, пели до утра"],
        start_ts=now - 3 * YEAR,
        title="Гитара у костра на даче",
        summary="пели под гитару у костра на даче")
    await _msg(db, "снова про гитару у костра на даче", now - 60)
    _caches(_limits())
    monkeypatch.setattr(nw, "_now_ts", lambda: now)
    bot = _FakeBot()
    llm = _FakeLLM([
        "SAY\nа помните гитару у костра на даче",
        "SAY\nа помните гитару у костра на даче",
    ])
    seen = _patch_transport(monkeypatch)
    worker = nw.NostalgiaWorker(db, memory=None, store=None, llm=llm,
                                bot=bot, bot_id=BOT_ID)
    first = await worker.recall_in_conversation(
        CHAT, memory_refs=["story:%s" % story_id])
    assert first["status"] == "sent"
    second = await worker.recall_in_conversation(
        CHAT, memory_refs=["story:%s" % story_id])
    assert second["status"] == "skipped"
    assert len(seen["texts"]) == 1                 # повтора нет
    rows = await _nostalgia_log(db)
    sent = [r for r in rows if r["status"] == "sent"]
    assert len(sent) == 1
    meta = json.loads(sent[0]["meta"])
    cited = [str(line) for line in (meta.get("year_lines") or [])]
    assert cited
    archive = await _all_messages(db)
    for line in cited:
        body = line.split("]: ", 1)[-1]
        assert body in archive, body                # нет выдуманных источников


@pytest.mark.asyncio
async def test_legacy_lore_story_can_be_recalled(db, monkeypatch):
    """Legacy-история «Темы» (lore_stories) тоже используется как источник
    памяти: кандидат читается тем же каналом episode и реконструируется из
    реальных сообщений периода."""
    now = int(time.time())
    start = now - 2 * YEAR
    await _msg(db, "спорили про аквариум и рыбок весь вечер", start)
    await _msg(db, "аквариум починили только к утру", start + 120)
    await _msg(db, "снова про аквариум и рыбок", now - 60)
    await _msg(db, "рыбки в аквариуме уже плавают", now - 30)
    await db.upsert_lore_story(
        CHAT, "аквариум-рыбки", "Аквариум и рыбки",
        "вечер починки аквариума и рыбок", last_ts=start + 120)
    _caches(_limits())
    llm = _FakeLLM([
        _verdict(kind="memory_recall", memory_slot=1),
        "SAY\nа помните, как чинили аквариум",
    ])
    seen = _patch_transport(monkeypatch)
    await _observe_event(db, bot=_FakeBot(), writer_service=None, llm=llm)
    assert seen["texts"] == ["а помните, как чинили аквариум"]
    rows = await _nostalgia_log(db)
    sent = [r for r in rows if r["status"] == "sent"]
    assert len(sent) == 1
    meta = json.loads(sent[0]["meta"])
    assert (meta.get("memory_refs") or [""])[0].startswith("lore:")


# ── взвешенный отбор и квантовое направление ────────────────────────────────


def test_rank_prefers_relevance_over_recent_year():
    """Релевантная старая память выше нерелевантного свежего периода; объём
    сообщений в весе не участвует."""
    semantic_old = {"year": 2022, "relevance": 0.95, "topical": True,
                    "messages": 1}
    calendar_new = {"year": 2026, "topical": False, "messages": 500}
    ranked = nw._rank_episodes([calendar_new, semantic_old])
    assert ranked[0] is semantic_old
    assert ranked[0]["weight_score"] > ranked[1]["weight_score"]


def test_rank_covers_unseen_period():
    """Незвучавший период получает покрытие (разнообразие без квот)."""
    seen = {"year": 2025, "topical": False}
    unseen = {"year": 2024, "topical": False}
    ranked = nw._rank_episodes([seen, unseen], told_years={2025})
    assert ranked[0] is unseen                     # 2024 ещё не звучал


@pytest.mark.asyncio
async def test_direction_draw_picks_boundary_slot_only(db, monkeypatch):
    """Направление исследования решает ОДНО квантовое значение.

    QND-NONDET §6(a): «полоса равно допустимых» отменена — inverse-CDF по
    весам ВСЕХ кандидатов (`0.65*relevance + 0.2*coverage + 0.1*usage`).
    Достоверность воспоминания и обязанность публикации не затрагиваются:
    выбирается только, какой эпизод предъявить первым.
    """
    now = int(time.time())
    monkeypatch.setattr(nw, "_now_ts", lambda: now)
    worker = nw.NostalgiaWorker(db, memory=None, store=None,
                                llm=_FakeLLM(), bot=_FakeBot(), bot_id=BOT_ID)
    pool = [{"year": 2020 + i, "topical": False, "start_ts": i,
             "relevance": 0.1 + 0.1 * i} for i in range(6)]
    ordered = nw._rank_episodes(pool)

    class _Result:
        deferred = False
        reason = None
        source = "quantum"
        draw_id = "draw-1"

    class _Source:
        """Одно значение `u` → детерминированный inverse-CDF."""

        def __init__(self, value):
            self.value = value
            self.calls = []

        async def draw_probability(self, *, chat_id=None, purpose="",
                                   policy_version=None, probability=None):
            self.calls.append((chat_id, purpose))
            return type("R", (), {"deferred": False, "reason": None,
                                  "source": "quantum", "draw_id": "draw-1",
                                  "value": self.value})()

    from services import mca_exploration as me

    async def _allowed(db_, purpose, chat_id=None):
        return True, None

    monkeypatch.setattr(me, "exploration_allowed", _allowed)

    # u≈0 → самый «тяжёлый» кандидат (первый в порядке ранжирования).
    low = _Source(0.0)
    monkeypatch.setattr(me, "get_source", lambda db=None: low)
    info: dict = {}
    first = await worker._direction_pick(CHAT, ordered, info)
    assert first == 0
    assert info["direction"]["source"] == "quantum"
    assert info["direction"]["draw_id"] == "draw-1"
    assert info["direction"]["candidates"] == len(ordered)
    assert low.calls and low.calls[0][1] == me.PURPOSE_MEMORY_RECALL

    # u≈1 → последний в порядке (кумулятивный вес добегает до конца).
    high = _Source(0.999999)
    monkeypatch.setattr(me, "get_source", lambda db=None: high)
    info2: dict = {}
    last = await worker._direction_pick(CHAT, ordered, info2)
    assert last == len(ordered) - 1

    # Один кандидат — выбора нет, значение не тратится.
    single = _Source(0.5)
    monkeypatch.setattr(me, "get_source", lambda db=None: single)
    assert await worker._direction_pick(CHAT, ordered[:1], {}) is None
    assert single.calls == []
