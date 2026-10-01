"""MCA-22 (round 10.27, ADR-1028-6 D1/D3) — Canonical Message Envelope.

C1: единый runtime read-контракт поверх существующих таблиц (`smart_messages`
v16 + `message_source_records`), НЕ новая БД (§2 ТЗ). Frozen-DTO
`CanonicalMessage` + batch projection `get_canonical_messages` — SELECT
расширен до полного набора роль/время-колонок ОДНИМ проходом (без N+1, §30).

Инварианты:
* неизвестное = `None` (никогда не выдумывается);
* роли не схлопываются: author ≠ reply addressee ≠ quoted author ≠
  forward author (`message_identity.roles`);
* kill-switch `MCA_CANONICAL_ATTRIBUTION_ENABLED`: OFF → потребители читают
  как сегодня (существующие SELECT), projection не вызывается;
* OFF-паритет: projection не пишет в БД (read-only слой).

R17: никаких сырых переписок в логах; только ID/числа/коды.
"""
from __future__ import annotations

import dataclasses
import logging
import time

from services import mca_gates
from services import message_identity

logger = logging.getLogger(__name__)

# Revision-ref контракта (контекст-версия/lineage). Рост версии — только
# при изменении набора полей DTO.
CANONICAL_ENVELOPE_VERSION = "mca22/canonical/v1"

_FULL_COLUMNS = (
    "id, user_id, chat_id, text, reply_to_id, timestamp, media_type, "
    "author_name, is_forward, forward_source, tg_message_id, "
    "caption, sent_at, ingested_at, edited_at, sent_at_source, "
    "source_kind, namespace, source_record_id, content_hash, media_ref, "
    "reply_to_kind, reply_to_author_id, quote_text, quote_author_id, "
    "forward_author_id, message_state, state_evidence, current_revision"
)


@dataclasses.dataclass(frozen=True)
class CanonicalMessage:
    """C1 (§2 ТЗ): единый read-контракт сообщения.

    Все поля честные: отсутствие данных в БД → `None` (unknown не
    выдумывается). `speaker_*` = author сообщения (MCA-03 `user_id`);
    субъект обсуждения — НЕ здесь (это уровень ClaimEnvelope, C4)."""

    message_ref: str | None            # каноническая ссылка `tg:<id>` / `msg:<row>`
    source_ref_id: int | None          # SourceRef mca-04a (если materialized)
    row_id: int                        # локальный rowid smart_messages
    chat_id: int
    tg_message_id: int | None
    revision: int                      # MCA-03 current_revision
    source_kind: str | None
    speaker_entity_id: int | None      # author (MCA-03 user_id)
    speaker_display_name: str | None
    sent_at: int | None                # дата события (Telegram)
    ingested_at: int | None            # дата записи (write-clock)
    edited_at: int | None
    reply_to_message_ref: str | None
    reply_to_speaker_entity_id: int | None   # reply_to_author_id
    quote_text: str | None
    quote_source_ref: str | None       # ссылка на цитируемое сообщение (если известна)
    quote_speaker_entity_id: int | None      # quote_author_id
    forward_source: str | None
    forward_speaker_entity_id: int | None    # forward_author_id
    is_forward: bool
    thread_id: int | None              # topic/thread (Telegram), если есть
    media_type: str | None
    media_ref: str | None
    content_hash: str | None
    message_state: str | None
    raw_text: str | None               # текст сообщения
    caption: str | None

    def roles(self) -> dict:
        """Раздельные роли (REUSE `message_identity.roles`, MCA-03 D4)."""
        return {
            message_identity.ROLE_AUTHOR: self.speaker_entity_id,
            message_identity.ROLE_REPLY_ADDRESSEE:
                self.reply_to_speaker_entity_id,
            message_identity.ROLE_QUOTED_AUTHOR:
                self.quote_speaker_entity_id,
            message_identity.ROLE_FORWARD_AUTHOR:
                self.forward_speaker_entity_id,
        }


