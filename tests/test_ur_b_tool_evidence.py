"""UNIFIED-REPLY UR-B — одна ToolEvidence (UR-03.1) и общий набор источников L1/L2 (UR-04.3).

UR-03.1: права/состояние провайдеров вычисляются ДО планирования
(``_resolve_turn_tool_state``), а результат tool-этапа отдаётся одной
структурой ``ToolEvidence``: dedup/ошибки/источник/время/tool trace в одном
месте. Тесты идут через НАСТОЯЩИЙ tool-этап (``run_tool_phase``/
``run_simple_tools``/``_dispatch_step``) и настоящий ``ToolRouter`` с
подменным поисковым провайдером; проверяемая логика (dedup, envelope,
проекция) не подменяется.

UR-04.3: L1 и L2 разделяют ОДИН набор выбранных источников. Один и тот же
кандидатный набор строк проецируется двумя живыми потребителями: L1 —
``allocate_window_projection`` + ``build_l1_context`` (компактные строки),
L2 — ``_build_l2_selection_candidates`` + ``_materialize_selection``
(канонические XML-блоки). Ассерт — идентичность source refs при разных
форматах и независимых бюджетах стадий.

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-B (UR-03.1/UR-04.3)
"""
import json
import re
from types import SimpleNamespace

import pytest

import services.direct_chat_service as dcs
from services import direct_context_composer as comp
from services import direct_execution as _dx
from services import direct_l1 as _l1
from services import turn_types as _tt
from services.search_aggregator import AllSearchEnginesFailedException
from services.tool_router import ToolContext, ToolDeps, ToolRouter

pytestmark = [pytest.mark.system2]

CHAT_ID = -1001234567890
CORRELATION = "corr-ur-b-evidence"
BOT_UID = 998000


class _SearchProvider:
    """Подменный поисковый провайдер (SearchAggregator.search-совместимый)."""

    def __init__(self, text: str = "", *, exc=None):
        self.text = text
        self.exc = exc
        self.queries: list[str] = []

    async def search(self, query, max_symbols=4000, **kw):
        self.queries.append(str(query))
        if self.exc is not None:
            raise self.exc
        return self.text


def _plan(**over):
    return _l1.normalize_l1_plan(dict({"action": "reply", "confidence": 0.9,
                                       **over}))


def _schemas(*names):
    return [{"function": {"name": name, "description": name}}
            for name in names]


def _router(search) -> ToolRouter:
    return ToolRouter(ToolDeps(search=search, memory=object()))


def _evidence_from(raw, *, plan, query):
    """Собрать ToolEvidence тем же продуктовым сборщиком, что live-путь."""
    axis = _l1.resolve_search_axis(plan)
    task = _dx.build_search_query(plan, query=query)
    return _dx._tool_evidence_from(raw, axis=axis, search_task=task)


async def _run_tool_phase(plan, query, search, **kw):
    return await _dx.run_tool_phase(
        plan=plan, router=_router(search), ctx=ToolContext(CHAT_ID, query),
        query=query, chat_id=CHAT_ID, correlation_id=CORRELATION,
        tool_schemas=_schemas("execute_web_search"), **kw)


class _Aliases:
    def resolve(self, uid, name, username):
        return name or f"u{uid}"


# ═══ UR-03.1: права/состояние провайдеров до планирования ═══════════════════


