"""A2 `tool-chains-round1026` (Эпик 3, Wave 2, ADR-1026-15; risk R3).

Покрытие §15/§16/§17:
* §16 (T-3528/T-3529/T-3530): out-of-band envelope на каждый вызов,
  структурированные ошибки, модельно-видимый канал байт-в-байт, reuse
  `ToolLoopResult` (аддитивный `tool_results`) / `ctx.tool_results`.
* §15 (T-3531/T-3532/T-3533): зависимые A→B последовательны, общий
  программный handoff `ctx.result_for`, контекстный резолв ссылки
  (`ctx.resolved_url`), отсутствие `asyncio.gather`.
* §17 (T-3534/T-3535/T-3536): cap 6 / мягкий тайм-аут 360 c / дедуп ≤2 /
  платные ≤4 / частичный результат с `chain_*`; kill-switch OFF → baseline.
* A2 `fetch_article` (T-3537/T-3538): атомарность, reuse extractor, JSON.
* R17 (T-3542): логи без аргументов/URL/текста; OFL/legacy-эквивалентность.
"""
import asyncio
import json
from unittest.mock import MagicMock

import pytest

from config.settings import settings
from services.llm_client import LLMChatResult, LLMError, LLMToolCall
from services.tool_loop import (
    CHAIN_CALL_LIMIT_REASON,
    CHAIN_COST_LIMIT_REASON,
    CHAIN_TIMEOUT_REASON,
    TOOL_CHAIN_MAX_METERED_CALLS,
    TOOL_CHAIN_TIMEOUT_SECONDS,
    TOOL_MAX_TOTAL_CALLS,
    ToolLoopResult,
    _TOOL_MAX_SAME_CALL,
    chat_with_tools,
)
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from services.tool_schemas import (
    ARTICLE_TOOL_NAME,
    TOOL_CALLING_TOOLS,
    TOOL_FETCH_ARTICLE,
    TOOL_GET_USER_CONTEXT,
    active_tools,
    factcheck_tools,
)
from services.smartmodule_urls import resolve_context_url
from services.web_content_extractor import WebContentExtractionFailedException

MESSAGES = [{"role": "user", "content": "вопрос"}]
TOOLS = [{"type": "function"}]


# ── фейки ────────────────────────────────────────────────────────────────


class FakeLLM:
    def __init__(self, answers):
        self._answers = list(answers)
        self.all_messages = []
        self.plain_generated = 0

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.all_messages.append([dict(m) for m in messages])
        if not self._answers:
            raise AssertionError("не хватило запланированных ответов")
        return self._answers.pop(0)

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        self.plain_generated += 1
        return "plain"


def _tc(call_id, name, args=None, raw=None):
    arguments = raw if raw is not None else json.dumps(args or {})
    return LLMChatResult(content=None,
                         tool_calls=[LLMToolCall(id=call_id, name=name,
                                                 arguments=arguments)],
                         finish_reason="tool_calls")


def _tc2(prefix, name_args):
    """Несколько tool_calls одним ходом: [(name, args), …]."""
    calls = [LLMToolCall(id=f"{prefix}_{i}", name=n,
                         arguments=json.dumps(a))
             for i, (n, a) in enumerate(name_args)]
    return LLMChatResult(content=None, tool_calls=calls,
                         finish_reason="tool_calls")


def _text(text):
    return LLMChatResult(content=text, tool_calls=None, finish_reason="stop")


class FakeRouter:
    def __init__(self, outputs=None, *, fn=None):
        self._outputs = dict(outputs or {})
        self._fn = fn
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, arguments))
        if self._fn is not None:
            return await self._fn(name, arguments, ctx)
        return self._outputs.get(name, f"данные:{name}")


class _RaiseRouter:
    def __init__(self, order):
        self._order = list(order)
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, arguments))
        nxt = self._order.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def _tool_contents(llm):
    return [m.get("content") for m in llm.all_messages[-1]
            if m.get("role") == "tool"]


# ── §16: envelope / structured errors ────────────────────────────────────


