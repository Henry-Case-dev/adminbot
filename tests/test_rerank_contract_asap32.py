"""ASAP-3.2 (round1029, ADR-1028-5 D3, T-4193) — typed reranker contract
(§10–§12/§71):

* robust-парсер: legacy numeric `1,3,5` / JSON `{"selected":[1,3,5]}` /
  markdown-wrapped JSON (детерминированный repair) / empty valid
  (`{"selected":[]}`, legacy `0`) / prose invalid / out-of-range IDs →
  корректная классификация + bounded fail-soft;
* номера = ПОЗИЦИИ списка (формат F3), range-acceptance 1..N;
* второй LLM-вызов ради formatting НЕ делается (парсер локальный);
* observability §12: candidate_count/selected_count/parser status/provider/
  model/latency/response_format/fallback + метрика `rerank_invalid_rate`;
  сырые приватные факты НЕ логируются (Q9);
* FTS-резерв (§62) не затрагивается (KNN failure → FTS — существующая
  механика, покрыта graphrag-тестами).
"""
import time

import pytest

from services import summary_memory as sm
from services import mca_retrieval_context as rc


# Прод-форма фактов rerank — 3-/6-кортежи (origin, fact, rag_ts, ...) из
# `_search_graph_facts` (без with_meta); позиции 1..N = порядок кортежей.
FACTS = [("chat_history", f"факт-{i}", 1700000000 + i)
         for i in range(1, 6)]


def _memory() -> sm.MemoryManager:
    return sm.MemoryManager(None, None)


# ═══ robust-парсер (§10–§11) ════════════════════════════════════════════════

def test_parse_legacy_numeric():
    kind, nums, mode = sm.parse_rerank_selected("1,3,5")
    assert (kind, nums, mode) == ("ok", (1, 3, 5), "numeric")


def test_parse_json_selected():
    kind, nums, mode = sm.parse_rerank_selected('{"selected":[1,4,2]}')
    assert (kind, nums, mode) == ("ok", (1, 4, 2), "json")


def test_parse_markdown_fenced_json_repair():
    raw = "Вот результат:\n```json\n{\"selected\":[2,5]}\n```\nГотово."
    kind, nums, mode = sm.parse_rerank_selected(raw)
    assert (kind, nums, mode) == ("ok", (2, 5), "json_fenced")


def test_parse_json_substring_prefix_repair():
    raw = "Ответ модели: {\"selected\":[3]} — конец."
    kind, nums, mode = sm.parse_rerank_selected(raw)
    assert (kind, nums, mode) == ("ok", (3,), "json_substring")


def test_parse_empty_valid_forms():
    assert sm.parse_rerank_selected('{"selected":[]}') == ("empty", (), "json")
    # §10: пустой/blank ответ — валидный empty (НЕ invalid).
    assert sm.parse_rerank_selected("") == ("empty", (), "none")
    assert sm.parse_rerank_selected("   ") == ("empty", (), "none")
    assert sm.parse_rerank_selected("[]") == ("empty", (), "json")


def test_parse_zero_is_invalid_not_empty():
    """§10: «0» — непустой ответ с некорректным (вне диапазона) номером →
    invalid → bounded fallback (прод-наблюдение §10, якорь F4)."""
    assert sm.parse_rerank_selected("0") == ("ok", (0,), "numeric")
    assert sm.parse_rerank_selected('{"selected":[0]}') == ("ok", (0,), "json")


def test_parse_prose_invalid():
    kind, nums, mode = sm.parse_rerank_selected(
        "Думаю, релевантны первые факты про проект")
    assert (kind, nums, mode) == ("invalid", (), "prose")
    assert sm.parse_rerank_selected(None) == ("empty", (), "none")


def test_parse_dedup_preserves_order():
    _, nums, _ = sm.parse_rerank_selected("3, 1, 3, 5")
    assert nums == (3, 1, 5)


# ═══ §71: классификация + bounded fail-soft ═════════════════════════════════

def test_apply_ok_positions_in_range():
    mm = _memory()
    kept = mm._typed_rerank_apply(FACTS, "1,3,5")
    assert [f[1] for f in kept] == ["факт-1", "факт-3", "факт-5"]
    snap = sm.rerank_metrics_snapshot()
    assert snap["ok"] >= 1


