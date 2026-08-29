"""Epic 33 — FactCheck handler (R33-3, D106/D107, Section 42.7.1).

Роутер 0c (после 0b summary, ДО 0:admin). Observer-стиль (прецедент 0a
summary_observer): не-триггер → return UNHANDLED (пропагация живёт), любой
ответ → консьюм. Триггер: reply/репост, текст вызова начинается со слова
«фактчек» (регистронезависимо, граница слова — «фактчекинг» НЕ матчится).

Reply-таргеты (контракт R33-3): вердикт, 5.3 (пустой контекст), 5.4b
(ошибка поиска), 5.5 (ошибка LLM) → reply на target.message_id (ЦЕЛЕВОЕ);
троттлинг 5.1 → reply на message.message_id (ВЫЗОВ, D107). Кулдаун
FACTCHECK_COOLDOWN_SECONDS per (chat, user), независимый (CooldownTracker).
"""
import logging
import random
import re

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from handlers.summary import _extract_forward_source
from handlers.voice_transcription import _is_transcription_target
from services import hot_config as hot
from services.llm_client import LLMBadResponseError, LLMError
from services.media_group_buffer import get_media_group_caption
from services.persistent_throttling import (
    cooldown_refresh,
    cooldown_remaining,
    cooldown_touch,
    make_cooldown,
)
from services.search_aggregator import AllSearchEnginesFailedException
from services.smart_cache import get_smart_cache
from services.smartmodule_phrases import (
    FACTCHECK_EMPTY_CONTEXT_PHRASES,
    FACTCHECK_ERROR_PHRASES,
    LLM_ERROR_PHRASES,
)
from services.smartmodule_throttling import CooldownTracker
from services.smartmodule_utils import (
    _reply,
    react_moai,
    send_chunked_reply,
    throttle_phrase,
)
from services.typing_manager import typing_active

logger = logging.getLogger(__name__)

factcheck_router = Router(name="factcheck")


async def _fetch_chat_context(chat_id: int, limit: int) -> str:
    """Epic 65: последние limit сообщений чата → <chat_context> блок.
    Fail-open: любая ошибка БД → '' (старое поведение без контекста)."""
    from services.chat_context import format_chat_context   # локальный импорт — без циклов
    if _db is None or limit <= 0:
        return ""
    try:
        rows = await _db.get_recent_messages(chat_id, limit)
        return format_chat_context(rows)
    except Exception:
        logger.warning("[factcheck] chat context fetch failed | chat=%s",
                       chat_id, exc_info=True)
        return ""

_service = None                                   # FactCheckService (DI)
_db = None                                        # Database (Epic 65: chat_context DI)
_cooldown = CooldownTracker(settings.FACTCHECK_COOLDOWN_SECONDS)

_FACTCHECK_TRIGGER_RE = re.compile(r"^фактчек\b", re.IGNORECASE)   # слово целиком («фактчекинг» НЕ матчится)
_HINT_LEAD_RE = re.compile(r"^[\s,:;]+")


def setup_factcheck(service, db=None) -> None:
    """DI: FactCheckService. Вызывается из bot.py on_startup (42.8).
    Epic 60 (63.1): db + THROTTLE_PERSISTENT_ENABLED → персистентный кулдаун
    (throttle_state, scope='factcheck'). Epic 65: db → окно chat_context."""
    global _service, _cooldown, _db
    _service = service
    _db = db
    _cooldown = make_cooldown(
        "factcheck", settings.FACTCHECK_COOLDOWN_SECONDS, db)


def _parse_trigger(message: types.Message) -> tuple[types.Message | None, str | None]:
    """→ (target, user_hint) или (None, None) если не триггер.
    target = message.reply_to_message (основной кейс);
             или message (репост-вариант: forward_origin есть, триггер в caption/text)."""
    text = (message.text or message.caption or "").lstrip()
    match = _FACTCHECK_TRIGGER_RE.match(text)
    if not match:
        return None, None
    target = message.reply_to_message
    if target is None and getattr(message, "forward_origin", None) is not None:
        target = message
    if target is None:
        return None, None                    # текст есть, но нет цели → НЕ триггер
    hint = _HINT_LEAD_RE.sub("", text[match.end():]).strip() or None
    return target, hint


def _extract_target_text(message: types.Message, target: types.Message) -> str | None:
    """Текст целевого сообщения. Приоритет: text/caption → буфер альбома (R36-1) → None (5.3).
    Репост-вариант (target is message): caption несёт триггер — берём только text,
    если он НЕ триггер; иначе None → 5.3 (D121: репост-вариант не меняется)."""
    if target is not message:
        direct = (target.text or target.caption or "").strip()
        if direct:
            return direct
        mgid = getattr(target, "media_group_id", None)   # getattr: MagicMock-safe в тестах
        if mgid:
            caption = get_media_group_caption(mgid)      # caption с 1-го фото альбома
            if caption:
                return caption
        return None
    raw = (target.text or "").strip()
    return raw if raw and not _FACTCHECK_TRIGGER_RE.match(raw) else None


# ── Epic 72 (74.C.3, D275): фактчек на расшифровку ───────────────────

_TRANSCRIPTION_CLAIM_RE = re.compile(r"🗣:\s?(.*)", re.DOTALL)


def _transcription_claim_text(target: types.Message) -> str | None:
    """Чистый клейм из текста расшифровки — всё после анкера «🗣:».
    Telegram хранит .text БЕЗ html-разметки и уже декодированным
    (&lt; → < при отправке), поэтому unescape не нужен. Нет анкера → None."""
    m = _TRANSCRIPTION_CLAIM_RE.search(target.text or "")
    claim = m.group(1).strip() if m else ""
    return claim or None


