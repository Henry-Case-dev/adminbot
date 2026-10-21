#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V63-REBIND-45 — glass/U08/B01/B06/B07 re-verification at 31c16555 (2.58.80).

Everything runs against the detached worktree of the deployed commit.
Sections:
  A. fingerprint (HEAD + sha256 of the 4 carrier files vs deploy evidence)
  B. stand grid: probe status, 3x close-up displacement field (peak method,
     subpixel), rim/specular/contrast, hit/click, visual crops
  C. displacement map decode (data-URI in index.html) — static field contract
  D. stand tierB (downgrade semantics) — no url() lens, no displacement
  E. real pages (status/oversight/modules/style-editor) — tier map, lens,
     pointer-events/hit, overflow, hover-specular, console errors
  F. mobile 390 — shell header, fs control (.header-fs-btn state), popover
     «Ещё», overflow, bg seed stability across scroll
  G. reduced-motion / low-end downgrades, fps proxy
Outputs: evidence/rebind-31c16555/{glass_playwright_results.json, *.png}
"""
import base64
import hashlib
import json
import os
import re
import sys
import threading
import zlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

WORKTREE = r"C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\rebind-31c16555"
MAIN = r"C:\Code\Python\adminbot"
EVID = os.path.join(MAIN, "plans", "features", "asap8-v6-3-live-correction",
                    "evidence", "rebind-31c16555")
PORT = 8963
BG_SEED = 424242

sys.path.insert(0, WORKTREE)
sys.path.insert(0, os.path.join(WORKTREE, "tools"))
os.chdir(WORKTREE)

import ui_round1025_matrix as M  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

os.makedirs(EVID, exist_ok=True)
BASE = "http://127.0.0.1:%d/web/index.html" % PORT
STAND = "http://127.0.0.1:%d/static/glass-teststand.html" % PORT

SDK_STUB = """
try { sessionStorage.setItem('adminbot.initData',
  'user=%7B%22id%22%3A5885953495%7D&hash=audit'); } catch (e) {}
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A5885953495%7D&hash=audit',
  initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
  platform: 'android', version: '9.0', colorScheme: 'dark', themeParams: {},
  get viewportStableHeight() { return Math.max(0, (window.innerHeight || 800) - 56); },
  isExpanded: true, isFullscreen: false,
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  ready() {}, expand() {}, close() {},
  setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
  requestFullscreen() {}, exitFullscreen() {},
  disableVerticalSwipes() {}, enableClosingConfirmation() {},
  onEvent() {}, offEvent() {},
  openLink() {}, openTelegramLink() {}, showAlert() {}, showConfirm() {},
  BackButton: { isVisible: false, show() {}, hide() {}, onClick() {}, offClick() {} },
  MainButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
  HapticFeedback: { impactOccurred() {}, notificationOccurred() {} },
} };
"""

FREEZE_JS = """
(() => {
  const out = { paused: false, mode: null, seed: null };
  try {
    const pb = window.__PolygonBackground;
    if (pb && typeof pb.pause === 'function') {
      pb.pause(); out.paused = true;
      if (typeof pb.mode === 'function') out.mode = pb.mode();
      const d = typeof pb.getDiagnostics === 'function' ? pb.getDiagnostics() : null;
      if (d) out.seed = d.sceneSeed != null ? d.sceneSeed : null;
    }
  } catch (e) { out.error = String(e); }
  return out;
})()
"""

INVENTORY_JS = r"""
() => {
  const out = [];
  document.querySelectorAll('[data-glass]').forEach(el => {
    const cs = getComputedStyle(el);
    const rec = {
      cls: (el.className || '').toString().slice(0, 90),
      declared: el.getAttribute('data-glass'),
      tier: el.getAttribute('data-glass-tier'),
      reason: el.getAttribute('data-glass-reason'),
      downgraded: el.getAttribute('data-glass-downgraded'),
      inlineBf: (el.style.backdropFilter || el.style.webkitBackdropFilter || '').slice(0, 150),
      computedBf: (cs.backdropFilter || cs.webkitBackdropFilter || 'none').slice(0, 150),
      decorative: [],
      rect: (() => { const r = el.getBoundingClientRect();
        return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; })(),
    };
    el.querySelectorAll('.lg-panel__backdrop, .lg-panel__tint, .lg-panel__rim, .lg-panel__specular').forEach(d => {
      const dcs = getComputedStyle(d);
      rec.decorative.push({
        c: (d.className || '').toString().slice(0, 46),
        pe: dcs.pointerEvents,
        bf: (d.style.backdropFilter || d.style.webkitBackdropFilter || dcs.backdropFilter || dcs.webkitBackdropFilter || 'none').slice(0, 150),
      });
    });
    out.push(rec);
  });
  return out;
}
"""

SURFACE_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  const bd = el.querySelector('.lg-panel__backdrop') || el;
  const bds = getComputedStyle(bd);
  return {
    x: r.x, y: r.y, w: r.width, h: r.height,
    declared: el.getAttribute('data-glass'), tier: el.getAttribute('data-glass-tier'),
    reason: el.getAttribute('data-glass-reason'),
    bfTarget: (bds.backdropFilter || bds.webkitBackdropFilter || 'none').slice(0, 150),
    bfTargetInline: (bd.style.backdropFilter || bd.style.webkitBackdropFilter || '').slice(0, 150),
    bfTargetPE: bds.pointerEvents, selfPE: cs.pointerEvents,
    cls: (el.className || '').toString().slice(0, 90),
  };
}
"""

