"""P0-FACTCHECK-CORRECTIVE W1 (owner 28.10.2026) — офлайн F-матрица.

Источник: plans/features/p0-factcheck-post-release/source-2026-10-28.md.
Проверки без сети/LLM (моки агрегатора/LLM по существующим паттернам):

* §1/§2.4 — пустой evidence НЕ блокирует анализ: существующий аналитик
  получает утверждение, контекст, статус поиска, разрешение логической/
  математической проверки и рамку происхождения вывода; положительный
  вердикт без внешних доказательств и без basis-пометки понижается
  сервером (no-false-acceptance в обе стороны);
* §5 — таксономия причин поиска (недоступность/timeout/API-ошибка/пустая
  выдача/нерелевантная выдача/ошибка обработки/нет подтверждений/частичный
  успех); «поисковики недоступны» ≠ «выдача не прошла relevance-фильтр»;
* §6 — кеш готовых вердиктов удалён во всех маршрутах (повторный тезис →
  новая проверка, старые ошибки не отдаются, дубль-отправки нет);
* §7 — вербализация: содержание проходит; без анализа — короткая честная
  граница; renderer не дублирует то же ограничение.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx

import services.factcheck_orchestrator as orch
import services.factcheck_planner as fsp
import services.factcheck_renderer as fr
import services.factcheck_service as fsvc
import services.search_aggregator as sa
import services.temporal_factcheck as tf
from config.settings import settings
from services.factcheck_service import (
    FactCheckService,
    RETRIEVAL_BUDGET,
    RETRIEVAL_INSUFFICIENT,
    RETRIEVAL_NO_RESULTS,
    RETRIEVAL_PROCESSING_FAILED,
    RETRIEVAL_SEARCH_FAILED,
    classify_retrieval,
)

CHAT_ID = -100777
TARGET_TG = 7700
TRIGGER_TG = 7701

CLAIM = ("⚡️ В чипе 96 линий PCIe: 40 от процессора и 56 от чипсета. "
         "Итого 96 линий у устройства.")


# ── Фейки (без сети/БД/LLM) ─────────────────────────────────────────────────

def _origin_row(text=CLAIM):
    return {"text": text, "caption": None, "origin_type": "channel",
            "origin_sent_at": None, "sent_at": 1792200000,
            "current_revision": None, "content_hash": None,
            "origin_sender_user_id": None, "origin_chat_id": -777,
            "origin_display_name": "Канал", "author_name": None,
            "forward_source": None}


class FakeDB:
    def __init__(self, origin_row=None):
        self._origin = origin_row or _origin_row()

    async def get_smart_message_origin_block(self, chat_id, tg):
        return dict(self._origin)

    async def get_media_assets_for_message(self, chat_id, tg):
        return []

    async def get_smart_message_by_tg_id(self, chat_id, tg):
        return self._origin


class FakeCache:
    def __init__(self):
        self.store = {}
        self.markers = {}
        self.gets: list[str] = []
        self.sets: list[str] = []

    async def get(self, key):
        self.gets.append(key)
        return self.store.get(key)

    async def set(self, key, value):
        self.sets.append(key)
        self.store[key] = value

    async def get_update_marker(self, key, *, ttl_seconds):
        self.gets.append(key)
        return self.markers.get(key)

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.sets.append(key)
        self.markers[key] = payload

    def build_key(self, slug, raw):
        from services.smart_cache import build_key, normalize_text
        return build_key(slug, normalize_text(str(raw)))


class RoutedLLM:
    """Аналитик/валидатор/вербализатор: JSON по шагу + журнал payload'ов."""

    def __init__(self, verdict=None, text="Краткий вывод."):
        self.verdict = verdict or {"factual_verdict": "insufficient_evidence",
                                   "temporal_status": "unknown"}
        self.text = text
        self.steps = []
        self.user_payloads: dict[str, str] = {}
        self.calls = 0

    async def generate(self, messages, **kw):
        self.calls += 1
        step = kw.get("step")
        self.steps.append(step)
        # последний payload шага (повторные прогоны — новые проверки)
        self.user_payloads[str(step)] = messages[1]["content"]
        if step in ("temporal_verdict", "temporal_fallback"):
            return json.dumps(self.verdict, ensure_ascii=False)
        if step == "temporal_validator":
            return json.dumps({"agree": True}, ensure_ascii=False)
        return self.text


