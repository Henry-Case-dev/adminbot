"""CFG-06 W7 — композит блокирующего критерия CFG-06.B + спор 200+ (06G).

TEST-LIFECYCLE: CONTRACT owner=CFG-06

Композит (бриф §4, L290): система (1) сначала решает, имеет ли смысл
проверка (gate) → (2) затем подтверждает утверждение реальными доступными
источниками (агрегатор/SafeFetcher на моках, сеть off) ИЛИ честно сообщает
ограничение → (3) служебные данные не выпускаются → (4) публикуется краткий
читаемый Telegram-вердикт с проверяемыми ссылками (только EvidenceMap) →
(5) единый контракт на всех маршрутах и fallback.

Все 8 сценариев идут через ОДИН вход `run_factcheck`. Сеть полностью
замокана (агрегатор + SafeFetcher-инъекция). Спор-фикстура 260 сообщений:
широкий контекст > кап-40, резолюция по доминирующему спору, needs_context.
"""
import os
import asyncio
import dataclasses
import io
import json
import time

import pytest

from config.settings import settings
from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services import factcheck_suitability as fsg
from services import smart_cache as sc
from services.factcheck_orchestrator import FactcheckRequest, run_factcheck
from services.factcheck_renderer import visible_text

CHAT_ID = -100111
TARGET_TG = 9400
TRIGGER_TG = 9401
THESIS_TG = 8000
THESIS = ("в Килякете выпало 120 мм осадков за сутки — рекорд для области")


# ── Моки (сеть off) ──────────────────────────────────────────────────────────

class FakeSafeFetcher:
    """Инъекция вместо SafeFetcher (прецедент enrich_evidence_dates)."""
    calls = []

    async def fetch_text(self, url, **kw):
        FakeSafeFetcher.calls.append(url)
        return ('<html><head><meta property="article:published_time" '
                'content="2019-07-01T08:00:00+00:00"></head><body><p>'
                'Метеостанция Килякета подтвердила: в июле 2019 года выпало '
                '120 мм осадков за сутки — рекорд наблюдений истории '
                'станции по данным архива метеоуслуг региона.</p></body></html>')


class FakeDB:
    def __init__(self, rows=None, origin_row=None):
        self._rows = rows or []
        self._origin = origin_row
        self.around_calls = 0

    async def get_messages_around(self, chat_id, tg, before, after):
        self.around_calls += 1
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
    def __init__(self, default=None, fail=False):
        self.default = default if default is not None else (
            "Рекорд осадков в Килякете\n"
            "Метеостанция подтвердила 120 мм за сутки июля 2019 года\n"
            "https://example.org/meteo")
        self.fail = fail
        self.calls = []

    async def search(self, query, max_symbols):
        self.calls.append(query)
        if self.fail:
            raise RuntimeError("engines down")
        return self.default


class FakeLLM:
    def __init__(self, reply="какой именно тезис проверить?"):
        self.reply = reply
        self.calls = []

    async def generate(self, messages, **kw):
        self.calls.append({"messages": messages, **kw})
        return self.reply


class FakeService:
    def __init__(self, aggregator=None, verdict=None, llm=None,
                 fail_llm=False):
        self.aggregator = aggregator
        self.llm = llm or FakeLLM()
        self.verdict = verdict or ("Данные доступных источников утверждение "
                                   "не подтверждают.")
        self.fail_llm = fail_llm
        self.check_claim_calls = []

    async def check_claim(self, target_text, user_hint, forward_source, *,
                          chat_id=None, chat_context=None,
                          search_results=None):
        self.check_claim_calls.append({
            "target_text": target_text, "search_results": search_results})
        if self.fail_llm:
            from services.llm_client import LLMError
            raise LLMError("model unavailable")
        return self.verdict


class FakeBot:
    id = 862000000

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("M", (), {"message_id": 555})()

    async def send_chat_action(self, chat_id, action, **kw):
        return True