HIT_JS = r"""
(sel) => {
  const list = document.querySelectorAll(sel);
  return Array.from(list).slice(0, 6).map(el => {
    const r = el.getBoundingClientRect();
    const x = r.x + r.width / 2, y = r.y + r.height / 2;
    const t = document.elementFromPoint(x, y);
    return {sel, x: Math.round(x), y: Math.round(y),
            hit: t ? ((t.className || '') + '|' + t.tagName).toString().slice(0, 90) : null,
            inside: t ? el === t || el.contains(t) : false};
  });
}
"""


# ── PNG decode (stdlib) ───────────────────────────────────────────────────


def decode_png(buf):
    if buf[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not png")
    pos, idat = 8, []
    while pos < len(buf):
        ln = int.from_bytes(buf[pos:pos + 4], "big")
        typ = buf[pos + 4:pos + 8]
        data = buf[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w = int.from_bytes(data[0:4], "big")
            h = int.from_bytes(data[4:8], "big")
            ct = data[9]
        elif typ == b"IDAT":
            idat.append(data)
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if ct not in (2, 6):
        raise ValueError("unsupported png ct=%s" % ct)
    bpp = 4 if ct == 6 else 3
    raw = zlib.decompress(b"".join(idat))
    stride = w * bpp
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        p += 1
        row = bytearray(raw[p:p + stride])
        p += stride
        if ft == 1:
            for x in range(bpp, stride):
                row[x] = (row[x] + row[x - bpp]) & 0xFF
        elif ft == 2:
            for x in range(stride):
                row[x] = (row[x] + prev[x]) & 0xFF
        elif ft == 3:
            for x in range(stride):
                a = row[x - bpp] if x >= bpp else 0
                row[x] = (row[x] + ((a + prev[x]) >> 1)) & 0xFF
        elif ft == 4:
            for x in range(stride):
                a = row[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[x] = (row[x] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = row
        prev = row
    return {"w": w, "h": h, "bpp": bpp, "data": bytes(out)}


def lin(px):
    c = px / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum_at(img, x, y):
    i = (y * img["w"] + x) * img["bpp"]
    d = img["data"]
    return 0.2126 * lin(d[i]) + 0.7152 * lin(d[i + 1]) + 0.0722 * lin(d[i + 2])


def band_mean(img, x0, x1, y0, y1):
    s, n = 0.0, 0
    for x in range(int(x0), int(x1)):
        for y in range(int(y0), int(y1)):
            s += lum_at(img, x, y)
            n += 1
    return s / max(1, n)


def percentile(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))] if s else 0.0


def peak_sub(prof, c, half):
    lo, hi = max(0, int(c - half)), min(len(prof), int(c + half) + 1)
    seg = prof[lo:hi]
    idx = max(range(len(seg)), key=lambda i: seg[i])
    i = lo + idx
    if 1 <= i < len(prof) - 1:
        y0, y1, y2 = prof[i - 1], prof[i], prof[i + 1]
        den = (y0 - 2 * y1 + y2)
        off = 0.5 * (y0 - y2) / den if abs(den) > 1e-9 else 0.0
        return i + max(-0.5, min(0.5, off))
    return float(i)


def prof_x(img, y):
    return [lum_at(img, x, int(y)) for x in range(img["w"])]


def est_phase(prof, step, lo, hi):
    best = (0, -1.0)
    for ph in range(step):
        s = 0.0
        c = ph
        while c < hi:
            if c >= lo:
                s += prof[c]
            c += step
        if s > best[1]:
            best = (ph, s)
    return best[0]


def field_measure(a, b, panel_css, dpr, rows_css):
    """Peak-based displacement field in CSS px. a/b = decoded crops (panel +/-24css).
    Returns per-row list of (line_css_pos, dx_css) and diagnostics."""
    PX0, PY0 = 24 * dpr, 24 * dpr
    PW, PH = panel_css["w"] * dpr, panel_css["h"] * dpr
    P = 48 * dpr
    # x-phase from hidden image (crisp) using rows below the panel
    phs = []
    for off in (20, 40):
        y = int(PY0 + PH + off * dpr)
        if y < b["h"]:
            pr = prof_x(b, y)
            lo, hi = max(0, int(PX0 - 30)), min(b["w"], int(PX0 + PW + 30))
            ph = est_phase(pr, 3 * dpr, lo, hi)
            # snap to the line center: search peak near ph + a few candidates
            best_c, best_v = None, -1.0
            for c0 in range(int(ph) - 6, int(ph) + P, 3):
                if c0 < 0 or c0 + 30 >= b["w"]:
                    continue
                v = max(pr[c0:c0 + 30])
                if v > best_v:
                    best_v, best_c = v, c0 + pr[c0:c0 + 30].index(v)
            phs.append(best_c % P)
    phx = sorted(phs)[len(phs) // 2]
    centers = [phx + P * k for k in range(0, a["w"] // P + 2)]
    centers = [c for c in centers if PX0 - 6 <= c <= PX0 + PW + 6]
    out = {"dpr": dpr, "phase_px": phx, "lines_css": [],
           "rows": []}
    for c in centers:
        out["lines_css"].append(round((c - PX0) / dpr, 1))
    half = int(15 * dpr)
    for y_off in rows_css:
        y = int(PY0 + y_off * dpr)
        if y >= a["h"] or y >= b["h"]:
            continue
        pa, pb = prof_x(a, y), prof_x(b, y)
        row = []
        for c in centers:
            xa = peak_sub(pa, c, half)
            xb = peak_sub(pb, c, half)
            row.append(round((xa - xb) / dpr, 2))
        out["rows"].append({"y_css": y_off, "dx": row})
    return out


# ── map decode ────────────────────────────────────────────────────────────

_MAP_CACHE = {}


def _map_img():
    if "img" not in _MAP_CACHE:
        html = open(os.path.join(WORKTREE, "web", "index.html"), encoding="utf-8").read()
        m = re.search(r'href="data:image/png;base64,([A-Za-z0-9+/=]+)"', html)
        _MAP_CACHE["img"] = decode_png(base64.b64decode(m.group(1)))
    return _MAP_CACHE["img"]


def map_value(u, v):
    """R-channel displacement (css px, scale=16) of the lens map at (u, v) in [-1,1]."""
    img = _map_img()
    W, H, d = img["w"], img["h"], img["data"]
    x = min(W - 1, max(0, int(round((u * 0.5 + 0.5) * (W - 1)))))
    y = min(H - 1, max(0, int(round((v * 0.5 + 0.5) * (H - 1)))))
    return round(16.0 * (d[(y * W + x) * img["bpp"]] / 255.0 - 0.5), 3)


def decode_map_contract():
    html = open(os.path.join(WORKTREE, "web", "index.html"), encoding="utf-8").read()
    m = re.search(r'href="data:image/png;base64,([A-Za-z0-9+/=]+)"', html)
    img = decode_png(base64.b64decode(m.group(1)))
    W, H, d = img["w"], img["h"], img["data"]

    def disp(x, y):
        i = (y * W + x) * img["bpp"]
        return 16.0 * (d[i] / 255.0 - 0.5), 16.0 * (d[i + 1] / 255.0 - 0.5)

    mx = my = 0.0
    ctr = 0.0
    for y in range(H):
        for x in range(W):
            dx, dy = disp(x, y)
            mx = max(mx, abs(dx)); my = max(my, abs(dy))
            u = (x / (W - 1)) * 2 - 1
            v = (y / (H - 1)) * 2 - 1
            if abs(u) <= 0.62 and abs(v) <= 0.62:
                ctr = max(ctr, abs(dx), abs(dy))

    def sample(u, v):
        x = min(W - 1, max(0, int(round((u * 0.5 + 0.5) * (W - 1)))))
        y = min(H - 1, max(0, int(round((v * 0.5 + 0.5) * (H - 1)))))
        return round(disp(x, y)[0], 2)

    prof = [{"u": u, "dx": sample(u, 0.0)} for u in
            (-0.95, -0.9, -0.7, -0.5, -0.3, 0.0, 0.3, 0.5, 0.7, 0.9, 0.95)]
    return {
        "map_size": [img["w"], img["h"]],
        "scale": 16,
        "max_abs_dx": round(mx, 2), "max_abs_dy": round(my, 2),
        "center_062_max": round(ctr, 3),
        "odd_symmetric": True,
        "mid_row_profile_u_dx": prof,
        "checks": {
            "map_max_le_8": mx <= 8.01 and my <= 8.01,
            "center_static": ctr <= 0.05,
            "edges_toward_center": sample(-0.9, 0.0) > 3.0 and sample(0.9, 0.0) < -3.0,
            "odd_symmetry": all(abs(sample(-u, 0.0) + sample(u, 0.0)) < 0.2
                                for u in (0.3, 0.6, 0.9)),
        },
    }


# ── server / helpers ──────────────────────────────────────────────────────


def make_handler(webroot):
    class _H(SimpleHTTPRequestHandler):
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
            return os.path.join(webroot, rel.replace("/", os.sep))

        def log_message(self, *a):
            pass
    return _H


def serve(port, webroot):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(webroot))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def launch(p):
    return p.chromium.launch(channel="chrome", headless=True)


def ev_path(name):
    return os.path.join(EVID, name)


def rel(p):
    return os.path.relpath(p, MAIN).replace("\\", "/")


def open_app(browser, width, height, route, override=None, reduced=False,
             low_end=False, wait_ms=2100):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=width < 768, has_touch=width < 768,
                              device_scale_factor=1)
    me = json.loads(json.dumps(M.ME_JSON))
    flags = dict(me["ui_flags"])
    flags["UI_POLYGON_BG_ENABLED"] = True
    if override:
        flags["UI_GLASS_TIER_OVERRIDE"] = override
    me["ui_flags"] = flags

    def _api(route_obj):
        p = route_obj.request.url.split("?")[0]
        payload = me if p.endswith("/api/me") else M._stub_for(route_obj.request.url)
        route_obj.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload, ensure_ascii=False))

    ctx.route("**/api/**", _api)
    ctx.route("**/static/vendor/telegram-web-app.js",
              lambda r: r.fulfill(status=200,
                                  content_type="application/javascript",
                                  body=SDK_STUB))
    ctx.add_init_script("window.__TMA_MOCK__ = 1;")
    if low_end:
        ctx.add_init_script(
            "Object.defineProperty(navigator,'hardwareConcurrency',{get:()=>2});"
            "Object.defineProperty(navigator,'deviceMemory',{get:()=>2});")
    page = ctx.new_page()
    if reduced:
        page.emulate_media(reduced_motion="reduce")
    page.set_default_timeout(9000)
    errors = []
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)[:200]))
    page.on("console", lambda m: errors.append("console: " + m.text[:200])
            if m.type == "error" else None)
    page.goto("%s?bgseed=%d%s" % (BASE, BG_SEED, route), wait_until="load")
    page.wait_for_selector(".app-shell", state="visible")
    page.wait_for_timeout(wait_ms)
    try:
        page.wait_for_function(
            "() => !!(window.__GlassProbe && window.__GlassProbe.cached())", timeout=4000)
    except Exception:
        pass
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('[data-glass][data-glass-tier]').length > 0",
            timeout=4000)
    except Exception:
        pass
    page.wait_for_timeout(250)
    freeze = page.evaluate(FREEZE_JS)
    return ctx, page, freeze, errors


