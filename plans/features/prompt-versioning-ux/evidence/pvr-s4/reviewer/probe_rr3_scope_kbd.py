# -*- coding: utf-8 -*-
"""Re-review 3: чем на самом деле переключается чат в ui_p0a (B1 proof path)."""
import os, sys, importlib.util, json
REPO = r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\EPIC-PROMPT-VERSIONING-UX-01-pv-ux"
spec = importlib.util.spec_from_file_location("p0a", os.path.join(REPO, "tests", "ui_p0a_ux_speech_compact_e2e.py"))
P = importlib.util.module_from_spec(spec); sys.modules["p0a"] = P
spec.loader.exec_module(P)
P.serve_static(P.PORT, os.path.join(REPO, "web"))
from playwright.sync_api import sync_playwright
out = {}
with sync_playwright() as pw:
    br = pw.chromium.launch()
    ctx, page = P.new_page(br, 390, 844, None, chat=P.CHAT_A)
    try:
        P.open_speech(page)
        P.open_speech_section(page, "core")
        page.wait_for_selector(".speech-editor", state="visible"); page.wait_for_timeout(400)
        page.locator(".speech-section .speech-editor").first.click()
        page.locator(".speech-section .speech-editor").first.type(" ЧЕРНОВИК A", delay=3)
        page.click(".scope-trigger")
        page.wait_for_selector(".scope-panel", state="visible")
        page.wait_for_timeout(300)
        out["focus0"] = page.evaluate("() => { const vm = window.__adminbotVm;"
                                      " const o = (vm.scopeOptions||[])[vm.scopeFocus];"
                                      " return {focus: vm.scopeFocus, title: o ? o.title : null,"
                                      " n: (vm.scopeOptions||[]).length,"
                                      " titles: (vm.scopeOptions||[]).map(x => x.title)}; }")
        # hit-test пункта «Чат B»: кликается ли он указателем
        out["hit_opt"] = page.evaluate("() => { const els = Array.from(document.querySelectorAll('.scope-option'));"
                                       " const o = els.find(e => (e.textContent||'').indexOf('Чат B') >= 0);"
                                       " if (!o) return null; const r = o.getBoundingClientRect();"
                                       " const h = document.elementFromPoint((r.left+r.right)/2, (r.top+r.bottom)/2);"
                                       " return {rect: [Math.round(r.top), Math.round(r.bottom), Math.round(r.left), Math.round(r.right)],"
                                       " vh: window.innerHeight, hitSelf: !!(h && (h === o || o.contains(h)))}; }")
        presses = 0
        for _ in range(6):
            cur = page.evaluate("() => { const vm = window.__adminbotVm;"
                                " const o = (vm.scopeOptions||[])[vm.scopeFocus]; return {t: o ? o.title : null, f: vm.scopeFocus}; }")
            if cur["t"] == "Чат B":
                break
            page.keyboard.press("ArrowDown"); presses += 1
        out["presses"] = presses
        out["at"] = page.evaluate("() => { const vm = window.__adminbotVm;"
                                  " const o = (vm.scopeOptions||[])[vm.scopeFocus]; return o ? o.title : null; }")
        page.keyboard.press("Enter")
        page.wait_for_timeout(900)
        out["dialogs"] = list(P.DIALOGS)
        out["active_chat"] = page.evaluate("() => (window.__adminbotVm || {}).activeChatId")
        out["grid_reset"] = page.locator(".speech-grid").count()
    finally:
        ctx.close(); br.close()
print(json.dumps(out, ensure_ascii=False, indent=1))
