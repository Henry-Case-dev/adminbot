"""FC-R1 — исправление фактчека по диагнозу/директиве владельца 21.10.2026
(plans/features/factcheck-run-diag-2026-10-21.md, owner-corrective-followup
§3.2–3.6). ОФЛАЙН: LLM/поиск — моки и фикстуры, Telegram не используется.

TEST-LIFECYCLE: CONTRACT owner=FC-R1 (слайс CFG-06, wave 2.58.107)

Покрывает:

* FC-UNIFY (§3.2): envelope-ветка выполняет retrieval ЕДИНЫМ контуром
  (planner CFG-06) — сервис получает выдачу параметром, второй поиск не
  создаётся; временная проверка — часть единого фактчека;
* FC-SEMQUERY (§3.3): запросы строятся от самостоятельных частей клейма
  по смыслу (+generic синонимы), НЕ слайс первых 200 символов; произвольные
  темы (без зашитых предметных терминов);
* FC-EVIDQ (§3.4): нерелевантная непустая выдача уровня не останавливает
  каскад; URL ≠ доказательство (primary-fetch существующим SafeFetcher);
  дубли url=None срезаны; тип источника — лёгкие признаки домена/структуры;
* FC-PERCLAIM (§3.5): вердикт агрегируется по частям — mixed вместо
  глобального insufficient при частичных доказательствах; validator-коррекция
  не прячет подтверждённые части (production-трасса «verdict corrected»);
* FC-RENDER (§3.6): ссылки привязаны к утверждениям, у каждого источника
  роль, мусорный список доменов без объяснения исключён; рендеринг не
  искажает вердикт аналитика.
"""
import json

import pytest

from config.settings import settings
from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services import factcheck_renderer as fr
from services import factcheck_suitability as fsg
from services import factcheck_service as fs
from services import temporal_factcheck as tf
from services.search_aggregator import (
    AllSearchEnginesFailedException,
    SearchAggregator,
    classify_source_kind,
    content_terms,
    is_relevant_result,
)

CHAT_ID = -100777
TARGET_TG = 9400
TRIGGER_TG = 9401

# Production-кейс диагностики (tfr-b900e314f9024379): вейпинг/EVALI/ХОБЛ.
VAPING_CLAIM = (
    "смертельную болезнь лёгких начали находить у молодых вейперов, "
    "врачи предупреждают о всплеске хобл. к медикам всё чаще обращаются "
    "любители электронных сигарет от 16 до 40 лет с кашлем и одышкой. "
    "число случаев выросло на 30% за год")

WIKI_BLOCK = (
    "Болезнь вейперов (EVALI)\n"
    "Вспышка поражений лёгких, связанных с электронными сигаретами: кашель "
    "и одышка у молодых вейперов, врачи фиксируют рост заболеваний.\n"
    "https://ru.wikipedia.org/wiki/Bolezney_veypirov")

CDC_BLOCK = (
    "CDC: outbreak of lung injury among e-cigarette users\n"
    "Число случаев EVALI выросло; пациенты 16–40 лет с кашлем и одышкой.\n"
    "https://www.cdc.gov/tobacco/evali.html")

IRRELEVANT_BLOCK = (
    "Рецепты домашнего борща\n"
    "Классический рецепт со свёклой и капустой, время приготовления.\n"
    "https://recipes.example/borsch")

CDC_HTML = (
    '<html><head><meta property="article:published_time" '
    'content="2026-04-10T08:00:00+00:00"></head><body><p>'
    'Центр по контролю заболеваний подтвердил всплеск болезней лёгких '
    'у молодых вейперов: пациенты от 16 до 40 лет обращаются с кашлем '
    'и одышкой, число случаев выросло за год.</p></body></html>')

CDC_PUBLISHED_AT = 1775808000     # 2026-04-10T08:00:00Z


def _decision(claim=VAPING_CLAIM, scope="web"):
    items = tuple(
        fsg.ClaimItem(text=s.strip(),
                      claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
                      verifiable=True, source="literal")
        for s in claim.split(". ") if s.strip())
    return fsg.SuitabilityDecision(
        decision=fsg.DECISION_CHECKABLE,
        claim_type=fsg.CHECKABLE_FACTUAL_CLAIM, claim_items=items,
        scope=scope, reason_code="obvious_checkable_predicate",
        confidence=0.8, target_ref={}, temporal_hint=True)


