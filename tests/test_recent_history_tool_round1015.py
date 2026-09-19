"""Раунд 10.15 (F9, T-1623) — инструмент `get_recent_history`
(кратковременная память): сырая хронологическая стенограмма последних
сообщений чата («Имя: текст»), НЕ векторный RAG.

Покрытие spec §8: путь `depth` (ASC, клампы 1..150), путь `query` (FTS +
фильтр окна + ASC), приоритет параметров, chat-скоуп, R16 (каскад имён),
R17 (без текста/URL в логах), сбой БД (структурная ошибка, fail-safe),
интеграция в F8 tool-сет. SQLite in-memory, без сети.
"""
import logging
import time
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.database import DatabaseService
from services.summary_aliases import AliasResolver
from services.tool_router import (
    _HISTORY_DEFAULT_DEPTH,
    _HISTORY_MAX_DEPTH,
    _HISTORY_MAX_SYMBOLS,
    _HISTORY_QUERY_WINDOW_SECONDS,
    _HISTORY_SEARCH_LIMIT,
    ToolContext,
    ToolDeps,
    ToolRouter,
)
from services.tool_schemas import TOOL_CALLING_TOOLS, TOOL_GET_RECENT_HISTORY

CHAT_ID = -1001234567890
OTHER_CHAT = -1009999999999
_EMPTY_PHRASE = "За последние сообщения ничего не нашлось"


def _deps(memory=None, db=None, aliases=None) -> ToolDeps:
    return ToolDeps(search=MagicMock(), memory=memory or MagicMock(),
                    aliases=aliases, db=db)


def _ctx(query="что обсуждали 10 минут назад") -> ToolContext:
    return ToolContext(CHAT_ID, query)


def _stamp(ts) -> str:
    """Ожидаемый канонический ts-сегмент (UTC, «ДД.ММ.ГГГГ ЧЧ:ММ») —
    10.20 (БЛОК 0, точка 8): строки get_recent_history несут ts."""
    return datetime.datetime.fromtimestamp(
        int(ts), datetime.timezone.utc).strftime("%d.%m.%Y %H:%M")


def _row(user_id=1, author_name="вася", text="сообщение", ts=None,
         media_type="text", chat_id=CHAT_ID) -> dict:
    return {"user_id": user_id, "author_name": author_name, "text": text,
            "timestamp": ts if ts is not None else int(time.time()),
            "media_type": media_type, "chat_id": chat_id}


async def _make_db(rows) -> DatabaseService:
    """Реальная DatabaseService на SQLite in-memory (DDL не вводится —
    переиспользуем уже существующий read-API get_recent_messages)."""
    db = DatabaseService(":memory:")
    await db.initialize()
    for row in rows:
        await db.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, timestamp, media_type, author_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (row.get("user_id"), row.get("chat_id", CHAT_ID), row.get("text"),
             row.get("timestamp"), row.get("media_type", "text"),
             row.get("author_name", "")))
    await db.db.commit()
    return db


# ── 1. Путь depth (хронологический срез) ─────────────────────────────────


