"""P0 DELTA (26.10.2026) — маршрутизация анализа, периоды, субъект,
provenance памяти, гейт lore-подмены.

Источник: plans/owner_inputs/2026-10-26-p0-delta-analysis.md; дефекты и
минимальные варианты — plans/features/p0-delta-analysis/evidence/audit.md.
Контрактные проверки (CONTRACT/REGRESSION), payload-level, БЕЗ речевого
эталона: никакой «универсальной композиции ответа» не вводится, маршруты
различаются СУЩЕСТВУЮЩИМИ полями плана (response_act/structure/task_kind).
"""
import asyncio
import datetime as _dt
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services import chat_statistics as _cs
from services import mca_gates
from services.database import DatabaseService
from services.direct_chat_service import lore_story_override, \
    lore_verbatim_allowed
from services.direct_l1 import (
    L1Plan,
    lore_story_delivery_allowed,
    normalize_l1_plan,
)
from services.summary_aliases import AliasResolver
from services.tool_router import ToolContext, ToolDeps, ToolRouter

CHAT_ID = -1001234567890


# ── fixtures/helpers ──────────────────────────────────────────────────────


def _deps(memory=None, aliases=None) -> ToolDeps:
    memory = memory or MagicMock()
    return ToolDeps(search=MagicMock(), memory=memory, aliases=aliases)


def _ctx(query="а что было раньше?", user_id=None) -> ToolContext:
    return ToolContext(CHAT_ID, query, user_id=user_id)


def _row(user_id=10, author_name="вася", text="текст", ts=None, row_id=1):
    return {"id": row_id, "user_id": user_id, "author_name": author_name,
            "text": text, "timestamp": ts or int(time.time()),
            "tg_message_id": None, "is_forward": 0, "forward_source": None}


def _dig_payload(out: str) -> dict:
    return json.loads(out)


def _k1(on: bool, monkeypatch):
    monkeypatch.setattr(mca_gates, "chat_statistics_enabled", lambda: on)


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


# ── дефект 1: гейт lore-подмены (bypass только при story-интенции) ────────


class TestLoreBypassIntentGate:
    """Дефект 1 (audit §5): lore_compiled больше не подменяет ответ на
    ЛЮБОМ ходе; только явная story-интенция существующих полей плана.
    Analysis/research → история остаётся материалом (Writer отвечает).
    Fail-open при неопределённости (легаси/fallback без плана)."""

    @staticmethod
    def _plan(act: str, structure: str, extent: str = "auto") -> L1Plan:
        return normalize_l1_plan({
            "action": "reply", "response_act": act, "structure": structure,
            "extent": extent, "tool_policy": "auto",
            "capabilities_needed": ["historical_search"],
        })

    def test_story_acts_allow_override(self):
        assert lore_story_delivery_allowed(self._plan("creative", "story"))
        assert lore_story_delivery_allowed(
            self._plan("historical_recall", "chat"))

    def test_analysis_acts_block_override(self):
        for act in ("research", "explanation", "comparison", "summarization",
                    "clarification"):
            assert not lore_story_delivery_allowed(
                self._plan(act, "chat")), act
        for structure in ("report", "explanation", "comparison", "summary",
                          "steps"):
            assert not lore_story_delivery_allowed(
                self._plan("answer", structure)), structure

    def test_canonicalized_analysis_act_blocks(self):
        # P0C-INT R2: «analysis»/«анализ» канонизируются в research ДО гейта.
        plan = self._plan("analysis", "chat")
        assert plan.response_act == "research"
        assert not lore_story_delivery_allowed(plan)
        plan_ru = self._plan("анализ", "chat")
        assert not lore_story_delivery_allowed(plan_ru)

    def test_undefined_intent_fails_open(self):
        # Не определено полями плана → прежнее поведение (без ложных блоков).
        assert lore_story_delivery_allowed(self._plan("answer", "chat"))
        assert lore_story_delivery_allowed(self._plan("other", "chat"))

    def test_no_plan_fails_open(self):
        assert lore_story_delivery_allowed(None, None)
        assert lore_story_delivery_allowed(None, "не-план-объект") is True

    def test_extent_is_not_a_routing_signal(self):
        # Длина/форма НЕ участвуют в маршрутизации доставки (§11: глубина
        # ≠ длина ответа; никаких универсальных требований к композиции).
        for extent in ("one_word", "compact", "longform", "exhaustive"):
            assert not lore_story_delivery_allowed(
                self._plan("research", "chat", extent=extent))
            assert lore_story_delivery_allowed(
                self._plan("creative", "story", extent=extent))

    def test_legacy_response_plan_kind_gate(self):
        class _RP:
            def __init__(self, kind):
                self.task_kind = kind

        assert not lore_story_delivery_allowed(None, _RP("research"))
        assert not lore_story_delivery_allowed(None, _RP("summarization"))
        assert lore_story_delivery_allowed(None, _RP("creative_writing"))
        assert lore_story_delivery_allowed(None, _RP("historical_recall"))
        assert lore_story_delivery_allowed(None, _RP("social_chat"))

    def test_override_delivers_story_only_for_story_intent(self):
        ctx = _ctx()
        ctx.lore_compiled = True
        ctx.lore_story = "<b>История</b>"
        assert lore_story_override(
            ctx, self._plan("historical_recall", "story")) == "<b>История</b>"
        # Analysis-план: история НЕ подменяет ответ Writer.
        assert lore_story_override(
            ctx, self._plan("research", "explanation")) == ""
        # Без плана (легаси/fallback) — прежнее поведение.
        assert lore_story_override(ctx, None, None) == "<b>История</b>"

    def test_override_requires_compiled_and_nonempty(self):
        ctx = _ctx()
        ctx.lore_compiled = False
        ctx.lore_story = "история"
        assert lore_story_override(ctx, None) == ""
        ctx.lore_compiled = True
        ctx.lore_story = ""
        assert lore_story_override(ctx, None) == ""

    def test_kill_switch_restores_legacy_behavior(self, monkeypatch):
        from config.settings import Settings
        ctx = _ctx()
        ctx.lore_compiled = True
        ctx.lore_story = "история"
        monkeypatch.setattr(Settings, "LORE_STORY_INTENT_GATE_ENABLED",
                            False)
        assert lore_story_override(
            ctx, self._plan("research", "explanation")) == "история"

    def test_call_site_is_gated(self):
        """REGRESSION-пин: условие подмены в direct_chat_service идёт через
        intent-гейт (безвозврат к безусловному override)."""
        import inspect

        from services import direct_chat_service as _dcs
        src = inspect.getsource(_dcs)
        assert "lore_story_override(tool_ctx, l1_plan, response_plan)" in src
        assert "strip_reasoning_tags(lore_story)" in src


