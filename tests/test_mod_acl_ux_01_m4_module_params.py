"""MOD-ACL-UX-01 M4 — страница «Векторной памяти»: РЕАЛЬНЫЕ параметры и
честная пустота.

Дефект (снимки владельца, 10.11.2026): `#/modules/embeddings` открывался, но
показывал ОДНУ вкладку «Обзор» и блок «На этой вкладке нет доступных
параметров / сервер отфильтровал их по правам» — при том что владелец является
глобальным админом (wildcard), а каталог реальные параметры модулю назначает
(`models_embeddings`, `keys_llm`).

Причина (диагностика, не догадка):
  * (A) у инфраструктурного модуля нет собственной config-вкладки в TABS,
    поэтому производный дескриптор страницы отдавал ПУСТОЙ `sources` → ноль
    параметров на всех вкладках, «Настройки»/«Лимиты» исчезали как пустые;
  * (B) НЕ подтвердилась: `GET /api/config` на глобальном пути фильтрует
    только ключи-секреты для не-админа (web/api/routes.py `get_config`),
    глобальный админ получает все не-скрытые параметры. Оба теста ниже
    фиксируют это как контракт (админ — всё, обычный юзер — без ключей).

Этот файл:
  1) проверяет контракт `GET /api/config` (реальный эндпоинт, fake PG):
     админ получает группы `models_embeddings` и `keys_llm`, обычный
     пользователь — `models_embeddings` без секретных ключей;
  2) снимает ЖИВОЙ ответ `/api/config` для админа и для простого пользователя
     и реестр `registry_for_frontend()` → снимок для node-теста, чтобы JS
     работал с настоящим серверным контрактом (не с рукописной копией);
  3) запускает `tests/js/mod_acl_ux_m4_module_params_test.js` на этом снимке:
     реальный набор параметров страницы «Векторной памяти» у админа
     (непустой, сгруппированный каталогом), поиск ВНУТРИ этих групп, отказ
     обычному пользователю на уровне маршрута и выбор текста пустого блока по
     ФАКТИЧЕСКОЙ причине (нет параметров ≠ отфильтровано по правам).

TEST-LIFECYCLE: CONTRACT owner=MOD-ACL-UX-01/M4 (§5 ТЗ владельца)
"""
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import tempfile
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from web.api import deps as deps_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS_M4"
ADMIN_ID = 5885953495
USER_ID = 7711771
EMB_GROUP = "models_embeddings"
KEYS_GROUP = "keys_llm"

SCRIPT = os.path.join("tests", "js", "mod_acl_ux_m4_module_params_test.js")
FIXTURE = os.path.join("tests", "fixtures", "mod_acl_m4_embeddings_payload.json")

# Строки bot_settings «как в проде»: все ключи каталога этих групп сохранены
# владельцем (сид keys-строки не создаёт — services/config_cache,
# `_synthetic_group_items`/D13), поэтому `/api/config` содержит ПОЛНЫЙ набор:
# models_embeddings 16 + keys_llm 9 + models_main 4.
KEEP_GROUPS = ("models_embeddings", "keys_llm", "models_main")


def _catalogue_rows(groups=KEEP_GROUPS):
    from services import param_catalog as pc
    rows = []
    for spec in pc.REGISTRY.values():
        if spec.group not in groups or spec.hidden or not spec.pg_key:
            continue
        if spec.secret:
            value = "sk-test-key"
        elif spec.type == "int":
            value = 1
        elif spec.type == "float":
            value = 1.0
        elif spec.type == "bool":
            value = False
        else:
            value = ""
        rows.append({"key": spec.pg_key, "value": value,
                     "category": spec.category, "updated_at": None})
    return rows


_SETTINGS_ROWS = _catalogue_rows()

# Поля ModuleSpec, которые получает фронт через `registry_for_frontend()`.
# `gate` намеренно не входит: его requested/effective/source зависит от env и
# сделал бы снимок недетерминированным (JS-контракту гейт не нужен).
REGISTRY_FIELDS = (
    "id", "title", "description", "parent_id", "master_param",
    "runtime_gate", "settings_groups", "model_slots", "config_tab",
    "visibility", "classification", "status_source", "analytics_anchor",
    "help_anchor", "tab", "route",
)



def make_init_data(user_id: int = ADMIN_ID) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


