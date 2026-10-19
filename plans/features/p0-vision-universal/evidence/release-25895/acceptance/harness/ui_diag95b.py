# -*- coding: utf-8 -*-
"""Diagnostic (read-only): where does the synthetic `content_media` group
(«Медиа-шара») live in the live «Выжимка видео» modal? Dumps modal groups,
tab buttons and the page-text presence. No writes.

Run: .venv\\Scripts\\python.exe ui_diag95b.py
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
              "query_id": "AAHaccept95diagb",
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
        page.goto(BASE + "/web/", wait_until="load", timeout=60000)
        try:
            page.wait_for_function(
                "typeof window.__adminbotVm !== 'undefined'", timeout=45000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        page.evaluate("window.__adminbotVm.setActiveChat(%d)" % WORK_CHAT)
        page.wait_for_timeout(800)
        page.evaluate("window.location.hash = '#/modules'")
        page.wait_for_timeout(1200)
        page.evaluate(
            """(id) => { const vm = window.__adminbotVm;
              const m = (vm.modules || []).find(x => x && x.id === id);
              if (m) vm.openModuleWindow(m); return !!m; }""",
            "mod_video_summary")
        try:
            page.wait_for_selector('.modal-body [data-config-group]',
                                   timeout=25000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        out["modal_groups"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('.modal-body '
              + '[data-config-group]')).map(e => e.getAttribute('data-config-group'))""")
        out["tabs"] = page.evaluate(
            """() => { const root = document.querySelector('.modal-body');
              if (!root) return null;
              return Array.from(root.querySelectorAll('button'))
                .map(b => (b.innerText || '').replace(/\\s+/g,' ').trim())
                .filter(t => t).slice(0, 20); }""")
        # click each tab-like button and look for the content_media texts
        found = []
        try:
            btns = page.query_selector_all('.modal-body button')
            for b in btns[:10]:
                try:
                    label = (b.inner_text() or '').strip()
                    if not label or len(label) > 30:
                        continue
                    b.click()
                    page.wait_for_timeout(700)
                    hit = page.evaluate(
                        "document.querySelector('.modal-body') "
                        "? document.querySelector('.modal-body').innerText "
                        ".indexOf('Медиа-шара') >= 0 : false")
                    if hit:
                        found.append(label)
                except Exception:
                    continue
        except Exception:
            pass
        out["media_share_on_tabs"] = found
        out["modal_groups_after_tabs"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('.modal-body '
              + '[data-config-group]')).map(e => e.getAttribute('data-config-group'))""")
        out["page_has_media_share"] = page.evaluate(
            "document.body.innerText.indexOf('Медиа-шара') >= 0")
        out["page_has_media_dir"] = page.evaluate(
            "document.body.innerText.indexOf('Каталог временной публикации') "
            ">= 0")
        out["vm_tab_state"] = page.evaluate(
            """() => { const vm = window.__adminbotVm;
              return { openModuleId: vm.openModuleId,
                       workspaceTab: vm.workspace && vm.workspace.tab,
                       activeTab: vm.activeTab }; }""")
        browser.close()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
