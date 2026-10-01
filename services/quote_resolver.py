"""MCA-22 (round 10.27, ADR-1028-6 D3) — единый Quote Resolver.

C3: приоритетная лестница §5 ТЗ (детерминированная, LLM-last):

1. Telegram native reply target (`reply_to_message` metadata);
2. Telegram quote metadata (`message.quote` + `quote_author_id`);
3. exact quote inside known parent (reply-цель существует и содержит текст);
4. exact/normalized match in current thread (окно чата);
5. exact match in Own Output Ledger (content_hash, `bot_output_ledger`);
6. bounded local historical search (FTS, bounded limit);
7. unresolved (честный unknown).

Инварианты:
* deterministic metadata закрывает ступени 1–2 БЕЗ LLM (§29);
* fuzzy semantic match ≠ доказанное авторство — fuzzy не поднимается в
  резолв, только в candidate-hint;
* partial quote внутри reply target: quote source/speaker = parent,
  current speaker = sender;
* ручные `>`-цитаты: короткие общие фразы не auto-bind; ≥2 уверенных
  совпадения → `ambiguous`; нет уверенного → `unresolved`;
* sender НИКОГДА не назначается автором цитаты по умолчанию;
* LLM-резолвер (если подключается на ступенях 3–4/6) обязан выбирать
  entity ID из candidate set; `unknown` лучше hallucinated binding —
  в этом модуле LLM не вызывается (bounded-поиск только детерминированный).

Kill-switch `MCA_CANONICAL_ATTRIBUTION_ENABLED`: OFF → `resolve_quote`
возвращает unresolved без побочных эффектов (паритет baseline).
"""
from __future__ import annotations

import dataclasses
import logging
import re

from services import mca_gates

logger = logging.getLogger(__name__)

# ── статусы резолва (§5) ────────────────────────────────────────────────────
QUOTE_RESOLVED = "resolved"
QUOTE_AMBIGUOUS = "ambiguous"
QUOTE_UNRESOLVED = "unresolved"

# Приоритеты лестницы (1–7; наблюдаемость/диагностика).
PRIORITY_NATIVE_REPLY = 1
PRIORITY_TG_QUOTE_METADATA = 2
PRIORITY_EXACT_IN_PARENT = 3
PRIORITY_EXACT_IN_THREAD = 4
PRIORITY_BOT_OUTPUT_LEDGER = 5
PRIORITY_BOUNDED_HISTORY = 6
PRIORITY_UNRESOLVED = 7

# Порог «короткой общей фразы»: <N токенов НЕ auto-bind по тексту
# (ручные `>`-цитаты/копипаста — §5). Native metadata (ступени 1–2) не
# зависит от порога.
_MIN_QUOTE_TOKENS_FOR_TEXT_BIND = 4
# Bounded-поиск (ступень 6): не более N кандидатов FTS, без LLM.
_BOUNDED_HISTORY_LIMIT = 10


@dataclasses.dataclass(frozen=True)
class QuoteResolution:
    """Итог резолва цитаты (frozen; R17-safe — только ID/коды/ref'ы)."""

    status: str                    # resolved|ambiguous|unresolved
    priority: int                  # ступень лестницы 1–7
    quote_source_ref: str | None = None   # `tg:<id>` / `bot_output:<id>` / None
    quote_speaker_entity_id: int | None = None
    quote_speaker_is_bot: bool = False
    self_output: bool = False      # источник — собственный output бота
    candidates: tuple[tuple[str, int | None], ...] = ()   # (ref, speaker)
    reason_code: str | None = None


