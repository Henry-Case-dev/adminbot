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
Раунд 10.20 (БЛОК 1/О5, ADR-1020-6): escape_lore_html — экранирование текста
истории «Летописца» под parse_mode="HTML" с сохранением whitelist-тегов.
"""
import asyncio
import logging
import random
import re

from aiogram import types
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from config.settings import settings
from services import hot_config as hot
from services.smartmodule_phrases import THROTTLE_PHRASES
from services.smartmodule_throttling import format_remaining_time
from services.summary_generator import SummaryGenerator   # только статический метод
from services.telegram_send import send_text

logger = logging.getLogger(__name__)

_CHUNK_LIMIT = 4096

_REPLY_GONE_MARKER = "message to be replied not found"   # точная строка из прод-логов

# Раунд 10.20 (БЛОК 1/О5, ADR-1020-6): разрешённые Telegram-HTML-теги историй
# Летописца. Всё, что не совпало, экранируется (TelegramBadRequest → фолбэк
# plain-text в direct_chat) — предсказуемость важнее «умного» парсера.
_LORE_HTML_TAG_RE = re.compile(
    r"</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|tg-spoiler|blockquote)>"
    r"|<a\s+href=\"[^\"]*\">|</a>",
    re.IGNORECASE,
)


def escape_lore_html(text: str) -> str:
    """Экранирование HTML-спецсимволов с сохранением разрешённых тегов.

    История «Летописца» доставляется с ``parse_mode="HTML"`` (О5). Модель
    может подсунуть «голые» ``<``/``>``/``&`` — они ломают парсер Telegram.
    Здесь всё вне whitelist-тегов превращается в сущности; при любой ошибке
    парсинга отправки direct_chat повторяет доставку plain-text'ом с
    ИСХОДНЫМ текстом (см. `direct_chat_service`).

    S10.20-11 (Low, принято): Telegram JS не исполняет, истории в TMA пока
    не рендерятся (``{{ }}``) — практической уязвимости нет. При переносе
    историй в TMA ОБЯЗАТЕЛЕН отдельный sanitize (в т.ч. ``<a href="javascript:...">``):
    регэксп ниже пропускает любой href и намеренно НЕ является HTML-sanitizer.
    """
    if not text:
        return ""
    out: list[str] = []
    pos = 0
    for match in _LORE_HTML_TAG_RE.finditer(text):
        out.append(_escape_chunk(text[pos:match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(_escape_chunk(text[pos:]))
    return "".join(out)


def strip_lore_html(text: str) -> str:
    """S10.20-4: убрать whitelist-HTML-теги историй из plain-доставки.

    Нужна фактчекеру/plain-путям: если модель эхом вернула HTML-историю
    (``<b>…</b>``), пользователь не должен видеть сырые теги. Убираются
    только теги из whitelist историй — обычный текст с ``<``/``>`` не
    затрагивается (no-op для вердиктов без разметки)."""
    if not text:
        return ""
    return _LORE_HTML_TAG_RE.sub("", text)


def _escape_chunk(chunk: str) -> str:
    """Текст между тегами → HTML-сущности (``&`` первым — иначе двойное
    экранирование)."""
    return (chunk.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


# ── A8 (раунд 10.26, ADR-1026-21 D1/D3/D5/D8/D10): механика реакции ─────────
# §41: официальный `setMessageReaction` — единственный путь; доступность
# разрешается реактивно; недоступная реакция → детерминированная альтернатива
# или тихий отказ; ошибка реакции НИКОГДА не становится текстом.
# Курируемый стандартный набор (боты — без custom/premium/paid; одна реакция).
REACTION_DEFAULT = "🗿"
REACTION_LAUGH = "😂"
REACTION_APPROVE = "👍"
REACTION_FIRE = "🔥"
STANDARD_REACTION_EMOJIS = frozenset(
    {REACTION_DEFAULT, REACTION_LAUGH, REACTION_APPROVE, REACTION_FIRE})
# Детерминированный порядок альтернатив (без случайности — REQ-A8-09).
REACTION_FALLBACK_ORDER = (REACTION_LAUGH, REACTION_APPROVE, REACTION_FIRE,
                           REACTION_DEFAULT)
# ≤2 попытки на реакцию (D3): достаточно для §41 «альтернатива/отказ»,
# дружелюбно к rate-limit.
MAX_REACTION_ATTEMPTS = 2

# Закрытый R17-safe словарь исходов (D5; ровно 7).
REACTION_OK = "ok"
REACTION_UNAVAILABLE = "unavailable"
REACTION_FORBIDDEN = "forbidden"
REACTION_MESSAGE_GONE = "message_gone"
REACTION_SERVICE = "service"
REACTION_RATE_LIMITED = "rate_limited"
REACTION_UNKNOWN = "unknown"
REACTION_OUTCOMES = frozenset({
    REACTION_OK, REACTION_UNAVAILABLE, REACTION_FORBIDDEN,
    REACTION_MESSAGE_GONE, REACTION_SERVICE, REACTION_RATE_LIMITED,
    REACTION_UNKNOWN,
})

# Классификационные маркеры Telegram-ошибок (lowercase-подстроки; D5).
_REACTION_UNAVAILABLE_MARKERS = ("reaction_invalid",)
_REACTION_FORBIDDEN_MARKERS = (
    "not enough rights", "chat_write_forbidden", "chat_admin_required",
    "bot was blocked",
)
_REACTION_GONE_MARKERS = (
    "message to react not found", "message not found", "message_id_invalid",
)
_REACTION_SERVICE_MARKERS = ("can't react to this message type",)


def reaction_mechanics_enabled() -> bool:
    """A8 kill-switch `REACTION_MECHANICS_ENABLED` (env-only, default ON; D10).

    Резолв per-call; никогда не бросает (fail-safe ON). OFF → точный legacy."""
    try:
        return bool(getattr(settings, "REACTION_MECHANICS_ENABLED", True))
    except Exception:
        return True


def _classify_reaction_error(exc: TelegramBadRequest) -> str:
    """R17-safe классификация ``TelegramBadRequest`` (D5).

    ``REACTION_INVALID`` → unavailable (единственный retryable); права/блок →
    forbidden; удалённое/служебное → gone/service; иначе unknown (безопасно)."""
    msg = str(getattr(exc, "message", "") or "").lower()
    if any(m in msg for m in _REACTION_UNAVAILABLE_MARKERS):
        return REACTION_UNAVAILABLE
    if any(m in msg for m in _REACTION_FORBIDDEN_MARKERS):
        return REACTION_FORBIDDEN
    if any(m in msg for m in _REACTION_GONE_MARKERS):
        return REACTION_MESSAGE_GONE
    if any(m in msg for m in _REACTION_SERVICE_MARKERS):
        return REACTION_SERVICE
    return REACTION_UNKNOWN


def _reaction_candidates(primary: str | None) -> tuple[str, ...]:
    """Детерминированные кандидаты: primary (или 🗿) + первые альтернативы из
    ``REACTION_FALLBACK_ORDER`` без primary, всего ≤ ``MAX_REACTION_ATTEMPTS``."""
    base = primary if primary in STANDARD_REACTION_EMOJIS else REACTION_DEFAULT
    alts = tuple(e for e in REACTION_FALLBACK_ORDER
                 if e != base)[:MAX_REACTION_ATTEMPTS - 1]
    return (base,) + alts


def _warn_reaction_failed(chat_id: int, message_id: int, code: str,
                          reason_code: str | None, *, exc_info: bool = False
                          ) -> None:
    """Единая R17-safe WARNING-строка (сохраняет подстроку
    ``moai reaction failed`` — регресс-совместимость `test_smartmodule_utils`);
    только id/enum/reason/эмодзи-код, без контента (R17)."""
    logger.warning(
        "SmartModule: moai reaction failed | chat=%s msg=%s code=%s reason=%s",
        chat_id, message_id, code, reason_code or "-", exc_info=exc_info)


async def react_moai(bot, chat_id: int, message_id: int | None, *,
                     reaction: str | None = None,
                     reason_code: str | None = None) -> str:
    """Реакция на триггер-сообщение (best-effort, 65.1 + A8 §41-механика).

    Аддитивное расширение: позиционные 3 аргумента сохранены → legacy-сайты
    (handlers/direct safety-net) работают байт-в-байт (🗿, одиночная попытка).
    Новые возможности (контекстный эмодзи + детерминированный fallback)
    включаются ТОЛЬКО при ``reaction is not None`` И kill-switch ON (D11).

    Всегда возвращает R17-safe код исхода (старые вызовы игнорируют возврат).
    НЕ бросает: любая ошибка → WARNING, молчание/текст НЕ порождаются."""
    if bot is None or message_id is None:
        return REACTION_UNKNOWN
    legacy = (reaction is None) or (not reaction_mechanics_enabled())
    candidates = (REACTION_DEFAULT,) if legacy else _reaction_candidates(reaction)
    for index, emoji in enumerate(candidates):
        try:
            # Q8 (aiogram 3.29.1/3.31.0): set_message_reaction(chat_id,
            # message_id, reaction=[ReactionTypeEmoji], is_big=False).
            await bot.set_message_reaction(
                chat_id, message_id,
                reaction=[types.ReactionTypeEmoji(emoji=emoji)], is_big=False)
            if not legacy:
                logger.info(
                    "SmartModule: moai reaction sent | chat=%s msg=%s "
                    "emoji=%s reason=%s",
                    chat_id, message_id, emoji, reason_code or "-")
            return REACTION_OK
        except TelegramRetryAfter:
            # D6: повтор НЕ выполняется (реакция некритична; sleep блокировал
            # бы handler); тихий отказ.
            _warn_reaction_failed(chat_id, message_id, REACTION_RATE_LIMITED,
                                  reason_code, exc_info=True)
            return REACTION_RATE_LIMITED
        except TelegramBadRequest as exc:
            code = _classify_reaction_error(exc)
            # Только `unavailable` retryable → следующая попытка; иначе стоп.
            if code == REACTION_UNAVAILABLE and index + 1 < len(candidates):
                continue
            _warn_reaction_failed(chat_id, message_id, code, reason_code,
                                  exc_info=True)
            return code
        except TelegramForbiddenError:
            # L-1 (REQ-A9-12, ADR-1026-22 D13): HTTP 403 (нет прав/бот
            # заблокирован) — отдельный класс, НЕ подкласс TelegramBadRequest;
            # раньше попадал в generic → REACTION_UNKNOWN. Поведение
            # безопасности идентично (тихий отказ, 0 текста/fallback).
            _warn_reaction_failed(chat_id, message_id, REACTION_FORBIDDEN,
                                  reason_code, exc_info=True)
            return REACTION_FORBIDDEN
        except Exception:
            _warn_reaction_failed(chat_id, message_id, REACTION_UNKNOWN,
                                  reason_code, exc_info=True)
            return REACTION_UNKNOWN
    # Все кандидаты недоступны → тихий отказ (0 реакций, 0 текста).
    _warn_reaction_failed(chat_id, message_id, REACTION_UNAVAILABLE,
                          reason_code)
    return REACTION_UNAVAILABLE


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
            return await send_text(bot, chat_id, text,
                                   reply_to_message_id=reply_to_message_id,
                                   **kwargs)
        return await send_text(bot, chat_id, text, **kwargs)
    except TelegramBadRequest as exc:
        if reply_to_message_id and _is_reply_target_gone(exc):
            logger.warning(
                "SmartModule: reply target gone — retrying without reply_to_message_id | "
                "chat_id=%s msg_id=%s", chat_id, reply_to_message_id, exc_info=True,
            )
            sent = await send_text(bot, chat_id, text, **kwargs)
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
