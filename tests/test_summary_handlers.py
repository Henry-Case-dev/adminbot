"""Tests for handlers/summary.py (T-184) + 13-router integration (T-188-B)."""
import asyncio
import datetime
import logging
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Router
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import (
    Chat,
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
    User,
)

from config.settings import settings
from handlers import summary as summary_mod
from handlers.summary import (
    cmd_summary,
    setup_summary,
    summary_observer,
    summary_observer_router,
    summary_router,
)
from services.database import DatabaseService
from services.summary_aliases import AliasResolver

CHAT_ID = -1001234567890
SLAVIK_ID = 479167456


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


@pytest.fixture
def setup_cleanup():
    yield
    summary_mod._generator = None
    summary_mod._db = None
    summary_mod._aliases = None
    summary_mod._bot_id = None


def _make_real_message(user_id, text, chat_id, bot_mock, **fields):
    message = Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=Chat(id=chat_id, type="group"),
        from_user=User(id=user_id, is_bot=False, first_name="Тест"),
        text=text,
        **fields,
    )
    message._bot = bot_mock
    return message


class TestObserver:
    @pytest.mark.asyncio
    async def test_saves_ordinary_message_and_returns_unhandled(
        self, db, make_message, setup_cleanup
    ):
        aliases = AliasResolver('{"1": "шкет"}')
        setup_summary(None, db, aliases, bot_id=None)
        msg = make_message(from_id=1, text="привет всем", reply_to_message=None,
                           username="@sket", first_name="Вася", last_name="Пупкин")
        result = await summary_observer(msg)
        assert result is UNHANDLED
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert len(rows) == 1
        row = rows[0]
        assert row["text"] == "привет всем"
        assert row["author_name"] == "шкет"  # alias wins
        assert row["media_type"] == "text"

    @pytest.mark.asyncio
    async def test_caption_saved_with_media_type(self, db, make_message, setup_cleanup):
        from aiogram.types import PhotoSize

        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = _make_real_message(
            1, None, CHAT_ID, AsyncMock(),
            caption="глянь фото",
            photo=[PhotoSize(file_id="f", file_unique_id="u", width=10, height=10)],
        )
        result = await summary_observer(msg)
        assert result is UNHANDLED
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["media_type"] == "photo"
        assert rows[0]["text"] == "глянь фото"

    @pytest.mark.asyncio
    async def test_media_without_caption_saved(self, db, setup_cleanup):
        from aiogram.types import Video

        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = _make_real_message(
            1, None, CHAT_ID, AsyncMock(),
            video=Video(file_id="f", file_unique_id="u", width=10, height=10, duration=1),
        )
        result = await summary_observer(msg)
        assert result is UNHANDLED
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["media_type"] == "video"
        assert rows[0]["text"] is None

    @pytest.mark.asyncio
    async def test_reply_to_id_saved(self, db, make_message, setup_cleanup):
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        reply = MagicMock()
        reply.message_id = 777
        msg = make_message(from_id=1, text="ответ", reply_to_message=reply)
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["reply_to_id"] == 777

    @pytest.mark.asyncio
    async def test_service_message_skipped(self, db, setup_cleanup):
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = _make_real_message(1, None, CHAT_ID, AsyncMock())
        result = await summary_observer(msg)
        assert result is UNHANDLED
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows == []

    @pytest.mark.asyncio
    async def test_bot_own_message_skipped(self, db, make_message, setup_cleanup):
        setup_summary(None, db, AliasResolver(""), bot_id=999)
        msg = make_message(from_id=999, text="я бот", reply_to_message=None)
        result = await summary_observer(msg)
        assert result is UNHANDLED
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows == []

    @pytest.mark.asyncio
    async def test_no_from_user_skipped(self, db, make_message, setup_cleanup):
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="аноним", reply_to_message=None,
                           from_user=None)
        result = await summary_observer(msg)
        assert result is UNHANDLED
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows == []

    @pytest.mark.asyncio
    async def test_not_initialized_returns_unhandled(self, make_message, setup_cleanup):
        msg = make_message(from_id=1, text="привет", reply_to_message=None)
        result = await summary_observer(msg)
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_save_failure_warns_and_returns_unhandled(
        self, make_message, setup_cleanup, caplog
    ):
        bad_db = MagicMock()
        bad_db.save_smart_message = AsyncMock(side_effect=RuntimeError("бд сдохла"))
        setup_summary(None, bad_db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="привет", reply_to_message=None)
        with caplog.at_level(logging.WARNING):
            result = await summary_observer(msg)
        assert result is UNHANDLED
        assert any("save failed" in r.message for r in caplog.records)

    def test_observer_router_has_handler(self):
        assert len(summary_observer_router.message.handlers) >= 1

    # ── B9 (Epic 25): команды /summary* не пишутся в память ──

    @pytest.mark.asyncio
    async def test_summary_command_not_saved(self, db, make_message, setup_cleanup):
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="/summary", reply_to_message=None)
        result = await summary_observer(msg)
        assert result is UNHANDLED
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows == []

    @pytest.mark.asyncio
    async def test_foreign_summary_command_not_saved(self, db, make_message, setup_cleanup):
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="/summary@RofloslavBot", reply_to_message=None)
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows == []

    @pytest.mark.asyncio
    async def test_summary_prefix_command_not_saved(self, db, make_message, setup_cleanup):
        """B9: guard по префиксу — /summaryfoo тоже не сохраняется."""
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="/summaryfoo", reply_to_message=None)
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows == []

    @pytest.mark.asyncio
    async def test_caption_summary_command_not_saved(self, db, make_message, setup_cleanup):
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text=None, caption="/summary", reply_to_message=None)
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows == []

    @pytest.mark.asyncio
    async def test_plain_message_still_saved_after_b9(self, db, make_message, setup_cleanup):
        """Регрессия: B9 не ломает сохранение обычных сообщений."""
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="про саммари разговор", reply_to_message=None)
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert [r["text"] for r in rows] == ["про саммари разговор"]


