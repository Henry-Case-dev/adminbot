"""FCT-S3-RETRIEVAL — retrieval-контракт S3 (FCT-201..FCT-502).

Проверяется наблюдаемое поведение production-путей планировщика и агрегатора,
а не внутренняя структура: пак провайдера → кандидаты → claim-aware отношение →
EvidenceMap/проекция модельного раздела → coverage/execution-статусы.
Фикстуры внутри модуля (контракт §8: без нового каталога фикстур).

Покрытие строк:
* FCT-201/401 — лексика только recall/якоря; supports без якоря невозможен;
  мягкий recall пака (перефразированный материал не выбрасывается).
* FCT-203 — приватная диагностика: запросы с claim_id/intent/purpose,
  провайдер/исход/латентность, stop_reason; без текстов/URL в событии.
* FCT-301 — различимые коды resource_limit/global_deadline/provider_timeout/
  rate_limit/cancelled/claim_not_searched/no_relevant_result/source_unreadable.
* FCT-302 — объём от claim coverage: фетчи по частям, длина запроса не режет
  якоря/метрики/период.
* FCT-303 — только существующие limits.factcheck_* с провенансом.
* FCT-306 — нет повторов идентичного запроса, честный partial.
* FCT-402 — basis + assertion_type passage; пустой basis невозможен.
* FCT-403 — material_role отделён от «официальности» домена.
* FCT-404 — claim-specific фрагмент + провенанс/версия выдержки.
* FCT-405 — копии одной публикации в одной independence_group.
* FCT-406 — отсеянный кандидат не попадает ни в evidence, ни в модельный текст.
* FCT-502 — дата провайдера структурно (published_at + published_at_source).
"""
from __future__ import annotations

import dataclasses
import json
import re

import pytest

from services import factcheck_planner as fsp
from services import search_aggregator as sa

CHAT = -100777

CLAIM_MARKETS = "Индекс S&P 500 упал на 2,1% 30 октября 2026 года."
CLAIM_GENERIC = "Мировые рынки обвалились."
CLAIM_RAIN = "В июле 2019 в Килякете выпало 120 мм осадков за сутки."


# ── helpers ─────────────────────────────────────────────────────────────────

def _unit(text: str = CLAIM_MARKETS, *, claim_id: str = "c1",
          metrics=("2,1%",), entities=("S&P",), timeframe="30 октября 2026",
          units=("percent",)) -> "fsp.ClaimUnit":
    return fsp.ClaimUnit(
        claim_id=claim_id, text=text, metrics=tuple(metrics),
        entities=tuple(entities), units=tuple(units), timeframe=timeframe)


def _plan(*units: "fsp.ClaimUnit", refine: bool = False,
          needs_primary_fetch: bool = False) -> "fsp.RetrievalPlan":
    queries = []
    for unit in units:
        queries.append(fsp.SearchQuery(
            text=" ".join(fsp._claim_terms(unit.text, limit=6)),
            intent=fsp.INTENT_ENTITY_CHECK, claim_id=unit.claim_id))
    if refine:
        for unit in units:
            queries.append(fsp.SearchQuery(
                text=(" ".join(fsp._claim_terms(unit.text, limit=6))
                      + " уточнение"),
                intent=fsp.INTENT_NUMERIC, claim_id=unit.claim_id,
                purpose=fsp.QUERY_PURPOSE_REFINE))
    return fsp.RetrievalPlan(
        queries=tuple(queries), needs_web=True,
        needs_primary_fetch=needs_primary_fetch,
        claim_text=" ".join(unit.text for unit in units),
        claims=tuple(units), chat_id=CHAT)


def _off_limits(**overrides) -> "fsp.FactcheckLimits":
    base = fsp.FactcheckLimits(
        budgets_enabled=False, budget_source="chat", budget_known=True,
        base_seconds=None, max_seconds=None, refine_calls=None,
        total_queries=None, search_text_chars=None,
        primary_fetches=None, excerpt_chars=None)
    return dataclasses.replace(base, **overrides)


class Routed:
    """Агрегатор-двойник: пак по игле, отказы по причине, учёт вызовов."""

    def __init__(self, routes=(), *, default="", fail_needles=(),
                 fail_reason="provider_error", empty_needles=(),
                 slow_needles=(), sleep=0.0):
        self.routes = tuple(routes)
        self.default = default
        self.fail_needles = tuple(fail_needles)
        self.fail_reason = fail_reason
        self.empty_needles = tuple(empty_needles)
        self.slow_needles = tuple(slow_needles)
        self.sleep = sleep
        self.calls: list[str] = []
        self.relevance_terms: list[list] = []

    async def search_relevant(self, query, max_symbols=None,
                              relevance_terms=None, timeout_budget=None,
                              trace=None):
        self.calls.append(query)
        self.relevance_terms.append(list(relevance_terms or ()))
        low = query.lower()
        if any(needle in low for needle in self.slow_needles):
            import asyncio
            await asyncio.sleep(self.sleep)
        if any(needle in low for needle in self.fail_needles):
            raise sa.AllSearchEnginesFailedException("fake", reason=self.fail_reason)
        if any(needle in low for needle in self.empty_needles):
            raise sa.AllSearchEnginesFailedException("fake", reason="empty_results")
        for needle, block in self.routes:
            if needle in low:
                return block
        if not self.default:
            raise sa.AllSearchEnginesFailedException("fake", reason="empty_results")
        return self.default


