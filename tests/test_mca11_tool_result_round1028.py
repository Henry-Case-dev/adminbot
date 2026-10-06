"""MCA-11 `mca-11-tools-costs` — focused блок A (T-4945…T-4949).

Покрытие: ToolResult-контракт (7 статусов/категории канона 12/A20), лимиты
D2 (env-only числа поверх существующих cap'ов), idempotency key/`delivery_unknown`
(A21, без слепого повтора), интеграция потребителей (SafeFetcher stage/retryable,
медиа-статусы, совместимость mca-15) и OFF-паритет K1.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services import image_generation as ig
from services import safe_fetch, tool_result
from services.llm_client import LLMChatResult, LLMToolCall
from services.tool_loop import chat_with_tools
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from services.tool_schemas import TOOL_CALLING_TOOLS
from services.web_content_extractor import WebContentExtractionFailedException

MESSAGES = [{"role": "user", "content": "вопрос"}]
TOOLS = [{"type": "function"}]

LEGACY_KEYS = {"round", "tool", "args_fingerprint", "status", "data",
               "error_code", "error_type", "truncated", "metered", "duplicate",
               "attempt", "out_chars"}


class FakeLLM:
    def __init__(self, answers):
        self._answers = list(answers)
        self.all_messages = []

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.all_messages.append([dict(m) for m in messages])
        if not self._answers:
            raise AssertionError("не хватило запланированных ответов")
        return self._answers.pop(0)

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        return "plain"


def _tc(call_id, name, args=None, raw=None):
    arguments = raw if raw is not None else json.dumps(args or {})
    return LLMChatResult(content=None,
                         tool_calls=[LLMToolCall(id=call_id, name=name,
                                                 arguments=arguments)],
                         finish_reason="tool_calls")


def _tc2(prefix, name_args):
    calls = [LLMToolCall(id=f"{prefix}_{i}", name=n,
                         arguments=json.dumps(a))
             for i, (n, a) in enumerate(name_args)]
    return LLMChatResult(content=None, tool_calls=calls,
                         finish_reason="tool_calls")


def _text(text):
    return LLMChatResult(content=text, tool_calls=None, finish_reason="stop")


class FakeRouter:
    def __init__(self, outputs=None, *, fn=None):
        self._outputs = dict(outputs or {})
        self._fn = fn
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, arguments))
        if self._fn is not None:
            return await self._fn(name, arguments, ctx)
        return self._outputs.get(name, f"данные:{name}")


async def _run(llm, router, ctx=None):
    return await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                 ctx=ctx or ToolContext(-100, "q"))


# ── T-4945: контракт ─────────────────────────────────────────────────────────


class TestContract:
    def test_statuses_closed_set_seven(self):
        assert tool_result.STATUSES == {
            "ok", "empty", "error", "timeout", "cancelled", "denied",
            "delivery_unknown"}

    def test_categories_cover_canon_twelve(self):
        # MCA-19 (ADR-1028-19 D22, санкция spec §8.6/§8.9): канон тулов
        # 12→13 (+recognize_image). Карту категорий mca-11 (канон 12, D1)
        # спека НЕ расширяет: учёт расхода recognize_image — отдельная
        # категория `vision.media` в llm_usage_events + METERED_TOOLS
        # (tool_loop.py). В mca-11 recognize_image — неизвестный тул →
        # консервативный external_read (никогда admin, D1).
        # MCA-20 (ADR-1028-20 §7.5, round 10.44): канон 13→14
        # (+fact_check). Карту НЕ расширяем — тот же прецедент:
        # fact_check — неизвестный тул → консервативный external_read;
        # расход — METERED_TOOLS + существующие категории llm_usage_events.
        names = {t["function"]["name"] for t in TOOL_CALLING_TOOLS}
        assert len(names) == 14
        assert set(tool_result.TOOL_CATEGORIES) == names - {
            "recognize_image", "fact_check"}
        assert tool_result.category_for("recognize_image") == "external_read"
        assert tool_result.category_for("fact_check") == "external_read"
        counts = {}
        for name in names:
            counts[tool_result.category_for(name)] = \
                counts.get(tool_result.category_for(name), 0) + 1
        assert counts == {"memory_read": 4, "external_read": 7,
                          "paid_media": 2, "admin": 1}

    def test_unknown_tool_conservative_never_admin(self):
        assert tool_result.category_for("nope") == "external_read"
        assert tool_result.category_for("") == "external_read"
        assert tool_result.category_for("get_bot_health") == "admin"

    def test_idempotency_by_category(self):
        assert tool_result.is_idempotent("query_chat_memory") is True
        assert tool_result.is_idempotent("fetch_article") is True
        assert tool_result.is_idempotent("get_bot_health") is True
        assert tool_result.is_idempotent("generate_image") is False
        assert tool_result.is_idempotent("compile_lore_story") is False
        assert tool_result.op_kind_for("generate_image") == "media_submit"
        assert tool_result.op_kind_for("fetch_article") == "tool_call"

    def test_evidence_refs_from_payload(self):
        payload = json.dumps({"status": "ok", "source_id": "abc123",
                              "metric_id": "m-1"})
        info = tool_result.classify_output("fetch_article", payload)
        assert info["evidence_refs"] == ["abc123", "m-1"]

    def test_usage_unknown_not_zero(self):
        info = tool_result.classify_output(
            "generate_image", "{}",
            signal={"usage": {"input_tokens": 0, "output_tokens": 0,
                              "cost_usd": None, "price_known": False,
                              "source": "image"}})
        assert info["usage"]["cost_usd"] is None
        assert info["usage"]["price_known"] is False
        assert info["usage"]["currency"] == "USD"


class TestA20ErrorNeverOk:
    def test_error_text_is_error(self):
        info = tool_result.classify_output(
            "execute_web_search", "ОШИБКА execute_web_search: недоступен")
        assert info["status"] == "error"
        assert info["status"] != "ok"
        assert info["error_code"] == "tool_error"

    def test_error_text_timeout_is_timeout(self):
        info = tool_result.classify_output(
            "execute_web_search", "ОШИБКА execute_web_search: timeout")
        assert info["status"] == "timeout"
        assert info["error_code"] == "timeout"
        assert info["retryable"] is True       # идемпотентное чтение

    def test_json_error_status_is_error(self):
        info = tool_result.classify_output(
            "fetch_article", json.dumps({"status": "error",
                                         "error": "extract_failed"}))
        assert info["status"] == "error"
        assert info["error_code"] == "extract_failed"

    @pytest.mark.asyncio
    async def test_tool_loop_envelope_error_never_ok(self):
        router = FakeRouter({"execute_web_search":
                             "ОШИБКА execute_web_search: поиск недоступен "
                             "(timeout)"})
        out = await _run(FakeLLM([_tc("c1", "execute_web_search",
                                      {"query": "x"}), _text("финал")]),
                         router)
        env = out.tool_results[0]
        assert env["status"] == "timeout"
        assert env["status"] != "ok"
        assert env["retryable"] is True
        # Модельно-видимый канал не изменился.
        assert "ОШИБКА execute_web_search" in out.tool_context

    def test_exception_text_is_error(self):
        info = tool_result.classify_output(
            "query_chat_memory", "ОШИБКА query_chat_memory: RuntimeError")
        assert info["status"] == "error"
        assert info["error_type"] == "RuntimeError"


class TestStatusMapping:
    def test_partial_keeps_payload_status(self):
        payload = json.dumps({"status": "partial", "stats": {"status": "ok",
                                                             "value": 5}})
        info = tool_result.classify_output("dig_into_lore", payload)
        assert info["status"] == "ok"
        assert info["partial"] is True
        assert info["data"]["status"] == "partial"     # mca-15 не подменяется
        assert info["data"]["stats"]["status"] == "ok"

    def test_not_found_maps_empty(self):
        info = tool_result.classify_output(
            "dig_into_lore", json.dumps({"status": "not_found",
                                         "message": "нет"}))
        assert info["status"] == "empty"
        assert info["error_code"] == "not_found"

    def test_unsupported_maps_empty_stats_unsupported(self):
        info = tool_result.classify_output(
            "query_chat_memory",
            json.dumps({"status": "unsupported", "value": None,
                        "reason": "stats_unsupported"}))
        assert info["status"] == "empty"
        assert info["error_code"] == "stats_unsupported"
        assert info["data"]["status"] == "unsupported"

    def test_stats_count_error_maps_error(self):
        payload = json.dumps({"status": "error",
                              "stats": {"status": "error",
                                        "reason": "stats_count_error"},
                              "message": "счётчик недоступен"})
        info = tool_result.classify_output("dig_into_lore", payload)
        assert info["status"] == "error"
        assert info["error_code"] == "stats_count_error"

    def test_insufficient_output_budget_maps_empty(self):
        info = tool_result.classify_output(
            "dig_into_lore",
            json.dumps({"status": "insufficient_output_budget", "value": None,
                        "reason": "insufficient_output_budget"}))
        assert info["status"] == "empty"
        assert info["error_code"] == "insufficient_output_budget"

    def test_disabled_text_denied(self):
        info = tool_result.classify_output(
            "dig_into_lore", "Инструмент dig_into_lore отключен.")
        assert info["status"] == "denied"
        assert info["error_code"] == "disabled"

    def test_disabled_payload_denied(self):
        info = tool_result.classify_output(
            "generate_image", json.dumps({"status": "error",
                                          "message": "Генерация изображений "
                                                     "отключена"}))
        assert info["status"] == "denied"
        assert info["error_code"] == "disabled"

    def test_retryable_closed_rules(self):
        # provider_unavailable — транзиентная причина идемпотентного чтения.
        info = tool_result.classify_output(
            "execute_web_search",
            json.dumps({"status": "error", "error": "provider_unavailable"}))
        assert info["retryable"] is True
        # paid media: даже timeout не ретраится автоматически.
        paid = tool_result.classify_output(
            "generate_image",
            json.dumps({"status": "error", "reason": "timeout"}))
        assert paid["status"] == "timeout"
        assert paid["retryable"] is False
        # empty/denied/cancelled/delivery_unknown — всегда false.
        assert tool_result.classify_output(
            "query_chat_memory", "ничего не найдено")["retryable"] is False
        for status in ("cancelled", "delivery_unknown"):
            info = tool_result.classify_output(
                "generate_image", "{}", signal={"status": status})
            assert info["retryable"] is False

    @pytest.mark.asyncio
    async def test_signal_consumed_once_with_ids(self):
        class SignalRouter:
            async def dispatch(self, name, arguments, ctx):
                tool_result.set_signal(ctx, {
                    "status": "cancelled", "error_code": "cancelled",
                    "external_operation_id": "op-77",
                    "evidence_refs": ["msg:5"],
                    "usage": {"input_tokens": 1, "output_tokens": 2,
                              "cost_usd": None, "price_known": False,
                              "source": "image"}})
                return "частичный результат"

        ctx = ToolContext(-100, "q")
        out = await _run(FakeLLM([_tc("c1", "generate_image", {"prompt": "к"}),
                                  _text("финал")]), SignalRouter(), ctx)
        env = out.tool_results[0]
        assert env["status"] == "cancelled"
        assert env["retryable"] is False
        assert env["external_operation_id"] == "op-77"
        assert env["evidence_refs"] == ["msg:5"]
        assert env["usage"]["cost_usd"] is None
        assert env["usage"]["price_known"] is False
        assert tool_result.take_signal(ctx) is None      # одноразово


class TestCanonicalEnvelope:
    @pytest.mark.asyncio
    async def test_envelope_additive_keys_and_duration(self):
        out = await _run(FakeLLM([_tc("c1", "query_chat_memory",
                                      {"query": "b"}), _text("f")]),
                         FakeRouter({"query_chat_memory": "B"}))
        env = out.tool_results[0]
        assert set(env) == LEGACY_KEYS | {
            "category", "retryable", "duration_ms", "usage",
            "external_operation_id", "evidence_refs", "partial"}
        assert env["category"] == "memory_read"
        assert env["retryable"] is False
        assert isinstance(env["duration_ms"], int)
        assert env["usage"] == {}
        assert env["partial"] is False


# ── T-4948: SafeFetcher → ToolResult (M-MCA02-3) ─────────────────────────────


class _Extractor:
    def __init__(self, exc):
        self.exc = exc

    async def extract(self, url, max_symbols):
        raise self.exc


def _article_router(exc):
    return ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                               extractor=_Extractor(exc)))


class TestSafeFetchMapping:
    @pytest.mark.asyncio
    async def test_safe_fetch_timeout_maps_retryable(self):
        exc = WebContentExtractionFailedException(
            "all failed",
            safe_error=safe_fetch.SafeFetchError(
                "safe_fetch_timeout", "stream", "request timeout",
                retryable=True))
        ctx = ToolContext(-100, "q")
        raw = await _article_router(exc).dispatch(
            "fetch_article", {"url": "https://a.b/c"}, ctx)
        # Модельно-видимый payload не изменился (M-MCA02-3).
        assert json.loads(raw)["error"] == "extract_failed"
        info = tool_result.classify_output(
            "fetch_article", raw, signal=tool_result.take_signal(ctx))
        assert info["status"] == "timeout"
        assert info["error_code"] == "safe_fetch_timeout"
        assert info["retryable"] is True
        assert info["data"]["stage"] == "stream"

    @pytest.mark.asyncio
    async def test_policy_block_not_retryable(self):
        exc = WebContentExtractionFailedException(
            "destination blocked",
            safe_error=safe_fetch.SafeFetchError(
                "destination_blocked", "resolve", "blocked", retryable=False))
        ctx = ToolContext(-100, "q")
        raw = await _article_router(exc).dispatch(
            "fetch_article", {"url": "https://a.b/c"}, ctx)
        info = tool_result.classify_output(
            "fetch_article", raw, signal=tool_result.take_signal(ctx))
        assert info["status"] == "error"
        assert info["error_code"] == "destination_blocked"
        assert info["retryable"] is False
        assert info["data"]["stage"] == "resolve"

    @pytest.mark.asyncio
    async def test_dispatch_clears_stale_signal(self):
        ctx = ToolContext(-100, "q")
        tool_result.set_signal(ctx, {"status": "cancelled"})
        raw = await ToolRouter(ToolDeps(search=MagicMock(),
                                        memory=MagicMock())).dispatch(
            "nope", {}, ctx)
        assert "неизвестный инструмент" in raw
        assert tool_result.take_signal(ctx) is None


# ── T-4946: лимиты D2 (env-only поверх существующих cap'ов) ──────────────────


class TestLimits:
    def test_env_numbers_visible_with_current_defaults(self):
        assert settings.MCA_TOOL_MAX_TOTAL_CALLS == 6
        assert settings.MCA_TOOL_MAX_METERED_CALLS == 4
        assert settings.MCA_TOOL_MAX_SAME_CALL == 2
        assert settings.MCA_TOOL_CHAIN_TIMEOUT_SECONDS == 360.0
        assert settings.MCA_TOOL_TRANSIENT_RETRIES_MAX == 2
        assert tool_result.transient_retries_max() == 2

    def test_env_numbers_not_in_catalog(self):
        from services import param_catalog as pc
        for name in ("MCA_TOOL_MAX_TOTAL_CALLS", "MCA_TOOL_MAX_METERED_CALLS",
                     "MCA_TOOL_MAX_SAME_CALL", "MCA_TOOL_CHAIN_TIMEOUT_SECONDS",
                     "MCA_TOOL_TRANSIENT_RETRIES_MAX",
                     "MCA_TOOL_RESULT_ENABLED",
                     "MCA_TOOL_DELIVERY_GUARD_ENABLED",
                     "MCA_COST_ACCOUNTING_ENABLED"):
            assert name not in pc.REGISTRY

    @pytest.mark.asyncio
    async def test_env_total_cap_enforced(self, monkeypatch):
        monkeypatch.setattr(type(settings), "MCA_TOOL_MAX_TOTAL_CALLS", 3)
        answers = [
            _tc2(f"r{r}", [("query_chat_memory", {"query": f"q{r}a"}),
                           ("query_chat_memory", {"query": f"q{r}b"})])
            for r in range(4)]
        out = await _run(FakeLLM(answers), FakeRouter())
        assert out.reason == "chain_call_limit"
        denied = [e for e in out.tool_results if e["status"] == "denied"]
        assert denied[-1]["data"]["value"] == 3

    @pytest.mark.asyncio
    async def test_media_deadline_separate_from_chain(self, monkeypatch):
        from services import media_execution as me
        monkeypatch.setattr(type(settings), "MCA_TOOL_CHAIN_TIMEOUT_SECONDS",
                            999.0)
        windows = me.resolve_windows("p", "m", "generate")
        assert windows.total_deadline == 180.0     # cold default политики
        assert windows.total_deadline != 999.0

    @pytest.mark.asyncio
    async def test_limit_result_explicit_reason_no_infinite_loop(self):
        answers = [
            _tc2(f"r{r}", [("query_chat_memory", {"query": f"q{r}a"}),
                           ("query_chat_memory", {"query": f"q{r}b"})])
            for r in range(4)]
        out = await _run(FakeLLM(answers), FakeRouter())
        assert out.degraded is True
        assert out.reason == "chain_call_limit"
        assert len(out.tool_results) == 7           # 6 исполнено + 1 denied


# ── T-4947: idempotency key / delivery_unknown (A21) ─────────────────────────


class TestIdempotency:
    def test_key_deterministic_and_sensitive(self):
        base = tool_result.idempotency_key(5, "corr", "generate_image",
                                           "fp", "media_submit")
        assert len(base) == 16
        assert base == tool_result.idempotency_key(5, "corr", "generate_image",
                                                   "fp", "media_submit")
        assert base != tool_result.idempotency_key(6, "corr", "generate_image",
                                                   "fp", "media_submit")
        assert base != tool_result.idempotency_key(5, "c2", "generate_image",
                                                   "fp", "media_submit")
        assert base != tool_result.idempotency_key(5, "corr", "fetch_article",
                                                   "fp", "media_submit")
        assert base != tool_result.idempotency_key(5, "corr", "generate_image",
                                                   "fp", "tool_call")
        int(base, 16)

    def test_key_r17_safe_no_raw_args(self):
        key = tool_result.idempotency_key(5, "corr", "generate_image",
                                          "deadbeefdeadbeef", "media_submit")
        assert "кот" not in key and "https" not in key


class TestDeliveryUnknown:
    @pytest.mark.asyncio
    async def test_send_failed_single_external_call_no_blind_retry(
            self, monkeypatch):
        monkeypatch.setattr(ig, "unified_image_request_enabled", lambda: False)
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))
        send = AsyncMock(return_value=ig.GenerationResult(
            ok=False, reason="send_failed"))
        monkeypatch.setattr(ig, "generate_and_send", send)
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock()))
        llm = FakeLLM([
            _tc("c1", "generate_image", {"prompt": "кот"}),
            _tc("c2", "generate_image", {"prompt": "кот"}),
            _text("финал")])
        out = await _run(llm, router)
        # A21: ровно один внешний вызов, слепого повтора нет.
        assert send.await_count == 1
        envs = [e for e in out.tool_results if e["tool"] == "generate_image"]
        assert len(envs) == 2
        assert envs[0]["status"] == "delivery_unknown"
        assert envs[0]["retryable"] is False
        assert envs[0]["error_code"] == "delivery_unknown"
        assert envs[1]["duplicate"] is True
        assert envs[1]["status"] == "delivery_unknown"
        # Модельно-видимый канал остался прежним JSON.
        assert '"status": "error"' in out.tool_context

    @pytest.mark.asyncio
    async def test_confirmed_success_no_retry(self):
        router = FakeRouter({"generate_image": json.dumps(
            {"status": "success", "message": "ok"})})
        llm = FakeLLM([_tc("c1", "generate_image", {"prompt": "кот"}),
                       _tc("c2", "generate_image", {"prompt": "кот"}),
                       _text("финал")])
        out = await _run(llm, router)
        assert len(router.calls) == 1                 # повтор запрещён
        envs = out.tool_results
        assert envs[0]["status"] == "ok"
        assert envs[1]["duplicate"] is True
        assert envs[1]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_k2_off_no_marking_and_no_guard(self, monkeypatch):
        monkeypatch.setattr(type(settings),
                            "MCA_TOOL_DELIVERY_GUARD_ENABLED", False)
        monkeypatch.setattr(ig, "unified_image_request_enabled", lambda: False)
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))
        send = AsyncMock(return_value=ig.GenerationResult(
            ok=False, reason="send_failed"))
        monkeypatch.setattr(ig, "generate_and_send", send)
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock()))
        llm = FakeLLM([_tc("c1", "generate_image", {"prompt": "кот"}),
                       _tc("c2", "generate_image", {"prompt": "кот"}),
                       _text("финал")])
        out = await _run(llm, router)
        # K2 OFF → прежняя деривация/поведение: error/send_failed, ≤2 вызова.
        assert send.await_count == 2
        envs = [e for e in out.tool_results if e["tool"] == "generate_image"]
        assert envs[0]["status"] == "error"
        assert envs[0]["error_code"] == "send_failed"

    def test_idempotency_key_passed_to_durable_media_job(self):
        import inspect
        from services import media_execution as me
        assert "idempotency_key" in inspect.signature(
            me.begin_media_job).parameters


# ── OFF-паритет K1 ───────────────────────────────────────────────────────────


class TestK1OffParity:
    @pytest.mark.asyncio
    async def test_legacy_envelope_bytes(self, monkeypatch):
        monkeypatch.setattr(type(settings), "MCA_TOOL_RESULT_ENABLED", False)
        llm = FakeLLM([_tc("c1", "dig_into_lore", {"query": "x"}),
                       _text("финал")])
        router = FakeRouter({"dig_into_lore": json.dumps(
            {"status": "not_found", "message": "ничего"})})
        out = await _run(llm, router)
        env = out.tool_results[0]
        # legacy `_classify_output`: not_found НЕ меняет status (ok).
        assert env["status"] == "ok"
        assert env["error_code"] == "not_found"
        assert set(env) == LEGACY_KEYS

    @pytest.mark.asyncio
    async def test_legacy_ok_error_and_skipped(self, monkeypatch):
        monkeypatch.setattr(type(settings), "MCA_TOOL_RESULT_ENABLED", False)
        monkeypatch.setattr(type(settings), "MCA_TOOL_CHAIN_TIMEOUT_SECONDS",
                            -1.0)
        llm = FakeLLM([_tc("c1", "execute_web_search", {"query": "x"}),
                       _text("финал")])
        out = await _run(llm, FakeRouter())
        env = out.tool_results[0]
        assert env["status"] == "skipped"
        assert env["data"] is None
        assert set(env) == LEGACY_KEYS

    @pytest.mark.asyncio
    async def test_k1_on_same_inputs_canonical(self):
        llm = FakeLLM([_tc("c1", "dig_into_lore", {"query": "x"}),
                       _text("финал")])
        router = FakeRouter({"dig_into_lore": json.dumps(
            {"status": "not_found", "message": "ничего"})})
        out = await _run(llm, router)
        assert out.tool_results[0]["status"] == "empty"
        assert "category" in out.tool_results[0]
