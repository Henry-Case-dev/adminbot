"""Tests for Epic 72 (74.C, T-556): гейт direct_chat на расшифровках.

Реплай на сообщение бота-расшифровку («Имя 🗣: текст») НЕ триггерит 0h;
реплай на обычный ответ бота и остальные ветки (mention/keyword) — как раньше.
"""
from unittest.mock import MagicMock

import pytest

from handlers import direct_chat as dc
from handlers import voice_transcription as vt

CHAT_ID = -1001234567890
BOT_ID = 999
USER_ID = 111


@pytest.fixture
def gate_env():
    """DI обоих хендлеров с восстановлением глобалов."""
    old_dc = (dc._service, dc._bot_id, dc._bot_username)
    dc.setup_direct_chat(service=MagicMock(), bot_id=BOT_ID,
                         bot_username="adminbot")
    old_vt = (vt._service, vt._db, vt._aliases, vt._memory, vt._bot_id)
    vt.setup_voice_transcription(service=MagicMock(), db=None, aliases=None,
                                 memory=None, bot_id=BOT_ID)
    yield
    dc._service, dc._bot_id, dc._bot_username = old_dc
    vt._service, vt._db, vt._aliases, vt._memory, vt._bot_id = old_vt


def _msg(text="спасибо", reply_to=None):
    m = MagicMock()
    m.text = text
    m.caption = None
    m.message_id = 10
    m.chat = MagicMock()
    m.chat.id = CHAT_ID
    m.from_user = MagicMock()
    m.from_user.id = USER_ID
    m.reply_to_message = reply_to
    m.entities = None
    return m


def _bot_target(text="Вася 🗣: привет"):
    t = MagicMock()
    t.text = text
    t.from_user = MagicMock()
    t.from_user.id = BOT_ID
    t.reply_to_message = None
    t.voice = None
    t.video_note = None
    return t


class TestDirectChatTranscriptionGate:
    def test_reply_on_transcription_is_not_trigger(self, gate_env):
        assert dc._is_direct_trigger(_msg(reply_to=_bot_target())) is False

    def test_reply_on_regular_bot_message_triggers(self, gate_env):
        assert dc._is_direct_trigger(
            _msg(reply_to=_bot_target("обычный ответ бота"))) is True

    def test_mention_branch_unaffected(self, gate_env):
        assert dc._is_direct_trigger(_msg(text="@adminbot привет")) is True

    def test_keyword_branch_unaffected(self, gate_env):
        assert dc._is_direct_trigger(_msg(text="эй, бот")) is True

    def test_reply_on_other_user_not_a_trigger(self, gate_env):
        other = _bot_target()
        other.from_user.id = 555          # не бот → гейт вообще не применяется
        assert dc._is_direct_trigger(_msg(reply_to=other)) is False

    def test_gate_uses_structural_fallback_too(self, gate_env):
        orig = MagicMock()
        orig.voice = MagicMock()
        orig.video_note = None
        target = _bot_target("")
        target.text = ""
        target.reply_to_message = orig
        assert dc._is_direct_trigger(_msg(reply_to=target)) is False
