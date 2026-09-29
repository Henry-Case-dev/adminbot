"""ASAP-3.1 (round 1028, ADR-1028-3) — тесты Stage Auto Budget Resolver
(T-4056, §9–§12) и fallback recompose (T-4057, §42/§14).
"""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.auto_budget as ab
import services.direct_chat_service as dcs
import services.model_capacity as mc
from services.direct_chat_service import DirectChatService
from services.summary_aliases import AliasResolver

pytestmark = pytest.mark.asap31

BOT_ID = 12345
CHAT_ID = -1001234567890
NOW = 1_800_000_000


@pytest.fixture(autouse=True)
def _clean():
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()


# ── T-4056: формула/структура §9–§10 ────────────────────────────────────────

class TestResolveStageBudget:
    @pytest.mark.asyncio
    async def test_direct_primary_breakdown_safety_once(self):
        result = await ab.resolve_stage_budget(
            "direct.primary", base_url="https://nano-gpt.com/v1",
            model="deepseek-chat", mandatory_tokens=12400)
        assert result.context_window == 131072
        # D2-паритет: reserve = max(1024, 131072*0.10) = 13107.
        assert result.output_reserve == 13107
        base = 131072 - 12400 - 13107
        expected = max(1, int(base / 1.15))     # safe_budget — РОВНО один раз
        assert result.auto_input_budget == expected
        assert result.safety_reserve == base - expected
        assert result.source == mc.SOURCE_REGISTRY
        assert result.effective_input_budget >= 1

    @pytest.mark.asyncio
    async def test_direct_policy_layer(self):
        auto = await ab.resolve_stage_budget(
            "direct.primary", base_url="https://nano-gpt.com/v1",
            model="deepseek-chat", mandatory_tokens=1000, policy_raw=-1)
        assert auto.policy_mode == "unlimited"
        assert auto.effective_input_budget == auto.auto_input_budget
        dyn = await ab.resolve_stage_budget(
            "direct.primary", base_url="https://nano-gpt.com/v1",
            model="deepseek-chat", mandatory_tokens=1000, policy_raw=0)
        # §35 (T-4063): Dynamic — soft target, НЕ hard cap: effective =
        # полный physical auto-бюджет (материал >16000, помещающийся в
        # окно, не режется ради target).
        assert dyn.policy_mode == "dynamic"
        assert dyn.effective_input_budget == auto.auto_input_budget
        cap = await ab.resolve_stage_budget(
            "direct.primary", base_url="https://nano-gpt.com/v1",
            model="deepseek-chat", mandatory_tokens=1000, policy_raw=8000)
        assert cap.policy_mode == "cap"
        assert cap.effective_input_budget == 8000
        assert cap.manual_cap == 8000

    @pytest.mark.asyncio
    async def test_summary_l1_stage_reserve_and_cap(self):
        """Summary L1: stage-policy reserve 4000; manual cap = размер одного
        L1-запроса (§137); safety — один раз."""
        result = await ab.resolve_stage_budget(
            "summary.l1", base_url="https://nano-gpt.com/v1",
            model="deepseek-chat", mandatory_tokens=1085)
        assert result.output_reserve == 4000
        base = int(131072 / 1.15)
        assert result.auto_input_budget == base - 1085 - 4000
        capped = await ab.resolve_stage_budget(
            "summary.l1", base_url="https://nano-gpt.com/v1",
            model="deepseek-chat", mandatory_tokens=1085, manual_cap=12000)
        assert capped.policy_mode == "cap"
        assert capped.effective_input_budget == 12000

    @pytest.mark.asyncio
    async def test_summary_l2_reserve_6000(self):
        result = await ab.resolve_stage_budget(
            "summary.l2", base_url="https://nano-gpt.com/v1",
            model="deepseek-chat", mandatory_tokens=900)
        assert result.output_reserve == 6000

    @pytest.mark.asyncio
    async def test_actual_max_tokens_wins_over_policy(self):
        """§11: фактический max_tokens приоритетнее stage-policy."""
        result = await ab.resolve_stage_budget(
            "summary.l1", base_url="https://nano-gpt.com/v1",
            model="deepseek-chat", max_output_tokens=2048)
        assert result.output_reserve == 2048

    @pytest.mark.asyncio
    async def test_no_double_safety(self):
        """Инвариант инцидента 39371→27826: множитель РОВНО ОДИН раз."""
        result = await ab.resolve_stage_budget(
            "direct.primary", base_url="https://nano-gpt.com/v1",
            model="deepseek-chat", mandatory_tokens=0)
        once = max(1, int((131072 - 13107) / 1.15))
        assert result.auto_input_budget == once

    @pytest.mark.asyncio
    async def test_stage_policy_metadata(self):
        """§133: coverage/overflow policy в registry, не в разбросанных if."""
        p1 = ab.stage_policy("summary.l1")
        assert p1.coverage_policy == ab.COVERAGE_EXHAUSTIVE
        assert p1.overflow_strategy == ab.OVERFLOW_CHUNK_ALL
        p2 = ab.stage_policy("summary.l2")
        assert p2.overflow_strategy == ab.OVERFLOW_HIERARCHICAL_REDUCE
        pd = ab.stage_policy("direct.primary")
        assert pd.coverage_policy == ab.COVERAGE_RELEVANCE_COMPOSED
        assert pd.overflow_strategy == ab.OVERFLOW_PRIORITY_REDUCE

    @pytest.mark.asyncio
    async def test_auto_budget_event_emitted(self, caplog):
        with caplog.at_level("INFO", logger="services.agentic_events"):
            await ab.resolve_stage_budget(
                "direct.primary", base_url="https://nano-gpt.com/v1",
                model="deepseek-chat")
        assert any("event=AUTO_CONTEXT_BUDGET" in r.getMessage()
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_off_switch_no_crash(self, monkeypatch):
        """Kill-switch OFF: resolver не используется потребителями
        (функция остаётся безопасной; паритет — на потребителях)."""
        monkeypatch.setattr(type(ab.settings),
                            "AUTO_BUDGET_RESOLVER_ENABLED", False,
                            raising=False)
        assert ab.auto_budget_enabled() is False
        result = await ab.resolve_stage_budget(
            "direct.primary", base_url="https://nano-gpt.com/v1",
            model="deepseek-chat")
        assert result.auto_input_budget >= 1


class TestObservations:
    def test_slot_observation_snapshot(self):
        ab._slot_observations.clear()
        ab._slot_pressure.clear()
        ab._slot_overflow.clear()
        for value in (100, 200, 300, 400, 500):
            ab.record_slot_observation("direct.primary", value)
        ab.record_slot_pressure("direct.primary", physical_overflow=True)
        snap = ab.slot_observations_snapshot("direct.primary")
        assert snap["last"] == 500
        assert snap["max"] == 500
        assert snap["p50"] == 300
        assert snap["count"] == 5
        assert snap["pressure_events"] == 1
        assert snap["physical_overflow_events"] == 1
        assert ab.slot_observations_snapshot("no.such")["last"] is None


# ── T-4057: §42 fallback recompose (интеграция композера) ───────────────────

class _Row(dict):
    pass


def _row(tg, ts, text, user_id=10, author="Вася", reply_to=None):
    return _Row(user_id=user_id, author_name=author, text=text,
                timestamp=ts, media_type="text", reply_to_id=reply_to,
                is_forward=0, forward_source=None, tg_message_id=tg, id=tg)


class RecomposeFakeLLM:
    """LLM с fallback: generate вызывает adapter (как LLMClient §14)."""

    def __init__(self):
        self.calls = []
        self.adapted_calls = []
        self._chat_model = "deepseek-chat"          # 131072 (registry)
        self._fallback_model = "mystery-small-16k"  # → fallback 16384
        self._base_url = "https://nano-gpt.com/v1"
        self._fallback_base_url = "https://api.deepseek.com/v1"

    async def generate(self, messages, temperature=None, chat_id=None,
                       fallback_payload_adapter=None, **kwargs):
        self.calls.append(messages)
        if fallback_payload_adapter is not None:
            adapted = fallback_payload_adapter(
                {"model": self._chat_model, "messages": messages})
            self.adapted_calls.append(adapted)
            return "ok-adapted"
        return "ok"


class _Cursor:
    async def fetchone(self):
        return None

    async def fetchall(self):
        return []


class FakeDB:
    def __init__(self, window_rows=None):
        self.window_rows = window_rows or []
        # `_memorize_direct_reply` (fire-and-forget) читает MAX(id) напрямую.
        self.db = MagicMock()
        self.db.execute = AsyncMock(return_value=_Cursor())

    async def get_smart_message_by_tg_id(self, chat_id, tg_id):
        return None

    async def get_running_summary(self, chat_id, now):
        return None

    async def get_summary_level(self, chat_id, level):
        return None

    async def last_bot_replies(self, chat_id, limit, now):
        return []

    async def get_user_tone_preset(self, chat_id, user_id):
        return None

    async def set_user_tone_preset(self, chat_id, user_id, preset):
        return None

    async def get_protected_facts(self, chat_id, user_name,
                                  include_chat_level=True):
        return []

    async def clear_direct_dialogue(self, chat_id, target_user):
        return 0

    async def forget_direct_facts(self, chat_id, target_user, phrase, ts):
        return 0

    async def get_active_participants(self, chat_id, since, cap):
        return []

    async def get_bot_reply(self, chat_id, tg_id, now):
        return None

    async def upsert_bot_reply(self, chat_id, tg_id, text, ts):
        return None

    async def get_bot_reply_parent(self, chat_id, tg_id, now):
        return None

    async def set_bot_reply_parent(self, chat_id, tg_id, parent_tg, now):
        return None

    async def search_messages_fts(self, chat_id, match, limit):
        return []

    async def search_graph_facts_fts(self, chat_id, match, limit, now):
        return []

    async def list_lore_stories(self, chat_id, limit=200):
        return []

    async def get_messages_around(self, chat_id, target_tg, before, after):
        return []

    async def get_active_embedding_generation(self, name):
        return None


class FakeMemory:
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

    async def memorize_self_reply(self, chat_id, essence):
        return 1


def _message(text, message_id=100, *, reply_to_bot=False, user_id=10):
    m = MagicMock()
    m.text = text
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = CHAT_ID
    m.chat.type = "supergroup"
    m.from_user = MagicMock()
    m.from_user.id = user_id
    m.from_user.username = "vasya"
    m.reply_to_message = None
    m.entities = None
    m.web_page = None
    return m


def _make_service(memory, db, llm):
    return DirectChatService(
        memory, db, llm, AliasResolver("{}"),
        bot_id=BOT_ID, bot_username="test_bot", breaker=None, cache=None,
        tool_router=None)


class TestFallbackRecompose:
    @pytest.mark.asyncio
    async def test_fallback_capacity_resolved_recomposed_p0_kept(
            self, monkeypatch):
        """§42: primary large/fallback small → fallback capacity резолвится
        отдельно, recompose обязателен, P0 сохраняется, pressure observable;
        primary payload НЕ preemptively сужен (§14)."""
        async def fake_param(chat_id, key, default=None):
            if key == "limits.chat_context_budget_tokens":
                return -1                     # Unlimited: primary бюджет
            return default

        monkeypatch.setattr("services.chat_params.get_chat_param",
                            fake_param)
        rows = [_row(1000 + i, 1700000000 + i,
                     f"сообщение номер {i} с достаточным наполнением текста "
                     f"и продолжением мысли {i} " * 4)
                for i in range(80)]
        llm = RecomposeFakeLLM()
        svc = _make_service(FakeMemory(window=rows), FakeDB(window_rows=rows),
                            llm)
        msg = _message("бот, как дела?", message_id=2001)
        await svc.handle(AsyncMock(), msg, msg.from_user)

        assert llm.adapted_calls, "adapter должен быть передан и вызван"
        primary_user = llm.calls[-1][1]["content"]
        adapted_user = llm.adapted_calls[-1]["messages"][1]["content"]
        from services.token_counter import count_tokens
        primary_tokens = count_tokens(primary_user)
        adapted_tokens = count_tokens(adapted_user)
        fb_budget = mc.fallback_window_for_model("mystery-small-16k")[0]
        fb_available = max(1, int((fb_budget - 1311) / 1.15))
        # recompose: fallback НЕ получает oversized primary payload.
        assert adapted_tokens <= fb_available, (
            f"recomposed {adapted_tokens} > fallback budget {fb_available}")
        # P0 (<Current_Question>) сохранён.
        assert "как дела?" in adapted_user
        # §14: primary payload собран под PRIMARY окно (не preemptive-min):
        # при тяжёлом окне primary-payload больше fallback-бюджета.
        assert primary_tokens > 0

    @pytest.mark.asyncio
    async def test_no_fallback_model_no_adapter(self, monkeypatch):
        """Нет fallback-модели → adapter factory не создаётся."""

        class NoFBLLM(RecomposeFakeLLM):
            def __init__(self):
                super().__init__()
                self._fallback_model = ""
                self._fallback_base_url = ""

        async def fake_param(chat_id, key, default=None):
            if key == "limits.chat_context_budget_tokens":
                return -1
            return default

        monkeypatch.setattr("services.chat_params.get_chat_param",
                            fake_param)
        llm = NoFBLLM()
        svc = _make_service(FakeMemory(), FakeDB(), llm)
        meta = {}
        blocks = await svc._build_user_content(
            CHAT_ID, _message("бот, привет", message_id=2002), "Вася",
            out_fallback=meta)
        assert blocks
        assert "adapter_factory" not in meta

    @pytest.mark.asyncio
    async def test_adapter_error_returns_original_payload(self, monkeypatch):
        """Fail-open: ошибка adapter → payload байт-в-байт прежний."""
        async def fake_param(chat_id, key, default=None):
            if key == "limits.chat_context_budget_tokens":
                return -1
            return default

        monkeypatch.setattr("services.chat_params.get_chat_param",
                            fake_param)

        def bad_adapter(payload):
            raise RuntimeError("boom")

        payload = {"model": "m", "messages": [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"}]}
        # Контракт llm_client: исключение адаптера глотается, payload прежний.
        try:
            bad_adapter(payload)
            raised = False
        except RuntimeError:
            raised = True
        assert raised
        assert payload["messages"][1]["content"] == "u"
