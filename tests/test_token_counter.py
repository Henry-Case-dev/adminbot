"""Epic 60 (Section 64.7/64.9, T-468): token_counter — count/truncate
(мок-кодировка), fallback chars×0.3, safe_budget, resolve_chat_limit."""
import logging

import pytest

from services import token_counter as tc


class FakeEncoding:
    """1 символ = 1 токен (детерминированный мок)."""

    def encode(self, text):
        return list(text)

    def decode(self, tokens):
        return "".join(tokens)


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    monkeypatch.setattr(tc, "_ENCODINGS", {})
    yield


class TestCountTokens:
    def test_count_with_encoding(self, monkeypatch):
        monkeypatch.setattr(tc, "_get_encoding", lambda: FakeEncoding())
        assert tc.count_tokens("привет мир") == 10

    def test_count_empty(self):
        assert tc.count_tokens("") == 0
        assert tc.count_tokens(None) == 0

    def test_fallback_chars_times_03(self, monkeypatch):
        monkeypatch.setattr(tc, "_get_encoding", lambda: None)
        assert tc.count_tokens("abcdefghij") == 3      # int(10 * 0.3)
        assert tc.count_tokens("") == 0

    def test_real_tiktoken_optional(self):
        """Опциональная проверка: реальный tiktoken считает > 0 (если стоит)."""
        try:
            import tiktoken  # noqa: F401
        except ImportError:
            pytest.skip("tiktoken not installed")
        tc._ENCODINGS.clear()
        assert tc.count_tokens("привет мир") > 0


class TestTruncateToTokens:
    def test_keeps_tail_with_encoding(self, monkeypatch):
        monkeypatch.setattr(tc, "_get_encoding", lambda: FakeEncoding())
        assert tc.truncate_to_tokens("abcdef", 3) == "def"

    def test_within_limit_unchanged(self, monkeypatch):
        monkeypatch.setattr(tc, "_get_encoding", lambda: FakeEncoding())
        assert tc.truncate_to_tokens("abc", 5) == "abc"

    def test_truncation_warns(self, monkeypatch, caplog):
        monkeypatch.setattr(tc, "_get_encoding", lambda: FakeEncoding())
        with caplog.at_level(logging.WARNING):
            tc.truncate_to_tokens("abcdef", 3)
        assert any("token_counter: truncated to 3 tokens" in r.message
                   for r in caplog.records)

    def test_fallback_chars_slice(self, monkeypatch):
        monkeypatch.setattr(tc, "_get_encoding", lambda: None)
        # 10 симв → int(10*0.3)=3 токена > 2 → срез: хвост int(2/0.3)=6 симв
        result = tc.truncate_to_tokens("abcdefghij", 2)
        assert result == "efghij"

    def test_zero_budget_empty(self):
        assert tc.truncate_to_tokens("abc", 0) == ""


class TestSafeBudget:
    def test_multiplier_applied(self, monkeypatch):
        from dataclasses import replace
        from unittest.mock import patch
        from config.settings import settings
        mod = replace(settings, TOKEN_SAFETY_MULTIPLIER=2.0)
        with patch("services.token_counter.settings", mod):
            assert tc.safe_budget(1000) == 500

    def test_never_zero(self, monkeypatch):
        from dataclasses import replace
        from unittest.mock import patch
        from config.settings import settings
        mod = replace(settings, TOKEN_SAFETY_MULTIPLIER=100.0)
        with patch("services.token_counter.settings", mod):
            assert tc.safe_budget(10) == 1


class TestResolveChatLimit:
    def test_tokens_when_configured(self):
        assert tc.resolve_chat_limit(2000, 1000, "CHAR_KEY", 4000, "LBL") \
            == ("tokens", 2000)

    def test_chars_fallback_warns(self, monkeypatch, caplog):
        monkeypatch.setenv("CHAR_KEY_XYZ", "6000")
        with caplog.at_level(logging.WARNING):
            result = tc.resolve_chat_limit(None, 1000, "CHAR_KEY_XYZ", 6000,
                                           "LBL_XYZ")
        assert result == ("chars", 6000)
        assert any("chars-fallback" in r.message for r in caplog.records)

    def test_default_tokens_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("CHAR_KEY_NONE", raising=False)
        assert tc.resolve_chat_limit(None, 1000, "CHAR_KEY_NONE", 4000, "LBL") \
            == ("tokens", 1000)
