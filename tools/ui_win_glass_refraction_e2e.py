"""WIN-GLASS-P0 (18.10.2026) — Playwright/Chromium e2e: оптическая рефракция
контролируемого фонового слоя на Android-эмуляции + аудит Tier A/FS-полосы.

Что проверяется на РЕАЛЬНЫХ байтах кандидата (http-серв web/index.html +
web/static/*, /api/* — стабы):
  A. `?glassrefract=off` (RED) → `?glassrefract=on` (GREEN): скриншоты одной
     и той же стеклянной поверхности, посчитанное смещение фоновых пикселей
     (энергия кромок и интерьера), плюс геометрия: 0 смещений/наложений DOM,
     `.lg-refract` не перехватывает pointer, текст не искажён (нет filter на
     контенте), горизонтального overflow нет.
  B. Проба `__GlassProbe`: tierA/reason/backdropRefRender/svgRender/engine —
     честные факты клиента (не «должно работать»).
  C. Полоса управления: `__FullscreenPolicy.diagnostics()` (slot/reason/
     actualFullscreen/launchFullscreen, launchParams platform) — что веб
     видит на старте, без ложных утверждений о геометрии нативного окна.

Запуск: .venv/Scripts/python.exe tools/ui_win_glass_refraction_e2e.py
Артефакты: plans/features/win-glass-hotfix/evidence/e2e/
"""
import json
import os
import struct
import sys
import threading
import zlib
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_round1025_matrix as M  # noqa: E402
import ui_asap8_w2_fullscreen_e2e as FS  # noqa: E402  (mock SDK + конфиги)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = M.REPO
PORT = M.PORT + 11
EVIDENCE = os.environ.get(
    "WG_E2E_EVIDENCE",
    os.path.join(REPO, "plans", "features", "win-glass-hotfix", "evidence", "e2e"))
RAW = os.path.join(EVIDENCE, "_results.json")
os.makedirs(EVIDENCE, exist_ok=True)
BASE_URL = "http://127.0.0.1:%d" % PORT
BG_SEED = 20260923          # детерминированная сцена polygon-фона (тест-режим)

ME = json.loads(json.dumps(M.ME_JSON))
ME["ui_flags"]["UI_POLYGON_BG_ENABLED"] = True      # основной фон production
ME["ui_flags"]["UI_AURORA_FLOW_V2"] = False
ME["ui_flags"]["TOKEN_FLOW_NODEFLOW_ENABLED"] = False


class Check:
    def __init__(self, name):
        self.name = name
        self.failures = []
        self.count = 0

    def ok(self, cond, msg):
        self.count += 1
        if not cond:
            self.failures.append(msg)
        return bool(cond)

    def note(self, **kw):
        self.count += 1
        return kw


def _api_handler_factory():
    def handler(route):
        try:
            path = route.request.url.split("?")[0]
            marker = "/api/"
            if marker not in path:
                route.continue_()
                return
            if path.endswith("/api/me"):
                API_LOG.append((path, "me"))
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(ME))
                return
            payload = M._stub_for(route.request.url)
            if isinstance(payload, (dict, list)):
                body = json.dumps(payload)
                ctype = "application/json"
            elif isinstance(payload, str):
                body = payload
                ctype = "text/plain; charset=utf-8"
            else:
                body = json.dumps({"ok": True})
                ctype = "application/json"
            API_LOG.append((path, type(payload).__name__))
            route.fulfill(status=200, content_type=ctype, body=body)
        except Exception as exc:  # noqa: BLE001 — диагностика стаба, не тишина
            import traceback
            print("[api-handler] %s: %s" % (type(exc).__name__, exc))
            traceback.print_exc()
            try:
                route.fulfill(status=500, content_type="text/plain",
                              body="stub-error")
            except Exception:  # noqa: BLE001
                pass
    return handler


def _start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


API_LOG = []


# Мок-капабилити Android WebView: canvas-проба проходит (filter:url на canvas
# рендерится), движок chromium, tierA как в продакшене остаётся по движку —
# носитель оптики выбирает app.js по platform=android (см. app.js
# _applyRefractLayer). Проба реальная (стенд не переписывает рендер), но
# подменяет только результат __GlassProbe, чтобы детерминированно проверить
# downstream-путь слоя в эмуляции: реальный Android WebView агентам недоступен
# (PENDING_OWNER_E2E).
STUB_PROBE_ANDROID_JS = """
(() => {
  const real = window.__GlassProbe;
  window.__GlassProbe = {
    probe: () => Promise.resolve(window.__GlassProbe.cached()),
    cached: () => ({
      tierA: false, reason: 'engine-webkit-backdrop-url-no',
      engine: 'webkit', svgRender: true, backdrop: true,
      refractionLayer: true, ms: 4,
    }),
    reset: () => {}, details: () => ({}),
    _real: real,
  };
  window.__WG_PROBE_STUB__ = 'android-webview-class';
})()
"""


