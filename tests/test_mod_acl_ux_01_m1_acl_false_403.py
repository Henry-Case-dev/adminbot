"""MOD-ACL-UX-01 (M1) — единая проверка «глобальный админ» (ACL false-403).

TEST-LIFECYCLE: REGRESSION owner=MOD-ACL-UX-01 §4.1 (ACL false-403)

Дефект (baseline M0 §3): `web/api/memory_agi.py` держал ЛОКАЛЬНУЮ копию
проверки админа (`telegram_id == ADMIN_USER_ID` / `role == "admin"` /
wildcard) и не вызывал `role_type_of()`. Пользователь с
`role_type="global_admin"`, но без legacy-строки `role == "admin"`,
получал 403 на всех `/api/memory/*` (жалоба владельца на Vector Memory /
Embeddings).

Что доказываем:
  (a) role_type=global_admin без legacy-имени роли → 200 (права роли при
      этом пустые — wildcard-путь тоже не участвует);
  (b) legacy-роль `admin` (role_type в колонке NULL) → 200 (нет регрессии);
  (c) локальный админ чата и обычный юзер → 403 на глобальных эндпоинтах;
  (d) нет initData / битая подпись → 401 (не 403);
  (e) кросс-чатовый доступ не расширен: локальный админ чата A не получает
      чат B (`chat_lore.can_access_chat`) и глобальные memory-эндпоинты.

БД не поднимается: stub-объект lore_runtime, глобальные эндпоинты
fail-open на ошибках БД (shape-совместимый 200) — проверяется именно
ACL-вердикт, а не содержимое метрик.
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from services.permissions import Permissions
from web.app import create_app
from web.api import chat_lore
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_ACL_M1"

# role_type=global_admin, но имя роли НЕ "admin" — прежний локальный guard
# (role == "admin") отбивал такого пользователя 403.
GLOBAL_ADMIN_ID = 770000111
# legacy-сид: имя роли "admin", колонка role_type = NULL.
LEGACY_ADMIN_ID = 770000222
LOCAL_ADMIN_ID = 770000333
PLAIN_USER_ID = 770000444

CHAT_A = -1001000000001
CHAT_B = -1001000000002


# ── helpers ─────────────────────────────────────────────────────────────────

def make_init_data(user_id: int, *, hash_ok: bool = True) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A"},
                           separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hash_ok:
        calc = "0" * 64
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc}"


def _hdr(user_id: int = GLOBAL_ADMIN_ID, *, hash_ok: bool = True) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id, hash_ok=hash_ok)}


def _seed_roles(cache: ConfigCache) -> None:
    """Матрица ролей как в PG: имя роли + колонка role_type.

    `owner_global` — role_type=global_admin с ПУСТЫМИ правами: проверка
    проходит только через role_type (не через wildcard и не через имя).
    `admin` — legacy-сид: role_type NULL, права пустые (без wildcard), т.е.
    единственный признак — legacy-эвристика `role_type_of` по имени.
    """
    cache._roles = {
        "owner_global": {"permissions": {}, "is_custom": False,
                         "role_type": "global_admin"},
        "admin": {"permissions": {}, "is_custom": False,
                  "role_type": None},
        "local_admin": {"permissions": {}, "is_custom": False,
                        "role_type": "local_admin"},
        "user": {"permissions": {}, "is_custom": False,
                 "role_type": "user"},
    }
    cache._permissions = {
        name: Permissions.from_dict(role["permissions"])
        for name, role in cache._roles.items()
    }
    cache._admins = {
        GLOBAL_ADMIN_ID: "owner_global",
        LEGACY_ADMIN_ID: "admin",
        LOCAL_ADMIN_ID: "local_admin",
        PLAIN_USER_ID: "user",
    }
    cache._initialized = True


class _StubDb:
    """lore_runtime db-подмена: любая БД-операция падает → fail-open 200."""

    async def graph_stats(self, chat_id=None):
        raise RuntimeError("stub db")

    def __getattr__(self, name):  # pragma: no cover - defensive
        raise AttributeError(f"stub db: {name}")


def _new_cache() -> ConfigCache:
    cache = ConfigCache(pg=None, retry_attempts=1, retry_delay=0)
    _seed_roles(cache)
    return cache


@pytest.fixture
def cache() -> ConfigCache:
    return _new_cache()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    cache = _new_cache()
    app = create_app(cache)
    from services import lore_runtime
    lore_runtime.set_lore_components(db=_StubDb())
    try:
        with TestClient(app) as tc:
            # startup мог переинициализировать кэш — матрица ролей нужна живой
            _seed_roles(cache)
            yield tc
    finally:
        lore_runtime.reset_lore_runtime()


# ── (a)/(b) канонная проверка: доступ выдаётся ──────────────────────────────

class TestCanonicalAdminGetsAccess:
    def test_role_type_global_admin_gets_200(self, client):
        """role_type=global_admin без legacy-строки `admin` → 200 (было 403)."""
        for path in ("/api/memory/stats", "/api/memory/embeddings"):
            resp = client.get(path, headers=_hdr(GLOBAL_ADMIN_ID))
            assert resp.status_code == 200, (path, resp.text)

    def test_role_type_global_admin_sees_no_legacy_string(self, client):
        """Страховка от тавтологии: у проверяемого юзера реально нет 'admin'."""
        cache = client.app.state.cache
        assert cache.get_role(GLOBAL_ADMIN_ID) == "owner_global"
        assert cache.get_role(GLOBAL_ADMIN_ID) != "admin"
        assert cache.get_permissions_by_telegram_id(
            GLOBAL_ADMIN_ID).wildcard is False

    def test_legacy_admin_role_still_gets_200(self, client):
        """Legacy-роль `admin` (role_type NULL) — регрессии нет."""
        resp = client.get("/api/memory/stats", headers=_hdr(LEGACY_ADMIN_ID))
        assert resp.status_code == 200, resp.text

    def test_wildcard_role_still_gets_200(self, client):
        """Wildcard-права (не-owner кастомная роль) не потеряны."""
        cache = client.app.state.cache
        cache._roles["wildcard_custom"] = {
            "permissions": {"wildcard": True}, "is_custom": True,
            "role_type": None}
        cache._permissions["wildcard_custom"] = Permissions.from_dict(
            {"wildcard": True})
        cache._admins[PLAIN_USER_ID + 1000] = "wildcard_custom"
        resp = client.get("/api/memory/stats",
                          headers=_hdr(PLAIN_USER_ID + 1000))
        assert resp.status_code == 200, resp.text


# ── (c) границы не расширены: локальный админ и юзер ────────────────────────

class TestNonGlobalAdminStillDenied:
    @pytest.mark.parametrize("user_id", [LOCAL_ADMIN_ID, PLAIN_USER_ID])
    @pytest.mark.parametrize("path", ["/api/memory/stats",
                                      "/api/memory/embeddings"])
    def test_403_for_local_admin_and_user(self, client, user_id, path):
        resp = client.get(path, headers=_hdr(user_id))
        assert resp.status_code == 403, (path, resp.text)

    def test_403_on_mutating_endpoint(self, client):
        """POST (мягкое удаление belief) — тоже только глобальный админ."""
        resp = client.delete("/api/memory/dream/beliefs/1",
                             headers=_hdr(LOCAL_ADMIN_ID))
        assert resp.status_code == 403, resp.text


# ── (d) аутентификация: 401, а не 403 ──────────────────────────────────────

class TestAuthStatusCodes:
    def test_missing_init_data_is_401(self, client):
        assert client.get("/api/memory/stats").status_code == 401

    def test_broken_signature_is_401(self, client):
        resp = client.get("/api/memory/stats",
                          headers=_hdr(GLOBAL_ADMIN_ID, hash_ok=False))
        assert resp.status_code == 401

    def test_broken_query_init_data_is_401(self, client):
        resp = client.get("/api/memory/stats?initData=garbage")
        assert resp.status_code == 401


# ── (e) кросс-чатовые границы ─────────────────────────────────────────────

class _StubStore:
    """chat_lore store: только явные строки chat_admins."""

    def __init__(self, grants=()):
        self._grants = set(grants)

    async def is_chat_admin(self, telegram_id: int, chat_id: int) -> bool:
        return (int(telegram_id), int(chat_id)) in self._grants


class TestCrossChatIsolation:
    @pytest.mark.asyncio
    async def test_local_admin_cannot_reach_other_chat(self, cache):
        store = _StubStore({(LOCAL_ADMIN_ID, CHAT_A)})
        assert await chat_lore.can_access_chat(
            cache, store, LOCAL_ADMIN_ID, CHAT_A) is True
        assert await chat_lore.can_access_chat(
            cache, store, LOCAL_ADMIN_ID, CHAT_B) is False
        assert await chat_lore.can_access_chat(
            cache, store, PLAIN_USER_ID, CHAT_A) is False

    @pytest.mark.asyncio
    async def test_global_admin_role_still_sees_all_chats(self, cache):
        store = _StubStore()
        assert await chat_lore.can_access_chat(
            cache, store, GLOBAL_ADMIN_ID, CHAT_B) is True
        assert await chat_lore.can_access_chat(
            cache, store, LEGACY_ADMIN_ID, CHAT_B) is True

    def test_local_admin_cannot_read_global_memory(self, client):
        """Локальный админ чата не получает глобальный memory-эндпоинт."""
        resp = client.get("/api/memory/stats?chat_id=%d" % CHAT_A,
                          headers=_hdr(LOCAL_ADMIN_ID))
        assert resp.status_code == 403


# ── chat_lore: тот же дефект закрыт общим guard'ом ────────────────────────

class TestChatLoreGuard:
    def test_guard_follows_role_type(self, cache):
        assert chat_lore._is_global_admin(cache, GLOBAL_ADMIN_ID) is True
        assert chat_lore._is_global_admin(cache, LEGACY_ADMIN_ID) is True
        assert chat_lore._is_global_admin(cache, LOCAL_ADMIN_ID) is False
        assert chat_lore._is_global_admin(cache, PLAIN_USER_ID) is False


# ── структурная страховка: второй копии проверки не осталось ──────────────

class TestNoLocalAdminCopy:
    def test_memory_module_has_single_canonical_guard(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parents[1] /
               "web" / "api" / "memory_agi.py").read_text(encoding="utf-8")
        assert "def _is_global_admin" not in src
        assert "from web.api.deps import" in src
        assert "user_is_global_admin" in src
        # все memory-эндпоинты идут через единый враппер
        assert src.count("_require_global_admin(request, user)") >= 15
