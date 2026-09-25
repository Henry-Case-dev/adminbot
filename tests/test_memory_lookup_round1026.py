"""A6 `memory-lookup-api-round1026` (Эпик 3, Wave 4, ADR-1026-18; risk R2).

Покрытие §32–§35 + §52 п.14 + §53:
* T-3611/T-3612: контракт `get_user_context`, атомарное расширение канона
  11→12 (в хвост; первые 11 — байт-в-байт), env-only kill-switch.
* T-3613/T-3614/T-3615/T-3616: purpose-роутинг, lazy RAG, капы, reuse.
* T-3617/T-3618: envelope из 5 полей §33, честность (unknown ≠ confirmed),
  структурированные not-valid аргументы, R17-лог.
* T-3619: adversarial-тесты (неоднозначность, отсутствие dump, фактчек=3).
"""
import json
from unittest.mock import MagicMock

import pytest

from config.settings import Settings, settings
from services.tool_loop import chat_with_tools
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from services.tool_schemas import (
    MEMORY_LOOKUP_TOOL_NAME,
    TOOL_CALLING_TOOLS,
    TOOL_GET_USER_CONTEXT,
    active_tools,
    factcheck_tools,
)


# ── фейки ────────────────────────────────────────────────────────────────


class FakeAliases:
    def __init__(self, mapping=None):
        self._aliases = {str(k): str(v) for k, v in (mapping or {}).items()}
        self._by_name = {v.casefold(): v for v in self._aliases.values()}

    def canon_name(self, name):
        text = str(name or "").strip()
        return self._by_name.get(text.casefold(), text)

    def resolve(self, user_id, nickname=None, username=None):
        alias = self._aliases.get(str(user_id))
        if alias:
            return str(alias)
        if nickname:
            return str(nickname)
        if username:
            return str(username).lstrip("@")
        return str(user_id)


def fact_row(fact, *, origin="chat_history", weight=0.8, status="confirmed",
             created_at=1700000000, tg=None, fid=1, target="Лёха",
             message_timestamp=None):
    return {
        "id": fid, "fact": fact, "origin": origin, "created_at": created_at,
        "target_user": target, "weight": weight, "status": status,
        "last_confirmed_at": created_at, "tg_message_id": tg,
        "message_timestamp": message_timestamp, "kind": "fact",
    }


class FakeDb:
    def __init__(self, *, facts=None, links=None, dossier=None, recent=None):
        self.facts = list(facts or [])
        self.links = list(links or [])
        self.dossier = dossier
        self.recent = list(recent or [])
        self.fact_calls = []
        self.card_calls = 0

    async def get_user_context_facts(self, chat_id, target_user, limit, now_ts):
        self.fact_calls.append((chat_id, target_user, limit))
        return self.facts[:limit]

    async def get_persona_card(self, chat_id, name, limit, now_ts):
        self.card_calls += 1
        return {"facts": [], "links": self.links[:limit]}

    async def get_generated_dossier(self, chat_id, target_user):
        return self.dossier

    async def get_recent_messages(self, chat_id, limit):
        return self.recent[-limit:]


class SpyMemory:
    def __init__(self, *, rag_facts=None, rows=None, context=""):
        self.rag_facts = list(rag_facts or [])
        self.rows = list(rows or [])
        self.context = context
        self.calls = []

    async def get_rag_facts(self, chat_id, query, **kwargs):
        self.calls.append("get_rag_facts")
        return list(self.rag_facts)

    async def search_long_term(self, chat_id, keywords_, limit):
        self.calls.append("search_long_term")
        return list(self.rows[:limit])

    async def get_rag_context(self, chat_id, query, **kwargs):
        self.calls.append("get_rag_context")
        return self.context

    async def vector_search(self, chat_id, query, limit):
        self.calls.append("vector_search")
        return []


def make_router(*, db=None, memory=None, aliases=None):
    return ToolRouter(ToolDeps(search=MagicMock(),
                               memory=memory if memory is not None
                               else SpyMemory(),
                               aliases=aliases, db=db))


