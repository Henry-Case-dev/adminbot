"""SMART P0 checkup (S1–S6, S8) — наблюдаемый контракт поверх S7-базы.

Production-трасса 16.11.2026: чекап нашёл инциденты watchdog.jobs, но отдал
«техническую ошибку провайдера», не прочитал код; прямой reply владельца
заглох; длинный отчёт пришёл сырым Markdown, а успешная доставка
(`report_sent`) скрывала `research_status=partial`.

Проверяется НАБЛЮДАЕМОЕ поведение (не текст исходников):

* S1: `LLMError` классифицируется по существующим классам/`status`:
  детерминированный 4xx режима tools → plain FR-15 с `tools_unavailable`;
  транзиент без evidence → plain последним средством с `llm_error`;
  транзиент при неполном исследовании и новых данных → продолжение в ТОМ ЖЕ
  цикле; пустой финал с evidence → `empty_final`, а не `LLMBadResponseError`.
* S2/S3: причина/human-текст `llm_error`/`empty_final`/`tools_unavailable`;
  телеметрия чекапа: `status != complete` даёт пометку неполноты (не только
  `degraded`), отсутствие/непригодность tool-runtime → `not_executed` и
  нейтральная причина `diagnostic_runtime_unavailable` (провайдер tools не
  отвергал).
* S5: двойная ось — `research_verdict` (complete/partial/premature_stop/
  not_executed/unknown) и валидный `outcome="success"` + `status` события
  доставки (`report_sent` только complete; partial/unresearched — WARN);
  покрытие self-diag считает все доставки.
* S6/S8: отчёт доставляется существующим rich-каналом `markdown` с reply;
  детерминированный отказ → прежний plain, неоднозначный timeout/сеть/5xx →
  `delivery_unknown` без слепой повторной отправки; ledger/reply-история
  хранит ИСХОДНЫЙ отчёт (Markdown, не HTML); аддендум разрешает лёгкий
  Markdown и запрещает таблицы/HTML.

LLM — граница провайдера (детерминированные двойники); ToolRouter,
ToolContext, tool-loop, CheckupService, handler, delivery wrapper и
sanitize — реальный код. Сеть/БД/Telegram не используются.
"""
from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from handlers import checkup as checkup_mod
from services import diagnostic_policy as diag
from services import direct_capabilities as caps
from services import mca_events
from services import source_reader as sr
from services import tool_schemas
from services.checkup_prompts import CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM
from services.checkup_service import CheckupService
from services.llm_client import (
    LLMBadResponseError,
    LLMChatResult,
    LLMError,
    LLMTimeoutError,
    LLMToolCall,
)
from services.tool_loop import (
    RESEARCH_COMPLETE,
    RESEARCH_NOT_EXECUTED,
    RESEARCH_PARTIAL,
    ToolLoopResult,
    chat_with_tools,
)
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from web.api import routes as web_routes

CHAT_ID = -1009876543210
REPO = "Henry-Case-dev/adminbot"
DEPLOYED = "d" * 40
CHECKOUT = "c" * 40
PATH = "services/mca_watchdog.py"
TOOLS = [{"type": "function", "function": {"name": "execute_web_search"}}]


# ── граница провайдера ─────────────────────────────────────────────────────

class _ScriptedLLM:
    """`generate_chat` — раунды исследования; `generate` — writer/plain.

    ``answers``: LLMChatResult | Exception (поднимается из generate_chat).
    ``finalize_error`` — ошибка финального writer-вызова (`step=finalize`).
    """

    def __init__(self, answers, *, finalize_text="ИТОГ по собранным данным",
                 finalize_error=None, plain_text="plain: без инструментов"):
        self._answers = list(answers)
        self.finalize_text = finalize_text
        self.finalize_error = finalize_error
        self.plain_text = plain_text
        self.chat_calls = 0
        self.generate_steps: list[str] = []
        self.messages: list = []

    async def generate_chat(self, messages, *, tools=None, **kwargs):
        self.chat_calls += 1
        self.messages = copy.deepcopy(messages)
        if not self._answers:
            raise AssertionError("не хватило запланированных ответов")
        item = self._answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kwargs):
        self.generate_steps.append(str(step or ""))
        if step == "single":
            return self.plain_text
        if self.finalize_error is not None:
            raise self.finalize_error
        return self.finalize_text

    @property
    def plain_calls(self) -> int:
        return self.generate_steps.count("single")


def _tc(call_id, name, args):
    return LLMToolCall(id=call_id, name=name,
                       arguments=json.dumps(args, ensure_ascii=False))


def _round(call_id, name, args):
    return LLMChatResult(content=None, tool_calls=[_tc(call_id, name, args)],
                         finish_reason="tool_calls")


