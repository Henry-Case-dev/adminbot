"""UNIFIED-REPLY UR-B — живая проводка оси поиска (BGS-01), а не тестовая.

Контракт `plans/features/unified-reply/arch/unified-reply-contract.md`
(UR-03/UR-06, owner 2026-11-05 §4) и BGS-01. До этой правки ось
`knowledge_origin`/`search_intent` жила ТОЛЬКО в тестах: `run_tool_phase`
вызывался лишь из `tests/`, а живые пути шли прежней цепочкой, и канон
планнера о полях молчал.

Проверяется наблюдаемое поведение:

  1. живой tool-этап Direct и Initiative идёт через `run_tool_phase`: ось
     плана РЕАЛЬНО запускает (или не запускает) сетевой поиск у провайдера;
  2. технические гейты сохранены на живом пути: явный запрет человека,
     SILENT/REACT, отсутствие инструмента (RBAC/флаги сети режет
     `_l1_tool_subset`), пустая формулировка;
  3. содержательного вето по теме нет (BGS-01) — личная реплика с именем
     участника доходит до провайдера;
  4. ровно ОДНА tool-фаза на ход (нет двойного исполнения того же поиска);
  5. поля оси реально ЗАПРАШИВАЮТСЯ моделью — проверка на отрендеренном
     system-промпте живого L1-пакета, а не на константе модуля.

Тесты идут через НАСТОЯЩИЙ `ToolRouter` с подменным поисковым провайдером
(`ToolDeps.search`), без сети.

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-B (live wiring)
"""
import inspect
import json

import pytest

import services.direct_chat_service as dcs
from services import direct_execution as _dx
from services import direct_l1 as _l1
from services import evidence_policy as _evp
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from tests.test_direct_chat import FakeLLM, FakeMemory, _make_service, _message

pytestmark = [pytest.mark.system2]

CHAT_ID = -1001234567890
CORRELATION = "corr-ur-b-live"


class _SearchProvider:
    """Подменный поисковый провайдер (SearchAggregator.search-совместимый)."""

    def __init__(self, text: str = "Заголовок\nфакт\nhttps://example.com/ok"):
        self.text = text
        self.queries: list[str] = []

    async def search(self, query, max_symbols=4000, **kw):
        self.queries.append(str(query))
        return self.text


def _router(search) -> ToolRouter:
    return ToolRouter(ToolDeps(search=search, memory=object()))


def _plan(**over):
    return _l1.normalize_l1_plan(dict({"action": "reply", "confidence": 0.9,
                                       **over}))


def _schemas(*names):
    return [{"function": {"name": name, "description": name}}
            for name in names]


def _service(search) -> dcs.DirectChatService:
    return _make_service(memory=FakeMemory(window=[]), llm=FakeLLM(),
                         tool_router=_router(search))


async def _tool_phase(service, plan, query, *, tool_schemas=None,
                      required_caps=(), explicit_request=False):
    return await service._l1_tool_phase(
        None, ToolContext(CHAT_ID, query), query=query,
        lore_enabled=False, image_enabled=False, temperature=0.5,
        chat_id=CHAT_ID, correlation_id=CORRELATION, l1_plan=plan,
        response_plan=plan.to_response_plan(), fallback_meta={},
        time_line="", tool_schemas=(_schemas("execute_web_search")
                                    if tool_schemas is None else tool_schemas),
        required_caps=required_caps, explicit_request=explicit_request)


@pytest.fixture()
def traces(monkeypatch):
    """Перехват R17-safe трассы поиска (MCA-контракт, поле source_ref_json)."""
    captured: list[dict] = []

    def _emit(event_name, **fields):
        if event_name == "reply_search_evidence":
            captured.append(dict(fields.get("source_ref_json") or {}))
        return {"event_name": event_name}

    import services.mca_events as mca_events
    monkeypatch.setattr(mca_events, "emit_mca_event", _emit)
    return captured


# ── живой Direct tool-этап: ось управляет поиском ───────────────────────────


