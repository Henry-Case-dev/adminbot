"""P0-FACTCHECK (owner 24.10.2026 §3.3–§3.7/§9): FC-01..FC-09 на фикстурах.

TEST-LIFECYCLE: CONTRACT owner=P0-FACTCHECK/FC-01..FC-09
Проверяются пользовательские инварианты, а не детали реализации:

* FC-01 составная публикация → несколько запросов по своим частям + части
  в вердикте;
* FC-02 пересказ другими словами проходит лексический фильтр (морфология);
* FC-03 недоступный первоисточник не обнуляет пригодные вторичные ссылки;
* FC-04 один провайдер упал → следующий даёт результат;
* FC-05 бюджет — техническое ограничение (reason/заголовок), не «нет данных»;
* FC-06 пустой EvidenceMap не даёт опровержения;
* FC-07 частичное подтверждение не превращается в «ничего неизвестно»;
* FC-08 тезис в подписи и на изображении (текст OCR идёт в анализ);
* FC-09 кешированный старый вердикт не скрывает новую проверку.

Полностью офлайн: провайдеры/LLM/Vision — фейки, без сети и без прод-чатов.
"""
import asyncio
import dataclasses
import json

import pytest

from config.settings import settings
from services import factcheck_planner as fsp
from services import factcheck_suitability as fsg
from services import factcheck_orchestrator as orch
from services import factcheck_renderer as fr
from services import search_aggregator as sa
from services.factcheck_service import (
    ClaimMediaMaterial,
    RETRIEVAL_BUDGET,
    RETRIEVAL_INSUFFICIENT,
    RETRIEVAL_NOT_RUN,
    RETRIEVAL_OK,
    RETRIEVAL_PROCESSING_FAILED,
    RETRIEVAL_SEARCH_FAILED,
    FactCheckService,
    _server_parts,
    classify_retrieval,
    load_claim_media,
)
from services.search_aggregator import (
    AllSearchEnginesFailedException,
    is_relevant_result,
)
from services import temporal_factcheck as tf

CHAT_ID = -100777
TARGET_TG = 7700
TRIGGER_TG = 7701

COMPOSITE = (
    "⚡️ В Telegram добавят ИИ-агентов: Claude и ChatGPT подключат через API. "
    "Функция появится в сборке 283365 на macOS 13.1.0. "
    "Дуров убил Claude Code.")


# ── Фейки (без сети/БД/LLM) ─────────────────────────────────────────────────

class FakeDB:
    def __init__(self, rows=None, origin_row=None):
        self._origin = origin_row
        self.runs = []

    async def get_smart_message_origin_block(self, chat_id, tg):
        if self._origin is None:
            raise RuntimeError("no origin")
        return dict(self._origin)

    async def get_media_assets_for_message(self, chat_id, tg):
        return []

    async def get_smart_message_by_tg_id(self, chat_id, tg):
        return self._origin


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
    id = 861000000

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("M", (), {"message_id": 99})()

    async def send_chat_action(self, chat_id, action, **kw):
        return True


class FakeService:
    def __init__(self, aggregator=None, verdict="Проверено."):
        self.aggregator = aggregator
        self.llm = None
        self.verdict = verdict
        self.check_claim_calls = []

    async def check_claim(self, target_text, user_hint, forward_source, *,
                          chat_id=None, chat_context=None,
                          search_results=None):
        self.check_claim_calls.append({
            "target_text": target_text, "search_results": search_results})
        return self.verdict


class _Pool:
    async def try_acquire(self, chat_id, timeout=None):
        return type("P", (), {"release": lambda self: None})()


class _Typing:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _decision(claim):
    item = fsg.ClaimItem(text=claim,
                         claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
                         verifiable=True, source="literal")
    return fsg.SuitabilityDecision(
        decision=fsg.DECISION_CHECKABLE,
        claim_type=fsg.CHECKABLE_FACTUAL_CLAIM, claim_items=(item,),
        scope="web", reason_code="obvious_checkable_predicate",
        confidence=0.8, target_ref={})


def _origin_row(text):
    return {"text": text, "caption": None, "origin_type": None,
            "origin_sent_at": None, "sent_at": 1792200000,
            "current_revision": None, "content_hash": None,
            "origin_sender_user_id": None, "origin_chat_id": None,
            "origin_display_name": None, "author_name": None,
            "forward_source": None}


@pytest.fixture
def planner_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


# ── FC-01: составная публикация → запросы по частям ─────────────────────────

class TestFC01Composite:
    def test_each_claim_part_gets_its_own_query(self, planner_on):
        plan = fsp.build_retrieval_plan(_decision(COMPOSITE),
                                        claim_text=COMPOSITE)
        assert plan is not None
        assert 2 <= len(plan.queries) <= 3          # бюджет не увеличен
        joined = " ".join(q.text.lower() for q in plan.queries)
        assert "telegram" in joined and "claude" in joined
        assert "283365" in joined                    # версия/сборка в запросе
        # не один общий запрос: части покрыты разными формулировками
        assert len({q.text.lower() for q in plan.queries}) > 1

    def test_server_parts_when_model_silent(self):
        env, _ = await_envelope(COMPOSITE)
        parts = _server_parts(env, [])
        assert len(parts) >= 2
        assert all(p["factual_verdict"] == "insufficient_evidence"
                   for p in parts)                   # без доказательств — не supported
        assert {p["part_id"] for p in parts} >= {"p1", "p2"}


def await_envelope(text):
    import asyncio
    return asyncio.run(_envelope(text))


