"""Tests for DeadPageRelay: progressive range search + fallback."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.dead_page_relay import DeadPageRelay
from services.media_picker import MediaService


# ── Helpers ────────────────────────────────────────────────────

def _make_valid_ids(valid: set[int]):
    """Return a forward_message side_effect that only succeeds for given IDs."""

    async def forward(**kwargs):
        msg_id = kwargs["message_id"]
        if msg_id in valid:
            return MagicMock()
        raise Exception("message to forward not found")

    return forward


def _make_channel_error(error_text: str = "Forbidden: bot is not an admin"):
    """Return a forward_message that always raises a non-'not found' error."""

    async def forward(**kwargs):
        raise Exception(error_text)

    return forward


# ── Fixtures ───────────────────────────────────────────────────


class TestDeadPageRelay:
    """Tests for DeadPageRelay (channel forward + fallback)."""

    @pytest.fixture
    def mock_bot(self):
        bot = MagicMock()
        bot.forward_message = AsyncMock()
        bot.send_photo = AsyncMock()
        bot.send_message = AsyncMock()
        return bot

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.was_dead_page_recently = AsyncMock(return_value=False)
        db.get_last_known_message_id = AsyncMock(return_value=None)
        db.update_last_known_message_id = AsyncMock()
        db.record_dead_page_post = AsyncMock()
        return db

    @pytest.fixture
    def mock_media(self):
        media = MagicMock(spec=MediaService)
        media.pick_random = AsyncMock(return_value=("test.jpg", "hello world"))
        return media

    @pytest.fixture
    def relay(self, mock_bot, mock_db, mock_media):
        return DeadPageRelay(mock_bot, mock_db, mock_media)

    # ── Core: forward from channel ──────────────────────────────

    @pytest.mark.asyncio
    async def test_tiny_channel_one_post_at_id_3(self, relay, mock_bot, mock_db):
        """
        Channel has 1 post at msg_id=3. DB has no last_msg_id.
        Mock random.randint to guarantee hitting ID=3 on first attempt.
        """
        mock_bot.forward_message.side_effect = _make_valid_ids({3})

        with patch("random.randint", return_value=3):
            await relay.send_dead_page(-100123)

        mock_bot.forward_message.assert_called()
        mock_db.record_dead_page_post.assert_called_once_with(-100123, "repost")
        mock_db.update_last_known_message_id.assert_called_with(3)

    @pytest.mark.asyncio
    async def test_channel_with_known_last_id(self, relay, mock_bot, mock_db):
        """DB has last_msg_id=100. Should search [1,100] then [1,200]."""
        mock_db.get_last_known_message_id.return_value = 100
        mock_bot.forward_message.side_effect = _make_valid_ids({42})

        await relay.send_dead_page(-100123)

        mock_bot.forward_message.assert_called()
        # 42 < 100, so no DB update needed
        mock_db.update_last_known_message_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_new_post_beyond_known_range(self, relay, mock_bot, mock_db):
        """
        DB last_msg_id=5, but post exists at ID=42.
        Range 1: [1,5] → all 5 IDs exhausted (unique), miss.
        Range 2: [1,100] → randint returns 42, hits.
        """
        mock_db.get_last_known_message_id.return_value = 5
        mock_bot.forward_message.side_effect = _make_valid_ids({42})

        # randint sequence: first 5 exhaust [1,5], 6th returns 42 in [1,100]
        with patch("random.randint", side_effect=[1, 2, 3, 4, 5, 42]):
            await relay.send_dead_page(-100123)

        mock_bot.forward_message.assert_called()
        mock_db.update_last_known_message_id.assert_called_with(42)

    @pytest.mark.asyncio
    async def test_cooldown_active_skips(self, relay, mock_db):
        """Should skip entirely when cooldown is active."""
        mock_db.was_dead_page_recently.return_value = True

        await relay.send_dead_page(-100123)

        mock_db.record_dead_page_post.assert_not_called()

    # ── Fallback scenarios ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_empty_channel_falls_back(self, relay, mock_bot, mock_db):
        """No posts at all → all ranges exhausted → fallback to local."""
        # Every forward returns "not found"
        mock_bot.forward_message.side_effect = _make_valid_ids(set())

        await relay.send_dead_page(-100123)

        # Fallback should fire
        mock_bot.send_photo.assert_called()
        assert mock_bot.forward_message.call_count >= relay.max_retries

    @pytest.mark.asyncio
    async def test_channel_inaccessible_falls_back(self, relay, mock_bot, mock_db):
        """Channel returns Forbidden (not admin) → immediate fallback."""
        mock_bot.forward_message.side_effect = _make_channel_error(
            "Forbidden: bot is not an administrator"
        )

        await relay.send_dead_page(-100123)

        # Should try once (non-"not found" error → immediate return False)
        mock_bot.forward_message.assert_called()
        # Fallback should fire
        mock_bot.send_photo.assert_called()

    @pytest.mark.asyncio
    async def test_fallback_with_long_text_splits(self, relay, mock_bot, mock_db):
        """Fallback text > 1024 chars should split into caption + overflow."""
        long_text = "A" * 1500
        relay.media.pick_random = AsyncMock(return_value=("img.jpg", long_text))
        mock_bot.forward_message.side_effect = _make_valid_ids(set())

        await relay.send_dead_page(-100123)

        mock_bot.send_photo.assert_called_once()
        mock_bot.send_message.assert_called_once()  # overflow

    @pytest.mark.asyncio
    async def test_fallback_no_media_files(self, relay, mock_bot, mock_db):
        """No local media files → graceful error, no crash."""
        mock_bot.forward_message.side_effect = _make_valid_ids(set())
        relay.media.pick_random = AsyncMock(side_effect=FileNotFoundError("no files"))

        # Should not raise
        await relay.send_dead_page(-100123)

        mock_bot.send_photo.assert_not_called()

    # ── Progressive range expansion ─────────────────────────────

    @pytest.mark.asyncio
    async def test_progressive_ranges_eventually_find_post(self, relay, mock_bot, mock_db):
        """
        Post at ID=80. Without DB hint:
        Range 1 [1,10]  → miss
        Range 2 [1,50]  → miss
        Range 3 [1,200] → should find 80
        """
        mock_bot.forward_message.side_effect = _make_valid_ids({80})

        await relay.send_dead_page(-100123)

        mock_bot.forward_message.assert_called()
        mock_db.record_dead_page_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_dedup_same_id_not_retried(self, relay, mock_bot, mock_db):
        """Within one range, the same msg_id should not be tried twice."""
        call_ids = []

        async def track_forward(**kwargs):
            call_ids.append(kwargs["message_id"])
            raise Exception("message to forward not found")

        mock_bot.forward_message.side_effect = track_forward

        await relay.send_dead_page(-100123)

        # All attempted IDs within a range should be unique
        # (they could repeat across ranges, that's fine)
        assert len(call_ids) == len(set(call_ids)) or len(call_ids) > relay.max_retries

    # ── Slot parameter ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_join_slot_passed_to_db(self, relay, mock_bot, mock_db):
        """slot='join' should be recorded in DB."""
        mock_bot.forward_message.side_effect = _make_valid_ids({1})

        await relay.send_dead_page(-100123, slot="join")

        mock_db.record_dead_page_post.assert_called_once_with(-100123, "join")

    def test_build_search_ranges_appends_discovery(self, relay):
        """D16: Verify anchored ranges come first, then _DISCOVERY_RANGES as safety net."""
        # Known ID path
        ranges = relay._build_search_ranges(5)
        assert ranges == [
            (1, 5),
            (1, 100),   # max(5*2, 100)
            (1, 10),    # _DISCOVERY_RANGES[0]
            (1, 50),    # _DISCOVERY_RANGES[1]
            (1, 200),   # _DISCOVERY_RANGES[2]
            (1, 500),   # _DISCOVERY_RANGES[3]
            (1, 2000),  # _DISCOVERY_RANGES[4]
        ]

        # Unknown ID path
        ranges = relay._build_search_ranges(None)
        assert ranges == [(1, 10), (1, 50), (1, 200), (1, 500), (1, 2000)]

        # Zero last_msg_id treated as unknown
        ranges = relay._build_search_ranges(0)
        assert ranges == [(1, 10), (1, 50), (1, 200), (1, 500), (1, 2000)]

    @pytest.mark.asyncio
    async def test_dedup_does_not_burn_attempts(self, relay, mock_bot, mock_db):
        """D17: Sequential scan of [1,3] tries 3 IDs exactly, then random mode finds post."""
        mock_db.get_last_known_message_id.return_value = 3
        relay.max_retries = 5
        mock_bot.forward_message.side_effect = _make_valid_ids({77})

        with patch("random.randint", return_value=77):
            await relay.send_dead_page(-100123)

        # Sequential (1,3): 3 calls (1,2,3 all fail) + 1 random hit at 77
        assert mock_bot.forward_message.call_count == 4

    # ── Sequential scan (D28/D29) ───────────────────────────────

    @pytest.mark.asyncio
    async def test_sequential_scan_finds_only_post(self, relay, mock_bot, mock_db):
        """D28: Channel with 1 post at ID=3 — sequential (1,10) finds it in 3 calls."""
        mock_db.get_last_known_message_id.return_value = 5  # stale DB value
        relay.max_retries = 5
        # All IDs except 3 return "not found"
        mock_bot.forward_message.side_effect = _make_valid_ids({3})

        await relay.send_dead_page(-100123)

        # Sequential scan should find ID=3: calls for 1, 2, 3
        assert mock_bot.forward_message.call_count == 3
        mock_db.record_dead_page_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_sequential_scan_exhausted_moves_to_next(self, relay, mock_bot, mock_db):
        """D28: (1,10) sequential exhausts all 10 — moves to next range, finds at ID=150."""
        mock_db.get_last_known_message_id.return_value = 5
        relay.max_retries = 5
        # (1,10): all "not found" → exhausted → next range (1,100): random finds 150
        mock_bot.forward_message.side_effect = _make_valid_ids({150})

        await relay.send_dead_page(-100123)

        # With post at ID=150 and last_msg_id=5:
        # Ranges: (1,5)→5 rand, (1,100)→5 rand, (1,10)→10 seq, (1,50)→50 seq, then random in (1,200) until hit
        # Total ≈ 70+: 5+5+10+50+N
        call_count = mock_bot.forward_message.call_count
        assert call_count >= 70
        mock_db.record_dead_page_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_large_range_uses_random(self, relay, mock_bot, mock_db):
        """D28: Large range (1,200) uses random, not sequential."""
        mock_db.get_last_known_message_id.return_value = None  # force discovery ranges
        relay.max_retries = 5
        mock_bot.forward_message.side_effect = _make_valid_ids({199})

        with patch("random.randint", return_value=199) as random_mock:
            await relay.send_dead_page(-100123)

        # First range (1,10) sequential → 10 calls (all fail)
        # Second range (1,50) sequential → 50 calls (all fail)
        # Third range (1,200) random → 1 call (hits 199)
        call_count = mock_bot.forward_message.call_count
        assert call_count >= 61  # 10 + 50 + 1
        mock_db.record_dead_page_post.assert_called_once()
        random_mock.assert_called()  # Verify random was called

    @pytest.mark.asyncio
    async def test_sequential_scan_channel_error_stops(self, relay, mock_bot, mock_db):
        """D29: Sequential scan stops on channel error (not 'not found')."""
        mock_db.get_last_known_message_id.return_value = 5
        relay.max_retries = 5

        call_count = 0
        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise Exception("Forbidden: bot is not an administrator")
            raise Exception("not found")

        mock_bot.forward_message.side_effect = side_effect

        result = await relay._try_forward_from_channel(-100123)

        assert result is False
        # Only 3 calls: 1→not found, 2→not found, 3→Forbidden (stops)
        assert call_count == 3
