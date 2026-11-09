"""P0-A (2026-11-10) — семантика решения о генерации изображения.

Контракт владельца (`plans/owner_inputs/2026-11-10-smart-module-semantic-routing-p0.md`,
§1 P0-A, §4, §5, §7, §8 A/C/D/E):

  * единственный детерминированный fast-path пользовательской генерации —
    явная команда «Бот, нарисуй <промпт>»: многострочный промпт сохраняется,
    пустой аргумент генерацию не запускает;
  * обычная фраза с корнем «рису» (реальный инцидент про мангу) НЕ создаёт
    намерение генерации: нет вызова провайдера, нет сообщения о квоте/оплате,
    ответ идёт обычным текстовым путём;
  * «Нарисуй кота» без обращения к боту — обычная реплика, решение за L1;
  * `generate_image` остаётся доступным L1 (анонс инструмента + tool-фаза);
  * лимит/провайдер/платёжный сценарий проверяются только при подтверждённом
    намерении генерации, а не по совпадению слова;
  * внутренние продюсеры (мемы/обложки/инициатива) не зависят от словесных
    словарей поручения — у них собственные разрешённые источники запуска.

TEST-LIFECYCLE: CONTRACT+REGRESSION owner=P0-A (2026-11-10)
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

#: Реальный вопрос владельца из инцидента P0-A (дословно).
MANGA_QUESTION = ("Бот, чем отличается манга от не манги? Тем что её японцы "
                  "рисуют или форматом страниц или чем?")


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
        gen_calls.append({"request": request, "chat_id": request.chat_id,
                          "prompt": ig.build_final_prompt(request)})
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
        calls.append({"direct": True,
                      "prompt": (args[2] if len(args) > 2
                                 else kwargs.get("prompt", ""))})
        return ig.GenerationResult(ok=True, content=b"x")
    return _f


async def _run(svc, bot, msg, user):
    await svc.handle(bot, msg, user)
    await asyncio.sleep(0)


def _sent_texts(bot) -> list:
    return [str(c.args[1]) for c in bot.send_message.await_args_list
            if len(c.args) > 1]


def _image_refusal_texts() -> set:
    """Все управляемые тексты отказа/уточнения генерации (реестр)."""
    codes = ("disabled", "not_configured", "quota_exhausted", "freq_limited",
             "temporarily_unavailable", "unsupported", "delivery_failed")
    texts = {caps.failure_text(code)[0] for code in codes}
    texts.add(caps.clarify_text()[0])
    return {t for t in texts if t}


# ── §8 A: реальный инцидент — ноль генерации, ноль квоты, текстовый ответ ───

#: Второе обычное предложение с image-лексикой В ПРОЗЕ (не императив, не
#: обращение-команда): «картинка»/«изображение» упомянуты по смыслу.
PROSE_IMAGE_QUESTION = ("Бот, объясни: чем картинка в книге отличается от "
                        "изображения на экране и что важнее для вёрстки?")

ORDINARY_IMAGE_TALK = (MANGA_QUESTION, PROSE_IMAGE_QUESTION)


@pytest.mark.parametrize("text", ORDINARY_IMAGE_TALK)
def test_ordinary_image_talk_creates_no_image_intent(text):
    """Детектор сам по себе не видит здесь поручения (корень инцидента)."""
    intent = dc.detect_action_intent(text, addressed=True)
    assert intent.intent != dc.INTENT_CREATE_IMAGE
    assert intent.actionable is False
    assert intent.reason == dc.REASON_NONE
    assert ig.is_image_keyword(text) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ORDINARY_IMAGE_TALK)
async def test_ordinary_image_talk_reaches_text_answer_without_quota(
        monkeypatch, text):
    """Сквозной реальный путь: ни генерации, ни сообщения о квоте/оплате,
    ни подмены ответа — ход идёт обычным (текстовым) путём."""
    svc, llm, bot, msg, user, gen_calls, announced = _drive(
        monkeypatch, text)
    await _run(svc, bot, msg, user)
    assert gen_calls == [], "ложная платная генерация по слову о картинке"
    assert announced, "ход не дошёл до анонса инструментов (нет L1/tool-фазы)"
    assert announced[0][0] is True, (
        "генерация не должна сниматься до L1: флаг image_enabled остаётся")
    forbidden = _image_refusal_texts()
    sent = _sent_texts(bot)
    assert not [t for t in sent if t in forbidden], sent
    assert "l2_writer" in llm.steps() or "single" in llm.steps()
    assert "<image_result" not in llm.l2_user_content()


@pytest.mark.asyncio
async def test_manga_question_does_not_consult_image_quota(monkeypatch):
    """Квота/готовность генерации не спрашивается без подтверждённого
    намерения: ни resolve(«image_generation»), ни события отказа."""
    resolved: list = []
    real_resolve = caps.resolve

    async def spy_resolve(capability_id, chat_id=None, **kwargs):
        resolved.append(str(capability_id))
        return await real_resolve(capability_id, chat_id, **kwargs)

    monkeypatch.setattr(caps, "resolve", spy_resolve)
    svc, llm, bot, msg, user, gen_calls, _tools = _drive(
        monkeypatch, MANGA_QUESTION)
    await _run(svc, bot, msg, user)
    assert gen_calls == []
    assert "image_generation" not in resolved, resolved


@pytest.mark.asyncio
async def test_ordinary_drawing_talk_generates_nothing(monkeypatch):
    """Сценарий D: разговор о картинках/рисовании не запускает генерацию и не
    спрашивает квоту — это обычная реплика."""
    for text in ("Японцы рисуют мангу",
                 "Бот, кто нарисовал этот мем?",
                 "Бот, что такое мем?",
                 "Бот, сделай уборку в квартире",
                 "Бот, создай план на март",
                 "Бот, перерисуй схему в отчёте"):
        svc, llm, bot, msg, user, gen_calls, _ann = _drive(
            monkeypatch, text)
        await _run(svc, bot, msg, user)
        assert gen_calls == [], text
        sent = _sent_texts(bot)
        forbidden = _image_refusal_texts()
        assert not [t for t in sent if t in forbidden], (text, sent)


# ── §4/§5: единственный детерминированный fast-path ────────────────────────

def test_explicit_command_is_the_only_command_form():
    """Команда — обращение + императив; свободная форма и общие глаголы без
    объекта изображения командой не являются."""
    assert ig.is_image_keyword("Бот, нарисуй кота") is True
    assert ig.is_image_keyword("бот нарисуй кота") is True
    assert ig.is_image_keyword("БОТ, НАРИСУЙ КОТА") is True
    assert ig.is_image_keyword("Бот: нарисуй кота") is True
    assert ig.is_image_keyword("Бот, нарисуй   кота") is True
    assert ig.is_image_keyword("Бот, создай картинку с котиком") is True
    assert ig.is_image_keyword("Нарисуй кота") is False
    assert ig.is_image_keyword("Бот, сгенерируй отчёт") is False
    assert ig.is_image_keyword("Бот, создай план на март") is False
    assert ig.is_image_keyword(MANGA_QUESTION) is False


@pytest.mark.asyncio
async def test_command_generates_exactly_once_with_confirmed_delivery(
        monkeypatch):
    """Явная команда остаётся быстрым путём: одна генерация, инструмент на
    ход не объявляется, блок результата попадает в контекст Writer'а."""
    svc, llm, bot, msg, user, gen_calls, announced = _drive(
        monkeypatch, "Бот, нарисуй мем про двачеров")
    await _run(svc, bot, msg, user)
    assert len(gen_calls) == 1
    assert announced and announced[0][0] is False
    assert "generate_image" not in announced[0][1]
    assert "<image_result" in llm.l2_user_content()
    assert 'status="ok"' in llm.l2_user_content()


