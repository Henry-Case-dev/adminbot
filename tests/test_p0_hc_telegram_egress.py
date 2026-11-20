"""P0-HC C1 — Telegram markup egress: parser, HTML, safe chunking, sender.

Контракт: ``plans/features/p0-history-coverage-temporal-egress/
arch-contract-2026-11-21.md`` §4.1, rows HC-EGRESS-CHANNEL-CHOICE /
HC-EGRESS-SAFE-CHUNKING. Никакой живой сети: fake Bot API + чистые функции.
"""
import html as html_module
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from services import telegram_markup as tm
from services.smartmodule_utils import _CHUNK_LIMIT

pytestmark = pytest.mark.system2

_BALANCED_RE = re.compile(
    r"<(/?)(b|i|u|s|code|pre|blockquote|a)\b[^>]*>")


def _assert_balanced(chunk: str) -> None:
    stack: list[str] = []
    for match in _BALANCED_RE.finditer(chunk):
        closing, name = match.groups()
        if closing:
            assert stack and stack[-1] == name, (chunk, stack, name)
            stack.pop()
        else:
            stack.append(name)
    assert stack == [], (chunk, stack)
    assert chunk.count("<") == chunk.count(">")


def _text_of(chunk: str) -> str:
    return html_module.unescape(re.sub(r"<[^>]+>", "", chunk))


class FakeBot:
    """Fake Bot API: записывает payload, умеет падать на выбранных чанках."""

    def __init__(self, *, fail_html: set[int] | None = None,
                 fail_plain: set[int] | None = None,
                 retry_after_once: bool = False):
        self.calls: list[dict] = []
        self._fail_html = fail_html or set()
        self._fail_plain = fail_plain or set()
        self._retry_after_once = retry_after_once
        self._message_id = 1000
        self.send_message = AsyncMock(side_effect=self._send)

    async def _send(self, chat_id, text, **kwargs):
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
        return SimpleNamespace(message_id=self._message_id)


class FakeDocument:
    def __init__(self, text: str):
        self._text = text

    def plain_text(self) -> str:
        return self._text


# ── решение о канале ──────────────────────────────────────────────────────

class TestDecideMarkup:
    def test_casual_text_is_plain_and_not_forced_into_structure(self):
        text = "Привет. Просто болтаем про вчерашний вечер и всякое."
        assert tm.decide_markup(text) == ("plain", "plain_no_markup")
        assert tm.to_telegram_html(text) == text
        assert tm.to_plain(text) == text

    def test_empty_is_plain(self):
        assert tm.decide_markup("") == ("plain", "plain_empty")
        assert tm.decide_markup("   \n") == ("plain", "plain_empty")

    @pytest.mark.parametrize("text", [
        "2 * 3 * 4 = 24",
        "snake_case_name",
        r"\*не жирный\*",
        r"\*\*тоже буквально\*\*",
        "**не закрыт",
        "одинокая * и одинокая _",
        "a ** b ** c",
    ])
    def test_literal_and_malformed_markup_stays_plain(self, text):
        assert tm.decide_markup(text)[0] == "plain"

    @pytest.mark.parametrize("text", [
        "x **жирный** y",
        "x __жирный__ y",
        "`код`",
        "[метка](https://example.com/page)",
    ])
    def test_inline_markup_selects_html_tier_one(self, text):
        assert tm.decide_markup(text) == ("telegram_html", "markup_tier1")

    @pytest.mark.parametrize("text", [
        "# Заголовок",
        "- пункт",
        "1. пункт",
        "> цитата",
        "```python\nprint(1)\n```",
        "**Псевдозаголовок**",
        "~~зачёркнуто~~",
    ])
    def test_block_markup_selects_html_tier_two(self, text):
        assert tm.decide_markup(text) == ("telegram_html", "markup_tier2")

    def test_single_star_is_not_italic_without_tier_two(self):
        assert tm.decide_markup("*x*") == ("plain", "plain_no_markup")
        assert "&lt;i&gt;" not in tm.to_telegram_html("*x*")
        assert "<i>" not in tm.to_telegram_html("*x*")

    def test_escaped_stars_are_literal_even_in_tier_two(self):
        text = "# H\n\n\\*буквально\\* и *курсив*"
        html = tm.to_telegram_html(text)
        assert "\\*" not in html
        assert "*буквально*" in html
        assert "<i>курсив</i>" in html


