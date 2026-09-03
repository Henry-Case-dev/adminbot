"""Эпик 04.09.2026 (3.3, T-17/AC-2.4) — ToolRouter: исполнение инструментов
поверх моков SearchAggregator/MemoryManager; fail-open в тексты «ОШИБКА …».
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.search_aggregator import AllSearchEnginesFailedException
from services.summary_aliases import AliasResolver
from services.tool_router import (
    ToolContext,
    ToolDeps,
    ToolRouter,
    keywords,
)

CHAT_ID = -1001234567890


def _deps(search=None, memory=None, aliases=None) -> ToolDeps:
    if search is None:
        search = MagicMock()
        search.search = AsyncMock(return_value="результаты поиска")
    memory = memory or MagicMock()
    return ToolDeps(search=search, memory=memory, aliases=aliases)


def _ctx(query="а что было вчера?") -> ToolContext:
    return ToolContext(CHAT_ID, query)


def _row(user_id=10, author_name="вася", text="текст сообщения", ts=None):
    return {"user_id": user_id, "author_name": author_name, "text": text,
            "timestamp": ts or int(time.time())}


class TestKeywords:
    def test_tokens_extracted(self):
        assert keywords("Что там с РЖД и курсом?") == ["что", "там", "с", "ржд",
                                                       "и", "курсом"]

    def test_empty(self):
        assert keywords("???!!") == []


class TestDispatchUnknownAndArgs:
    @pytest.mark.asyncio
    async def test_unknown_tool_name(self):
        router = ToolRouter(_deps())
        out = await router.dispatch("execute_arbitrary_code", {}, _ctx())
        assert "ОШИБКА: неизвестный инструмент execute_arbitrary_code" in out

    @pytest.mark.asyncio
    async def test_tool_raises_returns_error_text(self):
        search = MagicMock()
        search.search = AsyncMock(side_effect=RuntimeError("взрыв"))
        router = ToolRouter(_deps(search=search))
        out = await router.dispatch("execute_web_search",
                                    {"query": "новости"}, _ctx())
        assert "ОШИБКА execute_web_search" in out


class TestExecuteWebSearch:
    @pytest.mark.asyncio
    async def test_success_formats_result(self):
        search = MagicMock()
        search.search = AsyncMock(return_value="Текст результатов")
        router = ToolRouter(_deps(search=search))
        out = await router.dispatch("execute_web_search", {"query": "РЖД"},
                                    _ctx("что по ржд?"))
        assert out == "Результаты поиска по запросу «РЖД»:\nТекст результатов"
        search.search.assert_awaited_once_with("РЖД", max_symbols=4000)

    @pytest.mark.asyncio
    async def test_all_engines_failed_structured_error(self):
        search = MagicMock()
        search.search = AsyncMock(
            side_effect=AllSearchEnginesFailedException("all down"))
        router = ToolRouter(_deps(search=search))
        out = await router.dispatch("execute_web_search", {"query": "x"}, _ctx())
        assert "ОШИБКА execute_web_search: поиск недоступен (all down)" in out

    @pytest.mark.asyncio
    async def test_query_falls_back_to_ctx_query(self):
        search = MagicMock()
        search.search = AsyncMock(return_value="данные")
        router = ToolRouter(_deps(search=search))
        await router.dispatch("execute_web_search", {}, _ctx("исходный вопрос"))
        search.search.assert_awaited_once_with("исходный вопрос", max_symbols=4000)

    @pytest.mark.asyncio
    async def test_timeout_bounded(self, monkeypatch):
        async def slow(query, max_symbols):
            await asyncio.sleep(5)
            return "поздно"

        search = MagicMock()
        search.search = slow
        import services.tool_router as tool_router_mod
        monkeypatch.setattr(tool_router_mod, "_SEARCH_TOOL_TIMEOUT", 0.2)
        router = ToolRouter(_deps(search=search))
        started = time.monotonic()
        out = await router.dispatch("execute_web_search", {"query": "x"}, _ctx())
        assert time.monotonic() - started < 2.0
        assert "ОШИБКА execute_web_search: поиск недоступен (timeout)" in out

    @pytest.mark.asyncio
    async def test_result_truncated_to_4000(self):
        search = MagicMock()
        search.search = AsyncMock(return_value="x" * 9000)
        router = ToolRouter(_deps(search=search))
        out = await router.dispatch("execute_web_search", {"query": "q"}, _ctx())
        # тело ≤ 4000 символов (+ заголовок инструмента и многоточие)
        assert "x" * 4001 not in out
        assert len(out) <= 4100
        assert out.endswith("…")


class TestQueryChatMemory:
    @pytest.mark.asyncio
    async def test_fts_hits_rendered_with_aliases(self):
        memory = MagicMock()
        now = int(time.time())
        rows = [_row(user_id=138811255, author_name="Леха",
                     text="я говорил про поездку", ts=now - 100),
                _row(user_id=10, author_name="вася",
                     text="а я про другое", ts=now - 50)]
        memory.search_long_term = AsyncMock(return_value=rows)
        memory.vector_search = AsyncMock(return_value=[])
        aliases = AliasResolver('{"138811255": "Леха", "10": "Вася"}')
        router = ToolRouter(_deps(memory=memory, aliases=aliases))
        out = await router.dispatch(
            "query_chat_memory", {"query": "поездка", "time_range": "all"}, _ctx())
        assert "[Леха" in out and "я говорил про поездку" in out
        assert "[Вася" in out and "а я про другое" in out
        assert not out.startswith("ОШИБКА")
        memory.vector_search.assert_not_called()   # FTS нашёл — вектор не нужен

    @pytest.mark.asyncio
    async def test_time_range_filters_old_rows(self):
        memory = MagicMock()
        now = int(time.time())
        rows = [_row(user_id=10, text="старое", ts=now - 200 * 3600),   # > 24h
                _row(user_id=10, text="свежее", ts=now - 3600)]
        memory.search_long_term = AsyncMock(return_value=rows)
        memory.vector_search = AsyncMock(return_value=["факт из архива"])
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "вчера", "time_range": "last_day"}, _ctx())
        assert "старое" not in out
        assert "свежее" in out
        # last_day → векторный шаг НЕ выполняется
        memory.vector_search.assert_not_called()
        # но время-фильтр применён к FTS-строкам
        assert "свежее" in out

    @pytest.mark.asyncio
    async def test_fts_empty_falls_to_vector_for_wide_windows(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.vector_search = AsyncMock(return_value=["факт: Леха ездил на море"])
        memory.get_rag_context = AsyncMock(return_value="")
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "море", "time_range": "all"}, _ctx())
        assert "факт: Леха ездил на море" in out
        memory.vector_search.assert_awaited_once_with(CHAT_ID, "море", limit=15)

    @pytest.mark.asyncio
    async def test_fts_empty_last_day_no_vector_no_rag_hit(self):
        """Узкое окно + пустой FTS → вектор не идёт; rag не найден → честное
        «ничего не найдено»."""
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.vector_search = AsyncMock(return_value=[])
        memory.get_rag_context = AsyncMock(return_value="")
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "ничего", "time_range": "last_day"},
            _ctx())
        assert "в памяти ничего не найдено" in out
        memory.vector_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_rag_context_used_when_still_empty(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.vector_search = AsyncMock(return_value=[])
        memory.get_rag_context = AsyncMock(return_value="<RAG>важный факт</RAG>")
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "факт"}, _ctx())
        assert "<RAG>важный факт</RAG>" in out
        memory.get_rag_context.assert_awaited_once_with(CHAT_ID, "факт")

    @pytest.mark.asyncio
    async def test_bad_time_range_defaults_to_all(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.vector_search = AsyncMock(return_value=[])
        memory.get_rag_context = AsyncMock(return_value="")
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "x", "time_range": "yesterday"}, _ctx())
        assert "ничего не найдено" in out

    @pytest.mark.asyncio
    async def test_memory_errors_fail_open_to_error_text(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(side_effect=RuntimeError("БД упала"))
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "x"}, _ctx())
        assert out.startswith("ОШИБКА query_chat_memory")

    @pytest.mark.asyncio
    async def test_result_truncated_to_3500(self):
        memory = MagicMock()
        long_text = "буква " * 2000
        rows = [_row(user_id=10, text=long_text, ts=int(time.time()))]
        memory.search_long_term = AsyncMock(return_value=rows)
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "x"}, _ctx())
        assert len(out) <= 3510
