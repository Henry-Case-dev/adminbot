"""Epic 85 (T-613) — тесты services/config_cache.py (84.4).

DoD: get/set/upsert/reload/permissions; PG недоступен → init завершается с
WARNING и бот жив (R6, pg_available=False, set работает in-memory). Пул — мок.
"""
import asyncio
import json
import logging
import types

import pytest

from services.config_cache import ConfigCache
from services.permissions import Permissions


class _FakeConn:
    def __init__(self, settings_rows=(), role_rows=(), admin_rows=(),
                 execute_result="INSERT 0 1"):
        self.queries: list[tuple[str, tuple]] = []
        self._settings_rows = list(settings_rows)
        self._role_rows = list(role_rows)
        self._admin_rows = list(admin_rows)
        self.execute_result = execute_result

    async def execute(self, sql: str, *args):
        self.queries.append((sql, tuple(args)))
        # мутабельный фейк: reload после RBAC-операций видит изменения
        if "bot_admins" in sql:
            tg = args[0]
            self._admin_rows = [r for r in self._admin_rows
                                if r["telegram_id"] != tg]
            if "DELETE" not in sql and len(args) > 1:
                self._admin_rows.append(
                    {"telegram_id": tg, "role_name": args[1]})
        elif "bot_roles" in sql:
            name = args[0]
            self._role_rows = [r for r in self._role_rows
                               if r["role_name"] != name]
            if "DELETE" not in sql and len(args) > 1:
                self._role_rows.append({
                    "role_name": name, "permissions": json.loads(args[1]),
                    "is_custom": bool(args[2]) if len(args) > 2 else False})
        return self.execute_result

    async def fetch(self, sql: str, *args):
        self.queries.append((sql, tuple(args)))
        if "bot_settings" in sql:
            return self._settings_rows
        if "bot_roles" in sql:
            return self._role_rows
        if "bot_admins" in sql:
            return self._admin_rows
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


class _FakePg:
    """PgDatabase-мок: connect/init/close no-op, pool подменён."""

    def __init__(self, pool=None, fail_connect=False):
        self._pool = pool
        self._fail_connect = fail_connect
        self.closed = False
        self.connects = 0

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        self.connects += 1
        if self._fail_connect:
            raise ConnectionError("pg down")

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        self.closed = True


def _rows():
    settings = [
        {"key": "limits.search_max_symbols", "value": 8000, "category": "limits"},
        {"key": "flags.summary_enabled", "value": True, "category": "flags"},
        {"key": "keys.groq_api_key", "value": "sk-abc", "category": "keys"},
    ]
    roles = [
        {"role_name": "admin", "permissions": {"wildcard": True},
         "is_custom": False},
        {"role_name": "moderator",
         "permissions": {"sections": ["limits"],
                         "actions": ["control.restart", "control.stop",
                                     "control.start"]},
         "is_custom": False},
        {"role_name": "user", "permissions": {}, "is_custom": False},
    ]
    admins = [
        {"telegram_id": 5885953495, "role_name": "admin"},
        {"telegram_id": 1313107079, "role_name": "moderator"},
    ]
    return settings, roles, admins


class TestInitAndRead:
    @pytest.mark.asyncio
    async def test_init_loads_all(self):
        conn = _FakeConn(*_rows())
        cache = ConfigCache(pg=_FakePg(pool=_FakePool(conn)))
        await cache.init()
        assert cache.pg_available
        assert cache.get("limits.search_max_symbols") == 8000
        assert cache.get("missing.key") is None
        assert cache.get("missing.key", 42) == 42
        assert cache.get("flags.summary_enabled") is True

    @pytest.mark.asyncio
    async def test_get_all_snapshot(self):
        conn = _FakeConn(*_rows())
        cache = ConfigCache(pg=_FakePg(pool=_FakePool(conn)))
        await cache.init()
        all_values = cache.get_all()
        assert "keys.groq_api_key" in all_values
        assert "limits.search_max_symbols" in all_values
        assert "flags.summary_enabled" in all_values

    @pytest.mark.asyncio
    async def test_roles_and_permissions(self):
        conn = _FakeConn(*_rows())
        cache = ConfigCache(pg=_FakePg(pool=_FakePool(conn)))
        await cache.init()
        assert cache.get_role(5885953495) == "admin"
        assert cache.get_role(111) is None
        admin_perms = cache.get_permissions("admin")
        assert admin_perms is not None and admin_perms.wildcard
        mod_perms = cache.get_permissions_by_telegram_id(1313107079)
        assert mod_perms is not None
        assert "limits" in mod_perms.sections
        assert cache.get_permissions_by_telegram_id(999) is None
        assert cache.get_permissions("unknown") is None
        assert len(cache.roles()) == 3


