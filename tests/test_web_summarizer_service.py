"""Tests for services/web_summarizer_service.py (T-298, R38-3, Section 47.5/47.6).

Пайплайн: extractor.extract(url, settings.WEBPAGE_MAX_SYMBOLS) →
WEBPAGE_SYSTEM_PROMPT ({max_symbols} → settings) → user с <webpage url="…">
(escape_xml_text quote=True) → llm.generate → cleanup_llm_text (R37-7).
Ошибки экстрактора/LLM пробрасываются.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services.llm_client import LLMError
from services.web_content_extractor import WebContentExtractionFailedException
from services.web_summarizer_service import WebSummarizerService

TARGET = "https://example.com/article"


def _service():
    extractor = MagicMock()
    extractor.extract = AsyncMock(return_value="# Заголовок")
    llm = MagicMock()
    llm.generate = AsyncMock(return_value="выжимка")
    return WebSummarizerService(extractor, llm), extractor, llm


class TestSummarize:
    @pytest.mark.asyncio
    async def test_pipeline_order_and_prompt_substitution(self):
        """#24: экстрактор с settings-лимитом; system без {max_symbols}, с числом;
        user содержит <webpage url=…>."""
        service, extractor, llm = _service()
        result = await service.summarize(TARGET)
        assert result == "выжимка"
        extractor.extract.assert_awaited_once_with(
            TARGET, settings.WEBPAGE_MAX_SYMBOLS
        )
        messages = llm.generate.await_args.args[0]
        system_content = messages[0]["content"]
        assert "{max_symbols}" not in system_content
        assert str(settings.WEBPAGE_MAX_SYMBOLS) in system_content
        user = messages[1]["content"]
        assert f'<webpage url="{TARGET}">' in user
        assert "# Заголовок" in user
        assert "</webpage>" in user

    @pytest.mark.asyncio
    async def test_cleanup_applied_to_llm_output(self):
        """#25: «ёлочки» и «—» из raw LLM → cleanup_llm_text (R37-7)."""
        service, _, _ = _service()
        service.llm.generate = AsyncMock(return_value="«ёлочки» — тире")
        result = await service.summarize(TARGET)
        assert result == '"ёлочки" - тире'

    @pytest.mark.asyncio
    async def test_xml_escape_applied_to_markdown(self):
        """#26: XML-спецсимволы страницы эскейпятся."""
        service, extractor, _ = _service()
        extractor.extract = AsyncMock(return_value="<a> & </a>")
        await service.summarize(TARGET)
        user = service.llm.generate.await_args.args[0][1]["content"]
        assert "&lt;a&gt; &amp; &lt;/a&gt;" in user

    @pytest.mark.asyncio
    async def test_url_quotes_escaped(self):
        """quote=True (прецедент factcheck build_user_content, 42.6)."""
        service, _, _ = _service()
        url_with_quotes = 'https://x.com/a"b'
        await service.summarize(url_with_quotes)
        user = service.llm.generate.await_args.args[0][1]["content"]
        assert 'url="https://x.com/a&quot;b"' in user

    @pytest.mark.asyncio
    async def test_extractor_failure_propagates(self):
        """#27: WebContentExtractionFailedException проброшен, LLM не вызван."""
        service, extractor, _ = _service()
        extractor.extract = AsyncMock(
            side_effect=WebContentExtractionFailedException("сайт сдох")
        )
        with pytest.raises(WebContentExtractionFailedException):
            await service.summarize(TARGET)
        service.llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_propagates(self):
        service, _, llm = _service()
        llm.generate = AsyncMock(side_effect=LLMError("llm сдох"))
        with pytest.raises(LLMError):
            await service.summarize(TARGET)

    @pytest.mark.asyncio
    async def test_unexpected_extractor_failure_propagates(self):
        service, extractor, _ = _service()
        extractor.extract = AsyncMock(side_effect=RuntimeError("внезапно"))
        with pytest.raises(RuntimeError):
            await service.summarize(TARGET)


# ── Epic 46 (55.5, T-366-A #17-18) ────────────────────────────────

class TestGraphRagV2Hooks:
    @pytest.mark.asyncio
    async def test_memory_none_no_create_task(self, monkeypatch):
        """#17: memory=None → create_task НЕ вызван."""
        spy = []
        monkeypatch.setattr(
            "services.summary_memory.asyncio.create_task", lambda coro: spy.append(coro)
        )
        service, _, _ = _service()
        result = await service.summarize(TARGET)
        assert result == "выжимка"
        assert spy == []

    @pytest.mark.asyncio
    async def test_memory_set_create_task_and_raw_markdown(self, monkeypatch):
        """#18: create_task вызван; ответ возвращается (не блокирует);
        memorize — с raw-markdown страницы."""
        spy = []
        monkeypatch.setattr(
            "services.summary_memory.asyncio.create_task", lambda coro: spy.append(coro)
        )
        extractor = MagicMock()
        extractor.extract = AsyncMock(return_value="# Заголовок")
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="выжимка")
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        memory.get_rag_context = AsyncMock(return_value="")
        service = WebSummarizerService(extractor, llm, memory=memory)
        result = await service.summarize(TARGET, chat_id=-100, rag_query="статья")
        assert result == "выжимка"
        assert len(spy) == 1
        await spy[0]        # выполняем фоновую задачу вручную (детерминизм)
        memory.memorize_facts.assert_awaited_once_with(-100, "# Заголовок", "web_content")
        memory.get_rag_context.assert_awaited_once_with(-100, "статья")
        user = llm.generate.await_args.args[0][1]["content"]
        assert "<webpage" in user

    @pytest.mark.asyncio
    async def test_rag_context_prefixed_to_user_content(self, monkeypatch):
        """55.5/55.6: RAG-контекст — префикс user-контента (до <webpage>)."""
        spy = []
        monkeypatch.setattr(
            "services.summary_memory.asyncio.create_task", lambda coro: spy.append(coro)
        )
        extractor = MagicMock()
        extractor.extract = AsyncMock(return_value="# Заголовок")
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="выжимка")
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        memory.get_rag_context = AsyncMock(return_value="<context>ctx</context>")
        service = WebSummarizerService(extractor, llm, memory=memory)
        await service.summarize(TARGET, chat_id=-100, rag_query="статья")
        await spy[0]        # выполняем фоновую задачу вручную (детерминизм)
        user = llm.generate.await_args.args[0][1]["content"]
        assert user.startswith("<context>ctx</context>\n\n<webpage")
