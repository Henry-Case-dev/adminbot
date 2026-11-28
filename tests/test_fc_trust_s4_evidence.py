"""FCT-S4 U1 — доказательства и даты (FCT-023/501/702), 28.11.2026.

Контракт: `plans/features/fc-trust-01/evidence/fct-s4-design-2026-11-28/s4-design.md`
§2.1–§2.4/§4-U1 + decisions D2 (`publication_kind` — отдельная ось на
`ClaimEvidence`; `source_kind` не расширяется).

Проверяется наблюдаемое поведение:
* форма публикации различима (preprint/press_release/journal_article/
  secondary_report/interpretation/unknown) и влияет на доказательную силу:
  пресс-релиз (не официальный первоисточник) и интерпретация не дают прямой
  силы, `source_kind` не меняется;
* раздельные даты: `claim_valid_from/to`, `retrieved_at`, `original_posted_at`,
  `timezone`, `timestamp_source/confidence`; неизвестная дата остаётся None/
  unknown (никогда not now()/текущий год);
* `unverified_media` — структурный флаг только у затронутой медиа-части,
  текстовая часть не помечается; рендер не меняется.
"""
from __future__ import annotations

import asyncio
import dataclasses
import types

import pytest

from services import factcheck_planner as fsp
from services import search_aggregator as sa
from services import temporal_factcheck as tf
from services.factcheck_suitability import (CHECKABLE_FACTUAL_CLAIM,
                                            DECISION_CHECKABLE, ClaimItem,
                                            SuitabilityDecision)
from config.settings import settings

CHAT_ID = -100777
CLAIM = "Индекс S&P 500 упал на 2,1% 30 октября 2026 года."


def _plan(claim_text=CLAIM, *, unit_kwargs=None,
          queries=None, needs_fetch=False) -> fsp.RetrievalPlan:
    unit = fsp.ClaimUnit(claim_id="c1", text=claim_text,
                         metrics=("2,1%",), entities=("S&P",),
                         timeframe="30 октября 2026", units=("percent",),
                         **(unit_kwargs or {}))
    query = fsp.SearchQuery(text="s&p 500 индекс", intent=(
        fsp.INTENT_ENTITY_CHECK), claim_id="c1")
    return fsp.RetrievalPlan(queries=queries or (query,), needs_web=True,
                             needs_primary_fetch=needs_fetch,
                             claim_text=claim_text,
                             claims=(unit,), chat_id=CHAT_ID)


class _Agg:
    def __init__(self, text):
        self.text = text
        self.calls = []

    async def search(self, query, max_symbols):
        self.calls.append(query)
        return self.text

    async def search_relevant(self, query, max_symbols, **kw):
        self.calls.append(query)
        return self.text


def _off_limits():
    return fsp.FactcheckLimits(budgets_enabled=False, primary_fetches=None)


async def _page_fetch(url, max_bytes=None, timeout=None):
    return ('<html><body><p>S&P 500 falls 2.1% on October 30, as investors '
            'sold risk assets into the close.</p></body></html>')


def _coverage_for(text, *, unit_kwargs=None, fetch_text=None,
                  needs_fetch=False):
    plan = _plan(unit_kwargs=unit_kwargs, needs_fetch=needs_fetch)
    return asyncio.run(fsp.run_retrieval(
        plan, aggregator=_Agg(text), fetch_text=fetch_text,
        limits=_off_limits()))


def _decision(items):
    return SuitabilityDecision(
        decision=DECISION_CHECKABLE, claim_type=CHECKABLE_FACTUAL_CLAIM,
        claim_items=tuple(items), scope="web", reason_code=None,
        confidence=0.9, target_ref={"target_tg_message_id": 7712})


@pytest.fixture
def planner_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


# ── FCT-023: форма публикации — отдельная ось ──────────────────────────────

