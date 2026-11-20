"""P0-CORRECTIVE HC-TIME (slice B) — temporal metadata before Writer.

Contract: `plans/features/p0-history-coverage-temporal-egress/
arch-contract-2026-11-21.md` §3 (B). Slices A/C are not modified.

Coverage:
* UTC rendering of message timestamps (`_ha_fmt_ts`, `_format_timestamp`,
  `format_utc_timestamp`) against the configured chat zone and DST;
* additive canonical segments: recorded-fact date, reply edge, edit stamp;
* `RetrievalCandidate` additive time taxonomy (defaults + constructors) with
  `sent_at`/score/ranking untouched; episode event window vs discovered_at;
* RAG fact 8th tuple `time_origin` and `_fact_prefix`/origin label;
* mandatory storage→Writer regression: a real `smart_messages` row whose
  `sent_at`/`edited_at`/`reply_to_id`/`reply_to_author_id` are selected,
  rendered and captured in the FINAL Writer `messages` (not only DTOs);
* one UTC legend in `time_line`, no duplicated text, empty line stays empty.

SQLite in-memory, no network, no production access. Assertions use synthetic
markers only; the evidence payload is anonymized separately.
"""
import dataclasses
import re
from unittest.mock import MagicMock

import pytest

from services import canonical_context as cc
from services import mca_retrieval_context as rc
from services import summary_memory as sm
from services.canonical_context import resolve_item_id as _resolve_item_id
from services.database import DatabaseService
from services.direct_chat_service import (
    DirectChatService,
    _ha_fmt_ts,
)
from services.summary_aliases import AliasResolver
from services.tool_router import (
    ToolDeps,
    ToolRouter,
    _format_timestamp,
    extract_history_window,
    resolve_history_window_at,
)

CHAT_ID = -100777000111
TS = 1704067200          # 2024-01-01 00:00 UTC (Monday)
EDITED = 1704067500      # 2024-01-01 00:05 UTC
SUMMER = 1721044800      # 2024-07-15 12:00 UTC (Berlin DST, +02:00)
CLOCK_BLOCK = (
    '<Chat_Time_Context source="server" phase="answer">\n'
    "local: 01.01.2024 03:00, Понедельник (Europe/Moscow, UTC+03:00)\n"
    "as_of_utc: 2024-01-01T00:00:00+00:00\n"
    "</Chat_Time_Context>"
)
UTC_LEGEND = "Метки времени сообщений в контексте — UTC."


# ── fixtures ────────────────────────────────────────────────────────────────

async def _make_temporal_db():
    """Real DatabaseService: one row with reply/edit/sent_at metadata."""
    db = DatabaseService(":memory:")
    await db.initialize()
    row_id = await db.save_smart_message(
        7, CHAT_ID, "маркер-текущее", 11, TS, "text", "Автор",
        message_id=12)
    await db.db.execute(
        "UPDATE smart_messages SET sent_at = ?, ingested_at = ?, "
        "edited_at = ?, reply_to_author_id = ? WHERE id = ?",
        (TS, TS + 5, EDITED, 9, row_id))
    await db.db.commit()
    return db, row_id


def _service(db, llm=None):
    llm = llm or MagicMock()
    router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                 aliases=None, db=db))
    return DirectChatService(llm, db, llm, AliasResolver("{}"),
                             tool_router=router)


async def _capture_writer_payload(*, time_line=CLOCK_BLOCK,
                                  user_blocks=None):
    """Call the real `_l2_write_answer`; return the actual `messages` payload."""
    from tests.test_direct_chat import FakeLLM, _make_service
    llm = FakeLLM(text="ok")
    svc = _make_service(llm=llm)
    result = await svc._l2_write_answer(
        CHAT_ID, "что было час назад", temperature=0.5,
        time_line=time_line,
        user_blocks=user_blocks or ["<Global_Context>\nфон\n</Global_Context>"])
    assert result is not None
    assert llm.messages, "Writer LLM did not receive messages"
    return llm.messages


