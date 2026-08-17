"""Tests for config/settings.py helpers _env_int_min/_env_float_min (T-250, D104).

Кривые значения → WARNING + дефолт; значения ниже минимума → WARNING + дефолт;
корректные → парсинг; граница min — принимается.
"""
import logging

import pytest

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