# ── Epic 28 (T-212): forward-маркировка observer ───────────

def _now():
    return datetime.datetime.now()


class TestObserverForward:
    def _channel_origin(self):
        return MessageOriginChannel(
            date=_now(),
            chat=Chat(id=-777, type="channel", title="Канал X", username="channelx"),
            message_id=5,
            author_signature="Подпись",
        )

    def _user_origin(self):
        return MessageOriginUser(
            date=_now(),
            sender_user=User(
                id=5, is_bot=False, first_name="Вася", last_name="Пупкин", username="vasya"
            ),
        )

    def _hidden_origin(self):
        return MessageOriginHiddenUser(date=_now(), sender_user_name="Аноним")

    def _chat_origin(self):
        return MessageOriginChat(
            date=_now(),
            sender_chat=Chat(id=-888, type="group", title="Чат X", username="chatx"),
        )

    @pytest.mark.asyncio
    async def test_channel_origin_saved_with_source(self, db, make_message, setup_cleanup):
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="переслали", reply_to_message=None, forward_origin=self._channel_origin())
        result = await summary_observer(msg)
        assert result is UNHANDLED
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["is_forward"] == 1
        assert rows[0]["forward_source"] == "Канал X @channelx Подпись"

    @pytest.mark.asyncio
    async def test_channel_origin_title_only(self, db, make_message, setup_cleanup):
        origin = MessageOriginChannel(
            date=_now(), chat=Chat(id=-777, type="channel", title="Просто канал"),
            message_id=5,
        )
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="x", reply_to_message=None, forward_origin=origin)
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["is_forward"] == 1
        assert rows[0]["forward_source"] == "Просто канал"

    @pytest.mark.asyncio
    async def test_user_origin_resolved_through_aliases(self, db, make_message, setup_cleanup):
        setup_summary(None, db, AliasResolver('{"5": "вася-алиас"}'), bot_id=None)
        msg = make_message(from_id=1, text="x", reply_to_message=None, forward_origin=self._user_origin())
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["is_forward"] == 1
        assert rows[0]["forward_source"] == "вася-алиас"

    @pytest.mark.asyncio
    async def test_user_origin_nickname_without_aliases(self, db, make_message, setup_cleanup):
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="x", reply_to_message=None, forward_origin=self._user_origin())
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["is_forward"] == 1
        assert rows[0]["forward_source"] == "Вася Пупкин"

    @pytest.mark.asyncio
    async def test_hidden_user_origin(self, db, make_message, setup_cleanup):
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="x", reply_to_message=None, forward_origin=self._hidden_origin())
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["is_forward"] == 1
        assert rows[0]["forward_source"] == "Аноним"

    @pytest.mark.asyncio
    async def test_chat_origin(self, db, make_message, setup_cleanup):
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="x", reply_to_message=None, forward_origin=self._chat_origin())
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["is_forward"] == 1
        assert rows[0]["forward_source"] == "Чат X @chatx"

    @pytest.mark.asyncio
    async def test_unknown_origin_type_saved_with_empty_source(
        self, db, make_message, setup_cleanup
    ):
        """Неизвестный тип origin: is_forward=True, forward_source='' (содержание чужое)."""
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="x", reply_to_message=None, forward_origin=object())
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["is_forward"] == 1
        assert rows[0]["forward_source"] == ""

    @pytest.mark.asyncio
    async def test_source_truncated_to_100_chars(self, db, make_message, setup_cleanup):
        origin = MessageOriginChannel(
            date=_now(),
            chat=Chat(id=-777, type="channel", title="К" * 150),
            message_id=5,
        )
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="x", reply_to_message=None, forward_origin=origin)
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["is_forward"] == 1
        assert len(rows[0]["forward_source"]) == 100

    @pytest.mark.asyncio
    async def test_extraction_failure_saves_as_forward_empty_source(
        self, db, make_message, setup_cleanup, monkeypatch
    ):
        """Сбой экстракции не роняет сохранение: is_forward=1, source=''."""
        original = summary_mod._build_nickname

        def selective_boom(user):
            if getattr(user, "id", None) == 5:  # только sender_user из origin
                raise RuntimeError("кривой origin")
            return original(user)

        monkeypatch.setattr(summary_mod, "_build_nickname", selective_boom)
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="x", reply_to_message=None, forward_origin=self._user_origin())
        result = await summary_observer(msg)
        assert result is UNHANDLED
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["is_forward"] == 1
        assert rows[0]["forward_source"] == ""

    @pytest.mark.asyncio
    async def test_plain_message_saved_without_forward(self, db, make_message, setup_cleanup):
        setup_summary(None, db, AliasResolver(""), bot_id=None)
        msg = make_message(from_id=1, text="обычное", reply_to_message=None)
        await summary_observer(msg)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert rows[0]["is_forward"] == 0
        assert rows[0]["forward_source"] == ""