# ── FCT-201/401: лексика — recall, не судья ────────────────────────────────

def test_word_overlap_only_is_not_support_with_anchor_profile():
    claim = _unit(CLAIM_GENERIC, metrics=(), entities=(), timeframe="",
                  units=())
    doc = ("Мировые рынки обвалились, инвесторы уходили из риска "
           "и продавали акции")
    legacy = sa.claim_relevance(doc, claim_text=claim.vocabulary())
    profiled = sa.claim_relevance(doc, claim_text=claim.vocabulary(),
                                  require_anchor=True)
    # legacy-профиль (другие потребители) не переоткрывается
    assert legacy.role == sa.EVIDENCE_ROLE_SUPPORTS
    # evidence-профиль: без специфического якоря — контекст, не доказательство
    assert profiled.role == sa.EVIDENCE_ROLE_BACKGROUND
    assert profiled.anchor is False
    assert "word_overlap_only" in profiled.basis
    assert profiled.displayable is False


def test_timeframe_anchor_allows_support():
    claim = _unit(CLAIM_GENERIC, metrics=(), entities=(),
                  timeframe="30 октября 2026", units=())
    doc = "Мировые рынки обвалились 30 октября 2026 года, инвесторы уходили"
    rel = sa.claim_relevance(doc, claim_text=claim.vocabulary(),
                             timeframe=claim.timeframe, require_anchor=True)
    assert rel.role == sa.EVIDENCE_ROLE_SUPPORTS
    assert any(item.startswith("time:") for item in rel.basis)


def test_ticker_abbreviation_is_an_anchor():
    assert "S&P" in fsp._entities("Индекс S&P 500 упал на 2,1%")
    unit = fsp._pseudo_claim("Индекс S&P 500 упал на 2,1%")
    ref = fsp.EvidenceRef(evidence_id="", url="https://e/1",
                          support="S&P 500 falls 2.1% on October 30",
                          source_kind="secondary")
    rel = fsp._relevance_for(ref, unit)
    assert rel.role == sa.EVIDENCE_ROLE_SUPPORTS
    assert any(item.startswith("entity:") for item in rel.basis)


@pytest.mark.asyncio
async def test_word_overlap_only_pack_is_not_evidence_end_to_end():
    """Planner обязан использовать evidence-профиль (require_anchor=True)."""
    unit = _unit(CLAIM_GENERIC, metrics=(), entities=(), timeframe="",
                 units=())
    doc = ("Мировые рынки обвалились, инвесторы уходили из риска\n"
           "https://news.example/1")
    outcome = await fsp.run_retrieval(
        _plan(unit), aggregator=Routed(default=doc), limits=_off_limits())
    assert outcome.evidence_map is None
    assert outcome.claims[0].evidence == ()
    assert outcome.claims[0].status_detail == fsp.CLAIM_STATUS_NO_RELEVANT_SOURCES
    # recall не потерян: кандидат остаётся в типизированном разделе
    assert "news.example/1" in outcome.search_text


# ── FCT-401: мягкий recall пака ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_low_overlap_pack_returns_instead_of_hard_failure(monkeypatch):
    agg = sa.SearchAggregator(tavily_api_key="t", exa_api_key="e")
    calls: list[str] = []

    async def weak(query, timeout_budget=None):
        calls.append("weak")
        return "Борщ рецепт свёкла капуста\nhttps://t.example/1"

    async def down(query, timeout_budget=None):
        calls.append("down")
        raise RuntimeError("exa 503")

    async def ddg(query, timeout_budget=None):
        calls.append("ddg")
        raise ValueError("ddg: empty results")

    monkeypatch.setattr(agg, "_search_tavily", weak)
    monkeypatch.setattr(agg, "_search_exa", down)
    monkeypatch.setattr(agg, "_search_ddg", ddg)
    trace: dict = {}
    out = await agg.search_relevant(
        "всплеск хобл вейперы", 4000,
        relevance_terms=sa.content_terms("всплеск хобл вейперы"), trace=trace)
    assert "t.example/1" in out
    assert trace["reason"] == "low_overlap_fallback"
    assert calls == ["weak", "down", "ddg"]


@pytest.mark.asyncio
async def test_all_providers_failed_still_raises(monkeypatch):
    agg = sa.SearchAggregator(tavily_api_key="t", exa_api_key="e")

    async def down(query, timeout_budget=None):
        raise RuntimeError("503")

    monkeypatch.setattr(agg, "_search_tavily", down)
    monkeypatch.setattr(agg, "_search_exa", down)
    monkeypatch.setattr(agg, "_search_ddg", down)
    with pytest.raises(sa.AllSearchEnginesFailedException):
        await agg.search_relevant("q", 4000,
                                  relevance_terms=["q", "query"])


# ── FCT-502: даты провайдера структурно ────────────────────────────────────

