"""Epic 52 (T-417) — dead page delete detection (R52-8, D214).

Тесты:
  - маппинг {репост Славика → dead page бота} создаётся (on_forward + БД);
  - InaccessibleMessage в reply_to → бот удаляет СВОИ dead pages, в чат ничего
    не шлётся, маппинг снят;
  - delete_message кидает 403 → ОДНА фраза из пула с reply на вызвавшее
    сообщение, маппинг снят атомарным claim'ом;
  - 400 «message can't be deleted» / 404 (TelegramNotFound) → идемпотентно
    удалён, БЕЗ фразы, маппинг снят (H1);
  - 5xx/сетевые (TelegramServerError/TelegramNetworkError) → маппинг СОХРАНЁН,
    фразы нет (M3);
  - двойной reply при 403 в одном цикле → ровно ОДНА фраза (M2, atomic claim);
  - повторный update той же пары → UNHANDLED (маппинга нет);
  - нет маппинга → UNHANDLED (пропагация живёт);
  - reply на живой репост (обычный Message) → UNHANDLED;
  - TTL/cleanup: запись старше 24ч удаляется при следующей записи.
"""
import asyncio
import datetime
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramServerError,
)
from aiogram.types import Chat, InaccessibleMessage, Message, User

from handlers.dead_page_delete import (
    DEAD_PAGE_DELETE_PHRASES,
    dead_page_delete_handler,
    setup_dead_page_delete,
)
from services.database import DatabaseService

CHAT_ID = -1001234567890


def _make_inaccessible(reply_to_msg_id: int = 77) -> InaccessibleMessage:
    return InaccessibleMessage(
        chat=Chat(id=CHAT_ID, type="group"),
        message_id=reply_to_msg_id,
        date=0,
    )


def _make_message(from_id: int = 111, reply_to: object = None):
    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = from_id
    msg.message_id = 999
    msg.reply_to_message = reply_to
    msg.reply = AsyncMock()
    msg.bot = AsyncMock()
    msg.bot.delete_message = AsyncMock()
    return msg


