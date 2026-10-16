"""INC-FIX-RESIDUAL — родитель полностекового пробника (scratch).

1. Поднимает локальный stub Bot API (aiogram ходит в него как в Telegram).
2. Запускает `_probe_child_exit.py` (реальный `bot.main()` + реальный SIGTERM).
3. Меряет время жизни процесса после SIGTERM и печатает хвост вывода.

Запуск: .venv\\Scripts\\python.exe OPENCODE_WORKFLOW_SCRATCH/inc01_exit/_probe_full_stack.py [--betterstack]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo_root(start: str) -> str:
    """Корень репо (файл `bot.py`) — артефакт живёт в plans/…/evidence/."""
    cur = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(cur, "bot.py")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise RuntimeError("repo root not found")
        cur = parent


REPO = _repo_root(HERE)
PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")
DB = os.path.join(HERE, "probe_full_stack.db")

METHOD_LOG: list[str] = []


class _Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, obj) -> None:
        data = json.dumps(obj).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _handle(self) -> None:
        n = int(self.headers.get("content-length") or 0)
        if n:
            self.rfile.read(n)
        method = self.path.rsplit("/", 1)[-1].split("?")[0]
        METHOD_LOG.append(method)
        if method == "getUpdates":
            time.sleep(0.3)
            self._send({"ok": True, "result": []})
        elif method == "getMe":
            self._send({"ok": True, "result": {
                "id": 8802473181, "is_bot": True, "first_name": "Probe",
                "username": "probe_bot"}})
        elif method == "getWebhookInfo":
            self._send({"ok": True, "result": {"url": "", "has_custom_certificate": False,
                                               "pending_update_count": 0}})
        elif method == "deleteWebhook":
            self._send({"ok": True, "result": True})
        elif method == "getMyCommands":
            self._send({"ok": True, "result": []})
        elif method == "setMyCommands":
            self._send({"ok": True, "result": True})
        else:
            self._send({"ok": True, "result": True})

    do_POST = _handle
    do_GET = _handle

    def log_message(self, *a) -> None:
        pass


def main() -> int:
    use_betterstack = "--betterstack" in sys.argv
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True,
                     name="stub-botapi").start()
    print(f"[parent] stub Bot API on 127.0.0.1:{port}")

    if os.path.exists(DB):
        os.remove(DB)
    env = os.environ.copy()
    env.update({
        "ADMINBOT_SKIP_DOTENV": "1",
        "API_TOKEN": "123456:PROBE_TOKEN_LOCAL",
        "DOWNLOAD_ENABLED": "1",
        "LOCAL_BOT_API_URL": f"http://127.0.0.1:{port}",
        "DB_PATH": DB,
        "WEB_PORT": "8123",
        "POSTGRES_DSN": "",
        "PROBE_SIGTERM_AFTER": os.environ.get("PROBE_SIGTERM_AFTER", "12"),
        "PYTHONUNBUFFERED": "1",
    })
    env.pop("SENTRY_DSN", None)
    if use_betterstack:
        env["LOGTAIL_SOURCE_TOKEN"] = "probe-token"
        # Локальный «черный ход»: DNS-имя, которого нет → быстрый отказ
        # транспорта, но полный путь urllib/DNS.
        env["BETTERSTACK_HOST"] = "probe-betterstack.invalid"
    else:
        env.pop("LOGTAIL_SOURCE_TOKEN", None)
        env.pop("BETTERSTACK_HOST", None)

    t0 = time.monotonic()
    proc = subprocess.Popen([PY, os.path.join(HERE, "_exit_probe_child_exit.py")],
                            cwd=REPO, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    try:
        out, _ = proc.communicate(timeout=90)
        exited = True
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        exited = False
    wall = time.monotonic() - t0

    tag = "before" if env.get("INC01_CHILD_NO_CLOSERS") == "1" else "after"
    with open(os.path.join(HERE, f"_exit_fullstack_{tag}_output.txt"), "w",
              encoding="utf-8") as fh:
        fh.write(out or "")

    print(f"[parent] child exited={exited} rc={proc.returncode} wall={wall:.2f}s")
    sig_line = [ln for ln in (out or "").splitlines() if "raise SIGTERM" in ln]
    print(f"[parent] SIGTERM line: {sig_line}")
    print("[parent] tail:")
    for ln in (out or "").splitlines()[-45:]:
        print("   " + ln)
    print(f"[parent] stub methods: {sorted(set(METHOD_LOG))}")
    srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