# ── 1. UTC vs chat zone / DST ───────────────────────────────────────────────

class TestUtcRendering:
    def test_message_timestamp_renderers_are_utc(self):
        # A local-time `fromtimestamp` on a non-UTC host would shift these.
        assert _ha_fmt_ts(TS) == "01.01.2024 00:00 UTC"
        assert _format_timestamp(TS) == "2024-01-01 00:00 UTC"
        assert cc.format_utc_timestamp(TS) == "01.01.2024 00:00 UTC"
        assert _ha_fmt_ts("bad") == ""

    def test_fmt_ts_bytes_preserved(self):
        # `_fmt_ts` bytes are the accepted canonical contract: msg has
        # minutes (UTC), fact/archive keep the month only. B adds no hours.
        assert cc._fmt_ts(TS, with_time=True) == "01.01.2024 00:00 UTC"
        assert cc._fmt_ts(TS, with_time=False) == "01.2024"
        assert cc._fmt_ts(0, with_time=True) == ""
        assert cc._fmt_ts(None, with_time=False) == ""

    def test_chat_zone_and_dst_do_not_leak_into_utc_labels(self):
        winter = cc.format_chat_time(TS, "Europe/Berlin")
        summer = cc.format_chat_time(SUMMER, "Europe/Berlin")
        # Chat_Time_Context is local (IANA + DST), message labels stay UTC.
        assert "01.01.2024, 01:00" in winter
        assert "15.07.2024, 14:00" in summer
        assert _ha_fmt_ts(SUMMER) == "15.07.2024 12:00 UTC"

    def test_local_day_window_uses_passed_turn_as_of(self):
        spec = extract_history_window("вчера")
        assert spec is not None and spec.kind == "local_day"
        first = resolve_history_window_at(
            spec, as_of=TS, timezone="Europe/Berlin")
        second = resolve_history_window_at(
            spec, as_of=TS, timezone="Europe/Berlin")
        # 2024-01-01 00:00 UTC = 01:00 Berlin; "вчера" = 2023-12-31 local.
        assert first == second
        assert first["as_of"] == TS
        assert first["from"] == 1703977200
        assert first["to"] == 1704063599
        # A second `time.time()` would make the two calls drift; it must not.
        assert first["from"] < TS and first["to"] < TS


# ── 2. Canonical additive segments ──────────────────────────────────────────

class TestCanonicalTemporalSegments:
    def test_legacy_canonical_bytes_unchanged(self):
        line = cc.format_context_item(
            ts=TS, author="Автор [7]", item_id="tg:12", text="текст")
        assert line == (
            "[01.01.2024 00:00 UTC | Автор [7] | tg:12]: текст")

    def test_reply_and_edited_segments(self):
        line = cc.format_context_item(
            ts=TS, author="Автор [7]", item_id="tg:12", text="текст",
            reply_to="tg:11 (uid 9)", edited_at=EDITED)
        assert line == (
            "[01.01.2024 00:00 UTC | Автор [7] | tg:12 | "
            "ответ на tg:11 (uid 9) | ред. 01.01.2024 00:05 UTC]: текст")

    def test_recorded_fact_keeps_month_first(self):
        line = cc.format_context_item(
            ts=TS, author="Автор", item_id="fact:5", text="факт",
            kind=cc.KIND_FACT, time_origin=cc.TIME_ORIGIN_RECORDED)
        assert line == (
            "[01.2024 | дата записи | Автор | fact:5]: факт")
        # Existing per-point patterns still accept the additive segment.
        assert re.match(cc.canonical_line_pattern(cc.KIND_FACT), line)
        points = {p.pid: p for p in cc.CONTEXT_POINTS}
        assert re.match(points["legacy_rag"].pattern, line)
        assert re.match(points["direct_rag"].pattern,
                        "[chat_history] " + line)

    def test_source_origin_does_not_invent_hours_or_recorded(self):
        line = cc.format_context_item(
            ts=TS, author="Автор", item_id="fact:5", text="факт",
            kind=cc.KIND_FACT, time_origin=cc.TIME_ORIGIN_SOURCE)
        assert line == "[01.2024 | Автор | fact:5]: факт"
        assert "дата записи" not in line

    def test_speech_fallback_keeps_segments(self):
        line = cc.format_speech_item(
            ts=TS, author="Автор", item_id="tg:12", text="текст",
            reply_to="tg:11", edited_at=EDITED, projection=None)
        assert "ответ на tg:11" in line
        assert "ред. 01.01.2024 00:05 UTC" in line


