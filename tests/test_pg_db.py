"""Epic 85 (T-612/T-635) — тесты services/pg_db.py (84.3/84.14.1).

DoD: DDL идемпотентен (повторный запуск без ошибок); КРИТИЧНЫЕ telegram_id
засеяны; сид ролей v2 (permissions-объект '{}' + wildcard-админ); стартовый
bot_settings по каталогу (ON CONFLICT DO NOTHING, без секретов). Пул — мок
(реального PG на деве нет): все запросы записываются, ничего не выполняется.
"""
import json
import logging

import pytest

from services import pg_db as pg_mod
from services.pg_db import (
    DDL_STATEMENTS,
    DEFAULT_ADMINS,
    DEFAULT_ROLES,
    PgDatabase,
    SEED_CATEGORIES,
    coerce_catalog_value,
)
from services.param_catalog import REGISTRY, get


class _FakeConn:
    def __init__(self, execute_result: str = "INSERT 0 1"):
        self.queries: list[tuple[str, tuple]] = []
        self._execute_result = execute_result

    async def execute(self, sql: str, *args):
        self.queries.append((sql, tuple(args)))
        return self._execute_result

    async def fetch(self, sql: str, *args):
        return []


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn
        self.closed = False

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
        self.closed = True


@pytest.fixture
def fake_pool():
    conn = _FakeConn()
    return conn, _FakePool(conn)


def _joined_ddl() -> str:
    return " ".join(DDL_STATEMENTS)


class TestDdl:
    def test_tables_created_idempotently(self):
        ddl = _joined_ddl()
        assert "CREATE TABLE IF NOT EXISTS bot_settings" in ddl
        assert "CREATE TABLE IF NOT EXISTS bot_roles" in ddl
        assert "CREATE TABLE IF NOT EXISTS bot_admins" in ddl

    def test_permissions_jsonb_object_v2(self):
        # 84.14.1: DEFAULT '{}' (вместо '[]' из 84.3)
        roles_ddl = next(s for s in DDL_STATEMENTS if "bot_roles" in s)
        assert "permissions JSONB NOT NULL DEFAULT '{}'" in roles_ddl

    def test_indexes(self):
        ddl = _joined_ddl()
        assert "idx_bot_settings_category" in ddl
        assert "idx_bot_admins_role" in ddl

    def test_bot_admins_fk_restrict(self):
        admins_ddl = next(s for s in DDL_STATEMENTS if "bot_admins" in s)
        assert "REFERENCES bot_roles (role_name)" in admins_ddl
        assert "ON DELETE RESTRICT" in admins_ddl

    @pytest.mark.asyncio
    async def test_init_twice_no_errors(self, fake_pool):
        conn, pool = fake_pool
        db = PgDatabase(pool=pool)
        await db.connect()
        await db.init()
        await db.init()          # идемпотентность: повтор без ошибок
        create_tables = [q for q in conn.queries
                         if "CREATE TABLE" in q[0]]
        # 4 таблицы базовых + 4 таблицы лора чатов (раунд 7, T-771) × 2 запуска
        assert len(create_tables) == 8 * 2

    @pytest.mark.asyncio
    async def test_init_without_seed_settings_no_settings_insert(self, fake_pool):
        conn, pool = fake_pool
        db = PgDatabase(pool=pool)
        await db.connect()
        await db.init(seed_settings=False)
        assert not any("bot_settings" in q[0] and "INSERT" in q[0]
                       for q in conn.queries)