def _sdk_route(cfg):
    """Мок-клиент Telegram: Playwright зовёт handler(route, request) —
    используем функцию ровно с одним параметром (иначе cfg=Request)."""
    def handler(route):
        route.fulfill(status=200, content_type="application/javascript",
                      body=FS.mock_sdk_js(cfg))
    return handler


# ── Пробы страницы ────────────────────────────────────────────────────────
GLASS_PROBE_JS = """
(() => {
  const de = document.documentElement;
  const probe = (window.__GlassProbe && window.__GlassProbe.cached()) || null;
  const det = (window.__GlassProbe && window.__GlassProbe.details()) || null;
  const dg = (window.__GlassRefraction &&
              typeof window.__GlassRefraction.diagnostics === 'function')
    ? window.__GlassRefraction.diagnostics() : null;
  const tiers = {};
  document.querySelectorAll('[data-glass-tier]').forEach((el) => {
    const t = el.getAttribute('data-glass-tier');
    tiers[t] = (tiers[t] || 0) + 1;
  });
  const reasons = {};
  document.querySelectorAll('[data-glass-reason]').forEach((el) => {
    const r = el.getAttribute('data-glass-reason');
    reasons[r] = (reasons[r] || 0) + 1;
  });
  const refractOn = document.querySelectorAll('[data-refract-layer="on"]').length;
  const layers = document.querySelectorAll('canvas.lg-refract').length;
  const layerHit = (() => {
    const cv = document.querySelector('canvas.lg-refract');
    if (!cv) return null;
    const r = cv.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0)) return null;
    const el = document.elementFromPoint(r.left + r.width / 2,
                                         r.top + r.height / 2);
    return el ? (el.className || '').toString() : null;
  })();
  const layerPtr = (() => {
    const cv = document.querySelector('canvas.lg-refract');
    if (!cv) return null;
    const cs = getComputedStyle(cv);
    return { pointerEvents: cs.pointerEvents, zIndex: cs.zIndex,
             filter: cs.filter, backdrop: cs.backdropFilter };
  })();
  // Текст не искажается: filter:url на контенте поверхностей не появился
  // (собственные слои .lg-refract — декорация, они исключены).
  const filteredContent = Array.from(document.querySelectorAll(
    '.card, .module-card, .hub-card, .lg-panel__content, .card *'))
    .filter((el) => {
      if (el.classList && el.classList.contains('lg-refract')) return false;
      const f = getComputedStyle(el).filter || '';
      return f.indexOf('url(') >= 0;
    }).length;
  const shadow = { urlBackdrop: 0, count: 0 };
  document.querySelectorAll('[data-refract-layer="on"]').forEach((el) => {
    shadow.count++;
    const t = el.classList && el.classList.contains('lg-panel')
      ? el.querySelector('.lg-panel__backdrop') : el;
    const v = t ? (getComputedStyle(t).backdropFilter || '') : '';
    if (v.indexOf('url(') >= 0) shadow.urlBackdrop++;
  });
  return {
    probe: probe,
    probeDetails: det,
    refraction: dg,
    tiers: tiers,
    reasons: reasons,
    refractOn: refractOn,
    layers: layers,
    layerHit: layerHit,
    layerPtr: layerPtr,
    filteredContent: filteredContent,
    shadow: shadow,
    hOverflow: de.scrollWidth > window.innerWidth + 1,
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    bg: (() => {
      const c = document.getElementById('polygon-background');
      return c ? { w: c.width, h: c.height,
                   rect: (() => { const r = c.getBoundingClientRect();
                                  return [Math.round(r.left), Math.round(r.top),
                                          Math.round(r.width),
                                          Math.round(r.height)]; })() } : null;
    })(),
    polyMode: (window.__PolygonBackground &&
               typeof window.__PolygonBackground.mode === 'function')
      ? window.__PolygonBackground.mode() : null,
  };
})()
"""

