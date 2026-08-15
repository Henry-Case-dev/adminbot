"""Tests for services/summary_xml.py (T-180, R6)."""
from dataclasses import replace

import pytest

from config.settings import settings
from services.summary_aliases import AliasResolver
from services.summary_xml import XmlGroundingBuilder


def _row(**kwargs):
    defaults = {
        "id": 1,
        "user_id": 10,
        "timestamp": 1_700_000_000,
        "author_name": "вася",
        "text": "привет",
        "reply_to_id": None,
        "media_type": "text",
    }
    defaults.update(kwargs)
    return defaults


class TestXmlStructure:
    def test_empty_messages(self):
        assert XmlGroundingBuilder().build([]) == "<chat_history/>"

    def test_single_message(self):
        xml = XmlGroundingBuilder().build([_row()])
        assert xml.startswith("<chat_history>\n")
        assert xml.endswith("\n</chat_history>")
        assert '<message id="1"' in xml
        assert 'author="вася"' in xml
        assert 'type="text"' in xml
        assert 'reply_to_id=""' in xml
        assert "timestamp=" in xml
        assert ">привет</message>" in xml

    def test_reply_to_id_rendered(self):
        xml = XmlGroundingBuilder().build([_row(reply_to_id=42)])
        assert 'reply_to_id="42"' in xml

    def test_timestamp_iso8601(self):
        xml = XmlGroundingBuilder().build([_row()])
        # 1700000000 = 2023-11-14T22:13:20+00:00
        assert 'timestamp="2023-11-14T22:13:20+00:00"' in xml


class TestEscaping:
    def test_special_chars_escaped(self):
        xml = XmlGroundingBuilder().build([_row(text="a < b & c > d")])
        assert "a &lt; b &amp; c &gt; d" in xml

    def test_author_quote_escaped(self):
        xml = XmlGroundingBuilder().build([_row(author_name='вася "цитата"')])
        assert 'author="вася &quot;цитата&quot;"' in xml

    def test_control_chars_stripped(self):
        xml = XmlGroundingBuilder().build([_row(text="норм\x00\x08\x1fконец")])
        assert "\x00" not in xml
        assert "нормконец" in xml


class TestMediaDescriptions:
    @pytest.mark.parametrize(
        "media_type,description",
        [
            ("photo", "[фото]"),
            ("video", "[видео]"),
            ("voice", "[голосовое]"),
            ("audio", "[аудио]"),
            ("animation", "[гифка]"),
            ("sticker", "[стикер]"),
            ("document", "[файл]"),
            ("other", "[медиа]"),
        ],
    )
    def test_media_description(self, media_type, description):
        xml = XmlGroundingBuilder().build([_row(text=None, media_type=media_type)])
        assert f">{description}</message>" in xml

    def test_media_with_caption(self):
        xml = XmlGroundingBuilder().build(
            [_row(text="глянь сюда", media_type="photo")]
        )
        assert ">глянь сюда [фото]</message>" in xml

    def test_unknown_media_type(self):
        xml = XmlGroundingBuilder().build([_row(text=None, media_type="contact")])
        assert ">[медиа]</message>" in xml


class TestLimits:
    def test_max_messages_cap(self):
        rows = [_row(id=i) for i in range(10)]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("services.summary_xml.settings", replace(settings, SUMMARY_MAX_WINDOW_MESSAGES=3))
            xml = XmlGroundingBuilder().build(rows)
        assert xml.count("<message ") == 3

    def test_max_message_chars_cap(self):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("services.summary_xml.settings", replace(settings, SUMMARY_MAX_MESSAGE_CHARS=5))
            xml = XmlGroundingBuilder().build([_row(text="очень длинный текст")])
        assert ">очень</message>" in xml

    def test_total_context_hard_cap(self):
        rows = [_row(id=i, text="слово " * 500) for i in range(50)]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("services.summary_xml.settings", replace(settings, SUMMARY_MAX_CONTEXT_CHARS=1000))
            xml = XmlGroundingBuilder().build(rows)
        assert xml.endswith("</chat_history>")
        assert xml.count("<message ") < 50


class TestAuthorFallback:
    def test_empty_author_uses_alias_resolver(self):
        resolver = AliasResolver('{"10": "главный"}')
        xml = XmlGroundingBuilder().build([_row(author_name="")], aliases=resolver)
        assert 'author="главный"' in xml

    def test_empty_author_no_resolver(self):
        xml = XmlGroundingBuilder().build([_row(author_name="")])
        assert 'author=""' in xml
