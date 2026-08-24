"""Tests for handlers/checkup.py (T-330-A #1-10, Section 51.2/51.7).

Триггеры (6 фраз, регистр, хвостовая пунктуация, «сделай чекап» да /
«чекапчик» нет); кулдаун per-chat (слот (chat_id, 0)); ВСЕ ответы —
реплаем на message.message_id; фолбек-фраза ДО checkup; DEAD/LLM-пулы.
"""
import logging

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED
from unittest.mock import AsyncMock, MagicMock

from handlers import checkup as checkup_mod
from services.llm_client import LLMBadResponseError, LLMError
from services.smartmodule_phrases import (
    CHECKUP_DEAD_PHRASES,
    CHECKUP_FALLBACK_PHRASES,
    CHECKUP_LLM_ERROR_PHRASES,
    THROTTLE_PHRASES,
)
from services.smartmodule_throttling import format_remaining_time
from services.system_logs_fetcher import CheckupLogsUnavailableException

CHAT_ID = -1001234567890


@pytest.fixture
def fake_time(monkeypatch):
    state = {"now": 1000.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            return state["now"]

    monkeypatch.setattr("services.smartmodule_throttling.time", FakeTime)
    return state


@pytest.fixture
def checkup_cleanup():
    yield
    checkup_mod._service = None
    checkup_mod._fetcher = None
    checkup_mod._cooldown._last.clear()


def _make_msg(text=None, caption=None, message_id=1, user_id=1, chat_id=CHAT_ID):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    return msg


def _wire(service=None, fetcher=None):
    checkup_mod.setup_checkup(service, fetcher)


class TestCheckupTriggers:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "text",
        [
            "чекап", "ЧеКаП!!", "ты в порядке?", "живой собака", "пульс бота.",
            "чекни здоровье", "как сервак",                       # #1: регистр/пунктуация
            "сделай чекап", "ну и как сервак?", "есть тут живой собака?",  # #2: совпадение
            "ЧЕКАП", "ТЫ В ПОРЯДКЕ", "пульс бота",
        ],
    )
    async def test_trigger_fetcher_called(self, checkup_cleanup, text):
        service = MagicMock()
        service.checkup = AsyncMock(return_value="отчёт")
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text=text, message_id=11)
        result = await checkup_mod.checkup_handler(msg, bot=bot)
        assert result is None
        fetcher.fetch.assert_awaited_once()
        service.checkup.assert_awaited_once_with("логи", False)
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "text",
        [
            "чекапчик", "живой собакен", "как сервак работает",
            "ты в порядке духа", "чекни здоровье матери",
            "пульс бота дважды", "", None,
        ],
    )
    async def test_non_trigger_unhandled(self, checkup_cleanup, text):
        """#3: негативы — UNHANDLED, fetcher НЕ вызван."""
        service = MagicMock()
        service.checkup = AsyncMock()
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock()
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text=text, message_id=11)
        result = await checkup_mod.checkup_handler(msg, bot=bot)
        assert result is UNHANDLED
        fetcher.fetch.assert_not_called()
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_service_returns_unhandled(self, checkup_cleanup):
        """#4: _service is None → UNHANDLED."""
        checkup_mod._service = None
        checkup_mod._fetcher = None
        bot = AsyncMock()
        msg = _make_msg(text="чекап", message_id=11)
        result = await checkup_mod.checkup_handler(msg, bot=bot)
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_no_fetcher_returns_unhandled(self, checkup_cleanup):
        _wire(MagicMock(), None)
        bot = AsyncMock()
        msg = _make_msg(text="чекап", message_id=11)
        result = await checkup_mod.checkup_handler(msg, bot=bot)
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_caption_trigger(self, checkup_cleanup):
        """#5: caption-триггер (text=None, caption=«чекап»)."""
        service = MagicMock()
        service.checkup = AsyncMock(return_value="отчёт")
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text=None, caption="чекап", message_id=11)
        await checkup_mod.checkup_handler(msg, bot=bot)
        fetcher.fetch.assert_awaited_once()


