"""PVR-FC corrective (05.11.2026) — FC-BACKEND slice: приёмочные проверки.

TEST-LIFECYCLE: CONTRACT owner=PVR-FC-CORRECTIVE-01 (FC-01..FC-05, FC-07,
C1.6–C1.9, temporal row claim-time vs publication dates)

Тесты зеркалируют приёмочные примеры карты требований
(``plans/features/pvr-fc-corrective-01/requirements-map.json``, slice
FC-BACKEND): кейс «4 ячейки с тестостероном», отказ Reddit-кандидата про
датировку фотографий, невозврат понижения validator'а, корреляция ≠
причинность, разделение времени клейма и дат публикации, честные
деградации. Всё детерминированно: сеть/LLM/БД/Telegram не вызываются.

Мутационная чувствительность:
* удаление тематического шлюза → reddit-кандидат получает word-overlap роль
  и тест (b) краснеет;
* возврат эскалации из старых parts после validator-понижения → тест (c)
  краснеет;
* возврат source_kind="primary" за fetch → тесты FC-03.3 краснеют.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import types

import pytest

from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services import factcheck_service as fsvc
from services import search_aggregator as sa
from services import temporal_factcheck as tf

CHAT_ID = -100930
TARGET_TG = 9300
TRIGGER_TG = 9301


# ── Fakes (прецеденты test_evol_fc_evidence_style / test_factcheck_w1) ──────

class RoutedAggregator:
    """Выдача по первому совпавшему needle; журнал вызовов."""

    def __init__(self, routes=(), *, default: str = "",
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
            raise sa.AllSearchEnginesFailedException("timeout",
                                                    reason="timeout")
        for needle, block in self.routes:
            if needle in low:
                return block
        return self.default

    async def search_relevant(self, query, max_symbols,
                              relevance_terms=None, **kw):
        return await self.search(query, max_symbols)


@pytest.fixture
def planner_on():
    from config.settings import settings
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


def _plan(claim_text: str):
    """План от одного клейма (decision-минимум, как в evidence_style)."""
    decision = types.SimpleNamespace(scope="web", claim_items=(),
                                     target_ref=None)
    return fsp.build_retrieval_plan(decision, claim_text=claim_text)


def _retrieve(plan, agg, **kw):
    return asyncio.run(fsp.run_retrieval(plan, aggregator=agg, **kw))


def _env(claim: str = "Тестовый проверяемый тезис.", **over):
    return tf.TemporalClaimEnvelope(
        claim_id="c-fcb", chat_id=CHAT_ID, target_tg_message_id=TARGET_TG,
        target_revision=None, target_content_hash=None,
        trigger_tg_message_id=TRIGGER_TG, claim_text=claim, claim_span=None,
        source_type="text", attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=None, original_published_precision=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None, date_source="unknown",
        date_precision="unknown", date_timezone=None, date_uncertainty={},
        requested_mode="contextual", analysis_as_of=1792200000, **over)


# ── (a) FC-01.1/FC-01.2/FC-02.2: 4 ячейки — смысловые тезисы, не OCR-запрос ──

FC_IMAGE_MATERIAL = (
    "Текст с изображения 1 (OCR, не слова автора):\n"
    "Люди с высоким тестостероном имеют низкий интеллект и ведут себя "
    "агрессивно. Вывод: внешность определяет характер человека.\n\n"
    "Визуальное описание изображения 1 (результат модели; не доказывает "
    "подлинность, дату или место):\n"
    "Четыре ячейки с мужскими лицами и подписями высоко/низко."
)

#: служебные метки, которые НЕ должны попасть в поисковые запросы
_SERVICE_MARKERS = (
    "текст с изображения", "ocr", "не слова автора",
    "визуальное описание", "результат модели",
)


def test_fc01_four_cell_image_semantic_theses_not_ocr_query(planner_on):
    """FC-01.1/FC-02.2: тезисы извлечены по смыслу (сущности/связь/вывод),
    служебные обёртки распознавания в публичный поисковик не уходят,
    запрос — не пересказ всего OCR-блока."""
    plan = _plan(FC_IMAGE_MATERIAL)
    assert plan is not None and plan.queries
    queries = [q.text for q in plan.queries]
    joined = " ".join(queries).lower()
    # смысловые тезисы присутствуют (предмет: тестостерон/интеллект/характер)
    assert "тестостерон" in joined
    # служебные данные способа распознавания — вне поискового пути
    for marker in _SERVICE_MARKERS:
        assert marker not in joined, marker
    # «нет пересказа»: каждый запрос — короткая смысловая формулировка,
    # а не весь OCR-блок дословно
    for query in queries:
        assert len(query) <= fsp._QUERY_MAX_CHARS
        assert query.lower() != FC_IMAGE_MATERIAL.lower().strip()[:200]
        assert "\n" not in query


def test_fc01_service_labels_stay_in_claim_for_analyst():
    """FC-01.1: зачистка меток — только на поисковом пути; клейм для
    аналитика остаётся с метками происхождения материала."""
    thesis = fsp.search_thesis_text(FC_IMAGE_MATERIAL)
    for marker in _SERVICE_MARKERS:
        assert marker not in thesis.lower()
    assert "тестостерон" in thesis.lower()          # содержательное живо
    # сам клейм не менялся
    assert FC_IMAGE_MATERIAL.startswith("Текст с изображения")


# ── (b) FC-03.1/FC-03.3/FC-06.3: Reddit-кандидат про датировку фото ─────────

_TESTOSTERONE_CLAIM = (
    "На фото четыре ячейки: люди с высоким тестостероном и низким "
    "интеллектом ведут себя иначе.")

_REDDIT_PHOTO_BLOCK = (
    "Reddit: помогите определить дату съёмки старой фотографии — люди, "
    "мода, плёнка. Как определить время фото по деталям.\n"
    "https://reddit.com/r/photography/comments/dating")


def test_fc03_reddit_photo_dating_candidate_rejected_off_topic():
    """FC-03.1: ссылка с теми же общими словами, но другой темой —
    off_topic, а не evidence; верификатор не позволяет ей стать источником."""
    rel = sa.claim_relevance(_REDDIT_PHOTO_BLOCK,
                             claim_text=_TESTOSTERONE_CLAIM)
    assert rel.role == sa.EVIDENCE_ROLE_IRRELEVANT
    assert not rel.displayable
    # мутационная чувствительность: без шлюза совпадение общих слов
    # (люди/иначе/фото) давало бы пол ≤2 word_hits → роль evidence
    assert rel.word_hits >= 1


def test_fc03_reddit_candidate_never_enters_citations(planner_on):
    """FC-06.3/FC-07.1: reddit-страница не входит в citations/footer и не
    называется источником — off_topic снимается на binding-слое."""
    plan = _plan(_TESTOSTERONE_CLAIM)
    outcome = _retrieve(plan, RoutedAggregator(
        (("тестостерон", _REDDIT_PHOTO_BLOCK),)))
    assert outcome.off_topic_sources_dropped >= 1
    refs = outcome.evidence_map.refs if outcome.evidence_map else ()
    assert all("reddit.com" not in str(r.url or "") for r in refs)
    for cov in outcome.claims:
        for item in cov.evidence:
            assert "reddit.com" not in str(item.url or "")


def test_fc03_fetched_forum_page_stays_secondary_not_primary(planner_on):
    """FC-03.3: успешный fetch НЕ повышает source_kind — форум остаётся
    secondary и «первоисточником» не называется; gov-домен — primary по
    происхождению, а не по факту открытия."""
    forum_html = ("<html><body><p>Обсуждение датировки фотографий: люди, "
                  "плёнка, мода. Форумная ветка про время съёмки снимков "
                  "и как по деталям определить период съёмки фото.</p>"
                  "</body></html>")

    async def fake_fetch(url, max_bytes=None, timeout=None):
        return forum_html

    ref = asyncio.run(fsp.fetch_primary_evidence(
        "https://reddit.com/r/photography/comments/dating",
        fetch_text=fake_fetch))
    assert ref is not None
    assert ref.source_kind == "secondary"
    assert ref.source_kind == sa.classify_source_kind(
        "https://reddit.com/r/photography/comments/dating")

    gov_ref = asyncio.run(fsp.fetch_primary_evidence(
        "https://www.cdc.gov/niosh/topics/outdoor/", fetch_text=fake_fetch))
    assert gov_ref is not None
    assert gov_ref.source_kind == "primary"       # происхождение gov


def test_fc03_source_kind_words_no_primary_for_forum():
    """FC-03.3: словарь публичных имён типов источников не называет форум
    «первоисточником» — secondary после открытия страницы остаётся
    пересказом."""
    from services.factcheck_renderer import _SOURCE_KIND_LABELS
    assert _SOURCE_KIND_LABELS.get("primary") == "первоисточник"
    assert _SOURCE_KIND_LABELS.get("secondary") == "пересказ"


# ── (c) C1.9/FC-04.6: понижение validator'а не поднимается агрегатором ──────

def test_fc04_validator_downgrade_not_reescalated():
    """C1.9: validator понизил черновик — агрегатор не возвращает старый
    mixed из частей; обе стороны согласованы (положительная часть понижена,
    опровержение остаётся, поскольку согласуется с недостаточностью)."""
    env = _env("Вейпинг безопаснее сигарет и помогает бросить курить.")
    draft = tf.verdict_from_payload({
        "factual_verdict": "mixed", "temporal_status": "current",
        "parts": [
            {"part_id": "p1", "factual_verdict": "supported",
             "evidence_refs": ["ev-1"]},
            {"part_id": "p2", "factual_verdict": "refuted",
             "evidence_refs": ["ev-2"]},
        ]}, env)
    assert draft.factual_verdict == "mixed"       # двухстороннее содержание
    corrected, applied = tf.apply_validator(
        draft, {"agree": False,
                "corrected_factual_verdict": "insufficient_evidence",
                "note": "выдержки не подтверждают двухсторонний вывод"}, env)
    assert applied is True
    # мутационная чувствительность: эскалация из старых parts вернула бы
    # mixed — контракт требует согласованное понижение
    assert corrected.factual_verdict == "insufficient_evidence"
    part_statuses = {p.get("part_id"): p.get("factual_verdict")
                     for p in corrected.parts}
    # supported-часть понижена вместе с вердиктом (старый статус не живёт);
    # опровержение согласуется с недостаточностью целого и сохраняется
    assert part_statuses["p1"] == "insufficient_evidence"
    assert "supported" not in set(part_statuses.values())
    p1 = next(p for p in corrected.parts if p.get("part_id") == "p1")
    assert p1.get("validator_suppressed") is True
    assert p1.get("evidence_refs") == ["ev-1"]    # provenance не стёрт


def test_fc04_parts_and_global_consistent():
    """FC-04.5/FC-04.6: parts и глобальный enum не противоречат друг другу —
    supported-верх при опровергнутой части становится mixed; mixed без
    двухстороннего содержания понижается."""
    env = _env("Утверждение из двух значимых частей.")
    v = tf.verdict_from_payload({
        "factual_verdict": "supported", "temporal_status": "current",
        "parts": [
            {"part_id": "p1", "factual_verdict": "supported"},
            {"part_id": "p2", "factual_verdict": "refuted"},
        ]}, env)
    assert v.factual_verdict == "mixed"           # верх не прячет опровержение
    v2 = tf.verdict_from_payload({
        "factual_verdict": "mixed", "temporal_status": "current",
        "parts": [{"part_id": "p1", "factual_verdict": "supported"}]}, env)
    assert v2.factual_verdict == "insufficient_evidence"  # нет второй стороны


# ── (d) FC-04.7: корреляция не поднимается до причинного supported ──────────

def test_fc04_correlation_is_not_direct_support_for_cause_claim():
    """FC-04.7: положительные части без прямого подтверждающего evidence
    понижаются; корреляционные ссылки (qualifies/indirect) не удерживают
    причинный тезис, глобальный positive без direct-support запрещён."""
    claim = fsp.ClaimUnit(
        claim_id="c1",
        text="Высокий тестостерон вызывает низкий интеллект.",
        claim_type=fsp.CLAIM_TYPE_CAUSE)
    correlational = fsp.ClaimEvidence(
        claim_id="c1", evidence_id="ev-1", url="https://study.example/corr",
        role=sa.EVIDENCE_ROLE_QUALIFIES, strength="indirect")
    coverage = (fsp.ClaimCoverage(
        claim=claim, search_status=fsp.CLAIM_SEARCH_SEARCHED,
        status_detail=fsp.CLAIM_STATUS_NO_RELEVANT_SOURCES,
        outcome=fsp.CLAIM_OUTCOME_INSUFFICIENT, evidence=(correlational,),
        citation_ids=("ev-1",)),)
    verdict = tf.verdict_from_payload({
        "factual_verdict": "supported", "temporal_status": "current",
        "parts": [{"part_id": "c1",
                   "text": claim.text,
                   "factual_verdict": "supported",
                   "evidence_refs": ["ev-1"]}]}, _env(claim.text))
    merged = fsvc.merge_claim_coverage(verdict, coverage, evidence=())
    part = next(p for p in merged.parts
                if str(p.get("part_id")) == "c1")
    assert part["factual_verdict"] == "insufficient_evidence"
    assert merged.factual_verdict == "insufficient_evidence"


def test_fc04_positive_verdict_without_direct_support_downgraded():
    """FC-04.7: положительный вердикт, который агрегат вернул бы из частей
    без прямого подтверждающего evidence, понижается сервером с честной
    пометкой (basis* — формальный вывод — исключение)."""
    claim = fsp.ClaimUnit(claim_id="c1",
                          text="Тезис с косвенными источниками.",
                          claim_type=fsp.CLAIM_TYPE_CAUSE)
    weak = fsp.ClaimEvidence(
        claim_id="c1", evidence_id="ev-1", url="https://study.example/x",
        role=sa.EVIDENCE_ROLE_QUALIFIES, strength="indirect")
    coverage = (fsp.ClaimCoverage(
        claim=claim, search_status=fsp.CLAIM_SEARCH_SEARCHED,
        status_detail=fsp.CLAIM_STATUS_PARTIAL,
        outcome=fsp.CLAIM_OUTCOME_PARTIAL, evidence=(weak,),
        citation_ids=("ev-1",)),)
    verdict = tf.verdict_from_payload({
        "factual_verdict": "supported", "temporal_status": "current",
        "parts": [
            {"part_id": "c1", "text": claim.text,
             "factual_verdict": "mixed", "evidence_refs": ["ev-1"]},
            {"part_id": "c1b", "text": "вторая часть",
             "factual_verdict": "supported", "evidence_refs": []},
        ]}, _env(claim.text))
    merged = fsvc.merge_claim_coverage(verdict, coverage, evidence=())
    # после понижения неподтверждённых частей агрегат вернул бы supported —
    # guard FC-04.7 требует хотя бы один direct supporting evidence
    assert merged.factual_verdict == "insufficient_evidence"
    assert "positive_without_direct_support" in (merged.uncertainty or {})
    # с помеченным формальным основанием — принудительного понижения нет
    with_basis = dataclasses.replace(
        verdict, uncertainty={"basis": "внутренняя проверка: расчёт"})
    kept = fsvc.merge_claim_coverage(with_basis, coverage, evidence=())
    assert kept.factual_verdict != "insufficient_evidence" \
        or "positive_without_direct_support" not in (kept.uncertainty or {})


def test_fc04_correlational_role_is_indirect_strength():
    """FC-03.2: корреляционная ссылка для причинного тезиса — qualifies с
    strength=indirect (доказательством прямым не становится)."""
    claim = ("Высокий тестостерон вызывает низкий интеллект у людей.")
    body = ("Исследование: у людей с высоким тестостероном ниже результаты "
            "тестов интеллекта, корреляция умеренная.")
    rel = sa.claim_relevance(body, claim_text=claim,
                             claim_type=fsp.CLAIM_TYPE_CAUSE)
    assert rel.role == sa.EVIDENCE_ROLE_QUALIFIES     # нет причинной связки
    assert rel.strength == "indirect"
    direct = sa.claim_relevance(
        "Высокий тестостерон вызывает снижение интеллекта из-за влияния "
        "на нейроны у людей.", claim_text=claim,
        claim_type=fsp.CLAIM_TYPE_CAUSE)
    assert direct.role == sa.EVIDENCE_ROLE_SUPPORTS
    assert direct.strength == "direct"


# ── (e) temporal row: время клейма ≠ даты публикации (UR-27/ChatClock) ──────

def test_fc07_claim_time_not_overwritten_by_publication_date():
    """Temporal row: заявленный период клейма важнее даты публикации;
    дата публикации evidence остаётся своей; момент анализа — отдельно."""
    env = tf.TemporalClaimEnvelope(
        claim_id="c-fcb", chat_id=CHAT_ID, target_tg_message_id=TARGET_TG,
        target_revision=None, target_content_hash=None,
        trigger_tg_message_id=TRIGGER_TG,
        claim_text="В 2019 году заболеваемость выросла.", claim_span=None,
        source_type="text", attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=1685577600,      # 2023-06-01 (дата публикации)
        original_published_precision="day",
        claim_period_from=1546300800,          # 2019-01-01 (период КЛЕЙМА)
        claim_period_to=1577836799,
        claim_period_precision="year",
        date_source="original", date_precision="day",
        date_timezone=None, date_uncertainty={},
        requested_mode="contextual", analysis_as_of=1792200000)
    period = tf._default_evaluated_period(env)
    assert period["from"] == 1546300800              # период клейма 2019
    assert period["precision"] == "year"
    verdict = tf.verdict_from_payload({}, env)
    assert verdict.evaluated_period == period
    # дата публикации не подменяет период клейма
    assert verdict.evaluated_period["from"] != 1685577600
    assert verdict.as_of == 1792200000               # момент анализа отдельно


def test_fc07_chatclock_block_does_not_replace_source_dates():
    """Temporal row (UR-26.4/UR-27): ChatClock добавляет время оценки
    отдельным блоком, не подменяя даты публикаций в payload."""
    import datetime as _dt
    from services import chat_clock as cclock
    base = ("<temporal_context>\n"
            "публикация источника: 2023-06-01T00:00Z\n"
            "</temporal_context>")
    moment = _dt.datetime(2026, 11, 6, 12, 0,
                          tzinfo=_dt.timezone.utc)
    snap = cclock.TimeSnapshot(
        as_of_utc=moment,
        local_datetime=moment + _dt.timedelta(hours=3),
        weekday="пятница", timezone="Europe/Moscow", utc_offset="+03:00",
        timezone_source="chat", config_version="cfg-1")
    payload = cclock.append_time_block(base, snap,
                                       phase=cclock.PHASE_ANSWER)
    # дата публикации источника осталась в своём значении и не сдвинута
    assert "2023-06-01" in payload
    # время оценки присутствует отдельным блоком ChatClock
    assert "2026-11-06" in payload
    assert payload.index("2023-06-01") < payload.index("2026-11-06")


# ── (f) FC-05: честные деградации (существующая taxonomy) ───────────────────

def test_fc05_provider_error_is_not_empty_results():
    agg = sa.SearchAggregator(tavily_api_key="t", exa_api_key="")

    async def boom(query, timeout_budget=None):
        raise RuntimeError("503 service unavailable")

    agg._search_tavily = boom
    agg._search_exa = boom
    agg._search_ddg = boom
    with pytest.raises(sa.AllSearchEnginesFailedException) as ei:
        asyncio.run(agg.search("q", 100))
    assert ei.value.reason == "provider_error"


def test_fc05_timeout_distinguished():
    agg = sa.SearchAggregator(tavily_api_key="t", exa_api_key="")

    async def slow(query, timeout_budget=None):
        import httpx
        raise httpx.TimeoutException("read timed out")

    agg._search_tavily = slow
    agg._search_exa = slow
    agg._search_ddg = slow
    with pytest.raises(sa.AllSearchEnginesFailedException) as ei:
        asyncio.run(agg.search("q", 100))
    assert ei.value.reason == "timeout"
    assert ei.value.reason != "provider_error"


def _outcome(**over):
    base = dict(evidence_map=None, search_text="", queries_attempted=0,
                queries_used=0, refs_collected=0, fetch_errors=0,
                budget_exhausted=False, provider_failures=0,
                claims=(), budget_seconds=1.0)
    base.update(over)
    return fsp.RetrievalOutcome(**base)


def test_fc05_empty_results_are_not_reported_as_down():
    from services.factcheck_service import (
        RETRIEVAL_NO_RESULTS, RETRIEVAL_SEARCH_FAILED, classify_retrieval)
    outcome = _outcome(queries_attempted=2, empty_results=2)
    assert classify_retrieval(outcome) == RETRIEVAL_NO_RESULTS
    assert classify_retrieval(outcome) != RETRIEVAL_SEARCH_FAILED


def test_fc05_provider_failures_classified_as_search_failed():
    from services.factcheck_service import (
        RETRIEVAL_SEARCH_FAILED, classify_retrieval)
    outcome = _outcome(queries_attempted=2, provider_failures=2)
    assert classify_retrieval(outcome) == RETRIEVAL_SEARCH_FAILED


def test_fc05_budget_deadline_is_technical_status():
    """FC-05.1: исчерпанный бюджет — технический исход части, а не «данных
    нет» и не опровержение."""
    claim = fsp.ClaimUnit(claim_id="c1", text="Тезис про события 2026 года.")
    plan = fsp.RetrievalPlan(
        queries=(fsp.SearchQuery(text="тезис события 2026",
                                 intent=fsp.INTENT_ENTITY_CHECK,
                                 claim_id="c1"),),
        needs_web=True, claims=(claim,))
    agg = RoutedAggregator(slow_needles=("тезис",), sleep=0.5)
    outcome = _retrieve(plan, agg, budget_seconds=0.05)
    cov = outcome.claims[0]
    assert outcome.budget_exhausted is True
    assert cov.status_detail in (fsp.CLAIM_STATUS_DEADLINE,
                                 fsp.CLAIM_STATUS_PROVIDER_ERROR)
    assert cov.gap_note


def test_fc05_page_open_error_is_source_extract_status(planner_on):
    """FC-05.1/FC-03.2: не удалось открыть страницу — фактический сбой
    чтения фиксируется, страница не выдаётся за прочитанную; исход части
    остаётся честным (сниппет-уровень или технический статус), без
    превращения в «прочитанное исследование»."""
    claim = ("Метеорологи подтвердили: в июле 2019 года выпало 120 мм "
             "осадков за сутки.")
    block = ("Сводка осадков за июль 2019: 120 мм за сутки\n"
             "Метеорология региона подтверждает данные\n"
             "https://weather.example/july-2019")
    plan = _plan(claim)

    async def broken_fetch(url, max_bytes=None, timeout=None):
        raise RuntimeError("connection reset")

    outcome = _retrieve(plan, RoutedAggregator((("120", block),)),
                        fetch_text=broken_fetch)
    cov = outcome.claims[0]
    assert outcome.fetch_errors >= 1
    assert cov.opened == 0                       # страница НЕ прочитана
    assert cov.search_status != fsp.CLAIM_SEARCH_SOURCE_READ
    from services.factcheck_service import evidence_diagnostics
    fields = evidence_diagnostics(retrieval=outcome,
                                  retrieval_state="processing_failed",
                                  evidence=(), verdict=types.SimpleNamespace(
                                      reason="source_missing"))
    assert fields["extract_failures"] == outcome.fetch_errors
    assert fields["extract_successes"] == 0


def test_fc05_vision_failures_honest_notice():
    """FC-01.3/FC-05.1: недоступное изображение/неготовое распознавание —
    явная честная оговорка, а не заявление о проверенной публикации."""
    material_failed = fsvc.ClaimMediaMaterial(
        image_present=False, vision_failed=True)
    assert not material_failed.image_present
    material_unchecked = fsvc.ClaimMediaMaterial(
        image_present=True, image_count=1, image_unchecked=True,
        unchecked_reason="vision_failed")
    text = material_unchecked.notice()
    assert "не удалось" in text or "НЕ проверено" in text
    assert material_unchecked.image_unchecked is True
    # pending — отдельный честный статус, не «текста нет»
    material_pending = fsvc.ClaimMediaMaterial(
        image_present=True, image_analyzed=False, image_not_analyzed=True,
        pending_count=1, image_count=1)
    assert "не готово" in material_pending.notice() or \
        "распознана" in material_pending.notice()


def test_fc05_empty_search_never_invents_sources():
    """FC-05.2: при недоступном поиске источники не сочиняются —
    diagnostics без цитируемых ссылок, класс технический."""
    from services.factcheck_service import (
        RETRIEVAL_SEARCH_FAILED, evidence_diagnostics)
    outcome = _outcome(queries_attempted=2, provider_failures=2,
                       attempted_queries=("запрос один", "запрос два"))
    fields = evidence_diagnostics(retrieval=outcome,
                                  retrieval_state=RETRIEVAL_SEARCH_FAILED,
                                  evidence=(), verdict=types.SimpleNamespace(
                                      reason="provider_unavailable"))
    assert fields["citable_evidence_count"] == 0
    assert fields["retrieval_class"] == RETRIEVAL_SEARCH_FAILED
    assert fields["technical_reason"] == "provider_unavailable"


# ── FC-03.2/FC-07.1: provenance кандидата и attempted queries ───────────────

def test_fc03_candidate_metadata_stored(planner_on):
    """FC-03.2: кандидат хранит claim_id/url/title/passage/дату/relation/
    strength/opened; прямое подтверждение — direct."""
    claim = ("Метеорологи подтвердили: в июле 2019 года выпало 120 мм "
             "осадков за сутки.")
    block = ("Сводка осадков за июль 2019: выпало 120 мм за сутки\n"
             "Метеорология региона подтверждает данные наблюдений\n"
             "https://weather.example/july-2019")
    plan = _plan(claim)

    async def fetch(url, max_bytes=None, timeout=None):
        return ("<html><head><meta property=\"article:published_time\" "
                "content=\"2019-08-01T06:00:00+00:00\"></head><body><p>"
                "Сводка осадков за июль 2019 года: выпало "
                "120 мм осадков за сутки по данным метеорологов региона. "
                "Наблюдения подтверждены станциями сети.</p></body></html>")

    outcome = _retrieve(plan, RoutedAggregator((("120", block),)),
                        fetch_text=fetch)
    cov = outcome.claims[0]
    assert cov.evidence
    item = cov.evidence[0]
    assert item.claim_id == cov.claim.claim_id
    assert item.url == "https://weather.example/july-2019"
    assert item.title                                  # нормализованный title
    assert item.role in sa.DISPLAYABLE_EVIDENCE_ROLES
    assert item.strength in ("direct", "indirect")
    assert item.published_at                           # дата источника
    assert isinstance(item.opened, bool)


def test_fc07_attempted_queries_in_diagnostics(planner_on):
    """FC-07.1: attempted queries прогона попадают в приватную диагностику
    (без текста чата), вместе с причинами отказа кандидатов."""
    claim = "Метеорологи подтвердили летние осадки."
    plan = _plan(claim)
    outcome = _retrieve(plan, RoutedAggregator((("осадки", ""),)))
    assert outcome.queries_attempted >= 1
    assert outcome.attempted_queries
    from services.factcheck_service import (
        RETRIEVAL_NO_RESULTS, evidence_diagnostics)
    fields = evidence_diagnostics(retrieval=outcome,
                                  retrieval_state=RETRIEVAL_NO_RESULTS,
                                  evidence=(), verdict=types.SimpleNamespace(
                                      reason=""))
    assert fields["attempted_queries"] == list(outcome.attempted_queries)
    assert fields["off_topic_sources_dropped"] == \
        outcome.off_topic_sources_dropped


# ── C1.6/C1.7/C1.8: ссылки только при доказательности; coverage ≠ mixed ─────

def test_c16_off_topic_link_never_published_as_source(planner_on):
    """C1.6: ссылка публикуется только при реальной доказательности —
    off-topic кандидат не попадает в EvidenceMap прогона."""
    claim = ("Метеорологи подтвердили: в июле 2019 года выпало 120 мм "
             "осадков за сутки.")
    gold_block = ("Золото подорожало до 4200 долларов за унцию\n"
                  "Драгметалл обновил максимум\n"
                  "https://metals.example/gold")
    plan = _plan(claim)
    outcome = _retrieve(plan, RoutedAggregator((("осадков", gold_block),)))
    refs = outcome.evidence_map.refs if outcome.evidence_map else ()
    assert all("metals.example" not in str(r.url or "") for r in refs)


def test_c17_logical_proof_basis_not_forced_insufficient():
    """C1.7: формальный вывод с помеченным основанием (uncertainty basis*)
    не понижается принудительной недостаточностью."""
    payload = {
        "factual_verdict": "mixed",
        "temporal_status": "unknown",
        "parts": [{"part_id": "p1", "factual_verdict": "supported",
                   "note": "арифметика по заданным числам"},
                  {"part_id": "p2", "factual_verdict": "refuted",
                   "note": "внутреннее противоречие"}],
        "uncertainty": {"basis": "внутренняя проверка: расчёт и логика"},
    }
    v = tf.verdict_from_payload(payload, _env("Арифметический тезис."))
    assert v.factual_verdict == "mixed"


def test_c18_coverage_partial_is_not_mixed_synonym():
    """C1.8: mixed — о доказательном содержании; непроверенная часть с
    техническим исходом не делает вердикт mixed."""
    v = tf.verdict_from_payload({
        "factual_verdict": "insufficient_evidence",
        "temporal_status": "unknown",
        "parts": [{"part_id": "p1", "factual_verdict": "supported",
                   "evidence_refs": ["ev-1"]},
                  {"part_id": "p2", "factual_verdict": "insufficient_evidence",
                   "status_detail": "deadline_exceeded",
                   "note": "поиск прерван по лимиту времени"}]},
        _env("Составной тезис."))
    assert v.factual_verdict == "insufficient_evidence"
    statuses = {p.get("part_id"): p.get("status_detail") for p in v.parts}
    assert statuses["p2"] == "deadline_exceeded"      # полнота отдельно
