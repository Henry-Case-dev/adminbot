"""SMART-EXECUTION-RELIABILITY-01 stage D — единый capacity contract.

Покрытие owner-требований D1–D6 (source `2026-11-14-smart-execution-
reliability-01.md`, ЭТАП D):

* D1: неизвестная модель → `CHAT_UNKNOWN_MODEL_WINDOW` = 1 000 000
  (планировочная ОЦЕНКА), 16384 не возвращается ни одним путём;
* D2: precedence `proven_limit` → override (planning, capped) → runtime →
  provider catalog → verified cache → exact registry → 1M estimated;
  owner override виден с конфликтом, но не отменяет доказанный предел;
* D3: NanoGPT `z-ai/glm-5.3-flash-uncensored` через существующий
  `_adapter_nanogpt_catalog`: точное сопоставление ID (namespace/suffix/
  alias), реальные context/max output, обновление при смене модели;
  выдуманных записей и семейных догадок нет;
* D4: один resolver на все LLM-пути; окно фактически назначенной модели;
  fallback пересчитывается отдельно (без preemptive-min);
* D5: окно ≠ бюджет ≠ max_output; при budgets OFF доступно всё окно минус
  protocol/output reserve;
* D6: context length exceeded → structured parse → обновление capacity
  endpoint/model → payload в пределах доказанного предела, tool evidence
  сохраняются, повторы ограничены, 16384 не возвращается, миллионного
  probe нет.

Тесты герметичны: сеть (`_http_get_json`) всегда замокана, платных
LLM-вызовов нет. Маркер asap31 = прод-дефолты kill-switch (ON).
"""
import pytest

from config.settings import settings
from services import auto_budget as ab
from services import model_capacity as mc

pytestmark = pytest.mark.asap31

NANO_BASE = "https://nano-gpt.com/api/v1"
GLM_MODEL = "z-ai/glm-5.3-flash-uncensored"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    mc.invalidate_capacity_cache()
    mc.clear_proven_limits()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()

    async def _no_network(url, *, headers=None):
        return None

    monkeypatch.setattr(mc, "_http_get_json", _no_network)
    yield
    mc.invalidate_capacity_cache()
    mc.clear_proven_limits()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()


def _catalog(items):
    async def _get(url, *, headers=None):
        if "models" in str(url):
            return {"data": list(items)}
        return None

    return _get


# ── D1: неизвестная модель = 1M estimated, НЕ 16384 ────────────────────────

def test_factory_unknown_window_is_1m_not_16384():
    assert settings.CHAT_UNKNOWN_MODEL_WINDOW == 1_000_000
    assert mc.UNKNOWN_WINDOW_DEFAULT == 1_000_000
    assert mc._unknown_window() == 1_000_000


@pytest.mark.parametrize("value", [None, 0, -5, "garbage"])
def test_unknown_window_helper_never_falls_back_to_16384(monkeypatch, value):
    """D1: отсутствие/ноль/ошибка кастования не дают 16384."""
    monkeypatch.setattr(type(settings), "CHAT_UNKNOWN_MODEL_WINDOW", value,
                        raising=False)
    assert mc._unknown_window() == 1_000_000


def test_sync_resolver_unknown_is_estimated_1m():
    window, source = mc.resolve_model_context_window("no-such-model-d1")
    assert window == 1_000_000
    assert source == mc.WINDOW_SOURCE_FALLBACK


@pytest.mark.asyncio
async def test_async_resolver_unknown_is_estimated_not_verified():
    result = await mc.resolve_capacity(NANO_BASE, "no-such-model-d1")
    assert result.source == mc.SOURCE_ESTIMATED_UNKNOWN
    assert result.confidence == "estimated"
    assert result.fallback_used is False
    assert result.effective_context_window == 1_000_000