def test_provider_date_is_structured_and_not_in_support():
    pack = ("Рекорд осадков\n120 мм за сутки\n"
            "дата публикации: 2019-07-01\nhttps://weather.example/1")
    cands = fsp.search_candidates(pack)
    assert len(cands) == 1
    cand = cands[0]
    assert cand.published_at == 1561939200
    assert cand.published_at_source == "provider"
    assert cand.date_status == "known"
    assert cand.url == "https://weather.example/1"
    assert "дата публикации" not in cand.support
    assert "2019-07-01" not in cand.support
    ref = cand.evidence_ref()
    assert ref.published_at == 1561939200


def test_missing_date_is_unknown_and_never_invented():
    cand = fsp.search_candidates("Тема\nсниппет\nhttps://e/1")[0]
    assert cand.published_at is None
    assert cand.published_at_source == ""
    assert cand.date_status == "unknown"


def test_stale_provider_date_drops_candidate():
    unit = _unit("30 октября 2026 года акции Alphabet упали на 5%.",
                 metrics=("5%",), entities=("Alphabet",),
                 timeframe="30 октября 2026", units=("percent",))
    unit = dataclasses.replace(unit, event_at=1793145600)  # 2026-10-30
    stale = fsp.EvidenceRef(
        evidence_id="", url="https://e/1",
        support="Alphabet упала на 5% 30 октября 2026",
        source_kind="secondary", published_at=1561939200)
    fresh = dataclasses.replace(stale, published_at=1793232000)
    assert fsp._is_stale(stale, unit) is True
    assert fsp._is_stale(fresh, unit) is False


# ── FCT-404: claim-specific passage и провенанс/версия ─────────────────────

def test_claim_specific_passage_not_first_paragraph():
    html = ("<html><body><p>Коротко.</p><p>"
            "Совсем не про тезис длинный первый абзац, которого достаточно "
            "для порога в восемьдесят символов и даже больше.</p>"
            "<p>В Килякете в июле 2019 выпало 120 мм осадков за сутки.</p>"
            "</body></html>")
    passage, matched = fsp._claim_passage_from_html(html, claim=_unit(
        CLAIM_RAIN, metrics=("120 мм",), entities=("Килякете",),
        timeframe="июле 2019", units=("мм",)))
    assert matched is True
    assert "120 мм" in passage
    assert "Совсем не про тезис" not in passage


def test_unmatched_document_is_marked_not_claim_passage():
    html = "<html><body><p>" + ("Общий текст без якорей. " * 8) + "</p></body></html>"
    passage, matched = fsp._claim_passage_from_html(html, claim=_unit())
    assert matched is False
    assert passage


@pytest.mark.asyncio
async def test_fetched_page_reports_full_text_and_date_source():
    html = ("<html><head><meta property=\"article:published_time\" "
            "content=\"2019-07-01T08:00:00+00:00\"></head><body><p>"
            "Общий обзор погодных условий региона и сопредельных областей "
            "за длительный период наблюдений, без отношения к тезису.</p><p>"
            "В Килякете в июле 2019 выпало 120 мм осадков за сутки.</p>"
            "<p>Наблюдения станции продолжаются, данные передаются в сводку "
            "ежедневно и публикуются на сайте ведомства.</p>"
            "</body></html>")

    async def fake_fetch(url, *, max_bytes=65536, timeout=4.0):
        return html

    unit = _unit(CLAIM_RAIN, metrics=("120 мм",), entities=("Килякете",),
                 timeframe="июле 2019", units=("мм",))
    meta: dict = {}
    ref = await fsp.fetch_primary_evidence(
        "https://weather.example/1", fetch_text=fake_fetch, claim=unit,
        meta=meta)
    assert ref is not None and "120 мм" in ref.support
    assert ref.published_at == 1561968000
    assert meta["passage_matched"] is True
    assert meta["published_at_source"] == "page"
    assert meta["full_text_available"] is True


def test_evidence_version_is_stable_and_content_bound():
    first = fsp._evidence_version("https://e/1", 1561939200, "Текст выдержки")
    again = fsp._evidence_version("https://e/1", 1561939200, "Текст  выдержки")
    other = fsp._evidence_version("https://e/1", 1561939200, "Другой текст")
    assert first == again              # нормализация пробелов
    assert first != other
    assert re.fullmatch(r"[0-9a-f]{16}", first)


# ── FCT-403: официальность ≠ первичность ───────────────────────────────────

def test_gov_press_digest_is_not_original():
    role, basis = fsp._material_role(
        "https://minfin.gov.ru/news/1",
        "Минфин сообщает: по сообщению агентства, меры приняты",
        "primary")
    assert role in (fsp.MATERIAL_ROLE_ATTRIBUTED_REPRINT,
                    fsp.MATERIAL_ROLE_SUMMARY)
    assert role != fsp.MATERIAL_ROLE_ORIGINAL
    assert basis


def test_gov_own_statement_without_attribution_is_original():
    role, basis = fsp._material_role(
        "https://minfin.gov.ru/news/1",
        "Ведомство утвердило параметры бюджета на 2027 год.",
        "primary")
    assert role == fsp.MATERIAL_ROLE_ORIGINAL
    assert basis.startswith("host:")


def test_secondary_without_markers_stays_unknown():
    role, _basis = fsp._material_role(
        "https://news.example/1", "Событие произошло вчера.", "secondary")
    assert role == fsp.MATERIAL_ROLE_UNKNOWN


