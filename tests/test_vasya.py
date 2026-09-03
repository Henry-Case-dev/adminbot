import pytest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from handlers.vasya import reply_to_vasya, reply_to_admin


@pytest.fixture(autouse=True)
def _vasya_enabled():
    """Эпик 04.09.2026 (3.4.1): тумблер reactions.vasya_enabled — default
    false; для прежнего поведения включаем (patch модульного settings)."""
    mod = replace(settings, VASYA_ENABLED=True)
    with patch("handlers.vasya.settings", mod):
        yield


class TestVasyaHandlers:
    @pytest.mark.asyncio
    async def test_vasya_gets_admin(self, make_message):
        msg = make_message(12345, text="вася привет")
        await reply_to_vasya(msg)
        msg.reply.assert_called_once_with("АДМИН")

    @pytest.mark.asyncio
    async def test_vasiliy_gets_admin(self, make_message):
        msg = make_message(12345, text="Vasiliy тут?")
        await reply_to_vasya(msg)
        msg.reply.assert_called_once_with("АДМИН")

    @pytest.mark.asyncio
    async def test_admin_gets_vasya(self, make_message):
        msg = make_message(12345, text="админ")
        await reply_to_admin(msg)
        msg.reply.assert_called_once_with("ВАСЯ")

    @pytest.mark.asyncio
    async def test_admin_with_punctuation(self, make_message):
        msg = make_message(12345, text="!админ?")
        await reply_to_admin(msg)
        msg.reply.assert_called_once_with("ВАСЯ")

    @pytest.mark.asyncio
    async def test_admin_in_sentence(self, make_message):
        msg = make_message(12345, text="где админ?")
        await reply_to_admin(msg)
        msg.reply.assert_called_once_with("ВАСЯ")


class TestVasyaGateDisabled:
    """Эпик 04.09.2026 (FR-18/FR-19): тумблер выключен (default false) →
    гейт первой строкой, UNHANDLED, ответа нет, без ошибок."""

    @pytest.fixture(autouse=True)
    def _vasya_disabled(self):
        mod = replace(settings, VASYA_ENABLED=False)
        with patch("handlers.vasya.settings", mod):
            yield

    @pytest.mark.asyncio
    async def test_vasya_disabled_silent(self, make_message):
        msg = make_message(12345, text="вася привет")
        result = await reply_to_vasya(msg)
        assert result is UNHANDLED
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_disabled_silent(self, make_message):
        msg = make_message(12345, text="админ")
        result = await reply_to_admin(msg)
        assert result is UNHANDLED
        msg.reply.assert_not_called()
