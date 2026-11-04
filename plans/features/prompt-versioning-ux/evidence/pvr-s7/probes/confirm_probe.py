# -*- coding: utf-8 -*-
"""PVR-S7 reviewer probe: confirm dialogs for assign/restore baseline + editor buttons."""
import importlib.util, json, os, sys

WT = r"C:/Users/main/.config/opencode/WorkspaceData/worktrees/c742e4de9e92c489/pv-s7-review"
os.chdir(WT); sys.path.insert(0, WT)
spec = importlib.util.spec_from_file_location("pv_e2e", os.path.join(WT, "tests", "ui_prompt_version_card_e2e.py"))
E = importlib.util.module_from_spec(spec); sys.modules["pv_e2e"] = E; spec.loader.exec_module(E)

E.STATE["entries"] = E.build_entries()
PORT = 8907
E.PORT = PORT
E.BASE = "http://127.0.0.1:%d" % PORT
E.serve_static(PORT, os.path.join(WT, "web"))

out = {"dialogs": [], "checks": {}, "posts": []}
fails = []

def chk(name, cond, detail=""):
    out["checks"][name] = {"ok": bool(cond), "detail": detail}
    if not cond:
        fails.append("%s: %s" % (name, detail))

from playwright.sync_api import sync_playwright

def click_text(page, root_sel, text):
    return page.evaluate(
        """([root, t]) => {
            const r = document.querySelector(root);
            if (!r) return 'no-root';
            const els = Array.from(r.querySelectorAll('button, a'));
            const el = els.find(e => (e.textContent || '').trim().indexOf(t) >= 0);
            if (!el) return 'no-button';
            el.scrollIntoView({block: 'center'});
            el.click();
            return 'clicked';
        }""", [root_sel, text])

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    ctx.route("**/api/**", E.make_api_handler())
    ctx.route("**/static/vendor/telegram-web-app.js",
              lambda r: r.fulfill(status=200, content_type="application/javascript", body=E.SDK_STUB))
    ctx.add_init_script("try { localStorage.setItem('adminbot.active_chat_id', '%d'); } catch (e) {}" % E.CHAT_A)
    page = ctx.new_page(); page.set_default_timeout(20000)
    mode = {"accept": False}
    def on_dialog(d):
        out["dialogs"].append({"message": d.message or "", "type": d.type, "accepted": mode["accept"]})
        (d.accept() if mode["accept"] else d.dismiss())
    page.on("dialog", on_dialog)
    try:
        page.goto(E.BASE + "/#/modules/initiative/memes", wait_until="load")
        page.wait_for_selector("[data-ini-prompt='joke']", state="visible")
        page.wait_for_timeout(900)
        # UX-02: editor buttons inside the very card that owns the version UI
        card = page.evaluate("""() => {
            const c = document.querySelector("[data-ini-prompt='joke']");
            if (!c) return null;
            const btns = Array.from(c.querySelectorAll('button')).map(e => (e.textContent || '').trim());
            const vis = (t) => { const el = Array.from(c.querySelectorAll('button')).find(e => (e.textContent||'').trim() === t);
                if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
            return {buttons: btns, discard: vis('Отменить несохранённое'), save: vis('Сохранить'),
                    history: !!c.querySelector("[data-prompt-history]"),
                    textarea: !!c.querySelector('textarea')};
        }""")
        out["card"] = card
        chk("ux02_discard_visible", card and card["discard"], json.dumps(card, ensure_ascii=False)[:300])
        chk("ux02_save_visible", card and card["save"], json.dumps(card, ensure_ascii=False)[:300])

        r = click_text(page, "[data-ini-prompt='joke']", "История версий")
        chk("history_toggle", r == "clicked", r)
        page.wait_for_timeout(1200)
        page.wait_for_selector("[data-prompt-history-panel], .pv-panel, .pv-history", state="visible")

        # --- 1. assign baseline: CANCEL must not write anything
        before = len(E.STATE["posts"])
        mode["accept"] = False
        r = click_text(page, "[data-prompt-history-panel], .pv-panel, .pv-history", "Назначить базовой")
        page.wait_for_timeout(700)
        after = E.STATE["posts"][before:]
        body = page.evaluate("() => (document.body.textContent || '').replace(/\\s+/g,' ')")
        chk("assign_clicked", r == "clicked", r)
        msg = out["dialogs"][-1]["message"] if out["dialogs"] else ""
        chk("assign_dialog_before_action", "Меняется только эталон" in msg and "останется прежним" in msg, msg)
        chk("assign_cancel_no_write", len([x for x in after if "baseline" in str(x)]) == 0, str(after))
        chk("assign_cancel_notice", "Назначение отменено" in body, body[-260:])

        # --- 2. assign baseline: ACCEPT writes exactly one pointer event
        before = len(E.STATE["posts"])
        mode["accept"] = True
        r = click_text(page, "[data-prompt-history-panel], .pv-panel, .pv-history", "Назначить базовой")
        page.wait_for_timeout(1500)
        after = [x for x in E.STATE["posts"][before:]]
        out["posts"] = after
        body = page.evaluate("() => (document.body.textContent || '').replace(/\\s+/g,' ')")
        chk("assign_accept_one_post", len(after) == 1 and "baseline" in str(after[0]), str(after))
        chk("assign_no_activate", not any("/activate" in str(x) for x in after), str(after))
        chk("assign_truth_notice", "Базовая версия изменена, действующий текст пока прежний" in body, body[-300:])

        # --- 3. restore baseline asks first
        out["dialogs"].clear()
        before = len(E.STATE["posts"])
        mode["accept"] = False
        r = click_text(page, "[data-prompt-history-panel], .pv-panel, .pv-history", "Восстановить базовую")
        page.wait_for_timeout(700)
        after = E.STATE["posts"][before:]
        msg = out["dialogs"][-1]["message"] if out["dialogs"] else ""
        chk("restore_clicked", r == "clicked", r)
        chk("restore_dialog_warns_text_changes", "Действующий текст" in msg and "базовой версии" in msg, msg)
        chk("restore_cancel_no_write", len([x for x in after if "restore" in str(x)]) == 0, str(after))
        page.screenshot(path=r"C:/Users/main/.config/opencode/WorkspaceData/runs/pv-s7/assign_dialog_state.png")
    except Exception as exc:
        fails.append("exception: %s" % str(exc)[:400])
    finally:
        ctx.close(); b.close()

out["failures"] = fails
print(json.dumps(out, ensure_ascii=False, indent=2)[:4000])