class TestCheckupCooldown:
    @pytest.mark.asyncio
    async def test_second_call_in_same_chat_throttled(self, checkup_cleanup, fake_time):
        """#6: 2-й вызов в том же чате (другой user) → 5.1, fetcher НЕ вызван;
        другой chat — НЕ троттлится."""
        service = MagicMock()
        service.checkup = AsyncMock(return_value="отчёт")
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        _wire(service, fetcher)
        bot = AsyncMock()
        first = _make_msg(text="чекап", message_id=11, user_id=1)
        await checkup_mod.checkup_handler(first, bot=bot)
        assert fetcher.fetch.await_count == 1

        fake_time["now"] += 100
        expected_remaining = checkup_mod._cooldown.remaining(CHAT_ID, 0)
        assert expected_remaining > 0
        second = _make_msg(text="чекап", message_id=22, user_id=2)
        await checkup_mod.checkup_handler(second, bot=bot)
        assert fetcher.fetch.await_count == 1                      # не вызван
        fmt = format_remaining_time(expected_remaining)
        candidates = [p.replace("{remaining_time}", fmt) for p in THROTTLE_PHRASES]
        assert bot.send_message.await_args.args[1] in candidates
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 22

        other = _make_msg(text="чекап", message_id=33, user_id=3, chat_id=-987654321)
        await checkup_mod.checkup_handler(other, bot=bot)
        assert fetcher.fetch.await_count == 2                      # другой чат — ок


class TestCheckupHandler:
    @pytest.mark.asyncio
    async def test_success_sends_report(self, checkup_cleanup):
        """#7: fetch→(logs, False), checkup→report → send_chunked_reply реплаем."""
        service = MagicMock()
        service.checkup = AsyncMock(return_value="отчёт о здоровье")
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text="чекап", message_id=11)
        await checkup_mod.checkup_handler(msg, bot=bot)
        service.checkup.assert_awaited_once_with("логи", False)
        assert bot.send_message.await_args.args[1] == "отчёт о здоровье"
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    async def test_fallback_phrase_before_checkup(self, checkup_cleanup):
        """#8: fetch→(logs, True) → фолбек-фраза реплаем ДО checkup, затем отчёт."""
        service = MagicMock()
        service.checkup = AsyncMock(return_value="отчёт")
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("локальные логи", True))
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text="чекап", message_id=11)
        await checkup_mod.checkup_handler(msg, bot=bot)
        service.checkup.assert_awaited_once_with("локальные логи", True)
        calls = bot.send_message.await_args_list
        assert calls[0].args[1] in CHECKUP_FALLBACK_PHRASES
        assert calls[0].kwargs["reply_to_message_id"] == 11
        assert calls[1].args[1] == "отчёт"

    @pytest.mark.asyncio
    async def test_all_sources_dead_pool(self, checkup_cleanup):
        """#9: fetch raise CheckupLogsUnavailable → CHECKUP_DEAD_PHRASES, LLM НЕ вызван."""
        service = MagicMock()
        service.checkup = AsyncMock()
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(side_effect=CheckupLogsUnavailableException("dead"))
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text="чекап", message_id=11)
        await checkup_mod.checkup_handler(msg, bot=bot)
        service.checkup.assert_not_called()
        assert bot.send_message.await_args.args[1] in CHECKUP_DEAD_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    async def test_llm_error_pool(self, checkup_cleanup):
        """#10: checkup raise LLMError → CHECKUP_LLM_ERROR_PHRASES."""
        service = MagicMock()
        service.checkup = AsyncMock(side_effect=LLMError("сдохла"))
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text="чекап", message_id=11)
        await checkup_mod.checkup_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in CHECKUP_LLM_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    async def test_unexpected_error_pool(self, checkup_cleanup):
        """#10: checkup raise Exception → тот же CHECKUP_LLM_ERROR_PHRASES."""
        service = MagicMock()
        service.checkup = AsyncMock(side_effect=RuntimeError("неожиданно"))
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text="чекап", message_id=11)
        await checkup_mod.checkup_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in CHECKUP_LLM_ERROR_PHRASES

    @pytest.mark.asyncio
    async def test_empty_answer_silence_with_moai(self, checkup_cleanup, caplog):
        """65.1 (T-469): пустой ответ модели → НЕТ сообщения (ни отчёта, ни
        R13-фразы), есть реакция 🗿 на триггер."""
        service = MagicMock()
        service.checkup = AsyncMock(
            side_effect=LLMBadResponseError("checkup: empty answer"))
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text="чекап", message_id=11)
        with caplog.at_level(logging.WARNING):
            await checkup_mod.checkup_handler(msg, bot=bot)
        bot.send_message.assert_not_called()
        bot.set_message_reaction.assert_awaited_once()
        assert bot.set_message_reaction.await_args.args[:2] == (CHAT_ID, 11)
        assert any("empty answer" in r.message for r in caplog.records)