class TestProviderStateBeforePlanning:
    @pytest.mark.asyncio
    async def test_turn_tool_state_is_the_runtime_provider_set(self,
                                                               monkeypatch):
        """Снимок возможностей хода берётся из ФАКТИЧЕСКОГО набора tools.

        Это происходит конструктором ``TurnRequest`` ДО планирования, поэтому
        недоступный провайдер не может «появиться» в плане как доступный.
        """
        from services import direct_chat_service as dcs_mod
        from tests.test_direct_chat import FakeLLM, FakeMemory, _make_service

        service = _make_service(memory=FakeMemory(window=[]), llm=FakeLLM())

        state = await service._resolve_turn_tool_state(
            CHAT_ID, lore_enabled=False, image_enabled=False)
        assert state.source == "active_tools"
        assert state.search_available is True
        assert "web_search" in state.capabilities

        async def _slim(_chat_id, _lore=False, _image=False):
            return [{"function": {"name": "get_recent_history"}}]

        monkeypatch.setattr(dcs_mod, "active_tools_for_chat", _slim)
        slim = await service._resolve_turn_tool_state(
            CHAT_ID, lore_enabled=False, image_enabled=False)
        assert slim.search_available is False
        assert "web_search" not in slim.capabilities
        assert "chat_history" in slim.capabilities

    @pytest.mark.asyncio
    async def test_turn_request_binds_runtime_state_before_planner_call(
            self, monkeypatch):
        """Один и тот же runtime-снимок доезжает до РЕАЛЬНОГО planner'а.

        Порядок связан не docstring'ом: `_build_turn_request` кладёт tool-state
        в `TurnRequest`, `_execute_turn` фиксирует этот req в трассе ДО вызова
        L1, и fake-LLM внутри planner'а проверяет, что видит именно этот req.
        """
        from services import direct_chat_service as dcs_mod
        from services import direct_l1 as l1_mod
        from tests.test_direct_chat import FakeLLM, FakeMemory, _make_service

        service = _make_service(memory=FakeMemory(window=[]), llm=FakeLLM())

        async def _slim(_chat_id, _lore=False, _image=False):
            return [{"function": {"name": "get_recent_history"}}]

        monkeypatch.setattr(dcs_mod, "active_tools_for_chat", _slim)
        slot_meta = _tt.SlotBudgetMeta(budget_tokens=1000,
                                       credential_source="global")
        req = await service._build_turn_request(
            trigger_type="direct", chat_id=CHAT_ID,
            correlation_id="corr-turn-request", slot_meta=slot_meta,
            lore_enabled=False, image_enabled=False)
        assert req.tool_state.search_available is False
        assert "web_search" not in req.capabilities
        assert req.capabilities == req.tool_state.capabilities

        captured: dict = {}
        real_trace = l1_mod.record_turn_trace

        def _trace(turn_req, policy=None):
            captured["req"] = turn_req
            return real_trace(turn_req, policy=policy)

        monkeypatch.setattr(l1_mod, "record_turn_trace", _trace)

        plan_json = json.dumps({
            "action": "reply", "reaction": None, "response_act": "answer",
            "extent": "auto", "tone": "inherit",
            "emotional_mirroring": "none", "structure": "chat",
            "delivery_hint": "plain", "tool_policy": "none",
            "capabilities_needed": [], "needs_clarification": False,
            "clarification_target": None, "confidence": 0.9,
            "knowledge_origin": "conversation_only",
            "search_intent": "not_applicable"}, ensure_ascii=False)

        class _PlannerLLM:
            def __init__(self):
                self.calls = 0

            async def generate(self, messages, **kw):
                self.calls += 1
                assert captured.get("req") is req, (
                    "planner вызван до фиксации TurnRequest")
                assert captured["req"].tool_state.search_available is False
                assert "web_search" not in captured["req"].capabilities
                return plan_json

        llm = _PlannerLLM()
        service.llm = llm
        plan, _meta = await service._execute_turn(
            req, slot=SimpleNamespace(dedicated=False, model="",
                                      base_url=""),
            l1_messages=[{"role": "user", "content": "вопрос"}],
            l1_input_chars=6, meta={}, started_monotonic=None)
        assert llm.calls == 1
        assert plan is not None
        assert captured["req"] is req


# ═══ UR-03.1: одна ToolEvidence: dedup/ошибки/источник/время/trace ═════════


_EXPECTED_EVENT_KEYS = {
    "round", "tool", "status", "error_code", "error_type", "duplicate",
    "attempt", "duration_ms", "out_chars", "truncated", "metered"}