@pytest.fixture
def planner_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


@pytest.fixture
def date_fetch_off():
    old = getattr(settings, "TEMPORAL_EVIDENCE_DATE_FETCH_ENABLED", True)
    object.__setattr__(settings, "TEMPORAL_EVIDENCE_DATE_FETCH_ENABLED", False)
    yield
    object.__setattr__(settings, "TEMPORAL_EVIDENCE_DATE_FETCH_ENABLED", old)


# ── FC-SEMQUERY: смысловые запросы, не слайс (§3.3) ──────────────────────────

class TestSemanticQueries:
    def test_vaping_plan_queries_by_meaning_not_raw_slice(self, planner_on):
        plan = fsp.build_retrieval_plan(_decision(), claim_text=VAPING_CLAIM)
        assert plan is not None and plan.queries
        assert len(plan.queries) <= 3                     # бюджет сохранён
        joined = " ".join(q.text.lower() for q in plan.queries)
        # смысловые термины из РАЗНЫХ самостоятельных частей
        assert "вейперов" in joined        # часть 1 (тезис о болезнях)
        assert "сигарет" in joined         # часть 2 (электронные сигареты)
        numeric = [q for q in plan.queries
                   if q.intent == fsp.INTENT_NUMERIC]
        assert numeric and "16" in numeric[0].text and "40" in numeric[0].text
        # НЕ дословный слайс первых 200 символов
        for q in plan.queries:
            assert q.text.lower() != VAPING_CLAIM.lower()[:200]
            assert len(q.text) <= 200
            # запросы не содержат текстовый «мусор» исходника
            assert "🚭" not in q.text

    def test_generic_synonyms_for_arbitrary_topic(self, planner_on):
        # НЕ медицина: экономика/техника — generic синонимы работают так же
        claim = "всплеск отказов серверов в дата-центрах, поставщики жалуются"
        plan = fsp.build_retrieval_plan(_decision(claim), claim_text=claim)
        assert plan is not None and plan.queries
        joined = " ".join(q.text.lower() for q in plan.queries)
        assert "отказов" in joined and "серверов" in joined
        assert "рост" in joined or "увеличение" in joined  # синоним «всплеска»
        # зашитых предметных терминов нет в принципе
        for forbidden in ("хобл", "evali", "вейп", "копд"):
            assert forbidden not in joined

    def test_search_queries_for_semantic_fallback(self):
        envelope = _env(VAPING_CLAIM)
        parts = tf.decompose_claim(envelope)
        queries = tf.search_queries_for(parts, envelope)
        assert queries and len(queries) <= 2
        raw = tf.normalize_text(VAPING_CLAIM)[:200]
        for q in queries:
            assert q != raw                       # не слайс начала
            assert len(q) <= 200
        joined = " ".join(queries).lower()
        assert "вейперов" in joined or "сигарет" in joined

    def test_single_unit_claim_still_semantic(self, planner_on):
        claim = "в Килякете выпало 120 мм осадков за сутки"
        plan = fsp.build_retrieval_plan(_decision(claim), claim_text=claim)
        assert plan is not None
        joined = " ".join(q.text.lower() for q in plan.queries)
        assert "килякет" in joined
        numeric = [q for q in plan.queries
                   if q.intent == fsp.INTENT_NUMERIC]
        assert numeric and "120" in numeric[0].text


# ── FC-EVIDQ: релевантность каскада, URL ≠ доказательство (§3.4) ─────────────

def _make_relevance_aggregator(monkeypatch, first_payload, second_payload):
    """Каскад с MockTransport: первый провайдер отдаёт НЕПУСТУЮ, но
    нерелевантную выдачу, второй — релевантную."""
    import httpx

    def handler(request):
        if "tavily" in str(request.url):
            return httpx.Response(200, json=first_payload, request=request)
        return httpx.Response(200, json=second_payload, request=request)

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.search_aggregator.httpx.AsyncClient",
                        factory)
    return SearchAggregator(tavily_api_key="t", exa_api_key="e")


