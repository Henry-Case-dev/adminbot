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

import pytest

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
from services.outgoing_guard import sanitize_outgoing
from services.target_marking import (
    TARGET_INSTRUCTION_BLOCK,
    TARGET_MARKER,
    TARGET_MARKER_CORE,
    append_marker,
    is_target_item_id,
    is_target_row,
    normalize_trigger_id,
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
        assert is_target_row(_row(tg_message_id=100), 0) is False
        assert is_target_row({}, 100) is False

    def test_normalize_trigger_id(self):
        assert normalize_trigger_id(None) is None
        assert normalize_trigger_id("") is None
        assert normalize_trigger_id(0) is None
        assert normalize_trigger_id("bad") is None
        assert normalize_trigger_id("42") == 42
        assert normalize_trigger_id(42) == 42

    def test_is_target_item_id_unified_guard(self):
        """R1023F1-06: тот же guard/нормализация, что у is_target_row."""
        assert is_target_item_id("tg:100", 100) is True
        assert is_target_item_id("tg:100", "100") is True
        assert is_target_item_id("tg:99", 100) is False
        assert is_target_item_id("tg:100", None) is False
        assert is_target_item_id("tg:100", 0) is False
        assert is_target_item_id("msg:100", 100) is False
        assert is_target_item_id("tg:bad", 100) is False

    def test_append_marker_no_duplicates(self):
        assert append_marker("текст") == "текст " + TARGET_MARKER
        assert append_marker("") == TARGET_MARKER
        marked = "текст " + TARGET_MARKER
        assert append_marker(marked) == marked

    def test_append_marker_dedup_by_core(self):
        """R1023F1-05: тело, уже содержащее ядро (без `<<<`), не дублируется."""
        body_with_core = "текст " + TARGET_MARKER_CORE
        assert append_marker(body_with_core) == body_with_core

    def test_append_marker_whitespace_body_is_empty(self):
        """R1023F1-05: пробельное тело — как пустое."""
        assert append_marker("   ") == TARGET_MARKER
        assert append_marker("\n\t") == TARGET_MARKER


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

class TestEgressScrub:
    """R1023F1-03: egress-guard вырезает технический маркер (defense-in-depth
    к промпт-правилу; scrubber режет только технические токены)."""

    def test_full_marker_scrubbed(self):
        out = sanitize_outgoing("привет <<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]")
        assert TARGET_MARKER_CORE not in out
        assert "<<" not in out
        assert out == "привет"

    def test_core_only_scrubbed(self):
        assert sanitize_outgoing("[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА] текст") == "текст"

    def test_marker_in_middle_single_separator(self):
        out = sanitize_outgoing("до <<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА] после")
        assert out == "до после"
        assert "  " not in out

    def test_noop_without_marker_byte_for_byte(self):
        text = "обычный ответ без служебных токенов и цифр"
        assert sanitize_outgoing(text) == text

    def test_idempotent(self):
        once = sanitize_outgoing("x <<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА] y")
        assert sanitize_outgoing(once) == once

    def test_stage1_echo_does_not_reach_user(self):
        """Граница Stage-1 → отправка: если Синтезатор проэхоил маркер в
        выжимку/финал, egress его вырезает до показа пользователю."""
        stage2_output = ("вася спорил с петей про футбол "
                         "<<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]")
        outgoing = sanitize_outgoing(stage2_output)
        assert TARGET_MARKER_CORE not in outgoing
        assert TARGET_MARKER not in outgoing
        assert "вася спорил с петей про футбол" in outgoing


class TestDirectChatWiring:
    """R1023F1-02 + R1023F1-01: покрытие проводки T-2100 в прямом чате
    (`_context_row_line`/`_chain_line`/`_render_thread`/`_render_branch`/
    `_build_user_content`) и «суммарно ровно один маркер»."""

    def test_context_row_line_marks_target_and_legacy(self):
        from tests.test_direct_chat import _make_service
        svc = _make_service()
        row = {"user_id": 10, "author_name": "вася", "text": "привет",
               "timestamp": 1_700_000_000, "tg_message_id": 5, "id": 9}
        marked = svc._context_row_line(row, {}, trigger_message_id=5)
        assert TARGET_MARKER in marked
        legacy = svc._context_row_line(row, {})
        assert TARGET_MARKER not in legacy
        assert legacy == svc._context_row_line(row, {}, trigger_message_id=None)
        assert svc._context_row_line(row, {}, trigger_message_id=777) == legacy

    def test_chain_line_marks_target_and_unified_guard(self):
        from services.direct_chat_service import _ChainItem
        from tests.test_direct_chat import _make_service
        svc = _make_service()
        item = _ChainItem(10, "вася", "привет", False, 1_700_000_000,
                          "tg:5", None)
        assert TARGET_MARKER in svc._chain_line(item, {}, trigger_message_id=5)
        assert TARGET_MARKER not in svc._chain_line(item, {})
        assert TARGET_MARKER not in svc._chain_line(
            item, {}, trigger_message_id=999)
        # R1023F1-06: id=0 трактуется как отсутствие триггера (единый guard)
        assert TARGET_MARKER not in svc._chain_line(
            item, {}, trigger_message_id=0)

    def test_render_thread_and_branch_mark_target(self):
        from services.direct_chat_service import _ChainItem
        from tests.test_direct_chat import _make_service
        svc = _make_service()
        chain = [
            _ChainItem(10, "вася", "текущий", False, 1_700_000_000,
                       "tg:5", None),
            _ChainItem(None, "test_bot", "ответ", True, None, "tg:6", None),
        ]
        # В XML-подобных блоках direct чата маркер экранируется (`&lt;&lt;&lt;`),
        # поэтому считаем escape-стабильное ядро.
        thread = svc._render_thread(chain, {}, trigger_message_id=5)
        assert thread.count(TARGET_MARKER_CORE) == 1
        assert "&lt;&lt;&lt;" in thread
        assert TARGET_MARKER_CORE not in svc._render_thread(chain, {})
        branch = svc._render_branch(chain, {}, trigger_message_id=5)
        assert branch.count(TARGET_MARKER_CORE) == 1
        assert TARGET_MARKER_CORE not in svc._render_branch(chain, {})

    @pytest.mark.asyncio
    async def test_build_user_content_single_marker_ordinary(self):
        """Обычное сообщение: суммарно ровно один маркер (в <Global_Context>)."""
        from tests.test_direct_chat import FakeMemory, _make_service, _message
        row = {"user_id": 10, "author_name": "вася",
               "text": "текущая команда", "timestamp": 1_700_000_000,
               "media_type": "text", "reply_to_id": None, "tg_message_id": 100}
        svc = _make_service(memory=FakeMemory(window=[row]))
        blocks = await svc._build_user_content(-100, _message(message_id=100),
                                               "вася")
        joined = "\n".join(blocks)
        # В direct-блоках маркер экранируется (`&lt;&lt;&lt;`) — считаем ядро.
        assert joined.count(TARGET_MARKER_CORE) == 1
        assert joined.count("<<<") + joined.count("&lt;&lt;&lt;") == 1

    @pytest.mark.asyncio
    async def test_build_user_content_single_marker_reply(self):
        """Reply-сообщение: маркер один (branch/thread не дублируют)."""
        from tests.test_direct_chat import (
            FakeDB, FakeMemory, _make_service, _message, _thread_row)
        current = {"user_id": 10, "author_name": "вася",
                   "text": "текущая команда", "timestamp": 1_700_000_000,
                   "media_type": "text", "reply_to_id": 50,
                   "tg_message_id": 100}
        parent = _thread_row(50, text="родитель")
        svc = _make_service(
            memory=FakeMemory(window=[parent, current]),
            db=FakeDB(rows={100: current, 50: parent}))
        msg = _message(message_id=100)
        msg.reply_to_message = object()          # reply-триггер
        blocks = await svc._build_user_content(-100, msg, "вася")
        joined = "\n".join(blocks)
        assert joined.count(TARGET_MARKER_CORE) == 1
        assert joined.count("<<<") + joined.count("&lt;&lt;&lt;") == 1

    @pytest.mark.asyncio
    async def test_build_user_content_no_trigger_no_marker(self):
        from tests.test_direct_chat import FakeMemory, _make_service, _message
        row = {"user_id": 10, "author_name": "вася", "text": "текущая команда",
               "timestamp": 1_700_000_000, "media_type": "text",
               "reply_to_id": None, "tg_message_id": 100}
        svc = _make_service(memory=FakeMemory(window=[row]))
        blocks = await svc._build_user_content(-100, _message(message_id=777),
                                               "вася")
        assert TARGET_MARKER_CORE not in "\n".join(blocks)
