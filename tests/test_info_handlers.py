"""Tests for handlers/info.py (T-339-A #1-14, Section 52.6).

100% покрытие /info и /edit_info: delete+пул нет прав (СТОП), кулдаун
per-chat (команда удаляется даже при троттлинге), HTML-отправка с
plain-фолбеком, админ-гейт, DM-превью (порядок preview→save), рендер-
валидация (файл/кэш нетронуты), OSError, пустой аргумент, init-гарды.
"""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from handlers import info as info_mod
from services.smartmodule_phrases import (
    INFO_BAD_MARKUP_PHRASES,
    INFO_EDIT_OK_PHRASES,
    INFO_NO_DELETE_RIGHTS_PHRASES,
    INFO_NOT_ADMIN_PHRASES,
    THROTTLE_PHRASES,
)
from services.smartmodule_throttling import format_remaining_time

CHAT_ID = -1001234567890
ADMIN_ID = 5885953495
HTML_TEXT = "<b>Я — админ-бот</b>"


@pytest.fixture
def fake_time(monkeypatch):
    state = {"now": 1000.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            return state["now"]

    monkeypatch.setattr("services.smartmodule_throttling.time", FakeTime)
    return state


@pytest.fixture
def info_cleanup():
    yield
    info_mod._service = None
    info_mod._cooldown._last.clear()


def _make_msg(text, user_id=1, chat_id=CHAT_ID, message_id=5):
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.delete = AsyncMock()
    return msg


def _service(get_text=HTML_TEXT):
    service = MagicMock()
    service.get_text = MagicMock(return_value=get_text)
    service.save_text = MagicMock()
    return service


def _no_rights_400():
    return TelegramBadRequest(
        method=None, message="Bad Request: not enough rights to delete messages"
    )


class TestCmdInfo:
    @pytest.mark.asyncio
    async def test_success_delete_then_html_send(self, info_cleanup):
        """#1: delete ДО отправки (порядок await-ов); send_chunked_reply
        (..., None, parse_mode="HTML"); текст == кэшу сервиса."""
        service = _service()
        info_mod.setup_info(service)
        parent = MagicMock()
        parent.delete = AsyncMock()
        parent.send_message = AsyncMock()
        msg = _make_msg("/info")
        msg.delete = parent.delete
        bot = AsyncMock()
        bot.send_message = parent.send_message
        await info_mod.cmd_info(msg, bot=bot)
        names = [c[0] for c in parent.mock_calls]
        assert names.index("delete") < names.index("send_message")
        assert parent.send_message.await_args.args == (CHAT_ID, HTML_TEXT)
        assert parent.send_message.await_args.kwargs["parse_mode"] == "HTML"
        assert "reply_to_message_id" not in parent.send_message.await_args.kwargs
        service.get_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_no_rights_pool_and_stop(self, info_cleanup):
        """#2: delete бросает TelegramBadRequest → INFO_NO_DELETE_RIGHTS_PHRASES
        реплаем; отправка справки НЕ происходит (СТОП)."""
        service = _service()
        info_mod.setup_info(service)
        msg = _make_msg("/info")
        msg.delete = AsyncMock(side_effect=_no_rights_400())
        bot = AsyncMock()
        await info_mod.cmd_info(msg, bot=bot)
        assert bot.send_message.await_count == 1
        assert bot.send_message.await_args.args[1] in INFO_NO_DELETE_RIGHTS_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 5

    @pytest.mark.asyncio
    async def test_delete_generic_exception_same_pool(self, info_cleanup):
        """#3: delete бросает прочий Exception → тот же пул."""
        service = _service()
        info_mod.setup_info(service)
        msg = _make_msg("/info")
        msg.delete = AsyncMock(side_effect=RuntimeError("сеть"))
        bot = AsyncMock()
        await info_mod.cmd_info(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in INFO_NO_DELETE_RIGHTS_PHRASES

    @pytest.mark.asyncio
    async def test_cooldown_throttles_but_still_deletes(self, info_cleanup, fake_time):
        """#4: 2-й /info в том же чате (другой user) → 5.1 с remaining;
        команда УДАЛЕНА (порядок delete→кулдаун); другой chat — не троттлится."""
        service = _service()
        info_mod.setup_info(service)
        bot = AsyncMock()
        first = _make_msg("/info", user_id=1)
        await info_mod.cmd_info(first, bot=bot)
        assert bot.send_message.await_count == 1

        fake_time["now"] += 100
        expected_remaining = info_mod._cooldown.remaining(CHAT_ID, 0)
        assert expected_remaining > 0
        second = _make_msg("/info", user_id=2, message_id=6)
        await info_mod.cmd_info(second, bot=bot)
        second.delete.assert_awaited_once()                  # команда удалена
        fmt = format_remaining_time(expected_remaining)
        candidates = [p.replace("{remaining_time}", fmt) for p in THROTTLE_PHRASES]
        assert bot.send_message.await_args.args[1] in candidates
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 6
        assert bot.send_message.await_count == 2              # справка не слалась

        other = _make_msg("/info", user_id=3, chat_id=-987654321, message_id=7)
        await info_mod.cmd_info(other, bot=bot)
        assert bot.send_message.await_count == 3              # другой чат — ок

    @pytest.mark.asyncio
    async def test_html_rejected_plain_fallback(self, info_cleanup, caplog):
        """#5: отправка бросает TelegramBadRequest (файл правлен мимо
        /edit_info) → повтор БЕЗ parse_mode; хендлер не падает."""
        service = _service(get_text="<b>битая разметка</b")
        info_mod.setup_info(service)
        msg = _make_msg("/info")
        bot = AsyncMock()
        bot.send_message = AsyncMock(
            side_effect=[
                TelegramBadRequest(method=None, message="Bad Request: can't parse entities"),
                None,
            ]
        )
        await info_mod.cmd_info(msg, bot=bot)
        calls = bot.send_message.await_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["parse_mode"] == "HTML"
        assert "parse_mode" not in calls[1].kwargs
        assert calls[1].args[1] == "<b>битая разметка</b"

    @pytest.mark.asyncio
    async def test_plain_fallback_failure_logged_not_raised(self, info_cleanup, caplog):
        """#6: вторичный сбой plain-фолбека → logger.exception, не падает."""
        service = _service(get_text="<b>битая разметка</b")
        info_mod.setup_info(service)
        msg = _make_msg("/info")
        bot = AsyncMock()
        bot.send_message = AsyncMock(
            side_effect=[
                TelegramBadRequest(method=None, message="Bad Request: can't parse entities"),
                Exception("сеть упала"),
            ]
        )
        with caplog.at_level(logging.ERROR):
            await info_mod.cmd_info(msg, bot=bot)
        assert any("plain fallback failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_send_generic_exception_logged_not_raised(self, info_cleanup, caplog):
        """Наружный except Exception (сеть/не-HTML сбой отправки) — покрытие 100%."""
        service = _service()
        info_mod.setup_info(service)
        msg = _make_msg("/info")
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=ConnectionError("сеть упала"))
        with caplog.at_level(logging.ERROR):
            await info_mod.cmd_info(msg, bot=bot)
        assert any("[/info] send failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_service_no_delete_no_crash(self, info_cleanup):
        """#7: _service is None → нет краша, нет delete."""
        info_mod._service = None
        msg = _make_msg("/info")
        bot = AsyncMock()
        await info_mod.cmd_info(msg, bot=bot)
        msg.delete.assert_not_called()
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_bot_no_delete_no_crash(self, info_cleanup):
        info_mod.setup_info(_service())
        msg = _make_msg("/info")
        await info_mod.cmd_info(msg, bot=None)
        msg.delete.assert_not_called()


class TestCmdEditInfo:
    @pytest.mark.asyncio
    async def test_non_admin_denied(self, info_cleanup):
        """#8: не-админ → INFO_NOT_ADMIN_PHRASES реплаем; preview/save НЕ вызваны."""
        service = _service()
        info_mod.setup_info(service)
        msg = _make_msg("/edit_info <b>новое</b>", user_id=ADMIN_ID + 1)
        bot = AsyncMock()
        await info_mod.cmd_edit_info(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in INFO_NOT_ADMIN_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 5
        service.save_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_valid_preview_then_save_then_ok(self, info_cleanup):
        """#9: bot.send_message(ADMIN_USER_ID, text, parse_mode="HTML") ДО
        save_text (порядок); save_text(new_text); INFO_EDIT_OK реплаем."""
        service = _service()
        info_mod.setup_info(service)
        events = []

        def on_save(text):
            events.append("save")

        service.save_text = MagicMock(side_effect=on_save)
        bot = AsyncMock()

        async def on_send(*args, **kwargs):
            events.append("send")
            return MagicMock()

        bot.send_message = AsyncMock(side_effect=on_send)
        msg = _make_msg("/edit_info <b>новая справка</b>", user_id=ADMIN_ID)
        await info_mod.cmd_edit_info(msg, bot=bot)
        assert events[:2] == ["send", "save"]              # превью ДО сохранения
        service.save_text.assert_called_once_with("<b>новая справка</b>")
        preview = bot.send_message.await_args_list[0]
        assert preview.args == (ADMIN_ID, "<b>новая справка</b>")
        assert preview.kwargs["parse_mode"] == "HTML"
        ok_call = bot.send_message.await_args_list[-1]
        assert ok_call.args[1] in INFO_EDIT_OK_PHRASES
        assert ok_call.kwargs["reply_to_message_id"] == 5

    @pytest.mark.asyncio
    async def test_preview_bad_markup_file_untouched(self, info_cleanup):
        """#10: превью бросает TelegramBadRequest → INFO_BAD_MARKUP_PHRASES;
        save_text НЕ вызван; кэш/файл нетронуты (D163)."""
        service = _service()
        info_mod.setup_info(service)
        msg = _make_msg("/edit_info <b>криво", user_id=ADMIN_ID)
        bot = AsyncMock()
        bot.send_message = AsyncMock(
            side_effect=TelegramBadRequest(
                method=None, message="Bad Request: can't parse entities"
            )
        )
        await info_mod.cmd_edit_info(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in INFO_BAD_MARKUP_PHRASES
        service.save_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_preview_forbidden_same_pool_no_save(self, info_cleanup):
        """#11: превью бросает Forbidden/сеть → тот же пул; save НЕ вызван."""
        service = _service()
        info_mod.setup_info(service)
        msg = _make_msg("/edit_info <b>новое</b>", user_id=ADMIN_ID)
        bot = AsyncMock()
        bot.send_message = AsyncMock(
            side_effect=TelegramForbiddenError(
                method=None, message="bot was blocked by the user"
            )
        )
        await info_mod.cmd_edit_info(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in INFO_BAD_MARKUP_PHRASES
        service.save_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_oserror_bad_markup_pool(self, info_cleanup):
        """#12: save_text бросает OSError → INFO_BAD_MARKUP_PHRASES; кэш старый."""
        service = _service()
        service.save_text = MagicMock(side_effect=OSError("нет прав на запись"))
        info_mod.setup_info(service)
        msg = _make_msg("/edit_info <b>новое</b>", user_id=ADMIN_ID)
        bot = AsyncMock()
        await info_mod.cmd_edit_info(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in INFO_BAD_MARKUP_PHRASES
        service.save_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_argument_shows_current_text(self, info_cleanup):
        """#13: пустой аргумент → реплай = текущий текст; preview/save НЕ вызваны."""
        service = _service(get_text="ТЕКУЩИЙ ТЕКСТ")
        info_mod.setup_info(service)
        msg = _make_msg("/edit_info", user_id=ADMIN_ID)
        bot = AsyncMock()
        await info_mod.cmd_edit_info(msg, bot=bot)
        assert bot.send_message.await_args.args[1] == "ТЕКУЩИЙ ТЕКСТ"
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 5
        service.save_text.assert_not_called()
        assert all("parse_mode" not in c.kwargs for c in bot.send_message.await_args_list)

    @pytest.mark.asyncio
    async def test_whitespace_argument_shows_current_text(self, info_cleanup):
        """#14: `/edit_info   ` (только пробелы) → как #13."""
        service = _service(get_text="ТЕКУЩИЙ ТЕКСТ")
        info_mod.setup_info(service)
        msg = _make_msg("/edit_info   ", user_id=ADMIN_ID)
        bot = AsyncMock()
        await info_mod.cmd_edit_info(msg, bot=bot)
        assert bot.send_message.await_args.args[1] == "ТЕКУЩИЙ ТЕКСТ"
        service.save_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_service_skips(self, info_cleanup):
        info_mod._service = None
        msg = _make_msg("/edit_info <b>новое</b>", user_id=ADMIN_ID)
        bot = AsyncMock()
        await info_mod.cmd_edit_info(msg, bot=bot)
        bot.send_message.assert_not_called()