@pytest.mark.asyncio
async def test_legacy_killswitch_unknown_window_is_1m(monkeypatch):
    """D1 применяется и к legacy-контуру: 16384 удалён и там."""
    monkeypatch.setattr(type(settings), "MODEL_CAPACITY_RESOLVER_ENABLED",
                        False, raising=False)
    window, source = await mc.resolve_stage_window(
        NANO_BASE, "no-such-model-legacy")
    assert window == 1_000_000
    assert source == mc.WINDOW_SOURCE_FALLBACK


def test_evidence_window_unknown_is_1m():
    window, source = mc.resolve_evidence_window_tokens("no-such-evidence-d1")
    assert window == 1_000_000
    assert source == mc.WINDOW_SOURCE_FALLBACK


# ── D3: NanoGPT exact-ID path (мок-каталог, без платных вызовов) ───────────

@pytest.mark.asyncio
async def test_nanogpt_exact_id_resolves_after_namespace_strip(monkeypatch):
    """Запрошенный ID без namespace, каталог отдаёт `z-ai/...` — точное
    сопоставление по ID модели (не семейная догадка)."""
    monkeypatch.setattr(mc, "_http_get_json", _catalog([
        {"id": GLM_MODEL, "context_length": 202_752,
         "max_output_tokens": 32_768},
        {"id": "z-ai/glm-5.3-flash", "context_length": 131_072},
    ]))
    result = await mc.resolve_capacity(NANO_BASE, "glm-5.3-flash-uncensored")
    assert result.source == mc.SOURCE_PROVIDER_CATALOG
    assert result.effective_context_window == 202_752
    assert result.max_output_tokens == 32_768
    assert result.confidence == "verified"


@pytest.mark.asyncio
async def test_nanogpt_exact_id_matches_suffix_variant(monkeypatch):
    """`...:thinking` в каталоге — та же модель (routing-suffix)."""
    monkeypatch.setattr(mc, "_http_get_json", _catalog([
        {"id": f"{GLM_MODEL}:thinking", "context_length": 65_536},
    ]))
    result = await mc.resolve_capacity(NANO_BASE, GLM_MODEL)
    assert result.source == mc.SOURCE_PROVIDER_CATALOG
    assert result.effective_context_window == 65_536


@pytest.mark.asyncio
async def test_nanogpt_ambiguous_basename_is_honest_miss(monkeypatch):
    """Два разных namespace с одним basename → None, НЕ выбор наугад."""
    monkeypatch.setattr(mc, "_http_get_json", _catalog([
        {"id": "org-a/nano-model", "context_length": 32_768},
        {"id": "org-b/nano-model", "context_length": 65_536},
    ]))
    assert mc.catalog_item_for_model(
        [{"id": "org-a/nano-model"}, {"id": "org-b/nano-model"}],
        "nano-model") is None
    result = await mc.resolve_capacity(NANO_BASE, "nano-model")
    assert result.source == mc.SOURCE_ESTIMATED_UNKNOWN
    assert result.effective_context_window == 1_000_000


@pytest.mark.asyncio
async def test_nanogpt_catalog_unavailable_is_honest_unknown(monkeypatch):
    """Каталог недоступен → 1M с honest uncertainty, не 16384 и не verified."""
    async def _down(url, *, headers=None):
        return None

    monkeypatch.setattr(mc, "_http_get_json", _down)
    result = await mc.resolve_capacity(NANO_BASE, GLM_MODEL)
    assert result.source == mc.SOURCE_ESTIMATED_UNKNOWN
    assert result.confidence == "estimated"
    assert result.effective_context_window == 1_000_000


@pytest.mark.asyncio
async def test_nanogpt_catalog_miss_does_not_fabricate_entry():
    """D3: в реестре нет выдуманной записи под GLM-5.3/семейство."""
    assert mc._registry_exact_window(GLM_MODEL) is None
    assert mc._registry_exact_window("glm-5.3-flash-uncensored") is None
    assert not any("glm-5" in key for key in mc.MODEL_EXACT_WINDOWS)
    result = await mc.resolve_capacity(NANO_BASE, GLM_MODEL)
    assert result.source == mc.SOURCE_ESTIMATED_UNKNOWN


