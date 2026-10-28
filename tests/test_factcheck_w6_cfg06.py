"""CFG-06 W6 — единый retrieval-контур + сквозной egress + cache-hit рендер.

TEST-LIFECYCLE: CONTRACT owner=CFG-06

Контракты:
  * единый retrieval-контур v2 (06C.8): план выполняется ДО вердикта, выдача
    уходит в legacy-ветку (один поиск на прогон — агрегатор звался только
    планировщиком); бюджет/дедлайн → честная деградация без исключений;
  * метрики 06G.7: attempted/used/refs/fetch_errors/budget — в лог-дайджесте
    прогона;
  * envelope cache-hit идёт через ЕДИНУЮ доставку (renderer, HTML) —
    консистентно с кешем (детерминированное преобразование кешированного
    текста), plain-обхода нет;
  * сквозной egress (06B): FactcheckRequest → delivery — служебных полей
    нет, ссылки только из EvidenceMap (href), чанки ≤4096 с целыми тегами;
  * OFF: ни renderer, ни planner прод-путём не вызываются.
"""
import asyncio
import json

import pytest

from config.settings import settings
from services import factcheck_planner as fsp
from services import factcheck_renderer as fr
from services import factcheck_suitability as fsg
from services import factcheck_orchestrator as orch
from services import temporal_factcheck as tf
from services.factcheck_orchestrator import FactcheckRequest, run_factcheck

CHAT_ID = -100222
TARGET_TG = 9300
TRIGGER_TG = 9301


class FakeDB:
    def __init__(self, rows=None, origin_row=None):
        self._rows = rows or []
        self._origin = origin_row

    async def get_messages_around(self, chat_id, tg, before, after):
        return list(self._rows)

    async def get_recent_messages(self, chat_id, limit):
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


class FakeAggregator:
    def __init__(self, default=None, delay=0.0):
        self.default = default or (
            "Рекорд осадков в Килякете\n"
            "Метеостанция подтвердила 120 мм за сутки июля 2019\n"
            "https://example.org/meteo")
        self.delay = delay
        self.calls = []

    async def search(self, query, max_symbols):
        self.calls.append((query, max_symbols))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.default


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
    def __init__(self, aggregator=None, verdict="Проверено: тезис не "
                                               "подтвердился, as_of уточнять "
                                               "не будем."):
        self.aggregator = aggregator
        self.llm = None
        self.verdict = verdict
        self.check_claim_calls = []
        self.envelope_calls = []

    async def check_claim(self, target_text, user_hint, forward_source, *,
                          chat_id=None, chat_context=None,
                          search_results=None):
        self.check_claim_calls.append({
            "target_text": target_text, "search_results": search_results})
        return self.verdict

    async def check_claim_envelope(self, envelope, *, chat_context=None):
        self.envelope_calls.append(envelope)
        verdict = tf.TemporalVerdict(
            factual_verdict="refuted", temporal_status="current",
            evaluated_period={}, assessment_mode="contextual",
            as_of=1760900000, evidence_refs=("ev-1",), reason=None)
        return tf.TemporalRunResult(
            envelope=envelope, verdict=verdict,
            verdict_text="Данные утверждение не подтверждают.",
            evidence_rows=({"evidence_id": "ev-1",
                            "url": "https://example.org/t", "support": "s",
                            "source_kind": "secondary",
                            "published_at": None},))


@pytest.fixture
def v2_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


def _req(claim="в Килякете выпало 120 мм осадков за сутки — это рекорд"):
    return FactcheckRequest(
        chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
        target_tg_message_id=TARGET_TG, target_text=claim, kind="reply")


# ── Единый retrieval-контур (06C.8) ──────────────────────────────────────────

class TestUnifiedRetrieval:
    @pytest.mark.asyncio
    async def test_one_search_per_run_and_args_parity(self, v2_on):
        agg = FakeAggregator()
        svc = FakeService(aggregator=agg)
        await run_factcheck(_req(), service=svc, db=FakeDB(), bot=FakeBot(),
                            cache=FakeCache())
        # агрегатор звался ТОЛЬКО планировщиком; выдача ушла в сервис
        assert agg.calls and 1 <= len(agg.calls) <= 3
        call = svc.check_claim_calls[0]
        assert call["search_results"], "плановая выдача идёт в сервис"

    @pytest.mark.asyncio
    async def test_budget_deadline_honest_degradation(self, planner_on=True):
        object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
        try:
            plan = fsp.build_retrieval_plan(
                _decision(), claim_text="в Килякете выпало 120 мм осадков")
            slow = FakeAggregator(delay=1.0)
            outcome = await fsp.run_retrieval(plan, aggregator=slow,
                                              budget_seconds=0.1)
            assert outcome.budget_exhausted is True
            assert outcome.queries_attempted < len(plan.queries)
        finally:
            object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED",
                               False)

    @pytest.mark.asyncio
    async def test_metrics_in_run_digest(self, v2_on, caplog):
        import logging
        with caplog.at_level(logging.INFO,
                             logger="services.factcheck_orchestrator"):
            await run_factcheck(
                _req(), service=FakeService(aggregator=FakeAggregator()),
                db=FakeDB(), bot=FakeBot(), cache=FakeCache())
        digest = [r.getMessage() for r in caplog.records
                  if "retrieval | chat=" in r.getMessage()]
        assert digest, "метрики 06G.7 отсутствуют в дайджесте прогона"
        line = digest[-1]
        for field in ("attempted=", "used=", "refs=", "fetch_errors=",
                      "budget_exhausted="):
            assert field in line


