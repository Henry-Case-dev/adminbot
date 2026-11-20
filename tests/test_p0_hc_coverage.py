"""P0-CORRECTIVE HC-COV (2026-11-21) — покрытие запрошенного периода.

Проверяет наблюдаемый контракт слайса A:
- чистая грамматика `extract_history_window` (duration/local_day/
  local_day_range/unresolved; голое «N часов» — не период);
- резолв в IANA-зоне чата (локальная полночь, DST spring/fall, диапазон дат);
- `capture_history_range` (реальные anchor/oldest/available, пустой range);
- `get_recent_history`: ctx range → хронология, FTS запрещён; range > страницы
  листается cursor'ом без потерь; пустой range — `range_empty`, не ошибка;
- coverage ledger: независимые `range_read`/`range_complete`/`skipped`,
  `lines`; coverage есть и для range, влезшего в один слот;
- `_history_partial` остаётся, но inline-пометка не вставляется в
  `<Global_Context>` на ходу с выборкой; L1 получает секцию «ОХВАТ ПЕРИОДА»;
- существующая capability `chat_history` детерминированно добавляется
  reply-плану с активным range; react/silent/clarify не форсируются;
- Writer-инструкция различает `range_read=1/range_complete=1` и `range_read=0`.

SQLite in-memory, без сети и LLM. Тексты сообщений в логи не попадают.
"""
import datetime
import time
import zoneinfo
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.database import DatabaseService
from services.direct_chat_service import (
    DirectChatService,
    _HISTORY_COVERAGE_HEADER,
    _force_history_range_plan,
    _history_range_note,
)
from services.direct_execution import ChainResult, EvidenceSource
from services.direct_l1 import (
    HISTORY_PARTIAL_INLINE,
    HISTORY_PARTIAL_LINE,
    HISTORY_RANGE_NOTE,
    HISTORY_RANGE_SECTION,
    L1Plan,
    build_l1_context,
)
from services.prompt_style_blocks import HISTORY_COVERAGE_ASSEMBLY_BLOCK
from services.summary_aliases import AliasResolver
from services.tool_router import (
    HistoryWindowSpec,
    ToolContext,
    ToolDeps,
    ToolRouter,
    capture_history_range,
    extract_history_window,
    parse_history_sample,
    resolve_history_window_at,
)
from services.tool_schemas import TOOL_GET_RECENT_HISTORY

CHAT_ID = -1001234567890
TZ = "Europe/Berlin"
AS_OF = int(datetime.datetime(
    2026, 11, 21, 12, 0, tzinfo=zoneinfo.ZoneInfo(TZ)).timestamp())


def _local_epoch(year, month, day, hour=0, minute=0, second=0) -> int:
    return int(datetime.datetime(
        year, month, day, hour, minute, second,
        tzinfo=zoneinfo.ZoneInfo(TZ)).timestamp())


async def _make_db(rows, *, chat_id=CHAT_ID) -> DatabaseService:
    """Реальная SQLite in-memory; rows — (timestamp, text[, media_type])."""
    db = DatabaseService(":memory:")
    await db.initialize()
    for index, row in enumerate(rows, start=1):
        if isinstance(row, dict):
            ts = int(row["ts"])
            text = str(row.get("text", ""))
            media = str(row.get("media", "text"))
        else:
            ts, text = int(row[0]), str(row[1])
            media = "text"
        await db.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, timestamp, media_type, author_name, "
            "tg_message_id) VALUES (1, ?, ?, ?, ?, 'автор', ?)",
            (chat_id, text, ts, media, index))
    await db.db.commit()
    return db


def _deps(db, memory=None) -> ToolDeps:
    return ToolDeps(search=MagicMock(), memory=memory or MagicMock(),
                    aliases=None, db=db)


def _router(db, memory=None) -> ToolRouter:
    return ToolRouter(_deps(db, memory))


