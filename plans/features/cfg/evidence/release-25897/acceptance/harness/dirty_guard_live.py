# -*- coding: utf-8 -*-
"""Live dirty-guard check on the deployed MiniApp (prod URL, Playwright).

Steps: dirty the config -> try to leave the page (hash change) -> capture the
native confirm text, DISMISS -> must stay on the page with the value kept ->
try again, ACCEPT -> must navigate. Also records that the panel stays dirty
after a cancelled leave.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

URL = "https://admin-bot.duckdns.org/web/"
sys.path.insert(0, r"C:\Code\Python\adminbot\tools")
sys.path.insert(0, r"C:\Code\Python\adminbot")
import ui_round1025_matrix as M  # noqa: E402


def _api(route):
    req = route.request
    if req.method != "GET":
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"updated_at": 1, "updated": []}))
        return
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(M._stub_for(req.url), ensure_ascii=False))


DIRTY = """(key) => {
  const main = document.querySelector('main.scroll-area');
  let el = main && main.querySelector('[data-cfg-key="' + key + '"]');
  if (!el) return false;
  el.focus(); el.value = '4';
  el.dispatchEvent(new Event('input', {bubbles:true}));
  el.dispatchEvent(new Event('change', {bubbles:true}));
  return true;
}"""

STATE = """() => {
  const main = document.querySelector('main.scroll-area');
  const el = main && main.querySelector('[data-cfg-key="limits.dig_year_back_window_days"]');
  const panel = document.querySelector('.sticky-save');
  return JSON.stringify({hash: location.hash, value: el ? el.value : null,
    panel: !!panel, vh: innerHeight});
}"""


def main() -> int:
    out = {"url": URL, "now_utc": time.strftime("%Y-%m-%d %H:%M:%S",
                                                time.gmtime()),
           "dialogs": [], "steps": []}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  device_scale_factor=3, is_mobile=True,
                                  has_touch=True)
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _api)
        page = ctx.new_page()
        current = {"action": "dismiss"}

        def on_dialog(d):
            out["dialogs"].append({"type": d.type, "message": d.message,
                                   "action": current["action"]})
            if current["action"] == "dismiss":
                d.dismiss()
            else:
                d.accept()

        page.on("dialog", on_dialog)
        page.goto(URL + "#/memory/rag", wait_until="load")
        page.wait_for_timeout(2500)
        page.evaluate("""() => { const de=document.documentElement; const h=innerHeight;
          de.style.setProperty('--tg-content-safe-area-inset-bottom','56px');
          de.style.setProperty('--tg-safe-area-inset-bottom','56px');
          de.style.setProperty('--tg-viewport-stable-height',(h-56)+'px');
          de.style.setProperty('--app-usable-height',(h-56)+'px'); }""")
        dirty = page.evaluate(DIRTY, "limits.dig_year_back_window_days")
        page.wait_for_timeout(500)
        before = json.loads(page.evaluate(STATE))
        out["steps"].append({"step": "dirty", "ok": dirty, "state": before})

        # 1) leave, DISMISS
        current["action"] = "dismiss"
        page.evaluate("() => { window.location.hash = '#/'; }")
        page.wait_for_timeout(1200)
        after_dismiss = json.loads(page.evaluate(STATE))
        out["steps"].append({"step": "leave_dismiss", "state": after_dismiss})

        # 2) leave, ACCEPT
        current["action"] = "accept"
        page.evaluate("() => { window.location.hash = '#/'; }")
        page.wait_for_timeout(1500)
        after_accept = json.loads(page.evaluate(STATE))
        out["steps"].append({"step": "leave_accept", "state": after_accept})
        ctx.close()
        browser.close()

    d = out["steps"][1]["state"]
    a = out["steps"][2]["state"]
    out["verdict"] = {
        "dialog_shown": len(out["dialogs"]) >= 2,
        "dialog_messages": [x["message"] for x in out["dialogs"]],
        "dismiss_stays": d["hash"] == before["hash"] and d["panel"] is True,
        "value_kept_after_dismiss": d["value"] == "4",
        "accept_leaves": a["hash"] != before["hash"] and a["panel"] is False,
    }
    out["verdict"]["PASS"] = all([
        out["verdict"]["dialog_shown"], out["verdict"]["dismiss_stays"],
        out["verdict"]["value_kept_after_dismiss"],
        out["verdict"]["accept_leaves"]])
    pathlib.Path(sys.argv[1]).write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out["verdict"], ensure_ascii=False, indent=1))
    return 0 if out["verdict"]["PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
