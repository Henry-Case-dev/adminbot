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
