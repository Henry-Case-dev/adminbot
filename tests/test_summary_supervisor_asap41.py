"""ASAP 4.1 волна 4 (T-4612–T-4615, spec §4 зона D; ADR-1028-8 D5) —
LLMExecutionSupervisor: единый orchestration-owner LLM-вызовов Summary.

Покрытие:
* T-4612 core — attempt-потолок ≤4 HTTP на логический вызов (реальным
  подсчётом HTTP на transport-уровне), демонтаж вложенных retry
  (lower слой только transport: max_retries=1, retry_statuses=();
  внутренний fallback-каскад llm_client выключен для supervised-канала);
  kill-switch OFF = прежний канал байт-в-бит.
* T-4613 — execution modes/capability discovery: честные декларации
  (sync-opaque транспорт = Mode C), Mode A/B — контрактные слоты
  (режим следует декларации; без верифицированного адаптера — Mode C);
  никаких выдуманных ping-вызовов.
* T-4614 — adaptive watchdog: cold defaults/adaptive p95 по успешным
  длительностям per (provider, model, operation, token-bucket), клампы
  hard fuse [600, 7200] / inactivity [60, 900], ветки watchdog'а
  (stall / attempt deadline / streaming inactivity), telemetry
  (ttfa/queue/duration), R17-safe события.
* T-4615 — rename `total_budget_exceeded` → `execution_deadline_exceeded`
  (fuse) / `retry_time_budget_exhausted` (исчерпание попыток) в
  supervised-эмиccии; read-side alias; Analytics human-описания;
  не-Summary логи llm_client не тронуты (байт-в-бит).

R17: тесты не передают ключи/полные тексты наружу.
"""
import asyncio
import json
import logging
import types

import httpx
import pytest

import services.summary_llm_supervisor as sup
from services.llm_client import (
    LLMClient,
    LLMError,
    LLMTimeoutError,
)

pytestmark = pytest.mark.asap41

RID = "run-4612"
CHAT_ID = -1005550001
MODULE = "summary"
STEP = "l1_clusterizer"


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
    # PG-аналитика/global-usage в тестах не нужны (fail-open контракт,
    # но stub для детерминизма).
    client._record_global_usage = _async_noop()
    client._record_analytics = _async_noop()
    return client


def _async_noop():
    async def _noop(*args, **kwargs):
        return None
    return _noop


def _count_http(monkeypatch, *, post=None):
    """Реальный подсчёт HTTP: транспорт-уровень (httpx.AsyncClient.post)."""
    counter = {"http": 0}
    seen_kwargs = []

    async def _post_stub(self, url, *, json=None, timeout=None, **kwargs):
        counter["http"] += 1
        seen_kwargs.append({"timeout": timeout, "kwargs": kwargs})
        if post is not None:
            result = post(self, url, json=json, timeout=timeout, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, BaseException):
                raise result
            return result
        return _FakeResponse(_ok_payload())

    monkeypatch.setattr(httpx.AsyncClient, "post", _post_stub)
    return counter, seen_kwargs


@pytest.fixture(autouse=True)
def _clean_sup_state(monkeypatch):
    sup.reset_telemetry()
    yield
    sup.reset_telemetry()


def _patch_replan(monkeypatch, effective_window=131072):
    """Deterministic re-plan fallback capacity (T-4605 API)."""
    from services import model_capacity as mc

    async def fake_replan(*, base_url="", model="", required_input_tokens=0,
                          reserved_output_tokens=0, current_mode="",
                          segment_artifacts_created=False):
        margin = effective_window - required_input_tokens \
            - reserved_output_tokens
        mode = (mc.MODE_WHOLE_WINDOW if margin >= 0
                else mc.MODE_CAPACITY_OVERFLOW)
        reason = ("fits_effective_context" if margin >= 0
                  else "serialized_payload_exceeds_effective_context")
        return mc.SummaryCapacityPlan(
            mode=mode, reason=reason, provider="test", model=model,
            effective_context_window=effective_window,
            required_input_tokens=required_input_tokens,
            reserved_output_tokens=reserved_output_tokens,
            safety_margin_tokens=margin, window_source="runtime",
            confidence="estimated", fallback_used=False)

    monkeypatch.setattr(mc, "replan_summary_capacity", fake_replan)


