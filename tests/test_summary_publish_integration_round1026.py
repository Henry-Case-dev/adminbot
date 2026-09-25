"""S6 round1026 (`summary-publish-integration-round1026`, ADR-1026-11 D1–D10)
— публикационная интеграция живой доставки Саммари (§100–§106).

Покрытие T-3438…T-3453 (SC-01…SC-20):
  * SC-01/§100 — reuse существующего `sendRichMessage` (`send_rich_message`
    без изменений; второго rich-механизма нет);
  * SC-02/§101 — rich: `<img>` → настоящий `<h1>` → `<p>` (OFF и ON);
  * SC-03/§102 — `<p>`/`<b>`, экранирование `& < > " '`, Unicode/эмодзи/
    ссылки; `sanitize` ДО clean/escape (L-R1026S5-5); апострофы (L-R1026S5-6);
  * SC-04/§103 — памятка: утверждения/лимиты — spec §8, разметку делает код;
  * SC-05/§104 — обложка: `generate_image`/порядок/прикрепление не тронуты;
  * SC-06/§105 — plain: `<b>title</b>` + абзацы, чанки по границам абзацев,
    no-loss, `message_id` первого чанка в `PUBLISH_TEXT_COMPLETE`;
  * SC-07/§106 — 4 кода различимы, fail-closed, bounded retry (≤2 попытки);
  * SC-08/SC-09 — OFF/ON, 2-вызовность, `memorize_facts` и на ON (S-R1026S5-7);
  * SC-10/SC-11 — `PUBLISH_*` (§108/§109) + publish-узел/реальный статус;
  * SC-12/SC-13 — dry-run S9 без `PUBLISH_*`; viewer не переписан;
  * SC-14/SC-15/SC-19/SC-20 — R17, Δ DDL=0/Δ каталога=0, детерминизм, no-loss.

Автор: @Builder (S6, Step 4).
"""
from __future__ import annotations

import asyncio
import ast
import dataclasses
import json
import logging
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramRetryAfter

from config.settings import APP_VERSION, Settings
from services import execution_graph_source as egs
from services import param_catalog as pc
from services import summary_generator as sg
from services import usage_events
from services.llm_client import LLMError, LLMRateLimitError
from services.outgoing_guard import sanitize_outgoing
from services.summary_article_formatter import (
    MAX_PARAGRAPHS_HARD,
    RICH_MAX_CHARS,
    chunk_plain_blocks,
    chunk_plain_text,
    document_from_plain_text,
    extract_title_from_markdown,
    format_plain_html,
    format_plain_text,
    format_rich_html,
    rich_document_limits,
)
from services.summary_generator import SummaryDraft, SummaryGenerator
from services.summary_run_log import (
    CODE_COVER_GENERATION_FAILED,
    CODE_RICH_MESSAGE_SEND_FAILED,
    CODE_SUMMARY_GENERATION_FAILED,
    CODE_TEXT_FALLBACK_FAILED,
    STATUS_DEGRADED,
    STATUS_EMPTY,
    STATUS_FAILED,
    RunContext,
)
from services.summary_xml import XmlGroundingBuilder

from tests.test_summary_generator import FakeMemory, _row

ROOT = Path(__file__).resolve().parents[1]

CHAT = -1001
_RID = "RID-S6-0001"
_HYBRID_FLAG = "flags.summary_hybrid_l2_enabled"
_FILTER_FLAG = "flags.summary_filter_enabled"
_DIGEST = "# Событие\n- Вася спорил с Петей про футбол"
_NARRATOR = "Первый абзац рассказа. Второй абзац рассказа."
_SECRET_TEXT = "СЕКРЕТНЫЙ_ТЕКСТ_САММАРИ_R17"

_L1_JSON = json.dumps({
    "schema_version": 1,
    "threads": [{
        "thread_id": "t1", "topic": "Тема", "message_ids": [101],
        "facts": [{"text": "Важный факт", "evidence_message_ids": [101]}],
    }],
    "unassigned_message_ids": [],
})

_L2_JSON = json.dumps({
    "schema_version": 1,
    "title": "Тестовая статья",
    "paragraphs": [
        {"text": "Первый абзац статьи.", "emphasis": "Первый"},
    ],
}, ensure_ascii=False)

# ON rich: `cover_prompt` в L1-контракте (top-level) → service → rich-путь.
_L1_JSON_RICH = json.dumps({
    "schema_version": 1,
    "cover_prompt": "rain",
    "threads": [{
        "thread_id": "t1", "topic": "Тема", "message_ids": [101],
        "facts": [{"text": "Важный факт", "evidence_message_ids": [101]}],
    }],
    "unassigned_message_ids": [],
}, ensure_ascii=False)


# ── helpers ────────────────────────────────────────────────────────────────

def _rows():
    return [
        _row(id=1, tg_message_id=101, user_id=10, text="@vasya привет",
             timestamp=1000),
        _row(id=2, tg_message_id=102, user_id=11, text="второе сообщение",
             timestamp=1001),
    ]


def _patch_chat_limit(monkeypatch, overrides=None):
    overrides = dict(overrides or {})

    async def _fake(chat_id, key, default=None):
        if (chat_id, key) in overrides:
            return overrides[(chat_id, key)]
        if key == _HYBRID_FLAG:
            # S10 (ADR-1026-12 D2): Hybrid default ON — ON-кейсы включают режим
            # ЯВНО (`_HYBRID_FLAG: True`), OFF/§106-кейсы — явный аварийный OFF.
            return False
        return default

    monkeypatch.setattr(sg, "_chat_limit", _fake)


def _fixed_rid(monkeypatch):
    monkeypatch.setattr(usage_events, "new_correlation_id", lambda: _RID)


def _lines(caplog, name):
    return [r.getMessage() for r in caplog.records
            if r.getMessage().startswith(name + " |")]


class _TwoCallLLM:
    def __init__(self, narrator=_NARRATOR, digest=_DIGEST):
        self.calls = 0
        self.correlation_ids = []
        self.digest = digest
        self.narrator = narrator

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.correlation_ids.append(kwargs.get("correlation_id"))
        return self.digest if self.calls == 1 else self.narrator


def _gen(memory, llm):
    return SummaryGenerator(memory, XmlGroundingBuilder(), llm, AsyncMock())


def _capture_send_text(monkeypatch, sent, *, message_id=100):
    async def _send(bot, chat_id, text, **kw):
        sent.append({"text": text, "kw": kw})
        return SimpleNamespace(message_id=message_id + len(sent))

    monkeypatch.setattr(sg, "send_text", _send)