@pytest.fixture
def v2_on(monkeypatch):
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    # сеть off: SafeFetcher под инъекцией на уровне источника
    monkeypatch.setattr("services.safe_fetch.SafeFetcher", FakeSafeFetcher)
    FakeSafeFetcher.calls = []
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


# ── Харнесс сценария ─────────────────────────────────────────────────────────

class ScenarioResult:
    def __init__(self):
        self.bot = FakeBot()
        self.service = None
        self.aggregator = None
        self.decisions = []
        self.order = []
        self.db = None
        self.latency_ms = None
        self.error_phrase = None


def _dispute_rows(total=260):
    """Спор 200+: тезис ~60-е сообщение, анафора/местоимения, болтовня."""
    rows = []

    def _row(i, text, tg, reply_to=None, author="Вася"):
        rows.append({"id": 100 + i, "user_id": 1, "chat_id": CHAT_ID,
                     "text": text, "reply_to_id": reply_to,
                     "timestamp": 1000 + i, "media_type": "text",
                     "author_name": author, "is_forward": False,
                     "forward_source": None, "tg_message_id": tg})

    for i in range(total - 2):
        if i == 60:
            _row(i, THESIS, THESIS_TG, author="Вася")
        elif i == 61:
            _row(i, "это бред", 8001, reply_to=THESIS_TG, author="Петя")
        elif i == 62:
            _row(i, "источник где?", 8002, reply_to=THESIS_TG,
                 author="Петя")
        elif i == 63:
            _row(i, "пруфов не будет, знаю я", 8003, reply_to=8001,
                 author="Вася")
        elif i == 64:
            _row(i, "он опять про своё", 8004, author="Оля")
        else:
            _row(i, f"реплика болтовни номер {i}", 100 + i,
                 author="Вася" if i % 2 else "Петя")
    _row(total - 2, "правда?", TARGET_TG)
    _row(total - 1, "фактчек", TRIGGER_TG)
    return rows


async def _scenario(claim, *, rows=None, origin=None, aggregator=None,
                    service=None, fail_llm=False) -> ScenarioResult:
    res = ScenarioResult()
    res.db = FakeDB(rows=rows, origin_row=origin)
    res.aggregator = aggregator if aggregator is not None else FakeAggregator()
    res.service = service if service is not None else FakeService(
        aggregator=res.aggregator, fail_llm=fail_llm)

    agg_search = res.aggregator.search

    async def _search(q, m):
        res.order.append(("search", q))
        return await agg_search(q, m)

    res.aggregator.search = _search

    orig_check = res.service.check_claim

    async def _check(*a, **k):
        res.order.append(("verdict", a[0]))
        return await orig_check(*a, **k)

    res.service.check_claim = _check

    orig_eval = fsg.evaluate_with_expansion

    async def _eval(*a, **k):
        decision, ctx = await orig_eval(*a, **k)
        res.decisions.append(decision.decision if decision else None)
        res.last_decision = decision
        return decision, ctx

    fsg.evaluate_with_expansion = _eval
    try:
        started = time.perf_counter()
        await run_factcheck(
            FactcheckRequest(chat_id=CHAT_ID,
                             trigger_tg_message_id=TRIGGER_TG,
                             target_tg_message_id=TARGET_TG,
                             target_text=claim, kind="reply"),
            service=res.service, db=res.db, bot=res.bot,
            cache=FakeCache())
        res.latency_ms = int((time.perf_counter() - started) * 1000)
    finally:
        fsg.evaluate_with_expansion = orig_eval
    return res


def _composite_common(res: ScenarioResult):
    """(3) служебные данные не выпускаются + (4) читаемость/чанки."""
    assert res.bot.sent
    markup = "\n".join(s["text"] for s in res.bot.sent)
    visible = visible_text(markup)
    for token in ("as_of", "gate_version", "reason_code", "fsg1", "fcv2",
                  "fp1", "temporal_status", "factual_verdict",
                  "evaluated_period"):
        assert token not in visible, token
    for sent in res.bot.sent:
        assert len(sent["text"]) <= 4096
    return visible


