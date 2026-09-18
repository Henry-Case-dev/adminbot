"""F1 `target-message-marking-round1023` (ADR-1023-1) — маркировка цели.

Покрытие:
* единый токен + matcher по Telegram ``tg_message_id``;
* XML-рендер (`summary_xml`): маркер ровно на одном сообщении, до экранирования
  (`&lt;&lt;&lt;`), well-formed XML, дубль id → первое;
* plain-рендер (`canonical_context`/`chat_context`): сырой ``<<<``, только msg;
* паритет обоих рендереров по escape-стабильному ядру;
* legacy: нет триггера/нет совпадения → вывод байт-в-байт прежний;
* таймлайн не изменён (триггер присутствует, порядок сохранён);
* промпт-правило в трёх Stage-1 Синтезаторах; антиэхо (Вербализаторы без
  маркера; финальный текст без артефактов).
"""
import xml.etree.ElementTree as ET

from services import canonical_context as cc
from services.canonical_context import format_context_item
from services.chat_context import format_chat_context
from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    DIRECT_VERBALIZER_SYSTEM_PROMPT,
)
from services.factcheck_prompts import (
    FACTCHECK_ANALYST_SYSTEM_PROMPT,
    FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
)
from services.summary_prompts import (
    SUMMARY_EDITOR_SYSTEM_PROMPT,
    SUMMARY_NARRATOR_SYSTEM_PROMPT,
)
from services.summary_xml import XmlGroundingBuilder
from services.target_marking import (
    TARGET_INSTRUCTION_BLOCK,
    TARGET_MARKER,
    TARGET_MARKER_CORE,
    append_marker,
    is_target_row,
)


def _row(**kwargs):
    data = {
        "id": 1,
        "user_id": 10,
        "timestamp": 1_700_000_000,
        "author_name": "вася",
        "text": "привет",
        "reply_to_id": None,
        "media_type": "text",
        "tg_message_id": 100,
    }
    data.update(kwargs)
    return data


def _chat_row(**kwargs):
    data = {
        "user_id": 10, "author_name": "вася", "text": "привет",
        "timestamp": 1_700_000_000, "tg_message_id": 5, "id": 9,
    }
    data.update(kwargs)
    return data


class TestTokenAndMatcher:
    def test_marker_and_core_forms(self):
        assert TARGET_MARKER == "<<< " + TARGET_MARKER_CORE
        assert TARGET_MARKER_CORE == "[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]"

    def test_core_is_escape_stable(self):
        """Ядро без ``<`` → одинаково в XML и plain (паритет-якорь)."""
        assert "<" not in TARGET_MARKER_CORE
        assert "&" not in TARGET_MARKER_CORE

    def test_is_target_row_by_tg_id(self):
        assert is_target_row(_row(tg_message_id=100), 100) is True
        assert is_target_row(_row(tg_message_id=99), 100) is False
        assert is_target_row(_row(tg_message_id=100), None) is False
        assert is_target_row(_row(tg_message_id=None), 100) is False
        assert is_target_row(_row(tg_message_id="bad"), 100) is False
        assert is_target_row({}, 100) is False

    def test_append_marker_no_duplicates(self):
        assert append_marker("текст") == "текст " + TARGET_MARKER
        assert append_marker("") == TARGET_MARKER
        marked = "текст " + TARGET_MARKER
        assert append_marker(marked) == marked


class TestXmlRenderer:
    def test_marker_on_exactly_one_message(self):
        rows = [_row(id=1, tg_message_id=10, text="старое"),
                _row(id=2, tg_message_id=20, text="моя команда"),
                _row(id=3, tg_message_id=30, text="позже")]
        xml = XmlGroundingBuilder().build(rows, trigger_message_id=20)
        assert xml.count("&lt;&lt;&lt;") == 1
        assert TARGET_MARKER_CORE in xml
        assert "моя команда" in xml
        # таймлайн не изменён: порядок и состав сохранены, цель не вырезана
        assert xml.index("старое") < xml.index("моя команда") < xml.index("позже")
        assert xml.count("<message ") == 3

    def test_marker_inserted_before_escape_keeps_valid_xml(self):
        xml = XmlGroundingBuilder().build([_row(tg_message_id=5)],
                                          trigger_message_id=5)
        ET.fromstring(xml)                      # well-formed XML
        assert "&lt;&lt;&lt; " + TARGET_MARKER_CORE + "</message>" in xml

    def test_legacy_none_byte_for_byte(self):
        rows = [_row(id=1, tg_message_id=10, text="a")]
        assert (XmlGroundingBuilder().build(rows, None, None)
                == XmlGroundingBuilder().build(rows))

    def test_no_match_legacy_byte_for_byte(self):
        rows = [_row(id=1, tg_message_id=10, text="a")]
        assert (XmlGroundingBuilder().build(rows, None, 999)
                == XmlGroundingBuilder().build(rows))

    def test_duplicate_tg_marks_first_only(self):
        rows = [_row(id=1, tg_message_id=20, text="первое"),
                _row(id=2, tg_message_id=20, text="второе")]
        xml = XmlGroundingBuilder().build(rows, trigger_message_id=20)
        assert xml.count("&lt;&lt;&lt;") == 1
        first = [ln for ln in xml.splitlines() if "первое" in ln][0]
        assert TARGET_MARKER_CORE in first


