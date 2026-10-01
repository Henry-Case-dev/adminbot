"""MCA-22 (round 10.27, ADR-1028-6 D2) — Durable Own Output Ledger.

C2: реально отправленные ответы бота живут дольше TTL `bot_replies`
(3600 с) — durable-таблица `mca_bot_outputs` (DDL v22, append-only).
Наружу — через SourceRef `store='sqlite', entity_type='message',
entity_id='bot_output:<id>'` (совместимо с mca-04a).

Evidence-политика (§4/§14): bot output — допустимое evidence для
«бот раньше говорил X» (via `provenance.is_self_referential_origin`),
НЕДОПУСТИМОЕ как независимое подтверждение «X правда о человеке»
(`independence='self_referential'`).

Изоляция (§4 ТЗ): в `smart_messages` НЕ пишем (human-only corpus);
`bot_replies` остаётся быстрым TTL-кешем (контракт 63.1).

Kill-switch `MCA_BOT_OUTPUT_LEDGER_ENABLED`: OFF → не пишем/не читаем;
quote-priority 5 недоступна (лестница C3 падает на 6/7).
"""
from __future__ import annotations

import hashlib
import logging
import time

from services import mca_gates
from services.database import BOT_OUTPUT_KINDS

logger = logging.getLogger(__name__)

# Версия контракта ledger (наблюдаемость).
BOT_OUTPUT_LEDGER_VERSION = "mca22/ledger/v1"

# Fix round-1 (M-4): default-DB binding для send-путей БЕЗ DI-доступа к
# DatabaseService (SummaryGenerator, relays, download-хендлер). Привязка —
# из `setup_summary` (bot.py on_startup, тот же db, что и у direct).
# None → запись честно скипается (fail-open, см. `record_delivered_output`).
_default_db = None


def bind_default_db(db) -> None:
    """Привязать DatabaseService для вызовов `record_delivered_output`
    без явного db (idempotent-сеттер; None отвязывает — для тестов)."""
    global _default_db
    _default_db = db


def _resolve_db(db):
    """Явный db приоритетен; иначе default-binding; None → skip."""
    return db if db is not None else _default_db


def ledger_enabled() -> bool:
    """`MCA_BOT_OUTPUT_LEDGER_ENABLED` (per-call, никогда не бросает)."""
    try:
        return mca_gates.bot_output_ledger_enabled()
    except Exception:                                     # pragma: no cover
        return True


def content_hash(text: str | None, caption: str | None = None) -> str | None:
    """Стабильный hash контента output (REUSE семантика
    `message_identity.message_content_hash`: разделитель `\\x00`)."""
    if not text and not caption:
        return None
    material = f"{text or ''}\x00{caption or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def bot_output_source_ref_id(output_id: int) -> str:
    """Стабильный entity_id SourceRef для ledger-строки."""
    return f"bot_output:{int(output_id)}"


def validate_kind(output_kind: str | None) -> str:
    """Закрытый набор output_kind; неизвестное → честный `other`."""
    kind = str(output_kind or "").strip() or "other"
    return kind if kind in BOT_OUTPUT_KINDS else "other"


