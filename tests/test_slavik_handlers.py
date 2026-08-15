import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from aiogram.dispatcher.event.bases import UNHANDLED

from handlers.slavik import kucha_handler, slavik_catchall_handler, setup_slavik


def _make_mock_settings(**kwargs):
    """Create a mock Settings object to bypass frozen dataclass."""
    s = MagicMock()
    s.SLAVIC_PHOTO_INTERVAL = kwargs.get("SLAVIC_PHOTO_INTERVAL", 10)
    s.SLAVIC_PHOTO_PATH = kwargs.get("SLAVIC_PHOTO_PATH", "media/slavic_na_litso.jpg")
    s.SLAVIK_USER_ID = 479167456
    s.SLAVIK_MIMIC_MIN_WORDS = kwargs.get("SLAVIK_MIMIC_MIN_WORDS", 5)
    s.SLAVIK_MIMIC_COOLDOWN = kwargs.get("SLAVIK_MIMIC_COOLDOWN", 60.0)
    s.MIMIC_FORWARDS_ENABLED = kwargs.get("MIMIC_FORWARDS_ENABLED", False)
    s.DEAD_PAGE_SOURCE_CHANNEL_USERNAME = kwargs.get(
        "DEAD_PAGE_SOURCE_CHANNEL_USERNAME", "d_pages"
    )
    s.DEAD_PAGE_SOURCE_CHANNEL_ID = kwargs.get("DEAD_PAGE_SOURCE_CHANNEL_ID", 0)
    return s


class TestKuchaHandler:
    @pytest.mark.asyncio
    async def test_replies_dalbaeb(self, make_message):
        msg = make_message(479167456, text="КУЧА денег")
        await kucha_handler(msg)
        msg.reply.assert_called_once_with("ДАЛБАЕБ")


class TestSlavikCatchall:
    @pytest.mark.asyncio
    async def test_replies_poshel_nahui(self, make_message):
        msg = make_message(479167456, text="любое сообщение")
        await slavik_catchall_handler(msg)
        msg.reply.assert_called_once_with("пошёл нахуй")


# ── F6: Slavic Photo (Epic 12) ──

