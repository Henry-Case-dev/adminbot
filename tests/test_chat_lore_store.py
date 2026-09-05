"""Раунд 7 (chat-lore-management-v2, T-783/H1.1+H1.2) — тесты PG-слоя лора.

DDL (§3.2): идемпотентность повторного init (в test_pg_db — счётчики),
схема 4 таблиц (PK/CHECK/индексы/дефолты, включая last_auto_at) — проверка
текстов DDL_STATEMENTS. Store (T-772): транзакции «профиль+история+NOTIFY»
(сбой на середине → полный откат), по-полевая история, ChatLoreConflict с
актуальным updated_at, NOTIFY-эмит (payload=str(chat_id)), mark_auto_done без
истории, chat_links add/resolve (цепочки/циклы/глубина>5), chat_admins CRUD,
migrate_profile (чистый перенос + merge по Q9 + admins + история remap).

Пул — мок (реального PG в CI нет): `_FakePool`/`_FakeConn` с in-memory
состоянием таблиц (прецедент _FakePg/_FakePool из test_config_cache.py:78+),
транзакции с откатом (снимок состояния на входе в transaction()).
"""
import copy
import re
from datetime import datetime, timezone

import pytest

from services import pg_db as pg_mod
from services.chat_lore_store import (
    ChatLoreConflict,
    ChatLoreStore,
    _parse_ts,
)
from services.pg_db import DDL_STATEMENTS


# ── DDL-проверки (тексты констант) ─────────────────────────────────────────

def _joined_ddl() -> str:
    return " ".join(DDL_STATEMENTS)


def _ddl_for(table: str) -> str:
    return next(s for s in DDL_STATEMENTS if f"CREATE TABLE IF NOT EXISTS "
               f"{table}" in s)


class TestChatLoreDdl:
    @staticmethod
    def _has(sql: str, pattern: str) -> bool:
        """Поиск по DDL-тексту с учётом выравнивания (мульти-пробелы)."""
        return re.search(pattern, sql) is not None

    def test_four_new_tables_present_idempotent(self):
        ddl = _joined_ddl()
        for table in ("chat_profiles", "chat_lore_history", "chat_links",
                      "chat_admins"):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in ddl

    def test_chat_profiles_schema(self):
        sql = _ddl_for("chat_profiles")
        assert self._has(sql, r"chat_id\s+BIGINT PRIMARY KEY")
        assert self._has(sql, r"manual_lore\s+TEXT NOT NULL DEFAULT ''")
        assert self._has(sql, r"auto_lore\s+TEXT NOT NULL DEFAULT ''")
        assert self._has(sql,
                         r"auto_enabled\s+BOOLEAN NOT NULL DEFAULT TRUE")
        assert self._has(sql,
                         r"auto_period_hours\s+INTEGER NOT NULL DEFAULT 24")
        assert self._has(sql,
                         r"auto_window_hours\s+INTEGER NOT NULL DEFAULT 24")
        assert self._has(sql, r"is_active\s+BOOLEAN NOT NULL DEFAULT TRUE")
        assert self._has(sql, r"last_auto_at\s+TIMESTAMPTZ")    # D1/Q3
        assert self._has(
            sql, r"updated_at\s+TIMESTAMPTZ NOT NULL DEFAULT now\(\)")

    def test_chat_lore_history_schema_and_check(self):
        sql = _ddl_for("chat_lore_history")
        assert self._has(sql, r"id\s+BIGSERIAL PRIMARY KEY")
        assert self._has(sql, r"chat_id\s+BIGINT NOT NULL")
        assert self._has(sql, r"changed_by\s+BIGINT")
        for field in ("manual", "auto", "auto_enabled", "auto_period_hours",
                      "auto_window_hours", "remap", "chat_admin"):
            assert f"'{field}'" in sql                  # CHECK-энум (D2/Q7)
        assert self._has(sql, r"old_value\s+TEXT NOT NULL DEFAULT ''")
        assert self._has(sql, r"new_value\s+TEXT NOT NULL DEFAULT ''")
        assert "idx_chat_lore_history_chat_ts" in _joined_ddl()
        assert "created_at DESC" in _joined_ddl()

    def test_chat_links_and_admins_schema(self):
        ddl = _joined_ddl()
        links = _ddl_for("chat_links")
        assert self._has(links, r"old_chat_id\s+BIGINT PRIMARY KEY")
        assert self._has(links, r"new_chat_id\s+BIGINT NOT NULL")
        assert "idx_chat_links_new_chat" in ddl
        admins = _ddl_for("chat_admins")
        assert self._has(admins, r"chat_id\s+BIGINT NOT NULL")
        assert self._has(admins, r"telegram_id\s+BIGINT NOT NULL")
        assert "PRIMARY KEY (chat_id, telegram_id)" in admins
        assert self._has(admins, r"added_by\s+BIGINT")

    def test_no_fk_between_new_tables(self):
        """Стиль существующих таблиц: FK между новыми таблицами нет (§3.2)."""
        for table in ("chat_profiles", "chat_lore_history", "chat_links",
                      "chat_admins"):
            assert "REFERENCES" not in _ddl_for(table)


