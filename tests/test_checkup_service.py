"""Tests for services/checkup_service.py (T-330-A #24-26, Section 51.6).

system.replace({max_symbols}) → llm.generate → cleanup_llm_text; скрытая
приписка CHECKUP_FALLBACK_NOTICE в КОНЕЦ system-сообщения ровно 1 раз при
used_fallback; user = <system_logs>…</system_logs> (escape_xml_text);
LLMError пробрасывается; пустые логи валидны.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import checkup_service as svc_mod
from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE
from services.checkup_service import CheckupService
from services.llm_client import LLMError


@pytest.fixture
def make_service():
    def _make(return_value="всё горит"):
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=return_value)
        return CheckupService(llm), llm

    return _make


class TestCheckupService:
    @pytest.mark.asyncio
    async def test_max_symbols_substituted_and_context(self, make_service):
        """#24: system содержит подставленный max_symbols; приписки НЕТ;
        user = <system_logs>…</system_logs>."""
        service, llm = make_service()
        await service.checkup("some logs", used_fallback=False)
        messages = llm.generate.await_args.args[0]
        assert len(messages) == 2
        system, user = messages[0], messages[1]
        assert "{max_symbols}" not in system["content"]
        assert str(svc_mod.settings.CHECKUP_MAX_SYMBOLS) in system["content"]
        assert CHECKUP_FALLBACK_NOTICE not in system["content"]
        assert user["content"].startswith("<system_logs>")
        assert user["content"].endswith("</system_logs>")
        assert "some logs" in user["content"]

    @pytest.mark.asyncio
    async def test_fallback_notice_appended_once_at_end(self, make_service):
        """#25: used_fallback=True → приписка ровно 1 раз, в КОНЦЕ system."""
        service, llm = make_service()
        await service.checkup("logs", used_fallback=True)
        system = llm.generate.await_args.args[0][0]["content"]
        assert system.count(CHECKUP_FALLBACK_NOTICE) == 1
        assert system.endswith(CHECKUP_FALLBACK_NOTICE)
        assert system[: -len(CHECKUP_FALLBACK_NOTICE)].endswith("\n\n")

    @pytest.mark.asyncio
    async def test_logs_xml_escaped(self, make_service):
        service, llm = make_service()
        await service.checkup('<evil> & "quotes"', used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert "<evil>" not in user
        assert "&lt;evil&gt;" in user

    @pytest.mark.asyncio
    async def test_cleanup_applied_to_output(self, make_service):
        """#26: llm вернул «—»/««»»/«**» → cleanup_llm_text применился."""
        service, llm = make_service(return_value="поломка — «тест» **маркдаун**")
        result = await service.checkup("logs", used_fallback=False)
        assert result == 'поломка - "тест" **маркдаун**'
        assert "—" not in result and "«" not in result

    @pytest.mark.asyncio
    async def test_llm_error_propagates(self, make_service):
        """#26: LLMError пробрасывается (хендлер шлёт CHECKUP_LLM_ERROR_PHRASES)."""
        service, llm = make_service()
        llm.generate = AsyncMock(side_effect=LLMError("нейронка отвалилась"))
        with pytest.raises(LLMError):
            await service.checkup("logs", used_fallback=False)

    @pytest.mark.asyncio
    async def test_empty_logs_valid(self, make_service):
        """51.6: пустые логи («» от journalctl) валидны — не dead-пул."""
        service, llm = make_service()
        result = await service.checkup("", used_fallback=True)
        user = llm.generate.await_args.args[0][1]["content"]
        assert user == "<system_logs></system_logs>"
        assert result == "всё горит"


class TestEpic49ScrubAndTruncate:
    """Epic 49 (57.5, D196): scrub C0 (кроме \\n \\t → пробел) + потолок
    CHECKUP_MAX_INPUT_SYMBOLS; кириллица не затрагивается."""

    @pytest.mark.asyncio
    async def test_scrub_control_chars(self, make_service):
        """#4: "a\\x00b\\x01c\\nd\\x7fe" → "a b c\\nd e" — C0→пробел, \\n сохранён."""
        service, llm = make_service()
        await service.checkup("a\x00b\x01c\nd\x7fe", used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert "a b c\nd e" in user
        assert "\x00" not in user and "\x01" not in user and "\x7f" not in user

    @pytest.mark.asyncio
    async def test_scrub_keeps_tab(self, make_service):
        """\\t НЕ заменяется (разрешён вместе с \\n)."""
        service, llm = make_service()
        await service.checkup("a\tb\nc", used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert "a\tb\nc" in user

    @pytest.mark.asyncio
    async def test_input_truncated_with_warning(self, make_service, caplog):
        """#5: вход 12001+ симв → user ≤ CHECKUP_MAX_INPUT_SYMBOLS, WARNING,
        кириллица цела."""
        import logging

        limit = svc_mod.settings.CHECKUP_MAX_INPUT_SYMBOLS
        logs = "я" * (limit + 1)
        service, llm = make_service()
        with caplog.at_level(logging.WARNING):
            await service.checkup(logs, used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert user == f"<system_logs>{'я' * limit}</system_logs>"
        assert any("[checkup] input truncated" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_within_limit_unchanged(self, make_service):
        """#6: вход ≤ 12000 — байт-в-байт прежний путь (никаких правок)."""
        service, llm = make_service()
        await service.checkup("обычные логи без аномалий", used_fallback=False)
        user = llm.generate.await_args.args[0][1]["content"]
        assert user == "<system_logs>обычные логи без аномалий</system_logs>"