# ── HTML-рендеринг ────────────────────────────────────────────────────────

class TestTelegramHtml:
    def test_bold_and_italic(self):
        assert tm.to_telegram_html("**жирный**") == "<b>жирный</b>"
        assert tm.to_telegram_html("x __жирный__ y") == "x <b>жирный</b> y"
        assert tm.to_telegram_html("# H\n\n*i*") == "<b>H</b>\n\n<i>i</i>"

    def test_inline_code_escapes_html(self):
        html = tm.to_telegram_html('`a<b&c"d`')
        assert html == "<code>a&lt;b&amp;c&quot;d</code>"

    def test_fence_with_language_and_literal_markers(self):
        html = tm.to_telegram_html("```python\nprint('**x** <y>')\n```")
        assert html == (
            '<pre><code class="language-python">'
            "print('**x** &lt;y&gt;')</code></pre>")

    def test_fence_without_language(self):
        assert tm.to_telegram_html("```\nx < y\n```") == (
            "<pre><code>x &lt; y</code></pre>")

    def test_safe_links(self):
        html = tm.to_telegram_html("[метка](https://example.com/?a=1&b=2)")
        assert html == (
            '<a href="https://example.com/?a=1&amp;b=2">метка</a>')
        assert tm.to_telegram_html("[u](tg://user?id=1)") == (
            '<a href="tg://user?id=1">u</a>')

    @pytest.mark.parametrize("url", [
        "javascript:alert(1)",
        "ftp://example.com/x",
        "data:text/html,x",
        "https://example.com/\"onmouseover=x",
    ])
    def test_unsafe_links_remain_text(self, url):
        text = f"[x]({url})"
        html = tm.to_telegram_html(text)
        assert "<a " not in html
        assert "[x](" in html

    def test_headings_and_pseudo_heading(self):
        assert tm.to_telegram_html("### Заголовок") == "<b>Заголовок</b>"
        assert tm.to_telegram_html("**Псевдозаголовок**") == (
            "<b>Псевдозаголовок</b>")
        assert tm.to_telegram_html("#hashtag") == "#hashtag"

    def test_lists_and_quote(self):
        assert tm.to_telegram_html("- один\n- два") == "• один\n• два"
        assert tm.to_telegram_html("1. один\n2) два") == "1. один\n2. два"
        assert tm.to_telegram_html("> цитата\n> вторая") == (
            "<blockquote>цитата\nвторая</blockquote>")

    def test_strike(self):
        assert tm.to_telegram_html("~~старое~~") == "<s>старое</s>"

    def test_raw_html_is_always_escaped(self):
        text = '<b>hack</b> <script>alert("x")</script>'
        html = tm.to_telegram_html(text)
        assert "<b>" not in html
        assert "<script>" not in html
        assert "&lt;b&gt;hack&lt;/b&gt;" in html
        assert "&lt;script&gt;" in html

    def test_special_characters_are_escaped(self):
        assert tm.to_telegram_html("a & b < c > d \"q\"") == (
            "a &amp; b &lt; c &gt; d &quot;q&quot;")

    def test_code_content_is_not_reparsed(self):
        html = tm.to_telegram_html("`**x** [y](https://e.com)`")
        assert html == "<code>**x** [y](https://e.com)</code>"

    def test_unclosed_inline_code_is_literal(self):
        assert tm.to_telegram_html("`x") == "`x"

    def test_unclosed_fence_renders_code_without_raw_markers(self):
        html = tm.to_telegram_html("```python\nprint(1)")
        assert html == (
            '<pre><code class="language-python">print(1)</code></pre>')
        assert "```" not in html

    def test_unicode_and_zero_width_preserved(self):
        text = "😀\u200b **жирный**"
        html = tm.to_telegram_html(text)
        assert "😀\u200b" in html
        assert "<b>жирный</b>" in html

    def test_deterministic(self):
        text = "# H\n\n**a** `b` [c](https://e.com)\n- d"
        assert tm.to_telegram_html(text) == tm.to_telegram_html(text)
        assert tm.to_plain(text) == tm.to_plain(text)


