"""BGS-05-BUDGET — бюджеты отражают реальность (owner 2026-11-05 §6,
контракт behavior-gates-simplification §4).

SMART-EXECUTION-RELIABILITY-01 (owner 2026-11-14 §B1/B3) обновил контракт:
числа из окна модели остаются ДЕРИВАЦИЕЙ payload-срезов и наблюдаемой метой,
но НЕ потолком числа шагов; заводских 4/6000/4 больше нет, как и общего
дедлайна 360 с. Enforcement объёма — только явная операторская политика
(`DIRECT_ORCHESTRATOR_MAX_*`, `MCA_TOOL_MAX_*`, fuse `>0`) при effective
`flags.budgets_enabled=true`.

Проверяем наблюдаемый контракт, а не текст исходников:

* (a) динамическое окно модели реально течёт в деривацию границ
  (Model Capacity Resolver — тот же вызов, что у Direct primary);
  legacy-числа (4 шага / 6000 токенов / 800 символов запроса / 400 сниппет)
  — только нижний fallback при недоступном резолвере;
* (b) env ``DIRECT_ORCHESTRATOR_MAX_STEPS``/``_MAX_TOTAL_TOKENS`` — ЖЁСТКИЙ
  потолок при budgets ON: связывает цепочку сверху; без env цепочка не
  обрывается расчётным числом;
* (c) срез не вводит новых редактируемых ключей каталога: env-ножи
  остаются env-only (читаемы/живы), в каталоге их нет;
* (d) денежные/технические границы: заводского metered-потолка 4 нет
  (0 = политика не задана), анти-цикл и METERED_TOOLS не тронуты;
* (e) мутация «в вернуть захардкоженный дефолт как основной источник»
  роняет (a): пробы (a) ведут себя по-разному при разном окне.
"""
from __future__ import annotations

import json

import pytest

from config.settings import Settings
from services import direct_execution as dx
from services import model_capacity as mc
from services import param_catalog as pc
from services import tool_loop


# ── локальные фейки (паттерн test_asap8_v6_wc_direct_d04) ───────────────────


def _plan(execution_mode: str = "adaptive_tool_chain"):
    return type("P", (), {"execution_mode": execution_mode})()


class _Router:
    def __init__(self):
        self.dispatched = []

    async def dispatch(self, name, arguments, ctx):
        self.dispatched.append({"tool": name,
                                "arguments": dict(arguments or {})})
        return f"результат {name}"


class _OrchLLM:
    """Fake LLM оркестратора: последовательность JSON-решений."""

    def __init__(self, decisions, *, chat_model: str = "",
                 base_url: str = ""):
        self.decisions = list(decisions)
        self.calls = []
        if chat_model:
            self._chat_model = chat_model
        if base_url:
            self._base_url = base_url

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kw):
        self.calls.append({"step": step, "messages": messages})
        item = self.decisions.pop(0) if self.decisions else {
            "action": "finish", "reason": "done"}
        return json.dumps(item, ensure_ascii=False)


def _tool_decisions(n: int) -> list[dict]:
    return [{"action": "call_tool", "tool": "execute_web_search",
             "arguments": {"query": f"q{i}"}, "reason": f"r{i}"}
            for i in range(n)]


async def _run_chain(llm) -> dx.ChainResult:
    return await dx.run_adaptive_chain(
        llm=llm, router=_Router(), ctx=None, plan=_plan(), query="q",
        tool_schemas=[{"function": {"name": "execute_web_search",
                                    "description": "d"}}],
        chat_id=1, correlation_id="corr-bgs05")


# ── (a) динамическое окно течёт в границы оркестратора ──────────────────────


