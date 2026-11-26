"""MOD-ACL-UX-01 M1-C — UI-состояния доступа и утечки payload в DOM/консоль.

Реальный `web/index.html` + `web/app.js` на локальном http-сервере; `/api/*`
отвечает стаб (без прод-бэкенда, без сети, без продового initData). Telegram
стубируется существующим `TMA_STUB` из `tools/ui_round1025_matrix.py`
(локальный тестовый initData, не production).

Проверяется то, чего не видит unit-тест — ОТРИСОВАННЫЙ DOM и консоль:

* MAC-S4-171: 401 «missing init data» и 401 «invalid init data» дают РАЗНЫЕ
  видимые баннеры; 403/404/503 показывают свою подпись и не выглядят
  проблемой сессии;
* MAC-S4-172: посаженный литерал, реально присутствующий в теле ответа
  (положительный контроль по сырому телу), НЕ попадает ни в текст/HTML DOM,
  ни в сообщения консоли; контроль чувствительности — известные поля
  (`code`/`message`) видны пользователю, т.е. проверка отсутствия не пустая.

Запуск:
  .venv/Scripts/python.exe tools/ui_mod_acl_m1c_e2e.py
  .venv/Scripts/python.exe tools/ui_mod_acl_m1c_e2e.py --root <checkout>  # RED на базе
Артефакты: --out DIR (JSON + скриншоты 1440 и 390). Код возврата 1 при отличии.
Строка успеха: MOD-ACL-M1C-E2E-OK
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import ui_round1025_matrix as M  # noqa: E402  (TMA_STUB/API_STUBS/_stub_for)

PLANT = "M1C-PLANT-SECRET-7f3a91"     # не sk-/Bearer/URI — иначе маскируется
BENIGN = "M1C-BENIGN-MARKER-2c5d"
VIEWPORTS = [(1440, 900), (390, 844)]


class Handler(SimpleHTTPRequestHandler):
    """Статика из выбранного checkout (`--root`), без обращения к сети."""

    root = REPO

    def translate_path(self, path):  # noqa: N802
        p = path.split("?")[0]
        if p.startswith("/static/"):
            rel = "web/static/" + p[len("/static/"):]
        elif p in ("/", "", "/index.html"):
            rel = "web/index.html"
        else:
            rel = p.lstrip("/")
        return os.path.join(self.root, rel.replace("/", os.sep))

    def log_message(self, *args):  # тишина
        pass


def start_server(root: str, port: int) -> ThreadingHTTPServer:
    Handler.root = root
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _json(status: int, payload) -> tuple[int, str, dict]:
    return status, json.dumps(payload, ensure_ascii=False), {"Content-Type": "application/json"}


# Сценарии: что отвечает конкретный путь вместо обычного стаба.
SCENARIOS = {
    "auth_missing": {
        "url": "#/",
        "routes": {"/api/me": (401, {"detail": "missing init data"})},
        "must_show": ["нет данных Telegram (initData)"],
        "must_not_show": ["не принял подпись входа"],
    },
    "auth_invalid": {
        "url": "#/",
        "routes": {"/api/me": (401, {"detail": "invalid init data"})},
        "must_show": ["не принял подпись входа"],
        "must_not_show": ["нет данных Telegram (initData)"],
    },
    "access_403": {
        "url": "#/access/roles",
        "roles_page": True,
        "routes": {"/api/roles": (403, {"detail": "permission denied"})},
        "must_show": ["Нет доступа"],
        "must_not_show": ["Сессия устарела"],
    },
    "access_404": {
        "url": "#/access/roles",
        "roles_page": True,
        "routes": {"/api/roles": (404, {"detail": "Not Found"})},
        "must_show": ["Не найдено"],
        "must_not_show": ["Сессия устарела", "Нет доступа"],
    },
    "access_503": {
        "url": "#/access/roles",
        "roles_page": True,
        "routes": {"/api/roles": (503, {"detail": "PostgreSQL недоступен (R6)"})},
        "must_show": ["Сервис временно недоступен"],
        "must_not_show": ["Сессия устарела", "Нет доступа"],
    },
    # MAC-S4-172: неизвестное поле detail с посаженным литералом.
    "audit_secret_detail": {
        "url": "#/access/roles",
        "roles_page": True,
        "matrix_tab": True,
        "routes": {"/api/access/audit": (503, {"detail": {"note": PLANT}})},
        "click": "[data-access-audit-open]",
        "wait": "[data-access-audit-error]",
        "forbid_text": [PLANT],
        "must_show": ["Сервис временно недоступен"],
    },
    # Контроль чувствительности: известные поля НЕ маскируются.
    "audit_known_fields": {
        "url": "#/access/roles",
        "roles_page": True,
        "matrix_tab": True,
        "routes": {"/api/access/audit": (503, {"detail": {
            "code": "pg_down", "message": BENIGN}})},
        "click": "[data-access-audit-open]",
        "wait": "[data-access-audit-error]",
        "must_show": [BENIGN, "pg_down"],
    },
}


BASE_ROUTES = {
    # Пустой список ролей: страница ролей рисует свои состояния (403/404/503),
    # а не выбирает роль и не тянет редактор прав — тест не зависит от формы
    # дерева прав роли.
    "/api/roles": (200, {"roles": []}),
}


def _route_factory(routes: dict, seen: list):
    def _route(route):
        req = route.request
        path = "/" + req.url.split("/", 3)[3] if req.url.count("/") >= 3 else "/"
        path = path.split("?")[0]
        if not path.startswith("/api/"):
            route.continue_()
            return
        effective = dict(BASE_ROUTES)
        effective.update(routes)
        if path in effective:
            status, body = effective[path]
            seen.append({"path": path, "status": status, "raw": body})
            route.fulfill(status=status, content_type="application/json",
                          body=json.dumps(body, ensure_ascii=False))
            return
        payload = M._stub_for(req.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload, ensure_ascii=False))
    return _route


def run(root: str, out_dir: str) -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    port = 8857
    httpd = start_server(root, port)
    base_url = "http://127.0.0.1:%d/web/index.html" % port
    result = {"root": root, "plant": PLANT, "benign": BENIGN,
              "viewports": {}, "failures": [], "console": []}

    def fail(key, msg):
        result["failures"].append({"scenario": key, "msg": msg})

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for (w, h) in VIEWPORTS:
                vp = "%dx%d" % (w, h)
                result["viewports"][vp] = {}
                for key, sc in SCENARIOS.items():
                    ctx = browser.new_context(viewport={"width": w, "height": h})
                    ctx.add_init_script(M.TMA_STUB)
                    seen: list = []
                    ctx.route("**/api/**", _route_factory(sc["routes"], seen))
                    page = ctx.new_page()
                    console_msgs: list = []
                    page.on("console",
                            lambda m, b=console_msgs: b.append(
                                "%s: %s" % (m.type, m.text)))
                    page.on("pageerror",
                            lambda e, b=console_msgs: b.append(
                                "pageerror: %s" % str(e)[:200]))
                    page.goto(base_url, wait_until="load")
                    try:
                        page.wait_for_selector(".app-shell", timeout=8000)
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(900)
                    # Навигация как у пользователя: hash ставится после boot
                    # (deep-link при первой загрузке в desktop-оболочке
                    # съедался стартовым маршрутом).
                    if sc["url"] not in ("", "#/"):
                        page.evaluate(
                            "h => { window.location.hash = h; }", sc["url"])
                        if sc.get("roles_page"):
                            try:
                                page.wait_for_selector(".roles-page",
                                                       timeout=6000)
                            except Exception as exc:  # noqa: BLE001
                                fail(key, vp + " страница ролей не открылась: "
                                     + str(exc)[:120])
                        page.wait_for_timeout(600)
                    if sc.get("matrix_tab"):
                        try:
                            page.click('button.roles-tab:has-text('
                                       '"Доступ к параметрам")', timeout=5000)
                        except Exception as exc:  # noqa: BLE001
                            fail(key, vp + " вкладка матрицы: " + str(exc)[:120])
                        page.wait_for_timeout(300)
                    if sc.get("click"):
                        try:
                            page.click(sc["click"], timeout=5000)
                        except Exception as exc:  # noqa: BLE001
                            fail(key, vp + " клик " + sc["click"] + ": "
                                 + str(exc)[:120])
                    if sc.get("wait"):
                        try:
                            page.wait_for_selector(sc["wait"], timeout=5000)
                        except Exception as exc:  # noqa: BLE001
                            fail(key, vp + " не появился " + sc["wait"] + ": "
                                 + str(exc)[:120])
                    page.wait_for_timeout(400)

                    text = page.inner_text("body")
                    html = page.content()
                    shot = os.path.join(out_dir, key + "-" + vp + ".png")
                    page.screenshot(path=shot, full_page=False)
                    row = {"text_len": len(text), "shot": os.path.basename(shot),
                           "console_error_count": sum(
                               1 for m in console_msgs
                               if m.startswith(("error", "pageerror"))),
                           "seen": seen}
                    result["viewports"][vp][key] = row

                    for needle in sc.get("must_show", []):
                        if needle not in text:
                            fail(key, vp + " не показан текст "
                                 + json.dumps(needle, ensure_ascii=False)
                                 + " | text=" + json.dumps(text[:400],
                                                            ensure_ascii=False))
                    for needle in sc.get("must_not_show", []):
                        if needle in text:
                            fail(key, vp + " показан чужой текст "
                                 + json.dumps(needle, ensure_ascii=False))
                    # Положительный контроль: литерал есть в сыром теле ответа.
                    if sc.get("forbid_text"):
                        if not seen or not any(
                                PLANT in json.dumps(s["raw"], ensure_ascii=False)
                                for s in seen):
                            fail(key, vp + " положительный контроль: литерала "
                                 "нет в отданном теле — проверка ниже пустая")
                        for needle in sc.get("forbid_text", []):
                            if needle in text:
                                fail(key, vp + " ЛИТЕРАЛ В DOM: "
                                     + json.dumps(needle))
                            if needle in html:
                                fail(key, vp + " ЛИТЕРАЛ В HTML: "
                                     + json.dumps(needle))
                            hits = [m for m in console_msgs if needle in m]
                            if hits:
                                fail(key, vp + " ЛИТЕРАЛ В КОНСОЛИ: "
                                     + hits[0][:160])
                    result["console"].append(
                        {"viewport": vp, "scenario": key,
                         "messages": console_msgs[-12:]})
                    ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    with open(os.path.join(out_dir, "m1c-e2e.json"), "w",
              encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    total = len(VIEWPORTS) * len(SCENARIOS)
    if result["failures"]:
        print("MOD-ACL-M1C-E2E-FAILED (%d) из %d сценариев"
              % (len(result["failures"]), total))
        for f in result["failures"]:
            print(" - %s | %s" % (f["scenario"], f["msg"]))
        return 1
    print("MOD-ACL-M1C-E2E-OK (%d сценариев × %d вьюпорта, нарушений нет)"
          % (len(SCENARIOS), len(VIEWPORTS)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=REPO,
                    help="checkout, чьи web/ отдаются (для RED на базе)")
    ap.add_argument("--out", default=os.path.join(HERE, "_ui_m1c_out"))
    args = ap.parse_args()
    return run(os.path.abspath(args.root), os.path.abspath(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
