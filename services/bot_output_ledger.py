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


async def record_factcheck_output(
        db, *, chat_id: int, tg_message_id: int | None, text: str | None,
        bot_user_id: int | None = None, parent_message_ref: str | None = None,
        correlation_id: str | None = None) -> int | None:
    """UR-23.4: доставленный фактчек-ответ — в ТОТ ЖЕ durable ledger
    (`mca_bot_outputs`), что и другие прямые ответы (MCA-22 C2).

    Раньше factcheck-доставка шла через общий `send_chunked_reply` без
    записи — ответы фактчека были невидимы для «бот помнит свои ответы»
    (UR-23) и duplicate/observability-логики. Форма записи — как у direct:
    correlation_id, chat, точный доставленный текст + content_hash digest,
    tg_message_id, parent_message_ref. Маркер ветки —
    `source_feature='factcheck'`. Таксономия закрытого набора НЕ
    расширяется: вердикт с секциями/ссылками — `rich_message` (прецедент
    summary-статей/чанков). Вызывается ТОЛЬКО после подтверждённой
    отправки (недоставленный вердикт не пишется); fail-open как базовая
    запись; verdict/content pipeline фактчека не затрагивается."""
    return await record_delivered_output(
        db, chat_id=chat_id, tg_message_id=tg_message_id, text=text,
        bot_user_id=bot_user_id, output_kind="rich_message",
        parent_message_ref=parent_message_ref, correlation_id=correlation_id,
        source_feature="factcheck")


async def record_factcheck_reply(
        db, *, chat_id: int, tg_message_id: int | None, text: str | None,
        bot_user_id: int | None = None, parent_message_ref: str | None = None,
        correlation_id: str | None = None) -> int | None:
    """FC-OBSERVABILITY-01: доставленная КОРОТКАЯ реплика фактчека —
    в тот же durable ledger (`mca_bot_outputs`), что вердикт и прямые ответы.

    Повод (прод-трасса): уточняющий ответ ветки `ambiguous` приходил в чат без
    ledger-строки — опубликованный текст нельзя было проверить после прогона
    (в TTL-кеше `bot_replies` его тоже нет), а сам прогон искали по соседним
    событиям.

    Таксономия: `output_kind='direct_reply'` — это обычный короткий текстовый
    ответ в чате, а не вердикт с секциями/ссылками (`rich_message`, как в
    `record_factcheck_output`). Новый kind НЕ вводится: закрытый
    `BOT_OUTPUT_KINDS` и зависящие от него потребители (self-model, антифлуд,
    cooldown) не расширяются. Маркер ветки — `source_feature='factcheck'`
    (реплику произвёл прогон фактчека). Вызывается ТОЛЬКО после подтверждённой
    отправки; fail-open как базовая запись."""
    return await record_delivered_output(
        db, chat_id=chat_id, tg_message_id=tg_message_id, text=text,
        bot_user_id=bot_user_id, output_kind="direct_reply",
        parent_message_ref=parent_message_ref, correlation_id=correlation_id,
        source_feature="factcheck")


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


# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED-REPLY UR-23: единый read-path истории собственных сообщений.
#
# Источник истины — `mca_bot_outputs` (durable, append-only). `bot_replies`
# остаётся TTL-кешем краткосрочного reply; его истечение НЕ означает
# забывания. Здесь нет style-anchor семантики: собственные доставленные
# реплики — обычные события разговора (UR-14).
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_history_record(record: dict) -> dict:
    """Нормализовать ledger-строку для хронологии (без догадок).

    * актуальная ревизия (append-only: правка = новая строка);
    * `sent_at=None` → `sent_at=0`, `time_known=False` (дата не выдумывается);
    * media-only строка (`content_text IS NULL`) → `text=""`, `media_only`;
    * `correlation_id` сохраняется для многочастных ответов."""
    text = record.get("content_text")
    media_only = not (text or "").strip()
    sent_at = record.get("sent_at")
    try:
        sent_int = int(sent_at or 0)
    except (TypeError, ValueError):
        sent_int = 0
    out = dict(record)
    out["sent_at"] = sent_int
    out["time_known"] = bool(sent_int)
    out["text"] = "" if media_only else str(text)
    out["media_only"] = bool(media_only) and bool(
        record.get("content_ref") or record.get("tg_message_id"))
    out["revision"] = int(record.get("revision_no") or 1)
    out["source_id"] = bot_output_source_ref_id(
        record.get("output_id")) if record.get("output_id") is not None \
        else f"bot_output_tg:{record.get('tg_message_id')}"
    out["source"] = "bot_output_ledger"
    out["self_referential"] = True
    return out


async def list_bot_output_history(db, chat_id: int, *, since_ts: int = 0,
                                  until_ts: int = 0, limit: int = 200,
                                  kinds: tuple[str, ...] | None = None,
                                  include_undated: bool = True,
                                  raise_on_error: bool = False) -> list[dict]:
    """Собственные доставленные сообщения чата в хронологическом порядке.

    Единый read-path UR-23 для ContextSelection/thread_chain:
    * scope строго по `chat_id`; только `delivery_status='delivered'`
      (недоставленный send — не слова бота);
    * актуальная ревизия на `tg_message_id` (история ревизий доступна через
      `db.get_bot_output_revisions` по явному вопросу о правке);
    * `sent_at` — UTC фактической отправки; неизвестная дата честно
      помечается (`time_known=False`), не подменяется текущим временем;
    * media-only/пустые строки не отбрасываются и не получают текст из
      воздуха (`media_only=True`);
    * gate `MCA_BOT_OUTPUT_LEDGER_ENABLED` OFF, отсутствие метода/БД или
      ошибка → пустой список (бот не притворяется, что помнит).
    * ``raise_on_error=True`` — для диагностического чтения: ошибка чтения
      поднимается, чтобы отсутствие наблюдения не выдавалось за 0 записей;
      gate/absent-reader по-прежнему возвращают пустой список (их вызывающий
      проверяет отдельно через ``ledger_enabled``).
    """
    if not ledger_enabled():
        return []
    reader = getattr(db, "list_bot_outputs_between", None)
    if reader is None:
        return []
    try:
        rows = await reader(
            int(chat_id), since_ts=int(since_ts or 0),
            until_ts=int(until_ts or 0), limit=max(1, int(limit or 1)),
            kinds=kinds)
    except Exception:
        if raise_on_error:
            raise
        logger.warning("[mca22] bot output history read failed | chat=%s",
                       chat_id, exc_info=True)
        return []
    normalised = [_normalize_history_record(row) for row in rows or ()
                  if isinstance(row, dict)]
    # Актуальная ревизия: одна строка на tg_message_id. Неизвестный tg
    # (None) — отдельная строка по output_id (не склеиваем разные ответы).
    latest: dict = {}
    order: list = []
    for item in normalised:
        if not include_undated and not item["time_known"]:
            continue
        key = item.get("tg_message_id")
        if key is None:
            order.append(item)
            continue
        current = latest.get(key)
        if current is None:
            latest[key] = item
            order.append(item)
            continue
        if int(item["revision"]) >= int(current["revision"]):
            index = order.index(current)
            order[index] = item
            latest[key] = item
    order.sort(key=lambda rec: (int(rec.get("sent_at") or 0),
                                int(rec.get("output_id") or 0)))
    return order
