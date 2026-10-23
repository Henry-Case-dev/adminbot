# -*- coding: utf-8 -*-
"""ASAP 2 — durable-телеметрия уточнений (наблюдаемость R17-safe).

Первопричина: `needs_clarification`/`clarification_target` жили только в
памяти процесса (`plan`), а durable `plan_meta` на usage-строках
`step="l1_planner"` их не содержал → на проде нельзя измерить частоту
уточнений и долю generic-веток (true без предмета).

Добавлены ТОЛЬКО два boolean-флага: `needs_clar` (строгий `is True`, как в
`normalize_l1_plan`) и `clar_target_present` (непустая цель). Ни текста цели,
ни пользовательского текста в durable-колонку не попадает (§3.2/R17).

TEST-LIFECYCLE: CONTRACT owner=ASAP2-TELEMETRY
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services import usage_events as ue  # noqa: E402

CLAR_KEYS = {"needs_clar", "clar_target_present"}


def _plan_meta(plan, meta=None, **kw):
    """Прогон реальной проводки (`_l1_usage_plan_meta`) + R17-фильтр."""
    from services.direct_chat_service import _l1_usage_plan_meta
    safe = ue.sanitize_plan_meta(_l1_usage_plan_meta(
        plan, dict(meta or {"source": "main", "inherited": True}),
        fallback_flag=kw.pop("fallback_flag", ""),
        latency_ms=kw.pop("latency_ms", 10),
        input_chars=kw.pop("input_chars", 5)))
    assert safe is not None
    return safe


# ── 1. План без уточнения → оба флага false ────────────────────────────────

def test_false_plan_marks_no_clarification():
    from services.direct_l1 import L1Plan

    safe = _plan_meta(L1Plan(response_act="answer"))
    assert safe["needs_clar"] is False
    assert safe["clar_target_present"] is False


# ── 2. true + непустая цель → валидное уточнение ───────────────────────────

def test_true_with_target_marks_valid_clarification():
    from services.direct_l1 import normalize_l1_plan

    plan = normalize_l1_plan({"action": "reply", "needs_clarification": True,
                              "clarification_target": "media_target"})
    assert plan is not None and plan.needs_clarification is True
    safe = _plan_meta(plan)
    assert safe["needs_clar"] is True
    assert safe["clar_target_present"] is True
    # R17: сам текст цели в durable-колонку не попадает.
    assert "media_target" not in json.dumps(safe, ensure_ascii=False)


# ── 3. true + пустая цель → generic-ветка (видна отдельно) ─────────────────

@pytest.mark.parametrize("target", [None, "", "   "])
def test_true_empty_target_marks_generic_branch(target):
    from services.direct_l1 import L1Plan

    plan = L1Plan()
    plan.needs_clarification = True
    plan.clarification_target = target
    safe = _plan_meta(plan)
    assert safe["needs_clar"] is True
    assert safe["clar_target_present"] is False


# ── 4. Некорректная структура не ломает запись ─────────────────────────────

def test_malformed_plan_does_not_break_write():
    from services.direct_l1 import L1Plan

    # a) None-план (deterministic fallback) — оба флага false, ось fallback жива.
    safe = _plan_meta(None, fallback_flag="deterministic")
    assert safe["needs_clar"] is False
    assert safe["clar_target_present"] is False
    assert safe["fallback"] == "deterministic"

    # b) мусорный тип цели — не цель (строгая семантика normalize_l1_plan).
    garbage = L1Plan(response_act="clarification")
    garbage.needs_clarification = True
    garbage.clarification_target = {"nested": "мусор"}     # не str
    safe2 = _plan_meta(garbage)
    assert safe2["needs_clar"] is True
    assert safe2["clar_target_present"] is False

    # c) «враждебный» план: доступ к цели бросает — флаг просто false,
    # остальные оси целы (единственный новый код не становится хрупким).
    class _Boom:
        action = "reply"
        response_act = "other"
        tone = "inherit"
        confidence_bucket = "low"
        capabilities_needed = ()
        confidence = 0.0
        execution_mode = "none"

        def effective_extent(self):
            return "auto"

        @property
        def clarification_target(self):
            raise RuntimeError("boom")

    safe3 = _plan_meta(_Boom())
    assert safe3["clar_target_present"] is False
    assert safe3["action"] == "reply"


@pytest.mark.asyncio
async def test_attach_is_fail_open_on_junk_plan():
    """Некорректная структура плана НЕ ломает ход: писатель телеметрии
    fail-open, ошибка не пробрасывается."""
    from types import SimpleNamespace

    from services.direct_chat_service import DirectChatService

    fake_self = SimpleNamespace(llm=SimpleNamespace(_pg=lambda: None))
    await DirectChatService._attach_l1_plan_meta(
        fake_self, "corr-junk", object(), {}, chat_id=1,
        fallback_flag="", latency_ms=0, input_chars=0)


# ── 5. Whitelist-инвариант: флаги пропускаются, свободный текст — нет ──────

def test_whitelist_accepts_flags_and_drops_free_text():
    assert CLAR_KEYS <= set(ue.PLAN_META_FIELDS)
    safe = ue.sanitize_plan_meta({
        "needs_clar": True, "clar_target_present": False,
        "clarification_target": "свободный текст цели",
    })
    assert safe == {"needs_clar": True, "clar_target_present": False}


# ── 6. Проводка end-to-end: флаги доезжают до UPDATE plan_meta ─────────────

@pytest.mark.asyncio
async def test_l1_usage_row_carries_clar_flags(monkeypatch):
    """Реальный `handle` (fake LLM/PG): UPDATE plan_meta несёт пару
    (true,true) для валидного уточнения — durable-статистика возможна."""
    from tests.test_asap7_direct_l1 import _drive, _plan_json
    from tests.test_asap7_direct_settings import _MetaLLM

    llm = _MetaLLM(l1=_plan_json(response_act="clarification",
                                 needs_clarification=True,
                                 clarification_target="media_target"),
                   l2="какой именно медиафайл нужен?")
    svc, react, bot, msg, user = _drive(monkeypatch, "сделай как в том",
                                        llm=llm)
    await svc.handle(bot, msg, user)

    updates = [(sql, args) for sql, args in llm.conn.executed
               if "UPDATE llm_usage_events" in sql]
    assert len(updates) == 1, llm.conn.executed
    meta = json.loads(updates[0][1][0])
    assert meta["needs_clar"] is True
    assert meta["clar_target_present"] is True
    assert set(meta) <= set(ue.PLAN_META_FIELDS)
    assert "media_target" not in updates[0][1][0]
