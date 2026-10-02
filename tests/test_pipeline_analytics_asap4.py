"""ASAP-4 волна E (T-4440–T-4445, spec §5 E.1/E.2, ADR-1028-7 D8) — тесты
Pipeline Analytics / Run Inspector.

Покрытие:
  * §61.11/§60 — нормализованная модель стадий из structured events
    (mca_events + in-memory снапшот); узлы текстовой ветки и ветки ОБЛОЖКИ
    раздельны (§61.8);
  * §61.2/§61.7 — статусы ✓/⚠/✕/○/… и РАЗДЕЛЬНЫЕ repair/fallback/failure;
  * §61.3 — human-переводы причин (too_many_facts/quote_speaker_mismatch/
    rate_limit/reference_missing + коды волн A–D);
  * §61.6 — coverage first-class: «опубликован + 44.6% = degraded» (сценарий
    D §61.16 не healthy); health — только текстовые бейджи (§61.13);
  * §61.4/§61.5 — агрегаты per-stage (success/repaired/fallback/failure %,
    median/p95, top-3 причины) + итоги runs из ТЕХ ЖЕ событий;
  * §61.10 — список runs с бейджами/путём;
  * §61.15 — running-run: хвостовая топология ○ «ожидает»;
  * эмиссия стадийных событий (kill-switch ON/OFF) + reason-коды в едином
    словаре `mca_events.REASON_CODES`;
  * T-4445 guard §61.12 — путь данных виджета НЕ читает human-логи
    (source-scan: без open/read/glob; данные — FROM mca_events);
  * R17 — снапшот-проекция stage events bounded + только safe-ключи.
"""
import asyncio
import json

import pytest

from config.settings import settings
from services import execution_graph_source as egs
from services import mca_events
from services import mca_trace as trace
from services import pipeline_analytics as pa
from services import pipeline_events as pe


pytestmark = pytest.mark.asap4


def _ev(name, *, outcome="success", status=None, reason_code=None,
        duration_ms=None, attempt=None, model=None, provider=None,
        usage=None, ts=1000, chat_id=100):
    row = {
        "event_name": name, "outcome": outcome, "status": status,
        "reason_code": reason_code, "duration_ms": duration_ms,
        "attempt": attempt, "model": model, "provider": provider,
        "ts": ts, "chat_id": chat_id,
        "pipeline_run_id": "run-1", "trace_id": "run-1",
        "usage_json": json.dumps(usage) if usage else None,
    }
    return {k: v for k, v in row.items() if v is not None}


def _snap(**fields):
    base = {
        "run_id": "run-1", "chat_id": 100, "mode": "hybrid_l2",
        "source_count": 688, "status": "ok", "duration_ms": 42000.0,
        "publish_channel": "rich", "publish_status": "ok",
        "publish_message_id": 4242, "cover_status": "ok",
        "source_total": 688, "source_considered": 688,
        "source_coverage": 100.0, "pipeline_health": "ok",
    }
    base.update(fields)
    return base


# ── §61.3: human-переводы причин ────────────────────────────────────────────

class TestReasonTranslations:
    @pytest.mark.parametrize("code", [
        "too_many_facts", "quote_speaker_mismatch", "rate_limit",
        "reference_missing",
    ])
    def test_mandatory_owner_codes_translated(self, code):
        assert pa.reason_ru(code), "обязательный код §61.3 без перевода"

    @pytest.mark.parametrize("code", [
        # волна C
        "quote_text_not_found", "quote_attribution_repaired",
        "legacy_coverage_degraded", "legacy_full_window",
        # волна D
        "l2_review_rejected", "l2_review_unusable", "review_degraded",
        # волна B
        "no_style", "not_configured", "style_failed", "edit_unsupported",
        # волна A
        "paused_rate_limit", "auth_failed", "validation_failed",
    ])
    def test_wave_codes_translated(self, code):
        assert pa.reason_ru(code), "код волны без человеческого перевода"

    def test_unknown_code_is_safe(self):
        assert pa.reason_ru("") == ""
        assert pa.reason_ru("totally_unknown") == ""

    def test_new_codes_in_single_dictionary(self):
        # Единый словарь REASON_CODES (spec E.1: новых словарей нет).
        for code in ("too_many_facts", "too_many_threads",
                     "too_many_facts_total", "rate_limit", "timeout"):
            assert code in mca_events.REASON_CODES
        ev = mca_events.build_event("SUMMARY_L1_STAGE", outcome="failed",
                                    reason_code="too_many_facts")
        assert ev["reason_code"] == "too_many_facts"

    def test_map_reason_llm_classes(self):
        assert pe.map_reason("LLMRateLimitError") == "rate_limit"
        assert pe.map_reason("LLMTimeoutError") == "timeout"
        assert pe.map_reason("too_many_facts") == "too_many_facts"
        assert pe.map_reason("совершенно неизвестная причина") is None


# ── §61.1/§61.8/§61.16: карта запуска ───────────────────────────────────────

