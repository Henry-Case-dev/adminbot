# -*- coding: utf-8 -*-
"""P0-PROD-DISK-01 — визуальная проверка порогов диска на «Статусе».

Проверяет РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css`
(локальный harness: статический сервер `tools/ui_round1025_matrix.py`,
`/api/*` — route-стабы, Telegram SDK — route-mock; НЕ live TMA).

Сценарии (существующая телеметрия `/api/status.server.disk`):
  * 92 % → crit: красная полоса + текст «освободите место», aria-live;
  * 86 % → warn: янтарная полоса + текст «место заканчивается», aria-live;
  * 50 % → ok: обычная полоса, предупреждения нет;
  * нет данных → unknown: штриховка/«нет данных», НЕ ложное «здорово».

Виды: 1280×800 (desktop) и 390×844 (mobile). Дополнительно проверяется, что
соседние блоки «Статуса» (heartbeat, CPU/RAM, бюджеты) не сломаны и нет
горизонтального переполнения.

Запуск (из корня worktree):
  .venv\\Scripts\\python.exe plans/features/p0-prod-disk-01/evidence/ui/capture_p0_disk_status_ui.py

Артефакты: этот же каталог — PNG-скриншоты + `ui-checks.json`.
TEST-LIFECYCLE: CONTRACT owner=P0-PROD-DISK-01 (видимая классификация
заполнения диска без нового мониторинга и без повышения порогов).
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
while not os.path.exists(os.path.join(ROOT, "web", "index.html")):
    _parent = os.path.dirname(ROOT)
    if _parent == ROOT:
        raise SystemExit("repo root with web/index.html not found")
    ROOT = _parent
REPO = ROOT
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
os.chdir(REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import ui_round1025_matrix as M  # noqa: E402  (сервер/стабы/TMA — reuse)

PORT = 8897
BASE = "http://127.0.0.1:%d/web/index.html" % PORT
TOTAL = 100 * 1024 ** 3  # 100 GiB — только числа, без реальных данных (R17)

SCENARIOS = [
    # (id, disk payload / None, ожидаемый уровень, подстрока текста)
    ("92", {"used": int(TOTAL * 0.92), "total": TOTAL, "percent": 92.0},
     "crit", "освободите место"),
    ("86", {"used": int(TOTAL * 0.86), "total": TOTAL, "percent": 86.0},
     "warn", "место заканчивается"),
    ("50", {"used": int(TOTAL * 0.50), "total": TOTAL, "percent": 50.0},
     "ok", ""),
    ("unknown", None, "unknown", ""),
]
VIEWPORTS = [("desktop", 1280, 800), ("mobile", 390, 844)]

PROBE = r"""
(() => {
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const box = document.querySelector('.status-disk');
  const fill = box ? box.querySelector('.ctl-progress__fill') : null;
  const bar = box ? box.querySelector('[role="progressbar"]') : null;
  const alert = box ? box.querySelector('[data-disk-alert]') : null;
  const cs = fill ? getComputedStyle(fill) : null;
  const health = document.querySelector('.status-block.status-health');
  return {
    present: !!box,
    level: box ? box.getAttribute('data-disk-level') : null,
    rowText: box ? strip(box.textContent) : '',
    alertText: alert ? strip(alert.textContent) : '',
    alertRole: alert ? alert.getAttribute('role') : null,
    alertLive: alert ? alert.getAttribute('aria-live') : null,
    alertAtomic: alert ? alert.getAttribute('aria-atomic') : null,
    barAria: bar ? bar.getAttribute('aria-label') : null,
    barState: bar ? bar.getAttribute('data-state') : null,
    barValue: bar ? bar.getAttribute('aria-valuenow') : null,
    fillBgImage: cs ? cs.backgroundImage : null,
    fillBgColor: cs ? cs.backgroundColor : null,
    alertColor: alert ? getComputedStyle(alert).color : null,
    heartbeat: !!document.querySelector('[data-status-seg="heartbeat"]'),
    serverSeg: !!document.querySelector('[data-status-seg="server"]'),
    cpuBar: !!(health && health.querySelector('[data-state]')),
    analytics: !!document.querySelector('[data-status-health-analytics]'),
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    boxRect: box ? (() => {
      const r = box.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height) };
    })() : null,
  };
})()
"""


def _status_payload(disk):
    import copy
    payload = copy.deepcopy(M.STATUS_STUB)
    if disk is None:
        payload.pop("server", None)
    else:
        payload["server"] = dict(payload.get("server") or {})
        payload["server"]["disk"] = dict(disk)
    return payload


def _start_server(httpd_cls):
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), httpd_cls)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main() -> int:
    from playwright.sync_api import sync_playwright

    failures = []
    result = {"checks": {}, "screenshots": [], "console_errors": []}

    def fail(label, msg):
        failures.append("%s: %s" % (label, msg))
        print("  FAIL %s: %s" % (label, msg))

    httpd = _start_server(M._Handler)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vid, width, height in VIEWPORTS:
            for sid, disk, expect_level, expect_text in SCENARIOS:
                label = "%s/%s" % (vid, sid)
                payload = _status_payload(disk)

                def make_handler(_payload):
                    def handler(route):
                        req = route.request
                        url = req.url.split("?")[0]
                        body = (_payload if url.endswith("/api/status")
                                else M._stub_for(req.url))
                        route.fulfill(status=200,
                                      content_type="application/json",
                                      body=json.dumps(body,
                                                      ensure_ascii=False))
                    return handler

                ctx = browser.new_context(viewport={"width": width,
                                                    "height": height},
                                          is_mobile=width <= 430,
                                          has_touch=width <= 430,
                                          reduced_motion="reduce")
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", make_handler(payload))
                ctx.route("**/static/vendor/telegram-web-app.js",
                          lambda route: route.fulfill(
                              status=200,
                              content_type="application/javascript",
                              body=M.TMA_STUB))
                page = ctx.new_page()
                errors = []
                page.on("console", lambda m, e=errors: e.append(m.text[:200])
                        if m.type == "error" else None)
                page.on("pageerror",
                        lambda exc, e=errors: e.append("pageerror: %s" % exc))
                page.goto(BASE, wait_until="load")
                page.wait_for_selector("header.header-sticky",
                                       state="visible")
                try:
                    page.wait_for_function(
                        "(lvl) => { const b = document.querySelector('.status-disk');"
                        " return b && b.getAttribute('data-disk-level') === lvl; }",
                        arg=expect_level, timeout=15000)
                except Exception as exc:  # noqa: BLE001
                    fail(label, "уровень не появился: %s" % exc)
                page.wait_for_timeout(500)
                data = page.evaluate(PROBE)
                result["checks"][label] = data
                if errors:
                    result["console_errors"].extend(
                        ["%s: %s" % (label, e) for e in errors])

                if data["level"] != expect_level:
                    fail(label, "data-disk-level=%r, ожидался %r"
                         % (data["level"], expect_level))
                if not data["present"] or not data["barAria"]:
                    fail(label, "блок диска/прогрессбар не отрисованы")
                if expect_text:
                    if expect_text not in data["alertText"]:
                        fail(label, "текст предупреждения: %r"
                             % data["alertText"])
                    if data["alertRole"] != "status" \
                            or data["alertLive"] != "polite":
                        fail(label, "предупреждение без role=status/"
                                    "aria-live: %r"
                             % (data["alertRole"], data["alertLive"]))
                    if expect_text not in (data["barAria"] or ""):
                        fail(label, "aria-label полосы не называет проблему")
                else:
                    if data["alertText"]:
                        fail(label, "лишнее предупреждение: %r"
                             % data["alertText"])

                if expect_level == "crit":
                    # bar-red: существующее правило даёт сплошной красный.
                    if "239, 68, 68" not in (data["fillBgColor"] or ""):
                        fail(label, "crit красится не bar-red: %r"
                             % data["fillBgColor"])
                elif expect_level == "warn":
                    if "246, 197, 111" not in (data["fillBgImage"] or ""):
                        fail(label, "warn-полоса не янтарная: %r"
                             % data["fillBgImage"])
                elif expect_level == "ok":
                    if "246, 197, 111" in (data["fillBgImage"] or "") \
                            or "239, 68, 68" in (data["fillBgColor"] or ""):
                        fail(label, "ok-полоса окрашена как предупреждение")
                if expect_level == "unknown":
                    if data["level"] == "ok":
                        fail(label, "unknown показан как healthy")
                    if "нет данных" not in data["rowText"]:
                        fail(label, "unknown без честной подписи: %r"
                             % data["rowText"])

                if not data["heartbeat"] or not data["serverSeg"]:
                    fail(label, "соседние сегменты Статуса (heartbeat/server) "
                                "пропали")
                if not data["cpuBar"]:
                    fail(label, "CPU/RAM-полосы Статуса пропали")
                if data["overflow"] > 1:
                    fail(label, "горизонтальный overflow: %d px"
                         % data["overflow"])

                page.evaluate(
                    "() => { const el = document.querySelector('.status-disk');"
                    " if (el) el.scrollIntoView({block: 'center'}); }")
                page.wait_for_timeout(250)
                shot = os.path.join(
                    HERE, "status_disk_%s_%s_%dx%d.png"
                    % (sid, vid, width, height))
                page.screenshot(path=shot)
                result["screenshots"].append(os.path.relpath(shot, REPO))
                print("  ok %s (level=%s)" % (label, data["level"]))
                ctx.close()
        browser.close()
    httpd.shutdown()

    result["failures"] = failures
    with open(os.path.join(HERE, "ui-checks.json"), "w",
              encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print("UI-CHECKS: %d сценариев, %d ошибок"
          % (len(result["checks"]), len(failures)))
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("P0-DISK-UI-OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
