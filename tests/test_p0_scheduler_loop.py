"""P0 SCHEDULER: блокировка event loop и misfire (LVS-SCH-01..05).

Приёмка слайса (`plans/features/llm-vision-scheduler-p0`, SCH):

* LVS-SCH-02/03: sync SQLite-ожидание (`busy_timeout=5000`) не должно
  выполняться в event loop — ни в `slot_claims.claim_slot_if_due`, ни в
  `publication_coordination` (same class). RED: gap пробника ≈ время
  удержания write-lock; GREEN: gap < 100 ms, claim/бронь ровно один.
* LVS-SCH-01/03: у interval/cron-джоб явный `misfire_grace_time`,
  согласованный с интервалом (заводской 1 s не остаётся); grace ≤ интервала.
* LVS-SCH-03: summary сначала бронирует ВСЕ due-чаты, затем генерирует —
  долгий первый прогон не откладывает claim второго чата и не съедает его
  due-окно; без новой конкурентности, порядок чатов сохранён.
* LVS-SCH-05: ровно один INSERT heartbeat на запуск; late run в пределах
  grace выполняется один раз; два разных запуска — две строки.

Каждый тест дискриминативен: возврат sync `try_claim`, удаление claim-first
или удаление explicit grace делает соответствующий тест красным.

TEST-LIFECYCLE: CONTRACT owner=LVS-SCH / P0 scheduler
"""
import ast
import asyncio
import datetime
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import services.chat_params as chat_params
from config.settings import settings
from services import publication_coordination as pub
from services import slot_claims
from services.database import DatabaseService
from services.dream_worker import DreamWorker
from services.goodmorning_scheduler import GoodmorningSchedulerService
from services.lore_worker import LoreWorker
from services.memory_backup import MemoryBackupService
from services.memory_maintenance import MemoryMaintenanceService
from services.nostalgia_worker import NostalgiaWorker
from services.slot_claims import (
    SqliteSlotClaimStore,
    claim_slot_if_due,
)
from services.summary_scheduler import SummarySchedulerService
from services.uptime_heartbeat import UptimeHeartbeatService

pytestmark = pytest.mark.system2

UTC = datetime.timezone.utc
ROOT = Path(__file__).resolve().parents[1]

#: UTC-шкала 00/06/12/18; 12:00:30 — внутри due-окна 120 c (UTC-пояс).
SLOT_SEQ = ((0, 0), (6, 0), (12, 0), (18, 0))
NOW_DUE = datetime.datetime(2026, 1, 15, 12, 0, 30, tzinfo=UTC)
SLOT_LABEL = "12:00"
LOCAL_DATE = "2026-01-15"
#: Factory-пояс чата Asia/Yekaterinburg (+5): 18:00 local = 13:00:30 UTC.
NOW_SUMMARY = datetime.datetime(2026, 1, 15, 13, 0, 30, tzinfo=UTC)
SUMMARY_SLOT_LABEL = "18:00"


# ── вспомогательное: удержание write-lock и пробник event loop ──────────────


