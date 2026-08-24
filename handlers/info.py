"""Epic 43/58 — /info + /edit_info handlers (R43-1/R43-3, D162/D163/D231, Sections 52.6/53.4).

Роутер command-based (прецедент admin_commands, Epic 9), регистрируется
БЕЗУСЛОВНО (LLM не нужен, D162). /info: delete СРАЗУ → нет прав → пул +
ПРОДОЛЖИТЬ (команда висит в чате → справка реплаем) → кулдаун per-chat →
отправка rich через sendRichMessage (Epic 58; TelegramBadRequest → D231:
фолбек sendMessage + parse_mode="HTML" с legacy-эмуляцией Epic 57 → при
неудаче plain). /edit_info: ТОЛЬКО ADMIN_USER_ID; rich-рендер-валидация
превью админу в DM (D163, чат не спамим) → успех → save_text (файл+кэш) →
пул успеха реплаем на команду. Команда /edit_info НЕ удаляется — reply-таргет
должен жить (T-337-C).
"""
import logging
import random

from aiogram import Bot, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import InputRichMessage, ReplyParameters

from config.settings import settings
from services.persistent_throttling import (
    cooldown_remaining,
    cooldown_touch,
    make_cooldown,
)
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

_RICH_TEXT_LIMIT = 32768                          # rich-текст лимит (53.3, T-447)


def _rich_to_legacy_html(text: str) -> str:
    """D231: детерминированная on-the-fly трансформация rich-HTML → legacy-HTML
    (эмуляция Epic 57 как фолбек-вид; 53.3, T-447-B). Порядок существенен:
    шаги 1–2 (h1/h2) ДО шага 3 (<b><i>→<b><i><u>) — фолбек канона Epic 58
    равен канону Epic 57 (34 b / 28 u / 27 i, 2964 симв. < 4096). Guard:
    уже-обёрнутые цитаты Epic 57 (legacy-вход) прячутся за sentinel — шаг 3
    их не дублирует (<u><u>); на rich-каноне (u=0) sentinel-нетронут."""
    text = text.replace("<h1>", "<b><u>").replace("</h1>", "</u></b>")
    text = text.replace("<h2>", "<b>").replace("</h2>", "</b>")
    text = text.replace("<b><i><u>", "<b><i>\x00u>").replace("</u></i></b>", "</u\x00></i></b>")
    text = text.replace("<b><i>", "<b><i><u>").replace("</i></b>", "</u></i></b>")
    text = text.replace("<b><i><u>\x00u>", "<b><i><u>").replace("</u\x00></u></i></b>", "</u></i></b>")
    return text


def setup_info(service, db=None) -> None:
    """DI: InfoService (файл уже загружен .load()). Вызывается из bot.py
    on_startup (52.9). Epic 60 (63.1): db + THROTTLE_PERSISTENT_ENABLED →
    персистентный кулдаун (throttle_state, scope='info')."""
    global _service, _cooldown
    _service = service
    _cooldown = make_cooldown("info", settings.INFO_COOLDOWN_SECONDS, db)


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
    remaining = await cooldown_remaining(_cooldown, message.chat.id, _CHAT_SLOT)
    if remaining > 0:                              # 5.1 (D159)
        await _reply(bot, message.chat.id, throttle_phrase(remaining),
                     message.message_id)
        return
    await cooldown_touch(_cooldown, message.chat.id, _CHAT_SLOT)
    text = _service.get_text()
    reply_parameters = (None if deleted
                        else ReplyParameters(message_id=message.message_id))
    try:                                           # Epic 58: rich (sendRichMessage)
        await bot.send_rich_message(message.chat.id, InputRichMessage(html=text),
                                    reply_parameters=reply_parameters)
        logger.info("[/info] sent (rich) | chat=%s", message.chat.id)
    except TelegramBadRequest:
        # D231: rich отвергнут (файл правлен вручную мимо /edit_info) →
        # legacy-HTML-эмуляция Epic 57 → при неудаче plain. НЕ падаем.
        logger.warning("[/info] rich rejected → legacy HTML fallback | chat=%s",
                       message.chat.id, exc_info=True)
        legacy = _rich_to_legacy_html(text)
        try:
            await send_chunked_reply(bot, message.chat.id, legacy,
                                     None if deleted else message.message_id,
                                     parse_mode="HTML")
        except TelegramBadRequest:
            logger.exception("[/info] legacy HTML rejected → plain fallback | chat=%s",
                             message.chat.id)
            try:
                await send_chunked_reply(bot, message.chat.id, legacy,
                                         None if deleted else message.message_id)
            except Exception:
                logger.exception("[/info] plain fallback failed | chat=%s",
                                 message.chat.id)
        except Exception:
            logger.exception("[/info] send failed | chat=%s", message.chat.id)
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
    if len(new_text) > _RICH_TEXT_LIMIT:           # rich-лимит 32768 (53.3, T-447)
        logger.warning("[/edit_info] text exceeds rich limit | user=%s | chars=%d",
                       user_id, len(new_text))
        await _reply(bot, message.chat.id, random.choice(INFO_BAD_MARKUP_PHRASES),
                     message.message_id)
        return                                     # файл/кэш НЕ трогаем (D163)
    # D163 + Epic 58: rich-рендер-валидация превью админу в DM (не спамить чат)
    try:
        await bot.send_rich_message(settings.ADMIN_USER_ID,
                                    InputRichMessage(html=new_text))
        logger.info("[/edit_info] preview ok (DM, rich) | user=%s | chars=%d",
                    user_id, len(new_text))
    except TelegramBadRequest:
        logger.warning("[/edit_info] bad rich markup rejected by Telegram | user=%s",
                       user_id, exc_info=True)
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
