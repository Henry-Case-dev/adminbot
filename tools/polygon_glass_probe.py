"""round 10.26 (ADR-1026-3 D6 / T-3201-T-3203): гейт-прототип стекла над новым
полигональным фоном — объективная проверка 7 пунктов §12.2.

Поднимает локальный сервер над `tools/_polygon_glass_prototype/` (gitignored) +
`web/static`, монтирует vendored `@liquidglassjs/core` 0.5.3 на ОДНУ
изолированную `[data-glass-surface]` поверх полигонального фона с ЯВНЫМ
источником (`source` = `#polygon-background`, `mode:'webgl'`) и проверяет:

  1. преломление (эвристика headless: стекло меняется при смене фона позади);
  2. текст/иконка чётки и hit-testable;
  3. эффект не перекрывает содержимое кнопки;
  4. НЕТ белого непрозрачного прямоугольника (hotfix10);
  5. НЕТ яркого внешнего ореола;
  6. НЕТ конфликта WebGL-контекстов (фоновый рендерер — Canvas 2D);
  7. перф на mobile приемлема (~FPS).

Пункты, которые headless не подтверждает (реальная оптическая рефракция,
поведение Safari/WebKit, субъективная читаемость) — честно помечаются
`PENDING_OWNER`; они не объявляются пройденными.

Запуск: .venv/Scripts/python.exe tools/polygon_glass_probe.py
Выход: tools/_polygon_glass_prototype/probe.json + *.png (gitignored).
"""
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
PORT = 8794
OUT = os.path.join(REPO, "tools", "_polygon_glass_prototype")

from tools.glass_prototype_probe import _mean_abs_diff, _png_pixels  # noqa: E402


class _Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):  # noqa: N802
        p = path.split("?")[0]
        if p.startswith("/static/"):
            rel = "web/static/" + p[len("/static/"):]
        elif p in ("/", "", "/index.html"):
            rel = "tools/_polygon_glass_prototype/index.html"
        elif p == "/mount.js":
            rel = "tools/_polygon_glass_prototype/mount.js"
        else:
            rel = p.lstrip("/")
        return os.path.join(REPO, rel.replace("/", os.sep))

    def log_message(self, *args):
        pass


