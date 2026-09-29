"""MCA Wave 0 (`mca-01-tx-task-supervisor`) — батч 1 (без DDL).

Покрытие:
  * A01: откат A не уничтожает успешную запись B; отмена ожидающего C не
    инициирует rollback чужой транзакции; нет скрытого commit чужой операции;
  * A02: отмена не оставляет pending/active (`smartmodule_concurrency`);
  * known-state/retry (T-3735);
  * kill-switch OFF-паритет (`MCA_TX_OWNERSHIP_ENABLED=false`);
  * lore_cache inflight-cancel / stale-cache (generation);
  * lore_notify leak на ошибке init;
  * shutdown closers независимы;
  * TaskSupervisor registry/coalescing/bounded (T-3741/T-3742);
  * durable `task_jobs` v14: enqueue/coalesce/fencing/heartbeat/recover (T-3740);
  * CooldownTracker eviction (T-3744).
"""
import asyncio
import sqlite3

import aiosqlite
import pytest

import services.database as dbmod
import services.mca_gates as gates
from services.database import DatabaseService


def _locked() -> sqlite3.OperationalError:
    return sqlite3.OperationalError("database is locked")


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr(dbmod, "_LOCK_BACKOFF", 0.0)
    return None


async def _db(tmp_path, name="mca01.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


# ── A01: владение транзакцией ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a01_cancelled_waiter_does_not_rollback_owner(tmp_path,
                                                            no_backoff):
    """A01/SC-02: отменённый ОЖИДАЮЩИЙ lock не откатывает успешную запись
    владельца B (T-3734)."""
    d = await _db(tmp_path)
    try:
        await d.db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        await d.db.commit()
        started = asyncio.Event()
        release = asyncio.Event()

        async def owner_op(conn):
            await conn.execute("INSERT INTO t (v) VALUES (?)", ("B",))
            started.set()
            await release.wait()
            return 1

        # ожидающий C, который будет отменён, пока owner держит lock
        async def waiter_op(conn):
            await conn.execute("INSERT INTO t (v) VALUES (?)", ("C",))
            return 2

        owner = asyncio.ensure_future(
            d.write_transaction(owner_op, op_name="B"))
        await started.wait()
        waiter = asyncio.ensure_future(
            d.write_transaction(waiter_op, op_name="C"))
        await asyncio.sleep(0.01)          # waiter встал на acquisition
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        assert await owner == 1            # B успешно закоммичен
        cur = await d.db.execute("SELECT v FROM t ORDER BY id")
        assert [r[0] for r in await cur.fetchall()] == ["B"]
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_a01_rollback_does_not_destroy_other_write(tmp_path,
                                                         no_backoff):
    """A01/SC-01: откат A (ошибка в теле) не уничтожает успешную запись B."""
    d = await _db(tmp_path)
    try:
        await d.db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                           "v TEXT)")
        await d.db.commit()

        async def good(conn):
            await conn.execute("INSERT INTO t (v) VALUES (?)", ("B",))
            return 1

        async def bad(conn):
            await conn.execute("INSERT INTO t (v) VALUES (?)", ("A",))
            raise ValueError("boom")

        assert await d.write_transaction(good, op_name="B") == 1
        with pytest.raises(ValueError):
            await d.write_transaction(bad, op_name="A")
        cur = await d.db.execute("SELECT v FROM t ORDER BY id")
        assert [r[0] for r in await cur.fetchall()] == ["B"]
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_off_parity_baseline_semantics(tmp_path, monkeypatch,
                                             no_backoff):
    """Kill-switch OFF (`MCA_TX_OWNERSHIP_ENABLED=false`) → прежний
    `write_transaction`: F0.5-retry (`DB_LOCK_RESILIENCE_ENABLED`) сохраняется,
    меняется только размещение rollback (вне lock, baseline-дефект §5.1)."""
    monkeypatch.setattr(gates, "tx_ownership_enabled", lambda: False)
    monkeypatch.setattr(dbmod, "_tx_ownership_enabled", lambda: False)
    d = await _db(tmp_path)
    try:
        calls = {"n": 0}

        async def op(conn):
            calls["n"] += 1
            raise _locked()

        with pytest.raises(sqlite3.OperationalError):
            await d.write_transaction(op, op_name="off")
        # F0.5-retry (1 + 3) сохранён — OFF ownership не отключает resilience.
        assert calls["n"] == dbmod._LOCK_RETRIES + 1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_lock_retry_only_locked(tmp_path, no_backoff):
    """T-3735: retry только для `locked`, не-`locked` не маскируется."""
    d = await _db(tmp_path)
    try:
        calls = {"n": 0}

        async def op(conn):
            calls["n"] += 1
            if calls["n"] < 2:
                raise _locked()
            return "ok"

        assert await d.write_transaction(op, op_name="r") == "ok"
        assert calls["n"] == 2

        calls["n"] = 0

        async def bad(conn):
            calls["n"] += 1
            raise ValueError("no-retry")

        with pytest.raises(ValueError):
            await d.write_transaction(bad, op_name="nr")
        assert calls["n"] == 1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_commit_error_returns_known_state(tmp_path, no_backoff,
                                               monkeypatch):
    """T-3735/SC-03: провал COMMIT → connection в известном состоянии, ошибка
    видна; следующий писатель не подхватывает частичную транзакцию."""
    d = await _db(tmp_path)
    try:
        await d.db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        await d.db.commit()
        real_commit = d.db.commit

        async def flaky_commit():
            raise sqlite3.OperationalError("commit exploded")

        monkeypatch.setattr(d.db, "commit", flaky_commit)

        async def op(conn):
            await conn.execute("INSERT INTO t (v) VALUES (?)", ("x",))
            return 1

        with pytest.raises(sqlite3.OperationalError):
            await d.write_transaction(op, op_name="commit-fail")
        monkeypatch.setattr(d.db, "commit", real_commit)
        # известное состояние: частичной строки нет
        cur = await d.db.execute("SELECT COUNT(*) AS c FROM t")
        assert (await cur.fetchone())[0] == 0
    finally:
        await d.close()