def canonical_attribution_enabled() -> bool:
    """Мастер-рубильник C1/C3/C4/C5 (per-call, никогда не бросает)."""
    try:
        return mca_gates.canonical_attribution_enabled()
    except Exception:                                     # pragma: no cover
        return True


def _message_ref(row) -> str:
    tg = row["tg_message_id"]
    return f"tg:{tg}" if tg is not None else f"msg:{row['id']}"


def message_from_row(row, *, quote_source_ref: str | None = None
                     ) -> CanonicalMessage:
    """Строка SELECT (полный набор колонок) → `CanonicalMessage`.

    Один проход, без второго запроса (§30). `quote_source_ref` передаётся
    вызывающим, если reply-target уже известен (batch-карта), иначе None."""
    return CanonicalMessage(
        message_ref=_message_ref(row),
        source_ref_id=None,
        row_id=int(row["id"]),
        chat_id=int(row["chat_id"]),
        tg_message_id=row["tg_message_id"],
        revision=int(row["current_revision"] or 1),
        source_kind=row["source_kind"],
        speaker_entity_id=row["user_id"],
        speaker_display_name=(row["author_name"] or None)
        if row["author_name"] else None,
        sent_at=row["sent_at"],
        ingested_at=row["ingested_at"],
        edited_at=row["edited_at"],
        reply_to_message_ref=(f"tg:{row['reply_to_id']}"
                              if row["reply_to_id"] is not None else None),
        reply_to_speaker_entity_id=row["reply_to_author_id"],
        quote_text=row["quote_text"],
        quote_source_ref=quote_source_ref,
        quote_speaker_entity_id=row["quote_author_id"],
        forward_source=(row["forward_source"] or None)
        if row["forward_source"] else None,
        forward_speaker_entity_id=row["forward_author_id"],
        is_forward=bool(row["is_forward"]),
        thread_id=None,                    # Telegram topic — честный unknown
        media_type=row["media_type"],
        media_ref=row["media_ref"],
        content_hash=row["content_hash"],
        message_state=row["message_state"],
        raw_text=row["text"],
        caption=row["caption"],
    )


async def get_canonical_messages(db, chat_id: int, *,
                                 since_ts: int | None = None,
                                 older_than_ts: int | None = None,
                                 limit: int = 100) -> list[CanonicalMessage]:
    """Batch projection: окно сообщений чата → list[CanonicalMessage].

    ОДИН SELECT с полным набором колонок (без N+1, §30). Условия окна —
    как у существующих `get_smart_window` (`since_ts`) / `get_smart_raw`
    (`older_than_ts`); порядок хронологический ASC. Gate OFF → пустой
    список (потребитель обязан уйти в legacy-путь — паритет baseline).
    Fail-open: ошибка БД → [] (контекст не рвётся)."""
    if not canonical_attribution_enabled():
        return []
    try:
        sql = (f"SELECT {_FULL_COLUMNS} FROM smart_messages "
               f"WHERE chat_id = ?")
        params: list = [int(chat_id)]
        if since_ts is not None:
            sql += " AND timestamp >= ?"
            params.append(int(since_ts))
        if older_than_ts is not None:
            sql += " AND timestamp < ?"
            params.append(int(older_than_ts))
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(max(1, int(limit)))
        cursor = await db.db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        rows = list(rows)
        rows.reverse()
        # Batch-карта reply-target'ов: quote_source_ref из одного доп. прохода
        # по уже выбранному окну (вне окна — честный None, без N+1).
        by_tg = {r["tg_message_id"]: r for r in rows
                 if r["tg_message_id"] is not None}
        out: list[CanonicalMessage] = []
        for row in rows:
            qsrc = None
            if row["reply_to_id"] is not None:
                target = by_tg.get(row["reply_to_id"])
                if target is not None:
                    qsrc = _message_ref(target)
            out.append(message_from_row(row, quote_source_ref=qsrc))
        return out
    except Exception:
        logger.warning("[mca22] canonical projection failed | chat=%s",
                       chat_id, exc_info=True)
        return []


