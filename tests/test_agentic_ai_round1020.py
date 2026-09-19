"""Раунд 10.20 — Фаза G (БЛОК 7, Agentic AI), T-1926.

Тесты:
* T-1919 — fail-safe tool-loop: лимит раундов / LLMError позднего раунда →
  деградация (не исключение, не тишина), tool_trace, логирование потерянных
  раундов, сохранение контракта round==0/пустого финала;
* T-1920 — парсинг `reasoning_content` (алиасы) + обратная совместимость;
* T-1921 — stripper reasoning-тегов (позитив/негатив/мультистрочность/
  незакрытый тег);
* T-1922 — снятие канона «1-2 предложения» локально (general vs lore/factcheck);
* T-1923 — Context Middleware + приоритет метаданных над бюджет-капом;
* T-1924 — `graph_facts` v11→v12 (идемпотентность, provenance, ID-политика);
* T-1925 — EN-схемы тулов + строгая типизация (снапшот).
"""
import copy
import json
import logging
import sqlite3
from pathlib import Path

import httpx
import pytest

from services import direct_chat_service as dcs
from services.canonical_context import strip_context_header
from services.context_middleware import (
    context_item,
    metadata_header,
    truncate_keep_header,
)
from services.database import DatabaseService
from services.llm_client import (
    LLMBadResponseError,
    LLMError,
    LLMClient,
    LLMChatResult,
    LLMToolCall,
    NoApiKeyForChat,
)
from services.reply_postprocess import strip_reasoning_tags, REASONING_TAGS
from services.tool_loop import (
    TOOL_LOOP_FALLBACK_PHRASE,
    TOOL_MAX_ROUNDS,
    ToolLoopResult,
    chat_with_tools,
)
from services.tool_schemas import TOOL_CALLING_TOOLS

CHAT_ID = -1001234567890

# Реальный класс до monkeypatch (иначе повторный `_client` в цикле захватил бы
# уже подменённую фабрику).
_REAL_ASYNC_CLIENT = httpx.AsyncClient


# ── T-1919: fail-safe tool-loop ──────────────────────────────────────────


class _ScriptedLLM:
    def __init__(self, answers):
        self._answers = list(answers)
        self.calls = 0

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.calls += 1
        if not self._answers:
            raise AssertionError("не хватило ответов")
        return self._answers.pop(0)

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        return "plain"


class _Router:
    def __init__(self, output="данные"):
        self.output = output
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append(name)
        return self.output


def _tool_call(name="execute_web_search", args='{"query": "x"}'):
    return LLMChatResult(content=None,
                         tool_calls=[LLMToolCall(id="c", name=name,
                                                 arguments=args)],
                         finish_reason="tool_calls")


def _text(text):
    return LLMChatResult(content=text, tool_calls=None, finish_reason="stop")


