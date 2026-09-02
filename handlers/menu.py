"""Задание A/B/fix (2026-09-03): /menu — кнопка WebApp на мини-апп админки.

Доступна ВСЕМ (без админ-фильтров). Ветвление по chat.type (ФИКС 2026-09-03):
  * private → InlineKeyboardMarkup с web_app-кнопкой «🛠 Меню бота»;
  * group/supergroup/другое → НЕ web_app-кнопка (Telegram НЕ поддерживает
    web_app-инлайн-кнопки в группах: BUTTON_TYPE_INVALID), только текст-
    подсказка «напишите боту в личку». URL-кнопку (web_app/url) НЕ ставим
    осознанно: при открытии по url вне Telegram-контекста initData не
    придёт и миниапп покажет authLocked-заглушку (правило реализации:
    подсказка без URL-кнопки — зафиксировать в комментарии).
Текст кнопки — с эмодзи; цвет/форму кнопки изменить нельзя (ресерч
core.telegram.org/bots/buttons, webapps). URL настраивается env WEBAPP_URL.
"""
import logging

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from config.settings import settings

logger = logging.getLogger(__name__)

menu_router = Router(name="menu")

_WEBAPP_BUTTON_TEXT = "🛠 Меню бота"

_PRIVATE_CHAT_TYPES = ("private",)


async def _bot_username(message: types.Message) -> str:
    """Юзернейм бота для подсказки (не хардкод). bot.me() — прецедент
    ThrottlingMiddleware (services/summary_throttling.py); bot не имеет
    атрибута username в aiogram 3.31 (B1). Возвращает "botname" или ""."""
    bot = getattr(message, "bot", None)
    if bot is None:
        return ""
    try:
        me = await bot.me()
    except Exception:
        return ""
    if me is None:
        return ""
    username = getattr(me, "username", None)
    return username.lstrip("@") if isinstance(username, str) else ""


@menu_router.message(Command("menu"))
async def menu_command(message: types.Message) -> None:
    """Ветвление по chat.type: private → web_app-кнопка; группы → подсказка."""
    chat = message.chat
    chat_type = getattr(chat, "type", "private") or "private"
    url = (settings.WEBAPP_URL or "").strip()
    if not url:
        logger.warning("[menu] WEBAPP_URL пуст — команда без кнопки")
        await message.reply("Мини-апп не настроен (WEBAPP_URL).")
        return

    if chat_type in _PRIVATE_CHAT_TYPES:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=_WEBAPP_BUTTON_TEXT,
                                 web_app=WebAppInfo(url=url)),
        ]])
        await message.reply("Открыть мини-апп:", reply_markup=keyboard)
        logger.info("[menu] sent | chat=%s | type=%s", chat.id, chat_type)
        return

    # Группа/супергруппа и пр.: Telegram НЕ поддерживает web_app-инлайн-кнопки
    # в группах (BUTTON_TYPE_INVALID — бот админ, апдейты доходят). URL-кнопку
    # НЕ добавляем: миниапп без Telegram-контекста (initData) покажет
    # authLocked-заглушку. Только текст-подсказка (решение зафиксировано).
    user = await _bot_username(message)
    if user:
        hint = ("🛠 Меню бота доступно в личке — напишите боту @%s /menu "
                "(или нажмите кнопку меню слева)." % user)
    else:
        hint = ("🛠 Меню бота доступно в личке — напишите боту /menu "
                "(или нажмите кнопку меню слева).")
    await message.reply(hint)
    logger.info("[menu] sent (group hint) | chat=%s | type=%s", chat.id,
                chat_type)