class TestDynamicWindowResolution:
    def test_unknown_window_falls_back_to_legacy_floors(self):
        """Окно недоступно → legacy-константы (нижний fallback, контракт §4)."""
        budget = dx.orchestrator_budget_for_window(0)
        assert budget.window_tokens == 0
        assert budget.window_source == "fallback_default"
        assert budget.max_steps == dx.ORCHESTRATOR_MAX_STEPS == 4
        assert budget.max_total_tokens == dx.ORCHESTRATOR_MAX_TOTAL_TOKENS \
            == 6000
        assert budget.query_chars == dx.ORCHESTRATOR_QUERY_CHARS == 800
        assert budget.snippet_chars == \
            dx.ORCHESTRATOR_EVIDENCE_SNIPPET_CHARS == 400

    def test_large_window_scales_limits_above_legacy(self):
        """Окно 128k: границы растут с ёмкостью — legacy не потолок (05.2)."""
        budget = dx.orchestrator_budget_for_window(131072)
        assert budget.max_steps > 4
        assert budget.max_steps <= dx.ORCHESTRATOR_STEPS_HARD_MAX
        assert budget.max_total_tokens > 6000
        assert budget.query_chars > 800
        assert budget.snippet_chars > 400
        # Воспроизводимость: детерминированная функция окна (05.1).
        again = dx.orchestrator_budget_for_window(131072)
        assert again == budget

    @pytest.mark.asyncio
    async def test_resolver_window_flows_into_budget(self, monkeypatch):
        """Probe: окно из resolve_stage_window (слот Direct primary) —
        основной источник границ; резолвер из direct_chat_service."""
        async def _fake_stage_window(base_url, model, *, slot=None):
            assert slot == "direct.primary"
            assert base_url == "http://llm.example" and model == "big-model"
            return 131072, "runtime"

        monkeypatch.setattr(mc, "resolve_stage_window", _fake_stage_window)
        llm = _OrchLLM([], chat_model="big-model",
                       base_url="http://llm.example")
        limits = await dx.resolve_orchestrator_budget(llm=llm)
        assert limits.window_tokens == 131072
        assert limits.window_source == "runtime"
        assert limits.max_total_tokens == 131072 // 16      # 8192 > 6000
        assert limits.max_steps == 8                        # > legacy 4
        assert limits.query_chars == 131072
        assert limits.snippet_chars == 131072 // 32         # 4096 > 400

    @pytest.mark.asyncio
    async def test_resolver_failure_falls_back_without_raise(self, monkeypatch):
        """Runtime-резолвер упал → sync-путь (без сети) → честный fallback,
        границы не «молча» захардкожены, а выведены из registry/env-окна."""
        async def _boom(base_url, model, *, slot=None):
            raise RuntimeError("provider discovery down")

        monkeypatch.setattr(mc, "resolve_stage_window", _boom)
        monkeypatch.setattr(mc, "resolve_evidence_window_tokens",
                            lambda model=None: (16384, "unknown_fallback"))
        llm = _OrchLLM([], chat_model="big-model",
                       base_url="http://llm.example")
        limits = await dx.resolve_orchestrator_budget(llm=llm)
        assert limits.window_tokens == 16384
        assert limits.window_source == "unknown_fallback"
        assert limits.max_steps == 4          # 16384//16384 → пол 4
        assert limits.max_total_tokens == 6000  # пол 6000
        assert limits.query_chars == 16384
        assert limits.snippet_chars == 512      # 16384//32

    @pytest.mark.asyncio
    async def test_chain_not_capped_by_window_derived_steps(self, monkeypatch):
        """SMART-EXECUTION-RELIABILITY-01 §B1: число шагов больше не берётся
        из «окна модели» как потолок — все 9 решений оркестратора исполнены,
        остановка по `finish`. Деривация остаётся наблюдаемой метой
        (payload-срезы + `max_steps` как расчётное число), а не enforcement."""
        async def _fake_stage_window(base_url, model, *, slot=None):
            return 131072, "runtime"

        monkeypatch.setattr(mc, "resolve_stage_window", _fake_stage_window)
        monkeypatch.setattr(dx, "orchestrator_max_metered_calls", lambda: 0)
        llm = _OrchLLM(_tool_decisions(9), chat_model="big-model",
                       base_url="http://llm.example")
        result = await _run_chain(llm)
        assert len(result.tool_trace) == 9                  # ни один не срезан
        assert result.chain_meta["reason"] == "finish"
        assert result.chain_meta["window_tokens"] == 131072
        assert result.chain_meta["window_source"] == "runtime"
        assert result.chain_meta["max_steps"] == 8           # деривация, не cap
        assert result.chain_meta["limits"]["limits_enforced"] is True
        assert result.chain_meta["limits"]["max_total_calls"] == 0

    @pytest.mark.asyncio
    async def test_chain_without_window_not_capped_to_legacy(self, monkeypatch):
        """Резолвер недоступен → честный source, но legacy-число 4 больше не
        обрывает цепочку: исполняются все 9 решений до `finish`."""
        def _no_window(model=None):
            return 0, "fallback_default"

        monkeypatch.setattr(mc, "resolve_evidence_window_tokens", _no_window)
        monkeypatch.setattr(dx, "orchestrator_max_metered_calls", lambda: 0)
        llm = _OrchLLM(_tool_decisions(9))                  # без _base_url
        result = await _run_chain(llm)
        assert len(result.tool_trace) == 9
        assert result.chain_meta["reason"] == "finish"
        assert result.chain_meta["window_tokens"] == 0
        assert result.chain_meta["window_source"] == "fallback_default"

    def test_big_window_keeps_long_query_intact(self):
        """BGS-05.3: на большом окне запрос не режется локальным дефолтом;
        структурная граница — бюджет L1-стадии, не [:800] оркестратора."""
        marker_tail = "ХВОСТ-КОНТРДОВОД который раньше терялся на позиции 900"
        query = ("запрос " * 300) + " " + marker_tail
        caps = dx.orchestrator_budget_for_window(131072)
        messages = dx._orchestrator_messages(
            query=query, allowlist=[], evidence_sources=[], steps_done=[],
            query_chars=caps.query_chars, snippet_chars=caps.snippet_chars)
        assert marker_tail in messages[-1]["content"]