# ── LORE-VERBATIM-GATE micro-fix: «верни ДОСЛОВНО» = тот же гейт ──────────


def _l1_plan(act: str, structure: str) -> L1Plan:
    return normalize_l1_plan({
        "action": "reply", "response_act": act, "structure": structure,
        "extent": "auto", "tool_policy": "auto",
        "capabilities_needed": ["historical_search"],
    })


class _RP:
    """Легаси response_plan (существующее поле task_kind)."""

    def __init__(self, kind):
        self.task_kind = kind


class _StoryLLM:
    """LLM-фейк синтеза «Летописца» (канон test_lore_compiler_round1020)."""

    def __init__(self, story="<b>История</b> про Толяна."):
        self.story = story
        self.calls = 0

    async def generate(self, messages, temperature=None, chat_id=None):
        self.calls += 1
        return self.story


async def _dispatch_with_call_site_ctx(plan, rp, query):
    """Конструкция ToolContext РОВНО как в call-site direct_chat_service
    (гейт инструкции) + реальный dispatch compile_lore_story: БД in-memory,
    синтез — фейк-LLM. Возвращает (ctx, tool-output)."""
    from services.database import DatabaseService
    db = DatabaseService(":memory:")
    await db.initialize()
    try:
        await db.save_smart_message(1, CHAT_ID, "мем тут", None,
                                    int(time.time()), "text", "Толян")
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     db=db, llm=_StoryLLM()))
        ctx = ToolContext(
            CHAT_ID, query,
            lore_verbatim_instruction=lore_verbatim_allowed(plan, rp))
        out = await router.dispatch("compile_lore_story", {"topic": "мем"},
                                    ctx)
        return ctx, out
    finally:
        await db.close()


