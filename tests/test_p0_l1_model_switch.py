# -*- coding: utf-8 -*-
"""P0 L1 (2026-11-17): смена модели не должна ломать планировщик.

Требования (plans/features/llm-vision-scheduler-p0/requirements-map.json,
owner input §1.1–1.5): LVS-L1-02/03/04/05/12/13/14/15/16/17/19/20/23/24/26/
27/28/29/34/35/37.

Доказываемые контракты:
  * capability-слой описывает модель (окно / max_output / reasoning / tools /
    JSON / поле output-лимита) с честным источником и уверенностью; 1M —
    планировочная ОЦЕНКА, а не `model_window` и не подтверждённая ёмкость;
    проверенный физический предел сильнее оценки; семейные префиксы ёмкость
    не определяют (никаких списков имён моделей);
  * один общий нормализатор ответа для `generate`/`generate_chat`/
    `dedicated_generate`: текст/null/пустая строка/content-parts/reasoning-only/
    finish_reason=length/tool_calls/нет choices/ошибка внутри HTTP 200 —
    каждый случай имеет определённый класс; reasoning НЕ публикуется как ответ
    и НЕ попадает в prompt обход контракта;
  * L1 наследует действующий транспорт и общий бюджет вывода: код-дефолты
    15 s / 512 tokens удалены как универсальный аварийный fallback из всех
    ветвей; явный owner-override имеет приоритет и диагностируется;
  * один immutable `L1RouteSnapshot` на ход; смена модели без рестарта даёт
    новый снимок и не оставляет старых capability/cache;
  * ключ dedicated-слота НИКОГДА не уходит на чужой endpoint;
  * матрица repair/retry: `finish_reason=length`/reasoning-only → повтор с
    корректным бюджетом (не слепой тот же payload), provider-fallback только
    на разрешённой ноге, число платных вызовов ограничено;
  * телеметрия различает success / compatibility_repaired / retry_success /
    provider_fallback / deterministic_fallback / failed и не содержит
    prompt/ответа/reasoning/секретов.

TEST-LIFECYCLE: CONTRACT owner=P0-L1-MODEL-SWITCH (LVS-L1)
"""
from __future__ import annotations

import asyncio
import inspect
import json

import pytest

import services.llm_client as lc
import services.model_capacity as mc
from config.settings import Settings
from services import direct_l1 as _l1
from services.llm_client import (
    LLMBadResponseError,
    LLMClient,
    LLMRateLimitError,
    LLMTimeoutError,
    classify_chat_response,
    classify_llm_failure,
    incompatible_parameter,
)
from services.model_capacity import (
    OUTPUT_FIELD_MAX_COMPLETION_TOKENS,
    OUTPUT_FIELD_MAX_TOKENS,
    catalog_capability_fields,
    model_capability,
    record_proven_limit,
    resolve_model_capability,
)

pytestmark = [pytest.mark.system2, pytest.mark.asap3, pytest.mark.asap31]


# ── общие фикстуры ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_catalog_network(monkeypatch):
    """Каталог провайдера недоступен по умолчанию (без сети в тестах).

    Тесты, проверяющие каталог, подменяют `_http_get_json` сами."""
    async def _none(url, *, headers=None):
        return None
    monkeypatch.setattr(mc, "_http_get_json", _none)
    yield


@pytest.fixture(autouse=True)
def _clean_capacity_state():
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    mc.clear_proven_limits()
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    mc.clear_proven_limits()


@pytest.fixture(autouse=True)
def _reset_hot(monkeypatch):
    """Пустой hot-конфиг: никаких сохранённых L1-настроек по умолчанию."""
    from services import hot_config as hot
    previous = hot.get_config_cache()
    hot.set_config_cache(None)
    try:
        yield
    finally:
        hot.set_config_cache(previous)


class _CatalogCache:
    """Мини-ConfigCache для hot-значений (sync get)."""

    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    async def set(self, key, value, category=None):
        self.data[key] = value


def _set_hot(monkeypatch, data):
    from services import hot_config as hot
    hot.set_config_cache(_CatalogCache(data))


class _Resp:
    """httpx-подобный ответ с готовым JSON."""

    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data


class _ScriptLLM:
    """LLM-двойник: скрипт для `l1_planner`, текст для остальных шагов.

    Реализует только публичный контракт (`generate`) + атрибуты действующей
    transport-политики (`_timeout`/`_budget`), как у настоящего клиента."""

    def __init__(self, script, *, timeout=180.0, budget=360.0):
        self.script = list(script)
        self.calls = []
        self._timeout = float(timeout)
        self._budget = float(budget)
        self._base_url = "https://primary.example/v1"
        self._chat_model = "main-model"
        self._fallback_active = False

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kwargs):
        self.calls.append({"step": step, "messages": messages,
                           "kwargs": kwargs, "temperature": temperature,
                           "correlation_id": correlation_id})
        if step == "l1_planner":
            item = self.script.pop(0) if self.script else "{}"
            if isinstance(item, Exception):
                raise item
            if isinstance(item, tuple):        # (delay, text)
                await asyncio.sleep(item[0])
                return item[1]
            return item
        return "готовый ответ"

    def steps(self):
        return [c["step"] for c in self.calls]

    def calls_of(self, step):
        return [c for c in self.calls if c["step"] == step]


def _bad_response(kind="truncated_reasoning", finish="length"):
    exc = LLMBadResponseError(
        f"chat/completions: no final text | kind={kind} | "
        f"finish_reason={finish}")
    exc.response_kind = kind
    exc.llm_finish_reason = finish
    exc.reasoning_chars = 120
    return exc