@pytest.mark.asyncio
async def test_family_name_never_defines_capacity(monkeypatch):
    """D2/D3: слова GLM/Flash/Pro/DeepSeek сами по себе ёмкость не задают."""
    for name in ("glm-5.3-flash-uncensored", "some-pro-flash-model",
                 "deepseek-v5.1-flash", "qwen3-next"):
        result = await mc.resolve_capacity(NANO_BASE, name)
        assert result.source == mc.SOURCE_ESTIMATED_UNKNOWN, name
        assert result.effective_context_window == 1_000_000, name


@pytest.mark.asyncio
async def test_model_switch_refreshes_capacity(monkeypatch):
    """D3: смена модели не переиспользует ёмкость предыдущей."""
    monkeypatch.setattr(mc, "_http_get_json", _catalog([
        {"id": GLM_MODEL, "context_length": 202_752,
         "max_output_tokens": 32_768},
        {"id": "z-ai/glm-5.3-flash", "context_length": 8_192},
    ]))
    first = await mc.resolve_capacity(NANO_BASE, GLM_MODEL)
    assert first.effective_context_window == 202_752
    second = await mc.resolve_capacity(NANO_BASE, "z-ai/glm-5.3-flash")
    assert second.model == "z-ai/glm-5.3-flash"
    assert second.effective_context_window == 8_192
    # Ключи кэша разные: старая ёмкость не «переехала» на новую модель.
    assert mc._cache_key(NANO_BASE, GLM_MODEL) != \
        mc._cache_key(NANO_BASE, "z-ai/glm-5.3-flash")


@pytest.mark.asyncio
async def test_known_small_and_large_windows(monkeypatch):
    monkeypatch.setattr(mc, "_http_get_json", _catalog([
        {"id": "small-model", "context_length": 8_192},
        {"id": "large-model", "context_length": 1_048_576},
    ]))
    small = await mc.resolve_capacity(NANO_BASE, "small-model")
    large = await mc.resolve_capacity(NANO_BASE, "large-model")
    assert (small.effective_context_window, small.source) == (
        8_192, mc.SOURCE_PROVIDER_CATALOG)
    assert (large.effective_context_window, large.source) == (
        1_048_576, mc.SOURCE_PROVIDER_CATALOG)


@pytest.mark.asyncio
async def test_custom_model_id_uses_catalog_exact_match(monkeypatch):
    """Custom alias провайдера — только точное сопоставление каталога."""
    monkeypatch.setattr(mc, "_http_get_json", _catalog([
        {"id": "vendor/custom-alias-7b", "context_length": 32_768},
    ]))
    result = await mc.resolve_capacity(NANO_BASE, "custom-alias-7b")
    assert result.source == mc.SOURCE_PROVIDER_CATALOG
    assert result.effective_context_window == 32_768


# ── D2: precedence и override ↔ доказанный предел ──────────────────────────

@pytest.mark.asyncio
async def test_override_is_planning_not_provider_verified(monkeypatch):
    monkeypatch.setattr(type(settings), "CHAT_MODEL_CONTEXT_WINDOW", 300_000,
                        raising=False)
    result = await mc.resolve_capacity(NANO_BASE, GLM_MODEL)
    assert result.source == mc.SOURCE_DEVELOPER_OVERRIDE
    assert result.confidence == "override"
    assert result.effective_context_window == 300_000
    assert result.override_value == 300_000


