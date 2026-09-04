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
)


class TestEpic47SettingsDefaults:
    """Epic 47 (56.4/56.8, Section 56.2): дефолты Legacy-ретраев LLM."""

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

    def test_valid_values_parsed(self, monkeypatch):
        monkeypatch.setenv("LLM_TIMEOUT", "45")
        monkeypatch.setenv("LLM_RETRY_BACKOFF_BASE", "0.5")
        monkeypatch.setenv("LLM_RETRY_BACKOFF_CAP", "12")
        monkeypatch.setenv("LLM_RETRY_JITTER_MAX", "1")
        monkeypatch.setenv("LLM_TOTAL_BUDGET", "120")
        monkeypatch.setenv("GRAPH_MEMORIZE_MAX_BATCH_RETRIES", "4")
        monkeypatch.setenv("GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF", "3")
        monkeypatch.setenv("SUMMARY_RETRY_ONCE_PAUSE", "2.5")
        importlib.reload(settings_mod)
        assert settings_mod.settings.LLM_TIMEOUT == 45.0
        assert settings_mod.settings.LLM_RETRY_BACKOFF_BASE == 0.5
        assert settings_mod.settings.LLM_RETRY_BACKOFF_CAP == 12.0
        assert settings_mod.settings.LLM_RETRY_JITTER_MAX == 1.0
        assert settings_mod.settings.LLM_TOTAL_BUDGET == 120.0
        assert settings_mod.settings.GRAPH_MEMORIZE_MAX_BATCH_RETRIES == 4
        assert settings_mod.settings.GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF == 3.0
        assert settings_mod.settings.SUMMARY_RETRY_ONCE_PAUSE == 2.5

    def test_below_min_falls_back_with_warning(self, monkeypatch, caplog):
        """LLM_TOTAL_BUDGET=0.5 (<1) → дефолт 60.0 + WARNING."""
        monkeypatch.setenv("LLM_TOTAL_BUDGET", "0.5")
        with caplog.at_level(logging.WARNING):
            importlib.reload(settings_mod)
        assert settings_mod.settings.LLM_TOTAL_BUDGET == 60.0
        assert any("LLM_TOTAL_BUDGET=0.5 < 1.0" in r.message for r in caplog.records)


_EPIC4851_KEYS = (
    "CHECKUP_MAX_INPUT_SYMBOLS",
    "CHAT_GLOBAL_CONTEXT_LIMIT",
    "CHAT_BURST_LIMIT",
    "CHAT_COOLDOWN_SECONDS",
    "CHAT_DIRECT_REPLY_TTL_DAYS",
    "CHAT_GLOBAL_CONTEXT_MAX_CHARS",
    "CHAT_THREAD_MAX_DEPTH",
    "CHAT_THREAD_MAX_CHARS",
    "SMART_CACHE_ENABLED",
    "SMART_CACHE_TTL_SECONDS",
    "SMART_CACHE_MAX_ROWS",
)