def _plan_json(**over):
    from tests.test_asap7_direct_l1 import _plan_json as plan
    return plan(**over)


def _drive(monkeypatch, text, *, llm):
    from tests.test_asap7_direct_l1 import _drive as drive
    return drive(monkeypatch, text, llm=llm)


def _diag():
    from tests.test_direct_chat import CHAT_ID
    return _l1.get_l1_diagnostics(CHAT_ID) or {}


# ═══ A. capability-слой (model_capacity) ════════════════════════════════════


class TestCapabilityLayer:

    def test_catalog_capability_fields_tristate(self):
        """LVS-L1-03/05: capability из каталога — только по явному сигналу;
        отсутствие сигнала = «не подтверждено», а не «нет»."""
        fields = catalog_capability_fields({
            "id": "vendor/model-x", "context_length": 131072,
            "max_output_tokens": 8192,
            "capabilities": ["reasoning", "tools"]})
        assert fields["supports_reasoning"] is True
        assert fields["supports_tool_calling"] is True
        assert fields["supports_json_mode"] is None      # не подтверждено
        assert fields["output_token_field"] is None       # дефолт max_tokens
        assert fields["output_field_source"] == "default"

        flags = catalog_capability_fields({
            "capabilities": {"json_mode": True, "reasoning": False}})
        assert flags["supports_json_mode"] is True
        assert flags["supports_reasoning"] is False
        assert flags["supports_tool_calling"] is None

        explicit = catalog_capability_fields({
            "output_field": OUTPUT_FIELD_MAX_COMPLETION_TOKENS})
        assert explicit["output_token_field"] == \
            OUTPUT_FIELD_MAX_COMPLETION_TOKENS
        assert explicit["output_field_source"] == "provider_catalog"
        assert catalog_capability_fields({})["supports_reasoning"] is None

    @pytest.mark.asyncio
    async def test_catalog_metadata_reaches_capability(self, monkeypatch):
        """LVS-L1-02/05: окно/вывод/reasoning берутся из каталога провайдера
        с source=provider_catalog (не из списка известных имён)."""
        async def catalog(url, *, headers=None):
            return {"data": [{
                "id": "z-ai/glm-5.3-uncensored",
                "context_length": 131072, "max_output_tokens": 8192,
                "capabilities": ["reasoning", "tools", "json"],
            }]}
        monkeypatch.setattr(mc, "_http_get_json", catalog)
        cap = await resolve_model_capability(
            "https://nano-gpt.com/api/v1", "z-ai/glm-5.3-uncensored")
        assert cap.source == mc.SOURCE_PROVIDER_CATALOG
        assert cap.context_window == 131072
        assert cap.max_output == 8192
        assert cap.supports_reasoning is True
        assert cap.window_verified is True and cap.estimated is False
        assert cap.provider == mc.PROVIDER_NANOGPT
        assert cap.endpoint == "nano-gpt.com"
        # R17: provenance без ключей/промптов.
        events = cap.as_event_fields()
        assert "key" not in json.dumps(events).lower()

    @pytest.mark.asyncio
    async def test_estimated_1m_is_not_verified_window(self):
        """LVS-L1-16/33: unknown ID без metadata → 1M остаётся ОЦЕНКОЙ
        (source=estimated_unknown, window_verified=False)."""
        cap = await resolve_model_capability(
            "https://example.invalid/v1", "unknown-model-xyz")
        assert cap.context_window == 1_000_000
        assert cap.source == mc.SOURCE_ESTIMATED_UNKNOWN
        assert cap.confidence == mc.CONFIDENCE_ESTIMATED
        assert cap.window_verified is False
        assert cap.estimated is True
        assert cap.max_output is None       # 1M контекста ≠ 1M вывода

    @pytest.mark.asyncio
    async def test_proven_limit_beats_estimate(self, monkeypatch):
        """LVS-L1-33: проверенный провайдерский предел меньше оценки 1M —
        он и становится окном (estimate не перебивает факт)."""
        record_proven_limit("https://example.invalid/v1", "unknown-model-xyz",
                            65536, reason="context_length_exceeded")
        cap = await resolve_model_capability(
            "https://example.invalid/v1", "unknown-model-xyz")
        assert cap.context_window == 65536
        assert cap.source == mc.SOURCE_PROVEN_LIMIT
        assert cap.window_verified is True
        assert cap.proven_limit == 65536

    @pytest.mark.asyncio
    async def test_model_switch_refreshes_capability_without_restart(
            self, monkeypatch):
        """LVS-L1-32: GLM → другая → GLM: каждый резолв видит СВОЮ модель,
        старые capability/cache не применяются (без рестарта)."""
        items = {
            "z-ai/glm-5.3-uncensored": (131072, 8192, ["reasoning"]),
            "vendor/other-model": (32768, 2048, []),
        }

        async def catalog(url, *, headers=None):
            return {"data": [
                {"id": model, "context_length": ctx,
                 "max_output_tokens": out, "capabilities": caps}
                for model, (ctx, out, caps) in items.items()]}

        monkeypatch.setattr(mc, "_http_get_json", catalog)
        first = await resolve_model_capability(
            "https://nano-gpt.com/api/v1", "z-ai/glm-5.3-uncensored")
        other = await resolve_model_capability(
            "https://nano-gpt.com/api/v1", "vendor/other-model")
        again = await resolve_model_capability(
            "https://nano-gpt.com/api/v1", "z-ai/glm-5.3-uncensored")
        assert (first.context_window, first.max_output) == (131072, 8192)
        assert (other.context_window, other.max_output) == (32768, 2048)
        assert other.supports_reasoning is None
        assert (again.context_window, again.max_output) == (131072, 8192)
        assert first.supports_reasoning is True

    @pytest.mark.asyncio
    async def test_unknown_variant_does_not_inherit_family_window(self):
        """LVS-L1-05: ёмкость — только точный ID; `glm-5.3-*` не получает
        `glm-4` по общему префиксу (никаких списков имён)."""
        cap = await resolve_model_capability(
            "https://example.invalid/v1", "glm-5.3-uncensored")
        assert cap.window_verified is False
        assert cap.source == mc.SOURCE_ESTIMATED_UNKNOWN