def _ctx(query="", *, as_of=AS_OF) -> ToolContext:
    return ToolContext(CHAT_ID, query, turn_as_of=as_of)


def _header(out: str) -> dict:
    fields = parse_history_sample(out)
    assert fields is not None, out[:300]
    return fields


def _body(out: str) -> list[str]:
    start = out.find("@@END_HEADER")
    assert start >= 0
    start += len("@@END_HEADER")
    end = out.rfind("@@HISTORY_SAMPLE_END")
    assert end >= start
    chunk = out[start:end].strip("\n")
    return chunk.splitlines() if chunk else []


def _coverage(block: str) -> tuple[dict, list[str], list[str]]:
    lines = str(block or "").splitlines()
    assert lines and lines[0] == _HISTORY_COVERAGE_HEADER, block[:200]
    fields: dict = {}
    seg_lines: list[str] = []
    event_lines: list[str] = []
    after_end = False
    for line in lines[1:]:
        if line == "@@END_COVERAGE":
            after_end = True
            continue
        if line.startswith("seg "):
            seg_lines.append(line)
            continue
        if line.startswith("event "):
            event_lines.append(line)
            continue
        if not after_end and "=" in line:
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()
    return fields, seg_lines, event_lines


async def _range_turn(db, time_from: int, time_to: int, _, *,
                      as_of=AS_OF, query="что было за период"):
    """Захват range + первая страница инструмента → (ctx, raw, bound)."""
    router = _router(db)
    ctx = _ctx(query, as_of=as_of)
    bound = await capture_history_range(
        db, CHAT_ID, time_from, time_to, as_of=as_of)
    assert bound is not None
    ctx.history_sample = bound
    page = await router.dispatch("get_recent_history", {}, ctx)
    raw = ChainResult(page, evidence_sources=[
        EvidenceSource(tool="get_recent_history", status="ok",
                       content=page, total_chars=len(page))],
        chain_meta={})
    return ctx, raw, bound


def _service(db, llm=None, router=None) -> DirectChatService:
    return DirectChatService(
        MagicMock(), db, llm or MagicMock(), AliasResolver("{}"),
        tool_router=router or _router(db))


# ── 1. Чистая грамматика: только сильная временная граница ────────────────

class TestExtractWindow:
    @pytest.mark.parametrize("text, amount, unit", [
        ("Бот, напиши саммари, нахуя люди последние 10 часов срались",
         10, "hours"),
        ("что было за последние 24 часа", 24, "hours"),
        ("что случилось 30 минут назад", 30, "minutes"),
        ("полчаса назад был спор", 30, "minutes"),
        ("сутки назад всё сломалось", 1, "days"),
        ("последние 2 недели тишина", 2, "weeks"),
        ("за 3 дня до этого", 3, "days"),
    ])
    def test_duration_with_marker(self, text, amount, unit):
        spec = extract_history_window(text)
        assert spec is not None and spec.kind == "duration"
        assert (spec.amount, spec.unit) == (amount, unit)

    @pytest.mark.parametrize("text", [
        "просто болтаем 10 часов",
        "мне 10 часов ехать",
        "последние 400 сообщений",
        "оцени последние 2 000 реплик",
        "что было",
    ])
    def test_no_period_returns_none(self, text):
        assert extract_history_window(text) is None

    @pytest.mark.parametrize("text", [
        "последние 10 лет",
        "за 3 месяца",
        "с 5 ноября",
        "сегодня с 25:00 до 26:00",
    ])
    def test_period_like_but_unparsed_is_unresolved(self, text):
        spec = extract_history_window(text)
        assert spec is not None and spec.kind == "unresolved"

    def test_local_day_and_optional_clock(self):
        spec = extract_history_window("что было вчера с 22:00 до 23:30")
        assert spec.kind == "local_day" and spec.day_offset == -1
        assert spec.from_hm == (22, 0) and spec.to_hm == (23, 30)
        assert extract_history_window("позавчера").day_offset == -2
        assert extract_history_window("сегодня").day_offset == 0

    @pytest.mark.parametrize("text, expected", [
        ("с 5.11 по 7.11", ((5, 11, None), (7, 11, None))),
        ("с 5 ноября по 7 ноября 2026",
         ((5, 11, None), (7, 11, 2026))),
        ("с 5 по 7 ноября", ((5, 11, None), (7, 11, None))),
    ])
    def test_local_day_range(self, text, expected):
        spec = extract_history_window(text)
        assert spec.kind == "local_day_range"
        assert (spec.date_from, spec.date_to) == expected


