"""P0 follow-up (§2, снапшот владельца 18.10.2026) — Nostalgia: A/B и hot-включение.

Контракты слайса NOSTALGIA-FIX:
  * REGRESSION: джоб `nostalgia_tick` регистрируется даже при старте с OFF —
    hot-включение `memory.nostalgia_enabled` поднимает ностальгию без
    рестарта бота (OFF → дешёвый no-op тика, kill-switch держит run_once);
  * CONTRACT (сценарий A — контекстное воспоминание в активной беседе):
    последнее юзерское сообщение свежее окна тишины → гейт 45-мин тишины и
    quiet hours не применяются; воронка наблюдение→кандидат→порог→LLM→
    отправка работает целиком;
  * CONTRACT (сценарий B — автономное после затишья): тишина/quiet hours
    действуют как раньше;
  * CONTRACT: отказы воронки честны (no_candidates / unchanged) — строка
    nostalgia_log с причиной, без отправки;
  * CONTRACT: кандидат делегируется в ЕДИНЫЙ Decision/транспорт различимым
    источником (source=nostalgia, trigger_kind=nostalgia_due, ref nostalgia:*).

TEST-LIFECYCLE: REGRESSION owner=p0-followup/NOSTALGIA-FIX (job registration)
TEST-LIFECYCLE: CONTRACT owner=p0-followup/NOSTALGIA-FIX (A/B split)
"""
import json
import time
from unittest.mock import MagicMock

import pytest

from services import hot_config as hot
from services import nostalgia_worker as nw
from services.database import DatabaseService

CHAT_ID = -1002661910336
BOT_ID = 12345
USER_ID = 55
NOW = int(time.time())


