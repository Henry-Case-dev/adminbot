"""EVOL-016 — интеграция книги схемы v39 (журнал промптов) в services/database.

Интеграционная заметка ``plans/features/evol/audit/w2a-evol016.md`` §4
(выполнение в services/database.py + services/pg_db.py):

  a. свежая SQLite-БД мигрирует до последней версии (шаг
     ``prompt_revision_journal_v39`` в книге ``schema_migrations``; текущая
     последняя — v40 (EVOL-014, соседний шаг), поэтому пины user_version = 40);
  b. существующая БД v38 доезжает до v39 аддитивно, данные не теряются
     (фикстура «эпохи v38»: раннер без шага 39 + строки со quote-метаданными);
  c. релизная политика работает через РЕАЛЬНЫЙ ``PgPromptJournal``:
     feature-detect ``default_journal`` находит журнал, полный
     ``apply_release`` (cutover) и рестарт-ноопас проходят на asyncpg-двойнике
     пула с диспетчеризацией по идентичности SQL-констант модуля
     (live-PG smoke — отдельная staging-задача, здесь не выполняется);
     попутный регресс-пин: ``_INSERT_ACTIVATION_SQL`` обязан возвращать
     ``RETURNING activation_id`` (fetchval-контракт);
  d. повторный прогон (рестарт) не меняет ничего (книга: ровно одна строка
     v39, шаг не переисполняется);
  e. PG-DDL журнала в ``DDL_STATEMENTS`` идемпотентен по тексту и дословно
     равен ``prompt_release_policy.JOURNAL_DDL``.

TEST-LIFECYCLE: CONTRACT owner=EVOL-016 (интеграционная заметка §4)
"""
from __future__ import annotations

import json
import logging

import pytest

from services import message_identity as _mi
from services import prompt_factory as pf
from services import prompt_registry as pr
from services import prompt_release_policy as prp
from services.database import DatabaseService, row_get

BLOCK = "summary.base.narrator"
PG_KEY = "prompts.summary_narrator_system_prompt"

MANUAL_TEXT = "РУЧНАЯ ПРАВКА владельца до первой заводской поставки.\n"


# ── a/d: свежая БД 0→39 + рестарт-идемпотентность ───────────────────────────

@pytest.mark.asyncio
async def test_fresh_db_migrates_0_to_39(tmp_path):
    svc = DatabaseService(str(tmp_path / "v39_fresh.db"))
    await svc.initialize()
    try:
        cur = await svc.db.execute("PRAGMA user_version")
        # Свежая БД доезжает до ПОСЛЕДНЕЙ версии схемы: v39 (эта полоса) +
        # v40 (EVOL-014, журнал квоты мемов — соседний шаг, не отменяет v39).
        assert (await cur.fetchone())[0] == 40
        book = await svc.db.execute(
            "SELECT name, checksum FROM schema_migrations WHERE version = 39")
        row = await book.fetchone()
        assert row is not None
        assert row["name"] == "prompt_revision_journal_v39"
        assert row["checksum"]
        # Данных в SQLite нет: таблицы журнала PG-only (книга схемы, как v35)
        cur = await svc.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND "
            "name IN ('prompt_revisions', 'prompt_activations')")
        assert await cur.fetchone() is None
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_v39_step_registered_in_runner(tmp_path):
    steps = {s.version: s.name for s in DatabaseService.migration_steps()}
    assert steps.get(39) == "prompt_revision_journal_v39"
    # v38 остался на месте (шаг-сосед EVOL-015 не тронут)
    assert steps.get(38) == "quote_metadata_v38"
    assert callable(DatabaseService._migrate_prompt_journal_v39)


@pytest.mark.asyncio
async def test_v39_restart_is_true_noop(tmp_path, caplog):
    path = str(tmp_path / "v39_noop.db")
    svc = DatabaseService(path)
    await svc.initialize()
    await svc.close()

    svc2 = DatabaseService(path)
    with caplog.at_level(logging.INFO, logger="services.database"):
        await svc2.initialize()
    try:
        cur = await svc2.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 40
        cur = await svc2.db.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations WHERE version = 39")
        assert (await cur.fetchone())["c"] == 1
        # шаг не переисполняется: ни строки "migration v39 applied"
        assert "migration v39 applied" not in caplog.text
    finally:
        await svc2.close()