async def call(router, arguments, ctx=None):
    ctx = ctx or ToolContext(-100, "q", user_id=5)
    return await router.dispatch(MEMORY_LOOKUP_TOOL_NAME, arguments, ctx)


def payload(raw):
    return json.loads(raw)


# ── T-3611/T-3612: контракт + атомарный канон ────────────────────────────


class TestContract:
    def test_schema_shape(self):
        tool = TOOL_GET_USER_CONTEXT
        assert tool["type"] == "function"
        fn = tool["function"]
        assert fn["name"] == MEMORY_LOOKUP_TOOL_NAME
        params = fn["parameters"]
        assert params["type"] == "object"
        assert params["additionalProperties"] is False
        assert params["required"] == ["person", "purpose"]
        props = params["properties"]
        assert props["person"]["type"] == "string"
        assert props["user_id"]["type"] == "integer"
        assert props["max_items"]["type"] == "integer"
        assert props["max_items"]["minimum"] == 1
        assert props["purpose"]["enum"] == [
            "identity", "appearance", "speech_style", "biography",
            "relationships", "general"]
        json.dumps(tool)

    def test_description_memory_not_factcheck(self):
        desc = TOOL_GET_USER_CONTEXT["function"]["description"]
        assert "NOT fact-checking" in desc
        assert "no_data" in desc
        # RU-строк в EN-description нет (канон 3.3).
        assert not any("\u0400" <= ch <= "\u04FF" for ch in desc)

    def test_canon_twelve_tail_only(self):
        assert len(TOOL_CALLING_TOOLS) == 12
        assert TOOL_CALLING_TOOLS[-1] is TOOL_GET_USER_CONTEXT
        assert [t["function"]["name"] for t in TOOL_CALLING_TOOLS] == [
            "query_chat_memory", "dig_into_lore", "execute_web_search",
            "summarize_video", "download_media", "get_bot_health",
            "get_recent_history", "compile_lore_story", "generate_image",
            "transcribe_video", "fetch_article", "get_user_context"]

    def test_first_eleven_byte_identical(self):
        from services.tool_schemas import (
            TOOL_COMPILE_LORE_STORY,
            TOOL_DIG_INTO_LORE,
            TOOL_DOWNLOAD_MEDIA,
            TOOL_EXECUTE_WEB_SEARCH,
            TOOL_FETCH_ARTICLE,
            TOOL_GENERATE_IMAGE,
            TOOL_GET_BOT_HEALTH,
            TOOL_GET_RECENT_HISTORY,
            TOOL_QUERY_CHAT_MEMORY,
            TOOL_SUMMARIZE_VIDEO,
            TOOL_TRANSCRIBE_VIDEO,
        )
        pinned = [TOOL_QUERY_CHAT_MEMORY, TOOL_DIG_INTO_LORE,
                  TOOL_EXECUTE_WEB_SEARCH, TOOL_SUMMARIZE_VIDEO,
                  TOOL_DOWNLOAD_MEDIA, TOOL_GET_BOT_HEALTH,
                  TOOL_GET_RECENT_HISTORY, TOOL_COMPILE_LORE_STORY,
                  TOOL_GENERATE_IMAGE, TOOL_TRANSCRIBE_VIDEO,
                  TOOL_FETCH_ARTICLE]
        assert TOOL_CALLING_TOOLS[:11] == pinned
        assert all(a is b for a, b in zip(TOOL_CALLING_TOOLS[:11], pinned))

    def test_active_tools_default_eleven(self):
        names = [t["function"]["name"] for t in active_tools()]
        assert len(names) == 11
        assert MEMORY_LOOKUP_TOOL_NAME in names
        assert "generate_image" not in names          # image OFF (дефолт)

    def test_active_tools_memory_off(self, monkeypatch):
        monkeypatch.setattr(type(settings), "MEMORY_LOOKUP_ENABLED", False)
        names = [t["function"]["name"] for t in active_tools()]
        assert MEMORY_LOOKUP_TOOL_NAME not in names
        # Baseline-активный набор (10 имён, image OFF) — байт-в-байт.
        assert names == [
            "query_chat_memory", "dig_into_lore", "execute_web_search",
            "summarize_video", "download_media", "get_bot_health",
            "get_recent_history", "compile_lore_story", "transcribe_video",
            "fetch_article"]
        assert len(TOOL_CALLING_TOOLS) == 12          # схема/канон безусловны

    def test_factcheck_tools_unchanged_three(self):
        names = [t["function"]["name"] for t in factcheck_tools()]
        assert len(names) == 3
        assert names == ["dig_into_lore", "compile_lore_story",
                         "execute_web_search"]
        assert MEMORY_LOOKUP_TOOL_NAME not in names

    def test_kill_switch_not_in_catalog(self):
        import dataclasses
        from services import param_catalog as pc
        assert "MEMORY_LOOKUP_ENABLED" not in pc.REGISTRY
        assert "MEMORY_LOOKUP_ENABLED" not in {
            f.name for f in dataclasses.fields(Settings)}
        assert len(pc.REGISTRY) == 473
        assert len(pc.GROUPS) == 102
        assert len(pc._TAB_BY_GROUP) == 100
        assert len(pc.TAB_RULES) == 21


