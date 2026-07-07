import pytest
from unittest.mock import AsyncMock

from handlers.vasya import reply_to_vasya, reply_to_admin


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