# ── b: существующая v38-БД доезжает до v39 без потери данных ────────────────

class _V38EraService(DatabaseService):
    """Раннер эпохи v38: шаг 39 ещё не существует (симуляция апгрейда)."""

    @staticmethod
    def migration_steps():
        return [s for s in DatabaseService.migration_steps()
                if s.version < 39]


@pytest.mark.asyncio
async def test_v38_db_upgrades_to_v39_without_data_loss(tmp_path):
    path = str(tmp_path / "v38_upgrade.db")
    old = _V38EraService(path)
    await old.initialize()
    try:
        cur = await old.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 38
        await _mi.save_live_message(old, chat_id=100, user_id=1,
                                    text="до-v39-строка", tg_message_id=7)
        await old.db.execute(
            "UPDATE smart_messages SET quote_position = 5, "
            "quote_is_manual = 1, quote_entities = ? "
            "WHERE tg_message_id = 7",
            (json.dumps([{"type": "bold", "offset": 0, "length": 4}]),))
        await old.db.commit()
    finally:
        await old.close()

    svc = DatabaseService(path)
    await svc.initialize()
    try:
        cur = await svc.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 40
        book = await svc.db.execute(
            "SELECT name FROM schema_migrations WHERE version = 39")
        row = await book.fetchone()
        assert row is not None and row["name"] == "prompt_revision_journal_v39"
        # данные пережили апгрейд байт-в-байт (шаг v39 — только книга схемы)
        row = await svc.get_smart_message_by_tg_id(100, 7)
        assert row is not None
        assert row_get(row, "text") == "до-v39-строка"
        assert row_get(row, "quote_position") == 5
        assert row_get(row, "quote_is_manual") == 1
        assert row_get(row, "quote_entities") == json.dumps(
            [{"type": "bold", "offset": 0, "length": 4}])
    finally:
        await svc.close()


# ── e: PG-DDL журнала — дословно и идемпотентно ─────────────────────────────

def test_pg_journal_ddl_verbatim_and_idempotent():
    from services import pg_db
    journal = tuple(
        s for s in pg_db.DDL_STATEMENTS
        if "prompt_revisions" in s or "prompt_activations" in s)
    assert journal == prp.JOURNAL_DDL          # дословный перенос, порядок тот же
    assert len(journal) == 4                   # 2 таблицы + 2 индекса
    for stmt in journal:
        assert "IF NOT EXISTS" in stmt         # повтор PgDatabase.init — no-op
    joined = "\n".join(pg_db.DDL_STATEMENTS)
    assert joined.count(
        "CREATE TABLE IF NOT EXISTS prompt_revisions") == 1
    assert joined.count(
        "CREATE TABLE IF NOT EXISTS prompt_activations") == 1


# ── c: apply_release через реальный PgPromptJournal (asyncpg-двойник) ───────