class TestStoreSqlContract:
    """Реальный asyncpg: fetchrow на UPDATE без RETURNING вернул бы None
    ВСЕГДА (фейки это скрывают) — все fetchrow-UPDATE обязаны иметь
    RETURNING *."""

    def test_fetchrow_updates_have_returning(self):
        from services import chat_lore_store as store_mod
        for name in ("SET_MANUAL_SQL", "SET_MANUAL_LOCKED_SQL",
                     "SET_AUTO_SQL", "CLEAR_AUTO_SQL", "MERGE_PROFILE_SQL"):
            assert "RETURNING *" in getattr(store_mod, name), name

    def test_prune_deletes_whole_old_chat(self):
        from services.chat_lore_store import PRUNE_ADMINS_SQL
        assert "chat_id = $1" in PRUNE_ADMINS_SQL
        assert "NOT IN" not in PRUNE_ADMINS_SQL


# ── In-memory фейк пула (микро-PG для store) ────────────────────────────────

_BASE_TS = "2026-09-06T10:{m:02d}:{s:02d}+00:00"


def _profile_row(chat_id: int, *, manual: str = "", auto: str = "",
                 enabled: bool = True, period: int = 24, window: int = 24,
                 active: bool = True, last_auto_at=None, updated_at=None,
                 now_fn=None):
    return {
        "chat_id": chat_id,
        "manual_lore": manual,
        "auto_lore": auto,
        "auto_enabled": enabled,
        "auto_period_hours": period,
        "auto_window_hours": window,
        "is_active": active,
        "last_auto_at": last_auto_at,
        "updated_at": updated_at if updated_at is not None
        else (now_fn() if now_fn else _ts()),
    }