class TestToolLoopFailSafe:
    @pytest.mark.asyncio
    async def test_round_limit_returns_answer_not_exception(self):
        llm = _ScriptedLLM([_tool_call() for _ in range(TOOL_MAX_ROUNDS)])
        out = await chat_with_tools(llm, [{"role": "user", "content": "q"}],
                                    tools=[], router=_Router(), ctx=object())
        assert isinstance(out, ToolLoopResult)
        assert str(out) == TOOL_LOOP_FALLBACK_PHRASE
        assert out.degraded is True and out.reason == "round_limit"
        assert out.rounds_used == TOOL_MAX_ROUNDS
        assert len(out.tool_trace) == TOOL_MAX_ROUNDS
        assert all(t["ok"] for t in out.tool_trace)

    @pytest.mark.asyncio
    async def test_round_limit_prefers_partial_content(self):
        # Модель надумала текст и тут же позвала тул; раунды кончились —
        # отдаём ПОСЛЕДНИЙ непустой content (не заглушку).
        answers = [LLMChatResult(content="уже почти ответ", tool_calls=[
            LLMToolCall(id="c", name="execute_web_search",
                        arguments='{"query": "x"}')],
            finish_reason="tool_calls")]
        for _ in range(TOOL_MAX_ROUNDS - 1):
            answers.append(_tool_call())
        llm = _ScriptedLLM(answers)
        out = await chat_with_tools(llm, [{"role": "user", "content": "q"}],
                                    tools=[], router=_Router(), ctx=object())
        assert out.degraded is True
        assert str(out) == "уже почти ответ"

    @pytest.mark.asyncio
    async def test_late_round_llm_error_degrades(self):
        class _Boom:
            def __init__(self):
                self.calls = 0

            async def generate_chat(self, *a, **k):
                self.calls += 1
                if self.calls == 1:
                    return LLMChatResult(content="частичный", tool_calls=[
                        LLMToolCall(id="c", name="execute_web_search",
                                    arguments='{"query": "x"}')],
                        finish_reason="tool_calls")
                raise LLMError("upstream 500")

        out = await chat_with_tools(_Boom(), [{"role": "user", "content": "q"}],
                                    tools=[], router=_Router(), ctx=object())
        assert out.degraded is True and out.reason == "llm_error"
        assert str(out) == "частичный"

    @pytest.mark.asyncio
    async def test_round_zero_llm_error_still_plain_fallback(self):
        class _Reject:
            async def generate_chat(self, *a, **k):
                raise LLMError("tools unsupported")

            async def generate(self, messages, temperature=None, chat_id=None,
                               **kwargs):
                return "обычный ответ"

        out = await chat_with_tools(_Reject(), [{"role": "user", "content": "q"}],
                                    tools=[], router=_Router(), ctx=object())
        assert str(out) == "обычный ответ"
        assert out.degraded is False and out.reason == "ok"

    @pytest.mark.asyncio
    async def test_no_api_key_propagates(self):
        class _NoKey:
            async def generate_chat(self, *a, **k):
                raise NoApiKeyForChat("no key", reason="chat")

        with pytest.raises(NoApiKeyForChat):
            await chat_with_tools(_NoKey(), [{"role": "user", "content": "q"}],
                                  tools=[], router=_Router(), ctx=object())

    @pytest.mark.asyncio
    async def test_empty_final_still_raises(self):
        llm = _ScriptedLLM([_tool_call(),
                            LLMChatResult(content=None, tool_calls=None,
                                          finish_reason="stop")])
        with pytest.raises(LLMBadResponseError):
            await chat_with_tools(llm, [{"role": "user", "content": "q"}],
                                  tools=[], router=_Router(), ctx=object())

    @pytest.mark.asyncio
    async def test_degraded_log_has_lost_rounds_and_no_text(self, caplog):
        class _LateBoom:
            def __init__(self):
                self.calls = 0

            async def generate_chat(self, *a, **k):
                self.calls += 1
                if self.calls == 1:
                    return _tool_call()
                raise LLMError("SECRET-TEXT-IN-ERROR")

        with caplog.at_level(logging.WARNING, logger="services.tool_loop"):
            out = await chat_with_tools(
                _LateBoom(), [{"role": "user", "content": "q"}],
                tools=[], router=_Router(), ctx=object())
        assert out.degraded is True
        text = caplog.text
        assert "degraded" in text and "lost_rounds=" in text
        assert "reason=llm_error" in text
        # R17: текст ошибки/аргументы в degrade-логе не печатаются
        assert "SECRET-TEXT-IN-ERROR" not in text

    @pytest.mark.asyncio
    async def test_tool_trace_records_execution(self):
        llm = _ScriptedLLM([_tool_call(), _text("финал")])
        out = await chat_with_tools(llm, [{"role": "user", "content": "q"}],
                                    tools=[], router=_Router("результат"),
                                    ctx=object())
        assert out.reason == "ok" and out.degraded is False
        assert out.tool_trace == [{"round": 1, "tool": "execute_web_search",
                                   "ok": True, "out_chars": len("результат")}]


