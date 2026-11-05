"""UNIFIED-REPLY UR-A: один движок хода для Direct и Initiative.

Контракт (`plans/features/unified-reply/arch/unified-reply-contract.md` §2.1/§2.4/§6,
строки карты UR-RES-01, UR-01..UR-01.6, UR-02..UR-02.4):

* тип хода и его политика (слот → fallback, схема плана, bounded repair, учёт
  usage, temperature) резолвятся ОДИН раз и одинаково на обоих трассах;
* обе трассы несут `TurnRequest` (его поля видны при инспекции хода), включая
  фактический исходный текст, адресата/reply-parent, права и медиа;
* L1 получает ФАКТИЧЕСКИ доступные capabilities — пустого списка при включённом
  инструменте больше нет;
* исполнение L1 одно (`_execute_turn`): repair/слот/usage не дублируются;
* регресс: SILENT/REACT и явная пользовательская просьба поиска не изменились;
* право инициативы на молчание сохранено (блок политики ключей → None, а не
  падение; прямое обращение по-прежнему уходит в sandbox-путь).

TEST-LIFECYCLE: CONTRACT + REGRESSION owner=UNIFIED-REPLY/UR-A
"""
import json

import pytest

import services.direct_chat_service as dcs
from services import direct_capabilities as _caps
from services import direct_l1 as _l1
from services import turn_types as _tt
from services.llm_client import NoApiKeyForChat
from tests.test_direct_chat import FakeLLM, FakeMemory, _make_service, _message

CHAT = 4242
USER_ID = 10


def _plan(**over):
    payload = {
        "action": "reply",
        "reaction": None,
        "response_act": "answer",
        "extent": "auto",
        "tone": "inherit",
        "delivery_hint": "plain",
        "capabilities_needed": [],
        "confidence": 0.8,
    }
    payload.update(over)
    return json.dumps(payload, ensure_ascii=False)


class _ScriptedLLM(FakeLLM):
    """LLM с заранее заданной очередью ответов (для repair-маршрута)."""

    def __init__(self, *texts, error=None):
        super().__init__(text=(texts[0] if texts else _plan()), error=error)
        self._texts = list(texts) or [_plan()]
        self.calls = []

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        self.calls.append({"messages": messages, "temperature": temperature,
                           "chat_id": chat_id, "kwargs": kwargs})
        self.call_count += 1
        if self.error:
            raise self.error
        index = (len(self.calls) - 1) % len(self._texts)
        return self._texts[index]


def _svc(*texts, window=None, llm=None, aliases=None):
    memory = FakeMemory(window=window if window is not None else [])
    service = _make_service(memory=memory, llm=llm or _ScriptedLLM(*texts),
                            aliases=aliases)
    return service


@pytest.fixture(autouse=True)
def _clean_trace():
    _l1.reset_turn_trace()
    yield
    _l1.reset_turn_trace()


def _patch_fixed_tool_flags(monkeypatch, *, lore=False, image=False):
    """Одинаковые входные флаги инструментов на обеих трассах."""
    async def _cpg(chat_id, key, default=None):
        if key == "flags.lore_compiler_enabled":
            return lore
        return default

    async def _image_enabled(chat_id):
        return image

    from services import image_generation
    monkeypatch.setattr("services.chat_params.get_chat_param", _cpg)
    monkeypatch.setattr(image_generation, "resolve_module_enabled",
                        _image_enabled)


async def _run_direct(service, *, text="привет, как дела?", message_id=100,
                      correlation="corr-direct", user_id=USER_ID,
                      lore=False, image=False):
    service._history_partial = _async_false()
    message = _message(text, message_id=message_id)
    return await service._plan_direct_l1(
        CHAT, message, text, correlation, bundle=None, target_name="Вася",
        user_id=user_id, character_block="", lore_enabled=lore,
        image_enabled=image, force_required=True, reply_bot=False)


async def _run_initiative(service, *, correlation="corr-init",
                          intent_row=None):
    row = intent_row if intent_row is not None else {
        "goal": "спросить, как прошёл день", "kind": "follow_up",
        "origin": "observer", "addressee_user_id": USER_ID}
    return await service.plan_initiative_decision(
        CHAT, row, correlation_id=correlation)