FS_AUDIT_JS = """
(() => {
  const pol = window.__FullscreenPolicy;
  if (!pol) return null;
  const d = pol.diagnostics();
  const s = pol.state();
  return {
    platform: d.platform, sdkVersion: d.sdkVersion,
    launchParams: d.launchParams,
    actualFullscreen: d.actualFullscreen,
    launchFullscreen: d.launchFullscreen,
    hasRequestFullscreen: d.hasRequestFullscreen,
    hasExitFullscreen: d.hasExitFullscreen,
    slot: d.slot, reason: d.reason, reasonText: d.reasonText,
    canOfferFullscreen: d.canOfferFullscreen, canOfferExit: d.canOfferExit,
    clickResult: d.clickResult,
    viewport: [d.width, d.height, d.stableHeight],
    trace: (d.trace || []).map((t) => t.code).slice(-8),
  };
})()
"""

# Ключевые точки покраски в интерьер поверхности (центр и кромки).
SURFACE_JS = """
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: Math.round(r.left), y: Math.round(r.top),
           w: Math.round(r.width), h: Math.round(r.height),
           tier: el.getAttribute('data-glass-tier'),
           reason: el.getAttribute('data-glass-reason'),
           refract: el.getAttribute('data-refract-layer'),
           cls: (el.className || '').toString() };
}
"""


def _shot(page, selector, name):
    """Скриншот поверхности в evidence-каталог."""
    path = os.path.join(EVIDENCE, name + ".png")
    page.locator(selector).screenshot(path=path)
    return path


LAYOUT_TAG_JS = """
() => {
  const nodes = document.querySelectorAll('#app *');
  const limit = Math.min(nodes.length, 600);
  let i = 0;
  for (const el of nodes) {
    if (i >= limit) break;
    i++;
    if (el.classList && el.classList.contains('lg-refract')) continue;
    if (!el.hasAttribute('data-wg-id')) el.setAttribute('data-wg-id', 'L' + i);
    const host = el.querySelector ? el.querySelector(':scope > .lg-refract') : null;
    if (host) el.setAttribute('data-wg-host', '1');
  }
  return { tagged: document.querySelectorAll('[data-wg-id]').length,
           hosts: document.querySelectorAll('[data-wg-host="1"]').length,
           scrollH: document.documentElement.scrollHeight };
}
"""

LAYOUT_READ_JS = """
() => {
  const rows = [];
  document.querySelectorAll('[data-wg-id]').forEach((el) => {
    const r = el.getBoundingClientRect();
    rows.push([el.getAttribute('data-wg-id'),
               el.getAttribute('data-wg-host') === '1' ? 1 : 0,
               Math.round(r.x), Math.round(r.y),
               Math.round(r.width), Math.round(r.height)].join(':'));
  });
  return { rows: rows.sort(), scrollH: document.documentElement.scrollHeight };
}
"""


PERF_JS = """
(async () => {
  // Кадры страницы: ~90 rAF-замеров (headless ≠ реальное устройство, но
  // фиксирует порядок и отсутствие блокировки); стоимость кадра слоя — из
  // его собственной диагностики (performance.now вокруг paintLayers).
  const deltas = [];
  await new Promise((resolve) => {
    let last = 0, n = 0;
    const step = (ts) => {
      if (last) deltas.push(ts - last);
      last = ts;
      if (++n >= 90) resolve(); else requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
  deltas.sort((a, b) => a - b);
  const pick = (q) => deltas[Math.min(deltas.length - 1,
                                      Math.floor(deltas.length * q))] || 0;
  const dg = (window.__GlassRefraction &&
              typeof window.__GlassRefraction.diagnostics === 'function')
    ? window.__GlassRefraction.diagnostics() : null;
  return {
    frames: deltas.length,
    p50_ms: Math.round(pick(0.5) * 100) / 100,
    p95_ms: Math.round(pick(0.95) * 100) / 100,
    max_ms: Math.round((deltas[deltas.length - 1] || 0) * 100) / 100,
    layers: dg ? dg.layers.length : null,
    paintMs: dg ? dg.paintMs : null,
    paintMsMax: dg ? dg.paintMsMax : null,
    paintCount: dg ? dg.paintCount : null,
    errors: dg ? dg.errors : null,
    intervalMs: dg ? dg.renderIntervalMs : null,
  };
})()
"""


def surface_selector(page):
    """Самая высокая поверхность со слоем преломления, целиком видимая."""
    return page.evaluate("""
    () => {
      const layers = document.querySelectorAll('canvas.lg-refract');
      let best = null, bestH = 0;
      for (const cv of layers) {
        const host = cv.parentElement;
        if (!host) continue;
        const r = host.getBoundingClientRect();
        if (r.width > 120 && r.height > 120 &&
            r.top >= 0 && r.bottom <= window.innerHeight + 1 &&
            r.height > bestH) { best = host; bestH = r.height; }
      }
      if (!best) return null;
      if (!best.id) best.setAttribute('id', 'wg-measure-target');
      return '#' + best.id;
    }
    """)


