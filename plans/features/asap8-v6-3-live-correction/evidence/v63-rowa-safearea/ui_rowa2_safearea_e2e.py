"""ROW-A / U07.2 horizontal safe-area — репрод + ре-измерение (lane RESUME-ROWA).

Дефект (V63-FE-2, `_v63fe2_rowa_safearea.json`, случай `667_safearea_cutout`,
воспроизводится и этим харнессом в фазе `before`): интерактивный бокс
`.header-fs-btn` игнорирует ГОРИЗОНТАЛЬНЫЕ safe-area инсеты — при правом
inset 44 hit-box уходит в native-правую зону (safe-край 667−44=623), где
Telegram в landscape держит ✕/⋮. Причина: базовое правило
`header.header-sticky` брало `1rem + env(safe-area-inset-*)`, а в Telegram
Android `env(...)` = 0; значения SDK лежат в `--tg-safe-area-inset-*` /
`--tg-content-safe-area-inset-*` (пишет telegram-init.js). Формулу
`max(env, --tg-csa, --tg-sa)` имели только `.fullscreen-mode header`
(round 10.10), `.toast-wrap` и float-⛶.

Фазы:
  after  — как есть в рабочем дереве (кандидат);
  before — та же страница, но `/static/app.css` подменяется на версию из
           `git show HEAD:web/static/app.css` (route) → чистый RED без
           правки файлов в дереве.

Харнесс = паттерн `tools/ui_asap8_w2_fullscreen_e2e.py` (локальный
ThreadingHTTPServer + РЕАЛЬНЫЕ web/index.html, web/app.js, web/static/app.css,
web/static/fullscreen-policy.js; mock SDK через route). Ничего нового в стеке.

Контракт (U07.2/U07.2b/U07.2c/U07.2e, REQ-U07-2): control_box ⊆
content_safe_area в ОБОИХ осях, hit ≥44×44, визуал 28–34, нет h-overflow,
никаких кликабельных web-элементов в native-полосе на высоте кнопки.
content_safe_area = viewport минус максимум по каждой стороне из
(`safeAreaInset`, `contentSafeAreaInset`) — ровно то, что делает CSS-формула
`max(env(...), --tg-content-safe-area-inset-*, --tg-safe-area-inset-*)`.

Запуск (cwd = repo):
  .venv/Scripts/python.exe <evidence>/ui_rowa2_safearea_e2e.py [before|after]
Артефакты: <evidence>/_rowa2_safearea_<phase>.json + _rowa2_<tag>_<phase>.png
"""
import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
for _i in range(8):        # …/v63-rowa-safearea → evidence → feature → features → plans → repo
    if os.path.isfile(os.path.join(_HERE, "tools", "ui_round1025_matrix.py")):
        break
    _HERE = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "tools"))
import ui_round1025_matrix as M  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = M.REPO
EVIDENCE = os.path.dirname(os.path.abspath(__file__))
PHASE = (sys.argv[1] if len(sys.argv) > 1 else "after").strip().lower()
RAW = os.path.join(EVIDENCE, "_rowa2_safearea_%s.json" % PHASE)
PORT = 8872
BASE_URL = "http://127.0.0.1:%d" % PORT


def _git_show_head_app_css():
    """Версия app.css из HEAD — «до фикса» без правок рабочего дерева."""
    try:
        out = subprocess.run(["git", "show", "HEAD:web/static/app.css"],
                             cwd=REPO, capture_output=True, text=True,
                             encoding="utf-8")
        return out.stdout if out.returncode == 0 and out.stdout else None
    except Exception:  # noqa: BLE001
        return None


HEAD_APP_CSS = _git_show_head_app_css()
if PHASE == "before" and not HEAD_APP_CSS:
    print("[rowa2] НЕ УДАЛОСЬ получить HEAD:web/static/app.css — before невозможен")
    sys.exit(2)


def _me(flags):
    me = json.loads(json.dumps(M.ME_JSON))
    me["ui_flags"]["TOKEN_FLOW_NODEFLOW_ENABLED"] = False   # чужой known render-error
    me["ui_flags"]["UI_POLYGON_BG_ENABLED"] = False         # детерминированный фон
    me["ui_flags"].update(flags or {})
    return me


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
      (handlers[ev] || []).forEach(function (f) { f(payload); });
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