class TestDepthPath:
    @pytest.mark.asyncio
    async def test_real_db_chronological_transcript_and_scope(self):
        """Реальная БД: последние N — строго ASC, «Имя: текст»; строки
        другого chat_id не попадают (chat-скоуп)."""
        rows = [
            _row(user_id=1, chat_id=OTHER_CHAT, text="чужой чат", ts=50,
                 author_name="чужие"),
            _row(user_id=1, chat_id=CHAT_ID, text="первое", ts=100),
            _row(user_id=2, chat_id=CHAT_ID, text="второе", ts=200,
                 author_name="петя"),
            _row(user_id=1, chat_id=CHAT_ID, text="третье", ts=300),
        ]
        db = await _make_db(rows)
        try:
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history", {"depth": 10}, _ctx())
        finally:
            await db.db.close()
        assert out.splitlines() == [
            f"[{_stamp(100)} | вася | msg:2]: первое",
            f"[{_stamp(200)} | петя | msg:3]: второе",
            f"[{_stamp(300)} | вася | msg:4]: третье",
        ]
        assert "чужой чат" not in out

    @pytest.mark.asyncio
    async def test_depth_clamped_to_max(self):
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[])
        await ToolRouter(_deps(db=db)).dispatch(
            "get_recent_history", {"depth": 9999}, _ctx())
        db.get_recent_messages.assert_awaited_once_with(
            CHAT_ID, _HISTORY_MAX_DEPTH)

    @pytest.mark.asyncio
    async def test_depth_zero_or_negative_clamped_to_one(self):
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[])
        router = ToolRouter(_deps(db=db))
        for raw in (0, -5):
            await router.dispatch("get_recent_history", {"depth": raw}, _ctx())
        assert db.get_recent_messages.await_count == 2
        for call in db.get_recent_messages.await_args_list:
            assert call.args == (CHAT_ID, 1)

    @pytest.mark.asyncio
    async def test_bad_depth_type_falls_back_to_default(self):
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[])
        await ToolRouter(_deps(db=db)).dispatch(
            "get_recent_history", {"depth": "много"}, _ctx())
        db.get_recent_messages.assert_awaited_once_with(
            CHAT_ID, _HISTORY_DEFAULT_DEPTH)

    @pytest.mark.asyncio
    async def test_no_params_uses_default_depth(self):
        """Ни depth, ни query, ни свободного текста → _HISTORY_DEFAULT_DEPTH."""
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[])
        router = ToolRouter(_deps(db=db))
        out = await router.dispatch("get_recent_history", {}, _ctx(""))
        db.get_recent_messages.assert_awaited_once_with(
            CHAT_ID, _HISTORY_DEFAULT_DEPTH)
        assert out == _EMPTY_PHRASE

    @pytest.mark.asyncio
    async def test_no_params_falls_back_to_ctx_query(self):
        """Follow-up R10.15-6 (spec §5): модель не передала query/depth, но
        есть свободный текст сообщения → используется как query."""
        now = int(time.time())
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            _row(text="нашлось по ctx.query", ts=now - 30)])
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[])
        out = await ToolRouter(_deps(memory=memory, db=db)).dispatch(
            "get_recent_history", {}, _ctx("что обсуждали"))
        assert "нашлось по ctx.query" in out
        memory.search_long_term.assert_awaited_once()
        db.get_recent_messages.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_depth_result_is_honest_phrase(self):
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[])
        out = await ToolRouter(_deps(db=db)).dispatch(
            "get_recent_history", {"depth": 50}, _ctx())
        assert out == _EMPTY_PHRASE
        assert not out.startswith("ОШИБКА")


# ── 2. Путь query (поиск по последним часам) ─────────────────────────────


class TestQueryPath:
    @pytest.mark.asyncio
    async def test_query_window_filter_and_asc_sort(self):
        now = int(time.time())
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            _row(user_id=1, text="слишком старое", ts=now - 20 * 3600),
            _row(user_id=2, text="свежее позже", ts=now - 60, author_name="петя"),
            _row(user_id=1, text="свежее раньше", ts=now - 120),
        ])
        out = await ToolRouter(_deps(memory=memory)).dispatch(
            "get_recent_history", {"query": "ссылка"}, _ctx())
        assert "слишком старое" not in out
        assert out.splitlines() == [
            f"[{_stamp(now - 120)} | вася]: свежее раньше",
            f"[{_stamp(now - 60)} | петя]: свежее позже",
        ]
        args, kwargs = memory.search_long_term.await_args
        assert args[0] == CHAT_ID                    # chat-скоуп
        assert args[1] == ["ссылка"]
        assert kwargs.get("limit") == _HISTORY_SEARCH_LIMIT

    @pytest.mark.asyncio
    async def test_window_constant_is_last_hours(self):
        assert _HISTORY_QUERY_WINDOW_SECONDS == 12 * 3600

    @pytest.mark.asyncio
    async def test_query_empty_result_honest_phrase(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        out = await ToolRouter(_deps(memory=memory)).dispatch(
            "get_recent_history", {"query": "несуществующее"}, _ctx())
        assert out == _EMPTY_PHRASE

    @pytest.mark.asyncio
    async def test_query_priority_over_depth(self):
        now = int(time.time())
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            _row(text="нашлось по query", ts=now - 30)])
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[])
        out = await ToolRouter(_deps(memory=memory, db=db)).dispatch(
            "get_recent_history", {"depth": 2, "query": "тема"}, _ctx())
        assert "нашлось по query" in out
        memory.search_long_term.assert_awaited_once()
        db.get_recent_messages.assert_not_awaited()


# ── 3. R16: каскад имён ──────────────────────────────────────────────────