def _region_stats(png):
    w, h, bpp, px = _png_pixels(png)
    n = w * h
    white = 0
    lum = 0.0
    for i in range(0, len(px), bpp):
        r, g, b = px[i], px[i + 1], px[i + 2]
        if r > 240 and g > 240 and b > 240:
            white += 1
        lum += 0.2126 * r + 0.7152 * g + 0.0722 * b
    return {"w": w, "h": h, "white_frac": round(white / max(1, n), 4),
            "lum": round(lum / max(1, n), 2)}


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(OUT, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    result = {"mounted": False, "error": None, "mode": None, "usedSource": None,
              "checks": {}, "pending_owner": [], "failures": []}
    failures = result["failures"]
    url = "http://127.0.0.1:%d/index.html" % PORT

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            # reduced-motion → фоновый кадр детерминирован (сравнение A/B).
            ctx = browser.new_context(viewport={"width": 900, "height": 600},
                                      reduced_motion="reduce")
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m: (
                errors.append("%s: %s" % (m.type, m.text[:200]))
                if m.type == "error" else None))
            page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)[:300]))
            page.goto(url, wait_until="load")
            page.wait_for_timeout(1200)

            result["mounted"] = bool(page.evaluate("window.__glassMounted"))
            result["error"] = page.evaluate("window.__glassError")
            result["mode"] = page.evaluate("window.__glassMode")
            result["usedSource"] = bool(page.evaluate("window.__usedSource"))

            # Проверки 2/3 — чёткость и неперекрытие содержимого кнопки.
            hit = page.evaluate(
                "() => {"
                " const btn = document.getElementById('glass-btn');"
                " const lbl = document.getElementById('glass-label');"
                " const r = lbl.getBoundingClientRect();"
                " const el = document.elementFromPoint("
                "   r.x + r.width / 2, r.y + r.height / 2);"
                " return { labelVisible: r.width > 0 && r.height > 0,"
                "   hitIsButton: !!(el && (btn === el || btn.contains(el))),"
                "   labelText: lbl.textContent.trim() }; }")
            result["checks"]["text"] = hit

            # Проверка 6 — нет конфликта WebGL-контекстов (фон = Canvas 2D).
            ctxinfo = page.evaluate(
                "() => ({ polygonMode: window.__PolygonBackground"
                "   ? window.__PolygonBackground.mode() : 'none',"
                "   auroraCanvas: !!document.querySelector('#aurora-flow-canvas'),"
                "   legacy: !!window.__AuroraFlowLegacy,"
                "   bgCanvas: !!document.querySelector('#polygon-background') })")

            # Скриншоты области стекла, «дыры» (тот же кадр без стекла) и фона.
            box = page.evaluate(
                "() => { const g = document.querySelector('[data-probe=glass]')"
                ".getBoundingClientRect();"
                " const h = document.getElementById('probe-hole')"
                ".getBoundingClientRect();"
                " return { g: [g.x, g.y, g.width, g.height],"
                "          h: [h.x, h.y, h.width, h.height] }; }")
            g = box["g"]
            glass_png = os.path.join(OUT, "glass.png")
            page.screenshot(path=glass_png, clip={
                "x": g[0], "y": g[1], "width": g[2], "height": g[3]})

            # Тот же кадр без монтирования стекла (для A/B-эвристики).
            page.evaluate(
                "() => { if (window.__glassDispose) window.__glassDispose(); }")
            page.wait_for_timeout(400)
            glass_off_png = os.path.join(OUT, "glass_off.png")
            page.screenshot(path=glass_off_png, clip={
                "x": g[0], "y": g[1], "width": g[2], "height": g[3]})

            # Проверка 5 — внешний ореол: яркость кольца вокруг стекла.
            ring = page.evaluate(
                "() => { const g = document.querySelector('[data-probe=glass]')"
                ".getBoundingClientRect(); const d = 26;"
                " return { x: g.x - d, y: g.y - d,"
                "          width: g.width + 2 * d, height: g.height + 2 * d }; }")
            ring_png = os.path.join(OUT, "ring.png")
            page.screenshot(path=ring_png, clip=ring)

            # Проверка 7 — FPS на mobile.
            mctx = browser.new_context(viewport={"width": 390, "height": 844})
            mpage = mctx.new_page()
            mpage.goto(url, wait_until="load")
            mpage.wait_for_timeout(3000)
            mobile_fps = mpage.evaluate("window.__fps || null")
            mobile_mode = mpage.evaluate(
                "() => window.__PolygonBackground"
                " ? window.__PolygonBackground.mode() : 'none'")

            glass_stats = _region_stats(glass_png)
            glass_off_stats = _region_stats(glass_off_png)
            ring_stats = _region_stats(ring_png)
            result["glassStats"] = glass_stats
            result["checks"]["webgl_conflict"] = ctxinfo
            result["checks"]["mobile"] = {"fps": mobile_fps, "mode": mobile_mode}
            result["console"] = errors

            # 4. белый непрозрачный прямоугольник.
            if glass_stats["white_frac"] > 0.03:
                failures.append(
                    "белый непрозрачный прямоугольник (white_frac=%s)"
                    % glass_stats["white_frac"])
            # 2. текст.
            if not hit["labelVisible"]:
                failures.append("текст/иконка не отрисованы в стекле")
            # 3. не перекрывает кнопку.
            if not hit["hitIsButton"]:
                failures.append("эффект перекрывает содержимое кнопки (hit-test)")
            # 6. конфликт WebGL.
            if ctxinfo["polygonMode"] != "canvas2d" or ctxinfo["auroraCanvas"]:
                failures.append("конфликт рендереров: %s" % ctxinfo)
            if not ctxinfo["bgCanvas"]:
                failures.append("нет фонового canvas")
            # 7. mobile perf.
            if mobile_fps is not None and mobile_fps < 20:
                failures.append("mobile FPS низкий: %s" % mobile_fps)

            # 1/5 — эвристики, честно помечаем как неподтверждённые headless.
            result["checks"]["refraction_diff"] = round(
                _mean_abs_diff(glass_png, glass_off_png), 3)
            result["checks"]["halo_lum_delta"] = round(
                ring_stats["lum"] - glass_stats["lum"], 2)
            result["pending_owner"] = [
                "П№1 реальная оптическая рефракция (headless — эвристика "
                "diff=%s)" % result["checks"]["refraction_diff"],
                "П№5 субъективный внешний ореол (headless lum-дельта=%s)"
                % result["checks"]["halo_lum_delta"],
                "П№7 субъективная плавность/перф в реальном Telegram WebView "
                "(headless fps=%s)" % mobile_fps,
            ]
            if result["mode"] != "refraction":
                failures.append(
                    "режим стекла %r — не рефракция (source не применился)"
                    % result["mode"])
            browser.close()
    finally:
        httpd.shutdown()

    print(json.dumps(result, ensure_ascii=False, indent=1))
    with open(os.path.join(OUT, "probe.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("[polygon-glass-probe] failures:", len(failures))
    for f_ in failures:
        print("  !", f_)
    print("[polygon-glass-probe] PENDING_OWNER:", len(result["pending_owner"]))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