# ── T-4612: attempt-потолок ≤4 HTTP (реальный подсчёт HTTP) ─────────────────


class TestAttemptCeiling:
    @pytest.mark.asyncio
    async def test_logical_call_never_exceeds_4_http(self, monkeypatch):
        """Один логический вызов: primary transport-retry ×2 + fallback ×2
        = РОВНО 4 HTTP (потолок ADR-1028-8 D5.3; верхняя граница задокументиро-
        вана — прецедент R4-D-057). Транспорт всегда падает → конечный
        LLMTransportError (finite), не бесконечный цикл."""
        counter, _ = _count_http(
            monkeypatch,
            post=lambda self, url, **kw: (_ for _ in ()).throw(
                httpx.ConnectError("down")))
        llm = _client()
        with pytest.raises(LLMError):
            await sup.execute_supervised(
                llm, messages=[{"role": "user", "content": "тест"}],
                operation="l1", correlation_id=RID, chat_id=None,
                module=MODULE, step=STEP)
        # ≤4 HTTP: 2 primary (1+transport-retry) + 2 fallback (1+retry)
        assert counter["http"] == sup.ATTEMPT_CEILING_HTTP
        assert counter["http"] <= 4

    @pytest.mark.asyncio
    async def test_status_500_no_status_retry_single_fallback(self, monkeypatch):
        """retry_statuses=() → нижний слой НЕ ретраит статусы: 500 отдаётся
        наверх немедленно (1 HTTP primary + 1 fallback = 2, без каскада)."""
        counter, _ = _count_http(
            monkeypatch,
            post=lambda self, url, **kw: _FakeResponse(
                {"error": "boom"}, status=500))
        llm = _client()
        with pytest.raises(LLMError):
            await sup.execute_supervised(
                llm, messages=[{"role": "user", "content": "тест"}],
                operation="l1", correlation_id=RID, chat_id=None,
                module=MODULE, step=STEP)
        assert counter["http"] == 2      # было бы ≤6 при прежних вложенных

    @pytest.mark.asyncio
    async def test_success_first_http(self, monkeypatch):
        counter, seen = _count_http(monkeypatch)
        llm = _client()
        content, usage = await sup.execute_supervised(
            llm, messages=[{"role": "user", "content": "тест"}],
            operation="l1", correlation_id=RID, chat_id=None,
            module=MODULE, step=STEP)
        assert content == "ответ модели"
        assert counter["http"] == 1
        # Глобальный (не-dedicated) канал идёт через generate → usage
        # паритет прежнему контракту generate (str; usage уже записан
        # аналитикой клиента) → supervisor возвращает usage=None.
        assert usage is None

    @pytest.mark.asyncio
    async def test_transport_contract_of_primary_attempt(self, monkeypatch):
        """Нижний слой — ТОЛЬКО transport: max_retries=1, retry_statuses=(),
        per-call budget/timeout, supervised-метка rename."""
        captured = {}

        async def fake_post(path, payload, api_key=None, base_url=None,
                            channel="chat", **kwargs):
            captured.update(kwargs)
            return _FakeResponse(_ok_payload())

        llm = _client()
        llm._post = fake_post
        await sup.execute_supervised(
            llm, messages=[{"role": "user", "content": "тест"}],
            operation="writer", correlation_id=RID, chat_id=None,
            module=MODULE, step="l2_writer")
        assert captured["max_retries"] == 1
        assert captured["retry_statuses"] == ()
        assert captured["budget_reason_label"] == "summary_supervised"
        assert captured["budget"] == pytest.approx(900.0)
        assert captured["timeout"] == pytest.approx(900.0)

    @pytest.mark.asyncio
    async def test_generate_supervised_disables_internal_cascade(self):
        """Внутренний fallback-каскад llm_client для supervised-канала
        выключен (no retry multiplication): generate с supervised_transport
        НЕ вызывает _fallback_with_retries — fallback решает Supervisor."""

        async def fail_post(path, payload, **kwargs):
            raise LLMError("primary down")

        async def forbidden_cascade(payload):
            raise AssertionError("внутренний каскад запрещён (D5.3)")

        llm = _client()
        llm._post = fail_post
        llm._fallback_with_retries = forbidden_cascade
        with pytest.raises(LLMError):
            await llm.generate([{"role": "user", "content": "тест"}],
                               module=MODULE, step=STEP,
                               supervised_transport=sup.transport_contract(60.0))