# ── (b) env — жёсткий потолок ────────────────────────────────────────────────


class TestEnvHardCeilings:
    def test_ceiling_functions_return_zero_when_unset(self, monkeypatch):
        monkeypatch.delenv("DIRECT_ORCHESTRATOR_MAX_STEPS", raising=False)
        monkeypatch.delenv("DIRECT_ORCHESTRATOR_MAX_TOTAL_TOKENS",
                           raising=False)
        assert dx.orchestrator_max_steps() == 0
        assert dx.orchestrator_max_total_tokens() == 0

    def test_steps_ceiling_binds_over_dynamic(self, monkeypatch):
        monkeypatch.setenv("DIRECT_ORCHESTRATOR_MAX_STEPS", "2")
        assert dx.orchestrator_max_steps() == 2
        budget = dx.orchestrator_budget_for_window(131072)
        assert budget.max_steps == 8                        # динамика 8
        assert dx._apply_ceiling(budget.max_steps, 2) == 2

    def test_tokens_ceiling_binds_over_dynamic(self, monkeypatch):
        monkeypatch.setenv("DIRECT_ORCHESTRATOR_MAX_TOTAL_TOKENS", "5000")
        assert dx.orchestrator_max_total_tokens() == 5000
        budget = dx.orchestrator_budget_for_window(131072)
        assert dx._apply_ceiling(budget.max_total_tokens, 5000) == 5000

    def test_no_env_dynamic_not_clamped_to_legacy(self, monkeypatch):
        """Без env динамическое значение НЕ обрезается legacy-числом
        (регрессия «мёртвого ножа» от прежнего _limit-поведения)."""
        monkeypatch.delenv("DIRECT_ORCHESTRATOR_MAX_STEPS", raising=False)
        budget = dx.orchestrator_budget_for_window(131072)
        assert dx._apply_ceiling(budget.max_steps, 0) == 8

    def test_settings_classvar_takes_priority_over_env(self, monkeypatch):
        monkeypatch.setenv("DIRECT_ORCHESTRATOR_MAX_STEPS", "3")
        monkeypatch.setattr(Settings, "DIRECT_ORCHESTRATOR_MAX_STEPS", 5,
                            raising=False)
        assert dx.orchestrator_max_steps() == 5

    @pytest.mark.asyncio
    async def test_chain_env_ceiling_binds(self, monkeypatch):
        """env-потолок связывает цепочку на большом окне: 2 шага, не 8."""
        async def _fake_stage_window(base_url, model, *, slot=None):
            return 131072, "runtime"

        monkeypatch.setattr(mc, "resolve_stage_window", _fake_stage_window)
        monkeypatch.setenv("DIRECT_ORCHESTRATOR_MAX_STEPS", "2")
        monkeypatch.setattr(dx, "orchestrator_max_metered_calls", lambda: 999)
        llm = _OrchLLM(_tool_decisions(9), chat_model="big-model",
                       base_url="http://llm.example")
        result = await _run_chain(llm)
        assert len(result.tool_trace) == 2
        assert result.chain_meta["max_steps"] == 2


# ── (c) каталог: новых ножей нет, env-ножи живы и вне каталога ──────────────


class TestCatalogClassification:
    def test_orchestrator_knobs_are_not_catalog_entries(self):
        """DIRECT_ORCHESTRATOR_* не имеют редактируемой карточки в каталоге
        (env-only); срез не вводит новых ножей админки."""
        editable = {spec.pg_key for spec in pc.REGISTRY.values()
                    if spec.category is not None and not spec.hidden}
        for name in ("DIRECT_ORCHESTRATOR_MAX_STEPS",
                     "DIRECT_ORCHESTRATOR_MAX_TOTAL_TOKENS",
                     "DIRECT_ORCHESTRATOR_MAX_METERED_CALLS"):
            assert name not in pc.REGISTRY
            assert name not in editable

    def test_metered_knob_stays_readable_value_semantics(self, monkeypatch):
        """Денежный нож читаем и жив: не задан → 0 = политика не задана
        (заводского потолка 4 больше нет, §B1/B3); задан → значение."""
        monkeypatch.delenv("DIRECT_ORCHESTRATOR_MAX_METERED_CALLS",
                           raising=False)
        monkeypatch.delattr(Settings, "DIRECT_ORCHESTRATOR_MAX_METERED_CALLS",
                            raising=False)
        assert dx.orchestrator_max_metered_calls() == 0
        monkeypatch.setenv("DIRECT_ORCHESTRATOR_MAX_METERED_CALLS", "7")
        assert dx.orchestrator_max_metered_calls() == 7

    def test_no_new_catalog_rows_for_budget_slice(self):
        """BGS-05 не удаляет и не депрекирует ключей каталога: ни одна
        запись REGISTRY не получила migration_class от этого среза."""
        for spec in pc.REGISTRY.values():
            if spec.migration_class:
                assert "ORCHESTRATOR" not in spec.pg_key


