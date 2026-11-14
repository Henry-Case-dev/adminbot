"""SMART-CORRECTIVE-01 S4-COMPLETION — семантика завершения исследования.

Проверяется НАБЛЮДАЕМОЕ поведение (не наличие констант):

* состояние исследования на существующем ``ToolLoopResult``:
  ``complete | partial | failed`` + cause + continuation (варианты/токен) +
  evidence refs;
* достаточность: подтверждённые результаты без структурных пробелов →
  ``complete``; здоровый чекап без инструментальных попыток не делает
  лишних вызовов;
* продолжение при частичном/нерелевантном первом результате, единичном
  отказе, неполном фрагменте: директива продолжения в ТОМ ЖЕ tool-loop
  (user-сообщение), направление выбирает модель;
* исчерпанные/объективно недоступные пути → честный partial с конкретной
  причиной и пометкой в отчёте, а не ложное «полное» завершение;
* обычный диалог (без opt-in) не переисследует задачу;
* нет бесконечного цикла модель↔проверка (прогресс-гейт по отпечатку
  пробелов и записям журнала);
* частичный результат сохраняет фактически полученные данные и provenance.

LLM — граница провайдера (детерминированные двойники); ToolRouter,
ToolContext, tool-loop, CheckupService, классификация результатов —
настоящий код. Сеть/БД/Telegram не используются.
"""
from __future__ import annotations

import copy
import json
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

import pytest

from services import direct_capabilities as caps
from services import diagnostic_policy as diag
from services import tool_schemas
from services.checkup_service import CheckupService
from services.llm_client import LLMChatResult, LLMToolCall
from services.tool_loop import (
    RESEARCH_COMPLETE,
    RESEARCH_PARTIAL,
    ToolLoopResult,
    chat_with_tools,
)
from services.tool_router import ToolContext, ToolDeps, ToolRouter

CHAT_ID = -1009876543210
REPO = "Henry-Case-dev/adminbot"
DEPLOYED = "a" * 40
CHECKOUT = "b" * 40
PATH = "services/mca_watchdog.py"


# ── общие двойники границ ──────────────────────────────────────────────────

class _ScriptedLLM:
    """Провайдер-граница: по одному LLMChatResult на generate_chat."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0
        self.messages: list = []

    async def generate_chat(self, messages, *, tools=None, **kwargs):
        self.calls += 1
        self.messages = copy.deepcopy(messages)
        return self._results.pop(0)

    async def generate(self, messages, **kwargs):  # pragma: no cover
        raise AssertionError("single generate не должен вызываться")


def _tc(call_id, name, args):
    return LLMToolCall(id=call_id, name=name,
                       arguments=json.dumps(args, ensure_ascii=False))


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


class _Reader:
    """Двойник SourceReader: отдаёт заранее заданные payload'ы по порядку."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls: list[dict] = []

    async def run(self, **kwargs):
        self.calls.append(dict(kwargs))
        if not self._payloads:
            raise AssertionError("неожиданный вызов SourceReader")
        return copy.deepcopy(self._payloads.pop(0))


class _Diagnostics:
    """Минимальный двойник DiagnosticCollector (read-only runtime-проба)."""

    limits = SimpleNamespace(max_output_chars=8000)

    def __init__(self):
        self.requests: list = []

    async def collect(self, request):
        self.requests.append(request)
        page = {
            "schema": "self-diag-01/d3-bundle-v1", "status": "ok",
            "probe": request.probe, "sources": [], "not_checked": [],
            "access": {"chat_id": request.chat_id},
        }
        return SimpleNamespace(), page


