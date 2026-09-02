"""Задание A/B (2026-09-03): /menu — кнопка WebApp на мини-апп админки.

Доступна ВСЕМ (без админ-фильтров) и в ЛЮБОМ чате, где есть бот (личка,
группы, супергруппы): отвечает в том же чате той же кнопкой. Фильтр только
`F.text == "/menu"` — никаких chat.type-ограничений (A).
Текст кнопки — с эмодзи (unicode-эмодзи в тексте inline-кнопки Telegram
поддерживает); цвет/форму самой кнопки изменить нельзя — клиент рисует её
по своей теме (B, ресерч core.telegram.org/bots/buttons, webapps).
URL настраивается env WEBAPP_URL (дефолт https://admin-bot.duckdns.org/web/).
"""
import logging

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from config.settings import settings

logger = logging.getLogger(__name__)

menu_router = Router(name="menu")

_WEBAPP_BUTTON_TEXT = "🛠 Меню бота"


@menu_router.message(Command("menu"))
async def menu_command(message: types.Message) -> None:
    """Кнопка «🛠 Меню бота» → WebApp (мини-апп). Работает в ЛЮБОМ чате
    (личка/группа/супергруппа) — фильтра chat.type нет (A). Command("menu")
    матчит и /menu, и /menu@username (важно для групп с privacy mode)."""
    url = (settings.WEBAPP_URL or "").strip()
    if not url:
        logger.warning("[menu] WEBAPP_URL пуст — команда без кнопки")
        await message.reply("Мини-апп не настроен (WEBAPP_URL).")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_WEBAPP_BUTTON_TEXT,
                             web_app=WebAppInfo(url=url)),
    ]])
    await message.reply("Открыть мини-апп:", reply_markup=keyboard)
    logger.info("[menu] sent | chat=%s | type=%s", message.chat.id,
                getattr(message.chat, "type", "?") if message.chat else "?")
