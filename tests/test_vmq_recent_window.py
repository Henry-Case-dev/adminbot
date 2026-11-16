"""VMQ/MEM-TIME (16.11.2026, ARCH_DECISION) — окно времени `get_recent_history`.

Точечный фикс production-дефекта «бот, че было за последние пару часов»:
период передаётся СТРУКТУРОЙ (`time_window`), хронология окна читается
существующей страницей истории (нижний край time_from, верхний ≤ time_to),
FTS-путь получает since/until/order=time В SQL ДО limit, пустое окно/
отсутствие совпадений/техническая ошибка названы разными статусами, метки
времени — одна UTC-шкала с явной пометкой.

Покрытие A–G (см. задание Builder):
A точный 2-часовой интервал (границы включительно, ASC, window_from/to);
B фраза человека не становится FTS-query;
C empty_window vs no_match vs error и кривое окно → unsupported JSON;
D filter-before-limit (since/until/order=time; matched > limit → truncated);
E одна шкала времени (UTC+05 payload: нет ЧЧ:ММ без метки вне Chat_Time);
F 120 сообщений/2ч: cursor-страницы без дублей, remaining, boundary_to;
G границы окна/технический предел и неизменность Old_Episode-контракта.

SQLite in-memory, без сети. R17: в логах нет текстов/URL.
"""
import base64
import datetime
import hashlib
import hmac
import json
import re
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import runtime_probes as rp
from services.canonical_context import (
    CONTEXT_POINTS,
    _fmt_ts,
    format_context_item,
)
from services.database import DatabaseService
from services.direct_chat_service import _ha_fmt_ts
from services.tool_router import (
    _HISTORY_CURSOR_KEY,
    _HISTORY_SEARCH_LIMIT,
    _HISTORY_WINDOW_DEFAULT_SECONDS,
    _HISTORY_WINDOW_MAX_SECONDS,
    ToolContext,
    ToolDeps,
    ToolRouter,
    _format_timestamp,
    _history_cursor_decode,
    _history_sample_id,
    _history_window_label,
    capture_history_sample,
    parse_history_sample,
)
from services.tool_schemas import TOOL_GET_RECENT_HISTORY

CHAT_ID = -1001234567890
T0 = 1_700_000_000                       # 2023-11-14 22:13:20 UTC
_EMPTY_PHRASE = "За последние сообщения ничего не нашлось"


def _iso(ts) -> str:
    return datetime.datetime.fromtimestamp(
        int(ts), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _deps(db=None, memory=None) -> ToolDeps:
    return ToolDeps(search=MagicMock(), memory=memory or MagicMock(),
                    aliases=None, db=db)


def _ctx(query="", chat_id=CHAT_ID) -> ToolContext:
    return ToolContext(chat_id, query)


async def _make_db(rows) -> DatabaseService:
    db = DatabaseService(":memory:")
    await db.initialize()
    for index, row in enumerate(rows, start=1):
        await db.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, timestamp, media_type, author_name) "
            "VALUES (?, ?, ?, ?, 'text', ?)",
            (row.get("user_id", 1), row.get("chat_id", CHAT_ID),
             row.get("text", ""), row.get("ts", index),
             row.get("author", "вася")))
    await db.db.commit()
    return db


def _header(out: str) -> dict:
    fields = parse_history_sample(out)
    assert fields is not None, f"нет головы: {out[:200]!r}"
    return fields


def _body(out: str) -> list[str]:
    start = out.find("@@END_HEADER")
    assert start >= 0
    start += len("@@END_HEADER")
    end = out.rfind("@@HISTORY_SAMPLE_END")
    assert end >= start
    chunk = out[start:end].strip("\n")
    return chunk.splitlines() if chunk else []


def _texts(out: str) -> list[str]:
    return [line.partition("]: ")[2] for line in _body(out)]


def _window_rows(count: int, *, start_ts: int = T0, step: int = 60,
                 prefix: str = "m") -> list[dict]:
    return [{"text": f"{prefix}{i}", "ts": start_ts + i * step}
            for i in range(count)]


