"""ASAP 4.2 Step 2c-1 (T-4808…T-4816) — targeted tests.

Покрывает: capacity live-precedence + capability-aware reserve; streaming
Mode B capability + SSE assembly; NanoGPT edit contract (обе ветки) +
sanitized 400; dynamic prompt-limit discovery/cache/invalidation; P0–P3
compiler (semantic compression, no `[:N]`, overflow reason); supervisor
attempt-budget visibility.
"""
from __future__ import annotations

import json

import pytest

from services import image_capabilities as cap
from services import image_prompt_compiler as ipc
from services import cover_style_edit as cse
from services import model_capacity as mc


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_caches():
    mc.invalidate_capacity_cache()
    cap.reset_cache()
    cse._ROUTE_CACHE.clear()
    yield
    mc.invalidate_capacity_cache()
    cap.reset_cache()
    cse._ROUTE_CACHE.clear()


def _disable_live_precedence(monkeypatch):
    monkeypatch.setattr(
        type(mc.settings), "SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED", False,
        raising=False)


# ── T-4808: capacity live metadata precedence ───────────────────────────────

@pytest.mark.asyncio
async def test_live_metadata_beats_stale_registry(monkeypatch):
    """Live catalog суверенен: stale registry (131072) НЕ занижает live
    capability (200000)."""
    async def _catalog(url, *, headers=None):
        if "nano-gpt.com" in url:
            return {"data": [{"id": "deepseek-chat",
                              "context_length": 200000,
                              "max_output_tokens": 32768}]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _catalog)
    result = await mc.resolve_capacity("https://nano-gpt.com/api/v1",
                                       "deepseek-chat")
    assert result.source == mc.SOURCE_PROVIDER_CATALOG
    assert result.effective_context_window == 200000     # live, не min(registry)
    assert result.declared_context_window == 131072      # registry виден
    assert result.max_output_tokens == 32768


@pytest.mark.asyncio
async def test_legacy_min_runtime_declared_when_off(monkeypatch):
    """OFF → прежний min(live catalog, registry) байт-в-байт."""
    async def _catalog(url, *, headers=None):
        return {"data": [{"id": "deepseek-chat", "context_length": 200000}]}

    monkeypatch.setattr(mc, "_http_get_json", _catalog)
    _disable_live_precedence(monkeypatch)
    result = await mc.resolve_capacity("https://nano-gpt.com/api/v1",
                                       "deepseek-chat")
    assert result.effective_context_window == 131072


def test_cache_key_includes_route():
    k1 = mc._cache_key("https://nano-gpt.com/api/v1", "m")
    k2 = mc._cache_key("https://nano-gpt.com/api/v1", "m", "image_edits")
    k3 = mc._cache_key("https://nano-gpt.com/api/v1", "m", "image_api")
    assert k1 != k2 != k3
    # Смена base_url/model/provider → другой ключ.
    assert mc._cache_key("https://other.example/v1", "m") != k1
    assert mc._cache_key("https://nano-gpt.com/api/v1", "m2") != k1


@pytest.mark.asyncio
async def test_provider_switch_re_resolves(monkeypatch):
    async def _catalog(url, *, headers=None):
        if "nano-gpt.com" in url:
            return {"data": [{"id": "model-x", "context_length": 65536}]}
        if "openrouter.ai" in url:
            return {"data": [{"id": "model-x", "context_length": 32768}]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _catalog)
    r1 = await mc.resolve_capacity("https://nano-gpt.com/api/v1", "model-x")
    r2 = await mc.resolve_capacity("https://openrouter.ai/api/v1", "model-x")
    assert r1.effective_context_window == 65536
    assert r2.effective_context_window == 32768


# ── T-4809: capability-aware output reserve ─────────────────────────────────

def test_capability_reserve_uses_max_output():
    r = mc.capability_aware_output_reserve(
        effective_context=131072, max_output_tokens=8000,
        target_output=4000, safety_margin_ratio=0.02)
    assert 4000 <= r <= 8000
    # max_output меньше target → клампится max_output (floor 1024).
    small = mc.capability_aware_output_reserve(
        effective_context=131072, max_output_tokens=2000,
        target_output=4000)
    assert small == 2000


def test_capability_reserve_unknown_falls_to_ratio_floor():
    expected = mc.output_reserve_tokens(131072)
    got = mc.capability_aware_output_reserve(
        effective_context=131072, max_output_tokens=None, target_output=4000)
    assert got == expected


def test_capability_reserve_off_parity(monkeypatch):
    monkeypatch.setattr(
        type(mc.settings), "SUMMARY_OUTPUT_RESERVE_CAPABILITY_ENABLED", False,
        raising=False)
    got = mc.capability_aware_output_reserve(
        effective_context=131072, max_output_tokens=8000, target_output=4000)
    assert got == mc.output_reserve_tokens(131072)


