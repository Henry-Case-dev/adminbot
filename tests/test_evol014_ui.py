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

# EPIC-PROMPT-VERSIONING-UX-01 §3: запись значения промпта идёт единым
# журнальным слоем — тестам нужен стор (общая фикстура conftest).
pytestmark = pytest.mark.usefixtures("prompt_journal")

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

    async def _get_chat_param_sourced(chat_id, key, default=None):
        overrides = conn.params.get("overrides") or {}
        if key in overrides:
            return overrides[key], "chat"
        try:
            return hot.get(key, default), "global"
        except Exception:
            return default, "global"

    monkeypatch.setattr(chat_params_srv, "get_chat_param_sourced",
                        _get_chat_param_sourced)
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
    # Потолок длины и его источник: ТОЛЬКО канонические имена (алиасы
    # `value`/`prefix_chars`/`summary_target` удалены в P4 — одно число, одно
    # имя). Три числа §3 ТЗ считаются от эффективного шаблона.
    assert set(body["length_limit"]) == {
        "ceiling", "source", "mode", "template_chars", "joke_budget", "known",
        "placeholder", "candidates"}
    assert body["length_limit"]["known"] is False      # модель не прочитана
    assert body["length_limit"]["mode"] == "auto"      # P0.5: пусто = авто
    assert body["length_limit"]["ceiling"] is None
    # В режиме АВТО числа бюджета нет: `null`, а не «0 символов».
    assert body["length_limit"]["joke_budget"] is None
    assert isinstance(body["length_limit"]["template_chars"], int)
    assert body["template"]["text"] == body["prompts"]["image"]["text"]
    assert body["template"]["valid"] is True
    assert body["template"]["placeholders"] in (0, 1)
    # Оба промпта — редактируемые ключи каталога (не пассивный текст).
    for name in ("joke", "image"):
        view = body["prompts"][name]
        assert view["setting_key"].startswith("prompts.meme_")
        assert view["source"] in ("chat", "global", "factory", "registry")
        assert isinstance(view["text"], str) and view["text"]
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


DIAG = "/api/initiative/mechanism-diagnostics"


