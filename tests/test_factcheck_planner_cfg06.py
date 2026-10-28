"""CFG-06 W4 — планировщик проверки + структурный evidence (06C).

TEST-LIFECYCLE: CONTRACT owner=CFG-06

Контракты:
  * OFF-паритет: планировщик — часть pipeline v2; флаг default OFF →
    `build_retrieval_plan` = None (ни одного платного запроса);
  * осмысленные запросы (фикс 06A.4): из claim/claim_items, с различающимися
    интентами (entity/numeric/temporal/origin), НЕ дословный слайс клейма,
    ≤200 символов, ≤3 запросов;
  * privacy (06G.3): имена участников чата не утекают в веб-запрос;
  * структурный evidence: URL отдельно от текста, стабильные ID ev-N
    текущего прогона, allowlist = ID этого прогона; SafeFetch — инъекция
    (сеть off), fail-open;
  * якорь оркестратора: EvidenceMap наполняется ТОЛЬКО когда ветка не дала
    своих evidence (temporal-ветка не перезаписывается); аргументы сервиса
    не меняются (байт-паритет legacy-ветки W3 сохранён).
"""
import asyncio
import json

import pytest

from config.settings import settings
from services import factcheck_planner as fsp
from services import factcheck_suitability as fsg
from services.factcheck_orchestrator import (
    CheckedVerdict,
    EvidenceMap,
    EvidenceRef,
    FactcheckRequest,
    run_factcheck,
)

CHAT_ID = -100333
TARGET_TG = 9200
TRIGGER_TG = 9201


class FakeAggregator:
    def __init__(self, default=None, results=None, fail_queries=()):
        self.default = default or (
            "Рекорд осадков в Килякете\n"
            "В июле 2019 года метеостанция зафиксировала 120 мм осадков\n"
            "https://example.org/meteo")
        self.results = results or {}
        self.fail_queries = set(fail_queries)
        self.calls = []

    async def search(self, query, max_symbols):
        self.calls.append((query, max_symbols))
        if query in self.fail_queries:
            raise RuntimeError("engines down")
        return self.results.get(query, self.default)


class FakeDB:
    def __init__(self, rows=None, origin_row=None):
        self._rows = rows or []
        self._origin = origin_row
        self.queries = []

    async def get_messages_around(self, chat_id, tg, before, after):
        self.queries.append(("around", chat_id, before, after))
        return list(self._rows)

    async def get_recent_messages(self, chat_id, limit):
        self.queries.append(("recent", chat_id, limit))
        return list(self._rows[-limit:]) if limit else []

    async def get_smart_message_origin_block(self, chat_id, tg):
        if self._origin is None:
            raise RuntimeError("no origin")
        return dict(self._origin)


class FakeCache:
    def __init__(self):
        self.store = {}
        self.markers = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = value

    async def get_update_marker(self, key, *, ttl_seconds):
        return self.markers.get(key)

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.markers[key] = payload

    def build_key(self, slug, raw):
        from services.smart_cache import build_key, normalize_text
        return build_key(slug, normalize_text(str(raw)))


class FakeBot:
    id = 862000000

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("M", (), {"message_id": 555})()

    async def send_chat_action(self, chat_id, action, **kw):
        return True


class FakeService:
    """Legacy-ветка + агрегатор (для planner-якоря)."""

    def __init__(self, aggregator=None, verdict="Проверено: тезис "
                                              "не подтвердился."):
        self.aggregator = aggregator
        self.llm = None
        self.verdict = verdict
        self.check_claim_calls = []

    async def check_claim(self, target_text, user_hint, forward_source, *,
                          chat_id=None, chat_context=None,
                          search_results=None):
        self.check_claim_calls.append({
            "target_text": target_text, "user_hint": user_hint,
            "forward_source": forward_source, "chat_id": chat_id,
            "chat_context": chat_context, "search_results": search_results})
        return self.verdict


def _decision(claim="в Килякете выпало 120 мм осадков за сутки — это рекорд",
              scope="web"):
    item = fsg.ClaimItem(text=claim,
                         claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
                         verifiable=True, source="literal")
    return fsg.SuitabilityDecision(
        decision=fsg.DECISION_CHECKABLE,
        claim_type=fsg.CHECKABLE_FACTUAL_CLAIM, claim_items=(item,),
        scope=scope, reason_code="obvious_checkable_predicate",
        confidence=0.8, target_ref={})