def _events_healthy():
    return [
        _ev("SUMMARY_RUN_START", outcome="start", usage={"mode": "hybrid_l2"}),
        _ev("SUMMARY_SOURCE_WINDOW", usage={"input_count": 688}),
        _ev("SUMMARY_L1_STAGE", duration_ms=9000,
            usage={"threads": 12}),
        _ev("SUMMARY_L2_STAGE", duration_ms=21000, model="deepseek",
            usage={"output_count": 9}),
        _ev("SUMMARY_L2_REVIEW", status="ok", attempt=0,
            usage={"first_pass_approved": 1, "review_calls": 1}),
        _ev("COVER_STYLE_SELECTION", usage={},
            ),
        _ev("COVER_BASE_SUCCEEDED", duration_ms=8000),
        _ev("COVER_STYLE_SUCCEEDED", duration_ms=11000, attempt=1),
        _ev("COVER_RICH_PUBLISH_SUCCEEDED", duration_ms=1500),
        _ev("SUMMARY_RUN_DONE", usage={"coverage": 100.0,
                                       "publication": "rich"}),
    ]


class TestRunViewScenarios:
    """§61.16: acceptance-сценарии A–D на уровне модели."""

    def test_a_fully_healthy(self):
        view = pa.build_run_view("run-1", _snap(), _events_healthy())
        assert view["health"] == pa.HEALTH_HEALTHY
        by_key = {n["key"]: n for n in view["nodes"]}
        assert by_key["l1"]["icon"] == "✓"
        assert by_key["l2"]["icon"] == "✓"
        assert by_key["base_cover"]["icon"] == "✓"
        assert by_key["style_edit"]["icon"] == "✓"
        assert by_key["publish"]["icon"] == "✓"

    def test_branches_are_separate(self):
        view = pa.build_run_view("run-1", _snap(), _events_healthy())
        text = [n["key"] for n in view["nodes"] if n["branch"] == "text"]
        cover = [n["key"] for n in view["nodes"] if n["branch"] == "cover"]
        assert "l1" in text and "l2" in text
        assert "base_cover" in cover and "style_edit" in cover
        assert not (set(text) & set(cover))

    def test_b_l2_to_legacy_is_degraded_not_healthy(self):
        events = [
            _ev("SUMMARY_SOURCE_WINDOW", usage={"input_count": 688}),
            _ev("SUMMARY_L1_STAGE", duration_ms=9000),
            _ev("SUMMARY_L2_STAGE", outcome="failed", status="failed",
                reason_code="l2_review_rejected"),
            _ev("SUMMARY_L2_REVIEW", status="failed", attempt=2,
                reason_code="l2_review_rejected"),
            _ev("SUMMARY_LEGACY_FALLBACK", status="fallback",
                reason_code="fallback_engaged",
                usage={"fallback_from": "l2", "trigger": "l2_unusable"}),
            _ev("COVER_BASE_SUCCEEDED"),
            _ev("COVER_RICH_PUBLISH_SUCCEEDED"),
            _ev("SUMMARY_RUN_DONE", usage={"coverage": 100.0,
                                           "publication": "rich",
                                           "fallback": "legacy"}),
        ]
        snapshot = _snap(pipeline_health="degraded", fallback="legacy")
        view = pa.build_run_view("run-1", snapshot, events)
        assert view["health"] == pa.HEALTH_DEGRADED
        by_key = {n["key"]: n for n in view["nodes"]}
        assert by_key["l2"]["icon"] == "✕"
        assert by_key["legacy"]["state"] == pa.STATE_FALLBACK
        assert by_key["legacy"]["icon"] == "⚠"

    def test_c_style_failure_text_ok(self):
        events = [
            _ev("SUMMARY_SOURCE_WINDOW", usage={"input_count": 512}),
            _ev("SUMMARY_L1_STAGE"), _ev("SUMMARY_L2_STAGE",
                                         duration_ms=18000),
            _ev("COVER_BASE_SUCCEEDED", duration_ms=7000),
            _ev("COVER_STYLE_FAILED", reason_code="style_failed",
                duration_ms=30000),
            _ev("COVER_RICH_PUBLISH_SUCCEEDED"),
            _ev("SUMMARY_RUN_DONE", usage={"coverage": 100.0,
                                           "publication": "rich"}),
        ]
        view = pa.build_run_view("run-1", _snap(), events)
        by_key = {n["key"]: n for n in view["nodes"]}
        assert by_key["l2"]["icon"] == "✓"
        assert by_key["base_cover"]["icon"] == "✓"
        assert by_key["style_edit"]["state"] == pa.STATE_FALLBACK
        assert by_key["style_edit"]["reason_ru"] == pa.reason_ru(
            "style_failed")
        assert view["health"] == pa.HEALTH_HEALTHY

    def test_d_coverage_fixture_is_not_healthy(self):
        # §61.6/§61.16-D: «RichMessage опубликован + Coverage 44.6% =
        # degraded» — run НЕ имеет права быть healthy.
        snapshot = _snap(source_total=688, source_considered=307,
                         source_coverage=44.6, pipeline_health="ok")
        view = pa.build_run_view("run-1", snapshot, [])
        assert view["health"] == pa.HEALTH_DEGRADED
        assert view["coverage"]["full"] is False
        assert view["coverage"]["percent"] == 44.6

    def test_publication_failed_is_not_published(self):
        snapshot = _snap(publish_status="failed", publish_channel=None,
                         status="failed")
        code, label = pa.health_of(snapshot, {})
        assert code == pa.HEALTH_FAILED
        assert label == "Не издано"

    def test_no_publication_is_incomplete(self):
        snapshot = _snap(publish_status=None, publish_channel=None,
                         status="empty")
        code, label = pa.health_of(snapshot, {})
        assert code == pa.HEALTH_INCOMPLETE
        assert label == "Не завершён"

    def test_health_labels_text_only_no_score(self):
        # §61.13: только текстовые бейджи, без opaque score.
        for label in pa.HEALTH_LABELS_RU.values():
            assert label
            assert not any(ch.isdigit() for ch in label)