pytestmark = pytest.mark.system2


@pytest.fixture(autouse=True)
def _clean_graph_store():
    egs.reset()
    yield
    egs.reset()


# ══ SC-19/SC-03: детерминированные адаптеры и форматтер ════════════════════

class TestTitleAdapter:
    def test_markdown_heading_extracted(self):
        assert extract_title_from_markdown(
            "# Событие\n- Вася спорил") == "Событие"
        assert extract_title_from_markdown("## Два\n\nтекст") == "Два"

    def test_no_heading_empty(self):
        assert extract_title_from_markdown("просто текст\n- буллет") == ""
        assert extract_title_from_markdown("") == ""
        assert extract_title_from_markdown(None) == ""

    def test_single_line_and_cap(self):
        title = extract_title_from_markdown("# " + "я" * 300)
        assert len(title) == 200 and "\n" not in title

    def test_markdown_emphasis_stripped(self):
        assert extract_title_from_markdown("# **Жирный** заголовок") == \
            "Жирный заголовок"


class TestPlainAdapter:
    def test_explicit_title_priority(self):
        doc = document_from_plain_text("Тело статьи.", title="Заголовок")
        assert doc["title"] == "Заголовок"
        assert doc["paragraphs"] == [{"text": "Тело статьи.", "emphasis": None}]

    def test_first_short_line_paragraph(self):
        doc = document_from_plain_text("Заголовок\n\nТело статьи.")
        assert doc["title"] == "Заголовок"
        assert doc["paragraphs"][0]["text"] == "Тело статьи."

    def test_first_sentence_fallback(self):
        doc = document_from_plain_text(
            "Первое предложение. Второе предложение.")
        assert doc["title"] == "Первое предложение."
        assert doc["paragraphs"][0]["text"] == "Второе предложение."

    def test_no_title_body_unchanged(self):
        doc = document_from_plain_text("Единственный абзац без точки")
        assert doc["title"] == ""
        assert doc["paragraphs"] == [
            {"text": "Единственный абзац без точки", "emphasis": None}]

    def test_no_invented_title_and_no_truncation(self):
        text = "Очень длинное предложение без завершения и без точки " * 10
        doc = document_from_plain_text(text)
        assert doc["title"] == ""
        # Тело не обрезано ради заголовка (полный текст сохранён).
        assert "".join(p["text"] for p in doc["paragraphs"]).strip() == \
            text.strip()

    def test_body_never_lost(self):
        text = "Заголовок\n\nПервый абзац.\n\nВторой абзац."
        doc = document_from_plain_text(text)
        parts = [doc["title"]] + [p["text"] for p in doc["paragraphs"]]
        assert [p for p in parts if p] == [
            "Заголовок", "Первый абзац.", "Второй абзац."]

    def test_input_not_mutated(self):
        text = "Заголовок\n\nТело."
        snapshot = str(text)
        document_from_plain_text(text)
        assert text == snapshot

    def test_determinism_double_run(self):
        text = "Заголовок\n\nТело.\n\nЕщё."
        first = json.dumps(document_from_plain_text(text), ensure_ascii=False)
        second = json.dumps(document_from_plain_text(text), ensure_ascii=False)
        assert first == second
        assert format_rich_html(document_from_plain_text(text)) == \
            format_rich_html(document_from_plain_text(text))


class TestChunking:
    def test_chunk_plain_text_paragraphs(self):
        text = "А" * 3000 + "\n\n" + "Б" * 3000
        chunks = chunk_plain_text(text, limit=4096)
        assert len(chunks) == 2
        assert chunks[0] == "А" * 3000
        assert chunks[1] == "Б" * 3000

    def test_chunk_plain_text_no_loss_long_paragraph(self):
        text = ("слово " * 2000).strip()        # один абзац > 4096
        chunks = chunk_plain_text(text, limit=4096)
        assert "".join(chunks) == text          # без потерь
        assert all(len(c) <= 4096 for c in chunks)

    def test_chunk_plain_blocks_no_loss(self):
        doc = {"schema_version": 1, "title": "Т",
               "paragraphs": [{"text": f"Абзац {i}.", "emphasis": None}
                              for i in range(5)]}
        chunks = chunk_plain_blocks(doc, limit=4096)
        assert chunks == ["<b>Т</b>"] + [f"Абзац {i}." for i in range(5)] \
            or "".join(chunks).count("Абзац") == 5
        joined = "\n\n".join(chunks)
        for i in range(5):
            assert f"Абзац {i}." in joined
            assert joined.count(f"Абзац {i}.") == 1

    def test_chunk_plain_blocks_sanitize_before_escape(self):
        # L-R1026S5-5: sanitize → clean → escape. Кастомный sanitize
        # подставляет тег — он обязан быть ЭКРАНИРОВАН (значит sanitize был
        # ДО escape); технический `fact:` вырезается.
        doc = {"schema_version": 1, "title": "",
               "paragraphs": [{"text": "факт fact:123 и метка", "emphasis": None}]}
        chunks = chunk_plain_blocks(
            doc, sanitize=lambda t: sanitize_outgoing(t).replace("метка", "<evil>"))
        joined = "".join(chunks)
        assert "&lt;evil&gt;" in joined
        assert "<evil>" not in joined
        assert "fact:123" not in joined

    def test_chunk_plain_blocks_default_sanitize_strips_ids(self):
        doc = {"schema_version": 1, "title": "",
               "paragraphs": [{"text": "факт fact:9.", "emphasis": None}]}
        assert "fact:9" not in "".join(chunk_plain_blocks(doc))

    def test_chunk_plain_blocks_renders_emphasis_single_source(self):
        # B-R1026S6-2: фактическая plain-доставка рендерит абзацные `<b>`
        # тем же каноном, что и предпросмотр S9 (единый источник) — раньше
        # `emphasis` здесь игнорировался.
        doc = {"schema_version": 1, "title": "Заголовок",
               "paragraphs": [
                   {"text": "Главная тема — сильный дождь.",
                    "emphasis": "дождь"},
                   {"text": "Второй абзац без акцента.", "emphasis": None},
               ]}
        chunks = chunk_plain_blocks(doc)
        assert chunks == [format_plain_html(doc)]     # байт-в-байт один канон
        assert "<b>дождь</b>" in chunks[0]
        assert chunks[0].count("<b>") == 2            # title + один абзацный
        assert chunks[0].count("</b>") == 2

    def test_chunk_plain_blocks_emphasis_escaped(self):
        # Акцент — пользовательский текст: экранирование сохраняется,
        # ≤1 `<b>` на абзац (B-R1026S6-2/SC-06).
        doc = {"schema_version": 1, "title": "",
               "paragraphs": [
                   {"text": "Ключ <b>&</b> внутри.", "emphasis": "<b>&</b>"},
               ]}
        chunks = chunk_plain_blocks(doc)
        assert chunks == ["Ключ <b>&lt;b&gt;&amp;&lt;/b&gt;</b> внутри."]
        assert "<b>&</b>" not in chunks[0]
        assert chunks[0].count("<b>") == 1

    def test_chunk_plain_blocks_600_no_loss(self):
        # B-R1026S6-1 (проба c): кап 498 больше не режет хвост в чанкере.
        doc = {"schema_version": 1, "title": "",
               "paragraphs": [{"text": f"Абзац {i}.", "emphasis": None}
                              for i in range(600)]}
        joined = "\n\n".join(chunk_plain_blocks(doc, limit=4096))
        missing = [i for i in range(600)
                   if joined.count(f"Абзац {i}.") != 1]
        assert missing == []


