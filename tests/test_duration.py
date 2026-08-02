"""Tests for _parse_duration and _env_duration helpers."""
import pytest
from unittest.mock import patch
from config.settings import _parse_duration


class TestParseDuration:
    """Tests for _parse_duration() function."""

    def test_seconds(self):
        assert _parse_duration("1s") == 1.0
        assert _parse_duration("30s") == 30.0
        assert _parse_duration("0s") == 0.0

    def test_minutes(self):
        assert _parse_duration("1m") == 60.0
        assert _parse_duration("5m") == 300.0

    def test_hours(self):
        assert _parse_duration("1h") == 3600.0
        assert _parse_duration("2h") == 7200.0

    def test_days(self):
        assert _parse_duration("1d") == 86400.0
        assert _parse_duration("0.5d") == 43200.0

    def test_zero_or_disabled(self):
        assert _parse_duration("0") == 0.0
        assert _parse_duration("0s") == 0.0

    def test_backward_compat_bare_integer(self):
        """Bare integers treated as seconds."""
        assert _parse_duration("60") == 60.0
        assert _parse_duration("3600") == 3600.0

    def test_float_values(self):
        assert _parse_duration("1.5h") == 5400.0
        assert _parse_duration("0.5m") == 30.0

    def test_case_insensitive(self):
        assert _parse_duration("1H") == 3600.0
        assert _parse_duration("1M") == 60.0

    def test_stripped(self):
        assert _parse_duration("  1h  ") == 3600.0

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            _parse_duration("abc")
        with pytest.raises(ValueError):
            _parse_duration("1x")

    def test_empty_string(self):
        assert _parse_duration("") == 0.0


class TestEnvDuration:
    """Tests for _env_duration() function."""

    def test_returns_parsed_value(self):
        from config.settings import _env_duration
        with patch("config.settings.os.getenv", return_value="5m"):
            result = _env_duration("TEST_KEY", "1h")
            assert result == 300.0

    def test_falls_back_to_default_when_missing(self):
        from config.settings import _env_duration
        with patch("config.settings.os.getenv", return_value=None):
            result = _env_duration("TEST_KEY", "10s")
            assert result == 10.0

    def test_falls_back_to_default_on_invalid(self):
        from config.settings import _env_duration
        with patch("config.settings.os.getenv", return_value="invalid"):
            with patch("logging.getLogger"):
                result = _env_duration("TEST_KEY", "10s")
                assert result == 10.0

    def test_bare_integer_default(self):
        from config.settings import _env_duration
        with patch("config.settings.os.getenv", return_value="0"):
            result = _env_duration("TEST_KEY", "10s")
            assert result == 0.0