class TestDeadPageDeleteHandler:
    """Handler: InaccessibleMessage-детект + действия (а)/(б)."""

    @pytest.fixture(autouse=True)
    def _reset_db(self):
        mock_db = MagicMock()
        mock_db.get_dead_page_repost_map = AsyncMock(return_value=[100, 101])
        mock_db.delete_dead_page_repost_map = AsyncMock()
        mock_db.try_claim_dead_page_repost_map = AsyncMock(return_value=True)
        setup_dead_page_delete(mock_db, bot_id=12345)
        yield mock_db
        setup_dead_page_delete(None)

    @pytest.mark.asyncio
    async def test_no_reply_to_returns_unhandled(self, _reset_db):
        msg = _make_message(reply_to=None)
        result = await dead_page_delete_handler(msg)
        assert result is UNHANDLED
        msg.bot.delete_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reply_to_live_message_unhandled(self, _reset_db):
        """Reply на ЖИВОЙ репост (обычный Message с from_user) → UNHANDLED."""
        live = Message(
            message_id=77,
            date=datetime.datetime.now(),
            chat=Chat(id=CHAT_ID, type="group"),
            from_user=User(id=479167456, is_bot=False, first_name="Слава"),
            text="репост",
        )
        msg = _make_message(reply_to=live)
        result = await dead_page_delete_handler(msg)
        assert result is UNHANDLED
        msg.bot.delete_message.assert_not_awaited()
        msg.reply.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_self_message_unhandled(self, _reset_db):
        """Свои сообщения бота не триггерят."""
        msg = _make_message(from_id=12345, reply_to=_make_inaccessible())
        result = await dead_page_delete_handler(msg)
        assert result is UNHANDLED
        msg.bot.delete_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_mapping_unhandled(self, _reset_db):
        """Маппинга нет → UNHANDLED (пропагация живёт)."""
        _reset_db.get_dead_page_repost_map = AsyncMock(return_value=None)
        msg = _make_message(reply_to=_make_inaccessible())
        result = await dead_page_delete_handler(msg)
        assert result is UNHANDLED
        msg.bot.delete_message.assert_not_awaited()
        msg.reply.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_inaccessible_message_deletes_bot_pages(self, _reset_db):
        """(а): права есть → delete_message для каждого id из маппинга,
        в чат НИЧЕГО не отправлено, маппинг удалён."""
        msg = _make_message(reply_to=_make_inaccessible())
        result = await dead_page_delete_handler(msg)

        assert result is None                       # consume
        assert msg.bot.delete_message.await_count == 2
        msg.bot.delete_message.assert_any_await(chat_id=CHAT_ID, message_id=100)
        msg.bot.delete_message.assert_any_await(chat_id=CHAT_ID, message_id=101)
        msg.reply.assert_not_awaited()
        _reset_db.delete_dead_page_repost_map.assert_awaited_once_with(CHAT_ID, 77)

    @pytest.mark.asyncio
    async def test_403_sends_one_phrase(self, _reset_db):
        """(б): delete_message кидает 403 → ОДНА фраза из пула с reply,
        маппинг снят атомарным claim'ом (H1 + M2)."""
        msg = _make_message(reply_to=_make_inaccessible())
        msg.bot.delete_message = AsyncMock(
            side_effect=TelegramForbiddenError(
                method="deleteMessage", message="Forbidden: bot is not an administrator"
            )
        )
        result = await dead_page_delete_handler(msg)

        assert result is None
        msg.reply.assert_awaited_once()
        phrase = msg.reply.await_args.args[0]
        assert phrase in DEAD_PAGE_DELETE_PHRASES
        _reset_db.try_claim_dead_page_repost_map.assert_awaited_once_with(CHAT_ID, 77)
        _reset_db.delete_dead_page_repost_map.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_403_partial_success_still_phrase(self, _reset_db):
        """Частичный успех: первый id удалён, второй — 403 → фраза, маппинг снят."""
        msg = _make_message(reply_to=_make_inaccessible())

        async def delete_side_effect(chat_id, message_id):
            if message_id == 101:
                raise TelegramForbiddenError(
                    method="deleteMessage", message="Forbidden"
                )
            return True

        msg.bot.delete_message = AsyncMock(side_effect=delete_side_effect)
        result = await dead_page_delete_handler(msg)

        assert result is None
        msg.reply.assert_awaited_once()
        assert msg.reply.await_args.args[0] in DEAD_PAGE_DELETE_PHRASES
        _reset_db.try_claim_dead_page_repost_map.assert_awaited_once_with(CHAT_ID, 77)

    @pytest.mark.asyncio
    async def test_400_cant_be_deleted_no_phrase(self, _reset_db):
        """H1: 400 «message can't be deleted» (старее 48ч / ограничение прав) →
        идемпотентно удалён, фразы НЕТ, маппинг снят."""
        msg = _make_message(reply_to=_make_inaccessible())
        msg.bot.delete_message = AsyncMock(
            side_effect=TelegramBadRequest(
                method="deleteMessage",
                message="Bad Request: message can't be deleted",
            )
        )
        result = await dead_page_delete_handler(msg)

        assert result is None
        msg.reply.assert_not_awaited()
        _reset_db.delete_dead_page_repost_map.assert_awaited_once_with(CHAT_ID, 77)
        _reset_db.try_claim_dead_page_repost_map.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_404_not_found_no_phrase(self, _reset_db):
        """H1: 404 (TelegramNotFound — реальный класс aiogram 3.29.1, наследник
        TelegramAPIError, НЕ TelegramBadRequest) → идемпотентно удалён,
        фразы НЕТ, маппинг снят."""
        msg = _make_message(reply_to=_make_inaccessible())
        msg.bot.delete_message = AsyncMock(
            side_effect=TelegramNotFound(
                method="deleteMessage", message="Not Found: message not found"
            )
        )
        result = await dead_page_delete_handler(msg)

        assert result is None
        msg.reply.assert_not_awaited()
        _reset_db.delete_dead_page_repost_map.assert_awaited_once_with(CHAT_ID, 77)
        _reset_db.try_claim_dead_page_repost_map.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_403_error_treated_as_deleted(self, _reset_db):
        """L2 (H1): голый TelegramAPIError заменён на TelegramNotFound —
        именно 404-класс «message not found» означает «уже удалено»."""
        msg = _make_message(reply_to=_make_inaccessible())
        msg.bot.delete_message = AsyncMock(
            side_effect=TelegramNotFound(method="deleteMessage", message="not found")
        )
        result = await dead_page_delete_handler(msg)

        assert result is None
        msg.reply.assert_not_awaited()
        _reset_db.delete_dead_page_repost_map.assert_awaited_once_with(CHAT_ID, 77)

    @pytest.mark.asyncio
    async def test_5xx_error_mapping_kept(self, _reset_db):
        """M3: 500 (TelegramServerError) → транзиентная ошибка: маппинг НЕ
        снимается (следующий reply перепробует), фразы нет."""
        msg = _make_message(reply_to=_make_inaccessible())
        msg.bot.delete_message = AsyncMock(
            side_effect=TelegramServerError(
                method="deleteMessage", message="Internal Server Error"
            )
        )
        result = await dead_page_delete_handler(msg)

        assert result is None
        msg.reply.assert_not_awaited()
        _reset_db.delete_dead_page_repost_map.assert_not_awaited()
        _reset_db.try_claim_dead_page_repost_map.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_network_error_mapping_kept(self, _reset_db):
        """M3: TelegramNetworkError (сетевой сбой) → маппинг СОХРАНЁН."""
        msg = _make_message(reply_to=_make_inaccessible())
        msg.bot.delete_message = AsyncMock(
            side_effect=TelegramNetworkError(
                method="deleteMessage", message="NetworkError: connection reset"
            )
        )
        result = await dead_page_delete_handler(msg)

        assert result is None
        msg.reply.assert_not_awaited()
        _reset_db.delete_dead_page_repost_map.assert_not_awaited()
        _reset_db.try_claim_dead_page_repost_map.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unexpected_api_error_mapping_kept(self, _reset_db):
        """Защитный случай: прочий TelegramAPIError → маппинг не теряем
        безвозвратно (фразы нет)."""
        from aiogram.exceptions import TelegramAPIError

        msg = _make_message(reply_to=_make_inaccessible())
        msg.bot.delete_message = AsyncMock(
            side_effect=TelegramAPIError(method="deleteMessage", message="mystery")
        )
        result = await dead_page_delete_handler(msg)

        assert result is None
        msg.reply.assert_not_awaited()
        _reset_db.delete_dead_page_repost_map.assert_not_awaited()
        _reset_db.try_claim_dead_page_repost_map.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_double_reply_403_single_phrase(self, _reset_db):
        """M2: два reply на удалённый репост в одном цикле (оба прочитали
        маппинг до delete, оба получают 403) → фразу шлёт ровно первый
        (атомарный claim)."""
        _reset_db.try_claim_dead_page_repost_map = AsyncMock(
            side_effect=[True, False]
        )

        msg1 = _make_message(reply_to=_make_inaccessible())
        msg1.bot.delete_message = AsyncMock(
            side_effect=TelegramForbiddenError(method="deleteMessage", message="Forbidden")
        )
        msg2 = _make_message(reply_to=_make_inaccessible())
        msg2.bot.delete_message = AsyncMock(
            side_effect=TelegramForbiddenError(method="deleteMessage", message="Forbidden")
        )

        await dead_page_delete_handler(msg1)
        await dead_page_delete_handler(msg2)

        msg1.reply.assert_awaited_once()
        assert msg1.reply.await_args.args[0] in DEAD_PAGE_DELETE_PHRASES
        msg2.reply.assert_not_awaited()
        assert _reset_db.try_claim_dead_page_repost_map.await_count == 2

    @pytest.mark.asyncio
    async def test_repeat_update_mapping_gone_unhandled(self, _reset_db):
        """Повторный update той же пары → маппинга нет → UNHANDLED."""
        msg = _make_message(reply_to=_make_inaccessible())
        await dead_page_delete_handler(msg)

        _reset_db.get_dead_page_repost_map = AsyncMock(return_value=None)
        result = await dead_page_delete_handler(msg)
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_db_error_returns_none_no_spam(self, _reset_db):
        """Ошибка БД → WARNING + return None (не спамить повторами)."""
        _reset_db.get_dead_page_repost_map = AsyncMock(
            side_effect=RuntimeError("db down")
        )
        msg = _make_message(reply_to=_make_inaccessible())
        result = await dead_page_delete_handler(msg)
        assert result is None
        msg.reply.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_phrase_pool_minimum_size(self, _reset_db):
        """Пул DEAD_PAGE_DELETE_PHRASES — минимум 3–5 фраз (T-417-D)."""
        assert len(DEAD_PAGE_DELETE_PHRASES) >= 3
        for phrase in DEAD_PAGE_DELETE_PHRASES:
            assert isinstance(phrase, str) and phrase