# ── §52 п.14: невалидные аргументы ───────────────────────────────────────


class TestInvalidArguments:
    @pytest.mark.asyncio
    async def test_missing_person_and_user_id(self):
        out = payload(await call(make_router(), {"purpose": "general"}))
        assert out == {"status": "error", "error": "invalid_arguments",
                       "detail": "missing_person"}

    @pytest.mark.asyncio
    async def test_invalid_purpose(self):
        out = payload(await call(make_router(),
                                 {"person": "Лёха", "purpose": "future"}))
        assert out["error"] == "invalid_arguments"
        assert out["detail"] == "invalid_purpose"

    @pytest.mark.asyncio
    async def test_non_string_person(self):
        out = payload(await call(make_router(),
                                 {"person": 123, "purpose": "identity"}))
        assert out["detail"] == "invalid_person"

    @pytest.mark.asyncio
    async def test_bad_max_items(self):
        for bad in (0, -3, "x", True):
            out = payload(await call(
                make_router(),
                {"person": "Лёха", "purpose": "general", "max_items": bad}))
            assert out["detail"] == "invalid_max_items", bad

    @pytest.mark.asyncio
    async def test_non_int_user_id_without_person(self):
        out = payload(await call(make_router(),
                                 {"user_id": "abc", "purpose": "identity"}))
        assert out["detail"] == "invalid_person"

    @pytest.mark.asyncio
    async def test_invalid_does_not_crash_chain(self):
        """§52 п.14: структурная ошибка не роняет цепочку/другие инструменты."""
        from services.llm_client import LLMChatResult, LLMToolCall

        class FakeLLM:
            def __init__(self, answers):
                self._answers = list(answers)

            async def generate_chat(self, messages, **kwargs):
                return self._answers.pop(0)

            async def generate(self, messages, **kwargs):
                return "plain"

        def _tc(i, name, args):
            return LLMChatResult(
                content=None,
                tool_calls=[LLMToolCall(id=f"c{i}", name=name,
                                        arguments=json.dumps(args))],
                finish_reason="tool_calls")

        def _text(t):
            return LLMChatResult(content=t, tool_calls=None,
                                 finish_reason="stop")

        memory = SpyMemory(rows=[{"id": 1, "text": "привет",
                                  "timestamp": 1700000000, "user_id": 5,
                                  "tg_message_id": 9}])
        router = make_router(memory=memory)
        llm = FakeLLM([_tc(1, MEMORY_LOOKUP_TOOL_NAME, {"purpose": "general"}),
                       _tc(2, "query_chat_memory", {"query": "x"}),
                       _text("финал")])
        out = await chat_with_tools(llm, [{"role": "user", "content": "q"}],
                                    tools=TOOL_CALLING_TOOLS, router=router,
                                    ctx=ToolContext(-100, "q", user_id=5))
        assert str(out) == "финал"
        assert out.tool_results[0]["error_code"] == "invalid_arguments"
        assert out.tool_results[1]["status"] == "ok"


# ── T-3613/T-3614/T-3615/T-3616: purpose-роутинг + reuse ─────────────────