class TestEnvelope:
    @pytest.mark.asyncio
    async def test_envelope_recorded_on_every_call(self):
        llm = FakeLLM([_tc("c1", "execute_web_search", {"query": "новости"}),
                       _text("финал")])
        router = FakeRouter({"execute_web_search": "данные поиска"})
        ctx = ToolContext(-100, "q")
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ctx)
        assert out == "финал"
        assert len(out.tool_results) == 1
        env = out.tool_results[0]
        assert env["tool"] == "execute_web_search"
        assert env["round"] == 1
        assert env["status"] == "ok"
        assert env["metered"] is True
        assert env["duplicate"] is False
        assert env["attempt"] == 1
        assert env["out_chars"] == len("данные поиска")
        assert env["error_code"] == ""
        # R17: сырых аргументов в envelope нет — только короткий отпечаток.
        assert len(env["args_fingerprint"]) == 16
        assert "новости" not in json.dumps(env, ensure_ascii=False)
        # Спутник доступен и через ctx (общий handoff).
        assert ctx.tool_results == out.tool_results

    @pytest.mark.asyncio
    async def test_model_visible_channel_unchanged(self):
        llm = FakeLLM([_tc("c1", "execute_web_search", {"query": "x"}),
                       _text("финал")])
        router = FakeRouter({"execute_web_search": "res"})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        assert _tool_contents(llm) == ["res"]
        # Envelope НЕ утекает в модельный ввод.
        joined = json.dumps(llm.all_messages[1], ensure_ascii=False)
        assert "args_fingerprint" not in joined
        assert out.tool_context == "res"

    @pytest.mark.asyncio
    async def test_json_payload_becomes_data_and_truncated_flag(self):
        payload = json.dumps({"status": "ok", "markdown": "x" * 10,
                              "truncated": True}, ensure_ascii=False)
        llm = FakeLLM([_tc("c1", "fetch_article", {"url": "https://a.b/c"}),
                       _text("ок")])
        router = FakeRouter({"fetch_article": payload})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        env = out.tool_results[0]
        assert env["status"] == "ok"
        assert env["truncated"] is True
        assert env["data"]["markdown"] == "x" * 10

    @pytest.mark.asyncio
    async def test_structured_error_does_not_kill_llm(self):
        """SC-A2-06: одна упавшая — ответ жив; envelope error, цикл продолжен."""
        llm = FakeLLM([_tc("c1", "execute_web_search", {"query": "x"}),
                       _text("продолжаю несмотря ни на что")])
        router = _RaiseRouter([RuntimeError("внутренний взрыв")])
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        assert out == "продолжаю несмотря ни на что"
        assert out.degraded is False
        env = out.tool_results[0]
        assert env["status"] == "error"
        assert env["error_code"] == "tool_error"
        assert env["error_type"] == "RuntimeError"
        # Модель получила прежний различающий текст «ОШИБКА …».
        assert _tool_contents(llm)[0].startswith("ОШИБКА execute_web_search")

    @pytest.mark.asyncio
    async def test_structured_error_from_json_status(self):
        llm = FakeLLM([_tc("c1", "fetch_article", {"url": "https://a.b/c"}),
                       _text("ок")])
        router = FakeRouter(
            {"fetch_article": json.dumps({"status": "error", "error": "timeout"})})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        env = out.tool_results[0]
        assert env["status"] == "error"
        assert env["error_code"] == "timeout"

    @pytest.mark.asyncio
    async def test_tool_loop_result_reuse_additive(self):
        """Ключи tool_trace сохранены байт-в-байт; добавлен tool_results."""
        llm = FakeLLM([_tc("c1", "query_chat_memory", {"query": "b"}),
                       _text("финал")])
        router = FakeRouter({"query_chat_memory": "B"})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        assert out.tool_trace == [{"round": 1, "tool": "query_chat_memory",
                                   "ok": True, "out_chars": 1}]
        assert isinstance(out, ToolLoopResult) and isinstance(out, str)
        assert out.tool_results[0]["metered"] is False   # free/local


