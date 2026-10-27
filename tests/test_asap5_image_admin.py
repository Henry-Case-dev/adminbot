"""ASAP5 W2 — IMAGE-ADMIN: разграничение возможностей, правдивые заявления,
edit-route, контекст и админка (§18–§22).

Проверяется:

  * REQ-GEN-CAPABILITIES: capability ``image_edit`` — отдельная способность
    из реальных источников (модуль/ключ/модель/provider edit-capability);
    недоступность одной операции не означает недоступности остальных;
  * REQ-GEN-CONTRADICTION: root-cause fix — после фактического успеха
    media-инструмента устаревший ``<capability_notice>`` выветривается из
    контекста Writer'а (заявление = фактический результат; случай
    «не умею рисовать» → изображение отправлено → снова отрицает больше не
    воспроизводится);
  * REQ-GEN-EDIT-ROUTE (COR-02): edit-решение — за семантическим L1-планом
    (структурные поля ``capabilities_needed``); детерминированный пре-гейт
    НЕ классифицирует edit по словникам (словари удалены, словники не
    расширяются); план, выбравший edit, не подменяется генерацией;
    инструмент ``edit_image`` ведёт в СУЩЕСТВУЮЩИЙ
    ``media_execution.submit_edit``-маршрут; без исходника — честный отказ
    (не генерация «вместо»); ошибка не выдаётся за успех;
  * REQ-COR-01 (p0-nostalgia): effective-настройки чата одни у проверки
    capability и исполнения (chat_value); исходник edit сохраняет реальный
    формат (суффикс по сниффер-MIME, не безусловный .png);
  * REQ-COR-03 (p0-nostalgia): claim-sync определяет успех по структурному
    статусу результата (classify/envelope), не по подстрокам.
  * REQ-GEN-CONTEXT: уточняющий вопрос не повторяется ход за ходом;
  * REQ-ADMIN-TYPES: подраздел «Типы медиа» (5 тумблеров, заводские
    значения включены, главный тумблер Vision приоритетен, enqueue-гейт);
  * REQ-ADMIN-DIAG: диагностика — типы медиа, типы с преобразованием,
    задачи (ожидающие/выполняющиеся/с ошибкой) и последняя ошибка из
    существующих записей очереди.

TEST-LIFECYCLE: CONTRACT (ASAP5 §18–§22) / REGRESSION (W10 capability intent)
"""
from __future__ import annotations

import json
import time
import types
from unittest.mock import MagicMock

import pytest

from services import capability_registry as caps
from services import direct_capabilities as dc
from services import hot_config as hot
from services import image_generation as ig
from services import mca_vision
from services import tool_loop
from services import tool_schemas
from services.tool_router import ToolContext, ToolRouter

pytestmark = [pytest.mark.asap3]


# ── Общие дубли (паттерн test_soul1_capability_registry) ────────────────────

class _Cfg:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


READY = {
    "flags.image_generation_module_enabled": True,
    "keys.image_api_key": "test-key",
    "models.image_model": "test-model",
}

CHAT = -1001234567890


@pytest.fixture(autouse=True)
def _clean_registry():
    caps.reset_cache()
    hot.set_config_cache(None)
    yield
    caps.reset_cache()
    hot.set_config_cache(None)


def _patch_image_sources(monkeypatch, *, module_on=True, config=None):
    hot.set_config_cache(_Cfg(config if config is not None else READY))

    async def _module(_chat_id=None):
        return bool(module_on)

    monkeypatch.setattr(ig, "resolve_module_enabled", _module)

    from services import worker_budget as wb

    async def fake_usage(pg=None, scope=None, day=None):
        return []

    async def fake_limits(chat_id):
        return (200, 60, "default")

    monkeypatch.setattr(wb, "get_usage", fake_usage)
    monkeypatch.setattr(wb, "image_limits", fake_limits)


def _patch_edit_caps(monkeypatch, *, edit_value: str):
    """provider edit-capability цепочка (без сети): 'yes' | 'no' | 'unknown'."""
    from services import image_capabilities as icap

    def _resolve(provider, base_url, model, **kwargs):
        caps_obj = icap.conservative_unknown()
        caps_obj.image_edit = edit_value
        return caps_obj

    monkeypatch.setattr(icap, "resolve_capabilities", _resolve)


# ════════════════════════════════════════════════════════════════════════════
# REQ-GEN-CAPABILITIES: разграничение реальных возможностей (§18)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_image_edit_capability_ready_from_real_sources(monkeypatch):
    """image_edit строится из реальных источников: модуль + провайдер с
    подтверждённой edit-capability → ready, отдельная от image_generation."""
    _patch_image_sources(monkeypatch)
    _patch_edit_caps(monkeypatch, edit_value="yes")
    edit = await caps.resolve("image_edit", CHAT)
    gen = await caps.resolve("image_generation", CHAT)
    assert edit.status == caps.STATUS_READY
    assert edit.tool_name == "edit_image"
    assert edit.capability_id == "image_edit"
    assert gen.status == caps.STATUS_READY
    assert gen.tool_name == "generate_image"


@pytest.mark.asyncio
async def test_edit_unsupported_does_not_disable_generation(monkeypatch):
    """§18: недоступность одной операции (модель не умеет edit) НЕ означает
    недоступности остальных — генерация остаётся ready."""
    _patch_image_sources(monkeypatch)
    _patch_edit_caps(monkeypatch, edit_value="no")
    edit = await caps.resolve("image_edit", CHAT)
    gen = await caps.resolve("image_generation", CHAT)
    assert edit.status == caps.STATUS_UNSUPPORTED
    assert edit.reason_code == "edit_unsupported"
    assert gen.status == caps.STATUS_READY