def _api_handler_factory(me):
    def handler(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(me))
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
  const bcs = btn ? getComputedStyle(btn) : null;
  const before = btn ? getComputedStyle(btn, '::before') : null;
  const pol = window.__FullscreenPolicy ? window.__FullscreenPolicy.state() : null;
  const vw = window.innerWidth, vh = window.innerHeight;
  const r = btn ? btn.getBoundingClientRect() : null;
  const vw_px = before ? parseFloat(before.width) : null;
  const vh_px = before ? parseFloat(before.height) : null;
  const items = [];
  if (header) {
    for (const el of header.children) {
      const er = el.getBoundingClientRect();
      const es = getComputedStyle(el);
      items.push({
        cls: (el.className || '').toString().slice(0, 60),
        x: Math.round(er.x), right: Math.round(er.right),
        y: Math.round(er.y), bottom: Math.round(er.bottom),
        order: es.order, paddingRight: es.paddingRight, display: es.display,
      });
    }
  }
  // SVG-элементы: className — SVGAnimatedString; берём класс через closest().
  const desc = (el) => {
    if (!el) return null;
    const host = el.closest ? el.closest('.header-fs-btn') : null;
    if (host) return 'header-fs-btn';
    const c = (el.className !== undefined && typeof el.className === 'string')
      ? el.className : '';
    return (c || el.tagName).toString();
  };
  const cx = r ? Math.round(r.x + r.width / 2) : 0;
  const cy = r ? Math.round(r.y + r.height / 2) : 0;
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
    rectExact: r ? { x: r.x, y: r.y, w: r.width, h: r.height,
                     right: r.right, bottom: r.bottom } : null,
    margin: bcs ? { top: bcs.marginTop, right: bcs.marginRight,
                    bottom: bcs.marginBottom, left: bcs.marginLeft } : null,
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
    headerChildren: items,
    ariaLabel: btn ? (btn.getAttribute('aria-label') || '') : '',
    ariaPressed: btn ? btn.getAttribute('aria-pressed') : null,
    title: btn ? (btn.getAttribute('title') || '') : '',
    interceptBtnCenter: btn ? desc(document.elementFromPoint(cx, cy)) : null,
    interceptNativeRight: desc(document.elementFromPoint(vw - 4, cy)),
    interceptNativeLeft: desc(document.elementFromPoint(4, cy)),
    interceptTopRight: desc(document.elementFromPoint(vw - 10, 18)),
    interceptTopLeft: desc(document.elementFromPoint(24, 18)),
    tgVars: (() => {
      const cs2 = getComputedStyle(de);
      const g = (n) => cs2.getPropertyValue(n).trim();
      return {
        safeR: g('--tg-safe-area-inset-right'), safeL: g('--tg-safe-area-inset-left'),
        csaR: g('--tg-content-safe-area-inset-right'),
        csaL: g('--tg-content-safe-area-inset-left'),
        csaT: g('--tg-content-safe-area-inset-top'),
        safeT: g('--tg-safe-area-inset-top'),
      };
    })(),
  };
})()
"""

CSS_OVERRIDE = PHASE == "before"


def new_page(browser, me, cfg, sdk_js, viewport):
    ctx = browser.new_context(viewport=viewport, device_scale_factor=2,
                              locale="ru-RU")
    page = ctx.new_page()
    page.route("**/static/vendor/telegram-web-app.js",
               lambda route: route.fulfill(
                   status=200, content_type="application/javascript",
                   body=sdk_js))
    if CSS_OVERRIDE:
        page.route(lambda url: "/static/app.css" in url,
                   lambda route: route.fulfill(
                       status=200, content_type="text/css",
                       body=HEAD_APP_CSS))
    page.route("**/api/**", _api_handler_factory(me))
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


# tag, viewport, safeAreaInset, contentSafeAreaInset, ожидаемый слот, gate?
CASES = [
    # ── U07.2: обязательные 320/390/667 с right=44 (гейт) ──
    ("320x700_right44", {"width": 320, "height": 700},
     {"top": 0, "bottom": 0, "left": 0, "right": 44},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}, "inline", True),
    ("390x844_right44", {"width": 390, "height": 844},
     {"top": 0, "bottom": 0, "left": 0, "right": 44},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}, "inline", True),
    # точный повтор дефектного кейса V63-FE-2 667_safearea_cutout
    ("667x375_right44", {"width": 667, "height": 375},
     {"top": 20, "bottom": 0, "left": 0, "right": 44},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}, "inline", True),
    # ── регрессии (гейт) ──
    ("390_zero_inset", {"width": 390, "height": 844},
     {"top": 0, "bottom": 0, "left": 0, "right": 0},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}, "inline", True),
    ("320_lr_insets", {"width": 320, "height": 700},
     {"top": 20, "bottom": 0, "left": 24, "right": 24},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}, "inline", True),
    ("667x375_float_right44", {"width": 667, "height": 375},
     {"top": 20, "bottom": 0, "left": 0, "right": 44},
     {"top": 36, "bottom": 0, "left": 0, "right": 0}, "float", True),
    ("390_csa56_float", {"width": 390, "height": 844},
     {"top": 0, "bottom": 0, "left": 0, "right": 0},
     {"top": 56, "bottom": 0, "left": 0, "right": 0}, "float", True),
    ("390_csa56_float_right44", {"width": 390, "height": 844},
     {"top": 0, "bottom": 0, "left": 0, "right": 44},
     {"top": 56, "bottom": 0, "left": 0, "right": 0}, "float", True),
    # ── диагностика: legacy-шапка (UI_HEADER_COMPACT_V2=off), не гейт ──
    ("diag_667x375_right44_legacy", {"width": 667, "height": 375},
     {"top": 20, "bottom": 0, "left": 0, "right": 44},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}, "inline", False),
    ("diag_320x700_right44_legacy", {"width": 320, "height": 700},
     {"top": 0, "bottom": 0, "left": 0, "right": 44},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}, "inline", False),
    ("diag_390_csa35_inline", {"width": 390, "height": 844},
     {"top": 35, "bottom": 0, "left": 0, "right": 0},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}, "inline", False),
    ("diag_390_left44_potrait", {"width": 390, "height": 844},
     {"top": 20, "bottom": 0, "left": 44, "right": 0},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}, "inline", False),
    ("diag_320x700_lr44_extreme", {"width": 320, "height": 700},
     {"top": 20, "bottom": 0, "left": 44, "right": 44},
     {"top": 0, "bottom": 0, "left": 0, "right": 0}, "inline", False),
]


def run(browser):
    rows = []
    for tag, vp, sa, csa, exp_slot, gate in CASES:
        legacy = "legacy" in tag
        me = _me({"UI_HEADER_COMPACT_V2": False} if legacy else {})
        cfg = dict(platform="android", hasBoolean=True, isFullscreen=False,
                   stableHeight=max(300, vp["height"] - 56),
                   viewportHeight=vp["height"],
                   safeAreaInset=sa, contentSafeAreaInset=csa)
        ctx, page = new_page(browser, me, cfg, mock_sdk_js(cfg), vp)
        wait_ready(page)
        p = page.evaluate(PROBE_JS)
        safe = inset_max(sa, csa)
        vw, vh = vp["width"], vp["height"]
        r = p["rect"]
        rx = p["rectExact"]
        row = {
            "tag": tag, "gate": gate, "legacyHeader": legacy,
            "viewport": vp,
            "safeAreaInset": sa, "contentSafeAreaInset": csa,
            "expectedSlot": exp_slot,
            "safeEdge": {"left": safe["left"], "right": vw - safe["right"],
                         "top": safe["top"], "bottom": vh - safe["bottom"]},
            "btn": p["rect"], "visual": p["visualRect"], "visualCss": p["visualCss"],
            "slot": p["policySlot"], "fsSlotFloatClass": p["fsSlotFloatClass"],
            "hiddenClass": p["hiddenClass"], "fsReason": p["fsReason"],
            "posFixed": p["posFixed"], "margin": p["margin"],
            "headerRect": p["headerRect"], "headerPad": p["headerPad"],
            "headerCompact": p["headerCompact"],
            "headerChildren": p["headerChildren"],
            "hOverflow": p["hOverflow"], "scrollWidth": p["scrollWidth"],
            "tgVars": p["tgVars"],
            "ariaLabel": p["ariaLabel"], "ariaPressed": p["ariaPressed"],
            "title": p["title"],
            "interceptBtnCenter": p["interceptBtnCenter"],
            "interceptNativeRight": p["interceptNativeRight"],
            "interceptNativeLeft": p["interceptNativeLeft"],
            "interceptTopRight": p["interceptTopRight"],
            "interceptTopLeft": p["interceptTopLeft"],
            "policyInsets": p["policyInsets"],
        }
        # ── контракт: control_box ⊆ content_safe_area в ОБОИХ осях ──
        row["insideSafeArea"] = {
            "left": bool(rx and rx["x"] >= safe["left"]),
            "right": bool(rx and rx["right"] <= vw - safe["right"]),
            "top": bool(rx and rx["y"] >= safe["top"]),
            "bottom": bool(rx and rx["bottom"] <= vh - safe["bottom"]),
        }
        row["pxInsideNativeRight"] = round(max(0.0, (rx["right"] - (vw - safe["right"])) if rx else 0.0), 2)
        row["pxInsideNativeLeft"] = round(max(0.0, (safe["left"] - rx["x"]) if rx else 0.0), 2)
        row["pxInsideNativeTop"] = round(max(0.0, (safe["top"] - rx["y"]) if rx else 0.0), 2)
        row["pxInsideNativeBottom"] = round(max(0.0, (rx["bottom"] - (vh - safe["bottom"])) if rx else 0.0), 2)
        row["gapToSafeRight"] = round((vw - safe["right"] - rx["right"]), 2) if rx else None
        row["hitMin44"] = bool(rx and rx["w"] >= 44 and rx["h"] >= 44)
        row["visual28_34"] = bool(p["visualCss"] and 28 <= p["visualCss"]["w"] <= 34)
        row["noWebControlInNativeRight"] = "header-fs-btn" not in (
            p["interceptNativeRight"] or "")
        row["centerHitsButton"] = "header-fs-btn" in (p["interceptBtnCenter"] or "")
        row["topZoneFree"] = "header-fs-btn" not in (p["interceptTopRight"] or "")
        row["slotAsExpected"] = p["policySlot"] == exp_slot
        row["visualInSafeArea"] = bool(p["visualRect"] and
                                       safe["left"] <= p["visualRect"]["x"] and
                                       p["visualRect"]["right"] <= vw - safe["right"])
        row["checks"] = {
            "insideBothAxes": all(row["insideSafeArea"].values()),
            "hitMin44": row["hitMin44"], "visual28_34": row["visual28_34"],
            "noHOverflow": not p["hOverflow"],
            "noWebControlInNativeRight": row["noWebControlInNativeRight"],
            "centerHitsButton": row["centerHitsButton"],
            "slotAsExpected": row["slotAsExpected"],
            "topZoneFree": row["topZoneFree"],
            "visualInSafeArea": row["visualInSafeArea"],
        }
        row["ok"] = all(row["checks"].values())
        page.screenshot(path=os.path.join(EVIDENCE,
                                          "_rowa2_%s_%s.png" % (tag, PHASE)))
        rows.append(row)
        ctx.close()
    return rows


def main():
    from playwright.sync_api import sync_playwright
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print("[rowa2] server on %d, phase=%s (app.css override=%s)"
          % (PORT, PHASE, CSS_OVERRIDE))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            rows = run(browser)
        finally:
            browser.close()
    httpd.shutdown()
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump({"phase": PHASE, "generated": "2026-10-16",
                   "appCssOverride": CSS_OVERRIDE, "cases": rows}, fh,
                  ensure_ascii=False, indent=2)
    gate_fail = [r["tag"] for r in rows if r["gate"] and not r["ok"]]
    diag_fail = [r["tag"] for r in rows if not r["gate"] and not r["ok"]]
    for r in rows:
        b = r["btn"] or {}
        print("[rowa2] %-32s %s slot=%-6s(exp %-6s) btn=%s..%s (y %s..%s) "
              "safeR=%s safeT=%s gapR=%s pxNativeR=%s pxNativeT=%s inside=%s "
              "hOv=%s ok=%s"
              % (r["tag"], "GATE" if r["gate"] else "diag", r["slot"],
                 r["expectedSlot"], b.get("x"), b.get("right"), b.get("y"),
                 b.get("bottom"), r["safeEdge"]["right"], r["safeEdge"]["top"],
                 r["gapToSafeRight"], r["pxInsideNativeRight"],
                 r["pxInsideNativeTop"], r["insideSafeArea"], r["hOverflow"],
                 r["ok"]))
        if not r["ok"]:
            print("         checks=%s" % json.dumps(
                {k: v for k, v in r["checks"].items() if not v}))
    print("[rowa2] phase=%s GATE FAIL: %s | diag FAIL: %s"
          % (PHASE, gate_fail or "none", diag_fail or "none"))
    return 1 if gate_fail else 0


if __name__ == "__main__":
    sys.exit(main())
