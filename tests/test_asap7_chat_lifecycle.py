"""ASAP 7 (Workstream F, F5) — C1–C9: chat lifecycle + fallback.

REGRESSION (P7-C-1): собственное вступление/выход бота доставляется как
update `my_chat_member`, а не `chat_member`; без хендлеров на
my_chat_member-observer профиль нового чата не создаётся → чат невидим в
/api/access/chats (chain audit-modules-chat-claims.md §3.1 п.5).
REGRESSION (P7-C-2): fallback-регистрация по первому сообщению группы
(outer-middleware, гейт CHAT_PROFILE_FALLBACK_ENABLED, backoff-память).
C9: group→supergroup migration — upsert/set_active нового профиля при
отсутствии. C6/C7: RBAC /api/access/chats не ослаблен (локальный админ не
видит чужие чаты; title failure → fallback `Чат <id>`, чат не скрыт).
C3/C8: UI-контракт (badge «неактивен», stale localStorage) — на РЕАЛЬНОМ
web/app.js через node-сниппеты (секция SECTION-ACCESS, F5).

TEST-LIFECYCLE: REGRESSION owner=ASAP7/F5
"""
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

import handlers.chat_lifecycle as lifecycle

BOT_ID = 12345
CHAT_ID = -1002661910336
APP_JS = Path(__file__).resolve().parents[1] / "web" / "app.js"
NODE = shutil.which("node")


class FakeStore:
    """In-memory двойник ChatLoreStore (контракт: upsert/set_active/
    ensure/get_profile/add_link/migrate_profile)."""

    def __init__(self, profiles=None):
        self.profiles = dict(profiles or {})   # chat_id -> {"is_active": bool}
        self.calls = []

    async def get_profile(self, chat_id):
        self.calls.append(("get_profile", chat_id))
        return self.profiles.get(chat_id)

    async def ensure_profile(self, chat_id):
        self.calls.append(("ensure_profile", chat_id))
        self.profiles.setdefault(chat_id, {"is_active": True})
        return self.profiles[chat_id]

    upsert_profile_on_join = ensure_profile

    async def set_active(self, chat_id, is_active):
        self.calls.append(("set_active", chat_id, is_active))
        if is_active:
            self.profiles.setdefault(chat_id, {"is_active": True})
        if chat_id in self.profiles:
            self.profiles[chat_id]["is_active"] = is_active

    async def add_link(self, old_chat_id, new_chat_id):
        self.calls.append(("add_link", old_chat_id, new_chat_id))

    async def migrate_profile(self, old_chat_id, new_chat_id,
                              changed_by=None):
        self.calls.append(("migrate_profile", old_chat_id, new_chat_id))
        prof = self.profiles.pop(old_chat_id, None)
        if prof is not None and new_chat_id not in self.profiles:
            self.profiles[new_chat_id] = prof
            return {"moved": True, "merged": False}
        return {"moved": False, "merged": False}


@pytest.fixture(autouse=True)
def _lifecycle_env():
    """Fake-store + bot_id + чистая backoff-память на каждый тест."""
    store = FakeStore()
    lifecycle.reset_fallback_memory()
    with patch.object(lifecycle, "_store", store), \
            patch.object(lifecycle, "_bot_id", BOT_ID), \
            patch.object(lifecycle, "ensure_gates_defaults",
                         AsyncMock()) as gates:
        yield SimpleNamespace(store=store, gates=gates)
    lifecycle.reset_fallback_memory()


def _make_event(user_id: int, old_status: str, new_status: str,
                chat_id: int = CHAT_ID):
    event = MagicMock()
    event.chat = MagicMock()
    event.chat.id = chat_id
    event.old_chat_member = MagicMock()
    event.old_chat_member.status = old_status
    event.old_chat_member.user = MagicMock()
    event.old_chat_member.user.id = user_id
    event.new_chat_member = MagicMock()
    event.new_chat_member.status = new_status
    event.new_chat_member.user = MagicMock()
    event.new_chat_member.user.id = user_id
    return event


