"""Epic 85 (84.18, T-656) — тесты In-Memory State Dump (services/debug_config).

DoD 84.16.2 пп.17-18: допуск (wildcard / action.debug.config /
ADMIN_USER_ID-фолбек при деградации), source-семантика (memory-cache /
settings-fallback / missing), маскировка секретов ВСЕГДА, meta (keys_total,
cache_loaded_at, pid, app_version), _loaded_at ставится при загрузке RAM.
"""
import pytest

from config.settings import settings
from services.debug_config import (
    _dump_item,
    build_dump,
    is_debug_admin,
)
from services.permissions import Permissions


class _FakeCache:
    def __init__(self, values=None, updated_at=None, admins=None, roles=None,
                 pg_available=True, initialized=True, loaded_at=None):
        self._settings = dict(values or {})
        self._settings_updated_at = dict(updated_at or {})
        self._loaded_at = loaded_at
        self._admins = dict(admins or {})
        self._roles = dict(roles or {})
        self.pg_available = pg_available
        self.is_initialized = initialized

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def get_all(self):
        return dict(self._settings)

    def get_updated_at(self, key):
        return self._settings_updated_at.get(key)

    @property
    def loaded_at(self):
        return self._loaded_at

    def admins(self):
        return dict(self._admins)

    def get_permissions_by_telegram_id(self, tg_id):
        role = self._admins.get(tg_id)
        if role is None:
            return None
        data = (self._roles.get(role) or {}).get("permissions", {})
        return Permissions.from_dict(data)


def _admin_cache():
    return _FakeCache(
        admins={5885953495: "admin", 1313107079: "moderator"},
        roles={
            "admin": {"permissions": {"wildcard": True}},
            "moderator": {"permissions": {"sections": ["limits"]}},
        },
    )


class TestIsDebugAdmin:
    def test_wildcard_admin_allowed(self):
        assert is_debug_admin(_admin_cache(), 5885953495) is True

    def test_action_right_allowed(self):
        cache = _FakeCache(
            admins={111: "debugger"},
            roles={"debugger": {
                "permissions": {"actions": ["debug.config"]}}})
        assert is_debug_admin(cache, 111) is True

    def test_non_admin_denied(self):
        assert is_debug_admin(_admin_cache(), 1313107079) is False
        assert is_debug_admin(_admin_cache(), 999) is False
        assert is_debug_admin(_admin_cache(), None) is False

    def test_pg_down_fallback_to_admin_user_id(self):
        cache = _FakeCache(admins={}, pg_available=False)
        assert is_debug_admin(cache, settings.ADMIN_USER_ID) is True
        assert is_debug_admin(cache, 999) is False

    def test_empty_admins_fallback(self):
        cache = _FakeCache(admins={})
        assert is_debug_admin(cache, settings.ADMIN_USER_ID) is True
        assert is_debug_admin(cache, 12345) is False

    def test_cache_none_fallback(self):
        assert is_debug_admin(None, settings.ADMIN_USER_ID) is True
        assert is_debug_admin(None, 12345) is False


