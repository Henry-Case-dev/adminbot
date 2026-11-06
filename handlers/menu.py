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
import re
from urllib.parse import urlsplit

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from config.settings import settings

logger = logging.getLogger(__name__)

menu_router = Router(name="menu")

_WEBAPP_BUTTON_TEXT = "🛠 Меню бота"
_GROUP_BUTTON_TEXT = "Открыть мини-приложение"

_PRIVATE_CHAT_TYPES = ("private",)
_GROUP_CHAT_TYPES = ("group", "supergroup")
_TELEGRAM_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_MINI_APP_SHORT_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


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
    username = username.lstrip("@") if isinstance(username, str) else ""
    return username if _TELEGRAM_USERNAME_RE.fullmatch(username) else ""


def _group_deep_link(username: str, settings_obj) -> str:
    """Build a Telegram link only after external registration confirmation."""
    if not username or not getattr(settings_obj, "MINI_APP_REGISTRATION_CONFIRMED", False):
        return ""
    mode = (getattr(settings_obj, "MINI_APP_DEEP_LINK_MODE", "") or "").strip().lower()
    if mode == "main":
        return f"https://t.me/{username}?startapp"
    if mode == "named":
        short_name = (getattr(settings_obj, "MINI_APP_SHORT_NAME", "") or "").strip()
        if _MINI_APP_SHORT_NAME_RE.fullmatch(short_name):
            return f"https://t.me/{username}/{short_name}"
    return ""


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
        # 10.17 (F1 miniapp-mobile-dns-round1017, T-1670): host-only (R17) —
        # помогает определить, какой домен реально отдаётся кнопкой, без
        # логирования полного URL/секретов.
        logger.info("[menu] sent | chat=%s | type=%s | host=%s",
                    chat.id, chat_type, urlsplit(url).hostname or "-")
        return

    user = await _bot_username(message)
    deep_link = _group_deep_link(user, settings) if chat_type in _GROUP_CHAT_TYPES else ""
    if deep_link:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=_GROUP_BUTTON_TEXT, url=deep_link),
        ]])
        await message.reply("Открыть мини-апп:", reply_markup=keyboard)
        logger.info("[menu] sent (telegram deep link) | chat=%s | type=%s",
                    chat.id, chat_type)
        return

    if user:
        hint = ("🛠 Прямой запуск мини-аппа из этого чата пока недоступен. "
                "Напишите боту в личку @%s и отправьте /menu." % user)
    else:
        hint = ("🛠 Прямой запуск мини-аппа из этого чата пока недоступен. "
                "Напишите боту в личку и отправьте /menu.")
    await message.reply(hint)
    logger.info("[menu] sent (group hint) | chat=%s | type=%s", chat.id,
                chat_type)
