"""ASAP-3.1 (round 1028, ADR-1028-3) — тесты Model Capacity Resolver.

§40: known remote (registry) / unknown remote (fallback + warning + badge) /
developer override (побеждает) / model switch (cache invalidated).
§41: adapter-level fixtures Ollama `context_length` / llama.cpp `n_ctx`
(`/props`) / vLLM `max_model_len` — БЕЗ внешней сети (mock `_http_get_json`).
Kill-switch `MODEL_CAPACITY_RESOLVER_ENABLED` OFF → байт-в-байт прежний
путь (карта + env + fallback 16384).
"""
import pytest

from services import model_capacity as mc

pytestmark = pytest.mark.asap31


@pytest.fixture(autouse=True)
def _clean_cache():
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Адаптеры не ходят в сеть: `_http_get_json` → None (endpoint «недоступен»)."""

    async def _fail(url, *, headers=None):
        return None

    monkeypatch.setattr(mc, "_http_get_json", _fail)


def _override(monkeypatch, value):
    monkeypatch.setattr(
        type(mc.settings), "CHAT_MODEL_CONTEXT_WINDOW", value,
        raising=False)


async def _no_network(monkeypatch):
    """ASAP-3.2: nano-gpt/deepseek классы имеют catalog-адаптер — hermetic
    тест требует явного «endpoint недоступен» (→ registry/fallback)."""
    async def _fail(url, *, headers=None):
        return None

    monkeypatch.setattr(mc, "_http_get_json", _fail)


# ── §40.1: known remote model (registry) ────────────────────────────────────

@pytest.mark.asyncio
async def test_known_model_registry_source_no_fallback(monkeypatch):
    """Каталог недоступен → registry (честный source), fallback нет.

    ASAP-3.2: nano-gpt.com — отдельный provider class (D6); live catalog
    stub'ится сетью-вниз → registry-слой, семантика якоря §40.1 сохранена."""
    await _no_network(monkeypatch)
    window, source = await mc.resolve_stage_window(
        "https://nano-gpt.com/v1", "deepseek-chat")
    assert window == 131072
    assert source == mc.SOURCE_REGISTRY
    result = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                       "deepseek-chat")
    assert result.fallback_used is False
    assert result.confidence == "verified"


@pytest.mark.asyncio
async def test_prod_model_deepseek_v4_registry(monkeypatch):
    """Прод-модель инцидента (§74) больше не получает молчаливый 16384."""
    await _no_network(monkeypatch)
    window, source = await mc.resolve_stage_window(
        "https://nano-gpt.com/v1", "deepseek/deepseek-v4.1-flash")
    assert window == 131072
    assert source == mc.SOURCE_REGISTRY


# ── §40.3: completely unknown model → fallback + warning ────────────────────

@pytest.mark.asyncio
async def test_unknown_model_fallback_warns(caplog, monkeypatch):
    with caplog.at_level("WARNING", logger="services.model_capacity"):
        await _no_network(monkeypatch)
        window, source = await mc.resolve_stage_window(
            "https://nano-gpt.com/v1", "mystery-model-asap31")
    assert window == 16384
    assert source == mc.SOURCE_FALLBACK
    assert any("MODEL_CAPACITY_FALLBACK" in r.message for r in caplog.records)
    metrics = mc.capacity_metrics_snapshot()
    assert metrics["capacity_fallback_total"] >= 1


@pytest.mark.asyncio
async def test_unknown_model_fallback_cached_short_ttl(monkeypatch):
    """Fallback-результат кэшируется коротко — endpoint не долбится."""
    await _no_network(monkeypatch)
    await mc.resolve_stage_window("https://nano-gpt.com/v1", "mystery-2")
    key = mc._cache_key("https://nano-gpt.com/v1", "mystery-2")
    assert key in mc._CACHE


# ── §40.4: developer override — уровень 4 (AMEND AM-2, ADR-1028-8 D2) ───────

@pytest.mark.asyncio
async def test_developer_override_below_registry(monkeypatch):
    """ASAP 4.2 Step 2c-1 (AMEND ADR-1028-8 D2): override переезжает на
    УРОВЕНЬ 1 — при `SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED=ON` (default)
    explicit developer override сильнее registry. OFF → прежний уровень 4
    (registry выигрывает) байт-в-байт 2.58.47."""
    _override(monkeypatch, 500000)
    await _no_network(monkeypatch)
    result = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                       "deepseek-chat")
    assert result.effective_context_window == 500000
    assert result.source == mc.SOURCE_DEVELOPER_OVERRIDE
    assert result.fallback_used is False
    # OFF-kill-switch → legacy-контур: registry выше override.
    monkeypatch.setattr(
        type(mc.settings), "SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED", False,
        raising=False)
    mc.invalidate_capacity_cache()
    legacy = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                       "deepseek-chat")
    assert legacy.source == mc.SOURCE_REGISTRY
    assert legacy.effective_context_window == 131072


