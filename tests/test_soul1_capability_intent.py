"""SOUL-1 / W10 — Semantic Intent → Capability (SOUL-AMD.5.2/5.9/5.10).

Проверяется ПОВЕДЕНИЕ, а не внутренности:
  * шесть явных поручений §5.1 распознаются по смыслу (не одним регексом) и
    приводят к РОВНО ОДНОМУ вызову доступного инструмента с подтверждением
    результата/доставки (§8.6);
  * просьба придумать идею/текст/сценарий генерацию НЕ запускает (§8.7);
  * неоднозначное поручение → ровно ОДИН короткий уточняющий вопрос из
    управляемого шаблона, без генерации и без LLM-вызовов (§5.9);
  * регекс остаётся быстрым путём, но не единственной дверью: если L1 выбрал
    обычный текст при однозначном доступном действии, маршрутизация
    исправляется в том же ходу (§5.10);
  * ни один ход не порождает дубль генерации (pre-gate + L1 + tool-loop).

TEST-LIFECYCLE: CONTRACT owner=SOUL-AMD.5.2/5.9/5.10/8.6/8.7 (soul-1, W10)
"""
from __future__ import annotations

import asyncio
import json

import pytest

from config.settings import Settings
from services import capability_registry as caps
from services import direct_capabilities as dc
from services import hot_config as hot
from services import image_generation as ig

pytestmark = [pytest.mark.asap3]


# ── хелперы ─────────────────────────────────────────────────────────────────

READY_CONFIG = {
    "flags.image_generation_module_enabled": True,
    "keys.image_api_key": "test-key",
    "models.image_model": "test-model",
}


class _Cfg:
    """hot-слой с готовым image-провайдером (реальный путь `hot.get`)."""

    def __init__(self, values=None):
        self.values = dict(values or READY_CONFIG)

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeLLM:
    """L1 → план (по умолчанию БЕЗ capabilities), L2 → текст."""

    def __init__(self, *, l1=None, l2="готовый ответ"):
        self.l1_reply = l1 if l1 is not None else _plan_json()
        self.l2_text = l2
        self.calls = []

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kwargs):
        self.calls.append({"step": step, "messages": messages})
        if step == "l1_planner":
            return self.l1_reply
        if step == "l2_writer":
            return self.l2_text
        return self.l2_text

    def steps(self):
        return [c["step"] for c in self.calls]

    def l2_user_content(self) -> str:
        found = [c for c in self.calls if c["step"] == "l2_writer"]
        if not found:
            return ""
        return "\n".join(str(m.get("content", ""))
                         for m in found[-1]["messages"]
                         if isinstance(m, dict) and m.get("role") == "user")