class _FakeConn:
    def __init__(self, settings_rows=(), role_rows=(), admin_rows=()):
        self._settings_rows = list(settings_rows)
        self._role_rows = list(role_rows)
        self._admin_rows = list(admin_rows)

    async def execute(self, sql, *args):
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return None

    async def fetch(self, sql, *args):
        if "bot_settings" in sql:
            return self._settings_rows
        if "bot_roles" in sql:
            return self._role_rows
        if "bot_admins" in sql:
            return self._admin_rows
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self):
                return self._pool._conn

            async def __aexit__(self, *exc):
                return False

        cm = _CM()
        cm._pool = self
        return cm

    async def close(self):
        pass


class _FakePg:
    def __init__(self, conn):
        self._pool = _FakePool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


_ROLE_ROWS = [
    {"role_name": "admin", "permissions": {"wildcard": True},
     "is_custom": False},
    {"role_name": "user", "permissions": {}, "is_custom": False},
]
_ADMIN_ROWS = [
    {"telegram_id": ADMIN_ID, "role_name": "admin",
     "added_by": None, "created_at": "2026-08-30T00:00:00+00:00"},
]
# Сохранённые владельцем ключи (в проде строки bot_settings существуют —
# поэтому группа keys_llm реально приходит в /api/config; сид keys-строки не
# создаёт, см. services/config_cache._synthetic_group_items/D13). Набор строк
# генерируется из каталога (`_SETTINGS_ROWS` выше) — рукописного списка нет.


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(INFO_TEXT_FILE=str(tmp_path / "info.md"),
                              ADMIN_USER_ID=ADMIN_ID))
    conn = _FakeConn(settings_rows=_SETTINGS_ROWS, role_rows=_ROLE_ROWS,
                     admin_rows=_ADMIN_ROWS)
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as test_client:
        test_client.cache = cache
        yield test_client


def _items_of(body, group):
    return [it for it in body["items"] if it.get("group") == group]


def test_global_admin_receives_embeddings_groups(client):
    """Причина (B) отклонена: глобальному админу сервер НЕ режет параметры.

    Реальный набор страницы: models_embeddings 16 параметров + keys_llm 9
    ключей = 25 — ровно то, что рендерится на «Основных настройках».
    """
    resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
    assert resp.status_code == 200
    body = resp.json()
    emb = _items_of(body, EMB_GROUP)
    keys = _items_of(body, KEYS_GROUP)
    assert len(emb) == 16, "каталог объявляет 16 параметров models_embeddings"
    assert len(keys) == 9, "каталог объявляет 9 ключей keys_llm"
    assert len(emb) + len(keys) == 25, "страница модуля показывает 25 параметров"
    # Категории реальные (источники вкладки строятся по ним, не по догадке).
    assert {it["category"] for it in emb} == {"models"}
    assert {it["category"] for it in keys} == {"keys"}
    # Метаданные групп приходят тем же ответом — заголовки берём из каталога.
    gids = {g["id"]: g for g in body["groups"]}
    assert EMB_GROUP in gids and KEYS_GROUP in gids
    assert gids[EMB_GROUP]["title"] == "Отпечатки текста и длина"
    assert gids[EMB_GROUP]["category"] == "models"
    assert gids[KEYS_GROUP]["title"] == "Основная нейросеть"
    assert gids[KEYS_GROUP]["category"] == "keys"
    assert any(it["secret"] for it in keys), "ключи отданы в маскированном виде"


def test_plain_user_loses_secret_keys_but_keeps_model_params(client):
    """Настоящий фильтр прав существует — но он не объясняет пустоту админа.

    Сервер скрывает от не-админа именно СЕКРЕТЫ (`secret=True`, категория
    keys); несекретные участники той же группы (например «Квоты: группы
    ключей») остаются — поэтому проверяем и убыль набора, и отсутствие
    секретов, а не «группа пуста».
    """
    resp = client.get("/api/config", headers=_hdr(USER_ID))
    assert resp.status_code == 200
    body = resp.json()
    keys = _items_of(body, KEYS_GROUP)
    assert len(_items_of(body, EMB_GROUP)) == 16, (
        "несекретные параметры embeddings видны и обычному пользователю")
    assert not [it for it in keys if it["secret"]], (
        "ключи-секреты не-админу сервер не отдаёт — это и есть права")
    admin_keys = _items_of(
        client.get("/api/config", headers=_hdr(ADMIN_ID)).json(), KEYS_GROUP)
    assert len(keys) < len(admin_keys), (
        "у не-админа группа keys_llm реально урезана серверным фильтром")