# ── 2. Резолв: локальная полночь, границы, DST ────────────────────────────

class TestResolveWindow:
    def test_duration_is_absolute_seconds_from_as_of(self):
        spec = HistoryWindowSpec("duration", amount=10, unit="hours")
        resolved = resolve_history_window_at(spec, as_of=AS_OF, timezone=TZ)
        assert resolved == {"from": AS_OF - 10 * 3600, "to": AS_OF,
                            "as_of": AS_OF, "clamped": 0, "reason": ""}

    def test_local_day_uses_chat_midnight_not_server_zone(self):
        resolved = resolve_history_window_at(
            extract_history_window("сегодня"), as_of=AS_OF, timezone=TZ)
        assert resolved["from"] == _local_epoch(2026, 11, 21)
        assert resolved["to"] == AS_OF
        assert resolved["clamped"] == 1       # текущие сутки ещё не кончились

    def test_yesterday_is_full_local_day(self):
        resolved = resolve_history_window_at(
            extract_history_window("вчера"), as_of=AS_OF, timezone=TZ)
        assert resolved["from"] == _local_epoch(2026, 11, 20)
        assert resolved["to"] == _local_epoch(2026, 11, 20, 23, 59, 59)
        assert resolved["clamped"] == 0

    def test_local_day_with_clock(self):
        resolved = resolve_history_window_at(
            extract_history_window("вчера с 22:00 до 23:30"),
            as_of=AS_OF, timezone=TZ)
        assert resolved["from"] == _local_epoch(2026, 11, 20, 22, 0)
        assert resolved["to"] == _local_epoch(2026, 11, 20, 23, 30)

    def test_spring_forward_nonexistent_time_shifts_forward(self):
        as_of = _local_epoch(2026, 3, 29, 12, 0)
        resolved = resolve_history_window_at(
            extract_history_window("сегодня с 02:30 до 03:30"),
            as_of=as_of, timezone=TZ)
        start = datetime.datetime.fromtimestamp(
            resolved["from"], zoneinfo.ZoneInfo(TZ))
        end = datetime.datetime.fromtimestamp(
            resolved["to"], zoneinfo.ZoneInfo(TZ))
        assert (start.hour, start.minute) == (3, 0)
        assert (end.hour, end.minute) == (3, 30)

    def test_fall_back_ambiguous_time_uses_fold_zero(self):
        as_of = _local_epoch(2026, 10, 25, 12, 0)
        resolved = resolve_history_window_at(
            extract_history_window("сегодня с 02:30 до 03:00"),
            as_of=as_of, timezone=TZ)
        start = datetime.datetime.fromtimestamp(
            resolved["from"], zoneinfo.ZoneInfo(TZ))
        end = datetime.datetime.fromtimestamp(
            resolved["to"], zoneinfo.ZoneInfo(TZ))
        assert start.utcoffset() == datetime.timedelta(hours=2)   # fold=0
        assert end.utcoffset() == datetime.timedelta(hours=1)     # после fall

    def test_date_range_inclusive_end_of_day(self):
        resolved = resolve_history_window_at(
            extract_history_window("с 5.11 по 7.11"),
            as_of=AS_OF, timezone=TZ)
        assert resolved["from"] == _local_epoch(2026, 11, 5)
        assert resolved["to"] == _local_epoch(2026, 11, 7, 23, 59, 59)

    def test_date_range_crossing_new_year_uses_previous_year(self):
        as_of = _local_epoch(2026, 1, 15, 12, 0)
        resolved = resolve_history_window_at(
            extract_history_window("с 30.12 по 2.01"),
            as_of=as_of, timezone=TZ)
        start = datetime.datetime.fromtimestamp(
            resolved["from"], zoneinfo.ZoneInfo(TZ))
        end = datetime.datetime.fromtimestamp(
            resolved["to"], zoneinfo.ZoneInfo(TZ))
        assert (start.year, start.month, start.day) == (2025, 12, 30)
        assert (end.year, end.month, end.day) == (2026, 1, 2)

    def test_unresolved_has_concrete_reason(self):
        resolved = resolve_history_window_at(
            extract_history_window("последние 10 лет"),
            as_of=AS_OF, timezone=TZ)
        assert resolved["reason"] == "window_unresolved"


