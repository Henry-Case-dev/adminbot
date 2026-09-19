"""F6 (10.23, ADR-1023-6) — обложки саммари + Rich Article, тихий фолбэк.

Покрытие:
  * ``normalize_cover_prompt``: пусто/None/не-строка → ""; схлопывание
    пробелов/``\\n``; обрезка ≤300 по слову; идемпотентность;
  * разбор Stage-1 JSON с ``cover_prompt`` (отсутствие → "");
  * конкатенация «стиль + visual prompt» с финальным капом 300;
  * Article: ``html``-режим, ``<img src="tg://photo?id=summary_cover">``,
    экранирование, exactly-one-of;
  * guard ``_rich_media_supported`` (нет media → plain; реальный детектор
    на фейковом типе, без подмены всей функции);
  * тихий фолбэк: ``generate_image → None`` / ``TelegramBadRequest`` /
    любое исключение / двойной ``TelegramRetryAfter`` → plain, без ``_send_ux``;
  * даунгрейд rich → plain по СОДЕРЖИМОМУ (в т.ч. ``serious``/``casual``);
  * инвариант ``physical-two-call`` на JSON с непустым ``cover_prompt`` и
    изоляция Stage-2 от служебного поля.
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
from services.telegram_send import (
    SUMMARY_COVER_MEDIA_ID,
    build_cover_article_html,
    build_cover_media,
)

pytestmark = pytest.mark.system2

_DIGEST = "# Тема\n| a | b |\n|---|---|"


def _two_call_llm(cover_prompt="a lone cat on a neon rooftop", mode="deep_research"):
    class _LLM:
        def __init__(self):
            self.calls = 0

        async def generate(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return json.dumps({"response_mode": mode, "digest": _DIGEST,
                                   "cover_prompt": cover_prompt})
            return "богатый дерзкий рассказ"

    return _LLM()


def _mock_llm(cover_prompt="a lone cat", mode="deep_research",
              stage2="богатый дерзкий рассказ") -> MagicMock:
    """AsyncMock-LLM с `await_count`/`await_args_list` (инвариант 2 вызовов)."""
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=[
        json.dumps({"response_mode": mode, "digest": _DIGEST,
                    "cover_prompt": cover_prompt}),
        stage2,
    ])
    return llm


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

    def test_style_kept_visual_trimmed(self):
        # F12 (10.24, ADR-1024-4 D2): стиль приоритетнее visual; при
        # переполнении режется visual, общий кап = 1000.
        out = compose_cover_image_prompt("x" * 400, "y" * 800)
        assert out.startswith("x" * 400 + " ")
        assert len(out) == 1000
        assert set(out[401:]) == {"y"}


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

    @staticmethod
    def _fake_aiogram(monkeypatch, fields: dict):
        """Подменить aiogram-типы фейком: реальная логика `_rich_media_supported`
        исполняется, окружение aiogram не важно (review iter1, Medium-3)."""
        import aiogram
        import aiogram.types as aiogram_types

        class _FakeBot:
            def send_rich_message(self, *a, **k):  # noqa: D401
                return None

        class _FakeIRM:
            model_fields = fields

        monkeypatch.setattr(aiogram, "Bot", _FakeBot)
        monkeypatch.setattr(aiogram_types, "InputRichMessage", _FakeIRM)
        sg._rich_media_supported.cache_clear()

    def test_detector_true_when_media_present(self, monkeypatch):
        self._fake_aiogram(monkeypatch, {"html": object(), "media": object()})
        try:
            assert sg._rich_media_supported() is True
        finally:
            sg._rich_media_supported.cache_clear()

    def test_detector_false_when_media_absent(self, monkeypatch):
        """aiogram без `InputRichMessage.media` → guard выключает Article."""
        self._fake_aiogram(monkeypatch, {"html": object(), "markdown": object()})
        try:
            assert sg._rich_media_supported() is False
        finally:
            sg._rich_media_supported.cache_clear()

    def test_detector_cached_on_process(self, monkeypatch):
        """Review iter1 (Low-4): результат кэшируется на процесс."""
        self._fake_aiogram(monkeypatch, {"html": object(), "media": object()})
        try:
            sg._rich_media_supported()
            sg._rich_media_supported()
            assert sg._rich_media_supported.cache_info().hits >= 1
        finally:
            sg._rich_media_supported.cache_clear()


class TestStage1Canon:
    def test_single_json_format_block(self):
        """Review iter1 (Low-7): ровно один блок «ФОРМАТ ОТВЕТА» в каноне."""
        from services.summary_prompts import (
            PREV_SUMMARY_EDITOR_R1023_F6,
            SUMMARY_EDITOR_SYSTEM_PROMPT,
        )
        assert SUMMARY_EDITOR_SYSTEM_PROMPT.count("ФОРМАТ ОТВЕТА") == 1
        assert '"cover_prompt"' in SUMMARY_EDITOR_SYSTEM_PROMPT
        assert "response_mode" in SUMMARY_EDITOR_SYSTEM_PROMPT
        # слепок прежнего канона (F3) неизменен и отличается
        assert PREV_SUMMARY_EDITOR_R1023_F6 != SUMMARY_EDITOR_SYSTEM_PROMPT
        assert PREV_SUMMARY_EDITOR_R1023_F6.count("ФОРМАТ ОТВЕТА") == 1


# ── D. Тихий фолбэк в _run ───────────────────────────────────────────

class _Recorder:
    def __init__(self):
        self.plain = []
        self.rich = []
        self.image_prompts = []
        self.image_correlation_ids = []
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

    async def _gen_image(prompt, *, chat_id=None, correlation_id=None):
        rec.image_prompts.append(prompt)
        rec.image_correlation_ids.append(correlation_id)
        # 10.24 (F12): verbose-контракт — (путь, reason).
        return cover_path, ("ok" if cover_path else "error")

    monkeypatch.setattr(sg, "generate_image_verbose", _gen_image)


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
    async def test_cover_image_gets_summary_correlation_id(self, monkeypatch,
                                                           tmp_path):
        """F7 rework (M1): обложка несёт ТОТ ЖЕ correlation_id, что саммари —
        событие ``step='image'`` остаётся в дереве последнего вызова."""
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _base_env(monkeypatch, rec, cover_path=str(img))
        monkeypatch.setattr("services.usage_events.new_correlation_id",
                            lambda: "SUM-COVER-9")
        gen = _make_generator(_two_call_llm())

        await gen._run(-100, False)

        assert rec.image_correlation_ids == ["SUM-COVER-9"]

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
    async def test_retry_after_both_attempts_then_silent_plain(
            self, monkeypatch, tmp_path):
        """Review iter1 (Medium-3a): RetryAfter на обеих попытках → ровно 1
        повтор, затем тихий plain без UX-сообщений."""
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _base_env(monkeypatch, rec, cover_path=str(img))

        calls = {"n": 0}

        async def _always_retry(*a, **k):
            calls["n"] += 1
            raise TelegramRetryAfter(method=MagicMock(), message="too many",
                                     retry_after=0)

        monkeypatch.setattr(sg, "send_rich_message", _always_retry)
        gen = _make_generator(_two_call_llm())

        await gen._run(-100, False)

        assert calls["n"] == 2                     # ровно 1 повтор
        assert rec.rich == []
        assert rec.plain and "богатый дерзкий рассказ" in rec.plain[0]
        assert rec.ux == []

    @pytest.mark.asyncio
    async def test_downgrade_by_content_in_serious_mode(self, monkeypatch,
                                                        tmp_path):
        """Review iter1 (Medium-2): rich-разметка от Narrator в serious-режиме
        при фолбэке снимается (даунгрейд по содержимому, не по режиму)."""
        from tests.test_summary_generator import FakeMemory, _row
        from services.summary_xml import XmlGroundingBuilder

        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _base_env(monkeypatch, rec, cover_path=str(img))
        llm = _mock_llm(mode="serious", cover_prompt="cat",
                        stage2="| a | b |\n|---|---|\n| 1 | 2 |\n# Заголовок")

        async def _boom(*a, **k):
            raise TelegramBadRequest(method=MagicMock(), message="bad")

        monkeypatch.setattr(sg, "send_rich_message", _boom)
        gen = SummaryGenerator(FakeMemory(rows=[_row(author_name="вася")]),
                               XmlGroundingBuilder(), llm, AsyncMock())

        await gen._run(-100, False)

        assert rec.rich == []
        assert rec.plain
        assert "|" not in rec.plain[0]
        assert "#" not in rec.plain[0]
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


# ── G. Инвариант двух вызовов и изоляция Stage-2 ─────────────────────

class TestTwoCallInvariant:
    @pytest.mark.asyncio
    async def test_cover_json_keeps_two_physical_calls(self, monkeypatch):
        """Review iter1 (Medium-3c): непустой `cover_prompt` не добавляет
        третий LLM-вызов — ровно Stage-1 + Stage-2."""
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
        llm = _mock_llm(cover_prompt="neon cat")
        gen = _make_generator(llm)

        draft = await gen._generate_two_call("сырьё", 3800, -100)

        assert draft.cover_prompt == "neon cat"
        assert llm.generate.await_count == 2

    @pytest.mark.asyncio
    async def test_cover_prompt_isolated_from_stage2(self, monkeypatch):
        """Review iter1 (Medium-3d): служебное поле `cover_prompt` не попадает
        в user-content Stage-2 (R17/изоляция)."""
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
        llm = _mock_llm(cover_prompt="SECRET_VISUAL_TOKEN")
        gen = _make_generator(llm)

        await gen._generate_two_call("сырьё", 3800, -100)

        stage2_messages = llm.generate.await_args_list[1].args[0]
        blob = json.dumps(stage2_messages, ensure_ascii=False)
        assert "SECRET_VISUAL_TOKEN" not in blob
        assert "cover_prompt" not in blob
