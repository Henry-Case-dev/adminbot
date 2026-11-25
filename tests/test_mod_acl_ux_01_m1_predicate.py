"""MOD-ACL-UX-01 M1-B — единый предикат «глобальный админ» и границы секретов.

TEST-LIFECYCLE: CONTRACT owner=MAC-S4-174 (одна семантика прав в HTTP и в
чате) / MAC-S4-172 + MAC-S10-13 (секреты не выходят наружу) /
MAC-S4-171 (401≠403≠404≠503 на уровне отданных байт).

Дефект на выкаченной сборке `a64ecb89b` (2.58.250), проверенный здесь
поведением, а не чтением:

  * `web/api/deps.user_is_global_admin` — канон админки:
    `wildcard OR role_type == "global_admin" OR legacy-роль "admin"`;
  * `services/chat_access.is_admin` — тот же вопрос для чата, но отвечал
    только по `telegram_id == ADMIN_USER_ID` или строке роли `admin`.
    Следствие: глобальный админ Mini App (`role_type=global_admin` или
    wildcard) в боте считался обычным пользователем (`direct_chat_service`
    проверяет `privilege(...) == "user"`, `mca_style_scope` —
    `is_admin(...)`).

Что доказывается:
  (1) матрица паритета: `chat_access.is_global_admin` и
      `deps.user_is_global_admin` на ОДНОМ снимке `ConfigCache` дают
      одинаковый ответ по всем формам роли (RED на базе — две строки);
  (2) потребители: `privilege()`/`is_moderator()`/`_has_chat_admin_rights`;
  (3) секреты: посаженный секрет не доходит до отданных байт
      `/api/status/logs` и не остаётся в записи журнала; положительный
      контроль — тот же секрет ДО маскировки присутствует, и без
      литерального секрета каталога он не маскируется (значит проверка
      различает, а не проходит вхолостую);
  (4) четыре состояния доступа различаются статусом И телом.

Живой сессии Telegram нет: initData подписывается тестовым токеном,
подменённым в модуле зависимостей (прецедент
`tests/test_acl_global_admin_role_permission_gate.py`); продовый токен не
используется, сеть не поднимается.
"""
import asyncio
import collections
import hashlib
import hmac
import json
import logging
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from services import chat_access
from services import hot_config as hot
from services import log_ring as log_ring_mod
from services.config_cache import ConfigCache
from services.log_ring import SecretMaskFilter, get_log_ring
from services.permissions import Permissions
from web.api import deps as deps_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_M1B_PREDICATE"

# id не пересекаются с settings.ADMIN_USER_ID (владелец — отдельная ветка).
GLOBAL_ADMIN_ID = 880000111     # role_type=global_admin, прав нет, имя не admin
WILDCARD_ID = 880000222         # custom-роль с wildcard
LEGACY_ADMIN_ID = 880000333     # имя роли "admin", role_type в колонке NULL
CUSTOM_ACCESS_ID = 880000444    # custom: секция `access`, без wildcard
MODERATOR_ID = 880000555         # встроенный moderator
PLAIN_USER_ID = 880000666       # встроенный user
UNKNOWN_ID = 880000999          # нет строки в bot_admins

# ── helpers ─────────────────────────────────────────────────────────────────


def _seed_roles(cache: ConfigCache) -> None:
    """Матрица ролей как её собирает `_load_all` из PG (имя + role_type)."""
    cache._roles = {
        "owner_global": {"permissions": {}, "is_custom": False,
                         "role_type": "global_admin"},
        "wildcard_custom": {"permissions": {"wildcard": True},
                            "is_custom": True, "role_type": None},
        "admin": {"permissions": {}, "is_custom": False, "role_type": None},
        "custom_access": {"permissions": {"sections": ["access"]},
                          "is_custom": True, "role_type": None},
        "moderator": {"permissions": {"sections": ["limits"],
                                      "actions": ["control.restart"]},
                      "is_custom": False, "role_type": "moderator"},
        "user": {"permissions": {}, "is_custom": False, "role_type": "user"},
    }
    cache._permissions = {
        name: Permissions.from_dict(role["permissions"])
        for name, role in cache._roles.items()
    }
    cache._admins = {
        GLOBAL_ADMIN_ID: "owner_global",
        WILDCARD_ID: "wildcard_custom",
        LEGACY_ADMIN_ID: "admin",
        CUSTOM_ACCESS_ID: "custom_access",
        MODERATOR_ID: "moderator",
        PLAIN_USER_ID: "user",
    }
    cache._initialized = True