def _make_update(chat_id: int | None):
    """Update с одним message-полем (как из polling); None → без message."""
    update = MagicMock()
    for attr in ("edited_message", "channel_post", "edited_channel_post"):
        setattr(update, attr, None)
    if chat_id is None:
        update.message = None
    else:
        update.message = MagicMock()
        update.message.chat = MagicMock()
        update.message.chat.id = chat_id
    return update


# ── C1 — bot added (my_chat_member join) ────────────────────────────────

class TestC1JoinMyChatMember:
    def test_my_chat_member_observer_has_join_leave_handlers(self):
        """P7-C-1 root cause: my_chat_member-observer НЕ пуст."""
        my = lifecycle.chat_lifecycle_router.my_chat_member
        names = [h.callback.__name__ for h in my.handlers]
        assert "on_bot_joined_my" in names
        assert "on_bot_left_my" in names
        # существующие chat_member-хендлеры сохранены (контракт архитектуры)
        cm = lifecycle.chat_lifecycle_router.chat_member
        cm_names = [h.callback.__name__ for h in cm.handlers]
        assert "on_bot_joined" in cm_names
        assert "on_bot_left" in cm_names

    @pytest.mark.asyncio
    async def test_my_join_creates_active_profile(self, _lifecycle_env):
        event = _make_event(BOT_ID, "left", "member")
        assert await lifecycle.on_bot_joined_my(event) is None
        store = _lifecycle_env.store
        assert CHAT_ID in store.profiles                  # профиль создан
        assert store.profiles[CHAT_ID]["is_active"] is True

    @pytest.mark.asyncio
    async def test_my_join_new_profile_writes_gates_defaults(
            self, _lifecycle_env):
        event = _make_event(BOT_ID, "left", "member")
        await lifecycle.on_bot_joined_my(event)
        _lifecycle_env.gates.assert_awaited_once_with(CHAT_ID)

    @pytest.mark.asyncio
    async def test_chat_member_join_still_works(self, _lifecycle_env):
        event = _make_event(BOT_ID, "left", "administrator")
        assert await lifecycle.on_bot_joined(event) is None
        assert _lifecycle_env.store.profiles[CHAT_ID]["is_active"] is True


# ── C2 — restart: профиль персистентен, виден в селекторе ───────────────

class TestC2RestartVisible:
    @pytest.mark.asyncio
    async def test_profile_survives_handler_restart(self, _lifecycle_env):
        await lifecycle.on_bot_joined_my(_make_event(BOT_ID, "left", "member"))
        persisted = dict(_lifecycle_env.store.profiles)   # «БД» пережила рестарт
        fresh = FakeStore(persisted)
        with patch.object(lifecycle, "_store", fresh), \
                patch.object(lifecycle, "_bot_id", BOT_ID):
            # «/api/access/chats» = SELECT chat_profiles; профиль на месте
            assert CHAT_ID in fresh.profiles
            assert fresh.profiles[CHAT_ID]["is_active"] is True
            # повторный join после рестарта — без дубля
            await lifecycle.on_bot_joined_my(
                _make_event(BOT_ID, "left", "member"))
        assert list(fresh.profiles) == [CHAT_ID]


# ── C3 — remove: is_active=false + badge «неактивен» ────────────────────

