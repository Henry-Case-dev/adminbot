"""Epic 85 (T-628, 84.11.1) — тесты services/log_ring.py.

DoD 84.10 п.7-8: sanitize маскирует секреты (литералы, Bearer, sk-/gsk_/or-/
tvly- префиксы, URI-креды); exc_text (truncate 4000); errors_total; фильтр
logtail*; get_entries (уровни/limit/порядок от новых к старым).
"""
import logging
import types

import pytest

from services import log_ring as log_ring_mod
from services.log_ring import (
    LogRingHandler,
    sanitize,
)


@pytest.fixture(autouse=True)
def _secrets(monkeypatch):
    """Фиксированный набор секретов (settings — frozen, подменяем каталог)."""
    monkeypatch.setattr(log_ring_mod, "_SECRETS", (
        "123456:REAL_BOT_TOKEN_ABCDEFG",
        "gsk_groq_secret_value_xyz",
        "pass_proxy_123",
    ))


class TestSanitize:
    def test_literal_secrets_replaced(self):
        text = "token=123456:REAL_BOT_TOKEN_ABCDEFG hello"
        assert sanitize(text) == "token=*** hello"

    def test_postgres_dsn_password_masked(self, monkeypatch):
        monkeypatch.setenv(
            "POSTGRES_DSN",
            "postgresql://adminbot:supersecret_dsn_pass@127.0.0.1:5432/adminbot")
        monkeypatch.setattr(log_ring_mod, "_SECRETS", None)   # пересборка
        out = sanitize("dsn is postgresql://adminbot:supersecret_dsn_pass@127.0.0.1:5432/adminbot")
        assert "supersecret_dsn_pass" not in out
        assert "***" in out

    def test_broken_dsn_ignored(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_DSN", "http://[broken")
        monkeypatch.setattr(log_ring_mod, "_SECRETS", None)
        assert sanitize("обычное") == "обычное"

    def test_authorization_bearer(self):
        text = "Authorization: Bearer gsk_secret_abcdef token"
        assert "gsk_secret_abcdef" not in sanitize(text)
        assert "Bearer ***" in sanitize(text)

    def test_bearer_word(self):
        text = "http call bearer gsk_groq_secret_value_xyz failed"
        out = sanitize(text)
        assert "gsk_groq_secret_value_xyz" not in out

    def test_prefix_patterns(self):
        out = sanitize("keys: sk-abcdef123456 or-xyz789012345 gsk_abc123456789")
        assert "sk-abcdef123456" not in out
        assert "or-xyz789012345" not in out
        assert "gsk_abc123456789" not in out
        assert out.count("***") >= 3

    def test_uri_credentials(self):
        out = sanitize("proxy http://user:pass_proxy_123@127.0.0.1:10808 ok")
        assert "pass_proxy_123" not in out
        assert "http://***@127.0.0.1:10808" in out

    def test_empty_and_none_safe(self):
        assert sanitize("") == ""
        assert sanitize(None) is None

    def test_no_secret_untouched(self):
        assert sanitize("обычное сообщение без секретов") \
            == "обычное сообщение без секретов"


class TestHandler:
    def _make(self, maxlen=100):
        handler = LogRingHandler(maxlen=maxlen)
        return handler

    def _emit(self, handler, logger_name, level, message, exc_info=None):
        record = logging.LogRecord(
            name=logger_name, level=level, pathname="x", lineno=1,
            msg=message, args=(), exc_info=exc_info)
        handler.emit(record)

    def test_entry_structure(self):
        handler = self._make()
        self._emit(handler, "test.logger", logging.WARNING, "предупреждение")
        entries = handler.get_entries(level="ALL")
        assert len(entries) == 1
        entry = entries[0]
        assert entry["level"] == "WARNING"
        assert entry["logger"] == "test.logger"
        assert entry["message"] == "предупреждение"
        assert entry["exc_text"] is None
        assert entry["ts"]

    def test_exc_text_captured(self):
        handler = self._make()
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import sys
            self._emit(handler, "x", logging.ERROR, "ошибка",
                       exc_info=sys.exc_info())
        entries = handler.get_entries(level="ALL")
        assert "RuntimeError: boom" in entries[0]["exc_text"]

    def test_exc_text_truncated_4000(self):
        handler = self._make()
        try:
            raise RuntimeError("X" * 10000)
        except RuntimeError:
            import sys
            self._emit(handler, "x", logging.ERROR, "длинная",
                       exc_info=sys.exc_info())
        assert len(handler.get_entries(level="ALL")[0]["exc_text"]) <= 4000

    def test_errors_total_counts_error_and_above(self):
        handler = self._make()
        self._emit(handler, "x", logging.INFO, "info")
        self._emit(handler, "x", logging.WARNING, "warn")
        self._emit(handler, "x", logging.ERROR, "err")
        self._emit(handler, "x", logging.CRITICAL, "crit")
        assert handler.get_errors_total() == 2

    def test_logtail_filtered(self):
        handler = self._make()
        record = logging.LogRecord(
            name="logtail.ingest", level=logging.ERROR, pathname="x",
            lineno=1, msg="не должен попасть", args=(), exc_info=None)
        handler.handle(record)              # фильтры работают в handle()
        assert handler.get_entries(level="ALL") == []

    def test_secrets_masked_in_buffer(self):
        handler = self._make()
        self._emit(handler, "x", logging.ERROR,
                   "key=123456:REAL_BOT_TOKEN_ABCDEFG")
        entry = handler.get_entries(level="ALL")[0]
        assert "REAL_BOT_TOKEN" not in entry["message"]
        assert "***" in entry["message"]

    def test_secrets_masked_in_exc_text(self):
        """F3: sanitize применяется и к exc_text — секреты из трейсбеков
        не утекают в публичный /api/status/logs."""
        handler = self._make()
        try:
            raise RuntimeError("сбой: token=123456:REAL_BOT_TOKEN_ABCDEFG")
        except RuntimeError:
            import sys
            self._emit(handler, "x", logging.ERROR, "ошибка",
                       exc_info=sys.exc_info())
        entry = handler.get_entries(level="ALL")[0]
        assert "REAL_BOT_TOKEN" not in entry["exc_text"]
        assert "***" in entry["exc_text"]

    def test_maxlen_ring(self):
        handler = self._make(maxlen=3)
        for i in range(5):
            self._emit(handler, "x", logging.INFO, f"m{i}")
        entries = handler.get_entries(level="ALL")
        assert len(entries) == 3
        assert entries[0]["message"] == "m4"   # от новых к старым
        assert entries[-1]["message"] == "m2"

    def test_level_filter_default_info_and_above(self):
        handler = self._make()
        self._emit(handler, "x", logging.DEBUG, "debug")
        self._emit(handler, "x", logging.INFO, "info")
        self._emit(handler, "x", logging.ERROR, "error")
        entries = handler.get_entries()          # дефолт INFO+
        assert [e["message"] for e in entries] == ["error", "info"]
        assert [e["message"] for e in
                handler.get_entries(level="ERROR")] == ["error"]
        assert len(handler.get_entries(level="ALL")) == 3

    def test_limit(self):
        handler = self._make(maxlen=50)
        for i in range(10):
            self._emit(handler, "x", logging.INFO, f"m{i}")
        assert len(handler.get_entries(level="ALL", limit=4)) == 4

    def test_invalid_level_falls_back_to_info(self):
        handler = self._make()
        self._emit(handler, "x", logging.DEBUG, "debug")
        self._emit(handler, "x", logging.INFO, "info")
        assert len(handler.get_entries(level="БРЕД")) == 1

    def test_maxlen_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_RING_MAX_ENTRIES", "5")
        assert LogRingHandler().maxlen == 5
        monkeypatch.setenv("LOG_RING_MAX_ENTRIES", "мусор")
        assert LogRingHandler().maxlen == 1000
