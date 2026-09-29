"""ASAP-3.1 (round 1028, ADR-1028-3) — регрессионные тесты инцидентов
Summary (T-4074, §101/§142–§145) + manual cap (§137) + Auto-семантика
гибридных бюджетов (T-4069, §75/§77/§78).

Ключевые доказательства фичи:
  * §142: 369 сообщений / 6h / большое окно → chunks=1, coverage=100%,
    НЕТ skipped=81, НЕТ limit=21001;
  * §143: маленькая локальная модель (16K) → все 369 обработаны, chunks>1,
    chronological, без semantic prefilter;
  * §144: смена L1 модели A(large)→B(small) → cache invalidated,
    autobudget пересчитан, авто multi-chunk, coverage 100%;
  * §145: окно 6h→12h → без ручных правок, chunks растут при необходимости,
    coverage 100%;
  * §137: manual cap ограничивает размер ОДНОГО chunk, не coverage.
"""
import json
from unittest.mock import MagicMock

import pytest

import services.model_capacity as mc
import services.summary_l1_clusterizer as sl1
from services.summary_budget_auto import (
    BUDGET_MODE_AUTO,
    BUDGET_MODE_LEGACY_STATIC,
    BUDGET_MODE_MANUAL_CAP,
    hybrid_manual_cap_tokens,
)
from services.summary_hybrid_budget import HYBRID_CONTEXT_TOKEN_DEFAULT

pytestmark = pytest.mark.asap31

CHAT_ID = -100555


@pytest.fixture(autouse=True)
def _clean():
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    sl1._LAST_RUN_COVERAGE = None
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    sl1._LAST_RUN_COVERAGE = None


def _slot(monkeypatch, base_url, model):
    """Контролируемый слот summary.l1 (env-слой Settings ClassVar)."""
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_BASE_URL", base_url,
                        raising=False)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_MODEL_NAME", model,
                        raising=False)


def _rows(count, *, start_id=1, text_size=40):
    return [
        {"id": start_id + i, "tg_message_id": start_id + i,
         "user_id": 10 + (i % 3), "author_name": f"Автор{i % 3}",
         "text": f"сообщение {i} о коммуналке и соседях " * (text_size // 10),
         "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
         "reply_to_id": None, "is_forward": 0, "forward_source": None}
        for i in range(count)
    ]


def _mock_llm_call(payload_items_by_call=None):
    """LLM-канал: валидный §95-v2 ответ по ids фактического user-контента."""
    calls = {"count": 0}

    async def _call(messages):
        calls["count"] += 1
        user_content = ""
        for message in messages:
            if message.get("role") == "user":
                user_content = message.get("content") or ""
        ids = []
        for line in user_content.splitlines():
            line = line.strip()
            if not line.startswith('{"'):
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            mid = item.get("message_id")
            if isinstance(mid, int):
                ids.append(mid)
        assert ids, "mock: user content без §92-элементов"
        threads = [{"thread_id": "T1", "topic": "коммуналка",
                    "message_ids": ids,
                    "facts": [{"text": "обсуждали коммуналку",
                               "evidence_message_ids": ids[:3]}]}]
        return json.dumps({"schema_version": 2, "threads": threads,
                           "unassigned_message_ids": []},
                          ensure_ascii=False)

    _call.calls = calls
    return _call


# ── §142/§101: 369 сообщений, большое окно → 1 chunk, coverage 100% ────────

@pytest.mark.asyncio
async def test_incident_369_big_window_single_pass(monkeypatch):
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek/deepseek-v4.1")
    rows = _rows(369)
    llm_call = _mock_llm_call()
    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID,
                              llm_call=llm_call)
    assert result.usable
    # НЕТ искусственного 21001-cap: auto-бюджет от окна 131072.
    assert llm_call.calls["count"] == 1
    assert result.chunk_count == 1
    assert result.skipped_ids == ()
    assert result.truncated is False
    coverage = sl1.last_run_coverage()
    assert coverage["source_messages_total"] == 369
    assert coverage["source_messages_processed"] == 369
    assert coverage["source_messages_unprocessed"] == 0
    assert coverage["coverage_percent"] == 100.0
    assert coverage["budget_mode"] == BUDGET_MODE_AUTO
    assert coverage["l1_chunks"] == 1
    # §127 (M-ASAP31-1 rework): окно прогона — реальные timestamps,
    # НЕ заглушки.
    assert coverage["source_window_start"] == 1_700_000_000
    assert coverage["source_window_end"] == 1_700_000_000 + 368 * 60


