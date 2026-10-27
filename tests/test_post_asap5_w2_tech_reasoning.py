# -*- coding: utf-8 -*-
"""POST-ASAP5 CORRECTIVE W2 — техническое рассуждение, поиск, галлюцинации.

Источник: plans/features/post-asap5-corrective/source-2026-10-27.md
(§4=строки 162-232, §5=234-303, §6=306-368; §10 сценарии=549-651).

Контрактные проверки (CONTRACT/REGRESSION), payload-level, 0 LLM:
* §4.1: Writer-канон различает математическую оценку / теоретическую
  архитектуру / физическую реализацию / совместимость с устройством;
  запрос математической оценки выполняется, физические ограничения не
  отменяют расчёт;
* §4.2: размерности и параметры (скорость линии, ширина интерфейса,
  каналы vs корпуса, объёмы, частоты); контрольный пример источника
  (32x9600/8=38400, 448/38.4, 11.67, 12) ОТСУТСТВУЕТ в рабочих
  канонах/промптах (запрет хардкода §4.2);
* §4.3: несовместимость конкретной реализации != невозможность принципа;
  категорические выводы только в пределах установленных условий;
* §5: правило 4 канона L1 — семантика своевременного поиска (категории
  §5.2 без списков слов); формулы/расчёты/болтовня — без поиска; поиск
  недоступен — не выдавать неподтверждённое за факт; tool-phase секция
  «ПОИСК И НЕПОДТВЕРЖДЁННЫЕ ХАРАКТЕРИСТИКИ» — та же семантика для
  execute_web_search; capability-гейт резолвит web_search в анонс тула;
* §6.1: различение известное/результат поиска/расчёт/предположение/
  догадка; незнакомый продукт != выдуманная архитектура; пробелы не
  заполняются жаргоном;
* §6.2: гипотезы НЕ запрещены — допустимы при пометке; нет требования
  документа для арифметики; «достоверность, а не нерешительность»;
* §10.5: механика честного отказа (rejected_note) не регрессировала;
* W1-контракт: WRITER_FOCUS_DIRECTIVE ровно один раз на payload (все
  режимы), секция «ИЗМЕНЕНИЕ ЗАДАЧИ И ВОЗРАЖЕНИЯ» байт-в-байт;
* лестница ADR-1013-3: слепки PA5W2 (L1 ред.5 = 902dd00edf52), W2
  tool phase (f30c6d73da82), W2 writer (83ff62bbee40); ступени + откат +
  метки + fingerprint.

TEST-LIFECYCLE: CONTRACT owner=post-asap5-corrective/W2
"""
from __future__ import annotations

import hashlib
import re

import pytest

from services import chat_prompts as cp
from services import direct_capabilities as caps
from services import direct_l1 as l1
from services import prompt_migrations as pm
from services import prompt_registry as pr
from services import prompt_style_blocks as psb
from services import response_extent as extent
from services.tool_schemas import active_tools

ROOT = pathlib_path = __import__("pathlib").Path(__file__).resolve().parent.parent

L1_KEY = "prompts.direct_l1_planner_system_prompt"
L2_KEY = "prompts.direct_chat_verbalizer_system_prompt"
TOOL_KEY = "prompts.direct_chat_system_prompt"

#: Слова-инциденты: не появляются ни в одном новом тексте W2 (§3.1/§11).
_INCIDENT_WORDS = ("шина", "чип", "забей", "LPDDR", "Crescent", "GDDR",
                   "5060", "фотонн", "интерконнект")

#: Контрольный пример §4.2 источника: ТОЛЬКО тест, не рантайм (запрет
#: хардкода числа в рабочем коде и промптах).
_CONTROL_EXAMPLE_TOKENS = ("38 400", "38400", "448/38.4", "11.67")


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _plan(**kwargs) -> l1.L1Plan:
    base = dict(action="reply", response_act="answer", extent="compact",
                structure="chat", delivery_hint="plain")
    base.update(kwargs)
    return l1.L1Plan(**base)


def _payload(plan, *, modes_on: bool = True) -> str:
    """Сборка payload Writer: system + plan-блок + closing (как в W1)."""
    block = l1.build_l2_plan_block(
        plan, include_analysis=l1.analysis_directive_needed(plan,
                                                            modes_on=modes_on),
        include_delta=l1.delta_instruction_needed(plan), modes_on=modes_on)
    system = psb.compose_verbalizer_system(
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT, l1.plan_response_mode(plan),
        "plain", html_safe=True,
        extent_block=extent.render_extent_block(plan.to_response_plan()))
    return system + "\n\n" + block + "\n\n" + psb.NO_META_CLOSING_TEXT.strip()