# ── A. Точный интервал: границы включительно, ASC, window_from/to ─────────


class TestExactWindow:
    @pytest.mark.asyncio
    async def test_two_hour_interval_edges_and_order(self):
        rows = [
            {"text": "до окна", "ts": T0 - 1},
            {"text": "край-старт", "ts": T0},
            {"text": "середина", "ts": T0 + 3600},
            {"text": "край-конец", "ts": T0 + 7200},
            {"text": "после окна", "ts": T0 + 7201},
        ]
        db = await _make_db(rows)
        try:
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history",
                {"time_window": {"since": _iso(T0),
                                 "until": _iso(T0 + 7200)}},
                _ctx("бот, че было за последние пару часов"))
        finally:
            await db.db.close()
        header = _header(out)
        assert header["status"] == "ok"
        assert (header["window_from"], header["window_to"]) == (T0, T0 + 7200)
        assert header["window_label"] == _history_window_label(T0, T0 + 7200)
        assert header["window_label"].endswith("UTC")
        assert header["window_label"].count("UTC") == 2   # обе границы
        # Границы включительно; всё вне окна отсутствует; порядок ASC.
        assert _texts(out) == ["край-старт", "середина", "край-конец"]
        assert "до окна" not in out and "после окна" not in out
        # Без depth окно возвращается целиком: requested=0, available=COUNT.
        assert header["requested"] == 0
        assert header["available"] == 3
        assert header["window_total"] == 3
        assert header["has_next"] == 0

    @pytest.mark.asyncio
    async def test_last_seconds_is_exact_relative_window(self):
        now = int(time.time())
        rows = [
            {"text": "в окне", "ts": now - 10},
            {"text": "старое", "ts": now - 7201},
        ]
        db = await _make_db(rows)
        try:
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history", {"time_window": {"last_seconds": 7200}},
                _ctx())
        finally:
            await db.db.close()
        header = _header(out)
        assert header["status"] == "ok"
        # Окно считается от now процесса: обе границы внутри допуска.
        assert header["window_to"] - header["window_from"] == 7200
        assert _texts(out) == ["в окне"]


# ── B. Фраза человека не становится FTS-query ─────────────────────────────


class TestPhraseIsNotQuery:
    @pytest.mark.asyncio
    async def test_ctx_query_ignored_when_window_present(self):
        now = int(time.time())
        db = await _make_db([
            {"text": f"m{i}", "ts": now - 600 + i} for i in range(5)])
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        try:
            out = await ToolRouter(_deps(db=db, memory=memory)).dispatch(
                "get_recent_history",
                {"time_window": {"last_seconds": 7200}},
                _ctx("бот, че было за последние пару часов"))
        finally:
            await db.db.close()
        # Ключевое: свободный текст хода НЕ стал поисковым запросом.
        memory.search_long_term.assert_not_awaited()
        memory.count_mentions.assert_not_called()
        header = _header(out)
        assert header["status"] == "ok"
        assert _texts(out) == [f"m{i}" for i in range(5)]
        assert out != _EMPTY_PHRASE

    def test_schema_teaches_structural_period(self):
        fn = TOOL_GET_RECENT_HISTORY["function"]
        props = fn["parameters"]["properties"]
        window = props["time_window"]
        assert window["type"] == "object"
        assert window["additionalProperties"] is False
        fields = window["properties"]
        assert set(fields) == {"since", "until", "last_seconds"}
        assert fields["last_seconds"]["type"] == "integer"
        assert fields["last_seconds"]["minimum"] == 1
        text = (fn["description"] + " " + window["description"]).lower()
        assert "last_seconds" in text
        assert "never put that phrase into query" in text
        assert "no_match" in fn["description"].lower()
        assert "empty_window" in fn["description"].lower()
        # Окно не добавляет required: обычные вызовы остаются совместимыми.
        assert "time_window" not in (fn["parameters"].get("required") or [])


