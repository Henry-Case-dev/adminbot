import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from handlers.slavik import kucha_handler, slavik_catchall_handler, setup_slavik


def _make_mock_settings(**kwargs):
    """Create a mock Settings object to bypass frozen dataclass."""
    s = MagicMock()
    s.SLAVIC_PHOTO_INTERVAL = kwargs.get("SLAVIC_PHOTO_INTERVAL", 10)
    s.SLAVIC_PHOTO_PATH = kwargs.get("SLAVIC_PHOTO_PATH", "media/slavic_na_litso.jpg")
    s.SLAVIK_USER_ID = 479167456
    s.SLAVIK_MIMIC_MIN_WORDS = kwargs.get("SLAVIK_MIMIC_MIN_WORDS", 5)
    s.SLAVIK_MIMIC_COOLDOWN_SECONDS = kwargs.get("SLAVIK_MIMIC_COOLDOWN_SECONDS", 60.0)
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
        """Photo should be sent with FSInputFile using the configured path."""
        import handlers.slavik as slavik_module
        mock_db = AsyncMock()
        mock_db.slavic_photo_count_tick = AsyncMock(return_value=True)
        original_db = slavik_module._db
        slavik_module._db = mock_db
        try:
            monkeypatch.setattr(slavik_module, "settings", _make_mock_settings())
            with patch("handlers.slavik.Path.exists", return_value=True):
                with patch("handlers.slavik.FSInputFile") as mock_fs:
                    msg = make_message(479167456, text="любое сообщение")
                    msg.answer_photo = AsyncMock()
                    await slavik_catchall_handler(msg)
            mock_fs.assert_called_once_with("media/slavic_na_litso.jpg")
        finally:
            slavik_module._db = original_db
