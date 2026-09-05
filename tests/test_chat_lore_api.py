"""Раунд 7 (chat-lore-management-v2, T-783, H1.3) — тесты API /api/chat_lore.

TestClient + ConfigCache-стаб (как test_webapp_api) + фейковый ChatLoreStore
(в памяти) + мок-воркер через services.lore_runtime. Матрица Q6 (spec §3.8):
аноним 401; не-участник 403; глобальный admin — всё; moderator/custom с
секцией chat_lore — ТОЛЬКО свои chat_admins-строки; per-chat admin — свой
чат; remap/POST/DELETE admins — только глобальный admin. 409 optimistic;
cap 4000 → 422; generate auto_disabled → 409; history is_ai; 404 профиля.
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services import lore_runtime
from services.chat_lore_store import ChatLoreConflict
from services.config_cache import ConfigCache
from services.lore_cache import LoreProfile
from services.permissions import Permissions
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_FOR_LORE_API"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
USER_ID = 999999999
CHAT_MINE = -100111
CHAT_FOREIGN = -100222
CHAT_EMPTY = -100333


def make_init_data(user_id: int = ADMIN_ID) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkLore",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


_TS = "2026-09-06T10:00:00+00:00"
_NEXT_TS = {"v": 0}


def _next_ts() -> str:
    _NEXT_TS["v"] += 1
    return f"2026-09-06T10:00:0{_NEXT_TS['v'] % 10}+00:00"


def make_profile(chat_id: int, manual: str = "", auto: str = "",
                 auto_enabled: bool = True, is_active: bool = True) -> LoreProfile:
    return LoreProfile(
        chat_id=chat_id, manual_lore=manual, auto_lore=auto,
        auto_enabled=auto_enabled, auto_period_hours=24,
        auto_window_hours=24, is_active=is_active,
        last_auto_at=None, updated_at=_TS)


class FakeChatStore:
    """ChatLoreStore-заглушка (в памяти) для API-тестов."""

    def __init__(self):
        self.profiles = {
            CHAT_MINE: make_profile(CHAT_MINE, manual="мой чат мануал"),
            CHAT_FOREIGN: make_profile(
                CHAT_FOREIGN, manual="чужой чат", auto="авто-лор чужого"),
        }
        self.admin_rows: set[tuple[int, int]] = {(USER_ID, CHAT_MINE)}
        self._history_rows: list[dict] = []

    # ── чтение ──────────────────────────────────────────────────────────
    async def resolve_chat_id(self, chat_id: int) -> int:
        return chat_id

    async def get_profile(self, chat_id: int):
        return self.profiles.get(chat_id)

    async def list_profiles(self):
        return list(self.profiles.values())

    async def is_chat_admin(self, telegram_id: int, chat_id: int) -> bool:
        return (telegram_id, chat_id) in self.admin_rows

    async def list_chat_admins(self, chat_id: int) -> list[int]:
        return sorted(tg for tg, ch in self.admin_rows if ch == chat_id)

    # ── изменение (оптимистик-метки, как в ChatLoreStore) ──────────────
    async def set_manual(self, chat_id, text, changed_by=None,
                         expected_updated_at=None):
        profile = self.profiles.get(chat_id)
        if profile is None:
            raise ChatLoreConflict(chat_id, None)
        if expected_updated_at is not None \
                and expected_updated_at != profile.updated_at:
            raise ChatLoreConflict(chat_id, profile.updated_at)
        new = _next_ts()
        self.profiles[chat_id] = _replace(profile, manual_lore=text,
                                          updated_at=new)
        self._history(chat_id, "manual", changed_by, profile.manual_lore, text)
        return self.profiles[chat_id]

    async def update_settings(self, chat_id, *, auto_enabled=None,
                              auto_period_hours=None, auto_window_hours=None,
                              changed_by=None, expected_updated_at=None):
        profile = self.profiles.get(chat_id)
        if profile is None:
            raise ChatLoreConflict(chat_id, None)
        if expected_updated_at is not None \
                and expected_updated_at != profile.updated_at:
            raise ChatLoreConflict(chat_id, profile.updated_at)
        new = _replace(profile,
                       auto_enabled=profile.auto_enabled
                       if auto_enabled is None else auto_enabled,
                       auto_period_hours=profile.auto_period_hours
                       if auto_period_hours is None else auto_period_hours,
                       auto_window_hours=profile.auto_window_hours
                       if auto_window_hours is None else auto_window_hours,
                       updated_at=_next_ts())
        self.profiles[chat_id] = new
        return new

    async def clear_auto(self, chat_id, changed_by=None):
        profile = self.profiles.get(chat_id)
        if profile is None:
            raise ChatLoreConflict(chat_id, None)
        self._history(chat_id, "auto", changed_by, profile.auto_lore, "")
        self.profiles[chat_id] = _replace(
            profile, auto_lore="", last_auto_at=None, updated_at=_next_ts())
        return self.profiles[chat_id]

    async def migrate_profile(self, old_chat_id, new_chat_id,
                              changed_by=None) -> dict:
        old = self.profiles.pop(old_chat_id, None)
        if old is None:
            return {"moved": False, "merged": False}
        self.profiles[new_chat_id] = _replace(old, chat_id=new_chat_id,
                                              updated_at=_next_ts())
        self._history(old_chat_id, "remap", changed_by,
                      str(old_chat_id), str(new_chat_id))
        return {"moved": True, "merged": False}

    async def add_chat_admin(self, chat_id, telegram_id,
                             added_by=None) -> bool:
        key = (telegram_id, chat_id)
        if key in self.admin_rows:
            return False
        self.admin_rows.add(key)
        self._history(chat_id, "chat_admin", added_by, "", str(telegram_id))
        return True

    async def remove_chat_admin(self, chat_id, telegram_id) -> bool:
        key = (telegram_id, chat_id)
        if key not in self.admin_rows:
            return False
        self.admin_rows.discard(key)
        self._history(chat_id, "chat_admin", None, str(telegram_id), "")
        return True

    async def history(self, chat_id, limit=100):
        return [h for h in self._history_rows
                if h["chat_id"] == chat_id][:limit]

    def _history(self, chat_id, field, changed_by, old, new):
        self._history_rows.append({
            "id": len(self._history_rows) + 1, "chat_id": chat_id,
            "field": field, "changed_by": changed_by,
            "old_value": old, "new_value": new, "created_at": _next_ts(),
        })


def _replace(profile: LoreProfile, **kw) -> LoreProfile:
    data = profile.to_dict()
    data.update(kw)
    return LoreProfile(**data)


class FakeWorker:
    """Мок LoreWorker: настраиваемый результат + журнал вызовов."""

    def __init__(self, result=None):
        self.result = result or {"status": "ok", "changed": True}
        self.calls: list[tuple[int, bool]] = []

    async def generate_for_chat(self, chat_id, *, manual=False):
        self.calls.append((chat_id, manual))
        return dict(self.result)


class _FakeConn:
    def __init__(self, role_rows=(), admin_rows=()):
        self._role_rows = list(role_rows)
        self._admin_rows = list(admin_rows)

    async def execute(self, sql, *args):
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
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
        self.closed = False

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        self.closed = True


_ROLE_ROWS = [
    {"role_name": "admin", "permissions": {"wildcard": True},
     "is_custom": False},
    {"role_name": "moderator",
     "permissions": {"sections": ["limits", "chat_lore"]},
     "is_custom": False},
    {"role_name": "user", "permissions": {}, "is_custom": False},
]
_ADMIN_ROWS = [
    {"telegram_id": ADMIN_ID, "role_name": "admin",
     "added_by": None, "created_at": _TS},
    {"telegram_id": MODERATOR_ID, "role_name": "moderator",
     "added_by": ADMIN_ID, "created_at": _TS},
]


@pytest.fixture
def api_env(monkeypatch):
    """create_app + ConfigCache-стаб; store/worker через lore_runtime."""
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    conn = _FakeConn(_ROLE_ROWS, _ADMIN_ROWS)
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    store = FakeChatStore()
    worker = FakeWorker()
    lore_runtime.reset_lore_runtime()
    lore_runtime.set_lore_components(store=store, worker=worker)
    app = create_app(cache)
    client = TestClient(app)
    client.cache = cache
    yield types.SimpleNamespace(client=client, store=store, worker=worker,
                                cache=cache)
    lore_runtime.reset_lore_runtime()


# ── матрица доступов ────────────────────────────────────────────────────────

class TestAccess:
    def test_anonymous_401(self, api_env):
        assert api_env.client.get("/api/chat_lore/chats").status_code == 401
        assert api_env.client.get(
            f"/api/chat_lore/{CHAT_MINE}").status_code == 401

    def test_plain_user_without_row_403(self, api_env):
        resp = api_env.client.get(f"/api/chat_lore/{CHAT_FOREIGN}",
                                  headers=_hdr(USER_ID))
        assert resp.status_code == 403

    def test_plain_user_sees_only_own_chats(self, api_env):
        resp = api_env.client.get("/api/chat_lore/chats",
                                  headers=_hdr(USER_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert [item["chat_id"] for item in body] == [CHAT_MINE]

    def test_per_chat_admin_own_ok_foreign_403(self, api_env):
        assert api_env.client.get(f"/api/chat_lore/{CHAT_MINE}",
                                  headers=_hdr(USER_ID)).status_code == 200
        assert api_env.client.get(f"/api/chat_lore/{CHAT_FOREIGN}",
                                  headers=_hdr(USER_ID)).status_code == 403

    def test_moderator_section_without_row_403(self, api_env):
        assert api_env.client.get(f"/api/chat_lore/{CHAT_FOREIGN}",
                                  headers=_hdr(MODERATOR_ID)
                                  ).status_code == 403
        resp = api_env.client.get("/api/chat_lore/chats",
                                  headers=_hdr(MODERATOR_ID))
        assert resp.json() == []          # секция НЕ расширяет список (Q6)

    def test_moderator_section_with_row_ok(self, api_env):
        api_env.store.admin_rows.add((MODERATOR_ID, CHAT_MINE))
        assert api_env.client.get(f"/api/chat_lore/{CHAT_MINE}",
                                  headers=_hdr(MODERATOR_ID)
                                  ).status_code == 200
        resp = api_env.client.get("/api/chat_lore/chats",
                                  headers=_hdr(MODERATOR_ID))
        assert [i["chat_id"] for i in resp.json()] == [CHAT_MINE]

    def test_admin_sees_all_chats(self, api_env):
        resp = api_env.client.get("/api/chat_lore/chats",
                                  headers=_hdr(ADMIN_ID))
        body = resp.json()
        assert {i["chat_id"] for i in body} == {CHAT_MINE, CHAT_FOREIGN}
        mine = next(i for i in body if i["chat_id"] == CHAT_MINE)
        assert mine["has_manual"] is True
        assert mine["has_auto"] is False
        assert mine["auto_enabled"] is True
        assert mine["is_active"] is True
        assert "ман" in mine["manual_preview"]

    def test_profile_404(self, api_env):
        assert api_env.client.get(f"/api/chat_lore/{CHAT_EMPTY}",
                                  headers=_hdr(ADMIN_ID)).status_code == 404


# ── manual / settings / clear ───────────────────────────────────────────────

class TestManualAndSettings:
    def test_put_manual_ok_with_history(self, api_env):
        resp = api_env.client.put(
            f"/api/chat_lore/{CHAT_MINE}",
            json={"manual_lore": "новый ручной лор", "updated_at": _TS},
            headers=_hdr(USER_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["manual_lore"] == "новый ручной лор"
        rec = api_env.store._history_rows[-1]
        assert rec["field"] == "manual"
        assert rec["changed_by"] == USER_ID
        assert rec["old_value"] == "мой чат мануал"

    def test_put_manual_conflict_409(self, api_env):
        resp = api_env.client.put(
            f"/api/chat_lore/{CHAT_MINE}",
            json={"manual_lore": "x", "updated_at": "2020-01-01T00:00:00+00:00"},
            headers=_hdr(USER_ID))
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "conflict"
        assert detail["current_updated_at"] == _TS

    def test_put_manual_too_long_422(self, api_env):
        resp = api_env.client.put(
            f"/api/chat_lore/{CHAT_MINE}",
            json={"manual_lore": "д" * 4001, "updated_at": _TS},
            headers=_hdr(USER_ID))
        assert resp.status_code == 422

    def test_put_settings_ok(self, api_env):
        resp = api_env.client.put(
            f"/api/chat_lore/{CHAT_MINE}/settings",
            json={"auto_enabled": False, "auto_period_hours": 48,
                  "updated_at": _TS},
            headers=_hdr(USER_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["auto_enabled"] is False
        assert body["auto_period_hours"] == 48

    def test_put_settings_period_out_of_range_422(self, api_env):
        resp = api_env.client.put(
            f"/api/chat_lore/{CHAT_MINE}/settings",
            json={"auto_window_hours": 0, "updated_at": _TS},
            headers=_hdr(USER_ID))
        assert resp.status_code == 422
        resp = api_env.client.put(
            f"/api/chat_lore/{CHAT_MINE}/settings",
            json={"auto_period_hours": 721, "updated_at": _TS},
            headers=_hdr(USER_ID))
        assert resp.status_code == 422

    def test_put_settings_conflict_409(self, api_env):
        resp = api_env.client.put(
            f"/api/chat_lore/{CHAT_MINE}/settings",
            json={"auto_enabled": False, "updated_at": "старая метка"},
            headers=_hdr(USER_ID))
        assert resp.status_code == 409

    def test_clear_auto_ok(self, api_env):
        resp = api_env.client.post(
            f"/api/chat_lore/{CHAT_FOREIGN}/clear_auto",
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["auto_lore"] == ""
        rec = api_env.store._history_rows[-1]
        assert rec["field"] == "auto"
        assert rec["old_value"] == "авто-лор чужого"
        assert rec["new_value"] == ""


# ── generate ────────────────────────────────────────────────────────────────

class TestGenerate:
    def test_generate_auto_disabled_409(self, api_env):
        api_env.store.profiles[CHAT_MINE] = make_profile(
            CHAT_MINE, auto_enabled=False)
        resp = api_env.client.post(
            f"/api/chat_lore/{CHAT_MINE}/generate", headers=_hdr(USER_ID))
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "auto_disabled"
        assert api_env.worker.calls == []     # воркер НЕ вызван (токены целы)

    def test_generate_ok_invokes_manual(self, api_env):
        resp = api_env.client.post(
            f"/api/chat_lore/{CHAT_MINE}/generate", headers=_hdr(USER_ID))
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "changed": True}
        assert api_env.worker.calls == [(CHAT_MINE, True)]

    def test_generate_quiet_window_returns_skip(self, api_env):
        api_env.worker.result = {"status": "skipped", "reason": "quiet_window"}
        resp = api_env.client.post(
            f"/api/chat_lore/{CHAT_MINE}/generate", headers=_hdr(USER_ID))
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    def test_generate_llm_error_500(self, api_env):
        api_env.worker.result = {"status": "error", "reason": "llm_error"}
        resp = api_env.client.post(
            f"/api/chat_lore/{CHAT_MINE}/generate", headers=_hdr(USER_ID))
        assert resp.status_code == 500

    def test_generate_foreign_chat_403(self, api_env):
        resp = api_env.client.post(
            f"/api/chat_lore/{CHAT_FOREIGN}/generate", headers=_hdr(USER_ID))
        assert resp.status_code == 403


# ── remap (только глобальный admin) ────────────────────────────────────────

class TestRemap:
    def test_remap_per_chat_admin_403(self, api_env):
        resp = api_env.client.post(
            f"/api/chat_lore/{CHAT_MINE}/remap",
            json={"new_chat_id": -100999}, headers=_hdr(USER_ID))
        assert resp.status_code == 403

    def test_remap_moderator_403(self, api_env):
        api_env.store.admin_rows.add((MODERATOR_ID, CHAT_MINE))
        resp = api_env.client.post(
            f"/api/chat_lore/{CHAT_MINE}/remap",
            json={"new_chat_id": -100999}, headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_remap_admin_ok(self, api_env):
        resp = api_env.client.post(
            f"/api/chat_lore/{CHAT_MINE}/remap",
            json={"new_chat_id": -100999}, headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["moved"] is True
        assert body["profile"]["chat_id"] == -100999
        assert CHAT_MINE not in api_env.store.profiles

    def test_remap_same_id_422(self, api_env):
        resp = api_env.client.post(
            f"/api/chat_lore/{CHAT_MINE}/remap",
            json={"new_chat_id": CHAT_MINE}, headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_remap_missing_profile_404(self, api_env):
        resp = api_env.client.post(
            f"/api/chat_lore/{CHAT_EMPTY}/remap",
            json={"new_chat_id": -100999}, headers=_hdr(ADMIN_ID))
        assert resp.status_code == 404


# ── история ─────────────────────────────────────────────────────────────────

class TestHistory:
    def test_history_shape_and_is_ai(self, api_env):
        api_env.store._history(CHAT_MINE, "auto", None, "", "авто")
        api_env.store._history(CHAT_MINE, "manual", USER_ID, "", "ручно")
        resp = api_env.client.get(
            f"/api/chat_lore/{CHAT_MINE}/history", headers=_hdr(USER_ID))
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 2
        assert {r["field"] for r in rows} == {"auto", "manual"}
        by_field = {r["field"]: r for r in rows}
        assert by_field["auto"]["is_ai"] is True
        assert by_field["auto"]["changed_by"] is None
        assert by_field["manual"]["is_ai"] is False
        assert by_field["manual"]["changed_by"] == USER_ID
        assert by_field["manual"]["new_value"] == "ручно"

    def test_history_foreign_403(self, api_env):
        resp = api_env.client.get(
            f"/api/chat_lore/{CHAT_FOREIGN}/history", headers=_hdr(USER_ID))
        assert resp.status_code == 403


# ── admins CRUD (POST/DELETE — только глобальный admin) ───────────────────

class TestAdmins:
    def test_list_admins_own_chat(self, api_env):
        resp = api_env.client.get(
            f"/api/chat_lore/admins?chat_id={CHAT_MINE}", headers=_hdr(USER_ID))
        assert resp.status_code == 200
        assert resp.json() == [USER_ID]

    def test_list_admins_foreign_403(self, api_env):
        resp = api_env.client.get(
            f"/api/chat_lore/admins?chat_id={CHAT_FOREIGN}",
            headers=_hdr(USER_ID))
        assert resp.status_code == 403

    def test_add_admin_plain_user_403(self, api_env):
        resp = api_env.client.post(
            "/api/chat_lore/admins",
            json={"chat_id": CHAT_MINE, "telegram_id": 777},
            headers=_hdr(USER_ID))
        assert resp.status_code == 403

    def test_add_admin_moderator_403(self, api_env):
        resp = api_env.client.post(
            "/api/chat_lore/admins",
            json={"chat_id": CHAT_MINE, "telegram_id": 777},
            headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_add_remove_admin_global_admin_ok(self, api_env):
        resp = api_env.client.post(
            "/api/chat_lore/admins",
            json={"chat_id": CHAT_MINE, "telegram_id": 777},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json() == {"added": True}
        assert (777, CHAT_MINE) in api_env.store.admin_rows
        rec = api_env.store._history_rows[-1]
        assert rec["field"] == "chat_admin"
        assert rec["new_value"] == "777"

        resp = api_env.client.delete(
            f"/api/chat_lore/admins?chat_id={CHAT_MINE}&telegram_id=777",
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json() == {"removed": True}
        assert (777, CHAT_MINE) not in api_env.store.admin_rows

    def test_remove_admin_non_global_403(self, api_env):
        resp = api_env.client.delete(
            f"/api/chat_lore/admins?chat_id={CHAT_MINE}&telegram_id=777",
            headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403
