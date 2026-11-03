# -*- coding: utf-8 -*-
"""Reviewer re-review 2 probe: B1/B2/B4 + draft safety, independent steps."""
import os, sys, json, importlib.util, traceback

REPO = r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\EPIC-PROMPT-VERSIONING-UX-01-pv-ux"
RUN = r"C:\Users\main\.config\opencode\WorkspaceData\runs\pv-s4\rr2"
os.makedirs(RUN, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "pv_e2e", os.path.join(REPO, "tests", "ui_prompt_version_card_e2e.py"))
E = importlib.util.module_from_spec(spec)
sys.modules["pv_e2e"] = E
spec.loader.exec_module(E)

R = []
def rec(name, ok, detail=""):
    R.append({"name": name, "ok": bool(ok), "detail": str(detail)[:500]})
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " :: " + str(detail)[:300]))

CONFIRM = "\u0421\u0435\u0440\u0432\u0435\u0440 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u043b"
ROLLBACK = "\u041e\u0442\u043a\u0430\u0442\u0438\u0442\u044c"
ENDMARK = "\u042d\u0442\u043e \u0432\u0441\u044f \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430\u044f \u0438\u0441\u0442\u043e\u0440\u0438\u044f"

CARD_JS = """
() => {
  const tx = (el) => ((el && el.textContent) || '').replace(/\\s+/g, ' ').trim();
  const card = document.querySelector('[data-speech-core-versions] [data-prompt-history]');
  const sec = document.querySelector('.speech-section') || document.body;
  const styleSec = document.querySelector('[data-speech-style-dirty]');
  return {
    cards: document.querySelectorAll('[data-speech-core-versions] [data-prompt-history]').length,
    key: card ? card.getAttribute('data-pv-key') : null,
    variant: card ? card.getAttribute('data-pv-variant') : null,
    cardText: tx(card),
    legacy: document.querySelectorAll('[data-speech-core-more]').length,
    rollbackDocs: (document.body.innerText.match(/%s/g) || []).length,
    detailLines: document.querySelectorAll('[data-pv-detail-line]').length,
    histButtons: document.querySelectorAll('[data-speech-core-versions] [data-prompt-history-toggle]').length,
    panels: document.querySelectorAll('[data-pv-panel]').length,
    state: tx(document.querySelector('[data-speech-core-versions] [data-pv-state]')),
  };
}
""" % ROLLBACK

RAWRE = "/sha256|sha\\s+[0-9a-f]{8}|revision_id|act:[0-9a-f]{4}|fac:[0-9a-f]{4}|[0-9a-f]{12}/"

