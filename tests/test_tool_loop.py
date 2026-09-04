"""Эпик 04.09.2026 (3.3, T-17/AC-2.2/AC-2.3/AC-2.5) — цикл tool_calls.

Round-trip: модель вернула tool_calls → инструменты исполнены (по одному,
последовательно) → сообщения role:"tool" с корректными tool_call_id →
финальный текст; порядок сообщений валиден; лимит раундов; сбой инструмента
→ role:"tool" с «ОШИБКА …»; деградация без tools при LLMError на 1-м раунде.
"""
import copy
import json
from unittest.mock import MagicMock

import pytest

from services.llm_client import (
    LLMBadResponseError,
    LLMError,
    LLMChatResult,
    LLMToolCall,
)
from services.tool_loop import TOOL_MAX_ROUNDS, chat_with_tools


class FakeLLM:
    """generate_chat по заранее заданным ответам; generate — финальный фолбэк."""

    def __init__(self, answers, plain_text="обычный ответ"):
        self._answers = list(answers)
        self.plain_text = plain_text
        self.generated_plain = 0
        self.all_messages = []

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto"):
        self.all_messages.append(copy.deepcopy(messages))
        assert tools is not None, "generate_chat без tools — сломанный тест"
        if not self._answers:
            raise AssertionError("не хватило запланированных ответов")
        return self._answers.pop(0)

    async def generate(self, messages, temperature=None):
        self.generated_plain += 1
        self.all_messages.append(copy.deepcopy(messages))
        return self.plain_text


def _tool_result(call_id, name, query):
    return LLMChatResult(content=None,
                         tool_calls=[LLMToolCall(id=call_id, name=name,
                                                 arguments=json.dumps({"query": query}))],
                         finish_reason="tool_calls")


def _text(text):
    return LLMChatResult(content=text, tool_calls=None, finish_reason="stop")


class FakeRouter:
    def __init__(self, outputs):
        self._outputs = dict(outputs) if isinstance(outputs, dict) else outputs
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, arguments))
        if isinstance(self._outputs, dict):
            return self._outputs[name]
        return self._outputs.pop(0)


MESSAGES = [{"role": "user", "content": "вопрос"}]


