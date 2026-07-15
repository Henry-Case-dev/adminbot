"""
Edge cases and integration-style tests that span multiple components.
"""
import pytest
from unittest.mock import MagicMock

from filters.user_id import UserIdFilter
from filters.kucha_word import KuchaWordFilter
from filters.war_word import WarWordFilter


class TestEdgeCases:
    """Tests for various edge cases and corner scenarios."""

    # ── UserIdFilter Edge Cases ──

    @pytest.mark.asyncio
    async def test_zero_user_id(self, make_message):
        f = UserIdFilter(0)
        msg = make_message(0, text="hello")
        assert await f(msg) is True

    @pytest.mark.asyncio
    async def test_negative_user_id(self, make_message):
        f = UserIdFilter(-1)
        msg = make_message(479167456, text="hello")
        assert await f(msg) is False

    @pytest.mark.asyncio
    async def test_multiple_ids_first_matches(self, make_message):
        f = UserIdFilter(111, 222, 333)
        msg = make_message(111, text="hello")
        assert await f(msg) is True

    @pytest.mark.asyncio
    async def test_empty_ids_set(self, make_message):
        f = UserIdFilter()
        msg = make_message(479167456, text="hello")
        assert await f(msg) is False

    # ── KuchaWordFilter Edge Cases ──

    @pytest.mark.asyncio
    async def test_kucha_mixed_case(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, "КуЧа")) is True

    @pytest.mark.asyncio
    async def test_kucha_at_start(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, "Куча привет")) is True

    @pytest.mark.asyncio
    async def test_kucha_at_end(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, "привет куча")) is True

    @pytest.mark.asyncio
    async def test_kucha_alone(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, "куча")) is True

    @pytest.mark.asyncio
    async def test_kucha_with_punctuation(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, "!куча?")) is True

    @pytest.mark.asyncio
    async def test_kucha_not_matching_different_word(self, make_message):
        """'кучерявый' should NOT match because 'куч' is not a whole word."""
        f = KuchaWordFilter()
        assert await f(make_message(1, "кучерявый")) is False

    # ── WarWordFilter Edge Cases ──

    @pytest.mark.asyncio
    async def test_empty_string(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "")) is False

    @pytest.mark.asyncio
    async def test_only_whitespace(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "   \n\t  ")) is False

    @pytest.mark.asyncio
    async def test_war_word_as_substring_not_matched(self, make_message):
        """'дроновый' should NOT match 'дрон' because lookahead blocks Cyrillic."""
        f = WarWordFilter()
        result = await f(make_message(1, "дроновый аппарат"))
        assert result is False

    @pytest.mark.asyncio
    async def test_war_word_case_insensitive(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "ЛЕТИТ ДРОН")) is True

    @pytest.mark.asyncio
    async def test_war_word_with_punctuation(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "!!!дрон!!!")) is True

    # ── Non-text messages ──

    @pytest.mark.asyncio
    async def test_photo_message_filter_checks(self, make_message):
        msg = make_message(479167456, text=None)
        msg.from_user.id = 479167456

        assert await KuchaWordFilter()(msg) is False
        assert await WarWordFilter()(msg) is False
        assert await UserIdFilter(479167456)(msg) is True

    @pytest.mark.asyncio
    async def test_photo_with_caption_war_word(self, make_message):
        """Photo with war keyword in caption should match WarWordFilter."""
        msg = make_message(479167456, text=None)
        msg.caption = "опасность атаки"
        assert await WarWordFilter()(msg) is True

    @pytest.mark.asyncio
    async def test_photo_with_caption_no_keyword(self, make_message):
        """Photo with caption but no war keyword should not match."""
        msg = make_message(479167456, text=None)
        msg.caption = "красивый закат"
        assert await WarWordFilter()(msg) is False

    @pytest.mark.asyncio
    async def test_caption_none_war_filter(self, make_message):
        """Message with text=None and no caption should not match."""
        msg = make_message(479167456, text=None)
        msg.caption = None
        assert await WarWordFilter()(msg) is False

    # ── Router priority simulation ──

    @pytest.mark.asyncio
    async def test_priority_slavik_before_kostik(self, make_message):
        msg = make_message(479167456, text="куча дрон")
        
        kucha = await KuchaWordFilter()(msg)
        war = await WarWordFilter()(msg)
        
        assert kucha is True
        assert war is True

    @pytest.mark.asyncio
    async def test_same_message_all_slavik_handlers(self, make_message):
        msg = make_message(479167456, text="куча дронов")
        
        assert await KuchaWordFilter()(msg) is True
        assert await WarWordFilter()(msg) is True

    @pytest.mark.asyncio
    async def test_slavik_catchall_always_true(self, make_message):
        f = UserIdFilter(479167456)
        
        assert await f(make_message(479167456, text="hello")) is True
        assert await f(make_message(479167456, text=None)) is True
        assert await f(make_message(479167456)) is True
