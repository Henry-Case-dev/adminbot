"""ASAP-2 round1027 (T-3945, контракт (b)) — юниты deterministic repair
``services/summary_l1_repair.py``: шаги 1–7, формула useless (Q3), чистота
(вход не мутируется), детерминизм, R17-safe отчёт (int/bool)."""
from __future__ import annotations

import copy
import json

from services.summary_l1_contract import build_id_space
from services.summary_l1_repair import (
    USELESS_MASS_UNKNOWN_IDS,
    USELESS_NO_FACTS,
    USELESS_NO_TOPICS,
    repair_l1,
)


def _space(*ids):
    return build_id_space([{"message_id": i, "timestamp": i} for i in ids])


def _thread(thread_id="thread_001", topic="тема", ids=(), facts=()):
    return {"thread_id": thread_id, "topic": topic,
            "message_ids": list(ids),
            "facts": [{"text": t, "evidence_message_ids": list(e)}
                      for t, e in facts]}


def _data(threads=(), unassigned=()):
    return {"schema_version": 2, "threads": list(threads),
            "unassigned_message_ids": list(unassigned)}


# ── Шаг 1: unknown id в message_ids ────────────────────────────────────────

def test_step1_removes_unknown_message_ids():
    th = _thread(ids=(101, 999, 102))
    data = _data([th])
    repaired, report = repair_l1(data, _space(101, 102))
    assert repaired["threads"][0]["message_ids"] == [101, 102]
    assert report.unknown_ids_removed == 1


# ── Шаг 2: evidence unknown → удалить; существующий вне membership → добавить

def test_step2_expands_membership_from_evidence():
    th = _thread(ids=(101,), facts=[("факт", (102,))])
    repaired, report = repair_l1(_data([th]), _space(101, 102))
    thread = repaired["threads"][0]
    assert thread["message_ids"] == [101, 102]         # membership расширен
    assert report.evidence_membership_added == 1
    assert report.unknown_ids_removed == 0
    assert not report.useless                          # topics/facts целы


def test_step2_drops_unknown_evidence_and_facts_when_empty():
    th = _thread(ids=(101,), facts=[("факт", (999,))])
    repaired, report = repair_l1(_data([th]), _space(101))
    assert repaired["threads"][0]["facts"] == []
    assert report.unknown_ids_removed == 1
    assert report.facts_removed == 1


# ── Шаг 3/4: fact без evidence; пустой topic ───────────────────────────────

def test_step3_empty_evidence_fact_removed():
    th = _thread(ids=(101,), facts=[("факт", ())])
    repaired, report = repair_l1(_data([th]), _space(101))
    assert repaired["threads"][0]["facts"] == []
    assert report.facts_removed == 1
    # тред с сообщениями, но без фактов — СОХРАНЯЕТСЯ (шаг 4).
    assert report.topics_removed == 0
    assert len(repaired["threads"]) == 1


def test_step4_removes_fully_empty_thread_only():
    t1 = _thread("thread_001", ids=(), facts=())
    t2 = _thread("thread_002", ids=(101,), facts=[("ф", (101,))])
    repaired, report = repair_l1(_data([t1, t2]), _space(101))
    assert report.topics_removed == 1
    assert [t["thread_id"] for t in repaired["threads"]] == ["thread_002"]
    assert report.facts_after == 1
    assert not report.useless                          # 1 тема/1 факт цела


# ── Шаг 5: unassigned unknown + конфликт с membership ──────────────────────

def test_step5_membership_wins_over_unassigned():
    th = _thread(ids=(101,))
    data = _data([th], unassigned=(101, 999, 102))
    repaired, report = repair_l1(data, _space(101, 102))
    assert repaired["unassigned_message_ids"] == [102]
    assert report.unassigned_conflicts_resolved == 1
    assert report.unknown_ids_removed == 1             # 999 из unassigned


# ── Шаг 6: overlapping memberships (информационно) ─────────────────────────

