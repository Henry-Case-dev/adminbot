"""Epic 33 — SmartSearch handler (R33-4, D106/D107, Section 42.7.2).

Роутер 0d (после 0c factcheck, ДО 0:admin). Observer-стиль (прецедент 0a
summary_observer): не-триггер → return UNHANDLED, любой ответ → консьюм.
Триггер: «найди/поищи/загугли» + регулярка ДОСЛОВНО из ТЗ R33-4
(не «улучшать»; квирки — по ТЗ).

Reply-таргеты (контракт R33-4): ВСЕ ответы (выжимка, 5.1, 5.2, 5.4a, 5.5) —
реплаем на message.message_id. Кулдаун SEARCH_COOLDOWN_SECONDS per (chat, user),
независимый от фактчека (отдельный CooldownTracker, D107).
"""
import logging
import random
import re

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from services.llm_client import LLMBadResponseError, LLMError
from services.persistent_throttling import (
    cooldown_remaining,
    cooldown_touch,
    make_cooldown,
)
from services.search_aggregator import AllSearchEnginesFailedException
from services.smart_cache import get_smart_cache
from services.smartmodule_phrases import (
    LLM_ERROR_PHRASES,
    SEARCH_EMPTY_QUERY_PHRASES,
    SEARCH_ERROR_PHRASES,
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

search_router = Router(name="smartsearch")

_service = None                                   # SearchService (DI)
_db = None                                        # Database (Epic 65: chat_context DI)
_cooldown = CooldownTracker(settings.SEARCH_COOLDOWN_SECONDS)

_SEARCH_PREFIX_RE = re.compile(r"^(?:найди|поищи|загугли)\b", re.IGNORECASE)
# ТЗ R33-4: `^(?i)(?:найди|поищи|загугли)(?:[\s,:]+)(?:мне\s+|пожалуйста\s+)?(.+)$`.
# Python 3.12 отвергает inline-флаг `(?i)` после `^` (re.error: global flags not
# at the start) — семантика сохранена переносом флага в re.IGNORECASE
# (применяется ко всему паттерну — эквивалентно (?i)). Не «улучшать»; квирки — по ТЗ:
_SEARCH_QUERY_RE = re.compile(
    r"^(?:найди|поищи|загугли)(?:[\s,:]+)(?:мне\s+|пожалуйста\s+)?(.+)$",
    re.IGNORECASE,
)


def setup_search(service, db=None) -> None:
    """DI: SearchService. Вызывается из bot.py on_startup (42.8).
    Epic 60 (63.1): db + THROTTLE_PERSISTENT_ENABLED → персистентный кулдаун
    (throttle_state, scope='search'). Epic 65: db → окно chat_context."""
    global _service, _cooldown, _db
    _service = service
    _db = db
    _cooldown = make_cooldown("search", settings.SEARCH_COOLDOWN_SECONDS, db)


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
        logger.warning("[smartsearch] chat context fetch failed | chat=%s",
                       chat_id, exc_info=True)
        return ""


def _parse_search_query(raw: str) -> str | None:
    """None = не триггер → UNHANDLED; "" = триггер без тела → 5.2; иначе — тело запроса."""
    text = raw.strip()
    if not _SEARCH_PREFIX_RE.match(text):
        return None
    m = _SEARCH_QUERY_RE.match(text)
    if not m:
        return ""
    return m.group(1).strip()


@search_router.message()
async def smartsearch_handler(message: types.Message, bot: Bot = None) -> None:
    if _service is None or bot is None:
        return UNHANDLED
    query = _parse_search_query(message.text or message.caption or "")
    if query is None:
        return UNHANDLED                       # не триггер
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[smartsearch] triggered | chat=%s user=%s", message.chat.id, user_id)
    remaining = await cooldown_remaining(_cooldown, message.chat.id, user_id)
    if remaining > 0:                          # 5.1 → message.message_id (как ВСЕ ответы поиска)
        await _reply(bot, message.chat.id, throttle_phrase(remaining), message.message_id)
        return
    await cooldown_touch(_cooldown, message.chat.id, user_id)
    if not query:                              # 5.2 → БЕЗ обращения к поисковикам
        await _reply(bot, message.chat.id, random.choice(SEARCH_EMPTY_QUERY_PHRASES),
                     message.message_id)
        return
    # Epic 51 (59.2, D210): Exact Match Cache — ДО поиска/LLM. Хит → reply
    # на ТЕКУЩЕЕ сообщение, БЕЗ вызовов поисковиков.
    cache = get_smart_cache()
    cache_key = cache.build_key("search", query)
    cached = await cache.get(cache_key)
    if cached is not None:
        await _reply(bot, message.chat.id, cached, message.message_id)
        logger.info("[smartsearch] cache hit | chat=%s", message.chat.id)
        return
    try:
        # Epic 60 (65.7, T-475): «печатает…» от контекста в ИИ до отправки.
        async with typing_active(bot, message.chat.id):
            chat_context = await _fetch_chat_context(message.chat.id,
                                                     settings.SEARCH_CONTEXT_MESSAGES)
            summary = await _service.research(query, chat_id=message.chat.id,
                                              chat_context=chat_context or None)
            await send_chunked_reply(bot, message.chat.id, summary, message.message_id)
        await cache.set(cache_key, summary)    # только успешная генерация (59.2)
        logger.info("[smartsearch] summary sent | chat=%s", message.chat.id)
    except LLMBadResponseError as exc:
        # Epic 60 (65.1, T-469): пустой ответ модели → молчание + 🗿 (НЕ R13).
        logger.warning("[smartsearch] empty answer — silence | chat=%s | error=%s",
                       message.chat.id, exc)
        await react_moai(bot, message.chat.id, message.message_id)
    except AllSearchEnginesFailedException:
        logger.exception("[smartsearch] search failed | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(SEARCH_ERROR_PHRASES),     # 5.4a
                     message.message_id)
    except LLMError as exc:
        logger.warning("[smartsearch] LLM failed | chat=%s | error=%s",   # Epic 47 (D190): WARNING без traceback
                       message.chat.id, exc)
        await _reply(bot, message.chat.id, random.choice(LLM_ERROR_PHRASES),        # 5.5
                     message.message_id)
    except Exception:
        logger.exception("[smartsearch] unexpected error | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(LLM_ERROR_PHRASES),
                     message.message_id)
