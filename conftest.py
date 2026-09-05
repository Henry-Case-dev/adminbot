"""Корневой conftest (pytest из корня проекта подхватывает его первым).

1. Изоляция .env (тесты/CI): ADMINBOT_SKIP_DOTENV=1 ставится ПЕРВОЙ
   строкой — до любых импортов проекта, поэтому config.settings пропускает
   load_dotenv() и тестовый процесс не видит боевой .env. Тесты, которые
   ЯВНО выставляют env (monkeypatch.setenv/os.environ до импорта модуля),
   работают как раньше — гвард смотрит только на флаг.
2. Анти-зависание aiosqlite: тесты открывают raw-соединения
   (aiosqlite.connect) и не всегда закрывают их на failure-путях. Каждое
   такое соединение держит свой фоновый тред — если не закрыть, интерпретатор
   не выходит (процесс висит после summary). Обёртка трекает открытые
   соединения; pytest_sessionfinish закрывает оставшиеся хвосты.
"""
import os

os.environ["ADMINBOT_SKIP_DOTENV"] = "1"

import asyncio  # noqa: E402
import sys  # noqa: E402

import aiosqlite  # noqa: E402

_open_aiosqlite: set = set()
_orig_connect = aiosqlite.connect


async def _tracked_connect(*args, **kwargs):
    conn = await _orig_connect(*args, **kwargs)
    _open_aiosqlite.add(conn)
    orig_close = conn.close

    async def _close(*close_args, **close_kwargs):
        try:
            await orig_close(*close_args, **close_kwargs)
        finally:
            _open_aiosqlite.discard(conn)

    conn.close = _close
    return conn


aiosqlite.connect = _tracked_connect


def pytest_sessionfinish(session, exitstatus):
    """Закрыть незакрытые aiosqlite-соединения (иначе их фоновые треды
    не дают процессу завершиться). asyncio.run создаёт СВЕЖИЙ цикл — не
    зависит от того, закрыт ли уже session-scoped loop."""
    leftovers = list(_open_aiosqlite)
    if not leftovers:
        return
    closed = 0
    for conn in leftovers:
        try:
            asyncio.run(conn.close())
            closed += 1
        except Exception:
            pass
        finally:
            _open_aiosqlite.discard(conn)
    if closed:
        print(f"\nWARNING: closed {closed} leaked aiosqlite connection(s)",
              file=sys.stderr, flush=True)