class TestLoreVerbatimInstructionGate:
    """LORE-VERBATIM-GATE (P0-DELTA micro-fix): инструкция «верни story
    ДОСЛОВНО» включается в tool-payload ТОЛЬКО при story-интенции хода —
    тем же гейтом, что и детерминированная подмена (lore_story_override).
    До фикса инструкция летела в payload на ЛЮБОМ интенте: Writer эхом
    возвращал скомпилированную историю на analysis-ходах (S03/S05/S07/S10,
    live-scenarios §Находка) — D1 не выполнялся фактически. CONTRACT."""

    def test_verbatim_iff_delivery_allowed(self):
        for act, structure in (("creative", "story"),
                               ("historical_recall", "chat"),
                               ("answer", "chat")):      # fail-open
            assert lore_verbatim_allowed(_l1_plan(act, structure)), \
                (act, structure)
        for act in ("research", "explanation", "comparison",
                    "summarization", "clarification"):
            assert not lore_verbatim_allowed(_l1_plan(act, "chat")), act
        for structure in ("report", "explanation", "comparison", "summary",
                          "steps"):
            assert not lore_verbatim_allowed(
                _l1_plan("answer", structure)), structure

    def test_legacy_response_plan_kinds(self):
        assert not lore_verbatim_allowed(None, _RP("research"))
        assert not lore_verbatim_allowed(None, _RP("summarization"))
        assert lore_verbatim_allowed(None, _RP("creative_writing"))
        assert lore_verbatim_allowed(None, _RP("historical_recall"))
        assert lore_verbatim_allowed(None, _RP("social_chat"))

    def test_no_plan_fails_open(self):
        assert lore_verbatim_allowed(None, None)

    def test_kill_switch_off_restores_legacy(self, monkeypatch):
        from config.settings import Settings
        monkeypatch.setattr(Settings, "LORE_STORY_INTENT_GATE_ENABLED",
                            False)
        assert lore_verbatim_allowed(_l1_plan("research", "report"))

    def test_call_site_wires_gate_into_tool_context(self):
        """REGRESSION-пин: construction ToolContext в direct_chat_service
        резолвит инструкцию гейтом (безвозврат к дефолту True на любом
        интенте)."""
        import inspect

        from services import direct_chat_service as _dcs
        src = inspect.getsource(_dcs)
        assert "lore_verbatim_instruction=" in src
        assert "lore_verbatim_allowed(" in src

    # ── четыре живых сценария (S03/S05/S07/S10) — Writer-композиция ──

    @pytest.mark.asyncio
    async def test_s03_period_research_no_verbatim(self):
        # S03 «за период …»: research/report → инструкция отсутствует,
        # story остаётся provenance-материалом тул-результата.
        plan = _l1_plan("research", "report")
        ctx, out = await _dispatch_with_call_site_ctx(
            plan, plan.to_response_plan(), "что обсуждали за период 2023-2024")
        assert ctx.lore_compiled is True
        assert ctx.lore_verbatim_instruction is False
        assert "ДОСЛОВНО" not in out
        assert '"story"' in out          # provenance сохранён

    @pytest.mark.asyncio
    async def test_s05_meta_essay_summarization_no_verbatim(self):
        # S05 (мета-эссе о чате): summarization → без инструкции.
        plan = _l1_plan("summarization", "summary")
        ctx, out = await _dispatch_with_call_site_ctx(
            plan, plan.to_response_plan(),
            "напиши эссе о том, как менялся наш чат")
        assert ctx.lore_verbatim_instruction is False
        assert "ДОСЛОВНО" not in out
        assert '"story"' in out

    @pytest.mark.asyncio
    async def test_s05_legacy_response_plan_kind_no_verbatim(self):
        # Легаси-путь (l1-плана нет): task_kind=summarization гейтит.
        ctx, out = await _dispatch_with_call_site_ctx(
            None, _RP("summarization"), "суммируй, как мы общались")
        assert ctx.lore_verbatim_instruction is False
        assert "ДОСЛОВНО" not in out

    @pytest.mark.asyncio
    async def test_s07_two_person_comparison_no_verbatim(self):
        # S07 (отношения двух людей): comparison → без инструкции.
        plan = _l1_plan("comparison", "comparison")
        ctx, out = await _dispatch_with_call_site_ctx(
            plan, plan.to_response_plan(),
            "как общались вася и петя между собой")
        assert ctx.lore_verbatim_instruction is False
        assert "ДОСЛОВНО" not in out
        assert '"story"' in out

    @pytest.mark.asyncio
    async def test_s10_out_of_range_period_no_verbatim(self):
        # S10 (вне-периодный запрос): research/explanation → без инструкции.
        plan = _l1_plan("research", "explanation")
        ctx, out = await _dispatch_with_call_site_ctx(
            plan, plan.to_response_plan(), "что было в 1990-м году")
        assert ctx.lore_verbatim_instruction is False
        assert "ДОСЛОВНО" not in out
        assert '"story"' in out

    # ── story-интенции не сужаются (S04/S09) ──────────────────────────

    @pytest.mark.asyncio
    async def test_s04_creative_story_keeps_verbatim(self):
        # S04 (просьба рассказать историю): creative/story → инструкция на
        # месте (мягкая страховка доставки детерминированного HTML).
        plan = _l1_plan("creative", "story")
        ctx, out = await _dispatch_with_call_site_ctx(
            plan, plan.to_response_plan(), "расскажи историю про мем")
        assert ctx.lore_compiled is True
        assert ctx.lore_verbatim_instruction is True
        assert "ДОСЛОВНО" in out

    @pytest.mark.asyncio
    async def test_s09_historical_recall_keeps_verbatim(self):
        # S09: historical_recall → инструкция на месте.
        plan = _l1_plan("historical_recall", "chat")
        ctx, out = await _dispatch_with_call_site_ctx(
            plan, plan.to_response_plan(), "а вспомни, как мы шут про Толяна")
        assert ctx.lore_verbatim_instruction is True
        assert "ДОСЛОВНО" in out


# ── дефект 2: период выразим без второго роутера ──────────────────────────