class TestRelevanceCascade:
    @pytest.mark.asyncio
    async def test_irrelevant_first_level_continues_cascade(self, monkeypatch):
        agg = _make_relevance_aggregator(
            monkeypatch,
            {"results": [{"title": "Борщ", "content":
                          "рецепт свёкла капуста кастрюля",
                          "url": "https://t.example/1"}]},
            {"results": [{"title": "Всплеск хобл у вейперов",
                          "content": "всплеск хобл вейперы лёгких врачи",
                          "url": "https://e.example/1"}]})
        terms = content_terms("всплеск хобл вейперы лёгких врачи",
                              limit=10)
        out = await agg.search_relevant("всплеск хобл вейперы",
                                        4000, relevance_terms=terms)
        assert "e.example/1" in out            # второй провайдер использован
        assert "t.example/1" not in out        # нерелевантный уровень пропущен

    @pytest.mark.asyncio
    async def test_all_irrelevant_is_honest_failure(self, monkeypatch):
        agg = _make_relevance_aggregator(
            monkeypatch,
            {"results": [{"title": "Борщ", "content":
                          "рецепт свёкла капуста кастрюля",
                          "url": "https://t.example/1"}]},
            {"results": [{"title": "Погода", "content":
                          "осадки температура ветер прогноз",
                          "url": "https://e.example/1"}]})
        terms = content_terms("всплеск хобл вейперы лёгких", limit=10)
        with pytest.raises(AllSearchEnginesFailedException):
            await agg.search_relevant("всплеск хобл", 4000,
                                      relevance_terms=terms)

    @pytest.mark.asyncio
    async def test_search_without_terms_unchanged(self, monkeypatch):
        # регрессия: обычный `search()` без relevance_terms — прежнее
        # поведение «первая непустая выдача»
        agg = _make_relevance_aggregator(
            monkeypatch,
            {"results": [{"title": "Борщ", "content": "рецепт",
                          "url": "https://t.example/1"}]}, {"results": []})
        out = await agg.search("что-нибудь", 4000)
        assert "t.example/1" in out

    def test_is_relevant_threshold(self):
        terms = ["всплеск", "хобл", "вейперы", "лёгких", "врачи"]
        assert is_relevant_result("всплеск хобл у вейперов и лёгких", terms)
        assert not is_relevant_result("рецепт борща со свёклой", terms)
        assert is_relevant_result("любой текст", [])     # без терминов → True


class TestSourceClassification:
    def test_classify_by_domain_and_structure(self):
        assert classify_source_kind("https://www.cdc.gov/tobacco") == "primary"
        assert classify_source_kind("https://pubmed.ncbi.nlm.nih.gov/123") \
            == "research"
        assert classify_source_kind("https://doi.org/10.1000/x") == "research"
        assert classify_source_kind("https://ru.wikipedia.org/wiki/X") \
            == "reference"
        assert classify_source_kind("https://example.org/blog/post") \
            == "secondary"
        assert classify_source_kind(None) == "secondary"

    def test_evidence_rows_dedupe_url_none_duplicates(self):
        # кейс диагностики: Wikipedia ×2, у второго блока url=None —
        # дубль по содержимому срезается
        dup_no_url = "\n".join(WIKI_BLOCK.splitlines()[:-1])
        rows = tf.evidence_rows_from_results(
            f"{WIKI_BLOCK}\n\n{dup_no_url}", max_rows=10)
        assert len(rows) == 1
        assert rows[0]["url"] and rows[0]["source_kind"] == "reference"

    def test_evidence_rows_from_refs_keep_planner_metadata(self):
        ref = orch.EvidenceRef("ev-1", "https://www.cdc.gov/x",
                               "подтверждение всплеска", "primary",
                               published_at=CDC_PUBLISHED_AT)
        rows = tf.evidence_rows_from_refs((ref,))
        assert rows[0]["source_kind"] == "primary"
        assert rows[0]["published_at"] == CDC_PUBLISHED_AT
        assert rows[0]["date_parse_status"] == "parsed"
        assert rows[0]["evidence_id"] == "ev-1"
        # пустой список → fallback на текстовую выдачу
        fb = tf.evidence_rows_from_refs((), fallback_results=WIKI_BLOCK)
        assert fb and fb[0]["source_kind"] == "reference"

    @pytest.mark.asyncio
    async def test_run_retrieval_ranks_and_fetches_primary(self, planner_on):
        plan = fsp.build_retrieval_plan(_decision(), claim_text=VAPING_CLAIM)

        class _Agg:
            async def search_relevant(self, q, max_symbols,
                                      relevance_terms=None):
                return f"{WIKI_BLOCK}\n\n{IRRELEVANT_BLOCK}\n\n{CDC_BLOCK}"

        fetched = []
        pages = {
            "https://www.cdc.gov/tobacco/evali.html": CDC_HTML,
            "https://ru.wikipedia.org/wiki/Bolezney_veypirov": CDC_HTML,
        }

        async def fake_fetch(url, max_bytes=None, timeout=None):
            fetched.append(url)
            return pages.get(url, "")

        outcome = await fsp.run_retrieval(plan, aggregator=_Agg(),
                                          fetch_text=fake_fetch)
        assert outcome.ok and outcome.evidence_map is not None
        refs = outcome.evidence_map.refs
        assert refs[0].source_kind == "reference"   # сортировка по overlap'
        # primary-fetch существующим SafeFetcher-инъекцией: URL ≠ доказательство
        assert any(u.startswith("https://www.cdc.gov") for u in fetched)
        primary = [r for r in refs if r.source_kind == "primary"]
        assert primary and any(r.published_at == CDC_PUBLISHED_AT
                               for r in primary)   # дата из SafeFetcher-выдержки
        # нулевой overlap (борщ) не фетчится и не становится «доказательством»
        assert all("recipes.example" not in u for u in fetched)
        assert not any("борщ" in r.support.lower() and r.source_kind ==
                       "primary" for r in refs)


