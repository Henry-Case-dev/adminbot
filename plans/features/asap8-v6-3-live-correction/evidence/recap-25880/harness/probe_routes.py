"""RECAP-25880 probe: which route renders the Direct prompt library (L1 Planner).

Read-only wrt app code; serves the DETACHED WORKTREE web/ (deployed commit
31c16555) via the real suite harness. Prints DOM facts.
"""
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
import ui_asap8_w3_editor_e2e as E         # noqa: E402
import ui_asap8_v63_w3_status_e2e as St    # noqa: E402
import ui_asap8_w3_analytics_e2e as A      # noqa: E402
import ui_asap8_w3_modules_e2e as Mo       # noqa: E402

PORT = 8878
BASE = "http://127.0.0.1:%d/web/index.html" % PORT


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
        body = Mo._stub_config(False)
    elif url.endswith("/api/config"):
        body = {"ok": True}
    else:
        body = M._stub_for(req.url)
    route.fulfill(status=200, content_type="application/json; charset=utf-8",
                  body=json.dumps(body, ensure_ascii=False).encode("utf-8"))


def sdk(route):
    route.fulfill(status=200, content_type="application/javascript", body=SDK_JS)


SDK_JS = None

PROBE = """
(() => {
  const keys = Array.from(document.querySelectorAll('[data-prompt-key]'))
      .map(e => e.getAttribute('data-prompt-key'));
  const ta = document.querySelector('[data-prompt-textarea]');
  const lib = document.querySelector('[data-workspace-prompts]');
  const ed = document.querySelector('[data-prompt-editor]');
  const L1 = 'prompts.direct_l1_planner_system_prompt';
  const l1El = document.querySelector('[data-prompt-key="' + L1 + '"]');
  return {
    hash: location.hash,
    libPresent: !!lib,
    libClass: lib ? lib.className : null,
    promptKeys: keys,
    l1Present: !!l1El,
    l1Text: l1El ? l1El.textContent.replace(/\\s+/g, ' ').trim() : null,
    editorPresent: !!ed,
    textareaKey: ta ? ta.getAttribute('data-prompt-textarea') : null,
    textareaLen: ta ? (ta.value || '').length : null,
    directStages: document.querySelectorAll('[data-direct-stages] [data-stage]').length,
    l1SummaryCard: !!document.querySelector('[data-direct-l1-planner]'),
    l1SummaryText: (() => {
      const c = document.querySelector('[data-direct-l1-planner]');
      return c ? c.textContent.replace(/\\s+/g, ' ').trim().slice(0, 260) : null;
    })(),
    hOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()
"""


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    global SDK_JS
    out = {}
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (w, h, mobile) in [(1440, 900, False), (390, 844, True)]:
            SDK_JS = FS.mock_sdk_js({
                "platform": "android", "version": "8.0", "stableHeight": h - 56,
                "viewportHeight": h,
                "safeAreaInset": {"top": 0, "bottom": 0, "left": 0, "right": 0},
                "contentSafeAreaInset": {"top": 0, "bottom": 0, "left": 0, "right": 0},
                "hasBoolean": False})
            ctx = browser.new_context(viewport={"width": w, "height": h},
                                      is_mobile=mobile, has_touch=mobile)
            ctx.route("**/api/**", api)
            ctx.route("**/static/vendor/telegram-web-app.js", sdk)
            pg = ctx.new_page()
            pg.set_default_timeout(9000)
            tag = "%dx%d" % (w, h)
            for name, route_ in [
                    ("lib", "#/ai/prompts/direct"),
                    ("focus", "#/ai/prompts/direct/prompts.direct_l1_planner_system_prompt"),
                    ("ws_synth", "#/modules/direct/synthesizer"),
                    ("ws_models", "#/modules/direct/models")]:
                pg.goto(BASE + route_, wait_until="load")
                pg.wait_for_selector("header.header-sticky", state="visible")
                pg.wait_for_timeout(1100)
                out["%s/%s" % (name, tag)] = pg.evaluate(PROBE)
            ctx.close()
        browser.close()
    httpd.shutdown()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
