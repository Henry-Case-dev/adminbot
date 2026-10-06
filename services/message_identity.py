"""Раунд 10.27 (MCA Wave 1, `mca-03-message-identity`) — контракт логической
идентичности сообщения, ролей, времени и версий (ADR-1027-4 D1–D12).

Единый контракт (без второго ingestion/store):
  * **Логическая идентичность** — пара `(chat_id, tg_message_id)` (D1);
    `smart_messages.id` — стабильный внутренний ID, НИКОГДА не Telegram ID.
  * **Вхождения** — `message_source_records` (namespace + stable
    source_record_id); canonical source = строка `smart_messages` (D2).
  * **Время** — `sent_at` (дата события) ≠ `ingested_at` (дата записи);
    происхождение `sent_at` фиксирует `sent_at_source`; `timestamp` не
    переименовывается (D3).
  * **Роли** — author / reply addressee / quoted author / forward author
    разделены; алиасы (`ALIAS > real_name > username`) — display-only, имя НЕ
    сливает идентичности (D4).
  * **Версии** — редакция → append `message_revisions` + инкремент
    `current_revision` + FTS + событие `source_revision_changed`;
    `unavailable/deleted` — только по свидетельству (D5).
  * **Mapping `chat_id`** — только по подтверждённым метаданным (D6).

Kill-switch (env-only `ClassVar`, default ON, резолв per-call, OFF = паритет
baseline 7165ff7): `MCA_MESSAGE_IDENTITY_ENABLED`,
`MCA_MESSAGE_REVISION_TRACKING_ENABLED`.

R17: в логи/события — только id/коды/`error_type`; секреты/сырой контекст не
логируются (`emit_mca_event` проходит `sanitize()`).
"""
from __future__ import annotations

import hashlib
import logging
import time

from services import mca_gates
from services.mca_events import emit_mca_event

logger = logging.getLogger(__name__)

# ── source_kind (D2/D3): откуда пришла каноническая запись ──────────────────
SOURCE_KIND_LIVE = "live"
SOURCE_KIND_IMPORT = "import"
SOURCE_KIND_UNKNOWN = "unknown"
SOURCE_KINDS = frozenset({SOURCE_KIND_LIVE, SOURCE_KIND_IMPORT,
                          SOURCE_KIND_UNKNOWN})

# ── sent_at_source (D3): происхождение даты события (честный unknown) ───────
SENT_AT_SOURCE_TELEGRAM_DATE = "telegram_date"
SENT_AT_SOURCE_IMPORT_DATE = "import_date"
SENT_AT_SOURCE_LEGACY_UNVERIFIED = "legacy_unverified"
SENT_AT_SOURCE_UNKNOWN = "unknown"
SENT_AT_SOURCES = frozenset({
    SENT_AT_SOURCE_TELEGRAM_DATE, SENT_AT_SOURCE_IMPORT_DATE,
    SENT_AT_SOURCE_LEGACY_UNVERIFIED, SENT_AT_SOURCE_UNKNOWN,
})

# ── reply_to_kind (D3): TG-id vs экспортный id (смешение запрещено) ─────────
REPLY_KIND_TG = "tg"
REPLY_KIND_EXPORT = "export"
REPLY_KIND_UNKNOWN = "unknown"

# ── message_state (D5): NULL = unknown ─────────────────────────────────────
MESSAGE_STATE_ACTIVE = "active"
MESSAGE_STATE_UNAVAILABLE = "unavailable"
MESSAGE_STATE_DELETED = "deleted"
MESSAGE_STATES = frozenset({
    MESSAGE_STATE_ACTIVE, MESSAGE_STATE_UNAVAILABLE, MESSAGE_STATE_DELETED,
})

# ── revision_kind (D5) ──────────────────────────────────────────────────────
REVISION_KIND_INITIAL = "initial"
REVISION_KIND_EDIT = "edit"
REVISION_KIND_UNAVAILABLE = "unavailable"
REVISION_KIND_DELETED = "deleted"

# Namespace'ы: live-контур и legacy-импорт (backfill v16).
LIVE_NAMESPACE = "live"
LEGACY_IMPORT_NAMESPACE = "legacy_import_v1"

