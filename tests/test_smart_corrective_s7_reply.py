"""ARCH_DECISION SMART-CORRECTIVE — Slice S7: продолжение доставленного чекапа.

Наблюдаемый контракт (production trace 16.11.2026, reply владельца
«Посмотри по коду по watchdog.jobs» на отчёт чекапа → 🗿, tool loop 0):

* **S7.1 структурный grant**: ход — reply на доставленный `checkup_report`,
  а план L1 не задал `diagnostic_research` → объявляются существующие
  read-only диагностические инструменты + каноническая identity своего repo
  (`target=self`). Вызов инструмента по-прежнему делает модель.
* **S7.2 pre-L1**: адресованный reply-to-bot не глушится детерминированным
  `SILENT/recent_reply` до планировщика — смысл решает L1.
* **S7.3 allowed-set**: прямой запрос (`MSG_EXPLICIT`/`MSG_QUESTION`/
  `has_question`) не получает `SILENT` в allowed-набор; post-parse demote
  `silent → reply` с причиной `explicit_request`.
* **S7.4 L1 empty/bad**: для адресованного reply-to-bot ход не завершается
  молчанием — существующий fallback-план отвечает текстом.
* **S7.5 L2 пуст + evidence**: детерминированный partial удалён (P0
  corrective owner 2026-11-25, §4) — программный «частичный отчёт» из
  технических данных не публикуется; ход закрывается честным состоянием
  (молчание 🗿), факты остаются в журнале/телеметрии.

Тестовые фразы живут только в этом файле; runtime-код их не содержит.
Сеть/БД/Telegram не используются: LLM/reader — детерминированные двойники,
роутер/цикл/сервис — реальные.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import diagnostic_policy as diag
from services import direct_chat_service as dcs
from services import direct_l1 as l1
from services import source_reader as sr
from services import tool_loop
from services.llm_client import LLMChatResult, LLMError, LLMToolCall
from services.tool_router import ToolDeps, ToolRouter
from tests.test_asap7_direct_l1 import (
    _FakeLLM,
    _FakeRouter,
    _bot_reply,
    _drive,
    _plan_json,
)

pytestmark = [pytest.mark.system2, pytest.mark.asap3]

CHAT_ID = -1009876543210
REPO = "Henry-Case-dev/adminbot"
DEPLOYED = "d" * 40
REPORT = "ЧЕКАП: job watchdog.jobs завершился ошибкой"
SNIPPET = "WATCHDOG_JOBS = ['daily', 'weekly']\n"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """Runtime-root автоопределение выключено (герметичность identity)."""
    monkeypatch.setattr(sr, "runtime_application_root", lambda: None)


def _diag_ctx():
    """Каноническая identity своего repo: читается deployed SHA, не master."""
    return {
        "target": "self", "repo": REPO, "ref": DEPLOYED,
        "ref_source": "deployed_sha", "deployed_sha": DEPLOYED,
        "checkout_sha": DEPLOYED, "deployed_matches_checkout": True,
        "local_source_verification": "verified", "dirty": False,
        "conflict": [], "identity_error": "", "note": "",
    }


def _allow_policy(monkeypatch):
    """Разрешить read-only диагностические инструменты (RBAC — отдельно)."""
    async def _allow(*args, **kwargs):
        return MagicMock(allowed=True, reason_code="allowed_public_class_default",
                         message_ru="", effect="allow", capability="",
                         role="project_owner", matrix_role="global_admin",
                         data_class="PUBLIC_TECH", source="default")
    monkeypatch.setattr(diag, "check_tool_call", _allow)


class _FakeReader:
    """Детерминированный двойник SourceReader: фиксирует ФАКТИЧЕСКИЙ ref."""

    def __init__(self):
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "status": "ok", "verified": True,
            "verified_url": f"https://github.com/{REPO}/blob/{DEPLOYED}/services/watchdog.py",
            "snippet": SNIPPET, "snippet_chars": len(SNIPPET),
            "read_level": "selected", "file_total_lines": 2,
            "line_range": [10, 12], "path": kwargs.get("path") or "",
            "repo": REPO, "ref": kwargs.get("ref") or "",
            "commit": kwargs.get("ref") or DEPLOYED,
            "provider": "github", "host": "github.com",
            "source_id": "src:s7", "provenance": {"sha256": "x"},
            "truncation": {}, "network_calls": 1,
        }


class _ScriptedLLM(_FakeLLM):
    """`_FakeLLM` + сценарий оркестратора (adaptive tool-фаза)."""

    def __init__(self, *, orchestrator=(), **kw):
        super().__init__(**kw)
        self.orchestrator = list(orchestrator)

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kwargs):
        if step != "orchestrator":
            return await super().generate(
                messages, temperature=temperature, chat_id=chat_id,
                module=module, step=step, correlation_id=correlation_id,
                **kwargs)
        self.calls.append({"step": step, "messages": messages,
                           "kwargs": kwargs, "correlation_id": correlation_id,
                           "module": module})
        await asyncio.sleep(0)
        if self.orchestrator:
            return self.orchestrator.pop(0)
        return json.dumps({"action": "finish", "reason": "enough"})


def _capture_l1_trace(monkeypatch):
    """Записать фактически зафиксированное L1-решение хода (не план-объект)."""
    notes: list = []
    real = dcs._ttrace.note_l1

    def _spy(correlation_id, **fields):
        notes.append(dict(fields))
        return real(correlation_id, **fields)

    monkeypatch.setattr(dcs._ttrace, "note_l1", _spy)
    return notes


def _capture_tool_schemas(monkeypatch, svc):
    """Захватить ФАКТИЧЕСКИ анонсированные tool-схемы хода."""
    seen: dict = {}
    real = svc._l1_tool_phase

    async def _spy(payload, tool_ctx, **kwargs):
        seen["tools"] = {
            str(s.get("function", {}).get("name") or "")
            for s in (kwargs.get("tool_schemas") or ())
            if isinstance(s, dict)}
        return await real(payload, tool_ctx, **kwargs)

    monkeypatch.setattr(svc, "_l1_tool_phase", _spy)
    return seen


def _checkup_turn(monkeypatch, llm, *, text="Посмотри по коду по watchdog.jobs",
                  reply=None, tool_router=None, reply_id=7,
                  report_id=7):
    """Reply владельца на доставленный отчёт чекапа (структурный факт)."""
    svc, react, bot, msg, user = _drive(
        monkeypatch, text, reply=(reply if reply is not None
                                  else _bot_reply(message_id=reply_id)),
        llm=llm, tool_router=tool_router)
    svc._bot_replied_recently = AsyncMock(return_value=True)
    svc._recent_bot_replies = AsyncMock(return_value=(REPORT,))
    # Доставленный отчёт живого окна: (текст, tg_message_id доставки).
    monkeypatch.setattr(
        dcs, "_recent_checkup_reports",
        AsyncMock(return_value=[(REPORT, report_id)]))
    monkeypatch.setattr(dcs, "_recent_checkup_report_text",
                        AsyncMock(return_value=REPORT))
    return svc, react, bot, msg, user


# ── S7.1: структурный grant (только объявление инструментов/identity) ────────


class TestStructuralDiagnosticGrant:
    def test_grant_requires_reply_to_delivered_report(self):
        assert l1.structural_diagnostic_research(
            "", reply_to_bot=True) is None
        assert l1.structural_diagnostic_research(
            REPORT, reply_to_bot=False) is None

    def test_grant_announces_existing_readonly_tools_target_self(self):
        grant = l1.structural_diagnostic_research(
            REPORT, reply_to_bot=True,
            report_message_id=501, reply_message_id=501)
        assert grant is not None
        assert grant.needed is True
        assert grant.target == "self"
        plan = l1.L1Plan()
        plan.diagnostic_research = grant
        # Ровно существующие capability двух read-only инструментов.
        assert l1.diagnostic_source_capabilities(plan) == (
            "source_code", "deep_diagnostics")
        # Ничего не запускается самим grant'ом: вызов — решение модели.
        assert plan.capabilities_needed == ()


# ── S7.2: pre-L1 recent_reply не решает за планировщика ─────────────────────


class TestPreL1RecentReply:
    @staticmethod
    def _ctx(**over):
        base = dict(addressed=True)
        base.update(over)
        return dcs.DecisionContext(**base)

    def _pre(self, context, *, l1_decides):
        return dcs._decision_pre_action(
            message_class=dcs.MSG_OTHER, context=context,
            toggles=dcs.DecisionToggles(), target_message_id=100,
            l1_decides=l1_decides)

    def test_addressed_reply_to_bot_reaches_l1(self):
        ctx = self._ctx(reply_to_bot=True, bot_replied_recently=True)
        action, reason, _, _ = self._pre(ctx, l1_decides=True)
        assert (action, reason) == (dcs.ACTION_REPLY, dcs.REASON_DEFAULT)

    def test_legacy_l1_off_keeps_old_suppression(self):
        ctx = self._ctx(reply_to_bot=True, bot_replied_recently=True)
        action, reason, _, _ = self._pre(ctx, l1_decides=False)
        assert (action, reason) == (
            dcs.ACTION_SILENT, dcs.REASON_RECENT_REPLY)

    def test_background_after_recent_reply_still_silent(self):
        """Обычный фон (не reply-to-bot) политика по-прежнему не будит."""
        ctx = self._ctx(reply_to_bot=False, bot_replied_recently=True)
        action, reason, _, _ = self._pre(ctx, l1_decides=True)
        assert (action, reason) == (
            dcs.ACTION_SILENT, dcs.REASON_RECENT_REPLY)


# ── S7.1 + C: сквозной ход владельца по доставленному чекапу ────────────────


class TestCheckupReportReply:
    @pytest.mark.asyncio
    async def test_source_reader_announced_without_plan_and_reads_deployed_sha(
            self, monkeypatch):
        _allow_policy(monkeypatch)
        reader = _FakeReader()
        router = ToolRouter(ToolDeps(search=None, memory=None,
                                     aliases=None, source_reader=reader))
        llm = _ScriptedLLM(
            # План НЕ просит diagnostic_research — это структурный ход.
            l1=_plan_json(),
            l2="по коду: расписание watchdog.jobs задаётся в конфиге",
            orchestrator=[
                json.dumps({"action": "call_tool",
                            "tool": "read_source_code",
                            "arguments": {"operation": "read",
                                          "path": "services/watchdog.py",
                                          "query": "watchdog jobs"},
                            "reason": "read_code"}),
                json.dumps({"action": "finish", "reason": "enough"}),
            ])
        monkeypatch.setattr(sr, "resolve_self_repo_identity", _diag_ctx)
        svc, react, bot, msg, user = _checkup_turn(
            monkeypatch, llm, tool_router=router)
        announced = _capture_tool_schemas(monkeypatch, svc)

        await svc.handle(bot, msg, user)

        # read_source_code был РЕАЛЬНО исполнен → он был в анонсе, хотя план
        # L1 решения не задавал; identity — deployed SHA, не «master».
        assert "read_source_code" in announced.get("tools", set())
        assert reader.calls, "read_source_code не исполнен без решения L1"
        call = reader.calls[0]
        assert call["ref"] == DEPLOYED
        assert call["repo"] == REPO
        # Ответ непустой: 🗿/REACT не используются.
        react.assert_not_awaited()
        svc._send_direct_answer.assert_awaited_once()
        delivered = svc._send_direct_answer.await_args.args[2]
        assert delivered
        # Реальные данные инструмента доехали до Writer'а.
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert SNIPPET.strip() in l2_text

    @pytest.mark.asyncio
    async def test_explicit_plan_needed_false_is_not_overridden(
            self, monkeypatch):
        """Явное решение модели `needed=false` структурный grant не меняет."""
        _allow_policy(monkeypatch)
        reader = _FakeReader()
        router = ToolRouter(ToolDeps(search=None, memory=None,
                                     aliases=None, source_reader=reader))
        llm = _ScriptedLLM(
            l1=_plan_json(diagnostic_research={"needed": False,
                                               "target": "self"}),
            l2="отвечаю без чтения кода",
            orchestrator=[json.dumps({"action": "call_tool",
                                      "tool": "read_source_code",
                                      "arguments": {"operation": "read"},
                                      "reason": "read_code"})])
        monkeypatch.setattr(sr, "resolve_self_repo_identity", _diag_ctx)
        svc, react, bot, msg, user = _checkup_turn(
            monkeypatch, llm, tool_router=router)
        announced = _capture_tool_schemas(monkeypatch, svc)

        await svc.handle(bot, msg, user)

        assert "read_source_code" not in announced.get("tools", set())
        assert reader.calls == []
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_l1_silent_on_explicit_request_demoted(
            self, monkeypatch):
        """S7.3: прямой запрос не глушится даже планом action=silent."""
        llm = _ScriptedLLM(
            l1=_plan_json(action="silent", confidence=0.95),
            l2="вот что по коду")
        svc, react, bot, msg, user = _checkup_turn(
            monkeypatch, llm, text="Найди в коде watchdog.jobs")
        notes = _capture_l1_trace(monkeypatch)

        await svc.handle(bot, msg, user)

        react.assert_not_awaited()
        svc._send_direct_answer.assert_awaited_once()
        assert any(item.get("action") == "reply"
                   and item.get("override") == "explicit_request"
                   for item in notes), notes

    @pytest.mark.asyncio
    async def test_l1_silent_casual_reply_to_bot_stays_silent(
            self, monkeypatch):
        """S7.3 не превращает в ответ НЕявный casual reply — L1 решает сам."""
        llm = _ScriptedLLM(
            l1=_plan_json(action="silent", confidence=0.95))
        svc, react, bot, msg, user = _drive(
            monkeypatch, "Ок", reply=_bot_reply(), llm=llm)

        await svc.handle(bot, msg, user)

        react.assert_awaited_once()
        assert react.await_args.kwargs.get("reaction") == "🗿"
        svc._send_direct_answer.assert_not_awaited()
        assert llm.calls_of("l2_writer") == []


# ── S7.4: L1 empty/bad для адресованного reply-to-bot → текстовый fallback ──


class TestL1EmptyFallback:
    @pytest.mark.asyncio
    async def test_empty_l1_on_addressed_reply_to_bot_answers(self, monkeypatch):
        # «Ок» — ACK: детерминированная матрица дала бы SILENT; L1 пуст.
        llm = _ScriptedLLM(l1="", l2="честный ответ на продолжение")
        svc, react, bot, msg, user = _checkup_turn(
            monkeypatch, llm, text="Ок")
        notes = _capture_l1_trace(monkeypatch)

        await svc.handle(bot, msg, user)

        react.assert_not_awaited()
        svc._send_direct_answer.assert_awaited_once()
        assert svc._send_direct_answer.await_args.args[2] == \
            "честный ответ на продолжение"
        assert any(item.get("action") == "reply"
                   and item.get("fallback") == "deterministic"
                   for item in notes), notes

    @pytest.mark.asyncio
    async def test_empty_l1_on_owner_request_after_report_answers(
            self, monkeypatch):
        """Production-сценарий S7: пустой L1 на текстовый reply владельца.

        До среза pre-L1 `silent/recent_reply` превращал такой ход в 🗿 даже
        при доступном Writer'е — ответ обязан состояться."""
        llm = _ScriptedLLM(l1="", l2="ответ по существу запроса")
        svc, react, bot, msg, user = _checkup_turn(monkeypatch, llm)
        notes = _capture_l1_trace(monkeypatch)

        await svc.handle(bot, msg, user)

        react.assert_not_awaited()
        svc._send_direct_answer.assert_awaited_once()
        assert svc._send_direct_answer.await_args.args[2] == \
            "ответ по существу запроса"
        assert any(item.get("action") == "reply"
                   and item.get("fallback") == "deterministic"
                   for item in notes), notes