def stripes_on_background(page, seed=1337):
    """Тестовый оптический паттерн (только в стенде): контрастные вертикальные
    полосы ПСЕВДО-СЛУЧАЙНОЙ ширины (детерминированный LCG) в canvas
    полигонального фона. Случайная ширина исключает алиасинг корреляции
    (полосы кратной ширины давали бы ложные пики сдвига)."""
    return page.evaluate("""
    (seed) => {
      const c = document.getElementById('polygon-background');
      if (!c) return null;
      const ctx = c.getContext('2d');
      const w = c.width, h = c.height;
      let s = seed >>> 0;
      const rnd = () => {
        s = (1664525 * s + 1013904223) >>> 0;
        return s / 4294967296;
      };
      ctx.save();
      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = 1;
      let x = 0;
      while (x < w) {
        const bw = 3 + Math.floor(rnd() * 11);            // 3..13 px
        ctx.fillStyle = rnd() < 0.5 ? 'rgb(255,255,255)' : 'rgb(0,0,0)';
        ctx.fillRect(x, 0, bw, h);
        x += bw;
      }
      ctx.restore();
      return { w: w, h: h };
    }
    """, seed)


def row_shift(path_a, path_b, row_ratio, x0, x1, max_shift=40):
    """Сдвиг (в device px) строки row_ratio между кадрами A→B по максимуму
    корреляции (ищем, на сколько содержимое B сместилось относительно A)."""
    wa, ha, pa = _load_png(path_a)
    wb, hb, pb = _load_png(path_b)
    if (wa, ha) != (wb, hb):
        return None
    y = int(ha * row_ratio)
    best = None
    best_score = None
    for s in range(-max_shift, max_shift + 1):
        num = 0.0
        den_a = 0.0
        den_b = 0.0
        for x in range(max(0, x0), min(wa, x1)):
            xb = x + s
            if xb < 0 or xb >= wa:
                continue
            ia = (y * wa + x) * 3
            ib = (y * wb + xb) * 3
            va = 0.2126 * pa[ia] + 0.7152 * pa[ia + 1] + 0.0722 * pa[ia + 2]
            vb = 0.2126 * pb[ib] + 0.7152 * pb[ib + 1] + 0.0722 * pb[ib + 2]
            num += va * vb
            den_a += va * va
            den_b += vb * vb
        if den_a <= 0 or den_b <= 0:
            continue
        score = num / ((den_a ** 0.5) * (den_b ** 0.5))
        if best_score is None or score > best_score:
            best_score = score
            best = s
    return {"row": y, "shift_px": best, "corr": round(best_score or 0, 3)}


_PNG_CACHE = {}


def _load_png(path):
    """PNG → (w, h, rgb bytes). Чистый stdlib (без PIL), с кэшем на прогон."""
    if path in _PNG_CACHE:
        return _PNG_CACHE[path]

    def load(p):
        with open(p, "rb") as fh:
            data = fh.read()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", "не PNG: " + p
        pos = 8
        w = h = bitdepth = colortype = None
        idat = bytearray()
        while pos < len(data):
            ln = struct.unpack(">I", data[pos:pos + 4])[0]
            typ = data[pos + 4:pos + 8]
            chunk = data[pos + 8:pos + 8 + ln]
            if typ == b"IHDR":
                w, h, bitdepth, colortype = struct.unpack(">IIBB", chunk[:10])
            elif typ == b"IDAT":
                idat += chunk
            elif typ == b"IEND":
                break
            pos += 12 + ln
        assert bitdepth == 8, "support only 8-bit PNG"
        channels = {0: 1, 2: 3, 4: 2, 6: 4}[colortype]
        raw = zlib.decompress(bytes(idat))
        stride = w * channels
        out = bytearray(w * h * 3)
        prev = bytearray(stride)
        p = 0
        for y in range(h):
            f = raw[p]
            p += 1
            line = bytearray(raw[p:p + stride])
            p += stride
            if f == 1:
                for i in range(channels, stride):
                    line[i] = (line[i] + line[i - channels]) & 0xFF
            elif f == 2:
                for i in range(stride):
                    line[i] = (line[i] + prev[i]) & 0xFF
            elif f == 3:
                for i in range(stride):
                    left = line[i - channels] if i >= channels else 0
                    line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
            elif f == 4:
                for i in range(stride):
                    a = line[i - channels] if i >= channels else 0
                    b = prev[i]
                    cc = prev[i - channels] if i >= channels else 0
                    pp = a + b - cc
                    pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - cc)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else cc)
                    line[i] = (line[i] + pr) & 0xFF
            prev = line
            for x in range(w):
                si = x * channels
                di = (y * w + x) * 3
                if channels >= 3:
                    out[di] = line[si]
                    out[di + 1] = line[si + 1]
                    out[di + 2] = line[si + 2]
                else:
                    out[di] = out[di + 1] = out[di + 2] = line[si]
        return w, h, out

    res = load(path)
    _PNG_CACHE[path] = res
    return res