class TestLiveDirectToolPhase:
    @pytest.mark.asyncio
    async def test_axis_open_world_reaches_provider(self):
        """`knowledge_origin=open_world` без capability → реальный поиск."""
        search = _SearchProvider()
        service = _service(search)
        plan = _plan(knowledge_origin="open_world", capabilities_needed=[],
                     execution_mode="none")
        raw = await _tool_phase(service, plan, "когда вышла новая модель?")
        assert len(search.queries) == 1, "ось обязана дать реальный вызов"
        assert raw is not None
        tools = [str(getattr(s, "tool", "")) for s in raw.evidence_sources]
        assert "execute_web_search" in tools

    @pytest.mark.asyncio
    async def test_runtime_policy_still_forces_search_over_model_opinion(self):
        """Runtime-обязательная проверка не понижается мнением планера."""
        search = _SearchProvider()
        service = _service(search)
        plan = _plan(knowledge_origin="conversation_only",
                     search_intent="not_applicable")
        raw = await _tool_phase(service, plan, "свежий курс биткоина",
                                required_caps=("web_search",))
        assert len(search.queries) == 1
        assert raw is not None and raw.evidence_sources

    @pytest.mark.asyncio
    async def test_personal_topic_and_name_still_reach_provider(self):
        """BGS-01 §2.4: имя участника — тема, а не основание не искать."""
        search = _SearchProvider()
        service = _service(search)
        plan = _plan(knowledge_origin="open_world")
        await _tool_phase(service, plan,
                          "У Маши болит голова, какие общие причины бывают?")
        assert len(search.queries) == 1
        assert "голов" in search.queries[0].lower()

    @pytest.mark.asyncio
    async def test_chat_only_turn_makes_no_network_call(self, traces):
        """`not_applicable` → поиска ради отчётности нет (и он виден в трассе)."""
        search = _SearchProvider()
        service = _service(search)
        plan = _plan(knowledge_origin="conversation_only",
                     search_intent="not_applicable",
                     capabilities_needed=["web_search"])
        raw = await _tool_phase(service, plan,
                               "перескажи нашу шутку про 4 утра")
        assert search.queries == []
        assert traces, "трасса поиска обязана быть на живом пути"
        assert traces[-1]["search_called"] is False
        assert traces[-1]["search_intent"] == "not_applicable"
        # Инструментов, исполнимых без сети, у плана нет → raw отсутствует.
        assert raw is None or not raw.evidence_sources

    @pytest.mark.asyncio
    async def test_explicit_no_web_request_blocks_with_own_reason(self, traces):
        """Прямой запрет человека: сеть не тронута, причина названа честно."""
        search = _SearchProvider()
        service = _service(search)
        plan = _plan(knowledge_origin="open_world",
                     capabilities_needed=["web_search"])
        await _tool_phase(service, plan,
                          "не ищи в интернете, просто скажи что думаешь",
                          required_caps=("web_search",))
        assert search.queries == [], "запрет сети человеком нарушен"
        assert traces[-1]["search_called"] is False
        assert traces[-1]["search_skip_reason"] == _dx.SKIP_USER_FORBIDDEN

    @pytest.mark.asyncio
    async def test_silent_and_react_make_no_tool_calls(self, traces):
        for action, reaction in (("silent", None), ("react", "👍")):
            search = _SearchProvider()
            service = _service(search)
            plan = _plan(action=action, reaction=reaction,
                         knowledge_origin="open_world",
                         capabilities_needed=["web_search"])
            raw = await _tool_phase(service, plan, "что нового в мире",
                                    required_caps=("web_search",))
            assert search.queries == [], f"{action}: поиск ради отчётности"
            assert raw is None
            assert traces[-1]["search_skip_reason"] == (
                _dx.SKIP_PARTICIPATION_WITHOUT_TEXT)

    @pytest.mark.asyncio
    async def test_missing_tool_is_honest_not_search(self, traces):
        """RBAC/флаги сети режут набор схем → честный `tool_absent`."""
        search = _SearchProvider()
        service = _service(search)
        plan = _plan(knowledge_origin="open_world")
        await _tool_phase(service, plan, "цены на видеокарты",
                          tool_schemas=_schemas("get_recent_history"))
        assert search.queries == []
        assert traces[-1]["search_skip_reason"] == _dx.SKIP_TOOL_ABSENT

    @pytest.mark.asyncio
    async def test_empty_query_is_technical_skip(self, traces):
        search = _SearchProvider()
        service = _service(search)
        plan = _plan(knowledge_origin="open_world")
        await _tool_phase(service, plan, "  79991234567  ")
        assert search.queries == []
        assert traces[-1]["search_skip_reason"] == _dx.SKIP_EMPTY_QUERY

    @pytest.mark.parametrize("query", [
        # ключевые слова поиска ЕСТЬ («найди…»), но ось решила «не искать»:
        # fallback `_SEARCH_RE` не имеет права вернуть сетевой шаг.
        "найди в нашей переписке шутку про 4 утра",
        "перескажи, что мы обсуждали в интернете вчера",
    ])
    @pytest.mark.asyncio
    async def test_axis_not_applicable_blocks_keyword_search(self, query,
                                                             traces):
        """`not_applicable` — структурный запрет сети, а не только статус.

        Репро ревью: план `conversation_only`/`not_applicable` с capability
        `web_search` отправлял провайдеру сырой текст реплики, потому что
        деривация шагов по `_SEARCH_RE` возвращала `execute_web_search`.
        """
        search = _SearchProvider()
        service = _service(search)
        plan = _plan(knowledge_origin="conversation_only",
                     search_intent="not_applicable",
                     capabilities_needed=["web_search"])
        raw = await _tool_phase(service, plan, query)
        assert search.queries == [], (
            f"сеть тронута при not_applicable: {search.queries}")
        assert raw is None or all(
            str(getattr(s, "tool", "")) != "execute_web_search"
            for s in raw.evidence_sources)
        assert traces[-1]["search_called"] is False
        # Причина остаётся собственной причиной оси, а не «пустой запрос».
        assert traces[-1]["search_skip_reason"] == (
            _dx.SKIP_INTENT_NOT_APPLICABLE)

    @pytest.mark.asyncio
    async def test_axis_absent_keeps_plan_requested_search(self, traces):
        """«Поля оси не пришли» — не запрет: просьба плана остаётся в силе."""
        search = _SearchProvider()
        service = _service(search)
        plan = _plan(capabilities_needed=["web_search"])
        assert plan.search_intent == ""      # ось не заполнена планом
        await _tool_phase(service, plan, "найди в интернете какая погода")
        assert len(search.queries) == 1, (
            "паритет: без полей оси поиск плана обязан работать")
        assert traces[-1]["search_called"] is True

    @pytest.mark.asyncio
    async def test_axis_required_with_keywords_still_searches(self, traces):
        """Контроль обратного направления: ось просит поиск → вызов есть."""
        search = _SearchProvider()
        service = _service(search)
        plan = _plan(knowledge_origin="open_world")
        await _tool_phase(service, plan, "найди в интернете, какая погода")
        assert len(search.queries) == 1
        assert traces[-1]["search_called"] is True
        assert traces[-1]["search_intent"] == "required"

    @pytest.mark.asyncio
    async def test_exactly_one_tool_phase_per_turn(self):
        """Нет двойного исполнения: capability+required_caps не дублируют поиск."""
        search = _SearchProvider()
        service = _service(search)
        plan = _plan(knowledge_origin="web_search",  # мусор → ""
                     search_intent="required",
                     capabilities_needed=["web_search"])
        await _tool_phase(service, plan, "курс биткоина",
                          required_caps=("web_search",))
        assert len(search.queries) == 1, "поиск выполнен более одного раза"

    @pytest.mark.asyncio
    async def test_adaptive_mode_does_not_repeat_the_search(self, monkeypatch):
        """Adaptive-ветка получает дет. поиск первым шагом без повтора."""
        monkeypatch.setenv("DIRECT_ADAPTIVE_ORCHESTRATOR_ENABLED", "1")
        search = _SearchProvider()
        service = _service(search)

        class _Orchestrator(FakeLLM):
            async def generate(self, messages, **kw):
                self.call_count += 1
                return '{"action": "finish", "reason": "done"}'

        service.llm = _Orchestrator()
        plan = _plan(knowledge_origin="open_world",
                     execution_mode="adaptive_tool_chain",
                     capabilities_needed=["web_search"])
        await _tool_phase(service, plan, "проверь свежий факт")
        assert len(search.queries) == 1, (
            f"второго поиска быть не должно: {search.queries}")

    def test_live_helper_delegates_to_unified_phase(self):
        """Анти-регресс: живой seam не имеет собственной копии цепочки.

        Иначе ось снова окажется мёртвой в проде, а тесты останутся зелёными
        (ровно дефект, который закрывала эта правка).
        """
        src = inspect.getsource(dcs.DirectChatService._l1_tool_phase)
        assert "run_tool_phase" in src
        assert "run_adaptive_chain" not in src
        assert "run_simple_tools" not in src

    def test_both_live_call_sites_use_the_single_tool_phase(self):
        """Оба живых call site идут через общий этап, а не своей цепочкой."""
        for method in (dcs.DirectChatService._handle_turn,
                       dcs.DirectChatService.generate_initiative_reply):
            src = inspect.getsource(method)
            assert "self._l1_tool_phase(" in src, method.__name__
            assert "run_simple_tools" not in src, method.__name__
            assert "run_adaptive_chain" not in src, method.__name__