class _WriteLock:
    """`BEGIN IMMEDIATE` в отдельном потоке — имитация чужого писателя.

    Именно это ожидание (`busy_timeout=5000`) уходит в event loop при
    sync-вызове `try_claim`/store-метода; тест измеряет, блокируется ли
    loop, а не только длительность операции."""

    def __init__(self, path: str, hold: float = 0.5) -> None:
        self.path = path
        self.hold = hold
        self.acquired = threading.Event()
        self.released = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "_WriteLock":
        self._thread.start()
        assert self.acquired.wait(2.0), "write-lock не был взят"
        return self

    def _run(self) -> None:
        conn = sqlite3.connect(self.path, timeout=0, isolation_level=None,
                              check_same_thread=False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self.acquired.set()
            time.sleep(self.hold)
            conn.execute("COMMIT")
        finally:
            conn.close()
            self.released.set()


async def _max_loop_gap_while(task: asyncio.Task) -> float:
    """Максимальный разрыв между итерациями `sleep` под работающей задачей.

    Если задача блокирует event loop, разрыв ≈ времени блокировки."""
    loop = asyncio.get_running_loop()
    last = loop.time()
    gap = 0.0
    while not task.done():
        await asyncio.sleep(0.005)
        cur = loop.time()
        gap = max(gap, cur - last)
        last = cur
    return gap


async def _fixed_zone(chat_id):
    """Фиксированный пояс для claim-теста (не предмет проверки)."""
    return UTC, "UTC", "test", "v1"


def _prepare_slot_db(path: str) -> SqliteSlotClaimStore:
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    finally:
        conn.close()
    store = SqliteSlotClaimStore(path)
    store.apply_schema()
    return store


# ── B1: claim слотов не блокирует event loop ───────────────────────────────


class TestSlotClaimDoesNotBlockLoop:
    @pytest.mark.asyncio
    async def test_claim_waits_in_worker_thread_not_event_loop(
            self, tmp_path, monkeypatch):
        path = str(tmp_path / "slot.db")
        store = _prepare_slot_db(path)
        db = SimpleNamespace(db_path=path)
        monkeypatch.setattr(slot_claims, "resolve_chat_zone", _fixed_zone)
        lock = _WriteLock(path, hold=0.5).start()
        started = time.perf_counter()
        task = asyncio.create_task(claim_slot_if_due(
            kind="summary", db=db, chat_id=-1001, now_utc=NOW_DUE,
            slot_seq=SLOT_SEQ, due_window_s=120))
        gap = await _max_loop_gap_while(task)
        verdict = await task
        elapsed = time.perf_counter() - started
        assert lock.released.wait(2.0)
        assert verdict.action == slot_claims.ACTION_FIRE
        assert elapsed >= 0.4, (
            f"claim не ждал write-lock ({elapsed:.3f}s) — тест не воспроизводит "
            "ожидание")
        assert gap < 0.1, (
            f"event loop заблокирован на {gap * 1000:.0f} ms (ожидание "
            "busy_timeout в loop)")
        row = store.lookup(kind="summary", chat_id=-1001,
                           local_date=LOCAL_DATE, local_slot=SLOT_LABEL)
        assert row is not None and row["fired"] == 1

    @pytest.mark.asyncio
    async def test_claim_is_exactly_once_and_cas_preserved(
            self, tmp_path, monkeypatch):
        """CAS/атомарность не меняются: второй claim → skip_busy; строка
        честного skip (fired=0) перебронируется при смене instant."""
        path = str(tmp_path / "slot.db")
        store = _prepare_slot_db(path)
        db = SimpleNamespace(db_path=path)
        monkeypatch.setattr(slot_claims, "resolve_chat_zone", _fixed_zone)

        first = await claim_slot_if_due(
            kind="summary", db=db, chat_id=-1001, now_utc=NOW_DUE,
            slot_seq=SLOT_SEQ, due_window_s=120)
        second = await claim_slot_if_due(
            kind="summary", db=db, chat_id=-1001, now_utc=NOW_DUE,
            slot_seq=SLOT_SEQ, due_window_s=120)
        assert first.action == slot_claims.ACTION_FIRE
        assert second.action == slot_claims.ACTION_SKIP_BUSY
        conn = sqlite3.connect(path)
        try:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {slot_claims.SLOT_CLAIMS_TABLE} "
                "WHERE kind='summary' AND chat_id=-1001").fetchone()[0]
        finally:
            conn.close()
        assert count == 1, "claim не атомарен — создано больше одной строки"

        # CAS-перебронь: строка fired=0 со СТАРЫМ instant (смена пояса).
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                f"INSERT INTO {slot_claims.SLOT_CLAIMS_TABLE} (kind, chat_id, "
                "local_date, local_slot, slot_utc_instant, config_version, "
                "claimed_at, fired, reason_code) "
                "VALUES ('summary', -1002, ?, ?, 0, 'v1', 0, 0, "
                "'missed_slot_expired')", (LOCAL_DATE, SLOT_LABEL))
            conn.commit()
        finally:
            conn.close()
        cas = await claim_slot_if_due(
            kind="summary", db=db, chat_id=-1002, now_utc=NOW_DUE,
            slot_seq=SLOT_SEQ, due_window_s=120)
        assert cas.action == slot_claims.ACTION_FIRE
        row = store.lookup(kind="summary", chat_id=-1002,
                           local_date=LOCAL_DATE, local_slot=SLOT_LABEL)
        assert row["fired"] == 1 and row["reason_code"] == ""
        assert row["slot_utc_instant"] == int(NOW_DUE.timestamp()) - 30


