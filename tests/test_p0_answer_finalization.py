"""P0 corrective (owner 2026-11-25) — финализация и прямая публикация.

Контракт (owner_inputs/2026-11-25-p0-intent-memory-answer-quality.md §4,
уточнение приёмки 2026-11-25):
* естественно-языковой ответ не формируется из захардкоженных шаблонов;
  код отвечает за фактическое состояние, речь — модель;
* инструмент, уже доставивший запрошенный результат, + пустой Writer →
  никакой повторной доставки/технической заглушки/ложного статуса
  незавершённого исследования;
* промежуточный успех инструмента ≠ выполнение запроса → используется
  существующий recovery (финальный Writer по evidence);
* все генеративные пути недоступны → честное состояние, без псевдо-ответа;
* готовая история Летописца публикуется только когда ОНА и есть запрошенный
  конечный продукт (structure=story / historical_recall), а не по `creative`
  или неопределённой интенции.

Двойники — только LLM/роутер; цикл/сервис/гейт — реальные.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from services import direct_chat_service as dcs
from services import direct_l1 as l1
from services import tool_loop
from services.llm_client import LLMChatResult, LLMError, LLMToolCall
from tests.test_asap7_direct_l1 import (
    _drive,
    _FakeRouter,
    _bot_reply,
    _plan_json,
)
from tests.test_smart_corrective_s7_reply import _ScriptedLLM

pytestmark = [pytest.mark.system2, pytest.mark.asap3]

MESSAGES = [{"role": "user", "content": "что мы решили по деплою?"}]
TOOLS = [{"type": "function", "function": {"name": "execute_web_search"}}]
CHAT_ID = -1001112223330


class _LoopLLM:
    """`generate_chat` — tool-раунды; `generate` — Writer финальной фазы."""

    def __init__(self, *, rounds, finalize_text="", finalize_error=None):
        self._rounds = list(rounds)
        self.finalize_text = finalize_text
        self.finalize_error = finalize_error
        self.finalize_calls = 0
        self.finalize_messages = []

    async def generate_chat(self, messages, *, tools=None, **kwargs):
        item = self._rounds.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        self.finalize_calls += 1
        self.finalize_messages.append(messages)
        if self.finalize_error is not None:
            raise self.finalize_error
        return self.finalize_text


class _Router:
    def __init__(self, outputs=None, default="данные инструмента"):
        self.outputs = dict(outputs or {})
        self.default = default
        self.dispatched = []

    async def dispatch(self, name, arguments, ctx):
        self.dispatched.append(name)
        return self.outputs.get(name, self.default)


def _tool_round(tool="execute_web_search", args='{"query": "x"}'):
    return LLMChatResult(content=None,
                         tool_calls=[LLMToolCall(id="c", name=tool,
                                                 arguments=args)],
                         finish_reason="tool_calls")


def _text_round(text):
    return LLMChatResult(content=text, tool_calls=None, finish_reason="stop")


# ── 1. Инструмент уже доставил результат + пустой Writer ────────────────────

class TestDeliveredArtifact:
    @staticmethod
    def _capture_f6(monkeypatch):
        """F6-производитель не должен видеть ход неотвеченным."""
        calls = []

        async def _spy(db, chat_id, query, message_id=None):
            calls.append((chat_id, query))

        monkeypatch.setattr(dcs, "_f6_maybe_create_unanswered_question", _spy)
        return calls

    @pytest.mark.asyncio
    async def test_question_mark_artifact_turn_is_answered_no_follow_up(
            self, monkeypatch):
        """P0-AQ-FIN-F6-DELIVERED-ARTIFACT (review r1): доставленный
        видео/файл-артефакт при пустом Writer'е — отвеченный ход. Сообщение с
        '?' не создаёт durable `unanswered_question` и второго текста."""
        calls = self._capture_f6(monkeypatch)
        payload = json.dumps({"status": "success",
                              "message": "Файл успешно загружен в чат"},
                             ensure_ascii=False)
        router = _FakeRouter(outputs={"download_media": payload})
        llm = _ScriptedLLM(
            l1=_plan_json(tool_policy="auto", delivery_hint="media",
                          capabilities_needed=["media_download"]),
            l2="",
            orchestrator=[
                json.dumps({"action": "call_tool",
                            "tool": "download_media",
                            "arguments": {"url": "https://cdn.example/v.mp4"},
                            "reason": "download"}),
                json.dumps({"action": "finish", "reason": "enough"}),
            ])
        svc, react, bot, msg, user = _drive(
            monkeypatch, "can you send this video?",
            reply=_bot_reply(), llm=llm, tool_router=router)

        await svc.handle(bot, msg, user)

        assert [d["tool"] for d in router.dispatched] == ["download_media"]
        assert calls == []                       # F6 follow_up не создан
        svc._send_direct_answer.assert_not_awaited()   # второго текста нет
        react.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unanswered_turn_still_produces_follow_up(self, monkeypatch):
        """F6 не отключён: ход без доставленного артефакта и без ответа
        по-прежнему даёт `unanswered_question` (негативный контроль)."""
        calls = self._capture_f6(monkeypatch)
        llm = _ScriptedLLM(l1=_plan_json(), l2="")
        svc, react, bot, msg, user = _drive(
            monkeypatch, "что мы решили по деплою?", llm=llm)

        await svc.handle(bot, msg, user)

        react.assert_awaited_once()
        svc._send_direct_answer.assert_not_awaited()
        assert len(calls) == 1 and calls[0][1] == "что мы решили по деплою?"

    @pytest.mark.asyncio
    async def test_text_stub_absent_and_no_duplicate_delivery(
            self, monkeypatch):
        """Сценарий A (owner): download_media доставил файл, Writer пуст →
        никакого технического отчёта и второй доставки."""
        payload = json.dumps({"status": "success",
                              "message": "Файл успешно загружен в чат"},
                             ensure_ascii=False)
        router = _FakeRouter(outputs={"download_media": payload})
        llm = _ScriptedLLM(
            l1=_plan_json(tool_policy="auto", delivery_hint="media",
                          capabilities_needed=["media_download"]),
            l2="",
            orchestrator=[
                json.dumps({"action": "call_tool",
                            "tool": "download_media",
                            "arguments": {"url": "https://cdn.example/v.mp4"},
                            "reason": "download"}),
                json.dumps({"action": "finish", "reason": "enough"}),
            ])
        svc, react, bot, msg, user = _drive(
            monkeypatch, "Надо лицо дотера в это солнышко",
            reply=_bot_reply(), llm=llm, tool_router=router)

        await svc.handle(bot, msg, user)

        # Инструмент реально вызван (доставка была), но второго текстового
        # сообщения и 🗿-реакции «незавершённого исследования» нет.
        assert [d["tool"] for d in router.dispatched] == ["download_media"]
        svc._send_direct_answer.assert_not_awaited()
        react.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tool_loop_marks_delivered_artifact_without_text(self):
        llm = _LoopLLM(rounds=[_tool_round("download_media", '{"url": "u"}'),
                               _text_round("")])
        router = _Router({"download_media": json.dumps(
            {"status": "success", "message": "Файл успешно загружен в чат"},
            ensure_ascii=False)})
        out = await tool_loop.chat_with_tools(
            llm, list(MESSAGES), tools=TOOLS, router=router, ctx=object(),
            chat_id=CHAT_ID)
        assert str(out) == ""
        assert out.finalize_mode == "delivered_artifact"
        assert tool_loop.media_delivered(out) is True


# ── 2. Промежуточный успех + пустой Writer → recovery, не «выполнено» ───────

class TestIntermediateSuccess:
    @pytest.mark.asyncio
    async def test_recovery_writer_called_and_not_treated_as_fulfilment(self):
        llm = _LoopLLM(rounds=[_tool_round(), _text_round("")],
                       finalize_text="")
        router = _Router({"execute_web_search": "черновые данные"})
        out = await tool_loop.chat_with_tools(
            llm, list(MESSAGES), tools=TOOLS, router=router, ctx=object(),
            chat_id=CHAT_ID)
        # Существующий recovery-путь реально вызван (Writer по evidence).
        assert llm.finalize_calls == 1
        payload_text = "\n".join(str(m.get("content") or "")
                                 for m in llm.finalize_messages[0])
        assert "черновые данные" in payload_text
        assert "Причина остановки" in payload_text
        # Побочный успех не выдаётся ни за доставленный артефакт, ни за ответ.
        assert out.finalize_mode == "no_generative_path"
        assert tool_loop.media_delivered(out) is False
        assert str(out) == ""

    @pytest.mark.asyncio
    async def test_partial_research_with_working_llm_is_model_written(self):
        """Часть данных + рабочий Writer → ответ модели, без шаблона."""
        llm = _LoopLLM(rounds=[_tool_round(), LLMError("upstream 500")],
                       finalize_text="По деплою: сначала упал шаг сборки.")
        router = _Router({"execute_web_search": "deploy failed at build"})
        out = await tool_loop.chat_with_tools(
            llm, list(MESSAGES), tools=TOOLS, router=router, ctx=object(),
            chat_id=CHAT_ID)
        assert str(out) == "По деплою: сначала упал шаг сборки."
        assert out.finalize_mode == "llm"


# ── 3. Генеративного пути нет → честное состояние, без хардкода ─────────────

class TestNoGenerativePath:
    @pytest.mark.asyncio
    async def test_honest_state_and_no_programmatic_text(self):
        llm = _LoopLLM(rounds=[_tool_round(), LLMError("down")],
                       finalize_error=LLMError("writer down"))
        router = _Router({"execute_web_search": "данные"})
        out = await tool_loop.chat_with_tools(
            llm, list(MESSAGES), tools=TOOLS, router=router, ctx=object(),
            chat_id=CHAT_ID)
        text = str(out)
        assert llm.finalize_calls == 1
        assert text == ""
        assert out.finalize_mode == "no_generative_path"
        assert out.degraded is True
        assert out.research_state.get("status") in ("partial", "failed")
        for marker in ("Исследование остановлено", "Это частичный результат",
                       "Подтверждённые данные", "Непроверено",
                       "сохранены в журнале"):
            assert marker not in text

    def test_failure_state_has_no_conversational_text(self):
        state = tool_loop.failure_state(
            "empty", [{"tool": "execute_web_search", "status": "error",
                       "error_code": "provider_unavailable", "output": ""}])
        assert state["status"] == "no_generative_path"
        assert state["failed_tools"] == ["execute_web_search"]
        assert "Запрос:" not in str(state)


# ── 4. Летописец: публикация только по соответствию конечной цели ───────────

def _ctx(story="<b>История про мем</b>"):
    from services.tool_router import ToolContext
    ctx = ToolContext(CHAT_ID, "расскажи про мем")
    ctx.lore_compiled = True
    ctx.lore_story = story
    return ctx


def _plan(act, structure):
    return l1.normalize_l1_plan({
        "action": "reply", "response_act": act, "structure": structure,
        "tool_policy": "auto", "capabilities_needed": ["historical_search"]})


class TestLorePublicationGate:
    def test_requested_story_is_published(self):
        assert dcs.lore_story_override(
            _ctx(), _plan("historical_recall", "chat"))
        assert dcs.lore_story_override(_ctx(), _plan("creative", "story"))

    @pytest.mark.parametrize("act,structure", [
        ("creative", "chat"),          # творческий акт без story-формы
        ("answer", "chat"),            # неопределённая интенция
        ("research", "explanation"),   # анализ: история — материал
    ])
    def test_not_requested_product_is_context_not_answer(self, act, structure):
        assert dcs.lore_story_override(_ctx(), _plan(act, structure)) == ""

    def test_no_plan_is_not_permission(self):
        assert dcs.lore_story_override(_ctx(), None, None) == ""
        assert dcs.lore_verbatim_allowed(None, None) is False

    def test_unknown_intent_does_not_get_ready_lore_story(self):
        plan = _plan("answer", "chat")
        assert l1.lore_story_delivery_allowed(plan) is False
        assert dcs.lore_verbatim_allowed(plan) is False


# ── 5. Механизм удалён (а не переписан другими словами) ─────────────────────

def test_no_hardcoded_finalization_publisher_left():
    root = pathlib.Path(__file__).resolve().parents[1]
    loop_src = (root / "services/tool_loop.py").read_text(encoding="utf-8")
    direct_src = (root / "services/direct_chat_service.py").read_text(
        encoding="utf-8")
    for marker in ("Исследование остановлено", "Это частичный результат",
                   "Подтверждённые данные (результаты инструментов)",
                   "Полные результаты вызовов сохранены"):
        assert marker not in loop_src, marker
    assert "structured_partial_from_result" not in loop_src
    assert "structured_partial_from_result" not in direct_src
    assert "TOOL_LOOP_FALLBACK_PHRASE" not in loop_src
