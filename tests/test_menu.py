"""Задание B (2026-09-03): /menu — кнопка WebApp мини-аппа, доступна всем.

Проверяем: ответ содержит InlineKeyboardMarkup с InlineKeyboardButton
(web_app=WebAppInfo), URL из settings.WEBAPP_URL; без URL — понятный reply;
роутер зарегистрирован в bot.py.
"""
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers.menu import menu_command, menu_router


def _make_msg(from_id=777, text="/menu", chat_id=-1001234567890):
    msg = MagicMock()
    msg.text = text
    msg.message_id = 1
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = from_id
    msg.reply = AsyncMock()
    msg.answer = AsyncMock()
    return msg


class TestMenuCommand:
    @pytest.mark.asyncio
    async def test_menu_any_user_receives_webapp_button(self):
        """Любой user_id (не админ) получает клавиатуру с WebApp-кнопкой."""
        msg = _make_msg(from_id=999999)          # обычный юзер
        await menu_command(msg)
        msg.reply.assert_awaited_once()
        call = msg.reply.call_args
        assert call.kwargs["reply_markup"] is not None
        markup = call.kwargs["reply_markup"]
        button = markup.inline_keyboard[0][0]
        assert button.text == "Меню бота"
        assert button.web_app is not None
        assert button.web_app.url == "https://admin-bot.duckdns.org/web/"

    @pytest.mark.asyncio
    async def test_menu_url_from_settings(self):
        """URL берётся из settings.WEBAPP_URL (кастомное значение)."""
        import handlers.menu as menu_mod
        msg = _make_msg(from_id=42)
        custom = replace(menu_mod.settings, WEBAPP_URL="https://example.com/custom/")
        with patch.object(menu_mod, "settings", custom):
            await menu_command(msg)
        button = msg.reply.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
        assert button.web_app.url == "https://example.com/custom/"

    @pytest.mark.asyncio
    async def test_menu_empty_url_fallback_reply(self):
        """WEBAPP_URL пуст → понятное сообщение без клавиатуры."""
        import handlers.menu as menu_mod
        msg = _make_msg()
        empty = replace(menu_mod.settings, WEBAPP_URL="   ")
        with patch.object(menu_mod, "settings", empty):
            await menu_command(msg)
        msg.reply.assert_awaited_once()
        text = msg.reply.call_args.args[0]
        assert "WEBAPP_URL" in text
        assert "reply_markup" not in msg.reply.call_args.kwargs

    def test_router_registered_in_bot(self):
        """bot.py подключает menu_router (include_router)."""
        src = open("bot.py", encoding="utf-8").read()
        assert "menu_router" in src
        assert "dp.include_router(menu_router)" in src

    def test_command_in_bot_commands(self):
        """/menu в списке команд setMyCommands."""
        src = open("services/bot_commands.py", encoding="utf-8").read()
        assert 'command="menu"' in src
        assert "Меню бота" in src

    def test_router_object_sane(self):
        assert menu_router.name == "menu"