class TestRichFormatter:
    def _doc(self):
        return {
            "schema_version": 1, "title": 'Заголовок "X" & <Y>',
            "paragraphs": [
                {"text": "Абзац с & < > \" ' и ссылкой https://t.me/x.",
                 "emphasis": "ссылкой"},
                {"text": "😀 эмодзи и Юникод — ок.", "emphasis": None},
            ],
        }

    def test_order_img_h1_p(self):
        html = format_rich_html(self._doc(), cover_id="summary_cover")
        assert html.startswith(
            '<img src="tg://photo?id=summary_cover"><h1>')
        assert html.index("<img") < html.index("<h1>") < html.index("<p>")
        assert "</h1><p>" in html

    def test_tags_whitelist_only(self):
        html = format_rich_html(self._doc(), cover_id="summary_cover")
        tags = set(re.findall(r"</?([a-z0-9]+)", html))
        assert tags <= {"img", "h1", "p", "b"}

    def test_h1_not_bold_and_single_b_per_paragraph(self):
        html = format_rich_html(self._doc(), cover_id="summary_cover")
        head = html[html.index("<h1>"):html.index("</h1>")]
        assert "<b>" not in head
        for paragraph in re.findall(r"<p>(.*?)</p>", html):
            assert paragraph.count("<b>") <= 1

    def test_escaping(self):
        html = format_rich_html(self._doc(), cover_id=None)
        assert "&amp;" in html and "&lt;" in html and "&gt;" in html
        assert "&quot;" in html and "&#x27;" in html
        assert "😀" in html
        # Ссылка экранирована не ломает разметку.
        assert "https://t.me/x." in html

    def test_egress_guard_noop_on_rich_output(self):
        # L-R1026S5-5 (rich): egress-guard — no-op на выводе format_rich_html.
        doc = self._doc()
        html = format_rich_html(doc, cover_id="summary_cover")
        assert sanitize_outgoing(html) == html
        assert sanitize_outgoing(format_plain_html(doc)) == \
            format_plain_html(doc)

    def test_plain_has_bold_title_no_h1(self):
        html = format_plain_html(self._doc())
        assert html.startswith("<b>")
        assert "<h1>" not in html and "<img" not in html


class TestRichLimitsNoSilentTrim:
    """B-R1026S6-1: rich-канал проверяется по ПОЛНОМУ тексту, без среза."""

    @staticmethod
    def _doc(paragraphs):
        return {"schema_version": 1, "title": "Т", "paragraphs": paragraphs}

    def test_full_text_no_silent_trim(self):
        paragraphs = [{"text": "я" * 890, "emphasis": None} for _ in range(45)]
        html = format_rich_html(self._doc(paragraphs))
        assert html.count("<p>") == 45          # ни один абзац не срезан
        assert len(html) > RICH_MAX_CHARS

    def test_char_limit_reason(self):
        paragraphs = [{"text": "я" * 890, "emphasis": None} for _ in range(45)]
        plan = rich_document_limits(self._doc(paragraphs))
        assert plan["fits"] is False
        assert plan["reason"] == "rich_char_limit"
        assert plan["paragraphs"] == 45
        assert plan["html_len"] == len(plan["html"]) > plan["max_chars"]

    def test_paragraph_limit_reason(self):
        paragraphs = [{"text": f"Абзац {i}.", "emphasis": None}
                      for i in range(600)]
        plan = rich_document_limits(self._doc(paragraphs))
        assert plan["fits"] is False
        assert plan["reason"] == "rich_paragraph_limit"
        assert plan["paragraphs"] == 600
        assert plan["html"].count("<p>") == 600

    def test_small_document_fits(self):
        plan = rich_document_limits(self._doc(
            [{"text": "Короткий абзац.", "emphasis": None}]))
        assert plan["fits"] is True and plan["reason"] == ""


# ══ SC-01/SC-02/SC-03: OFF-путь (reuse sendRichMessage, H1-порядок) ════════

