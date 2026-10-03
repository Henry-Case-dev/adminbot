"""ASAP 4.1 волна 2 (эпик asap-4-1-durable-whole-window-summary) — T-4606:
CoverageLedger strict-покрытия в CAPACITY_OVERFLOW (spec §1 A.3; ADR-1028-8
D2.4) и overflow-контур run_l1 (§44-B-инеграция).

Покрытие:
  * pure Ledger: source/segments/processed/fallback/missing; XOR-покрытие
    (каждое сообщение ∈ ≥1 сегмента; overlap по stable ID dedup);
  * fixture «сегмент упал» → restore (re-run только проблемного сегмента,
    ровно одна попытка) → coverage 100%;
  * fixture «сегмент упал навсегда» → честный degraded (НЕ «success»,
    событие SUMMARY_SEGMENT_LEDGER);
  * fixture «839/N → все N covered» (large overflow, no truncation);
  * потеря сообщений запрещена (fixture-контрпример «взять 300» ломает
    ledger — never passes);
  * R17: событие Ledger'а — только counts/percent/bool (без текстов).
"""
import json
import logging

import pytest

import services.model_capacity as mc
import services.summary_l1_clusterizer as sl1
from services.summary_coverage_ledger import (
    CoverageLedger,
    snapshot_dict,
    stable_message_id,
)

pytestmark = pytest.mark.asap41

CHAT_ID = -100555


@pytest.fixture(autouse=True)
def _clean():
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None


def _slot(monkeypatch, base_url, model):
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_BASE_URL", base_url,
                        raising=False)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_MODEL_NAME", model,
                        raising=False)


def _rows(count, *, text_size=40):
    return [
        {"id": i + 1, "tg_message_id": i + 1, "user_id": 10 + (i % 3),
         "author_name": f"Автор{i % 3}",
         "text": f"сообщение {i} о коммуналке и соседях " * (text_size // 10),
         "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
         "reply_to_id": None, "is_forward": 0, "forward_source": None}
        for i in range(count)
    ]


def _catalog_16k(monkeypatch):
    async def _catalog(url, *, headers=None):
        if "openrouter.ai/api/v1/models" in url:
            return {"data": [{"id": "small/small-16k",
                              "context_length": 16384}]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _catalog)


# ── Pure-Ledger контракты ───────────────────────────────────────────────────

def test_ledger_source_ids_from_rows():
    ledger = CoverageLedger(source_message_ids=[stable_message_id(r)
                                                for r in _rows(5)])
    assert ledger.source_message_ids == (1, 2, 3, 4, 5)


def test_ledger_xor_coverage_invariant_with_overlap():
    """XOR-инвариант: каждое сообщение ∈ ≥1 сегмента; overlap-дубликат
    (стабильный ID в двух соседних сегментах) — не потеря (dedup merge)."""
    ledger = CoverageLedger(source_message_ids=(1, 2, 3, 4))
    ledger.register_segment("segment_1", [1, 2, 3])
    ledger.register_segment("segment_2", [3, 4])     # overlap сообщения 3
    ledger.mark_processed([1, 2, 3, 4])
    status = ledger.verify()
    assert status["assignment_lossless"] is True
    assert status["missing"] == 0
    assert status["coverage_percent"] == 100.0


def test_ledger_missing_is_detectable():
    ledger = CoverageLedger(source_message_ids=(1, 2, 3, 4))
    ledger.register_segment("segment_1", [1, 2])
    ledger.mark_processed([1, 2])
    status = ledger.verify()
    assert status["assignment_lossless"] is False
    assert status["missing"] == 2
    with pytest.raises(ValueError):
        ledger.require_full_coverage()   # fail-closed перед Writer


def test_ledger_fallback_does_not_count_processed_twice():
    ledger = CoverageLedger(source_message_ids=(1, 2, 3))
    ledger.register_segment("segment_1", [1, 2])
    ledger.register_segment("segment_2", [3])
    ledger.mark_processed([1, 2])
    ledger.mark_fallback([3])
    status = ledger.verify()
    assert status["processed"] == 2 and status["fallback"] == 1
    assert status["missing"] == 0   # fallback фактически покрыт (degraded
    # подекларативно честен: fallback-not-success, missing only unaccounted)


def test_ledger_stranger_ids_rejected():
    ledger = CoverageLedger(source_message_ids=(1, 2))
    ledger.register_segment("segment_1", [1, 2, 999])   # 999 вне source
    ledger.mark_processed([1, 2, 999])
    status = ledger.verify()
    assert 999 not in ledger.processed_ids
    assert status["assigned"] == 2


def test_snapshot_dict_r17_safe():
    ledger = CoverageLedger(source_message_ids=(1, 2))
    ledger.register_segment("segment_1", [1, 2])
    ledger.mark_processed([1, 2])
    status = snapshot_dict(ledger)
    assert set(status) == {"segments", "source", "assigned", "processed",
                           "fallback", "missing", "coverage_percent",
                           "assignment_lossless"}


# ── Overflow-интеграция run_l1 (§44-B expanded) ─────────────────────────────

@pytest.mark.asyncio
async def test_overflow_all_messages_covered_no_truncation(monkeypatch):
    """Fixture «Большое окно → N сегментов → все covered»: coverage 100%,
    no truncation, L1-запросов = число сегментов, ledger overwrite честны."""
    _slot(monkeypatch, "https://openrouter.ai/api/v1", "small/small-16k")
    _catalog_16k(monkeypatch)
    rows = _rows(300)                            # serialized ~29K > allowance
    llm_call: list = []

    async def _call(messages):
        user = next(m["content"] for m in messages if m["role"] == "user")
        ids = [json.loads(line.strip())["message_id"]
               for line in user.splitlines() if line.strip().startswith('{"')]
        llm_call.append(ids)
        # ASAP 4.1 волна 3 (T-4607, ADR-1028-8 D3): map-режим — выход
        # L1 = semantic map v1 (без facts/текстов; ledger не меняется).
        topics = [{"topic_id": "topic_001", "title": "коммуналка",
                   "message_ids": ids, "participants": [],
                   "short_hint": ""}]
        return json.dumps({"schema_version": 1, "topics": topics,
                           "events": [], "unassigned_message_ids": []})

    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=_call,
                              correlation_id="run-overflow")
    assert result.usable
    plan = sl1._capacity_plan_snapshot()
    assert plan["mode"] == "CAPACITY_OVERFLOW"
    assert plan["segments"] == len(llm_call)     # L1-запросов = сегментам
    assert result.truncated is False
    assert result.skipped_ids == ()
    covered = set()
    for ids in llm_call:
        covered.update(ids)
    assert covered == {row["tg_message_id"] for row in rows}
    coverage = sl1.last_run_coverage()
    assert coverage["source_messages_processed"] == len(rows)
    assert coverage["coverage_percent"] == 100.0


