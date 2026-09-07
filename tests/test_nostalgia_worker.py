"""Раунд 9 (AGI Memory, spec §3.5, T-827/E2, G3) — NostalgiaWorker (слой B).

Покрытие: гейты чата (не-группа/флаг/тишина/no_history/quiet hours/
cooldown/дневной лимит/Q14-стоп после 2 неотвеченных), кандидаты («год
назад» по диапазону timestamp; «золотые» по последней теме), порог
агрессивности (0.3 + aggr*0.5), 1 LLM-вызов и отправка (мок бота),
исходы лога sent/skipped/error (+unchanged/empty не тратят дневной лимит),
регистрация джоба только при флаге (run_once работает без флага),
PG down/store отсутствует → no-op. LLM/бот замоканы; часы/окна — подменой
nw._now_ts/_local_hour.
"""
import asyncio
import json
import time
from unittest.mock import MagicMock

import pytest

from services import hot_config as hot
from services import nostalgia_worker as nw
from services.database import DatabaseService
from services.nostalgia_prompts import NOSTALGIA_PROMPT
from services.summary_memory import MemoryManager

CHAT_ID = -1002661910336
BOT_ID = 12345
USER_ID = 55
NOW = int(time.time())


@pytest.fixture
def db():
    """In-memory SQLite (миграции v1..v8) — база для всех кейсов."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _hot_cache(monkeypatch, values: dict | None = None):
    """hot-кэш-заглушка (прецедент test_dream_worker): заданные ключи;
    отсутствующие — settings-дефолты (hot.get(key, default))."""
    class _FakeHotCache:
        def __init__(self, values):
            self._values = dict(values or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


class _FakeLLM:
    """Мок облачного LLMClient: очередь ответов (строка или исключение)."""

    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = []                     # [(messages, temperature), ...]

    async def generate(self, messages, temperature=None):
        self.calls.append((messages, temperature))
        if self._answers:
            answer = self._answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return "кстати, помню как тогда было"


class _FakeBot:
    """Мок aiogram Bot: send_message записывает вызовы; error — бросок."""

    def __init__(self, error=None):
        self.error = error
        self.calls = []                     # [(chat_id, text), ...]

    async def send_message(self, chat_id, text):
        if self.error is not None:
            raise self.error
        self.calls.append((int(chat_id), str(text)))
        return MagicMock(message_id=1)


class _FakeStore:
    """Мок ChatLoreStore.list_active_chat_ids (Q13)."""

    def __init__(self, chats=None, error=None):
        self.chats = list(chats or [])
        self.error = error

    async def list_active_chat_ids(self):
        if self.error is not None:
            raise self.error
        return list(self.chats)


def _worker(db, llm=None, *, values=None, monkeypatch=None, bot=None,
            store=None, memory=None):
    w = nw.NostalgiaWorker(
        db, memory=memory, store=store,
        llm=llm if llm is not None else _FakeLLM(),
        bot=bot if bot is not None else _FakeBot(),
        bot_id=BOT_ID)
    if values:
        _hot_cache(monkeypatch, values)
    else:
        # Раунд 10 (F-10 §6): см. test_dream_worker — глобальный флаг ON
        # для фоновых кейсов (иначе gates chain скинет чат при тике);
        # НЕ перезаписываем кэш, заданный до _worker.
        if getattr(hot, "_cache", None) is None:
            _hot_cache(monkeypatch, {"memory.nostalgia_enabled": True})
    return w


def _patch_time(monkeypatch, hour: int = 12):
    """Фиксация «сейчас» + не-quiet час (гейт quiet hours детерминирован)."""
    monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
    monkeypatch.setattr(nw, "_local_hour", lambda ts, tz=None: hour)


async def _add_user_msg(db, text, *, ts=None, uid=USER_ID, name="Вася"):
    """Юзерское сообщение чата (ts по умолчанию NOW — «тишины нет»)."""
    return await db.save_smart_message(
        uid, CHAT_ID, text, None, NOW if ts is None else int(ts),
        "text", name)


async def _add_fact(db, text, *, days_ago=400, importance=7):
    """Факт чата: старый (message_timestamp = NOW - days_ago), важный —
    «золотой»-кандидат по SQL-фильтру fetch_golden_facts."""
    return await db.insert_graph_fact(
        CHAT_ID, text, "chat_history", None,
        importance=importance,
        message_timestamp=NOW - int(days_ago) * 86400)


async def _log_rows(db, status=None):
    """Строки nostalgia_log (id ASC)."""
    sql = "SELECT id, chat_id, ts, kind, fact_id, status, meta " \
          "FROM nostalgia_log"
    params = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY id"
    cur = await db.db.execute(sql, params)
    return await cur.fetchall()


async def _sent_count(db):
    return await db.count_nostalgia_sent_since(CHAT_ID, 0)


class TestGates:
    @pytest.mark.asyncio
    async def test_chat_must_be_group(self, db, monkeypatch):
        _patch_time(monkeypatch)
        w = _worker(db, monkeypatch=monkeypatch)
        out = await w._process_chat(100500, NOW, manual=True)
        assert out == {"candidates": 0, "sent": 0, "skipped": 0,
                       "errors": 0}
        assert await _log_rows(db) == []

    @pytest.mark.asyncio
    async def test_flag_off_job_not_registered_and_run_once_skipped(
            self, db, monkeypatch):
        """ФИКС R5 (F-10 §6): флаг/гейт off → джоб не регистрируется И
        ручной run_once теперь скипается (kill-switch стопит ручные
        запуски; carve-out удалён)."""
        _patch_time(monkeypatch)
        _hot_cache(monkeypatch, {"memory.nostalgia_enabled": False})
        await _add_user_msg(db, "давно молчим", ts=NOW - 3 * 3600)
        await _add_user_msg(db, "год назад было весело",
                            ts=NOW - 365 * 86400 + 3000)
        llm = _FakeLLM("кстати, вася, помню как ты тогда выступал")
        w = _worker(db, llm, monkeypatch=monkeypatch)
        w.start()
        assert w._scheduler.get_jobs() == []
        assert w._scheduler.running is False
        result = await w.run_once(CHAT_ID)
        assert result["sent"] == 0                  # gate nostalgia → skip
        assert llm.calls == []
        rows = await _log_rows(db)
        assert not any(r["status"] == "sent" for r in rows)

    @pytest.mark.asyncio
    async def test_silence_too_short_skip(self, db, monkeypatch):
        _patch_time(monkeypatch)
        await _add_user_msg(db, "только что писали", ts=NOW - 60 * 10)
        w = _worker(db, monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 0 and out["errors"] == 0
        assert await _log_rows(db) == []    # дешёвый скип — без строк

    @pytest.mark.asyncio
    async def test_no_history_skip(self, db, monkeypatch):
        _patch_time(monkeypatch)
        w = _worker(db, monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 0
        assert await _log_rows(db) == []

    @pytest.mark.asyncio
    async def test_quiet_hours_skip(self, db, monkeypatch):
        _patch_time(monkeypatch, hour=23)   # >= quiet_start (23)
        await _add_user_msg(db, "тихо уже сутки", ts=NOW - 26 * 3600)
        await _add_user_msg(db, "год назад текст",
                            ts=NOW - 365 * 86400 + 3000)
        w = _worker(db, monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 0
        assert await _log_rows(db) == []

    @pytest.mark.asyncio
    async def test_quiet_hours_morning_skip(self, db, monkeypatch):
        _patch_time(monkeypatch, hour=3)    # < quiet_end (8)
        await _add_user_msg(db, "тихо", ts=NOW - 26 * 3600)
        w = _worker(db, monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 0

    @pytest.mark.asyncio
    async def test_cooldown_skip(self, db, monkeypatch):
        _patch_time(monkeypatch)
        await _add_user_msg(db, "тихо", ts=NOW - 30 * 3600)
        await db.log_nostalgia(CHAT_ID, NOW - 3600, kind="year_back",
                               status="sent",
                               meta=json.dumps({"reason": "sent"}))
        w = _worker(db, monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 0
        assert len(await _log_rows(db)) == 1    # новой строки нет

    @pytest.mark.asyncio
    async def test_max_per_day_skip(self, db, monkeypatch):
        _patch_time(monkeypatch)
        await _add_user_msg(db, "тихо", ts=NOW - 30 * 3600)
        for i in range(3):                      # лимит 3 достигнут
            await db.log_nostalgia(CHAT_ID, NOW - (i + 1) * 3600,
                                   kind="year_back", status="sent",
                                   meta=json.dumps({"reason": "sent"}))
        w = _worker(db, monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 0
        assert await _sent_count(db) == 3

    @pytest.mark.asyncio
    async def test_unanswered_two_sent_stop(self, db, monkeypatch):
        _patch_time(monkeypatch)
        # юзер писал 30 часов назад (тишина ок), но ПОСЛЕ sent — ни разу
        await _add_user_msg(db, "тихо", ts=NOW - 30 * 3600)
        await db.log_nostalgia(CHAT_ID, NOW - 23 * 3600, kind="golden",
                               status="sent", meta=json.dumps({"a": 1}))
        await db.log_nostalgia(CHAT_ID, NOW - 21 * 3600, kind="golden",
                               status="sent", meta=json.dumps({"a": 2}))
        w = _worker(db, monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 0 and out["errors"] == 0
        assert len(await _log_rows(db)) == 2    # skip без новых строк
        assert w.bot.calls == []

    @pytest.mark.asyncio
    async def test_unanswered_resolved_by_user_message(self, db,
                                                       monkeypatch):
        _patch_time(monkeypatch)
        # последний sent отвечен (юзер писал после него)
        await _add_user_msg(db, "ответил после первого",
                            ts=NOW - 20 * 3600)
        await db.log_nostalgia(CHAT_ID, NOW - 23 * 3600, kind="golden",
                               status="sent", meta=json.dumps({"a": 1}))
        await db.log_nostalgia(CHAT_ID, NOW - 21 * 3600, kind="golden",
                               status="sent", meta=json.dumps({"a": 2}))
        # + кандидат «год назад», чтобы тик дошёл до отправки
        await _add_user_msg(db, "год назад текст про поездку",
                            ts=NOW - 365 * 86400 + 3000)
        llm = _FakeLLM("кстати, вася, помню ту поездку")
        bot = _FakeBot()
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 1
        assert len(bot.calls) == 1
        assert bot.calls[0][0] == CHAT_ID

    @pytest.mark.asyncio
    async def test_store_none_tick_noop(self, db, monkeypatch):
        _patch_time(monkeypatch)
        w = _worker(db, monkeypatch=monkeypatch, store=None)
        stats = await w._run(manual=False)
        assert stats["chats"] == 0 and stats["sent"] == 0

    @pytest.mark.asyncio
    async def test_pg_down_tick_noop(self, db, monkeypatch):
        _patch_time(monkeypatch)
        store = _FakeStore(error=RuntimeError("pg down"))
        w = _worker(db, monkeypatch=monkeypatch, store=store)
        stats = await w._run(manual=False)
        assert stats["chats"] == 0 and stats["sent"] == 0

    @pytest.mark.asyncio
    async def test_no_active_chats_tick_noop(self, db, monkeypatch):
        _patch_time(monkeypatch)
        store = _FakeStore(chats=[])
        w = _worker(db, monkeypatch=monkeypatch, store=store)
        stats = await w._run(manual=False)
        assert stats["chats"] == 0


class TestCandidatesAndThreshold:
    async def _quiet_then_year_back(self, db):
        await _add_user_msg(db, "в чате тишина", ts=NOW - 30 * 3600)
        await _add_user_msg(db, "год назад был жаркий спор",
                            ts=NOW - 365 * 86400 + 1000)
        await _add_user_msg(db, "и ещё запомнилась поездка",
                            ts=NOW - 365 * 86400 - 80000)

    @pytest.mark.asyncio
    async def test_year_back_candidate_sent(self, db, monkeypatch):
        _patch_time(monkeypatch)
        await self._quiet_then_year_back(db)
        bot = _FakeBot()
        w = _worker(db, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["candidates"] == 1 and out["sent"] == 1
        rows = await _log_rows(db)
        assert len(rows) == 1
        assert rows[0]["status"] == "sent"
        assert rows[0]["kind"] == "year_back"
        assert rows[0]["ts"] == NOW
        assert rows[0]["fact_id"] is None
        meta = json.loads(rows[0]["meta"])
        assert meta["candidate"] == "year_back"
        assert "год назад" in meta["candidate_text"]
        # дневной лимит потрачен (sent)
        assert await _sent_count(db) == 1

    @pytest.mark.asyncio
    async def test_golden_candidate_sent(self, db, monkeypatch):
        _patch_time(monkeypatch)
        # тишина: последние юзерские сообщения — по теме («золотой»-поиск)
        await _add_user_msg(db, "опять василий переезд обсуждают",
                            ts=NOW - 5 * 3600)
        await _add_user_msg(db, "переезд в москву долгий был",
                            ts=NOW - 4 * 3600)
        await db.log_nostalgia(CHAT_ID, NOW - 90 * 3600, kind="year_back",
                               status="skipped",
                               meta=json.dumps({"reason": "threshold"}))
        # «золотой»: старше 60 дней, важность 6 (вес 0.3+0.3=0.6 ≥ 0.45)
        fact_id = await _add_fact(
            db, "василий переезд в москву занял месяц",
            days_ago=400, importance=6)
        memory = MemoryManager(db, MagicMock())
        bot = _FakeBot()
        w = _worker(db, monkeypatch=monkeypatch, bot=bot, memory=memory)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["candidates"] == 1 and out["sent"] == 1
        rows = [r for r in await _log_rows(db) if r["status"] == "sent"]
        assert len(rows) == 1
        assert rows[0]["kind"] == "golden"
        assert rows[0]["fact_id"] == fact_id
        meta = json.loads(rows[0]["meta"])
        assert "переезд" in meta["candidate_text"]
        assert bot.calls and bot.calls[0][0] == CHAT_ID

    @pytest.mark.asyncio
    async def test_golden_fact_weak_importance_no_candidate(
            self, db, monkeypatch):
        _patch_time(monkeypatch)
        await _add_user_msg(db, "василий и его дела", ts=NOW - 3 * 3600)
        # важность 2 < порога 5 → fetch_golden_facts не вернёт (не «золотой»)
        await _add_fact(db, "василий ездил на выходные за город",
                        days_ago=400, importance=2)
        memory = MemoryManager(db, MagicMock())
        w = _worker(db, monkeypatch=monkeypatch, memory=memory)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        rows = await _log_rows(db)
        assert out["sent"] == 0
        # кандидатов нет → kind='none' reason=no_candidates
        assert len(rows) == 1
        assert rows[0]["kind"] == "none"
        assert json.loads(rows[0]["meta"])["reason"] == "no_candidates"

    @pytest.mark.asyncio
    async def test_aggressiveness_raises_threshold(self, db, monkeypatch):
        _patch_time(monkeypatch)
        _hot_cache(monkeypatch, {"memory.nostalgia_aggressiveness": 1.0,
                                 "memory.nostalgia_enabled": True})
        await _add_user_msg(db, "тишина", ts=NOW - 30 * 3600)
        await _add_user_msg(db, "год назад текст для кандидата",
                            ts=NOW - 365 * 86400 + 3000)
        llm = _FakeLLM("кстати...")
        bot = _FakeBot()
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        # порог 0.3+0.5=0.8 > вес «год назад» 0.7 → threshold-skip
        assert out["candidates"] == 1 and out["sent"] == 0
        assert bot.calls == []
        rows = await _log_rows(db)
        assert len(rows) == 1
        meta = json.loads(rows[0]["meta"])
        assert meta["reason"] == "threshold"
        assert rows[0]["kind"] == "year_back"

    @pytest.mark.asyncio
    async def test_no_candidates_anywhere_logged_none(self, db,
                                                      monkeypatch):
        _patch_time(monkeypatch)
        await _add_user_msg(db, "просто тихо", ts=NOW - 30 * 3600)
        w = _worker(db, monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["candidates"] == 0 and out["sent"] == 0
        rows = await _log_rows(db)
        assert len(rows) == 1
        assert rows[0]["kind"] == "none"
        assert rows[0]["status"] == "skipped"
        assert json.loads(rows[0]["meta"])["reason"] == "no_candidates"


class TestLLMAndSend:
    async def _candidate_setup(self, db):
        await _add_user_msg(db, "тишина в чате", ts=NOW - 30 * 3600)
        await _add_user_msg(db, "год назад пили чай у вас дома",
                            ts=NOW - 365 * 86400 + 3000)

    @pytest.mark.asyncio
    async def test_unchanged_skips_no_daily_spend(self, db, monkeypatch):
        _patch_time(monkeypatch)
        await self._candidate_setup(db)
        llm = _FakeLLM("  unchanged \n")
        bot = _FakeBot()
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 0 and out["skipped"] == 1
        assert bot.calls == []
        rows = await _log_rows(db)
        assert len(rows) == 1
        assert rows[0]["status"] == "skipped"
        meta = json.loads(rows[0]["meta"])
        assert meta["reason"] == "unchanged"
        assert meta.get("llm_skipped") is True
        assert await _sent_count(db) == 0   # лимит дня НЕ потрачен

    @pytest.mark.asyncio
    async def test_empty_llm_text_skips(self, db, monkeypatch):
        _patch_time(monkeypatch)
        await self._candidate_setup(db)
        llm = _FakeLLM("   ")
        bot = _FakeBot()
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 0 and out["skipped"] == 1
        assert bot.calls == []
        assert json.loads((await _log_rows(db))[0]["meta"])["reason"] == \
            "empty"

    @pytest.mark.asyncio
    async def test_send_failure_logs_error(self, db, monkeypatch):
        _patch_time(monkeypatch)
        await self._candidate_setup(db)
        llm = _FakeLLM("кстати, помню чай у вас")
        bot = _FakeBot(error=RuntimeError("chat kicked bot"))
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 0 and out["errors"] == 1
        rows = await _log_rows(db)
        assert len(rows) == 1
        assert rows[0]["status"] == "error"
        assert json.loads(rows[0]["meta"])["reason"] == "bot_api"

    @pytest.mark.asyncio
    async def test_llm_error_logs_error(self, db, monkeypatch):
        _patch_time(monkeypatch)
        await self._candidate_setup(db)
        llm = _FakeLLM(RuntimeError("upstream down"))
        bot = _FakeBot()
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["errors"] == 1 and out["sent"] == 0
        assert bot.calls == []
        rows = await _log_rows(db)
        assert rows[0]["status"] == "error"
        assert json.loads(rows[0]["meta"])["reason"] == "llm_error"

    @pytest.mark.asyncio
    async def test_send_text_capped_at_max_send_chars(self, db,
                                                      monkeypatch):
        _patch_time(monkeypatch)
        _hot_cache(monkeypatch, {"memory.nostalgia_max_send_chars": 40,
                                 "memory.nostalgia_enabled": True})
        await self._candidate_setup(db)
        llm = _FakeLLM("слово " * 100)
        bot = _FakeBot()
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert out["sent"] == 1
        assert len(bot.calls[0][1]) <= 40

    @pytest.mark.asyncio
    async def test_one_llm_call_one_send(self, db, monkeypatch):
        _patch_time(monkeypatch)
        await self._candidate_setup(db)
        llm = _FakeLLM()
        bot = _FakeBot()
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        await w._process_chat(CHAT_ID, NOW, manual=True)
        assert len(llm.calls) == 1          # максимум 1 LLM-вызов на чат
        assert len(bot.calls) == 1          # и 1 отправка
        assert bot.calls[0][0] == CHAT_ID


class TestTickFlow:
    @pytest.mark.asyncio
    async def test_tick_processes_store_chats(self, db, monkeypatch):
        _patch_time(monkeypatch)
        _hot_cache(monkeypatch, {"memory.nostalgia_enabled": True})
        await _add_user_msg(db, "тишина", ts=NOW - 30 * 3600)
        await _add_user_msg(db, "год назад был матч",
                            ts=NOW - 365 * 86400 + 3000)
        store = _FakeStore(chats=[CHAT_ID, -1002222])
        bot = _FakeBot()
        w = _worker(db, monkeypatch=monkeypatch, store=store, bot=bot)
        stats = await w._run(manual=False)
        assert stats["chats"] == 2
        assert stats["sent"] == 1           # второй чат пуст — кандидатов нет
        assert len(bot.calls) == 1
