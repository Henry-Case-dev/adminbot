"""P0-HA (снапшот 2026-10-29, §3/§7, slice DEPTH) — динамическая глубина
get_recent_history: depth без потолка 150, passthrough запрошенного объёма,
постраничное чтение БД (страницы от размера выборки), детерминированный
порядок с tie-break по PK, сохранённый таймаут, честный fetched/count лог.

Покрытие REQ: REQ-HA-DEPTH-CAPABILITY, REQ-HA-DEPTH-NO-CAP,
REQ-HA-DEPTH-DEFAULT, REQ-HA-DEPTH-PASSTHROUGH, REQ-HA-DEPTH-PAGES,
REQ-HA-DEPTH-NO-GLOBAL-MAX, REQ-HA-DEPTH-OVERSIZE-GRACE,
REQ-HA-P01-NO-CONSTANT-SWAP. SQLite in-memory / mocks, без сети.

Не входит в срез (владельцы TRUNC-PAGES/SEGMENTS): символьная усечка
результата (осталась как есть), continuation-поля tool-result, сегменты,
изоляция диапазона."""
import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import database as database_mod
from services.database import DatabaseService
from services.tool_router import (
    _HISTORY_DEFAULT_DEPTH,
    _HISTORY_TOOL_TIMEOUT,
    _history_depth,
    ToolContext,
    ToolDeps,
    ToolRouter,
)
from services.tool_schemas import TOOL_GET_RECENT_HISTORY

CHAT_ID = -1001234567890
OTHER_CHAT = -1009999999999


def _deps(memory=None, db=None) -> ToolDeps:
    return ToolDeps(search=MagicMock(), memory=memory or MagicMock(),
                    aliases=None, db=db)


def _ctx(query="") -> ToolContext:
    return ToolContext(CHAT_ID, query)


async def _make_db(seed: list[tuple[int, str]] | None = None,
                   chat_id: int = CHAT_ID) -> DatabaseService:
    """Реальная DatabaseService на SQLite in-memory; seed — (timestamp, text)."""
    db = DatabaseService(":memory:")
    await db.initialize()
    if seed:
        await db.db.executemany(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, timestamp, media_type, author_name) "
            "VALUES (?, ?, ?, ?, 'text', 'вася')",
            [(1, chat_id, text, ts) for ts, text in seed],
        )
        await db.db.commit()
    return db


class _CountingConn:
    """Прокси над aiosqlite-соединением: считает физические execute()."""

    def __init__(self, conn):
        self._conn = conn
        self.queries = 0

    async def execute(self, sql, *params):
        self.queries += 1
        return await self._conn.execute(sql, *params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


# ── 1. Passthrough depth: никакого клампа в пути (REQ-HA-DEPTH-PASSTHROUGH,
#    REQ-HA-DEPTH-NO-CAP, REQ-HA-P01-NO-CONSTANT-SWAP) ──────────────────────


class TestDepthPassthrough:
    @pytest.mark.parametrize("depth", [200, 400, 500, 2000, 5000])
    def test_history_depth_unit_no_cap(self, depth):
        assert _history_depth(depth) == depth

    @pytest.mark.asyncio
    @pytest.mark.parametrize("depth", [200, 400, 2000, 5000])
    async def test_dispatch_passes_depth_unchanged(self, depth):
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[])
        await ToolRouter(_deps(db=db)).dispatch(
            "get_recent_history", {"depth": depth}, _ctx())
        db.get_recent_messages.assert_awaited_once_with(CHAT_ID, depth)

    def test_default_50_when_absent_or_bad(self):
        """Дефолт 50 — только при отсутствии/кривом типе; он НЕ максимум."""
        assert _history_depth(None) == _HISTORY_DEFAULT_DEPTH == 50
        assert _history_depth("") == 50
        assert _history_depth("много") == 50
        assert _history_depth(0) == 1
        assert _history_depth(-5) == 1
        assert _history_depth(50) == 50          # явное значение сохраняется
        assert _history_depth(2000) == 2000      # …и не уменьшается до 50


# ── 2. JSON-схема: без maximum, учит точному числу ────────────────────────