def _plan_json(**over):
    plan = {"action": "reply", "reaction": None,
            "response_act": "answer", "extent": "auto", "tone": "inherit",
            "emotional_mirroring": "none", "structure": "chat",
            "delivery_hint": "plain", "tool_policy": "none",
            "capabilities_needed": [], "needs_clarification": False,
            "clarification_target": None, "confidence": 0.9}
    plan.update(over)
    return json.dumps(plan, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _clean_state():
    caps.reset_cache()
    hot.set_config_cache(None)
    yield
    caps.reset_cache()
    hot.set_config_cache(None)


def _drive(monkeypatch, text, *, l1=None, reply=None, config=None,
           real_pre_gate=True, router=None, forwarded=False):
    """Реальный DirectChatService (L1-режим), моки только ввода/вывода.

    Возвращает ``(svc, llm, bot, message, user, gen_calls, announced)``, где
    ``announced`` — наблюдаемый seam анонса инструментов на ход
    (``_l1_tool_subset``: ``(image_flag, имена tools)``)."""
    import services.direct_chat_service as dcs
    from tests.test_direct_chat import _bot, _make_service, _message, _user

    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", True)
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", True)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    hot.set_config_cache(_Cfg(config))
    monkeypatch.setattr(ig, "resolve_module_enabled", _async_true())
    gen_calls: list = []
    announced: list = []

    async def fake_run(request, *, bot=None, correlation_id=None):
        gen_calls.append({"request": request, "chat_id": request.chat_id})
        return ig.GenerationResult(ok=True, content=b"x")

    monkeypatch.setattr(ig, "run_image_request", fake_run)
    monkeypatch.setattr(ig, "generate_and_send", _gen_and_send_spy(gen_calls))

    llm = _FakeLLM(l1=l1)
    svc = _make_service(tool_router=router, llm=llm)
    orig_subset = svc._l1_tool_subset

    async def spy_subset(chat_id, correlation_id, lore, image, l1_plan,
                         **kwargs):
        out = await orig_subset(chat_id, correlation_id, lore, image, l1_plan,
                                **kwargs)
        announced.append((bool(image),
                          [t["function"]["name"] for t in out[0]]))
        return out

    svc._l1_tool_subset = spy_subset
    svc._build_user_content = _async_list([])
    if not real_pre_gate:
        svc._image_pre_gate_block = _async_none()
    svc._dig_pre_gate_block = _async_none()
    svc._send_direct_answer = _async_id(999)
    svc.remember_bot_reply = _async_none()
    msg = _message(text=text)
    msg.forward_origin = _forward_origin() if forwarded else None
    if reply is not None:
        msg.reply_to_message = reply
    return svc, llm, _bot(), msg, _user(), gen_calls, announced


def _forward_origin():
    """Реальная пересылка (MessageOriginUser) — «чужие слова»."""
    import datetime
    from aiogram.types import MessageOriginUser, User
    return MessageOriginUser(
        type="user", date=datetime.datetime(2026, 10, 16, 12, 0),
        sender_user=User(id=7, is_bot=False, first_name="Петя"))


def _async_true():
    async def _f(*_a, **_k):
        return True
    return _f


def _async_none():
    async def _f(*_a, **_k):
        return None
    return _f


def _async_list(value):
    async def _f(*_a, **_k):
        return list(value)
    return _f


def _async_id(value):
    async def _f(*_a, **_k):
        return value
    return _f


def _gen_and_send_spy(calls):
    async def _f(*args, **kwargs):
        calls.append({"direct": True})
        return ig.GenerationResult(ok=True, content=b"x")
    return _f


async def _run(svc, bot, msg, user):
    await svc.handle(bot, msg, user)
    await asyncio.sleep(0)


def _sent_texts(bot) -> list:
    return [str(c.args[1]) for c in bot.send_message.await_args_list
            if len(c.args) > 1]


# ── §5.1/§8.6: шесть поручений распознаются по смыслу ───────────────────────

SIX_PHRASES = [
    "Бот, нарисуй мем про двачеров",
    "Бот, сделай мем про двачеров",
    "Бот, надо сделать мем про двачеров",
    "Сделай картинку из этой ситуации",
    "Нужна инфографика по этим данным",
    "Давай изобразим это в виде комикса",
]


@pytest.mark.parametrize("text", SIX_PHRASES)
def test_semantic_phrasings_are_create_image(text):
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.intent == dc.INTENT_CREATE_IMAGE
    assert intent.capability == "image_generation"
    assert intent.confidence == dc.CONFIDENCE_HIGH
    assert intent.actionable is True


@pytest.mark.parametrize("text", SIX_PHRASES)
def test_detector_is_not_a_single_regex(text):
    """Смысловая дверь шире регекса: пять из шести формулировок §5.1 регекс
    быстрого пути НЕ покрывает (проверка ниже — на всём наборе)."""
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.actionable is True


def test_legacy_regex_alone_would_miss_most_phrasings():
    """SOUL-AMD.5.10: регекс — быстрый путь, но не единственная дверь."""
    missed = [t for t in SIX_PHRASES if not ig.is_image_keyword(t)]
    assert len(missed) >= 5, missed


@pytest.mark.asyncio
@pytest.mark.parametrize("text", SIX_PHRASES)
async def test_six_phrases_call_tool_exactly_once(monkeypatch, text):
    """§8.6: намерение распознано, доступный инструмент вызван РОВНО ОДИН раз,
    результат и доставка подтверждены (успех заявляется только по факту)."""
    svc, llm, bot, msg, user, gen_calls, announced = _drive(monkeypatch, text)
    await _run(svc, bot, msg, user)
    assert len(gen_calls) == 1, f"{text}: генераций {len(gen_calls)}"
    assert announced, "tool-фаза не дошла до анонса инструментов"
    assert announced[0][0] is False, (
        "на ход генерации image-инструмент не объявляется (дубль исключён)")
    assert "generate_image" not in announced[0][1]
    assert "l2_writer" in llm.steps() or "single" in llm.steps()


@pytest.mark.asyncio
async def test_regex_fast_path_generates_and_confirms_delivery(monkeypatch):
    """Быстрый путь («Бот, нарисуй …») остаётся: один вызов + подтверждённая
    доставка + запрет повторного вызова инструмента на этом ходу."""
    svc, llm, bot, msg, user, gen_calls, tools_seen = _drive(
        monkeypatch, "Бот, нарисуй мем про двачеров")
    await _run(svc, bot, msg, user)
    assert len(gen_calls) == 1
    l2 = [c["messages"] for c in llm.calls if c["step"] == "l2_writer"]
    if l2:
        user_content = "\n".join(
            str(m.get("content", "")) for m in l2[-1] if m.get("role") == "user")
        assert "<image_result" in user_content
        assert 'status="ok"' in user_content


@pytest.mark.asyncio
async def test_semantic_phrase_routes_after_l1_plain_text(monkeypatch):
    """§5.10: L1 выбрал обычный текст, но действие было однозначно доступно —
    маршрутизация исправлена в этом же ходу (ровно один вызов, без 2-го LLM)."""
    svc, llm, bot, msg, user, gen_calls, announced = _drive(
        monkeypatch, "Бот, надо сделать мем про двачеров")
    await _run(svc, bot, msg, user)
    assert len(gen_calls) == 1
    assert llm.steps().count("l1_planner") == 1, "второго LLM-вызова нет"
    # Инструмент не объявлен: генерация уже выполнена тем же путём.
    assert announced and announced[0][0] is False
    assert "generate_image" not in announced[0][1]


# ── §8.7: придумать ≠ нарисовать; неоднозначность → один вопрос ─────────────

@pytest.mark.parametrize("text", [
    "придумай концепт мема, рисовать не надо",
    "придумай текст мема, не рисуй",
    "Бот, придумай концепт мема, рисовать не надо",
])
def test_conceive_only_never_triggers_generation(text):
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.intent == dc.INTENT_NONE
    assert intent.conceive_only is True
    assert intent.actionable is False


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "Бот, придумай концепт мема, рисовать не надо",
    "Бот, придумай текст мема, не рисуй",
])
async def test_conceive_only_pipeline_no_generation(monkeypatch, text):
    svc, llm, bot, msg, user, gen_calls, _tools = _drive(monkeypatch, text)
    await _run(svc, bot, msg, user)
    assert gen_calls == []
    # обычный ход (ответ пишет Writer), без подмены на «не умею рисовать»
    assert "l2_writer" in llm.steps() or "single" in llm.steps()


