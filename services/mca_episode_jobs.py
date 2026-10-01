"""Раунд 10.27 (MCA Wave 2, `mca-05-episodes-stories`, ADR-1027-12 D10/D6) —
resumable backfill job сборки эпизодов/историй по архиву.

Durable `task_jobs` (mca-01): unique key ``episodes.backfill:<chat_id>``
(coalescing — без дублей/параллельного старта), checkpoint продвигается
ТОЛЬКО после фиксации результата batch, heartbeat/attempt, счётчики
``processed/linked/unresolved/errors``.

Честная финализация (прецедент mca-04b D3): budget/ошибка LLM →
``paused`` (никогда ложный ``completed``); отмена → ``cancelled``;
неожиданная ошибка → ``failed``; полный корректный проход → ``completed``
(нулевой результат валиден). Чтение (keyset ``(timestamp, id)``, без
OFFSET по миллионам строк) → LLM → короткая запись — разделены (никакой
долгой транзакции, MCA14-R3). Порция ≤ ``MCA_EPISODES_BATCH_MAX_MESSAGES``
(default 500, D6); 1 активный LLM batch/чат (coalescing); direct-
приоритет: backfill уступает direct-пути (не блокирует его).

Пайплайн физически НЕ имеет пути отправки в Telegram (§2 п.2, grep-гейт
T-4259) — модуль только читает архив и пишет производные таблицы mca-05.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from services import mca_gates
from services.task_supervisor import (
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    TaskJobStore,
)

logger = logging.getLogger(__name__)

BACKFILL_JOB_KIND = "episodes.backfill"
JOB_PAUSED = "paused"            # durable-статус паузы (прецедент mca-04b D3)
BACKFILL_REASON_BUDGET = "story_backfill_paused_budget"

# Пауза между LLM-порциями при direct-приоритете (backfill уступает
# direct-пути; код-константа, Δ каталога = 0).
_DIRECT_PRIORITY_YIELD_SECONDS = 2.0


def backfill_coalesce_key(chat_id: int) -> str:
    """Unique key durable-задачи (без дублей/параллельного старта)."""
    return f"episodes.backfill:{int(chat_id)}"


def default_counters() -> dict:
    """Счётчики job (checkpoint-payload; честные — не подменяются)."""
    return {"processed": 0, "linked": 0, "unresolved": 0, "errors": 0,
            "batches": 0}


def backfill_status_from_job(row: dict | None) -> str | None:
    """Статус durable-задачи чата (для потребителя mca-12). Статус задания
    — отдельная сущность от `state` истории (инвариант §9.1)."""
    if row is None:
        return None
    return str(row.get("status") or "")


async def enqueue_episodes_backfill(db, chat_id: int, *, owner: str = "mca05",
                                    max_messages: int | None = None,
                                    ) -> str:
    """Поставить resumable backfill в durable-очередь (coalescing: при
    активной задаче с тем же ключом возвращается её `job_id`)."""
    if not mca_gates.episodes_backfill_enabled():
        raise RuntimeError("episodes backfill disabled (kill-switch OFF)")
    store = TaskJobStore(db)
    payload = json.dumps({
        "chat_id": int(chat_id),
        "cursor_ts": 0,
        "cursor_id": 0,
        "max_messages": int(max_messages
                            or mca_gates.episodes_batch_max_messages()),
        "counters": default_counters(),
    }, ensure_ascii=False)
    return await store.enqueue(
        owner=owner, kind=BACKFILL_JOB_KIND,
        coalesce_key=backfill_coalesce_key(chat_id), payload=payload,
        max_attempts=3)


async def get_active_backfill(db, chat_id: int) -> dict | None:
    """Активная (queued/running) задача backfill чата или None."""
    cursor = await db.db.execute(
        "SELECT * FROM task_jobs WHERE coalesce_key = ? AND status IN (?, ?) "
        "ORDER BY created_at DESC LIMIT 1",
        (backfill_coalesce_key(chat_id), JOB_QUEUED, JOB_RUNNING))
    row = await cursor.fetchone()
    return dict(row) if row is not None else None


class EpisodesBackfillRunner:
    """Исполнитель durable-задачи backfill (реентерабельный по `job_id`).

    `llm` — существующий клиент (интерфейс `generate`, GEN-R2); `None` →
    LLM-стадии честно unresolved (записи не выдумываются). `cancel_cb` —
    внешняя отмена (опционально).
    """

    def __init__(self, db, llm=None, *, cancel_cb=None) -> None:
        self._db = db
        self._llm = llm
        self._cancel_cb = cancel_cb
        self._store = TaskJobStore(db)
        from services.mca_episodes import EpisodeService
        self._service = EpisodeService(db, llm)

    # ── payload/checkpoint (durable курсор) ───────────────────────────────

    async def _load_payload(self, job_id: str) -> dict:
        cursor = await self._db.db.execute(
            "SELECT payload FROM task_jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        try:
            data = json.loads(row["payload"] or "{}") if row else {}
        except (ValueError, TypeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("chat_id", 0)
        data.setdefault("cursor_ts", 0)
        data.setdefault("cursor_id", 0)
        data.setdefault("max_messages",
                        mca_gates.episodes_batch_max_messages())
        counters = data.setdefault("counters", default_counters())
        for key, value in default_counters().items():
            counters.setdefault(key, value)
        return data

    async def _checkpoint(self, job_id: str, payload: dict) -> None:
        """Checkpoint ПОСЛЕ фиксации результата batch (короткая транзакция
        под single-writer; без долгой транзакции на весь диапазон)."""
        payload_json = json.dumps(payload, ensure_ascii=False)
        now = int(time.time())

        async def _body(_conn):
            await self._db.db.execute(
                "UPDATE task_jobs SET payload = ?, progress_at = ?, "
                "updated_at = ? WHERE job_id = ?",
                (payload_json, now, now, job_id))
            return 1

        await self._db.write_transaction(_body, op_name="mca05_checkpoint")

    async def _finish(self, job_id: str, *, status: str, reason_code=None,
                      payload: dict | None = None) -> None:
        if payload is not None:
            await self._checkpoint(job_id, payload)
        await self._store.finish(job_id, status=status,
                                 reason_code=reason_code)

    # ── порции архива (keyset (timestamp, id), без OFFSET) ────────────────

    async def _fetch_portion(self, chat_id: int, cursor_ts: int,
                             cursor_id: int, limit: int) -> list[dict]:
        cursor = await self._db.db.execute(
            "SELECT id, chat_id, user_id, text, reply_to_id, timestamp, "
            "tg_message_id FROM smart_messages WHERE chat_id = ? AND "
            "(timestamp > ? OR (timestamp = ? AND id > ?)) "
            "ORDER BY timestamp ASC, id ASC LIMIT ?",
            (int(chat_id), int(cursor_ts), int(cursor_ts), int(cursor_id),
             max(1, int(limit))))
        return [dict(r) for r in await cursor.fetchall()]

    # ── главный цикл ──────────────────────────────────────────────────────

    async def run(self, job_id: str) -> str:
        """Выполнить задачу до честного терминального статуса.

        Бюджет/LLM-ошибка → `paused` (никогда ложный `completed`); отмена →
        `cancelled`; рестарт продолжает с checkpoint без дублей (дедуп по
        стабильному message-ключу/segment_key)."""
        if not mca_gates.episodes_backfill_enabled():
            await self._finish(job_id, status=JOB_CANCELLED,
                               reason_code="cancelled")
            return JOB_CANCELLED
        payload = await self._load_payload(job_id)
        chat_id = int(payload["chat_id"])
        if not chat_id:      # Telegram chat_id отрицательные; 0 = битый payload
            await self._finish(job_id, status=JOB_FAILED,
                               reason_code="invalid_payload",
                               payload=payload)
            return JOB_FAILED
        started = await self._store.mark_running(job_id)
        if not started:
            row = await self._store.get(job_id)
            return backfill_status_from_job(row) or JOB_RUNNING
        budget = mca_gates.episodes_batch_max_messages()
        while True:
            if self._cancel_cb is not None:
                try:
                    if self._cancel_cb():
                        await self._finish(job_id, status=JOB_CANCELLED,
                                           reason_code="cancelled",
                                           payload=payload)
                        return JOB_CANCELLED
                except Exception:
                    pass
            await self._store.heartbeat(job_id)
            portion = await self._fetch_portion(
                chat_id, int(payload["cursor_ts"]), int(payload["cursor_id"]),
                min(int(payload["max_messages"]), budget))
            if not portion:
                # Полный корректный проход; нулевой результат валиден.
                await self._finish(job_id, status=JOB_COMPLETED,
                                   payload=payload)
                return JOB_COMPLETED
            # Прямые ответы приоритетны: backfill уступает direct-пути.
            if mca_gates.episodes_direct_priority_enabled():
                await asyncio.sleep(_DIRECT_PRIORITY_YIELD_SECONDS)
            try:
                counters = await self._service.process_batch(
                    chat_id, portion)
            except asyncio.CancelledError:
                # Отмена между порциями — честный interrupted (не
                # completed); checkpoint уже продвинут по зафиксированным
                # порциям (resume без дублей).
                await self._store.finish(job_id, status="interrupted",
                                         reason_code="cancelled")
                raise
            except Exception:
                # LLM-сбой → пауза с причиной (retryable), никогда ложный
                # `completed` (D10/прецедент mca-04b D3).
                await self._finish(job_id, status=JOB_PAUSED,
                                   reason_code="model_unavailable",
                                   payload=payload)
                return JOB_PAUSED
            agg = payload["counters"]
            for key in ("processed", "linked", "unresolved", "errors"):
                agg[key] = int(agg.get(key) or 0) + int(
                    counters.get(key) or 0)
            agg["batches"] = int(agg.get("batches") or 0) + 1
            last = portion[-1]
            payload["cursor_ts"] = int(last.get("timestamp") or 0)
            payload["cursor_id"] = int(last.get("id") or 0)
            await self._checkpoint(job_id, payload)
            if int(counters.get("errors") or 0) > 0:
                # Ошибка операции в batch (LLM-сбой) → честная пауза с
                # причиной; рестарт продолжит с checkpoint (никогда
                # ложный `completed`, D10/прецедент mca-04b D3).
                await self._finish(job_id, status=JOB_PAUSED,
                                   reason_code="model_unavailable",
                                   payload=payload)
                return JOB_PAUSED

    # ── перепроверка по revision (D10; без рекурсивного каскада) ──────────

    async def process_rechecks(self, chat_id: int, *, limit: int = 20) -> int:
        """Перепроверить эпизоды с `recheck_pending=1`: повторное извлечение
        по исходным сообщениям (содержимое эпизода обновляется на месте,
        `discovered_at` не меняется — A11) + новая версия историй
        (override не затирается). Возврат — число перепроверенных."""
        from services.mca_episodes import queue_source_recheck  # noqa: F401
        repo = self._service.repo
        processed = 0
        for episode in await repo.list_recheck_episodes(
                chat_id, limit=max(1, int(limit))):
            try:
                messages = await self._episode_source_messages(
                    chat_id, episode)
                ok = await self._service.reextract_episode(
                    chat_id, episode, messages)
                await repo.set_episode_recheck(
                    episode["episode_id"], pending=not ok)
                if ok:
                    processed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("[mca05] recheck processing failed",
                               exc_info=True)
                await repo.set_episode_recheck(
                    episode["episode_id"], pending=True)
        return processed

    async def _episode_source_messages(self, chat_id: int,
                                       episode: dict) -> list[dict]:
        """Прочитать исходные сообщения эпизода по стабильным ключам."""
        try:
            keys = json.loads(episode.get("message_keys_json") or "[]")
        except (ValueError, TypeError):
            keys = []
        messages: list[dict] = []
        for key in keys or ():
            row = await self._message_by_key(chat_id, str(key))
            if row is not None:
                messages.append(row)
        return messages

    async def _message_by_key(self, chat_id: int, key: str):
        if ":tg:" in key:
            try:
                tg = int(key.rsplit(":tg:", 1)[1])
            except (TypeError, ValueError):
                return None
            cursor = await self._db.db.execute(
                "SELECT id, chat_id, user_id, text, reply_to_id, timestamp, "
                "tg_message_id FROM smart_messages WHERE chat_id = ? AND "
                "tg_message_id = ? LIMIT 1", (int(chat_id), tg))
            row = await cursor.fetchone()
            return dict(row) if row is not None else None
        if ":db:" in key:
            try:
                mid = int(key.rsplit(":db:", 1)[1])
            except (TypeError, ValueError):
                return None
            cursor = await self._db.db.execute(
                "SELECT id, chat_id, user_id, text, reply_to_id, timestamp, "
                "tg_message_id FROM smart_messages WHERE id = ? AND "
                "chat_id = ? LIMIT 1", (mid, int(chat_id)))
            row = await cursor.fetchone()
            return dict(row) if row is not None else None
        return None