# ── живой Initiative path: тот же единый этап ───────────────────────────────


def _initiative_decision(*, required=True, caps=("web_search",),
                         claim=("rtx 5090", "exists")):
    return _evp.EvidenceDecision(
        required=required, evidence_class="externally_factual",
        claims=(_evp.ClaimKey(entity=claim[0], relation=claim[1]),)
        if claim else (),
        required_caps=tuple(caps), explicit_request=False,
        note="test_initiative")


class TestLiveInitiativeToolPhase:
    @pytest.mark.asyncio
    async def test_initiative_call_site_reaches_provider(self, monkeypatch,
                                                         traces):
        """`generate_initiative_reply` — настоящий инициативный tool-этап."""
        search = _SearchProvider()
        service = _service(search)

        async def _preflight(*a, **kw):
            return _initiative_decision()

        captured: dict = {}

        async def _writer(*a, **kw):
            captured["evidence"] = str(kw.get("evidence") or "")
            return ("инициативный текст", "plain")

        monkeypatch.setattr(service, "_evidence_preflight", _preflight)
        monkeypatch.setattr(service, "_l2_write_answer", _writer)
        monkeypatch.setattr(_evp, "egress_guard_enabled", lambda: False)
        plan = _l1.parse_l1_plan(json.dumps({
            "action": "reply", "response_act": "other",
            "knowledge_origin": "open_world"}))
        assert plan is not None and plan.search_intent == "required"
        await service.generate_initiative_reply(
            CHAT_ID, {"goal": "напомнить про релиз", "kind": "follow_up",
                      "origin": "observer"}, l1_plan=plan,
            correlation_id=CORRELATION)
        assert len(search.queries) == 1, (
            "инициатива обязана идти тем же единым tool-этапом")
        assert "example.com" in captured.get("evidence", ""), (
            "выдача обязана дойти до Writer'а")
        # Единый этап пишет R17-safe трассу оси и на инициативном пути:
        # старая цепочка её не писала вовсе.
        assert traces[-1]["search_intent"] == "required"
        assert traces[-1]["search_called"] is True

    @pytest.mark.asyncio
    async def test_initiative_without_claim_query_makes_no_call(self, monkeypatch):
        """Паритет прежнего решения: нет claim'ов → запроса нет (не мусор)."""
        search = _SearchProvider()
        service = _service(search)

        async def _preflight(*a, **kw):
            return _initiative_decision(claim=None)

        async def _writer(*a, **kw):
            return ("инициативный текст", "plain")

        monkeypatch.setattr(service, "_evidence_preflight", _preflight)
        monkeypatch.setattr(service, "_l2_write_answer", _writer)
        monkeypatch.setattr(_evp, "egress_guard_enabled", lambda: False)
        plan = _l1.parse_l1_plan(json.dumps({
            "action": "reply", "knowledge_origin": "open_world"}))
        await service.generate_initiative_reply(
            CHAT_ID, {"goal": "спросить, как прошёл день",
                      "kind": "follow_up", "origin": "observer"},
            l1_plan=plan, correlation_id=CORRELATION)
        assert search.queries == []


