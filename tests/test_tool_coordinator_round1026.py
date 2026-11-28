"""A1 `tool-coordinator-round1026` (Эпик 3 Wave 1, §13/§14, ADR-1026-14 D1–D10).

Покрытие:
  * Координатор (программный слой в существующем Синтезаторе): намерение /
    адресат / необходимость памяти; выбор инструментов + оценка результатов;
    решение о действии ≠ текст (гейт Stage-2).
  * Общий механизм цепочек — reuse `tool_loop` (зависимые A→B последовательны;
    лимиты `TOOL_MAX_ROUNDS`/≤2-в-раунде; fail-open); отсутствие
    per-combination обработчиков.
  * Изоляция Вербализатора (только `stage2_payload` + стиль).
  * R17-safe наблюдаемость координатора.
  * Регресс живого direct-чата: OFF/legacy; 2-вызовность (`await_count==2`);
    отсутствие wire-`action`.
  * Границы diff (§104/§85-UI/DDL/каталог/промпты), версия/канон.
"""
import dataclasses
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import APP_VERSION, Settings
from services import param_catalog as pc
from services.direct_chat_service import (
    ACTION_REACT,
    ACTION_REPLY,
    ACTION_SILENT,
    ACTION_TOOL,
    ADDRESSEE_AUTHOR,
    ADDRESSEE_FORWARD,
    ADDRESSEE_REPLY,
    ADDRESSEE_UNKNOWN,
    COORDINATOR_ACTIONS,
    CoordinatorDecision,
    EVAL_DEGRADED,
    EVAL_FAILED,
    EVAL_NONE,
    EVAL_OK,
    EVAL_PARTIAL,
    INTENT_CHAT,
    INTENT_FORWARD,
    INTENT_IMAGE,
    INTENT_NOSTALGIA,
    INTENT_QUESTION,
    DirectChatService,
    _coordinator_addressee,
    _coordinator_choose_action,
    _coordinator_evaluate,
    _coordinator_intent,
    _coordinator_memory_need,
    _coordinator_tool_names,
    build_coordinator_decision,
    coordinator_enabled,
)
from services.llm_client import LLMChatResult, LLMError, LLMToolCall
from services.system2_handoff import parse_direct_synthesis, stage2_payload
from services.tool_loop import (
    ToolLoopResult,
    chat_with_tools,
)
from services.tool_schemas import TOOL_CALLING_TOOLS

# Единый канон публичных инструментов (состав и порядок). Это объявленный
# контракт, а не снимок байтов: добавление инструмента — осознанное изменение
# канона, удаление/перестановка/дубль ломают контракт.
# SELF-DIAG-01 D6-19/D6-20 (28.11.2026): +inspect_runtime, +prompt_readback.
TOOL_CANON = [
    "query_chat_memory", "dig_into_lore", "execute_web_search",
    "summarize_video", "download_media", "get_bot_health",
    "get_recent_history", "compile_lore_story", "generate_image",
    "transcribe_video", "fetch_article", "get_user_context",
    "recognize_image", "fact_check", "edit_image", "read_source_code",
    "inspect_runtime", "prompt_readback",
]

ROOT = Path(__file__).resolve().parents[1]

# Тесты System-2-контура (гейт Stage-2, 2-вызовность) — маркер снимает
# autouse-патч `_system2_flags_off_by_default` (tests/conftest.py) и держит
# прод-дефолты ON, как в test_direct_two_call_round1022.py.
pytestmark = pytest.mark.system2

_SYNTH_JSON = json.dumps({
    "user_question": "что там с погодой",
    "facts": [{"topic": "погода", "finding": "завтра дождь",
               "source": "exa", "confidence": "high"}],
    "answer_outline": "взять зонт",
    "limitations": [],
})


# ── Вспомогательные ────────────────────────────────────────────────────────