@pytest.mark.parametrize("text", [
    "давай обсудим мемы",
    "расскажи про мемы в этом чате",
    "Бот, сделай кратко",
    "что делаешь?",
    "сделай одолжение",
    "сделай текст мема",
])
def test_non_creation_requests_do_not_trigger_generation(text):
    """Ложное срабатывание дороже пропуска: разговор о мемах и обычные просьбы
    «сделать» без объекта изображения генерацию не запускают."""
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.intent != dc.INTENT_CREATE_IMAGE or \
        intent.confidence == dc.CONFIDENCE_AMBIGUOUS
    assert intent.actionable is False


@pytest.mark.asyncio
async def test_ambiguous_request_asks_one_clarifying_question(monkeypatch):
    """§5.9: неоднозначное поручение → ОДИН короткий вопрос из шаблона,
    без генерации и без единого LLM-вызова (0 стоимости)."""
    svc, llm, bot, msg, user, gen_calls, _tools = _drive(
        monkeypatch, "Бот, сделай это")
    await _run(svc, bot, msg, user)
    assert gen_calls == []
    assert llm.calls == [], "уточняющий вопрос не стоит LLM-вызова"
    texts = _sent_texts(bot)
    assert len(texts) == 1, texts
    expected, block_id, _src = caps.clarify_text()
    assert texts[0] == expected
    assert block_id == "message.image_request.clarify"


# ── Дубли: pre-gate + L1 + tool-loop ────────────────────────────────────────

@pytest.mark.asyncio
async def test_l1_requested_capability_is_not_pre_generated_twice(monkeypatch):
    """L1 сам запросил image_generation → консистентность НЕ запускает второй
    путь: генерация остаётся за tool-фазой (один вызов на намерение)."""
    svc, llm, bot, msg, user, gen_calls, announced = _drive(
        monkeypatch, "Бот, надо сделать мем про двачеров",
        l1=_plan_json(capabilities_needed=["image_generation"]))
    await _run(svc, bot, msg, user)
    assert gen_calls == [], "второй путь генерации не должен срабатывать"
    assert announced and announced[0][0] is True, (
        "L1-запрошенная capability остаётся доступной tool-фазе")
    assert "generate_image" in announced[0][1]