# ── 3. Захват диапазона и маршрут инструмента ─────────────────────────────

class TestCaptureAndRoute:
    @pytest.mark.asyncio
    async def test_bounds_are_real_rows_and_available_is_exact(self):
        db = await _make_db([
            (1000, "до"), (1010, "край-старт"), (1020, "середина"),
            (1030, "край-конец"), (1040, "после")])
        try:
            bound = await capture_history_range(
                db, CHAT_ID, 1010, 1030, as_of=1035)
            assert bound["window_kind"] == "time_range"
            assert (bound["anchor_ts"], bound["oldest_ts"]) == (1030, 1010)
            assert bound["available"] == bound["requested"] == 3
            assert bound["as_of"] == 1035 and bound["range_status"] == "ok"
            assert bound["sample_id"].startswith("hs_")
            assert len(bound["sample_id"]) == 15
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_empty_range_is_range_empty_not_error(self):
        db = await _make_db([(1000, "вне")])
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        try:
            bound = await capture_history_range(
                db, CHAT_ID, 2000, 3000, as_of=3000)
            assert bound["available"] == 0 and bound["requested"] == 0
            assert bound["anchor_ts"] == 0
            assert bound["range_status"] == "empty"
            ctx = _ctx("что было за период", as_of=3000)
            ctx.history_sample = bound
            out = await _router(db, memory).dispatch(
                "get_recent_history", {"query": "игнорируй-меня"}, ctx)
            header = _header(out)
            assert header["status"] == "empty_window"
            assert header["reason"] == "range_empty"
            assert header["available"] == 0 and header["has_next"] == 0
            assert header.get("cursor", "") == ""
            memory.search_long_term.assert_not_awaited()
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_range_bound_wins_over_query_fts_forbidden(self):
        rows = [(1000 + i * 10, f"m{i}") for i in range(30)]
        db = await _make_db(rows)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        try:
            ctx, _raw, _bound = await _range_turn(
                db, 1000, 1290, None, as_of=1295)
            out = await _router(db, memory).dispatch(
                "get_recent_history", {"query": "слово-которого-нет"}, ctx)
            header = _header(out)
            assert header["window_kind"] == "time_range"
            assert header["available"] == 30
            assert len(_body(out)) == 30
            memory.search_long_term.assert_not_awaited()
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_range_pages_cover_every_row_once(self):
        rows = [(1000 + i * 10, f"m{i}") for i in range(95)]
        db = await _make_db(rows)
        try:
            ctx, _raw, bound = await _range_turn(
                db, 1000, 1940, None, as_of=1945)
            router = _router(db)
            out = await router.dispatch("get_recent_history", {}, ctx)
            header = _header(out)
            assert header["has_next"] == 1
            assert header["requested"] == bound["available"] == 95
            seen: list[str] = []
            for _ in range(10):
                body = _body(out)
                assert body, "пустая страница в середине range-цепочки"
                seen.extend(line.partition("]: ")[2] for line in body)
                if header["has_next"] != 1:
                    break
                out = await router.dispatch(
                    "get_recent_history", {"cursor": header["cursor"]}, ctx)
                header = _header(out)
                assert header["window_kind"] == "time_range"
                assert header["window_from"] == bound["window_from"]
                assert header["window_to"] == bound["window_to"]
                assert header["as_of"] == bound["as_of"]
            assert seen == [f"m{i}" for i in range(95)]
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_tool_extracts_period_from_ctx_query_without_fts(self):
        now = int(time.time())
        db = await _make_db([
            {"ts": now - 300, "text": "в периоде"},
            {"ts": now - 7200 - 10, "text": "старое"}])
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        router = _router(db, memory)

        async def _tz(_chat_id):
            return "UTC"

        router._chat_timezone = _tz
        try:
            out = await router.dispatch(
                "get_recent_history", {},
                _ctx("что было за последние 2 часа", as_of=now))
            header = _header(out)
            assert header["window_kind"] == "time_range"
            assert header["window_to"] == now
            assert [line.partition("]: ")[2] for line in _body(out)] == \
                ["в периоде"]
            memory.search_long_term.assert_not_awaited()
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_tool_unresolved_period_fails_closed(self):
        db = await _make_db([(1000, "м")])
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        try:
            out = await _router(db, memory).dispatch(
                "get_recent_history", {},
                _ctx("что было за последние 10 лет"))
            assert out == "ОШИБКА get_recent_history: window_unresolved"
            memory.search_long_term.assert_not_awaited()
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_turn_capture_range_and_count_are_distinguished(self):
        now = int(time.time())
        db = await _make_db([
            {"ts": now - 100, "text": "a"},
            {"ts": now - 50, "text": "b"},
            {"ts": now - 8000, "text": "c"}])
        service = _service(db)

        async def _tz(_chat_id):
            return "UTC"

        service.tool_router._chat_timezone = _tz
        try:
            range_bound = await service._capture_turn_history_sample(
                CHAT_ID, "что было за последние 2 часа", now)
            assert range_bound["window_kind"] == "time_range"
            assert range_bound["available"] == 2
            count_bound = await service._capture_turn_history_sample(
                CHAT_ID, "последние 2 сообщения", now)
            assert "window_kind" not in count_bound
            assert count_bound["requested"] == 2
        finally:
            await db.db.close()


