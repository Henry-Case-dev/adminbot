"""EXTRA Pass 2 (ADR-1028-4 D9; spec §3.1/§3.4/§49–§52/§78–§82/§90) — runtime
интеграция публикационного контура: fail-soft ladder + degraded Rich-without-cover.

Крит. регресс §90: no-style happy path не меняется. §80/§49: style failure не
перегенерирует base. §81/§51: base failure → Rich без обложки. §82/§52: rich
failure → plain. §95: kill-switch OFF → parity baseline (plain).
"""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import summary_generator as sg
from services.summary_generator import SummaryGenerator

CHAT = -100123
DOC = {"schema_version": 1, "title": "Событие",
       "paragraphs": [{"text": "Первый абзац.", "emphasis": None},
                      {"text": "Второй абзац.", "emphasis": None}]}


class _Recorder:
    def __init__(self):
        self.media_paths = []
        self.rich = []
        self.plain = []
        self.image_calls = 0

    def install(self, monkeypatch, tmp_path, *, base_ok=True, rich_ok=True):
        rec = self
        base = tmp_path / "base.jpg"
        base.write_bytes(b"BASE")
        styled = tmp_path / "styled.jpg"
        styled.write_bytes(b"STYLED")

        async def _gen(prompt, *, chat_id=None, correlation_id=None,
                       shorter_prompt=None, attempt_log=None):
            # ASAP 7 (F7, 2.58.73): generate_image_verbose получил
            # shorter_prompt/attempt_log (content-loss fix) — стаб зеркалит
            # сигнатуру (image_generation.py:1303), иначе TypeError до
            # самого вызова → COVER_GENERATION_FAILED.
            rec.image_calls += 1
            return (str(base), "ok") if base_ok else (None, "no_key")

        async def _rich(bot, chat_id, text, *, media=None, cover_id=None,
                        content_format="auto", **kw):
            if not rich_ok:
                raise RuntimeError("sendRichMessage down")
            rec.rich.append({"text": text, "media": media, "cover_id": cover_id})
            return MagicMock(message_id=555)

        async def _text(bot, chat_id, text, **kw):
            rec.plain.append(text)
            return MagicMock(message_id=101)

        monkeypatch.setattr(sg, "generate_image_verbose", _gen)
        monkeypatch.setattr(sg, "build_cover_media",
                            lambda path, **kw: rec.media_paths.append(path)
                            or {"path": path})
        monkeypatch.setattr(sg, "send_rich_message", _rich)
        monkeypatch.setattr(sg, "send_text", _text)
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
        return rec, str(base), str(styled)