async def _envelope(text):
    return await tf.build_envelope(
        FakeDB(origin_row=_origin_row(text)),
        tf.InputRef(kind="reply", chat_id=CHAT_ID,
                    target_tg_message_id=TARGET_TG,
                    trigger_tg_message_id=TRIGGER_TG))


# ── FC-02: другие слова в источнике ─────────────────────────────────────────

class TestFC02Morphology:
    def test_relevant_publication_with_other_words_passes(self, planner_on):
        claim = "врачи зафиксировали всплеск заболеваемости среди молодёжи"
        plan = fsp.build_retrieval_plan(_decision(claim), claim_text=claim)
        assert plan is not None
        terms = fsp._claim_terms(plan.queries[0].text, limit=10)
        # пересказ другими словами: «заболевших» вместо «заболеваемости»,
        # «рост» вместо «всплеск» (generic-синоним уже в запросе)
        hits = ("Резкий рост заболевших среди молодых людей\n"
                "Медики сообщили о увеличении числа случаев\n"
                "https://example.org/health")
        assert is_relevant_result(hits, terms) is True

    def test_single_word_match_is_not_relevance(self):
        terms = ["telegram", "агентов", "claude", "chatgpt", "подключат"]
        off_topic = ("Утечка исходников Claude Code\n"
                     "Boris Cherny рассказал о расследовании утечки\n"
                     "https://example.org/leak")
        assert is_relevant_result(off_topic, terms) is False


# ── FC-03/FC-04: вторичные источники и каскад провайдеров ───────────────────

class _Agg:
    def __init__(self, text="", fail=False):
        self.text = text
        self.fail = fail
        self.calls = []

    async def search(self, query, max_symbols):
        self.calls.append(query)
        if self.fail:
            raise AllSearchEnginesFailedException("down")
        return self.text


SECONDARY = ("Вторичная публикация о событии Telegram\n"
             "Claude и ChatGPT подключат через API силами Telegram\n"
             "https://news.example.org/a")


class TestFC03SecondarySources:
    @pytest.mark.asyncio
    async def test_primary_unavailable_keeps_secondary(self, planner_on):
        plan = fsp.build_retrieval_plan(_decision(COMPOSITE),
                                        claim_text=COMPOSITE)
        agg = _Agg(SECONDARY)

        async def broken_fetch(url, **kw):
            raise RuntimeError("primary down")

        outcome = await fsp.run_retrieval(plan, aggregator=agg,
                                          fetch_text=broken_fetch)
        assert outcome.evidence_map is not None
        assert outcome.fetch_errors >= 1                 # первоисточник упал
        assert classify_retrieval(outcome) == RETRIEVAL_OK
        refs = outcome.evidence_map.refs
        assert refs and all(r.url for r in refs)         # ссылки проверяемы
        rows = tf.evidence_rows_from_refs(refs)
        assert rows and rows[0]["url"]


class TestFC04ProviderCascade:
    @pytest.mark.asyncio
    async def test_first_provider_down_second_returns(self, monkeypatch):
        agg = sa.SearchAggregator(tavily_api_key="t", exa_api_key="e")

        async def boom(query):
            raise RuntimeError("tavily 503")

        async def ok(query):
            return ("Публикация по теме\nтекст подтверждения\n"
                    "https://exa.example.org/1")

        monkeypatch.setattr(agg, "_search_tavily", boom)
        monkeypatch.setattr(agg, "_search_exa", ok)
        out = await agg.search_relevant(
            "составная новость telegram claude", 4000,
            relevance_terms=["публикация", "подтверждения"])
        assert "exa.example.org/1" in out


# ── FC-05/FC-06: бюджет и пустой EvidenceMap ────────────────────────────────

class TestFC05Budget:
    def test_budget_class_has_technical_reason(self):
        outcome = fsp.RetrievalOutcome(
            evidence_map=None, search_text="", queries_attempted=1,
            queries_used=0, refs_collected=0, fetch_errors=0,
            budget_exhausted=True, provider_failures=0)
        assert classify_retrieval(outcome) == RETRIEVAL_BUDGET
        verdict = orch.CheckedVerdict(
            verdict_text="Проверку прервал лимит времени.",
            route="envelope_temporal",
            factual_verdict="insufficient_evidence",
            reason_code="deadline_exceeded")
        markup = fr.render_factcheck(
            orch.build_presentation(verdict), verdict).text
        assert "истёк лимит времени" in markup
        assert "Недостаточно данных для проверки" not in markup
        assert "лимит" in fr.visible_text(markup)

    @pytest.mark.asyncio
    async def test_budget_exhausted_marks_outcome(self, planner_on):
        plan = fsp.build_retrieval_plan(_decision(COMPOSITE),
                                        claim_text=COMPOSITE)
        assert len(plan.queries) >= 2

        class Slow:
            async def search(self, q, max_symbols):
                import asyncio
                await asyncio.sleep(0.05)
                return SECONDARY

        outcome = await fsp.run_retrieval(plan, aggregator=Slow(),
                                          budget_seconds=0.01)
        assert outcome.budget_exhausted is True