# ── 4. Coverage ledger: range_read/range_complete/lines/skipped ────────────

class TestCoverageLedger:
    @pytest.mark.asyncio
    async def test_short_range_still_gets_coverage_and_keeps_page(self):
        rows = [(1000 + i * 10, f"m{i}") for i in range(20)]
        db = await _make_db(rows)
        try:
            ctx, raw, bound = await _range_turn(
                db, 1000, 1190, None, as_of=1195)
            block = await _service(db).collect_history_segments(
                ctx, raw, slot_chars=100000, chat_id=CHAT_ID)
            assert block is not None and block.startswith(
                _HISTORY_COVERAGE_HEADER)
            fields, _, _ = _coverage(block)
            assert fields["range_read"] == "1"
            assert fields["range_complete"] == "1"
            assert fields["complete"] == "1"
            assert fields["available"] == "20"
            assert fields["processed"] == "20"
            assert fields["lines"] == "20"
            assert fields["skipped"] == "0"
            assert fields["window_kind"] == "time_range"
            # coverage головой, страница остаётся в том же EvidenceSource
            assert raw.evidence_sources[0].content.startswith(
                _HISTORY_COVERAGE_HEADER)
            assert "@@HISTORY_SAMPLE" in raw.evidence_sources[0].content
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_skipped_rows_are_counted_not_silently_dropped(self):
        rows = [(1000 + i * 10, f"m{i}") for i in range(20)]
        rows.insert(7, {"ts": 1070, "text": "", "media": "text"})
        db = await _make_db(rows)
        try:
            ctx, raw, bound = await _range_turn(
                db, 1000, 1200, None, as_of=1205)
            page_header = _header(raw.evidence_sources[0].content)
            assert page_header["skipped"] == 1
            assert page_header["lines"] == 20
            block = await _service(db).collect_history_segments(
                ctx, raw, slot_chars=100000, chat_id=CHAT_ID)
            fields, _, _ = _coverage(block)
            assert fields["available"] == "21"
            assert fields["processed"] == "21"
            assert fields["lines"] == "20"
            assert fields["skipped"] == "1"
            assert fields["range_complete"] == "1"
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_empty_range_coverage_is_complete_empty(self):
        db = await _make_db([(1000, "вне")])
        try:
            ctx, raw, bound = await _range_turn(
                db, 2000, 3000, None, as_of=3000)
            block = await _service(db).collect_history_segments(
                ctx, raw, slot_chars=100000, chat_id=CHAT_ID)
            fields, _, _ = _coverage(block)
            assert fields["range_read"] == "1"
            assert fields["range_complete"] == "1"
            assert fields["available"] == "0"
            assert fields["reason"] == "range_empty"
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_segmented_range_reports_complete_coverage(self):
        rows = [(1000 + i * 10, f"m{i}") for i in range(120)]
        db = await _make_db(rows)

        class _LLM:
            async def generate(self, messages, **kwargs):
                return '{"events":[],"status":"ok"}'

        try:
            ctx, raw, bound = await _range_turn(
                db, 1000, 2190, None, as_of=2195)
            block = await _service(db, _LLM()).collect_history_segments(
                ctx, raw, slot_chars=4000, chat_id=CHAT_ID)
            fields, seg_lines, _ = _coverage(block)
            assert fields["range_read"] == "1"
            assert fields["range_complete"] == "1"
            assert fields["available"] == "120"
            assert fields["processed"] == "120"
            assert fields["lines"] == "120"
            assert fields["failed"] == "0"
            assert seg_lines and all("status=ok" in ln for ln in seg_lines)
        finally:
            await db.db.close()

    def test_unread_capture_failed_is_range_read_zero(self):
        marker = {
            "sample_id": "", "window_kind": "time_range",
            "window_from": 1000, "window_to": 2000, "as_of": 2000,
            "range_status": "capture_failed", "reason": "db_error",
            "available": 0, "requested": 0,
        }
        block = DirectChatService._ensure_history_range_coverage(marker, "")
        assert "range_read=0" in block
        assert "range_complete=0" in block
        assert "reason=db_error" in block
        assert "available=" not in block
        assert "processed=" not in block

    def test_unread_not_checked_when_tool_never_delivered(self):
        marker = {
            "sample_id": "hs_x", "window_kind": "time_range",
            "window_from": 1000, "window_to": 2000, "as_of": 2000,
            "range_status": "ok", "available": 5, "requested": 5,
        }
        block = DirectChatService._ensure_history_range_coverage(marker, "")
        assert "range_read=0" in block and "reason=not_checked" in block

    def test_existing_coverage_not_duplicated(self):
        existing = ("@@HISTORY_COVERAGE v1\nrange_read=1\n"
                    "range_complete=1\n@@END_COVERAGE")
        marker = {"window_kind": "time_range", "range_status": "ok"}
        assert DirectChatService._ensure_history_range_coverage(marker, existing) == existing


