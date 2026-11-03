# -*- coding: utf-8 -*-
import os, sys, json, importlib.util, traceback
REPO = r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\EPIC-PROMPT-VERSIONING-UX-01-pv-ux"
RUN = r"C:\Users\main\.config\opencode\WorkspaceData\runs\pv-s4\rr2"
spec = importlib.util.spec_from_file_location(
    "pv_e2e", os.path.join(REPO, "tests", "ui_prompt_version_card_e2e.py"))
E = importlib.util.module_from_spec(spec); sys.modules["pv_e2e"] = E
spec.loader.exec_module(E)
R = []
def rec(n, ok, d=""):
    R.append({"name": n, "ok": bool(ok), "detail": str(d)[:400]})
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else " :: " + str(d)[:250]))

ROLLBACK = "\u041e\u0442\u043a\u0430\u0442\u0438\u0442\u044c"

def main():
    shots = os.path.join(RUN, "shots"); os.makedirs(shots, exist_ok=True)
    httpd = E.serve_static(0, os.path.join(REPO, "web"))
    E.BASE = "http://127.0.0.1:%d" % httpd.server_address[1]

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # --- cursor paging proof (record real request URLs, then fall back)
        E.STATE["posts"] = []; E.STATE["gets"] = []
        E.STATE["active"] = "rev-manual-2"; E.STATE["entries"] = E.build_entries()
        E.STATE["core_text"] = {"full": "FULL-CORE-v1", "compact": "COMPACT-CORE-v1"}
        ctx, page = E.new_page(browser, 1366, 768)
        URLS = []
        def rec_route(route):
            URLS.append(route.request.url)
            route.fallback()
        ctx.route("**/api/prompts/**", rec_route)
        try:
            page.goto(E.BASE + "/#/ai/speech", wait_until="load")
            page.wait_for_selector(".speech-screen", state="visible")
            page.wait_for_timeout(600)
            page.click("[data-speech-area='rules']")
            page.wait_for_selector("[data-speech-rules-link='core']", state="visible")
            page.click("[data-speech-rules-link='core']")
            page.wait_for_selector("[data-speech-core-versions] [data-prompt-history-toggle]",
                                   state="visible")
            page.wait_for_timeout(600)
            page.click("[data-speech-core-versions] [data-prompt-history-toggle]")
            page.wait_for_selector("[data-pv-panel]", state="visible")
            page.wait_for_timeout(500)
            n1 = page.evaluate("() => document.querySelectorAll('[data-pv-row]').length")
            while page.locator("[data-pv-load-more]").count():
                page.click("[data-pv-load-more]"); page.wait_for_timeout(450)
            n2 = page.evaluate("() => document.querySelectorAll('[data-pv-row]').length")
            vers = [u for u in URLS if "/versions" in u]
            cur = [u for u in vers if "cursor=" in u]
            rec("cursor/first-page", n1 == 50, n1)
            rec("cursor/load-more-requests", len(cur) >= 2,
                [u.split("/api/prompts/")[-1][:80] for u in cur])
            rec("cursor/total", n2 == len(E.STATE["entries"]),
                {"rows": n2, "entries": len(E.STATE["entries"])})
        except Exception:
            rec("cursor/EXCEPTION", False, traceback.format_exc()[-500:])
        finally:
            ctx.close()

        # --- «Стиль письма»: no prompt-registry card expected
        E.STATE["posts"] = []; E.STATE["gets"] = []
        ctx, page = E.new_page(browser, 1536, 900)
        try:
            page.goto(E.BASE + "/#/ai/speech", wait_until="load")
            page.wait_for_selector(".speech-screen", state="visible")
            page.wait_for_timeout(600)
            areas = page.evaluate(
                "() => Array.from(document.querySelectorAll('[data-speech-area]'))"
                ".map((e) => e.getAttribute('data-speech-area'))")
            rec("style/areas", "style" in areas, areas)
            page.click("[data-speech-area='style']")
            page.wait_for_timeout(1200)
            st = page.evaluate("""
                () => {
                  const sec = document.querySelector('.speech-screen') || document.body;
                  const txt = (sec.innerText || '');
                  return {
                    cards: sec.querySelectorAll('[data-prompt-history]').length,
                    rows: sec.querySelectorAll('[data-pv-row]').length,
                    styleVisible: !!document.querySelector('[data-speech-style-dirty]'),
                    rollback: (txt.match(/%s/g) || []).length,
                    histRows: sec.querySelectorAll('.speech-scrollable').length,
                    detailButtons: sec.querySelectorAll('details button').length,
                    rawShaInOpen: (txt.match(/[0-9a-f]{12}/g) || []).length,
                  };
                }
            """ % ROLLBACK)
            rec("style/no-version-card", st["cards"] == 0 and st["rows"] == 0, st)
            rec("style/no-rollback-button", st["rollback"] == 0, st["rollback"])
            page.screenshot(path=os.path.join(shots, "rr2_style_1536.png"), full_page=True)
            # open the style diagnostics disclosure: history rows are read-only text
            try:
                page.click("details summary")
                page.wait_for_timeout(400)
            except Exception:
                pass
            after = page.evaluate(
                "() => ({buttons: document.querySelectorAll('.speech-screen details button').length,"
                " cards: document.querySelectorAll('[data-prompt-history]').length})")
            rec("style/details-readonly", after["buttons"] == 0 and after["cards"] == 0, after)
            page.screenshot(path=os.path.join(shots, "rr2_style_details_1536.png"),
                            full_page=True)
        except Exception:
            rec("style/EXCEPTION", False, traceback.format_exc()[-500:])
        finally:
            ctx.close()

        # --- «Характер» follows the active edition (independent quick check)
        E.STATE["posts"] = []; E.STATE["entries"] = E.build_entries()
        E.STATE["core_text"] = {"full": "FULL-CORE-v1", "compact": "COMPACT-CORE-v1"}
        ctx, page = E.new_page(browser, 1366, 768)
        try:
            page.goto(E.BASE + "/#/ai/speech", wait_until="load")
            page.wait_for_selector(".speech-screen", state="visible")
            page.wait_for_timeout(600)
            page.click("[data-speech-area='rules']")
            page.wait_for_selector("[data-speech-rules-link='core']", state="visible")
            page.click("[data-speech-rules-link='core']")
            page.wait_for_selector("[data-speech-core-versions] [data-prompt-history]",
                                   state="visible")
            page.wait_for_timeout(600)
            page.locator(".speech-tab").nth(1).click()
            page.wait_for_timeout(900)
            key = page.evaluate(
                "() => { const c = document.querySelector('[data-speech-core-versions]"
                " [data-prompt-history]'); return c ? c.getAttribute('data-pv-key') : null; }")
            rec("core/compact-key", key == "core.personality.compact", key)
            page.locator(".speech-tab").nth(0).click()
            page.wait_for_timeout(800)
            key2 = page.evaluate(
                "() => { const c = document.querySelector('[data-speech-core-versions]"
                " [data-prompt-history]'); return c ? c.getAttribute('data-pv-key') : null; }")
            rec("core/full-key-back", key2 == "core.personality", key2)
            # journal outage: honest message, no action buttons
            E.STATE["journal_down"] = True
            page.locator(".speech-tab").nth(1).click(); page.wait_for_timeout(700)
            page.locator(".speech-tab").nth(0).click(); page.wait_for_timeout(700)
            page.click("[data-speech-core-versions] [data-prompt-history-toggle]")
            page.wait_for_timeout(900)
            out = page.evaluate(
                "() => ({rows: document.querySelectorAll('[data-pv-row]').length,"
                " err: ((document.querySelector('[data-pv-panel]') || {}).innerText || '')"
                ".replace(/\\s+/g,' ').trim().slice(0, 160)})")
            rec("core/journal-down-honest", out["rows"] == 0 and len(out["err"]) > 10, out)
        except Exception:
            rec("core/EXCEPTION", False, traceback.format_exc()[-500:])
        finally:
            ctx.close()
        browser.close()
    bad = [x for x in R if not x["ok"]]
    with open(os.path.join(RUN, "rr2b-results.json"), "w", encoding="utf-8") as fh:
        json.dump({"total": len(R), "failed": len(bad), "checks": R}, fh,
                  ensure_ascii=False, indent=1)
    print("\n== checks=%d failed=%d" % (len(R), len(bad)))

main()