# ── FC-PERCLAIM: per-claim вердикты (§3.5) ───────────────────────────────────

class TestPerClaimVerdicts:
    def _verdict(self, payload, claim=VAPING_CLAIM, allowed_refs=None):
        return tf.verdict_from_payload(payload, _env(claim),
                                       allowed_refs=allowed_refs)

    def test_partial_support_is_mixed_not_insufficient(self):
        v = self._verdict({
            "factual_verdict": "insufficient_evidence",
            "temporal_status": "unknown",
            "parts": [
                {"part_id": "p1", "factual_verdict": "supported",
                 "evidence_refs": ["ev-1"]},
                {"part_id": "p2", "factual_verdict": "insufficient_evidence",
                 "note": "числа в выдержках отсутствуют"},
            ]})
        assert v.factual_verdict == "mixed"     # было: insufficient_evidence

    def test_refuted_part_with_unknown_rest_is_mixed(self):
        v = self._verdict({
            "factual_verdict": "insufficient_evidence",
            "temporal_status": "unknown",
            "parts": [
                {"part_id": "p1", "factual_verdict": "refuted"},
                {"part_id": "p2", "factual_verdict": "insufficient_evidence"},
            ]})
        assert v.factual_verdict == "mixed"

    def test_all_insufficient_parts_stay_insufficient(self):
        v = self._verdict({
            "factual_verdict": "insufficient_evidence",
            "temporal_status": "unknown",
            "parts": [
                {"part_id": "p1", "factual_verdict": "insufficient_evidence"},
                {"part_id": "p2", "factual_verdict": "insufficient_evidence"},
            ]})
        assert v.factual_verdict == "insufficient_evidence"  # честно

    def test_global_supported_hiding_refuted_part_is_mixed(self):
        v = self._verdict({
            "factual_verdict": "supported", "temporal_status": "current",
            "parts": [
                {"part_id": "p1", "factual_verdict": "supported"},
                {"part_id": "p2", "factual_verdict": "refuted"},
            ]})
        assert v.factual_verdict == "mixed"

    def test_validator_cannot_bury_supported_parts(self):
        """Production-трасса: аналитик дал нюансный черновик, validator
        «поправил» на insufficient_evidence — серверный guard сохраняет
        частичные результаты (TH-2 не обходится через corrected)."""
        env = _env(VAPING_CLAIM)
        draft = tf.verdict_from_payload({
            "factual_verdict": "mixed", "temporal_status": "current",
            "parts": [
                {"part_id": "p1", "factual_verdict": "supported",
                 "evidence_refs": ["ev-1"]},
                {"part_id": "p2", "factual_verdict": "insufficient_evidence",
                 "note": "числа не подтверждены"},
            ]}, env)
        corrected, applied = tf.apply_validator(
            draft, {"agree": False,
                    "corrected_factual_verdict": "insufficient_evidence",
                    "note": "выдержки не подтверждают всё утверждение"},
            env)
        assert applied is True                  # коррекция принята…
        assert corrected.factual_verdict == "mixed"   # …но части не спрятаны

    def test_parts_evidence_refs_respect_allowlist(self):
        v = self._verdict(
            {"factual_verdict": "mixed", "temporal_status": "current",
             "parts": [{"part_id": "p1", "factual_verdict": "supported",
                        "evidence_refs": ["ev-1", "ev-99"]}]},
            allowed_refs=("ev-1",))
        assert v.factual_verdict == "mixed"   # top не завышается агрегатом
        assert v.parts[0]["evidence_refs"] == ["ev-1"]  # выдуманный ev-99 срезан