class _MiniPgEngine:
    """Двойник сервера PG: исполняет КОНКРЕТНЫЕ SQL-константы модуля.

    Диспетчеризация по идентичности констант (не парсер SQL): журнал
    ревизий/активаций ведётся на списках строк, bot_settings — на dict.
    Незнакомый SQL — ошибка (строгий контракт: реальный путь ходит только
    по известным запросам). Live-PG smoke — отдельная staging-задача.
    """

    def __init__(self):
        self.revisions: list[dict] = []
        self.activations: list[dict] = []
        self.bot_settings: dict[str, str] = {}
        self.executed: list[str] = []
        self._activation_seq = 0
        self._ts_seq = 0

    def _next_ts(self) -> str:
        self._ts_seq += 1
        return f"2026-10-30T10:00:{self._ts_seq:02d}+00:00"

    async def execute(self, sql, *args):
        self.executed.append(sql)
        if sql in prp.JOURNAL_DDL:
            return "CREATE TABLE"
        if sql is prp.APPLY_LOCK_SQL:
            return None
        if sql is prp._INSERT_REVISION_SQL:
            (rid, bid, key, scope, chat, origin, sha, body, fac, compat,
             release, actor, reason, src_upd, created) = args
            if any(r["revision_id"] == rid for r in self.revisions):
                return "INSERT 0 0"            # ON CONFLICT DO NOTHING
            self.revisions.append(dict(
                revision_id=rid, block_id=bid, pg_key=key, scope=scope,
                chat_id=chat, origin=origin, content_sha12=sha, body=body,
                factory_revision=fac, schema_compat=compat,
                release_id=release, actor=actor, reason=reason,
                source_updated_at=src_upd, retired=False,
                created_at=created or self._next_ts()))
            return "INSERT 0 1"
        if sql is prp._UPSERT_BOT_SETTING_SQL:
            key, value, _category = args
            # jsonb round-trip: value #>> '{}' отдаёт исходный текст
            self.bot_settings[key] = json.loads(value)
            return "INSERT 0 1"
        if sql is prp._MARK_RETIRED_SQL:
            ids = set(args[0])
            n = 0
            for r in self.revisions:
                if r["block_id"] in ids and not r["retired"]:
                    r["retired"] = True
                    n += 1
            return f"UPDATE {n}"
        raise AssertionError(f"неизвестный SQL execute: {sql[:60]!r}")

    async def fetchval(self, sql, *args):
        if sql is prp._INSERT_ACTIVATION_SQL:
            (bid, scope, chat, rid, fac, kind, outcome, release, actor,
             detail) = args
            self._activation_seq += 1
            self.activations.append(dict(
                activation_id=self._activation_seq, block_id=bid,
                scope=scope, chat_id=chat, revision_id=rid,
                factory_revision_applied=fac, kind=kind, outcome=outcome,
                release_id=release, actor=actor, detail_code=detail))
            return self._activation_seq        # RETURNING activation_id
        if sql is prp._HAS_IMPORT_SQL:
            bid, scope, chat = args
            hit = any(r["block_id"] == bid and r["scope"] == scope
                      and r["chat_id"] == chat and r["origin"] == "legacy"
                      for r in self.revisions)
            return 1 if hit else None
        if sql is prp._HAS_CUTOVER_SQL:
            bid, scope, chat = args
            hit = any(a["block_id"] == bid and a["scope"] == scope
                      and a["chat_id"] == chat and a["kind"] == "legacy_import"
                      for a in self.activations)
            return 1 if hit else None
        raise AssertionError(f"неизвестный SQL fetchval: {sql[:60]!r}")

    async def fetchrow(self, sql, *args):
        if sql is prp._LAST_APPLIED_SQL:
            bid, scope, chat = args
            rows = [a for a in self.activations
                    if a["block_id"] == bid and a["scope"] == scope
                    and a["chat_id"] == chat
                    and a["outcome"] in ("applied", "skipped_same")]
            return rows[-1] if rows else None   # ORDER BY activation_id DESC LIMIT 1
        if sql is prp._GET_REVISION_SQL:
            rid = args[0]
            return next((r for r in self.revisions
                         if r["revision_id"] == rid), None)
        if sql is prp._SELECT_BOT_SETTING_SQL:
            key = args[0]
            if key not in self.bot_settings:
                return None
            return {"text": self.bot_settings[key]}
        raise AssertionError(f"неизвестный SQL fetchrow: {sql[:60]!r}")

    async def fetch(self, sql, *args):
        if sql is prp._KNOWN_BLOCK_IDS_SQL:
            return [{"block_id": b}
                    for b in {r["block_id"] for r in self.revisions}]
        if sql is prp._SELECT_CHAT_OVERRIDES_SQL:
            return []
        raise AssertionError(f"неизвестный SQL fetch: {sql[:60]!r}")

    def transaction(self):
        # Тестовый сценарий всегда завершается коммитом (rollback-семантика
        # пакета доказана MemoryPromptJournal-тестами транзакций).
        class _Tx:
            async def start(self):
                pass

            async def commit(self):
                pass

            async def rollback(self):
                pass

        return _Tx()


class _FakeAsyncpgConn:
    """Двойник asyncpg-коннекта (контракт PgPromptJournal._PgTx)."""

    def __init__(self, engine):
        self._engine = engine

    async def execute(self, sql, *args):
        return await self._engine.execute(sql, *args)

    async def fetchval(self, sql, *args):
        return await self._engine.fetchval(sql, *args)

    async def fetchrow(self, sql, *args):
        return await self._engine.fetchrow(sql, *args)

    async def fetch(self, sql, *args):
        return await self._engine.fetch(sql, *args)

    def transaction(self):
        return self._engine.transaction()