@pytest.mark.asyncio
async def test_command_preserves_multiline_prompt(monkeypatch):
    """Многострочный пользовательский промпт сохраняется целиком."""
    text = "Бот, нарисуй\nкота в шляпе\nна фоне заката"
    svc, llm, bot, msg, user, gen_calls, _ann = _drive(monkeypatch, text)
    await _run(svc, bot, msg, user)
    assert len(gen_calls) == 1
    assert gen_calls[0]["prompt"] == "кота в шляпе\nна фоне заката"


@pytest.mark.asyncio
async def test_command_without_argument_generates_nothing(monkeypatch):
    """Пустой аргумент: генерации нет (ни провайдера, ни квоты, ни оплаты),
    ход продолжается обычным путём."""
    svc, llm, bot, msg, user, gen_calls, _ann = _drive(
        monkeypatch, "Бот, нарисуй")
    await _run(svc, bot, msg, user)
    assert gen_calls == []
    forbidden = _image_refusal_texts()
    sent = _sent_texts(bot)
    assert not [t for t in sent if t in forbidden], sent
    assert "l2_writer" in llm.steps() or "single" in llm.steps()


def test_empty_command_has_no_prompt():
    """Контракт extract_prompt: пустой аргумент = пустой промпт (выдуманного
    промпта «Бот, нарисуй» не бывает)."""
    assert ig.extract_prompt("Бот, нарисуй") == ""
    assert ig.extract_prompt("Бот, нарисуй,") == ""
    assert ig.extract_prompt("Бот, нарисуй кота") == "кота"