# ── M-ASAP4-E1: health после рестарта — из durable-событий ──────────────────

async def _inspector_db(tmp_path, name="asap4e.db"):
    """Чистый SQLite-store (реальная схема v23) для durable-событий."""
    from services.database import DatabaseService
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


class TestRestartHealthDurable:
    """Рестарт-сценарий (review.md M-ASAP4-E1): события пишутся в БД,
    in-memory снапшот пуст (новый процесс/сброшенный кэш) → финальный
    health строится ИЗ durable-событий (§61.6: health = publication ×
    coverage; §61.13: «Не завершён» — только для реально незавершённых
    прогонов). Никакой опоры на in-memory кэш."""

    @staticmethod
    def _emit_published_run(run_id, *, coverage, considered, status,
                            health, pipeline_health="ok"):
        """Полный published-run через РЕАЛЬНЫЙ транспорт mca-17a:
        pipeline_events (SUMMARY_*) + COVER_* → буфер mca_events.
        (reset_pending вызывающий — до первой эмиссии сценария.)"""
        pe.summary_start(run_id, chat_id=100, mode="hybrid_l2", manual=False)
        pe.source_window(run_id, chat_id=100, messages=688)
        pe.l1_stage(run_id, chat_id=100, usable=True, duration_ms=9000,
                    threads=12)
        pe.l2_stage(run_id, chat_id=100, usable=True, duration_ms=21000,
                    paragraphs=9)
        span = trace.span_fields(run_id=run_id, pipeline_type="summary")
        trace.emit_stage("COVER_STYLE_SELECTION", outcome="success",
                         component="cover", stage="style_selection", **span)
        trace.emit_stage("COVER_BASE_SUCCEEDED", outcome="success",
                         component="cover", stage="base_cover", **span)
        trace.emit_stage("COVER_STYLE_SUCCEEDED", outcome="success",
                         component="cover", stage="style_edit", **span)
        trace.emit_stage("COVER_RICH_PUBLISH_SUCCEEDED", outcome="success",
                         component="cover", stage="publish", **span)
        pe.summary_done(
            run_id, chat_id=100, status=status, health=health,
            duration_ms=42000.0,
            counts={"coverage": coverage, "source_total": 688,
                    "source_considered": considered, "publication": "rich",
                    "message_id": 4242, "fallback": "none",
                    "pipeline_health": pipeline_health})

    def test_restart_published_low_coverage_is_degraded_full_is_healthy(
            self, tmp_path):
        """ОБЯЗАТЕЛЬНЫЙ негативный тест (re-gate рецепт): collect_run по
        durable-событиям БЕЗ снапшота → published+coverage 44.6% =
        «С деградацией»; published+100% = «Здоров»."""

        async def scenario():
            d = await _inspector_db(tmp_path)
            try:
                mca_events.reset_pending()
                self._emit_published_run("run-e1-low", coverage=44.6,
                                         considered=307, status="degraded",
                                         health="ok")
                self._emit_published_run("run-e1-full", coverage=100.0,
                                         considered=688, status="ok",
                                         health="ok")
                written = await mca_events.flush_events(d)
                assert written >= 16      # 8 событий × 2 run — без потерь
                egs.reset()               # рестарт: реестр снапшотов пуст
                low = await pa.collect_run(d, "run-e1-low")
                full = await pa.collect_run(d, "run-e1-full")
                return low, full
            finally:
                await d.close()

        low, full = asyncio.run(scenario())
        # published + coverage 44.6% → «С деградацией» (§61.6), не «Не
        # завершён» — и это НЕ fallback-исход: единственный сигнал деградации
        # здесь coverage (pipeline_health=ok, fallback=none).
        assert low["running"] is False
        assert low["publication"]["status"] == "rich"
        assert low["coverage"]["percent"] == 44.6
        assert low["coverage"]["full"] is False
        assert low["health"] == pa.HEALTH_DEGRADED
        assert low["health_label"] == "С деградацией"
        by_key = {n["key"]: n for n in low["nodes"]}
        assert by_key["publish"]["state"] == pa.STATE_SUCCESS
        assert by_key["l1"]["icon"] == "✓"
        # published + coverage 100% → «Здоров».
        assert full["running"] is False
        assert full["publication"]["status"] == "rich"
        assert full["coverage"]["percent"] == 100.0
        assert full["health"] == pa.HEALTH_HEALTHY
        assert full["health_label"] == "Здоров"

    def test_latest_card_after_restart_uses_durable_done(self, tmp_path):
        """«Последний запуск» (§61.4) после рестарта: latest-карточка из
        durable DONE — degraded, а не «Не завершён»."""

        async def scenario():
            d = await _inspector_db(tmp_path, name="asap4e_latest.db")
            try:
                mca_events.reset_pending()
                self._emit_published_run("run-e1-latest", coverage=44.6,
                                         considered=307, status="degraded",
                                         health="ok")
                await mca_events.flush_events(d)
                egs.reset()
                return await pa.collect_latest(d)
            finally:
                await d.close()

        view = asyncio.run(scenario())
        assert view is not None
        assert view["run_id"] == "run-e1-latest"
        assert view["health"] == pa.HEALTH_DEGRADED
        assert view["health_label"] == "С деградацией"

    def test_finalized_failed_run_after_restart_is_not_published(
            self, tmp_path):
        """Финализированный провал без публикации после рестарта →
        «Не издано» (fallback run_status из DONE status/outcome), не
        «Не завершён» (§61.13)."""

        async def scenario():
            d = await _inspector_db(tmp_path, name="asap4e_failed.db")
            try:
                mca_events.reset_pending()
                pe.summary_start("run-e1-fail", chat_id=100,
                                 mode="hybrid_l2", manual=False)
                pe.summary_done("run-e1-fail", chat_id=100, status="failed",
                                health="failed", counts={"fallback": "none"})
                await mca_events.flush_events(d)
                egs.reset()
                return await pa.collect_run(d, "run-e1-fail")
            finally:
                await d.close()

        view = asyncio.run(scenario())
        assert view["health"] == pa.HEALTH_FAILED
        assert view["health_label"] == "Не издано"

    def test_run_without_done_event_after_restart_is_incomplete(
            self, tmp_path):
        """Только реально-незавершённый прогон (START+стадии, финального
        события нет) → «Не завершён» (§61.13) + running-состояние."""

        async def scenario():
            d = await _inspector_db(tmp_path, name="asap4e_running.db")
            try:
                mca_events.reset_pending()
                pe.summary_start("run-e1-running", chat_id=100,
                                 mode="hybrid_l2", manual=False)
                pe.source_window("run-e1-running", chat_id=100, messages=688)
                pe.l1_stage("run-e1-running", chat_id=100, usable=True,
                            duration_ms=9000, threads=12)
                await mca_events.flush_events(d)
                egs.reset()
                return await pa.collect_run(d, "run-e1-running")
            finally:
                await d.close()

        view = asyncio.run(scenario())
        assert view["running"] is True
        assert view["health"] == pa.HEALTH_INCOMPLETE
        assert view["health_label"] == "Не завершён"

    def test_text_publication_recognized_from_durable_usage(self):
        """Канальный статус `text` из durable usage_json — тоже публикация
        (§61.6: publication × coverage, без опоры на канал)."""
        code, label = pa.health_of(
            {}, {"coverage": 100.0, "publication": "text"})
        assert code == pa.HEALTH_HEALTHY
        assert label == "Здоров"
        code, label = pa.health_of(
            {}, {"coverage": 44.6, "publication": "text"})
        assert code == pa.HEALTH_DEGRADED
        assert label == "С деградацией"

    def test_review_degraded_publication_survives_restart(self):
        """review_degraded (волна D): публикация ок и coverage 100%, но
        durable pipeline_health=degraded → после рестарта не «Здоров»
        (паритет с in-memory снапшотом)."""
        code, label = pa.health_of(
            {}, {"coverage": 100.0, "publication": "rich",
                 "pipeline_health": "degraded"})
        assert code == pa.HEALTH_DEGRADED
        assert label == "С деградацией"

    def test_done_outcome_failed_recognized_without_snapshot(self):
        """DONE outcome=failed (status-колонка отсутствует) — тот же
        финальный исход без in-memory снапшота."""
        code, label = pa.health_of({}, {"fallback": "none"},
                                   done_event={"outcome": "failed"})
        assert code == pa.HEALTH_FAILED
        assert label == "Не издано"

    def test_publication_failed_in_durable_usage_is_not_published(self):
        """publication=failed из durable usage_json → «Не издано»
        (рестарт-паритет in-memory-ветки publish_status=failed)."""
        code, label = pa.health_of(
            {}, {"coverage": None, "publication": "failed"})
        assert code == pa.HEALTH_FAILED
        assert label == "Не издано"