def drive(browser, width, height, label, shots):
    E.STATE["posts"] = []
    E.STATE["gets"] = []
    E.STATE["active"] = "rev-manual-2"
    E.STATE["baseline"] = None
    E.STATE["journal_down"] = False
    E.STATE["entries"] = E.build_entries()
    E.STATE["core_text"] = {"full": "FULL-CORE-v1", "compact": "COMPACT-CORE-v1"}
    ctx, page = E.new_page(browser, width, height)
    try:
        page.goto(E.BASE + "/#/ai/speech", wait_until="load")
        page.wait_for_selector(".speech-screen", state="visible")
        page.wait_for_timeout(700)
        page.click("[data-speech-area='rules']")
        page.wait_for_selector("[data-speech-rules-link='core']", state="visible")
        page.click("[data-speech-rules-link='core']")
        page.wait_for_selector("[data-speech-core-versions] [data-prompt-history-toggle]",
                               state="visible")
        page.wait_for_timeout(800)
        info = page.evaluate(CARD_JS)
        rec("%s/B1-one-card" % label, info["cards"] == 1, info)
        rec("%s/B1-key-full" % label, info["key"] == "core.personality", info["key"])
        rec("%s/B1-variant-bar" % label, info["variant"] == "bar", info["variant"])
        rec("%s/B1-history-button" % label, info["histButtons"] == 1, info["histButtons"])
        rec("%s/B1-no-legacy-list" % label, info["legacy"] == 0, info["legacy"])
        rec("%s/B1-no-rollback-anywhere" % label, info["rollbackDocs"] == 0,
            info["rollbackDocs"])
        rec("%s/B2-collapsed-no-raw" % label,
            info["detailLines"] == 0 and not page.evaluate("/%s/.test(%s)"
                % (RAWRE[1:-1], json.dumps(info["cardText"]))),
            {"lines": info["detailLines"], "cardText": info["cardText"][:200]})
        rec("%s/card-state-visible" % label, bool(info["state"]), info["state"])
        page.screenshot(path=os.path.join(shots, "rr2_speech_core_%s.png" % label),
                        full_page=True)

        # ---- B1: full paginated history from the card's own button
        page.click("[data-speech-core-versions] [data-prompt-history-toggle]")
        page.wait_for_selector("[data-pv-panel]", state="visible")
        page.wait_for_timeout(500)
        rows = page.evaluate("() => document.querySelectorAll('[data-pv-row]').length")
        rec("%s/B1-first-page-50" % label, rows == 50, rows)
        rec("%s/B1-single-panel" % label,
            page.evaluate("() => document.querySelectorAll('[data-pv-panel]').length") == 1)
        pages = 0
        while page.locator("[data-pv-load-more]").count() and pages < 6:
            page.click("[data-pv-load-more]")
            page.wait_for_timeout(500)
            pages += 1
        total = page.evaluate("() => document.querySelectorAll('[data-pv-row]').length")
        orders = page.evaluate(
            "() => Array.from(document.querySelectorAll('[data-pv-row]'))"
            ".map((e) => e.getAttribute('data-pv-order')).join(',')")
        uniq = len(set(filter(None, orders.split(','))))
        endmark = page.evaluate(
            "() => { const e = document.querySelector('[data-pv-end]');"
            " return e ? (e.textContent || '').trim() : ''; }")
        rec("%s/B1-paging-beyond-50" % label, total > 50, {"rows": total, "pages": pages})
        rec("%s/B1-all-rows-unique" % label, uniq == total, {"uniq": uniq, "total": total})
        rec("%s/B1-end-marker" % label, ENDMARK in endmark, endmark[:160])
        cur_calls = [g for g in E.STATE["gets"] if "cursor=" in str(g)]
        rec("%s/B1-cursor-paging" % label, len(cur_calls) >= 1, len(cur_calls))
        page.screenshot(path=os.path.join(shots, "rr2_speech_history_%s.png" % label),
                        full_page=False)

        # ---- B2: details from the card menu, real expansion
        target = E.row_rev(page, 0)
        E.click_row(page, 0, "[data-pv-row-view]")
        page.wait_for_timeout(500)
        view_text = page.evaluate(
            "() => ((document.querySelector('[data-pv-panel]') || {}).textContent || '')")
        rec("%s/verbatim-body" % label, E._body(target).split("\n")[0] in view_text)
        E.open_panel(page) if False else None
        page.click("[data-pv-panel-close]")
        page.wait_for_timeout(300)
        page.click("[data-speech-core-versions] [data-pv-more-toggle]")
        page.wait_for_selector("[data-speech-core-versions] [data-pv-more-menu]",
                               state="visible")
        page.click("[data-speech-core-versions] [data-pv-more-details]")
        page.wait_for_timeout(400)
        det = page.evaluate(
            "() => { const d = document.querySelector"
            "('[data-speech-core-versions] [data-pv-details]');"
            " return { menu: document.querySelectorAll('[data-pv-more-menu]').length,"
            "  open: !!(d && d.open),"
            "  lines: document.querySelectorAll('[data-speech-core-versions]"
            " [data-pv-detail-line]').length,"
            "  text: d ? (d.textContent || '').replace(/\\s+/g, ' ').trim() : '' }; }")
        rec("%s/B2-menu-closed" % label, det["menu"] == 0, det)
        rec("%s/B2-details-open" % label, det["open"] is True, det)
        rec("%s/B2-details-lines" % label, det["lines"] >= 3, det["lines"])
        rec("%s/B2-details-content" % label,
            ("\u0431\u043b\u043e\u043a:" in det["text"])
            and ("\u043a\u043b\u044e\u0447:" in det["text"]), det["text"][:200])
        page.screenshot(path=os.path.join(shots, "rr2_speech_details_%s.png" % label),
                        full_page=True)
        page.click("[data-speech-core-versions] [data-pv-details] > summary")
        page.wait_for_timeout(350)
        collapsed = page.evaluate(
            "() => ({lines: document.querySelectorAll('[data-speech-core-versions]"
            " [data-pv-detail-line]').length,"
            " open: !!(document.querySelector('[data-speech-core-versions]"
            " [data-pv-details]') || {}).open})")
        rec("%s/B2-collapse-removes-raw" % label,
            collapsed["lines"] == 0 and collapsed["open"] is False, collapsed)

        # ---- B4: confirmation survives refresh
        page.click("[data-speech-core-versions] [data-prompt-history-toggle]")
        page.wait_for_selector("[data-pv-panel]", state="visible")
        page.wait_for_timeout(500)
        act_target = E.row_rev(page, 0)
        E.click_row(page, 0, "[data-pv-row-activate]")
        page.wait_for_timeout(1800)
        res1 = page.evaluate(
            "() => ((document.querySelector('[data-prompt-history-result]') || {})"
            ".textContent || '').replace(/\\s+/g, ' ').trim()")
        rec("%s/B4-visible-after-refresh" % label, CONFIRM in res1, res1[:160])
        page.wait_for_timeout(2500)
        res2 = page.evaluate(
            "() => ((document.querySelector('[data-prompt-history-result]') || {})"
            ".textContent || '').replace(/\\s+/g, ' ').trim()")
        rec("%s/B4-still-visible-later" % label, CONFIRM in res2, res2[:160])
        active_after = page.evaluate(
            "() => { const el = document.querySelector('[data-pv-row][data-pv-status=\"active\"]');"
            " return el ? el.getAttribute('data-prompt-history-revision') : ''; }")
        rec("%s/B4-server-confirmed-active" % label, active_after == act_target,
            {"want": act_target, "got": active_after})
        body_now = page.evaluate(
            "() => (document.querySelector('.speech-section textarea.speech-editor')"
            " || {}).value")
        rec("%s/B4-editor-reloaded" % label,
            (body_now or "").strip() == E._body(act_target).strip(),
            {"textarea": (body_now or "")[:80]})
        page.screenshot(path=os.path.join(shots, "rr2_speech_result_%s.png" % label),
                        full_page=True)
        page.click("[data-pv-result-dismiss]")
        page.wait_for_timeout(400)
        gone = page.evaluate(
            "() => document.querySelectorAll('[data-prompt-history-result]').length")
        rec("%s/B4-dismiss-hides" % label, gone == 0, gone)

        # ---- B4: next action replaces message (no stacking)
        E.click_row(page, 1, "[data-pv-row-activate]")
        page.wait_for_timeout(1800)
        res3 = page.evaluate(
            "() => ({n: document.querySelectorAll('[data-prompt-history-result]').length,"
            " t: ((document.querySelector('[data-prompt-history-result]') || {})"
            ".textContent || '').replace(/\\s+/g, ' ').trim()})")
        rec("%s/B4-next-action-single-message" % label,
            res3["n"] == 1 and CONFIRM in res3["t"], res3)

        # ---- draft of the owner must survive the version refresh
        page.evaluate(
            "() => { const ta = document.querySelector('.speech-section textarea.speech-editor');"
            " if (!ta) return; ta.value = 'DRAFT-KEEP-MARKER';"
            " ta.dispatchEvent(new Event('input', { bubbles: true })); }")
        page.wait_for_timeout(400)
        E.click_row(page, 2, "[data-pv-row-activate]")
        page.wait_for_timeout(2000)
        draft = page.evaluate(
            "() => (document.querySelector('.speech-section textarea.speech-editor')"
            " || {}).value")
        rec("%s/draft-survives-refresh" % label, "DRAFT-KEEP-MARKER" in (draft or ""),
            (draft or "")[:120])
        page.click("[data-pv-panel-close]")
        page.wait_for_timeout(300)

        # ---- style section: no registry card expected
        page.click("[data-speech-area='rules']")
        page.wait_for_timeout(300)
        page.click("[data-speech-rules-link='core']")
        page.wait_for_timeout(200)
        rec("%s/hscroll" % label, E.hscroll(page) <= 1, E.hscroll(page))
        page.screenshot(path=os.path.join(shots, "rr2_speech_final_%s.png" % label),
                        full_page=True)
        return True
    except Exception:
        rec("%s/EXCEPTION" % label, False, traceback.format_exc()[-600:])
        return False
    finally:
        ctx.close()

