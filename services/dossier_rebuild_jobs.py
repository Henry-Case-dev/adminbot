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
# mca-04b (ADR-1027-9 D3): `paused` — АКТИВНЫЙ статус (неполный диапазон
# остаётся в очереди: budget exhaustion ≠ завершение, A89; retention не
# вытесняет); resume — повторный старт того же job'а с checkpoint.
_ACTIVE_STATUSES = frozenset(
    {"queued", "running", "cancelling", "paused"})
_TERMINAL_STATUSES = frozenset(
    {"done", "failed", "cancelled", "completed"})
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
        # ── mca-04b (ADR-1027-9 D1–D4): контракт full rebuild ──────────────
        "mode": "legacy",              # legacy | full
        "scope_kind": "range",         # full | range | incremental
        "range_from_ts": None,
        "range_to_ts": None,
        "snapshot_boundary_ts": None,
        "snapshot_boundary_id": None,
        "cursor_ts": None,             # keyset-cursor (после фиксации batch)
        "cursor_id": None,
        "extractor_version": None,
        "kernel_version": None,
        "attempt": 0,
        "reason_code": None,
        "counters": {},                # раздельные счётчики (разные единицы)
        "coverage": {},                # покрытие по годам/месяцам
        "generation_id": None,         # активированное поколение досье
    }


