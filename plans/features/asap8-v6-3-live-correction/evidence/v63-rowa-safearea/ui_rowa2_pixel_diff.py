"""ROWA2 — пиксельная проверка рендера (before vs after) без PIL.

Идея: обе PNG-фазы (before = app.css из HEAD, after = рабочее дерево) одного и
того же кейса грузятся в <canvas> headless-Chromium и сравниваются поэлементно.
Пиксельные координаты — device px (device_scale_factor=2) → CSS px = /2.

Ожидания:
  * кейсы с НУЛЕВЫМИ инсетами (390_zero_inset, 667x375_float_right44):
    diffPixels == 0 → «минимальный визуальный сдвиг»: обычные сценарии
    рендерятся байт-в-байт одинаково;
  * кейсы с right=44 (667x375_right44, 320x700_right44): diffPixels > 0,
    и bbox изменённых пикселей в фазе `after` НЕ выходит за content-safe
    край (2*(vw-44)), а в фазе `before` — выходит (дефект был виден глазами).

Запуск: .venv/Scripts/python.exe <evidence>/ui_rowa2_pixel_diff.py
Артефакт: <evidence>/_rowa2_pixel_diff.json
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
for _i in range(8):
    if os.path.isfile(os.path.join(_HERE, "tools", "ui_round1025_matrix.py")):
        break
    _HERE = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "tools"))
import ui_round1025_matrix as M  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

EVIDENCE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(EVIDENCE, "_rowa2_pixel_diff.json")
PORT = 8873
BASE_URL = "http://127.0.0.1:%d" % PORT

# tag, viewport_width, right_inset, ожидается_пустой_diff
PAIRS = [
    ("390_zero_inset", 390, 0, True),
    ("667x375_float_right44", 667, 44, True),
    ("667x375_right44", 667, 44, False),
    ("320x700_right44", 320, 44, False),
]

DIFF_JS = """
async () => {
  const load = (uri) => new Promise((res, rej) => {
    const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = uri;
  });
  const a = await load(window.__A), b = await load(window.__B);
  const c = document.createElement('canvas');
  c.width = Math.max(a.width, b.width); c.height = Math.max(a.height, b.height);
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.clearRect(0, 0, c.width, c.height); ctx.drawImage(a, 0, 0);
  const da = ctx.getImageData(0, 0, c.width, c.height).data;
  ctx.clearRect(0, 0, c.width, c.height); ctx.drawImage(b, 0, 0);
  const db = ctx.getImageData(0, 0, c.width, c.height).data;
  let diff = 0, minX = 1e9, maxX = -1, minY = 1e9, maxY = -1, maxDelta = 0;
  for (let y = 0; y < c.height; y++) {
    for (let x = 0; x < c.width; x++) {
      const i = (y * c.width + x) * 4;
      const d = Math.abs(da[i] - db[i]) + Math.abs(da[i + 1] - db[i + 1])
              + Math.abs(da[i + 2] - db[i + 2]) + Math.abs(da[i + 3] - db[i + 3]);
      if (d > 8) {
        diff++;
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (y < minY) minY = y; if (y > maxY) maxY = y;
        if (d > maxDelta) maxDelta = d;
      }
    }
  }
  return { w: c.width, h: c.height, diffPixels: diff, maxDelta: maxDelta,
           bbox: maxX < 0 ? null : { minX, maxX, minY, maxY } };
}
"""


def main():
    from playwright.sync_api import sync_playwright

    def serve_png(route):
        name = os.path.basename(route.request.url.split("?")[0])
        path = os.path.join(EVIDENCE, name)
        if not os.path.isfile(path):
            route.fulfill(status=404, body="nope")
            return
        with open(path, "rb") as fh:
            route.fulfill(status=200, content_type="image/png", body=fh.read())

    def handler(ctx):
        route = ctx.request
        if route.url.endswith("/blank"):
            route.fulfill(status=200, content_type="text/html",
                          body="<html><body></body></html>")
            return
        serve_png(route)

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            ctx = browser.new_context(viewport={"width": 400, "height": 300})
            page = ctx.new_page()
            page.route("**/_rowa2_*.png", handler)
            page.goto(BASE_URL + "/blank", wait_until="domcontentloaded")
            for tag, vw, inset, expect_empty in PAIRS:
                before = "_rowa2_%s_before.png" % tag
                after = "_rowa2_%s_after.png" % tag
                if not (os.path.isfile(os.path.join(EVIDENCE, before)) and
                        os.path.isfile(os.path.join(EVIDENCE, after))):
                    rows.append({"tag": tag, "status": "MISSING_PNG"})
                    continue
                page.evaluate("(v) => { window.__A = v.a; window.__B = v.b; }",
                              {"a": BASE_URL + "/" + before,
                               "b": BASE_URL + "/" + after})
                res = page.evaluate(DIFF_JS)
                safe_edge_px = 2 * (vw - inset)
                bbox = res["bbox"]
                row = {
                    "tag": tag, "viewportWidth": vw, "rightInset": inset,
                    "safeEdgeCssPx": vw - inset, "safeEdgeDevicePx": safe_edge_px,
                    "size": {"w": res["w"], "h": res["h"]},
                    "diffPixels": res["diffPixels"], "maxDelta": res["maxDelta"],
                    "changedBBoxDevicePx": bbox,
                    "changedBBoxCssPx": None if not bbox else {
                        "minX": bbox["minX"] / 2, "maxX": bbox["maxX"] / 2,
                        "minY": bbox["minY"] / 2, "maxY": bbox["maxY"] / 2},
                    "expectedEmptyDiff": expect_empty,
                }
                if expect_empty:
                    row["ok"] = res["diffPixels"] == 0
                    row["note"] = ("нулевые инсеты → рендер идентичен (сдвига нет)"
                                   if row["ok"] else
                                   "НЕОЖИДАННЫЙ визуальный сдвиг при нулевых инсетах")
                else:
                    inside = bool(bbox) and bbox["maxX"] <= safe_edge_px
                    row["ok"] = res["diffPixels"] > 0 and inside
                    row["note"] = ("изменения есть и НЕ выходят за safe-край "
                                   "(в до-фазе выходили)" if row["ok"] else
                                   "изменения выходят за safe-край или их нет")
                rows.append(row)
                print("[rowa2px] %-24s diff=%-7s maxDelta=%-4s bboxCSS=%s safeEdge=%s ok=%s"
                      % (tag, row["diffPixels"], row["maxDelta"],
                         row["changedBBoxCssPx"], row["safeEdgeCssPx"], row["ok"]))
            ctx.close()
        finally:
            browser.close()
    httpd.shutdown()
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump({"generated": "2026-10-16",
                   "method": "headless-Chromium canvas diff, device_scale_factor=2",
                   "pairs": rows}, fh, ensure_ascii=False, indent=2)
    bad = [r["tag"] for r in rows if not r.get("ok")]
    print("[rowa2px] FAIL: %s" % (bad or "none"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