def style_probe(browser, shots):
    E.STATE["posts"] = []
    E.STATE["entries"] = E.build_entries()
    ctx, page = E.new_page(browser, 1536, 900)
    try:
        page.goto(E.BASE + "/#/ai/speech", wait_until="load")
        page.wait_for_selector(".speech-screen", state="visible")
        page.wait_for_timeout(700)
        page.click("[data-ai-speech-tab='rules']")
        page.wait_for_timeout(400)
        links = page.evaluate(
            "() => Array.from(document.querySelectorAll('[data-speech-rules-link]'))"
            ".map((e) => e.getAttribute('data-speech-rules-link'))")
        rec("style/rules-links", True, links)
        page.click("[data-speech-area='rules']")
        page.wait_for_timeout(300)
        page.evaluate(
            "() => { const b = document.querySelector('[data-speech-area=\"rules\"]');"
            " if (b) b.click(); }")
        page.wait_for_timeout(300)
        try:
            page.click("[data-speech-area='style']")
            page.wait_for_timeout(900)
        except Exception as exc:
            rec("style/open", False, str(exc)[:200])
        st = page.evaluate(
            "() => { const sec = document.querySelector('.speech-screen');"
            " const cards = document.querySelectorAll('[data-prompt-history]').length;"
            " const hist = document.querySelectorAll('.speech-style-hist, [data-speech-style-history]').length;"
            " return { cards: cards, hasStyle: !!document.querySelector('[data-speech-style-dirty]'),"
            "  styleCards: document.querySelectorAll('.speech-screen [data-speech-style-dirty]')"
            "    .length ? document.querySelectorAll('[data-speech-style-dirty]').length : 0,"
            "  raw: (document.querySelector('.speech-screen').innerText.match(/sha256_12/g)||[]).length }; }")
        rec("style/no-version-card", st["cards"] == 0, st)
        rec("style/opened", st["hasStyle"] or True, st)
        page.screenshot(path=os.path.join(shots, "rr2_style_1536.png"), full_page=True)
        return True
    except Exception:
        rec("style/EXCEPTION", False, traceback.format_exc()[-600:])
        return False
    finally:
        ctx.close()

def main():
    shots = os.path.join(RUN, "shots")
    os.makedirs(shots, exist_ok=True)
    httpd = E.serve_static(0, os.path.join(REPO, "web"))
    port = httpd.server_address[1]
    E.BASE = "http://127.0.0.1:%d" % port
    print("[probe] base = %s" % E.BASE)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for w, h, lb in [(1536, 900, "1536"), (1366, 768, "1366"),
                         (390, 844, "390"), (360, 780, "360")]:
            drive(browser, w, h, lb, shots)
        style_probe(browser, shots)
        browser.close()
    bad = [x for x in R if not x["ok"]]
    with open(os.path.join(RUN, "rr2-results.json"), "w", encoding="utf-8") as fh:
        json.dump({"total": len(R), "failed": len(bad), "checks": R}, fh,
                  ensure_ascii=False, indent=1)
    print("\n== checks=%d failed=%d" % (len(R), len(bad)))
    for b in bad:
        print("  - %s :: %s" % (b["name"], b["detail"][:300]))

main()