class TestPublicationKind:

    @pytest.mark.parametrize("url,expected", [
        ("https://arxiv.org/abs/2401.00001", "preprint"),
        ("https://www.medrxiv.org/content/10.1101/2026.01.01.1v1", "preprint"),
        ("https://www.biorxiv.org/content/10.1101/2025.12.31.1v1", "preprint"),
        ("https://www.eurekalert.org/news-releases/123", "press_release"),
        ("https://www.prnewswire.com/news-releases/x-301.html",
         "press_release"),
        ("https://www.nature.com/articles/s41586-026-00001-1",
         "journal_article"),
        ("https://doi.org/10.1038/s41586-026-00001-1", "journal_article"),
        ("https://pubmed.ncbi.nlm.nih.gov/12345678/", "journal_article"),
        ("https://example.org/opinion/2026/what-we-think", "interpretation"),
        ("https://example.org/commentary/analysis-of-the-deal",
         "interpretation"),
        ("https://news.example.com/story/2026/01/01/markets",
         "secondary_report"),
        ("", "unknown"),
        ("not-a-url", "unknown"),
    ])
    def test_kind_is_distinguishable(self, url, expected):
        kind, basis = sa.classify_publication_kind(url)
        assert kind == expected
        assert kind in sa.PUBLICATION_KINDS
        assert basis

    def test_source_kind_is_not_extended(self):
        """D2: четыре source_kind сохраняют смысл, ось отдельная."""
        assert sa.classify_source_kind("https://arxiv.org/abs/1") == "research"
        assert sa.classify_source_kind("https://www.sec.gov/x") == "primary"
        assert sa.classify_source_kind("https://ru.wikipedia.org/x") == \
            "reference"
        assert sa.classify_source_kind("https://example.org/a") == "secondary"
        row = tf.evidence_rows_from_refs((
            types.SimpleNamespace(
                evidence_id="ev-1", url="https://arxiv.org/abs/1",
                support="S&P 500 falls 2.1%", source_kind="research",
                published_at=None),))[0]
        assert row["source_kind"] == "research"          # прежняя ось
        assert row["publication_kind"] == "preprint"     # новая ось
        assert row["publication_kind_basis"].startswith("host:")

    def test_press_release_is_not_direct_support(self):
        """Мутация «press_release → direct» обязана ловиться."""
        text = ("S&P 500 falls 2.1% on October 30\nUS stocks slid\n"
                "https://www.eurekalert.org/news-releases/123")
        outcome = _coverage_for(text)
        cov = outcome.claims[0]
        assert cov.evidence
        ev = cov.evidence[0]
        assert ev.publication_kind == "press_release"
        assert ev.role == "qualifies"                # не прямое подтверждение
        assert ev.strength != "direct"
        assert ev.role != "supports"
        # часть не становится confirmed на одном пресс-релизе
        assert cov.outcome != fsp.CLAIM_OUTCOME_CONFIRMED
        assert "пресс-релиз" in ev.note

    def test_interpretation_is_not_direct_support(self):
        text = ("S&P 500 falls 2.1% on October 30, my take\n"
                "https://example.org/opinion/2026/10/markets")
        outcome = _coverage_for(text)
        ev = outcome.claims[0].evidence[0]
        assert ev.publication_kind == "interpretation"
        assert ev.role == "qualifies"
        assert ev.strength != "direct"

    def test_official_primary_press_release_keeps_support(self):
        """Собственный релиз официального источника — первичный материал."""
        text = ("S&P 500 falls 2.1% on October 30, says agency\n"
                "https://www.sec.gov/newsroom/press-release-2026-1")
        outcome = _coverage_for(text)
        ev = outcome.claims[0].evidence[0]
        assert ev.publication_kind == "press_release"
        assert ev.role == "supports"        # не понижен до qualifies
        assert ev.strength == "indirect"    # неоткрытый сниппет — не direct

    def test_negative_control_without_non_direct_kinds(self, monkeypatch):
        """Мутация «press_release → direct»: без запрета роль снова supports."""
        text = ("S&P 500 falls 2.1% on October 30\nUS stocks slid\n"
                "https://www.eurekalert.org/news-releases/123")
        monkeypatch.setattr(fsp, "PUBLICATION_NON_DIRECT_KINDS", frozenset())
        opened = _coverage_for(text, fetch_text=_page_fetch, needs_fetch=True)
        ev = opened.claims[0].evidence[0]
        assert ev.publication_kind == "press_release"
        assert ev.role == "supports"            # дефект воспроизведён
        assert ev.strength == "direct"

    @pytest.mark.parametrize("url", [
        "https://www.politico.com/news/2024/01/15/markets-fall",
        "https://www.politico.com/story/2024/01/15/markets-fall",
    ])
    def test_ordinary_news_path_is_not_press_release(self, url):
        """RV-S4U1-02: датированный путь новостного CMS — не пресс-релиз.

        Оба пути (`/news/YYYY/…` и `/story/YYYY/…`) — обычная новость:
        `secondary_report` и прямая сила; релиз определяется только по
        реальным признакам (`/press-release/`, newsroom, PR-домены)."""
        kind, basis = sa.classify_publication_kind(url)
        assert kind == "secondary_report"
        assert kind != "press_release"
        assert basis == "default:secondary_report"

    def test_news_url_keeps_confirmed_outcome(self):
        """Мутация «news/YYYY → press_release» ломает вердикт — ловим."""
        text = ("S&P 500 falls 2.1% on October 30\n"
                "https://www.politico.com/news/2024/01/15/markets-fall")
        cov = _coverage_for(text).claims[0]
        ev = cov.evidence[0]
        assert ev.publication_kind == "secondary_report"
        assert ev.role == "supports"
        assert ev.strength != "direct"          # неоткрытый сниппет
        assert cov.outcome == fsp.CLAIM_OUTCOME_CONFIRMED

    def test_opened_press_release_stays_qualifies(self):
        """RV-S4U1-01: открытая страница не обходит демоцию формы."""
        text = ("S&P 500 falls 2.1% on October 30\nUS stocks slid\n"
                "https://www.eurekalert.org/news-releases/123")
        cov = _coverage_for(text, fetch_text=_page_fetch,
                            needs_fetch=True).claims[0]
        ev = cov.evidence[0]
        assert ev.publication_kind == "press_release"
        assert ev.opened is True
        assert ev.role == "qualifies"
        assert ev.strength == "indirect"        # role qualifies → indirect
        assert "пресс-релиз" in ev.note         # caveat не потерян
        assert cov.outcome != fsp.CLAIM_OUTCOME_CONFIRMED

    def test_opened_official_press_release_stays_supports(self):
        """Официальный первичный релиз (primary) остаётся первичным."""
        text = ("S&P 500 falls 2.1% on October 30, says agency\n"
                "https://www.sec.gov/newsroom/press-release-2026-1")
        cov = _coverage_for(text, fetch_text=_page_fetch,
                            needs_fetch=True).claims[0]
        ev = cov.evidence[0]
        assert ev.publication_kind == "press_release"
        assert ev.opened is True
        assert ev.role == "supports"
        assert ev.strength == "direct"

    def test_as_dict_is_additive(self):
        text = ("S&P 500 falls 2.1% on October 30\n"
                "https://www.nature.com/articles/x")
        ev = _coverage_for(text).claims[0].evidence[0]
        data = ev.as_dict()
        assert data["publication_kind"] == "journal_article"
        assert "publication_kind_basis" in data
        # старые ключи не потеряны
        for key in ("claim_id", "evidence_id", "url", "role", "published_at",
                    "opened", "snippet_only", "date_status"):
            assert key in data