async def record_delivered_output(
        db, *, chat_id: int, tg_message_id: int | None, text: str | None,
        caption: str | None = None, bot_user_id: int | None = None,
        output_kind: str = "direct_reply", sent_at: int | None = None,
        parent_message_ref: str | None = None, correlation_id: str | None
        = None, source_feature: str | None = None, revision_no: int = 1,
        created_at: int | None = None) -> int | None:
    """Записать ДОСТАВЛЕННЫЙ output (после успешной send).

    `db` может быть None — тогда берётся default-binding
    (`bind_default_db`; send-пути summary/relays/download без DI).
    DB недоступна → None (честный skip, без записи — фикс round-1 M-4
    НЕ создаёт скрытых fallback-хранилищ).

    Недоставленный draft НЕ записывается write-path'ом фичи — «недоставленное
    ≠ слова бота» (§4); это решение фиксируется событием
    `bot_output_undelivered_skipped` на вызывающей стороне. Правка
    собственного сообщения → новая revision-строка (append-only).

    Возвращает output_id (SourceRef `bot_output:<id>`) либо None (fail-open).
    Gate OFF → None без записи (паритет baseline)."""
    if not ledger_enabled():
        return None
    target_db = _resolve_db(db)
    if target_db is None:
        return None
    try:
        output_id = await target_db.record_bot_output(
            chat_id=int(chat_id), bot_user_id=bot_user_id,
            tg_message_id=(int(tg_message_id)
                           if tg_message_id is not None else None),
            revision_no=max(1, int(revision_no or 1)),
            sent_at=(int(sent_at) if sent_at is not None
                     else int(created_at or time.time())),
            parent_message_ref=parent_message_ref,
            output_kind=validate_kind(output_kind),
            content_text=(str(text) if text else None),
            content_ref=(f"caption_of:{int(tg_message_id)}"
                         if caption and not text and tg_message_id is not None
                         else None),
            content_hash=content_hash(text, caption),
            correlation_id=correlation_id,
            source_feature=source_feature,
            delivery_status="delivered",
            created_at=(int(created_at) if created_at is not None else None))
        if output_id is not None:
            try:
                from services import mca_events
                mca_events.emit_mca_event(
                    "bot_output_recorded", outcome="success",
                    component="bot_output_ledger", chat_id=int(chat_id),
                    message_id=(int(tg_message_id)
                                if tg_message_id is not None else None),
                    reason_code="bot_output_recorded",
                    entity_ids=[bot_output_source_ref_id(output_id)])
            except Exception:                             # pragma: no cover
                pass
        return output_id
    except Exception:
        logger.warning("[mca22] ledger record failed | chat=%s", chat_id,
                       exc_info=True)
        return None


async def resolve_bot_output_by_tg(db, chat_id: int,
                                   tg_message_id: int) -> dict | None:
    """Ledger-строка по `(chat_id, tg_message_id)` (quote-priority 5, §5).

    Gate OFF → None (лестница падает на 6/7 — паритет baseline)."""
    if not ledger_enabled():
        return None
    return await db.get_bot_output_by_tg(chat_id, tg_message_id)


async def find_bot_output_by_text(db, chat_id: int, text: str | None,
                                  caption: str | None = None) -> dict | None:
    """Exact-match поиск output по стабильному content_hash (§5 priority 5).

    Только точное совпадение хеша; fuzzy-совпадение авторством НЕ считается
    (C3: fuzzy semantic match ≠ доказанное авторство)."""
    if not ledger_enabled():
        return None
    digest = content_hash(text, caption)
    if not digest:
        return None
    matches = await db.find_bot_outputs_by_hash(chat_id, digest)
    return matches[0] if matches else None


def bot_output_as_message_dict(record: dict) -> dict:
    """Ledger-строка → совместимое представление «сообщения» для
    thread_chain/quote-resolver (bot-side walk сквозь ход бота старше TTL).

    `entity_id` SourceRef доступен через `bot_output_source_ref_id`."""
    return {
        "bot_output_id": record.get("output_id"),
        "chat_id": record.get("chat_id"),
        "tg_message_id": record.get("tg_message_id"),
        "revision_no": record.get("revision_no") or 1,
        "sent_at": record.get("sent_at"),
        "parent_message_ref": record.get("parent_message_ref"),
        "output_kind": record.get("output_kind"),
        "text": record.get("content_text"),
        "content_hash": record.get("content_hash"),
        "correlation_id": record.get("correlation_id"),
        "source_feature": record.get("source_feature"),
        "delivery_status": record.get("delivery_status"),
        "source": "bot_output_ledger",
        "self_referential": True,       # никогда не independent proof
    }