class TestFC06EmptyEvidence:
    @pytest.mark.asyncio
    async def test_empty_evidence_never_becomes_refuted(self):
        outcome = fsp.RetrievalOutcome(
            evidence_map=None, search_text="", queries_attempted=0,
            queries_used=0, refs_collected=0, fetch_errors=0,
            budget_exhausted=False)
        # поиск был, но ничего не дал по существу — это реальная
        # недостаточность доказательств, а не технический сбой
        assert classify_retrieval(outcome) == RETRIEVAL_INSUFFICIENT
        payload = {"factual_verdict": "insufficient_evidence",
                   "temporal_status": "unknown"}
        env, _ = await tf.build_envelope(
            FakeDB(origin_row=_origin_row(COMPOSITE)),
            tf.InputRef(kind="reply", chat_id=CHAT_ID,
                        target_tg_message_id=TARGET_TG,
                        trigger_tg_message_id=TRIGGER_TG))
        verdict = tf.verdict_from_payload(payload, env, allowed_refs=None)
        assert verdict.factual_verdict != "refuted"

    def test_processing_failure_is_technical_not_absence(self):
        outcome = fsp.RetrievalOutcome(
            evidence_map=None, search_text="нашли текст без ссылок",
            queries_attempted=1, queries_used=1, refs_collected=0,
            fetch_errors=0, budget_exhausted=False)
        assert classify_retrieval(outcome) == RETRIEVAL_PROCESSING_FAILED
        failed = fsp.RetrievalOutcome(
            evidence_map=None, search_text="", queries_attempted=2,
            queries_used=0, refs_collected=0, fetch_errors=0,
            budget_exhausted=False, provider_failures=2)
        assert classify_retrieval(failed) == RETRIEVAL_SEARCH_FAILED


def _run(coro):
    """Мини-исполнитель корутины без pytest-asyncio (для sync-тестов)."""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)




# ── FC-07: частичное подтверждение ──────────────────────────────────────────

class TestFC07Partial:
    def test_mixed_not_hidden_by_insufficient_title(self):
        verdict = orch.CheckedVerdict(
            verdict_text="Первая часть подтверждается, вторая — нет.",
            route="envelope_temporal", factual_verdict="mixed",
            parts=(
                {"part_id": "p1", "text": "функция появится",
                 "factual_verdict": "supported",
                 "evidence_refs": ["ev-1"]},
                {"part_id": "p2", "text": "Дуров убил Claude Code",
                 "factual_verdict": "insufficient_evidence"},
            ),
            evidence=orch.EvidenceMap(
                refs=(orch.EvidenceRef(
                    evidence_id="ev-1", url="https://news.example.org/a",
                    support="функция подтверждена"),),
                allowlist=("ev-1",)))
        markup = fr.render_factcheck(
            orch.build_presentation(verdict), verdict).text
        assert "<b>Подтверждается частично</b>" in markup
        assert "По утверждениям:" in markup
        assert "подтверждается" in markup and "данных недостаточно" in markup
        assert "проверяемой ссылки нет" in fr.visible_text(markup)


# ── FC-08: подпись + изображение ────────────────────────────────────────────

class TestFC08Image:
    @pytest.mark.asyncio
    async def test_ocr_text_goes_into_analysis_material(self):
        async def fake_render(db, *, chat_id, tg_message_id):
            return {"caption": "В Telegram добавят ИИ-агентов",
                    "untrusted_ocr_texts": [
                        "Сборка 283365 · macOS 13.1.0 · Claude, ChatGPT API"],
                    "lines": ["Подпись отправителя: ...", "Текст на изображении"]}

        media = await load_claim_media(FakeDB(), CHAT_ID, TARGET_TG,
                                       render_async=fake_render)
        assert media.image_present and media.image_analyzed
        assert "283365" in media.text_suffix
        assert "macos" in media.text_suffix.lower()
        assert media.caption                      # подпись не потеряна

    @pytest.mark.asyncio
    async def test_not_analyzed_is_honest_and_caption_kept(self):
        async def fake_render(db, *, chat_id, tg_message_id):
            return {"caption": "Подпись с тезисом", "knowledge_time": None,
                    "untrusted_ocr_texts": [],
                    "lines": ["изображение, содержание ещё не распознано"]}

        media = await load_claim_media(FakeDB(), CHAT_ID, TARGET_TG,
                                       render_async=fake_render)
        assert media.image_not_analyzed is True
        assert media.text_suffix == ""
        assert media.caption == "Подпись с тезисом"
        assert "не готово" in media.notice()

    @pytest.mark.asyncio
    async def test_orchestrator_feeds_ocr_into_claim(self, monkeypatch,
                                                    planner_on):
        captured = {}

        async def fake_evaluate(db_, chat_id, **kwargs):
            captured["claim"] = kwargs.get("claim_text")
            return _decision(kwargs.get("claim_text") or COMPOSITE), None

        monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_evaluate)
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_enabled", lambda: False)
        monkeypatch.setattr(orch, "get_smartmodule_concurrency_pool",
                            lambda: _Pool())
        monkeypatch.setattr(orch, "typing_active", _Typing)

        async def fake_media(db, chat_id, tg, **kw):
            return ClaimMediaMaterial(
                text_suffix="Текст с изображения (OCR):\nсборка 283365",
                image_present=True, image_analyzed=True, ocr_chars=17,
                caption="В Telegram добавят ИИ-агентов")

        import services.factcheck_service as fsvc
        monkeypatch.setattr(fsvc, "load_claim_media", fake_media)
        service = FakeService()
        await orch.run_factcheck(
            orch.FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
                target_tg_message_id=TARGET_TG, target_text=COMPOSITE),
            service=service, db=FakeDB(origin_row=_origin_row(COMPOSITE)),
            bot=FakeBot(), cache=FakeCache())
        assert "283365" in captured["claim"]
        assert COMPOSITE.split(".")[0] in captured["claim"]  # подпись цела