class TestRunViewStates:
    def test_repair_distinct_from_fallback_and_failure(self):
        events = [
            _ev("SUMMARY_L1_STAGE", duration_ms=5000),
            _ev("SUMMARY_L2_STAGE", duration_ms=15000),
            _ev("SUMMARY_L2_REVIEW", status="repaired", attempt=1,
                reason_code="quote_attribution_repaired"),
            _ev("COVER_BASE_SUCCEEDED"),
            _ev("COVER_RICH_PUBLISH_SUCCEEDED"),
            _ev("SUMMARY_RUN_DONE", usage={"coverage": 100.0,
                                           "publication": "rich"}),
        ]
        view = pa.build_run_view("run-1", _snap(), events)
        by_key = {n["key"]: n for n in view["nodes"]}
        assert by_key["l2_review"]["state"] == pa.STATE_REPAIRED
        assert by_key["l2_review"]["icon"] == "⚠"
        assert by_key["l2_review"]["status_label"] == "исправлено, продолжено"
        # …и это не fallback/failure-терминология (§61.7).
        assert by_key["l2_review"]["status_label"] != "резервный контур"
        assert by_key["l2_review"]["status_label"] != "не выполнено"

    def test_style_skipped_by_design_is_circle(self):
        events = [
            _ev("COVER_STYLE_SKIPPED", reason_code="no_style"),
            _ev("COVER_BASE_SUCCEEDED"),
            _ev("COVER_RICH_PUBLISH_SUCCEEDED"),
            _ev("SUMMARY_RUN_DONE", usage={"coverage": 100.0,
                                           "publication": "rich"}),
        ]
        view = pa.build_run_view("run-1", _snap(), events)
        style = [n for n in view["nodes"] if n["key"] == "style_edit"][0]
        assert style["state"] == pa.STATE_SKIPPED
        assert style["icon"] == "○"
        assert style["reason_ru"] == pa.reason_ru("no_style")

    def test_running_run_pending_tail(self):
        # §61.15: L1 ✓, L2 …, Cover ○ ожидает, Publish ○ ожидает.
        events = [
            _ev("SUMMARY_RUN_START", outcome="start"),
            _ev("SUMMARY_SOURCE_WINDOW", usage={"input_count": 100}),
            _ev("SUMMARY_L1_STAGE"),
        ]
        view = pa.build_run_view("run-1", None, events, running=True)
        by_key = {n["key"]: n for n in view["nodes"]}
        assert by_key["l1"]["icon"] == "✓"
        assert by_key["l2_review"]["state"] == pa.STATE_PENDING
        assert by_key["base_cover"]["state"] == pa.STATE_PENDING
        assert by_key["publish"]["status_label"] == "ожидает"
        assert view["running"] is True

    def test_drill_down_fields_safe(self):
        # §61.9: timestamps/provider/model/counts/coverage/publication/
        # message id; БЕЗ ключей/промптов/сырого чата.
        view = pa.build_run_view(
            "run-1", _snap(model="deepseek-v4-flash", provider="apinet.cloud"),
            _events_healthy())
        dev = view["developer"]
        assert dev["model"] == "deepseek-v4-flash"
        assert dev["provider"] == "apinet.cloud"
        assert view["publication"]["message_id"] == 4242
        assert view["publication"]["channel"] == "rich"
        assert view["coverage"]["total"] == 688
        blob = json.dumps(view, ensure_ascii=False)
        for forbidden in ("api_key", "apikey", "token", "prompt_text"):
            assert forbidden not in blob.lower() or forbidden == "token"
        assert "raw_chat" not in blob

    def test_empty_run_without_data(self):
        view = pa.build_run_view("run-x", None, [])
        assert view["nodes"] == []
        assert view["health"] == pa.HEALTH_INCOMPLETE