class TestOneToolEvidenceStructure:
    @pytest.mark.asyncio
    async def test_success_keeps_sources_events_and_trace_in_one_evidence(self):
        search = _SearchProvider(
            "Результаты поиска:\nЗаголовок\nhttps://example.com/a")
        plan = _plan(knowledge_origin="open_world")
        result = await _run_tool_phase(plan, "проверь курс биткоина", search)
        ev = result.evidence

        assert ev.search_called is True
        assert ev.search_status == _dx.SEARCH_STATUS_OK
        assert ev.source_ids
        assert ev.source_count == len(ev.source_ids) == len(ev.sources)
        assert tuple(s.source_id for s in ev.sources) == ev.source_ids
        assert all(ev.full_text(s.content_ref).strip() for s in ev.sources)
        assert ev.tool_trace and ev.tool_events

        # Проекция — из фактического журнала, без data/args/URLs.
        assert len(ev.tool_events) == len(result.raw.tool_results)
        row = result.raw.tool_results[0]
        event = ev.tool_events[0]
        assert set(event) == _EXPECTED_EVENT_KEYS
        assert event["round"] == int(row["round"])
        assert event["tool"] == row["tool"] == "execute_web_search"
        assert event["status"] == row["status"] == "ok"
        assert event["error_code"] == "" and event["error_type"] == ""
        assert event["duplicate"] is False
        assert event["attempt"] == int(row["attempt"]) == 1
        assert event["duration_ms"] == int(row["duration_ms"] or 0) >= 0
        assert event["out_chars"] == int(row["out_chars"]) > 0
        assert "data" not in event and "args_fingerprint" not in event
        assert ev.tool_trace[0]["tool"] == "execute_web_search"
        assert ev.tool_trace[0]["ok"] is True

    @pytest.mark.asyncio
    async def test_duplicate_call_projected_as_duplicate_in_same_evidence(
            self, monkeypatch):
        """Второй идентичный вызов не диспетчится и виден как duplicate."""
        search = _SearchProvider(
            "Результаты поиска:\nЗаголовок\nhttps://example.com/a")
        plan = _plan(knowledge_origin="open_world")
        step = {"step_id": "first", "tool": "execute_web_search",
                "arguments": {"query": "биткоин"}, "depends_on": [],
                "failure_policy": "optional"}
        second = dict(step, step_id="second", depends_on=["first"])

        monkeypatch.setattr(
            _dx, "derive_simple_steps",
            lambda *a, **kw: ([dict(step), dict(second)], []))
        raw = await _dx.run_simple_tools(
            plan=plan, router=_router(search),
            ctx=ToolContext(CHAT_ID, "биткоин"), query="биткоин",
            chat_id=CHAT_ID, correlation_id=CORRELATION,
            announced=("execute_web_search",))

        assert raw is not None
        assert search.queries == ["биткоин"], "дубль сходил в провайдер"
        assert len(raw.tool_results) == 2
        first_row, duplicate_row = raw.tool_results
        assert first_row["duplicate"] is False
        assert duplicate_row["duplicate"] is True
        assert duplicate_row["attempt"] == first_row["attempt"] + 1
        assert duplicate_row["status"] == first_row["status"] == "ok"
        assert duplicate_row["out_chars"] == first_row["out_chars"]
        # Дубль отдаётся из кэша: времени нового вызова у него нет.
        assert duplicate_row["duration_ms"] == 0

        ev = _evidence_from(raw, plan=plan, query="биткоин")
        assert len(ev.tool_events) == 2
        assert ev.tool_events[0]["duplicate"] is False
        assert ev.tool_events[1]["duplicate"] is True
        assert ev.tool_events[1]["attempt"] == 2
        assert ev.tool_events[1]["status"] == "ok"
        assert ev.source_ids
        assert set(ev.source_ids) == {ev.sources[0].source_id}
        assert len(ev.tool_trace) == 2
        # Наблюдение UR-03.1 (не блокер строки): cached-дубль всё ещё
        # добавляет EvidenceSource, поэтому `source_ids` содержит повторы
        # одного id. Живая деривация шагов (`derive_simple_steps`) дублей не
        # порождает — путь защитный; follow-up, если деривация изменится.

    @pytest.mark.asyncio
    async def test_error_event_carries_code_type_and_time(self, monkeypatch):
        search = _SearchProvider(exc=AllSearchEnginesFailedException("quota"))
        plan = _plan(knowledge_origin="open_world")
        step = {"step_id": "search", "tool": "execute_web_search",
                "arguments": {"query": "курс биткоина"}, "depends_on": [],
                "failure_policy": "optional"}

        monkeypatch.setattr(_dx, "derive_simple_steps",
                            lambda *a, **kw: ([dict(step)], []))
        raw = await _dx.run_simple_tools(
            plan=plan, router=_router(search),
            ctx=ToolContext(CHAT_ID, "курс биткоина"),
            query="курс биткоина", chat_id=CHAT_ID,
            correlation_id=CORRELATION, announced=("execute_web_search",))
        assert raw is not None
        assert len(search.queries) == 1

        ev = _evidence_from(raw, plan=plan, query="курс биткоина")
        assert ev.search_called is True
        assert ev.search_status == _dx.SEARCH_STATUS_UNAVAILABLE
        assert ev.source_ids == () and ev.source_count == 0
        event = ev.tool_events[0]
        assert event["status"] == "error"
        assert event["duplicate"] is False
        assert event["error_code"] == "tool_error"
        assert "поиск недоступен" in event["error_type"]
        assert event["duration_ms"] >= 0
        assert event["out_chars"] > 0
        assert ev.tool_trace and ev.tool_trace[0]["ok"] is False
        assert ev.claim_policy != "claim_allowed"


