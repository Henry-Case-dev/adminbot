import pytest
from unittest.mock import AsyncMock

from handlers.slavik import kucha_handler, war_word_handler, slavik_catchall_handler


class TestKuchaHandler:
    @pytest.mark.asyncio
    async def test_replies_dalbaeb(self, make_message):
        msg = make_message(479167456, text="КУЧА денег")
        await kucha_handler(msg)
        msg.reply.assert_called_once_with("ДАЛБАЕБ")


class TestWarWordHandler:
    @pytest.mark.asyncio
    async def test_replies_tryaslo(self, make_message):
        msg = make_message(479167456, text="летит дрон")
        await war_word_handler(msg)
        msg.reply.assert_called_once_with("трясло ебаное")


class TestSlavikCatchall:
    @pytest.mark.asyncio
    async def test_replies_poshel_nahui(self, make_message):
        msg = make_message(479167456, text="любое сообщение")
        await slavik_catchall_handler(msg)
        msg.reply.assert_called_once_with("пошёл нахуй")