# ── B3: publication coordination — тот же class sync-wait ──────────────────


class TestPublicationDoesNotBlockLoop:
    @pytest.mark.asyncio
    async def test_publication_acquire_waits_outside_event_loop(self, tmp_path):
        path = str(tmp_path / "pub.db")
        conn = sqlite3.connect(path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        finally:
            conn.close()
        store = pub.SqliteClaimStore(path)
        store.apply_schema()
        now = 1_000_000
        coordinator = pub.PublicationCoordinator(
            store=store, now_fn=lambda: now)
        lock = _WriteLock(path, hold=0.5).start()
        task = asyncio.create_task(
            coordinator.acquire(-1001, "initiative", interval_seconds=0))
        gap = await _max_loop_gap_while(task)
        decision = await task
        assert lock.released.wait(2.0)
        assert decision.granted is True
        assert gap < 0.1, (
            f"event loop заблокирован на {gap * 1000:.0f} ms бронью публикации")
        # publish-контракт не меняется: claimed → sending → release+watermark.
        sending = await coordinator.begin_sending(
            -1001, decision.claim_id, now=now)
        assert sending.granted is True
        released = await coordinator.release(
            -1001, decision.claim_id, published=True,
            holder_kind="initiative", now=now + 1)
        assert released is True
        snapshot = await coordinator.snapshot(-1001, now=now + 2)
        assert snapshot["last_publish_kind"] == "initiative"
        assert snapshot["last_publish_ts"] == now + 1


class _ProbeEvent(asyncio.Event):
    """Event с публичным сигналом «waiter реально вошёл в wait()»."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()

    async def wait(self):
        self.entered.set()
        return await super().wait()


class TestReleaseEventThreadSafety:
    @pytest.mark.asyncio
    async def test_manual_waiter_wakes_after_release_from_worker_thread(
            self, tmp_path, monkeypatch):
        """F1: `store.release` выполняется в worker-thread (`to_thread`).

        `Event.set()` из чужого потока недопустим: в debug-loop это
        RuntimeError, без debug — потерянный wakeup/гонка. Проверяем
        production-путь `coordinator.release` → `SqliteClaimStore.release`
        при `loop.set_debug(True)`: ошибки нет, ручной waiter просыпается
        сразу (<1 s) и получает слот.
        """
        loop = asyncio.get_running_loop()
        loop.set_debug(True)
        try:
            path = str(tmp_path / "pub-wake.db")
            conn = sqlite3.connect(path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            finally:
                conn.close()
            store = pub.SqliteClaimStore(path)
            store.apply_schema()
            now = 1_000_000
            coordinator = pub.PublicationCoordinator(
                store=store, now_fn=lambda: now)
            foreign = await coordinator.acquire(
                -1001, pub.KIND_TEXT_INITIATIVE, interval_seconds=0)
            assert foreign.granted
            sending = await coordinator.begin_sending(
                -1001, foreign.claim_id, now=now)
            assert sending.granted

            # Событие создаётся production-путём (loop запоминается) и
            # подменяется пробником, чтобы детерминированно знать, что
            # waiter уже внутри wait().
            pub.reset_release_events()
            assert pub._release_event(-1001) is not None
            probe = _ProbeEvent()
            pub._RELEASE_EVENTS[-1001] = probe
            monkeypatch.setattr(pub, "_release_event", lambda _cid: probe)

            waiter = asyncio.create_task(coordinator.acquire(
                -1001, pub.KIND_MEME_INITIATIVE, interval_seconds=0,
                manual=True, wait_for_sending=5.0))
            await asyncio.wait_for(probe.entered.wait(), 2.0)
            assert not waiter.done()

            started = time.perf_counter()
            released = await coordinator.release(
                -1001, foreign.claim_id, published=True,
                holder_kind=pub.KIND_TEXT_INITIATIVE, now=now + 1)
            decision = await asyncio.wait_for(waiter, 1.0)
            elapsed = time.perf_counter() - started
            assert released is True
            assert decision.granted is True
            assert elapsed < 1.0, (
                f"waiter проснулся только через {elapsed:.2f}s")
        finally:
            loop.set_debug(False)
            pub.reset_release_events()


# ── APScheduler misfire: blocked loop → late run вне grace пропускается ────


class TestApschedulerMisfireMechanism:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("grace,expected", [(1, 0), (5, 1)])
    async def test_late_job_skipped_or_run_once(self, grace, expected):
        """Blocker держит loop 2 s → victim стартует с опозданием ~1.9 s:
        grace 1 s (минимум APScheduler) → skip, grace 5 s → ровно один
        запуск. Это тот же механизм, что давал три WARN на 4–5 s lag."""
        runs: list[float] = []
        scheduler = AsyncIOScheduler(timezone=UTC)
        base = datetime.datetime.now(UTC)

        async def blocker():  # blocker в loop: имитация sync I/O в тике
            time.sleep(2.0)

        def victim():
            runs.append(time.perf_counter())

        scheduler.add_job(
            blocker, IntervalTrigger(seconds=60),
            next_run_time=base + datetime.timedelta(seconds=0.05),
            id="blocker", max_instances=1)
        scheduler.add_job(
            victim, IntervalTrigger(seconds=60),
            next_run_time=base + datetime.timedelta(seconds=0.10),
            id="victim", max_instances=1, coalesce=True,
            misfire_grace_time=grace)
        scheduler.start()
        try:
            await asyncio.sleep(2.8)
        finally:
            scheduler.shutdown(wait=False)
        assert len(runs) == expected


# ── B2: claim-first summary (backpressure без потери due-окна) ─────────────


class _FakeCache:
    def __init__(self, roots=None):
        self._roots = dict(roots or {})

    async def get_chat_params(self, chat_id):
        return self._roots.get(int(chat_id), {})

    async def get_chat_params_full(self, chat_id):
        return self._roots.get(int(chat_id), {}), "v1"


@pytest.fixture()
def chat_clock_env(monkeypatch):
    """Изоляция пояса чата: factory-слой Asia/Yekaterinburg (UTC+5)."""
    old_tz = settings.SUMMARY_TIMEZONE
    old_chat_tz = settings.CHAT_TIMEZONE
    slot_claims.reset_in_memory_claims()
    chat_params._chat_params_cache = _FakeCache()
    monkeypatch.delenv("GOODMORNING_TZ", raising=False)
    monkeypatch.delenv("CHAT_TIMEZONE", raising=False)
    monkeypatch.delenv("SUMMARY_TIMEZONE", raising=False)
    object.__setattr__(settings, "SUMMARY_TIMEZONE", "Asia/Yekaterinburg")
    object.__setattr__(settings, "CHAT_TIMEZONE", "")
    yield
    chat_params._chat_params_cache = None
    object.__setattr__(settings, "SUMMARY_TIMEZONE", old_tz)
    object.__setattr__(settings, "CHAT_TIMEZONE", old_chat_tz)
    slot_claims.reset_in_memory_claims()


class TestSummaryClaimFirst:
    @pytest.mark.asyncio
    async def test_all_due_chats_claimed_before_first_long_run(
            self, tmp_path, chat_clock_env):
        """Пока первый чат генерируется, слот второго уже забронирован;
        второй не получает `missed_slot_expired`, дублей нет."""
        db = DatabaseService(str(tmp_path / "summary.db"))
        await db.initialize()
        store = SqliteSlotClaimStore(db.db_path)
        started = asyncio.Event()
        release = asyncio.Event()
        calls: list[int] = []

        async def generate_and_send(chat_id):
            calls.append(chat_id)
            if len(calls) == 1:
                started.set()
                await release.wait()

        generator = SimpleNamespace(generate_and_send=generate_and_send)
        service = SummarySchedulerService(generator, db)
        targets = (-1001, -1002)
        mod = replace(settings, SUMMARY_TARGET_CHAT_IDS=targets)
        with patch("services.summary_scheduler.settings", mod):
            task = asyncio.create_task(service._tick(now_utc=NOW_SUMMARY))
            await asyncio.wait_for(started.wait(), 2.0)
            assert calls == [-1001], (
                "второй чат стартовал до завершения первого (новая "
                "конкурентность не разрешена)")
            second = store.lookup(kind="summary", chat_id=-1002,
                                  local_date=LOCAL_DATE,
                                  local_slot=SUMMARY_SLOT_LABEL)
            assert second is not None, (
                "claim второго чата не сделан до долгого первого прогона: "
                "due-окно может истечь")
            assert second["fired"] == 1 and second["reason_code"] == ""
            assert not task.done()
            release.set()
            await asyncio.wait_for(task, 5.0)
        assert calls == [-1001, -1002], "порядок чатов должен сохраниться"

        # Повторный тик в том же due-окне: слоты заняты, дублей нет.
        with patch("services.summary_scheduler.settings", mod):
            await service._tick(
                now_utc=NOW_SUMMARY + datetime.timedelta(seconds=5))
        assert calls == [-1001, -1002]
        for chat_id in targets:
            row = store.lookup(kind="summary", chat_id=chat_id,
                               local_date=LOCAL_DATE,
                               local_slot=SUMMARY_SLOT_LABEL)
            assert row is not None
            assert row["fired"] == 1
            assert row["reason_code"] == "", (
                "слот второго чата помечен missed_slot_expired")
        await service.shutdown()
        await db.close()


# ── uptime heartbeat: один запуск — одна строка ────────────────────────────


class _CountingConn:
    def __init__(self, fail: bool = False) -> None:
        self.queries: list[tuple[str, tuple]] = []
        self._fail = fail

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        if self._fail:
            raise ConnectionError("pg down")

    async def fetch(self, sql, *args):
        return []


class _FakePool:
    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _FakePg:
    def __init__(self, conn=None) -> None:
        self.pool = _FakePool(conn) if conn is not None else None


class TestUptimeNoDuplicate:
    @pytest.mark.asyncio
    async def test_one_insert_per_run_and_two_runs_two_rows(self):
        conn = _CountingConn()
        service = UptimeHeartbeatService(pg=_FakePg(conn))
        await service._heartbeat()
        assert len(conn.queries) == 1
        await service._heartbeat()
        assert len(conn.queries) == 2, (
            "два разных запуска должны дать две строки, не дубль одного")

    @pytest.mark.asyncio
    async def test_late_run_within_explicit_grace_executes_once(self):
        conn = _CountingConn()
        service = UptimeHeartbeatService(pg=_FakePg(conn))
        service.start()
        try:
            job = service._scheduler.get_job("uptime_heartbeat")
            assert job is not None
            assert job.misfire_grace_time == 30
            late = datetime.datetime.now(UTC) - datetime.timedelta(seconds=1)
            service._scheduler.modify_job(
                "uptime_heartbeat", next_run_time=late)
            await asyncio.sleep(0.6)
        finally:
            await service.shutdown()
        assert len(conn.queries) == 1, (
            f"late run в пределах grace дал {len(conn.queries)} INSERT")


# ── A: явный misfire_grace_time у всех джоб ────────────────────────────────

#: Точный контракт значений: не одна универсальная константа, а значение
#: ≤ интервала и ≤ собственного due/lease-окна джобы.
EXPECTED_GRACE = {
    "summary_job": 30,                # interval 60 s, due-окно 120 s
    "goodmorning_job": 30,            # interval 60 s, due-окно 120 s
    "nostalgia_tick": 30,             # heartbeat ≥ 60 s, log/lease
    "uptime_heartbeat": 30,           # interval 60 s
    "uptime_cleanup": 300,            # interval 1 h, идемпотентный DELETE
    "lore_worker_tick": 60,           # interval 30 min
    "dream_tick": 300,                # interval ~60 min, durable watermark
    "deep_sleep_tick": 300,           # interval ~60 min, _deep_lock
    "memory_backup_job": 3600,        # daily cron
    "graph_episode_merge": 3600,      # interval days
    "graph_review": 3600,             # interval days
    "db_wal_checkpoint": 300,         # interval hours
    "experience_review_tick": 60,     # interval 900 s
    "intent_heartbeat_tick": 60,      # interval 300 s
    "embed_recovery_tick": 60,        # interval 600 s
    "initiative_observer_tick": 60,   # interval 300 s
    "memory_communities_build": 60,   # interval 3600 s
    "self_diag_samples": 60,          # interval 300 s (D6-20: срез ресурсов)
    "legacy_traits_parse_tick": 60,   # interval 3600 s (если K3 ON)
}


class _NullCursor:
    async def fetchone(self):
        return None

    async def fetchall(self):
        return []


class _NullInnerDb:
    async def execute(self, *args, **kwargs):
        return _NullCursor()


class _NullDb:
    """Минимальный async-двойник DatabaseService для старта обслуживания."""

    def __init__(self) -> None:
        self.db = _NullInnerDb()


class TestSchedulerJobContract:
    @pytest.mark.asyncio
    async def test_all_started_jobs_declare_expected_explicit_grace(self):
        summary = SummarySchedulerService(MagicMock(), MagicMock())
        summary.start()
        goodmorning = GoodmorningSchedulerService(
            MagicMock(), "07:30", (-1001,))
        assert goodmorning.start() is True
        nostalgia = NostalgiaWorker(MagicMock())
        nostalgia.start()
        lore = LoreWorker(MagicMock())
        await lore.start()
        dream = DreamWorker(MagicMock())
        dream.start()
        maintenance = MemoryMaintenanceService(_NullDb(), None, None)
        maintenance.start()
        backup = MemoryBackupService(MagicMock())
        backup.start()
        uptime = UptimeHeartbeatService(pg=_FakePg(_CountingConn()))
        uptime.start()

        services = [summary, goodmorning, nostalgia, lore, dream,
                    maintenance, backup, uptime]
        seen: dict[str, int] = {}
        try:
            for service in services:
                for job in service._scheduler.get_jobs():
                    assert job.misfire_grace_time is not None, (
                        f"{job.id}: заводской misfire_grace_time=1 s")
                    assert job.id in EXPECTED_GRACE, (
                        f"{job.id}: значение grace не зафиксировано контрактом")
                    assert job.misfire_grace_time == EXPECTED_GRACE[job.id], (
                        f"{job.id}: grace={job.misfire_grace_time}, "
                        f"ожидалось {EXPECTED_GRACE[job.id]}")
                    assert job.coalesce is True, f"{job.id}: coalesce потерян"
                    assert job.max_instances == 1, (
                        f"{job.id}: max_instances != 1")
                    if isinstance(job.trigger, IntervalTrigger):
                        interval = job.trigger.interval.total_seconds()
                        assert job.misfire_grace_time <= interval, (
                            f"{job.id}: grace больше интервала")
                    seen[job.id] = job.misfire_grace_time
        finally:
            for service in services:
                scheduler = getattr(service, "_scheduler", None)
                if scheduler is not None and scheduler.running:
                    scheduler.shutdown(wait=False)
        assert set(EXPECTED_GRACE) - set(seen) <= {"legacy_traits_parse_tick"}

    @pytest.mark.asyncio
    async def test_grace_is_clamped_to_effective_not_default_interval(
            self, monkeypatch):
        """F3: `grace ≤ интервал` держится и на не-дефолтных значениях.

        Hot/конструктор может задать интервал меньше константы grace
        (uptime 10 s, nostalgia 10 s, lore/dream 1 min, merge/WAL hot-доли);
        job обязан получить grace не больше фактического интервала.
        """
        uptime = UptimeHeartbeatService(
            pg=_FakePg(_CountingConn()), heartbeat_seconds=10)
        uptime.start()
        monkeypatch.setattr(
            "services.nostalgia_worker.hot.get",
            lambda key, default=None: 10
            if key == "limits.qnd_heartbeat_seconds" else default)
        nostalgia = NostalgiaWorker(MagicMock())
        nostalgia.start()
        monkeypatch.setattr(
            "services.lore_worker.hot.get",
            lambda key, default=None: True
            if key == "flags.lore_worker_enabled"
            else (1 if key == "limits.lore_tick_minutes" else default))
        monkeypatch.setattr("services.lore_worker._jitter", lambda _m: 0)
        lore = LoreWorker(MagicMock())
        await lore.start()
        monkeypatch.setattr(
            "services.dream_worker.hot.get",
            lambda key, default=None: 1
            if key == "memory.dream_tick_minutes" else default)
        monkeypatch.setattr("services.dream_worker._tick_jitter",
                            lambda _m: 0)
        dream = DreamWorker(MagicMock())
        dream.start()
        monkeypatch.setattr(
            "services.memory_maintenance.hot.get",
            lambda key, default=None: {
                "limits.graph_episode_merge_interval_days": 0.01,
                "limits.db_wal_checkpoint_hours": 0.05,
            }.get(key, default))
        maintenance = MemoryMaintenanceService(_NullDb(), None, None)
        maintenance.start()

        expected = {
            "uptime_heartbeat": 10,        # min(30, 10 s)
            "nostalgia_tick": 10,          # min(30, 10 s)
            "lore_worker_tick": 60,        # min(60, 1 min)
            "dream_tick": 60,              # min(300, 1 min)
            "deep_sleep_tick": 60,         # min(300, 1 min)
            "graph_episode_merge": 864,    # min(3600, 0.01 дня)
            "db_wal_checkpoint": 180,      # min(300, 0.05 ч)
        }
        services = [uptime, nostalgia, lore, dream, maintenance]
        seen: dict[str, int] = {}
        try:
            for service in services:
                for job in service._scheduler.get_jobs():
                    assert isinstance(job.trigger, IntervalTrigger)
                    interval = job.trigger.interval.total_seconds()
                    assert job.misfire_grace_time <= interval, (
                        f"{job.id}: grace={job.misfire_grace_time} > "
                        f"interval={interval}")
                    if job.id in expected:
                        assert job.misfire_grace_time == expected[job.id], (
                            f"{job.id}: grace={job.misfire_grace_time}, "
                            f"ожидалось {expected[job.id]}")
                        seen[job.id] = job.misfire_grace_time
        finally:
            for service in services:
                scheduler = getattr(service, "_scheduler", None)
                if scheduler is not None and scheduler.running:
                    scheduler.shutdown(wait=False)
        assert set(expected) <= set(seen), set(expected) - set(seen)

    def test_every_add_job_call_declares_explicit_misfire_grace(self):
        """Статический контракт: `add_job` без `misfire_grace_time` в
        `services/*.py` — регрессия к заводскому 1 s."""
        missing: list[str] = []
        for path in sorted((ROOT / "services").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "add_job"):
                    continue
                keywords = {kw.arg for kw in node.keywords}
                if "misfire_grace_time" not in keywords:
                    missing.append(f"{path.name}:{node.lineno}")
        assert missing == [], (
            "add_job без explicit misfire_grace_time: " + ", ".join(missing))