class TestOffDelivery:
    def _patch_cover(self, monkeypatch, tmp_path, *, image=None,
                     message_id=321):
        gen = _gen(FakeMemory(), MagicMock())
        gen._resolve_cover_style_text = AsyncMock(return_value="style")
        if image is None:
            img = tmp_path / "cover.jpg"
            img.write_bytes(b"jpeg")
            image = str(img)
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(image, "ok")))
        monkeypatch.setattr(sg, "build_cover_media", MagicMock(return_value="M"))
        rich = AsyncMock(return_value=SimpleNamespace(message_id=message_id))
        monkeypatch.setattr(sg, "send_rich_message", rich)
        return gen, rich

    @pytest.mark.asyncio
    async def test_off_rich_img_h1_p(self, monkeypatch, tmp_path, caplog):
        _fixed_rid(monkeypatch)
        gen, rich = self._patch_cover(monkeypatch, tmp_path)
        sent_text = []

        async def _no_plain(*a, **kw):
            sent_text.append(a)

        monkeypatch.setattr(sg, "send_text", _no_plain)

        with caplog.at_level(logging.INFO):
            await gen._deliver_rich(CHAT, _NARRATOR, "a lone cat",
                                    correlation_id=_RID,
                                    title="Событие")
        assert not sent_text                       # plain не использован
        rich.assert_awaited_once()
        _, _, html = rich.await_args.args
        assert rich.await_args.kwargs["content_format"] == "html"
        assert rich.await_args.kwargs["cover_id"] == sg.SUMMARY_COVER_MEDIA_ID
        assert html.startswith(
            '<img src="tg://photo?id=summary_cover"><h1>Событие</h1><p>')
        assert "<h1>Событие</h1>" in html
        done = _lines(caplog, "PUBLISH_RICH_COMPLETE")
        assert done and f"run_id={_RID}" in done[0]
        assert "method=sendRichMessage" in done[0]
        assert "message_id=321" in done[0]
        start = _lines(caplog, "PUBLISH_RICH_START")
        assert start and f"run_id={_RID}" in start[0]

    @pytest.mark.asyncio
    async def test_off_rich_fallback_to_plain_no_h1(self, monkeypatch,
                                                    caplog):
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        gen._resolve_cover_style_text = AsyncMock(return_value="style")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(None, "no_key")))
        sent = []
        _capture_send_text(monkeypatch, sent)
        ctx = RunContext(run_id=_RID, chat_id=CHAT)

        with caplog.at_level(logging.INFO):
            await gen._deliver_rich(CHAT, _NARRATOR, "a lone cat",
                                    correlation_id=_RID, ctx=ctx,
                                    title="Событие")
        joined = "".join(item["text"] for item in sent)
        assert joined.startswith("<b>Событие</b>")
        assert "<h1>" not in joined and "<img" not in joined
        assert all(item["kw"].get("parse_mode") == "HTML" for item in sent)
        cover = _lines(caplog, "COVER_COMPLETE")
        assert cover and "status=unavailable" in cover[0]
        assert f"code={CODE_COVER_GENERATION_FAILED}" in cover[0]
        pub = _lines(caplog, "PUBLISH_TEXT_COMPLETE")
        assert pub and f"reason=cover_unavailable" in pub[0]
        assert ctx.publish_channel == "text" and ctx.publish_status == "ok"

    @pytest.mark.asyncio
    async def test_off_plain_document_published(self, monkeypatch):
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        sent = []
        _capture_send_text(monkeypatch, sent)
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        await gen._deliver_plain(CHAT, "Первый абзац.\n\nВторой абзац.",
                                 correlation_id=_RID, ctx=ctx)
        joined = "".join(item["text"] for item in sent)
        # Первое предложение первого абзаца → жирный заголовок (fallback §5.3).
        assert joined.startswith("<b>Первый абзац.</b>")
        assert "Второй абзац." in joined
        assert ctx.publish_message_id == 101          # первый чанк

    @pytest.mark.asyncio
    async def test_run_off_two_calls_and_no_loss(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {(CHAT, _FILTER_FLAG): False})
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", True)
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", False)
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: False)
        sent = []
        _capture_send_text(monkeypatch, sent)
        gen = _gen(FakeMemory(rows=_rows()), _TwoCallLLM())

        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)

        assert gen.llm.calls == 2                     # 2-вызовность OFF
        joined = "".join(item["text"] for item in sent)
        # Title из digest (rich-заголовок) → жирный в plain; H1 нет.
        assert "<b>Событие</b>" in joined
        assert "<h1>" not in joined
        done = _lines(caplog, "PUBLISH_TEXT_COMPLETE")
        assert done and f"run_id={_RID}" in done[0]
        assert "message_id=101" in done[0]            # первый чанк
        assert f"code=-" in _lines(caplog, "SUMMARY_COMPLETE")[0]
        assert "PUBLISH_RICH" not in caplog.text

    @pytest.mark.asyncio
    async def test_run_off_rich_integration(self, monkeypatch, tmp_path,
                                            caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {(CHAT, _FILTER_FLAG): False})
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", True)
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
        monkeypatch.setattr(Settings, "SUMMARY_COVER_FALLBACK_ENABLED", True)
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpeg")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(str(img), "ok")))
        monkeypatch.setattr(sg, "build_cover_media", MagicMock(return_value="M"))
        rich = AsyncMock(return_value=SimpleNamespace(message_id=777))
        monkeypatch.setattr(sg, "send_rich_message", rich)
        gen = _gen(FakeMemory(rows=_rows()), _TwoCallLLM())

        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)

        assert gen.llm.calls == 2
        rich.assert_awaited_once()
        html = rich.await_args.args[2]
        assert html.startswith(
            '<img src="tg://photo?id=summary_cover"><h1>Событие</h1><p>')
        assert rich.await_args.kwargs["content_format"] == "html"
        assert rich.await_args.kwargs["media"]
        # Нет отдельного сообщения с изображением (§104): send_photo не вызван.
        snap = egs.get_run(_RID)
        assert snap["publish_channel"] == "rich"
        assert snap["publish_status"] == "ok"
        assert snap["publish_message_id"] == 777
        graph = egs.build_graph(_RID, snap, [])
        assert graph["publication_status"] == "published_rich"
        assert graph["nodes"][-1]["kind"] == "publish"


# ══ SC-09: ON-путь (единая доставка, память, fail-closed) ══════════════════

