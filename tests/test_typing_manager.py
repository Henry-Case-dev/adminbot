"""Epic 60 (65.7, R60-16, T-475): typing_active — тонкая обёртка над
ChatActionSender.typing (aiogram 3.29.1, вердикт T-459 тема 2).

Вход в блок → фоновая таска шлёт sendChatAction (без искусственной паузы);
выход → задача остановлена (индикатор гаснет сам ≤5с/при отправке сообщения).
TYPING_INDICATOR_ENABLED=false → блок не создаётся (ровно старое поведение).
"""
import asyncio
import dataclasses
from contextlib import nullcontext
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services import typing_manager


def _cfg(**overrides):
    """Копия frozen-Settings с переопределениями."""
    return dataclasses.replace(settings, **overrides)


class TestTypingManager:
    def test_disabled_returns_nullcontext(self, monkeypatch):
        monkeypatch.setattr(
            "services.typing_manager.settings",
            _cfg(TYPING_INDICATOR_ENABLED=False))
        ctx = typing_manager.typing_active(AsyncMock(), 123)
        assert isinstance(ctx, nullcontext)   # блок НЕ создаётся

    def test_none_bot_returns_nullcontext(self):
        ctx = typing_manager.typing_active(None, 123)
        assert isinstance(ctx, nullcontext)

    def test_enabled_wraps_chat_action_sender(self, monkeypatch):
        fake_sender = MagicMock()
        sender_cls = MagicMock()
        sender_cls.typing = MagicMock(return_value=fake_sender)
        monkeypatch.setattr("services.typing_manager.ChatActionSender", sender_cls)
        bot = AsyncMock()
        ctx = typing_manager.typing_active(bot, 123)
        assert ctx is fake_sender
        sender_cls.typing.assert_called_once_with(
            bot=bot, chat_id=123, interval=settings.TYPING_INTERVAL_SECONDS)

    @pytest.mark.asyncio
    async def test_real_sender_sends_action_and_stops(self):
        """Интеграционно: реальный ChatActionSender с AsyncMock-ботом — вход
        шлёт action, выход останавливает фоновую задачу."""
        bot = AsyncMock()
        bot.id = 1
        sender = typing_manager.typing_active(bot, 123)
        async with sender:
            await asyncio.sleep(0.05)          # дать фоновой таске отправить action
            bot.send_chat_action.assert_awaited()
            assert sender.running
        assert not sender.running              # задача остановлена на выходе
