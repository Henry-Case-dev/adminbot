"""SELF-DIAG-01 corrective (13.11.2026) — исследовательский чекап и продолжение.

Проверяется НАБЛЮДАЕМОЕ поведение, а не наличие классов/схем:

* explicit-чекап реально проходит через существующий tool-loop: модель
  запросила `read_source_code`/`inspect_runtime` → ToolRouter выполнил их →
  результат вернулся модели для синтеза (owner §3);
* структурированное решение `diagnostic_research` разбирается/валидируется, а
  `target=self` разрешает канонический repo без ссылки от пользователя
  (owner §2/§4);
* доставленный отчёт чекапа становится полноценным контекстом продолжения
  (структурный output_kind ledger'а, без разбора слов);
* при отказе L1 уже установленное решение сохраняется ТОЛЬКО для ответа на
  сообщение бота, инструменты автоматически не запускаются (owner §5);
* RBAC/deny применяется до выполнения инструмента; отрицательные смысловые
  кейсы (needed=false) не запускают чтение кода.

Тестовые фразы живут исключительно в этом файле и НЕ попадают в runtime.
Сеть/БД/Telegram не используются: LLM/reader/diagnostics — детерминированные
двойники, роутер/цикл — реальные.
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import direct_capabilities as caps
from services import direct_l1 as l1
from services import diagnostic_policy as diag
from services import source_reader as sr
from services import tool_schemas
from services.checkup_prompts import CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM
from services.checkup_service import CheckupService
from services.llm_client import LLMBadResponseError, LLMChatResult, LLMToolCall
from services.tool_router import ToolContext, ToolDeps, ToolRouter

CHAT_ID = -1009876543210
REPO = "Henry-Case-dev/adminbot"
DEPLOYED = "a" * 40
CHECKOUT = "b" * 40


class _ScriptedLLM:
    """По одному `LLMChatResult` на вызов `generate_chat`, последний — финал."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0
        self.messages = []

    async def generate_chat(self, messages, *, tools=None, **kwargs):
        self.calls += 1
        self.messages = copy.deepcopy(messages)
        return self._results.pop(0)

    async def generate(self, messages, **kwargs):  # pragma: no cover - не должен
        raise AssertionError("single generate не должен вызываться при tool-loop")


def _tc(call_id, name, args):
    return LLMToolCall(id=call_id, name=name, arguments=json.dumps(args))


class _FakeReader:
    def __init__(self):
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(dict(kwargs))
        snippet = "def checkup():\n    return 'ok'\n"
        return {
            "status": "ok", "verified": True, "verified_url":
                f"https://github.com/{REPO}/blob/{DEPLOYED}/services/checkup_service.py",
            "snippet": snippet, "snippet_chars": len(snippet),
            "read_level": "selected", "file_total_lines": 2,
            "line_range": [1, 2], "path": kwargs.get("path") or "",
            "repo": REPO, "ref": kwargs.get("ref") or "",
            "commit": kwargs.get("ref") or DEPLOYED,
            "provider": "github", "host": "github.com",
            "source_id": "src:test", "provenance": {"sha256": "x"},
            "truncation": {}, "network_calls": 1,
        }


class _FakeDiagnostics:
    limits = SimpleNamespace(max_output_chars=8000)

    def __init__(self):
        self.requests = []

    async def collect(self, request):
        self.requests.append(request)
        page = {
            "schema": "self-diag-01/d3-bundle-v1", "status": "ok",
            "probe": request.probe, "sources": [], "not_checked": [],
            "access": {"chat_id": request.chat_id},
        }
        return SimpleNamespace(), page


def _deps(*, reader=None, diagnostics=None):
    return ToolDeps(
        search=MagicMock(), memory=MagicMock(), aliases=None,
        source_reader=reader, diagnostics=diagnostics)


def _diag_ctx():
    return {
        "target": "self", "repo": REPO, "ref": DEPLOYED,
        "ref_source": "deployed_sha", "deployed_sha": DEPLOYED,
        "checkout_sha": CHECKOUT, "deployed_matches_checkout": False,
        "local_source_verification": "verified", "dirty": False,
        "conflict": [], "identity_error": "", "note": "",
    }