# ── A02: pending в finally ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a02_pending_released_on_cancel(monkeypatch):
    """A02/SC-07: отмена ожидания слотом уменьшает pending (не утекает)."""
    from services import smartmodule_concurrency as smc
    from config.settings import Settings

    monkeypatch.setattr(smc, "settings", Settings(
        SMARTMODULE_CONCURRENCY_PER_CHAT=1,
        SMARTMODULE_CONCURRENCY_WAIT_SECONDS=60.0))
    pool = smc.ChatConcurrencyPool()
    holder = await pool.acquire(-1001)
    task = asyncio.ensure_future(pool.acquire(-1001))
    await asyncio.sleep(0)
    slot = pool._slots[-1001]
    assert slot.pending == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert slot.pending == 0            # pending снят в finally
    holder.release()


@pytest.mark.asyncio
async def test_a02_pending_released_on_timeout(monkeypatch):
    from services import smartmodule_concurrency as smc
    from config.settings import Settings

    monkeypatch.setattr(smc, "settings", Settings(
        SMARTMODULE_CONCURRENCY_PER_CHAT=1,
        SMARTMODULE_CONCURRENCY_WAIT_SECONDS=0.01))
    pool = smc.ChatConcurrencyPool()
    holder = await pool.acquire(-1002)
    permit = await pool.try_acquire(-1002, timeout=0.01)
    assert permit is None
    assert pool._slots[-1002].pending == 0
    holder.release()


# ── D7/D8: lore_cache / lore_notify ───────────────────────────────────────

@pytest.mark.asyncio
async def test_lore_cache_generation_blocks_stale_write():
    """SC-13/SC-14: инвалидация во время загрузки не воскрешает старое."""
    from services.lore_cache import ChatLoreCache, LoreProfile

    class SlowStore:
        def __init__(self):
            self.release = asyncio.Event()

        async def get_profile(self, chat_id):
            await self.release.wait()
            return LoreProfile(chat_id, "old", "", True, 24, 12, True, None,
                               "2026-01-01T00:00:00Z")

    store = SlowStore()
    cache = ChatLoreCache(store)
    task = asyncio.ensure_future(cache.get(-100))
    await asyncio.sleep(0)
    await cache.invalidate(-100)            # generation++
    store.release.set()
    await task
    # устаревшее значение не закэшировано
    assert cache.size() == 0
    assert cache.generation(-100) == 1