# ── §61.4/§61.5: агрегаты ───────────────────────────────────────────────────

class TestAggregates:
    def _rows(self):
        rows = []
        # L1: 9 ok, 1 failed → 90% success / 10% failed.
        for i in range(9):
            rows.append(_ev("SUMMARY_L1_STAGE", duration_ms=1000 + i))
        rows.append(_ev("SUMMARY_L1_STAGE", outcome="failed", status="failed",
                        reason_code="too_many_facts", duration_ms=800))
        # L2: 8 ok, 2 review-fallback.
        for i in range(8):
            rows.append(_ev("SUMMARY_L2_STAGE", duration_ms=20000))
        rows.append(_ev("SUMMARY_L2_STAGE", outcome="failed", status="failed",
                        reason_code="parse_error", duration_ms=5000))
        # Review: 6 ok, 2 repaired, 2 rejected (fallback).
        for i in range(6):
            rows.append(_ev("SUMMARY_L2_REVIEW", status="ok"))
        for i in range(2):
            rows.append(_ev("SUMMARY_L2_REVIEW", status="repaired",
                            reason_code="quote_attribution_repaired"))
        for i in range(2):
            rows.append(_ev("SUMMARY_L2_REVIEW", status="failed",
                            reason_code="l2_review_rejected"))
        # Style: 7 ok, 3 fallback (style_failed → base).
        for i in range(7):
            rows.append(_ev("COVER_STYLE_SUCCEEDED", duration_ms=9000))
        for i in range(3):
            rows.append(_ev("COVER_STYLE_FAILED",
                            reason_code="style_failed", duration_ms=25000))
        # Runs: 5 done — 2 healthy, 2 degraded (один по coverage), 1 failed.
        rows.append(_ev("SUMMARY_RUN_DONE", status="ok",
                        usage={"coverage": 100.0}))
        rows.append(_ev("SUMMARY_RUN_DONE", status="ok",
                        usage={"coverage": 100.0}))
        rows.append(_ev("SUMMARY_RUN_DONE", status="degraded",
                        usage={"coverage": 100.0}))
        rows.append(_ev("SUMMARY_RUN_DONE", status="ok",
                        usage={"coverage": 44.6}))
        rows.append(_ev("SUMMARY_RUN_DONE", status="failed",
                        usage={"coverage": None}))
        return rows

    def test_stage_percentages(self):
        agg = pa.aggregate_from_rows(self._rows())
        l1 = agg["stages"]["l1"]
        assert l1["total"] == 10
        assert l1["success_pct"] == 90.0
        assert l1["failed_pct"] == 10.0
        style = agg["stages"]["style_edit"]
        assert style["success_pct"] == 70.0
        assert style["fallback_pct"] == 30.0

    def test_review_buckets_repair_vs_fallback(self):
        agg = pa.aggregate_from_rows(self._rows())
        review = agg["stages"]["l2_review"]
        assert review["success_pct"] == 60.0
        assert review["repaired_pct"] == 20.0
        assert review["fallback_pct"] == 20.0

    def test_median_and_p95(self):
        agg = pa.aggregate_from_rows(self._rows())
        l1 = agg["stages"]["l1"]
        assert l1["median_ms"] is not None
        assert l1["p95_ms"] >= l1["median_ms"]

    def test_top3_failure_reasons(self):
        agg = pa.aggregate_from_rows(self._rows())
        l1 = agg["stages"]["l1"]
        assert l1["top_reasons"][0]["code"] == "too_many_facts"
        assert l1["top_reasons"][0]["ru"] == pa.reason_ru("too_many_facts")

    def test_run_totals_with_coverage_degraded(self):
        agg = pa.aggregate_from_rows(self._rows())
        totals = agg["totals"]
        assert totals["total"] == 5
        assert totals["healthy"] == 2
        # coverage 44.6% при публикации = degraded (§61.6).
        assert totals["degraded"] == 2
        assert totals["failed"] == 1

    def test_empty_window_is_not_fake_health(self):
        agg = pa.aggregate_from_rows([])
        assert agg["totals"]["total"] == 0
        assert agg["stages"] == {}

    def test_window_labels(self):
        assert pa.WINDOW_LABELS_RU[1] == "24 часа"
        assert pa.WINDOW_LABELS_RU[7] == "7 дней"


