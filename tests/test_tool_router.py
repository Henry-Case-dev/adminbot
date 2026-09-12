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
        memory.count_mentions = AsyncMock(
            return_value={"count": 1, "first_seen": 1, "last_seen": 2})
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "x"}, _ctx())
        assert len(out) <= 3510


class TestQueryChatMemoryCount:
    """Bugfix 04.09.2026 (Часть 2, FR-19/AC-3.5): в выводе query_chat_memory
    — счётчик совпадений и диапазон дат (заголовок «Найдено N упоминаний»);
    count=0 → честная фраза; сбой count → fail-open (сниппеты без заголовка);
    last_day-лейбл; sqlite3.Row-строки нормализуются (T-678 прод-баг)."""

    @pytest.mark.asyncio
    async def test_header_with_count_and_period(self):
        memory = MagicMock()
        now = int(time.time())
        rows = [_row(user_id=10, text="бензин вчера", ts=now - 100)]
        memory.search_long_term = AsyncMock(return_value=rows)
        memory.count_mentions = AsyncMock(
            return_value={"count": 5, "first_seen": now - 5 * 86400,
                          "last_seen": now - 100})
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory",
            {"query": "бензин", "time_range": "last_week"}, _ctx())
        assert "Найдено 5 упоминаний «бензин» за неделю" in out
        assert "бензин вчера" in out
        memory.count_mentions.assert_awaited_once()
        args, kwargs = memory.count_mentions.await_args
        assert args[0] == CHAT_ID
        assert args[1] == ["бензин"]
        assert kwargs.get("since_ts", 0) > 0   # since_ts окна (не 0)

    @pytest.mark.asyncio
    async def test_header_all_time_with_dates(self):
        memory = MagicMock()
        now = int(time.time())
        rows = [_row(user_id=10, text="раз", ts=now - 100)]
        memory.search_long_term = AsyncMock(return_value=rows)
        memory.count_mentions = AsyncMock(
            return_value={"count": 2, "first_seen": now - 86400,
                          "last_seen": now - 100})
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "раз", "time_range": "all"}, _ctx())
        assert "Найдено 2 упоминаний «раз» за всё время" in out
        assert "(с " in out and " по " in out

    @pytest.mark.asyncio
    async def test_count_zero_but_rows_empty_honest_phrase(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.count_mentions = AsyncMock(
            return_value={"count": 0, "first_seen": None, "last_seen": None})
        memory.vector_search = AsyncMock(return_value=[])
        memory.get_rag_context = AsyncMock(return_value="")
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "ничего", "time_range": "all"},
            _ctx())
        assert "в памяти ничего не найдено" in out
        assert not out.startswith("Найдено")

    @pytest.mark.asyncio
    async def test_count_failure_fail_open_without_header(self, caplog):
        import logging
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            _row(user_id=10, text="строка есть", ts=int(time.time()))])
        memory.count_mentions = AsyncMock(side_effect=RuntimeError("БД упала"))
        router = ToolRouter(_deps(memory=memory))
        with caplog.at_level(logging.WARNING):
            out = await router.dispatch(
                "query_chat_memory", {"query": "x", "time_range": "all"},
                _ctx())
        assert "строка есть" in out
        assert not out.startswith("Найдено")
        assert any("count failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_last_day_label(self):
        memory = MagicMock()
        now = int(time.time())
        rows = [_row(user_id=10, text="свежий бензин", ts=now - 100)]
        memory.search_long_term = AsyncMock(return_value=rows)
        memory.count_mentions = AsyncMock(
            return_value={"count": 1, "first_seen": now - 100,
                          "last_seen": now - 100})
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory",
            {"query": "бензин", "time_range": "last_day"}, _ctx())
        assert "Найдено 1 упоминаний «бензин» за сутки" in out
        memory.vector_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_sqlite_row_rows_normalized(self):
        """T-678 (прод-лог): search_long_term отдаёт aiosqlite.Row без .get —
        нормализация в dict не даёт инструменту упасть."""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT 10 AS user_id, 'вася' AS author_name, "
                "'про бензин' AS text, ? AS timestamp",
                (int(time.time()) - 100,)).fetchone()
        finally:
            conn.close()
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[row])
        memory.count_mentions = AsyncMock(
            return_value={"count": 1, "first_seen": row["timestamp"],
                          "last_seen": row["timestamp"]})
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "бензин", "time_range": "all"},
            _ctx())
        assert "про бензин" in out
        assert "Найдено 1 упоминаний" in out

