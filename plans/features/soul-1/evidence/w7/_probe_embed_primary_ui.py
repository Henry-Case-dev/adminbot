"""COMMIT-FS/W7: реальный рендер UI-блока SOUL-13.4 (primary-слот).

Стенд: настоящие `web/index.html` + `web/app.js` + CSS через http-сервер
харнесса (`ui_round1025_matrix._Handler`), мок SDK и мок API. Единственная
подмена — ответ `GET /api/memory/embeddings`: его форма снята 1:1 с
`provider_panel()` (`services/embedding_control_plane.py:455-497`) для двух
состояний:

  * scenario=absent  — primary-слот пуст при живых fallback-ключах:
      primary_present=false, primary_source=absent, primary_state=primary_absent,
      primary_warn=true, primary_hint=_PRIMARY_HINT_RU;
  * scenario=hot     — primary из hot-конфига:
      primary_present=true, primary_source=hot, primary_state=primary_from_hot,
      primary_warn=false, primary_hint="".

Что проверяется в браузере (реальный рендер):
  1. `[data-embeddings-primary-warn]` видим в absent-сценарии и содержит
     «primary-слот пуст», число ключей, источник `absent` и hint;
  2. `[data-embeddings-primary-state]` видим в hot-сценарии и называет
     hot-конфиг (`keys.embedding_api_key`);
  3. в обоих сценариях в блоке нет значений ключей/токенов/initData
     (скан секрет-маркеров);
  4. блок занимает ненулевой rect и не пересекает правый край (390px).

Это мок-канал (SDK/API стенда): он доказывает UI-wiring (состояние из панели
доходит до владельца понятным текстом), а не состояние реального прода.

Запуск: py -3 evidence/w7/_probe_embed_primary_ui.py [--port 8831] [--scenario absent|hot]
"""
import argparse
import json
import sys
import threading
import time
from http.server import ThreadingHTTPServer

sys.path.insert(0, r"C:\Code\Python\adminbot\tools")
import ui_round1025_matrix as M          # noqa: E402
import ui_asap8_w2_fullscreen_e2e as FH  # noqa: E402

PRIMARY_HINT_RU = (
    "Задайте EMBEDDING_API_KEY (env) либо hot-ключ "
    "keys.embedding_api_key — hot подхватывается без рестарта; "
    "ключи по группам: keys.embedding_quota_group_labels"
)

_SDK = FH.mock_sdk_js(dict(
    platform="tdesktop", hasBoolean=True, isFullscreen=False,
    stableHeight=700, viewportHeight=768,
    safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
    contentSafeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
)).encode("utf-8")


def _rotation(scenario: str) -> dict:
    base = {
        "status": "grouped", "keys": 2, "groups": ["g-fallback-1", "g-fallback-2"],
        "degenerate": False, "warn": False, "reason": "",
        "hint": "",
    }
    if scenario == "absent":
        base.update({
            "primary_present": False, "primary_source": "absent",
            "primary_state": "primary_absent", "degraded": True,
            "primary_warn": True, "primary_hint": PRIMARY_HINT_RU,
        })
    else:
        base.update({
            "primary_present": True, "primary_source": "hot",
            "primary_state": "primary_from_hot", "degraded": False,
            "primary_warn": False, "primary_hint": "",
        })
    return base


def payload(scenario: str) -> dict:
    return {
        "provider": {
            "provider": "gemini", "model": "gemini-embedding-001",
            "credentials": 2, "quota_group_display": "g-fallback-1, g-fallback-2",
            "rotation": _rotation(scenario),
            "concurrency": 4, "batch_size": 32, "rate_limits_10m": 0,
            "credential_rows": [],
        },
        "vector_memory": {},
    }


def make_handler(scenario: str):
    class Handler(M._Handler):
        def _json(self, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if "vendor/telegram-web-app.js" in self.path:
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Content-Length", str(len(_SDK)))
                self.end_headers()
                self.wfile.write(_SDK)
                return
            p = self.path.split("?")[0]
            if p.endswith("/api/me"):
                return self._json(FH.ME)
            if p.endswith("/api/memory/embeddings"):
                return self._json(payload(Handler.scenario))
            if "/api/" in self.path:
                return self._json(M._stub_for(self.path))
            return M._Handler.do_GET(self)

    Handler.scenario = scenario
    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8831)
    ap.add_argument("--scenario", choices=["absent", "hot"], default="absent")
    a = ap.parse_args()
    httpd = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.scenario))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print("[embed-ui] http://127.0.0.1:%d/web/index.html#/oversight (scenario=%s)"
          % (a.port, a.scenario))
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