class TestPlainRenderer:
    def test_format_context_item_is_target_raw_marker(self):
        line = format_context_item(
            ts=1_700_000_000, author="вася", item_id="tg:5", text="привет",
            is_target=True)
        assert line.endswith("привет " + TARGET_MARKER)
        assert "&lt;" not in line                # plain: сырой <<<

    def test_is_target_only_for_msg(self):
        fact = format_context_item(text="факт", kind="fact", is_target=True)
        archive = format_context_item(text="арх", kind="archive",
                                      is_target=True)
        assert TARGET_MARKER not in fact
        assert TARGET_MARKER not in archive

    def test_default_false_is_legacy(self):
        assert (format_context_item(text="x")
                == format_context_item(text="x", is_target=False))

    def test_parity_of_both_renderers(self):
        xml = XmlGroundingBuilder().build([_row(tg_message_id=5, text="x")],
                                          trigger_message_id=5)
        plain = format_context_item(text="x", is_target=True)
        assert TARGET_MARKER_CORE in xml and TARGET_MARKER_CORE in plain
        assert "&lt;&lt;&lt;" in xml
        assert "<<<" in plain


class TestChatContext:
    def test_marks_target_and_legacy_default(self):
        rows = [_chat_row(tg_message_id=5, text="команда")]
        marked = format_chat_context(rows, trigger_message_id=5)
        assert TARGET_MARKER in marked
        legacy = format_chat_context(rows)
        assert TARGET_MARKER not in legacy
        assert legacy == format_chat_context(rows, trigger_message_id=None)

    def test_chat_context_no_match_legacy(self):
        rows = [_chat_row(tg_message_id=5, text="команда")]
        assert (format_chat_context(rows, trigger_message_id=777)
                == format_chat_context(rows))

    def test_chat_context_duplicate_marks_first_only(self):
        rows = [_chat_row(tg_message_id=5, id=1, text="a"),
                _chat_row(tg_message_id=5, id=2, text="b")]
        out = format_chat_context(rows, trigger_message_id=5)
        assert out.count(TARGET_MARKER) == 1


class TestPromptsAndAntiEcho:
    def test_rule_present_in_three_stage1(self):
        for prompt in (SUMMARY_EDITOR_SYSTEM_PROMPT,
                       FACTCHECK_ANALYST_SYSTEM_PROMPT,
                       CHAT_SYSTEM_PROMPT):
            assert TARGET_INSTRUCTION_BLOCK in prompt
            assert TARGET_MARKER_CORE in prompt

    def test_verbalizers_never_see_marker(self):
        """Антиэхо: Вербализаторы (Stage-2) истории не видят и маркер не
        содержат — он не может протечь в финальный текст из промпта."""
        for prompt in (SUMMARY_NARRATOR_SYSTEM_PROMPT,
                       FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
                       DIRECT_VERBALIZER_SYSTEM_PROMPT):
            assert TARGET_MARKER_CORE not in prompt
            assert "<<<" not in prompt

    def test_final_text_has_no_marker_artifacts(self):
        """Симуляция финального пользовательского текста: маркер не должен
        появляться (правило промпта + изоляция Вербализатора)."""
        final = "вася спорил с петей про футбол и обосрался с прогнозом"
        assert TARGET_MARKER not in final
        assert TARGET_MARKER_CORE not in final
        assert cc.ARCHIVE_MARKER not in final
