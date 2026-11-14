"""SMART-EXECUTION-RELIABILITY-01 I4 — unmapped reason codes (контракт/регресс).

Прод-факт (recon 2026-11-14 §8): события `experience.fresh_stream_lag` и
`detector_scan` (и ещё шесть наблюдавшихся маркеров) писались с
`reason_code=unmapped:<sha256(code)[:8]>`, потому что producer-код реального
эмиттера отсутствовал в единственном реестре `mca_events.REASON_CODES`.

Правила I4, которые здесь закреплены:
  * каждый восстановленный producer-код — канонический код единственного
    реестра (без второго словаря и без универсального `unknown`);
  * штатный skip/информационный исход не превращается в failure;
  * неизвестный код по-прежнему остаётся честным `unmapped:<sha8>` и виден
    WARN-строкой без сырого значения (warning не удаляется);
  * утечки секретов/произвольного payload нет.

Тесты не привязаны к двум конкретным идентификаторам: проверяется весь
наблюдавшийся набор маркеров и все литеральные reason_code эмиттеров
семейства (AST-мета-тест), поэтому новое расхождение снова даст RED.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from services import mca_events as me

REPO = Path(__file__).resolve().parents[1]

#: Раскодированные маркеры production recon §8: sha256(code)[:8] → producer-код.
#: Доказательство декодирования — совпадение sha8 со строковым литералом
#: реального emit-сайта (см. test_marker_digest_matches_producer_code).
PRODUCTION_MARKERS = {
    "18d14796": "fresh_stream_lag",
    "4f8aced7": "detector_scan",
    "a999e0fd": "detector_fact_user",
    "373cf2f7": "tool_claim",
    "d07c353d": "limit_unknown",
    "69e80269": "archive_direction",
    "38dc4799": "archive_coverage",
    "54c94ee2": "samples_selected",
}

#: Коды тех же emit-путей, доказанные по коду (`emit_mca_event`), но пока не
#: наблюдавшиеся отдельным прод-маркером.
ADJACENT_CODES = (
    "detector_preference",
    "detector_correction",
    "stale_belief",
    "lesson_contradiction",
    "owner_reset_learning",
    "anomaly_recovered",
    "cover_context_missing",
)

RESTORED_CODES = tuple(PRODUCTION_MARKERS.values()) + ADJACENT_CODES

#: Штатные skip-исходы: событие остаётся skipped/WARN, не failed.
SKIP_CODES = ("fresh_stream_lag", "stale_belief", "lesson_contradiction",
              "cover_context_missing")
#: Success-исходы (информационные проходы).
SUCCESS_CODES = ("detector_scan", "detector_preference", "detector_correction",
                 "detector_fact_user", "archive_direction", "archive_coverage",
                 "samples_selected", "owner_reset_learning",
                 "anomaly_recovered", "tool_claim")
#: Start-исход (наблюдаемый degraded-маркер лимита, не failure).
START_CODES = ("limit_unknown",)

#: Модули-эмиттеры семейства I4: reason_code у этих вызовов обязан быть в
#: единственном реестре. Второго словаря кодов не заводим.
EMITTER_MODULES = (
    "services/mca_experience_jobs.py",
    "services/mca_experience.py",
    "services/mca_humor_feedback.py",
    "services/mca_sample_library.py",
    "services/summary_generator.py",
    "services/tool_router.py",
    "services/temporal_factcheck.py",
    "services/cover_style_jobs.py",
)
#: Обёртки единственной точки эмиссии (`mca_events.emit_mca_event`).
EVENT_WRAPPERS = frozenset({
    "_emit", "emit_mca_event", "emit_cover_event", "stage_event",
    "pipeline_stage_event", "emit_stage",
})


@pytest.fixture(autouse=True)
def _clean_pending():
    me.reset_pending()
    yield
    me.reset_pending()


@pytest.fixture
def captured(monkeypatch):
    """Перехватить реальные события единственной точки эмиссии."""
    events: list[dict] = []
    real = me.emit_mca_event

    def _spy(event_name, *, outcome, level="INFO", **fields):
        event = real(event_name, outcome=outcome, level=level, **fields)
        events.append(event)
        return event

    monkeypatch.setattr(me, "emit_mca_event", _spy)
    return events


def _by_name(events, name):
    rows = [e for e in events if e and e.get("event_name") == name]
    assert rows, f"event {name} not emitted; got {[e and e.get('event_name') for e in events]}"
    return rows[-1]


def _assert_canonical(event, code):
    assert event.get("reason_code") == code, event
    assert not str(event.get("reason_code")).startswith(me.UNMAPPED_REASON_PREFIX)


# ── декодирование маркеров и реестр ────────────────────────────────────────

@pytest.mark.parametrize("marker,code", sorted(PRODUCTION_MARKERS.items()))
def test_marker_digest_matches_producer_code(marker, code):
    """sha8 прод-маркера — это sha256 самого producer-кода (декодирование)."""
    assert hashlib.sha256(code.encode("utf-8")).hexdigest()[:8] == marker


@pytest.mark.parametrize("code", RESTORED_CODES)
def test_restored_code_is_canonical_in_single_registry(code):
    """Код есть в REASON_CODES и строится в событие без unmapped-маркера."""
    assert code in me.REASON_CODES
    event = me.build_event("I4_CONTRACT", outcome=me.OUTCOME_SKIPPED,
                           reason_code=code)
    assert event is not None
    _assert_canonical(event, code)


def test_registry_has_no_duplicate_entries():
    """Реестр без дублей: frozenset молча дедуплицирует, поэтому смотрим AST."""
    tree = ast.parse((REPO / "services/mca_events.py").read_text(encoding="utf-8"))
    values: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "REASON_CODES" not in targets:
            continue
        call = node.value
        assert isinstance(call, ast.Call) and call.args
        container = call.args[0]
        for item in getattr(container, "elts", []):
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                values.append(item.value)
    assert values, "REASON_CODES literal not found"
    duplicates = sorted({v for v in values if values.count(v) > 1})
    assert not duplicates, f"duplicate reason codes: {duplicates}"


def test_producer_emit_sites_only_use_registered_codes():
    """AST-мета-тест: литеральные reason_code эмиттеров семейства I4 —
    только из единственного реестра (не подгонка под два идентификатора)."""
    missing: list[str] = []
    for rel in EMITTER_MODULES:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name not in EVENT_WRAPPERS:
                continue
            for kw in node.keywords:
                if kw.arg != "reason_code":
                    continue
                val = kw.value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    if val.value and val.value not in me.REASON_CODES:
                        missing.append(f"{rel}:{node.lineno} {val.value!r}")
    assert not missing, "unmapped producer reason_code(s): " + ", ".join(missing)


def test_detector_class_family_is_registered():
    """Динамический шаблон `detector_<class>` покрыт для закрытого набора
    классов детектора (иначе класс снова станет unmapped)."""
    from services import mca_experience_jobs as mj
    classes = {mj.DETECTOR_CLASS_PREFERENCE, mj.DETECTOR_CLASS_CORRECTION,
               mj.DETECTOR_CLASS_FACT_USER}
    # Классы детектора — подмножество закрытого отображения kind→class
    # (смена константы без обновления отображения ломает этот тест).
    assert classes <= set(mj.SEMANTIC_CLASS_BY_KIND.values())
    for cls in sorted(classes):
        code = f"detector_{cls}"
        assert code in me.REASON_CODES, code
        event = me.build_event("detector_signal", outcome=me.OUTCOME_SUCCESS,
                               reason_code=code)
        _assert_canonical(event, code)


# ── неизвестный код остаётся честным unmapped ──────────────────────────────

def test_unknown_code_stays_unmapped_and_not_collapsed(caplog):
    """Warning не удалён, неизвестные коды не схлопываются в один и не
    публикуют сырое значение (R17)."""
    import logging

    unknown_a = "i4_unregistered_producer_alpha"
    unknown_b = "i4_unregistered_producer_beta"
    with caplog.at_level(logging.WARNING, logger="services.mca_events"):
        ev_a = me.build_event("I4_UNKNOWN", outcome=me.OUTCOME_SKIPPED,
                              reason_code=unknown_a)
        ev_b = me.build_event("I4_UNKNOWN", outcome=me.OUTCOME_SKIPPED,
                              reason_code=unknown_b)
    mark_a, mark_b = ev_a["reason_code"], ev_b["reason_code"]
    assert mark_a.startswith(me.UNMAPPED_REASON_PREFIX)
    assert mark_b.startswith(me.UNMAPPED_REASON_PREFIX)
    assert mark_a != mark_b                       # не один универсальный код
    assert mark_a not in me.REASON_CODES
    assert unknown_a not in str(ev_a)
    assert unknown_b not in str(ev_b)
    warns = [r.getMessage() for r in caplog.records
             if "unmapped reason_code" in r.getMessage()]
    assert len(warns) >= 2                        # warning сохранён
    assert all(unknown_a not in w and unknown_b not in w for w in warns)


# ── producer-исходы: skip ≠ failure, payload R17-safe ──────────────────────

def test_fresh_stream_lag_producer_is_skip_with_canonical_code(captured,
                                                              monkeypatch):
    """Реальный эмиттер лага: skipped/WARN, канонический код, только числа."""
    from services import mca_experience_jobs as mj

    monkeypatch.setattr(mj, "fresh_lag_warn_rows", lambda: 500)
    runner = mj.ExperienceReviewRunner(db=object())
    payload = {mj.SEMANTIC_PENDING_KEY: {"42": 14399},
               f"{mj.SEMANTIC_CURSOR_PREFIX}42": 12992,
               "counters": {}}
    runner._note_fresh_lag(payload)

    event = _by_name(captured, "experience.fresh_stream_lag")
    _assert_canonical(event, "fresh_stream_lag")
    assert event["outcome"] == me.OUTCOME_SKIPPED      # штатный skip
    assert event["level"] == me.LEVEL_WARN             # не ERROR/failure
    assert event["chat_id"] == "42"
    usage = str(event.get("usage_json") or "")
    assert '"lag_rows": 14399' in usage                # диагностический смысл
    assert '"threshold": 500' in usage
    assert "message" not in usage and "text" not in usage


@pytest.mark.asyncio
async def test_archive_direction_producer_is_success_with_canonical_code(
        captured, monkeypatch):
    """Реальный селектор направления архива: success (не failure)."""
    from services import mca_experience_jobs as mj

    class _Draw:
        index = 0
        source = "random"

    class _Source:
        async def draw_index(self, total, *, chat_id, purpose):
            return _Draw()

    runner = mj.ExperienceReviewRunner(db=object())
    monkeypatch.setattr(runner, "_random_source", _Source())
    payload = {"counters": {}}
    chosen = await runner._pick_archive_direction(
        payload, [{"chat_id": 7, "year": 2024, "weight": 1.0}])

    assert chosen == {"chat_id": 7, "year": 2024, "weight": 1.0}
    event = _by_name(captured, "experience.archive_direction_selected")
    _assert_canonical(event, "archive_direction")
    assert event["outcome"] == me.OUTCOME_SUCCESS
    assert event["level"] == me.LEVEL_INFO


def test_cover_limit_unknown_producer_keeps_start_semantics(captured):
    """Реальный эмиттер стадии cover: limit_unknown — start, не failure."""
    from services import cover_style_jobs as csj
    from services import cover_prompt_assembly as cpa

    csj.emit_cover_event(cpa.COVER_LIMIT_UNKNOWN, outcome="start",
                         status="limit_unknown", reason_code="limit_unknown")
    event = _by_name(captured, cpa.COVER_LIMIT_UNKNOWN)
    _assert_canonical(event, "limit_unknown")
    assert event["outcome"] == me.OUTCOME_START
    assert event["level"] == me.LEVEL_INFO


def test_cover_context_missing_producer_is_skip_not_failure(captured):
    """cover_context_missing — skipped (degraded публикация), не failed."""
    from services import cover_style_jobs as csj
    from services import cover_prompt_assembly as cpa

    csj.emit_cover_event(cpa.COVER_ANOMALY, outcome="skipped",
                         status="cover_context_missing",
                         reason_code="cover_context_missing")
    event = _by_name(captured, cpa.COVER_ANOMALY)
    _assert_canonical(event, "cover_context_missing")
    assert event["outcome"] == me.OUTCOME_SKIPPED
    assert event["level"] != me.LEVEL_ERROR


def test_factcheck_tool_claim_stage_is_success_with_canonical_code(captured):
    """Tool-маршрут фактчека: tool_claim — success (не failure)."""
    from services import temporal_factcheck as tf

    tf.stage_event("target_resolve", "success", reason_code="tool_claim",
                   chat_id=11, pipeline_run_id="run-i4")
    event = _by_name(captured, "factcheck_temporal")
    _assert_canonical(event, "tool_claim")
    assert event["outcome"] == me.OUTCOME_SUCCESS
    assert event["level"] == me.LEVEL_INFO
    assert event["stage"] == "target_resolve"