def test_step6_counts_overlapping_memberships():
    t1 = _thread("thread_001", ids=(101, 102))
    t2 = _thread("thread_002", ids=(102, 103))
    repaired, report = repair_l1(_data([t1, t2]), _space(101, 102, 103))
    assert report.overlapping_topic_memberships == 1   # 102 в двух тредах
    assert [t["message_ids"] for t in repaired["threads"]] == \
        [[101, 102], [102, 103]]                      # пересечение — норма v2


# ── Шаг 7: формула useless (Q3) ────────────────────────────────────────────

def test_useless_no_topics():
    th = _thread(ids=(), facts=())
    repaired, report = repair_l1(_data([th]), _space(101))
    assert report.topics_after == 0
    assert report.useless and report.useless_reason == USELESS_NO_TOPICS


def test_useless_no_facts():
    th = _thread(ids=(101, 102))                       # тема без фактов цела
    repaired, report = repair_l1(_data([th]), _space(101, 102))
    assert report.topics_after == 1 and report.facts_after == 0
    assert report.useless and report.useless_reason == USELESS_NO_FACTS


def test_useless_mass_unknown_ids_over_half():
    # real: 100,101,102; LLM выдумал 999999 среди 4 ссылок → 1/4 = 25% → НЕ
    # useless (пример владельца §6:2160–2172).
    good = _thread(ids=(100, 101, 999999, 102), facts=[("ф", (100,))])
    repaired, report = repair_l1(_data([good]), _space(100, 101, 102))
    assert report.unknown_ids_removed == 1
    assert not report.useless
    # 3 из 5 ссылок выдуманы (60% > 0.5) при живых topics/facts → useless
    # mass_unknown_ids (порядок формулы Q3: no_topics → no_facts → ratio).
    bad = _thread(ids=(101, 999, 998), facts=[("ф", (101,)),
                                              ("ф2", (999, 998))])
    repaired2, report2 = repair_l1(_data([bad]), _space(101))
    assert report2.facts_after == 1                    # факты целы
    assert report2.useless
    assert report2.useless_reason == USELESS_MASS_UNKNOWN_IDS


def test_boundary_exactly_half_is_not_useless():
    """Граница «>0.5» строгая: ровно половина удалённых — продолжаем
    (§6:2188–2189 «половина evidence уцелела — структура наполовину полезна»)."""
    th = _thread(ids=(101, 999), facts=[("ф", (101,))])
    repaired, report = repair_l1(_data([th]), _space(101))
    assert report.unknown_ids_removed == 1
    assert not report.useless


# ── Чистота/детерминизм/тип-отчёт ──────────────────────────────────────────

def test_input_not_mutated():
    th = _thread(ids=(101, 999), facts=[("факт", (101, 999))])
    data = _data([th], unassigned=(998,))
    before = copy.deepcopy(data)
    repair_l1(data, _space(101))
    assert data == before


def test_double_run_byte_identical():
    t1 = _thread(ids=(101, 999), facts=[("факт", (102,))])
    t2 = _thread("thread_002", ids=(998,))
    data = _data([t1, t2], unassigned=(102, 997))
    space = _space(101, 102)
    a, ra = repair_l1(copy.deepcopy(data), space)
    b, rb = repair_l1(copy.deepcopy(data), space)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert ra == rb


def test_report_fields_are_int_bool_only():
    repaired, report = repair_l1(_data([]), _space())
    d = report.as_log_fields()
    assert all(isinstance(v, (int, bool)) and not isinstance(v, float)
               for k, v in d.items() if k != "useless_reason")
    assert isinstance(d["useless_reason"], str)
    assert report.useless and report.useless_reason == USELESS_NO_TOPICS


def test_structural_garbage_left_for_validator():
    """Repair не решает вопросы типов — не-dict треды остаются как есть
    (их отбракует строгий валидатор v2)."""
    data = {"schema_version": 2, "threads": [None],
            "unassigned_message_ids": []}
    repaired, report = repair_l1(data, _space(101))
    assert repaired["threads"] == [None]