@pytest.mark.asyncio
async def test_edit_unknown_capability_stays_honest(monkeypatch):
    """unknown edit-capability провайдера — честный not_configured
    (поддержка НЕ выдумывается; реестр называет причину, а не «не знаю»).
    Реестровый STATUS_UNKNOWN зарезервирован для «capability не в реестре»."""
    _patch_image_sources(monkeypatch)
    _patch_edit_caps(monkeypatch, edit_value="unknown")
    edit = await caps.resolve("image_edit", CHAT)
    assert edit.status == caps.STATUS_NOT_CONFIGURED
    assert edit.reason_code == "edit_capability_unknown"


@pytest.mark.asyncio
async def test_edit_module_off_disables_only_edit_view(monkeypatch):
    _patch_image_sources(monkeypatch, module_on=False)
    edit = await caps.resolve("image_edit", CHAT)
    assert edit.status == caps.STATUS_DISABLED


@pytest.mark.asyncio
async def test_capability_view_lists_edit_separately(monkeypatch):
    _patch_image_sources(monkeypatch)
    _patch_edit_caps(monkeypatch, edit_value="yes")
    view = await caps.capability_view(CHAT)
    ids = [item["capability_id"] for item in view]
    assert "image_edit" in ids and "image_generation" in ids


def test_notice_block_requires_reported_success_over_stale_claim():
    """Правдивая пометка Writer'у не подменяет фактический результат хода."""
    state = caps.CapabilityState(capability_id="image_generation",
                                 status=caps.STATUS_TEMPORARILY_UNAVAILABLE,
                                 reason_code="timeout")
    notice = caps.notice_block(state)
    assert "недоступен" in notice
    # §19: фактический результат действия сильнее устаревшего отказа.
    assert "фактический результат" in notice


def test_capability_tools_map_includes_edit():
    assert dc.CAPABILITY_TOOLS.get("image_edit") == ("edit_image",)
    assert dc.CAPABILITY_LABELS.get("image_edit") == "редактирование картинок"


# ════════════════════════════════════════════════════════════════════════════
# REQ-GEN-CONTRADICTION (§19): заявление синхронно с фактическим результатом
# ════════════════════════════════════════════════════════════════════════════

_NOTICE = ('<capability_notice status="temporarily_unavailable" '
           'capability="image_generation">\n'
           "Инструмент image_generation сейчас недоступен: провайдер временно "
           "не отвечает (причина: timeout).\nОбъясни отказ.\n"
           "</capability_notice>")


def test_strip_stale_notices_removes_only_target_capability():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": f"вопрос\n{_NOTICE}"},
        {"role": "user", "content": "<capability_notice capability=\"fact_check"
         "\">другой</capability_notice>"},
    ]
    removed = tool_loop._strip_stale_capability_notices(
        messages, "image_generation")
    assert removed == 1
    assert "capability_notice" not in messages[1]["content"]
    assert "fact_check" in messages[2]["content"]


def test_sync_claim_structured_contract():
    """COR-03: успех/неуспех — по структурному статусу классификации, не по
    подстрокам. Не-успех, битый/чужой info — консервативно (notice жив)."""
    messages = [{"role": "user", "content": f"q\n{_NOTICE}"}]
    assert tool_loop._sync_claim_with_outcome(
        messages, "generate_image",
        {"status": "error", "error_code": "timeout"}) == 0
    assert "capability_notice" in messages[0]["content"]
    # Битый/неподтверждённый результат → консервативно:
    assert tool_loop._sync_claim_with_outcome(
        messages, "generate_image", None) == 0
    assert tool_loop._sync_claim_with_outcome(
        messages, "generate_image", "текст вместо структуры") == 0
    assert tool_loop._sync_claim_with_outcome(
        messages, "generate_image", {}) == 0
    assert tool_loop._sync_claim_with_outcome(
        messages, "generate_image", {"status": "delivery_unknown"}) == 0
    assert tool_loop._sync_claim_with_outcome(
        messages, "generate_image", {"status": "empty"}) == 0
    assert "capability_notice" in messages[0]["content"]
    # Чужой тул (не media-claim) → 0 даже при ok:
    assert tool_loop._sync_claim_with_outcome(
        messages, "fetch_article", {"status": "ok"}) == 0
    assert "capability_notice" in messages[0]["content"]


def test_sync_claim_structured_success_strips_and_ignores_substring_trick():
    """COR-03: структурный ok выветривает notice; подстрока
    '"status": "success"' внутри СТРУКТУРНОЙ ошибки успехом не считается
    (случайное совпадение текста ≠ успех)."""
    messages = [{"role": "user", "content": f"q\n{_NOTICE}"}]
    assert tool_loop._sync_claim_with_outcome(
        messages, "generate_image", {"status": "ok"}) == 1
    assert "capability_notice" not in messages[0]["content"]
    # Подстрочный трюк: ошибка, ЧЬЁ сообщение содержит маркер успеха.
    trick = {"status": "error", "error_code": "provider_error",
             "error_type": "expected '\"status\": \"success\"' in output"}
    messages2 = [{"role": "user", "content": f"q\n{_NOTICE}"}]
    assert tool_loop._sync_claim_with_outcome(
        messages2, "generate_image", trick) == 0
    assert "capability_notice" in messages2[0]["content"]