def _gen(monkeypatch, *, style_meta=None):
    gen = SummaryGenerator(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    gen._resolve_cover_style_text = AsyncMock(return_value="style")
    gen._maybe_apply_cover_style = AsyncMock(return_value=style_meta)
    return gen


@pytest.mark.asyncio
async def test_no_style_base_cover_rich_regression(monkeypatch, tmp_path):
    """§90: `Без дополнительного стиля` — ровно текущий путь (base + rich)."""
    rec, base, _ = _Recorder().install(monkeypatch, tmp_path)
    gen = _gen(monkeypatch, style_meta=None)
    published = await gen._publish_rich_document(CHAT, DOC, "a lone cat")
    assert published is True
    assert rec.image_calls == 1
    assert rec.media_paths == [base]
    assert rec.rich and rec.rich[0]["media"]           # обложка вложена
    assert rec.rich[0]["text"].startswith('<img src="tg://photo?id=summary_cover">')
    assert rec.plain == []


@pytest.mark.asyncio
async def test_style_success_publishes_styled(monkeypatch, tmp_path):
    """§79: style success → публикуется styled cover."""
    rec, _, styled = _Recorder().install(monkeypatch, tmp_path)
    gen = _gen(monkeypatch, style_meta={"styled_path": styled,
                                        "outcome": "styled", "reason": ""})
    published = await gen._publish_rich_document(CHAT, DOC, "a lone cat")
    assert published is True
    assert rec.media_paths == [styled]
    assert rec.image_calls == 1                        # base сгенерирован 1 раз


@pytest.mark.asyncio
async def test_style_failure_uses_base_no_regen(monkeypatch, tmp_path):
    """§80/§49: style failure → сохранённая base, БЕЗ второй генерации base."""
    rec, base, _ = _Recorder().install(monkeypatch, tmp_path)
    gen = _gen(monkeypatch, style_meta={"styled_path": None,
                                        "reason": "style_failed"})
    published = await gen._publish_rich_document(CHAT, DOC, "a lone cat")
    assert published is True
    assert rec.image_calls == 1                        # no second base gen
    assert rec.media_paths == [base]


@pytest.mark.asyncio
async def test_base_failure_degraded_rich_without_cover(monkeypatch, tmp_path):
    """§81/§51: base failure → Rich БЕЗ обложки (media=[]), статья сохранена."""
    rec, _, _ = _Recorder().install(monkeypatch, tmp_path, base_ok=False)
    gen = _gen(monkeypatch, style_meta=None)
    published = await gen._publish_rich_document(CHAT, DOC, "a lone cat")
    assert published is True
    assert rec.rich, "degraded rich отправлен"
    assert not rec.rich[0]["media"]                    # media=[] (без обложки)
    assert rec.rich[0]["cover_id"] is None
    assert "<img" not in rec.rich[0]["text"]
    assert "<h1>" in rec.rich[0]["text"]               # структура сохранена
    assert rec.plain == []                             # plain не понадобился
    assert rec.image_calls == 1


@pytest.mark.asyncio
async def test_base_failure_parity_plain_when_degraded_off(monkeypatch,
                                                           tmp_path):
    """§95: degraded OFF → baseline parity (plain), §90 не задет."""
    monkeypatch.setattr("services.cover_style_jobs.rich_degraded_enabled", lambda: False)
    rec, _, _ = _Recorder().install(monkeypatch, tmp_path, base_ok=False)
    gen = _gen(monkeypatch, style_meta=None)
    published = await gen._publish_rich_document(CHAT, DOC, "a lone cat")
    assert published is True
    assert rec.plain and not rec.rich


@pytest.mark.asyncio
async def test_kill_switch_off_parity(monkeypatch, tmp_path):
    """§95: `COVER_STYLES_ENABLED=false` → базовая+публикация живы, plain."""
    monkeypatch.setattr("services.cover_style_jobs.cover_styles_enabled", lambda: False)
    rec, _, _ = _Recorder().install(monkeypatch, tmp_path, base_ok=False)
    gen = _gen(monkeypatch, style_meta=None)
    published = await gen._publish_rich_document(CHAT, DOC, "a lone cat")
    assert published is True
    assert rec.plain and not rec.rich


@pytest.mark.asyncio
async def test_degraded_rich_failure_falls_back_to_plain(monkeypatch, tmp_path):
    """§82/§52: Rich без обложки упал → обычный sendMessage, текст сохранён."""
    rec = _Recorder()
    plain_chunks = []

    async def _gen2(prompt, *, chat_id=None, correlation_id=None):
        return (None, "no_key")

    async def _rich2(bot, chat_id, text, *, media=None, cover_id=None,
                     content_format="auto", **kw):
        raise RuntimeError("still down")

    async def _text2(bot, chat_id, text, **kw):
        plain_chunks.append(text)
        return MagicMock(message_id=1)

    monkeypatch.setattr(sg, "generate_image_verbose", _gen2)
    monkeypatch.setattr(sg, "send_rich_message", _rich2)
    monkeypatch.setattr(sg, "send_text", _text2)
    monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
    gen = _gen(monkeypatch, style_meta=None)
    published = await gen._publish_rich_document(CHAT, DOC, "a lone cat")
    assert published is True
    assert plain_chunks                                # plain-фолбэк сработал
    joined = "".join(plain_chunks)
    assert "Первый абзац." in joined and "Второй абзац." in joined