@pytest.mark.asyncio
async def test_lore_cache_waiter_does_not_break_coalescing():
    """SC-13: отмена/завершение ОЖИДАЮЩЕГО не снимает inflight владельца."""
    from services.lore_cache import ChatLoreCache, LoreProfile

    calls = {"n": 0}

    class Store:
        async def get_profile(self, chat_id):
            calls["n"] += 1
            await asyncio.sleep(0.02)
            return LoreProfile(chat_id, "l", "", True, 24, 12, True, None,
                               "2026-01-01T00:00:00Z")

    cache = ChatLoreCache(Store())
    owner = asyncio.ensure_future(cache.get(-200))
    await asyncio.sleep(0)
    waiter = asyncio.ensure_future(cache.get(-200))
    await asyncio.sleep(0)
    waiter.cancel()
    try:
        await waiter
    except asyncio.CancelledError:
        pass
    await owner
    assert calls["n"] == 1              # второй SELECT не запускался


@pytest.mark.asyncio
async def test_lore_notify_closes_conn_on_init_failure():
    """SC-13: провал init-функции закрывает соединение (нет утечки)."""
    from services.lore_notify import LoreNotify

    closed = {"n": 0}

    class FakeConn:
        def __init__(self):
            self.is_closed = lambda: False

        async def close(self):
            closed["n"] += 1

    async def connector():
        conn = FakeConn()

        async def bad_init(_conn):
            raise RuntimeError("init failed")

        ln = LoreNotify.__new__(LoreNotify)
        ln._dsn = "dsn"
        ln._init_fn = bad_init
        try:
            await LoreNotify._connect_default(ln) if False else None
        except Exception:
            pass
        # прямой вызов реального метода с фейковым connect
        return conn

    # тестируем сам `_connect_default` с подменённым asyncpg.connect
    import services.lore_notify as lnotify

    class FakeAsyncpg:
        @staticmethod
        async def connect(dsn):
            return FakeConn()

    class FakeLoreNotify(LoreNotify):
        pass

    ln = FakeLoreNotify.__new__(FakeLoreNotify)
    ln._dsn = "dsn"

    async def bad_init(_conn):
        raise RuntimeError("init failed")

    ln._init_fn = bad_init
    orig = lnotify.asyncpg.connect
    lnotify.asyncpg.connect = FakeAsyncpg.connect
    try:
        with pytest.raises(RuntimeError):
            await ln._connect_default()
    finally:
        lnotify.asyncpg.connect = orig
    assert closed["n"] == 1


# ── shutdown closers ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_shutdown_closers_independent(monkeypatch):
    """SC-13: ошибка одного closer не мешает закрыть остальные."""
    monkeypatch.setenv("API_TOKEN", "123456:TEST_TOKEN_FOR_MAIN_FLOW_ABCDE")
    import importlib
    import sys
    import config.settings as settings_mod
    sys.modules.pop("bot", None)
    importlib.reload(settings_mod)
    import bot

    order = []

    class Boom:
        async def stop(self):
            order.append("boom")
            raise RuntimeError("boom")

    class Ok:
        async def stop(self):
            order.append("ok")

    monkeypatch.setattr(bot, "_nostalgia_worker", Boom(), raising=False)
    monkeypatch.setattr(bot, "_anticliche_worker", Ok(), raising=False)
    for name in ("_dream_worker", "_lore_worker", "_lore_notify",
                 "_chat_params_notify", "_uptime_heartbeat",
                 "_goodmorning_scheduler", "_summary_service",
                 "_memory_backup_service", "_memory_maintenance_service",
                 "_llm_client", "_search_aggregator", "_web_extractor",
                 "_checkup_fetcher"):
        monkeypatch.setattr(bot, name, None, raising=False)
    await bot.on_shutdown()
    assert "ok" in order              # следующий closer выполнился


