"""P0-CORRECTIVE §1.1: маршрут L1 по материалу просьбы + один payload.

Доказывает по `source-owner-p0-corrective-2026-10-25.md` §1.1 и
`evidence/p0-hotfix/l1-harness-audit.md` §3/§5/§8:

* активный канон L1 различает «разобраться в уже сказанном» (→
  ``response_act=research``, внутренний разбор может быть глубоким) и
  «только мнение/оценка» (→ ``structure=answer`` без эссе); глубина разбора
  не задаёт длину ответа; JSON-дисциплина — правило 9; литеральных фраз
  запроса в каноне нет;
* ``PREV_DIRECT_L1_PLANNER_P0CS`` — ровно прежние активные байты, цель
  отката, R3b не изменён (ADR-1013-3);
* ``response_act=research`` достаточен для точных analysis/Writer-текстов:
  ровно 1×1 в полном payload и 0×0 для обычного короткого ответа; режим
  ``serious`` (не ``deep_research``), дубля нет.

TEST-LIFECYCLE: CONTRACT owner=P0-CORRECTIVE/L1-ROUTING-REPAIR
"""
from __future__ import annotations

import hashlib

from services import chat_prompts as cp
from services import direct_l1 as l1
from services import prompt_migrations as pm
from services import prompt_style_blocks as psb
from services import response_extent as _extent


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _plan(**kwargs) -> l1.L1Plan:
    base = dict(action="reply", response_act="research", extent="normal",
                structure="answer", delivery_hint="plain")
    base.update(kwargs)
    return l1.L1Plan(**base)


def _payload(plan: l1.L1Plan) -> tuple[str, str, str]:
    """Сборка payload тем же набором решений, что и сервис: mode, extent и
    plan-блок строятся из ОДНОГО плана реального L1 (аудит §7 п.2)."""
    response_mode = l1.plan_response_mode(plan)
    response_plan = plan.to_response_plan()
    extent_block = _extent.render_extent_block(response_plan)
    needed = l1.analysis_directive_needed(plan)
    plan_block = l1.build_l2_plan_block(plan, include_analysis=needed)
    system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", response_mode, "plain",
        html_safe=True, extent_block=extent_block)
    return system, plan_block, system + "\n\n" + plan_block


# ── 1. Семантика канона ─────────────────────────────────────────────────────

def test_l1_canon_separates_material_from_opinion():
    rules = cp._DIRECT_L1_PLANNER_RULES
    assert cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT.count(rules) == 1

    # ветка «разобраться в уже сказанном» → research
    assert "разобраться в уже сказанном" in rules
    assert "response_act=research" in rules
    assert "внутренний разбор может быть глубоким" in rules
    # смешанная просьба: разбор материала приоритетнее финальной оценки
    assert "приоритет у\n   разбора" in rules
    assert "оценка - его вывод, а не замена" in rules
    # ветка «только мнение/оценка» → answer без эссе
    assert "только мнение" in rules
    assert "structure=answer" in rules
    assert "без хроники, биографии и отчёта" in rules
    # глубина не задаёт длину; detailed/report — только по явной просьбе
    assert "Глубина разбора не задаёт длину ответа" in rules
    assert "Обычная просьба - compact или" in rules
    assert "явная просьба подробного разбора - detailed" in rules
    assert "полного отчёта -" in rules
    # при нехватке материала — существующие возможности, не догадка
    assert "истории или памяти из списка выше" in rules
    assert "не выдавай догадку за подтверждённое" in rules
    # JSON — правило 9, дисциплина не отменена
    assert "9. В ответе - ровно одна JSON-строка" in rules
    assert rules.index("7. Смотри, что человек просит") < \
        rules.index("8. Глубина разбора") < rules.index("9. В ответе")

    # запрет §1.1: никаких литеральных фраз запроса как триггеров
    low = rules.casefold()
    for phrase in ("проанализируй мои сообщения", "мои сообщения",
                   "я злобный", "злобный", "в чате"):
        assert phrase not in low, phrase

    # правила 1-6 — байт-в-байт из замороженного R3b
    assert cp._DIRECT_L1_PLANNER_RULES_R3B.split(
        "6. confidence")[0] == rules.split("6. confidence")[0]
    # текст владельца (контракт §4.1) не менялся
    assert cp._DIRECT_L1_CLARIFICATION_CONTRACT in \
        cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT


def test_analysis_texts_do_not_impose_length():
    """Глубина не задаёт длину: в точных текстах нет приказов объёма."""
    for text in (psb.ANALYSIS_DIRECTIVE_TEXT, psb.ANALYSIS_WRITER_TEXT):
        low = text.casefold()
        for banned in ("полностью", "полный отчёт", "полный отчет",
                       "не сжимай", "ничего не выбрасывай",
                       "обязательно", "минимум", "максимум",
                       "не менее", "не более"):
            assert banned not in low, (banned, text[:60])
    # «соразмерно запросу» — прямая формулировка §1.1
    assert "соразмерно запросу" in psb.ANALYSIS_DIRECTIVE_TEXT


# ── 2. Слепок/лестница (ADR-1013-3) ────────────────────────────────────────