class TestC3LeaveBadge:
    @pytest.mark.asyncio
    async def test_my_leave_deactivates(self, _lifecycle_env):
        await lifecycle.on_bot_joined_my(_make_event(BOT_ID, "left", "member"))
        assert await lifecycle.on_bot_left_my(
            _make_event(BOT_ID, "member", "kicked")) is None
        assert _lifecycle_env.store.profiles[CHAT_ID]["is_active"] is False

    @pytest.mark.asyncio
    async def test_my_leave_other_user_unhandled(self, _lifecycle_env):
        assert await lifecycle.on_bot_left_my(
            _make_event(99999, "member", "left")) is UNHANDLED
        assert _lifecycle_env.store.profiles == {}

    @pytest.mark.skipif(NODE is None, reason="node недоступен")
    def test_inactive_chat_shown_with_badge_not_hidden(self, tmp_path):
        """Реальный scopeOptions (SECTION-ACCESS, в брифе «activeChatOptions»
        :4242-4265): inactive-чат в списке, badge «неактивен»; active/ЛС —
        прежние badge."""
        src = APP_JS.read_text(encoding="utf-8")
        ret = "return opts.concat(filt(chats), filt(dms));"
        start = src.index("scopeOptions: function")
        end = src.index(ret, start) + len(ret)
        snippet = src[start:end] + "\n}"
        script = (
            "var obj = { " + snippet + " };\n"
            "var ctx = { scopeSearch: '', isGlobalAdmin: true,\n"
            "  accessChats: [\n"
            "    { chat_id: -100123, title: 'Группа А', is_active: false,"
            " access: 'global_admin' },\n"
            "    { chat_id: -100456, title: 'Группа Б', is_active: true,"
            " access: 'global_admin' },\n"
            "    { chat_id: 555, title: 'Личные сообщения', is_dm: true,"
            " is_active: true, access: 'dm' }\n"
            "  ] };\n"
            "var out = obj.scopeOptions.call(ctx);\n"
            "console.log(JSON.stringify(out));\n")
        proc = subprocess.run([NODE, "-e", script], capture_output=True,
                              text=True, timeout=60, cwd=str(tmp_path))
        assert proc.returncode == 0, proc.stderr
        opts = json.loads(proc.stdout.strip().splitlines()[-1])
        inactive = [o for o in opts if o["chat_id"] == -100123]
        assert inactive and inactive[0]["badge"] == "неактивен"
        active = [o for o in opts if o["chat_id"] == -100456]
        assert active and active[0]["badge"] == ""
        dm = [o for o in opts if o["chat_id"] == 555]
        assert dm and dm[0]["badge"] == "ЛС"


# ── C4 — re-add: реактивация без дубля ──────────────────────────────────

class TestC4ReAdd:
    @pytest.mark.asyncio
    async def test_readd_reactivates_same_profile(self, _lifecycle_env):
        await lifecycle.on_bot_joined_my(_make_event(BOT_ID, "left", "member"))
        await lifecycle.on_bot_left_my(
            _make_event(BOT_ID, "member", "kicked"))
        assert _lifecycle_env.store.profiles[CHAT_ID]["is_active"] is False
        await lifecycle.on_bot_joined_my(_make_event(BOT_ID, "left", "member"))
        store = _lifecycle_env.store
        assert list(store.profiles) == [CHAT_ID]          # без дубля
        assert store.profiles[CHAT_ID]["is_active"] is True
        # гейт-дефолты НЕ переписываются при re-add (гейты уже записаны →
        # ensured только для новых; здесь профиль существовал при 2-м join)
        assert _lifecycle_env.gates.await_count == 1


# ── C5 — incoming-message fallback ──────────────────────────────────────

class TestC5FallbackRegistration:
    @pytest.mark.asyncio
    async def test_first_message_ensures_profile(self, _lifecycle_env):
        await lifecycle.maybe_ensure_group_profile(_make_update(-100777))
        store = _lifecycle_env.store
        assert -100777 in store.profiles
        assert store.profiles[-100777]["is_active"] is True
        _lifecycle_env.gates.assert_awaited_once_with(-100777)

    @pytest.mark.asyncio
    async def test_backoff_no_repeat_calls(self, _lifecycle_env):
        await lifecycle.maybe_ensure_group_profile(_make_update(-100777))
        ensure_calls = len([c for c in _lifecycle_env.store.calls
                            if c[0] == "ensure_profile"])
        for _ in range(5):
            await lifecycle.maybe_ensure_group_profile(_make_update(-100777))
        assert len([c for c in _lifecycle_env.store.calls
                    if c[0] == "ensure_profile"]) == ensure_calls

    @pytest.mark.asyncio
    async def test_known_profile_not_re_ensured(self, _lifecycle_env):
        _lifecycle_env.store.profiles[-100777] = {"is_active": True}
        await lifecycle.maybe_ensure_group_profile(_make_update(-100777))
        assert ("ensure_profile", -100777) not in _lifecycle_env.store.calls

    @pytest.mark.asyncio
    async def test_dm_and_non_message_skipped(self, _lifecycle_env):
        await lifecycle.maybe_ensure_group_profile(_make_update(555))
        await lifecycle.maybe_ensure_group_profile(_make_update(None))
        assert _lifecycle_env.store.calls == []

    @pytest.mark.asyncio
    async def test_gate_off_disables_fallback(self, _lifecycle_env):
        from config.settings import settings
        # Settings — frozen dataclass: kill-switch патчится на классе (ClassVar)
        with patch.object(settings.__class__,
                          "CHAT_PROFILE_FALLBACK_ENABLED", False):
            await lifecycle.maybe_ensure_group_profile(_make_update(-100777))
        assert _lifecycle_env.store.calls == []

    @pytest.mark.asyncio
    async def test_middleware_passes_handler_and_fail_open(self):
        handler = AsyncMock(return_value="handled")
        with patch.object(lifecycle, "_store", None):
            mw = lifecycle.ChatProfileFallbackMiddleware()
            result = await mw(handler, _make_update(-100777), {})
        assert result == "handled"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_error_fail_open(self, _lifecycle_env):
        async def _boom(chat_id):
            raise RuntimeError("pg down")
        _lifecycle_env.store.get_profile = _boom
        await lifecycle.maybe_ensure_group_profile(_make_update(-100777))
        # не бросили; backoff-память записана (не спамим PG на каждый msg)
        assert -100777 in lifecycle._fallback_last_try