class _Ctx:
    """Лёгкий stand-in ConversationContext (только authors)."""

    def __init__(self, authors):
        self.messages = [type("M", (), {"author": a, "text": "текст",
                                        "tg_message_id": 1})()
                         for a in authors]


@pytest.fixture
def planner_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


# ── OFF-паритет ───────────────────────────────────────────────────────────────

class TestPlannerOff:
    def test_default_off_returns_none(self):
        assert fsp.planner_enabled() is False
        assert fsp.build_retrieval_plan(
            _decision(), claim_text="любой клейм с фактами") is None

    def test_gate_mirrors_pipeline_v2_flag(self, planner_on):
        assert fsp.planner_enabled() is True


# ── План из клейма (фикс 06A.4) ───────────────────────────────────────────────

class TestPlanBuilding:
    def test_semantic_queries_not_raw_slice(self, planner_on):
        claim = ("В 2019 году в Килякете выпало рекордное количество "
                 "осадков. Урожай погиб полностью.")
        plan = fsp.build_retrieval_plan(_decision(claim), claim_text=claim)
        assert plan is not None and plan.queries
        assert len(plan.queries) <= 3
        for q in plan.queries:
            assert q.intent in fsp.INTENTS
            assert len(q.text) <= 200
            # 06A.4-фикс: запрос — реформулировка, не весь клейм дословно
            assert q.text.lower() != claim.lower()[:200]
        joined = " ".join(q.text.lower() for q in plan.queries)
        assert "килякет" in joined               # сущность сохранена
        assert "2019" in joined                  # уточнение в запросе части
        # F4 (review r1): части не голодают — каждая часть имеет свой
        # запрос (прежнее требование «уникальные интенты» противоречило
        # пользовательскому §3.3/§3.5: частей больше, чем интентов).
        assert sum(1 for q in plan.queries
                   if q.intent == fsp.INTENT_ENTITY_CHECK) >= 2
        assert fsp.INTENT_TEMPORAL in [q.intent for q in plan.queries]

    def test_numeric_intent_for_numbers(self, planner_on):
        claim = "в Килякете выпало 120 мм осадков за сутки"
        plan = fsp.build_retrieval_plan(_decision(claim), claim_text=claim)
        assert plan is not None
        assert fsp.INTENT_NUMERIC in [q.intent for q in plan.queries]
        numeric = [q for q in plan.queries
                   if q.intent == fsp.INTENT_NUMERIC][0]
        assert "120" in numeric.text

    def test_privacy_authors_not_leaked(self, planner_on):
        claim = "Вася утверждает, что в Килякете выпало 120 мм осадков"
        plan = fsp.build_retrieval_plan(
            _decision(claim), ctx=_Ctx(["Вася", "Петя"]), claim_text=claim)
        assert plan is not None
        assert "Вася" in plan.dropped_privacy
        for q in plan.queries:
            assert "вася" not in q.text.lower()

    def test_chat_scope_no_web_plan(self, planner_on):
        assert fsp.build_retrieval_plan(
            _decision(scope="chat_history"),
            claim_text="в Килякете выпало 120 мм осадков") is None

    def test_no_decision_no_plan(self, planner_on):
        assert fsp.build_retrieval_plan(None) is None


# ── 06G.1: биологический спор + латиница-сущность (гап W7 закрыт) ────────────

class TestSaccharomycesBiologicalCase:
    """06G.1/06C.3: в биологическом споре «дрожжи — грибы, а не бактерии»
    атомарный тезис выделяется гейтом (не отклоняется как бессмыслица,
    06B.4), а точное научное название Saccharomyces boulardii сохраняется
    в осмысленных веб-запросах и в структурном evidence.

    TEST-LIFECYCLE: REGRESSION owner=CFG-06 (W7-гап: Saccharomyces-кейс
    был покрыт только архитектурно, отдельного кейса не было)."""

    CLAIM = ("дрожжи — это грибы, а не бактерии, поэтому пробиотики с "
             "Saccharomyces boulardii восстанавливают микрофлору после "
             "антибиотиков")

    def test_binomial_preserved_and_claim_checkable(self, planner_on):
        old_gate = getattr(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED",
                           False)
        object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED",
                           True)
        try:
            gate = fsg.evaluate_suitability(self.CLAIM, None, None)
        finally:
            object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED",
                               old_gate)
        assert gate.decision == fsg.DECISION_CHECKABLE
        assert gate.claim_items                      # атомарный тезис выделен
        plan = fsp.build_retrieval_plan(_decision(self.CLAIM),
                                        claim_text=self.CLAIM)
        assert plan is not None and plan.queries
        joined = " ".join(q.text.lower() for q in plan.queries)
        assert "saccharomyces" in joined and "boulardii" in joined
        for q in plan.queries:                       # 06A.4: не сырой слайс
            assert q.text.lower() != self.CLAIM.lower()[:200]

    def test_saccharomyces_evidence_structured(self):
        refs = fsp.evidence_refs_from_search(
            "Saccharomyces boulardii — пробиотический дрожжевой грибок\n"
            "Относится к грибам, а не к бактериям; применяется после "
            "антибиотиков\nhttps://example.org/saccharomyces-boulardii")
        assert refs
        assert refs[0].url == "https://example.org/saccharomyces-boulardii"
        assert "saccharomyces" in refs[0].support.lower()
        assert "https://" not in refs[0].support     # URL отдельно от текста