def _async_false():
    from unittest.mock import AsyncMock
    return AsyncMock(return_value=False)


# ── 1. Политика хода: одна таблица, отличие только в праве молчания ─────────

def test_turn_policy_is_identical_for_both_triggers():
    direct = _tt.turn_policy("direct")
    initiative = _tt.turn_policy("initiative")
    assert direct.turn_type != initiative.turn_type
    assert direct.plan_schema == initiative.plan_schema
    assert direct.slot_policy == initiative.slot_policy
    assert direct.repair_policy == initiative.repair_policy
    assert direct.temperature_source == initiative.temperature_source
    assert direct.usage_accounting == initiative.usage_accounting
    # Единственное различие — «право говорить», а не отдельный L1.
    assert direct.silent_on_policy_block is False
    assert initiative.silent_on_policy_block is True


def test_same_input_resolves_same_turn_type():
    assert _tt.resolve_turn_type("direct") == _tt.TurnType.DIRECT.value
    assert _tt.resolve_turn_type("initiative") == _tt.TurnType.INITIATIVE.value
    # Неизвестный/битый trigger не создаёт третий тип хода.
    assert _tt.resolve_turn_type("") == _tt.TurnType.DIRECT.value
    assert _tt.resolve_turn_type(None) == _tt.TurnType.DIRECT.value
    request = _tt.TurnRequest(trigger_type="initiative", chat_id=1)
    assert request.turn_type == _tt.turn_policy("initiative").turn_type


# ── 2. Один исполнитель: обе трассы идут через `_execute_turn` ──────────────

@pytest.mark.asyncio
async def test_both_traces_execute_through_single_turn_engine(monkeypatch):
    calls = []
    original = dcs.DirectChatService._execute_turn

    async def _spy(self, req, **kwargs):
        calls.append(req)
        return await original(self, req, **kwargs)

    monkeypatch.setattr(dcs.DirectChatService, "_execute_turn", _spy)
    _patch_fixed_tool_flags(monkeypatch)
    service = _svc(_plan())

    await _run_direct(service)
    await _run_initiative(service)

    assert len(calls) == 2
    assert isinstance(calls[0], _tt.TurnRequest)
    assert isinstance(calls[1], _tt.TurnRequest)
    assert [c.turn_type for c in calls] == ["direct", "initiative"]


@pytest.mark.asyncio
async def test_slot_schema_and_repair_resolution_equal_on_both_traces(
        monkeypatch):
    _patch_fixed_tool_flags(monkeypatch)
    service = _svc(_plan())

    _, direct_meta = await _run_direct(service)
    await _run_initiative(service)

    direct_trace, initiative_trace = _l1.get_turn_trace(CHAT, limit=2)
    # Один резолв слота/схемы/repair: значения совпадают, различается только
    # тип хода и его собственные данные.
    assert direct_trace.plan_schema == initiative_trace.plan_schema
    assert direct_trace.slot_policy == initiative_trace.slot_policy
    assert direct_trace.repair_policy == initiative_trace.repair_policy
    assert direct_trace.model == initiative_trace.model
    assert direct_trace.slot == initiative_trace.slot
    # Бюджет пакета/источник слота — из того же резолва, что на трассе.
    assert direct_meta["plan_schema"] == direct_trace.plan_schema
    assert direct_meta["l1_context_budget"] == \
        direct_trace.request.model_slot.budget_tokens
    assert initiative_trace.request.model_slot.budget_tokens == \
        direct_meta["l1_context_budget"]
    # Диагностика L1 показывает те же машинные оси для обоих триггеров.
    diag = _l1.get_l1_diagnostics(CHAT)
    assert diag["trigger_type"] == "initiative"
    assert diag["plan_schema"] == direct_trace.plan_schema
    assert diag["repair_policy"] == direct_trace.repair_policy


# ── 3. Capabilities: пустого списка больше нет ─────────────────────────────