# ── FCT-501: раздельные даты, неизвестное = unknown ───────────────────────

class TestTimeFields:

    def test_plan_carries_valid_period_and_original_posted_at(self, planner_on):
        items = [ClaimItem(text=CLAIM, claim_type=CHECKABLE_FACTUAL_CLAIM,
                           verifiable=True, source="literal")]
        plan = fsp.build_retrieval_plan(
            _decision(items), claim_text=CLAIM,
            claim_valid_from=1767225600, claim_valid_to=1767312000,
            original_posted_at=1767225600)
        assert plan is not None
        unit = plan.claims[0]
        assert (unit.valid_from, unit.valid_to,
                unit.original_posted_at) == (1767225600, 1767312000,
                                             1767225600)
        # и на уровне evidence (копия из части)
        outcome = asyncio.run(fsp.run_retrieval(
            plan, aggregator=_Agg(
                "S&P 500 falls 2.1% on October 30\nhttps://example.org/a"),
            limits=_off_limits()))
        ev = outcome.claims[0].evidence[0]
        assert ev.claim_valid_from == 1767225600
        assert ev.claim_valid_to == 1767312000
        assert ev.original_posted_at == 1767225600

    def test_unknown_dates_stay_unknown_never_now(self):
        """Мутация «now()/текущий год вместо unknown» обязана ловиться."""
        now_year = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).year
        outcome = _coverage_for(
            "S&P 500 falls 2.1% on October 30\nhttps://example.org/a")
        ev = outcome.claims[0].evidence[0]
        assert ev.published_at is None            # дата публикации неизвестна
        assert ev.date_status == "unknown"
        assert ev.original_posted_at is None      # НЕ дата запроса
        assert ev.claim_valid_from is None
        assert ev.claim_valid_to is None
        assert ev.retrieved_at is None            # сниппет не открывался
        assert ev.timestamp_source == ""
        assert ev.timestamp_confidence == "unknown"
        assert now_year != ev.published_at        # не текущий год

    def test_opened_page_fills_retrieved_at_and_high_confidence(self):
        html = ('<html><head><meta property="article:published_time" '
                'content="2026-10-30T08:00:00+00:00"></head><body><p>'
                'S&P 500 falls 2.1% on October 30, as investors sold risk '
                'assets into the close.</p></body></html>')

        async def fetch(url, max_bytes=None, timeout=None):
            return html

        outcome = _coverage_for(
            "S&P 500 falls 2.1% on October 30\nhttps://example.org/a",
            fetch_text=fetch, needs_fetch=True)
        ev = outcome.claims[0].evidence[0]
        assert ev.opened is True
        assert ev.published_at is not None
        assert ev.timestamp_source == "page"
        assert ev.timestamp_confidence == "high"
        assert isinstance(ev.retrieved_at, int)
        assert ev.retrieved_at > 0

    def test_temporal_row_carries_same_time_fields(self):
        rows = tf.evidence_rows_from_refs((
            types.SimpleNamespace(
                evidence_id="ev-1", url="https://example.org/a",
                support="S&P 500 falls 2.1%", source_kind="secondary",
                published_at=1767225600),))
        row = rows[0]
        assert row["retrieved_at"]
        assert "publication_kind" in row and "publication_kind_basis" in row
        assert row["claim_valid_from"] is None
        assert row["original_posted_at"] is None
        assert row["timezone"] == ""
        assert row["timestamp_source"] == "provider"
        assert row["timestamp_confidence"] == "medium"
        assert row["unverified_media"] is False


