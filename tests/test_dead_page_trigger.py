import pytest
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import Message, Chat, User, MessageOriginChannel
from filters.user_id import UserIdFilter
from handlers.dead_page_trigger import on_forward, setup_dead_page
from config.settings import settings


class TestDeadPageTrigger:
    """Tests for dead_page_trigger handler (Epic 22 / D53: only Slava's reposts)."""

    @pytest.fixture(autouse=True)
    def _reset_dedup_state(self):
        """Сброс dedup-состояния между тестами (модульные OrderedDict/dict)."""
        import handlers.dead_page_trigger as dpt
        dpt._seen_media_groups.clear()
        dpt._media_group_bot_ids.clear()
        dpt._pending_media_group_ids.clear()
        yield
        dpt._seen_media_groups.clear()
        dpt._media_group_bot_ids.clear()
        dpt._pending_media_group_ids.clear()

    def make_forward_message(self, username="d_pages", chat_id=-100123,
                             user_id=None):
        """Create a Message with forward_origin from a channel."""
        if user_id is None:
            user_id = settings.SLAVIK_USER_ID
        user = User(id=user_id, is_bot=False, first_name="Test")
        chat_obj = Chat(id=chat_id, type="group")
        origin_chat = Chat(id=-100999, type="channel", username=username)
        origin = MessageOriginChannel(
            type="channel",
            date=1234567890,
            chat=origin_chat,
            message_id=42,
        )
        msg = Message(
            message_id=1,
            date=1234567890,
            chat=chat_obj,
            from_user=user,
            forward_origin=origin,
        )
        return msg

    @pytest.fixture
    def mock_relay(self):
        relay = MagicMock()
        relay.send_dead_page = AsyncMock()
        return relay

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.is_present = AsyncMock(return_value=True)
        return db

    @pytest.mark.asyncio
    async def test_triggers_on_d_pages_repost(self, mock_relay, mock_db):
        """Should detect repost from @d_pages and send dead page."""
        setup_dead_page(mock_relay, mock_db)
        msg = self.make_forward_message(username="d_pages")
        await on_forward(msg)
        mock_relay.send_dead_page.assert_called_once_with(-100123, slot="repost")

    @pytest.mark.asyncio
    async def test_ignores_other_channels(self, mock_relay, mock_db):
        """Should not trigger for reposts from other channels."""
        setup_dead_page(mock_relay, mock_db)
        msg = self.make_forward_message(username="other_channel")
        await on_forward(msg)
        mock_relay.send_dead_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_check_presence(self, mock_relay, mock_db):
        """D53: is_present gate removed — a repost by Slava implies presence."""
        setup_dead_page(mock_relay, mock_db)
        mock_db.is_present.return_value = False
        msg = self.make_forward_message(username="d_pages")
        await on_forward(msg)
        mock_relay.send_dead_page.assert_called_once_with(-100123, slot="repost")
        mock_db.is_present.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_id_filter_accepts_slavik(self):
        """D53: router filter passes reposts from Slava."""
        f = UserIdFilter(settings.SLAVIK_USER_ID)
        msg = self.make_forward_message(username="d_pages",
                                        user_id=settings.SLAVIK_USER_ID)
        assert await f(msg) is True

    @pytest.mark.asyncio
    async def test_user_id_filter_rejects_non_slavik(self):
        """D53: router filter rejects reposts from anyone else."""
        f = UserIdFilter(settings.SLAVIK_USER_ID)
        msg = self.make_forward_message(username="d_pages", user_id=111)
        assert await f(msg) is False

    @pytest.mark.asyncio
    async def test_no_crash_when_relay_not_setup(self, mock_db):
        """Should not crash if relay is not initialized."""
        setup_dead_page(None, mock_db)
        msg = self.make_forward_message(username="d_pages")
        await on_forward(msg)

    @pytest.mark.asyncio
    async def test_media_group_dedup_skips_duplicates(self, mock_relay, mock_db):
        """D48: Second msg with same media_group_id within 5s → skipped."""
        setup_dead_page(mock_relay, mock_db)

        msg1 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg1, "media_group_id", "mg_test_123")

        msg2 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg2, "media_group_id", "mg_test_123")

        await on_forward(msg1)
        mock_relay.send_dead_page.assert_called_once_with(-100123, slot="repost")

        mock_relay.send_dead_page.reset_mock()

        await on_forward(msg2)
        mock_relay.send_dead_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_media_group_dedup_allows_first(self, mock_relay, mock_db):
        """D48: First msg with media_group_id is NOT skipped."""
        setup_dead_page(mock_relay, mock_db)

        msg = self.make_forward_message(username="d_pages")
        object.__setattr__(msg, "media_group_id", "mg_first_456")

        await on_forward(msg)
        mock_relay.send_dead_page.assert_called_once_with(-100123, slot="repost")

    @pytest.mark.asyncio
    async def test_media_group_dedup_different_groups(self, mock_relay, mock_db):
        """D48: Different media_group_ids → both trigger."""
        setup_dead_page(mock_relay, mock_db)

        msg1 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg1, "media_group_id", "mg_aaa")

        msg2 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg2, "media_group_id", "mg_bbb")

        await on_forward(msg1)
        assert mock_relay.send_dead_page.call_count == 1

        await on_forward(msg2)
        assert mock_relay.send_dead_page.call_count == 2

    @pytest.mark.asyncio
    async def test_no_media_group_id_still_triggers(self, mock_relay, mock_db):
        """Non-album forwards (no media_group_id) should still work normally."""
        setup_dead_page(mock_relay, mock_db)

        msg = self.make_forward_message(username="d_pages")
        object.__setattr__(msg, "media_group_id", None)

        await on_forward(msg)
        mock_relay.send_dead_page.assert_called_once_with(-100123, slot="repost")

    # ── Epic 52 (T-417): маппинг «репост → dead page бота» ──

    @pytest.mark.asyncio
    async def test_mapping_recorded_after_repost(self, mock_relay, mock_db):
        """T-417 (Section 61.6.2): send_dead_page вернул bot_msg_ids →
        записан маппинг {chat_id, repost_msg_id, bot_ids}."""
        setup_dead_page(mock_relay, mock_db)
        mock_relay.send_dead_page = AsyncMock(return_value=[100, 101])
        mock_db.record_dead_page_repost_map = AsyncMock()

        msg = self.make_forward_message(username="d_pages")

        await on_forward(msg)

        mock_db.record_dead_page_repost_map.assert_awaited_once_with(
            -100123, msg.message_id, [100, 101]
        )

    @pytest.mark.asyncio
    async def test_no_mapping_when_send_failed(self, mock_relay, mock_db):
        """T-417: send_dead_page вернул None → маппинг НЕ пишется."""
        setup_dead_page(mock_relay, mock_db)
        mock_relay.send_dead_page = AsyncMock(return_value=None)
        mock_db.record_dead_page_repost_map = AsyncMock()

        msg = self.make_forward_message(username="d_pages")

        await on_forward(msg)

        mock_db.record_dead_page_repost_map.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_db_error_on_record_graceful(self, mock_relay, mock_db):
        """T-417: ошибка записи маппинга → не падает."""
        setup_dead_page(mock_relay, mock_db)
        mock_relay.send_dead_page = AsyncMock(return_value=[100])
        mock_db.record_dead_page_repost_map = AsyncMock(
            side_effect=RuntimeError("db down")
        )

        msg = self.make_forward_message(username="d_pages")

        await on_forward(msg)  # не должно бросить исключение

    # ── M1 (review-fix): маппинг для ВСЕХ элементов альбома ──

    @pytest.mark.asyncio
    async def test_mapping_recorded_for_all_album_messages(self, mock_relay, mock_db):
        """M1: дедуп скипает повторную отправку, но маппинг пишется и для
        2-го элемента альбома (тем же набором bot_ids) — reply на удалённый
        2-й элемент найдёт маппинг."""
        setup_dead_page(mock_relay, mock_db)
        mock_relay.send_dead_page = AsyncMock(return_value=[100, 101])
        mock_db.record_dead_page_repost_map = AsyncMock()

        msg1 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg1, "media_group_id", "mg_map_001")
        object.__setattr__(msg1, "message_id", 1)

        msg2 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg2, "media_group_id", "mg_map_001")
        object.__setattr__(msg2, "message_id", 2)

        await on_forward(msg1)
        await on_forward(msg2)

        assert mock_relay.send_dead_page.call_count == 1       # дедуп жив
        mock_db.record_dead_page_repost_map.assert_any_await(-100123, 1, [100, 101])
        mock_db.record_dead_page_repost_map.assert_any_await(-100123, 2, [100, 101])

    @pytest.mark.asyncio
    async def test_dedup_no_mapping_when_send_failed(self, mock_relay, mock_db):
        """M1: send_dead_page вернул None для первого элемента → маппинга нет
        ни для первого, ни для дублей (нечего удалять)."""
        setup_dead_page(mock_relay, mock_db)
        mock_relay.send_dead_page = AsyncMock(return_value=None)
        mock_db.record_dead_page_repost_map = AsyncMock()

        msg1 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg1, "media_group_id", "mg_map_none")
        object.__setattr__(msg1, "message_id", 1)
        msg2 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg2, "media_group_id", "mg_map_none")
        object.__setattr__(msg2, "message_id", 2)

        await on_forward(msg1)
        await on_forward(msg2)

        mock_db.record_dead_page_repost_map.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mapping_recorded_for_all_album_messages_concurrent(self, mock_relay, mock_db):
        """B1 (review-fix): aiogram 3.29.1 с handle_as_tasks=True обрабатывает
        апдейты альбома конкурентно (asyncio.create_task на каждый апдейт) —
        второй элемент может попасть в dedup-ветку, пока первый ещё внутри
        send_dead_page (медленный сетевой вызов, смоделирован asyncio.sleep).
        Маппинг {репост → dead page бота} должен быть записан для ОБОИХ
        message_id — reply на удалённый 2-й элемент альбома найдёт маппинг."""
        import asyncio

        setup_dead_page(mock_relay, mock_db)

        async def slow_send_dead_page(chat_id, slot="repost"):
            await asyncio.sleep(0.1)
            return [100, 101]

        mock_relay.send_dead_page = AsyncMock(side_effect=slow_send_dead_page)
        mock_db.record_dead_page_repost_map = AsyncMock()

        msg1 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg1, "media_group_id", "mg_b1_concurrent")
        object.__setattr__(msg1, "message_id", 1)

        msg2 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg2, "media_group_id", "mg_b1_concurrent")
        object.__setattr__(msg2, "message_id", 2)

        await asyncio.gather(on_forward(msg1), on_forward(msg2))

        assert mock_relay.send_dead_page.call_count == 1   # дедуп жив
        mock_db.record_dead_page_repost_map.assert_any_await(-100123, 1, [100, 101])
        mock_db.record_dead_page_repost_map.assert_any_await(-100123, 2, [100, 101])
