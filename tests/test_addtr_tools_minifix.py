"""ADD-TR.3 (слайс ADTR-TOOLS, 19.10.2026) — health/checkup как исполняемая
capability L1 + фиксация свободной формы генерации.

Контракт (source-add-tr-2026-10-19.md §ADD-TR.3 п.4, снапшот L45):
свободное «бот, как состояние сервера?» / «глянь последние ошибки» /
«проверь логи» приводит к СУЩЕСТВУЮЩЕМУ инструменту ``get_bot_health`` (тот
же путь, что канонический «чекап» роутера 0g): capability резолвится,
анонсируется L1, исполняется через уже существующий ``ToolRouter`` и отдаёт
реальные данные Writer'у. При выключенном модуле чекапа — честный
наблюдаемый отказ (registry notice + ошибка исполнителя), без выдуманного
«всё нормально» без данных.

Пять независимых фактов (§ADD-TR.3 L48) в файле разведены явно:
  зарегистрирован (схема) / показан LLM (анонс) / модель вызвала
  (dispatch) / данные (evidence) / Writer получает текст (tool_context).

TEST-LIFECYCLE: CONTRACT owner=ADTR-TOOLS
Покрывает M-ADTR-TOOLS-E2E (health-сценарий, unit-контур) и
M-ADTR-TOOLS-FIVEFACTS (стадии не смешаны) из
plans/features/add-tr/requirements-map.json. Живые вызовы в Telegram —
postdeploy (live_when=postdeploy); здесь — достоверная код-цепочка.
"""
from __future__ import annotations

import pytest

from services import capability_registry as caps
from services import direct_capabilities as dc
from services import direct_execution as dx
from services import direct_l1 as l1
from services import hot_config as hot
from services import image_generation as ig
from services.tool_router import ToolContext
from services.tool_schemas import TOOL_CALLING_TOOLS, active_tools
from tests.test_asap8_v6_wc_direct_d04 import _Router

CHAT = -1001234567890
QUERY_FREE = "бот, как состояние сервера, глянь последние ошибки"
HEALTH_REPORT = "ЧЕКАП: бот зелёный, ошибок за сутки не найдено"