def _base_payload(path=PATH):
    snippet = ('def _process_job(job):\n'
               '    process_id = "watchdog.jobs"\n'
               '    return job\n')
    return {
        "status": "ok", "outcome": "ok", "verified": True,
        "path": path, "path_depth": path.count("/"), "line_range": [1, 3],
        "snippet": snippet, "snippet_chars": len(snippet),
        "file_total_lines": 3, "read_level": "parsed",
        "repo": REPO, "commit": DEPLOYED, "ref": DEPLOYED,
        "provider": "github", "host": "github.com", "network_calls": 1,
        "match_count": 1, "match_material": "implementation",
        "source_id": f"src:{REPO}@{DEPLOYED}:{path}",
        "verified_url": f"https://github.com/{REPO}/blob/{DEPLOYED}/{path}",
        "provenance": {"provider": "github", "commit": DEPLOYED,
                       "path": path, "sha256": "deadbeef"},
        "truncation": {"truncated": False, "why": "",
                       "retrievable_remainder_lines": 0},
        "continuation": {"kind": "", "cursor": "", "remaining": False,
                         "reason": "", "next_arguments": {},
                         "progress_id": "srp_test"},
        "not_checked": {},
    }


def _confirmed_payload(path=PATH):
    return _base_payload(path)


def _mention_payload(path="scripts/harness_watchdog.py"):
    """Нерелевантный первый результат: упоминание без подтверждения байтов."""
    payload = _base_payload(path)
    payload.update({
        "verified": False, "verified_url": "", "match_material": "mention",
        "outcome": "partial", "partial": True,
        "snippet": "watchdog.jobs mentioned only\n", "snippet_chars": 30,
    })
    return payload


def _fragment_payload(path=PATH):
    """Неполный фрагмент: доставлено начало, остаток доступен продолжением."""
    payload = _base_payload(path)
    payload.update({
        "outcome": "partial", "partial": True, "line_range": [1, 3],
        "file_total_lines": 200,
        "truncation": {"truncated": True, "why": "evidence_window",
                       "retrievable_remainder_lines": 197},
        "continuation": {
            "kind": "file_lines", "cursor": "", "remaining": True,
            "reason": "evidence_window",
            "next_arguments": {"repo": REPO, "ref": DEPLOYED, "path": path,
                               "line_start": 4, "follow": False},
            "progress_id": "srp_test"},
    })
    return payload


def _error_payload(reason="rate_limit", outcome="provider_limit"):
    return {"status": "error", "outcome": outcome, "reason": reason,
            "message": "provider rejected the request",
            "source_id": f"src:{REPO}@{DEPLOYED}"}


def _denied_payload(reason="policy_denied"):
    return {"status": "denied", "reason": reason,
            "message": "tool disabled by policy"}


def _router(reader, diagnostics=None):
    return ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                               aliases=None, source_reader=reader,
                               diagnostics=diagnostics))


def _runtime(router, *, tools=("read_source_code",)):
    ctx = ToolContext(CHAT_ID, "watchdog.jobs", user_id=1)
    ctx.diagnostic_research = _diag_ctx()
    schemas = caps.schemas_for_names(
        list(tools), tool_schemas.active_tools(False, False))
    return {"router": router, "ctx": ctx, "schemas": schemas,
            "correlation_id": "checkup:s4"}


async def _run_checkup(llm, runtime, *, logs="ERROR watchdog.jobs stuck"):
    telemetry: dict = {}
    report = await CheckupService(llm).checkup(
        logs, used_fallback=False, telemetry=telemetry,
        tool_runtime=runtime)
    return report, telemetry


def _directive_messages(llm) -> list[dict]:
    return [m for m in llm.messages
            if "<research_continuation>" in str(m.get("content") or "")]


# ── 1. Достаточность: подтверждённые факты → без лишних вызовов ────────────