@pytest.mark.asyncio
async def _run_with_fail_second_segment(monkeypatch, permanently_fail):
    _slot(monkeypatch, "https://openrouter.ai/api/v1", "small/small-16k")
    _catalog_16k(monkeypatch)
    rows = _rows(300)
    calls: list = []
    state: dict = {}

    async def _call(messages):
        calls.append(None)
        user = next(m["content"] for m in messages if m["role"] == "user")
        ids = [json.loads(line.strip())["message_id"]
               for line in user.splitlines() if line.strip().startswith('{"')]
        calls[-1] = ids
        start = ids[0]
        state.setdefault("attempt_by_start", {})
        attempts = state["attempt_by_start"]
        attempts[start] = attempts.get(start, 0) + 1
        starts = state.setdefault("starts", [])
        if start not in starts:
            starts.append(start)
        # Сегмент №2 (вторая уникальная партиция): первая (!) попытка
        # падает; при permanently_fail — ВСЕ попытки падают.
        if len(starts) >= 2 and start == starts[1]:
            attempt = attempts[start]
            if permanently_fail or attempt == 1:
                raise RuntimeError("provider segment down")
        # ASAP 4.1 волна 3 (T-4607, ADR-1028-8 D3): map-режим — выход
        # L1 = semantic map v1 (без facts/текстов; ledger не меняется).
        topics = [{"topic_id": "topic_001", "title": "коммуналка",
                   "message_ids": ids, "participants": [],
                   "short_hint": ""}]
        return json.dumps({"schema_version": 1, "topics": topics,
                           "events": [], "unassigned_message_ids": []})

    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=_call,
                              correlation_id="run-failseg")
    return result, calls, rows


@pytest.mark.asyncio
async def test_segment_fails_restored_by_single_rerun(monkeypatch):
    """Fixture «сегмент упал» → restore: re-run ТОЛЬКО проблемного сегмента
    (одна доп. попытка), покрытие затем 100 % (не degraded)."""
    result, call_payloads, _rows_used = await _run_with_fail_second_segment(
        monkeypatch, permanently_fail=False)
    assert result.usable
    coverage = sl1.last_run_coverage()
    assert coverage["coverage_percent"] == 100.0
    assert coverage["reason"] is None
    plan = sl1._capacity_plan_snapshot()
    # Restore = одна дополнительная попытка проблемного сегмента:
    # L1-запросов = сегменты + 1.
    assert len(call_payloads) == plan["segments"] + 1


