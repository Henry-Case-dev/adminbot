"""Epic 85 (T-637) — тесты scripts/migrate_env_to_pg.py (84.12.2).

DoD 84.16.2 п.11: dry-run без записи; идемпотентность (повтор без --force —
no-op); --force перезаписывает; --only-category/--exclude фильтруют; секреты
НЕ печатаются (маскировка R17); отчёт по категориям. Пул — мок.
"""
import argparse
import dataclasses
import json
import types

import pytest

from scripts.migrate_env_to_pg import (
    UPSERT_DO_NOTHING,
    UPSERT_FORCE,
    _build_plan,
    _inserted_count,
    _masked,
    _parse_args,
    _run,
)

from config.settings import settings


def _fake_settings(**overrides) -> types.SimpleNamespace:
    """Снапшот Settings с переопределёнными полями (settings — frozen)."""
    values = {f.name: getattr(settings, f.name)
              for f in dataclasses.fields(type(settings))}
    values.update(overrides)
    return types.SimpleNamespace(**values)


class _FakeConn:
    def __init__(self, results=None):
        self.queries: list[tuple[str, tuple]] = []
        self._results = iter(results or ["INSERT 0 1"])

    async def execute(self, sql: str, *args):
        self.queries.append((sql, tuple(args)))
        return next(self._results, "INSERT 0 1")


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self):
                return self._pool._conn

            async def __aexit__(self, *exc):
                return False

        cm = _CM()
        cm._pool = self
        return cm

    async def close(self):
        pass


class _FakePg:
    def __init__(self, pool=None):
        self._pool = pool

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        assert seed_settings is False  # миграция ДО старта: сид не мешает env

    async def close(self):
        pass


def _plan_row(plan, pg_key):
    return next(r for r in plan if r["pg_key"] == pg_key)


class TestArgParsing:
    def test_defaults(self):
        args = _parse_args([])
        assert args.env_file == ".env"
        assert args.dry_run is False
        assert args.force is False
        assert args.only_category == ""
        assert args.exclude_keys == ""

    def test_flags(self):
        args = _parse_args(["--env-file", "x.env", "--dry-run", "--force",
                            "--only-category", "limits,keys",
                            "--exclude-keys", "summary_,chat_"])
        assert args.env_file == "x.env"
        assert args.dry_run and args.force
        assert args.only_category == "limits,keys"
        assert args.exclude_keys == "summary_,chat_"


class TestBuildPlan:
    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("SEARCH_MAX_SYMBOLS", "12345")
        fake = _fake_settings(SEARCH_MAX_SYMBOLS=12345)
        plan = _build_plan(fake, _parse_args([]))
        row = _plan_row(plan, "limits.search_max_symbols")
        assert row["value"] == 12345
        assert row["source"] == "env"

    def test_default_source(self, monkeypatch):
        monkeypatch.delenv("FACTCHECK_MAX_SYMBOLS", raising=False)
        plan = _build_plan(settings, _parse_args([]))
        row = _plan_row(plan, "limits.factcheck_max_symbols")
        assert row["source"] == "default"
        assert row["value"] == settings.FACTCHECK_MAX_SYMBOLS

    def test_only_category_filter(self):
        plan = _build_plan(settings, _parse_args(["--only-category", "keys"]))
        assert plan
        assert {r["category"] for r in plan} == {"keys"}

    def test_exclude_keys_filter(self):
        plan = _build_plan(settings, _parse_args(["--exclude-keys", "summary_"]))
        assert not any(r["pg_key"].startswith("limits.summary_")
                       or (r["env_name"] or "").startswith("summary_")
                       for r in plan)
        assert any("summary" not in r["pg_key"] for r in plan)

    def test_no_infra_and_no_prompts_in_plan(self):
        plan = _build_plan(settings, _parse_args([]))
        keys = {r["pg_key"] for r in plan}
        assert not any(k.startswith("prompts.") for k in keys)
        assert not any(k.startswith("content.") for k in keys)
        assert "api_token" not in keys

    def test_secret_values_in_plan_but_masked_in_output(self):
        plan = _build_plan(settings, _parse_args([]))
        key_row = _plan_row(plan, "keys.groq_api_key")
        assert key_row["secret"] is True
        assert _masked(key_row) in ("configured", "empty")
        assert _masked(key_row) != key_row["value"]


class TestMasking:
    def test_secret_never_printed(self):
        row = {"value": "sk-super-secret", "secret": True}
        assert "super" not in _masked(row)
        row = {"value": "", "secret": True}
        assert _masked(row) == "empty"

    def test_long_values_truncated(self):
        row = {"value": "a" * 100, "secret": False}
        masked = _masked(row)
        assert len(masked) <= 62
        assert masked.endswith("...")

    def test_short_values_as_json(self):
        row = {"value": 42, "secret": False}
        assert _masked(row) == "42"


