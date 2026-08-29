"""Tests for handlers/info.py (T-339-A #1-16, Sections 52.6/53.4; Epic 58, T-448-D).

100% покрытие /info и /edit_info: delete+пул нет прав (ПРОДОЛЖЕНИЕ — справка
реплаем на висящую команду), кулдаун per-chat (команда удаляется даже при
троттлинге), rich-отправка sendRichMessage с reply_parameters, фолбек D231
(rich 400 → legacy-HTML-эмуляция Epic 57 → plain), админ-гейт, rich-DM-превью
(порядок preview→save), рендер-валидация (файл/кэш нетронуты), лимит 32768,
OSError, пустой аргумент, init-гарды, _rich_to_legacy_html (счётчики эмуляции
Epic 71: 0 h1/h2, 39 b, 31 u).
"""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InputRichMessage, ReplyParameters

from handlers import info as info_mod
from services.info_service import DEFAULT_INFO_TEXT
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


def _rich_400():
    return TelegramBadRequest(method=None, message="Bad Request: RICH_MESSAGE_INVALID")


class TestRichToLegacyHtml:
    """D231: детерминированная трансформация rich→legacy (эмуляция Epic 57)."""

    def test_no_rich_tags_and_epic57_counters(self):
        result = info_mod._rich_to_legacy_html(DEFAULT_INFO_TEXT)
        assert "<h1>" not in result and "</h1>" not in result
        assert "<h2>" not in result and "</h2>" not in result
        # Epic 83 (D306): rich-канон обновлён — b=42, b+i+u=32, u=33, i=32
        assert result.count("<b>") == 42
        assert result.count("</b>") == 42
        assert result.count("<b><i><u>") == 32
        assert result.count("<u>") == 33
        assert result.count("</u>") == 33
        assert result.count("<i>") == 32
        assert result.count("</i>") == 32

    def test_intro_h1_emulation_and_links_kept(self):
        result = info_mod._rich_to_legacy_html(DEFAULT_INFO_TEXT)
        assert "<b><u>Гайд по фичам" in result
        assert "прямо в диалоге.</u></b>" in result
        assert '<a href="https://youtu.be/">' in result
        assert result.count("<a ") == 2
        assert result.count("</a>") == 2

    def test_legacy_epic57_input_idempotent_no_double_u(self):
        """M1: legacy-вход Epic 57 (<b><i><u> уже обёрнут) → результат равен
        входу, дублей <u><u>/</u></u> нет (sentinel-guard)."""
        legacy = (
            "<b><u>Гайд по фичам бота.</u></b>\n\n"
            "<b>1. Фактчек</b>\n"
            "- слово <b><i><u>фактчек</u></i></b>.\n"
            "Например: <b><i><u>фактчек правда ли склад сгорел?</u></i></b> или "
            "<b><i><u>фактчек поясни за цифры</u></i></b>.\n"
        )
        result = info_mod._rich_to_legacy_html(legacy)
        assert result == legacy
        assert "<u><u>" not in result
        assert "</u></u>" not in result

    def test_legacy_epic57_mixed_with_unwrapped_quotes(self):
        """M1: legacy-цитаты не дублируются, незавёрнутые <b><i> — оборачиваются
        (смешанный вход)."""
        text = "<b><i><u>старое</u></i></b> и <b><i>новое</i></b>"
        result = info_mod._rich_to_legacy_html(text)
        assert result == "<b><i><u>старое</u></i></b> и <b><i><u>новое</u></i></b>"
        assert "<u><u>" not in result
        assert "</u></u>" not in result


