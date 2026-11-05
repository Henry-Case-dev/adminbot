"""BGS-01 (§0.1) — обязательной деперсонализации запроса фактчека нет.

Прежняя политика: `factcheck_planner._strip_privacy` вырезала имена
участников чата из клейма ДО построения поискового запроса
(«Маша уволилась из Сбера» → «уволилась из Сбера»), а клейм из одного имени
превращался в пустую строку. Владелец (BGS-01, §0.1) снял это вето:
упоминание человека не запрещает проверку факта и не обедняет запрос.

Что СОХРАНЕНО (проверяется здесь же):
* смысловое ядро клейма: числа, даты, единицы и отрицания не искажаются;
* запрос строится из клейма, а не из чата — у планировщика вообще нет
  доступа к контексту/участникам (нет параметра ``ctx``);
* предел длины запроса (`_QUERY_MAX_CHARS`);
* технические санитайзеры секретов (`safe_fetch.mask_text/mask_query`) —
  их этот контракт не трогает.

TEST-LIFECYCLE: CONTRACT owner=BGS-01 (снятие privacy-вето в фактчеке).
"""
from __future__ import annotations

import pytest

from config.settings import settings
from services import factcheck_planner as fsp
from services import factcheck_suitability as fsg


@pytest.fixture
def planner_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


def _decision(claim: str, scope: str = "web"):
    return fsg.SuitabilityDecision(
        decision=fsg.DECISION_CHECKABLE,
        claim_type=fsg.CHECKABLE_FACTUAL_CLAIM, claim_items=(),
        scope=scope, reason_code="obvious_checkable_predicate",
        confidence=0.8, target_ref={"chat_id": -100555})


def _plan(claim: str):
    return fsp.build_retrieval_plan(_decision(claim), claim_text=claim)


# ── Имя участника: остаётся в клейме и в запросе ────────────────────────────

def test_participant_name_reaches_query(planner_on):
    claim = "Маша уволилась из Сбера"
    plan = _plan(claim)
    assert plan is not None and plan.queries
    assert plan.claim_text == claim                 # клейм не переписан
    assert plan.claims[0].text == claim
    joined = " ".join(q.text.lower() for q in plan.queries)
    assert "маша" in joined                         # имя уходит в поиск
    assert "сбер" in joined                         # тема не потеряна


def test_name_only_claim_is_not_deleted(planner_on):
    """Клейм-имя (без глагола/факта) не превращается в пустую строку:
    имя остаётся в проверяемой части; план либо строится по имени, либо не
    строится вовсе (обычный путь сервиса), но пустого запроса не возникает."""
    claim = "Маша Петрова"
    units = fsp.build_claim_units([], claim)
    assert units and units[0].text == claim         # имя не вычищено
    plan = _plan(claim)
    if plan is not None:
        assert plan.claim_text == claim
        assert plan.queries and all(q.text.strip() for q in plan.queries)


def test_single_token_name_follows_honest_path(planner_on):
    """Однословный клейм: либо запрос по имени, либо обычный путь «проверить
    нечего» (plan=None → клейм уходит в сервис как есть), но НЕ удаление
    имени и НЕ пустой запрос вместо него."""
    claim = "Маша"
    units = fsp.build_claim_units([], claim)
    assert units and units[0].text == claim         # текст части — само имя
    plan = _plan(claim)
    if plan is not None:
        assert plan.queries and all(q.text.strip() for q in plan.queries)


# ── Смысловое ядро клейма не искажается ─────────────────────────────────────

def test_numeric_claim_keeps_numbers(planner_on):
    claim = "В Килякете выпало 120 мм осадков за сутки"
    plan = _plan(claim)
    assert plan is not None and plan.queries
    assert plan.claim_text == claim
    unit = plan.claims[0]
    assert "120" in unit.text
    assert any("120" in metric for metric in unit.metrics)
    numeric = [q for q in plan.queries if q.intent == fsp.INTENT_NUMERIC]
    assert numeric, "числовой интент должен строиться"
    assert "120" in numeric[0].text


def test_negation_claim_keeps_negation(planner_on):
    claim = "В Килякете не выпало 120 мм осадков за сутки"
    plan = _plan(claim)
    assert plan is not None and plan.queries
    assert plan.claim_text == claim
    assert "не выпало" in plan.claims[0].text       # отрицание не снято
    assert plan.claims[0].text.count("не ") == claim.count("не ")


def test_quoted_claim_keeps_quote(planner_on):
    claim = "В отчёте написано: «в Килякете выпало 120 мм осадков за сутки»"
    plan = _plan(claim)
    assert plan is not None and plan.queries
    assert "«" in plan.claim_text and "»" in plan.claim_text
    assert any(q.intent == fsp.INTENT_ORIGIN for q in plan.queries), \
        "цитата должна проверяться по происхождению"


# ── Техническая гигиена (не про людей) ──────────────────────────────────────

def test_planner_has_no_chat_context_input(planner_on):
    """У планировщика нет доступа к участникам: вычищать имена нечем и
    неоткуда — «весь чат в запрос» структурно невозможен."""
    with pytest.raises(TypeError):
        fsp.build_retrieval_plan(_decision("Маша уволилась из Сбера"),
                                 ctx=object())


def test_query_length_cap_kept(planner_on):
    claim = "В Килякете " + " ".join(f"слово{i}" for i in range(200))
    plan = _plan(claim)
    assert plan is not None and plan.queries
    assert max(len(q.text) for q in plan.queries) <= fsp._QUERY_MAX_CHARS


def test_secret_masking_of_urls_and_logs_intact():
    """Техническая гигиена секретов остаётся (не относится к именам людей)."""
    from services import safe_fetch as sf
    assert "SECRET" not in sf.mask_text("failed url=https://h?key=SECRET&a=1")
    assert "abcdef" not in sf.mask_text("Bearer sk-abcdef")
    assert sf.mask_query("key=abc123&q=погода") == "key=***&q=погода"