# ── §61.10: список runs ─────────────────────────────────────────────────────

class TestRunsList:
    def test_badges_and_path(self):
        entry = pa.run_list_entry(_ev(
            "SUMMARY_RUN_DONE", status="degraded",
            usage={"coverage": 100.0, "fallback": "legacy",
                   "publication": "rich", "source_total": 688}))
        assert entry["health"] == pa.HEALTH_DEGRADED
        assert entry["health_label"] == "С деградацией"
        assert "Legacy" in entry["path"]

    def test_coverage_below_100_downgrades_badge(self):
        entry = pa.run_list_entry(_ev(
            "SUMMARY_RUN_DONE", status="ok",
            usage={"coverage": 44.6, "publication": "rich"}))
        assert entry["health"] == pa.HEALTH_DEGRADED

    def test_healthy_entry(self):
        entry = pa.run_list_entry(_ev(
            "SUMMARY_RUN_DONE", status="ok",
            usage={"coverage": 100.0, "publication": "rich"}))
        assert entry["health"] == pa.HEALTH_HEALTHY
        assert "Hybrid" in entry["path"]

    def test_styled_path_flag(self):
        base = pa.run_list_entry(_ev(
            "SUMMARY_RUN_DONE", status="ok",
            usage={"coverage": 100.0, "publication": "rich"}))
        assert base["path"].endswith("базовая")
        styled = pa.run_list_entry(_ev(
            "SUMMARY_RUN_DONE", status="ok",
            usage={"coverage": 100.0, "publication": "rich"}), styled=True)
        assert styled["path"].endswith("стиль")

    def test_failed_publication_path(self):
        entry = pa.run_list_entry(_ev(
            "SUMMARY_RUN_DONE", status="failed",
            usage={"publication": "failed"}))
        assert entry["path"].endswith("без обложки")
        assert entry["health"] == pa.HEALTH_FAILED


# ── эмиссия стадийных событий (kill-switch, R17) ────────────────────────────

