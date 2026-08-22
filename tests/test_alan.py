"""Tests for Alan_Z reply engine (F6) and silence greeting (F7v2).

Tests cover:
  - Counter increments correctly
  - Reply fires every ALAN_REPLY_INTERVAL (10) messages
  - Reply does NOT fire on non-divisible messages
  - Random selection from reply pool
  - DB dependency injection
  - No reply when DB not set up
  - Silence greeting: baseline, threshold exceeded, threshold not reached
  - Silence greeting: disabled, float threshold, cooldown suppression
  - Silence greeting: multi-chat isolation, error handling
  - F6 + F7v2 coexistence
  - UNHANDLED return for propagation
"""
import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, patch

from handlers.alan import alan_handler, setup_alan, ALAN_REPLIES, _last_greeting
from handlers.alan_greeting import _greeting_locks
from aiogram.dispatcher.event.bases import UNHANDLED


class TestAlanHandler:
    """Unit tests for the Alan reply engine handler."""

    @pytest.mark.asyncio
    async def test_reply_fires_every_10_messages(self, make_message):
        """Reply should fire exactly on messages 10, 20, 30, etc."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        # Messages 1-9: no reply
        for i in range(1, 10):
            mock_db.increment_and_get_count.return_value = i
            msg = make_message(138811255, text=f"message {i}")
            await alan_handler(msg)
            msg.reply.assert_not_called()

        # Message 10: reply fires
        mock_db.increment_and_get_count.return_value = 10
        msg = make_message(138811255, text="message 10")
        await alan_handler(msg)
        msg.reply.assert_called_once()
        reply_arg = msg.reply.call_args[0][0]
        assert reply_arg in ALAN_REPLIES

    @pytest.mark.asyncio
    async def test_no_reply_on_non_divisible(self, make_message):
        """Messages not divisible by interval should not trigger reply."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        for count in [1, 3, 7, 11, 19, 21, 99]:
            mock_db.increment_and_get_count.return_value = count
            msg = make_message(138811255, text=f"msg_{count}")
            await alan_handler(msg)
            msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_at_20_30_40(self, make_message):
        """Verify reply fires at each multiple of 10."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        for count in [10, 20, 30, 40, 50]:
            mock_db.increment_and_get_count.return_value = count
            msg = make_message(138811255, text=f"msg_{count}")
            await alan_handler(msg)
            msg.reply.assert_called_once()
            reply_arg = msg.reply.call_args[0][0]
            assert reply_arg in ALAN_REPLIES
            msg.reply.reset_mock()

    @pytest.mark.asyncio
    async def test_random_selection_from_pool(self, make_message):
        """Over many calls, we should see different replies (not always the same)."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        seen_replies = set()
        for i in range(1, 51):
            mock_db.increment_and_get_count.return_value = i
            msg = make_message(138811255, text=f"msg_{i}")
            await alan_handler(msg)
            if msg.reply.called:
                seen_replies.add(msg.reply.call_args[0][0])
                msg.reply.reset_mock()

        # At 10,20,30,40,50 we should have 5 replies
        # They should not all be identical (probabilistic check)
        assert len(seen_replies) >= 2, (
            f"Expected at least 2 unique replies from 5 calls, got {len(seen_replies)}"
        )

    @pytest.mark.asyncio
    async def test_all_replies_in_pool_are_strings(self):
        """All entries in ALAN_REPLIES must be non-empty strings."""
        for reply in ALAN_REPLIES:
            assert isinstance(reply, str), f"Non-string reply: {reply!r}"
            assert len(reply) > 0, f"Empty reply found in pool"

    @pytest.mark.asyncio
    async def test_pool_has_minimum_size(self):
        """Pool should have at least 16 variants (6 original + 10 new)."""
        assert len(ALAN_REPLIES) >= 16, (
            f"ALAN_REPLIES pool has {len(ALAN_REPLIES)} entries, need at least 16"
        )

    @pytest.mark.asyncio
    async def test_topic_coverage(self):
        """Key topics must be represented in the reply pool.

        T-408 (Epic 52): «фьючерс» убран из обязательных тем; добавлены новые
        (никс/линукс, нейрокластер, планшет, ссд, витамин, тренажёр/гантел, колен).
        """
        pool_text = " ".join(ALAN_REPLIES).lower()
        required_topics = [
            "тренировк",   # тренировки/тренировка
            "лонгковид",
            "нейросет",    # нейросети/нейросеть/нейросетки
            "жим дьявола",
            # ── новые темы T-408 ──
            "никс",        # NixOS/никсы
            "линукс",
            "нейрокластер",
            "планшет",
            "колен",       # колени (тренажёр + реванш)
        ]
        for topic in required_topics:
            assert topic in pool_text, f"Topic '{topic}' not found in ALAN_REPLIES"
        # SSD может писаться латиницей (SSD) или кириллицей (ссд)
        assert ("ssd" in pool_text or "ссд" in pool_text), "Topic 'SSD/ссд' not found in ALAN_REPLIES"
        assert ("витамин" in pool_text or "life extension" in pool_text), \
            "Topic 'витамины Life Extension' not found in ALAN_REPLIES"
        assert ("тренажёр" in pool_text or "гантел" in pool_text), \
            "Topic 'тренажёр/гантели' not found in ALAN_REPLIES"

    @pytest.mark.asyncio
    async def test_no_trading_words(self):
        """T-408: в пуле НЕТ трейдинг-слов (фьючерсы/биток/рынок/трейдеры и т.п.).

        Word-boundary матчинг: «лонгковид» НЕ считается «лонг» (после «лонг»
        идёт буква → граница не срабатывает).
        """
        trading_words = [
            "фьючерс", "биток", "биткоин", "рынок", "трейдер",
            "график", "шорт", "лонг", "крипт",
        ]
        pool_text = " ".join(ALAN_REPLIES).lower()
        for word in trading_words:
            pattern = r"(?<![0-9a-zа-яё_])" + word + r"(?![0-9a-zа-яё_])"
            assert not __import__("re").search(pattern, pool_text), (
                f"Trading word '{word}' found in ALAN_REPLIES: {pool_text}"
            )

    @pytest.mark.asyncio
    async def test_no_reply_for_wrong_user(self, make_message):
        """Handler itself does NOT filter by user ID — that's the router/filter's job.
        
        The UserIdFilter decorator on alan_router handles user-ID matching.
        When calling the handler directly (bypassing the router), it processes
        any message. This is correct: filtering is a router concern.
        
        The UserIdFilter itself is tested in test_filters.py.
        """
        mock_db = AsyncMock()
        setup_alan(mock_db)

        # Even with wrong user ID, handler processes it (filtering happens at router level)
        mock_db.increment_and_get_count.return_value = 10
        mock_db.get_alan_last_message_ts = AsyncMock(return_value=None)
        mock_db.set_alan_last_message_ts = AsyncMock()
        msg = make_message(479167456, text="hello")

        with patch("handlers.alan._send_greeting", return_value=True):
            with patch("handlers.alan._last_greeting", {}):
                with patch("handlers.alan.settings") as mock_settings:
                    mock_settings.ALAN_SILENCE_GREETING_HOURS = 6.0
                    mock_settings.ALAN_REPLY_INTERVAL = 10
                    mock_settings.ALAN_GREETING_COOLDOWN = 10
                    await alan_handler(msg)

        # Handler fires because we bypassed the router filter — this is expected
        msg.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_reply_when_db_not_setup(self, make_message):
        """If setup_alan() was never called, handler should silently return."""
        global alan_db
        from handlers import alan as alan_module
        alan_module.alan_db = None  # Simulate no setup

        msg = make_message(138811255, text="hello")
        await alan_handler(msg)
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_counter_increments_even_without_reply(self, make_message):
        """increment_and_get_count should be called on every message, not just reply ones."""
        mock_db = AsyncMock()
        setup_alan(mock_db)
        mock_db.increment_and_get_count.return_value = 3

        msg = make_message(138811255, text="message that won't trigger reply")
        await alan_handler(msg)
        mock_db.increment_and_get_count.assert_called_once_with(msg.chat.id, msg.from_user.id)

    @pytest.mark.asyncio
    async def test_configurable_interval(self, make_message, monkeypatch):
        """Changing ALAN_REPLY_INTERVAL via a new Settings instance changes reply timing."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        # Create a new settings instance with interval=5 and inject into alan module
        import config.settings as settings_module
        new_settings = settings_module.Settings(
            ALAN_REPLY_INTERVAL=5,
        )
        monkeypatch.setattr("handlers.alan.settings", new_settings)

        # Count 5: should fire
        mock_db.increment_and_get_count.return_value = 5
        msg = make_message(138811255, text="fifth message")
        await alan_handler(msg)
        msg.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_replies_disabled_flag(self, make_message):
        """T-408: ALAN_REPLIES_ENABLED=False → reply-блок молчит, счётчик инкрементится."""
        mock_db = AsyncMock()
        setup_alan(mock_db)
        mock_db.increment_and_get_count.return_value = 10  # кратно интервалу

        with patch("handlers.alan.settings") as mock_settings:
            mock_settings.ALAN_REPLIES_ENABLED = False
            mock_settings.ALAN_REPLY_INTERVAL = 10
            mock_settings.ALAN_SILENCE_GREETING_HOURS = 0  # F7v2 выключен — чисто reply-блок
            msg = make_message(138811255, text="сообщение на 10-м счётчике")
            await alan_handler(msg)

        msg.reply.assert_not_called()
        mock_db.increment_and_get_count.assert_called_once_with(msg.chat.id, msg.from_user.id)

    @pytest.mark.asyncio
    async def test_replies_disabled_flag_default_true(self, make_message):
        """T-408: default (флаг не выставлялся) — reply работает как раньше."""
        mock_db = AsyncMock()
        setup_alan(mock_db)
        mock_db.increment_and_get_count.return_value = 10

        with patch("handlers.alan.settings") as mock_settings:
            mock_settings.ALAN_REPLIES_ENABLED = True
            mock_settings.ALAN_REPLY_INTERVAL = 10
            mock_settings.ALAN_SILENCE_GREETING_HOURS = 0
            msg = make_message(138811255, text="десятое сообщение")
            await alan_handler(msg)

        msg.reply.assert_called_once()
        assert msg.reply.call_args[0][0] in ALAN_REPLIES

    @pytest.mark.asyncio
    async def test_non_text_message_also_counts(self, make_message):
        """Photo/sticker messages should still increment counter and potentially reply."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        # Photo message (no text)
        mock_db.increment_and_get_count.return_value = 10
        msg = make_message(138811255, text=None)
        msg.photo = []  # Simulate photo message
        await alan_handler(msg)
        msg.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_reply_uses_message_reply(self, make_message):
        """Verify reply is sent as a reply to the original message."""
        mock_db = AsyncMock()
        setup_alan(mock_db)
        mock_db.increment_and_get_count.return_value = 10

        msg = make_message(138811255, text="test reply")
        await alan_handler(msg)
        msg.reply.assert_called_once()
        # message.reply() should be called (not answer() or send_message())
        assert msg.reply.called
        assert not msg.answer.called

    @pytest.mark.asyncio
    async def test_same_chat_separate_counters(self, make_message):
        """Different chats should have independent counters."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        # Chat A: count 10 → reply
        mock_db.increment_and_get_count.return_value = 10
        msg_a = make_message(138811255, text="chat A msg", chat_id=-100)
        await alan_handler(msg_a)
        assert msg_a.reply.called

        # Chat B: count 9 → no reply (separate counter)
        mock_db.increment_and_get_count.return_value = 9
        msg_b = make_message(138811255, text="chat B msg", chat_id=-200)
        await alan_handler(msg_b)
        msg_b.reply.assert_not_called()


class TestEpic53AlanTopics:
    """Epic 53 (D215, Section 62.2, тест-план 62.5 #14-15): 5 новых тем
    полноценные (≥3 фразы на маркер), пул вопросов присутствует, фраза
    alan.py:43 (старая) удалена, контракты сохранены."""

    TOPIC_MARKERS = {
        "NixOS/Линукс": ("никс", "nix"),
        "SSD": ("ssd", "ссд"),
        "Витамины Life Extension": ("life extension", "витамин"),
        "5-сек прогулки с гантелями": ("гантел",),
        "Уличный тренажёр + колени": ("уличн", "тренажёр"),
    }

    QUESTION_POOL = (
        "разминку сделал или сразу к железу с негнущимися коленями?",
        "а ты вообще разминался? или как обычно — с дивана сразу к штанге?",
        "гантели для прогулки сегодня брал или опять филонишь?",
        "дыхалку тренируешь или она у тебя уже по гарантии не подлежит ремонту?",
        "сколько раз сегодня размялся? ноль раз — это тоже результат, запиши в дневничок",
    )

    @pytest.mark.asyncio
    async def test_new_topics_have_at_least_three_phrases(self):
        """62.5 #14: на каждую из 5 тем — маркер в ≥3 фразах пула (канон даёт 5)."""
        pool = [phrase.lower() for phrase in ALAN_REPLIES]
        for topic, markers in self.TOPIC_MARKERS.items():
            count = sum(1 for phrase in pool if any(m in phrase for m in markers))
            assert count >= 3, f"Тема '{topic}': {count} фраз < 3"

    @pytest.mark.asyncio
    async def test_question_pool_verbatim_present(self):
        """Пул издевательских вопросов (62.2.2) присутствует байт-в-байт."""
        for question in self.QUESTION_POOL:
            assert question in ALAN_REPLIES, f"Вопрос '{question}' не найден в пуле"

    @pytest.mark.asyncio
    async def test_old_line43_phrase_removed(self):
        """Старая фраза alan.py:43 удалена (заменена пулом вопросов, D215)."""
        assert not any(
            phrase.startswith("разминался сегодня? я вот на 5-секундной прогулке")
            for phrase in ALAN_REPLIES
        )

    @pytest.mark.asyncio
    async def test_question_phrases_are_questions(self):
        """Каждая фраза пула вопросов содержит '?'; 4 из 5 заканчиваются на
        '?' (5-я фраза канона 62.2.2 — с '?' в середине: «сколько раз сегодня
        размялся? ноль раз — это тоже результат...»)."""
        for phrase in self.QUESTION_POOL:
            assert "?" in phrase
        assert sum(1 for p in self.QUESTION_POOL if p.rstrip().endswith("?")) == 4


class TestAlanSilenceGreeting:
    """Unit tests for F7v2 Alan silence greeting (Epic 11).

    Default settings values are used for most tests:
      ALAN_SILENCE_GREETING_HOURS=6.0, ALAN_GREETING_COOLDOWN=10.
    Tests that need different values replace the entire settings object
    on handlers.alan.settings (Settings is a frozen dataclass).
    """

    NOW = 1721000000.0

    @pytest.fixture(autouse=True)
    def _clear_last_greeting(self):
        """Reset _last_greeting and _greeting_locks between tests to avoid cross-test pollution."""
        _last_greeting.clear()
        _greeting_locks.clear()

    @pytest.mark.asyncio
    async def test_silence_first_message_baseline(self, make_message):
        """First Alan message: no DB record → baseline, no greeting, timestamp recorded."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = None
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting") as mock_send:
                msg = make_message(138811255, text="first msg", chat_id=-100)
                await alan_handler(msg)

        mock_send.assert_not_called()
        mock_db.get_alan_last_message_ts.assert_called_once_with(-100)
        mock_db.set_alan_last_message_ts.assert_called_once_with(-100, self.NOW)

    @pytest.mark.asyncio
    async def test_silence_threshold_exceeded_sends_greeting(self, make_message):
        """elapsed >= threshold → _send_greeting called, _last_greeting updated."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 6.1 * 3600
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                msg = make_message(138811255, text="woke up", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_send.assert_called_once()
        mock_db.set_alan_last_message_ts.assert_called_once_with(-100, self.NOW)
        assert _last_greeting[-100] == self.NOW

    @pytest.mark.asyncio
    async def test_silence_threshold_not_reached_no_greeting(self, make_message):
        """elapsed < threshold → no greeting, timestamp updated."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 2.0 * 3600
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting") as mock_send:
                msg = make_message(138811255, text="quick msg", chat_id=-100)
                await alan_handler(msg)

        mock_send.assert_not_called()
        mock_db.set_alan_last_message_ts.assert_called_once_with(-100, self.NOW)

    @pytest.mark.asyncio
    async def test_silence_disabled_when_zero(self, make_message, monkeypatch):
        """ALAN_SILENCE_GREETING_HOURS=0 → entire silence logic skipped."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        setup_alan(mock_db)

        import config.settings as settings_module
        new_settings = settings_module.Settings(ALAN_SILENCE_GREETING_HOURS=0.0)
        monkeypatch.setattr("handlers.alan.settings", new_settings)

        with patch("handlers.alan._send_greeting") as mock_send:
            msg = make_message(138811255, text="hello", chat_id=-100)
            await alan_handler(msg)

        mock_send.assert_not_called()
        mock_db.get_alan_last_message_ts.assert_not_called()
        mock_db.set_alan_last_message_ts.assert_not_called()

    @pytest.mark.asyncio
    async def test_silence_float_threshold(self, make_message, monkeypatch):
        """ALAN_SILENCE_GREETING_HOURS=0.5 (30 min), elapsed=31 min → triggered."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 31 * 60
        setup_alan(mock_db)

        import config.settings as settings_module
        new_settings = settings_module.Settings(ALAN_SILENCE_GREETING_HOURS=0.5)
        monkeypatch.setattr("handlers.alan.settings", new_settings)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                msg = make_message(138811255, text="back", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_silence_cooldown_suppresses_duplicate(self, make_message):
        """_last_greeting[chat_id]=2s ago, cooldown=10 → suppressed."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        setup_alan(mock_db)

        _last_greeting[-100] = self.NOW - 2

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting") as mock_send:
                msg = make_message(138811255, text="hi", chat_id=-100)
                await alan_handler(msg)

        mock_send.assert_not_called()
        mock_db.set_alan_last_message_ts.assert_called_once_with(-100, self.NOW)

    @pytest.mark.asyncio
    async def test_silence_cooldown_expired_allows_greeting(self, make_message):
        """_last_greeting[chat_id]=15s ago, cooldown=10 → greeting allowed."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        setup_alan(mock_db)

        _last_greeting[-100] = self.NOW - 15

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                msg = make_message(138811255, text="back again", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_silence_multi_chat_isolation(self, make_message):
        """Different chats have independent silence timers."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1

        async def get_last_ts_mock(chat_id):
            if chat_id == -100:
                return self.NOW - 7.0 * 3600
            else:
                return self.NOW - 1.0 * 3600
        mock_db.get_alan_last_message_ts.side_effect = get_last_ts_mock
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                msg_a = make_message(138811255, text="chat A", chat_id=-100)
                msg_a.bot = AsyncMock()
                await alan_handler(msg_a)

                msg_b = make_message(138811255, text="chat B", chat_id=-200)
                msg_b.bot = AsyncMock()
                await alan_handler(msg_b)

        assert mock_send.call_count == 1
        mock_db.set_alan_last_message_ts.assert_any_call(-100, self.NOW)
        mock_db.set_alan_last_message_ts.assert_any_call(-200, self.NOW)

    @pytest.mark.asyncio
    async def test_silence_db_read_error_graceful(self, make_message):
        """get_alan_last_message_ts raises → handler doesn't crash, F6 still works."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.side_effect = Exception("DB read error")
        setup_alan(mock_db)

        with patch("handlers.alan._send_greeting") as mock_send:
            msg = make_message(138811255, text="hello", chat_id=-100)
            await alan_handler(msg)

        mock_send.assert_not_called()
        mock_db.increment_and_get_count.assert_called_once()

    @pytest.mark.asyncio
    async def test_silence_db_write_error_graceful(self, make_message):
        """set_alan_last_message_ts raises → handler doesn't crash."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        mock_db.set_alan_last_message_ts.side_effect = Exception("DB write error")
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                msg = make_message(138811255, text="woke up", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_silence_send_greeting_error_graceful(self, make_message):
        """_send_greeting returns False → handler doesn't crash, timestamp still updated."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=False) as mock_send:
                msg = make_message(138811255, text="woke up", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_send.assert_called_once()
        mock_db.set_alan_last_message_ts.assert_called_once_with(-100, self.NOW)
        assert -100 not in _last_greeting

    @pytest.mark.asyncio
    async def test_f6_reply_still_works_with_silence(self, make_message):
        """F6 reply fires on interval while F7v2 silence is active."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 10
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                msg = make_message(138811255, text="msg 10", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_send.assert_called_once()
        msg.reply.assert_called_once()
        assert msg.reply.call_args[0][0] in ALAN_REPLIES

    @pytest.mark.asyncio
    async def test_f7v2_alive_when_replies_disabled(self, make_message):
        """T-408: ALAN_REPLIES_ENABLED=False + истёкший silence-порог →
        greeting отправлен, reply НЕ отправлен (гейт не трогает F7v2)."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 10   # кратно интервалу → без гейта ответил бы
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                with patch("handlers.alan.settings") as mock_settings:
                    mock_settings.ALAN_REPLIES_ENABLED = False
                    mock_settings.ALAN_REPLY_INTERVAL = 10
                    mock_settings.ALAN_SILENCE_GREETING_HOURS = 6.0
                    mock_settings.ALAN_GREETING_COOLDOWN = 10
                    msg = make_message(138811255, text="woke up but replies off", chat_id=-100)
                    msg.bot = AsyncMock()
                    await alan_handler(msg)

        mock_send.assert_called_once()          # F7v2 жив
        msg.reply.assert_not_called()           # reply-блок молчит
        mock_db.increment_and_get_count.assert_called_once()  # счётчик инкрементился

    @pytest.mark.asyncio
    async def test_silence_timestamp_always_updated(self, make_message):
        """Even when greeting send fails, timestamp is still updated."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=False):
                msg = make_message(138811255, text="woke up", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_db.set_alan_last_message_ts.assert_called_once_with(-100, self.NOW)

    @pytest.mark.asyncio
    async def test_silence_non_alan_ignored(self, make_message):
        """Silence logic should not execute for non-Alan users (UserIdFilter at router level).

        When handler is called directly (bypassing router filter), silence logic
        still executes because it's in the same alan_handler. But for non-Alan messages
        the router won't route to this handler at all. This test verifies that even
        if somehow reached, the logic doesn't crash.
        """
        global alan_db
        from handlers import alan as alan_module

        mock_db = AsyncMock()
        mock_db.increment_and_get_count = AsyncMock(return_value=3)
        mock_db.get_alan_last_message_ts = AsyncMock(return_value=None)
        mock_db.set_alan_last_message_ts = AsyncMock()
        alan_module.alan_db = mock_db

        with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
            with patch("handlers.alan._last_greeting", {}):
                with patch("handlers.alan.settings") as mock_settings:
                    mock_settings.ALAN_SILENCE_GREETING_HOURS = 6.0
                    mock_settings.ALAN_REPLY_INTERVAL = 10
                    mock_settings.ALAN_GREETING_COOLDOWN = 10
                    msg = make_message(99999, text="random message from non-Alan")
                    await alan_handler(msg)

        # Silence greeting should NOT be called (first message = baseline)
        mock_send.assert_not_called()
        # DB should still record timestamp (baseline for non-Alan via this handler)
        mock_db.set_alan_last_message_ts.assert_called_once()


class _FakeSilenceDB:
    """In-memory fake of DatabaseService: get reads dict, set writes — imitates the real DB under lock."""

    def __init__(self):
        self.ts: dict[int, float] = {}
        self.set_count = 0

    async def increment_and_get_count(self, chat_id, user_id):
        return 1

    async def get_alan_last_message_ts(self, chat_id):
        return self.ts.get(chat_id)

    async def set_alan_last_message_ts(self, chat_id, ts):
        self.set_count += 1
        self.ts[chat_id] = ts


class TestAlanSilenceGreetingRace:
    """Concurrency tests for the F7v2 race fix (Epic 35, Section 44).

    Per-chat asyncio.Lock + claim-before-send: a burst of parallel Alan
    messages must produce exactly ONE greeting — the in-memory cooldown and
    the persistent ts are claimed BEFORE `await _send_greeting()`.
    """

    NOW = 1721000000.0

    @pytest.fixture(autouse=True)
    def _clear_greeting_state(self):
        _last_greeting.clear()
        _greeting_locks.clear()

    def _make_slow_send(self, results, delay=0.05):
        async def slow_send(bot, chat_id):
            await asyncio.sleep(delay)
            results.append((bot, chat_id))
            return True
        return slow_send

    def _make_batch(self, make_message, chat_id, count):
        msgs = [make_message(138811255, text=f"burst {i}", chat_id=chat_id) for i in range(count)]
        for m in msgs:
            m.bot = AsyncMock()
        return msgs

    @pytest.mark.asyncio
    async def test_race_three_parallel_calls_single_greeting(self, make_message, caplog):
        """3 parallel alan_handler calls on stale ts → exactly 1 greeting; H2/H3 skip."""
        db = _FakeSilenceDB()
        db.ts[-100] = self.NOW - 7.0 * 3600
        setup_alan(db)

        sends = []
        slow_send = self._make_slow_send(sends)

        with patch("handlers.alan.time.time", return_value=self.NOW), \
             patch("handlers.alan._send_greeting", side_effect=slow_send) as mock_send, \
             caplog.at_level(logging.INFO, logger="handlers.alan"):
            msgs = self._make_batch(make_message, -100, 3)
            await asyncio.gather(*(alan_handler(m) for m in msgs))

        assert mock_send.call_count == 1
        assert db.ts[-100] == self.NOW
        assert caplog.text.count("F7v2: silence greeting triggered") == 1
        assert caplog.text.count("F7v2: silence threshold not reached") == 2

    @pytest.mark.asyncio
    async def test_race_repeat_within_cooldown_suppressed(self, make_message):
        """A second burst within the 10s cooldown → 0 greetings."""
        db = _FakeSilenceDB()
        db.ts[-100] = self.NOW - 7.0 * 3600
        setup_alan(db)

        sends = []
        slow_send = self._make_slow_send(sends)

        with patch("handlers.alan.time.time", return_value=self.NOW), \
             patch("handlers.alan._send_greeting", side_effect=slow_send) as mock_send:
            batch1 = self._make_batch(make_message, -100, 3)
            await asyncio.gather(*(alan_handler(m) for m in batch1))
            assert mock_send.call_count == 1

            batch2 = self._make_batch(make_message, -100, 3)
            await asyncio.gather(*(alan_handler(m) for m in batch2))

        assert mock_send.call_count == 1
        assert _last_greeting[-100] == self.NOW

    @pytest.mark.asyncio
    async def test_race_after_cooldown_expiry_sends_once(self, make_message):
        """Cooldown expired (15s ago) + stale ts → burst produces exactly 1 greeting."""
        db = _FakeSilenceDB()
        db.ts[-100] = self.NOW - 7.0 * 3600
        setup_alan(db)

        _last_greeting[-100] = self.NOW - 15

        sends = []
        slow_send = self._make_slow_send(sends)

        with patch("handlers.alan.time.time", return_value=self.NOW), \
             patch("handlers.alan._send_greeting", side_effect=slow_send) as mock_send:
            msgs = self._make_batch(make_message, -100, 3)
            await asyncio.gather(*(alan_handler(m) for m in msgs))

        assert mock_send.call_count == 1

    @pytest.mark.asyncio
    async def test_ts_claimed_before_send(self, make_message):
        """ts must be written to the DB BEFORE `await _send_greeting()` (claim-before-send)."""
        db = _FakeSilenceDB()
        db.ts[-100] = self.NOW - 7.0 * 3600
        setup_alan(db)

        observed = {}

        async def check_send(bot, chat_id):
            observed["db_ts"] = db.ts.get(chat_id)
            observed["claimed"] = chat_id in _last_greeting
            await asyncio.sleep(0.05)
            return True

        msg = make_message(138811255, text="wake", chat_id=-100)
        msg.bot = AsyncMock()

        with patch("handlers.alan.time.time", return_value=self.NOW), \
             patch("handlers.alan._send_greeting", side_effect=check_send):
            await alan_handler(msg)

        assert observed["db_ts"] == self.NOW
        assert observed["claimed"] is True

    @pytest.mark.asyncio
    async def test_restart_simulation_single_greeting(self, make_message):
        """After a restart (in-memory state empty, stale ts in DB) → 1 greeting, then cooldown."""
        db = _FakeSilenceDB()
        db.ts[-100] = self.NOW - 7.0 * 3600
        setup_alan(db)

        assert _last_greeting == {}
        assert _greeting_locks == {}

        sends = []
        slow_send = self._make_slow_send(sends)

        with patch("handlers.alan.time.time", return_value=self.NOW), \
             patch("handlers.alan._send_greeting", side_effect=slow_send) as mock_send:
            msg = make_message(138811255, text="back after silence", chat_id=-100)
            msg.bot = AsyncMock()
            await alan_handler(msg)
            assert mock_send.call_count == 1

            msg2 = make_message(138811255, text="immediate repeat", chat_id=-100)
            msg2.bot = AsyncMock()
            await alan_handler(msg2)

        assert mock_send.call_count == 1

    @pytest.mark.asyncio
    async def test_per_chat_lock_isolation(self, make_message):
        """Parallel bursts in two chats → 1 greeting per chat (2 total), locks don't collide."""
        db = _FakeSilenceDB()
        db.ts[-100] = self.NOW - 7.0 * 3600
        db.ts[-200] = self.NOW - 7.0 * 3600
        setup_alan(db)

        sends = []
        slow_send = self._make_slow_send(sends)

        with patch("handlers.alan.time.time", return_value=self.NOW), \
             patch("handlers.alan._send_greeting", side_effect=slow_send) as mock_send:
            msgs = self._make_batch(make_message, -100, 3) + self._make_batch(make_message, -200, 3)
            await asyncio.gather(*(alan_handler(m) for m in msgs))

        assert mock_send.call_count == 2
        sent_chats = {call.args[1] for call in mock_send.call_args_list}
        assert sent_chats == {-100, -200}

    @pytest.mark.asyncio
    async def test_race_send_failure_rolls_back_claim(self, make_message):
        """Send failure in a burst → claim rolled back (_last_greeting empty), 1 ts write per call."""
        db = _FakeSilenceDB()
        db.ts[-100] = self.NOW - 7.0 * 3600
        setup_alan(db)

        sends = []

        async def fail_send(bot, chat_id):
            await asyncio.sleep(0.05)
            sends.append((bot, chat_id))
            return False

        with patch("handlers.alan.time.time", return_value=self.NOW), \
             patch("handlers.alan._send_greeting", side_effect=fail_send) as mock_send:
            msgs = self._make_batch(make_message, -100, 3)
            await asyncio.gather(*(alan_handler(m) for m in msgs))

        assert mock_send.call_count == 1
        assert _last_greeting == {}
        assert db.set_count == 3
        assert db.ts[-100] == self.NOW


class TestAlanHandlerPropagation:
    """Test that alan_handler returns UNHANDLED for propagation."""

    @pytest.mark.asyncio
    async def test_alan_handler_returns_unhandled(self, make_message):
        """alan_handler must return UNHANDLED so propagation continues."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = None
        setup_alan(mock_db)

        with patch("handlers.alan._send_greeting", return_value=True):
            with patch("handlers.alan._last_greeting", {}):
                with patch("handlers.alan.settings") as mock_settings:
                    mock_settings.ALAN_SILENCE_GREETING_HOURS = 6.0
                    mock_settings.ALAN_REPLY_INTERVAL = 10
                    mock_settings.ALAN_GREETING_COOLDOWN = 10
                    msg = make_message(138811255, text="test propagation")
                    result = await alan_handler(msg)

        assert result is UNHANDLED, f"Expected UNHANDLED, got {result}"
