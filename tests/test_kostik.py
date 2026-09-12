"""Tests for Kostik reply engine (F7).

Tests cover:
  - Reply fires for Kostik's user ID
  - Probability-based firing (0.0 → never, 1.0 → always, 0.5 → sometimes)
  - Random selection from reply pool
  - All replies are non-empty strings
  - Reply uses message.reply() (not answer or send_message)
"""
import pytest
from unittest.mock import AsyncMock, patch

from handlers.kostik import kostik_handler, KOSTIK_REPLIES, _resolve_replies


OWNER_PHRASES = [
    "Папочка, только не в попочку",
    "Папа Костя, только не там",
    "Папа Костя, можно хотя бы сегодня без конфетки?",
    "Daddy, i'm scared, убери это пожалуйста",
]


class _FakeHotCache:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


def _set_hot(monkeypatch, data):
    monkeypatch.setattr("services.hot_config._cache", _FakeHotCache(data))


def _set_probability(monkeypatch, prob: float):
    """Helper: inject a new Settings instance with given KOSTIK_REPLY_PROBABILITY."""
    import config.settings as settings_module
    new_settings = settings_module.Settings(KOSTIK_REPLY_PROBABILITY=prob)
    monkeypatch.setattr("handlers.kostik.settings", new_settings)


class TestKostikHandler:
    """Unit tests for the Kostik reply engine handler."""

    @pytest.mark.asyncio
    async def test_reply_with_probability_1_0(self, make_message, monkeypatch):
        """At probability 1.0, EVERY message gets a reply."""
        _set_probability(monkeypatch, 1.0)

        for i in range(5):
            msg = make_message(350803143, text=f"message {i}")
            await kostik_handler(msg)
            msg.reply.assert_called_once()
            reply_arg = msg.reply.call_args[0][0]
            assert reply_arg in KOSTIK_REPLIES

    @pytest.mark.asyncio
    async def test_reply_with_probability_0_0(self, make_message, monkeypatch):
        """At probability 0.0, NO messages get a reply."""
        _set_probability(monkeypatch, 0.0)

        for i in range(10):
            msg = make_message(350803143, text=f"message {i}")
            await kostik_handler(msg)
            msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_random_selection_from_pool(self, make_message, monkeypatch):
        """Over many calls at prob=1.0, we should see different replies."""
        _set_probability(monkeypatch, 1.0)

        seen = set()
        for i in range(30):
            msg = make_message(350803143, text=f"msg_{i}")
            await kostik_handler(msg)
            seen.add(msg.reply.call_args[0][0])
            msg.reply.reset_mock()

        assert len(seen) >= 2, f"Only {len(seen)} unique replies from 30 calls"

    @pytest.mark.asyncio
    async def test_all_replies_are_non_empty_strings(self):
        """All entries in KOSTIK_REPLIES must be non-empty strings."""
        for reply in KOSTIK_REPLIES:
            assert isinstance(reply, str), f"Non-string: {reply!r}"
            assert len(reply) > 0, "Empty string in pool"

    @pytest.mark.asyncio
    async def test_pool_has_minimum_size(self):
        """Pool should have at least 3 variants."""
        assert len(KOSTIK_REPLIES) >= 3, (
            f"Pool has {len(KOSTIK_REPLIES)} entries, need at least 3"
        )

    @pytest.mark.asyncio
    async def test_reply_uses_message_reply(self, make_message, monkeypatch):
        """Verify reply is sent via message.reply()."""
        _set_probability(monkeypatch, 1.0)

        msg = make_message(350803143, text="test")
        await kostik_handler(msg)
        msg.reply.assert_called_once()
        assert not msg.answer.called

    @pytest.mark.asyncio
    async def test_non_text_message_also_triggers(self, make_message, monkeypatch):
        """Photo/sticker messages from Kostik should also trigger reply."""
        _set_probability(monkeypatch, 1.0)

        msg = make_message(350803143, text=None)
        msg.photo = []
        await kostik_handler(msg)
        msg.reply.assert_called_once()
        assert msg.reply.call_args[0][0] in KOSTIK_REPLIES

    @pytest.mark.asyncio
    async def test_probability_0_5_random(self, make_message, monkeypatch):
        """At prob=0.5, random.random() controls firing."""
        _set_probability(monkeypatch, 0.5)

        # random returns 0.3 (< 0.5): should reply
        with patch("random.random", return_value=0.3):
            msg = make_message(350803143, text="should fire")
            await kostik_handler(msg)
            msg.reply.assert_called_once()

        # random returns 0.7 (>= 0.5): should NOT reply
        with patch("random.random", return_value=0.7):
            msg = make_message(350803143, text="should not fire")
            await kostik_handler(msg)
            msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_negative_probability_treated_as_zero(self, make_message, monkeypatch):
        """Negative prob should be treated as 0.0 (never reply)."""
        _set_probability(monkeypatch, -0.5)
        msg = make_message(350803143, text="test")
        await kostik_handler(msg)
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_above_one_probability_treated_as_always(self, make_message, monkeypatch):
        """Prob > 1.0 should be treated as always (>= 1.0 branch)."""
        _set_probability(monkeypatch, 2.0)
        msg = make_message(350803143, text="test")
        await kostik_handler(msg)
        msg.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_legacy_behavior_default_probability(self, make_message):
        """Default probability (1.0) should reply to every message (legacy compat)."""
        # Don't monkeypatch — settings default is 1.0
        msg = make_message(350803143, text="hello")
        await kostik_handler(msg)
        msg.reply.assert_called_once()


