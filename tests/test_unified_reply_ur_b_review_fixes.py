"""UNIFIED-REPLY UR-B — review-fix: приватность, публичный якорь, явная просьба, ref.

Воспроизводит ЧЕТЫРЕ находки ревью UR-B (до правки каждый тест падал):

  1. `privacy_blocked` — сеть не трогается ВООБЩЕ: пустая безопасная
     формулировка не подменяется сырым текстом в fallback-ветке, а если вызов
     всё же случился, `search_called` не может остаться False;
  2. приватный пересказ после вычистки алиаса («Маша») не уходит провайдеру:
     нет публичного якоря → `privacy_blocked`, 0 вызовов; публичное имя
     (`Tesla`) по-прежнему ищется;
  3. явная просьба человека (`explicit_request=True`) делает поиск
     `required`/`user_forced` даже без `required_caps` и без ключевого слова;
     нет инструмента → честный `unavailable`, а не тихий пропуск;
  4. ref, напечатанный в маркере обрезки evidence-пакета, открывается через
     `ToolEvidence.full_text` (нет «висячих» ev-ссылок).

Тесты идут через настоящий ToolRouter с подменным провайдером, без сети.

TEST-LIFECYCLE: REGRESSION owner=UNIFIED-REPLY/UR-B
"""
import re

import pytest

from services import direct_execution as _dx
from services.tool_router import ToolContext, ToolRouter
from tests.test_unified_reply_ur_b_search_first import (
    CHAT_ID, _plan, _router, _schemas, _SearchProvider)

pytestmark = [pytest.mark.system2]

RAW_QUERY = "найди в интернете @vasya 79991234567 t.me/c/123"


async def _run(plan, query, search, *, tool_schemas=None, private_terms=(),
               required_caps=(), explicit_request=False, capacity_chars=None,
               prepend_sources=()):
    router = search if isinstance(search, ToolRouter) else _router(search)
    return await _dx.run_tool_phase(
        plan=plan, router=router, ctx=ToolContext(CHAT_ID, query),
        query=query,
        chat_id=CHAT_ID, correlation_id="corr-ur-b-fix",
        tool_schemas=(_schemas("execute_web_search")
                      if tool_schemas is None else tool_schemas),
        required_caps=required_caps, explicit_request=explicit_request,
        private_terms=private_terms, capacity_chars=capacity_chars,
        prepend_sources=prepend_sources, emit_trace=False)


def _search_calls(result):
    return [dict(item) for item in (result.evidence.tool_trace or ())
            if str(item.get("tool") or "") == "execute_web_search"]


# ── находка 1: приватный запрос — ни одного сетевого вызова ──────────────────


class TestPrivacyBlockedTouchesNoNetwork:
    @pytest.mark.asyncio
    async def test_raw_text_never_reaches_provider(self):
        """Fallback-ветка `_SEARCH_RE` не возвращает сырой текст в поиск."""
        search = _SearchProvider("Ответ\nтекст\nhttps://example.com/x")
        plan = _plan(knowledge_origin="open_world",
                     capabilities_needed=["web_search"])
        result = await _run(plan, RAW_QUERY, search,
                            private_terms=("vasya",), required_caps=(
                                "web_search",))
        assert search.queries == [], "приватный текст ушёл в поисковик"
        for leaked in ("vasya", "79991234567", "t.me", "@"):
            assert all(leaked not in q for q in search.queries)
        assert result.evidence.search_status == (
            _dx.SEARCH_STATUS_PRIVACY_BLOCKED)
        assert result.evidence.search_called is False
        assert result.evidence.search_query == ""
        assert _search_calls(result) == []
        assert "79991234567" not in (getattr(result.pack, "text", "") or "")

    @pytest.mark.asyncio
    async def test_internal_tools_still_run_but_search_is_structurally_off(self):
        """Запрет точечный: локальные инструменты работают, сеть — нет."""
        search = _SearchProvider("Ответ\nтекст\nhttps://example.com/x")
        plan = _plan(knowledge_origin="open_world",
                     capabilities_needed=["web_search", "chat_history"])
        result = await _run(plan, RAW_QUERY, search, private_terms=("vasya",),
                            tool_schemas=_schemas("execute_web_search",
                                                  "get_recent_history"))
        assert search.queries == []
        assert result.evidence.search_called is False
        assert result.evidence.search_status == (
            _dx.SEARCH_STATUS_PRIVACY_BLOCKED)

    def test_search_called_cannot_be_false_for_a_real_call(self):
        """Если вызов всё-таки состоялся — трасса обязана это сказать."""
        raw = _dx.ChainResult(
            "", evidence_sources=[_dx.EvidenceSource(
                tool="execute_web_search", status="ok",
                content="Заголовок\nфакт\nhttps://example.com/f")],
            chain_meta={"mode": "simple_tools"})
        task = _dx.SearchTask(blocked_reason="privacy_blocked",
                              source_request=RAW_QUERY)
        evidence = _dx._tool_evidence_from(
            raw, axis=_l1_axis(), search_task=task)
        assert evidence.search_called is True
        assert evidence.search_status == _dx.SEARCH_STATUS_PRIVACY_BLOCKED
        assert evidence.can_claim_verified is False