class TestUpsertSql:
    def test_do_nothing_idempotent(self):
        assert "ON CONFLICT (key) DO NOTHING" in UPSERT_DO_NOTHING
        assert "DO UPDATE" not in UPSERT_DO_NOTHING

    def test_force_overwrites(self):
        assert "ON CONFLICT (key) DO UPDATE" in UPSERT_FORCE
        assert "updated_at = now()" in UPSERT_FORCE

    def test_inserted_count_strict_parsing(self):
        """F17: строгий разбор «INSERT 0 n» — никакого split()[-1]."""
        assert _inserted_count("INSERT 0 1") is True
        assert _inserted_count("INSERT 0 0") is False
        assert _inserted_count("МУСОР 1") is False
        assert _inserted_count(None) is False
        assert _inserted_count("") is False


class TestRunDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_does_not_touch_db(self, monkeypatch):
        class _BoomPg:
            def __init__(self, *a, **kw):
                raise AssertionError("dry-run не должен ходить в БД")

        monkeypatch.setattr("services.pg_db.PgDatabase", _BoomPg)
        code = await _run(["--dry-run", "--only-category", "keys"])
        assert code == 0

    @pytest.mark.asyncio
    async def test_missing_env_file_uses_defaults(self, monkeypatch, caplog):
        import logging

        class _BoomPg:
            def __init__(self, *a, **kw):
                raise AssertionError("dry-run не должен ходить в БД")

        monkeypatch.setattr("services.pg_db.PgDatabase", _BoomPg)
        with caplog.at_level(logging.WARNING):
            code = await _run(["--dry-run", "--env-file",
                               "no_such_env_file.env",
                               "--only-category", "keys"])
        assert code == 0
        assert any("env-файл не найден" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_pool_none_returns_1(self, monkeypatch):
        """Без dry-run: PgDatabase без пула → экспорт невозможен, exit 1."""
        monkeypatch.setattr("services.pg_db.PgDatabase",
                            lambda *a, **kw: _FakePg(pool=None))
        code = await _run(["--only-category", "keys"])
        assert code == 1

    @pytest.mark.asyncio
    async def test_run_created_and_idempotent_skip(self, monkeypatch):
        conn = _FakeConn(results=["INSERT 0 1"])
        pool = _FakePool(conn)
        monkeypatch.setattr("services.pg_db.PgDatabase",
                            lambda *a, **kw: _FakePg(pool=pool))

        code1 = await _run(["--only-category", "keys"])
        assert code1 == 0
        inserts1 = [q for q in conn.queries if "bot_settings" in q[0]]
        assert len(inserts1) == 16  # 16 ключей категории keys
        assert all("DO NOTHING" in q[0] for q in inserts1)

        # повторный запуск БЕЗ --force: все 16 уже существуют → skipped
        conn2 = _FakeConn(results=["INSERT 0 0"])
        pool2 = _FakePool(conn2)
        monkeypatch.setattr("services.pg_db.PgDatabase",
                            lambda *a, **kw: _FakePg(pool=pool2))
        code2 = await _run(["--only-category", "keys"])
        assert code2 == 0
        assert len(conn2.queries) == 16  # DO NOTHING — но без дублей

    @pytest.mark.asyncio
    async def test_force_uses_update_sql(self, monkeypatch):
        conn = _FakeConn(results=["INSERT 0 1"])
        monkeypatch.setattr("services.pg_db.PgDatabase",
                            lambda *a, **kw: _FakePg(pool=_FakePool(conn)))
        await _run(["--force", "--only-category", "keys"])
        inserts = [q for q in conn.queries if "bot_settings" in q[0]]
        assert inserts and all("DO UPDATE" in q[0] for q in inserts)

    @pytest.mark.asyncio
    async def test_force_logs_updated_by(self, monkeypatch, caplog):
        """F20: --force перезаписи логируются с источником (host/user)."""
        import logging

        conn = _FakeConn(results=["INSERT 0 1"])
        monkeypatch.setattr("services.pg_db.PgDatabase",
                            lambda *a, **kw: _FakePg(pool=_FakePool(conn)))
        with caplog.at_level(logging.INFO):
            await _run(["--force", "--only-category", "keys"])
        force_logs = [r for r in caplog.records
                      if "force rewrite" in r.message]
        assert force_logs
        assert "updated_by=" in force_logs[0].message
        assert "@" in force_logs[0].message   # user@host

    @pytest.mark.asyncio
    async def test_values_are_json(self, monkeypatch):
        conn = _FakeConn(results=["INSERT 0 1"])
        monkeypatch.setattr("services.pg_db.PgDatabase",
                            lambda *a, **kw: _FakePg(pool=_FakePool(conn)))
        await _run(["--only-category", "keys"])
        for _, args in conn.queries:
            if "bot_settings" in _:
                json.loads(args[1])
