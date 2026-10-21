"""B10-R09 (D01) — поведенческий тест гонки concurrent UI edit/refresh/409
на настройках чата (dossier/settings-поверхность).

Остаток (prep-rfl-binding.md §PROBE-UI, agent-close §4): был только
клиентский guard (dossierSaving); поведенческого теста гонки с 409 не было.

Контракт (services/chat_params.py, Q4): ОДИН optimistic-токен на профиль —
updated_at chat_profiles; писатель, стартовавший со старым
`expected_updated_at`, получает ChatParamsConflict → API 409
{code:'conflict', current_updated_at}; клиент перечитывает актуальный
токен и его повторная запись проходит (edit → 409 → refresh → retry).

TEST-LIFECYCLE: REGRESSION owner=B10-R09
"""
import copy

import pytest

from services.chat_params import (
    ChatParamsConflict,
    ChatParamsCache,
    set_chat_params,
    set_chat_params_cache,
)

CHAT = -100700


class _FakeConn:
    """Минимальный PG-двойник chat_profiles (образец tests/test_chat_params.py):
    UPDATE ... WHERE updated_at = $3 — честный optimistic-гвард."""

    def __init__(self):
        self.profiles = {}
        self.notifies = []
        self._seq = 0

    def _ts(self):
        self._seq += 1
        return f"2026-10-21T10:00:{self._seq:02d}+00:00"

    async def fetchrow(self, sql, *args):
        if sql.startswith("SELECT"):
            row = self.profiles.get(args[0])
            return copy.deepcopy(row) if row else None
        if "UPDATE chat_profiles" in sql:
            chat_id = args[0]
            row = self.profiles.get(chat_id)
            if not row:
                return None
            if "AND updated_at = $3::timestamptz" in sql:
                expected = (args[2].isoformat()
                            if hasattr(args[2], "isoformat") else str(args[2]))
                if expected != row["updated_at"]:
                    return None          # optimistic-конфликт: 0 строк
            row["chat_params"] = __import__("json").loads(
                __import__("json").dumps(args[1]))
            row["updated_at"] = self._ts()
            return copy.deepcopy(row)
        return None

    async def execute(self, sql, *args):
        if "INSERT INTO chat_profiles" in sql:
            chat_id = args[0]
            if chat_id in self.profiles:
                return "INSERT 0 0"
            self.profiles[chat_id] = {
                "chat_id": chat_id,
                "updated_at": self._ts(),
                "chat_params": {},
                "gates_opt_in": False,
            }
            return "INSERT 0 1"
        if "INSERT INTO chat_lore_history" in sql:
            pass
        if "pg_notify" in sql:
            self.notifies.append(str(args[0]))
        return "UPDATE 1"

    def add_profile(self, chat_id, chat_params=None):
        self.profiles[chat_id] = {
            "chat_id": chat_id,
            "updated_at": self._ts(),
            "chat_params": chat_params or {},
            "gates_opt_in": False,
        }

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *exc):
                return False

        tx = _Tx()
        tx._conn = self
        return tx


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


class _FakePg:
    def __init__(self, conn):
        self.pool = _FakePool(conn)


@pytest.fixture(autouse=True)
def _cache(monkeypatch):
    conn = _FakeConn()
    pg = _FakePg(conn)
    monkeypatch.setattr("services.chat_params._chat_params_cache",
                        ChatParamsCache(pg))
    monkeypatch.setattr("services.chat_params._chat_write_locks", {})
    yield conn, pg
    monkeypatch.setattr("services.chat_params._chat_params_cache", None)


@pytest.mark.asyncio
async def test_concurrent_edit_race_409_then_refresh_retry(_cache):
    """Два UI-писателя стартуют с одного токена T1: первый коммитится
    (T2), второй получает 409 с АКТУАЛЬНЫМ токеном; после refresh (перечит)
    повторная запись второго проходит — гонка завершается без потери
    правки и без silent overwrite."""
    conn, pg = _cache
    conn.add_profile(CHAT)                          # профиль существует (T0)
    token_t0 = conn.profiles[CHAT]["updated_at"]

    # оба «UI-редактирования» прочитали один и тот же токен T0
    # (панель настроек/досье открыта в двух окнах)
    writer_a = set_chat_params(
        CHAT, {"overrides": {"limits.chat_cooldown_seconds": 20}},
        changed_by=7, pg=pg, expected_updated_at=token_t0)
    writer_b = set_chat_params(
        CHAT, {"overrides": {"limits.chat_cooldown_seconds": 99}},
        changed_by=8, pg=pg, expected_updated_at=token_t0)

    result_a = await writer_a                       # первый коммитится
    token_t2 = conn.profiles[CHAT]["updated_at"]
    assert token_t2 != token_t0
    with pytest.raises(ChatParamsConflict) as exc:  # второй — 409
        await writer_b
    # 409 несёт актуальный токен для refresh-клиента
    assert exc.value.current_updated_at == token_t2

    # refresh: клиент перечитал актуальный токен и повторил правку
    result_b = await set_chat_params(
        CHAT, {"overrides": {"limits.chat_cooldown_seconds": 99}},
        changed_by=8, pg=pg, expected_updated_at=token_t2)
    assert result_b["overrides"]["limits.chat_cooldown_seconds"] == 99
    assert conn.profiles[CHAT]["updated_at"] != token_t2