# ── T-1920: парсинг reasoning_content ────────────────────────────────────


def _client(handler, monkeypatch):
    transport = httpx.MockTransport(handler)
    original = _REAL_ASYNC_CLIENT

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.llm_client.httpx.AsyncClient", factory)
    client = LLMClient("https://api.test/v1", "key", "chat", "embed")
    client.backoff_base = 0
    return client


def _resp(message, finish="stop"):
    return {"choices": [{"message": message, "finish_reason": finish}]}


class TestReasoningParsing:
    @pytest.mark.asyncio
    async def test_reasoning_only_returns_result(self, monkeypatch):
        seen = {}

        def handler(request):
            seen["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_resp(
                {"content": None, "reasoning_content": "черновик"}), request=request)

        client = _client(handler, monkeypatch)
        result = await client.generate_chat([{"role": "user", "content": "q"}],
                                            tools=[{"type": "function"}])
        assert result.content is None
        assert result.reasoning == "черновик"
        assert result.tool_calls is None

    @pytest.mark.asyncio
    async def test_reasoning_aliases(self, monkeypatch):
        for alias in ("reasoning_content", "reasoning", "thinking"):
            def handler(request, _alias=alias):
                return httpx.Response(
                    200, json=_resp({"content": None, alias: f"via-{_alias}"}),
                    request=request)

            client = _client(handler, monkeypatch)
            result = await client.generate_chat(
                [{"role": "user", "content": "q"}],
                tools=[{"type": "function"}])
            assert result.reasoning == f"via-{alias}"

    @pytest.mark.asyncio
    async def test_content_only_backcompat(self, monkeypatch):
        def handler(request):
            return httpx.Response(200, json=_resp({"content": "ответ"}),
                                  request=request)

        client = _client(handler, monkeypatch)
        result = await client.generate_chat([{"role": "user", "content": "q"}])
        assert result.content == "ответ"
        assert result.reasoning is None

    @pytest.mark.asyncio
    async def test_all_empty_still_raises(self, monkeypatch):
        def handler(request):
            return httpx.Response(200, json=_resp({"content": None}),
                                  request=request)

        client = _client(handler, monkeypatch)
        with pytest.raises(LLMBadResponseError):
            await client.generate_chat([{"role": "user", "content": "q"}],
                                       tools=[{"type": "function"}])


# ── T-1921: stripper reasoning-тегов ─────────────────────────────────────


class TestStripReasoningTags:
    def test_paired_tags_removed(self):
        for tag in REASONING_TAGS:
            text = f"до <{tag}>черновик</{tag}> после"
            assert strip_reasoning_tags(text) == "до  после"

    def test_multiple_and_multiline(self):
        text = ("итог\n<thinking>\nстрока 1\nстрока 2\n</thinking>\n"
                "<analysis>x</analysis>конец")
        assert strip_reasoning_tags(text) == "итог\n\nконец"

    def test_case_insensitive(self):
        assert strip_reasoning_tags("a <THOUGHT>x</Thought> b") == "a  b"

    def test_unclosed_truncates_to_end(self):
        assert strip_reasoning_tags("ответ <scratchpad>не закрыт...") == "ответ "

    def test_legitimate_lt_not_eaten(self):
        for text in ("5 < 10 & 7 > 3", "a < b, b > c", "тег <b>жирный</b>"):
            assert strip_reasoning_tags(text) == text

    def test_no_tags_is_noop_identity(self):
        text = "обычный текст без тегов"
        assert strip_reasoning_tags(text) == text

    def test_stray_closing_tag_removed(self):
        assert strip_reasoning_tags("a</thinking>b") == "ab"

    def test_cleanup_llm_text_includes_strip(self):
        from services.summary_cleanup import cleanup_llm_text
        assert cleanup_llm_text("X <reasoning>draft</reasoning> Y") == "X  Y"


# ── T-1922: локальное снятие канона «1-2 предложения» ─────────────────────


