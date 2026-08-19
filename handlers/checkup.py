"""Epic 42 — Checkup handler (R42-1, D162, Section 51.7).

Роутер 0g (после 0f web, под гейтом SUMMARY_ENABLED). Observer-стиль
(прецедент 0d search): не-триггер → return UNHANDLED, любой ответ → консьюм.
ВСЕ ответы (отчёт, 5.1, фолбек, dead, LLM-ошибка) — реплаем на
message.message_id (R42-1). Кулдаун per-chat (T-328-C): слот (chat_id, 0).
"""
import logging
import random
import re

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from services.llm_client import LLMError
from services.smartmodule_phrases import (
    CHECKUP_DEAD_PHRASES,
    CHECKUP_FALLBACK_PHRASES,
    CHECKUP_LLM_ERROR_PHRASES,
)
from services.smartmodule_throttling import CooldownTracker
from services.smartmodule_utils import _reply, send_chunked_reply, throttle_phrase
from services.system_logs_fetcher import CheckupLogsUnavailableException

logger = logging.getLogger(__name__)

checkup_router = Router(name="checkup")

_service = None                                   # CheckupService (DI)
_fetcher = None                                   # CheckupLogsFetcher (DI)
_cooldown = CooldownTracker(settings.CHECKUP_COOLDOWN_SECONDS)
_CHAT_SLOT = 0                                    # per-chat кулдаун (T-328-C)

_CHECKUP_TRIGGER_RE = re.compile(
    r"(?:^|[\s\u00ab\u00bb\"'(\[\-])"
    r"(?:чекап|ты в порядке|живой собака|пульс бота|чекни здоровье|как сервак)"
    r"(?=[\s!?.,;:\u2026\u00ab\u00bb)]*$)",
    re.IGNORECASE,
)


def setup_checkup(service, fetcher) -> None:
    """DI: CheckupService + CheckupLogsFetcher. Вызывается из bot.py on_startup (51.9)."""
    global _service, _fetcher
    _service = service
    _fetcher = fetcher


@checkup_router.message()
async def checkup_handler(message: types.Message, bot: Bot = None) -> None:
    if _service is None or _fetcher is None or bot is None:
        return UNHANDLED
    text = (message.text or message.caption or "").strip()
    if not text or not _CHECKUP_TRIGGER_RE.search(text):
        return UNHANDLED                       # не триггер → пропагация живёт
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[checkup] triggered | chat=%s user=%s", message.chat.id, user_id)
    remaining = _cooldown.remaining(message.chat.id, _CHAT_SLOT)
    if remaining > 0:                          # 5.1 → реплай на триггер
        await _reply(bot, message.chat.id, throttle_phrase(remaining),
                     message.message_id)
        return
    _cooldown.touch(message.chat.id, _CHAT_SLOT)
    try:
        logs, used_fallback = await _fetcher.fetch()
    except CheckupLogsUnavailableException:
        logger.exception("[checkup] all log sources failed | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(CHECKUP_DEAD_PHRASES),
                     message.message_id)
        return
    if used_fallback:                          # R42-2: фолбек-фраза ДО LLM (юзер ждёт)
        logger.warning("[checkup] fallback phrase sent | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(CHECKUP_FALLBACK_PHRASES),
                     message.message_id)
    try:
        report = await _service.checkup(logs, used_fallback)
        await send_chunked_reply(bot, message.chat.id, report, message.message_id)
        logger.info("[checkup] report sent | chat=%s", message.chat.id)
    except LLMError:
        logger.exception("[checkup] LLM failed | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(CHECKUP_LLM_ERROR_PHRASES),
                     message.message_id)
    except Exception:
        logger.exception("[checkup] unexpected error | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(CHECKUP_LLM_ERROR_PHRASES),
                     message.message_id)
