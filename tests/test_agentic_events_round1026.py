"""A9 round1026 (`agentic-events-graph-round1026`, ADR-1026-22 D2/D5/D6/D7/D8/D9)
— тесты ядра: схема событий §49, R17-whitelist, fail-open эмиссия,
9 §51-этапов ExecutionGraph, честные метрики (no-fake-tokens),
silent-no-verbalizer, OFF-паритет, границы.

Автор: @Builder (A9, Step 3, T-3698/T-3699).
"""
import logging
from pathlib import Path

import pytest

from config.settings import Settings
from services import agentic_events as ae
from services import execution_graph_source as egs
from web.api import analytics as analytics_mod

_ROOT = Path(__file__).resolve().parents[1]
_AGENTIC_SRC = (_ROOT / "services" / "agentic_events.py").read_text(
    encoding="utf-8")
_ANALYTICS_SRC = (_ROOT / "web" / "api" / "analytics.py").read_text(
    encoding="utf-8")
_SETTINGS_SRC = (_ROOT / "config" / "settings.py").read_text(encoding="utf-8")

CORE_12 = (
    "DECISION_START", "DECISION_COMPLETE", "TOOL_PLAN_CREATED",
    "TOOL_CALL_START", "TOOL_CALL_COMPLETE", "TOOL_CALL_FAILED",
    "REACTION_SENT", "MESSAGE_IGNORED", "IMAGE_CONTEXT_RESOLVED",
    "IMAGE_GENERATION_START", "IMAGE_GENERATION_COMPLETE",
    "IMAGE_GENERATION_FAILED",
)
ANTI_8 = (
    "ANTI_CLICHE_UPDATE_START", "ANTI_CLICHE_MODEL_REQUEST",
    "ANTI_CLICHE_MODEL_RESPONSE", "ANTI_CLICHE_PARSE_ERROR",
    "ANTI_CLICHE_DEDUP_COMPLETE", "ANTI_CLICHE_SAVE_COMPLETE",
    "ANTI_CLICHE_UPDATE_COMPLETE", "ANTI_CLICHE_UPDATE_FAILED",
)


@pytest.fixture(autouse=True)
def _clean_store():
    egs.reset()
    yield
    egs.reset()


# ── T-3691: закрытый enum + schema_version ─────────────────────────────────

class TestEventSchema:
    def test_core_12_present(self):
        assert len(ae.CORE_EVENT_TYPES) == 12
        for name in CORE_12:
            assert name in ae.AGENTIC_EVENT_TYPES

    def test_anti_cliche_8_included(self):
        assert len(ae.ANTI_CLICHE_EVENT_TYPES) == 8
        for name in ANTI_8:
            assert name in ae.AGENTIC_EVENT_TYPES

    def test_total_20_and_schema_version(self):
        assert len(ae.AGENTIC_EVENT_TYPES) == 20
        assert ae.SCHEMA_VERSION == "1"

    def test_closed_enum_unknown_event_dropped(self, caplog):
        with caplog.at_level(logging.INFO):
            ae.emit_agentic_event("NOT_AN_EVENT", run_id="r1")
        assert "NOT_AN_EVENT" not in caplog.text
        assert egs.get_agentic_events("r1") == []


# ── T-3692: эмиссия / fail-open / R17 ──────────────────────────────────────

