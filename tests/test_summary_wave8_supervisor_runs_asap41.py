"""ASAP 4.1 волна 8 (T-4626, spec §9/§45; ADR-1028-8 D5) — Supervisor
FULL-RUNS: единая консолидированная матрица liveness/attempt-потолка.

Сценарии (§45):
  F1  primary fail → fallback по capability re-plan; attempt-потолок
      соблюдён (3 HTTP ≤ 4);
  F2  всё падает → честный финITE финал при РОВНО 4 HTTP (потолок
      ADR-1028-8 D5.3; финальное событие retry_time_budget_exhausted,
      старых misleading reason'ов нет);
  F3  полный L1-прогон через Supervisor (реальный llm_client-транспорт
      под httpx-моками): primary down ×2 + fallback → L1 usable, ≤4 HTTP;
  F4  watchdog stall → cancel → finite fallback (§45 opaque/stall);
  F5  hard fuse — последний рубеж (execution_deadline_exceeded);
  F6  adaptive-оценщик: timeout/failure НЕ обучают дедлайн (только
      успешные длительности), долгий живой вызов не убивается wall-clock.

R17: тесты не передают ключи/полные тексты наружу.
"""
import asyncio
import json
import types

import httpx
import pytest

import services.model_capacity as mc
import services.summary_l1_clusterizer as sl1
import services.summary_llm_supervisor as sup
from services.llm_client import LLMClient, LLMError, LLMTimeoutError

pytestmark = pytest.mark.asap41

RID = "run-wave8"
CHAT_ID = -100999001
MODULE = "summary"
STEP = "l1_clusterizer"

ATTEMPT_CEILING = 4


@pytest.fixture(autouse=True)
def _clean_sup_state(monkeypatch):
    sup.reset_telemetry()
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    yield
    sup.reset_telemetry()
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = httpx.Headers()
        self.content = json.dumps(payload).encode()

    def json(self):
        return self._payload


def _ok_payload(content="ответ модели"):
    return {"choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def _client(*, with_fallback: bool = True) -> LLMClient:
    client = LLMClient(
        base_url="https://primary.example/v1",
        api_key="k-primary",
        chat_model="mystery-large-1m",
        embed_model="text-embed",
        fallback_base_url="https://fallback.example/v1" if with_fallback
        else "",
        fallback_api_key="k-fb" if with_fallback else "",
        fallback_model="mystery-small-16k" if with_fallback else "",
    )
    client._record_global_usage = _async_noop()
    client._record_analytics = _async_noop()
    return client


def _async_noop():
    async def _noop(*args, **kwargs):
        return None
    return _noop


def _count_http(monkeypatch):
    counter = {"http": 0}
    urls = []

    async def _post_stub(self, url, *, json=None, timeout=None, **kwargs):
        counter["http"] += 1
        urls.append(url)
        return _FakeResponse(_ok_payload())

    monkeypatch.setattr(httpx.AsyncClient, "post", _post_stub)
    return counter, urls


def _events(monkeypatch):
    from services import pipeline_events as pe
    captured = []

    def fake_emit(event_name, **kwargs):
        captured.append((event_name, dict(kwargs)))

    monkeypatch.setattr(pe, "_emit", fake_emit)
    return captured


def _patch_replan(monkeypatch, effective_window=131072):
    from services import model_capacity as mcap

    async def fake_replan(*, base_url="", model="", required_input_tokens=0,
                          reserved_output_tokens=0, current_mode="",
                          segment_artifacts_created=False):
        margin = effective_window - required_input_tokens \
            - reserved_output_tokens
        mode = (mcap.MODE_WHOLE_WINDOW if margin >= 0
                else mcap.MODE_CAPACITY_OVERFLOW)
        reason = ("fits_effective_context" if margin >= 0
                  else "serialized_payload_exceeds_effective_context")
        return mcap.SummaryCapacityPlan(
            mode=mode, reason=reason, provider="test", model=model,
            effective_context_window=effective_window,
            required_input_tokens=required_input_tokens,
            reserved_output_tokens=reserved_output_tokens,
            safety_margin_tokens=margin, window_source="runtime",
            confidence="estimated", fallback_used=False)

    monkeypatch.setattr(mcap, "replan_summary_capacity", fake_replan)


# ── F1 (§27/§45): primary fail → fallback; attempt-потолок соблюдён ────────

@pytest.mark.asyncio
async def test_f1_primary_fail_fallback_within_ceiling(monkeypatch):
    """Primary transport падает, fallback вмещает → same whole-window task;
    РОВНО 3 HTTP (2 primary + 1 fallback) ≤ 4 (потолок D5.3)."""
    counter = {"http": 0}

    async def post_route(self, url, *, json=None, timeout=None, **kw):
        counter["http"] += 1
        if "primary.example" in url:
            raise httpx.ConnectError("primary down")
        return _FakeResponse(_ok_payload("fallback ответ"))

    monkeypatch.setattr(httpx.AsyncClient, "post", post_route)
    _patch_replan(monkeypatch)
    llm = _client()
    content, _ = await sup.execute_supervised(
        llm, messages=[{"role": "user", "content": "тест"}],
        operation="l1", correlation_id=RID, chat_id=None,
        module=MODULE, step=STEP)
    assert content == "fallback ответ"
    assert counter["http"] == 3
    assert counter["http"] <= sup.ATTEMPT_CEILING_HTTP
    # Fallback решает Supervisor (внутренний каскад выключен): только
    # /chat/completions, никаких выдуманных ping/status вызовов.
    states = sup.recent_states()
    assert states and states[-1]["operation"] == "l1"


# ── F2 (§27/§30/§45): всё падает → честный финал при РОВНО ≤4 HTTP ────────

@pytest.mark.asyncio
async def test_f2_everything_fails_honest_final_at_ceiling(monkeypatch):
    """Все уровни падают → конечный LLMError (не бесконечный цикл),
    РОВНО 4 HTTP попытки (верхняя граница — не больше!), финальное
    событие с честным retry_time_budget_exhausted (не «budget balance»)."""
    counter = {"http": 0}

    async def post_route(self, url, *, json=None, timeout=None, **kw):
        counter["http"] += 1
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx.AsyncClient, "post", post_route)
    events = _events(monkeypatch)
    llm = _client()
    with pytest.raises(LLMError):
        await sup.execute_supervised(
            llm, messages=[{"role": "user", "content": "тест"}],
            operation="l1", correlation_id=RID, chat_id=None,
            module=MODULE, step=STEP)
    assert counter["http"] == sup.ATTEMPT_CEILING_HTTP
    reasons = [kw.get("reason_code") for _, kw in events
               if kw.get("reason_code")]
    assert "retry_time_budget_exhausted" in reasons
    assert "total_budget_exceeded" not in reasons
    assert "budget_exhausted" not in reasons