# ── TaskSupervisor: T-3741/T-3742 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_task_supervisor_registry_and_result():
    from services.task_supervisor import (TaskSupervisor, OUTCOME_COMPLETED)

    sup = TaskSupervisor()

    async def work():
        return "ref-1"

    rec = await sup.run(work, owner="summary", kind="important",
                        coalesce_key="chat:-1:v1")
    assert rec.status == OUTCOME_COMPLETED
    assert rec.result_ref == "ref-1"
    assert sup.running_count() == 0
    assert sup.registry_size() == 1


@pytest.mark.asyncio
async def test_task_supervisor_coalescing_singleflight():
    """T-3741/SC-11: один активный запуск на coalesce_key."""
    from services.task_supervisor import TaskSupervisor

    sup = TaskSupervisor()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = {"n": 0}

    async def work():
        calls["n"] += 1
        started.set()
        await release.wait()
        return "x"

    t1 = asyncio.ensure_future(sup.run(work, owner="summary",
                                       coalesce_key="k"))
    await started.wait()
    rec2 = await sup.run(work, owner="summary", coalesce_key="k")
    assert calls["n"] == 1                  # второй запуск не состоялся
    release.set()
    rec1 = await t1
    assert rec2.task_id == rec1.task_id


@pytest.mark.asyncio
async def test_task_supervisor_bounded_secondary_rejected():
    """T-3742/SC-12: переполнение → второстепенное отклонено с причиной."""
    from services.task_supervisor import (TaskSupervisor, QueueFullError,
                                           REASON_QUEUE_FULL)

    sup = TaskSupervisor(max_concurrent=1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def work():
        started.set()
        await release.wait()

    t1 = asyncio.ensure_future(sup.run(work, owner="o", kind="important"))
    await started.wait()

    async def quick():
        return None

    with pytest.raises(QueueFullError) as ei:
        await sup.run(quick, owner="o", kind="secondary")
    assert ei.value.reason_code == REASON_QUEUE_FULL
    release.set()
    await t1


@pytest.mark.asyncio
async def test_task_supervisor_off_passthrough(monkeypatch):
    """Kill-switch OFF: без реестра/коалесинга (pass-through)."""
    from services import task_supervisor as ts

    monkeypatch.setattr(ts, "task_supervisor_enabled", lambda: False)
    sup = ts.TaskSupervisor()
    ran = {"n": 0}

    async def work():
        ran["n"] += 1

    rec = await sup.run(work, owner="o")
    assert ran["n"] == 1
    assert sup.registry_size() == 0


@pytest.mark.asyncio
async def test_task_supervisor_visible_failure():
    """SC-09: провал задачи → видимый терминальный исход + handler."""
    from services.task_supervisor import (TaskSupervisor, OUTCOME_FAILED)

    sup = TaskSupervisor()
    seen = {}

    async def handler(exc):
        seen["type"] = type(exc).__name__

    async def work():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await sup.run(work, owner="o", exception_handler=handler)
    assert seen["type"] == "ValueError"
    assert sup.running_count() == 0


# ── T-3744: cooldown eviction ─────────────────────────────────────────────

def test_cooldown_tracker_eviction():
    from services.smartmodule_throttling import CooldownTracker

    tr = CooldownTracker(cooldown_seconds=0.0)
    for i in range(600):
        tr.touch(i, i)
    # все записи истекли (cooldown=0) и вычищены при переполнении порога
    assert tr.size() <= tr._EVICT_THRESHOLD


# ── feature gates: env-only ClassVar ──────────────────────────────────────

def test_kill_switch_defaults_on(monkeypatch):
    from config.settings import Settings
    monkeypatch.delenv("MCA_TX_OWNERSHIP_ENABLED", raising=False)
    monkeypatch.delenv("MCA_TASK_SUPERVISOR_ENABLED", raising=False)
    monkeypatch.delenv("MCA_SCHEMA_MIGRATIONS_ENABLED", raising=False)
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.Settings.MCA_TX_OWNERSHIP_ENABLED is True
    assert s.Settings.MCA_TASK_SUPERVISOR_ENABLED is True
    assert s.Settings.MCA_SCHEMA_MIGRATIONS_ENABLED is True


# ── T-3740: durable `task_jobs` (v14) ─────────────────────────────────────

async def _job_db(tmp_path, name="jobs.db"):
    from services.database import DatabaseService
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


@pytest.mark.asyncio
async def test_v14_task_jobs_schema_and_version(tmp_path):
    """T-3740: `task_jobs` создана реестром (v14); user_version поднят."""
    d = await _job_db(tmp_path)
    try:
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND "
            "name='task_jobs'")
        assert (await cur.fetchone()) is not None
        cur = await d.db.execute(
            "SELECT version FROM schema_migrations WHERE version = 14")
        assert (await cur.fetchone()) is not None
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_task_jobs_enqueue_and_active(tmp_path):
    from services.task_supervisor import TaskJobStore, JOB_QUEUED

    d = await _job_db(tmp_path)
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="summary", kind="important",
                                  coalesce_key="chat:-1:v1")
        row = await store.get(jid)
        assert row["status"] == JOB_QUEUED
        assert row["owner"] == "summary"
        assert await store.depth() == 1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_task_jobs_coalesce_dedup(tmp_path):
    """SC-11/T-3741: уникальный partial-индекс по активному coalesce_key."""
    from services.task_supervisor import TaskJobStore

    d = await _job_db(tmp_path)
    try:
        store = TaskJobStore(d)
        a = await store.enqueue(owner="summary", kind="important",
                                coalesce_key="k1")
        b = await store.enqueue(owner="summary", kind="important",
                                coalesce_key="k1")
        assert a == b                     # второй не создал дубль
        assert len(await store.active()) == 1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_task_jobs_recover_stale_fencing(tmp_path):
    """A51/SC-10: `running` без heartbeat → `interrupted` + fencing_token++."""
    from services.task_supervisor import TaskJobStore, JOB_INTERRUPTED

    d = await _job_db(tmp_path)
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="archive", kind="important")
        await store.mark_running(jid)
        # heartbeat в прошлом → stale
        await d.db.execute(
            "UPDATE task_jobs SET heartbeat_at = 0 WHERE job_id = ?", (jid,))
        await d.db.commit()
        recovered = await store.recover_stale(stale_after_seconds=1)
        assert jid in recovered
        row = await store.get(jid)
        assert row["status"] == JOB_INTERRUPTED
        assert row["reason_code"] == "worker_lost"
        assert row["fencing_token"] == 1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_task_jobs_finish_and_prune(tmp_path):
    from services.task_supervisor import TaskJobStore, JOB_COMPLETED

    d = await _job_db(tmp_path)
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="summary", kind="secondary")
        await store.mark_running(jid)
        await store.heartbeat(jid)
        await store.finish(jid, status=JOB_COMPLETED, result_ref="ref-1")
        row = await store.get(jid)
        assert row["status"] == JOB_COMPLETED and row["result_ref"] == "ref-1"
        # prune с ретенцией 0 → удаляет терминальные
        await d.db.execute("UPDATE task_jobs SET finished_at = 0 "
                           "WHERE job_id = ?", (jid,))
        await d.db.commit()
        assert await store.prune(terminal_retention_seconds=1) == 1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_task_jobs_overdue(tmp_path):
    from services.task_supervisor import TaskJobStore

    d = await _job_db(tmp_path)
    try:
        store = TaskJobStore(d)
        await store.enqueue(owner="summary", kind="secondary", deadline_at=1)
        overdue = await store.overdue(now=10)
        assert len(overdue) == 1
    finally:
        await d.close()