class TestCanonRemovalLocal:
    def test_general_answer_still_one_or_two_sentences(self):
        from services.chat_prompts import CHAT_SYSTEM_PROMPT
        assert "ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ" in CHAT_SYSTEM_PROMPT

    def test_lore_prompt_has_no_short_canon(self):
        from services.lore_prompts import LORE_STORY_SYSTEM_PROMPT
        assert "ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ" not in LORE_STORY_SYSTEM_PROMPT
        assert "3-6 абзацев" in LORE_STORY_SYSTEM_PROMPT

    def test_factcheck_prompt_allows_full_verdict(self):
        from services.factcheck_prompts import FACTCHECK_SYSTEM_PROMPT
        assert "ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ" not in FACTCHECK_SYSTEM_PROMPT
        assert "пару абзацев" in FACTCHECK_SYSTEM_PROMPT

    def test_tool_context_story_delivered(self):
        from services.tool_router import ToolContext
        ctx = ToolContext(CHAT_ID, "топик")
        ctx.lore_compiled = True
        ctx.lore_story = "<b>История</b>"
        assert ctx.lore_story == "<b>История</b>"


# ── T-1923: Context Middleware + приоритет заголовков ────────────────────


class TestContextMiddleware:
    def test_metadata_header_split(self):
        header, body = metadata_header("[12.09.2026 10:00 | Вася | msg:5]: текст")
        assert header.startswith("[12.09.2026 10:00 | Вася | msg:5]:")
        assert body == "текст"

    def test_no_header(self):
        assert metadata_header("просто текст") == ("", "просто текст")

    def test_header_survives_hard_cap_rag(self):
        block = "[12.09.2026 10:00 | Автор | fact:7]: " + "тело " * 2000
        out = truncate_keep_header(block, 3, kind="rag")
        assert out.startswith("[12.09.2026 10:00 | Автор | fact:7]:")
        assert out.startswith("[")

    def test_header_survives_for_global_and_thread(self):
        for kind in ("global", "thread"):
            block = "[12.09.2026 10:00 | Автор | msg:5]: " + "x" * 5000
            out = truncate_keep_header(block, 5, kind=kind)
            assert out.startswith("[12.09.2026 10:00 | Автор | msg:5]:")

    def test_header_only_when_budget_below_header(self):
        block = "[12.09.2026 10:00 | Автор | msg:5]: " + "x" * 5000
        out = truncate_keep_header(block, 0, kind="rag")
        assert out == "[12.09.2026 10:00 | Автор | msg:5]:"

    def test_no_header_falls_back_to_old_keep_end(self):
        text = "AAAA " * 100 + "BBBB " * 100
        out = truncate_keep_header(text, 10, kind="thread")
        assert "BBBB" in out  # keep-end (прежнее поведение)

    def test_no_header_global_keep_head(self):
        text = "AAAA " * 100 + "BBBB " * 100
        out = truncate_keep_header(text, 10, kind="global")
        assert "AAAA" in out and "BBBB" not in out

    def test_strip_context_header_reused(self):
        assert strip_context_header("[12.09.2026 10:00 | A | msg:5]: x") == "x"

    def test_context_item_alias(self):
        assert context_item(ts=None, text="t") == "t"

    def test_budget_preserves_header_and_measures(self):
        """Замер facts/chars до/после: метаданные целы при жёстком капе."""
        facts = [
            f"[0{i}.2024 | Автор | fact:{i}]: " + "длинный текст " * 50
            for i in range(1, 7)
        ]
        before_chars = sum(len(f) for f in facts)
        svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
        blocks = [("rag", "<RAG_Memory>\n" + "\n".join(facts) + "\n</RAG_Memory>")]
        result = svc._apply_context_budget(blocks, True, 200)
        after_chars = sum(len(t) for t in result)
        # инвариант приоритета: блок не пуст и заголовок первой строки цел
        assert result and result[0].startswith("<RAG_Memory>")
        assert "[" in result[0]
        assert before_chars > after_chars
        logging.getLogger(__name__).info(
            "middleware measurement | facts=%d | chars=%d -> %d",
            len(facts), before_chars, after_chars)