# ── C. empty_window vs no_match vs error; кривое окно → unsupported ───────


class TestHonestStates:
    @pytest.mark.asyncio
    async def test_empty_window_is_not_no_match(self):
        now = int(time.time())
        db = await _make_db([{"text": "десять дней назад",
                              "ts": now - 10 * 24 * 3600}])
        try:
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history", {"time_window": {"last_seconds": 3600}},
                _ctx())
        finally:
            await db.db.close()
        header = _header(out)
        assert header["status"] == "empty_window"
        assert header["available"] == 0
        assert header["window_total"] == 0
        assert _body(out) == []
        assert out != _EMPTY_PHRASE                # окно ≠ «фраза без окна»

    @pytest.mark.asyncio
    async def test_no_match_when_window_has_messages(self):
        now = int(time.time())
        db = await _make_db([
            {"text": f"в окне {i}", "ts": now - 300 + i} for i in range(3)])
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.count_mentions = AsyncMock(return_value={"count": 0})
        try:
            out = await ToolRouter(_deps(db=db, memory=memory)).dispatch(
                "get_recent_history",
                {"time_window": {"last_seconds": 3600}, "query": "нет-такого"},
                _ctx())
        finally:
            await db.db.close()
        header = _header(out)
        assert header["status"] == "no_match"
        assert header["window_total"] == 3         # сообщения в окне БЫЛИ
        assert header["matched"] == 0
        assert _body(out) == []

    @pytest.mark.asyncio
    async def test_technical_error_is_error_status(self):
        now = int(time.time())
        db = await _make_db([{"text": "в окне", "ts": now - 60}])
        memory = MagicMock()
        memory.search_long_term = AsyncMock(side_effect=RuntimeError("fts down"))
        try:
            out = await ToolRouter(_deps(db=db, memory=memory)).dispatch(
                "get_recent_history",
                {"time_window": {"last_seconds": 3600}, "query": "x"},
                _ctx())
        finally:
            await db.db.close()
        header = _header(out)
        assert header["status"] == "error"
        assert header["reason"] == "search_failed"
        assert _body(out) == []
        assert not out.startswith("ОШИБКА")         # структура, не «пусто»

    @pytest.mark.asyncio
    async def test_broken_window_is_unsupported_json(self):
        out = await ToolRouter(_deps(db=MagicMock())).dispatch(
            "get_recent_history",
            {"time_window": {"since": "не-дата", "until": "тоже"}}, _ctx())
        payload = json.loads(out)
        assert payload["status"] == "unsupported"
        assert payload["reason_code"] == "invalid_time_window"
        assert parse_history_sample(out) is None


# ── D. Filter-before-limit: since/until/order в SQL ДО limit ──────────────


class TestFilterBeforeLimit:
    @pytest.mark.asyncio
    async def test_window_filters_reach_sql_and_truncation_named(self):
        rows = _window_rows(200, step=1, prefix="match-")
        db = await _make_db(rows)
        found = [{"text": row["text"], "timestamp": row["ts"],
                  "id": i + 1, "tg_message_id": None, "is_forward": 0,
                  "media_type": "text", "author_name": "вася", "user_id": 1}
                 for i, row in enumerate(rows[:80])]
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=found)
        memory.count_mentions = AsyncMock(return_value={"count": 200})
        try:
            out = await ToolRouter(_deps(db=db, memory=memory)).dispatch(
                "get_recent_history",
                {"time_window": {"since": _iso(T0),
                                 "until": _iso(T0 + 199)},
                 "query": "match"}, _ctx())
        finally:
            await db.db.close()
        _, kwargs = memory.search_long_term.await_args
        assert kwargs["since_ts"] == T0
        assert kwargs["until_ts"] == T0 + 199
        assert kwargs["order"] == "time"           # bounded план по окну
        assert kwargs["limit"] == _HISTORY_SEARCH_LIMIT
        header = _header(out)
        assert header["status"] == "ok"
        assert header["window_total"] == 200
        assert header["matched"] == 200
        assert header["truncated"] == 1
        assert header["incomplete"] == 1
        assert header["reason"] == "match_limit"
        assert header["remaining"] == 200 - 80
        assert header["has_next"] == 0
        assert not header.get("cursor")
        assert len(_body(out)) == 80

    @pytest.mark.asyncio
    async def test_legacy_query_also_filters_before_limit(self):
        """Без time_window путь query тоже шлёт окно в SQL (прежние 12ч)."""
        rows = [{"text": "свежее", "ts": int(time.time()) - 60}]
        db = await _make_db(rows)
        found = [{"text": "свежее", "timestamp": int(time.time()) - 60,
                  "id": 1, "author_name": "вася", "user_id": 1}]
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=found)
        try:
            await ToolRouter(_deps(db=db, memory=memory)).dispatch(
                "get_recent_history", {"query": "свежее"}, _ctx())
        finally:
            await db.db.close()
        _, kwargs = memory.search_long_term.await_args
        now = int(time.time())
        assert kwargs["since_ts"] >= now - 12 * 3600 - 5
        assert kwargs["until_ts"] >= now - 5
        assert kwargs["order"] == "time"


