# -*- coding: utf-8 -*-
"""Re-review 3: свой замер видимости подтверждения (PVR-S4 B4)."""
import os, sys, json, importlib.util
REPO = r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\EPIC-PROMPT-VERSIONING-UX-01-pv-ux"
RUN = r"C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489\prompt-versioning-ux-6e485692ce03\temp-711868b769"
SHOTS = os.path.join(RUN, "rr3"); os.makedirs(SHOTS, exist_ok=True)
spec = importlib.util.spec_from_file_location("pv_e2e", os.path.join(REPO, "tests", "ui_prompt_version_card_e2e.py"))
E = importlib.util.module_from_spec(spec); sys.modules["pv_e2e"] = E
spec.loader.exec_module(E)
MEAS = r"""
() => {
  const el = document.querySelector('[data-prompt-history-result]');
  const body = document.querySelector('[data-pv-panel] .pv-panel__body');
  const R = (n) => n ? n.getBoundingClientRect() : null;
  const r = R(el), b = R(body), fr = R(document.querySelector('[data-pv-row]'));
  const rd = (o) => o ? {top: Math.round(o.top), bottom: Math.round(o.bottom), left: Math.round(o.left), right: Math.round(o.right), h: Math.round(o.height)} : null;
  let hit = null;
  if (r) { const h = document.elementFromPoint((r.left+r.right)/2, (r.top+r.bottom)/2); hit = !!(h && (h === el || el.contains(h))); }
  return {has: !!el, text: el ? (el.innerText||'').replace(/\s+/g,' ').trim().slice(0,70) : '',
    rect: rd(r), body: rd(b), firstRow: rd(fr),
    scrollTop: body ? body.scrollTop : null, scrollHeight: body ? body.scrollHeight : null,
    vh: window.innerHeight, vw: window.innerWidth, scrollY: window.scrollY,
    hitsCenter: hit,
    fullyInsideBody: !!(r && b && r.top >= b.top - 0.5 && r.bottom <= b.bottom + 0.5),
    insideWindow: !!(r && r.top >= -0.5 && r.bottom <= window.innerHeight + 0.5)};
}
"""

def shot(page, name):
    page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=False)

def open_panel(page, style):
    if style == "speech":
        page.goto(E.BASE + "/#/ai/speech", wait_until="load")
        page.wait_for_selector(".speech-screen", state="visible"); page.wait_for_timeout(700)
        page.click("[data-speech-area='rules']")
        page.wait_for_selector("[data-speech-rules-link='core']", state="visible")
        page.click("[data-speech-rules-link='core']")
        page.wait_for_selector("[data-speech-core-versions] [data-prompt-history-toggle]", state="visible")
        page.wait_for_timeout(700)
        page.click("[data-speech-core-versions] [data-prompt-history-toggle]")
    else:
        E.open_prompt_editor(page)
        page.click("[data-prompt-editor] [data-prompt-history-toggle]")
    page.wait_for_selector("[data-pv-panel]", state="visible"); page.wait_for_timeout(700)

def act(page, sel, idx=1):
    page.evaluate("([i, s]) => { const r = document.querySelectorAll('[data-pv-row]')[i];"
                  " const b = r && r.querySelector(s); if (b) b.click(); }", [idx, sel])
    page.wait_for_timeout(2400)

def scroll_body(page, to_end):
    page.evaluate("(end) => { const b = document.querySelector('[data-pv-panel] .pv-panel__body');"
                  " if (!b) return; b.scrollTop = end ? b.scrollHeight : 0; }", to_end)
    page.wait_for_timeout(400)

def run(browser, width, height, label, style):
    E.STATE["posts"] = []; E.STATE["gets"] = []
    E.STATE["active"] = "rev-manual-2"; E.STATE["entries"] = E.build_entries()
    E.STATE["baseline"] = None
    E.STATE["core_text"] = {"full": "FULL-CORE-v1 text", "compact": "COMPACT-CORE-v1 text"}
    ctx, page = E.new_page(browser, width, height)
    out = {"label": label, "style": style, "w": width, "h": height}
    try:
        open_panel(page, style)
        out["before"] = page.evaluate(MEAS)
        act(page, "[data-pv-row-activate]")
        out["apply"] = page.evaluate(MEAS)
        shot(page, "rr3_%s_apply_%s" % (style, label))
        scroll_body(page, True)
        out["scroll_end"] = page.evaluate(MEAS)
        shot(page, "rr3_%s_scrollend_%s" % (style, label))
        scroll_body(page, False)
        out["scroll_back"] = page.evaluate(MEAS)
        act(page, "[data-pv-row-baseline]")
        out["baseline"] = page.evaluate(MEAS)
        shot(page, "rr3_%s_baseline_%s" % (style, label))
        page.wait_for_timeout(2600)
        out["after_wait"] = page.evaluate(MEAS)
        page.evaluate("() => { const b = document.querySelector('[data-pv-result-dismiss]'); if (b) b.click(); }")
        page.wait_for_timeout(400)
        out["dismissed"] = page.evaluate(MEAS)
        shot(page, "rr3_%s_dismissed_%s" % (style, label))
    except Exception as e:
        out["error"] = str(e)[:400]
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
        for style in ("library", "speech"):
            res["%s_%s" % (style, lb)] = run(b, w, h, lb, style)
    b.close()
json.dump(res, open(os.path.join(RUN, "rr3-geometry.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
bad = 0
for k in sorted(res):
    v = res[k]
    if v.get("error"):
        print(k, "ERROR", v["error"]); bad += 1
    for ph in ("before", "apply", "scroll_end", "scroll_back", "baseline", "after_wait", "dismissed"):
        d = v.get(ph) or {}
        r = d.get("rect") or {}; bd = d.get("body") or {}
        print("%-14s %-11s has=%-5s inBody=%-5s inWin=%-5s hit=%-5s st=%-5s rect=%s..%s body=%s..%s %r" % (
            k, ph, d.get("has"), d.get("fullyInsideBody"), d.get("insideWindow"),
            d.get("hitsCenter"), d.get("scrollTop"), r.get("top"), r.get("bottom"),
            bd.get("top"), bd.get("bottom"), (d.get("text") or "")[:46]))
    print("-")
print("errors:", bad)