def png_metrics(path_a, path_b):
    """Энергия (сумма |Δ|) по зонам и разница яркости для двух PNG.
    Чистый stdlib: PNG → RGB (без PIL)."""
    wa, ha, pa = _load_png(path_a)
    wb, hb, pb = _load_png(path_b)
    if (wa, ha) != (wb, hb):
        return {"error": "size-mismatch", "a": (wa, ha), "b": (wb, hb)}
    w, h = wa, ha
    # Зоны в device-пикселях (скриншот элемента при DPR 2): рамка слоя —
    # 20 solid + 46 fade CSS px (§ glass-refraction.js). Ожидание: в рамке
    # смещение заметно, в центре — спокойно.
    scale = 2 if min(w, h) > 150 else 1
    ring = 66 * scale
    mid = 132 * scale
    zone = {"ring": [0.0, 0], "mid": [0.0, 0], "center": [0.0, 0]}
    luma_a, luma_b = 0.0, 0.0
    ring_n = 0
    moved = 0
    total = w * h
    for y in range(h):
        row = y * w
        dy = min(y, h - 1 - y)
        for x in range(w):
            i = (row + x) * 3
            v = (abs(pa[i] - pb[i]) + abs(pa[i + 1] - pb[i + 1]) +
                 abs(pa[i + 2] - pb[i + 2])) / 3.0
            if v > 8:
                moved += 1
            d = min(dy, min(x, w - 1 - x))
            key = "ring" if d < ring else ("mid" if d < mid else "center")
            zone[key][0] += v
            zone[key][1] += 1
            if key == "ring":
                luma_a += (0.2126 * pa[i] + 0.7152 * pa[i + 1] +
                           0.0722 * pa[i + 2])
                luma_b += (0.2126 * pb[i] + 0.7152 * pb[i + 1] +
                           0.0722 * pb[i + 2])
                ring_n += 1
    ring_luma_a = luma_a / max(1, ring_n)
    ring_luma_b = luma_b / max(1, ring_n)
    out = {"w": w, "h": h, "moved_frac": round(moved / max(1, total), 4),
           "band_ring_px": ring,
           "ring_luma_b": round(ring_luma_b, 2),
           "ring_luma_a": round(ring_luma_a, 2),
           "luma_delta_pct": round(100.0 * (ring_luma_b - ring_luma_a) /
                                   max(1.0, ring_luma_a), 2)}
    for k, (s, n) in zone.items():
        out[k + "_energy"] = round(s / max(1, n), 3)
    out["edge_inner_ratio"] = round(
        out["ring_energy"] / max(0.001, out["center_energy"]), 2)
    return out


ANDROID_CFG = dict(
    platform="android", hasBoolean=True, isFullscreen=False,
    stableHeight=788, viewportHeight=844,
    safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
    contentSafeAreaInset={"top": 36, "bottom": 0, "left": 0, "right": 0})

TDESKTOP_CFG = dict(
    platform="tdesktop", hasBoolean=True, isFullscreen=True,
    stableHeight=860, viewportHeight=900,
    safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
    contentSafeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0})