# ── §15: chains / context URL ────────────────────────────────────────────


class TestChains:
    @pytest.mark.asyncio
    async def test_dependent_chain_a_then_b_sequential(self):
        """A (search) → B (memory) — последовательно, B видит результат A."""
        seen = {}

        async def _fn(name, arguments, ctx):
            seen[name] = ctx.result_for("execute_web_search")
            return f"out:{name}"

        llm = FakeLLM([_tc("c1", "execute_web_search", {"query": "a"}),
                       _tc("c2", "query_chat_memory", {"query": "b"}),
                       _text("финал")])
        router = FakeRouter(fn=_fn)
        ctx = ToolContext(-100, "q")
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ctx)
        assert [c[0] for c in router.calls] == ["execute_web_search",
                                                "query_chat_memory"]
        assert [t["tool"] for t in out.tool_trace] == ["execute_web_search",
                                                       "query_chat_memory"]
        # A→B: результат A (envelope) доступен инструменту B через ctx.
        assert seen["query_chat_memory"] is not None
        assert seen["query_chat_memory"]["tool"] == "execute_web_search"

    def test_no_asyncio_gather_in_chain_sources(self):
        """D4: параллельность не вводится (обоснованная последовательность)."""
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for rel in ("services/tool_loop.py", "services/tool_router.py"):
            src = (root / rel).read_text(encoding="utf-8")
            assert "asyncio.gather" not in src, rel

    def test_resolve_context_url_single_current(self):
        assert resolve_context_url("смотри https://example.com/a") == \
            "https://example.com/a"

    def test_resolve_context_url_falls_back_to_reply(self):
        assert resolve_context_url("без ссылки", "тут https://ex.org/b.") == \
            "https://ex.org/b"

    def test_resolve_context_url_ambiguous_returns_none(self):
        assert resolve_context_url(
            "https://a.com/1 и https://b.com/2", "https://c.com/3") is None

    def test_resolve_context_url_no_url_returns_none(self):
        assert resolve_context_url("просто текст", None, "") is None

    @pytest.mark.asyncio
    async def test_no_per_phrase_handler(self):
        """Механизм инструмент-агностичный: две любые пары работают без хардкода."""
        for first, second in (("execute_web_search", "compile_lore_story"),
                              ("dig_into_lore", "get_recent_history")):
            llm = FakeLLM([_tc("c1", first, {"query": "x"}),
                           _tc("c2", second, {"query": "y"}),
                           _text("ok")])
            router = FakeRouter()
            await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                  ctx=ToolContext(-100, "q"))
            assert [c[0] for c in router.calls] == [first, second]


# ── §17: limits ──────────────────────────────────────────────────────────