def test_no_empty_capabilities_shortcut_left_in_engine_source():
    source = open("services/direct_chat_service.py", encoding="utf-8").read()
    # Прежний облегчённый инициативный L1 передавал пустой набор прав.
    assert "capabilities=()" not in source
    # И не ходит в модель напрямую мимо общего исполнителя.
    initiative_block = source[source.index(
        "async def plan_initiative_decision"):source.index(
        "async def generate_initiative_reply")]
    assert 'self.llm.generate(' not in initiative_block
    assert "_execute_turn(" in initiative_block


@pytest.mark.asyncio
async def test_initiative_receives_real_capabilities(monkeypatch):
    _patch_fixed_tool_flags(monkeypatch)
    captured = {}

    original_build = _l1.build_l1_context

    def _spy_build(**kwargs):
        captured.setdefault("capabilities", []).append(
            tuple(kwargs.get("capabilities") or ()))
        return original_build(**kwargs)

    monkeypatch.setattr(_l1, "build_l1_context", _spy_build)
    service = _svc(_plan())

    await _run_direct(service)
    await _run_initiative(service)

    direct_caps, initiative_caps = captured["capabilities"][0], \
        captured["capabilities"][1]
    assert direct_caps, "прямой ход обязан видеть свои инструменты"
    assert initiative_caps == direct_caps, \
        "одинаковые флаги → одинаковый набор прав у обоих триггеров"
    assert "web_search" in initiative_caps
    assert _l1.get_turn_trace(CHAT, limit=1)[0].capabilities == \
        initiative_caps


# ── 4. Трасса несёт TurnRequest целиком ────────────────────────────────────

@pytest.mark.asyncio
async def test_trace_carries_turn_request_with_full_source_text(monkeypatch):
    _patch_fixed_tool_flags(monkeypatch)
    long_text = "подробный вопрос " + ("деталь " * 130) + "ХВОСТ-МАРКЕР"
    assert len(long_text) > 900
    service = _svc(_plan())

    await _run_direct(service, text=long_text, message_id=777,
                      correlation="corr-trace")

    request = _l1.last_turn_request(CHAT)
    assert isinstance(request, _tt.TurnRequest)
    assert request.trigger_type == "direct"
    assert request.chat_id == CHAT
    assert request.correlation_id == "corr-trace"
    assert request.source_message_id == 777
    # UR-01.2: исходный текст целиком, без preview-среза.
    assert request.raw_text == long_text
    assert request.speaker_uid == USER_ID
    assert request.addressee is not None
    assert request.capabilities == request.tool_state.capabilities
    assert request.delivery.force_reply is True
    assert request.delivery.trigger == "direct"
    assert request.model_slot.budget_tokens > 0
    assert request.turn_started_at_utc > 0
    # Текст реально доехал до L1 в этом ходе.
    llm_call = service.llm.calls[-1]["messages"][-1]["content"]
    assert "ХВОСТ-МАРКЕР" in llm_call


@pytest.mark.asyncio
async def test_initiative_trace_carries_opportunity_and_addressee(monkeypatch):
    _patch_fixed_tool_flags(monkeypatch)
    service = _svc(_plan())
    row = {"intent_id": 55, "goal": "поздравить с днём рождения",
           "kind": "follow_up", "origin": "observer", "created_at": 1700,
           "addressee_user_id": USER_ID}

    await _run_initiative(service, intent_row=row)

    request = _l1.last_turn_request(CHAT)
    assert request.trigger_type == "initiative"
    assert request.turn_type == _tt.TurnType.INITIATIVE.value
    assert request.opportunity is not None
    assert request.opportunity.intent_id == 55
    assert request.opportunity.kind == "follow_up"
    assert request.addressee is not None
    assert request.addressee.user_id == USER_ID
    assert request.delivery.recheck is True
    assert request.source_message_id is None


# ── 5. Repair/учёт usage — тот же маршрут на обеих трассах ──────────────────