def _flat(text: str) -> str:
    """Канон/правила в одну строку (якоря смысла, не переносов)."""
    return " ".join(text.split())


# ═══ §4/§6. Writer-канон: секция технических расчётов и гипотез ═════════════

def test_writer_tech_section_present_once_inside_kak_pisat():
    canon = cp.DIRECT_VERBALIZER_SYSTEM_PROMPT
    section = cp._VERBALIZER_TECH_REASONING_PA5W2
    assert canon.count(section) == 1
    assert "ТЕХНИЧЕСКИЕ РАСЧЁТЫ И ГИПОТЕЗЫ" in section
    # в разделе КАК ПИСАТЬ-потока: после уточнений/границы, до ВЫХОД
    assert canon.index("КАК ПИСАТЬ") < canon.index(section) < \
        canon.index("ВЫХОД")


def test_writer_41_separates_theory_from_implementation():
    section = cp._VERBALIZER_TECH_REASONING_PA5W2
    for anchor in ("математическую оценку",
                   "теоретически возможную архитектуру",
                   "физически существующую реализацию",
                   "совместимость с конкретным устройством"):
        assert anchor in section, anchor
    # запрос математической оценки выполняется; ограничения не отменяют расчёт
    assert "несовместимость конкретной реализации" in section
    assert "не невозможность принципа при иной архитектуре" in section


def test_writer_42_dimensions_and_parameters():
    section = cp._VERBALIZER_TECH_REASONING_PA5W2
    for anchor in ("сверяй размерности и параметры",
                   "скорость линии",
                   "ширина интерфейса",
                   "число независимых каналов",
                   "число корпусов памяти",
                   "объёмы",
                   "частоты"):
        assert anchor in section, anchor
    # пакеты не отождествляются с интерфейсами; организация называется явно
    assert "число корпусов не равно числу независимых интерфейсов" in section
    assert "принятая организация интерфейса называется явно" in section
    # совокупная пропускная способность = ширина x скорость (семантика)
    assert "складывается из ширины интерфейса и скорости передачи" in section


def test_writer_42_control_example_not_hardcoded_anywhere():
    """Контрольный пример источника - тестовый сценарий, не рантайм:
    чисел примера нет ни в одном рабочем каноне/промпте/plan-блоке."""
    carriers = (cp.DIRECT_VERBALIZER_SYSTEM_PROMPT,
                cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT,
                cp.CHAT_SYSTEM_PROMPT,
                psb.DELTA_READY_INSTRUCTION_TEXT,
                psb.ANALYSIS_DIRECTIVE_TEXT,
                psb.ANALYSIS_WRITER_TEXT,
                cp._VERBALIZER_TECH_REASONING_PA5W2,
                cp._DIRECT_SEARCH_DECISION_PA5W2)
    for carrier in carriers:
        for token in _CONTROL_EXAMPLE_TOKENS:
            assert token not in carrier, (token, carrier[:60])
    src = (ROOT / "services" / "chat_prompts.py").read_text(encoding="utf-8")
    for token in _CONTROL_EXAMPLE_TOKENS:
        assert token not in src, token


def test_writer_43_impossibility_scoped_to_conditions():
    section = cp._VERBALIZER_TECH_REASONING_PA5W2
    assert "категорический вывод допустим только в пределах установленных " \
        "условий" in section


def test_writer_61_assumptions_labeled_and_no_invented_products():
    section = cp._VERBALIZER_TECH_REASONING_PA5W2
    # различение источников достоверности
    assert "Отделяй известные данные, результаты поиска и проверенные " \
        "расчёты от предположений" in section
    # незнакомый продукт != выдуманная архитектура; без заполнения жаргоном
    assert "незнакомый продукт не превращай в выдуманную архитектуру" in section
    assert "не заполняй пробелы техническим жаргоном" in section
    # выдавать предположение предположением (переиспользует ТОЧНОСТЬ)
    assert "выдавай их предположением, а не установленным фактом" in section
    # честное неизвестное
    assert "честнее назвать, какой именно факт неизвестен" in section