class TestSummaryCommand:
    @pytest.mark.asyncio
    async def test_ack_before_pipeline_and_manual_flag(self, make_message, setup_cleanup):
        """B1/B2: ack отдельным send_message ДО generate_and_send(manual=True)."""
        events = []

        generator = MagicMock()

        async def _generate(chat_id, manual=False):
            events.append("generate")

        generator.generate_and_send = AsyncMock(side_effect=_generate)
        setup_summary(generator)

        bot = AsyncMock()

        async def _send(chat_id, text):
            events.append(("send", text))

        bot.send_message = AsyncMock(side_effect=_send)

        msg = make_message(from_id=SLAVIK_ID, text="/summary", delete=AsyncMock())
        mod = replace(settings, ALLOWED_SUMMARY_IDS=())
        with patch.object(summary_mod, "settings", mod):
            result = await cmd_summary(msg, bot=bot)

        assert result is None
        assert events[0][0] == "send"
        assert events[0][1] in summary_mod._UX_ACK_VARIANTS
        assert events[1] == "generate"
        generator.generate_and_send.assert_awaited_once_with(CHAT_ID, manual=True)

    @pytest.mark.asyncio
    async def test_delete_called_before_ack_before_pipeline(self, make_message, setup_cleanup):
        """D81: удаление команды ДО ack и до пайплайна (delete → ack → generate)."""
        events = []

        generator = MagicMock()
        generator.generate_and_send = AsyncMock(
            side_effect=lambda *a, **k: events.append("generate")
        )
        setup_summary(generator)
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=lambda *a, **k: events.append("ack"))
        msg = make_message(
            from_id=SLAVIK_ID, text="/summary",
            delete=AsyncMock(side_effect=lambda: events.append("delete")),
        )
        mod = replace(settings, ALLOWED_SUMMARY_IDS=())
        with patch.object(summary_mod, "settings", mod):
            await cmd_summary(msg, bot=bot)
        assert events == ["delete", "ack", "generate"]

    def test_ack_pool_contains_canon(self):
        """D82: каноничная фраза «ща гляну, подожди» остаётся в пуле."""
        assert "ща гляну, подожди" in summary_mod._UX_ACK_VARIANTS

    def test_ack_pool_size_at_least_20(self):
        """D82: пул — ~20 вариаций."""
        assert len(summary_mod._UX_ACK_VARIANTS) >= 20

    def test_ack_pool_style(self):
        """D82: все фразы — с маленькой буквы, без эмодзи."""
        for phrase in summary_mod._UX_ACK_VARIANTS:
            assert phrase == phrase.lower()
            assert not any(0x1F000 <= ord(ch) <= 0x1FAFF for ch in phrase)

    @pytest.mark.asyncio
    async def test_log_order_delete_before_ack(self, make_message, setup_cleanup, caplog):
        """D81/T-221-C: журнал в фактическом порядке: triggered → command deleted → ack sent."""
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        setup_summary(generator)
        bot = AsyncMock()
        msg = make_message(from_id=SLAVIK_ID, text="/summary", delete=AsyncMock())
        mod = replace(settings, ALLOWED_SUMMARY_IDS=())
        with patch.object(summary_mod, "settings", mod), caplog.at_level(logging.INFO):
            await cmd_summary(msg, bot=bot)

        def _stage(text: str) -> str | None:
            for marker in ("triggered", "command deleted", "command delete failed", "ack sent"):
                if marker in text:
                    return marker
            return None

        stages = [
            stage for record in caplog.records
            if record.name == "handlers.summary" and (stage := _stage(record.message))
        ]
        assert stages.index("triggered") < stages.index("command deleted") < stages.index("ack sent")

    @pytest.mark.asyncio
    async def test_ack_is_not_reply(self, make_message, setup_cleanup):
        """B1: ack — send_message (не reply/answer)."""
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        setup_summary(generator)
        bot = AsyncMock()
        msg = make_message(from_id=SLAVIK_ID, text="/summary", delete=AsyncMock())
        mod = replace(settings, ALLOWED_SUMMARY_IDS=())
        with patch.object(summary_mod, "settings", mod):
            await cmd_summary(msg, bot=bot)
        msg.reply.assert_not_called()
        msg.answer.assert_not_called()
        bot.send_message.assert_awaited_once()
        sent = bot.send_message.await_args.args
        assert sent[0] == CHAT_ID
        assert sent[1] in summary_mod._UX_ACK_VARIANTS

    @pytest.mark.asyncio
    async def test_allowed_empty_everyone(self, make_message, setup_cleanup):
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        setup_summary(generator)
        bot = AsyncMock()
        mod = replace(settings, ALLOWED_SUMMARY_IDS=())
        msg = make_message(from_id=SLAVIK_ID, text="/summary", delete=AsyncMock())
        with patch.object(summary_mod, "settings", mod):
            result = await cmd_summary(msg, bot=bot)
        assert result is None
        generator.generate_and_send.assert_awaited_once_with(CHAT_ID, manual=True)

    @pytest.mark.asyncio
    async def test_allowed_list_contains_user(self, make_message, setup_cleanup):
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        setup_summary(generator)
        bot = AsyncMock()
        mod = replace(settings, ALLOWED_SUMMARY_IDS=(SLAVIK_ID, 42))
        msg = make_message(from_id=SLAVIK_ID, text="/summary", delete=AsyncMock())
        with patch.object(summary_mod, "settings", mod):
            await cmd_summary(msg, bot=bot)
        generator.generate_and_send.assert_awaited_once_with(CHAT_ID, manual=True)

    @pytest.mark.asyncio
    async def test_not_allowed_silently_absorbed(self, make_message, setup_cleanup, caplog):
        """R9/B8: denied → нет ack, нет delete, нет ответа; только INFO-лог."""
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        setup_summary(generator)
        bot = AsyncMock()
        mod = replace(settings, ALLOWED_SUMMARY_IDS=(42,))
        msg = make_message(from_id=SLAVIK_ID, text="/summary", delete=AsyncMock())
        with patch.object(summary_mod, "settings", mod), caplog.at_level(logging.INFO):
            result = await cmd_summary(msg, bot=bot)
        assert result is None  # НЕ UNHANDLED — propagation остановлен
        generator.generate_and_send.assert_not_called()
        bot.send_message.assert_not_called()
        msg.delete.assert_not_called()
        msg.reply.assert_not_called()
        msg.answer.assert_not_called()
        assert any("denied" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_generator_not_initialized_ux(self, make_message, setup_cleanup):
        """B6: _generator is None → UX «не смог сделать саммари» через DI-bot."""
        setup_summary(None)
        bot = AsyncMock()
        mod = replace(settings, ALLOWED_SUMMARY_IDS=())
        msg = make_message(from_id=SLAVIK_ID, text="/summary", delete=AsyncMock())
        with patch.object(summary_mod, "settings", mod):
            await cmd_summary(msg, bot=bot)
        bot.send_message.assert_awaited_once_with(CHAT_ID, "не смог сделать саммари")
        msg.delete.assert_not_called()
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_generator_none_without_bot_no_crash(self, make_message, setup_cleanup):
        """B6: bot=None (юнит-вызов) → warning, не падение."""
        setup_summary(None)
        mod = replace(settings, ALLOWED_SUMMARY_IDS=())
        msg = make_message(from_id=SLAVIK_ID, text="/summary", delete=AsyncMock())
        with patch.object(summary_mod, "settings", mod):
            await cmd_summary(msg)
        msg.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_failure_does_not_break_pipeline(self, make_message, setup_cleanup, caplog):
        """B7: отказ удаления (нет прав delete_messages) → WARNING, пайплайн жив."""
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        setup_summary(generator)
        bot = AsyncMock()
        msg = make_message(
            from_id=SLAVIK_ID, text="/summary",
            delete=AsyncMock(side_effect=Exception("нет прав")),
        )
        mod = replace(settings, ALLOWED_SUMMARY_IDS=())
        with patch.object(summary_mod, "settings", mod), caplog.at_level(logging.WARNING):
            await cmd_summary(msg, bot=bot)
        generator.generate_and_send.assert_awaited_once_with(CHAT_ID, manual=True)
        bot.send_message.assert_awaited_once()  # ack всё равно ушёл
        assert any("command delete failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_ack_send_failure_does_not_break_pipeline(self, make_message, setup_cleanup):
        """B6: отказ отправки ack не роняет хендлер — delete и пайплайн выполняются."""
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        setup_summary(generator)
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=Exception("сеть упала"))
        msg = make_message(from_id=SLAVIK_ID, text="/summary", delete=AsyncMock())
        mod = replace(settings, ALLOWED_SUMMARY_IDS=())
        with patch.object(summary_mod, "settings", mod):
            await cmd_summary(msg, bot=bot)
        msg.delete.assert_awaited_once()
        generator.generate_and_send.assert_awaited_once_with(CHAT_ID, manual=True)

    def test_summary_router_has_command_handler(self):
        assert len(summary_router.message.handlers) >= 1

    def test_summary_router_has_throttle_middleware(self):
        outer = summary_router.message.outer_middleware
        names = [m.__class__.__name__ for m in outer._middlewares]
        assert "ThrottlingMiddleware" in names


# ═══════════════════════════════════════════════════════════════
# Integration: all 13 routers on one dispatcher (T-188-B)
# ═══════════════════════════════════════════════════════════════

_ALL_ROUTERS = None


def _collect_routers():
    global _ALL_ROUTERS
    if _ALL_ROUTERS is not None:
        return _ALL_ROUTERS
    from handlers.admin_commands import admin_commands_router
    from handlers.alan import alan_router
    from handlers.alan_greeting import alan_greeting_router
    from handlers.common import common_router
    from handlers.dead_page_trigger import dead_page_router
    from handlers.kostik import kostik_router
    from handlers.olya import olya_router
    from handlers.slava_presence import slava_presence_router
    from handlers.slavik import slavik_router
    from handlers.vasya import vasya_router
    from handlers.war_alert import war_alert_router

    _ALL_ROUTERS = [
        summary_observer_router,  # 0a
        summary_router,           # 0b
        admin_commands_router,    # 0
        slava_presence_router,    # 1
        alan_greeting_router,     # 1b
        kostik_router,            # 2
        alan_router,              # 3
        dead_page_router,         # 4
        war_alert_router,         # 4b
        common_router,            # 4c
        olya_router,              # 4d
        slavik_router,            # 5
        vasya_router,             # 6
    ]
    return _ALL_ROUTERS


def _wire_existing_services(db):
    from handlers.admin_commands import setup_admin_commands
    from handlers.alan import setup_alan
    from handlers.common import setup_common, setup_common_mimic
    from handlers.dead_page_trigger import setup_dead_page
    from handlers.olya import setup_olya
    from handlers.slava_presence import setup_presence
    from handlers.slavik import setup_slavik
    from handlers.war_alert import setup_war_alert

    relay = MagicMock()
    mimic = MagicMock()
    olya = MagicMock()
    scheduler = MagicMock()
    setup_admin_commands(MagicMock())
    setup_presence(MagicMock(), scheduler)
    setup_dead_page(relay, db)
    setup_war_alert()
    setup_slavik(db)
    setup_common(relay)
    setup_common_mimic(mimic)
    setup_olya(olya)
    setup_alan(db)


@pytest.fixture
def integration_env(db):
    generators = []

    generator = MagicMock()
    generator.generate_and_send = AsyncMock()
    generators.append(generator)

    parent = Router(name="test_parent")
    routers = _collect_routers()
    for router in routers:
        router._parent_router = None
        parent.include_router(router)

    _wire_existing_services(db)
    setup_summary(generator, db, AliasResolver(""), bot_id=None)

    yield parent, generator, db

    # cleanup: detach routers and module state
    for router in routers:
        router._parent_router = None
    summary_mod._generator = None
    summary_mod._db = None
    summary_mod._aliases = None
    summary_mod._bot_id = None


class TestRouterIntegration:
    @pytest.mark.asyncio
    async def test_summary_from_slavik_does_not_trigger_catchall(self, integration_env):
        parent, generator, db = integration_env
        bot_mock = AsyncMock()
        bot_mock.send_message = AsyncMock()

        message = _make_real_message(SLAVIK_ID, "/summary", -1001, bot_mock)
        await parent.propagate_event(
            update_type="message", event=message, bot=bot_mock
        )

        generator.generate_and_send.assert_awaited_once_with(-1001, manual=True)
        # B7: команда удалена (aiogram: delete → bot(DeleteMessage))
        assert bot_mock.await_count == 1
        assert bot_mock.await_args.args[0].__class__.__name__ == "DeleteMessage"
        # B1: ack отдельным send_message; Слава не ответил «пошёл нахуй»
        assert bot_mock.send_message.await_count == 1
        assert bot_mock.send_message.await_args.args[1] in summary_mod._UX_ACK_VARIANTS
        # B9: команда не попала в память наблюдателя (0a вернул UNHANDLED)
        rows = await db.get_smart_window(-1001, 0, 10)
        assert all(not (r["text"] or "").lstrip().startswith("/summary") for r in rows)

    @pytest.mark.asyncio
    async def test_summary_not_allowed_silently_absorbed(self, integration_env):
        parent, generator, db = integration_env
        bot_mock = AsyncMock()
        bot_mock.send_message = AsyncMock()

        mod = replace(settings, ALLOWED_SUMMARY_IDS=(42,))
        message = _make_real_message(SLAVIK_ID, "/summary", -1002, bot_mock)
        with patch.object(summary_mod, "settings", mod):
            await parent.propagate_event(
                update_type="message", event=message, bot=bot_mock
            )

        generator.generate_and_send.assert_not_called()
        assert bot_mock.await_count == 0  # и Слава молчит
        bot_mock.send_message.assert_not_called()  # B1: denied → без ack

    @pytest.mark.asyncio
    async def test_summary_from_other_user_works(self, integration_env):
        parent, generator, db = integration_env
        bot_mock = AsyncMock()
        bot_mock.send_message = AsyncMock()

        message = _make_real_message(777, "/summary", -1003, bot_mock)
        await parent.propagate_event(
            update_type="message", event=message, bot=bot_mock
        )

        generator.generate_and_send.assert_awaited_once_with(-1003, manual=True)
        # B7: удаление команды — единственный вызов bot-объекта
        assert bot_mock.await_count == 1
        assert bot_mock.await_args.args[0].__class__.__name__ == "DeleteMessage"
        # B1: ack отдельным send_message
        assert bot_mock.send_message.await_count == 1
        assert bot_mock.send_message.await_args.args[1] in summary_mod._UX_ACK_VARIANTS

    @pytest.mark.asyncio
    async def test_ordinary_message_still_reaches_slavik(self, integration_env):
        """Наблюдатель не блокирует propagation: обычное сообщение Славы
        по-прежнему обрабатывается его catch-all («пошёл нахуй»)."""
        parent, generator, db = integration_env
        bot_mock = AsyncMock()
        bot_mock.send_message = AsyncMock(return_value=MagicMock())

        message = _make_real_message(SLAVIK_ID, "привет народ", -1004, bot_mock)
        await parent.propagate_event(
            update_type="message", event=message, bot=bot_mock
        )

        generator.generate_and_send.assert_not_called()
        assert bot_mock.await_count == 1
        sent_method = bot_mock.await_args.args[0]
        assert sent_method.__class__.__name__ == "SendMessage"
        assert sent_method.text == "пошёл нахуй"
        rows = await db.get_smart_window(-1004, 0, 10)
        assert any(r["text"] == "привет народ" for r in rows)

    @pytest.mark.asyncio
    async def test_observer_does_not_save_bot_messages(self, integration_env):
        parent, generator, db = integration_env
        bot_mock = MagicMock()
        bot_mock.id = 555
        bot_mock.send_message = AsyncMock(return_value=MagicMock())

        summary_mod._bot_id = 555
        message = _make_real_message(555, "я бот", -1005, bot_mock)
        await parent.propagate_event(
            update_type="message", event=message, bot=bot_mock
        )
        rows = await db.get_smart_window(-1005, 0, 10)
        assert rows == []

    def test_router_count_is_13(self):
        routers = _collect_routers()
        assert len(routers) == 13
        assert len(set(id(r) for r in routers)) == 13
