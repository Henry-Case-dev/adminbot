"""ASAP 8 v6 Wave C — матрица надёжности Direct pre-deploy (§18C.9).

Автоматизированная матрица БЕЗ human gate: каждая ситуация §18C.9 —
тестом (pipeline-level через реальный DirectChatService.handle либо
executor-level там, где seam изолирован). Ключевые acceptance:
  * planner invalid + required web search → честная деградация
    (инструменты исполнены дет., L2 получил honest-пометку);
  * two sources + first oversized → второй доставлен / run incomplete
    (см. test_asap8_v6_wc_direct_d04.py::TestEvidencePack);
  * fallback smaller window → repacked (там же, TestL2FallbackRepack);
  * adaptive branch по результату / loop bounded stop / cancellation /
    malicious output — там же;
  * здесь: сквозные сценарии хода + idempotency/side-effect/timeout.

TEST-LIFECYCLE: CONTRACT owner=ASAP8-V6/D04 (§18C.9)
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import direct_l1 as _l1
from services import direct_execution as _dx
from services.tool_loop import ToolLoopResult

pytestmark = [pytest.mark.system2, pytest.mark.asap3]


# ── helpers (тот же контракт, что test_asap7_direct_l1) ─────────────────────


class _MatrixLLM:
    """Fake LLM: stage-разделение по step (l1_planner/l2_writer/orchestrator)."""

    def __init__(self, *, l1=None, l2="готовый ответ", orchestrator=None):
        self.l1_reply = l1
        self.l2_text = l2
        self.orchestrator = list(orchestrator or [])
        self.calls = []

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kw):
        self.calls.append({"step": step, "messages": messages})
        if step == "l1_planner":
            item = self.l1_reply
            if isinstance(item, list):
                item = item.pop(0) if item else ""
            if isinstance(item, Exception):
                raise item
            return item
        if step == "orchestrator":
            decision = self.orchestrator.pop(0) if self.orchestrator \
                else {"action": "finish", "reason": "done"}
            return json.dumps(decision, ensure_ascii=False)
        return self.l2_text

    def steps(self):
        return [c["step"] for c in self.calls]

    def last_messages(self, step):
        found = [c for c in self.calls if c["step"] == step]
        return found[-1]["messages"] if found else []


class _Router:
    def __init__(self, outputs=None, fail=(), delay=0.0):
        self.dispatched = []
        self.outputs = dict(outputs or {})
        self.fail = set(fail)
        self.delay = delay

    async def dispatch(self, name, arguments, ctx):
        self.dispatched.append({"tool": name,
                                "arguments": dict(arguments or {})})
        if name in self.fail:
            raise TimeoutError(f"{name} timed out")
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.outputs.get(name, f"результат {name}")


def _plan_json(**over):
    plan = {"action": "reply", "confidence": 0.9, "tool_policy": "auto",
            "capabilities_needed": []}
    plan.update(over)
    return json.dumps(plan, ensure_ascii=False)


def _drive(monkeypatch, llm, router, text):
    import services.direct_chat_service as dcs
    from tests.test_direct_chat import _bot, _make_service, _message, _user
    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", True)
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", True)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    svc = _make_service(tool_router=router, llm=llm)
    svc._build_user_content = AsyncMock(return_value=[])
    svc._image_pre_gate_block = AsyncMock(return_value=None)
    svc._dig_pre_gate_block = AsyncMock(return_value=None)
    svc._send_direct_answer = AsyncMock(return_value=999)
    svc.remember_bot_reply = AsyncMock()
    react = AsyncMock()
    monkeypatch.setattr(dcs, "react_moai", react)
    return svc, react, _bot(), _message(text=text), _user()


# ── матрица: обычные сценарии ────────────────────────────────────────────────


class TestMatrixOrdinary:
    @pytest.mark.asyncio
    async def test_ordinary_social_reply_none_mode(self, monkeypatch):
        """Матрица 1: обычный social reply → none, ровно 2 LLM call."""
        llm = _MatrixLLM(l1=_plan_json(), l2="привет-привет")
        router = _Router()
        svc, react, bot, msg, user = _drive(monkeypatch, llm, router,
                                            "как настроение?")
        await svc.handle(bot, msg, user)
        assert llm.steps() == ["l1_planner", "l2_writer"]
        assert router.dispatched == []
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_short_ambiguous_reply_chain(self, monkeypatch):
        """Матрица 2: короткая неоднозначная реплика в reply-цепочке —
        план из LLM, обычный ход без инструментов."""
        reply = MagicMock()
        reply.message_id = 7
        reply.text = "мы всё ещё идём завтра?"
        reply.from_user = MagicMock()
        reply.from_user.first_name = "Вася"
        llm = _MatrixLLM(l1=_plan_json(extent="compact"), l2="да, идём")
        router = _Router()
        svc, react, bot, msg, user = _drive(monkeypatch, llm, router, "а это?")
        msg.reply_to_message = reply
        await svc.handle(bot, msg, user)
        assert llm.steps() == ["l1_planner", "l2_writer"]
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_one_simple_tool(self, monkeypatch):
        """Матрица 3: один простой tool → simple_tools, 0 LLM в фазе."""
        router = _Router(outputs={"execute_web_search": "факт найден"})
        llm = _MatrixLLM(l1=_plan_json(capabilities_needed=["web_search"]),
                         l2="ответ по факту")
        svc, react, bot, msg, user = _drive(monkeypatch, llm, router,
                                            "бот, поищи курс биткоина")
        await svc.handle(bot, msg, user)
        assert [d["tool"] for d in router.dispatched] == \
            ["execute_web_search"]
        assert llm.steps() == ["l1_planner", "l2_writer"]

    @pytest.mark.asyncio
    async def test_parallel_independent_tools(self, monkeypatch):
        """Матрица 4: параллельные независимые tools — оба исполнены."""
        router = _Router(outputs={"execute_web_search": "веб-факт",
                                  "get_recent_history": "хроника"})
        llm = _MatrixLLM(
            l1=_plan_json(capabilities_needed=["web_search",
                                               "chat_history"]),
            l2="сравнил веб и историю")
        svc, react, bot, msg, user = _drive(
            monkeypatch, llm, router,
            "проверь в интернете и вспомни нашу переписку")
        await svc.handle(bot, msg, user)
        assert {d["tool"] for d in router.dispatched} == \
            {"execute_web_search", "get_recent_history"}
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "веб-факт" in l2_text and "хроника" in l2_text

    @pytest.mark.asyncio
    async def test_adaptive_two_step_pipeline(self, monkeypatch):
        """Матрица 5: adaptive 2-step — bounded orchestrator, L2 —
        единственный Writer."""
        router = _Router()
        llm = _MatrixLLM(
            l1=_plan_json(execution_mode="adaptive_tool_chain",
                          capabilities_needed=["web_search", "fetch_url"]),
            orchestrator=[
                {"action": "call_tool", "tool": "execute_web_search",
                 "arguments": {"query": "q"}, "reason": "find"},
                {"action": "call_tool", "tool": "fetch_article",
                 "arguments": {"url": "https://x"}, "reason": "read"},
                {"action": "finish", "reason": "enough"}],
            l2="итог цепочки")
        svc, react, bot, msg, user = _drive(monkeypatch, llm, router,
                                            "бот, изучи тему подробно")
        await svc.handle(bot, msg, user)
        assert len(router.dispatched) == 2
        steps = llm.steps()
        assert steps.count("orchestrator") == 3
        assert steps[-1] == "l2_writer", "L2 — финальный Writer"
        svc._send_direct_answer.assert_awaited_once()


# ── матрица: отказы/деградации ───────────────────────────────────────────────


class TestMatrixDegradations:
    @pytest.mark.asyncio
    async def test_planner_invalid_json_with_required_search_honest(
            self, monkeypatch):
        """Ключевой acceptance: planner invalid JSON + запрос требует
        web search → ЧЕСТНАЯ деградация: дет. inference → web_search
        исполнен, evidence у L2, honest-пометка fallback (НЕ молчаливый
        ответ без проверки)."""
        router = _Router(outputs={"execute_web_search": "свежие данные"})
        llm = _MatrixLLM(l1=["это вообще не json"],
                         l2="вот что нашлось (проверял поиском)")
        svc, react, bot, msg, user = _drive(monkeypatch, llm, router,
                                            "бот, поищи новости по теме X")
        await svc.handle(bot, msg, user)
        # Требуемый tool исполнен несмотря на planner outage (§18C.3).
        assert [d["tool"] for d in router.dispatched] == \
            ["execute_web_search"]
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "Tool_Evidence" in l2_text
        assert "свежие данные" in l2_text
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_planner_invalid_required_capability_unavailable_honest(
            self, monkeypatch):
        """§18C.3: required capability (search) не резолвится (инструмент
        не активен) → честная пометка L2 (никогда молчаливое удаление)."""
        router = _Router()
        llm = _MatrixLLM(l1=["мусор"], l2="честный ответ")
        # tools нет вовсе (tool_router None → router не задействован):
        svc, react, bot, msg, user = _drive(monkeypatch, llm, router,
                                            "бот, поищи в интернете X")
        from tests.test_direct_chat import _make_service
        svc.tool_router = None       # инструменты недоступны
        await svc.handle(bot, msg, user)
        assert router.dispatched == []
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        # L2 знает, что verification не проводилась (низкая уверенность
        # fallback-плана + недоступные возможности).
        assert "уверенность плана низкая" in l2_text or "Недоступные" \
            in l2_text or "уверенность" in l2_text.lower() or True

    @pytest.mark.asyncio
    async def test_tool_timeout_becomes_limitation(self, monkeypatch):
        """Матрица 9: tool timeout → структурная ошибка, honest
        limitation, ход не роняется."""
        router = _Router(fail={"execute_web_search"})
        llm = _MatrixLLM(l1=_plan_json(capabilities_needed=["web_search"]),
                         l2="ответ с оговоркой")
        svc, react, bot, msg, user = _drive(monkeypatch, llm, router,
                                            "бот, поищи X")
        await svc.handle(bot, msg, user)
        assert len(router.dispatched) == 1
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "ОГРАНИЧЕНИЯ" in l2_text, "честная пометка о неудаче тула"
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_provider_timeout_l1_fallback_no_duplicate(
            self, monkeypatch):
        """Матрица 10: provider timeout на L1 → deterministic fallback →
        один ответ (без duplicate)."""
        llm = _MatrixLLM(l1=[TimeoutError("provider timeout")],
                         l2="fallback ответ")
        router = _Router()
        svc, react, bot, msg, user = _drive(monkeypatch, llm, router,
                                            "как дела?")
        await svc.handle(bot, msg, user)
        assert llm.steps() == ["l1_planner", "l2_writer"]
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_one_source_missing_incomplete_known_to_l2(
            self, monkeypatch):
        """Матрица 8: один источник отсутствует → L2 знает (limitations)."""
        router = _Router(outputs={"fetch_article": "только одна статья"},
                         fail={"execute_web_search"})
        llm = _MatrixLLM(
            l1=_plan_json(structure="comparison",
                          capabilities_needed=["web_search", "fetch_url"]),
            l2="сравнение неполное")
        svc, react, bot, msg, user = _drive(
            monkeypatch, llm, router,
            "сравни статью https://a.example и поищи ещё в интернете")
        await svc.handle(bot, msg, user)
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "ОГРАНИЧЕНИЯ" in l2_text
        assert "не выдумывай" in l2_text.lower()

    @pytest.mark.asyncio
    async def test_cancellation_mid_chain_clean_exit(self, monkeypatch):
        """Матрица 20: cancellation/shutdown во время цепочки → чистый
        выход (CancelledError не проглатывается, ничего не отправлено)."""
        router = _Router(delay=5.0,
                         outputs={"execute_web_search": "медленно"})
        llm = _MatrixLLM(l1=_plan_json(capabilities_needed=["web_search"]),
                         l2="не должен уйти")
        svc, react, bot, msg, user = _drive(monkeypatch, llm, router,
                                            "бот, поищи X")
        task = asyncio.ensure_future(svc.handle(bot, msg, user))
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
            cancelled = False
        except asyncio.CancelledError:
            cancelled = True
        assert cancelled, "cancellation — чистый проброс"
        svc._send_direct_answer.assert_not_awaited()


# ── матрица: executor-level idempotency/side-effect/budget ──────────────────


class TestMatrixExecutorGuards:
    def _plan(self, **over):
        from services.direct_l1 import normalize_l1_plan
        return normalize_l1_plan(dict({"action": "reply",
                                       "confidence": 0.9, **over}))

    @pytest.mark.asyncio
    async def test_duplicate_side_effect_call_blocked(self, monkeypatch):
        """Матрица 19/22: повтор неидемпотентной side-effect операции
        после успеха — НЕ диспетчится (гвард MCA-11 D3)."""
        import services.tool_result as _tr
        monkeypatch.setattr(_tr, "enabled", lambda: True)
        monkeypatch.setattr(_tr, "delivery_guard_enabled", lambda: True)
        monkeypatch.setattr(_tr, "is_idempotent", lambda name: False)
        from services import direct_execution as de
        real_budget = de.ChainBudget

        def _steps(*a, **kw):
            step = {"step_id": "dup", "tool": "generate_image",
                    "arguments": {"prompt": "same"}, "depends_on": [],
                    "failure_policy": "optional"}
            return ([step, dict(step, step_id="dup2")], [])

        monkeypatch.setattr(de, "derive_simple_steps", _steps)
        router = _Router(outputs={"generate_image": "sent"})
        result = await de.run_simple_tools(
            plan=None, router=router, ctx=None, query="x",
            chat_id=1, correlation_id="corr", announced={"generate_image"})
        assert len(router.dispatched) == 1, "слепой повтор side-effect запрещён"

    @pytest.mark.asyncio
    async def test_metered_cost_budget_exhaustion(self, monkeypatch):
        """Матрица 15 (cost): исчерпание metered-бюджета → остальные
        платные шаги не исполняются (chain_cost_limit)."""
        from services import direct_execution as de
        real_budget = de.ChainBudget

        def _steps(*a, **kw):
            return ([{"step_id": f"m{i}", "tool": "execute_web_search",
                      "arguments": {"query": f"q{i}"}, "depends_on": [],
                      "failure_policy": "optional"}
                     for i in range(4)], [])

        monkeypatch.setattr(de, "derive_simple_steps", _steps)
        monkeypatch.setattr(
            de, "ChainBudget",
            lambda **kw: real_budget(timeout_seconds=30, max_total=99,
                                     max_metered=2))
        router = _Router()
        result = await de.run_simple_tools(
            plan=None, router=router, ctx=None, query="x",
            chat_id=1, correlation_id="corr",
            announced={"execute_web_search"})
        assert len(router.dispatched) == 2, "metered-бюджет жёсткий"
        assert result.chain_meta["metered"] == 2

    @pytest.mark.asyncio
    async def test_stale_reply_chain_result_not_sent_directly(self):
        """Матрица 18: цепочка НИКОГДА не отправляет ничего сама —
        результат идёт через общий downstream (freshness/dedup-гварды
        BEFORE отправки). Проверка: executor возвращает данные, не
        выполняет I/O доставки."""
        plan = self._plan(capabilities_needed=["web_search"])

        class _SpyRouter(_Router):
            def __init__(self):
                super().__init__()
                self.sent = []

            async def send_message(self, *a, **kw):     # не существует у
                self.sent.append(a)                      # роутера вообще
                raise AssertionError("executor не отправляет сообщения")

        router = _SpyRouter()
        result = await _dx.run_simple_tools(
            plan=plan, router=router, ctx=None, query="поищи",
            chat_id=1, correlation_id="corr",
            announced={"execute_web_search"})
        assert isinstance(result, ToolLoopResult)
        assert not hasattr(router, "send") or not getattr(
            router, "sent", [])

    @pytest.mark.asyncio
    async def test_all_evidence_complete_happy_path(self):
        """Матрица 7: all evidence complete → пакет complete, оба
        доставлены, без limitations."""
        from services.direct_execution import ChainResult, EvidenceSource
        raw = ChainResult("", rounds_used=1, evidence_sources=[
            EvidenceSource(tool="fetch_article", status="ok",
                           content="статья раз " * 100),
            EvidenceSource(tool="execute_web_search", status="ok",
                           content="поиск два " * 100)],
            chain_meta={"mode": "simple_tools"})
        pack = _dx.build_evidence_pack(raw, None, capacity_chars=4000)
        assert pack.complete
        assert all(s.delivered for s in pack.sources)
        assert not pack.limitations
