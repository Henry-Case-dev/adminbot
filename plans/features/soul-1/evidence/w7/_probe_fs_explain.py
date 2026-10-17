"""W7 / SOUL-12.1-12.5: before/after probe — видит ли владелец объяснение.

Харнесс: переиспользует tools/ui_round1025_matrix.py (сервер+API-стабы) и
мок SDK из tools/ui_asap8_w2_fullscreen_e2e.py (route вместо addInitScript).
Ничего в репозитории не пишет: артефакты — в OPENCODE_WORKFLOW_SCRATCH/w7.

Запуск: .venv/Scripts/python.exe <scratch>/w7/probe_fs_explain.py [out.json]
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

REPO = r"C:\Code\Python\adminbot"
sys.path.insert(0, os.path.join(REPO, "tools"))
import ui_round1025_matrix as M          # noqa: E402
import ui_asap8_w2_fullscreen_e2e as FH  # noqa: E402

SCRATCH = os.environ.get("OPENCODE_WORKFLOW_SCRATCH") or os.path.join(REPO, ".scratch")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SCRATCH, "w7", "fs-state.json")
PORT = 8810
BASE = "http://127.0.0.1:%d" % PORT

PROBE = r"""(() => {
  const de = document.documentElement;
  const strip = document.querySelector('[data-fs-diagnostics]');
  const pol = window.__FullscreenPolicy;
  const bodyText = (document.body.innerText || '');
  const keys = ['BotFather', 'Launch Mode', 'Fullscreen', 'Compact', 'На весь экран'];
  const mentions = {};
  keys.forEach((k) => { mentions[k] = bodyText.indexOf(k) >= 0; });
  return {
    btnPresent: !!document.querySelector('.header-fs-btn'),
    hiddenClass: de.classList.contains('fs-hidden'),
    fsReason: de.getAttribute('data-fs-reason'),
    stripPresent: !!strip,
    stripOpen: strip ? strip.open === true : null,
    stripText: strip ? (strip.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 600) : null,
    policyApi: pol ? Object.keys(pol).sort() : null,
    hasExplain: !!(pol && typeof pol.explain === 'function'),
    hasDiagnostics: !!(pol && typeof pol.diagnostics === 'function'),
    explain: (pol && typeof pol.explain === 'function') ? pol.explain() : null,
    diagnostics: (pol && typeof pol.diagnostics === 'function') ? pol.diagnostics() : null,
    stateReasonText: pol ? (pol.state().reasonText === undefined ? null : pol.state().reasonText) : null,
    stateNextStep: pol ? (pol.state().nextStep === undefined ? null : pol.state().nextStep) : null,
    bodyMentions: mentions,
    toasts: Array.from(document.querySelectorAll('.toast-text')).map((t) => t.textContent.trim()),
    hOverflow: de.scrollWidth > window.innerWidth + 1,
    headerH: (() => {
      const h = document.querySelector('header.header-sticky');
      return h ? Math.round(h.getBoundingClientRect().height) : null;
    })(),
    shellFullscreen: (() => {
      const sh = document.querySelector('.app-shell');
      return sh ? sh.classList.contains('fullscreen-mode') : null;
    })(),
  };
})()"""

SCENARIOS = {
    "tdesktop_hidden": dict(
        platform="tdesktop", hasBoolean=True, isFullscreen=False, stableHeight=700,
        viewportHeight=768,
        safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
        contentSafeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0}),
    "tdesktop_launch_fullscreen": dict(
        platform="tdesktop", hasBoolean=True, isFullscreen=True, stableHeight=700,
        viewportHeight=768,
        safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
        contentSafeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0}),
    "android_float": dict(
        platform="android", hasBoolean=True, isFullscreen=False, stableHeight=788,
        viewportHeight=844,
        safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
        contentSafeAreaInset={"top": 36, "bottom": 0, "left": 0, "right": 0}),
}
VIEWPORTS = {"tdesktop_hidden": {"width": 1024, "height": 768},
             "tdesktop_launch_fullscreen": {"width": 1024, "height": 768},
             "android_float": {"width": 390, "height": 844}}


def start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def open_page(browser, name, sdk_js=None, viewport=None):
    viewport = viewport or VIEWPORTS[name]
    sdk_js = sdk_js if sdk_js is not None else FH.mock_sdk_js(SCENARIOS[name])
    ctx = browser.new_context(viewport=viewport, device_scale_factor=2, locale="ru-RU")
    page = ctx.new_page()
    page.route("**/static/vendor/telegram-web-app.js",
               lambda route: route.fulfill(status=200,
                                           content_type="application/javascript",
                                           body=sdk_js))
    page.route("**/api/**", FH._api_handler_factory())
    page.set_viewport_size(viewport)
    page.goto(BASE + "/#/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector("header.header-sticky", state="visible", timeout=25000)
    page.wait_for_timeout(900)
    return ctx, page


def main():
    from playwright.sync_api import sync_playwright
    httpd = start_server()
    print("[w7-fs] server %s" % BASE)
    out = {"base": BASE, "scenarios": {}}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name in SCENARIOS:
            ctx, page = open_page(browser, name)
            rec = page.evaluate(PROBE)
            out["scenarios"][name] = rec
            print("[w7-fs] %-28s btn=%s hidden=%s reason=%s strip=%s explain=%s diag=%s"
                  % (name, rec["btnPresent"], rec["hiddenClass"], rec["fsReason"],
                     rec["stripPresent"], rec["hasExplain"], rec["hasDiagnostics"]))
            print("        toasts=%s mentions=%s"
                  % (rec["toasts"], {k: v for k, v in rec["bodyMentions"].items() if v}))
            ctx.close()
        # stand-alone (без Telegram SDK)
        ctx, page = open_page(browser, "tdesktop_hidden", sdk_js=FH.NO_SDK_JS,
                              viewport={"width": 1280, "height": 800})
        rec = page.evaluate(PROBE)
        out["scenarios"]["no_telegram"] = rec
        print("[w7-fs] %-28s btn=%s hidden=%s reason=%s strip=%s"
              % ("no_telegram", rec["btnPresent"], rec["hiddenClass"], rec["fsReason"],
                 rec["stripPresent"]))
        ctx.close()
        browser.close()
    httpd.shutdown()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("[w7-fs] -> %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
