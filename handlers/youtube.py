"""Epic 37 — YouTube handler (R37-4, Section 46.9.1).
Роутер 0e (после 0d search, ДО 0:admin). Триггер: YT-триггер-фраза
(регистронезависимо, substring) + валидный YouTube-URL (D125-формы).
Reply-таргеты: успех/5.6/5.5 → target.message_id (ЦЕЛЕВОЕ: сценарий А —
message.reply_to_message, сценарий Б — сам message); троттлинг 5.1 →
message.message_id (ВЫЗОВ, D131-прецедент D107).
"""
import logging
import random

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from services.llm_client import LLMBadResponseError, LLMError
from services.persistent_throttling import (
    cooldown_remaining,
    cooldown_touch,
    make_cooldown,
)
from services.smart_cache import get_smart_cache
from services.smartmodule_phrases import (
    LLM_ERROR_PHRASES,
    YOUTUBE_ERROR_PHRASES,
    YOUTUBE_RETRY_PHRASES,   # НОВОЕ (5.8, R41-2)
)
from services.smartmodule_throttling import CooldownTracker
from services.smartmodule_urls import extract_youtube_video_id
from services.smartmodule_utils import (
    _reply,
    react_moai,
    send_chunked_reply,
    throttle_phrase,
)
from services.typing_manager import typing_active
from services.youtube_transcript_engine import YouTubeTranscriptUnavailableException

logger = logging.getLogger(__name__)

youtube_router = Router(name="youtube")

_service = None                                   # YoutubeSummarizerService (DI)
_cooldown = CooldownTracker(settings.YOUTUBE_COOLDOWN_SECONDS)

_YOUTUBE_TRIGGERS: tuple[str, ...] = (
    "транскрипт", "че за видос", "о чем видео", "поясни за видос",
    "перескажи видос", "че в видосе",
)


def setup_youtube(service, db=None) -> None:
    """DI: YoutubeSummarizerService. Вызывается из bot.py on_startup (46.10).
    Epic 60 (63.1): db + THROTTLE_PERSISTENT_ENABLED → персистентный кулдаун
    (throttle_state, scope='youtube')."""
    global _service, _cooldown
    _service = service
    _cooldown = make_cooldown(
        "youtube", settings.YOUTUBE_COOLDOWN_SECONDS, db)


def _has_trigger(text: str) -> bool:
    """Регистронезависимый substring-матч любой триггер-фразы (R37-4)."""
    lowered = text.lower()
    return any(trigger in lowered for trigger in _YOUTUBE_TRIGGERS)


def _make_retry_notifier(bot, chat_id, target_message_id):
    """R41-2/D156: on_retry-замыкание для движка — токсичная фраза из 5.8
    реплаем на ЦЕЛЕВОЕ сообщение (target.message_id), прецедент Reply-To 5.6/5.5.
    Best-effort: если таргет исчез (_reply бросит MessageToReplyNotFound) —
    каскад НЕ падает: движок глушит колбэк logger.exception (50.3)."""
    async def on_retry(attempt: int, max_attempts: int) -> None:
        await _reply(bot, chat_id, random.choice(YOUTUBE_RETRY_PHRASES),
                     target_message_id)
    return on_retry


def _parse(message: types.Message) -> tuple[types.Message | None, str | None]:
    """→ (reply_target, video_id) | (None, None).
    Сценарий А: reply на сообщение с YT-URL → (reply_to_message, video_id);
    D126 (Q2): в replied-сообщении URL нет → fallback на URL в тексте вызова
    → (message, video_id) = сценарий Б; URL нигде нет → НЕ триггер.
    Сценарий Б: URL+триггер в самом сообщении (любой порядок/позиция)."""
    text = (message.text or message.caption or "")
    if not _has_trigger(text):
        return None, None
    reply_target = message.reply_to_message
    if reply_target is not None:
        target_text = (reply_target.text or reply_target.caption or "")
        video_id = extract_youtube_video_id(target_text)
        if video_id is not None:
            return reply_target, video_id
        video_id = extract_youtube_video_id(text)   # D126: fallback на Б
        if video_id is not None:
            return message, video_id
        return None, None
    video_id = extract_youtube_video_id(text)
    if video_id is None:
        return None, None
    return message, video_id


@youtube_router.message()
async def youtube_handler(message: types.Message, bot: Bot = None) -> None:
    if _service is None or bot is None:
        return UNHANDLED
    target, video_id = _parse(message)
    if target is None:
        return UNHANDLED                       # не триггер → пропагация живёт
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[youtube] triggered | chat=%s user=%s video_id=%r",   # R41-5
                message.chat.id, user_id, video_id)
    remaining = await cooldown_remaining(_cooldown, message.chat.id, user_id)
    if remaining > 0:                          # 5.1 → РЕПЛАЙ НА ВЫЗОВ (D131/D107)
        await _reply(bot, message.chat.id, throttle_phrase(remaining), message.message_id)
        return                                # консьюм
    await cooldown_touch(_cooldown, message.chat.id, user_id)
    text = (message.text or message.caption or "")   # Epic 46 (55.5): rag_query
    # Epic 51 (59.2, D210): Exact Match Cache по video_id (канонический
    # идентификатор — разные URL одной ссылки дают один ключ) — ДО
    # транскрипта/LLM. Хит → reply на ТЕКУЩЕЕ сообщение.
    cache = get_smart_cache()
    cache_key = cache.build_key("youtube", video_id)
    cached = await cache.get(cache_key)
    if cached is not None:
        await _reply(bot, message.chat.id, cached, message.message_id)
        logger.info("[youtube] cache hit | chat=%s video_id=%r",
                    message.chat.id, video_id)
        return
    try:
        # Epic 60 (65.7, T-475): «печатает…» от контекста в ИИ до отправки.
        async with typing_active(bot, message.chat.id):
            text_out = await _service.summarize(
                video_id,
                on_retry=_make_retry_notifier(bot, message.chat.id,
                                              target.message_id),
                chat_id=message.chat.id,
                rag_query=text,
            )
            await send_chunked_reply(bot, message.chat.id, text_out, target.message_id)
        await cache.set(cache_key, text_out)      # только успешная генерация (59.2)
        logger.info("[youtube] summary sent | chat=%s video_id=%r",      # R41-5
                    message.chat.id, video_id)
    except LLMBadResponseError as exc:
        # Epic 60 (65.1, T-469): пустой ответ модели → молчание + 🗿 (НЕ R13).
        logger.warning("[youtube] empty answer — silence | chat=%s video_id=%r | error=%s",
                       message.chat.id, video_id, exc)
        await react_moai(bot, message.chat.id, target.message_id)
    except YouTubeTranscriptUnavailableException:
        logger.exception("[youtube] transcript failed | chat=%s video_id=%r",
                         message.chat.id, video_id)                       # R41-5
        await _reply(bot, message.chat.id, random.choice(YOUTUBE_ERROR_PHRASES),  # 5.6 → ЦЕЛЕВОЕ
                     target.message_id)
    except LLMError as exc:
        logger.warning("[youtube] LLM failed | chat=%s video_id=%r | error=%s",  # Epic 47 (D190): WARNING
                       message.chat.id, video_id, exc)
        await _reply(bot, message.chat.id, random.choice(LLM_ERROR_PHRASES),       # 5.5 → ЦЕЛЕВОЕ
                     target.message_id)
    except Exception:
        logger.exception("[youtube] unexpected error | chat=%s video_id=%r",
                         message.chat.id, video_id)                       # R41-5
        await _reply(bot, message.chat.id, random.choice(LLM_ERROR_PHRASES),
                     target.message_id)
