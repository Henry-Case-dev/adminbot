"""Сателлит теста `tests/test_summary_inc01_exit.py` (не pytest-модуль — имя с
подчёркиванием, коллекция его не берёт). Запускается САБПРОЦЕССОМ: настоящий
`bot.main()` + настоящий SIGTERM; перед запуском открыт реальный SQLite
`DatabaseService` (как в `on_startup` прода) и зарегистрирован в lore_runtime.

Смысл: единственный способ проверить контракт «процесс ВЫХОДИТ сам» — живой
процесс (внутрипроцессная проверка `main()` этот дефект не видит: зависание
происходит в `threading._shutdown()` уже ПОСЛЕ возврата из `asyncio.run`).

Печатает маркеры и время. Env-переключатель `INC01_CHILD_NO_CLOSERS=1`
выключает новые closer'ы остановки — RED-репро пред-фиксового поведения
(процесс не выходит, тест это ловит по таймауту). Это тест-поддержка, не
продакшн-ручка.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
import types
from unittest.mock import AsyncMock

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)

T0 = time.monotonic()
SIGTERM_AFTER_UP = float(os.environ.get("INC01_CHILD_SIGTERM_AFTER_UP", "0.5"))


def _t() -> str:
    return f"{time.monotonic() - T0:.2f}"


class _FakeCache:
    def __init__(self):
        self._pg = types.SimpleNamespace(pool=None, close=AsyncMock())
        self.closed = False

    async def init(self):
        pass

    def get(self, key, default=None):
        return default

    async def close(self):
        self.closed = True

    @property
    def pg(self):
        return self._pg


class _ShutdownAwareServer:
    """Сервер, завершающий `serve()` только по `should_exit` (как uvicorn)."""

    def __init__(self):
        self.should_exit = False

    async def serve(self):
        while not self.should_exit:
            await asyncio.sleep(0.01)


async def _run() -> int:
    import bot

    # Инфраструктура `main()`: сеть/БД-миграции не поднимаем (предмет — выход
    # процесса, а не старт сервинга). SQLite при этом РЕАЛЬНЫЙ (см. ниже).
    os.environ["WEB_PORT"] = "0"
    bot.ConfigCache = lambda **kw: _FakeCache()
    bot.on_startup = AsyncMock()

    async def fake_polling(*args, **kwargs):
        while True:
            await asyncio.sleep(0.05)

    bot.dp.start_polling = fake_polling
    bot.uvicorn = types.SimpleNamespace(
        Server=lambda cfg: _ShutdownAwareServer(),
        Config=lambda *a, **kw: None)
    bot.ControlService.flag_file_exists = classmethod(lambda cls, *a, **k: False)
    if os.environ.get("INC01_CHILD_NO_CLOSERS") == "1":
        async def _noop_closer():
            return None

        async def _noop_leftovers():
            return 0

        bot._close_runtime_sqlite_db = _noop_closer
        bot._close_leftover_sqlite_connections = _noop_leftovers
        print("[child] closer'ы остановки ОТКЛЮЧЕНЫ (RED-репро)", flush=True)

    from services.database import DatabaseService

    db = DatabaseService(os.environ["DB_PATH"])
    # Как в `on_startup` прода: владелец соединения — ref модуля `bot`
    # (его закрывает `_close_runtime_sqlite_db` из `on_shutdown`).
    bot._runtime_sqlite_db = db
    await db.initialize()               # реальный aiosqlite-коннект (как on_startup)
    print(f"[child] {_t()} runtime sqlite открыт (как в on_startup)", flush=True)

    main_task = asyncio.create_task(bot.main())
    for _ in range(200):
        await asyncio.sleep(0.05)
        if bot.status.state == "polling":
            break
    else:
        raise AssertionError("main() не поднялся (polling не стартовал)")
    await asyncio.sleep(SIGTERM_AFTER_UP)

    t_sig = time.monotonic()
    print(f"[child] {_t()} raise SIGTERM", flush=True)
    signal.raise_signal(signal.SIGTERM)
    await asyncio.wait_for(main_task, timeout=float(
        os.environ.get("INC01_CHILD_MAIN_BUDGET", "30")))
    print(f"[child] SIGTERM→main() returned: "
          f"{time.monotonic() - t_sig:.2f}s", flush=True)
    print(f"[child] {_t()} sqlite running={getattr(db.db, '_running', None)} "
          f"closed={getattr(db.db, '_connection', 'n/a') is None}", flush=True)
    print(f"[child] {_t()} bot.main() returned", flush=True)
    return 0


def main() -> int:
    rc = asyncio.run(_run())
    # Если процесс дойдёт до этой строки, но не выйдет — виноват не loop, а
    # не-демон-thread (aiosqlite worker): см. заголовок теста.
    print(f"[child] {_t()} asyncio.run() finished — выходим", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
