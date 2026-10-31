"""EVOL-014 (Wave 4 UI) — настройки мемов внутри модуля «Инициатива».

TEST-LIFECYCLE: CONTRACT owner=EVOL-014

Сервисный контракт (квота/выжимка/публикация) — в
`tests/test_evol014_meme_initiative.py`. Здесь — админский слой:
  * GET отдаёт настройки/квоту дня/аналитику/шаблон промпта/эффективный
    потолок длины/отношение к публикации для КОНКРЕТНОГО чата;
  * недоступность (инициатива выключена / image-провайдер не настроен)
    приходит с конкретной причиной, а не общим «не работает»;
  * POST: RBAC как у per-chat настроек, валидация (тихие часы), запись
    per-chat override, мастер модуля не меняется;
  * витрина: свой тумблер (не мастер), квота «1 / 3», остаток/сброс/пояс,
    стадии и причины пропусков, шаблон (заводской/ручной), объяснение
    «будет ли отправлено».
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services import meme_initiative as mi
from tests.test_webapp_api import ADMIN_ID, USER_ID, _FakeConn, _FakePg, _hdr
from web.api import routes as routes_mod
from web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
CHAT_A = -100111
CHAT_B = -100222
LOCAL_ADMIN_ID = 424242424
ENDPOINT = "/api/initiative/meme-settings"


class _ProfileConn(_FakeConn):
    """PG-двойник с профилем чата: читает и пишет `chat_params`."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.params = {"overrides": {}, "meta": {}}
        self.writes = []

    async def fetchrow(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        low = str(sql).lower().lstrip()
        if low.startswith("update chat_profiles") and "chat_params" in low:
            self.params = json.loads(args[1])
            self.writes.append(dict(self.params.get("overrides") or {}))
            return {"chat_id": args[0], "updated_at": "2026-10-31T00:00:00+00:00",
                    "chat_params": json.dumps(self.params), "gates_opt_in": False}
        if low.startswith("select chat_id") and "chat_profiles" in low:
            return {"chat_id": args[0], "updated_at": "2026-10-31T00:00:00+00:00",
                    "chat_params": json.dumps(self.params), "gates_opt_in": False}
        return None


def _build(monkeypatch, conn=None):
    monkeypatch.setattr(
        "web.api.deps.settings",
        type("S", (), {"API_TOKEN": "123456:TEST_TOKEN_FOR_API_TESTS"})())
    conn = conn or _ProfileConn(
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
    return conn, cache, app


@pytest.fixture
def client(monkeypatch):
    conn, cache, app = _build(monkeypatch)
    # Детерминированные зависимости: инициатива включена, image-провайдер
    # настроен, журнал квоты отсутствует (schema_absent — честно).
    monkeypatch.setattr(mi, "open_ledger", lambda db: None)
    from services import initiative_observer
    monkeypatch.setattr(initiative_observer, "observer_enabled", lambda: True)
    from services import image_generation as ig
    monkeypatch.setattr(ig, "resolve_module_enabled",
                        lambda chat_id=None: _true())
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: None)
    # Резолв per-chat значений — как в проде через ChatParamsCache, но здесь
    # источник — профиль фейкового PG (иначе POST не виден следующему GET).
    from services import chat_params as chat_params_srv
    from services import hot_config as hot

    async def _get_chat_param(chat_id, key, default=None):
        overrides = conn.params.get("overrides") or {}
        if key in overrides:
            return overrides[key]
        try:
            return hot.get(key, default)
        except Exception:
            return default

    monkeypatch.setattr(chat_params_srv, "get_chat_param", _get_chat_param)
    with TestClient(app) as tc:
        tc.cache = cache
        tc.conn = conn
        yield tc


async def _true():
    return True


def test_missing_auth_is_401(client):
    assert client.get(ENDPOINT, headers={}).status_code == 401


def test_chat_is_required(client):
    assert client.get(ENDPOINT, headers=_hdr()).status_code == 422


def test_plain_user_cannot_read_foreign_chat(client):
    resp = client.get(ENDPOINT, headers={**_hdr(USER_ID),
                                         "X-Chat-Id": str(CHAT_B)})
    assert resp.status_code == 403


def test_settings_quota_and_analytics_payload(client):
    resp = client.get(ENDPOINT, headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["chat_id"] == CHAT_A
    settings = body["settings"]
    assert settings["daily_limit"] == mi.DEFAULT_DAILY_LIMIT == 3
    assert settings["enabled"] is False            # default OFF
    assert settings["window_messages"] == mi.DEFAULT_WINDOW_MESSAGES
    assert settings["cooldown_seconds"] == mi.DEFAULT_COOLDOWN_SECONDS
    assert settings["min_messages"] == mi.DEFAULT_MIN_MESSAGES
    assert body["defaults"]["daily_limit"] == 3
    # Квота: 0 потрачено из 3 (журнала нет — честный schema_absent).
    quota = body["quota"]
    assert quota["available"] is False
    assert quota["reason"] == "schema_absent"
    assert quota["limit"] == 3
    assert quota["spent"] is None
    assert body["day"]["timezone_name"]
    assert body["day"]["next_reset"]
    # Аналитика отдельная от текстовой инициативы.
    assert body["analytics"]["separate_from_initiative"] is True
    assert body["analytics"]["output_kind"] == mi.OUTPUT_KIND
    assert set(body["analytics"]["counters"]) == set(mi.STAGES)
    # Шаблон картинки — из реестра, с признаком заводской/ручной.
    assert body["prompts"]["image"]["block_id"] == mi.IMAGE_PROMPT_BLOCK_ID
    assert "text" in body["prompts"]["image"]
    assert "differs_from_factory" in body["prompts"]["image"]
    assert body["image_prefix"] == mi.MEME_IMAGE_PROMPT
    # Потолок длины и его источник.
    assert set(body["length_limit"]) >= {"value", "source", "known",
                                         "summary_target"}
    # Отношение к публикации: мемы не блокируют текстовую инициативу.
    assert body["delivery"]["blocks_text_initiative"] is False
    assert "publish_blocked_count" in body["delivery"]
    # Мастер модуля — отдельный ключ (второго мастера здесь нет).
    assert body["master_key"] == "flags.initiative_enabled"
    assert body["own_key"] == mi.KEY_ENABLED
    assert "flags.initiative_enabled" not in settings


def test_unavailable_reason_is_concrete(client, monkeypatch):
    from services import initiative_observer
    monkeypatch.setattr(initiative_observer, "observer_enabled", lambda: False)
    body = client.get(ENDPOINT, headers={**_hdr(),
                                         "X-Chat-Id": str(CHAT_A)}).json()
    assert body["availability"]["available"] is False
    assert body["availability"]["reason"] == "initiative_disabled"

    monkeypatch.setattr(initiative_observer, "observer_enabled", lambda: True)
    # Мемы включены (иначе честная причина — «выключено настройкой»).
    assert client.post(ENDPOINT, json={"enabled": True},
                       headers={**_hdr(), "X-Chat-Id": str(CHAT_A)}
                       ).status_code == 200
    from services import image_generation as ig
    monkeypatch.setattr(ig, "resolve_module_enabled",
                        lambda chat_id=None: _false())
    body = client.get(ENDPOINT, headers={**_hdr(),
                                         "X-Chat-Id": str(CHAT_A)}).json()
    assert body["availability"]["reason"] == "image_module_off"


async def _false():
    return False


def test_quiet_hours_validation(client):
    resp = client.post(ENDPOINT, json={"quiet_hours": "25:99"},
                       headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
    assert resp.status_code == 422
    # Часы вне суток недопустимы даже при корректных минутах: раньше
    # «25:00-26:00» сохранялось как «тихие часы» и никогда не срабатывало.
    for bad in ("25:00-26:00", "24:00-01:00", "23:00-07:60", "7:5-9:0",
                "07:00", "07:00-"):
        resp = client.post(ENDPOINT, json={"quiet_hours": bad},
                           headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
        assert resp.status_code == 422, (bad, resp.text)
    ok = client.post(ENDPOINT, json={"quiet_hours": "23:00-07:30"},
                     headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
    assert ok.status_code == 200, ok.text
    # Пустая строка = тихие часы не заданы (снять настройку можно).
    empty = client.post(ENDPOINT, json={"quiet_hours": ""},
                        headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
    assert empty.status_code == 200, empty.text
    assert empty.json()["settings"]["quiet_hours"] in (None, "")
    # Границы суток допустимы.
    assert client.post(ENDPOINT, json={"quiet_hours": "00:00-23:59"},
                       headers={**_hdr(), "X-Chat-Id": str(CHAT_A)}
                       ).status_code == 200


def test_post_writes_chat_override_without_touching_master(client):
    resp = client.post(ENDPOINT,
                       json={"enabled": True, "daily_limit": 5,
                             "window_messages": 300, "summarizer_model": ""},
                       headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["settings"]["enabled"] is True
    assert body["settings"]["daily_limit"] == 5
    assert body["settings"]["window_messages"] == 300
    overrides = client.conn.writes[-1]
    assert overrides[mi.KEY_ENABLED] is True
    assert overrides[mi.KEY_DAILY_LIMIT] == 5
    assert overrides[mi.KEY_WINDOW] == 300
    # Мастер модуля не записан этим путём.
    assert "flags.initiative_enabled" not in overrides


def test_post_by_plain_user_is_403(client):
    resp = client.post(ENDPOINT, json={"enabled": True},
                       headers={**_hdr(USER_ID), "X-Chat-Id": str(CHAT_B)})
    assert resp.status_code == 403
    assert client.conn.writes == []


def test_post_empty_body_is_422(client):
    resp = client.post(ENDPOINT, json={},
                       headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
    assert resp.status_code == 422


def test_ui_meme_settings_block():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    block = html.split("data-meme-settings", 1)[1]
    block = block.split("data-workspace-testing", 1)[0]
    assert "data-meme-toggle" in block
    assert "data-meme-window" in block
    assert "data-meme-daily-limit" in block
    assert "data-meme-cooldown" in block
    assert "data-meme-min-messages" in block
    assert "data-meme-summarizer" in block
    assert "data-meme-quiet-hours" in block
    assert "data-meme-length-limit" in block
    assert "data-meme-quota-text" in block
    assert "data-meme-quota-remaining" in block
    assert "data-meme-quota-reset" in block
    assert "data-meme-quota-tz" in block
    assert "data-meme-analytics" in block
    assert "data-meme-skip-reasons" in block
    assert "data-meme-prompt-source" in block
    assert "data-meme-delivery" in block
    assert "data-meme-unavailable" in block
    # Второго мастер-тумблера модуля нет (EVOL-035/040): только своя ось.
    assert "flags.initiative_enabled" not in block
    assert "toggleModule" not in block
    # Мастер остаётся в каталоге модулей (app.js MODULES).
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "toggleKey: 'flags.initiative_enabled'" in js
    # L-F11S-1 (EVOL-027 v0.8, W10): в шапке деталей модуля тождественного
    # master-toggle БОЛЬШЕ НЕТ (plans/current_task.md L389) — только read-only
    # статус и ссылка «Управляется из каталога», где живёт единственный
    # глобальный тумблер.
    assert "toggleModule(workspaceModule" not in html
    assert "data-module-managed-link" in html


def test_ui_quota_text_is_generated_from_server_data():
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    view = js.split("memeSettingsView: function ()", 1)[1]
    view = view.split("expPipelineView: function ()", 1)[0]
    assert "Генерации сегодня:" in view
    assert "Осталось:" in view
    assert "limit === 0" in view          # 0 = выключено, честная подпись
    assert "schemaPresent" in view
    assert "memeUnavailableLabel" in js
    assert "'/api/initiative/meme-settings'" in js
