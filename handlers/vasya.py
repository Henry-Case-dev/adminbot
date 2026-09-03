"""Эпик 04.09.2026 (3.4.1): «Вася → АДМИН / админ → ВАСЯ» под тумблером
reactions.vasya_enabled (default false). Фильтры лишь определяют «кто
сработал» и не меняются; выключенный флаг → гейт первой строкой +
UNHANDLED (для последнего роутера это тишина, без ошибок и сообщений).

Порядок регистрации роутеров в bot.py НЕ меняется.
"""
import logging

from aiogram import Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from services import hot_config as hot
from filters.vasya_name import VasyaFilter
from filters.admin_word import StrictAdminFilter

logger = logging.getLogger(__name__)

vasya_router = Router()


@vasya_router.message(VasyaFilter())
async def reply_to_vasya(message: types.Message):
    """If someone writes VASYA → reply ADMIN"""
    if not hot.get("reactions.vasya_enabled", settings.VASYA_ENABLED):
        logger.info("vasya: disabled (reactions.vasya_enabled=False) | user=%s",
                    message.from_user.id if message.from_user else 0)
        return UNHANDLED
    await message.reply("АДМИН")


@vasya_router.message(StrictAdminFilter())
async def reply_to_admin(message: types.Message):
    """If someone writes ADMIN → reply VASYA"""
    if not hot.get("reactions.vasya_enabled", settings.VASYA_ENABLED):
        logger.info("admin: disabled (reactions.vasya_enabled=False) | user=%s",
                    message.from_user.id if message.from_user else 0)
        return UNHANDLED
    await message.reply("ВАСЯ")