@pytest.mark.asyncio
async def test_supervisor_durable_lifecycle(tmp_path):
    """T-3740: `run(job_store=...)` ведёт durable queued→running→completed."""
    from services.task_supervisor import (TaskSupervisor, TaskJobStore,
                                          JOB_COMPLETED)

    d = await _job_db(tmp_path, name="life.db")
    try:
        store = TaskJobStore(d)
        sup = TaskSupervisor()

        async def work():
            return "ref-x"

        rec = await sup.run(work, owner="summary", kind="important",
                            job_store=store, coalesce_key="c1",
                            emit_event=False)
        assert rec.job_id
        row = await store.get(rec.job_id)
        assert row["status"] == JOB_COMPLETED
        assert row["result_ref"] == "ref-x"
        assert row["attempt"] == 1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_supervisor_emits_events(tmp_path):
    """T-3746: терминальный исход задачи эмитит событие MCA-13."""
    from services.task_supervisor import TaskSupervisor
    from services import mca_events as me

    me.reset_pending()
    sup = TaskSupervisor()

    async def work():
        return None

    await sup.run(work, owner="summary", kind="important",
                  coalesce_key="evt1", emit_event=True)
    # start не буферизуется, терминальный — да
    assert me.pending_size() == 1
    me.reset_pending()