class TestSlavicPhotoHandler:
    """Tests for slavic_na_litso.jpg photo feature."""

    @pytest.mark.asyncio
    async def test_sends_text_when_db_not_setup(self, make_message):
        """When _db is None (not injected), fall back to text reply."""
        import handlers.slavik as slavik_module
        original_db = slavik_module._db
        slavik_module._db = None
        try:
            msg = make_message(479167456, text="любое сообщение")
            msg.answer_photo = AsyncMock()
            await slavik_catchall_handler(msg)
            msg.reply.assert_called_once_with("пошёл нахуй")
            msg.answer_photo.assert_not_called()
        finally:
            slavik_module._db = original_db

    @pytest.mark.asyncio
    async def test_sends_photo_when_interval_reached(self, make_message, monkeypatch):
        """When DB returns True, photo should be sent instead of text."""
        import handlers.slavik as slavik_module
        mock_db = AsyncMock()
        mock_db.slavic_photo_count_tick = AsyncMock(return_value=True)
        original_db = slavik_module._db
        slavik_module._db = mock_db
        try:
            monkeypatch.setattr(slavik_module, "settings", _make_mock_settings())
            with patch("handlers.slavik.Path.exists", return_value=True):
                with patch("handlers.slavik.FSInputFile") as mock_fs:
                    with patch("handlers.slavik._pick_random_slavik_media", return_value=None):
                        msg = make_message(479167456, text="любое сообщение")
                        msg.answer_photo = AsyncMock()
                        await slavik_catchall_handler(msg)
            msg.answer_photo.assert_called_once()
            msg.reply.assert_not_called()
        finally:
            slavik_module._db = original_db

    @pytest.mark.asyncio
    async def test_sends_text_when_interval_not_reached(self, make_message, monkeypatch):
        """When DB returns False, send text reply."""
        import handlers.slavik as slavik_module
        mock_db = AsyncMock()
        mock_db.slavic_photo_count_tick = AsyncMock(return_value=False)
        original_db = slavik_module._db
        slavik_module._db = mock_db
        try:
            monkeypatch.setattr(slavik_module, "settings", _make_mock_settings())
            msg = make_message(479167456, text="любое сообщение")
            msg.answer_photo = AsyncMock()
            await slavik_catchall_handler(msg)
            msg.reply.assert_called_once_with("пошёл нахуй")
            msg.answer_photo.assert_not_called()
        finally:
            slavik_module._db = original_db

    @pytest.mark.asyncio
    async def test_photo_not_sent_when_interval_zero(self, make_message, monkeypatch):
        """When SLAVIC_PHOTO_INTERVAL=0, feature is disabled."""
        import handlers.slavik as slavik_module
        mock_db = AsyncMock()
        mock_db.slavic_photo_count_tick = AsyncMock()
        original_db = slavik_module._db
        slavik_module._db = mock_db
        try:
            monkeypatch.setattr(slavik_module, "settings", _make_mock_settings(SLAVIC_PHOTO_INTERVAL=0))
            msg = make_message(479167456, text="любое сообщение")
            msg.answer_photo = AsyncMock()
            await slavik_catchall_handler(msg)
            msg.reply.assert_called_once_with("пошёл нахуй")
            msg.answer_photo.assert_not_called()
            mock_db.slavic_photo_count_tick.assert_not_called()
        finally:
            slavik_module._db = original_db

    @pytest.mark.asyncio
    async def test_fallback_to_text_on_db_error(self, make_message, monkeypatch):
        """When DB throws, fall back to text reply."""
        import handlers.slavik as slavik_module
        mock_db = AsyncMock()
        mock_db.slavic_photo_count_tick = AsyncMock(side_effect=Exception("DB error"))
        original_db = slavik_module._db
        slavik_module._db = mock_db
        try:
            monkeypatch.setattr(slavik_module, "settings", _make_mock_settings())
            msg = make_message(479167456, text="любое сообщение")
            msg.answer_photo = AsyncMock()
            await slavik_catchall_handler(msg)
            msg.reply.assert_called_once_with("пошёл нахуй")
            msg.answer_photo.assert_not_called()
        finally:
            slavik_module._db = original_db

    @pytest.mark.asyncio
    async def test_photo_file_not_found_fallback(self, make_message, monkeypatch):
        """When photo file doesn't exist, fall back to text reply."""
        import handlers.slavik as slavik_module
        mock_db = AsyncMock()
        mock_db.slavic_photo_count_tick = AsyncMock(return_value=True)
        original_db = slavik_module._db
        slavik_module._db = mock_db
        try:
            monkeypatch.setattr(slavik_module, "settings", _make_mock_settings())
            with patch("handlers.slavik.Path.exists", return_value=False):
                msg = make_message(479167456, text="любое сообщение")
                msg.answer_photo = AsyncMock()
                await slavik_catchall_handler(msg)
            msg.reply.assert_called_once_with("пошёл нахуй")
            msg.answer_photo.assert_not_called()
        finally:
            slavik_module._db = original_db

    @pytest.mark.asyncio
    async def test_kucha_handler_unaffected(self, make_message):
        """KUCHA handler should not depend on _db."""
        import handlers.slavik as slavik_module
        original_db = slavik_module._db
        slavik_module._db = None
        try:
            msg = make_message(479167456, text="КУЧА денег")
            await kucha_handler(msg)
            msg.reply.assert_called_once_with("ДАЛБАЕБ")
        finally:
            slavik_module._db = original_db

    @pytest.mark.asyncio
    async def test_photo_uses_correct_path(self, make_message, monkeypatch):
        """Photo should be sent with FSInputFile using the configured fallback path."""
        import handlers.slavik as slavik_module
        mock_db = AsyncMock()
        mock_db.slavic_photo_count_tick = AsyncMock(return_value=True)
        original_db = slavik_module._db
        slavik_module._db = mock_db
        try:
            monkeypatch.setattr(slavik_module, "settings", _make_mock_settings())
            with patch("handlers.slavik.Path.exists", return_value=True):
                with patch("handlers.slavik.FSInputFile") as mock_fs:
                    with patch("handlers.slavik._pick_random_slavik_media", return_value=None):
                        msg = make_message(479167456, text="любое сообщение")
                        msg.answer_photo = AsyncMock()
                        await slavik_catchall_handler(msg)
            mock_fs.assert_called_once_with("media/slavic_na_litso.jpg")
        finally:
            slavik_module._db = original_db


# ── Epic 22 (D52): Slavik mimic — forwards gate ──