class TestPeriodExpressible:
    """Дефект 2 (audit §9.2): «за период» выразим существующими тулами —
    аддитивные year_from/year_to в схемах, SQL-фильтры до LIMIT."""

    def test_query_chat_memory_schema_has_period_and_author(self):
        from services.tool_schemas import TOOL_QUERY_CHAT_MEMORY
        props = TOOL_QUERY_CHAT_MEMORY["function"]["parameters"]["properties"]
        assert props["year_from"]["type"] == "integer"
        assert props["year_to"]["type"] == "integer"
        assert props["author"]["type"] == "string"
        # Аддитивность: required/additionalProperties не изменились.
        assert TOOL_QUERY_CHAT_MEMORY["function"]["parameters"][
            "required"] == ["query"]
        assert TOOL_QUERY_CHAT_MEMORY["function"]["parameters"][
            "additionalProperties"] is False
        desc = props["author"]["description"].lower()
        assert "telegram user id" in desc
        assert '"me"' in desc

    def test_dig_schema_has_year_to_and_uid_person(self):
        from services.tool_schemas import TOOL_DIG_INTO_LORE
        props = TOOL_DIG_INTO_LORE["function"]["parameters"]["properties"]
        assert props["year_to"]["type"] == "integer"
        assert TOOL_DIG_INTO_LORE["function"]["parameters"][
            "required"] == ["query"]
        person_desc = props["person"]["description"].lower()
        assert "telegram user id" in person_desc
        assert '"me"' in person_desc

    @pytest.mark.asyncio
    async def test_year_range_passthrough_to_sql(self, monkeypatch):
        _k1(True, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            _row(text="в 2023 писали", ts=int(_dt.datetime(2023, 6, 1)
                                            .timestamp()))])
        memory.count_mentions = AsyncMock(
            return_value={"count": 1, "first_seen": 1, "last_seen": 2})
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory",
            {"query": "писали", "year_from": 2022, "year_to": 2024}, _ctx())
        args, kwargs = memory.search_long_term.await_args
        assert kwargs["since_ts"] == int(_dt.datetime(2022, 1, 1).timestamp())
        assert kwargs["until_ts"] == int(_dt.datetime(2024, 12, 31, 23, 59,
                                                      59).timestamp())
        assert "author_ids" not in kwargs
        cargs, ckwargs = memory.count_mentions.await_args
        assert ckwargs["since_ts"] == kwargs["since_ts"]
        assert ckwargs["until_ts"] == kwargs["until_ts"]
        assert "писали" in out

    @pytest.mark.asyncio
    async def test_year_from_only_opens_window(self, monkeypatch):
        _k1(True, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.count_mentions = AsyncMock(
            return_value={"count": 0, "first_seen": None, "last_seen": None})
        router = ToolRouter(_deps(memory=memory))
        await router.dispatch(
            "query_chat_memory", {"query": "x", "year_from": 2022}, _ctx())
        _, kwargs = memory.search_long_term.await_args
        assert kwargs["since_ts"] == int(_dt.datetime(2022, 1, 1).timestamp())
        # year_to не задан → открытый конец (легаси until=0, kwarg не ставится)
        assert "until_ts" not in kwargs

    @pytest.mark.asyncio
    async def test_invalid_period_honest_unsupported(self, monkeypatch):
        _k1(True, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory",
            {"query": "x", "year_from": 2024, "year_to": 2022}, _ctx())
        payload = json.loads(out)
        assert payload["status"] == "unsupported"
        assert payload["reason"] == "invalid_period"
        memory.search_long_term.assert_not_called()

    @pytest.mark.asyncio
    async def test_out_of_range_year_honest_unsupported(self, monkeypatch):
        _k1(True, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "x", "year_from": 1800}, _ctx())
        payload = json.loads(out)
        assert payload["reason"] == "invalid_period"
        memory.search_long_term.assert_not_called()

    @pytest.mark.asyncio
    async def test_dig_year_range_bounds(self, monkeypatch):
        _k1(False, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            _row(text="старое сообщение", ts=int(_dt.datetime(2023, 3, 1)
                                            .timestamp()))])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore",
            {"query": "сообщение", "year": 2022, "year_to": 2024,
             "mode": "messages"}, _ctx())
        args, kwargs = memory.search_long_term.await_args
        assert kwargs["since_ts"] == int(_dt.datetime(2022, 1, 1).timestamp())
        assert kwargs["until_ts"] == int(_dt.datetime(2024, 12, 31, 23, 59,
                                                      59).timestamp())
        assert "старое сообщение" in out

    @pytest.mark.asyncio
    async def test_dig_invalid_range_honest_unsupported(self, monkeypatch):
        _k1(False, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore",
            {"query": "x", "year": 2024, "year_to": 2022, "mode": "messages"},
            _ctx())
        payload = json.loads(out)
        assert payload["status"] == "unsupported"
        assert payload["reason"] == "invalid_period"
        memory.search_long_term.assert_not_called()

    @pytest.mark.asyncio
    async def test_stats_period_and_uid_author(self, monkeypatch):
        """Точная статистика: годовой диапазон и author=uid/me доходят до
        StatsQuery (interval_to + author_ids) без второго роутера."""
        _k1(True, monkeypatch)
        captured: dict = {}

        async def fake_measure(db, query):
            captured["query"] = query
            raise RuntimeError("short-circuit")

        monkeypatch.setattr(_cs, "measure", fake_measure)
        memory = MagicMock()
        memory.db = object()          # db доступен (проверка пройдена)
        router = ToolRouter(_deps(memory=memory))
        year_from = int(_dt.datetime(2022, 1, 1).timestamp())
        year_to = int(_dt.datetime(2024, 12, 31, 23, 59, 59).timestamp())
        out = await router.dispatch(
            "query_chat_memory",
            {"query": "тема", "year_from": 2022, "year_to": 2024,
             "stats": {"metric": "messages", "author": "me"}},
            _ctx(user_id=777))
        assert "unsupported" in out      # short-circuit measure
        query = captured["query"]
        assert query.interval_from == year_from
        assert query.interval_to == year_to
        assert query.author_ids == (777,)

    @pytest.mark.asyncio
    async def test_stats_uid_string_author(self, monkeypatch):
        _k1(True, monkeypatch)
        captured: dict = {}

        async def fake_measure(db, query):
            captured["query"] = query
            raise RuntimeError("short-circuit")

        monkeypatch.setattr(_cs, "measure", fake_measure)
        memory = MagicMock()
        memory.db = object()
        router = ToolRouter(_deps(memory=memory))
        await router.dispatch(
            "query_chat_memory",
            {"query": "тема", "stats": {"metric": "messages",
                                        "author": "123456789"}},
            _ctx(user_id=1))
        assert captured["query"].author_ids == (123456789,)


# ── дефект 3: покрытие и свежесть выборки ─────────────────────────────────