@pytest.mark.asyncio
async def test_command_with_cancellation_in_same_message_generates_nothing(
        monkeypatch):
    """«нарисуй …, но не рисуй» — явная отмена в той же реплике: пре-гейт
    молчит, ложного платного вызова нет (решение уходит L1)."""
    text = "Бот, нарисуй мем, но не рисуй"
    assert ig.is_image_keyword(text) is False
    svc, llm, bot, msg, user, gen_calls, _ann = _drive(monkeypatch, text)
    await _run(svc, bot, msg, user)
    assert gen_calls == []


@pytest.mark.asyncio
async def test_detect_action_intent_is_not_image_authority(monkeypatch):
    """P0-A: детектор больше не является семантическим авторитетом изображения.
    Даже если он вернёт «create_image/high», исход обычной фразы не меняется:
    ни генерации, ни квоты, ни перехвата хода."""
    from services import direct_capabilities as dc_mod
    calls: list = []

    def _spy(*args, **kwargs):
        calls.append(args)
        return dc_mod.ActionIntent(
            intent=dc_mod.INTENT_CREATE_IMAGE,
            capability="image_generation",
            confidence=dc_mod.CONFIDENCE_HIGH,
            reason=dc_mod.REASON_CREATE_COMMAND,
            evidence=("explicit_command",))

    monkeypatch.setattr(dc_mod, "detect_action_intent", _spy)
    resolved: list = []
    real_resolve = caps.resolve

    async def spy_resolve(capability_id, chat_id=None, **kwargs):
        resolved.append(str(capability_id))
        return await real_resolve(capability_id, chat_id, **kwargs)

    monkeypatch.setattr(caps, "resolve", spy_resolve)
    svc, llm, bot, msg, user, gen_calls, announced = _drive(
        monkeypatch, MANGA_QUESTION)
    await _run(svc, bot, msg, user)
    # NB: единственный оставшийся вызов детектора на этом пути — не-image
    # сигнал evidence-политики (`_evidence_explicit_request`: поиск/фактчек,
    # P1-демоция). Авторитетом ИЗОБРАЖЕНИЯ он не является — проверяется ниже.
    assert gen_calls == []
    assert "image_generation" not in resolved, resolved
    assert announced and announced[0][0] is True
    assert not [t for t in _sent_texts(bot) if t in _image_refusal_texts()]
    assert "l2_writer" in llm.steps() or "single" in llm.steps()