class TestLimits:
    @pytest.mark.asyncio
    async def test_total_call_cap_six(self):
        # 2 free-вызова/раунд × 4 раунда = 8 запрошено; cap 6 → 6 исполнено.
        answers = [
            _tc2(f"r{r}", [("query_chat_memory", {"query": f"q{r}a"}),
                           ("query_chat_memory", {"query": f"q{r}b"})])
            for r in range(4)]
        llm = FakeLLM(answers)
        router = FakeRouter()
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        assert len(router.calls) == TOOL_MAX_TOTAL_CALLS == 6
        assert out.degraded is True
        assert out.reason == CHAIN_CALL_LIMIT_REASON
        skipped = [e for e in out.tool_results if e["status"] == "skipped"]
        assert skipped and skipped[-1]["error_code"] == CHAIN_CALL_LIMIT_REASON

    @pytest.mark.asyncio
    async def test_metered_call_limit_four(self):
        # 4 платных (search) исполняются, 5-й — structural skip + cost degrade.
        answers = [
            _tc2(f"r{r}", [("execute_web_search", {"query": f"q{r}0"}),
                           ("execute_web_search", {"query": f"q{r}1"})])
            for r in range(3)]
        llm = FakeLLM(answers)
        router = FakeRouter()
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        assert len(router.calls) == TOOL_CHAIN_MAX_METERED_CALLS == 4
        assert out.reason == CHAIN_COST_LIMIT_REASON
        assert [e["metered"] for e in out.tool_results
                if e["status"] == "ok"] == [True] * 4

    @pytest.mark.asyncio
    async def test_free_calls_not_cost_limited(self):
        # 5 разных free-вызовов не упираются в лимит расходов (2+2+1 за раунд).
        answers = [
            _tc2("r0", [("query_chat_memory", {"query": "q0"}),
                        ("query_chat_memory", {"query": "q1"})]),
            _tc2("r1", [("query_chat_memory", {"query": "q2"}),
                        ("query_chat_memory", {"query": "q3"})]),
            _tc("r2", "query_chat_memory", {"query": "q4"}),
            _text("финал"),
        ]
        llm = FakeLLM(answers)
        router = FakeRouter()
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        assert len(router.calls) == 5
        assert out.degraded is False and out.reason == "ok"
        assert all(e["metered"] is False for e in out.tool_results)

    @pytest.mark.asyncio
    async def test_dedup_same_call_max_two(self):
        # Одинаковый вызов (имя+канон.аргументы) исполняется ≤2 раз.
        llm = FakeLLM([_tc("c1", "execute_web_search", {"query": "same"}),
                       _tc("c2", "execute_web_search", {"query": "same"}),
                       _tc("c3", "execute_web_search", {"query": "same"}),
                       _text("финал")])
        router = FakeRouter({"execute_web_search": "RES"})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        assert len(router.calls) == _TOOL_MAX_SAME_CALL == 2
        dup = [e for e in out.tool_results if e["duplicate"]]
        assert len(dup) == 1 and dup[0]["attempt"] == 3
        # Модельно-видимый content повтора — прежний результат (идемпотентно).
        assert _tool_contents(llm) == ["RES", "RES", "RES"]

    @pytest.mark.asyncio
    async def test_adversarial_duplicate_storm(self):
        # «Шторм»: 2 одинаковых/раунд × 4 раунда → исполняется только 2.
        answers = [_tc2(f"r{r}", [("execute_web_search", {"query": "s"}),
                                  ("execute_web_search", {"query": "s"})])
                   for r in range(4)]
        llm = FakeLLM(answers)
        router = FakeRouter({"execute_web_search": "S"})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        assert len(router.calls) == 2
        assert len([e for e in out.tool_results if e["duplicate"]]) == 6
        assert out.reason == "round_limit"      # завершилось, не зависло

    @pytest.mark.asyncio
    async def test_soft_timeout_does_not_cancel_inflight(self, monkeypatch):
        monkeypatch.setattr("services.tool_loop.TOOL_CHAIN_TIMEOUT_SECONDS",
                            0.05)

        class SlowRouter:
            def __init__(self):
                self.completed = False

            async def dispatch(self, name, arguments, ctx):
                await asyncio.sleep(0.1)
                self.completed = True
                return "долгий результат"

        llm = FakeLLM([_tc("c1", "summarize_video", {}),
                       _text("не дошли")])
        router = SlowRouter()
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        # In-flight вызов не отменён: результат получен (round0) и сохранён.
        assert router.completed is True
        assert out.tool_results[0]["status"] == "ok"
        assert "долгий результат" in out.tool_context
        # Добор новых ограничен → мягкая деградация (round1 boundary).
        assert out.degraded is True and out.reason == CHAIN_TIMEOUT_REASON

    @pytest.mark.asyncio
    async def test_timeout_skips_new_calls(self, monkeypatch):
        monkeypatch.setattr("services.tool_loop.TOOL_CHAIN_TIMEOUT_SECONDS",
                            -1.0)
        llm = FakeLLM([_tc("c1", "execute_web_search", {"query": "x"}),
                       _text("финал")])
        router = FakeRouter()
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        assert router.calls == []
        assert out.reason == CHAIN_TIMEOUT_REASON
        assert out.tool_results[0]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_limits_off_no_cap(self, monkeypatch):
        monkeypatch.setattr(type(settings), "TOOL_CHAIN_LIMITS_ENABLED", False)
        answers = [
            _tc2(f"r{r}", [("execute_web_search", {"query": f"a{r}"}),
                           ("execute_web_search", {"query": f"b{r}"})])
            for r in range(4)]
        llm = FakeLLM(answers)
        router = FakeRouter()
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        assert len(router.calls) == 8           # cap не применяется
        assert out.reason == "round_limit"      # прежняя причина
        assert all(e["status"] == "ok" for e in out.tool_results)

    @pytest.mark.asyncio
    async def test_limits_off_does_not_change_model_visible(self, monkeypatch):
        """OFF vs ON (лимиты не срабатывают) → модельно-видимые артефакты равны."""
        def _run():
            return FakeLLM([_tc("c1", "execute_web_search", {"query": "x"}),
                            _text("финал tool-loop")])

        monkeypatch.setattr(type(settings), "TOOL_CHAIN_LIMITS_ENABLED", True)
        on_llm = _run()
        on = await chat_with_tools(on_llm, MESSAGES, tools=TOOLS,
                                   router=FakeRouter({"execute_web_search": "R"}),
                                   ctx=ToolContext(-100, "q"))
        monkeypatch.setattr(type(settings), "TOOL_CHAIN_LIMITS_ENABLED", False)
        off_llm = _run()
        off = await chat_with_tools(off_llm, MESSAGES, tools=TOOLS,
                                    router=FakeRouter({"execute_web_search": "R"}),
                                    ctx=ToolContext(-100, "q"))
        assert str(on) == str(off)
        assert on.tool_context == off.tool_context
        assert on.tool_trace == off.tool_trace
        assert _tool_contents(on_llm) == _tool_contents(off_llm)
        # Envelope остаётся out-of-band и при OFF.
        assert len(off.tool_results) == 1

    @pytest.mark.asyncio
    async def test_adversarial_mixed_errors(self):
        """Один упал, второй жив — оба envelope, финал есть."""
        llm = FakeLLM([_tc2("r", [("execute_web_search", {"query": "a"}),
                                  ("query_chat_memory", {"query": "b"})]),
                       _text("финал")])
        router = _RaiseRouter([RuntimeError("boom"), "живой результат"])
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        assert out == "финал"
        statuses = [e["status"] for e in out.tool_results]
        assert statuses == ["error", "ok"]

    @pytest.mark.asyncio
    async def test_adversarial_huge_output_truncation_flag(self):
        big = "x" * 5000 + "…"
        llm = FakeLLM([_tc("c1", "query_chat_memory", {"query": "q"}),
                       _text("финал")])
        router = FakeRouter({"query_chat_memory": big})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ToolContext(-100, "q"))
        env = out.tool_results[0]
        assert env["truncated"] is True
        assert env["out_chars"] == len(big)


