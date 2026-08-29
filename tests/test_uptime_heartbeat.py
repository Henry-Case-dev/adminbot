"""Epic 85 (T-630, 84.11.3) — тесты UptimeHeartbeatService (мок пула).

DoD 84.10 п.9: heartbeat пишет строку 'up' в uptime_events; автоочистка по
UPTIME_EVENTS_RETENTION_HOURS; PG down → WARNING, бот жив (R6, без raise).
"""
import logging

import pytest

from services.uptime_heartbeat import UptimeHeartbeatService


class _FakeConn:
    def __init__(self, fail=False):
        self.queries = []
        self._fail = fail

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        if self._fail:
            raise ConnectionError("pg down")

    async def fetch(self, sql, *args):
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
    def __init__(self, conn=None):
        self.pool = _FakePool(conn) if conn is not None else None


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_inserts_up(self):
        conn = _FakeConn()
        svc = UptimeHeartbeatService(pg=_FakePg(conn))
        await svc._heartbeat()
        assert conn.queries == [
            ("INSERT INTO uptime_events (status) VALUES ('up')", ())]

    @pytest.mark.asyncio
    async def test_heartbeat_retries_and_does_not_raise(self, caplog):
        conn = _FakeConn(fail=True)
        svc = UptimeHeartbeatService(pg=_FakePg(conn))
        with caplog.at_level(logging.WARNING):
            await svc._heartbeat()          # 3 ретрая + WARNING, БЕЗ raise
        assert len(conn.queries) == 3
        assert any("R6" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_cleanup_uses_retention_hours(self):
        conn = _FakeConn()
        svc = UptimeHeartbeatService(pg=_FakePg(conn), retention_hours=48)
        await svc._cleanup()
        sql, args = conn.queries[0]
        assert "DELETE FROM uptime_events" in sql
        assert args == (48,)

    @pytest.mark.asyncio
    async def test_cleanup_pg_down_no_raise(self, caplog):
        conn = _FakeConn(fail=True)
        svc = UptimeHeartbeatService(pg=_FakePg(conn))
        with caplog.at_level(logging.WARNING):
            await svc._cleanup()
        assert any("R6" in r.message for r in caplog.records)

    def test_retention_from_env(self, monkeypatch):
        monkeypatch.setenv("UPTIME_EVENTS_RETENTION_HOURS", "120")
        assert UptimeHeartbeatService(pg=_FakePg()).retention_hours == 120
        monkeypatch.setenv("UPTIME_EVENTS_RETENTION_HOURS", "мусор")
        assert UptimeHeartbeatService(pg=_FakePg()).retention_hours == 72

    def test_start_without_pg_logs_warning(self, caplog):
        svc = UptimeHeartbeatService(pg=_FakePg())   # pool None
        with caplog.at_level(logging.WARNING):
            svc.start()
        assert any("не запущен" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_start_and_shutdown(self):
        conn = _FakeConn()
        svc = UptimeHeartbeatService(pg=_FakePg(conn), heartbeat_seconds=5)
        svc.start()
        assert svc._running
        await svc.shutdown()
        assert not svc._running