def test_apply_json_ok():
    mm = _memory()
    kept = mm._typed_rerank_apply(FACTS, '{"selected":[2] }')
    assert [f[1] for f in kept] == ["факт-2"]


def test_apply_valid_empty_returns_empty_not_all():
    """A05/§10: валидный пустой выбор → ПУСТО (НЕ все кандидаты)."""
    mm = _memory()
    assert mm._typed_rerank_apply(FACTS, '{"selected":[]}') == []
    snap = sm.rerank_metrics_snapshot()
    assert snap["empty"] >= 1


def test_apply_prose_invalid_bounded_fallback():
    mm = _memory()
    kept = mm._typed_rerank_apply(FACTS, "никаких номеров тут нет")
    # bounded pre-rerank порядок, top-k=8 → все 5 (меньше порога).
    assert len(kept) == 5
    snap = sm.rerank_metrics_snapshot()
    assert snap["invalid"] >= 1
    rate = sm.rerank_invalid_rate()
    assert rate is not None and rate > 0


def test_apply_out_of_range_ids_invalid():
    """§71: вне диапазона → invalid → bounded fallback (не падает)."""
    mm = _memory()
    kept = mm._typed_rerank_apply(FACTS, "40, 41")
    assert len(kept) == rc.fallback_top_k(len(FACTS))
    snap = sm.rerank_metrics_snapshot()
    assert snap["invalid"] >= 1


def test_apply_zero_only_is_invalid_fallback():
    """§10: «0» → invalid → bounded fallback (НЕ пусто)."""
    mm = _memory()
    kept = mm._typed_rerank_apply(FACTS, "0")
    assert len(kept) == rc.fallback_top_k(len(FACTS))
    snap = sm.rerank_metrics_snapshot()
    assert snap["invalid"] >= 1


@pytest.mark.asyncio
async def test_llm_timeout_event_path():
    mm = _memory()

    class Boom:
        async def generate(self, messages, *a, **kw):
            raise TimeoutError("llm timeout")

    mm.llm = Boom()
    kept = await mm.rerank_rag_facts("запрос", FACTS)
    assert len(kept) == rc.fallback_top_k(len(FACTS))
    snap = sm.rerank_metrics_snapshot()
    assert snap["timeout"] >= 1


# ═══ §12: observability — без приватного контента ═══════════════════════════

@pytest.mark.asyncio
async def test_observability_fields_no_private_content(caplog, monkeypatch):
    """События/лог reranker: counts/latency/mode — БЕЗ текстов фактов (Q9)."""
    mm = _memory()

    class FakeLLM:
        _chat_model = "deepseek/deepseek-v4.1-flash"
        _base_url = "https://nano-gpt.com/api/v1"

        async def generate(self, messages, *a, **kw):
            return '{"selected":[1,2]}'

    mm.llm = FakeLLM()
    with caplog.at_level("INFO", logger="services.summary_memory"):
        kept = await mm.rerank_rag_facts("запрос", FACTS)
    assert len(kept) == 2
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert "факт-1" not in blob and "chat_history" not in blob
    assert "candidate_count" in blob or "rerank(typed) OK" in blob
    snap = sm.rerank_metrics_snapshot()
    assert snap["ok"] >= 1


# ═══ MCA-07-фикс: позиции, а не row-id (регресс прод-формы фактов) ══════════

@pytest.mark.asyncio
async def test_apply_ok_with_production_row_id_dicts():
    """Продовые факты — dict С полем `id` (with_meta=True-путь): валидный
    ответ LLM обязан выбрать ПОЗИЦИИ, не терять кандидаты (ранее kept
    обнулялся из-за маппинга по row-id)."""
    prod_facts = [{"id": 9001 + i, "fact": f"прод-факт-{i}",
                   "origin": "chat_history"} for i in range(4)]
    mm = _memory()
    kept = mm._typed_rerank_apply(prod_facts, '{"selected":[1,3]}')
    assert [f["fact"] for f in kept] == ["прод-факт-0", "прод-факт-2"]
