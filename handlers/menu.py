"""Задание B (2026-09-03): /menu — кнопка WebApp на мини-апп админки.

Доступна ВСЕМ (без админ-фильтров): открывает Telegram Mini App
(settings.WEBAPP_URL) кнопкой InlineKeyboardButton(web_app=WebAppInfo).
URL настраивается env WEBAPP_URL (дефолт https://admin-bot.duckdns.org/web/).
"""
import logging

from aiogram import F, Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from config.settings import settings

logger = logging.getLogger(__name__)

menu_router = Router(name="menu")

_WEBAPP_BUTTON_TEXT = "Меню бота"


@menu_router.message(F.text == "/menu")
async def menu_command(message: types.Message) -> None:
    """Кнопка «Меню бота» → WebApp (мини-апп). Без прав и фильтров."""
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
    logger.info("[menu] sent | chat=%s", message.chat.id)