@pytest.fixture
def cache():
    """Живой `ConfigCache` (без PG) — один снимок для обеих сторон."""
    old = hot.get_config_cache()
    snap = ConfigCache(pg=None, retry_attempts=1, retry_delay=0)
    _seed_roles(snap)
    hot.set_config_cache(snap)
    try:
        yield snap
    finally:
        hot.set_config_cache(old)


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


@pytest.fixture
def client(monkeypatch):
    """Приложение стенда: реальные роутеры + тестовый токен HMAC."""
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    snap = ConfigCache(pg=None, retry_attempts=1, retry_delay=0)
    _seed_roles(snap)
    old = hot.get_config_cache()
    hot.set_config_cache(snap)
    app = create_app(snap)
    try:
        with TestClient(app) as tc:
            _seed_roles(snap)          # startup мог переинициализировать кэш
            hot.set_config_cache(snap)
            yield tc
    finally:
        hot.set_config_cache(old)


# ── (1) паритет предикатов: чат и админка отвечают одинаково ────────────────

PARITY_CASES = [
    # (метка, telegram_id, ожидание обеих сторон)
    ("role_type=global_admin, прав нет", GLOBAL_ADMIN_ID, True),
    ("custom-роль с wildcard", WILDCARD_ID, True),
    ("legacy-роль admin (role_type NULL)", LEGACY_ADMIN_ID, True),
    ("custom: секция access без wildcard", CUSTOM_ACCESS_ID, False),
    ("встроенный moderator", MODERATOR_ID, False),
    ("встроенный user", PLAIN_USER_ID, False),
    ("нет строки в bot_admins", UNKNOWN_ID, False),
]


class TestPredicateParity:
    """`chat_access.is_global_admin` == `user_is_global_admin` (MAC-S4-174)."""

    @pytest.mark.parametrize("label,tid,expected", PARITY_CASES,
                             ids=[c[0] for c in PARITY_CASES])
    def test_bot_and_admin_side_agree(self, cache, label, tid, expected):
        admin_side = deps_mod.user_is_global_admin(cache, tid)
        bot_side = chat_access.is_global_admin(tid)
        assert admin_side is expected, (label, "admin-side")
        # RED на a64ecb89b: для role_type=global_admin и wildcard бот
        # отвечал False — здесь падает именно это равенство.
        assert bot_side is admin_side, label

    def test_global_admin_by_role_type_is_admin_in_chat(self, cache):
        """Дефект M1-B буквально: глобальный админ Mini App — не админ бота."""
        assert chat_access.is_admin(GLOBAL_ADMIN_ID) is True
        assert chat_access.privilege(GLOBAL_ADMIN_ID) == "admin"

    def test_wildcard_custom_is_admin_in_chat(self, cache):
        assert chat_access.is_admin(WILDCARD_ID) is True
        assert chat_access.privilege(WILDCARD_ID) == "admin"

    def test_specific_permission_is_not_global_admin(self, cache):
        """Модель прав не ослаблена: `access`-секция ≠ глобальный админ."""
        assert chat_access.is_global_admin(CUSTOM_ACCESS_ID) is False
        assert chat_access.privilege(CUSTOM_ACCESS_ID) == "user"

    def test_owner_shortcut_is_bot_only_and_documented(self, cache):
        """ADMIN_USER_ID — бот-фолбэк R6 (ADR канoна `deps` его не содержит).

        Это единственное намеренное расхождение сторон: без него владелец
        терял бы админку в чате при недоступном PG/пустом кэше. Фиксируем
        обе стороны явно, чтобы расхождение не разрасталось молча.
        """
        owner = int(settings.ADMIN_USER_ID)
        assert chat_access.is_global_admin(owner) is False   # роли в кэше нет
        assert chat_access.is_admin(owner) is True           # бот-фолбэк
        assert deps_mod.user_is_global_admin(cache, owner) is False

    def test_admin_role_of_name_admin_with_foreign_role_type(self, cache):
        """Строка `admin` с явным role_type — та же сторона, тот же ответ."""
        cache._roles["admin"] = {"permissions": {}, "is_custom": False,
                                 "role_type": "custom"}
        cache._permissions["admin"] = Permissions.from_dict({})
        assert chat_access.is_global_admin(LEGACY_ADMIN_ID) is True
        assert deps_mod.user_is_global_admin(cache, LEGACY_ADMIN_ID) is True

    def test_no_cache_is_fail_closed(self):
        """Кэш не инициализирован → не админ, без исключений."""
        old = hot.get_config_cache()
        hot.set_config_cache(None)
        try:
            assert chat_access.is_global_admin(PLAIN_USER_ID) is False
            assert chat_access.is_admin(PLAIN_USER_ID) is False
            assert chat_access.privilege(PLAIN_USER_ID) == "user"
        finally:
            hot.set_config_cache(old)

    def test_broken_cache_does_not_raise(self, cache, monkeypatch):
        """Сбой чтения ролей — fail-closed, а не падение горячего пути."""
        def boom():
            raise RuntimeError("cache broken")
        monkeypatch.setattr(cache, "roles", boom)
        assert chat_access.is_admin(GLOBAL_ADMIN_ID) is False
        assert chat_access.privilege(GLOBAL_ADMIN_ID) == "user"


