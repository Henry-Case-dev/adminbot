"""MCA-23 (Wave 3) — Unified Response Orchestrator: ядро.

Покрытие лейна W3-M-mca23:
* Golden-классификация §44: A micro / B fanfic / C detailed no-tools /
  L explicit short vs long (детерминированный ResponsePlan, 0 LLM).
* §5 compat-алиасы casual/serious/deep_research -> оси плана.
* §11 Verbalizer = исполнитель плана: extent-блок вместо mode-блока;
  prompt-conflict scrub старого cap-текста (PG-кастом) из финальной сборки.
* §10 канон: глобального cap «1-2 предложения» больше нет (в новом каноне),
  прежний текст — в слепках (детально в test_prompt_migrations/
  test_direct_chat_prompts).
* §Model slots: max_output_tokens только для longform-планов.
* §Delivery Router: RichMessage — опциональная ветка с честным fallback.
"""
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import response_extent as rext
from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    DIRECT_VERBALIZER_SYSTEM_PROMPT,
    PREV_CHAT_MCA23_SYSTEM_PROMPT,
    PREV_CHAT_VERBALIZER_MCA23,
    PREV_CHAT_VERBALIZER_R1023,
)
from services.direct_chat_service import DirectChatService
from services.prompt_style_blocks import (
    MODE_CASUAL_BLOCK,
    MODE_DEEP_RESEARCH_BLOCK,
    TYPOGRAPHY_BLOCK,
    compose_verbalizer_system,
)
from services.response_extent import ResponsePlan
from services.tool_loop import ToolLoopResult


# ── A/B/C/L. Golden-классификация (§44) ──────────────────────────────────────

class TestClassifyRequestGoldens:
    def test_a_micro_yes_no(self):
        """A: «бот, да или нет?» -> micro, один вызов fast path."""
        plan = rext.classify_request("бот, да или нет?")
        assert plan.extent == "micro"
        assert plan.task_kind == "direct_answer"
        assert plan.structure == "answer"
        assert plan.delivery_hint == "plain"

    def test_b_fanfic_longform(self):
        """B: «бот, напиши фанфик...» -> creative_writing/longform/story,
        tools не нужны (§9/§16)."""
        plan = rext.classify_request("бот, напиши фанфик про дракона")
        assert plan.task_kind == "creative_writing"
        assert plan.extent == "longform"
        assert plan.structure == "story"
        assert plan.tool_policy == "none"
        assert plan.is_longform()

    def test_c_detailed_no_tools(self):
        """C: «бот, подробно объясни X» -> longform-семейство, не cap."""
        plan = rext.classify_request("бот, подробно объясни каналы в Go")
        assert plan.task_kind == "explanation"
        assert plan.is_longform()
        assert plan.structure == "explanation"
        assert plan.delivery_hint == "plain"

    def test_l_explicit_short_vs_long(self):
        """L: одна тема, разные инструкции -> разные extent."""
        short = rext.classify_request("бот, коротко про каналы Go")
        long = rext.classify_request("бот, распиши подробно каналы Go")
        assert short.source == "explicit"
        assert long.source == "explicit"
        assert short.extent == "compact"
        assert long.extent == "longform"
        assert short.extent != long.extent

    def test_chat_default_compact(self):
        plan = rext.classify_request("бот, как дела?")
        # ультракороткий вопрос без маркеров -> micro fast path (§8);
        # болтовня без вопросики -> compact
        assert plan.extent in ("micro", "compact")
        assert plan.structure in ("chat", "answer")
        assert not plan.is_longform()

    def test_research_report_wants_rich(self):
        plan = rext.classify_request("бот, сделай полный обзор по теме X")
        assert plan.task_kind == "research"
        assert plan.structure == "report"
        assert plan.delivery_hint == "rich"

    def test_explicit_short_beats_task_kind(self):
        plan = rext.classify_request("бот, напиши коротко рассказ")
        assert plan.task_kind == "creative_writing"
        assert plan.extent == "compact"

    def test_empty_query_default_plan(self):
        plan = rext.classify_request("")
        assert plan == ResponsePlan()
        assert not plan.is_longform()


# ── §5: compat-алиасы режимов ────────────────────────────────────────────────

class TestModeAliasPlans:
    @pytest.mark.parametrize("mode,extent,structure,delivery", [
        ("casual", "compact", "chat", "plain"),
        ("serious", "normal", "answer", "plain"),
        ("deep_research", "detailed", "report", "rich"),
    ])
    def test_alias_mapping(self, mode, extent, structure, delivery):
        plan = rext.plan_from_response_mode(mode)
        assert plan is not None
        assert plan.extent == extent
        assert plan.structure == structure
        assert plan.delivery_hint == delivery
        assert plan.source == "mode_alias"

    def test_unknown_mode_no_plan(self):
        assert rext.plan_from_response_mode("wat") is None