class TestKostikCatalogPhrases:
    """Раунд 10.12 (ADR-1012-1 D4): фразы — параметр каталога
    reactions.kostik_replies (hot.get), дефолт = 4 владельца + 10 новых."""

    def test_default_pool_owner_plus_new(self):
        from config.settings import DEFAULT_KOSTIK_REPLIES
        pool = list(DEFAULT_KOSTIK_REPLIES)
        assert len(pool) == 14, len(pool)
        for phrase in OWNER_PHRASES:
            assert phrase in pool, phrase
        new = [p for p in pool if p not in OWNER_PHRASES]
        assert len(new) >= 10, len(new)

    def test_default_pool_non_empty_and_unique(self):
        from config.settings import DEFAULT_KOSTIK_REPLIES
        pool = list(DEFAULT_KOSTIK_REPLIES)
        assert all(isinstance(p, str) and p.strip() for p in pool)
        assert len(pool) == len(set(pool)), "фразы должны быть уникальны"

    def test_no_hardcoded_pool_in_handler(self):
        import handlers.kostik as mod
        import inspect
        src = inspect.getsource(mod)
        # Код-дефолт живёт в settings; в хендлере — только чтение через hot.get.
        assert "reactions.kostik_replies" in src
        # Литерала старого пула «кринжатура» больше нет.
        assert "кринжатура" not in src

    @pytest.mark.asyncio
    async def test_custom_phrases_via_hot(self, make_message, monkeypatch):
        _set_probability(monkeypatch, 1.0)
        _set_hot(monkeypatch, {"reactions.kostik_replies": ["только это"]})
        msg = make_message(350803143, text="x")
        await kostik_handler(msg)
        assert msg.reply.call_args[0][0] == "только это"

    @pytest.mark.asyncio
    async def test_empty_list_silences(self, make_message, monkeypatch):
        _set_probability(monkeypatch, 1.0)
        _set_hot(monkeypatch, {"reactions.kostik_replies": []})
        msg = make_message(350803143, text="x")
        await kostik_handler(msg)
        msg.reply.assert_not_called()

    def test_resolve_replies_normalizes(self):
        assert _resolve_replies(["a", " b ", "", None, 5]) == ["a", "b"]
        assert _resolve_replies('["x", " y "]') == ["x", "y"]
        assert _resolve_replies("not-json") == []
        assert _resolve_replies(None) == []
        assert _resolve_replies({"a": 1}) == []