@pytest.mark.asyncio
async def test_payload_over_21k_not_truncated(monkeypatch):
    """§101: serialized >21K, но << capacity → БЕЗ truncation на 21001."""
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    # ~25K токенов суммарно (по ~70 токенов на сообщение, 369 шт ≈ 26K).
    rows = _rows(369, text_size=70)
    llm_call = _mock_llm_call()
    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID,
                              llm_call=llm_call)
    assert result.usable
    assert result.truncated is False
    assert result.skipped_ids == ()
    assert llm_call.calls["count"] == 1


# ── §143: маленькая локальная модель 16K → chunks>1, coverage 100% ─────────

@pytest.mark.asyncio
async def test_small_local_model_all_processed(monkeypatch):
    """Unknown-модель → fallback 16384 (§8) → авто multi-chunk; ВСЕ 369
    обработаны; chronological; без semantic prefilter."""
    _slot(monkeypatch, "http://127.0.0.1:8080/v1", "tiny-local-model")
    rows = _rows(369)
    llm_call = _mock_llm_call()
    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID,
                              llm_call=llm_call)
    assert result.usable
    assert llm_call.calls["count"] > 1, "должен быть auto multi-chunk"
    assert result.chunk_count == llm_call.calls["count"]
    assert result.truncated is False
    assert result.skipped_ids == ()
    coverage = sl1.last_run_coverage()
    assert coverage["source_messages_total"] == 369
    assert coverage["source_messages_processed"] == 369
    assert coverage["coverage_percent"] == 100.0
    assert coverage["l1_chunks"] == llm_call.calls["count"]
    # §127 (M-ASAP31-1 rework): overlap-дубликаты посчитаны реально
    # (по одному сообщению на каждую границу партиций).
    assert coverage["duplicate_overlap_messages"] == \
        llm_call.calls["count"] - 1
    assert coverage["source_window_start"] == 1_700_000_000
    assert coverage["source_window_end"] == 1_700_000_000 + 368 * 60


@pytest.mark.asyncio
async def test_chunked_chronological_order_and_coverage(monkeypatch):
    _slot(monkeypatch, "http://127.0.0.1:8080/v1", "tiny-local-model")
    rows = _rows(120)
    seen_orders = []

    async def _call(messages):
        user_content = next(m["content"] for m in messages
                            if m["role"] == "user")
        ids = []
        for line in user_content.splitlines():
            line = line.strip()
            if line.startswith('{"'):
                try:
                    ids.append(json.loads(line)["message_id"])
                except (ValueError, KeyError):
                    pass
        seen_orders.append(ids)
        threads = [{"thread_id": "T1", "topic": "т", "message_ids": ids,
                    "facts": [{"text": "ф", "evidence_message_ids": ids[:2]}]}]
        return json.dumps({"schema_version": 2, "threads": threads,
                           "unassigned_message_ids": []})

    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=_call)
    assert result.usable
    assert len(seen_orders) > 1
    for order in seen_orders:
        assert order == sorted(order), "chronological ASC внутри chunk"
    covered = [mid for order in seen_orders for mid in order]
    assert set(covered) == {r["tg_message_id"] for r in rows}, \
        "каждый source ID ≥1 primary chunk (§121)"


# ── §144: смена L1 модели A(large)→B(small) ────────────────────────────────

@pytest.mark.asyncio
async def test_model_switch_recalculates(monkeypatch):
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    rows = _rows(369)
    llm_call = _mock_llm_call()
    big = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=llm_call)
    assert big.usable and llm_call.calls["count"] == 1
    # Смена модели (новый слот → новый ключ кэша → пересчёт, §38).
    _slot(monkeypatch, "http://127.0.0.1:8080/v1", "tiny-local-model")
    small = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=llm_call)
    assert small.usable
    assert llm_call.calls["count"] > 1, "auto multi-chunk после смены модели"
    coverage = sl1.last_run_coverage()
    assert coverage["coverage_percent"] == 100.0
    assert coverage["source_messages_processed"] == 369


# ── §145: окно 6h→12h (workload вырос) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_window_growth_recalculated(monkeypatch):
    _slot(monkeypatch, "http://127.0.0.1:8080/v1", "tiny-local-model")
    rows_6h = _rows(369)
    llm_call = _mock_llm_call()
    first = await sl1.run_l1(rows=rows_6h, chat_id=CHAT_ID, llm_call=llm_call)
    chunks_6h = llm_call.calls["count"]
    assert first.usable
    rows_12h = _rows(738)
    second = await sl1.run_l1(rows=rows_12h, chat_id=CHAT_ID,
                              llm_call=llm_call)
    assert second.usable
    assert llm_call.calls["count"] > chunks_6h, \
        "chunk count растёт с workload без ручных настроек"
    coverage = sl1.last_run_coverage()
    assert coverage["source_messages_total"] == 738
    assert coverage["coverage_percent"] == 100.0


