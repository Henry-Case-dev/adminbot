"""ХОТФИКС (прод-инцидент 86b3d3a): jsonb-значения из asyncpg приходят СТРОКАМИ
(json-кодек не зарегистрирован) — TypeError '<= str/int' в handlers/alan.py.

Регресс-тесты типизации на всём пути «БД → ConfigCache._load_all →
hot.get → сравнения»: int/float/bool/json нормализуются по param_catalog;
неизвестные ключи и секреты — as-is; PG down → settings-фолбек сохраняет
типы; hot-reload (cache.set) — тоже нормализуется; второй рубеж — hot.get
кастует строки даже если они каким-то путём попали в кэш.
"""
import pytest

from services import hot_config as hot
from services.config_cache import ConfigCache
from services.permissions import Permissions


class _FakeConn:
    def __init__(self, settings_rows=()):
        self.queries = []
        self._settings_rows = list(settings_rows)

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        if "bot_settings" in sql:
            return self._settings_rows
        if "bot_roles" in sql:
            return []
        if "bot_admins" in sql:
            return []
        return []


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
    def __init__(self, conn):
        self._pool = _FakePool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


# ── «прод»: asyncpg вернул jsonb СТРОКАМИ ────────────────────────────────────
_STRING_ROWS = [
    {"key": "limits.alan_reply_interval", "value": "10", "category": "limits",
     "updated_at": None},
    {"key": "limits.alan_silence_greeting_hours", "value": "6.0",
     "category": "limits", "updated_at": None},
    {"key": "limits.kostik_reply_probability", "value": "1.0",
     "category": "limits", "updated_at": None},
    {"key": "flags.summary_enabled", "value": "true", "category": "flags",
     "updated_at": None},
    {"key": "flags.alan_replies_enabled", "value": "false", "category": "flags",
     "updated_at": None},
    {"key": "reactions.goodmorning_target_chat_ids", "value": "[1, 2]",
     "category": "reactions", "updated_at": None},
    {"key": "content.info_how_it_works",
     "value": '{"html": "<h1>x</h1>", "updated_by": 1}',
     "category": "content", "updated_at": None},
    {"key": "keys.groq_api_key", "value": "gsk_secret_str",
     "category": "keys", "updated_at": None},
    {"key": "unknown.weird_key", "value": "как есть", "category": "unknown",
     "updated_at": None},
]


@pytest.fixture(autouse=True)
def _reset_hot():
    hot.set_config_cache(None)
    yield
    hot.set_config_cache(None)