async def get_canonical_messages_by_refs(db, chat_id: int, refs: list[int]
                                         ) -> dict[int, CanonicalMessage]:
    """Batch projection по списку `tg_message_id` → карта.

    ОДИН SELECT `IN (...)`. Отсутствующие refs честно отсутствуют в карте.
    Gate OFF → {}."""
    if not canonical_attribution_enabled() or not refs:
        return {}
    try:
        marks = ",".join("?" for _ in refs)
        sql = (f"SELECT {_FULL_COLUMNS} FROM smart_messages "
               f"WHERE chat_id = ? AND tg_message_id IN ({marks})")
        cursor = await db.db.execute(sql, (int(chat_id),
                                           *(int(r) for r in refs)))
        rows = await cursor.fetchall()
        return {int(r["tg_message_id"]): message_from_row(r)
                for r in rows}
    except Exception:
        logger.warning("[mca22] canonical projection (refs) failed | chat=%s",
                       chat_id, exc_info=True)
        return {}


def window_row_to_canonical(row, *, reply_map: dict | None = None
                            ) -> CanonicalMessage | None:
    """Конвертер «узкой» строки 11 колонок невозможен по контракту — роль-
    колонки не выбирались. Адаптер для `get_smart_message_by_tg_id` (полный
    ряд v16): роли/время/revision доезжают без второго запроса."""
    try:
        return message_from_row(row)
    except Exception:
        return None


def envelope_version() -> str:
    """Версия контракта (наблюдаемость/lineage)."""
    return CANONICAL_ENVELOPE_VERSION


def format_canonical_envelope(msg: CanonicalMessage, *,
                              show_quote_text: bool = True) -> str:
    """C1 rendering (§3 ТЗ, T-4283): `store rich → retrieve rich → render
    only relevant metadata`; но reply-адресат / автор цитаты / автор
    пересылки обязательны в model-facing context — без них меняется смысл.

    Роли РАЗЛИЧИМЫ (анти-инварианты §3):
    * reply ≠ quote ≠ forward — раздельные слоты, не склеиваются;
    * цитата — НЕ слова цитирующего: текст цитаты маркирован `>` и подписан
      автором цитаты, автор сообщения отдельный;
    * автор пересылки ≠ отправитель текущего сообщения.
    Неизвестная роль — слот опускается (честный unknown, не выдумка)."""
    head: list[str] = []
    if msg.sent_at:
        head.append(time.strftime("%Y-%m-%d %H:%M", time.gmtime(msg.sent_at)))
    if msg.speaker_display_name:
        head.append(str(msg.speaker_display_name))
    if msg.tg_message_id is not None:
        head.append(f"tg:{msg.tg_message_id}")
    if msg.forward_source or msg.forward_speaker_entity_id is not None:
        fwd_author = (str(msg.forward_speaker_entity_id)
                      if msg.forward_speaker_entity_id is not None else "?")
        head.append(f"Переслано: {msg.forward_source or fwd_author}"
                    f" (автор: {fwd_author})")
    if msg.reply_to_speaker_entity_id is not None:
        head.append(f"в ответ: {msg.reply_to_speaker_entity_id}")
    body_parts: list[str] = []
    if show_quote_text and msg.quote_text:
        q_author = (str(msg.quote_speaker_entity_id)
                    if msg.quote_speaker_entity_id is not None else "автор unknown")
        body_parts.append(f"> {msg.quote_text} (автор цитаты: {q_author})")
    text = msg.raw_text or msg.caption or ""
    if text:
        body_parts.append(text)
    body = "\n".join(body_parts)
    if not head:
        return body
    return f"[{' | '.join(head)}]: {body}"
