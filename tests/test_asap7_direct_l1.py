"""ASAP 7 (F1) — Direct L1 Planner: Golden D1-D15 + контракты топологии.

Покрытие (architecture.md §1.1-§1.9, current_task ASAP 7 §2/§3/§15/§22/§23):
  * D1  — короткое контекстное «а этот?»: план из LLM, не по длине;
  * D2  — one_word;
  * D3  — explicit short override (форма поверх semantic extent, §2.5);
  * D4  — aggression → hostile_rebuff (semantic, не keyword);
  * D5  — aggression в другом контексте — L1 свободен;
  * D6  — banter;
  * D7  — web+memory без 2 URL (capability mapping §1.4);
  * D8  — history only;
  * D9  — contextual media без clarification;
  * D10 — missing target → ровно один clarification, тула не запускаются;
  * D11 — CONTRACT: финальный промпт longform НЕ содержит «коротко»/«по
          делу» (sandwich D-1); L1 sandwich не получает;
  * D12 — longform не режется hidden cap (max_output_tokens честный);
  * D13 — L1 outage → deterministic fallback, без duplicate reply;
  * D14 — invalid JSON → ровно 1 repair → fallback (без циклов);
  * D15 — hallucinated capability → drop + L1_CAPABILITY_REJECTED + честная
          пометка L2; statistics → ∅ (нет тула);
  * force → REPLY hard override; SILENT direct → 🗿; топология ≤2 semantic
    LLM call на reply-путь; DIRECT_L1_ENABLED=false → legacy байт-паритет.

TEST-LIFECYCLE: CONTRACT + REGRESSION(D-1/D-2/D-3) owner=ASAP7/F1
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import direct_l1 as _l1
from services import direct_capabilities as _caps
from services import response_extent as _extent
from services.llm_client import LLMError
from services.tool_loop import ToolLoopResult

pytestmark = [pytest.mark.system2, pytest.mark.asap3]


# ── фикстуры/хелперы ─────────────────────────────────────────────────────────


def _drive(monkeypatch, text, *, reply=None, tool_router=None, llm=None,
           l1=True, decision=True, user_blocks=None, memory=None,
           real_user_content=False):
    """DirectChatService в L1-режиме: моки ввода/вывода, реальный pipeline."""
    import services.direct_chat_service as dcs
    from tests.test_direct_chat import _bot, _make_service, _message, _user
    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", l1)
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", decision)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    svc = _make_service(tool_router=tool_router, llm=llm, memory=memory)
    if not real_user_content:
        svc._build_user_content = AsyncMock(
            return_value=list(user_blocks if user_blocks is not None else []))
    svc._image_pre_gate_block = AsyncMock(return_value=None)
    svc._dig_pre_gate_block = AsyncMock(return_value=None)
    svc._send_direct_answer = AsyncMock(return_value=999)
    svc.remember_bot_reply = AsyncMock()
    react = AsyncMock()
    monkeypatch.setattr(dcs, "react_moai", react)
    msg = _message(text=text)
    if reply is not None:
        msg.reply_to_message = reply
    return svc, react, _bot(), msg, _user()


def _bot_reply(message_id=7, text="предыдущее сообщение"):
    m = MagicMock()
    m.message_id = message_id
    m.text = text
    m.from_user = MagicMock()
    m.from_user.id = 12345          # bot_id из _make_service
    m.web_page = None
    for attr in ("photo", "video", "video_note", "voice", "audio",
                 "animation", "sticker", "document"):
        setattr(m, attr, None)
    return m


class _FakeLLM:
    """Fake LLM с раздельными стадиями по `step`: l1_planner → план,
    l2_writer → финальный текст, прочее → legacy single-текст."""

    def __init__(self, *, l1=None, l2="готовый ответ", single="обычный ответ",
                 l1_error=None):
        self.l1_reply = l1              # str | list (pop по вызовам)
        self.l2_text = l2
        self.single_text = single
        self.l1_error = l1_error
        self.calls = []

    def _next_l1(self):
        item = self.l1_reply
        if isinstance(item, list):
            item = item.pop(0) if item else ""
        if isinstance(item, Exception):
            raise item
        return item

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kwargs):
        self.calls.append({"step": step, "messages": messages,
                           "kwargs": kwargs})
        if step == "l1_planner":
            if self.l1_error is not None:
                raise self.l1_error
            await asyncio.sleep(0)
            return self._next_l1()
        if step == "l2_writer":
            return self.l2_text
        return self.single_text

    def steps(self):
        return [c["step"] for c in self.calls]

    def calls_of(self, step):
        return [c for c in self.calls if c["step"] == step]

    def last_messages(self, step):
        found = self.calls_of(step)
        return found[-1]["messages"] if found else []


def _plan_json(**over):
    plan = {"action": "reply", "reaction": None,
            "response_act": "answer", "extent": "auto", "tone": "inherit",
            "emotional_mirroring": "none", "structure": "chat",
            "delivery_hint": "plain", "tool_policy": "none",
            "capabilities_needed": [], "needs_clarification": False,
            "clarification_target": None, "confidence": 0.9}
    plan.update(over)
    import json
    return json.dumps(plan, ensure_ascii=False)


def _plan_dict(**over):
    """Тот же план, но dict (для прямых вызовов normalize_l1_plan)."""
    import json
    return json.loads(_plan_json(**over))


def _window(rows):
    return [{"user_id": 10, "author_name": author, "text": text,
             "timestamp": 100 + i, "media_type": "text",
             "reply_to_id": None, "tg_message_id": None}
            for i, (author, text) in enumerate(rows)]


def _patch_chat_with_tools(monkeypatch, result, capture=None):
    import services.direct_chat_service as dcs

    async def fake_chat_with_tools(llm, payload, *, tools, router, ctx,
                                   temperature, chat_id=None, module=None,
                                   correlation_id=None,
                                   fallback_payload_adapter=None,
                                   max_output_tokens=None, tool_plan=None,
                                   **kw):
        if capture is not None:
            capture.append({
                "tools": [t["function"]["name"] for t in tools],
                "tool_plan": tool_plan})
        return result

    monkeypatch.setattr(dcs, "chat_with_tools", fake_chat_with_tools)


def _tool_result_ok(text="финал тулов"):
    return ToolLoopResult(
        text, rounds_used=2,
        tool_trace=[{"tool": "execute_web_search", "ok": True}],
        tool_context="найденные данные поиска",
        tool_results=[{"tool": "execute_web_search", "status": "ok"}])


# ── D1 — короткое контекстное «а этот?» (план из LLM, не по длине) ───────────


class TestGoldenD1D6:
    @pytest.mark.asyncio
    async def test_d1_short_contextual_plan_from_llm(self, monkeypatch):
        """D1: «а этот?» после обсуждения моделей — L1 получает окно и
        решает семантически (normal extent), а не «3 слова → micro»."""
        memory = MagicMock()
        memory.get_window_messages = AsyncMock(return_value=_window([
            ("вася", "смотри, Model A стоит дешевле"),
            ("олег", "а Model B быстрее, но дороже"),
        ]))
        llm = _FakeLLM(l1=_plan_json(extent="normal",
                                     response_act="comparison"),
                       l2="этот быстрее и дороже")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "а этот?", llm=llm, memory=memory)
        await svc.handle(bot, msg, user)
        l1_calls = llm.calls_of("l1_planner")
        assert len(l1_calls) == 1
        l1_text = "".join(str(m.get("content")) for m in l1_calls[0]["messages"])
        assert "Model A" in l1_text and "Model B" in l1_text
        # План (не длина) определяет extent: micro-блока нет, L2 получил
        # ОБЫЧНУЮ полноту (auto → без extent-блока, D11-семантика).
        l2_messages = llm.last_messages("l2_writer")
        l2_text = "".join(str(m.get("content")) for m in l2_messages)
        assert "МИКРО" not in l2_text
        svc._send_direct_answer.assert_awaited_once()
        assert svc._send_direct_answer.await_args.args[2] == "этот быстрее и дороже"

    @pytest.mark.asyncio
    async def test_d2_one_word(self, monkeypatch):
        """D2: «понял?» — L1 вправе выбрать one_word; L2 получает МИКРО."""
        llm = _FakeLLM(l1=_plan_json(extent="one_word"), l2="да")
        svc, react, bot, msg, user = _drive(monkeypatch, "понял?", llm=llm)
        await svc.handle(bot, msg, user)
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "МИКРО" in l2_text
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_d3_explicit_short_override_beats_semantic(self, monkeypatch):
        """D3: явная форма «одним словом» — дет. override ПОСЛЕ L1 поверх
        semantic extent (§2.5)."""
        llm = _FakeLLM(l1=_plan_json(extent="detailed"), l2="кот")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "ответь одним словом: кто такой кот?", llm=llm)
        await svc.handle(bot, msg, user)
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "МИКРО" in l2_text
        assert "ПОДРОБНО" not in l2_text

    @pytest.mark.asyncio
    async def test_d4_aggression_hostile_rebuff_semantic(self, monkeypatch):
        """D4: грубый стёб → L1 выбирает hostile_rebuff/aggressive; план
        приходит из LLM (никакого keyword-hardcode в production logic)."""
        memory = MagicMock()
        memory.get_window_messages = AsyncMock(return_value=_window([
            ("вася", "ты опять хуйню несёшь"),
            ("бот", "сам ты несёшь"),
        ]))
        llm = _FakeLLM(l1=_plan_json(response_act="hostile_rebuff",
                                     tone="aggressive", extent="one_word",
                                     emotional_mirroring="strong"),
                       l2="сам иди")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "иди нахуй", llm=llm, memory=memory)
        await svc.handle(bot, msg, user)
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "hostile_rebuff" in l2_text
        assert "aggressive" in l2_text
        assert "strong" in l2_text
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_d5_aggression_other_context_l1_free(self, monkeypatch):
        """D5: та же грубость в другом контексте — L1 не обязан зеркалить;
        semantic model реально решает."""
        memory = MagicMock()
        memory.get_window_messages = AsyncMock(return_value=_window([
            ("вася", "меня вчера выгнали с работы, я в отчаянии"),
        ]))
        llm = _FakeLLM(l1=_plan_json(response_act="support", tone="serious",
                                     extent="normal"),
                       l2="держись, расскажи что случилось")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "иди нахуй", llm=llm, memory=memory)
        await svc.handle(bot, msg, user)
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "support" in l2_text
        assert "hostile_rebuff" not in l2_text
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_d6_banter(self, monkeypatch):
        """D6: banter — playful/tease вместо generic explanatory."""
        llm = _FakeLLM(l1=_plan_json(response_act="banter", tone="playful",
                                     extent="micro"),
                       l2="ахах ну ты и выдал")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "ахах ну ты долбоёб", llm=llm)
        await svc.handle(bot, msg, user)
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "banter" in l2_text and "playful" in l2_text
        svc._send_direct_answer.assert_awaited_once()


# ── D7/D8 — semantic capabilities без 2 URL ──────────────────────────────────


class TestGoldenCapabilities:
    @pytest.mark.asyncio
    async def test_d7_web_plus_memory_without_two_urls(self, monkeypatch):
        """D7: «проверь в интернете и сравни с перепиской» →
        web_search + chat_history; 2-URL больше не «единственный мозг»."""
        capture = []
        _patch_chat_with_tools(monkeypatch, _tool_result_ok(), capture)
        llm = _FakeLLM(l1=_plan_json(tool_policy="auto",
                                     capabilities_needed=["web_search",
                                                          "chat_history"]),
                       l2="вот сравнение")
        router = MagicMock()
        svc, react, bot, msg, user = _drive(
            monkeypatch, "проверь это в интернете и сравни с нашей перепиской",
            tool_router=router, llm=llm)
        await svc.handle(bot, msg, user)
        assert capture, "tool-фаза должна была запуститься"
        assert set(capture[0]["tools"]) == {"execute_web_search",
                                            "get_recent_history"}
        # evidence packet дошёл до L2 (дет., без LLM-Синтезатора).
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "Tool_Evidence" in l2_text
        assert "найденные данные поиска" in l2_text
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_d8_history_only_no_url(self, monkeypatch):
        """D8: «сравни с тем, что он говорил вчера» → chat_history, без URL."""
        capture = []
        _patch_chat_with_tools(monkeypatch, _tool_result_ok(), capture)
        llm = _FakeLLM(l1=_plan_json(tool_policy="auto",
                                     capabilities_needed=["chat_history"]),
                       l2="вчера он говорил другое")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "сравни с тем, что он говорил вчера",
            tool_router=MagicMock(), llm=llm)
        await svc.handle(bot, msg, user)
        assert capture and capture[0]["tools"] == ["get_recent_history"]
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tool_plan_fastpath_urls_still_work(self, monkeypatch):
        """§1.4: дет. fast-path «2+ URL + явное сравнение» сохранён как
        дополнение; шаги строятся по resolved-подсету."""
        capture = []
        _patch_chat_with_tools(monkeypatch, _tool_result_ok(), capture)
        llm = _FakeLLM(l1=_plan_json(tool_policy="auto",
                                     capabilities_needed=["fetch_url"]),
                       l2="сравнил")
        svc, react, bot, msg, user = _drive(
            monkeypatch,
            "сравни https://a.example/1 и https://b.example/2",
            tool_router=MagicMock(), llm=llm)
        await svc.handle(bot, msg, user)
        assert capture and capture[0]["tools"] == ["fetch_article"]
        assert capture[0]["tool_plan"], "2-URL fast-path должен строить план"
        svc._send_direct_answer.assert_awaited_once()


# ── D9/D10 — clarification ───────────────────────────────────────────────────


class TestGoldenClarification:
    @pytest.mark.asyncio
    async def test_d9_contextual_media_no_clarification(self, monkeypatch):
        """D9: reply на медиа «расшифруй» — цель разрешима из контекста,
        clarification не задаётся, тула transcription запускается."""
        capture = []
        _patch_chat_with_tools(monkeypatch, _tool_result_ok(), capture)
        llm = _FakeLLM(l1=_plan_json(tool_policy="auto",
                                     capabilities_needed=["transcription"]),
                       l2="вот расшифровка")
        reply = _bot_reply()
        reply.document = MagicMock()          # медиа-цель в reply
        reply.text = None
        svc, react, bot, msg, user = _drive(
            monkeypatch, "расшифруй", reply=reply,
            tool_router=MagicMock(), llm=llm)
        await svc.handle(bot, msg, user)
        assert capture and capture[0]["tools"] == ["transcribe_video"]
        bot.send_message.assert_not_called()   # фикс-вопроса не было
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_d10_missing_target_exactly_one_clarification(
            self, monkeypatch):
        """D10: «скачай это» без цели → ровно один clarification; тула НЕ
        запускается; формулирует L2 (не fixed-фраза)."""
        capture = []
        _patch_chat_with_tools(monkeypatch, _tool_result_ok(), capture)
        llm = _FakeLLM(
            l1=_plan_json(response_act="clarification",
                          needs_clarification=True,
                          clarification_target="media_target",
                          capabilities_needed=["media_download"]),
            l2="что именно скачать — скинь ссылку")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "скачай это", tool_router=MagicMock(), llm=llm)
        await svc.handle(bot, msg, user)
        assert capture == [], "при clarification тула не запускаются"
        svc._send_direct_answer.assert_awaited_once()
        assert svc._send_direct_answer.await_args.args[2].startswith(
            "что именно скачать")
        # Вопрос от L2 содержит инструкцию плана (ровно один вопрос).
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "уточняющий вопрос" in l2_text
        assert len(llm.calls_of("l2_writer")) == 1


# ── D11/D12 — extent-контракты ───────────────────────────────────────────────


class TestGoldenExtentContracts:
    @pytest.mark.asyncio
    async def test_d11_longform_prompt_no_hidden_global_short(self, monkeypatch):
        """D11 CONTRACT: финальный промпт longform-плана не содержит
        «коротко»/«по делу» (sandwich D-1 починен глобально)."""
        llm = _FakeLLM(l1=_plan_json(extent="longform",
                                     response_act="creative"),
                       l2="длинная история")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "напиши рассказ про осенний лес", llm=llm,
            real_user_content=True)
        await svc.handle(bot, msg, user)
        assert llm.calls_of("l2_writer"), "L2 должен был вызваться"
        for call in llm.calls_of("l2_writer"):
            full_prompt = "\n".join(str(m.get("content"))
                                    for m in call["messages"]).lower()
            assert "коротко" not in full_prompt
            assert "по делу" not in full_prompt
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_d11b_l1_prompt_gets_no_sandwich(self, monkeypatch):
        """§1.5: L1-промпт sandwich-хвост НЕ получает (L1 не пишет прозу)."""
        llm = _FakeLLM(l1=_plan_json(), l2="ответ")
        svc, react, bot, msg, user = _drive(monkeypatch, "привет", llm=llm,
                                            real_user_content=True)
        await svc.handle(bot, msg, user)
        l1_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l1_planner"))
        assert "людей называй именами" not in l1_text
        # А Writer-контекст sandwich получает (якорь + правила имён).
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "людей называй именами" in l2_text

    @pytest.mark.asyncio
    async def test_d12_longform_not_cut_by_hidden_cap(self, monkeypatch):
        """D12: longform → явный max_output_tokens (не hidden cap/None)."""
        llm = _FakeLLM(l1=_plan_json(extent="longform",
                                     response_act="creative"),
                       l2="фанфик целиком")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "напиши полный фанфик", llm=llm)
        await svc.handle(bot, msg, user)
        l2_calls = llm.calls_of("l2_writer")
        assert l2_calls
        assert l2_calls[0]["kwargs"].get("max_output_tokens") == \
            _extent.longform_max_output_tokens()
        svc._send_direct_answer.assert_awaited_once()


# ── D13/D14/D15 — отказы и гигиена плана ─────────────────────────────────────


class TestGoldenFailureLadder:
    @pytest.mark.asyncio
    async def test_d13_l1_outage_fallback_no_duplicate_reply(self, monkeypatch):
        """D13: L1 outage → deterministic fallback (classify + demote) →
        один ответ; без duplicate/второй отправки."""
        llm = _FakeLLM(l1_error=LLMError("l1 outage"), l2="fallback ответ")
        svc, react, bot, msg, user = _drive(monkeypatch, "как дела?",
                                            llm=llm)
        await svc.handle(bot, msg, user)
        # Ровно одна попытка L1 (inherit main) + одна L2: топология целa.
        assert llm.steps() == ["l1_planner", "l2_writer"]
        svc._send_direct_answer.assert_awaited_once()
        react.assert_not_awaited()
        assert svc._send_direct_answer.await_args.args[2] == "fallback ответ"

    @pytest.mark.asyncio
    async def test_d13b_dedicated_slot_falls_back_to_main(self, monkeypatch):
        """§1.6 ladder: dedicated L1 slot упал → main model (fallback ON)."""
        llm = _FakeLLM(l1=[LLMError("slot down"), _plan_json(extent="micro")],
                       l2="ответ с main")

        async def fake_post(path, payload, *, api_key=None, base_url=None,
                            **kw):
            raise LLMError("slot down")

        llm._post = fake_post
        monkeypatch.setattr(
            _l1, "resolve_l1_model",
            lambda chat_id=None, **kw: _l1.L1ModelSlot(
                base_url="https://l1.example", model="l1-model",
                api_key="k", dedicated=True, source="l1"))
        svc, react, bot, msg, user = _drive(monkeypatch, "как дела?",
                                            llm=llm)
        await svc.handle(bot, msg, user)
        assert llm.steps() == ["l1_planner", "l2_writer"]
        l1_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "МИКРО" in l1_text
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_d14_invalid_json_one_repair_then_fallback(self, monkeypatch):
        """D14: invalid JSON → ровно 1 repair → deterministic fallback;
        циклов нет; ответ всё равно один."""
        llm = _FakeLLM(l1="это вообще не json", l2="ответ через fallback")
        svc, react, bot, msg, user = _drive(monkeypatch, "как дела?",
                                            llm=llm)
        await svc.handle(bot, msg, user)
        assert llm.steps().count("l1_planner") == 2      # 1 попытка + 1 repair
        assert llm.steps()[-1] == "l2_writer"
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_d14b_repair_succeeds(self, monkeypatch):
        """D14: после одного repair валидный JSON принимается."""
        llm = _FakeLLM(l1=["мусор", _plan_json(extent="micro")],
                       l2="короткий ответ")
        svc, react, bot, msg, user = _drive(monkeypatch, "как дела?",
                                            llm=llm)
        await svc.handle(bot, msg, user)
        assert llm.steps().count("l1_planner") == 2
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "МИКРО" in l2_text
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_d15_hallucinated_capability_dropped_with_event(
            self, monkeypatch):
        """D15: hallucinated capability → drop + L1_CAPABILITY_REJECTED;
        анонсируется только resolved-подсет; L2 получает честную пометку."""
        rejected_events = []
        monkeypatch.setattr(
            _caps, "emit_capability_rejected",
            lambda cap, reason, **kw: rejected_events.append((cap, reason)))
        capture = []
        _patch_chat_with_tools(monkeypatch, _tool_result_ok(), capture)
        llm = _FakeLLM(l1=_plan_json(tool_policy="auto",
                                     capabilities_needed=["quantum_telepathy",
                                                          "web_search"]),
                       l2="ответ без телепатии")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "проверь в интернете", tool_router=MagicMock(),
            llm=llm)
        await svc.handle(bot, msg, user)
        assert ("quantum_telepathy", "unknown_capability") in rejected_events
        assert capture and capture[0]["tools"] == ["execute_web_search"]
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "quantum_telepathy" in l2_text      # честная пометка L2
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_d15b_statistics_no_tool_honest_note(self, monkeypatch):
        """§1.4: statistics тула не имеет → ∅ + честная пометка L2; тул-фаза
        не запускается."""
        capture = []
        _patch_chat_with_tools(monkeypatch, _tool_result_ok(), capture)
        llm = _FakeLLM(l1=_plan_json(capabilities_needed=["statistics"]),
                       l2="статистику не считаю честно")
        svc, react, bot, msg, user = _drive(monkeypatch, "бот, статистика",
                                            tool_router=MagicMock(), llm=llm)
        await svc.handle(bot, msg, user)
        assert capture == []
        l2_text = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "statistics" in l2_text
        svc._send_direct_answer.assert_awaited_once()


# ── Hard gates / топология / legacy-паритет ──────────────────────────────────


class TestGatesTopologyLegacy:
    @pytest.mark.asyncio
    async def test_force_hard_override_silent_to_reply(self, monkeypatch):
        """§1.7: force → REPLY всегда; LLM не может отменить."""
        llm = _FakeLLM(l1=_plan_json(action="silent"), l2="ответ по force")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "Бот, ответь нормально", llm=llm)
        await svc.handle(bot, msg, user)
        react.assert_not_awaited()
        svc._send_direct_answer.assert_awaited_once()
        assert svc._send_direct_answer.await_args.args[2] == "ответ по force"

    @pytest.mark.asyncio
    async def test_silent_direct_executes_moai(self, monkeypatch):
        """§1.7: conscious L1 SILENT в autonomous-контексте → 🗿 (конъюнкция
        silent-ack неизменна); текст не генерируется."""
        llm = _FakeLLM(l1=_plan_json(action="silent", confidence=0.95))
        reply = _bot_reply()
        svc, react, bot, msg, user = _drive(
            monkeypatch, "Ок", reply=reply, llm=llm)
        await svc.handle(bot, msg, user)
        react.assert_awaited_once()
        assert react.await_args.kwargs.get("reaction") == "🗿"
        svc._send_direct_answer.assert_not_awaited()
        assert llm.calls_of("l2_writer") == []

    @pytest.mark.asyncio
    async def test_silent_outside_allowed_leads_to_silence(self, monkeypatch):
        """§1.7: SILENT вне allowed (ignore_trivial=False) → тишина без 🗿."""
        llm = _FakeLLM(l1=_plan_json(action="silent", confidence=0.95))
        reply = _bot_reply()
        svc, react, bot, msg, user = _drive(
            monkeypatch, "Ок", reply=reply, llm=llm)
        from services.direct_chat_service import DecisionToggles
        svc._decision_toggles = AsyncMock(
            return_value=DecisionToggles(False, True, True))
        await svc.handle(bot, msg, user)
        react.assert_not_awaited()
        svc._send_direct_answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_silent_demoted_to_reply_when_decision_off(self, monkeypatch):
        """§48-семантика: decision-политика выключена → L1 silent/react
        демотируются в текстовый ответ."""
        llm = _FakeLLM(l1=_plan_json(action="silent", confidence=0.95),
                       l2="текстовый ответ")
        reply = _bot_reply()
        svc, react, bot, msg, user = _drive(
            monkeypatch, "Ок", reply=reply, llm=llm, decision=False)
        await svc.handle(bot, msg, user)
        react.assert_not_awaited()
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_react_uses_allowed_emoji(self, monkeypatch):
        """§1.7: L1 react — реакция из ALLOWED_LLM_REACTIONS уходит в
        react_moai; текста нет."""
        llm = _FakeLLM(l1=_plan_json(action="react", reaction="🔥"),
                       l2="не должно")
        reply = _bot_reply()
        msg = None
        svc, react, bot, m, user = _drive(
            monkeypatch, "АХАХА", reply=reply, llm=llm)
        m.message_id = 4242
        await svc.handle(bot, m, user)
        react.assert_awaited_once()
        assert react.await_args.kwargs.get("reaction") == "🔥"
        svc._send_direct_answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_react_invalid_reaction_demote_or_silence(self, monkeypatch):
        """§1.7: невалидная реакция вне demoted-REACT → тишина (семантика
        :2658-2683)."""
        llm = _FakeLLM(l1=_plan_json(action="react", reaction="🙃"),
                       l2="не должно")
        svc, react, bot, msg, user = _drive(monkeypatch, "привет", llm=llm)
        await svc.handle(bot, msg, user)
        react.assert_not_awaited()
        svc._send_direct_answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_topology_two_semantic_calls_on_reply_path(self, monkeypatch):
        """§22 п.3/§2.7: reply-путь — ровно 2 semantic LLM call
        (l1_planner + l2_writer); третий запрещён."""
        capture = []
        _patch_chat_with_tools(monkeypatch, _tool_result_ok(), capture)
        llm = _FakeLLM(l1=_plan_json(tool_policy="auto",
                                     capabilities_needed=["web_search"]),
                       l2="итог тулов")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "бот, загугли новости", tool_router=MagicMock(),
            llm=llm)
        await svc.handle(bot, msg, user)
        semantic = [s for s in llm.steps() if s in ("l1_planner",
                                                    "l2_writer")]
        assert semantic == ["l1_planner", "l2_writer"]
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_l1_off_legacy_byte_parity(self, monkeypatch):
        """DIRECT_L1_ENABLED=false → legacy pipeline: один generate
        step='single', L1/L2-стадий нет, Decision Task не инжектится."""
        llm = _FakeLLM(single="обычный legacy ответ")
        svc, react, bot, msg, user = _drive(monkeypatch, "Почему?",
                                            llm=llm, l1=False)
        await svc.handle(bot, msg, user)
        assert llm.steps() == ["single"]
        svc._send_direct_answer.assert_awaited_once()
        assert svc._send_direct_answer.await_args.args[2] == \
            "обычный legacy ответ"

    @pytest.mark.asyncio
    async def test_l1_off_react_llm_line_still_armed(self, monkeypatch):
        """Legacy-паритет: при L1 OFF прежняя LLM REACT-линия (:2415-2475)
        доступна (armed через pre_action=REACT + reaction-флаги)."""
        llm = _FakeLLM(single='{"action": "REACT", "reaction": "😂", '
                             '"reason": "шутка"}')
        svc, react, bot, msg, user = _drive(monkeypatch, "АХАХА", llm=llm,
                                            l1=False)
        msg.message_id = 4242
        await svc.handle(bot, msg, user)
        # Decision Task ответил REACT-JSON → react, текст не отправлен.
        react.assert_awaited_once()
        svc._send_direct_answer.assert_not_awaited()


# ── Юнит: нормализация плана и capability-таблица ────────────────────────────


class TestL1PlanUnit:
    def test_normalize_never_raises_closed_sets(self):
        plan = _l1.normalize_l1_plan({
            "action": "REPLY", "extent": "чушь", "structure": "нет",
            "delivery_hint": "телепорт", "tool_policy": "всегда",
            "response_act": "  ЖИВНОЙ ОТВЕТ  ",
            "tone": "x" * 100, "emotional_mirroring": "сильно",
            "confidence": 5, "reaction": "🙃",
            "capabilities_needed": ["web_search", "", 42, "web_search"]})
        assert plan is not None
        assert plan.action == "reply"
        assert plan.extent == "auto"          # unknown → auto
        assert plan.structure == "chat"
        assert plan.delivery_hint == "plain"
        assert plan.tool_policy == "none"
        assert plan.response_act == "живной ответ"
        assert len(plan.tone) == _l1.TONE_MAX
        assert plan.emotional_mirroring == "none"
        assert plan.confidence == 1.0 and plan.confidence_bucket == "high"
        assert plan.reaction is None          # 🙃 не из allowed → None
        assert plan.capabilities_needed == ("web_search",)

    def test_normalize_invalid_action_none(self):
        assert _l1.normalize_l1_plan({"action": "dance"}) is None
        assert _l1.normalize_l1_plan({}) is None
        assert _l1.normalize_l1_plan("не dict") is None

    def test_confidence_buckets(self):
        assert _l1.confidence_bucket(0.1) == "low"
        assert _l1.confidence_bucket(0.5) == "medium"
        assert _l1.confidence_bucket(0.75) == "high"
        assert _l1.confidence_bucket(0.49) == "low"

    def test_fallback_plan_uses_classify(self):
        plan = _l1.fallback_plan("напиши фанфик про осень")
        assert plan.source == "fallback"
        assert plan.extent in _l1.L1_EXTENTS
        assert plan.action == "reply"

    def test_form_override_semantics(self):
        plan = _l1.normalize_l1_plan(_plan_dict(extent="detailed"))
        assert plan is not None
        plan.apply_form_override(_extent.explicit_form_override(
            "ответь одним словом"))
        assert plan.effective_extent() == "one_word"
        assert plan.to_response_plan().extent == "micro"

    def test_capability_table_exact_tool_names(self):
        from services.tool_schemas import TOOL_CALLING_TOOLS
        announced = {t["function"]["name"] for t in TOOL_CALLING_TOOLS}
        for cap, tools in _caps.CAPABILITY_TOOLS.items():
            for tool in tools:
                assert tool in announced, f"{cap} → {tool} не в tool_schemas"

    def test_capability_resolve_subset(self):
        resolved, rejected = _caps.resolve_capabilities(
            ["web_search", "chat_memory", "statistics", "мусор"],
            {"execute_web_search", "query_chat_memory"})
        assert resolved == ["execute_web_search", "query_chat_memory"]
        assert ("statistics", "no_tool") in rejected
        assert ("мусор", "unknown_capability") in rejected

    def test_capability_inactive_tool_rejected(self):
        resolved, rejected = _caps.resolve_capabilities(
            ["image_generation"], set())
        assert resolved == []
        assert rejected == [("image_generation", "tool_not_active")]