# ── plain-рендеринг / паритет ─────────────────────────────────────────────

class TestPlain:
    def test_plain_text_is_byte_identical(self):
        text = (
            "Обычная реплика: 2*3*4, snake_case_name, <не тег>, \"кавычки\"."
        )
        assert tm.to_plain(text) == text
        assert tm.decide_markup(text)[0] == "plain"

    def test_plain_removes_markers_but_keeps_content(self):
        text = "# Заголовок\n\n**жирный** и *курсив* и `код`"
        assert tm.to_plain(text) == "Заголовок\n\nжирный и курсив и код"

    def test_plain_lists_and_quote(self):
        assert tm.to_plain("- один\n- два") == "• один\n• два"
        assert tm.to_plain("1. один\n2. два") == "1. один\n2. два"
        assert tm.to_plain("> цитата\n> вторая") == "цитата\nвторая"

    def test_plain_fence_keeps_literal_code(self):
        assert tm.to_plain("```python\nx = '**y**'\n```") == "x = '**y**'"

    def test_plain_link_keeps_url(self):
        assert tm.to_plain("[метка](https://example.com/page)") == (
            "метка (https://example.com/page)")
        assert tm.to_plain("[https://e.com](https://e.com)") == "https://e.com"

    def test_plain_escaped_markers(self):
        assert tm.to_plain(r"\*\*буквально\*\*") == "**буквально**"

    def test_plain_raw_html_not_escaped(self):
        assert tm.to_plain("<b>x</b> & y") == "<b>x</b> & y"

    def test_plain_trailing_newline_preserved(self):
        assert tm.to_plain("a\n") == "a\n"

    def test_html_to_plain_preserves_link_target(self):
        html = tm.to_telegram_html("[метка](https://example.com/page)")
        assert tm.html_to_plain(html) == "метка (https://example.com/page)"


# ── безопасный chunking ──────────────────────────────────────────────────

