import logging
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import settings
from services.message_counter import MessageCounterMiddleware
from services.database import DatabaseService


def _patched_settings(**overrides):
    return replace(settings, **overrides)


def _make_event():
    event = MagicMock()
    event.from_user.id = 479167456
    event.chat.id = -100123
    event.answer_animation = AsyncMock()
    event.new_chat_members = None   # T-410: not a service message by default (MagicMock-safe)
    event.left_chat_member = None   # T-410: not a service message by default (MagicMock-safe)
    return event


class TestMessageCounterMiddleware:
    def test_real_gif_path_exists_in_repo(self):
        """Sanity: the default GIF_PATH file (media/slavik/slavic_chlen.mp4) is on place in the repo."""
        assert Path("media/slavik/slavic_chlen.mp4").is_file(), "Missing media file: media/slavik/slavic_chlen.mp4"

    @pytest.mark.asyncio
    async def test_increments_counter(self):
        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=1)

        middleware = MessageCounterMiddleware(mock_db)

        event = _make_event()
        handler = AsyncMock(return_value="done")

        result = await middleware(handler, event, {})

        mock_db.increment_and_get_count.assert_called_once_with(-100123, 479167456)
        handler.assert_called_once_with(event, {})
        assert result == "done"

    @pytest.mark.asyncio
    async def test_sends_gif_on_5th_message(self, tmp_path):
        gif_file = tmp_path / "slavic_chlen.mp4"
        gif_file.write_bytes(b"fake")
        mod = _patched_settings(GIF_PATH=str(gif_file), GIF_INTERVAL=5)

        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)

        with patch("services.message_counter.settings", mod):
            middleware = MessageCounterMiddleware(mock_db)

        event = _make_event()
        handler = AsyncMock(return_value="done")

        await middleware(handler, event, {})

        event.answer_animation.assert_called_once()
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_gif_on_3rd_message(self):
        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=3)

        middleware = MessageCounterMiddleware(mock_db)

        event = _make_event()
        handler = AsyncMock(return_value="done")

        await middleware(handler, event, {})

        event.answer_animation.assert_not_called()
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_gif_on_10th_message(self, tmp_path):
        gif_file = tmp_path / "slavic_chlen.mp4"
        gif_file.write_bytes(b"fake")
        mod = _patched_settings(GIF_PATH=str(gif_file), GIF_INTERVAL=5)

        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=10)

        with patch("services.message_counter.settings", mod):
            middleware = MessageCounterMiddleware(mock_db)

        event = _make_event()
        handler = AsyncMock(return_value="done")

        await middleware(handler, event, {})

        event.answer_animation.assert_called_once()

    @pytest.mark.asyncio
    async def test_fs_input_file_uses_settings_gif_path(self, tmp_path):
        gif_file = tmp_path / "slavic_chlen.mp4"
        gif_file.write_bytes(b"fake")
        mod = _patched_settings(GIF_PATH=str(gif_file), GIF_INTERVAL=5)

        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)

        with patch("services.message_counter.settings", mod), \
                patch("services.message_counter.FSInputFile") as mock_fs:
            middleware = MessageCounterMiddleware(mock_db)
            event = _make_event()
            await middleware(AsyncMock(), event, {})

        mock_fs.assert_called_once_with(str(gif_file))

    @pytest.mark.asyncio
    async def test_custom_gif_interval_from_settings(self, tmp_path):
        gif_file = tmp_path / "slavic_chlen.mp4"
        gif_file.write_bytes(b"fake")
        mod = _patched_settings(GIF_PATH=str(gif_file), GIF_INTERVAL=2)

        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(side_effect=[1, 2])

        with patch("services.message_counter.settings", mod):
            middleware = MessageCounterMiddleware(mock_db)

        handler = AsyncMock(return_value="done")

        event1 = _make_event()
        await middleware(handler, event1, {})
        event1.answer_animation.assert_not_called()

        event2 = _make_event()
        await middleware(handler, event2, {})
        event2.answer_animation.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_gif_file_skips_with_warning(self, tmp_path, caplog):
        missing = tmp_path / "nope" / "slavic_chlen.mp4"
        mod = _patched_settings(GIF_PATH=str(missing), GIF_INTERVAL=5)

        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)

        with patch("services.message_counter.settings", mod), \
                caplog.at_level(logging.WARNING, logger="services.message_counter"):
            middleware = MessageCounterMiddleware(mock_db)
            event = _make_event()
            handler = AsyncMock(return_value="done")
            result = await middleware(handler, event, {})

        event.answer_animation.assert_not_called()
        handler.assert_called_once_with(event, {})
        assert result == "done"
        assert "GIF file not found: %s, skipping" % str(missing) in caplog.text

    @pytest.mark.asyncio
    async def test_gif_send_error_logged_with_path(self, tmp_path, caplog):
        gif_file = tmp_path / "slavic_chlen.mp4"
        gif_file.write_bytes(b"fake")
        mod = _patched_settings(GIF_PATH=str(gif_file), GIF_INTERVAL=5)

        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)

        event = _make_event()
        event.answer_animation = AsyncMock(side_effect=Exception("Network error"))

        with patch("services.message_counter.settings", mod), \
                caplog.at_level(logging.ERROR, logger="services.message_counter"):
            middleware = MessageCounterMiddleware(mock_db)
            handler = AsyncMock(return_value="done")
            result = await middleware(handler, event, {})

        handler.assert_called_once()
        assert result == "done"
        assert "GIF send failed" in caplog.text
        assert str(gif_file) in caplog.text

    @pytest.mark.asyncio
    async def test_gif_send_file_not_found_error_logged(self, tmp_path, caplog):
        gif_file = tmp_path / "slavic_chlen.mp4"
        gif_file.write_bytes(b"fake")
        mod = _patched_settings(GIF_PATH=str(gif_file), GIF_INTERVAL=5)

        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)

        event = _make_event()
        event.answer_animation = AsyncMock(side_effect=FileNotFoundError("gone"))

        with patch("services.message_counter.settings", mod), \
                caplog.at_level(logging.ERROR, logger="services.message_counter"):
            middleware = MessageCounterMiddleware(mock_db)
            handler = AsyncMock(return_value="done")
            result = await middleware(handler, event, {})

        handler.assert_called_once()
        assert result == "done"
        assert "GIF file missing at send time" in caplog.text
        assert str(gif_file) in caplog.text

    @pytest.mark.asyncio
    async def test_gif_success_logs_info(self, tmp_path, caplog):
        gif_file = tmp_path / "slavic_chlen.mp4"
        gif_file.write_bytes(b"fake")
        mod = _patched_settings(GIF_PATH=str(gif_file), GIF_INTERVAL=5)

        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)

        with patch("services.message_counter.settings", mod), \
                caplog.at_level(logging.INFO, logger="services.message_counter"):
            middleware = MessageCounterMiddleware(mock_db)
            event = _make_event()
            await middleware(AsyncMock(), event, {})

        assert "GIF sent" in caplog.text

    @pytest.mark.asyncio
    async def test_zero_interval_no_crash(self, caplog):
        mod = _patched_settings(GIF_INTERVAL=0)

        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)

        with patch("services.message_counter.settings", mod), \
                caplog.at_level(logging.WARNING, logger="services.message_counter"):
            middleware = MessageCounterMiddleware(mock_db)
            event = _make_event()
            handler = AsyncMock(return_value="done")
            result = await middleware(handler, event, {})

        event.answer_animation.assert_not_called()
        handler.assert_called_once()
        assert result == "done"
        assert "GIF interval is 0" in caplog.text

    # ── T-410 (Epic 52, Section 61.4.2): service-сообщения + data-флаг ──

    @pytest.mark.asyncio
    async def test_service_message_new_chat_members_skipped(self):
        """T-410: new_chat_members → БЕЗ инкремента и БЕЗ гифки (чинит «гифка на вход»)."""
        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)

        middleware = MessageCounterMiddleware(mock_db)
        event = _make_event()
        event.new_chat_members = [MagicMock()]
        handler = AsyncMock(return_value="done")

        data = {}
        result = await middleware(handler, event, data)

        mock_db.increment_and_get_count.assert_not_called()
        event.answer_animation.assert_not_called()
        handler.assert_called_once_with(event, data)
        assert result == "done"
        assert "slavik_gif_sent" not in data

    @pytest.mark.asyncio
    async def test_service_message_left_chat_member_skipped(self):
        """T-410: left_chat_member → БЕЗ инкремента и БЕЗ гифки."""
        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)

        middleware = MessageCounterMiddleware(mock_db)
        event = _make_event()
        event.left_chat_member = MagicMock()
        handler = AsyncMock(return_value="done")

        await middleware(handler, event, {})

        mock_db.increment_and_get_count.assert_not_called()
        event.answer_animation.assert_not_called()

    @pytest.mark.asyncio
    async def test_gif_sent_sets_data_flag(self, tmp_path):
        """T-410: гифка реально отправлена → data['slavik_gif_sent'] is True."""
        gif_file = tmp_path / "slavic_chlen.mp4"
        gif_file.write_bytes(b"fake")
        mod = _patched_settings(GIF_PATH=str(gif_file), GIF_INTERVAL=5)

        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)

        with patch("services.message_counter.settings", mod):
            middleware = MessageCounterMiddleware(mock_db)

        event = _make_event()
        data = {}
        await middleware(AsyncMock(return_value="done"), event, data)

        event.answer_animation.assert_called_once()
        assert data.get("slavik_gif_sent") is True

    @pytest.mark.asyncio
    async def test_gif_missing_file_no_data_flag(self, tmp_path):
        """T-410: файл отсутствует → гифка НЕ отправлена, флага НЕТ (иначе
        сообщение осталось бы без реакции — Section 61.4.1)."""
        missing = tmp_path / "nope" / "slavic_chlen.mp4"
        mod = _patched_settings(GIF_PATH=str(missing), GIF_INTERVAL=5)

        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)

        with patch("services.message_counter.settings", mod):
            middleware = MessageCounterMiddleware(mock_db)

        event = _make_event()
        data = {}
        await middleware(AsyncMock(return_value="done"), event, data)

        event.answer_animation.assert_not_called()
        assert "slavik_gif_sent" not in data

    @pytest.mark.asyncio
    async def test_gif_send_error_no_data_flag(self, tmp_path):
        """T-410: ошибка отправки гифки → флага НЕТ."""
        gif_file = tmp_path / "slavic_chlen.mp4"
        gif_file.write_bytes(b"fake")
        mod = _patched_settings(GIF_PATH=str(gif_file), GIF_INTERVAL=5)

        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)

        event = _make_event()
        event.answer_animation = AsyncMock(side_effect=Exception("Network error"))

        with patch("services.message_counter.settings", mod):
            middleware = MessageCounterMiddleware(mock_db)

        data = {}
        await middleware(AsyncMock(return_value="done"), event, data)

        assert "slavik_gif_sent" not in data

    @pytest.mark.asyncio
    async def test_gif_interval_not_reached_no_flag(self):
        """T-410: интервал не достигнут → гифки нет, флага нет."""
        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=3)

        middleware = MessageCounterMiddleware(mock_db)
        event = _make_event()
        data = {}
        await middleware(AsyncMock(return_value="done"), event, data)

        event.answer_animation.assert_not_called()
        assert "slavik_gif_sent" not in data