class TestSufficientEvidence:
    @pytest.mark.asyncio
    async def test_confirmed_result_ends_immediately(self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _Reader([_confirmed_payload()])
        llm = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=[
                _tc("c1", "read_source_code",
                    {"operation": "read", "path": PATH})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Причина: heartbeat не обновляется.",
                          tool_calls=None, finish_reason="stop"),
        ])
        report, telemetry = await _run_checkup(
            llm, _runtime(_router(reader)))
        assert report == "Причина: heartbeat не обновляется."
        assert llm.calls == 2
        assert telemetry["research_status"] == RESEARCH_COMPLETE
        assert telemetry["research_cause"] == "evidence_sufficient"
        assert telemetry["research_continuations"] == 0
        assert telemetry["research_confirmed"] == 1
        assert telemetry["research_unresolved"] == 0

    @pytest.mark.asyncio
    async def test_healthy_checkup_without_tool_calls(self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _Reader([])
        llm = _ScriptedLLM([
            LLMChatResult(content="Всё здорово, аномалий нет.",
                          tool_calls=None, finish_reason="stop"),
        ])
        report, telemetry = await _run_checkup(
            llm, _runtime(_router(reader)))
        assert report == "Всё здорово, аномалий нет."
        assert reader.calls == []
        assert llm.calls == 1
        assert telemetry["research_status"] == RESEARCH_COMPLETE
        assert telemetry["research_cause"] == "no_research_needed"
        assert telemetry["research_calls"] == 0
        assert telemetry["research_continuations"] == 0


# ── 2. Продолжение: нерелевантный результат / единичный отказ ──────────────

class TestContinuation:
    @pytest.mark.asyncio
    async def test_irrelevant_first_result_gets_continuation(self,
                                                             monkeypatch):
        _allow_policy(monkeypatch)
        reader = _Reader([_mention_payload(), _confirmed_payload()])
        llm = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=[
                _tc("c1", "read_source_code",
                    {"operation": "locate", "query": "watchdog.jobs"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Предварительно: файл найден.",
                          tool_calls=None, finish_reason="stop"),
            LLMChatResult(content=None, tool_calls=[
                _tc("c2", "read_source_code",
                    {"operation": "locate",
                     "query": "ProcessWatchdog heartbeat stale"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Подтверждено: heartbeat watchdog.jobs "
                                  "проверяется в _process_job.",
                          tool_calls=None, finish_reason="stop"),
        ])
        report, telemetry = await _run_checkup(
            llm, _runtime(_router(reader)))
        # Промежуточный вывод не публикуется как финал.
        assert report.startswith("Подтверждено:")
        assert "Примечание" not in report
        assert llm.calls == 4
        assert telemetry["research_status"] == RESEARCH_COMPLETE
        assert telemetry["research_continuations"] == 1
        # Директива продолжения — данные о пробеле, а не подсказка файла.
        directive = _directive_messages(llm)
        assert directive, "директива продолжения не попала в payload"
        text = str(directive[0]["content"])
        assert "read_source_code" in text
        assert "уточнить направление поиска" in text
        assert PATH not in text  # жёсткой подсказки файла нет
        # Модель реально сменила запрос (направление выбирает она).
        assert reader.calls[0]["query"] != reader.calls[1]["query"]

    @pytest.mark.asyncio
    async def test_single_transient_failure_allows_continuation(
            self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _Reader([_error_payload("rate_limit"),
                          _confirmed_payload()])
        llm = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=[
                _tc("c1", "read_source_code",
                    {"operation": "locate", "query": "watchdog.jobs"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Источник отказал, данных нет.",
                          tool_calls=None, finish_reason="stop"),
            LLMChatResult(content=None, tool_calls=[
                _tc("c2", "read_source_code",
                    {"operation": "locate",
                     "query": "watchdog jobs heartbeat stale"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Подтверждено кодом после повтора.",
                          tool_calls=None, finish_reason="stop"),
        ])
        report, telemetry = await _run_checkup(
            llm, _runtime(_router(reader)))
        assert report == "Подтверждено кодом после повтора."
        assert llm.calls == 4
        assert telemetry["research_status"] == RESEARCH_COMPLETE
        assert telemetry["research_continuations"] == 1
        assert _directive_messages(llm)
        assert len(reader.calls) == 2

    @pytest.mark.asyncio
    async def test_unavailable_source_allows_other_declared_tool(
            self, monkeypatch):
        """Единичный отказ одного источника: доступный другой инструмент —
        способ продолжения (кросс-проверка runtime), выбор за моделью."""
        _allow_policy(monkeypatch)
        reader = _Reader([_denied_payload()])
        diagnostics = _Diagnostics()
        llm = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=[
                _tc("c1", "read_source_code",
                    {"operation": "locate", "query": "watchdog.jobs"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Код недоступен.",
                          tool_calls=None, finish_reason="stop"),
            LLMChatResult(content=None, tool_calls=[
                _tc("c2", "inspect_runtime",
                    {"area": "logs", "probe": "logs.window",
                     "scope": "instance"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Подтверждено runtime-данными журнала.",
                          tool_calls=None, finish_reason="stop"),
        ])
        report, telemetry = await _run_checkup(
            llm, _runtime(_router(reader, diagnostics),
                          tools=("read_source_code", "inspect_runtime")))
        # Продолжение другим объявленным инструментом реально исполнено.
        assert llm.calls == 4
        assert len(diagnostics.requests) == 1
        assert telemetry["research_continuations"] == 1
        # Источник кода остался объективно недоступен: вывод подтверждён
        # runtime-данными, но отчёт честно называет незакрытую область.
        assert telemetry["research_status"] == RESEARCH_PARTIAL
        assert telemetry["research_cause"] == "source_unavailable"
        assert report.startswith("Подтверждено runtime-данными журнала.")
        assert "это частичный результат" in report
        assert "read_source_code: недоступен (policy_denied)" in report
        directive = str(_directive_messages(llm)[0]["content"])
        assert "другими доступными инструментами" in directive

    @pytest.mark.asyncio
    async def test_incomplete_fragment_continues_from_next_arguments(
            self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _Reader([_fragment_payload(), _confirmed_payload()])
        llm = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=[
                _tc("c1", "read_source_code",
                    {"operation": "read", "path": PATH})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Видел только начало файла.",
                          tool_calls=None, finish_reason="stop"),
            LLMChatResult(content=None, tool_calls=[
                _tc("c2", "read_source_code",
                    {"operation": "read", "path": PATH, "line_start": 4})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Дочитал остаток: логика подтверждена.",
                          tool_calls=None, finish_reason="stop"),
        ])
        report, telemetry = await _run_checkup(
            llm, _runtime(_router(reader)))
        assert report == "Дочитал остаток: логика подтверждена."
        assert llm.calls == 4
        assert telemetry["research_continuations"] == 1
        # Продолжение реально исполнилось с next line_start.
        assert reader.calls[1]["line_start"] == 4
        assert telemetry["research_status"] == RESEARCH_COMPLETE


# ── 3. Объективная невозможность → честный partial с причиной ──────────────

class TestHonestPartial:
    @pytest.mark.asyncio
    async def test_denied_only_path_returns_partial_with_cause(
            self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _Reader([_denied_payload()])
        llm = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=[
                _tc("c1", "read_source_code",
                    {"operation": "locate", "query": "watchdog.jobs"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="По доступным данным причина не установлена.",
                          tool_calls=None, finish_reason="stop"),
        ])
        report, telemetry = await _run_checkup(
            llm, _runtime(_router(reader)))
        # Никакого автоматического продолжения: пути объективно исчерпаны.
        assert llm.calls == 2
        assert telemetry["research_status"] == RESEARCH_PARTIAL
        assert telemetry["research_cause"] == "source_unavailable"
        assert telemetry["research_continuations"] == 0
        assert telemetry["research_unresolved"] >= 1
        # Отчёт не выдаётся за полный: причина + неподтверждённая область.
        assert report.startswith("По доступным данным")
        assert "это частичный результат" in report
        assert "часть источников недоступна" in report
        assert "read_source_code" in report

    @pytest.mark.asyncio
    async def test_model_declines_continuation_and_partial_is_marked(
            self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _Reader([_mention_payload()])
        llm = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=[
                _tc("c1", "read_source_code",
                    {"operation": "locate", "query": "watchdog.jobs"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Ничего существенного не нашёл.",
                          tool_calls=None, finish_reason="stop"),
            LLMChatResult(content="Вывод: подтверждённых данных нет.",
                          tool_calls=None, finish_reason="stop"),
        ])
        report, telemetry = await _run_checkup(
            llm, _runtime(_router(reader)))
        assert llm.calls == 3
        assert telemetry["research_continuations"] == 1
        assert telemetry["research_status"] == RESEARCH_PARTIAL
        assert telemetry["research_cause"] == "continuation_not_taken"
        assert "это частичный результат" in report
        assert "возможность продолжить исследование не была использована" \
            in report


# ── 4. Прогресс-гейт: бесконечного цикла модель↔проверка нет ───────────────

class TestNoInfiniteLoop:
    @pytest.mark.asyncio
    async def test_repeated_same_failure_offers_only_once(self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _Reader([_error_payload("rate_limit"),
                          _error_payload("rate_limit")])
        llm = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=[
                _tc("c1", "read_source_code",
                    {"operation": "locate", "query": "watchdog.jobs"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Первая попытка отказала.",
                          tool_calls=None, finish_reason="stop"),
            LLMChatResult(content=None, tool_calls=[
                _tc("c2", "read_source_code",
                    {"operation": "locate",
                     "query": "watchdog.jobs process_id"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Повтор тоже отказал; причина не подтверждена.",
                          tool_calls=None, finish_reason="stop"),
        ])
        report, telemetry = await _run_checkup(
            llm, _runtime(_router(reader)))
        # Один offer, дальше — никаких новых директив.
        assert llm.calls == 4
        assert telemetry["research_continuations"] == 1
        assert telemetry["research_status"] == RESEARCH_PARTIAL
        assert telemetry["research_cause"] == "no_progress"
        assert "это частичный результат" in report
        assert "продолжение не дало новых данных" in report

    @pytest.mark.asyncio
    async def test_ordinary_dialog_does_not_re_research(self, monkeypatch):
        """Без opt-in общие диалоги не получают директиву продолжения."""
        _allow_policy(monkeypatch)
        reader = _Reader([_mention_payload()])
        # Обычный диалог: policy-гейт не нужен — router вызывается напрямую.
        llm = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=[
                _tc("c1", "read_source_code",
                    {"operation": "locate", "query": "watchdog.jobs"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Обычный ответ по найденному файлу.",
                          tool_calls=None, finish_reason="stop"),
        ])
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "что там по watchdog.jobs?"}],
            tools=caps.schemas_for_names(
                ["read_source_code"], tool_schemas.active_tools(False, False)),
            router=_router(reader),
            ctx=ToolContext(CHAT_ID, "watchdog.jobs", user_id=1),
            chat_id=CHAT_ID)
        assert isinstance(result, ToolLoopResult)
        assert str(result) == "Обычный ответ по найденному файлу."
        assert llm.calls == 2
        assert not _directive_messages(llm)
        # Общая семантика состояния доступна потребителю, но не навязывает
        # повторное исследование.
        assert result.research_state["status"] == RESEARCH_PARTIAL
        assert result.research_state["continuation"]["available"] is True
        assert result.continuation_offers == 0


# ── 5. Partial сохраняет фактически собранные данные и provenance ──────────

class TestPartialPreservesEvidence:
    @pytest.mark.asyncio
    async def test_partial_keeps_results_refs_and_text(self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _Reader([_mention_payload()])
        llm = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=[
                _tc("c1", "read_source_code",
                    {"operation": "locate", "query": "watchdog.jobs"})],
                finish_reason="tool_calls"),
            LLMChatResult(content="Частичный вывод по упоминанию.",
                          tool_calls=None, finish_reason="stop"),
            LLMChatResult(content="Итог без подтверждения.",
                          tool_calls=None, finish_reason="stop"),
        ])
        ctx = ToolContext(CHAT_ID, "watchdog.jobs", user_id=1)
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "проверь watchdog.jobs"}],
            tools=caps.schemas_for_names(
                ["read_source_code"], tool_schemas.active_tools(False, False)),
            router=_router(reader), ctx=ctx, chat_id=CHAT_ID,
            ensure_research_completion=True)
        state = result.research_state
        assert state["status"] == RESEARCH_PARTIAL
        # Данные вызова не потеряны: журнал, текст, source_id/provenance.
        assert len(result.tool_results) == 1
        envelope = result.tool_results[0]
        assert envelope["tool"] == "read_source_code"
        assert envelope["data"]["source_id"].startswith("src:")
        assert envelope["data"]["provenance"]["commit"] == DEPLOYED
        assert "mentioned only" in result.tool_context
        assert str(result) == "Итог без подтверждения."
        # Evidence refs и структурный пробел видны потребителю.
        assert any(ref.startswith("src:") for ref in state["evidence_refs"])
        assert state["gaps"] and state["gaps"][0]["tool"] == "read_source_code"
        assert state["confirmed"] == 0
