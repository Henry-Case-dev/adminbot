"""MCA-10a `mca-10a-random-source-anu` — focused-тесты блока E (T-4982).

Покрытие (GEN-R17, spec D10/§11):
  * процесс `random.source` v1 в реестре mca-17a: стадии по санкции
    (activate→receive→buffer→draw→select→fallback→result), notable-события
    (random_activation/random_batch/random_fallback), widget-ID — контракт
    mca-17c (UI не делается), state_source/trigger/gate;
  * OFF → честный `disabled`; без реальных событий — `not_run`; с событием —
    `implemented` (не выдаём декларацию за факт);
  * reason_code — только аддитивно и только из единого словаря
    (`quantum_activated`/`quota_exhausted` +2; прочие переиспользуются);
  * R17: события не несут ключ/отпечаток/сырой текст (единый emit-контракт);
  * без нового шума телеметрии: draw/select/result — durable-журнал,
    per-draw событий нет.
"""
import asyncio
import re
from pathlib import Path

import pytest

from services import mca_events
from services import mca_gates
from services import mca_process_registry as reg
from services import mca_random_source as mrs

ROOT = Path(__file__).resolve().parent.parent
_SRC = (ROOT / "services" / "mca_random_source.py").read_text(encoding="utf-8")

STAGES = ("activate", "receive", "buffer", "draw", "select", "fallback",
          "result")
NOTABLE_EVENTS = ("random_activation", "random_batch", "random_fallback")


def _process() -> reg.ProcessDefinition:
    process = reg.get_process("random.source")
    assert process is not None, "процесс random.source не зарегистрирован"
    return process


def test_process_declared_per_sanction():
    p = _process()
    assert p.version == "1"
    assert p.stages == STAGES
    assert p.trigger_kind == "background"
    assert p.owner_feature == "mca-10a"
    assert p.enabled_gate == "MCA_RANDOM_SOURCE_ENABLED"
    assert p.widget_id == "Источник случайности"      # контракт mca-17c
    assert p.state_source == ("mca_random_batches", "mca_random_draws",
                              "mca_random_quota_state", "task_jobs")
    assert p.recovery_ops == ("refill_resume", "draw_reconcile")
    assert set(p.settings_ref) >= {"MCA_RANDOM_SOURCE_ENABLED",
                                   "MCA_RANDOM_QUANTUM_ENABLED",
                                   "MCA_RANDOM_REFILL_ENABLED",
                                   "MCA_RANDOM_EXPLORATION_ENABLED",
                                   "MCA_DREAM_RANDOM_EXPLORE_ENABLED"}


def test_notable_events_only_no_per_draw_spam():
    p = _process()
    assert p.stages_to_events == {"activate": "random_activation",
                                  "receive": "random_batch",
                                  "fallback": "random_fallback"}
    assert p.instrumentation == ("activate", "receive", "fallback")
    assert p.event_names == NOTABLE_EVENTS
    # draw/select/result — durable-журнал, НЕ событийный поток (без шума).
    for stage in ("draw", "select", "result"):
        assert stage not in p.stages_to_events
        assert stage not in p.instrumentation


def test_gate_resolver_registered():
    assert reg._GATE_RESOLVERS["MCA_RANDOM_SOURCE_ENABLED"] == \
        "random_source_enabled"
    assert reg.runtime_status(_process()) == reg.STATUS_IMPLEMENTED


def test_runtime_status_not_run_and_disabled(monkeypatch):
    p = _process()
    # Декларация есть, реальных событий нет → честный not_run.
    assert reg.runtime_status(
        p, event_names_present=frozenset({"unrelated"})) == reg.STATUS_NOT_RUN
    # Реальное событие → implemented.
    assert reg.runtime_status(
        p, event_names_present=frozenset({"random_batch"})) == \
        reg.STATUS_IMPLEMENTED
    # K1 OFF → disabled (не выдаём «активно»).
    monkeypatch.setattr(mca_gates, "random_source_enabled", lambda: False)
    assert reg.runtime_status(
        p, event_names_present=frozenset({"random_batch"})) == \
        reg.STATUS_DISABLED
    assert reg.runtime_status(p) == reg.STATUS_DISABLED


def test_registry_snapshot_contains_process():
    snap = asyncio.run(reg.registry_snapshot(db=None))
    row = next(r for r in snap["processes"]
               if r["process_id"] == "random.source")
    assert row["version"] == "1"
    assert tuple(row["stages"]) == STAGES
    assert row["widget_id"] == "Источник случайности"


def test_reason_codes_additive_only():
    # +2 санкции — в единственном словаре; прочие переиспользуются.
    assert "quantum_activated" in mca_events.REASON_CODES
    assert "quota_exhausted" in mca_events.REASON_CODES
    for reused in ("provider_unavailable", "provider_unconfigured",
                   "auth_failed", "random_fallback", "validation_failed",
                   "timeout", "rate_limit", "delivery_unknown", "disabled",
                   "no_eligible_alternative", "invalid_url",
                   "scheme_not_allowed", "redirect_blocked"):
        assert reused in mca_events.REASON_CODES, reused
    # Коды, которые реально эмитит контур (литералы + AnuError), все в словаре.
    literals = set(re.findall(r'reason_code="([a-z_]+)"', _SRC))
    assert literals, "литеральные reason_code не найдены"
    assert literals <= mca_events.REASON_CODES, literals
    anu_codes = set(re.findall(r'AnuError\("([a-z_]+)"', _SRC))
    assert anu_codes <= mca_events.REASON_CODES, anu_codes


def test_event_names_exist_in_code_scan():
    # Сверка mca-17a: declared event_names реально эмитируются кодом
    # (`_emit("random_...")`).
    emitted = set(re.findall(r'_emit\(\s*["\']([A-Za-z0-9_]+)["\']', _SRC))
    assert set(NOTABLE_EVENTS) <= emitted, emitted


def test_r17_event_payload_has_no_key(monkeypatch):
    captured: list = []

    def fake_emit(event_name, *, outcome, **fields):
        # Единый контракт mca-13: unknown/небезопасные поля отбрасываются.
        captured.append(mca_events.build_event(event_name, outcome=outcome,
                                               **fields))
        return {}

    monkeypatch.setattr(mrs.mca_events, "emit_mca_event", fake_emit)
    monkeypatch.setattr(mca_gates, "random_source_enabled", lambda: True)
    svc = mrs.RandomSourceService(None)
    svc._emit("random_activation", outcome=mca_events.OUTCOME_SUCCESS,
              reason_code="quantum_activated", stage="activate",
              provider=mrs.PROVIDER_ANU,
              entity_ids={"batch_id": "b1"},
              key="must-not-leak", api_key="must-not-leak")
    assert len(captured) == 1
    event = captured[0]
    assert event is not None
    assert event["event_name"] == "random_activation"
    assert event["reason_code"] == "quantum_activated"
    assert "key" not in event and "api_key" not in event
    assert "must-not-leak" not in str(event)
    # Неизвестный reason_code тоже не проходит единый словарь.
    built = mca_events.build_event("random_activation", outcome="success",
                                   reason_code="invented_code")
    assert built is not None and "reason_code" not in built