# ── F3 (§45): полный L1-прогон под Supervisor (реальный транспорт) ────────

@pytest.mark.asyncio
async def test_f3_full_l1_pipeline_supervised_transport(monkeypatch):
    """run_l1 через настоящий llm_client-канал: L1-врезка ставит
    supervised_transport (max_retries=1, retry_statuses=()), primary-нога
    падает ×2 → fallback-ответ consuming map JSON; L1 usable, HTTP ≤4."""
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_BASE_URL",
                        "https://primary.example/v1", raising=False)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_MODEL_NAME",
                        "mystery-large-1m", raising=False)

    counter = {"http": 0}

    async def post_route(self, url, *, json=None, timeout=None, **kw):
        import json as _json
        counter["http"] += 1
        req = (json or {}).get("messages") or []
        user = ""
        for m in req:
            if m.get("role") != "system":
                user = m.get("content") or ""
        ids = []
        for line in user.splitlines():
            line = line.strip()
            if not line.startswith('{"'):
                continue
            try:
                item = _json.loads(line)
            except ValueError:
                continue
            if isinstance(item.get("message_id"), int):
                ids.append(item["message_id"])
        if "primary.example" in url:
            raise httpx.ConnectError("primary down")
        topics = [{"topic_id": "topic_001", "title": "живой прогон",
                   "message_ids": ids, "participants": [], "short_hint": ""}]
        map_payload = _json.dumps(
            {"schema_version": 1, "topics": topics, "events": [],
             "unassigned_message_ids": []}, ensure_ascii=False)
        return _FakeResponse(_ok_payload(map_payload))

    monkeypatch.setattr(httpx.AsyncClient, "post", post_route)
    _patch_replan(monkeypatch)
    rows = [{"id": 101 + i, "tg_message_id": 101 + i, "user_id": 7 + i % 2,
             "author_name": f"Автор{i % 2}", "text": f"строка {i}",
             "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
             "reply_to_id": None, "is_forward": 0, "forward_source": None}
            for i in range(6)]
    result = await sl1.run_l1(llm=_client(), rows=rows, chat_id=CHAT_ID,
                              correlation_id=RID)
    assert result.usable
    assert counter["http"] == 3
    assert counter["http"] <= sup.ATTEMPT_CEILING_HTTP
    cov = sl1.last_run_coverage()
    assert cov["coverage_percent"] == 100.0


