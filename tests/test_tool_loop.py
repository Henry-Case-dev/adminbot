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
from services.tool_loop import (
    TOOL_LOOP_FALLBACK_PHRASE,
    ToolLoopResult,
    chat_with_tools,
)


class FakeLLM:
    """generate_chat по заранее заданным ответам; generate — финальный фолбэк."""

    def __init__(self, answers, plain_text="обычный ответ"):
        self._answers = list(answers)
        self.plain_text = plain_text
        self.generated_plain = 0
        self.all_messages = []

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.all_messages.append(copy.deepcopy(messages))
        assert tools is not None, "generate_chat без tools — сломанный тест"
        if not self._answers:
            raise AssertionError("не хватило запланированных ответов")
        return self._answers.pop(0)

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
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
    async def test_more_than_four_rounds_continue_until_model_finishes(self):
        """SMART-EXECUTION-RELIABILITY-01 §B1: фиксированного лимита раундов
        (4) больше нет — модель доводит исследование до своего финала; все
        вызовы исполняются и не теряются."""
        answers = [
            _tool_result(f"call_{i}", "execute_web_search", f"q{i}")
            for i in range(6)
        ] + [_text("содержательный финал после шести раундов")]
        llm = FakeLLM(answers)
        router = FakeRouter({"execute_web_search": "данные"})
        out = await chat_with_tools(llm, MESSAGES, tools=[], router=router,
                                    ctx=MagicMock())
        assert out == "содержательный финал после шести раундов"
        assert out.degraded is False and out.reason == "ok"
        assert out.rounds_used == 7                     # 6 tool-раундов + финал
        assert len(router.calls) == 6                   # ни один не потерян
        assert len(out.tool_results) == 6
        # Валидная последовательность провайдера на КАЖДОМ раунде.
        for snapshot in llm.all_messages[1:]:
            roles = [m["role"] for m in snapshot]
            assert roles.count("assistant") == roles.count("tool")

    @pytest.mark.asyncio
    async def test_identical_repeat_rounds_stop_by_no_progress(self):
        """§B4 п.2: если модель повторяет тот же вызов без изменения условий,
        новые данные не прибавляются — честный stop `no_progress` с частичным
        результатом (не квота объёма, а отсутствие прогресса)."""
        answers = [_tool_result("call_same", "execute_web_search", "same")
                   for _ in range(4)]
        llm = FakeLLM(answers)
        router = FakeRouter({"execute_web_search": "данные"})
        out = await chat_with_tools(llm, MESSAGES, tools=[], router=router,
                                    ctx=MagicMock())
        assert out.degraded is True and out.reason == "no_progress"
        assert len(router.calls) == 1                   # повтор из кэша
        assert out.tool_results[1]["duplicate"] is True
        # Каждый запрошенный tool_call_id получил сообщение role:"tool"
        # (кумулятивно по payload: ни один id не потерян).
        for snapshot in llm.all_messages[1:]:
            assistants = [m for m in snapshot if m["role"] == "assistant"]
            tool_msgs = [m for m in snapshot if m["role"] == "tool"]
            assert len(tool_msgs) == sum(
                len(a["tool_calls"]) for a in assistants)

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
                                    tools=None, tool_choice="auto",
                                    chat_id=None, **kwargs):
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
    async def test_all_tool_calls_in_one_round_are_dispatched(self):
        """§B1: список вызовов одного хода больше НЕ обрезается до 2 — все
        корректно запрошенные вызовы исполняются, каждый со своим id."""
        llm = FakeLLM([
            LLMChatResult(content=None, tool_calls=[
                LLMToolCall(id="c1", name="execute_web_search", arguments='{"query": "a"}'),
                LLMToolCall(id="c2", name="query_chat_memory", arguments='{"query": "b"}'),
                LLMToolCall(id="c3", name="execute_web_search", arguments='{"query": "c"}'),
            ], finish_reason="tool_calls"),
            _text("финал"),
        ])
        router = FakeRouter({"execute_web_search": "A", "query_chat_memory": "B"})
        out = await chat_with_tools(llm, MESSAGES, tools=[], router=router,
                                    ctx=MagicMock())
        assert [c[0] for c in router.calls] == ["execute_web_search",
                                                "query_chat_memory",
                                                "execute_web_search"]
        assistant = llm.all_messages[1][1]
        assert len(assistant["tool_calls"]) == 3
        tool_ids = [m["tool_call_id"] for m in llm.all_messages[1]
                    if m["role"] == "tool"]
        assert tool_ids == ["c1", "c2", "c3"]
        assert out.degraded is False and len(out.tool_results) == 3

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
        assert "Широкий поиск (префиксы, не морфология): 7 сообщений «бензин» за всё время" in tool["content"]