# ── S7.5: пустой L2 + evidence → честное состояние, без программного отчёта ──
# P0 corrective (owner 2026-11-25, §4): детерминированный «частичный отчёт» из
# технических данных удалён. Пустой Writer после существующих recovery/retry не
# подменяется программным текстом: ход закрывается молчанием (🗿), а факты
# (инструменты/статусы) остаются в журнале прогона и телеметрии.


class TestEmptyL2WithEvidence:
    @pytest.mark.asyncio
    async def test_no_programmatic_report_instead_of_silence(self, monkeypatch):
        router = _FakeRouter(outputs={"get_recent_history":
                                      "вчера обсуждали watchdog.jobs"})
        llm = _ScriptedLLM(
            l1=_plan_json(tool_policy="auto",
                          capabilities_needed=["chat_history"]),
            l2="")                       # Writer вернул пусто
        svc, react, bot, msg, user = _drive(
            monkeypatch, "Что мы решали по watchdog.jobs?",
            llm=llm, tool_router=router)

        await svc.handle(bot, msg, user)

        # Инструмент реально исполнялся, но публикуемого программного текста
        # нет: ни «подтверждённых данных», ни «исследование остановлено».
        assert [d["tool"] for d in router.dispatched] == ["get_recent_history"]
        react.assert_awaited_once()
        svc._send_direct_answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_evidence_keeps_existing_silence(self, monkeypatch):
        """Пустые evidence → заглушка НЕ публикуется, прежний исход (🗿)."""
        llm = _ScriptedLLM(l1=_plan_json(), l2="")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "Что мы решали по watchdog.jobs?", llm=llm)

        await svc.handle(bot, msg, user)

        react.assert_awaited_once()
        svc._send_direct_answer.assert_not_awaited()

    def test_failure_state_is_structured_not_prose(self):
        """Внутреннее состояние остаётся структурным (без пользовательского
        текста): коды/счётчики доступны диагностике."""
        items = [{"tool": "get_recent_history", "status": "error",
                  "error_code": "provider_unavailable", "output": ""}]
        state = tool_loop.failure_state("chain_timeout", items)
        assert state["status"] == "no_generative_path"
        assert state["stop_reason"] == "chain_timeout"
        assert state["failed_tools"] == ["get_recent_history"]
        assert state["calls"] == 1
        assert not any(isinstance(value, str) and "\n" in value
                       for value in state.values())


