import pytest
from pathlib import Path
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

    @pytest.mark.asyncio
    async def test_kucha_with_gif_flag_skips_dalbaeb(self, make_message):
        """T-410: КУЧА + data-флаг (гифка уже ушла) → ДАЛБАЕБ НЕ шлётся."""
        msg = make_message(479167456, text="КУЧА денег")
        result = await kucha_handler(msg, data={"slavik_gif_sent": True})
        assert result is UNHANDLED
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_kucha_without_flag_replies_dalbaeb(self, make_message):
        """T-410: КУЧА без флага → ДАЛБАЕБ (прежнее поведение)."""
        msg = make_message(479167456, text="КУЧА денег")
        await kucha_handler(msg, data={})
        msg.reply.assert_called_once_with("ДАЛБАЕБ")


class TestSlavikCatchall:
    @pytest.mark.asyncio
    async def test_replies_poshel_nahui(self, make_message):
        msg = make_message(479167456, text="любое сообщение")
        await slavik_catchall_handler(msg)
        msg.reply.assert_called_once_with("пошёл нахуй")


# ── Epic 52 (T-410): одно действие на сообщение ──


class TestSlavikOneAction:
    """T-410 (Section 61.4.3): жёсткий приоритет ровно одного действия."""

    @pytest.fixture(autouse=True)
    def _reset_db(self):
        import handlers.slavik as slavik_module
        original_db = slavik_module._db
        slavik_module._db = None
        yield
        slavik_module._db = original_db

    @pytest.mark.asyncio
    async def test_gif_flag_skips_poshel_nahui(self, make_message, _reset_db):
        """Branch 1: data['slavik_gif_sent']=True → return, «пошёл нахуй» НЕ шлётся."""
        msg = make_message(479167456, text="любое сообщение")
        result = await slavik_catchall_handler(msg, data={"slavik_gif_sent": True})
        assert result is None
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_gif_flag_skips_random_media(self, make_message, monkeypatch, _reset_db):
        """Branch 1 > Branch 2: гифка ушла → slavic_photo_count_tick НЕ тикает."""
        import handlers.slavik as slavik_module
        mock_db = AsyncMock()
        mock_db.slavic_photo_count_tick = AsyncMock(return_value=True)
        slavik_module._db = mock_db
        monkeypatch.setattr(slavik_module, "settings", _make_mock_settings())

        msg = make_message(479167456, text="сообщение с гифкой")
        msg.answer_photo = AsyncMock()
        result = await slavik_catchall_handler(msg, data={"slavik_gif_sent": True})

        assert result is None
        mock_db.slavic_photo_count_tick.assert_not_called()
        msg.reply.assert_not_called()
        msg.answer_photo.assert_not_called()

    @pytest.mark.asyncio
    async def test_service_message_returns_unhandled(self, make_message, _reset_db):
        """Branch 0.5: new_chat_members → UNHANDLED (join обрабатывает slava_presence)."""
        msg = make_message(479167456, text="Слава в чате")
        msg.new_chat_members = [MagicMock()]
        result = await slavik_catchall_handler(msg)
        assert result is UNHANDLED
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_service_message_leave_returns_unhandled(self, make_message, _reset_db):
        """Branch 0.5: left_chat_member → UNHANDLED."""
        msg = make_message(479167456, text="Слава вышел")
        msg.left_chat_member = MagicMock()
        result = await slavik_catchall_handler(msg)
        assert result is UNHANDLED
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_random_media_replaces_poshel_nahui(self, make_message, monkeypatch, _reset_db):
        """Branch 2 > Branch 4: фото-интервал достигнут → медиа ВМЕСТО «пошёл нахуй»."""
        import handlers.slavik as slavik_module
        mock_db = AsyncMock()
        mock_db.slavic_photo_count_tick = AsyncMock(return_value=True)
        slavik_module._db = mock_db
        monkeypatch.setattr(slavik_module, "settings", _make_mock_settings())

        with patch("handlers.slavik._pick_random_slavik_media") as mock_pick:
            fake_pick = (Path("media/slavik/photo.jpg"), "photo")
            mock_pick.return_value = fake_pick
            with patch("handlers.slavik._send_slavik_media") as mock_send:
                msg = make_message(479167456, text="любое сообщение")
                await slavik_catchall_handler(msg)
                mock_send.assert_called_once_with(msg, fake_pick[0], fake_pick[1])

        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_mimic_replaces_poshel_nahui(self, make_message, monkeypatch, _reset_db):
        """Branch 3 > Branch 4: mimic вместо «пошёл нахуй» (существующее поведение)."""
        import handlers.slavik as slavik_module
        monkeypatch.setattr(
            slavik_module, "settings",
            _make_mock_settings(SLAVIK_MIMIC_COOLDOWN=0.0, SLAVIC_PHOTO_INTERVAL=0),
        )
        with patch("handlers.slavik.mimic_transform", return_value="передразнил") as mock_mimic:
            msg = make_message(479167456, text="один два три четыре пять шесть")
            await slavik_catchall_handler(msg)

        msg.reply.assert_called_once_with("передразнил")

    @pytest.mark.asyncio
    async def test_dead_page_priority_over_gif_flag(self, make_message, _reset_db):
        """Branch 0 > Branch 1: d_pages-репост → UNHANDLED даже при data-флаге."""
        msg = make_message(479167456, text="репост из d_pages")
        msg.forward_origin = TestSlavikCatchallDeadPageGate._make_channel_origin(-100999, "d_pages")
        result = await slavik_catchall_handler(msg, data={"slavik_gif_sent": True})
        assert result is UNHANDLED
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_gif_flag_no_data_dict(self, make_message, _reset_db):
        """data=None (прямой вызов без миддлвари) — флага нет, поведение прежнее."""
        msg = make_message(479167456, text="любое сообщение")
        await slavik_catchall_handler(msg, data=None)
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