class TestFallbackDecision:
    @pytest.mark.asyncio
    async def test_fallback_fits_same_whole_window_task(self, monkeypatch):
        """§27/§28: fallback capacity вмещает → тот же whole-window payload
        (семантика задачи инвариантна); РОВНО 1 fallback-provider HTTP."""
        counter = {"http": 0}

        async def post_route(self, url, *, json=None, timeout=None, **kw):
            counter["http"] += 1
            if "primary.example" in url:
                raise httpx.ConnectError("primary down")
            return _FakeResponse(_ok_payload("fallback ответ"))

        monkeypatch.setattr(httpx.AsyncClient, "post", post_route)
        _patch_replan(monkeypatch, effective_window=131072)
        llm = _client()
        content, usage = await sup.execute_supervised(
            llm, messages=[{"role": "user", "content": "тест"}],
            operation="l1", correlation_id=RID, chat_id=None,
            module=MODULE, step=STEP)
        assert content == "fallback ответ"
        # 2 primary + 1 fallback = 3 ≤ 4
        assert counter["http"] == 3

    @pytest.mark.asyncio
    async def test_fallback_smaller_capacity_no_oversized_send(self, monkeypatch):
        """§27: fallback НЕ вмещает → oversized payload НЕ отправляется;
        честный отказ (исходная primary-ошибка) + capacity-событие."""
        sent_fallback = []

        async def post_route(self, url, *, json=None, timeout=None, **kw):
            if "primary.example" in url:
                raise httpx.ConnectError("primary down")
            sent_fallback.append(url)
            return _FakeResponse(_ok_payload("should not happen"))

        monkeypatch.setattr(httpx.AsyncClient, "post", post_route)
        _patch_replan(monkeypatch, effective_window=512)
        llm = _client()
        big = [{"role": "user", "content": "наполнение окна " * 5000}]
        with pytest.raises(LLMError):
            await sup.execute_supervised(
                llm, messages=big, operation="l1", correlation_id=RID,
                chat_id=None, module=MODULE, step=STEP)
        assert not sent_fallback, "oversized payload не должен был уйти"


class TestKillSwitchOff:
    @pytest.mark.asyncio
    async def test_off_uses_legacy_channel_byte_identical(self, monkeypatch):
        """OFF → Summary-вызовы через прежний llm_client-контур: generate
        БЕЗ supervised_transport (бюджеты/каскады 2.58.46 байт-в-бит)."""
        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_LLM_SUPERVISOR_ENABLED", False)
        seen = {}

        class ScriptedLLM:
            async def generate(self, messages, **kw):
                seen["kw"] = kw
                return "legacy ответ"

        llm = ScriptedLLM()
        wrapped = sup.make_wrapped(llm, None, RID, operation="l1",
                                   module=MODULE, step=STEP)
        assert wrapped is None      # врезки нет — прежний канал
        result = await llm.generate([{"role": "user", "content": "тест"}],
                                    module=MODULE, step=STEP)
        assert result == "legacy ответ"

    @pytest.mark.asyncio
    async def test_off_post_keeps_old_reason_strings(self, monkeypatch, caplog):
        """Не-Summary семантика: без supervised-метки — прежние строки
        total_budget_exceeded / budget_exhausted (байт-в-бит, R6-D-009
        фиксирует только Summary-эмиccию)."""
        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_LLM_SUPERVISOR_ENABLED", False)
        llm = _client()
        llm.backoff_base = 0.0

        async def slow_post(self, url, *, json=None, timeout=None, **kw):
            await asyncio.sleep(0.3)
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx.AsyncClient, "post", slow_post)
        with caplog.at_level(logging.ERROR, logger="services.llm_client"):
            with pytest.raises(LLMError):
                await llm._post("/chat/completions", {"model": "m"},
                                budget=0.1, max_retries=0)
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "total_budget_exceeded" in joined
        assert "execution_deadline_exceeded" not in joined