class TestRoleSeeds:
    """84.14.3: сид v2 — admin wildcard, moderator limits+control, user {}."""

    def test_roles_v2(self):
        by_name = {r["role_name"]: r for r in DEFAULT_ROLES}
        assert set(by_name) == {"admin", "moderator", "user"}
        assert by_name["admin"]["permissions"] == {"wildcard": True}
        mod = by_name["moderator"]["permissions"]
        assert mod["sections"] == ["limits"]
        assert mod["actions"] == ["control.restart", "control.stop",
                                  "control.start"]
        assert by_name["user"]["permissions"] == {}
        for role in DEFAULT_ROLES:
            assert role["is_custom"] is False

    def test_critical_telegram_ids(self):
        admins = dict(DEFAULT_ADMINS)
        assert admins == {
            5885953495: "admin",
            1313107079: "moderator",
            134812796: "moderator",
        }

    @pytest.mark.asyncio
    async def test_seed_sql_conflict_do_nothing(self, fake_pool):
        conn, pool = fake_pool
        db = PgDatabase(pool=pool)
        await db.connect()
        await db.init()
        insert_sqls = [q[0] for q in conn.queries if "INSERT" in q[0]]
        assert insert_sqls
        assert all("ON CONFLICT" in s for s in insert_sqls)
        role_inserts = [q for q in conn.queries
                        if "INSERT" in q[0] and "bot_roles" in q[0]]
        assert len(role_inserts) == 3
        admin_inserts = [q for q in conn.queries
                         if "INSERT" in q[0] and "bot_admins" in q[0]]
        assert len(admin_inserts) == 3
        # КРИТИЧНЫЕ telegram_id переданы как параметры
        telegram_ids = {a[1][0] for a in admin_inserts}
        assert telegram_ids == {5885953495, 1313107079, 134812796}


class TestSettingsSeed:
    """84.12.3 belt-and-suspenders: дефолты БЕЗ секретов, DO NOTHING."""

    @staticmethod
    def _settings_inserts(conn):
        return [q for q in conn.queries
                if "INSERT" in q[0] and "bot_settings" in q[0]]

    @pytest.mark.asyncio
    async def test_no_secret_values_seeded(self, fake_pool):
        conn, pool = fake_pool
        db = PgDatabase(pool=pool)
        await db.connect()
        await db.init()
        seeded_keys = {q[1][0] for q in self._settings_inserts(conn)}
        secret_keys = {s.pg_key for s in REGISTRY.values() if s.secret}
        assert seeded_keys.isdisjoint(secret_keys)

    @pytest.mark.asyncio
    async def test_seeded_categories_only(self, fake_pool):
        conn, pool = fake_pool
        db = PgDatabase(pool=pool)
        await db.connect()
        await db.init()
        for sql, args in self._settings_inserts(conn):
            assert args[2] in SEED_CATEGORIES

    @pytest.mark.asyncio
    async def test_prompts_seeded_from_code_canon(self, fake_pool):
        conn, pool = fake_pool
        db = PgDatabase(pool=pool)
        await db.connect()
        await db.init()
        prompt_rows = {q[1][0]: json.loads(q[1][1])
                       for q in self._settings_inserts(conn)
                       if q[1][2] == "prompts"}
        assert "prompts.factcheck_system_prompt" in prompt_rows
        assert "провер" in prompt_rows["prompts.factcheck_system_prompt"].lower() \
            or "факт" in prompt_rows["prompts.factcheck_system_prompt"].lower()

    @pytest.mark.asyncio
    async def test_values_json_serializable(self, fake_pool):
        conn, pool = fake_pool
        db = PgDatabase(pool=pool)
        await db.connect()
        await db.init()
        for sql, args in self._settings_inserts(conn):
            json.loads(args[1])  # валидный JSON


class TestCoerceCatalogValue:
    def test_tuple_to_list(self):
        from services.param_catalog import REGISTRY
        spec = next(s for s in REGISTRY.values()
                    if s.settings_field == "GOODMORNING_TARGET_CHAT_IDS")
        assert coerce_catalog_value(spec, (1, 2)) == [1, 2]

    def test_json_string_parsed(self):
        spec = next(s for s in REGISTRY.values()
                    if s.settings_field == "SUMMARY_ALIASES")
        assert coerce_catalog_value(spec, '{"1": "а"}') == {"1": "а"}

    def test_json_bad_string_kept(self):
        spec = next(s for s in REGISTRY.values()
                    if s.settings_field == "SUMMARY_ALIASES")
        assert coerce_catalog_value(spec, "") == ""

    def test_primitives(self):
        assert coerce_catalog_value(get("SLAVIK_USER_ID"), "5") == 5
        assert coerce_catalog_value(get("SUMMARY_WINDOW_HOURS"), "6") == 6.0
        assert coerce_catalog_value(get("SUMMARY_ENABLED"), 0) is False
        assert coerce_catalog_value(get("LLM_BASE_URL"), "https://x") \
            == "https://x"
        assert coerce_catalog_value(get("SUMMARY_ENABLED"), None) is None

    def test_str_type_int_passthrough(self):
        # str-тип с не-str значением — как есть (JSON-сериализуемое)
        assert coerce_catalog_value(get("LLM_BASE_URL"), 42) == 42

    def test_json_dict_passthrough(self):
        spec = next(s for s in REGISTRY.values()
                    if s.settings_field == "SUMMARY_ALIASES")
        assert coerce_catalog_value(spec, {"1": "а"}) == {"1": "а"}