# ── Структурный evidence ──────────────────────────────────────────────────────

class TestStructuredEvidence:
    def test_search_refs_url_separate_from_text(self):
        refs = fsp.evidence_refs_from_search(
            "Рекорд осадков\n120 мм за сутки, метеостанция\n"
            "https://example.org/meteo\n\n"
            "Second source\nЕщё сниппет\nhttps://example.org/second")
        assert len(refs) == 2
        assert refs[0].url == "https://example.org/meteo"
        assert "https://" not in refs[0].support
        assert "Рекорд осадков" in refs[0].support
        assert refs[0].source_kind == "secondary"

    @pytest.mark.asyncio
    async def test_execute_retrieval_consistent_map(self, planner_on):
        plan = fsp.build_retrieval_plan(
            _decision(), claim_text="в Килякете выпало 120 мм осадков")
        agg = FakeAggregator()
        emap = await fsp.execute_retrieval(plan, aggregator=agg,
                                           fetch_text=lambda *a, **k: None)
        assert emap is not None and emap.refs
        ids = [r.evidence_id for r in emap.refs]
        assert ids == [f"ev-{i + 1}" for i in range(len(ids))]
        assert emap.allowlist == tuple(ids)
        assert len(emap.links()) == len(set(emap.links()))
        # запросы — из плана (осмысленные), не сырой клейм
        for query, _max in agg.calls:
            assert query in [q.text for q in plan.queries]

    @pytest.mark.asyncio
    async def test_primary_fetch_via_injection(self, planner_on):
        html = ('<html><head><meta property="article:published_time" '
                'content="2019-07-01T08:00:00+00:00"></head><body><p>'
                'Метеостанция Килякета подтвердила: в июле 2019 года '
                'выпало 120 мм осадков за сутки, что стало рекордом '
                'наблюдений за всю историю станции.</p></body></html>')

        async def fake_fetch(url, max_bytes=None, timeout=None):
            return html

        ref = await fsp.fetch_primary_evidence("https://example.org/meteo",
                                               fetch_text=fake_fetch)
        assert ref is not None
        assert ref.source_kind == "primary"
        assert ref.published_at == 1561968000     # 2019-07-01 08:00 UTC
        assert "120 мм" in ref.support
        assert "<p>" not in ref.support           # теги срезаны

    @pytest.mark.asyncio
    async def test_primary_fetch_fail_open(self):
        async def broken(url, **kw):
            raise RuntimeError("down")

        assert await fsp.fetch_primary_evidence(
            "https://example.org/x", fetch_text=broken) is None
        assert await fsp.fetch_primary_evidence(
            "https://example.org/x",
            fetch_text=lambda *a, **k: "<p>коротко</p>") is None

    @pytest.mark.asyncio
    async def test_query_failure_is_honest_degradation(self, planner_on):
        plan = fsp.build_retrieval_plan(
            _decision(), claim_text="в Килякете выпало 120 мм осадков")
        agg = FakeAggregator(fail_queries=set(q.text for q in plan.queries))
        assert await fsp.execute_retrieval(plan, aggregator=agg) is None


# ── Якорь оркестратора (моя зона) ────────────────────────────────────────────