@pytest.mark.asyncio
async def test_developer_override_applies_above_fallback(monkeypatch):
    """Override применяется ТОЛЬКО когда runtime/каталог/реестр не дали
    значения (уровень 4 перед консервативным fallback, уровень 5)."""
    _override(monkeypatch, 500000)
    await _no_network(monkeypatch)
    result = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                       "mystery-override-model")
    assert result.effective_context_window == 500000
    assert result.source == mc.SOURCE_DEVELOPER_OVERRIDE
    assert result.fallback_used is False
    # Override входит в ключ кеша: смена = новый ключ (§38).
    _override(monkeypatch, None)
    result2 = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                        "mystery-override-model")
    assert result2.source == mc.SOURCE_FALLBACK
    assert result2.effective_context_window == 16384


@pytest.mark.asyncio
async def test_override_negative_is_never_capacity(monkeypatch):
    """§39: `-1` НИКОГДА не capacity (только policy Unlimited)."""
    _override(monkeypatch, -1)
    result = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                       "mystery-override-neg")
    assert result.source != mc.SOURCE_DEVELOPER_OVERRIDE
    assert result.effective_context_window == 16384


# ── §40.5: model switch → cache invalidated ────────────────────────────────

@pytest.mark.asyncio
async def test_model_switch_invalidates_cache(monkeypatch):
    await _no_network(monkeypatch)
    first = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                      "deepseek-chat")
    assert first.source == mc.SOURCE_REGISTRY
    second = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                       "mystery-switched")
    assert second.source == mc.SOURCE_FALLBACK
    assert second.effective_context_window != \
        first.effective_context_window
    # Явная инвалидация (config reload / refresh-кнопка).
    assert mc.invalidate_capacity_cache() >= 2
    assert not mc._CACHE


@pytest.mark.asyncio
async def test_base_url_switch_invalidates_cache(monkeypatch):
    await _no_network(monkeypatch)
    await mc.resolve_capacity("https://nano-gpt.com/v1", "deepseek-chat")
    await mc.resolve_capacity("https://api.deepseek.com/v1", "deepseek-chat")
    assert len(mc._CACHE) == 2


# ── §41: adapter fixtures (без сети) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_openrouter_catalog_context_length(monkeypatch):
    """Класс OpenRouter: `context_length` из model catalog, кэш."""

    async def _catalog(url, *, headers=None):
        if "openrouter.ai/api/v1/models" in url:
            return {"data": [
                {"id": "deepseek/deepseek-v4.1", "context_length": 1048576},
            ]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _catalog)
    result = await mc.resolve_capacity("https://openrouter.ai/api/v1",
                                       "deepseek/deepseek-v4.1")
    assert result.source == mc.SOURCE_PROVIDER_CATALOG
    assert result.effective_context_window == 1048576
    assert result.declared_context_window == 1048576
    assert result.fallback_used is False


@pytest.mark.asyncio
async def test_ollama_runtime_context_length(monkeypatch):
    """Ollama fixture: running model `context_length` используется."""

    async def _ps(url, *, headers=None):
        if url.endswith("/api/ps"):
            return {"models": [
                {"name": "qwen3:32b", "context_length": 16384},
            ]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _ps)
    result = await mc.resolve_capacity("http://localhost:11434/v1",
                                       "qwen3:32b")
    assert result.source == mc.SOURCE_RUNTIME
    assert result.runtime_context_window == 16384
    # §5: локальный runtime 16K при theoretical 128K → используется 16K.
    assert result.effective_context_window == 16384
    assert result.declared_context_window == 131072


@pytest.mark.asyncio
async def test_llama_cpp_props_n_ctx(monkeypatch):
    """llama.cpp fixture: `/props` → `n_ctx` (runtime)."""

    async def _props(url, *, headers=None):
        if url.endswith("/props"):
            return {"default_generation_settings": {"n_ctx": 32768},
                    "model_metadata": {"llama.context_length": 131072}}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _props)
    result = await mc.resolve_capacity("http://127.0.0.1:8080/v1",
                                       "llama-3.1-8b")
    assert result.source == mc.SOURCE_RUNTIME
    assert result.runtime_context_window == 32768
    assert result.effective_context_window == 32768


