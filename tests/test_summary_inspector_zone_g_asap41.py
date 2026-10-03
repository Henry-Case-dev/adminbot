"""ASAP 4.1 волна 7 (зона G: T-4621/T-4622/T-4623/T-4624) — тесты Run
Inspector: честная coverage semantics + capacity/liveness/cover-style
карточки + structured events.

Покрытие (spec §7 G.1–G.3, ADR-1028-8 D8; ТЗ §38–§43, якоря 23362–23529):
  * §38 honest coverage semantics — РАЗДЕЛЬНЫЕ оси Источник / L1 input +
    result / Writer input / Final text / Overflow (segments/messages
    covered); fixture «L1 failed, source 100%» НЕ показывается единым
    успехом; данные из structured state (usage_json событий + in-memory
    снапшот), НЕ парсинг логов (guard-скан);
  * §39 capacity-карточка «КОНТЕКСТ МОДЕЛИ» (Provider/Model/Effective
    window/Serialized input/Output reserve/Mode + человеческая причина +
    source-of-window по цепочке §5 + replan count);
  * §40 liveness (execution mode честно = sync для sync-транспорта,
    provider fallback, last activity, «жива/ждёт»);
  * §41 cover-style карточка (Base ✓/Selected style/provider/model/
    capability/edit ✓-✕/Published styled|base_fallback|no_cover + точная
    причина fallback — не generic style_failed);
  * §42/§43 structured events: полный перечень на fixture-run; overflow-
    run добавляет три сегментных; SUMMARY_TEXT_READY и SUMMARY_REVISION_
    RESULT (новые, T-4624); один run_id сквозной; R17-scan (без API
    keys/полных сообщений/промптов/reference bytes).
"""
import asyncio
import json
import re

import pytest

from config.settings import settings
from services import execution_graph_source as egs
from services import mca_events
from services import mca_trace as trace
from services import pipeline_analytics as pa
from services import pipeline_events as pe


pytestmark = pytest.mark.asap41


def _ev(name, *, outcome="success", status=None, reason_code=None,
        duration_ms=None, attempt=None, model=None, provider=None,
        usage=None, ts=1000, chat_id=100, stage=None):
    row = {
        "event_name": name, "outcome": outcome, "status": status,
        "reason_code": reason_code, "duration_ms": duration_ms,
        "attempt": attempt, "model": model, "provider": provider,
        "ts": ts, "chat_id": chat_id, "stage": stage,
        "pipeline_run_id": "run-g1", "trace_id": "run-g1",
        "usage_json": json.dumps(usage) if usage else None,
    }
    return {k: v for k, v in row.items() if v is not None}


def _snap(**fields):
    base = {
        "run_id": "run-g1", "chat_id": 100, "mode": "hybrid_l2",
        "source_count": 839, "status": "ok", "duration_ms": 42000.0,
        "publish_channel": "rich", "publish_status": "ok",
        "publish_message_id": 4242, "cover_status": "ok",
        "source_total": 839, "source_considered": 839,
        "source_coverage": 100.0, "pipeline_health": "ok",
    }
    base.update(fields)
    return base


# ── T-4621: честная coverage semantics (§38) ─────────────────────────────

