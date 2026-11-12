# -*- coding: utf-8 -*-
"""Re-shoot the Status page «Самодиагностика» block for chat B on deployed 2.58.198.

More robust navigation than the first pass: click the «Статус» nav item, wait for
the block's runtime line to become non-empty, then capture.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(r"C:\Code\Python\adminbot\plans\features\self-diag-01\release-258198\harness")))
import live_258198 as H  # noqa: E402

OUT = Path(sys.argv[1]).resolve()
CHAT = H.CHAT_B
BASE = H.BASE + "/web/#/status"

INIT_SCRIPT = """
window.Telegram = window.Telegram || {};
window.Telegram.WebApp = {
  initData: %s,
  initDataUnsafe: { user: { id: %d, first_name: 'owner' } },
  ready: function(){}, expand: function(){}, close: function(){},
  onEvent: function(){}, offEvent: function(){},
  colorScheme: 'dark', themeParams: {}, isExpanded: true,
  viewportStableHeight: Math.max(0, (window.innerHeight || 800) - 56),
  viewportHeight: window.innerHeight || 800
};
try { sessionStorage.setItem('adminbot.initData', %s); } catch (e) {}
try { localStorage.setItem('adminbot.active_chat_id', '%s'); } catch (e) {}
"""

EXTRACT = r"""
() => {
  const t = (sel) => { const el = document.querySelector(sel); return el ? el.innerText.replace(/\s+/g, ' ').trim().slice(0, 1500) : null; };
  const block = document.querySelector('[data-self-diagnosis]');
  return {
    block_present: !!block,
    route: location.hash,
    runtime: t('[data-self-diagnosis-runtime]'),
    analytics: t('[data-self-diagnosis-analytics]'),
    source_badge: t('[data-self-diagnosis-source]'),
    error: t('[data-self-diagnosis-error]'),
    rows: Array.from(document.querySelectorAll('[data-self-diagnosis-row]')).length,
    block_text: block ? block.innerText.replace(/\s+/g, ' ').trim().slice(0, 2000) : null,
  };
}
"""


def main() -> int:
    init = json.dumps(H.INIT)
    result = {"release": "2.58.198", "chat": "B", "chat_id": CHAT}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(viewport={"width": 1280, "height": 2200}, locale="ru-RU")
            ctx.add_init_script(INIT_SCRIPT % (init, H.OWNER, init, CHAT))
            page = ctx.new_page()
            page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            # click the «Статус» nav entry if present (hash routing can race on cold load)
            try:
                page.get_by_text("Статус", exact=True).first.click(timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
            for _ in range(3):
                if page.query_selector("[data-self-diagnosis-refresh]"):
                    try:
                        page.click("[data-self-diagnosis-refresh]", timeout=4000)
                    except Exception:
                        pass
                page.wait_for_timeout(2000)
                cur = page.evaluate(EXTRACT)
                if cur.get("runtime"):
                    break
            data = page.evaluate(EXTRACT)
            result.update(data)
            shot = OUT / "live-selfdiag-B-2.58.198.png"
            el = page.query_selector("[data-self-diagnosis]")
            try:
                (el or page).screenshot(path=str(shot), timeout=20000)
            except Exception:
                page.screenshot(path=str(shot))
            result["screenshot"] = shot.name
            ctx.close()
        finally:
            browser.close()
    (OUT / "live-ui-B-2.58.198.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