# ── Композит CFG-06.B: 8 сценариев ───────────────────────────────────────────

class TestCompositeCfg06B:
    @pytest.mark.asyncio
    async def test_s1_meaningful_with_sources(self, v2_on):
        """(1) gate checkable → (2) реальные источники (агрегатор+SafeFetch)
        → (4) краткий вердикт с проверяемой ссылкой (только EvidenceMap)."""
        res = await _scenario(
            "в Килякете выпало 120 мм осадков за сутки — это рекорд")
        # (1) gate первым, решение осмысленное
        assert res.decisions and res.decisions[0] == "checkable_in_context"
        # (2) поиск реальному источнику: план → агрегатор → SafeFetcher
        assert res.order and res.order[0][0] == "search"
        assert res.order[-1][0] == "verdict"          # вердикт после поиска
        assert FakeSafeFetcher.calls == ["https://example.org/meteo"]
        # (4) читаемый вердикт + проверяемая ссылка только из EvidenceMap
        assert len(res.bot.sent) == 1
        markup = res.bot.sent[0]["text"]
        assert markup.count('href="https://example.org/meteo"') == 1
        visible = visible_text(markup)
        assert "https://example.org/meteo" not in visible
        assert "example.org" in visible               # label = домен
        # (3) служебное не утекает; чанки целые
        visible = _composite_common(res)

    @pytest.mark.asyncio
    async def test_s2_meaningful_without_sources_honest_limit(
            self, v2_on):
        """(2) источники без URL → честное ограничение, не самоуверенность."""
        agg = FakeAggregator(default="Рекорд осадков\n"
                                     "Сниппет без ссылки\n")
        res = await _scenario(
            "в Килякете выпало 120 мм осадков за сутки — это рекорд",
            aggregator=agg)
        assert res.decisions[0] == "checkable_in_context"
        visible = _composite_common(res)
        assert "первоисточник" in visible.lower()
        assert "не удалось" in visible.lower()
        assert "href=" not in res.bot.sent[0]["text"]   # выдуманных ссылок нет

    @pytest.mark.asyncio
    async def test_s3_engines_down_honest_error(self, v2_on):
        """(2) веб недоступен (план И внутренний поиск) → честная ошибка."""
        from services.llm_client import LLMError
        from services.search_aggregator import AllSearchEnginesFailedException
        from services.smartmodule_phrases import FACTCHECK_ERROR_PHRASES
        agg = FakeAggregator(fail=True)

        class _DownService(FakeService):
            async def check_claim(self, target_text, user_hint,
                                  forward_source, *, chat_id=None,
                                  chat_context=None, search_results=None):
                # planner упал → search_results=None → внутренний поиск
                # тоже упал → честная ошибка наверх (семантика 5.4b)
                assert search_results is None
                raise AllSearchEnginesFailedException("all engines down")

        svc = _DownService(aggregator=agg)
        svc.llm = FakeLLM()
        res = await _scenario(
            "в Килякете выпало 120 мм осадков за сутки — это рекорд",
            aggregator=agg, service=svc)
        assert res.aggregator.calls                  # планировщик пытался
        visible = _composite_common(res)
        assert any(phrase in visible for phrase in FACTCHECK_ERROR_PHRASES)
        assert "подтвержд" not in visible.lower()     # нет самоуверенности

    @pytest.mark.asyncio
    async def test_s4_nonsense_refusal_without_search(self, v2_on):
        """(1) gate: бессмысленное → отказ БЕЗ поиска (короткая реплика)."""
        from services.smartmodule_phrases import FACTCHECK_NO_CLAIM_PHRASES
        rows = [{"id": 100 + i, "user_id": 1, "chat_id": CHAT_ID,
                 "text": "целевое" if i == 10 else "абв гдё жзик лсн прст",
                 "reply_to_id": None, "timestamp": 1000 + i,
                 "media_type": "text", "author_name": "Вася",
                 "is_forward": False, "forward_source": None,
                 "tg_message_id": TARGET_TG if i == 10 else 100 + i}
                for i in range(12)]
        agg = FakeAggregator()
        res = await _scenario("абв гдё жзик лсн прст", rows=rows,
                              aggregator=agg)
        assert res.decisions[-1] == "no_claim_after_context"
        assert res.order == []                        # поиска НЕТ (1)
        assert len(res.bot.sent) == 1
        assert res.bot.sent[0]["text"] in FACTCHECK_NO_CLAIM_PHRASES
        _composite_common(res)

    @pytest.mark.asyncio
    async def test_s5_needs_context_expansion_then_honest(self, v2_on):
        """(1) gate: мало контекста → needs_context → дозапрос → честно."""
        rows = [{"id": 100 + i, "user_id": 1, "chat_id": CHAT_ID,
                 "text": "реплика", "reply_to_id": None,
                 "timestamp": 1000 + i, "media_type": "text",
                 "author_name": "Вася", "is_forward": False,
                 "forward_source": None, "tg_message_id": 100 + i}
                for i in range(3)]
        rows.append({"id": 999, "user_id": 1, "chat_id": CHAT_ID,
                     "text": "правда?", "reply_to_id": None,
                     "timestamp": 9999, "media_type": "text",
                     "author_name": "Вася", "is_forward": False,
                     "forward_source": None, "tg_message_id": TARGET_TG})
        db = FakeDB(rows=rows)
        res = ScenarioResult()
        res.db, res.bot = db, FakeBot()
        res.aggregator = FakeAggregator()
        res.service = FakeService(aggregator=res.aggregator)
        orig_eval = fsg.evaluate_suitability

        def _eval(*a, **k):
            d = orig_eval(*a, **k)
            res.decisions.append(d.decision if d else None)
            return d

        fsg.evaluate_suitability = _eval
        try:
            await run_factcheck(
                FactcheckRequest(chat_id=CHAT_ID,
                                 trigger_tg_message_id=TRIGGER_TG,
                                 target_tg_message_id=TARGET_TG,
                                 target_text="правда?", kind="reply"),
                service=res.service, db=db, bot=res.bot, cache=FakeCache())
        finally:
            fsg.evaluate_suitability = orig_eval
        # дозапрос: две выборки окна (начальная + расширенная)
        assert db.around_calls == 2
        # лестница 06J.1: needs_context → (расширение) → честный
        # context_unavailable, НЕ отказ
        assert res.decisions[0] == "needs_context"
        assert res.decisions[-1] == "context_unavailable"
        # честно: продолжение без выдуманного тезиса, вердикт-ограничение
        assert len(res.bot.sent) == 1
        _composite_common(res)

    @pytest.mark.asyncio
    async def test_s6_dispute_200_plus_context_resolution(self, v2_on, tmp_path):
        """Спор 260 сообщений: широкий контекст, доминирующий спор,
        автор анцедента сохранён; метрики в evidence."""
        rows = _dispute_rows(260)
        res = await _scenario("правда?", rows=rows)
        # широкий контекст: окно > кап-40 (сообщений в срезе ≥ 200)
        assert len(res.db._rows) >= 200
        assert res.decisions[-1] == "checkable_in_context"
        # резолюция по доминирующему спору: анцедент-тезис, автор сохранён
        d = res.last_decision
        assert d.claim_items and d.claim_items[0].source in ("topic",
                                                             "reply_to")
        assert d.claim_items[0].anchor_tg_message_id == THESIS_TG
        assert d.claim_items[0].author == "Вася"
        visible = _composite_common(res)
        assert visible                              # читаемый ответ
        assert res.latency_ms is not None
        # метрики спора — в evidence-JSON (06G.7/приёмка)
        _dump_dispute_metrics(res, rows, d, tmp_path)

    @pytest.mark.asyncio
    async def test_s7_fallback_legacy_error_honest(self, v2_on):
        """Fallback: LLM-ветка упала → честная фраза 5.5, без выдумки."""
        from services.smartmodule_phrases import LLM_ERROR_PHRASES
        res = await _scenario(
            "в Килякете выпало 120 мм осадков за сутки — это рекорд",
            service=FakeService(aggregator=FakeAggregator(), fail_llm=True))
        visible = _composite_common(res)
        assert any(phrase in visible for phrase in LLM_ERROR_PHRASES)
        assert res.service.check_claim_calls        # fallback-ветка отработала

    @pytest.mark.asyncio
    async def test_s8_ambiguous_clarification_persona(self, v2_on,
                                                      monkeypatch):
        """(1) gate: два спора → уточнение (персона, без поиска)."""
        import services.prompt_composer as pc

        async def _owner(chat_id):
            return "[PERSONA]"

        monkeypatch.setattr(pc, "speech_owner_block", _owner)
        rows = []
        base = 0
        for tg0, thesis, author in ((8000, THESIS, "Вася"),
                                    (8100, "вакцина от гриппа содержит "
                                           "живой вирус штамм", "Оля")):
            rows.append({"id": 100 + base, "user_id": 1, "chat_id": CHAT_ID,
                         "text": thesis, "reply_to_id": None,
                         "timestamp": 1000 + base, "media_type": "text",
                         "author_name": author, "is_forward": False,
                         "forward_source": None, "tg_message_id": tg0})
            rows.append({"id": 101 + base, "user_id": 1, "chat_id": CHAT_ID,
                         "text": "это бред", "reply_to_id": tg0,
                         "timestamp": 1001 + base, "media_type": "text",
                         "author_name": "Петя", "is_forward": False,
                         "forward_source": None, "tg_message_id": tg0 + 1})
            base += 10
        rows.append({"id": 999, "user_id": 1, "chat_id": CHAT_ID,
                     "text": "целевое", "reply_to_id": None,
                     "timestamp": 9999, "media_type": "text",
                     "author_name": "Вася", "is_forward": False,
                     "forward_source": None, "tg_message_id": TARGET_TG})
        agg = FakeAggregator()
        llm = FakeLLM(reply="какой именно тезис проверить?")
        svc = FakeService(aggregator=agg, llm=llm)
        res = await _scenario("ну и что там?", rows=rows, aggregator=agg,
                              service=svc)
        assert res.decisions[-1] == "ambiguous_needs_clarification"
        assert res.order == []                      # без поиска
        assert llm.calls and llm.calls[0][
            "messages"][0]["content"].endswith("[PERSONA]")
        assert "какой именно тезис" in res.bot.sent[0]["text"]
        _composite_common(res)