@pytest.mark.asyncio
async def test_archive_job_checkpoint_resume(tmp_path):
    """T-3757: checkpoint сохраняется/читается для resume (без долгой tx)."""
    from services.task_supervisor import TaskJobStore

    d = await _job_db(tmp_path, name="arch.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="archive", kind="important",
                                  coalesce_key="archive:range:1")
        await store.save_checkpoint(jid, cursor_token="mid-42", processed=42)
        cp = await store.get_checkpoint(jid)
        assert cp == {"cursor": "mid-42", "processed": 42}
        # повторный старт с тем же coalesce_key не создаёт дубль
        jid2 = await store.enqueue(owner="archive", kind="important",
                                   coalesce_key="archive:range:1")
        assert jid2 == jid
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_a51_takeover_no_duplicate(tmp_path):
    """A51: гибель worker → `interrupted`, takeover с fencing, без дублей.

    Пока job `running` (heartbeat stale), повторный enqueue с тем же
    coalesce_key не создаёт вторую задачу (unique partial-индекс активных)."""
    from services.task_supervisor import (TaskJobStore, JOB_INTERRUPTED,
                                          JOB_QUEUED)

    d = await _job_db(tmp_path, name="a51.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="archive", kind="important",
                                  coalesce_key="archive:takeover")
        await store.mark_running(jid)
        # worker «умер»: heartbeat устарел
        await d.db.execute(
            "UPDATE task_jobs SET heartbeat_at = 0 WHERE job_id = ?", (jid,))
        await d.db.commit()
        # takeover-кандидат виден, но дубль не создаётся, пока задача активна
        dup = await store.enqueue(owner="archive", kind="important",
                                  coalesce_key="archive:takeover")
        assert dup == jid
        # recovery помечает interrupted и бампает fencing_token
        recovered = await store.recover_stale(stale_after_seconds=1)
        assert jid in recovered
        row = await store.get(jid)
        assert row["status"] == JOB_INTERRUPTED
        assert row["fencing_token"] >= 1
        # теперь активного нет → новая задача с тем же ключом создаётся
        new_id = await store.enqueue(owner="archive", kind="important",
                                     coalesce_key="archive:takeover")
        assert new_id != jid
        new_row = await store.get(new_id)
        assert new_row["status"] == JOB_QUEUED
    finally:
        await d.close()


# ── B-MCA01-2: важная очередь под переполнением (регресс deadlock) ──────────

