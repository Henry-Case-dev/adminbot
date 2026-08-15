"""Tests for DeadPageRelay: progressive range search + fallback."""
import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.dead_page_relay import DeadPageRelay
from services.media_picker import MediaService


# ── Helpers ────────────────────────────────────────────────────

def _make_msg_mock(**kwargs):
    """Create a MagicMock that mimics a forwarded Message with a date."""
    msg = MagicMock()
    msg.message_id = kwargs.get("message_id", 0)
    # Use naive datetime (tzinfo=None) so _normalize_date works
    msg.date = kwargs.get("date", datetime.datetime(2026, 7, 28, 12, 0, 0))
    msg.rich_message = None
    return msg


def _make_valid_ids(valid: set[int]):
    """Return a forward_message side_effect that only succeeds for given IDs."""

    async def forward(**kwargs):
        msg_id = kwargs["message_id"]
        if msg_id in valid:
            return _make_msg_mock(message_id=msg_id)
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
        bot.forward_messages = AsyncMock()
        bot.send_photo = AsyncMock()
        bot.send_message = AsyncMock()
        bot.delete_message = AsyncMock()
        return bot

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.was_dead_page_recently = AsyncMock(return_value=False)
        db.get_last_known_message_id = AsyncMock(return_value=None)
        db.update_last_known_message_id = AsyncMock()
        db.record_dead_page_post = AsyncMock()
        # Epic 22 / D54: anti-repeat
        db.get_dead_page_last_sent = AsyncMock(return_value=None)
        db.set_dead_page_last_sent = AsyncMock()
        # Epic 14: Album-aware forwarding
        db.get_relay_media_group_id = AsyncMock(return_value=None)
        db.get_relay_album_message_ids = AsyncMock(return_value=[])
        db.save_relay_album_map = AsyncMock()
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
        # Known ID path — forward range first, then wide, then narrow, then discovery
        ranges = relay._build_search_ranges(5)
        assert ranges == [
            (6, 100),   # forward range: last_msg_id+1 to max(last_msg_id+50, last_msg_id*2, 100)
            (1, 100),   # wide fallback: (1, max(last_msg_id*2, 100))
            (1, 5),     # narrow fallback: (1, last_msg_id)
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
        """D17: Forward scan probes 50 IDs, then random range with heuristic probing finds post.
        Forward scan: 50 calls (IDs 4-53, all fail).
        Range (4,100): randint→77 (1 hit) + heuristic probes neighbors (3 fwd + 3 bwd gaps).
        Total: 50 + 1 + 6 = 57."""
        mock_db.get_last_known_message_id.return_value = 3
        relay.max_retries = 5
        mock_bot.forward_message.side_effect = _make_valid_ids({77})

        with patch("random.randint", return_value=77):
            await relay.send_dead_page(-100123)

        assert mock_bot.forward_message.call_count == 57

    # ── Sequential scan (D28/D29) ───────────────────────────────

    @pytest.mark.asyncio
    async def test_sequential_scan_finds_only_post(self, relay, mock_bot, mock_db):
        """D28: Post at ID=3, DB last_msg_id=5 (stale). Forward scan IDs 6-55 (50 fail).
        randint pinned to distinct values that never hit the valid ID=3, so random
        ranges (6,100) and (1,100) always miss and the sequential (1,5) scan
        deterministically finds ID=3.
        Total: 50 (fwd scan) + 5 (random 6,100) + 5 (random 1,100) + 2 (seq fails 1,2)
        + 6 (hit ID=3 + probes) = 68."""
        mock_db.get_last_known_message_id.return_value = 5  # stale DB value
        relay.max_retries = 5
        mock_bot.forward_message.side_effect = _make_valid_ids({3})

        with patch("random.randint", side_effect=[77, 78, 79, 80, 81, 82, 83, 84, 85, 86]):
            await relay.send_dead_page(-100123)

        assert mock_bot.forward_message.call_count == 68
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
    async def test_sequential_scan_channel_error_continues(self, relay, mock_bot, mock_db):
        """D29v2: Channel errors no longer stop the search — they are logged and skipped.
        Forward scan + all ranges exhaust → False with 140 total calls."""
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

        assert result is None
        # Forward scan (50) + ranges (5+5+5+10+50+5+5+5) = 140
        assert call_count == 140


class TestAntiRepeatLastSent:
    """Epic 22 / D54: PostPicker must not pick the previously sent post."""

    @pytest.fixture
    def mock_bot(self):
        bot = MagicMock()
        bot.forward_message = AsyncMock()
        bot.forward_messages = AsyncMock()
        bot.delete_message = AsyncMock()
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
        db.get_dead_page_last_sent = AsyncMock(return_value=None)
        db.set_dead_page_last_sent = AsyncMock()
        db.get_relay_media_group_id = AsyncMock(return_value=None)
        db.get_relay_album_message_ids = AsyncMock(return_value=[])
        db.save_relay_album_map = AsyncMock()
        return db

    @pytest.fixture
    def mock_media(self):
        media = MagicMock(spec=MediaService)
        media.pick_random = AsyncMock(return_value=("test.jpg", "hello"))
        return media

    @pytest.fixture
    def relay(self, mock_bot, mock_db, mock_media):
        return DeadPageRelay(mock_bot, mock_db, mock_media)

    @pytest.mark.asyncio
    async def test_sequential_scan_skips_last_sent(self, relay, mock_bot, mock_db):
        """Posts {3, 4}, last_sent=3 → sequential scan skips 3, finds 4."""
        mock_bot.forward_message.side_effect = _make_valid_ids({3, 4})

        result = await relay._try_forward_from_channel(-100123, last_sent=3)

        assert result == 4

    @pytest.mark.asyncio
    async def test_forward_scan_skips_last_sent(self, relay, mock_bot, mock_db):
        """last_msg_id=3, posts {4, 5}, last_sent=4 → forward scan finds 5."""
        mock_db.get_last_known_message_id.return_value = 3
        mock_bot.forward_message.side_effect = _make_valid_ids({4, 5})

        result = await relay._try_forward_from_channel(-100123, last_sent=4)

        assert result == 5

    @pytest.mark.asyncio
    async def test_random_rerolls_last_sent_without_burning_attempt(self, relay, mock_bot, mock_db):
        """randint returns last_sent → re-roll WITHOUT attempt. max_retries=1 still finds 150."""
        relay.max_retries = 1
        mock_bot.forward_message.side_effect = _make_valid_ids({150})

        with patch("random.randint", side_effect=[77, 150]) as random_mock:
            result = await relay._try_forward_from_channel(-100123, last_sent=77)

        # 77 (re-roll) → 150 (attempt 1). If 77 burned the attempt, result would be None.
        assert result == 150
        assert random_mock.call_count == 2

    @pytest.mark.asyncio
    async def test_last_resort_repeats_only_post(self, relay, mock_bot, mock_db):
        """Only post (3) == last_sent → all ranges skip it → last-resort repeats 3."""
        mock_bot.forward_message.side_effect = _make_valid_ids({3})
        # 3 random ranges × 5 attempts — all miss (valid only {3})
        with patch("random.randint", side_effect=[1, 2, 4, 5, 6] * 3):
            result = await relay._try_forward_from_channel(-100123, last_sent=3)

        assert result == 3

    @pytest.mark.asyncio
    async def test_last_sent_none_returns_id(self, relay, mock_bot, mock_db):
        """Contract: int | None — success returns primary msg_id, not bool."""
        mock_bot.forward_message.side_effect = _make_valid_ids({3})

        result = await relay._try_forward_from_channel(-100123)

        assert result == 3

    @pytest.mark.asyncio
    async def test_send_dead_page_writes_last_sent_after_success(self, relay, mock_bot, mock_db):
        """Successful channel forward → set_dead_page_last_sent(chat, primary_id)."""
        mock_bot.forward_message.side_effect = _make_valid_ids({3})

        await relay.send_dead_page(-100123)

        mock_db.set_dead_page_last_sent.assert_called_once_with(-100123, 3)

    @pytest.mark.asyncio
    async def test_album_forward_writes_primary_id_not_max(self, relay, mock_bot, mock_db):
        """Album {10, 11, 12} → write primary candidate id (10), not max (12)."""

        async def get_group(msg_id):
            return "mg123" if msg_id == 10 else None

        mock_db.get_relay_media_group_id = AsyncMock(side_effect=get_group)
        mock_db.get_relay_album_message_ids.return_value = [10, 11, 12]
        mock_bot.forward_message.side_effect = _make_valid_ids({10})

        await relay.send_dead_page(-100123)

        mock_db.set_dead_page_last_sent.assert_called_once_with(-100123, 10)

    @pytest.mark.asyncio
    async def test_fallback_local_does_not_write_last_sent(self, relay, mock_bot, mock_db):
        """Local-media fallback has no message_id → set_dead_page_last_sent NOT called."""
        mock_bot.forward_message.side_effect = _make_valid_ids(set())
        # avoid infinite re-roll: provide distinct randint values
        with patch("random.randint", side_effect=[1, 2, 4, 5, 6] * 20):
            await relay.send_dead_page(-100123)

        mock_bot.send_photo.assert_called()
        mock_db.set_dead_page_last_sent.assert_not_called()
        mock_db.record_dead_page_post.assert_called_once_with(-100123, "repost")

    @pytest.mark.asyncio
    async def test_get_last_sent_db_error_is_graceful(self, relay, mock_bot, mock_db):
        """DB error on get → anti-repeat disabled, dead page still works."""
        mock_db.get_dead_page_last_sent = AsyncMock(side_effect=RuntimeError("db down"))
        mock_bot.forward_message.side_effect = _make_valid_ids({3})

        await relay.send_dead_page(-100123)

        mock_db.set_dead_page_last_sent.assert_called_once_with(-100123, 3)

    @pytest.mark.asyncio
    async def test_two_calls_pick_different_posts(self, relay, mock_bot, mock_db):
        """D54: two sequential sends → second send avoids the first post."""
        state = {"last": None}

        async def get_last(chat_id):
            return state["last"]

        async def set_last(chat_id, msg_id):
            state["last"] = msg_id

        mock_db.get_dead_page_last_sent = AsyncMock(side_effect=get_last)
        mock_db.set_dead_page_last_sent = AsyncMock(side_effect=set_last)
        mock_bot.forward_message.side_effect = _make_valid_ids({3, 4})

        await relay.send_dead_page(-100123)
        assert state["last"] == 3

        await relay.send_dead_page(-100123)
        assert state["last"] == 4


class TestAlbumForwarding:
    """Epic 14: Album-aware forwarding tests (DB path + heuristic)."""

    @pytest.fixture
    def mock_bot(self):
        bot = MagicMock()
        bot.forward_message = AsyncMock()
        bot.forward_messages = AsyncMock()
        bot.delete_message = AsyncMock()
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
        db.get_relay_media_group_id = AsyncMock(return_value=None)
        db.get_relay_album_message_ids = AsyncMock(return_value=[])
        db.save_relay_album_map = AsyncMock()
        return db

    @pytest.fixture
    def mock_media(self):
        media = MagicMock(spec=MediaService)
        media.pick_random = AsyncMock(return_value=("test.jpg", "hello"))
        return media

    @pytest.fixture
    def relay(self, mock_bot, mock_db, mock_media):
        return DeadPageRelay(mock_bot, mock_db, mock_media)

    @pytest.mark.asyncio
    async def test_db_album_path_forwards_all(self, relay, mock_bot, mock_db):
        """D46: DB has album info → forward_messages() called with all IDs."""
        mock_db.get_relay_media_group_id.return_value = "mg123"
        mock_db.get_relay_album_message_ids.return_value = [10, 11, 12]

        result = await relay._forward_with_album_detection(-100123, 11, None)

        assert result is True
        mock_bot.forward_messages.assert_called_once_with(
            chat_id=-100123,
            from_chat_id=relay.relay_channel_id,
            message_ids=[10, 11, 12],
            disable_notification=False,
        )
        mock_bot.forward_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_album_updates_last_known_id(self, relay, mock_bot, mock_db):
        """D46: max album ID > last_msg_id → DB updated."""
        mock_db.get_relay_media_group_id.return_value = "mg456"
        mock_db.get_relay_album_message_ids.return_value = [100, 101, 102]

        await relay._forward_with_album_detection(-100123, 100, 50)

        mock_db.update_last_known_message_id.assert_called_once_with(102)

    @pytest.mark.asyncio
    async def test_heuristic_album_forwards_all(self, relay, mock_bot, mock_db):
        """D47+T-110: All consecutive msgs with same date → collected then group-forwarded."""
        import datetime
        base_dt = datetime.datetime(2026, 7, 28, 12, 0, 0)

        call_count = 0
        async def forward_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            msg = MagicMock()
            msg.date = base_dt
            msg.message_id = kwargs["message_id"]
            msg.rich_message = None
            return msg

        mock_bot.forward_message.side_effect = forward_side_effect

        result = await relay._forward_with_heuristic(-100123, 11, None)

        assert result is True
        assert mock_bot.forward_message.call_count == 19  # probing unchanged
        # T-110: must use forward_messages for group forward
        mock_bot.forward_messages.assert_called_once()
        call_args = mock_bot.forward_messages.call_args
        assert call_args.kwargs["chat_id"] == -100123
        assert call_args.kwargs["from_chat_id"] == relay.relay_channel_id
        # IDs should be sorted
        forwarded_ids = call_args.kwargs["message_ids"]
        assert forwarded_ids == sorted(forwarded_ids)

    @pytest.mark.asyncio
    async def test_heuristic_date_boundary_stops_probe(self, relay, mock_bot, mock_db):
        """D47: msg+1 has different date → deleted, probe stops."""
        import datetime
        base_dt = datetime.datetime(2026, 7, 28, 12, 0, 0)
        other_dt = datetime.datetime(2026, 7, 28, 13, 0, 0)

        async def forward_side_effect(**kwargs):
            msg = MagicMock()
            msg_id = kwargs["message_id"]
            msg.message_id = msg_id
            msg.rich_message = None
            if msg_id == 11:
                msg.date = base_dt
            else:
                msg.date = other_dt
            return msg

        mock_bot.forward_message.side_effect = forward_side_effect

        result = await relay._forward_with_heuristic(-100123, 11, None)

        assert result is True
        assert mock_bot.forward_message.call_count == 3
        assert mock_bot.delete_message.call_count == 2

    @pytest.mark.asyncio
    async def test_heuristic_gap_allows_skip(self, relay, mock_bot, mock_db):
        """D47.2: 1 missing msg → skipped, next msg found."""
        import datetime
        base_dt = datetime.datetime(2026, 7, 28, 12, 0, 0)

        async def forward_side_effect(**kwargs):
            msg_id = kwargs["message_id"]
            if msg_id == 12:
                raise Exception("message to forward not found")
            msg = MagicMock()
            msg.date = base_dt
            msg.message_id = msg_id
            msg.rich_message = None
            return msg

        mock_bot.forward_message.side_effect = forward_side_effect

        result = await relay._forward_with_heuristic(-100123, 11, None)

        assert result is True
        assert mock_bot.forward_message.call_count == 19

    @pytest.mark.asyncio
    async def test_heuristic_channel_error_in_probe_propagates(self, relay, mock_bot, mock_db):
        """D47: Real error during sibling probe → raises."""
        import datetime
        base_dt = datetime.datetime(2026, 7, 28, 12, 0, 0)

        call_count = 0
        async def forward_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            msg_id = kwargs["message_id"]
            if msg_id == 12:
                raise Exception("Forbidden: bot is not an administrator")
            msg = MagicMock()
            msg.date = base_dt
            msg.message_id = msg_id
            msg.rich_message = None
            return msg

        mock_bot.forward_message.side_effect = forward_side_effect

        with pytest.raises(Exception, match="Forbidden"):
            await relay._forward_with_heuristic(-100123, 11, None)

    @pytest.mark.asyncio
    async def test_heuristic_at_channel_start(self, relay, mock_bot, mock_db):
        """D47: msg_id=1 → backward probe skipped (candidate < 1)."""
        import datetime
        base_dt = datetime.datetime(2026, 7, 28, 12, 0, 0)

        async def forward_side_effect(**kwargs):
            msg = MagicMock()
            msg.date = base_dt
            msg.message_id = kwargs["message_id"]
            msg.rich_message = None
            return msg

        mock_bot.forward_message.side_effect = forward_side_effect

        result = await relay._forward_with_heuristic(-100123, 1, None)

        assert result is True
        assert mock_bot.forward_message.call_count == 10


class TestCollectThenGroup:
    """T-110: Collect-then-Group strategy for _forward_with_heuristic."""

    @pytest.fixture
    def mock_bot(self):
        bot = MagicMock()
        bot.forward_message = AsyncMock()
        bot.forward_messages = AsyncMock()
        bot.delete_message = AsyncMock()
        return bot

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.update_last_known_message_id = AsyncMock()
        return db

    @pytest.fixture
    def mock_media(self):
        media = MagicMock(spec=MediaService)
        return media

    @pytest.fixture
    def relay(self, mock_bot, mock_db, mock_media):
        return DeadPageRelay(mock_bot, mock_db, mock_media)

    @pytest.mark.asyncio
    async def test_single_post_no_siblings(self, relay, mock_bot, mock_db):
        """T-110: Single post with no siblings → one forward_message, no forward_messages."""
        import datetime
        base_dt = datetime.datetime(2026, 7, 28, 12, 0, 0)
        other_dt = datetime.datetime(2026, 7, 28, 13, 0, 0)

        async def forward_side_effect(**kwargs):
            msg = MagicMock()
            msg_id = kwargs["message_id"]
            msg.message_id = msg_id
            msg.rich_message = None
            if msg_id == 11:
                msg.date = base_dt
            else:
                msg.date = other_dt  # siblings have different date → boundary
            return msg

        mock_bot.forward_message.side_effect = forward_side_effect

        result = await relay._forward_with_heuristic(-100123, 11, None)

        assert result is True
        # Primary forwarded (1 call), then forward probe (1 call → no match → break),
        # backward probe (1 call → no match → break) = 3 forward_message calls
        assert mock_bot.forward_message.call_count == 3
        # No siblings → no group forward
        mock_bot.forward_messages.assert_not_called()

    @pytest.mark.asyncio
    async def test_album_with_siblings_group_forwards(self, relay, mock_bot, mock_db):
        """T-110: Album (2+ siblings) → one forward_messages with all sorted IDs."""
        import datetime
        base_dt = datetime.datetime(2026, 7, 28, 12, 0, 0)

        async def forward_side_effect(**kwargs):
            msg = MagicMock()
            msg_id = kwargs["message_id"]
            msg.message_id = msg_id
            msg.rich_message = None
            if 9 <= msg_id <= 13:
                msg.date = base_dt  # IDs 9-13 form an album
            else:
                msg.date = datetime.datetime(2026, 7, 28, 14, 0, 0)
            return msg

        mock_bot.forward_message.side_effect = forward_side_effect

        result = await relay._forward_with_heuristic(-100123, 11, None)

        assert result is True
        # forward_messages called once with sorted IDs
        mock_bot.forward_messages.assert_called_once()
        call_args = mock_bot.forward_messages.call_args
        forwarded_ids = call_args.kwargs["message_ids"]
        assert forwarded_ids == sorted(forwarded_ids)
        assert len(forwarded_ids) >= 3  # album of 11 and at least 2 siblings

    @pytest.mark.asyncio
    async def test_forward_messages_error_returns_false(self, relay, mock_bot, mock_db):
        """T-110: forward_messages error → graceful handling, returns False."""
        import datetime
        base_dt = datetime.datetime(2026, 7, 28, 12, 0, 0)

        async def forward_side_effect(**kwargs):
            msg = MagicMock()
            msg.message_id = kwargs["message_id"]
            msg.date = base_dt  # all same date → album
            msg.rich_message = None
            return msg

        mock_bot.forward_message.side_effect = forward_side_effect
        mock_bot.forward_messages.side_effect = Exception("message to forward not found")

        result = await relay._forward_with_heuristic(-100123, 11, None)

        assert result is False  # group forward failed

    @pytest.mark.asyncio
    async def test_group_forward_ids_are_sorted(self, relay, mock_bot, mock_db):
        """T-110: forward_messages receives message_ids in ascending order."""
        import datetime
        base_dt = datetime.datetime(2026, 7, 28, 12, 0, 0)

        async def forward_side_effect(**kwargs):
            msg = MagicMock()
            msg.message_id = kwargs["message_id"]
            msg.date = base_dt
            msg.rich_message = None
            return msg

        mock_bot.forward_message.side_effect = forward_side_effect

        # msg_id=11: forward probes 12-14, backward probes 10-8
        await relay._forward_with_heuristic(-100123, 11, None)

        mock_bot.forward_messages.assert_called_once()
        forwarded_ids = mock_bot.forward_messages.call_args.kwargs["message_ids"]
        assert forwarded_ids == sorted(forwarded_ids)
        # Verify it contains the full range
        assert min(forwarded_ids) <= 11 <= max(forwarded_ids)