# ── §11: extent-блоки и compose ──────────────────────────────────────────────

class TestExtentBlocks:
    def test_render_block_all_extents(self):
        for extent in rext.EXTENTS:
            block = rext.render_extent_block(
                ResponsePlan(extent=extent, structure="chat"))
            assert block.startswith("ОЖИДАЕМАЯ ПОЛНОТА:")
        assert "«" not in rext.render_extent_block(
            ResponsePlan(extent="detailed", structure="report"))
        assert "—" not in rext.render_extent_block(
            ResponsePlan(extent="longform", structure="story"))

    def test_render_block_includes_structure(self):
        block = rext.render_extent_block(
            ResponsePlan(extent="longform", structure="story"))
        assert "Форма результата: история." in block

    def test_render_block_none_or_invalid(self):
        assert rext.render_extent_block(None) == ""
        assert rext.render_extent_block(ResponsePlan(extent="wat")) == ""

    def test_compose_extent_block_replaces_mode_block(self):
        composed = compose_verbalizer_system("BASE", "casual", "plain",
                                             extent_block="EXTENT_SENTINEL")
        assert "EXTENT_SENTINEL" in composed
        assert MODE_CASUAL_BLOCK not in composed

    def test_compose_without_extent_byte_parity(self):
        composed = compose_verbalizer_system("BASE", "casual", "plain")
        assert MODE_CASUAL_BLOCK in composed
        assert compose_verbalizer_system("BASE", "casual", "plain",
                                         extent_block="") == composed

    def test_compose_deep_research_extent_keeps_format_block(self):
        """deep_research: extent заменяет только mode-блок, канальный
        форматный блок (html-safe) сохраняется."""
        composed = compose_verbalizer_system("BASE", "deep_research", "plain",
                                             html_safe=True,
                                             extent_block="EXTENT_SENTINEL")
        assert "EXTENT_SENTINEL" in composed
        assert MODE_DEEP_RESEARCH_BLOCK not in composed
        assert "ФОРМАТ PLAIN" in composed

    def test_new_verbalizer_canon_is_extent_driven(self):
        """§11: unconditional cap-правило убрано из канона Вербализатора."""
        assert "одно-два предложения" not in DIRECT_VERBALIZER_SYSTEM_PROMPT
        assert "ОЖИДАЕМАЯ ПОЛНОТА" in DIRECT_VERBALIZER_SYSTEM_PROMPT
        assert TYPOGRAPHY_BLOCK in DIRECT_VERBALIZER_SYSTEM_PROMPT

    def test_new_chat_canon_has_no_global_cap(self):
        """§10: глобального cap «СТРОГО 1-2 предложения» в каноне нет."""
        assert "СТРОГО ИЗ ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ" not in CHAT_SYSTEM_PROMPT
        assert "ОЧЕНЬ коротко" not in CHAT_SYSTEM_PROMPT
        assert "Не сокращай ответ так" in CHAT_SYSTEM_PROMPT

    def test_prev_snapshots_keep_cap_text(self):
        """Правило миграции: прежний cap-текст живёт в слепках."""
        assert "СТРОГО ИЗ ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ" \
            in PREV_CHAT_MCA23_SYSTEM_PROMPT
        assert "одно-два предложения" in PREV_CHAT_VERBALIZER_MCA23
        assert PREV_CHAT_VERBALIZER_MCA23 == (
            PREV_CHAT_VERBALIZER_R1023 + "\n\n" + TYPOGRAPHY_BLOCK)
        assert PREV_CHAT_MCA23_SYSTEM_PROMPT != CHAT_SYSTEM_PROMPT


# ── §11/§32: prompt-conflict scrub ───────────────────────────────────────────