class TestEmission:
    def _recorded(self, monkeypatch):
        seen = []

        def _recorder(event_name, *, outcome, level="INFO", **fields):
            seen.append({"event_name": event_name, "outcome": outcome,
                         "level": level, **fields})
            return None

        import services.mca_trace as trace
        monkeypatch.setattr(trace, "emit_stage", _recorder)
        return seen

    def test_kill_switch_off_is_noop(self, monkeypatch):
        import config.settings as cs
        import services.direct_chat_service as _dcs
        for _cls in {type(settings), type(cs.settings), type(_dcs.settings)}:
            monkeypatch.setattr(_cls, "SUMMARY_PIPELINE_EVENTS_ENABLED",
                                False, raising=False)
        seen = self._recorded(monkeypatch)
        pe.summary_start("r1", chat_id=1, mode="hybrid_l2", manual=False)
        pe.summary_done_from_ctx(None)
        assert seen == []
        assert pe.events_enabled() is False

    def test_events_carry_pipeline_run_id(self, monkeypatch):
        seen = self._recorded(monkeypatch)
        pe.summary_start("r-42", chat_id=7, mode="hybrid_l2", manual=True)
        pe.source_window("r-42", chat_id=7, messages=688)
        pe.l1_stage("r-42", chat_id=7, usable=False,
                    invalid_reason="too_many_facts", duration_ms=900.5,
                    threads=3)
        by_name = {e["event_name"]: e for e in seen}
        start = by_name["SUMMARY_RUN_START"]
        assert start["outcome"] == "start"
        assert start["component"] == "summary"
        assert start["pipeline_run_id"] == "r-42"
        assert start["chat_id"] == 7
        assert start["usage_json"]["manual"] is True
        window = by_name["SUMMARY_SOURCE_WINDOW"]
        assert window["usage_json"]["input_count"] == 688
        l1 = by_name["SUMMARY_L1_STAGE"]
        assert l1["outcome"] == "failed"
        assert l1["reason_code"] == "too_many_facts"
        assert l1["duration_ms"] == 900
        assert l1["status"] == "failed"

    def test_review_ladder_statuses(self, monkeypatch):
        seen = self._recorded(monkeypatch)
        pe.l2_review("r", chat_id=1, metrics={
            "l2_review_calls": 3, "l2_first_pass_approved": 0,
            "l2_revision_count": 2, "l2_revision_fixed_count": 1,
            "l2_final_approved": 1})
        ev = [e for e in seen if e["event_name"] == "SUMMARY_L2_REVIEW"][0]
        assert ev["status"] == "ok"
        assert ev["attempt"] == 2
        pe.l2_review("r", chat_id=1, metrics={
            "l2_review_calls": 3, "l2_legacy_after_review": 1})
        ev2 = [e for e in seen if e["event_name"] == "SUMMARY_L2_REVIEW"][-1]
        assert ev2["status"] == "failed"
        assert ev2["reason_code"] == "l2_review_rejected"

    def test_no_review_calls_no_event(self, monkeypatch):
        seen = self._recorded(monkeypatch)
        pe.l2_review("r", chat_id=1, metrics={"l2_review_calls": 0})
        pe.l2_review("r", chat_id=1, metrics={})
        assert seen == []

    def test_done_event_from_ctx_r17_slice(self, monkeypatch):
        seen = self._recorded(monkeypatch)

        class _Ctx:
            run_id = "r-9"
            chat_id = 5
            status = "ok"
            pipeline_health = "degraded"
            source_coverage = 44.6
            source_total = 688
            source_considered = 307
            publish_status = "ok"
            publish_channel = "rich"
            publish_message_id = 777
            fallback = "legacy"
            package_grade = "degraded"
            reason = None

            def duration_ms(self):
                return 1234.0

        pe.summary_done_from_ctx(_Ctx())
        ev = seen[0]
        assert ev["event_name"] == "SUMMARY_RUN_DONE"
        assert ev["status"] == "degraded"
        usage = ev["usage_json"]
        assert usage["coverage"] == 44.6
        assert usage["publication"] == "rich"
        assert usage["message_id"] == 777
        assert usage["fallback"] == "legacy"
        # R17: только числа/коды/enum — без сырых текстов.
        assert "text" not in json.dumps(usage)

    def test_done_never_raises_on_broken_ctx(self, monkeypatch):
        seen = self._recorded(monkeypatch)

        class _Broken:
            run_id = "r-broken"

            def duration_ms(self):
                raise RuntimeError("boom")

        pe.summary_done_from_ctx(_Broken())     # fail-open: без исключения
        pe.summary_done_from_ctx(None)
        assert seen == []


# ── снапшот-проекция (in-memory state) ──────────────────────────────────────

class TestSnapshotProjection:
    def test_record_run_from_context_carries_wave_e_fields(self):
        class _Ctx:
            run_id = "snap-1"
            chat_id = 42
            mode = "hybrid_l2"
            source_count = 688
            threads = 12
            paragraphs = 9
            cover_status = "ok"
            format_channel = None
            format_status = None
            format_duration_ms = None
            publish_channel = "rich"
            publish_status = "ok"
            publish_duration_ms = 1400.0
            publish_message_id = 999
            source_total = 688
            source_considered = 307
            source_coverage = 44.6
            pipeline_health = "degraded"
            package_grade = "degraded"
            fallback = "legacy"
            model = "deepseek"
            provider = "apinet.cloud"
            reason = None
            stage_events = [{"stage": "l2_review", "attempt": 1,
                             "status": "repaired", "reason_code": "quote_x",
                             "secret_field": "MUST_NOT_LEAK"}]

            def duration_ms(self):
                return 1000.0

        egs.record_run_from_context(_Ctx(), None)
        snap = egs.get_run("snap-1")
        assert snap["source_coverage"] == 44.6
        assert snap["pipeline_health"] == "degraded"
        assert snap["fallback"] == "legacy"
        assert snap["model"] == "deepseek"
        events = snap["stage_events"]
        assert len(events) == 1
        assert "secret_field" not in events[0], "R17: только safe-ключи"

    def test_stage_events_bounded(self):
        events = [{"stage": "s", "attempt": i, "status": "ok"}
                  for i in range(100)]
        projected = egs._project_stage_events(events)
        assert len(projected) == egs._STAGE_EVENTS_MAX
        assert projected[-1]["attempt"] == 99

    def test_projection_fail_open(self):
        assert egs._project_stage_events(None) == []
        assert egs._project_stage_events("garbage") == []


# ── T-4445 guard §61.12: путь данных НЕ читает human-логи ───────────────────