@pytest.mark.asyncio
async def test_successful_fetch_does_not_upgrade_material_role():
    html = ("<html><body><p>В Килякете в июле 2019 выпало 120 мм осадков, "
            "по сообщению агентства.</p></body></html>")

    async def fake_fetch(url, *, max_bytes=65536, timeout=4.0):
        return html

    unit = _unit(CLAIM_RAIN, metrics=("120 мм",), entities=("Килякете",),
                 timeframe="июле 2019", units=("мм",))
    ref = await fsp.fetch_primary_evidence(
        "https://news.example/1", fetch_text=fake_fetch, claim=unit)
    assert ref.source_kind == "secondary"
    role, _basis = fsp._material_role(ref.url, ref.support, ref.source_kind)
    assert role == fsp.MATERIAL_ROLE_ATTRIBUTED_REPRINT


# ── FCT-405: независимость копий ───────────────────────────────────────────

def test_copies_share_independence_group():
    text = ("В Килякете в июле 2019 выпало 120 мм осадков за сутки. "
            "Наблюдения станции подтверждены.")
    one = fsp._independence_group(text, "https://a.example/1")
    two = fsp._independence_group(text, "https://b.example/2")
    other = fsp._independence_group("Другое событие про индекс S&P 500 "
                                    "и его динамику на торгах.", "https://a.example/3")
    assert one == two
    assert one != other


@pytest.mark.asyncio
async def test_one_quality_primary_suffices_and_copies_are_not_independent():
    unit = _unit()
    block = ("S&P 500 falls 2.1% on October 30\n"
             "Инвесторы продавали акции\nhttps://a.example/1")
    copy = ("S&P 500 falls 2.1% on October 30\n"
            "Инвесторы продавали акции\nhttps://b.example/2")
    other = ("S&P 500 падает: 2,1% потери за день\n"
             "S&P 500 2.1% падение индекса\nhttps://c.example/3")
    outcome = await fsp.run_retrieval(
        _plan(unit), aggregator=Routed(default="\n\n".join((block, copy, other))),
        limits=_off_limits())
    cov = outcome.claims[0]
    groups = [e.independence_group for e in cov.evidence if e.independence_group]
    assert len(groups) == len(set(groups)) or any(
        e.independent is False for e in cov.evidence)
    assert any(e.independent for e in cov.evidence)
    assert any(e.independent is False for e in cov.evidence)
    # один качественный источник не требует второго: покрытие возможно одной
    assert cov.outcome in (fsp.CLAIM_OUTCOME_CONFIRMED,
                           fsp.CLAIM_OUTCOME_PARTIAL)


# ── FCT-406: отсеянное не получает власти ──────────────────────────────────

@pytest.mark.asyncio
async def test_rejected_candidate_absent_when_others_accepted():
    """FCT-406: отсеянный кандидат не возвращается «в другой форме».

    Рядом с принятым источником в паке лежит off-topic материал: он не
    попадает ни в EvidenceMap, ни в модельный раздел (прежний дефект —
    конкатенация сырых блоков).
    """
    unit = _unit()
    gold = ("Золото дорожает\nИнвесторы скупают золото\n"
            "https://metals.example.com/gold")
    sp = ("S&P 500 falls 2.1% on October 30\n"
          "Инвесторы продавали акции\nhttps://m.example/1")
    outcome = await fsp.run_retrieval(
        _plan(unit), aggregator=Routed(default=gold + "\n\n" + sp),
        limits=_off_limits())
    assert outcome.evidence_map is not None
    assert {r.url for r in outcome.evidence_map.refs} == {"https://m.example/1"}
    assert "metals.example.com" not in outcome.search_text
    assert "m.example/1" in outcome.search_text
    assert outcome.off_topic_sources_dropped == 1


@pytest.mark.asyncio
async def test_off_topic_candidates_do_not_reach_model_or_evidence():
    unit = _unit("Alphabet (GOOGL) потерял 658 млрд капитализации.",
                 metrics=("658 млрд",), entities=("Alphabet", "GOOGL"),
                 timeframe="", units=("billion", "usd"))
    off = ("Золото дорожает\nИнвесторы скупают золото\n"
           "https://metals.example.com/gold")
    outcome = await fsp.run_retrieval(
        _plan(unit), aggregator=Routed(default=off), limits=_off_limits())
    assert outcome.evidence_map is None
    assert outcome.refs_collected == 0
    assert outcome.search_text == ""          # отсеянное не уходит в модель
    assert "metals.example.com" not in outcome.search_text
    cov = outcome.claims[0]
    assert cov.citation_ids == ()
    assert not cov.displayable_evidence
    assert cov.status_detail == fsp.CLAIM_STATUS_NO_RELEVANT_SOURCES
    assert outcome.off_topic_sources_dropped >= 1


@pytest.mark.asyncio
async def test_low_overlap_candidate_is_typed_non_evidence_section():
    generic = _unit(CLAIM_GENERIC, metrics=(), entities=(), timeframe="",
                    units=())
    doc = ("Мировые рынки обвалились, инвесторы уходили из риска\n"
           "https://news.example/1")
    outcome = await fsp.run_retrieval(
        _plan(generic), aggregator=Routed(default=doc), limits=_off_limits())
    assert outcome.evidence_map is None
    assert outcome.search_text.startswith(fsp._CANDIDATE_CONTEXT_HEADER)
    assert "news.example/1" in outcome.search_text
    assert outcome.claims[0].evidence == ()
    # шапка прямо запрещает считать раздел доказательством
    assert "НЕ доказательства" in outcome.search_text


