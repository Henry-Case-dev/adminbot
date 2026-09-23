"""S5 round1026 (ADR-1026-7 D2) — тесты серверного форматтера §98/§101/§102/§105.

Покрытие: SC-01/SC-03/SC-04 (rich HTML, H1, ``<p>``/``<b>``, экранирование),
SC-05 (plain + разбивка), SC-12 (детерминизм).
"""
from __future__ import annotations

from services.summary_article_formatter import (
    RICH_MAX_CHARS,
    chunk_plain_blocks,
    format_plain_html,
    format_plain_text,
    format_rich_html,
)


def _doc(title="Дождливый день", paragraphs=None) -> dict:
    if paragraphs is None:
        paragraphs = [
            {"text": "В чате обсудили погоду.", "emphasis": None},
            {"text": "Главная тема — сильный дождь.", "emphasis": "дождь"},
        ]
    return {"schema_version": 1, "title": title, "paragraphs": paragraphs}


def _no_sanitize(text: str) -> str:
    return text


# ── SC-03/SC-04: rich HTML §101/§102 ───────────────────────────────────────

class TestRich:
    def test_real_h1_not_bold(self):
        out = format_rich_html(_doc(), sanitize=_no_sanitize)
        assert out.startswith("<h1>Дождливый день</h1>")
        assert "<b>Дождливый день</b>" not in out

    def test_paragraphs_and_emphasis(self):
        out = format_rich_html(_doc(), sanitize=_no_sanitize)
        assert "<p>В чате обсудили погоду.</p>" in out
        assert "<p>Главная тема — сильный <b>дождь</b>.</p>" in out

    def test_cover_img_first(self):
        out = format_rich_html(_doc(), cover_id="summary_cover",
                               sanitize=_no_sanitize)
        assert out.startswith('<img src="tg://photo?id=summary_cover">')

    def test_emphasis_not_substring_ignored(self):
        doc = _doc(paragraphs=[{"text": "Текст.", "emphasis": "нет"}])
        out = format_rich_html(doc, sanitize=_no_sanitize)
        assert "<b>" not in out

    def test_only_allowed_tags(self):
        import re
        out = format_rich_html(_doc(), cover_id="c", sanitize=_no_sanitize)
        tags = set(re.findall(r"</?([a-zA-Z0-9]+)", out))
        assert tags <= {"img", "h1", "p", "b"}

    def test_escaping_special_chars(self):
        doc = _doc(title="A < B & C > D",
                   paragraphs=[{"text": '<script>"x"</script>', "emphasis": None}])
        out = format_rich_html(doc, sanitize=_no_sanitize)
        assert "&lt;" in out and "&amp;" in out and "&gt;" in out
        assert "<script>" not in out
        assert "&quot;" in out            # quote=True

    def test_unicode_and_emoji_preserved(self):
        doc = _doc(title="Привет 😀",
                   paragraphs=[{"text": "ёлка «ёлочка» — тире", "emphasis": None}])
        out = format_rich_html(doc, sanitize=_no_sanitize)
        assert "😀" in out and "ёлочка" in out

    def test_deterministic_double_run(self):
        a = format_rich_html(_doc(), cover_id="c", sanitize=_no_sanitize)
        b = format_rich_html(_doc(), cover_id="c", sanitize=_no_sanitize)
        assert a == b

    def test_no_markdown_headings_or_bullets(self):
        doc = _doc(paragraphs=[{"text": "# Заголовок\n- пункт", "emphasis": None}])
        out = format_rich_html(doc, sanitize=_no_sanitize)
        assert "# Заголовок" not in out
        assert "- пункт" not in out
        assert "**" not in out

    def test_rich_cap_drops_tail_paragraphs(self):
        paragraphs = [{"text": "я" * 890, "emphasis": None} for _ in range(45)]
        out = format_rich_html(_doc(paragraphs=paragraphs), sanitize=_no_sanitize)
        assert len(out) <= RICH_MAX_CHARS + 64   # грубая граница блока


# ── SC-05: plain §105 ──────────────────────────────────────────────────────

class TestPlain:
    def test_plain_html_bold_title(self):
        out = format_plain_html(_doc(), sanitize=_no_sanitize)
        assert out.startswith("<b>Дождливый день</b>")
        assert "<h1>" not in out

    def test_plain_html_emphasis(self):
        out = format_plain_html(_doc(), sanitize=_no_sanitize)
        assert "<b>дождь</b>" in out

    def test_plain_text_no_markup(self):
        out = format_plain_text(_doc())
        assert "<b>" not in out and "<h1>" not in out
        assert "Дождливый день" in out

    def test_chunk_by_paragraphs(self):
        paragraphs = [{"text": f"Абзац {i} " + "я" * 100, "emphasis": None}
                      for i in range(40)]
        chunks = chunk_plain_blocks(_doc(paragraphs=paragraphs), limit=4096)
        assert all(len(chunk) <= 4096 for chunk in chunks)
        # Ни один текст не потерян.
        joined = "".join(chunks)
        for i in range(40):
            assert f"Абзац {i}" in joined

    def test_chunk_empty_document(self):
        assert chunk_plain_blocks({}, limit=4096) == []

    def test_chunk_does_not_split_html_entity(self):
        # S-R1026S5-4: вынужденная нарезка не рвёт HTML-сущность.
        doc = _doc(title="t", paragraphs=[
            {"text": "<script>alert(1)</script>" + "x" * 40,
             "emphasis": None}])
        chunks = chunk_plain_blocks(doc, limit=20)
        joined = "".join(chunks)
        # Экранированные сущности сохранены целиком (нет разорванных `&…`).
        assert "&lt;script&gt;" in joined
        for chunk in chunks:
            assert "&" not in chunk or ";" in chunk.split("&", 1)[1]