class TestEmission:
    @pytest.mark.parametrize("event", CORE_12)
    def test_each_core_event_emitted_with_fields(self, event, caplog):
        with caplog.at_level(logging.INFO):
            ae.emit_agentic_event(
                event, run_id="run-1", chat_id=5, message_id=9,
                action="reply", reason="default", duration_ms=3)
        assert f"event={event}" in caplog.text
        stored = egs.get_agentic_events("run-1")
        assert stored and stored[-1]["event"] == event
        assert stored[-1]["schema_version"] == "1"
        assert stored[-1]["run_id"] == "run-1"

    def test_required_fields_types(self, caplog):
        with caplog.at_level(logging.INFO):
            ae.emit_agentic_event(
                "DECISION_COMPLETE", run_id="r1", chat_id=5, message_id=9,
                action="reply", reason="default", duration_ms=12)
        ev = egs.get_agentic_events("r1")[-1]
        assert ev["chat_id"] == 5
        assert ev["message_id"] == 9
        assert ev["action"] == "reply"
        assert ev["reason"] == "default"
        assert ev["duration_ms"] == 12
        assert ev["ts"] is not None

    def test_r17_forbidden_content_never_stored_or_logged(self, caplog):
        secret = "Досье: Иван Петров, промпт <system>"
        with caplog.at_level(logging.INFO):
            ae.emit_agentic_event(
                "DECISION_COMPLETE", run_id="r1",
                action=secret,                 # строка с пробелами/текстом
                reason="hello world",          # не reason_code
                prompt=secret,                 # ключ вне whitelist
                message_text=secret)           # ключ вне whitelist
        assert secret not in caplog.text
        ev = egs.get_agentic_events("r1")[-1]
        assert "prompt" not in ev
        assert "message_text" not in ev
        assert "action" not in ev
        assert "reason" not in ev

    def test_whitelist_drops_unknown_keys(self, caplog):
        with caplog.at_level(logging.INFO):
            ae.emit_agentic_event(
                "TOOL_CALL_COMPLETE", run_id="r1", tool="get_user_context",
                round=1, status="ok", out_chars=10, dossier="секрет")
        ev = egs.get_agentic_events("r1")[-1]
        assert ev["tool"] == "get_user_context"
        assert ev["out_chars"] == 10
        assert "dossier" not in ev

    def test_emit_never_raises_on_store_failure(self, monkeypatch, caplog):
        def _boom(*a, **k):
            raise RuntimeError("store down")
        monkeypatch.setattr(egs, "record_agentic_event", _boom)
        with caplog.at_level(logging.INFO):
            ae.emit_agentic_event("DECISION_START", run_id="r1")  # не бросает
        assert "event=DECISION_START" in caplog.text

    def test_no_run_id_no_graph_record_but_logged(self, caplog):
        with caplog.at_level(logging.INFO):
            ae.emit_agentic_event("DECISION_START", chat_id=1)
        assert "event=DECISION_START" in caplog.text
        assert egs.latest_run_id() is None

    def test_missing_fields_are_honest_none_not_invented(self, caplog):
        with caplog.at_level(logging.INFO):
            ae.emit_agentic_event("DECISION_START", run_id="r1")
        ev = egs.get_agentic_events("r1")[-1]
        assert "action" not in ev and "duration_ms" not in ev


# ── T-3700: kill-switch / OFF-паритет ──────────────────────────────────────

class TestKillSwitch:
    def test_settings_classvar_env_only(self):
        assert "AGENTIC_EVENTS_ENABLED" in _SETTINGS_SRC
        assert "AGENTIC_EVENTS_ENABLED: ClassVar[bool] = _env_bool(" \
            in _SETTINGS_SRC

    def test_off_zero_events(self, monkeypatch, caplog):
        monkeypatch.setattr(Settings, "AGENTIC_EVENTS_ENABLED", False)
        assert ae.agentic_events_enabled() is False
        with caplog.at_level(logging.INFO):
            ae.emit_agentic_event("DECISION_START", run_id="r1")
        assert "event=DECISION_START" not in caplog.text
        assert egs.get_agentic_events("r1") == []
        assert egs.latest_run_id() is None

    def test_on_default(self, monkeypatch):
        monkeypatch.setattr(Settings, "AGENTIC_EVENTS_ENABLED", True)
        assert ae.agentic_events_enabled() is True


# ── T-3693/T-3694: 9 этапов / честные метрики / silent ─────────────────────

