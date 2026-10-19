# -*- coding: utf-8 -*-
"""Diagnostic (read-only): why is [data-image-freq-facts] absent in the live
admin UI while the quota facts block renders? Dumps the page's budgetInfo
shape + the app's own computed facts. No writes.

Run: .venv\\Scripts\\python.exe ui_diag95.py
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
import urllib.parse
from pathlib import Path

REPO = Path(r"C:\Code\Python\adminbot")
BASE = "https://admin-bot.duckdns.org"
ADMIN_ID = 5885953495
WORK_CHAT = -1002661910336


def _token() -> str:
    for line in (REPO / ".env").read_text(encoding="utf-8",
                                          errors="replace").splitlines():
        line = line.strip()
        if line.startswith("API_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no token")


def make_init_data(tok: str, user_id: int = ADMIN_ID) -> str:
    fields = {"auth_date": str(int(time.time())),
              "query_id": "AAHaccept95diag",
              "user": json.dumps({"id": user_id, "first_name": "Accept95",
                                  "username": "accept95"},
                                 separators=(",", ":"))}
    dc = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", tok.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, dc.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


def main() -> int:
    init = make_init_data(_token())
    from playwright.sync_api import sync_playwright
    out: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        ctx.add_init_script(
            "try { sessionStorage.setItem('adminbot.initData', %s); } "
            "catch (e) {}" % json.dumps(init))
        page = ctx.new_page()
        reqs = []
        page.on("response", lambda r: reqs.append(
            {"url": r.url.split("?")[0], "status": r.status})
            if "/api/workers/budget" in r.url else None)
        page.goto(BASE + "/web/", wait_until="load", timeout=60000)
        try:
            page.wait_for_function(
                "typeof window.__adminbotVm !== 'undefined'", timeout=45000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        page.evaluate("window.__adminbotVm.setActiveChat(%d)" % WORK_CHAT)
        page.wait_for_timeout(1000)
        page.evaluate("window.location.hash = '#/modules/images/settings'")
        page.wait_for_timeout(2500)
        out["budget_requests"] = reqs
        out["page_state"] = page.evaluate(
            """() => {
              const vm = window.__adminbotVm;
              const bi = vm.budgetInfo || null;
              const entry = bi ? (bi.chats || []).find(c => c.scope === 'chat:%d') : null;
              const usage = vm.imageUsage || null;
              const freqFacts = vm.imageFreqFacts ? vm.imageFreqFacts() : null;
              return {
                activeChatId: vm.activeChatId,
                budgetInfo_present: !!bi,
                chats_len: bi ? (bi.chats || []).length : null,
                chat_entry_keys: entry ? Object.keys(entry) : null,
                entry_has_image_usage: entry ? !!entry.image_usage : null,
                entry_has_freq: entry && entry.image_usage ? ('freq' in entry.image_usage) : null,
                imageUsage_chat_keys: usage && usage.chat ? Object.keys(usage.chat) : null,
                imageUsage_chat_freq_present: !!(usage && usage.chat && usage.chat.freq),
                freqFacts_freq_present: !!(freqFacts && freqFacts.freq),
                freqFacts_enabled: freqFacts ? freqFacts.enabled : null,
                dom_freq_facts: !!document.querySelector('[data-image-freq-facts]'),
                dom_quota_facts: !!document.querySelector('[data-image-quota-facts]'),
                dom_group: !!document.querySelector('[data-config-group="limits_images"]'),
              };
            }""" % WORK_CHAT)
        out["api_direct"] = page.evaluate(
            """async () => {
              const r = await fetch('/api/workers/budget', {headers: {
                'X-Telegram-Init-Data': window.__adminbotVm.initData || ''}});
              const j = await r.json();
              const e = (j.chats || []).find(c => c.scope === 'chat:%d');
              return { status: r.status, entry_keys: e ? Object.keys(e) : null,
                       has_image_usage: e ? !!e.image_usage : null,
                       has_freq: e && e.image_usage ? ('freq' in e.image_usage) : null };
            }""" % WORK_CHAT)
        browser.close()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