class _FakeLLM:
    """Двойник LLM: раунд 0 — tool_call generate_image, раунд 1 — финал.
    Запоминает payload_messages КАЖДОГО вызова (проверка контекста финала)."""

    def __init__(self):
        self.payloads: list[list[dict]] = []

    async def generate_chat(self, messages, **kwargs):
        self.payloads.append(messages)
        round_index = len(self.payloads) - 1
        if round_index == 0:
            call = types.SimpleNamespace(
                id="call_1", name="generate_image",
                arguments=json.dumps({"prompt": "мем про кота"}),
                as_openai_dict=lambda: {"id": "call_1", "type": "function",
                                        "function": {
                                            "name": "generate_image",
                                            "arguments": "{\"prompt\": \"мем\"}"},
                                        })
            return types.SimpleNamespace(
                content="", tool_calls=[call])
        return types.SimpleNamespace(
            content="Готово, картинку отправил.", tool_calls=None)


class _FakeRouter:
    def __init__(self, output: str):
        self.output = output
        self.calls: list[tuple[str, dict]] = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, dict(arguments)))
        return self.output


async def _run_tool_loop(monkeypatch, *, router_output: str):
    """Прогон chat_with_tools: успешная/неуспешная генерация на раунде 0."""
    llm = _FakeLLM()
    router = _FakeRouter(router_output)
    ctx = ToolContext(CHAT, "бот нарисуй мем", bot=object(),
                      correlation_id="corr-test")
    result = await tool_loop.chat_with_tools(
        llm, [{"role": "user",
               "content": f"бот нарисуй мем\n{_NOTICE}"}],
        tools=[], router=router, ctx=ctx, chat_id=CHAT)
    return llm, router, result


@pytest.mark.asyncio
async def test_generation_success_strips_stale_inability_claim(monkeypatch):
    """RED→GREEN дефекта противоречия: успех генерации + устаревший
    «объясни отказ» в одном контексте → финальный контекст БЕЗ notice
    (ToolResult и заявление не противоречат друг другу)."""
    success = json.dumps({"status": "success",
                          "message": "Изображение сгенерировано и отправлено "
                                     "в чат"})
    llm, router, result = await _run_tool_loop(monkeypatch,
                                               router_output=success)
    assert len(router.calls) == 1 and router.calls[0][0] == "generate_image"
    final_payload = llm.payloads[-1]
    user_texts = [m.get("content", "") for m in final_payload
                  if m.get("role") == "user"]
    joined = "\n".join(user_texts)
    assert "capability_notice" not in joined


@pytest.mark.asyncio
async def test_failed_generation_keeps_notice_honestly(monkeypatch):
    """Неуспех: пометка остаётся (она была правдой на момент планирования)."""
    failure = json.dumps({"status": "error", "reason": "timeout",
                          "message": "Генератор сейчас не отвечает"})
    llm, router, result = await _run_tool_loop(monkeypatch,
                                               router_output=failure)
    final_payload = llm.payloads[-1]
    joined = "\n".join(m.get("content", "") for m in final_payload
                       if m.get("role") == "user")
    assert "capability_notice" in joined


@pytest.mark.asyncio
async def test_substring_success_inside_error_keeps_notice(monkeypatch):
    """COR-03: маркер успеха как ПОДСТРОКА внутри структурной ошибки не
    трактуется как успех — notice остаётся (решение по структурному
    статусу классификации, не по текстовым фрагментам)."""
    trick = json.dumps({
        "status": "error", "reason": "provider_error",
        "message": 'валидатор ожидал фрагмент "status": "success" в выводе'})
    llm, router, result = await _run_tool_loop(monkeypatch,
                                               router_output=trick)
    final_payload = llm.payloads[-1]
    joined = "\n".join(m.get("content", "") for m in final_payload
                       if m.get("role") == "user")
    assert "capability_notice" in joined


# ════════════════════════════════════════════════════════════════════════════
# REQ-GEN-EDIT-ROUTE (§20): изменение исходника ≠ создание нового
# ════════════════════════════════════════════════════════════════════════════

def test_edit_intent_not_word_derived():
    """COR-02: пре-гейт НЕ классифицирует edit по словнику — словари
    _EDIT_VERB/_EDIT_REMOVE/_EDIT_LOCATIVE_RE удалены, словники не
    расширяются под очередные фразы. Ни прежние словниковые формулировки,
    ни естественные фразы без словарных основ не дают INTENT_EDIT_IMAGE от
    детектора (edit-решение — за L1-планом, структурные поля)."""
    for text in ("бот, измени текст на картинке",     # прежний словник
                 "можешь изменить мем",               # прежний словник
                 "убери надпись с фото",              # прежний remove+локатив
                 "замени фон на закат",               # прежний словник
                 "пусть человек на снимке смотрит влево",  # БЕЗ словарных основ
                 "сделай так, чтобы тут был вечер"):  # БЕЗ словарных основ
        intent = dc.detect_action_intent(text, addressed=True)
        assert intent.intent != dc.INTENT_EDIT_IMAGE, text
        assert intent.edit_actionable is False, text


def test_edit_phrasing_does_not_misroute_into_create():
    """COR-02: edit-формулировка без create-поручений не даёт
    actionable-поручения генерации (fast-path генерации не стреляет).
    Фразы с need-маркером («можешь изменить мем») детектор W10 классифицирует
    как create-интент — edit/generate развязывает АВТОРИТЕТНЫЙ L1-план
    (см. test_word_intent_create_does_not_override_plan_edit: routing-fix
    план с edit генерацией не подменяет)."""
    intent = dc.detect_action_intent("бот, измени текст на картинке",
                                     addressed=True)
    assert intent.actionable is False
    assert intent.intent != dc.INTENT_CREATE_IMAGE
    intent2 = dc.detect_action_intent("убери надпись с фото", addressed=True)
    assert intent2.intent != dc.INTENT_CREATE_IMAGE
    assert intent2.edit_actionable is False


