# -*- coding: utf-8 -*-
"""Live UI screenshots + closure-field read for both chats on deployed 2.58.196.

Injects the owner's signed TMA initData (from local .env via live_258196)
and the active chat id; read-only, no messages.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

import live_258196 as H

BASE = "https://admin-bot.duckdns.org/web/#/modules/initiative"
OUT = Path(__file__).parent

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
  const txt = (sel) => {
    const el = document.querySelector(sel);
    return el ? el.innerText.replace(/\s+/g, ' ').trim().slice(0, 900) : null;
  };
  const attr = (sel, name) => {
    const el = document.querySelector(sel);
    return el ? el.getAttribute(name) : null;
  };
  const cards = Array.from(document.querySelectorAll('[data-ini-card]')).map(el => ({
    card: el.getAttribute('data-ini-card'),
    text: el.innerText.replace(/\s+/g, ' ').trim().slice(0, 900),
    effect: attr('[data-ini-effect="' + el.getAttribute('data-ini-card') + '"]', 'data-ini-effect'),
  }));
  const events = Array.from(document.querySelectorAll('[data-ini-event]')).map(el => ({
    mode: el.getAttribute('data-ini-event-mode'),
    text: el.innerText.replace(/\s+/g, ' ').trim().slice(0, 300)
  }));
  return {
    cards,
    events,
    scope: txt('[data-ini-overview-scope]'),
    chat: txt('[data-ini-overview-chat]'),
    tz: txt('[data-ini-overview-tz]'),
    tz_source: attr('[data-ini-overview-tz]', 'data-ini-tz-source'),
    snapshot: txt('[data-ini-overview-snapshot]'),
    snapshot_basis: attr('[data-ini-overview-snapshot]', 'data-ini-snapshot-basis'),
    coordination: txt('[data-ini-coordination]'),
    has_refresh: !!document.querySelector('[data-ini-refresh]'),
    has_show_attempt: !!document.querySelector('[data-ini-show-attempt], [data-ini-attempt-open]'),
    no_data_count: (document.body.innerText.match(/нет данных/g) || []).length,
    heartbeat: txt('[data-meme-diag-heartbeat]'),
    image_provider: txt('[data-meme-diag-image-provider]'),
    full_text_missing: !!document.querySelector('[data-ini-step-full-text-missing]'),
    body_head: document.body.innerText.replace(/\s+/g, ' ').trim().slice(0, 1200)
  };
}
"""


def run() -> int:
    results = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for label, chat in (("chatA", H.CHAT_A), ("chatB", H.CHAT_B)):
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            ctx.add_init_script(INIT_SCRIPT % (json.dumps(H.INIT), H.OWNER,
                                              json.dumps(H.INIT), chat))
            page = ctx.new_page()
            console = []
            page.on("console", lambda m: console.append(m.type + ": " + m.text[:200])
                    if m.type in ("error", "warning") else None)
            item = {"chat_id": chat, "console": console}
            try:
                page.goto(BASE, wait_until="load", timeout=60000)
                page.wait_for_selector("header.header-sticky", state="visible", timeout=45000)
                page.wait_for_timeout(2500)
                item["overview"] = page.evaluate(EXTRACT)
                page.screenshot(path=str(OUT / ("live-overview-%s-2.58.196.png" % label)),
                                full_page=True)
                page.goto(BASE + "/memes", wait_until="load", timeout=60000)
                page.wait_for_selector("header.header-sticky", state="visible", timeout=45000)
                page.wait_for_timeout(2500)
                item["memes"] = page.evaluate(EXTRACT)
                page.screenshot(path=str(OUT / ("live-memes-%s-2.58.196.png" % label)),
                                full_page=True)
            except Exception as exc:  # noqa: BLE001
                item["error"] = type(exc).__name__ + ": " + str(exc)[:400]
            results[label] = item
            ctx.close()
        browser.close()
    (OUT / "live-ui-2.58.196.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    for label, item in results.items():
        print(label, "error=", item.get("error"),
              "console=", item.get("console")[:3])
        ov = item.get("overview") or {}
        print("  overview scope=", ov.get("scope"), "cards=", len(ov.get("cards") or []),
              "events=", len(ov.get("events") or []), "no_data=", ov.get("no_data_count"))
        me = item.get("memes") or {}
        print("  memes heartbeat=", (me.get("heartbeat") or "")[:120])
        print("  memes image_provider=", (me.get("image_provider") or "")[:120])
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