class TestBuildDump:
    def test_sources_semantics(self):
        """memory-cache / settings-fallback / missing — все три источника."""
        cache = _FakeCache(
            values={"limits.search_max_symbols": 8000,
                    "unknown.weird": "x"},
            updated_at={"limits.search_max_symbols": "2026-08-30T01:00:00+00:00"},
            loaded_at="2026-08-30T02:00:00+00:00")
        dump = build_dump(cache)
        items = {i["key"]: i for i in dump["items"]}
        assert items["limits.search_max_symbols"]["source"] == "memory-cache"
        assert items["limits.search_max_symbols"]["value"] == 8000
        assert items["limits.search_max_symbols"]["updated_at"] \
            == "2026-08-30T01:00:00+00:00"
        assert items["unknown.weird"]["source"] == "memory-cache"
        # ключа нет в RAM, но есть settings-дефолт
        assert items["limits.factcheck_max_symbols"]["source"] \
            == "settings-fallback"
        assert items["limits.factcheck_max_symbols"]["value"] \
            == settings.FACTCHECK_MAX_SYMBOLS
        # промпт: нет в RAM и нет settings-источника → missing
        assert items["prompts.factcheck_system_prompt"]["source"] == "missing"

    def test_secrets_always_masked(self):
        cache = _FakeCache(values={"keys.groq_api_key": "gsk_super_secret_1234"})
        dump = build_dump(cache)
        item = {i["key"]: i for i in dump["items"]}["keys.groq_api_key"]
        assert item["secret"] is True
        assert item["value"] == {"configured": True, "last4": "1234"}
        assert "gsk_super_secret" not in str(dump)
        # secret-категория без каталога: прокси-URL тоже маскируется
        cache2 = _FakeCache(values={
            "keys.youtube_transcript_proxy_url": "http://u:p@x:1"})
        dump2 = build_dump(cache2)
        item2 = {i["key"]: i for i in dump2["items"]}[
            "keys.youtube_transcript_proxy_url"]
        assert item2["value"]["configured"] is True
        assert "u:p" not in str(dump2)

    def test_meta_contains_ram_proof(self):
        cache = _FakeCache(values={"limits.search_max_symbols": 1},
                           loaded_at="2026-08-30T02:00:00+00:00")
        dump = build_dump(cache)
        meta = dump["meta"]
        assert meta["keys_total"] == 1
        assert meta["cache_loaded_at"] == "2026-08-30T02:00:00+00:00"
        assert meta["pid"] > 0
        assert meta["app_version"]
        assert meta["generated_at"]
        assert meta["is_initialized"] is True
        assert meta["pg_available"] is True

    def test_single_key_returns_item(self):
        cache = _FakeCache(values={"limits.search_max_symbols": 777})
        dump = build_dump(cache, key="limits.search_max_symbols")
        assert "item" in dump and "items" not in dump
        assert dump["item"]["value"] == 777
        assert dump["item"]["source"] == "memory-cache"

    def test_single_key_missing_source(self):
        dump = build_dump(_FakeCache(), key="prompts.no_such_key")
        assert dump["item"]["source"] == "missing"
        assert dump["item"]["value"] is None

    def test_cache_none_dump_safe(self):
        dump = build_dump(None, key="limits.search_max_symbols")
        assert dump["meta"]["keys_total"] == 0
        assert dump["meta"]["pg_available"] is False
        assert dump["item"]["source"] == "settings-fallback"

    def test_type_from_catalog(self):
        dump = build_dump(_FakeCache(
            values={"limits.alan_reply_interval": 10}))
        item = {i["key"]: i for i in dump["items"]}["limits.alan_reply_interval"]
        assert item["type"] == "int"
        assert item["category"] == "limits"

    def test_unknown_key_type_from_python(self):
        dump = build_dump(_FakeCache(values={"unknown.weird": 42}))
        item = {i["key"]: i for i in dump["items"]}["unknown.weird"]
        assert item["type"] == "int"   # type(42).__name__

    def test_long_value_gets_value_len_marker(self):
        long_prompt = "П" * 500
        cache = _FakeCache(
            values={"prompts.factcheck_system_prompt": long_prompt})
        dump = build_dump(cache)
        item = {i["key"]: i for i in dump["items"]}[
            "prompts.factcheck_system_prompt"]
        assert item["value_len"] == 500   # обрезка — на стороне Telegram-вывода


class TestLoadedAt:
    """84.18.8: _loaded_at ставится в _load_all; None при старте без PG."""

    @pytest.mark.asyncio
    async def test_loaded_at_set_after_init(self):
        from services.config_cache import ConfigCache

        class _Conn:
            async def execute(self, sql, *args):
                return "INSERT 0 1"

            async def fetch(self, sql, *args):
                if "bot_settings" in sql:
                    return [{"key": "limits.search_max_symbols",
                             "value": 1, "category": "limits",
                             "updated_at": None}]
                if "bot_roles" in sql:
                    return []
                if "bot_admins" in sql:
                    return []
                return []

        class _Pool:
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

        class _Pg:
            def __init__(self, conn):
                self.pool = _Pool(conn)

            async def connect(self):
                pass

            async def init(self, seed_settings: bool = True):
                pass

            async def close(self):
                pass

        cache = ConfigCache(pg=_Pg(_Conn()), retry_attempts=1, retry_delay=0)
        assert cache.loaded_at is None
        await cache.init()
        assert cache.loaded_at is not None

    @pytest.mark.asyncio
    async def test_loaded_at_none_without_pg(self):
        from services.config_cache import ConfigCache

        class _FailPg:
            async def connect(self):
                raise ConnectionError("down")

            async def init(self, seed_settings: bool = True):
                pass

            async def close(self):
                pass

        cache = ConfigCache(pg=_FailPg(), retry_attempts=1, retry_delay=0)
        await cache.init()
        assert cache.loaded_at is None