class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_l1_writes_go_through_supervisor(self, monkeypatch):
        """L1 вызовы идут через Supervisor: supervised_transport присутствует
        (attempt-потолок ≤4 HTTP), запись через generate-канал."""
        seen = {}

        class MockLLM:
            async def generate(self, messages, **kw):
                seen["kw"] = kw
                return json.dumps({"schema_version": 1, "topics": [],
                                   "events": [],
                                   "unassigned_message_ids": [101, 102]},
                                  ensure_ascii=False)

        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_L1_SEMANTIC_MAP_ENABLED", False)
        from services import summary_l1_clusterizer as sl1
        from services.summary_l1_contract import validate_l1_response
        rows = [{"id": 101, "tg_message_id": 101, "user_id": 1,
                 "author_name": "Вася", "text": "привет",
                 "timestamp": 1_700_000_000, "media_type": "text",
                 "reply_to_id": None, "is_forward": 0, "forward_source": None},
                {"id": 102, "tg_message_id": 102, "user_id": 2,
                 "author_name": "Макс", "text": "и тебе",
                 "timestamp": 1_700_000_060, "media_type": "text",
                 "reply_to_id": None, "is_forward": 0,
                 "forward_source": None}]
        result = await sl1.run_l1(
            llm=MockLLM(), rows=rows, chat_id=CHAT_ID, correlation_id=RID,
            budget=("tokens", 100000), system_prompt="канон",
            _allow_chunking=False)
        assert seen["kw"]["supervised_transport"]["max_retries"] == 1
        assert seen["kw"]["supervised_transport"][
            "retry_statuses"] == ()
        assert seen["kw"]["supervised_transport"][
            "budget_reason_label"] == "summary_supervised"

    @pytest.mark.asyncio
    async def test_writer_and_reviewer_go_through_supervisor(self):
        seen = []

        class MockLLM:
            async def generate(self, messages, **kw):
                seen.append(kw)
                return "{}"

        from services.summary_l2_writer import L2Slot, _make_llm_call as l2_call
        from services.summary_l2_review import _make_llm_call as rev_call
        slot = L2Slot(base_url="https://primary.example/v1",
                      model="mystery-large-1m", api_key="k", dedicated=False)
        await l2_call(MockLLM(), slot, RID)([{"role": "user", "content": "x"}])
        await rev_call(MockLLM(), slot, RID,
                       operation="reviewer")(
            [{"role": "user", "content": "x"}])
        assert seen[0]["supervised_transport"]["max_retries"] == 1
        assert seen[1]["supervised_transport"]["max_retries"] == 1

    @pytest.mark.asyncio
    async def test_legacy_generator_path_supervised(self):
        """Legacy/Single/Two-call путь генератора идёт через Supervisor."""
        seen = {}

        class MockLLM:
            async def generate(self, messages, **kw):
                seen["kw"] = kw
                return "текст"

        from services.summary_generator import SummaryGenerator
        gen = types.SimpleNamespace(llm=MockLLM())
        raw = await SummaryGenerator._supervised_generate(
            gen, [{"role": "user", "content": "x"}],
            correlation_id=RID, step="single")
        assert raw == "текст"
        assert seen["kw"]["supervised_transport"]["max_retries"] == 1
        assert seen["kw"]["supervised_transport"][
            "budget_reason_label"] == "summary_supervised"


# ── T-4613: modes + capability discovery ────────────────────────────────────