def test_negated_create_still_suppressed():
    """Регресс: отрицание/запрет по-прежнему глушит поручение (это защита
    create-пути, не словниковая edit-детекция)."""
    intent = dc.detect_action_intent("не редактируй картинку, просто скажи "
                                     "что видишь", addressed=True)
    assert intent.edit_actionable is False
    assert intent.actionable is False


def test_create_regressions_stay_create():
    """Регресс W10: прежние create-поручения не ушли в edit."""
    for text in ("Бот, перерисуй мем про двачеров",
                 "Бот, нарисуй кота в шляпе",
                 "Бот, сделай мем с текстом"):
        intent = dc.detect_action_intent(text, addressed=True)
        assert intent.actionable is True, text
        assert intent.intent == dc.INTENT_CREATE_IMAGE, text


def test_intent_blockers_cover_edit_capability_status():
    """COR-02: структурный контракт edit-пути сохранён — сконструированный
    intent (план/структурные поля, не словник) проверяет capability."""
    intent = dc.ActionIntent(intent=dc.INTENT_EDIT_IMAGE,
                             capability="image_edit",
                             confidence=dc.CONFIDENCE_HIGH)
    assert dc.intent_blockers(intent, capability_status="unsupported") == \
        ("capability_unsupported",)
    assert dc.intent_blockers(intent, capability_status="ready") == ()


# ════════════════════════════════════════════════════════════════════════════
# COR-02: edit-решение L1-планом (структурные поля) — honesty-путь
# ════════════════════════════════════════════════════════════════════════════

def _make_svc():
    from unittest.mock import MagicMock
    from services.direct_chat_service import DirectChatService
    return DirectChatService(MagicMock(), MagicMock(), MagicMock(),
                             types.SimpleNamespace(resolve=lambda *a, **k: ""))


def _patch_reg_resolve(monkeypatch, *, edit_status: str,
                       gen_status: str = "ready"):
    """Подмена реестра (без сети): статусы image_edit / image_generation."""

    def _state(cap_id: str, status: str):
        return caps.CapabilityState(capability_id=cap_id, title=cap_id,
                                    status=status, reason_code="",
                                    declared=True)

    async def _resolve(capability_id, chat_id=None, **kwargs):
        if capability_id == "image_edit":
            return _state("image_edit", edit_status)
        if capability_id == "image_generation":
            return _state("image_generation", gen_status)
        return _state(str(capability_id), caps.STATUS_UNKNOWN)

    monkeypatch.setattr(caps, "resolve", _resolve)


@pytest.mark.asyncio
async def test_plan_edit_unavailable_denied_and_notice(monkeypatch):
    """COR-02: план (семантика) запросил image_edit, инструмент недоступен →
    правдивая пометка Writer'у + инструмент скрыт (denied); генерация вместо
    редактирования не подменяется (fired=False)."""
    from services.direct_l1 import L1Plan
    _patch_reg_resolve(monkeypatch, edit_status=caps.STATUS_NOT_CONFIGURED)
    svc = _make_svc()
    block, fired, denied = await svc._l1_capability_consistency(
        CHAT, "пусть человек на снимке смотрит влево", MagicMock(),
        MagicMock(), L1Plan(capabilities_needed=("image_edit",)),
        intent=None, image_pre_gate_fired=False)
    assert fired is False
    assert "image_edit" in denied
    assert "capability_notice" in block and "image_edit" in block


@pytest.mark.asyncio
async def test_plan_edit_available_no_denial_no_generation_force(monkeypatch):
    """COR-02: план запросил image_edit, инструмент готов → без отказов и
    без принудительной генерации; edit_image остаётся анонсированным."""
    from services.direct_l1 import L1Plan
    _patch_reg_resolve(monkeypatch, edit_status=caps.STATUS_READY)
    svc = _make_svc()
    block, fired, denied = await svc._l1_capability_consistency(
        CHAT, "пусть человек на снимке смотрит влево", MagicMock(),
        MagicMock(), L1Plan(capabilities_needed=("image_edit",)),
        intent=None, image_pre_gate_fired=False)
    assert fired is False
    assert denied == ()
    assert block == ""


@pytest.mark.asyncio
async def test_word_intent_create_does_not_override_plan_edit(monkeypatch):
    """COR-02: детерминированный create-интент (need+объект) НЕ подменяет
    генерацией план, выбравший edit (структурное поле); честность edit
    сохраняется через пометку."""
    from services.direct_l1 import L1Plan
    _patch_reg_resolve(monkeypatch, edit_status=caps.STATUS_NOT_CONFIGURED,
                       gen_status=caps.STATUS_READY)
    svc = _make_svc()
    create_intent = dc.ActionIntent(intent=dc.INTENT_CREATE_IMAGE,
                                    capability="image_generation",
                                    confidence=dc.CONFIDENCE_HIGH)
    block, fired, denied = await svc._l1_capability_consistency(
        CHAT, "можешь изменить мем", MagicMock(), MagicMock(),
        L1Plan(capabilities_needed=("image_edit",)),
        intent=create_intent, image_pre_gate_fired=False)
    # План выбрал edit → routing-fix генерации НЕ стреляет:
    assert fired is False
    assert denied == ()          # image_generation готов (не он выбирался)
    # Недоступный edit — правдивая пометка Writer'у (генерация вместо него
    # не идёт); контракт §5.18 others: инструмент не прячется, пометка есть.
    assert "capability_notice" in block and "image_edit" in block