# ── E. Одна шкала: UTC+05 payload без ЧЧ:ММ без метки ─────────────────────


class TestSingleTimeScale:
    def test_msg_utc_and_fact_archive_unchanged(self):
        line = format_context_item(ts=1714500000, author="вася",
                                   item_id="msg:1", text="x")
        assert line == "[30.04.2024 18:00 UTC | вася | msg:1]: x"
        assert format_context_item(ts=1714500000, text="f",
                                   kind="fact") == "[04.2024]: f"
        archive = format_context_item(ts=1714500000, text="a",
                                      kind="archive")
        assert archive == "[Архивная справка: 04.2024]: a"
        assert "UTC" not in archive

    def test_one_utc_renderer_for_ha_and_tools(self):
        assert _fmt_ts(T0, with_time=True) == "14.11.2023 22:13 UTC"
        assert _ha_fmt_ts(T0) == _fmt_ts(T0, with_time=True)
        assert _ha_fmt_ts(0) == ""
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC",
                            _format_timestamp(T0))
        assert _format_timestamp(0) == ""

    def test_query_chat_memory_pattern_accepts_marked_and_legacy(self):
        point = next(p for p in CONTEXT_POINTS
                     if p.pid == "query_chat_memory")
        pattern = re.compile(point.pattern)
        assert pattern.match("[вася [2026-11-16 08:33 UTC]]: текст")
        assert pattern.match("[вася [2026-11-16 08:33]]: текст")

    @pytest.mark.asyncio
    async def test_history_payload_has_no_unmarked_hhmm(self):
        db = await _make_db(_window_rows(4))
        try:
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history",
                {"time_window": {"since": _iso(T0),
                                 "until": _iso(T0 + 180)}}, _ctx())
        finally:
            await db.db.close()
        # Вне <Chat_Time_Context> (его в tool-result нет) каждая ЧЧ:ММ
        # сопровождается явной меткой UTC — одна шкала во всём payload.
        assert re.findall(r"\d{2}:\d{2}(?! UTC)", out) == []
        assert " UTC | " in out


# ── F. 120 сообщений/2ч: страницы cursor без дублей ───────────────────────