def _dump_dispute_metrics(res: ScenarioResult, rows, decision, out_dir):
    """Метрики спора 200+ → JSON (06G.7/приёмка W7).

    Пишет в каталог прогона (pytest tmp_path): tracked evidence-файл
    не мутируется тестовым прогоном (hygiene-fix 28.10.2026)."""
    item = decision.claim_items[0] if decision.claim_items else None
    metrics = {
        "fixture_messages": len(rows),
        "wide_context_min": 200,
        "cap40_exceeded": len(rows) > 40,
        "final_decision": decision.decision,
        "decision_path": res.decisions,
        "claim_source": item.source if item else None,
        "antecedent_anchor_tg": item.anchor_tg_message_id if item else None,
        "antecedent_author": item.author if item else None,
        "expected_author": "Вася",
        "attribution_ok": bool(item and item.author == "Вася"),
        "recall_antecedent_found": bool(
            item and item.anchor_tg_message_id == THESIS_TG),
        "searches_before_verdict": sum(
            1 for e in res.order if e[0] == "search"),
        "latency_ms_mock": res.latency_ms,
        "delivered_messages": len(res.bot.sent),
    }
    path = os.path.join(str(out_dir), "w7-dispute-metrics.json")
    io.open(path, "w", encoding="utf-8").write(
        json.dumps(metrics, ensure_ascii=False, indent=1))