# ═══ B. единый нормализатор ответа (llm_client) ═════════════════════════════


class TestResponseNormalizer:

    def test_content_shapes(self):
        """LVS-L1-19: строка/null/пустая/content-parts — определённый класс."""
        text = classify_chat_response({"choices": [{"message": {
            "content": "готовый план"}}]})
        assert (text.kind, text.content) == (lc.RESPONSE_KIND_TEXT,
                                            "готовый план")
        null = classify_chat_response({"choices": [{"message": {
            "content": None}}]})
        assert null.kind == lc.RESPONSE_KIND_EMPTY and null.content is None
        blank = classify_chat_response({"choices": [{"message": {
            "content": "   "}}]})
        assert blank.kind == lc.RESPONSE_KIND_EMPTY
        parts = classify_chat_response({"choices": [{"message": {
            "content": [{"type": "text", "text": "часть1"},
                        {"type": "image_url", "image_url": {"url": "x"}},
                        {"type": "text", "text": "часть2"}]}}]})
        assert parts.kind == lc.RESPONSE_KIND_TEXT
        assert parts.content == "часть1\nчасть2"
        assert parts.content_parts == 3
        weird = classify_chat_response({"choices": [{"message": {
            "content": 42}}]})
        assert weird.kind == lc.RESPONSE_KIND_INVALID_CONTENT

    def test_reasoning_is_never_the_answer(self):
        """LVS-L1-20: reasoning-only и обрыв на reasoning — НЕ план."""
        only = classify_chat_response({"choices": [{"message": {
            "content": None, "reasoning_content": "думаю..."}}]})
        assert only.kind == lc.RESPONSE_KIND_REASONING_ONLY
        assert only.content is None                       # не ответ
        assert only.reasoning_chars == len("думаю...")
        truncated = classify_chat_response({"choices": [{
            "message": {"content": "", "thinking": "длинный reasoning"},
            "finish_reason": "length"}]})
        assert truncated.kind == lc.RESPONSE_KIND_TRUNCATED_REASONING
        assert truncated.content is None
        assert truncated.truncated is True
        # Reasoning в события — только числом.
        assert "reasoning" not in truncated.as_event_fields()
        assert truncated.as_event_fields()["reasoning_chars"] > 0

    def test_tool_calls_no_choices_and_http200_error(self):
        """LVS-L1-23/24: tool_calls/нет choices/ошибка внутри 200 различаются."""
        tools = classify_chat_response({"choices": [{"message": {
            "content": None, "tool_calls": [
                {"id": "1", "function": {"name": "search",
                                         "arguments": "{}"}}]}}]})
        assert tools.kind == lc.RESPONSE_KIND_TOOL_CALLS
        assert [t.name for t in tools.tool_calls] == ["search"]
        malformed = classify_chat_response({"choices": [{"message": {
            "content": None, "tool_calls": [{"id": "1",
                                             "function": {"name": ""}}]}}]})
        assert malformed.kind == lc.RESPONSE_KIND_EMPTY   # не валидный tool
        none = classify_chat_response({"choices": []})
        assert none.kind == lc.RESPONSE_KIND_NO_CHOICES
        poor = classify_chat_response("not a dict")
        assert poor.kind == lc.RESPONSE_KIND_INVALID_PAYLOAD
        error = classify_chat_response({"error": {
            "code": "insufficient_quota", "message": "no money"}})
        assert error.kind == lc.RESPONSE_KIND_PROVIDER_ERROR
        assert error.error_code == "insufficient_quota"

    def test_failure_taxonomy(self):
        """LVS-L1-23: у каждого класса отказа свой код (не один except)."""
        assert classify_llm_failure(LLMRateLimitError("429")) == "rate_limit"
        assert classify_llm_failure(LLMTimeoutError("t")) == "timeout"
        budget = LLMTimeoutError("t", cause_class="budget")
        assert classify_llm_failure(budget) == "deadline_exceeded"
        assert classify_llm_failure(asyncio.CancelledError()) == "cancelled"
        assert classify_llm_failure(LLMBadResponseError("x")) == "bad_response"
        bad = lc.LLMError("LLM HTTP 400: x")
        bad.status = 400
        bad.body = '{"error": {"message": "Unsupported parameter: temperature"}}'
        assert incompatible_parameter(bad) == "temperature"
        assert classify_llm_failure(bad) == "incompatible_request"
        plain = lc.LLMError("LLM HTTP 400: x")
        plain.status = 400
        plain.body = '{"error": {"message": "invalid messages"}}'
        assert incompatible_parameter(plain) is None
        assert classify_llm_failure(plain) == "bad_request"
        field = lc.LLMError("LLM HTTP 422: x")
        field.status = 422
        field.body = '{"error": {"message": "unknown parameter max_tokens"}}'
        assert incompatible_parameter(field) == "max_tokens"


