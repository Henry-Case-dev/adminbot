"""ASAP-2.1 — T-3988: тесты детерминированного Rich cut (§28, ADR-1028-1 D4).

Сценарии владельца §28:3541–3570:
  1. один body paragraph → title + paragraph, без искусственного ката;
  2. два абзаца → p1 виден, p2 внутри закрытого cut;
  3. много абзацев → p1 виден, 2..N внутри ОДНОГО закрытого cut, ничего
     не потеряно;
  4. rich failure → plain fallback содержит ВСЮ статью.
"""
import re

import pytest

from services.summary_article_formatter import (
    chunk_plain_blocks,
    format_plain_html,
    format_plain_text,
    format_rich_html,
    rich_document_limits,
)
from services.summary_generator import SummaryGenerator
from services.summary_xml import XmlGroundingBuilder


class FakeMemory:
    def __init__(self, rows):
        self.rows = rows
        self.writes = 0


def _doc(paragraphs, finale=None):
    return {
        "schema_version": 1,
        "title": "Заголовок статьи",
        "paragraphs": [{"text": t, "emphasis": None} for t in paragraphs],
        **({"finale": finale} if finale else {}),
    }


async def _noop(*a, **k):
    return None


def _count_details(html):
    return html.count("<details>") + html.count("<details ")


# ── §28.1: один абзац — ката нет ───────────────────────────────────────────

def test_single_paragraph_no_cut():
    doc = _doc(["Единственный абзац статьи."])
    html = format_rich_html(doc, cover_id="cov")
    assert "<details" not in html
    assert "<h1>Заголовок статьи</h1>" in html
    assert "<p>Единственный абзац статьи.</p>" in html
    # Весь текст присутствует (ничего не потеряно).
    assert "Единственный абзац статьи." in html


def test_zero_paragraphs_no_cut():
    doc = _doc([])
    html = format_rich_html(doc, cover_id=None)
    assert "<details" not in html


# ── §28.2: два абзаца — p1 виден, p2 под закрытым cut ──────────────────────

def test_two_paragraphs_second_under_closed_cut():
    doc = _doc(["Первый абзац.", "Второй абзац."])
    html = format_rich_html(doc, cover_id=None)
    assert _count_details(html) == 1
    assert html.count("</details>") == 1
    # Закрытый cut: атрибут open НЕ ставится.
    assert re.search(r"<details[^>]*\bopen\b", html) is None
    assert "<summary>Читать дальше</summary>" in html
    # p1 ВНЕ details, p2 ВНУТРИ.
    before, after = html.split("<details>", 1)
    assert "<p>Первый абзац.</p>" in before
    assert "<p>Второй абзац.</p>" in after
    assert "<p>Первый абзац.</p>" not in after


# ── §28.3: много абзацев — один cut, ничего не потеряно ────────────────────

def test_many_paragraphs_single_cut_keeps_all():
    paras = [f"Абзац номер {i}." for i in range(1, 11)]
    doc = _doc(paras, finale="Главным шизом объявляется Лёха.")
    html = format_rich_html(doc, cover_id="cov")
    assert _count_details(html) == 1
    # Ничего не потеряно: все 10 абзацев + finale в HTML.
    for p in paras:
        assert f"<p>{p}</p>" in html
    assert "Главным шизом объявляется Лёха." in html
    # p1 вне cut; finale внутри cut (всё после 1-го абзаца под одним cat'ом).
    before, after = html.split("<details>", 1)
    assert "<p>Абзац номер 1.</p>" in before
    assert "Главным шизом объявляется Лёха." in after


def test_finale_visible_without_cut_single_paragraph():
    doc = _doc(["Один абзац."], finale="Главным шизом объявляется Кот.")
    html = format_rich_html(doc, cover_id=None)
    assert "<details" not in html
    assert "Главным шизом объявляется Кот." in html


