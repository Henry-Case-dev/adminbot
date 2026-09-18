"""F8 round 10.22 (ADR-1022-8) — персистентный job-store + фоновый раннер
асинхронной пересборки досье участника из мини-аппа.

Контур (spec §2):
  * `DossierRebuildJobStore` — файловый JSON-стор (`tmp`→`os.replace`+fsync),
    один писатель (`asyncio.Lock`), retention (последние 50 job'ов / 7 дней,
    активные не вытесняются), in-process реестр `job_id → asyncio.Task`.
    БЕЗ DDL: SQLite остаётся v12.
  * `acquire_chat_lock`/`release_chat_lock` — кросс-процессный file-lock per
    chat (`O_CREAT|O_EXCL`) против одновременного CLI-прогона F1 (stale по TTL).
  * `create_user_snapshot`/`restore_user_snapshot`/`archive_user_derived` —
    точечный снапшот производных юзера на старте (fail-closed) и rollback при
    отмене. Сырая история/overrides/beliefs/nodes/edges НЕ трогаются.
  * `run_dossier_rebuild` — фоновый раннер: snapshot → confirmed-cleanup (F1)
    → аддитивный `LoreWorker.rebuild_dossier_for_user` (чанки/прогресс/отмена)
    → finalize; при отмене — rollback из снапшота (идемпотентно).

R17: персистим/логируем только числа/коды/счётчики; текстов фактов, полных
путей и секретов в job-view нет.
"""
import asyncio
import inspect
import json
import logging
import os
import time
from pathlib import Path

from config.settings import settings
from services.memory_maintenance import _flush_fsync_and_dir

logger = logging.getLogger(__name__)

_JOBS_FILE = "dossier_rebuild_jobs.json"
_SNAPSHOT_PREFIX = "rollback_"
_CANCELLED_PREFIX = "cancelled_"
# S10.22-5: `interrupted` — НЕ активный статус. После рестарта такие job'ы
# навсегда оставались «активными»: `find_active` блокировал новый старт (409),
# а `_prune` не применял к ним retention. Теперь новый старт разрешён, а
# прерванные job'ы вытесняются по retention (последние 50 / 7 дней).
_ACTIVE_STATUSES = frozenset({"queued", "running", "cancelling"})
_TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})
_RETENTION_MAX = 50
_RETENTION_DAYS = 7
_LOCK_PREFIX = "rebuild_"


def _now() -> int:
    return int(time.time())


def jobs_dir(base_dir=None) -> Path:
    """Каталог job-store/lock'ов (`<MEMORY_BACKUP_DIR>/dossier_jobs`).

    Единая точка для API и CLI (R6/spec §2.7): UI-джоба берёт lock через
    `DossierRebuildJobStore.dir_path`, CLI F1 — через этот helper. Иначе
    кросс-процессная защита CLI ↔ UI не сработает."""
    base = (base_dir if base_dir is not None
            else getattr(settings, "MEMORY_BACKUP_DIR", "backups"))
    return Path(str(base)) / "dossier_jobs"


# ── file-lock per chat (vs CLI-прогон F1) ───────────────────────────────────

