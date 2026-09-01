"""Epic 33 — SmartModule shared utils (R33-7, D110, Sections 42.7/42.9).

_reply: best-effort отправка (прецедент _send_ux) — отказ не роняет хендлер.
throttle_phrase: пул 5.1 + подстановка {remaining_time} (.replace, НЕ .format —
прецедент C2).
send_chunked_reply: чанкинг ≤4096 по пробелам (прецедент
SummaryGenerator._chunk_by_whitespace, существующий код НЕ меняем),
reply_to_message_id ТОЛЬКО у первой части, TelegramRetryAfter → sleep + один
повтор (прецедент _send_one_chunk).
react_moai (Epic 60, 65.1, T-469): best-effort реакция 🗿 на триггер-сообщение
при пустом ответе модели; НЕ бросает (молчание гарантировано отсутствием
send_message — реакция только дополняет его).
"""
import asyncio
import logging
import random

from aiogram import types
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from config.settings import settings
from services import hot_config as hot
from services.smartmodule_phrases import THROTTLE_PHRASES
from services.smartmodule_throttling import format_remaining_time
from services.summary_generator import SummaryGenerator   # только статический метод

logger = logging.getLogger(__name__)

_CHUNK_LIMIT = 4096

_REPLY_GONE_MARKER = "message to be replied not found"   # точная строка из прод-логов


async def react_moai(bot, chat_id: int, message_id: int | None) -> None:
    """🗿 на триггер-сообщение (best-effort, 65.1). НЕ бросает: любая ошибка
    реакции (в т.ч. удалённый триггер) → WARNING, молчание НЕ нарушается.
    Q8 (aiogram 3.29.1): Bot.set_message_reaction(chat_id, message_id,
    reaction=[ReactionTypeEmoji], is_big=None) — сигнатура подтверждена
    inspect-ом при реализации."""
    if bot is None or message_id is None:
        return
    try:
        await bot.set_message_reaction(
            chat_id, message_id,
            reaction=[types.ReactionTypeEmoji(emoji="🗿")], is_big=False)
    except Exception:
        logger.warning("SmartModule: moai reaction failed | chat=%s msg=%s",
                       chat_id, message_id, exc_info=True)


def _is_reply_target_gone(exc: TelegramBadRequest) -> bool:
    """aiogram 3.29.1: description лежит в exc.message (TelegramAPIError.__init__).
    Маркер — точная подстрока, БЕЗ регэкспов и БЕЗ .description/.match
    (в aiogram этих атрибутов НЕТ — проверено MRO/сигнатурой)."""
    return _REPLY_GONE_MARKER in (getattr(exc, "message", "") or "")


async def _send_once(bot, chat_id: int, text: str,
                     reply_to_message_id: int | None = None,
                     parse_mode: str | None = None):
    """Одна отправка с reply-fallback (D112):
    - 400 «message to be replied not found» + reply задан → WARNING (exc_info —
      полный трейс в Betterstack) + РОВНО ОДИН повтор БЕЗ reply → INFO;
    - прочие исключения — НАВЕРХ без изменений (ERROR остаётся делом хендлера);
    - fallback возможен только при заданном reply (у чанков 2+ его нет) —
      единый код для всех чанков, спец-логики по индексу НЕТ (не переусложнять);
    - parse_mode (Epic 43, 52.2) — опциональный kwarg, None → БЕЗ ключа
      (обратная совместимость существующих вызовов).
    Возвращает отправленное Message (или None) — Epic 50: DirectChatService
    хранит id ответа бота (bot_replies, 58.6)."""
    kwargs: dict = {}
    if parse_mode:
        kwargs["parse_mode"] = parse_mode
    try:
        if reply_to_message_id:
            return await bot.send_message(chat_id, text, reply_to_message_id=reply_to_message_id, **kwargs)
        return await bot.send_message(chat_id, text, **kwargs)
    except TelegramBadRequest as exc:
        if reply_to_message_id and _is_reply_target_gone(exc):
            logger.warning(
                "SmartModule: reply target gone — retrying without reply_to_message_id | "
                "chat_id=%s msg_id=%s", chat_id, reply_to_message_id, exc_info=True,
            )
            sent = await bot.send_message(chat_id, text, **kwargs)
            logger.info("SmartModule: sent without reply | chat_id=%s", chat_id)
            return sent
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
    parse_mode: str | None = None,
):
    """Прецедент _send_chunked (summary_generator.py), НО с reply-таргетом:
    reply_to_message_id ТОЛЬКО у первой части; остальные — plain send_message.
    TelegramRetryAfter → sleep + один повтор (прецедент _send_one_chunk).
    parse_mode (Epic 43, 52.2) — опциональный kwarg для всех чанков
    (обратная совместимость: существующие вызовы без kwarg не меняются).
    Возвращает message_id ПЕРВОЙ (реплай-)части или None — Epic 50 (58.6):
    DirectChatService хранит id ответа бота (bot_replies) для цепочек reply."""
    # Миграция read-пути: пауза между чанками из админки (не бейкдится в дефолте)
    chunk_delay = hot.get("limits.summary_chunk_delay", chunk_delay)
    chunks = SummaryGenerator._chunk_by_whitespace(text, _CHUNK_LIMIT)   # существующий код НЕ меняем
    if not chunks:
        logger.warning("SmartModule: empty final text | chat_id=%s", chat_id)
        return None
    sent_id = None
    for index, chunk in enumerate(chunks):
        if len(chunk) > _CHUNK_LIMIT:
            logger.warning(
                "SmartModule: chunk %d exceeds %d chars (%d) | chat_id=%s",
                index, _CHUNK_LIMIT, len(chunk), chat_id,
            )
        reply_id = reply_to_message_id if index == 0 else None
        try:
            sent = await _send_once(bot, chat_id, chunk, reply_id, parse_mode)
        except TelegramRetryAfter as exc:
            logger.warning("TelegramRetryAfter %.1fs — sleeping, one retry | chat_id=%s",
                           exc.retry_after, chat_id)
            await asyncio.sleep(exc.retry_after)
            sent = await _send_once(bot, chat_id, chunk, reply_id, parse_mode)   # повтор ТОЖЕ через _send_once
        if index == 0 and sent is not None and getattr(sent, "message_id", None) is not None:
            sent_id = sent.message_id
        if index < len(chunks) - 1:
            await asyncio.sleep(chunk_delay)
    return sent_id
