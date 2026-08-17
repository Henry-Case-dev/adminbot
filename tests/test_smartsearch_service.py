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