@pytest.mark.asyncio
async def test_proven_limit_beats_catalog_and_caps_override(monkeypatch):
    """D2/D6: доказанный физический предел сильнее каталога; override выше
    предела показывается, но effective = предел."""
    monkeypatch.setattr(mc, "_http_get_json", _catalog([
        {"id": GLM_MODEL, "context_length": 1_048_576},
    ]))
    catalog = await mc.resolve_capacity(NANO_BASE, GLM_MODEL)
    assert catalog.effective_context_window == 1_048_576
    monkeypatch.setattr(type(settings), "CHAT_MODEL_CONTEXT_WINDOW", 900_000,
                        raising=False)
    mc.record_proven_limit(NANO_BASE, GLM_MODEL, 128_000,
                           max_output_tokens=16_384,
                           requested_tokens=140_000)
    result = await mc.resolve_capacity(NANO_BASE, GLM_MODEL)
    assert result.source == mc.SOURCE_PROVEN_LIMIT
    assert result.confidence == "verified"
    assert result.effective_context_window == 128_000
    assert result.override_value == 900_000
    assert result.clamped_by_proven_limit is True
    assert result.proven_limit == 128_000
    assert result.as_window_meta()["clamped_by_proven_limit"] is True


@pytest.mark.asyncio
async def test_override_below_proven_limit_stays_owner_choice(monkeypatch):
    monkeypatch.setattr(type(settings), "CHAT_MODEL_CONTEXT_WINDOW", 64_000,
                        raising=False)
    mc.record_proven_limit(NANO_BASE, GLM_MODEL, 128_000)
    result = await mc.resolve_capacity(NANO_BASE, GLM_MODEL)
    assert result.source == mc.SOURCE_DEVELOPER_OVERRIDE
    assert result.effective_context_window == 64_000
    assert result.clamped_by_proven_limit is False


@pytest.mark.asyncio
async def test_verified_cache_used_by_sync_tool_path(monkeypatch):
    """D4: sync-потребитель видит уже подтверждённое окно того же endpoint."""
    monkeypatch.setattr(mc, "_http_get_json", _catalog([
        {"id": GLM_MODEL, "context_length": 202_752},
    ]))
    await mc.resolve_capacity(NANO_BASE, GLM_MODEL)
    window, source = mc.resolve_evidence_window_tokens(GLM_MODEL,
                                                       base_url=NANO_BASE)
    assert window == 202_752
    assert source == mc.SOURCE_PROVIDER_CATALOG
    # Чужой endpoint не наследует это значение.
    other_window, other_source = mc.resolve_evidence_window_tokens(
        GLM_MODEL, base_url="https://api.example-llm.com/v1")
    assert other_source == mc.WINDOW_SOURCE_FALLBACK
    assert other_window == 1_000_000


# ── D4: fallback пересчитывается, primary не занижается ────────────────────

@pytest.mark.asyncio
async def test_primary_chain_not_shrunk_by_small_fallback(monkeypatch):
    monkeypatch.setattr(mc, "_http_get_json", _catalog([
        {"id": "big-model", "context_length": 1_000_000},
        {"id": "small-model", "context_length": 16_384},
    ]))
    primary = await ab.resolve_stage_budget(
        "direct.primary", base_url=NANO_BASE, model="big-model",
        policy_raw=-1)
    fallback = await ab.resolve_stage_budget(
        "direct.fallback", base_url=NANO_BASE, model="small-model",
        policy_raw=-1)
    assert primary.context_window == 1_000_000
    assert fallback.context_window == 16_384
    # Fallback получает СВОЙ бюджет — используется при фактическом переходе.
    assert primary.effective_input_budget > fallback.effective_input_budget
    assert primary.effective_input_budget > 500_000
    # Preemptive-min отсутствует: окно primary — не окно fallback.
    effective, source = mc.resolve_effective_window("big-model", "small-model")
    assert effective == 1_000_000
    # Синхронный путь БЕЗ сети не знает каталога — честно возвращает
    # планировочную оценку (для recompose используется async-бюджет выше).
    assert mc.fallback_window_for_model("small-model") == (
        1_000_000, mc.SOURCE_ESTIMATED_UNKNOWN)


# ── D5: окно ≠ бюджет ≠ max_output; budgets OFF использует всё окно ────────