class TestAgenticGraphStages:
    def test_nine_stage_kind_mapping(self):
        expected = {
            "decision": "algorithm", "memory_lookup": "tool", "rag": "tool",
            "web_extraction": "tool", "factcheck": "tool",
            "image_prompt": "algorithm", "image_generation": "tool",
            "reaction": "tool", "text_generation": "llm",
        }
        assert len(egs.AGENTIC_STAGE_ORDER) == 9
        for stage, kind in expected.items():
            assert egs.STEP_KIND[stage] == kind
            assert egs.STAGE_LABELS[stage]

    def test_kind_tool_constant_no_new_kind(self):
        assert egs.KIND_TOOL == "tool"
        assert egs.STEP_KIND["memory_lookup"] == egs.KIND_TOOL

    def _emit_all_stages(self, run_id="r1"):
        ae.emit_agentic_event(
            "DECISION_COMPLETE", run_id=run_id, action="reply",
            reason="default", duration_ms=4)
        for tool in ("get_user_context", "rag_search", "fetch_article",
                     "factcheck_text"):
            ae.emit_agentic_event(
                "TOOL_CALL_COMPLETE", run_id=run_id, tool=tool, round=1,
                status="ok", out_chars=5)
        ae.emit_agentic_event(
            "IMAGE_CONTEXT_RESOLVED", run_id=run_id, resolution="resolved",
            sources=["dossier"], facts=2, slice=1, prompt_chars=12,
            latency_ms=5)
        ae.emit_agentic_event(
            "IMAGE_GENERATION_COMPLETE", run_id=run_id, source="direct",
            duration_ms=9)
        ae.emit_agentic_event(
            "REACTION_SENT", run_id=run_id, outcome="ok", reaction="x",
            reason="emoji_reaction")

    def test_all_nine_stages_rendered(self):
        self._emit_all_stages()
        rows = [{"step": "stage1", "model": "m1", "input_tokens": 10,
                 "output_tokens": 5, "cost_usd": 0.001, "price_known": True}]
        graph = egs.build_graph("r1", egs.get_run("r1"), rows)
        assert [n["stageKey"] for n in graph["nodes"]] == list(
            egs.AGENTIC_STAGE_ORDER)
        assert len(graph["edges"]) == 8
        assert graph["empty"] is False

    def test_no_fake_tokens_for_algorithmic_nodes(self):
        self._emit_all_stages()
        rows = [{"step": "stage1", "model": "m1", "input_tokens": 10,
                 "output_tokens": 5, "cost_usd": 0.001, "price_known": True}]
        graph = egs.build_graph("r1", egs.get_run("r1"), rows)
        for node in graph["nodes"]:
            if node["stageKey"] == "text_generation":
                continue
            assert node["inputTokens"] is None, node["stageKey"]
            assert node["outputTokens"] is None, node["stageKey"]
            assert node["cost"] is None, node["stageKey"]
            assert node["priceKnown"] is False, node["stageKey"]

    def test_text_generation_carries_real_tokens_only(self):
        self._emit_all_stages()
        rows = [{"step": "stage1", "model": "m1", "input_tokens": 10,
                 "output_tokens": 5, "cost_usd": 0.001, "price_known": True}]
        graph = egs.build_graph("r1", egs.get_run("r1"), rows)
        tg = next(n for n in graph["nodes"]
                  if n["stageKey"] == "text_generation")
        assert tg["kind"] == "llm"
        assert tg["inputTokens"] == 10
        assert tg["outputTokens"] == 5
        assert tg["cost"] == 0.001
        assert tg["priceKnown"] is True

    def test_unknown_price_never_zero(self):
        self._emit_all_stages()
        rows = [{"step": "stage1", "input_tokens": 1, "output_tokens": 1,
                 "cost_usd": 0, "price_known": False}]
        graph = egs.build_graph("r1", egs.get_run("r1"), rows)
        tg = next(n for n in graph["nodes"]
                  if n["stageKey"] == "text_generation")
        assert tg["cost"] is None       # null ≠ $0
        assert tg["costCurrency"] is None

    def test_no_data_stage_no_node(self):
        ae.emit_agentic_event(
            "DECISION_COMPLETE", run_id="r1", action="reply",
            reason="default")
        graph = egs.build_graph("r1", egs.get_run("r1"), [])
        # Нет tool/image/reaction/LLM-данных → только Decision (§25/§30).
        assert [n["stageKey"] for n in graph["nodes"]] == ["decision"]

    def test_summary_graph_without_agentic_unchanged(self):
        snap = {"source_count": 10, "saved_count": 7,
                "filter_status": "ok"}
        graph = egs.build_graph("s1", snap, [])
        assert [n["stageKey"] for n in graph["nodes"]] == ["filter"]


