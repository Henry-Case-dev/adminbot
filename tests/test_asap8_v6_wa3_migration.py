"""ASAP 8 v6 (Wave A, W-A3 / D02) — group→supergroup migration: реальный seam.

REGRESSION (D02, v6 §C / v5 §18B): хендлер зовёт add_link ДО
migrate_profile; store считал голый link доказательством переезда и
ранним no-op-ом (`resolved_old == new → {moved: False}` ДО чтения старого
профиля) создавал сироту: профиль оставался под old, под new появлялся
ПУСТОЙ профиль (upsert_profile_on_join). Плюс COPY_ADMINS терял
role_name → DB default 'local_admin' эскалировал moderator.

Здесь РЕАЛЬНЫЙ хендлер (handlers.chat_lifecycle.on_chat_migrated) +
РЕАЛЬНЫЙ ChatLoreStore (боевой SQL без изменений) на РЕАЛЬНОЙ SQLite-базе
(движок исполняет те же statements: транзакции BEGIN/ROLLBACK, RETURNING,
upsert ON CONFLICT). Никаких FakeStore-имитаций успеха. Негативные
сценарии: duplicate event; injected failure halfway → ретрай доводит без
сирот и без дублей; роль-эскалация админов.

Матрица миграции, проверяемая здесь (реально переносится):
  * chat_profiles целиком при move (лор/настройки/relations/
    relations_enabled/chat_params/gates_opt_in);
  * merge по Q9: manual/auto/params + D02-мерж relations/chat_params
    (новое живое значение приоритетно, старое заполняет пробелы) и
    gates_opt_in = old OR new;
  * chat_admins: move (все колонки) / copy с ЯВНЫМ role_name (moderator
    остаётся moderator);
  * chat_lore_history — переезжает на новый id (timeline живой), remap-
    строка ровно одна на переезд;
  * chat_links + NOTIFY old+new.
Вне store (отдельные seam'ы, здесь не тестируются): SQLite
chat_id_migrations для aliases/self-model identity — хендлер регистрирует
через message_identity.register_chat_id_migration (MCA-03, свой D-ID);
summary/memory-таблицы — домен summary_memory (свой D-ID).

TEST-LIFECYCLE: REGRESSION owner=ASAP8-V6/D02
"""
import json
import re
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers import chat_lifecycle as lifecycle
from services.chat_lore_store import ChatLoreStore

BOT_ID = 12345
OLD = -100111
NEW = -100222