# ── A2: fetch_article (атомарность / reuse / JSON) ───────────────────────


class FakeExtractor:
    def __init__(self, text="текст статьи " * 40, exc=None):
        self.text = text
        self.exc = exc
        self.calls = []

    async def extract(self, url, max_symbols):
        self.calls.append((url, max_symbols))
        if self.exc is not None:
            raise self.exc
        return self.text[:max_symbols]


def _article_router(extractor):
    return ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                               extractor=extractor))


class TestFetchArticle:
    def test_atomic_registration_canon_twelve(self):
        # A6 (ADR-1026-18 D1): канон 11 → 12 (get_user_context в хвост).
        assert len(TOOL_CALLING_TOOLS) == 12
        assert TOOL_CALLING_TOOLS[-1] is TOOL_GET_USER_CONTEXT
        assert TOOL_CALLING_TOOLS[10] is TOOL_FETCH_ARTICLE
        assert TOOL_FETCH_ARTICLE["function"]["name"] == ARTICLE_TOOL_NAME
        params = TOOL_FETCH_ARTICLE["function"]["parameters"]
        assert params["required"] == []
        assert params["additionalProperties"] is False
        assert params["properties"]["url"]["type"] == "string"

    def test_active_tools_gate_default_on(self):
        names = [t["function"]["name"] for t in active_tools()]
        assert ARTICLE_TOOL_NAME in names

    def test_active_tools_gate_off(self, monkeypatch):
        monkeypatch.setattr(type(settings), "ARTICLE_TOOL_ENABLED", False)
        names = [t["function"]["name"] for t in active_tools()]
        assert ARTICLE_TOOL_NAME not in names
        assert len(TOOL_CALLING_TOOLS) == 12    # схема/канон безусловны (A6)

    def test_factcheck_tools_unchanged(self):
        names = [t["function"]["name"] for t in factcheck_tools()]
        assert len(names) == 3
        assert ARTICLE_TOOL_NAME not in names

    async def _dispatch(self, router, arguments, ctx):
        return await router.dispatch("fetch_article", arguments, ctx)

    @pytest.mark.asyncio
    async def test_url_argument_and_json_contract(self):
        extractor = FakeExtractor(text="# Заголовок\n\n" + "тело " * 100)
        router = _article_router(extractor)
        raw = await self._dispatch(router, {"url": "https://example.com/a."},
                                   ToolContext(-100, "q"))
        payload = json.loads(raw)
        assert payload["status"] == "ok"
        assert payload["url"] == "https://example.com/a"   # нормализация
        assert payload["source_id"] and len(payload["source_id"]) == 12
        assert payload["chars"] == len(payload["markdown"])
        assert payload["truncated"] is False
        assert payload["title"] == "Заголовок"
        assert extractor.calls == [("https://example.com/a", 8000)]

    @pytest.mark.asyncio
    async def test_uses_resolved_url_from_context(self):
        extractor = FakeExtractor()
        router = _article_router(extractor)
        ctx = ToolContext(-100, "q", resolved_url="https://ctx.example/x")
        raw = await self._dispatch(router, {}, ctx)
        payload = json.loads(raw)
        assert payload["status"] == "ok"
        assert payload["url"] == "https://ctx.example/x"
        assert extractor.calls[0][0] == "https://ctx.example/x"

    @pytest.mark.asyncio
    async def test_no_url_is_honest_error(self):
        router = _article_router(FakeExtractor())
        raw = await self._dispatch(router, {}, ToolContext(-100, "q"))
        assert json.loads(raw) == {"status": "error", "error": "no_url"}

    @pytest.mark.asyncio
    async def test_extraction_failure_structured(self):
        extractor = FakeExtractor(
            exc=WebContentExtractionFailedException("all failed"))
        router = _article_router(extractor)
        raw = await self._dispatch(router, {"url": "https://a.b/c"},
                                   ToolContext(-100, "q"))
        payload = json.loads(raw)
        assert payload["status"] == "error"
        assert payload["error"] == "extract_failed"

    @pytest.mark.asyncio
    async def test_service_unavailable_when_extractor_none(self):
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock()))
        raw = await self._dispatch(router, {"url": "https://a.b/c"},
                                   ToolContext(-100, "q"))
        assert json.loads(raw)["error"] == "service_unavailable"

    @pytest.mark.asyncio
    async def test_truncated_flag_when_capped(self, monkeypatch):
        extractor = FakeExtractor(text="y" * 9000)
        router = _article_router(extractor)
        raw = await self._dispatch(router, {"url": "https://a.b/c"},
                                   ToolContext(-100, "q"))
        payload = json.loads(raw)
        assert payload["truncated"] is True
        assert payload["chars"] == 8000

    @pytest.mark.asyncio
    async def test_fetch_article_timeout(self, monkeypatch):
        monkeypatch.setattr("services.tool_router._ARTICLE_TOOL_TIMEOUT", 0.01)

        class SlowExtractor:
            async def extract(self, url, max_symbols):
                await asyncio.sleep(0.1)
                return "z" * 200

        router = _article_router(SlowExtractor())
        raw = await self._dispatch(router, {"url": "https://a.b/c"},
                                   ToolContext(-100, "q"))
        assert json.loads(raw)["error"] == "timeout"