# ── Честный degraded (сегмент не восстановился) ─────────────────────────────

@pytest.mark.asyncio
async def test_segment_permanent_failure_is_honest_degraded(monkeypatch,
                                                            caplog):
    """Fixture «сегмент упал навсегда» → run НЕ выглядит как normal
    success: L1 → error (LEVEL-2 ladder достраивает честный fallback из
    ПОЛНОГО набора), событие SUMMARY_SEGMENT_LEDGER несёт fallback>0."""
    import config.settings as _cs
    from config.settings import Settings as _S
    for _cls in {_S, type(_cs.settings), type(sl1.settings)}:
        monkeypatch.setattr(_cls, "SUMMARY_PIPELINE_EVENTS_ENABLED", True,
                            raising=False)
    caplog.set_level(logging.INFO)
    result, call_payloads, rows_used = await _run_with_fail_second_segment(
        monkeypatch, permanently_fail=True)
    plan = sl1._capacity_plan_snapshot()
    restored_segment_ids = set()
    for ids in call_payloads:
        restored_segment_ids.update(ids or ())
    # Честный degraded (T-4608, spec §2 B.2): успешные maps сохраняются,
    # невосстановимый сегмент → deterministic MINIMAL map (ids не теряются,
    # никогда не 0/839); итог map_degraded, НЕ маскированный ok-маской.
    assert result.usable
    assert result.map_degraded
    assert result.map_reason == "map_degraded"
    payload_ids = set()
    for topic in (result.payload or {}).get("topics") or []:
        payload_ids.update(topic.get("message_ids") or [])
    assert payload_ids == {row["tg_message_id"] for row in rows_used}
    coverage = sl1.last_run_coverage()
    assert coverage and coverage["coverage_percent"] == 100.0
    texts = [r.getMessage() for r in caplog.records]
    # События сегмента честно показывают провал сегмента (не «ok» везде).
    assert any("SUMMARY_SEGMENT_RESULT" in t and "outcome=failed" in t
               for t in texts)
    # Minimal map виден явно (честный маркер деградации).
    assert any("SUMMARY_SEGMENT_MINIMAL_MAP" in t for t in texts)
    # Честные дополнительные попытки: ровно одна restore на сегмент.
    assert len(call_payloads) == plan["segments"] + 1


# ── «Потеря сообщений» невозможна по построению (fixture-контрпример §10) ──

@pytest.mark.asyncio
async def test_model_omission_cannot_lose_messages(monkeypatch):
    """Fixture-контрпример «взять 300» невозможен по построению: модель
    атрибутирует только первый ID сегмента — валидатор §95-v2 ловит
    неатрибуированные id в auto-unassigned (вход всегда ≥ выход), Ledger
    missing == 0; прозрачно в coverage 100 %. Полная потеря сегмента
    возможна ТОЛЬКО через его провал (см. честный degraded выше) — то
    видно через mark_fallback/missing."""
    _slot(monkeypatch, "https://openrouter.ai/api/v1", "small/small-16k")
    _catalog_16k(monkeypatch)
    rows = _rows(300)
    attributed: list = []

    async def _call(messages):
        user = next(m["content"] for m in messages if m["role"] == "user")
        ids = [json.loads(line.strip())["message_id"]
               for line in user.splitlines() if line.strip().startswith('{"')]
        attributed.extend(ids[:1])
        # Атрибутируем ТОЛЬКО первый ID каждого сегмента — валидатор
        # сегмента поместит остальные в unassigned (покрытие сохраняется).
        threads = [{"thread_id": "T1", "topic": "коммуналка",
                    "message_ids": ids[:1],
                    "facts": [{"text": "обсуждали коммуналку",
                               "evidence_message_ids": ids[:1]}]}]
        return json.dumps({"schema_version": 2, "threads": threads,
                           "unassigned_message_ids": []})

    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=_call,
                              correlation_id="run-loss")
    # Ни одного потерянного сообщения (механизм auto-unassigned + ledger).
    assert result.usable
    all_ids = {m for m in attributed}
    coverage = sl1.last_run_coverage()
    assert coverage["coverage_percent"] == 100.0
    assert coverage["source_messages_unprocessed"] == 0
    assert len(all_ids) == sl1._capacity_plan_snapshot()["segments"]