def test_cut_is_presentation_layer_document_untouched():
    doc = _doc(["a", "b", "c"])
    snapshot = repr(doc)
    format_rich_html(doc, cover_id=None)
    assert repr(doc) == snapshot        # документ не мутируется


# ── plain-каналы: полный текст без ката ────────────────────────────────────

def test_plain_html_full_text_no_cut():
    paras = [f"Абзац {i}." for i in range(1, 6)]
    doc = _doc(paras, finale="Финальная строка.")
    html = format_plain_html(doc)
    assert "<details" not in html
    for p in paras:
        assert p in html
    assert "Финальная строка." in html


def test_plain_chunks_no_loss():
    paras = [f"Абзац {i}." for i in range(1, 6)]
    doc = _doc(paras, finale="Финальная строка.")
    chunks = chunk_plain_blocks(doc, limit=4096)
    joined = "\n\n".join(chunks)
    for p in paras:
        assert p in joined
    assert "Финальная строка." in joined


def test_plain_text_full_text():
    doc = _doc(["Один.", "Два."], finale="Финал.")
    text = format_plain_text(doc)
    assert "<details" not in text
    assert "Один." in text and "Два." in text and "Финал." in text


# ── limits: обёртка cut не ломает семантику fail-closed ────────────────────

def test_rich_document_limits_counts_full_html():
    paras = [f"Абзац {i}." for i in range(1, 5)]
    doc = _doc(paras)
    plan = rich_document_limits(doc, cover_id=None)
    assert plan["fits"] is True
    assert plan["paragraphs"] == 4
    # rich-HTML содержит details-обёртку, лимит считается по фактическому HTML.
    assert "<details>" in plan["html"]
    assert plan["html_len"] == len(plan["html"])


def test_too_long_still_fails_closed():
    doc = _doc(["x" * 950 for _ in range(60)])
    plan = rich_document_limits(doc, cover_id=None)
    assert plan["fits"] is False
    assert plan["reason"] in ("rich_char_limit", "rich_paragraph_limit")


# ── §28.4: rich failure → plain fallback со ВСЕЙ статьёй ──────────────────

@pytest.mark.asyncio
async def test_rich_send_failure_plain_fallback_full_article(monkeypatch):
    """RichMessage упала → обычный sendMessage получает ПОЛНЫЙ текст статьи
    (инвариант §1:2837; cut — только rich-presentation)."""
    import services.summary_generator as sg

    doc = _doc(["Первый абзац статьи.", "Второй абзац статьи.",
                "Третий абзац статьи."], finale="Финал статьи.")

    sent = []

    async def _capture_send(bot, chat_id, text, **kw):
        sent.append(text)
        return type("Msg", (), {"message_id": 1})()

    async def _fail_rich(*a, **k):
        raise RuntimeError("rich send failed")

    async def _fail_image(*a, **k):
        return ("", "error")           # обложка недоступна → plain fallback

    monkeypatch.setattr(sg, "send_text", _capture_send)
    monkeypatch.setattr(sg, "send_rich_message", _fail_rich)
    monkeypatch.setattr(sg, "generate_image_verbose", _fail_image)

    gen = SummaryGenerator(FakeMemory(rows=[]), XmlGroundingBuilder(), None,
                           None)
    # cover_prompt непустой → rich-ветка; обложка падает → plain-фолбэк
    # с ПОЛНЫМ текстом (инвариант §1:2837/§28.4).
    published = await gen._publish_rich_document(
        -100, doc, cover_prompt="тест визуальный промпт",
        correlation_id="r-cut")
    assert published is True             # текст доставлен plain-каналом
    assert sent, "plain fallback должен был отправить текст"
    joined = "\n\n".join(sent)
    assert "<details" not in joined       # plain-канал без ката
    for para in ("Первый абзац статьи.", "Второй абзац статьи.",
                 "Третий абзац статьи."):
        assert para in joined
    assert "Финал статьи." in joined