# ── T-4810: streaming Mode B capability + SSE assembly ──────────────────────

def test_declare_streaming_capability_follows_flag(monkeypatch):
    from services import summary_llm_supervisor as sup
    monkeypatch.setattr(type(sup.settings),
                        "SUMMARY_LLM_STREAMING_MODE_ENABLED", True)
    caps = sup.declare_execution_capabilities("nano-gpt.com",
                                              "deepseek/deepseek-v4.1-flash")
    assert caps.supports_streaming_liveness is True
    assert caps.supports_async_status is False
    assert caps.opaque_sync_only is False
    assert caps.source == "openai_chat_stream_route"
    assert sup.select_execution_mode(caps) == sup.MODE_STREAM


def test_declare_capability_off_is_sync(monkeypatch):
    from services import summary_llm_supervisor as sup
    monkeypatch.setattr(type(sup.settings),
                        "SUMMARY_LLM_STREAMING_MODE_ENABLED", False)
    caps = sup.declare_execution_capabilities()
    assert caps.supports_streaming_liveness is False
    assert sup.select_execution_mode(caps) == sup.MODE_SYNC


class _FakeStreamResponse:
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status

    async def aread(self):
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCtx:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, *, json=None, headers=None):
        chunks = json.get("_chunks") if isinstance(json, dict) else None
        return _FakeStreamCtx(_FakeStreamResponse(chunks or []))


@pytest.mark.asyncio
async def test_stream_chat_completion_assembles_and_touches(monkeypatch):
    from services import llm_client as llm_mod
    delta_lines = [
        'data: ' + json.dumps(
            {"choices": [{"delta": {"content": "При"}}]}),
        'data: ' + json.dumps(
            {"choices": [{"delta": {"content": "вет"}}]}),
        'data: ' + json.dumps(
            {"choices": [{"delta": {}}],
             "usage": {"prompt_tokens": 3, "completion_tokens": 2}}),
        "data: [DONE]",
    ]
    captured = {}

    class _Client(_FakeAsyncClient):
        def stream(self, method, url, *, json=None, headers=None):
            captured["url"] = url
            captured["payload"] = json
            return _FakeStreamCtx(_FakeStreamResponse(delta_lines))

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    client = llm_mod.LLMClient.__new__(llm_mod.LLMClient)
    client._base_url = "https://nano-gpt.com/api/v1"
    client._chat_model = "deepseek/deepseek-v4.1-flash"
    client._timeout = 60.0
    touches = {"n": 0}

    content, usage = await client.stream_chat_completion(
        [{"role": "user", "content": "hi"}],
        api_key="k", base_url="https://nano-gpt.com/api/v1",
        on_activity=lambda: touches.__setitem__("n", touches["n"] + 1))
    assert content == "Привет"
    assert captured["payload"]["stream"] is True
    assert captured["url"].endswith("/chat/completions")
    assert touches["n"] >= 2
    assert usage["completion_tokens"] == 2


# ── T-4812/T-4813: NanoGPT edit contract + diagnostics ─────────────────────