class TestCoverageHonesty:
    """Дефект 3 (audit §9.3): фильтры до LIMIT; честное покрытие показа;
    «Летописец» сэмплирует окна по всему периоду."""

    @pytest.mark.asyncio
    async def test_shown_vs_total_reported(self, monkeypatch):
        _k1(True, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(
            return_value=[_row(text="совпадение", ts=int(time.time()))])
        memory.count_mentions = AsyncMock(
            return_value={"count": 312, "first_seen": 1, "last_seen": 2})
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "тема", "time_range": "all"},
            _ctx())
        assert "Показано 1 из 312 сообщений" in out

    @pytest.mark.asyncio
    async def test_no_coverage_noise_when_all_shown(self, monkeypatch):
        _k1(True, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(
            return_value=[_row(text="раз"), _row(text="два", row_id=2)])
        memory.count_mentions = AsyncMock(
            return_value={"count": 2, "first_seen": 1, "last_seen": 2})
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "тема"}, _ctx())
        assert "Показано" not in out

    @pytest.mark.asyncio
    async def test_indirect_memory_block_labeled(self, monkeypatch):
        """Дефект 5/provenance: производные факты (vector) не смешиваются
        с дословными сообщениями — отдельный маркированный блок."""
        _k1(True, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.count_mentions = AsyncMock(
            return_value={"count": 0, "first_seen": None, "last_seen": None})
        memory.vector_search = AsyncMock(return_value=["Обобщённый факт"])
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "тема", "time_range": "all"},
            _ctx())
        assert ("Контекст из памяти (обобщённые факты и пересказ, "
                "не дословные сообщения):") in out
        assert "Обобщённый факт" in out

    @pytest.mark.asyncio
    async def test_rag_fallback_labeled_when_still_empty(self, monkeypatch):
        _k1(True, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.count_mentions = AsyncMock(
            return_value={"count": 0, "first_seen": None, "last_seen": None})
        memory.vector_search = AsyncMock(return_value=[])
        memory.get_rag_context = AsyncMock(return_value="Сводка RAG")
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "тема", "time_range": "all"},
            _ctx())
        assert ("Контекст из памяти (обобщённые факты и пересказ, "
                "не дословные сообщения):") in out
        assert "Сводка RAG" in out

    @pytest.mark.asyncio
    async def test_author_filter_skips_indirect_channels(self, monkeypatch):
        """Фильтр автора не «протекает» в каналы, которые не умеют его
        фильтровать: vector/RAG при author не вызываются."""
        _k1(True, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.count_mentions = AsyncMock(
            return_value={"count": 0, "first_seen": None, "last_seen": None})
        memory.vector_search = AsyncMock(return_value=[])
        memory.get_rag_context = AsyncMock(return_value="")
        aliases = AliasResolver('{"77": "Вася"}')
        router = ToolRouter(_deps(memory=memory, aliases=aliases))
        out = await router.dispatch(
            "query_chat_memory",
            {"query": "тема", "author": "Вася", "time_range": "all"}, _ctx())
        assert "ничего не найдено" in out
        memory.vector_search.assert_not_called()
        memory.get_rag_context.assert_not_called()
        _, kwargs = memory.search_long_term.await_args
        assert kwargs["author_ids"] == (77,)

    @pytest.mark.asyncio
    async def test_dig_payload_reports_coverage(self, monkeypatch):
        _k1(True, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            _row(text="сниппет один"),
            _row(text="сниппет два", row_id=2)])
        db = MagicMock()
        db.search_messages_fts_count_by_author = AsyncMock(
            return_value={"count": 5, "by_author": [], "first_seen": 1,
                          "last_seen": 2})
        memory.db = db
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "тема", "mode": "messages"}, _ctx())
        payload = _dig_payload(out)
        coverage = payload["coverage"]
        assert coverage["messages_shown"] == 2
        assert coverage["messages_total"] == 5
        assert coverage["facts_shown"] == 0

    @pytest.mark.asyncio
    async def test_dig_snippets_window_filter_in_sql(self, monkeypatch):
        """Узкое окно: top-40 по rank больше не теряет совпадения периода —
        фильтр окна в SQL ДО LIMIT (kwargs), пост-фильтр сохранён."""
        _k1(False, monkeypatch)
        memory = MagicMock()
        old_ts = int(_dt.datetime(2022, 5, 1).timestamp())
        memory.search_long_term = AsyncMock(return_value=[
            _row(text="старое совпадение", ts=old_ts)])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore",
            {"query": "совпадение", "year": 2022, "mode": "messages"}, _ctx())
        payload = _dig_payload(out)
        assert any("старое совпадение" in s for s in payload["snippets"])
        _, kwargs = memory.search_long_term.await_args
        assert kwargs["since_ts"] == int(_dt.datetime(2022, 1, 1).timestamp())
        assert kwargs["until_ts"] == int(_dt.datetime(2022, 12, 31, 23, 59,
                                                      59).timestamp())

    @pytest.mark.asyncio
    async def test_lore_dense_dialogs_sample_across_period(self, db):
        """«Летописец»: окна строятся по стрйд-сэмплу ВСЕГО периода, а не
        по первым max_scan ASC — поздние плотные всплески достижимы."""
        chat = -100999
        # 40 разрежённых упоминений с 2022 (одно в ~45 дней) + плотный
        # всплеск (10 сообщений за час) в 2025.
        base = _dt.datetime(2022, 1, 1)
        for i in range(40):
            ts = int((base + _dt.timedelta(days=45 * i)).timestamp())
            await db.save_smart_message(1, chat, f"тема раз{i}", None, ts,
                                        "text", "кто-то")
        burst_start = _dt.datetime(2025, 6, 1, 12, 0)
        for i in range(10):
            ts = int((burst_start + _dt.timedelta(minutes=i)).timestamp())
            await db.save_smart_message(2, chat, f"тема всплеск{i}", None, ts,
                                        "text", "кто-то")
        result = await db.lore_dense_dialogs(chat, "тема", max_scan=20)
        assert result["total"] == 50
        assert result["dialogs"], "окна непусты"
        year_of = lambda ts: _dt.datetime.fromtimestamp(ts).year  # noqa: E731
        window_years = [year_of(win[0]["timestamp"])
                        for win in result["dialogs"] if win]
        assert 2025 in window_years, (
            "плотный всплеск 2025 должен попасть в окна (сэмпл по всему "
            f"периоду); окна: {window_years}")

    @pytest.mark.asyncio
    async def test_lore_dense_dialogs_small_corpus_parity(self, db):
        """total <= max_scan → прежний полный ASC-скан (путь не сломан)."""
        chat = -100998
        start = _dt.datetime(2024, 3, 1, 10, 0)
        for i in range(5):
            ts = int((start + _dt.timedelta(minutes=7 * i)).timestamp())
            await db.save_smart_message(1, chat, f"тема шаг {i}", None, ts,
                                        "text", "кто-то")
        result = await db.lore_dense_dialogs(chat, "тема", max_scan=300)
        assert result["total"] == 5
        assert len(result["dialogs"]) == 1
        texts = [r["text"] for r in result["dialogs"][0]]
        assert texts == [f"тема шаг {i}" for i in range(5)]