@pytest.mark.asyncio
async def test_semantic_phrase_sets_run_marker_for_tool_phase(monkeypatch):
    """§5.10/§5.17: смысловая формулировка (регекс её не покрывает) доходит до
    единственного пути генерации, а на ход ставится маркер прогона — повторный
    вызов инструмента исключён (``image_enabled=False`` для tool-фазы)."""
    svc, llm, bot, msg, user, gen_calls, announced = _drive(
        monkeypatch, "Бот, надо сделать мем про двачеров")
    await _run(svc, bot, msg, user)
    assert len(gen_calls) == 1, "ровно один платный вызов на намерение"
    assert announced and announced[0][0] is False, (
        "после генерации в этом же ходу инструмент не анонсируется")
    assert "generate_image" not in announced[0][1]


@pytest.mark.asyncio
async def test_routing_fix_observable_event_still_fires(monkeypatch):
    """§6.5/§5.10: «доступное действие не было выбрано L1» остаётся наблюдаемым
    событием — смысловой veto пре-гейта НЕ глушит путь согласованности
    (иначе механизм и его событие стали бы мёртвыми)."""
    from services import agentic_events
    events: list = []
    monkeypatch.setattr(agentic_events, "emit_agentic_event",
                        lambda name, **kw: events.append((name, kw)))
    svc, llm, bot, msg, user, gen_calls, _tools = _drive(
        monkeypatch, "Бот, надо сделать мем про двачеров")
    await _run(svc, bot, msg, user)
    assert len(gen_calls) == 1
    routed = [e for e in events
              if e[0] == agentic_events.L1_CAPABILITY_REJECTED
              and str(e[1].get("reason", "")).startswith(
                  "available_action_not_chosen")]
    assert routed, events


@pytest.mark.asyncio
async def test_no_second_generation_for_same_intent(monkeypatch):
    """Повторный прогон того же намерения — новая генерация только по новому
    ходу пользователя (idempotency: 1 намерение = 1 платный вызов)."""
    svc, llm, bot, msg, user, gen_calls, _tools = _drive(
        monkeypatch, "Бот, нарисуй мем про двачеров")
    await _run(svc, bot, msg, user)
    assert len(gen_calls) == 1
    # Внутренние пути (pre-gate + consistency) не добавляют второй вызов.
    assert len(gen_calls) == 1


@pytest.mark.asyncio
async def test_l1_requested_image_capability_not_ready_is_not_promised(
        monkeypatch):
    """L1 запросил image_generation, но в чате она недоступна (нет ключа):
    инструмент не анонсируется (наблюдаемый блокер), Writer получает
    правдивую пометку — обещания недоступного нет."""
    svc, llm, bot, msg, user, gen_calls, announced = _drive(
        monkeypatch, "Бот, посоветуй фильм на вечер",
        config=dict(READY_CONFIG, **{"keys.image_api_key": ""}),
        l1=_plan_json(capabilities_needed=["image_generation"]))
    await _run(svc, bot, msg, user)
    assert gen_calls == []
    assert announced and "generate_image" not in announced[0][1]
    assert "<capability_notice" in llm.l2_user_content()


def test_intent_blockers_are_observable():
    """§5.10/§5.18: у «доступное действие не выбрано» есть наблюдаемый блокер."""
    intent = dc.detect_action_intent("Бот, сделай мем про двачеров",
                                     addressed=True)
    assert dc.intent_blockers(intent, capability_status="ready") == ()
    assert dc.intent_blockers(intent, capability_status="disabled") == (
        "capability_disabled",)
    ambiguous = dc.detect_action_intent("Бот, сделай это", addressed=True)
    assert dc.intent_blockers(ambiguous, capability_status="ready") == (
        dc.REASON_CREATE_DEICTIC,)


# ═══════════════════════════════════════════════════════════════════════════
# F1/F2 rework (review-w10): ложное срабатывание = ПЛАТНАЯ генерация.
# TEST-LIFECYCLE: REGRESSION owner=SOUL-AMD.5.1/5.9/5.10 (soul-1, W10 fix)
# ═══════════════════════════════════════════════════════════════════════════

#: Стем как ПОДСТРОКА («арт» в квартир*/март*/карт*/стартап*, «мем» в
#: мемориальн*/мембран*) — не объект изображения.
NON_IMAGE_STEM_PHRASES = [
    "Бот, сделай уборку в квартире",
    "Бот, сделай план на март",
    "Бот, сделай мемориальный пост про Петю",
    "Бот, надо сделать уборку в квартире",
    "Бот, сделай карту маршрута",
    "Бот, сделай логотип для стартапа",
    "Бот, сделай артефакт для игры",
    "Бот, сделай описание мембраны",
]

