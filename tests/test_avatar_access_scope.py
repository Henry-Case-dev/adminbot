"""avatar-scope (privacy-фикс): кто вправе получить картинку по
`GET /api/avatar/{kind}/{tid}`.

До фикса эндпоинт проверял ТОЛЬКО аутентификацию (`Depends(get_tma_user)`),
хотя id в пути приходит от клиента, а мини-апп открывается из /menu любому,
кто написал боту (`handlers/menu.py`: «Доступна ВСЕМ»). Т.е. любой валидный
TMA-юзер мог тянуть фото произвольного Telegram-id (Bot API
getUserProfilePhotos / getChat) и аватар любого чата бота.

Контракт после фикса (правило выведено из продукта: мини-апп показывает
аватары ровно из RBAC-отфильтрованных списков — self, доступные чаты,
участники доступного чата):
  * self — всегда 200 (в т.ч. ролью `user`);
  * глобальный админ — любой аватар (владелец видит весь мини-апп);
  * kind=chat — 200 только для чата, доступного запросившему (канон
    `access.can_access_chat`); иначе 403;
  * kind=user — 200 только для участника (users_meta) или админа
    (chat_admins) чата, доступного запросившему; иначе 403;
  * без initData — 401 (не изменилось);
  * отказ — ДО Bot API (чужой аватар не тянется вообще) и без записи
    негатива в кэш байтов; форма ответа прежняя (image/jpeg), а кэш ответа
    сужен до клиентского: `Cache-Control: private, max-age=86400` +
    `Vary: X-Telegram-Init-Data` (персональный гейт: shared-кэш не должен
    отдавать разрешённую одному картинку другому в обход 403); байтовый
    RAM-кэш и его TTL не изменены.

Тесты — поведенческие: реальный `create_app` + `TestClient`, подписанный
initData (HMAC как у Telegram), стаб Bot API, стабы лора/кэша. Никаких
реальных вызовов Telegram.
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services import lore_runtime, web_runtime
from services.permissions import Permissions
from web.api import deps as deps_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_FOR_HMAC_VECTOR"

ADMIN_ID = 5885953495        # глобальный админ (роль admin/wildcard)
LOCAL_ID = 111111            # local_admin ТОЛЬКО чата A
USER_ID = 222222             # обычный юзер без грантов
CHAT_A = -1001000000001      # чат, доступный LOCAL_ID (грант)
CHAT_B = -1002000000002      # чужой для LOCAL_ID чат
PEER_A = 333333              # участник CHAT_A
PEER_B = 444444              # участник только CHAT_B
GRANT_ONLY = 777888          # админ CHAT_A по chat_admins, НЕ участник
                             # users_meta ни одного чата (ветка гранта)
JPEG = b"\xff\xd8\xff\xe0avatar-bytes"


# ── auth ───────────────────────────────────────────────────────────────────

def make_init_data(token: str, user_id: int) -> str:
    """Валидный initData по канону Telegram (HMAC-SHA256), как в Telegram."""
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "U",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc}"


def hdr(user_id: int) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(TEST_TOKEN, user_id)}


# ── стабы Bot API (реальных вызовов Telegram нет) ──────────────────────────

class FakeBot:
    """Bot API-стаб: фото есть у всех; `calls` — фактические обращения."""

    id = 100500

    def __init__(self):
        self.calls = []

    async def get_user_profile_photos(self, user_id, limit=1):
        self.calls.append(("get_user_profile_photos", user_id))
        return types.SimpleNamespace(
            photos=[[types.SimpleNamespace(file_id=f"photo-{user_id}")]])

    async def get_chat(self, chat_id):
        self.calls.append(("get_chat", chat_id))
        return types.SimpleNamespace(
            id=chat_id,
            photo=types.SimpleNamespace(big_file_id=f"big-{chat_id}"))

    async def get_file(self, file_id):
        self.calls.append(("get_file", file_id))
        return types.SimpleNamespace(file_path="photos/a.jpg")

    async def download_file(self, path, destination=None):
        destination.write(JPEG)
        return destination

    # обогащение /api/chat_lore — не в фокусе этого файла
    async def get_chat_member(self, chat_id, user_id):
        self.calls.append(("get_chat_member", chat_id, user_id))
        return types.SimpleNamespace(user=types.SimpleNamespace(username="u"))


# ── стабы данных лора / RBAC ───────────────────────────────────────────────

_ROLES = {
    "admin": {"permissions": {"wildcard": True}, "is_custom": False,
              "role_type": "global_admin"},
    "user": {"permissions": {}, "is_custom": False, "role_type": "user"},
    "local_admin": {"permissions": {"sections": ["limits", "chat_lore"],
                                    "actions": []},
                    "is_custom": False, "role_type": "local_admin"},
}


class _FakeConn:
    """chat_admins: {(chat_id, telegram_id): role_name} (PG-гранты)."""

    def __init__(self, admins):
        self.admins = admins

    async def fetchrow(self, sql, *args):
        assert "FROM chat_admins" in sql
        role = self.admins.get((args[0], args[1]))
        return {"role_name": role} if role is not None else None


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _FakePg:
    def __init__(self, conn):
        self.pool = _FakePool(conn)


class _FakeCache:
    """ConfigCache-стаб: глобальные роли + chat_admins-гранты (PG)."""

    is_initialized = True
    pg_available = True

    def __init__(self, roles: dict, chat_admins: dict):
        self._roles = roles
        self.pg = _FakePg(_FakeConn(chat_admins))

    async def init(self):
        pass

    def get_role(self, telegram_id):
        role = self._roles.get(telegram_id)
        return role.get("role_name") if role else None

    def get_permissions_by_telegram_id(self, telegram_id):
        role = self._roles.get(telegram_id)
        if role is None or "role_name" not in role:
            return None
        return Permissions.from_dict(
            _ROLES[role["role_name"]].get("permissions", {}))

    def get_permissions(self, role_name):
        role = _ROLES.get(role_name)
        return (Permissions.from_dict(role.get("permissions", {}))
                if role is not None else None)

    def roles(self):
        return dict(_ROLES)


class _FakeProfile:
    def __init__(self, chat_id):
        self.chat_id = chat_id


class _FakeLoreStore:
    """list_profiles/is_chat_admin — то, что читает гейт аватаров."""

    def __init__(self, chats, chat_admins):
        self._chats = list(chats)
        self._admins = dict(chat_admins)   # {(chat_id, tg_id): role}

    async def list_profiles(self):
        return [_FakeProfile(c) for c in self._chats]

    async def is_chat_admin(self, telegram_id, chat_id):
        return (int(chat_id), int(telegram_id)) in self._admins


class _FakeDb:
    """users_meta: {(chat_id, user_id)} — авторитетный список участников."""

    def __init__(self, members):
        self._members = set((int(c), int(u)) for c, u in members)

    def has(self, chat_id, user_id) -> bool:
        """Синхронная проверка для тестов изоляции ветвей гейта."""
        return (int(chat_id), int(user_id)) in self._members

    async def get_users_meta(self, chat_id, user_ids=None, limit=None):
        if user_ids is None:
            return [{"chat_id": chat_id, "user_id": u}
                    for (c, u) in self._members if c == int(chat_id)]
        return [{"chat_id": chat_id, "user_id": int(u)}
                for u in user_ids
                if (int(chat_id), int(u)) in self._members]


# ── фикстуры ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))


@pytest.fixture(autouse=True)
def _runtime():
    """Чистый web/lore runtime и кэши байтов на каждый тест."""
    from web.api import avatars
    web_runtime.reset_web_runtime()
    lore_runtime.reset_lore_runtime()
    for cache in (avatars._avatar_cache, avatars._chat_info_cache,
                  avatars._username_cache, avatars._user_photo_cache,
                  avatars._user_name_cache):
        cache.clear()
    yield
    web_runtime.reset_web_runtime()
    lore_runtime.reset_lore_runtime()
    for cache in (avatars._avatar_cache, avatars._chat_info_cache,
                  avatars._username_cache, avatars._user_photo_cache,
                  avatars._user_name_cache):
        cache.clear()


@pytest.fixture
def bot():
    """Bot API-стаб в web_runtime + запись фактических обращений."""
    fake = FakeBot()
    web_runtime.set_web_bot(fake)
    return fake


@pytest.fixture
def lore():
    """Лор: чаты A и B. GRANT_ONLY — админ чата A ТОЛЬКО через chat_admins
    (в users_meta ни одного чата его нет — изоляция ветки гранта);
    участники: PEER_A/USER_ID — чат A, PEER_B/LOCAL_ID — чат B."""
    store = _FakeLoreStore([CHAT_A, CHAT_B],
                           {(CHAT_A, GRANT_ONLY): "local_admin"})
    db = _FakeDb({(CHAT_A, PEER_A), (CHAT_A, USER_ID),
                  (CHAT_B, PEER_B), (CHAT_B, LOCAL_ID)})
    lore_runtime.set_lore_components(store=store, db=db)
    return types.SimpleNamespace(store=store, db=db)


@pytest.fixture
def client():
    """Реальное приложение: LOCAL_ID — local_admin ТОЛЬКО чата A."""
    cache = _FakeCache(
        roles={ADMIN_ID: {"role_name": "admin"},
               LOCAL_ID: {"role_name": "user"},
               USER_ID: {"role_name": "user"}},
        chat_admins={(CHAT_A, LOCAL_ID): "local_admin"},
    )
    return TestClient(create_app(cache))


# ═══ self ═══════════════════════════════════════════════════════════════════

class TestSelfAlwaysAllowed:
    def test_plain_user_gets_own_avatar(self, client, bot, lore):
        """Роль `user` без грантов: свой аватар — 200, форма ответа прежняя."""
        r = client.get(f"/api/avatar/user/{USER_ID}", headers=hdr(USER_ID))
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        assert r.content == JPEG
        assert r.headers["cache-control"] == "private, max-age=86400"
        assert r.headers["vary"].lower() == "x-telegram-init-data"

    def test_plain_user_self_ignores_broken_lore(self, client, bot):
        """Self работает даже без лора (нет store): правило self первое."""
        r = client.get(f"/api/avatar/user/{USER_ID}", headers=hdr(USER_ID))
        assert r.status_code == 200
        assert r.content == JPEG


# ═══ общий чат ══════════════════════════════════════════════════════════════

class TestSharedChatAllowed:
    def test_participant_of_accessible_chat(self, client, bot, lore):
        """LOCAL_ID (local_admin чата A) — аватар участника A."""
        r = client.get(f"/api/avatar/user/{PEER_A}", headers=hdr(LOCAL_ID))
        assert r.status_code == 200
        assert r.content == JPEG
        assert ("get_user_profile_photos", PEER_A) in bot.calls

    def test_chat_admin_grant_in_accessible_chat(self, client, bot, lore):
        """Грант chat_admins БЕЗ участия в users_meta: тест изолирует ветку
        is_chat_admin (иначе её удаление не было бы замечено)."""
        assert not lore.db.has(CHAT_A, GRANT_ONLY)
        assert not lore.db.has(CHAT_B, GRANT_ONLY)
        r = client.get(f"/api/avatar/user/{GRANT_ONLY}", headers=hdr(LOCAL_ID))
        assert r.status_code == 200
        assert r.content == JPEG

    def test_chat_avatar_of_accessible_chat(self, client, bot, lore):
        """kind=chat: аватар чата, к которому есть доступ."""
        r = client.get(f"/api/avatar/chat/{CHAT_A}", headers=hdr(LOCAL_ID))
        assert r.status_code == 200
        assert r.content == JPEG
        assert ("get_chat", CHAT_A) in bot.calls


# ═══ кэш ответа: персональный, shared-кэш не должен отдавать чужое ═════════

class TestResponseCacheScope:
    def test_authorized_response_is_private_and_varies_by_auth(self, client,
                                                              bot, lore):
        """`public` при персональном гейте позволял бы прокси/CDN отдать
        разрешённую одному юзеру картинку другому в обход 403. Контракт:
        private (кэш только у клиента) + Vary по механизму аутентификации;
        TTL не изменился (сутки)."""
        r = client.get(f"/api/avatar/user/{PEER_A}", headers=hdr(LOCAL_ID))
        assert r.status_code == 200
        assert r.headers["cache-control"] == "private, max-age=86400"
        assert "public" not in r.headers["cache-control"]
        assert r.headers["vary"].lower() == "x-telegram-init-data"

    def test_denied_response_carries_no_permissive_cache(self, client, bot,
                                                         lore):
        """403 не должен объявлять себя кэшируемым для посредников."""
        r = client.get(f"/api/avatar/user/{PEER_B}", headers=hdr(LOCAL_ID))
        assert r.status_code == 403
        assert "public" not in (r.headers.get("cache-control") or "")
        assert bot.calls == []


# ═══ чужие — отказ ══════════════════════════════════════════════════════════

class TestStrangerDenied:
    def test_stranger_user_denied_and_bot_not_called(self, client, bot, lore):
        """PEER_B — участник только ЧУЖОГО чата B: 403, Bot API не трогаем."""
        r = client.get(f"/api/avatar/user/{PEER_B}", headers=hdr(LOCAL_ID))
        assert r.status_code == 403
        assert r.json()["detail"] == "permission denied"
        assert bot.calls == [], "отказ не должен доходить до Bot API"

    def test_plain_user_cannot_fetch_other_user(self, client, bot, lore):
        """Роль `user` без грантов: чужой аватар — 403 (общего чата нет)."""
        r = client.get(f"/api/avatar/user/{PEER_A}", headers=hdr(USER_ID))
        assert r.status_code == 403
        assert bot.calls == []

    def test_chat_without_access_denied(self, client, bot, lore):
        r = client.get(f"/api/avatar/chat/{CHAT_B}", headers=hdr(LOCAL_ID))
        assert r.status_code == 403
        assert r.headers["content-type"].startswith("application/json")
        assert bot.calls == []

    def test_denial_does_not_poison_negative_cache(self, client, bot, lore):
        """403 не пишет негатив в кэш байтов: легальный просмотр — 200."""
        from web.api import avatars
        r = client.get(f"/api/avatar/user/{PEER_B}", headers=hdr(LOCAL_ID))
        assert r.status_code == 403
        assert ("user", PEER_B) not in avatars._avatar_cache
        # владелец (global admin) видит того же юзера — байты не «отравлены»
        ok = client.get(f"/api/avatar/user/{PEER_B}", headers=hdr(ADMIN_ID))
        assert ok.status_code == 200
        assert ok.content == JPEG

    def test_warmed_byte_cache_does_not_bypass_gate(self, client, bot, lore):
        """Опасное направление: админ ПРОГРЕЛ байтовый кэш чужого аватара —
        обычный юзер по тому же id обязан получить 403 (JSON), а не
        закэшированные байты: гейт стоит ДО кэша."""
        from web.api import avatars
        ok = client.get(f"/api/avatar/user/{PEER_B}", headers=hdr(ADMIN_ID))
        assert ok.status_code == 200
        assert ok.content == JPEG
        assert ("user", PEER_B) in avatars._avatar_cache, "кэш горячий"
        calls_before = len(bot.calls)
        denied = client.get(f"/api/avatar/user/{PEER_B}",
                            headers=hdr(LOCAL_ID))
        assert denied.status_code == 403
        assert denied.headers["content-type"].startswith("application/json")
        assert denied.json()["detail"] == "permission denied"
        assert denied.content != JPEG, "байты из кэша не отдаются"
        assert len(bot.calls) == calls_before, "Bot API не вызывается заново"

    def test_fail_closed_without_lore(self, client, bot):
        """Нет лора/данных участников → чужой аватар закрыт (не 500)."""
        r = client.get(f"/api/avatar/user/{PEER_A}", headers=hdr(LOCAL_ID))
        assert r.status_code == 403

    def test_dm_chat_of_other_user_denied(self, client, bot, lore):
        """kind=chat по чужому ЛС (положительный id) — 403: F-14, доступ к ЛС
        только владельцу (иначе `get_chat` вернул бы фото чужого профиля)."""
        other_dm = 555000
        assert other_dm != LOCAL_ID
        r = client.get(f"/api/avatar/chat/{other_dm}", headers=hdr(LOCAL_ID))
        assert r.status_code == 403
        assert bot.calls == []


# ═══ глобальный админ / аутентификация ══════════════════════════════════════

class TestGlobalAdminAndAuth:
    def test_global_admin_any_user_and_chat(self, client, bot, lore):
        assert client.get(f"/api/avatar/user/{PEER_B}",
                          headers=hdr(ADMIN_ID)).status_code == 200
        assert client.get(f"/api/avatar/chat/{CHAT_B}",
                          headers=hdr(ADMIN_ID)).status_code == 200

    def test_global_admin_works_without_lore(self, client, bot):
        """Владельцу лор-источник не нужен (short-circuit global admin)."""
        assert client.get(f"/api/avatar/user/{PEER_B}",
                          headers=hdr(ADMIN_ID)).status_code == 200

    def test_unauthenticated_is_401(self, client, bot, lore):
        assert client.get(f"/api/avatar/user/{USER_ID}").status_code == 401
        assert client.get(f"/api/avatar/chat/{CHAT_A}").status_code == 401
        assert bot.calls == []

    def test_invalid_signature_is_401(self, client, bot, lore):
        bad = make_init_data("999:WRONG_TOKEN", USER_ID)
        r = client.get(f"/api/avatar/user/{USER_ID}",
                       headers={"X-Telegram-Init-Data": bad})
        assert r.status_code == 401
