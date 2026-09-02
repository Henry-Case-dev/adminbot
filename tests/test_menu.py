"""Задание B (2026-09-03): /menu — кнопка WebApp мини-аппа, доступна всем.

Проверяем: ответ содержит InlineKeyboardMarkup с InlineKeyboardButton
(web_app=WebAppInfo), URL из settings.WEBAPP_URL; без URL — понятный reply;
роутер зарегистрирован в bot.py.
"""
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers.menu import menu_command, menu_router


def _make_msg(from_id=777, text="/menu", chat_id=-1001234567890,
              chat_type="private"):
    msg = MagicMock()
    msg.text = text
    msg.message_id = 1
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.chat.type = chat_type
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
        assert button.text == "🛠 Меню бота"
        assert button.web_app is not None
        assert button.web_app.url == "https://admin-bot.duckdns.org/web/"

    @pytest.mark.asyncio
    async def test_menu_works_in_supergroup(self):
        """A: супергруппа — та же кнопка, без ошибок."""
        for chat_type in ("supergroup", "group", "channel"):
            msg = _make_msg(from_id=555, chat_id=-100999888,
                            chat_type=chat_type)
            await menu_command(msg)
            msg.reply.assert_awaited_once()
            button = msg.reply.call_args.kwargs[
                "reply_markup"].inline_keyboard[0][0]
            assert button.web_app is not None

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

    def test_no_chat_type_filter(self):
        """A: в обработчике /menu НЕТ фильтра F.chat.type — работает в группах."""
        src = open("handlers/menu.py", encoding="utf-8").read()
        assert "F.chat.type" not in src

    @pytest.mark.asyncio
    async def test_command_filter_matches_mention(self):
        """Ревью: Command("menu") матчит и /menu, и /menu@username (группы с
        privacy mode); чужой @username — НЕ матчит."""
        from datetime import datetime, timezone
        from aiogram.filters import Command
        from aiogram.types import Chat, Message, User

        def _real_msg(text):
            return Message(
                message_id=1,
                date=datetime.now(timezone.utc),
                chat=Chat(id=-100, type="supergroup"),
                from_user=User(id=1, is_bot=False, first_name="x"),
                text=text,
            )

        filt = Command("menu")
        bot = MagicMock()
        bot.username = "PERMsoc_bot"
        bot.me = AsyncMock(return_value=User(
            id=42, is_bot=True, first_name="PERM", username="PERMsoc_bot"))
        assert await filt(_real_msg("/menu"), bot)
        assert await filt(_real_msg("/menu@PERMsoc_bot"), bot)
        assert not await filt(_real_msg("/menu@other_bot"), bot)
        assert not await filt(_real_msg("/menu2"), bot)
        assert not await filt(_real_msg("просто текст"), bot)

    def test_theme_colors_in_miniapp(self):
        """B: миниапп применяет Telegram.WebApp-тему (themeParams + фолбэки)."""
        src = open("web/index.html", encoding="utf-8").read()
        assert "Telegram.WebApp.setHeaderColor(" in src
        assert "themeParams" in src
        assert "setBackgroundColor(" in src
        assert "setBottomBarColor" in src
        assert "'#2b2b40'" in src          # фолбэк-палитра админки
        assert "Telegram.WebApp.ready()" in src
