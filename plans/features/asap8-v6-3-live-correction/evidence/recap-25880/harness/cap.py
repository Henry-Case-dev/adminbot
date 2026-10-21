"""RECAP-25880 capture — whole-viewport UI evidence bound to deployed 31c16555.

Serves the DETACHED WORKTREE (deployed commit) web/ via the real suite harnesses
(ui_round1025_matrix._Handler + real /api/* stubs of the six suites +
ui_asap8_w2_fullscreen_e2e.mock_sdk_js). Writes PNGs + probe JSON into the MAIN
repo evidence dir plans/features/asap8-v6-3-live-correction/evidence/recap-25880/.
Read-only wrt app code.
"""
import hashlib
import json
import os
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer

WT = r"C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\recap-31c16555"
OUT = r"C:\Code\Python\adminbot\plans\features\asap8-v6-3-live-correction\evidence\recap-25880"
PREFIX = "_31c16555_"
PORT = 8871
BASE = "http://127.0.0.1:%d/web/index.html" % PORT

for p in (WT, os.path.join(WT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)
sys.stdout.reconfigure(encoding="utf-8")

import ui_round1025_matrix as M            # noqa: E402
import ui_asap8_w2_fullscreen_e2e as FS    # noqa: E402
import ui_asap8_w3_editor_e2e as E         # noqa: E402
import ui_asap8_v63_w3_status_e2e as St    # noqa: E402
import ui_asap8_w3_analytics_e2e as A      # noqa: E402
import ui_asap8_w3_modules_e2e as Mo       # noqa: E402
from services import chat_prompts as CP    # noqa: E402

VIEWPORTS = [(320, 700), (360, 780), (390, 844), (430, 932),
             (768, 1024), (1024, 768), (1440, 900), (667, 375)]
ROUTES = [
    ("status", "#/"),
    ("analytics_overview", "#/oversight"),
    ("analytics_processes", "#/oversight?view=processes"),
    ("modules", "#/modules"),
    ("editor_prompts", "#/ai/prompts/direct"),
]
SDK_JS = None
L1_KEY = "prompts.direct_l1_planner_system_prompt"


def _sd(v=0):
    return {"top": v, "bottom": 0, "left": 0, "right": 0}


def sd(top=0, bottom=0, left=0, right=0):
    return {"top": top, "bottom": bottom, "left": left, "right": right}


def _cfg(w, h, platform="android", safe=None, content=None, isfull=None):
    return {"platform": platform, "version": "8.0",
            "stableHeight": h - 56, "viewportHeight": h,
            "safeAreaInset": safe or sd(),
            "contentSafeAreaInset": content or sd(),
            "hasBoolean": isfull is not None,
            **({"isFullscreen": isfull} if isfull is not None else {})}


def config_stub():
    """Real catalog stub (R17: values blanked) + code canon for the deployed
    L1-planner key (services.chat_prompts.DIRECT_L1_PLANNER_SYSTEM_PROMPT,
    len matches prod `/api/config` probe value_len=2423)."""
    data = Mo._stub_config(False)
    seeded = 0
    for it in data["items"]:
        if it["key"] == L1_KEY:
            it["value"] = CP.DIRECT_L1_PLANNER_SYSTEM_PROMPT
            seeded += 1
    assert seeded == 1, seeded
    return data


CONFIG = None


def api(route):
    req = route.request
    url = req.url.split("?")[0]
    m = req.method
    if url.endswith("/api/cover/styles/st_w3"):
        body = E.meta_payload(E.STATE.scenario)
    elif url.endswith("/api/cover/styles") and m == "GET":
        body = E.STYLES_LIST
    elif url.endswith("/api/cover/connections"):
        body = {"connections": []}
    elif url.endswith("/api/cover/preview-compile"):
        body = E.compile_payload(E.STATE.scenario, E.STATE.final_text())
    elif url.endswith("/api/memory/expired-overview"):
        body = St.EXPIRED_OVERVIEW
    elif url.endswith("/api/memory/intel-funnels"):
        body = St.INTEL_FUNNELS
    elif url.endswith("/api/oversight/experience/funnel"):
        body = St._funnel(1)
    elif url.endswith("/api/memory/cognition/status"):
        body = St.COGNITION
    elif url.endswith("/api/memory/deep-sleep"):
        body = St.DEEP_SLEEP
    elif url.endswith("/api/memory/health"):
        body = St.HEALTH
    elif url.endswith("/api/status/logs"):
        body = St.LOGS_PAYLOAD
    elif url.endswith("/api/status"):
        body = St.STATUS_W3
    elif url.endswith("/api/analytics/viz/activity"):
        body = A.VIZ_ACTIVITY
    elif url.endswith("/api/analytics/viz/process-activity"):
        body = A.PROCESS_ACTIVITY
    elif url.endswith("/api/analytics/pipeline/runs/latest"):
        body = A.PIPELINE_LATEST
    elif url.endswith("/api/factcheck/temporal/runs"):
        body = A.TEMPORAL_RUNS
    elif url.endswith("/api/config/overrides-map"):
        body = A.OVERRIDES_MAP
    elif url.endswith("/api/oversight/summary"):
        body = A.OVERSIGHT_SUMMARY
    elif url.endswith("/api/oversight/runs"):
        body = A.OVERSIGHT_RUNS
    elif url.endswith("/api/oversight/processes"):
        body = A.PROCESSES
    elif url.endswith("/api/memory/stats"):
        body = A.COGNITION["stats"]
    elif url.endswith("/api/stories/summary"):
        body = A.STORIES_SUMMARY
    elif url.endswith("/api/stories/feed"):
        body = A.STORIES_FEED
    elif url.endswith("/api/stories"):
        body = A.STORIES_TABLE
    elif url.endswith("/api/access/chats"):
        body = [{"chat_id": -1001234567890, "title": "PERMsoc и очень длинное имя чата",
                 "is_dm": False, "photo_file_id": None, "access": "admin"}]
    elif url.endswith("/api/access/me"):
        body = {"is_local_admin": False, "permissions": {}}
    elif url.endswith("/api/me"):
        body = M.ME_JSON
    elif url.endswith("/api/config") and m == "GET":
        body = CONFIG
    elif url.endswith("/api/config"):
        body = {"ok": True}
    else:
        body = M._stub_for(req.url)
    route.fulfill(status=200, content_type="application/json; charset=utf-8",
                  body=json.dumps(body, ensure_ascii=False).encode("utf-8"))


def sdk(route):
    route.fulfill(status=200, content_type="application/javascript", body=SDK_JS)


PROBE = """
(() => {
  const de = document.documentElement;
  const h = document.querySelector('header.header-sticky');
  const fs = document.querySelector('.header-fs-btn');
  const nav = document.querySelector('.mobile-topnav');
  const side = document.querySelector('.app-sidebar');
  const cs = e => e ? getComputedStyle(e) : null;
  const r = e => { const b = e && e.getBoundingClientRect();
    return b ? {x:Math.round(b.x),y:Math.round(b.y),w:Math.round(b.width),
                h:Math.round(b.height),right:Math.round(b.right),
                bottom:Math.round(b.bottom)} : null; };
  return {
    vw: window.innerWidth, vh: window.innerHeight,
    scrollWidth: de.scrollWidth, hOverflow: de.scrollWidth > window.innerWidth + 1,
    hash: location.hash,
    header: r(h), headerH: h ? Math.round(h.getBoundingClientRect().height*10)/10 : null,
    headerPad: h ? {
      top: cs(h).paddingTop, right: cs(h).paddingRight,
      left: cs(h).paddingLeft, bottom: cs(h).paddingBottom } : null,
    nav: r(nav),
    sidebar: r(side), sidebarVisible: !!(side && cs(side).display !== 'none'
                                         && side.getBoundingClientRect().width > 0),
    fsBtn: r(fs), fsVisible: fs ? (cs(fs).display !== 'none'
                                   && cs(fs).visibility !== 'hidden') : false,
    shellClass: document.querySelector('.app-shell')
      ? document.querySelector('.app-shell').className : null,
    promptKeys: Array.from(document.querySelectorAll('[data-prompt-key]'))
      .map(e => e.getAttribute('data-prompt-key')),
    l1PromptPresent: !!document.querySelector(
      '[data-prompt-key="prompts.direct_l1_planner_system_prompt"]'),
    l1PromptText: (() => { const el = document.querySelector(
      '[data-prompt-key="prompts.direct_l1_planner_system_prompt"]');
      return el ? el.textContent.replace(/\\s+/g,' ').trim() : null; })(),
    promptTextarea: (() => { const t = document.querySelector('[data-prompt-textarea]');
      return t ? {key: t.getAttribute('data-prompt-textarea'),
                  len: (t.value || '').length} : null; })(),
    directStages: document.querySelectorAll('[data-direct-stages] [data-stage]').length,
    l1SummaryCard: !!document.querySelector('[data-direct-l1-planner]'),
    coverEditorOpen: !!document.querySelector('[data-cover-style-editor]'),
  };
})()
"""

MORE_JS = """
(() => { const b = document.querySelector('.mobile-topnav-more');
  if (!b) return false; b.click(); return true; })()
"""


def main():
    global SDK_JS, CONFIG
    os.makedirs(OUT, exist_ok=True)
    CONFIG = config_stub()
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    res = {"generated": "2026-10-16", "lane": "RECAP-25880", "port": PORT,
           "worktree": WT, "prefix": PREFIX,
           "stub_notes": ("config stub = deployed catalog, values blanked (R17); "
                          "ONLY prompts.direct_l1_planner_system_prompt seeded with "
                          "services.chat_prompts.DIRECT_L1_PLANNER_SYSTEM_PROMPT "
                          "(len 2423 = prod probe value_len)"),
           "shots": [], "states": {}, "console_errors": [],
           "served_css": {}, "inset_cases": {}}

    def record(pg, surface, tag, name, extra=None):
        m = pg.evaluate(PROBE)
        if extra:
            m.update(extra)
        res["states"]["%s/%s" % (surface, tag)] = m
        fn = PREFIX + name + ".png"
        pg.screenshot(path=os.path.join(OUT, fn), full_page=False)
        res["shots"].append(fn)

    def new_ctx(browser, w, h, platform="android", safe=None, content=None,
                isfull=None):
        global SDK_JS
        SDK_JS = FS.mock_sdk_js(_cfg(w, h, platform, safe, content, isfull))
        mobile = w < 768
        ctx = browser.new_context(viewport={"width": w, "height": h},
                                  is_mobile=mobile, has_touch=mobile)
        ctx.route("**/api/**", api)
        ctx.route("**/static/vendor/telegram-web-app.js", sdk)
        pg = ctx.new_page()
        pg.set_default_timeout(12000)
        return ctx, pg

    def attach_errs(pg, key):
        def _on(msg):
            if msg.type == "error":
                res["console_errors"].append({"state": key, "err": msg.text[:200]})
        pg.on("console", _on)

    with_errors = attach_errs

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ── main matrix: 8 viewports × surfaces ──────────────────────────────
        for (w, h) in VIEWPORTS:
            tag = "%dx%d" % (w, h)
            ctx, pg = new_ctx(browser, w, h)
            with_errors(pg, "matrix/" + tag)
            for name, route_ in ROUTES:
                pg.goto(BASE + route_, wait_until="load")
                pg.wait_for_selector("header.header-sticky", state="visible")
                pg.wait_for_timeout(950)
                if name == "editor_prompts":
                    try:
                        pg.wait_for_selector("[data-prompt-key]", timeout=4000)
                    except Exception:
                        pass
                record(pg, name, tag, "%s_%s" % (name, tag))
            # cover editor (real U06 flow: open style editor)
            try:
                E.open_editor(pg, BASE)
                record(pg, "cover_editor", tag, "cover_editor_%s" % tag)
            except Exception as exc:  # noqa: BLE001
                res["console_errors"].append(
                    {"state": "cover_editor/%s" % tag, "err": "open failed: %s" % exc})
            ctx.close()
            print("matrix done:", tag, flush=True)

        # ── L1 prompt focus + direct models + more menu ──────────────────────
        for (w, h) in [(390, 844), (1440, 900)]:
            tag = "%dx%d" % (w, h)
            ctx, pg = new_ctx(browser, w, h)
            with_errors(pg, "focus/" + tag)
            pg.goto(BASE + "#/ai/prompts/direct/" + L1_KEY, wait_until="load")
            pg.wait_for_selector("[data-prompt-textarea]", state="visible")
            pg.wait_for_timeout(700)
            record(pg, "editor_prompts_l1_focus", tag, "editor_prompts_l1_focus_%s" % tag)
            pg.goto(BASE + "#/modules/direct/models", wait_until="load")
            pg.wait_for_selector("[data-direct-l1-planner]", state="visible")
            pg.wait_for_timeout(600)
            record(pg, "direct_models", tag, "direct_models_%s" % tag)
            ctx.close()
            print("focus done:", tag, flush=True)

        ctx, pg = new_ctx(browser, 390, 844)
        with_errors(pg, "more/390x844")
        pg.goto(BASE + "#/", wait_until="load")
        pg.wait_for_selector("header.header-sticky", state="visible")
        pg.wait_for_timeout(700)
        pg.evaluate(MORE_JS)
        pg.wait_for_selector(".more-menu-panel", state="visible")
        pg.wait_for_timeout(400)
        record(pg, "shell_more_open", "390x844", "shell_more_open_390x844")
        ctx.close()
        print("more menu done", flush=True)

        # ── fullscreen states (android) + tdesktop policy ────────────────────
        for (w, h, tag) in [(390, 844, "390x844"), (1024, 768, "1024x768")]:
            ctx, pg = new_ctx(browser, w, h, "android", sd(20, 0, 0, 44),
                              sd(), isfull=True)
            with_errors(pg, "fullscreen/" + tag)
            pg.goto(BASE + "#/", wait_until="load")
            pg.wait_for_selector("header.header-sticky", state="visible")
            pg.evaluate("window.__tma.__emit('fullscreenChanged')")
            pg.wait_for_timeout(900)
            record(pg, "fullscreen_on", tag, "fullscreen_on_%s" % tag)
            ctx.close()
            print("fullscreen done:", tag, flush=True)
        ctx, pg = new_ctx(browser, 1440, 900, "tdesktop", sd(), sd(), isfull=False)
        with_errors(pg, "tdesktop/1440x900")
        pg.goto(BASE + "#/", wait_until="load")
        pg.wait_for_selector("header.header-sticky", state="visible")
        pg.wait_for_timeout(900)
        record(pg, "tdesktop_policy", "1440x900", "tdesktop_policy_1440x900")
        ctx.close()
        print("tdesktop done", flush=True)

        # ── U07.2 safe-area inset geometry (deployed CSS fix) ────────────────
        INSET_CASES = [
            ("rowa_390_zero", (390, 844), "android", sd(0, 0, 0, 0), sd(), None,
             {"pad_right": 16.0, "pad_left": 16.0, "safe_right": 390}),
            ("rowa_667_right44", (667, 375), "android", sd(20, 0, 0, 44), sd(), None,
             {"pad_right": 60.0, "pad_left": 16.0, "safe_right": 623}),
            ("rowa_320_lr24", (320, 700), "android", sd(20, 0, 24, 24), sd(), None,
             {"pad_right": 40.0, "pad_left": 40.0, "safe_right": 296}),
        ]
        for (name, (w, h), plat, sa, ca, isf, want) in INSET_CASES:
            ctx, pg = new_ctx(browser, w, h, plat, sa, ca, isf)
            with_errors(pg, "inset/" + name)
            pg.goto(BASE + "#/", wait_until="load")
            pg.wait_for_selector("header.header-sticky", state="visible")
            pg.wait_for_timeout(900)
            tag = "%dx%d" % (w, h)
            record(pg, name, tag, "%s_%s" % (name, tag))
            st = res["states"]["%s/%s" % (name, tag)]
            got = {"pad_right": float(str(st["headerPad"]["right"]).replace("px", "")),
                   "pad_left": float(str(st["headerPad"]["left"]).replace("px", "")),
                   "safe_right": st["vw"] - sa["right"]}
            st["inset_expected"] = want
            st["inset_ok"] = all(abs(got[k] - want[k]) < 0.51 for k in want)
            st["inset_got"] = got
            ctx.close()
            print("inset done:", name, got, flush=True)

        browser.close()

    # ── served CSS check (over the same local server, BEFORE shutdown) ──────
    css_url = "http://127.0.0.1:%d/static/app.css" % PORT
    css = urllib.request.urlopen(css_url, timeout=15).read()
    httpd.shutdown()
    formula_r = ("max(env(safe-area-inset-right, 0px), "
                 "var(--tg-content-safe-area-inset-right, 0px), "
                 "var(--tg-safe-area-inset-right, 0px))")
    formula_l = formula_r.replace("right", "left")
    formula_t = formula_r.replace("right", "top")
    res["served_css"] = {
        "url": css_url, "bytes": len(css),
        "sha256": hashlib.sha256(css).hexdigest(),
        "right_formula_count": css.decode("utf-8").count(formula_r),
        "left_formula_count": css.decode("utf-8").count(formula_l),
        "top_formula_count": css.decode("utf-8").count(formula_t),
        "file_sha256_match": hashlib.sha256(
            open(os.path.join(WT, "web", "static", "app.css"), "rb").read()
        ).hexdigest() == hashlib.sha256(css).hexdigest(),
    }
    with open(os.path.join(OUT, "capture_states.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    n_of = sum(1 for v in res["states"].values() if v.get("hOverflow"))
    print("shots=%d states=%d hOverflow_states=%d console_err=%d"
          % (len(res["shots"]), len(res["states"]), n_of, len(res["console_errors"])))
    print("served_css:", json.dumps(res["served_css"], ensure_ascii=False))
    print("out:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
