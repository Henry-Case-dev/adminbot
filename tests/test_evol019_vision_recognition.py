"""EVOL-019 — «Проверить распознавание»: HTTP 200 ≠ распознавание работает.

TEST-LIFECYCLE: CONTRACT (plans/current_task.md EVOL-019).

Проверяется РАЗДЕЛЕНИЕ состояний, а не только happy-path:
  * 200 + не-JSON, 200 + пустой content, 200 + неверная схема — три РАЗНЫЕ
    причины, и ни одна из них не «распознавание работает»;
  * реальная фикстура через действующий маршрут (stubbed провайдер) →
    `content_received` True + безопасный образец;
  * отказ модальности ≠ «изображение не принято» ≠ таймаут;
  * в Telegram ничего не отправляется, сеть подменена транспортом.
"""
import time
from contextlib import contextmanager

import pytest

from config.settings import settings
from services import mca_vision

VISION_BASE = "http://vlm.local/v1"


@contextmanager
def patched_settings(**kw):
    """Подмена instance-полей frozen Settings с гарантированным откатом."""
    saved = {k: getattr(settings, k) for k in kw}
    for k, v in kw.items():
        object.__setattr__(settings, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            object.__setattr__(settings, k, v)


@pytest.fixture(autouse=True)
def _clean_state():
    mca_vision.reset_capability_cache()
    with patched_settings(VISION_API_BASE_URL=VISION_BASE,
                          VISION_MODEL="test-vlm",
                          VISION_API_KEY="test-key",
                          VISION_API_TYPE="openai_compatible"):
        yield
    mca_vision.reset_capability_cache()


def _route():
    route = mca_vision.resolve_route()
    assert route.base_url == VISION_BASE
    return route


def _transport(status, body, raw=None):
    """Транспорт проверки: (status, body, raw). `raw=None` — тело неизвестно."""
    calls = []

    async def _call(url, *, payload, headers, timeout):
        calls.append({"url": url, "payload": payload, "headers": headers})
        if raw is not None:
            return status, body, raw
        return status, body

    _call.calls = calls
    return _call


def _content_transport(text, status=200):
    body = {"choices": [{"message": {"role": "assistant",
                                     "content": text}}]}
    return _transport(status, body, raw='{"choices": [...]}')


@pytest.mark.asyncio
async def test_real_fixture_recognition_returns_content():
    """Реальная фикстура через действующий маршрут → получено содержимое."""
    transport = _content_transport("  тёмно-синий   фон с белой панелью ")
    result = await mca_vision.recognition_check(transport=transport)

    assert result["state"] == "recognized"
    assert result["terminal_reason"] == mca_vision.RC_RECOGNIZED
    assert result["config_ok"] is True
    assert result["provider_reachable"] is True
    assert result["media_accepted"] is True
    assert result["recognition_completed"] is True
    assert result["content_received"] is True
    assert result["content_sample"] == "тёмно-синий фон с белой панелью"
    assert result["content_chars"] > 0
    assert result["model"] == "test-vlm"
    assert result["fixture"]["mime"] == "image/png"
    assert result["fixture"]["width"] >= 512
    assert result["paid_call"] is True
    assert result["duration_ms"] >= 0
    assert result["timestamp"].endswith("Z")
    # Запрос ушёл ровно один раз и только на chat-completions маршрута.
    assert len(transport.calls) == 1
    assert transport.calls[0]["url"].endswith("/chat/completions")
    # Фикстура — локальная, без пользовательских медиа.
    assert result["fixture"]["source"] == "generated_in_process"


@pytest.mark.asyncio
async def test_http_200_non_json_is_not_working():
    """200 с не-JSON телом — НЕ «распознавание работает»."""
    transport = _transport(200, None, raw="<html>gateway</html>")
    result = await mca_vision.recognition_check(transport=transport)

    assert result["provider_reachable"] is True
    assert result["media_accepted"] is True
    assert result["recognition_completed"] is False
    assert result["content_received"] is False
    assert result["state"] == "schema_invalid"
    assert result["terminal_reason"] == mca_vision.RC_RESPONSE_NOT_JSON
    assert "не является JSON" in result["terminal_reason_label"]


@pytest.mark.asyncio
async def test_empty_content_is_a_separate_state():
    """Пустой текст ≠ битый JSON ≠ успех: три различимые причины."""
    empty = await mca_vision.recognition_check(
        transport=_content_transport("   "))
    non_json = await mca_vision.recognition_check(
        transport=_transport(200, None, raw="not-json"))
    schema = await mca_vision.recognition_check(
        transport=_transport(200, {"result": "ok"}, raw='{"result":"ok"}'))
    good = await mca_vision.recognition_check(
        transport=_content_transport("панель"))

    reasons = {empty["terminal_reason"], non_json["terminal_reason"],
               schema["terminal_reason"], good["terminal_reason"]}
    assert reasons == {mca_vision.RC_EMPTY_CONTENT,
                       mca_vision.RC_RESPONSE_NOT_JSON,
                       mca_vision.RC_SCHEMA_INVALID,
                       mca_vision.RC_RECOGNIZED}
    assert empty["state"] == "content_empty"
    assert empty["content_received"] is False
    # Схема валидна у completion, но текст пуст → это «распознавание без
    # результата», а не «работает».
    assert empty["recognition_completed"] is False


@pytest.mark.asyncio
async def test_empty_body_and_empty_choices_are_distinct():
    empty_body = await mca_vision.recognition_check(
        transport=_transport(200, None, raw="   "))
    no_choices = await mca_vision.recognition_check(
        transport=_transport(200, {"choices": []}, raw='{"choices": []}'))

    assert empty_body["terminal_reason"] == mca_vision.RC_EMPTY_BODY
    assert no_choices["terminal_reason"] == mca_vision.RC_EMPTY_CHOICES
    assert empty_body["content_received"] is False
    assert no_choices["content_received"] is False
    assert no_choices["media_accepted"] is True


@pytest.mark.asyncio
async def test_access_denied_and_rate_limit_are_not_media_rejection():
    denied = await mca_vision.recognition_check(
        transport=_transport(401, {"error": {"message": "invalid api key"}}))
    limited = await mca_vision.recognition_check(
        transport=_transport(429, {"error": {"message": "rate limit"}}))

    assert denied["terminal_reason"] == mca_vision.RC_ACCESS_DENIED
    assert denied["media_accepted"] is None
    assert denied["provider_reachable"] is True
    assert limited["terminal_reason"] == mca_vision.RC_RATE_LIMITED
    assert denied["state"] == "access_denied"
    assert limited["state"] == "rate_limited"


@pytest.mark.asyncio
async def test_modality_refusal_vs_image_rejection():
    refusal = await mca_vision.recognition_check(
        transport=_transport(400, {"error": {
            "message": "This model does not support image input"}}))
    rejection = await mca_vision.recognition_check(
        transport=_transport(400, {"error": {
            "message": "invalid image: could not decode"}}))

    assert refusal["terminal_reason"] == mca_vision.RC_MODALITY
    assert refusal["media_accepted"] is False
    assert rejection["terminal_reason"] == mca_vision.RC_MEDIA_REJECTED
    assert rejection["media_accepted"] is False
    # Оба — «не принято», но по РАЗНЫМ причинам (модальность ≠ формат файла).
    assert refusal["state"] == rejection["state"] == "not_accepted"


@pytest.mark.asyncio
async def test_timeout_and_transport_errors_are_unreachable():
    import httpx

    async def timeout_transport(url, *, payload, headers, timeout):
        raise httpx.ReadTimeout("slow")

    async def broken_transport(url, *, payload, headers, timeout):
        raise RuntimeError("socket closed")

    timeout_res = await mca_vision.recognition_check(
        transport=timeout_transport)
    broken_res = await mca_vision.recognition_check(
        transport=broken_transport)

    assert timeout_res["terminal_reason"] == mca_vision.RC_TIMEOUT
    assert timeout_res["provider_reachable"] is None
    assert timeout_res["media_accepted"] is None
    assert broken_res["terminal_reason"] == mca_vision.RC_TRANSPORT
    assert broken_res["state"] == "unreachable"


@pytest.mark.asyncio
async def test_misconfiguration_spends_no_budget():
    transport = _transport(200, {"choices": []}, raw='{"choices":[]}')
    with patched_settings(VISION_API_KEY="", LLM_API_KEY="", VISION_MODEL=""):
        route = mca_vision.resolve_route()
        result = await mca_vision.recognition_check(route=route,
                                                    transport=transport)

    assert result["config_ok"] is False
    assert result["terminal_reason"] in (mca_vision.RC_NOT_CONFIGURED,
                                         mca_vision.RC_KEY_MISSING)
    assert result["paid_call"] is False
    assert transport.calls == []          # бюджет не тратится на конфиг-ошибку
    assert result["state"] == "misconfigured"


@pytest.mark.asyncio
async def test_pipeline_readiness_is_derived_and_limited():
    """Готовность pipeline — производная, и она не выдаётся за доказательство."""
    route = _route()
    mca_vision.store_capability(route, mca_vision.CapabilityVerdict(
        "ok", "", True, time.monotonic()))
    with patched_settings(VISION_ENABLED=True):
        result = await mca_vision.recognition_check(
            transport=_content_transport("белая панель на тёмном фоне"))
    assert result["pipeline"]["ready"] is True
    assert result["pipeline"]["reason"] == "recognition_proven"
    assert "не подтверждает" in result["pipeline"]["note"]

    mca_vision.reset_capability_cache()
    with patched_settings(VISION_ENABLED=True):
        pending = await mca_vision.recognition_check(
            transport=_content_transport("белая панель"))
    assert pending["pipeline"]["ready"] is False
    assert pending["pipeline"]["reason"] == "module_check_pending"


@pytest.mark.asyncio
async def test_media_coverage_is_honest_about_untested_types():
    result = await mca_vision.recognition_check(
        transport=_content_transport("панель"))
    coverage = {m["type"]: m for m in result["media_coverage"]}
    assert coverage["photo_docs"]["tested_by_this_check"] is True
    for untested in ("gif_animations", "animated_stickers", "video_previews",
                     "static_stickers"):
        assert coverage[untested]["tested_by_this_check"] is False
        assert "не подтверждено" in coverage[untested]["note"]


@pytest.mark.asyncio
async def test_content_sample_is_bounded_and_single_line():
    long_text = "строка\n" * 200
    result = await mca_vision.recognition_check(
        transport=_content_transport(long_text))
    assert result["content_received"] is True
    assert len(result["content_sample"]) <= 160
    assert "\n" not in result["content_sample"]


def test_reason_dictionary_maps_to_event_codes():
    """Каждая причина имеет RU-текст и код состояния; событие опыта —
    только существующим словарём reason_code (второй словарь запрещён)."""
    from services.mca_events import REASON_CODES

    for reason, (state, label) in mca_vision.RECOGNITION_REASONS.items():
        assert label, reason
        assert mca_vision.recognition_state_for(reason) == state
        event_code = mca_vision._RECOGNITION_EVENT_REASON.get(reason)
        assert event_code is not None, reason
        if event_code:
            assert event_code in REASON_CODES, (reason, event_code)
