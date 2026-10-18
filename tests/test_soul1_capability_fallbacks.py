"""SOUL-1 / W10 — правдивые ошибки, доставка и отсутствие дублей
(SOUL-AMD.5.15/5.17/5.18, 8.8/8.9/8.11).

Проверяется:
  * матрица отказов (модуль OFF / нет ключа / провайдер не отвечает / квота)
    даёт РАЗНЫЕ правдивые объяснения из зарегистрированных Factory Default
    шаблонов, выбранных по РЕАЛЬНОМУ коду отказа; ложной фразы «я вообще не
    умею рисовать» в пользовательском пути нет (§8.8);
  * успешная генерация + сбой Telegram-отправки → «отправил» НЕ заявляется,
    статус — ошибка доставки (§8.9);
  * переисполнение/retry/pre-gate+tool-loop не порождают дубль платного
    вызова и двойное списание (§8.9);
  * те же правила для не-image действия (поиск): недоступная capability не
    обещается, отказ наблюдаем (§8.11).

TEST-LIFECYCLE: CONTRACT owner=SOUL-AMD.5.15/5.17/5.18/8.8/8.9/8.11
                (soul-1, W10)
"""
from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from config.settings import Settings
from services import capability_registry as caps
from services import direct_capabilities as dc
from services import hot_config as hot
from services import image_generation as ig

pytestmark = [pytest.mark.asap3]

LEGACY = ig.IMAGE_GENERATION_FALLBACK_PHRASE
CHAT = -1001234567890

READY = {
    "flags.image_generation_module_enabled": True,
    "keys.image_api_key": "test-key",
    "models.image_model": "test-model",
}

FAILURE_CODES = [
    ("send_failed", "delivery_failed"),
    ("no_bot", "delivery_failed"),
    ("budget", "quota_exhausted"),
    ("unauthorized", "not_configured"),
    ("forbidden", "not_configured"),
    ("timeout", "temporarily_unavailable"),
    ("network", "temporarily_unavailable"),
    ("http_503", "temporarily_unavailable"),
    ("rate_limited", "temporarily_unavailable"),
    ("too_large", "unsupported"),
    ("empty_prompt", "unsupported"),
    ("something_weird", "unknown"),
]