class ChatRebuildLock:
    """Хэндл удерживаемого file-lock после успешного acquire."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._released = False

    def release(self) -> None:
        """Удалить lock-файл (идемпотентно; missing-ok)."""
        if self._released:
            return
        self._released = True
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            logger.debug("[dossier_jobs] lock release failed")


def acquire_chat_lock(jobs_dir, chat_id: int, *,
                      ttl_seconds: int | None = None) -> ChatRebuildLock | None:
    """Попытаться взять file-lock на чат. None — уже занят (не stale).

    Stale (возраст > TTL или битый файл) перехватывается АТОМАРНО: под
    уникальным takeover-маркером (`O_CREAT|O_EXCL`) перепроверяем возраст и
    переносим старый lock через `os.replace` в tombstone, затем создаём lock
    строго `O_EXCL`. Параллельный stale-перехватчик не сработает. R17: в лог
    только chat_id и код причины."""
    directory = Path(jobs_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_LOCK_PREFIX}{int(chat_id)}.lock"
    ttl = int(ttl_seconds if ttl_seconds is not None
              else getattr(settings, "DOSSIER_REBUILD_LOCK_TTL_SECONDS",
                           6 * 3600) or 6 * 3600)
    payload = json.dumps({"pid": os.getpid(), "ts": _now()})

    def _try_create() -> ChatRebuildLock | None:
        try:
            with open(path, "x", encoding="utf-8") as fh:
                fh.write(payload)
            return ChatRebuildLock(path)
        except FileExistsError:
            return None
        except OSError:
            return None

    def _is_stale() -> bool:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            age = _now() - int(data.get("ts") or 0)
            return age > ttl
        except Exception:
            return True                      # битый lock — перехватываем

    handle = _try_create()
    if handle is not None:
        return handle
    if not _is_stale():
        return None
    # Сериализуем перехват: маркер-файл создаётся только одним процессом.
    takeover = directory / f"{_LOCK_PREFIX}{int(chat_id)}.takeover"
    try:
        fd = os.open(takeover, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None                          # перехват уже идёт
    except OSError:
        return None
    try:
        if not _is_stale():                  # перепроверка под маркером
            return None
        logger.warning("[dossier_jobs] stale chat-lock takeover | chat=%s",
                       chat_id)
        tombstone = directory / (
            f"{_LOCK_PREFIX}{int(chat_id)}.{os.getpid()}.stale")
        try:
            os.replace(path, tombstone)
        except OSError:
            return None
        handle = _try_create()
        try:
            tombstone.unlink(missing_ok=True)
        except OSError:
            pass
        return handle
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            takeover.unlink(missing_ok=True)
        except OSError:
            pass


def release_chat_lock(chat_id: int, jobs_dir) -> None:
    """Удалить lock-файл чата (best-effort; для CLI-совместимости)."""
    try:
        (Path(jobs_dir) / f"{_LOCK_PREFIX}{int(chat_id)}.lock").unlink(
            missing_ok=True)
    except OSError:
        pass


# ── job-store ───────────────────────────────────────────────────────────────

def _job_defaults(job_id: str, *, chat_id: int, user_id: int,
                  target_name: str, actor_id: int, period: str,
                  window_hours: int, chunk_size: int, total: int) -> dict:
    ts = _now()
    return {
        "job_id": job_id,
        "chat_id": int(chat_id),
        "user_id": int(user_id),
        "target_name": str(target_name or ""),
        "actor_id": int(actor_id or 0),
        "period": str(period or "180"),
        "window_hours": int(window_hours or 0),
        "chunk_size": int(chunk_size or 0),
        "status": "queued",
        "stage": "snapshot",
        "total": int(total or 0),
        "processed": 0,
        "cleaned": 0,
        "rebuilt": 0,
        "snapshot_ref": f"{_SNAPSHOT_PREFIX}{job_id}.jsonl",
        "rollback": {"done": False, "restored_facts": 0, "reason": ""},
        "cancel_requested": False,
        "error_code": None,
        "created_at": ts,
        "updated_at": ts,
        "started_at": 0,
        "finished_at": None,
    }


def job_view(job: dict) -> dict:
    """R17-safe представление job'а для UI: числа/коды/`snapshot_ref`-basename.
    Текстов фактов, `target_name` и полных путей нет."""
    if not isinstance(job, dict):
        return {}
    total = int(job.get("total") or 0)
    processed = max(0, int(job.get("processed") or 0))
    if total > 0:
        percent = int(round(100.0 * min(processed, total) / total))
    else:
        percent = 100 if job.get("status") == "done" else 0
    rollback = job.get("rollback") or {}
    snap = str(job.get("snapshot_ref") or "")
    return {
        "job_id": str(job.get("job_id") or ""),
        "chat_id": int(job.get("chat_id") or 0),
        "user_id": int(job.get("user_id") or 0),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "period": job.get("period"),
        "window_hours": int(job.get("window_hours") or 0),
        "chunk_size": int(job.get("chunk_size") or 0),
        "total": total,
        "processed": processed,
        "percent": percent,
        "cleaned": int(job.get("cleaned") or 0),
        "rebuilt": int(job.get("rebuilt") or 0),
        "snapshot_ref": Path(snap).name if snap else "",
        "rollback": {
            "done": bool(rollback.get("done")),
            "restored_facts": int(rollback.get("restored_facts") or 0),
            "reason": str(rollback.get("reason") or "")[:64],
        },
        "cancel_requested": bool(job.get("cancel_requested")),
        "error_code": job.get("error_code"),
        "created_at": int(job.get("created_at") or 0),
        "updated_at": int(job.get("updated_at") or 0),
        "started_at": int(job.get("started_at") or 0),
        "finished_at": job.get("finished_at"),
    }


class DossierRebuildJobStore:
    """Файловый JSON job-store (один писатель, атомарная запись, retention)."""

    def __init__(self, base_dir=None, *, retention_max: int = _RETENTION_MAX,
                 retention_days: int = _RETENTION_DAYS):
        self._base_dir = base_dir
        self._retention_max = int(retention_max)
        self._retention_days = int(retention_days)
        self._lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task] = {}
        self._jobs: dict[str, dict] = {}
        self._loaded = False

    # ── пути/IO ─────────────────────────────────────────────────────────
    @property
    def dir_path(self) -> Path:
        return jobs_dir(self._base_dir)

    def _file(self) -> Path:
        return self.dir_path / _JOBS_FILE

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        jobs: dict[str, dict] = {}
        try:
            raw = self._file().read_text(encoding="utf-8")
            data = json.loads(raw)
            for item in (data.get("jobs") or []):
                if isinstance(item, dict) and item.get("job_id"):
                    jobs[str(item["job_id"])] = item
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("[dossier_jobs] job-store read failed — пусто")
        self._jobs = jobs

    def _persist_sync(self) -> None:
        directory = self.dir_path
        directory.mkdir(parents=True, exist_ok=True)
        target = self._file()
        tmp = target.with_name(target.name + ".tmp")
        payload = {"version": 1,
                   "jobs": list((self._jobs or {}).values())}
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
            _flush_fsync_and_dir(fh, directory)
        os.replace(tmp, target)

    async def _persist(self) -> None:
        await asyncio.to_thread(self._persist_sync)

    def _prune(self) -> None:
        """Retention: активные не вытесняются; у терминальных — не больше
        `retention_max` и не старше `retention_days`. Снапшоты удалённых
        job'ов сносятся вместе с записью."""
        now = _now()
        terminal = sorted(
            ((jid, j) for jid, j in self._jobs.items()
             if j.get("status") not in _ACTIVE_STATUSES),
            key=lambda kv: (kv[1].get("finished_at")
                            or kv[1].get("created_at") or 0))
        excess = len(terminal) - self._retention_max
        for index, (jid, job) in enumerate(terminal):
            ts = job.get("finished_at") or job.get("created_at") or 0
            expired = (self._retention_days > 0
                       and (now - int(ts or 0)) > self._retention_days * 86400)
            if index < excess or expired:
                self._jobs.pop(jid, None)
                self._remove_artifact(jid, job.get("snapshot_ref"))

    def _remove_artifact(self, job_id: str, snapshot_ref) -> None:
        for name in (snapshot_ref, f"{_CANCELLED_PREFIX}{job_id}.jsonl"):
            if not name:
                continue
            try:
                (self.dir_path / Path(str(name)).name).unlink(missing_ok=True)
            except OSError:
                pass

    # ── async API (один писатель) ───────────────────────────────────────
    async def create(self, job_id: str, *, chat_id: int, user_id: int,
                     target_name: str, actor_id: int = 0, period: str = "180",
                     window_hours: int = 4320, chunk_size: int = 40,
                     total: int = 0) -> dict:
        async with self._lock:
            self._ensure_loaded()
            job = _job_defaults(
                job_id, chat_id=chat_id, user_id=user_id,
                target_name=target_name, actor_id=actor_id, period=period,
                window_hours=window_hours, chunk_size=chunk_size, total=total)
            self._jobs[job_id] = job
            self._prune()
            await self._persist()
            return dict(job)

    async def update(self, job_id: str, **fields) -> dict | None:
        async with self._lock:
            self._ensure_loaded()
            job = self._jobs.get(str(job_id))
            if job is None:
                return None
            job.update(fields)
            job["updated_at"] = _now()
            self._prune()
            await self._persist()
            return dict(job)

    async def get(self, job_id: str) -> dict | None:
        async with self._lock:
            self._ensure_loaded()
            job = self._jobs.get(str(job_id))
            return dict(job) if job else None

    async def latest(self, chat_id: int, user_id: int) -> dict | None:
        async with self._lock:
            self._ensure_loaded()
            return self._latest_locked(chat_id, user_id)

    def _latest_locked(self, chat_id: int, user_id: int) -> dict | None:
        cands = [j for j in self._jobs.values()
                 if int(j.get("chat_id") or 0) == int(chat_id)
                 and int(j.get("user_id") or 0) == int(user_id)]
        if not cands:
            return None
        cands.sort(key=lambda j: (j.get("created_at") or 0), reverse=True)
        return dict(cands[0])

    async def find_active(self, chat_id: int, user_id: int) -> dict | None:
        async with self._lock:
            self._ensure_loaded()
            for job in self._jobs.values():
                if (int(job.get("chat_id") or 0) == int(chat_id)
                        and int(job.get("user_id") or 0) == int(user_id)
                        and job.get("status") in _ACTIVE_STATUSES):
                    return dict(job)
            return None

    def get_sync(self, job_id: str) -> dict | None:
        """Снимок job'а без ожидания lock (для sync `cancel_cb` прогресса)."""
        self._ensure_loaded()
        job = self._jobs.get(str(job_id))
        return dict(job) if job else None

    async def reconcile_interrupted(self, reason: str = "process_restart") -> int:
        """Рестарт процесса: non-terminal job'ы → `interrupted` (авто-resume
        сознательно НЕ делаем — ADR-1022-8 §Decision п.7)."""
        async with self._lock:
            self._ensure_loaded()
            changed = 0
            for job in self._jobs.values():
                if job.get("status") in {"queued", "running", "cancelling"}:
                    job["status"] = "interrupted"
                    job["error_code"] = str(reason or "process_restart")
                    job["updated_at"] = _now()
                    changed += 1
            if changed:
                self._prune()
                await self._persist()
            return changed

    # ── in-process реестр задач ─────────────────────────────────────────
    def register_task(self, job_id: str, task) -> None:
        self._tasks[str(job_id)] = task

    def get_task(self, job_id: str):
        return self._tasks.get(str(job_id))

    def pop_task(self, job_id: str):
        return self._tasks.pop(str(job_id), None)