class _Cfg:
    """hot-слой с явным гейтом чекапа (реальный путь hot.get)."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture(autouse=True)
def _clean_state():
    caps.reset_cache()
    hot.set_config_cache(None)
    yield
    caps.reset_cache()
    hot.set_config_cache(None)


def _plan(**over):
    return l1.normalize_l1_plan(dict(
        {"action": "reply", "confidence": 0.9, **over}))


# ── 1. Capability ссылается на существующий инструмент и анонсируется ──────


def test_health_capability_maps_to_existing_tool():
    """Не пересоздание: capability → уже существующий канон-инструмент."""
    assert dc.CAPABILITY_TOOLS["health"] == ("get_bot_health",)
    names = [t["function"]["name"] for t in TOOL_CALLING_TOOLS]
    assert "get_bot_health" in names


def test_health_resolves_in_l1_subset():
    resolved, rejected = dc.resolve_capabilities(
        ["health"], {"get_bot_health", "execute_web_search"})
    assert resolved == ["get_bot_health"]
    assert rejected == []


def test_health_announced_in_l1_vocabulary():
    """L1-планировщик видит capability в «ДОСТУПНЫЕ ВОЗМОЖНОСТИ» — иначе
    свободная форма физически не может дойти до инструмента."""
    names = {t["function"]["name"] for t in active_tools(True, False)}
    assert "health" in dc.available_capabilities(names)


def test_health_honest_rejection_when_inactive():
    """Известная capability без активного тула — наблюдаемый отказ."""
    resolved, rejected = dc.resolve_capabilities(["health"], set())
    assert resolved == []
    assert rejected == [("health", dc.REASON_NOT_ACTIVE)]


# ── 2. Реестр: честная доступность (ON → ready; OFF → отказ с причиной) ────


@pytest.mark.asyncio
async def test_registry_knows_health_as_ready():
    hot.set_config_cache(_Cfg({"flags.checkup_enabled": True}))
    state = await caps.resolve("health", CHAT, use_cache=False)
    assert state.status == caps.STATUS_READY
    assert state.tool_name == "get_bot_health"
    assert state.declared is True
    assert caps.CHECKUP_KEY in state.gates
    assert caps.notice_block(state) == ""


@pytest.mark.asyncio
async def test_registry_health_off_never_silent():
    """Модуль выключен → registry обязан сказать «недоступно» (Writer не
    обещает и не выдумывает), а не молчать/притворяться готовым."""
    hot.set_config_cache(_Cfg({"flags.checkup_enabled": False}))
    state = await caps.resolve("health", CHAT, use_cache=False)
    assert state.status == caps.STATUS_DISABLED
    assert state.reason_code == "checkup_module_disabled"
    notice = caps.notice_block(state)
    assert "health" in notice and "недоступен" in notice


# ── 3. Цепочка: derivation → dispatch → данные → Writer (simple_tools) ─────


def test_health_derived_as_deterministic_step():
    plan = _plan(capabilities_needed=["health"])
    assert plan.execution_mode == "simple_tools"
    steps, limitations = dx.derive_simple_steps(
        plan, query=QUERY_FREE, ctx=None, announced={"get_bot_health"})
    assert [s["tool"] for s in steps] == ["get_bot_health"]
    assert steps[0]["arguments"] == {}
    assert not [line for line in limitations if "health" in line], limitations


@pytest.mark.asyncio
async def test_health_simple_tools_dispatch_returns_data_for_writer():
    """Данные реального исполнения (не факт вызова) доезжают до tool_context,
    который получает Writer."""
    plan = _plan(capabilities_needed=["health"])
    router = _Router(outputs={"get_bot_health": HEALTH_REPORT})
    result = await dx.run_simple_tools(
        plan=plan, router=router, ctx=None, query=QUERY_FREE,
        chat_id=CHAT, correlation_id="t-ok", announced={"get_bot_health"})
    assert result is not None
    assert [d["tool"] for d in router.dispatched] == ["get_bot_health"]
    assert result.evidence_sources[0].tool == "get_bot_health"
    assert result.evidence_sources[0].status == "ok"
    assert HEALTH_REPORT in (result.tool_context or "")


@pytest.mark.asyncio
async def test_health_failure_is_visible_not_fabricated():
    """Сбой инструмента честно виден в evidence/контексте Writer'а:
    никакого «всё нормально» из пустоты."""
    plan = _plan(capabilities_needed=["health"])
    router = _Router(fail=("get_bot_health",))
    result = await dx.run_simple_tools(
        plan=plan, router=router, ctx=None, query=QUERY_FREE,
        chat_id=CHAT, correlation_id="t-fail", announced={"get_bot_health"})
    assert result is not None
    src = result.evidence_sources[0]
    assert src.tool == "get_bot_health"
    # K1-контракт ON → канонический статус сбоя (timeout/error), OFF → error;
    # в обоих случаях это НЕ успех.
    assert src.status not in ("ok", "empty"), src.status
    assert "ОШИБКА get_bot_health" in (result.tool_context or "")
    assert HEALTH_REPORT not in (result.tool_context or "")


@pytest.mark.asyncio
async def test_health_real_executor_report_flows_to_writer_context():
    """INTEGRATION: в дет. шаге — РЕАЛЬНЫЙ ToolRouter (тот же обработчик
    _get_bot_health, что у канонического «чекапа» 0g): отчёт чекапа
    становится данными для Writer'а (fetch → checkup → tool_context)."""
    from unittest.mock import AsyncMock, MagicMock

    from services.tool_router import ToolHealthDeps, ToolRouter
    from tests.test_tool_calling_round1015 import _deps
    service = MagicMock()
    service.checkup = AsyncMock(return_value=HEALTH_REPORT)
    fetcher = MagicMock()
    fetcher.fetch = AsyncMock(return_value=("logs", False))
    router = ToolRouter(_deps(health=ToolHealthDeps(service, fetcher)))
    plan = _plan(capabilities_needed=["health"])
    result = await dx.run_simple_tools(
        plan=plan, router=router, ctx=ToolContext(CHAT, QUERY_FREE),
        query=QUERY_FREE, chat_id=CHAT, correlation_id="t-real",
        announced={"get_bot_health"})
    assert result is not None
    fetcher.fetch.assert_awaited_once()
    service.checkup.assert_awaited_once_with("logs", False)
    assert HEALTH_REPORT in (result.tool_context or "")


