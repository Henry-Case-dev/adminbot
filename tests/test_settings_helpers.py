"""Tests for config/settings.py helpers _env_int_min/_env_float_min (T-250, D104).

Кривые значения → WARNING + дефолт; значения ниже минимума → WARNING + дефолт;
корректные → парсинг; граница min — принимается. Epic 37 (R37-2, 46.2):
дефолты 4 новых ключей + D104-механика через reload config.settings.
"""
import importlib
import logging

import pytest

import config.settings as settings_mod
from config.settings import _env_float_min, _env_int_min


class TestEnvIntMin:
    def test_valid_value_parsed(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_MIN_VALID", "250")
        assert _env_int_min("TEST_INT_MIN_VALID", 4000, 100) == 250

    def test_invalid_value_falls_back_with_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("TEST_INT_MIN_BAD", "курицы")
        with caplog.at_level(logging.WARNING):
            assert _env_int_min("TEST_INT_MIN_BAD", 4000, 100) == 4000
        assert any("Invalid int" in r.message for r in caplog.records)

    def test_below_min_falls_back_with_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("TEST_INT_MIN_LOW", "50")
        with caplog.at_level(logging.WARNING):
            assert _env_int_min("TEST_INT_MIN_LOW", 4000, 100) == 4000
        assert any("TEST_INT_MIN_LOW=50 < 100" in r.message for r in caplog.records)

    def test_min_boundary_accepted(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_MIN_EDGE", "100")
        assert _env_int_min("TEST_INT_MIN_EDGE", 4000, 100) == 100

    def test_missing_key_uses_default(self, monkeypatch):
        monkeypatch.delenv("TEST_INT_MIN_MISSING", raising=False)
        assert _env_int_min("TEST_INT_MIN_MISSING", 4000, 100) == 4000


class TestEnvFloatMin:
    def test_valid_value_parsed(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_MIN_VALID", "300.5")
        assert _env_float_min("TEST_FLOAT_MIN_VALID", 300.0, 0.0) == 300.5

    def test_invalid_value_falls_back_with_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("TEST_FLOAT_MIN_BAD", "abc")
        with caplog.at_level(logging.WARNING):
            assert _env_float_min("TEST_FLOAT_MIN_BAD", 300.0, 0.0) == 300.0
        assert any("Invalid float" in r.message for r in caplog.records)

    def test_below_min_falls_back_with_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("TEST_FLOAT_MIN_LOW", "-1.5")
        with caplog.at_level(logging.WARNING):
            assert _env_float_min("TEST_FLOAT_MIN_LOW", 300.0, 0.0) == 300.0
        assert any("TEST_FLOAT_MIN_LOW=-1.5 < 0.0" in r.message for r in caplog.records)

    def test_zero_min_boundary_accepted(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_MIN_EDGE", "0")
        assert _env_float_min("TEST_FLOAT_MIN_EDGE", 300.0, 0.0) == 0.0


_EPIC37_KEYS = (
    "YOUTUBE_MAX_SYMBOLS",
    "WEBPAGE_MAX_SYMBOLS",
    "YOUTUBE_COOLDOWN_SECONDS",
    "WEBPAGE_COOLDOWN_SECONDS",
)


class TestEpic37SettingsDefaults:
    """R37-2 (46.2): дефолты 4 новых ключей + D104-механика (reload settings)."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for key in _EPIC37_KEYS:
            monkeypatch.delenv(key, raising=False)
        yield
        importlib.reload(settings_mod)   # вернуть продовый инстанс

    def test_defaults_without_env(self):
        importlib.reload(settings_mod)
        assert settings_mod.settings.YOUTUBE_MAX_SYMBOLS == 4000
        assert settings_mod.settings.WEBPAGE_MAX_SYMBOLS == 4000
        assert settings_mod.settings.YOUTUBE_COOLDOWN_SECONDS == 300.0
        assert settings_mod.settings.WEBPAGE_COOLDOWN_SECONDS == 300.0

    def test_max_symbols_below_100_falls_back_with_warning(self, monkeypatch, caplog):
        """#40: YOUTUBE_MAX_SYMBOLS=50 (<100) → дефолт 4000 + WARNING."""
        monkeypatch.setenv("YOUTUBE_MAX_SYMBOLS", "50")
        monkeypatch.setenv("WEBPAGE_MAX_SYMBOLS", "курицы")
        with caplog.at_level(logging.WARNING):
            importlib.reload(settings_mod)
        assert settings_mod.settings.YOUTUBE_MAX_SYMBOLS == 4000
        assert settings_mod.settings.WEBPAGE_MAX_SYMBOLS == 4000
        assert any("YOUTUBE_MAX_SYMBOLS=50 < 100" in r.message for r in caplog.records)
        assert any("Invalid int" in r.message for r in caplog.records)

    def test_cooldowns_below_zero_fall_back_with_warning(self, monkeypatch, caplog):
        """#40: кулдауны <0 → дефолт 300.0 + WARNING; 0 — принимается."""
        monkeypatch.setenv("YOUTUBE_COOLDOWN_SECONDS", "-5")
        monkeypatch.setenv("WEBPAGE_COOLDOWN_SECONDS", "0")
        with caplog.at_level(logging.WARNING):
            importlib.reload(settings_mod)
        assert settings_mod.settings.YOUTUBE_COOLDOWN_SECONDS == 300.0
        assert settings_mod.settings.WEBPAGE_COOLDOWN_SECONDS == 0.0
        assert any(
            "YOUTUBE_COOLDOWN_SECONDS=-5.0 < 0.0" in r.message
            for r in caplog.records
        )

    def test_valid_values_parsed(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_MAX_SYMBOLS", "6000")
        monkeypatch.setenv("WEBPAGE_MAX_SYMBOLS", "2000")
        monkeypatch.setenv("YOUTUBE_COOLDOWN_SECONDS", "60.5")
        monkeypatch.setenv("WEBPAGE_COOLDOWN_SECONDS", "0")
        importlib.reload(settings_mod)
        assert settings_mod.settings.YOUTUBE_MAX_SYMBOLS == 6000
        assert settings_mod.settings.WEBPAGE_MAX_SYMBOLS == 2000
        assert settings_mod.settings.YOUTUBE_COOLDOWN_SECONDS == 60.5
        assert settings_mod.settings.WEBPAGE_COOLDOWN_SECONDS == 0.0


_EPIC39_KEYS = (
    "YOUTUBE_TRANSCRIPT_PROXY_URL",
    "YOUTUBE_COOKIES_FILE",
)


class TestEpic39SettingsDefaults:
    """Epic 39 (48.2/48.6): дефолты 2 новых ключей failover + reload-паттерн."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for key in _EPIC39_KEYS:
            monkeypatch.delenv(key, raising=False)
        yield
        importlib.reload(settings_mod)   # вернуть продовый инстанс

    def test_defaults_without_env(self):
        importlib.reload(settings_mod)
        assert settings_mod.settings.YOUTUBE_TRANSCRIPT_PROXY_URL == ""
        assert settings_mod.settings.YOUTUBE_COOKIES_FILE == ""

    def test_valid_values_parsed(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_TRANSCRIPT_PROXY_URL", "http://127.0.0.1:8080")
        monkeypatch.setenv("YOUTUBE_COOKIES_FILE", "/tmp/cookies.txt")
        importlib.reload(settings_mod)
        assert settings_mod.settings.YOUTUBE_TRANSCRIPT_PROXY_URL == "http://127.0.0.1:8080"
        assert settings_mod.settings.YOUTUBE_COOKIES_FILE == "/tmp/cookies.txt"


_EPIC45_KEYS = (
    "CHECKUP_BETTERSTACK_SQL_HOST",
    "CHECKUP_BETTERSTACK_SQL_USER",
    "CHECKUP_BETTERSTACK_SQL_PASSWORD",
    "CHECKUP_BETTERSTACK_SQL_TABLE",
    "CHECKUP_BETTERSTACK_SQL_QUERY",
)


class TestEpic45SettingsDefaults:
    """Epic 45 (54.2, #17): дефолты SQL-ключей; легаси live-tail-ключей нет."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for key in _EPIC45_KEYS:
            monkeypatch.delenv(key, raising=False)
        yield
        importlib.reload(settings_mod)   # вернуть продовый инстанс

    def test_defaults_without_env(self):
        importlib.reload(settings_mod)
        assert settings_mod.settings.CHECKUP_BETTERSTACK_SQL_HOST == (
            "https://eu-fsn-3-connect.betterstackdata.com"
        )
        assert settings_mod.settings.CHECKUP_BETTERSTACK_SQL_USER == ""
        assert settings_mod.settings.CHECKUP_BETTERSTACK_SQL_PASSWORD == ""
        assert settings_mod.settings.CHECKUP_BETTERSTACK_SQL_TABLE == ""
        assert settings_mod.settings.CHECKUP_BETTERSTACK_SQL_QUERY == ""

    def test_valid_values_parsed(self, monkeypatch):
        monkeypatch.setenv("CHECKUP_BETTERSTACK_SQL_USER", "clickhouse_user")
        monkeypatch.setenv("CHECKUP_BETTERSTACK_SQL_TABLE", "t123_x")
        monkeypatch.setenv("CHECKUP_BETTERSTACK_SQL_QUERY", "SELECT 1")
        importlib.reload(settings_mod)
        assert settings_mod.settings.CHECKUP_BETTERSTACK_SQL_USER == "clickhouse_user"
        assert settings_mod.settings.CHECKUP_BETTERSTACK_SQL_TABLE == "t123_x"
        assert settings_mod.settings.CHECKUP_BETTERSTACK_SQL_QUERY == "SELECT 1"

    def test_legacy_live_tail_keys_absent(self):
        """54.4: легаси-ключи Epic 44 отсутствуют в Settings."""
        for key in (
            "CHECKUP_BETTERSTACK_TOKEN",
            "CHECKUP_BETTERSTACK_URL",
            "CHECKUP_BETTERSTACK_SOURCE_IDS",
            "CHECKUP_BETTERSTACK_QUERY",
        ):
            assert not hasattr(settings_mod.settings, key), f"legacy {key} должен быть удалён"


_EPIC46_KEYS = (
    "EMBEDDING_DIM",
    "GRAPH_FACT_TTL_DAYS",
    "GRAPH_RAG_FACTS_LIMIT",
    "GRAPH_RAG_CONTEXT_MAX_CHARS",
)


class TestEpic46SettingsDefaults:
    """Epic 46 (55.2, #26): EMBEDDING_DIM=3072 и дефолты GraphRAG v2."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for key in _EPIC46_KEYS:
            monkeypatch.delenv(key, raising=False)
        yield
        importlib.reload(settings_mod)   # вернуть продовый инстанс

    def test_defaults_without_env(self):
        importlib.reload(settings_mod)
        assert settings_mod.settings.EMBEDDING_DIM == 3072
        assert settings_mod.settings.GRAPH_FACT_TTL_DAYS == 14
        assert settings_mod.settings.GRAPH_RAG_FACTS_LIMIT == 10
        assert settings_mod.settings.GRAPH_RAG_CONTEXT_MAX_CHARS == 2000

    def test_valid_values_parsed(self, monkeypatch):
        monkeypatch.setenv("GRAPH_FACT_TTL_DAYS", "21")
        monkeypatch.setenv("GRAPH_RAG_FACTS_LIMIT", "7")
        monkeypatch.setenv("GRAPH_RAG_CONTEXT_MAX_CHARS", "1500")
        importlib.reload(settings_mod)
        assert settings_mod.settings.GRAPH_FACT_TTL_DAYS == 21
        assert settings_mod.settings.GRAPH_RAG_FACTS_LIMIT == 7
        assert settings_mod.settings.GRAPH_RAG_CONTEXT_MAX_CHARS == 1500


_EPIC47_KEYS = (
    "LLM_TIMEOUT",
    "LLM_RETRY_BACKOFF_BASE",
    "LLM_RETRY_BACKOFF_CAP",
    "LLM_RETRY_JITTER_MAX",
    "LLM_TOTAL_BUDGET",
    "GRAPH_MEMORIZE_MAX_BATCH_RETRIES",
    "GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF",
    "SUMMARY_RETRY_ONCE_PAUSE",
    "SUMMARY_DEGRADED_ENABLED",
    "SUMMARY_DEGRADED_COUNT",
)


class TestEpic47SettingsDefaults:
    """Epic 47 (56.4/56.8, Section 56.2): дефолты Legacy-ретраев LLM + degrade."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for key in _EPIC47_KEYS:
            monkeypatch.delenv(key, raising=False)
        yield
        importlib.reload(settings_mod)   # вернуть продовый инстанс

    def test_defaults_without_env(self):
        importlib.reload(settings_mod)
        assert settings_mod.settings.LLM_TIMEOUT == 30.0
        assert settings_mod.settings.LLM_RETRY_BACKOFF_BASE == 1.0
        assert settings_mod.settings.LLM_RETRY_BACKOFF_CAP == 8.0
        assert settings_mod.settings.LLM_RETRY_JITTER_MAX == 2.0
        assert settings_mod.settings.LLM_TOTAL_BUDGET == 60.0
        assert settings_mod.settings.GRAPH_MEMORIZE_MAX_BATCH_RETRIES == 2
        assert settings_mod.settings.GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF == 2.0
        assert settings_mod.settings.SUMMARY_RETRY_ONCE_PAUSE == 5.0
        assert settings_mod.settings.SUMMARY_DEGRADED_ENABLED is True
        assert settings_mod.settings.SUMMARY_DEGRADED_COUNT == 15

    def test_valid_values_parsed(self, monkeypatch):
        monkeypatch.setenv("LLM_TIMEOUT", "45")
        monkeypatch.setenv("LLM_RETRY_BACKOFF_BASE", "0.5")
        monkeypatch.setenv("LLM_RETRY_BACKOFF_CAP", "12")
        monkeypatch.setenv("LLM_RETRY_JITTER_MAX", "1")
        monkeypatch.setenv("LLM_TOTAL_BUDGET", "120")
        monkeypatch.setenv("GRAPH_MEMORIZE_MAX_BATCH_RETRIES", "4")
        monkeypatch.setenv("GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF", "3")
        monkeypatch.setenv("SUMMARY_RETRY_ONCE_PAUSE", "2.5")
        monkeypatch.setenv("SUMMARY_DEGRADED_ENABLED", "false")
        monkeypatch.setenv("SUMMARY_DEGRADED_COUNT", "8")
        importlib.reload(settings_mod)
        assert settings_mod.settings.LLM_TIMEOUT == 45.0
        assert settings_mod.settings.LLM_RETRY_BACKOFF_BASE == 0.5
        assert settings_mod.settings.LLM_RETRY_BACKOFF_CAP == 12.0
        assert settings_mod.settings.LLM_RETRY_JITTER_MAX == 1.0
        assert settings_mod.settings.LLM_TOTAL_BUDGET == 120.0
        assert settings_mod.settings.GRAPH_MEMORIZE_MAX_BATCH_RETRIES == 4
        assert settings_mod.settings.GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF == 3.0
        assert settings_mod.settings.SUMMARY_RETRY_ONCE_PAUSE == 2.5
        assert settings_mod.settings.SUMMARY_DEGRADED_ENABLED is False
        assert settings_mod.settings.SUMMARY_DEGRADED_COUNT == 8

    def test_below_min_falls_back_with_warning(self, monkeypatch, caplog):
        """LLM_TOTAL_BUDGET=0.5 (<1) → дефолт 60.0 + WARNING; SUMMARY_DEGRADED_COUNT=0 → 15."""
        monkeypatch.setenv("LLM_TOTAL_BUDGET", "0.5")
        monkeypatch.setenv("SUMMARY_DEGRADED_COUNT", "0")
        with caplog.at_level(logging.WARNING):
            importlib.reload(settings_mod)
        assert settings_mod.settings.LLM_TOTAL_BUDGET == 60.0
        assert settings_mod.settings.SUMMARY_DEGRADED_COUNT == 15
        assert any("LLM_TOTAL_BUDGET=0.5 < 1.0" in r.message for r in caplog.records)
        assert any("SUMMARY_DEGRADED_COUNT=0 < 1" in r.message for r in caplog.records)