def test_tool_canon_15_edit_image_at_tail():
    """Канон R9 = 15: edit_image в КОНЦЕ; первые 14 имён не меняются."""
    names = [t["function"]["name"] for t in tool_schemas.TOOL_CALLING_TOOLS]
    assert len(names) == 15
    assert names[-1] == "edit_image"
    assert names[:14] == ["query_chat_memory", "dig_into_lore",
                          "execute_web_search", "summarize_video",
                          "download_media", "get_bot_health",
                          "get_recent_history", "compile_lore_story",
                          "generate_image", "transcribe_video",
                          "fetch_article", "get_user_context",
                          "recognize_image", "fact_check"]


def test_active_tools_gate_edit_with_image_module():
    with_image = {t["function"]["name"]
                  for t in tool_schemas.active_tools(True, True)}
    without_image = {t["function"]["name"]
                     for t in tool_schemas.active_tools(True, False)}
    assert "edit_image" in with_image and "generate_image" in with_image
    assert "edit_image" not in without_image
    assert "generate_image" not in without_image


@pytest.mark.asyncio
async def test_edit_image_dispatch_routes_to_submit_edit(monkeypatch):
    """Direct Chat edit-просьба доходит до СУЩЕСТВУЮЩЕГО submit_edit-пути
    (media_execution → cover_style_edit) и доставляет результат существующей
    отправкой; исход связан с запросом (reply); исход фиксируется в реестре."""
    from services import capability_registry
    from services import mca_vision as mv
    from services import telegram_send
    from services.media_execution import MediaSubmitResult

    _patch_image_sources(monkeypatch)
    _patch_edit_caps(monkeypatch, edit_value="yes")
    caps.invalidate(None, None, reason="test")

    calls = {"submit_edit": [], "send_photo": [], "download": []}

    class _FakeAdapter:
        name = "nanogpt"

        async def submit_edit(self, *, prompt, model, image_paths, **kwargs):
            calls["submit_edit"].append(
                {"prompt": prompt, "model": model,
                 "image_paths": list(image_paths)})
            return MediaSubmitResult(ok=True, content=b"edited-bytes",
                                     reason="ok")

    import services.media_execution as me
    monkeypatch.setattr(me, "detect_adapter",
                        lambda base_url: _FakeAdapter())

    async def _fake_download(bot, file_id, **kwargs):
        calls["download"].append(file_id)
        return mv.DownloadedImage(data=b"png-bytes", mime="image/png",
                                  declared_mime="image/png", width=10,
                                  height=10, byte_size=9)

    monkeypatch.setattr(mv, "download_telegram_file", _fake_download)

    async def _fake_send_photo(bot, chat_id, photo, **kwargs):
        calls["send_photo"].append({"chat_id": chat_id, **kwargs})
        return object()

    monkeypatch.setattr(telegram_send, "send_photo", _fake_send_photo)

    class _FakeDb:
        async def get_media_assets_for_message(self, chat_id, tg_id):
            return [{"asset_kind": "photo", "file_id": "fid_1",
                     "file_unique_id": "uniq_1"}]

    router = object.__new__(ToolRouter)
    router.deps = types.SimpleNamespace(db=_FakeDb())
    ctx = ToolContext(CHAT, "измени текст на картинке", bot=object(),
                      reply_to_message_id=501, correlation_id="corr-edit")
    out = await router.dispatch(
        "edit_image",
        {"prompt": "убери текст",
         "target": {"chat_id": CHAT, "message_id": 501}},
        ctx)
    payload = json.loads(out)
    assert payload["status"] == "success"
    assert payload["operation"] == "edit"
    assert payload["source"]["message_id"] == 501
    assert len(calls["submit_edit"]) == 1
    assert calls["submit_edit"][0]["image_paths"] and \
        calls["submit_edit"][0]["prompt"] == "убери текст"
    assert calls["send_photo"] and \
        calls["send_photo"][0].get("reply_to_message_id") == 501
    # Генерация вместо edit не выполнялась (изменение ≠ создание):
    # единственный исполнитель — submit_edit (выше), generate-путь не тронут.
    assert len(calls["submit_edit"]) == 1
    # Наблюдаемый исход фиксируется отдельной capability image_edit.
    assert caps._outcome("image_edit", CHAT)[0] == caps.RESULT_SUCCESS
    assert ctx.image_request_handled is True


@pytest.mark.asyncio
async def test_edit_image_without_source_is_honest_error_no_generation(
        monkeypatch):
    """Нет исходника → честный отказ no_source_image; генерация «вместо»
    edit не выполняется; ошибка не выдаётся за успех."""
    _patch_image_sources(monkeypatch)
    _patch_edit_caps(monkeypatch, edit_value="yes")
    caps.invalidate(None, None, reason="test")
    submit_calls = []

    class _FakeAdapter:
        name = "nanogpt"

        async def submit_edit(self, **kwargs):
            submit_calls.append(kwargs)
            raise AssertionError("submit_edit не должен вызываться без "
                                 "исходника")

    import services.media_execution as me
    monkeypatch.setattr(me, "detect_adapter",
                        lambda base_url: _FakeAdapter())

    class _FakeDb:
        async def get_media_assets_for_message(self, chat_id, tg_id):
            return []

    router = object.__new__(ToolRouter)
    router.deps = types.SimpleNamespace(db=_FakeDb())
    ctx = ToolContext(CHAT, "измени картинку", bot=object(),
                      reply_to_message_id=None)
    out = await router.dispatch("edit_image", {"prompt": "измени"}, ctx)
    payload = json.loads(out)
    assert payload["status"] == "error"
    assert payload["reason"] == "no_source_image"
    assert submit_calls == []


