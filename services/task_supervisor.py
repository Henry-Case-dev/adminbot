"""Раунд 10.27 (MCA Wave 0, `mca-01-tx-task-supervisor`) — TaskSupervisor.

In-process реестр фоновых задач + coalescing/singleflight + bounded-очередь
(ADR-1027-3 D5/D6, spec §4.5) **и** durable-персистенция в `task_jobs` (v14,
T-3740, ADR-1027-3 D5/D8/D10; рамка §1.1.1): восстановление после рестарта,
`heartbeat_at`/`attempt`/`status`/`reason_code`/`result_ref`/`generation`/
`fencing_token`. Запись/чтение — через общий write-механизм `mca-01`
(`DatabaseService.write_transaction`) и короткие SELECT'ы.

Контракт:
  * **Реестр:** каждая фоновая задача зарегистрирована с
    `task_id/owner/kind/deadline/result_ref/exception_handler`; handler
    гарантирует **видимый терминальный исход** (не `except: pass`).
  * **Coalescing/singleflight:** повторяющееся задание по одному
    `coalesce_key` (чат/версия) не запускается дважды — второй запрос
    получает тот же future/результат.
  * **Bounded-очередь:** при заполнении важное задание (durable-класс) не
    теряется молча, второстепенное объединяется/отклоняется **с причиной**
    (`queue_coalesced`/`queue_full`).

Kill-switch `MCA_TASK_SUPERVISOR_ENABLED` (default ON): OFF → задачи
выполняются как раньше, без реестра/коалесинга/ограничения (точный
pass-through, паритет baseline). Резолв per-call, никогда не бросает.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from services.mca_gates import task_supervisor_enabled

logger = logging.getLogger(__name__)

# Класс задания: важное (durable — не терять молча) / второстепенное.
KIND_IMPORTANT = "important"
KIND_SECONDARY = "secondary"

# Причины отказа (словарь MCA-13).
REASON_QUEUE_COALESCED = "queue_coalesced"
REASON_QUEUE_FULL = "queue_full"

# Терминальные исходы.
OUTCOME_COMPLETED = "completed"
OUTCOME_FAILED = "failed"
OUTCOME_REJECTED = "rejected"
OUTCOME_CANCELLED = "cancelled"


@dataclass
class TaskRecord:
    """Запись реестра: владелец/тип/срок/результат/handler (spec §4.5 D5)."""

    task_id: str
    owner: str
    kind: str
    deadline_at: float | None = None
    result_ref: str | None = None
    exception_handler: Callable[[BaseException], Awaitable[None]] | None = None
    status: str = "running"
    coalesce_key: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error_code: str | None = None
    job_id: str | None = None       # T-3740: durable job_id (v14)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "owner": self.owner,
            "kind": self.kind,
            "status": self.status,
            "coalesce_key": self.coalesce_key,
            "deadline_at": self.deadline_at,
            "result_ref": self.result_ref,
            "error_code": self.error_code,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class QueueFullError(RuntimeError):
    """Bounded-очередь заполнена; второстепенное задание отклонено с причиной."""

    reason_code = REASON_QUEUE_FULL


async def _safe_finish(job_store, job_id: str, status: str,
                       reason_code: str | None, *,
                       result_ref: str | None = None,
                       error_code: str | None = None,
                       fencing_token: int | None = None) -> None:
    """Durable-финализация задачи (fail-safe: ошибка БД не рвёт поток).

    B-MCA01-3: при заданном `fencing_token` финализация обусловлена им —
    устаревший владелец после takeover получает no-op (A51)."""
    if job_store is None or not job_id:
        return
    try:
        await job_store.finish(job_id, status=status, reason_code=reason_code,
                               result_ref=result_ref, error_code=error_code,
                               fencing_token=fencing_token)
    except Exception:
        logger.warning("task_supervisor: durable finish failed | job_id=%s",
                       job_id, exc_info=True)


def _emit_start(owner: str, kind: str, coalesce_key) -> None:
    """T-3746: start-событие задачи через контракт MCA-13 (fail-open)."""
    try:
        from services import mca_events as me
        me.emit_mca_event("TASK_START", outcome=me.OUTCOME_START,
                          component="task_supervisor",
                          operation_id=coalesce_key or owner,
                          reason_code=None)
    except Exception:
        return


def _emit_terminal(owner: str, kind: str, coalesce_key, outcome: str,
                   result_ref) -> None:
    try:
        from services import mca_events as me
        me.emit_mca_event("TASK_TERMINAL", outcome=outcome,
                          component="task_supervisor",
                          operation_id=coalesce_key or owner,
                          reason_code=None)
    except Exception:
        return


def _emit_failure(exc: BaseException, owner: str, kind: str,
                  coalesce_key) -> None:
    try:
        from services import mca_events as me
        meta = me.build_error_metadata(exc, stage="task", retryable=False)
        me.emit_mca_event("TASK_FAILED", outcome=me.OUTCOME_FAILED,
                          level=me.LEVEL_ERROR, component="task_supervisor",
                          operation_id=coalesce_key or owner,
                          error_json=meta)
    except Exception:
        return


class TaskSupervisor:
    """In-process реестр задач + coalescing + bounded-очередь.

    max_concurrent — потолок одновременно выполняемых задач (bounded).
    Класс `important` при заполнении ожидает слот (не теряется молча);
    `secondary` при заполнении отклоняется `QueueFullError` с причиной.
    """

    def __init__(self, max_concurrent: int = 16,
                 max_registry: int = 1024) -> None:
        self._max_concurrent = max(1, max_concurrent)
        self._max_registry = max(1, max_registry)
        self._registry: dict[str, TaskRecord] = {}
        self._running = 0
        # B-MCA01-2: `asyncio.Condition` вместо Lock+Event — `wait_for`
        # освобождает блокировку во время ожидания слота, поэтому
        # завершающаяся задача может освободить слот и разбудить ожидающего
        # (устранён deadlock важной очереди).
        self._cond = asyncio.Condition()
        # singleflight: coalesce_key → task_id владельца
        self._coalesce: dict[str, str] = {}

    # ── интроспекция (тесты/витрина) ──────────────────────────────────────

    def get(self, task_id: str) -> TaskRecord | None:
        return self._registry.get(task_id)

    def registry_size(self) -> int:
        return len(self._registry)

    def running_count(self) -> int:
        return self._running

    def active(self) -> list[TaskRecord]:
        return [r for r in self._registry.values() if r.status == "running"]

    # ── выполнение ────────────────────────────────────────────────────────

    async def run(self, coro_factory: Callable[[], Awaitable],
                  *, owner: str, kind: str = KIND_SECONDARY,
                  coalesce_key: str | None = None,
                  deadline_at: float | None = None,
                  exception_handler: Callable[[BaseException], Awaitable[None]]
                  | None = None,
                  job_store: "TaskJobStore | None" = None,
                  emit_event: bool = True,
                  pipeline_run_id: str | None = None,
                  span_id: str | None = None,
                  parent_span_id: str | None = None,
                  causation_id: str | None = None,
                  attempt_id: str | None = None,
                  checkpoint_ref: str | None = None) -> TaskRecord:
        """Запустить задачу под реестром/коалесингом/лимитом.

        `coro_factory()` вызывается ровно один раз при реальном старте.
        OFF-паритет (`MCA_TASK_SUPERVISOR_ENABLED=false`) → без реестра/
        коалесинга/лимита: просто await корутины.

        `job_store` (T-3740) → durable-жизненный цикл в `task_jobs`
        (queued→running→terminal) + heartbeat. `emit_event` (T-3746) →
        события контракта MCA-13 (start/terminal, `failure`/`success`)."""
        if not task_supervisor_enabled():
            await coro_factory()
            return TaskRecord(task_id="", owner=owner, kind=kind,
                              status=OUTCOME_COMPLETED)
        # L-MCA01-3: in-process singleflight проверяется ДО durable-enqueue —
        # коалесцированный вызов не создаёт и не «трогает» durable-строку
        # (attempt/heartbeat не инкрементируются впустую).
        async with self._cond:
            if coalesce_key is not None:
                existing_id = self._coalesce.get(coalesce_key)
                if existing_id is not None:
                    existing = self._registry.get(existing_id)
                    if existing is not None and existing.status == "running":
                        return existing
        job_id: str | None = None
        fence: int | None = None
        if job_store is not None:
            try:
                job_id = await job_store.enqueue(
                    owner=owner, kind=kind, coalesce_key=coalesce_key,
                    deadline_at=(int(deadline_at) if deadline_at else None),
                    pipeline_run_id=pipeline_run_id, span_id=span_id,
                    parent_span_id=parent_span_id, causation_id=causation_id,
                    attempt_id=attempt_id, checkpoint_ref=checkpoint_ref)
                await job_store.mark_running(job_id)
                # B-MCA01-3: запоминаем выданный fencing_token владельца —
                # все терминальные записи обусловлены им. После takeover
                # (`recover_stale` бампает токен) устаревший владелец не
                # перезапишет результат нового (A51).
                row = await job_store.get(job_id)
                if row is not None:
                    fence = int(row.get("fencing_token") or 0)
            except Exception:
                logger.warning("task_supervisor: durable enqueue failed",
                               exc_info=True)
                job_id = None
                fence = None
        _emit_start(owner, kind, coalesce_key) if emit_event else None
        # B-MCA01-2: безопасное ожидание слота под Condition.
        # `wait_for` освобождает блокировку во время ожидания — завершающаяся
        # задача успевает снять слот и разбудить ожидающего (нет deadlock).
        async with self._cond:
            if coalesce_key is not None:
                existing_id = self._coalesce.get(coalesce_key)
                if existing_id is not None:
                    existing = self._registry.get(existing_id)
                    if existing is not None and existing.status == "running":
                        # race-окно: коалесцированный вызов успел создать свою
                        # durable-строку — снимаем её как лишнюю.
                        if job_id is not None:
                            await _safe_finish(job_store, job_id,
                                               JOB_CANCELLED,
                                               REASON_QUEUE_COALESCED)
                        return existing
            # bounded: важное ждёт слот, второстепенное отклоняется с причиной.
            # `Condition.wait_for` освобождает блокировку во время ожидания —
            # завершающаяся задача успевает снять слот (нет deadlock).
            if self._running >= self._max_concurrent:
                if kind != KIND_IMPORTANT:
                    if job_id is not None:
                        await _safe_finish(job_store, job_id, JOB_CANCELLED,
                                           REASON_QUEUE_FULL,
                                           fencing_token=fence)
                    raise QueueFullError(REASON_QUEUE_FULL)
                await self._cond.wait_for(
                    lambda: self._running < self._max_concurrent)
            record = TaskRecord(
                task_id=uuid.uuid4().hex, owner=owner, kind=kind,
                deadline_at=deadline_at, coalesce_key=coalesce_key,
                exception_handler=exception_handler)
            record.job_id = job_id
            self._registry[record.task_id] = record
            if coalesce_key is not None:
                self._coalesce[coalesce_key] = record.task_id
            self._running += 1
            if len(self._registry) > self._max_registry:
                self._prune_finished_locked()
        try:
            result = await coro_factory()
            async with self._cond:
                record.status = OUTCOME_COMPLETED
                record.result_ref = (
                    result if isinstance(result, str) else None)
                record.finished_at = time.time()
                self._release_locked(record)
            if job_id is not None:
                await _safe_finish(job_store, job_id, JOB_COMPLETED, None,
                                   result_ref=record.result_ref,
                                   fencing_token=fence)
            if emit_event:
                _emit_terminal(owner, kind, coalesce_key, "success",
                               record.result_ref)
            return record
        except asyncio.CancelledError:
            async with self._cond:
                record.status = OUTCOME_CANCELLED
                record.finished_at = time.time()
                self._release_locked(record)
            if job_id is not None:
                # L-MCA01-5: fencing и в cancelled-пути — после takeover
                # «медленный» владелец не перезапишет терминальную строку.
                await _safe_finish(job_store, job_id, JOB_CANCELLED,
                                   "cancelled", fencing_token=fence)
            if emit_event:
                _emit_terminal(owner, kind, coalesce_key, "cancelled",
                               None)
            raise
        except BaseException as exc:  # noqa: BLE001 — видимый терминальный исход
            record.status = OUTCOME_FAILED
            record.error_code = type(exc).__name__
            record.finished_at = time.time()
            if job_id is not None:
                # L-MCA01-5: fencing и в failed-пути (симметрично success).
                await _safe_finish(job_store, job_id, JOB_FAILED,
                                   "task_failed",
                                   error_code=type(exc).__name__,
                                   fencing_token=fence)
            if exception_handler is not None:
                try:
                    await exception_handler(exc)
                except Exception:
                    logger.warning(
                        "task_supervisor: exception_handler failed | "
                        "task_id=%s", record.task_id, exc_info=True)
            else:
                logger.warning(
                    "task_supervisor: task failed | owner=%s | kind=%s | "
                    "error=%s", owner, kind, type(exc).__name__, exc_info=True)
            async with self._cond:
                self._release_locked(record)
            if emit_event:
                _emit_failure(exc, owner, kind, coalesce_key)
            raise

    def _release_locked(self, record: TaskRecord) -> None:
        """Под Condition: снять слот, снять коалесинг, разбудить ожидающих.

        B-MCA01-2: `notify_all` вместо `Event.set` — будит важных ожидающих,
        которые пере-проверят условие и займут освободившийся слот."""
        self._running = max(0, self._running - 1)
        if record.coalesce_key is not None and \
                self._coalesce.get(record.coalesce_key) == record.task_id:
            self._coalesce.pop(record.coalesce_key, None)
        self._cond.notify_all()

    def _prune_finished_locked(self) -> None:
        """Под Condition: удалить старейшие терминальные записи (bounded)."""
        finished = sorted(
            (r for r in self._registry.values()
             if r.status != "running" and r.finished_at is not None),
            key=lambda r: r.finished_at or 0.0)
        for rec in finished:
            if len(self._registry) <= self._max_registry:
                break
            self._registry.pop(rec.task_id, None)


_supervisor_singleton: TaskSupervisor | None = None


def get_task_supervisor() -> TaskSupervisor:
    """Модульный синглтон супервизора (как get_smart_cache/pool)."""
    global _supervisor_singleton
    if _supervisor_singleton is None:
        _supervisor_singleton = TaskSupervisor()
    return _supervisor_singleton


def reset_task_supervisor() -> None:
    """Сброс синглтона для тестов."""
    global _supervisor_singleton
    _supervisor_singleton = None


# ── T-3740 (v14): durable-стор `task_jobs` ──────────────────────────────────

# Статусы durable-очереди (рамка §1.1.1).
JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"
JOB_INTERRUPTED = "interrupted"
ACTIVE_JOB_STATUSES = (JOB_QUEUED, JOB_RUNNING)

# Колонки `task_jobs` (порядок INSERT; `updated_at`/`finished_at` — отдельно).
# v19 (`mca-17a`, ADR-1027-8 D2/D4): correlation/span/progress-колонки.
_JOB_INSERT_COLS = (
    "job_id", "owner", "kind", "coalesce_key", "payload", "status",
    "reason_code", "result_ref", "error_code", "attempt", "max_attempts",
    "deadline_at", "heartbeat_at", "generation", "fencing_token",
    "created_at", "updated_at", "finished_at",
    "pipeline_run_id", "span_id", "parent_span_id", "causation_id",
    "attempt_id", "progress_at", "next_retry_at", "checkpoint_ref",
)


class TaskJobStore:
    """Durable-очередь задач в SQLite-таблице `task_jobs` (v14).

    Записи идут через `DatabaseService.write_transaction` (mca-01, single-
    writer); чтения — короткие SELECT'ы. Fail-safe: методы не бросают наружу
    ничего, кроме явных ошибок БД на write-пути (их видит вызывающий).
    """

    def __init__(self, db) -> None:
        self._db = db

    # ── write ─────────────────────────────────────────────────────────────

    async def enqueue(self, *, owner: str, kind: str, coalesce_key=None,
                      payload=None, max_attempts: int = 1,
                      deadline_at=None, generation: int = 0,
                      job_id: str | None = None,
                      pipeline_run_id=None, span_id=None, parent_span_id=None,
                      causation_id=None, attempt_id=None,
                      progress_at=None, next_retry_at=None,
                      checkpoint_ref=None) -> str:
        """Поставить задачу в очередь. Возвращает `job_id`.

        Dedup активного `coalesce_key` — по unique partial-индексу (v14): при
        конфликте возвращается `job_id` уже активной задачи (singleflight).
        Correlation/span-поля (v19, §27.3) сохраняются в durable-очереди и
        восстанавливаются при resume."""
        jid = job_id or uuid.uuid4().hex
        now = int(time.time())

        async def _body(conn):
            await conn.execute(
                "INSERT OR IGNORE INTO task_jobs ("
                + ", ".join(_JOB_INSERT_COLS) + ") VALUES ("
                + ", ".join("?" * len(_JOB_INSERT_COLS)) + ")",
                (jid, owner, kind, coalesce_key, payload, JOB_QUEUED,
                 None, None, None, 0, max(1, int(max_attempts)),
                 deadline_at, now, int(generation), 0, now, now, None,
                 pipeline_run_id, span_id, parent_span_id, causation_id,
                 attempt_id, progress_at, next_retry_at, checkpoint_ref))
            if coalesce_key is None:
                return jid
            cursor = await conn.execute(
                "SELECT job_id FROM task_jobs WHERE coalesce_key = ? "
                "AND status IN (?, ?) LIMIT 1",
                (coalesce_key, JOB_QUEUED, JOB_RUNNING))
            row = await cursor.fetchone()
            return row["job_id"] if row is not None else jid

        return await self._db.write_transaction(
            _body, op_name="task_jobs_enqueue")

    async def mark_running(self, job_id: str, *, fencing_token: int | None
                           = None) -> bool:
        """Перевести задачу в `running`, обновить heartbeat/attempt/fencing.

        L-MCA01-3: UPDATE обусловлен `status = 'queued'` — если переданный
        `job_id` это уже активная (запущенная) задача из durable-dedup, повторный
        `mark_running` не инкрементирует `attempt`/heartbeat впустую."""
        now = int(time.time())
        token = fencing_token

        async def _body(conn):
            cursor = await conn.execute(
                "SELECT fencing_token FROM task_jobs WHERE job_id = ?",
                (job_id,))
            row = await cursor.fetchone()
            if row is None:
                return 0
            use_token = int(token) if token is not None \
                else int(row["fencing_token"] or 0)
            cur2 = await conn.execute(
                "UPDATE task_jobs SET status = ?, heartbeat_at = ?, "
                "attempt = attempt + 1, fencing_token = ?, updated_at = ? "
                "WHERE job_id = ? AND status = ?",
                (JOB_RUNNING, now, use_token, now, job_id, JOB_QUEUED))
            return cur2.rowcount

        return bool(await self._db.write_transaction(
            _body, op_name="task_jobs_running"))

    async def heartbeat(self, job_id: str, *,
                        fencing_token: int | None = None) -> bool:
        """Обновить `heartbeat_at` (живость владельца).

        B-MCA01-3: при заданном `fencing_token` запись обусловлена им —
        устаревший владелец (токен не совпал) получает `False` (no-op)."""
        now = int(time.time())
        token = fencing_token

        async def _body(conn):
            if token is None:
                cursor = await conn.execute(
                    "UPDATE task_jobs SET heartbeat_at = ?, updated_at = ? "
                    "WHERE job_id = ?", (now, now, job_id))
            else:
                cursor = await conn.execute(
                    "UPDATE task_jobs SET heartbeat_at = ?, updated_at = ? "
                    "WHERE job_id = ? AND fencing_token = ?",
                    (now, now, job_id, int(token)))
            return cursor.rowcount

        return bool(await self._db.write_transaction(
            _body, op_name="task_jobs_heartbeat"))

    async def finish(self, job_id: str, *, status: str,
                     reason_code: str | None = None,
                     result_ref: str | None = None,
                     error_code: str | None = None,
                     generation: int | None = None,
                     fencing_token: int | None = None) -> bool:
        """Терминальный исход: `completed|failed|cancelled|interrupted`.

        B-MCA01-3: при заданном `fencing_token` UPDATE обусловлен им — запись
        устаревшего владельца после takeover отклоняется (no-op, `False`)."""
        now = int(time.time())
        token = fencing_token

        async def _body(conn):
            fence = "" if token is None else " AND fencing_token = ?"
            base_params = [status, reason_code, result_ref, error_code]
            if generation is not None:
                sql = ("UPDATE task_jobs SET status = ?, reason_code = ?, "
                       "result_ref = ?, error_code = ?, generation = ?, "
                       "updated_at = ?, finished_at = ? WHERE job_id = ?")
                params = base_params + [int(generation), now, now, job_id]
            else:
                sql = ("UPDATE task_jobs SET status = ?, reason_code = ?, "
                       "result_ref = ?, error_code = ?, updated_at = ?, "
                       "finished_at = ? WHERE job_id = ?")
                params = base_params + [now, now, job_id]
            if token is not None:
                sql += fence
                params.append(int(token))
            cursor = await conn.execute(sql, tuple(params))
            return cursor.rowcount

        return bool(await self._db.write_transaction(
            _body, op_name="task_jobs_finish"))

    async def recover_stale(self, *, stale_after_seconds: int) -> list[str]:
        """Пометить `running`-задачи без свежего heartbeat как `interrupted`.

        Возвращает список job_id (takeover-кандидаты). `fencing_token`
        увеличивается — старый владелец потеряет право записи (A51)."""
        cutoff = int(time.time()) - max(1, int(stale_after_seconds))

        async def _body(conn):
            cursor = await conn.execute(
                "SELECT job_id FROM task_jobs WHERE status = ? AND "
                "(heartbeat_at IS NULL OR heartbeat_at < ?)",
                (JOB_RUNNING, cutoff))
            ids = [r["job_id"] for r in await cursor.fetchall()]
            for jid in ids:
                await conn.execute(
                    "UPDATE task_jobs SET status = ?, reason_code = ?, "
                    "fencing_token = fencing_token + 1, updated_at = ? "
                    "WHERE job_id = ?",
                    (JOB_INTERRUPTED, "worker_lost", int(time.time()), jid))
            return ids

        return await self._db.write_transaction(
            _body, op_name="task_jobs_recover")

    async def prune(self, *, terminal_retention_seconds: int,
                    keep_active: bool = True) -> int:
        """Удалить терминальные задачи старше ретенции (bounded disk)."""
        cutoff = int(time.time()) - max(1, int(terminal_retention_seconds))

        async def _body(conn):
            cursor = await conn.execute(
                "DELETE FROM task_jobs WHERE status NOT IN (?, ?) AND "
                "finished_at IS NOT NULL AND finished_at < ?",
                (JOB_QUEUED, JOB_RUNNING, cutoff))
            return cursor.rowcount

        return int(await self._db.write_transaction(
            _body, op_name="task_jobs_prune") or 0)

    # ── read ──────────────────────────────────────────────────────────────

    async def get(self, job_id: str) -> dict | None:
        cursor = await self._db.db.execute(
            "SELECT * FROM task_jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def active(self) -> list[dict]:
        cursor = await self._db.db.execute(
            "SELECT * FROM task_jobs WHERE status IN (?, ?) "
            "ORDER BY created_at", (JOB_QUEUED, JOB_RUNNING))
        return [dict(r) for r in await cursor.fetchall()]

    async def overdue(self, *, now: int | None = None) -> list[dict]:
        ts = int(now if now is not None else time.time())
        cursor = await self._db.db.execute(
            "SELECT * FROM task_jobs WHERE status IN (?, ?) AND "
            "deadline_at IS NOT NULL AND deadline_at < ? "
            "ORDER BY deadline_at", (JOB_QUEUED, JOB_RUNNING, ts))
        return [dict(r) for r in await cursor.fetchall()]

    async def depth(self) -> int:
        cursor = await self._db.db.execute(
            "SELECT COUNT(*) AS c FROM task_jobs WHERE status = ?",
            (JOB_QUEUED,))
        row = await cursor.fetchone()
        return int(row["c"]) if row is not None else 0

    async def save_checkpoint(self, job_id: str, *, cursor_token: str,
                              processed: int,
                              fencing_token: int | None = None,
                              checkpoint_ref: str | None = None) -> bool:
        """T-3757: сохранить checkpoint архивного задания (после фиксации).

        Checkpoint — R17-safe JSON в `payload`; короткая транзакция (не
        держим её на весь диапазон). B-MCA01-3: при заданном `fencing_token`
        запись устаревшего владельца отклоняется (no-op, `False`).
        v19 (`mca-17a`): обновляются `checkpoint_ref`/`progress_at`
        (фактический progress marker, §27.5).
        ASAP-4 волна B (L-EXTRA-6, spec §2 B.5, T-4416): payload — MERGE, не
        overwrite: `cursor`/`processed` вливаются в существующий payload
        (cover-джобы хранят там chat_id/correlation_id/style_id — рестарт
        восстанавливает identity джобы; graphrag-resume workaround остаётся
        валидным — он срабатывает только при отсутствующих полях)."""
        now = int(time.time())
        token = fencing_token
        cref = checkpoint_ref or f"cp:{int(processed)}"

        async def _body(conn):
            cursor = await conn.execute(
                "SELECT payload FROM task_jobs WHERE job_id = ?", (job_id,))
            row = await cursor.fetchone()
            base: dict = {}
            if row is not None and row["payload"]:
                try:
                    parsed = json.loads(row["payload"])
                    if isinstance(parsed, dict):
                        base = parsed
                except ValueError:
                    base = {}
            merged = dict(base)
            merged["cursor"] = str(cursor_token)
            merged["processed"] = int(processed)
            payload = json.dumps(merged, ensure_ascii=False)
            update = ("UPDATE task_jobs SET payload = ?, result_ref = ?, "
                      "checkpoint_ref = ?, progress_at = ?, updated_at = ? "
                      "WHERE job_id = ?")
            params = [payload, str(processed), cref, now, now, job_id]
            if token is not None:
                update += " AND fencing_token = ?"
                params.append(int(token))
            cursor = await conn.execute(update, tuple(params))
            return cursor.rowcount

        return bool(await self._db.write_transaction(
            _body, op_name="task_jobs_checkpoint"))

    async def set_progress(self, job_id: str, *,
                           fencing_token: int | None = None) -> bool:
        """Обновить `progress_at` (фактический progress marker; ≠ heartbeat)."""
        now = int(time.time())
        token = fencing_token

        async def _body(conn):
            if token is None:
                cursor = await conn.execute(
                    "UPDATE task_jobs SET progress_at = ?, updated_at = ? "
                    "WHERE job_id = ?", (now, now, job_id))
            else:
                cursor = await conn.execute(
                    "UPDATE task_jobs SET progress_at = ?, updated_at = ? "
                    "WHERE job_id = ? AND fencing_token = ?",
                    (now, now, job_id, int(token)))
            return cursor.rowcount

        return bool(await self._db.write_transaction(
            _body, op_name="task_jobs_progress"))

    async def cancel(self, job_id: str, *,
                     reason_code: str | None = None) -> bool:
        """mca-17c (round 10.47, ADR-1028-23 D10): отменить АКТИВНУЮ задачу
        (queued/running → cancelled) — санкционированный expose для
        `POST /api/oversight/jobs/{job_id}/action`.

        Тот же терминальный исход, что internal-cancel supervisor'а
        (`finish`/JOB_CANCELLED), + bump `fencing_token` (механизм
        `recover_stale`, A51/B-MCA01-3): устаревший владелец после отмены
        не перезапишет терминальный статус — его `finish` станет no-op.
        Терминальные строки не трогаются (no-op, `False`) —
        идемпотентность state-машины; повторный cancel — no-op."""
        now = int(time.time())

        async def _body(conn):
            cursor = await conn.execute(
                "UPDATE task_jobs SET status = ?, "
                "reason_code = COALESCE(?, reason_code), "
                "fencing_token = fencing_token + 1, updated_at = ?, "
                "finished_at = ? WHERE job_id = ? AND status IN (?, ?)",
                (JOB_CANCELLED, reason_code, now, now, job_id,
                 JOB_QUEUED, JOB_RUNNING))
            return cursor.rowcount

        return bool(await self._db.write_transaction(
            _body, op_name="task_jobs_cancel"))

    async def requeue(self, job_id: str, *,
                      reason_code: str | None = None,
                      fencing_token: int | None = None) -> bool:
        """Вернуть задачу в `queued` (resume/retry): снять терминальность.

        `finished_at` очищается (задача снова активна), `attempt` не сбрасывается
        (история попыток сохраняется; retry = новая попытка, §27.3)."""
        now = int(time.time())
        token = fencing_token

        async def _body(conn):
            sql = ("UPDATE task_jobs SET status = ?, reason_code = ?, "
                   "finished_at = NULL, error_code = NULL, updated_at = ? "
                   "WHERE job_id = ?")
            params = [JOB_QUEUED, reason_code, now, job_id]
            if token is not None:
                sql += " AND fencing_token = ?"
                params.append(int(token))
            cursor = await conn.execute(sql, tuple(params))
            return cursor.rowcount

        return bool(await self._db.write_transaction(
            _body, op_name="task_jobs_requeue"))

    async def set_next_retry(self, job_id: str, next_retry_at: int,
                             *, reason_code: str | None = None) -> bool:
        """Запланировать bounded-retry: `next_retry_at` + `retry_scheduled`."""
        now = int(time.time())

        async def _body(conn):
            cursor = await conn.execute(
                "UPDATE task_jobs SET next_retry_at = ?, status = ?, "
                "reason_code = COALESCE(?, reason_code), updated_at = ? "
                "WHERE job_id = ? AND status != ?",
                (int(next_retry_at), JOB_QUEUED, reason_code, now, job_id,
                 JOB_INTERRUPTED))
            return cursor.rowcount

        return bool(await self._db.write_transaction(
            _body, op_name="task_jobs_next_retry"))

    async def get_checkpoint(self, job_id: str) -> dict | None:
        """T-3757: прочитать checkpoint для resume (None — нет/битый)."""
        row = await self.get(job_id)
        if row is None or not row.get("payload"):
            return None
        try:
            data = json.loads(row["payload"])
            return data if isinstance(data, dict) else None
        except Exception:
            return None

