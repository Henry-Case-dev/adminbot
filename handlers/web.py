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
from services import command_prefix
from services import command_registry
from services import hot_config as hot
from services.llm_client import LLMBadResponseError, LLMError
from services.persistent_throttling import (
    cooldown_refresh,
    cooldown_remaining,
    cooldown_touch,
    make_cooldown,
)
from services.smart_cache import get_smart_cache
from services.smartmodule_concurrency import (
    get_smartmodule_concurrency_pool,
    smartmodule_wait_seconds,
)
from services.smartmodule_phrases import (
    LLM_ERROR_PHRASES,
    COMMAND_NO_TARGET_PHRASES,
    SMARTMODULE_BUSY_PHRASES,
    WEB_ERROR_PHRASES,
)
from services.smartmodule_throttling import CooldownTracker
from services.smartmodule_urls import extract_web_url
from services.smartmodule_utils import (
    _reply,
    react_moai,
    send_chunked_reply,
    throttle_phrase,
)
from services.typing_manager import typing_active
from services.web_content_extractor import WebContentExtractionFailedException

logger = logging.getLogger(__name__)

web_router = Router(name="web")

_service = None                                   # WebSummarizerService (DI)
_cooldown = CooldownTracker(settings.WEBPAGE_COOLDOWN_SECONDS)


def setup_web(service, db=None) -> None:
    """DI: WebSummarizerService. Вызывается из bot.py on_startup (46.10).
    Epic 60 (63.1): db + THROTTLE_PERSISTENT_ENABLED → персистентный кулдаун
    (throttle_state, scope='web')."""
    global _service, _cooldown
    _service = service
    _cooldown = make_cooldown("web", settings.WEBPAGE_COOLDOWN_SECONDS, db)


def _has_trigger(text: str) -> bool:
    """Триггер web как ОТДЕЛЬНОЕ слово (Review-fix M1: правая граница —
    ложные подстроки больше не матчатся)."""
    return command_registry.has_trigger_word("web", text)


def _command_body(message: types.Message) -> str | None:
    """Раунд 10.15 (F6, T-1595): остаток сообщения ПОСЛЕ обязательного префикса.

    None — префикса нет (bare-триггеры больше не работают → UNHANDLED)."""
    text = (message.text or message.caption or "").strip()
    tok, body = command_prefix.split_prefix(text)
    if tok is None:
        return None
    return body


def _triggered_body(message: types.Message) -> str | None:
    """Триггер web при валидной цели (URL); иначе None (НЕ консьюм).

    Раунд 10.15 (F6/F7 + follow-up R10.15-1/-3): симметрично youtube —
    префикс в начале + триггер в начале остатка (явная команда, может быть без
    цели → консьюм), префикс + триггер в любом месте + веб-URL, «ссылка-первой»
    (URL до обращения). Обычная речь со словом-триггером уходит в LLM."""
    text = (message.text or message.caption or "").strip()
    body = _command_body(message)
    if body is not None:
        if command_registry.matches_group("web", body):
            return body
        if _has_trigger(body) and extract_web_url(body) is not None:
            return body
        return None
    # Ссылка-первой (гайд F7 §4): обращение ПОСЛЕ URL. R10.15-10: при
    # повторном обращении берём то, перед которым стоит веб-ссылка.
    tok, rest, at = command_prefix.split_prefix_anywhere(
        text, url_before=lambda prefix: extract_web_url(prefix) is not None)
    if tok is None or at < 0:
        return None
    if extract_web_url(text[:at]) is None:
        return None                       # URL обязан стоять ДО обращения
    if not command_registry.matches_group("web", rest):
        return None
    # body сохраняет URL (нужен `_parse`).
    return (text[:at].rstrip() + " " + rest).strip()