class TestSilentNoVerbalizer:
    def test_silent_decision_without_text_generation(self):
        ae.emit_agentic_event(
            "DECISION_START", run_id="r1", chat_id=1, message_id=2)
        ae.emit_agentic_event(
            "DECISION_COMPLETE", run_id="r1", chat_id=1, message_id=2,
            action="silent", reason="not_addressed", duration_ms=1)
        ae.emit_agentic_event(
            "MESSAGE_IGNORED", run_id="r1", chat_id=1, message_id=2,
            action="silent", reason="not_addressed", target=2)
        graph = egs.build_graph("r1", egs.get_run("r1"), [])
        stages = [n["stageKey"] for n in graph["nodes"]]
        assert "decision" in stages
        assert "text_generation" not in stages      # фиктивного Вербализатора нет
        assert graph["nodes"][0]["metrics"]["action"] == "silent"

    def test_reaction_node_from_reaction_sent(self):
        ae.emit_agentic_event(
            "REACTION_SENT", run_id="r1", outcome="ok", reaction="x",
            reason="emoji_reaction")
        graph = egs.build_graph("r1", egs.get_run("r1"), [])
        assert [n["stageKey"] for n in graph["nodes"]] == ["reaction"]
        assert graph["nodes"][0]["kind"] == "tool"


# ── T-3691/T-3693: ANTI_CLICHE_* (enum/whitelist) без чат-графа ────────────

class TestAntiClicheEvents:
    def test_worker_event_logged_r17_safe_no_graph_node(self, caplog):
        with caplog.at_level(logging.INFO):
            ae.emit_agentic_event(
                "ANTI_CLICHE_UPDATE_START", capacity=10, per_run=5,
                model="test-model", source="wikipedia")
        assert "event=ANTI_CLICHE_UPDATE_START" in caplog.text
        assert "capacity=10" in caplog.text
        assert "per_run=5" in caplog.text
        assert "model=test-model" in caplog.text
        # нет run_id → чат-граф не трогается (D11).
        assert egs.latest_run_id() is None

    def test_worker_phrase_content_not_logged(self, caplog):
        with caplog.at_level(logging.INFO):
            ae.emit_agentic_event(
                "ANTI_CLICHE_DEDUP_COMPLETE", candidates=2, duplicates=1,
                phrase="секретная клишированная фраза")
        assert "секретная клишированная фраза" not in caplog.text
        assert "phrase" not in egs.get_agentic_events("")


# ── T-3695: API-поверхность (существующий endpoint, fail-open) ─────────────