def test_writer_62_hypotheses_allowed_and_no_document_required():
    section = cp._VERBALIZER_TECH_REASONING_PA5W2
    # §6.2: способность рассуждать/оценивать/спорить СОХРАНЕНА явно
    assert "гипотеза, оценка и инженерное рассуждение допустимы" in section
    # известные формулы/расчёты без подтверждений (§6.2, запрет документа)
    assert "Известные формулы и расчёты на заданных числах подтверждений " \
        "не требуют" in section
    # без превращения каждого ответа в оговорки (§6.1)
    assert "каждый ответ не обязан быть цепочкой оговорок" in section
    assert "нужна достоверность, а не нерешительность" in section


def test_writer_tech_section_no_incident_words_no_quotes_no_quotas():
    section = cp._VERBALIZER_TECH_REASONING_PA5W2
    for word in _INCIDENT_WORDS:
        assert not re.search(rf"\b{re.escape(word.lower())}",
                             section.lower()), word
    assert "«" not in section and "»" not in section
    assert "—" not in section
    for banned in ("символов", "токен", "знаков", "обязательная структура",
                   "шаблон ответа"):
        assert banned not in section.lower()


def test_writer_prev_snapshot_and_step():
    prev = cp.PREV_CHAT_VERBALIZER_PA5W2
    # слепок = активные байты до W2 (= R3b-канон: §3.1 + §4.2 + граница)
    assert prev != cp.DIRECT_VERBALIZER_SYSTEM_PROMPT
    assert _sha12(prev) == "83ff62bbee40"
    assert "ТЕХНИЧЕСКИЕ РАСЧЁТЫ И ГИПОТЕЗЫ" not in prev
    steps = dict(pm.PROMPT_MIGRATIONS[L2_KEY])
    assert steps[prev] == cp.DIRECT_VERBALIZER_SYSTEM_PROMPT
    assert pm.ROLLBACK_MIGRATIONS[L2_KEY][0] == (
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT, prev)
    assert pm.ROLLBACK_MIGRATIONS[L2_KEY][1] == (
        prev, cp.PREV_CHAT_VERBALIZER_CLAR)
    assert pr.is_known_canon(prev)


# ═══ §5. L1 правило 4: семантика своевременного поиска ══════════════════════

def test_l1_rule4_search_decision_semantics():
    rules_flat = _flat(cp._DIRECT_L1_PLANNER_RULES_PA5W2)
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert canon.count(cp._DIRECT_L1_PLANNER_RULES_PA5W2) == 1
    # категории §5.2 — семантические, без слов инцидента
    for anchor in ("Запрашивай поиск (web_search)",
                   "существенно зависит от внешних сведений",
                   "характеристики современных устройств",
                   "аппаратные архитектуры",
                   "сравнение продуктов",
                   "спецификации производителей",
                   "изменяющиеся стандарты",
                   "точные числа, даты или характеристики",
                   "проверяемыми сведениями собеседника"):
        assert anchor in rules_flat, anchor
    # §5.2 вторая сторона: без обязательного поиска на каждый вопрос
    assert "Общеизвестные формулы, расчёты с заданными параметрами" \
        in rules_flat
    assert "обычная болтовня в поиске не нуждаются" in rules_flat
    # §10.5: поиск недоступен — honest unknown, не уверенная спекуляция
    assert "Если поиска нет в списке" in rules_flat
    assert "не выдавай неподтверждённую характеристику за факт" in rules_flat
    assert "какой факт неизвестен" in rules_flat


def test_l1_rule4_no_incident_words_no_quota():
    rules = cp._DIRECT_L1_PLANNER_RULES_PA5W2
    for word in _INCIDENT_WORDS:
        assert not re.search(rf"\b{re.escape(word.lower())}",
                             rules.lower()), word
    # прежние правила 5-9 байт-в-байт (W2 дельта — только правило 4)
    assert rules.split("5. needs_clarification")[1] == \
        cp._DIRECT_L1_PLANNER_RULES.split("5. needs_clarification")[1]