# ── Никаких захардкоженных фраз production-лейна ────────────────────────────


def test_runtime_has_no_phrase_hardcode():
    root = pathlib.Path(__file__).resolve().parents[1]
    for name in ("services/direct_chat_service.py", "services/direct_l1.py",
                 "services/tool_loop.py"):
        text = (root / name).read_text(encoding="utf-8").lower()
        assert "watchdog" not in text, name
        assert "посмотри по коду" not in text, name


# ── Reviewer «Needs Fixes» F1/F2 → P0 corrective: честность финализации ─────
# F1/F2 фиксировали честность ДЕТЕРМИНИРОВАННОГО partial'а. P0 corrective
# (owner 2026-11-25, §4) удалил сам механизм: внутренние технические данные не
# становятся разговорным текстом. Здесь проверяется новое состояние:
# структурное `failure_state` (диагностика) и отсутствие публикуемого текста.


def _envelope(*, status="ok", out_chars=0, tool="get_recent_history"):
    return {"tool": tool, "status": status, "error_code": "",
            "data": {}, "out_chars": out_chars}


def _items(*envelopes):
    return tool_loop._evidence_inventory(list(envelopes), [""] * len(envelopes))


class TestPartialSeamHonesty:
    def test_structured_state_names_failures_for_diagnostics(self):
        """Отказы/коды остаются доступными диагностике (не в речи)."""
        state = tool_loop.failure_state(
            "chain_timeout",
            _items(_envelope(status="error"), _envelope(out_chars=15)))
        assert state["stop_reason"] == "chain_timeout"
        assert state["failed"] == 1
        assert state["usable"] == 1
        assert "get_recent_history" in state["failed_tools"]

    def test_structured_state_has_no_publishable_text(self):
        """Структурное состояние не содержит разговорного текста/цитаты
        запроса: публикуемый текст формирует только модель."""
        state = tool_loop.failure_state(
            "empty", _items(_envelope(out_chars=15)))
        assert "Запрос:" not in str(state)
        assert "Исследование остановлено" not in str(state)
        assert "Подтверждённые данные" not in str(state)

    def test_delivered_artifact_state(self):
        state = tool_loop.failure_state("empty", _items(_envelope()),
                                        delivered=True)
        assert state["status"] == "delivered_artifact"

    @pytest.mark.asyncio
    async def test_empty_tool_output_keeps_existing_silence(self, monkeypatch):
        """Если данных нет и Writer пуст → прежний silence-path (🗿), без
        программной заглушки."""
        router = _FakeRouter(outputs={"get_recent_history": ""}, default="")
        llm = _ScriptedLLM(
            l1=_plan_json(tool_policy="auto",
                          capabilities_needed=["chat_history"]),
            l2="")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "Что мы решали по watchdog.jobs?", llm=llm,
            tool_router=router)

        await svc.handle(bot, msg, user)

        react.assert_awaited_once()
        assert react.await_args.args[0] is bot
        svc._send_direct_answer.assert_not_awaited()
        # Не тавтология: инструмент РЕАЛЬНО исполнялся (пустая выдача).
        assert [d["tool"] for d in router.dispatched] == ["get_recent_history"]