class TestWindowPagination:
    @pytest.mark.asyncio
    async def test_120_messages_two_hours_pages(self):
        rows = _window_rows(120)
        last_ts = T0 + 119 * 60
        db = await _make_db(rows)
        try:
            router = ToolRouter(_deps(db=db))
            ctx = _ctx()
            out = await router.dispatch(
                "get_recent_history",
                {"time_window": {"since": _iso(T0), "until": _iso(last_ts)}},
                ctx)
            pages = []
            for _ in range(10):
                header = _header(out)
                body = _body(out)
                pages.append((header, body))
                # Окно переживает каждую страницу через cursor.
                assert (header["window_from"], header["window_to"]) == \
                    (T0, last_ts)
                if header.get("has_next") != 1:
                    break
                assert header["cursor"].startswith("v3.")
                out = await router.dispatch(
                    "get_recent_history", {"cursor": header["cursor"]}, ctx)
            else:                                   # pragma: no cover
                pytest.fail("цепочка cursor не завершилась")
        finally:
            await db.db.close()
        assert len(pages) == 3
        first, second, last = (p[0] for p in pages)
        assert (first["available"], first["processed"], first["remaining"],
                first["has_next"]) == (120, 40, 80, 1)
        assert (second["processed"], second["remaining"],
                second["has_next"]) == (80, 40, 1)
        assert (last["processed"], last["remaining"],
                last["has_next"]) == (120, 0, 0)
        seen = [line for _, body in pages for line in body]
        assert len(seen) == 120 and len(set(seen)) == 120   # без дублей
        assert [line.partition("]: ")[2] for line in seen] == \
            [f"m{i}" for i in range(120)]
        assert f"m119" in seen[-1]
        assert last["boundary_to"] == f"{last_ts}:120"
        # page_to последней страницы — свежайшее сообщение окна.
        assert last["page_to"] == f"{last_ts}:120"


# ── G. Границы окна/предел; Old_Episode-контракт не тронут ────────────────