# ── канон L1: поля оси реально запрошены у модели ───────────────────────────


class TestL1PromptAsksForAxis:
    @pytest.mark.asyncio
    async def test_rendered_l1_system_prompt_requests_axis_fields(self):
        """Отрендеренный L1-пакет (тот, что уходит модели) несёт поля оси."""
        service = _make_service(memory=FakeMemory(window=[]),
                                llm=FakeLLM(text='{"action": "reply"}'))
        message = _message("привет, как дела?", message_id=101)

        async def _not_partial(*a, **kw):
            return False

        service._history_partial = _not_partial
        await service._plan_direct_l1(
            CHAT_ID, message, "привет, как дела?", CORRELATION, bundle=None,
            target_name="Вася", user_id=10, character_block="",
            lore_enabled=False, image_enabled=False, force_required=True,
            reply_bot=False)
        system = str(service.llm.messages[0]["content"])
        assert "ИСТОЧНИК ЗНАНИЯ И НУЖДА В ПОИСКЕ" in system
        # Поля стоят в СХЕМЕ, а не только в пояснительном абзаце.
        schema = system.split("СХЕМА JSON", 1)[1].split("\n\n", 1)[0]
        assert '"knowledge_origin": ""' in schema
        assert '"search_intent": ""' in schema
        assert '"preserve_source_facts": false' in schema
        # VMQ-MEM-TIME (§2): политика памяти — в ТОЙ ЖЕ схеме, после
        # сохранения фактов; значение по умолчанию auto.
        assert '"memory_scope": "auto"' in schema
        assert schema.index('"recheck": false,') < schema.index(
            '"knowledge_origin"') < schema.index('"search_intent": ""')
        assert schema.index('"search_intent": ""') < schema.index(
            '"preserve_source_facts": false') < schema.index(
            '"memory_scope": "auto"')
        # Значения перечислены в том же пакете — модели есть из чего выбрать.
        assert "conversation_only" in system
        assert "not_applicable" in system