# ── FC-09: повторный тезис — новая проверка (кеш вердиктов удалён) ──────────

class TestFC09RepeatFreshRun:
    @pytest.mark.asyncio
    async def test_old_cached_key_does_not_block_new_check(
            self, monkeypatch, planner_on):
        cache = FakeCache()
        # записи прежних версий контура ни на что не влияют: кеш вердиктов
        # удалён, повторный тезис всегда вычисляется заново
        old_key = cache.build_key(
            "factcheck", f"fcv3\x00fcv3\x00fp2\x00{COMPOSITE}")
        cache.store[old_key] = "Старый ошибочный вердикт"

        async def fake_evaluate(db_, chat_id, **kwargs):
            return _decision(kwargs.get("claim_text") or COMPOSITE), None

        monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_evaluate)
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_enabled", lambda: False)
        monkeypatch.setattr(orch, "get_smartmodule_concurrency_pool",
                            lambda: _Pool())
        monkeypatch.setattr(orch, "typing_active", _Typing)
        service = FakeService(verdict="Исправленный вердикт")
        bot = FakeBot()
        await orch.run_factcheck(
            orch.FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
                target_tg_message_id=TARGET_TG, target_text=COMPOSITE),
            service=service, db=FakeDB(origin_row=_origin_row(COMPOSITE)),
            bot=bot, cache=cache)
        assert len(service.check_claim_calls) == 1       # проверка была
        assert any("Исправленный вердикт" in m["text"]
                   for m in bot.sent)


# ═══════════════════════════════════════════════════════════════════════════
# Review r1 (F1–F6): интеграционные проверки через ФАКТИЧЕСКИЙ сервисный путь
# ═══════════════════════════════════════════════════════════════════════════

OFF_TOPIC_BLOCK = (
    "Утечка исходников Claude Code\n"
    "Boris Cherny рассказал о расследовании утечки кода\n"
    "Claude Code source code leak newsletter")


class _JsonLLM:
    """Аналитик/валидатор/вербализатор: JSON по шагу (без сети)."""

    def __init__(self, verdict=None, validator=None, text="Краткий вывод."):
        self.verdict = verdict or {"factual_verdict": "insufficient_evidence",
                                   "temporal_status": "unknown"}
        self.validator = validator or {"agree": True}
        self.text = text
        self.steps = []

    async def generate(self, messages, **kw):
        import json
        step = kw.get("step")
        self.steps.append(step)
        if step == "temporal_verdict":
            return json.dumps(self.verdict, ensure_ascii=False)
        if step == "temporal_validator":
            return json.dumps(self.validator, ensure_ascii=False)
        return self.text


def _service(llm=None, aggregator=None):
    return FactCheckService(aggregator=aggregator, llm=llm or _JsonLLM())


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


class TestF1CascadeRealPath:
    """F1: бюджет не ломает каскад; Tavily упал → Exa реально вызван."""

    @pytest.mark.asyncio
    async def test_budget_kwarg_does_not_break_one_arg_engines(
            self, monkeypatch):
        agg = sa.SearchAggregator(tavily_api_key="t", exa_api_key="e")
        calls = []

        async def tavily(query):                 # сторонний движок: без kwarg
            calls.append("tavily")
            raise RuntimeError("tavily 503")

        async def exa(query):                    # сторонний движок: без kwarg
            calls.append("exa")
            return ("Рост заболеваемости среди молодёжи\n"
                    "Медики подтвердили увеличение случаев\n"
                    "https://exa.example.org/1")

        monkeypatch.setattr(agg, "_search_tavily", tavily)
        monkeypatch.setattr(agg, "_search_exa", exa)
        out = await agg.search_relevant(
            "рост заболеваемости", 4000,
            relevance_terms=["рост", "заболеваемости", "медики"],
            timeout_budget=3.0)                  # продукт всегда передаёт бюджет
        assert calls == ["tavily", "exa"]        # Exa реально вызван
        assert "exa.example.org/1" in out

    @pytest.mark.asyncio
    async def test_retrieval_numbers_after_tavily_failure(self, planner_on):
        agg = sa.SearchAggregator(tavily_api_key="t", exa_api_key="e")

        async def tavily(query):
            raise RuntimeError("tavily down")

        async def exa(query):
            return ("Публикация про Telegram и Claude\n"
                    "Агенты Telegram подключат Claude, ChatGPT через API\n"
                    "https://exa.example.org/tg")

        agg._search_tavily = tavily
        agg._search_exa = exa
        plan = fsp.build_retrieval_plan(_decision(COMPOSITE),
                                        claim_text=COMPOSITE)
        outcome = await fsp.run_retrieval(plan, aggregator=agg)
        assert outcome.queries_used >= 1 and outcome.refs_collected >= 1
        assert classify_retrieval(outcome) == RETRIEVAL_OK
        assert outcome.evidence_map is not None
        assert all(r.url for r in outcome.evidence_map.refs)


