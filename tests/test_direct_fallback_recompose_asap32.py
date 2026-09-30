"""ASAP-3.2 (ADR-1028-5 D10, §44–§46, Q11) — fallback recompose на ВСЕХ
Direct execution paths.

§44: контракт ``primary payload → primary failure → resolve fallback
capacity → RECOMPOSE FULL logical context under fallback budget → fallback
call`` обязан работать на: plain generate; tool-enabled generate_chat;
tool loop; retry path; any direct response branch.
§45: mandatory payload = system + persona + tool schemas + tool state +
messages; tool schemas ВХОДЯТ в fallback budget.
§46: регресс production-like — primary effective 1M / fallback 32K /
tool_router enabled / primary forced failure → fallback payload recomposed,
≤ fallback effective budget, P0 сохранён, tools preserved, no 400/overflow.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.tool_loop as tool_loop
from services.llm_client import LLMClient, LLMError, LLMChatResult

pytestmark = pytest.mark.asap32

FB_WINDOW_TOKENS = 32768          # §46: fallback 32K


def _chat_result(content="ok"):
    return LLMChatResult(content=content, tool_calls=None,
                         finish_reason="stop", reasoning=None)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _ok_response(content="fallback answer"):
    return _FakeResponse({"choices": [{"message": {"content": content},
                                       "finish_reason": "stop"}],
                          "usage": {"prompt_tokens": 10}})


def _client() -> LLMClient:
    """LLMClient с fallback-парой: primary 1M-модель / fallback 32K."""
    client = LLMClient(
        base_url="https://primary.example/v1",
        api_key="k-primary",
        chat_model="mystery-large-1m",
        embed_model="text-embed",
        fallback_base_url="https://fallback.example/v1",
        fallback_api_key="k-fb",
        fallback_model="mystery-small-16k",
    )
    assert client._fallback_active
    return client


def _tools():
    """Реалистичные tool schemas (заметная константа бюджета, §45)."""
    return [
        {"type": "function", "function": {
            "name": f"tool_{i}",
            "description": "Инструмент с длинным описанием контракта. " * 6,
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string",
                          "description": "поисковый запрос пользователя"}}}},
        } for i in range(8)]


def _big_messages(target_tokens: int):
    """Сообщения под primary 1M-окно (упрощённо: chars ≈ tokens)."""
    block = "сообщение контекста с достаточным наполнением " * 20
    messages = [{"role": "system", "content": "Ты Летописец. Системный канон."}]
    per_msg = 900
    count = max(1, target_tokens // per_msg)
    for i in range(count):
        messages.append({"role": "user" if i % 2 == 0 else "assistant",
                         "content": block[:per_msg]})
    messages.append({"role": "user", "content": "бот, ответь на вопрос P0"})
    return messages


def _recompose_adapter(budget_tokens: int):
    """§45-адаптер: system + messages recompose под бюджет; tools
    сохраняются и УЧИТЫВАЮТСЯ (резерв вычтен до вызова адаптера)."""
    from services.token_counter import count_tokens

    def _adapt(payload):
        tools = payload.get("tools") or []
        tools_reserve = count_tokens(json.dumps(tools, ensure_ascii=False)) \
            if tools else 0
        effective = max(1, budget_tokens - tools_reserve)
        system = ""
        messages = payload.get("messages") or []
        kept = []
        used = 0
        for msg in messages:
            # стоимость сообщения = JSON-обёртка + контент (точный учёт)
            cost = count_tokens(json.dumps(msg, ensure_ascii=False))
            if msg.get("role") == "system":
                system = str(msg.get("content") or "")
                used += cost
                continue
            kept.append(msg)
        # Хвост (P0: последний user) сохраняется всегда; старые вытесняются.
        tail = [kept[-1]] if kept else []
        tail_cost = sum(count_tokens(json.dumps(m, ensure_ascii=False))
                        for m in tail)
        mid = []
        acc = used + tail_cost
        for msg in reversed(kept[:-1]):
            cost = count_tokens(json.dumps(msg, ensure_ascii=False))
            if acc + cost > effective:
                break
            mid.append(msg)
            acc += cost
        recomposed = []
        if system:
            recomposed.append({"role": "system", "content": system})
        recomposed.extend(reversed(mid))
        recomposed.extend(tail)
        adapted = dict(payload)
        adapted["messages"] = recomposed
        return adapted
    return _adapt


class TestGenerateChatRecompose:
    @pytest.mark.asyncio
    async def test_chat_recomposed_under_fallback_budget_tools_kept(self):
        """§46 (generate_chat): primary 1M fails → recomposed ≤ fallback
        budget, tool schemas preserved, no oversized payload."""
        client = _client()
        seen = {}

        async def fail_primary(path, payload, **kwargs):
            seen["primary"] = payload
            raise LLMError("primary down")

        async def fb_retries(payload):
            seen["fallback"] = payload
            return _ok_response()

        client._post_with_key = fail_primary
        client._fallback_with_retries = fb_retries
        adapter = _recompose_adapter(FB_WINDOW_TOKENS)
        result = await client.generate_chat(
            _big_messages(600_000), tools=_tools(), chat_id=1,
            fallback_payload_adapter=adapter)
        assert result.content == "fallback answer"
        fb_payload = seen["fallback"]
        # tools сохранены (§45: не «выбросить tools, чтобы влезло»)
        assert fb_payload.get("tools"), "tool schemas должны сохраниться"
        # recomposed ≤ fallback effective budget (tools_reserve учтён)
        from services.token_counter import count_tokens
        msg_tokens = count_tokens(json.dumps(
            fb_payload["messages"], ensure_ascii=False))
        tools_tokens = count_tokens(json.dumps(
            fb_payload["tools"], ensure_ascii=False))
        assert msg_tokens + tools_tokens <= FB_WINDOW_TOKENS
        # P0 (последний user-вопрос) сохранён
        assert fb_payload["messages"][-1]["content"] == \
            "бот, ответь на вопрос P0"
        # system сохранён
        assert fb_payload["messages"][0]["role"] == "system"
        # adapter вызван с ПОЛНЫМ payload (включая tools)
        assert seen["primary"].get("tools")

    @pytest.mark.asyncio
    async def test_chat_no_adapter_primary_sized_payload_fallback(self):
        """Без адаптера — прежнее поведение (payload сквозной)."""
        client = _client()
        seen = {}

        async def fail_primary(path, payload, **kwargs):
            raise LLMError("primary down")

        async def fb_retries(payload):
            seen["p"] = payload
            return _ok_response()

        client._post_with_key = fail_primary
        client._fallback_with_retries = fb_retries
        await client.generate_chat(_big_messages(10_000), chat_id=1)
        assert len(seen["p"]["messages"]) == 13  # байт-в-байт (system+11+user)

    @pytest.mark.asyncio
    async def test_chat_adapter_failure_loud_oversized_diagnostic(
            self, caplog):
        """D10 усиление: ошибка адаптера → fail-open, но oversized-risk
        диагностика ВИДИМА (не тихая отправка)."""
        client = _client()
        seen = {}

        async def fail_primary(path, payload, **kwargs):
            raise LLMError("primary down")

        async def fb_retries(payload):
            seen["p"] = payload
            return _ok_response()

        client._post_with_key = fail_primary
        client._fallback_with_retries = fb_retries

        def bad_adapter(payload):
            raise RuntimeError("boom")

        import logging
        with caplog.at_level(logging.WARNING, logger="services.llm_client"):
            await client.generate_chat(_big_messages(1_000), chat_id=1,
                                       fallback_payload_adapter=bad_adapter)
        assert any("oversized_risk=1" in r.message for r in caplog.records)
        assert seen["p"]["messages"]  # payload отправлен прежний (fail-open)


class TestToolLoopRecompose:
    @pytest.mark.asyncio
    async def test_tool_loop_passes_adapter_every_round(self):
        """§44 (tool loop): adapter прокидывается в generate_chat каждого
        раунда и в FR-15 plain-фолбэк."""
        seen_kwargs = []

        class FakeLLM:
            _chat_model = "m"
            _fallback_model = "fb"
            _base_url = "https://x/v1"
            _fallback_base_url = ""

            async def generate_chat(self, messages, **kwargs):
                seen_kwargs.append(kwargs)
                raise LLMError("provider rejects tools")

            async def generate(self, messages, **kwargs):
                seen_kwargs.append(kwargs)
                return "plain answer"

        adapter = _recompose_adapter(FB_WINDOW_TOKENS)
        result = await tool_loop.chat_with_tools(
            FakeLLM(), [{"role": "user", "content": "q"}],
            tools=_tools(), router=MagicMock(), ctx=MagicMock(),
            fallback_payload_adapter=adapter)
        assert result == "plain answer"
        assert len(seen_kwargs) == 2  # generate_chat + plain generate
        assert seen_kwargs[0].get("fallback_payload_adapter") is adapter
        assert seen_kwargs[1].get("fallback_payload_adapter") is adapter

    @pytest.mark.asyncio
    async def test_tool_loop_no_adapter_kwarg_when_absent(self):
        """Без адаптера — kwargs не содержат ключа (паритет прежних вызовов
        с тестовыми double без fallback_payload_adapter)."""
        seen_kwargs = []

        class FakeLLM:
            _chat_model = "m"
            _fallback_model = "fb"

            async def generate_chat(self, messages, **kwargs):
                seen_kwargs.append(kwargs)
                return _chat_result("final")

        await tool_loop.chat_with_tools(
            FakeLLM(), [{"role": "user", "content": "q"}],
            tools=_tools(), router=MagicMock(), ctx=MagicMock())
        assert seen_kwargs[0].get("fallback_payload_adapter") is None


class TestGenerateStrengthenedDiagnostics:
    @pytest.mark.asyncio
    async def test_generate_adapter_error_loud_and_payload_intact(
            self, caplog):
        """generate(): якорь ASAP-3.1 (payload прежний) + D10 (громкий лог)."""
        client = _client()
        seen = {}

        async def fail_primary(path, payload, **kwargs):
            raise LLMError("down")

        async def fb_retries(payload):
            seen["p"] = payload
            return _ok_response("done")

        client._post_with_key = fail_primary
        client._fallback_with_retries = fb_retries

        def bad_adapter(payload):
            raise RuntimeError("boom")

        import logging
        with caplog.at_level(logging.WARNING, logger="services.llm_client"):
            out = await client.generate(
                [{"role": "user", "content": "hi"}], chat_id=1,
                fallback_payload_adapter=bad_adapter)
        assert out == "done"
        assert any("oversized_risk=1" in r.message for r in caplog.records)
        assert len(seen["p"]["messages"]) == 1

    @pytest.mark.asyncio
    async def test_generate_adapter_invalid_shape_loud(self, caplog):
        client = _client()

        async def fail_primary(path, payload, **kwargs):
            raise LLMError("down")

        async def fb_retries(payload):
            return _ok_response("done")

        client._post_with_key = fail_primary
        client._fallback_with_retries = fb_retries
        import logging
        with caplog.at_level(logging.WARNING, logger="services.llm_client"):
            await client.generate(
                [{"role": "user", "content": "hi"}], chat_id=1,
                fallback_payload_adapter=lambda p: {"no": "messages"})
        assert any("oversized_risk=1" in r.message for r in caplog.records)


# ── §45: tool schemas входят в fallback budget (фабрика композера) ──────────

class _Row(dict):
    pass


def _row(tg, ts, text, user_id=10, author="Вася"):
    return _Row(user_id=user_id, author_name=author, text=text,
                timestamp=ts, media_type="text", reply_to_id=None,
                is_forward=0, forward_source=None, tg_message_id=tg, id=tg)


class _Cursor:
    async def fetchone(self):
        return None

    async def fetchall(self):
        return []


class _FakeDB:
    def __init__(self, window_rows=None):
        self.window_rows = window_rows or []
        self.db = MagicMock()
        self.db.execute = AsyncMock(return_value=_Cursor())

    def __getattr__(self, name):
        async def _none(*a, **k):
            return None
        return _none

    async def get_smart_message_by_tg_id(self, chat_id, tg_id):
        return None

    async def last_bot_replies(self, chat_id, limit, now):
        return []

    async def get_active_participants(self, chat_id, since, cap):
        return []

    async def get_running_summary(self, chat_id, now):
        return None

    async def get_summary_level(self, chat_id, level):
        return None

    async def get_messages_around(self, chat_id, target_tg, before, after):
        return []

    async def get_bot_reply(self, chat_id, tg_id, now):
        return None

    async def get_protected_facts(self, chat_id, user_name,
                                  include_chat_level=True):
        return []

    async def search_messages_fts(self, chat_id, match, limit):
        return []

    async def search_graph_facts_fts(self, chat_id, match, limit, now):
        return []

    async def list_lore_stories(self, chat_id, limit=200):
        return []


class _FakeMemory:
    def __init__(self, window=None):
        self.window = window or []

    async def get_window_messages(self, chat_id):
        return self.window

    async def get_rag_context(self, chat_id, query, **kwargs):
        return ""

    async def get_rag_facts(self, chat_id, query, **kwargs):
        return []

    async def rerank_rag_facts(self, query, facts):
        return list(facts)

    async def retrieve_fact_candidates(self, chat_id, query, limit=8):
        return []

    async def memorize_facts(self, chat_id, raw_text, source_type, **kw):
        return None


class _FBLLM:
    def __init__(self):
        self._chat_model = "deepseek-chat"
        self._fallback_model = "mystery-small-16k"
        self._base_url = "https://nano-gpt.com/v1"
        self._fallback_base_url = "https://api.deepseek.com/v1"

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        return "ok"


class TestToolSchemasInFallbackBudget:
    @pytest.mark.asyncio
    async def test_factory_extra_reserve_shrinks_recompose(self, monkeypatch):
        """§45: extra_reserve (tool schemas) уменьшает recompose-бюджет —
        payload с tools пересобирается под (fallback_budget − tools)."""
        async def fake_param(chat_id, key, default=None):
            if key == "limits.chat_context_budget_tokens":
                return -1
            return default

        monkeypatch.setattr("services.chat_params.get_chat_param", fake_param)
        import services.direct_chat_service as dcs
        rows = [_row(1000 + i, 1700000000 + i,
                     "сообщение окна с содержательным текстом " * 8)
                for i in range(60)]
        llm = _FBLLM()
        svc = dcs.DirectChatService(
            _FakeMemory(window=rows), _FakeDB(window_rows=rows), llm,
            __import__("services.summary_aliases", fromlist=["AliasResolver"]
                       ).AliasResolver("{}"),
            bot_id=1, bot_username="tb", breaker=None, cache=None,
            tool_router=None)
        trigger = MagicMock()
        trigger.text = "бот, как дела?"
        trigger.message_id = 2000
        trigger.reply_to_message = None
        trigger.web_page = None
        trigger.entities = None
        # маленькое primary-окно → тяжёлые блоки P1/P2 вытесняются по бюджету
        meta = {}
        blocks = await svc._build_user_content(
            1, trigger, "Вася", out_fallback=meta)
        assert blocks and "adapter_factory" in meta
        factory = meta["adapter_factory"]
        payload = {"model": "m",
                   "messages": [
                       {"role": "system", "content": "SYS"},
                       {"role": "user", "content": "\n\n".join(blocks)}],
                   "tools": _tools()}
        light = factory(None, extra_reserve=0)(dict(payload))
        heavy = factory(None, extra_reserve=100_000)(dict(payload))
        light_size = len(str(light["messages"][1]["content"]))
        heavy_size = len(str(heavy["messages"][1]["content"]))
        assert heavy_size < light_size, (
            "tool schemas должны вычитаться из recompose-бюджета")
        # tools проходят сквозь адаптер без потерь (dict passthrough)
        assert heavy.get("tools") == payload["tools"]