class TestCmdInfo:
    @pytest.mark.asyncio
    async def test_rich_success_sent_via_send_rich_message(self, info_cleanup):
        """Epic 58: delete ДО отправки (порядок await-ов); send_rich_message
        (CHAT_ID, InputRichMessage(html=text)); reply_parameters НЕ задан
        (команда удалена); текст == кэшу сервиса."""
        service = _service()
        info_mod.setup_info(service)
        parent = MagicMock()
        parent.delete = AsyncMock()
        parent.send_rich_message = AsyncMock()
        msg = _make_msg("/info")
        msg.delete = parent.delete
        bot = AsyncMock()
        bot.send_rich_message = parent.send_rich_message
        await info_mod.cmd_info(msg, bot=bot)
        names = [c[0] for c in parent.mock_calls]
        assert names.index("delete") < names.index("send_rich_message")
        assert parent.send_rich_message.await_args.args == (
            CHAT_ID, InputRichMessage(html=HTML_TEXT))
        assert parent.send_rich_message.await_args.kwargs.get("reply_parameters") is None
        service.get_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_no_rights_pool_then_continue(self, info_cleanup):
        """#2': delete бросает TelegramBadRequest → пул реплаем на message_id;
        справка — send_rich_message с reply_parameters=ReplyParameters(message_id=5);
        порядок: пул ДО справки; service.get_text вызван (R44-2, 53.4)."""
        service = _service()
        info_mod.setup_info(service)
        parent = MagicMock()
        parent.send_message = AsyncMock()
        parent.send_rich_message = AsyncMock()
        msg = _make_msg("/info")
        msg.delete = AsyncMock(side_effect=_no_rights_400())
        bot = AsyncMock()
        bot.send_message = parent.send_message
        bot.send_rich_message = parent.send_rich_message
        await info_mod.cmd_info(msg, bot=bot)
        names = [c[0] for c in parent.mock_calls]
        assert names.index("send_message") < names.index("send_rich_message")
        assert parent.send_message.await_args.args[1] in INFO_NO_DELETE_RIGHTS_PHRASES
        assert parent.send_message.await_args.kwargs["reply_to_message_id"] == 5
        assert parent.send_rich_message.await_args.args == (
            CHAT_ID, InputRichMessage(html=HTML_TEXT))
        assert parent.send_rich_message.await_args.kwargs["reply_parameters"] == (
            ReplyParameters(message_id=5))
        service.get_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_generic_exception_pool_then_continue(self, info_cleanup):
        """#3': delete бросает прочий Exception → как #2' (пул + rich-справка)."""
        service = _service()
        info_mod.setup_info(service)
        msg = _make_msg("/info")
        msg.delete = AsyncMock(side_effect=RuntimeError("сеть"))
        bot = AsyncMock()
        await info_mod.cmd_info(msg, bot=bot)
        pool_call = bot.send_message.await_args_list[0]
        assert pool_call.args[1] in INFO_NO_DELETE_RIGHTS_PHRASES
        assert pool_call.kwargs["reply_to_message_id"] == 5
        assert bot.send_rich_message.await_args.args == (
            CHAT_ID, InputRichMessage(html=HTML_TEXT))
        assert bot.send_rich_message.await_args.kwargs["reply_parameters"] == (
            ReplyParameters(message_id=5))

    @pytest.mark.asyncio
    async def test_no_rights_help_replied_to_visible_command(self, info_cleanup):
        """NEW (53.7): нет прав + успех → справка приходит с
        reply_parameters == ReplyParameters(message_id=77)
        (команда висит в чате)."""
        service = _service()
        info_mod.setup_info(service)
        msg = _make_msg("/info", message_id=77)
        msg.delete = AsyncMock(side_effect=_no_rights_400())
        bot = AsyncMock()
        await info_mod.cmd_info(msg, bot=bot)
        help_call = bot.send_rich_message.await_args_list[-1]
        assert help_call.args == (CHAT_ID, InputRichMessage(html=HTML_TEXT))
        assert help_call.kwargs["reply_parameters"] == ReplyParameters(message_id=77)

    @pytest.mark.asyncio
    async def test_no_rights_and_cooldown_pool_throttle_no_help(
        self, info_cleanup, fake_time
    ):
        """NEW (53.7): нет прав + кулдаун активен → пул прав реплаем;
        throttle 5.1 реплаем; справка НЕ шлётся (return после кулдауна)."""
        service = _service()
        info_mod.setup_info(service)
        bot = AsyncMock()
        first = _make_msg("/info", user_id=1)
        await info_mod.cmd_info(first, bot=bot)
        assert bot.send_rich_message.await_count == 1

        fake_time["now"] += 100
        expected_remaining = info_mod._cooldown.remaining(CHAT_ID, 0)
        assert expected_remaining > 0
        second = _make_msg("/info", user_id=2, message_id=6)
        second.delete = AsyncMock(side_effect=_no_rights_400())
        await info_mod.cmd_info(second, bot=bot)
        calls = bot.send_message.await_args_list
        assert len(calls) == 2
        assert calls[0].args[1] in INFO_NO_DELETE_RIGHTS_PHRASES
        assert calls[0].kwargs["reply_to_message_id"] == 6
        fmt = format_remaining_time(expected_remaining)
        candidates = [p.replace("{remaining_time}", fmt) for p in THROTTLE_PHRASES]
        assert calls[1].args[1] in candidates
        assert calls[1].kwargs["reply_to_message_id"] == 6
        assert service.get_text.call_count == 1     # справка после кулдауна НЕ слалась

    @pytest.mark.asyncio
    async def test_cooldown_throttles_but_still_deletes(self, info_cleanup, fake_time):
        """#4: 2-й /info в том же чате (другой user) → 5.1 с remaining;
        команда УДАЛЕНА (порядок delete→кулдаун); другой chat — не троттлится."""
        service = _service()
        info_mod.setup_info(service)
        bot = AsyncMock()
        first = _make_msg("/info", user_id=1)
        await info_mod.cmd_info(first, bot=bot)
        assert bot.send_rich_message.await_count == 1

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
        assert bot.send_message.await_count == 1              # справка не слалась

        other = _make_msg("/info", user_id=3, chat_id=-987654321, message_id=7)
        await info_mod.cmd_info(other, bot=bot)
        assert bot.send_rich_message.await_count == 2         # другой чат — ок

    @pytest.mark.asyncio
    async def test_rich_bad_request_html_fallback(self, info_cleanup, caplog):
        """D231: rich 400 → sendMessage + parse_mode="HTML" с legacy-эмуляцией
        (_rich_to_legacy_html); HTML ТОЖЕ 400 → plain БЕЗ parse_mode; WARNING
        с причиной в логе."""
        text = "<h1>Заголовок</h1><h2>Секция</h2><b><i>цитата</i></b>"
        service = _service(get_text=text)
        info_mod.setup_info(service)
        msg = _make_msg("/info")
        bot = AsyncMock()
        bot.send_rich_message = AsyncMock(side_effect=_rich_400())
        bot.send_message = AsyncMock(side_effect=[
            TelegramBadRequest(method=None, message="Bad Request: can't parse entities"),
            None,
        ])
        with caplog.at_level(logging.WARNING):
            await info_mod.cmd_info(msg, bot=bot)
        legacy = info_mod._rich_to_legacy_html(text)
        calls = bot.send_message.await_args_list
        assert len(calls) == 2
        assert calls[0].args[1] == legacy
        assert calls[0].kwargs["parse_mode"] == "HTML"
        assert calls[1].args[1] == legacy
        assert "parse_mode" not in calls[1].kwargs
        assert any("rich rejected" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_plain_fallback_failure_logged_not_raised(self, info_cleanup, caplog):
        """Вторичный сбой plain-фолбека (после rich 400 + HTML 400) →
        logger.exception, не падает."""
        service = _service(get_text="<h1>битая разметка")
        info_mod.setup_info(service)
        msg = _make_msg("/info")
        bot = AsyncMock()
        bot.send_rich_message = AsyncMock(side_effect=_rich_400())
        bot.send_message = AsyncMock(side_effect=[
            TelegramBadRequest(method=None, message="Bad Request: can't parse entities"),
            Exception("сеть упала"),
        ])
        with caplog.at_level(logging.ERROR):
            await info_mod.cmd_info(msg, bot=bot)
        assert any("plain fallback failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_legacy_html_fallback_generic_failure_logged(self, info_cleanup, caplog):
        """Сбой legacy-HTML-фолбека непонятным Exception → logger.exception."""
        service = _service(get_text="<h1>текст</h1>")
        info_mod.setup_info(service)
        msg = _make_msg("/info")
        bot = AsyncMock()
        bot.send_rich_message = AsyncMock(side_effect=_rich_400())
        bot.send_message = AsyncMock(side_effect=ConnectionError("сеть упала"))
        with caplog.at_level(logging.ERROR):
            await info_mod.cmd_info(msg, bot=bot)
        assert any("[/info] send failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_send_generic_exception_logged_not_raised(self, info_cleanup, caplog):
        """Наружный except Exception (сеть/не-rich сбой отправки) — покрытие 100%."""
        service = _service()
        info_mod.setup_info(service)
        msg = _make_msg("/info")
        bot = AsyncMock()
        bot.send_rich_message = AsyncMock(side_effect=ConnectionError("сеть упала"))
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
        bot.send_rich_message.assert_not_called()

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
        bot.send_rich_message.assert_not_called()
        service.save_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_valid_preview_then_save_then_ok(self, info_cleanup):
        """#9: bot.send_rich_message(ADMIN_USER_ID, InputRichMessage(html=text))
        ДО save_text (порядок); save_text(new_text); INFO_EDIT_OK реплаем."""
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

        bot.send_rich_message = AsyncMock(side_effect=on_send)
        msg = _make_msg("/edit_info <b>новая справка</b>", user_id=ADMIN_ID)
        await info_mod.cmd_edit_info(msg, bot=bot)
        assert events[:2] == ["send", "save"]              # превью ДО сохранения
        service.save_text.assert_called_once_with("<b>новая справка</b>")
        preview = bot.send_rich_message.await_args_list[0]
        assert preview.args == (ADMIN_ID,
                                InputRichMessage(html="<b>новая справка</b>"))
        ok_call = bot.send_message.await_args_list[-1]
        assert ok_call.args[1] in INFO_EDIT_OK_PHRASES
        assert ok_call.kwargs["reply_to_message_id"] == 5

    @pytest.mark.asyncio
    async def test_preview_bad_markup_file_untouched(self, info_cleanup):
        """#10: rich-превью бросает TelegramBadRequest →
        INFO_BAD_MARKUP_PHRASES; save_text НЕ вызван; кэш/файл нетронуты (D163)."""
        service = _service()
        info_mod.setup_info(service)
        msg = _make_msg("/edit_info <h1>криво", user_id=ADMIN_ID)
        bot = AsyncMock()
        bot.send_rich_message = AsyncMock(side_effect=_rich_400())
        await info_mod.cmd_edit_info(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in INFO_BAD_MARKUP_PHRASES
        service.save_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_preview_forbidden_same_pool_no_save(self, info_cleanup):
        """#11: rich-превью бросает Forbidden/сеть → тот же пул; save НЕ вызван."""
        service = _service()
        info_mod.setup_info(service)
        msg = _make_msg("/edit_info <b>новое</b>", user_id=ADMIN_ID)
        bot = AsyncMock()
        bot.send_rich_message = AsyncMock(
            side_effect=TelegramForbiddenError(
                method=None, message="bot was blocked by the user"
            )
        )
        await info_mod.cmd_edit_info(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in INFO_BAD_MARKUP_PHRASES
        service.save_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_preview_too_long_pool_without_rich_call(self, info_cleanup):
        """Epic 58: len(new_text) > 32768 → сразу INFO_BAD_MARKUP_PHRASES,
        send_rich_message НЕ вызывается, файл/кэш нетронуты."""
        service = _service()
        info_mod.setup_info(service)
        msg = _make_msg("/edit_info " + "x" * 32769, user_id=ADMIN_ID)
        bot = AsyncMock()
        await info_mod.cmd_edit_info(msg, bot=bot)
        bot.send_rich_message.assert_not_called()
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
        bot.send_rich_message.assert_not_called()
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
        bot.send_rich_message.assert_not_called()
        service.save_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_service_skips(self, info_cleanup):
        info_mod._service = None
        msg = _make_msg("/edit_info <b>новое</b>", user_id=ADMIN_ID)
        bot = AsyncMock()
        await info_mod.cmd_edit_info(msg, bot=bot)
        bot.send_message.assert_not_called()
        bot.send_rich_message.assert_not_called()