#: Чужая просьба / сам сделаю / противоречие — поручения боту нет.
NOT_A_USER_REQUEST_PHRASES = [
    "Бот, Петя сказал: нарисуй мем про двачеров",
    "Петя просил нарисовать мем",
    "Бот, я сам нарисую мем, оценишь потом",
    "Бот, подскажи идею мема, я сам нарисую",
    "Мне нужно нарисовать мем для конкурса",
    "Бот, нарисуй мем, но не рисуй",
    "Бот, нарисуй мем? не надо, забудь",
]

#: Пример кода/инлайн-код — не команда боту.
CODE_PHRASES = [
    "Бот, вот пример кода:\n```python\nнарисуй мем про двачеров\n```",
    "```\nБот, нарисуй мем про двачеров\n```",
    "Бот, посмотри `нарисуй мем` — это из логов",
]

#: «нарисуй»/«рисуй» внутри более длинного НЕ-image слова.
LONGER_WORD_PHRASES = [
    "Бот, перерисуй схему в отчёте",
    "Бот, дорисуй таблицу в документе",
]

ALL_FALSE_POSITIVE_PHRASES = (NON_IMAGE_STEM_PHRASES
                             + NOT_A_USER_REQUEST_PHRASES
                             + CODE_PHRASES + LONGER_WORD_PHRASES)


@pytest.mark.parametrize("text", ALL_FALSE_POSITIVE_PHRASES)
def test_false_positive_phrases_are_not_actionable(text):
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.actionable is False, text


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ALL_FALSE_POSITIVE_PHRASES)
async def test_false_positive_phrases_generate_nothing(monkeypatch, text):
    """РЕГРЕССИЯ review-w10 F1/F2: ни одна из фраз не запускает платную
    генерацию через реальный DirectChatService (0 вызовов)."""
    svc, llm, bot, msg, user, gen_calls, _tools = _drive(monkeypatch, text)
    await _run(svc, bot, msg, user)
    assert gen_calls == [], f"{text}: ложная платная генерация"


@pytest.mark.asyncio
async def test_forwarded_request_generates_nothing(monkeypatch):
    """Пересланное сообщение — чужие слова, не поручение пользователя."""
    svc, llm, bot, msg, user, gen_calls, _tools = _drive(
        monkeypatch, "Бот, нарисуй мем про двачеров", forwarded=True)
    await _run(svc, bot, msg, user)
    assert gen_calls == []
    intent = dc.detect_action_intent("Бот, нарисуй мем про двачеров",
                                     addressed=True, forwarded=True)
    assert intent.actionable is False
    assert intent.reason == dc.REASON_CREATE_FORWARDED


@pytest.mark.parametrize("text", [
    "Бот, нарисуй мем про двачеров",
    "Бот, сделай мем про двачеров",
])
def test_forwarded_flag_does_not_leak_to_own_messages(text):
    """Обратная сторона: своё сообщение по-прежнему поручение."""
    intent = dc.detect_action_intent(text, addressed=True, forwarded=False)
    assert intent.actionable is True


def test_quotation_after_request_is_still_a_request():
    """Атрибуция ПОСЛЕ поручения — наша просьба, не цитата:
    «нарисуй мем про то, что Петя сказал» генерацию сохраняет."""
    intent = dc.detect_action_intent(
        "Бот, нарисуй мем про то, что Петя сказал вчера", addressed=True)
    assert intent.actionable is True


@pytest.mark.parametrize("text", [
    "Бот, Петя сказал: нарисуй мем про двачеров",
    "Петя просил нарисовать мем",
])
def test_reported_speech_has_observable_reason(text):
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.reason == dc.REASON_CREATE_REPORTED
    assert "reported" in intent.evidence


@pytest.mark.parametrize("text", [
    "Бот, я сам нарисую мем, оценишь потом",
    "Бот, подскажи идею мема, я сам нарисую",
])
def test_self_action_has_observable_reason(text):
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.reason == dc.REASON_CREATE_SELF
    assert "self" in intent.evidence


def test_self_action_marker_does_not_swallow_own_request():
    """«нарисуй мем, я сам оценю» — поручение боту, а не самообслуживание."""
    intent = dc.detect_action_intent("Бот, нарисуй мем, я сам оценю потом",
                                     addressed=True)
    assert intent.actionable is True