class TestSetUpsertReload:
    @pytest.mark.asyncio
    async def test_set_updates_memory_and_db(self):
        conn = _FakeConn(*_rows())
        cache = ConfigCache(pg=_FakePg(pool=_FakePool(conn)))
        await cache.init()
        await cache.set("limits.search_max_symbols", 9000, "limits")
        assert cache.get("limits.search_max_symbols") == 9000
        upsert_sql = [q for q in conn.queries
                      if "bot_settings" in q[0] and "ON CONFLICT" in q[0]
                      and q[1] and q[1][0] == "limits.search_max_symbols"]
        assert len(upsert_sql) == 1
        sql, args = upsert_sql[0]
        assert args[0] == "limits.search_max_symbols"
        assert json.loads(args[1]) == 9000
        assert args[2] == "limits"

    @pytest.mark.asyncio
    async def test_upsert_alias(self):
        conn = _FakeConn(*_rows())
        cache = ConfigCache(pg=_FakePg(pool=_FakePool(conn)))
        await cache.init()
        await cache.upsert("flags.summary_enabled", False, "flags")
        assert cache.get("flags.summary_enabled") is False

    @pytest.mark.asyncio
    async def test_reload_refetches(self):
        conn = _FakeConn(*_rows())
        cache = ConfigCache(pg=_FakePg(pool=_FakePool(conn)))
        await cache.init()
        conn._settings_rows.append(
            {"key": "models.llm_model_name", "value": "m2",
             "category": "models"})
        await cache.reload()
        assert cache.get("models.llm_model_name") == "m2"

    @pytest.mark.asyncio
    async def test_concurrent_sets_serialized(self):
        conn = _FakeConn(*_rows())
        cache = ConfigCache(pg=_FakePg(pool=_FakePool(conn)))
        await cache.init()
        await asyncio.gather(
            *(cache.set(f"limits.k{i}", i, "limits") for i in range(20)))
        for i in range(20):
            assert cache.get(f"limits.k{i}") == i


