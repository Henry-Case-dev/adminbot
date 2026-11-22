"""MOD-ACL-UX-01 M4C ACL-hardening S1 — Playwright-приёмка модалки
«Роли» (#/access/admins): non-global — read-only, global — контролы.

Реальные `web/index.html` / `web/app.js` / `web/static/app.css` на локальном
http-сервере; `/api/*` — детерминированные стабы C1-стенда (реальный
param_catalog/module_registry). TMA — `TMA_STUB` из существующего M4A e2e
(локальный стенд, НЕ live TMA).

Проверяется (контракт §5.1/§6.3):
  * non-global: 0 кнопок «Удалить», нет блока add (Telegram ID/select/
    «Назначить»), видима подпись «Только просмотр», список админов цел;
  * global: кнопки/блок add на месте, подписи «Только просмотр» нет;
  * 1440 и 390: без горизонтального overflow; модалка видима.

Запуск:
  py tools/ui_mod_acl_m4c_hardening_admins_e2e.py           # Playwright
  py tools/ui_mod_acl_m4c_hardening_admins_e2e.py --serve   # стенд 8814
Артефакты: MOD_ACL_HARDENING_SHOTS (по умолчанию evidence/m4c/hardening/shots).
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import ui_mod_acl_m4c1_roles_e2e as c1  # noqa: E402

PORT = int(os.environ.get("MOD_ACL_HARDENING_PORT", "8814"))
SHOTS = os.environ.get(
    "MOD_ACL_HARDENING_SHOTS",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4c", "hardening", "shots"))
BASE = "http://127.0.0.1:%d" % PORT
VIEWPORTS = [(1440, 900), (390, 844)]
STATE = {"non_global": False}


def _api_response(url, headers=None):
    c1.MODE["non_global"] = STATE["non_global"]
    return c1._api_response(url, headers)


class _Handler(c1._Handler):
    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0].startswith("/api/"):
            code, payload = _api_response(
                "http://127.0.0.1%s" % self.path,
                {k.lower(): v for k, v in self.headers.items()})
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()


def _serve():
    non_global = os.environ.get("MOD_ACL_HARDENING_NON_GLOBAL", "") == "1"
    STATE["non_global"] = non_global
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    print("[serve] %s (Browser Use stand, non_global=%s), Ctrl+C to stop"
          % (BASE, non_global))
    httpd.serve_forever()


PROBE_JS = r"""
() => {
  const sec = document.querySelector('#sec-admins');
  const qa = (s) => sec ? Array.from(sec.querySelectorAll(s)) : [];
  const visible = (el) => !!(el && el.getClientRects().length
    && getComputedStyle(el).visibility !== 'hidden'
    && getComputedStyle(el).display !== 'none');
  const buttons = qa('button').filter(visible);
  const text = (el) => (el.textContent || '').trim();
  const del = buttons.filter((b) => text(b) === 'Удалить');
  const add = buttons.filter((b) => text(b) === 'Назначить');
  const note = sec ? sec.querySelector('[data-admins-readonly]') : null;
  const rowIds = qa('.font-mono').map(text);
  return {
    vw: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
    modalOpen: !!document.querySelector('.modal-backdrop'),
    sectionVisible: visible(sec),
    inModal: !!(sec && sec.closest('.modal-backdrop')),
    admins: qa('.badge.badge-info').length,
    rowIds: rowIds,
    deleteButtons: del.length,
    addButtons: add.length,
    idInputs: qa('input[placeholder="Telegram ID"]').filter(visible).length,
    roleSelects: qa('select').filter(visible).length,
    readonlyNote: note ? text(note) : null,
    readonlyVisible: visible(note),
    emptyText: qa('.text-gray-500').map(text),
  };
}
"""


def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, name)
    page.screenshot(path=path, full_page=False)
    return path


def _assert(cond, name, detail, failures):
    if not cond:
        failures.append("%s: %s" % (name, detail))


def _open(browser, width, height):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    ctx.add_init_script(c1.base.TMA_STUB)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console:" + m.text)
            if (m.type == "error"
                and "Failed to load resource" not in m.text) else None)
    page.route("**/api/**", lambda route: route.fulfill(
        status=(_api_response(route.request.url)[0]),
        content_type="application/json",
        body=json.dumps(_api_response(route.request.url)[1])))
    page.goto(BASE + "/#/access/admins", wait_until="load")
    page.wait_for_selector(".app-shell", timeout=20000)
    page.wait_for_selector("#sec-admins", timeout=20000)
    page.wait_for_timeout(900)
    return ctx, page, errors


def run_playwright() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    failures = []
    report = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for non_global in (True, False):
                STATE["non_global"] = non_global
                mode = "non-global" if non_global else "global"
                for (vw, vh) in VIEWPORTS:
                    key = "%s-%dx%d" % (mode, vw, vh)
                    ctx, page, errors = _open(browser, vw, vh)
                    try:
                        d = page.evaluate(PROBE_JS)
                        report[key] = d
                        _assert(d["modalOpen"] and d["inModal"], key,
                                "модалка #/access/admins не открыта", failures)
                        _assert(d["sectionVisible"], key,
                                "#sec-admins не видим", failures)
                        _assert(d["admins"] == len(c1.ADMINS), key,
                                "строк админов %s != %s"
                                % (d["admins"], len(c1.ADMINS)), failures)
                        _assert(len(d["rowIds"]) >= len(c1.ADMINS), key,
                                "ID админов не отрисованы: %s" % d["rowIds"],
                                failures)
                        _assert(not d["hScroll"], key,
                                "horizontal overflow %s > %s"
                                % (d["scrollWidth"], vw), failures)
                        if non_global:
                            _assert(d["deleteButtons"] == 0, key,
                                    "non-global видит «Удалить»: %s"
                                    % d["deleteButtons"], failures)
                            _assert(d["addButtons"] == 0
                                    and d["idInputs"] == 0
                                    and d["roleSelects"] == 0, key,
                                    "non-global видит блок назначения: %s"
                                    % d, failures)
                            _assert(d["readonlyVisible"]
                                    and "Только просмотр"
                                    in (d["readonlyNote"] or ""), key,
                                    "нет подписи «Только просмотр»: %r"
                                    % d["readonlyNote"], failures)
                        else:
                            _assert(d["deleteButtons"] == len(c1.ADMINS), key,
                                    "global: «Удалить» %s != %s"
                                    % (d["deleteButtons"], len(c1.ADMINS)),
                                    failures)
                            _assert(d["addButtons"] == 1
                                    and d["idInputs"] == 1
                                    and d["roleSelects"] >= 1, key,
                                    "global: блок назначения неполон: %s"
                                    % d, failures)
                            _assert(not d["readonlyVisible"], key,
                                    "global видит подпись «Только просмотр»",
                                    failures)
                        _assert(not errors, key, "JS-ошибки: %s"
                                % errors[:3], failures)
                        _shot(page, "admins-%s-%dx%d.png" % (mode, vw, vh))
                    finally:
                        ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    out = {
        "ok": not failures,
        "failures": failures,
        "report": report,
        "limitations": [
            "локальный стенд: API-стабы C1 (GET /api/admins, /api/me, "
            "/api/access/me), TMA_STUB; не live TMA",
            "POST-мутации не кликаются: серверная граница доказана "
            "deterministic-тестами (tests/test_mod_acl_ux_m4c_acl_hardening.py)",
        ],
    }
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, "report.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("[hardening-admins] %s: %d failure(s)" % (
        "PASS" if out["ok"] else "FAIL", len(failures)))
    for f in failures:
        print("  -", f)
    print("[hardening-admins] report ->", path)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    if "--serve" in sys.argv:
        _serve()
    else:
        raise SystemExit(run_playwright())