class TestOnDelivery:
    @pytest.mark.asyncio
    async def test_on_two_calls_memorize_and_publish(self, monkeypatch,
                                                     caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True,
                                        (CHAT, _FILTER_FLAG): False})
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", False)
        memory = FakeMemory(rows=_rows())
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=[_L1_JSON, _L2_JSON])
        gen = _gen(memory, llm)
        sent = []
        _capture_send_text(monkeypatch, sent)
        tasks = []
        monkeypatch.setattr(sg, "fire_and_forget",
                            lambda coro, tag: tasks.append(asyncio.ensure_future(coro)))

        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)
        await asyncio.sleep(0)

        assert llm.generate.await_count == 2          # 2-вызовность ON
        for call in llm.generate.await_args_list:
            assert call.kwargs.get("correlation_id") == _RID
        # S-R1026S5-7: memorize_facts вызван на ON ровно 1 раз, те же строки.
        assert len(memory.memorized) == 1
        chat_id, batch, source = memory.memorized[0]
        from services.summary_memory import _build_batch_text
        assert chat_id == CHAT and source == "chat_history"
        assert batch == _build_batch_text(_rows(), skip_empty=True)
        assert len(tasks) == 1
        joined = "".join(item["text"] for item in sent)
        assert "<b>Тестовая статья</b>" in joined and "<h1>" not in joined
        done = _lines(caplog, "PUBLISH_TEXT_COMPLETE")
        assert done and "reason=plain" in done[0]

    @pytest.mark.asyncio
    async def test_on_rich_img_h1_p(self, monkeypatch, tmp_path, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True,
                                        (CHAT, _FILTER_FLAG): False})
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpeg")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(str(img), "ok")))
        monkeypatch.setattr(sg, "build_cover_media", MagicMock(return_value="M"))
        rich = AsyncMock(return_value=SimpleNamespace(message_id=555))
        monkeypatch.setattr(sg, "send_rich_message", rich)
        sent = []
        _capture_send_text(monkeypatch, sent)
        llm = MagicMock()
        # Реальный L1 (1 вызов) + реальный L2 (1 вызов) = 2-вызовность.
        llm.generate = AsyncMock(side_effect=[_L1_JSON_RICH, _L2_JSON])
        gen = _gen(FakeMemory(rows=_rows()), llm)
        gen._resolve_cover_style_text = AsyncMock(return_value="style")

        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)

        assert llm.generate.await_count == 2
        assert not sent                               # rich доставлен, plain нет
        rich.assert_awaited_once()
        html = rich.await_args.args[2]
        assert html.startswith(
            '<img src="tg://photo?id=summary_cover"><h1>Тестовая статья</h1><p>')
        assert "<b>Первый</b>" in html                # акцент абзаца
        snap = egs.get_run(_RID)
        assert snap["publish_channel"] == "rich"
        assert egs.build_graph(_RID, snap, [])["publication_status"] == \
            "published_rich"

    @pytest.mark.asyncio
    async def test_on_l1_not_usable_fail_closed(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})
        from services.summary_l1_contract import invalid_result

        async def fake_run_l1(**kwargs):
            return invalid_result("invalid_json")

        monkeypatch.setattr("services.summary_l1_clusterizer.run_l1",
                            fake_run_l1)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=_L2_JSON)
        gen = _gen(FakeMemory(rows=_rows()), llm)
        # Доставка не должна вызываться (fail-closed).
        gen._deliver_l2_plain = AsyncMock()
        gen._deliver_l2_rich = AsyncMock()

        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)

        assert llm.generate.await_count == 0          # L2 не вызван
        gen._deliver_l2_plain.assert_not_awaited()
        gen._deliver_l2_rich.assert_not_awaited()
        assert "PUBLISH_" not in caplog.text
        complete = _lines(caplog, "SUMMARY_COMPLETE")
        assert complete and "status=degraded" in complete[0]
        assert f"code={CODE_SUMMARY_GENERATION_FAILED}" in complete[0]

    @pytest.mark.asyncio
    async def test_on_parallel_memory_off_also_once(self, monkeypatch):
        """OFF-контур памяти не меняется: ровно один `memorize_facts`."""
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {(CHAT, _FILTER_FLAG): False})
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", False)
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: False)
        memory = FakeMemory(rows=_rows())
        gen = _gen(memory, _TwoCallLLM())
        _capture_send_text(monkeypatch, [])
        tasks = []
        monkeypatch.setattr(sg, "fire_and_forget",
                            lambda coro, tag: tasks.append(asyncio.ensure_future(coro)))
        await gen._run(CHAT, False)
        await asyncio.sleep(0)
        assert len(memory.memorized) == 1
        assert len(tasks) == 1


# ══ SC-07/§106: коды, fail-closed, bounded retry ═══════════════════════════

class TestFailureCodes:
    @pytest.mark.asyncio
    async def test_summary_generation_failed_llm(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {})
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        monkeypatch.setattr(Settings, "SUMMARY_RETRY_ONCE_PAUSE", 0)
        llm = MagicMock()
        llm.generate = AsyncMock(
            side_effect=LLMRateLimitError("rate limited (429) after 3 attempts"))
        gen = _gen(FakeMemory(rows=_rows()), llm)
        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)
        failed = _lines(caplog, "SUMMARY_FAILED")
        assert failed and f"code={CODE_SUMMARY_GENERATION_FAILED}" in failed[0]
        assert f"run_id={_RID}" in failed[0]

    @pytest.mark.asyncio
    async def test_summary_generation_failed_empty(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {})
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="   ")
        gen = _gen(FakeMemory(rows=_rows()), llm)
        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)
        complete = _lines(caplog, "SUMMARY_COMPLETE")
        assert complete and "status=empty" in complete[0]
        assert f"code={CODE_SUMMARY_GENERATION_FAILED}" in complete[0]

    @pytest.mark.asyncio
    async def test_cover_error_code_on_exception(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        gen._resolve_cover_style_text = AsyncMock(return_value="style")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(side_effect=RuntimeError("boom")))
        sent = []
        _capture_send_text(monkeypatch, sent)
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._deliver_rich(CHAT, _NARRATOR, "prompt",
                                    correlation_id=_RID, ctx=ctx,
                                    title="Событие")
        err = _lines(caplog, "COVER_ERROR")
        assert err and f"code={CODE_COVER_GENERATION_FAILED}" in err[0]
        assert "error_type=RuntimeError" in err[0]
        assert ctx.cover_status == "unavailable"
        assert sent                                   # текст опубликован plain

    @pytest.mark.asyncio
    async def test_rich_send_failed_code_and_plain_fallback(
            self, monkeypatch, tmp_path, caplog):
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        gen._resolve_cover_style_text = AsyncMock(return_value="style")
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpeg")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(str(img), "ok")))
        monkeypatch.setattr(sg, "build_cover_media", MagicMock(return_value="M"))

        async def _boom(*a, **kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(sg, "send_rich_message", _boom)
        sent = []
        _capture_send_text(monkeypatch, sent)
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._deliver_rich(CHAT, _NARRATOR, "a lot",
                                    correlation_id=_RID, ctx=ctx)
        err = _lines(caplog, "PUBLISH_RICH_ERROR")
        assert err and f"code={CODE_RICH_MESSAGE_SEND_FAILED}" in err[0]
        assert "error_type=RuntimeError" in err[0]
        assert sent                                   # plain-фолбэк
        assert ctx.publish_status in ("ok",)          # финальный plain удался
        assert _lines(caplog, "PUBLISH_TEXT_COMPLETE")

    @pytest.mark.asyncio
    async def test_text_fallback_failed(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)

        async def _always_retry(*a, **kw):
            raise TelegramRetryAfter(method=MagicMock(), message="retry",
                                     retry_after=0)

        monkeypatch.setattr(sg, "send_text", _always_retry)
        gen = _gen(FakeMemory(), MagicMock())
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._deliver_plain(CHAT, "Текст без разметки.",
                                     correlation_id=_RID, ctx=ctx)
        err = _lines(caplog, "PUBLISH_TEXT_ERROR")
        assert err and f"code={CODE_TEXT_FALLBACK_FAILED}" in err[0]
        assert "error_type=TelegramRetryAfter" in err[0]
        assert ctx.status == STATUS_FAILED
        assert ctx.code == CODE_TEXT_FALLBACK_FAILED
        assert ctx.publish_status == "failed"

    @pytest.mark.asyncio
    async def test_run_text_fallback_failed_summary_failed(
            self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {(CHAT, _FILTER_FLAG): False})
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", True)
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", False)
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: False)

        async def _always_retry(*a, **kw):
            raise TelegramRetryAfter(method=MagicMock(), message="retry",
                                     retry_after=0)

        monkeypatch.setattr(sg, "send_text", _always_retry)
        gen = _gen(FakeMemory(rows=_rows()), _TwoCallLLM())
        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)
        failed = _lines(caplog, "SUMMARY_FAILED")
        assert failed and f"code={CODE_TEXT_FALLBACK_FAILED}" in failed[0]
        assert "stage=publish" in failed[0]
        # Публикации нет (оба канала упали) — snapshot честен.
        assert egs.get_run(_RID)["publish_status"] == "failed"
        assert egs.build_graph(_RID, egs.get_run(_RID), []) \
            ["publication_status"] == "failed"


