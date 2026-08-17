"""Epic 33 — SmartModule shared utils (R33-7, D110, Sections 42.7/42.9).

_reply: best-effort отправка (прецедент _send_ux) — отказ не роняет хендлер.
throttle_phrase: пул 5.1 + подстановка {remaining_time} (.replace, НЕ .format —
прецедент C2).
send_chunked_reply: чанкинг ≤4096 по пробелам (прецедент
SummaryGenerator._chunk_by_whitespace, существующий код НЕ меняем),
reply_to_message_id ТОЛЬКО у первой части, TelegramRetryAfter → sleep + один
повтор (прецедент _send_one_chunk).
"""
import asyncio
import logging
import random

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from config.settings import settings
from services.smartmodule_phrases import THROTTLE_PHRASES
from services.smartmodule_throttling import format_remaining_time
from services.summary_generator import SummaryGenerator   # только статический метод

logger = logging.getLogger(__name__)

_CHUNK_LIMIT = 4096

_REPLY_GONE_MARKER = "message to be replied not found"   # точная строка из прод-логов


def _is_reply_target_gone(exc: TelegramBadRequest) -> bool:
    """aiogram 3.29.1: description лежит в exc.message (TelegramAPIError.__init__).
    Маркер — точная подстрока, БЕЗ регэкспов и БЕЗ .description/.match
    (в aiogram этих атрибутов НЕТ — проверено MRO/сигнатурой)."""
    return _REPLY_GONE_MARKER in (getattr(exc, "message", "") or "")


async def _send_once(bot, chat_id: int, text: str,
                     reply_to_message_id: int | None = None) -> None:
    """Одна отправка с reply-fallback (D112):
    - 400 «message to be replied not found» + reply задан → WARNING (exc_info —
      полный трейс в Betterstack) + РОВНО ОДИН повтор БЕЗ reply → INFO;
    - прочие исключения — НАВЕРХ без изменений (ERROR остаётся делом хендлера);
    - fallback возможен только при заданном reply (у чанков 2+ его нет) —
      единый код для всех чанков, спец-логики по индексу НЕТ (не переусложнять)."""
    try:
        if reply_to_message_id:
            await bot.send_message(chat_id, text, reply_to_message_id=reply_to_message_id)
        else:
            await bot.send_message(chat_id, text)
    except TelegramBadRequest as exc:
        if reply_to_message_id and _is_reply_target_gone(exc):
            logger.warning(
                "SmartModule: reply target gone — retrying without reply_to_message_id | "
                "chat_id=%s msg_id=%s", chat_id, reply_to_message_id, exc_info=True,
            )
            await bot.send_message(chat_id, text)
            logger.info("SmartModule: sent without reply | chat_id=%s", chat_id)
            return
        raise


async def _reply(
    bot, chat_id: int, text: str, reply_to_message_id: int | None = None
) -> None:
    """Best-effort reply (42.7); отказ — WARNING, НЕ роняет хендлер (прецедент _send_ux).
    Fallback «gone»-400 → повтор без reply — внутри _send_once (D112)."""
    if bot is None:
        logger.warning("SmartModule: no bot available to send | chat_id=%s", chat_id)
        return
    try:
        await _send_once(bot, chat_id, text, reply_to_message_id)
    except Exception:
        logger.warning(
            "SmartModule: failed to send reply | chat_id=%s", chat_id, exc_info=True
        )


def throttle_phrase(remaining: float) -> str:
    """5.1: random.choice + подстановка {remaining_time} через .replace (42.7)."""
    return random.choice(THROTTLE_PHRASES).replace(
        "{remaining_time}", format_remaining_time(remaining)
    )


async def send_chunked_reply(
    bot,
    chat_id: int,
    text: str,
    reply_to_message_id: int,
    chunk_delay: float = settings.SUMMARY_CHUNK_DELAY,
) -> None:
    """Прецедент _send_chunked (summary_generator.py), НО с reply-таргетом:
    reply_to_message_id ТОЛЬКО у первой части; остальные — plain send_message.
    TelegramRetryAfter → sleep + один повтор (прецедент _send_one_chunk)."""
    chunks = SummaryGenerator._chunk_by_whitespace(text, _CHUNK_LIMIT)   # существующий код НЕ меняем
    if not chunks:
        logger.warning("SmartModule: empty final text | chat_id=%s", chat_id)
        return
    for index, chunk in enumerate(chunks):
        if len(chunk) > _CHUNK_LIMIT:
            logger.warning(
                "SmartModule: chunk %d exceeds %d chars (%d) | chat_id=%s",
                index, _CHUNK_LIMIT, len(chunk), chat_id,
            )
        reply_id = reply_to_message_id if index == 0 else None
        try:
            await _send_once(bot, chat_id, chunk, reply_id)
        except TelegramRetryAfter as exc:
            logger.warning("TelegramRetryAfter %.1fs — sleeping, one retry | chat_id=%s",
                           exc.retry_after, chat_id)
            await asyncio.sleep(exc.retry_after)
            await _send_once(bot, chat_id, chunk, reply_id)   # повтор ТОЖЕ через _send_once
        if index < len(chunks) - 1:
            await asyncio.sleep(chunk_delay)