# ── 5. Разделение причин: _history_partial vs range; L1-заметка ────────────

class TestCauseSeparation:
    @pytest.mark.asyncio
    async def test_inline_partial_suppressed_on_sampled_turn(
            self, monkeypatch):
        import services.direct_chat_service as dcs

        async def _summary_off(_chat_id):
            return False

        async def _cp_g(_chat_id, _key, default=None):
            return default

        monkeypatch.setattr(dcs, "chat_summary_enabled", _summary_off)
        monkeypatch.setattr(dcs, "_cp_g", _cp_g)
        window = [{"author_name": "вася", "text": "реплика",
                   "timestamp": 1000, "user_id": 1, "media_type": "text"}]

        class _Svc:
            db = MagicMock()
            aliases = AliasResolver("{}")

            @staticmethod
            def _history_window(rows, _trigger):
                return list(rows)

            @staticmethod
            def _context_row_line(row, _suffix, **_kw):
                return f"{row['author_name']}: {row['text']}"

            @staticmethod
            async def _history_partial(_chat_id, _window):
                return True

        svc = _Svc()
        parts = await DirectChatService._build_global_context_parts(
            svc, CHAT_ID, window,
            history_sample={"window_kind": "time_range",
                            "sample_id": "hs_x"})
        head = "\n".join(parts["head_lines"])
        assert "дословно последние 1 сообщений" in head
        assert HISTORY_PARTIAL_INLINE not in head
        # Без выборки — прежняя inline-пометка (байт-паритет)
        parts2 = await DirectChatService._build_global_context_parts(
            svc, CHAT_ID, window)
        assert HISTORY_PARTIAL_INLINE in "\n".join(parts2["head_lines"])

    def test_l1_range_note_is_separate_from_partial_line(self):
        text = build_l1_context(
            query="что было последние 10 часов",
            history_partial=True,
            history_range_note=HISTORY_RANGE_NOTE)
        assert f"[{HISTORY_RANGE_SECTION}]" in text
        assert HISTORY_RANGE_NOTE in text
        assert HISTORY_PARTIAL_LINE in text
        plain = build_l1_context(query="обычный вопрос")
        assert HISTORY_RANGE_SECTION not in plain

    def test_range_note_helper_only_for_range_sample(self):
        assert _history_range_note(
            {"window_kind": "time_range"}) == HISTORY_RANGE_NOTE
        assert _history_range_note({"window_kind": "count"}) == ""
        assert _history_range_note(None) == ""