class _Cfg:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeLLM:
    def __init__(self, *, l1=None, l2="готовый ответ"):
        self.l1_reply = l1 if l1 is not None else _plan_json()
        self.l2_text = l2
        self.calls = []

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kwargs):
        self.calls.append({"step": step, "messages": messages})
        return self.l1_reply if step == "l1_planner" else self.l2_text

    def steps(self):
        return [c["step"] for c in self.calls]

    def l2_user_content(self):
        found = [c for c in self.calls if c["step"] == "l2_writer"]
        if not found:
            return ""
        return "\n".join(str(m.get("content", "")) for m in found[-1]["messages"]
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
def _clean():
    caps.reset_cache()
    hot.set_config_cache(None)
    yield
    caps.reset_cache()
    hot.set_config_cache(None)


async def _true(*_a, **_k):
    return True


async def _none(*_a, **_k):
    return None


def _drive(monkeypatch, text, *, config=None, module_on=True, l1=None,
           usage=None):
    """Реальный сервис в L1-режиме; генерация подменена счётчиком."""
    from tests.test_direct_chat import _bot, _make_service, _message, _user

    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", True)
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", True)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    hot.set_config_cache(_Cfg(config if config is not None else READY))

    async def _module(_chat_id=None):
        return bool(module_on)

    monkeypatch.setattr(ig, "resolve_module_enabled", _module)
    gen_calls: list = []

    async def fake_run(request, *, bot=None, correlation_id=None):
        gen_calls.append(request)
        return ig.GenerationResult(ok=True, content=b"x")

    monkeypatch.setattr(ig, "run_image_request", fake_run)

    if usage is not None:
        from services import worker_budget as wb

        async def fake_usage(pg=None, scope=None, day=None):
            return [{"day": "2026-10-17", "scope": scope,
                     "metric": wb.METRIC_IMAGE_CALLS, "used": usage[0],
                     "limit": usage[1]}]

        monkeypatch.setattr(wb, "get_usage", fake_usage)

    llm = _FakeLLM(l1=l1)
    svc = _make_service(llm=llm)
    svc._build_user_content = _async_list([])
    svc._dig_pre_gate_block = _none
    svc._send_direct_answer = _async_id(999)
    svc.remember_bot_reply = _none
    return svc, llm, _bot(), _message(text=text), _user(), gen_calls


def _async_id(value):
    async def _f(*_a, **_k):
        return value
    return _f


def _async_list(value):
    async def _f(*_a, **_k):
        return list(value)
    return _f


async def _run(svc, bot, msg, user):
    await svc.handle(bot, msg, user)
    await asyncio.sleep(0)


def _sent(bot) -> list:
    return [str(c.args[1]) for c in bot.send_message.await_args_list
            if len(c.args) > 1]


# ── §8.8: матрица отказов — разные правдивые объяснения ─────────────────────

@pytest.mark.asyncio
async def test_module_off_replies_disabled_template(monkeypatch):
    svc, llm, bot, msg, user, gen_calls = _drive(
        monkeypatch, "Бот, нарисуй мем про двачеров", module_on=False)
    await _run(svc, bot, msg, user)
    assert gen_calls == []
    assert llm.calls == [], "честный отказ не стоит LLM-вызова"
    text, block_id, _src = caps.failure_text("disabled")
    assert _sent(bot) == [text]
    assert block_id == "message.image_failure.disabled"
    assert LEGACY not in text and "не умею" not in text


@pytest.mark.asyncio
async def test_no_key_replies_not_configured_template(monkeypatch):
    svc, llm, bot, msg, user, gen_calls = _drive(
        monkeypatch, "Бот, сделай мем про двачеров",
        config=dict(READY, **{"keys.image_api_key": ""}))
    await _run(svc, bot, msg, user)
    assert gen_calls == [] and llm.calls == []
    text, block_id, _src = caps.failure_text("not_configured")
    assert _sent(bot) == [text]
    assert block_id == "message.image_failure.not_configured"


@pytest.mark.asyncio
async def test_quota_exhausted_replies_quota_template(monkeypatch):
    svc, llm, bot, msg, user, gen_calls = _drive(
        monkeypatch, "Бот, нарисуй мем про двачеров", usage=(60, 60))
    await _run(svc, bot, msg, user)
    assert gen_calls == [] and llm.calls == []
    text, block_id, _src = caps.failure_text("quota_exhausted")
    assert _sent(bot) == [text]
    assert block_id == "message.image_failure.quota_exhausted"


@pytest.mark.asyncio
async def test_provider_down_replies_temporary_template(monkeypatch):
    svc, llm, bot, msg, user, gen_calls = _drive(
        monkeypatch, "Бот, нарисуй мем про двачеров")
    caps.record_outcome("image_generation", chat_id=CHAT, ok=False,
                        code="timeout")
    await _run(svc, bot, msg, user)
    assert gen_calls == [] and llm.calls == []
    text, block_id, _src = caps.failure_text("temporarily_unavailable")
    assert _sent(bot) == [text]
    assert block_id == "message.image_failure.temporarily_unavailable"


@pytest.mark.asyncio
async def test_failure_matrix_texts_are_distinct_and_truthful(monkeypatch):
    """Семь случаев — семь РАЗНЫХ текстов, каждый называет СВОЮ причину
    (выключено/не подключено/провайдер/квота/запрос/доставка), и ни один не
    выдаёт ложное «я вообще не умею рисовать»."""
    markers = {
        "disabled": "выключ",
        "not_configured": "не подключ",
        "temporarily_unavailable": "не отвечает",
        "quota_exhausted": "лимит",
        "unsupported": "не потянул",
        "delivery_failed": "не доехала",
        "unknown": "не «я не умею",
    }
    texts = {}
    for code, marker in markers.items():
        text, block_id, _src = caps.failure_text(code)
        assert text.strip() and text != LEGACY
        assert marker in text.lower(), (code, text)
        assert block_id == f"message.image_failure.{code}"
        texts[code] = text
    assert len(set(texts.values())) == len(texts), "тексты должны различаться"
    assert "Рисовать я, конечно, не умею" not in " ".join(texts.values())


@pytest.mark.parametrize("reason,expected", FAILURE_CODES)
def test_real_failure_code_selects_template(reason, expected):
    """Шаблон выбирается по РЕАЛЬНОМУ коду отказа (§5.15), не «на все случаи»."""
    text, block_id, _src = caps.failure_message_for_reason(reason)
    assert block_id == f"message.image_failure.{expected}"
    assert caps.failure_code_for_reason(reason) == expected
    assert text and text != LEGACY


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,expected", FAILURE_CODES)
async def test_tool_path_message_uses_template_by_code(monkeypatch, reason,
                                                       expected):
    from tests.test_unified_image_request_round1026 import _ctx, _router
    monkeypatch.setattr(ig, "resolve_module_enabled", _true)

    async def fail_run(request, *, bot=None, correlation_id=None):
        return ig.GenerationResult(ok=False, reason=reason)

    monkeypatch.setattr(ig, "run_image_request", fail_run)
    payload = json.loads(await _router()._generate_image({"prompt": "кот"},
                                                          _ctx()))
    assert payload["status"] == "error" and payload["reason"] == reason
    text, block_id, _src = caps.failure_text(expected)
    if expected == "quota_exhausted":
        # CFG-02A (§02A.5): отказ по СУТОЧНОЙ квоте дополняется фактическим
        # временем следующего сброса (календарный день чата в его TZ);
        # управляемая речевая форма реестра остаётся префиксом — контракт
        # SOUL-1 «текст выбирается по реальному коду отказа» сохранён.
        assert payload["message"].startswith(text + " ")
        assert "Суточная квота обновится" in payload["message"]
    else:
        assert payload["message"] == text
    assert payload["message_id"] == block_id
    assert LEGACY not in payload["message"]


@pytest.mark.asyncio
async def test_pre_gate_block_uses_template_by_code(monkeypatch):
    monkeypatch.setattr(ig, "resolve_module_enabled", _true)
    from services.tool_router import ToolContext

    for reason, expected in FAILURE_CODES:
        async def fail_send(*_a, _reason=reason, **_k):
            return ig.GenerationResult(ok=False, reason=_reason)

        monkeypatch.setattr(ig, "run_image_request", fail_send)
        ctx = ToolContext(1, "Бот, нарисуй кота", bot=object())
        block = await ig.maybe_handle_keyword(ctx, "Бот, нарисуй кота")
        text, block_id, _src = caps.failure_text(expected)
        assert text in block, reason
        assert f'reason="{expected}"' in block
        assert LEGACY not in block
        assert "уже сгенерировано и отправлено" not in block


# ── Удаление захардкоженной фразы из пользовательского пути ─────────────────

def test_hardcoded_phrase_is_out_of_user_path():
    """SOUL-AMD.5.15: ложная фраза убрана из пользовательского пути.

    Проверяется ИСХОДНИК реальных пользовательских функций (не только
    поведение): пре-гейт и tool-статус больше не рендерят константу."""
    src_handle = inspect.getsource(ig.maybe_handle_keyword)
    assert "IMAGE_GENERATION_FALLBACK_PHRASE" not in src_handle
    assert "failure_message_for_reason" in src_handle or \
        "_image_error_block" in src_handle
    from services.tool_router import ToolRouter
    src_tool = inspect.getsource(ToolRouter._generate_image)
    assert "IMAGE_GENERATION_FALLBACK_PHRASE" not in src_tool
    src_error = inspect.getsource(ig._image_error_block)
    assert "IMAGE_GENERATION_FALLBACK_PHRASE" not in src_error
    # Константа остаётся только заводской редакцией исторического слепка.
    assert LEGACY.startswith("Рисовать я, конечно, не умею")


def test_user_path_files_do_not_reference_legacy_constant():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "services"
    for name in ("tool_router.py", "direct_chat_service.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "IMAGE_GENERATION_FALLBACK_PHRASE" not in text, name


@pytest.mark.asyncio
async def test_templates_are_editable_factory_defaults(monkeypatch):
    """SOUL-AMD.5.15/4.1: замена — РЕДАКТИРУЕМЫЕ Factory Default-шаблоны:
    заводской текст = код-канон; правка владельца через API реестра становится
    действующей; «Вернуть заводской вариант» возвращает канон (без рестарта)."""
    from services import prompt_factory as pf

    class _Cache:
        def __init__(self, values=None):
            self.values = dict(values or {})
            self.writes = []
            self.pg_available = True

        def get(self, key, default=None):
            return self.values.get(key, default) if key in self.values \
                else default

        def get_updated_at(self, key):
            return None

        async def set(self, key, value, category):
            self.values[key] = value
            self.writes.append((key, value, category))

        async def set_many(self, items):
            for key, value, category in items:
                self.values[key] = value

    cache = _Cache()
    hot.set_config_cache(cache)
    try:
        block_id = "message.image_failure.temporarily_unavailable"
        text, bid, source = caps.failure_text("temporarily_unavailable")
        assert bid == block_id and source == "Factory"
        result = await pf.write_speech_value(block_id, "Правка владельца: жди.",
                                            cache=cache, actor=7)
        assert result["applied"] is True
        assert result["pg_key"] == "content.image_failure.temporarily_unavailable"
        edited, bid2, source2 = caps.failure_text("temporarily_unavailable")
        assert edited == "Правка владельца: жди."
        assert bid2 == block_id and source2 == "Global Custom"
        # Factory Default возвращает заводской текст без перезапуска.
        reset = await pf.apply_factory_reset(block_id, cache=cache)
        assert reset["applied"] is True
        back, _bid3, source3 = caps.failure_text("temporarily_unavailable")
        assert back == text and source3 == "Factory"
    finally:
        hot.set_config_cache(None)


@pytest.mark.asyncio
async def test_legacy_phrase_never_reaches_the_user(monkeypatch):
    """Провал генерации на пре-гейте не показывает ложную фразу (регресс-щит)."""
    monkeypatch.setattr(ig, "resolve_module_enabled", _true)

    async def fail_send(*_a, **_k):
        return ig.GenerationResult(ok=False, reason="timeout")

    monkeypatch.setattr(ig, "run_image_request", fail_send)
    from services.tool_router import ToolContext
    ctx = ToolContext(1, "Бот, нарисуй кота", bot=object())
    block = await ig.maybe_handle_keyword(ctx, "Бот, нарисуй кота")
    assert LEGACY not in block


# ── §8.9: доставка и отсутствие дублей ──────────────────────────────────────

@pytest.mark.asyncio
async def test_success_but_send_failure_never_claims_sent(monkeypatch):
    """Реальный `generate_and_send`: генерация прошла, отправка упала →
    «отправил» не заявляется, статус — ошибка доставки."""
    monkeypatch.setattr(ig, "resolve_module_enabled", _true)
    monkeypatch.setattr(ig, "_consume_budget", _true)

    async def fake_generate(prompt, **kwargs):
        return ig.GenerationResult(ok=True, content=b"img")

    monkeypatch.setattr(ig, "generate", fake_generate)
    from services import telegram_send

    async def boom(*_a, **_k):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(telegram_send, "send_photo", boom)
    result = await ig.generate_and_send(object(), CHAT, "кот")
    assert result.ok is False and result.reason == "send_failed"
    block = ig._image_error_block(result, chat_id=CHAT)
    assert 'status="error"' in block
    assert caps.failure_text("delivery_failed")[0] in block
    assert "уже сгенерировано и отправлено" not in block
    # Наблюдаемое состояние: доставка не удалась (успех ≠ доставка).
    state = await caps.resolve("image_generation", CHAT, use_cache=False)
    assert state.last_result == caps.RESULT_DELIVERY_FAILED


@pytest.mark.asyncio
async def test_send_failure_does_not_retry_paid_generation(monkeypatch):
    """Сбой доставки НЕ запускает повторную платную генерацию (§5.17)."""
    monkeypatch.setattr(ig, "resolve_module_enabled", _true)
    monkeypatch.setattr(ig, "_consume_budget", _true)
    calls = {"n": 0}

    async def fake_generate(prompt, **kwargs):
        calls["n"] += 1
        return ig.GenerationResult(ok=True, content=b"img")

    monkeypatch.setattr(ig, "generate", fake_generate)
    from services import telegram_send

    async def boom(*_a, **_k):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(telegram_send, "send_photo", boom)
    await ig.generate_and_send(object(), CHAT, "кот")
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_budget_lifecycle_once_per_intent(monkeypatch):
    """Одно намерение — один жизненный цикл квоты: один commit, ноль release
    (retry/повтор внутри не дублируют списание)."""
    monkeypatch.setattr(ig, "resolve_module_enabled", _true)
    events: list = []

    async def spy_commit(idem_key, chat_id, *, generation_failed,
                         error_code="generation_failed",
                         delivery_failed=False):
        events.append(("commit" if not generation_failed else "release",
                       bool(delivery_failed)))

    monkeypatch.setattr(ig, "_commit_or_release", spy_commit)

    async def fake_generate(prompt, **kwargs):
        return ig.GenerationResult(ok=True, content=b"img")

    monkeypatch.setattr(ig, "generate", fake_generate)
    from services import telegram_send

    async def ok_send(*_a, **_k):
        return None

    monkeypatch.setattr(telegram_send, "send_photo", ok_send)
    result = await ig.generate_and_send(object(), CHAT, "кот")
    assert result.ok is True
    assert events == [("commit", False)], events


@pytest.mark.asyncio
async def test_tool_skips_when_intent_already_handled(monkeypatch):
    """Pre-gate уже сгенерировал → tool-вызов возвращает skipped, 0 генераций
    (тот же авторитетный маркер прогона, без второго платного вызова)."""
    from tests.test_unified_image_request_round1026 import _router
    from services.tool_router import ToolContext
    monkeypatch.setattr(ig, "resolve_module_enabled", _true)
    calls = {"n": 0}

    async def fake_run(request, *, bot=None, correlation_id=None):
        calls["n"] += 1
        return ig.GenerationResult(ok=True, content=b"x")

    monkeypatch.setattr(ig, "run_image_request", fake_run)
    ctx = ToolContext(CHAT, "нарисуй", bot=object(),
                      image_request_handled=True)
    payload = json.loads(await _router()._generate_image({"prompt": "кот"},
                                                         ctx))
    assert payload["status"] == "skipped"
    assert payload["reason"] == "already_handled"
    assert calls["n"] == 0


# ── §8.11: те же правила для не-image действия (поиск) ──────────────────────

@pytest.mark.asyncio
async def test_search_capability_not_promised_when_unconfigured(monkeypatch):
    """Поиск без ключей: Writer получает правдивую пометку о недоступности
    (не обещаем и не выдумываем результат), отказ наблюдаем в trace."""
    svc, llm, bot, msg, user, gen_calls = _drive(
        monkeypatch, "Бот, поищи в интернете про двачеров",
        config=dict(READY, **{"keys.tavily_api_key": "",
                              "keys.exa_api_key": ""}),
        l1=_plan_json(capabilities_needed=["web_search"]))
    events: list = []
    monkeypatch.setattr(caps, "emit_capability_event",
                        lambda *a, **k: events.append((a, k)))
    await _run(svc, bot, msg, user)
    assert gen_calls == []
    content = llm.l2_user_content()
    assert "<capability_notice" in content
    assert "web_search" in content
    assert events, "отказ должен быть наблюдаемым (trace)"
    state = await caps.resolve("web_search", CHAT, use_cache=False)
    assert state.status == caps.STATUS_NOT_CONFIGURED


@pytest.mark.asyncio
async def test_search_capability_ready_needs_no_notice(monkeypatch):
    svc, llm, bot, msg, user, gen_calls = _drive(
        monkeypatch, "Бот, поищи в интернете про двачеров",
        config=dict(READY, **{"keys.tavily_api_key": "t-key"}),
        l1=_plan_json(capabilities_needed=["web_search"]))
    await _run(svc, bot, msg, user)
    assert "<capability_notice" not in llm.l2_user_content()
    assert (await caps.resolve("web_search", CHAT,
                               use_cache=False)).status == caps.STATUS_READY


def test_search_intent_is_detected_by_meaning():
    """§5.18: правило применяется не только к изображениям."""
    intent = dc.detect_action_intent("Бот, поищи в интернете про двачеров",
                                     addressed=True)
    assert intent.intent == dc.INTENT_WEB_SEARCH
    assert intent.capability == "web_search"
    fact = dc.detect_action_intent("Бот, проверь факт: двачеры спят днём",
                                   addressed=True)
    assert fact.capability == "fact_check"