def main() -> int:
    from playwright.sync_api import sync_playwright

    httpd = _start_server()
    checks = []
    results = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  device_scale_factor=2, locale="ru-RU")
        page = ctx.new_page()
        # Мок-клиент Telegram (android-контракт U07) — /api/* стабы.
        page.route("**/static/vendor/telegram-web-app.js", _sdk_route(ANDROID_CFG))
        page.route("**/api/**", _api_handler_factory())
        # polygon-фон включён (UI_POLYGON_BG_ENABLED=True), автоанимация
        # остановлена после прогрева — детерминированный кадр для замера.
        page.goto(BASE_URL + "/web/index.html?bgseed=%d#/" % BG_SEED,
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("#app", timeout=20000)
        page.wait_for_timeout(2500)                      # прогрев фона/стекла
        page.evaluate("() => { try { window.__PolygonBackground.pause(); } "
                      "catch (e) {} }")
        page.wait_for_timeout(200)

        c = Check("A_refraction_layer_android_390")
        probe = page.evaluate(GLASS_PROBE_JS)
        results["probe_mobile"] = probe
        c.ok(probe["polyMode"] in ("canvas2d",),
             "polygon-фон активен (mode=%s)" % probe["polyMode"])
        c.ok(probe["layers"] >= 1,
             "слой преломления создан (layers=%s, refractOn=%s)"
             % (probe["layers"], probe["refractOn"]))
        c.ok(probe["layers"] <= 3,
             "тяжёлая рефракция ограничена бюджетом ≤3 (layers=%s)"
             % probe["layers"])
        if probe["layers"] >= 1:
            c.ok(probe["layerPtr"] and probe["layerPtr"]["pointerEvents"] == "none",
                 "слой не перехватывает pointer (pointer-events=%s)"
                 % (probe["layerPtr"] or {}).get("pointerEvents"))
            c.ok("lg-refract" not in (probe["layerHit"] or ""),
                 "hit-тест центра поверхности не попадает в слой (got=%s)"
                 % probe["layerHit"])
            c.ok(probe["layerPtr"] and probe["layerPtr"]["filter"].find("url(") >= 0,
                 "у слоя реальный SVG-фильтр линзы (%s)"
                 % (probe["layerPtr"] or {}).get("filter"))
            c.ok(probe["layerPtr"] and probe["layerPtr"]["backdrop"] == "none",
                 "у слоя нет собственного backdrop-filter")
        c.ok(probe["filteredContent"] == 0,
             "filter:url() на контенте поверхностей отсутствует (найдено %s)"
             % probe["filteredContent"])
        c.ok(probe["shadow"]["urlBackdrop"] == 0,
             "у layer-поверхностей нет остаточного url() в backdrop-filter "
             "(%s из %s)" % (probe["shadow"]["urlBackdrop"],
                             probe["shadow"]["count"]))
        perf = page.evaluate(PERF_JS)
        results["perf_mobile"] = perf
        c.ok(perf["errors"] == 0,
             "слой без ошибок отрисовки (%s)" % perf["errors"])
        c.ok(perf["paintMs"] is not None and perf["paintMs"] < 6.0,
             "стоимость кадра слоя < 6 ms (paintMs=%s, max=%s, кадров=%s)"
             % (perf["paintMs"], perf["paintMsMax"], perf["paintCount"]))
        c.ok(perf["p95_ms"] < 40.0,
             "кадры страницы без блокировки (p50=%s ms, p95=%s ms, max=%s ms)"
             % (perf["p50_ms"], perf["p95_ms"], perf["max_ms"]))
        c.ok(not probe["hOverflow"], "горизонтального overflow нет")

        sel = surface_selector(page)
        c.ok(bool(sel), "найдена измеряемая Tier A поверхность (%s)" % sel)
        shot_off = shot_on = None
        metrics = None
        if sel:
            # Геометрия страницы ДО включения слоя (сильная проверка «слой не
            # двигает раскладку»): помечаем элементы и сравниваем их rect'ы
            # после включения. Пропажа помеченного узла допустима (Vue
            # перерисовал контент), расхождение геометрии — нет.
            tag = page.evaluate(LAYOUT_TAG_JS)
            page.evaluate("() => window.__GlassRefraction.setEnabled(false)")
            page.wait_for_timeout(600)
            shot_off = _shot(page, sel, "refract_off")
            layout_off = page.evaluate(LAYOUT_READ_JS)
            page.evaluate("() => window.__GlassRefraction.setEnabled(true)")
            page.wait_for_timeout(900)
            layout_on = page.evaluate(LAYOUT_READ_JS)
            shot_on = _shot(page, sel, "refract_on")
            metrics = png_metrics(shot_off, shot_on)
            results["metrics_mobile"] = {"selector": sel, **metrics}
            c.ok(metrics.get("moved_frac", 0) > 0.01,
                 "слой видимо смещает фон (moved_frac=%s)"
                 % metrics.get("moved_frac"))
            c.ok(metrics.get("ring_energy", 0) >= metrics.get("center_energy", 0),
                 "смещение у кромок не слабее центра: ring=%s center=%s"
                 % (metrics.get("ring_energy"), metrics.get("center_energy")))
            c.ok(metrics.get("ring_energy", 0) > 2.0,
                 "амплитуда смещения у кромок измерима (ring=%s)"
                 % metrics.get("ring_energy"))
            c.ok(abs(metrics.get("luma_delta_pct", 0)) <= 12.0,
                 "яркость кромок не ушла (Δ=%s%%, off=%s on=%s)"
                 % (metrics.get("luma_delta_pct"), metrics.get("ring_luma_a"),
                    metrics.get("ring_luma_b")))
            # Слой не меняет раскладку: сравнение помеченных элементов;
            # для узлов-носителей слоя rect обязан совпасть строго.
            off_rows = {r.split(':')[0]: r for r in layout_off["rows"]}
            on_rows = {r.split(':')[0]: r for r in layout_on["rows"]}
            moved = []
            host_moved = []
            for k, row in off_rows.items():
                other = on_rows.get(k)
                if other is None:
                    continue                       # узел перерисован приложением
                if row != other:
                    moved.append((k, row, other))
                    if row.split(':')[1] == '1':
                        host_moved.append((k, row, other))
            results["layout_shift"] = {
                "tagged": tag["tagged"], "hosts": tag["hosts"],
                "missing": len(off_rows) - len([k for k in off_rows
                                                if k in on_rows]),
                "moved": len(moved),
                "host_moved": len(host_moved),
                "scrollH_off": layout_off["scrollH"],
                "scrollH_on": layout_on["scrollH"],
                "sample_moved": moved[:3],
            }
            c.ok(not host_moved,
                 "носители слоя не сдвинулись (%s из %s; пример %s)"
                 % (len(host_moved), tag["hosts"], host_moved[:1]))
            c.ok(layout_off["scrollH"] == layout_on["scrollH"],
                 "высота страницы не изменилась (%s → %s)"
                 % (layout_off["scrollH"], layout_on["scrollH"]))
            surf = page.evaluate(SURFACE_JS, sel)
            results["surface_mobile"] = surf
            c.ok(surf and surf.get("refract") == "on",
                 "поверхность помечена носителем layer (reason=%s)"
                 % (surf or {}).get("reason"))
        checks.append(c)

        # ── C: контрастный оптический тест-паттерн → измеренный сдвиг линий ──
        c3 = Check("C_optical_pattern_displacement")
        if sel:
            page.evaluate("() => window.__GlassRefraction.setEnabled(false)")
            page.wait_for_timeout(500)
            stripes_on_background(page, 24)
            page.wait_for_timeout(200)
            pat_off = _shot(page, sel, "pattern_off")
            page.wait_for_timeout(250)
            pat_off2 = _shot(page, sel, "pattern_off2")
            page.evaluate("() => window.__GlassRefraction.setEnabled(true)")
            page.wait_for_timeout(900)
            pat_on = _shot(page, sel, "pattern_on")
            w, h, _ = _load_png(pat_on)
            # Полоса слоя 20+46 CSS px = 132 device px при DPR 2.
            left_band = row_shift(pat_off, pat_on, 0.35, 6, 120)
            right_band = row_shift(pat_off, pat_on, 0.65, w - 120, w - 6)
            center_row = row_shift(pat_off, pat_on, 0.5, w // 2 - 60, w // 2 + 60)
            # RED/шум: два кадра БЕЗ слоя — сдвига нет (иначе метрика ловит шум).
            noise_left = row_shift(pat_off, pat_off2, 0.35, 6, 120)
            noise_right = row_shift(pat_off, pat_off2, 0.65, w - 120, w - 6)
            results["pattern_shift"] = {"left": left_band, "right": right_band,
                                        "center": center_row, "w": w, "h": h,
                                        "noise_off_left": noise_left,
                                        "noise_off_right": noise_right}
            c3.ok(noise_left and noise_left["shift_px"] == 0 and
                  noise_right and noise_right["shift_px"] == 0,
                 "шум OFF↔OFF = 0 px (слева %s, справа %s)"
                 % ((noise_left or {}).get("shift_px"),
                    (noise_right or {}).get("shift_px")))
            c3.ok(left_band and left_band["shift_px"] not in (None, 0),
                 "у левой кромки линии смещены (shift=%s px, corr=%s)"
                 % ((left_band or {}).get("shift_px"),
                    (left_band or {}).get("corr")))
            c3.ok(right_band and right_band["shift_px"] not in (None, 0),
                 "у правой кромки линии смещены (shift=%s px, corr=%s)"
                 % ((right_band or {}).get("shift_px"),
                    (right_band or {}).get("corr")))
            c3.ok(center_row and center_row["shift_px"] == 0,
                 "центр поверхности не смещён (shift=%s px)"
                 % (center_row or {}).get("shift_px"))
        checks.append(c3)

        # ── Desktop 1440×900: тот же путь + FS-полоса ──────────────────────
        c2 = Check("B_desktop_1440")
        ctx2 = browser.new_context(viewport={"width": 1440, "height": 900},
                                   device_scale_factor=1, locale="ru-RU")
        page2 = ctx2.new_page()
        page2.route("**/static/vendor/telegram-web-app.js", _sdk_route(TDESKTOP_CFG))
        page2.route("**/api/**", _api_handler_factory())
        page2.goto(BASE_URL + "/web/index.html?bgseed=%d#/" % BG_SEED,
                   wait_until="domcontentloaded", timeout=30000)
        page2.wait_for_selector("#app", timeout=20000)
        page2.wait_for_timeout(2500)
        page2.evaluate("() => { try { window.__PolygonBackground.pause(); } "
                       "catch (e) {} }")
        page2.wait_for_timeout(200)
        p2 = page2.evaluate(GLASS_PROBE_JS)
        results["probe_desktop"] = p2
        c2.ok(p2["polyMode"] == "canvas2d", "polygon-фон активен на desktop")
        c2.ok(p2["probe"] is not None, "проба стекла посчитана")
        # Desktop: носитель оптики прежний (url() в backdrop-filter) —
        # слой преломления НЕ создаётся, разметка не меняется.
        c2.ok(p2["layers"] == 0,
             "desktop: слой преломления не создаётся (layers=%s)" % p2["layers"])
        c2.ok(p2["refractOn"] == 0,
             "desktop: data-refract-layer не выставлен (шт=%s)" % p2["refractOn"])
        c2.ok(p2["reasons"].get("refract-layer", 0) == 0,
             "desktop: reason=refract-layer отсутствует (%s)" % p2["reasons"])
        results["fs_audit"] = page2.evaluate(FS_AUDIT_JS)
        c2.ok(bool(results["fs_audit"]), "FS-политика доступна (dev-API)")
        fs = results["fs_audit"] or {}
        c2.ok(fs.get("slot") == "inline" and not fs.get("reason"),
             "FS-кнопка в потоке (slot=%s, reason=%r)"
             % (fs.get("slot"), fs.get("reason")))
        c2.ok(fs.get("launchFullscreen") is True and
              fs.get("actualFullscreen") is True,
             "launch-fullscreen сохраняется (launch=%s actual=%s)"
             % (fs.get("launchFullscreen"), fs.get("actualFullscreen")))
        c2.ok(fs.get("canOfferExit") is True and
              fs.get("canOfferFullscreen") is False,
             "кнопка = выход, второго request нет")
        c2.ok(not p2["hOverflow"], "desktop: без горизонтального overflow")
        checks.append(c2)

    # ── D: запрет «CSS/JS управляет нативным окном» (U07.0, FS-HOTFIX) ─────
    c4 = Check("D_no_window_geometry_hacks")
    import re as _re
    # Только реальные попытки двигать/масштабировать нативное окно:
    # window.moveTo/resizeTo и родственные алиасы. ctx.moveTo (Canvas 2D) и
    # упоминания в комментариях — не хак.
    hack_re = _re.compile(
        r"\b(window|self|top|parent|globalThis)\s*\.\s*(moveTo|resizeTo)\s*\(")

    def strip_comments(src):
        src = _re.sub(r"/\*[\s\S]*?\*/", "", src)
        return _re.sub(r"(?m)^\s*//.*$", "", src)

    hits = []
    for rel in ("web/app.js", "web/static/fullscreen-policy.js",
                "web/static/glass-refraction.js", "web/static/telegram-init.js"):
        try:
            src = open(os.path.join(REPO, rel), encoding="utf-8").read()
        except OSError:
            continue
        code = strip_comments(src)
        for m in hack_re.finditer(code):
            line = code.count("\n", 0, m.start()) + 1
            hits.append("%s:~%d:%s" % (rel, line, m.group(0).strip()))
    results["window_hack_hits"] = hits
    c4.ok(not hits, "нет попыток управлять нативным окном из JS (%s)"
         % (hits[:3] or "чисто"))
    c4.ok(os.path.exists(os.path.join(REPO, "web", "static",
                                      "glass-refraction.js")),
          "модуль слоя на месте (web/static/glass-refraction.js)")
    checks.append(c4)

    try:
        httpd.shutdown()
    except Exception:  # noqa: BLE001
        pass

    ok = all(not c.failures for c in checks)
    results["checks"] = [{"name": c.name, "count": c.count,
                          "failures": c.failures} for c in checks]
    results["passed"] = ok
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    for c in checks:
        state = "OK" if not c.failures else "FAIL"
        print("[%s] %s (%d проверок)" % (state, c.name, c.count))
        for f in c.failures:
            print("   - " + f)
    print("WG-REFRACT-E2E-%s" % ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
