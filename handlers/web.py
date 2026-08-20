"""Epic 37 — Web handler (R37-4, Section 46.9.2).
Роутер 0f (после 0e youtube, ДО 0:admin). Триггер: web-триггер-фраза
(регистронезависимо, substring) + валидный веб-URL (YouTube-URL пропускаются,
D128). Reply-таргеты: успех/5.7/5.5 → target.message_id (ЦЕЛЕВОЕ: сценарий А —
message.reply_to_message, сценарий Б — сам message); троттлинг 5.1 →
message.message_id (ВЫЗОВ, D131-прецедент D107). Кулдаун — ОТДЕЛЬНЫЙ
CooldownTracker (троттлинг YouTube и Web независимы, 46.9).
"""
import logging
import random

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from services.llm_client import LLMError
from services.smart_cache import get_smart_cache
from services.smartmodule_phrases import LLM_ERROR_PHRASES, WEB_ERROR_PHRASES
from services.smartmodule_throttling import CooldownTracker
from services.smartmodule_urls import extract_web_url
from services.smartmodule_utils import _reply, send_chunked_reply, throttle_phrase
from services.web_content_extractor import WebContentExtractionFailedException

logger = logging.getLogger(__name__)

web_router = Router(name="web")

_service = None                                   # WebSummarizerService (DI)
_cooldown = CooldownTracker(settings.WEBPAGE_COOLDOWN_SECONDS)

_WEB_TRIGGERS: tuple[str, ...] = (
    "поясни за ссылку", "че по ссылке", "о чем статья", "поясни за статью",
    "выжимка", "че на сайте", "перескажи статью",
)


def setup_web(service) -> None:
    """DI: WebSummarizerService. Вызывается из bot.py on_startup (46.10)."""
    global _service
    _service = service


def _has_trigger(text: str) -> bool:
    """Регистронезависимый substring-матч любой триггер-фразы (R37-4)."""
    lowered = text.lower()
    return any(trigger in lowered for trigger in _WEB_TRIGGERS)


def _parse(message: types.Message) -> tuple[types.Message | None, str | None]:
    """→ (reply_target, web_url) | (None, None).
    Сценарий А: reply на сообщение с веб-URL → (reply_to_message, url);
    D126 (Q2): в replied-сообщении URL нет → fallback на URL в тексте вызова
    → (message, url) = сценарий Б; URL нигде нет → НЕ триггер.
    Сценарий Б: URL+триггер в самом сообщении (любой порядок/позиция).
    extract_web_url пропускает YouTube-URL (D128)."""
    text = (message.text or message.caption or "")
    if not _has_trigger(text):
        return None, None
    reply_target = message.reply_to_message
    if reply_target is not None:
        target_text = (reply_target.text or reply_target.caption or "")
        url = extract_web_url(target_text)
        if url is not None:
            return reply_target, url
        url = extract_web_url(text)                # D126: fallback на Б
        if url is not None:
            return message, url
        return None, None
    url = extract_web_url(text)
    if url is None:
        return None, None
    return message, url


@web_router.message()
async def web_handler(message: types.Message, bot: Bot = None) -> None:
    if _service is None or bot is None:
        return UNHANDLED
    target, url = _parse(message)
    if target is None:
        return UNHANDLED                       # не триггер → пропагация живёт
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[web] triggered | chat=%s user=%s", message.chat.id, user_id)
    remaining = _cooldown.remaining(message.chat.id, user_id)
    if remaining > 0:                          # 5.1 → РЕПЛАЙ НА ВЫЗОВ (D131/D107)
        await _reply(bot, message.chat.id, throttle_phrase(remaining), message.message_id)
        return                                # консьюм
    _cooldown.touch(message.chat.id, user_id)
    text = (message.text or message.caption or "")   # Epic 46 (55.5): rag_query
    # Epic 51 (59.2, D210): Exact Match Cache — ДО Trafilatura/Tavily/LLM.
    # Хит → reply на ТЕКУЩЕЕ сообщение.
    cache = get_smart_cache()
    cache_key = cache.build_key("web", url)
    cached = await cache.get(cache_key)
    if cached is not None:
        await _reply(bot, message.chat.id, cached, message.message_id)
        logger.info("[web] cache hit | chat=%s", message.chat.id)
        return
    try:
        summary = await _service.summarize(
            url, chat_id=message.chat.id, rag_query=text
        )
        await send_chunked_reply(bot, message.chat.id, summary, target.message_id)
        await cache.set(cache_key, summary)       # только успешная генерация (59.2)
        logger.info("[web] summary sent | chat=%s", message.chat.id)
    except WebContentExtractionFailedException:
        logger.exception("[web] extractor failed | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(WEB_ERROR_PHRASES),      # 5.7 → ЦЕЛЕВОЕ
                     target.message_id)
    except LLMError as exc:
        logger.warning("[web] LLM failed | chat=%s | error=%s",          # Epic 47 (D190): WARNING без traceback
                       message.chat.id, exc)
        await _reply(bot, message.chat.id, random.choice(LLM_ERROR_PHRASES),       # 5.5 → ЦЕЛЕВОЕ
                     target.message_id)
    except Exception:
        logger.exception("[web] unexpected error | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(LLM_ERROR_PHRASES),
                     target.message_id)