class TestApiSurface:
    def test_existing_endpoint_only_no_second(self):
        assert _ANALYTICS_SRC.count(
            '@analytics_router.get("/analytics/execution/latest")') == 1
        assert "/analytics/agentic" not in _ANALYTICS_SRC

    def test_rbac_preserved(self):
        idx = _ANALYTICS_SRC.index(
            '@analytics_router.get("/analytics/execution/latest")')
        snippet = _ANALYTICS_SRC[idx:idx + 500]
        assert "requires_global_admin()" in snippet

    def test_execution_response_includes_agentic_nodes(self):
        ae.emit_agentic_event(
            "DECISION_COMPLETE", run_id="r1", action="reply",
            reason="default")
        ae.emit_agentic_event(
            "TOOL_CALL_COMPLETE", run_id="r1", tool="get_user_context",
            round=1, status="ok", out_chars=3)
        graph = analytics_mod._execution_response(
            "r1", egs.get_run("r1"), [])
        assert [n["stageKey"] for n in graph["nodes"]] == [
            "decision", "memory_lookup"]

    def test_fail_open_empty_shape(self):
        graph = analytics_mod._execution_response("", None, [])
        assert graph["nodes"] == [] and graph["empty"] is True
        assert "context" in graph["metrics"]

    def test_api_additive_no_required_new_fields(self):
        # Новых обязательных полей контракта нет: shape совместим.
        graph = analytics_mod._execution_response("", None, [])
        for key in ("run_id", "nodes", "edges", "metrics", "empty",
                    "publication_status"):
            assert key in graph


# ── T-3701: статические границы (аудит-diff вспомогательно) ────────────────

class TestBoundaries:
    def test_agentic_module_is_sync_fail_open(self):
        import asyncio
        assert not asyncio.iscoroutinefunction(ae.emit_agentic_event)
        assert not asyncio.iscoroutinefunction(egs.record_agentic_event)
        assert "except Exception" in _AGENTIC_SRC

    def test_single_store_no_second_analytics(self):
        # Второй event-store/модуль аналитики нет: события идут в существующий
        # execution_graph_source.
        assert "execution_graph_source" in _AGENTIC_SRC
        assert "record_agentic_event" in (
            _ROOT / "services" / "execution_graph_source.py").read_text(
            encoding="utf-8")

    def test_no_agentic_events_in_param_catalog(self):
        from services import param_catalog
        assert "AGENTIC_EVENTS_ENABLED" not in param_catalog.REGISTRY

    def test_timeout_free_emit_regex(self):
        # Значения-строки без пробелов: свободный текст не проходит.
        assert not ae._IDENT_RE.match("текст с пробелами")
        assert ae._IDENT_RE.match("reason_code_1")


# ── T-3693: точки эмиссии — image-путь / tool_loop / direct-чат ────────────

class TestImageEmissionPoint:
    @pytest.mark.asyncio
    async def test_image_path_events(self, monkeypatch):
        from services import image_generation as ig

        async def _fake(bot, chat_id, prompt, **kw):
            return ig.GenerationResult(ok=True, reason="", content=b"x")

        monkeypatch.setattr(ig, "generate_and_send", _fake)
        request = ig.build_image_request("direct", 5, "кот")
        result = await ig.run_image_request(request, correlation_id="r-img")
        assert result.ok
        names = [e["event"] for e in egs.get_agentic_events("r-img")]
        assert "IMAGE_CONTEXT_RESOLVED" in names
        assert "IMAGE_GENERATION_START" in names
        assert "IMAGE_GENERATION_COMPLETE" in names
        assert "IMAGE_GENERATION_FAILED" not in names

    @pytest.mark.asyncio
    async def test_image_failure_event(self, monkeypatch):
        from services import image_generation as ig

        async def _fake(bot, chat_id, prompt, **kw):
            return ig.GenerationResult(ok=False, reason="timeout")

        monkeypatch.setattr(ig, "generate_and_send", _fake)
        request = ig.build_image_request("tool", 5, "кот")
        result = await ig.run_image_request(request, correlation_id="r-img2")
        assert result.ok is False
        events = {e["event"]: e for e in egs.get_agentic_events("r-img2")}
        assert "IMAGE_GENERATION_FAILED" in events
        assert events["IMAGE_GENERATION_FAILED"]["reason_class"] == "timeout"