class TestSchemaNoCap:
    def test_depth_schema_has_no_maximum(self):
        params = TOOL_GET_RECENT_HISTORY["function"]["parameters"]
        depth = params["properties"]["depth"]
        assert depth["type"] == "integer"
        assert depth["minimum"] == 1
        assert "maximum" not in depth

    def test_descriptions_teach_exact_depth(self):
        fn = TOOL_GET_RECENT_HISTORY["function"]
        tool_desc = fn["description"]
        depth_desc = fn["parameters"]["properties"]["depth"]["description"]
        # старый потолок исчез из обоих текстов
        assert "150" not in tool_desc
        assert "150" not in depth_desc
        # L1 явно учится передавать точное запрошенное число
        assert "exact" in tool_desc.lower()
        assert "exact" in depth_desc.lower()
        assert "no cap" in depth_desc.lower()
        # дефолт 50 остался задокументированным
        assert "default 50" in depth_desc.lower()

    def test_no_replacement_cap_constant_in_tool_router(self):
        """REQ-HA-DEPTH-NO-GLOBAL-MAX / H31: 150 не заменено новой константой-
        потолком выборки; в db-слое — только технический размер страницы."""
        import services.tool_router as tr
        assert not hasattr(tr, "_HISTORY_MAX_DEPTH")
        assert database_mod._RECENT_MESSAGES_PAGE_SIZE == 500


# ── 3. Детерминированный порядок с равными timestamp (§7) ─────────────────


class TestStableOrderingTies:
    @pytest.mark.asyncio
    async def test_tie_group_broken_by_id(self):
        """Равные timestamp: «последние N» детерминированы (id DESC в DESC-
        выборке), возврат ASC с tie-break id ASC."""
        db = await _make_db([
            (50, "a1"),    # id 1
            (50, "a2"),    # id 2
            (100, "b1"),   # id 3  ┐ tie-группа ts=100
            (100, "b2"),   # id 4  │
            (100, "b3"),   # id 5  ┘
            (200, "c1"),   # id 6  ┐ tie-группа ts=200
            (200, "c2"),   # id 7  │
            (200, "c3"),   # id 8  ┘
        ])
        try:
            rows = await db.get_recent_messages(CHAT_ID, 4)
            assert [r["id"] for r in rows] == [5, 6, 7, 8]
            assert [r["timestamp"] for r in rows] == [100, 200, 200, 200]
            # глубже — ровно вся tie-группа ts=100 по возрастанию id
            rows7 = await db.get_recent_messages(CHAT_ID, 7)
            assert [r["id"] for r in rows7] == [2, 3, 4, 5, 6, 7, 8]
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_chat_scope_and_asc_unchanged(self):
        """Скоуп по chat_id и хронологический ASC — прежние контракты."""
        db = await _make_db([(10, "своё 1"), (20, "своё 2")])
        await db.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, timestamp, media_type, author_name) "
            "VALUES (1, ?, 'чужое', 30, 'text', 'чужие')", (OTHER_CHAT,))
        await db.db.commit()
        try:
            rows = await db.get_recent_messages(CHAT_ID, 10)
            assert [r["text"] for r in rows] == ["своё 1", "своё 2"]
        finally:
            await db.db.close()


# ── 4. Постраничное чтение: страницы от размера выборки (§3.2) ────────────