@pytest.mark.asyncio
async def test_budgets_off_uses_full_window_minus_reserves(monkeypatch):
    monkeypatch.setattr(mc, "_http_get_json", _catalog([
        {"id": "known-200k", "context_length": 200_000,
         "max_output_tokens": 8_192},
    ]))
    result = await mc.resolve_capacity(NANO_BASE, "known-200k")
    assert result.effective_context_window == 200_000
    assert result.max_output_tokens == 8_192
    stage = await ab.resolve_stage_budget(
        "direct.primary", base_url=NANO_BASE, model="known-200k",
        policy_raw=-1, max_output_tokens=1_500)
    # Unlimited (budgets OFF): effective = физический вход, не 16000.
    assert stage.effective_input_budget == stage.auto_input_budget
    assert stage.effective_input_budget > 170_000
    # Окно и резерв ответа — разные величины.
    assert stage.context_window == 200_000
    assert stage.output_reserve == max(1_024, 1_500)


# ── D6: context length exceeded → parse + capacity update + recovery ──────

class _ProviderError(Exception):
    """Имитация LLMError с телом структурированной ошибки провайдера."""

    def __init__(self, message, *, body):  # noqa: D401 - тест-двойник
        super().__init__(message)
        self.status = 400
        self.body = body


def _overflow_error(body):
    return _ProviderError("LLM HTTP 400: /chat/completions", body=body)


@pytest.mark.asyncio
async def test_context_overflow_structured_json_updates_capacity(monkeypatch):
    monkeypatch.setattr(mc, "_http_get_json", _catalog([
        {"id": GLM_MODEL, "context_length": 1_048_576},
    ]))
    first = await mc.resolve_capacity(NANO_BASE, GLM_MODEL)
    assert first.effective_context_window == 1_048_576      # каталог врал
    exc = _overflow_error(
        '{"error": {"code": "context_length_exceeded", '
        '"message": "This model\'s maximum context length is 131072 tokens. '
        'However, your messages resulted in 145000 tokens.", '
        '"model": "z-ai/glm-5.3-flash-uncensored"}}')
    info, plan = mc.note_context_overflow(exc, base_url=NANO_BASE,
                                          model=GLM_MODEL,
                                          output_reserve_tokens=4_096)
    assert info is not None
    assert info.limit_tokens == 131_072
    assert info.requested_tokens == 145_000
    assert info.code == "context_length_exceeded"
    assert plan is not None
    assert plan.uncertain is False
    assert plan.preserve_tool_evidence is True
    assert plan.max_attempts == 1 and plan.attempt == 1
    # Payload пересобирается в пределах доказанного предела.
    assert plan.budget_tokens <= 131_072 - 4_096
    # Ёмкость endpoint/model обновлена: каталог больше не «верифицирован».
    second = await mc.resolve_capacity(NANO_BASE, GLM_MODEL)
    assert second.source == mc.SOURCE_PROVEN_LIMIT
    assert second.effective_context_window == 131_072
    assert second.max_output_tokens is None or isinstance(
        second.max_output_tokens, int)


@pytest.mark.asyncio
async def test_context_overflow_text_only_is_parsed(monkeypatch):
    exc = _ProviderError(
        "maximum context length is 32768 tokens. "
        "Your messages resulted in 40000 tokens.",
        body="")
    info, plan = mc.note_context_overflow(
        exc, base_url="https://api.example-llm.com/v1", model="custom-32k")
    assert info is not None and info.limit_tokens == 32_768
    assert plan is not None and plan.budget_tokens <= 32_768
    assert mc.proven_limit_for("https://api.example-llm.com/v1",
                               "custom-32k") == 32_768


