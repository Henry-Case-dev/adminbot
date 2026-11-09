"""MOD-ACL-UX-01 M2 — запись три-состояния (ТЗ §2.1/§2.4-3) без второго store.

Проверяется реальный путь записи `chat_params`:

* `POST /api/config` + `X-Chat-Id` с `mode="inherit"` СНИМАЕТ override чата —
  это и есть третье состояние «наследовать» (прежде записать его было нельзя:
  API умело только `true/false`);
* запись INHERIT не трогает другие чаты и не меняет глобальное значение;
* повторная запись INHERIT идемпотентна: состояние уже целевое → нет
  UPDATE/NOTIFY, optimistic-метка не сдвигается;
* `PUT /api/chat/{id}/gates` принимает `enabled="inherit"` (та же точка
  записи, домен `chat_params.gates`).
"""
import json
import types

import pytest

from services import chat_params, hot_config
from web.api import gates as gates_api
from web.api import routes as routes_api

CHAT_A = -100
CHAT_B = -200
KEY = "flags.chat_silent_ack_enabled"      # per_chat bool из каталога
KEY2 = "flags.dream_enabled"
NEW_TS = "2026-11-09T12:00:00+00:00"


class _Conn:
    """Fake-PG: строки chat_profiles + журнал SQL (аудит побочных записей)."""

    def __init__(self, store):
        self.store = store
        self.queries: list[tuple[str, tuple]] = []

    @staticmethod
    def _row(rec):
        return {"chat_id": rec["chat_id"], "updated_at": rec["updated_at"],
                "chat_params": json.dumps(rec["params"]),
                "gates_opt_in": rec.get("opt_in", False)}

    async def fetchrow(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        if "SELECT chat_id, updated_at, chat_params" in sql:
            rec = self.store.get(int(args[0]))
            return None if rec is None else self._row(rec)
        if "UPDATE chat_profiles SET chat_params" in sql:
            rec = self.store[int(args[0])]
            # Оптимистическая ветка (§10-3): UPDATE ... WHERE updated_at = $3
            # не находит строку при устаревшем токене — иначе конфликт было
            # бы невозможно проверить.
            if len(args) >= 3 and chat_params._iso(args[2]) != rec["updated_at"]:
                return None
            rec["params"] = json.loads(args[1])
            rec["updated_at"] = NEW_TS
            return self._row(rec)
        return None

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return "OK"

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Tx()

    # счётчики для утверждений
    def count(self, needle: str) -> int:
        return sum(1 for sql, _ in self.queries if needle in sql)


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _Pg:
    def __init__(self, conn):
        self.pool = _Pool(conn)


def _store():
    return {
        CHAT_A: {"chat_id": CHAT_A, "updated_at": "2026-11-09T10:00:00+00:00",
                 "params": {"overrides": {KEY: True, KEY2: False},
                            "gates": {"dream": True, "permsoc": False}}},
        CHAT_B: {"chat_id": CHAT_B, "updated_at": "2026-11-09T10:05:00+00:00",
                 "params": {"overrides": {KEY: False}, "gates": {}}},
    }


@pytest.fixture
def env(monkeypatch):
    store = _store()
    conn = _Conn(store)
    cache = types.SimpleNamespace(pg=_Pg(conn), pg_available=True)
    state = types.SimpleNamespace(cache=cache)
    request = types.SimpleNamespace(app=types.SimpleNamespace(state=state))
    user = types.SimpleNamespace(id=777)
    owner = types.SimpleNamespace(is_global_admin=True, role_chat=None,
                                 is_local_admin=False, is_dm_owner=False,
                                 rank=4)

    async def _access_for(*_a, **_kw):
        return owner

    async def _db_override_map(*_a, **_kw):
        return {}

    monkeypatch.setattr("services.roles.access_for", _access_for)
    monkeypatch.setattr("web.api.routes.access_srv.db_override_map",
                        _db_override_map)
    monkeypatch.setattr(hot_config, "get", lambda key, default=None: False)

    class _Cache:
        """Тот же store, что у fake-PG: кэш читает актуальные строки."""

        def __init__(self):
            self.invalidated: list[int] = []

        async def get_chat_params(self, chat_id):
            rec = store.get(int(chat_id))
            return json.loads(json.dumps(rec["params"])) if rec else {}

        async def get_chat_params_full(self, chat_id):
            rec = store.get(int(chat_id))
            if rec is None:
                return {}, None
            return (json.loads(json.dumps(rec["params"])),
                    rec["updated_at"])

        async def get_chat_params_checked(self, chat_id):
            return await self.get_chat_params(chat_id), True

        async def invalidate_chat(self, chat_id):
            self.invalidated.append(int(chat_id))

    cache_obj = _Cache()
    chat_params.set_chat_params_cache(cache_obj)
    yield types.SimpleNamespace(store=store, conn=conn, cache=cache,
                                request=request, user=user,
                                cache_invalidated=cache_obj.invalidated)
    chat_params.set_chat_params_cache(None)


def _payload(items, updated_at=None):
    return routes_api.ConfigUpdateRequest(items=items, updated_at=updated_at)


async def _post(env, items, updated_at=None):
    return await routes_api.post_config(
        env.request, _payload(items, updated_at), env.user, str(CHAT_A))


@pytest.mark.asyncio
async def test_inherit_removes_only_this_chat_override(env):
    """`mode="inherit"` снимает запись ТОЛЬКО этого чата; другие чаты и
    глобальный слой не меняются (§2.4-3)."""
    out = await _post(env, [routes_api.ConfigItemUpdate(key=KEY,
                                                        mode="inherit")])
    assert out["inherit"] == [KEY] and KEY in out["updated"]
    assert env.store[CHAT_A]["params"]["overrides"] == {KEY2: False}
    # второй чат и глобал не тронуты
    assert env.store[CHAT_B]["params"]["overrides"] == {KEY: False}
    assert env.conn.count("bot_settings") == 0
    # состояние чата — «наследовать», значение берётся из глобального слоя
    state = await chat_params.resolve_param_capability(CHAT_A, KEY,
                                                       root=env.store[CHAT_A]["params"])
    assert state.chat_state == chat_params.INHERIT
    assert state.source == "global" and state.desired is False


@pytest.mark.asyncio
async def test_inherit_is_idempotent(env):
    """Повторная запись INHERIT: состояние уже целевое → без UPDATE/NOTIFY и
    без сдвига optimistic-метки."""
    first = await _post(env, [routes_api.ConfigItemUpdate(key=KEY,
                                                          mode="inherit")])
    updates_after_first = env.conn.count("UPDATE chat_profiles SET chat_params")
    ts_after_first = env.store[CHAT_A]["updated_at"]
    notifies_after_first = env.conn.count("pg_notify")

    second = await _post(env, [routes_api.ConfigItemUpdate(key=KEY,
                                                           mode="inherit")])
    assert second["revalidated"] is True
    assert env.conn.count("UPDATE chat_profiles SET chat_params") == \
        updates_after_first
    assert env.conn.count("pg_notify") == notifies_after_first
    assert env.store[CHAT_A]["updated_at"] == ts_after_first
    assert env.store[CHAT_A]["params"]["overrides"] == {KEY2: False}
    assert first["updated_at"] == second["updated_at"]


@pytest.mark.asyncio
async def test_inherit_then_explicit_on_round_trip(env):
    """INHERIT → явный ON → снова INHERIT: значение пишется и снимается, а не
    «переключается» в противоположное (отсутствие записи ≠ false)."""
    await _post(env, [routes_api.ConfigItemUpdate(key=KEY, mode="inherit")])
    await _post(env, [
        routes_api.ConfigItemUpdate(key=KEY, value=True)])
    assert env.store[CHAT_A]["params"]["overrides"][KEY] is True
    on_state = await chat_params.resolve_param_capability(
        CHAT_A, KEY, root=env.store[CHAT_A]["params"])
    assert on_state.chat_state == chat_params.ON and on_state.desired is True

    await _post(env, [routes_api.ConfigItemUpdate(key=KEY, mode="inherit")])
    assert KEY not in env.store[CHAT_A]["params"]["overrides"]
    final = await chat_params.resolve_param_capability(
        CHAT_A, KEY, root=env.store[CHAT_A]["params"])
    assert final.chat_state == chat_params.INHERIT


@pytest.mark.asyncio
async def test_unknown_mode_is_rejected(env):
    with pytest.raises(Exception) as exc:
        await _post(env, [routes_api.ConfigItemUpdate(key=KEY,
                                                      mode="maybe")])
    assert getattr(exc.value, "status_code", None) == 422


@pytest.mark.asyncio
async def test_gates_put_accepts_inherit(env):
    """`PUT /api/chats/{id}/gates` `enabled="inherit"` снимает чатовый гейт:
    другие гейты чата и другие чаты не тронуты (§2.4-3)."""
    out = await gates_api.gates_put(
        CHAT_A, env.request,
        gates_api.GateBody(feature="dream", enabled="inherit"), env.user)
    assert out["chat_state"] == "inherit"
    assert out["enabled"] is None
    gates = env.store[CHAT_A]["params"]["gates"]
    assert "dream" not in gates and gates.get("permsoc") is False
    assert env.store[CHAT_B]["params"]["gates"] == {}
    state = await chat_params.resolve_gate_capability(
        CHAT_A, "dream", global_value=False,
        root=env.store[CHAT_A]["params"])
    assert state.chat_state == chat_params.INHERIT
    assert state.desired is False and state.source == "global"


@pytest.mark.asyncio
async def test_gates_put_invalid_state_rejected(env):
    with pytest.raises(Exception) as exc:
        await gates_api.gates_put(
            CHAT_A, env.request,
            gates_api.GateBody(feature="dream", enabled="banana"), env.user)
    assert getattr(exc.value, "status_code", None) == 422


# ── F: механика hot-config (updated_at / NOTIFY / инвалидация кэша) ─────────

@pytest.mark.asyncio
async def test_write_bumps_updated_at_notifies_and_invalidates(env):
    """Запись значения: optimistic-метка обновлена, PG NOTIFY отправлен,
    in-memory кэш чата инвалидирован — иначе hot-изменение не дошло бы до
    уже работающего процесса (§2.4-6)."""
    out = await _post(env, [routes_api.ConfigItemUpdate(key=KEY,
                                                        value=True)])
    assert env.conn.count("pg_notify") == 1
    assert env.store[CHAT_A]["updated_at"] == NEW_TS
    assert out["updated_at"] == NEW_TS
    assert CHAT_A in env.cache_invalidated


@pytest.mark.asyncio
async def test_notify_invalidates_cache_and_change_is_visible(env):
    """Payload канала `chat_params_updated` сбрасывает кэш: следующий резолв
    видит новое значение БЕЗ перезапуска."""
    before = await chat_params.resolve_param_capability(CHAT_A, KEY,
                                                        root={"overrides": {KEY: True}})
    assert before.desired is True
    await chat_params.invalidate_chat_from_notify(str(CHAT_A))
    assert CHAT_A in env.cache_invalidated
    after = await chat_params.resolve_param_capability(
        CHAT_A, KEY, root={"overrides": {}})
    assert after.desired is False and after.chat_state == chat_params.INHERIT


@pytest.mark.asyncio
async def test_stale_token_recovers_and_keeps_foreign_keys(env):
    """Устаревший optimistic-токен у настроек чата НЕ даёт 409: действует
    документированный P0-контракт (2.58.139) — один bounded-ретрай с merge
    поверх свежего root. Чужие ключи не теряются, целевое значение применяется.

    (Прежняя версия теста требовала 409 и противоречила этому контракту:
    строгий 409 на каждую конкурентную мета-запись и был production-багом,
    который ретрай исправляет. Для гейтов строгий путь остаётся отдельным.)
    """
    out = await _post(env, [routes_api.ConfigItemUpdate(key=KEY, value=False)],
                      updated_at="2020-01-01T00:00:00+00:00")
    assert out["updated"] == [KEY]
    assert env.store[CHAT_A]["params"]["overrides"][KEY] is False
    # посторонний ключ того же чата сохранён (merge поверх свежих данных)
    assert env.store[CHAT_A]["params"]["overrides"][KEY2] is False
    # и запись реально произошла: метка и NOTIFY
    assert env.store[CHAT_A]["updated_at"] == NEW_TS
    assert env.conn.count("pg_notify") >= 1


@pytest.mark.asyncio
async def test_inherit_survives_stale_token(env):
    """INHERIT + устаревший токен: снятие override не должно «возвращаться»
    из свежего root при ретрае (§2.4-3). Раньше merge `fresh.update(new)`
    воскрешал удалённый ключ — наследование молча не включалось."""
    out = await _post(env, [routes_api.ConfigItemUpdate(key=KEY,
                                                        mode="inherit")],
                      updated_at="2020-01-01T00:00:00+00:00")
    assert out["inherit"] == [KEY]
    assert KEY not in env.store[CHAT_A]["params"]["overrides"]
    state = await chat_params.resolve_param_capability(
        CHAT_A, KEY, root=env.store[CHAT_A]["params"])
    assert state.chat_state == chat_params.INHERIT
    assert state.source == "global"