# ── Раунд 9 (AGI Memory, T-820, spec §3.2.1): dig_into_lore ────────────────

class TestDigIntoLore:
    """dig_into_lore: FTS-сниппеты L1 с датами + факты графа; пост-фильтры
    year/person; режимы messages/facts/both; «ничего не нашёл»; НЕ бросает;
    лимит 3500; флаг dig_enabled."""

    @staticmethod
    def _dig_row(user_id=10, author_name="вася", text="текст", ts=None):
        return {"user_id": user_id, "author_name": author_name, "text": text,
                "timestamp": ts}

    @pytest.mark.asyncio
    async def test_registered_in_dispatch(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.db = None                       # факты-этап отключён
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "как мы тогда"}, _ctx())
        assert "ничего не нашёл" in out

    @pytest.mark.asyncio
    async def test_mode_messages_renders_dated_snippets(self):
        memory = MagicMock()
        import datetime as _dt
        ts = int(_dt.datetime(2024, 5, 1).timestamp())
        memory.search_long_term = AsyncMock(return_value=[
            self._dig_row(user_id=10, author_name="вася",
                          text="ездили тогда на море", ts=ts)])
        memory.db = None                       # факты-этап отключён
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore",
            {"query": "море", "mode": "messages", "year": 2024}, _ctx())
        assert out.startswith("сообщения:")
        assert "[вася 2024-05-01]: ездили тогда на море" in out
        assert "факты:" not in out

    @pytest.mark.asyncio
    async def test_year_filter_applies_to_snippets(self):
        memory = MagicMock()
        import datetime as _dt
        rows = [
            self._dig_row(user_id=1, text="в 2023 писали", ts=int(
                _dt.datetime(2023, 6, 1).timestamp())),
            self._dig_row(user_id=1, text="в 2024 писали", ts=int(
                _dt.datetime(2024, 6, 1).timestamp())),
            self._dig_row(user_id=1, text="в 2025 писали", ts=int(
                _dt.datetime(2025, 6, 1).timestamp())),
        ]
        memory.search_long_term = AsyncMock(return_value=rows)
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "писали", "mode": "messages",
                              "year": 2024}, _ctx())
        assert "в 2024 писали" in out
        assert "в 2023 писали" not in out
        assert "в 2025 писали" not in out

    @pytest.mark.asyncio
    async def test_person_alias_filters_by_user_id(self):
        memory = MagicMock()
        rows = [
            self._dig_row(user_id=138811255, author_name="Леха",
                          text="леха писал про лето", ts=int(time.time()) - 10),
            self._dig_row(user_id=10, author_name="вася",
                          text="и вася про лето", ts=int(time.time()) - 5),
        ]
        memory.search_long_term = AsyncMock(return_value=rows)
        memory.db = None
        aliases = AliasResolver('{"138811255": "Леха", "10": "Вася"}')
        router = ToolRouter(_deps(memory=memory, aliases=aliases))
        out = await router.dispatch(
            "dig_into_lore", {"query": "лето", "person": "Леха",
                              "mode": "messages"}, _ctx())
        assert "леха писал про лето" in out
        assert "и вася про лето" not in out

    @pytest.mark.asyncio
    async def test_mode_facts_only(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        db = MagicMock()
        db.search_graph_facts_fts = AsyncMock(return_value=[{
            "id": 1, "fact": "Леха тогда купил машину", "origin": "chat_history",
            "created_at": 1, "target_user": "Леха", "weight": 0.5,
            "last_confirmed_at": 1, "message_timestamp": 1,
            "rag_ts": int(time.time()) - 3600}])
        memory.db = db
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "машина", "mode": "facts"}, _ctx())
        assert out.startswith("факты:")
        assert "Леха тогда купил машину" in out
        memory.search_long_term.assert_not_called()

    @pytest.mark.asyncio
    async def test_mode_facts_renders_dated_prefix(self):
        """F1/T-1420 (spec §3.6): факт графа рендерится единым RAG-хелпером
        «[{label}] [ММ.ГГГГ | Автор: X] текст (возможно устарело)»."""
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        import datetime as _dt
        ts = int(_dt.datetime(2023, 3, 15).timestamp())
        db = MagicMock()
        db.search_graph_facts_fts = AsyncMock(return_value=[{
            "id": 1, "fact": "Леха тогда купил машину", "origin": "chat_history",
            "created_at": ts, "target_user": "Леха", "weight": 0.5,
            "last_confirmed_at": 1, "message_timestamp": None,
            "rag_ts": ts}])
        memory.db = db
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "машина", "mode": "facts"}, _ctx())
        assert out.startswith("факты:")
        assert "[03.2023 | Автор: Леха] Леха тогда купил машину" in out
        assert "(Внимание: возможно устарело)" in out

    @pytest.mark.asyncio
    async def test_mode_facts_without_date_renders_origin_label_only(self):
        """Без даты (rag_ts=0) и без автора — только origin-метка, без
        временного префикса/пометки."""
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        db = MagicMock()
        db.search_graph_facts_fts = AsyncMock(return_value=[{
            "id": 1, "fact": "факт без даты", "origin": "chat_history",
            "created_at": 0, "target_user": None, "weight": 0.5,
            "last_confirmed_at": 0, "message_timestamp": 0, "rag_ts": 0}])
        memory.db = db
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "без даты", "mode": "facts"}, _ctx())
        assert "факт без даты" in out
        assert out.split("факты:")[1].strip() == "[чат] факт без даты"
        assert "(Внимание" not in out

    @pytest.mark.asyncio
    async def test_mode_both_has_both_sections(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            self._dig_row(text="про поездку в переписке", ts=int(time.time()))])
        db = MagicMock()
        db.search_graph_facts_fts = AsyncMock(return_value=[{
            "id": 1, "fact": "факт: поездка была в 2024", "origin": "chat_history",
            "created_at": 1, "target_user": None, "weight": 0.5,
            "last_confirmed_at": 1, "message_timestamp": 1,
            "rag_ts": int(time.time()) - 3600}])
        memory.db = db
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "поездка", "mode": "both"}, _ctx())
        assert out.index("сообщения:") < out.index("факты:")
        assert "про поездку в переписке" in out
        assert "факт: поездка была в 2024" in out

    @pytest.mark.asyncio
    async def test_empty_returns_nothing_found(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "чего-то древнего", "mode": "both"},
            _ctx())
        assert "ничего не нашёл по запросу" in out
        assert not out.startswith("ОШИБКА")

    @pytest.mark.asyncio
    async def test_bad_mode_defaults_to_both(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            self._dig_row(text="нашлось", ts=int(time.time()))])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "нашлось", "mode": "картинки"}, _ctx())
        assert "нашлось" in out

    @pytest.mark.asyncio
    async def test_error_stage_returns_error_text(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(
            side_effect=RuntimeError("БД упала"))
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "x", "mode": "messages"}, _ctx())
        assert "ОШИБКА dig_into_lore" in out

    @pytest.mark.asyncio
    async def test_messages_error_keeps_facts_section(self):
        """Ошибка этапа сообщений не роняет факты (spec: ошибка этапа →
        WARNING + секция пуста, рамка не бросает)."""
        memory = MagicMock()
        memory.search_long_term = AsyncMock(
            side_effect=RuntimeError("fts down"))
        db = MagicMock()
        db.search_graph_facts_fts = AsyncMock(return_value=[{
            "id": 1, "fact": "факт выжил", "origin": "chat_history",
            "created_at": 1, "target_user": None, "weight": 0.5,
            "last_confirmed_at": 1, "message_timestamp": 1,
            "rag_ts": int(time.time()) - 100}])
        memory.db = db
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "факт выжил", "mode": "both"}, _ctx())
        assert "факты:" in out and "факт выжил" in out
        assert "сообщения:" not in out

    @pytest.mark.asyncio
    async def test_result_truncated_to_3500(self):
        memory = MagicMock()
        long_text = "буква " * 2000
        memory.search_long_term = AsyncMock(return_value=[
            self._dig_row(text=long_text, ts=int(time.time()))])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "x", "mode": "messages"}, _ctx())
        assert len(out) <= 3600

    @pytest.mark.asyncio
    async def test_year_out_of_range_ignored(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            self._dig_row(text="недавнее", ts=int(time.time()))])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "недавнее", "mode": "messages",
                              "year": 1800}, _ctx())
        assert "недавнее" in out

    @pytest.mark.asyncio
    async def test_flag_off_returns_disabled(self, monkeypatch):
        from services import hot_config as hot
        class _FakeHotCache:
            def get(self, key, default=None):
                return {"flags.dig_enabled": False}.get(key, default)
        monkeypatch.setattr(hot, "_cache", _FakeHotCache())
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "x"}, _ctx())
        assert out == "Инструмент dig_into_lore отключен."


