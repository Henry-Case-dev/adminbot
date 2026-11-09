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
# создаёт, см. services/config_cache._synthetic_group_items/D13).
_SETTINGS_ROWS = [
    {"key": "keys.llm_api_key", "value": "sk-test-llm",
     "category": "keys", "updated_at": None},
    {"key": "keys.embedding_api_key", "value": "sk-test-emb",
     "category": "keys", "updated_at": None},
]


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
    """Причина (B) отклонена: глобальному админу сервер НЕ режет параметры."""
    resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
    assert resp.status_code == 200
    body = resp.json()
    emb = _items_of(body, EMB_GROUP)
    keys = _items_of(body, KEYS_GROUP)
    assert len(emb) >= 3, "каталог объявляет >=3 параметра models_embeddings"
    assert keys, "глобальный админ видит секретные ключи своей области"
    # Категории реальные (источники вкладки строятся по ним, не по догадке).
    assert {it["category"] for it in emb} == {"models"}
    assert {it["category"] for it in keys} == {"keys"}
    # Метаданные групп приходят тем же ответом — заголовки берём из каталога.
    gids = {g["id"]: g for g in body["groups"]}
    assert EMB_GROUP in gids and KEYS_GROUP in gids
    assert gids[EMB_GROUP]["title"] == "Отпечатки текста и длина"
    assert gids[EMB_GROUP]["category"] == "models"


def test_plain_user_loses_secret_keys_but_keeps_model_params(client):
    """Настоящий фильтр прав существует — но он не объясняет пустоту админа."""
    resp = client.get("/api/config", headers=_hdr(USER_ID))
    assert resp.status_code == 200
    body = resp.json()
    assert _items_of(body, EMB_GROUP), (
        "несекретные параметры embeddings видны и обычному пользователю")
    assert not _items_of(body, KEYS_GROUP), (
        "ключи-секреты не-админу сервер не отдаёт — это и есть права")


def _registry_snapshot():
    """Ровно то, что получает фронт: `registry_for_frontend()`."""
    from services.module_registry import registry_for_frontend
    return registry_for_frontend()


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
        res = subprocess.run([node, SCRIPT, snap], capture_output=True,
                             text=True, timeout=180, cwd=root)
    finally:
        try:
            os.unlink(snap)
        except OSError:
            pass
    assert res.returncode == 0, (
        "MOD-ACL-UX-01 M4 JS-UNIT провалился:\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (res.stdout, res.stderr))
    assert "MOD-ACL-UX-01 M4 MODULE PARAMS OK" in res.stdout
