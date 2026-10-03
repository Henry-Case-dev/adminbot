"""ASAP-3.2 (round1029, ADR-1028-5 D6/D7, T-4202/T-4203) — Text Capacity
Resolver: NanoGPT catalog adapter / Direct DeepSeek verified_registry /
unknown честный unknown / discovery timeout (§53–§57, §69):

* NanoGPT (§53): live/public каталог `GET /api/v1/models?detailed=true`
  (схема верифицирована по официальным docs) → context window + max output;
  catalog недоступен → registry/fallback, source честен;
* Direct DeepSeek (§54): отдельная identity; verified official registry →
  source=`verified_registry`, НЕ `provider_catalog`;
* OpenRouter adapter сохранён (§55; существующие ASAP-3.1 якоря);
* Unknown provider (§56): НЕ угадывается из URL → conservative fallback с
  видимым source;
* §57: metadata fetch короткий (2 c), кэш, failure НЕ блокирует generation;
* §69: switch без code change — ключ кэша включает provider+base_url+model.
"""
import time

import pytest

from services import model_capacity as mc

# Прецедент ASAP-3.1: тесты resolver'а живут с прод-дефолтами флагов
# (иначе conftest глушит MODEL_CAPACITY_RESOLVER_ENABLED → legacy-путь).
pytestmark = pytest.mark.asap31


@pytest.fixture(autouse=True)
def _clean_cache():
    mc.invalidate_capacity_cache()
    # Модульные кэши legacy-пути/предупреждений — изоляция от якорных
    # тестов ASAP-3.1 (в т.ч. kill-switch OFF, заполняющий _WINDOW_CACHE).
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    yield
    mc.invalidate_capacity_cache()


async def _no_network(monkeypatch):
    async def _fail(url, *, headers=None):
        return None

    monkeypatch.setattr(mc, "_http_get_json", _fail)


# ── §53: NanoGPT provider adapter (live catalog) ────────────────────────────