# ── РЕАЛЬНАЯ SQLite-база (схема = боевая pg_db-схема, incl. F-7/R9-колонки)

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS chat_profiles (
        chat_id           INTEGER PRIMARY KEY,
        manual_lore       TEXT NOT NULL DEFAULT '',
        auto_lore         TEXT NOT NULL DEFAULT '',
        auto_enabled      BOOLEAN NOT NULL DEFAULT TRUE,
        auto_period_hours INTEGER NOT NULL DEFAULT 24,
        auto_window_hours INTEGER NOT NULL DEFAULT 24,
        is_active         BOOLEAN NOT NULL DEFAULT TRUE,
        last_auto_at      TIMESTAMPTZ,
        updated_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        relations         TEXT NOT NULL DEFAULT '{}',
        relations_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        chat_params       TEXT NOT NULL DEFAULT '{}',
        gates_opt_in      BOOLEAN NOT NULL DEFAULT FALSE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_lore_history (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id    INTEGER NOT NULL,
        field      TEXT NOT NULL CHECK (field IN
                   ('manual', 'auto', 'auto_enabled', 'auto_period_hours',
                    'auto_window_hours', 'remap', 'chat_admin')),
        changed_by INTEGER,
        old_value  TEXT NOT NULL DEFAULT '',
        new_value  TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_links (
        old_chat_id INTEGER PRIMARY KEY,
        new_chat_id INTEGER NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_admins (
        chat_id     INTEGER NOT NULL,
        telegram_id INTEGER NOT NULL,
        added_by    INTEGER,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        role_name   TEXT NOT NULL DEFAULT 'local_admin',
        PRIMARY KEY (chat_id, telegram_id)
    )
    """,
)


class _SqliteConn:
    """asyncpg-совместимый conn над реальным sqlite3
    (isolation_level=None → явные BEGIN/COMMIT/ROLLBACK = настоящая
    атомарность/откат). SQL боевого store исполняется движком как есть:
    $N→? (позиционные), ::type-касты срезаются, now()→CURRENT_TIMESTAMP,
    pg_notify — перехват в журнал. fail_on — подстрока SQL, на которой
    операция падает (injected failure). JSONB-колонки (relations/
    chat_params) возвращаются распарсенными — как asyncpg jsonb-кодек."""

    _CAST = re.compile(r"::\w+")
    _PARAM = re.compile(r"\$(\d+)")
    _NOW = re.compile(r"\bnow\(\)")
    _JSON_COLS = ("relations", "chat_params")

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self.notifies: list[str] = []
        self.fail_on: str | None = None

    def _translate(self, sql: str, args: tuple):
        tsql = self._NOW.sub("CURRENT_TIMESTAMP", sql)
        tsql = self._CAST.sub("", tsql)
        # asyncpg биндит $N ПО НОМЕРУ (в MERGE $1 стоит в WHERE последним),
        # sqlite3 «?» — позиционно: пермутируем аргументы по порядку
        # появления плейсхолдеров в тексте.
        order: list[int] = []

        def _repl(match: "re.Match[str]") -> str:
            order.append(int(match.group(1)))
            return "?"

        tsql = self._PARAM.sub(_repl, tsql)
        targs = tuple(
            args[n - 1].isoformat() if isinstance(args[n - 1], datetime)
            else args[n - 1]
            for n in order)
        return tsql, targs

    def _maybe_fail(self, sql: str) -> None:
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError(f"injected failure on: {self.fail_on}")

    def _row(self, cur) -> dict | None:
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        cur.close()
        if row is None:
            return None
        out = dict(zip(cols, row))
        for col in self._JSON_COLS:
            if isinstance(out.get(col), str):
                try:
                    out[col] = json.loads(out[col])
                except ValueError:
                    pass
        return out

    async def execute(self, sql: str, *args):
        if "pg_notify" in sql:                       # NOTIFY-журнал
            self.notifies.append(str(args[0]) if args else "")
            return "SELECT 1"
        self._maybe_fail(sql)
        tsql, targs = self._translate(sql, args)
        self._db.execute(tsql, targs)
        return "OK"

    async def fetchrow(self, sql: str, *args):
        self._maybe_fail(sql)
        tsql, targs = self._translate(sql, args)
        return self._row(self._db.execute(tsql, targs))

    async def fetch(self, sql: str, *args):
        self._maybe_fail(sql)
        tsql, targs = self._translate(sql, args)
        cur = self._db.execute(tsql, targs)
        cols = [d[0] for d in cur.description]
        rows = []
        for raw in cur.fetchall():
            out = dict(zip(cols, raw))
            for col in self._JSON_COLS:
                if isinstance(out.get(col), str):
                    try:
                        out[col] = json.loads(out[col])
                    except ValueError:
                        pass
            rows.append(out)
        cur.close()
        return rows

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                conn._db.execute("BEGIN")
                return conn

            async def __aexit__(self, exc_type, exc, tb):
                if exc_type is not None:
                    conn._db.execute("ROLLBACK")     # настоящий откат
                else:
                    conn._db.execute("COMMIT")
                return False

        return _Tx()


class _SqlitePool:
    """asyncpg-совместимый пул: один реальный sqlite3-коннект."""

    def __init__(self, db: sqlite3.Connection):
        self.conn = _SqliteConn(db)

    @property
    def pool(self) -> "_SqlitePool":
        """ChatLoreStore._pool() читает pg.pool — отдаём себя."""
        return self

    def acquire(self):
        conn = self.conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


@pytest.fixture()
def env():
    """Реальный store на реальной SQLite-базе + реальный хендлер."""
    db = sqlite3.connect(":memory:", isolation_level=None)
    for stmt in _DDL:
        db.execute(stmt)
    pool = _SqlitePool(db)
    store = ChatLoreStore(pool)
    with patch.object(lifecycle, "_store", store), \
            patch.object(lifecycle, "_bot_id", BOT_ID), \
            patch.object(lifecycle, "_db", None), \
            patch.object(lifecycle, "ensure_gates_defaults",
                         AsyncMock()) as gates:
        yield SimpleNamespace(store=store, pool=pool, db=db,
                              conn=pool.conn, gates=gates)
    db.close()


# ── сиды (сырой SQL — та же база, что видит store) ─────────────────────────

def _seed_profile(db, chat_id, *, manual="", auto="", enabled=1, active=1,
                  period=24, window=24, relations="{}",
                  relations_enabled=0, chat_params="{}", gates_opt_in=0):
    db.execute(
        "INSERT INTO chat_profiles (chat_id, manual_lore, auto_lore, "
        "auto_enabled, auto_period_hours, auto_window_hours, is_active, "
        "relations, relations_enabled, chat_params, gates_opt_in) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (chat_id, manual, auto, enabled, period, window, active,
         relations, relations_enabled, chat_params, gates_opt_in))


def _seed_admin(db, chat_id, telegram_id, role_name="local_admin",
                added_by=1):
    db.execute(
        "INSERT INTO chat_admins (chat_id, telegram_id, added_by, role_name) "
        "VALUES (?, ?, ?, ?)", (chat_id, telegram_id, added_by, role_name))


def _admin_roles(db, chat_id) -> dict[int, str]:
    return {r[0]: r[1] for r in db.execute(
        "SELECT telegram_id, role_name FROM chat_admins WHERE chat_id = ?",
        (chat_id,)).fetchall()}


def _remap_count(db) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM chat_lore_history WHERE field = 'remap'"
    ).fetchone()[0]


def _migrate_message(old_id=OLD, new_id=NEW):
    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = old_id
    msg.migrate_to_chat_id = new_id
    msg.message_id = 555
    return msg


# ── главный негативный сценарий (RED на pre-fix коде) ──────────────────────

class TestLinkBeforeMigrateRegression:
    @pytest.mark.asyncio
    async def test_link_before_migrate_migrates_full_profile(self, env):
        """add_link→migrate_profile: голый link НЕ «уже перенесено».
        Pre-fix store возвращал ранний no-op → хендлер создавал ПУСТОЙ
        профиль под new, лор оставался сиротой под old."""
        _seed_profile(
            env.db, OLD, manual="ручной лор", auto="авто лор",
            relations=json.dumps(
                {"555": {"manual_stage": "veteran", "note": "старожил"}}),
            relations_enabled=1,
            chat_params=json.dumps(
                {"v": 1,
                 "overrides": {"limits.context_max_chars": 8000},
                 "gates": {"dream": False, "lore_auto": False}}),
            gates_opt_in=1)
        _seed_admin(env.db, OLD, 555, role_name="moderator")

        assert await lifecycle.on_chat_migrated(_migrate_message()) is None

        # профиль ПЕРЕНЕСЁН с данными (не пустая заглушка)
        profile = await env.store.get_profile(NEW)
        assert profile is not None
        assert profile.chat_id == NEW
        assert profile.manual_lore == "ручной лор"
        assert profile.auto_lore == "авто лор"
        assert profile.relations.get("555", {}).get("manual_stage") == \
            "veteran"
        assert profile.relations_enabled is True
        # сироты нет: под old физически пусто
        rows = env.db.execute(
            "SELECT chat_id FROM chat_profiles WHERE chat_id = ?",
            (OLD,)).fetchall()
        assert rows == []
        # link записан, параметры/оптины переехали (move — строка целиком)
        link = env.db.execute(
            "SELECT new_chat_id FROM chat_links WHERE old_chat_id = ?",
            (OLD,)).fetchone()
        assert link == (NEW,)
        params = env.db.execute(
            "SELECT chat_params, gates_opt_in FROM chat_profiles "
            "WHERE chat_id = ?", (NEW,)).fetchone()
        moved_params = json.loads(params[0])
        assert moved_params["overrides"] == {"limits.context_max_chars": 8000}
        assert moved_params["gates"] == {"dream": False, "lore_auto": False}
        assert params[1] == 1

    @pytest.mark.asyncio
    async def test_store_migrates_despite_preexisting_link(self, env):
        """Store-level: migrate_profile при УЖЕ записанном link досносит
        профиль под исходный id (pre-fix: ранний no-op)."""
        _seed_profile(env.db, OLD, manual="старый лор")
        await env.store.add_link(OLD, NEW)
        report = await env.store.migrate_profile(OLD, NEW)
        assert report == {"moved": True, "merged": False}
        profile = await env.store.get_profile(NEW)
        assert profile.manual_lore == "старый лор"
        assert env.db.execute(
            "SELECT COUNT(*) FROM chat_profiles WHERE chat_id = ?",
            (OLD,)).fetchone()[0] == 0


class TestInjectedFailureAndDuplicate:
    @pytest.mark.asyncio
    async def test_failure_halfway_move_branch_retry_completes(self, env):
        """Сбой посередине move-ветки (после переноса профиля, на админах):
        транзакция откатывается ЦЕЛИКОМ (профиль остаётся под old, link
        уже закоммичен отдельной транзакцией add_link) → ретрай тем же
        событием доводит миграцию: без сирот, без дублей remap."""
        _seed_profile(env.db, OLD, manual="лор до сбоя")
        _seed_admin(env.db, OLD, 555, role_name="moderator")
        env.db.execute(
            "INSERT INTO chat_lore_history (chat_id, field, changed_by, "
            "old_value, new_value) VALUES (?, 'manual', 1, '', 'запись "
            "истории')", (OLD,))

        env.conn.fail_on = "UPDATE chat_admins"          # MOVE_ADMINS
        assert await lifecycle.on_chat_migrated(
            _migrate_message()) is None                  # fail-open хендлера
        # откат: профиль всё ещё под старым id; link уже есть
        assert env.db.execute(
            "SELECT COUNT(*) FROM chat_profiles WHERE chat_id = ?",
            (OLD,)).fetchone()[0] == 1
        assert env.db.execute(
            "SELECT COUNT(*) FROM chat_profiles WHERE chat_id = ?",
            (NEW,)).fetchone()[0] == 0
        assert env.db.execute(
            "SELECT new_chat_id FROM chat_links WHERE old_chat_id = ?",
            (OLD,)).fetchone() == (NEW,)
        assert _remap_count(env.db) == 0

        env.conn.fail_on = None                          # ретрай
        assert await lifecycle.on_chat_migrated(_migrate_message()) is None

        profile = await env.store.get_profile(NEW)
        assert profile is not None
        assert profile.manual_lore == "лор до сбоя"
        assert env.db.execute(
            "SELECT COUNT(*) FROM chat_profiles WHERE chat_id = ?",
            (OLD,)).fetchone()[0] == 0
        assert _admin_roles(env.db, NEW) == {555: "moderator"}
        assert _admin_roles(env.db, OLD) == {}
        # remap ровно один; история лора переехала на новый id
        assert _remap_count(env.db) == 1
        history_new = await env.store.history(NEW, limit=50)
        assert [h["new_value"] for h in history_new
                if h["field"] == "manual"] == ["запись истории"]
        assert any(h["field"] == "remap" for h in history_new)

    @pytest.mark.asyncio
    async def test_failure_halfway_merge_branch_retry_completes(self, env):
        """Сбой посередине merge-ветки (после мержа, на удалении old):
        полный откат → ретрай доводит merge без дублей админов."""
        _seed_profile(env.db, OLD, manual="старый ручной",
                      relations=json.dumps(
                          {"555": {"manual_stage": "regular"}}),
                      chat_params=json.dumps(
                          {"v": 1, "gates": {"dream": False}}),
                      gates_opt_in=1)
        _seed_profile(env.db, NEW, manual="новый ручной",
                      relations_enabled=1,
                      chat_params=json.dumps(
                          {"v": 1,
                           "overrides": {"flags.reactions_enabled": True},
                           "gates": {"permsoc": False}}))
        _seed_admin(env.db, OLD, 555, role_name="moderator")
        _seed_admin(env.db, NEW, 777, role_name="moderator", added_by=2)

        env.conn.fail_on = "DELETE FROM chat_profiles"
        assert await lifecycle.on_chat_migrated(_migrate_message()) is None
        # откат: оба профиля на месте, мерж не закоммичен
        assert env.db.execute(
            "SELECT COUNT(*) FROM chat_profiles").fetchone()[0] == 2
        assert _remap_count(env.db) == 0

        env.conn.fail_on = None
        assert await lifecycle.on_chat_migrated(_migrate_message()) is None

        profile = await env.store.get_profile(NEW)
        assert profile.chat_id == NEW
        assert profile.manual_lore == "старый ручной"     # Q9: старый важнее
        assert env.db.execute(
            "SELECT COUNT(*) FROM chat_profiles WHERE chat_id = ?",
            (OLD,)).fetchone()[0] == 0
        # union админов без дублей
        assert sorted(_admin_roles(env.db, NEW)) == [555, 777]
        assert _remap_count(env.db) == 1

    @pytest.mark.asyncio
    async def test_duplicate_event_no_duplicates(self, env):
        """Повторная доставка migrate_to_chat_id после успешного переезда —
        честный no-op: без второй remap-строки, без перезаписи данных,
        без дублей админов."""
        _seed_profile(env.db, OLD, manual="лор")
        _seed_admin(env.db, OLD, 555, role_name="moderator")
        env.db.execute(
            "INSERT INTO chat_lore_history (chat_id, field, changed_by, "
            "old_value, new_value) VALUES (?, 'manual', 1, '', 'история')",
            (OLD,))

        assert await lifecycle.on_chat_migrated(_migrate_message()) is None
        first_history = await env.store.history(NEW, limit=50)
        first_admins = _admin_roles(env.db, NEW)

        assert await lifecycle.on_chat_migrated(_migrate_message()) is None

        assert _remap_count(env.db) == 1
        assert await env.store.history(NEW, limit=50) == first_history
        assert _admin_roles(env.db, NEW) == first_admins
        profile = await env.store.get_profile(NEW)
        assert profile.manual_lore == "лор"
        # под old не resurrectился
        assert env.db.execute(
            "SELECT COUNT(*) FROM chat_profiles WHERE chat_id = ?",
            (OLD,)).fetchone()[0] == 0


# ── роль-модель админов (D4 из v5: без эскалации) ──────────────────────────

class TestAdminRolesNoEscalation:
    @pytest.mark.asyncio
    async def test_merge_copies_exact_role_not_default(self, env):
        """COPY-ветка (merge): role_name копируется ЯВНО. Pre-fix SQL не
        нёс role_name → вставка получала DB default 'local_admin' —
        moderator незаметно становился local_admin."""
        _seed_profile(env.db, OLD, manual="старый")
        _seed_profile(env.db, NEW, manual="новый")
        _seed_admin(env.db, OLD, 555, role_name="moderator")
        _seed_admin(env.db, OLD, 666, role_name="local_admin")
        _seed_admin(env.db, NEW, 777, role_name="moderator")

        await env.store.migrate_profile(OLD, NEW)

        roles = _admin_roles(env.db, NEW)
        assert roles == {555: "moderator", 666: "local_admin",
                         777: "moderator"}
        assert _admin_roles(env.db, OLD) == {}

    @pytest.mark.asyncio
    async def test_move_preserves_exact_roles(self, env):
        """Move-ветка: строки переезжают целиком — moderator остаётся
        moderator (никто не повышен default'ом)."""
        _seed_profile(env.db, OLD, manual="лор")
        _seed_admin(env.db, OLD, 555, role_name="moderator")
        _seed_admin(env.db, OLD, 666, role_name="local_admin")

        assert await lifecycle.on_chat_migrated(_migrate_message()) is None

        assert _admin_roles(env.db, NEW) == {555: "moderator",
                                             666: "local_admin"}


# ── матрица merge: params/opt-ins/relations/module state ───────────────────

class TestMergeMatrix:
    @pytest.mark.asyncio
    async def test_merge_carries_params_gates_optin_relations(self, env):
        """Merge: chat_params мержится по ключам (старое заполняет пробелы,
        новое приоритетно в общих ключах), gates объединяются,
        gates_opt_in = old OR new, relations объединяются,
        relations_enabled = old OR new."""
        _seed_profile(
            env.db, OLD,
            manual="старый ручной",
            relations=json.dumps(
                {"555": {"manual_stage": "regular", "note": "пометка"}}),
            relations_enabled=0,
            chat_params=json.dumps(
                {"v": 1,
                 "overrides": {"limits.context_max_chars": 8000,
                               "memory.random_enabled": True},
                 "gates": {"dream": False, "lore_auto": False}}),
            gates_opt_in=1)
        _seed_profile(
            env.db, NEW,
            manual="новый ручной",
            relations=json.dumps(
                {"777": {"manual_stage": "acquaintance"}}),
            relations_enabled=1,
            chat_params=json.dumps(
                {"v": 1,
                 "overrides": {"flags.reactions_enabled": True},
                 "gates": {"permsoc": False, "lore_auto": True}}),
            gates_opt_in=0)

        report = await env.store.migrate_profile(OLD, NEW)
        assert report == {"moved": False, "merged": True}

        row = env.db.execute(
            "SELECT chat_params, gates_opt_in, relations, relations_enabled "
            "FROM chat_profiles WHERE chat_id = ?", (NEW,)).fetchone()
        params = json.loads(row[0])
        # overrides: union обоих чатов (module state не потерян)
        assert params["overrides"] == {
            "limits.context_max_chars": 8000,
            "memory.random_enabled": True,
            "flags.reactions_enabled": True,
        }
        # gates: feature opt-ins union (общий ключ — живой новый)
        assert params["gates"] == {"dream": False, "lore_auto": True,
                                   "permsoc": False}
        assert row[1] == 1                        # gates_opt_in = old OR new
        relations = json.loads(row[2])
        assert set(relations) == {"555", "777"}   # связи обоих
        assert relations["555"]["note"] == "пометка"
        assert row[3] == 1                        # relations_enabled OR

    @pytest.mark.asyncio
    async def test_merge_empty_new_params_filled_from_old(self, env):
        """Типовой кейс: под new пустой дефолт-профиль — все параметры/
        оптины старого переносятся целиком."""
        _seed_profile(
            env.db, OLD, manual="лор",
            chat_params=json.dumps(
                {"v": 1,
                 "overrides": {"memory.random_enabled": True},
                 "gates": {"dream": False}}),
            gates_opt_in=1)
        _seed_profile(env.db, NEW)                # дефолт-строка

        await env.store.migrate_profile(OLD, NEW)

        row = env.db.execute(
            "SELECT chat_params, gates_opt_in FROM chat_profiles "
            "WHERE chat_id = ?", (NEW,)).fetchone()
        params = json.loads(row[0])
        assert params["overrides"] == {"memory.random_enabled": True}
        assert params["gates"] == {"dream": False}
        assert row[1] == 1

    @pytest.mark.asyncio
    async def test_move_keeps_whole_profile_row(self, env):
        """Move: строка переезжает целиком — chat_params/relations/
        gates_opt_in на месте без отдельного мержа."""
        _seed_profile(
            env.db, OLD, manual="лор", enabled=0, active=0, period=48,
            window=6,
            relations=json.dumps({"555": {"manual_stage": "veteran"}}),
            relations_enabled=1,
            chat_params=json.dumps({"v": 1, "gates": {"nostalgia": False}}),
            gates_opt_in=1)

        assert await lifecycle.on_chat_migrated(_migrate_message()) is None

        row = env.db.execute(
            "SELECT manual_lore, auto_enabled, is_active, auto_period_hours,"
            " auto_window_hours, relations, relations_enabled, chat_params,"
            " gates_opt_in FROM chat_profiles WHERE chat_id = ?",
            (NEW,)).fetchone()
        assert row[0] == "лор"
        assert row[1] == 0 and row[2] == 0          # silent-реактивации нет
        assert (row[3], row[4]) == (48, 6)
        assert json.loads(row[5])["555"]["manual_stage"] == "veteran"
        assert row[6] == 1
        assert json.loads(row[7])["gates"] == {"nostalgia": False}
        assert row[8] == 1


# ── поведенческие контракты хендлера на реальном store ─────────────────────

class TestHandlerContractsRealStore:
    @pytest.mark.asyncio
    async def test_old_profile_absent_creates_new_profile(self, env):
        """Профиль old отсутствовал (потеря данных) → migrate no-op, но
        новый чат регистрируется (C9-контракт) + gates-дефолты."""
        assert await lifecycle.on_chat_migrated(_migrate_message()) is None
        profile = await env.store.get_profile(NEW)
        assert profile is not None
        assert profile.manual_lore == ""             # честный дефолт
        env.gates.assert_awaited_once_with(NEW)

    @pytest.mark.asyncio
    async def test_migration_notifies_old_and_new(self, env):
        """NOTIFY lore_updated для old и new (инвалидация LoreCache)."""
        _seed_profile(env.db, OLD, manual="лор")
        await lifecycle.on_chat_migrated(_migrate_message())
        assert NEW in {int(n) for n in env.conn.notifies}
        assert env.conn.notifies.count(str(OLD)) + \
            env.conn.notifies.count(str(NEW)) >= 2

    @pytest.mark.asyncio
    async def test_resolves_chain_after_migration(self, env):
        """Чтения по старому id резолвятся на новый (chat_links)."""
        _seed_profile(env.db, OLD, manual="лор")
        await lifecycle.on_chat_migrated(_migrate_message())
        assert await env.store.resolve_chat_id(OLD) == NEW
        resolved = await env.store.get_profile(OLD)
        assert resolved.chat_id == NEW