class _FakeConn:
    """In-memory состояние chat_profiles/chat_lore_history/chat_links/
    chat_admins + журнал NOTIFY. execute/fetch/fetchrow разбирают SQL
    нашего store по shape (параметры $N → args[N-1]). transaction() со
    снимком состояния (откат при исключении). fail_on — подстрока SQL,
    при которой операция падает (тест атомарности)."""

    def __init__(self):
        self.profiles: dict[int, dict] = {}
        self.history: list[dict] = []
        self.links: dict[int, int] = {}
        self.admins: dict[tuple[int, int], dict] = {}
        self.notifies: list[str] = []
        self.queries: list[tuple[str, tuple]] = []
        self._seq = 0
        self._snapshots: list[dict] = []
        self.fail_on: str | None = None
        self.execute_result = "UPDATE 1"

    # ── утилиты состояния ──────────────────────────────────────────────────

    def _next_ts(self) -> str:
        self._seq += 1
        return _BASE_TS.format(m=self._seq // 60, s=self._seq % 60)

    def _snapshot(self) -> dict:
        return {
            "profiles": copy.deepcopy(self.profiles),
            "history": copy.deepcopy(self.history),
            "links": dict(self.links),
            "admins": copy.deepcopy(self.admins),
            "notifies": list(self.notifies),
            "seq": self._seq,
        }

    def _restore(self, snap: dict) -> None:
        for key, value in snap.items():
            setattr(self, key, copy.deepcopy(value))

    def _maybe_fail(self, sql: str) -> None:
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("boom (fake rollback test)")

    # ── транзакции ─────────────────────────────────────────────────────────

    def transaction(self):
        self._snapshots.append(self._snapshot())

        class _Tx:
            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, exc_type, exc, tb):
                self._conn._maybe_rollback(exc is not None)

        tx = _Tx()
        tx._conn = self
        return tx

    def _maybe_rollback(self, failed: bool) -> None:
        if self._snapshots:
            snap = self._snapshots.pop()
            if failed:
                self._restore(snap)

    # ── применение операций ────────────────────────────────────────────────

    def _apply(self, sql: str, args: tuple, *, return_row: bool):
        """Общий исполнитель UPDATE/INSERT/DELETE/SELECT chat_profiles и пр.
        Возврат: (tag, row|None). SQL нашего store — строчными буквами,
        матчим по сырому тексту."""
        if "pg_notify" in sql:                        # SELECT pg_notify(...)
            self.notifies.append(str(args[0]))
            return "SELECT 1", None
        if sql.startswith("SELECT"):
            row = self._select(sql, args)
            return None, row
        if "INSERT INTO chat_profiles" in sql and "VALUES ($1)" in sql:
            chat_id = args[0]
            if chat_id in self.profiles:
                return "INSERT 0 0", None
            self.profiles[chat_id] = _profile_row(chat_id,
                                                  updated_at=self._next_ts())
            return "INSERT 0 1", None
        if "INSERT INTO chat_profiles" in sql:        # сид (manual_lore и пр.)
            chat_id, manual = args[0], args[1]
            if chat_id in self.profiles:
                return "INSERT 0 0", None
            self.profiles[chat_id] = _profile_row(
                chat_id, manual=manual or "", updated_at=self._next_ts())
            return "INSERT 0 1", None
        if "INSERT INTO chat_lore_history" in sql:
            self._seq += 1
            row = {
                "id": self._seq,
                "chat_id": args[0], "field": args[1], "changed_by": args[2],
                "old_value": args[3] or "", "new_value": args[4] or "",
                "created_at": _ts(),
            }
            self.history.append(row)
            return "INSERT 0 1", None
        if "INSERT INTO chat_links" in sql:
            self.links[args[0]] = args[1]
            return "INSERT 0 1", None
        if "INSERT INTO chat_admins" in sql:
            if "SELECT" in sql:                       # COPY_ADMINS (merge)
                new_id, old_id = args[0], args[1]
                for key, row in list(self.admins.items()):
                    if key[0] == old_id:
                        self.admins.setdefault(
                            (new_id, key[1]),
                            dict(row, chat_id=new_id))
                return "INSERT 0 1", None
            key = (args[0], args[1])
            if key in self.admins:
                return "INSERT 0 0", None
            self.admins[key] = {"chat_id": args[0], "telegram_id": args[1],
                                "added_by": args[2]}
            return "INSERT 0 1", None
        if sql.startswith("UPDATE chat_profiles"):
            row, ok = self._update_profile(sql, args)
            if not ok or row is None:
                return "UPDATE 0", None
            return "UPDATE 1", row
        if sql.startswith("DELETE FROM chat_profiles"):
            self.profiles.pop(args[0], None)
            return "DELETE 1", None
        if sql.startswith("DELETE FROM chat_admins"):
            if len(args) == 1:                # PRUNE_ADMINS (merge): все old
                for key in list(self.admins):
                    if key[0] == args[0]:
                        del self.admins[key]
                return "DELETE 1", None
            key = (args[0], args[1])
            if key in self.admins:
                del self.admins[key]
                return "DELETE 1", None
            return "DELETE 0", None
        if sql.startswith("UPDATE chat_admins"):      # MOVE_ADMINS
            new_id, old_id = args[0], args[1]
            for key in list(self.admins):
                if key[0] == old_id:
                    row = self.admins.pop(key)
                    self.admins[(new_id, key[1])] = row
            return "UPDATE 1", None
        return self.execute_result, None

    def _select(self, sql: str, args: tuple):
        if "FROM chat_links" in sql:
            nxt = self.links.get(args[0])
            return {"new_chat_id": nxt} if nxt is not None else None
        if "FROM chat_admins" in sql:                 # SELECT 1 ... LIMIT 1
            return {"found": 1} if (args[0], args[1]) in self.admins else None
        if "FROM chat_profiles" in sql and "WHERE chat_id" in sql:
            row = self.profiles.get(args[0])
            return copy.deepcopy(row) if row is not None else None
        return None

    def _update_profile(self, sql: str, args: tuple):
        """UPDATE chat_profiles (manual/auto/settings/move/merge) → (row, ok)."""
        m = re.search(r"WHERE chat_id = \$(\d+)", sql)
        if not m:
            return None, False
        chat_id = args[int(m.group(1)) - 1]
        row = self.profiles.get(chat_id)
        if row is None:
            return None, False
        lock = re.search(r"AND updated_at = \$(\d+)::timestamptz", sql)
        if lock and _ts_norm(args[int(lock.group(1)) - 1]) != \
                _ts_norm(row["updated_at"]):
            return None, False
        if "SET chat_id = $1" in sql:                 # MOVE (чистый перенос)
            new_id = args[0]
            moved = dict(row, chat_id=new_id, updated_at=self._next_ts())
            del self.profiles[chat_id]
            self.profiles[new_id] = moved
            return moved, True
        mset = re.search(r"SET (.*?) WHERE", sql)
        assignments = [t.strip() for t in mset.group(1).split(",")
                       if t.strip()]
        for token in assignments:
            am = re.match(r"(\w+) = (.*)$", token)
            if not am:
                continue
            field, raw = am.group(1), am.group(2)
            if raw == "now()":
                row[field] = self._next_ts()
            elif raw.startswith("$"):
                arg_index = int(re.match(r"\$(\d+)", raw).group(1)) - 1
                value = args[arg_index]
                if isinstance(value, datetime):         # $8::timestamptz
                    value = value.isoformat()
                row[field] = "" if value is None and field in (
                    "manual_lore", "auto_lore") else value
            elif raw == "NULL":
                row[field] = None
            else:
                row[field] = raw.strip("'")
        row["updated_at"] = self._next_ts()
        return row, True

    # ── asyncpg-интерфейс ──────────────────────────────────────────────────

    async def execute(self, sql: str, *args):
        self.queries.append((sql, tuple(args)))
        self._maybe_fail(sql)
        tag, _row = self._apply(sql, args, return_row=False)
        return tag

    async def fetchrow(self, sql: str, *args):
        self.queries.append((sql, tuple(args)))
        self._maybe_fail(sql)
        _tag, row = self._apply(sql, args, return_row=True)
        return row

    async def fetch(self, sql: str, *args):
        self.queries.append((sql, tuple(args)))
        self._maybe_fail(sql)
        if "FROM chat_lore_history" in sql:
            limit = args[1]
            rows = [r for r in self.history if r["chat_id"] == args[0]]
            rows.sort(key=lambda r: (r["created_at"], r["id"]),
                      reverse=True)
            return rows[:limit]
        if "FROM chat_profiles" in sql:
            rows = list(self.profiles.values())
            if "WHERE is_active" in sql:
                rows = [r for r in rows if r["is_active"]]
            if "WHERE is_active AND auto_enabled" in sql:
                rows = [r for r in rows
                        if r["is_active"] and r["auto_enabled"]]
            if "SELECT chat_id FROM" in sql:
                rows.sort(key=lambda r: r["chat_id"])
                return [{"chat_id": r["chat_id"]} for r in rows]
            rows.sort(key=lambda r: r["chat_id"])
            return rows
        if "FROM chat_admins" in sql:
            rows = [r for key, r in self.admins.items()
                    if key[0] == args[0]]
            rows.sort(key=lambda r: r["telegram_id"])
            return rows
        return []


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn
        self.closed = False

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
        self.closed = True