# ── дефект 4: субъект анализа по Telegram uid ─────────────────────────────


class TestPersonIdentity:
    """Дефект 4 (audit §9.4): резолв по Telegram uid первым, «me» = uid
    говорящего; ненайденный субъект — честный unsupported, фильтр автора
    не исчезает молча; похожие имена не сливаются."""

    def test_uid_forms_resolve_directly(self):
        router = ToolRouter(_deps())
        uid, detail, terms = router._resolve_person_identity(
            "138811255", _ctx())
        assert (uid, detail, terms) == (138811255, "", [])
        uid, detail, terms = router._resolve_person_identity(
            "id:138811255", _ctx())
        assert uid == 138811255 and terms == []
        uid, detail, terms = router._resolve_person_identity(
            "user:138811255", _ctx())
        assert uid == 138811255

    def test_me_resolves_caller_uid(self):
        router = ToolRouter(_deps())
        for value in ("me", "self", "я"):
            uid, detail, _ = router._resolve_person_identity(
                value, _ctx(user_id=777))
            assert uid == 777, value

    def test_me_without_caller_is_honest(self):
        router = ToolRouter(_deps())
        uid, detail, _ = router._resolve_person_identity("me", _ctx())
        assert uid is None and detail == "caller_unknown"

    def test_alias_single_match_resolves(self):
        aliases = AliasResolver('{"138811255": "Леха"}')
        router = ToolRouter(_deps(aliases=aliases))
        uid, detail, terms = router._resolve_person_identity("Леха", _ctx())
        assert uid == 138811255 and detail == ""
        assert "леха" in terms

    def test_duplicate_alias_names_not_merged(self):
        aliases = AliasResolver('{"1": "вася", "2": "вася"}')
        router = ToolRouter(_deps(aliases=aliases))
        uid, detail, _ = router._resolve_person_identity("вася", _ctx())
        assert uid is None and detail == "author_ambiguous"

    def test_unknown_name_unresolved(self):
        router = ToolRouter(_deps(aliases=AliasResolver('{"1": "вася"}')))
        uid, detail, terms = router._resolve_person_identity("Сеня", _ctx())
        assert uid is None and detail == "author_unresolved"
        assert "сеня" in terms

    @pytest.mark.asyncio
    async def test_dig_person_by_uid_filters_in_sql(self, monkeypatch):
        _k1(False, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            _row(user_id=138811255, author_name="Леха",
                 text="леха писал про лето")])
        memory.db = None
        aliases = AliasResolver('{"138811255": "Леха"}')
        router = ToolRouter(_deps(memory=memory, aliases=aliases))
        out = await router.dispatch(
            "dig_into_lore",
            {"query": "лето", "person": "138811255", "mode": "messages"},
            _ctx())
        _, kwargs = memory.search_long_term.await_args
        assert kwargs["author_ids"] == (138811255,)
        assert "леха писал про лето" in out

    @pytest.mark.asyncio
    async def test_dig_person_me_uses_caller_uid(self, monkeypatch):
        _k1(False, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            _row(user_id=777, author_name="я сам",
                 text="моё сообщение про лето")])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore",
            {"query": "лето", "person": "me", "mode": "messages"},
            _ctx(user_id=777))
        _, kwargs = memory.search_long_term.await_args
        assert kwargs["author_ids"] == (777,)
        assert "моё сообщение про лето" in out

    @pytest.mark.asyncio
    async def test_dig_person_unresolved_honest_refusal(self, monkeypatch):
        """Ядро дефекта 4: имя без алиаса больше НЕ превращается в
        OR-токены упоминаний — честный отказ без поиска."""
        _k1(False, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[_row()])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore",
            {"query": "лето", "person": "Незнакомец", "mode": "messages"},
            _ctx())
        payload = _dig_payload(out)
        assert payload["status"] == "unsupported"
        assert payload["reason"] == "author_unresolved"
        assert "Незнакомец" in payload["message"]
        memory.search_long_term.assert_not_called()

    @pytest.mark.asyncio
    async def test_dig_person_ambiguous_honest_refusal(self, monkeypatch):
        _k1(False, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[_row()])
        memory.db = None
        aliases = AliasResolver('{"1": "вася", "2": "вася"}')
        router = ToolRouter(_deps(memory=memory, aliases=aliases))
        out = await router.dispatch(
            "dig_into_lore",
            {"query": "лето", "person": "вася", "mode": "messages"}, _ctx())
        payload = _dig_payload(out)
        assert payload["status"] == "unsupported"
        assert payload["reason"] == "author_ambiguous"
        memory.search_long_term.assert_not_called()

    @pytest.mark.asyncio
    async def test_dig_person_me_without_caller_refusal(self, monkeypatch):
        _k1(False, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[_row()])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore",
            {"query": "лето", "person": "me", "mode": "messages"}, _ctx())
        payload = _dig_payload(out)
        assert payload["status"] == "unsupported"
        assert payload["reason"] == "caller_unknown"
        memory.search_long_term.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_memory_author_unresolved_refusal(self, monkeypatch):
        _k1(True, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[_row()])
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory",
            {"query": "тема", "author": "Незнакомец"}, _ctx())
        payload = json.loads(out)
        assert payload["status"] == "unsupported"
        assert payload["reason"] == "author_unresolved"
        memory.search_long_term.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_memory_author_uid_passthrough(self, monkeypatch):
        _k1(True, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[_row(text="нашлось")])
        memory.count_mentions = AsyncMock(
            return_value={"count": 1, "first_seen": 1, "last_seen": 1})
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "тема", "author": "123456789"},
            _ctx())
        _, kwargs = memory.search_long_term.await_args
        assert kwargs["author_ids"] == (123456789,)
        assert "нашлось" in out

    @pytest.mark.asyncio
    async def test_query_memory_no_person_keeps_mentions_semantics(
            self, monkeypatch):
        """person/author НЕ задан → прежний поиск по упоминаниям (без
        фильтра) не ломается."""
        _k1(False, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            _row(text="упоминание")])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "лето", "mode": "messages"}, _ctx())
        _, kwargs = memory.search_long_term.await_args
        assert "author_ids" not in kwargs
        assert "упоминание" in out


