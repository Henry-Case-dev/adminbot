# -*- coding: utf-8 -*-
"""P0C-INT R3: реранк RAG — сбой и осознанная отбраковка различаются.

TEST-LIFECYCLE: CONTRACT
owner=P0-SPEECH/hotfix
why=`probes_final5-rerun.md` §8: RAG-блок пустел в 4/5 прогонов при непустых
    фактах (`service_empty`). Единственный шаг, способный обнулить набор, —
    LLM-реранк. При этом пустой ОТВЕТ провайдера (`""`) трактовался как
    «валидный пустой выбор» и молча обнулял RAG, то есть сбой выдавался за
    решение модели. Здесь зафиксировано: явный `{"selected":[]}` остаётся
    законной отбраковкой (A05), а пустой/битый ответ — bounded fallback с
    `fallback=true` и наблюдаемым статусом.
replace_when=если контракт A05 или формат ответа реранка изменится.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import mca_retrieval_context as rc  # noqa: E402
from services import summary_memory as sm  # noqa: E402
from services.summary_memory import MemoryManager  # noqa: E402

FACTS = [("chat_history", "про дроны вчера", 100),
         ("search_fact", "про дроны в поиске", 200),
         ("web_content", "про погоду завтра", 300)]


class _LLM:
    _chat_model = "probe-model"
    _base_url = "https://provider.example/v1"

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    async def generate(self, messages, *a, **kw):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


def _memory(llm) -> MemoryManager:
    return MemoryManager(None, llm)


def _last() -> dict:
    return dict(sm._RERANK_LAST)


@pytest.mark.asyncio
async def test_explicit_empty_selection_is_a_valid_rejection():
    """A05: модель СКАЗАЛА «ничего не подходит» → пусто и это не fallback."""
    memory = _memory(_LLM('{"selected": []}'))
    kept = await memory.rerank_rag_facts("запрос", list(FACTS))
    assert kept == []
    last = _last()
    assert last["status"] == "empty"
    assert last["fallback"] is False
    assert last["candidate_count"] == 3 and last["selected_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   ", "\n"])
async def test_blank_provider_response_falls_back_not_silent_empty(blank):
    """Пустой ОТВЕТ провайдера — сбой: bounded fallback + fallback=true.

    Раньше такой ответ давал пустой RAG-блок и выглядел как осознанный выбор.
    """
    memory = _memory(_LLM(blank))
    kept = await memory.rerank_rag_facts("запрос", list(FACTS))
    assert kept == list(FACTS), "пустой ответ не должен обнулять RAG"
    last = _last()
    assert last["status"] == "empty_response"
    assert last["fallback"] is True
    assert last["candidate_count"] == 3 and last["selected_count"] == 3


@pytest.mark.asyncio
async def test_prose_without_numbers_is_invalid_fallback():
    memory = _memory(_LLM("никаких номеров тут нет"))
    kept = await memory.rerank_rag_facts("запрос", list(FACTS))
    assert kept == list(FACTS)
    last = _last()
    assert last["status"] == "invalid" and last["fallback"] is True


@pytest.mark.asyncio
async def test_valid_selection_keeps_evaluation_order():
    memory = _memory(_LLM('{"selected": [3, 1]}'))
    kept = await memory.rerank_rag_facts("запрос", list(FACTS))
    assert [f[1] for f in kept] == ["про погоду завтра", "про дроны вчера"]
    last = _last()
    assert last["status"] == "ok" and last["fallback"] is False
    assert last["selected_count"] == 2


@pytest.mark.asyncio
async def test_provider_error_is_reported_and_falls_back():
    memory = _memory(_LLM(error=RuntimeError("provider down")))
    kept = await memory.rerank_rag_facts("запрос", list(FACTS))
    assert kept == list(FACTS)
    last = _last()
    assert last["fallback"] is True
    assert last["status"] in ("error", "timeout", "invalid")


def test_parse_distinguishes_blank_from_explicit_empty():
    """Единая точка правды парсера: blank ≠ «выбрано ничего»."""
    kind, nums, mode = sm.parse_rerank_selected("")
    assert (kind, nums, mode) == ("empty_response", (), "none")
    kind, nums, mode = sm.parse_rerank_selected('{"selected": []}')
    assert (kind, nums) == ("empty", ())
    kind, nums, _ = sm.parse_rerank_selected("[]")
    assert (kind, nums) == ("empty", ())


def test_fallback_is_bounded_by_top_k():
    """Fallback остаётся bounded (D3), а не «отдать всё»."""
    limit = rc.fallback_top_k(50)
    assert limit < 50
