"""INC-FIX-RESIDUAL — дочерний процесс полного стека (scratch).

Запускается родителем (`_probe_full_stack.py`) с env:
  ADMINBOT_SKIP_DOTENV=1, API_TOKEN, DOWNLOAD_ENABLED=1,
  LOCAL_BOT_API_URL=http://127.0.0.1:<stub>, DB_PATH, WEB_PORT,
  POSTGRES_DSN="" (PG выключен), SENTRY_DSN удалён,
  LOGTAIL_SOURCE_TOKEN/BETTERSTACK_HOST по выбору, PROBE_SIGTERM_AFTER.

Поднимает НАСТОЯЩИЙ `bot.main()` (реальный uvicorn, реальные сервисы
on_startup, реальный aiogram-polling в локальный stub Bot API), затем шлёт
процессу настоящий SIGTERM и печатает, что осталось в loop'е/тредах.
"""
from __future__ import annotations

import asyncio
import faulthandler
import os
import signal
import sys
import threading
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
while not os.path.exists(os.path.join(REPO, "bot.py")):
    parent = os.path.dirname(REPO)
    if parent == REPO:
        raise RuntimeError("repo root not found")
    REPO = parent
sys.path.insert(0, REPO)

T0 = time.monotonic()


def _t() -> str:
    return f"{time.monotonic() - T0:.2f}s"


def _watchdog() -> None:
    delay = float(os.environ.get("PROBE_SIGTERM_AFTER", "12"))
    time.sleep(delay)
    print(f"[child] {_t()} raise SIGTERM", flush=True)
    signal.raise_signal(signal.SIGTERM)


def _dump(tag: str) -> None:
    print(f"[child] {_t()} --- {tag} ---", flush=True)
    try:
        tasks = asyncio.all_tasks()
    except RuntimeError:
        tasks = []
    for t in tasks:
        print(f"[child]   TASK {t.get_name()} done={t.done()} "
              f"coro={t.get_coro()}", flush=True)
    for th in threading.enumerate():
        print(f"[child]   THREAD {th.name} daemon={th.daemon}", flush=True)


_SQLITE_CONNS: list[tuple[object, str]] = []


def _patch_aiosqlite() -> None:
    """Записать все aiosqlite-соединения (кто открыл) — чтобы после остановки
    показать, какие из них остались ОТКРЫТЫМИ (их non-daemon worker-thread и
    держит процесс на `threading._shutdown`)."""
    import traceback

    import aiosqlite

    orig = aiosqlite.connect

    def tracked(*a, **kw):
        coro = orig(*a, **kw)

        async def wrapper():
            conn = await coro
            stack = [f"  {f.filename}:{f.lineno} {f.name}"
                     for f in traceback.extract_stack()[:-1]
                     if "/aiosqlite/" not in f.filename
                     and "\\aiosqlite\\" not in f.filename][-4:]
            _SQLITE_CONNS.append((conn, "\n".join(stack)))
            return conn
        return wrapper()

    aiosqlite.connect = tracked


def main() -> int:
    _patch_aiosqlite()
    import bot  # noqa: F401  (реальный модуль, реальный logging/Bot)

    if os.environ.get("INC01_CHILD_NO_CLOSERS") == "1":
        # RED-репро пред-фиксового поведения: closer'ы остановки выключены
        # (до INC-FIX-RESIDUAL runtime-SQLite не закрывал никто).
        async def _noop_closer() -> None:
            return None

        bot._close_runtime_sqlite_db = _noop_closer
        print("[child] closer остановки ОТКЛЮЧЁН (RED-репро)", flush=True)

    async def wrapped() -> None:
        try:
            await bot.main()
        finally:
            print(f"[child] {_t()} bot.main() RETURNED", flush=True)
            _dump("after main()")
            for i, (conn, where) in enumerate(_SQLITE_CONNS):
                th = getattr(conn, "_thread", None)
                print(f"[child]   SQLITE#{i} running={conn._running} "
                      f"thread_alive={th.is_alive() if th else None} "
                      f"daemon={th.daemon if th else None}", flush=True)
                print(f"[child]   SQLITE#{i} opened_at:\n{where}", flush=True)

    faulthandler.dump_traceback_later(
        int(os.environ.get("PROBE_DUMP_AFTER", "25")), repeat=True, exit=False)
    threading.Thread(target=_watchdog, name="probe-watchdog",
                     daemon=True).start()
    asyncio.run(wrapped())
    print(f"[child] {_t()} asyncio.run() finished | threads="
          f"{[(t.name, t.daemon) for t in threading.enumerate()]}", flush=True)
    print(f"[child] {_t()} END-OF-SCRIPT", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