# ── FCT-203: приватная диагностика без текстов в событии ───────────────────

@pytest.mark.asyncio
async def test_query_journal_has_claim_intent_purpose_and_outcome():
    unit = _unit()
    outcome = await fsp.run_retrieval(
        _plan(unit, refine=True),
        aggregator=Routed(routes=(("s&p", "S&P 500 falls 2.1% on October 30\n"
                                          "https://m.example/1"),),
                          empty_needles=("уточнение",)),
        limits=_off_limits())
    cov = outcome.claims[0]
    assert cov.queries
    first = cov.queries[0]
    assert first["claim_id"] == "c1"
    assert first["intent"] == fsp.INTENT_ENTITY_CHECK
    assert first["purpose"] == fsp.QUERY_PURPOSE_BASE
    assert first["provider"] == "search" or first["provider"]
    assert first["outcome"] in ("ok", "empty", "failed")
    summary = outcome.coverage_summary()
    assert summary["stop_reason"] in (
        fsp.STOP_SUFFICIENT_EVIDENCE, fsp.STOP_NO_PROGRESS,
        fsp.STOP_PATHS_EXHAUSTED, fsp.STOP_RESOURCE_LIMIT,
        fsp.STOP_GLOBAL_DEADLINE)
    # приватное событие (то, что уходит в factcheck_claims) не несёт ни URL,
    # ни текстов запросов/чатов
    payload = json.dumps(summary, ensure_ascii=False, default=str)
    assert "http" not in payload
    assert "S&P 500 falls" not in payload
    from services.factcheck_orchestrator import _claim_telemetry_row
    row = json.dumps(_claim_telemetry_row(cov), ensure_ascii=False, default=str)
    assert "http" not in row
    assert "S&P 500 falls" not in row


# ── FCT-301: различимые коды исходов ───────────────────────────────────────

@pytest.mark.asyncio
async def test_provider_timeout_is_distinct_from_provider_error():
    outcome = await fsp.run_retrieval(
        _plan(_unit()), aggregator=Routed(fail_needles=("индекс",),
                                          fail_reason="timeout"),
        limits=_off_limits())
    cov = outcome.claims[0]
    assert cov.status_detail == fsp.CLAIM_STATUS_PROVIDER_TIMEOUT
    assert cov.outcome == fsp.CLAIM_OUTCOME_TECHNICAL
    assert outcome.stop_reason == fsp.STOP_PROVIDER_TIMEOUT
    assert outcome.provider_timeouts >= 1


@pytest.mark.asyncio
async def test_rate_limit_is_distinct_from_provider_error():
    outcome = await fsp.run_retrieval(
        _plan(_unit()), aggregator=Routed(fail_needles=("индекс",),
                                          fail_reason="rate_limit"),
        limits=_off_limits())
    cov = outcome.claims[0]
    assert cov.status_detail == fsp.CLAIM_STATUS_RATE_LIMIT
    assert outcome.stop_reason == fsp.STOP_RATE_LIMIT
    assert outcome.rate_limits >= 1


@pytest.mark.asyncio
async def test_provider_error_stays_provider_error():
    outcome = await fsp.run_retrieval(
        _plan(_unit()), aggregator=Routed(fail_needles=("индекс",)),
        limits=_off_limits())
    assert outcome.claims[0].status_detail == fsp.CLAIM_STATUS_PROVIDER_ERROR
    assert outcome.stop_reason == fsp.STOP_PROVIDERS_UNAVAILABLE


@pytest.mark.asyncio
async def test_resource_limit_is_not_claim_not_searched():
    units = tuple(_unit(CLAIM_MARKETS, claim_id=f"c{i}",
                        metrics=("2,1%",), entities=("S&P",),
                        timeframe="30 октября 2026", units=("percent",))
                  for i in range(1, 5))
    outcome = await fsp.run_retrieval(
        _plan(*units),
        aggregator=Routed(default="S&P 500 falls 2.1% on October 30\n"
                                  "https://m.example/1"),
        limits=fsp.FactcheckLimits(budgets_enabled=True, total_queries=1))
    unattempted = [c for c in outcome.claims if c.queries_count == 0]
    assert unattempted
    assert all(c.status_detail == fsp.CLAIM_STATUS_RESOURCE_LIMIT
               for c in unattempted)
    assert all(c.search_status == fsp.CLAIM_SEARCH_RESOURCE_LIMIT
               for c in unattempted)
    assert outcome.stop_reason == fsp.STOP_RESOURCE_LIMIT
    # лимит — ограничение, а не «источников не нашлось»
    assert all("лимит" in c.gap_note for c in unattempted)