# ── Epic 52 (T-410, Section 61.4.4): join-интеграция через Dispatcher ──


class TestSlavikJoinIntegration:
    """T-410: join Славы (message-фоллбек new_chat_members) → ровно «ДОЛБОЕБ
    ВЕРНУЛСЯ»; миддлварь пропускает service-сообщение (без гифки), catchall
    отдаёт UNHANDLED (0.5) → рандом-медиа и «пошёл нахуй» отсутствуют."""

    @pytest.fixture
    def db(self):
        import asyncio
        from services.database import DatabaseService
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        d = DatabaseService(":memory:")
        loop.run_until_complete(d.initialize())
        yield d
        loop.run_until_complete(d.close())
        loop.close()

    @pytest.mark.asyncio
    async def test_join_only_dolboeb_no_gif_no_media(self, db):
        import asyncio
        import datetime

        import handlers.slava_presence as presence_mod
        import handlers.slavik as slavik_mod
        from aiogram import Dispatcher
        from aiogram.types import Chat, Message, Update, User
        from services.message_counter import MessageCounterMiddleware

        for router in (presence_mod.slava_presence_router, slavik_mod.slavik_router):
            router._parent_router = None

        dp = Dispatcher()
        dp.include_router(presence_mod.slava_presence_router)   # 1
        dp.include_router(slavik_mod.slavik_router)             # 5

        scheduler = MagicMock()
        scheduler.signal_immediate_post = AsyncMock()
        presence_mod.setup_presence(db, scheduler)
        slavik_mod.setup_slavik(db)
        middleware = MessageCounterMiddleware(db)
        slavik_mod.slavik_router.message.middleware(middleware)

        try:
            bot = AsyncMock()
            bot.send_message = AsyncMock()

            slava = User(id=479167456, is_bot=False, first_name="Слава")
            message = Message(
                message_id=1,
                date=datetime.datetime.now(),
                chat=Chat(id=-1001234567890, type="group"),
                from_user=slava,
                new_chat_members=[slava],
            )
            await dp.feed_update(bot, Update(update_id=1, message=message))

            # ровно один ответ — «ДОЛБОЕБ ВЕРНУЛСЯ» (message.reply → bot(SendMessage))
            bot.assert_awaited_once()
            sent_method = bot.await_args.args[0]
            assert sent_method.text == "ДОЛБОЕБ ВЕРНУЛСЯ"
            scheduler.signal_immediate_post.assert_awaited_once()
            # никакой гифки и никакого медиа на входе
            assert not any(
                c.args[0].text == "пошёл нахуй" for c in bot.await_args_list
                if getattr(c.args[0], "text", None)
            )
        finally:
            # обязательно снять миддлварь — иначе другие тесты (test_slavik_priority
            # и др.) получат её на общем роутере с закрытой БД
            slavik_mod.slavik_router.message.middleware.unregister(middleware)

        for router in (presence_mod.slava_presence_router, slavik_mod.slavik_router):
            router._parent_router = None
