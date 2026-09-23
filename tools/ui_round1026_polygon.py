"""round 10.26 (ADR-1026-3 D8 / T-3207-T-3210, §14): Playwright-проверка
полигонального фона.

Отдельный прогон (существующая матрица §71 остаётся на откатном пути Aurora):
реальный `web/index.html` с `UI_POLYGON_BG_ENABLED=true`, локальный http + те же
API-стабы, что в `tools/ui_round1025_matrix.py` (импортируются, не дублируются).

Проверяет:
  * один активный рендерер: `#polygon-background` (fixed/inset:0/pointer-events:
    none, прямой потомок body), `html.polygon-bg`, ОТСУТСТВИЕ `#aurora-flow-canvas`;
  * `getDiagnostics()` — 11 полей §14.1; nodeCount 90–140 / 45–75;
  * движение §14.2 — кадры 0/5/10/20 с: меняется ПОЛОЖЕНИЕ геометрии, не только
    яркость (сдвиг центроида + структурная разница); fullscreen — анимация жива,
    seed не сброшен; нет левой полосы;
  * композиция §14.3 — узлы/полигоны/линии, сиреневая + циановая области,
    локальные яркие участки (программно, не «canvas в DOM»);
  * материалы §14.4 — Desktop/Mobile × Статус/Модули × normal/fullscreen (PNG).

Артефакты (gitignored): tools/_ui_round1026_raw.json + tools/_ui_round1026_shots/*.png
Запуск: .venv/Scripts/python.exe tools/ui_round1026_polygon.py
"""
import colorsys
import json
import os
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tools.ui_round1025_matrix as m  # noqa: E402

PORT = m.PORT
SHOTS = os.path.join(REPO, "tools", "_ui_round1026_shots")
RAW = os.path.join(REPO, "tools", "_ui_round1026_raw.json")

# Полигональный фон включён (в матрице §71 он намеренно OFF = Aurora-откат).
m.ME_JSON["ui_flags"]["UI_POLYGON_BG_ENABLED"] = True

GRID_W, GRID_H = 120, 75
MOTION_WAITS = (0, 5000, 5000, 10000)   # 0 / 5 / 10 / 20 с

SAMPLE_JS = """
() => {
  const cv = document.getElementById('polygon-background');
  if (!cv) return null;
  const ctx = cv.getContext('2d');
  const W = %d, H = %d, cw = cv.width, ch = cv.height;
  const img = ctx.getImageData(0, 0, cw, ch).data;
  const out = [];
  for (let y = 0; y < H; y++) {
    const row = [];
    for (let x = 0; x < W; x++) {
      const px = Math.min(cw - 1, Math.floor((x + 0.5) * cw / W));
      const py = Math.min(ch - 1, Math.floor((y + 0.5) * ch / H));
      const i = (py * cw + px) * 4;
      row.push([img[i], img[i + 1], img[i + 2]]);
    }
    out.push(row);
  }
  return out;
}
""" % (GRID_W, GRID_H)

DOM_JS = """
() => {
  const cv = document.getElementById('polygon-background');
  const de = document.documentElement;
  const bg = cv ? getComputedStyle(cv) : null;
  const r = cv ? cv.getBoundingClientRect() : null;
  const inContainer = cv ? !!cv.closest(
    '.module-list, .module-catalog, .scroll-area, .card, main') : null;
  const bgCanvases = [...document.querySelectorAll('canvas')].filter((c) => {
    const s = getComputedStyle(c);
    return s.position === 'fixed' && c.width > 0 &&
      c.getAttribute('aria-hidden') === 'true';
  }).length;
  return {
    id: cv ? cv.id : null,
    parentIsBody: cv ? cv.parentNode === document.body : false,
    position: bg ? bg.position : null,
    pointerEvents: bg ? bg.pointerEvents : null,
    zIndex: bg ? bg.zIndex : null,
    rect: r ? { x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height) } : null,
    vw: window.innerWidth, vh: window.innerHeight,
    inContainer: inContainer,
    polygonClass: de.classList.contains('polygon-bg'),
    auroraClass: de.classList.contains('aurora-flow-v2'),
    auroraCanvas: !!document.querySelector('#aurora-flow-canvas'),
    visibleBgCanvases: bgCanvases,
    diagnostics: window.__PolygonBackground
      ? window.__PolygonBackground.getDiagnostics() : null,
    auroraMode: (window.__AuroraFlow && window.__AuroraFlow.mode)
      ? window.__AuroraFlow.mode() : null,
    auroraSample: (window.__AuroraFlow && window.__AuroraFlow.sample)
      ? !!window.__AuroraFlow.sample() : false,
  };
}
"""


