"""MCA-18 side-fix T-5150 — регресс ежечасного legacy-тика (int(datetime)).

Прод-дефект 2.58.62+ (`mca_self_model.py` `_tick_legacy_traits_parse` →
`run_legacy_traits_parse`): PG `persona_traits.created_at` — `timestamptz`,
asyncpg отдаёт `datetime`; старый код `int(row["created_at"] or time.time())`
падал `TypeError` на КАЖДОЙ строке → ежечасный fail-soft, legacy-черты
никогда не разбирались. Фикс: datetime → unix-секунды через `.timestamp()`.
"""
import datetime
import time

import pytest

from services import bot_persona, mca_events, mca_gates
from services import mca_self_model as sm
from services.database import DatabaseService

AGENT = "agent-uuid-fixed"
CHAT = -100500


def async_returns(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


class _RowsConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, sql, *args):
        if "persona_traits" in sql:
            return self._rows
        return []


class _RowsPool:
    def __init__(self, rows):
        self._conn = _RowsConn(rows)

    def acquire(self):
        pool = self

        class _CM:
            async def __aenter__(self):
                return pool._conn

            async def __aexit__(self, *exc):
                return False
        return _CM()


@pytest.fixture(autouse=True)
def _clean_events():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


@pytest.fixture
def events(monkeypatch):
    recorded: list = []

    def _fake(name, **kw):
        recorded.append((name, kw))
        return {"event_name": name}

    monkeypatch.setattr(mca_events, "emit_mca_event", _fake)
    return recorded


@pytest.mark.asyncio
async def test_legacy_parse_accepts_pg_timestamptz_datetime(
        tmp_path, monkeypatch, events):
    """created_at = datetime (timestamptz через asyncpg) → наблюдение
    разбирается, observed_at = int(dt.timestamp()); рядом числовая строка —
    прежнее поведение (числа) не сломано."""
    d = DatabaseService(str(tmp_path / "mca18_ts.db"))
    await d.initialize()
    try:
        await d.rebind_self_identity(bot_user_id=4242, note="test")
        await d.db.execute(
            "UPDATE mca_self_identity SET agent_id = ? WHERE id = true",
            (AGENT,))
        await d.db.commit()

        dt = datetime.datetime(2026, 10, 6, 12, 0, 0,
                               tzinfo=datetime.timezone.utc)
        pool = _RowsPool([
            {"id": 101, "chat_id": None, "trait": "любит точность",
             "source": "deep_sleep", "created_at": dt},
            {"id": 102, "chat_id": CHAT, "trait": "отвечает с иронией",
             "source": "deep_sleep", "created_at": 1_700_000_100},
        ])
        monkeypatch.setattr(bot_persona, "_persona_pool", lambda: pool)
        monkeypatch.setattr(mca_gates, "legacy_traits_migration_enabled",
                            lambda: True)
        monkeypatch.setattr(sm, "_owner_core_conflict",
                            async_returns(None))

        stats = await sm.run_legacy_traits_parse(d)
        assert stats["status"] == "ok"
        assert stats["parsed"] == 2

        cur = await d.db.execute(
            "SELECT legacy_ref, observed_at FROM mca_trait_observations "
            "ORDER BY legacy_ref")
        rows = {r["legacy_ref"]: r["observed_at"]
                for r in await cur.fetchall()}
        assert rows[101] == int(dt.timestamp())   # datetime → unix-секунды
        assert rows[102] == 1_700_000_100         # числа — без изменений
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_legacy_parse_none_created_at_falls_back_to_now(
        tmp_path, monkeypatch, events):
    """created_at IS NULL → fallback `time.time()` (честный unknown-момент),
    TypeError не возникает."""
    d = DatabaseService(str(tmp_path / "mca18_ts2.db"))
    await d.initialize()
    try:
        await d.rebind_self_identity(bot_user_id=4242, note="test")
        await d.db.execute(
            "UPDATE mca_self_identity SET agent_id = ? WHERE id = true",
            (AGENT,))
        await d.db.commit()

        pool = _RowsPool([
            {"id": 201, "chat_id": CHAT, "trait": "шутит про грибы",
             "source": "deep_sleep", "created_at": None},
        ])
        monkeypatch.setattr(bot_persona, "_persona_pool", lambda: pool)
        monkeypatch.setattr(mca_gates, "legacy_traits_migration_enabled",
                            lambda: True)
        monkeypatch.setattr(sm, "_owner_core_conflict", async_returns(None))

        before = int(time.time())
        stats = await sm.run_legacy_traits_parse(d)
        assert stats["status"] == "ok" and stats["parsed"] == 1
        cur = await d.db.execute(
            "SELECT observed_at FROM mca_trait_observations "
            "WHERE legacy_ref = 201")
        row = await cur.fetchone()
        assert before - 5 <= row["observed_at"] <= time.time() + 5
    finally:
        await d.close()