# ── дефект 5: provenance в фактическом пути памяти ────────────────────────


class TestFactProvenanceLabels:
    """Дефект 5 (audit §9.5): происхождение фактов доезжает до модели —
    пересказы/выводы L2 не выдаются за независимые свидетельства."""

    @staticmethod
    def _fact_row(origin="chat_history", fact="факт текст", status="confirmed",
                  rag_ts=0):
        return {"id": 1, "fact": fact, "origin": origin, "created_at": 1,
                "target_user": None, "weight": 0.5, "last_confirmed_at": 1,
                "message_timestamp": rag_ts, "status": status, "rag_ts": rag_ts}

    @pytest.mark.asyncio
    async def _facts(self, monkeypatch, rows):
        _k1(False, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        db = MagicMock()
        db.search_graph_facts_fts = AsyncMock(return_value=rows)
        memory.db = db
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "факт", "mode": "facts"}, _ctx())
        return _dig_payload(out)

    @pytest.mark.asyncio
    async def test_chat_history_fact_labeled_as_retell(self, monkeypatch):
        payload = await self._facts(
            monkeypatch, [self._fact_row(origin="chat_history")])
        assert payload["facts"][0].startswith("[пересказ из чата] ")

    @pytest.mark.asyncio
    async def test_derived_belief_labeled_as_bot_inference(self, monkeypatch):
        payload = await self._facts(
            monkeypatch, [self._fact_row(origin="derived_belief")])
        assert payload["facts"][0].startswith("[вывод бота] ")

    @pytest.mark.asyncio
    async def test_unknown_origin_labeled_honestly(self, monkeypatch):
        payload = await self._facts(
            monkeypatch, [self._fact_row(origin="weird_source")])
        assert payload["facts"][0].startswith("[weird_source] ")

    @pytest.mark.asyncio
    async def test_archived_belief_marked(self, monkeypatch):
        payload = await self._facts(
            monkeypatch, [self._fact_row(status="archived_belief")])
        assert "(архивное убеждение)" in payload["facts"][0]

    @pytest.mark.asyncio
    async def test_message_snippets_stay_direct_quotes(self, monkeypatch):
        """Сниппеты kind="msg" — прямые цитаты корпуса, меток пересказа
        на них нет (различение прямое/производное в payload)."""
        _k1(False, monkeypatch)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            _row(text="дословное сообщение")])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "дословное", "mode": "messages"},
            _ctx())
        payload = _dig_payload(out)
        assert payload["snippets"] == [s for s in payload["snippets"]]
        assert not any(s.startswith("[пересказ") for s in payload["snippets"])


# ── §1/§13: анти-шаблон и различение маршрутов по существующим полям ──────