def test_l1_w1_section_bytes_unchanged_and_snapshot_pins():
    """W1-контракт: секция intent-update байт-в-байт; слепки ред.4/ред.5
    целы; активный канон = ред.5 + новое правило 4."""
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    prev5 = cp.PREV_DIRECT_L1_PLANNER_PA5W2
    assert canon.count(cp._DIRECT_L1_INTENT_UPDATE_PA5) == 1
    head, _tail = prev5.rsplit(cp._DIRECT_L1_PLANNER_RULES, 1)
    assert canon == head + cp._DIRECT_L1_PLANNER_RULES_PA5W2
    assert len(cp.PREV_DIRECT_L1_PLANNER_PA5W1) == 9750
    assert _sha12(cp.PREV_DIRECT_L1_PLANNER_PA5W1) == "422e9d73d316"
    assert _sha12(prev5) == "902dd00edf52"
    assert _sha12(canon) == "14743d288ea3"
    steps = dict(pm.PROMPT_MIGRATIONS[L1_KEY])
    assert steps[prev5] == canon
    rollback = pm.ROLLBACK_MIGRATIONS[L1_KEY]
    assert rollback[0] == (canon, prev5)
    assert rollback[1] == (prev5, cp.PREV_DIRECT_L1_PLANNER_PA5W1)
    assert pr.is_known_canon(prev5)


def test_l1_prev_rules_frozen_untouched():
    """Прежние редакции правил (включая активные до W2) заморожены —
    лестница и откаты узнают прод-байты."""
    assert _sha12(cp.PREV_DIRECT_L1_PLANNER_PA5W1) == "422e9d73d316"
    assert "Запрашивай поиск" not in cp._DIRECT_L1_PLANNER_RULES
    assert "Запрашивай поиск" not in cp.PREV_DIRECT_L1_PLANNER_PA5W2


# ═══ §5. Гейт: интент/фолбэк/резолв capability → анонс тула ═════════════════

def test_capability_gate_announces_search_when_l1_chooses_it():
    """Deterministic часть поискового решения: план с web_search резолвится
    в анонс execute_web_search (§5.3 - существующий гейт, без нового
    роутера). Поведение самой LLM - живой прогон §10 (волна 3)."""
    announced = {t["function"]["name"] for t in active_tools(False, False)}
    assert "execute_web_search" in announced
    resolved, rejected = caps.resolve_capabilities(
        ("web_search",), announced)
    assert resolved == ["execute_web_search"]
    assert rejected == []
    # plan → execution mode: простой тул-проход без новых вызовов
    assert l1.derive_execution_mode(("web_search",)) == "simple_tools"
    assert l1.derive_execution_mode(()) == "none"


def test_device_spec_question_has_no_forced_intent_by_design():
    """Технический вопрос без командных маркеров не создаёт принудительный
    интент - решение за семантикой L1 (правило 4), а не за regex-дверью;
    наблюдаемая причина отсутствия поручения фиксируется."""
    intent = caps.detect_action_intent(
        "что за устройство Intel Crescent Island и какая у него пропускная "
        "способность?")
    assert intent.intent == caps.INTENT_NONE
    assert intent.reason == caps.REASON_NONE


def test_honest_unavailable_note_intact():
    """§10.5: честная пометка недоступного инструмента не регрессировала
    (reused existing mechanics, не дублируется)."""
    note = caps.rejected_note((("web_search", caps.REASON_NOT_READY),))
    assert "не выдумывай результат" in note
    assert "честно скажи" in note


# ═══ §5. Tool-phase: секция решения о поиске ════════════════════════════════

def test_toolphase_search_section_once_and_semantics():
    canon = cp.CHAT_SYSTEM_PROMPT
    section = cp._DIRECT_SEARCH_DECISION_PA5W2
    assert canon.count(section) == 1
    assert canon.endswith(section)
    for anchor in ("характеристики современных устройств",
                   "новые аппаратные архитектуры",
                   "спецификации производителей",
                   "сравнения продуктов",
                   "изменяющиеся стандарты",
                   "точные числа",
                   "execute_web_search",
                   "Общеизвестные формулы",
                   "обычная болтовня в поиске не нуждаются",
                   "не выдавай догадку за результат поиска",
                   "честную границу знания"):
        assert anchor in section, anchor