class TestF2EnvelopeEvidencePath:
    """F2: строки без URL не становятся evidence на envelope-пути."""

    @pytest.mark.asyncio
    async def test_url_less_retrieval_is_processing_failed(self):
        env, _ = await tf.build_envelope(
            FakeDB(origin_row=_origin_row(COMPOSITE)),
            tf.InputRef(kind="reply", chat_id=CHAT_ID,
                        target_tg_message_id=TARGET_TG,
                        trigger_tg_message_id=TRIGGER_TG))
        outcome = fsp.RetrievalOutcome(
            evidence_map=None, search_text=OFF_TOPIC_BLOCK,
            queries_attempted=1, queries_used=1, refs_collected=0,
            fetch_errors=0, budget_exhausted=False)
        assert classify_retrieval(outcome) == RETRIEVAL_PROCESSING_FAILED
        run = await _service().check_claim_envelope(env, retrieval=outcome)
        assert run.evidence_rows == ()                  # url=None не evidence
        assert run.verdict.factual_verdict == "insufficient_evidence"
        assert run.verdict.reason == "source_missing"
        markup = _presentation_from_run(run)
        assert "материалы не удалось разобрать" in markup.lower()
        assert "Недостаточно данных для проверки" not in markup

    @pytest.mark.asyncio
    async def test_model_called_but_unbacked_positive_downgraded(self):
        """P0-FACTCHECK-CORRECTIVE (§2.4): аналитический вызов выполняется
        даже без цитируемого evidence; положительный вердикт без внешних
        доказательств и без помеченного основания самостоятельной проверки
        понижается сервером до honest insufficient_evidence."""
        llm = _JsonLLM(verdict={"factual_verdict": "supported"})
        env, _ = await tf.build_envelope(
            FakeDB(origin_row=_origin_row(COMPOSITE)),
            tf.InputRef(kind="reply", chat_id=CHAT_ID,
                        target_tg_message_id=TARGET_TG,
                        trigger_tg_message_id=TRIGGER_TG))
        outcome = fsp.RetrievalOutcome(
            evidence_map=None, search_text=OFF_TOPIC_BLOCK,
            queries_attempted=1, queries_used=1, refs_collected=0,
            fetch_errors=0, budget_exhausted=False)
        run = await _service(llm=llm).check_claim_envelope(
            env, retrieval=outcome)
        # существующий аналитик вызван (анализ не блокируется пустым evidence)
        assert "temporal_verdict" in llm.steps
        # «вспомнил цифру → подтверждено» не проходит: положительный вердикт
        # без basis-пометки → честная неопределённость (no-false-acceptance)
        assert run.verdict.factual_verdict == "insufficient_evidence"
        assert "unbacked_positive" in (run.verdict.uncertainty or {})


class TestF3RepeatFreshRun:
    """F3/§6.4: кеш готовых вердиктов удалён — повторный тезис и старые
    технические ошибки не подменяют новую проверку."""

    async def _envelope(self):
        env, _ = await tf.build_envelope(
            FakeDB(origin_row=_origin_row(COMPOSITE)),
            tf.InputRef(kind="reply", chat_id=CHAT_ID,
                        target_tg_message_id=TARGET_TG,
                        trigger_tg_message_id=TRIGGER_TG))
        return env

    @pytest.mark.asyncio
    async def test_repeat_claim_runs_fresh_analysis(self):
        llm = _JsonLLM()
        service = _service(llm=llm)
        env = await self._envelope()
        outcome = fsp.RetrievalOutcome(
            evidence_map=None, search_text="", queries_attempted=1,
            queries_used=0, refs_collected=0, fetch_errors=0,
            budget_exhausted=False, provider_failures=1)
        run1 = await service.check_claim_envelope(env, retrieval=outcome)
        calls_after_first = llm.steps.count("temporal_verdict")
        run2 = await service.check_claim_envelope(env, retrieval=outcome)
        # второй прогон = новый аналитический вызов, не выдача старого ответа
        assert calls_after_first == 1
        assert llm.steps.count("temporal_verdict") == 2
        assert run1.verdict_text is not None and run2.verdict_text is not None
        assert run2.cache_hit is False

    @pytest.mark.asyncio
    async def test_temporal_cache_machinery_removed(self):
        """F17: временный/legacy пути не читают и не пишут вердикт-кеш —
        механизм удалён целиком (§6.1)."""
        for name in ("build_temporal_cache_key", "read_temporal_cache",
                     "write_temporal_cache",
                     "temporal_cache_key_with_bucket"):
            assert not hasattr(tf, name), f"{name} должен быть удалён"


class TestF4BudgetPerPart:
    """F4: первая часть с числом/годом не забирает весь бюджет."""

    def test_every_part_gets_a_query(self, planner_on):
        claim = ("В сборке 283365 от macOS 13.1.0 (2024) добавили агентов. "
                 "Telegram подключил Claude. "
                 "Дуров убил Claude Code.")
        plan = fsp.build_retrieval_plan(_decision(claim), claim_text=claim)
        assert plan is not None
        assert len(plan.queries) == 3
        joined = " ".join(q.text.lower() for q in plan.queries)
        assert "telegram" in joined            # часть 2 покрыта
        assert "дуров" in joined or "code" in joined   # часть 3 покрыта
        assert len({q.text.lower() for q in plan.queries}) == 3

    def test_refinements_use_only_remaining_budget(self, planner_on):
        claim = ("В 2019 году выпало 120 мм осадков. "
                 "Урожай погиб. Инженеры признали ошибку.")
        plan = fsp.build_retrieval_plan(_decision(claim), claim_text=claim)
        assert plan is not None and len(plan.queries) == 3
        # при полном бюджете уточнения не вытесняют запросы частей
        intents = [q.intent for q in plan.queries]
        assert intents == [fsp.INTENT_ENTITY_CHECK] * 3