# ── T-1924: graph_facts v11→v12 ──────────────────────────────────────────

_V9_GRAPH_FACTS_DDL = """
CREATE TABLE graph_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
    fact TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN
        ('chat_history', 'search_fact', 'youtube_content', 'web_content',
         'bot_direct_reply', 'voice_transcript', 'video_transcript',
         'user_memory', 'history_import', 'derived_belief', 'bot_self_reply')),
    expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT,
    weight REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'confirmed',
    last_confirmed_at INTEGER, supersedes INTEGER,
    message_timestamp INTEGER
);
"""


def _create_v11_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(_V9_GRAPH_FACTS_DDL + """
        CREATE VIRTUAL TABLE graph_facts_fts USING fts5(
            fact, content='graph_facts', content_rowid='id', tokenize='unicode61');
        CREATE INDEX idx_graph_facts_chat_origin ON graph_facts(chat_id, origin);
    """)
    conn.execute(
        "INSERT INTO graph_facts (id, chat_id, fact, origin, created_at, "
        "target_user) VALUES (7, -100, 'вася любит озон', 'chat_history', "
        "1700000000, 'вася')")
    conn.execute(
        "INSERT INTO graph_facts_fts(rowid, fact) SELECT id, fact FROM graph_facts")
    conn.execute("PRAGMA user_version = 11")
    conn.commit()
    conn.close()


class TestGraphFactsV12:
    @pytest.mark.asyncio
    async def test_legacy_v11_migration_adds_columns_idempotent(self, tmp_path):
        path = tmp_path / "v11.db"
        _create_v11_db(path)
        d = DatabaseService(str(path))
        await d.initialize()
        cursor = await d.db.execute("PRAGMA table_info(graph_facts)")
        cols = {r["name"] for r in await cursor.fetchall()}
        assert {"tg_message_id", "forward_from"} <= cols
        cursor = await d.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 12
        # старые строки NULL-толерантны
        cursor = await d.db.execute(
            "SELECT tg_message_id, forward_from FROM graph_facts WHERE id=7")
        row = await cursor.fetchone()
        assert row["tg_message_id"] is None and row["forward_from"] == ""
        await d.close()
        # повторный init — no-op, данные не задвоены
        await d.initialize()
        cursor = await d.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 1
        await d.close()

    @pytest.mark.asyncio
    async def test_fresh_db_has_columns(self):
        d = DatabaseService(":memory:")
        await d.initialize()
        cursor = await d.db.execute("PRAGMA table_info(graph_facts)")
        cols = {r["name"] for r in await cursor.fetchall()}
        assert {"tg_message_id", "forward_from"} <= cols
        await d.close()

    @pytest.mark.asyncio
    async def test_id_policy_tg_vs_fact(self):
        d = DatabaseService(":memory:")
        await d.initialize()
        await d.insert_graph_fact(-100, "мем про озон", "chat_history", None,
                                  tg_message_id=555)
        cursor = await d.db.execute("SELECT id FROM graph_facts")
        fid = (await cursor.fetchone())["id"]
        rows = await d.search_graph_facts_fts(-100, '"озон"*', 5, 2_000_000_000)
        from services.canonical_context import resolve_item_id
        item_id = resolve_item_id(tg_message_id=rows[0]["tg_message_id"],
                                  fact_id=rows[0]["id"])
        assert item_id == "tg:555"
        # без tg_message_id → fact:<id>
        await d.insert_graph_fact(-100, "мем про погоду", "chat_history", None)
        rows2 = await d.search_graph_facts_fts(-100, '"погоду"*', 5,
                                               2_000_000_000)
        item_id2 = resolve_item_id(tg_message_id=rows2[0]["tg_message_id"],
                                   fact_id=rows2[0]["id"])
        assert item_id2.startswith("fact:")
        await d.close()

    @pytest.mark.asyncio
    async def test_rendering_with_provenance(self):
        from services.summary_memory import MemoryManager, build_rag_context

        d = DatabaseService(":memory:")
        await d.initialize()
        await d.insert_graph_fact(-100, "факт с форвардом", "chat_history",
                                  None, tg_message_id=777,
                                  forward_from="Канал X")
        memory = MemoryManager(d, llm=None)
        ctx = build_rag_context(await memory._search_graph_facts(
            -100, "форвардом", 5))
        assert "tg:777" in ctx
        assert "Переслано: Канал X" in ctx
        await d.close()

    def test_pg_noop(self):
        """PG — no-op: таблицы graph_facts в pg-слое нет (phantom не создаём)."""
        source = Path("services/pg_db.py").read_text(encoding="utf-8")
        assert "graph_facts" not in source