def test_toolphase_prev_snapshot_and_existing_contracts_intact():
    canon = cp.CHAT_SYSTEM_PROMPT
    prev = cp.PREV_CHAT_W2_SYSTEM_PROMPT
    assert canon == prev + "\n\n" + cp._DIRECT_SEARCH_DECISION_PA5W2
    assert _sha12(prev) == "f30c6d73da82"
    assert "ПОИСК И НЕПОДТВЕРЖДЁННЫЕ ХАРАКТЕРИСТИКИ" not in prev
    # существующие контракты tool phase не регрессировали
    for block in ("НАЗНАЧЕНИЕ КАНАЛА DIRECT", "ДОСТОВЕРНОСТЬ",
                  "ИНСТРУМЕНТЫ:", "АНТИ-ГАЛЛЮЦИНАЦИИ:",
                  "СЛУЖЕБНЫЕ ПОМЕТКИ (НЕ ДЛЯ ОТВЕТА):",
                  "ЕСЛИ ПОЙМАЛИ НА НЕСТЫКОВКЕ:"):
        assert block in canon, block
    # честный слив §10.5 (существующий носитель) на месте
    assert "Признай косяк в саркастичной манере" in canon
    steps = dict(pm.PROMPT_MIGRATIONS[TOOL_KEY])
    assert steps[prev] == canon
    assert pm.ROLLBACK_MIGRATIONS[TOOL_KEY][0] == (canon, prev)
    assert pm.ROLLBACK_MIGRATIONS[TOOL_KEY][1] == (
        prev, cp.PREV_CHAT_W1_SYSTEM_PROMPT)
    assert pr.is_known_canon(prev)


def test_toolphase_section_no_incident_words_no_quotes():
    section = cp._DIRECT_SEARCH_DECISION_PA5W2
    for word in _INCIDENT_WORDS:
        assert not re.search(rf"\b{re.escape(word.lower())}",
                             section.lower()), word
    assert "«" not in section and "»" not in section
    assert "—" not in section


# ═══ Payload-уровень: секции едут в payload Writer без дублей ═══════════════

@pytest.mark.parametrize("plan_kwargs", [
    dict(response_act="answer", extent="compact", structure="chat"),
    dict(response_act="research", extent="normal", structure="answer"),
    dict(response_act="research", extent="auto", structure="report",
         delivery_hint="rich"),
])
def test_writer_canon_carries_tech_semantics_without_focus_dup(plan_kwargs):
    """Writer-канон с секцией §4/§6 доезжает до payload; директива фокуса
    W1 по-прежнему ровно один раз; новые тексты не дублируют её."""
    plan = _plan(**plan_kwargs)
    payload = _payload(plan)
    assert cp._VERBALIZER_TECH_REASONING_PA5W2 in payload
    assert payload.count(psb.WRITER_FOCUS_DIRECTIVE_TEXT) == 1
    # секция не содержит директиву фокуса (нет дубля-носителя)
    focus = psb.WRITER_FOCUS_DIRECTIVE_TEXT
    assert focus not in cp._VERBALIZER_TECH_REASONING_PA5W2
    assert focus not in cp._DIRECT_SEARCH_DECISION_PA5W2
    assert focus not in cp._DIRECT_L1_PLANNER_RULES_PA5W2


# ═══ §11-гварды карты: без новых слоёв/роутеров/классификаторов ═════════════

def test_no_new_layers_routers_or_classifiers():
    """§5.3/§11: правки только в существующих канонах (строки/секции);
    нет нового классификатора, роутера или обязательных LLM-вызовов."""
    src_chats = (ROOT / "services" / "chat_prompts.py").read_text(
        encoding="utf-8")
    for name in ("_DIRECT_SEARCH_DECISION_PA5W2",
                 "_VERBALIZER_TECH_REASONING_PA5W2",
                 "_DIRECT_L1_PLANNER_RULES_PA5W2"):
        assert name in src_chats
    # гейты не расширялись словными списками устройств/продуктов
    src_caps = (ROOT / "services" / "direct_capabilities.py").read_text(
        encoding="utf-8")
    for word in ("LPDDR", "Crescent", "фотонн"):
        assert word not in src_caps, word


# ═══ Лестница/реестр: метки и fingerprint ═══════════════════════════════════

def test_labels_and_fingerprint_after_bump():
    assert "l1-planner-tech-reasoning" in pr.factory_revision(
        "direct.base.l1_planner")
    assert "toolphase-search-decision" in pr.factory_revision(
        "direct.base.tool_phase")
    assert "l2-writer-tech-reasoning" in pr.factory_revision(
        "direct.base.l2_writer")
    assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12