@pytest.mark.asyncio
async def test_non_image_commands_generate_nothing(monkeypatch):
    """Решение §1a: общие глаголы без объекта изображения — не команда
    генерации. «Бот, сгенерируй отчёт» и «Бот, создай план» дают ноль
    генераций, ноль обращений к квоте/готовности и обычный текстовый путь."""
    for text in ("Бот, сгенерируй отчёт по продажам",
                 "Бот, создай план на март"):
        resolved: list = []
        real_resolve = caps.resolve

        async def spy_resolve(capability_id, chat_id=None, **kwargs):
            resolved.append(str(capability_id))
            return await real_resolve(capability_id, chat_id, **kwargs)

        monkeypatch.setattr(caps, "resolve", spy_resolve)
        assert ig.is_image_keyword(text) is False, text
        svc, llm, bot, msg, user, gen_calls, announced = _drive(
            monkeypatch, text)
        await _run(svc, bot, msg, user)
        assert gen_calls == [], text
        assert "image_generation" not in resolved, (text, resolved)
        assert announced and announced[0][0] is True
        assert not [t for t in _sent_texts(bot) if t in _image_refusal_texts()]
        assert "l2_writer" in llm.steps() or "single" in llm.steps()


# ── §4/§8 C: «Нарисуй кота» без обращения — решение за L1 ──────────────────

@pytest.mark.asyncio
async def test_unprefixed_draw_is_left_to_l1(monkeypatch):
    """Свободная форма не запускает быстрый путь и ничего не блокирует:
    генерация остаётся доступной решению L1/модели."""
    svc, llm, bot, msg, user, gen_calls, announced = _drive(
        monkeypatch, "Нарисуй кота")
    await _run(svc, bot, msg, user)
    assert gen_calls == [], "свободная форма не должна запускать fast-path"
    assert announced and announced[0][0] is True
    assert "l2_writer" in llm.steps() or "single" in llm.steps()


@pytest.mark.asyncio
async def test_generate_image_stays_announced_to_l1(monkeypatch):
    """Инструмент остаётся в наборе L1, когда план его запросил: ничто не
    снимает генерацию до решения модели (пре-гейт не сработал)."""
    svc, llm, bot, msg, user, gen_calls, announced = _drive(
        monkeypatch, "Нарисуй кота",
        l1=_plan_json(capabilities_needed=["image_generation"]))
    await _run(svc, bot, msg, user)
    assert announced and announced[0][0] is True
    assert "generate_image" in announced[0][1]
    assert gen_calls == [], "детерминированного запуска по лексеме нет"


@pytest.mark.asyncio
async def test_model_chosen_generate_image_reaches_image_workflow(monkeypatch):
    """INTEGRATION: вызов инструмента моделью доходит до РЕАЛЬНОГО image-контура
    (ToolRouter._generate_image → run_image_request, source="tool")."""
    from services.tool_router import ToolContext, ToolDeps, ToolRouter
    from unittest.mock import MagicMock

    generated: list = []

    async def fake_run(request, *, bot=None, correlation_id=None):
        generated.append(request)
        return ig.GenerationResult(ok=True, content=b"x")

    monkeypatch.setattr(ig, "run_image_request", fake_run)
    router = ToolRouter(MagicMock(spec=ToolDeps))
    payload = json.loads(await router._generate_image(
        {"prompt": "кота"}, ToolContext(-1001234567890, "Нарисуй кота",
                                        bot=object())))
    assert payload["status"] == "success"
    assert len(generated) == 1
    assert generated[0].source == "tool"
    assert generated[0].user_request == "кота"


@pytest.mark.asyncio
async def test_l1_requested_capability_is_not_pre_generated_twice(monkeypatch):
    """Команда + план L1 с image_generation: второй (детерминированный) путь
    не срабатывает — генерация остаётся за tool-фазой, дубля нет."""
    svc, llm, bot, msg, user, gen_calls, announced = _drive(
        monkeypatch, "Бот, нарисуй мем про двачеров",
        l1=_plan_json(capabilities_needed=["image_generation"]),
        real_pre_gate=False)
    await _run(svc, bot, msg, user)
    assert gen_calls == []
    assert announced and announced[0][0] is True
    assert "generate_image" in announced[0][1]