@pytest.mark.asyncio
async def test_important_queue_no_deadlock_on_overflow():
    """B-MCA01-2/SC-12: важная задача при переполнении дожидается слота под
    `Condition` и завершается; регресс воспроизведённого Reviewer deadlock
    (ожидание слота под мьютексом, нужным для освобождения)."""
    from services.task_supervisor import TaskSupervisor

    sup = TaskSupervisor(max_concurrent=1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def hold():
        started.set()
        await release.wait()
        return "h"

    t1 = asyncio.ensure_future(sup.run(hold, owner="o", kind="important",
                                       emit_event=False))
    await started.wait()

    async def quick():
        return "q"

    t2 = asyncio.ensure_future(sup.run(quick, owner="o", kind="important",
                                       emit_event=False))
    await asyncio.sleep(0.02)
    assert sup.running_count() == 1          # t2 ждёт слот, guard не удержан
    release.set()
    done = await asyncio.wait_for(asyncio.gather(t1, t2), timeout=2.0)
    assert [r.result_ref for r in done] == ["h", "q"]
    assert sup.running_count() == 0


# ── B-MCA01-3: fencing реально отклоняет запись устаревшего владельца ────────

@pytest.mark.asyncio
async def test_stale_fencing_owner_write_rejected(tmp_path):
    """B-MCA01-3/A51: после takeover запись старым `fencing_token` — no-op
    (`finish`/`heartbeat`/`save_checkpoint`); актуальный токен пишет успешно."""
    from services.task_supervisor import TaskJobStore, JOB_COMPLETED

    d = await _job_db(tmp_path, name="fence.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="archive", kind="important")
        await store.mark_running(jid)                 # token=0
        await d.db.execute(
            "UPDATE task_jobs SET heartbeat_at = 0 WHERE job_id = ?", (jid,))
        await d.db.commit()
        await store.recover_stale(stale_after_seconds=1)
        new_token = (await store.get(jid))["fencing_token"]
        assert new_token >= 1
        # старый владелец (token=0) отклонён на всех write-путях
        assert await store.finish(jid, status=JOB_COMPLETED,
                                  result_ref="stale", fencing_token=0) is False
        assert await store.heartbeat(jid, fencing_token=0) is False
        assert await store.save_checkpoint(
            jid, cursor_token="x", processed=1, fencing_token=0) is False
        row = await store.get(jid)
        assert row["result_ref"] != "stale"
        # актуальный владелец пишет успешно
        assert await store.finish(jid, status=JOB_COMPLETED, result_ref="ok",
                                  fencing_token=new_token) is True
        assert (await store.get(jid))["result_ref"] == "ok"
    finally:
        await d.close()


# ── B-MCA01-4: recovery деградировавшего соединения строго под lock ─────────

@pytest.mark.asyncio
async def test_degraded_recovery_rollback_under_lock(tmp_path, no_backoff,
                                                     monkeypatch):
    """B-MCA01-4/SC-03: recovery деградировавшего соединения выполняется под
    `self._lock`; параллельные писатели не откатывают транзакцию друг друга."""
    d = await _db(tmp_path, name="degraded.db")
    try:
        await d.db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        await d.db.commit()
        seen = {}
        real = d._safe_rollback_locked

        async def spy(op_name, phase):
            seen[phase] = d._write_owner is asyncio.current_task()
            return await real(op_name, phase)

        monkeypatch.setattr(d, "_safe_rollback_locked", spy)
        d._connection_degraded = True

        async def op(v):
            async def _body(conn):
                await conn.execute("INSERT INTO t (v) VALUES (?)", (v,))
                return v
            return await d.write_transaction(_body, op_name=f"w-{v}")

        results = await asyncio.gather(op("a"), op("b"))
        assert set(results) == {"a", "b"}
        cur = await d.db.execute("SELECT COUNT(*) AS c FROM t")
        assert (await cur.fetchone())[0] == 2
        assert d._connection_degraded is False
        assert seen.get("recover-degraded") is True   # под lock
    finally:
        await d.close()


# ── B-MCA01-1/SC-05: аудит write-точек (guard) ──────────────────────────────

def test_write_points_go_through_single_writer():
    """B-MCA01-1/SC-05: аудит ВСЕХ write-точек `services/` (реестр/allowlist).

    * `database.py` — прямой `*.commit()` допустим ТОЛЬКО внутри
      `@_serialized_write`-метода, `write_transaction`-машинерии или
      санкционированного DDL-этапа `initialize()`/`_migrate_*` (L-MCA14-3,
      до старта сервинга); новых прямых commit вне механизма быть не должно.
    * остальные модули — только в allowlist и под `serialized()` (единый
      single-writer) либо с явным маркером санкционированного fallback
      (`mca01-write-fallback`); собственные соединения (`smart_cache.py`) —
      санкционированное исключение (отдельная БД, не общая connection).
    """
    import ast
    from pathlib import Path

    # allowlist: файл → число прямых commit (все — эквивалент single-writer).
    # database.py: 49 в `@_serialized_write`-методах + 60 в санкционированной
    # DDL/initialize/write_transaction-машинерии (реестр — evidence-rework.md;
    # +7 — санкционированные commit шага v16 `mca-03`/backfill, L-MCA14-3;
    # +7 — санкционированные commit шага v17 `mca-04a`/backfill, L-MCA14-3;
    # +6 — санкционированные commit шага v18 `mca-07` (миграция identity/
    # поколений + `ensure_embedding_generation` под serialized(), L-MCA14-3).
    # +7 — санкционированные commit шага v19 `mca-17a` (observability_core:
    # run/incident-таблицы + их индексы + 2×ALTER-колонки `task_jobs`/
    # `mca_events` + PRAGMA, L-MCA14-3; раннер до старта писателей).
    allow = {
        "database.py": 129,
        "dossier_rebuild_jobs.py": 1,   # внутри `async with db.serialized()`
        "memory_maintenance.py": 1,     # внутри `async with self.db.serialized()`
        "persistent_throttling.py": 1,  # fallback-двойник без write_transaction
        "smart_cache.py": 3,            # ОТДЕЛЬНОЕ соединение (F17), не общая
        "summary_memory.py": 13,        # 12 в serialized() + 1 fallback-двойник
    }
    # database.py: санкционированные точки (DDL/инициализация до сервинга,
    # машинерия write_transaction). Остальное обязано быть `@_serialized_write`.
    db_sanctioned = {
        "initialize", "initialize_existing", "_run_migrations",
        "_ensure_migration_book", "_write_transaction_baseline",
        "_write_transaction_owned", "_commit_locked",
    }
    separate_connection = {"smart_cache.py"}

    def _decorators(node) -> list[str]:
        return [ast.unparse(d) for d in node.decorator_list]

    def _walk_up(call):
        """Ancestors до ближайшей функции + флаг `serialized()`-контекста."""
        node = call
        in_serialized = False
        while id(node) in parents:
            node = parents[id(node)]
            if isinstance(node, (ast.With, ast.AsyncWith)):
                ctx = [ast.unparse(item.context_expr)
                       for item in node.items]
                if any("serialized()" in c for c in ctx):
                    in_serialized = True
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node, in_serialized
        return None, in_serialized

    found: dict[str, int] = {}
    unguarded: list[str] = []
    root = Path(__file__).resolve().parent.parent / "services"
    for path in sorted(root.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines()
        tree = ast.parse(src)
        parents: dict[int, object] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[id(child)] = node
        commits = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "commit"]
        for call in commits:
            lineno = call.lineno
            found[path.name] = found.get(path.name, 0) + 1
            func, in_serialized = _walk_up(call)
            if path.name == "database.py":
                guarded = in_serialized or (
                    func is not None
                    and (any("_serialized_write" in d
                             for d in _decorators(func))
                         or func.name in db_sanctioned
                         or func.name.startswith("_migrate_")))
                if not guarded:
                    unguarded.append(f"database.py:{lineno}")
                continue
            if "mca01-write-fallback" in lines[lineno - 1]:
                continue
            if path.name in separate_connection:
                continue    # санкционированное исключение (отдельное соединение)
            guarded = in_serialized or (
                func is not None
                and any("_serialized_write" in d for d in _decorators(func)))
            if not guarded:
                unguarded.append(f"{path.name}:{lineno}")
    assert found == allow, f"write-точки изменились (нужен аудит): {found}"
    assert unguarded == [], f"commit вне single-writer/allowlist: {unguarded}"


def test_no_nested_raw_lock_in_serialized_methods():
    """B-MCA01-1: `@_serialized_write`-метод не должен повторно брать
    `self._lock`/`serialized()` вручную — иначе self-дедлок (регресс
    `slavic_photo_count_tick`), т.к. `asyncio.Lock` не реентрантен."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "services"
    offenders: list[str] = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            decorators = [ast.unparse(d) for d in node.decorator_list]
            if not any("_serialized_write" in d for d in decorators):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Attribute)
                        and inner.attr == "_lock"
                        and isinstance(inner.value, ast.Name)
                        and inner.value.id == "self"):
                    offenders.append(f"{path.name}:{node.name}:{inner.lineno}")
    assert offenders == [], (
        f"raw self._lock внутри @_serialized_write (дедлок): {offenders}")
