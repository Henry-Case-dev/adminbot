"""Общие хелперы тестов обложки саммари (rich/фолбэк) — round10.25.

Review L10.25H4-5: вынесено из `test_hotfix3_summary_fallback_round1025.py`,
чтобы hotfix3/hotfix4-гейты не зависели от приватных символов чужого тест-модуля.
"""
from unittest.mock import AsyncMock, MagicMock

from config.settings import Settings
from services import summary_generator as sg
from services.summary_generator import SummaryGenerator


class Recorder:
    """Сбор фактически доставленного (plain/rich/image-промпты/UX)."""

    def __init__(self):
        self.plain = []
        self.rich = []
        self.image_prompts = []
        self.ux = []


def patch_delivery(monkeypatch, rec):
    async def _plain(self, chat_id, text):
        rec.plain.append(text)

    async def _rich(bot, chat_id, text, *, media=None, cover_id=None, **kwargs):
        rec.rich.append({"media": media, "cover_id": cover_id, "text": text})

    monkeypatch.setattr(SummaryGenerator, "_send_streaming", _plain)
    monkeypatch.setattr(SummaryGenerator, "_send_chunked", _plain)
    monkeypatch.setattr(sg, "send_rich_message", _rich)

    async def _ux(self, chat_id, text):
        rec.ux.append(text)

    monkeypatch.setattr(SummaryGenerator, "_send_ux", _ux)


def env(monkeypatch, rec, *, cover_path, rich=True):
    monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", True)
    monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
    monkeypatch.setattr(Settings, "SUMMARY_COVER_FALLBACK_ENABLED", True)
    monkeypatch.setattr(sg, "_rich_media_supported", lambda: rich)
    # Не зависим от наличия `InputRichMessageMedia` в версии aiogram.
    monkeypatch.setattr(
        sg, "build_cover_media",
        lambda path, **kw: {"stub_path": path})
    patch_delivery(monkeypatch, rec)

    async def _gen_image(prompt, *, chat_id=None, correlation_id=None):
        rec.image_prompts.append(prompt)
        return cover_path, ("ok" if cover_path else "error")

    monkeypatch.setattr(sg, "generate_image_verbose", _gen_image)


def generator(side_effect):
    from tests.test_summary_generator import FakeMemory, _row
    from services.summary_xml import XmlGroundingBuilder

    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=side_effect)
    gen = SummaryGenerator(FakeMemory(rows=[_row(author_name="вася")]),
                           XmlGroundingBuilder(), llm, AsyncMock())
    return gen, llm
