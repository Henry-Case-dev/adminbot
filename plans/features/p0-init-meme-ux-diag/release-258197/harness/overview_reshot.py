# -*- coding: utf-8 -*-
"""Clean overview screenshots for 2.58.197 (wait for real snapshot data)."""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

import live_258197 as H

BASE = "https://admin-bot.duckdns.org/web/#/modules/initiative"
OUT = Path(__file__).parent
INIT = """
window.Telegram = window.Telegram || {};
window.Telegram.WebApp = { initData: %s, initDataUnsafe: {user:{id:%d,first_name:'owner'}},
  ready:function(){},expand:function(){},close:function(){},onEvent:function(){},
  offEvent:function(){},colorScheme:'dark',themeParams:{},isExpanded:true,
  viewportStableHeight: Math.max(0,(window.innerHeight||800)-56), viewportHeight: window.innerHeight||800 };
try { sessionStorage.setItem('adminbot.initData', %s); } catch(e){}
try { localStorage.setItem('adminbot.active_chat_id', '%s'); } catch(e){}
"""
JS = r"""
() => ({
  scope: (document.querySelector('[data-ini-overview-scope]')||{}).innerText || '',
  snapshot: (document.querySelector('[data-ini-overview-snapshot]')||{}).innerText || '',
  tz: (document.querySelector('[data-ini-overview-tz]')||{}).innerText || '',
  events: Array.from(document.querySelectorAll('[data-ini-event]')).map(el => ({
    time: (el.querySelector('.ini-event__time')||{}).innerText || '',
    label: (el.querySelector('[data-ini-event-mode]')||{}).innerText || '',
    text: el.innerText.replace(/\s+/g,' ').trim().slice(0,200)
  }))
})
"""
res = {}
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for label, chat in (("chatA", H.CHAT_A), ("chatB", H.CHAT_B)):
        ctx = browser.new_context(viewport={"width": 1280, "height": 1000})
        ctx.add_init_script(INIT % (json.dumps(H.INIT), H.OWNER, json.dumps(H.INIT), chat))
        page = ctx.new_page()
        page.goto(BASE, wait_until="load", timeout=60000)
        page.wait_for_selector("[data-ini-overview-snapshot]", state="visible", timeout=45000)
        data = None
        for _ in range(12):
            page.wait_for_timeout(1000)
            data = page.evaluate(JS)
            snap = data.get("snapshot") or ""
            if "не прочитан" not in snap and "снимок" in snap:
                break
        page.screenshot(path=str(OUT / ("live-overview-%s-2.58.197.png" % label)),
                        full_page=True)
        res[label] = data
        ctx.close()
    browser.close()
Path(OUT / "live-overview-2.58.197.json").write_text(
    json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
for label, data in res.items():
    print("==", label)
    print(" scope:", (data.get("scope") or "")[:120])
    print(" snapshot:", data.get("snapshot"))
    print(" tz:", (data.get("tz") or "")[:120])
    print(" events:", [(e.get("time"), e.get("label")) for e in data.get("events") or []])
