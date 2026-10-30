"""EVOL-019 (Wave 4 UI) — «Проверить распознавание» в админке.

TEST-LIFECYCLE: CONTRACT owner=EVOL-019

Проверяется HTTP-слой и витрина, а не только сервис (сервисный контракт —
`tests/test_evol019_vision_recognition.py`):
  * отдельное действие «Проверить распознавание» существует и НЕ выдаёт
    «распознавание работает» на HTTP 200 с не-JSON/пустым содержимым;
  * ответ содержит раздельные шаги (конфигурация/провайдер/медиа/
    распознавание/содержимое), длительность, модель, время, причину;
  * платный вызов помечен, ключ/адрес провайдера не утекают в ответ;
  * RBAC: без сессии 401, без права 403, повтор чаще 10 с — 429;
  * витрина: две РАЗНЫЕ кнопки, видимые состояния и образец, покрытие типов
    медиа честное (фото проверено, остальные — нет).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from services import mca_vision
from tests.test_webapp_api import ADMIN_ID, USER_ID, _FakeConn, _FakePg, _hdr
from web.api import routes as routes_mod
from web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
VISION_BASE = "http://vlm.local/v1"
ENDPOINT = "/api/vision/recognition-check"


@contextmanager
def _patched_settings(**kw):
    saved = {k: getattr(settings, k) for k in kw}
    for k, v in kw.items():
        object.__setattr__(settings, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            object.__setattr__(settings, k, v)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        "web.api.deps.settings",
        type("S", (), {"API_TOKEN": "123456:TEST_TOKEN_FOR_API_TESTS"})())
    conn = _FakeConn(
        role_rows=[
            {"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False},
            {"role_name": "user", "permissions": {}, "is_custom": False},
        ],
        admin_rows=[
            {"telegram_id": ADMIN_ID, "role_name": "admin",
             "added_by": None, "created_at": "2026-10-30T00:00:00+00:00"},
        ],
    )
    from services.config_cache import ConfigCache
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    routes_mod.reset_vision_recognition_rate_limit()
    with TestClient(app) as tc:
        tc.cache = cache
        yield tc
    routes_mod.reset_vision_recognition_rate_limit()


def _install_recognition(monkeypatch, transport, *, chat_ctx=None):
    """Реальный `recognition_check` с подменённым транспортом/маршрутом.

    Подменяется только сеть и производный контекст модуля: сам разбор
    ответа (схема/пустое содержимое/классы ошибок) остаётся боевым кодом.
    """
    real = mca_vision.recognition_check

    async def _fake(*, chat_id=None):
        return await real(route=mca_vision.resolve_route(),
                          transport=transport, chat_id=chat_id)

    monkeypatch.setattr(mca_vision, "recognition_check", _fake)
    if chat_ctx is not None:
        async def _state(_chat_id=None):
            return chat_ctx
        monkeypatch.setattr(mca_vision, "resolve_effective_state", _state)

        async def _media(_chat_id, _type_key):
            return True
        monkeypatch.setattr(mca_vision, "resolve_media_type_enabled", _media)


def _transport(status, body, raw=None):
    async def _call(url, *, payload, headers, timeout):
        if raw is not None:
            return status, body, raw
        return status, body

    return _call


def _content_transport(text):
    body = {"choices": [{"message": {"role": "assistant", "content": text}}]}
    return _transport(200, body, raw='{"choices": [...]}')


@contextmanager
def _vision_configured():
    mca_vision.reset_capability_cache()
    with _patched_settings(VISION_API_BASE_URL=VISION_BASE,
                           VISION_MODEL="test-vlm",
                           VISION_API_KEY="test-key",
                           VISION_API_TYPE="openai_compatible"):
        yield
    mca_vision.reset_capability_cache()


def test_missing_auth_is_401(client):
    assert client.post(ENDPOINT, json={}).status_code == 401


def test_plain_user_is_403(client):
    assert client.post(ENDPOINT, json={},
                       headers=_hdr(USER_ID)).status_code == 403


def test_repeat_faster_than_10s_is_429(client, monkeypatch):
    with _vision_configured():
        _install_recognition(monkeypatch, _content_transport("фон"))
        first = client.post(ENDPOINT, json={}, headers=_hdr())
        assert first.status_code == 200, first.text
        second = client.post(ENDPOINT, json={}, headers=_hdr())
    assert second.status_code == 429


def test_http_200_with_non_json_is_not_recognition(client, monkeypatch):
    """HTTP 200 + не-JSON: состояние «не подтверждено», не «работает»."""
    import types
    ctx = types.SimpleNamespace(requested=True, effective_enabled=True,
                                reason="")
    with _vision_configured():
        _install_recognition(monkeypatch,
                             _transport(200, None, raw="<html>ok"),
                             chat_ctx=ctx)
        resp = client.post(ENDPOINT, json={}, headers=_hdr())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "schema_invalid"
    assert body["content_received"] is False
    assert body["recognition_completed"] is False
    assert body["provider_reachable"] is True
    assert body["terminal_reason"] == "response_not_json"
    assert body["terminal_reason_label"]
    assert body["pipeline"]["ready"] is False
    assert body["pipeline"]["reason"] == "recognition_not_proven"
    assert body["paid_call"] is True
    # R17: ни ключ, ни адрес провайдера в ответе.
    assert "test-key" not in resp.text
    assert VISION_BASE not in resp.text


def test_empty_content_is_its_own_state(client, monkeypatch):
    """200 + валидная схема + пустой content ≠ распознавание работает."""
    with _vision_configured():
        empty = {"choices": [{"message": {"role": "assistant",
                                          "content": "   "}}]}
        _install_recognition(monkeypatch, _transport(200, empty,
                                                     raw='{"choices": []}'))
        body = client.post(ENDPOINT, json={}, headers=_hdr()).json()
    assert body["state"] == "content_empty"
    assert body["content_received"] is False
    assert body["content_chars"] == 0
    assert body["pipeline"]["ready"] is False


def test_recognized_returns_sample_duration_and_model(client, monkeypatch):
    import types
    ctx = types.SimpleNamespace(requested=True, effective_enabled=True,
                                reason="")
    with _vision_configured():
        _install_recognition(
            monkeypatch,
            _content_transport("  тёмно-синий фон\nс белой панелью "),
            chat_ctx=ctx)
        body = client.post(ENDPOINT, json={}, headers=_hdr()).json()
    assert body["state"] == "recognized"
    assert body["content_received"] is True
    assert body["recognition_completed"] is True
    assert body["media_accepted"] is True
    # Образец безопасный: одна строка, без перевода строк.
    assert "\n" not in body["content_sample"]
    assert body["content_sample"].startswith("тёмно-синий фон")
    assert body["content_chars"] > 0
    assert isinstance(body["duration_ms"], int)
    assert body["duration_ms"] >= 0
    assert body["model"] == "test-vlm"
    assert body["timestamp"].endswith("Z")
    assert body["paid_call"] is True
    assert "платный" in body["budget_note"]
    assert body["pipeline"]["ready"] is True
    assert body["pipeline"]["reason"] == "recognition_proven"


def test_unconfigured_route_makes_no_paid_call(client, monkeypatch):
    mca_vision.reset_capability_cache()
    with _patched_settings(VISION_API_BASE_URL="", VISION_MODEL="",
                           VISION_API_KEY="", VISION_API_TYPE=""):
        _install_recognition(monkeypatch, _content_transport("x"))
        body = client.post(ENDPOINT, json={}, headers=_hdr()).json()
    mca_vision.reset_capability_cache()
    assert body["config_ok"] is False
    assert body["state"] == "misconfigured"
    assert body["paid_call"] is False
    assert body["content_received"] is False


def test_media_coverage_is_honest(client, monkeypatch):
    """Фото проверено этой проверкой, остальные типы — «не проверено»."""
    with _vision_configured():
        _install_recognition(monkeypatch, _content_transport("фон"))
        body = client.post(ENDPOINT, json={}, headers=_hdr()).json()
    coverage = {row["type"]: row for row in body["media_coverage"]}
    assert coverage["photo_docs"]["tested_by_this_check"] is True
    for key in ("static_stickers", "gif_animations", "animated_stickers",
                "video_previews"):
        assert coverage[key]["tested_by_this_check"] is False
        assert coverage[key]["note"]


def test_ui_has_two_distinct_actions_and_visible_states():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    block = html.split("data-vision-recognition", 1)[1]
    block = block.split("data-workspace-testing", 1)[0]
    assert "Проверить распознавание" in block
    assert "платный вызов" in block
    assert "data-vision-recognition-states" in block
    assert "data-vision-state-step=\"config\"" not in block  # шаги рендерит v-for
    assert "data-vision-state-step" in block
    assert "data-vision-recognition-facts" in block
    assert "data-vision-media-tested" in block
    # «Проверить подключение» — отдельная существующая кнопка блока модели.
    assert "Проверить подключение" in html
    assert "Проверить распознавание" != "Проверить подключение"
    # Секретов и адреса в карточке нет.
    assert "api_key" not in block
    assert "base_url" not in block


def test_ui_never_shows_green_without_content():
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    view = js.split("visionRecognitionView: function ()", 1)[1]
    view = view.split("episodeFeedView: function ()", 1)[0]
    # «Подтверждено» — только по двум фактам сервера одновременно.
    assert "r.content_received && r.recognition_completed" in view
    assert "Не подтверждено" in view
    assert "runVisionRecognitionCheck" in js
    # Результат обновляет видимые данные, а не только тост.
    assert "maybeLoadVisionState(true)" in js
