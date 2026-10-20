"""CFG-06 (REV-CFG-06 F1, 06B.1/06H.2): tool-интент `fact_check` в
Direct-чате при v2 ON исполняется ЕДИНЫМ контуром оркестратора —
suitability-gate + широкий контекст (evaluate_with_expansion) ДО платного
поиска; no_claim/ambiguous → структурный JSON агенту БЕЗ платного поиска;
иначе тот же check_claim_envelope с chat_context=feed. OFF → байт-паритет
2.58.98: прежний вызов одним позиционным аргументом, gate не вызывается.

Всё на моках: сеть, LLM и реальные чаты не используются.

TEST-LIFECYCLE: CONTRACT owner=CFG-06
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from config.settings import settings
from services import temporal_factcheck as tf

CLAIM = "Байкал — самое глубокое озеро в мире"

_READY_KEYS = {"status", "reason", "claim", "factual_verdict",
               "temporal_status", "evaluated_period", "assessment_mode",
               "as_of", "date_source", "original_published_at",
               "repost_received_at", "uncertainty", "run_id", "cache_hit",
               "verdict"}


# ── Фикстуры/помощники ──────────────────────────────────────────────────────

@pytest.fixture
def v2_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
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
    db = DatabaseService(str(tmp_path / "fc_tool_route_v2.db"))
    await db.initialize()
    yield db
    await db.close()


class _FakeService:
    """Ловушка вместо FactCheckService: фиксирует ТОЧНЫЙ вызов
    (args, kwargs) — kwargs == {} значит «байт-паритет старого вызова»."""
    calls: list = []

    def __init__(self, search, llm):
        pass

    async def check_claim_envelope(self, envelope, **kwargs):
        type(self).calls.append((envelope, kwargs))
        verdict = tf.verdict_from_payload(
            {"factual_verdict": "supported", "temporal_status": "unknown"},
            envelope)
        return tf.TemporalRunResult(envelope=envelope, verdict=verdict,
                                    verdict_text="Подтверждено.")


@pytest.fixture(autouse=True)
def _fake_service(monkeypatch):
    _FakeService.calls = []
    monkeypatch.setattr("services.factcheck_service.FactCheckService",
                        _FakeService)
    yield


class _FeedCtx:
    def __init__(self, feed):
        self._feed = feed

    def render_feed(self, **kwargs):
        return self._feed


def _decision(decision_str):
    from services import factcheck_suitability as fsg
    return fsg.SuitabilityDecision(
        decision=decision_str, claim_type="checkable_fact",
        claim_items=(), scope="web", reason_code=None, confidence=0.9,
        target_ref={"chat_id": 7})


def _patch_gate(monkeypatch, decision, ctx=None, calls=None):
    """Подмена evaluate_with_expansion (детерминированный ответ гейта)."""
    from services import factcheck_suitability as fsg

    async def fake_eval(db_, chat_id, **kwargs):
        if calls is not None:
            calls.append({"db": db_, "chat_id": chat_id, **kwargs})
        return decision, ctx

    monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_eval)


async def _dispatch(db, claim=CLAIM):
    from services.tool_router import ToolContext, ToolDeps, ToolRouter
    deps = ToolDeps(MagicMock(), MagicMock(), db=db, llm=MagicMock())
    router = ToolRouter(deps)
    raw = await router.dispatch("fact_check", {"claim": claim},
                                ToolContext(7, "фактчек",
                                            lore_verbatim_instruction=False))
    return json.loads(raw)


# ── Контракт v2 ON ──────────────────────────────────────────────────────────

class TestV2OnToolRoute:
    @pytest.mark.asyncio
    async def test_ready_goes_through_gate_and_passes_feed(
            self, monkeypatch, db, v2_on):
        """v2 ON: gate (evaluate_with_expansion) вызван ДО платного поиска
        с тем же db/chat_id/claim; check_claim_envelope получает
        chat_context=feed; наружный JSON-контракт tool-loop не меняется."""
        gate_calls: list = []
        _patch_gate(monkeypatch, _decision("checkable_in_context"),
                    ctx=_FeedCtx("<chat_context>FEED</chat_context>"),
                    calls=gate_calls)
        payload = await _dispatch(db)
        # gate вызван ровно один раз с правильной разводкой
        assert len(gate_calls) == 1
        call = gate_calls[0]
        assert call["db"] is db
        assert call["chat_id"] == 7
        assert call["claim_text"] == CLAIM
        assert call["user_hint"] is None
        assert call["target_tg_message_id"] is None
        # платный шаг — с контекстом из единого контура
        assert len(_FakeService.calls) == 1
        envelope, kwargs = _FakeService.calls[0]
        assert kwargs == {"chat_context": "<chat_context>FEED"
                                          "</chat_context>"}
        assert envelope.claim_text == CLAIM
        # наружный контракт tool-ответа (структура) не меняется
        assert payload["status"] == "ready"
        assert set(payload) == _READY_KEYS
        assert payload["factual_verdict"] == "supported"
        assert payload["claim"] == CLAIM
        assert payload["run_id"]

    @pytest.mark.asyncio
    async def test_no_claim_skips_paid_search(self, monkeypatch, db, v2_on):
        """06B.1/06J.3: no_claim → структурный JSON агенту БЕЗ платного
        поиска (check_claim_envelope не вызывается вовсе)."""
        _patch_gate(monkeypatch, _decision("no_claim_after_context"),
                    ctx=_FeedCtx("FEED"))
        payload = await _dispatch(db)
        assert payload == {"status": "skipped",
                           "reason": "no_claim_after_context"}
        assert _FakeService.calls == []

    @pytest.mark.asyncio
    async def test_ambiguous_skips_paid_search(self, monkeypatch, db, v2_on):
        """06B.1: ambiguous → структурный JSON (агент попросит уточнение),
        платный поиск не запускается."""
        _patch_gate(monkeypatch,
                    _decision("ambiguous_needs_clarification"),
                    ctx=_FeedCtx("FEED"))
        payload = await _dispatch(db)
        assert payload == {"status": "skipped",
                           "reason": "ambiguous_needs_clarification"}
        assert _FakeService.calls == []

    @pytest.mark.asyncio
    async def test_real_gate_wiring_single_contour(self, monkeypatch, db,
                                                   v2_on):
        """Ровно ОДИН вызов платного шага через РЕАЛЬНЫЙ
        evaluate_with_expansion (тот же объект, что у handler-маршрута);
        chat_context-kwarg присутствует (контекст пустого чата → None)."""
        from services import factcheck_suitability as fsg
        real_eval = fsg.evaluate_with_expansion
        gate_calls: list = []

        async def spy(db_, chat_id, **kwargs):
            gate_calls.append(chat_id)
            return await real_eval(db_, chat_id, **kwargs)

        monkeypatch.setattr(fsg, "evaluate_with_expansion", spy)
        payload = await _dispatch(db)
        assert gate_calls == [7]          # единый gate-объект, тот же чат
        assert payload["status"] == "ready"
        assert len(_FakeService.calls) == 1
        _envelope, kwargs = _FakeService.calls[0]
        assert "chat_context" in kwargs   # feed из реального контура

    @pytest.mark.asyncio
    async def test_gate_failure_fails_closed(self, monkeypatch, db, v2_on):
        """Сбой гейта при v2 ON — честный failed БЕЗ обхода gate платным
        поиском (check_claim_envelope не вызывается)."""
        from services import factcheck_suitability as fsg

        async def broken(*a, **kw):
            raise RuntimeError("gate down")

        monkeypatch.setattr(fsg, "evaluate_with_expansion", broken)
        payload = await _dispatch(db)
        assert payload == {"status": "failed",
                           "reason": "temporal_insufficient_evidence"}
        assert _FakeService.calls == []


# ── Контракт OFF: байт-паритет 2.58.98 ──────────────────────────────────────

class TestOffParity:
    @pytest.mark.asyncio
    async def test_off_single_positional_call_no_gate(self, monkeypatch,
                                                      db, v2_off):
        """OFF: прежний вызов байт-в-байт — (envelope,) без kwargs;
        gate не вызывается; payload-структура прежняя."""
        from services import factcheck_suitability as fsg

        async def must_not_run(*a, **kw):
            raise AssertionError("gate must not run with v2 OFF")

        monkeypatch.setattr(fsg, "evaluate_with_expansion", must_not_run)
        payload = await _dispatch(db)
        assert payload["status"] == "ready"
        assert set(payload) == _READY_KEYS
        assert len(_FakeService.calls) == 1
        envelope, kwargs = _FakeService.calls[0]
        assert kwargs == {}               # ровно прежний вызов одним аргументом
        assert envelope.claim_text == CLAIM

    @pytest.mark.asyncio
    async def test_off_and_v2_ready_payload_keys_identical(
            self, monkeypatch, db, v2_off):
        """Структурный паритет: набор ключей ready-ответа при OFF и v2 ON
        совпадает (tool-loop-контракт не меняется)."""
        _patch_gate(monkeypatch, _decision("checkable_in_context"),
                    ctx=_FeedCtx("FEED"))
        off_payload = await _dispatch(db)
        assert off_payload["status"] == "ready"
        _FakeService.calls.clear()
        object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
        try:
            v2_payload = await _dispatch(db)
        finally:
            object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED",
                               False)
        assert set(v2_payload) == set(off_payload) == _READY_KEYS