@pytest.mark.asyncio
async def test_nanogpt_catalog_resolves_window_and_max_output(monkeypatch):
    """`context_length` + `max_output_tokens` из каталога; source =
    provider_catalog (честный source, НЕ registry guess)."""

    async def catalog(url, *, headers=None):
        if "nano-gpt.com" in url and "models" in url:
            return {"data": [
                {"id": "deepseek/deepseek-v4.1-flash",
                 "context_length": 131072, "max_output_tokens": 16384},
                {"id": "other/model", "context_length": 4096},
            ]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", catalog)
    result = await mc.resolve_capacity("https://nano-gpt.com/api/v1",
                                       "deepseek/deepseek-v4.1-flash")
    assert result.source == mc.SOURCE_PROVIDER_CATALOG
    assert result.effective_context_window == 131072
    assert result.max_output_tokens == 16384
    assert result.fallback_used is False
    assert result.confidence == "verified"


@pytest.mark.asyncio
async def test_nanogpt_catalog_missing_model_falls_to_registry(monkeypatch):
    """Модели нет в каталоге (или окна нет) → registry-слой, fallback нет."""

    async def catalog(url, *, headers=None):
        if "nano-gpt.com" in url:
            return {"data": [{"id": "other/model",
                              "context_length": 4096}]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", catalog)
    result = await mc.resolve_capacity("https://nano-gpt.com/api/v1",
                                       "deepseek-chat")
    assert result.source == mc.SOURCE_REGISTRY
    assert result.effective_context_window == 131072
    assert result.fallback_used is False


@pytest.mark.asyncio
async def test_nanogpt_catalog_unreachable_registry_fallback(monkeypatch):
    """§53: каталог недоступен → registry/fallback; Analytics видит честный
    source (registry), NOT provider_catalog."""
    await _no_network(monkeypatch)
    window, source = await mc.resolve_stage_window(
        "https://nano-gpt.com/api/v1", "deepseek-chat")
    assert (window, source) == (131072, mc.SOURCE_REGISTRY)
    result = await mc.resolve_capacity("https://nano-gpt.com/api/v1",
                                       "mystery-nanogpt-model")
    assert result.source == mc.SOURCE_FALLBACK
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_nanogpt_catalog_urls_both_documented_forms():
    """Route НЕ выдумывается: {base}/models + канонический /api/v1/models
    (когда base не содержит /api)."""
    urls = mc._nanogpt_catalog_urls("https://nano-gpt.com/api/v1")
    assert urls[0] == "https://nano-gpt.com/api/v1/models?detailed=true"
    urls2 = mc._nanogpt_catalog_urls("https://nano-gpt.com/v1")
    assert urls2[0] == "https://nano-gpt.com/v1/models?detailed=true"
    assert ("https://nano-gpt.com/api/v1/models?detailed=true"
            in urls2[1:])


# ── §54: Direct DeepSeek — verified_registry, НЕ provider_catalog ───────────

@pytest.mark.asyncio
async def test_deepseek_verified_registry_source(monkeypatch):
    await _no_network(monkeypatch)
    result = await mc.resolve_capacity("https://api.deepseek.com/v1",
                                       "deepseek-chat")
    assert result.source == mc.SOURCE_VERIFIED_REGISTRY
    assert result.source != mc.SOURCE_PROVIDER_CATALOG
    assert result.effective_context_window == 131072
    assert result.confidence == "verified"
    assert result.fallback_used is False


@pytest.mark.asyncio
async def test_deepseek_unknown_model_honest_fallback(monkeypatch):
    """DeepSeek-identity без registry-совпадения → честный fallback
    (НЕ угадываем из имени/URL, §56)."""
    await _no_network(monkeypatch)
    result = await mc.resolve_capacity("https://api.deepseek.com/v1",
                                       "mystery-deepseek-x")
    assert result.source == mc.SOURCE_FALLBACK
    assert result.fallback_used is True


# ── §55: OpenRouter adapter сохранён ────────────────────────────────────────

@pytest.mark.asyncio
async def test_openrouter_adapter_unchanged(monkeypatch):
    async def catalog(url, *, headers=None):
        if url == "https://openrouter.ai/api/v1/models":
            return {"data": [{"id": "qwen/qwen3", "context_length": 131072}]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", catalog)
    result = await mc.resolve_capacity("https://openrouter.ai/api/v1",
                                       "qwen/qwen3")
    assert result.source == mc.SOURCE_PROVIDER_CATALOG
    assert result.effective_context_window == 131072


# ── §19: local runtime сохранён ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_local_runtime_llamacpp_preserved(monkeypatch):
    async def props(url, *, headers=None):
        if url.endswith("/props"):
            return {"n_ctx": 16384}
        return None

    monkeypatch.setattr(mc, "_http_get_json", props)
    result = await mc.resolve_capacity("http://127.0.0.1:8080/v1",
                                       "llama-3.1-8b")
    assert result.source == mc.SOURCE_RUNTIME
    assert result.effective_context_window == 16384


# ── §56: unknown — не угадывать из URL, честный fallback ────────────────────

@pytest.mark.asyncio
async def test_unknown_provider_no_url_guessing(monkeypatch):
    await _no_network(monkeypatch)
    window, source = await mc.resolve_stage_window(
        "https://supermodel-hosting.example.com/v1",
        "ultra-model-1000000k-context")
    assert source == mc.SOURCE_FALLBACK
    assert window == 16384


# ── §57/§69: короткий fetch, кэш, инвалидация при switch ────────────────────

@pytest.mark.asyncio
async def test_discovery_failure_short_negative_cache(monkeypatch):
    """§57: discovery failure НЕ блокирует generation; fallback-результат
    кэшируется коротко (endpoint не долбится)."""
    calls = {"n": 0}

    async def fail(url, *, headers=None):
        calls["n"] += 1
        return None

    monkeypatch.setattr(mc, "_http_get_json", fail)
    for _ in range(3):
        result = await mc.resolve_capacity("https://nano-gpt.com/api/v1",
                                           "mystery-neg-cache")
    assert result.fallback_used is True
    assert calls["n"] == 1                     # TTL 300 c, не на каждый вызов


@pytest.mark.asyncio
async def test_provider_switch_no_code_change(monkeypatch):
    """§69: runtime switch NanoGPT → OpenRouter → direct DeepSeek БЕЗ code
    change: новый ключ кэша → новый source/window (cache invalidation)."""
    async def catalog(url, *, headers=None):
        if "nano-gpt.com" in url:
            return {"data": [{"id": "model-x", "context_length": 65536,
                              "max_output_tokens": 8192}]}
        if "openrouter.ai" in url:
            return {"data": [{"id": "model-x", "context_length": 32768}]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", catalog)
    r1 = await mc.resolve_capacity("https://nano-gpt.com/api/v1", "model-x")
    assert r1.source == mc.SOURCE_PROVIDER_CATALOG
    assert r1.effective_context_window == 65536
    r2 = await mc.resolve_capacity("https://openrouter.ai/api/v1", "model-x")
    assert r2.source == mc.SOURCE_PROVIDER_CATALOG
    assert r2.effective_context_window == 32768
    r3 = await mc.resolve_capacity("https://api.deepseek.com/v1", "deepseek-chat")
    assert r3.source == mc.SOURCE_VERIFIED_REGISTRY


@pytest.mark.asyncio
async def test_developer_override_applies_below_registry(monkeypatch):
    """AMEND ADR-1028-3 (ADR-1028-8 D2/AM-2): реестр/каталог выше override —
    живая модель на 131072 не сужается override'ом; lower-capacity сценарии
    (§48 Run 2) — через конфиг-фикстуру модели, не override."""
    monkeypatch.setattr(type(mc.settings), "CHAT_MODEL_CONTEXT_WINDOW",
                        777777, raising=False)
    await _no_network(monkeypatch)
    result = await mc.resolve_capacity("https://nano-gpt.com/api/v1",
                                       "deepseek-chat")
    assert result.source == mc.SOURCE_REGISTRY
    assert result.effective_context_window == 131072


# ── таймаут discovery (§57): adapter timeout ≤ 2 с ──────────────────────────

def test_adapter_timeout_short():
    assert mc._ADAPTER_TIMEOUT_SECONDS <= 2.0