def _tc(name, call_id=None, arguments="{}"):
    return LLMToolCall(id=call_id or f"call_{name}", name=name,
                       arguments=arguments)


def _chat(content=None, tool_calls=None):
    return LLMChatResult(content=content, tool_calls=tool_calls,
                         finish_reason="tool_calls" if tool_calls else "stop")


class _FakeRouter:
    def __init__(self):
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, dict(arguments)))
        return f"out:{name}"


class _FakeToolLLM:
    """LLM для `chat_with_tools`: очередь ответов (или исключений)."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    async def generate_chat(self, messages, **kwargs):
        self.calls.append([dict(m) for m in messages])
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def generate(self, messages, **kwargs):
        return "PLAIN"


def _trace(*tools):
    return [{"round": i + 1, "tool": t, "ok": True, "out_chars": 5}
            for i, t in enumerate(tools)]


# ── 1. Координатор: чистые функции ─────────────────────────────────────────

class TestCoordinatorIntent:
    def test_image_marker_wins(self):
        assert _coordinator_intent("что угодно", image_fired=True,
                                   dig_fired=True, forward=True) == INTENT_IMAGE

    def test_nostalgia_marker(self):
        assert _coordinator_intent("помнишь", image_fired=False,
                                   dig_fired=True, forward=False) == INTENT_NOSTALGIA

    def test_forward(self):
        assert _coordinator_intent("текст", image_fired=False,
                                   dig_fired=False, forward=True) == INTENT_FORWARD

    def test_question(self):
        assert _coordinator_intent("как дела?", image_fired=False,
                                   dig_fired=False, forward=False) == INTENT_QUESTION

    def test_chat_default(self):
        assert _coordinator_intent("привет", image_fired=False,
                                   dig_fired=False, forward=False) == INTENT_CHAT


class TestCoordinatorAddressee:
    def test_forward(self):
        assert _coordinator_addressee(MagicMock(), forward=True,
                                      has_author=True) == ADDRESSEE_FORWARD

    def test_reply_target(self):
        m = MagicMock()
        m.reply_to_message = MagicMock()
        m.reply_to_message.from_user = MagicMock()
        assert _coordinator_addressee(m, forward=False,
                                      has_author=True) == ADDRESSEE_REPLY

    def test_author(self):
        m = MagicMock()
        m.reply_to_message = None
        assert _coordinator_addressee(m, forward=False,
                                      has_author=True) == ADDRESSEE_AUTHOR

    def test_unknown(self):
        m = MagicMock()
        m.reply_to_message = None
        assert _coordinator_addressee(m, forward=False,
                                      has_author=False) == ADDRESSEE_UNKNOWN


class TestCoordinatorMemoryAndTools:
    def test_memory_tool_detected(self):
        assert _coordinator_memory_need(
            ("query_chat_memory",), dig_fired=False, lore_compiled=False)

    def test_dig_pre_gate_detected(self):
        assert _coordinator_memory_need(
            (), dig_fired=True, lore_compiled=False)

    def test_no_memory_need(self):
        assert not _coordinator_memory_need(
            ("execute_web_search",), dig_fired=False, lore_compiled=False)

    def test_tool_names_order_and_dedup(self):
        trace = _trace("b", "a", "b")
        assert _coordinator_tool_names(trace) == ("b", "a")

    def test_tool_names_empty(self):
        assert _coordinator_tool_names([]) == ()


class TestCoordinatorEvaluation:
    def test_none(self):
        assert _coordinator_evaluate([], False) == EVAL_NONE

    def test_ok(self):
        assert _coordinator_evaluate(_trace("a", "b"), False) == EVAL_OK

    def test_partial(self):
        trace = [{"tool": "a", "ok": True}, {"tool": "b", "ok": False}]
        assert _coordinator_evaluate(trace, False) == EVAL_PARTIAL

    def test_failed(self):
        trace = [{"tool": "a", "ok": False}, {"tool": "b", "ok": False}]
        assert _coordinator_evaluate(trace, False) == EVAL_FAILED

    def test_degraded_wins(self):
        assert _coordinator_evaluate(_trace("a"), True) == EVAL_DEGRADED


class TestCoordinatorAction:
    def test_tool_action(self):
        assert _coordinator_choose_action(
            has_tools=True, degraded=False, lore_compiled=False) == ACTION_TOOL

    def test_reply_without_tools(self):
        assert _coordinator_choose_action(
            has_tools=False, degraded=False, lore_compiled=False) == ACTION_REPLY

    def test_reply_when_degraded(self):
        assert _coordinator_choose_action(
            has_tools=True, degraded=True, lore_compiled=False) == ACTION_REPLY

    def test_reply_when_lore_compiled(self):
        assert _coordinator_choose_action(
            has_tools=True, degraded=False, lore_compiled=True) == ACTION_REPLY

    def test_enum_members(self):
        assert set(COORDINATOR_ACTIONS) == {
            ACTION_REPLY, ACTION_REACT, ACTION_SILENT, ACTION_TOOL}


# ── 2. Сборка решения (0 LLM) ──────────────────────────────────────────────

class TestBuildCoordinatorDecision:
    def _build(self, raw, **over):
        kwargs = dict(query="привет", message=MagicMock(), raw=raw,
                      user_id=10, image_fired=False, dig_fired=False,
                      lore_compiled=False)
        kwargs.update(over)
        kwargs["message"].reply_to_message = None
        return build_coordinator_decision(**kwargs)

    def test_tool_turn(self):
        raw = ToolLoopResult("финал", rounds_used=2,
                             tool_trace=_trace("execute_web_search",
                                               "query_chat_memory"),
                             tool_context="логи")
        d = self._build(raw)
        assert isinstance(d, CoordinatorDecision)
        assert d.action == ACTION_TOOL
        assert d.tool_calls == ("execute_web_search", "query_chat_memory")
        assert d.evaluation == EVAL_OK
        assert d.memory_need is True
        assert d.intent == INTENT_CHAT
        assert d.enabled is True

    def test_plain_turn(self):
        raw = ToolLoopResult("просто ответ", rounds_used=1, tool_trace=[],
                             tool_context="")
        d = self._build(raw, query="как дела?")
        assert d.action == ACTION_REPLY
        assert d.tool_calls == ()
        assert d.evaluation == EVAL_NONE
        assert d.memory_need is False
        assert d.intent == INTENT_QUESTION

    def test_degraded_turn(self):
        raw = ToolLoopResult("частичный", rounds_used=4, degraded=True,
                             reason="round_limit",
                             tool_trace=_trace("execute_web_search"))
        d = self._build(raw)
        assert d.action == ACTION_REPLY
        assert d.evaluation == EVAL_DEGRADED

    def test_intent_image(self):
        raw = ToolLoopResult("x", rounds_used=1, tool_trace=[])
        d = self._build(raw, image_fired=True)
        assert d.intent == INTENT_IMAGE

    def test_never_raises_on_garbage(self):
        d = self._build(object())
        assert d.action == ACTION_REPLY


# ── 3. Общий механизм цепочек — reuse `tool_loop` ──────────────────────────

class TestChainMechanism:
    """A1 не создаёт per-combination обработчики: механизм цепочек — общий
    многораундовый `tool_loop` (ADR-1026-14 D3). Границы §15–§17 — A2."""

    @pytest.mark.asyncio
    async def test_dependent_calls_are_sequential(self):
        llm = _FakeToolLLM([
            _chat(tool_calls=[_tc("tool_a")]),
            _chat(tool_calls=[_tc("tool_b")]),
            _chat(content="финал"),
        ])
        router = _FakeRouter()
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "tool_a"}}],
            router=router, ctx=object())
        assert str(result) == "финал"
        # A→B — последовательно, в порядке вызова моделью.
        assert [c[0] for c in router.calls] == ["tool_a", "tool_b"]
        assert [e["tool"] for e in result.tool_trace] == ["tool_a", "tool_b"]
        # Результат A попал в следующий LLM-вызов (role "tool"), затем B.
        second = llm.calls[1]
        assert any(m.get("role") == "tool"
                   and m.get("content") == "out:tool_a" for m in second)
        third = llm.calls[2]
        assert any(m.get("role") == "tool"
                   and m.get("content") == "out:tool_b" for m in third)

    @pytest.mark.asyncio
    async def test_calls_per_round_not_truncated(self):
        """SMART-EXECUTION-RELIABILITY-01 §B1: все вызовы хода исполнены."""
        llm = _FakeToolLLM([
            _chat(tool_calls=[_tc("a"), _tc("b"), _tc("c")]),
            _chat(content="финал"),
        ])
        router = _FakeRouter()
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "a"}}],
            router=router, ctx=object())
        assert [c[0] for c in router.calls] == ["a", "b", "c"]
        assert len(result.tool_trace) == 3

    @pytest.mark.asyncio
    async def test_identical_repeats_stop_by_no_progress(self):
        """Фиксированного предела раундов нет; повтор того же вызова без
        изменения условий даёт честный stop `no_progress`."""
        llm = _FakeToolLLM([
            _chat(tool_calls=[_tc("a")]) for _ in range(6)
        ])
        router = _FakeRouter()
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "a"}}],
            router=router, ctx=object())
        assert result.degraded is True
        assert result.reason == "no_progress"
        # §G2/§G4: финальная фаза использует накопленные данные — ответ
        # писателя; программный partial/заглушка удалены (owner 2026-11-25 §4).
        assert result.finalize_mode == "llm"
        assert str(result) == "PLAIN"
        assert result.tool_results
        assert len(llm.calls) == 3

    @pytest.mark.asyncio
    async def test_late_llm_error_fail_open(self):
        llm = _FakeToolLLM([
            _chat(tool_calls=[_tc("a")]),
            LLMError("boom"),
        ])
        router = _FakeRouter()
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "a"}}],
            router=router, ctx=object())
        assert result.degraded is True
        assert result.reason == "llm_error"

    @pytest.mark.asyncio
    async def test_provider_reject_plain_fallback(self):
        llm = _FakeToolLLM([LLMError("no tools")])
        router = _FakeRouter()
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "a"}}],
            router=router, ctx=object())
        assert str(result) == "PLAIN"
        assert result.degraded is False

    def test_tool_loop_is_tool_agnostic(self):
        """Нет per-combination обработчиков: цикл не ветвится по именам
        инструментов, а диспетчеризует ЛЮБОЕ имя через общий `router.dispatch`."""
        src = (ROOT / "services" / "tool_loop.py").read_text(encoding="utf-8")
        assert "router.dispatch(tc.name, arguments, ctx)" in src
        assert "if tc.name ==" not in src
        assert "if tc.name in" not in src
        assert "if name ==" not in src

    def test_no_second_router_in_direct_service(self):
        src = (ROOT / "services" / "direct_chat_service.py").read_text(
            encoding="utf-8")
        assert "async def dispatch(" not in src


# ── 4. Изоляция Вербализатора + отсутствие wire-`action` ───────────────────

class TestNoWireAction:
    def test_stage1_contract_keys_unchanged(self):
        data = parse_direct_synthesis(_SYNTH_JSON)
        assert set(data.keys()) == {
            "user_question", "facts", "answer_outline", "limitations",
            "response_mode"}
        assert "action" not in data

    def test_stage2_payload_strips_service_fields(self):
        data = {"user_question": "q", "facts": [], "answer_outline": "o",
                "response_mode": "casual", "cover_prompt": "x"}
        payload = stage2_payload(data)
        assert "response_mode" not in payload
        assert "cover_prompt" not in payload
        assert "action" not in payload

    def test_decision_is_not_serialized(self):
        raw = ToolLoopResult("x", rounds_used=1, tool_trace=[])
        m = MagicMock()
        m.reply_to_message = None
        d = build_coordinator_decision(
            query="q", message=m, raw=raw, user_id=1, image_fired=False,
            dig_fired=False, lore_compiled=False)
        # Объект решения — внутренний; в Stage-контракты не попадает.
        assert isinstance(d, CoordinatorDecision)
        assert not hasattr(d, "to_json")


# ── 5. Наблюдаемость координатора на legacy-пути (L1 OFF) ──────────────────


def _drive_handle(monkeypatch, raw, *, enabled=True, lore=False):
    """Ход с выключенным L1: координатор строится, второго автора нет.

    RLR-02-LEGACY: гейт `_synthesize_direct_answer` удалён, поэтому мока
    Вербализатора больше нет — проверяется только наблюдаемость координатора
    и фактически доставленный текст (он же финал tool-loop).
    """
    import services.direct_chat_service as dcs
    from tests.test_direct_chat import _bot, _make_service, _message, _user
    monkeypatch.setattr(Settings, "DIRECT_COORDINATOR_ENABLED", enabled)
    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", False)
    svc = _make_service(tool_router=MagicMock())
    send = AsyncMock(return_value=None)
    svc._send_direct_answer = send

    async def fake_chat_with_tools(llm, payload, *, tools, router, ctx,
                                   temperature, chat_id, **kwargs):
        if lore:
            ctx.lore_compiled = True
            ctx.lore_story = "HTML история"
        return raw

    monkeypatch.setattr(dcs, "chat_with_tools", fake_chat_with_tools)
    return svc, send, _bot(), _message(), _user()


class TestCoordinatorObservability:
    @pytest.mark.asyncio
    async def test_r17_no_raw_text_in_logs(self, monkeypatch, caplog):
        raw = ToolLoopResult("финал", rounds_used=2,
                             tool_trace=_trace("execute_web_search"),
                             tool_context="СЕКРЕТ_ТУЛА")
        svc, _send, bot, msg, user = _drive_handle(monkeypatch, raw)
        query_secret = "СЕКРЕТ_ЗАПРОСА_42"
        msg.text = query_secret
        with caplog.at_level("INFO", logger="services.direct_chat_service"):
            await svc.handle(bot, msg, user)
        coord_lines = [r.getMessage() for r in caplog.records
                       if r.getMessage().startswith("[coordinator]")]
        assert coord_lines, "нет событий координатора"
        blob = "\n".join(coord_lines)
        assert query_secret not in blob
        assert "СЕКРЕТ_ТУЛА" not in blob
        assert "execute_web_search" in blob      # имя инструмента — безопасно

    @pytest.mark.asyncio
    async def test_off_no_coordinator_logs(self, monkeypatch, caplog):
        raw = ToolLoopResult("финал", rounds_used=2,
                             tool_trace=_trace("execute_web_search"),
                             tool_context="логи")
        svc, _send, bot, msg, user = _drive_handle(
            monkeypatch, raw, enabled=False)
        with caplog.at_level("INFO", logger="services.direct_chat_service"):
            await svc.handle(bot, msg, user)
        assert not [r for r in caplog.records
                    if r.getMessage().startswith("[coordinator]")]

    def test_kill_switch_default_on(self, monkeypatch):
        monkeypatch.setattr(Settings, "DIRECT_COORDINATOR_ENABLED", True)
        assert coordinator_enabled() is True

    def test_kill_switch_off(self, monkeypatch):
        monkeypatch.setattr(Settings, "DIRECT_COORDINATOR_ENABLED", False)
        assert coordinator_enabled() is False


# ── 6. Границы / версия / канон ────────────────────────────────────────────

class TestBounds:
    def _diff_names(self):
        # Рабочая дельта (staged+unstaged+untracked), а не накопленная история
        # от исторического baseline: старый baseline превращал любой релиз в
        # механический re-pin allowlist.
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain",
             "--untracked-files=all"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
        names = []
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            names.append(path.strip().strip('"').replace("\\", "/"))
        return names

    def test_forbidden_paths_out_of_worktree_diff(self):
        # §104/A3: user-owned канон (`plans/current_task.md`) и `db/` не
        # меняются в рабочем дереве. Исторический allowlist web/-путей заменён
        # каноническими контрактами: routes — tests/routes_contract.py,
        # каталог/DDL — F8-инварианты, AST-границы A3 — тесты ниже/рядом.
        names = self._diff_names()
        assert "plans/current_task.md" not in names
        assert not any(n.startswith("db/") for n in names)

    def test_version_and_catalog(self):
        from tests.version_contract import assert_version_contract
        assert_version_contract()
        # ASAP-3 (ADR-1028-2 D12, санкция spec §6): Δ +2 каталога-ключа → 483/423/458 (см. примечание в test_round1025_f8_registry).
        # ASAP5 §22 (27.10.2026): +5 «Типы медиа» → 587/466/562/121/119.
        assert len(pc.REGISTRY) == 668
        assert len({f.name for f in dataclasses.fields(Settings)}) == 477  # CFG-06 v2 (5af56d8b): +3 поля фактчек-конвейера; ASAP5 §22: +5 типов медиа ; MENU-01 (f8f11a01): +3 MINI_APP_* (deep-link mode/registration confirmed/short name, env-only) -> 471
        # PINS-258151 reissue (MEME-PIPELINE-REFACTOR-01 P2, 07627068):
        # +2 PG-only prompt-ключа prompts.meme_joke/prompts.meme_image →
        # categorized 570→572 (REGISTRY 597/GROUPS 121/TAB 119 переизданы
        # тем же лейном). Санкция: P2 spec §13; F8 emit+check EXIT=0.
        # MEMORY-07 (C-6 §5.2): +1 categorized ключ
        # flags.memory_communities_enabled → 572→573 (REGISTRY 598 тем же
        # лейном; санкция — принятая дельта каталога волны 3–4).
        assert len([s for s in pc.REGISTRY.values()
                    if s.category is not None]) == 642   # +4 temporal (mca-20), +5 типов медиа (ASAP5 §22)
        assert len(pc.GROUPS) == 121
        assert len(pc._TAB_BY_GROUP) == 119
        assert len(pc.TAB_RULES) == 23

    def test_canon_twelve_tools(self):
        # A2 (ADR-1026-15 D5): канон 10 → 11 (+fetch_article);
        # A6 (ADR-1026-18 D1): 11 → 12 (+get_user_context, в хвост).
        # MCA-19 (10.43): 12 → 13 (+recognize_image).
        # MCA-20 (10.44, ADR-1028-20 §7.5): 13 → 14 (+fact_check).
        # ASAP5 §20 (edit-route): 14 → 15 (+edit_image);
        # EVOL-SRC-READER (W6): 15 → 16 (+read_source_code);
        # SELF-DIAG-01 D6-19/D6-20: 16 → 18 (+inspect_runtime, +prompt_readback).
        names = [t["function"]["name"] for t in TOOL_CALLING_TOOLS]
        assert names == TOOL_CANON
        assert len(names) == len(set(names))

    def test_kill_switch_not_in_catalog(self):
        assert "DIRECT_COORDINATOR_ENABLED" not in pc.REGISTRY
        assert "DIRECT_COORDINATOR_ENABLED" not in {
            f.name for f in dataclasses.fields(Settings)}

    def test_no_ddl_in_coordinator_sources(self):
        for rel in ("services/direct_chat_service.py",
                    "services/tool_loop.py"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            assert "CREATE TABLE" not in src, rel
            assert "ALTER TABLE" not in src, rel