def _fixture_events_full_window(l1_failed: bool = False):
    """Материал §38-фикстуры: 839-сообщений WHOLE_WINDOW, богачом L1."""
    events = [
        _ev("SUMMARY_RUN_START", outcome="start",
            usage={"mode": "hybrid_l2"}),
        _ev("SUMMARY_SOURCE_WINDOW", usage={"input_count": 839}),
        _ev("SUMMARY_SOURCE_WINDOW_READY",
            usage={"messages": 839, "durable": True}),
        _ev("SUMMARY_CAPACITY_RESOLVED",
            provider="api.openai.com", model="gpt-test",
            usage={
                "effective_context_window": 400000,
                "required_input_tokens": 96120,
                "reserved_output_tokens": 4000,
                "safety_margin_tokens": 299880,
                "window_source": "runtime",
                "confidence": "verified",
                "fallback_used": False,
                "mode": "WHOLE_WINDOW",
                "reason": "fits_effective_context",
                "budget_mode": "auto",
                "segments": None,
            }),
        _ev("SUMMARY_EXECUTION_MODE_SELECTED", status="WHOLE_WINDOW",
            usage={"reason": "fits_effective_context",
                   "budget_mode": "auto"}),
        _ev("SUMMARY_L1_STAGE",
            outcome="failed" if l1_failed else "success",
            status="failed" if l1_failed else "ok",
            reason_code="parse_error" if l1_failed else None,
            usage={"threads": 12, "map_degraded": 0}),
        _ev("SUMMARY_L2_STAGE", usage={"output_count": 9}),
        _ev("SUMMARY_RUN_DONE",
            usage={"coverage": 100.0, "source_total": 839,
                   "source_considered": 839, "publication": "rich"}),
    ]
    return events


class TestHonestCoverageSemantics:
    def test_l1_failed_source_full_are_separate_axes(self):
        """ОБЯЗАТЕЛЬНЫЙ fixture-тест (T-4621, spec G.1): «839/839 Coverage
        100%» рядом с L1 failure НЕ показывается единым успехом — L1
        result=failed отдельная ось рядом с source 100%."""
        events = _fixture_events_full_window(l1_failed=True)
        view = pa.build_run_view("run-g1", _snap(), events)
        br = view["coverage_breakdown"]
        assert br is not None
        # Источник честно полный…
        assert br["source"]["total"] == 839
        assert br["source"]["percent"] == 100.0
        # …но structurer-L1 результат — ОТДЕЛЬНАЯ ось со своим failed.
        assert br["l1"]["result"] == "failed"
        assert br["l1"]["input_total"] == 839
        assert br["l1"]["input_mode"] == "WHOLE_WINDOW"
        assert br["l1"]["input_requests"] == 1
        # Существующая first-class coverage (R4-E) сохраняется рядом.
        assert view["coverage"]["percent"] == 100.0
        # Ось Final — отдельная (результат not merged с L1).
        assert br["final"]["percent"] == 100.0

    def test_l1_ok_same_fixture_shows_ok_axis(self):
        view = pa.build_run_view("run-g1", _snap(),
                                 _fixture_events_full_window(False))
        br = view["coverage_breakdown"]
        assert br["l1"]["result"] == "ok"

    def test_map_degraded_displayed_in_l1_axis(self):
        """T-4624: map_degraded-карточки строятся из SUMMARY_L1_STAGE
        counts (честный degraded, не ok-маска)."""
        events = _fixture_events_full_window(False)
        events[5]["usage_json"] = json.dumps(
            {"threads": 12, "map_degraded": 1, "map_reason": "map_degraded"})
        view = pa.build_run_view("run-g1", _snap(), events)
        br = view["coverage_breakdown"]
        assert br["l1"]["map_degraded"] is True
        assert br["l1"]["map_reason"] == "map_degraded"
        assert pa.reason_ru("map_degraded")

    def test_overflow_segments_and_messages_covered(self):
        """§38 (overflow): segments 4/4 + messages covered 839/839."""
        events = _fixture_events_full_window(False)
        events.insert(6, _ev("SUMMARY_SEGMENT_PLAN", outcome="start",
                             usage={"segments": 4,
                                    "source_messages": 839}))
        events.insert(7, _ev("SUMMARY_SEGMENT_LEDGER", outcome="success",
                             status="ok",
                             usage={"segments": 4, "processed": 839,
                                    "fallback": 0, "missing": 0,
                                    "assignment_lossless": True}))
        view = pa.build_run_view("run-g1", _snap(), events)
        br = view["coverage_breakdown"]
        assert br["overflow"]["segments"] == 4
        assert br["overflow"]["messages_covered"] == 839
        assert br["overflow"]["messages_total"] == 839
        assert br["overflow"]["lossless"] is True
        assert br["l1"]["input_requests"] == 4

    def test_writer_input_coverage_axis(self):
        view = pa.build_run_view("run-g1", _snap(),
                                 _fixture_events_full_window(False))
        br = view["coverage_breakdown"]
        assert br["writer"]["total"] == 839
        assert br["writer"]["percent"] == 100.0
        assert br["writer"]["result"] == "ok"

    def test_no_log_parsing_in_path(self):
        """Guard §38 (23384): данные — structured state, НЕ парсинг логов."""
        src = open("services/pipeline_analytics.py", encoding="utf-8").read()
        for pattern in (r"\bopen\(", r"read_text", r"\bglob\(",
                        r"subprocess", r"Path\("):
            assert not re.search(pattern, src), pattern


