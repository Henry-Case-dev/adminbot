# -*- coding: utf-8 -*-
import os, sys, json, importlib.util
REPO = r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\EPIC-PROMPT-VERSIONING-UX-01-pv-ux"
RUN = r"C:\Users\main\.config\opencode\WorkspaceData\runs\pv-s4\rr2"
spec = importlib.util.spec_from_file_location("pv_e2e", os.path.join(REPO, "tests", "ui_prompt_version_card_e2e.py"))
E = importlib.util.module_from_spec(spec); sys.modules["pv_e2e"] = E
spec.loader.exec_module(E)

MEAS = """
() => {
  const r = document.querySelector('[data-prompt-history-result]');
  const body = document.querySelector('[data-pv-panel] .pv-panel__body')
            || document.querySelector('[data-pv-panel]');
  const rb = body ? body.getBoundingClientRect() : null;
  const q = r ? r.getBoundingClientRect() : null;
  return {
    has: !!r,
    text: r ? (r.innerText||'').replace(/\\s+/g,' ').trim().slice(0,80) : '',
    rect: q ? [Math.round(q.top), Math.round(q.bottom), Math.round(q.left), Math.round(q.right)] : null,
    bodyRect: rb ? [Math.round(rb.top), Math.round(rb.bottom)] : null,
    vh: window.innerHeight, vw: window.innerWidth,
    scrollTop: body ? body.scrollTop : null,
    scrollH: body ? body.scrollHeight : null,
    inView: !!(q && q.bottom > 0 && q.top < window.innerHeight && q.right > 0 && q.left < window.innerWidth),
    innerScrollVisible: !!(q && rb && q.top < rb.bottom && q.bottom > rb.top),
  };
}
"""

def run(browser, width, height, label, style):
    E.STATE["posts"] = []; E.STATE["gets"] = []
    E.STATE["active"] = "rev-manual-2"; E.STATE["entries"] = E.build_entries()
    E.STATE["core_text"] = {"full": "FULL-CORE-v1", "compact": "COMPACT-CORE-v1"}
    ctx, page = E.new_page(browser, width, height)
    out = {}
    try:
        if style == "speech":
            page.goto(E.BASE + "/#/ai/speech", wait_until="load")
            page.wait_for_selector(".speech-screen", state="visible"); page.wait_for_timeout(700)
            page.click("[data-speech-area='rules']")
            page.wait_for_selector("[data-speech-rules-link='core']", state="visible")
            page.click("[data-speech-rules-link='core']")
            page.wait_for_selector("[data-speech-core-versions] [data-prompt-history-toggle]",
                                   state="visible"); page.wait_for_timeout(700)
            page.click("[data-speech-core-versions] [data-prompt-history-toggle]")
        else:
            E.open_prompt_editor(page)
            page.click("[data-prompt-editor] [data-prompt-history-toggle]")
        page.wait_for_selector("[data-pv-panel]", state="visible"); page.wait_for_timeout(600)
        E.click_row(page, 1, "[data-pv-row-activate]")
        page.wait_for_timeout(2200)
        out["after_activate"] = page.evaluate(MEAS)
        page.evaluate("() => {const b=document.querySelector('[data-pv-panel] .pv-panel__body')"
                      "||document.querySelector('[data-pv-panel]'); if(b) b.scrollTop=b.scrollHeight;}")
        page.wait_for_timeout(500)
        out["after_scroll_to_end"] = page.evaluate(MEAS)
        page.screenshot(path=os.path.join(RUN, "shots", "rr2_vis_%s_%s.png" % (style, label)),
                        full_page=False)
    except Exception as e:
        out["error"] = str(e)[:300]
    finally:
        ctx.close()
    return out

httpd = E.serve_static(0, os.path.join(REPO, "web"))
E.BASE = "http://127.0.0.1:%d" % httpd.server_address[1]
from playwright.sync_api import sync_playwright
res = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    for w, h, lb in [(1536, 900, "1536"), (390, 844, "390")]:
        res["speech_%s" % lb] = run(b, w, h, lb, "speech")
        res["library_%s" % lb] = run(b, w, h, lb, "library")
    b.close()
json.dump(res, open(os.path.join(RUN, "visibility.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
for k, v in res.items():
    a = v.get("after_activate", {})
    print(k, "inView=", a.get("inView"), "innerScrollVisible=", a.get("innerScrollVisible"),
          "rect=", a.get("rect"), "body=", a.get("bodyRect"), "scrollTop=", a.get("scrollTop"),
          "err=", v.get("error"))