class TestPurposeRouting:
    @pytest.mark.asyncio
    async def test_identity_uses_alias_and_persona_facts(self):
        db = FakeDb(facts=[fact_row("любит чай", tg=456, fid=7)])
        aliases = FakeAliases({"5": "Лёха"})
        out = payload(await call(
            make_router(db=db, aliases=aliases),
            {"person": "лёха", "purpose": "identity"}))
        assert out["status"] == "ok"
        assert out["person"]["name"] == "Лёха"
        assert out["person"]["user_id"] == 5
        assert out["person"]["resolution"] == "resolved"
        assert out["facts"][0]["text"] == "любит чай"
        assert out["facts"][0]["source_id"] == "tg:456"
        assert out["confidence"]["label"] == "confirmed"
        assert "dossier" in out and out["dossier"]
        assert db.fact_calls and db.fact_calls[0][1] == "Лёха"

    @pytest.mark.asyncio
    async def test_appearance_filters_and_honest_no_data(self):
        db = FakeDb(facts=[
            fact_row("носит очки", fid=1),
            fact_row("любит чай", fid=2),
            fact_row("высокий рост", fid=3)])
        out = payload(await call(make_router(db=db, aliases=FakeAliases({"5": "Лёха"})),
                                 {"person": "Лёха", "purpose": "appearance"}))
        texts = [f["text"] for f in out["facts"]]
        assert "носит очки" in texts and "высокий рост" in texts
        assert "любит чай" not in texts
        assert out["no_data"] is False

    @pytest.mark.asyncio
    async def test_appearance_no_storage_honest(self):
        db = FakeDb(facts=[fact_row("любит чай")])
        out = payload(await call(make_router(db=db, aliases=FakeAliases({"5": "Лёха"})),
                                 {"person": "Лёха", "purpose": "appearance"}))
        assert out["no_data"] is True
        assert out["empty_reason"] == "no_storage_for_purpose"
        assert out["facts"] == []

    @pytest.mark.asyncio
    async def test_biography_includes_portrait(self):
        db = FakeDb(facts=[fact_row("работает в IT", fid=1)],
                    dossier={"portrait": "Портрет Лёхи", "patterns": [],
                             "themes": [], "updated_at": 1700000000})
        out = payload(await call(make_router(db=db, aliases=FakeAliases({"5": "Лёха"})),
                                 {"person": "Лёха", "purpose": "biography"}))
        texts = [f["text"] for f in out["facts"]]
        assert "работает в IT" in texts
        assert "Портрет Лёхи" in texts
        portrait = [f for f in out["facts"]
                    if f["source_id"] == "dossier_portrait"][0]
        assert portrait["confidence"] == "unknown"
        assert "dossier" in out

    @pytest.mark.asyncio
    async def test_relationships_uses_links(self):
        db = FakeDb(links=[{"source_name": "Лёха", "relation_type": "друг",
                            "target_name": "Петя"}])
        out = payload(await call(make_router(db=db, aliases=FakeAliases({"5": "Лёха"})),
                                 {"person": "Лёха", "purpose": "relationships"}))
        assert out["facts"][0]["text"] == "Лёха (друг) Петя"
        assert out["sources"][0]["kind"] == "edge"
        assert db.card_calls == 1

    @pytest.mark.asyncio
    async def test_relationships_empty_honest(self):
        out = payload(await call(make_router(db=FakeDb(links=[]),
                                             aliases=FakeAliases({"5": "Лёха"})),
                                 {"person": "Лёха", "purpose": "relationships"}))
        assert out["no_data"] is True
        assert out["empty_reason"] == "empty"

    @pytest.mark.asyncio
    async def test_general_uses_rag_sources(self):
        memory = SpyMemory(
            rag_facts=[("chat_history", "факт про Лёху", 1700000000, "Лёха")],
            rows=[{"id": 3, "text": "сообщение про Лёху",
                   "timestamp": 1700000100, "user_id": 9, "tg_message_id": 88}])
        out = payload(await call(make_router(memory=memory, aliases=FakeAliases({"5": "Лёха"})),
                                 {"person": "Лёха", "purpose": "general"}))
        assert {"get_rag_facts", "search_long_term"} <= set(memory.calls)
        assert out["facts"][0]["text"] == "факт про Лёху"
        kinds = {s["kind"] for s in out["sources"]}
        assert "rag" in kinds and "message" in kinds

    @pytest.mark.asyncio
    async def test_speech_style_from_bounded_slice(self):
        recent = [
            {"id": i, "text": f"сообщение {i}", "user_id": 5,
             "timestamp": 1700000000 + i, "tg_message_id": i}
            for i in range(1, 8)]
        db = FakeDb(recent=recent,
                    dossier={"portrait": "", "patterns": ["короткие фразы"],
                             "themes": ["игры"], "updated_at": 1700000000})
        memory = SpyMemory()
        out = payload(await call(
            make_router(db=db, memory=memory, aliases=FakeAliases({"5": "Лёха"})),
            {"person": "Лёха", "purpose": "speech_style"}))
        texts = [f["text"] for f in out["facts"]]
        assert "сообщение 7" in texts
        assert any("Паттерны речи" in t for t in texts)
        assert memory.calls == []          # срез достаточен → RAG не нужен