def _normalized(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _token_count(text: str | None) -> int:
    return len(re.findall(r"[а-яёa-z0-9]+", str(text or "").casefold()))


def _gate_on() -> bool:
    try:
        return mca_gates.canonical_attribution_enabled()
    except Exception:                                     # pragma: no cover
        return True


def _emit(reason_code: str, **fields) -> None:
    try:
        from services import mca_events
        mca_events.emit_mca_event("quote_resolver_step",
                                  outcome="success",
                                  component="quote_resolver",
                                  reason_code=reason_code, **fields)
    except Exception:                                     # pragma: no cover
        pass


async def resolve_quote(
        db, *, chat_id: int, sender_entity_id: int | None,
        quote_text: str | None = None,
        reply_to_tg_message_id: int | None = None,
        reply_to_speaker_entity_id: int | None = None,
        tg_quote_text: str | None = None,
        tg_quote_author_id: int | None = None,
        bot_user_id: int | None = None,
        thread_texts: list[tuple[str | None, int | None]] | None = None,
        exclude_tg_message_id: int | None = None,
) -> QuoteResolution:
    """Единый резолв цитаты (лестница 1–7, deterministic-first).

    `thread_texts` — [(text, author_entity_id), ...] текущего окна/ветки
    (готовит вызывающий из canonical projection — batch, без N+1).
    `exclude_tg_message_id` — identity ТЕКУЩЕГО сообщения-триггера: оно
    исключается из кандидатов ступени 6, иначе ручная `>`-цитата в самом
    триггере всегда находила бы «второго автора» (цитирующего) и любой
    живой manual-quote резолв вырождался бы в ambiguous. Self-restatement
    (повтор sender'ом СОБСТВЕННОЙ старой фразы из другого сообщения)
    остаётся ambiguous — исключается только сам триггер (fix M-2 wiring).
    Никогда не бросает."""
    if not _gate_on():
        return QuoteResolution(status=QUOTE_UNRESOLVED,
                               priority=PRIORITY_UNRESOLVED,
                               reason_code="quote_unresolved")
    try:
        return await _resolve(db, chat_id=chat_id,
                              sender_entity_id=sender_entity_id,
                              quote_text=quote_text,
                              reply_to_tg_message_id=reply_to_tg_message_id,
                              reply_to_speaker_entity_id=
                              reply_to_speaker_entity_id,
                              tg_quote_text=tg_quote_text,
                              tg_quote_author_id=tg_quote_author_id,
                              bot_user_id=bot_user_id,
                              thread_texts=thread_texts,
                              exclude_tg_message_id=exclude_tg_message_id)
    except Exception:
        logger.warning("[mca22] quote resolver failed", exc_info=True)
        return QuoteResolution(status=QUOTE_UNRESOLVED,
                               priority=PRIORITY_UNRESOLVED,
                               reason_code="quote_unresolved")


async def _resolve(db, *, chat_id, sender_entity_id, quote_text,
                   reply_to_tg_message_id, reply_to_speaker_entity_id,
                   tg_quote_text, tg_quote_author_id, bot_user_id,
                   thread_texts, exclude_tg_message_id=None) -> QuoteResolution:
    # ── 1. native reply target (Telegram metadata) ──────────────────────────
    if reply_to_tg_message_id is not None:
        ref = f"tg:{int(reply_to_tg_message_id)}"
        _emit("quote_resolved", chat_id=int(chat_id),
              message_id=(int(reply_to_tg_message_id)
                          if reply_to_tg_message_id is not None else None))
        return QuoteResolution(
            status=QUOTE_RESOLVED, priority=PRIORITY_NATIVE_REPLY,
            quote_source_ref=ref,
            quote_speaker_entity_id=reply_to_speaker_entity_id,
            quote_speaker_is_bot=(
                bot_user_id is not None
                and reply_to_speaker_entity_id == bot_user_id),
            self_output=(bot_user_id is not None
                         and reply_to_speaker_entity_id == bot_user_id),
            reason_code="quote_resolved")

    # ── 2. Telegram quote metadata ───────────────────────────────────────────
    if tg_quote_author_id is not None or tg_quote_text:
        # Автор цитаты — только честный metadata; при отсутствии автор-поля
        # резолв НЕ выдумывается (unknown, sender не подставляется).
        resolved_author = tg_quote_author_id
        if resolved_author is not None:
            _emit("quote_resolved", chat_id=int(chat_id))
            return QuoteResolution(
                status=QUOTE_RESOLVED, priority=PRIORITY_TG_QUOTE_METADATA,
                quote_source_ref=None,
                quote_speaker_entity_id=int(resolved_author),
                quote_speaker_is_bot=(bot_user_id is not None
                                      and int(resolved_author) == bot_user_id),
                self_output=(bot_user_id is not None
                             and int(resolved_author) == bot_user_id),
                reason_code="quote_resolved")

    qtext = _normalized(quote_text or tg_quote_text)
    manual_quote = bool(quote_text) and not tg_quote_text

    # ── 3. exact quote inside known parent ──────────────────────────────────
    # (родитель известен только вместе с native reply metadata — тогда
    # срабатывает ступень 1; отдельного «parent без metadata» контракта нет:
    # partial quote внутри reply target наследует speaker=parent и покрыт
    # ступенью 1, current speaker = sender — обязанность ClaimEnvelope.)

    # ── 4. exact/normalized match in current thread ─────────────────────────
    if qtext and _token_count(qtext) >= _MIN_QUOTE_TOKENS_FOR_TEXT_BIND:
        hits: list[tuple[str, int | None]] = []
        if thread_texts:
            for text, author in thread_texts:
                if text and qtext in _normalized(text):
                    hits.append(("thread", author))
        # ≥2 разных авторов → ambiguous; ровно 1 уверенный → resolved
        distinct_authors = {a for _, a in hits if a is not None}
        if len(distinct_authors) == 1:
            author = next(iter(distinct_authors))
            # sender никогда не назначается автором цитаты по умолчанию:
            # совпадение текста с собственной репликой sender'а — НЕ proof,
            # что он автор цитаты (self-restatement), → ambiguous, если
            # больше никого.
            if sender_entity_id is not None and author == sender_entity_id:
                return QuoteResolution(
                    status=QUOTE_AMBIGUOUS,
                    priority=PRIORITY_EXACT_IN_THREAD,
                    candidates=tuple(hits[:_BOUNDED_HISTORY_LIMIT]),
                    reason_code="quote_ambiguous")
            _emit("quote_resolved", chat_id=int(chat_id))
            return QuoteResolution(
                status=QUOTE_RESOLVED, priority=PRIORITY_EXACT_IN_THREAD,
                quote_source_ref=None,
                quote_speaker_entity_id=author,
                quote_speaker_is_bot=(bot_user_id is not None
                                      and author == bot_user_id),
                self_output=(bot_user_id is not None
                             and author == bot_user_id),
                reason_code="quote_resolved")
        if len(distinct_authors) > 1:
            return QuoteResolution(
                status=QUOTE_AMBIGUOUS, priority=PRIORITY_EXACT_IN_THREAD,
                candidates=tuple(hits[:_BOUNDED_HISTORY_LIMIT]),
                reason_code="quote_ambiguous")

    # ── 5. exact match in Own Output Ledger ─────────────────────────────────
    if db is not None and qtext:
        try:
            from services import bot_output_ledger
            record = await bot_output_ledger.find_bot_output_by_text(
                db, chat_id, str(quote_text or tg_quote_text or ""))
            if record is not None:
                _emit("quote_resolved", chat_id=int(chat_id))
                return QuoteResolution(
                    status=QUOTE_RESOLVED,
                    priority=PRIORITY_BOT_OUTPUT_LEDGER,
                    quote_source_ref=bot_output_ledger
                    .bot_output_source_ref_id(record["output_id"]),
                    quote_speaker_entity_id=bot_user_id,
                    quote_speaker_is_bot=True, self_output=True,
                    reason_code="quote_resolved")
        except Exception:                                 # pragma: no cover
            pass

    # ── 6. bounded local historical search (детерминированный FTS) ─────────
    # Ручные `>`-цитаты/копипаста тоже проходят: auto-bind только при
    # единственном уверенном exact-совпадении (не sender); короткие общие
    # фразы отсечены порогом токенов; ≥2 авторов → ambiguous (ступень выше).
    if db is not None and qtext and \
            _token_count(qtext) >= _MIN_QUOTE_TOKENS_FOR_TEXT_BIND:
        try:
            from services.summary_memory import build_fts_query
            keywords = re.findall(r"[а-яёa-z0-9]+", qtext)[:8]
            match = build_fts_query(keywords) if keywords else ""
            if match:
                cursor = await db.db.execute(
                    "SELECT id, user_id, text, tg_message_id FROM "
                    "smart_messages WHERE chat_id = ? AND id IN "
                    "(SELECT rowid FROM smart_messages_fts WHERE "
                    "smart_messages_fts MATCH ?) ORDER BY timestamp "
                    "DESC LIMIT ?",
                    (int(chat_id), match,
                     _BOUNDED_HISTORY_LIMIT + 1))
                rows = await cursor.fetchall()
                if exclude_tg_message_id is not None:
                    # триггер сам содержит цитату в `>`-блоке — не автор
                    rows = [r for r in rows
                            if r["tg_message_id"] != exclude_tg_message_id]
                exact = [r for r in rows
                         if qtext in _normalized(r["text"])]
                distinct = {r["user_id"] for r in exact
                            if r["user_id"] is not None}
                if len(distinct) == 1 and \
                        sender_entity_id not in distinct:
                    author = next(iter(distinct))
                    _emit("quote_resolved", chat_id=int(chat_id))
                    return QuoteResolution(
                        status=QUOTE_RESOLVED,
                        priority=PRIORITY_BOUNDED_HISTORY,
                        quote_source_ref=None,
                        quote_speaker_entity_id=author,
                        quote_speaker_is_bot=(bot_user_id is not None
                                              and author == bot_user_id),
                        self_output=(bot_user_id is not None
                                     and author == bot_user_id),
                        reason_code="quote_resolved")
                if len(distinct) > 1 or (len(distinct) == 1 and
                                         sender_entity_id in distinct):
                    return QuoteResolution(
                        status=QUOTE_AMBIGUOUS,
                        priority=PRIORITY_BOUNDED_HISTORY,
                        candidates=tuple(("history", r["user_id"])
                                         for r in exact)
                        [:_BOUNDED_HISTORY_LIMIT],
                        reason_code="quote_ambiguous")
        except Exception:                                 # pragma: no cover
            pass

    # ── 7. unresolved ────────────────────────────────────────────────────────
    _emit("quote_unresolved", chat_id=int(chat_id))
    return QuoteResolution(status=QUOTE_UNRESOLVED,
                           priority=PRIORITY_UNRESOLVED,
                           reason_code="quote_unresolved")