class TestChatWithTools:
    @pytest.mark.asyncio
    async def test_roundtrip_tool_then_final_text(self):
        llm = FakeLLM([
            _tool_result("call_1", "execute_web_search", "новости"),
            _text("вот что нашлось: новости такие-то"),
        ])
        router = FakeRouter({"execute_web_search": "данные поиска"})
        out = await chat_with_tools(llm, MESSAGES, tools=[{"type": "function"}],
                                    router=router, ctx=MagicMock())
        assert out == "вот что нашлось: новости такие-то"
        # второй запрос: assistant с tool_calls + role:tool
        second = llm.all_messages[1]
        roles = [m["role"] for m in second]
        assert roles == ["user", "assistant", "tool"]
        assistant = second[1]
        assert assistant["tool_calls"][0]["id"] == "call_1"
        assert json.loads(
            assistant["tool_calls"][0]["function"]["arguments"]) == \
            {"query": "новости"}
        tool = second[2]
        assert tool["role"] == "tool"
        assert tool["tool_call_id"] == "call_1"
        assert tool["content"] == "данные поиска"

    @pytest.mark.asyncio
    async def test_two_tools_sequential_one_round(self):
        llm = FakeLLM([
            LLMChatResult(content=None, tool_calls=[
                LLMToolCall(id="c1", name="execute_web_search",
                            arguments='{"query": "a"}'),
                LLMToolCall(id="c2", name="query_chat_memory",
                            arguments='{"query": "b"}'),
            ], finish_reason="tool_calls"),
            _text("финал"),
        ])
        router = FakeRouter({"execute_web_search": "A", "query_chat_memory": "B"})
        await chat_with_tools(llm, MESSAGES, tools=[], router=router, ctx=MagicMock())
        assert router.calls == [("execute_web_search", {"query": "a"}),
                                ("query_chat_memory", {"query": "b"})]
        roles = [m["role"] for m in llm.all_messages[1]]
        assert roles == ["user", "assistant", "tool", "tool"]

    @pytest.mark.asyncio
    async def test_round_limit_reached_raises_bad_response(self):
        """AC-2.3: лимит раундов — не более TOOL_MAX_ROUNDS вызовов LLM."""
        answers = []
        for i in range(TOOL_MAX_ROUNDS):
            answers.append(_tool_result(f"call_{i}", "execute_web_search", f"q{i}"))
        llm = FakeLLM(answers)
        router = FakeRouter({"execute_web_search": "данные"})
        with pytest.raises(LLMBadResponseError):
            await chat_with_tools(llm, MESSAGES, tools=[], router=router,
                                  ctx=MagicMock())
        assert len(llm.all_messages) == TOOL_MAX_ROUNDS  # ровно 4 вызова LLM
        assert len(router.calls) == TOOL_MAX_ROUNDS

    @pytest.mark.asyncio
    async def test_tool_error_returned_as_tool_message(self):
        """AC-2.4: сбой инструмента → role:"tool" с «ОШИБКА …», диалог жив."""
        llm = FakeLLM([
            _tool_result("c1", "execute_web_search", "x"),
            _text("продолжаю"),
        ])
        router = FakeRouter(
            {"execute_web_search": "ОШИБКА execute_web_search: поиск недоступен"})
        out = await chat_with_tools(llm, MESSAGES, tools=[], router=router,
                                    ctx=MagicMock())
        assert out == "продолжаю"
        tool = llm.all_messages[1][-1]
        assert tool["role"] == "tool"
        assert tool["content"].startswith("ОШИБКА execute_web_search")

    @pytest.mark.asyncio
    async def test_dispatch_exception_wrapped_into_error_text(self):
        class BoomRouter:
            async def dispatch(self, name, arguments, ctx):
                raise RuntimeError("внутренний взрыв")

        llm = FakeLLM([_tool_result("c1", "execute_web_search", "x"), _text("жив")])
        out = await chat_with_tools(llm, MESSAGES, tools=[], router=BoomRouter(),
                                    ctx=MagicMock())
        assert out == "жив"
        tool = llm.all_messages[1][-1]
        assert tool["role"] == "tool"
        assert "ОШИБКА execute_web_search: RuntimeError" in tool["content"]

    @pytest.mark.asyncio
    async def test_provider_rejects_tools_degrades_to_plain(self):
        """AC-2.5/FR-15: LLMError на 1-м раунде → один повтор БЕЗ tools →
        обычный ответ (юзер не видит ошибок)."""
        class RejectingLLM(FakeLLM):
            def __init__(self):
                super().__init__([])
                self.plain_text = "обычный ответ без инструментов"

            async def generate_chat(self, messages, *, temperature=None,
                                    tools=None, tool_choice="auto"):
                raise LLMError("HTTP 400: provider does not support tools")

        llm = RejectingLLM()
        out = await chat_with_tools(llm, MESSAGES, tools=[{"type": "function"}],
                                    router=FakeRouter({}), ctx=MagicMock())
        assert out == "обычный ответ без инструментов"
        assert llm.generated_plain == 1

    @pytest.mark.asyncio
    async def test_empty_final_answer_raises_bad_response(self):
        llm = FakeLLM([_tool_result("c1", "execute_web_search", "x"),
                       LLMChatResult(content=None, tool_calls=None,
                                     finish_reason="stop")])
        router = FakeRouter({"execute_web_search": "данные"})
        with pytest.raises(LLMBadResponseError):
            await chat_with_tools(llm, MESSAGES, tools=[], router=router,
                                  ctx=MagicMock())

    @pytest.mark.asyncio
    async def test_first_answer_without_tools_is_final(self):
        llm = FakeLLM([_text("сразу ответ")])
        router = FakeRouter({})
        out = await chat_with_tools(llm, MESSAGES, tools=[{"type": "function"}],
                                    router=router, ctx=MagicMock())
        assert out == "сразу ответ"
        assert router.calls == []
        assert len(llm.all_messages) == 1

    @pytest.mark.asyncio
    async def test_more_than_two_tool_calls_truncated(self):
        """Защита от спама: >2 tool_calls одним ходом → обрезка до 2."""
        llm = FakeLLM([
            LLMChatResult(content=None, tool_calls=[
                LLMToolCall(id="c1", name="execute_web_search", arguments='{"query": "a"}'),
                LLMToolCall(id="c2", name="query_chat_memory", arguments='{"query": "b"}'),
                LLMToolCall(id="c3", name="execute_web_search", arguments='{"query": "c"}'),
            ], finish_reason="tool_calls"),
            _text("финал"),
        ])
        router = FakeRouter({"execute_web_search": "A", "query_chat_memory": "B"})
        await chat_with_tools(llm, MESSAGES, tools=[], router=router, ctx=MagicMock())
        assert [c[0] for c in router.calls] == ["execute_web_search",
                                                "query_chat_memory"]
        assistant = llm.all_messages[1][1]
        assert len(assistant["tool_calls"]) == 2

    @pytest.mark.asyncio
    async def test_crushed_arguments_wrapped_by_loop(self):
        """Кривой JSON аргументов → tool-результат «ОШИБКА …», диалог жив."""
        llm = FakeLLM([
            LLMChatResult(content=None,
                          tool_calls=[LLMToolCall(id="c1", name="execute_web_search",
                                                  arguments="{не json")],
                          finish_reason="tool_calls"),
            _text("ответ"),
        ])
        router = FakeRouter({})

        async def _never_dispatch(name, arguments, ctx):
            raise AssertionError("dispatch не должен был вызваться")

        router.dispatch = _never_dispatch
        out = await chat_with_tools(llm, MESSAGES, tools=[], router=router,
                                    ctx=MagicMock())
        assert out == "ответ"
        tool = llm.all_messages[1][-1]
        assert tool["content"].startswith("ОШИБКА execute_web_search")

    @pytest.mark.asyncio
    async def test_query_chat_memory_count_reaches_model(self):
        """Bugfix 04.09.2026 (Часть 2, AC-3.7): реальный ToolRouter c count →
        роль tool несёт «Найдено N упоминаний …» → финальный текст с числом."""
        import time
        from unittest.mock import AsyncMock, MagicMock

        from services.tool_router import ToolContext, ToolDeps, ToolRouter

        now = int(time.time())
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            {"user_id": 10, "author_name": "вася", "text": "бензин опять",
             "timestamp": now - 100}])
        memory.vector_search = AsyncMock(return_value=[])
        memory.get_rag_context = AsyncMock(return_value="")
        memory.count_mentions = AsyncMock(return_value={
            "count": 7, "first_seen": now - 9000, "last_seen": now - 100})
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory,
                                     aliases=None))
        llm = FakeLLM([
            LLMChatResult(content=None, tool_calls=[
                LLMToolCall(id="mc1", name="query_chat_memory",
                            arguments='{"query": "бензин"}')],
                finish_reason="tool_calls"),
            _text("упоминали 7 раз"),
        ])
        ctx = ToolContext(-1001234567890, "сколько раз упоминали бензин?")
        out = await chat_with_tools(llm, MESSAGES, tools=[], router=router,
                                    ctx=ctx)
        assert out == "упоминали 7 раз"
        tool = llm.all_messages[1][-1]
        assert tool["role"] == "tool"
        assert "Найдено 7 упоминаний «бензин» за всё время" in tool["content"]
