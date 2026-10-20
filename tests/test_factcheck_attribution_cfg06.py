"""CFG-06 06G.3 — локальный tool «кто это сказал»: контракты.

Спор «кто конкретно это сказал в чате» (клейм «X сказал Y»):

* детерминированное распознавание атрибуционного клейма (БЕЗ LLM);
* локальная резолюция реплики-источника по ConversationContext v2 —
  автор (участник) + цитата (дословный фрагмент) + дата/время →
  EvidenceRef(source_kind="chat") в EvidenceMap текущего прогона;
* совпадения нет → честный отказ (attribution_not_found) БЕЗ домыслов
  и БЕЗ внешнего поиска (агрегатор не вызывается вовсе);
* реплика найдена → проверяется по существу ТОЛЬКО тезис; участники
  чата (включая упомянутого автора) не утекают в веб-запросы — регресс
  W4-инварианта privacy (test_privacy_authors_not_leaked);
* публичные фигуры («Путин сказал …») — НЕ чат-спор: обычный контур
  без изменений (байт-паритет);
* OFF (FACTCHECK_PIPELINE_V2_ENABLED=False) → слой не вызывается,
  прежний путь байт-в-байт (tool-маршрут и оркестратор).

Всё на моках: сеть (SafeFetcher-инъекция), LLM и реальные чаты не
используются.

TEST-LIFECYCLE: CONTRACT owner=CFG-06
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from config.settings import settings
from services import factcheck_attribution as fat
from services import temporal_factcheck as tf

CHAT_ID = -100444
TARGET_TG = 9100
TRIGGER_TG = 9101
FOUND_TS = 1700000000            # 14.11.2023 22:13 UTC
QUOTE = "в Килякете выпало 120 мм осадков за сутки"

CLAIM_FOUND = "Вася сказал, что в Килякете выпало 120 мм осадков за сутки"
CLAIM_MISS = "Вася сказал, что в Килякете выпало 500 мм снега за ночь"
CLAIM_PUBLIC = "Путин сказал, что в Килякете выпало 120 мм осадков за сутки"

_READY_KEYS = {"status", "reason", "claim", "factual_verdict",
               "temporal_status", "evaluated_period", "assessment_mode",
               "as_of", "date_source", "original_published_at",
               "repost_received_at", "uncertainty", "run_id", "cache_hit",
               "verdict"}


# ── Фикстуры/помощники ──────────────────────────────────────────────────────


class FakeSafeFetcher:
    """Инъекция вместо SafeFetcher (сеть off; прецедент w7-acceptance)."""
    calls = []

    async def fetch_text(self, url, **kw):
        FakeSafeFetcher.calls.append(url)
        return ("<html><body><p>Метеостанция Килякета подтвердила: "
                "120 мм осадков за сутки — рекорд наблюдений станции."
                "</p></body></html>")


@pytest.fixture
def v2_on(monkeypatch):
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    # сеть off: SafeFetcher под инъекцией на уровне источника
    monkeypatch.setattr("services.safe_fetch.SafeFetcher", FakeSafeFetcher)
    FakeSafeFetcher.calls = []
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


@pytest.fixture
def v2_off():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


@pytest_asyncio.fixture
async def db(tmp_path):
    from services.database import DatabaseService
    db = DatabaseService(str(tmp_path / "fc_attribution.db"))
    await db.initialize()
    yield db
    await db.close()


def _row(i, text, tg, author="Вася", ts=None, reply_to=None):
    return {"id": 100 + i, "user_id": 1, "chat_id": CHAT_ID, "text": text,
            "reply_to_id": reply_to, "timestamp": ts if ts is not None
            else 1000 + i, "media_type": "text", "author_name": author,
            "is_forward": False, "forward_source": None,
            "tg_message_id": tg}


def _default_rows():
    """Вася ДОСЛОВНО говорил тезис; Оля/Петя — болтовня; цель в окне."""
    return [
        _row(0, "болтовня про погоду", 8000, author="Оля"),
        _row(1, f"ну да {QUOTE}, я сам видел", 8001, author="Вася",
             ts=FOUND_TS),
        _row(2, "источник где?", 8002, author="Петя", reply_to=8001),
        _row(3, "целевое", TARGET_TG, author="Вася"),
    ]


def _miss_rows():
    return [
        _row(0, "болтовня про погоду", 8000, author="Оля"),
        _row(1, "а в Килякете дожди и туман", 8001, author="Вася"),
        _row(2, "целевое", TARGET_TG, author="Вася"),
    ]


class _Ctx:
    """Двойник ConversationContext с фикс. сообщениями (для tool-маршрута)."""

    def __init__(self, rows):
        from services.factcheck_context import (ContextMessage,
                                                ConversationContext)
        msgs = tuple(
            ContextMessage(message_id=r["id"], tg_message_id=r["tg_message_id"],
                           chat_id=CHAT_ID, author=r["author_name"],
                           timestamp=r["timestamp"], reply_to_tg_id=None,
                           is_forward=False, forward_source=None,
                           text=r["text"])
            for r in rows)
        self._ctx = ConversationContext(
            chat_id=CHAT_ID, target_tg_message_id=None,
            trigger_tg_message_id=None, messages=msgs,
            window={"before": 10, "after": 2}, newest_message_id=9999)

    def render_feed(self, **kwargs):
        return "<chat_context>FEED</chat_context>"

    @property
    def messages(self):
        return self._ctx.messages


class SpyAggregator:
    def __init__(self):
        self.searches = []

    async def search(self, query, max_symbols=2500):
        self.searches.append(query)
        return ("Рекорд осадков в Килякете\n"
                "Метеостанция подтвердила 120 мм за сутки\n"
                "https://example.org/meteo")


class FakeService:
    """Ловушка вместо FactCheckService: фиксирует точные вызовы."""

    def __init__(self, aggregator=None):
        self.aggregator = aggregator
        self.check_claim_calls = []
        self.envelope_calls = []

    async def check_claim(self, target_text, user_hint, forward_source, *,
                          chat_id=None, chat_context=None,
                          search_results=None):
        self.check_claim_calls.append({
            "target_text": target_text, "user_hint": user_hint,
            "forward_source": forward_source, "chat_id": chat_id,
            "chat_context": chat_context, "search_results": search_results})
        return "Тезис по данным источников подтверждается частично."

    async def check_claim_envelope(self, envelope, *, chat_context=None,
                                   stage_trace=None):
        self.envelope_calls.append({"envelope": envelope,
                                    "chat_context": chat_context})
        verdict = tf.verdict_from_payload(
            {"factual_verdict": "supported", "temporal_status": "unknown"},
            envelope)
        return tf.TemporalRunResult(envelope=envelope, verdict=verdict,
                                    verdict_text="Подтверждено.")


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


class FakeBot:
    id = 862000000

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("M", (), {"message_id": 555})()

    async def send_chat_action(self, chat_id, action, **kw):
        return True


def _req(claim):
    from services import factcheck_orchestrator as orch
    return orch.FactcheckRequest(
        chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
        target_tg_message_id=TARGET_TG, target_text=claim, kind="reply")


# ── Распознавание клейма (детерминированное, БЕЗ LLM) ───────────────────────

class TestDetect:
    def test_said_that_form(self):
        attr = fat.detect_attribution_claim(CLAIM_FOUND)
        assert attr is not None
        assert attr.author_mention == "Вася"
        assert "килякете" in attr.thesis_text.lower()
        assert "120" in attr.thesis_text

    def test_quoted_form_keeps_two_token_author(self):
        attr = fat.detect_attribution_claim(
            "Вася Пупкин говорил: «Байкал — самое глубокое озеро в мире»")
        assert attr is not None
        assert attr.author_mention == "Вася Пупкин"
        assert attr.thesis_text == "Байкал — самое глубокое озеро в мире"

    def test_no_attribution_claims(self):
        assert fat.detect_attribution_claim("дрожжи — это грибы") is None
        assert fat.detect_attribution_claim(
            "Байкал — самое глубокое озеро в мире") is None
        assert fat.detect_attribution_claim("") is None

    def test_pronoun_too_short_not_author(self):
        assert fat.detect_attribution_claim("Он сказал, что дождь идёт") \
            is None

    def test_public_figure_is_pattern_match_but_not_participant(self):
        attr = fat.detect_attribution_claim(CLAIM_PUBLIC)
        assert attr is not None and attr.author_mention == "Путин"
        ctx = _Ctx(_default_rows())
        assert fat.mention_is_participant(ctx, attr.author_mention) is False
        assert fat.mention_is_participant(ctx, "Вася") is True
        assert fat.mention_is_participant(None, "Вася") is False


# ── Локальная резолюция: автор + дословная цитата + дата ────────────────────

class TestResolve:
    def test_found_verbatim_quote_author_date(self):
        ctx = _Ctx(_default_rows())
        attr = fat.detect_attribution_claim(CLAIM_FOUND)
        match = fat.resolve_attribution(ctx, attr)
        assert match is not None
        assert match.author == "Вася"
        assert match.quote == QUOTE                    # дословный фрагмент
        assert match.timestamp == FOUND_TS
        assert match.tg_message_id == 8001

    def test_utterance_by_other_author_is_not_confirmation(self):
        """Отказ от домыслов: реплика ЕСТЬ, но автор другой → не
        подтверждение атрибуции."""
        rows = _default_rows()
        rows[1] = dict(rows[1], author_name="Оля")
        ctx = _Ctx(rows)
        match = fat.resolve_attribution(
            ctx, fat.detect_attribution_claim(CLAIM_FOUND))
        assert match is None

    def test_participant_exists_but_utterance_absent(self):
        ctx = _Ctx(_miss_rows())
        match = fat.resolve_attribution(
            ctx, fat.detect_attribution_claim(CLAIM_MISS))
        assert match is None

    def test_no_context_no_match(self):
        attr = fat.detect_attribution_claim(CLAIM_FOUND)
        assert fat.resolve_attribution(None, attr) is None
        assert fat.resolve_attribution(_Ctx(_default_rows()), None) is None


# ── Структурный evidence (ср. 06D.4: тезис → выдержка → источник) ───────────

class TestEvidenceBinding:
    def test_ref_contains_author_quote_date(self):
        ctx = _Ctx(_default_rows())
        match = fat.resolve_attribution(
            ctx, fat.detect_attribution_claim(CLAIM_FOUND))
        ref = fat.attribution_evidence_ref(match)
        assert ref.evidence_id == "chat-1"
        assert ref.source_kind == "chat"
        assert ref.url is None                          # внешней ссылки нет
        assert "Вася" in ref.support
        assert QUOTE in ref.support
        assert "14.11.2023" in ref.support              # дата/время реплики
        assert ref.published_at == FOUND_TS

    def test_attach_keeps_web_ids_and_prepends_chat(self):
        from services.factcheck_orchestrator import (CheckedVerdict,
                                                     EvidenceMap, EvidenceRef)
        verdict = CheckedVerdict(
            verdict_text="Итог.", route="envelope_temporal",
            evidence=EvidenceMap(
                refs=(EvidenceRef("ev-1", "https://example.org/a",
                                  "support"),),
                allowlist=("ev-1",)))
        match = fat.resolve_attribution(
            _Ctx(_default_rows()),
            fat.detect_attribution_claim(CLAIM_FOUND))
        merged = fat.attach_attribution_evidence(verdict, match)
        ids = [r.evidence_id for r in merged.evidence.refs]
        assert ids == ["chat-1", "ev-1"]                # ev-N не сдвигаются
        assert merged.evidence.allowlist == ("chat-1", "ev-1")
        assert merged.verdict_text == "Итог."

    def test_attach_fail_open_keeps_verdict(self):
        from services.factcheck_orchestrator import CheckedVerdict
        verdict = CheckedVerdict(verdict_text="Итог.", route="legacy_single")
        assert fat.attach_attribution_evidence(verdict, None) is verdict


# ── Privacy: участники чата не утекают во внешний поиск (W4-инвариант) ──────

class TestPrivacy:
    def test_external_safe_claim_strips_participants(self):
        ctx = _Ctx(_default_rows())
        attr = fat.detect_attribution_claim(CLAIM_FOUND)
        safe = fat.external_safe_claim(CLAIM_FOUND, ctx, attr)
        low = safe.lower()
        assert "вася" not in low and "сказал" not in low
        assert "килякет" in low                        # тезис сохранён

    def test_with_external_claim_replaces_frozen_envelope(self):
        envelope = tf.TemporalClaimEnvelope(
            claim_id="c1", chat_id=CHAT_ID, target_tg_message_id=None,
            target_revision=None, target_content_hash=None,
            trigger_tg_message_id=None, claim_text=CLAIM_FOUND,
            claim_span=None, source_type="free_text", attribution={},
            origin_type=None, origin_sender_user_id=None, origin_chat_id=None,
            origin_display_name=None, repost_received_at=None,
            original_published_at=None, original_published_precision=None,
            claim_period_from=None, claim_period_to=None,
            claim_period_precision=None, date_source="unknown",
            date_precision="unknown", date_timezone=None,
            date_uncertainty={"origin": "explicit_unknown"},
            requested_mode="contextual", analysis_as_of=1)
        ctx = _Ctx(_default_rows())
        attr = fat.detect_attribution_claim(CLAIM_FOUND)
        replaced = fat.with_external_claim(
            envelope, fat.external_safe_claim(CLAIM_FOUND, ctx, attr))
        assert "вася" not in replaced.claim_text.lower()
        assert replaced.chat_id == envelope.chat_id     # provenance цел
        assert replaced.analysis_as_of == envelope.analysis_as_of


# ── Оркестратор (v2 ON): found / miss / публичная фигура / envelope ─────────

class TestOrchestratorAttribution:
    @pytest.mark.asyncio
    async def test_found_thesis_checked_privacy_and_chat_evidence(
            self, v2_on, monkeypatch):
        """Реплика найдена: проверяется ТОЛЬКО тезис (без «Вася сказал»),
        участники не в поисковых запросах, chat-evidence в EvidenceMap
        вердикта (автор+цитата+дата)."""
        from services import factcheck_orchestrator as orch
        import services.factcheck_renderer as renderer

        agg = SpyAggregator()
        svc = FakeService(aggregator=agg)
        captured = {}
        real_render = renderer.render_factcheck

        def spy_render(presentation, verdict=None):
            captured["verdict"] = verdict
            return real_render(presentation, verdict)

        monkeypatch.setattr(renderer, "render_factcheck", spy_render)
        bot = FakeBot()
        await orch.run_factcheck(_req(CLAIM_FOUND), service=svc,
                                 db=FakeDB(rows=_default_rows()), bot=bot,
                                 cache=FakeCache())
        # тезис — без атрибуционной обвязки и без имён участников
        assert len(svc.check_claim_calls) == 1
        target = svc.check_claim_calls[0]["target_text"].lower()
        assert "вася" not in target and "сказал" not in target
        assert "килякет" in target
        # внешний поиск: ни один запрос не содержит участников чата
        assert agg.searches
        for q in agg.searches:
            assert "вася" not in q.lower()
        # chat-evidence привязан к вердикту (автор/цитата/дата)
        verdict = captured["verdict"]
        chat_refs = [r for r in verdict.evidence.refs
                     if r.evidence_id == "chat-1"]
        assert chat_refs and chat_refs[0].source_kind == "chat"
        assert "Вася" in chat_refs[0].support and QUOTE in chat_refs[0].support
        assert "14.11.2023" in chat_refs[0].support
        # доставка состоялась (renderer → Telegram)
        assert len(bot.sent) == 1

    @pytest.mark.asyncio
    async def test_miss_honest_refusal_no_paid_search(self, v2_on):
        """Совпадения нет: честный отказ из пула фраз, сервис проверки и
        внешний поиск НЕ вызываются (участники наружу не утекают)."""
        from services import factcheck_orchestrator as orch
        from services.smartmodule_phrases import (
            FACTCHECK_ATTRIBUTION_MISS_PHRASES)
        agg = SpyAggregator()
        svc = FakeService(aggregator=agg)
        bot = FakeBot()
        await orch.run_factcheck(_req(CLAIM_MISS), service=svc,
                                 db=FakeDB(rows=_miss_rows()), bot=bot,
                                 cache=FakeCache())
        assert svc.check_claim_calls == []
        assert svc.envelope_calls == []
        assert agg.searches == []                       # внешний поиск не звали
        assert len(bot.sent) == 1
        assert bot.sent[0]["text"] in FACTCHECK_ATTRIBUTION_MISS_PHRASES

    @pytest.mark.asyncio
    async def test_public_figure_goes_standard_web_route(self, v2_on):
        """«Путин сказал …» — не чат-спор (Путин не участник среза):
        обычный контур, клейм не меняется (байт-паритет)."""
        from services import factcheck_orchestrator as orch
        agg = SpyAggregator()
        svc = FakeService(aggregator=agg)
        bot = FakeBot()
        await orch.run_factcheck(_req(CLAIM_PUBLIC), service=svc,
                                 db=FakeDB(rows=_default_rows()), bot=bot,
                                 cache=FakeCache())
        assert len(svc.check_claim_calls) == 1
        target = svc.check_claim_calls[0]["target_text"].lower()
        assert "путин" in target                        # клейм не урезан
        assert len(bot.sent) == 1

    @pytest.mark.asyncio
    async def test_envelope_branch_searches_privacy_claim(self, v2_on,
                                                          monkeypatch):
        """Envelope-ветка: поисковые стадии получают тезис без участников
        (frozen-replace клейма, provenance не меняется)."""
        from services import factcheck_orchestrator as orch
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_enabled", lambda: True)
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_cache_enabled",
            lambda: True)
        origin = {"text": CLAIM_FOUND, "caption": None, "origin_type": None,
                  "origin_sent_at": None, "sent_at": FOUND_TS,
                  "current_revision": None, "content_hash": None,
                  "origin_sender_user_id": None, "origin_chat_id": None,
                  "origin_display_name": None, "author_name": "Вася",
                  "forward_source": None}
        agg = SpyAggregator()
        svc = FakeService(aggregator=agg)
        bot = FakeBot()
        await orch.run_factcheck(_req(CLAIM_FOUND), service=svc,
                                 db=FakeDB(rows=_default_rows(),
                                           origin_row=origin),
                                 bot=bot, cache=FakeCache())
        assert svc.envelope_calls and not svc.check_claim_calls
        claim_text = svc.envelope_calls[0]["envelope"].claim_text.lower()
        assert "вася" not in claim_text and "сказал" not in claim_text
        assert "килякет" in claim_text


# ── Tool-маршрут fact_check (v2 ON / OFF-паритет) ────────────────────────────

def _decision(decision_str):
    from services import factcheck_suitability as fsg
    return fsg.SuitabilityDecision(
        decision=decision_str, claim_type="checkable_fact",
        claim_items=(), scope="web", reason_code=None, confidence=0.9,
        target_ref={"chat_id": CHAT_ID})


def _patch_gate(monkeypatch, decision, ctx):
    from services import factcheck_suitability as fsg

    async def fake_eval(db_, chat_id, **kwargs):
        return decision, ctx

    monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_eval)


async def _dispatch(db, claim):
    from services.tool_router import ToolContext, ToolDeps, ToolRouter
    deps = ToolDeps(MagicMock(), MagicMock(), db=db, llm=MagicMock())
    router = ToolRouter(deps)
    raw = await router.dispatch("fact_check", {"claim": claim},
                                ToolContext(CHAT_ID, "фактчек",
                                            lore_verbatim_instruction=False))
    return json.loads(raw)


class TestToolRouteAttribution:
    @pytest.mark.asyncio
    async def test_miss_skips_paid_search_structured(self, monkeypatch, db,
                                                     v2_on):
        _patch_gate(monkeypatch, _decision("checkable_in_context"),
                    _Ctx(_miss_rows()))
        payload = await _dispatch(db, CLAIM_MISS)
        assert payload == {"status": "skipped",
                           "reason": "attribution_not_found"}

    @pytest.mark.asyncio
    async def test_found_ready_payload_privacy_envelope(self, monkeypatch,
                                                        db, v2_on):
        """Реплика найдена: ready-контракт tool-loop не меняется, поисковые
        стадии получают privacy-клейм (без участников чата)."""

        class _TrapService:
            """Ловушка вместо FactCheckService (паттерн tool_route-тестов)."""
            envelopes = []

            def __init__(self, search, llm):
                pass

            async def check_claim_envelope(self, envelope, *,
                                           chat_context=None,
                                           stage_trace=None):
                type(self).envelopes.append(envelope)
                verdict = tf.verdict_from_payload(
                    {"factual_verdict": "supported",
                     "temporal_status": "unknown"},
                    envelope)
                return tf.TemporalRunResult(envelope=envelope,
                                            verdict=verdict,
                                            verdict_text="Подтверждено.")

        monkeypatch.setattr("services.factcheck_service.FactCheckService",
                            _TrapService)
        _TrapService.envelopes = []
        _patch_gate(monkeypatch, _decision("checkable_in_context"),
                    _Ctx(_default_rows()))
        payload = await _dispatch(db, CLAIM_FOUND)
        assert payload["status"] == "ready"
        assert set(payload) == _READY_KEYS
        assert len(_TrapService.envelopes) == 1
        claim_text = _TrapService.envelopes[0].claim_text.lower()
        assert "вася" not in claim_text and "сказал" not in claim_text
        assert "килякет" in claim_text

    @pytest.mark.asyncio
    async def test_off_attribution_layer_not_engaged(self, monkeypatch, db,
                                                     v2_off):
        """OFF: слой не вызывается — прежний путь байт-в-байт, клейм с
        участником чата идёт как есть (gate не вызывается)."""
        from services import factcheck_suitability as fsg

        class _TrapService:
            def __init__(self, search, llm):
                pass

            async def check_claim_envelope(self, envelope, **kwargs):
                assert kwargs == {}         # прежний вызов одним аргументом
                verdict = tf.verdict_from_payload(
                    {"factual_verdict": "supported",
                     "temporal_status": "unknown"},
                    envelope)
                return tf.TemporalRunResult(envelope=envelope,
                                            verdict=verdict,
                                            verdict_text="Подтверждено.")

        monkeypatch.setattr("services.factcheck_service.FactCheckService",
                            _TrapService)

        async def must_not_run(*a, **kw):
            raise AssertionError("gate must not run with v2 OFF")

        monkeypatch.setattr(fsg, "evaluate_with_expansion", must_not_run)
        payload = await _dispatch(db, CLAIM_FOUND)
        assert payload["status"] == "ready"
        assert set(payload) == _READY_KEYS
        assert "вася" in payload["claim"].lower()       # клейм не менялся