# ── Reviewer «Needs Fixes» R1 → P0 corrective: внутренний degraded-путь ─────
# R1 требовал не публиковать пустую выдачу инструмента как «подтверждённые
# данные». P0 corrective (owner 2026-11-25, §4) удалил программный partial
# целиком: пустая/непустая выдача остаётся в диагностике, а публикуемого
# текста нет. Проверяется РЕАЛЬНЫЙ `chat_with_tools` (роутер/цикл настоящие,
# LLM — детерминированный двойник с пустым финальным Writer'ом).

MESSAGES_R1 = [{"role": "user", "content": "почему упал деплой?"}]
TOOLS_R1 = [{"type": "function", "function": {"name": "execute_web_search"}}]


class _ToolLoopLLM:
    """`generate_chat` — исследование (tool_calls → LLMError позднего раунда),
    `generate` — существующий Writer-путь финальной фазы."""

    def __init__(self, *, finalize_text="", finalize_error=None):
        self.finalize_text = finalize_text
        self.finalize_error = finalize_error
        self.chat_calls = 0
        self.finalize_calls = 0
        self.finalize_messages = []

    async def generate_chat(self, messages, *, tools=None, **kwargs):
        self.chat_calls += 1
        if self.chat_calls == 1:
            return LLMChatResult(
                content=None,
                tool_calls=[LLMToolCall(id="c1", name="execute_web_search",
                                        arguments='{"query": "deploy"}')],
                finish_reason="tool_calls")
        raise LLMError("upstream 500")

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        self.finalize_calls += 1
        self.finalize_messages.append(messages)
        if self.finalize_error is not None:
            raise self.finalize_error
        return self.finalize_text


