"""F6 (10.23, ADR-1023-6) — обложки саммари + Rich Article, тихий фолбэк.

Покрытие:
  * ``normalize_cover_prompt``: пусто/None/не-строка → ""; схлопывание
    пробелов/``\\n``; обрезка ≤300 по слову; идемпотентность;
  * разбор Stage-1 JSON с ``cover_prompt`` (отсутствие → "");
  * конкатенация «стиль + visual prompt» с финальным капом 300;
  * Article: ``html``-режим, ``<img src="tg://photo?id=summary_cover">``,
    экранирование, exactly-one-of;
  * guard ``_rich_media_supported`` (нет media → plain);
  * тихий фолбэк: ``generate_image → None`` / ``TelegramBadRequest`` /
    любое исключение → plain, без ``_send_ux``;
  * даунгрейд rich → plain (таблицы/HTML снимаются).
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from config.settings import Settings
from services import summary_generator as sg
from services.summary_generator import (
    SummaryDraft,
    SummaryGenerator,
    compose_cover_image_prompt,
    downgrade_rich_to_plain,
)
from services.system2_handoff import (
    COVER_PROMPT_MAX,
    normalize_cover_prompt,
    parse_summary_handoff,
)
from services.telegram_send import SUMMARY_COVER_MEDIA_ID, build_cover_article_html

pytestmark = pytest.mark.system2

_DIGEST = "# Тема\n| a | b |\n|---|---|"


def _two_call_llm(cover_prompt="a lone cat on a neon rooftop", mode="deep_research"):
    class _LLM:
        def __init__(self):
            self.calls = 0

        async def generate(self, messages):
            self.calls += 1
            if self.calls == 1:
                return json.dumps({"response_mode": mode, "digest": _DIGEST,
                                   "cover_prompt": cover_prompt})
            return "богатый дерзкий рассказ"

    return _LLM()


def _make_generator(llm):
    from tests.test_summary_generator import FakeMemory, _row
    from services.summary_xml import XmlGroundingBuilder

    return SummaryGenerator(FakeMemory(rows=[_row(author_name="вася")]),
                            XmlGroundingBuilder(), llm, AsyncMock())


# ── A. normalize_cover_prompt ────────────────────────────────────────

class TestNormalizeCoverPrompt:
    @pytest.mark.parametrize("value", [None, "", "   ", 42, [], {}])
    def test_non_string_or_empty_is_empty(self, value):
        assert normalize_cover_prompt(value) == ""

    def test_collapses_whitespace_and_newlines(self):
        assert normalize_cover_prompt("  a   cat\n\non  a   roof ") == \
            "a cat on a roof"

    def test_truncates_to_300_by_word(self):
        text = "word " * 100
        out = normalize_cover_prompt(text)
        assert len(out) <= COVER_PROMPT_MAX
        assert not out.endswith(" ")
        # обрезка по границе слова — не рвёт слово
        assert set(out.split()) == {"word"}

    def test_short_text_untouched(self):
        assert normalize_cover_prompt("cinematic sunset") == "cinematic sunset"

    def test_idempotent(self):
        once = normalize_cover_prompt("a  b\n c")
        assert normalize_cover_prompt(once) == once


class TestParseSummaryHandoffCover:
    def test_cover_prompt_parsed(self):
        raw = json.dumps({"response_mode": "casual", "digest": _DIGEST,
                          "cover_prompt": "  a  cat\nroof "})
        parsed = parse_summary_handoff(raw)
        assert parsed["cover_prompt"] == "a cat roof"

    def test_missing_cover_prompt_is_empty(self):
        raw = json.dumps({"response_mode": "serious", "digest": _DIGEST})
        assert parse_summary_handoff(raw)["cover_prompt"] == ""

    def test_invalid_cover_prompt_is_empty(self):
        raw = json.dumps({"response_mode": "serious", "digest": _DIGEST,
                          "cover_prompt": 123})
        assert parse_summary_handoff(raw)["cover_prompt"] == ""

    def test_legacy_markdown_has_empty_cover(self):
        assert parse_summary_handoff(_DIGEST)["cover_prompt"] == ""


# ── B. Конкатенация стиля ────────────────────────────────────────────

class TestStyleConcat:
    def test_style_plus_prompt(self):
        assert compose_cover_image_prompt("photoreal", "a cat") == \
            "photoreal a cat"

    def test_empty_style_drops(self):
        assert compose_cover_image_prompt("", "a cat") == "a cat"
        assert compose_cover_image_prompt(None, "a cat") == "a cat"

    def test_hard_cap_300(self):
        out = compose_cover_image_prompt("x" * 400, "y" * 50)
        assert len(out) == 300


# ── C. Article-сборка ────────────────────────────────────────────────

class TestArticleBuild:
    def test_cover_img_and_escape(self):
        html = build_cover_article_html("раз <b>два</b>\n\nтри")
        assert html.startswith(
            '<img src="tg://photo?id=%s">' % SUMMARY_COVER_MEDIA_ID)
        assert "<p>раз &lt;b&gt;два&lt;/b&gt;</p>" in html
        assert "<p>три</p>" in html

    def test_no_cover_id_has_no_img(self):
        html = build_cover_article_html("просто текст", cover_id="")
        assert "tg://photo" not in html
        assert html == "<p>просто текст</p>"

    def test_rich_media_supported_on_installed_aiogram(self):
        # requirements.txt пинит aiogram>=3.31; локально установлено 3.31.
        assert sg._rich_media_supported() is True


# ── D. Тихий фолбэк в _run ───────────────────────────────────────────

class _Recorder:
    def __init__(self):
        self.plain = []
        self.rich = []
        self.image_prompts = []
        self.ux = []


def _patch_delivery(monkeypatch, rec):
    async def _plain(self, chat_id, text):
        rec.plain.append(text)

    async def _rich(bot, chat_id, text, *, media=None, cover_id=None,
                    **kwargs):
        rec.rich.append({"text": text, "media": media, "cover_id": cover_id})

    monkeypatch.setattr(SummaryGenerator, "_send_streaming", _plain)
    monkeypatch.setattr(SummaryGenerator, "_send_chunked", _plain)
    monkeypatch.setattr(sg, "send_rich_message", _rich)

    async def _ux(self, chat_id, text):
        rec.ux.append(text)

    monkeypatch.setattr(SummaryGenerator, "_send_ux", _ux)


def _base_env(monkeypatch, rec, *, cover_path):
    monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", True)
    monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
    monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
    _patch_delivery(monkeypatch, rec)

    async def _gen_image(prompt, *, chat_id=None):
        rec.image_prompts.append(prompt)
        return cover_path

    monkeypatch.setattr(sg, "generate_image", _gen_image)


class TestRichDelivery:
    @pytest.mark.asyncio
    async def test_article_sent_when_cover_available(self, monkeypatch,
                                                      tmp_path):
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _base_env(monkeypatch, rec, cover_path=str(img))
        gen = _make_generator(_two_call_llm())

        await gen._run(-100, False)

        assert not rec.plain                       # plain не использовался
        assert len(rec.rich) == 1
        assert rec.rich[0]["cover_id"] == SUMMARY_COVER_MEDIA_ID
        assert rec.rich[0]["media"] and len(rec.rich[0]["media"]) == 1
        assert "богатый дерзкий рассказ" in rec.rich[0]["text"]
        assert rec.ux == []                        # без сообщений об ошибках
        # конкатенация стиля и visual prompt
        assert rec.image_prompts == [
            compose_cover_image_prompt(sg.SUMMARY_COVER_STYLE_DEFAULT,
                                       "a lone cat on a neon rooftop")]
        # tmp-файл обложки удалён после отправки
        assert not img.exists()

    @pytest.mark.asyncio
    async def test_image_none_is_silent_plain_fallback(self, monkeypatch):
        rec = _Recorder()
        _base_env(monkeypatch, rec, cover_path=None)
        gen = _make_generator(_two_call_llm())

        await gen._run(-100, False)

        assert rec.rich == []
        assert rec.plain and "богатый дерзкий рассказ" in rec.plain[0]
        assert rec.ux == []

    @pytest.mark.asyncio
    async def test_telegram_bad_request_is_silent_plain_and_downgraded(
            self, monkeypatch, tmp_path):
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _base_env(monkeypatch, rec, cover_path=str(img))

        async def _boom(*a, **k):
            raise TelegramBadRequest(method=MagicMock(), message="bad")

        monkeypatch.setattr(sg, "send_rich_message", _boom)
        gen = _make_generator(_two_call_llm())

        await gen._run(-100, False)

        assert rec.rich == []
        assert rec.plain and "богатый дерзкий рассказ" in rec.plain[0]
        # rich→plain даунгрейд: таблица снята, разделитель вырезан
        assert "|" not in rec.plain[0]
        assert rec.ux == []

    @pytest.mark.asyncio
    async def test_generic_exception_is_silent_plain(self, monkeypatch,
                                                     tmp_path):
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _base_env(monkeypatch, rec, cover_path=str(img))

        async def _boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(sg, "send_rich_message", _boom)
        gen = _make_generator(_two_call_llm())

        await gen._run(-100, False)

        assert rec.rich == []
        assert rec.plain
        assert rec.ux == []

    @pytest.mark.asyncio
    async def test_retry_after_one_retry_then_plain(self, monkeypatch,
                                                    tmp_path):
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _base_env(monkeypatch, rec, cover_path=str(img))

        calls = {"n": 0}

        async def _flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TelegramRetryAfter(method=MagicMock(),
                                         message="too many", retry_after=0)
            rec.rich.append({"text": a[2] if len(a) > 2 else k.get("text")})

        monkeypatch.setattr(sg, "send_rich_message", _flaky)
        gen = _make_generator(_two_call_llm())

        await gen._run(-100, False)

        assert calls["n"] == 2                     # ровно 1 повтор
        assert rec.plain == []                     # повтор успешен
        assert rec.ux == []

    @pytest.mark.asyncio
    async def test_guard_false_skips_cover(self, monkeypatch):
        rec = _Recorder()
        _base_env(monkeypatch, rec, cover_path="ignored")
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: False)
        gen = _make_generator(_two_call_llm())

        await gen._run(-100, False)

        assert rec.rich == []
        assert rec.image_prompts == []             # обложка не запрашивалась
        assert rec.plain and "богатый дерзкий рассказ" in rec.plain[0]
        assert rec.ux == []

    @pytest.mark.asyncio
    async def test_flag_off_skips_cover(self, monkeypatch):
        rec = _Recorder()
        _base_env(monkeypatch, rec, cover_path="ignored")
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", False)
        gen = _make_generator(_two_call_llm())

        await gen._run(-100, False)

        assert rec.rich == []
        assert rec.image_prompts == []
        assert rec.plain


# ── E. Даунгрейд rich → plain ────────────────────────────────────────

class TestDowngrade:
    def test_strips_table_and_tags(self):
        text = "| a | b |\n|---|---|\n| 1 | 2 |\n\n<table><tr><td>x</td></tr></table>"
        out = downgrade_rich_to_plain(text)
        assert "|" not in out
        assert "<table>" not in out and "<td>" not in out
        assert "a" in out and "1" in out and "x" in out

    def test_plain_text_with_pipe_is_kept(self):
        out = downgrade_rich_to_plain("Команда: cat file | grep error")
        assert "cat file | grep error" in out


# ── F. SummaryDraft-контракт ─────────────────────────────────────────

class TestSummaryDraft:
    @pytest.mark.asyncio
    async def test_cover_prompt_propagates(self, monkeypatch):
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
        gen = _make_generator(_two_call_llm(cover_prompt="neon cat"))
        draft = await gen._generate_two_call("сырьё", 3800, -100)
        assert isinstance(draft, SummaryDraft)
        assert draft.cover_prompt == "neon cat"
        assert draft.response_mode == "deep_research"
