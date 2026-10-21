"""RECAP-25880 diag: hOverflow on #/ai/prompts/direct at 1440x900 — who overflows?"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

WT = r"C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\recap-31c16555"
TOOLS = os.path.join(WT, "tools")
for p in (WT, TOOLS):
    if p not in sys.path:
        sys.path.insert(0, p)
sys.stdout.reconfigure(encoding="utf-8")

import ui_round1025_matrix as M            # noqa: E402
import ui_asap8_w2_fullscreen_e2e as FS    # noqa: E402
import probe_routes as PR                  # noqa: E402

PORT = 8879
BASE = "http://127.0.0.1:%d/web/index.html" % PORT

DIAG = """
(() => {
  const vw = window.innerWidth;
  const out = [];
  document.querySelectorAll('*').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.right > vw + 1) {
      out.push({tag: el.tagName, cls: (el.className || '').toString().slice(0, 80),
                right: Math.round(r.right), w: Math.round(r.width),
                sw: el.scrollWidth, cw: el.clientWidth});
    }
  });
  return {
    vw, scrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    mainScrollW: (() => { const m = document.querySelector('main'); return m ? [m.clientWidth, m.scrollWidth] : null; })(),
    offenders: out.slice(0, 12), count: out.length,
  };
})()
"""


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    PR.SDK_JS = FS.mock_sdk_js({
        "platform": "android", "version": "8.0", "stableHeight": 844,
        "viewportHeight": 900,
        "safeAreaInset": {"top": 0, "bottom": 0, "left": 0, "right": 0},
        "contentSafeAreaInset": {"top": 0, "bottom": 0, "left": 0, "right": 0},
        "hasBoolean": False})
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.route("**/api/**", PR.api)
        ctx.route("**/static/vendor/telegram-web-app.js", PR.sdk)
        pg = ctx.new_page()
        pg.set_default_timeout(9000)
        for route_ in ["#/ai/prompts/direct", "#/modules/direct/synthesizer",
                       "#/ai/prompts/direct/prompts.direct_l1_planner_system_prompt"]:
            pg.goto(BASE + route_, wait_until="load")
            pg.wait_for_selector("header.header-sticky", state="visible")
            pg.wait_for_timeout(1200)
            out[route_ + "/t1.2"] = pg.evaluate(DIAG)
            pg.wait_for_timeout(1500)
            out[route_ + "/t2.7"] = pg.evaluate(DIAG)
        ctx.close()
        # mobile for contrast
        ctx2 = browser.new_context(viewport={"width": 390, "height": 844},
                                   is_mobile=True, has_touch=True)
        ctx2.route("**/api/**", PR.api)
        ctx2.route("**/static/vendor/telegram-web-app.js", PR.sdk)
        pg2 = ctx2.new_page()
        pg2.set_default_timeout(9000)
        pg2.goto(BASE + "#/ai/prompts/direct", wait_until="load")
        pg2.wait_for_selector("header.header-sticky", state="visible")
        pg2.wait_for_timeout(1200)
        out["390/#/ai/prompts/direct"] = pg2.evaluate(DIAG)
        ctx2.close()
        browser.close()
    httpd.shutdown()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