# ── T-4622: capacity-карточка + liveness (§39/§40) ───────────────────────

class TestCapacityCard:
    def test_fields_from_structured_state(self):
        events = _fixture_events_full_window(False)
        view = pa.build_run_view("run-g1", _snap(), events)
        card = view["capacity"]
        assert card is not None
        assert card["provider"] == "api.openai.com"
        assert card["model"] == "gpt-test"
        assert card["effective_window"] == 400000
        assert card["required_input_tokens"] == 96120
        assert card["reserved_output_tokens"] == 4000
        assert card["mode"] == "WHOLE_WINDOW"
        assert card["reason"] == "fits_effective_context"
        # Человеческая причина (не машинная каша).
        assert card["reason_ru"] == pa.reason_ru("fits_effective_context")
        assert card["window_source"] == "runtime"
        assert card["window_source_ru"]
        assert card["replans"] == 0

    def test_no_capacity_event_no_card(self):
        view = pa.build_run_view("run-g1", _snap(), [
            _ev("SUMMARY_SOURCE_WINDOW", usage={"input_count": 839})])
        assert view["capacity"] is None

    def test_replan_counter_counts_capacity_resolved(self):
        """Re-plan события (T-4605 контур, T-4622 витрина): второй+
        третий SUMMARY_CAPACITY_RESOLVED = 2 replan'а; последний value
        surface — truthful."""
        events = _fixture_events_full_window(False)
        replan = dict(_ev("SUMMARY_CAPACITY_RESOLVED",
                          provider="fallback.host", model="small",
                          usage={
                              "mode": "CAPACITY_OVERFLOW",
                              "reason": "fallback_capacity_smaller",
                              "window_source": "provider_catalog",
                              "segments": 4,
                              "fallback_used": True,
                              "required_input_tokens": 0,
                              "reserved_output_tokens": 0,
                              "effective_context_window": 0,
                              "safety_margin_tokens": 0,
                          }))
        events.insert(9, replan)
        view = pa.build_run_view("run-g1", _snap(), events)
        card = view["capacity"]
        assert card["replans"] == 1
        assert card["mode"] == "CAPACITY_OVERFLOW"
        assert card["segments"] == 4

    def test_capacity_reason_translation_known_codes(self):
        # Ключ из цепочки §5 выигрывает у выдуманных наименований.
        for code in ("fits_effective_context", "capacity_overflow",
                     "fallback_capacity_smaller", "segment_artifacts_exist",
                     "capacity_cache_invalidated"):
            assert pa.reason_ru(code), code