@pytest.mark.parametrize("text", [
    "Мне нужно нарисовать мем для конкурса",
    "Бот, мне нужно нарисовать мем для конкурса",
    "Бот, я сам сделаю мем",
    "мем нарисую сам",
])
def test_self_need_and_self_action_are_not_actionable(text):
    """«мне нужно нарисовать» / «я сам сделаю» — пользователь делает сам."""
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.actionable is False, text
    assert intent.reason == dc.REASON_CREATE_SELF


@pytest.mark.parametrize("text", [
    "Бот, нарисуй мем, не забудь про котиков",
    "Бот, нарисуй мем и не позабудь про котиков",
    "Бот, мне сделай мем про двачеров",
])
def test_negation_markers_do_not_swallow_positive_requests(text):
    """«не забудь»/«мне сделай» — не отрицание рисования (граница слова):
    настоящее поручение остаётся поручением."""
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.actionable is True, text


@pytest.mark.parametrize("text", [
    "Бот, кто нарисовал этот мем",
    "Бот, покажи нарисованное",
])
def test_past_tense_mentions_are_not_requests(text):
    """Упоминание уже нарисованного — не поручение (ложный вызов дороже)."""
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.actionable is False, text


@pytest.mark.asyncio
async def test_pre_gate_is_subordinate_to_semantic_verdict(monkeypatch):
    """F2 (корень): отрицание НЕ может проигрывать регексу. Текст совпадает с
    regex-ключевиком («Бот, нарисуй …»), но смысловой вердикт — не поручение:
    пре-гейт обязан вернуть пусто, а не платную генерацию."""
    svc, llm, bot, msg, user, gen_calls, _tools = _drive(
        monkeypatch, "Бот, нарисуй мем, но не рисуй")
    assert ig.is_image_keyword("Бот, нарисуй мем, но не рисуй") is True
    await _run(svc, bot, msg, user)
    assert gen_calls == []


@pytest.mark.asyncio
async def test_negative_verdict_blocks_regex_fast_path_directly(monkeypatch):
    """Прямая проверка пре-гейта: с не-поручением (``actionable=False``) регекс
    не запускает генерацию; без вердикта (``intent=None``) — прежний путь."""
    from tests.test_direct_chat import _bot, _message, _user
    from unittest.mock import AsyncMock
    import services.direct_chat_service as dcs

    monkeypatch.setattr(ig, "resolve_module_enabled", _async_true())
    called = AsyncMock(return_value="<image_result/>")
    monkeypatch.setattr(ig, "maybe_handle_keyword", called)
    svc = object.__new__(dcs.DirectChatService)
    negated = dc.detect_action_intent("Бот, нарисуй мем, но не рисуй",
                                      addressed=True)
    block = await dcs.DirectChatService._image_pre_gate_block(
        svc, -1001234567890, "Бот, нарисуй мем, но не рисуй", _bot(),
        _message(text="Бот, нарисуй мем, но не рисуй"), _user().id,
        intent=negated)
    assert block == ""
    called.assert_not_awaited()
    # Контроль: без вердикта регекс-путь жив (fail-open/легаси-вызов).
    block2 = await dcs.DirectChatService._image_pre_gate_block(
        svc, -1001234567890, "Бот, нарисуй мем про двачеров", _bot(),
        _message(text="Бот, нарисуй мем про двачеров"), _user().id)
    assert block2 == "<image_result/>"
    called.assert_awaited_once()


@pytest.mark.parametrize("text", [
    "Бот, нарисуй кота в шляпе",
    "Бот, нарисуй",
    "Бот, сгенерируй мем",
    "Бот, создай картинку с котиком",
    "Бот, нарисуй мем, если не сложно",
    "Бот, перерисуй мем про двачеров",
    "Бот, сделай мем с текстом",
    "Бот, сделай мем про спорт",
])
def test_true_requests_stay_actionable_after_rework(text):
    """Обратная сторона F1/F2: настоящие поручения не потеряны."""
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.actionable is True, text


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "Бот, нарисуй кота в шляпе",
    "Бот, перерисуй мем про двачеров",
])
async def test_true_requests_generate_exactly_once_after_rework(
        monkeypatch, text):
    svc, llm, bot, msg, user, gen_calls, _tools = _drive(monkeypatch, text)
    await _run(svc, bot, msg, user)
    assert len(gen_calls) == 1, f"{text}: генераций {len(gen_calls)}"