class TestPromptConflictScrub:
    def test_canonical_cap_phrases_removed(self):
        dirty = ("ПРАВИЛА:\n"
                 "5. Коротко: одно-два предложения.\n"
                 "ГЛАВНОЕ ОГРАНИЧЕНИЕ (КРИТИЧЕСКИ ВАЖНО):\n"
                 "Ты должен отвечать ОЧЕНЬ коротко. "
                 "Твой ответ должен состоять СТРОГО ИЗ ОДНОГО "
                 "ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ. \n"
                 "Не объясняй свои мысли, не пиши списки. "
                 "Максимум пара язвительных фраз. "
                 "Если напишешь больше двух предложений - система упадет.\n"
                 "ДРУГОЕ:\nполезный текст")
        cleaned, removed = rext.strip_cap_phrases(dirty)
        assert removed >= 5
        assert "одно-два предложения" not in cleaned
        assert "СТРОГО ИЗ ОДНОГО" not in cleaned
        assert "ОЧЕНЬ коротко" not in cleaned
        assert "система упадет" not in cleaned
        assert "полезный текст" in cleaned
        assert "ДРУГОЕ" in cleaned

    def test_scrub_only_for_longform_family(self):
        text = "5. Коротко: одно-два предложения."
        out, removed = rext.scrub_for_plan(
            text, ResponsePlan(extent="compact", structure="chat"))
        assert removed == 0 and out == text
        out2, removed2 = rext.scrub_for_plan(
            text, ResponsePlan(extent="longform", structure="story"))
        assert removed2 == 1 and "одно-два предложения" not in out2
        out3, removed3 = rext.scrub_for_plan(text, None)
        assert removed3 == 0 and out3 == text


# ── §Model slots: max_output_tokens только для longform ──────────────────────

class TestLongformMaxOutputTokens:
    def test_default_conservative_value(self, monkeypatch):
        monkeypatch.delattr(Settings, "DIRECT_LONGFORM_MAX_OUTPUT_TOKENS",
                            raising=False)
        value = rext.longform_max_output_tokens()
        assert value == rext.DEFAULT_LONGFORM_MAX_OUTPUT_TOKENS

    def test_env_zero_disables(self, monkeypatch):
        # Патчим КЛАСС ТЕКУЩЕГО инстанса config.settings.settings — именно
        # его читает response_extent. Полный прогон содержит
        # importlib.reload(config.settings): класс `Settings`, импортированный
        # в шапке модуля, сдвигается, и патч старого класса не действует
        # (order-dependency; тот же приём, что в
        # test_direct_context_capacity_asap3 / test_image_daily_limit_round1026).
        from config import settings as settings_mod
        monkeypatch.setattr(type(settings_mod.settings),
                            "DIRECT_LONGFORM_MAX_OUTPUT_TOKENS", 0,
                            raising=False)
        assert rext.longform_max_output_tokens() is None

    def test_env_override_clamped(self, monkeypatch):
        # См. NOTE в test_env_zero_disables: целимся в type(инстанса).
        from config import settings as settings_mod
        monkeypatch.setattr(type(settings_mod.settings),
                            "DIRECT_LONGFORM_MAX_OUTPUT_TOKENS",
                            999999, raising=False)
        assert rext.longform_max_output_tokens() == 16384

    def test_kill_switches_default_on(self, monkeypatch):
        monkeypatch.delattr(Settings, "DIRECT_RESPONSE_PLAN_ENABLED",
                            raising=False)
        monkeypatch.delattr(Settings, "DIRECT_RICH_DELIVERY_ENABLED",
                            raising=False)
        assert rext.response_plan_enabled() is True
        assert rext.rich_delivery_enabled() is True


class TestLLMGenerateMaxTokens:
    """max_tokens попадает в payload только при переданном параметре."""

    @staticmethod
    def _client():
        from services.llm_client import LLMClient
        return LLMClient("http://x", "KEY", "chat-model", "")

    @staticmethod
    def _capturing_client(captured: dict):
        client = TestLLMGenerateMaxTokens._client()

        class _Resp:
            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "ответ"}}],
                        "usage": {}}

        async def _fake_post(path, payload, api_key=None, **kwargs):
            captured["payload"] = payload
            return _Resp()

        async def _fake_key(chat_id=None):
            return "KEY", "global"

        client._post_with_key = _fake_post           # type: ignore[assignment]
        client._resolve_api_key_and_source = _fake_key  # type: ignore[assignment]
        client._record_global_usage = AsyncMock()    # type: ignore[assignment]
        client._record_analytics = AsyncMock()       # type: ignore[assignment]
        return client

    @pytest.mark.asyncio
    async def test_max_tokens_present_when_passed(self):
        captured: dict = {}
        client = self._capturing_client(captured)
        await client.generate([{"role": "user", "content": "q"}],
                              chat_id=-100,
                              max_output_tokens=4096)
        assert captured["payload"]["max_tokens"] == 4096

    @pytest.mark.asyncio
    async def test_no_max_tokens_key_by_default(self):
        captured: dict = {}
        client = self._capturing_client(captured)
        await client.generate([{"role": "user", "content": "q"}],
                              chat_id=-100)
        assert "max_tokens" not in captured["payload"]

    @pytest.mark.asyncio
    async def test_invalid_or_zero_ignored(self):
        captured: dict = {}
        client = self._capturing_client(captured)
        await client.generate([{"role": "user", "content": "q"}],
                              chat_id=-100, max_output_tokens=0)
        assert "max_tokens" not in captured["payload"]