# reason_code WARN-расширения MCA-13 (реестр в `services/mca_events.py`).
DUPLICATE_IDENTITY_ROWS = "duplicate_identity_rows"

# Роли (D4) — раздельные смысловые слоты, не схлопываются.
ROLE_AUTHOR = "author"
ROLE_REPLY_ADDRESSEE = "reply_addressee"
ROLE_QUOTED_AUTHOR = "quoted_author"
ROLE_FORWARD_AUTHOR = "forward_author"


def identity_enabled() -> bool:
    """`MCA_MESSAGE_IDENTITY_ENABLED` (default ON, per-call, не бросает).

    ON → producers пишут каноническую идентичность/source records;
    OFF → точный legacy-путь (`save_smart_message`)."""
    return mca_gates.message_identity_enabled()


def revision_tracking_enabled() -> bool:
    """`MCA_MESSAGE_REVISION_TRACKING_ENABLED` (default ON, per-call).

    ON → правки человека создают версии; OFF → прежнее поведение (без
    версионирования)."""
    return mca_gates.message_revision_tracking_enabled()


def canonical_key(chat_id, tg_message_id) -> tuple[int, int] | None:
    """Канонический ключ сообщения: `(chat_id, tg_message_id)` (D1).

    `None`, если Telegram ID отсутствует — локальный ID за Telegram не
    выдаётся."""
    if tg_message_id is None:
        return None
    return (int(chat_id), int(tg_message_id))


def live_source_record_id(chat_id, tg_message_id) -> str | None:
    """Стабильный локальный record ID live-вхождения (не Telegram ID)."""
    if tg_message_id is None:
        return None
    return f"{int(chat_id)}:{int(tg_message_id)}"


def message_content_hash(text, caption=None) -> str | None:
    """Content-hash сообщения (sha256 hex).

    `None`, если ни текста, ни подписи нет (честный unknown, не выдуманный
    хэш). Разделитель `\\x00` исключает склейку text+caption."""
    if not text and not caption:
        return None
    material = f"{text or ''}\x00{caption or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def roles(rec) -> dict:
    """Разделение ролей (D4) из плоской записи: author ≠ reply addressee ≠
    quoted author ≠ forward author. Субъект обсуждения — вне MCA-03."""
    return {
        ROLE_AUTHOR: rec.get("user_id"),
        ROLE_REPLY_ADDRESSEE: rec.get("reply_to_author_id"),
        ROLE_QUOTED_AUTHOR: rec.get("quote_author_id"),
        ROLE_FORWARD_AUTHOR: rec.get("forward_author_id"),
    }


def _as_str(value):
    """Только `str` (после strip) либо `None` — защита от не-str/mock-объектов
    (честный unknown вместо мусора в БД)."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _as_int(value):
    """Только `int` (не bool) либо `None`."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