# ── Офлайн-инфраструктура replay ─────────────────────────────────────────────

class _FakeDB:
    def __init__(self, origin_row):
        self._origin = origin_row
        self.runs = []

    async def get_smart_message_origin_block(self, chat_id, tg):
        return dict(self._origin)

    async def record_factcheck_run(self, payload):
        self.runs.append(dict(payload))

    async def record_factcheck_evidence(self, run_id, rows, max_rows=20):
        self.runs[-1]["evidence"] = list(rows)


class _FakeCache:
    async def get(self, key):
        return None

    async def set(self, key, value):
        return True

    async def get_update_marker(self, key, *, ttl_seconds):
        return None

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        return True

    def build_key(self, slug, raw):
        from services.smart_cache import build_key, normalize_text
        return build_key(slug, normalize_text(str(raw)))


class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("M", (), {"message_id": 555})()

    async def send_chat_action(self, chat_id, action, **kw):
        return True


class _FakePool:
    def __init__(self):
        self._permit = type("P", (), {"release": lambda self: None})()

    async def try_acquire(self, chat_id, timeout=None):
        return self._permit


class _FakeTyping:
    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


BRIDGE_BLOCK = (
    "Открытие моста в городе N\n"
    "Новый мост длиной 500 метров открыт после трёх лет строительства, "
    "стоимость 10 млрд рублей.\n"
    "https://www.gorodn.gov/news/bridge")

TOURISM_BLOCK = (
    "Опровержение запрета туризма\n"
    "Ведомство опровергло заявление о запрете туризма; публикация удалена "
    "с сайта.\n"
    "https://vesti.example/tourism")


class VapingAggregator:
    """Мок каскада: смысловые запросы → релевантные страницы своей темы,
    вне-темные запросы → нерелевантный «борщ»; relevance-вход проверяет
    overlap как настоящий агрегатор (нерелевантное — честный отказ)."""

    def __init__(self):
        self.search_calls = []

    def _hits(self, query):
        low = query.lower()
        if any(w in low for w in ("вейпер", "сигарет", "лёгких", "болезн",
                                  "медик", "хобл")):
            return f"{WIKI_BLOCK}\n\n{CDC_BLOCK}"
        if any(w in low for w in ("мост", "метров", "рубл", "строител")):
            return BRIDGE_BLOCK
        if any(w in low for w in ("туризм", "запрете", "опроверг",
                                  "публикац")):
            return TOURISM_BLOCK
        return IRRELEVANT_BLOCK

    async def search(self, q, max_symbols):
        self.search_calls.append(q)
        return self._hits(q)

    async def search_relevant(self, q, max_symbols, relevance_terms=None):
        self.search_calls.append(q)
        hits = self._hits(q)
        if not is_relevant_result(hits, relevance_terms):
            raise AllSearchEnginesFailedException("no relevant results")
        return hits