def _text(value):
    return LLMChatResult(content=value, tool_calls=None, finish_reason="stop")


class _Reader:
    """SourceReader-двойник: заранее заданные payload'ы по порядку."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls: list[dict] = []

    async def run(self, **kwargs):
        self.calls.append(dict(kwargs))
        if not self._payloads:
            raise AssertionError("неожиданный вызов SourceReader")
        return copy.deepcopy(self._payloads.pop(0))


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


def _mention_payload(path="scripts/harness_watchdog.py"):
    """Нерелевантный первый результат: упоминание без подтверждения байтов."""
    payload = _base_payload(path)
    payload.update({
        "verified": False, "verified_url": "", "match_material": "mention",
        "outcome": "partial", "partial": True,
        "snippet": "watchdog.jobs mentioned only\n",
    })
    return payload


def _diag_ctx():
    return {
        "target": "self", "repo": REPO, "ref": DEPLOYED,
        "ref_source": "deployed_sha", "deployed_sha": DEPLOYED,
        "checkout_sha": CHECKOUT, "deployed_matches_checkout": False,
        "local_source_verification": "verified", "dirty": False,
        "conflict": [], "identity_error": "", "note": "",
    }


def _allow_policy(monkeypatch):
    async def _allow(*args, **kwargs):
        return MagicMock(allowed=True, reason_code="allowed_public_class_default",
                         message_ru="", effect="allow", capability="",
                         role="project_owner", matrix_role="global_admin",
                         data_class="PUBLIC_TECH", source="default")
    monkeypatch.setattr(diag, "check_tool_call", _allow)


def _router(reader):
    return ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                               aliases=None, source_reader=reader,
                               diagnostics=None))


def _runtime(router):
    ctx = ToolContext(CHAT_ID, "watchdog.jobs", user_id=1)
    ctx.diagnostic_research = _diag_ctx()
    schemas = caps.schemas_for_names(
        ["read_source_code"], tool_schemas.active_tools(False, False))
    return {"router": router, "ctx": ctx, "schemas": schemas,
            "correlation_id": "checkup:p0"}


async def _run_checkup(llm, runtime, *, logs="ERROR watchdog.jobs stuck"):
    telemetry: dict = {}
    report = await CheckupService(llm).checkup(
        logs, used_fallback=False, telemetry=telemetry,
        tool_runtime=runtime)
    return report, telemetry


def _last_call_messages(llm) -> list[dict]:
    return copy.deepcopy(llm.messages)


def _capture_checkup_events(monkeypatch):
    """Реальная эмиссия `mca_events`: наблюдение через durable pending-буфер.

    `build_event`/`emit_mca_event` НЕ подменяются: подмена скрыла бы
    отбрасывание невалидного outcome (именно так `outcome="delivery"`
    терял событие). Форсируются только документированные default-ON
    kill-switch'и контракта — тест не зависит от env прогона.
    """
    monkeypatch.setattr(
        mca_events.mca_gates, "event_contract_enabled", lambda: True)
    monkeypatch.setattr(
        mca_events.mca_gates, "telemetry_store_enabled", lambda: True)
    mca_events.reset_pending()

    def _events(name=None):
        return [ev for ev in list(mca_events._pending)
                if name is None or ev.get("event_name") == name]

    return _events


# ── S1: классификация LLMError в цикле ─────────────────────────────────────

class TestTransientClassification:
    @pytest.mark.asyncio
    async def test_round0_tool_unsupported_marks_tools_unavailable(self):
        exc = LLMError("LLM HTTP 400: https://provider.example/v1")
        exc.status = 400
        llm = _ScriptedLLM([exc])
        router = MagicMock()
        router.dispatch = AsyncMock()
        out = await chat_with_tools(llm, [{"role": "user", "content": "q"}],
                                    tools=TOOLS, router=router, ctx=object())
        assert str(out) == "plain: без инструментов"
        assert out.not_executed_cause == "tools_unavailable"
        assert out.research_state["status"] == RESEARCH_NOT_EXECUTED
        assert out.research_state["cause"] == "tools_unavailable"
        assert out.degraded is False
        assert router.dispatch.await_count == 0

    @pytest.mark.asyncio
    async def test_round0_transient_without_evidence_plain_last_resort(self):
        exc = LLMTimeoutError("LLM request timed out",
                              cause_class="ReadTimeout")
        llm = _ScriptedLLM([exc])
        out = await chat_with_tools(llm, [{"role": "user", "content": "q"}],
                                    tools=TOOLS, router=MagicMock(),
                                    ctx=object())
        assert str(out) == "plain: без инструментов"
        # Честная причина: провайдер прервал, tools он не отвергал.
        assert out.not_executed_cause == "llm_error"
        assert out.research_state["status"] == RESEARCH_NOT_EXECUTED
        assert out.research_state["cause"] == "llm_error"

    @pytest.mark.asyncio
    async def test_round0_transient_with_plan_evidence_not_plain(self):
        """Evidence уже собран шагами плана → финализация, не plain-ответ."""
        llm = _ScriptedLLM(
            [LLMTimeoutError("timeout", cause_class="ReadTimeout")],
            finalize_text="ИТОГ: план дал данные")
        router = MagicMock()
        router.dispatch = AsyncMock(return_value=json.dumps(
            {"status": "ok", "results": ["a"], "source_id": "src-1"}))
        out = await chat_with_tools(
            llm, [{"role": "user", "content": "q"}], tools=TOOLS,
            router=router, ctx=SimpleNamespace(tool_results=[]),
            tool_plan=[{"step_id": "s1", "tool": "execute_web_search",
                        "arguments": {"query": "x"}}])
        assert str(out) == "ИТОГ: план дал данные"
        assert out.degraded is True and out.reason == "llm_error"
        assert out.finalize_mode == "llm"
        assert llm.plain_calls == 0
        assert out.tool_results and out.tool_results[0]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_round1_timeout_continues_and_preserves_evidence(
            self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _Reader([_mention_payload(), _base_payload()])
        llm = _ScriptedLLM([
            _round("c1", "read_source_code",
                   {"operation": "locate", "query": "watchdog.jobs"}),
            LLMTimeoutError("timeout", cause_class="ReadTimeout"),
            _round("c2", "read_source_code",
                   {"operation": "locate",
                    "query": "watchdog.jobs process_id heartbeat"}),
            _text("Подтверждено кодом: heartbeat watchdog.jobs обновляется "
                  "в _process_job."),
        ])
        report, telemetry = await _run_checkup(llm, _runtime(_router(reader)))
        assert report.startswith("Подтверждено кодом")
        assert telemetry["research_status"] == RESEARCH_COMPLETE
        assert telemetry["research_continuations"] == 1
        assert telemetry["research_degraded"] is False
        assert telemetry["research_calls"] == 2
        assert len(reader.calls) == 2          # evidence не потерян
        assert llm.plain_calls == 0
        directive = [m for m in llm.messages
                     if "<research_continuation>" in str(m.get("content"))]
        assert directive, "директива продолжения не добавлена после timeout"

    @pytest.mark.asyncio
    async def test_sustained_timeout_degrades_partial(self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _Reader([_mention_payload()])
        llm = _ScriptedLLM([
            _round("c1", "read_source_code",
                   {"operation": "locate", "query": "watchdog.jobs"}),
            LLMTimeoutError("timeout", cause_class="ReadTimeout"),
            LLMTimeoutError("timeout", cause_class="ReadTimeout"),
        ], finalize_error=LLMTimeoutError("timeout", cause_class="ReadTimeout"))
        report, telemetry = await _run_checkup(llm, _runtime(_router(reader)))
        assert telemetry["research_status"] == RESEARCH_PARTIAL
        assert telemetry["research_cause"] == "llm_error"
        assert telemetry["research_degraded"] is True
        # Никакого plain-ответа: финализация по evidence дала honest partial.
        assert llm.plain_calls == 0
        assert "Исследование остановлено" in report
        assert checkup_mod.research_verdict(telemetry) == "partial"
        assert checkup_mod.checkup_delivery_status("partial") == \
            "report_sent_partial"

    @pytest.mark.asyncio
    async def test_empty_final_with_evidence_degrades(self):
        class _EmptyFinalLLM(_ScriptedLLM):
            async def generate(self, *a, **kw):
                raise AssertionError("writer не должен вызываться")

        llm = _EmptyFinalLLM([_round("c1", "read_source_code",
                                     {"operation": "read", "path": PATH}),
                              LLMChatResult(content=None, tool_calls=None,
                                            finish_reason="stop")])
        out = await chat_with_tools(
            llm, [{"role": "user", "content": "q"}],
            tools=[{"type": "function",
                    "function": {"name": "read_source_code"}}],
            router=MagicMock(dispatch=AsyncMock(return_value="данные")),
            ctx=object())
        assert isinstance(out, ToolLoopResult)
        assert out.degraded is True and out.reason == "empty_final"
        assert out.tool_results
        assert "данные" in out.tool_context
        assert out.research_state["cause"] == "empty_final"


# ── S2/S3: пометка неполноты и not_executed в сервисе ─────────────────────

class TestCheckupHonesty:
    @pytest.mark.asyncio
    async def test_unusable_tool_runtime_marks_not_executed_and_note(
            self, monkeypatch):
        """Runtime запрошен, но непригоден → not_executed + честная пометка."""
        llm = _ScriptedLLM([])
        telemetry: dict = {}
        report = await CheckupService(llm).checkup(
            "logs", used_fallback=False, telemetry=telemetry,
            tool_runtime={"schemas": ()})
        assert llm.chat_calls == 0
        assert telemetry["research_status"] == RESEARCH_NOT_EXECUTED
        # F1b: причина нейтральна — модель tools не видела.
        assert telemetry["research_cause"] == "diagnostic_runtime_unavailable"
        assert report.startswith("ИТОГ по собранным данным")
        assert "инструментальное исследование не выполнялось" in report
        assert "провайдер модели не принял" not in report

    @pytest.mark.asyncio
    async def test_legacy_no_research_requested_keeps_report_clean(self):
        """Легаси-вызов (внутренний tool-loop) не запрашивал исследование.

        Телеметрия честно говорит not_executed, но отчёт не получает
        ложную пометку: вызывающий не просил инструментальную диагностику.
        """
        llm = _ScriptedLLM([])
        telemetry: dict = {}
        report = await CheckupService(llm).checkup(
            "logs", used_fallback=False, telemetry=telemetry)
        assert report == "ИТОГ по собранным данным"
        assert telemetry["research_status"] == RESEARCH_NOT_EXECUTED
        assert telemetry["research_cause"] == "diagnostic_runtime_unavailable"
        assert "Примечание" not in report

    @pytest.mark.asyncio
    async def test_handler_requested_without_runtime_is_marked(self):
        """Handler всегда запрашивает исследование, даже если runtime=None."""
        llm = _ScriptedLLM([])
        telemetry: dict = {}
        report = await CheckupService(llm).checkup(
            "logs", used_fallback=False, telemetry=telemetry,
            tool_runtime=None, research_requested=True)
        assert telemetry["research_status"] == RESEARCH_NOT_EXECUTED
        assert telemetry["research_cause"] == "diagnostic_runtime_unavailable"
        assert "инструментальное исследование не выполнялось" in report
        assert "провайдер модели не принял" not in report

    @pytest.mark.asyncio
    async def test_degraded_llm_finalize_gets_partial_note(self, monkeypatch):
        """S2: LLM-финализация по evidence при status=partial — с пометкой."""
        _allow_policy(monkeypatch)
        reader = _Reader([_mention_payload()])
        llm = _ScriptedLLM([
            _round("c1", "read_source_code",
                   {"operation": "locate", "query": "watchdog.jobs"}),
            LLMBadResponseError("upstream empty"),
        ], finalize_text="ИТОГ: есть только упоминание")
        report, telemetry = await _run_checkup(llm, _runtime(_router(reader)))
        assert telemetry["research_status"] == RESEARCH_PARTIAL
        assert telemetry["research_degraded"] is True
        assert report.startswith("ИТОГ: есть только упоминание")
        assert "это частичный результат" in report
        assert "read_source_code" in report


# ── S5: двойная ось и покрытие self-diag ──────────────────────────────────

class TestResearchVerdictAxis:
    def test_unknown_is_not_complete(self):
        assert checkup_mod.research_verdict(None) == "unknown"
        assert checkup_mod.research_verdict({}) == "unknown"
        assert checkup_mod.research_verdict(
            {"research_status": ""}) == "unknown"

    def test_complete_partial_not_executed(self):
        assert checkup_mod.research_verdict(
            {"research_status": "complete"}) == "complete"
        assert checkup_mod.research_verdict(
            {"research_status": "partial"}) == "partial"
        assert checkup_mod.research_verdict(
            {"research_status": "failed"}) == "partial"
        assert checkup_mod.research_verdict(
            {"research_status": "not_executed"}) == "not_executed"

    def test_premature_stop_by_cause_and_flag(self):
        assert checkup_mod.research_verdict({
            "research_status": "partial",
            "research_cause": "continuation_not_taken"}) == "premature_stop"
        assert checkup_mod.research_verdict({
            "research_status": "partial",
            "research_cause": "no_progress"}) == "premature_stop"
        assert checkup_mod.research_verdict({
            "research_status": "partial",
            "research_continuation_available": True}) == "premature_stop"

    def test_delivery_status_only_complete_is_report_sent(self):
        assert checkup_mod.checkup_delivery_status("complete") == "report_sent"
        for verdict in ("partial", "premature_stop"):
            assert checkup_mod.checkup_delivery_status(verdict) == \
                "report_sent_partial"
        for verdict in ("not_executed", "unknown"):
            assert checkup_mod.checkup_delivery_status(verdict) == \
                "report_sent_unresearched"

    def test_event_level_warn_for_incomplete_delivery(self, monkeypatch):
        """Реальный `build_event`: валидный `success` + ось полноты в status."""
        events = _capture_checkup_events(monkeypatch)
        for status in ("report_sent", "report_sent_partial",
                       "report_sent_unresearched"):
            checkup_mod.emit_checkup_event(
                outcome="success", chat_id=CHAT_ID, status=status,
                telemetry={})
        emitted = events("checkup_triggered")
        assert [ev["status"] for ev in emitted] == [
            "report_sent", "report_sent_partial", "report_sent_unresearched"]
        assert {ev["outcome"] for ev in emitted} == {"success"}
        assert [ev["level"] for ev in emitted] == ["INFO", "WARN", "WARN"]

    def test_delivery_outcome_is_not_in_mca_contract(self):
        """`delivery` не существует в контракте: событие молча пропало бы."""
        assert "success" in mca_events.ALL_OUTCOMES
        assert "delivery" not in mca_events.ALL_OUTCOMES
        assert mca_events.build_event(
            "checkup_triggered", outcome="delivery",
            status="report_sent") is None
        # Полнота едет отдельной осью в валидном событии.
        built = mca_events.build_event(
            "checkup_triggered", outcome="success",
            status="report_sent_partial", stage="final")
        assert built is not None and built["status"] == "report_sent_partial"

    def test_self_diag_coverage_counts_all_deliveries(self):
        delivered = mca_events.build_event(
            "checkup_triggered", outcome="success",
            status="report_sent_partial", stage="final", duration_ms=10)
        validated = mca_events.build_event(
            "checkup_output_validated", outcome="success", status="clean")
        assert delivered is not None and validated is not None
        result = web_routes._self_diag_validation_coverage(
            [delivered, validated])
        assert result["deliveries"]["checkup"] == 1
        assert result["measured"] is True

    def test_self_diag_row_state_partial_not_complete(self):
        partial = mca_events.build_event(
            "checkup_triggered", outcome="success",
            status="report_sent_partial", stage="final")
        complete = mca_events.build_event(
            "checkup_triggered", outcome="success",
            status="report_sent", stage="final")
        assert partial is not None and complete is not None
        assert web_routes._self_diag_row_state(partial) == "partial"
        assert web_routes._self_diag_row_state(complete) == "complete"


# ── S6/S8: rich Markdown, plain fallback, ledger source ────────────────────

class _Bot:
    """Telegram-граница: возвращает настоящие int message_id."""

    def __init__(self, *, rich_error=None):
        self.id = 777
        self.rich_error = rich_error
        self.rich_calls: list = []
        self.sent: list = []
        self._mid = 900

    async def send_rich_message(self, chat_id, rich, **kwargs):
        if self.rich_error is not None:
            raise self.rich_error
        self.rich_calls.append((chat_id, rich, kwargs))
        self._mid += 1
        return SimpleNamespace(message_id=self._mid)

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))
        self._mid += 1
        return SimpleNamespace(message_id=self._mid)


def _msg(message_id=11):
    return SimpleNamespace(chat=SimpleNamespace(id=CHAT_ID),
                           message_id=message_id)


REPORT_MD = ("**Причина:** heartbeat в `services/mca_watchdog.py` "
             "не обновляется.\n\n```\nPROCESS_ID = \"watchdog.jobs\"\n```")


class TestRichMarkdownDelivery:
    @pytest.mark.asyncio
    async def test_markdown_rich_with_reply_and_identifiers(self):
        bot = _Bot()
        sent_id, sent_ids, channel = await checkup_mod._send_checkup_report(
            bot, _msg(11), REPORT_MD)
        assert channel == "rich_markdown"
        assert sent_id == 901 and sent_ids == [901]
        assert bot.sent == []
        chat_id, rich, kwargs = bot.rich_calls[0]
        assert chat_id == CHAT_ID
        assert rich.html is None
        assert rich.markdown == REPORT_MD
        assert "**Причина:**" in rich.markdown
        assert "`services/mca_watchdog.py`" in rich.markdown
        assert "```" in rich.markdown
        assert kwargs["reply_parameters"].message_id == 11

    @pytest.mark.asyncio
    async def test_rich_deterministic_failure_falls_back_to_existing_plain(
            self, monkeypatch):
        """Детерминированный отказ rich (bad request) → plain, один отчёт."""
        bot = _Bot(rich_error=TelegramBadRequest(
            MagicMock(), "sendRichMessage unavailable"))

        async def _plain(_bot, _chat, _text, _reply, sent_ids=None):
            if sent_ids is not None:
                sent_ids.append(901)
            return 901

        plain = AsyncMock(side_effect=_plain)
        monkeypatch.setattr(checkup_mod, "send_chunked_reply", plain)
        sent_id, ids, channel = await checkup_mod._send_checkup_report(
            bot, _msg(11), REPORT_MD)
        assert channel == "plain_raw"
        assert sent_id == 901 and ids == [901]
        assert plain.await_count == 1
        assert plain.await_args.args[2] == REPORT_MD   # без обрезки
        assert plain.await_args.args[3] == 11          # тот же reply
        assert bot.rich_calls == []

    @pytest.mark.asyncio
    async def test_ambiguous_rich_timeout_is_not_blindly_repeated(
            self, monkeypatch):
        """F2: rich мог дойти до Telegram, затем timeout → без второго отчёта."""
        class _TimeoutAfterDeliveryBot(_Bot):
            async def send_rich_message(self, chat_id, rich, **kwargs):
                self.rich_calls.append((chat_id, rich, kwargs))
                self._mid += 1
                raise asyncio.TimeoutError()

        bot = _TimeoutAfterDeliveryBot()
        plain = AsyncMock()
        monkeypatch.setattr(checkup_mod, "send_chunked_reply", plain)
        sent_id, ids, channel = await checkup_mod._send_checkup_report(
            bot, _msg(11), REPORT_MD)
        assert len(bot.rich_calls) == 1     # rich-вызов реально ушёл
        assert bot.sent == []
        assert plain.await_count == 0       # слепого повтора нет
        assert channel == checkup_mod.CHECKUP_DELIVERY_UNKNOWN
        assert sent_id is None and ids == []

    @pytest.mark.asyncio
    async def test_transport_limit_uses_plain_without_truncation(
            self, monkeypatch):
        bot = _Bot()
        plain = AsyncMock(return_value=None)
        monkeypatch.setattr(checkup_mod, "send_chunked_reply", plain)
        long_report = "x" * (checkup_mod.CHECKUP_RICH_MARKDOWN_MAX_CHARS + 1)
        _sent, _ids, channel = await checkup_mod._send_checkup_report(
            bot, _msg(11), long_report)
        assert channel == "plain_raw"
        assert bot.rich_calls == []
        assert len(plain.await_args.args[2]) == len(long_report)

    @pytest.mark.asyncio
    async def test_persist_keeps_original_markdown_not_html(self, monkeypatch):
        db = MagicMock()
        db.upsert_bot_reply = AsyncMock()
        db.set_bot_reply_parent = AsyncMock()
        ledger_calls: list = []

        async def _record(_db, **kwargs):
            ledger_calls.append(dict(kwargs))

        monkeypatch.setattr(
            "services.bot_output_ledger.record_delivered_output", _record)
        monkeypatch.setattr(checkup_mod, "_service",
                            SimpleNamespace(db=db))
        await checkup_mod._persist_checkup_conversation(
            chat_id=CHAT_ID, sent_id=901, report=REPORT_MD, parent_id=11,
            correlation_id="checkup:p0", bot=SimpleNamespace(id=777))
        assert db.upsert_bot_reply.await_args.args[2] == REPORT_MD
        assert ledger_calls and ledger_calls[0]["text"] == REPORT_MD
        assert ledger_calls[0]["output_kind"] == "checkup_report"
        assert ledger_calls[0]["parent_message_ref"] == "tg:11"
        assert "<p>" not in ledger_calls[0]["text"]

    def test_no_markdownv2_or_second_engine(self):
        import pathlib
        source = pathlib.Path(checkup_mod.__file__).read_text(encoding="utf-8")
        assert 'parse_mode="MarkdownV2"' not in source
        assert "parse_mode='MarkdownV2'" not in source

    def test_addendum_allows_light_markdown_only(self):
        text = CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM
        assert "лёгкий Markdown допустим" in text
        assert "Таблицы и HTML запрещены" in text


# ── A/F: сквозной handler — rich delivery + событие по второй оси ─────────

@pytest.fixture
def clean_checkup():
    yield
    checkup_mod._service = None
    checkup_mod._fetcher = None
    checkup_mod._diagnostics = None
    checkup_mod._tool_router = None
    checkup_mod._cooldown._last.clear()


def _handler_msg(text="чекап", message_id=11):
    return SimpleNamespace(
        text=text, caption=None, message_id=message_id,
        chat=SimpleNamespace(id=CHAT_ID),
        from_user=SimpleNamespace(id=1))


class TestHandlerDeliveryAxis:
    @pytest.mark.asyncio
    async def test_positive_checkup_rich_and_report_sent(
            self, clean_checkup, monkeypatch):
        _allow_policy(monkeypatch)
        monkeypatch.setattr(sr, "resolve_self_repo_identity", _diag_ctx)
        reader = _Reader([_base_payload()])
        router = _router(reader)
        llm = _ScriptedLLM([
            _round("c1", "read_source_code",
                   {"operation": "read", "path": PATH}),
            _text(REPORT_MD),
        ])
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("ERROR watchdog.jobs stuck",
                                                 False))
        fetcher.last_state = ""
        fetcher.last_journal_state = ""
        checkup_mod.setup_checkup(CheckupService(llm), fetcher,
                                  diagnostics=False)
        checkup_mod.setup_checkup_tool_router(router)
        events = _capture_checkup_events(monkeypatch)
        bot = _Bot()

        await checkup_mod.checkup_handler(_handler_msg(), bot=bot)

        # read_source_code реально исполнен и пришёл rich-каналом.
        assert reader.calls and reader.calls[0]["ref"] == DEPLOYED
        assert len(bot.rich_calls) == 1 and bot.sent == []
        rich = bot.rich_calls[0][1]
        assert rich.markdown and rich.html is None
        assert "**Причина:**" in rich.markdown
        assert "```" in rich.markdown
        assert bot.rich_calls[0][2]["reply_parameters"].message_id == 11

        delivered = [ev for ev in events("checkup_triggered")
                     if str(ev.get("status") or "").startswith("report_sent")]
        assert delivered, events("checkup_triggered")
        fields = delivered[-1]
        assert fields["outcome"] == "success"
        assert fields["status"] == "report_sent"
        assert fields["level"] == "INFO"
        payload = json.loads(fields["source_ref_json"])
        assert payload["research_status"] == RESEARCH_COMPLETE
        assert payload["research_cause"] == "evidence_sufficient"
        assert payload["research_verdict"] == "complete"
        assert payload["delivery_channel"] == "rich_markdown"
        assert payload["report_chunks"] == 1
        assert "Причина" not in str(payload)   # текста отчёта в телеметрии нет

    @pytest.mark.asyncio
    async def test_healthy_checkup_complete_without_tools(
            self, clean_checkup, monkeypatch):
        _allow_policy(monkeypatch)
        monkeypatch.setattr(sr, "resolve_self_repo_identity", _diag_ctx)
        reader = _Reader([])
        llm = _ScriptedLLM([_text("Всё здорово, аномалий нет.")])
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("logs look clean", False))
        fetcher.last_state = ""
        fetcher.last_journal_state = ""
        checkup_mod.setup_checkup(CheckupService(llm), fetcher,
                                  diagnostics=False)
        checkup_mod.setup_checkup_tool_router(_router(reader))
        events = _capture_checkup_events(monkeypatch)
        bot = _Bot()

        await checkup_mod.checkup_handler(_handler_msg(), bot=bot)

        assert reader.calls == []
        assert llm.chat_calls == 1
        payload = json.loads(
            [ev for ev in events("checkup_triggered")
             if ev.get("status") == "report_sent"][-1]["source_ref_json"])
        assert payload["research_status"] == RESEARCH_COMPLETE
        assert payload["research_cause"] == "no_research_needed"
        assert payload["research_verdict"] == "complete"
        assert payload["research_calls"] == 0
        # Здоровый чекап без инструментов не получает пометку неполноты.
        assert "Примечание" not in bot.rich_calls[0][1].markdown

    @pytest.mark.asyncio
    async def test_handler_without_tool_runtime_marks_unresearched(
            self, clean_checkup, monkeypatch):
        """F1: handler запросил исследование, runtime=None → честная пометка.

        Не только телеметрия: доставленный отчёт несёт нейтральную пометку,
        а событие доставки — `report_sent_unresearched` (WARN).
        """
        _allow_policy(monkeypatch)
        monkeypatch.setattr(sr, "resolve_self_repo_identity", _diag_ctx)
        llm = _ScriptedLLM([_text("Всё здорово, аномалий нет.")])
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("logs look clean", False))
        fetcher.last_state = ""
        fetcher.last_journal_state = ""
        checkup_mod.setup_checkup(CheckupService(llm), fetcher,
                                  diagnostics=False)
        checkup_mod.setup_checkup_tool_router(None)
        events = _capture_checkup_events(monkeypatch)
        bot = _Bot()

        await checkup_mod.checkup_handler(_handler_msg(), bot=bot)

        assert llm.chat_calls == 0          # runtime не собран → plain-вызов
        report = bot.rich_calls[0][1].markdown
        assert "инструментальное исследование не выполнялось" in report
        assert "провайдер модели не принял" not in report
        delivered = [ev for ev in events("checkup_triggered")
                     if str(ev.get("status") or "").startswith("report_sent")]
        assert delivered, events("checkup_triggered")
        fields = delivered[-1]
        assert fields["outcome"] == "success"
        assert fields["status"] == "report_sent_unresearched"
        assert fields["level"] == "WARN"
        payload = json.loads(fields["source_ref_json"])
        assert payload["research_status"] == RESEARCH_NOT_EXECUTED
        assert payload["research_cause"] == "diagnostic_runtime_unavailable"
        assert payload["research_verdict"] == "not_executed"
        assert payload["delivery_channel"] == "rich_markdown"

    @pytest.mark.asyncio
    async def test_handler_delivery_unknown_does_not_duplicate(
            self, clean_checkup, monkeypatch):
        """F2: rich ушёл, ответ потерян по timeout → без второго отчёта."""
        _allow_policy(monkeypatch)
        monkeypatch.setattr(sr, "resolve_self_repo_identity", _diag_ctx)
        reader = _Reader([_base_payload()])
        llm = _ScriptedLLM([
            _round("c1", "read_source_code",
                   {"operation": "read", "path": PATH}),
            _text(REPORT_MD),
        ])
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("ERROR watchdog.jobs stuck",
                                                 False))
        fetcher.last_state = ""
        fetcher.last_journal_state = ""
        checkup_mod.setup_checkup(CheckupService(llm), fetcher,
                                  diagnostics=False)
        checkup_mod.setup_checkup_tool_router(_router(reader))
        events = _capture_checkup_events(monkeypatch)

        class _TimeoutAfterDeliveryBot(_Bot):
            async def send_rich_message(self, chat_id, rich, **kwargs):
                self.rich_calls.append((chat_id, rich, kwargs))
                self._mid += 1
                raise asyncio.TimeoutError()

        bot = _TimeoutAfterDeliveryBot()
        plain = AsyncMock()
        monkeypatch.setattr(checkup_mod, "send_chunked_reply", plain)

        await checkup_mod.checkup_handler(_handler_msg(), bot=bot)

        assert len(bot.rich_calls) == 1
        assert bot.sent == []
        assert plain.await_count == 0
        terminal = [ev for ev in events("checkup_triggered")
                    if ev.get("stage") == "final"]
        assert terminal, events("checkup_triggered")
        fields = terminal[-1]
        assert fields["outcome"] == "failed"
        assert fields["status"] == "delivery_unknown"
        assert fields["level"] == "WARN"
        payload = json.loads(fields["source_ref_json"])
        assert payload["delivery_channel"] == "delivery_unknown"
        assert payload["research_verdict"] == "complete"

    @pytest.mark.asyncio
    async def test_round0_transient_reports_unresearched(
            self, clean_checkup, monkeypatch):
        """S1/S5: plain-ответ после timeout — не complete; WARN unresearched."""
        _allow_policy(monkeypatch)
        monkeypatch.setattr(sr, "resolve_self_repo_identity", _diag_ctx)
        reader = _Reader([])
        llm = _ScriptedLLM([
            LLMTimeoutError("timeout", cause_class="ReadTimeout")])
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("logs", False))
        fetcher.last_state = ""
        fetcher.last_journal_state = ""
        checkup_mod.setup_checkup(CheckupService(llm), fetcher,
                                  diagnostics=False)
        checkup_mod.setup_checkup_tool_router(_router(reader))
        events = _capture_checkup_events(monkeypatch)
        bot = _Bot()

        await checkup_mod.checkup_handler(_handler_msg(), bot=bot)

        assert reader.calls == []
        assert bot.rich_calls and bot.sent == []
        delivered = [ev for ev in events("checkup_triggered")
                     if str(ev.get("status") or "").startswith("report_sent")]
        assert delivered, events("checkup_triggered")
        fields = delivered[-1]
        assert fields["outcome"] == "success"
        assert fields["status"] == "report_sent_unresearched"
        assert fields["level"] == "WARN"
        payload = json.loads(fields["source_ref_json"])
        assert payload["research_status"] == RESEARCH_NOT_EXECUTED
        assert payload["research_cause"] == "llm_error"
        assert payload["research_verdict"] == "not_executed"
        # Пометка неполноты реально доехала до доставленного отчёта.
        assert "это частичный результат" in bot.rich_calls[0][1].markdown


# ── Только контракт: без захардкоженных фраз production-лейна ──────────────

def test_runtime_has_no_phrase_hardcode():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for name in ("services/tool_loop.py", "services/checkup_service.py",
                 "handlers/checkup.py"):
        text = (root / name).read_text(encoding="utf-8").lower()
        assert "watchdog" not in text, name
        assert "посмотри по коду" not in text, name