class TestModes:
    def test_honest_sync_declaration(self):
        caps = sup.declare_execution_capabilities("primary.example",
                                                  "mystery-large-1m")
        assert caps.opaque_sync_only is True
        assert caps.supports_streaming_liveness is False
        assert caps.supports_async_status is False
        assert caps.supports_cancel is False
        assert caps.source == "sync_transport_observed"
        assert sup.select_execution_mode(caps) == sup.MODE_SYNC

    def test_mode_flags_without_verified_adapter_still_sync(self, monkeypatch):
        """ASAP 4.2 Step 2c-1 (AM-2): verified OpenAI-compatible chat-route →
        при `SUMMARY_LLM_STREAMING_MODE_ENABLED=ON` Mode B активируется;
        Mode A (async job/status) остаётся неподтверждённым слотом."""
        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_LLM_ASYNC_MODE_ENABLED", True)
        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_LLM_STREAMING_MODE_ENABLED", True)
        caps = sup.declare_execution_capabilities()
        assert caps.supports_streaming_liveness is True
        assert caps.supports_async_status is False
        assert sup.select_execution_mode(caps) == sup.MODE_STREAM
        # async-флаг без verified job/status adapter режима не даёт
        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_LLM_STREAMING_MODE_ENABLED", False)
        caps_async_only = sup.declare_execution_capabilities()
        assert caps_async_only.supports_async_status is False
        assert sup.select_execution_mode(caps_async_only) == sup.MODE_SYNC

    def test_mode_follows_declaration_slot(self, monkeypatch):
        """Режим Supervisor'а следует декларации адаптера (контрактный
        слот Mode A)."""
        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_LLM_ASYNC_MODE_ENABLED", True)
        caps = types.SimpleNamespace(
            supports_streaming_liveness=False,
            supports_async_status=True,
            supports_cancel=True,
            opaque_sync_only=False,
            source="verified_adapter")
        assert sup.select_execution_mode(caps) == sup.MODE_ASYNC_JOB
        caps_b = types.SimpleNamespace(
            supports_streaming_liveness=True,
            supports_async_status=False,
            supports_cancel=True,
            opaque_sync_only=False,
            source="verified_adapter")
        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_LLM_ASYNC_MODE_ENABLED", False)
        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_LLM_STREAMING_MODE_ENABLED", True)
        assert sup.select_execution_mode(caps_b) == sup.MODE_STREAM

    @pytest.mark.asyncio
    async def test_no_invented_ping_http(self, monkeypatch):
        """«Пинговать генерацию» запрещено: за логический вызов — РОВНО
        HTTP-вызовы попыток, никаких status/ping запросов."""
        urls = []

        async def post_route(self, url, *, json=None, timeout=None, **kw):
            urls.append(url)
            return _FakeResponse(_ok_payload())

        monkeypatch.setattr(httpx.AsyncClient, "post", post_route)
        llm = _client()
        await sup.execute_supervised(
            llm, messages=[{"role": "user", "content": "тест"}],
            operation="l1", correlation_id=RID, chat_id=None,
            module=MODULE, step=STEP)
        assert len(urls) == 1
        assert urls[0].endswith("/chat/completions")


# ── T-4614: adaptive watchdog + hard fuse + telemetry ───────────────────────