class TestDeadPageRepostMapDB:
    """БД: маппинг, TTL-очистка, cap (Section 61.6.2)."""

    @pytest.fixture
    def db(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        d = DatabaseService(":memory:")
        loop.run_until_complete(d.initialize())
        yield d
        loop.run_until_complete(d.close())
        loop.close()

    @pytest.mark.asyncio
    async def test_record_and_get(self, db):
        await db.record_dead_page_repost_map(CHAT_ID, 77, [100, 101])
        assert await db.get_dead_page_repost_map(CHAT_ID, 77) == [100, 101]
        assert await db.get_dead_page_repost_map(CHAT_ID, 78) is None

    @pytest.mark.asyncio
    async def test_insert_or_replace(self, db):
        await db.record_dead_page_repost_map(CHAT_ID, 77, [100])
        await db.record_dead_page_repost_map(CHAT_ID, 77, [200, 201])
        assert await db.get_dead_page_repost_map(CHAT_ID, 77) == [200, 201]

    @pytest.mark.asyncio
    async def test_delete_mapping(self, db):
        await db.record_dead_page_repost_map(CHAT_ID, 77, [100])
        await db.delete_dead_page_repost_map(CHAT_ID, 77)
        assert await db.get_dead_page_repost_map(CHAT_ID, 77) is None

    @pytest.mark.asyncio
    async def test_try_claim_atomic_single(self, db):
        """M2: try_claim — атомарный DELETE + rowcount: первый claim True,
        повторный False, маппинг снят."""
        await db.record_dead_page_repost_map(CHAT_ID, 77, [100])
        assert await db.try_claim_dead_page_repost_map(CHAT_ID, 77) is True
        assert await db.get_dead_page_repost_map(CHAT_ID, 77) is None
        assert await db.try_claim_dead_page_repost_map(CHAT_ID, 77) is False

    @pytest.mark.asyncio
    async def test_try_claim_no_mapping_returns_false(self, db):
        assert await db.try_claim_dead_page_repost_map(CHAT_ID, 77) is False

    @pytest.mark.asyncio
    async def test_no_duplicate_index_on_repost_map(self, db):
        """L4: UNIQUE (chat_id, repost_msg_id) авто-создаёт sqlite_autoindex —
        явного idx_dprm_chat_repost в схеме НЕТ (удалён как дублирующий)."""
        cursor = await db.db.execute("PRAGMA index_list('dead_page_repost_map')")
        rows = await cursor.fetchall()
        names = [row["name"] for row in rows]
        assert "idx_dprm_chat_repost" not in names
        assert any(name.startswith("sqlite_autoindex") for name in names)

    @pytest.mark.asyncio
    async def test_ttl_cleanup_on_next_record(self, db):
        """Запись старше 24ч удаляется при следующей записи (ленивая TTL-очистка)."""
        await db.record_dead_page_repost_map(CHAT_ID, 77, [100])
        old = time.time() - 86400 - 10
        await db.db.execute(
            "UPDATE dead_page_repost_map SET created_at = ? WHERE repost_msg_id = 77",
            (old,),
        )
        await db.db.commit()

        await db.record_dead_page_repost_map(CHAT_ID, 78, [200])

        assert await db.get_dead_page_repost_map(CHAT_ID, 77) is None
        assert await db.get_dead_page_repost_map(CHAT_ID, 78) == [200]

    @pytest.mark.asyncio
    async def test_cap_cleanup_keeps_last_500(self, db):
        """Cap-очистка: при переполнении остаются последние 500 записей."""
        for i in range(510):
            await db.record_dead_page_repost_map(CHAT_ID, 1000 + i, [i])
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM dead_page_repost_map")
        row = await cursor.fetchone()
        assert row["c"] == 500
        # последние записи на месте, старейшие вытеснены
        assert await db.get_dead_page_repost_map(CHAT_ID, 1000) is None
        assert await db.get_dead_page_repost_map(CHAT_ID, 1509) == [509]

    @pytest.mark.asyncio
    async def test_chat_isolation(self, db):
        await db.record_dead_page_repost_map(CHAT_ID, 77, [100])
        await db.record_dead_page_repost_map(-200, 77, [300])
        assert await db.get_dead_page_repost_map(CHAT_ID, 77) == [100]
        assert await db.get_dead_page_repost_map(-200, 77) == [300]