class _FakePg:
    def __init__(self, pool=None):
        self.pool = pool


def _ts() -> str:
    return "2026-09-06T10:00:00+00:00"


def _ts_norm(value):
    """Метка к datetime-сравнению: фейк хранит ISO-строки, а store (после
    _parse_ts) шлёт datetime — сравнение как в реальном PG (timestamptz)."""
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)


def make_store(conn: _FakeConn) -> ChatLoreStore:
    return ChatLoreStore(_FakePg(pool=_FakePool(conn)))


@pytest.fixture
def store():
    return make_store(_FakeConn())


@pytest.fixture
def conn_store():
    conn = _FakeConn()
    return conn, make_store(conn)


# ── _parse_ts: ISO-строка клиента → datetime (asyncpg $N::timestamptz) ──────

class TestParseTs:
    """Прод-фикс: asyncpg не принимает str для ::timestamptz (DataError →
    500); фронт шлёт ISO-строки → store обязан конвертировать в datetime."""

    def test_iso_with_offset_returns_datetime(self):
        dt = _parse_ts("2026-09-05T16:30:51.034356+00:00")
        assert isinstance(dt, datetime)
        assert dt == datetime(2026, 9, 5, 16, 30, 51, 34356,
                              tzinfo=timezone.utc)

    def test_iso_with_z_returns_datetime(self):
        dt = _parse_ts("2026-09-05T16:30:51Z")
        assert isinstance(dt, datetime)
        assert dt == datetime(2026, 9, 5, 16, 30, 51, tzinfo=timezone.utc)

    def test_none_and_non_string_passthrough(self):
        assert _parse_ts(None) is None
        src = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        assert _parse_ts(src) is src

    def test_garbage_raises_value_error(self):
        with pytest.raises(ValueError, match="invalid updated_at timestamp"):
            _parse_ts("не-ISO-мусор")


# ── CRUD профиля ────────────────────────────────────────────────────────────

class TestProfileCrud:
    @pytest.mark.asyncio
    async def test_get_profile_none_and_defaults(self, conn_store):
        conn, store = conn_store
        assert await store.get_profile(-1001) is None
        profile = await store.ensure_profile(-1001)
        assert profile.chat_id == -1001
        assert profile.manual_lore == ""
        assert profile.auto_lore == ""
        assert profile.auto_enabled is True
        assert profile.auto_period_hours == 24
        assert profile.auto_window_hours == 24
        assert profile.is_active is True
        assert profile.last_auto_at is None
        assert profile.updated_at
        again = await store.get_profile(-1001)
        assert again == profile
        assert len(conn.profiles) == 1

    @pytest.mark.asyncio
    async def test_ensure_idempotent(self, store):
        p1 = await store.ensure_profile(42)
        p2 = await store.ensure_profile(42)
        assert p1 == p2
        assert len(await store.list_profiles()) == 1

    @pytest.mark.asyncio
    async def test_list_profiles_and_active_chats(self, conn_store):
        conn, store = conn_store
        conn.profiles[1] = _profile_row(1, active=True, enabled=True)
        conn.profiles[2] = _profile_row(2, active=False, enabled=True)
        conn.profiles[3] = _profile_row(3, active=True, enabled=False)
        assert [p.chat_id for p in await store.list_profiles()] == [1, 2, 3]
        assert [p.chat_id for p in
                await store.list_profiles(active_only=True)] == [1, 3]
        assert await store.list_active_chats() == [1]

    @pytest.mark.asyncio
    async def test_upsert_profile_on_join_alias(self, store):
        p = await store.upsert_profile_on_join(-77)
        assert p.chat_id == -77 and p.is_active


# ── set_manual / optimistic-конфликт / история / NOTIFY ─────────────────────