@pytest.mark.asyncio
async def test_claim_with_evidence_keeps_status_under_run_limit():
    """Coverage части не выводится из run-level лимита (§5).

    Часть, которая успела получить подтверждение, сохраняет свой
    содержательный статус; лимит отражается только run-level и на
    непроверенных частях.
    """
    first = _unit()
    second = _unit("Nasdaq потерял 3,4%.", claim_id="c2", metrics=("3,4%",),
                   entities=("Nasdaq",), timeframe="", units=("percent",))
    outcome = await fsp.run_retrieval(
        _plan(first, second),
        aggregator=Routed(routes=(
            ("индекс", "S&P 500 falls 2.1% on October 30\n"
                       "https://m.example/1"),)),
        limits=fsp.FactcheckLimits(budgets_enabled=True, total_queries=1))
    assert outcome.stop_reason == fsp.STOP_RESOURCE_LIMIT
    got = outcome.claims[0]
    assert got.queries_count == 1
    assert got.status_detail == fsp.CLAIM_STATUS_VERIFIED
    assert got.outcome == fsp.CLAIM_OUTCOME_CONFIRMED
    assert got.budget_exhausted is False
    limited = outcome.claims[1]
    assert limited.status_detail == fsp.CLAIM_STATUS_RESOURCE_LIMIT


@pytest.mark.asyncio
async def test_global_deadline_is_distinct_and_honest():
    first = _unit()
    second = _unit("Nasdaq потерял 3,4%.", claim_id="c2",
                   metrics=("3,4%",), entities=("Nasdaq",),
                   timeframe="", units=("percent",))
    # Первая часть отвечает медленно и съедает wall-clock бюджет: вторая
    # часть не получает попытки и честно помечается дедлайном.
    outcome = await fsp.run_retrieval(
        _plan(first, second),
        aggregator=Routed(default="S&P 500 falls 2.1%\nhttps://m.example/1",
                          slow_needles=("индекс",), sleep=0.2),
        budget_seconds=0.01)
    assert outcome.stop_reason == fsp.STOP_GLOBAL_DEADLINE
    assert outcome.budget_exhausted is True
    second_cov = next(c for c in outcome.claims if c.claim.claim_id == "c2")
    assert second_cov.queries_count == 0
    assert second_cov.status_detail == fsp.CLAIM_STATUS_DEADLINE
    assert second_cov.search_status == fsp.CLAIM_SEARCH_DEADLINE
    assert "лимиту времени" in second_cov.gap_note


@pytest.mark.asyncio
async def test_cancelled_run_is_reported_as_cancelled():
    state = {"calls": 0}

    def is_cancelled() -> bool:
        state["calls"] += 1
        return state["calls"] > 1

    outcome = await fsp.run_retrieval(
        _plan(_unit(), _unit(claim_id="c2", text="Nasdaq потерял 3,4%.",
                             metrics=("3,4%",), entities=("Nasdaq",),
                             timeframe="", units=("percent",))),
        aggregator=Routed(default="Nasdaq drops 3.4%\nhttps://m.example/2"),
        limits=_off_limits(), is_cancelled=is_cancelled)
    assert outcome.cancelled is True
    assert outcome.stop_reason == fsp.STOP_CANCELLED
    assert any(c.status_detail == fsp.CLAIM_STATUS_CANCELLED
               for c in outcome.claims)


@pytest.mark.asyncio
async def test_unreadable_source_is_counted_and_not_marked_opened():
    async def broken_fetch(url, *, max_bytes=65536, timeout=4.0):
        raise RuntimeError("connection reset")

    unit = _unit()
    outcome = await fsp.run_retrieval(
        _plan(unit, needs_primary_fetch=True),
        aggregator=Routed(default="S&P 500 falls 2.1% on October 30\n"
                                  "https://m.example/1"),
        fetch_text=broken_fetch, limits=_off_limits())
    cov = outcome.claims[0]
    # реальная ошибка чтения учтена отдельно от «пустой/нерелевантной выдачи»
    assert outcome.source_unreadable == 1
    assert outcome.fetch_errors == 1
    assert outcome.source_extract_failed == 0
    # страница не открылась: evidence остаётся snippet_only и прямой силы
    # (strength) не имеет — прямое подтверждение требует открытого passage
    assert cov.evidence
    assert all(e.opened is False and e.snippet_only is True
               for e in cov.evidence)
    assert all(e.strength != "direct" for e in cov.evidence)


def test_source_unreadable_code_is_reachable():
    run = fsp._ClaimRun(_unit())
    run.unreadable = 1
    outcome, detail = fsp._technical_detail(run)
    assert outcome == fsp.CLAIM_OUTCOME_TECHNICAL
    assert detail == fsp.CLAIM_STATUS_SOURCE_UNREADABLE
    assert fsp.CLAIM_OUTCOME_REASON[detail] == "source_missing"


def test_level_failure_reason_rate_limit_is_distinct():
    import httpx
    request = httpx.Request("GET", "https://api.example/search")
    response = httpx.Response(429, request=request)
    exc = httpx.HTTPStatusError("429", request=request, response=response)
    assert sa.level_failure_reason(exc) == "rate_limit"
    assert sa.level_failure_reason(RuntimeError("quota exceeded")) == "rate_limit"
    assert sa.level_failure_reason(RuntimeError("boom")) == "provider_error"
    assert sa.level_failure_reason(httpx.TimeoutException("slow")) == "timeout"