class ReplayLLM:
    """Аналитик: нюансный черновик с верхнеуровневым insufficient (как в
    production-трассе); validator — disagree с corrected=insufficient
    (трасса «verdict corrected»)."""

    def __init__(self, parts_payload=None, top="insufficient_evidence"):
        self.calls = []
        self.parts_payload = parts_payload or [
            {"part_id": "p1", "factual_verdict": "supported",
             "temporal_status": "current",
             "note": "болезнь вейперов (EVALI) подтверждается источниками",
             "evidence_refs": ["ev-1"]},
            {"part_id": "p2", "factual_verdict": "insufficient_evidence",
             "note": "конкретные числа публикации в выдержках отсутствуют",
             "evidence_refs": []},
        ]
        self.top = top

    async def generate(self, messages, **kw):
        self.calls.append(kw.get("step"))
        step = kw.get("step")
        if step == "temporal_verdict":
            return json.dumps({
                "factual_verdict": self.top,
                "temporal_status": "current",
                "evaluated_period": {"from": None, "to": None,
                                     "precision": "unknown"},
                "parts": self.parts_payload,
                "uncertainty": {"summary": "числа публикации требуют "
                                           "отдельной проверки"},
                "reason": None,
            }, ensure_ascii=False)
        if step == "temporal_validator":
            return json.dumps({
                "agree": False,
                "corrected_factual_verdict": "insufficient_evidence",
                "corrected_temporal_status": None,
                "note": "выдержки подтверждают EVALI, но не все числа"},
                ensure_ascii=False)
        return json.dumps({"factual_verdict": "insufficient_evidence",
                           "temporal_status": "unknown"},
                          ensure_ascii=False)


def _env(claim=VAPING_CLAIM):
    return tf.TemporalClaimEnvelope(
        claim_id="c-fc1", chat_id=CHAT_ID, target_tg_message_id=TARGET_TG,
        target_revision=None, target_content_hash=None,
        trigger_tg_message_id=TRIGGER_TG, claim_text=claim, claim_span=None,
        source_type="text", attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=None, original_published_precision=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None, date_source="unknown",
        date_precision="unknown", date_timezone=None, date_uncertainty={},
        requested_mode="contextual", analysis_as_of=1792200000)


def _patch_verbalize(monkeypatch, text):
    async def fake_verbalize(_generate, messages, **kwargs):
        return text, {"attempts": 1, "retries": 0, "hits": [],
                      "fallback": False}

    monkeypatch.setattr(fs, "verbalize_validated", fake_verbalize)

    async def fake_owner(chat_id):
        return ""

    monkeypatch.setattr(fs, "speech_owner_block", fake_owner)


ORIGIN_ROW = {
    "text": VAPING_CLAIM, "caption": None, "origin_type": None,
    "origin_sent_at": None, "sent_at": 1792200000, "current_revision": None,
    "content_hash": None, "origin_sender_user_id": None,
    "origin_chat_id": None, "origin_display_name": "CHP Perm",
    "author_name": None, "forward_source": "CHP Perm"}


# ── FC-UNIFY + FC-PERCLAIM + FC-RENDER: сквозной офлайн-replay ──────────────