class TestConnectDegradation:
    @pytest.mark.asyncio
    async def test_no_dsn_no_pool_init_skips(self, monkeypatch, caplog):
        monkeypatch.delenv("POSTGRES_DSN", raising=False)
        db = PgDatabase(dsn=None)
        await db.connect()
        assert db.pool is None
        await db.init()
        assert "init skipped" in caplog.text

    @pytest.mark.asyncio
    async def test_connect_creates_pool(self, monkeypatch):
        from unittest.mock import AsyncMock
        fake_pool = object()
        create_pool = AsyncMock(return_value=fake_pool)
        monkeypatch.setattr(pg_mod.asyncpg, "create_pool", create_pool)
        db = PgDatabase(dsn="postgresql://u:p@127.0.0.1/x")
        await db.connect()
        assert db.pool is fake_pool
        kwargs = create_pool.await_args.kwargs
        assert kwargs["min_size"] == 1
        assert kwargs["max_size"] == 10
        assert kwargs["command_timeout"] == 10
        # ПРОД-ИНЦИДЕНТ (A): init-колбэк с json/jsonb-кодеками
        assert callable(kwargs["init"])


class TestJsonCodecs:
    """ПРОД-ИНЦИДЕНТ (A): json/jsonb-кодеки на каждом соединении пула."""

    def test_encoder_idempotent_for_json_strings(self):
        """str (уже JSON, напр. json.dumps в INSERT) проходит КАК ЕСТЬ —
        миграция/сиды не задваивают кавычки; объекты сериализуются."""
        assert pg_mod._json_encoder('{"a": 1}') == '{"a": 1}'
        assert pg_mod._json_encoder("plain") == "plain"
        assert pg_mod._json_encoder({"a": 1}) == '{"a": 1}'
        assert pg_mod._json_encoder(42) == "42"

    @pytest.mark.asyncio
    async def test_init_connection_registers_codecs(self):
        from unittest.mock import AsyncMock
        conn = AsyncMock()
        await pg_mod._init_connection(conn)
        assert conn.set_type_codec.await_count == 2
        calls = conn.set_type_codec.await_args_list
        for i, codec in enumerate(("json", "jsonb")):
            args, kwargs = calls[i]
            assert args[0] == codec
            assert kwargs["encoder"] is pg_mod._json_encoder
            assert kwargs["decoder"].__name__ == "loads"
            assert kwargs["schema"] == "pg_catalog"

    def test_dsn_property(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_DSN", "postgresql://u:p@h/db")
        assert PgDatabase().dsn == "postgresql://u:p@h/db"
        assert PgDatabase(dsn="x").dsn == "x"

    @pytest.mark.asyncio
    async def test_close_with_pool(self, fake_pool):
        conn, pool = fake_pool
        db = PgDatabase(pool=pool)
        await db.close()
        assert pool.closed
        assert db.pool is None

    @pytest.mark.asyncio
    async def test_bad_code_source_warns_and_continues(self, monkeypatch,
                                                       fake_pool, caplog):
        conn, pool = fake_pool
        db = PgDatabase(pool=pool)

        def _boom(source):
            raise ImportError("no module")

        monkeypatch.setattr(pg_mod, "resolve_code_source", _boom)
        await db.connect()
        with caplog.at_level(logging.WARNING):
            await db.init()
        assert any("code_source не резолвится" in r.message
                   for r in caplog.records)
        # остальной сид не пострадал
        assert any("bot_settings" in q[0] for q in conn.queries)