def _l1_axis():
    from services import direct_l1 as _l1
    return _l1.SearchAxis("open_world", _l1.SEARCH_REQUIRED,
                          "normalized_open_world", False)


# ── находка 2: приватный пересказ не становится запросом ─────────────────────


class TestPrivateRetellingNeedsPublicAnchor:
    @pytest.mark.asyncio
    async def test_alias_stripped_private_retelling_is_blocked(self):
        query = "Маша беременна третьем месяце говори никому"
        search = _SearchProvider("Ответ\nтекст\nhttps://example.com/x")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, query, search, private_terms=("Маша",))
        assert search.queries == [], "личный рассказ ушёл в поисковик"
        assert result.evidence.search_status == (
            _dx.SEARCH_STATUS_PRIVACY_BLOCKED)
        assert result.evidence.search_called is False
        assert result.evidence.search_query == ""

    def test_retelling_without_alias_is_blocked_too(self):
        task = _dx.build_search_query(
            _plan(knowledge_origin="open_world"),
            query="она мне писала что беременна третьем месяце говори никому")
        assert task.blocked is True
        assert task.query == ""

    @pytest.mark.asyncio
    async def test_public_name_in_retelling_still_searchable(self):
        query = "Маша сказала что Tesla выпустила новую модель"
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/t")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, query, search, private_terms=("Маша",))
        assert len(search.queries) == 1, "публичное имя обязано искаться"
        sent = search.queries[0].lower()
        assert "tesla" in sent
        for forbidden in ("маша", "беременна", "говори"):
            assert forbidden not in sent
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK


# ── находка 3: явная просьба не демотируется ────────────────────────────────


class TestExplicitRequestForcesRequired:
    @pytest.mark.asyncio
    async def test_explicit_request_without_caps_and_keywords(self):
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/b")
        plan = _plan()      # нет knowledge_origin/search_intent/capabilities
        assert plan.search_intent == ""
        result = await _run(plan, "биткоин сейчас", search,
                            explicit_request=True, required_caps=())
        assert result.evidence.search_intent == "required"
        assert result.evidence.search_axis_source == "user_forced"
        assert len(search.queries) == 1, "явная просьба обязана дать вызов"
        assert result.evidence.search_called is True
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK

    @pytest.mark.asyncio
    async def test_explicit_request_without_tool_is_unavailable(self):
        search = _SearchProvider("не вызывается")
        plan = _plan()
        result = await _run(plan, "биткоин сейчас", search,
                            tool_schemas=[], explicit_request=True)
        assert result.evidence.search_intent == "required"
        assert result.evidence.search_axis_source == "user_forced"
        assert result.evidence.search_status == (
            _dx.SEARCH_STATUS_UNAVAILABLE)
        assert result.evidence.search_skip_reason == _dx.SKIP_TOOL_ABSENT
        assert result.evidence.claim_policy == "claim_forbidden_no_search"

    def test_axis_source_is_user_forced_without_required_caps(self):
        from services import direct_l1 as _l1
        axis = _l1.resolve_search_axis(_l1.L1Plan(), required_caps=(),
                                       explicit_request=True)
        assert (axis.search_intent, axis.source, axis.user_forced) == (
            _l1.SEARCH_REQUIRED, "user_forced", True)


# ── находка 4: напечатанный ref открывается ─────────────────────────────────


class TestPrintedRefOpensFullText:
    @pytest.mark.asyncio
    async def test_marker_ref_resolves_in_evidence(self):
        body = "Заголовок\n" + ("важное доказательство " * 200)
        search = _SearchProvider(body + "\nhttps://example.com/long")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, "проверь длинный факт", search,
                            capacity_chars=600)
        pack_text = result.pack.text
        printed = re.findall(r"полный текст: (ev:[0-9a-f]+)", pack_text)
        assert printed, "маркер обрезки обязан адресовать полный текст"
        for ref in set(printed):
            full = result.evidence.full_text(ref)
            assert full, f"висячий ref {ref}: full_text пуст"
            assert "важное доказательство" in full
        # У каждого адресуемого источника пакета ref тоже открывается.
        assert result.evidence.sources
        assert result.evidence.full_text(
            result.evidence.sources[0].content_ref)


# ── рядом: reuse не порождает второй сетевой вызов ──────────────────────────


class TestReuseDoesNotSearchAgain:
    @pytest.mark.asyncio
    async def test_reuse_plus_search_keyword_makes_no_call(self):
        search = _SearchProvider("не должно вызываться")
        plan = _plan(knowledge_origin="open_world",
                     capabilities_needed=["web_search"])
        reuse = [_dx.EvidenceSource(
            tool="fetch_article", status="ok",
            content="reuse: bitcoin|exists | статья\nбиткоин вырос на 5%",
            total_chars=60)]
        result = await _run(plan, "найди в интернете курс биткоина", search,
                            tool_schemas=_schemas("execute_web_search",
                                                 "fetch_article"),
                            prepend_sources=reuse)
        assert search.queries == [], "reuse не даёт права на новый поиск"
        assert result.evidence.search_called is False
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK
        assert result.evidence.search_skip_reason == _dx.SKIP_REUSE