@pytest.mark.asyncio
async def test_invalid_json_repair_route_is_shared(monkeypatch):
    _patch_fixed_tool_flags(monkeypatch)
    llm = _ScriptedLLM("это не json", _plan())
    service = _svc(llm=llm)

    direct_plan, direct_meta = await _run_direct(service)
    assert direct_plan is not None
    assert direct_meta["repair"] == 1
    assert len(llm.calls) == 2

    before = len(llm.calls)
    initiative_plan = await _run_initiative(service)
    assert initiative_plan is not None
    # Инициатива больше не «одна попытка без repair»: тот же bounded repair.
    assert len(llm.calls) == before + 2
    assert _l1.get_l1_diagnostics(CHAT)["repair"] == 1
    assert _l1.get_l1_diagnostics(CHAT)["plan_schema"] == direct_meta[
        "plan_schema"]


@pytest.mark.asyncio
async def test_usage_is_accounted_on_both_traces(monkeypatch):
    _patch_fixed_tool_flags(monkeypatch)
    service = _svc(_plan())
    steps = []

    async def _generate(messages, temperature=None, chat_id=None, module=None,
                        step=None, correlation_id=None, **kwargs):
        steps.append((step, chat_id, module))
        return _plan()

    service.llm.generate = _generate
    await _run_direct(service)
    await _run_initiative(service)

    assert steps == [("l1_planner", CHAT, "direct_chat"),
                     ("l1_planner", CHAT, "direct_chat")]


# ── 6. Право говорить: блок политики ключей ────────────────────────────────

@pytest.mark.asyncio
async def test_policy_block_keeps_initiative_silent_and_direct_raising(
        monkeypatch):
    _patch_fixed_tool_flags(monkeypatch)
    service = _svc(_plan())

    async def _blocked(llm, chat_id):
        raise NoApiKeyForChat(chat_id, "forbidden")

    monkeypatch.setattr(_l1, "authorize_l1_call", _blocked)

    assert await _run_initiative(service) is None
    with pytest.raises(NoApiKeyForChat):
        await _run_direct(service)


# ── 7. Регресс: SILENT/REACT и явный поиск не изменились ───────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["silent", "react"])
async def test_silent_and_react_survive_single_engine(monkeypatch, action):
    _patch_fixed_tool_flags(monkeypatch)
    plan_json = _plan(action=action,
                      reaction=("👍" if action == "react" else None))
    service = _svc(plan_json)

    direct_plan, _ = await _run_direct(service)
    initiative_plan = await _run_initiative(service)

    assert direct_plan is not None and initiative_plan is not None
    assert direct_plan.action == action
    assert initiative_plan.action == action


@pytest.mark.asyncio
async def test_explicit_search_request_resolves_same_tools(monkeypatch):
    _patch_fixed_tool_flags(monkeypatch)
    events = []

    def _spy_emit(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(_l1, "emit_l1_plan_event", _spy_emit)
    service = _svc(_plan(capabilities_needed=["web_search"]))

    await _run_direct(service, text="проверь в интернете, кто сейчас президент")
    await _run_initiative(service)

    assert len(events) == 2
    for event in events:
        assert "web_search" in tuple(event["requested"])
        # Резолв — те же РЕАЛЬНЫЕ tools allowlist'а на обеих трассах.
        assert tuple(event["resolved"]) == ("execute_web_search",)
    assert events[0]["resolved"] == events[1]["resolved"]
    # Ось поиска (UR-B) не переписывается этим движком.
    plan = _l1.parse_l1_plan(_plan(capabilities_needed=["web_search"]))
    axis = _l1.resolve_search_axis(plan, explicit_request=True)
    assert axis.user_forced is True
    assert axis.search_expected is True


# ── 8. Capability-резолв: ложная capability не превращается в тул ─────────

def test_capability_resolution_is_the_shared_helper():
    service = _svc()
    announced = tuple(sorted({t["function"]["name"] for t in
                              dcs.active_tools(False, False)
                              if isinstance(t, dict) and t.get("function")}))
    expected = tuple(_caps.available_capabilities(announced))
    resolved, rejected = _caps.resolve_capabilities(
        ["web_search", "выдуманная_возможность", "web_search"], announced)
    assert resolved == ["execute_web_search"]
    assert set(resolved).issubset(set(announced))
    assert ("выдуманная_возможность", _caps.REASON_UNKNOWN) in rejected
    assert "web_search" in expected
    assert "выдуманная_возможность" not in expected
    assert service is not None