_store: DossierRebuildJobStore | None = None
_store_reconciled = False


def get_job_store() -> DossierRebuildJobStore:
    """Process-wide job-store. При первом обращении помечает недожитые
    (non-terminal) job'ы как `interrupted` — job-store переживает рестарт,
    живое исполнение нет."""
    global _store, _store_reconciled
    if _store is None:
        _store = DossierRebuildJobStore()
    if not _store_reconciled:
        _store_reconciled = True
        try:
            _store._ensure_loaded()
            changed = 0
            for job in _store._jobs.values():
                if job.get("status") in {"queued", "running", "cancelling"}:
                    job["status"] = "interrupted"
                    job["error_code"] = "process_restart"
                    job["updated_at"] = _now()
                    changed += 1
            if changed:
                _store._prune()
                _store._persist_sync()
        except Exception:
            logger.warning("[dossier_jobs] startup reconcile failed")
    return _store


def reset_job_store() -> None:
    """Сброс singleton (тесты/шатдаун)."""
    global _store, _store_reconciled
    _store = None
    _store_reconciled = False


# ── снапшот производных юзера + rollback ────────────────────────────────────

_USER_DERIVED_SQL = (
    "SELECT * FROM graph_facts WHERE chat_id = ? AND target_user = ? "
    "AND kind = 'fact' "
    "AND status IN ('confirmed', 'chat_meme', 'dossier_portrait') "
    "ORDER BY id ASC"
)