async def _degraded_run(output):
    """Одна tool-выдача `output`, затем деградация + пустой финальный Writer."""
    llm = _ToolLoopLLM(finalize_text="")
    router = _FakeRouter(outputs={"execute_web_search": output})
    out = await tool_loop.chat_with_tools(
        llm, [dict(m) for m in MESSAGES_R1], tools=TOOLS_R1, router=router,
        ctx=object(), chat_id=CHAT_ID)
    return out, router, llm


class TestInternalDegradedHonestState:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("output", ["", '{"status": "empty"}', "  \n\t  "])
    async def test_empty_tool_result_publishes_no_fake_reply(self, output):
        out, router, llm = await _degraded_run(output)
        text = str(out)
        # Не тавтология: инструмент РЕАЛЬНО исполнялся — журнал прогона есть.
        assert [d["tool"] for d in router.dispatched] == ["execute_web_search"]
        assert out.tool_results and out.tool_results[0]["tool"] == \
            "execute_web_search"
        assert out.degraded is True and out.reason == "llm_error"
        assert llm.finalize_calls == 1
        # P0 corrective (owner 2026-11-25 §4): ни «подтверждённых данных», ни
        # программной заглушки — только честное состояние.
        assert "Подтверждённые данные" not in text
        assert "0 символов" not in text
        assert out.finalize_mode == "no_generative_path"
        assert text == ""

    @pytest.mark.asyncio
    async def test_real_tool_data_kept_in_diagnostics_not_in_reply(self):
        """Реальные данные не публикуются программным текстом: они уходят в
        существующий Writer-путь (директива) и остаются в журнале."""
        out, router, llm = await _degraded_run("данные поиска")
        text = str(out)
        assert out.degraded is True and out.reason == "llm_error"
        assert out.finalize_mode == "no_generative_path"
        assert text == ""
        # Данные реально были доставлены финальному LLM-вызову (payload).
        tool_messages = [m for m in llm.finalize_messages[0]
                         if m.get("role") == "tool"]
        assert tool_messages and "данные поиска" in tool_messages[0]["content"]
        assert out.tool_results and out.tool_results[0]["status"] == "ok"