# ── F4 (§45): stalled stream → cancel → finite fallback ───────────────────

@pytest.mark.asyncio
async def test_f4_watchdog_stall_cancel_finite_fallback(monkeypatch):
    """Stalled (нет подтверждённой активности > inactivity threshold) →
    cancel_attempt → конечный fallback; живой долгий вызов при этом НЕ
    убивается wall-clock (проверка F6 branch)."""
    counter = {"http": 0}

    async def post_route(self, url, *, json=None, timeout=None, **kw):
        counter["http"] += 1
        if "primary.example" in url:
            await asyncio.sleep(3.0)
            return _FakeResponse(_ok_payload())
        return _FakeResponse(_ok_payload("fallback после stall"))

    monkeypatch.setattr(httpx.AsyncClient, "post", post_route)
    monkeypatch.setattr(sup, "resolve_attempt_deadline",
                        lambda *a, **k: (0.05, "cold_default"))
    llm = _client()
    content, _ = await sup.execute_supervised(
        llm, messages=[{"role": "user", "content": "тест"}],
        operation="l1", correlation_id=RID, chat_id=None,
        module=MODULE, step=STEP)
    assert content == "fallback после stall"
    assert counter["http"] <= sup.ATTEMPT_CEILING_HTTP


# ── F5 (§25/§30): hard fuse — последний рубеж ─────────────────────────────

@pytest.mark.asyncio
async def test_f5_hard_fuse_last_resort_reason(monkeypatch):
    """Fuse < врéмени попытки → LLMTimeoutError; reason
    execution_deadline_exceeded (не misleading «budget»)."""
    async def post_route(self, url, *, json=None, timeout=None, **kw):
        await asyncio.sleep(1.5)
        return _FakeResponse(_ok_payload())

    monkeypatch.setattr(httpx.AsyncClient, "post", post_route)
    monkeypatch.setattr(sup, "hard_deadline_seconds", lambda: 0.05)
    events = _events(monkeypatch)
    llm = _client()
    with pytest.raises(LLMTimeoutError):
        await sup.execute_supervised(
            llm, messages=[{"role": "user", "content": "тест"}],
            operation="l1", correlation_id=RID, chat_id=None,
            module=MODULE, step=STEP)
    blob = json.dumps(events, ensure_ascii=False, default=str)
    assert "execution_deadline_exceeded" in blob
    assert "total_budget_exceeded" not in blob


# ── F6 (§29/§45): adaptive-оценщик — timeout НЕ обучает ───────────────────

@pytest.mark.asyncio
async def test_f6_timeouts_never_train_estimator_long_generation_alive():
    """Оценщик строится ТОЛЬКО по успешным длительностям (§29):
    timeout/failure не меняют дедлайн; успешные 400s-образцы дают
    дедлайн ≥ 600s — длинная живая генерация (622s-класс) не убивается
    wall-clock (attempt-дедлайн адаптивный, не глобальный)."""
    for d in (400.0, 405.0, 410.0, 415.0):
        sup.record_outcome("primary.example", "mystery-large-1m", "l1",
                           token_bucket="tok_l", ok=True, duration_s=d)
    before, source = sup.resolve_attempt_deadline(
        "primary.example", "mystery-large-1m", "l1", token_bucket="tok_l")
    assert source == "adaptive_p95"
    assert before >= 600.0
    for _ in range(5):
        sup.record_outcome("primary.example", "mystery-large-1m", "l1",
                           token_bucket="tok_l", ok=False, duration_s=None,
                           timeout=True)
    after, _ = sup.resolve_attempt_deadline(
        "primary.example", "mystery-large-1m", "l1", token_bucket="tok_l")
    assert after == before
    # Изоляция по бакету/операции: чужой бакет — cold default.
    cold, cold_source = sup.resolve_attempt_deadline(
        "primary.example", "mystery-large-1m", "l2_review",
        token_bucket="tok_l")
    assert cold_source == "cold_default"
    snap = sup.telemetry_snapshot()
    entry = snap["primary.example|mystery-large-1m|l1|tok_l"]
    assert entry["samples"] == 4
    assert entry["timeouts"] == 5          # reliability-signal, не обучение