# ── CoordinatorDecision: оси плана ───────────────────────────────────────────

class TestCoordinatorDecisionPlan:
    def _decision(self, **over):
        from services.direct_chat_service import build_coordinator_decision
        message = MagicMock()
        message.message_id = 7
        raw = "текст"
        defaults = dict(query="бот, напиши фанфик", message=message,
                        raw=raw, user_id=1, image_fired=False,
                        dig_fired=False, lore_compiled=False)
        defaults.update(over)
        return build_coordinator_decision(**defaults)

    def test_plan_fields_filled_from_query(self):
        decision = self._decision()
        assert decision.task_kind == "creative_writing"
        assert decision.extent == "longform"
        assert decision.structure == "story"
        assert decision.tool_policy == "none"
        assert decision.action == "reply"

    def test_plan_passthrough(self):
        plan = ResponsePlan(task_kind="research", extent="detailed",
                            structure="report", delivery_hint="rich",
                            tool_policy="auto", source="task-kind")
        decision = self._decision(plan=plan, query="что угодно")
        assert decision.extent == "detailed"
        assert decision.structure == "report"
        assert decision.delivery_hint == "rich"

    def test_invalid_axes_normalized_to_empty(self):
        plan = ResponsePlan(task_kind="research", extent="detailed",
                            structure="report", delivery_hint="rich",
                            tool_policy="auto")
        decision = self._decision(plan=plan, query="q")
        decision.task_kind = "bogus-kind"
        decision.extent = "bogus-extent"
        decision.structure = "bogus-struct"
        decision.delivery_hint = "bogus-delivery"
        decision.tool_policy = "bogus-policy"
        # нормализация происходит в __post_init__; повторно прогоняем через
        # конструктор с "грязными" значениями
        from services.direct_chat_service import CoordinatorDecision
        dirty = CoordinatorDecision(
            intent="question", addressee="author", memory_need=False,
            tool_calls=(), evaluation="none", action="reply",
            task_kind="bogus-kind", extent="bogus-extent",
            structure="bogus-struct", delivery_hint="bogus-delivery",
            tool_policy="bogus-policy")
        assert dirty.task_kind == ""
        assert dirty.extent == ""
        assert dirty.structure == ""
        assert dirty.delivery_hint == ""
        assert dirty.tool_policy == ""


# ── §11: Verbalizer — исполнитель плана (System2) ────────────────────────────

_DIRECT_JSON = json.dumps({
    "user_question": "что там с погодой",
    "facts": [{"topic": "погода", "finding": "завтра дождь",
               "source": "exa", "confidence": "high"}],
    "answer_outline": "взять зонт",
    "limitations": [],
    "response_mode": "casual",
})


def _service(side_effect):
    svc = DirectChatService.__new__(DirectChatService)
    svc.llm = MagicMock()
    svc.llm.generate = AsyncMock(side_effect=side_effect)
    return svc


def _tool_raw(text="финал tool-loop"):
    return ToolLoopResult(
        text, rounds_used=2,
        tool_trace=[{"round": 1, "tool": "execute_web_search", "ok": True,
                     "out_chars": 20}],
        tool_context="сырые логи")


class TestVerbalizerExecutesPlan:
    @pytest.mark.asyncio
    async def test_longform_plan_extent_block_replaces_mode_block(self):
        svc = _service([_DIRECT_JSON, "развернутый ответ"])
        plan = ResponsePlan(task_kind="creative_writing", extent="longform",
                            structure="story", delivery_hint="plain",
                            tool_policy="none")
        text, mode = await svc._synthesize_direct_answer(
            -100, "что там", _tool_raw(), None, plan=plan)
        assert text == "развернутый ответ"
        stage2_system = svc.llm.generate.await_args_list[1].args[0][0][
            "content"]
        assert "ОЖИДАЕМАЯ ПОЛНОТА: РАЗВЁРНУТЫЙ ТЕКСТ" in stage2_system
        assert "Форма результата: история." in stage2_system
        assert MODE_CASUAL_BLOCK not in stage2_system
        # max_tokens: только longform-план получает модельный слот длины
        stage2_kwargs = svc.llm.generate.await_args_list[1].kwargs
        assert stage2_kwargs.get("max_output_tokens") == \
            rext.DEFAULT_LONGFORM_MAX_OUTPUT_TOKENS

    @pytest.mark.asyncio
    async def test_no_plan_legacy_mode_block_and_no_max_tokens(self):
        svc = _service([_DIRECT_JSON, "ответ"])
        text, _mode = await svc._synthesize_direct_answer(
            -100, "что там", _tool_raw(), None)
        stage2_system = svc.llm.generate.await_args_list[1].args[0][0][
            "content"]
        assert MODE_CASUAL_BLOCK in stage2_system
        assert "ОЖИДАЕМАЯ ПОЛНОТА: " not in stage2_system
        assert svc.llm.generate.await_args_list[1].kwargs.get(
            "max_output_tokens") is None

    @pytest.mark.asyncio
    async def test_compact_plan_no_max_tokens(self):
        svc = _service([_DIRECT_JSON, "ответ"])
        plan = ResponsePlan(extent="compact", structure="chat")
        await svc._synthesize_direct_answer(
            -100, "что там", _tool_raw(), None, plan=plan)
        assert svc.llm.generate.await_args_list[1].kwargs.get(
            "max_output_tokens") is None