async def _select_user_derived(db, chat_id: int, target_user: str) -> list:
    cursor = await db.db.execute(
        _USER_DERIVED_SQL, (int(chat_id), str(target_user or "")))
    return [dict(r) for r in await cursor.fetchall()]


def _write_jsonl_sync(path: Path, rows) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str))
            fh.write("\n")
        _flush_fsync_and_dir(fh, path.parent)
    os.replace(tmp, path)


def _read_jsonl(path: Path) -> list | None:
    """None — файла нет (snapshot_missing); [] — пустой снапшот."""
    try:
        rows = []
        with open(Path(path), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
    except FileNotFoundError:
        return None


async def create_user_snapshot(db, chat_id: int, target_user: str,
                               path) -> int:
    """Точечный снапшот производных юзера (fsync). Возвращает число строк."""
    rows = await _select_user_derived(db, chat_id, target_user)
    await asyncio.to_thread(_write_jsonl_sync, Path(path), rows)
    return len(rows)


async def archive_user_derived(db, chat_id: int, target_user: str,
                               path) -> tuple:
    """Аудит-архив текущих производных юзера (JSONL) → guard-DELETE.

    Возвращает `(archived, deleted)`."""
    rows = await _select_user_derived(db, chat_id, target_user)
    await asyncio.to_thread(_write_jsonl_sync, Path(path), rows)
    if not rows:
        return 0, 0
    from services.memory_rebuild import delete_generated_facts

    deleted = await delete_generated_facts(db, [r["id"] for r in rows])
    return len(rows), int(deleted)


async def restore_user_snapshot(db, path) -> int:
    """Восстановить строки `graph_facts` из снапшота (`INSERT OR REPLACE` по
    `id`) + FTS (best-effort). `FileNotFoundError` — снапшота нет; пустой
    снапшот → 0. vec — не восстанавливаем (best-effort, embeddings не храним)."""
    rows = await asyncio.to_thread(_read_jsonl, Path(path))
    if rows is None:
        raise FileNotFoundError("snapshot_missing")
    if not rows:
        return 0
    # S10.22-9 (defense-in-depth): имена колонок для INSERT берём из СХЕМЫ
    # `graph_facts` (PRAGMA), а не из JSONL-строки. Вредоносный/битый снапшот
    # не сможет подставить произвольный идентификатор в SQL — невалидные
    # ключи молча отбрасываются.
    cursor = await db.db.execute("PRAGMA table_info(graph_facts)")
    allowed_cols = {str(info[1]) for info in await cursor.fetchall()}
    restored = 0
    for row in rows:
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        cols = [c for c in row.keys() if c in allowed_cols]
        if not cols:
            continue
        collist = ",".join(cols)
        placeholders = ",".join("?" * len(cols))
        values = [row[c] for c in cols]
        await db.db.execute(
            f"INSERT OR REPLACE INTO graph_facts ({collist}) "
            f"VALUES ({placeholders})", values)
        restored += 1
    await db.db.commit()
    for row in rows:
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        try:
            await db.db.execute(
                "DELETE FROM graph_facts_fts WHERE rowid = ?",
                (int(row["id"]),))
            await db.db.execute(
                "INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)",
                (int(row["id"]), str(row.get("fact") or "")))
        except Exception:
            logger.debug("[dossier_jobs] fts restore skipped | id=%s",
                         row.get("id"))
    await db.db.commit()
    return restored


# ── раннер фоновой пересборки ───────────────────────────────────────────────

def _cancel_requested(cancel_cb) -> bool:
    if cancel_cb is None:
        return False
    try:
        return bool(cancel_cb())
    except Exception:
        return False


async def _emit_progress(progress_cb, processed, total, stage) -> None:
    """Fail-open вызов progress_cb (sync/async): прогресс не роняет пересборку."""
    if progress_cb is None:
        return
    try:
        result = progress_cb(processed, total, stage)
        if inspect.isawaitable(result):
            await result
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.debug("[dossier_jobs] progress callback failed (fail-open)")


async def perform_rollback(store: DossierRebuildJobStore, db, job_id: str, *,
                           jobs_dir, chat_id: int, target_name: str,
                           reason: str = "cancelled") -> dict | None:
    """Кооперативная отмена = rollback: архив текущих производных → guard-DELETE
    → восстановление стартового снапшота. Идемпотентно (terminal → no-op).

    Не трогает `persona_dossier_overrides`, `smart_messages`(+FTS/vec),
    `kind='belief'`, `nodes`/`edges`, чужие производные."""
    try:
        return await _perform_rollback_inner(
            store, db, job_id, jobs_dir=jobs_dir, chat_id=chat_id,
            target_name=target_name, reason=reason)
    finally:
        release_chat_lock(chat_id, jobs_dir)


async def _perform_rollback_inner(
        store: DossierRebuildJobStore, db, job_id: str, *, jobs_dir,
        chat_id: int, target_name: str,
        reason: str = "cancelled") -> dict | None:
    job = await store.get(job_id)
    if job is None:
        return None
    rollback = job.get("rollback") or {}
    if (job.get("status") == "cancelled" and rollback.get("done")):
        return job
    await store.update(job_id, status="cancelling", stage="rollback",
                       cancel_requested=True)
    snap_ref = job.get("snapshot_ref") or f"{_SNAPSHOT_PREFIX}{job_id}.jsonl"
    directory = Path(jobs_dir)
    try:
        await archive_user_derived(
            db, chat_id, target_name,
            directory / f"{_CANCELLED_PREFIX}{job_id}.jsonl")
        restored = await restore_user_snapshot(db, directory / snap_ref)
    except FileNotFoundError:
        logger.warning("[dossier_jobs] rollback snapshot missing | job=%s",
                       job_id)
        return await store.update(
            job_id, status="failed", stage="rollback",
            error_code="rollback_failed",
            rollback={"done": False, "restored_facts": 0,
                      "reason": "snapshot_missing"},
            finished_at=_now())
    except Exception:
        logger.warning("[dossier_jobs] rollback failed | job=%s", job_id,
                       exc_info=True)
        return await store.update(
            job_id, status="failed", stage="rollback",
            error_code="rollback_failed",
            rollback={"done": False, "restored_facts": 0,
                      "reason": "rollback_failed"},
            finished_at=_now())
    logger.info("[dossier_jobs] rollback done | job=%s | restored=%s",
                job_id, restored)
    return await store.update(
        job_id, status="cancelled", stage="rollback", finished_at=_now(),
        rollback={"done": True, "restored_facts": int(restored), "reason": ""})


async def run_dossier_rebuild(*, store: DossierRebuildJobStore, db, worker,
                              job_id: str, chat_id: int, user_id: int,
                              target_name: str, window_hours: int,
                              chunk_size: int, jobs_dir, archive_dir,
                              lock=None) -> None:
    """Фоновый раннер одного job'а (HTTP не блокируется)."""
    state = {"last_write": 0.0, "stage": None}

    async def _progress(processed, cb_total, stage):
        try:
            now = time.monotonic()
            if (stage == state["stage"] and now - state["last_write"] < 1.0):
                return
            state["last_write"] = now
            state["stage"] = stage
            fields = {"processed": max(0, int(processed or 0)),
                      "stage": stage or "extract"}
            if cb_total and int(cb_total) > int((store.get_sync(job_id)
                                                or {}).get("total") or 0):
                fields["total"] = int(cb_total)
            await store.update(job_id, **fields)
        except Exception:
            pass                          # fail-open: прогресс не роняет job

    def _cancel_cb() -> bool:
        current = store.get_sync(job_id)
        return bool(current and current.get("cancel_requested"))

    try:
        await store.update(job_id, status="running", started_at=_now(),
                           stage="snapshot")
        if _cancel_requested(_cancel_cb):
            raise asyncio.CancelledError()
        snapshot_path = Path(jobs_dir) / f"{_SNAPSHOT_PREFIX}{job_id}.jsonl"
        try:
            await create_user_snapshot(db, chat_id, target_name, snapshot_path)
        except Exception:
            logger.warning("[dossier_jobs] snapshot failed — job aborted | "
                           "job=%s", job_id, exc_info=True)
            await store.update(job_id, status="failed",
                               error_code="snapshot_failed", stage="snapshot",
                               finished_at=_now())
            return
        await store.update(job_id, stage="cleanup")
        if _cancel_requested(_cancel_cb):
            raise asyncio.CancelledError()
        cleaned = 0
        try:
            from services.memory_rebuild import cleanup_confirmed_dossier_facts

            report = await cleanup_confirmed_dossier_facts(
                db, chat_ids=[chat_id], target_user=target_name, dry_run=False,
                backup_dir=archive_dir)
            cleaned = int(report.get("cleaned") or 0)
        except Exception:
            logger.warning("[dossier_jobs] confirmed-cleanup failed — "
                           "продолжаем | job=%s", job_id, exc_info=True)
        await store.update(job_id, cleaned=cleaned, stage="extract")
        if _cancel_requested(_cancel_cb):
            raise asyncio.CancelledError()
        written = int(await worker.rebuild_dossier_for_user(
            chat_id, target_user=target_name, window_hours=window_hours,
            chunk_size=chunk_size, progress_cb=_progress,
            cancel_cb=_cancel_cb) or 0)
        await store.update(job_id, rebuilt=written, stage="finalize")
        current = store.get_sync(job_id) or {}
        # Гонка отмены: cancel мог прийти между последним чанком и finalize.
        # Перед 'done' перепроверяем флаг — иначе отмена «залипнет» и снапшот
        # не откатится (finalize→done безусловен был бы багом).
        if _cancel_requested(_cancel_cb):
            raise asyncio.CancelledError()
        # S10.22-2: зеркалим инвариант F1 `rebuild_empty` — если confirmed-факты
        # участника уже удалены (`cleaned > 0`), а движок не пересобрал ничего
        # (`written == 0`), это НЕ молчаливый успех: job → `failed`/`rebuild_empty`.
        # Снапшот цел, поэтому UI (критерий `cleaned > 0`) даёт ручной откат.
        if cleaned > 0 and written == 0:
            logger.warning(
                "[dossier_jobs] rebuild empty after cleanup | job=%s "
                "| cleaned=%d", job_id, cleaned)
            await store.update(job_id, status="failed", stage="finalize",
                               error_code="rebuild_empty",
                               processed=int(current.get("total") or 0),
                               finished_at=_now())
            return
        await store.update(job_id, status="done", stage="finalize",
                           processed=int(current.get("total") or 0),
                           finished_at=_now())
    except asyncio.CancelledError:
        await perform_rollback(store, db, job_id, jobs_dir=jobs_dir,
                               chat_id=chat_id, target_name=target_name,
                               reason="cancelled")
    except Exception:
        logger.warning("[dossier_jobs] rebuild failed | job=%s", job_id,
                       exc_info=True)
        await store.update(job_id, status="failed",
                           error_code="rebuild_failed", finished_at=_now())
    finally:
        store.pop_task(job_id)
        if lock is not None:
            lock.release()
        else:
            release_chat_lock(chat_id, jobs_dir)