# ── T-3616: lazy RAG on/off ──────────────────────────────────────────────


class TestLazyRag:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("purpose,args", [
        ("identity", {"person": "Лёха", "purpose": "identity"}),
        ("appearance", {"person": "Лёха", "purpose": "appearance"}),
        ("biography", {"person": "Лёха", "purpose": "biography"}),
        ("relationships", {"person": "Лёха", "purpose": "relationships"}),
    ])
    async def test_rag_off_for_non_rag_purposes(self, purpose, args):
        memory = SpyMemory(rag_facts=[("x", "y", 1, "z")], rows=[
            {"id": 1, "text": "t", "timestamp": 1, "user_id": 5}])
        db = FakeDb(facts=[fact_row("носит очки")],
                    links=[{"source_name": "A", "relation_type": "r",
                            "target_name": "B"}])
        await call(make_router(db=db, memory=memory, aliases=FakeAliases({"5": "Лёха"})),
                   args)
        assert memory.calls == [], purpose

    @pytest.mark.asyncio
    async def test_rag_on_for_general(self):
        memory = SpyMemory(rag_facts=[("chat_history", "f", 1, "Лёха")])
        await call(make_router(memory=memory, aliases=FakeAliases({"5": "Лёха"})),
                   {"person": "Лёха", "purpose": "general"})
        assert "get_rag_facts" in memory.calls
        assert "search_long_term" in memory.calls

    @pytest.mark.asyncio
    async def test_rag_on_for_speech_style_when_slice_thin(self):
        memory = SpyMemory(rows=[{"id": 1, "text": "характерное",
                                  "timestamp": 5, "user_id": 5,
                                  "tg_message_id": 1}])
        await call(make_router(db=FakeDb(recent=[]), memory=memory,
                               aliases=FakeAliases({"5": "Лёха"})),
                   {"person": "Лёха", "purpose": "speech_style"})
        assert "search_long_term" in memory.calls


# ── T-3615/T-3618: капы ──────────────────────────────────────────────────