class TestChunkedFetch:
    @pytest.mark.asyncio
    async def test_pages_derive_from_depth_small_page(self, monkeypatch):
        """depth=120 при странице 50 → 3 физических чтения, ровно 120 строк ASC."""
        db = await _make_db([(i, f"м{i}") for i in range(120)])
        monkeypatch.setattr(database_mod, "_RECENT_MESSAGES_PAGE_SIZE", 50)
        db.db = _CountingConn(db.db)
        try:
            rows = await db.get_recent_messages(CHAT_ID, 120)
            assert len(rows) == 120
            assert db.db.queries == 3                 # ceil(120/50)
            ids = [r["id"] for r in rows]
            assert ids == sorted(ids)                 # ASC
            assert ids[0] == 1 and ids[-1] == 120
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_returns_exactly_min_available_depth(self, monkeypatch):
        """Истории меньше, чем запрошено → ровно min(доступно, depth) (H7)."""
        db = await _make_db([(i, f"м{i}") for i in range(120)])
        monkeypatch.setattr(database_mod, "_RECENT_MESSAGES_PAGE_SIZE", 50)
        db.db = _CountingConn(db.db)
        try:
            rows = await db.get_recent_messages(CHAT_ID, 200)
            assert len(rows) == 120                   # не пусто, не 200
            assert db.db.queries == 3                 # последняя — короткая
            ids = [r["id"] for r in rows]
            assert ids == list(range(1, 121))
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_depth_5000_no_hidden_ceiling(self, monkeypatch):
        """depth=5000: постранично, без скрытого общего потолка (H6)."""
        db = await _make_db([(i, f"м{i}") for i in range(30)])
        monkeypatch.setattr(database_mod, "_RECENT_MESSAGES_PAGE_SIZE", 25)
        db.db = _CountingConn(db.db)
        try:
            rows = await db.get_recent_messages(CHAT_ID, 5000)
            assert len(rows) == 30                    # min(доступно, 5000)
            assert db.db.queries == 2                 # 25 + 5
            ids = [r["id"] for r in rows]
            assert ids == list(range(1, 31))
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_default_page_500_and_small_limit_single_query(self):
        """Дефолтная страница 500: 610 строк → 2 чтения; малый лимит
        (существующие вызовы ≤ страницы) — по-прежнему ОДИН запрос."""
        db = await _make_db([(i, f"м{i}") for i in range(610)])
        db.db = _CountingConn(db.db)
        try:
            rows = await db.get_recent_messages(CHAT_ID, 610)
            assert len(rows) == 610
            assert db.db.queries == 2                 # 500 + 110
            ids = [r["id"] for r in rows]
            assert ids == list(range(1, 611))
            db.db.queries = 0
            small = await db.get_recent_messages(CHAT_ID, 120)
            assert len(small) == 120
            assert db.db.queries == 1                 # старый одиночный путь
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_chunked_order_matches_single_read(self, monkeypatch):
        """Постраничный путь даёт тот же результат, что одиночное чтение."""
        seed = [(100 + i, f"сообщение {i}") for i in range(40)]
        db = await _make_db(seed)
        single = await db.get_recent_messages(CHAT_ID, 40)
        await db.db.close()

        db2 = await _make_db(seed)
        monkeypatch.setattr(database_mod, "_RECENT_MESSAGES_PAGE_SIZE", 7)
        db2.db = _CountingConn(db2.db)
        try:
            paged = await db2.get_recent_messages(CHAT_ID, 40)
            assert [(r["id"], r["text"]) for r in paged] == \
                [(r["id"], r["text"]) for r in single]
        finally:
            await db2.db.close()


# ── 5. Таймаут сохранён для больших depth (§3.3) ──────────────────────────


class TestTimeoutKept:
    @pytest.mark.asyncio
    async def test_depth_5000_still_under_timeout(self, monkeypatch):
        db = MagicMock()

        async def slow(chat_id, limit):
            assert limit == 5000                       # passthrough до отмены
            await asyncio.sleep(1.0)
            return []

        db.get_recent_messages = AsyncMock(side_effect=slow)
        monkeypatch.setattr(
            "services.tool_router._HISTORY_TOOL_TIMEOUT", 0.05)
        out = await ToolRouter(_deps(db=db)).dispatch(
            "get_recent_history", {"depth": 5000}, _ctx())
        assert out == "ОШИБКА get_recent_history: timeout"
        db.get_recent_messages.assert_awaited_once_with(CHAT_ID, 5000)

    def test_timeout_constant_untouched(self):
        assert _HISTORY_TOOL_TIMEOUT == 10.0


# ── 6. Лог-покрытие: fetched vs returned, без текстов (R17) ───────────────


class TestLogCoverage:
    @pytest.mark.asyncio
    async def test_fetched_vs_returned_logged(self, caplog):
        db = await _make_db([(i, f"т{i}") for i in range(60)])
        try:
            with caplog.at_level(logging.INFO):
                out = await ToolRouter(_deps(db=db)).dispatch(
                    "get_recent_history", {"depth": 60}, _ctx())
        finally:
            await db.db.close()
        record = next(r for r in caplog.records
                      if "get_recent_history |" in r.message)
        assert "fetched=60" in record.message
        assert "count=60" in record.message
        assert "out_chars=" in record.message

    @pytest.mark.asyncio
    async def test_fetched_counts_skipped_rows(self, caplog):
        """fetched — прочитано из БД; count — вошло в стенограмму."""
        db = MagicMock()
        db.get_recent_messages = AsyncMock(return_value=[
            {"user_id": 1, "author_name": "вася", "text": "виден",
             "timestamp": int(time.time()), "media_type": "text",
             "chat_id": CHAT_ID},
            {"user_id": 1, "author_name": "вася", "text": "   ",
             "timestamp": int(time.time()), "media_type": "text",
             "chat_id": CHAT_ID},
            {"user_id": 2, "author_name": "петя", "text": "тоже виден",
             "timestamp": int(time.time()), "media_type": "text",
             "chat_id": CHAT_ID},
        ])
        with caplog.at_level(logging.INFO):
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history", {"depth": 3}, _ctx())
        record = next(r for r in caplog.records
                      if "get_recent_history |" in r.message)
        assert "fetched=3" in record.message
        assert "count=2" in record.message
        assert "виден" not in caplog.text              # R17: текстов нет
