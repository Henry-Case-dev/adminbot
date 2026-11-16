"""M4A: локальный стенд для живой проверки (Browser Use/реальный Chromium).

Отдаёт `web/*` и перехватывает `/api/*` ТЕМИ ЖЕ стабами, что Playwright-e2e
(`tools/ui_mod_acl_m4_catalog_e2e.py`), потому что реальный браузер не умеет
Playwright route. Управление 409: GET `/__conflict/on|off`. Стенд read-only:
никаких записей, секретов и production-доступа.

Запуск: .venv/Scripts/python.exe tools/ui_mod_acl_m4_catalog_serve.py
URL: http://127.0.0.1:8796/web/index.html#/modules
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tools.ui_mod_acl_m4_catalog_e2e as e2e  # noqa: E402

PORT = int(os.environ.get("MOD_ACL_M4A_SERVE_PORT", "8796"))
CONFLICT = {"on": False}


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, rel):
        path = os.path.join(REPO, rel.replace("/", os.sep))
        if not os.path.isfile(path):
            self.send_error(404)
            return
        ctype = ("text/html" if path.endswith(".html")
                 else "application/javascript" if path.endswith(".js")
                 else "text/css" if path.endswith(".css")
                 else "application/octet-stream")
        with open(path, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        p = self.path.split("?")[0]
        if p == "/__conflict/on":
            CONFLICT["on"] = True
            return self._json({"conflict": True})
        if p == "/__conflict/off":
            CONFLICT["on"] = False
            return self._json({"conflict": False})
        if p.startswith("/api/"):
            if p == "/api/config":
                chat = bool(self.headers.get("X-Chat-Id"))
                return self._json(e2e.CONFIG_CHAT if chat
                                  else e2e.CONFIG_GLOBAL)
            return self._json(e2e._stub_for(self.path))
        if p.startswith("/static/"):
            return self._file("web/static/" + p[len("/static/"):])
        if p.startswith("/web/"):
            return self._file(p[1:])
        return self._file("web/index.html")

    def do_POST(self):  # noqa: N802
        p = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        if p.endswith("/api/config"):
            if CONFLICT["on"] and "flags.summary_enabled" in raw:
                return self._json({"detail": {
                    "code": "conflict", "applied": [],
                    "conflicting": ["flags.summary_enabled"],
                    "current_updated_at": "ts-server-2"}}, status=409)
            keys = []
            try:
                keys = [it.get("key") for it in
                        (json.loads(raw).get("items") or [])]
            except Exception:  # noqa: BLE001
                pass
            return self._json({"saved": keys, "updated_at": "ts-chat-2"})
        return self._json({"ok": True})

    def do_PUT(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        return self._json({"ok": True})

    def log_message(self, *args):  # тишина
        pass


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("M4A serve:", "http://127.0.0.1:%d/web/index.html#/modules" % PORT,
          "| conflict:", CONFLICT["on"])
    httpd.serve_forever()


if __name__ == "__main__":
    main()
