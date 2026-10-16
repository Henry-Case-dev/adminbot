"""ROW-A / U07.2 horizontal safe-area — Playwright-репрод и ре-измерение.

Дефект (lane V63-FE-2, `_v63fe2_rowa_safearea.json`, случай
`667_safearea_cutout`): интерактивный бокс `.header-fs-btn` игнорирует
ГОРИЗОНТАЛЬНЫЕ safe-area инсеты — при правом inset 44 hit-box уходит на 28 px
в native-правую зону (✕/⋮ Telegram в landscape).

Харнесс = паттерн `tools/ui_asap8_w2_fullscreen_e2e.py` (локальный
ThreadingHTTPServer + РЕАЛЬНЫЕ web/index.html, web/app.js,
web/static/app.css, web/static/fullscreen-policy.js, mock SDK через route).
Ничего нового в стеке не появляется.

Считаем «content-safe область» = viewport минус МАКСИМУМ по каждой стороне
из (`safeAreaInset`, `contentSafeAreaInset`) — так же, как это делает
CSS-формула `max(env(...), --tg-content-safe-area-inset-*, --tg-safe-area-inset-*)`.

Запуск: .venv/Scripts/python.exe <evidence>/ui_rowa_safearea_e2e.py (cwd = repo)
Артефакты: <evidence>/_v63fe2_rowa_safearea.json + _v63fe2_rowa_<tag>.png
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

_HERE = os.path.abspath(__file__)
for _i in range(6):        # file → v63-rowa-safearea → evidence → feature → features → plans → repo
    _HERE = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "tools"))
import ui_round1025_matrix as M  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = M.REPO
EVIDENCE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(EVIDENCE, "_v63fe2_rowa_safearea.json")
PORT = 8871
BASE_URL = "http://127.0.0.1:%d" % PORT

ME = json.loads(json.dumps(M.ME_JSON))
ME["ui_flags"]["TOKEN_FLOW_NODEFLOW_ENABLED"] = False   # чужой known render-error
ME["ui_flags"]["UI_POLYGON_BG_ENABLED"] = False         # детерминированный фон


def mock_sdk_js(cfg):
    """Мок официального SDK (образец w2-fullscreen §4.2): РОВНО те факты,
    что задаёт сценарий; horizontal insets управляемы."""
    return """
