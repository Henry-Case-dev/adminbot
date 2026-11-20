"""P0-HC C2 — Telegram egress call-site в обычном Direct.

Контракт: ``plans/features/p0-history-coverage-temporal-egress/
arch-contract-2026-11-21.md`` §4.2/§5, row ``HC-EGRESS-STRUCTURED``.

Проверяется фактический Bot API payload (fake bot записывает ``parse_mode``,
``entities``, тексты чанков и reply-таргет), а не внутренние DTO:
  * casual без escape → прежний plain-путь байт-в-байт;
  * буквальные escape-маркеры (`\\*`) → plain без служебного backslash
    (P0-ACCEPT F2: тот же закрытый C1 `render_plain`, один вызов);
  * структурный Markdown → ``send_structured`` (HTML), без сырых маркеров;
  * long answer → тег-безопасные чанки по UTF-16, reply только у первого;
  * частичный сбой → plain ТОЛЬКО сбойного чанка, без повторов и LLM;
  * ``document``-источник и первый ``message_id`` для downstream ledger;
  * rich/lore/deep_research и ``/summary``-путь не меняются.
"""
from __future__ import annotations

import inspect
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

import services.direct_chat_service as dcs
from services import telegram_markup as tm
from services import turn_trace
from services.direct_chat_service import DirectChatService
from services.response_document import document_from_answer
from services.smartmodule_utils import _CHUNK_LIMIT, send_chunked_reply

pytestmark = pytest.mark.system2

CHAT_ID = -100777


class FakeBot:
    """Fake Bot API: записывает реальный payload и умеет падать по индексу."""

    def __init__(self, *, fail_html: set[int] | None = None,
                 fail_plain: set[int] | None = None,
                 retry_after_once: bool = False):
        self.calls: list[dict] = []
        self.rich_calls: list[dict] = []
        self._fail_html = fail_html or set()
        self._fail_plain = fail_plain or set()
        self._retry_after_once = retry_after_once
        self._message_id = 1000

    async def send_message(self, chat_id, text, **kwargs):
        index = len(self.calls)
        self.calls.append({"chat_id": chat_id, "text": text, **kwargs})
        if (self._retry_after_once and index == 0
                and kwargs.get("parse_mode") == "HTML"):
            raise TelegramRetryAfter(
                method=MagicMock(), message="flood", retry_after=0)
        if kwargs.get("parse_mode") == "HTML" and index in self._fail_html:
            raise TelegramBadRequest(
                method=MagicMock(), message="can't parse entities")
        if "parse_mode" not in kwargs and index in self._fail_plain:
            raise TelegramBadRequest(
                method=MagicMock(), message="plain failed")
        self._message_id += 1
        self.calls[-1]["message_id"] = self._message_id
        return SimpleNamespace(message_id=self._message_id)

    async def send_rich_message(self, chat_id, rich, **kwargs):
        self.rich_calls.append({"chat_id": chat_id, "rich": rich, **kwargs})
        self._message_id += 1
        return SimpleNamespace(message_id=self._message_id)


class FakeDocument:
    """Минимальный ResponseDocument-контракт: plain_text() и rich_text()."""

    def __init__(self, text: str):
        self._text = text

    def plain_text(self) -> str:
        return self._text

    def rich_text(self) -> str:
        return self._text


@pytest.fixture(autouse=True)
def _no_chunk_delay(monkeypatch):
    """Тестовая пауза 0; боевой hot-ключ/default не меняются."""
    monkeypatch.setattr(
        tm.hot, "get",
        lambda key, default=None:
        (0.0 if key == "limits.summary_chunk_delay" else default))


def _send(bot, text, *, reply_to=42, document=None, **kwargs):
    return DirectChatService._send_direct_answer(
        bot, CHAT_ID, text, reply_to, document=document, **kwargs)


def _html_calls(bot):
    return [call for call in bot.calls if call.get("parse_mode") == "HTML"]


def _plain_calls(bot):
    return [call for call in bot.calls if "parse_mode" not in call]


# ── выбор канала в обычном Direct ─────────────────────────────────────────

