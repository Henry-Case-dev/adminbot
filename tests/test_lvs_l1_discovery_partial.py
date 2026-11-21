# -*- coding: utf-8 -*-
"""LVS-L1-07/08/10: discovery неизвестной модели и частичных карточек.

Контракт (plans/features/llm-vision-scheduler-p0/requirements-map.json,
additional_requirements LVS-L1-07/08/10):

* unknown/new ID получает документированный результат с provenance, а НЕ
  микролимит 512/15 s и НЕ 1M как физический предел;
* частичная карточка каталога (нет окна, но есть output/capabilities; есть
  окно, нет output; карточка без machine-readable полей) не теряет реально
  доступную информацию и не деградирует до чужих дефолтов;
* 1M остаётся `estimated_unknown` с явной пометкой; proven-лимит меньше 1M
  становится effective; публично известный контекст каталога не подменяется
  планировочной оценкой;
* модель без карточки проходит discovery/compatibility path: route usable,
  источник и уверенность видны, модель не отключается и не подменяется.

TEST-LIFECYCLE: CONTRACT owner=LVS-L1-DISCOVERY (LVS-L1-07/08/10)
"""
from __future__ import annotations

import pytest

import services.model_capacity as mc
from services import direct_l1 as l1

NANO = "https://nano-gpt.com/api/v1"
OPENROUTER = "https://openrouter.ai/api/v1"


pytestmark = [pytest.mark.system2, pytest.mark.asap3, pytest.mark.asap31]


def _catalog(payload):
    async def _get(url, *, headers=None):
        return payload
    return _get


@pytest.fixture(autouse=True)
def _no_network_and_clean_state(monkeypatch):
    async def _none(url, *, headers=None):
        return None
    monkeypatch.setattr(mc, "_http_get_json", _none)
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    mc.clear_proven_limits()
    from services import hot_config as hot
    previous = hot.get_config_cache()
    hot.set_config_cache(None)
    try:
        yield
    finally:
        hot.set_config_cache(previous)
        mc.invalidate_capacity_cache()
        mc._WINDOW_CACHE.clear()
        mc._WARNED_UNKNOWN.clear()
        mc.clear_proven_limits()


async def _route(model: str, base_url: str = NANO) -> l1.L1RouteSnapshot:
    slot = l1.L1ModelSlot(base_url=base_url, model=model,
                          api_key="test-key", dedicated=True)
    return await l1.resolve_l1_route(slot)


@pytest.mark.asyncio
async def test_unknown_id_without_card_is_documented_estimate(monkeypatch):
    """LVS-L1-07/08/10: без карточки — 1M estimated, route usable, не 512/15 s."""
    monkeypatch.setattr(mc, "_http_get_json", _catalog({"data": []}))
    cap = await mc.resolve_model_capability(NANO, "vendor/brand-new-model")
    assert cap.context_window == 1_000_000
    assert cap.source == mc.SOURCE_ESTIMATED_UNKNOWN
    assert cap.confidence == mc.CONFIDENCE_ESTIMATED
    assert cap.window_verified is False
    assert cap.estimated is True
    assert cap.max_output is None              # 1M контекста ≠ 1M вывода

    route = await _route("vendor/brand-new-model")
    assert route.usable is True
    assert route.model == "vendor/brand-new-model"   # не подменяется
    assert route.context_source == mc.SOURCE_ESTIMATED_UNKNOWN
    assert route.window_confidence == mc.CONFIDENCE_ESTIMATED
    assert route.window_estimated is True
    assert route.max_output_tokens > 1024       # не микролимит 512
    assert route.max_output_tokens < 1_000_000  # не выдача 1M за физический output
    assert route.timeout_seconds != 15.0
    assert route.timeout_seconds >= 60.0


@pytest.mark.asyncio
async def test_partial_card_without_window_keeps_output_and_capabilities(
        monkeypatch):
    """LVS-L1-07: карточка с max_output/capabilities, но без context_length
    отдаёт реальные данные каталога; окно остаётся planning-оценкой."""
    payload = {"data": [{
        "id": "vendor/partial-output",
        "max_output_tokens": 4096,
        "capabilities": {"reasoning": True, "tools": True, "json_mode": True},
        "output_field": "max_completion_tokens",
    }]}
    monkeypatch.setattr(mc, "_http_get_json", _catalog(payload))
    cap = await mc.resolve_model_capability(NANO, "vendor/partial-output")
    assert cap.context_window == 1_000_000
    assert cap.source == mc.SOURCE_ESTIMATED_UNKNOWN   # окно — оценка
    assert cap.confidence == mc.CONFIDENCE_ESTIMATED
    assert cap.window_verified is False
    assert cap.max_output == 4096                      # output не потерян
    assert cap.max_output_source == mc.OUTPUT_FIELD_SOURCE_PROVIDER
    assert cap.supports_reasoning is True
    assert cap.supports_tool_calling is True
    assert cap.supports_json_mode is True
    assert cap.output_token_field == mc.OUTPUT_FIELD_MAX_COMPLETION_TOKENS
    assert cap.output_field_source == mc.OUTPUT_FIELD_SOURCE_PROVIDER

    route = await _route("vendor/partial-output")
    assert route.max_output_tokens == 4096
    assert route.output_source.endswith("+max_output")
    assert route.output_field == mc.OUTPUT_FIELD_MAX_COMPLETION_TOKENS
    assert route.window_estimated is True
    assert route.usable is True