class TestPromptConflictScrubLive:
    """PG-кастом со старым cap + longform-план → фраза вычищена из сборки."""

    @pytest.mark.asyncio
    async def test_pg_cap_custom_scrubbed_with_warn(self, monkeypatch, caplog):
        from services import hot_config as hot

        class _FakeCache:
            pg_available = True

            def __init__(self, values):
                self.values = dict(values)

            def get(self, key, default=None):
                return self.values.get(key, default)

            async def set(self, key, value, category):
                self.values[key] = value

        pg_prompt = (PREV_CHAT_VERBALIZER_R1023
                     + "\n\n" + TYPOGRAPHY_BLOCK)  # прод-канон 10.23 с cap
        hot.set_config_cache(_FakeCache({
            "prompts.direct_chat_verbalizer_system_prompt": pg_prompt}))
        try:
            svc = _service([_DIRECT_JSON, "ответ"])
            plan = ResponsePlan(task_kind="creative_writing",
                                extent="longform", structure="story",
                                delivery_hint="plain", tool_policy="none")
            with caplog.at_level(logging.WARNING,
                                 logger="services.direct_chat_service"):
                await svc._synthesize_direct_answer(
                    -100, "что там", _tool_raw(), None, plan=plan)
            stage2_system = svc.llm.generate.await_args_list[1].args[0][0][
                "content"]
            # cap-фраза вычищена из ФИНАЛЬНОЙ сборки ( extent-блок жив)
            assert "одно-два предложения" not in stage2_system
            assert "ОЖИДАЕМАЯ ПОЛНОТА: РАЗВЁРНУТЫЙ ТЕКСТ" in stage2_system
            assert any("extent-conflict scrub" in r.message
                       and "stage=verbalizer" in r.message
                       for r in caplog.records)
        finally:
            hot.set_config_cache(None)


# ── §Delivery Router: rich-опция с честным fallback ──────────────────────────

class TestRichDeliveryOption:
    @staticmethod
    def _bot(**rich_behavior):
        bot = MagicMock()
        if "exc" in rich_behavior:
            bot.send_rich_message = AsyncMock(side_effect=rich_behavior["exc"])
        else:
            sent = MagicMock()
            sent.message_id = rich_behavior.get("message_id", 555)
            bot.send_rich_message = AsyncMock(return_value=sent)
        return bot

    @pytest.mark.asyncio
    async def test_rich_success_returns_message_id(self):
        bot = self._bot(message_id=777)
        sent_id = await DirectChatService._send_direct_answer(
            bot, -100, "статья", 42, rich=True)
        assert sent_id == 777
        bot.send_rich_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rich_failure_falls_back_to_plain(self, monkeypatch):
        bot = self._bot(exc=RuntimeError("sendRichMessage not supported"))
        sent = MagicMock()
        sent.message_id = 888
        chunked = AsyncMock(return_value=888)
        monkeypatch.setattr("services.direct_chat_service.send_chunked_reply",
                            chunked)
        sent_id = await DirectChatService._send_direct_answer(
            bot, -100, "ответ", 42, rich=True)
        assert sent_id == 888
        chunked.assert_awaited_once()
        assert chunked.await_args.args[2] == "ответ"

    @pytest.mark.asyncio
    async def test_rich_without_flag_plain_path(self, monkeypatch):
        bot = self._bot()
        chunked = AsyncMock(return_value=999)
        monkeypatch.setattr("services.direct_chat_service.send_chunked_reply",
                            chunked)
        sent_id = await DirectChatService._send_direct_answer(
            bot, -100, "ответ", 42)
        assert sent_id == 999
        bot.send_rich_message.assert_not_awaited()
