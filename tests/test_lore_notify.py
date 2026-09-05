"""Раунд 7 (chat-lore-management-v2, T-773, B3) — тесты LoreNotify (LISTEN).

B3/Q4: отдельное asyncpg-соединение (не из пула), add_listener
'lore_updated', колбэк (conn, pid, channel, payload) → task
cache.invalidate(int(payload)); кривой payload — WARNING без падения;
PG недоступен на старте/обрыв → WARNING + retry (интервал теста мал);
stop() закрывает соединение и завершает цикл. Соединение — мок-фабрика
(прецедент моков asyncpg в tests/test_pg_db.py).
"""
import asyncio
import logging

import pytest

from services.lore_notify import LoreNotify, _CHANNEL


class _FakeCache:
    """Кэш-заглушка: фиксирует invalidate(chat_id)."""

    def __init__(self):
        self.invalidated: list[int] = []

    async def invalidate(self, chat_id: int) -> None:
        self.invalidated.append(chat_id)


class _FakeNotifyConn:
    """asyncpg-соединение-заглушка для add_listener/is_closed/close."""

    def __init__(self, conn_id: int = 1):
        self.conn_id = conn_id
        self.listeners: list[tuple[str, object]] = []
        self.closed_flag = False
        self.closed_calls = 0

    async def add_listener(self, channel: str, callback) -> None:
        self.listeners.append((channel, callback))

    async def close(self) -> None:
        self.closed_flag = True
        self.closed_calls += 1

    def is_closed(self) -> bool:
        return self.closed_flag

    def publish(self, channel: str, payload: str) -> None:
        """Эмуляция NOTIFY: вызов зарегистрированных колбэков."""
        for ch, cb in list(self.listeners):
            if ch == channel:
                cb(self, 0, channel, payload)


class _FlakyConnector:
    """Фабрика соединений: первые `fail_first` попыток падают (PG down)."""

    def __init__(self, fail_first: int = 0):
        self.attempts = 0
        self.fail_first = fail_first
        self.conns: list[_FakeNotifyConn] = []

    async def __call__(self):
        self.attempts += 1
        if self.attempts <= self.fail_first:
            raise ConnectionError("pg down")
        conn = _FakeNotifyConn(self.attempts)
        self.conns.append(conn)
        return conn


async def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("условие не наступило за таймаут")
        await asyncio.sleep(0.01)


class TestListener:
    @pytest.mark.asyncio
    async def test_start_listens_and_notify_invalidates_cache(self):
        cache = _FakeCache()
        connector = _FlakyConnector()
        notify = LoreNotify(cache, dsn="postgresql://u:p@h/db",
                            retry_interval=0.05, connector=connector)
        task = asyncio.create_task(notify.start())
        try:
            await _wait_until(lambda: connector.conns)
            conn = connector.conns[0]
            await _wait_until(lambda: bool(conn.listeners))
            assert conn.listeners[0][0] == "lore_updated"
            conn.publish("lore_updated", "123")
            await _wait_until(lambda: cache.invalidated == [123])
            # payload = str(chat_id) из NOTIFY-эмита store (отрицательный id)
            conn.publish("lore_updated", "-1002661910336")
            await _wait_until(
                lambda: cache.invalidated == [123, -1002661910336])
        finally:
            await notify.stop()
            await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_bad_payload_ignored_without_crash(self, caplog):
        cache = _FakeCache()
        connector = _FlakyConnector()
        notify = LoreNotify(cache, dsn="x", retry_interval=0.05,
                            connector=connector)
        task = asyncio.create_task(notify.start())
        try:
            await _wait_until(lambda: connector.conns)
            conn = connector.conns[0]
            await _wait_until(lambda: bool(conn.listeners))
            with caplog.at_level(logging.WARNING):
                conn.publish("lore_updated", "не-число")
            await asyncio.sleep(0.05)
            assert cache.invalidated == []
            assert any("кривой payload" in r.message for r in caplog.records)
            assert not task.done()          # слушатель жив
        finally:
            await notify.stop()
            await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_cache_error_does_not_kill_listener(self):
        class _BoomCache(_FakeCache):
            async def invalidate(self, chat_id: int) -> None:
                raise RuntimeError("cache boom")

        cache = _BoomCache()
        connector = _FlakyConnector()
        notify = LoreNotify(cache, dsn="x", retry_interval=0.05,
                            connector=connector)
        task = asyncio.create_task(notify.start())
        try:
            await _wait_until(lambda: connector.conns)
            conn = connector.conns[0]
            await _wait_until(lambda: bool(conn.listeners))
            conn.publish("lore_updated", "1")   # не должно уронить слушателя
            await asyncio.sleep(0.05)
            assert not task.done()
            conn.publish("lore_updated", "2")   # слушает дальше
            await asyncio.sleep(0.05)
            assert not task.done()
        finally:
            await notify.stop()
            await asyncio.wait_for(task, timeout=2.0)


class TestRetryAndLifecycle:
    @pytest.mark.asyncio
    async def test_pg_down_on_start_retries_until_connected(self, caplog):
        cache = _FakeCache()
        connector = _FlakyConnector(fail_first=2)   # 2 отказа подряд
        notify = LoreNotify(cache, dsn="x", retry_interval=0.05,
                            connector=connector)
        task = asyncio.create_task(notify.start())
        try:
            with caplog.at_level(logging.WARNING):
                await _wait_until(lambda: connector.attempts >= 3)
                await _wait_until(lambda: connector.conns)
            assert any("LISTEN-подписка не активна" in r.message
                       for r in caplog.records)
            assert connector.conns[0].listeners   # в итоге подписан
        finally:
            await notify.stop()
            await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_connection_drop_reconnects(self):
        cache = _FakeCache()
        connector = _FlakyConnector()
        notify = LoreNotify(cache, dsn="x", retry_interval=0.05,
                            connector=connector)
        task = asyncio.create_task(notify.start())
        try:
            await _wait_until(lambda: connector.conns)
            conn1 = connector.conns[0]
            await _wait_until(lambda: bool(conn1.listeners))
            await conn1.close()             # обрыв соединения
            await _wait_until(lambda: len(connector.conns) >= 2)
            conn2 = connector.conns[-1]
            await _wait_until(lambda: bool(conn2.listeners))
            assert conn2 is not conn1
            assert not task.done()
        finally:
            await notify.stop()
            await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_stop_closes_connection(self):
        cache = _FakeCache()
        connector = _FlakyConnector()
        notify = LoreNotify(cache, dsn="x", retry_interval=0.05,
                            connector=connector)
        task = asyncio.create_task(notify.start())
        await _wait_until(lambda: connector.conns)
        conn = connector.conns[0]
        await _wait_until(lambda: bool(conn.listeners))
        await notify.stop()
        await asyncio.wait_for(task, timeout=2.0)
        assert conn.closed_flag

    @pytest.mark.asyncio
    async def test_unknown_channel_ignored(self):
        cache = _FakeCache()
        connector = _FlakyConnector()
        notify = LoreNotify(cache, dsn="x", retry_interval=0.05,
                            connector=connector)
        task = asyncio.create_task(notify.start())
        try:
            await _wait_until(lambda: connector.conns)
            conn = connector.conns[0]
            await _wait_until(lambda: bool(conn.listeners))
            conn.publish("другой_канал", "42")
            await asyncio.sleep(0.05)
            assert cache.invalidated == []
        finally:
            await notify.stop()
            await asyncio.wait_for(task, timeout=2.0)

    def test_channel_constant(self):
        assert _CHANNEL == "lore_updated"