@pytest.mark.asyncio
async def test_l1_requested_image_capability_not_ready_is_not_promised(
        monkeypatch):
    """L1 запросил image_generation, но в чате её нет (нет ключа): инструмент
    не анонсируется, Writer получает правдивую пометку — обещаний нет."""
    svc, llm, bot, msg, user, gen_calls, announced = _drive(
        monkeypatch, "Бот, посоветуй фильм на вечер",
        config=dict(READY_CONFIG, **{"keys.image_api_key": ""}),
        l1=_plan_json(capabilities_needed=["image_generation"]))
    await _run(svc, bot, msg, user)
    assert gen_calls == []
    assert announced and "generate_image" not in announced[0][1]
    assert "<capability_notice" in llm.l2_user_content()


@pytest.mark.asyncio
async def test_forwarded_command_generates_nothing(monkeypatch):
    """Пересланная команда — чужие слова, не поручение пользователя."""
    svc, llm, bot, msg, user, gen_calls, _ann = _drive(
        monkeypatch, "Бот, нарисуй мем про двачеров", forwarded=True)
    await _run(svc, bot, msg, user)
    assert gen_calls == []
    intent = dc.detect_action_intent("Бот, нарисуй мем про двачеров",
                                     addressed=True, forwarded=True)
    assert intent.actionable is False
    assert intent.reason == dc.REASON_CREATE_FORWARDED


# ── §5: квота/оплата только при подтверждённом намерении ────────────────────

@pytest.mark.asyncio
async def test_quota_is_consulted_for_confirmed_command(monkeypatch):
    """Обратная сторона: у явной команды готовность/лимит проверяются
    (это и есть подтверждённое намерение)."""
    resolved: list = []
    real_resolve = caps.resolve

    async def spy_resolve(capability_id, chat_id=None, **kwargs):
        resolved.append(str(capability_id))
        return await real_resolve(capability_id, chat_id, **kwargs)

    monkeypatch.setattr(caps, "resolve", spy_resolve)
    svc, llm, bot, msg, user, gen_calls, _ann = _drive(
        monkeypatch, "Бот, нарисуй кота")
    await _run(svc, bot, msg, user)
    assert "image_generation" in resolved, resolved


@pytest.mark.asyncio
async def test_command_without_capability_reports_honest_template(monkeypatch):
    """Явная команда при недоступной генерации: честный отказ из шаблона
    реестра, 0 платных вызовов, 0 генераций."""
    svc, llm, bot, msg, user, gen_calls, _ann = _drive(
        monkeypatch, "Бот, нарисуй кота",
        config=dict(READY_CONFIG, **{"flags.image_generation_module_enabled":
                                     False}))
    # Модуль выключен и для реестра готовности (тот же resolver, что у пре-гейта)
    async def _module_off(*_a, **_k):
        return False
    monkeypatch.setattr(ig, "resolve_module_enabled", _module_off)
    await _run(svc, bot, msg, user)
    assert gen_calls == []
    sent = _sent_texts(bot)
    assert caps.failure_text("disabled")[0] in sent, sent


# ── §5.10-контракт: наблюдаемость блокеров (структурный, не словесный) ──────

def test_intent_blockers_are_observable_for_structural_intent():
    """Блокеры готовности считаются по СТРУКТУРНОМУ интенту (план/команда),
    а не по словесному словарю."""
    intent = dc.detect_action_intent("Бот, нарисуй мем про двачеров",
                                     addressed=True)
    assert dc.intent_blockers(intent, capability_status="ready") == ()
    assert dc.intent_blockers(intent, capability_status="disabled") == (
        "capability_disabled",)
    assert dc.intent_blockers(None, capability_status="disabled") == ()