class TestDigFixRound:
    """Фикс-раунд (major-2): «N лет назад» из query без year (год = now.year
    − N); расширение ключей именами из графа (BFS по nodes/edges с глубиной
    limits.dig_graph_hop_depth, фолбэк target_user); лимиты читаются через
    hot (dig_max_symbols/snippets/facts)."""

    @staticmethod
    def _rows_by_year(*rows):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=list(rows))
        memory.db = None
        return memory

    @staticmethod
    def _ts(year, month=6, day=1):
        import datetime as _dt
        return int(_dt.datetime(year, month, day).timestamp())

    @pytest.mark.asyncio
    async def test_years_ago_phrase_sets_year(self):
        """«2 года назад» без year → год now.year − 2; сниппеты того года
        в выдаче, соседних лет — нет."""
        now_year = 2026   # фиксируем фактом из контекста раунда (runtime)
        year = now_year - 2
        memory = MagicMock()
        rows = [
            {"user_id": 1, "author_name": "вася", "text": "старое",
             "timestamp": self._ts(year)},
            {"user_id": 1, "author_name": "вася", "text": "совсем новое",
             "timestamp": self._ts(now_year - 1)},
            {"user_id": 1, "author_name": "вася", "text": "древнее",
             "timestamp": self._ts(now_year - 3)},
        ]
        memory.search_long_term = AsyncMock(return_value=rows)
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore",
            {"query": f"как мы ездили 2 года назад", "mode": "messages"},
            _ctx())
        assert "старое" in out
        assert "совсем новое" not in out
        assert "древнее" not in out

    @pytest.mark.asyncio
    async def test_word_years_ago_paruvsneskolko(self):
        """«пару/несколько лет назад» без числа → N = 2/3."""
        now_year = 2026
        for phrase, n in (("пару", 2), ("несколько", 3)):
            target = now_year - n
            memory = MagicMock()
            rows = [
                {"user_id": 1, "author_name": "вася", "text": "цель",
                 "timestamp": self._ts(target)},
                {"user_id": 1, "author_name": "вася", "text": "мимо",
                 "timestamp": self._ts(now_year)},
            ]
            memory.search_long_term = AsyncMock(return_value=rows)
            memory.db = None
            router = ToolRouter(_deps(memory=memory))
            out = await router.dispatch(
                "dig_into_lore",
                {"query": f"расскажи про {phrase} лет назад", "mode": "messages"},
                _ctx())
            assert "цель" in out, phrase
            assert "мимо" not in out, phrase

    @pytest.mark.asyncio
    async def test_graph_names_bfs_expands_query_tokens(self):
        """BFS по графу (nodes/edges) даёт имена — они уходят OR-токенами в
        FTS (search_long_term получает расширенный merged)."""
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            {"user_id": 7, "author_name": "антон", "text": "антон был на море",
             "timestamp": int(time.time())}])
        db = MagicMock()
        db.dig_graph_related_names = AsyncMock(return_value=["антон", "марина"])
        memory.db = db
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "поездка на море", "mode": "messages"},
            _ctx())
        args, kwargs = memory.search_long_term.await_args
        merged = args[1]
        assert "антон" in merged
        assert "марина" in merged
        db.dig_graph_related_names.assert_awaited_once()
        assert db.dig_graph_related_names.await_args.kwargs["max_depth"] == 2
        assert "антон был на море" in out

    @pytest.mark.asyncio
    async def test_person_expands_related_names_via_graph(self):
        """person задан (алиаса нет — без user_id-фильтра): seeds = формы
        имени person; связанные имена из графа расширяют FTS-запрос
        (сообщение от другого участника про связанного человека — в
        выдаче: OR-токен связанного имени)."""
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            {"user_id": 8, "author_name": "петя",
             "text": "петя ездил с василием на рыбалку",
             "timestamp": int(time.time())}])
        db = MagicMock()
        db.dig_graph_related_names = AsyncMock(return_value=["василий"])
        memory.db = db
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "рыбалка", "person": "Вася",
                              "mode": "messages"}, _ctx())
        args, kwargs = memory.search_long_term.await_args
        merged = args[1]
        assert "василий" in merged
        assert "петя ездил с василием на рыбалку" in out

    @pytest.mark.asyncio
    async def test_graph_empty_falls_back_to_target_user(self):
        """BFS пуст (узлы/рёбра не нашли) → фолбэк target_user: имена из
        фактов чата, содержащие токен person."""
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            {"user_id": 8, "author_name": "петя",
             "text": "петя вспоминал василия на рыбалке",
             "timestamp": int(time.time())}])
        db = MagicMock()
        db.dig_graph_related_names = AsyncMock(return_value=[])
        db.dig_fallback_target_names = AsyncMock(return_value=["василий"])
        memory.db = db
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "рыбалка", "person": "Вася",
                              "mode": "messages"}, _ctx())
        db.dig_fallback_target_names.assert_awaited_once()
        args, kwargs = memory.search_long_term.await_args
        assert "василий" in args[1]
        assert "петя вспоминал василия на рыбалке" in out

    @pytest.mark.asyncio
    async def test_graph_db_missing_is_fail_open(self):
        """memory.db None (нет графа) → ничего не падает, имена не
        расширяются, выдача как раньше."""
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            {"user_id": 1, "author_name": "вася", "text": "нашлось",
             "timestamp": int(time.time())}])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "нашлось", "mode": "messages"}, _ctx())
        assert "нашлось" in out

    @pytest.mark.asyncio
    async def test_limits_read_via_hot_and_symbols_limit(self, monkeypatch):
        """limits.dig_max_symbols/snippets/facts читаются через hot
        (фикс-раунд major-5: REGISTRY-ключи, не код-константы)."""
        from services import hot_config as hot
        class _FakeHotCache:
            def __init__(self, values):
                self._values = values
            def get(self, key, default=None):
                return self._values.get(key, default)
        monkeypatch.setattr(hot, "_cache", _FakeHotCache({
            "limits.dig_max_symbols": 500,
            "limits.dig_max_snippets": 1,
            "limits.dig_max_facts": 1,
        }))
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            {"user_id": 1, "author_name": "вася",
             "text": "длинный сниппет " + "буква " * 300,
             "timestamp": int(time.time())}])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "длинный", "mode": "messages"}, _ctx())
        # truncate = limit символов + многоточие
        assert len(out) <= 501
