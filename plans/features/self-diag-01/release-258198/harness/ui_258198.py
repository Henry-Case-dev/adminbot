# -*- coding: utf-8 -*-
"""2.58.198 live UI check: «Самодиагностика» block on the existing Status page.

Injects the owner's signed TMA initData (local .env via live_258198) and the
active chat id; read-only, no messages. Screenshots the block for both chats.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

import live_258198 as H

BASE = "https://admin-bot.duckdns.org/web/#/status"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
CHATS = {"A": H.CHAT_A, "B": H.CHAT_B}

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
  const block = document.querySelector('[data-self-diagnosis]');
  const txt = (sel) => {
    const el = document.querySelector(sel);
    return el ? el.innerText.replace(/\s+/g, ' ').trim().slice(0, 1200) : null;
  };
  return {
    block_present: !!block,
    source_badge: txt('[data-self-diagnosis-source]'),
    error: txt('[data-self-diagnosis-error]'),
    runtime: txt('[data-self-diagnosis-runtime]'),
    sources: txt('[data-self-diagnosis-sources]'),
    analytics: txt('[data-self-diagnosis-analytics]'),
    rows: Array.from(document.querySelectorAll('[data-self-diagnosis-row]')).map(
      el => el.innerText.replace(/\s+/g, ' ').trim().slice(0, 200)),
    has_refresh: !!document.querySelector('[data-self-diagnosis-refresh]'),
    block_text: block ? block.innerText.replace(/\s+/g, ' ').trim().slice(0, 2500) : null,
    body_head: document.body.innerText.replace(/\s+/g, ' ').trim().slice(0, 600),
    route: location.hash,
  };
}
"""


def main() -> int:
    results: dict = {"release": "2.58.198", "checks": {}}
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for label, chat in CHATS.items():
                ctx = browser.new_context(viewport={"width": 1280, "height": 2200},
                                          locale="ru-RU")
                page = ctx.new_page()
                init = json.dumps(H.INIT)
                page.add_init_script(INIT_SCRIPT % (init, H.OWNER, init, chat))
                page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3500)
                if not page.query_selector("[data-self-diagnosis]"):
                    page.goto(BASE.replace("#/status", "#/status/graph"),
                              wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(3500)
                if page.query_selector("[data-self-diagnosis-refresh]"):
                    try:
                        page.click("[data-self-diagnosis-refresh]", timeout=5000)
                        page.wait_for_timeout(2500)
                    except Exception:
                        pass
                data = page.evaluate(EXTRACT)
                results["checks"][label] = {"chat_id": chat, **data}
                shot = OUT / ("live-selfdiag-%s-2.58.198.png" % label)
                el = page.query_selector("[data-self-diagnosis]")
                try:
                    (el or page).screenshot(path=str(shot), timeout=20000)
                except Exception:
                    page.screenshot(path=str(shot), full_page=False)
                results["checks"][label]["screenshot"] = shot.name
                ctx.close()
        finally:
            browser.close()
    (OUT / "live-ui-2.58.198.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
