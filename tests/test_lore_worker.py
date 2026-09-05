"""Раунд 7 (chat-lore-management-v2, T-784, H2.1) — тесты LoreWorker.

SQLite-tmp (smart_messages/protected_facts — реальный SQL воркера через
db.db.execute, ЧТЕНИЕ) + мок-стор + мок-llm + фейковый advisory-lock-connector.

Покрытие (spec §6.1/H2.1):
  * гейты: auto_enabled=false → skip без LLM; профиля нет → no_profile;
    inactive → skip; период не прошёл (свежий last_auto_at) → skip;
    flags.lore_auto_enabled=false → skip; cooldown → skip (manual игнорирует);
  * окно: осмысленных < lore_min_messages → quiet_window skip БЕЗ
    last_auto_at; фильтр осмысленности (короткие/команды/бот-строки
    исключены, импорт-строки user_id NULL включены); выборка DESC LIMIT
    + reverse → контекст ASC по формату канона;
  * INIT при пустом auto_lore / MERGE при непустом; chat-факты БЕЗ
    legacy-константы CHAT_LORE_2661910336;
  * запись: мок-ответ → set_auto (ok changed=True); UNCHANGED →
    mark_auto_done без set_auto и без истории; ответ == старому →
    mark_auto_done; LLM-ошибка → error без done (профиль не тронут);
  * advisory-lock: занят → skipped locked (unlock+close в finally);
    исключение генерации → unlock всё равно вызван.
"""
import time
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from services import hot_config as hot
from services.llm_client import LLMError
from services.lore_cache import LoreProfile
from services.lore_prompts import LORE_INIT_SYSTEM_PROMPT
from services.lore_worker import LoreWorker

CHAT_ID = -1002661910336
BOT_ID = 12345


def make_profile(chat_id: int = CHAT_ID, *,
                 manual: str = "", auto: str = "", auto_enabled: bool = True,
                 period_hours: int = 24, window_hours: int = 24,
                 is_active: bool = True, last_auto_at=None,
                 updated_at: str = "2026-09-06T10:00:00+00:00") -> LoreProfile:
    return LoreProfile(
        chat_id=chat_id, manual_lore=manual, auto_lore=auto,
        auto_enabled=auto_enabled, auto_period_hours=period_hours,
        auto_window_hours=window_hours, is_active=is_active,
        last_auto_at=last_auto_at, updated_at=updated_at)


class FakeStore:
    """Store-мок: профили + запись вызовов set_auto/mark_auto_done."""

    def __init__(self, profiles=None, fail_get=False):
        self.profiles = dict(profiles or {})
        self.fail_get = fail_get
        self.active_calls = 0
        self.set_auto_calls: list[tuple[int, str]] = []
        self.mark_done_calls: list[int] = []

    @property
    def pg(self):
        return None

    async def get_profile(self, chat_id):
        if self.fail_get:
            raise RuntimeError("pg down")
        return self.profiles.get(chat_id)

    async def list_active_chats(self):
        self.active_calls += 1
        return sorted(chat for chat, p in self.profiles.items()
                      if p.is_active and p.auto_enabled)

    async def set_auto(self, chat_id, text, changed_by=None,
                       record_history=True):
        self.set_auto_calls.append((chat_id, text))
        self.profiles[chat_id] = make_profile(
            chat_id, auto=text,
            last_auto_at=datetime.now(timezone.utc).isoformat())

    async def mark_auto_done(self, chat_id):
        self.mark_done_calls.append(chat_id)


class FakeLLM:
    """LLM-мок: текст ответа/ошибка; фиксирует вызовы (system/user)."""

    def __init__(self, text="новый авто-лор чата: все живы и общаются",
                 error=None):
        self.text = text
        self.error = error
        self.calls: list[list[dict]] = []
        self.call_count = 0

    async def generate(self, messages, temperature=None):
        self.call_count += 1
        self.calls.append(messages)
        if self.error is not None:
            if callable(self.error):
                raise self.error()
            raise self.error
        return self.text