# ── (2) потребители предиката ───────────────────────────────────────────────

class TestConsumers:
    def test_privilege_and_moderator_for_global_admin(self, cache):
        assert chat_access.privilege(GLOBAL_ADMIN_ID) == "admin"
        assert chat_access.is_moderator(GLOBAL_ADMIN_ID) is True

    def test_moderator_unchanged(self, cache):
        assert chat_access.privilege(MODERATOR_ID) == "moderator"
        assert chat_access.is_admin(MODERATOR_ID) is False

    def test_mca_style_scope_chat_admin_rights(self, cache):
        """`_has_chat_admin_rights` (mca_style_scope) видит глобального админа.

        Дефект: chat-scope просьба по стилю от глобального админа Mini App
        получала `style_request_denied`.
        """
        from services import mca_style_scope
        assert asyncio.run(
            mca_style_scope._has_chat_admin_rights(GLOBAL_ADMIN_ID, -100)) is True
        assert asyncio.run(
            mca_style_scope._has_chat_admin_rights(PLAIN_USER_ID, -100)) is False


# ── (3) четыре состояния доступа: 401 ≠ 403 ≠ 404 ≠ 503 ─────────────────────

class TestAccessStates:
    """MAC-S4-171: отказ не сводится к одному «нет доступа»."""

    def test_401_missing_init_data(self, client):
        resp = client.get("/api/admins")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "missing init data"

    def test_401_invalid_signature(self, client):
        resp = client.get("/api/admins", headers=_hdr(GLOBAL_ADMIN_ID,
                                                      hash_ok=False))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "invalid init data"

    def test_403_authenticated_without_permission(self, client):
        resp = client.get("/api/admins", headers=_hdr(PLAIN_USER_ID))
        assert resp.status_code == 403
        assert resp.json()["detail"] == "permission denied"

    def test_404_unknown_route(self, client):
        resp = client.get("/api/no-such-route-m1b")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Not Found"

    def test_404_missing_resource_under_valid_admin(self, client):
        """Нет возможности/ресурса — 404, и это НЕ 403 и НЕ 503."""
        resp = client.delete(
            "/api/access/diagnostic_policy/__m1b_absent_cap__",
            headers=_hdr(GLOBAL_ADMIN_ID))
        assert resp.status_code == 404, resp.text
        assert "нет такой возможности" in resp.json()["detail"]

    def test_503_backend_unavailable_under_valid_admin(self, client):
        """PG недоступен → 503, а не 403 «нет доступа»."""
        resp = client.put(
            "/api/access/param_permissions/limits.x",
            headers=_hdr(GLOBAL_ADMIN_ID),
            json={"view_min_role": "moderator"})
        assert resp.status_code == 503, resp.text
        assert "PostgreSQL" in resp.json()["detail"]

    def test_four_states_are_pairwise_distinct(self, client):
        """Собираем четыре отказа в одном прогоне и сравниваем тела."""
        body = {
            401: client.get("/api/admins").json()["detail"],
            403: client.get("/api/admins",
                            headers=_hdr(PLAIN_USER_ID)).json()["detail"],
            404: client.get("/api/no-such-route-m1b").json()["detail"],
            503: client.put("/api/access/param_permissions/limits.x",
                            headers=_hdr(GLOBAL_ADMIN_ID),
                            json={"view_min_role": "moderator"}
                            ).json()["detail"],
        }
        assert set(body) == {401, 403, 404, 503}
        assert len(set(body.values())) == 4, body
        assert body[403] != body[401]      # «нет прав» не выдаётся за «нет сессии»
        assert body[503] != body[403]      # недоступность ≠ отсутствие прав