@pytest.mark.asyncio
async def test_edit_image_model_without_edit_capability_honest(monkeypatch):
    """Модель без edit-capability → честный unsupported, не спекулятивная
    генерация (операция выбирается Capability Registry)."""
    _patch_image_sources(monkeypatch)
    _patch_edit_caps(monkeypatch, edit_value="no")
    caps.invalidate(None, None, reason="test")
    router = object.__new__(ToolRouter)
    router.deps = types.SimpleNamespace(db=None)
    ctx = ToolContext(CHAT, "измени картинку", bot=object(),
                      reply_to_message_id=501)
    out = await router.dispatch("edit_image", {"prompt": "измени"}, ctx)
    payload = json.loads(out)
    assert payload["status"] == "error"
    assert payload["reason"] == "edit_unsupported"


@pytest.mark.asyncio
async def test_edit_image_failure_is_not_reported_as_success(monkeypatch):
    """Ошибка исполнителя (submit_edit ok=False) → честный error с реальной
    причиной; отправка не выполняется."""
    from services.media_execution import MediaSubmitResult

    _patch_image_sources(monkeypatch)
    _patch_edit_caps(monkeypatch, edit_value="yes")
    caps.invalidate(None, None, reason="test")
    sent = []

    class _FakeAdapter:
        name = "nanogpt"

        async def submit_edit(self, **kwargs):
            return MediaSubmitResult(ok=False, reason="timeout")

    import services.media_execution as me
    from services import mca_vision as mv
    from services import telegram_send
    monkeypatch.setattr(me, "detect_adapter",
                        lambda base_url: _FakeAdapter())

    async def _fake_download(bot, file_id, **kwargs):
        return mv.DownloadedImage(data=b"png", mime="image/png",
                                  declared_mime="image/png", width=1,
                                  height=1, byte_size=1)

    async def _fake_send(bot, chat_id, photo, **kwargs):
        sent.append(chat_id)
        return object()

    monkeypatch.setattr(mv, "download_telegram_file", _fake_download)
    monkeypatch.setattr(telegram_send, "send_photo", _fake_send)

    class _FakeDb:
        async def get_media_assets_for_message(self, chat_id, tg_id):
            return [{"asset_kind": "photo", "file_id": "fid_1",
                     "file_unique_id": "uniq_1"}]

    router = object.__new__(ToolRouter)
    router.deps = types.SimpleNamespace(db=_FakeDb())
    ctx = ToolContext(CHAT, "измени", bot=object(), reply_to_message_id=501)
    out = await router.dispatch(
        "edit_image", {"prompt": "измени",
                       "target": {"chat_id": CHAT, "message_id": 501}}, ctx)
    payload = json.loads(out)
    assert payload["status"] == "error"
    assert payload["reason"] == "timeout"
    assert sent == []
    assert caps._outcome("image_edit", CHAT)[0] == caps.RESULT_FAILED


# ════════════════════════════════════════════════════════════════════════════
# REQ-COR-01: единый effective-конфиг чата + реальный формат исходника
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_edit_image_source_format_preserved(monkeypatch):
    """COR-01: исходник сохраняется во временный файл с расширением по
    сниффер-MIME (JPEG → .jpg, WebP → .webp), PNG — без изменений; MIME
    edit-запроса соответствует фактическому формату (data URL от суффикса)."""
    from services.media_execution import MediaSubmitResult
    from services import cover_style_edit as cse
    from services import mca_vision as mv
    from services import telegram_send

    _patch_image_sources(monkeypatch)
    _patch_edit_caps(monkeypatch, edit_value="yes")
    caps.invalidate(None, None, reason="test")
    seen_suffixes: list[str] = []
    seen_data_mimes: list[str] = []

    class _FakeAdapter:
        name = "nanogpt"

        async def submit_edit(self, *, prompt, model, image_paths, **kwargs):
            path = image_paths[0]
            seen_suffixes.append(path)
            seen_data_mimes.append(cse._data_url(path).split(";")[0])
            return MediaSubmitResult(ok=True, content=b"edited", reason="ok")

    import services.media_execution as me
    monkeypatch.setattr(me, "detect_adapter",
                        lambda base_url: _FakeAdapter())

    async def _fake_send(bot, chat_id, photo, **kwargs):
        return object()

    monkeypatch.setattr(telegram_send, "send_photo", _fake_send)

    class _FakeDb:
        async def get_media_assets_for_message(self, chat_id, tg_id):
            return [{"asset_kind": "photo", "file_id": "fid_1",
                     "file_unique_id": "uniq_1"}]

    router = object.__new__(ToolRouter)
    router.deps = types.SimpleNamespace(db=_FakeDb())

    for mime, suffix, data_mime in (
            ("image/jpeg", ".jpg", "data:image/jpeg"),
            ("image/webp", ".webp", "data:image/webp"),
            ("image/png", ".png", "data:image/png")):
        def _make_download(_mime=mime):
            async def _download(bot, file_id, **kwargs):
                return mv.DownloadedImage(data=b"frame-bytes", mime=_mime,
                                          declared_mime=_mime, width=4,
                                          height=4, byte_size=11)
            return _download

        monkeypatch.setattr(mv, "download_telegram_file", _make_download())
        ctx = ToolContext(CHAT, "измени", bot=object(),
                          reply_to_message_id=501)
        out = await router.dispatch(
            "edit_image", {"prompt": "измени",
                           "target": {"chat_id": CHAT, "message_id": 501}},
            ctx)
        assert json.loads(out)["status"] == "success", mime
        assert seen_suffixes[-1].endswith(suffix), mime
        assert seen_data_mimes[-1] == data_mime, mime
    assert [p.endswith(s) for p, s in
            zip(seen_suffixes, (".jpg", ".webp", ".png"))] == [True] * 3


