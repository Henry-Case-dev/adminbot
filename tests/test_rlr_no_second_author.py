# -*- coding: utf-8 -*-
"""RLR-02-LEGACY — второй автор текста в Direct удалён физически.

Источник: `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md`
(R-00.1, R-00.2, R-02.1…R-02.5, R-FAIL.4) и карта
`plans/features/remove-legacy-rephrasing/requirements-map.json` (срез
RLR-02-LEGACY).

Что доказывается (и чем это может упасть):

1. **(а) Один автор при ``SYSTEM2_DIRECT_ENABLED=true``.** Ход с успешным
   tool-loop и выключенным L1 даёт РОВНО ОДИН смысловой текст: финал
   tool-loop доставляется как есть, ни один `llm.generate` не вызывается,
   стадий `stage1`/`stage2` нет. Если вернуть legacy-вызов
   `_synthesize_direct_answer` на гейт — счётчик вызовов и доставленный текст
   меняются, тест краснеет.
2. **(б) Ошибка L2 не уходит в legacy-текст.** Падение провайдера на L2 даёт
   честную фразу недоступности; черновик, существовавший ДО Writer, не
   публикуется, второй автор не запускается.
3. **(в) Факты инструментов доходят до единственного Writer'а.** Payload L2
   содержит пакет `Tool_Evidence` с атрибуцией источника и самой находкой —
   то есть нормализация фактов живёт ДО генерации, а не в удалённой Stage-1.
4. **(г) Специализированные пайплайны сохранили свою финальную стадию.**
   Фактчек по-прежнему строит свой итоговый текст из JSON аналитика: его
   `verbalize_validated` вызывается один раз и получает `СПРАВКА (JSON)`.

ЧЕГО ЭТОТ ФАЙЛ НЕ ДОКАЗЫВАЕТ (честная граница): живой прогон на реальном
провайдере и сравнение `raw_final` ↔ отправленного Telegram-payload — это
RLR-07-PROOF; полнота сценариев саммари/мемов — их собственные наборы.

TEST-LIFECYCLE: CONTRACT + REGRESSION owner=RLR-02-LEGACY
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services.direct_chat_service import DirectChatService
from services.llm_client import LLMError
from services.smartmodule_phrases import CHAT_ERROR_PHRASES
from services.tool_loop import ToolLoopResult
from tests.test_asap7_direct_l1 import _FakeLLM, _FakeRouter, _drive, _plan_json
from tests.test_direct_chat import _bot, _make_service, _message, _user

pytestmark = [pytest.mark.system2, pytest.mark.asap3]

_TOOL_TRACE = [{"round": 1, "tool": "execute_web_search", "ok": True,
                "out_chars": 20}]


def _tool_final(text="финал tool-loop", *, tool_context="сырые логи"):
    return ToolLoopResult(text, rounds_used=2, tool_trace=_TOOL_TRACE,
                          tool_context=tool_context)


def _legacy_off_drive(monkeypatch, raw, *, flag=True, llm=None,
                      tool_router_present=True):
    """Ход с выключенным L1 — тот самый маршрут, где жил второй автор."""
    import services.direct_chat_service as dcs
    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", False)
    if flag is not None:
        monkeypatch.setattr(Settings, "SYSTEM2_DIRECT_ENABLED", flag)
    llm = llm if llm is not None else _FakeLLM(single="ВТОРОЙ АВТОР")
    svc = _make_service(
        tool_router=MagicMock() if tool_router_present else None, llm=llm)
    svc._send_direct_answer = AsyncMock(return_value=999)
    svc.remember_bot_reply = AsyncMock()

    async def fake_chat_with_tools(llm_, payload, *, tools, router, ctx,
                                   temperature, chat_id=None, **kwargs):
        return raw

    monkeypatch.setattr(dcs, "chat_with_tools", fake_chat_with_tools)
    react = AsyncMock()
    monkeypatch.setattr(dcs, "react_moai", react)
    return svc, react, _bot(), _message(text="Бот, загугли новости"), _user()


class TestNoSecondAuthor:
    """(а) — ни один флаг не даёт второго смыслового прохода."""

    @pytest.mark.asyncio
    async def test_flag_on_l1_off_tool_loop_is_the_only_author(
            self, monkeypatch):
        raw = _tool_final()
        llm = _FakeLLM(single="ВТОРОЙ АВТОР")
        svc, _react, bot, msg, user = _legacy_off_drive(
            monkeypatch, raw, flag=True, llm=llm)
        await svc.handle(bot, msg, user)
        # Ровно одна доставка и ровно тот текст, который родился в tool-loop.
        svc._send_direct_answer.assert_awaited_once()
        assert svc._send_direct_answer.await_args.args[2] == "финал tool-loop"
        # Никакой второй генерации: ни Stage-1 «справки», ни Stage-2 речи.
        assert llm.steps() == [], f"лишние LLM-стадии: {llm.steps()}"
        assert "stage1" not in llm.steps() and "stage2" not in llm.steps()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("flag", [True, False, None])
    async def test_no_flag_value_restores_a_second_writer(self, monkeypatch,
                                                         flag):
        raw = _tool_final()
        llm = _FakeLLM(single="ВТОРОЙ АВТОР")
        svc, _react, bot, msg, user = _legacy_off_drive(
            monkeypatch, raw, flag=flag, llm=llm)
        await svc.handle(bot, msg, user)
        assert svc._send_direct_answer.await_args.args[2] == "финал tool-loop"
        assert llm.steps() == []

    @pytest.mark.asyncio
    async def test_missing_tool_capability_single_call_path_too(
            self, monkeypatch):
        """Инструментов нет вовсе — тоже один автор, без псевдо-справки."""
        llm = _FakeLLM(single="единственный ответ")
        svc, _react, bot, msg, user = _legacy_off_drive(
            monkeypatch, None, flag=True, llm=llm,
            tool_router_present=False)
        await svc.handle(bot, msg, user)
        svc._send_direct_answer.assert_awaited_once()
        assert llm.steps() == ["single"], llm.steps()
        assert svc._send_direct_answer.await_args.args[2] == "единственный ответ"

    def test_legacy_entrypoints_do_not_exist(self):
        """Структурная граница: ни функции, ни JSON-парсера справки в модуле."""
        assert not hasattr(DirectChatService, "_synthesize_direct_answer")
        import services.direct_chat_service as dcs
        src = open(dcs.__file__, encoding="utf-8").read()
        assert "_synthesize_direct_answer" not in src.replace(
            "_synthesize_direct_answer` (Stage-1", "")
        assert "parse_direct_synthesis(" not in src
        assert "stage2_payload(" not in src

    def test_flag_has_no_consumer_in_active_graph(self):
        """Ключ читаем, но в активном графе сервиса его никто не спрашивает."""
        import services.direct_chat_service as dcs
        src = open(dcs.__file__, encoding="utf-8").read()
        code_lines = [ln for ln in src.splitlines()
                      if "SYSTEM2_DIRECT_ENABLED" in ln
                      and not ln.lstrip().startswith("#")]
        assert code_lines == [], code_lines


class TestNoLegacyFallbackFromL2:
    """(б) — ошибка L2 диагностируется, но не подменяется legacy-текстом."""

    @pytest.mark.asyncio
    async def test_provider_error_is_honest_not_draft_not_second_author(
            self, monkeypatch):
        llm = _FakeLLM(l1=_plan_json(), l2="не дошло")

        async def exploding_generate(messages, temperature=None, chat_id=None,
                                     module=None, step=None,
                                     correlation_id=None, **kwargs):
            llm.calls.append({"step": step, "messages": messages,
                              "kwargs": kwargs})
            if step == "l1_planner":
                return _plan_json()
            raise LLMError("провайдер недоступен")

        llm.generate = exploding_generate
        svc, _react, bot, msg, user = _drive(
            monkeypatch, "сравни с тем, что писали вчера", llm=llm,
            tool_router=_FakeRouter())
        svc._l1_tool_phase = AsyncMock(return_value=_tool_final(
            "ЧЕРНОВИК ДО WRITER"))
        await svc.handle(bot, msg, user)

        # L2 действительно упал (одна финальная генерация пыталась и умерла).
        assert llm.steps() == ["l1_planner", "l2_writer"], llm.steps()
        # Черновик, существовавший до Writer, НЕ публикуется.
        sent_texts = [str(c.args[1]) for c in bot.send_message.await_args_list
                      if len(c.args) > 1]
        assert all("ЧЕРНОВИК ДО WRITER" not in t for t in sent_texts), sent_texts
        # Второго автора нет: legacy-стадий в шагах LLM не было.
        assert "stage1" not in llm.steps() and "stage2" not in llm.steps()
        # Честное сообщение недоступности пользователю ушло.
        assert any(any(p in t for p in CHAT_ERROR_PHRASES)
                   for t in sent_texts), sent_texts


class TestToolFactsReachTheSingleWriter:
    """(в) — нормализация фактов инструментов живёт ДО L2."""

    @pytest.mark.asyncio
    async def test_evidence_pack_delivered_to_l2_with_attribution(
            self, monkeypatch):
        router = _FakeRouter(outputs={
            "execute_web_search": "завтра дождь, 12 градусов"})
        llm = _FakeLLM(
            l1=_plan_json(tool_policy="auto",
                          capabilities_needed=["web_search"]),
            l2="завтра дождь, бери зонт")
        svc, _react, bot, msg, user = _drive(
            monkeypatch, "проверь в интернете погоду на завтра",
            tool_router=router, llm=llm)
        await svc.handle(bot, msg, user)

        # Финальный Writer — ровно один, и это единственная смысловая стадия
        # после L1-плана.
        assert llm.steps() == ["l1_planner", "l2_writer"], llm.steps()
        payload = "".join(str(m.get("content"))
                          for m in llm.last_messages("l2_writer"))
        assert "<Tool_Evidence>" in payload
        # Сама находка и её атрибуция (источник/статус) доехали до Writer'а.
        assert "завтра дождь, 12 градусов" in payload
        assert "[ИСТОЧНИК 1 | execute_web_search | ok | " in payload
        assert "дата публикации не сообщается источником" in payload
        svc._send_direct_answer.assert_awaited_once()
        assert svc._send_direct_answer.await_args.args[2] == \
            "завтра дождь, бери зонт"


class TestSpecialisedPipelinesKeepTheirOwnFinalStage:
    """(г) — фактчек сохранил собственный финальный текстовый этап."""

    @pytest.mark.asyncio
    async def test_factcheck_two_call_still_produces_own_final_text(
            self, monkeypatch):
        from tests.test_asap_fc_voice01_verbalizer import (
            CHAT_ID, _analyst_json, _two_call)
        service, cap = _two_call(monkeypatch, _analyst_json())
        await service._check_claim_two_call(
            "тезис", "USER", "", "RESULTS", CHAT_ID, 1000)
        # Ровно один финальный текстовый этап фактчека, и он получает
        # машинную справку аналитика — специализированный пайплайн цел.
        assert cap.calls == 1
        assert cap.messages[1]["content"].startswith("АНАЛИЗ (JSON):")

    def test_specialised_modules_untouched_by_this_slice(self):
        """Direct-демонтаж не задел саммари/мемы: их стадии на месте."""
        from services import summary_generator
        src = open(summary_generator.__file__, encoding="utf-8").read()
        assert "step=\"stage2\"" in src
        assert "step=\"stage1\"" in src
