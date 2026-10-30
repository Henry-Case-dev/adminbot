"""ASAP-FC-EVIDENCE-STYLE-02 — полнота поиска, привязка источников и живая речь.

TEST-LIFECYCLE: CONTRACT owner=ASAP-FC-EVIDENCE-STYLE-02 (§3.1–3.3, §4, §5, §6)

Двенадцать фиксированных сценариев §8 (`plans/current_task.md` 1722–1739) на
детерминированных fixtures: провайдеры/LLM/сеть/Telegram не вызываются.
Недетерминированная модель в тестах НЕ использовалась — проверяется
структурная композиция подачи на фиксированном payload, а не «живое
остроумие» (это прямо оговорено §8.10).

Проверяемые пользовательские инварианты:

1.  составная новость из 6 независимых claim → попытка поиска у КАЖДОЙ части;
2.  4 подтверждены, 2 нет → подтверждённые не превращаются в
    `insufficient_evidence`, у пробелов точные причины;
3.  статья о золоте при тезисе об Alphabet → off-topic, ссылкой тезиса не
    становится;
4.  русский пересказ с английским именем/тикером → англоязычный запрос;
5.  дата статьи ≠ дата события → устаревшая публикация не «свежее»
    подтверждение, интервал сохранён;
6.  заголовок о падении индекса не подтверждает $658 млрд → честное
    разделение;
7.  противоречивые данные → conflicting/partial с объяснением расхождения;
8.  провайдер/дедлайн упал → не «в интернете данных нет», успешные части
    сохранены, остальные помечены техническим исходом;
9.  полный пакет источников → все ссылки — реальные EvidenceRef этого прогона
    и поддерживают свой claim;
10. частичный вердикт со стилем → живая подача внутри структуры, доказательства
    не меняются, выдуманного опровержения нет;
11. стиль выключен/настроен иначе и fallback → chat/global-изоляция, активные
    настройки доходят до payload, техсбой не симулирует фактчек;
12. доставка/кеш → длинный ответ без битого HTML/ссылок, устаревшие/чужие
    ссылки не выдаются за свежие, независимый список источников не
    перегенерируется.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from config.settings import settings
from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services import factcheck_prompts as fp
from services import factcheck_renderer as fr
from services import factcheck_suitability as fsg
from services import search_aggregator as sa
from services import temporal_factcheck as tf
from services.factcheck_service import (
    CLAIM_STATUS_HUMAN,
    FactCheckService,
    claim_payload_rows,
    critique_section_default,
    merge_claim_coverage,
    resolve_critique_section,
)

CHAT_ID = -100902
TARGET_TG = 9020
TRIGGER_TG = 9021

HEADING = fp.FACTCHECK_CRITIQUE_HEADING
DIRECTIVE = fp.FACTCHECK_CRITIQUE_DIRECTIVE


# ── Fixtures: составная рыночная новость (6 независимых claim) ──────────────

CLAIM_MARKETS = (
    "30 октября 2026 года мировые рынки обвалились.",
    "Индекс S&P 500 упал на 2,1%.",
    "Nasdaq потерял 3,4%.",
    "Золото выросло до 4200 долларов за унцию.",
    "Биткоин упал ниже 90000 долларов.",
    "Alphabet (GOOGL) потерял $658 млрд капитализации.",
)

BLOCK_WORLD = ("Мировые рынки обвалились 30 октября 2026\n"
               "Инвесторы уходили из риска третий день подряд\n"
               "https://news.example.com/world-markets")
BLOCK_SP = ("S&P 500 falls 2.1% on October 30\n"
            "US stocks slid as investors fled risk assets\n"
            "https://markets.example.com/sp500")
BLOCK_NASDAQ = ("Nasdaq drops 3.4% on October 30\n"
                "Tech shares led the sell-off in New York\n"
                "https://markets.example.com/nasdaq")
BLOCK_GOLD = ("Золото подорожало до 4200 долларов за унцию\n"
              "Драгметалл обновил максимум на фоне бегства в защиту\n"
              "https://metals.example.com/gold")
BLOCK_BTC = ("Биткоин упал ниже 90000 долларов\n"
             "Криптовалюта потеряла поддержку на азиатской сессии\n"
             "https://crypto.example.com/btc")
BLOCK_ALPHABET = ("Alphabet (GOOGL) loses $658 billion in market value\n"
                  "Shares fell as investors repriced the whole complex\n"
                  "https://markets.example.com/alphabet")
BLOCK_ALPHABET_NO_NUMBER = (
    "Alphabet (GOOGL) shares fell on October 30\n"
    "Market wrap without the claimed figure\n"
    "https://markets.example.com/markets-wrap")

MARKET_ROUTES = (
    ("мировые", BLOCK_WORLD),
    ("s&p", BLOCK_SP),
    ("nasdaq", BLOCK_NASDAQ),
    ("золото", BLOCK_GOLD),
    ("биткоин", BLOCK_BTC),
    ("alphabet", BLOCK_ALPHABET),
)


# ── Фейки (без сети/БД/LLM) ─────────────────────────────────────────────────

class FakeDB:
    def __init__(self, text: str) -> None:
        self._row = {
            "text": text, "caption": None, "origin_type": None,
            "origin_sent_at": None, "sent_at": 1792200000,
            "current_revision": None, "content_hash": None,
            "origin_sender_user_id": None, "origin_chat_id": None,
            "origin_display_name": None, "author_name": None,
            "forward_source": None,
        }

    async def get_smart_message_origin_block(self, chat_id, tg):
        return dict(self._row)

    async def get_media_assets_for_message(self, chat_id, tg):
        return []

    async def get_smart_message_by_tg_id(self, chat_id, tg):
        return dict(self._row)

    async def get_smart_messages_reply_to(self, *a, **kw):
        return []


class FakeBot:
    id = 861000902

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("M", (), {"message_id": 800 + len(self.sent)})()

    async def send_chat_action(self, chat_id, action, **kw):
        return True


class RoutedAggregator:
    """Выдача по первому совпавшему needle запроса; журнал вызовов."""

    def __init__(self, routes=MARKET_ROUTES, *, default: str = "",
                 fail_needles=(), slow_needles=(), sleep: float = 0.0):
        self.routes = tuple((n.lower(), b) for n, b in routes)
        self.default = default
        self.fail_needles = tuple(n.lower() for n in fail_needles)
        self.slow_needles = tuple(n.lower() for n in slow_needles)
        self.sleep = sleep
        self.calls: list[str] = []

    async def search(self, query, max_symbols):
        import asyncio
        self.calls.append(query)
        low = str(query).lower()
        if any(needle in low for needle in self.fail_needles):
            raise sa.AllSearchEnginesFailedException(
                "engines down", reason="provider_error")
        if self.sleep and any(needle in low for needle in self.slow_needles):
            await asyncio.sleep(self.sleep)
            raise sa.AllSearchEnginesFailedException("timeout", reason="timeout")
        for needle, block in self.routes:
            if needle in low:
                return block
        return self.default


_NO_VERDICT = object()


class StepLLM:
    """LLM-фейк: JSON на машинных стадиях, текст — на вербализации."""

    def __init__(self, *, verdict=None, text="Готово.", validator=None):
        if verdict is _NO_VERDICT:
            self.verdict = None
        elif verdict is None:
            self.verdict = {"factual_verdict": "insufficient_evidence",
                            "temporal_status": "unknown"}
        else:
            self.verdict = verdict
        self.validator = validator or {"agree": True}
        self.text = text
        self.calls: list[dict] = []

    async def generate(self, messages, **kw):
        step = kw.get("step")
        self.calls.append({"step": step, "messages": messages})
        if step == "temporal_verdict":
            if self.verdict is None:
                return "не json"
            return json.dumps(self.verdict, ensure_ascii=False)
        if step == "temporal_validator":
            return json.dumps(self.validator, ensure_ascii=False)
        return self.text

    def system_of(self, step: str) -> str:
        for call in self.calls:
            if call["step"] == step:
                return call["messages"][0]["content"]
        raise AssertionError(f"нет вызова стадии {step}")

    def user_of(self, step: str) -> str:
        for call in self.calls:
            if call["step"] == step:
                return call["messages"][1]["content"]
        raise AssertionError(f"нет вызова стадии {step}")

    def systems(self) -> str:
        return "\n".join(str(c["messages"][0]["content"]) for c in self.calls)


@pytest.fixture
def planner_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


@pytest.fixture(autouse=True)
def _offline_network():
    """Полный офлайн: дата-фетч выдержек и провайдеры не ходят в сеть."""
    old = getattr(settings, "TEMPORAL_EVIDENCE_DATE_FETCH_ENABLED", True)
    object.__setattr__(settings, "TEMPORAL_EVIDENCE_DATE_FETCH_ENABLED", False)
    yield
    object.__setattr__(settings, "TEMPORAL_EVIDENCE_DATE_FETCH_ENABLED", old)


def _decision(*units: str):
    items = tuple(fsg.ClaimItem(text=u, claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
                                verifiable=True, source="literal")
                  for u in units)
    return fsg.SuitabilityDecision(
        decision=fsg.DECISION_CHECKABLE,
        claim_type=fsg.CHECKABLE_FACTUAL_CLAIM, claim_items=items,
        scope="web", reason_code="obvious_checkable_predicate",
        confidence=0.8, target_ref={})


def _plan(*units: str):
    claim = " ".join(units)
    return fsp.build_retrieval_plan(_decision(*units), claim_text=claim)


async def _envelope(text: str):
    env, _reject = await tf.build_envelope(
        FakeDB(text),
        tf.InputRef(kind="reply", chat_id=CHAT_ID,
                    target_tg_message_id=TARGET_TG,
                    trigger_tg_message_id=TRIGGER_TG))
    return env


async def _run_service(outcome, *, units=CLAIM_MARKETS, llm=None):
    llm = llm or StepLLM()
    env = await _envelope(" ".join(units))
    service = FactCheckService(aggregator=RoutedAggregator(), llm=llm)
    run = await service.check_claim_envelope(env, retrieval=outcome)
    return run, llm


async def _offline_fetch(url, max_bytes=None, timeout=None):
    """Первоисточник недоступен офлайн: контур честно деградирует."""
    raise RuntimeError("offline test")


async def _retrieve(plan, aggregator, *, fetch=_offline_fetch, **kw):
    return await fsp.run_retrieval(plan, aggregator=aggregator,
                                   fetch_text=fetch, **kw)


def _checked(run) -> orch.CheckedVerdict:
    """Тот же egress-переход, что делает оркестратор."""
    refs = tuple(
        orch.EvidenceRef(evidence_id=str(r.get("evidence_id") or ""),
                         url=r.get("url"),
                         support=str(r.get("support") or ""),
                         source_kind=str(r.get("source_kind") or "secondary"),
                         published_at=r.get("published_at"),
                         claims=((str(r.get("claim_part")),)
                                 if r.get("claim_part") else ()))
        for r in (run.evidence_rows or ()))
    return orch.CheckedVerdict(
        verdict_text=run.verdict_text or "Вердикт.",
        route="envelope_temporal",
        factual_verdict=run.verdict.factual_verdict,
        temporal_status=run.verdict.temporal_status,
        evaluated_period=run.verdict.evaluated_period,
        uncertainty=run.verdict.uncertainty,
        evidence=orch.EvidenceMap(refs=refs,
                                 allowlist=tuple(r.evidence_id
                                                 for r in refs)),
        reason_code=run.verdict.reason,
        fallback_used=run.fallback_used,
        evidence_refs=tuple(run.verdict.evidence_refs or ()),
        parts=tuple(run.verdict.parts or ()))


def _publish(verdict: orch.CheckedVerdict, *, allow_critique: bool = True,
             notice: str = "") -> str:
    presentation = orch.build_presentation(verdict, notice=notice)
    return fr.render_factcheck(presentation, verdict,
                               allow_critique=allow_critique).text


def _hrefs(markup: str) -> list[str]:
    import re
    return re.findall(r'href="([^"]+)"', markup)


def asyncio_run(coro):
    """Мини-исполнитель корутины в sync-тесте (без pytest-asyncio)."""
    import asyncio
    return asyncio.run(coro)


# ═══ 1. Составная новость: попытка у КАЖДОЙ части ═══════════════════════════

@pytest.mark.asyncio
async def test_sc1_every_claim_gets_a_search_attempt(planner_on):
    plan = _plan(*CLAIM_MARKETS)
    assert plan is not None and len(plan.claims) == 6
    # §3.2: «≤3 запроса на всю новость» больше не оставляет части без поиска
    assert len(plan.queries) >= 6
    assert len({q.claim_id for q in plan.queries}) == 6

    outcome = await _retrieve(plan, RoutedAggregator())
    assert len(outcome.claims) == 6
    for cov in outcome.claims:
        assert cov.queries_count >= 1
        assert cov.search_status in (fsp.CLAIM_SEARCH_SEARCHED,
                                     fsp.CLAIM_SEARCH_SOURCE_READ)
    summary = outcome.coverage_summary()
    assert summary["total_claims"] == 6
    assert summary["claims_searched"] == 6
    assert summary["claims_with_direct_evidence"] == 6
    # доказательства разложены по СВОИМ частям (не все в одну)
    urls_by_claim = {cov.claim.claim_id: {e.url for e in cov.evidence}
                     for cov in outcome.claims}
    assert all(urls_by_claim.values())
    assert len({u for urls in urls_by_claim.values() for u in urls}) >= 6
    for ref in outcome.evidence_map.refs:
        assert ref.url and ref.claims, "у ссылки нет claim-привязки"
    # §3.2: по хорошо подтверждённой части поиск не повторяется
    assert outcome.coverage_summary()["refine_calls"] == 0


# ═══ 1b. Adaptive coverage-loop: уточнение только непокрытой части ══════════

@pytest.mark.asyncio
async def test_adaptive_refinement_only_for_uncovered_claim(planner_on):
    units = ("Индекс упал на 2,1%.", "Nasdaq потерял 3,4%.")
    plan = _plan(*units)
    base_queries = {q.text for q in plan.queries
                    if q.purpose == fsp.QUERY_PURPOSE_BASE}
    assert len(base_queries) == 2

    block_index = ("Индекс упал на 2,1% в среду\n"
                   "Торги закрылись снижением\n"
                   "https://markets.example.com/index")

    class FirstEmpty:
        """Базовая формулировка пустая, уточнение (метрика) — результативно."""

        def __init__(self):
            self.calls: list[str] = []

        async def search(self, query, max_symbols):
            self.calls.append(query)
            if query in base_queries:
                return ""
            return block_index

    agg = FirstEmpty()
    outcome = await _retrieve(plan, agg)
    assert outcome.coverage_summary()["refine_calls"] >= 1
    assert len(agg.calls) > len(base_queries)          # уточняющий вызов был
    assert len(agg.calls) == len(set(agg.calls))       # один и тот же не повтор
    by_id = {cov.claim.claim_id: cov for cov in outcome.claims}
    # уточнение спасло часть, по которой базовая выдача была пустой
    assert by_id["c1"].evidence
    assert by_id["c1"].status_detail == fsp.CLAIM_STATUS_VERIFIED
    # часть без уточнения остаётся честно неподтверждённой, а не «данных нет»
    assert by_id["c2"].status_detail == fsp.CLAIM_STATUS_NO_RELEVANT_SOURCES


# ═══ 2. 4 подтверждены, 2 нет → не общий insufficient ═══════════════════════

@pytest.mark.asyncio
async def test_sc2_four_confirmed_two_concrete_gaps(planner_on):
    units = CLAIM_MARKETS
    plan = _plan(*units)
    routes = tuple(r for r in MARKET_ROUTES if r[0] != "мировые")
    routes = tuple((n, (BLOCK_ALPHABET_NO_NUMBER if n == "alphabet" else b))
                   for n, b in routes)
    agg = RoutedAggregator(routes, fail_needles=("мировые",))
    outcome = await _retrieve(plan, agg)

    by_id = {cov.claim.claim_id: cov for cov in outcome.claims}
    # c1 — технический сбой провайдера, c6 — числа нет в источнике
    assert by_id["c1"].search_status == fsp.CLAIM_SEARCH_PROVIDER_FAILED
    assert by_id["c6"].status_detail == fsp.CLAIM_STATUS_EXACT_NUMBER

    verdict_payload = {
        "factual_verdict": "insufficient_evidence",
        "temporal_status": "current",
        "parts": [
            {"part_id": f"p{i}", "text": units[i],
             "factual_verdict": "supported",
             "evidence_refs": []}
            for i in (2, 3, 4)],        # Nasdaq / золото / биткоин
    }
    llm = StepLLM(verdict=verdict_payload,
                  text="Четыре пункта сходится. По Alphabet суммы нет.")
    run, _llm = await _run_service(outcome, units=units, llm=llm)

    parts = {str(p.get("claim_id")): p for p in (run.verdict.parts or ())
             if p.get("claim_id")}
    supported = [p for p in parts.values()
                 if p.get("factual_verdict") == "supported"]
    assert len(supported) == 4, parts
    # подтверждённые части не затёрты двумя проблемными
    assert run.verdict.factual_verdict == "mixed"
    assert parts["c1"]["status_detail"] == fsp.CLAIM_STATUS_PROVIDER_ERROR
    assert parts["c6"]["status_detail"] == fsp.CLAIM_STATUS_EXACT_NUMBER
    assert "технический сбой" in parts["c1"]["gap_note"]
    assert "сумма/число" in parts["c6"]["gap_note"]

    markup = _publish(_checked(run))
    visible = fr.visible_text(markup)
    assert "сумма/число" in visible            # конкретная причина в публичном
    assert visible.lower().count("данных недостаточно") <= 2


# ═══ 3. Золото при тезисе об Alphabet — off-topic ═══════════════════════════

@pytest.mark.asyncio
async def test_sc3_off_topic_source_not_bound_to_claim(planner_on):
    unit = "Alphabet (GOOGL) потерял $658 млрд капитализации."
    plan = _plan(unit)
    agg = RoutedAggregator((), default=BLOCK_GOLD)
    outcome = await _retrieve(plan, agg)
    assert outcome.evidence_map is None
    assert outcome.off_topic_sources_dropped >= 1
    cov = outcome.claims[0]
    assert cov.status_detail in (fsp.CLAIM_STATUS_NO_RELEVANT_SOURCES,
                                 fsp.CLAIM_STATUS_EXACT_NUMBER)
    assert cov.gap_note and "не нашлось" in cov.gap_note
    verdict = orch.CheckedVerdict(
        verdict_text="Про капитализацию подтверждений нет.",
        route="envelope_temporal",
        factual_verdict="insufficient_evidence")
    markup = _publish(verdict)
    assert "metals.example.com" not in markup     # off-topic не «Источник»
    assert not _hrefs(markup)


# ═══ 4. Русский пересказ с английским именем/тикером ═══════════════════════

def test_sc4_foreign_name_produces_english_query(planner_on):
    unit = ("В пересказе пишут, что акции Alphabet (GOOGL) обвалились "
            "после отчёта.")
    plan = _plan(unit)
    claim = plan.claims[0]
    assert "Alphabet" in claim.foreign_terms
    assert "GOOGL" in claim.foreign_terms
    latin_queries = [q.text for q in plan.queries
                     if "alphabet" in q.text.lower()
                     and "googl" in q.text.lower()]
    assert latin_queries, plan.queries
    query = latin_queries[0]
    latin_chars = sum(1 for ch in query if ch.isascii() and ch.isalpha())
    assert latin_chars >= len(query) / 2     # англоязычный, не русский фрагмент
    assert query.lower() != unit.lower()[:200]


# ═══ 5. Дата статьи ≠ дата события ═════════════════════════════════════════

@pytest.mark.asyncio
async def test_sc5_stale_article_not_fresh_confirmation(planner_on):
    unit = "30 октября 2026 года акции Alphabet (GOOGL) упали на 5%."
    plan = _plan(unit)
    claim = plan.claims[0]
    assert "30" in claim.timeframe and "октября" in claim.timeframe
    assert claim.event_at is not None
    assert any("30" in q.text for q in plan.queries)   # интервал в запросе

    old_html = ('<html><head><meta property="article:published_time" '
                'content="2020-01-05T08:00:00+00:00"></head><body><p>'
                'Alphabet (GOOGL) shares fell on October 30, 2020 after the '
                'report: the market value dropped sharply that day.</p>'
                '</body></html>')

    async def fake_fetch(url, max_bytes=None, timeout=None):
        return old_html

    snippet = ("Alphabet (GOOGL) shares fell on October 30\n"
               "Market recap of the sell-off\n"
               "https://markets.example.com/alphabet-old")
    outcome = await fsp.run_retrieval(plan,
                                      aggregator=RoutedAggregator(
                                          (("alphabet", snippet),)),
                                      fetch_text=fake_fetch)
    cov = outcome.claims[0]
    assert outcome.stale_sources_dropped >= 1
    assert cov.status_detail != fsp.CLAIM_STATUS_VERIFIED
    assert "старше" in cov.gap_note
    markup = _publish(_verdict_only(outcome))
    assert "alphabet-old" not in " ".join(_hrefs(markup))


def _verdict_only(outcome) -> orch.CheckedVerdict:
    """Минимальный вердикт из покрытия (без LLM) для проверок рендера."""
    return orch.CheckedVerdict(
        verdict_text="Источник оказался старше заявленного события.",
        route="envelope_temporal", factual_verdict="insufficient_evidence",
        parts=tuple({
            "part_id": c.claim.claim_id,
            "text": c.claim.text,
            "factual_verdict": fsp.CLAIM_OUTCOME_TO_VERDICT.get(
                c.outcome, "insufficient_evidence"),
            "evidence_refs": list(c.citation_ids),
            "gap_note": c.gap_note,
            "claim_id": c.claim.claim_id,
            "status_detail": c.status_detail,
            "search_status": c.search_status,
        } for c in outcome.claims),
        evidence=outcome.evidence_map or orch.EvidenceMap())


# ═══ 6. Заголовок о падении индекса ≠ $658 млрд ════════════════════════════

@pytest.mark.asyncio
async def test_sc6_index_drop_headline_does_not_confirm_market_cap(planner_on):
    # Заголовок о падении индекса не содержит заявленной суммы: событие он
    # подтверждает, но $658 млрд — нет (честное разделение утверждений).
    assert "658" not in BLOCK_SP
    units = ("Индекс S&P 500 упал 30 октября 2026 года.",
             "Alphabet (GOOGL) потеряла $658 млрд капитализации.")
    plan = _plan(*units)
    outcome = await _retrieve(
        plan, RoutedAggregator((("s&p", BLOCK_SP),
                                ("alphabet", BLOCK_ALPHABET_NO_NUMBER))))
    by_id = {cov.claim.claim_id: cov for cov in outcome.claims}
    assert by_id["c1"].status_detail == fsp.CLAIM_STATUS_VERIFIED
    assert by_id["c2"].status_detail == fsp.CLAIM_STATUS_EXACT_NUMBER
    assert by_id["c2"].outcome == fsp.CLAIM_OUTCOME_INSUFFICIENT
    # сумма не приписана заголовку об индексе: привязка к своему claim
    assert {e.url for e in by_id["c1"].evidence} == {
        "https://markets.example.com/sp500"}
    assert {e.url for e in by_id["c2"].evidence} == {
        "https://markets.example.com/markets-wrap"}

    verdict = _verdict_only(outcome)
    visible = fr.visible_text(_publish(verdict))
    assert "сумма/число" in visible
    assert "Индекс" in visible and "капитализации" in visible

    # Даже если модель назовёт сумму подтверждённой, источник с ролью
    # «событие есть, числа нет» удержать положительный вердикт не может.
    llm = StepLLM(verdict={
        "factual_verdict": "supported",
        "temporal_status": "current",
        "parts": [{"part_id": "p2", "text": units[1],
                   "factual_verdict": "supported",
                   "evidence_refs": []}]})
    run, _llm = await _run_service(outcome, units=units, llm=llm)
    part = next(p for p in run.verdict.parts if p.get("claim_id") == "c2")
    assert part["factual_verdict"] == "insufficient_evidence"
    assert "сумма/число" in part["gap_note"]
    assert run.verdict.factual_verdict != "supported"


# ═══ 7. Противоречивые данные ═════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sc7_conflicting_sources_explained(planner_on):
    unit = "Nasdaq упал 3,4% 30 октября 2026 года."
    plan = _plan(unit)
    blocks = ("Nasdaq fell 3.4% on October 30\n"
              "Tech sell-off deepened in New York\n"
              "https://markets.example.com/nasdaq-a\n\n"
              "Nasdaq fell 2.8% on October 30\n"
              "Later revisions showed a smaller decline\n"
              "https://markets.example.com/nasdaq-b")
    outcome = await _retrieve(
        plan, RoutedAggregator((("nasdaq", blocks),)))
    cov = outcome.claims[0]
    assert cov.outcome == fsp.CLAIM_OUTCOME_CONFLICTING
    assert cov.status_detail == fsp.CLAIM_STATUS_CONFLICTING
    assert "расходятся" in cov.gap_note
    # выбран удобный вариант не молча: обе оценки остаются в покрытии
    assert len(cov.evidence) >= 2
    verdict = _verdict_only(outcome)
    verdict = dataclasses.replace(verdict, factual_verdict="mixed")
    visible = fr.visible_text(_publish(verdict))
    assert "расходятся" in visible


# ═══ 8. Провайдер/дедлайн: не «данных нет» ═════════════════════════════════

@pytest.mark.asyncio
async def test_sc8_provider_and_deadline_are_technical(planner_on):
    units = ("Индекс S&P 500 упал 30 октября 2026 года.",
             "Nasdaq вырос на 2% в тот же день.",
             "Золото подорожало до 4200 долларов за унцию.")
    plan = _plan(*units)
    agg = RoutedAggregator((("s&p", BLOCK_SP),),
                           fail_needles=("nasdaq",),
                           slow_needles=("золото",), sleep=0.2)
    outcome = await _retrieve(plan, agg, budget_seconds=0.05)
    by_id = {cov.claim.claim_id: cov for cov in outcome.claims}
    assert by_id["c1"].status_detail == fsp.CLAIM_STATUS_VERIFIED
    assert by_id["c2"].status_detail == fsp.CLAIM_STATUS_PROVIDER_ERROR
    assert by_id["c3"].status_detail in (fsp.CLAIM_STATUS_DEADLINE,
                                         fsp.CLAIM_STATUS_PROVIDER_ERROR)
    deadline_claims = [cov for cov in outcome.claims
                       if cov.status_detail == fsp.CLAIM_STATUS_DEADLINE]
    assert outcome.coverage_summary()["claims_unchecked_due_to_deadline"] == \
        len(deadline_claims)

    verdict = _verdict_only(outcome)
    verdict = dataclasses.replace(verdict, factual_verdict="mixed")
    markup = _publish(verdict)
    visible = fr.visible_text(markup)
    # Reviewer F3: технические части называются техническим исходом, а не
    # «данных недостаточно» (сбой поиска ≠ отсутствие фактов).
    assert "поиск не завершён: технический сбой" in visible or \
        "поиск не завершён: лимит времени" in visible
    assert "данных недостаточно" not in visible
    assert "в интернете данных нет" not in visible.lower()
    # успешная часть сохранилась вместе со своей ссылкой
    assert any("markets.example.com/sp500" in url for url in _hrefs(markup))


# ═══ 9. Полный пакет источников ════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sc9_displayed_links_are_real_refs_of_this_run(planner_on):
    plan = _plan(*CLAIM_MARKETS)
    outcome = await _retrieve(plan, RoutedAggregator())
    run, _llm = await _run_service(outcome)
    checked = _checked(run)
    markup = _publish(checked)
    hrefs = _hrefs(markup)
    known = {ref.url for ref in checked.evidence.refs if ref.url}
    assert hrefs
    assert set(hrefs) <= known, "в разметке ссылка не из EvidenceMap прогона"
    bound = {p.get("claim_id"): set(p.get("evidence_refs") or ())
             for p in checked.parts if p.get("claim_id")}
    refs_by_id = {r.evidence_id: r for r in checked.evidence.refs}
    for claim_id, ids in bound.items():
        for evidence_id in ids:
            ref = refs_by_id[evidence_id]
            assert claim_id in (ref.claims or ()), (
                "ссылка показана рядом с чужим тезисом")
    # каждая показанная ссылка действительно поддержана своим claim-ом:
    # off-topic/background в текущем прогоне не выводятся вовсе
    assert checked.evidence.refs
    for ref in checked.evidence.refs:
        assert ref.claims, "ссылка без claim-привязки не должна попадать в ответ"
    assert outcome.off_topic_sources_dropped == 0


# ═══ 10. Частичный вердикт, стиль включён ══════════════════════════════════

@pytest.mark.asyncio
async def test_sc10_partial_verdict_live_style_within_structure(
        planner_on, monkeypatch):
    assert critique_section_default() is True
    units = ("Индекс S&P 500 упал 30 октября 2026 года.",
             "Alphabet потеряла $658 млрд капитализации.")
    plan = _plan(*units)
    outcome = await _retrieve(
        plan, RoutedAggregator((("s&p", BLOCK_SP),
                                ("alphabet", BLOCK_ALPHABET_NO_NUMBER))))
    writer = (
        "Коротко: индекс действительно просел, а вот сумма потерь — фантазия.\n\n"
        "S&P 500 в тот день упал, это подтверждается источником.\n\n"
        + HEADING + ": сумму в 658 миллиардов автор просто придумал, "
        "ни один источник её не даёт.")
    llm = StepLLM(verdict={
        "factual_verdict": "insufficient_evidence",
        "temporal_status": "current",
        "parts": [{"part_id": "p1", "text": units[0],
                   "factual_verdict": "supported", "evidence_refs": []}]},
        text=writer)
    run, llm = await _run_service(outcome, units=units, llm=llm)

    # активная директива и стиль-слой доходят до публичного Writer'а
    system = llm.system_of("temporal_verbalize")
    assert DIRECTIVE in system and HEADING in system
    payload = llm.user_of("temporal_verbalize")
    assert "claims" in payload and "658" in payload

    verdict = _checked(run)
    assert verdict.factual_verdict == "mixed"     # подтверждено + пробел
    markup = _publish(verdict)
    visible = fr.visible_text(markup)
    # семантический порядок: вывод → разбор → критический разнос → источники
    assert visible.index("Коротко") < visible.index(HEADING)
    assert visible.index(HEADING) < visible.index("По утверждениям:")
    assert "сумма/число" in visible              # конкретный пробел, не шаблон
    assert "<b>" in markup                       # структура сохранена
    # доказательства не изменены подачей
    assert set(_hrefs(markup)) <= {r.url for r in verdict.evidence.refs}
    # подтверждённый тезис не превращён в выдуманное опровержение
    supported = [p for p in verdict.parts
                 if p.get("factual_verdict") == "supported"]
    assert len(supported) == 1


# ═══ 11. Стиль выключен/иная настройка + fallback ══════════════════════════

@pytest.mark.asyncio
async def test_sc11_style_isolation_and_fallback(planner_on, monkeypatch):
    from services import chat_params

    async def fake_param(chat_id, key, default):
        if int(chat_id) == -1001:
            return False, "chat"
        if int(chat_id) == -1002:
            return True, "chat"
        return default, "factory"

    monkeypatch.setattr(chat_params, "get_chat_param_sourced", fake_param)
    assert (await resolve_critique_section(-1001))[0] is False
    assert (await resolve_critique_section(-1002))[0] is True
    # отсутствие чат-настройки → заводской дефолт (глобальная изоляция)
    assert (await resolve_critique_section(-1003))[0] is critique_section_default()

    verdict = orch.CheckedVerdict(
        verdict_text="Разбор.\n\n" + HEADING + ": автор наврал с суммой.",
        route="envelope_temporal", factual_verdict="mixed",
        parts=({"part_id": "p1", "text": "тезис",
                "factual_verdict": "insufficient_evidence",
                "evidence_refs": []},))
    stripped = await orch._apply_critique_section_setting(-1001, verdict)
    assert HEADING not in stripped.verdict_text
    assert "Разбор." in stripped.verdict_text
    kept = await orch._apply_critique_section_setting(-1002, verdict)
    assert HEADING in kept.verdict_text

    # технический сбой/fallback: разгрома нет, фактчек не симулируется
    assert fp.critique_policy_for_verdict(
        factual_verdict="unsupported-unknown", fallback_used=True) == \
        fp.CRITIQUE_POLICY_FORBIDDEN
    assert fp.critique_policy_for_verdict(
        factual_verdict="insufficient_evidence",
        reason_code="deadline_exceeded") == fp.CRITIQUE_POLICY_FORBIDDEN

    units = ("Индекс S&P 500 упал 30 октября 2026 года.",)
    plan = _plan(*units)
    outcome = await _retrieve(
        plan, RoutedAggregator((("s&p", BLOCK_SP),)))
    llm = StepLLM(verdict=_NO_VERDICT, text="")
    run, llm = await _run_service(outcome, units=units, llm=llm)
    assert run.fallback_used is True
    assert HEADING not in llm.systems()          # раздел не инструктируется
    # fallback не симулирует проверенный фактчек: нет выдуманного подтверждения
    fallback_text = (run.verdict_text or "").lower()
    assert "подтверждается" not in fallback_text
    assert "источник подтверждает" not in fallback_text


# ═══ 12. Доставка и кеш ════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sc12_delivery_split_and_no_stale_links(planner_on):
    plan = _plan(*CLAIM_MARKETS)
    outcome = await _retrieve(plan, RoutedAggregator())
    run, _llm = await _run_service(outcome)
    checked = _checked(run)
    first = _publish(checked)
    second = _publish(checked)
    assert first == second                       # независимый список не генерится
    # чужая/устаревшая ссылка не попадает в публикацию: presentation.links
    # дополняется ссылкой вне EvidenceMap этого прогона
    presentation = orch.build_presentation(checked)
    presentation = dataclasses.replace(
        presentation,
        links=presentation.links + ("https://old.example.org/stale",))
    markup = fr.render_factcheck(presentation, checked).text
    assert "old.example.org" not in markup

    chunks = fr.split_entity_safe(first, limit=300)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 300
        for tag in ("b", "i", "a"):
            assert chunk.count(f"<{tag}") == chunk.count(f"</{tag}>")
    assert sum(chunk.count('href="') for chunk in chunks) == first.count('href="')
    # кеш готовых вердиктов удалён: повторная проверка — новый прогон,
    # «кеш-хит» не маскирует устаревший результат под свежий
    assert checked.cache_hit is False
    assert "cache" not in fr.visible_text(first).lower()


# ═══ §6: телеметрия покрытия и подачи ═════════════════════════════════════

@pytest.mark.asyncio
async def test_telemetry_claim_trace_and_turn_summary(planner_on, caplog):
    import logging
    plan = _plan(*CLAIM_MARKETS)
    outcome = await _retrieve(plan, RoutedAggregator())
    run, _llm = await _run_service(outcome)
    checked = _checked(run)
    with caplog.at_level(logging.INFO,
                         logger="services.factcheck_orchestrator"):
        fields = await orch._emit_claim_coverage(
            chat_id=CHAT_ID, outcome=outcome, verdict=checked,
            verbalizer_path="envelope_temporal", renderer_path="telegram_html",
            critical_section_enabled=True, fallback_reason="")
    for key in ("total_claims", "claims_searched", "claims_with_direct_evidence",
                "claims_partial", "claims_unchecked_due_to_deadline",
                "off_topic_sources_dropped", "verbalizer_path", "renderer_path",
                "critical_section_enabled", "fallback_reason", "core_revision",
                "expression_revision", "style_revision"):
        assert key in fields, key
    assert fields["total_claims"] == 6
    lines = [r.getMessage() for r in caplog.records
             if "[factcheck_claims]" in r.getMessage()]
    assert lines and "chat=-100902" in lines[-1]
    # в трассе нет сырых текстов тезисов и URL
    assert "S&P" not in lines[-1] and "http" not in lines[-1]
    payload_rows = claim_payload_rows(outcome.claims)
    assert payload_rows and all("status" in row for row in payload_rows)
    assert CLAIM_STATUS_HUMAN["provider_error"]


# ═══ Reviewer fixes F1–F5 (ASAP-FC-EVIDENCE-STYLE-02, round 2) ═════════════

#: Блок «событие есть, суммы нет»: подтверждает тему, но не масштаб.
BLOCK_EVENT_ONLY = ("Alphabet (GOOGL) shares fell on October 30\n"
                    "Market wrap without the claimed figure\n"
                    "https://markets.example.com/wrap")
#: Блок с тем же числом, но ДРУГИМ масштабом ($658 million вместо млрд).
BLOCK_WRONG_SCALE = ("Alphabet (GOOGL) loses $658 million in market value\n"
                     "Shares fell as investors repriced the complex\n"
                     "https://markets.example.com/alphabet-mn")


def test_review_f1a_units_must_match_scale(planner_on):
    """RED: «$658 млрд» → ('658 м',) и источник «$658 million» подтверждал.

    PASS: длинные единицы разбираются целиком, масштаб/валюта обязаны
    совпадать, иначе это расхождение, а не подтверждение.
    """
    unit = "Alphabet (GOOGL) потерял $658 млрд капитализации."
    plan = _plan(unit)
    claim = plan.claims[0]
    assert "$658 млрд" in claim.metrics
    assert {"$", "млрд"} <= set(claim.units)

    rel = sa.claim_relevance(BLOCK_WRONG_SCALE, claim_text=claim.vocabulary(),
                             anchor_terms=claim.foreign_terms,
                             metrics=claim.metrics, entities=claim.entities,
                             claim_type=claim.claim_type)
    assert rel.role != sa.EVIDENCE_ROLE_SUPPORTS
    assert rel.strong is False
    assert rel.number_mismatch is True

    # полный прогон: «confirmed verified» и подтверждение $658 млрд невозможны
    outcome = asyncio_run(_retrieve(plan, RoutedAggregator(
        (("alphabet", BLOCK_WRONG_SCALE),))))
    cov = outcome.claims[0]
    assert cov.outcome != fsp.CLAIM_OUTCOME_CONFIRMED
    assert cov.status_detail != fsp.CLAIM_STATUS_VERIFIED
    assert "расходятся" in cov.gap_note
    run, _llm = asyncio_run(_run_service(outcome, units=(unit,)))
    assert run.verdict.factual_verdict != "supported"
    visible = fr.visible_text(_publish(_checked(run)))
    assert "Подтверждается\n" not in visible
    assert "расходятся" in visible


def test_review_f1b_server_does_not_upgrade_insufficient(planner_on):
    """RED: серверная часть поднимала вывод «недостаточно данных» до mixed.

    PASS: если модель сказала insufficient_evidence, синтезированная часть не
    становится подтверждением.
    """
    unit = "Индекс S&P 500 упал 30 октября 2026 года."
    plan = _plan(unit)
    outcome = asyncio_run(_retrieve(plan, RoutedAggregator(
        (("s&p", BLOCK_SP),))))
    assert outcome.claims[0].outcome == fsp.CLAIM_OUTCOME_CONFIRMED
    llm = StepLLM(verdict={"factual_verdict": "insufficient_evidence",
                           "temporal_status": "current"})
    run, _llm = asyncio_run(_run_service(outcome, units=(unit,), llm=llm))
    assert run.verdict.factual_verdict == "insufficient_evidence"
    part = next(p for p in run.verdict.parts if p.get("claim_id") == "c1")
    assert part["factual_verdict"] == "insufficient_evidence"


def test_review_f1c_cause_requires_causal_link(planner_on):
    """RED: «из-за …» подтверждалось обычной статьёй о падении.

    PASS: причинный тезис подтверждается только источником с причинной
    связкой, иначе — qualifies (тема есть, причина не подтверждена).
    """
    unit = "Индекс упал из-за отчёта Alphabet."
    plan = _plan(unit)
    claim = plan.claims[0]
    assert claim.claim_type == fsp.CLAIM_TYPE_CAUSE
    no_cause = "Индекс упал на 2,1% в среду\nТорги закрылись снижением\n"
    with_cause = ("Индекс упал на 2,1% из-за слабого отчёта Alphabet\n"
                  "Торги закрылись снижением\n")
    rel_plain = sa.claim_relevance(no_cause, claim_text=claim.vocabulary(),
                                   anchor_terms=claim.foreign_terms,
                                   metrics=claim.metrics, entities=claim.entities,
                                   claim_type=claim.claim_type)
    rel_causal = sa.claim_relevance(with_cause, claim_text=claim.vocabulary(),
                                    anchor_terms=claim.foreign_terms,
                                    metrics=claim.metrics, entities=claim.entities,
                                    claim_type=claim.claim_type)
    assert rel_plain.role != sa.EVIDENCE_ROLE_SUPPORTS
    assert rel_causal.role == sa.EVIDENCE_ROLE_SUPPORTS


def test_review_f1d_direction_morphology(planner_on):
    """RED: закрытый список пар не ловил «вырос» против «подешевел/снизился».

    PASS: направление определяется морфологией, источник «наоборот» — не
    подтверждение.
    """
    unit = "Золото выросло до 4200 долларов за унцию."
    plan = _plan(unit)
    claim = plan.claims[0]
    for body in ("Золото подешевело до 4000 долларов за унцию\nРынок металлов\n",
                 "Золото снизилось до 4000 долларов за унцию\nРынок металлов\n"):
        rel = sa.claim_relevance(body, claim_text=claim.vocabulary(),
                                 anchor_terms=claim.foreign_terms,
                                 metrics=claim.metrics, entities=claim.entities,
                                 claim_type=claim.claim_type)
        assert rel.opposite is True, body
        assert rel.role != sa.EVIDENCE_ROLE_SUPPORTS


@pytest.mark.asyncio
async def test_review_f2_diverging_estimates_become_conflicting(planner_on):
    """RED: 2,8 % и 3,1 % против заявленных 3,4 % → «число не подтверждено».

    PASS: расходящиеся оценки — conflicting_evidence с объяснением.
    """
    unit = "Nasdaq упал 3,4% 30 октября 2026 года."
    plan = _plan(unit)
    blocks = ("Nasdaq fell 2.8% on October 30\n"
              "Tech sell-off deepened\n"
              "https://markets.example.com/a\n\n"
              "Nasdaq fell 3.1% on October 30\n"
              "Later revisions\n"
              "https://markets.example.com/b")
    outcome = await _retrieve(plan, RoutedAggregator((("nasdaq", blocks),)))
    cov = outcome.claims[0]
    assert cov.outcome == fsp.CLAIM_OUTCOME_CONFLICTING
    assert cov.status_detail == fsp.CLAIM_STATUS_CONFLICTING
    assert "расходятся" in cov.gap_note
    assert len(cov.evidence) >= 2           # обе оценки не замолчаны
    visible = fr.visible_text(_publish(_verdict_only(outcome)))
    assert "расходятся" in visible


def _technical_verdict() -> orch.CheckedVerdict:
    """Вердикт, где обе части упали технически, reason-код прогона пуст."""
    return orch.CheckedVerdict(
        verdict_text="Поиск не дал материалов.",
        route="envelope_temporal", factual_verdict="insufficient_evidence",
        parts=(
            {"part_id": "p1", "text": "Индекс упал",
             "factual_verdict": "insufficient_evidence",
             "status_detail": "provider_error", "evidence_refs": []},
            {"part_id": "p2", "text": "Nasdaq вырос",
             "factual_verdict": "insufficient_evidence",
             "status_detail": "deadline_exceeded", "evidence_refs": []},
        ))


def test_review_f3_technical_failure_not_called_insufficient(planner_on):
    """RED: provider_error → «Недостаточно данных для проверки» и
    «данных недостаточно (поиск не ответил…)».

    PASS: технический сбой получает технический заголовок и подпись части;
    «данных недостаточно» остаётся только для реального отсутствия данных.
    """
    markup = _publish(_technical_verdict())
    visible = fr.visible_text(markup)
    assert "Проверка не завершена: поиск недоступен" in visible
    assert "Недостаточно данных для проверки" not in visible
    assert "данных недостаточно" not in visible
    assert "поиск не завершён: технический сбой" in visible
    assert "поиск не завершён: лимит времени" in visible


@pytest.mark.asyncio
async def test_review_f4_telemetry_has_no_texts_and_has_trace_id(
        planner_on, caplog):
    """RED: событие несло тексты тезисов и URL, без trace_id/run_id.

    PASS: в событии только id/счётчики/роли/причина/цитаты + trace_id.
    """
    import logging
    plan = _plan(*CLAIM_MARKETS)
    outcome = await _retrieve(plan, RoutedAggregator())
    run, _llm = await _run_service(outcome)
    checked = _checked(run)
    with caplog.at_level(logging.INFO, logger="services.mca_events"):
        await orch._emit_claim_coverage(
            chat_id=CHAT_ID, outcome=outcome, verdict=checked,
            verbalizer_path="envelope_temporal", renderer_path="telegram_html",
            critical_section_enabled=True, trace_id="tr-f4-1",
            pipeline_run_id="tr-f4-1")
    event_lines = [r.getMessage() for r in caplog.records
                   if "mca_event=factcheck_claims" in r.getMessage()]
    assert event_lines, "событие factcheck_claims не записано"
    line = event_lines[-1]
    assert "trace_id=tr-f4-1" in line
    assert "pipeline_run_id=tr-f4-1" in line
    # ни текстов тезисов, ни URL
    assert "мировые рынки" not in line.lower()
    assert "http" not in line
    assert "example.com" not in line
    # строки claim в событии не содержат text/url
    assert '"text"' not in line and '"url"' not in line
    assert "citation_ids" in line and "status_detail" in line


@pytest.mark.asyncio
async def test_review_f5_qualifies_does_not_stop_refinement(planner_on):
    """RED: одна «событийная» ссылка (qualifies) отменяла уточнение по числу.

    PASS: уточнение выполняется, пока нет сильного подтверждения.
    """
    unit = "Alphabet (GOOGL) потеряла $658 млрд капитализации."
    plan = _plan(unit)
    base_queries = {q.text for q in plan.queries
                    if q.purpose == fsp.QUERY_PURPOSE_BASE}

    class NumberOnRefine:
        def __init__(self):
            self.calls: list[str] = []

        async def search(self, query, max_symbols):
            self.calls.append(query)
            if query in base_queries:
                return BLOCK_EVENT_ONLY
            return ("Alphabet (GOOGL) market value fell by $658 billion\n"
                    "Confirmed by the filing\n"
                    "https://markets.example.com/filing")

    agg = NumberOnRefine()
    outcome = await _retrieve(plan, agg)
    assert outcome.refine_calls >= 1
    assert len(agg.calls) > len(base_queries)
    cov = outcome.claims[0]
    assert cov.outcome == fsp.CLAIM_OUTCOME_CONFIRMED
    assert cov.status_detail == fsp.CLAIM_STATUS_VERIFIED


@pytest.mark.asyncio
async def test_review_claims_beyond_query_budget_are_marked_honestly(
        planner_on):
    """Nonblocking: части сверх бюджета запросов не исчезают молча."""
    units = tuple(f"Утверждение {i} про рынок и индекс." for i in range(14))
    plan = _plan(*units)
    assert len(plan.claims) == 14
    outcome = await _retrieve(
        plan, RoutedAggregator((), default=""))
    unchecked = [cov for cov in outcome.claims
                 if cov.search_status == fsp.CLAIM_SEARCH_DEADLINE]
    assert len(unchecked) == 14 - len(plan.queries)
    for cov in unchecked:
        assert cov.status_detail == fsp.CLAIM_STATUS_DEADLINE
        assert "лимит" in cov.gap_note
    summary = outcome.coverage_summary()
    assert summary["total_claims"] == 14