@pytest.mark.asyncio
async def test_edit_image_uses_chat_provider_config(monkeypatch):
    """COR-01: проверка capability и исполнение используют ОДИН effective-
    набор настроек чата (per-chat override → hot → default, резолв
    capability_registry.chat_value): и resolve_capabilities (проверка), и
    submit_edit (исполнение) получают провайдера/модель/ключ этого чата.
    Новых конфигурационных систем нет."""
    from services import chat_params
    from services import image_capabilities as icap
    from services import mca_vision as mv
    from services import telegram_send
    from services.media_execution import MediaSubmitResult

    _patch_image_sources(monkeypatch)
    caps.invalidate(None, None, reason="test")

    class _FakeParamsCache:
        async def get_chat_params(self, chat_id):
            return {"overrides": {
                "models.image_base_url": "https://chat-a.example/v1",
                "models.image_model": "chat-model-a",
                "keys.image_api_key": "chat-key-a",
            }}

    chat_params.set_chat_params_cache(_FakeParamsCache())
    try:
        check_calls = []

        def _capture_caps(provider, base_url, model, **kwargs):
            check_calls.append({"provider": provider, "base_url": base_url,
                                "model": model})
            caps_obj = icap.conservative_unknown()
            caps_obj.image_edit = "yes"
            return caps_obj

        monkeypatch.setattr(icap, "resolve_capabilities", _capture_caps)

        exec_calls = []
        adapter_base = []

        class _FakeAdapter:
            name = "nanogpt"

            async def submit_edit(self, *, prompt, model, image_paths,
                                  **kwargs):
                exec_calls.append({"model": model,
                                   "api_key": kwargs.get("api_key")})
                return MediaSubmitResult(ok=True, content=b"edited",
                                         reason="ok")

        def _detect(base_url):
            adapter_base.append(base_url)
            return _FakeAdapter()

        import services.media_execution as me
        monkeypatch.setattr(me, "detect_adapter", _detect)

        async def _fake_download(bot, file_id, **kwargs):
            return mv.DownloadedImage(data=b"png", mime="image/png",
                                      declared_mime="image/png", width=2,
                                      height=2, byte_size=4)

        async def _fake_send(bot, chat_id, photo, **kwargs):
            return object()

        monkeypatch.setattr(mv, "download_telegram_file", _fake_download)
        monkeypatch.setattr(telegram_send, "send_photo", _fake_send)

        class _FakeDb:
            async def get_media_assets_for_message(self, chat_id, tg_id):
                return [{"asset_kind": "photo", "file_id": "fid_1",
                         "file_unique_id": "uniq_1"}]

        router = object.__new__(ToolRouter)
        router.deps = types.SimpleNamespace(db=_FakeDb())
        ctx = ToolContext(CHAT, "измени", bot=object(),
                          reply_to_message_id=501)
        out = await router.dispatch(
            "edit_image", {"prompt": "измени",
                           "target": {"chat_id": CHAT, "message_id": 501}},
            ctx)
        assert json.loads(out)["status"] == "success"
        # Исполнение — на настройках ЧАТА (не глобальных):
        assert adapter_base == ["https://chat-a.example/v1"]
        assert exec_calls == [{"model": "chat-model-a",
                               "api_key": "chat-key-a"}]
        # Проверка способности — тот же effective-набор (тот же провайдер):
        assert check_calls and \
            check_calls[0]["base_url"] == "https://chat-a.example/v1"
        assert check_calls[0]["model"] == "chat-model-a"
        assert check_calls[0]["provider"] == "chat-a.example"
    finally:
        chat_params.set_chat_params_cache(None)


# ════════════════════════════════════════════════════════════════════════════
# REQ-GEN-CONTEXT (§21): уточняющий вопрос не повторяется
# ════════════════════════════════════════════════════════════════════════════

def test_clarify_not_repeated_within_ttl(monkeypatch):
    from services.direct_chat_service import DirectChatService
    svc = object.__new__(DirectChatService)
    svc._CLARIFY_REPEAT_SECONDS = 600.0
    assert svc._clarify_recently(CHAT) is False
    svc._mark_clarify_sent(CHAT)
    assert svc._clarify_recently(CHAT) is True
    # TTL истёк → вопрос можно задать снова (не «навсегда заглушен»).
    from services.direct_chat_service import _CLARIFY_TS
    _CLARIFY_TS[int(CHAT)] = time.monotonic() - 601.0
    assert svc._clarify_recently(CHAT) is False


# ════════════════════════════════════════════════════════════════════════════
# REQ-ADMIN-TYPES (§22): подраздел «Типы медиа»
# ════════════════════════════════════════════════════════════════════════════

def test_media_types_group_and_params_registered():
    from services import param_catalog as pc
    spec = pc.REGISTRY.get("VISION_MEDIA_PHOTO_DOCS")
    assert spec is not None and spec.pg_key == "flags.vision_media_photo_docs"
    assert spec.per_chat is True          # настройки отдельных чатов
    for field, key in (
            ("VISION_MEDIA_PHOTO_DOCS", "flags.vision_media_photo_docs"),
            ("VISION_MEDIA_STATIC_STICKERS",
             "flags.vision_media_static_stickers"),
            ("VISION_MEDIA_GIF_ANIMATIONS",
             "flags.vision_media_gif_animations"),
            ("VISION_MEDIA_ANIMATED_STICKERS",
             "flags.vision_media_animated_stickers"),
            ("VISION_MEDIA_VIDEO_PREVIEWS",
             "flags.vision_media_video_previews")):
        item = pc.REGISTRY.get(field)
        assert item is not None, field
        assert item.pg_key == key
        assert item.group == "flags_vision_media_types"
    groups = {g.id for g in pc.groups_by_category("flags")}
    assert "flags_vision_media_types" in groups
    # Подраздел живёт на вкладке «Модули → Распознавание изображений»
    # (отдельного GIF-модуля/второго Vision-раздела нет).
    assert pc.group_tab("flags_vision_media_types") == pc.TAB_MOD_VISION