def test_context_overflow_without_limit_is_uncertain_not_16384():
    exc = _ProviderError(
        '{"error": {"code": "context_length_exceeded", '
        '"message": "prompt is too long"}}', body="")
    info, plan = mc.note_context_overflow(
        exc, base_url="https://api.example-llm.com/v1", model="mystery")
    assert info is not None and info.limit_tokens is None
    assert plan is not None and plan.uncertain is True
    assert plan.budget_tokens == 0
    assert mc.proven_limit_for("https://api.example-llm.com/v1",
                               "mystery") is None


def test_non_context_error_is_ignored():
    exc = _ProviderError('{"error": {"code": "invalid_request", '
                         '"message": "bad temperature"}}', body="")
    info, plan = mc.note_context_overflow(
        exc, base_url=NANO_BASE, model="m")
    assert (info, plan) == (None, None)
    assert mc.proven_limit_for(NANO_BASE, "m") is None


def test_context_overflow_recovery_is_bounded():
    exc = _overflow_error(
        '{"error": {"code": "context_length_exceeded", '
        '"message": "maximum context length is 65536 tokens"}}')
    mc.clear_proven_limits()
    info, plan = mc.note_context_overflow(
        exc, base_url=NANO_BASE, model=GLM_MODEL, attempt=0)
    assert info is not None and plan is not None
    mc.clear_proven_limits()
    # Вторая попытка recovery запрещена: платного цикла нет.
    info2, plan2 = mc.note_context_overflow(
        exc, base_url=NANO_BASE, model=GLM_MODEL, attempt=1)
    assert info2 is not None
    assert plan2 is None


def test_recovery_budget_separates_window_and_output():
    budget = mc.recovery_budget_tokens(
        131_072, output_reserve_tokens=8_192, protocol_reserve_tokens=1_024)
    assert 0 < budget < 131_072
    assert budget == max(1, int((131_072 - 8_192 - 1_024) / 1.15))


def test_llm_client_context_overflow_error_carries_recovery(monkeypatch):
    """D6: единый LLM-слой превращает 400 context-overflow в типизированную
    ошибку с разобранной причиной и планом (без сети и без логирования тел)."""
    from services.llm_client import (LLMContextOverflowError, LLMError,
                                     _context_overflow_exc)
    monkeypatch.setattr(mc, "_http_get_json", _catalog([]))
    err = LLMError("LLM HTTP 400: https://nano-gpt.com/api/v1/chat/completions")
    err.status = 400
    err.model = GLM_MODEL
    err.body = ('{"error": {"code": "context_length_exceeded", '
                '"message": "maximum context length is 131072 tokens. '
                'However, your messages resulted in 160000 tokens."}}')
    overflow = _context_overflow_exc(
        err, status=400, payload={"model": GLM_MODEL, "max_tokens": 4_096},
        base_url=NANO_BASE)
    assert isinstance(overflow, LLMContextOverflowError)
    assert isinstance(overflow, LLMError)
    assert overflow.context_info.limit_tokens == 131_072
    assert overflow.context_recovery is not None
    assert overflow.context_recovery.budget_tokens <= 131_072
    assert mc.proven_limit_for(NANO_BASE, GLM_MODEL) == 131_072
    # Не-контекстная ошибка остаётся обычным LLMError.
    plain = LLMError("LLM HTTP 400: url")
    plain.body = '{"error": {"code": "invalid_request"}}'
    assert _context_overflow_error_is_none(plain) is True


def _context_overflow_error_is_none(err) -> bool:
    from services.llm_client import _context_overflow_exc
    return _context_overflow_exc(
        err, status=400, payload={"model": "m"},
        base_url=NANO_BASE) is None


def test_capacity_budget_keys_untouched():
    """Scope-контракт S4: budget-resolution ключи не менялись этой стадией."""
    assert settings.CHAT_CONTEXT_BUDGET_TOKENS == 16_000
    assert settings.CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS > 0
    assert settings.CHAT_BUDGET_RESERVE_RATIO > 0
    # Единственный новый дефолт стадии D — окно неизвестной модели.
    assert settings.CHAT_UNKNOWN_MODEL_WINDOW == 1_000_000