# ── T-1925: EN-схемы + строгая типизация ─────────────────────────────────


class TestToolSchemasEnCanon:
    def test_all_ten_descriptions_are_english(self):
        # 10.23 (F5/ADR-1023-5 D2): +generate_image → 9;
        # 10.24 (F19/ADR-1024-20 §2.1): +transcribe_video → 10.
        assert len(TOOL_CALLING_TOOLS) == 10
        for tool in TOOL_CALLING_TOOLS:
            fn = tool["function"]
            desc = fn["description"]
            assert desc.strip(), fn["name"]
            assert not any("\u0400" <= ch <= "\u04FF" for ch in desc), \
                f"кириллица в description: {fn['name']}"
            assert fn["parameters"]["additionalProperties"] is False

    def test_enums_and_numeric_bounds(self):
        def props(name):
            return next(t["function"]["parameters"]["properties"]
                        for t in TOOL_CALLING_TOOLS
                        if t["function"]["name"] == name)

        assert props("query_chat_memory")["time_range"]["enum"] == [
            "last_day", "last_week", "last_month", "all"]
        assert props("dig_into_lore")["mode"]["enum"] == [
            "messages", "facts", "both"]
        depth = props("get_recent_history")["depth"]
        assert depth["minimum"] == 1 and depth["maximum"] == 150
        # F14 (ADR-1024-15 §2.3-bis, UPD5): у summarize_video `mode` удалён
        # (только выжимка); источник — опциональный `url` + `source`.
        assert "mode" not in props("summarize_video")
        assert props("summarize_video")["source"]["enum"] == ["link", "reply"]

    def test_param_descriptions_are_english(self):
        for tool in TOOL_CALLING_TOOLS:
            for param, schema in tool["function"]["parameters"]["properties"].items():
                desc = schema.get("description") or ""
                assert not any("\u0400" <= ch <= "\u04FF" for ch in desc), \
                    f"{tool['function']['name']}.{param}"

    def test_names_order_and_required_unchanged(self):
        assert [t["function"]["name"] for t in TOOL_CALLING_TOOLS] == [
            "query_chat_memory", "dig_into_lore", "execute_web_search",
            "summarize_video", "download_media", "get_bot_health",
            "get_recent_history", "compile_lore_story", "generate_image",
            "transcribe_video"]
        assert TOOL_CALLING_TOOLS[0]["function"]["parameters"]["required"] == ["query"]

    def test_description_snapshot(self):
        snapshot = {
            t["function"]["name"]: t["function"]["description"]
            for t in TOOL_CALLING_TOOLS
        }
        assert snapshot["dig_into_lore"] == (
            "Use this for fast, factual lookups. Answers simple questions "
            "like 'Who owns X?', 'When did Y happen?'. Returns minimal, "
            "precise facts.")
        assert snapshot["compile_lore_story"] == (
            "Use this ONLY when the user asks to explain a meme, tell a "
            "story, or give a comprehensive historical overview of a topic. "
            "Heavy narrative tool.")
        assert "Search the web" in snapshot["execute_web_search"]
        assert "the bot's memory" in snapshot["query_chat_memory"]