class TestWatchdog:
    def test_cold_default_when_no_samples(self):
        deadline, source = sup.resolve_attempt_deadline(
            "primary.example", "mystery-large-1m", "l1",
            token_bucket="tok_m")
        assert source == "cold_default"
        assert deadline >= sup.inactivity_threshold_seconds()
        assert deadline <= sup.hard_deadline_seconds()

    @pytest.mark.asyncio
    async def test_adaptive_p95_from_successful_durations(self):
        """Оценщик строится ТОЛЬКО по успешным длительностям (REUSE
        media_execution: p95 × safety; timeout/failure не обучают)."""
        for d in (400.0, 410.0, 420.0, 430.0):
            sup.record_outcome("primary.example", "mystery-large-1m", "l1",
                               token_bucket="tok_l", ok=True, duration_s=d)
        sup.record_outcome("primary.example", "mystery-large-1m", "l1",
                           token_bucket="tok_l", ok=False, duration_s=None,
                           timeout=True)
        deadline, source = sup.resolve_attempt_deadline(
            "primary.example", "mystery-large-1m", "l1",
            token_bucket="tok_l")
        assert source == "adaptive_p95"
        assert deadline >= 400.0 * 1.5      # живая генерация 622s не убивается
        # Другой бакет — cold default (изоляция по token-bucket).
        other, other_source = sup.resolve_attempt_deadline(
            "primary.example", "mystery-large-1m", "l1",
            token_bucket="tok_s")
        assert other_source == "cold_default"

    def test_clamps_hard_fuse_and_inactivity(self, monkeypatch):
        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_LLM_HARD_DEADLINE_SECONDS", 99999.0)
        assert sup.hard_deadline_seconds() == 7200.0
        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_LLM_HARD_DEADLINE_SECONDS", 10.0)
        assert sup.hard_deadline_seconds() == 600.0
        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_LLM_INACTIVITY_SECONDS", 9999.0)
        assert sup.inactivity_threshold_seconds() == 900.0
        monkeypatch.setattr(type(sup.settings),
                            "SUMMARY_LLM_INACTIVITY_SECONDS", 5.0)
        assert sup.inactivity_threshold_seconds() == 60.0

    def test_evaluate_watchdog_branches(self):
        st = sup.SupervisedCallState(
            request_id="r", provider="p", model="m", operation="l1",
            mode=sup.MODE_SYNC, started_at=0.0)
        # sync: attempt-дедлайн
        st.attempt_started_at = 0.0
        assert sup.evaluate_watchdog(st, now=10.0, mode=sup.MODE_SYNC,
                                     attempt_deadline=600.0,
                                     inactivity=300.0) is None
        st.state = sup.STATE_RUNNING
        assert sup.evaluate_watchdog(st, now=601.0, mode=sup.MODE_SYNC,
                                     attempt_deadline=600.0,
                                     inactivity=300.0) == "stalled"
        # streaming: только по неактивности (elapsed НЕ убивает живой поток)
        st.mode = sup.MODE_STREAM
        st.last_activity_at = 599.0
        assert sup.evaluate_watchdog(st, now=601.0, mode=sup.MODE_STREAM,
                                     attempt_deadline=10.0,
                                     inactivity=300.0) is None
        st.last_activity_at = 200.0
        assert sup.evaluate_watchdog(st, now=601.0, mode=sup.MODE_STREAM,
                                     attempt_deadline=10.0,
                                     inactivity=300.0) == "stalled"

    @pytest.mark.asyncio
    async def test_stall_detection_finite_fallback(self, monkeypatch):
        """Stalled → cancel попытки → finite fallback (§45: opaque sync →
        adaptive watchdog + finite fallback)."""
        async def slow_post(self, url, *, json=None, timeout=None, **kw):
            if "primary.example" in url:
                await asyncio.sleep(5.0)
                return _FakeResponse(_ok_payload())
            return _FakeResponse(_ok_payload("fallback жив"))

        monkeypatch.setattr(httpx.AsyncClient, "post", slow_post)
        monkeypatch.setattr(sup, "resolve_attempt_deadline",
                            lambda *a, **k: (0.05, "cold_default"))
        llm = _client()
        content, _usage = await sup.execute_supervised(
            llm, messages=[{"role": "user", "content": "тест"}],
            operation="l1", correlation_id=RID, chat_id=None,
            module=MODULE, step=STEP)
        assert content == "fallback жив"

    @pytest.mark.asyncio
    async def test_hard_fuse_trip_reason(self, monkeypatch):
        """Hard fuse — последний рубеж: execution_deadline_exceeded."""
        async def slow_post(self, url, *, json=None, timeout=None, **kw):
            await asyncio.sleep(2.0)
            return _FakeResponse(_ok_payload())

        monkeypatch.setattr(httpx.AsyncClient, "post", slow_post)
        monkeypatch.setattr(sup, "hard_deadline_seconds", lambda: 0.05)
        llm = _client()
        with pytest.raises(LLMTimeoutError):
            await sup.execute_supervised(
                llm, messages=[{"role": "user", "content": "тест"}],
                operation="l1", correlation_id=RID, chat_id=None,
                module=MODULE, step=STEP)

    def test_telemetry_buckets_and_signals(self):
        sup.record_outcome("p", "m", "l1", token_bucket="tok_m", ok=True,
                           duration_s=100.0, ttfa_s=100.0, queue_s=0.01)
        sup.record_outcome("p", "m", "l1", token_bucket="tok_m", ok=True,
                           duration_s=200.0, ttfa_s=200.0, queue_s=0.02)
        sup.record_outcome("p", "m", "l1", token_bucket="tok_m", ok=True,
                           duration_s=300.0, ttfa_s=300.0, queue_s=0.03)
        sup.record_outcome("p", "m", "l1", token_bucket="tok_m", ok=False,
                           duration_s=None, timeout=True)
        snap = sup.telemetry_snapshot()
        key = "p|m|l1|tok_m"
        assert key in snap
        entry = snap[key]
        assert entry["samples"] == 3
        assert entry["p50_s"] == 200.0
        assert entry["p95_s"] == 300.0
        assert entry["timeouts"] == 1
        assert entry["ttfa_p50_s"] == 200.0
        assert entry["queue_p50_s"] == pytest.approx(0.02)

    @pytest.mark.asyncio
    async def test_wait_queue_and_ttfa_recorded(self, monkeypatch):
        counter, _ = _count_http(monkeypatch)
        llm = _client()
        await sup.execute_supervised(
            llm, messages=[{"role": "user", "content": "тест"}],
            operation="l1", correlation_id=RID, chat_id=None,
            module=MODULE, step=STEP)
        snap = sup.telemetry_snapshot()
        entry = next(iter(snap.values()))
        assert entry["samples"] == 1
        assert entry["ttfa_p50_s"] is not None and entry["ttfa_p50_s"] > 0
        assert entry["queue_p50_s"] is not None

    @pytest.mark.asyncio
    async def test_events_r17_safe_no_message_texts(self, monkeypatch):
        """R17: в событиях Supervisor'а нет текстов сообщений/промптов."""
        emitted = []

        async def post_route(self, url, *, json=None, timeout=None, **kw):
            return _FakeResponse(_ok_payload("секретное содержимое xyz"))

        monkeypatch.setattr(httpx.AsyncClient, "post", post_route)

        def fake_emit(event_name, **kwargs):
            emitted.append((event_name, kwargs))

        from services import pipeline_events
        monkeypatch.setattr(pipeline_events, "_emit", fake_emit)
        llm = _client()
        await sup.execute_supervised(
            llm, messages=[{"role": "user",
                            "content": "УНИКАЛЬНЫЙ-МАРКЕР-ТЕКСТА"}],
            operation="l1", correlation_id=RID, chat_id=CHAT_ID,
            module=MODULE, step=STEP)
        blob = json.dumps(emitted, ensure_ascii=False, default=str)
        assert "УНИКАЛЬНЫЙ-МАРКЕР-ТЕКСТА" not in blob
        assert "секретное содержимое" not in blob
        names = {name for name, _ in emitted}
        assert "SUMMARY_L1_ACTIVITY" in names