def test_new_status_details_map_only_to_existing_reason_codes():
    from services import mca_events
    for detail in (fsp.CLAIM_STATUS_SOURCE_UNREADABLE,
                   fsp.CLAIM_STATUS_PROVIDER_TIMEOUT,
                   fsp.CLAIM_STATUS_RATE_LIMIT,
                   fsp.CLAIM_STATUS_RESOURCE_LIMIT):
        reason = fsp.CLAIM_OUTCOME_REASON[detail]
        assert reason in mca_events.REASON_CODES
    assert fsp.CLAIM_OUTCOME_REASON.get(fsp.CLAIM_STATUS_CANCELLED) is None


# ── FCT-302: объём по coverage; длина запроса не режет якоря ────────────────

@pytest.mark.asyncio
async def test_fetch_cap_is_shared_between_claims_not_eaten_by_first():
    units = (
        _unit(),
        _unit("Nasdaq потерял 3,4%.", claim_id="c2", metrics=("3,4%",),
              entities=("Nasdaq",), timeframe="", units=("percent",)),
        _unit("Золото выросло до 4200 долларов за унцию.", claim_id="c3",
              metrics=("4200 долларов",), entities=("Золото",),
              timeframe="", units=("usd",)),
    )
    opened: list[str] = []

    async def fake_fetch(url, *, max_bytes=65536, timeout=4.0):
        opened.append(url)
        return ("Подтверждение тезиса из открытого документа. " * 8) + url

    # Каждой части — свой качественный пак со своим URL.
    routes = (
        ("индекс", "S&P 500 falls 2.1% on October 30\nhttps://m.example/1"),
        ("nasdaq", "Nasdaq drops 3.4% on October 30\nhttps://m.example/2"),
        ("золото", "Золото выросло до 4200 долларов\nhttps://m.example/3"),
    )
    outcome = await fsp.run_retrieval(
        _plan(*units, needs_primary_fetch=True),
        aggregator=Routed(routes),
        fetch_text=fake_fetch,
        limits=fsp.FactcheckLimits(budgets_enabled=True, primary_fetches=2))
    # cap=2 при 3 частях: первая часть не забирает оба открытия себе
    assert len(opened) == 2
    assert len(set(opened)) == 2
    assert outcome.fetch_skipped_budget == 1
    assert outcome.claims[0].opened <= 1


def test_query_length_keeps_anchor_and_period_on_word_boundary():
    terms = ["оченьдлинныйтермин%d" % i for i in range(40)]
    query = fsp._make_query(terms, fsp.INTENT_NUMERIC,
                            tail="658 млрд долларов 30 октября 2026")
    assert query is not None
    assert len(query.text) <= fsp._QUERY_MAX_CHARS
    assert "658 млрд долларов 30 октября 2026" in query.text
    # граница слова: нет обрезанного токена в конце
    assert not query.text.endswith("оченьдлинныйтерм")
    assert query.text == query.text.strip()


def test_short_query_composition_is_unchanged():
    query = fsp._make_query(["альфа", "бета"], fsp.INTENT_ENTITY_CHECK,
                            tail="2026")
    assert query.text == "альфа бета 2026"


# ── FCT-303: только существующие limits.* с провенансом ───────────────────

@pytest.mark.asyncio
async def test_limits_resolve_existing_keys_with_provenance(monkeypatch):
    from services import budget_gate
    values = {
        "limits.factcheck_retrieval_seconds": (300.0, "chat"),
        "limits.factcheck_retrieval_seconds_max": (900.0, "chat"),
        "limits.factcheck_refine_calls": (12, "global"),
        "limits.factcheck_max_queries_total": (100, "global"),
        "limits.factcheck_search_text_chars": (150_000, "default"),
        "limits.factcheck_page_size": (25, "default"),
        "limits.factcheck_claim_portion": (64, "default"),
        "limits.factcheck_primary_fetches": (4, "default"),
        "limits.factcheck_excerpt_chars": (2000, "default"),
    }

    async def fake_read(key, *, chat_id=None, default=None):
        return values[key]

    async def fake_budgets(chat_id=None):
        return budget_gate.BudgetState(
            enabled=True, source="chat", chat_id=chat_id, stale=False,
            known=True)

    monkeypatch.setattr(
        "services.worker_settings.resolve_setting_with_source", fake_read)
    monkeypatch.setattr(budget_gate, "resolve_budgets", fake_budgets)
    limits = await fsp.resolve_factcheck_limits(CHAT)
    sources = dict(limits.sources)
    assert set(values) <= set(sources)
    assert sources["limits.factcheck_retrieval_seconds"] == "chat"
    assert sources["limits.factcheck_max_queries_total"] == "global"
    assert sources["flags.budgets_enabled"] == "chat"
    # новых тумблеров не появилось
    assert set(sources) == set(values) | {"flags.budgets_enabled"}
    summary = fsp.RetrievalOutcome(
        evidence_map=None, search_text="", queries_attempted=0,
        queries_used=0, refs_collected=0, fetch_errors=0,
        budget_exhausted=False,
        budgets_enabled=limits.budgets_enabled,
        budget_source=limits.budget_source,
        limit_sources=tuple(limits.sources)
    ).coverage_summary()
    assert limits.budget_source == "chat"
    assert summary["budget_source"] == "chat"
    assert summary["budgets_enabled"] is True


# ── FCT-306: нет повторов идентичного запроса ─────────────────────────────

