"""Epic 43 — /info + /edit_info handlers (R43-1/R43-3, D162/D163, Section 52.6/53.4).

Роутер command-based (прецедент admin_commands, Epic 9), регистрируется
БЕЗУСЛОВНО (LLM не нужен, D162). /info: delete СРАЗУ → нет прав → пул +
ПРОДОЛЖИТЬ (команда висит в чате → справка реплаем) → кулдаун per-chat →
отправка HTML (TelegramBadRequest → plain-фолбек). /edit_info: ТОЛЬКО
ADMIN_USER_ID; рендер-валидация превью админу в DM (D163, чат не спамим) →
успех → save_text (файл+кэш) → пул успеха реплаем на команду. Команда
/edit_info НЕ удаляется — reply-таргет должен жить (T-337-C).
"""
import logging
import random

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command

from config.settings import settings
from services.smartmodule_phrases import (
    INFO_BAD_MARKUP_PHRASES,
    INFO_EDIT_OK_PHRASES,
    INFO_NO_DELETE_RIGHTS_PHRASES,
    INFO_NOT_ADMIN_PHRASES,
)
from services.smartmodule_throttling import CooldownTracker
from services.smartmodule_utils import _reply, send_chunked_reply, throttle_phrase

logger = logging.getLogger(__name__)

info_router = Router(name="info")

_service = None                                   # InfoService (DI)
_cooldown = CooldownTracker(settings.INFO_COOLDOWN_SECONDS)
_CHAT_SLOT = 0                                    # per-chat кулдаун (T-336-C)


def setup_info(service) -> None:
    """DI: InfoService (файл уже загружен .load()). Вызывается из bot.py on_startup (52.9)."""
    global _service
    _service = service


@info_router.message(Command("info"))
async def cmd_info(message: types.Message, bot: Bot = None) -> None:
    if _service is None or bot is None:
        logger.warning("[/info] InfoService not initialized — skipping")
        return
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[/info] triggered | chat=%s user=%s", message.chat.id, user_id)
    deleted = True                                 # R44-2 (53.4): отказ delete — НЕ стоп
    try:                                           # R43-1: удалить СРАЗУ
        await message.delete()
        logger.info("[/info] command deleted | chat=%s msg=%s",
                    message.chat.id, message.message_id)
    except Exception:
        logger.warning("[/info] delete failed (no delete_messages right?) | chat=%s",
                       message.chat.id, exc_info=True)
        await _reply(bot, message.chat.id, random.choice(INFO_NO_DELETE_RIGHTS_PHRASES),
                     message.message_id)
        deleted = False                            # команда висит → справка РЕПЛАЕМ
    remaining = _cooldown.remaining(message.chat.id, _CHAT_SLOT)
    if remaining > 0:                              # 5.1 (D159)
        await _reply(bot, message.chat.id, throttle_phrase(remaining),
                     message.message_id)
        return
    _cooldown.touch(message.chat.id, _CHAT_SLOT)
    text = _service.get_text()
    reply_to = None if deleted else message.message_id
    try:
        await send_chunked_reply(bot, message.chat.id, text, reply_to, parse_mode="HTML")
        logger.info("[/info] sent | chat=%s", message.chat.id)
    except TelegramBadRequest:
        # файл правлен вручную мимо /edit_info → plain-деградация, НЕ падаем
        logger.exception("[/info] HTML markup rejected → plain fallback | chat=%s",
                         message.chat.id)
        try:
            await send_chunked_reply(bot, message.chat.id, text, reply_to)
        except Exception:
            logger.exception("[/info] plain fallback failed | chat=%s", message.chat.id)
    except Exception:
        logger.exception("[/info] send failed | chat=%s", message.chat.id)


@info_router.message(Command("edit_info"))
async def cmd_edit_info(message: types.Message, bot: Bot = None) -> None:
    if _service is None or bot is None:
        logger.warning("[/edit_info] InfoService not initialized — skipping")
        return
    user_id = message.from_user.id if message.from_user else 0
    if user_id != settings.ADMIN_USER_ID:          # R43-3: ТОЛЬКО админ
        logger.info("[/edit_info] denied | user=%s", user_id)
        await _reply(bot, message.chat.id, random.choice(INFO_NOT_ADMIN_PHRASES),
                     message.message_id)
        return
    args = (message.text or "").split(maxsplit=1)
    new_text = args[1] if len(args) > 1 else ""
    if not new_text.strip():                       # T-337-D: пустой аргумент
        logger.info("[/edit_info] empty arg → current text shown | user=%s", user_id)
        await _reply(bot, message.chat.id, _service.get_text(), message.message_id)
        return
    # D163: рендер-валидация превью админу в DM (не спамить чат)
    try:
        await bot.send_message(settings.ADMIN_USER_ID, new_text, parse_mode="HTML")
        logger.info("[/edit_info] preview ok (DM) | user=%s | chars=%d",
                    user_id, len(new_text))
    except TelegramBadRequest:
        logger.exception("[/edit_info] bad markup rejected by Telegram | user=%s", user_id)
        await _reply(bot, message.chat.id, random.choice(INFO_BAD_MARKUP_PHRASES),
                     message.message_id)
        return                                     # файл/кэш НЕ трогаем (D163)
    except Exception:
        logger.exception("[/edit_info] preview send failed | user=%s", user_id)
        await _reply(bot, message.chat.id, random.choice(INFO_BAD_MARKUP_PHRASES),
                     message.message_id)
        return
    try:
        _service.save_text(new_text)               # файл + кэш (52.3)
    except OSError:
        logger.exception("[/edit_info] file write failed | user=%s", user_id)
        await _reply(bot, message.chat.id, random.choice(INFO_BAD_MARKUP_PHRASES),
                     message.message_id)
        return                                     # кэш остался старым
    await _reply(bot, message.chat.id, random.choice(INFO_EDIT_OK_PHRASES),
                 message.message_id)               # реплаем на /edit_info (T-337-C)