class TestManualUpdate:
    @pytest.mark.asyncio
    async def test_set_manual_ok_history_and_notify(self, conn_store):
        conn, store = conn_store
        await store.ensure_profile(7)
        profile = await store.set_manual(7, "Новый ручной лор", changed_by=111)
        assert profile.manual_lore == "Новый ручной лор"
        assert conn.notifies == ["7"]
        rec = conn.history[-1]
        assert rec["field"] == "manual"
        assert rec["changed_by"] == 111
        assert rec["old_value"] == ""
        assert rec["new_value"] == "Новый ручной лор"

    @pytest.mark.asyncio
    async def test_set_manual_does_not_touch_auto(self, conn_store):
        conn, store = conn_store
        conn.profiles[7] = _profile_row(7, auto="авто-лор",
                                        last_auto_at=_ts())
        await store.set_manual(7, "manual", changed_by=111)
        row = conn.profiles[7]
        assert row["auto_lore"] == "авто-лор"
        assert row["last_auto_at"] == _ts()

    @pytest.mark.asyncio
    async def test_set_manual_optimistic_conflict(self, conn_store):
        conn, store = conn_store
        p = await store.ensure_profile(7)
        # параллельная правка двигает updated_at
        await store.set_manual(7, "правка конкурента", changed_by=222)
        with pytest.raises(ChatLoreConflict) as ei:
            await store.set_manual(7, "моя правка", changed_by=111,
                                   expected_updated_at=p.updated_at)
        assert ei.value.chat_id == 7
        assert ei.value.current_updated_at == conn.profiles[7]["updated_at"]
        # строка не изменилась, истории/нотификаций от неудавшейся нет
        assert conn.profiles[7]["manual_lore"] == "правка конкурента"
        assert [h["field"] for h in conn.history] == ["manual"]
        assert conn.notifies == ["7"]

    @pytest.mark.asyncio
    async def test_set_manual_missing_profile_conflict(self, store):
        with pytest.raises(ChatLoreConflict) as ei:
            await store.set_manual(99, "текст", changed_by=1,
                                   expected_updated_at="x")
        assert ei.value.chat_id == 99
        assert ei.value.current_updated_at is None

    @pytest.mark.asyncio
    async def test_atomicity_rollback_on_history_failure(self, conn_store):
        """Сбой на середине транзакции → полный откат: ни апдейта, ни
        истории, ни NOTIFY (инвариант §1.3-4)."""
        conn, store = conn_store
        await store.ensure_profile(7)
        conn.fail_on = "INSERT INTO chat_lore_history"
        with pytest.raises(RuntimeError):
            await store.set_manual(7, "текст", changed_by=1)
        assert conn.profiles[7]["manual_lore"] == ""
        assert conn.history == []
        assert conn.notifies == []

    @pytest.mark.asyncio
    async def test_update_manual_alias(self, store):
        await store.ensure_profile(7)
        p = await store.update_manual(7, "алиас-правка", changed_by=1)
        assert p.manual_lore == "алиас-правка"

    @pytest.mark.asyncio
    async def test_set_manual_iso_expected_passes_datetime_to_sql(self,
                                                                  conn_store):
        """ISO-строка expected_updated_at → в asyncpg $3::timestamptz уходит
        datetime (продакшен-фикс: str-параметр = DataError → HTTP 500)."""
        conn, store = conn_store
        p = await store.ensure_profile(7)
        assert p.updated_at == "2026-09-06T10:00:01+00:00"
        await store.set_manual(
            7, "правка", changed_by=111,
            expected_updated_at="2026-09-06T10:00:01+00:00")
        locked = [q[1] for q in conn.queries
                  if "AND updated_at = $3::timestamptz" in q[0]]
        assert len(locked) == 1
        assert locked[0][0] == 7 and locked[0][1] == "правка"
        assert isinstance(locked[0][2], datetime)
        assert locked[0][2] == _ts_norm("2026-09-06T10:00:01+00:00")
        assert conn.profiles[7]["manual_lore"] == "правка"


# ── set_auto / mark_auto_done / clear_auto ──────────────────────────────────

class TestAutoUpdate:
    @pytest.mark.asyncio
    async def test_set_auto_writes_history_null_changed_by(self, conn_store):
        conn, store = conn_store
        conn.profiles[7] = _profile_row(7)
        p = await store.set_auto(7, "выжимка")
        assert p.auto_lore == "выжимка"
        assert p.last_auto_at is not None          # метка успешного прогона
        assert conn.notifies == ["7"]
        rec = conn.history[-1]
        assert rec["field"] == "auto"
        assert rec["changed_by"] is None
        assert rec["old_value"] == ""
        assert rec["new_value"] == "выжимка"

    @pytest.mark.asyncio
    async def test_set_auto_record_history_false(self, conn_store):
        conn, store = conn_store
        conn.profiles[7] = _profile_row(7, auto="старое")
        await store.set_auto(7, "новое", record_history=False)
        assert conn.history == []
        assert conn.profiles[7]["auto_lore"] == "новое"

    @pytest.mark.asyncio
    async def test_mark_auto_done_no_history(self, conn_store):
        conn, store = conn_store
        conn.profiles[7] = _profile_row(7, auto="UNCHANGED-путь",
                                        last_auto_at=None)
        await store.mark_auto_done(7)
        assert conn.profiles[7]["last_auto_at"] is not None
        assert conn.history == []
        assert conn.notifies == ["7"]

    @pytest.mark.asyncio
    async def test_clear_auto_history_and_null_metka(self, conn_store):
        conn, store = conn_store
        conn.profiles[7] = _profile_row(7, auto="старый авто",
                                        last_auto_at=_ts())
        p = await store.clear_auto(7, changed_by=333)
        assert p.auto_lore == ""
        assert p.last_auto_at is None
        rec = conn.history[-1]
        assert rec["field"] == "auto"
        assert rec["old_value"] == "старый авто"
        assert rec["new_value"] == ""
        assert rec["changed_by"] == 333
        assert conn.notifies == ["7"]

    @pytest.mark.asyncio
    async def test_clear_auto_missing_profile(self, store):
        with pytest.raises(ChatLoreConflict):
            await store.clear_auto(5)


# ── update_settings: частичное обновление, по-полевая история ───────────────