# ── Reviewer «Needs Fixes» F3/F4: телеметрия grant'а и адресность reply ─────


class TestGrantTelemetryAndAddressing:
    @pytest.mark.asyncio
    async def test_grant_visible_in_l1_telemetry(self, monkeypatch):
        """F3: диагностика L1 фиксирует РЕАЛЬНО объявленные инструменты."""
        _allow_policy(monkeypatch)
        reader = _FakeReader()
        router = ToolRouter(ToolDeps(search=None, memory=None,
                                     aliases=None, source_reader=reader))
        llm = _ScriptedLLM(l1=_plan_json(), l2="ответ по коду")
        monkeypatch.setattr(sr, "resolve_self_repo_identity", _diag_ctx)
        svc, react, bot, msg, user = _checkup_turn(
            monkeypatch, llm, tool_router=router)

        await svc.handle(bot, msg, user)

        diag = l1.get_l1_diagnostics(int(msg.chat.id))
        assert diag is not None, "диагностика L1 не записана"
        assert diag.get("diagnostic_needed") is True, diag
        assert diag.get("diagnostic_target") == "self", diag
        assert "source_code" in str(diag.get("diagnostic_sources") or "")

    def test_grant_requires_reply_to_the_delivered_report(self):
        """F4: reply на другое сообщение бота в окне grant не даёт."""
        assert l1.structural_diagnostic_research(
            REPORT, reply_to_bot=True,
            report_message_id=501, reply_message_id=777) is None
        assert l1.structural_diagnostic_research(
            REPORT, reply_to_bot=True,
            report_message_id=501, reply_message_id=None) is None
        grant = l1.structural_diagnostic_research(
            REPORT, reply_to_bot=True,
            report_message_id=501, reply_message_id=501)
        assert grant is not None and grant.needed is True

    @pytest.mark.asyncio
    async def test_recent_reports_expose_delivered_message_id(self):
        """F4: реальный durable ledger отдаёт id доставленного отчёта.

        Проводка без подмены helper'а: именно эту пару (текст, tg id) сверяет
        grant — иначе адресность была бы только на словах."""
        import time

        from services import bot_output_ledger as ledger
        from services.database import DatabaseService

        db = DatabaseService(":memory:")
        await db.initialize()
        try:
            await ledger.record_delivered_output(
                db, chat_id=CHAT_ID, tg_message_id=501, text=REPORT,
                output_kind="checkup_report", sent_at=int(time.time()),
                correlation_id="s7:f4")
            reports = await dcs._recent_checkup_reports(db, CHAT_ID)
        finally:
            await db.close()

        assert reports == [(REPORT, 501)], reports
        grant = l1.structural_diagnostic_research(
            reports[-1][0], reply_to_bot=True,
            report_message_id=reports[-1][1], reply_message_id=501)
        assert grant is not None and grant.needed is True
        assert l1.structural_diagnostic_research(
            reports[-1][0], reply_to_bot=True,
            report_message_id=reports[-1][1], reply_message_id=777) is None

    @pytest.mark.asyncio
    async def test_reply_to_other_bot_message_gets_no_grant(
            self, monkeypatch):
        """F4 e2e: reply на постороннее сообщение бота — инструментов нет."""
        llm = _ScriptedLLM(l1=_plan_json(), l2="отвечаю без чтения кода")
        svc, react, bot, msg, user = _checkup_turn(
            monkeypatch, llm, reply_id=777, report_id=7)
        announced = _capture_tool_schemas(monkeypatch, svc)

        await svc.handle(bot, msg, user)

        assert "read_source_code" not in announced.get("tools", set())
        svc._send_direct_answer.assert_awaited_once()