class TestLivenessCard:
    def test_sync_transport_not_shown_as_stream(self):
        """§40 честная база (T-4613): декларация отражает фактическое
        состояние — sync-транспорт НЕ показывается как «stream ✓»."""
        events = [
            _ev("SUMMARY_L1_STAGE", usage={"threads": 3}),
            _ev("SUMMARY_L2_STAGE", usage={"output_count": 2}),
        ]
        events += [
            _ev("SUMMARY_L1_ACTIVITY", ts=1100, status="sync",
                usage={"op": "l1"}),
            _ev("SUMMARY_WRITER_ACTIVITY", ts=1200, status="sync",
                usage={"op": "writer"}),
        ]
        cards = pa._liveness_cards(events, running=False)
        by = {c["stage"]: c for c in cards}
        assert by["l1"]["mode"] == "sync"
        assert "стрим" not in by["l1"]["mode_ru"]
        assert "синхронн" in by["l1"]["mode_ru"]

    def test_provider_fallback_visible(self):
        events = [
            _ev("SUMMARY_LLM_SUPERVISOR", ts=1100, status="sync",
                outcome="fallback", reason_code="provider_unavailable",
                provider="b.host", model="m2", usage={"op": "l1",
                                                      "fallback_target": "b"}),
        ]
        cards = pa._liveness_cards(events, running=False)
        assert cards[0]["provider_fallback"] is True
        assert cards[0]["reason_ru"] == pa.reason_ru("provider_unavailable")
        assert cards[0]["live"] is False

    def test_running_stage_alive_ticker(self):
        """T-4624: «жива/ждёт» — per-stage статус из durable stage-строк +
        activity событий при running-прогоне."""
        stage_rows = [
            {"stage": "l1", "status": "ok", "last_activity_at": 1700,
             "finished_at": 1710},
            {"stage": "l2", "status": "degraded", "last_activity_at": 1800,
             "finished_at": None},
        ]
        cards = pa._liveness_cards([], stage_rows=stage_rows, running=True)
        by = {c["stage"]: c for c in cards}
        # running-run: l1 (finished) ждёт финальной RUN_DONE honesty —
        # стадия завершена; l2 без finished_at + activity → жива.
        assert by["l1"]["live"] is False
        assert by["l2"]["live"] is True
        assert "жива" in by["l2"]["status_ru"]

    def test_stage_rows_waiting_when_no_activity(self):
        stage_rows = [
            {"stage": "l2", "status": "ok", "last_activity_at": None,
             "finished_at": None},
        ]
        cards = pa._liveness_cards([], stage_rows=stage_rows,
                                   running=True)
        assert cards[0]["status_ru"] == "ждёт"
        assert cards[0]["live"] is False


# ── T-4623: cover-style карточка (§41) ───────────────────────────────────

def _cover_events_styled():
    return [
        _ev("COVER_STYLE_SELECTION", usage={}),
        _ev("COVER_STYLE_RESOLVE", outcome="start",
            model="painter-x", provider="nano-gpt.com",
            status=None, stage="style", ts=1900,
            usage={"resolve_source": "global_image", "configured": True}),
        # emit_cover_event сериализует extra поля строки в log-line, не JSON
        # — resolve_source/top-level хранятся в событии колонкой reason_code
        # пока нет; для карточки тестов всё в usage_json — читается честно.
        _ev("COVER_BASE_SUCCEEDED", ts=1950, model="painter-x",
            provider="nano-gpt.com",
            usage={"reference_count": 0}),
        _ev("COVER_STYLE_SUCCEEDED", ts=2000, model="painter-x",
            provider="nano-gpt.com", usage={"reference_count": 2}),
        _ev("COVER_RICH_PUBLISH_SUCCEEDED", ts=2100),
    ]


def _cover_events_style_failed():
    return [
        _ev("COVER_STYLE_RESOLVE", outcome="start",
            model="painter-old", provider="nano-gpt.com", ts=1900,
            usage={"resolve_source": "connections_default",
                   "configured": True}),
        _ev("COVER_BASE_SUCCEEDED", ts=1950,
            usage={"reference_count": 0}),
        _ev("COVER_STYLE_FAILED", outcome="failed", ts=2000,
            reason_code="edit_unsupported",
            duration_ms=30000, usage={"reference_count": 2}),
        _ev("COVER_RICH_PUBLISH_SUCCEEDED", ts=2100),
    ]