# ── C6/C7 — RBAC /api/access/chats не ослаблен ──────────────────────────

class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, sql, *args):
        return self._rows


class _FakePool:
    def __init__(self, rows):
        self._rows = rows

    def acquire(self):
        rows = self._rows

        class _CM:
            async def __aenter__(self):
                return _FakeConn(rows)

            async def __aexit__(self, *exc):
                return False
        return _CM()


class TestC6C7RbacTitle:
    def _patch(self, monkeypatch, rows, info=None):
        from web.api import access as access_api
        from services import roles as roles_srv

        async def fake_access_for(user_id, cache=None):
            return SimpleNamespace(is_global_admin=False,
                                   is_local_admin=True, rank=20)
        monkeypatch.setattr(roles_srv, "access_for", fake_access_for)
        monkeypatch.setattr(access_api, "get_cache", lambda r: None)
        monkeypatch.setattr(access_api, "_pool", lambda cache: _FakePool(rows))
        if info is not None:
            monkeypatch.setattr(access_api, "chat_display_info", info)

    @pytest.mark.asyncio
    async def test_local_admin_does_not_see_foreign_chats(self, monkeypatch):
        from web.api import access as access_api
        rows = [
            {"chat_id": -100123, "chat_role": "local_admin", "is_active": True},
            {"chat_id": -100999, "chat_role": None, "is_active": True},
        ]
        self._patch(monkeypatch, rows,
                    info=lambda chat_id: {"title": f"T{chat_id}",
                                          "photo_file_id": None})
        res = await _call_endpoint(access_api.access_chats, user_id=777)
        ids = [c["chat_id"] for c in res]
        assert -100123 in ids            # грант локального админа
        assert -100999 not in ids        # чужой чат отфильтрован
        granted = [c for c in res if c["chat_id"] == -100123][0]
        assert granted["access"] == "local_admin"
        dm = [c for c in res if c.get("is_dm")]
        assert dm and dm[0]["chat_id"] == 777

    @pytest.mark.asyncio
    async def test_title_failure_falls_back_chat_stays(self, monkeypatch):
        from web.api import access as access_api

        def _boom(chat_id):
            raise RuntimeError("no cache")
        rows = [{"chat_id": -100123, "chat_role": "local_admin",
                 "is_active": True}]
        self._patch(monkeypatch, rows, info=_boom)
        res = await _call_endpoint(access_api.access_chats, user_id=777)
        row = [c for c in res if c["chat_id"] == -100123]
        assert row and row[0]["title"] == f"Чат {-100123}"


async def _call_endpoint(fn, user_id: int):
    """Вызов endpoint-функции напрямую (Depends-дефолты не участвуют)."""
    import inspect
    sig = inspect.signature(fn)
    kwargs = {}
    for name, param in sig.parameters.items():
        if name == "request":
            kwargs[name] = SimpleNamespace()
        elif name == "user":
            kwargs[name] = SimpleNamespace(id=user_id)
    return await fn(**kwargs)