class TestChunking:
    def test_default_limit_matches_smartmodule(self):
        assert tm.DEFAULT_CHUNK_LIMIT == _CHUNK_LIMIT == 4096

    def test_empty(self):
        assert tm.split_telegram_html("") == []
        assert tm.split_telegram_html("", 20) == []

    def test_utf16_units(self):
        assert tm.utf16_units("abc") == 3
        assert tm.utf16_units("😀") == 2
        assert tm.utf16_units("😀a") == 3
        assert tm.utf16_units("\ud800") == 1       # lone surrogate, total

    def test_plain_text_partitions_exactly(self):
        text = ("слово " * 200).strip()
        chunks = tm.split_telegram_html(text, 100)
        assert len(chunks) > 1
        assert "".join(chunks) == text
        assert all(tm.utf16_units(chunk) <= 100 for chunk in chunks)

    def test_bold_is_closed_and_reopened(self):
        text = "**" + ("жирный " * 40).strip() + "**"
        chunks = tm.split_telegram_html(tm.to_telegram_html(text), 80)
        assert len(chunks) > 1
        for chunk in chunks:
            assert tm.utf16_units(chunk) <= 80
            _assert_balanced(chunk)
            assert chunk.startswith("<b>")
            assert chunk.endswith("</b>")
        assert "".join(_text_of(chunk) for chunk in chunks) == (
            ("жирный " * 40).strip())

    def test_link_reopened_with_same_href(self):
        html = tm.to_telegram_html(
            "[метка подлиннее](https://example.com/page)")
        chunks = tm.split_telegram_html(html, 48)
        assert len(chunks) > 1
        for chunk in chunks:
            assert 'href="https://example.com/page"' in chunk
            _assert_balanced(chunk)
        assert "".join(_text_of(chunk) for chunk in chunks) == "метка подлиннее"

    def test_long_unbroken_word_is_force_split(self):
        content = "Ж" * 500
        html = tm.to_telegram_html(f"**{content}**")
        chunks = tm.split_telegram_html(html, 64)
        assert len(chunks) > 1
        for chunk in chunks:
            assert tm.utf16_units(chunk) <= 64
            _assert_balanced(chunk)
        assert "".join(_text_of(chunk) for chunk in chunks) == content

    def test_emoji_and_surrogate_pairs_never_split(self):
        text = "😀" * 80
        chunks = tm.split_telegram_html(text, 9)
        assert len(chunks) > 1
        for chunk in chunks:
            assert tm.utf16_units(chunk) <= 9
            chunk.encode("utf-16-le")          # no lone surrogate
        assert "".join(chunks) == text

    def test_zero_width_and_combining_preserved(self):
        text = "a\u200bb\u0301c"
        chunks = tm.split_telegram_html(text, 4)
        assert "".join(chunks) == text
        assert all(tm.utf16_units(chunk) <= 4 for chunk in chunks)

    def test_fence_tags_reopened_across_chunks(self):
        html = tm.to_telegram_html(
            "```python\n" + ("print(1)\n" * 40) + "```")
        chunks = tm.split_telegram_html(html, 70)
        assert len(chunks) > 1
        for chunk in chunks:
            assert tm.utf16_units(chunk) <= 70
            _assert_balanced(chunk)
            assert chunk.startswith(
                '<pre><code class="language-python">')
            assert chunk.endswith("</code></pre>")

    def test_real_limit_4096_and_content_preserved(self):
        content = ("Очень длинный разбор " * 300).strip()
        html = tm.to_telegram_html(f"**{content}**")
        chunks = tm.split_telegram_html(html)
        assert len(chunks) > 1
        assert all(tm.utf16_units(chunk) <= 4096 for chunk in chunks)
        assert "".join(_text_of(chunk) for chunk in chunks) == content

    def test_link_with_entity_in_href_is_not_split(self):
        html = tm.to_telegram_html("[метка](https://e.com/?a=1&b=2)")
        chunks = tm.split_telegram_html(html, 40)
        for chunk in chunks:
            assert "&amp;" in chunk
            assert re.search(r"&[^;]*$", chunk) is None
            _assert_balanced(chunk)

    def test_entities_are_atomic(self):
        html = tm.to_telegram_html("& < > \"")
        chunks = tm.split_telegram_html(html, 8)
        for chunk in chunks:
            assert re.search(r"&[^;]*$", chunk) is None
            assert chunk.count("&") == chunk.count(";")
        assert "".join(chunks) == html

    def test_no_split_inside_tags(self):
        html = tm.to_telegram_html("**x** `" + ("y" * 300) + "`")
        chunks = tm.split_telegram_html(html, 24)
        assert len(chunks) > 1
        for chunk in chunks:
            _assert_balanced(chunk)
            assert tm.utf16_units(chunk) <= 24

    def test_deterministic(self):
        html = tm.to_telegram_html("**" + "слово " * 50 + "**")
        assert tm.split_telegram_html(html, 60) == tm.split_telegram_html(
            html, 60)

    def test_invalid_limit(self):
        with pytest.raises(ValueError):
            tm.split_telegram_html("<b>x</b>", 0)


# ── отправка на fake Bot API ─────────────────────────────────────────────