# ── 6. Capability force и Writer-инструкция ───────────────────────────────

class TestForceAndWriterInstruction:
    def test_reply_plan_gets_chat_history(self):
        plan = L1Plan(action="reply")
        forced, flag = _force_history_range_plan(
            plan, [TOOL_GET_RECENT_HISTORY])
        assert flag is True
        assert "chat_history" in forced.capabilities_needed
        assert forced.execution_mode == "simple_tools"

    @pytest.mark.parametrize("action", ["react", "silent"])
    def test_non_reply_actions_are_not_forced(self, action):
        plan = L1Plan(action=action)
        forced, flag = _force_history_range_plan(
            plan, [TOOL_GET_RECENT_HISTORY])
        assert flag is False
        assert "chat_history" not in forced.capabilities_needed

    def test_clarification_is_not_forced(self):
        plan = L1Plan(action="reply", needs_clarification=True)
        forced, flag = _force_history_range_plan(
            plan, [TOOL_GET_RECENT_HISTORY])
        assert flag is False

    def test_missing_history_tool_is_not_forced(self):
        plan = L1Plan(action="reply")
        forced, flag = _force_history_range_plan(plan, [])
        assert flag is False

    def test_existing_capability_not_duplicated(self):
        plan = L1Plan(action="reply",
                      capabilities_needed=("chat_history",))
        forced, flag = _force_history_range_plan(
            plan, [TOOL_GET_RECENT_HISTORY])
        assert flag is False
        assert forced.capabilities_needed == ("chat_history",)

    def test_writer_instruction_distinguishes_range_states(self):
        text = HISTORY_COVERAGE_ASSEMBLY_BLOCK
        assert "range_read=1" in text and "range_complete=1" in text
        assert "range_read=0" in text
        assert "не заявляй" in text
        assert "не доказательство непрерывности всей переписки" in text