class TestPgDownDegradation:
    """R6: PG недоступен → init с WARNING, бот жив, set — in-memory."""

    @pytest.mark.asyncio
    async def test_init_with_pg_down_does_not_raise(self, caplog):
        cache = ConfigCache(pg=_FakePg(fail_connect=True),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        assert not cache.pg_available
        assert cache.get("any.key") is None
        assert "PG недоступен" in caplog.text

    @pytest.mark.asyncio
    async def test_set_memory_only_when_pg_down(self, caplog):
        cache = ConfigCache(pg=_FakePg(fail_connect=True),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        with caplog.at_level(logging.DEBUG):
            await cache.set("limits.x", 5, "limits")
        assert cache.get("limits.x") == 5
        assert "in-memory only" in caplog.text

    @pytest.mark.asyncio
    async def test_reload_noop_when_pg_down(self, caplog):
        cache = ConfigCache(pg=_FakePg(fail_connect=True),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        await cache.reload()
        assert "no-op" in caplog.text

    @pytest.mark.asyncio
    async def test_close(self):
        pg = _FakePg(fail_connect=True)
        cache = ConfigCache(pg=pg, retry_attempts=1, retry_delay=0)
        await cache.init()
        await cache.close()
        assert pg.closed


class TestInfoSeed:
    """84.13.2 (T-638): content.info_how_it_works сидится из info_text.md
    при первом старте; существующее значение НЕ перезаписывается."""

    @pytest.mark.asyncio
    async def test_seed_from_file_when_missing(self, tmp_path, monkeypatch):
        info_file = tmp_path / "info_text.md"
        info_file.write_text("<h1>Сид из файла</h1>", encoding="utf-8")
        monkeypatch.setattr(
            "services.config_cache.settings",
            types.SimpleNamespace(INFO_TEXT_FILE=str(info_file),
                                  ADMIN_USER_ID=5885953495))
        conn = _FakeConn(*_rows())
        cache = ConfigCache(pg=_FakePg(pool=_FakePool(conn)),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        value = cache.get("content.info_how_it_works")
        assert isinstance(value, dict)
        assert value["html"] == "<h1>Сид из файла</h1>"
        assert value["updated_by"] == 5885953495
        assert value["updated_at"]

    @pytest.mark.asyncio
    async def test_existing_value_not_overwritten(self, tmp_path, monkeypatch):
        info_file = tmp_path / "info_text.md"
        info_file.write_text("<h1>НОВЫЙ файл</h1>", encoding="utf-8")
        monkeypatch.setattr(
            "services.config_cache.settings",
            types.SimpleNamespace(INFO_TEXT_FILE=str(info_file),
                                  ADMIN_USER_ID=5885953495))
        settings_rows, role_rows, admin_rows = _rows()
        settings_rows.append({
            "key": "content.info_how_it_works",
            "value": {"html": "<h1>ИЗ БД</h1>", "updated_at": "t",
                      "updated_by": 1},
            "category": "content",
        })
        conn = _FakeConn(settings_rows, role_rows, admin_rows)
        cache = ConfigCache(pg=_FakePg(pool=_FakePool(conn)),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        assert cache.get("content.info_how_it_works")["html"] == "<h1>ИЗ БД</h1>"

    @pytest.mark.asyncio
    async def test_seed_skipped_on_file_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.config_cache.settings",
            types.SimpleNamespace(INFO_TEXT_FILE=str(tmp_path / "nope.md"),
                                  ADMIN_USER_ID=5885953495))
        conn = _FakeConn(*_rows())
        cache = ConfigCache(pg=_FakePg(pool=_FakePool(conn)),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        assert cache.get("content.info_how_it_works") is None

    @pytest.mark.asyncio
    async def test_seed_skipped_on_empty_file(self, tmp_path, monkeypatch):
        info_file = tmp_path / "info_text.md"
        info_file.write_text("   \n", encoding="utf-8")
        monkeypatch.setattr(
            "services.config_cache.settings",
            types.SimpleNamespace(INFO_TEXT_FILE=str(info_file),
                                  ADMIN_USER_ID=5885953495))
        conn = _FakeConn(*_rows())
        cache = ConfigCache(pg=_FakePg(pool=_FakePool(conn)),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        assert cache.get("content.info_how_it_works") is None

    @pytest.mark.asyncio
    async def test_init_idempotent(self):
        pg = _FakePg(pool=_FakePool(_FakeConn(*_rows())))
        cache = ConfigCache(pg=pg, retry_attempts=1, retry_delay=0)
        await cache.init()
        connects_before = pg.connects
        await cache.init()                     # повтор — no-op
        assert pg.connects == connects_before


class TestRbacOperations:
    """upsert/remove_admin, upsert/delete_role: PG + reload; без PG → 503-ошибка."""

    async def _cache(self, execute_result="INSERT 0 1"):
        conn = _FakeConn(*_rows(), execute_result=execute_result)
        cache = ConfigCache(pg=_FakePg(pool=_FakePool(conn)),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        return cache

    @pytest.mark.asyncio
    async def test_upsert_admin(self):
        cache = await self._cache()
        await cache.upsert_admin(777, "moderator", added_by=5885953495)
        assert cache.get_role(777) == "moderator"   # reload отработал

    @pytest.mark.asyncio
    async def test_remove_admin_true_and_false(self):
        cache = await self._cache(execute_result="DELETE 1")
        assert await cache.remove_admin(1313107079) is True
        cache = await self._cache(execute_result="DELETE 0")
        assert await cache.remove_admin(1313107079) is False

    @pytest.mark.asyncio
    async def test_remove_admin_broken_command_tag_false(self):
        """F17: кривой command-tag (не «DELETE n») → False, не True."""
        cache = await self._cache(execute_result="МУСОР ИЗ БД")
        assert await cache.remove_admin(1313107079) is False

    @pytest.mark.asyncio
    async def test_upsert_role(self):
        cache = await self._cache()
        await cache.upsert_role("viewer", {"sections": ["limits"]}, True)
        assert "viewer" in cache.roles()

    @pytest.mark.asyncio
    async def test_delete_role(self):
        cache = await self._cache(execute_result="DELETE 1")
        assert await cache.delete_role("user") is True
        assert "user" not in cache.roles()

    @pytest.mark.asyncio
    async def test_rbac_ops_without_pg_raise(self):
        pg = _FakePg(fail_connect=True)
        cache = ConfigCache(pg=pg, retry_attempts=1, retry_delay=0)
        await cache.init()
        from services.config_cache import ConfigCacheUnavailableError
        with pytest.raises(ConfigCacheUnavailableError):
            await cache.upsert_admin(1, "admin", None)
        with pytest.raises(ConfigCacheUnavailableError):
            await cache.remove_admin(1)
        with pytest.raises(ConfigCacheUnavailableError):
            await cache.upsert_role("x", {}, True)
        with pytest.raises(ConfigCacheUnavailableError):
            await cache.delete_role("x")