def test_mechanism_diagnostics_endpoint_returns_two_separate_blocks(client):
    """P4 (`MEME-IIC-DIAG-UI`): API отдаёт ДВА блока, не склеивая их.

    Без журнала/состояния блоки честно «нет данных», но оба присутствуют и
    названы по контракту P9 — карточка не собирает их сама.
    """
    resp = client.get(DIAG, headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == 1
    assert body["chat_id"] == CHAT_A
    text = body["text_initiative"]
    meme = body["meme"]
    assert text["mechanism"] == "text_initiative"
    assert meme["mechanism"] == "meme"
    assert text["output_kind"] == "initiative_reply"
    assert meme["output_kind"] == mi.OUTPUT_KIND
    # Ключи блоков — контракт P9 (ничего не добавлено и не переименовано).
    from services import initiative_diagnostics as diag
    assert set(text) == set(diag.MECHANISM_BLOCK_FIELDS)
    assert set(meme) == set(diag.MECHANISM_BLOCK_FIELDS)
    # «Нет данных» — флаг + коды причин, а не нули вместо неизвестного.
    for block in (text, meme):
        assert block["available"] is False
        assert block["data_state"] == "no_data"
        assert block["no_data_reasons"]
        assert block["last_check_ts"] is None      # «никогда», не 0/1970
    # Показатели не смешаны: у текста стадий нет, у мема список брони пуст.
    assert text["stages"] is None
    assert meme["blocking"] is None
    assert isinstance(body["degraded"], list)


def test_mechanism_diagnostics_endpoint_requires_chat_and_access(client):
    assert client.get(DIAG, headers=_hdr()).status_code == 422
    resp = client.get(DIAG, headers={**_hdr(USER_ID), "X-Chat-Id": str(CHAT_B)})
    assert resp.status_code == 403


def test_mechanism_diagnostics_lives_in_zone_router_not_routes_py():
    """REGRESSION (L-F11S-1): новый маршрут — отдельный файл-зона.

    `web/api/routes.py` держит набор маршрутов под byte-freeze F8/F11; новый
    маршрут добавляется файлом-зоной (прецедент stories/oversight/speech) и
    регистрируется в `web/app.py`. Если маршрут вернётся в `routes.py`,
    routes-инвентарь `f8_baseline.json` перестанет быть ловушкой против
    случайного нового endpoint'а.
    """
    from web.api.mechanism_diagnostics import mechanism_diagnostics_router
    paths = {getattr(r, "path", "") for r in mechanism_diagnostics_router.routes}
    assert paths == {DIAG[len("/api"):]}
    routes_src = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")
    assert "mechanism-diagnostics" not in routes_src
    app_src = (ROOT / "web" / "app.py").read_text(encoding="utf-8")
    assert "include_router(mechanism_diagnostics_router, prefix=\"/api\")" \
        in app_src


def test_mechanism_diagnostics_endpoint_does_not_merge_blocks(
        client, monkeypatch):
    """Маршрут возвращает ровно то, что собрал сервис (без склейки/пересчёта)."""
    from services import initiative_diagnostics as diag
    marker = {
        "schema_version": 1, "generated_at": 1800000000, "chat_id": CHAT_A,
        "text_initiative": {"mechanism": "text_initiative", "sentinel": "T"},
        "meme": {"mechanism": "meme", "sentinel": "M"},
        "degraded": ["meme"],
    }
    calls = []

    async def _fake(db, chat_id, **kw):
        calls.append(chat_id)
        return marker

    monkeypatch.setattr(diag, "collect_mechanism_diagnostics", _fake)
    resp = client.get(DIAG, headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
    assert resp.status_code == 200, resp.text
    assert calls == [CHAT_A]
    assert resp.json() == marker
    assert resp.json()["text_initiative"]["sentinel"] == "T"
    assert resp.json()["meme"]["sentinel"] == "M"


def test_meme_prompts_edit_persist_and_empty_removes_override(client):
    """P4 §1: оба промпта сохраняются существующим путём и читаются обратно.

    Пустая строка СНИМАЕТ чатовое переопределение (ключ удаляется), а не
    записывает пустой промпт: действует слой ниже.
    """
    chat = {"X-Chat-Id": str(CHAT_A)}
    joke_key = mi.prompt_setting_key(mi.JOKE_PROMPT_BLOCK_ID)
    image_key = mi.prompt_setting_key(mi.IMAGE_PROMPT_BLOCK_ID)
    resp = client.post(ENDPOINT,
                       json={"prompt_joke": "Свой прикол-промпт",
                             "prompt_image": "Кадр: {joke}"},
                       headers={**_hdr(), **chat})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["prompts"]["joke"]["text"] == "Свой прикол-промпт"
    assert body["prompts"]["joke"]["source"] == "chat"
    assert body["prompts"]["image"]["text"] == "Кадр: {joke}"
    assert body["prompts"]["image"]["source"] == "chat"
    assert body["template"]["text"] == "Кадр: {joke}"
    overrides = client.conn.writes[-1]
    assert overrides[joke_key] == "Свой прикол-промпт"
    assert overrides[image_key] == "Кадр: {joke}"
    # Мастер модуля не затронут.
    assert "flags.initiative_enabled" not in overrides

    # Повторная загрузка показывает сохранённое (не заводской текст).
    again = client.get(ENDPOINT, headers={**_hdr(), **chat}).json()
    assert again["prompts"]["joke"]["text"] == "Свой прикол-промпт"
    assert again["prompts"]["image"]["text"] == "Кадр: {joke}"
    assert again["prompts"]["image"]["differs_from_factory"] is True

    # Пустая строка = снять переопределение: действует заводской слой.
    resp = client.post(ENDPOINT, json={"prompt_joke": "", "prompt_image": "  "},
                       headers={**_hdr(), **chat})
    assert resp.status_code == 200, resp.text
    overrides = client.conn.writes[-1]
    assert joke_key not in overrides
    assert image_key not in overrides
    body = resp.json()
    assert body["prompts"]["joke"]["source"] != "chat"
    assert body["prompts"]["joke"]["text"] == mi.MEME_JOKE_PROMPT
    assert body["prompts"]["image"]["text"] == mi.MEME_IMAGE_PROMPT


def test_meme_prompt_422_names_the_field_and_writes_nothing(client):
    """P4 §1: отказ по шаблону (2+ `{joke}`) — 422, а не молчаливая запись.

    Ответ называет ключ поля, поэтому карточка показывает причину У ПОЛЯ.
    """
    chat = {"X-Chat-Id": str(CHAT_A)}
    writes_before = len(client.conn.writes)
    resp = client.post(ENDPOINT,
                       json={"prompt_image": "a {joke} b {joke}"},
                       headers={**_hdr(), **chat})
    assert resp.status_code == 422
    detail = str(resp.json().get("detail") or "")
    assert "prompts.meme_image" in detail or "шаблон" in detail
    assert len(client.conn.writes) == writes_before

    # Неизвестное имя поля (опечатка клиента) — громкий 422, не «успех».
    resp = client.post(ENDPOINT, json={"joke_prompt": "текст"},
                       headers={**_hdr(), **chat})
    assert resp.status_code == 422
    assert len(client.conn.writes) == writes_before


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
    assert "data-meme-delivery" in block
    assert "data-meme-unavailable" in block
    # P4: оба промпта — реальные поля, три числа бюджета, диагностика прикола,
    # два блока диагностики механизмов и видимые стадии попытки.
    # PVR-S4 (одобрено ревью): поле рисует единый компонент
    # `<prompt-version-card>` — его шаблон #prompt-version-card-tpl содержит
    # настоящий <textarea rows>, привязанный к v-model. Требование
    # «два реальных поля» сохранено: в блоке ровно две карточки и нет
    # сырых <textarea>, пассивный текст по-прежнему отсутствует.
    assert block.count("<prompt-version-card") == 2
    assert block.count("<textarea") == 0
    tpl = html.split('id="prompt-version-card-tpl"', 1)[1].split("</script>", 1)[0]
    assert tpl.count("<textarea") == 1
    assert ':value="modelValue"' in tpl
    assert "data-meme-prompt-joke" in block
    assert "data-meme-prompt-image" in block
    assert "data-meme-prompt-error-joke" in block
    assert "data-meme-prompt-error-image" in block
    assert "data-meme-prompt-text" not in block      # пассивный текст убран
    assert "data-meme-limit-ceiling" in block
    assert "data-meme-limit-template" in block
    assert "data-meme-limit-joke" in block
    assert "data-meme-speech" in block
    assert "data-meme-attempt-stages" in block
    assert "data-meme-diag" in block
    assert "data-meme-diag-degraded" in block
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