# ── C8 — stale localStorage (реальный loadAccessCtx) ────────────────────

class TestC8StaleLocalStorage:
    @pytest.mark.skipif(NODE is None, reason="node недоступен")
    def test_stale_saved_id_cleared_app_not_broken(self, tmp_path):
        src = APP_JS.read_text(encoding="utf-8")
        start = src.index("loadAccessCtx: async function")
        end = src.index("syncActiveChatTitle: function", start)
        snippet = src[start:end].rstrip().rstrip(",")
        script = (
            "var removed = [];\n"
            "var mem = { 'adminbot.active_chat_id': '424242' };\n"
            "globalThis.localStorage = {\n"
            "  getItem: function (k) { return (k in mem) ? mem[k] : null; },\n"
            "  setItem: function (k, v) { mem[k] = String(v); },\n"
            "  removeItem: function (k) { removed.push(k); delete mem[k]; }\n"
            "};\n"
            "var obj = { api: async function (url) {\n"
            "  if (url === '/api/access/me')"
            " return { is_global_admin: true };\n"
            "  return [{ chat_id: -100123, title: 'Группа А',"
            " is_active: true }];\n"
            "}, " + snippet + " };\n"
            "var ctx = Object.create(obj);\n"
            "ctx.activeChatId = 424242;\n"
            "ctx.accessChats = [];\n"
            "ctx.accessMy = null;\n"
            "ctx.syncActiveChatTitle = function () {};\n"
            "obj.loadAccessCtx.call(ctx).then(function () {\n"
            "  console.log(JSON.stringify({ removed: removed,\n"
            "    activeChatId: ctx.activeChatId,\n"
            "    chats: ctx.accessChats.length }));\n"
            "}).catch(function (e) {\n"
            "  console.log(JSON.stringify({ error: String(e) }));\n"
            "});\n")
        proc = subprocess.run([NODE, "-e", script], capture_output=True,
                              text=True, timeout=60, cwd=str(tmp_path))
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        assert out.get("error") is None
        assert out["removed"] == ["adminbot.active_chat_id"]
        assert out["activeChatId"] is None
        assert out["chats"] == 1


# ── C9 — group→supergroup migration ─────────────────────────────────────

def _migrate_message(old_id=-100111, new_id=-100222):
    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = old_id
    msg.migrate_to_chat_id = new_id
    msg.message_id = 555
    return msg


class TestC9Migration:
    @pytest.mark.asyncio
    async def test_migrate_moves_profile_without_duplicate(
            self, _lifecycle_env):
        _lifecycle_env.store.profiles[-100111] = {"is_active": True}
        assert await lifecycle.on_chat_migrated(_migrate_message()) is None
        store = _lifecycle_env.store
        assert ("add_link", -100111, -100222) in store.calls
        assert list(store.profiles) == [-100222]          # один логический чат
        assert store.profiles[-100222]["is_active"] is True

    @pytest.mark.asyncio
    async def test_migrate_creates_profile_when_old_absent(
            self, _lifecycle_env):
        """Профиль old отсутствовал → migrate_profile no-op; новый чат всё
        равно регистрируется (иначе невидим в селекторе)."""
        assert await lifecycle.on_chat_migrated(_migrate_message()) is None
        store = _lifecycle_env.store
        assert ("add_link", -100111, -100222) in store.calls
        assert store.profiles.get(-100222, {}).get("is_active") is True
        _lifecycle_env.gates.assert_awaited_once_with(-100222)

    @pytest.mark.asyncio
    async def test_migrate_inactive_old_stays_inactive_on_move(
            self, _lifecycle_env):
        """Перенос сохраняет is_active old (не silent-реактивация); join/
        leave-события — единственный источник активности."""
        _lifecycle_env.store.profiles[-100111] = {"is_active": False}
        assert await lifecycle.on_chat_migrated(_migrate_message()) is None
        store = _lifecycle_env.store
        assert store.profiles[-100222]["is_active"] is False
        assert ("ensure_profile", -100222) not in store.calls