class TestCaps:
    @pytest.mark.asyncio
    async def test_max_items_hard_ceiling_twenty(self):
        db = FakeDb(facts=[fact_row(f"факт {i}", fid=i) for i in range(30)])
        out = payload(await call(
            make_router(db=db, aliases=FakeAliases({"5": "Лёха"})),
            {"person": "Лёха", "purpose": "biography", "max_items": 999}))
        assert len(out["facts"]) <= 20

    @pytest.mark.asyncio
    async def test_message_slice_capped_at_five(self):
        rows = [{"id": i, "text": f"msg {i}", "timestamp": 100 + i,
                 "user_id": 5, "tg_message_id": i} for i in range(10)]
        memory = SpyMemory(rows=rows)
        out = payload(await call(
            make_router(memory=memory, aliases=FakeAliases({"5": "Лёха"})),
            {"person": "Лёха", "purpose": "general", "max_items": 20}))
        messages = [f for f in out["facts"] if f["source_id"].startswith(("tg:", "msg:"))]
        assert len(messages) <= 5

    @pytest.mark.asyncio
    async def test_slice_chars_capped(self):
        rows = [{"id": 1, "text": "я" * 500, "timestamp": 100, "user_id": 5,
                 "tg_message_id": 1}]
        out = payload(await call(
            make_router(memory=SpyMemory(rows=rows),
                        aliases=FakeAliases({"5": "Лёха"})),
            {"person": "Лёха", "purpose": "general"}))
        assert len(out["facts"][0]["text"]) <= 241

    @pytest.mark.asyncio
    async def test_result_budget_4000_with_truncated_flag(self):
        db = FakeDb(facts=[fact_row("я" * 3000, fid=i) for i in range(10)])
        raw = await call(make_router(db=db, aliases=FakeAliases({"5": "Лёха"})),
                         {"person": "Лёха", "purpose": "biography",
                          "max_items": 20})
        assert len(raw) <= 4000
        assert payload(raw)["truncated"] is True


# ── T-3617/T-3618: envelope + честность ──────────────────────────────────


class TestEnvelopeAndHonesty:
    @pytest.mark.asyncio
    async def test_five_fields_always_present(self):
        out = payload(await call(make_router(db=FakeDb(facts=[fact_row("факт")]),
                                             aliases=FakeAliases({"5": "Лёха"})),
                                 {"person": "Лёха", "purpose": "biography"}))
        for key in ("facts", "sources", "confidence", "time_context",
                    "no_data"):
            assert key in out, key
        assert set(out["confidence"]) == {"available", "label", "value"}
        assert set(out["time_context"]) == {"from", "to", "label"}

    @pytest.mark.asyncio
    async def test_unknown_never_confirmed_without_carrier(self):
        memory = SpyMemory(rag_facts=[("chat_history", "слух", 1700000000,
                                       "Лёха")])
        out = payload(await call(make_router(memory=memory,
                                             aliases=FakeAliases({"5": "Лёха"})),
                                 {"person": "Лёха", "purpose": "general"}))
        assert all(f["confidence"] != "confirmed" for f in out["facts"])
        assert out["confidence"]["available"] is False
        assert out["confidence"]["label"] == "unknown"

    @pytest.mark.asyncio
    async def test_low_weight_is_likely_not_confirmed(self):
        db = FakeDb(facts=[fact_row("слабый факт", weight=0.2)])
        out = payload(await call(make_router(db=db, aliases=FakeAliases({"5": "Лёха"})),
                                 {"person": "Лёха", "purpose": "biography"}))
        assert out["facts"][0]["confidence"] == "likely"
        assert out["confidence"]["label"] == "likely"

    @pytest.mark.asyncio
    async def test_unknown_person_honest(self):
        out = payload(await call(make_router(db=FakeDb(facts=[]),
                                             aliases=FakeAliases({})),
                                 {"person": "Никто", "purpose": "biography"}))
        assert out["status"] == "ok"
        assert out["no_data"] is True
        assert out["empty_reason"] == "unknown_person"

    @pytest.mark.asyncio
    async def test_ambiguous_name_no_fact_merge(self):
        aliases = FakeAliases({"5": "Лёха", "6": "Лёха"})
        db = FakeDb(facts=[fact_row("секрет одного из них")])
        out = payload(await call(make_router(db=db, aliases=aliases),
                                 {"person": "Лёха", "purpose": "biography"}))
        assert out["person"]["resolution"] == "ambiguous"
        assert out["person"]["candidates"] == [5, 6]
        assert "name" not in out["person"] or out["person"]["name"] == ""
        assert out["facts"] == []
        assert out["no_data"] is True
        assert out["empty_reason"] == "ambiguous"

    @pytest.mark.asyncio
    async def test_no_universal_dump_only_asked_person(self):
        db = FakeDb(facts=[fact_row("факт Лёхи", target="Лёха")])
        out = payload(await call(make_router(db=db, aliases=FakeAliases({"5": "Лёха"})),
                                 {"person": "Лёха", "purpose": "biography"}))
        # Запрошен только один человек — чтение строго по его canon-имени.
        assert db.fact_calls[0][1] == "Лёха"
        assert len(db.fact_calls) == 1