def test_media_type_for_asset_matrix():
    assert mca_vision.media_type_for_asset("photo") == "photo_docs"
    assert mca_vision.media_type_for_asset("document") == "photo_docs"
    assert mca_vision.media_type_for_asset("sticker") == "static_stickers"
    assert mca_vision.media_type_for_asset("animation", "animation") == \
        "gif_animations"
    assert mca_vision.media_type_for_asset("animation", "sticker") == \
        "animated_stickers"
    assert mca_vision.media_type_for_asset("animation_preview",
                                           "animation_preview") == \
        "gif_animations"
    assert mca_vision.media_type_for_asset("animation_preview",
                                           "sticker_preview") == \
        "animated_stickers"
    assert mca_vision.media_type_for_asset("video_preview",
                                           "video_preview") == \
        "video_previews"
    assert mca_vision.media_type_for_asset("video_preview",
                                           "video_note_preview") == \
        "video_previews"


@pytest.mark.asyncio
async def test_media_type_default_enabled_and_hot_override(monkeypatch):
    from tests.test_mca19_block_b_round1043 import patched_settings
    # Заводское значение — включено при включённом модуле.
    assert await mca_vision.resolve_media_type_enabled(CHAT,
                                                       "photo_docs") is True
    with patched_settings(VISION_MEDIA_GIF_ANIMATIONS=False):
        # hot-слой отсутствует → Settings-дефолт.
        assert await mca_vision.resolve_media_type_enabled(
            CHAT, "gif_animations") is False


@pytest.mark.asyncio
async def test_enqueue_gates_disabled_media_type(tmp_path, monkeypatch):
    """Выключенный тип медиа → джоба авто-разбора не создаётся; канонический
    реестр активов остаётся (главный тумблер Vision не сужается)."""
    from tests.test_mca19_block_c_round1043 import (
        CHAT_A, _fresh, _photo_message, _queued_jobs)
    from tests.test_mca19_block_b_round1043 import patched_settings

    db = await _fresh(tmp_path, name="asap5types.db")
    mca_vision.reset_runtime()
    real_get = hot.get

    def _hot_get(key, default=None):
        if key == "flags.vision_media_photo_docs":
            return False
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", _hot_get)
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY="", VISION_MEDIA_PHOTO_DOCS=True):
        msg = _photo_message(chat_id=CHAT_A, tg_id=101)
        asset_ids = await mca_vision.register_intake_assets(db, msg)
        assert len(asset_ids) == 1
        # Реестр остался, enqueue-гейт отсёк авто-разбор.
        assert await db.get_media_assets_for_message(CHAT_A, 101)
        assert await mca_vision.enqueue_intake_jobs(db, msg, asset_ids) == 0
        assert not await _queued_jobs(db)
        # Тот же тип включён → джоба создаётся (заводское поведение).
        monkeypatch.setattr(hot, "get", real_get)
        mca_vision.reset_runtime()
        msg2 = _photo_message(chat_id=CHAT_A, tg_id=102)
        asset_ids2 = await mca_vision.register_intake_assets(db, msg2)
        assert await mca_vision.enqueue_intake_jobs(db, msg2, asset_ids2) == 1
        assert await _queued_jobs(db)


# ════════════════════════════════════════════════════════════════════════════
# REQ-ADMIN-DIAG (§22): диагностика из существующих записей
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_runtime_snapshot_diag_fields_no_db():
    snapshot = await mca_vision.runtime_snapshot(db=None, chat_id=CHAT)
    types_ = snapshot["media_types"]
    labels = [t["type"] for t in types_]
    assert labels == ["photo_docs", "static_stickers", "gif_animations",
                      "animated_stickers", "video_previews"]
    # Заводские значения — включены.
    assert all(t["enabled"] for t in types_)
    # Типы, требующие преобразования (исходник не анализируется).
    assert snapshot["types_need_transform"] == ["gif_animations",
                                                "animated_stickers",
                                                "video_previews"]


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return list(self._rows)


class _FakeRawDb:
    """aiosqlite-подобный двойник с scripted-ответами на SQL."""

    def __init__(self):
        self.queries: list[str] = []

    async def execute(self, sql, *params):
        self.queries.append(sql)
        if "COUNT(*)" in sql:
            return _FakeCursor([{"n": 3}])
        if "reason_code" in sql:
            return _FakeCursor([{"reason_code": "download_failed",
                                 "updated_at": 1760000000}])
        return _FakeCursor([])


class _FakeStore:
    def __init__(self, db):
        self.db = db

    async def depth(self):
        return 5

    async def active(self):
        return [{"kind": mca_vision.VISION_JOB_KIND, "status": "running"}]


@pytest.mark.asyncio
async def test_runtime_snapshot_queue_counts_and_last_error(monkeypatch):
    import services.task_supervisor as ts
    monkeypatch.setattr(ts, "TaskJobStore", _FakeStore)
    raw = _FakeRawDb()

    class _Db:
        self_db = raw

    db = types.SimpleNamespace(db=raw)
    snapshot = await mca_vision.runtime_snapshot(db=db, chat_id=CHAT)
    assert snapshot["queue"]["queued"] == 5
    assert snapshot["queue"]["running"] == 1
    # Завершённые с ошибкой — из существующих durable-строк.
    assert snapshot["queue"]["failed"] == 3
    assert snapshot["last_error"]["reason_code"] == "download_failed"