def test_l1_prev_snapshot_is_previous_rule_bytes():
    prev = cp.PREV_DIRECT_L1_PLANNER_P0CS
    assert prev == (cp._DIRECT_L1_PLANNER_BASE_R3
                    + cp._DIRECT_L1_CLARIFICATION_CONTRACT
                    + cp._DIRECT_L1_CONTINUATION_R3B
                    + cp._DIRECT_L1_PLANNER_RULES_P0CS)
    # ровно прежние активные байты (пин из прежнего теста миграции)
    assert len(prev) == 8574 and _sha12(prev) == "8ef75b632d12"
    assert prev != cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    # прежнее правило 7 (объектная оценка) осталось только в слепке
    assert "7. Просьба оценить человека" in cp._DIRECT_L1_PLANNER_RULES_P0CS
    assert "7. Просьба оценить человека" not in cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    # R3b не тронут
    assert cp.PREV_DIRECT_L1_PLANNER_R3B == (
        cp._DIRECT_L1_PLANNER_BASE_R3 + cp._DIRECT_L1_CLARIFICATION_CONTRACT
        + cp._DIRECT_L1_CONTINUATION_R3B + cp._DIRECT_L1_PLANNER_RULES_R3B)
    assert _sha12(cp.PREV_DIRECT_L1_PLANNER_R3B) == "6c2ddc17c998"


def test_l1_prev_p0cs2_is_previous_active_bytes():
    """Лестница ред.2: P0CS2 — ровно активные байты редакции 1
    (``f6f5d3b1fc1d``), R3b/P0CS не изменены."""
    prev2 = cp.PREV_DIRECT_L1_PLANNER_P0CS2
    assert prev2 == (cp._DIRECT_L1_PLANNER_BASE_R3
                     + cp._DIRECT_L1_CLARIFICATION_CONTRACT
                     + cp._DIRECT_L1_CONTINUATION_R3B
                     + cp._DIRECT_L1_PLANNER_RULES_P0CS2)
    assert len(prev2) == 9145 and _sha12(prev2) == "f6f5d3b1fc1d"
    assert prev2 != cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert _sha12(cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT) == "23aae0c9499d"
    # усиление не отменило прежние ветки
    assert "response_act=research" in prev2
    # ступень вперёд и цель отката указывают на новый слепок
    steps = dict(pm.PROMPT_MIGRATIONS[
        "prompts.direct_l1_planner_system_prompt"])
    assert steps[prev2] == cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert steps[cp.PREV_DIRECT_L1_PLANNER_P0CS] == \
        cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert steps[cp.PREV_DIRECT_L1_PLANNER_R3B] == \
        cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert pm.ROLLBACK_MIGRATIONS[
        "prompts.direct_l1_planner_system_prompt"][0] == (
            cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT, prev2)
    assert pm.ROLLBACK_MIGRATIONS[
        "prompts.direct_l1_planner_system_prompt"][1] == (
            prev2, cp.PREV_DIRECT_L1_PLANNER_P0CS)


# ── 3. Payload: research 1×1, answer 0×0, без дублей ────────────────────────

def test_research_compact_payload_has_exact_texts_once():
    plan = _plan(extent="compact", structure="answer")
    assert l1.analysis_directive_needed(plan) is True
    system, block, payload = _payload(plan)
    assert block.strip()                      # plan-блок несёт тексты
    assert payload.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 1
    assert payload.count(psb.ANALYSIS_WRITER_TEXT) == 1
    assert system.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 0


def test_answer_short_reply_has_no_analysis_texts():
    plan = _plan(response_act="answer", extent="compact", structure="chat")
    assert l1.analysis_directive_needed(plan) is False
    system, block, payload = _payload(plan)
    assert payload.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 0
    assert payload.count(psb.ANALYSIS_WRITER_TEXT) == 0
    assert psb.ANALYSIS_DIRECTIVE_TEXT not in block


def test_research_auto_keeps_single_mode_source():
    """research без extent-блока: режим serious даёт нейтральный mode-блок,
    точные тексты несёт ТОЛЬКО plan-блок (ровно 1×1, без дубля)."""
    plan = _plan(extent="auto", structure="answer")
    assert l1.plan_response_mode(plan) == "serious"
    assert l1.analysis_directive_needed(plan) is True
    system, block, payload = _payload(plan)
    assert psb.ANALYSIS_DIRECTIVE_TEXT in block
    assert system.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 0
    assert payload.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 1
    assert payload.count(psb.ANALYSIS_WRITER_TEXT) == 1


def test_research_mode_is_serious_not_deep_research():
    """Не deep_research: PG-кастом режима может вернуть старый приказ
    «выведи отчёт полностью» (дефект эссе), а exact-тексты уже даёт план."""
    for extent in ("compact", "normal", "auto", "detailed"):
        plan = _plan(extent=extent)
        assert l1.plan_response_mode(plan) == "serious", extent
    # report по-прежнему deep_research (явная форма отчёта — не этот дефект)
    assert l1.plan_response_mode(
        _plan(extent="detailed", structure="report")) == "deep_research"
