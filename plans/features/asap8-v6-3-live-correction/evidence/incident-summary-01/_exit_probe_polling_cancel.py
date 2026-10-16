"""INC-FIX-RESIDUAL probe #1 (scratch, not production code).

Вопрос: если отменить `asyncio.create_task(dp.start_polling(bot,
handle_signals=False))` так же, как это делает `bot.py` на остановке, —
остаются ли «осиротевшие» внутренние таски aiogram и мешают ли они выходу
процесса (asyncio.run cleanup)?

Запуск: .venv\\Scripts\\python.exe OPENCODE_WORKFLOW_SCRATCH/inc01_exit/_probe_polling_cancel.py
Печатает: время до возврата main(), список оставшихся тасок/тредов, и
(если процесс завис) faulthandler-дамп всех стеков через N секунд.
"""
from __future__ import annotations

import asyncio
import faulthandler
import json
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

T0 = time.monotonic()


class _Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, obj) -> None:
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("content-length") or 0)
        if n:
            self.rfile.read(n)
        method = self.path.rsplit("/", 1)[-1]
        if method == "getUpdates":
            time.sleep(0.3)                       # эмуляция long-poll
            self._send({"ok": True, "result": []})
        elif method == "getMe":
            self._send({"ok": True, "result": {
                "id": 1, "is_bot": True, "first_name": "Probe",
                "username": "probe_bot"}})
        elif method == "deleteWebhook":
            self._send({"ok": True, "result": True})
        else:
            self._send({"ok": True, "result": True})

    def do_GET(self) -> None:  # noqa: N802
        self.do_POST()

    def log_message(self, *a) -> None:
        pass


def start_stub() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True,
                     name="stub-botapi").start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def dump_state(tag: str) -> None:
    print(f"--- {tag}: tasks/threads ---", flush=True)
    for t in asyncio.all_tasks():
        print(f"    task {t.get_name()} done={t.done()} coro={t.get_coro()}",
              flush=True)
    for th in threading.enumerate():
        print(f"    thread {th.name} daemon={th.daemon} alive={th.is_alive()}",
              flush=True)


async def main() -> None:
    from aiogram import Bot, Dispatcher
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer
    from aiogram.fsm.storage.memory import MemoryStorage

    srv, base = start_stub()
    bot = Bot(token="123456:PROBE",
              session=AiohttpSession(api=TelegramAPIServer.from_base(base)))
    dp = Dispatcher(storage=MemoryStorage())

    polling = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    await asyncio.sleep(1.5)
    print(f"[probe] polling running={not polling.done()} t={time.monotonic()-T0:.2f}",
          flush=True)
    dump_state("before cancel")

    t_cancel = time.monotonic()
    polling.cancel()
    try:
        await polling
    except asyncio.CancelledError:
        print("[probe] outer polling task cancelled", flush=True)
    print(f"[probe] await polling returned after {time.monotonic()-t_cancel:.3f}s",
          flush=True)
    dump_state("after await polling")

    # Сколько ждём «осиротевшие» таски, если их не трогать
    await asyncio.sleep(2.0)
    print(f"[probe] main() returns at t={time.monotonic()-T0:.2f}", flush=True)
    srv.shutdown()


if __name__ == "__main__":
    faulthandler.dump_traceback_later(15, repeat=True, exit=False)
    try:
        asyncio.run(main())
    finally:
        print(f"[probe] asyncio.run() finished at t={time.monotonic()-T0:.2f}",
              flush=True)
        print(f"[probe] threads at exit: "
              f"{[(t.name, t.daemon) for t in threading.enumerate()]}",
              flush=True)
    print(f"[probe] END t={time.monotonic()-T0:.2f}", flush=True)