async def save_live_message(db, *, chat_id: int, user_id=None, text=None,
                            caption=None, timestamp=None, sent_at=None,
                            ingested_at=None, media_type="text",
                            author_name="", is_forward=False,
                            forward_source="", tg_message_id=None,
                            media_ref=None, reply_to_id=None,
                            reply_to_author_id=None, quote_text=None,
                            quote_author_id=None, forward_author_id=None,
                            sender_chat_id=None, origin_type=None,
                            origin_sent_at=None, origin_sender_user_id=None,
                            origin_chat_id=None, origin_message_id=None,
                            origin_display_name=None,
                            origin_author_signature=None, thread_id=None,
                            media_group_id=None) -> int:
    """Живой ingestion → канонический get-or-create (ON) либо legacy (OFF).

    OFF (`MCA_MESSAGE_IDENTITY_ENABLED=false`) → ровно `save_smart_message`
    (паритет baseline: те же аргументы, new-columns остаются NULL).
    MCA-19 (ADR-1028-19 D2): Origin-блок — опциональные kwargs; None =
    честный unknown (никаких выдуманных значений)."""
    now = int(timestamp if timestamp is not None else time.time())
    text = _as_str(text)
    caption = _as_str(caption)
    user_id = _as_int(user_id)
    tg_message_id = _as_int(tg_message_id)
    reply_to_id = _as_int(reply_to_id)
    reply_to_author_id = _as_int(reply_to_author_id)
    quote_text = _as_str(quote_text)
    quote_author_id = _as_int(quote_author_id)
    forward_author_id = _as_int(forward_author_id)
    media_ref = _as_str(media_ref)
    sender_chat_id = _as_int(sender_chat_id)
    origin_type = _as_str(origin_type)
    origin_sent_at = _as_int(origin_sent_at)
    origin_sender_user_id = _as_int(origin_sender_user_id)
    origin_chat_id = _as_int(origin_chat_id)
    origin_message_id = _as_int(origin_message_id)
    origin_display_name = _as_str(origin_display_name)
    origin_author_signature = _as_str(origin_author_signature)
    thread_id = _as_int(thread_id)
    media_group_id = _as_str(media_group_id)
    if not identity_enabled():
        return await db.save_smart_message(
            user_id=user_id, chat_id=int(chat_id), text=text,
            reply_to_id=reply_to_id, timestamp=now, media_type=media_type,
            author_name=author_name, is_forward=bool(is_forward),
            forward_source=forward_source or "", message_id=tg_message_id,
            sender_chat_id=sender_chat_id, origin_type=origin_type,
            origin_sent_at=origin_sent_at,
            origin_sender_user_id=origin_sender_user_id,
            origin_chat_id=origin_chat_id,
            origin_message_id=origin_message_id,
            origin_display_name=origin_display_name,
            origin_author_signature=origin_author_signature,
            thread_id=thread_id, media_group_id=media_group_id)
    if sent_at is None:
        sent_at_source = SENT_AT_SOURCE_UNKNOWN
    else:
        sent_at_source = SENT_AT_SOURCE_TELEGRAM_DATE
    rec = {
        "user_id": user_id,
        "chat_id": int(chat_id),
        "text": text,
        "caption": caption,
        "timestamp": now,
        "sent_at": sent_at,
        "ingested_at": int(ingested_at if ingested_at is not None else now),
        "sent_at_source": sent_at_source,
        "source_kind": SOURCE_KIND_LIVE,
        "namespace": LIVE_NAMESPACE,
        "source_record_id": live_source_record_id(chat_id, tg_message_id),
        "content_hash": message_content_hash(text, caption),
        "media_type": media_type,
        "media_ref": media_ref,
        "author_name": author_name,
        "is_forward": bool(is_forward),
        "forward_source": forward_source or "",
        "forward_author_id": forward_author_id,
        "reply_to_id": reply_to_id,
        "reply_to_kind": (REPLY_KIND_TG if reply_to_id is not None else None),
        "reply_to_author_id": reply_to_author_id,
        "quote_text": quote_text,
        "quote_author_id": quote_author_id,
        "tg_message_id": tg_message_id,
        "message_state": MESSAGE_STATE_ACTIVE,
        "current_revision": 1,
        # MCA-19 (ADR-1028-19 D2): Origin-блок — кто ИСТОЧНИК пересылки,
        # отдельно от отправителя (D3: sender ≠ original author ≠
        # on-image author).
        "sender_chat_id": sender_chat_id,
        "origin_type": origin_type,
        "origin_sent_at": origin_sent_at,
        "origin_sender_user_id": origin_sender_user_id,
        "origin_chat_id": origin_chat_id,
        "origin_message_id": origin_message_id,
        "origin_display_name": origin_display_name,
        "origin_author_signature": origin_author_signature,
        "thread_id": thread_id,
        "media_group_id": media_group_id,
    }
    return await db.save_smart_message_identity(rec)


