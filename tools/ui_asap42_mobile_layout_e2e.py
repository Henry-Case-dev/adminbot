"""ASAP 4.2 Step 3 (T-4828, §49 «mobile bottom-layout measurements») —
реальная геометрическая проверка закрытой шторки «Ещё» (`<768`) через
Playwright/Chromium на настоящих `web/index.html` / `web/static/*`.

Контракт D5.1 (T-4823):
  * при `moreOpen=false` `.more-sheet`/`.more-backdrop` ОТСУТСТВУЮТ в DOM →
    visible intersection с viewport = **0 px**;
  * закрытая шторка не перехватывает pointer/touch (hit-test в нижней полосе
    не возвращает `.more-sheet`/`.more-backdrop`);
  * open работает (шторка видима и в границах экрана); close → снова 0 px;
  * Quick Access отсутствует в DOM каталога модулей;
  * `.bottom-nav` нормального размера и целиком в видимой области.

Это @Builder browser-evidence, НЕ замена независимой приёмки @Reviewer
(T-4833/T-4838) и не живой Telegram WebView. Без секретов/провайдера/БД.

Запуск: .venv\\Scripts\\python tools\\ui_asap42_mobile_layout_e2e.py
Артефакт: tools/_ui_asap42_step3_layout.json
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui_round1025_matrix as M  # noqa: E402  (server/TMA-стаб/API-стабы)

REPO = M.REPO
PORT = M.PORT + 42
RAW = os.path.join(REPO, "tools", "_ui_asap42_step3_layout.json")

PROBE = r"""
(() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const rect = (sel) => {
    const e = document.querySelector(sel);
    if (!e) return null;
    const r = e.getBoundingClientRect();
    const st = getComputedStyle(e);
    const ix = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
    const iy = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
    return { x: Math.round(r.x), y: Math.round(r.y),
             w: Math.round(r.width), h: Math.round(r.height),
             bottom: Math.round(r.bottom),
             position: st.position, zIndex: st.zIndex,
             intersection: Math.round(ix * iy),
             inViewport: r.bottom <= vh + 1 && r.top >= -1 };
  };
  const txt = (el) => (el && el.textContent ? el.textContent.trim() : '');
  const moreBtn = Array.from(document.querySelectorAll('.bottom-nav-link'))
    .find((b) => /Ещё/.test(txt(b)));
  // hit-test нижней полосы (там, где раньше «торчала» закрытая шторка)
  const hits = [];
  for (const y of [vh - 8, vh - 30, vh - 70, vh - 110]) {
    for (const x of [24, Math.round(vw / 2), vw - 24]) {
      const e = document.elementFromPoint(x, y);
      const overlay = e && e.closest ?
        e.closest('.more-sheet, .more-backdrop') : null;
      hits.push({ x: x, y: y, overlay: !!overlay,
                  tag: e ? (e.tagName + '.' + (e.className || '')
                     .toString().split(' ')[0]).slice(0, 40) : null });
    }
  }
  const quick = document.querySelector(
    '.module-quick-wrap, [data-module-quick], #module-quick');
  const quickText = /Быстрое управление/.test(document.body.innerText || '');
  return {
    innerWidth: vw, innerHeight: vh,
    shell: M_SHELL,
    moreSheet: rect('.more-sheet'),
    moreBackdrop: rect('.more-backdrop'),
    morePresent: !!document.querySelector('.more-sheet'),
    moreBackdropPresent: !!document.querySelector('.more-backdrop'),
    bottomNav: rect('.bottom-nav'),
    bottomNavCount: document.querySelectorAll('.bottom-nav-link').length,
    moreButton: !!moreBtn,
    overlayHits: hits.filter((h) => h.overlay).length,
    overlayHitSample: hits.filter((h) => h.overlay).slice(0, 3),
    quickAccessPresent: !!(quick || quickText),
  };
})()
"""


def _probe(page):
    script = PROBE.replace("M_SHELL", json.dumps(page.evaluate(
        "() => (window.matchMedia('(max-width: 767px)').matches "
        "? 'mobile' : 'wide')")))
    return page.evaluate(script)


def _run():
    from playwright.sync_api import sync_playwright

    os.chdir(REPO)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start();

    result = {"failures": [], "console_errors": [], "probes": {}}
    failures = result["failures"]
    url = "http://127.0.0.1:%d/web/index.html" % PORT

    def _api_handler(route):
        req = route.request
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(req.url)))

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for label, vp, mobile in (("mobile", {"width": 390, "height": 844}, True),
                                      ("desktop", {"width": 1280, "height": 800}, False)):
                ctx = browser.new_context(viewport=vp, is_mobile=mobile,
                                          has_touch=mobile)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", _api_handler)
                page = ctx.new_page()
                page.on("console", lambda m, L=label: result["console_errors"].append(
                    "%s: %s" % (L, m.text[:200]))
                    if m.type == "error" else None)
                page.on("pageerror", lambda e, L=label: result["console_errors"].append(
                    "%s pageerror: %s" % (L, str(e)[:200])))
                page.on("dialog", lambda d: d.accept())
                page.goto(url + "#/modules", wait_until="load")
                page.wait_for_timeout(1800)

                closed = _probe(page)
                result["probes"][label + "_closed"] = closed
                result["probes"][label + "_closed_ready"] = closed["shell"]

                if closed["quickAccessPresent"]:
                    failures.append("%s: Quick Access присутствует в DOM" % label)
                if label == "mobile":
                    if not closed.get("bottomNav"):
                        failures.append("mobile: .bottom-nav не найден")
                    else:
                        bn = closed["bottomNav"]
                        if bn["intersection"] <= 0 or not bn["inViewport"]:
                            failures.append("mobile: bottom-nav вне вьюпорта: %s" % bn)
                        if bn["h"] > 140:
                            failures.append("mobile: bottom-nav высота %d (норма ≤140)"
                                            % bn["h"])
                    if not closed["moreButton"]:
                        failures.append("mobile: кнопка «Ещё» не найдена")
                    # closed contract
                    if closed["morePresent"] or closed["moreBackdropPresent"]:
                        failures.append("mobile: closed more-sheet/backdrop в DOM")
                    if closed["overlayHits"] != 0:
                        failures.append("mobile: closed overlay перехватывает "
                                        "pointer (%d hits): %s"
                                        % (closed["overlayHits"],
                                           closed["overlayHitSample"]))
                    # open works
                    page.click('.bottom-nav-link:has-text("Ещё")')
                    page.wait_for_timeout(700)
                    opened = _probe(page)
                    result["probes"]["mobile_open"] = opened
                    if not opened["morePresent"]:
                        failures.append("mobile: open more-sheet не появился")
                    elif opened["moreSheet"]["intersection"] <= 0:
                        failures.append("mobile: open more-sheet вне вьюпорта")
                    # close → снова unmount/0px
                    page.click(".more-backdrop")
                    page.wait_for_timeout(700)
                    reclosed = _probe(page)
                    result["probes"]["mobile_reclosed"] = reclosed
                    if reclosed["morePresent"] or reclosed["moreBackdropPresent"]:
                        failures.append("mobile: после close шторка осталась в DOM")
                    if reclosed["overlayHits"] != 0:
                        failures.append("mobile: после close overlay перехватывает "
                                        "pointer (%d)" % reclosed["overlayHits"])
                ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    uniq = [e for e in result["console_errors"] if "favicon" not in e]
    if uniq:
        failures.append("console/pageerror: %s" % uniq[:3])
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if failures:
        print("FAILURES: %d" % len(failures))
        for f in failures:
            print(" -", f)
        return 1
    print("ASAP42 STEP3 MOBILE BOTTOM-LAYOUT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
