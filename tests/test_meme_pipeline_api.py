"""MEME-PIPELINE-REFactor-01 / P2 — API мем-настроек: два редактируемых
промпта и диагностика бюджета L/T/J.

Контракт владельца (§3 ТЗ; arch/integration-decisions.md §2–§3):

  * оба промпта мем-пайплайна (`prompts.meme_joke`, `prompts.meme_image`) —
    штатные ключи каталога: правка сохраняется, читается обратно и сразу
    действует в рантайме; глобальный слой → чатовое переопределение →
    заводской текст, пустое значение НЕ обнуляет промпт, а проваливается
    на следующий слой;
  * витрина показывает ТРИ числа §3 ТЗ (потолок итогового промпта L, длина
    шаблона T, бюджет прикола J) и считает их той же функцией, что рантайм,
    от ЭФФЕКТИВНОГО шаблона;
  * шаблон с двумя `{joke}` отклоняется (422) на любом пути записи;
  * реестр промптов остаётся целым: один блок-объявление, печати валидны.

Каждая проверка может упасть: числа берутся из реального ответа API и
реального прогона пайплайна, подменены только внешние границы (LLM,
image-провайдер, Telegram).

TEST-LIFECYCLE: CONTRACT owner=2026-11-03-meme-pipeline-refactor-01
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services import hot_config
from services import meme_initiative as meme
from services import param_catalog as pc
from services import prompt_registry as pr
from tests.test_webapp_api import ADMIN_ID, USER_ID, _FakeConn, _FakePg, _hdr
from web.api import routes as routes_mod
from web.app import create_app

CHAT_A = -100111
ENDPOINT = "/api/initiative/meme-settings"
JOKE_KEY = "prompts.meme_joke"
IMAGE_KEY = "prompts.meme_image"
JOKE_FACTORY = "Придумай короткий абсурдный прикол из этой выжимки."
IMAGE_FACTORY = "Создай мем с шрифтом импакт:"
IMAGE_OK = {"available": True, "reason": "ok", "health": "healthy",
            "configured": True, "module_enabled": True}


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
            return {"chat_id": args[0], "updated_at": "2026-11-03T00:00:00+00:00",
                    "chat_params": json.dumps(self.params), "gates_opt_in": False}
        if low.startswith("select chat_id") and "chat_profiles" in low:
            return {"chat_id": args[0], "updated_at": "2026-11-03T00:00:00+00:00",
                    "chat_params": json.dumps(self.params), "gates_opt_in": False}
        return None


def _build(monkeypatch):
    monkeypatch.setattr(
        "web.api.deps.settings",
        type("S", (), {"API_TOKEN": "123456:TEST_TOKEN_FOR_API_TESTS"})())
    conn = _ProfileConn(
        role_rows=[
            {"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False},
            {"role_name": "user", "permissions": {}, "is_custom": False},
        ],
        admin_rows=[
            {"telegram_id": ADMIN_ID, "role_name": "admin",
             "added_by": None, "created_at": "2026-11-02T00:00:00+00:00"},
        ],
    )
    from services.config_cache import ConfigCache
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    return conn, cache, app


@pytest.fixture
def client(monkeypatch):
    """Админский клиент с ЧЕСТНЫМИ слоями настроек (override чата → global).

    `global_layer` эмулирует глобальный слой (`bot_settings` через
    ConfigCache/hot_config): его правит штатная карточка «Промпты».
    """
    conn, cache, app = _build(monkeypatch)
    global_layer: dict[str, object] = {}
    # Детерминированные зависимости мем-модуля (сеть не используется).
    monkeypatch.setattr(meme, "open_ledger", lambda db: None)
    monkeypatch.setattr(meme, "model_prompt_chars", _no_model_capability)
    from services import initiative_observer
    monkeypatch.setattr(initiative_observer, "observer_enabled", lambda: True)
    from services import image_generation as ig
    monkeypatch.setattr(ig, "resolve_module_enabled", lambda chat_id=None: _true())
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: None)
    from services import chat_params as chat_params_srv

    def _overrides():
        return conn.params.get("overrides") or {}

    async def _get_chat_param(chat_id, key, default=None):
        overrides = _overrides()
        if key in overrides and overrides[key] is not None:
            return overrides[key]
        return global_layer.get(key, default)

    async def _get_sourced(chat_id, key, default=None):
        overrides = _overrides()
        if key in overrides and overrides[key] is not None:
            return overrides[key], "chat"
        if key in global_layer:
            return global_layer[key], "global"
        return default, "factory"

    monkeypatch.setattr(chat_params_srv, "get_chat_param", _get_chat_param)
    monkeypatch.setattr(chat_params_srv, "get_chat_param_sourced", _get_sourced)
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: global_layer.get(key, default))
    with TestClient(app) as tc:
        tc.cache = cache
        tc.conn = conn
        tc.global_layer = global_layer
        yield tc


@pytest.fixture
def real_layers(monkeypatch):
    """Админский клиент, у которого слои настройки — НАСТОЯЩИЕ.

    Отличие от фикстуры `client`: `chat_params.get_chat_param` и
    `chat_params.get_chat_param_sourced` НЕ подменяются. Профиль читается
    реальным `ChatParamsCache` над PG-двойником, пишется реальным
    `set_chat_params` (тот же код, что в проде). Подменены только внешние
    границы мем-модуля (сеть, ledger, БД лора), как и в `client`.
    """
    conn, cache, app = _build(monkeypatch)
    global_layer: dict[str, object] = {}
    monkeypatch.setattr(meme, "open_ledger", lambda db: None)
    monkeypatch.setattr(meme, "model_prompt_chars", _no_model_capability)
    from services import initiative_observer
    monkeypatch.setattr(initiative_observer, "observer_enabled", lambda: True)
    from services import image_generation as ig
    monkeypatch.setattr(ig, "resolve_module_enabled",
                        lambda chat_id=None: _true())
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: None)
    from services import chat_params as chat_params_srv
    # Штатный кэш чат-параметров поверх PG-двойника: резолв слоёв идёт из
    # хранилища, а не из мока резолвера.
    chat_cache = chat_params_srv.ChatParamsCache(cache.pg)
    monkeypatch.setattr(chat_params_srv, "_chat_params_cache", chat_cache)
    # Глобальный слой (`bot_settings`) эмулируется тем же hot.get.
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: global_layer.get(key, default))
    with TestClient(app) as tc:
        tc.cache = cache
        tc.conn = conn
        tc.global_layer = global_layer
        tc.chat_params_cache = chat_cache
        yield tc


async def _true():
    return True


async def _no_model_capability():
    """Потолок модели неизвестен: L определяется настройками (детерминизм)."""
    return None


def _headers(chat_id: int = CHAT_A, user_id: int = ADMIN_ID):
    return {**_hdr(user_id), "X-Chat-Id": str(chat_id)}


def _get(client) -> dict:
    resp = client.get(ENDPOINT, headers=_headers())
    assert resp.status_code == 200, resp.text
    return resp.json()


def _post(client, **payload):
    return client.post(ENDPOINT, json=payload, headers=_headers())


# ── фикстуры рантайма: настоящий пайплайн, подменены только границы ────────

def _ledger(tmp_path):
    led = meme.SqliteQuotaLedger(str(tmp_path / "meme_api.db"))
    led.apply_schema()
    return led


def _run_pipeline(tmp_path, chat_id: int = CHAT_A) -> dict:
    """Один ручной прогон пайплайна → факты этапа B из журнала попыток.

    `manual=True`: квота/кулдаун/окно/random/гейт не мешают проверке бюджета
    (сам бюджет и промпты считаются ровно тем же кодом, что в проде).
    """
    led = _ledger(tmp_path)
    prompts: list[str] = []
    rows = [{"chat_id": chat_id, "id": i, "text": f"реплика {i}"}
            for i in range(5)]

    async def summarizer(cid, window, system):
        return "хук выжимки"

    async def joke(cid, summary, instruction):
        return "прикол"

    async def provider(prompt, cid, jid):
        prompts.append(prompt)
        return SimpleNamespace(ok=True, called=True, reason="", content=b"png")

    async def sender(cid, content, prompt):
        return None

    result = asyncio.run(meme.consider_chat(
        None, chat_id, ledger=led, messages=rows,
        initiative_enabled=lambda: True, image_status=IMAGE_OK,
        summarizer=summarizer, joke_generator=joke, image_provider=provider,
        sender=sender, model_chars=None, manual=True))
    facts = {}
    for row in led.attempts(chat_id):
        parsed = meme.parse_attempt_facts(row)
        if parsed:
            facts[str(row["stage"])] = parsed
    return {"result": result, "facts": facts, "prompts": prompts,
            "journal": led.attempts(chat_id)}


# ── реестр/каталог: ключи есть, блок один, печати валидны ──────────────────

def test_prompts_are_catalog_keys_with_single_registry_block():
    for key in (JOKE_KEY, IMAGE_KEY):
        spec = pc.get_by_pg_key(key)
        assert spec is not None, key
        assert spec.category == pc.CATEGORY_PROMPTS
        assert spec.group == "prompts_initiative_meme"
        assert spec.per_chat is True          # глобально + чатовое переопределение
        block = pr.by_pg_key(key)
        assert block is not None and not block.block_id.startswith("unregistered:")
        assert block.ui == "catalog"          # карточка: не «каталог ожидается»
        assert pc.group_tab(spec.group) == pc.TAB_PROMPTS
    # Один блок — одно объявление (дубль уронил бы EVOL-018).
    ids = [b.block_id for b in pr.all_blocks()]
    assert ids.count("initiative.meme.joke") == 1
    assert ids.count("initiative.meme.image") == 1
    # Заводские тексты — дословные, печати ревизий целы.
    assert pr.factory_text("initiative.meme.joke") == JOKE_FACTORY
    assert pr.factory_text("initiative.meme.image") == IMAGE_FACTORY
    assert pr.seal_integrity() == {}
    assert pr.unregistered_catalog_keys() == ()


# ── правка каждого промпта: сохранение → чтение обратно ────────────────────

def test_each_prompt_edit_persists_and_reads_back(client):
    joke_text = "Придумай прикол про кота из этой выжимки."
    image_text = "Мем: {joke}"
    resp = _post(client, prompt_joke=joke_text, prompt_image=image_text)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Записаны именно КЛЮЧИ КАТАЛОГА (чат-слой), а не выдуманное поле.
    overrides = client.conn.writes[-1]
    assert overrides[JOKE_KEY] == joke_text
    assert overrides[IMAGE_KEY] == image_text

    # Ответ и повторная загрузка показывают сохранённое и источник «чат».
    for payload in (body, _get(client)):
        prompts = payload["prompts"]
        assert prompts["joke"]["text"] == joke_text
        assert prompts["joke"]["source"] == "chat"
        assert prompts["joke"]["differs_from_factory"] is True
        assert prompts["joke"]["setting_key"] == JOKE_KEY
        assert prompts["image"]["text"] == image_text
        assert prompts["image"]["source"] == "chat"
        assert payload["template"]["text"] == image_text
        assert payload["template"]["source"] == "chat"
        assert payload["template"]["placeholders"] == 1
        assert payload["template"]["valid"] is True


def test_global_layer_then_chat_override_then_factory(client):
    """Слои: чат → глобальный → заводской; пустое значение = снять override."""
    client.global_layer[JOKE_KEY] = "Глобальный прикол."
    client.global_layer[IMAGE_KEY] = "Глобальный шаблон {joke}"

    body = _get(client)
    assert body["prompts"]["joke"]["text"] == "Глобальный прикол."
    assert body["prompts"]["joke"]["source"] == "global"
    assert body["prompts"]["image"]["text"] == "Глобальный шаблон {joke}"

    # Чатовое переопределение сильнее глобального.
    assert _post(client, prompt_joke="Чатовый прикол.").status_code == 200
    chat_body = _get(client)
    assert chat_body["prompts"]["joke"]["text"] == "Чатовый прикол."
    assert chat_body["prompts"]["joke"]["source"] == "chat"

    # Пустая строка снимает ЧАТОВОЕ переопределение (ключ удалён), глобальное
    # значение снова действует; пустота не обнуляет промпт.
    assert _post(client, prompt_joke="", prompt_image="   ").status_code == 200
    overrides = client.conn.writes[-1]
    assert JOKE_KEY not in overrides and IMAGE_KEY not in overrides
    back = _get(client)
    assert back["prompts"]["joke"]["text"] == "Глобальный прикол."
    assert back["prompts"]["joke"]["source"] == "global"
    assert back["prompts"]["image"]["text"] == "Глобальный шаблон {joke}"

    # Без глобального слоя действует заводской текст.
    client.global_layer.pop(JOKE_KEY)
    client.global_layer.pop(IMAGE_KEY)
    factory = _get(client)
    assert factory["prompts"]["joke"]["text"] == JOKE_FACTORY
    assert factory["prompts"]["joke"]["source"] == "factory"
    assert factory["prompts"]["image"]["text"] == IMAGE_FACTORY
    assert factory["template"]["text"] == IMAGE_FACTORY
    assert factory["template"]["placeholders"] == 0


# ── витрина = рантайм: одни и те же L/T/J ──────────────────────────────────

@pytest.mark.parametrize("case", ["factory", "chat_slot", "chat_append"])
def test_preview_numbers_equal_runtime_numbers(client, tmp_path, monkeypatch,
                                               case):
    """L/T/J витрины равны L/T/J реального прогона для ОДНОГО шаблона.

    Регресс, который закрывает полоса: раньше витрина считала от заводской
    константы, поэтому для шаблона `Мем: {joke}` при L=400 она давала J=371,
    а пайплайн — 395.
    """
    assert _post(client, enabled=True, daily_limit=3, min_messages=0,
                 cooldown_seconds=0, length_limit=400).status_code == 200
    if case == "chat_slot":
        assert _post(client, prompt_image="Мем: {joke}").status_code == 200
    elif case == "chat_append":
        assert _post(client, prompt_image="Мем:").status_code == 200

    payload = _get(client)
    numbers = payload["length_limit"]
    template = payload["template"]["text"]
    assert template == ({"factory": IMAGE_FACTORY,
                         "chat_slot": "Мем: {joke}",
                         "chat_append": "Мем:"}[case])

    # 1) Числа витрины = прямой расчёт той же функцией от того же шаблона.
    expected = meme.resolve_meme_budget(
        model_chars=None, admin=400, explicit=None, template=template)
    assert numbers["ceiling"] == expected.ceiling == 400
    assert numbers["template_chars"] == expected.template_chars
    assert numbers["joke_budget"] == expected.joke_budget
    assert numbers["placeholder"] == expected.placeholder
    assert numbers["summary_target"] is None      # у выжимки потолка нет

    # 2) Числа витрины = числа РЕАЛЬНОГО прогона (журнал попыток).
    run = _run_pipeline(tmp_path)
    facts = run["facts"]["joke"]
    assert run["result"].published is True
    assert facts["ceiling"] == numbers["ceiling"]
    assert facts["template_chars"] == numbers["template_chars"]
    assert facts["limit"] == numbers["joke_budget"]
    assert facts["placeholder"] == numbers["placeholder"]
    # Инвариант бюджета соблюдён и на фактическом prompt у провайдера.
    assert len(run["prompts"][0]) <= numbers["ceiling"]
    assert run["prompts"][0] == meme.render_image_prompt(template, "прикол")

    if case == "chat_slot":
        # Измеренный регресс: T = |«Мем: »| = 5, J = 395 (не 371).
        assert numbers["template_chars"] == len("Мем: ")
        assert numbers["joke_budget"] == 395
        assert numbers["joke_budget"] != 400 - (len(IMAGE_FACTORY) + 1)
    if case == "chat_append":
        # Без плейсхолдера прикол дописывается через пробел: T = |шаблон| + 1.
        assert numbers["template_chars"] == len("Мем:") + 1
        assert numbers["joke_budget"] == 400 - (len("Мем:") + 1)


# ── плейсхолдер: два `{joke}` — 422, без записи ────────────────────────────

def test_two_placeholders_are_rejected_without_writing(client):
    bad = "{joke} и ещё {joke}"
    resp = _post(client, prompt_image=bad)
    assert resp.status_code == 422, resp.text
    assert "joke" in resp.json()["detail"]
    assert client.conn.writes == []               # молчаливой записи нет
    assert meme.template_validation_error(bad)
    # Один плейсхолдер и ноль — допустимы.
    assert meme.template_validation_error("{joke} — мем") == ""
    assert meme.template_validation_error(IMAGE_FACTORY) == ""
    assert _post(client, prompt_image="{joke} — мем").status_code == 200


class _GlobalCache:
    """Кэш глобального слоя (bot_settings) для `POST /api/config`."""

    pg_available = True

    def __init__(self):
        self.store: dict[str, object] = {}
        self.updated: dict[str, str | None] = {}
        self.written: list[tuple[str, object]] = []

    def get(self, key, default=None):
        return self.store.get(key, default)

    def get_updated_at(self, key):
        return self.updated.get(key)

    async def set_many(self, items):
        for key, value, _category in items:
            self.written.append((key, value))
            self.store[key] = value
            self.updated[key] = None

    async def set(self, key, value, category):
        self.written.append((key, value))
        self.store[key] = value
        self.updated[key] = None


def _global_payload(key: str, value: str):
    return SimpleNamespace(
        items=[SimpleNamespace(key=key, value=value, updated_at=None)],
        updated_at=None)


@pytest.mark.asyncio
async def test_global_edit_saves_and_feeds_runtime(monkeypatch):
    """Глобальная правка карточки «Промпты» пишется и читается тем же резолвом."""
    cache = _GlobalCache()
    monkeypatch.setattr(routes_mod, "get_cache", lambda request: cache)
    monkeypatch.setattr(routes_mod, "can_edit_param", lambda c, uid, key: True)
    monkeypatch.setattr(routes_mod, "can_view_key_value",
                        lambda c, uid, key: True)
    monkeypatch.setattr(hot_config, "_cache", cache)   # тот же кэш, что у рантайма

    bad = _global_payload(IMAGE_KEY, "{joke} и {joke}")
    with pytest.raises(HTTPException) as exc:
        await routes_mod._post_config_global(
            object(), bad, SimpleNamespace(id=ADMIN_ID))
    assert exc.value.status_code == 422
    assert cache.written == []                     # невалидный шаблон не сохранён

    ok = _global_payload(IMAGE_KEY, "Мем: {joke}")
    out = await routes_mod._post_config_global(
        object(), ok, SimpleNamespace(id=ADMIN_ID))
    assert out["updated"] == [IMAGE_KEY]
    assert cache.store[IMAGE_KEY] == "Мем: {joke}"

    view = await meme.effective_meme_prompt(
        -100500, meme.IMAGE_PROMPT_BLOCK_ID, factory=IMAGE_FACTORY)
    assert view["text"] == "Мем: {joke}"
    assert view["source"] == "global"
    assert meme.joke_placeholder_count(view["text"]) == 1


def test_post_requires_admin_and_some_change(client):
    resp = client.post(ENDPOINT, json={"prompt_joke": "x"},
                       headers=_headers(user_id=USER_ID))
    assert resp.status_code == 403
    assert client.conn.writes == []
    empty = _post(client, prompt_joke="", prompt_image="")
    assert empty.status_code == 422               # нечего менять — не «успех»


# ── durable-регрессии из ревью P2 (пункты 8-10 чек-листа) ──────────────────

def test_unknown_field_is_rejected_instead_of_silent_noop(real_layers):
    """Опечатка в имени поля — 422, а не «сохранено ничего» (`extra="forbid"`).

    Имена в коде — `prompt_joke`/`prompt_image`. Клиент по чужому имени
    (`joke_prompt`, как в тексте слайс-графа) раньше получал 422 «нет
    изменений» либо 200 без записи и считал правку сохранённой.
    """
    client = real_layers
    resp = _post(client, prompt_joke="Прикол.", joke_prompt="Прикол.")
    assert resp.status_code == 422, resp.text
    assert "joke_prompt" in resp.text            # отказ называет виновника
    assert client.conn.writes == []              # и ничего не записал
    # Штатный путь карточки (только канонические имена) по-прежнему проходит.
    ok = _post(client, prompt_joke="Прикол.")
    assert ok.status_code == 200, ok.text
    assert client.conn.params["overrides"][JOKE_KEY] == "Прикол."


def test_chat_level_config_rejects_two_placeholders_without_writing(
        real_layers):
    """Чат-уровень `POST /api/config` — тот же гейт шаблона, что и глобальный.

    Ревью P2 закрыло только глобальный путь (`_post_config_global`); здесь
    закреплён чатовый (`X-Chat-Id`): два `{joke}` → 422, в `overrides` чата
    ничего не записано (реальное хранилище, не мок).
    """
    client = real_layers
    bad = {"items": [{"key": IMAGE_KEY, "value": "{joke} и ещё {joke}"}]}
    resp = client.post("/api/config", json=bad, headers=_headers())
    assert resp.status_code == 422, resp.text
    assert "joke" in resp.text
    assert client.conn.writes == []              # молчаливой записи нет
    assert (client.conn.params.get("overrides") or {}) == {}

    # Контроль: валидный шаблон тем же путём сохраняется (гейт не глухой).
    ok = client.post("/api/config",
                     json={"items": [{"key": IMAGE_KEY,
                                      "value": "Мем: {joke}"}]},
                     headers=_headers())
    assert ok.status_code == 200, ok.text
    assert ok.json()["updated"] == [IMAGE_KEY]
    assert client.conn.params["overrides"][IMAGE_KEY] == "Мем: {joke}"


def test_layers_and_removal_through_real_resolver(real_layers):
    """Три слоя и снятие чатового override — через НАСТОЯЩИЙ резолвер.

    `effective_meme_prompt` → `_prompt_layer` → `chat_params.get_chat_param_sourced`
    без мока этого шва: чат → глобальный → заводской, а пустая строка из API
    удаляет именно чатовое переопределение. Запись идёт реальным
    `set_chat_params` (он же инвалидирует кэш), поэтому каждое чтение берётся
    из хранилища, а не из памяти предыдущего запроса.
    """
    client = real_layers

    def view() -> dict:
        return asyncio.run(meme.effective_meme_prompt(
            CHAT_A, meme.JOKE_PROMPT_BLOCK_ID, factory=JOKE_FACTORY))

    # 1) Нет ни переопределения, ни глобального значения → заводской текст.
    factory = view()
    assert factory["text"] == JOKE_FACTORY
    assert factory["source"] == "factory"
    assert factory["setting_key"] == JOKE_KEY

    # 2) Глобальный слой (карточка «Промпты») сильнее заводского.
    client.global_layer[JOKE_KEY] = "Глобальный прикол."
    glob = view()
    assert glob["text"] == "Глобальный прикол."
    assert glob["source"] == "global"

    # 3) Чатовое переопределение, записанное РЕАЛЬНЫМ API, сильнее глобального.
    assert _post(client, prompt_joke="Чатовый прикол.").status_code == 200
    assert client.conn.params["overrides"][JOKE_KEY] == "Чатовый прикол."
    chat = view()
    assert chat["text"] == "Чатовый прикол."
    assert chat["source"] == "chat"
    assert chat["differs_from_factory"] is True

    # 4) Пустая строка снимает ЧАТОВЫЙ слой → снова действует глобальный.
    assert _post(client, prompt_joke="").status_code == 200
    assert JOKE_KEY not in client.conn.params["overrides"]
    back = view()
    assert back["text"] == "Глобальный прикол."
    assert back["source"] == "global"

    # 5) Без глобального слоя остаётся заводской текст (пустота ничего не обнулила).
    client.global_layer.pop(JOKE_KEY)
    out = view()
    assert out["text"] == JOKE_FACTORY
    assert out["source"] == "factory"