# ── 3. RetrievalCandidate taxonomy ──────────────────────────────────────────

class TestRetrievalCandidateTemporalFields:
    def test_defaults_keep_all_constructors_compatible(self):
        cand = rc.RetrievalCandidate(
            id="msg:1", entity_type="message", entity_id="1")
        assert cand.time_kind == ""
        assert cand.recorded_at == 0
        assert cand.valid_from == 0 and cand.valid_to == 0
        assert cand.event_start == 0 and cand.event_end == 0
        assert cand.discovered_at == 0

    def test_message_candidate_source_and_recorded(self):
        cand = rc._message_candidate(
            {"id": 1, "tg_message_id": 12, "chat_id": CHAT_ID,
             "timestamp": TS, "sent_at": TS, "ingested_at": TS + 5,
             "user_id": 7, "text": "текст"},
            "lexical", 0, _resolve_item_id)
        assert cand.time_kind == "source"
        assert cand.sent_at == TS          # unchanged field
        assert cand.recorded_at == TS + 5
        assert cand.event_start == 0 and cand.discovered_at == 0

    def test_message_without_time_is_honest_unknown(self):
        cand = rc._message_candidate(
            {"id": 2, "chat_id": CHAT_ID, "timestamp": 0, "sent_at": None,
             "user_id": 7, "text": "без времени"},
            "lexical", 0, _resolve_item_id)
        assert cand.time_kind == "unknown"
        assert cand.sent_at == 0
        assert cand.recorded_at == 0

    def test_graph_fact_source_vs_recorded_not_mixed(self):
        source = rc._fact_candidate(
            {"id": 5, "fact": "факт", "chat_id": CHAT_ID,
             "message_timestamp": TS, "created_at": TS + 100,
             "rag_ts": TS, "valid_from": TS - 10, "valid_to": TS + 999,
             "subject_ref_id": 7, "origin": "chat_history"},
            "lexical", 0, _resolve_item_id)
        assert source.time_kind == "source"
        assert source.recorded_at == TS + 100
        assert source.sent_at == TS         # COALESCE(rag_ts…) unchanged
        assert source.valid_from == TS - 10
        assert source.valid_to == TS + 999

        recorded = rc._fact_candidate(
            {"id": 6, "fact": "факт", "chat_id": CHAT_ID,
             "message_timestamp": None, "created_at": TS + 100,
             "rag_ts": TS + 100, "origin": "chat_history"},
            "lexical", 1, _resolve_item_id)
        assert recorded.time_kind == "recorded"
        assert recorded.recorded_at == TS + 100
        assert recorded.sent_at == TS + 100

    def test_vector_meta_fact_uses_row_time_origin(self):
        cand = rc._fact_meta_candidate(
            {"id": 8, "fact": "факт", "chat_id": CHAT_ID,
             "rag_ts": TS, "message_timestamp": None,
             "created_at": TS + 50, "time_origin": "recorded",
             "subject_ref_id": 7},
            0, _resolve_item_id)
        assert cand.time_kind == "recorded"
        assert cand.recorded_at == TS + 50
        assert cand.sent_at == TS

    def test_episode_separates_event_window_and_discovered(self):
        cand = rc._episode_candidate(
            {"id": "ep_1", "topic": "событие", "last_ts": TS + 200,
             "event_start_ts": TS, "event_end_ts": TS + 100,
             "discovered_at": TS + 500},
            CHAT_ID, 0)
        assert cand.time_kind == "event"
        assert cand.event_start == TS
        assert cand.event_end == TS + 100
        assert cand.discovered_at == TS + 500
        assert cand.recorded_at == TS + 500
        assert cand.sent_at == TS + 200   # legacy last_ts unchanged
        # The event window is not silently reported as the discovery time.
        assert cand.discovered_at != cand.event_start

    def test_episode_without_event_columns_is_recorded_not_event(self):
        cand = rc._episode_candidate(
            {"id": "ep_2", "topic": "факт", "last_ts": TS,
             "created_at": TS + 10}, CHAT_ID, 0)
        assert cand.time_kind == "recorded"
        assert cand.event_start == 0 and cand.event_end == 0
        assert cand.discovered_at == TS + 10

    def test_time_kind_does_not_participate_in_score(self):
        base = rc._message_candidate(
            {"id": 1, "chat_id": CHAT_ID, "timestamp": TS, "user_id": 7,
             "text": "x"}, "lexical", 2, _resolve_item_id)
        substituted = dataclasses.replace(base, time_kind="unknown")
        assert substituted.score == base.score
        assert substituted.sent_at == base.sent_at