class TestEpic4851SettingsDefaults:
    """Epic 48-51 (57.7/58.3/59.4, D212): дефолты checkup-400 / DirectChat /
    SmartCache; SUMMARY_DEGRADED_* УДАЛЕНЫ."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for key in _EPIC4851_KEYS + ("SUMMARY_DEGRADED_ENABLED", "SUMMARY_DEGRADED_COUNT"):
            monkeypatch.delenv(key, raising=False)
        yield
        importlib.reload(settings_mod)   # вернуть продовый инстанс

    def test_summary_degraded_settings_removed(self):
        importlib.reload(settings_mod)
        assert not hasattr(settings_mod.settings, "SUMMARY_DEGRADED_ENABLED")
        assert not hasattr(settings_mod.settings, "SUMMARY_DEGRADED_COUNT")

    def test_defaults_without_env(self):
        importlib.reload(settings_mod)
        assert settings_mod.settings.CHECKUP_MAX_INPUT_SYMBOLS == 12000
        assert settings_mod.settings.CHAT_GLOBAL_CONTEXT_LIMIT == 100
        assert settings_mod.settings.CHAT_BURST_LIMIT == 3
        assert settings_mod.settings.CHAT_COOLDOWN_SECONDS == 300.0
        # раунд 3 (FR-C2): кодовый дефолт 30 (пусто/отсутствие), 0 = вечно
        assert settings_mod.settings.CHAT_DIRECT_REPLY_TTL_DAYS == 30
        assert settings_mod.settings.CHAT_GLOBAL_CONTEXT_MAX_CHARS == 4000
        assert settings_mod.settings.CHAT_THREAD_MAX_DEPTH == 6
        assert settings_mod.settings.CHAT_THREAD_MAX_CHARS == 2000
        assert settings_mod.settings.SMART_CACHE_ENABLED is False
        assert settings_mod.settings.SMART_CACHE_TTL_SECONDS == 1800
        assert settings_mod.settings.SMART_CACHE_MAX_ROWS == 1000

    def test_valid_values_parsed(self, monkeypatch):
        monkeypatch.setenv("CHECKUP_MAX_INPUT_SYMBOLS", "9000")
        monkeypatch.setenv("CHAT_GLOBAL_CONTEXT_LIMIT", "50")
        monkeypatch.setenv("CHAT_BURST_LIMIT", "5")
        monkeypatch.setenv("CHAT_COOLDOWN_SECONDS", "120")
        monkeypatch.setenv("CHAT_DIRECT_REPLY_TTL_DAYS", "7")
        monkeypatch.setenv("CHAT_GLOBAL_CONTEXT_MAX_CHARS", "3000")
        monkeypatch.setenv("CHAT_THREAD_MAX_DEPTH", "4")
        monkeypatch.setenv("CHAT_THREAD_MAX_CHARS", "1500")
        monkeypatch.setenv("SMART_CACHE_ENABLED", "true")
        monkeypatch.setenv("SMART_CACHE_TTL_SECONDS", "900")
        monkeypatch.setenv("SMART_CACHE_MAX_ROWS", "500")
        importlib.reload(settings_mod)
        assert settings_mod.settings.CHECKUP_MAX_INPUT_SYMBOLS == 9000
        assert settings_mod.settings.CHAT_GLOBAL_CONTEXT_LIMIT == 50
        assert settings_mod.settings.CHAT_BURST_LIMIT == 5
        assert settings_mod.settings.CHAT_COOLDOWN_SECONDS == 120.0
        assert settings_mod.settings.CHAT_DIRECT_REPLY_TTL_DAYS == 7
        assert settings_mod.settings.CHAT_GLOBAL_CONTEXT_MAX_CHARS == 3000
        assert settings_mod.settings.CHAT_THREAD_MAX_DEPTH == 4
        assert settings_mod.settings.CHAT_THREAD_MAX_CHARS == 1500
        assert settings_mod.settings.SMART_CACHE_ENABLED is True
        assert settings_mod.settings.SMART_CACHE_TTL_SECONDS == 900
        assert settings_mod.settings.SMART_CACHE_MAX_ROWS == 500

    def test_empty_ttl_days_means_default_30(self, monkeypatch):
        """CHAT_DIRECT_REPLY_TTL_DAYS="" → 30 (кодовый дефолт раунда 3)."""
        monkeypatch.setenv("CHAT_DIRECT_REPLY_TTL_DAYS", "")
        importlib.reload(settings_mod)
        assert settings_mod.settings.CHAT_DIRECT_REPLY_TTL_DAYS == 30

    def test_zero_ttl_days_means_eternal(self, monkeypatch):
        """CHAT_DIRECT_REPLY_TTL_DAYS=0 → 0 (вечно, expires_at NULL)."""
        monkeypatch.setenv("CHAT_DIRECT_REPLY_TTL_DAYS", "0")
        importlib.reload(settings_mod)
        assert settings_mod.settings.CHAT_DIRECT_REPLY_TTL_DAYS == 0

    def test_crooked_ttl_days_warns_and_defaults(self, monkeypatch, caplog):
        monkeypatch.setenv("CHAT_DIRECT_REPLY_TTL_DAYS", "каша")
        with caplog.at_level(logging.WARNING):
            importlib.reload(settings_mod)
        assert settings_mod.settings.CHAT_DIRECT_REPLY_TTL_DAYS == 30
        assert any("CHAT_DIRECT_REPLY_TTL_DAYS" in r.message for r in caplog.records)

    def test_below_min_falls_back_with_warning(self, monkeypatch, caplog):
        """CHECKUP_MAX_INPUT_SYMBOLS=500 (<1000) → 12000 + WARNING;
        CHAT_BURST_LIMIT=0 (<1) → 3 + WARNING; SMART_CACHE_TTL_SECONDS=30 → 1800."""
        monkeypatch.setenv("CHECKUP_MAX_INPUT_SYMBOLS", "500")
        monkeypatch.setenv("CHAT_BURST_LIMIT", "0")
        monkeypatch.setenv("SMART_CACHE_TTL_SECONDS", "30")
        with caplog.at_level(logging.WARNING):
            importlib.reload(settings_mod)
        assert settings_mod.settings.CHECKUP_MAX_INPUT_SYMBOLS == 12000
        assert settings_mod.settings.CHAT_BURST_LIMIT == 3
        assert settings_mod.settings.SMART_CACHE_TTL_SECONDS == 1800
        assert any("CHECKUP_MAX_INPUT_SYMBOLS=500 < 1000" in r.message for r in caplog.records)
        assert any("CHAT_BURST_LIMIT=0 < 1" in r.message for r in caplog.records)
        assert any("SMART_CACHE_TTL_SECONDS=30 < 60" in r.message for r in caplog.records)


_EPIC53_KEYS = (
    "LLM_CB_ENABLED",
    "LLM_CB_FAILURE_THRESHOLD",
    "LLM_CB_COOLDOWN_SECONDS",
    "LLM_FALLBACK_BASE_URL",
    "LLM_FALLBACK_MODEL",
    "LLM_FALLBACK_API_KEY",
)


class TestEpic53SettingsDefaults:
    """Epic 53 (62.6, тест-план 62.5 #16): дефолты CB + фоллбэк-ключей."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for key in _EPIC53_KEYS:
            monkeypatch.delenv(key, raising=False)
        yield
        importlib.reload(settings_mod)   # вернуть продовый инстанс

    def test_defaults_without_env(self):
        importlib.reload(settings_mod)
        assert settings_mod.settings.LLM_CB_ENABLED is True
        assert settings_mod.settings.LLM_CB_FAILURE_THRESHOLD == 3
        assert settings_mod.settings.LLM_CB_COOLDOWN_SECONDS == 300.0
        assert settings_mod.settings.LLM_FALLBACK_BASE_URL == ""
        assert settings_mod.settings.LLM_FALLBACK_MODEL == ""
        assert settings_mod.settings.LLM_FALLBACK_API_KEY == ""

    def test_valid_values_parsed(self, monkeypatch):
        monkeypatch.setenv("LLM_CB_ENABLED", "false")
        monkeypatch.setenv("LLM_CB_FAILURE_THRESHOLD", "5")
        monkeypatch.setenv("LLM_CB_COOLDOWN_SECONDS", "600")
        monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://other.test/v1")
        monkeypatch.setenv("LLM_FALLBACK_MODEL", "model-2")
        monkeypatch.setenv("LLM_FALLBACK_API_KEY", "key-2")
        importlib.reload(settings_mod)
        assert settings_mod.settings.LLM_CB_ENABLED is False
        assert settings_mod.settings.LLM_CB_FAILURE_THRESHOLD == 5
        assert settings_mod.settings.LLM_CB_COOLDOWN_SECONDS == 600.0
        assert settings_mod.settings.LLM_FALLBACK_BASE_URL == "https://other.test/v1"
        assert settings_mod.settings.LLM_FALLBACK_MODEL == "model-2"
        assert settings_mod.settings.LLM_FALLBACK_API_KEY == "key-2"

    def test_threshold_below_one_falls_back_with_warning(self, monkeypatch, caplog):
        """LLM_CB_FAILURE_THRESHOLD=0 (<1) → 3 + WARNING."""
        monkeypatch.setenv("LLM_CB_FAILURE_THRESHOLD", "0")
        with caplog.at_level(logging.WARNING):
            importlib.reload(settings_mod)
        assert settings_mod.settings.LLM_CB_FAILURE_THRESHOLD == 3
        assert any(
            "LLM_CB_FAILURE_THRESHOLD=0 < 1" in r.message for r in caplog.records
        )

    def test_cooldown_below_zero_falls_back_with_warning(self, monkeypatch, caplog):
        """LLM_CB_COOLDOWN_SECONDS=-5 (<0) → 300.0 + WARNING."""
        monkeypatch.setenv("LLM_CB_COOLDOWN_SECONDS", "-5")
        with caplog.at_level(logging.WARNING):
            importlib.reload(settings_mod)
        assert settings_mod.settings.LLM_CB_COOLDOWN_SECONDS == 300.0
        assert any(
            "LLM_CB_COOLDOWN_SECONDS=-5.0 < 0.0" in r.message for r in caplog.records
        )

_EPIC60B_KEYS = (
    "GRAPH_DEDUP_ENABLED",
    "GRAPH_DEDUP_SIMILARITY_HIGH",
    "GRAPH_DEDUP_SIMILARITY_LOW",
    "GRAPH_DEDUP_WEIGHT_BONUS",
    "GRAPH_UNCONFIRMED_RETENTION_DAYS",
    "MEMORY_BACKUP_ENABLED",
    "MEMORY_BACKUP_DIR",
    "MEMORY_BACKUP_KEEP",
    "MEMORY_BACKUP_HOUR",
    "EMBED_CACHE_ENABLED",
    "EMBED_CACHE_TTL_DAYS",
    "EMBED_CACHE_MAX_ROWS",
    "CHECKUP_MEMORY_METRICS_ENABLED",
    "CHAT_RUNNING_SUMMARY_ENABLED",
    "CHAT_CONTEXT_FILL_RATIO",
    "CHAT_RUNNING_SUMMARY_TAIL",
    "RUNNING_SUMMARY_TTL_MINUTES",
    "TOKENIZER_ENCODING",
    "TOKEN_SAFETY_MULTIPLIER",
    "CHAT_GLOBAL_CONTEXT_MAX_TOKENS",
    "CHAT_THREAD_MAX_TOKENS",
    "SUMMARY_MAX_CONTEXT_TOKENS",
    "CHAT_GLOBAL_CONTEXT_MAX_CHARS",
    "CHAT_THREAD_MAX_CHARS",
    "SUMMARY_MAX_CONTEXT_CHARS",
)


class TestEpic60PhaseBSettingsDefaults:
    """Epic 60 (64.8/64.9 #11): дефолты Фазы B + эффективные токенные лимиты."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for key in _EPIC60B_KEYS:
            monkeypatch.delenv(key, raising=False)
        yield
        importlib.reload(settings_mod)   # вернуть продовый инстанс

    def test_defaults_without_env(self):
        importlib.reload(settings_mod)
        s = settings_mod.settings
        assert s.GRAPH_DEDUP_ENABLED is True
        assert s.GRAPH_DEDUP_SIMILARITY_HIGH == 0.95
        assert s.GRAPH_DEDUP_SIMILARITY_LOW == 0.85
        assert s.GRAPH_DEDUP_WEIGHT_BONUS == 0.1
        assert s.GRAPH_UNCONFIRMED_RETENTION_DAYS == 14
        assert s.MEMORY_BACKUP_ENABLED is True
        assert s.MEMORY_BACKUP_DIR == "backups"
        assert s.MEMORY_BACKUP_KEEP == 7
        assert s.MEMORY_BACKUP_HOUR == "05:00"
        assert s.EMBED_CACHE_ENABLED is True
        assert s.EMBED_CACHE_TTL_DAYS == 30
        # Epic 64: 20000 × ~6.5 КБ (float16 BLOB) ≈ ~130 МБ стационар
        # (было 50000 × ~46 КБ JSON ≈ 2.3 ГБ — взрывной рост БД).
        assert s.EMBED_CACHE_MAX_ROWS == 20000
        assert s.CHECKUP_MEMORY_METRICS_ENABLED is True
        assert s.CHAT_RUNNING_SUMMARY_ENABLED is True
        assert s.CHAT_CONTEXT_FILL_RATIO == 0.8
        assert s.CHAT_RUNNING_SUMMARY_TAIL == 30
        assert s.RUNNING_SUMMARY_TTL_MINUTES == 60
        assert s.TOKENIZER_ENCODING == "o200k_base"
        assert s.TOKEN_SAFETY_MULTIPLIER == 1.15
        assert s.CHAT_GLOBAL_CONTEXT_MAX_TOKENS is None
        assert s.CHAT_THREAD_MAX_TOKENS is None
        assert s.SUMMARY_MAX_CONTEXT_TOKENS is None

    def test_effective_token_defaults(self):
        """64.7: без env — эффективные токенные бюджеты 1000/500/30000."""
        importlib.reload(settings_mod)
        from services.token_counter import resolve_chat_limit
        s = settings_mod.settings
        assert resolve_chat_limit(
            s.CHAT_GLOBAL_CONTEXT_MAX_TOKENS, 1000,
            "CHAT_GLOBAL_CONTEXT_MAX_CHARS", s.CHAT_GLOBAL_CONTEXT_MAX_CHARS,
            "CHAT_GLOBAL_CONTEXT") == ("tokens", 1000)
        assert resolve_chat_limit(
            s.CHAT_THREAD_MAX_TOKENS, 500,
            "CHAT_THREAD_MAX_CHARS", s.CHAT_THREAD_MAX_CHARS,
            "CHAT_THREAD") == ("tokens", 500)
        assert resolve_chat_limit(
            s.SUMMARY_MAX_CONTEXT_TOKENS, 30000,
            "SUMMARY_MAX_CONTEXT_CHARS", s.SUMMARY_MAX_CONTEXT_CHARS,
            "SUMMARY_MAX_CONTEXT") == ("tokens", 30000)

    def test_valid_values_parsed(self, monkeypatch):
        monkeypatch.setenv("GRAPH_DEDUP_SIMILARITY_HIGH", "0.97")
        monkeypatch.setenv("GRAPH_DEDUP_WEIGHT_BONUS", "0.2")
        monkeypatch.setenv("EMBED_CACHE_TTL_DAYS", "60")
        monkeypatch.setenv("MEMORY_BACKUP_KEEP", "10")
        monkeypatch.setenv("RUNNING_SUMMARY_TTL_MINUTES", "90")
        monkeypatch.setenv("CHAT_GLOBAL_CONTEXT_MAX_TOKENS", "2000")
        importlib.reload(settings_mod)
        s = settings_mod.settings
        assert s.GRAPH_DEDUP_SIMILARITY_HIGH == 0.97
        assert s.GRAPH_DEDUP_WEIGHT_BONUS == 0.2
        assert s.EMBED_CACHE_TTL_DAYS == 60
        assert s.MEMORY_BACKUP_KEEP == 10
        assert s.RUNNING_SUMMARY_TTL_MINUTES == 90
        assert s.CHAT_GLOBAL_CONTEXT_MAX_TOKENS == 2000

class TestBuildYtdlpBaseOpts:
    """Epic 72 (74.A/D270): единый хелпер yt-dlp опций прокси/cookies.
    Пустые настройки → ключи НЕ добавляются (D142-семантика «без прокси»)."""

    _KEYS = ("YOUTUBE_TRANSCRIPT_PROXY_URL", "YOUTUBE_COOKIES_FILE")

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for key in self._KEYS:
            monkeypatch.delenv(key, raising=False)
        yield
        importlib.reload(settings_mod)   # вернуть продовый инстанс

    def test_empty_settings_no_keys(self):
        importlib.reload(settings_mod)
        # cachedir=False — всегда (84.23, HTTP-кэш yt-dlp отключён)
        assert settings_mod.build_ytdlp_base_opts() == {"cachedir": False}

    def test_proxy_only(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_TRANSCRIPT_PROXY_URL", "http://u:p@127.0.0.1:10808")
        importlib.reload(settings_mod)
        assert settings_mod.build_ytdlp_base_opts() == {
            "cachedir": False,
            "proxy": "http://u:p@127.0.0.1:10808"}

    def test_cookies_only(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_COOKIES_FILE", "/tmp/cookies.txt")
        importlib.reload(settings_mod)
        assert settings_mod.build_ytdlp_base_opts() == {
            "cachedir": False,
            "cookiefile": "/tmp/cookies.txt"}

    def test_both_set(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_TRANSCRIPT_PROXY_URL", "http://h:1")
        monkeypatch.setenv("YOUTUBE_COOKIES_FILE", "/c.txt")
        importlib.reload(settings_mod)
        assert settings_mod.build_ytdlp_base_opts() == {
            "cachedir": False, "proxy": "http://h:1", "cookiefile": "/c.txt"}

    def test_whitespace_only_treated_as_empty(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_TRANSCRIPT_PROXY_URL", "   ")
        monkeypatch.setenv("YOUTUBE_COOKIES_FILE", "\t")
        importlib.reload(settings_mod)
        assert settings_mod.build_ytdlp_base_opts() == {"cachedir": False}


class TestInfiniteRetentionEnv:
    """Фаза 2 (T-755): settings.INFINITE_RETENTION — env-дефолт False,
    валидные true-значения парсятся _env_bool (seed/тесты полноты)."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        monkeypatch.delenv("INFINITE_RETENTION", raising=False)
        yield
        importlib.reload(settings_mod)   # вернуть продовый инстанс

    def test_default_false_without_env(self, monkeypatch):
        importlib.reload(settings_mod)
        assert settings_mod.settings.INFINITE_RETENTION is False

    def test_true_forms(self, monkeypatch):
        for raw in ("true", "True", "1", "on", "yes"):
            monkeypatch.setenv("INFINITE_RETENTION", raw)
            importlib.reload(settings_mod)
            assert settings_mod.settings.INFINITE_RETENTION is True, raw

    def test_false_forms(self, monkeypatch):
        for raw in ("false", "0", "off", ""):
            monkeypatch.setenv("INFINITE_RETENTION", raw)
            importlib.reload(settings_mod)
            assert settings_mod.settings.INFINITE_RETENTION is False, raw