class TestToolLoopEmissionPoint:
    @pytest.mark.asyncio
    async def test_tool_events_emitted(self, monkeypatch):
        import services.tool_loop as tl
        from services.llm_client import LLMChatResult, LLMToolCall
        calls = []
        monkeypatch.setattr(
            tl, "emit_agentic_event",
            lambda event, **fields: calls.append((event, fields)))

        class _LLM:
            def __init__(self):
                self.n = 0
            async def generate_chat(self, messages, **kw):
                self.n += 1
                if self.n == 1:
                    return LLMChatResult(
                        content=None,
                        tool_calls=[LLMToolCall(
                            id="c1", name="get_user_context",
                            arguments="{}")],
                        finish_reason="tool_calls")
                return LLMChatResult(content="финал", tool_calls=None,
                                     finish_reason="stop")

        class _Router:
            async def dispatch(self, name, arguments, ctx):
                return "данные"

        result = await tl.chat_with_tools(
            _LLM(), [{"role": "user", "content": "hi"}], tools=[],
            router=_Router(), ctx=object(), correlation_id="r-tool",
            chat_id=1)
        assert str(result)
        names = [event for event, _ in calls]
        assert "TOOL_PLAN_CREATED" in names
        assert "TOOL_CALL_START" in names
        assert "TOOL_CALL_COMPLETE" in names
        plan = next(f for e, f in calls if e == "TOOL_PLAN_CREATED")
        # Спай видит сырые поля до whitelist-нормализации emit.
        assert plan["tools"] == ["get_user_context"]

    @pytest.mark.asyncio
    async def test_tool_failed_event(self, monkeypatch):
        import services.tool_loop as tl
        from services.llm_client import LLMChatResult, LLMToolCall
        calls = []
        monkeypatch.setattr(
            tl, "emit_agentic_event",
            lambda event, **fields: calls.append((event, fields)))

        class _LLM:
            def __init__(self):
                self.n = 0
            async def generate_chat(self, messages, **kw):
                self.n += 1
                if self.n == 1:
                    return LLMChatResult(
                        content=None,
                        tool_calls=[LLMToolCall(
                            id="c1", name="execute_web_search",
                            arguments="{}")],
                        finish_reason="tool_calls")
                return LLMChatResult(content="финал", tool_calls=None,
                                     finish_reason="stop")

        class _Router:
            async def dispatch(self, name, arguments, ctx):
                raise RuntimeError("tool down")

        await tl.chat_with_tools(
            _LLM(), [{"role": "user", "content": "hi"}], tools=[],
            router=_Router(), ctx=object(), correlation_id="r-tool2",
            chat_id=1)
        names = [event for event, _ in calls]
        assert "TOOL_CALL_FAILED" in names


class TestDirectChatEmissionPoint:
    @pytest.mark.asyncio
    async def test_silent_events(self, monkeypatch):
        import services.direct_chat_service as dcs
        from tests.test_decision_making_round1026 import _drive
        calls = []
        monkeypatch.setattr(
            dcs, "emit_agentic_event",
            lambda event, **fields: calls.append((event, fields)))
        svc, react, bot, msg, user = _drive(monkeypatch, "Ок")
        await svc.handle(bot, msg, user)
        names = [event for event, _ in calls]
        assert "DECISION_START" in names
        assert "DECISION_COMPLETE" in names
        assert "MESSAGE_IGNORED" in names
        done = next(f for e, f in calls if e == "DECISION_COMPLETE")
        assert done["action"] == "silent"

    @pytest.mark.asyncio
    async def test_react_event(self, monkeypatch):
        import services.direct_chat_service as dcs
        from tests.test_decision_making_round1026 import _drive
        calls = []
        monkeypatch.setattr(
            dcs, "emit_agentic_event",
            lambda event, **fields: calls.append((event, fields)))
        svc, react, bot, msg, user = _drive(monkeypatch, "АХАХА")
        await svc.handle(bot, msg, user)
        names = [event for event, _ in calls]
        assert "REACTION_SENT" in names
        assert "MESSAGE_IGNORED" not in names