def job_view(job: dict) -> dict:
    """R17-safe представление job'а для UI: числа/коды/`snapshot_ref`-basename.
    Текстов фактов, `target_name` и полных путей нет."""
    if not isinstance(job, dict):
        return {}
    total = int(job.get("total") or 0)
    processed = max(0, int(job.get("processed") or 0))
    status = str(job.get("status") or "")
    if total > 0:
        percent = int(round(100.0 * min(processed, total) / total))
    else:
        percent = 100 if status in ("done", "completed") else 0
    rollback = job.get("rollback") or {}
    snap = str(job.get("snapshot_ref") or "")
    view = {
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
    # mca-04b (аддитивно, R17-safe — числа/коды): контракт full rebuild.
    # `processed` — фактическое значение (НЕ подменяется total; на paused
    # percent < 100 — честный прогресс частичного прохода).
    view.update({
        "mode": str(job.get("mode") or "legacy"),
        "scope_kind": job.get("scope_kind"),
        "attempt": int(job.get("attempt") or 0),
        "reason_code": job.get("reason_code"),
        "cursor_ts": job.get("cursor_ts"),
        "cursor_id": job.get("cursor_id"),
        "snapshot_boundary_ts": job.get("snapshot_boundary_ts"),
        "extractor_version": job.get("extractor_version"),
        "generation_id": job.get("generation_id"),
    })
    counters = job.get("counters")
    if isinstance(counters, dict):
        view["counters"] = {k: v for k, v in counters.items()
                            if isinstance(v, (int, float))}
    coverage = job.get("coverage")
    if isinstance(coverage, dict) and coverage:
        view["coverage"] = coverage
    return view


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
        сознательно НЕ делаем — ADR-1022-8 §Decision п.7).

        mca-04b: `paused` тоже → `interrupted` (различимое состояние §8.3.3);
        cursor/checkpoint сохраняются в job — повторный старт продолжает с
        места фиксации (без дублей — дедуп записей)."""
        async with self._lock:
            self._ensure_loaded()
            changed = 0
            for job in self._jobs.values():
                if job.get("status") in {"queued", "running", "cancelling",
                                         "paused"}:
                    was_paused = job.get("status") == "paused"
                    job["status"] = "interrupted"
                    job["error_code"] = str(reason or "process_restart")
                    job["reason_code"] = "dossier_interrupted"
                    if was_paused:
                        # Причина паузы сохраняется в error_code-хвосте
                        # (различимые состояния; cursor не затирается).
                        job["reason_code"] = str(
                            job.get("reason_code") or "dossier_interrupted")
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
                if job.get("status") in {"queued", "running", "cancelling",
                                         "paused"}:
                    job["status"] = "interrupted"
                    job["error_code"] = "process_restart"
                    job["reason_code"] = "dossier_interrupted"
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

    # B-MCA01-1 (D3): INSERT-фаза — через общий write-механизм.
    async def _insert_body(conn):
        n = 0
        for row in rows:
            if not isinstance(row, dict) or row.get("id") is None:
                continue
            cols = [c for c in row.keys() if c in allowed_cols]
            if not cols:
                continue
            collist = ",".join(cols)
            placeholders = ",".join("?" * len(cols))
            await conn.execute(
                f"INSERT OR REPLACE INTO graph_facts ({collist}) "
                f"VALUES ({placeholders})",
                [row[c] for c in cols])
            n += 1
        return n

    restored = int(await db.write_transaction(
        _insert_body, op_name="dossier_restore_facts") or 0)
    # B-MCA01-1 (D3): FTS-фаза (best-effort) — под тем же single-writer.
    async with db.serialized():
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
    """Фоновый раннер одного job'а (HTTP не блокируется).

    mca-04b (ADR-1027-9 D3/D13): dispatch по мастер-гейту
    `MCA_DOSSIER_REBUILD_ENABLED`:
      * OFF → `_run_legacy` — ровно прежний путь (паритет baseline,
        включая cleanup и безусловный `done`);
      * ON → `_run_full_contract` — keyset full rebuild, staging/активация,
        различимые состояния, честная финализация (`processed` не
        подменяется `total`; budget exhaustion → `paused`)."""
    try:
        from services import mca_gates
        full = mca_gates.dossier_rebuild_enabled()
    except Exception:
        full = False
    if full and hasattr(worker, "rebuild_dossier_full"):
        await _run_full_contract(
            store=store, db=db, worker=worker, job_id=job_id,
            chat_id=chat_id, user_id=user_id, target_name=target_name,
            window_hours=window_hours, chunk_size=chunk_size,
            jobs_dir=jobs_dir, archive_dir=archive_dir, lock=lock)
        return
    await _run_legacy(store=store, db=db, worker=worker, job_id=job_id,
                      chat_id=chat_id, user_id=user_id,
                      target_name=target_name, window_hours=window_hours,
                      chunk_size=chunk_size, jobs_dir=jobs_dir,
                      archive_dir=archive_dir, lock=lock)


def _emit_rebuild_event(outcome: str, *, chat_id: int, job_id: str,
                        reason_code: str | None = None, **extra) -> None:
    """Событие контура пересборки по контракту MCA-13 (start+терминальный
    outcome, reason_code §17.2). Fail-open, никогда не бросает (R17: только
    id/коды/числа). Span-поля mca-17a (`pipeline_run_id`/`span_id`/
    `attempt_id`/`pipeline_type`/`checkpoint_ref`) проходят через
    `ALLOWED_FIELDS` контракта (extra отдаёт вызывающий через `mt.span_fields`)."""
    try:
        from services import mca_events
        fields = {"component": "dossier.rebuild", "stage": "extract",
                  "job_id": str(job_id), "chat_id": int(chat_id)}
        if reason_code:
            fields["reason_code"] = reason_code
        span_allowed = ("pipeline_run_id", "span_id", "parent_span_id",
                        "attempt_id", "pipeline_type", "pipeline_version",
                        "checkpoint_ref", "status")
        for key, value in extra.items():
            if value is None:
                continue
            if key in span_allowed:
                fields[key] = str(value)
            elif key in ("attempt", "processed", "total", "duration_ms"):
                fields[key] = int(value)
        mca_events.emit_mca_event("dossier_rebuild", outcome=outcome,
                                  **fields)
    except Exception:
        logger.debug("[dossier_jobs] event emit failed (fail-open)",
                     exc_info=True)


async def _run_full_contract(*, store: DossierRebuildJobStore, db, worker,
                             job_id: str, chat_id: int, user_id: int,
                             target_name: str, window_hours: int,
                             chunk_size: int, jobs_dir, archive_dir,
                             lock=None) -> None:
    """Новый контракт full rebuild (mca-04b, ADR-1027-9 D1–D8).

    * снимок производных (backup/rollback — прежний механизм сохранён);
    * БЕЗ auto-cleanup старых confirmed (D7: новые правила не очищают);
    * keyset-проход движка `rebuild_dossier_full` (≤500/batch, backlog на
      диске, checkpoint после фиксации);
    * staging/атомарная активация (gate `MCA_DOSSIER_STAGING_ACTIVATION_ENABLED`)
      либо прямая запись (паритет baseline-записи);
    * честная финализация: `completed` — только весь диапазон; budget/
      модель/отмена/рестарт → `paused`/`interrupted`/`cancelled` с курсором
      (неполные диапазоны остаются в очереди; `processed` — фактический);
    * каскадный пересчёт зависимых по очереди после активации (D9)."""
    from services import mca_gates
    from services import mca_trace as mt
    from services.provenance import EXTRACTOR_VERSION
    started_mono = time.monotonic()
    state = {"last_write": 0.0, "stage": None}
    current = store.get_sync(job_id) or {}
    attempt = int(current.get("attempt") or 0) + 1
    resume_cursor = None
    if current.get("cursor_ts") is not None and current.get("cursor_id") \
            is not None:
        resume_cursor = (int(current["cursor_ts"]), int(current["cursor_id"]))
    staging_on = mca_gates.dossier_staging_activation_enabled()
    # H-1 (review round 1): незавершённое поколение прошлой паузы — кандидаты
    # прерванного прогона уже в staging; при resume они сеются в движок
    # (Layer B видит оба сегмента) и до-активируются тем же поколением.
    pending_generation_id = current.get("generation_id") or None
    resume_candidates: list | None = None
    if staging_on and pending_generation_id and resume_cursor:
        try:
            gen = await db.get_dossier_generation(pending_generation_id)
            if gen and str(gen.get("state") or "") == "building":
                staged_items = await db.list_dossier_staging_items(
                    pending_generation_id)
                resume_candidates = _staged_items_to_candidates(
                    staged_items, target_name=target_name)
        except Exception:
            logger.warning("[dossier_jobs] resume seeding from staging "
                           "failed — продолжаем с курсора | job=%s",
                           job_id, exc_info=True)
            resume_candidates = None

    async def _progress(processed, cb_total, stage):
        try:
            now = time.monotonic()
            if stage == state["stage"] and now - state["last_write"] < 1.0:
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

    def _checkpoint(cursor_ts, cursor_id, counters, coverage):
        """Checkpoint ПОСЛЕ фиксации batch (дисковый артефакт + факты):
        курсор/счётчики/покрытие durable в job-store (short write) + run
        `checkpoint_ref`/heartbeat (mca-17a correlation, T-3911)."""
        async def _inner():
            await store.update(
                job_id, cursor_ts=int(cursor_ts), cursor_id=int(cursor_id),
                counters={k: v for k, v in (counters or {}).items()
                          if isinstance(v, (int, float))},
                coverage=dict(coverage or {}))
            if run_id:
                await mt.touch_run(db, run_id, checkpoint_ref=(
                    f"job:{job_id}:{int(cursor_ts)}:{int(cursor_id)}"))
        return _inner()

    # mca-17a: durable root-run (correlation pipeline_run_id/span/attempt
    # восстанавливается при resume — новый attempt = новый attempt_id).
    run_id = None
    try:
        run_id = await mt.start_run(
            db, pipeline_type="dossier.rebuild", version="1",
            root_job_id=job_id, job_id=job_id,
            attempt_id=f"{job_id}:{attempt}")
    except Exception:
        run_id = None

    def _span():
        fields = mt.span_fields(
            run_id=run_id, pipeline_type="dossier.rebuild",
            pipeline_version="1", span_id=run_id, job_id=job_id,
            attempt_id=f"{job_id}:{attempt}", status="running")
        fields.pop("job_id", None)     # job_id передаётся явно (без дублей)
        return fields

    try:
        await store.update(job_id, status="running", started_at=_now(),
                           stage="snapshot", attempt=attempt,
                           mode="full", reason_code=None)
        _emit_rebuild_event("start", chat_id=chat_id, job_id=job_id,
                            attempt=attempt, **_span())
        if _cancel_requested(_cancel_cb):
            raise asyncio.CancelledError()
        # 1. Снимок производных (backup/rollback сохранён — REUSE).
        snapshot_path = Path(jobs_dir) / f"{_SNAPSHOT_PREFIX}{job_id}.jsonl"
        try:
            await create_user_snapshot(db, chat_id, target_name, snapshot_path)
        except Exception:
            logger.warning("[dossier_jobs] snapshot failed — job aborted | "
                           "job=%s", job_id, exc_info=True)
            await store.update(job_id, status="failed",
                               error_code="snapshot_failed", stage="snapshot",
                               finished_at=_now())
            _emit_rebuild_event("failed", chat_id=chat_id, job_id=job_id,
                                reason_code="snapshot_failed", **_span())
            await mt.finish_run(db, run_id, outcome=mt.RUN_FAILED,
                                reason_code="snapshot_failed")
            return
        # 2. Keyset-проход (БЕЗ confirmed-cleanup: D7 — старые confirmed
        # не очищаются автоматически; реклассификация — в staging).
        await store.update(job_id, stage="extract")
        backlog_dir = Path(jobs_dir) / "backlog" / job_id
        engine_kwargs = {}
        if resume_candidates:
            engine_kwargs["resume_candidates"] = resume_candidates
        report = await worker.rebuild_dossier_full(
            chat_id, target_user=target_name, window_hours=int(window_hours
                                                               or 0),
            chunk_size=int(chunk_size or 0), progress_cb=_progress,
            cancel_cb=_cancel_cb, checkpoint_cb=_checkpoint,
            backlog_dir=backlog_dir,
            write_mode="collect" if staging_on else "direct",
            resume_cursor=resume_cursor, **engine_kwargs)
        status = str((report or {}).get("status") or "failed")
        processed = int((report or {}).get("processed") or 0)
        counters = dict((report or {}).get("counters") or {})
        coverage = dict((report or {}).get("coverage") or {})
        boundary = (report or {}).get("boundary") or (None, None)
        base_fields = {
            "processed": processed,
            # total — авторитетный полный диапазон движка (не оценка API);
            # прогресс считается от него (A87/честный percent).
            "total": int((report or {}).get("total") or 0),
            "counters": {k: v for k, v in counters.items()
                         if isinstance(v, (int, float))},
            "coverage": coverage,
            "extractor_version": EXTRACTOR_VERSION,
            "kernel_version": "mca-04b/v1",
            "range_from_ts": (None if int(window_hours or 0) <= 0
                              else int(time.time()) - int(window_hours)
                              * 3600),
            "range_to_ts": int(time.time()),
        }
        if boundary and boundary[0] is not None:
            base_fields["snapshot_boundary_ts"] = int(boundary[0])
            base_fields["snapshot_boundary_id"] = int(boundary[1] or 0)
        # 3. Маппинг состояния движка → различимые batch-состояния (D3).
        # H-2 (review round 1): model_unavailable/failed — честные исходы
        # движка; никогда не маппятся в completed (инвариант 2).
        report_stage = str((report or {}).get("failed_stage") or "extract")
        if status in ("budget_exhausted", "model_unavailable"):
            # Пауза (retryable): неполный диапазон остаётся в очереди.
            # H-1: кандидаты прерванного прогона персистятся в staging
            # ДО паузы — resume не теряет сегмент до курсора.
            reason = str((report or {}).get("reason_code")
                         or ("dossier_paused_budget"
                             if status == "budget_exhausted"
                             else "model_unavailable"))
            pending_gen = None
            if staging_on:
                pending_gen = await _persist_pending_candidates(
                    db, job_id=job_id, chat_id=chat_id,
                    target_name=target_name, report=report,
                    jobs_dir=jobs_dir, window_hours=window_hours,
                    existing_generation_id=pending_generation_id)
                if pending_gen is None and pending_generation_id:
                    pending_gen = pending_generation_id
                if pending_gen is None and (
                        report or {}).get("candidates"):
                    # Кандидаты есть, а персистентация не удалась: пауза
                    # молча теряла бы сегмент (H-1) — честный failed.
                    await store.update(
                        job_id, status="failed", stage=report_stage,
                        error_code="pending_staging_failed",
                        reason_code="dossier_pending_staging_failed",
                        finished_at=_now(), **base_fields)
                    _emit_rebuild_event("failed", chat_id=chat_id,
                                        job_id=job_id,
                                        reason_code=(
                                            "dossier_pending_staging_failed"),
                                        processed=processed, **_span())
                    await mt.finish_run(
                        db, run_id, outcome=mt.RUN_FAILED,
                        reason_code="dossier_pending_staging_failed")
                    return
            cursor = (report or {}).get("cursor") or (None, None)
            await store.update(
                job_id, status="paused", stage=report_stage,
                reason_code=reason,
                error_code=None, cursor_ts=cursor[0], cursor_id=cursor[1],
                finished_at=None,
                **({"generation_id": pending_gen} if pending_gen else {}),
                **base_fields)
            _emit_rebuild_event("skipped", chat_id=chat_id, job_id=job_id,
                                reason_code=reason,
                                processed=processed, **_span())
            await mt.finish_run(db, run_id, outcome=mt.RUN_PARTIAL,
                                reason_code=reason,
                                checkpoint_ref=(f"job:{job_id}:"
                                                f"{cursor[0]}:{cursor[1]}"))
            return
        if status != "completed":
            # Любой иной не-completed статус движка — честный failed
            # (reason_code от движка; parse_error — fallback).
            reason = str((report or {}).get("reason_code") or "parse_error")
            await store.update(job_id, status="failed", stage=report_stage,
                               error_code="rebuild_failed",
                               reason_code=reason,
                               finished_at=_now(), **base_fields)
            _emit_rebuild_event("failed", chat_id=chat_id, job_id=job_id,
                                reason_code=reason,
                                processed=processed, **_span())
            await mt.finish_run(db, run_id, outcome=mt.RUN_FAILED,
                                reason_code=reason)
            return
        # 4. Финализация: staging/атомарная активация (SC-12) либо прямая
        # запись (уже выполнена движком).
        await store.update(job_id, rebuilt=int((report or {}).get("written")
                                               or 0), stage="activate",
                           **base_fields)
        generation_id = None
        if staging_on:
            generation_id = await _stage_and_activate(
                db, chat_id=chat_id, target_name=target_name,
                report=report, jobs_dir=jobs_dir, window_hours=window_hours,
                existing_generation_id=pending_generation_id)
            if generation_id is None:
                # Staging не удался: старые факты НЕ тронуты (staging-only),
                # job → failed без уничтожения (SC-12).
                await store.update(
                    job_id, status="failed", stage="activate",
                    error_code="activation_failed",
                    reason_code="dossier_partial_range",
                    finished_at=_now())
                _emit_rebuild_event("failed", chat_id=chat_id,
                                    job_id=job_id,
                                    reason_code="dossier_partial_range",
                                    **_span())
                await mt.finish_run(db, run_id, outcome=mt.RUN_FAILED,
                                    reason_code="dossier_partial_range")
                return
        # Гонка отмены: cancel между последним batch и finalize → не
        # `completed` (инвариант 2).
        if _cancel_requested(_cancel_cb):
            raise asyncio.CancelledError()
        await store.update(job_id, status="completed", stage="finalize",
                           processed=processed, finished_at=_now(),
                           reason_code=None,
                           generation_id=generation_id)
        _emit_rebuild_event("success", chat_id=chat_id, job_id=job_id,
                            processed=processed, **_span())
        await mt.finish_run(db, run_id, outcome=mt.RUN_SUCCEEDED,
                            reason_code=None)
        # 5. Каскадный пересчёт зависимых по очереди (D9) — фон, не блокирует.
        if generation_id is not None:
            await _schedule_cascade(db, chat_id=chat_id, job_id=job_id,
                                    generation_id=generation_id,
                                    worker=worker)
    except asyncio.CancelledError:
        # Отмена (кооперативная): staging-версия не активирована → старые
        # факты не тронуты; job → cancelled (или interrupted при рестарте).
        current = store.get_sync(job_id) or {}
        if current.get("cancel_requested"):
            await store.update(job_id, status="cancelled", stage="finalize",
                               reason_code="cancelled",
                               error_code=None, finished_at=_now())
            _emit_rebuild_event("cancelled", chat_id=chat_id, job_id=job_id,
                                reason_code="cancelled", **_span())
            await mt.finish_run(db, run_id, outcome=mt.RUN_CANCELLED,
                                reason_code="cancelled")
        else:
            await store.update(job_id, status="interrupted", stage="finalize",
                               reason_code="dossier_interrupted",
                               finished_at=_now())
            _emit_rebuild_event("interrupted", chat_id=chat_id,
                                job_id=job_id,
                                reason_code="dossier_interrupted", **_span())
            await mt.finish_run(db, run_id, outcome=mt.RUN_INTERRUPTED,
                                reason_code="dossier_interrupted")
    except Exception:
        logger.warning("[dossier_jobs] rebuild failed | job=%s", job_id,
                       exc_info=True)
        await store.update(job_id, status="failed",
                           error_code="rebuild_failed",
                           reason_code="parse_error", finished_at=_now())
        _emit_rebuild_event("failed", chat_id=chat_id, job_id=job_id,
                            reason_code="parse_error", **_span())
        await mt.finish_run(db, run_id, outcome=mt.RUN_FAILED,
                            reason_code="parse_error")
    finally:
        store.pop_task(job_id)
        if lock is not None:
            lock.release()
        else:
            release_chat_lock(chat_id, jobs_dir)


def _staging_payload(item: dict) -> dict:
    """Payload staged-элемента (fail-open на битом JSON)."""
    try:
        payload = json.loads((item or {}).get("payload_json") or "{}")
    except (TypeError, ValueError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _staging_dedup_key(item: dict) -> tuple:
    """Ключ дедупа staged-элемента: (kind, text, target)."""
    payload = _staging_payload(item)
    return (str((item or {}).get("item_kind") or ""),
            str(payload.get("text") or "").strip().casefold(),
            str(payload.get("target_user") or "").strip().casefold())


def _staged_items_to_candidates(items, *, target_name: str = "") -> list:
    """H-1 (review round 1): staged-элементы building-поколения → кандидаты
    для посева в движок при resume (`resume_candidates`). Layer B видит
    ОБА сегмента (до и после курсора) — портрет полного диапазона;
    повторная активация не удваивает элементы (дедуп по ключу +
    `_restored`-маркер). Портреты не сеются — синтез повторяется."""
    out: list = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("item_kind") or "")
        if kind not in ("person_fact", "meme"):
            continue
        payload = _staging_payload(item)
        text = str(payload.get("text") or "").strip()
        if not text:
            continue
        target = str(payload.get("target_user") or target_name
                     or "").strip()
        src = item.get("source_ref_id")
        try:
            src_ids = [int(src)] if src else []
        except (TypeError, ValueError):
            src_ids = []
        out.append({
            "text": text,
            "target": target,
            "meme": kind == "meme",
            "kind": str(item.get("classification") or kind),
            "_source_ref_ids": src_ids,
            "_evidence_valid": bool(src_ids),
            "_author_name": (target
                             if str(payload.get("attribution_method")
                                    or "") == "self_report" else None),
            "_restored": True,
        })
    return out


async def _persist_pending_candidates(
        db, *, job_id: str, chat_id: int, target_name: str, report: dict,
        jobs_dir, window_hours: int,
        existing_generation_id: str | None = None) -> str | None:
    """H-1 (review round 1): кандидаты прерванного прогона — в staging ДО
    паузы (SC-05/A89: resume без потерь). Создаёт (однократно) или
    переиспользует building-поколение job'а; дедуп исключает удвоение при
    повторных паузах. Возврат `generation_id` (building) либо None —
    persisted нечего/не удалось (вызывающий решает: paused допустим только
    если терять нечего)."""
    from services.provenance import EXTRACTOR_VERSION
    candidates = [c for c in ((report or {}).get("candidates") or [])
                  if isinstance(c, dict) and not c.get("_restored")]
    if not candidates and not existing_generation_id:
        return None
    subject_ref_id = await _resolve_dossier_subject_ref(db, chat_id,
                                                        target_name)
    generation_id = None
    if existing_generation_id:
        try:
            gen = await db.get_dossier_generation(existing_generation_id)
        except Exception:
            gen = None
        if gen and str(gen.get("state") or "") == "building":
            generation_id = existing_generation_id
    existing_keys: set = set()
    if generation_id:
        existing_keys = {_staging_dedup_key(i) for i in
                         await db.list_dossier_staging_items(generation_id)}
    if not generation_id:
        boundary = (report or {}).get("boundary") or (None, None)
        counters = dict((report or {}).get("counters") or {})
        counters_json = json.dumps(
            {k: v for k, v in counters.items()
             if isinstance(v, (int, float))}, ensure_ascii=False)
        generation_id = await db.create_dossier_generation(
            chat_id, int(subject_ref_id or 0), scope_kind="range",
            range_from_ts=(None if int(window_hours or 0) <= 0
                           else int(time.time()) - int(window_hours) * 3600),
            range_to_ts=int(time.time()),
            snapshot_boundary_ts=boundary[0], snapshot_boundary_id=boundary[1],
            extractor_version=EXTRACTOR_VERSION, kernel_version="mca-04b/v1",
            counters_json=counters_json)
        if not generation_id:
            return None
    staged = 0
    for cand in candidates:
        kind = "meme" if cand.get("meme") else "person_fact"
        text = str(cand.get("text") or "").strip()
        target = str(cand.get("target") or "").strip()
        if (kind, text.casefold(), target.casefold()) in existing_keys:
            continue
        payload = {
            "text": text,
            "target_user": target or target_name,
            "attribution_method": (
                "self_report" if cand.get("_author_name")
                and str(cand.get("_author_name")).strip().casefold()
                == target.casefold() else "third_party"),
        }
        if not payload["text"]:
            continue
        item_id = await db.insert_dossier_staging_item(
            generation_id, kind, subject_ref_id=subject_ref_id,
            source_ref_id=(int(cand["_source_ref_ids"][0])
                           if cand.get("_source_ref_ids") else None),
            classification=str(cand.get("kind") or kind), payload=payload,
            verification="tentative", extractor_version=EXTRACTOR_VERSION)
        if item_id:
            existing_keys.add((kind, text.casefold(), target.casefold()))
            staged += 1
    # Счётчики поколения — актуальные на момент паузы (R17-safe числа).
    counters = dict((report or {}).get("counters") or {})
    if counters:
        await db.set_dossier_generation_state(
            generation_id, "building",
            counters_json=json.dumps(
                {k: v for k, v in counters.items()
                 if isinstance(v, (int, float))}, ensure_ascii=False))
    logger.info("[dossier_jobs] pending candidates staged before pause | "
                "chat=%s | job=%s | gen=%s | staged=%s", chat_id, job_id,
                generation_id, staged)
    return generation_id


async def _resolve_dossier_subject_ref(db, chat_id: int,
                                       target_name: str) -> int | None:
    """Субъект — устойчивый subject_ref_id (§8.3.2); fail-open → None."""
    try:
        from services import provenance
        ref = await provenance.resolve_subject_ref(db, chat_id, target_name)
        return await provenance.resolve_source_ref(db, ref)
    except Exception:
        return None


async def _stage_and_activate(db, *, chat_id: int, target_name: str,
                              report: dict, jobs_dir, window_hours: int,
                              existing_generation_id: str | None = None
                              ) -> str | None:
    """Staging → атомарная активация поколения (mca-04b, ADR-1027-9 D8).

    Staged-элементы: личные факты/мемы/портрет (R17-safe payload); активация
    — одна короткая транзакция под single-writer; прежняя версия остаётся
    (`superseded`). Rollback — REUSE `memory_backup` (backup_ref).
    H-1 (review round 1): `existing_generation_id` (building-поколение
    прошлой паузы) переиспользуется — кандидаты обоих сегментов (до и после
    курсора) активируются ОДНИМ поколением; дедуп по (kind, text, target)
    исключает удвоение засеянных кандидатов."""
    from services import mca_gates
    from services.provenance import EXTRACTOR_VERSION
    # backup ПЕРЕД активацией (REUSE memory_backup; in-memory → None).
    backup_ref = None
    try:
        from services.memory_backup import migration_backup
        path = await migration_backup(db, backup_dir=str(archive_dir))
        backup_ref = str(path) if path else None
    except Exception:
        logger.debug("[dossier_jobs] activation backup unavailable "
                     "(fail-open)", exc_info=True)
    # Субъект — устойчивый subject_ref_id (§8.3.2).
    subject_ref_id = await _resolve_dossier_subject_ref(db, chat_id,
                                                        target_name)
    # H-1: переиспользование building-поколения прошлой паузы.
    generation_id = None
    reused = False
    if existing_generation_id:
        try:
            gen = await db.get_dossier_generation(existing_generation_id)
        except Exception:
            gen = None
        if gen and str(gen.get("state") or "") == "building":
            generation_id = existing_generation_id
            reused = True
    existing_keys: set = set()
    if reused:
        existing_keys = {_staging_dedup_key(i) for i in
                         await db.list_dossier_staging_items(generation_id)}
    candidates = [c for c in ((report or {}).get("candidates") or [])
                  if isinstance(c, dict) and not c.get("_restored")]
    synthesized = (report or {}).get("synthesized") or {}
    counters = dict((report or {}).get("counters") or {})
    counters_json = json.dumps(
        {k: v for k, v in counters.items() if isinstance(v, (int, float))},
        ensure_ascii=False)
    if not generation_id:
        generation_id = await db.create_dossier_generation(
            chat_id, int(subject_ref_id or 0), scope_kind="range",
            range_from_ts=(report or {}).get("range_from_ts"),
            range_to_ts=(report or {}).get("range_to_ts"),
            snapshot_boundary_ts=((report or {}).get("boundary") or (None,
                                                                     None))[0],
            snapshot_boundary_id=((report or {}).get("boundary")
                                  or (None, None))[1],
            extractor_version=EXTRACTOR_VERSION, kernel_version="mca-04b/v1",
            counters_json=counters_json, backup_ref=backup_ref)
        if not generation_id:
            return None
    staged = 0
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        text = str(cand.get("text") or "").strip()
        if not text:
            continue
        target = str(cand.get("target") or "").strip()
        kind = "meme" if cand.get("meme") else "person_fact"
        if (kind, text.casefold(), target.casefold()) in existing_keys:
            continue                  # уже staged (H-1: seeded/прошлая пауза)
        payload = {
            "text": text,
            "target_user": target or target_name,
            "attribution_method": (
                "self_report" if cand.get("_author_name")
                and str(cand.get("_author_name")).strip().casefold()
                == target.casefold() else "third_party"),
        }
        item_id = await db.insert_dossier_staging_item(
            generation_id, kind, subject_ref_id=subject_ref_id,
            source_ref_id=(int(cand["_source_ref_ids"][0])
                           if cand.get("_source_ref_ids") else None),
            classification=str(cand.get("kind") or kind), payload=payload,
            verification="tentative", extractor_version=EXTRACTOR_VERSION)
        if item_id:
            existing_keys.add((kind, text.casefold(), target.casefold()))
            staged += 1
    # Портрет — синтез Layer B (уже выполнен движком; candidates пуст).
    for portrait in synthesized.get("portraits") or []:
        payload = {
            "target_user": str((portrait or {}).get("target") or target_name),
            "portrait": str((portrait or {}).get("portrait") or ""),
            "patterns": list((portrait or {}).get("patterns") or []),
            "themes": list((portrait or {}).get("themes") or []),
        }
        item_id = await db.insert_dossier_staging_item(
            generation_id, "portrait", subject_ref_id=subject_ref_id,
            payload=payload, verification="tentative",
            extractor_version=EXTRACTOR_VERSION)
        if item_id:
            staged += 1
    for meme in synthesized.get("memes") or []:
        payload = {
            "text": str((meme or {}).get("text") or ""),
            "target_user": str((meme or {}).get("target") or target_name),
        }
        if not payload["text"]:
            continue
        item_id = await db.insert_dossier_staging_item(
            generation_id, "meme", subject_ref_id=subject_ref_id,
            payload=payload, verification="tentative",
            extractor_version=EXTRACTOR_VERSION)
        if item_id:
            staged += 1
    if reused:
        # H-1: финальные счётчики прохода + свежий backup_ref на
        # переиспользованном поколении (создано на паузе с частичными).
        await db.set_dossier_generation_state(
            generation_id, "building", counters_json=counters_json,
            backup_ref=backup_ref)
    # Атомарная активация (single-writer, короткая транзакция).
    result = await db.activate_dossier_generation(generation_id)
    state = str((result or {}).get("state") or "unknown")
    if state != "active":
        await db.set_dossier_generation_state(
            generation_id, "failed",
            staging_ref=f"backlog/{Path(str(jobs_dir)).name}")
        return None
    if (result or {}).get("superseded_generation_id"):
        _emit_rebuild_event("success", chat_id=chat_id, job_id="activation",
                            reason_code="dossier_generation_superseded")
    logger.info("[dossier_jobs] generation activated | chat=%s | gen=%s | "
                "staged=%s applied=%s", chat_id, generation_id, staged,
                (result or {}).get("applied"))
    return generation_id


async def _schedule_cascade(db, *, chat_id: int, job_id: str,
                            generation_id: str, worker) -> None:
    """Каскадный пересчёт зависимых ПО ОЧЕРЕДИ (D9) через существующие
    контуры: (1) портреты/мемы (Layer B recount), (2) RAG/vec-поколение
    (проверка fingerprint; перестройка — отдельный resumable job),
    (3) убеждения (сон `DreamWorker.run_once`), (4) парадигмы (deep-сон —
    тот же контур Dream). Идемпотентно; второй контур не создаётся; каждый
    шаг fail-open с событием `dossier_cascade`."""
    steps: list[tuple[str, object]] = []
    steps.append(("portraits", _cascade_portraits(chat_id, worker)))
    steps.append(("rag", _cascade_vec_check(db, chat_id)))
    try:
        from services import lore_runtime
        dream = lore_runtime.get_dream_worker()
        if dream is not None and hasattr(dream, "run_once"):
            steps.append(("beliefs", dream.run_once(chat_id)))
    except Exception:
        pass
    for name, coro in steps:
        if coro is None:
            continue
        try:
            await coro
            _emit_cascade_event(chat_id, job_id, name, "success")
        except asyncio.CancelledError:
            raise
        except Exception:
            _emit_cascade_event(chat_id, job_id, name, "failed")
            logger.warning("[dossier_jobs] cascade step %s failed | chat=%s",
                           name, chat_id, exc_info=True)


def _emit_cascade_event(chat_id: int, job_id: str, step: str,
                        outcome: str) -> None:
    try:
        from services import mca_events
        mca_events.emit_mca_event(
            "dossier_cascade", outcome=outcome,
            component="dossier.rebuild", stage="cascade",
            reason_code="dossier_cascade_scheduled",
            job_id=str(job_id), chat_id=int(chat_id))
    except Exception:
        logger.debug("[dossier_jobs] cascade event failed (fail-open)",
                     exc_info=True)


async def _cascade_portraits(chat_id: int, worker):
    """Шаг 1 каскада: пересчёт портретов/мемов существующим контуром
    (LoreWorker.rebuild_dossier_for_chat; LLM-контур, идемпотентно)."""
    if worker is None or not hasattr(worker, "rebuild_dossier_for_chat"):
        return None
    return await worker.rebuild_dossier_for_chat(chat_id)


async def _cascade_vec_check(db, chat_id: int):
    """Шаг 2 каскада: vec-поколение — честная проверка реестра mca-07
    (v18) БЕЗ перевекторизации (§8.3: «не перевекторизовывать без
    установленной необходимости»). `building`/`failed`-поколение при
    активном → диагностируемая причина (`embedding_generation_changed`);
    перестройка несовместимого индекса — отдельный resumable job (вне
    этого шага); операция активации — `db.activate_embedding_generation`
    (N-MCA07-1, гейт `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED`)."""
    try:
        active = await db.get_active_embedding_generation("graph_facts_vec")
        latest = await db.get_latest_embedding_generation("graph_facts_vec")
    except Exception:
        return None
    if latest is not None and str(latest.get("status")) != "active" \
            and active is not None:
        try:
            from services import mca_events
            mca_events.emit_mca_event(
                "dossier_cascade", outcome="skipped",
                component="dossier.rebuild", stage="cascade",
                reason_code="embedding_generation_changed",
                chat_id=int(chat_id))
        except Exception:
            pass
    return latest


async def _run_legacy(*, store: DossierRebuildJobStore, db, worker,
                      job_id: str, chat_id: int, user_id: int,
                      target_name: str, window_hours: int, chunk_size: int,
                      jobs_dir, archive_dir, lock=None) -> None:
    """Legacy-раннер (паритет baseline, master OFF) — поведение
    ADR-1022-8 без изменений."""
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