# ── FCT-702: unverified_media — только затронутая часть ───────────────────

class _MediaHelpers:

    def _pub(self, **kw):
        from services import factcheck_orchestrator as orch
        base = dict(image_unchecked=False, vision_failed=False,
                    image_not_analyzed=False, truncated=False,
                    element_segments=(), caption="")
        base.update(kw)
        return types.SimpleNamespace(media=types.SimpleNamespace(**base))

    def test_helpers_follow_factual_media_state(self):
        from services import factcheck_orchestrator as orch
        pub = self._pub(image_unchecked=True,
                        element_segments=((1, "ocr_block", "OCR block"),),
                        caption="Caption")
        assert orch._media_unverified(pub) is True
        segs = orch._media_segments(pub)
        assert "OCR block" in segs and "Caption" in segs
        clean = self._pub()
        assert orch._media_unverified(clean) is False
        assert orch._media_segments(clean) == ()

    def test_no_parts_flagged_when_media_verified(self):
        outcome = _coverage_for(
            "На фото расписание поездов\nhttps://example.org/a")
        assert all(not ev.unverified_media
                   for ev in outcome.claims[0].evidence)


class TestUnverifiedMediaPerPart:

    def test_only_media_derived_part_is_flagged(self):
        caption = "На фото расписание поездов на завтра."
        claim = caption + " Поезда ходят по расписанию."
        units = fsp.build_claim_units(
            [], claim, media_unverified=True, media_segments=(caption,))
        flags = {u.text: u.unverified_media for u in units}
        assert flags
        media_units = [u for u in units if u.text.startswith("На фото")]
        text_units = [u for u in units if u.text.startswith("Поезда")]
        assert media_units and text_units
        assert media_units[0].unverified_media is True
        assert all(u.unverified_media is False for u in text_units)

    def test_no_flag_without_unverified_media(self):
        caption = "На фото расписание поездов на завтра."
        claim = caption + " Поезда ходят по расписанию."
        units = fsp.build_claim_units(
            [], claim, media_unverified=False, media_segments=(caption,))
        assert all(u.unverified_media is False for u in units)

    def test_evidence_carries_flag_for_affected_part(self):
        claim = "На фото расписание поездов. Поезда ходят по расписанию."
        plan = _plan(claim, unit_kwargs={"unverified_media": True})
        outcome = asyncio.run(fsp.run_retrieval(
            plan, aggregator=_Agg(
                "На фото расписание поездов\nhttps://example.org/a"),
            limits=_off_limits()))
        cov = outcome.claims[0]
        assert cov.evidence
        assert cov.evidence[0].unverified_media is True
        assert cov.as_dict()["claim"]["unverified_media"] is True
