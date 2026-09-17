"""F2 fix-round 10.21 (Issue 3) — grounding на tool-loop пути фактчекера.

Регресс: валидатор `strip_phantom_tags` собирал допустимые якоря только из
user-контента (RAG + claim + search) и жёстко вырезал `fact:ID`/даты, реально
добытые инструментами (`dig_into_lore`), — валидная ссылка исчезала из
вердикта. Фикс: якоря добавляются из выводов инструментов
(`ToolLoopResult.tool_context`).

Покрытие:
  * id/дата ИЗ tool-вывода ⇒ тег сохранён;
  * фантомный id (нет ни в контексте, ни в tool-выводе) ⇒ вырезан.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.factcheck_service import FactCheckService
from services.llm_client import LLMChatResult, LLMToolCall


class _FakeLLM:
    def __init__(self, results):
        self._results = list(results)
        self.calls: list[dict] = []

    async def generate_chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self._results.pop(0)

    async def generate(self, messages, **kwargs):
        return "plain"


class _ToolRouter:
    """Роутер-«Летописец»: вывод содержит канон-тег с датой и fact:ID."""

    def __init__(self, output: str):
        self.output = output

    async def dispatch(self, name, arguments, ctx):
        return self.output


def _service(router, *, results):
    aggregator = MagicMock()
    aggregator.search = AsyncMock(return_value="хиты поиска")
    llm = _FakeLLM(results)
    svc = FactCheckService(aggregator, llm, memory=None, tool_router=router)
    return svc, llm


def _tool_round(tool_output):
    call = LLMToolCall(id="c1", name="dig_into_lore",
                       arguments='{"query": "кто сказал"}')
    return [LLMChatResult(content=None, tool_calls=[call],
                          finish_reason="tool_calls"),
            LLMChatResult(content=tool_output[1], tool_calls=None,
                          finish_reason="stop")]


class TestToolOutputAnchors:
    @pytest.mark.asyncio
    async def test_id_from_tool_output_kept(self):
        tag = "[01.01.2024 | Ваня | fact:777]"
        verdict = f"по данным {tag} это правда"
        router = _ToolRouter(f"нашёл: {tag} Ваня подтвердил")
        svc, _llm = _service(router, results=_tool_round((None, verdict)))
        result = await svc.check_claim("проверь факт", chat_id=-100)
        assert "fact:777" in result

    @pytest.mark.asyncio
    async def test_phantom_id_still_stripped(self):
        # В tool-выводе id=555, а модель выдумала id=999.
        router = _ToolRouter("[01.01.2024 | Ваня | fact:555] подтверждение")
        verdict = "ссылка [01.01.2024 | Ваня | fact:999] не существует"
        svc, _llm = _service(router, results=_tool_round((None, verdict)))
        result = await svc.check_claim("проверь факт", chat_id=-100)
        assert "fact:999" not in result

    @pytest.mark.asyncio
    async def test_no_tool_context_keeps_old_behavior(self):
        # Без tool-вызова (роутер не дёргается) валидных tool-якорей нет:
        # тег, которого нет в user-контексте, вырезается как раньше.
        router = _ToolRouter("не используется")
        svc, _llm = _service(router, results=[
            LLMChatResult(content="ссылка [01.01.2024 | Ваня | fact:777]",
                          tool_calls=None, finish_reason="stop")])
        result = await svc.check_claim("проверь факт", chat_id=-100)
        assert "fact:777" not in result