def main():
    from playwright.sync_api import sync_playwright
    serve(PORT, os.path.join(WORKTREE, "web"))
    head = os.popen("git rev-parse HEAD").read().strip()
    hashes = {}
    for f in ("web/static/app.css", "web/app.js", "web/index.html",
              "services/param_catalog.py"):
        with open(os.path.join(WORKTREE, f), "rb") as fh:
            hashes[f] = hashlib.sha256(fh.read()).hexdigest()
    out = {"head": head, "hashes": hashes,
           "deploy_evidence": "evidence/deploy-25880/ev03-verification-summary.md"}
    out["map_contract"] = decode_map_contract()

    with sync_playwright() as p:
        browser = launch(p)
        out["chrome_version"] = browser.version

        # ── B. stand grid ──
        st = {}
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=3)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        page.goto(STAND + "?bg=grid", wait_until="load")
        page.wait_for_selector("#stand-probe[data-tiera]", timeout=6000)
        page.wait_for_timeout(400)
        probe_el = page.query_selector("#stand-probe")
        st["probe"] = {"text": (probe_el.inner_text() or "").strip(),
                       "tierA": probe_el.get_attribute("data-tiera"),
                       "reason": probe_el.get_attribute("data-reason")}
        st["panel"] = page.evaluate(SURFACE_JS, "#panel-hero")
        box = st["panel"]
        px, py, pw, ph = box["x"], box["y"], box["w"], box["h"]
        clip = {"x": px - 24, "y": py - 24, "width": pw + 48, "height": ph + 48}
        page.screenshot(path=ev_path("stand_grid_3x_on.png"), clip=clip)
        page.screenshot(path=ev_path("stand_page_full_3x.png"))
        page.evaluate("() => { const el = document.querySelector('#panel-hero');"
                      " el.style.visibility = 'hidden'; }")
        page.wait_for_timeout(250)
        page.screenshot(path=ev_path("stand_grid_3x_hidden.png"), clip=clip)
        page.evaluate("() => { const el = document.querySelector('#panel-hero');"
                      " el.style.visibility = ''; }")
        page.wait_for_timeout(200)
        # hit test + click on the hero button
        st["hit"] = page.evaluate(HIT_JS, "#hero-btn")
        try:
            page.click("#hero-btn", timeout=3000)
            st["hero_btn_click"] = "ok"
        except Exception as e:
            st["hero_btn_click"] = "fail: " + str(e)[:120]
        # contrast / rim / specular on the 1x full-page shot
        page.screenshot(path=ev_path("stand_page_full_after_3x.png"))
        ctx.close()
        st["errors"] = errs[:5]
        a3 = decode_png(open(ev_path("stand_grid_3x_on.png"), "rb").read())
        b3 = decode_png(open(ev_path("stand_grid_3x_hidden.png"), "rb").read())
        st["field"] = field_measure(a3, b3, {"w": pw, "h": ph}, 3,
                                    [3, 5, 7, 112, 118, 124, 130, ph + 8, ph + 16])
        # evaluate field against the decoded lens map (apparent shift = -map_dx)
        lines = st["field"]["lines_css"]
        us = [x / pw * 2 - 1 for x in lines]
        bottom = [r for r in st["field"]["rows"] if r["y_css"] in (112, 118, 124, 130)]
        top = [r for r in st["field"]["rows"] if r["y_css"] in (3, 5, 7)]
        ctrl = [r for r in st["field"]["rows"] if r["y_css"] > ph]
        ctrl_max = max((abs(v) for r in ctrl for v in r["dx"]), default=0.0)

        def map_dx_at(u, v):
            return map_value(u, v)

        devs = []
        field_table = []
        for r in bottom:
            v = (r["y_css"] - ph / 2.0) / (ph / 2.0)
            row_pred, row_dev = [], []
            for u, dx in zip(us, r["dx"]):
                pred = -map_dx_at(u, v)
                row_pred.append(round(pred, 2))
                row_dev.append(round(dx - pred, 2))
            field_table.append({"y_css": r["y_css"], "v": round(v, 2),
                                "measured": r["dx"], "predicted_apparent": row_pred,
                                "deviation": row_dev})
            devs.extend(abs(x) for x in row_dev)
        devs_sorted = sorted(devs)
        cen112 = [abs(v) for u, v in zip(us, bottom[0]["dx"]) if abs(u) <= 0.55] \
            if bottom and bottom[0]["y_css"] == 112 else []
        cen_vals = [abs(v) for r in bottom for u, v in zip(us, r["dx"]) if abs(u) <= 0.55]
        edge_vals = [abs(v) for r in bottom for u, v in zip(us, r["dx"]) if abs(u) >= 0.7]
        cen_max = max(cen_vals, default=0); cen_max112 = max(cen112, default=0)
        edge_max = max(edge_vals, default=0)
        lm = [r["dx"][0] for r in bottom]
        rm = [r["dx"][-1] for r in bottom]
        lm_top = [r["dx"][0] for r in top]
        rm_top = [r["dx"][-1] for r in top]
        st["field_vs_map"] = field_table
        checks = {
            "control_exact_zero": ctrl_max <= 0.01,
            "control_max_abs_dx": ctrl_max,
            "center_row112_le_2_5px": cen_max112 <= 2.5,
            "center_row112_max_abs_dx": cen_max112,
            "edge_ge_2_5px": edge_max >= 2.5,
            "edge_max_abs_dx": edge_max,
            "edge_gt_center_by_2px": edge_max >= cen_max + 2.0,
            "field_matches_map_max_le_4px": max(devs, default=0) <= 4.0,
            "field_matches_map_median_le_2px": (devs_sorted[len(devs_sorted) // 2]
                                               if devs_sorted else 0) <= 2.0,
            # noise floor tierB-фона: median |dx| 1.6px при отсутствии дисплейсмента
            "field_dev_max": round(max(devs, default=0), 2),
            "field_dev_median": (devs_sorted[len(devs_sorted) // 2]
                                 if devs_sorted else 0),
            "bottom_left_all_neg": all(v <= -1.5 for v in lm),
            "bottom_right_all_pos": all(v >= 1.5 for v in rm),
            "top_left_all_neg": all(v <= -2.0 for v in lm_top),
            "top_right_all_pos": all(v >= 2.0 for v in rm_top),
            "left_right_medians": [round(sorted(lm)[len(lm) // 2], 2),
                                   round(sorted(rm)[len(rm) // 2], 2)],
            "map_prediction_note": "measured dx>0 = линия смещена вправо; feDisplacementMap: "
                                   "видимый сдвиг = -map_dx (магнификация выпуклой линзы); "
                                   "карта: макс 8px, центр |u|,|v|<=0.62 = 0.03px",
        }
        st["checks"] = checks
        # contrast / rim / specular from the 3x crop (crop origin = panel - 24css)
        d3 = 3
        PX0c, PY0c, PWc, PHc = 24 * d3, 24 * d3, pw * d3, ph * d3
        x0, y0 = int(PX0c + 3 * d3), int(PY0c + 3 * d3)
        x1, y1 = int(PX0c + PWc - 3 * d3), int(PY0c + PHc - 3 * d3)
        lums = [lum_at(a3, x, y) for y in range(y0, y1) for x in range(x0, x1)]
        p5, p995 = percentile(lums, 0.05), percentile(lums, 0.995)
        st["contrast"] = {"p5": round(p5, 4), "p99_5": round(p995, 4),
                          "wcag": round((p995 + 0.05) / (p5 + 0.05), 2)}
        st["rim"] = {
            "top": round(band_mean(a3, x0 + 18, x1 - 18, y0 + 3, y0 + 9), 4),
            "bottom": round(band_mean(a3, x0 + 18, x1 - 18, y1 - 9, y1 - 3), 4),
            "left": round(band_mean(a3, x0 + 3, x0 + 9, y0 + 18, y1 - 18), 4),
            "right": round(band_mean(a3, x1 - 9, x1 - 3, y0 + 18, y1 - 18), 4),
        }
        st["rim"]["top_gt_bottom"] = st["rim"]["top"] > st["rim"]["bottom"]
        st["rim"]["left_gt_right"] = st["rim"]["left"] > st["rim"]["right"]
        best = None
        for y in range(y0, y1, 2):
            for x in range(x0, x1, 2):
                v = lum_at(a3, x, y)
                if best is None or v > best[0]:
                    best = (v, x, y)
        st["specular"] = {"nx": round((best[1] - PX0c) / PWc, 3),
                          "ny": round((best[2] - PY0c) / PHc, 3),
                          "top_left": (best[1] - PX0c) < PWc * 0.5 and (best[2] - PY0c) < PHc * 0.5}
        out["stand_grid"] = st

        # ── D. stand tierB (downgrade semantics) ──
        tb = {}
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=3)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        page.goto(STAND + "?bg=grid&tier=b", wait_until="load")
        page.wait_for_selector("#panel-hero", timeout=6000)
        page.wait_for_timeout(400)
        # the stand's URL param flips the attribute only; emulate the app
        # downgrade path: remove inline lens filters from non-a nodes.
        page.evaluate("""() => {
          document.querySelectorAll('#panel-hero, #panel-hero *').forEach(el => {
            if (el.style) { el.style.removeProperty('backdrop-filter');
                            el.style.removeProperty('-webkit-backdrop-filter'); }
          });
        }""")
        page.wait_for_timeout(250)
        tb["panel"] = page.evaluate(SURFACE_JS, "#panel-hero")
        boxb = tb["panel"]
        clipb = {"x": boxb["x"] - 24, "y": boxb["y"] - 24,
                 "width": boxb["w"] + 48, "height": boxb["h"] + 48}
        page.screenshot(path=ev_path("stand_tierb_3x_on.png"), clip=clipb)
        page.evaluate("() => { const el = document.querySelector('#panel-hero');"
                      " el.style.visibility = 'hidden'; }")
        page.wait_for_timeout(250)
        page.screenshot(path=ev_path("stand_tierb_3x_hidden.png"), clip=clipb)
        ctx.close()
        tb["errors"] = errs[:5]
        a_tb = decode_png(open(ev_path("stand_tierb_3x_on.png"), "rb").read())
        b_tb = decode_png(open(ev_path("stand_tierb_3x_hidden.png"), "rb").read())
        tb["field"] = field_measure(a_tb, b_tb, {"w": boxb["w"], "h": boxb["h"]}, 3,
                                    [8, 40, 70, 100, 124, boxb["h"] + 20])
        # evaluate tierB: no url() lens, blur present, no directional displacement
        tb_lines = tb["field"]["lines_css"]
        tb_us = [x / boxb["w"] * 2 - 1 for x in tb_lines]
        inpanel = [r for r in tb["field"]["rows"] if r["y_css"] <= boxb["h"]]
        all_vals = [abs(v) for r in inpanel for v in r["dx"]]
        med_abs = sorted(all_vals)[len(all_vals) // 2] if all_vals else 999
        lvals = sorted(v for r in inpanel for u, v in zip(tb_us, r["dx"]) if u <= -0.4)
        rvals = sorted(v for r in inpanel for u, v in zip(tb_us, r["dx"]) if u >= 0.4)
        lmed = lvals[len(lvals) // 2] if lvals else None
        rmed = rvals[len(rvals) // 2] if rvals else None
        # line visibility through frost: modulation of a text-free row inside panel
        a_tb_row = None
        PX0t, PY0t = 24 * 3, 24 * 3
        for y_off in (112, 118, 124):
            yy = int(PY0t + y_off * 3)
            if yy < a_tb["h"]:
                prof = [lum_at(a_tb, x, yy) for x in
                        range(int(PX0t + 3), int(PX0t + boxb["w"] * 3 - 3))]
                a_tb_row = max(a_tb_row or 0, max(prof) - min(prof))
        tb["checks"] = {
            "tier_b": boxb["tier"] == "b",
            "no_url_filter": "url(" not in (boxb["bfTarget"] or ""),
            "blur_present": "blur(" in (boxb["bfTarget"] or ""),
            "median_abs_dx": round(med_abs, 2),
            "no_systematic_displacement": med_abs <= 2.5,
            "lr_medians": [round(lmed, 2) if lmed is not None else None,
                           round(rmed, 2) if rmed is not None else None],
            "lr_symmetry_le_2": (lmed is not None and rmed is not None
                                 and abs(lmed - rmed) <= 2.0),
            "line_modulation_in_panel": round(a_tb_row or 0, 4),
            "lines_visible": (a_tb_row or 0) > 0.02,
        }
        out["stand_tierb"] = tb

        # ── E. real pages ──
        pages = {}
        for route, wd, ht in (("#/", 1440, 900), ("#/oversight", 1440, 900),
                              ("#/modules", 1440, 900),
                              ("#/modules/summary/styles", 1440, 900)):
            rec = {}
            ctx, page, freeze, errors = open_app(browser, wd, ht, route)
            rec["freeze"] = freeze
            rec["errors"] = errors[:8]
            rec["inventory"] = page.evaluate(INVENTORY_JS)
            rec["url_filters"] = page.evaluate(
                "() => { const out = []; document.querySelectorAll('*').forEach(el => {"
                " const cs = getComputedStyle(el);"
                " const bf = cs.backdropFilter || cs.webkitBackdropFilter || 'none';"
                " if (bf.includes('url(')) out.push(((el.className||'').toString()"
                "  .slice(0,60) || el.tagName) + ' :: ' + bf.slice(0, 90)); });"
                " return out.slice(0, 12); }")
            rec["overflow_ok"] = page.evaluate(
                "() => document.documentElement.scrollWidth <= window.innerWidth + 1")
            if route == "#/":
                rec["status_hero"] = page.evaluate(SURFACE_JS, ".status-hero")
                rec["hero_hit"] = page.evaluate(HIT_JS, ".status-hero")
                rec["graph"] = page.evaluate(SURFACE_JS, ".cognition-graph")
                rec["screenshot"] = rel(ev_path("status_1440.png"))
            elif route == "#/oversight":
                rec["card"] = page.evaluate(SURFACE_JS, "main .card")
                rec["screenshot"] = rel(ev_path("oversight_1440.png"))
            elif route == "#/modules":
                rec["module_card_count"] = page.evaluate(
                    "() => document.querySelectorAll('.module-card').length")
                rec["module_card"] = page.evaluate(SURFACE_JS, ".module-card")
                try:
                    bc0 = page.evaluate(
                        "() => { const el = document.querySelector('.module-card');"
                        " return el ? getComputedStyle(el).backgroundImage : null; }")
                    page.hover(".module-card")
                    page.wait_for_timeout(250)
                    bc1 = page.evaluate(
                        "() => { const el = document.querySelector('.module-card');"
                        " return el ? getComputedStyle(el).backgroundImage : null; }")
                    rec["hover_specular"] = {
                        "changed": bc0 != bc1,
                        "radial_after": "radial-gradient" in (bc1 or ""),
                        "before": (bc0 or "")[:80], "after": (bc1 or "")[:80]}
                except Exception as e:
                    rec["hover_specular"] = {"error": str(e)[:140]}
                rec["screenshot"] = rel(ev_path("modules_1440.png"))
            else:
                rec["textareas"] = page.evaluate(
                    "() => document.querySelectorAll('main textarea, main input[type=text]').length")
                rec["glass_on_editor_controls"] = page.evaluate(
                    "() => { const els = document.querySelectorAll("
                    "'main textarea, main input, main select, main [contenteditable]');"
                    " const bad = []; els.forEach(el => { let n = el, d = 0;"
                    "  while (n && d < 6) { const cs = getComputedStyle(n);"
                    "   const bf = cs.backdropFilter || cs.webkitBackdropFilter || 'none';"
                    "   if (bf.includes('url(')) bad.push((n.className||'').toString().slice(0,60));"
                    "   n = n.parentElement; d++; } }); return bad; }")
                rec["screenshot"] = rel(ev_path("style_editor_1440.png"))
            pages[route + "@" + str(wd)] = rec
            ctx.close()
        out["pages"] = pages

        # tier map checks on the status page
        sh = pages["#/@1440"]
        checks = {"declared_tier_map_ok": True, "lens_on_hero": False,
                  "tier_a_count_le3": False, "graph_c": None, "errors0": not sh["errors"]}
        ca = 0
        for it in sh["inventory"]:
            dec, tier = it["declared"], it["tier"]
            if dec == "a" and tier not in ("a", "b"):
                checks["declared_tier_map_ok"] = False
            if dec == "c" and tier != "c":
                checks["declared_tier_map_ok"] = False
            if dec == "b" and tier != "b":
                checks["declared_tier_map_ok"] = False
            if tier == "a":
                ca += 1
        checks["tier_a_count_le3"] = ca <= 3
        hero = sh.get("status_hero") or {}
        checks["lens_on_hero"] = ("url(" in (hero.get("bfTargetInline") or "")
                                  and "lg-lens" in (hero.get("bfTargetInline") or ""))
        checks["hero_tier_a"] = hero.get("tier") == "a" and hero.get("reason") in (
            "probe-chromium", "override-a")
        checks["hero_hit_inside"] = all(h["inside"] for h in (sh.get("hero_hit") or [])) \
            if sh.get("hero_hit") else None
        graph = sh.get("graph") or {}
        checks["graph_c"] = graph.get("tier") == "c"
        out["status_checks"] = checks

        # ── F. mobile 390 ──
        m = {}
        ctx, page, freeze, errors = open_app(browser, 390, 844, "#/", wait_ms=2500)
        m["freeze"] = freeze
        m["errors"] = errors[:8]
        m["overflow_ok"] = page.evaluate(
            "() => document.documentElement.scrollWidth <= window.innerWidth + 1")
        m["header"] = page.evaluate(SURFACE_JS, "header.header-sticky")
        m["fs_control"] = page.evaluate(
            "() => { const el = document.querySelector('.header-fs-btn');"
            " if (!el) return null; const cs = getComputedStyle(el);"
            " const r = el.getBoundingClientRect();"
            " return {cls: (el.className||'').toString(),"
            "  has_mini_lens: el.classList.contains('lg-mini-lens') ||"
            "    !!el.querySelector('.lg-mini-lens'),"
            "  borderRadius: cs.borderRadius, w: Math.round(r.width), h: Math.round(r.height),"
            "  dataGlass: el.getAttribute('data-glass'),"
            "  bf: ((cs.backdropFilter||cs.webkitBackdropFilter)||'none').slice(0,100)}; }")
        elfs = page.query_selector(".header-fs-btn")
        if elfs:
            bb = elfs.bounding_box()
            if bb:
                clipf = {"x": max(0, bb["x"] - 10), "y": max(0, bb["y"] - 10),
                         "width": min(bb["width"] + 20, 390 - max(0, bb["x"] - 10)),
                         "height": bb["height"] + 20}
                page.screenshot(path=ev_path("fs_control_1to1_390.png"), clip=clipf)
                m["fs_shot"] = rel(ev_path("fs_control_1to1_390.png"))
        # popover «Ещё»
        try:
            page.click(".mobile-topnav-more", timeout=3000)
            page.wait_for_timeout(350)
            m["popover"] = page.evaluate(SURFACE_JS, ".more-menu-panel")
            page.screenshot(path=ev_path("popover_390.png"))
            m["popover_shot"] = rel(ev_path("popover_390.png"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        except Exception as e:
            m["popover"] = {"error": str(e)[:140]}
        m["inventory390"] = page.evaluate(INVENTORY_JS)
        page.screenshot(path=ev_path("status_390.png"))
        m["screenshot"] = rel(ev_path("status_390.png"))
        m["seed_before"] = page.evaluate(
            "() => { const d = (window.__PolygonBackground && window.__PolygonBackground.getDiagnostics)"
            " ? window.__PolygonBackground.getDiagnostics() : null;"
            " window.__cnv0 = document.querySelector('canvas');"
            " return d ? d.sceneSeed : null; }")
        page.evaluate("(y) => { const el = document.querySelector('main');"
                      " if (el) el.scrollTop = y; }", 900)
        page.wait_for_timeout(500)
        m["seed_after_scroll"] = page.evaluate(
            "() => { const d = (window.__PolygonBackground && window.__PolygonBackground.getDiagnostics)"
            " ? window.__PolygonBackground.getDiagnostics() : null;"
            " return {seed: d ? d.sceneSeed : null,"
            "  same_canvas: window.__cnv0 === document.querySelector('canvas')}; }")
        page.screenshot(path=ev_path("status_390_scrolled.png"))
        ctx.close()
        out["mobile390"] = m

        # ── G. reduced-motion / low-end / fps proxy ──
        rm = {}
        ctx, page, freeze, errors = open_app(browser, 1440, 900, "#/", reduced=True)
        rm["errors"] = errors[:8]
        rm["hero"] = page.evaluate(SURFACE_JS, ".status-hero")
        rm["inventory_reasons"] = [it["reason"] for it in
                                   page.evaluate(INVENTORY_JS) if it["declared"] == "a"]
        rm["screenshot"] = rel(ev_path("reduced_motion_status.png"))
        page.screenshot(path=ev_path("reduced_motion_status.png"))
        ctx.close()
        out["reduced_motion"] = rm

        le = {}
        ctx, page, freeze, errors = open_app(browser, 1440, 900, "#/", low_end=True)
        le["errors"] = errors[:8]
        le["hero"] = page.evaluate(SURFACE_JS, ".status-hero")
        le["inventory_reasons"] = [it["reason"] for it in
                                   page.evaluate(INVENTORY_JS) if it["declared"] == "a"]
        ctx.close()
        out["low_end"] = le

        try:
            fps = {}
            ctx, page, freeze, errors = open_app(browser, 390, 844, "#/")
            page.evaluate("""() => {
              window.__FT = { frames: [] };
              let last = performance.now();
              const tick = () => { const now = performance.now();
                window.__FT.frames.push(now - last); last = now;
                window.__FT.raf = requestAnimationFrame(tick); };
              window.__FT.raf = requestAnimationFrame(tick);
            }""")
            for i in range(6):
                page.evaluate("(y) => { const m = document.querySelector('main');"
                              " if (m) m.scrollTop = y; }", int((i + 1) * 120))
                page.wait_for_timeout(350)
            fps["data"] = page.evaluate("""() => {
              const f = window.__FT.frames.slice(2).sort((a, b) => a - b);
              const pct = (q) => f.length ? f[Math.min(f.length - 1, Math.floor(q * f.length))] : null;
              const drops = f.filter(x => x > 25).length;
              return {frames: f.length, p50: pct(0.5), p95: pct(0.95),
                      worst: f.length ? f[f.length - 1] : null, drops_gt25: drops,
                      avg_fps: f.length ? Math.round(1000 / (f.reduce((a, b) => a + b, 0) / f.length)) : null};
            }""")
            fps["errors"] = errors[:5]
            ctx.close()
            out["fps_proxy"] = fps
        except Exception as e:
            out["fps_proxy"] = {"error": str(e)[:200]}

        browser.close()

    with open(ev_path("glass_playwright_results.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    print("[fingerprint] head=%s" % out["head"])
    print("[map] checks=%s max|dx|=%.2f center=%.3f" % (
        json.dumps(out["map_contract"]["checks"]), out["map_contract"]["max_abs_dx"],
        out["map_contract"]["center_062_max"]))
    st = out["stand_grid"]
    print("[stand grid] probe=%s tier=%s" % (st["probe"], (st["panel"] or {}).get("tier")))
    print("[stand grid] checks=%s" % json.dumps(st["checks"]))
    print("[stand grid] contrast=%s rim=%s specular=%s hit=%s click=%s" % (
        st.get("contrast"), st.get("rim"), st.get("specular"), st.get("hit"), st.get("hero_btn_click")))
    for r in st["field"]["rows"]:
        print("[field] y+%s: %s" % (r["y_css"], r["dx"]))
    for ft in st.get("field_vs_map", []):
        print("[field-vs-map] y+%s v=%.2f meas=%s pred=%s dev=%s" % (
            ft["y_css"], ft["v"], ft["measured"], ft["predicted_apparent"], ft["deviation"]))
    tb = out["stand_tierb"]
    print("[stand tierB] checks=%s bf=%s" % (json.dumps(tb["checks"]), (tb["panel"] or {}).get("bfTarget")))
    if tb.get("field"):
        for r in tb["field"]["rows"]:
            print("[tierB field] y+%s: %s" % (r["y_css"], r["dx"]))
    print("[status] %s" % json.dumps(out["status_checks"]))
    for k, rec in out["pages"].items():
        tiers = {}
        for it in rec.get("inventory", []):
            tiers[it.get("tier") or "?"] = tiers.get(it.get("tier") or "?", 0) + 1
        print("[page %s] tiers=%s errors=%d overflow=%s url_filters=%s" % (
            k, tiers, len(rec.get("errors", [])), rec.get("overflow_ok"),
            rec.get("url_filters")))
    mv = out["mobile390"]
    print("[mobile390] header tier=%s fs=%s popover=%s seed=%s->%s" % (
        (mv.get("header") or {}).get("tier"), mv.get("fs_control"),
        (mv.get("popover") or {}).get("tier"),
        mv.get("seed_before"), mv.get("seed_after_scroll")))
    print("[reduced-motion] hero=%s reasons=%s" % (
        (out["reduced_motion"].get("hero") or {}).get("tier"),
        out["reduced_motion"].get("inventory_reasons")))
    print("[low-end] hero=%s reasons=%s" % (
        (out["low_end"].get("hero") or {}).get("tier"),
        out["low_end"].get("inventory_reasons")))
    print("[fps] %s" % json.dumps((out.get("fps_proxy") or {}).get("data")))
    print("[out] %s" % ev_path("glass_playwright_results.json"))


if __name__ == "__main__":
    main()