@pytest.mark.asyncio
async def test_l1_seam_announce_then_execute_once():
    """Seam реального сервиса: L1-подсет анонсирует ТОЛЬКО get_bot_health,
    tool-фаза (simple_tools) вызывает его ровно один раз и отдаёт данные."""
    import services.direct_chat_service as dcs
    svc = object.__new__(dcs.DirectChatService)
    router = _Router(outputs={"get_bot_health": HEALTH_REPORT})
    svc.tool_router = router
    plan = _plan(capabilities_needed=["health"])
    schemas, rejected = await svc._l1_tool_subset(
        CHAT, "run-tools-1", True, False, plan)
    assert [t["function"]["name"] for t in schemas] == ["get_bot_health"]
    assert rejected == ()
    ctx = ToolContext(CHAT, QUERY_FREE, correlation_id="run-tools-1")
    result = await svc._l1_tool_phase(
        None, ctx, query=QUERY_FREE, lore_enabled=True, image_enabled=False,
        temperature=None, chat_id=CHAT, correlation_id="run-tools-1",
        l1_plan=plan, response_plan=None, fallback_meta={}, time_line="",
        tool_schemas=schemas)
    assert result is not None
    assert [d["tool"] for d in router.dispatched] == ["get_bot_health"]
    assert HEALTH_REPORT in (result.tool_context or "")


@pytest.mark.asyncio
async def test_full_handle_health_evidence_reaches_l2_writer(monkeypatch):
    """INTEGRATION (handle → L1 → tool-фаза → L2): отчёт get_bot_health
    реально попадает в контекст Writer'а (§ADD-TR.3: данные, не «факт
    вызова»)."""
    from tests.test_asap8_v6_wc_direct_d04 import _Router
    from tests.test_soul1_capability_intent import _drive, _plan_json, _run
    router = _Router(outputs={"get_bot_health": HEALTH_REPORT})
    svc, llm, bot, msg, user, _gen, announced = _drive(
        monkeypatch, QUERY_FREE,
        l1=_plan_json(capabilities_needed=["health"]), router=router)
    await _run(svc, bot, msg, user)
    assert announced, "tool-фаза не дошла до анонса инструментов"
    assert "get_bot_health" in announced[0][1]
    assert [d["tool"] for d in router.dispatched] == ["get_bot_health"]
    assert HEALTH_REPORT in llm.l2_user_content()


# ── 4. Канон «чекап» не задет (0g-роутер и его гейт) ────────────────────────


def test_canonical_checkup_trigger_intact():
    import handlers.checkup as chk
    assert chk._is_checkup_trigger("чекап") is True
    assert chk._is_checkup_trigger("Чекап!") is True
    assert chk._is_checkup_trigger("чекапнуть") is False


def test_checkup_group_stays_functional_for_direct_yield():
    """Канонический «чекап» в Direct по-прежнему yield-ится в 0g, когда
    модуль включён, и не теряется, когда выключен (идёт обычным путём)."""
    import handlers.direct_chat as dch
    hot.set_config_cache(_Cfg({"flags.checkup_enabled": True}))
    assert dch._functional_module_active("checkup") is True
    hot.set_config_cache(_Cfg({"flags.checkup_enabled": False}))
    assert dch._functional_module_active("checkup") is False


# ── 5. Свободная форма генерации изображений (фиксация проводки) ────────────


@pytest.mark.asyncio
async def test_free_form_draw_reaches_single_image_workflow(monkeypatch):
    """«Бот, надо нарисовать X» — смысловая дверь (не регекс): ровно одна
    генерация, ровно один L1-вызов, через существующий image-контур."""
    from tests.test_soul1_capability_intent import _drive, _run
    text = "Бот, надо нарисовать мем про котов"
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.actionable is True
    assert ig.is_image_keyword(text) is False    # не регекс-быстрый путь
    svc, llm, bot, msg, user, gen_calls, _tools = _drive(monkeypatch, text)
    await _run(svc, bot, msg, user)
    assert len(gen_calls) == 1
    assert llm.steps().count("l1_planner") == 1