async def _transcription_forward_author(chat_id: int,
                                        target: types.Message) -> str | None:
    """Epic 72 (74.C.3, D275): автор оригинального голосового из smart_messages
    (цепочка расшифровка→reply_to_message). Приоритет forward_source →
    author_name. Fail-open: нет DI/нет цепочки/нет записи/ошибка БД → None
    (= клейм без атрибуции, прежнее поведение)."""
    orig_id = getattr(getattr(target, "reply_to_message", None),
                      "message_id", None)
    if _db is None or orig_id is None:
        return None
    try:
        row = await _db.get_smart_message_by_tg_id(chat_id, orig_id)
    except Exception:
        logger.warning("[factcheck] transcription author lookup failed",
                       exc_info=True)
        return None
    if row is None:
        return None
    try:
        return row["forward_source"] or row["author_name"] or None
    except (KeyError, IndexError, TypeError):
        return None


@factcheck_router.message()
async def factcheck_handler(message: types.Message, bot: Bot = None) -> None:
    if _service is None or bot is None:
        return UNHANDLED
    user_id = message.from_user.id if message.from_user else 0
    target, user_hint = _parse_trigger(message)
    if target is None:
        return UNHANDLED                       # не триггер → пропагация живёт
    logger.info("[factcheck] triggered | chat=%s user=%s", message.chat.id, user_id)
    # T-619: кулдаун — горячая точка (ConfigCache → settings-фолбек)
    cooldown_refresh(_cooldown, hot.get("limits.factcheck_cooldown_seconds",
                                        settings.FACTCHECK_COOLDOWN_SECONDS))
    remaining = await cooldown_remaining(_cooldown, message.chat.id, user_id)
    if remaining > 0:                          # 5.1 → РЕПЛАЙ НА ВЫЗОВ (message.message_id)
        await _reply(bot, message.chat.id, throttle_phrase(remaining), message.message_id)
        return                                # консьюм (D107: троттлинг — на вызов)
    await cooldown_touch(_cooldown, message.chat.id, user_id)  # слот сразу (42.4)
    target_text = _extract_target_text(message, target)
    if not target_text:                        # 5.3 → РЕПЛАЙ НА ЦЕЛЕВОЕ, БЕЗ поиска
        await _reply(bot, message.chat.id, random.choice(FACTCHECK_EMPTY_CONTEXT_PHRASES),
                     target.message_id)
        return
    forward_source = None
    if getattr(target, "forward_origin", None) is not None:
        forward_source = _extract_forward_source(target.forward_origin)  # reuse handlers/summary.py
    # Epic 72 (74.C.3, D275): реплай на расшифровку → клейм адресуем автору
    # исходного ГС; явный user-forward цели имеет приоритет (не регрессируем
    # существующий репост-вариант). Fail-open: записи нет → без атрибуции.
    if forward_source is None and _is_transcription_target(target):
        claim = _transcription_claim_text(target)
        if claim:
            target_text = claim
        author = await _transcription_forward_author(message.chat.id, target)
        if author:
            forward_source = author
    # Epic 51 (59.2, D210): Exact Match Cache — ДО ресурсоёмких ступеней
    # (поиск/LLM). Хит → reply на ТЕКУЩЕЕ сообщение, БЕЗ вызовов.
    cache = get_smart_cache()
    cache_key = cache.build_key("factcheck", target_text)
    cached = await cache.get(cache_key)
    if cached is not None:
        await _reply(bot, message.chat.id, cached, message.message_id)
        logger.info("[factcheck] cache hit | chat=%s", message.chat.id)
        return
    try:
        # Epic 60 (65.7, T-475): «печатает…» от контекста в ИИ до отправки.
        async with typing_active(bot, message.chat.id):
            chat_context = await _fetch_chat_context(message.chat.id,
                                                     settings.FACTCHECK_CONTEXT_MESSAGES)
            verdict = await _service.check_claim(
                target_text, user_hint, forward_source, chat_id=message.chat.id,
                chat_context=chat_context or None,
            )
            await send_chunked_reply(bot, message.chat.id, verdict, target.message_id)
        await cache.set(cache_key, verdict)      # только успешная генерация (59.2)
        logger.info("[factcheck] verdict sent | chat=%s", message.chat.id)
    except LLMBadResponseError as exc:
        # Epic 60 (65.1, T-469): пустой ответ модели → молчание + 🗿 (НЕ R13).
        logger.warning("[factcheck] empty answer — silence | chat=%s | error=%s",
                       message.chat.id, exc)
        await react_moai(bot, message.chat.id, target.message_id)
    except AllSearchEnginesFailedException:
        logger.exception("[factcheck] search failed | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(FACTCHECK_ERROR_PHRASES),  # 5.4b → ЦЕЛЕВОЕ
                     target.message_id)
    except LLMError as exc:
        logger.warning("[factcheck] LLM failed | chat=%s | error=%s",   # Epic 47 (D190): WARNING без traceback
                       message.chat.id, exc)
        await _reply(bot, message.chat.id, random.choice(LLM_ERROR_PHRASES),       # 5.5 → ЦЕЛЕВОЕ
                     target.message_id)
    except Exception:
        logger.exception("[factcheck] unexpected error | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(LLM_ERROR_PHRASES),       # 5.5 → ЦЕЛЕВОЕ
                     target.message_id)
