"""Epic 85 (T-615/T-642, фаза 5) — smoke тест bot.main(): один event loop,
корректный старт/стоп без зависших тасок (SIGTERM-flow, graceful shutdown).

Всё сетевое замокано: polling-таска, uvicorn.Server, on_startup/on_shutdown,
ConfigCache — фейк (PG down, R6). Проверяем: main() завершается чисто,
on_shutdown вызван ровно один раз, polling-таска отменена, hot-кэш установлен.
"""
import asyncio
import os
import types

import pytest

from unittest.mock import AsyncMock


class _FakeCache:
    def __init__(self):
        self.pg_available = False
        self.is_initialized = False
        self._pg = types.SimpleNamespace(pool=None, close=AsyncMock())
        self.init_calls = 0
        self.closed = False

    async def init(self):
        self.init_calls += 1
        self.is_initialized = True

    def get(self, key, default=None):
        return default

    async def close(self):
        self.closed = True

    @property
    def pg(self):
        return self._pg


class _FakeServer:
    def __init__(self, delay=0.05):
        self.delay = delay
        self.should_exit = False

    async def serve(self):
        await asyncio.sleep(self.delay)


class _ShutdownAwareServer:
    """F1: сервер, который РЕАЛЬНО завершает serve() только при should_exit
    (как uvicorn): если dev-stop не выставит should_exit — тест зависнет."""

    def __init__(self):
        self.should_exit = False

    async def serve(self):
        while not self.should_exit:
            await asyncio.sleep(0.01)


@pytest.fixture
def bot_module(monkeypatch):
    import importlib
    import sys

    import config.settings as settings_mod

    monkeypatch.setenv("API_TOKEN", "123456:TEST_TOKEN_FOR_MAIN_FLOW_ABCDE")
    monkeypatch.delenv("LOGTAIL_SOURCE_TOKEN", raising=False)
    # settings — снапшот env на момент импорта: при совместном прогоне модуль
    # уже в кэше с пустым токеном → пересоздаём Settings (reload-паттерн
    # test_settings_helpers) и переимпортируем bot начисто.
    sys.modules.pop("bot", None)
    importlib.reload(settings_mod)
    import bot
    return bot


@pytest.mark.asyncio
async def test_main_start_stop_clean(bot_module, monkeypatch):
    bot = bot_module
    cache = _FakeCache()
    shutdown_calls = []

    async def fake_on_startup():
        pass

    async def fake_on_shutdown():
        shutdown_calls.append(1)

    async def fake_polling(*a, **kw):
        await asyncio.sleep(0.2)   # «живая» polling-таска, затем завершается

    monkeypatch.setattr(bot, "ConfigCache",
                        lambda **kw: cache)
    monkeypatch.setattr(bot, "on_startup", fake_on_startup)
    monkeypatch.setattr(bot, "on_shutdown", fake_on_shutdown)
    monkeypatch.setattr(bot.dp, "start_polling", fake_polling)
    monkeypatch.setattr(
        bot, "create_app",
        lambda cache_obj, control=None: object())
    monkeypatch.setattr(
        bot, "uvicorn",
        types.SimpleNamespace(Server=lambda cfg: _FakeServer(0.05),
                              Config=lambda *a, **kw: None))

    await asyncio.wait_for(bot.main(), timeout=5.0)

    assert cache.init_calls == 1          # кэш инициализирован (R6-режим)
    assert cache.closed is True           # PG-пул закрыт ровно один раз
    assert shutdown_calls == [1]          # on_shutdown ровно один раз
    assert bot.status.state == "stopped"  # polling-таска завершена штатно

    # hot-кэш сброшен после теста
    from services import hot_config
    hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_main_polling_error_state(bot_module, monkeypatch):
    """polling упал с исключением → state=polling_error, main() не завис."""
    bot = bot_module
    cache = _FakeCache()

    async def fake_polling(*a, **kw):
        await asyncio.sleep(0.02)
        raise RuntimeError("network exploded")

    monkeypatch.setattr(bot, "ConfigCache", lambda **kw: cache)
    monkeypatch.setattr(bot, "on_startup", AsyncMock())
    monkeypatch.setattr(bot, "on_shutdown", AsyncMock())
    monkeypatch.setattr(bot.dp, "start_polling", fake_polling)
    monkeypatch.setattr(bot, "create_app",
                        lambda cache_obj, control=None: object())
    monkeypatch.setattr(
        bot, "uvicorn",
        types.SimpleNamespace(Server=lambda cfg: _FakeServer(0.15),
                              Config=lambda *a, **kw: None))

    await asyncio.wait_for(bot.main(), timeout=5.0)
    assert bot.status.state == "polling_error"


@pytest.mark.asyncio
async def test_dev_stop_actually_stops_bot(bot_module, monkeypatch):
    """F1: dev restart/stop ДОЛЖЕН останавливать и uvicorn, и polling.
    Fake-server завершается ТОЛЬКО по should_exit — без фикса тест завис бы
    и упал по таймауту. ControlService перехватывается при создании, затем
    «извне» (как через /api/control/stop) вызывается request('stop')."""
    bot = bot_module
    cache = _FakeCache()
    created_controls = []
    shutdown_calls = []

    class _CapturingControl(bot.ControlService):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created_controls.append(self)

    async def fake_polling(*a, **kw):
        while True:
            await asyncio.sleep(1)

    async def fake_on_shutdown():
        shutdown_calls.append(1)

    monkeypatch.setattr(bot, "ConfigCache", lambda **kw: cache)
    monkeypatch.setattr(bot, "ControlService", _CapturingControl)
    monkeypatch.setattr(bot, "on_startup", AsyncMock())
    monkeypatch.setattr(bot, "on_shutdown", fake_on_shutdown)
    monkeypatch.setattr(bot.dp, "start_polling", fake_polling)
    monkeypatch.setattr(bot, "create_app",
                        lambda cache_obj, control=None: object())
    monkeypatch.setattr(
        bot, "uvicorn",
        types.SimpleNamespace(Server=lambda cfg: _ShutdownAwareServer(),
                              Config=lambda *a, **kw: None))

    main_task = asyncio.create_task(bot.main())
    await asyncio.sleep(0.2)
    assert created_controls, "ControlService не создан внутри main"
    assert bot.status.state == "polling"

    # «запрос через API»: dev stop → request_shutdown → stop_event +
    # server.should_exit → serve() завершается → main() выходит чисто
    await created_controls[0].request("stop", by=1)
    await asyncio.wait_for(main_task, timeout=5.0)

    assert shutdown_calls == [1]          # on_shutdown ровно один раз
    assert cache.closed is True
    assert bot.status.state == "stopped"