def _registry_snapshot():
    """Ровно то, что получает фронт: `registry_for_frontend()` (без gate)."""
    from services.module_registry import registry_for_frontend
    rows = []
    for spec in registry_for_frontend():
        rows.append({f: spec[f] for f in REGISTRY_FIELDS})
    return rows


def _project_body(body):
    """Детерминированная проекция `/api/config` для node-теста.

    Оставляем только группы, которые проверяет контракт (объявленные модулю +
    соседняя models_main), и только поля, влияющие на рендер/проверки. Значения
    параметров не входят в снимок: они зависят от env/Settings, а контракт
    здесь — НАБОР параметров, их группы, заголовки и фильтрация поиском.
    """
    items = [
        {
            "key": it["key"], "category": it["category"], "group": it["group"],
            "title": it["title"], "description": it["description"],
            "type": it["type"], "secret": bool(it["secret"]),
            "per_chat": bool(it["per_chat"]), "widget": it.get("widget") or "",
            "progressive_level": it.get("progressive_level") or "basic",
            "value": ({"configured": True, "last4": "0000"}
                      if it["secret"] else None),
        }
        for it in body.get("items", [])
        if it.get("group") in KEEP_GROUPS
    ]
    items.sort(key=lambda it: (it["category"], it["group"], it["key"]))
    present = {it["category"] for it in items}
    groups = [
        {"id": g["id"], "category": g["category"], "title": g["title"],
         "description": g["description"], "order": g["order"]}
        for g in body.get("groups", []) if g["category"] in present
    ]
    return {"items": items, "groups": groups}


def _fixture_payload(client):
    """Снимок, который node-тест берёт по умолчанию (самодостаточный прогон)."""
    return {
        "registry": _registry_snapshot(),
        "admin": _project_body(client.get("/api/config",
                                         headers=_hdr(ADMIN_ID)).json()),
        "user": _project_body(client.get("/api/config",
                                        headers=_hdr(USER_ID)).json()),
    }


def _run_node(node, root, argv):
    return subprocess.run([node, SCRIPT] + list(argv), capture_output=True,
                          text=True, timeout=180, cwd=root)


def test_js_fixture_matches_live_contract(client):
    """Drift-guard: снимок в репозитории = живой контракт сервера.

    Тот же приём, что у `tests/fixtures/module_registry_visible.json` (M3):
    node-тест обязан запускаться БЕЗ аргументов стандартным прогоном
    `node tests/js/*.js`, поэтому ему нужен закоммиченный снимок; расхождение
    с живым контрактом ловится здесь, а не «зелёным» устаревшим снимком.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, FIXTURE)
    with open(path, encoding="utf-8") as fh:
        saved = json.load(fh)
    live = _fixture_payload(client)
    assert saved == live, (
        "tests/fixtures/mod_acl_m4_embeddings_payload.json устарел — "
        "пересоберите его из живого контракта (см. docstring теста)")


def test_js_module_page_uses_real_catalogue_params(client):
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    admin = client.get("/api/config", headers=_hdr(ADMIN_ID)).json()
    user = client.get("/api/config", headers=_hdr(USER_ID)).json()
    payload = {"registry": _registry_snapshot(), "admin": admin, "user": user}
    fd, snap = tempfile.mkstemp(prefix="mod_acl_m4_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        res = _run_node(node, root, [snap])
    finally:
        try:
            os.unlink(snap)
        except OSError:
            pass
    assert res.returncode == 0, (
        "MOD-ACL-UX-01 M4 JS-UNIT провалился (живой контракт):\n"
        "STDOUT:\n%s\nSTDERR:\n%s" % (res.stdout, res.stderr))
    assert "MOD-ACL-UX-01 M4 MODULE PARAMS OK" in res.stdout


def test_js_standalone_runs_from_committed_snapshot():
    """Стандартный прогон `node tests/js/*.js` (без аргументов) ЗЕЛЁНЫЙ.

    Раньше файл требовал обязательный аргумент-снимок и валил стандартный
    прогон (9 падений вместо 8 на предке). Теперь он читает закоммиченный
    снимок относительно своего расположения.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    res = _run_node(node, root, [])
    assert res.returncode == 0, (
        "standalone-прогон M4 упал (нет аргумента = берётся снимок из repo):\n"
        "STDOUT:\n%s\nSTDERR:\n%s" % (res.stdout, res.stderr))
    assert "MOD-ACL-UX-01 M4 MODULE PARAMS OK" in res.stdout