class TestNameCascade:
    @pytest.mark.asyncio
    async def test_alias_then_author_then_user_id(self):
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[
            _row(user_id=555, author_name="", text="без имени", ts=1),
            _row(user_id=777, author_name="Автор", text="с автором", ts=2),
            _row(user_id=42, author_name="", text="только id", ts=3),
        ])
        aliases = AliasResolver('{"555": "Леха"}')
        out = await ToolRouter(_deps(db=db, aliases=aliases)).dispatch(
            "get_recent_history", {"depth": 3}, _ctx())
        assert out.splitlines() == [
            f"[{_stamp(1)} | Леха]: без имени",
            f"[{_stamp(2)} | Автор]: с автором",
            f"[{_stamp(3)} | 42]: только id",
        ]

    @pytest.mark.asyncio
    async def test_media_marker_and_blank_text_skipped(self):
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[
            _row(text="", media_type="video", ts=1),
            _row(text="   ", media_type="text", ts=2),
            _row(text="обычное", media_type="text", ts=3),
        ])
        out = await ToolRouter(_deps(db=db)).dispatch(
            "get_recent_history", {"depth": 3}, _ctx())
        assert out.splitlines() == [
            f"[{_stamp(1)} | вася]: [медиа: video]",
            f"[{_stamp(3)} | вася]: обычное",
        ]


# ── 4. R17: приватность логов ────────────────────────────────────────────


class TestR17:
    @pytest.mark.asyncio
    async def test_logs_have_no_text_or_url(self, caplog):
        secret = "СЕКРЕТНЫЙ-ТЕКСТ https://secret.example.com/x"
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[
            _row(text=secret, ts=1)])
        with caplog.at_level(logging.INFO):
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history", {"depth": 5}, _ctx())
        assert secret in out                       # модели — да (tool_result)
        assert "СЕКРЕТНЫЙ-ТЕКСТ" not in caplog.text
        assert "secret.example.com" not in caplog.text

    @pytest.mark.asyncio
    async def test_failure_logs_only_class_and_structured_error(self, caplog):
        db = MagicMock()
        db.get_recent_messages = AsyncMock(side_effect=RuntimeError("БД упала"))
        with caplog.at_level(logging.WARNING):
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history", {"depth": 5}, _ctx())
        assert out == "ОШИБКА get_recent_history: RuntimeError"
        assert any("get_recent_history failed" in r.message
                   for r in caplog.records)
        assert "БД упала" not in caplog.text

    @pytest.mark.asyncio
    async def test_query_stage_failure_structured(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(side_effect=RuntimeError("fts down"))
        out = await ToolRouter(_deps(memory=memory)).dispatch(
            "get_recent_history", {"query": "x"}, _ctx())
        assert out == "ОШИБКА get_recent_history: RuntimeError"

    @pytest.mark.asyncio
    async def test_missing_db_structured_error(self):
        out = await ToolRouter(_deps()).dispatch(
            "get_recent_history", {"depth": 5}, _ctx())
        assert out.startswith("ОШИБКА get_recent_history")
        assert "неизвестный инструмент" not in out


# ── 5. Обрезка результата ────────────────────────────────────────────────


class TestTruncate:
    @pytest.mark.asyncio
    async def test_long_history_truncated(self):
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[
            _row(text="x" * 9000, ts=1)])
        out = await ToolRouter(_deps(db=db)).dispatch(
            "get_recent_history", {"depth": 1}, _ctx())
        assert len(out) <= _HISTORY_MAX_SYMBOLS + 1
        assert out.endswith("…")


# ── 6. Интеграция в F8 tool-сет ──────────────────────────────────────────


class TestToolSetIntegration:
    def test_schema_registered_in_tool_set(self):
        # 10.20 (C/T-1887): tool-сет 7 → 8 (последним добавлен
        # compile_lore_story); 10.23 (F5/ADR-1023-5 D2): +generate_image → 9;
        # 10.24 (F19/ADR-1024-20 §2.1): +transcribe_video → 10;
        # get_recent_history сохранён по имени.
        names = [t["function"]["name"] for t in TOOL_CALLING_TOOLS]
        assert len(TOOL_CALLING_TOOLS) == 10
        assert "get_recent_history" in names
        assert TOOL_GET_RECENT_HISTORY in TOOL_CALLING_TOOLS

    def test_schema_shape(self):
        params = TOOL_GET_RECENT_HISTORY["function"]["parameters"]
        assert params["additionalProperties"] is False
        assert "required" not in params
        assert params["properties"]["depth"]["minimum"] == 1
        assert params["properties"]["depth"]["maximum"] == 150
        assert "query" in params["properties"]

    @pytest.mark.asyncio
    async def test_dispatch_finds_branch(self):
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[])
        out = await ToolRouter(_deps(db=db)).dispatch(
            "get_recent_history", {"depth": 1}, _ctx())
        assert "неизвестный инструмент" not in out