@pytest.mark.asyncio
async def test_partial_card_with_only_window_keeps_verified_window(monkeypatch):
    """LVS-L1-07: карточка с context_length, но без max_output — окно
    подтверждено, output не выдумывается и не становится микролимитом."""
    payload = {"data": [{
        "id": "vendor/partial-window",
        "context_length": 131072,
        "capabilities": ["reasoning"],
    }]}
    monkeypatch.setattr(mc, "_http_get_json", _catalog(payload))
    cap = await mc.resolve_model_capability(NANO, "vendor/partial-window")
    assert cap.context_window == 131072
    assert cap.source == mc.SOURCE_PROVIDER_CATALOG
    assert cap.confidence == mc.CONFIDENCE_VERIFIED
    assert cap.window_verified is True
    assert cap.max_output is None
    assert cap.supports_reasoning is True

    route = await _route("vendor/partial-window")
    assert route.context_window == 131072
    assert route.context_source == mc.SOURCE_PROVIDER_CATALOG
    assert route.max_output_tokens > 1024
    assert route.output_source == l1.OUTPUT_SOURCE_CAPABILITY


@pytest.mark.asyncio
async def test_partial_card_without_window_uses_exact_registry(monkeypatch):
    """LVS-L1-07: если точный реестр знает окно, частичная карточка не
    понижает его до 1M-оценки; output из карточки сохраняется."""
    payload = {"data": [{
        "id": "deepseek-chat",
        "max_output_tokens": 2048,
        "capabilities": ["tools"],
    }]}
    monkeypatch.setattr(mc, "_http_get_json", _catalog(payload))
    cap = await mc.resolve_model_capability(NANO, "deepseek-chat")
    assert cap.context_window == 131072
    assert cap.source == mc.SOURCE_REGISTRY
    assert cap.confidence == mc.CONFIDENCE_VERIFIED
    assert cap.window_verified is True
    assert cap.max_output == 2048
    assert cap.max_output_source == mc.OUTPUT_FIELD_SOURCE_PROVIDER
    assert cap.supports_tool_calling is True


@pytest.mark.asyncio
async def test_model_without_machine_card_passes_discovery(monkeypatch):
    """LVS-L1-10: карточка без машиночитаемых полей — не «модель устарела/
    отключена», а прозрачный discovery: source/confidence видны, route usable,
    модель не подменяется."""
    monkeypatch.setattr(mc, "_http_get_json", _catalog(
        {"data": [{"id": "vendor/no-card", "name": "No Card"}]}))
    cap = await mc.resolve_model_capability(NANO, "vendor/no-card")
    assert cap.source == mc.SOURCE_ESTIMATED_UNKNOWN
    assert cap.confidence == mc.CONFIDENCE_ESTIMATED
    assert cap.window_verified is False
    assert cap.estimated is True
    assert cap.max_output is None
    assert cap.supports_reasoning is None      # не «нет способностей»

    route = await _route("vendor/no-card")
    assert route.usable is True
    assert route.model == "vendor/no-card"
    assert route.context_source == mc.SOURCE_ESTIMATED_UNKNOWN
    assert route.window_estimated is True
    assert route.max_output_tokens > 1024


@pytest.mark.asyncio
async def test_proven_limit_below_estimate_wins_and_estimate_keeps_label(
        monkeypatch):
    """LVS-L1-08: 1M — оценка; proven-лимит 200k становится effective,
    подтверждённый источник/уверенность явно видны."""
    monkeypatch.setattr(mc, "_http_get_json", _catalog({"data": []}))
    before = await mc.resolve_model_capability(NANO, "vendor/proven-model")
    assert before.context_window == 1_000_000
    assert before.source == mc.SOURCE_ESTIMATED_UNKNOWN
    assert before.confidence == mc.CONFIDENCE_ESTIMATED
    assert before.window_verified is False
    assert before.as_event_fields()["window_estimated"] is True

    mc.record_proven_limit(NANO, "vendor/proven-model", 200_000,
                           reason="context_length_exceeded")
    after = await mc.resolve_model_capability(NANO, "vendor/proven-model")
    assert after.context_window == 200_000          # verified < 1M — effective
    assert after.source == mc.SOURCE_PROVEN_LIMIT
    assert after.confidence == mc.CONFIDENCE_VERIFIED
    assert after.window_verified is True
    assert after.proven_limit == 200_000
    assert after.context_window != 1_000_000

    route = await _route("vendor/proven-model")
    assert route.context_window == 200_000
    assert route.context_source == mc.SOURCE_PROVEN_LIMIT
    assert route.window_estimated is False


@pytest.mark.asyncio
async def test_public_catalog_context_is_not_replaced_by_estimate(monkeypatch):
    """LVS-L1-08: публично известный контекст каталога сильнее planning-1M и
    не подменяется выдуманным гарантированным лимитом шлюза."""
    payload = {"data": [{
        "id": "vendor/public-model",
        "context_length": 200000,
        "top_provider": {"max_completion_tokens": 8192},
    }]}
    monkeypatch.setattr(mc, "_http_get_json", _catalog(payload))
    cap = await mc.resolve_model_capability(OPENROUTER, "vendor/public-model")
    assert cap.context_window == 200000              # не 1M
    assert cap.source == mc.SOURCE_PROVIDER_CATALOG
    assert cap.confidence == mc.CONFIDENCE_VERIFIED
    assert cap.window_verified is True
    assert cap.max_output == 8192

    route = await _route("vendor/public-model", base_url=OPENROUTER)
    assert route.context_window == 200000
    assert route.context_source == mc.SOURCE_PROVIDER_CATALOG
    assert route.window_estimated is False
    assert route.max_output_tokens == 4608  # plan contract, capped by 8192