(function () {
  var cfg = %s;
  var handlers = {};
  var calls = [];
  var webapp = {
    platform: cfg.platform,
    version: cfg.version || '8.0',
    initData: 'user=%%7B%%22id%%22%%3A5885953495%%7D&hash=audit',
    initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
    themeParams: {}, colorScheme: 'dark',
    viewportStableHeight: cfg.stableHeight,
    viewportHeight: cfg.viewportHeight,
    safeAreaInset: cfg.safeAreaInset,
    contentSafeAreaInset: cfg.contentSafeAreaInset,
    ready() {}, expand() {},
    setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
    isExpanded: true,
    requestFullscreen() { calls.push('requestFullscreen'); },
    requestFullScreen() { calls.push('requestFullScreen'); },
    exitFullscreen() { calls.push('exitFullscreen'); },
    onEvent(ev, fn) { (handlers[ev] = handlers[ev] || []).push(fn); },
    offEvent(ev, fn) {
      var a = handlers[ev] || []; var i = a.indexOf(fn);
      if (i >= 0) a.splice(i, 1);
    },
    __emit(ev, payload) {
      (handlers[ev] || []).slice().forEach(function (f) { f(payload); });
    },
    __calls: calls,
  };
  if (cfg.hasBoolean) webapp.isFullscreen = !!cfg.isFullscreen;
  window.Telegram = { WebApp: webapp };
  window.__tma = webapp;
  try {
    sessionStorage.setItem('adminbot.initData',
      'user=%%7B%%22id%%22%%3A5885953495%%7D&hash=audit');
  } catch (e) {}
})();
""" % json.dumps(cfg)


def _api_handler_factory():
    def handler(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(ME))
            return
        payload = M._stub_for(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload))
    return handler


PROBE_JS = """
(() => {
  const btn = document.querySelector('.header-fs-btn');
  const de = document.documentElement;
  const header = document.querySelector('header.header-sticky');
  const hr = header ? header.getBoundingClientRect() : null;
  const cs = header ? getComputedStyle(header) : null;
  const before = btn ? getComputedStyle(btn, '::before') : null;
  const pol = window.__FullscreenPolicy ? window.__FullscreenPolicy.state() : null;
  const st = window.__FullscreenPolicy ? null : null;
  const vw = window.innerWidth, vh = window.innerHeight;
  const r = btn ? btn.getBoundingClientRect() : null;
  const vw_px = before ? parseFloat(before.width) : null;
  const vh_px = before ? parseFloat(before.height) : null;
  return {
    vw: vw, vh: vh,
    scrollWidth: de.scrollWidth,
    hOverflow: de.scrollWidth > vw + 1,
    fsSlotFloatClass: de.classList.contains('fs-slot-float'),
    hiddenClass: de.classList.contains('fs-hidden'),
    fsReason: de.getAttribute('data-fs-reason'),
    policySlot: pol ? pol.slot : null,
    policyInsets: pol ? pol.viewport : null,
    btnPresent: !!btn,
    posFixed: btn ? getComputedStyle(btn).position === 'fixed' : null,
    rect: r ? { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width),
                h: Math.round(r.height), right: Math.round(r.right),
                bottom: Math.round(r.bottom) } : null,
    margin: btn ? (() => { const m = getComputedStyle(btn);
              return { top: m.marginTop, right: m.marginRight,
                       bottom: m.marginBottom, left: m.marginLeft }; })() : null,
    visualCss: before ? { w: vw_px, h: vh_px,
                          radius: before.borderRadius,
                          pe: before.pointerEvents } : null,
    visualRect: (r && vw_px && vh_px) ? {
      x: Math.round(r.x + (r.width - vw_px) / 2),
      y: Math.round(r.y + (r.height - vh_px) / 2),
      right: Math.round(r.x + (r.width + vw_px) / 2),
      bottom: Math.round(r.y + (r.height + vh_px) / 2) } : null,
    headerRect: hr ? { x: Math.round(hr.x), y: Math.round(hr.y),
                       w: Math.round(hr.width), h: Math.round(hr.height),
                       right: Math.round(hr.right) } : null,
    headerPad: cs ? { top: cs.paddingTop, right: cs.paddingRight,
                      left: cs.paddingLeft, bottom: cs.paddingBottom } : null,
    headerCompact: !!header && header.classList.contains('header-compact-v2'),
    ariaLabel: btn ? (btn.getAttribute('aria-label') || '') : '',
    ariaPressed: btn ? btn.getAttribute('aria-pressed') : null,
    title: btn ? (btn.getAttribute('title') || '') : '',
    interceptTopRight: (() => {
      const el = document.elementFromPoint(vw - 10, 18);
      return el ? (el.className || '').toString() + '#' + el.tagName : null;
    })(),
    interceptTopLeft: (() => {
      const el = document.elementFromPoint(24, 18);
      return el ? (el.className || '').toString() + '#' + el.tagName : null;
    })(),
    tgVars: (() => {
      const cs2 = getComputedStyle(de);
      return {
        safeR: cs2.getPropertyValue('--tg-safe-area-inset-right').trim(),
        safeL: cs2.getPropertyValue('--tg-safe-area-inset-left').trim(),
        csaR: cs2.getPropertyValue('--tg-content-safe-area-inset-right').trim(),
        csaL: cs2.getPropertyValue('--tg-content-safe-area-inset-left').trim(),
        csaT: cs2.getPropertyValue('--tg-content-safe-area-inset-top').trim(),
        safeT: cs2.getPropertyValue('--tg-safe-area-inset-top').trim()
      };
    })(),
    consoleErrors: []
  };
})()
"""


def new_page(browser, cfg, sdk_js, viewport):
    ctx = browser.new_context(viewport=viewport, device_scale_factor=2,
                              locale="ru-RU")
    page = ctx.new_page()
    page.route("**/static/vendor/telegram-web-app.js",
               lambda route: route.fulfill(
                   status=200, content_type="application/javascript",
                   body=sdk_js))
    page.route("**/api/**", _api_handler_factory())
    page.set_viewport_size(viewport)
    page.goto(BASE_URL + "/#/", wait_until="domcontentloaded", timeout=30000)
    return ctx, page


def wait_ready(page, want_btn=True, timeout=20000):
    if want_btn:
        page.wait_for_selector(".header-fs-btn", state="attached",
                               timeout=timeout)
    else:
        page.wait_for_selector("header.header-sticky", state="visible",
                               timeout=timeout)
        page.wait_for_timeout(600)
    page.wait_for_timeout(400)


def inset_max(sa, csa):
    """Максимум по каждой стороне — как в CSS-формуле max(env, --tg-csa, --tg-sa)."""
    return {k: max(sa.get(k, 0), csa.get(k, 0)) for k in ("top", "bottom",
                                                          "left", "right")}


CASES = [
    # tag, viewport, safeAreaInset, contentSafeAreaInset
    ("390_zero_inset", {"width": 390, "height": 844},
     {"top": 0, "bottom": 0, "left": 0, "right": 0},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}),
    ("390_safearea_56", {"width": 390, "height": 844},
     {"top": 0, "bottom": 0, "left": 0, "right": 0},
     {"top": 56, "bottom": 0, "left": 0, "right": 0}),
    ("390_ios_notch", {"width": 390, "height": 844},
     {"top": 47, "bottom": 34, "left": 0, "right": 0},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}),
    ("667_safearea_cutout", {"width": 667, "height": 375},
     {"top": 20, "bottom": 0, "left": 0, "right": 44},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}),
    ("667_float_right44", {"width": 667, "height": 375},
     {"top": 20, "bottom": 0, "left": 0, "right": 44},
     {"top": 36, "bottom": 0, "left": 0, "right": 0}),
    ("320_lr_insets", {"width": 320, "height": 700},
     {"top": 20, "bottom": 0, "left": 24, "right": 24},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}),
]


def run(browser):
    rows = []
    for tag, vp, sa, csa in CASES:
        cfg = dict(platform="android", hasBoolean=True, isFullscreen=False,
                   stableHeight=max(300, vp["height"] - 56),
                   viewportHeight=vp["height"],
                   safeAreaInset=sa, contentSafeAreaInset=csa)
        ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), vp)
        wait_ready(page)
        p = page.evaluate(PROBE_JS)
        safe = inset_max(sa, csa)
        vw, vh = vp["width"], vp["height"]
        row = {
            "tag": tag, "viewport": vp,
            "safeAreaInset": sa, "contentSafeAreaInset": csa,
            "safeEdge": {"left": safe["left"], "right": vw - safe["right"],
                         "top": safe["top"], "bottom": vh - safe["bottom"]},
            "btn": p["rect"], "visual": p["visualRect"], "visualCss": p["visualCss"],
            "slot": p["policySlot"], "fsSlotFloatClass": p["fsSlotFloatClass"],
            "hiddenClass": p["hiddenClass"], "fsReason": p["fsReason"],
            "posFixed": p["posFixed"], "margin": p["margin"],
            "headerPad": p["headerPad"], "headerCompact": p["headerCompact"],
            "hOverflow": p["hOverflow"], "scrollWidth": p["scrollWidth"],
            "tgVars": p["tgVars"],
            "ariaLabel": p["ariaLabel"], "ariaPressed": p["ariaPressed"],
            "title": p["title"],
            "interceptTopRight": p["interceptTopRight"],
            "interceptTopLeft": p["interceptTopLeft"],
        }
        # ── контракт: control_box ⊆ content_safe_area в ОБОИХ осях ──
        r = p["rect"]
        row["insideSafeArea"] = {
            "left": bool(r and r["x"] >= safe["left"]),
            "right": bool(r and r["right"] <= vw - safe["right"]),
            "top": bool(r and r["y"] >= safe["top"]),
            "bottom": bool(r and r["bottom"] <= vh - safe["bottom"]),
        }
        row["pxInsideNativeRight"] = max(0, (r["right"] - (vw - safe["right"])) if r else 0)
        row["pxInsideNativeLeft"] = max(0, (safe["left"] - r["x"]) if r else 0)
        row["pxInsideNativeTop"] = max(0, (safe["top"] - r["y"]) if r else 0)
        row["pxInsideNativeBottom"] = max(0, (r["bottom"] - (vh - safe["bottom"])) if r else 0)
        row["hitMin44"] = bool(r and r["w"] >= 44 and r["h"] >= 44)
        row["visual28_34"] = bool(p["visualCss"] and 28 <= p["visualCss"]["w"] <= 34)
        row["ok"] = (all(row["insideSafeArea"].values()) and row["hitMin44"]
                     and not r is None and not p["hOverflow"])
        page.screenshot(path=os.path.join(EVIDENCE, "_v63fe2_rowa_%s.png" % tag))
        rows.append(row)
        ctx.close()
    return rows


def main():
    from playwright.sync_api import sync_playwright
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print("[rowa-sa] server on %d" % PORT)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            rows = run(browser)
        finally:
            browser.close()
    httpd.shutdown()
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump({"generated": "2026-10-16", "cases": rows}, fh,
                  ensure_ascii=False, indent=2)
    bad = [r["tag"] for r in rows if not r["ok"]]
    for r in rows:
        b = r["btn"] or {}
        print("[rowa-sa] %-22s slot=%-6s btn=%s..%s (y %s..%s) safeR=%s safeL=%s "
              "inside=%s nativeRightPx=%s"
              % (r["tag"], r["slot"], b.get("x"), b.get("right"), b.get("y"),
                 b.get("bottom"), r["safeEdge"]["right"], r["safeEdge"]["left"],
                 r["insideSafeArea"], r["pxInsideNativeRight"]))
    print("[rowa-sa] FAIL: %s" % (bad or "none"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