class DownAggregator:
    """Все провайдеры недоступны (транспортная ошибка каскада)."""

    async def search(self, q, max_symbols):
        raise sa.AllSearchEnginesFailedException(
            "all search engines failed (tavily → exa → ddg)",
            reason="provider_error")

    async def search_relevant(self, q, max_symbols, **kw):
        await self.search(q, max_symbols)


class ScriptedAggregator:
    """Каскад по скрипту вызовов: исключение или текст выдачи."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[str] = []

    async def search_relevant(self, q, max_symbols, **kw):
        self.calls.append(q)
        item = self.script.pop(0) if self.script else ""
        if isinstance(item, Exception):
            raise item
        return item


async def _envelope(text=CLAIM):
    env, _ = await tf.build_envelope(
        FakeDB(), tf.InputRef(kind="reply", chat_id=CHAT_ID,
                              target_tg_message_id=TARGET_TG,
                              trigger_tg_message_id=TRIGGER_TG))
    return env


def _outcome(**kw):
    base = dict(evidence_map=None, search_text="", queries_attempted=1,
                queries_used=0, refs_collected=0, fetch_errors=0,
                budget_exhausted=False, provider_failures=0,
                empty_results=0, irrelevant_results=0)
    base.update(kw)
    return fsp.RetrievalOutcome(**base)


def _evidence_map(*refs):
    return orch.EvidenceMap(
        refs=tuple(refs), allowlist=tuple(r.evidence_id for r in refs))


def _ref(eid="ev-1", url="https://example.org/a",
         support="Публикация подтверждает утверждение"):
    return orch.EvidenceRef(eid, url, support)


def _service(llm, aggregator=None):
    return FactCheckService(aggregator=aggregator, llm=llm)


def _presentation_from_run(run):
    verdict = orch.CheckedVerdict(
        verdict_text=run.verdict_text or "вывод",
        route="envelope_temporal",
        factual_verdict=run.verdict.factual_verdict,
        reason_code=run.verdict.reason,
        evidence=orch.EvidenceMap(
            refs=tuple(
                orch.EvidenceRef(
                    evidence_id=str(r.get("evidence_id") or ""),
                    url=r.get("url"), support=str(r.get("support") or ""),
                    source_kind=str(r.get("source_kind") or "secondary"))
                for r in (run.evidence_rows or ())),
            allowlist=tuple(str(r.get("evidence_id")) for r in
                            (run.evidence_rows or ()))))
    return fr.render_factcheck(
        orch.build_presentation(verdict), verdict).text


# ── §5.1: таксономия причин в агрегаторе ────────────────────────────────────

class TestAggregatorFailureTaxonomy:
    def _set_engine(self, agg, result):
        async def engine_fn(query, timeout_budget=None):
            if isinstance(result, Exception):
                raise result
            return result
        agg._search_tavily = engine_fn
        agg._search_exa = engine_fn

    def test_timeout_is_not_provider_unavailable(self):
        agg = sa.SearchAggregator(tavily_api_key="t", exa_api_key="")
        self._set_engine(agg, httpx.TimeoutException("read timed out"))
        with pytest.raises(sa.AllSearchEnginesFailedException) as ei:
            asyncio.run(agg.search("q", 100))
        assert ei.value.reason == "timeout"

    def test_empty_results_distinguished(self):
        agg = sa.SearchAggregator(tavily_api_key="t", exa_api_key="")
        self._set_engine(agg, "")
        with pytest.raises(sa.AllSearchEnginesFailedException) as ei:
            asyncio.run(agg.search("q", 100))
        assert ei.value.reason == "empty_results"
        assert ei.value.reason != "provider_error"

    def test_irrelevant_results_distinguished(self):
        agg = sa.SearchAggregator(tavily_api_key="t", exa_api_key="")
        self._set_engine(agg, "Совершенно другая тема про рецепты борща"
                              "\nhttps://x.org/1")
        with pytest.raises(sa.AllSearchEnginesFailedException) as ei:
            asyncio.run(agg.search("заболеваемость молодёжи", 100,
                                   relevance_terms=["заболеваемость",
                                                    "молодёжи"]))
        assert ei.value.reason == "irrelevant_results"

    def test_api_error_is_provider_error(self):
        agg = sa.SearchAggregator(tavily_api_key="t", exa_api_key="")
        self._set_engine(agg, RuntimeError("503 service unavailable"))
        with pytest.raises(sa.AllSearchEnginesFailedException) as ei:
            asyncio.run(agg.search("q", 100))
        assert ei.value.reason == "provider_error"


# ── §5.1/§5.2: classify_retrieval — пусто/нерелевантно ≠ недоступно ─────────

class TestClassifyRetrieval:
    def test_empty_results_not_reported_as_down(self):
        outcome = _outcome(queries_attempted=2, empty_results=2)
        assert classify_retrieval(outcome) == RETRIEVAL_NO_RESULTS
        assert classify_retrieval(outcome) != RETRIEVAL_SEARCH_FAILED

    def test_irrelevant_results_not_reported_as_down(self):
        outcome = _outcome(queries_attempted=3, irrelevant_results=3)
        assert classify_retrieval(outcome) == RETRIEVAL_NO_RESULTS
        # F4: нерелевантная выдача ≠ «самих фактов нет» — класс честно
        # говорит «поиск не дал подходящих», а не «недоступны»
        caveat = fsvc._RETRIEVAL_CAVEAT[RETRIEVAL_NO_RESULTS]
        assert "недоступ" not in caveat.lower()
        assert "не попадать в выдачу" in caveat or "подходящих" in caveat

    def test_provider_failures_only_still_search_failed(self):
        outcome = _outcome(queries_attempted=2, provider_failures=2)
        assert classify_retrieval(outcome) == RETRIEVAL_SEARCH_FAILED

    def test_mixed_failure_and_empty_is_no_results(self):
        outcome = _outcome(queries_attempted=3, provider_failures=1,
                           empty_results=2)
        assert classify_retrieval(outcome) == RETRIEVAL_NO_RESULTS

    def test_used_but_no_refs_is_processing_failed(self):
        outcome = _outcome(queries_attempted=1, queries_used=1,
                           search_text="материалы без ссылок")
        assert classify_retrieval(outcome) == RETRIEVAL_PROCESSING_FAILED

    def test_budget_precedence_kept(self):
        outcome = _outcome(queries_attempted=1, budget_exhausted=True)
        assert classify_retrieval(outcome) == RETRIEVAL_BUDGET

    def test_no_attempts_is_real_insufficiency(self):
        outcome = _outcome(queries_attempted=0)
        assert classify_retrieval(outcome) == RETRIEVAL_INSUFFICIENT


# ── §5.1: planner — частичный успех сохраняется, причины различаются ────────

class TestPlannerPartialAndCauses:
    @pytest.mark.asyncio
    async def test_first_down_second_works_evidence_used(self):
        """F2: первый запрос упал на провайдерах, второй дал доказательства
        — доказательства используются, класс OK."""
        plan = fsp.RetrievalPlan(
            queries=(fsp.SearchQuery(text="96 линий PCIe чипсет",
                                     intent="entity_check"),
                     fsp.SearchQuery(text="чипсет процессор линии PCIe",
                                     intent="entity_check")),
            needs_web=True, needs_primary_fetch=False,
            dropped_privacy=(), claim_text=CLAIM)
        agg = ScriptedAggregator([
            sa.AllSearchEnginesFailedException("down", reason="provider_error"),
            ("Линии PCIe у устройства\n"
             "40 линий от процессора, 56 от чипсета\n"
             "https://example.org/pcie"),
        ])
        outcome = await fsp.run_retrieval(plan, aggregator=agg)
        assert outcome.queries_used == 1
        assert outcome.provider_failures == 1
        assert outcome.evidence_map is not None
        assert outcome.evidence_map.refs
        assert classify_retrieval(outcome) == "ok"

    @pytest.mark.asyncio
    async def test_partial_evidence_kept_on_next_failure(self):
        """F5: доказательства первого запроса сохраняются при ошибке
        следующего; не выбрасываются из-за сбоя провайдера."""
        plan = fsp.RetrievalPlan(
            queries=(fsp.SearchQuery(text="96 линий PCIe чипсет",
                                     intent="entity_check"),
                     fsp.SearchQuery(text="40 56 линии итог",
                                     intent="numeric_verification")),
            needs_web=True, needs_primary_fetch=False,
            dropped_privacy=(), claim_text=CLAIM)
        agg = ScriptedAggregator([
            ("Линии PCIe: 40 от CPU + 56 от чипсета\n"
             "https://example.org/pcie"),
            sa.AllSearchEnginesFailedException("down", reason="provider_error"),
        ])
        outcome = await fsp.run_retrieval(plan, aggregator=agg)
        assert outcome.refs_collected >= 1
        assert outcome.provider_failures == 1
        assert classify_retrieval(outcome) == "ok"


# ── §1/§2.4: анализ продолжается без внешнего evidence ─────────────────────

class TestEmptyEvidenceAnalysisContinues:
    @pytest.mark.asyncio
    async def test_all_providers_down_analyst_still_runs(self):
        """F1/F22: все провайдеры недоступны — существующий аналитический
        verdict-вызов выполняется (не подменяется серверным статусом)."""
        llm = RoutedLLM()
        await _service(llm, DownAggregator()).check_claim_envelope(
            await _envelope())
        assert llm.steps.count("temporal_verdict") == 1
        payload = llm.user_payloads["temporal_verdict"]
        # payload несёт утверждение + статус поиска + разрешение анализа
        assert "<claim>" in payload and "96 линий" in payload
        assert "<analysis_context>" in payload
        assert "поисковые сервисы не ответили" in payload
        assert "математическая проверка" in payload
        assert "basis" in payload
        assert "<evidence>" not in payload

    @pytest.mark.asyncio
    async def test_chat_context_reaches_analyst(self):
        """F11: доступный контекст беседы (пользовательские данные)
        доходит до аналитика вместе с рамкой анализа."""
        llm = RoutedLLM()
        await _service(llm, DownAggregator()).check_claim_envelope(
            await _envelope(),
            chat_context="<chat_context>спор про линии PCIe у устройства"
                         "</chat_context>")
        payload = llm.user_payloads["temporal_verdict"]
        assert "спор про линии PCIe" in payload

    @pytest.mark.asyncio
    async def test_math_verdict_with_basis_stands(self):
        """F7/F12: расчёт по явно заданным числам с помеченным основанием —
        положительный вердикт НЕ понижается сервером из-за отсутствия
        интернета; происхождение вывода остаётся в uncertainty."""
        llm = RoutedLLM(verdict={
            "factual_verdict": "refuted", "temporal_status": "current",
            "parts": [{"part_id": "p1",
                       "text": "40 + 56 = 96 — арифметика сходится, но 96 "
                               "заявлено «у устройства»: линия чипсета и "
                               "линия CPU не складываются в доступные "
                               "устройству",
                       "factual_verdict": "refuted"}],
            "uncertainty": {"basis": "внутренняя проверка: арифметика "
                                     "заданных чисел"},
        })
        run = await _service(llm, DownAggregator()).check_claim_envelope(
            await _envelope())
        assert run.verdict.factual_verdict == "refuted"
        assert "basis" in (run.verdict.uncertainty or {})
        # выдуманных ссылок нет (evidence не существовал)
        assert run.verdict.evidence_refs == ()

    @pytest.mark.asyncio
    async def test_unbacked_positive_downgraded(self):
        """F13/§2.4-граница: «модель вспомнила цифру → подтверждено» без
        basis-пометки и без evidence — честная неопределённость, не
        supported; содержание (части) сохраняется."""
        llm = RoutedLLM(verdict={
            "factual_verdict": "supported", "temporal_status": "current",
            "evidence_refs": ["ev-1"],
        })
        run = await _service(llm, DownAggregator()).check_claim_envelope(
            await _envelope())
        assert run.verdict.factual_verdict == "insufficient_evidence"
        assert "unbacked_positive" in (run.verdict.uncertainty or {})
        assert run.verdict.evidence_refs == ()

    @pytest.mark.asyncio
    async def test_invented_evidence_refs_filtered(self):
        """F10/§2.5: ссылки на несуществующие ev-ID не становятся cited
        evidence; выдуманный источник невозможен."""
        llm = RoutedLLM(verdict={
            "factual_verdict": "supported",
            "evidence_refs": ["ev-1", "ev-9"],
            "parts": [{"part_id": "p1", "text": "x",
                       "factual_verdict": "supported",
                       "evidence_refs": ["ev-2"]}],
            "uncertainty": {"basis": "внутренняя проверка: логика"},
        })
        run = await _service(llm, DownAggregator()).check_claim_envelope(
            await _envelope())
        assert run.verdict.evidence_refs == ()
        for part in run.verdict.parts:
            assert not part.get("evidence_refs")

    @pytest.mark.asyncio
    async def test_contradiction_explained_not_uncertain(self):
        """F8/F12: внутреннее противоречие — положительный (отрицательный)
        вердикт с basis не объявляется «неопределённым»."""
        llm = RoutedLLM(verdict={
            "factual_verdict": "mixed",
            "parts": [{"part_id": "p1", "text": "итог 96 противоречит "
                                                "условию",
                       "factual_verdict": "refuted"}],
            "uncertainty": {"basis": "внутренняя проверка: противоречие "
                                     "частей утверждения"},
        })
        run = await _service(llm, DownAggregator()).check_claim_envelope(
            await _envelope())
        assert run.verdict.factual_verdict == "mixed"
        part = run.verdict.parts[0]
        assert part["factual_verdict"] == "refuted"

    @pytest.mark.asyncio
    async def test_principle_vs_unverified_spec_separated(self):
        """F9: известный принцип (basis) подтверждается, неподтверждаемая
        спецификация остаётся insufficient с пояснением, а не supported."""
        llm = RoutedLLM(verdict={
            "factual_verdict": "mixed",
            "parts": [
                {"part_id": "p1", "text": "линии CPU и чипсета — разные "
                                          "группы",
                 "factual_verdict": "supported",
                 "note": "известный принцип PCIe"},
                {"part_id": "p2", "text": "ровно 96 у устройства",
                 "factual_verdict": "insufficient_evidence",
                 "note": "конкретная спецификация устройства неизвестна "
                         "без внешних источников"},
            ],
            "uncertainty": {"basis": "внутренняя проверка: логика групп "
                                     "линий"},
        })
        run = await _service(llm, DownAggregator()).check_claim_envelope(
            await _envelope())
        assert run.verdict.factual_verdict == "mixed"
        verdicts = {p["part_id"]: p["factual_verdict"]
                    for p in run.verdict.parts}
        assert verdicts == {"p1": "supported", "p2": "insufficient_evidence"}

    @pytest.mark.asyncio
    async def test_no_confirmation_is_not_technical_failure(self):
        """F6: поиск дал доказательства, но подтверждений нет — это
        содержательный «insufficient», а не технический заголовок сбоя."""
        outcome = _outcome(
            queries_attempted=1, queries_used=1, refs_collected=1,
            search_text="выдача",
            evidence_map=_evidence_map(_ref()))
        llm = RoutedLLM(verdict={"factual_verdict": "insufficient_evidence",
                                 "temporal_status": "unknown"})
        run = await _service(llm).check_claim_envelope(await _envelope(),
                                                       retrieval=outcome)
        assert run.verdict.factual_verdict == "insufficient_evidence"
        assert run.verdict.reason is None
        assert run.fallback_used is False
        markup = _presentation_from_run(run).lower()
        assert "недостаточно данных" in markup
        assert "проверка не завершена" not in markup

    @pytest.mark.asyncio
    async def test_technical_failure_keeps_honest_headline(self):
        """F13: анализа нет (аналитик вернул insufficient без содержания)
        при техническом сбое поиска — заголовок честно называет сбой."""
        outcome = _outcome(queries_attempted=2, provider_failures=2)
        llm = RoutedLLM(verdict={"factual_verdict": "insufficient_evidence",
                                 "temporal_status": "unknown"})
        run = await _service(llm).check_claim_envelope(await _envelope(),
                                                       retrieval=outcome)
        assert run.verdict.reason == "provider_unavailable"
        markup = _presentation_from_run(run)
        assert "Проверка не завершена: поиск недоступен" in markup

    @pytest.mark.asyncio
    async def test_substantive_verdict_no_technical_headline(self):
        """F25/§7.3: содержательный разбор без поиска НЕ сводится к
        сообщению о сбое (технический заголовок снят, причина — в
        оговорке)."""
        outcome = _outcome(queries_attempted=2, provider_failures=2)
        llm = RoutedLLM(verdict={
            "factual_verdict": "mixed",
            "parts": [{"part_id": "p1", "text": "арифметика не сходится",
                       "factual_verdict": "refuted"}],
            "uncertainty": {"basis": "внутренняя проверка: расчёт"},
        })
        run = await _service(llm).check_claim_envelope(await _envelope(),
                                                       retrieval=outcome)
        assert run.verdict.reason is None
        assert "retrieval_state" in (run.verdict.uncertainty or {})
        markup = _presentation_from_run(run)
        assert "Проверка не завершена" not in markup
        assert "подтверждается частично" in markup.lower()

    @pytest.mark.asyncio
    async def test_no_results_state_not_called_down(self):
        """F3/F4 (сервисный путь): пустая/нерелевантная выдача — статус
        поиска в payload analyst'а говорит «подходящих не дал», а не
        «поисковики недоступны»."""
        outcome = _outcome(queries_attempted=2, irrelevant_results=2)
        llm = RoutedLLM()
        run = await _service(llm).check_claim_envelope(await _envelope(),
                                                       retrieval=outcome)
        payload = llm.user_payloads["temporal_verdict"]
        assert "подходящих материалов не дали" in payload \
            or "нерелевантная выдача" in payload
        assert "не ответили" not in payload
        assert run.verdict.uncertainty.get("retrieval_state") == \
            fsvc._RETRIEVAL_CAVEAT[RETRIEVAL_NO_RESULTS]

    @pytest.mark.asyncio
    async def test_empty_results_state_in_payload(self):
        outcome = _outcome(queries_attempted=2, empty_results=2)
        llm = RoutedLLM()
        await _service(llm).check_claim_envelope(await _envelope(),
                                                 retrieval=outcome)
        payload = llm.user_payloads["temporal_verdict"]
        assert "поисковые сервисы не ответили" not in payload
        assert "<analysis_context>" in payload


# ── §7: вербализация ────────────────────────────────────────────────────────

class TestVerbalization:
    @pytest.mark.asyncio
    async def test_no_analysis_short_limit_note(self):
        """§7.2: анализа нет → вербализатор получает короткую границу
        (limit_note), а не приглашение к сочинению."""
        llm = RoutedLLM(verdict={"factual_verdict": "insufficient_evidence",
                                 "temporal_status": "unknown"})
        await _service(llm, DownAggregator()).check_claim_envelope(
            await _envelope())
        verbalize_payload = json.loads(
            llm.user_payloads["temporal_verbalize"]
            .split("ВЕРДИКТ (JSON):\n", 1)[1])
        assert "limit_note" in verbalize_payload
        assert "коротко" in verbalize_payload["limit_note"]

    @pytest.mark.asyncio
    async def test_substantive_result_passes_through(self):
        """§7.1: содержательный разбор передаётся вербализатору целиком —
        части, оговорки, вердикт; универсального лимита нет."""
        llm = RoutedLLM(verdict={
            "factual_verdict": "mixed",
            "parts": [{"part_id": "p1", "text": "арифметика не сходится",
                       "factual_verdict": "refuted"}],
            "uncertainty": {"basis": "внутренняя проверка: расчёт",
                            "note": "поиск не удался — проверено без веб"},
        })
        await _service(llm, DownAggregator()).check_claim_envelope(
            await _envelope())
        verbalize_payload = json.loads(
            llm.user_payloads["temporal_verbalize"]
            .split("ВЕРДИКТ (JSON):\n", 1)[1])
        assert "limit_note" not in verbalize_payload
        assert verbalize_payload["verdict"] == \
            "данные противоречивы — утверждение верно лишь частично"
        assert verbalize_payload["parts"]
        assert verbalize_payload["caveats"]

    @pytest.mark.asyncio
    async def test_renderer_no_duplicate_technical_notice(self):
        """F27/§7.3: при техническом заголовке отдельная концовка с тем же
        ограничением не добавляется."""
        verdict = orch.CheckedVerdict(
            verdict_text="Проверку не удалось выполнить: поисковые сервисы "
                         "не ответили.",
            route="envelope_temporal",
            factual_verdict="insufficient_evidence",
            reason_code="provider_unavailable")
        markup = fr.render_factcheck(
            orch.build_presentation(verdict), verdict).text
        assert "Проверка не завершена: поиск недоступен" in markup
        assert "Поисковые сервисы не ответили" not in fr.visible_text(markup)

    @pytest.mark.asyncio
    async def test_renderer_body_not_regrouped(self):
        """§7.4: тело вербализатора не перекладывается в обязательный
        список 2–4 пунктов."""
        body = ("Первое содержательное предложение. Второе предложение. "
                "Третье предложение. Четвёртое. Пятое. Шестое. Седьмое.")
        p = fr.render_factcheck(
            orch.FactcheckPresentation(text=body, links=(),
                                       reply_to_message_id=1,
                                       parse_mode=None, notice=""), None)
        assert p.text == body


# ── §6: кеш вердиктов удалён ────────────────────────────────────────────────

class TestVerdictCacheRemoved:
    def test_cache_machinery_gone(self):
        """F17 (механика): функции вердикт-кеша удалены — второго скрытого
        read/write-пути нет."""
        for name in ("build_temporal_cache_key", "read_temporal_cache",
                     "write_temporal_cache",
                     "temporal_cache_key_with_bucket", "cache_components",
                     "freshness_bucket_for", "freshness_ttl_seconds"):
            assert not hasattr(tf, name), f"{name} должен быть удалён"
        assert not hasattr(orch, "write_legacy_cache")
        assert not hasattr(orch, "_v2_cache_input")

    @pytest.mark.asyncio
    async def test_repeat_claim_runs_fresh(self):
        """F14: повторный Fact-check того же тезиса — новый аналитический
        вызов, не выдача старого ответа."""
        llm = RoutedLLM()
        service = _service(llm, DownAggregator())
        env = await _envelope()
        await service.check_claim_envelope(env)
        await service.check_claim_envelope(env)
        assert llm.steps.count("temporal_verdict") == 2

    @pytest.mark.asyncio
    async def test_old_error_not_served_after_recovery(self):
        """F16: первый прогон — техническая ошибка; после восстановления
        провайдеров следующий прогон использует доказательства, а не
        старый результат."""
        llm = RoutedLLM(verdict={"factual_verdict": "supported",
                                 "temporal_status": "current"})
        service = _service(llm, DownAggregator())
        env = await _envelope()
        run1 = await service.check_claim_envelope(env)
        assert run1.verdict.factual_verdict == "insufficient_evidence"
        # провайдеры восстановились (выдача с URL → evidence)
        outcome = _outcome(
            queries_attempted=1, queries_used=1, refs_collected=1,
            search_text="выдача с URL",
            evidence_map=_evidence_map(_ref()))
        run2 = await service.check_claim_envelope(env, retrieval=outcome)
        # второй прогон — свежий вердикт текущего прогона (не старая ошибка)
        assert run2.verdict.factual_verdict == "supported"
        assert llm.steps.count("temporal_verdict") == 2
        # второй прогон получил <evidence> — доказательства дошли до analyst
        assert "<evidence>" in llm.user_payloads["temporal_verdict"]

    @pytest.mark.asyncio
    async def test_legacy_branch_does_not_read_verdict_cache(self):
        """F17: legacy-ветка не читает и не пишет SmartCache-вердикты
        (даже если под ключом что-то осталось от прежнего механизма)."""
        cache = FakeCache()
        legacy_key = cache.build_key("factcheck", CLAIM)
        cache.store[legacy_key] = "Старый вердикт из кеша"
        svc = SimpleNamespace(
            check_claim=AsyncMock(return_value="Свежий вердикт"))
        req = orch.FactcheckRequest(
            chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
            target_tg_message_id=TARGET_TG, target_text=CLAIM,
            kind="reply")
        verdict = await orch._run_legacy_branch(req, svc, "")
        assert verdict.verdict_text == "Свежий вердикт"
        assert verdict.cache_hit is False
        assert cache.gets == [] and cache.sets == []
        svc.check_claim.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_envelope_branch_does_not_write_cache(self):
        cache = FakeCache()
        svc = SimpleNamespace(
            check_claim_envelope=AsyncMock(return_value=SimpleNamespace(
                verdict=tf.TemporalVerdict(
                    factual_verdict="insufficient_evidence",
                    temporal_status="unknown", evaluated_period={},
                    assessment_mode="contextual", as_of=1760000000),
                verdict_text="Свежий вердикт", evidence_rows=(),
                fallback_used=False)))
        req = orch.FactcheckRequest(
            chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
            target_tg_message_id=TARGET_TG, target_text=CLAIM,
            kind="reply")
        env = await _envelope()
        verdict = await orch._run_envelope_branch(
            req, svc, None, None, env, "", tf, __import__(
                "services.mca_gates", fromlist=["mca_gates"]))
        assert verdict.cache_hit is False
        assert cache.gets == [] and cache.sets == []
        assert cache.markers == {}

    @pytest.mark.asyncio
    async def test_single_delivery_per_run(self):
        """F19: один прогон → одна отправка (двойной доставки нет)."""
        db = FakeDB()
        calls = {"n": 0}

        class SpyService:
            async def check_claim(self, *a, **kw):
                calls["n"] += 1
                return "Свежий вердикт"

        class FakeBot:
            def __init__(self):
                self.sent = []

            async def send_message(self, chat_id, text, **kw):
                self.sent.append(text)
                return SimpleNamespace(message_id=99)

        class _Pool:
            async def try_acquire(self, chat_id, timeout=None):
                return SimpleNamespace(release=lambda: None)

        class _Typing:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        async def fake_evaluate(db_, chat_id, **kwargs):
            import services.factcheck_suitability as fsg
            item = fsg.ClaimItem(
                text=CLAIM, claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
                verifiable=True, source="literal")
            return fsg.SuitabilityDecision(
                decision=fsg.DECISION_CHECKABLE,
                claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
                claim_items=(item,), scope="web",
                reason_code="obvious_checkable_predicate", confidence=0.8,
                target_ref={}), None

        import services.factcheck_suitability as fsg
        orig_eval = fsg.evaluate_with_expansion
        orig_pool = orch.get_smartmodule_concurrency_pool
        orig_typing = orch.typing_active
        orig_gates = None
        fsg.evaluate_with_expansion = fake_evaluate
        orch.get_smartmodule_concurrency_pool = lambda: _Pool()
        orch.typing_active = _Typing
        try:
            import services.mca_gates as mca_gates
            orig_gates = mca_gates.temporal_factcheck_enabled
            mca_gates.temporal_factcheck_enabled = lambda: False
            bot = FakeBot()
            await orch.run_factcheck(
                orch.FactcheckRequest(
                    chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
                    target_tg_message_id=TARGET_TG, target_text=CLAIM,
                    kind="reply"),
                service=SpyService(), db=db, bot=bot, cache=FakeCache())
            assert calls["n"] == 1
            assert len(bot.sent) == 1
        finally:
            fsg.evaluate_with_expansion = orig_eval
            orch.get_smartmodule_concurrency_pool = orig_pool
            orch.typing_active = orig_typing
            if orig_gates is not None:
                mca_gates.temporal_factcheck_enabled = orig_gates


# ── §9.4: неблокирующие проверки ────────────────────────────────────────────

class TestNonBlockingDegradation:
    @pytest.mark.asyncio
    async def test_validator_failure_keeps_run(self):
        """F20/F21: сбой validator'а не уничтожает результат аналитика и
        полученные доказательства."""
        outcome = _outcome(
            queries_attempted=1, queries_used=1, refs_collected=1,
            search_text="выдача",
            evidence_map=_evidence_map(_ref()))

        class BrokenValidatorLLM:
            def __init__(self):
                self.steps = []

            async def generate(self, messages, **kw):
                self.steps.append(kw.get("step"))
                if kw.get("step") == "temporal_validator":
                    return "не JSON {{{"
                if kw.get("step") == "temporal_fallback":
                    return json.dumps({
                        "factual_verdict": "supported",
                        "evidence_refs": ["ev-1"]})
                return json.dumps({
                    "factual_verdict": "supported",
                    "evidence_refs": ["ev-1"]})

        llm = BrokenValidatorLLM()
        run = await _service(llm).check_claim_envelope(await _envelope(),
                                                       retrieval=outcome)
        assert run.verdict.factual_verdict == "supported"
        assert run.verdict.evidence_refs == ("ev-1",)
        assert run.evidence_rows
        assert "temporal_fallback" in llm.steps

    @pytest.mark.asyncio
    async def test_invalid_input_still_rejected(self):
        """F24/§4.2: обязательные защитные проверки не обходятся —
        невалидный вход в существующем gate-контуре не запускает проверку
        (no-claim/пустой ответ без вызова аналитика)."""
        llm = RoutedLLM(verdict={"factual_verdict": "supported"})
        service = _service(llm, DownAggregator())
        env = await _envelope(text="лол")
        run = await service.check_claim_envelope(env)
        # спам-цель не получает фиктивного положительного вердикта:
        # suitability/entry-контур handler'а отсеивает — на сервисном
        # уровне проверяем honest-verdict и отсутствие выдуманных ссылок
        assert run.verdict.factual_verdict != "supported" \
            or run.verdict.evidence_refs == ()