class TestF5NoContradictoryParts:
    """F5: положительный топ не сопровождается частями «данных недостаточно»."""

    @pytest.mark.asyncio
    async def test_positive_top_has_no_synthesized_contradiction(self):
        env, _ = await tf.build_envelope(
            FakeDB(origin_row=_origin_row(
                "Агенты Telegram подключены. Claude доступен. "
                "Дуров убил Claude Code.")),
            tf.InputRef(kind="reply", chat_id=CHAT_ID,
                        target_tg_message_id=TARGET_TG,
                        trigger_tg_message_id=TRIGGER_TG))
        ref = orch.EvidenceRef(
            evidence_id="ev-1", url="https://example.org/a",
            support="Агенты Telegram подключены к Claude")
        outcome = fsp.RetrievalOutcome(
            evidence_map=orch.EvidenceMap(refs=(ref,), allowlist=("ev-1",)),
            search_text="Агенты Telegram подключены к Claude\n"
                        "https://example.org/a",
            queries_attempted=1, queries_used=1, refs_collected=1,
            fetch_errors=0, budget_exhausted=False)
        llm = _JsonLLM(verdict={"factual_verdict": "supported",
                                "temporal_status": "current",
                                "evidence_refs": ["ev-1"]})
        run = await _service(llm=llm).check_claim_envelope(
            env, retrieval=outcome)
        assert run.verdict.factual_verdict == "supported"
        assert run.verdict.parts == ()          # нет противоречащего разбора
        markup = _presentation_from_run(run)
        assert "данных недостаточно" not in markup

    @pytest.mark.asyncio
    async def test_insufficient_top_still_gets_parts(self):
        env, _ = await tf.build_envelope(
            FakeDB(origin_row=_origin_row(COMPOSITE)),
            tf.InputRef(kind="reply", chat_id=CHAT_ID,
                        target_tg_message_id=TARGET_TG,
                        trigger_tg_message_id=TRIGGER_TG))
        outcome = fsp.RetrievalOutcome(
            evidence_map=None, search_text=OFF_TOPIC_BLOCK,
            queries_attempted=1, queries_used=1, refs_collected=0,
            fetch_errors=0, budget_exhausted=False)
        run = await _service().check_claim_envelope(env, retrieval=outcome)
        assert len(run.verdict.parts) >= 2
        assert all(p["factual_verdict"] == "insufficient_evidence"
                   for p in run.verdict.parts)


class TestF6ReadyNoText:
    """F6: «распознано, текста нет» ≠ «не анализировали»."""

    @pytest.mark.asyncio
    async def test_ready_without_text_is_not_reported_as_pending(self):
        async def fake_render(db, *, chat_id, tg_message_id):
            return {"caption": "Подпись", "knowledge_time": 1792200000,
                    "untrusted_ocr_texts": [],
                    "lines": ["Визуальное описание: кот на столе"]}

        media = await load_claim_media(FakeDB(), CHAT_ID, TARGET_TG,
                                       render_async=fake_render)
        assert media.image_analyzed is True
        assert media.image_not_analyzed is False
        assert media.notice() == ""
        assert media.caption == "Подпись"

    @pytest.mark.asyncio
    async def test_pending_analysis_is_still_marked(self):
        async def fake_render(db, *, chat_id, tg_message_id):
            return {"caption": "Подпись", "knowledge_time": None,
                    "untrusted_ocr_texts": [],
                    "lines": ["изображение, содержание ещё не распознано"]}

        media = await load_claim_media(FakeDB(), CHAT_ID, TARGET_TG,
                                       render_async=fake_render)
        assert media.image_not_analyzed is True
        assert media.image_analyzed is False
        assert "не готово" in media.notice()


# ═══════════════════════════════════════════════════════════════════════════
# FC-RFL-CLOSE: FC-05/FC-08 через ФАКТИЧЕСКИЙ сервисный путь без сети.
# Отличие от FC-05/FC-08 выше: класс исхода не собирается руками, а
# получается РЕАЛЬНЫМ `run_retrieval` (бюджет/дедлайн контура), решение о
# техническом исходе идёт через `check_claim_envelope`, заголовок — через
# renderer, а для FC-08 текст изображения читает РЕАЛЬНЫЙ
# `mca_vision.render_media_context_async` (а не поддельный dict).
# ═══════════════════════════════════════════════════════════════════════════


class _DeadlineAgg:
    """Провайдер, не укладывающийся в бюджет контура: первый запрос «висит»
    дольше дедлайна и падает по таймауту (как настоящий per-engine timeout),
    дальнейшие — быстрый отказ. Сети нет."""

    def __init__(self, delay: float = 0.2):
        self.delay = delay
        self.calls = 0

    async def search_relevant(self, query, max_symbols, relevance_terms=None,
                             timeout_budget=None):
        self.calls += 1
        if self.calls == 1:
            await asyncio.sleep(self.delay)
            raise TimeoutError("engine timeout")
        raise AllSearchEnginesFailedException("down")

    async def search(self, query, max_symbols):
        raise AllSearchEnginesFailedException("down")


class _FailingVerbalizer:
    """Вербализатор недоступен → используется ДЕТЕРМИНИРОВАННЫЙ честный текст
    (`_temporal_fallback_text`), а не «данных недостаточно»."""

    def __init__(self):
        self.steps = []

    async def generate(self, messages, **kw):
        self.steps.append(kw.get("step"))
        raise RuntimeError("verbalizer down")