def _hue(r, g, b):
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return h * 360.0, s, v


def _composition(grid):
    n = sum(len(row) for row in grid)
    lilac = cyan = bright = 0
    lum = []
    for row in grid:
        for (r, g, b) in row:
            h, s, v = _hue(r, g, b)
            if 250 <= h <= 305 and s > 0.18 and v > 0.20:
                lilac += 1
            if 160 <= h <= 205 and s > 0.18 and v > 0.22:
                cyan += 1
            if v > 0.62:
                bright += 1
            lum.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
    # edge density: доля ячеек с локальным градиентом выше порога (линии/грани).
    H, W = len(grid), len(grid[0])
    edges = 0
    for y in range(1, H - 1):
        for x in range(1, W - 1):
            dx = abs(lum[y * W + x + 1] - lum[y * W + x - 1])
            dy = abs(lum[(y + 1) * W + x] - lum[(y - 1) * W + x])
            if (dx + dy) > 12:
                edges += 1
    # локальность ярких: доля ярких в топ-10% ячеек.
    cells = sorted(lum, reverse=True)
    top = max(1, len(cells) // 10)
    top_mean = sum(cells[:top]) / top
    all_mean = sum(cells) / max(1, len(cells))
    bright_frac = bright / max(1, n)
    return {
        "lilac": round(lilac / n, 4), "cyan": round(cyan / n, 4),
        "bright": round(bright_frac, 4),
        "edge": round(edges / max(1, (H - 2) * (W - 2)), 4),
        "top_mean": round(top_mean, 1), "mean": round(all_mean, 1),
        "local_ratio": round(top_mean / max(1.0, all_mean), 2),
    }


def _struct_corr(a, b):
    la = [0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]
          for row in a for p in row]
    lb = [0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]
          for row in b for p in row]
    n = min(len(la), len(lb))
    ma = sum(la) / max(1, n)
    mb = sum(lb) / max(1, n)
    num = sum((la[i] - ma) * (lb[i] - mb) for i in range(n))
    da = sum((la[i] - ma) ** 2 for i in range(n)) ** 0.5
    db = sum((lb[i] - mb) ** 2 for i in range(n)) ** 0.5
    return round(num / (da * db), 4) if da > 0 and db > 0 else 0.0


def _luminances(grid):
    return [0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]
            for row in grid for p in row]


def _local_maxima(grid):
    """Локальные максимумы яркости (9-окрестность) — позиции «узловых» ячеек.
    Используются для проверки, что меняется ПОЛОЖЕНИЕ, а не только яркость."""
    W, H = len(grid[0]), len(grid)
    lum = _luminances(grid)
    mean = sum(lum) / max(1, len(lum))
    var = sum((v - mean) ** 2 for v in lum) / max(1, len(lum))
    thr = mean + 0.8 * (var ** 0.5)
    pts = []
    for y in range(1, H - 1):
        for x in range(1, W - 1):
            i = y * W + x
            if lum[i] < thr:
                continue
            if (lum[i] >= lum[i - 1] and lum[i] >= lum[i + 1]
                    and lum[i] >= lum[i - W] and lum[i] >= lum[i + W]):
                pts.append((x, y))
    return pts