class TestEpic49LogLevels:
    """Epic 49 (57.6, D199): checkup.py:68/81 — WARNING без traceback."""

    @pytest.mark.asyncio
    async def test_llm_error_is_warning_without_traceback(self, checkup_cleanup, caplog):
        import logging

        service = MagicMock()
        service.checkup = AsyncMock(side_effect=LLMError("сдохла"))
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text="чекап", message_id=11)
        with caplog.at_level(logging.WARNING):
            await checkup_mod.checkup_handler(msg, bot=bot)
        records = [r for r in caplog.records
                   if r.message.startswith("[checkup] LLM failed")]
        assert records, "нет WARNING-лога LLM failed"
        assert records[0].levelno == logging.WARNING
        assert records[0].exc_info is None or records[0].exc_info[0] is None
        assert "error=" in records[0].message
        assert bot.send_message.await_args.args[1] in CHECKUP_LLM_ERROR_PHRASES

    @pytest.mark.asyncio
    async def test_dead_is_warning_without_traceback(self, checkup_cleanup, caplog):
        import logging

        service = MagicMock()
        service.checkup = AsyncMock()
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(side_effect=CheckupLogsUnavailableException("dead"))
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text="чекап", message_id=11)
        with caplog.at_level(logging.WARNING):
            await checkup_mod.checkup_handler(msg, bot=bot)
        records = [r for r in caplog.records
                   if r.message.startswith("[checkup] all log sources failed")]
        assert records
        assert records[0].levelno == logging.WARNING
        assert records[0].exc_info is None or records[0].exc_info[0] is None
        assert bot.send_message.await_args.args[1] in CHECKUP_DEAD_PHRASES

    @pytest.mark.asyncio
    async def test_llm_failure_never_says_db_phrase(self, checkup_cleanup):
        """DoD T-390: при падении LLM «база подавилась логами» НЕ уходит."""
        service = MagicMock()
        service.checkup = AsyncMock(side_effect=LLMError("сдохла"))
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text="чекап", message_id=11)
        await checkup_mod.checkup_handler(msg, bot=bot)
        reply = bot.send_message.await_args.args[1]
        assert reply in CHECKUP_LLM_ERROR_PHRASES
        assert "база подавилась логами" not in reply
        assert "база подавилась логами" not in CHECKUP_LLM_ERROR_PHRASES


class TestEpic60MemoryMetricsFlow:
    """Epic 60 (64.5/64.9 #8, T-466): полный поток чекапа с реальной БД —
    метрики попадают в user-контент, отчёт доходит реплаем."""

    @pytest.mark.asyncio
    async def test_full_flow_with_metrics(self, checkup_cleanup):
        from services.checkup_service import CheckupService
        from services.database import DatabaseService

        db = DatabaseService(":memory:")
        await db.initialize()
        await db.insert_graph_fact(-100, "факт для метрик", "search_fact", None)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="отчёт с данными")
        service = CheckupService(llm, db=db, memory=None)
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("логи", False))
        _wire(service, fetcher)
        bot = AsyncMock()
        msg = _make_msg(text="чекап", message_id=11)
        await checkup_mod.checkup_handler(msg, bot=bot)
        user = llm.generate.await_args.args[0][1]["content"]
        assert "graph_facts: 1" in user
        assert "&lt;memory_health&gt;" in user
        assert bot.send_message.await_args.args[1] == "отчёт с данными"
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11
        await db.close()
