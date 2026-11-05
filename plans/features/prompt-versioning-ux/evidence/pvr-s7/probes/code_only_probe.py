# -*- coding: utf-8 -*-
"""PVR-S7: code-only read-only in the history catalogue (real registry + real UI component)."""
import importlib.util, json, os, sys

WT = r"C:/Users/main/.config/opencode/WorkspaceData/worktrees/c742e4de9e92c489/pv-s7-review"
os.chdir(WT); sys.path.insert(0, WT)
sys.path.insert(0, os.path.join(WT, "tools"))
spec = importlib.util.spec_from_file_location("pv_e2e", os.path.join(WT, "tests", "ui_prompt_version_card_e2e.py"))
E = importlib.util.module_from_spec(spec); sys.modules["pv_e2e"] = E; spec.loader.exec_module(E)
import services.prompt_registry as pr

res = {}
fails = []
code_only = [b for b in pr.all_blocks() if b.ui == "code_only"]
res["code_only_blocks"] = len(code_only)
res["code_only_have_pg_key"] = [b.block_id for b in code_only if b.pg_key]
# real server rule: manageable = bool(pg_key) and not hidden
res["manageable_for_code_only"] = {b.block_id: bool(b.pg_key) for b in code_only[:8]}
if res["code_only_have_pg_key"]:
    fails.append("code_only with pg_key: %r" % res["code_only_have_pg_key"][:5])

E.STATE["entries"] = E.build_entries()
E.STATE["code_only"] = True
PORT = 8908; E.PORT = PORT; E.BASE = "http://127.0.0.1:%d" % PORT
E.serve_static(PORT, os.path.join(WT, "web"))

from playwright.sync_api import sync_playwright
def click_text(page, root_sel, text):
    return page.evaluate("""([root, t]) => {
        const r = document.querySelector(root); if (!r) return 'no-root';
        const el = Array.from(r.querySelectorAll('button, a')).find(e => (e.textContent||'').trim().indexOf(t) >= 0);
        if (!el) return 'no-button'; el.scrollIntoView({block:'center'}); el.click(); return 'clicked';
    }""", [root_sel, text])

with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(viewport={"width": 1440, "height": 900})
    ctx.route("**/api/**", E.make_api_handler())
    ctx.route("**/static/vendor/telegram-web-app.js", lambda r: r.fulfill(status=200, content_type="application/javascript", body=E.SDK_STUB))
    ctx.add_init_script("try { localStorage.setItem('adminbot.active_chat_id','%d'); } catch(e){}" % E.CHAT_A)
    page = ctx.new_page(); page.set_default_timeout(20000)
    page.on("dialog", lambda d: d.accept())
    try:
        page.goto(E.BASE + "/#/modules/initiative/memes", wait_until="load")
        page.wait_for_selector("[data-ini-prompt='joke']", state="visible"); page.wait_for_timeout(800)
        click_text(page, "[data-ini-prompt='joke']", "История версий")
        page.wait_for_timeout(1200)
        info = page.evaluate("""() => {
            const panel = document.querySelector("[data-prompt-history-panel], .pv-panel, .pv-history");
            const txt = ((panel && panel.textContent) || '').replace(/\\s+/g, ' ');
            const btns = panel ? Array.from(panel.querySelectorAll('button')).map(e => (e.textContent||'').trim()).filter(Boolean) : [];
            const vis = (t) => { if (!panel) return false;
                const el = Array.from(panel.querySelectorAll('button')).find(e => (e.textContent||'').trim() === t);
                if (!el) return false; const r = el.getBoundingClientRect(); return r.width>0 && r.height>0; };
            return {text: txt, buttons: btns,
                    apply: vis('Применить эту версию'), assign: vis('Назначить базовой'),
                    reason: txt.indexOf('code-only') >= 0};
        }""")
        res["ui"] = info
        if not info["reason"]:
            fails.append("no honest code-only reason in panel")
        if info["apply"] or info["assign"]:
            fails.append("active switch buttons visible for code-only: apply=%s assign=%s" % (info["apply"], info["assign"]))
        page.screenshot(path=r"C:/Users/main/.config/opencode/WorkspaceData/runs/pv-s7/code_only_panel.png")
    except Exception as exc:
        fails.append("exception: %s" % str(exc)[:300])
    finally:
        ctx.close(); b.close()

res["failures"] = fails
print("FAILS", json.dumps(res["failures"], ensure_ascii=False)); print("BTNS", json.dumps(res.get("ui",{}).get("buttons"), ensure_ascii=False))