def _median_shift(pa, pb):
    if not pa or not pb:
        return None
    dists = []
    for (x, y) in pa:
        best = 1e9
        for (X, Y) in pb:
            d = ((X - x) ** 2 + (Y - y) ** 2) ** 0.5
            if d < best:
                best = d
        dists.append(best)
    dists.sort()
    return dists[len(dists) // 2]


def _polygon_checks(probe, label, expect_mobile):
    fails = []
    d = probe["diagnostics"] or {}
    if probe["id"] != "polygon-background":
        fails.append("%s: нет фонового canvas #polygon-background" % label)
    if not probe["parentIsBody"]:
        fails.append("%s: canvas не прямой потомок body" % label)
    if probe["position"] != "fixed":
        fails.append("%s: canvas не fixed" % label)
    if probe["pointerEvents"] != "none":
        fails.append("%s: canvas перехватывает клики" % label)
    if str(probe["zIndex"]) != "0":
        fails.append("%s: z-index != 0 (%s)" % (label, probe["zIndex"]))
    if probe["inContainer"]:
        fails.append("%s: canvas внутри max-width/scroll-контейнера" % label)
    if not probe["polygonClass"]:
        fails.append("%s: нет html.polygon-bg" % label)
    if probe["auroraClass"] or probe["auroraCanvas"]:
        fails.append("%s: Aurora активна одновременно с Polygon" % label)
    if probe["visibleBgCanvases"] != 1:
        fails.append("%s: фоновых canvas %d (ожидался ровно 1)"
                     % (label, probe["visibleBgCanvases"]))
    if len(d) != 11:
        fails.append("%s: getDiagnostics полей %d != 11" % (label, len(d)))
    if d.get("renderer") != "canvas2d":
        fails.append("%s: renderer=%r" % (label, d.get("renderer")))
    lo, hi = (45, 75) if expect_mobile else (90, 140)
    if not (lo <= d.get("nodeCount", 0) <= hi):
        fails.append("%s: nodeCount=%s вне %d–%d"
                     % (label, d.get("nodeCount"), lo, hi))
    if d.get("triangleCount", 0) <= 0:
        fails.append("%s: нет граней (triangleCount=0)" % label)
    if d.get("canvasWidth", 0) <= 0 or d.get("canvasHeight", 0) <= 0:
        fails.append("%s: пустой drawing buffer" % label)
    if d.get("devicePixelRatio", 1) > (1.5 if expect_mobile else 2):
        fails.append("%s: DPR-кап нарушен (%s)"
                     % (label, d.get("devicePixelRatio")))
    return fails


def _composition_failures(comp, label):
    fails = []
    if comp["lilac"] < 0.01:
        fails.append("%s: сиреневых пикселей мало (%s)"
                     % (label, comp["lilac"]))
    if comp["cyan"] < 0.01:
        fails.append("%s: циановых пикселей мало (%s)" % (label, comp["cyan"]))
    if comp["bright"] < 0.005:
        fails.append("%s: нет ярких участков (%s)" % (label, comp["bright"]))
    if comp["edge"] < 0.03:
        fails.append("%s: нет граней/линий (edge=%s)" % (label, comp["edge"]))
    if comp["local_ratio"] < 1.3:
        fails.append("%s: яркость равномерна (local_ratio=%s)"
                     % (label, comp["local_ratio"]))
    return fails


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    httpd = m._start_server()
    out = {"config": "polygon ON", "viewports": {}, "failures": []}
    failures = out["failures"]

    def route_api(route):
        url = route.request.url
        p = url.split("?")[0]
        if p.endswith("/api/config"):
            payload = m.CONFIG_STUB
        else:
            payload = m._stub_for(url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload))

    cases = [("desktop_status", 1440, 900, "#/", False),
             ("mobile_status", 390, 844, "#/", True),
             ("desktop_modules", 1440, 900, "#/modules", False),
             ("mobile_modules", 390, 844, "#/modules", True)]

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for (tag, w, h, route, mobile) in cases:
                ctx = browser.new_context(viewport={"width": w, "height": h})
                ctx.add_init_script(m.TMA_STUB)
                ctx.route("**/api/**", route_api)
                page = ctx.new_page()
                errs = []
                page.on("pageerror", lambda e, b=errs: b.append(str(e)[:300]))
                page.goto("http://127.0.0.1:%d/web/index.html" % PORT + route,
                          wait_until="load")
                try:
                    page.wait_for_selector(".app-shell", timeout=8000)
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(900)
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(400)

                out["viewports"][tag] = {"errors": errs}
                probe = page.evaluate(DOM_JS)
                out["viewports"][tag]["dom"] = probe
                failures.extend(_polygon_checks(probe, tag, mobile))

                # Материалы §14.4 (normal).
                try:
                    page.screenshot(path=os.path.join(SHOTS, tag + "_normal.png"))
                except Exception as e:  # noqa: BLE001
                    failures.append("%s: screenshot fail %s" % (tag, e))

                if tag.endswith("status"):
                    samples = []
                    for i, wait in enumerate(MOTION_WAITS):
                        if wait:
                            page.wait_for_timeout(wait)
                        samples.append(page.evaluate(SAMPLE_JS))
                    out["viewports"][tag]["motion"] = {
                        "t": [0, 5, 10, 20]}
                    if any(s is None for s in samples):
                        failures.append("%s: нет пиксельной пробы фона" % tag)
                    else:
                        maxima = [_local_maxima(s) for s in samples]
                        shifts = [round(_median_shift(maxima[0], maxima[i]) or 0.0, 2)
                                  for i in range(1, 4)]
                        total_shift = shifts[-1]
                        corr = _struct_corr(samples[0], samples[-1])
                        out["viewports"][tag]["motion"].update(
                            {"median_shifts": shifts,
                             "total_shift": total_shift, "corr_0_20": corr,
                             "maxima": [len(mx) for mx in maxima]})
                        # 4–18 CSS px при ячейке ~3–12 px: медианный сдвиг узловых
                        # ячеек обязан быть заметным (≥0.3 ячейки), иначе — статика.
                        if total_shift < 0.3 and max(shifts) < 0.3:
                            failures.append(
                                "%s: положение элементов не меняется "
                                "(median_shifts=%s)" % (tag, shifts))
                        if corr > 0.995 and total_shift < 0.3:
                            failures.append(
                                "%s: кадр 0/20с почти идентичен (corr=%s)"
                                % (tag, corr))
                        comp = _composition(samples[-1])
                        out["viewports"][tag]["composition"] = comp
                        failures.extend(_composition_failures(comp, tag))

                # fullscreen §14.2/§14.4: анимация жива, seed не сброшен, нет
                # левой полосы; материалы fullscreen — для всех кейсов.
                d0 = page.evaluate(
                    "() => window.__PolygonBackground.getDiagnostics()")
                page.set_viewport_size({"width": w, "height": 700})
                page.wait_for_timeout(400)
                page.evaluate("() => window.__AuroraFlow.resize()")
                page.wait_for_timeout(500)
                d1 = page.evaluate(
                    "() => window.__PolygonBackground.getDiagnostics()")
                r = page.evaluate(
                    "() => { const c = document.getElementById("
                    "'polygon-background').getBoundingClientRect();"
                    " return { x: Math.round(c.x), w: Math.round(c.width),"
                    " vw: window.innerWidth }; }")
                page.wait_for_timeout(700)
                d2 = page.evaluate(
                    "() => window.__PolygonBackground.getDiagnostics()")
                out["viewports"][tag]["fullscreen"] = {
                    "diag0": d0, "diag1": d1, "diag2": d2, "rect": r}
                if r["x"] != 0 or abs(r["w"] - r["vw"]) > 2:
                    failures.append(
                        "%s: левая полоса/сдвиг canvas (rect=%s)" % (tag, r))
                if d2["frameCount"] <= d1["frameCount"]:
                    failures.append(
                        "%s: анимация остановилась после fullscreen" % tag)
                if d0["nodeCount"] != d2["nodeCount"]:
                    failures.append(
                        "%s: seed сброшен после fullscreen (%s→%s)"
                        % (tag, d0["nodeCount"], d2["nodeCount"]))
                try:
                    page.screenshot(path=os.path.join(
                        SHOTS, tag + "_fullscreen.png"))
                except Exception:  # noqa: BLE001
                    pass
                ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    print(json.dumps(out, ensure_ascii=False, indent=1))
    with open(RAW, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("[polygon-playwright] failures:", len(failures))
    for f_ in failures:
        print("  !", f_)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
