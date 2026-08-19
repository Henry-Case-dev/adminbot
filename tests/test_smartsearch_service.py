"""Tests for services/search_service.py (T-253-B, Section 42.6/42.10).

research: aggregator→SEARCH_SYSTEM_PROMPT→<query>/<search_results>→LLM→cleanup;
ошибки пробрасываются.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services.llm_client import LLMError
from services.search_aggregator import AllSearchEnginesFailedException
from services.search_service import SearchService


class TestResearch:
    def _service(self):
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="хиты")
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="выжимка «да» — суть")
        return SearchService(aggregator, llm), aggregator, llm

    @pytest.mark.asyncio
    async def test_pipeline_and_xml_content(self):
        service, aggregator, llm = self._service()
        result = await service.research("найди пруфы")
        aggregator.search.assert_awaited_once_with(
            "найди пруфы", settings.SEARCH_MAX_SYMBOLS
        )
        messages = llm.generate.await_args.args[0]
        system, user = messages[0]["content"], messages[1]["content"]
        assert str(settings.SEARCH_MAX_SYMBOLS) in system
        assert "{max_symbols}" not in system
        assert "Максимальный жесткий потолок" in system  # R36-2 (D120)
        assert user == "<query>найди пруфы</query>\n\n<search_results>хиты</search_results>"

    @pytest.mark.asyncio
    async def test_cleanup_applied_to_llm_output(self):
        service, _, _ = self._service()
        service.llm.generate = AsyncMock(return_value="«ёлочки» — тире")
        result = await service.research("q")
        assert result == '"ёлочки" - тире'

    @pytest.mark.asyncio
    async def test_query_and_results_xml_escaped(self):
        service, _, llm = self._service()
        await service.research("a < b")
        user = llm.generate.await_args.args[0][1]["content"]
        assert "<query>a &lt; b</query>" in user

    @pytest.mark.asyncio
    async def test_search_failure_propagates(self):
        service, aggregator, _ = self._service()
        aggregator.search = AsyncMock(
            side_effect=AllSearchEnginesFailedException("все упали")
        )
        with pytest.raises(AllSearchEnginesFailedException):
            await service.research("q")
        service.llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_propagates(self):
        service, _, llm = self._service()
        llm.generate = AsyncMock(side_effect=LLMError("llm сдох"))
        with pytest.raises(LLMError):
            await service.research("q")


# ── Epic 46 (55.5, T-366-A #17-18) ────────────────────────────────

def _spy_create_task(monkeypatch):
    spy = []
    monkeypatch.setattr(
        "services.summary_memory.asyncio.create_task", lambda coro: spy.append(coro)
    )
    return spy


class TestGraphRagV2Hooks:
    def _service_with_memory(self):
        aggregator = MagicMock()
        aggregator.search = AsyncMock(return_value="хиты")
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="выжимка")
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        memory.get_rag_context = AsyncMock(return_value="")
        return SearchService(aggregator, llm, memory=memory), aggregator, llm, memory

    @pytest.mark.asyncio
    async def test_memory_none_old_path_no_create_task(self, monkeypatch):
        """#17: memory=None → create_task НЕ вызван, user-контент как раньше."""
        spy = _spy_create_task(monkeypatch)
        service, _, llm = TestResearch._service(self)
        result = await service.research("найди пруфы")
        assert result == 'выжимка "да" - суть'
        assert spy == []
        user = llm.generate.await_args.args[0][1]["content"]
        assert user == "<query>найди пруфы</query>\n\n<search_results>хиты</search_results>"

    @pytest.mark.asyncio
    async def test_chat_id_none_old_path_no_create_task(self, monkeypatch):
        """#17: chat_id=None → create_task НЕ вызван."""
        spy = _spy_create_task(monkeypatch)
        service, _, llm, _ = self._service_with_memory()
        result = await service.research("найди пруфы")
        assert result == "выжимка"
        assert spy == []

    @pytest.mark.asyncio
    async def test_memory_set_create_task_and_raw_memorize(self, monkeypatch):
        """#18: память задана → create_task вызван; research возвращает ответ
        (НЕ блокирует); memorize вызван с RAW-результатами поиска (НЕ с
        финальным LLM-ответом, R46-2)."""
        spy = _spy_create_task(monkeypatch)
        service, _, llm, memory = self._service_with_memory()
        result = await service.research("найди пруфы", chat_id=-100)
        assert result == "выжимка"
        assert len(spy) == 1
        await spy[0]        # выполняем фоновую задачу вручную (детерминизм)
        memory.memorize_facts.assert_awaited_once_with(-100, "хиты", "search_fact")
        memory.get_rag_context.assert_awaited_once_with(-100, "найди пруфы")
        user = llm.generate.await_args.args[0][1]["content"]
        assert "<search_results>хиты</search_results>" in user

    @pytest.mark.asyncio
    async def test_rag_context_prefixed_to_user_content(self, monkeypatch):
        """55.5/55.6: непустой RAG-контекст — ПЕРВОЙ секцией user-контента."""
        spy = _spy_create_task(monkeypatch)
        service, _, llm, memory = self._service_with_memory()
        memory.get_rag_context = AsyncMock(return_value="<context>ctx</context>")
        await service.research("найди пруфы", chat_id=-100)
        await spy[0]        # выполняем фоновую задачу вручную (детерминизм)
        user = llm.generate.await_args.args[0][1]["content"]
        assert user.startswith("<context>ctx</context>\n\n<query>найди пруфы</query>")