async def record_edit(db, *, chat_id: int, tg_message_id, text=None,
                      caption=None, edited_at=None) -> int:
    """Правка сообщения человеком → новая версия (D5).

    OFF (`MCA_MESSAGE_REVISION_TRACKING_ENABLED=false`) → no-op (текущее
    поведение, версий нет). Возвращает id канонической строки (0 — не найдена
    либо выключено). Идемпотентно: повтор с тем же содержимым версию не плодит.
    """
    if tg_message_id is None or not revision_tracking_enabled():
        return 0
    row = await db.get_smart_message_by_tg_id(int(chat_id), int(tg_message_id))
    if row is None:
        emit_mca_event("message_revision", outcome="skipped", level="WARN",
                       reason_code="source_missing", stage="edit",
                       chat_id=int(chat_id))
        return 0
    message_id = int(row["id"])
    keys = row.keys() if hasattr(row, "keys") else []
    old_text = row["text"]
    old_caption = row["caption"] if "caption" in keys else None
    if text == old_text and caption == old_caption:
        return message_id
    content_hash = message_content_hash(text, caption)
    await db.apply_message_revision(
        message_id=message_id, chat_id=int(chat_id),
        tg_message_id=int(tg_message_id), revision_kind=REVISION_KIND_EDIT,
        text=text, caption=caption, content_hash=content_hash,
        edited_at=int(edited_at if edited_at is not None else time.time()))
    emit_mca_event("message_revision", outcome="success", stage="edit",
                   reason_code="source_revision_changed",
                   chat_id=int(chat_id), message_id=message_id)
    # mca-05 (ADR-1027-12 D10): изменение источника ставит зависимые
    # эпизоды/истории на перепроверку (очередь, без рекурсивного каскада).
    # Аддитивно, fail-open, за мастер-гейтом mca-05; OFF mca-03 → недостижимо.
    try:
        from services import mca_gates as _gates
        if _gates.episodes_enabled():
            from services.mca_episodes import (
                message_key as _ep_key, queue_source_recheck,
            )
            row = {"chat_id": int(chat_id), "tg_message_id": int(tg_message_id),
                   "id": message_id}
            await queue_source_recheck(db, int(chat_id),
                                       [_ep_key(row)])
    except Exception:
        logger.warning("[identity] episodes recheck queue failed",
                       exc_info=True)
    return message_id


async def set_message_state(db, *, message_id: int, state: str, evidence,
                            chat_id=None, tg_message_id=None,
                            editor_user_id=None) -> bool:
    """Смена состояния сообщения ТОЛЬКО по свидетельству (D5).

    Допустимы `unavailable`/`deleted`; без непустого `evidence` — отказ
    (`False`). Отсутствие API-события статус не меняет и не считается
    доказательством сохранности."""
    if state not in (MESSAGE_STATE_UNAVAILABLE, MESSAGE_STATE_DELETED):
        return False
    if not evidence:
        return False
    await db.apply_message_state(
        message_id=int(message_id), state=state, evidence=str(evidence),
        revision_kind=state, chat_id=chat_id, tg_message_id=tg_message_id,
        editor_user_id=editor_user_id)
    return True


async def register_chat_id_migration(db, *, old_chat_id: int,
                                     new_chat_id: int, evidence: str,
                                     observed_at=None) -> bool:
    """Явный mapping смены `chat_id` по подтверждённым метаданным (D6).

    `evidence` обязателен (напр. `migrate_to_chat_id` сервисного сообщения);
    объединение по похожему названию запрещено."""
    if not evidence or int(old_chat_id) == int(new_chat_id):
        return False
    await db.upsert_chat_id_migration(
        old_chat_id=int(old_chat_id), new_chat_id=int(new_chat_id),
        evidence=str(evidence),
        observed_at=int(observed_at if observed_at is not None else time.time()))
    return True


async def resolve_chat_id(db, chat_id: int) -> int:
    """Канонический `chat_id` по цепочке подтверждённых миграций (D6)."""
    try:
        return await db.resolve_canonical_chat_id(int(chat_id))
    except Exception:
        logger.debug("message_identity: chat_id resolve failed — as-is",
                     exc_info=True)
        return int(chat_id)


def emit_duplicate_identity_warning(count: int) -> None:
    """WARN `duplicate_identity_rows` при legacy-дублях (D7, MCA-13).

    Частичный UNIQUE не создаётся; дубли НЕ удаляются (старые записи
    сохраняются)."""
    logger.warning(
        "[message_identity] duplicate identity rows detected | count=%d | "
        "partial unique index skipped (legacy rows preserved)", int(count))
    emit_mca_event("message_identity_migration", outcome="silent", level="WARN",
                   reason_code=DUPLICATE_IDENTITY_ROWS, stage="migrate_v16",
                   component="message_identity")
