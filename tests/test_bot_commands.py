"""Tests for services/bot_commands.py (Epic 31, T-236/R31-2/D95; Epic 43, T-338-B)."""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import BotCommand, BotCommandScopeDefault

from services.bot_commands import _COMMANDS, setup_bot_commands

_DESCRIPTION = "Саммари чата — прочитай, что ты пропустил, ленивец"
_INFO_DESCRIPTION = "Справка по фичам бота"


class TestCommandsTuple:
    """D95 + Epic 43 (T-338-B): /summary + /info (append, порядок не тронут)."""

    def test_commands_contains_summary_and_info(self):
        assert len(_COMMANDS) == 2
        cmd = _COMMANDS[0]
        assert isinstance(cmd, BotCommand)
        assert cmd.command == "summary"
        assert cmd.description == _DESCRIPTION
        info = _COMMANDS[1]
        assert isinstance(info, BotCommand)
        assert info.command == "info"
        assert info.description == _INFO_DESCRIPTION


class TestSetupBotCommands:
    @pytest.mark.asyncio
    async def test_success_registers_and_returns_true(self, caplog):
        bot = MagicMock()
        bot.set_my_commands = AsyncMock(return_value=True)
        with caplog.at_level(logging.INFO):
            result = await setup_bot_commands(bot)
        assert result is True
        bot.set_my_commands.assert_awaited_once()
        kwargs = bot.set_my_commands.await_args.kwargs
        commands = kwargs["commands"]
        assert len(commands) == 2
        assert isinstance(commands[0], BotCommand)
        assert commands[0].command == "summary"
        assert commands[0].description == _DESCRIPTION
        assert commands[1].command == "info"
        assert commands[1].description == _INFO_DESCRIPTION
        assert isinstance(kwargs.get("scope"), BotCommandScopeDefault)
        assert kwargs.get("language_code") is None
        assert any("set_my_commands ok" in r.message for r in caplog.records)
        assert any(
            "['summary', 'info']" in r.message for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_api_error_returns_false_and_does_not_raise(self, caplog):
        """D95: сбой setMyCommands → False + ERROR-лог, старт не падает."""
        bot = MagicMock()
        bot.set_my_commands = AsyncMock(side_effect=Exception("Telegram API сдох"))
        with caplog.at_level(logging.ERROR):
            result = await setup_bot_commands(bot)
        assert result is False
        assert any("Failed to register bot commands" in r.message for r in caplog.records)