class TestOrchestratorAnchor:
    @pytest.mark.asyncio
    async def test_legacy_branch_evidence_filled_args_parity(
            self, planner_on):
        agg = FakeAggregator()
        svc = FakeService(aggregator=agg)
        db = FakeDB()
        bot = FakeBot()
        await run_factcheck(
            FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
                target_tg_message_id=TARGET_TG,
                target_text="в Килякете выпало 120 мм осадков за сутки",
                kind="reply"),
            service=svc, db=db, bot=bot, cache=FakeCache())
        # байт-паритет W3: аргументы сервиса не изменились (search_results —
        # выдача единого контура v2, W6; None/строка, остальное 1:1)
        call = svc.check_claim_calls[0]
        assert call["target_text"] == ("в Килякете выпало 120 мм осадков "
                                       "за сутки")
        assert call["chat_id"] == CHAT_ID
        # планировщик выполнил осмысленные запросы ДО вердикта
        assert agg.calls
        for query, _max in agg.calls:
            assert "120" in query.lower() or "килякет" in query.lower()
        # единый контур W6: выдача плана ушла в сервис, внутренний поиск
        # агрегатора для user-content не дублируется (агрегатор звался
        # только планировщиком)
        assert call["search_results"], "плановая выдача должна идти в сервис"
        # W5 renderer (join §6): URL из EvidenceMap — ровно 1 раз и только
        # как href; в видимом тексте полного URL нет (label — домен)
        assert len(bot.sent) == 1
        assert bot.sent[0]["text"].count(
            'href="https://example.org/meteo"') == 1
        from services.factcheck_renderer import visible_text
        visible = visible_text(bot.sent[0]["text"])
        assert "https://example.org/meteo" not in visible
        assert "example.org" in visible          # label = домен (контракт W5)

    @pytest.mark.asyncio
    async def test_envelope_branch_unified_retrieval(self, planner_on,
                                                     monkeypatch):
        """FC-UNIFY (owner 21.10.2026 §3.2): envelope-ветка выполняет retrieval
        через ЕДИНЫЙ контур планировщика (агрегатор зовётся планировщиком,
        выдача уходит в сервис параметром retrieval); EvidenceMap при этом
        НЕ перезаписывается — temporal-ветка несёт ev-N текущего прогона."""
        origin = {"text": "в килякете 120 мм", "caption": None,
                  "origin_type": None, "origin_sent_at": None,
                  "sent_at": 1700000000, "current_revision": None,
                  "content_hash": None, "origin_sender_user_id": None,
                  "origin_chat_id": None, "origin_display_name": None,
                  "author_name": "Вася", "forward_source": None}
        db = FakeDB(origin_row=origin)
        agg = FakeAggregator()

        class _EnvelopeService:
            aggregator = agg

            def __init__(self):
                self.retrievals = []

            async def check_claim_envelope(self, envelope, *,
                                           chat_context=None,
                                           retrieval=None):
                self.retrievals.append(retrieval)
                from services.temporal_factcheck import (
                    TemporalRunResult, TemporalVerdict)
                verdict = TemporalVerdict(
                    factual_verdict="refuted", temporal_status="current",
                    evaluated_period={}, assessment_mode="contextual",
                    as_of=1760900000, evidence_refs=("ev-1",), reason=None)
                return TemporalRunResult(
                    envelope=envelope, verdict=verdict,
                    verdict_text="Вердикт temporal-ветки",
                    evidence_rows=({"evidence_id": "ev-1",
                                    "url": "https://example.org/t",
                                    "support": "s", "source_kind":
                                    "secondary", "published_at": None},))

        svc = _EnvelopeService()
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_enabled", lambda: True)
        # FC-06C (§6.3): патч cache_enabled снят — гейт удалён вместе с кешем.
        bot = FakeBot()
        await run_factcheck(
            FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
                target_tg_message_id=TARGET_TG,
                target_text="в Килякете выпало 120 мм осадков за сутки",
                kind="reply"),
            service=svc, db=db, bot=bot, cache=FakeCache())
        # единый механизм: планировщик выполнил осмысленные запросы...
        assert agg.calls, "envelope-ветка должна идти через единый retrieval"
        # ...и выдача контура передана сервису (второго поиска нет)
        assert svc.retrievals and svc.retrievals[0].search_text
        # из planner-запросов: privacy (участники не утекают)
        for query, _max in agg.calls:
            assert "вася" not in query.lower()
        # EvidenceMap остался от ветки (не перезаписан planner-картой):
        # доставленный текст — вердикт ветки, рендер выполнен
        assert len(bot.sent) == 1
        assert "Вердикт temporal-ветки" in bot.sent[0]["text"]

    @pytest.mark.asyncio
    async def test_v2_off_planner_never_called(self, monkeypatch):
        # OFF: без v2 планировщик нестроит план даже при явном вызове
        object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
        try:
            assert fsp.build_retrieval_plan(
                _decision(), claim_text="в Килякете 120 мм") is None
        finally:
            object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED",
                               False)