# ── §137: manual cap = размер одного chunk ─────────────────────────────────

@pytest.mark.asyncio
async def test_manual_cap_limits_chunk_not_coverage(monkeypatch):
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    # Кастом владельца (≠ дефолт 30000) → Developer manual cap (§78).
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_HYBRID_CONTEXT_TOKENS",
                        6000, raising=False)
    assert hybrid_manual_cap_tokens() == 6000
    rows = _rows(369)
    llm_call = _mock_llm_call()
    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=llm_call)
    assert result.usable
    assert llm_call.calls["count"] > 1, "cap ≤ окна → только размер chunk"
    coverage = sl1.last_run_coverage()
    assert coverage["budget_mode"] == BUDGET_MODE_MANUAL_CAP
    assert coverage["coverage_percent"] == 100.0
    assert coverage["source_messages_processed"] == 369


# ── §77/§78: Auto-семантика ключей ─────────────────────────────────────────

def test_untouched_default_is_auto(monkeypatch):
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_HYBRID_CONTEXT_TOKENS",
                        None, raising=False)
    assert hybrid_manual_cap_tokens() is None        # Auto


def test_default_value_is_auto(monkeypatch):
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_HYBRID_CONTEXT_TOKENS",
                        HYBRID_CONTEXT_TOKEN_DEFAULT, raising=False)
    assert hybrid_manual_cap_tokens() is None        # untouched → Auto (§78)


def test_custom_value_is_manual_cap(monkeypatch):
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_HYBRID_CONTEXT_TOKENS",
                        25000, raising=False)
    assert hybrid_manual_cap_tokens() == 25000


def test_legacy_max_summary_parts_not_used(monkeypatch):
    """§23: legacy MAX_SUMMARY_PARTS не участвует в Hybrid-бюджете."""
    monkeypatch.setattr(type(sl1.settings), "MAX_SUMMARY_PARTS", 1,
                        raising=False)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_HYBRID_CONTEXT_TOKENS",
                        None, raising=False)
    assert hybrid_manual_cap_tokens() is None


# ── §128: события chunked/degraded ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_chunked_event_emitted(monkeypatch, caplog):
    _slot(monkeypatch, "http://127.0.0.1:8080/v1", "tiny-local-model")
    rows = _rows(300)
    llm_call = _mock_llm_call()
    with caplog.at_level("INFO", logger="services.agentic_events"):
        result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID,
                                  llm_call=llm_call)
    assert result.usable
    assert any("event=SUMMARY_L1_CHUNKED" in r.getMessage()
               for r in caplog.records)


@pytest.mark.asyncio
async def test_off_chunking_keeps_legacy_truncation(monkeypatch):
    """Kill-switch `SUMMARY_COVERAGE_CHUNKING_ENABLED=false` → байт-в-байт
    прежний single-pass (truncated + skipped_ids + WARN)."""
    monkeypatch.setattr(type(sl1.settings),
                        "SUMMARY_COVERAGE_CHUNKING_ENABLED", False,
                        raising=False)
    _slot(monkeypatch, "http://127.0.0.1:8080/v1", "tiny-local-model")
    rows = _rows(300)
    llm_call = _mock_llm_call()
    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=llm_call)
    # Прежняя семантика: 1 вызов, eviction, truncated-статус.
    assert llm_call.calls["count"] == 1
    assert result.truncated is True
    assert len(result.skipped_ids) > 0


@pytest.mark.asyncio
async def test_off_auto_budget_keeps_legacy_static(monkeypatch):
    """AUTO_BUDGET_RESOLVER_ENABLED=false → static 30000-путь (байт-в-байт),
    369 сообщений → truncated-семантика прежнего инцидента (паритет)."""
    monkeypatch.setattr(type(sl1.settings), "AUTO_BUDGET_RESOLVER_ENABLED",
                        False, raising=False)
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    rows = _rows(369, text_size=70)          # ≈26K > static 21001
    llm_call = _mock_llm_call()
    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=llm_call)
    assert result.truncated is True
    assert len(result.skipped_ids) > 0
