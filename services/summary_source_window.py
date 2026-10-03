"""ASAP 4.1 волна 2 (эпик `asap-4-1-durable-whole-window-summary`) —
SummarySourceWindow: один канонический immutable first-class source
объект на run (T-4603, spec §1 A.1; ADR-1028-8 D1).

Решение (носитель): per-run durable row в SQLite-таблице
``summary_source_windows`` (DDL v24, additive; PostgreSQL — no-op).
Один write в стадии SOURCE_READY, после — immutable (никаких UPDATE
после создания; повторная запись → fail-open log без overwrite).

Совместимость заново:
  * окно = ВСЕ сообщения окна как immutable source (никаких
    messages[:N]/last N/50k/fixed caps — §1 ТЗ; pre-filter S1/S2 удалён
    ASAP-2.1 и не возвращает);
  * схема messages[] — §2 ТЗ (22439–22449): message_id/author_id/
    display_name/timestamp/text/reply_to_message_id/forward-метаданные/
    media-derived text (media_type) — ТОЛЬКО фактически доступные поля
    строк окна (`memory.get_window_messages`), без вымысла;
  * restart-safe: row переживает рестарт — run может докатиться
    (load_source_window по run_id);
  * новые «источники истины» из L1 JSON/FactPackage/XML после создания
    не строятся (все производные стадии ссылаются по run_id/source_ref).

Kill-switch ``SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED`` (env-only, default
ON; OFF → snapshot не пишется, in-memory rows — бит-в-бит 2.58.46).
Immutability: dataclass frozen; ``messages_as_view()`` отдаёт deep-copy
(мутирование потребителя байт-идентичности snapshot не меняет).

R17: messages_json живёт только в БД; наружу — counts/timestamps/safe id.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import logging
import time
from typing import Iterable

from config.settings import settings

logger = logging.getLogger(__name__)

SCHEMA_NAME = "summary_source_windows"
SOURCE_REF_PREFIX = "summary_source_window"


def durable_enabled() -> bool:
    """Kill-switch ``SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED`` (env-only,
    default ON; резолв per-call; никогда не бросает — прецедент
    `summary_l1_capacity.capacity_guard_enabled`)."""
    try:
        return bool(getattr(settings,
                            "SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def retention_days() -> int:
    """``SUMMARY_SOURCE_WINDOW_RETENTION_DAYS`` (env-only, default 7;
    мусор → дефолт; min 1)."""
    try:
        value = int(getattr(settings,
                            "SUMMARY_SOURCE_WINDOW_RETENTION_DAYS", 7))
    except (TypeError, ValueError):      # pragma: no cover - защитная ветка
        return 7
    return max(1, value)


def _row_get(row, name):
    if row is None:
        return None
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, None)


def _row_int(row, name):
    value = _row_get(row, name)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _message_of_row(row) -> dict | None:
    """§2-элемент messages[]: только фактически доступные поля строки
    окна (тот же материал, что сегодня идёт в build_l1_payload/Legacy;
    никакой новой предфильтрации — ASAP-2.1 R4-D-038 остаётся)."""
    text = _row_get(row, "text")
    msg = {
        "message_id": _row_get(row, "tg_message_id"),
        "author_id": _row_get(row, "user_id"),
        "display_name": _row_get(row, "author_name"),
        "timestamp": _row_int(row, "timestamp"),
        "text": "" if text is None else str(text),
        "reply_to_message_id": _row_get(row, "reply_to_id"),
        "media_type": _row_get(row, "media_type"),
        # DB id — стабильный (stable) материальный id окна (он же ключ
        # coverage/Ledger-упорядочения и точного возврата к строке окна;
        # пространства ID не смешиваются: TG id идёт отдельным полем).
        "db_id": _row_int(row, "id"),
    }
    is_forward = _row_get(row, "is_forward")
    if is_forward:
        msg["is_forward"] = True
        source = _row_get(row, "forward_source")
        if source:
            msg["forward_source"] = str(source)
    if msg.get("message_id") is None and msg.get("db_id") is None:
        return None
    return msg


@dataclasses.dataclass(frozen=True)
class SummarySourceWindow:
    """Immutable canonical SourceWindow (§1–§2 ТЗ; ADR-1028-8 D1)."""

    run_id: str
    chat_id: int
    window_from: int | None
    window_to: int | None
    messages: tuple                  # tuple of frozen-safe dicts (copy-on-view)
    messages_json: str               # canonical serialized window (immutable)
    created_at: int

    @property
    def source_message_count(self) -> int:
        return len(self.messages)

    @property
    def source_ref(self) -> str:
        """Ссылка производных стадий (run_id/source_ref; §2 ТЗ)."""
        return f"{SOURCE_REF_PREFIX}:{self.run_id}"

    def messages_as_view(self) -> list:
        """Отдаёт deep-copy список сообщений (мутирование потребителя
        не трогает snapshot — байт-идентичный readback гарантирован)."""
        return copy.deepcopy([dict(m) for m in self.messages])

    def counts(self) -> dict:
        """R17-safe числа для событий/логов (без текстов)."""
        return {
            "messages": self.source_message_count,
            "window_from": self.window_from,
            "window_to": self.window_to,
        }


def _canonical_json(messages: list) -> str:
    """Канонический serialized (§2): компактный JSON ASC-порядка.
    Детерминирован: ключи фиксированы порядком словаря ``_message_of_row``."""
    return json.dumps(messages, ensure_ascii=False, separators=(",", ":"))


def build_source_window(run_id, chat_id: int, rows: Iterable,
                        *, created_at: int | None = None
                        ) -> SummarySourceWindow | None:
    """Единственная точка монтирования snapshot'а (write-once, §A.1).

    ``rows`` — строки окна как сегодня (`memory.get_window_messages`); никакой
    предфильтрации/срезов. ``None`` → пустое окно/нет rows (снапшот не
    создаётся, run себя ведёт как 2.58.46). Никогда не бросает."""
    try:
        run_id = str(run_id or "").strip()
        if not run_id:
            return None
        messages: list = []
        for row in (rows or ()):
            message = _message_of_row(row)
            if message is not None:
                messages.append(message)
        if not messages:
            return None
        timestamps = [int(m.get("timestamp") or 0) for m in messages]
        window_from = min(timestamps) if timestamps else None
        window_to = max(timestamps) if timestamps else None
        return SummarySourceWindow(
            run_id=run_id,
            chat_id=int(chat_id) if chat_id is not None else 0,
            window_from=window_from,
            window_to=window_to,
            messages=tuple(messages),
            messages_json=_canonical_json(messages),
            created_at=int(created_at if created_at is not None
                           else time.time()))
    except Exception:      # pragma: no cover - защитная ветка (материал run'а)
        logger.warning("summary_source_window: build failed | chat_id=%s",
                       chat_id, exc_info=True)
        return None


def source_window_from_row(row) -> SummarySourceWindow | None:
    """Durable row → immutable объект (read-back; byte-identical ===
    сравнение ``messages_json``)."""
    if row is None:
        return None
    try:
        raw = str(row["messages_json"])
        messages = json.loads(raw)
        if not isinstance(messages, list):
            return None
        window_from = row["window_from"]
        window_to = row["window_to"]
        return SummarySourceWindow(
            run_id=str(row["run_id"]),
            chat_id=int(row["chat_id"]),
            window_from=None if window_from is None else int(window_from),
            window_to=None if window_to is None else int(window_to),
            messages=tuple(dict(m) for m in messages if isinstance(m, dict)),
            messages_json=raw,
            created_at=int(row["created_at"]))
    except Exception:      # pragma: no cover - защитная ветка
        logger.warning("summary_source_window: read-back failed",
                       exc_info=True)
        return None


# ── Persistence wrappers (SQL живёт в database.py; здесь уровня контура) ───

async def store_source_window(db, window: SummarySourceWindow) -> bool:
    """Write-once запись row (single write в SOURCE_READY).

    ``True`` → записана; ``False`` → повторная запись того же run_id
    (IntegrityError) — fail-open log, НИКОГДА не overwrite, НИКОГДА не
    бросает (блокирует мутации 2-го прохода — guard-инвариант spec §A.1)."""
    if window is None:
        return False
    try:
        return await db.save_summary_source_window(
            run_id=window.run_id, chat_id=window.chat_id,
            window_from=window.window_from, window_to=window.window_to,
            source_message_count=window.source_message_count,
            messages_json=window.messages_json,
            created_at=window.created_at)
    except Exception:      # pragma: no cover - fail-open (run не рвём)
        logger.warning("summary_source_window: store failed | run_id=%s",
                       getattr(window, "run_id", "-"), exc_info=True)
        return False


async def load_source_window(db, run_id) -> SummarySourceWindow | None:
    """Перечитать durable snapshot по run_id (restart-safe докат)."""
    try:
        row = await db.get_summary_source_window(str(run_id or ""))
        return source_window_from_row(row)
    except Exception:      # pragma: no cover - fail-open
        logger.warning("summary_source_window: load failed | run_id=%s",
                       run_id, exc_info=True)
        return None


async def purge_expired_source_windows(db, *, now: int | None = None) -> int:
    """TTL-очистка (единственный легитимный источник удаления окон).

    Удаляет только snapshot'ы старше ``SUMMARY_SOURCE_WINDOW_RETENTION_DAYS``
    (env-only, default 7). Уruns'ы читаемые позже (resume) моложе горизонта
    никогда не задеваются. Fail-open → 0."""
    try:
        horizon = retention_days() * 86400
        cutoff = int(now if now is not None else time.time()) - horizon
        return await db.purge_summary_source_windows(before_ts=cutoff)
    except Exception:      # pragma: no cover - fail-open
        logger.warning("summary_source_window: purge failed", exc_info=True)
        return 0


__all__ = [
    "SCHEMA_NAME", "SOURCE_REF_PREFIX", "SummarySourceWindow",
    "build_source_window", "source_window_from_row", "durable_enabled",
    "retention_days", "store_source_window", "load_source_window",
    "purge_expired_source_windows",
]