# ── (d) деньги/таймауты/анти-цикл не мигрируют ──────────────────────────────


class TestHardProtectionsUntouched:
    @pytest.mark.asyncio
    async def test_chain_keeps_metered_observational_by_default(
            self, monkeypatch):
        """Окно 128k не вводит денежный потолок (§B1/B3): `max_metered`
        по умолчанию 0 = политика не задана; счётчик metered — наблюдаемый.
        Деривация окна остаётся в мете, enforcement — только явная политика."""
        async def _fake_stage_window(base_url, model, *, slot=None):
            return 131072, "runtime"

        monkeypatch.setattr(mc, "resolve_stage_window", _fake_stage_window)
        monkeypatch.delenv("DIRECT_ORCHESTRATOR_MAX_METERED_CALLS",
                           raising=False)
        monkeypatch.delattr(Settings, "DIRECT_ORCHESTRATOR_MAX_METERED_CALLS",
                            raising=False)
        llm = _OrchLLM([{"action": "finish", "reason": "done"}],
                       chat_model="big-model", base_url="http://llm.example")
        result = await _run_chain(llm)
        assert result.chain_meta["max_metered"] == 0
        assert result.chain_meta["metered"] == 0
        assert result.chain_meta["window_tokens"] == 131072
        assert result.chain_meta["max_steps"] == 8

    def test_metered_tools_set_unchanged(self):
        for name in ("execute_web_search", "fetch_article", "fact_check",
                     "generate_image", "transcribe_video"):
            assert name in tool_loop.METERED_TOOLS

    def test_chain_deadline_resolution_unchanged(self, monkeypatch):
        """ER-08 резолв дедлайна не тронут: override → MCA → tool_loop."""
        monkeypatch.delenv("DIRECT_ORCHESTRATOR_MAX_TIME_SECONDS",
                           raising=False)
        monkeypatch.setattr(Settings, "DIRECT_ORCHESTRATOR_MAX_TIME_SECONDS",
                            42.0, raising=False)
        assert dx.orchestrator_max_time_seconds() == 42.0
        monkeypatch.setattr(Settings, "DIRECT_ORCHESTRATOR_MAX_TIME_SECONDS",
                            None, raising=False)
        monkeypatch.setattr(Settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS", 360.0,
                            raising=False)
        assert dx.orchestrator_max_time_seconds() == 360.0

    @pytest.mark.asyncio
    async def test_cycle_protection_unchanged(self, monkeypatch):
        """Анти-цикл жив: повтор того же (tool, args) → bounded stop."""
        def _no_window(model=None):
            return 0, "fallback_default"

        monkeypatch.setattr(mc, "resolve_evidence_window_tokens", _no_window)
        router = _Router()
        llm = _OrchLLM([
            {"action": "call_tool", "tool": "execute_web_search",
             "arguments": {"query": "same"}, "reason": "a"},
            {"action": "call_tool", "tool": "execute_web_search",
             "arguments": {"query": "same"}, "reason": "loop"}])
        result = await dx.run_adaptive_chain(
            llm=llm, router=router, ctx=None, plan=_plan(), query="q",
            tool_schemas=[{"function": {"name": "execute_web_search"}}],
            chat_id=1, correlation_id="corr-bgs05-cycle")
        assert result.chain_meta["reason"] == "cycle_detected"
        assert len(router.dispatched) == 1

    @pytest.mark.asyncio
    async def test_shared_logic_for_direct_and_initiative(self, monkeypatch):
        """BGS-05.6: границы резолвятся в общей цепочке — вне зависимости
        от чата/режима один и тот же llm даёт один и тот же бюджет."""
        async def _fake_stage_window(base_url, model, *, slot=None):
            return 131072, "runtime"

        monkeypatch.setattr(mc, "resolve_stage_window", _fake_stage_window)
        llm = _OrchLLM([], chat_model="big-model",
                       base_url="http://llm.example")
        a = await dx.resolve_orchestrator_budget(llm=llm)
        b = await dx.resolve_orchestrator_budget(llm=llm)
        assert a == b
