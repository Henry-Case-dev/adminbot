"""SMART-EXECUTION-RELIABILITY-01 — контракт этапа G (owner 2026-11-14).

Проверяется НАБЛЮДАЕМОЕ поведение существующего tool-loop/Writer, а не текст
исходников (архконтракт §5):

  * штатный финальный ответ модели НЕ вызывает второй LLM-вызов;
  * остановка исследования с накопленным evidence → содержательная
    финализация по данным (существующий LLM/Writer), причина/отказы/
    непроверенное переданы в финальный payload;
  * частичный отказ одного источника не обнуляет исследование;
  * финальный LLM недоступен → безопасный структурный partial из
    tool-результатов (не саркастичная заглушка);
  * лимиты исследования исчерпаны, но финализация работает независимо;
  * `retryable=false` терминален для маршрута: идентичный вызов не
    повторяется, другие запросы к тому же недоступному host не диспетчатся;
  * tool results/provenance сохраняются при любом исходе;
  * тот же контракт используют checkup и фактчек (не отдельный механизм).

TEST-LIFECYCLE: CONTRACT owner=SXR-G (S7-FINALIZE)
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from services import budget_gate
from services.llm_client import LLMChatResult, LLMError, LLMToolCall
from services.tool_loop import (
    FINALIZE_STEP,
    TOOL_LOOP_FALLBACK_PHRASE,
    ToolLoopResult,
    chat_with_tools,
)

MESSAGES = [{"role": "user", "content": "почему упал деплой?"}]
TOOLS = [{"type": "function", "function": {"name": "execute_web_search"}}]
CHAT_ID = -1001234567890


# ── фейки ───────────────────────────────────────────────────────────────────

class FakeLLM:
    """`generate_chat` — исследование; `generate` — существующий Writer."""

    def __init__(self, answers, *, finalize_text="ИТОГ: собранные данные",
                 finalize_error=None):
        self._answers = list(answers)
        self.finalize_text = finalize_text
        self.finalize_error = finalize_error
        self.chat_calls = 0
        self.finalize_calls = 0
        self.finalize_messages = []
        self.finalize_kwargs = []

    async def generate_chat(self, messages, *, tools=None, **kwargs):
        self.chat_calls += 1
        if not self._answers:
            raise AssertionError("не хватило запланированных ответов")
        item = self._answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        self.finalize_calls += 1
        self.finalize_messages.append(messages)
        self.finalize_kwargs.append(kwargs)
        if self.finalize_error is not None:
            raise self.finalize_error
        return self.finalize_text


class FakeRouter:
    def __init__(self, outputs=None, fn=None):
        self._outputs = dict(outputs or {})
        self._fn = fn
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, dict(arguments or {})))
        if self._fn is not None:
            return await self._fn(name, arguments, ctx)
        return self._outputs.get(name, f"данные:{name}")


def _ctx():
    return SimpleNamespace(tool_results=[])


def _round(prefix, calls):
    return LLMChatResult(
        content=None,
        tool_calls=[LLMToolCall(id=f"{prefix}_{i}", name=name,
                                arguments=json.dumps(args, ensure_ascii=False))
                    for i, (name, args) in enumerate(calls)],
        finish_reason="tool_calls")


def _text(value):
    return LLMChatResult(content=value, tool_calls=None, finish_reason="stop")


def _patch_budgets(monkeypatch, value):
    async def _enabled(chat_id=None):
        return bool(value)

    monkeypatch.setattr(budget_gate, "budgets_enabled", _enabled)


def _error_payload(**fields):
    payload = {"status": "error"}
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False)


# ── G2/G4: нормальный и деградировавший финал ──────────────────────────────

class TestFinalizationContract:
    @pytest.mark.asyncio
    async def test_normal_final_answer_makes_no_extra_llm_call(self):
        llm = FakeLLM([_round("r0", [("execute_web_search", {"query": "x"})]),
                       _text("финальный ответ модели")])
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=FakeRouter(), ctx=_ctx(),
                                    chat_id=CHAT_ID)
        assert out == "финальный ответ модели"
        assert out.degraded is False and out.reason == "ok"
        assert out.finalize_mode == ""
        assert llm.finalize_calls == 0            # лишнего вызова нет

    @pytest.mark.asyncio
    async def test_stop_with_evidence_finalizes_with_context(self):
        """Исследование прервано провайдером, данные есть → финальная фаза
        по evidence; в финальный payload переданы запрос, результаты,
        причина остановки и provenance."""
        llm = FakeLLM(
            [_round("r0", [("execute_web_search", {"query": "deploy"})]),
             LLMError("upstream 500")],
            finalize_text="ИТОГ: деплой упал после шага сборки")
        router = FakeRouter({"execute_web_search":
                             json.dumps({"status": "ok", "results": ["a"],
                                         "source_id": "src-1"})})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=router, ctx=_ctx(),
                                    chat_id=CHAT_ID)
        assert out == "ИТОГ: деплой упал после шага сборки"
        assert out.degraded is True and out.reason == "llm_error"
        assert out.finalize_mode == "llm"
        assert llm.finalize_calls == 1
        # Финал — Writer-путь без tools.
        assert llm.finalize_kwargs[0].get("step") == FINALIZE_STEP
        final_payload = llm.finalize_messages[0]
        assert final_payload[0]["content"] == "почему упал деплой?"
        tool_messages = [m for m in final_payload if m["role"] == "tool"]
        assert tool_messages and "source_id" in tool_messages[0]["content"]
        directive = final_payload[-1]["content"]
        assert "Причина остановки" in directive and "llm_error" in directive
        # Результаты/журнал сохранены.
        assert out.tool_results and out.tool_results[0]["status"] == "ok"
        assert out.tool_results[0]["evidence_refs"] == ["src-1"]
        assert "source_id" in out.tool_context
        assert str(out) != TOOL_LOOP_FALLBACK_PHRASE

    @pytest.mark.asyncio
    async def test_one_failed_source_does_not_reset_research(self):
        llm = FakeLLM(
            [_round("r0", [("execute_web_search", {"query": "a"}),
                           ("fetch_article", {"url": "https://broken.example/x"})]),
             LLMError("upstream 500")],
            finalize_text="ИТОГ: поиск дал данные, статья недоступна")
        router = FakeRouter({
            "execute_web_search": "полезные данные поиска",
            "fetch_article": _error_payload(
                error="extract_failed", reason="source_unavailable",
                retryable=False, host="broken.example")})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=router, ctx=_ctx(),
                                    chat_id=CHAT_ID)
        assert out == "ИТОГ: поиск дал данные, статья недоступна"
        assert out.finalize_mode == "llm"
        statuses = [env["status"] for env in out.tool_results]
        assert statuses == ["ok", "error"]         # отказ не обнулил run
        directive = llm.finalize_messages[0][-1]["content"]
        assert "fetch_article" in directive and "broken.example" not in directive
        assert "Отказавшие источники/инструменты" in directive

    @pytest.mark.asyncio
    async def test_all_sources_failed_finalize_names_failures(self):
        llm = FakeLLM(
            [_round("r0", [("execute_web_search", {"query": "a"})]),
             LLMError("down")],
            finalize_text="ИТОГ: источники недоступны, проверено ничего")
        router = FakeRouter({"execute_web_search": _error_payload(
            error="provider_unavailable", reason="provider_unavailable")})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=router, ctx=_ctx(),
                                    chat_id=CHAT_ID)
        assert out == "ИТОГ: источники недоступны, проверено ничего"
        assert out.finalize_mode == "llm"
        directive = llm.finalize_messages[0][-1]["content"]
        assert "execute_web_search" in directive
        assert "provider_unavailable" in directive
        assert "Непроверенные области" in directive
        assert out.tool_results[0]["status"] == "error"

    @pytest.mark.asyncio
    async def test_final_llm_unavailable_gives_structured_partial(self):
        llm = FakeLLM(
            [_round("r0", [("execute_web_search", {"query": "deploy"})]),
             LLMError("upstream 500")],
            finalize_error=LLMError("writer down"))
        router = FakeRouter({"execute_web_search":
                             json.dumps({"status": "ok",
                                         "snippet": "deploy failed at build",
                                         "source_id": "src-9",
                                         "verified_url":
                                             "https://github.com/o/r/blob/x"})})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=router, ctx=_ctx(),
                                    chat_id=CHAT_ID)
        text = str(out)
        assert out.degraded is True and out.reason == "llm_error"
        assert out.finalize_mode == "structured_partial"
        assert text != TOOL_LOOP_FALLBACK_PHRASE
        assert "Исследование остановлено" in text
        assert "llm_error" in text
        assert "почему упал деплой?" in text          # исходный запрос
        assert "execute_web_search" in text           # источник данных
        assert "src-9" in text and "github.com" in text  # provenance
        assert "финальный LLM-вызов недоступен" in text
        assert out.tool_results[0]["status"] == "ok"  # журнал сохранён

    @pytest.mark.asyncio
    async def test_exhausted_research_counters_do_not_block_finalize(
            self, monkeypatch):
        """LIMIT исследования исчерпан (явная политика ON) — финализация
        всё равно формирует ответ по накопленным данным."""
        _patch_budgets(monkeypatch, True)
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_TOTAL_CALLS", 1)
        llm = FakeLLM(
            [_round("r0", [("execute_web_search", {"query": "a"}),
                           ("execute_web_search", {"query": "b"})])],
            finalize_text="ИТОГ: есть один результат, второй вызов ограничен")
        router = FakeRouter({"execute_web_search": "данные поиска"})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=router, ctx=_ctx(),
                                    chat_id=CHAT_ID)
        assert out.degraded is True and out.reason == "chain_call_limit"
        assert out.finalize_mode == "llm"
        assert out == "ИТОГ: есть один результат, второй вызов ограничен"
        assert str(out) != TOOL_LOOP_FALLBACK_PHRASE
        assert [env["status"] for env in out.tool_results] == ["ok", "denied"]
        assert len(router.calls) == 1
        directive = llm.finalize_messages[0][-1]["content"]
        assert "лимит вызовов" in directive


# ── G5: терминальные отказы ────────────────────────────────────────────────

class TestTerminalRoutes:
    @pytest.mark.asyncio
    async def test_retryable_false_identical_call_not_repeated(self):
        llm = FakeLLM([
            _round("r0", [("read_source_code", {"url":
                         "https://github.com/o/r/blob/x.py"})]),
            _round("r1", [("read_source_code", {"url":
                         "https://github.com/o/r/blob/x.py"})]),
            _text("финал")])
        router = FakeRouter({"read_source_code": _error_payload(
            error="auth_failed", reason="auth_failed",
            host="github.com")})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=router, ctx=_ctx(),
                                    chat_id=CHAT_ID)
        assert out == "финал"
        assert len(router.calls) == 1              # идентичный не повторён
        assert out.tool_results[0]["error_code"] == "auth_failed"
        assert out.tool_results[0]["retryable"] is False
        assert out.tool_results[1]["duplicate"] is True
        assert out.tool_results[1]["error_code"] == "auth_failed"

    @pytest.mark.asyncio
    async def test_other_query_to_blocked_host_not_dispatched(self):
        llm = FakeLLM([
            _round("r0", [("fetch_article", {"url":
                         "https://blocked.example/one"})]),
            _round("r1", [("fetch_article", {"url":
                         "https://blocked.example/two"})]),
            _round("r2", [("fetch_article", {"url":
                         "https://ok.example/three"})]),
            _text("финал")])
        router = FakeRouter({
            "fetch_article": _error_payload(
                error="extract_failed", reason="destination_blocked",
                retryable=False, host="blocked.example")})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=router, ctx=_ctx(),
                                    chat_id=CHAT_ID)
        # Первый вызов исполнен, второй (тот же host) — структурный denied,
        # другой host — снова исполнен (маршрут не заблокирован целиком).
        assert [call[1]["url"] for call in router.calls] == [
            "https://blocked.example/one", "https://ok.example/three"]
        assert out.tool_results[1]["status"] == "denied"
        assert out.tool_results[1]["error_code"] == "route_terminal"
        denied = json.loads(out.tool_context.splitlines()[1])
        assert denied["reason"] == "route_terminal"
        assert denied["code"] == "extract_failed"


# ── единый контракт потребителей (Direct/checkup/фактчек) ─────────────────

class TestConsumersShareContract:
    def test_direct_uses_same_function(self):
        from services import direct_chat_service
        from services import tool_loop
        assert direct_chat_service.chat_with_tools is tool_loop.chat_with_tools

    @pytest.mark.asyncio
    async def test_checkup_research_stop_returns_finalized_text(self):
        from services.checkup_service import CheckupService

        llm = FakeLLM(
            [_round("c", [("get_bot_health", {})]),
             LLMError("research broke")],
            finalize_text="ОТЧЁТ: бот жив, логов новых нет")
        router = FakeRouter({"get_bot_health": "ok"})
        service = CheckupService(llm, metrics_enabled=False)
        raw = await service.checkup(
            "log line", used_fallback=False, chat_id=None,
            tool_runtime={"router": router, "ctx": _ctx(),
                          "schemas": list(TOOLS),
                          "correlation_id": "corr-g"})
        assert raw == "ОТЧЁТ: бот жив, логов новых нет"
        assert str(raw) != TOOL_LOOP_FALLBACK_PHRASE
        assert llm.finalize_calls == 1

    @pytest.mark.asyncio
    async def test_factcheck_tool_path_uses_same_finalization(
            self, monkeypatch):
        from services import factcheck_service as fc

        async def _lore(_chat_id):
            return False

        monkeypatch.setattr(fc, "resolve_lore_compiler_flag", _lore)
        llm = FakeLLM(
            [_round("f", [("fact_check", {"claim": "x"})]),
             LLMError("research broke")],
            finalize_text="ВЕРДИКТ: подтверждено частично")
        router = FakeRouter({"fact_check": "evidence"})
        service = fc.FactCheckService(MagicMock(), llm, tool_router=router)
        raw, used_tools = await service._invoke_llm(
            list(MESSAGES), "x", CHAT_ID, correlation_id="corr-g")
        assert used_tools is True
        assert str(raw) == "ВЕРДИКТ: подтверждено частично"
        assert isinstance(raw, ToolLoopResult)
        assert raw.finalize_mode == "llm"
        assert llm.finalize_calls == 1