# ═══ UR-04.3: L1 и L2 делят один набор источников в разных форматах ════════

# L1 печатает `[msg:<id>]`, канонический L2-рендер — `[tg:<tg_message_id>]`:
# это одна и та же реплика в РАЗНЫХ форматах стадий.
_L1_REF_RE = re.compile(r"\[msg:(\d+)\]")
_L2_REF_RE = re.compile(r"\btg:(\d+)")


def _rows(count: int = 6) -> list[dict]:
    return [{
        "id": index, "tg_message_id": index, "user_id": 10 + index % 2,
        "author_name": f"Вася{index % 2}", "text": f"реплика номер {index}",
        "timestamp": 100 + index, "media_type": "text", "reply_to_id": None,
    } for index in range(1, count + 1)]


def _materialize_l2(selection, rows):
    service = dcs.DirectChatService(None, None, None, _Aliases(),
                                    bot_id=BOT_UID)
    index = {f"msg:{row['tg_message_id']}": row for row in rows}

    def _render_row(frag, row):
        base = dict(row or {})
        base["text"] = frag.text
        return service._context_row_line(
            base, {}, trigger_message_id=None, projection=None,
            window_items=None)

    return dict(dcs._materialize_selection(
        selection, render_chain_line=lambda frag, source: "",
        render_row_line=_render_row, source_index=index))


class TestSharedL1L2SourceSet:
    @pytest.mark.asyncio
    async def test_l1_and_l2_project_same_source_refs_in_their_own_formats(
            self):
        rows = _rows()
        # L1 — компактная проекция окна на том же кандидатном наборе.
        l1_rows, l1_alloc = comp.allocate_window_projection(
            rows, budget_tokens=10 ** 6, fresh_count=3)
        l1_refs = {f.source_id for f in l1_alloc.fragments()
                   if f.source_id != "window:current"}
        l1_text = _l1.build_l1_context(
            query="что обсуждали?", window=l1_rows, budget_tokens=4000,
            with_ids=True, line_chars=0, preallocated=True)

        # L2 — единая selection из ТЕХ ЖЕ строк (живой producer).
        selection = dcs._build_l2_selection_candidates(
            current_text="что обсуждали?", window_rows=rows,
            working_window_messages=3, budget_tokens=0, allocate=False,
            preserve_projections=True)
        l2_window_refs = {
            f.source_id for f in
            (list(selection.fresh_neighbours) + list(selection.background))
            if f.source_id.startswith("msg:")}
        blocks = _materialize_l2(selection, rows)
        l2_text = blocks["global"]

        # Один и тот же набор выбранных источников.
        assert l1_refs == l2_window_refs == {
            f"msg:{row['tg_message_id']}" for row in rows}
        assert set(_L1_REF_RE.findall(l1_text)) == \
            set(_L2_REF_RE.findall(l2_text))
        assert set(_L1_REF_RE.findall(l1_text)) == {
            str(row["tg_message_id"]) for row in rows}

        # Разные форматы: L1 — секции/строки, L2 — канонический XML-блок.
        assert "[ПОСЛЕДНИЕ СООБЩЕНИЯ]" in l1_text
        assert "<Global_Context>" not in l1_text
        assert "<Global_Context>" in l2_text
        assert "[ПОСЛЕДНИЕ СООБЩЕНИЯ]" not in l2_text

        # Объём не форсируется общим: у стадий независимые бюджеты.
        assert l1_alloc.provenance.budget_tokens == 10 ** 6
        assert selection.provenance.budget_tokens == 0
        assert l1_text != l2_text