# ── T-4615: rename total_budget_exceeded ────────────────────────────────────


class TestRename:
    @pytest.mark.asyncio
    async def test_supervised_fuse_reason_renamed(self, monkeypatch, caplog):
        """Supervised Summary-канал: fuse-ветка → execution_deadline_exceeded;
        старый код total_budget_exceeded не появляется."""
        llm = _client()

        async def slow_post(self, url, *, json=None, timeout=None, **kw):
            await asyncio.sleep(0.3)
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx.AsyncClient, "post", slow_post)
        with caplog.at_level(logging.ERROR, logger="services.llm_client"):
            with pytest.raises(LLMError):
                await llm._post("/chat/completions", {"model": "m"},
                                budget=0.1, max_retries=0,
                                budget_reason_label="summary_supervised")
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "execution_deadline_exceeded" in joined
        assert "total_budget_exceeded" not in joined

    @pytest.mark.asyncio
    async def test_exhausted_attempts_reason_renamed(self, monkeypatch):
        """Исчерпание попыток (primary fail + fallback недоступен) →
        финальное событие Supervisor'а с retry_time_budget_exhausted
        (§30/ADR-1028-8 D5.6: «budget» не выглядит как денежный balance)."""
        emitted = []

        def fake_emit(event_name, **kwargs):
            emitted.append((event_name, kwargs))

        from services import pipeline_events
        monkeypatch.setattr(pipeline_events, "_emit", fake_emit)

        async def post_route(self, url, *, json=None, timeout=None, **kw):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx.AsyncClient, "post", post_route)
        llm = _client()
        llm._fallback_active = False
        with pytest.raises(LLMError):
            await sup.execute_supervised(
                llm, messages=[{"role": "user", "content": "тест"}],
                operation="l1", correlation_id=RID, chat_id=None,
                module=MODULE, step=STEP)
        reasons = [kw.get("reason_code") for _, kw in emitted
                   if kw.get("reason_code")]
        assert "retry_time_budget_exhausted" in reasons
        assert "total_budget_exceeded" not in reasons
        assert "budget_exhausted" not in reasons

    def test_map_reason_read_side_alias(self):
        """Совместимость старых логов — READ-SIDE alias only."""
        from services.pipeline_events import map_reason
        assert map_reason("total_budget_exceeded") == \
            "execution_deadline_exceeded"
        assert map_reason("budget_exhausted") == \
            "retry_time_budget_exhausted"
        from services.mca_events import REASON_CODES
        assert "execution_deadline_exceeded" in REASON_CODES
        assert "retry_time_budget_exhausted" in REASON_CODES

    def test_analytics_human_descriptions(self):
        from services.pipeline_analytics import REASONS_RU
        assert "предохранительным" in REASONS_RU["execution_deadline_exceeded"]
        assert "попытки исчерпаны" in REASONS_RU["retry_time_budget_exhausted"]
        # Старый misleading код не является reason-кодом новых эмиссий.
        assert "total_budget_exceeded" not in REASONS_RU

    @pytest.mark.asyncio
    async def test_new_events_carry_new_reasons_only(self, monkeypatch):
        """В новых событиях Supervisor'а старый код не появляется."""
        emitted = []

        def fake_emit(event_name, **kwargs):
            emitted.append((event_name, kwargs))

        from services import pipeline_events
        monkeypatch.setattr(pipeline_events, "_emit", fake_emit)

        async def post_route(self, url, *, json=None, timeout=None, **kw):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx.AsyncClient, "post", post_route)
        llm = _client()
        with pytest.raises(LLMError):
            await sup.execute_supervised(
                llm, messages=[{"role": "user", "content": "тест"}],
                operation="l1", correlation_id=RID, chat_id=None,
                module=MODULE, step=STEP)
        blob = json.dumps(emitted, ensure_ascii=False, default=str)
        assert "total_budget_exceeded" not in blob
        # Честные причины присутствуют (provider_unavailable primary +
        # exhaustion финал).
        reasons = [kw.get("reason_code") for _, kw in emitted
                   if kw.get("reason_code")]
        assert "retry_time_budget_exhausted" in reasons
        assert "provider_unavailable" in reasons


class TestTelemetryGuardRails:
    @pytest.mark.asyncio
    async def test_failure_does_not_train_estimator(self):
        """timeout/failure — reliability signals, НЕ обучают дедлайн."""
        for d in (50.0, 60.0, 70.0):
            sup.record_outcome("p", "m", "l1", token_bucket="tok_s", ok=True,
                               duration_s=d)
        before, _ = sup.resolve_attempt_deadline(
            "p", "m", "l1", token_bucket="tok_s")
        for _ in range(5):
            sup.record_outcome("p", "m", "l1", token_bucket="tok_s",
                               ok=False, duration_s=None, timeout=True)
        after, _ = sup.resolve_attempt_deadline(
            "p", "m", "l1", token_bucket="tok_s")
        assert before == after

    def test_recent_states_r17_safe(self):
        st = sup.SupervisedCallState(
            request_id=f"{RID}:l1:abcd", provider="p", model="m",
            operation="l1", mode=sup.MODE_SYNC, started_at=0.0)
        sup._RECENT_STATES.append(st)
        states = sup.recent_states()
        assert states[-1]["operation"] == "l1"
        assert "messages" not in states[-1]
