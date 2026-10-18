# -*- coding: utf-8 -*-
"""Scratch-стенд для Browser Use: реальный web/-кандидат + /api-стабы harness'а.

Нужен потому, что Playwright-харнесс стабит /api на уровне route, а обычному
браузеру нужен HTTP-ответ. Стабы переиспользуются как есть:
tests.ui_p0a_ux_speech_compact_e2e.payload_for (speech-раздел) и
tools.ui_round1025_matrix._stub_for (остальные разделы MiniApp).

Запуск: python serve_gridfix.py <webroot> <port>
"""
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

REPO = r"C:\Code\Python\adminbot"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))
sys.path.insert(0, os.path.join(REPO, "tools"))
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402
import tests.ui_p0a_ux_speech_compact_e2e as E  # noqa: E402

WEBROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "web"))
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8899


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):  # noqa: N802
        p = path.split("?")[0]
        if p.startswith("/static/"):
            rel = "static/" + p[len("/static/"):]
        elif p.startswith("/web/"):
            rel = p[len("/web/"):]
        elif p in ("/", "", "/index.html"):
            rel = "index.html"
        else:
            rel = p.lstrip("/")
        return os.path.join(WEBROOT, rel.replace("/", os.sep))

    def _json(self, obj, status=200):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _chat_key(self):
        return self.headers.get("x-chat-id") or "global"

    def do_GET(self):  # noqa: N802
        p = self.path.split("?")[0]
        if p.startswith("/api/"):
            chat = self._chat_key()
            if "/api/speech/" in p:
                name = p.rsplit("/api/speech/", 1)[1]
                return self._json(E.payload_for(name, chat))
            if p.endswith("/api/access/me") or p.endswith("/api/access/chats"):
                return self._json(E.payload_for(p.rsplit("/api/", 1)[-1], chat))
            return self._json(M._stub_for(self.path))
        return SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        return self._json({"ok": True})

    def log_message(self, *args):  # noqa: A003
        pass


if __name__ == "__main__":
    print("webroot=%s port=%d" % (WEBROOT, PORT), flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