# ── T-3612: kill-switch OFF (прямой вызов) ───────────────────────────────


class TestKillSwitchDirect:
    @pytest.mark.asyncio
    async def test_disabled_direct_call(self, monkeypatch):
        monkeypatch.setattr(type(settings), "MEMORY_LOOKUP_ENABLED", False)
        out = payload(await call(make_router(), {"person": "Лёха",
                                                 "purpose": "identity"}))
        assert out == {"status": "error", "error": "disabled"}


# ── T-3619: R17-лог ──────────────────────────────────────────────────────


class TestR17Log:
    @pytest.mark.asyncio
    async def test_log_has_only_allowed_fields(self, caplog):
        import logging
        secret = "СЕКРЕТНЫЙ_ФАКТ_xyz"
        db = FakeDb(facts=[fact_row(secret, tg=777, fid=3)])
        with caplog.at_level(logging.INFO, logger="services.tool_router"):
            await call(make_router(db=db, aliases=FakeAliases({"5": "Лёха"})),
                       {"person": "Лёха", "purpose": "biography"})
        lines = [r.getMessage() for r in caplog.records
                 if "[memory] lookup" in r.getMessage()]
        assert lines, "ожидалась строка [memory] lookup"
        line = lines[0]
        for token in ("purpose=biography", "user_id=5", "chat_id=-100",
                      "count=1", "latency_ms=", "empty_reason="):
            assert token in line, token
        assert secret not in caplog.text
        assert "Лёха" not in caplog.text

    @pytest.mark.asyncio
    async def test_general_message_text_not_logged(self, caplog):
        import logging
        secret = "ПРИВАТНОЕ_СООБЩЕНИЕ_секрет"
        rows = [{"id": 1, "text": secret, "timestamp": 5, "user_id": 9,
                 "tg_message_id": 1}]
        with caplog.at_level(logging.INFO, logger="services.tool_router"):
            await call(make_router(memory=SpyMemory(rows=rows),
                                   aliases=FakeAliases({"5": "Лёха"})),
                       {"person": "Лёха", "purpose": "general"})
        assert secret not in caplog.text


# ── T-3619: §35-комбинирование не трогает фактчек ────────────────────────


class TestComposition:
    @pytest.mark.asyncio
    async def test_envelope_reaches_tool_context(self):
        db = FakeDb(facts=[fact_row("факт")])
        router = make_router(db=db, aliases=FakeAliases({"5": "Лёха"}))
        ctx = ToolContext(-100, "q", user_id=5)
        await chat_with_tools(
            _OneCallLLM(), [{"role": "user", "content": "q"}],
            tools=TOOL_CALLING_TOOLS, router=router, ctx=ctx)
        env = ctx.result_for(MEMORY_LOOKUP_TOOL_NAME)
        assert env is not None
        assert env["status"] == "ok"
        assert env["metered"] is False          # free/local (D5)
        assert env["data"]["facts"][0]["text"] == "факт"

    def test_memory_tool_absent_from_factcheck(self):
        names = [t["function"]["name"] for t in factcheck_tools()]
        assert len(names) == 3
        assert MEMORY_LOOKUP_TOOL_NAME not in names


class _OneCallLLM:
    """LLM-заглушка: один tool-call на memory lookup → финальный текст."""

    def __init__(self):
        from services.llm_client import (LLMChatResult, LLMToolCall)
        self._answers = [
            LLMChatResult(
                content=None,
                tool_calls=[LLMToolCall(
                    id="c1", name=MEMORY_LOOKUP_TOOL_NAME,
                    arguments=json.dumps({"person": "Лёха",
                                          "purpose": "biography"}))],
                finish_reason="tool_calls"),
            LLMChatResult(content="финал", tool_calls=None,
                          finish_reason="stop"),
        ]

    async def generate_chat(self, messages, **kwargs):
        return self._answers.pop(0)

    async def generate(self, messages, **kwargs):
        return "plain"