# ── 4. RAG fact tuple origin / recorded label ───────────────────────────────

class TestRagFactOrigin:
    def test_fact_time_origin_helper(self):
        helper = getattr(sm, "_fact_time_origin", None)
        assert helper is not None
        assert helper({"message_timestamp": TS, "created_at": TS + 1}) == \
            "source"
        assert helper({"message_timestamp": None, "created_at": TS + 1}) == \
            "recorded"
        assert helper({"message_timestamp": 0, "created_at": 0}) == "unknown"

    def test_recorded_prefix_and_origin_label(self):
        item = ("chat_history", "факт", TS, "Автор", "tg:5", "", False,
                "recorded")
        line = sm._format_origin_labeled_line(item)
        label = sm._ORIGIN_LABELS["chat_history"]
        assert line.startswith(f"[{label}] [01.2024 | дата записи | ")
        assert "| tg:5]: " in line
        # `_fact_prefix` keeps the month first.
        assert sm._fact_prefix(TS, "Автор", "recorded") == \
            "[01.2024 | дата записи | Автор: Автор] "

    def test_source_and_legacy_tuples_byte_parity(self):
        legacy = ("chat_history", "факт", TS, "Автор", "tg:5", "", False)
        source = legacy + ("source",)
        assert sm._format_origin_labeled_line(legacy) == \
            sm._format_origin_labeled_line(source)
        assert "дата записи" not in sm._format_origin_labeled_line(source)

    def test_build_rag_context_structure_unchanged(self):
        legacy = ("chat_history", "факт", TS, "Автор", "tg:5", "", False)
        recorded = legacy + ("recorded",)
        # `build_rag_context` structure/order is not changed by B: the 8th
        # element is consumed only by the direct origin-labeled renderer.
        assert sm.build_rag_context([legacy]) == \
            sm.build_rag_context([recorded])
        labeled = sm.build_rag_context([recorded], origin_labels=True)
        label = sm._ORIGIN_LABELS["chat_history"]
        assert labeled.startswith(
            f"[{label}] [01.2024 | дата записи | ")

    def test_direct_rag_tuple_carries_eighth_time_origin(self):
        from services.direct_chat_service import _rag_rows_with_ranks
        facts, _ranks = _rag_rows_with_ranks([{
            "origin": "chat_history", "fact": "факт", "rag_ts": TS,
            "message_timestamp": None, "created_at": TS + 10,
            "target_user": "Автор", "item_id": "fact:5",
            "forward_from": "", "expired": False, "time_origin": "recorded",
        }])
        assert len(facts[0]) == 8
        assert facts[0][7] == "recorded"
        line = sm._format_origin_labeled_line(facts[0])
        assert "| дата записи |" in line


# ── 5. Mandatory storage → Writer payload regression ────────────────────────