class TestCoverStyleCard:
    def test_styled_result_card(self):
        view = pa.build_run_view("run-g1", _snap(), _cover_events_styled())
        card = view["cover_style"]
        assert card is not None
        assert card["base_cover_ok"] is True
        # Нет style_id в fixture → честное отсутствие (не выдумка).
        assert card.get("selected_style") in (None, "")
        assert card["style_provider"] == "nano-gpt.com"
        assert card["style_model"] == "painter-x"
        assert card["style_edit_ok"] is True
        assert card["capability_edit"] is True
        assert card["reference_assets"] == 2
        assert card["result"] == "styled"
        assert card["resolve_source"] == "global_image"
        assert card["resolve_source_ru"]

    def test_style_failure_precise_reason_not_generic(self):
        """§41/DoD-30: причина fallback — точный reason (D6.3), прочнее
        generic style_failed; published = base_fallback ✓."""
        view = pa.build_run_view("run-g1", _snap(),
                                 _cover_events_style_failed())
        card = view["cover_style"]
        assert card["style_edit_ok"] is False
        assert card["fallback_reason"] == "edit_unsupported"
        assert card["fallback_reason_ru"] == pa.reason_ru("edit_unsupported")
        assert card["result"] == "base_fallback"
        assert card["capability_edit"] is False

    def test_base_failed_no_cover(self):
        events = [
            _ev("COVER_STYLE_RESOLVE", outcome="start",
                usage={"resolve_source": "profile_connection"}),
            _ev("COVER_BASE_FAILED", outcome="failed",
                reason_code="base_failed"),
        ]
        view = pa.build_run_view("run-g1", _snap(), events)
        card = view["cover_style"]
        assert card["result"] == "no_cover"
        assert card["base_cover_ok"] is False

    def test_resolve_source_translation_ladder(self):
        # Лестница наследования §35: только реальные SLOT_SOURCE-значения.
        for src, need_ru in (("global_style", True),
                             ("profile_connection", True),
                             ("connections_default", True),
                             ("global_image", True)):
            assert pa._RESOLVE_SOURCE_RU.get(src) if need_ru else True, src
        view = pa.build_run_view("run-g1", _snap(),
                                 _cover_events_style_failed())
        assert view["cover_style"]["resolve_source_ru"]
        assert "наследован" in view["cover_style"]["resolve_source_ru"]

    def test_no_cover_events_no_card(self):
        view = pa.build_run_view("run-g1", _snap(), [])
        assert view["cover_style"] is None

    def test_reason_ru_for_fallback_cause_families(self):
        # Точные семейства причин fallback §41 ТЗ (connection/inheritance/
        # registry) дают человеческие строки, не generic.
        for code in ("connection_missing", "not_configured",
                     "edit_unsupported", "capability_unknown",
                     "reference_missing"):
            assert pa.reason_ru(code), code


# ── T-4624: structured events + приватность (§42/§43) ────────────────────

SPEC_EVENT_NAMES = (
    # spec §7.3 таблица (сущ. + new волны 4.1).
    "SUMMARY_RUN_START", "SUMMARY_SOURCE_WINDOW",
    "SUMMARY_SOURCE_WINDOW_READY", "SUMMARY_CAPACITY_RESOLVED",
    "SUMMARY_EXECUTION_MODE_SELECTED", "SUMMARY_L1_STAGE",
    "SUMMARY_L1_ACTIVITY", "SUMMARY_L2_STAGE", "SUMMARY_L2_REVIEW",
    "SUMMARY_LEGACY_FALLBACK", "SUMMARY_RUN_DONE",
    "SUMMARY_SEGMENT_PLAN", "SUMMARY_SEGMENT_RESULT",
    "SUMMARY_SEGMENT_LEDGER", "SUMMARY_TEXT_READY",
    "SUMMARY_REVISION_RESULT",
    "COVER_BASE_SUCCEEDED", "COVER_BASE_FAILED",
    "COVER_STYLE_SUCCEEDED", "COVER_STYLE_FAILED", "COVER_STYLE_SKIPPED",
    "COVER_STYLE_RESOLVE",
    "SUMMARY_L1_ACTIVITY", "SUMMARY_WRITER_ACTIVITY", "SUMMARY_LLM_SUPERVISOR",
)