@pytest.fixture
def db():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class _MutableHot:
    """hot-кэш-заглушка с изменяемыми значениями (hot-включение в тесте)."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeLLM:
    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = []

    async def generate(self, messages, temperature=None):
        self.calls.append((messages, temperature))
        if self._answers:
            answer = self._answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return "кстати, помню как тогда было"


class _FakeBot:
    def __init__(self, error=None):
        self.id = BOT_ID
        self.error = error
        self.calls = []

    async def send_message(self, chat_id, text, **kwargs):
        if self.error is not None:
            raise self.error
        self.calls.append((int(chat_id), str(text)))
        return MagicMock(message_id=1)


class _FakeStore:
    def __init__(self, chats=None, error=None):
        self.chats = list(chats or [])
        self.error = error

    async def list_active_chat_ids(self):
        if self.error is not None:
            raise self.error
        return list(self.chats)


def _patch_time(monkeypatch, hour: int = 12):
    monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
    monkeypatch.setattr(nw, "_local_hour", lambda ts, tz=None: hour)


def _legacy_send(monkeypatch):
    """Детерминированная legacy-ветка отправки (без общего Decision)."""
    monkeypatch.setattr(nw, "_intent_delegation_enabled", lambda: False)


def _worker(db, llm=None, *, monkeypatch=None, bot=None, store=None,
            memory=None, values=None):
    if values is not None:
        monkeypatch.setattr(hot, "_cache", _MutableHot(values))
    elif getattr(hot, "_cache", None) is None:
        monkeypatch.setattr(
            hot, "_cache", _MutableHot({"memory.nostalgia_enabled": True}))
    return nw.NostalgiaWorker(
        db, memory=memory, store=store,
        llm=llm if llm is not None else _FakeLLM(),
        bot=bot if bot is not None else _FakeBot(), bot_id=BOT_ID)


async def _add_user_msg(db, text, *, ts=None, uid=USER_ID, name="Вася"):
    return await db.save_smart_message(
        uid, CHAT_ID, text, None, NOW if ts is None else int(ts),
        "text", name)


async def _log_rows(db, status=None):
    sql = ("SELECT id, chat_id, ts, kind, fact_id, status, meta "
           "FROM nostalgia_log")
    params = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY id"
    cur = await db.db.execute(sql, params)
    return await cur.fetchall()


def _user_message(llm, index=0) -> str:
    messages = llm.calls[index][0]
    return next(m["content"] for m in messages if m["role"] == "user")


class TestHotEnable:
    @pytest.mark.asyncio
    async def test_job_registered_at_off_start_and_hot_enable_works(
            self, db, monkeypatch):
        """OFF на старте → джоб всё равно есть; hot-включение без рестарта."""
        _patch_time(monkeypatch)
        _legacy_send(monkeypatch)
        h = _MutableHot({"memory.nostalgia_enabled": False})
        monkeypatch.setattr(hot, "_cache", h)
        await _add_user_msg(db, "живая беседа прямо сейчас", ts=NOW - 300)
        await _add_user_msg(db, "год назад ездили в сочи",
                            ts=NOW - 365 * 86400 + 2000)
        bot, llm = _FakeBot(), _FakeLLM("кстати, помню сочи")
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot,
                    store=_FakeStore(chats=[CHAT_ID]))
        w.start()
        try:
            ids = [j.id for j in w._scheduler.get_jobs()]
            assert ids == [w.JOB_NOSTALGIA_ID]      # регистрация не зависит
            stats = await w._run(manual=False)      # от старт-значения флага
            assert stats["sent"] == 0 and bot.calls == []
            assert await _log_rows(db) == []        # OFF → дешёвый no-op
            result = await w.run_once(CHAT_ID)      # kill-switch держит ручные
            assert result["sent"] == 0 and llm.calls == []
            h.values["memory.nostalgia_enabled"] = True   # hot-включение
            stats = await w._run(manual=False)      # без рестарта бота
            assert stats["chats"] == 1 and stats["sent"] == 1
            assert bot.calls == [(CHAT_ID, "кстати, помню сочи")]
        finally:
            await w.stop()


class TestScenarioA:
    """Активная беседа: без 45-мин тишины и без quiet hours."""

    @pytest.mark.asyncio
    async def test_active_chat_sends_without_silence(self, db, monkeypatch):
        _patch_time(monkeypatch)
        _legacy_send(monkeypatch)
        await _add_user_msg(db, "сейчас обсуждаем отпуск", ts=NOW - 300)
        await _add_user_msg(db, "год назад ездили в сочи",
                            ts=NOW - 365 * 86400 + 3000)
        bot, llm = _FakeBot(), _FakeLLM("кстати, помню сочи")
        w = _worker(db, llm, monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=False)
        assert out["candidates"] == 1 and out["sent"] == 1
        assert bot.calls == [(CHAT_ID, "кстати, помню сочи")]
        rows = await _log_rows(db)
        assert [(r["status"], r["kind"]) for r in rows] == [("sent", "year_back")]
        user = _user_message(llm)
        assert "В чате сейчас живая беседа" in user
        assert "В чате давно тихо" not in user

    @pytest.mark.asyncio
    async def test_active_chat_ignores_quiet_hours(self, db, monkeypatch):
        _patch_time(monkeypatch, hour=23)          # quiet_start=23
        _legacy_send(monkeypatch)
        await _add_user_msg(db, "ночью тоже болтаем", ts=NOW - 300)
        await _add_user_msg(db, "год назад был спор",
                            ts=NOW - 365 * 86400 + 1000)
        bot = _FakeBot()
        w = _worker(db, _FakeLLM("кстати, помню спор"),
                    monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=False)
        assert out["sent"] == 1
        assert len(bot.calls) == 1

    @pytest.mark.asyncio
    async def test_scenario_b_quiet_hours_still_skip(self, db, monkeypatch):
        """Контроль: затишье (B) — quiet hours действуют как раньше."""
        _patch_time(monkeypatch, hour=23)
        _legacy_send(monkeypatch)
        await _add_user_msg(db, "тихо уже сутки", ts=NOW - 26 * 3600)
        await _add_user_msg(db, "год назад текст",
                            ts=NOW - 365 * 86400 + 1000)
        bot = _FakeBot()
        w = _worker(db, _FakeLLM("кстати"), monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=False)
        assert out["sent"] == 0 and bot.calls == []
        assert await _log_rows(db) == []

    @pytest.mark.asyncio
    async def test_active_chat_no_candidates_reason(self, db, monkeypatch):
        """Отказ воронки: кандидатов нет → строка skipped/no_candidates."""
        _patch_time(monkeypatch)
        _legacy_send(monkeypatch)
        await _add_user_msg(db, "просто болтаем", ts=NOW - 300)
        w = _worker(db, monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=False)
        assert out["candidates"] == 0 and out["sent"] == 0
        rows = await _log_rows(db)
        assert len(rows) == 1 and rows[0]["status"] == "skipped"
        assert json.loads(rows[0]["meta"])["reason"] == "no_candidates"

    @pytest.mark.asyncio
    async def test_active_chat_llm_unchanged_reason(self, db, monkeypatch):
        """Отказ воронки: LLM UNCHANGED → skipped/unchanged, без отправки."""
        _patch_time(monkeypatch)
        _legacy_send(monkeypatch)
        await _add_user_msg(db, "нынешняя тема", ts=NOW - 300)
        await _add_user_msg(db, "год назад текст про поездку",
                            ts=NOW - 365 * 86400 + 3000)
        bot = _FakeBot()
        w = _worker(db, _FakeLLM("UNCHANGED"), monkeypatch=monkeypatch, bot=bot)
        out = await w._process_chat(CHAT_ID, NOW, manual=False)
        assert out["sent"] == 0 and bot.calls == []
        rows = await _log_rows(db)
        assert len(rows) == 1 and rows[0]["status"] == "skipped"
        assert json.loads(rows[0]["meta"])["reason"] == "unchanged"


class TestPromptCoreCoexistence:
    """P0-followup (§2): активный промпт Nostalgia не конкурирует с SOUL-1."""

    @pytest.mark.asyncio
    async def test_composer_on_system_has_core_without_legacy_persona(
            self, monkeypatch):
        from services import chat_params, prompt_composer as pc
        from services import mca_authorial_speech as au

        core = "ТЫ — ХАРАКТЕР ВЛАДЕЛЬЦА."

        class _Hot:
            def __init__(self, values=None):
                self.values = dict(values or {})

            def get(self, key, default=None):
                return self.values.get(key, default)

            def set(self, key, value):
                return None

            def set_many(self, items):
                return None

        class _Chat:
            async def get_chat_params(self, chat_id):
                return {"overrides": {}}

            async def get_chat_params_full(self, chat_id):
                return await self.get_chat_params(chat_id), None

        class _Store:
            async def get_profile(self, chat_id):
                class _P:
                    manual_lore = ""
                    auto_lore = ""
                return _P()

        class _Db:
            async def list_chat_memes(self, chat_id, ts, limit=10):
                return []

        monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
        monkeypatch.setattr(hot, "_cache", _Hot({
            "memory.nostalgia_enabled": True,
            "flags.unified_composer_enabled": True,
            "character.core": {"revision": 3, "enabled": True,
                               "full_text": core, "compact_text": core}}))
        chat_params.set_chat_params_cache(_Chat())
        pc.reset_state()
        llm = _FakeLLM("кстати, помню")
        worker = nw.NostalgiaWorker(_Db(), store=_Store(), llm=llm)
        try:
            await worker._llm_once(
                {"text": "факт", "kind": "year_back",
                 "year_lines": ["[Кто-то 2025]: шутка"], "golden_lines": []},
                -100)
            system = llm.calls[0][0][0]["content"]
            assert core in system
            assert au.genre_rules("nostalgia") in system
            assert "UNCHANGED" in system
            assert "токсично-тёплый" not in system    # legacy-персона не рендерится
        finally:
            hot.set_config_cache(None)
            chat_params.set_chat_params_cache(None)
            pc.reset_state()


class TestSingleDecisionDelegation:
    @pytest.mark.asyncio
    async def test_active_chat_delegates_with_distinguishable_source(
            self, db, monkeypatch):
        """Сценарий A: кандидат уходит в единый Decision различимым
        источником (nostalgia/nostalgia_due), отправка логируется sent."""
        _patch_time(monkeypatch)
        monkeypatch.setattr(nw, "_intent_delegation_enabled", lambda: True)
        captured: dict = {}

        async def _spy(*, bot, chat_id, situation, candidates,
                       prepared_text=None, db=None, correlation_id=None,
                       writer_service=None):
            captured["chat_id"] = chat_id
            captured["source"] = candidates[0].source
            captured["trigger"] = situation.trigger_kind
            captured["text"] = prepared_text
            captured["ref"] = candidates[0].prepared_text_ref
            return {"status": "sent", "delivery_kind": "text"}

        from services import direct_chat_service as dcs
        monkeypatch.setattr(dcs, "handle_initiative", _spy)
        await _add_user_msg(db, "живая беседа", ts=NOW - 300)
        await _add_user_msg(db, "год назад был концерт",
                            ts=NOW - 365 * 86400 + 4000)
        w = _worker(db, _FakeLLM("кстати, помню концерт"),
                    monkeypatch=monkeypatch)
        out = await w._process_chat(CHAT_ID, NOW, manual=False)
        assert out["sent"] == 1
        assert captured["chat_id"] == CHAT_ID
        assert captured["source"] == "nostalgia"
        assert captured["trigger"] == "nostalgia_due"
        assert captured["ref"].startswith("nostalgia:")
        assert captured["text"] == "кстати, помню концерт"
        rows = await _log_rows(db)
        assert rows[0]["status"] == "sent"
        assert json.loads(rows[0]["meta"])["path"] == "initiative"