def _allow_policy(monkeypatch):
    """Разрешить диагностические инструменты (RBAC проверяется отдельно)."""
    async def _allow(*args, **kwargs):
        return MagicMock(allowed=True, reason_code="allowed_public_class_default",
                         message_ru="", effect="allow", capability="",
                         role="project_owner", matrix_role="global_admin",
                         data_class="PUBLIC_TECH", source="default")
    monkeypatch.setattr(diag, "check_tool_call", _allow)


# ── 1. Структурированное решение: разбор/валидация, без слов ────────────────

class TestDiagnosticDecisionNormalization:
    def test_valid_self_decision(self):
        plan = l1.normalize_l1_plan({
            "action": "reply",
            "diagnostic_research": {
                "needed": True, "target": "self",
                "sources": ["source_code", "runtime", "bogus_source"],
            },
        })
        assert plan is not None
        decision = plan.diagnostic_research
        assert decision.needed is True
        assert decision.target == "self"
        assert decision.sources == ("source_code", "runtime")
        assert l1.diagnostic_source_capabilities(plan) == (
            "source_code", "deep_diagnostics")

    def test_absent_invalid_and_false_do_not_start_research(self):
        for raw in ({}, {"diagnostic_research": None},
                    {"diagnostic_research": {"needed": "true",
                                             "target": "self"}}):
            plan = l1.normalize_l1_plan({"action": "reply", **raw})
            assert plan is not None
            assert l1.diagnostic_source_capabilities(plan) == ()

    def test_unknown_target_and_sources_are_honest(self):
        plan = l1.normalize_l1_plan({
            "action": "reply",
            "diagnostic_research": {
                "needed": True, "target": "outer-space",
                "sources": ["source_code", "not_a_source"]},
        })
        assert plan.diagnostic_research.target == "unknown"
        assert plan.diagnostic_research.sources == ("source_code",)
        # unknown target не запускает инструмент, даже если sources валидны.
        assert l1.diagnostic_source_capabilities(plan) == ()
        other = l1.normalize_l1_plan({
            "action": "reply",
            "diagnostic_research": {"needed": True, "target": "other",
                                    "sources": ["source_code"]}})
        assert l1.diagnostic_source_capabilities(other) == ()

    def test_negative_lexical_text_alone_never_adds_capabilities(self):
        """Похожая лексика без решения модели — никаких диагностических caps."""
        plan = l1.fallback_plan("разберись пожалуйста почему падает и посмотри код")
        assert l1.diagnostic_source_capabilities(plan) == ()
        assert plan.capabilities_needed == ()

    def test_preserved_only_for_reply_to_bot(self):
        previous = {
            "diagnostic_needed": True, "diagnostic_target": "self",
            "diagnostic_sources": "source_code",
        }
        assert l1.preserved_diagnostic_research(
            previous, reply_to_bot=False) is None
        kept = l1.preserved_diagnostic_research(previous, reply_to_bot=True)
        assert kept is not None and kept.needed and kept.target == "self"
        assert l1.preserved_diagnostic_research(
            {"diagnostic_needed": False}, reply_to_bot=True) is None


# ── 2. Checkup research loop: реальные вызовы инструментов ─────────────────