# ── R17 / OFF-legacy / границы ───────────────────────────────────────────


class TestR17AndBoundaries:
    @pytest.mark.asyncio
    async def test_no_payload_in_logs(self, caplog):
        import logging
        secret = "SECRET_URL_https://leak.example/xyz"
        llm = FakeLLM([_tc("c1", "execute_web_search", {"query": secret}),
                       _text("финал")])
        router = FakeRouter({"execute_web_search": f"текст {secret}"})
        with caplog.at_level(logging.INFO):
            await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                  ctx=ToolContext(-100, "q"))
        for record in caplog.records:
            assert secret not in record.getMessage()

    @pytest.mark.asyncio
    async def test_degraded_log_r17_safe(self, caplog):
        import logging
        answers = [
            _tc2(f"r{r}", [("query_chat_memory", {"query": f"a{r}"}),
                           ("query_chat_memory", {"query": f"b{r}"})])
            for r in range(4)]
        with caplog.at_level(logging.WARNING):
            await chat_with_tools(FakeLLM(answers), MESSAGES, tools=TOOLS,
                                  router=FakeRouter(),
                                  ctx=ToolContext(-100, "q"))
        text = caplog.text
        assert "chain_call_limit" in text
        assert "q0" not in text and "a0" not in text

    @pytest.mark.asyncio
    async def test_fetch_article_url_not_logged(self, caplog):
        import logging
        url = "https://secret-article.example/path"
        router = _article_router(FakeExtractor())
        with caplog.at_level(logging.INFO):
            await router.dispatch("fetch_article", {"url": url},
                                  ToolContext(-100, "q"))
        for record in caplog.records:
            assert url not in record.getMessage()

    def test_kill_switches_not_in_catalog(self):
        import dataclasses
        from services import param_catalog as pc
        from config.settings import Settings
        fields = {f.name for f in dataclasses.fields(Settings)}
        for name in ("TOOL_CHAIN_LIMITS_ENABLED", "ARTICLE_TOOL_ENABLED"):
            assert name not in pc.REGISTRY
            assert name not in fields

    def test_catalog_counts_unchanged(self):
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 473
        assert len(pc.GROUPS) == 102
        assert len(pc._TAB_BY_GROUP) == 100
        assert len(pc.TAB_RULES) == 21

    def test_no_ddl_in_a2_sources(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for rel in ("services/tool_loop.py", "services/tool_router.py",
                    "services/tool_schemas.py",
                    "services/smartmodule_urls.py"):
            src = (root / rel).read_text(encoding="utf-8").lower()
            for forbidden in ("create table", "alter table", "create index"):
                assert forbidden not in src, f"{rel}: {forbidden}"

    def test_two_call_condition_preserved(self):
        """Пустой tool_trace → System 2 не вызывается (2-вызовность интактна)."""
        out = ToolLoopResult("ответ", rounds_used=1, tool_trace=[])
        assert bool(getattr(out, "tool_trace", None)) is False
        assert out.tool_results == []

    def test_off_legacy_effective_canon(self, monkeypatch):
        """Rollback-доказательство (D8/R3): ARTICLE_TOOL_ENABLED OFF →
        до-A2 канон без fetch_article; A6 get_user_context остаётся в хвосте
        (MEMORY_LOOKUP_ENABLED ON)."""
        monkeypatch.setattr(type(settings), "TOOL_CHAIN_LIMITS_ENABLED", False)
        monkeypatch.setattr(type(settings), "ARTICLE_TOOL_ENABLED", False)
        legacy = [
            "query_chat_memory", "dig_into_lore", "execute_web_search",
            "summarize_video", "download_media", "get_bot_health",
            "get_recent_history", "compile_lore_story", "generate_image",
            "transcribe_video", "get_user_context"]
        assert [t["function"]["name"]
                for t in active_tools(True, image_generation_enabled=True)] == \
            legacy
        # Схема остаётся в снапшоте (безусловна), но LLM её не видит.
        assert ARTICLE_TOOL_NAME not in [t["function"]["name"]
                                         for t in active_tools()]