class TestWindowBoundaries:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("window,reason", [
        ({"last_seconds": 0}, "time_window_out_of_range"),
        ({"last_seconds": _HISTORY_WINDOW_MAX_SECONDS + 1},
         "time_window_out_of_range"),
        ({"since": "2020-01-01T00:00:00Z"}, "time_window_too_wide"),
        ({"since": "2026-11-16T00:00:00Z", "last_seconds": 60},
         "time_window_ambiguous"),
        ({"until": "2099-01-01T00:00:00Z"}, "time_window_in_future"),
        ({"until": "not-a-date"}, "invalid_time_window"),
        ({}, "invalid_time_window"),
        ("x", "time_window_must_be_object"),
        ({"foo": 1}, "time_window_unknown_field"),
    ])
    async def test_invalid_window_explicit_refusal(self, window, reason):
        out = await ToolRouter(_deps(db=MagicMock())).dispatch(
            "get_recent_history", {"time_window": window}, _ctx())
        payload = json.loads(out)
        assert payload["status"] == "unsupported"
        assert payload["reason_code"] == reason
        assert "window_from" not in payload
        assert parse_history_sample(out) is None

    def test_parse_time_window_without_limits_is_shared(self):
        now = 1_800_000_000
        window, reason = rp.parse_time_window(
            {"last_seconds": 7200}, now=now,
            max_seconds=_HISTORY_WINDOW_MAX_SECONDS)
        assert reason == "" and window == (now - 7200, now)
        window, reason = rp.parse_time_window(
            {"last_seconds": 7200}, now=now,
            default_seconds=_HISTORY_WINDOW_DEFAULT_SECONDS,
            max_seconds=_HISTORY_WINDOW_MAX_SECONDS)
        assert reason == "" and window == (now - 7200, now)
        window, reason = rp.parse_time_window(
            {"until": _iso(now)}, now=now,
            default_seconds=_HISTORY_WINDOW_DEFAULT_SECONDS,
            max_seconds=_HISTORY_WINDOW_MAX_SECONDS)
        assert reason == ""
        assert window == (now - _HISTORY_WINDOW_DEFAULT_SECONDS, now)

    @pytest.mark.asyncio
    async def test_until_only_uses_documented_tail(self):
        now = int(time.time())
        db = await _make_db([{"text": "вчера", "ts": now - 1200}])
        try:
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history", {"time_window": {"until": _iso(now)}},
                _ctx())
        finally:
            await db.db.close()
        header = _header(out)
        assert header["window_to"] == now
        assert header["window_from"] == now - _HISTORY_WINDOW_DEFAULT_SECONDS
        assert _texts(out) == ["вчера"]

    @pytest.mark.asyncio
    async def test_depth_caps_sample_inside_window(self):
        db = await _make_db(_window_rows(10))
        try:
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history",
                {"time_window": {"since": _iso(T0),
                                 "until": _iso(T0 + 540)}, "depth": 3},
                _ctx())
            # depth больше окна: доступно ровно окно, requested честно
            # сохранён (дефолт/запрос не подменяются).
            out2 = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history",
                {"time_window": {"since": _iso(T0),
                                 "until": _iso(T0 + 540)}, "depth": 50},
                _ctx())
        finally:
            await db.db.close()
        header = _header(out)
        assert header["requested"] == 3
        assert header["available"] == 3
        assert header["window_total"] == 10
        assert _texts(out) == ["m7", "m8", "m9"]
        header2 = _header(out2)
        assert header2["requested"] == 50
        assert header2["available"] == 10
        assert len(_body(out2)) == 10

    @pytest.mark.asyncio
    async def test_capture_without_window_is_byte_parity(self):
        """Контракт `ctx.history_sample` (вход Old_Episode) не изменён:
        без окна — те же ключи/границы/sample_id, что и до VMQ-фикса."""
        db = await _make_db(_window_rows(5))
        try:
            bound = await capture_history_sample(db, CHAT_ID, 3)
        finally:
            await db.db.close()
        assert bound is not None
        expected = "hs_" + hashlib.sha256(
            f"{CHAT_ID}|{T0 + 4 * 60}|5|3".encode("utf-8")).hexdigest()[:12]
        assert bound["sample_id"] == expected
        assert bound["anchor_ts"] == T0 + 4 * 60
        assert bound["oldest_ts"] == T0 + 2 * 60
        assert bound["requested"] == 3
        assert bound["available"] == 3
        assert "window_from" not in bound
        assert "window_total" not in bound

    @pytest.mark.asyncio
    async def test_windowed_tool_does_not_touch_old_episode_pipeline(
            self, monkeypatch):
        """Новый путь окна не вызывает L1-retrieval/Old_Episode и не мутирует
        выборку хода: это H37-совместимая изоляция, не второй пайплайн."""
        calls: list[str] = []

        def _boom(*args, **kwargs):
            calls.append("retrieve")
            raise AssertionError("mca retrieve must not run")

        monkeypatch.setattr(
            "services.mca_retrieval_context.retrieve", _boom)
        db = await _make_db(_window_rows(6))
        try:
            bound = await capture_history_sample(db, CHAT_ID, 6)
            ctx = _ctx(query="последние пару часов")
            ctx.history_sample = dict(bound)
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history",
                {"time_window": {"last_seconds": 7200}}, ctx)
        finally:
            await db.db.close()
        assert calls == []
        header = _header(out)
        # Зафиксированная выборка хода сильнее окна: контракт Old_Episode
        # (реальные края N-выборки) не подменён.
        assert header["requested"] == 6
        assert header["boundary_from"].endswith(f"{T0}:1")
        assert ctx.history_sample == bound

    @pytest.mark.asyncio
    async def test_cursor_rejects_foreign_window_shape(self):
        """v3 cursor с окном только по одному краю/перевёрнутым — отказ."""
        sample_id = _history_sample_id(CHAT_ID, T0, 5, 10)
        payload = "|".join(str(v) for v in (
            "v3", CHAT_ID, T0, 5, T0, 1, 10, 10, 0, T0, 2,
            int(time.time()) + 300, sample_id, 1000, 0))
        token = base64.urlsafe_b64encode(
            payload.encode("ascii")).decode("ascii").rstrip("=")
        sig = hmac.new(_HISTORY_CURSOR_KEY, payload.encode("ascii"),
                       hashlib.sha256).hexdigest()[:16]
        cursor = f"v3.{token}.{sig}"
        assert _history_cursor_decode(cursor, CHAT_ID)[1] == "unknown_cursor"
