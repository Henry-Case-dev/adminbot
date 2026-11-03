# -*- coding: utf-8 -*-
"""HTTP-стенд PVR-S4 для осмотра в РЕАЛЬНОМ Chrome (Browser Use).

Playwright-роуты в реальном браузере недоступны, поэтому статика `web/` и те же
самые /api-стабы из `tests/ui_prompt_version_card_e2e.py` отдаются по HTTP:
обработчик e2e вызывается через маленький шим `route`.

Запуск (из корня репозитория):
    py -3 plans/features/prompt-versioning-ux/evidence/pvr-s4/chrome_stand.py
    # затем открыть http://127.0.0.1:8901/ в браузере

Стенд только читает файлы `web/` и не пишет в репозиторий.
"""
import importlib.util
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))
os.chdir(REPO)

spec = importlib.util.spec_from_file_location(
    "pv_e2e", os.path.join(REPO, "tests", "ui_prompt_version_card_e2e.py"))
E = importlib.util.module_from_spec(spec)
sys.modules["pv_e2e"] = E
spec.loader.exec_module(E)

E.STATE["entries"] = E.build_entries()
HANDLER = E.make_api_handler()
PORT = int(os.environ.get("PV_STAND_PORT", "8901"))


class _Req(object):
    def __init__(self, url, method, post_data):
        self.url = url
        self.method = method
        self.post_data = post_data


class _Route(object):
    def __init__(self, url, method, post_data):
        self.request = _Req(url, method, post_data)
        self.status = 200
        self.body = b"{}"
        self.content_type = "application/json"

    def fulfill(self, status=200, content_type="application/json", body=""):
        self.status = status
        self.content_type = content_type
        self.body = body.encode("utf-8") if isinstance(body, str) else body


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, ctype, body):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self, method):
        url = "http://127.0.0.1:%d%s" % (self.server.server_address[1], self.path)
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if path.startswith("/api/"):
            route = _Route(url, method,
                           raw.decode("utf-8", "replace") if raw else "")
            HANDLER(route)
            return self._send(route.status, route.content_type, route.body)
        if path == "/static/vendor/telegram-web-app.js":
            return self._send(200, "application/javascript",
                              E.SDK_STUB.encode("utf-8"))
        if path.startswith("/static/"):
            rel = "static/" + path[len("/static/"):]
        elif path.startswith("/web/"):
            rel = path[len("/web/"):]
        elif path in ("/", "", "/index.html"):
            rel = "index.html"
        else:
            rel = path.lstrip("/")
        full = os.path.join(REPO, "web", rel.replace("/", os.sep))
        if not os.path.isfile(full):
            return self._send(404, "text/plain", b"not found")
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".png": "image/png", ".svg": "image/svg+xml",
            ".json": "application/json; charset=utf-8",
        }.get(os.path.splitext(full)[1], "application/octet-stream")
        with open(full, "rb") as fh:
            data = fh.read()
        return self._send(200, ctype, data)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")


httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
print("stand http://127.0.0.1:%d" % PORT, flush=True)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
while True:
    time.sleep(5)