@pytest.mark.asyncio
async def test_vllm_model_info_max_model_len(monkeypatch):
    """vLLM fixture: deployment `max_model_len`, а не theoretical context."""

    async def _info(url, *, headers=None):
        if url.endswith("/model_info"):
            return {"max_model_len": 65536}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _info)
    result = await mc.resolve_capacity("http://10.0.0.5:8000/v1",
                                       "deepseek-chat")  # declared 131072
    assert result.source == mc.SOURCE_RUNTIME
    # deployment limit (65536) < theoretical (131072) → используется 65536.
    assert result.effective_context_window == 65536


@pytest.mark.asyncio
async def test_vllm_endpoint_unavailable_registry_fallback(monkeypatch):
    """Q8.4 санкция: недоступный metadata-endpoint НЕ блокирует резолв —
    registry + (developer override); НЕ выдумывать из имени модели."""

    async def _fail(url, *, headers=None):
        return None

    monkeypatch.setattr(mc, "_http_get_json", _fail)
    result = await mc.resolve_capacity("http://10.0.0.5:8000/v1",
                                       "deepseek-v4-custom-deploy")
    assert result.source == mc.SOURCE_REGISTRY
    assert result.effective_context_window == 131072


@pytest.mark.asyncio
async def test_generic_provider_regex_guessing_forbidden():
    """§6: generic OpenAI-compatible — НЕ выдумывать окно regex'ом из имени."""
    window, source = await mc.resolve_stage_window(
        "https://api.example-llm.com/v1",
        "some-supermodel-1048576k-unlimited")
    assert source == mc.SOURCE_FALLBACK
    assert window == 16384


# ── §5: runtime > theoretical ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_effective_is_min_runtime_declared(monkeypatch):
    async def _props(url, *, headers=None):
        if url.endswith("/props"):
            return {"n_ctx": 16384}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _props)
    result = await mc.resolve_capacity("http://127.0.0.1:8080/v1",
                                       "deepseek-chat")  # declared 131072
    assert result.runtime_context_window == 16384
    assert result.effective_context_window == 16384


# ── Kill-switch OFF: паритет прежнего пути ──────────────────────────────────

@pytest.mark.asyncio
async def test_resolver_off_legacy_path(monkeypatch):
    monkeypatch.setattr(type(mc.settings),
                        "MODEL_CAPACITY_RESOLVER_ENABLED", False,
                        raising=False)
    window, source = await mc.resolve_stage_window(
        "https://nano-gpt.com/v1", "deepseek-chat")
    assert (window, source) == (131072, mc.WINDOW_SOURCE_MAP)
    window2, source2 = await mc.resolve_stage_window(
        "https://nano-gpt.com/v1", "mystery-model-off-path")
    assert (window2, source2) == (16384, mc.WINDOW_SOURCE_FALLBACK)


@pytest.mark.asyncio
async def test_resolver_off_env_override(monkeypatch):
    monkeypatch.setattr(type(mc.settings),
                        "MODEL_CAPACITY_RESOLVER_ENABLED", False,
                        raising=False)
    _override(monkeypatch, 200000)
    window, source = await mc.resolve_stage_window(
        "https://nano-gpt.com/v1", "deepseek-chat")
    assert (window, source) == (200000, mc.WINDOW_SOURCE_ENV)


# ── Adaptive TTL (Q9) ───────────────────────────────────────────────────────

def test_ttl_local_capped_300s():
    assert mc._ttl_for(mc.PROVIDER_LLAMA_CPP) == 300
    assert mc._ttl_for(mc.PROVIDER_OLLAMA) == 300
    assert mc._ttl_for(mc.PROVIDER_GENERIC) >= 86400 // 2


def test_detect_provider_classes():
    assert mc.detect_provider_class("https://openrouter.ai/api/v1") == \
        mc.PROVIDER_OPENROUTER
    assert mc.detect_provider_class("http://localhost:11434/v1") == \
        mc.PROVIDER_OLLAMA
    assert mc.detect_provider_class("http://192.168.1.10:8080/v1") == \
        mc.PROVIDER_LLAMA_CPP
    # ASAP-3.2 (D6/T-4202): NanoGPT и Direct DeepSeek — отдельные identity
    # (не generic host).
    assert mc.detect_provider_class("https://nano-gpt.com/v1") == \
        mc.PROVIDER_NANOGPT
    assert mc.detect_provider_class("https://api.deepseek.com/v1") == \
        mc.PROVIDER_DEEPSEEK
    assert mc.detect_provider_class("") == mc.PROVIDER_GENERIC
