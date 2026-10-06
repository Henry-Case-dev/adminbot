"""T-5150r — старт миграционной цепочки: наблюдаемость + устойчивость DDL-окна.

Прод-инцидент 2.58.64 (mca-20 retry): рестарт 12:19:37 UTC → backup-guard
создал pre_migration_20261006_121956.db, НО v33 не применена (user_version
32, book33=0) и веб-слой не поднялся (healthz 502 x8) при живом процессе.
Механизм окна «guard → DDL»: прод-старт часами парковался между backup-guard
(VACUUM INTO 1.3GB + read-back) и шагом v33 без единого лога, а любой
внешний держатель write-лока ронял бы DDL через 5с (`database is locked`).

Покрытие:
  * полный стартовый след guard→DDL→book (log-пин: start / guard start+done /
    applying retry / applied / complete) — на retry-деплое замирание видно
    по логу без фильтров;
  * DDL-окно: busy_timeout 30с на время `_run_migrations` — конкурент,
    держащий write-лок дольше базовых 5с, не роняет старт (v33 применяется);
  * bounded retry шага на `database is locked` (шаг идемпотентен по
    контракту mca-14 — повтор no-op);
  * контрфакт: без механизма (окно 0.8с, retries=0) тот же лок = падение
    старта — документирует класс отказа T-5150;
  * prod-retry путь: БД user_version=32 → v33 применяется ровно один раз
    (guard + book + таблицы/индексы), повтор — no-op;
  * старт-порядок: миграции до воркеров/веб-слоя (пин bot.py — порядок
    идентичен здоровому d298f1f/2.58.63; 968b049 bot.py не менял).
"""
import asyncio
import logging
import sqlite3
import threading
import time
from pathlib import Path

import aiosqlite
import pytest

import services.database as dbmod
import services.memory_backup as memory_backup_mod
from services.database import DatabaseService, _SCHEMA_MIGRATIONS_DDL

BOT_PY = Path(__file__).resolve().parent.parent / "bot.py"


async def _noop_backup(db, *, target_version=None):
    return None


@pytest.fixture
def fast_guard(monkeypatch):
    """Backup-guard no-op: лок-конкуренты не должны ждать VACUUM копию."""
    monkeypatch.setattr(memory_backup_mod, "migration_backup", _noop_backup)