class TestSlavikMimicForwardsGate:
    """D52: _slavik_mimic_should_trigger respects is_forwarded + MIMIC_FORWARDS_ENABLED."""

    @pytest.fixture(autouse=True)
    def _reset_cooldown(self):
        import handlers.slavik as slavik_module
        original = slavik_module._slavik_mimic_last_sent.copy()
        slavik_module._slavik_mimic_last_sent.clear()
        yield
        slavik_module._slavik_mimic_last_sent.clear()
        slavik_module._slavik_mimic_last_sent.update(original)

    @pytest.mark.asyncio
    async def test_ordinary_message_off_triggers(self, monkeypatch, _reset_cooldown):
        import handlers.slavik as slavik_module
        monkeypatch.setattr(
            slavik_module, "settings",
            _make_mock_settings(SLAVIK_MIMIC_COOLDOWN=0.0, MIMIC_FORWARDS_ENABLED=False),
        )
        result = slavik_module._slavik_mimic_should_trigger(
            -100123, "один два три четыре пять шесть", is_forwarded=False
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_forwarded_off_does_not_trigger(self, monkeypatch, _reset_cooldown):
        import handlers.slavik as slavik_module
        monkeypatch.setattr(
            slavik_module, "settings",
            _make_mock_settings(SLAVIK_MIMIC_COOLDOWN=0.0, MIMIC_FORWARDS_ENABLED=False),
        )
        result = slavik_module._slavik_mimic_should_trigger(
            -100123, "один два три четыре пять шесть", is_forwarded=True
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_forwarded_on_triggers(self, monkeypatch, _reset_cooldown):
        import handlers.slavik as slavik_module
        monkeypatch.setattr(
            slavik_module, "settings",
            _make_mock_settings(SLAVIK_MIMIC_COOLDOWN=0.0, MIMIC_FORWARDS_ENABLED=True),
        )
        result = slavik_module._slavik_mimic_should_trigger(
            -100123, "один два три четыре пять шесть", is_forwarded=True
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_ordinary_message_on_triggers(self, monkeypatch, _reset_cooldown):
        import handlers.slavik as slavik_module
        monkeypatch.setattr(
            slavik_module, "settings",
            _make_mock_settings(SLAVIK_MIMIC_COOLDOWN=0.0, MIMIC_FORWARDS_ENABLED=True),
        )
        result = slavik_module._slavik_mimic_should_trigger(
            -100123, "один два три четыре пять шесть", is_forwarded=False
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_ordinary_long_message_mimics_in_catchall(self, make_message, monkeypatch, _reset_cooldown):
        """No regression: ordinary message with forward_origin=None still mimics."""
        import handlers.slavik as slavik_module
        original_db = slavik_module._db
        slavik_module._db = None
        try:
            monkeypatch.setattr(
                slavik_module, "settings",
                _make_mock_settings(SLAVIK_MIMIC_COOLDOWN=0.0, MIMIC_FORWARDS_ENABLED=False),
            )
            msg = make_message(479167456, text="один два три четыре пять шесть")
            msg.forward_origin = None
            await slavik_catchall_handler(msg)
            msg.reply.assert_called_once()
            assert msg.reply.call_args[0][0] != "пошёл нахуй"
        finally:
            slavik_module._db = original_db


# ── Epic 22 (D53): catch-all — d_pages gate ──


class TestSlavikCatchallDeadPageGate:
    """D53: d_pages repost by Slava → UNHANDLED, dead page stays the only answer."""

    @pytest.fixture(autouse=True)
    def _reset_db(self):
        import handlers.slavik as slavik_module
        original_db = slavik_module._db
        slavik_module._db = None
        yield
        slavik_module._db = original_db

    @staticmethod
    def _make_channel_origin(chat_id: int, username: str):
        from aiogram.types import Chat, MessageOriginChannel
        return MessageOriginChannel(
            type="channel",
            date=1234567890,
            chat=Chat(id=chat_id, type="channel", username=username),
            message_id=42,
        )

    @pytest.mark.asyncio
    async def test_d_pages_repost_returns_unhandled(self, make_message, _reset_db):
        msg = make_message(479167456, text="репост из d_pages")
        msg.forward_origin = self._make_channel_origin(-100999, "d_pages")

        result = await slavik_catchall_handler(msg)

        assert result is UNHANDLED
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_d_pages_repost_by_id_returns_unhandled(self, make_message, monkeypatch, _reset_db):
        import handlers.slavik as slavik_module
        monkeypatch.setattr(
            slavik_module, "settings",
            _make_mock_settings(DEAD_PAGE_SOURCE_CHANNEL_USERNAME="", DEAD_PAGE_SOURCE_CHANNEL_ID=-100777),
        )
        msg = make_message(479167456, text="репост из d_pages")
        msg.forward_origin = self._make_channel_origin(-100777, None)

        result = await slavik_catchall_handler(msg)

        assert result is UNHANDLED
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_channel_repost_replies_nahui(self, make_message, monkeypatch, _reset_db):
        import handlers.slavik as slavik_module
        monkeypatch.setattr(
            slavik_module, "settings",
            _make_mock_settings(MIMIC_FORWARDS_ENABLED=False),
        )
        msg = make_message(479167456, text="репост из другого канала")
        msg.forward_origin = self._make_channel_origin(-100888, "other_channel")

        result = await slavik_catchall_handler(msg)

        assert result is None
        msg.reply.assert_called_once_with("пошёл нахуй")

    @pytest.mark.asyncio
    async def test_user_forward_origin_not_blocked(self, make_message, monkeypatch, _reset_db):
        """MessageOriginUser (not channel) → no dead-page yield, normal fallback."""
        import handlers.slavik as slavik_module
        from aiogram.types import MessageOriginUser, User
        monkeypatch.setattr(
            slavik_module, "settings",
            _make_mock_settings(MIMIC_FORWARDS_ENABLED=False),
        )
        msg = make_message(479167456, text="репост от пользователя")
        msg.forward_origin = MessageOriginUser(
            type="user",
            date=1234567890,
            sender_user=User(id=111, is_bot=False, first_name="Test"),
        )

        result = await slavik_catchall_handler(msg)

        assert result is None
        msg.reply.assert_called_once_with("пошёл нахуй")