def _parse(message: types.Message) -> tuple[types.Message | None, str | None]:
    """→ (reply_target, web_url) | (None, None).
    Сценарий А: reply на сообщение с веб-URL → (reply_to_message, url);
    D126 (Q2): в replied-сообщении URL нет → fallback на URL в остатке вызова
    → (message, url) = сценарий Б; URL нигде нет → НЕ триггер.
    Сценарий Б: URL+триггер в остатке вызова (любой порядок/позиция).
    Раунд 10.15 (F6): обязательный префикс снимается ДО матча.
    extract_web_url пропускает YouTube-URL (D128)."""
    body = _triggered_body(message)
    if body is None:
        return None, None
    reply_target = message.reply_to_message
    if reply_target is not None:
        target_text = (reply_target.text or reply_target.caption or "")
        url = extract_web_url(target_text)
        if url is not None:
            return reply_target, url
        url = extract_web_url(body)                # D126: fallback на Б
        if url is not None:
            return message, url
        return None, None
    url = extract_web_url(body)
    if url is None:
        return None, None
    return message, url


@web_router.message()
async def web_handler(message: types.Message, bot: Bot = None) -> None:
    if _service is None or bot is None:
        return UNHANDLED
    # Раунд 10.6 (T-1201/A1): master-флаг модуля (default ON).
    if not hot.get("flags.webpage_enabled", settings.WEBPAGE_ENABLED):
        return UNHANDLED
    # Раунд 10.15 (F6, T-1595): обязательный префикс (Имя/«Бот,»). Нет
    # префикса или нет триггера в остатке → UNHANDLED (пропагация живёт).
    body = _triggered_body(message)
    if body is None:
        return UNHANDLED
    target, url = _parse(message)
    if target is None:
        # Триггер есть, цели (URL) нет → консьюм нейтральной фразой
        # (НЕ уходит в LLM обычного ответа, spec §5).
        await _reply(bot, message.chat.id,
                     random.choice(COMMAND_NO_TARGET_PHRASES),
                     message.message_id)
        return
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[web] triggered | chat=%s user=%s", message.chat.id, user_id)
    # T-619: кулдаун — горячая точка (ConfigCache → settings-фолбек)
    cooldown_refresh(_cooldown, hot.get("limits.webpage_cooldown_seconds",
                                        settings.WEBPAGE_COOLDOWN_SECONDS))
    remaining = await cooldown_remaining(_cooldown, message.chat.id, user_id)
    if remaining > 0:                          # 5.1 → РЕПЛАЙ НА ВЫЗОВ (D131/D107)
        await _reply(bot, message.chat.id, throttle_phrase(remaining), message.message_id)
        return                                # консьюм
    await cooldown_touch(_cooldown, message.chat.id, user_id)
    text = body                                    # Epic 46 (55.5): rag_query (без префикса)
    # Epic 51 (59.2, D210): Exact Match Cache — ДО Trafilatura/Tavily/LLM.
    # Хит → reply на ТЕКУЩЕЕ сообщение.
    cache = get_smart_cache()
    cache_key = cache.build_key("web", url)
    cached = await cache.get(cache_key)
    if cached is not None:
        await _reply(bot, message.chat.id, cached, message.message_id)
        logger.info("[web] cache hit | chat=%s", message.chat.id)
        return
    # Раунд N (T-841): слот пула per-chat перед LLM-вызовом summarize
    # (cache-hit выше — быстрый путь БЕЗ пула). Таймаут → busy-фраза.
    pool = get_smartmodule_concurrency_pool()
    permit = await pool.try_acquire(message.chat.id,
                                    timeout=smartmodule_wait_seconds())
    if permit is None:
        logger.warning("[web] concurrency slot timeout | chat=%s",
                       message.chat.id)
        await _reply(bot, message.chat.id,
                     random.choice(SMARTMODULE_BUSY_PHRASES),
                     message.message_id)
        return
    try:
        # Epic 60 (65.7, T-475): «печатает…» от контекста в ИИ до отправки.
        async with typing_active(bot, message.chat.id):
            summary = await _service.summarize(
                url, chat_id=message.chat.id, rag_query=text
            )
            await send_chunked_reply(bot, message.chat.id, summary, target.message_id)
        await cache.set(cache_key, summary)       # только успешная генерация (59.2)
        logger.info("[web] summary sent | chat=%s", message.chat.id)
    except LLMBadResponseError as exc:
        # Epic 60 (65.1, T-469): пустой ответ модели → молчание + 🗿 (НЕ R13).
        logger.warning("[web] empty answer — silence | chat=%s | error=%s",
                       message.chat.id, exc)
        await react_moai(bot, message.chat.id, target.message_id)
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
    finally:
        permit.release()