class TestStorageToWriterPayload:
    @pytest.mark.asyncio
    async def test_smart_window_selects_reply_edit_sent_at(self):
        db, _ = await _make_temporal_db()
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert len(rows) == 1
        row = rows[0]
        assert row["sent_at"] == TS
        assert row["edited_at"] == EDITED
        assert row["reply_to_author_id"] == 9
        assert row["reply_to_id"] == 11

    @pytest.mark.asyncio
    async def test_final_writer_messages_contain_reply_and_edit(self):
        db, _ = await _make_temporal_db()
        svc = _service(db)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        line = svc._context_row_line(rows[0], {}, trigger_message_id=12)
        assert "ответ на tg:11 (uid 9)" in line
        assert "ред. 01.01.2024 00:05 UTC" in line
        payload = await _capture_writer_payload(
            user_blocks=["<Global_Context>\n" + line + "\n</Global_Context>"])
        user = payload[1]["content"]
        # Actual model payload, not a DTO: fields and the UTC legend are there.
        assert "маркер-текущее" in user
        assert "ответ на tg:11 (uid 9)" in user
        assert "ред. 01.01.2024 00:05 UTC" in user
        assert user.count(UTC_LEGEND) == 1
        assert payload[0]["role"] == "system"
        assert payload[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_history_pages_show_reply_and_edit(self):
        db, _ = await _make_temporal_db()
        svc = _service(db)
        rows = await db.get_recent_messages(CHAT_ID, 10)
        lines = svc.tool_router._history_lines(rows, with_user_id=True)
        assert len(lines) == 1
        assert "ответ на tg:11 (uid 9)" in lines[0]
        assert "ред. 01.01.2024 00:05 UTC" in lines[0]
        assert "[7]" in lines[0]

    @pytest.mark.asyncio
    async def test_messages_around_selects_temporal_fields(self):
        db, _ = await _make_temporal_db()
        rows = await db.get_messages_around(CHAT_ID, 12, 1, 0)
        assert rows
        anchor = rows[-1]
        assert anchor["tg_message_id"] == 12
        assert anchor["edited_at"] == EDITED
        assert anchor["reply_to_author_id"] == 9
        assert anchor["sent_at"] == TS

    @pytest.mark.asyncio
    async def test_legacy_row_payload_has_no_invented_segments(self):
        db = DatabaseService(":memory:")
        await db.initialize()
        await db.save_smart_message(
            7, CHAT_ID, "обычная строка", None, TS, "text", "Автор",
            message_id=13)
        await db.db.commit()
        svc = _service(db)
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        line = svc._context_row_line(rows[0], {}, trigger_message_id=13)
        assert "ответ на" not in line
        assert "ред." not in line
        payload = await _capture_writer_payload(
            user_blocks=["<Global_Context>\n" + line + "\n</Global_Context>"])
        user = payload[1]["content"]
        assert "ответ на" not in user
        assert "ред." not in user


# ── 6. time_line legend (one, idempotent, empty-safe) ───────────────────────

class TestTimeLineLegend:
    @pytest.mark.asyncio
    async def test_legend_once_and_after_clock_block(self):
        payload = await _capture_writer_payload()
        user = payload[1]["content"]
        assert user.count(UTC_LEGEND) == 1
        assert user.count("<Chat_Time_Context") == 1
        assert user.index(UTC_LEGEND) > user.index("</Chat_Time_Context>")

    @pytest.mark.asyncio
    async def test_empty_time_line_adds_no_legend(self):
        payload = await _capture_writer_payload(time_line="")
        user = payload[1]["content"]
        assert UTC_LEGEND not in user

    @pytest.mark.asyncio
    async def test_legend_is_idempotent_on_repeated_assembly(self):
        payload = await _capture_writer_payload(
            time_line=CLOCK_BLOCK + "\n" + UTC_LEGEND)
        user = payload[1]["content"]
        assert user.count(UTC_LEGEND) == 1