class TestCheckupResearchLoop:
    @pytest.mark.asyncio
    async def test_model_decides_and_tool_results_return_to_llm(
            self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _FakeReader()
        diagnostics = _FakeDiagnostics()
        router = ToolRouter(_deps(reader=reader, diagnostics=diagnostics))
        ctx = ToolContext(CHAT_ID, "", user_id=1,
                          correlation_id="checkup:test")
        ctx.diagnostic_research = _diag_ctx()
        schemas = caps.schemas_for_names(
            ["read_source_code", "inspect_runtime"],
            tool_schemas.active_tools(False, False))
        llm = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=[
                _tc("c1", "read_source_code",
                    {"operation": "read", "path": "services/checkup_service.py"}),
                _tc("c2", "inspect_runtime",
                    {"area": "logs", "probe": "logs.window",
                     "scope": "instance"}),
            ], finish_reason="tool_calls"),
            LLMChatResult(content="Причина подтверждена кодом.",
                          tool_calls=None, finish_reason="stop"),
        ])
        telemetry: dict = {}
        service = CheckupService(llm)
        report = await service.checkup(
            "ERROR boom", used_fallback=False, telemetry=telemetry,
            tool_runtime={"router": router, "ctx": ctx, "schemas": schemas,
                          "correlation_id": "checkup:test"})
        assert report == "Причина подтверждена кодом."
        # Модель реально получила схемы и результаты инструментов.
        assert {t["function"]["name"] for t in schemas} == {
            "read_source_code", "inspect_runtime"}
        tool_messages = [m for m in llm.messages if m.get("role") == "tool"]
        assert len(tool_messages) == 2
        assert "def checkup()" in tool_messages[0]["content"]
        assert '"status": "ok"' in tool_messages[1]["content"]
        # repo/ref подставлены из структурированного target=self.
        assert len(reader.calls) == 1
        assert reader.calls[0]["repo"] == REPO
        assert reader.calls[0]["ref"] == DEPLOYED
        assert len(diagnostics.requests) == 1
        # Телеметрия — факты вызовов, без текстов.
        assert telemetry["research_calls"] == 2
        assert "read_source_code" in telemetry["research_tools"]
        assert "inspect_runtime" in telemetry["research_tools"]

    @pytest.mark.asyncio
    async def test_no_research_when_decision_not_needed(self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _FakeReader()
        router = ToolRouter(_deps(reader=reader))
        ctx = ToolContext(CHAT_ID, "", user_id=1)
        schemas = caps.schemas_for_names(
            ["read_source_code", "inspect_runtime"],
            tool_schemas.active_tools(False, False))
        llm = _ScriptedLLM([
            LLMChatResult(content="Данных уже достаточно.", tool_calls=None,
                          finish_reason="stop")])
        service = CheckupService(llm)
        report = await service.checkup(
            "logs", used_fallback=False,
            tool_runtime={"router": router, "ctx": ctx, "schemas": schemas,
                          "correlation_id": "checkup:test2"})
        assert report.startswith("Данных уже")
        assert reader.calls == []
        # Если модель не вызвала tools, это не ошибка: один финальный раунд.
        assert llm.calls == 1

    @pytest.mark.asyncio
    async def test_external_target_does_not_substitute_self_repo(
            self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _FakeReader()
        router = ToolRouter(_deps(reader=reader))
        ctx = ToolContext(CHAT_ID, "", user_id=1)
        # target=external: серверная self-identity не подставляется.
        out = await router.dispatch(
            "read_source_code", {"operation": "read",
                                 "path": "src/main.py"}, ctx)
        payload = json.loads(out)
        assert payload["status"] == "error"
        assert payload["reason"] == "no_url_no_repo_no_query"
        assert reader.calls == []


# ── 3. Продолжение разговора: отчёт чекапа — контекст, а не слова ───────────

class TestContinuationContext:
    def test_l1_context_contains_delivered_report_section(self):
        report = ("Проверил журнал и код: пустой ответ L1 приходит из "
                  "services/direct_chat_service.py, строка 7541.")
        context = l1.build_l1_context(
            query="почему это произошло?", diagnostic_report=report,
            budget_tokens=1600)
        assert l1.DIAGNOSTIC_REPORT_SECTION in context
        assert "services/direct_chat_service.py" in context

    @pytest.mark.asyncio
    async def test_recent_checkup_report_uses_structural_output_kind(self):
        from services.direct_chat_service import DirectChatService

        class _Db:
            async def list_bot_outputs_between(self, chat_id, *, since_ts=0,
                                               until_ts=0, limit=200,
                                               kinds=None):
                assert kinds == ("checkup_report",)
                return [{
                    "output_id": 1, "chat_id": chat_id,
                    "tg_message_id": 77, "content_text": "ОТЧЁТ ЧЕКАПА",
                    "sent_at": int(__import__("time").time()),
                    "source_feature": "checkup", "output_kind":
                        "checkup_report", "revision_no": 1,
                }]

        service = DirectChatService.__new__(DirectChatService)
        service.db = _Db()
        report = await service._recent_checkup_report(CHAT_ID)
        assert report == "ОТЧЁТ ЧЕКАПА"

    def test_stale_or_missing_report_is_not_injected(self):
        context = l1.build_l1_context(query="привет")
        assert l1.DIAGNOSTIC_REPORT_SECTION not in context


# ── 4. L1 outage: сохранение установленного решения без автозапуска ────────

class TestL1OutageDegradation:
    def test_preserved_decision_announces_tools_but_runs_nothing(self):
        previous = {"diagnostic_needed": True,
                    "diagnostic_target": "self",
                    "diagnostic_sources": "source_code"}
        kept = l1.preserved_diagnostic_research(previous, reply_to_bot=True)
        plan = l1.fallback_plan("продолжай", diagnostic_research=kept)
        assert plan.source == "fallback"
        # Инструменты лишь объявлены; ни один вызов не сформирован кодом.
        assert l1.diagnostic_source_capabilities(plan) == ("source_code",)
        assert plan.capabilities_needed == ()

    def test_no_preservation_without_structural_continuation(self):
        previous = {"diagnostic_needed": True,
                    "diagnostic_target": "self",
                    "diagnostic_sources": "source_code"}
        assert l1.preserved_diagnostic_research(previous,
                                               reply_to_bot=False) is None
        plan = l1.fallback_plan("продолжай")
        assert l1.diagnostic_source_capabilities(plan) == ()

    def test_l1_empty_content_is_part_of_existing_ladder(self):
        """LLMBadResponseError наследует LLMError → ловит существующая
        лестница слот→main; отдельного классификатора/цикла не появляется."""
        assert issubclass(LLMBadResponseError, Exception)
        from services import llm_client
        assert issubclass(LLMBadResponseError, llm_client.LLMError)


# ── 5. RBAC: отказ политики ДО выполнения, без утечки результата ───────────

class TestRbacBeforeExecution:
    @pytest.mark.asyncio
    async def test_denied_tool_is_not_executed(self, monkeypatch):
        async def _deny(*args, **kwargs):
            return MagicMock(allowed=False, reason_code="denied_by_class_default",
                             message_ru="нет прав", effect="deny",
                             capability="source_code", role="member",
                             matrix_role="user", data_class="PROMPT_CONTENT",
                             source="default")
        monkeypatch.setattr(diag, "check_tool_call", _deny)
        reader = _FakeReader()
        router = ToolRouter(_deps(reader=reader))
        ctx = ToolContext(CHAT_ID, "", user_id=5)
        ctx.diagnostic_research = _diag_ctx()
        out = await router.dispatch(
            "read_source_code",
            {"operation": "read", "path": "services/checkup_service.py"}, ctx)
        assert "нет прав" in out
        assert reader.calls == []                  # инструмент не выполнялся


# ── 6. Схемы инструментов реально объявляются модельному циклу ─────────────

@pytest.mark.asyncio
async def test_structured_decision_announces_existing_tool_schemas():
    """needed=false → диагностических схем нет; needed=true,target=self →
    ровно существующие `read_source_code`/`inspect_runtime` (не новый агент)."""
    from services.direct_chat_service import DirectChatService

    service = DirectChatService.__new__(DirectChatService)
    base = l1.normalize_l1_plan({"action": "reply", "confidence": 0.9})
    schemas, _ = await service._l1_tool_subset(
        CHAT_ID, "corr", False, False, base)
    names = {s["function"]["name"] for s in schemas}
    assert "read_source_code" not in names
    assert "inspect_runtime" not in names

    decided = l1.normalize_l1_plan({
        "action": "reply", "confidence": 0.9,
        "diagnostic_research": {"needed": True, "target": "self",
                                "sources": ["source_code", "runtime"]},
    })
    schemas, rejected = await service._l1_tool_subset(
        CHAT_ID, "corr", False, False, decided)
    names = {s["function"]["name"] for s in schemas}
    assert names == {"read_source_code", "inspect_runtime"}
    assert rejected == ()


@pytest.mark.asyncio
async def test_tool_phase_forces_adaptive_only_for_structured_decision(
        monkeypatch):
    """Typed decision исполняется adaptive-контуром; без решения — как было."""
    from services import direct_chat_service as dcs

    seen = {}

    async def _capture(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(raw=None)

    monkeypatch.setattr(dcs._dx, "run_tool_phase", _capture)
    svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
    svc.tool_router = object()
    svc.llm = MagicMock()
    schemas = caps.schemas_for_names(
        ["read_source_code", "inspect_runtime"],
        tool_schemas.active_tools(False, False))
    plan = l1.normalize_l1_plan({
        "action": "reply", "confidence": 0.9,
        "diagnostic_research": {"needed": True, "target": "self",
                                "sources": ["source_code", "runtime"]},
    })
    await svc._l1_tool_phase(
        None, ToolContext(CHAT_ID, ""), query="продолжай", lore_enabled=False,
        image_enabled=False, temperature=None, chat_id=CHAT_ID,
        correlation_id="corr", l1_plan=plan, response_plan=None,
        fallback_meta={}, time_line="", tool_schemas=schemas)
    assert seen["plan"].execution_mode == "adaptive"
    assert {"source_code", "deep_diagnostics"} <= set(seen["required_caps"])

    seen.clear()
    plain = l1.normalize_l1_plan({"action": "reply", "confidence": 0.9})
    await svc._l1_tool_phase(
        None, ToolContext(CHAT_ID, ""), query="привет", lore_enabled=False,
        image_enabled=False, temperature=None, chat_id=CHAT_ID,
        correlation_id="corr", l1_plan=plain, response_plan=None,
        fallback_meta={}, time_line="", tool_schemas=schemas)
    assert seen["plan"].execution_mode != "adaptive"


def test_checkup_addendum_only_with_tools(monkeypatch):
    """Функциональная директива не подмешивается в офлайн/без-tools путь."""
    import asyncio

    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr("services.checkup_service.speech_owner_block", _noop)
    llm = MagicMock()
    llm.generate = AsyncMock(return_value="отчёт")
    service = CheckupService(llm)
    # Без tool_runtime — канон байт-в-байт, директивы инструментов нет.
    asyncio.run(service.checkup("logs", used_fallback=False))
    system = llm.generate.await_args.args[0][0]["content"]
    assert CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM not in system


@pytest.mark.asyncio
async def test_handler_builds_existing_router_runtime(monkeypatch):
    """Handler отдаёт сервису ТОТ ЖЕ роутер и реальный principal."""
    from handlers import checkup as cm

    monkeypatch.setattr(cm, "_tool_router", ToolRouter(_deps()))
    monkeypatch.setattr(sr, "resolve_self_repo_identity", _diag_ctx)
    runtime = await cm._build_checkup_tool_runtime(
        CHAT_ID, 777, None, "checkup:handler")
    assert runtime is not None
    names = {s["function"]["name"] for s in runtime["schemas"]}
    assert names == {"read_source_code", "inspect_runtime"}
    assert runtime["ctx"].user_id == 777
    assert runtime["ctx"].diagnostic_research["target"] == "self"


@pytest.mark.asyncio
async def test_handler_persists_delivered_report_as_conversation(monkeypatch):
    """Доставленный отчёт пишется существующим ledger как checkup_report."""
    from handlers import checkup as cm
    from services import bot_output_ledger as ledger

    calls = []

    class _Db:
        async def upsert_bot_reply(self, *args):
            calls.append(("reply", args))

        async def set_bot_reply_parent(self, *args):
            calls.append(("parent", args))

    async def _record(db, **kwargs):
        calls.append(("ledger", kwargs))
        return 1

    monkeypatch.setattr(cm, "_service", SimpleNamespace(db=_Db()))
    monkeypatch.setattr(ledger, "record_delivered_output", _record)
    await cm._persist_checkup_conversation(
        chat_id=CHAT_ID, sent_id=55, report="ОТЧЁТ", parent_id=44,
        correlation_id="checkup:x", bot=SimpleNamespace(id=9))
    ledger_calls = [c for c in calls if c[0] == "ledger"]
    assert ledger_calls and ledger_calls[0][1]["output_kind"] == "checkup_report"
    assert any(c[0] == "reply" for c in calls)


# ── 7. Реальный Direct L1: дополнение схемы и сохранение при outage ───────

@pytest.mark.asyncio
async def test_direct_l1_addendum_and_outage_keeps_previous_decision(
        monkeypatch):
    """L1 пустой ответ → plan None, но предыдущее решение не потеряно.

    Проверяется фактический `_plan_direct_l1` (резолв промпта/слота/рендера
    контекста), а не только helper. Второго классификатора/цикла нет.
    """
    from services import direct_chat_service as dcs
    from services import hot_config as hot
    from services import chat_params
    from services import prompt_composer as pc
    from services.summary_aliases import AliasResolver

    class _StubLLM:
        def __init__(self):
            self.captured = []

        async def generate(self, messages, **kwargs):
            self.captured.append({"step": kwargs.get("step"),
                                  "messages": [dict(m) for m in messages]})
            raise LLMBadResponseError("empty content")

    class _Stub:
        _render_current_question = dcs.DirectChatService._render_current_question
        _l1_speech_hints = dcs.DirectChatService._l1_speech_hints
        _build_speech_understanding = \
            dcs.DirectChatService._build_speech_understanding
        _attach_l1_plan_meta = dcs.DirectChatService._attach_l1_plan_meta
        _compose_speech_system = dcs.DirectChatService._compose_speech_system
        _resolve_turn_slot_meta = dcs.DirectChatService._resolve_turn_slot_meta
        _resolve_turn_tool_state = \
            dcs.DirectChatService._resolve_turn_tool_state
        _turn_aliases_snapshot = dcs.DirectChatService._turn_aliases_snapshot
        _build_reply_parent_ref = \
            dcs.DirectChatService._build_reply_parent_ref
        _build_turn_request = dcs.DirectChatService._build_turn_request
        _execute_turn = dcs.DirectChatService._execute_turn
        _recent_checkup_report = dcs.DirectChatService._recent_checkup_report

        def _l1_reply_block(self, message, budget_tokens=None):
            return dcs.DirectChatService._l1_reply_block(
                self, message, budget_tokens=budget_tokens)

        async def _history_partial(self, chat_id, window):
            return False

        def __init__(self, llm):
            self.llm = llm
            self.memory = type("M", (), {
                "get_window_messages": staticmethod(lambda chat_id: _empty())})()
            self.db = None
            self.bot_id = 999
            self.aliases = AliasResolver({})

    async def _empty():
        return []

    message = type("M", (), {
        "text": "продолжи разбор", "caption": None, "message_id": 2,
        "chat": type("C", (), {"type": "supergroup"})(),
        "reply_to_message": None, "from_user": None})()

    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    # Уже установленное решение предыдущего диагностического хода.
    l1.record_l1_diagnostics(
        CHAT_ID, diagnostic_needed=True, diagnostic_target="self",
        diagnostic_sources="source_code")
    llm = _StubLLM()
    plan, meta = await dcs.DirectChatService._plan_direct_l1(
        _Stub(llm), CHAT_ID, message, "продолжи разбор", None,
        bundle=None, target_name="Аня", user_id=None,
        character_block="", character_ctx=None, lore_enabled=False,
        image_enabled=False, force_required=False, reply_bot=False)
    assert plan is None
    assert meta["previous_diagnostic_research"]["diagnostic_needed"] is True
    # Схема L1 реально получила функциональное дополнение (в данных контекста;
    # системный канон не переписан).
    l1_user = [c["messages"][1]["content"] for c in llm.captured
               if c["step"] == "l1_planner"]
    assert l1_user and "diagnostic_research" in l1_user[0]

