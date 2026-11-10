"""MAC-DEF-01 — role_type=global_admin проходит гейты `requires_permission`.

TEST-LIFECYCLE: CONTRACT owner=MAC-DEF-01 (ACL: глобальный админ и гейты
секции `access`)

Дефект (проверен по коду 721bab10): `web/api/deps.py::requires_permission`
решал доступ только через `services.permissions.requires_permission`
(матчинг 84.14.2) и не смотрел на `role_type`. Поэтому роль с
`role_type="global_admin"`, но без `wildcard` получала 403 на всех гейтах
«access» — `/api/admins`, `/api/roles`, `/api/cover/*` (33 эндпоинта).
Владельца дефект не задевал только потому, что seeded-роль `admin` несёт
`{"wildcard": true}` — природа та же, что у ACL false-403 в MOD-ACL-UX-01.

Что доказываем РЕАЛЬНЫМИ статусами через `create_app` (не моками вызовов):
  (a) role_type=global_admin с ПУСТЫМИ правами → 200 на /api/admins,
      /api/roles и /api/cover/styles;
  (b) custom-роль без права `access` → 403 на тех же трёх (модель прав не
      ослаблена, «всем всё» не включено);
  (c) обычный юзер → 403;
  (d) без initData / битая подпись → 401 (а не 403);
  (e) legacy-роль `admin` (role_type в колонке NULL), wildcard-роль и
      custom-роль с секцией `access` → 200 (нет регрессии);
  (f) matcher `services.permissions.requires_permission` для этой роли
      по-прежнему False — проход даёт новый канон, а не изменённый матчинг.

БД не поднимается: `ConfigCache(pg=None)`, registry cover-стилей отдаёт
пустой список (изоляция ввода-вывода, не предмет проверки).
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from services.permissions import Permissions
from web.api import deps as deps_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_ACL_GLOBAL_ADMIN_GATE"

# role_type=global_admin, но имя роли НЕ "admin" и прав нет (без wildcard).
GLOBAL_ADMIN_ID = 880000111
# legacy-сид: имя роли "admin", колонка role_type = NULL, права пустые.
LEGACY_ADMIN_ID = 880000222
# custom-роль с явной секцией `access` (permission-модель работает как раньше).
CUSTOM_ACCESS_ID = 880000333
# custom-роль с чужим правом (`limits`) — на гейтах `access` обязан 403.
CUSTOM_LIMITS_ID = 880000444
# встроенный moderator: только actions, без `access`.
MODERATOR_ID = 880000555
PLAIN_USER_ID = 880000666
WILDCARD_ID = 880000777

# 33 гейта `requires_permission` живут на трёх репрезентативных путях:
GATED_PATHS = ("/api/admins", "/api/roles", "/api/cover/styles")


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


def _hdr(user_id: int, *, hash_ok: bool = True) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id, hash_ok=hash_ok)}


def _seed_roles(cache: ConfigCache) -> None:
    """Матрица ролей как в PG: имя роли + колонка `role_type`.

    `owner_global` — role_type=global_admin с ПУСТЫМИ правами: пройти гейт
    можно только по role_type (не по wildcard и не по имени роли).
    """
    cache._roles = {
        "owner_global": {"permissions": {}, "is_custom": False,
                         "role_type": "global_admin"},
        "admin": {"permissions": {}, "is_custom": False, "role_type": None},
        "moderator": {"permissions": {"sections": ["limits"],
                                      "actions": ["control.restart"]},
                      "is_custom": False, "role_type": "moderator"},
        "custom_access": {"permissions": {"sections": ["access"]},
                          "is_custom": True, "role_type": None},
        "custom_limits": {"permissions": {"sections": ["limits"]},
                          "is_custom": True, "role_type": None},
        "wildcard_custom": {"permissions": {"wildcard": True},
                            "is_custom": True, "role_type": None},
        "user": {"permissions": {}, "is_custom": False, "role_type": "user"},
    }
    cache._permissions = {
        name: Permissions.from_dict(role["permissions"])
        for name, role in cache._roles.items()
    }
    cache._admins = {
        GLOBAL_ADMIN_ID: "owner_global",
        LEGACY_ADMIN_ID: "admin",
        MODERATOR_ID: "moderator",
        CUSTOM_ACCESS_ID: "custom_access",
        CUSTOM_LIMITS_ID: "custom_limits",
        WILDCARD_ID: "wildcard_custom",
        PLAIN_USER_ID: "user",
    }
    # F7: карточки для GET /api/admins (иначе список пуст и проверка payload
    # выродилась бы в «пустой 200»).
    cache._admins_full = {
        GLOBAL_ADMIN_ID: {"telegram_id": GLOBAL_ADMIN_ID,
                          "role_name": "owner_global",
                          "added_by": None, "created_at": None},
    }
    cache._initialized = True


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    # cover-registry: изоляция ввода-вывода (не предмет проверки ACL).
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)
    monkeypatch.setattr("services.cover_style_registry.list_profiles",
                        AsyncMock(return_value=[]))
    cache = ConfigCache(pg=None, retry_attempts=1, retry_delay=0)
    _seed_roles(cache)
    app = create_app(cache)
    with TestClient(app) as tc:
        # startup мог переинициализировать кэш — матрица ролей нужна живой.
        _seed_roles(cache)
        yield tc


# ── (a) канон: глобальный админ по role_type проходит ───────────────────────

class TestGlobalAdminRoleTypePasses:
    @pytest.mark.parametrize("path", GATED_PATHS)
    def test_role_type_global_admin_gets_200(self, client, path):
        """Было 403: rights пустые, role_type=global_admin, имя не `admin`."""
        resp = client.get(path, headers=_hdr(GLOBAL_ADMIN_ID))
        assert resp.status_code == 200, (path, resp.text)

    def test_admins_payload_is_real(self, client):
        """200 — это исполнение маршрута, а не заглушка: карточка админа."""
        resp = client.get("/api/admins", headers=_hdr(GLOBAL_ADMIN_ID))
        body = resp.json()
        assert [a["telegram_id"] for a in body["admins"]] == [GLOBAL_ADMIN_ID]
        assert body["admins"][0]["role_name"] == "owner_global"

    def test_roles_payload_is_real(self, client):
        body = client.get("/api/roles",
                          headers=_hdr(GLOBAL_ADMIN_ID)).json()
        roles = {r["role_name"]: r for r in body["roles"]}
        assert roles["owner_global"]["role_type"] == "global_admin"
        # права роли действительно пустые — проход даёт role_type
        assert roles["owner_global"]["permissions"] == {}

    def test_cover_payload_is_real(self, client):
        body = client.get("/api/cover/styles",
                          headers=_hdr(GLOBAL_ADMIN_ID)).json()
        assert body["enabled"] is True
        assert "styles" in body and "no_style_label" in body

    def test_pass_comes_from_role_type_not_from_matcher(self, client):
        """Страховка от тавтологии: матчер прав для этой роли — False.

        Проход даёт канон `user_is_global_admin` (role_type), а не
        ослабленный `services.permissions.requires_permission`.
        """
        cache = client.app.state.cache
        perms = cache.get_permissions_by_telegram_id(GLOBAL_ADMIN_ID)
        assert perms.wildcard is False
        assert cache.get_role(GLOBAL_ADMIN_ID) != "admin"
        from services.permissions import requires_permission as match_permission
        for required in ("access", "section.access", "action.control.stop",
                         "param.limits.x"):
            assert match_permission(perms, required) is False, required
        # и при этом гейт пропускает
        assert deps_mod.user_has_permission(cache, GLOBAL_ADMIN_ID,
                                           "access") is True


# ── (b) границы модели прав не расширены ───────────────────────────────────

class TestPermissionModelNotRelaxed:
    @pytest.mark.parametrize("path", GATED_PATHS)
    def test_custom_role_without_access_gets_403(self, client, path):
        resp = client.get(path, headers=_hdr(CUSTOM_LIMITS_ID))
        assert resp.status_code == 403, (path, resp.text)
        assert resp.json()["detail"] == "permission denied"

    @pytest.mark.parametrize("path", GATED_PATHS)
    def test_moderator_actions_only_gets_403(self, client, path):
        """role_type=moderator — не глобальный админ, `access` ему не выдан."""
        resp = client.get(path, headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403, (path, resp.text)

    @pytest.mark.parametrize("path", GATED_PATHS)
    def test_wildcard_role_not_affected(self, client, path):
        """custom-роль с wildcard проходила и раньше — регрессии нет."""
        resp = client.get(path, headers=_hdr(WILDCARD_ID))
        assert resp.status_code == 200, (path, resp.text)

    def test_non_admin_field_rights_unchanged(self, client):
        """Модератор сохраняет своё право action-уровня (helper, не гейт)."""
        cache = client.app.state.cache
        assert deps_mod.user_has_permission(
            cache, MODERATOR_ID, "action.control.restart") is True
        assert deps_mod.user_has_permission(
            cache, PLAIN_USER_ID, "action.control.restart") is False


# ── (c) обычный юзер ───────────────────────────────────────────────────────

class TestPlainUserDenied:
    @pytest.mark.parametrize("path", GATED_PATHS)
    def test_plain_user_gets_403(self, client, path):
        resp = client.get(path, headers=_hdr(PLAIN_USER_ID))
        assert resp.status_code == 403, (path, resp.text)

    def test_unknown_telegram_id_gets_403(self, client):
        """Неизвестный ID → роль user без прав → 403 (не 500/не 200)."""
        resp = client.get("/api/admins", headers=_hdr(899999999))
        assert resp.status_code == 403


# ── (d) аутентификация: 401, а не 403 ──────────────────────────────────────

class TestAuthStatusCodes:
    @pytest.mark.parametrize("path", GATED_PATHS)
    def test_missing_init_data_is_401(self, client, path):
        assert client.get(path).status_code == 401

    @pytest.mark.parametrize("path", GATED_PATHS)
    def test_broken_signature_is_401(self, client, path):
        resp = client.get(path, headers=_hdr(GLOBAL_ADMIN_ID, hash_ok=False))
        assert resp.status_code == 401


# ── (e) legacy-роль `admin` и явная секция access ──────────────────────────

class TestLegacyAndExplicitAccessStillWork:
    @pytest.mark.parametrize("path", GATED_PATHS)
    def test_legacy_admin_string_role_gets_200(self, client, path):
        """Роль `admin` с role_type=NULL и пустыми правами — как раньше."""
        resp = client.get(path, headers=_hdr(LEGACY_ADMIN_ID))
        assert resp.status_code == 200, (path, resp.text)

    @pytest.mark.parametrize("path", GATED_PATHS)
    def test_custom_role_with_access_section_gets_200(self, client, path):
        """Канонический путь 84.14.2 (секция `access`) не сломан."""
        resp = client.get(path, headers=_hdr(CUSTOM_ACCESS_ID))
        assert resp.status_code == 200, (path, resp.text)
