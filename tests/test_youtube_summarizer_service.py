"""Tests for services/youtube_summarizer_service.py (T-289, R37-7, D130, Section 46.8/46.12).

Пайплайн: engine.fetch_transcript(video_id, settings.YOUTUBE_MAX_SYMBOLS) →
YOUTUBE_SYSTEM_PROMPT ({max_symbols} → settings) → user с <video_id>/<transcript>
(escape_xml_text) → llm.generate → cleanup_llm_text (пост-процессинг, R37-7).
Ошибки движка/LLM пробрасываются.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services.llm_client import LLMError
from services.youtube_summarizer_service import YoutubeSummarizerService
from services.youtube_transcript_engine import YouTubeTranscriptUnavailableException

VIDEO_ID = "dQw4w9WgXcQ"


def _service():
    engine = MagicMock()
    engine.fetch_transcript = AsyncMock(return_value="[00:05] привет")
    llm = MagicMock()
    llm.generate = AsyncMock(return_value="выжимка")
    return YoutubeSummarizerService(engine, llm), engine, llm


class TestSummarize:
    @pytest.mark.asyncio
    async def test_pipeline_order_and_prompt_substitution(self):
        """#24: движок с settings-лимитом; system без {max_symbols}, с числом;
        user содержит <video_id> и <transcript>."""
        service, engine, llm = _service()
        result = await service.summarize(VIDEO_ID)
        assert result == "выжимка"
        engine.fetch_transcript.assert_awaited_once_with(
            VIDEO_ID, settings.YOUTUBE_MAX_SYMBOLS
        )
        messages = llm.generate.await_args.args[0]
        system_content, user = messages[0]["content"], messages[1]["content"]
        assert "{max_symbols}" not in system_content
        assert str(settings.YOUTUBE_MAX_SYMBOLS) in system_content
        assert f"<video_id>{VIDEO_ID}</video_id>" in user
        assert "<transcript>[00:05] привет</transcript>" in user

    @pytest.mark.asyncio
    async def test_cleanup_applied_to_llm_output(self):
        """#25: «ёлочки» и «—» из raw LLM → cleanup_llm_text (R37-7)."""
        service, _, _ = _service()
        service.llm.generate = AsyncMock(return_value="«ёлочки» — тире")
        result = await service.summarize(VIDEO_ID)
        assert result == '"ёлочки" - тире'

    @pytest.mark.asyncio
    async def test_xml_escape_applied_to_transcript(self):
        """#26: XML-спецсимволы транскрипта эскейпятся."""
        service, engine, _ = _service()
        engine.fetch_transcript = AsyncMock(return_value="<a> & </a>")
        await service.summarize(VIDEO_ID)
        user = service.llm.generate.await_args.args[0][1]["content"]
        assert "<transcript>&lt;a&gt; &amp; &lt;/a&gt;</transcript>" in user

    @pytest.mark.asyncio
    async def test_engine_failure_propagates(self):
        """#27: YouTubeTranscriptUnavailableException проброшен, LLM не вызван."""
        service, engine, _ = _service()
        engine.fetch_transcript = AsyncMock(
            side_effect=YouTubeTranscriptUnavailableException("нет субтитров")
        )
        with pytest.raises(YouTubeTranscriptUnavailableException):
            await service.summarize(VIDEO_ID)
        service.llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_propagates(self):
        service, _, llm = _service()
        llm.generate = AsyncMock(side_effect=LLMError("llm сдох"))
        with pytest.raises(LLMError):
            await service.summarize(VIDEO_ID)

    @pytest.mark.asyncio
    async def test_unexpected_engine_failure_propagates(self):
        service, engine, _ = _service()
        engine.fetch_transcript = AsyncMock(side_effect=RuntimeError("внезапно"))
        with pytest.raises(RuntimeError):
            await service.summarize(VIDEO_ID)