class TestUpdateSettings:
    @pytest.mark.asyncio
    async def test_single_field_history(self, conn_store):
        conn, store = conn_store
        p = await store.ensure_profile(7)
        new = await store.update_settings(
            7, auto_period_hours=48, changed_by=111,
            expected_updated_at=p.updated_at)
        assert new.auto_period_hours == 48
        assert new.auto_enabled is True
        assert conn.notifies == ["7"]
        rec = conn.history[-1]
        assert rec["field"] == "auto_period_hours"
        assert rec["old_value"] == "24"
        assert rec["new_value"] == "48"
        assert rec["changed_by"] == 111

    @pytest.mark.asyncio
    async def test_multi_field_per_field_history(self, conn_store):
        conn, store = conn_store
        p = await store.ensure_profile(7)
        await store.update_settings(
            7, auto_enabled=False, auto_period_hours=12,
            auto_window_hours=6, changed_by=222,
            expected_updated_at=p.updated_at)
        fields = {h["field"] for h in conn.history}
        assert fields == {"auto_enabled", "auto_period_hours",
                          "auto_window_hours"}
        by_field = {h["field"]: h for h in conn.history}
        assert by_field["auto_enabled"]["old_value"] == "True"
        assert by_field["auto_enabled"]["new_value"] == "False"
        assert by_field["auto_window_hours"]["old_value"] == "24"
        assert by_field["auto_window_hours"]["new_value"] == "6"

    @pytest.mark.asyncio
    async def test_no_changes_no_history_no_notify_no_update(self, conn_store):
        conn, store = conn_store
        p = await store.ensure_profile(7)
        before = conn.profiles[7]["updated_at"]
        result = await store.update_settings(
            7, auto_enabled=True, auto_period_hours=24,
            auto_window_hours=24, changed_by=111,
            expected_updated_at=p.updated_at)
        assert result == p
        assert conn.history == []
        assert conn.notifies == []
        assert conn.profiles[7]["updated_at"] == before   # UPDATE не было

    @pytest.mark.asyncio
    async def test_none_fields_ignored(self, conn_store):
        conn, store = conn_store
        await store.ensure_profile(7)
        await store.update_settings(7, changed_by=1)
        assert conn.history == [] and conn.notifies == []

    @pytest.mark.asyncio
    async def test_settings_optimistic_conflict(self, conn_store):
        conn, store = conn_store
        p = await store.ensure_profile(7)
        await store.set_manual(7, "конкурент", changed_by=1)
        with pytest.raises(ChatLoreConflict) as ei:
            await store.update_settings(
                7, auto_enabled=False, changed_by=1,
                expected_updated_at=p.updated_at)
        assert ei.value.current_updated_at == conn.profiles[7]["updated_at"]
        assert conn.profiles[7]["auto_enabled"] is True  # не применено

    @pytest.mark.asyncio
    async def test_settings_iso_expected_passes_datetime_to_sql(self,
                                                                conn_store):
        """ISO-string expected_updated_at → datetime в asyncpg-аргументах."""
        conn, store = conn_store
        p = await store.ensure_profile(7)
        await store.update_settings(
            7, auto_period_hours=48, changed_by=111,
            expected_updated_at=p.updated_at)
        locked = [q[1] for q in conn.queries if "::timestamptz" in q[0]]
        assert len(locked) == 1
        assert isinstance(locked[0][-1], datetime)
        assert locked[0][-1] == _ts_norm(p.updated_at)


# ── set_active (lifecycle, без истории) ─────────────────────────────────────

class TestSetActive:
    @pytest.mark.asyncio
    async def test_set_active_writes_no_history(self, conn_store):
        conn, store = conn_store
        await store.ensure_profile(7)
        await store.set_active(7, False)
        assert conn.profiles[7]["is_active"] is False
        assert conn.history == []
        assert conn.notifies == ["7"]

    @pytest.mark.asyncio
    async def test_set_active_true_creates_profile(self, conn_store):
        conn, store = conn_store
        await store.set_active(-9, True)
        assert -9 in conn.profiles
        assert conn.profiles[-9]["is_active"] is True


# ── chat_links: add/resolve ─────────────────────────────────────────────────

class TestChatLinks:
    @pytest.mark.asyncio
    async def test_add_link_upsert_repeat(self, conn_store):
        conn, store = conn_store
        await store.add_link(10, 20)
        await store.add_link(10, 30)          # повторный переезд — апдейт
        assert conn.links == {10: 30}

    @pytest.mark.asyncio
    async def test_resolve_chain(self, store):
        await store.add_link(10, 20)
        await store.add_link(20, 30)
        await store.add_link(30, 40)
        assert await store.resolve_chat_id(10) == 40
        assert await store.resolve_chat_id(30) == 40
        assert await store.resolve_chat_id(40) == 40   # без ссылки — сам
        assert await store.resolve_chat_id(999) == 999

    @pytest.mark.asyncio
    async def test_resolve_cycle_returns_original(self, store):
        await store.add_link(10, 20)
        await store.add_link(20, 10)
        assert await store.resolve_chat_id(10) == 10

    @pytest.mark.asyncio
    async def test_resolve_self_link(self, store):
        await store.add_link(10, 10)
        assert await store.resolve_chat_id(10) == 10

    @pytest.mark.asyncio
    async def test_resolve_depth_more_than_5_returns_original(self, store):
        for i in range(6):                    # 6 хопов: 1→2→…→7
            await store.add_link(100 + i, 101 + i)
        assert await store.resolve_chat_id(100) == 100

    @pytest.mark.asyncio
    async def test_resolve_depth_exactly_5_ok(self, store):
        for i in range(5):                    # 5 хопов: 100→101→…→105
            await store.add_link(100 + i, 101 + i)
        assert await store.resolve_chat_id(100) == 105