class _FakeAsyncpgPool:
    """__module__ = asyncpg.* — проходит feature-detect default_journal().

    Оба протокола asyncpg: ``await pool.acquire()`` (_PgTx) и
    ``async with pool.acquire()`` (ensure_journal/_run_on_conn).
    """

    __module__ = "asyncpg.pool"

    def __init__(self, engine):
        self._engine = engine

    def acquire(self):
        engine = self._engine

        class _Acquire:
            def __init__(self):
                self._conn = None

            def __await__(self):
                return self._create().__await__()

            async def _create(self):
                self._conn = _FakeAsyncpgConn(engine)
                return self._conn

            async def __aenter__(self):
                return await self._create()

            async def __aexit__(self, *exc):
                self._conn = None
                return False

        return _Acquire()

    async def release(self, conn):
        return None


class _PgCache:
    """Контракт ConfigCache (sync get / async set) + PG-пул."""

    def __init__(self, values=None, pool=None):
        self.pg_available = True
        self.pg = type("PgHandle", (), {"pool": pool})()
        self.values = dict(values or {})
        self.set_calls: list[tuple[str, object, str]] = []
        self._updated_at = "2026-10-29T10:00:00+00:00"

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category):
        self.set_calls.append((key, value, category))
        self.values[key] = value

    def get_updated_at(self, key):
        return self._updated_at


@pytest.fixture()
def registry_reset():
    """Сброс глобального состояния реестра после релизной проводки."""
    yield
    pr.set_release_policy_active(False)
    pr.set_retired_blocks(())
    pf._HISTORY_FROZEN = False
    pr.reset_cache()


@pytest.mark.asyncio
async def test_apply_release_real_pg_store_cutover_and_restart(
        registry_reset):
    # Регресс-пин попутного фикса: fetchval-контракт вставки активаций
    assert "RETURNING activation_id" in prp._INSERT_ACTIVATION_SQL

    engine = _MiniPgEngine()
    pool = _FakeAsyncpgPool(engine)
    cache = _PgCache({PG_KEY: MANUAL_TEXT}, pool=pool)

    # Feature-detect находит журнал (раньше честный no-op, теперь реальный путь)
    store = prp.default_journal(cache)
    assert isinstance(store, prp.PgPromptJournal)

    # Полная проводка БЕЗ явного store: default_journal → PgPromptJournal
    result = await prp.apply_release(
        cache, release_id=prp.CUTOVER_RELEASE_ID, blocks=[BLOCK])
    assert result["applied"] is True
    assert result["changed"] == 2            # снимок legacy + заводская

    # DDL журнала исполнен при первом ensure (идемпотентные выражения)
    assert engine.executed[:4] == list(prp.JOURNAL_DDL)

    # Журнал: снимок legacy → активация заводской (контракт §1.4)
    assert [(a["kind"], a["outcome"]) for a in engine.activations] == [
        ("legacy_import", "applied"), ("deploy_activate", "applied")]
    origins = [r["origin"] for r in engine.revisions]
    assert origins == ["legacy", "factory"]
    assert engine.revisions[0]["body"] == MANUAL_TEXT
    assert engine.revisions[1]["body"] == pr.factory_text(BLOCK)

    # Активное значение — заводской текст (upsert bot_settings в транзакции)
    assert engine.bot_settings[PG_KEY] == pr.factory_text(BLOCK)
    # память кэша обновлена из PG после коммита
    assert cache.values[PG_KEY] == pr.factory_text(BLOCK)
    assert cache.set_calls[-1][2] == "prompts"
    assert pr.release_policy_active() is True

    # Рестарт с той же меткой — истинный no-op (ни строки, ни записи)
    before = (len(engine.revisions), len(engine.activations))
    result2 = await prp.apply_release(
        cache, release_id=prp.CUTOVER_RELEASE_ID, blocks=[BLOCK])
    assert result2["applied"] is True
    rows = {(r.block_id, r.scope, r.chat_id): r for r in result2["results"]}
    assert rows[(BLOCK, "global", None)].action == "no_op"
    assert rows[(BLOCK, "global", None)].outcome == "skipped_same"
    assert (len(engine.revisions), len(engine.activations)) == before