# ── (4) секреты: не выходят в отданные байты и в журнал ─────────────────────

LITERAL_PLANT = "M1B-LITERAL-PLANT-9f3c1d"      # без sk-/bearer/URI-шаблона
PREFIX_PLANT = "sk-m1bplanted0123456789"        # подпадает под _PREFIX_RE
BENIGN = "m1b-benign-marker-ok"


@pytest.fixture
def ring():
    """Модульный ring-буфер: подключаем к root и восстанавливаем содержимое."""
    r = get_log_ring()
    root = logging.getLogger()
    attached = r not in root.handlers
    if attached:
        r.setLevel(logging.DEBUG)
        root.addHandler(r)
    snapshot = collections.deque(r._buffer, maxlen=r.maxlen)
    try:
        yield r
    finally:
        r._buffer.clear()
        r._buffer.extend(snapshot)
        if attached:
            root.removeHandler(r)


class TestSecretsDoNotLeave:
    def test_planted_literal_is_caught_by_literal_masking_only(self, monkeypatch):
        """Положительный контроль: без литерала каталога секрет не ловится."""
        monkeypatch.setattr(log_ring_mod, "_SECRETS", ())
        assert log_ring_mod.sanitize(f"key={LITERAL_PLANT}") \
            == f"key={LITERAL_PLANT}"
        monkeypatch.setattr(log_ring_mod, "_SECRETS", (LITERAL_PLANT,))
        assert log_ring_mod.sanitize(f"key={LITERAL_PLANT}") == "key=***"

    def test_planted_secrets_absent_from_served_log_payload(self, client, ring,
                                                            monkeypatch):
        """Секрет в журнале не доходит до отданных байт `/api/status/logs`."""
        monkeypatch.setattr(log_ring_mod, "_SECRETS", (LITERAL_PLANT,))
        log = logging.getLogger("m1b.secret_probe")
        record = log.makeRecord(
            log.name, logging.WARNING, __file__, 0,
            "probe %s %s %s", (BENIGN, LITERAL_PLANT, PREFIX_PLANT), None)
        # Положительный контроль: посадка реальна — до маскировки секреты в
        # записи есть, значит их отсутствие ниже не тавтология.
        raw = record.getMessage()
        assert LITERAL_PLANT in raw and PREFIX_PLANT in raw
        # Продовый фильтр консоли/journald: маскирует саму запись.
        SecretMaskFilter().filter(record)
        assert LITERAL_PLANT not in record.getMessage()
        assert PREFIX_PLANT not in record.getMessage()
        assert BENIGN in record.getMessage()
        # Кольцо логов маскирует при записи; читаем через API.
        log.handle(record)

        resp = client.get("/api/status/logs",
                          headers=_hdr(PLAIN_USER_ID), params={"limit": 200})
        assert resp.status_code == 200, resp.text
        assert BENIGN in resp.text                      # запись реально отдана
        assert LITERAL_PLANT not in resp.text
        assert PREFIX_PLANT not in resp.text

    def test_status_logs_requires_authentication(self, client):
        """Граница: без сессии журнал не отдаётся вовсе (401, не пустой 200)."""
        assert client.get("/api/status/logs").status_code == 401