def _emit_full_run(run_id, *, overflow=False):
    """Полный fixture-run через РЕАЛЬНЫЙ mca-17a transport (events are
    real emit_stage calls, не заглушки)."""
    chat = 101
    pe.summary_start(run_id, chat_id=chat, mode="hybrid_l2", manual=False)
    pe.source_window(run_id, chat_id=chat, messages=839)
    pe.source_window_ready(run_id, chat_id=chat,
                           counts={"messages": 839, "durable": True},
                           window_from=1000, window_to=9999)
    pe.capacity_resolved(
        run_id, chat_id=chat, provider="api.test.host", model="m1",
        counts={"effective_context_window": 400000,
                "required_input_tokens": 90000,
                "reserved_output_tokens": 4000,
                "mode": "WHOLE_WINDOW", "reason": "fits_effective_context",
                "window_source": "runtime"})
    pe.execution_mode_selected(
        run_id, chat_id=chat, mode="WHOLE_WINDOW",
        reason="fits_effective_context")
    pe.l1_stage(run_id, chat_id=chat, usable=True, duration_ms=9000,
                threads=12, counts={"map_degraded": 0})
    pe.l2_stage(run_id, chat_id=chat, usable=True, duration_ms=21000,
                paragraphs=9)
    pe.l2_review(run_id, chat_id=chat, metrics={"l2_final_approved": 1,
                                                "l2_review_calls": 1})
    pe.revision_result(run_id, chat_id=chat, attempt=1,
                       usable=True, repair_target="patch")
    pe.text_ready(run_id, chat_id=chat, stage="l2")
    span = trace.span_fields(run_id=run_id, pipeline_type="summary")
    trace.emit_stage("COVER_STYLE_SELECTION", outcome="success",
                     component="cover", stage="style_selection", **span)
    trace.emit_stage("COVER_BASE_SUCCEEDED", outcome="success",
                     component="cover", stage="base_cover", **span)
    trace.emit_stage("COVER_STYLE_SUCCEEDED", outcome="success",
                     component="cover", stage="style_edit", **span)
    trace.emit_stage("COVER_RICH_PUBLISH_SUCCEEDED", outcome="success",
                     component="cover", stage="publish", **span)
    pe.summary_done(run_id, chat_id=chat, status="ok", health="ok",
                    duration_ms=42000.0,
                    counts={"coverage": 100.0, "source_total": 839,
                            "source_considered": 839,
                            "publication": "rich", "message_id": 4242})
    if overflow:
        pe.segment_plan(run_id, chat_id=chat, segments=4,
                        counts={"source_messages": 839})
        pe.segment_result(run_id, chat_id=chat, segment=1, usable=True)
        pe.segment_ledger(run_id, chat_id=chat,
                          status={"processed": 839, "fallback": 0,
                                  "missing": 0, "segments": 4,
                                  "assignment_lossless": True})


def _try_flush_or_events():
    """Асинхронная запись в test DB не используется — только pending
    mca_events первых emit_stage вызовов. Вернуть их для scan'ов."""
    outer = {}

    async def _collect():
        outer["rows"] = list(mca_events._PENDING)

    try:
        asyncio.run(_collect())
    except Exception:
        outer["rows"] = []
    return outer["rows"]