class TestScenarioMatrixNoTemplate:
    """Сценарная матрица владельца (§12, 8 интентов) на payload-уровне:
    L1-план + task_kind + response_mode + lore-гейт. БЕЗ golden text;
    различия композиции/длины/юмора у корректных ответов — не дефект."""

    @staticmethod
    def _route(plan_json: dict) -> tuple:
        plan = normalize_l1_plan(plan_json)
        rp = plan.to_response_plan()
        mode = __import__("services.direct_l1",
                          fromlist=["plan_response_mode"]
                          ).plan_response_mode(plan)
        gate = lore_story_delivery_allowed(plan, rp)
        return plan, rp.task_kind, mode, gate

    def test_matrix_routes_differ_by_intent(self):
        cases = [
            # (имя, L1 JSON, task_kind, lore-gate)
            ("free_reasoning",
             {"action": "reply", "response_act": "answer",
              "structure": "chat", "tool_policy": "none"},
             "social_chat", True),
            ("fact_lookup",
             {"action": "reply", "response_act": "answer",
              "structure": "answer", "tool_policy": "auto",
              "capabilities_needed": ["chat_memory"]},
             "social_chat", True),
            ("person_analysis",
             {"action": "reply", "response_act": "analysis",
              "structure": "explanation", "tool_policy": "auto",
              "capabilities_needed": ["chat_memory", "historical_search"]},
             "research", False),
            ("period_change",
             {"action": "reply", "response_act": "research",
              "structure": "report", "tool_policy": "auto",
              "capabilities_needed": ["historical_search"]},
             "research", False),
            ("meme_story",
             {"action": "reply", "response_act": "historical_recall",
              "structure": "story", "tool_policy": "auto",
              "capabilities_needed": ["historical_search"]},
             "historical_recall", True),
            ("relations",
             {"action": "reply", "response_act": "comparison",
              "structure": "comparison", "tool_policy": "auto",
              "capabilities_needed": ["user_memory"]},
             "comparison", False),
            ("exact_stats",
             {"action": "reply", "response_act": "answer",
              "structure": "answer", "tool_policy": "auto",
              "capabilities_needed": ["statistics"]},
             "social_chat", True),
            ("creative",
             {"action": "reply", "response_act": "creative",
              "structure": "story", "tool_policy": "auto"},
             "creative_writing", True),
        ]
        seen_kinds: set = set()
        for name, plan_json, kind, gate in cases:
            plan, task_kind, mode, lore_gate = self._route(plan_json)
            assert task_kind == kind, (name, task_kind)
            assert lore_gate is gate, (name, lore_gate)
            assert isinstance(mode, str) and mode
            seen_kinds.add(task_kind)
        # Различение реальное, а не «всё в один режим» (§13).
        assert len(seen_kinds) >= 4

    def test_conversational_interpretation_not_forced_to_archive(self):
        """§2.1: разговорно-интерпретационный анализ не обязан быть
        архивным расследованием — tool_policy=none проходит как есть."""
        plan = normalize_l1_plan({
            "action": "reply", "response_act": "answer",
            "structure": "chat", "tool_policy": "none",
            "extent": "compact"})
        rp = plan.to_response_plan()
        assert rp.task_kind == "social_chat"
        assert plan.tool_policy == "none"
        assert plan.capabilities_needed == ()

    def test_deep_analysis_word_canonizes_to_research(self):
        """§2.2/§3: анализ конкретного человека попадает в research-контур
        БЕЗ второго роутера (канонизация известной формы)."""
        for word in ("analysis", "analyze", "разбор", "проанализировать"):
            plan = normalize_l1_plan({
                "action": "reply", "response_act": word,
                "structure": "chat", "tool_policy": "auto"})
            assert plan.response_act == "research", word
            assert not lore_story_delivery_allowed(plan, plan.to_response_plan())

    def test_no_universal_composition_added(self):
        """Гейт доставки — единственная новая точка; он НЕ добавляет
        обязательной композиции (проверка по публичной поверхности модуля:
        никаких новых «всегда-» требований, списков структуры ответа)."""
        import inspect

        from services import direct_l1
        src = inspect.getsource(direct_l1)
        assert "LORE_STORY_ACTS" in src          # гейт — фильтр доставки
        # Новых обязательных композиционных констант не появилось:
        for forbidden in ("ALWAYS_", "MUST_START_WITH", "REQUIRED_STRUCTURE"):
            assert forbidden not in src, forbidden

    def test_lore_prompt_not_wired_into_analysis_paths(self):
        """§8: LORE_STORY_SYSTEM_PROMPT применяется только в синтезе
        истории «Летописца» (lore_compiler_service); в анализ/Writer/роутер
        он не попадает. Проверка по AST — реальное использование в коде,
        а не упоминания в комментариях."""
        import ast

        def _canon_usages(path):
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            used = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if "LORE_STORY" in alias.name:
                            used.append(f"{node.module}.{alias.name}")
                elif isinstance(node, ast.Attribute) and \
                        "LORE_STORY" in (node.attr or ""):
                    used.append(node.attr)
            return used

        for mod, path in (
                ("direct_chat_service", "services/direct_chat_service.py"),
                ("direct_l1", "services/direct_l1.py"),
                ("tool_router", "services/tool_router.py"),
                ("lore_prompts_owner", "services/lore_prompts.py")):
            assert not _canon_usages(path), (mod, _canon_usages(path))
        used = _canon_usages("services/lore_compiler_service.py")
        assert used == ["services.lore_prompts.LORE_STORY_SYSTEM_PROMPT"]
