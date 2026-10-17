"""W7: постоянный стенд для MCP-браузеров (Playwright MCP / Browser Use).

Поднимает http-сервер харнесса на 127.0.0.1:8820 и блокируется.
Мок SDK — Telegram Desktop (кнопка ⛶ скрыта по причине) — именно тот кейс,
который меняет W7 (объяснение владельцу).
"""
import json
import sys
import threading
import time
from http.server import ThreadingHTTPServer

sys.path.insert(0, r"C:\Code\Python\adminbot\tools")
import ui_round1025_matrix as M          # noqa: E402
import ui_asap8_w2_fullscreen_e2e as FH  # noqa: E402

PORT = 8820

TDESKTOP = dict(platform="tdesktop", hasBoolean=True, isFullscreen=False,
                stableHeight=700, viewportHeight=768,
                safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
                contentSafeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0})

_mock_js = FH.mock_sdk_js(TDESKTOP).encode("utf-8")


class Handler(M._Handler):
    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if "vendor/telegram-web-app.js" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(_mock_js)))
            self.end_headers()
            self.wfile.write(_mock_js)
            return
        if self.path.split("?")[0].endswith("/api/me"):
            return self._json(FH.ME)
        if "/api/" in self.path:
            return self._json(M._stub_for(self.path))
        return M._Handler.do_GET(self)


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print("[w7-serve] http://127.0.0.1:%d/#/" % PORT)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