def test_build_edit_payload_input_references(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(b"\x89PNG")
    payload = cse.build_edit_payload("p", model="m", image_paths=[str(p)])
    assert list(payload["input_references"]) and \
        payload["input_references"][0].startswith("data:image/png;base64,")
    assert "imageDataUrl" not in payload
    assert "imageDataUrls" not in payload


def test_build_image_edits_payload_single_and_array(tmp_path):
    p1 = tmp_path / "a.png"
    p1.write_bytes(b"aaa")
    p2 = tmp_path / "b.png"
    p2.write_bytes(b"bbb")
    single = cse.build_image_edits_payload("p", model="m",
                                           image_paths=[str(p1)])
    assert "imageDataUrl" in single and "imageDataUrls" not in single
    assert "input_references" not in single
    arr = cse.build_image_edits_payload("p", model="m",
                                        image_paths=[str(p1), str(p2)])
    assert "imageDataUrls" in arr and len(arr["imageDataUrls"]) == 2
    assert "input_references" not in arr


def test_build_image_edits_multipart(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(b"bytes")
    data, files = cse.build_image_edits_multipart(
        "p", model="m", image_paths=[str(p)])
    assert data["model"] == "m"
    assert len(files) == 1 and files[0][0] == "image"


def test_classify_route_from_endpoints():
    assert cse._classify_route_from_endpoints(
        {"routes": [{"path": "/api/v1/images/edit"}]}) == cse.ROUTE_IMAGE_EDITS
    assert cse._classify_route_from_endpoints(
        {"input_reference_constraints": {"max_items": 3}}) == cse.ROUTE_IMAGE_API
    assert cse._classify_route_from_endpoints({}) == cse.ROUTE_UNVERIFIED
    assert cse._classify_route_from_endpoints(None) == cse.ROUTE_UNVERIFIED


@pytest.mark.asyncio
async def test_edit_route_unverified_fail_soft():
    res = await cse.edit_image("p", base_image_path=None,
                               reference_paths=None, base_url="https://x/v1",
                               model="m", route=cse.ROUTE_UNVERIFIED)
    assert res.ok is False
    assert res.reason == "route_unverified"


class _CaptureTransport:
    def __init__(self, status=200, body=None):
        self.calls = []
        self.status = status
        self.body = body or {
            "data": [{"b64_json": "aGk="}]}   # b64 "hi"

    async def __call__(self, url, payload, headers, timeout):
        self.calls.append((url, payload))

        class _Resp:
            status_code = self.status

            def json(_self):
                return self.body

        return _Resp()


@pytest.mark.asyncio
async def test_edit_image_uses_image_edits_branch(tmp_path):
    p = tmp_path / "base.png"
    p.write_bytes(b"img")
    transport = _CaptureTransport()
    res = await cse.edit_image("prompt", base_image_path=str(p),
                               reference_paths=None, base_url="https://x/v1",
                               model="m", api_key="k",
                               route=cse.ROUTE_IMAGE_EDITS,
                               transport=transport)
    assert res.ok is True
    url, payload = transport.calls[0]
    assert url.endswith("/images/edit")
    assert "imageDataUrl" in payload and "input_references" not in payload


@pytest.mark.asyncio
async def test_edit_image_legacy_uses_input_references(tmp_path, monkeypatch):
    p = tmp_path / "base.png"
    p.write_bytes(b"img")
    monkeypatch.setattr(type(cse.settings),
                        "COVER_STYLE_PROVIDER_ROUTES_ENABLED", False,
                        raising=False)
    transport = _CaptureTransport()
    res = await cse.edit_image("prompt", base_image_path=str(p),
                               reference_paths=None, base_url="https://x/v1",
                               model="m", api_key="k", transport=transport)
    assert res.ok is True
    url, payload = transport.calls[0]
    assert url.endswith("/images")
    assert payload["input_references"] and "imageDataUrl" not in payload


def test_extract_provider_error_sanitized():
    body = {
        "error": {"code": "image_input_too_large",
                  "message": "image data:image/png;base64,AAAA too big "
                             "see https://x/y?k=secret"},
        "request_id": "req_123",
    }
    diag = cap.extract_provider_error(body)
    assert diag["reason_code"] == "image_input_too_large"
    assert diag["request_id"] == "req_123"
    assert "data:image" not in diag.get("message", "")
    assert "secret" not in diag.get("message", "")


@pytest.mark.asyncio
async def test_edit_image_400_diagnostics_no_secrets(tmp_path):
    p = tmp_path / "base.png"
    p.write_bytes(b"img")
    transport = _CaptureTransport(status=400, body={
        "error": {"code": "missing_image_input", "message": "bad key sk-xyz"}})
    res = await cse.edit_image("SECRET_PROMPT", base_image_path=str(p),
                               reference_paths=None, base_url="https://x/v1",
                               model="m", api_key="k",
                               route=cse.ROUTE_IMAGE_API, transport=transport)
    assert res.ok is False
    assert res.reason == "bad_request"
    diag = res.meta.get("provider_error") or {}
    assert diag.get("reason_code") == "missing_image_input"
    assert "SECRET_PROMPT" not in json.dumps(res.meta)
    assert "sk-xyz" not in json.dumps(res.meta)


# ── T-4814: dynamic prompt-limit discovery/cache ────────────────────────────

def test_extract_prompt_limit_patterns():
    assert cap.extract_prompt_limit("prompt max 1234 chars") == (1234, "chars")
    assert cap.extract_prompt_limit("maximum prompt length is 900") == \
        (900, "chars")
    assert cap.extract_prompt_limit("no limit mentioned") is None
    assert cap.extract_prompt_limit("") is None


def test_parse_discovery_prompt_limit_model_then_route():
    entry = {"capabilities": {"image_to_image": True},
             "max_prompt_length": 2000}
    c = cap.parse_discovery(entry, {"prompt_limit": 800})
    assert c.prompt_limit.value == 2000
    assert c.prompt_limit.source == cap.SOURCE_LIVE_MODEL
    # model-слой пуст → route-слой.
    c2 = cap.parse_discovery({"capabilities": {"image_to_image": True}},
                             {"max_prompt_length": 800})
    assert c2.prompt_limit.value == 800
    assert c2.prompt_limit.source == cap.SOURCE_LIVE_ROUTE


def test_runtime_limit_cached_per_route_no_leak():
    cap.record_runtime_limit("nanogpt", "https://x/v1", "m", "image_edits",
                             800, "chars")
    caps_edits = cap.resolve_capabilities("nanogpt", "https://x/v1", "m",
                                          route="image_edits")
    assert caps_edits.prompt_limit.value == 800
    assert caps_edits.prompt_limit.source == cap.SOURCE_RUNTIME_DISCOVERED
    # Другой route не получает 800.
    caps_api = cap.resolve_capabilities("nanogpt", "https://x/v1", "m",
                                        route="image_api")
    assert caps_api.prompt_limit.value is None
    # Смена model инвалидирует.
    caps_other_model = cap.resolve_capabilities("nanogpt", "https://x/v1",
                                                "m2", route="image_edits")
    assert caps_other_model.prompt_limit.value is None


def test_no_hardcoded_800_in_limit_sources():
    import ast
    import pathlib
    for name in ("image_capabilities.py", "image_prompt_compiler.py"):
        src = (pathlib.Path(__file__).resolve().parents[1] / "services"
               / name).read_text("utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == 800:
                pytest.fail(f"hardcoded 800 in {name}")


# ── T-4815/T-4816: P0–P3 compiler ───────────────────────────────────────────

def _caps(limit, unit="chars"):
    c = cap.conservative_unknown()
    c.prompt_limit = cap.PromptLimit(value=limit, unit=unit,
                                     source=cap.SOURCE_OVERRIDE)
    return c


def test_p0_p1_never_cut_p3_dropped():
    comps = [
        ipc.PromptComponent("P0 механика редактирования", priority=ipc.P0,
                            label="p0"),
        ipc.PromptComponent("P1 стиль и бренд", priority=ipc.P1, label="p1"),
        ipc.PromptComponent("P2 контекст summary " * 3, priority=ipc.P2,
                            label="p2"),
        ipc.PromptComponent("P3 декоративный hint " * 5, priority=ipc.P3,
                            label="p3"),
    ]
    res = ipc.compile_prompt(comps, capabilities=_caps(60),
                             budget_component="")
    assert "P0 механика редактирования" in res.prompt
    assert "P1 стиль и бренд" in res.prompt
    assert "P3" in res.dropped or "p3" in res.dropped
    assert res.exceeded is False
    assert res.original_len > len(res.prompt)


def test_p0_p1_overflow_gives_reason_not_scissors():
    comps = [
        ipc.PromptComponent("P0 " + "x" * 80, priority=ipc.P0, label="p0"),
        ipc.PromptComponent("P1 " + "y" * 80, priority=ipc.P1, label="p1"),
    ]
    res = ipc.compile_prompt(comps, capabilities=_caps(20))
    assert res.exceeded is True
    assert res.reason == "prompt_limit_exceeded"
    # Никаких строковых ножниц: полный P0/P1 сохранён.
    assert "x" * 80 in res.prompt and "y" * 80 in res.prompt


def test_p2_compressed_to_semantic_brief():
    comps = [
        ipc.PromptComponent("P0 mech", priority=ipc.P0, label="p0"),
        ipc.PromptComponent("P1 style", priority=ipc.P1, label="p1"),
    ]
    long_brief = ("Первое предложение сюжета. " * 1
                  + "Второе очень длинное предложение " * 4)
    res = ipc.compile_prompt(comps, capabilities=_caps(45),
                             budget_component=long_brief)
    assert "mech" in res.prompt and "style" in res.prompt
    # semantic brief = первое предложение (не [:N] посреди слова).
    assert "Первое предложение сюжета." in res.prompt
    assert res.resolved_limit == 45


def test_compiler_off_legacy_parity(monkeypatch):
    monkeypatch.setattr(
        type(mc.settings), "IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED", False,
        raising=False)
    comps = [
        ipc.PromptComponent("P0 mandatory", priority=ipc.P0, label="p0"),
        ipc.PromptComponent("P2 hint", priority=ipc.P2, label="p2"),
    ]
    res = ipc.compile_prompt(comps, capabilities=_caps(1000))
    assert "P0 mandatory" in res.prompt and "P2 hint" in res.prompt
    assert res.exceeded is False


# ── T-4811: supervisor attempt-budget visibility ────────────────────────────

def test_supervisor_attempt_ceiling_and_network_attempts_visible():
    from services import summary_llm_supervisor as sup
    assert sup.ATTEMPT_CEILING_HTTP == 4
    state = sup.SupervisedCallState(
        request_id="r:op:1", provider="p", model="m", operation="l1",
        mode=sup.MODE_SYNC, started_at=0.0)
    state.http_attempts = 3
    snap = state.snapshot()
    assert snap["network_attempts"] == 3 == snap["http_attempts"]
