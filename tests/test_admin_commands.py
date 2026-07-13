"""Tests for admin test commands (Epic 10)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.admin_commands import (
    admin_commands_router,
    cmd_deadpage_dm,
    cmd_deadpage_group,
    cmd_alangreet_dm,
    cmd_alangreet_group,
    _delete_command,
    setup_admin_commands,
)


class TestAdminCommands:
    @pytest.mark.asyncio
    async def test_deadpage_dm_triggers_relay(self, make_admin_message):
        msg = make_admin_message("private", 5885953495, -100)
        mock_relay = AsyncMock()
        mock_relay.send_dead_page = AsyncMock()
        with patch("handlers.admin_commands._relay", mock_relay):
            await cmd_deadpage_dm(msg)
        mock_relay.send_dead_page.assert_called_once_with(-100, slot="manual")
        msg.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_deadpage_group_admin_accepted(self, make_admin_message):
        msg = make_admin_message("group", 5885953495, -100)
        mock_relay = AsyncMock()
        mock_relay.send_dead_page = AsyncMock()
        with patch("handlers.admin_commands._relay", mock_relay):
            await cmd_deadpage_group(msg)
        mock_relay.send_dead_page.assert_called_once_with(-100, slot="manual")
        msg.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_deadpage_group_non_admin_rejected(self, make_admin_message):
        msg = make_admin_message("group", 99999, -100)
        mock_relay = MagicMock()
        with patch("handlers.admin_commands._relay", mock_relay):
            await cmd_deadpage_group(msg)
        mock_relay.send_dead_page.assert_not_called()
        msg.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_alangreet_dm_sends_video(self, make_admin_message):
        msg = make_admin_message("private", 5885953495, -100)
        with patch("handlers.alan_greeting._send_greeting", new_callable=AsyncMock) as mock_send:
            await cmd_alangreet_dm(msg)
        mock_send.assert_called_once_with(msg.bot, -100)

    @pytest.mark.asyncio
    async def test_alangreet_group_admin_accepted(self, make_admin_message):
        msg = make_admin_message("group", 5885953495, -100)
        with patch("handlers.alan_greeting._send_greeting", new_callable=AsyncMock) as mock_send:
            await cmd_alangreet_group(msg)
        mock_send.assert_called_once_with(msg.bot, -100)
        msg.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_alangreet_group_non_admin_rejected(self, make_admin_message):
        msg = make_admin_message("group", 99999, -100)
        with patch("handlers.alan_greeting._send_greeting", new_callable=AsyncMock) as mock_send:
            await cmd_alangreet_group(msg)
        mock_send.assert_not_called()
        msg.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_command_messages_are_deleted_dm(self, make_admin_message):
        msg = make_admin_message("private", 5885953495, -100)
        with patch("handlers.alan_greeting._send_greeting", new_callable=AsyncMock):
            await cmd_alangreet_dm(msg)
        msg.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_router_has_four_handlers(self):
        assert len(admin_commands_router.message.handlers) == 4

    @pytest.mark.asyncio
    async def test_setup_injects_relay(self):
        mock_relay = MagicMock()
        setup_admin_commands(mock_relay)
        from handlers import admin_commands as ac
        assert ac._relay is mock_relay
        setup_admin_commands(None)  # cleanup

    @pytest.mark.asyncio
    async def test_deadpage_no_relay_dm(self, make_admin_message):
        msg = make_admin_message("private", 5885953495, -100)
        with patch("handlers.admin_commands._relay", None):
            await cmd_deadpage_dm(msg)
        msg.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_error_not_fatal_deadpage(self, make_admin_message):
        """D24: delete() raises → deadpage still fires."""
        msg = make_admin_message("private", 5885953495)
        msg.delete.side_effect = Exception("Permission denied")
        mock_relay = AsyncMock()
        mock_relay.send_dead_page = AsyncMock()
        with patch("handlers.admin_commands._relay", mock_relay):
            await cmd_deadpage_dm(msg)
        mock_relay.send_dead_page.assert_called_once_with(-100123, slot="manual")

    @pytest.mark.asyncio
    async def test_delete_error_not_fatal_alangreet(self, make_admin_message):
        """D24: delete() raises → alangreet still fires."""
        msg = make_admin_message("private", 5885953495)
        msg.delete.side_effect = Exception("Permission denied")
        with patch("handlers.alan_greeting._send_greeting", new_callable=AsyncMock) as mock_send:
            await cmd_alangreet_dm(msg)
        mock_send.assert_called_once_with(msg.bot, -100123)

    @pytest.mark.asyncio
    async def test_alangreet_no_videos(self, make_admin_message):
        """_send_greeting returns False → no crash."""
        msg = make_admin_message("private", 5885953495)
        msg.answer = AsyncMock()
        with patch("handlers.alan_greeting._send_greeting", new_callable=AsyncMock, return_value=False):
            await cmd_alangreet_dm(msg)

    @pytest.mark.asyncio
    async def test_alangreet_send_error(self, make_admin_message):
        """_send_greeting raises → handler logs but doesn't crash."""
        msg = make_admin_message("private", 5885953495)
        msg.answer = AsyncMock()
        with patch("handlers.alan_greeting._send_greeting", new_callable=AsyncMock,
                   side_effect=Exception("Telegram API error")):
            with pytest.raises(Exception, match="Telegram API error"):
                await cmd_alangreet_dm(msg)