class TestLoadAllNormalization:
    @pytest.mark.asyncio
    async def test_string_jsonb_normalized_by_catalog(self, monkeypatch):
        monkeypatch.setattr(
            "services.config_cache.settings",
            __import__("types").SimpleNamespace(
                INFO_TEXT_FILE="не существует.md", ADMIN_USER_ID=1))
        cache = ConfigCache(pg=_FakePg(_FakeConn(_STRING_ROWS)),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        assert cache.get("limits.alan_reply_interval") == 10
        assert isinstance(cache.get("limits.alan_reply_interval"), int)
        assert cache.get("limits.alan_silence_greeting_hours") == 6.0
        assert cache.get("limits.kostik_reply_probability") == 1.0
        assert cache.get("flags.summary_enabled") is True
        assert cache.get("flags.alan_replies_enabled") is False
        assert cache.get("reactions.goodmorning_target_chat_ids") == [1, 2]
        info = cache.get("content.info_how_it_works")
        assert isinstance(info, dict)
        assert info["html"] == "<h1>x</h1>"
        # секрет — строка без изменений
        assert cache.get("keys.groq_api_key") == "gsk_secret_str"
        # неизвестный каталогу ключ — as-is
        assert cache.get("unknown.weird_key") == "как есть"


class TestHotGetDefenseInDepth:
    """Второй рубеж: даже если в кэш попали строки, hot.get кастует."""

    class _StrCache:
        pg_available = False

        def __init__(self, values):
            self._settings = dict(values)

        def get(self, key, default=None):
            return self._settings.get(key, default)

    def test_int_float_bool_json_casts(self):
        hot.set_config_cache(self._StrCache({
            "limits.alan_reply_interval": "10",
            "limits.alan_silence_greeting_hours": "6.0",
            "flags.summary_enabled": "true",
            "reactions.goodmorning_target_chat_ids": "[1, 2]",
            "keys.groq_api_key": "gsk_secret_str",
        }))
        assert hot.get("limits.alan_reply_interval", 0) == 10
        assert isinstance(hot.get("limits.alan_reply_interval", 0), int)
        assert hot.get("limits.alan_silence_greeting_hours", 0.0) == 6.0
        assert hot.get("flags.summary_enabled", False) is True
        assert hot.get("reactions.goodmorning_target_chat_ids", ()) == [1, 2]
        assert hot.get("keys.groq_api_key", "") == "gsk_secret_str"

    def test_fallback_default_keeps_type_when_key_missing(self):
        hot.set_config_cache(self._StrCache({}))
        value = hot.get("limits.alan_reply_interval", 7)
        assert value == 7
        assert isinstance(value, int)

    def test_no_cache_returns_default(self):
        assert hot.get("limits.alan_reply_interval", 7) == 7


class TestAlanScenario:
    """Специфичный кейс инцидента: сравнения в handlers/alan.py не падают."""

    class _StrCache:
        pg_available = False

        def __init__(self, values):
            self._settings = dict(values)

        def get(self, key, default=None):
            return self._settings.get(key, default)

    def test_alan_interval_comparison_no_type_error(self):
        from config.settings import settings
        hot.set_config_cache(self._StrCache({
            "limits.alan_reply_interval": "10",
            "limits.alan_silence_greeting_hours": "6.0",
        }))
        # дословный паттерн handlers/alan.py:123-125
        interval = hot.get("limits.alan_reply_interval",
                           settings.ALAN_REPLY_INTERVAL)
        assert not (interval <= 0)              # не TypeError
        assert 20 % interval == 0              # count % interval
        # дословный паттерн handlers/alan.py:140-145
        silence_hours = hot.get("limits.alan_silence_greeting_hours",
                                settings.ALAN_SILENCE_GREETING_HOURS)
        assert not (silence_hours <= 0)
        threshold = silence_hours * 3600
        assert threshold == 21600.0

    def test_pg_down_fallback_settings_types(self):
        """PG down: кэш без ключа → settings-дефолт — типы родные."""
        from config.settings import settings
        hot.set_config_cache(self._StrCache({}))
        interval = hot.get("limits.alan_reply_interval",
                           settings.ALAN_REPLY_INTERVAL)
        assert isinstance(interval, int)


class TestSetNormalization:
    @pytest.mark.asyncio
    async def test_set_normalizes_string_value(self, monkeypatch):
        import types
        monkeypatch.setattr(
            "services.config_cache.settings",
            types.SimpleNamespace(INFO_TEXT_FILE="нет.md", ADMIN_USER_ID=1))
        cache = ConfigCache(pg=_FakePg(_FakeConn([])),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        await cache.set("limits.alan_reply_interval", "10", "limits")
        assert cache.get("limits.alan_reply_interval") == 10
        assert isinstance(cache.get("limits.alan_reply_interval"), int)

    @pytest.mark.asyncio
    async def test_set_keeps_typed_value(self, monkeypatch):
        import types
        monkeypatch.setattr(
            "services.config_cache.settings",
            types.SimpleNamespace(INFO_TEXT_FILE="нет.md", ADMIN_USER_ID=1))
        cache = ConfigCache(pg=_FakePg(_FakeConn([])),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        await cache.set("flags.summary_enabled", True, "flags")
        assert cache.get("flags.summary_enabled") is True
        await cache.set("reactions.goodmorning_target_chat_ids", (1, 2),
                        "reactions")
        assert cache.get("reactions.goodmorning_target_chat_ids") == [1, 2]