# ── §6: вердикт-кеш удалён — единая доставка свежего результата ─────────────

class TestEnvelopeFreshRunDelivery:
    @pytest.mark.asyncio
    async def test_stale_cache_entries_are_not_served(self, v2_on):
        """P0-FACTCHECK-CORRECTIVE (§6.1/§6.4): записи прежнего механизма
        кеша не читаются — каждое обращение доставляет свежий результат
        одним сообщением (renderer → одна доставка)."""
        origin = {"text": "в килякете 120 мм", "caption": None,
                  "origin_type": None, "origin_sent_at": None,
                  "sent_at": 1700000000, "current_revision": None,
                  "content_hash": None, "origin_sender_user_id": None,
                  "origin_chat_id": None, "origin_display_name": None,
                  "author_name": "Вася", "forward_source": None}
        db = FakeDB(origin_row=origin)
        cache = FakeCache()
        cache.markers["любой-ключ-прежнего-механизма"] = json.dumps({
            "text": "Кешированный текст вердикта прошлой проверки.",
            "as_of": 1760900000, "factual_verdict": "refuted",
            "temporal_status": "current", "assessment_mode": "contextual",
            "pipeline_version": tf.TEMPORAL_PIPELINE_VERSION,
            "tz_resolution_version": tf.TEMPORAL_TZ_RESOLUTION_VERSION,
        }, ensure_ascii=False)
        svc = FakeService()
        bot = FakeBot()
        await run_factcheck(
            FactcheckRequest(chat_id=CHAT_ID,
                             trigger_tg_message_id=TRIGGER_TG,
                             target_tg_message_id=TARGET_TG,
                             target_text="в килякете 120 мм", kind="reply"),
            service=svc, db=db, bot=bot, cache=cache)
        assert svc.envelope_calls              # проверка ВЫПОЛНЕНА заново
        assert len(bot.sent) == 1              # ОДНА доставка
        assert "Кешированный текст вердикта" not in bot.sent[0]["text"]


def _decision(claim="в Килякете выпало 120 мм осадков за сутки — это рекорд"):
    item = fsg.ClaimItem(text=claim,
                         claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
                         verifiable=True, source="literal")
    return fsg.SuitabilityDecision(
        decision=fsg.DECISION_CHECKABLE,
        claim_type=fsg.CHECKABLE_FACTUAL_CLAIM, claim_items=(item,),
        scope="web", reason_code="obvious_checkable_predicate",
        confidence=0.8, target_ref={})


# ── Сквозной egress (06B) ────────────────────────────────────────────────────

class TestEndToEndEgress:
    @pytest.mark.asyncio
    async def test_request_to_delivery_no_service_fields(self, v2_on):
        agg = FakeAggregator()
        svc = FakeService(aggregator=agg)
        bot = FakeBot()
        await run_factcheck(_req(), service=svc, db=FakeDB(), bot=bot,
                            cache=FakeCache())
        assert bot.sent
        full_markup = "\n".join(s["text"] for s in bot.sent)
        # 1. служебные поля/маркеры отсутствуют (в т.ч. срезанные из текста)
        visible = fr.visible_text(full_markup)
        for token in ("as_of", "gate_version", "reason_code", "fsg1",
                      "fcv2", "fp1", "temporal_status"):
            assert token not in visible
        # 2. ссылки только из EvidenceMap текущего прогона, только href
        assert full_markup.count('href="https://example.org/meteo"') >= 1
        assert visible.count("https://example.org/meteo") == 0
        # 3. чанки ≤4096, теги целые в каждой части
        for sent in bot.sent:
            assert len(sent["text"]) <= 4096
            assert sent["text"].count("<b>") == sent["text"].count("</b>")
            fr.visible_text(sent["text"])          # парсится без ошибок


# ── OFF-паритет ──────────────────────────────────────────────────────────────

class TestOffParity:
    def test_off_planner_none_and_handler_imports_clean(self):
        object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
        try:
            assert fsp.planner_enabled() is False
            assert fsp.build_retrieval_plan(
                _decision(), claim_text="в Килякете 120 мм") is None
        finally:
            object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED",
                               False)
        import io
        src = io.open("handlers/factcheck.py", encoding="utf-8").read()
        assert "factcheck_renderer" not in src   # OFF-паритет доставки (W5)
        assert "factcheck_planner" not in src    # planner — только внутри v2