_TRUE_ASYNC_CLIENT = None


def _client(handler, monkeypatch, **kwargs):
    import httpx
    global _TRUE_ASYNC_CLIENT
    if _TRUE_ASYNC_CLIENT is None:
        _TRUE_ASYNC_CLIENT = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    original = _TRUE_ASYNC_CLIENT

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.llm_client.httpx.AsyncClient", factory)
    params = dict(base_url="https://primary.example/v1", api_key="test-key",
                  chat_model="model-init", embed_model="embed-init",
                  fallback_base_url="", fallback_model="",
                  fallback_api_key="")
    params.update(kwargs)
    client = LLMClient(**params)
    client.backoff_base = 0
    return client


def _json_handler(payload):
    import httpx

    def handler(request):
        return httpx.Response(200, json=payload, request=request)
    return handler


class TestConsumerParsers:

    @pytest.mark.asyncio
    async def test_generate_rejects_reasoning_only_with_reason(
            self, monkeypatch):
        """LVS-L1-20/23: `generate` не отдаёт reasoning как ответ; причина
        отказа доступна вызывающему (kind/finish_reason)."""
        client = _client(_json_handler({
            "choices": [{"message": {"content": None,
                                     "reasoning_content": "черновик"},
                         "finish_reason": "length"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5}}),
            monkeypatch)
        with pytest.raises(LLMBadResponseError) as info:
            await client.generate([{"role": "user", "content": "hi"}])
        assert info.value.response_kind == lc.RESPONSE_KIND_TRUNCATED_REASONING
        assert info.value.llm_finish_reason == "length"

    @pytest.mark.asyncio
    async def test_generate_chat_parts_text_and_reasoning_separate(
            self, monkeypatch):
        """LVS-L1-19/20: content-parts склеиваются, reasoning остаётся
        отдельным полем и не становится content."""
        client = _client(_json_handler({
            "choices": [{"message": {
                "content": [{"type": "text", "text": "ответ"}],
                "reasoning": "мысль"}}]}), monkeypatch)
        result = await client.generate_chat(
            [{"role": "user", "content": "hi"}])
        assert result.content == "ответ"
        assert result.reasoning == "мысль"
        assert result.response_kind == lc.RESPONSE_KIND_TEXT

        client2 = _client(_json_handler({
            "choices": [{"message": {"content": None,
                                     "thinking": "только мысль"}}]}),
            monkeypatch)
        reasoning = await client2.generate_chat(
            [{"role": "user", "content": "hi"}])
        assert reasoning.content is None            # НЕ опубликован
        assert reasoning.reasoning == "только мысль"
        assert reasoning.response_kind == lc.RESPONSE_KIND_REASONING_ONLY

    @pytest.mark.asyncio
    async def test_r17_secret_not_in_logs(self, monkeypatch, caplog):
        """LVS-L1-29: ни prompt, ни ответ, ни reasoning не пишутся в лог."""
        secret = "sk-SECRET-abcdef123456"
        client = _client(_json_handler({
            "choices": [{"message": {"content": "ответ с " + secret,
                                     "reasoning_content": "мысль " + secret},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}}),
            monkeypatch)
        caplog.set_level("DEBUG")
        text = await client.generate(
            [{"role": "user", "content": "prompt with " + secret}],
            module="direct_chat", step="l1_planner")
        assert secret in text
        combined = "\n".join(str(r.getMessage()) for r in caplog.records)
        assert secret not in combined
        assert "prompt with" not in combined


# ═══ C. L1: слот / транспорт / бюджет / ключи ═══════════════════════════════


class TestL1RouteContract:

    def test_no_universal_15s_and_512(self, monkeypatch):
        """LVS-L1-12: без явной настройки L1 НЕ имеет собственных 15 s / 512."""
        assert _l1.l1_timeout_seconds() is None
        assert _l1.l1_max_output_tokens() is None
        _set_hot(monkeypatch, {
            "limits.direct_l1_timeout_seconds": 20,
            "limits.direct_l1_max_output_tokens": 700})
        assert _l1.l1_timeout_seconds() == 20
        assert _l1.l1_max_output_tokens() == 700
        # Существующий owner-выбор не перезаписывается чтением.
        _set_hot(monkeypatch, {"limits.direct_l1_timeout_seconds": 15,
                               "limits.direct_l1_max_output_tokens": 512})
        assert _l1.l1_timeout_seconds() == 15
        assert _l1.l1_max_output_tokens() == 512

    def test_env_override_is_explicit_owner_choice(self, monkeypatch):
        """LVS-L1-13: env-значение — явный override (не автоматический
        дефолт): читается обратно без изменений."""
        monkeypatch.setenv("DIRECT_L1_TIMEOUT_SECONDS", "25")
        monkeypatch.setattr(Settings, "DIRECT_L1_TIMEOUT_SECONDS", 25)
        assert _l1.l1_timeout_seconds() == 25
        monkeypatch.delenv("DIRECT_L1_TIMEOUT_SECONDS", raising=False)
        monkeypatch.setattr(Settings, "DIRECT_L1_TIMEOUT_SECONDS", 15)
        assert _l1.l1_timeout_seconds() is None

    @pytest.mark.asyncio
    async def test_route_inherits_transport_and_plan_budget(self, monkeypatch):
        """LVS-L1-12/14/15/17: маршрут наследует транспорт (180/360) и
        бюджет вывода из контракта плана — не 512 и не 1M."""
        llm = _ScriptLLM([])
        slot = _l1.L1ModelSlot(base_url="https://nano-gpt.com/api/v1",
                               model="z-ai/glm-5.3-uncensored",
                               api_key="k", dedicated=False)
        route = await _l1.resolve_l1_route(slot, llm)
        assert route.timeout_seconds == 180.0
        assert route.deadline_seconds == 360.0
        assert route.timeout_source == _l1.TIMEOUT_SOURCE_TRANSPORT
        assert route.output_field == OUTPUT_FIELD_MAX_TOKENS
        assert route.output_source == _l1.OUTPUT_SOURCE_CAPABILITY
        assert route.max_output_tokens is not None
        assert 2048 <= route.max_output_tokens <= _l1.L1_OUTPUT_CEILING_TOKENS
        assert route.output_reserve == _l1.L1_REASONING_RESERVE_TOKENS
        assert route.key_slot == "main" and route.usable is True

    @pytest.mark.asyncio
    async def test_owner_override_wins_and_is_reported(self, monkeypatch):
        """LVS-L1-13: явный owner-override приоритетен и виден в снимке."""
        _set_hot(monkeypatch, {
            "limits.direct_l1_timeout_seconds": 15,
            "limits.direct_l1_max_output_tokens": 512})
        llm = _ScriptLLM([])
        slot = _l1.L1ModelSlot(base_url="https://x.example/v1",
                               model="m", api_key="k")
        route = await _l1.resolve_l1_route(
            slot, llm, owner_timeout=_l1.l1_timeout_seconds(),
            owner_output=_l1.l1_max_output_tokens())
        assert route.timeout_seconds == 15.0
        assert route.timeout_source == _l1.TIMEOUT_SOURCE_OWNER
        assert route.max_output_tokens == 512
        assert route.output_source == _l1.OUTPUT_SOURCE_OWNER

    def test_output_budget_reasoning_and_ceiling(self):
        """LVS-L1-14/35: reasoning-резерв учитывается; известный max_output
        модели — потолок; повтор не слепой и не гигантский."""
        class _NoReasoning:
            supports_reasoning = False
            max_output = None

        class _Reasoning:
            supports_reasoning = True
            max_output = 4096

        plain, reserve_plain, source_plain = _l1.l1_plan_output_budget(
            _NoReasoning())
        reasoning, reserve_reasoning, _ = _l1.l1_plan_output_budget(
            _Reasoning())
        assert reserve_plain == 0 and source_plain == _l1.OUTPUT_SOURCE_CONTRACT
        assert reserve_reasoning == _l1.L1_REASONING_RESERVE_TOKENS
        assert reasoning > plain
        assert reasoning <= 4096                    # capability ceiling
        retry, _, _ = _l1.l1_plan_output_budget(_Reasoning(), attempt=2)
        assert retry <= 4096 and retry >= reasoning
        assert _l1.l1_plan_output_budget(None)[0] > 512

    @pytest.mark.asyncio
    async def test_snapshot_is_immutable_across_model_switch(
            self, monkeypatch):
        """LVS-L1-32: начатый ход держит свой снимок; следующий — новый."""
        llm = _ScriptLLM([])
        slot_a = _l1.L1ModelSlot(base_url="https://a.example/v1",
                                 model="model-a", api_key="k")
        first = await _l1.resolve_l1_route(slot_a, llm)
        slot_b = _l1.L1ModelSlot(base_url="https://b.example/v1",
                                 model="model-b", api_key="k")
        second = await _l1.resolve_l1_route(slot_b, llm)
        assert first.model == "model-a" and second.model == "model-b"
        assert first.endpoint == "a.example" and second.endpoint == "b.example"
        assert first.context_source != ""      # старый снимок не переписан
        with pytest.raises(Exception):
            first.model = "mutated"             # frozen: снимок неизменяем

    def test_dedicated_key_never_crosses_endpoint(self):
        """LVS-L1-13 и security: main-ключ не уходит на чужой endpoint;
        тот же endpoint — ключ легитимен."""
        hot = {
            "models.llm_base_url": "https://main.example/v1",
            "models.llm_model_name": "main-model",
            "keys.llm_api_key": "sk-main",
            "models.direct_l1_base_url": "https://other.example/v1",
            "models.direct_l1_model_name": "l1-model",
            "keys.direct_l1_api_key": "",
        }
        slot = _l1.resolve_l1_model(hot_get=lambda k, d=None: hot.get(k, d))
        assert slot.dedicated is True
        assert slot.api_key == ""                      # НЕ main-ключ
        route = asyncio.run(_l1.resolve_l1_route(slot))
        assert route.key_slot == "none" and route.usable is False

        hot_same = dict(hot, **{"models.direct_l1_base_url":
                                "https://main.example/v1"})
        same = _l1.resolve_l1_model(
            hot_get=lambda k, d=None: hot_same.get(k, d))
        assert same.api_key == "sk-main"
        assert asyncio.run(_l1.resolve_l1_route(same)).usable is True

    @pytest.mark.asyncio
    async def test_context_budget_estimate_is_labelled(self, monkeypatch):
        """LVS-L1-16/33: 1M-оценка не выдаётся за подтверждённое
        `model_window` (источник/уверенность видны)."""
        budget, meta = await _l1.resolve_l1_context_budget(
            base_url="https://example.invalid/v1",
            model="unknown-model-xyz")
        assert meta["capacity_source"] == mc.SOURCE_ESTIMATED_UNKNOWN
        assert meta["window_estimated"] is True
        assert meta["source"] == "model_window_estimate"
        assert budget <= meta["context_window"]

    @pytest.mark.asyncio
    async def test_dedicated_generate_uses_route_output_field(self):
        """LVS-L1-17/24/34: dedicated отправляет ФАКТИЧЕСКОЕ поле лимита и
        классифицирует ответ тем же нормализатором."""
        payloads = []

        class _LLM:
            async def _post(self, path, payload, *, api_key=None,
                            base_url=None, **kw):
                payloads.append(dict(payload))
                if len(payloads) == 1:
                    return _Resp({"choices": [{
                        "message": {"content": None,
                                    "reasoning_content": "черновик"},
                        "finish_reason": "length"}],
                        "usage": {"prompt_tokens": 1,
                                  "completion_tokens": 1}})
                return _Resp({"choices": [{"message": {
                    "content": [{"type": "text", "text": "{\"action\":1}"}]},
                    "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 2}})

        slot = _l1.L1ModelSlot(base_url="https://l1.example/v1",
                               model="l1-model", api_key="k", dedicated=True)
        with pytest.raises(LLMBadResponseError) as info:
            await _l1.dedicated_generate(
                _LLM(), [{"role": "user", "content": "hi"}], slot,
                max_output_tokens=3000,
                output_field=OUTPUT_FIELD_MAX_COMPLETION_TOKENS)
        assert info.value.response_kind == lc.RESPONSE_KIND_TRUNCATED_REASONING
        assert payloads[0][OUTPUT_FIELD_MAX_COMPLETION_TOKENS] == 3000
        assert OUTPUT_FIELD_MAX_TOKENS not in payloads[0]

        content, usage = await _l1.dedicated_generate(
            _LLM(), [{"role": "user", "content": "hi"}], slot,
            max_output_tokens=3000)
        assert content == '{"action":1}'
        assert payloads[-1][OUTPUT_FIELD_MAX_TOKENS] == 3000


# ═══ D. матрица repair/retry и taxonomy исхода ══════════════════════════════


class TestRetryMatrix:

    def test_length_and_reasoning_get_correction_not_blind_repeat(self):
        """LVS-L1-26/34: length/reasoning-only → увеличенный бюджет (НЕ тот
        же payload), второй такой же коррекции нет."""
        truncated = _bad_response("truncated_reasoning", "length")
        correction = _l1.next_l1_correction(
            truncated, failure="bad_response",
            response_kind="truncated_reasoning", finish_reason="length")
        assert correction["kind"] == _l1.CORRECTION_BUDGET
        assert _l1.next_l1_correction(
            truncated, failure="bad_response",
            response_kind="truncated_reasoning", finish_reason="length",
            corrected_budget=True)["kind"] == _l1.CORRECTION_JSON_REPAIR
        assert _l1.next_l1_correction(
            truncated, failure="bad_response",
            response_kind="truncated_reasoning", finish_reason="length",
            corrected_budget=True, repaired=True) is None

        empty = _bad_response("empty", "stop")
        assert _l1.next_l1_correction(
            empty, failure="bad_response", response_kind="empty",
            finish_reason="stop")["kind"] == _l1.CORRECTION_JSON_REPAIR

    def test_transport_and_provider_classes_are_not_retried_here(self):
        """LVS-L1-26: 429/5xx/timeout/auth — владелец другой слой; L1 не
        дублирует попытки (нет двойной оплаты)."""
        for failure in ("rate_limit", "server_error", "timeout",
                        "deadline_exceeded", "transport", "auth", "no_key",
                        "cancelled", "context_overflow"):
            assert _l1.next_l1_correction(
                LLMRateLimitError("429"), failure=failure) is None

    def test_incompatible_param_corrections(self):
        """LVS-L1-24: несовместимое поле/температура → точечный repair."""
        temp = lc.LLMError("LLM HTTP 400: x")
        temp.status = 400
        temp.body = '{"error": {"message": "unsupported parameter temperature"}}'
        assert _l1.next_l1_correction(
            temp, failure="incompatible_request",
            has_temperature=True)["kind"] == \
            _l1.CORRECTION_DROP_TEMPERATURE
        assert _l1.next_l1_correction(
            temp, failure="incompatible_request", has_temperature=True,
            corrected_fields=True) is None
        field = lc.LLMError("LLM HTTP 422: x")
        field.status = 422
        field.body = '{"error": {"message": "unknown parameter max_tokens"}}'
        correction = _l1.next_l1_correction(
            field, failure="incompatible_request", has_temperature=False)
        assert correction["kind"] == _l1.CORRECTION_OUTPUT_FIELD
        assert correction["field"] == OUTPUT_FIELD_MAX_COMPLETION_TOKENS

    def test_failure_mode_one_category(self):
        """LVS-L1-28: ровно одна категория; deterministic ≠ success."""
        assert _l1.resolve_failure_mode(plan_present=True) == "success"
        assert _l1.resolve_failure_mode(plan_present=False) == \
            "deterministic_fallback"
        assert _l1.resolve_failure_mode(
            plan_present=True, fallback_leg=True) == "provider_fallback"
        assert _l1.resolve_failure_mode(
            plan_present=True, corrected_fields=True) == \
            "compatibility_repaired"
        assert _l1.resolve_failure_mode(
            plan_present=True, corrected_budget=True) == "retry_success"
        assert _l1.resolve_failure_mode(
            plan_present=False, aborted=True) == "failed"
        assert len(set(_l1.FAILURE_MODES)) == len(_l1.FAILURE_MODES)
        assert "success" != "deterministic_fallback"

    def test_repair_prompt_does_not_carry_reasoning(self):
        """LVS-L1-20: reasoning не складывается в prompt обход контракта."""
        messages = [{"role": "system", "content": "sys"},
                    {"role": "user", "content": "вопрос"}]
        reasoning = "СЕКРЕТНЫЙ-РАЗМЫШЛЕНИЕ-ТЕКСТ"
        repaired = _l1.build_repair_messages(
            messages, reasoning, reason=_l1.REPAIR_REASON_REASONING_ONLY)
        blob = " ".join(str(m.get("content")) for m in repaired)
        assert reasoning not in blob
        assert "финального JSON-плана" in blob
        # Прежний контракт invalid_json — байт-в-байт прежняя аннотация.
        legacy = _l1.build_repair_messages(messages, "мусор")
        assert _l1.REPAIR_ANNOTATION in legacy[-1]["content"]
        assert "мусор" in legacy[-1]["content"]


# ═══ E. ход L1: инцидент 09:27, телеметрия, ключи ══════════════════════════


class TestL1Turn:

    @pytest.mark.asyncio
    async def test_length_truncated_empty_content_retried_with_budget(
            self, monkeypatch):
        """ИНЦИДЕНТ (09:27:43Z): finish_reason=length + пустой content при
        out=512 → deterministic fallback. Теперь: повтор с корректным
        бюджетом → валидный план, без подмены модели."""
        llm = _ScriptLLM([_bad_response("truncated_reasoning", "length"),
                          _plan_json(extent="micro")])
        svc, react, bot, msg, user = _drive(monkeypatch, "а этот?", llm=llm)
        await svc.handle(bot, msg, user)

        calls = llm.calls_of("l1_planner")
        assert len(calls) == 2, "ровно один корректный повтор"
        first_budget = calls[0]["kwargs"]["max_output_tokens"]
        second_budget = calls[1]["kwargs"]["max_output_tokens"]
        assert second_budget > first_budget > 512
        # Повтор — не тот же payload: бюджет реально изменён.
        assert calls[0]["messages"] != [] and calls[1]["messages"]
        plan_text = "".join(str(m.get("content"))
                            for m in llm.calls_of("l2_writer")[0]["messages"])
        assert "МИКРО" in plan_text
        diag = _diag()
        assert diag["l1_failure_mode"] == "retry_success"
        assert diag["l1_attempts"] == 2
        assert diag["l1_finish_reason"] == "length"
        assert diag["l1_output_limit"] == second_budget
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_plain_answer_is_success_not_fallback(self, monkeypatch):
        """LVS-L1-28/36: обычный валидный ответ — `success`, ни
        provider-, ни deterministic-fallback."""
        llm = _ScriptLLM([_plan_json(extent="micro")])
        svc, react, bot, msg, user = _drive(monkeypatch, "привет", llm=llm)
        await svc.handle(bot, msg, user)
        assert len(llm.calls_of("l1_planner")) == 1
        diag = _diag()
        assert diag["l1_failure_mode"] == "success"
        assert diag["l1_attempts"] == 1
        assert diag["l1_output_limit"] >= 2048   # не 512

    @pytest.mark.asyncio
    async def test_dedicated_without_key_skips_leg_never_leaks_key(
            self, monkeypatch):
        """LVS-L1-13 + security: у dedicated-слота свой endpoint без ключа →
        попытка НЕ выполняется, main-ключ не уходит; план строит main."""
        from services import hot_config as hot
        hot.set_config_cache(_CatalogCache({
            "models.llm_base_url": "https://main.example/v1",
            "models.llm_model_name": "main-model",
            "keys.llm_api_key": "sk-main",
            "models.direct_l1_base_url": "https://other.example/v1",
            "models.direct_l1_model_name": "l1-model",
            "flags.direct_l1_fallback_enabled": True,
        }))
        llm = _ScriptLLM([_plan_json(extent="micro")])

        async def _post(*a, **kw):       # dedicated-канал не должен звонить
            raise AssertionError("dedicated endpoint used without own key")

        llm._post = _post
        svc, react, bot, msg, user = _drive(monkeypatch, "а этот?", llm=llm)
        await svc.handle(bot, msg, user)
        assert len(llm.calls_of("l1_planner")) == 1
        diag = _diag()
        assert diag["l1_skipped_leg"] == "l1_slot"
        assert diag["l1_failure_mode"] == "provider_fallback"
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deadline_follows_transport_policy_not_15s(
            self, monkeypatch):
        """LVS-L1-15: верхняя граница хода — действующая transport-политика
        (изменение политики реально меняет поведение; 15s не зашит)."""
        slow = _ScriptLLM([(0.25, _plan_json(extent="micro"))], budget=0.05)
        svc, react, bot, msg, user = _drive(monkeypatch, "а этот?", llm=slow)
        await svc.handle(bot, msg, user)
        assert _diag()["l1_failure_mode"] == "deterministic_fallback"
        svc._send_direct_answer.assert_awaited_once()

        normal = _ScriptLLM([(0.25, _plan_json(extent="micro"))], budget=30.0)
        svc2, _, bot2, msg2, user2 = _drive(monkeypatch, "а этот?",
                                            llm=normal)
        await svc2.handle(bot2, msg2, user2)
        assert _diag()["l1_failure_mode"] == "success"

    @pytest.mark.asyncio
    async def test_attempt_ceiling_per_leg(self, monkeypatch):
        """LVS-L1-26: число платных вызовов ограничено (нет удвоения)."""
        assert _l1.L1_MAX_CALLS_PER_LEG == 3
        llm = _ScriptLLM([_bad_response("empty", "stop")] * 6)
        svc, react, bot, msg, user = _drive(monkeypatch, "а этот?", llm=llm)
        await svc.handle(bot, msg, user)
        calls = len(llm.calls_of("l1_planner"))
        assert calls <= _l1.L1_MAX_CALLS_PER_LEG
        assert _diag()["l1_failure_mode"] == "deterministic_fallback"

    def test_turn_source_has_no_local_15_second_wait(self):
        """LVS-L1-12: в коде хода нет локального `wait_for(15)`.

        Статическая проверка дополняет поведенческий тест выше: 15 s не
        должны вернуться как «безопасный» дефолт."""
        from services import direct_chat_service as dcs
        source = inspect.getsource(dcs.DirectChatService._execute_turn)
        assert "wait_for" in source                      # дедлайн остаётся
        assert "l1_timeout_seconds()" in source          # но только override
        assert "timeout=15" not in source
        assert "float(15" not in source

    def test_plan_meta_carries_outcome_fields(self):
        """LVS-L1-28/29: durable plan_meta получает исход попытки (коды)."""
        from services import usage_events as ue
        out = _l1.next_l1_correction(_bad_response(), failure="bad_response",
                                     response_kind="truncated_reasoning",
                                     finish_reason="length")
        assert out is not None
        safe = ue.sanitize_plan_meta({
            "l1_failure_mode": "retry_success", "l1_finish_reason": "length",
            "l1_output_limit": 8192, "l1_attempts": 2,
            "l1_output_field": "max_tokens",
            "l1_window_estimated": True,
            "l1_output_source": "model_capability",
            "prompt": "SECRET PROMPT", "reasoning": "SECRET REASONING"})
        assert safe is not None
        assert safe["l1_failure_mode"] == "retry_success"
        assert safe["l1_output_limit"] == 8192
        assert safe["l1_attempts"] == 2
        assert safe["l1_window_estimated"] is True
        assert "prompt" not in safe and "reasoning" not in safe


# ═══ F. R17-safe событие L1_PLAN ════════════════════════════════════════════


class TestL1Event:

    def test_event_fields_survive_whitelist(self):
        """LVS-L1-28/29: новые поля исхода доезжают в существующее событие
        (whitelist), текст/секреты — нет."""
        from services import agentic_events as ae
        captured = []
        original = ae.emit_agentic_event
        import services.agentic_events as module

        real = module.emit_agentic_event

        def spy(event, **fields):
            captured.append((event, fields))
            return real(event, **fields)

        module.emit_agentic_event = spy
        try:
            _l1.emit_l1_plan_event(
                run_id="run1", chat_id=1, plan=None, inherited=False,
                fallback="deterministic", latency_ms=12, input_chars=34,
                source="main", failure_mode="deterministic_fallback",
                finish_reason="length", output_limit=8192,
                output_field="max_tokens", timeout_seconds=180.0,
                deadline_seconds=360.0, attempts=2, model="z-ai/glm-5.3",
                correlation_id="run1", window_source="provider_catalog",
                window_estimated=False)
        finally:
            module.emit_agentic_event = real
        assert captured, "событие должно быть эмитировано"
        _event, fields = captured[0]
        assert fields["failure_mode"] == "deterministic_fallback"
        assert fields["finish_reason"] == "length"
        assert fields["output_limit"] == 8192
        assert fields["attempts"] == 2
        assert fields["deadline_seconds"] == 360.0
        blob = json.dumps(fields, ensure_ascii=False, default=str)
        assert "prompt" not in blob.lower()
        assert "reasoning" not in blob.lower()


# ═══ G. production-конфигурация: 1M estimate не ломает бюджет ══════════════


class TestEffectiveConfiguration:

    @pytest.mark.asyncio
    async def test_reasoning_model_gets_budget_above_512(self):
        """LVS-L1-35: сложный план с reasoning получает бюджет, достаточный
        для финального JSON (и не гигантский)."""
        class _Cap:
            supports_reasoning = True
            max_output = None

        budget, reserve, source = _l1.l1_plan_output_budget(_Cap())
        assert budget >= 2048 + reserve
        assert budget <= _l1.L1_OUTPUT_CEILING_TOKENS
        assert source == _l1.OUTPUT_SOURCE_CAPABILITY

    @pytest.mark.asyncio
    async def test_route_budget_matches_capability_max_output(self,
                                                              monkeypatch):
        """LVS-L1-17: единственный effective совпадает с отправленным
        payload (computed == snapshot == sent)."""
        async def catalog(url, *, headers=None):
            return {"data": [{"id": "z-ai/glm-5.3-uncensored",
                              "context_length": 131072,
                              "max_output_tokens": 3000,
                              "capabilities": ["reasoning"]}]}
        monkeypatch.setattr(mc, "_http_get_json", catalog)
        llm = _ScriptLLM([])
        slot = _l1.L1ModelSlot(base_url="https://nano-gpt.com/api/v1",
                               model="z-ai/glm-5.3-uncensored", api_key="k")
        route = await _l1.resolve_l1_route(slot, llm)
        assert route.max_output_tokens <= 3000
        assert route.output_source.endswith("+max_output")
        assert route.supports_reasoning is True