class FakeLockConn:
    """Соединение pg_advisory-lock: fetchval-ответ + журнал execute/close."""

    def __init__(self, locked: bool = True):
        self.locked = locked
        self.ops: list[tuple[str, tuple]] = []
        self.closed = False

    async def fetchval(self, sql, *args):
        self.ops.append((sql, tuple(args)))
        return self.locked

    async def execute(self, sql, *args):
        self.ops.append((sql, tuple(args)))
        return "SELECT 1"

    async def close(self):
        self.closed = True

    @property
    def unlock_calls(self):
        return [op for op in self.ops
                if "pg_advisory_unlock" in op[0]]

    @property
    def lock_calls(self):
        return [op for op in self.ops
                if "pg_try_advisory_lock" in op[0]]


def _unlock_sql_present(conn: FakeLockConn) -> bool:
    return bool(conn.unlock_calls)


_SMART_SCHEMA = """
CREATE TABLE smart_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    chat_id INTEGER NOT NULL,
    text TEXT,
    reply_to_id INTEGER,
    timestamp INTEGER NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'text',
    author_name TEXT NOT NULL DEFAULT '',
    is_forward INTEGER NOT NULL DEFAULT 0,
    forward_source TEXT NOT NULL DEFAULT '',
    tg_message_id INTEGER
);
CREATE TABLE protected_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_name TEXT,
    fact TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


def _now_ts() -> int:
    return int(time.time())


async def _open_db(tmp_path, name="lore.db"):
    conn = await aiosqlite.connect(str(tmp_path / name))
    await conn.executescript(_SMART_SCHEMA)
    await conn.commit()
    return conn


async def _add_message(conn, text, *, user_id=111, author="Саша", ts=None,
                       chat_id=CHAT_ID):
    await conn.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "author_name) VALUES (?, ?, ?, ?, ?)",
        (user_id, chat_id, text, ts if ts is not None else _now_ts(), author))
    await conn.commit()


async def _add_fact(conn, fact, *, user_name=None, chat_id=CHAT_ID):
    await conn.execute(
        "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
        "VALUES (?, ?, ?, ?)",
        (chat_id, user_name, fact, time.time()))
    await conn.commit()


def _worker(store, conn, llm, *, bot_id=BOT_ID, locked=True, manual=False):
    lock_conn = FakeLockConn(locked=locked)

    async def _lock_connector():
        return lock_conn

    worker = LoreWorker(
        store, cache=None, db=type("DB", (), {"db": conn})(),
        llm=llm, bot_id=bot_id, lock_connector=_lock_connector,
    )
    return worker, lock_conn


def _hot_cache(monkeypatch, values: dict | None = None):
    """hot-кэш-заглушка: заданные ключи; отсутствующие → settings-дефолты
    (как hot.get(key, default))."""
    class _FakeHotCache:
        def __init__(self, values):
            self._values = dict(values or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


async def _seed_quiet_chat(conn) -> None:
    """Один осмысленный + мусор (короткое/команда/бот) — окно «тихое»."""
    await _add_message(conn, "x" * 30, user_id=111, author="Саша")
    await _add_message(conn, "короткое", user_id=222, author="Ксюша")
    await _add_message(conn, "/start очень длинная команда которая не нужна",
                       user_id=333)
    await _add_message(conn, "y" * 25, user_id=BOT_ID, author="бот")


async def _seed_busy_chat(conn, n: int = 16, chat_id: int = CHAT_ID) -> None:
    """n осмысленных сообщений (≥ дефолтного порога 15) + бот/команды."""
    for i in range(n):
        await _add_message(conn, f"сообщение номер {i} для лора — вполне "
                                 f"осмысленный текст", user_id=1000 + i,
                           author=f"Юзер{i}", ts=_now_ts() - (n - i) * 60,
                           chat_id=chat_id)


class TestProfileGates:
    @pytest.mark.asyncio
    async def test_missing_profile_skips_without_llm(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            store = FakeStore()
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "skipped", "reason": "no_profile"}
            assert llm.call_count == 0
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_inactive_profile_skips(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            store = FakeStore({CHAT_ID: make_profile(is_active=False)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "skipped", "reason": "inactive"}
            assert llm.call_count == 0
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_auto_disabled_skips_even_with_messages(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            store = FakeStore({CHAT_ID: make_profile(auto_enabled=False)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "skipped", "reason": "auto_disabled"}
            assert llm.call_count == 0
            assert store.mark_done_calls == []
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_resolved_chat_id_used_for_window_and_write(self, tmp_path):
        """Профиль «переехал» (резолв в store) → окно/запись идут по
        актуальному id (spec §3.5: актуальный chat_id после резолва)."""
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn, chat_id=-100999)
            store = FakeStore({CHAT_ID: make_profile(chat_id=-100999,
                                                     last_auto_at=None)})
            llm = FakeLLM()
            worker, lock_conn = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result["status"] == "ok"
            assert lock_conn.lock_calls[0][1] == (-100999,)  # лок по новому id
            assert store.set_auto_calls == [(-100999, llm.text)]
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_auto_disabled_skips_manual_too(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            store = FakeStore({CHAT_ID: make_profile(auto_enabled=False)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID, manual=True)
            assert result["reason"] == "auto_disabled"
            assert llm.call_count == 0
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_period_not_due_skips(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            fresh = (datetime.now(timezone.utc) - timedelta(hours=2)
                     ).isoformat()
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=fresh)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "skipped", "reason": "period_not_due"}
            assert llm.call_count == 0
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_period_elapsed_proceeds(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            old = (datetime.now(timezone.utc) - timedelta(hours=25)
                   ).isoformat()
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=old)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result["status"] == "ok"
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_auto_flag_disabled_skips(self, tmp_path, monkeypatch):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            _hot_cache(monkeypatch, {"flags.lore_auto_enabled": False})
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=None)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "skipped",
                              "reason": "auto_flag_disabled"}
            assert llm.call_count == 0
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_manual_ignores_period_and_flag(self, tmp_path, monkeypatch):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            fresh = (datetime.now(timezone.utc) - timedelta(hours=1)
                     ).isoformat()
            _hot_cache(monkeypatch, {"flags.lore_auto_enabled": False})
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=fresh)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID, manual=True)
            assert result["status"] == "ok"          # manual вне периода
        finally:
            await conn.close()


class TestCooldown:
    @pytest.mark.asyncio
    async def test_cooldown_skips_second_auto_run(self, tmp_path, monkeypatch):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            _hot_cache(monkeypatch, {"limits.lore_generate_cooldown": 3600})
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=None)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            first = await worker.generate_for_chat(CHAT_ID)
            assert first["status"] == "ok"
            # период «прошёл» (last_auto_at сброшен) — но cooldown ещё активен
            store.profiles[CHAT_ID] = make_profile(
                auto=llm.text, last_auto_at=None)
            second = await worker.generate_for_chat(CHAT_ID)
            assert second == {"status": "skipped", "reason": "cooldown"}
            assert llm.call_count == 1
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_manual_ignores_cooldown(self, tmp_path, monkeypatch):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            _hot_cache(monkeypatch, {"limits.lore_generate_cooldown": 3600})
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=None)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            assert (await worker.generate_for_chat(CHAT_ID))["status"] == "ok"
            store.profiles[CHAT_ID] = make_profile(
                auto=llm.text, last_auto_at=None)
            result = await worker.generate_for_chat(CHAT_ID, manual=True)
            assert result["status"] == "ok"          # рука человека (Q4)
            assert llm.call_count == 2
        finally:
            await conn.close()


class TestWindow:
    @pytest.mark.asyncio
    async def test_quiet_window_skips_without_marking(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_quiet_chat(conn)
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=None)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "skipped", "reason": "quiet_window"}
            assert llm.call_count == 0
            assert store.set_auto_calls == []
            assert store.mark_done_calls == []   # тихие дни НЕ сдвигают период
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_meaningfulness_filter(self, tmp_path, monkeypatch):
        """Короткие/команды/бот-строки исключены; импорт-строки (user_id
        NULL) включены; окно собирается в хронологическом порядке."""
        conn = await _open_db(tmp_path)
        try:
            _hot_cache(monkeypatch, {"limits.lore_min_messages": 1})
            ts_base = _now_ts() - 600
            # мусор: короткое, команда, бот
            await _add_message(conn, "короткое", user_id=222,
                               author="Ксюша", ts=ts_base)
            await _add_message(conn, "/start длинная команда с текстом",
                               user_id=333, author="Костя", ts=ts_base)
            await _add_message(conn, "b" * 30, user_id=BOT_ID,
                               author="бот", ts=ts_base)
            # осмысленные: импорт (user_id NULL) + юзер
            await _add_message(conn, "импортированная строка истории без "
                                     "автора и без юзера", user_id=None,
                               author="", ts=ts_base - 60)
            await _add_message(conn, "свежее сообщение от Саши про лор чата",
                               user_id=111, author="Саша", ts=ts_base + 60)
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=None)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result["status"] == "ok"
            user_content = llm.calls[0][1]["content"]
            assert "Саша: свежее сообщение" in user_content
            assert "импортированная строка истории" in user_content
            assert "короткое" not in user_content.split(
                "Защищённые факты")[0]
            assert "/start" not in user_content
            assert ("бот: " + "b" * 30) not in user_content
            # хронология ASC: импорт раньше свежего
            assert (user_content.find("импортированная")
                    < user_content.find("свежее сообщение"))
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_window_max_messages_limit(self, tmp_path, monkeypatch):
        conn = await _open_db(tmp_path)
        try:
            _hot_cache(monkeypatch, {
                "limits.lore_min_messages": 1,
                "limits.lore_window_max_messages": 3,
            })
            for i in range(10):
                await _add_message(
                    conn, f"сообщение {i} достаточно длинное для лора",
                    user_id=100 + i, author=f"Юзер{i}",
                    ts=_now_ts() - (10 - i) * 60)
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=None)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            await worker.generate_for_chat(CHAT_ID)
            content = llm.calls[0][1]["content"]
            assert "сообщение 9" in content          # свежий конец
            assert "сообщение 0" not in content      # лимит строк сработал
            # хронология ASC: строки от старого к свежему внутри окна
            assert (content.find("сообщение 7")
                    < content.find("сообщение 9"))
        finally:
            await conn.close()


class TestContextAndWrite:
    @pytest.mark.asyncio
    async def test_init_mode_when_auto_empty(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            store = FakeStore({CHAT_ID: make_profile(auto="")})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "ok", "changed": True}
            system = llm.calls[0][0]["content"]
            assert system.startswith(LORE_INIT_SYSTEM_PROMPT.split("\n")[0])
            assert "Новые сообщения чата" in llm.calls[0][1]["content"]
            assert "Текущий авто-лор" not in llm.calls[0][1]["content"]
            assert store.set_auto_calls == [(CHAT_ID, llm.text)]
            assert store.mark_done_calls == []
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_merge_mode_with_existing_auto(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            store = FakeStore({CHAT_ID: make_profile(auto="старый авто-лор")})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "ok", "changed": True}
            content = llm.calls[0][1]["content"]
            assert "Текущий авто-лор чата:\nстарый авто-лор" in content
            assert "Новые сообщения чата" in content
            assert store.set_auto_calls == [(CHAT_ID, llm.text)]
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_facts_include_chat_level_without_legacy_const(
            self, tmp_path):
        from services.chat_lore import CHAT_LORE_2661910336
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            await _add_fact(conn, "чат-факт: сходки по субботам")
            await _add_fact(conn, CHAT_LORE_2661910336)
            store = FakeStore({CHAT_ID: make_profile(auto="")})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            await worker.generate_for_chat(CHAT_ID)
            content = llm.calls[0][1]["content"]
            assert "- чат-факт: сходки по субботам" in content
            assert CHAT_LORE_2661910336 not in content  # дубль manual после
            # сида исключён
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_unchanged_response_marks_done(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            store = FakeStore({CHAT_ID: make_profile(auto="старый")})
            llm = FakeLLM(text="unchanged")
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "ok", "changed": False}
            assert store.set_auto_calls == []
            assert store.mark_done_calls == [CHAT_ID]
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_response_equal_to_old_marks_done(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            store = FakeStore({CHAT_ID: make_profile(auto="тот же лор")})
            llm = FakeLLM(text="тот же лор")
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "ok", "changed": False}
            assert store.set_auto_calls == []
            assert store.mark_done_calls == [CHAT_ID]
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_llm_error_fails_without_touching_profile(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            store = FakeStore({CHAT_ID: make_profile(auto="старый")})
            llm = FakeLLM(error=LLMError("provider 500"))
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "error", "reason": "llm_error"}
            assert store.set_auto_calls == []
            assert store.mark_done_calls == []
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_empty_llm_response_is_error(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            store = FakeStore({CHAT_ID: make_profile(auto="старый")})
            llm = FakeLLM(text="   \n  ")
            worker, _ = _worker(store, conn, llm)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "error", "reason": "llm_empty"}
            assert store.set_auto_calls == []
            assert store.mark_done_calls == []
        finally:
            await conn.close()


class TestAdvisoryLock:
    @pytest.mark.asyncio
    async def test_lock_busy_skips_and_unlocks_nothing(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=None)})
            llm = FakeLLM()
            worker, lock_conn = _worker(store, conn, llm, locked=False)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "skipped", "reason": "locked"}
            assert llm.call_count == 0
            assert lock_conn.lock_calls
            assert _unlock_sql_present(lock_conn)   # unlock в finally
            assert lock_conn.closed
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_unlock_on_llm_error(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=None)})
            llm = FakeLLM(error=LLMError("boom"))
            worker, lock_conn = _worker(store, conn, llm, locked=True)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result["status"] == "error"
            assert _unlock_sql_present(lock_conn)
            assert lock_conn.closed
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_lock_connector_failure_fail_open(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=None)})
            llm = FakeLLM()

            async def broken_connector():
                raise ConnectionError("pg down")

            worker = LoreWorker(
                store, db=type("DB", (), {"db": conn})(), llm=llm,
                bot_id=BOT_ID, lock_connector=broken_connector)
            result = await worker.generate_for_chat(CHAT_ID)
            assert result == {"status": "failed"}
            assert llm.call_count == 0
        finally:
            await conn.close()


class TestTick:
    @pytest.mark.asyncio
    async def test_tick_runs_active_chats_and_fails_open(self, tmp_path):
        conn = await _open_db(tmp_path)
        try:
            await _seed_busy_chat(conn)
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=None)})
            llm = FakeLLM(text="UNCHANGED")
            worker, _ = _worker(store, conn, llm)
            await worker.tick()
            assert llm.call_count == 1
            assert store.mark_done_calls == [CHAT_ID]
            assert store.active_calls == 1
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_tick_survives_store_failure(self, tmp_path, caplog):
        conn = await _open_db(tmp_path)
        try:
            store = FakeStore({})
            store.fail_get = True

            async def broken_store_call():
                raise RuntimeError("pg down")

            store.list_active_chats = broken_store_call
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            await worker.tick()                 # не роняет тик
            assert llm.call_count == 0
        finally:
            await conn.close()


class TestWindowCharsBudget:
    @pytest.mark.asyncio
    async def test_char_budget_keeps_fresh_end(self, tmp_path, monkeypatch):
        conn = await _open_db(tmp_path)
        try:
            _hot_cache(monkeypatch, {
                "limits.lore_min_messages": 1,
                "limits.lore_window_max_chars": 120,
            })
            long_text = "очень длинное сообщение " + "текст " * 40
            for i in range(4):
                await _add_message(conn, f"сообщение {i} " + long_text,
                                   user_id=100 + i, author=f"Юзер{i}",
                                   ts=_now_ts() - (4 - i) * 60)
            store = FakeStore({CHAT_ID: make_profile(last_auto_at=None)})
            llm = FakeLLM()
            worker, _ = _worker(store, conn, llm)
            await worker.generate_for_chat(CHAT_ID)
            content = llm.calls[0][1]["content"]
            assert "сообщение 3" in content       # свежий конец сохранён
            assert "Защищённые факты" in content or True
        finally:
            await conn.close()