class TestGuardNoLogParsing:
    _MODULES = (
        "services/pipeline_analytics.py",
        "services/pipeline_events.py",
    )

    def test_widget_modules_never_open_or_parse_logs(self):
        import re
        for rel in self._MODULES:
            with open(rel, "r", encoding="utf-8") as fh:
                src = fh.read()
            for pattern in (r"\bopen\(", r"read_text", r"read_bytes",
                            r"\bglob\(", r"subprocess", r"Path\("):
                assert not re.search(pattern, src), (
                    "%s: путь данных виджета не должен читать файлы/логи (%s)"
                    % (rel, pattern))

    def test_data_source_is_durable_structured_store(self):
        with open("services/pipeline_analytics.py", "r",
                  encoding="utf-8") as fh:
            src = fh.read()
        assert "FROM mca_events" in src, (
            "агрегаты/список — из durable mca_events (единый source)")
        assert "execution_graph_source" in src, (
            "Last Run — из structured снапшотов прогона")

    def test_no_human_log_imports(self):
        import services.pipeline_analytics as mod
        imported = getattr(mod, "__dict__", {})
        assert "summary_run_log" not in str(imported)
        assert not hasattr(mod, "log_summary_complete")
        # Событийный модуль не форматтирует human-логи пайплайна.
        import services.pipeline_events as pev
        assert not hasattr(pev, "log_summary_complete")


# ── kill-switch семантика агрегатов (spec §8.2: OFF → state-проекции) ───────

def _events_flag_off(monkeypatch) -> None:
    """Kill-switch OFF для ТЕКУЩЕГО инстанса settings (перезагрузки
    test_settings_worker_sync подменяют экземпляр/класс — патчим на месте,
    как conftest: ОБА класса активных инстансов)."""
    import config.settings as cs
    import services.direct_chat_service as _dcs
    for _cls in {type(settings), type(cs.settings), type(_dcs.settings)}:
        monkeypatch.setattr(_cls, "SUMMARY_PIPELINE_EVENTS_ENABLED",
                            False, raising=False)


class TestKillSwitchAggregates:
    def test_off_aggregate_honest_empty(self, monkeypatch):
        _events_flag_off(monkeypatch)
        import asyncio
        result = asyncio.run(pa.collect_aggregate(None, 7))
        assert result["available"] is False
        assert result["totals"]["total"] == 0
        assert result["window"]["label"] == "7 дней"

    def test_off_runs_list_empty(self, monkeypatch):
        _events_flag_off(monkeypatch)
        import asyncio
        assert asyncio.run(pa.collect_runs_list(None, limit=5)) == []

    def test_off_inspector_uses_state_projection(self, monkeypatch):
        # OFF: collect_run строит вид из снапшота без durable-событий.
        _events_flag_off(monkeypatch)
        import asyncio
        egs.record_run(run_id="off-1", status="ok",
                       source_coverage=100.0, publish_status="ok",
                       publish_channel="rich", pipeline_health="ok")
        try:
            view = asyncio.run(pa.collect_run(None, "off-1"))
            assert view["run_id"] == "off-1"
            assert view["health"] == pa.HEALTH_HEALTHY
        finally:
            egs.reset()


@pytest.fixture(autouse=True)
def _isolated_run_store():
    """In-memory реестр снапшотов — общий на процесс; изоляция тестов."""
    egs.reset()
    yield
    egs.reset()


# ── API RBAC (как существующие analytics-эндпоинты: requires_global_admin) ──

from fastapi.testclient import TestClient
from web.app import create_app

from tests.test_webapp_analytics_api import (
    ADMIN_ID,
    TEST_TOKEN,
    USER_NO_ROLE,
    _FakeConn,
    _FakePg,
    _hdr,
)
from services.config_cache import ConfigCache
from web.api import deps as deps_mod


@pytest.fixture
def client_pipeline(monkeypatch):
    """Каркас `test_webapp_analytics_api.client`: RBAC через fake PG;
    SQLite (mca_events) в тест-окружении отсутствует → fail-open shape."""
    import types as _types
    monkeypatch.setattr(deps_mod, "settings",
                        _types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    conn = _FakeConn()
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as tc:
        yield tc


class TestPipelineApiRbac:
    """401 unauth / 403 не-глобал / 200 admin (fail-open shape).

    Реюз проверенного каркаса `tests/test_webapp_analytics_api.py`
    (TestClient(create_app) + fake PG для RBAC). SQLite `get_lore_db()` в
    тестовом окружении None → эндпоинты честно деградируют в пустой shape
    (не 500)."""

    def test_401_without_init_data(self, client_pipeline):
        assert client_pipeline.get(
            "/api/analytics/pipeline/inspector").status_code == 401
        assert client_pipeline.get(
            "/api/analytics/pipeline/runs/some-run").status_code == 401

    def test_403_without_global_admin(self, client_pipeline):
        for path in ("/api/analytics/pipeline/inspector",
                     "/api/analytics/pipeline/runs/r1"):
            resp = client_pipeline.get(path, headers=_hdr(USER_NO_ROLE))
            assert resp.status_code == 403, path

    def test_200_admin_fail_open_shape(self, client_pipeline):
        resp = client_pipeline.get(
            "/api/analytics/pipeline/inspector?mode=latest",
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "latest"
        assert body["runs"] == []
        assert body["run"] is None
        resp = client_pipeline.get(
            "/api/analytics/pipeline/inspector?mode=24h",
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["aggregate"]["totals"]["total"] == 0
        assert body["aggregate"]["window"]["label"] == "24 часа"
        resp = client_pipeline.get(
            "/api/analytics/pipeline/runs/unknown-run",
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["run"] is not None   # честная пустая карта run
        assert resp.json()["run"]["nodes"] == []
