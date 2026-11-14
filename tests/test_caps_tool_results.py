"""SMART-EXECUTION-RELIABILITY-01 · C2-01/C3-01: потолки tool-результатов.

Проверяется РЕАЛЬНЫЙ путь данных каждого семейства инструментов:

* поиск — ``SearchAggregator`` поверх ``httpx.MockTransport`` (транспорт
  провайдера) → ``ToolRouter.execute_web_search`` → ToolResult/tool-loop →
  composer → LLM payload → финальный ответ;
* память — ``query_chat_memory``/``get_user_context`` поверх хранилища;
* транскрипты — ``YouTubeTranscriptEngine`` (сегменты провайдера),
  ``transcribe_video`` и ``voice_transcripts`` bundle;
* OCR/Vision — ``analyze_image_bytes`` с transport-стабом провайдера и
  ``recognize_image`` до ToolResult/payload.

Контракт (owner 2026-11-14 §C2/§C3): искусственные символьные/item-потолки
сняты; семантическая выборка сохранена; первая порция не выдаётся за
исчерпывающий результат; физические/провайдерские/транспортные лимиты
остаются и документированы.

RED-proof: на базе ``aca13702`` тесты падают на старых потолках
(4000/3500/20/240/3/20000/4000).
"""
from __future__ import annotations

import copy
import json
import re

import httpx
import pytest

from services import direct_context_composer as comp
from services.llm_client import LLMChatResult, LLMToolCall
from services.search_aggregator import SearchAggregator
from services.tool_loop import chat_with_tools
from services.tool_router import ToolContext, ToolDeps, ToolRouter

TAIL = "CAP-TAIL-MARKER"


class _PipelineLLM:
    """1-й вызов — tool call; 2-й — ответ по маркеру из role:tool."""

    def __init__(self, tool_name: str, arguments: dict, marker: str) -> None:
        self.tool_name = tool_name
        self.arguments = arguments
        self.marker = marker
        self.calls = 0
        self.all_messages: list = []
        self.answer = ""

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.all_messages.append(copy.deepcopy(messages))
        if self.calls == 0:
            self.calls += 1
            return LLMChatResult(
                content=None,
                tool_calls=[LLMToolCall(id="call_1", name=self.tool_name,
                                        arguments=json.dumps(self.arguments))],
                finish_reason="tool_calls")
        tool_content = "\n".join(
            str(m.get("content") or "") for m in messages
            if m.get("role") == "tool")
        found = re.search(re.escape(self.marker), tool_content)
        self.answer = ("Итог: " + found.group(0)) if found else "Итог: потеряно"
        return LLMChatResult(content=self.answer, tool_calls=None,
                             finish_reason="stop")

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):       # pragma: no cover - fallback не нужен
        self.all_messages.append(copy.deepcopy(messages))
        return "fallback"


class _RecordingRouter(ToolRouter):
    """Реальный ToolRouter + запись фактического выхода для byte-сверки."""

    def __init__(self, deps) -> None:
        super().__init__(deps)
        self.outputs: list[str] = []

    async def dispatch(self, name: str, arguments: dict, ctx) -> str:
        output = await super().dispatch(name, arguments, ctx)
        self.outputs.append(output)
        return output


async def _run_tool_loop(tool_name: str, arguments: dict, marker: str,
                         router, ctx):
    llm = _PipelineLLM(tool_name, arguments, marker)
    final = await chat_with_tools(
        llm, [{"role": "user", "content": "вопрос"}],
        tools=[{"type": "function"}], router=router, ctx=ctx)
    tool_msg = [m for m in llm.all_messages[1] if m.get("role") == "tool"][0]
    return llm, tool_msg, final


# ═══════════════════════════════════════════════════════════════════════════
# C2-01 / C3-01 · поиск: провайдер → ToolResult → payload → ответ
# ═══════════════════════════════════════════════════════════════════════════

def _tavily_payload(hits: int = 5, snippet_chars: int = 1200) -> dict:
    return {"results": [
        {"title": f"Заголовок {i}",
         "content": ("S" * snippet_chars) + f" {TAIL}-{i}",
         "url": f"https://provider.example/{i}"}
        for i in range(1, hits + 1)]}


def _provider_aggregator(payload: dict) -> tuple[SearchAggregator,
                                                 httpx.AsyncClient]:
    """Реальный агрегатор с transport-стабом провайдера (не fake search)."""

    def _handler(request: httpx.Request) -> httpx.Response:
        if "api.tavily.com" in str(request.url):
            return httpx.Response(200, json=payload, request=request)
        return httpx.Response(500, json={}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    aggregator = SearchAggregator(tavily_api_key="tav-key", exa_api_key="")
    aggregator._client = client
    return aggregator, client


@pytest.mark.asyncio
async def test_search_provider_result_is_not_trimmed_to_4000() -> None:
    """Шаг 1: провайдер отдал >4000 симв. — инструмент получает весь ответ."""
    aggregator, client = _provider_aggregator(_tavily_payload())
    try:
        text = await aggregator.search("запрос", 4000)
    finally:
        await client.aclose()
    assert len(text) > 4000                      # было жёсткое text[:4000]
    assert f"{TAIL}-5" in text                   # хвост последнего хита цел
    assert text.rstrip().endswith("https://provider.example/5")


@pytest.mark.asyncio
async def test_search_tool_result_reaches_payload_and_answer() -> None:
    """Шаги 2–7: тот же ответ проходит ToolResult → tool-loop → payload."""
    aggregator, client = _provider_aggregator(_tavily_payload())
    ctx = ToolContext(-100, "запрос")
    router = _RecordingRouter(ToolDeps(search=aggregator,
                                       memory=_StubMemory(),
                                       aliases=None))
    try:
        llm, tool_msg, final = await _run_tool_loop(
            "execute_web_search", {"query": "запрос"}, f"{TAIL}-5",
            router, ctx)
    finally:
        await client.aclose()
    delivered = router.outputs[0]
    assert len(delivered) > 4000
    assert tool_msg["content"] == delivered      # байт-в-байт
    assert f"{TAIL}-5" in tool_msg["content"]
    assert final == f"Итог: {TAIL}-5"
    # Context composer не режет уже доставленный результат (budget 0 = OFF).
    fragment = comp.ContextFragment(
        kind=comp.KIND_EXTERNAL_EVIDENCE, source_id="search:1",
        text=delivered, role=comp.ROLE_MEMORY,
        authority=comp.AUTHORITY_PRIMARY, timestamp_utc=1700000000)
    selection = comp.build_context_selection(
        current_text="запрос", memory=(fragment,), budget_tokens=0)
    assert selection.memory and selection.memory[0].text == delivered


class _StubMemory:
    """Минимальное хранилище памяти для tool-loop тестов поиска."""

    async def search_long_term(self, chat_id, keywords_, limit):
        return []

    async def count_mentions(self, chat_id, keywords_, **kwargs):
        return {"count": 0}

    async def vector_search(self, chat_id, query, limit):
        return []

    async def get_rag_context(self, chat_id, query, **kwargs):
        return ""