@pytest.mark.asyncio
async def test_identical_query_text_is_not_repeated():
    unit = _unit()
    base_text = " ".join(fsp._claim_terms(unit.text, limit=6))
    plan = fsp.RetrievalPlan(
        queries=(fsp.SearchQuery(text=base_text,
                                 intent=fsp.INTENT_ENTITY_CHECK,
                                 claim_id="c1"),
                 fsp.SearchQuery(text=base_text,
                                 intent=fsp.INTENT_NUMERIC,
                                 claim_id="c1",
                                 purpose=fsp.QUERY_PURPOSE_REFINE)),
        needs_web=True, claim_text=unit.text, claims=(unit,))
    # Сниппет без заявленного числа оставляет тезис непокрытым, поэтому
    # цикл уточнений реально исполняется и мог бы повторить тот же запрос.
    agg = Routed(default="S&P 500 falls on October 30\nhttps://m.example/1")
    outcome = await fsp.run_retrieval(plan, aggregator=agg,
                                      limits=_off_limits())
    assert agg.calls.count(base_text) == 1
    assert outcome.queries_attempted == 1
    assert outcome.claims[0].status_detail != fsp.CLAIM_STATUS_VERIFIED


# ── FCT-402: basis и assertion_type passage ───────────────────────────────

def test_assertion_type_comes_from_passage_not_claim():
    quote_type, quote_basis = fsp._assertion_type(
        "Министр заявил: «меры будут приняты в этом году»")
    legal_type, _ = fsp._assertion_type(
        "Законопроект вступил в силу после подписания")
    opinion_type, _ = fsp._assertion_type("Эксперт считает, что рынок упадёт")
    stat_type, _ = fsp._assertion_type(
        "По данным опроса, 42% респондентов поддерживают меры")
    unknown_type, _ = fsp._assertion_type("Короткая фраза")
    assert quote_type == fsp.ASSERTION_ATTRIBUTED_QUOTE
    assert quote_basis.startswith("quote")
    assert legal_type == fsp.ASSERTION_LEGAL
    assert opinion_type == fsp.ASSERTION_OPINION
    assert stat_type == fsp.ASSERTION_STATISTIC
    assert unknown_type == fsp.ASSERTION_UNKNOWN


@pytest.mark.asyncio
async def test_displayable_relation_always_has_basis():
    unit = _unit()
    outcome = await fsp.run_retrieval(
        _plan(unit),
        aggregator=Routed(default="S&P 500 falls 2.1% on October 30\n"
                                  "Инвесторы продавали акции\n"
                                  "https://m.example/1"),
        limits=_off_limits())
    cov = outcome.claims[0]
    assert cov.evidence
    for item in cov.evidence:
        assert item.role in sa.DISPLAYABLE_EVIDENCE_ROLES
        assert item.basis, "displayable-роль без основания запрещена"
        assert item.assertion_type in fsp.ASSERTION_TYPES


@pytest.mark.asyncio
async def test_assertion_type_from_passage_in_pipeline():
    """Тип утверждения берётся из passage, а не из claim."""
    unit = _unit()          # claim_type == "fact"/"number"
    assert unit.claim_type != fsp.ASSERTION_LEGAL
    outcome = await fsp.run_retrieval(
        _plan(unit),
        aggregator=Routed(default="S&P 500 falls 2.1% on October 30 после "
                                  "того, как законопроект вступил в силу\n"
                                  "https://m.example/1"),
        limits=_off_limits())
    cov = outcome.claims[0]
    assert cov.evidence
    assert cov.evidence[0].assertion_type == fsp.ASSERTION_LEGAL
    assert cov.evidence[0].assertion_type != unit.claim_type


def test_background_and_unrelated_are_distinct():
    claim = _unit(CLAIM_RAIN, metrics=("120 мм",), entities=("Килякете",),
                  timeframe="июле 2019", units=("мм",))
    background = sa.claim_relevance(
        "В Килякете наблюдали осадки, станция фиксировала показатели",
        claim_text=claim.vocabulary(), timeframe=claim.timeframe,
        require_anchor=True)
    unrelated = sa.claim_relevance(
        "рецепт борща со свёклой и капустой", claim_text=claim.vocabulary(),
        timeframe=claim.timeframe, require_anchor=True)
    assert background.role == sa.EVIDENCE_ROLE_BACKGROUND
    assert unrelated.role == sa.EVIDENCE_ROLE_IRRELEVANT
    assert unrelated.topic_miss is True


# ── Публичный контракт совместимости ──────────────────────────────────────

def test_evidence_refs_from_search_keeps_public_shape():
    refs = fsp.evidence_refs_from_search(
        "Заголовок\nсниппет\nhttps://e/1\n\nВторой\nсниппет\nhttps://e/2")
    assert len(refs) == 2
    assert refs[0].url == "https://e/1"
    assert "https://" not in refs[0].support
    assert refs[0].source_kind == "secondary"


@pytest.mark.asyncio
async def test_run_retrieval_never_raises_on_broken_aggregator():
    class Broken:
        async def search_relevant(self, *a, **kw):
            raise RuntimeError("boom")

    outcome = await fsp.run_retrieval(_plan(_unit()), aggregator=Broken(),
                                      limits=_off_limits())
    assert outcome.stop_reason == fsp.STOP_PROVIDERS_UNAVAILABLE
    assert outcome.evidence_map is None