class TestBoundedRetry:
    @pytest.mark.asyncio
    async def test_rich_forever_retry_exactly_two_attempts(
            self, monkeypatch, caplog, tmp_path):
        """«Вечно RetryAfter»: rich ≤2 попытки (1 + 1 retry), затем plain."""
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        gen._resolve_cover_style_text = AsyncMock(return_value="style")
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpeg")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(str(img), "ok")))
        monkeypatch.setattr(sg, "build_cover_media", MagicMock(return_value="M"))
        calls = {"n": 0}

        async def _retry_then_fail(*a, **kw):
            calls["n"] += 1
            raise TelegramRetryAfter(method=MagicMock(), message="retry",
                                     retry_after=0)

        monkeypatch.setattr(sg, "send_rich_message", _retry_then_fail)
        sent = []
        _capture_send_text(monkeypatch, sent)
        with caplog.at_level(logging.INFO):
            await gen._deliver_rich(CHAT, _NARRATOR, "prompt",
                                    correlation_id=_RID)
        assert calls["n"] == 2                        # 1 + ровно 1 retry
        assert _lines(caplog, "PUBLISH_RICH_ERROR")
        assert sent                                   # текст не потерян

    @pytest.mark.asyncio
    async def test_plain_chunk_retry_after_once(self, monkeypatch):
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        calls = {"n": 0}

        async def _retry_then_ok(bot, chat_id, text, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TelegramRetryAfter(method=MagicMock(), message="retry",
                                         retry_after=0)
            return SimpleNamespace(message_id=42)

        monkeypatch.setattr(sg, "send_text", _retry_then_ok)
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        await gen._deliver_plain(CHAT, "Короткий текст",
                                 correlation_id=_RID, ctx=ctx)
        assert calls["n"] == 2                        # чанк ≤2 попытки
        assert ctx.publish_message_id == 42

    @pytest.mark.asyncio
    async def test_plain_forever_retry_bounded(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        calls = {"n": 0}

        async def _forever(bot, chat_id, text, **kw):
            calls["n"] += 1
            raise TelegramRetryAfter(method=MagicMock(), message="retry",
                                     retry_after=0)

        monkeypatch.setattr(sg, "send_text", _forever)
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._deliver_plain(CHAT, "Короткий текст",
                                     correlation_id=_RID, ctx=ctx)
        # HTML: 2 попытки → даунгрейд; финальный текст: 2 попытки → стоп.
        assert calls["n"] == 4
        assert _lines(caplog, "PUBLISH_TEXT_ERROR")
        assert ctx.code == CODE_TEXT_FALLBACK_FAILED


# ══ SC-20: no-loss и message_id первого чанка ══════════════════════════════

class TestNoLossPublication:
    @pytest.mark.asyncio
    async def test_multi_chunk_no_loss_first_message_id(self, monkeypatch,
                                                        caplog):
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        doc = {
            "schema_version": 1, "title": "Заголовок",
            "paragraphs": [
                {"text": "А" * 3000, "emphasis": None},
                {"text": "Б" * 3000, "emphasis": None},
            ],
        }
        sent = []
        _capture_send_text(monkeypatch, sent)
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._publish_plain_document(
                CHAT, doc, correlation_id=_RID, ctx=ctx, reason="plain")
        assert len(sent) >= 2
        joined = "\n\n".join(item["text"] for item in sent)
        # Каждый абзац доставлен ровно один раз (no-loss, SC-20).
        assert joined.count("А" * 3000) == 1
        assert joined.count("Б" * 3000) == 1
        assert joined.count("<b>Заголовок</b>") == 1
        done = _lines(caplog, "PUBLISH_TEXT_COMPLETE")
        assert done and f"message_id={ctx.publish_message_id}" in done[0]
        assert ctx.publish_message_id == 100 + 1      # id первого чанка

    @pytest.mark.asyncio
    async def test_plain_600_paragraphs_delivered_no_loss(self, monkeypatch,
                                                          caplog):
        """B-R1026S6-1 (проба a): 600 абзацев через `_deliver_plain` — каждый
        доставлен ровно один раз (ранее кап 498 терял 101 без WARN)."""
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        text = "\n\n".join(f"Абзац {i}. " + "я" * 60 for i in range(600))
        sent = []
        _capture_send_text(monkeypatch, sent)
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._deliver_plain(CHAT, text, correlation_id=_RID, ctx=ctx)
        joined = "\n\n".join(item["text"] for item in sent)
        missing = [i for i in range(600)
                   if joined.count(f"Абзац {i}.") != 1]
        assert missing == []
        assert ctx.publish_channel == "text" and ctx.publish_status == "ok"
        done = _lines(caplog, "PUBLISH_TEXT_COMPLETE")
        assert done and f"message_id={ctx.publish_message_id}" in done[0]
        assert ctx.publish_message_id == 101          # id первого чанка

    @pytest.mark.asyncio
    async def test_rich_char_overflow_plain_fallback_full_text(
            self, monkeypatch, tmp_path, caplog):
        """B-R1026S6-1 (проба b): rich >32000 символов — без среза: явный
        WARN с числами (R17-safe) и plain-фолбэк с полным текстом."""
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        gen._resolve_cover_style_text = AsyncMock(return_value="style")
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpeg")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(str(img), "ok")))
        monkeypatch.setattr(sg, "build_cover_media", MagicMock(return_value="M"))
        rich = AsyncMock(return_value=SimpleNamespace(message_id=7))
        monkeypatch.setattr(sg, "send_rich_message", rich)
        sent = []
        _capture_send_text(monkeypatch, sent)
        doc = {"schema_version": 1, "title": "Заголовок",
               "paragraphs": [{"text": f"Фрагмент {i}: " + "я" * 800,
                               "emphasis": None} for i in range(45)]}
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._publish_rich_document(
                CHAT, doc, "prompt", correlation_id=_RID, ctx=ctx)
        rich.assert_not_awaited()                    # rich не отправлялся
        joined = "".join(item["text"] for item in sent)
        missing = [i for i in range(45) if f"Фрагмент {i}:" not in joined]
        assert missing == []
        warn = [r.getMessage() for r in caplog.records
                if "exceeds limits" in r.getMessage()]
        assert warn and "reason=rich_char_limit" in warn[0]
        assert "paragraphs=45" in warn[0] and "max_chars=32000" in warn[0]
        fmt_err = _lines(caplog, "FORMAT_ERROR")
        assert fmt_err and "reason=rich_char_limit" in fmt_err[0]
        assert not _lines(caplog, "PUBLISH_RICH_START")  # rich не стартовал
        pub = _lines(caplog, "PUBLISH_TEXT_COMPLETE")
        assert pub and "reason=rich_overflow" in pub[0]
        assert ctx.publish_channel == "text" and ctx.publish_status == "ok"
        assert ctx.publish_message_id == 101         # первый чанк plain

    @pytest.mark.asyncio
    async def test_rich_paragraph_overflow_plain_fallback_full_text(
            self, monkeypatch, tmp_path, caplog):
        """B-R1026S6-1: >498 абзацев (лимит 500 блоков Telegram) — rich не
        шлём, plain доставляет весь текст (ранее терялся хвост)."""
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        gen._resolve_cover_style_text = AsyncMock(return_value="style")
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpeg")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(str(img), "ok")))
        monkeypatch.setattr(sg, "build_cover_media", MagicMock(return_value="M"))
        rich = AsyncMock(return_value=SimpleNamespace(message_id=7))
        monkeypatch.setattr(sg, "send_rich_message", rich)
        sent = []
        _capture_send_text(monkeypatch, sent)
        doc = {"schema_version": 1, "title": "Заголовок",
               "paragraphs": [{"text": f"Абзац {i}.", "emphasis": None}
                              for i in range(600)]}
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._publish_rich_document(
                CHAT, doc, "prompt", correlation_id=_RID, ctx=ctx)
        rich.assert_not_awaited()
        joined = "".join(item["text"] for item in sent)
        missing = [i for i in range(600)
                   if joined.count(f"Абзац {i}.") != 1]
        assert missing == []
        warn = [r.getMessage() for r in caplog.records
                if "exceeds limits" in r.getMessage()]
        assert warn and "reason=rich_paragraph_limit" in warn[0]
        assert "paragraphs=600" in warn[0] and "max_paragraphs=498" in warn[0]
        assert _lines(caplog, "PUBLISH_TEXT_COMPLETE")

    @pytest.mark.asyncio
    async def test_plain_delivery_renders_paragraph_emphasis(
            self, monkeypatch, caplog):
        """B-R1026S6-2: plain-доставка (ON-обёртка) рендерит абзацный
        `<b>`-акцент; заголовок — тоже `<b>`, настоящего H1 нет."""
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        sent = []
        _capture_send_text(monkeypatch, sent)
        doc = {"schema_version": 1, "title": "Тестовая статья",
               "paragraphs": [
                   {"text": "Первый абзац статьи.", "emphasis": "Первый"},
                   {"text": "Второй абзац без акцента.", "emphasis": None},
               ]}
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._deliver_l2_plain(CHAT, doc, _RID, ctx=ctx)
        joined = "\n\n".join(item["text"] for item in sent)
        assert "<b>Тестовая статья</b>" in joined
        assert "<b>Первый</b>" in joined             # акцент абзаца
        assert "<h1>" not in joined
        assert all(item["kw"].get("parse_mode") == "HTML" for item in sent)
        pub = _lines(caplog, "PUBLISH_TEXT_COMPLETE")
        assert pub and "reason=plain" in pub[0]


# ══ SC-10/SC-11: PUBLISH_* / publish-статус / R17 ══════════════════════════

class TestPublishObservability:
    def test_graph_records_publish_fields(self):
        ctx = RunContext(run_id="r1", chat_id=CHAT)
        ctx.publish_channel = "text"
        ctx.publish_status = "ok"
        ctx.publish_duration_ms = 12.0
        ctx.publish_message_id = 9
        egs.record_run_from_context(ctx)
        snap = egs.get_run("r1")
        assert snap["publish_channel"] == "text"
        assert snap["publish_status"] == "ok"
        assert snap["publish_message_id"] == 9
        graph = egs.build_graph("r1", snap, [])
        assert graph["nodes"][-1]["kind"] == "publish"
        assert graph["nodes"][-1]["metrics"]["message_id"] == 9
        assert graph["publication_status"] == "published_text"

    def test_skipped_when_run_failed(self):
        ctx = RunContext(run_id="r2", chat_id=CHAT)
        ctx.status = STATUS_DEGRADED
        egs.record_run_from_context(ctx)
        assert egs.build_graph("r2", egs.get_run("r2"), [])[
            "publication_status"] == "skipped"

    def test_no_data_none_not_gated(self):
        assert egs.build_graph("r3", None, [])["publication_status"] is None

    @pytest.mark.asyncio
    async def test_publish_events_r17_no_raw_text(self, monkeypatch,
                                                  tmp_path, caplog):
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        gen._resolve_cover_style_text = AsyncMock(return_value="style")
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpeg")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(str(img), "ok")))
        monkeypatch.setattr(sg, "build_cover_media", MagicMock(return_value="M"))
        monkeypatch.setattr(sg, "send_rich_message",
                            AsyncMock(return_value=SimpleNamespace(message_id=5)))
        with caplog.at_level(logging.INFO):
            await gen._deliver_rich(CHAT, _SECRET_TEXT, "prompt",
                                    correlation_id=_RID, title="Т")
        assert _SECRET_TEXT not in caplog.text
        pub_lines = _lines(caplog, "PUBLISH_RICH_START")
        assert pub_lines
        for line in pub_lines:
            assert f"run_id={_RID}" in line
            assert "chat_id=" in line and "method=" in line
        done = _lines(caplog, "PUBLISH_RICH_COMPLETE")
        assert done and "duration_ms=" in done[0]
        assert _SECRET_TEXT not in done[0]


# ══ SC-04/§103: утверждения и лимиты (документируемые, проверяемые) ════════

class TestSpec103Statements:
    def test_limits_are_source_of_truth(self):
        # spec §8: лимиты Rich Message 32 768/500/16/50/20; rich-кап форматтера
        # 32 000 ≤ 32 768; абзацев ≤ 498; plain-чанк 4096.
        assert RICH_MAX_CHARS == 32000
        assert MAX_PARAGRAPHS_HARD == 498
        assert sg.hot.get("limits.max_summary_parts",
                          Settings.MAX_SUMMARY_PARTS) * 4000 - 200 < 32768

    def test_send_message_limit_plain_chunks(self):
        doc = {"schema_version": 1, "title": "",
               "paragraphs": [{"text": "х" * 9000, "emphasis": None}]}
        chunks = chunk_plain_blocks(doc, limit=4096)
        assert chunks and all(len(c) <= 4096 for c in chunks)
        assert "".join(c for c in chunks).count("х") == 9000

    def test_no_doc_copies_in_prompt_sources(self):
        # §103: документация Telegram в промпт не копируется; разметка — код.
        src = (ROOT / "services" / "summary_prompts.py").read_text(
            encoding="utf-8")
        assert "core.telegram.org" not in src
        assert "InputRichBlockSectionHeading" not in src


# ══ SC-12/SC-13/SC-14/SC-17: границы ═══════════════════════════════════════

class TestBoundaries:
    @pytest.mark.asyncio
    async def test_dry_run_no_publish_events(self, monkeypatch, caplog):
        from tests.test_summary_test_run import (
            CHAT_ID as DRY_CHAT, L1_JSON, L2_JSON, _fake_llm,
            _real_generator, _rows as _dry_rows,
        )
        from services.summary_test_run import run_summary_test

        _patch_chat_limit(monkeypatch, {})
        gen = _real_generator(_dry_rows(), _fake_llm([L1_JSON, L2_JSON]))
        with caplog.at_level(logging.INFO):
            result = await run_summary_test(
                DRY_CHAT, {"hours": 24}, generator=gen,
                correlation_id=_RID, pg=None)
        assert result.status == "ok"
        assert "PUBLISH_" not in caplog.text
        assert result.publication["status"] == "not_published"

    def test_viewer_markers_and_labels(self):
        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        assert "'PUBLISH_'" in app_js                  # §110-маркер
        assert "PUBLISH_RICH_ERROR" in app_js          # подпись ошибки
        assert "PUBLISH_TEXT_ERROR" in app_js
        assert "недоступна (гейт S6)" not in app_js
        assert "'published_rich'" in app_js
        assert "logSummaryMarkers" in app_js

    def test_no_second_rich_mechanism(self):
        src = (ROOT / "services" / "summary_generator.py").read_text(
            encoding="utf-8")
        assert "build_cover_article_html" not in src   # саммари-путь её не зовёт
        assert "send_rich_message" in src              # reuse обёртки
        assert "send_photo" not in src                 # отдельного image-сообщения нет

    def test_no_new_llm_calls_in_formatter(self):
        src = (ROOT / "services" / "summary_article_formatter.py").read_text(
            encoding="utf-8")
        for marker in ("llm", "generate(", "httpx", "requests", "async def"):
            assert marker not in src, f"форматтер обязан быть чистым: {marker}"

    def test_no_ddl_in_touched_sources(self):
        for name in ("services/summary_generator.py",
                     "services/summary_article_formatter.py",
                     "services/summary_run_log.py",
                     "services/execution_graph_source.py"):
            src = (ROOT / name).read_text(encoding="utf-8")
            assert not re.search(
                r"\b(CREATE\s+TABLE|ALTER\s+TABLE|CREATE\s+INDEX)", src,
                re.IGNORECASE), name

    def test_catalog_zero_delta(self):
        assert len(pc.REGISTRY) == 473
        assert len({f.name for f in dataclasses.fields(Settings)}) == 430
        assert len([s for s in pc.REGISTRY.values()
                    if s.category is not None]) == 448
        assert len(pc.GROUPS) == 102
        assert len(pc._TAB_BY_GROUP) == 100
        assert len(pc.TAB_RULES) == 21

    def test_app_version(self):
        assert APP_VERSION == "2.58.31"
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "v2.58.31" in readme

    def test_analytics_docstring_only_changed(self):
        """web/api/analytics.py: S6 меняет только docstring (код эндпоинта —
        pass-through `build_graph`, D1/ADR-1026-11)."""
        try:
            old = subprocess.run(
                ["git", "show", "pre-round1026-s6:web/api/analytics.py"],
                cwd=str(ROOT), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30)
        except Exception:      # pragma: no cover - git недоступен
            pytest.skip("git недоступен — аудит пропущен")
        if old.returncode != 0:
            pytest.skip("базовый тег недоступен — аудит пропущен")

        def _strip_docstrings(source: str) -> str:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                    body = node.body
                    if (body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)
                            and isinstance(body[0].value.value, str)):
                        node.body = body[1:] or [ast.Pass()]
            return ast.dump(tree, annotate_fields=True)

        current = (ROOT / "web" / "api" / "analytics.py").read_text(
            encoding="utf-8")
        assert _strip_docstrings(old.stdout) == _strip_docstrings(current)

    def test_forbidden_paths_outside_diff(self):
        # NOTE (A2, ADR-1026-15 D5): `bot.py` исключён — A2 санкционировал там
        # аддитивную DI-строку `extractor=_web_extractor` (reuse
        # WebContentExtractor для `fetch_article`); больше bot.py A2 не менял.
        forbidden = [
            "services/telegram_send.py",
            # NOTE (A3, ADR-1026-16 D2/D6): `services/image_generation.py`
            # исключён — санction A3 (ImageRequest-контракт); §104 гейтится
            # AST-гейтом A3 (test_unified_image_request_round1026.py).
            "services/summary_prompts.py", "services/summary_test_run.py",
            "web/api/routes.py", "db",
            # NOTE (A5, ADR-1026-17 D9): `services/param_catalog.py` исключён —
            # A5 санкционирует Δ каталога +1 ParamSpec +1 GroupSpec.
        ]
        try:
            proc = subprocess.run(
                ["git", "diff", "--name-only", "pre-round1026-s6",
                 "--", *forbidden],
                cwd=str(ROOT), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30)
        except Exception:      # pragma: no cover - git недоступен
            pytest.skip("git недоступен — diff-аудит пропущен")
        if proc.returncode != 0:
            pytest.skip("базовый тег недоступен — diff-аудит пропущен")
        changed = [line.strip() for line in proc.stdout.splitlines()
                   if line.strip()]
        assert changed == [], f"запрещённые пути изменены: {changed}"