class TestSendStructured:
    @pytest.mark.asyncio
    async def test_plain_chat_uses_plain_path_and_reply(self):
        bot = FakeBot()
        first_id = await tm.send_structured(bot, 7, "привет, как дела?", 42)

        assert first_id == 1001
        assert len(bot.calls) == 1
        call = bot.calls[0]
        assert call["text"] == "привет, как дела?"
        assert "parse_mode" not in call
        assert call["reply_to_message_id"] == 42

    @pytest.mark.asyncio
    async def test_literal_stars_stay_plain(self):
        bot = FakeBot()
        await tm.send_structured(bot, 7, r"2 \* 3 = 6 и \*\*буквально\*\*", 1)
        assert bot.calls[0]["text"] == "2 * 3 = 6 и **буквально**"
        assert "parse_mode" not in bot.calls[0]

    @pytest.mark.asyncio
    async def test_html_path_uses_html_and_no_raw_markers(self):
        bot = FakeBot()
        first_id = await tm.send_structured(bot, 7, "**разбор**", 42)

        assert first_id == 1001
        call = bot.calls[0]
        assert call["parse_mode"] == "HTML"
        assert call["text"] == "<b>разбор</b>"
        assert "**" not in call["text"]
        assert call["reply_to_message_id"] == 42

    @pytest.mark.asyncio
    async def test_multichunk_reply_only_first(self):
        bot = FakeBot()
        text = "**" + ("Слово " * 100).strip() + "**"
        first_id = await tm.send_structured(bot, 7, text, 42, limit=80)

        assert len(bot.calls) > 1
        assert first_id == 1001
        assert bot.calls[0]["reply_to_message_id"] == 42
        for call in bot.calls[1:]:
            assert "reply_to_message_id" not in call
            assert call["parse_mode"] == "HTML"
            _assert_balanced(call["text"])

    @pytest.mark.asyncio
    async def test_bad_html_chunk_falls_back_only_that_chunk(self):
        bot = FakeBot(fail_html={1})
        text = ("**" + " ".join(f"Первый{i}" for i in range(40)) + "**\n\n**"
                + " ".join(f"Второй{i}" for i in range(40)) + "**")
        first_id = await tm.send_structured(bot, 7, text, 42, limit=80)

        assert first_id == 1001
        assert len(bot.calls) >= 3
        assert bot.calls[0]["parse_mode"] == "HTML"
        assert bot.calls[1]["parse_mode"] == "HTML"     # rejected by fake
        fallback = bot.calls[2]
        assert "parse_mode" not in fallback
        assert "<b>" not in fallback["text"]
        assert fallback["text"].strip()
        # Первый чанк не отправлялся повторно.
        first_text = bot.calls[0]["text"]
        assert [call["text"] for call in bot.calls].count(first_text) == 1

    @pytest.mark.asyncio
    async def test_link_fallback_keeps_url(self):
        bot = FakeBot(fail_html={0})
        first_id = await tm.send_structured(
            bot, 7, "[метка](https://example.com/page)", 42, limit=80)

        assert first_id == 1001
        assert len(bot.calls) == 2
        assert bot.calls[0]["parse_mode"] == "HTML"
        assert "parse_mode" not in bot.calls[1]
        assert "https://example.com/page" in bot.calls[1]["text"]

    @pytest.mark.asyncio
    async def test_plain_fallback_failure_stops_without_resend(self):
        bot = FakeBot(fail_html={1}, fail_plain={2})
        text = ("**" + " ".join(f"Первый{i}" for i in range(40)) + "**\n\n**"
                + " ".join(f"Второй{i}" for i in range(40)) + "**")
        first_id = await tm.send_structured(bot, 7, text, 42, limit=80)

        assert first_id == 1001
        assert len(bot.calls) == 3
        assert [call["text"] for call in bot.calls].count(
            bot.calls[0]["text"]) == 1

    @pytest.mark.asyncio
    async def test_retry_after_retries_same_chunk_once(self):
        bot = FakeBot(retry_after_once=True)
        first_id = await tm.send_structured(bot, 7, "**разбор**", 42)

        assert first_id == 1001
        assert len(bot.calls) == 2
        assert bot.calls[0]["text"] == bot.calls[1]["text"] == "<b>разбор</b>"
        assert bot.calls[0]["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_document_takes_plain_text(self):
        bot = FakeBot()
        document = FakeDocument("**из документа**")
        await tm.send_structured(bot, 7, "игнорируется", 1, document=document)

        assert len(bot.calls) == 1
        assert bot.calls[0]["text"] == "<b>из документа</b>"
        assert bot.calls[0]["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_empty_does_not_send(self):
        bot = FakeBot()
        assert await tm.send_structured(bot, 7, "   ", 1) is None
        assert bot.calls == []

    @pytest.mark.asyncio
    async def test_reasoning_tags_are_sanitized_before_html_parse(self):
        bot = FakeBot()
        await tm.send_structured(
            bot, 7, "**разбор** <thought>секрет</thought>", 1)
        assert len(bot.calls) == 1
        assert "секрет" not in bot.calls[0]["text"]
        assert "thought" not in bot.calls[0]["text"]
        assert bot.calls[0]["text"].startswith("<b>разбор</b>")

    @pytest.mark.asyncio
    async def test_plain_path_does_not_call_html_sender(self):
        bot = FakeBot()
        await tm.send_structured(bot, 7, "просто болтовня", 1)
        assert all("parse_mode" not in call for call in bot.calls)