class TestOrdinaryDirectChannelChoice:
    @pytest.mark.asyncio
    async def test_casual_uses_existing_plain_chunked_path_byte_identical(
            self, monkeypatch):
        sent = []

        async def fake_chunked(bot, chat_id, text, reply_to=None, **kw):
            sent.append({"chat_id": chat_id, "text": text,
                         "reply_to": reply_to, "kwargs": kw})
            return 321

        structured = AsyncMock()
        monkeypatch.setattr(dcs, "send_chunked_reply", fake_chunked)
        monkeypatch.setattr(tm, "send_structured", structured)
        answer = "Привет. Просто болтаем про вчерашний вечер."

        result = await _send(FakeBot(), answer)

        assert result == 321
        assert structured.await_count == 0
        assert sent == [{"chat_id": CHAT_ID, "text": answer,
                         "reply_to": 42, "kwargs": {}}]

    @pytest.mark.asyncio
    async def test_markdown_answer_uses_structured_html(self):
        bot = FakeBot()
        answer = "**Итог**\n\n- первый\n- второй"

        result = await _send(bot, answer)

        assert result == 1001
        assert len(bot.calls) == 1
        call = bot.calls[0]
        assert call["parse_mode"] == "HTML"
        assert call["text"].startswith("<b>Итог</b>")
        assert "• первый" in call["text"] and "• второй" in call["text"]
        assert "**" not in call["text"]
        assert "entities" not in call          # канал — parse_mode, не entities
        assert call["reply_to_message_id"] == 42

    @pytest.mark.asyncio
    async def test_literal_stars_and_plain_code_word_stay_plain(self):
        bot = FakeBot()
        answer = "2 * 3 * 4 = 24, snake_case_name и слово report"

        result = await _send(bot, answer)

        assert result == 1001
        assert len(bot.calls) == 1
        assert "parse_mode" not in bot.calls[0]
        assert bot.calls[0]["text"] == answer
        assert bot.calls[0]["reply_to_message_id"] == 42

    @pytest.mark.asyncio
    async def test_escaped_stars_are_not_forced_into_html(self):
        bot = FakeBot()
        answer = r"2 \* 3 = 6 и \*\*буквально\*\*"

        await _send(bot, answer)

        assert len(bot.calls) == 1
        assert "parse_mode" not in bot.calls[0]
        # P0-ACCEPT F2: канал остаётся plain, но служебный backslash-escape
        # снимается закрытым C1-рендером: получатель видит `*`, а не `\*`;
        # `**буквально**` остаётся текстом (не HTML <b>).
        assert len(answer) == 30
        assert bot.calls[0]["text"] == "2 * 3 = 6 и **буквально**"
        assert len(bot.calls[0]["text"]) == 25
        assert answer.count("\\") == 5      # пять служебных escape-слэшей
        assert len(answer) - len(bot.calls[0]["text"]) == answer.count("\\")
        assert "\\" not in bot.calls[0]["text"]
        assert bot.calls[0]["reply_to_message_id"] == 42

    @pytest.mark.asyncio
    async def test_escaped_literal_markers_plain_without_backslashes(self):
        """F2: расчётный пример `2 * 2` и literal-markers — plain, один вызов."""
        bot = FakeBot()
        answer = r"2 * 2 = 4; \*не текст\*; snake_case"

        await _send(bot, answer)

        assert len(bot.calls) == 1
        assert "parse_mode" not in bot.calls[0]
        assert len(answer) == 35
        assert bot.calls[0]["text"] == "2 * 2 = 4; *не текст*; snake_case"
        assert len(bot.calls[0]["text"]) == 33
        assert len(answer) - len(bot.calls[0]["text"]) == answer.count("\\")
        assert "\\" not in bot.calls[0]["text"]
        assert bot.calls[0]["reply_to_message_id"] == 42

    @pytest.mark.asyncio
    async def test_html_specials_and_link_are_escaped_not_raw(self):
        bot = FakeBot()
        answer = ("**Итог** <b> & [сайт](https://example.com/?a=1&b=2)")

        await _send(bot, answer)

        payload = bot.calls[0]["text"]
        assert bot.calls[0]["parse_mode"] == "HTML"
        assert "&lt;b&gt;" in payload and "&amp;" in payload
        assert "<b> &" not in payload
        assert re.search(r"<a href=\"https://example\.com/\?a=1&amp;b=2\">",
                         payload)
        assert "**" not in payload

    @pytest.mark.asyncio
    async def test_document_plain_text_is_the_delivery_source_and_id_returned(
            self):
        bot = FakeBot()
        doc = FakeDocument("**из документа**")

        result = await _send(bot, "игнорируется", document=doc)

        assert result == 1001
        assert len(bot.calls) == 1
        assert bot.calls[0]["text"] == "<b>из документа</b>"
        assert bot.calls[0]["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_plain_document_keeps_exact_plain_text(self):
        bot = FakeBot()
        doc = FakeDocument("обычный текст без разметки")

        await _send(bot, "не используется", document=doc)

        assert len(bot.calls) == 1
        assert "parse_mode" not in bot.calls[0]
        assert bot.calls[0]["text"] == doc.plain_text()

    @pytest.mark.asyncio
    async def test_egress_guard_markers_are_never_delivered_visible(self):
        """C1 санитизирует источник ДО разбора: разметка не «оживляет» теги.

        Digest трассы обязан совпасть с фактическим Bot API payload: иначе
        наблюдаемость показывала бы escaped `<thought>`, которого нет у чата.
        """
        cid = "c2-trace-guard"
        turn_trace.begin(cid, chat_id=CHAT_ID, trigger="test")
        try:
            bot = FakeBot()
            answer = "**Итог**\n\n<thought>скрытая цепочка</thought>"

            result = await _send(bot, answer, correlation_id=cid)

            trace = turn_trace.get(cid)
            payload = bot.calls[0]["text"]
            assert result == 1001
            assert bot.calls[0]["parse_mode"] == "HTML"
            assert "скрытая цепочка" not in payload
            assert "<thought>" not in payload
            assert "&lt;thought&gt;" not in payload
            assert payload.startswith("<b>Итог</b>")
            assert trace is not None
            assert trace.delivered_digest == turn_trace.text_digest(payload)
        finally:
            turn_trace.close(cid)

    @pytest.mark.asyncio
    async def test_trace_has_exactly_one_html_delivery_for_the_turn(self):
        """Нет дублирующей трассы/доставки; digest = фактический payload."""
        cid = "c2-trace-html"
        turn_trace.begin(cid, chat_id=CHAT_ID, trigger="test")
        try:
            bot = FakeBot()

            result = await _send(bot, "**Итог**\n\n- один",
                                 correlation_id=cid)

            trace = turn_trace.get(cid)
            assert result == 1001
            assert trace is not None
            assert trace.delivery["outcome"] == "success"
            assert trace.delivery["channel"] == "html"
            assert trace.delivery["tg_message_ids"] == [1001]
            ops = [op["op"] for op in trace.ops]
            assert ops.count("html_escape") == 1
            assert ops.count("egress_sanitize") == 1
            assert ops.count("telegram_chunk") == 1
            assert "plain_render" not in ops
            # Итоговый digest трассы — ровно то, что ушло в Bot API.
            assert trace.delivered_digest == turn_trace.text_digest(
                bot.calls[0]["text"])
        finally:
            turn_trace.close(cid)


# ── long / partial failure / retry ────────────────────────────────────────

class TestStructuredDeliveryFailureSemantics:
    @staticmethod
    def _long_answer() -> str:
        return "**" + ("Слово " * 900).strip() + "**"

    @pytest.mark.asyncio
    async def test_long_answer_chunks_html_reply_only_first(self):
        bot = FakeBot()
        answer = self._long_answer()

        result = await _send(bot, answer)

        assert result == 1001
        assert len(bot.calls) >= 2
        assert all(call["parse_mode"] == "HTML" for call in bot.calls)
        assert bot.calls[0]["reply_to_message_id"] == 42
        assert all("reply_to_message_id" not in call
                   for call in bot.calls[1:])
        for call in bot.calls:
            assert tm.utf16_units(call["text"]) <= _CHUNK_LIMIT
            assert "**" not in call["text"]
        joined = " ".join(call["text"] for call in bot.calls)
        assert "Слово" in joined and "Слово Слово" in joined

    @pytest.mark.asyncio
    async def test_partial_failure_falls_back_only_failed_chunk_no_resend(self):
        bot = FakeBot(fail_html={1})
        answer = self._long_answer()

        result = await _send(bot, answer)

        assert result == 1001
        assert len(bot.calls) >= 3
        assert bot.calls[0]["parse_mode"] == "HTML"
        assert bot.calls[1]["parse_mode"] == "HTML"      # отклонён fake API
        fallback = bot.calls[2]
        assert "parse_mode" not in fallback
        assert "<b>" not in fallback["text"]
        assert fallback["text"].strip()
        # Первый доставленный чанк не отправлялся повторно.
        first_text = bot.calls[0]["text"]
        assert [call["text"] for call in bot.calls].count(first_text) == 1
        # Никакой новой генерации: в тесте нет LLM, а вызовов ровно 3.
        assert len(bot.calls) == 3

    @pytest.mark.asyncio
    async def test_retry_after_retries_same_chunk_once(self):
        bot = FakeBot(retry_after_once=True)

        result = await _send(bot, "**разбор**")

        assert result == 1001
        assert len(bot.calls) == 2
        assert bot.calls[0]["text"] == bot.calls[1]["text"] == "<b>разбор</b>"
        assert bot.calls[0]["parse_mode"] == bot.calls[1]["parse_mode"] == "HTML"
        assert bot.calls[0]["reply_to_message_id"] == 42

    @pytest.mark.asyncio
    async def test_plain_fallback_failure_stops_with_first_delivered_id(self):
        bot = FakeBot(fail_html={1}, fail_plain={2})

        result = await _send(bot, self._long_answer())

        assert result == 1001
        assert len(bot.calls) == 3
        assert [call["text"] for call in bot.calls].count(
            bot.calls[0]["text"]) == 1

    @pytest.mark.asyncio
    async def test_returned_first_id_is_the_single_downstream_identifier(
            self, monkeypatch):
        """Call-site не пишет ledger сам; downstream получает один первый id."""
        bot = FakeBot()
        ledger = AsyncMock()
        monkeypatch.setattr(dcs._ledger, "record_delivered_output", ledger)
        doc = FakeDocument("**итог**")

        sent_id = await _send(bot, "игнорируется", document=doc)

        assert sent_id == 1001
        assert ledger.await_count == 0       # egress не дублирует запись
        # Ровно один id для существующего remember/ledger-вызова после send:
        # reply-таргет присутствует только у первого (и единственного) чанка.
        reply_calls = [call for call in bot.calls
                       if call.get("reply_to_message_id") == 42]
        assert len(reply_calls) == 1
        assert sent_id == reply_calls[0].get("message_id", sent_id)


# ── неизменные ветки и границы ────────────────────────────────────────────

class TestUnchangedBranches:
    @pytest.mark.asyncio
    async def test_rich_success_never_reaches_structured_path(self, monkeypatch):
        structured = AsyncMock()
        monkeypatch.setattr(tm, "send_structured", structured)
        bot = FakeBot()

        result = await _send(bot, "**статья**", rich=True)

        assert result == 1001
        assert len(bot.rich_calls) == 1
        assert bot.calls == []
        assert structured.await_count == 0

    @pytest.mark.asyncio
    async def test_rich_failure_then_structured_same_answer(self):
        bot = FakeBot()
        bot.send_rich_message = AsyncMock(
            side_effect=RuntimeError("sendRichMessage not supported"))

        result = await _send(bot, "**разбор**", rich=True)

        assert result == 1001
        assert bot.send_rich_message.await_count == 1
        assert len(bot.calls) == 1
        assert bot.calls[0]["parse_mode"] == "HTML"
        assert bot.calls[0]["text"] == "<b>разбор</b>"

    @pytest.mark.asyncio
    async def test_lore_branch_is_unchanged_safe_html(self):
        bot = FakeBot()
        answer = "<b>ок</b> 5 < 10"

        await _send(bot, answer, lore=True)

        assert len(bot.calls) == 1
        assert bot.calls[0]["parse_mode"] == "HTML"
        assert bot.calls[0]["text"] == "<b>ок</b> 5 &lt; 10"

    @pytest.mark.asyncio
    async def test_deep_research_branch_is_unchanged_safe_html(self):
        bot = FakeBot()
        answer = "<b>акцент</b> 5 < 10"

        await _send(bot, answer, deep_research=True)

        assert len(bot.calls) == 1
        assert bot.calls[0]["parse_mode"] == "HTML"
        assert bot.calls[0]["text"] == "<b>акцент</b> 5 &lt; 10"

    @pytest.mark.asyncio
    async def test_long_lore_stays_plain_without_tag_split(self):
        bot = FakeBot()
        answer = "<b>" + ("слово " * 900) + "</b>"

        await _send(bot, answer, lore=True)

        # send_chunked_reply режет длинный plain по пробелам; ни один чанк
        # не получает parse_mode и не содержит разорванного/сырого <b>.
        assert len(bot.calls) >= 1
        assert all("parse_mode" not in call for call in bot.calls)
        assert all("<b>" not in call["text"] for call in bot.calls)
        assert all("</b>" not in call["text"] for call in bot.calls)

    def test_shared_send_defaults_and_summary_path_untouched(self):
        # C2 не меняет общий SmartModule-путь и его defaults.
        assert inspect.signature(
            send_chunked_reply).parameters["parse_mode"].default is None
        assert tm.DEFAULT_CHUNK_LIMIT == _CHUNK_LIMIT
        import services.summary_generator as sg
        source = inspect.getsource(sg)
        assert "telegram_markup" not in source
        assert "send_structured" not in source


# ── матрица decision → фактический payload ────────────────────────────────

@pytest.mark.parametrize(("answer", "expect_html"), [
    ("Просто болтовня", False),
    ("2 * 3 * 4 = 24", False),
    ("snake_case_name", False),
    ("**Итог**", True),
    ("`код`", True),
    ("[метка](https://example.com)", True),
    ("# Заголовок", True),
    ("1. пункт", True),
    ("> цитата", True),
    ("```python\nprint(1)\n```", True),
])
@pytest.mark.asyncio
async def test_decision_and_actual_payload_agree(answer, expect_html):
    bot = FakeBot()

    await _send(bot, answer)

    assert len(bot.calls) == 1
    call = bot.calls[0]
    assert ("parse_mode" in call) is expect_html
    if expect_html:
        assert call["parse_mode"] == "HTML"
        assert "**" not in call["text"] and "`" not in call["text"]
    else:
        assert call["text"] == answer
        assert "entities" not in call