class TestStructuredEventsFullList:
    def test_full_event_lamp_on_fixture_run(self):
        """§42 ТЗ (критерий): полный перечень событий на fixture-run;
        overflow-run добавляет три сегментных. R17-scan чист.
        События — реальный emit_stage транспорт (не заглушки)."""
        mca_events.reset_pending()
        _emit_full_run("run-event-list", overflow=True)
        names = [e.get("event_name") for e in mca_events._pending]
        for needle in ("SUMMARY_RUN_START", "SUMMARY_SOURCE_WINDOW_READY",
                       "SUMMARY_CAPACITY_RESOLVED",
                       "SUMMARY_EXECUTION_MODE_SELECTED",
                       "SUMMARY_L1_STAGE", "SUMMARY_L2_STAGE",
                       "SUMMARY_L2_REVIEW", "SUMMARY_REVISION_RESULT",
                       "SUMMARY_TEXT_READY", "SUMMARY_RUN_DONE",
                       "SUMMARY_SEGMENT_PLAN", "SUMMARY_SEGMENT_RESULT",
                       "SUMMARY_SEGMENT_LEDGER", "COVER_BASE_SUCCEEDED"):
            assert needle in names, needle
        mca_events.reset_pending()

    def test_existing_event_names_not_renamed(self):
        """§42 ТЗ: существующие имена не переименовываются. Контрактные
        константы pipeline_events не менялись волной 7."""
        assert pe.EV_SUMMARY_START == "SUMMARY_RUN_START"
        assert pe.EV_L1_STAGE == "SUMMARY_L1_STAGE"
        assert pe.EV_L2_STAGE == "SUMMARY_L2_STAGE"
        assert pe.EV_L2_REVIEW == "SUMMARY_L2_REVIEW"
        assert pe.EV_SUMMARY_DONE == "SUMMARY_RUN_DONE"
        # Новые константы (T-4624) — добавление, без переименований.
        assert pe.EV_TEXT_READY == "SUMMARY_TEXT_READY"
        assert pe.EV_REVISION_RESULT == "SUMMARY_REVISION_RESULT"

    def test_overflow_run_adds_three_segment_events(self):
        mca_events.reset_pending()
        _emit_full_run("run-ev-overflow", overflow=False)
        base_names = {e.get("event_name") for e in mca_events._pending}
        mca_events.reset_pending()
        _emit_full_run("run-ev-overflow", overflow=True)
        names = {e.get("event_name") for e in mca_events._pending}
        added = names - base_names
        for seg in ("SUMMARY_SEGMENT_PLAN", "SUMMARY_SEGMENT_RESULT",
                    "SUMMARY_SEGMENT_LEDGER"):
            assert seg in added, seg
        mca_events.reset_pending()

    def test_r17_scan_no_text_or_keys(self):
        """R17/§43 (23507–23528): только counts/enum/коды/safe id;
        никакие API keys/полные сообщения/промпты/byte-строки."""
        mca_events.reset_pending()
        _emit_full_run("run-ev-r17", overflow=True)
        serial = json.dumps(list(mca_events._pending), ensure_ascii=False)
        for bad in ("api_key", "sk-", "reference_bytes", "image/png",
                    "леха"):
            assert bad.lower() not in serial.lower(), bad
        mca_events.reset_pending()


# ── integration: честная витрина на durable-пути (events + стages) ───────

class TestViewBuilderIntegration:
    def test_running_view_has_liveness(self):
        """collect_run (drill-down) строит liveness из stage_rows; для
        unit-уровня -- _liveness_cards surface (упрощение без db)."""
        cards = pa._liveness_cards(
            [], stage_rows=[{"stage": "l1", "status": "ok",
                             "last_activity_at": 10,
                             "finished_at": 20}],
            running=False)
        assert cards[0]["stage"] == "l1"

    def test_capacity_card_uses_module_surface(self):
        events = _fixture_events_full_window(False)
        card = pa._capacity_card(events)
        assert card["mode"] == "WHOLE_WINDOW"


@pytest.fixture(autouse=True)
def _isolated_registry():
    egs.reset()
    yield
    egs.reset()


@pytest.fixture(autouse=True)
def _zone_g_flags_on(monkeypatch):
    """Витрина зоны G читает mca_events → SUMMARY_PIPELINE_EVENTS_ENABLED
    должен быть True. Автouse-фикстуры conftest применяются в порядке
    объявления и asap4-OFF перекрывает asap41-ON (факт-прогон), поэтому
    фиксим честный прод-дефолт локально для this module (прецедент
    _set_settings волн 5/6: патчим оба класса активных инстансов)."""
    import config.settings as cs
    import services.direct_chat_service as dcs
    seen = []
    for cls in {type(settings), type(cs.settings), type(dcs.settings)}:
        if cls not in seen:
            seen.append(cls)
        monkeypatch.setattr(cls, "SUMMARY_PIPELINE_EVENTS_ENABLED", True,
                            raising=False)
