"""Tests for services/youtube_summarizer_service.py (T-289, R37-7, D130, Section 46.8/46.12).

Пайплайн: engine.fetch_transcript(video_id, settings.YOUTUBE_MAX_SYMBOLS) →
YOUTUBE_SYSTEM_PROMPT ({max_symbols} → settings) → user с <video_id>/<transcript>
(escape_xml_text) → llm.generate → cleanup_llm_text (пост-процессинг, R37-7).
Ошибки движка/LLM пробрасываются.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services.llm_client import LLMBadResponseError, LLMError
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
            VIDEO_ID, settings.YOUTUBE_MAX_SYMBOLS, on_retry=None
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
    async def test_on_retry_passed_through_to_engine(self):
        """#20 (50.8, R41-2): on_retry пробрасывается в fetch_transcript как есть."""
        service, engine, _ = _service()
        cb = AsyncMock()
        await service.summarize(VIDEO_ID, on_retry=cb)
        engine.fetch_transcript.assert_awaited_once_with(
            VIDEO_ID, settings.YOUTUBE_MAX_SYMBOLS, on_retry=cb
        )

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
    async def test_empty_answer_raises_bad_response(self):
        """65.1 (T-469): пустой ответ модели (после cleanup) → LLMBadResponseError."""
        service, _, llm = _service()
        llm.generate = AsyncMock(return_value="   ")
        with pytest.raises(LLMBadResponseError):
            await service.summarize(VIDEO_ID)

    @pytest.mark.asyncio
    async def test_unexpected_engine_failure_propagates(self):
        service, engine, _ = _service()
        engine.fetch_transcript = AsyncMock(side_effect=RuntimeError("внезапно"))
        with pytest.raises(RuntimeError):
            await service.summarize(VIDEO_ID)


# ── Epic 46 (55.5, T-366-A #17-19) ────────────────────────────────

class TestGraphRagV2Hooks:
    def _service_with_memory(self):
        engine = MagicMock()
        engine.fetch_transcript = AsyncMock(return_value="[00:05] привет")
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="выжимка")
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        memory.get_rag_context = AsyncMock(return_value="")
        return YoutubeSummarizerService(engine, llm, memory=memory), engine, llm, memory

    @pytest.mark.asyncio
    async def test_memory_none_no_create_task(self, monkeypatch):
        """#17: memory=None → create_task НЕ вызван."""
        spy = []
        monkeypatch.setattr(
            "services.summary_memory.asyncio.create_task", lambda coro: spy.append(coro)
        )
        service, _, _ = _service()
        result = await service.summarize(VIDEO_ID)
        assert result == "выжимка"
        assert spy == []

    @pytest.mark.asyncio
    async def test_short_transcript_memorized_raw(self, monkeypatch):
        """#19: transcript ≤ 8000 → memorize сырых субтитров (create_task)."""
        spy = []
        monkeypatch.setattr(
            "services.summary_memory.asyncio.create_task", lambda coro: spy.append(coro)
        )
        service, _, _, memory = self._service_with_memory()
        result = await service.summarize(VIDEO_ID, chat_id=-100, rag_query="че за видос")
        assert result == "выжимка"
        assert len(spy) == 1
        await spy[0]        # выполняем фоновую задачу вручную (детерминизм)
        memory.memorize_facts.assert_awaited_once_with(
            -100, "[00:05] привет", "youtube_content"
        )
        memory.get_rag_context.assert_awaited_once_with(-100, "че за видос")

    @pytest.mark.asyncio
    async def test_long_transcript_compressed_then_memorized(self):
        """#19: > 8000 символов → нетоксичная LLM-выжимка, затем memorize
        сжатого (порог 55.5)."""
        from services.summary_memory import _MEMORIZE_COMPRESS_PROMPT, _memorize_youtube

        long_text = "слово " * 3000
        memory = MagicMock()
        memory.llm = MagicMock()
        memory.llm.generate = AsyncMock(return_value="сжатая выжимка")
        memory.memorize_facts = AsyncMock()
        await _memorize_youtube(memory, -100, long_text)
        system = memory.llm.generate.await_args.args[0][0]["content"]
        assert system == _MEMORIZE_COMPRESS_PROMPT
        memory.memorize_facts.assert_awaited_once_with(
            -100, "сжатая выжимка", "youtube_content"
        )

    @pytest.mark.asyncio
    async def test_compress_failure_does_not_raise(self):
        """#19: сжатие упало → тихий WARNING, НЕ бросает."""
        from services.summary_memory import _memorize_youtube

        long_text = "слово " * 3000
        memory = MagicMock()
        memory.llm = MagicMock()
        memory.llm.generate = AsyncMock(side_effect=LLMError("сжатие упало"))
        await _memorize_youtube(memory, -100, long_text)   # не бросает
        memory.memorize_facts.assert_not_called()