class _CapturingLLM(_JsonLLM):
    """`_JsonLLM` + сохранение payload каждой стадии (проверка промпта)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.payloads = {}

    async def generate(self, messages, **kw):
        self.payloads.setdefault(kw.get("step"), []).append(messages)
        return await super().generate(messages, **kw)


def _patch_orchestrator_seams(monkeypatch, *, evaluate):
    monkeypatch.setattr(
        "services.mca_gates.temporal_factcheck_enabled", lambda: True)
    # FC-06C (§6.3): патч temporal_factcheck_cache_enabled снят — гейт
    # удалён вместе с кешем готовых вердиктов (кеша больше нет).
    monkeypatch.setattr(orch, "get_smartmodule_concurrency_pool",
                        lambda: _Pool())
    monkeypatch.setattr(orch, "typing_active", _Typing)
    monkeypatch.setattr(fsg, "evaluate_with_expansion", evaluate)


async def _envelope_for(text):
    env, _reject = await tf.build_envelope(
        FakeDB(origin_row=_origin_row(text)),
        tf.InputRef(kind="reply", chat_id=CHAT_ID,
                    target_tg_message_id=TARGET_TG,
                    trigger_tg_message_id=TRIGGER_TG))
    return env


class TestFC05RealServicePath:
    """FC-05: истёкший бюджет — технический исход на реальном пути."""

    @pytest.mark.asyncio
    async def test_budget_outcome_class_reason_and_headline(self, planner_on):
        plan = fsp.build_retrieval_plan(_decision(COMPOSITE),
                                        claim_text=COMPOSITE)
        assert plan is not None
        agg = _DeadlineAgg()
        outcome = await fsp.run_retrieval(plan, aggregator=agg,
                                          budget_seconds=0.05)
        # исход получен реальным контуром: попытки были, время вышло,
        # пригодной выдачи нет
        assert outcome.queries_attempted >= 1
        assert outcome.budget_exhausted is True
        assert outcome.queries_used == 0
        assert classify_retrieval(outcome) == RETRIEVAL_BUDGET

        env = await _envelope_for(COMPOSITE)
        run = await _service(llm=_FailingVerbalizer(),
                             aggregator=agg).check_claim_envelope(
            env, retrieval=outcome)
        assert run.verdict.reason == "deadline_exceeded"
        assert run.verdict.factual_verdict == "insufficient_evidence"
        assert "лимит" in run.verdict.uncertainty["retrieval_state"]
        # вербализатор упал → детерминированный текст называет причину
        assert "истёк лимит времени на поиск" in run.verdict_text
        markup = _presentation_from_run(run)
        assert "истёк лимит времени" in markup
        # P0-FACTCHECK-CORRECTIVE (§7.3): заголовок уже называет то же
        # ограничение — второй раз концовкой оно НЕ дублируется
        assert "ограничение проверки, а не опровержение" not in \
            fr.visible_text(markup)
        assert "Недостаточно данных для проверки" not in markup

    @pytest.mark.asyncio
    async def test_deadline_reaches_delivered_message(self, monkeypatch,
                                                      planner_on):
        # Дедлайн контура для теста короткий; сам контур — настоящий.
        monkeypatch.setattr(fsp, "_BUDGET_SECONDS_DEFAULT", 0.05)

        async def fake_evaluate(db_, chat_id, **kwargs):
            return _decision(kwargs.get("claim_text") or COMPOSITE), None

        _patch_orchestrator_seams(monkeypatch, evaluate=fake_evaluate)
        recorded = {}

        async def fake_record(db_, run, **kwargs):
            recorded["run"] = run

        monkeypatch.setattr(tf, "record_temporal_run", fake_record)

        agg = _DeadlineAgg()
        service = FactCheckService(aggregator=agg,
                                   llm=_FailingVerbalizer())
        bot = FakeBot()
        await orch.run_factcheck(
            orch.FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
                target_tg_message_id=TARGET_TG, target_text=COMPOSITE),
            service=service, db=FakeDB(origin_row=_origin_row(COMPOSITE)),
            bot=bot, cache=FakeCache())

        run = recorded["run"]
        assert run.verdict.reason == "deadline_exceeded"
        assert run.verdict.factual_verdict == "insufficient_evidence"
        assert run.evidence_rows == ()
        sent = "\n".join(m["text"] for m in bot.sent)
        assert "Проверка не завершена: истёк лимит времени" in sent
        # §7.3: концовка с тем же ограничением (технический notice) при
        # техническом заголовке не добавляется — дубля нет
        assert "ограничение проверки, а не опровержение" not in sent
        assert "Недостаточно данных для проверки" not in sent


FC08_CAPTION = ("В Telegram добавят ИИ-агентов: Claude и ChatGPT подключат "
                "через API")
FC08_OCR = "Сборка 283365 · macOS 13.1.0 · Claude, ChatGPT API"


def _vision_analysis_row():
    return {
        "status": "ready",
        "ocr_blocks": json.dumps(
            [{"text": FC08_OCR, "channel": "untrusted_image_data"}],
            ensure_ascii=False),
        "visual_description": "скриншот экрана настроек",
        "uncertainty": [],
        "self_reported_confidence": 0.8,
        "error_reason": "",
        "completed_at": 1792200500,
        "revision": 1,
    }


class VisionDB:
    """DB-фейк FC-08: строка сообщения + asset изображения + готовый анализ.

    Отдаётся в РЕАЛЬНЫЙ `mca_vision.render_media_context_async` (никакого
    поддельного dict контракта Vision)."""

    def __init__(self, *, fail_lookup: bool = False, text: str = ""):
        self.fail_lookup = fail_lookup
        self.row = {
            "text": text, "caption": FC08_CAPTION,
            "sent_at": 1792200000, "author_name": "Тест",
            "is_forward": False, "origin_type": None,
            "origin_sent_at": None, "current_revision": None,
            "content_hash": None, "origin_sender_user_id": None,
            "origin_chat_id": None, "origin_display_name": None,
            "forward_source": None,
        }

    async def get_smart_message_origin_block(self, chat_id, tg):
        # Like the real DB: строка сообщения доступна (дата/подпись), origin
        # отсутствует (не пересылка).
        return dict(self.row)

    async def get_media_assets_for_message(self, chat_id, tg):
        return [{"asset_kind": "photo", "asset_id": "asset-fc08",
                 "content_hash": "hash-fc08"}]

    async def get_smart_message_by_tg_id(self, chat_id, tg):
        return dict(self.row)

    async def get_ready_analysis(self, asset_id, scope, **kwargs):
        if self.fail_lookup:
            raise RuntimeError("vision store down")
        return _vision_analysis_row()

    async def find_ready_analysis_by_content_hash(self, *a, **kw):
        if self.fail_lookup:
            raise RuntimeError("vision store down")
        return None


EVIDENCE_BLOCK = (
    "Публикация про Telegram и Claude\n"
    "Агенты Telegram подключат Claude, ChatGPT через API, сборка 283365\n"
    "https://exa.example.org/tg")


class TestFC08RealVisionPath:
    """FC-08: подпись + изображение через реальный Vision-контур."""

    @pytest.mark.asyncio
    async def test_real_vision_render_feeds_caption_and_ocr(self):
        media = await load_claim_media(VisionDB(), CHAT_ID, TARGET_TG)
        assert media.caption == FC08_CAPTION       # подпись не потеряна
        assert media.image_present and media.image_analyzed
        assert "283365" in media.text_suffix
        assert "macos" in media.text_suffix.lower()
        # OCR — данные изображения, а не слова автора (честная маркировка)
        assert "не слова автора" in media.text_suffix
        assert media.ocr_chars > 0
        assert media.notice() == ""                # ложной оговорки нет

    @pytest.mark.asyncio
    async def test_vision_unavailable_is_honest_and_keeps_caption(self):
        media = await load_claim_media(VisionDB(fail_lookup=True), CHAT_ID,
                                       TARGET_TG)
        assert media.image_not_analyzed is True    # распознавания нет — честно
        assert media.image_analyzed is False
        assert media.text_suffix == ""             # OCR не выдуман
        assert media.caption == FC08_CAPTION       # подпись сохранена
        assert "не готово" in media.notice()

    @pytest.mark.asyncio
    async def test_end_to_end_caption_and_ocr_reach_search_and_analyst(
            self, monkeypatch, planner_on):
        captured = {}

        async def fake_evaluate(db_, chat_id, **kwargs):
            captured["claim"] = kwargs.get("claim_text")
            return _decision(kwargs.get("claim_text") or FC08_CAPTION), None

        _patch_orchestrator_seams(monkeypatch, evaluate=fake_evaluate)

        async def no_fetch(url, **kw):        # офлайн: SafeFetcher недоступен
            return None

        async def no_record(db_, run, **kwargs):
            return None

        monkeypatch.setattr(fsp, "fetch_primary_evidence", no_fetch)
        monkeypatch.setattr(tf, "record_temporal_run", no_record)
        llm = _CapturingLLM(
            verdict={"factual_verdict": "insufficient_evidence",
                     "temporal_status": "current"})
        agg = _Agg(EVIDENCE_BLOCK)
        bot = FakeBot()
        await orch.run_factcheck(
            orch.FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
                target_tg_message_id=TARGET_TG, target_text=FC08_CAPTION),
            service=FactCheckService(aggregator=agg, llm=llm),
            db=VisionDB(), bot=bot, cache=FakeCache())

        # 1) OCR попал в тезис, который ушёл в определение пригодности
        assert FC08_CAPTION in captured["claim"]
        assert "283365" in captured["claim"]
        assert "не слова автора" in captured["claim"]   # честная маркировка
        # 2) OCR попал в поисковые запросы (не только в промпт)
        assert any("283365" in q for q in agg.calls)
        # 3) OCR попал в промпт аналитика (реальный payload стадии verdict)
        analyst = llm.payloads.get("temporal_verdict") or []
        assert analyst, "аналитик должен получить evidence"
        payload = "\n".join(m["content"] for m in analyst[0])
        assert FC08_CAPTION in payload
        assert "283365" in payload
        assert "не слова автора" in payload
        # 4) ответ доставлен
        assert bot.sent

    @pytest.mark.asyncio
    async def test_orchestrator_reports_image_not_analyzed(self, monkeypatch,
                                                           planner_on):
        async def fake_evaluate(db_, chat_id, **kwargs):
            return _decision(kwargs.get("claim_text") or FC08_CAPTION), None

        _patch_orchestrator_seams(monkeypatch, evaluate=fake_evaluate)

        async def no_fetch(url, **kw):
            return None

        async def no_record(db_, run, **kwargs):
            return None

        monkeypatch.setattr(fsp, "fetch_primary_evidence", no_fetch)
        monkeypatch.setattr(tf, "record_temporal_run", no_record)
        bot = FakeBot()
        await orch.run_factcheck(
            orch.FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
                target_tg_message_id=TARGET_TG, target_text=FC08_CAPTION),
            service=FactCheckService(aggregator=_Agg(EVIDENCE_BLOCK),
                                     llm=_JsonLLM()),
            db=VisionDB(fail_lookup=True), bot=bot, cache=FakeCache())
        sent = "\n".join(m["text"] for m in bot.sent)
        assert "распознавание ещё не готово" in sent   # честная оговорка
        assert "283365" not in sent                    # OCR не выдуман