def _make_v32_db(path: Path) -> None:
    """Прод-подобная БД v32: схема baseline + user_version=32 + книга с
    применённой v32 (на проде книга существует с эпохи v13; baseline-ветка
    раннера не срабатывает — первый WRITE в раннере это сам шаг v33)."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(DatabaseService._SCHEMA_SQL)
        conn.execute(_SCHEMA_MIGRATIONS_DDL)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at, "
            "checksum) VALUES (32, 'media_vision', strftime('%s','now'), '')")
        conn.execute("PRAGMA user_version = 32")
        conn.commit()
    finally:
        conn.close()


def _hold_write_lock(path: Path, hold_seconds: float,
                     acquired: "threading.Event") -> None:
    """Внешний конкурент: держит SQLite write-лок (BEGIN IMMEDIATE)."""
    conn = sqlite3.connect(str(path), timeout=1.0)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO channel_state (key, value) "
                     "VALUES ('t5150_probe', 'x')")
        acquired.set()             # лок реально удерживается
        time.sleep(hold_seconds)
        conn.commit()
    finally:
        conn.close()


async def _open_prelude(svc: DatabaseService) -> None:
    """Минимальный прелюд `initialize()` (connect + WAL + busy 5с)."""
    svc.db = await aiosqlite.connect(str(svc.db_path))
    svc.db.row_factory = aiosqlite.Row
    await svc.db.execute("PRAGMA journal_mode=WAL")
    await svc.db.execute(
        f"PRAGMA busy_timeout = {dbmod._BUSY_TIMEOUT_MS}")


async def _run_with_competitor(svc: DatabaseService, hold: float) -> None:
    acquired = threading.Event()
    holder = asyncio.create_task(asyncio.to_thread(
        _hold_write_lock, Path(svc.db_path), hold, acquired))
    await asyncio.to_thread(acquired.wait)   # детерминизм: лок ДО раннера
    try:
        await svc._run_migrations()
    finally:
        await holder


# ── окно DDL + retry ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_ddl_window_survives_lock_longer_than_base_5s(
        tmp_path, fast_guard):
    """busy_timeout 30с: конкурент держит лок 6с (> старых 5с) — старт
    не падает, v33 применяется (окно DDL поглощает ожидание без retry)."""
    path = tmp_path / "t5150_window.db"
    _make_v32_db(path)
    svc = DatabaseService(str(path))
    await _open_prelude(svc)
    try:
        await _run_with_competitor(svc, hold=6.0)
        cur = await svc.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 33
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_b_step_retry_recovers_after_locked(tmp_path, fast_guard,
                                                  monkeypatch, caplog):
    """bounded retry: короткое окно 0.8с + лок 2.2с → первый DDL падает
    `database is locked`, шаг перезапускается (идемпотентен) и доходит."""
    monkeypatch.setattr(dbmod, "_MIGRATION_BUSY_TIMEOUT_MS", 800)
    monkeypatch.setattr(dbmod, "_MIGRATION_LOCK_RETRIES", 3)
    monkeypatch.setattr(dbmod, "_MIGRATION_LOCK_BACKOFF_S", 0.05)
    path = tmp_path / "t5150_retry.db"
    _make_v32_db(path)
    svc = DatabaseService(str(path))
    await _open_prelude(svc)
    try:
        with caplog.at_level(logging.INFO, logger="services.database"):
            await _run_with_competitor(svc, hold=2.2)
        cur = await svc.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 33
        assert "retry 1/3" in caplog.text
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_c_without_mechanism_lock_kills_startup(tmp_path, fast_guard,
                                                      monkeypatch):
    """Контрфакт T-5150: тот же лок без окна/retry → `database is locked`
    наружу (класс отказа: старт падает, systemd рестарт-петля)."""
    monkeypatch.setattr(dbmod, "_MIGRATION_BUSY_TIMEOUT_MS", 800)
    monkeypatch.setattr(dbmod, "_MIGRATION_LOCK_RETRIES", 0)
    path = tmp_path / "t5150_nomech.db"
    _make_v32_db(path)
    svc = DatabaseService(str(path))
    await _open_prelude(svc)
    try:
        with pytest.raises(aiosqlite.OperationalError, match="locked"):
            await _run_with_competitor(svc, hold=2.2)
    finally:
        await svc.close()


# ── полный стартовый след (требование DevOps на retry) ──────────────────────

@pytest.mark.asyncio
async def test_d_migration_chain_full_log_trail(tmp_path, caplog):
    """guard→DDL→book: каждая фаза оставляет INFO-точку ДО/ПОСЛЕ с
    длительностью — замирание между фазами видно по стартовому логу."""
    path = tmp_path / "t5150_trail.db"
    _make_v32_db(path)
    svc = DatabaseService(str(path))
    with caplog.at_level(logging.INFO, logger="services.database"):
        await svc.initialize()
    try:
        text = caplog.text
        assert "migrations: start" in text
        assert "current user_version=32" in text
        assert "pending=[33]" in text
        assert "migration backup-guard: start" in text
        assert "migration backup-guard: done in" in text
        assert "migration v33 applied in" in text
        assert "migrations: complete | user_version=33" in text
    finally:
        await svc.close()


# ── prod-retry путь: v32 → v33 ровно один раз, повтор no-op ─────────────────

@pytest.mark.asyncio
async def test_e_v32_db_applies_v33_once_with_guard(tmp_path, caplog):
    """Прод-сценарий retry: БД на v32 (книги нет) → guard + v33 одним шагом;
    таблицы/индексы на месте; повторный initialize — no-op (ровно одна
    строка v33 в книге, user_version не скачет)."""
    path = tmp_path / "t5150_prodretry.db"
    _make_v32_db(path)
    svc = DatabaseService(str(path))
    with caplog.at_level(logging.INFO, logger="services.database"):
        await svc.initialize()
    try:
        cur = await svc.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 33
        cur = await svc.db.execute(
            "SELECT version, name FROM schema_migrations "
            "WHERE version IN (32, 33) ORDER BY version")
        rows = [tuple(r) for r in await cur.fetchall()]
        assert rows == [(32, "media_vision"), (33, "factcheck_temporal")]
        for table in ("mca_factcheck_runs", "mca_factcheck_evidence"):
            cur = await svc.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name=?", (table,))
            assert await cur.fetchone() is not None
        cur = await svc.db.execute(
            "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_mca_factcheck%'")
        assert (await cur.fetchone())["c"] == 3
    finally:
        await svc.close()

    caplog.clear()
    svc2 = DatabaseService(str(path))
    with caplog.at_level(logging.INFO, logger="services.database"):
        await svc2.initialize()
    try:
        cur = await svc2.db.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations WHERE version=33")
        assert (await cur.fetchone())["c"] == 1
        cur = await svc2.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 33
        assert "migration v33 applied" not in caplog.text   # повтор — no-op
    finally:
        await svc2.close()


# ── старт-порядок: миграции до воркеров/веба (пин) ──────────────────────────

def test_f_startup_order_migrations_before_workers_and_web():
    """Пин порядка (ident 2.58.63 d298f1f; 968b049 bot.py не менял):
    `db.initialize()` (внутри on_startup, до возврата — воркеры) строго
    раньше `_vision_worker.start()`, а `await on_startup()` — раньше
    uvicorn-сервера. Иначе async-воркеры/веб стартуют на недомигрированной
    схеме (гипотеза T-5150 «старт-порядок» — зафиксирована как регресс)."""
    src = BOT_PY.read_text(encoding="utf-8")
    i_init = src.index("await db.initialize()")
    i_vision = src.index("_vision_worker.start()")
    i_onstartup = src.index("await on_startup()")
    i_uvicorn = src.index("server = uvicorn.Server(")
    i_serve = src.index("await server.serve()")
    assert i_init < i_vision, "vision-воркер должен стартовать после БД"
    assert i_onstartup < i_uvicorn < i_serve, \
        "веб-слой поднимается после on_startup (миграции включительно)"