class TestVapingReplayOffline:
    """Полный офлайн-путь query → search → fetch → evidence → verdict →
    response на production-кейсе (tfr-b900e314f9024379) и на
    синтетических многочастных сообщениях."""

    async def _run(self, monkeypatch, llm, claim=VAPING_CLAIM,
                   verbalized="EVALI у вейперов подтверждается источниками. "
                              "Конкретные числа публикации в выдержках не "
                              "нашли. Даты части источников не распознались."):
        object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
        _patch_verbalize(monkeypatch, verbalized)

        async def fake_evaluate(db_, chat_id, **kwargs):
            return _decision(kwargs.get("claim_text") or claim), None

        monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_evaluate)
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_enabled", lambda: True)
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_cache_enabled",
            lambda: False)
        monkeypatch.setattr(orch, "get_smartmodule_concurrency_pool",
                            lambda: _FakePool())
        monkeypatch.setattr(orch, "typing_active", _FakeTyping)
        db = _FakeDB(origin_row=dict(ORIGIN_ROW, text=claim))
        agg = VapingAggregator()

        async def fake_fetch(url, max_bytes=None, timeout=None):
            return CDC_HTML

        import services.factcheck_planner as planner_mod
        real_fetch = planner_mod.fetch_primary_evidence

        async def injected_fetch(url, **kw):
            kw.pop("fetch_text", None)
            return await real_fetch(url, fetch_text=fake_fetch, **kw)

        monkeypatch.setattr(planner_mod, "fetch_primary_evidence",
                            injected_fetch)
        service = fs.FactCheckService(aggregator=agg, llm=llm, memory=None)
        bot = _FakeBot()
        await orch.run_factcheck(
            orch.FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
                target_tg_message_id=TARGET_TG, target_text=claim,
                kind="reply"),
            service=service, db=db, bot=bot, cache=_FakeCache())
        return agg, db, bot

    @pytest.mark.asyncio
    async def test_mixed_verdict_with_per_claim_rendering(
            self, monkeypatch, planner_on, date_fetch_off):
        agg, db, bot = await self._run(monkeypatch, ReplayLLM())
        # FC-UNIFY: единый retrieval — агрегатор звался планировщиком
        assert agg.search_calls
        run = db.runs[0]
        assert run["pipeline_version"] == "tf2"
        # FC-PERCLAIM: mixed вместо глобального insufficient_evidence
        # (production было: insufficient/unknown + reason=null)
        assert run["factual_verdict"] == "mixed"
        assert run["temporal_status"] == "current"
        # evidence дошёл до аналитика из единого контура (wiki+cdc+primary)
        kinds = {r["source_kind"] for r in run.get("evidence", [])}
        assert "reference" in kinds and "primary" in kinds
        assert any(r["published_at"] for r in run.get("evidence", []))
        # FC-RENDER: было «Недостаточно данных» + 6 безадресных хостов
        markup = bot.sent[0]["text"]
        assert "<b>Подтверждается частично</b>" in markup
        assert "Недостаточно данных" not in markup
        assert "По утверждениям:" in markup     # ссылки привязаны к тезисам
        # роль каждого источника объяснена
        visible = fr.visible_text(markup)
        assert ("— пересказ" in visible or "— энциклопедия" in visible
                or "— первоисточник" in visible)
        # конкретная цитата в href, не в видимом тексте
        assert 'href=' in markup
        assert "https://" not in visible
        assert "instagram" not in markup        # мусорного списка нет

    @pytest.mark.asyncio
    async def test_all_parts_supported_is_supported(
            self, monkeypatch, planner_on, date_fetch_off):
        llm = ReplayLLM(parts_payload=[
            {"part_id": "p1", "factual_verdict": "supported",
             "evidence_refs": ["ev-1"]},
            {"part_id": "p2", "factual_verdict": "supported",
             "evidence_refs": ["ev-2"]},
        ])
        _agg, db, bot = await self._run(
            monkeypatch, llm,
            claim="в городе N открыли новый мост длиной 500 метров. "
                  "строительство шло три года и стоило 10 млрд рублей",
            verbalized="Мост открыт. Параметры подтверждаются.")
        assert db.runs[0]["factual_verdict"] == "supported"

    @pytest.mark.asyncio
    async def test_refuted_part_reported_not_hidden(
            self, monkeypatch, planner_on, date_fetch_off):
        llm = ReplayLLM(parts_payload=[
            {"part_id": "p1", "factual_verdict": "refuted",
             "evidence_refs": ["ev-1"]},
            {"part_id": "p2", "factual_verdict": "insufficient_evidence"},
        ])
        _agg, db, bot = await self._run(
            monkeypatch, llm,
            claim="заявление чиновника о запрете туризма опровергли. "
                  "публикацию удалили с сайта ведомства",
            verbalized="Запрет туризма не подтверждается. Судьба публикации "
                       "неясна.")
        assert db.runs[0]["factual_verdict"] == "mixed"
        markup = bot.sent[0]["text"]
        assert "не подтверждается" in markup    # разбор части виден

    @pytest.mark.asyncio
    async def test_empty_search_stays_honest_insufficient(
            self, monkeypatch, planner_on, date_fetch_off):
        class _DownAgg:
            async def search(self, q, max_symbols):
                raise AllSearchEnginesFailedException("down")

            async def search_relevant(self, q, max_symbols,
                                      relevance_terms=None):
                raise AllSearchEnginesFailedException("down")

        _agg, db, bot = await self._run(
            monkeypatch, ReplayLLM(),
            claim="загадочное утверждение про новый закон о налогах",
            verbalized="Данных недостаточно.")
        assert db.runs[0]["factual_verdict"] == "insufficient_evidence"
        # P0-FACTCHECK (§3.6): недоступность провайдеров — технический сбой,
        # а не «недостаточно данных»: вердикт остаётся консервативным, но
        # заголовок называет настоящую причину.
        assert "Проверка не завершена: поиск недоступен" in bot.sent[0]["text"]
        assert "<b>Недостаточно данных для проверки</b>" \
            not in bot.sent[0]["text"]