# ── chat_admins CRUD ────────────────────────────────────────────────────────

class TestChatAdmins:
    @pytest.mark.asyncio
    async def test_add_list_is_chat_admin(self, conn_store):
        conn, store = conn_store
        assert await store.add_chat_admin(-10, 555, added_by=1) is True
        assert await store.list_chat_admins(-10) == [555]
        assert await store.is_chat_admin(555, -10) is True
        assert await store.is_chat_admin(556, -10) is False
        rec = conn.history[-1]
        assert rec["field"] == "chat_admin"
        assert rec["new_value"] == "555"

    @pytest.mark.asyncio
    async def test_duplicate_add_no_history(self, conn_store):
        conn, store = conn_store
        assert await store.add_chat_admin(-10, 555, added_by=1) is True
        assert await store.add_chat_admin(-10, 555, added_by=1) is False
        assert len(conn.history) == 1

    @pytest.mark.asyncio
    async def test_remove_chat_admin_history(self, conn_store):
        conn, store = conn_store
        await store.add_chat_admin(-10, 555, added_by=1)
        assert await store.remove_chat_admin(-10, 555) is True
        assert await store.list_chat_admins(-10) == []
        rec = conn.history[-1]
        assert rec["field"] == "chat_admin"
        assert rec["old_value"] == "555"
        assert rec["new_value"] == ""
        assert await store.remove_chat_admin(-10, 555) is False

    @pytest.mark.asyncio
    async def test_admins_are_per_chat(self, store):
        await store.add_chat_admin(-10, 555, added_by=1)
        await store.add_chat_admin(-11, 555, added_by=1)
        assert await store.list_chat_admins(-11) == [555]
        assert await store.is_chat_admin(555, -10) is True


# ── migrate_profile: чистый перенос + merge (Q9/D5) ────────────────────────

class TestMigrateProfile:
    async def _seed_old(self, conn: _FakeConn, store: ChatLoreStore,
                        chat_id: int = -1000):
        conn.profiles[chat_id] = _profile_row(
            chat_id, manual="старый ручной", auto="старый авто",
            enabled=True, period=48, window=6, active=True)
        await store.add_chat_admin(chat_id, 555, added_by=1)
        await store.add_chat_admin(chat_id, 666, added_by=1)

    @pytest.mark.asyncio
    async def test_clean_move(self, conn_store):
        conn, store = conn_store
        await self._seed_old(conn, store, -1000)
        report = await store.migrate_profile(-1000, -2000)
        assert report == {"moved": True, "merged": False}
        # профиль перенесён (данные/настройки сохранены)
        new = await store.get_profile(-2000)
        assert new is not None and new.manual_lore == "старый ручной"
        assert new.auto_lore == "старый авто"
        assert new.auto_period_hours == 48 and new.auto_window_hours == 6
        assert new.is_active is True
        # старый удалён физически; чтения резолвятся на новый
        assert -1000 not in conn.profiles
        resolved = await store.get_profile(-1000)
        assert resolved is not None and resolved.chat_id == -2000
        # links + admins + история remap + NOTIFY old+new
        assert conn.links[-1000] == -2000
        assert await store.list_chat_admins(-2000) == [555, 666]
        remap = [h for h in conn.history if h["field"] == "remap"]
        assert len(remap) == 1
        assert remap[0]["old_value"] == "-1000"
        assert remap[0]["new_value"] == "-2000"
        assert set(conn.notifies) == {"-1000", "-2000"}

    @pytest.mark.asyncio
    async def test_merge_manual_old_wins(self, conn_store):
        conn, store = conn_store
        await self._seed_old(conn, store, -1000)
        conn.profiles[-2000] = _profile_row(
            -2000, manual="новый ручной", auto="новый авто",
            enabled=True, period=24, window=24, active=True)
        report = await store.migrate_profile(-1000, -2000)
        assert report == {"moved": False, "merged": True}
        merged = conn.profiles[-2000]
        assert merged["manual_lore"] == "старый ручной"   # старый приоритетнее
        assert merged["auto_lore"] == "новый авто"        # new не пуст
        assert merged["auto_enabled"] is True
        assert merged["is_active"] is True
        assert merged["auto_period_hours"] == 48          # скаляры от old
        assert merged["auto_window_hours"] == 6
        assert -1000 not in conn.profiles                  # old удалён
        assert await store.list_chat_admins(-2000) == [555, 666]
        assert set(conn.notifies) >= {"-1000", "-2000"}

    @pytest.mark.asyncio
    async def test_merge_old_manual_empty_keeps_new(self, conn_store):
        conn, store = conn_store
        conn.profiles[-1000] = _profile_row(
            -1000, manual="", auto="", enabled=True, period=24, window=24,
            active=True)
        conn.profiles[-2000] = _profile_row(
            -2000, manual="ценный ручной", auto="авто new", enabled=True,
            period=24, window=24, active=True)
        await store.migrate_profile(-1000, -2000)
        assert conn.profiles[-2000]["manual_lore"] == "ценный ручной"

    @pytest.mark.asyncio
    async def test_merge_auto_transfer_when_new_empty(self, conn_store):
        conn, store = conn_store
        conn.profiles[-1000] = _profile_row(
            -1000, manual="m old", auto="авто old", enabled=True,
            period=24, window=24, active=True)
        conn.profiles[-2000] = _profile_row(
            -2000, manual="m new", auto="", enabled=True,
            period=24, window=24, active=True)
        await store.migrate_profile(-1000, -2000)
        assert conn.profiles[-2000]["auto_lore"] == "авто old"

    @pytest.mark.asyncio
    async def test_merge_admins_union_old_rows_removed(self, conn_store):
        """Q9: админы объединяются (union); строки СТАРОГО чата удаляются
        целиком; админы, бывшие только у нового, сохраняются."""
        conn, store = conn_store
        await self._seed_old(conn, store, -1000)          # 555, 666
        conn.profiles[-2000] = _profile_row(-2000, manual="m new")
        await store.add_chat_admin(-2000, 777, added_by=2)  # только у new
        await store.migrate_profile(-1000, -2000)
        assert await store.list_chat_admins(-2000) == [555, 666, 777]
        assert await store.list_chat_admins(-1000) == []   # old вычищен

    @pytest.mark.asyncio
    async def test_merge_last_auto_at_max(self, conn_store):
        conn, store = conn_store
        conn.profiles[-1000] = _profile_row(
            -1000, last_auto_at="2026-09-01T00:00:00+00:00")
        conn.profiles[-2000] = _profile_row(
            -2000, last_auto_at="2026-09-05T00:00:00+00:00")
        await store.migrate_profile(-1000, -2000)
        assert conn.profiles[-2000]["last_auto_at"] == \
            "2026-09-05T00:00:00+00:00"

    @pytest.mark.asyncio
    async def test_merge_last_auto_at_iso_passes_datetime_to_sql(self,
                                                                 conn_store):
        """ISO-строки last_auto_at (из _max_ts) → datetime в $8::timestamptz."""
        conn, store = conn_store
        conn.profiles[-1000] = _profile_row(
            -1000, last_auto_at="2026-09-01T00:00:00+00:00")
        conn.profiles[-2000] = _profile_row(
            -2000, last_auto_at="2026-09-05T00:00:00+00:00")
        await store.migrate_profile(-1000, -2000)
        merge = [q[1] for q in conn.queries if "last_auto_at = $8" in q[0]]
        assert len(merge) == 1
        assert isinstance(merge[0][7], datetime)
        assert merge[0][7] == _ts_norm("2026-09-05T00:00:00+00:00")

    @pytest.mark.asyncio
    async def test_merge_enabled_and_active_or(self, conn_store):
        conn, store = conn_store
        conn.profiles[-1000] = _profile_row(-1000, enabled=False, active=True)
        conn.profiles[-2000] = _profile_row(-2000, enabled=True, active=False)
        await store.migrate_profile(-1000, -2000)
        row = conn.profiles[-2000]
        assert row["auto_enabled"] is True and row["is_active"] is True

    @pytest.mark.asyncio
    async def test_migrate_no_old_profile_noop(self, conn_store):
        conn, store = conn_store
        report = await store.migrate_profile(-1, -2)
        assert report == {"moved": False, "merged": False}
        assert conn.history == [] and conn.notifies == []
        assert conn.links == {} and await store.get_profile(-2) is None

    @pytest.mark.asyncio
    async def test_migrate_same_id_noop(self, conn_store):
        conn, store = conn_store
        await store.ensure_profile(-1)
        assert await store.migrate_profile(-1, -1) == \
            {"moved": False, "merged": False}
        assert conn.notifies == []

    @pytest.mark.asyncio
    async def test_migrate_through_links_resolves_old(self, conn_store):
        conn, store = conn_store
        await store.add_link(-1000, -1500)         # -1000 уже переезжал
        await self._seed_old(conn, store, -1500)
        await store.migrate_profile(-1000, -2000)  # переезд по цепочке
        assert conn.links[-1000] == -1500          # старая ссылка цела
        assert conn.links[-1500] == -2000          # цепь продолжена
        assert await store.resolve_chat_id(-1000) == -2000
        assert await store.get_profile(-2000) is not None


# ── история: timeline ───────────────────────────────────────────────────────

class TestHistory:
    @pytest.mark.asyncio
    async def test_history_rows_shape_and_desc(self, conn_store):
        conn, store = conn_store
        await store.ensure_profile(7)
        await store.set_manual(7, "первая", changed_by=1)
        await store.set_manual(7, "вторая", changed_by=2)
        rows = await store.history(7, limit=10)
        assert [r["new_value"] for r in rows] == ["вторая", "первая"]
        first = rows[0]
        assert set(first) == {"id", "chat_id", "field", "changed_by",
                              "old_value", "new_value", "created_at"}
        assert first["created_at"]
        assert first["field"] == "manual" and first["changed_by"] == 2
        assert await store.history(999) == []
        assert await store.list_history(7) == rows      # alias

    @pytest.mark.asyncio
    async def test_history_limit(self, conn_store):
        conn, store = conn_store
        await store.ensure_profile(7)
        for i in range(5):
            await store.set_manual(7, f"текст {i}", changed_by=i)
        assert len(await store.history(7, limit=2)) == 2
