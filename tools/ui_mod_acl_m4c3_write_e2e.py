"""MOD-ACL-UX-01 M4C C3 — Playwright-приёмка записи/409/audit/reset.

Реальные `web/index.html` / `web/app.js` / `web/static/app.css` на локальном
http-сервере; `/api/*` — детерминированные стабы. Это ЛОКАЛЬНЫЙ СТЕНД, НЕ
live TMA. C1/C2-инструменты не меняются; этот файл их не импортирует как
product-код.

Проверяется:
  * матрица: toggle не пишет; save — PUT с expected_updated_at, per-item
    статус и итог; 409-карточка + reapply; h-scroll 0 на 1440/1280/768/390/320;
  * роль: expected_revision, 409-карточка и запрет save до перечитывания;
  * audit-панель: открытие/список/entity/«Показать ещё»;
  * #/access/local: перекрытия и reset «в наследование» (DELETE);
  * скриншоты 1440/390 в evidence/m4c/c3/shots.

Запуск:
  py tools/ui_mod_acl_m4c3_write_e2e.py
  py tools/ui_mod_acl_m4c3_write_e2e.py --serve   # стенд для Browser Use
"""
import copy
import json
import os
import sys
import threading
import urllib.parse
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import ui_mod_acl_m4_catalog_e2e as base  # noqa: E402
import ui_mod_acl_m4c1_roles_e2e as c1  # noqa: E402

PORT = int(os.environ.get("MOD_ACL_M4C3_PORT", "8813"))
SHOTS = os.environ.get(
    "MOD_ACL_M4C3_SHOTS",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4c", "c3", "shots"))
BASE = "http://127.0.0.1:%d" % PORT
CHECK_VIEWPORTS = [(1440, 900), (1280, 800), (768, 1024),
                   (390, 844), (320, 568)]
SHOT_VIEWPORTS = {(1440, 900), (390, 844)}
CHAT_ID = c1.CHAT_ID
MATRIX_KEY = "limits.summary_hybrid_context_tokens"

ROLES = copy.deepcopy(c1.ROLES)
for _name, _role in ROLES.items():
    _role["revision"] = "rev-" + _name
MATRIX = copy.deepcopy(c1.MATRIX)
MATRIX["items"][MATRIX_KEY]["default"] = False
MATRIX["items"][MATRIX_KEY]["updated_at"] = "2026-11-22T12:00:00+00:00"
AUDIT = [
    {"id": 3, "created_at": "2026-11-22T12:03:00+00:00",
     "changed_by": 5885953495, "entity": "param_global", "op": "update",
     "role_name": None, "telegram_id": None, "key": MATRIX_KEY,
     "before": {"view_roles": ["moderator", "local_admin"],
                "edit_roles": ["local_admin"]},
     "after": {"view_roles": ["local_admin"], "edit_roles": ["local_admin"]}},
    {"id": 2, "created_at": "2026-11-22T12:02:00+00:00",
     "changed_by": 5885953495, "entity": "admin", "op": "create",
     "role_name": None, "telegram_id": 777000111,
     "key": None, "before": None, "after": {"role_name": "moderator"}},
    {"id": 1, "created_at": "2026-11-22T12:01:00+00:00",
     "changed_by": 5885953495, "entity": "role", "op": "update",
     "role_name": "custom_used", "telegram_id": None, "key": None,
     "before": None,
     "after": {"added": {"sections": ["limits"]}}},
]
LOCAL_OVERRIDES = {
    MATRIX_KEY: {"view_roles": ["local_admin"],
                 "edit_roles": ["local_admin"],
                 "updated_at": "2026-11-22T12:00:00+00:00", "legacy": False},
}
STATE = {
    "matrix_puts": 0, "matrix_deletes": 0, "role_posts": 0,
    "audit_gets": 0, "local_deletes": 0,
    "conflict_once": False, "role_conflict": False,
    "mode": {},
}


def _reset_state():
    STATE.update({
        "matrix_puts": 0, "matrix_deletes": 0, "role_posts": 0,
        "audit_gets": 0, "local_deletes": 0,
        "conflict_once": False, "role_conflict": False, "mode": {},
    })


def _api_response(url, method="GET", body=None):
    path = url.split("?")[0]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    mode = STATE["mode"]
    if path.endswith("/api/roles") and method == "GET":
        if mode.get("roles"):
            return mode["roles"], {"detail": "stub roles error"}
        return 200, {"roles": [ROLES[n] for n in sorted(ROLES)]}
    if path.endswith("/api/roles/tree") and method == "GET":
        role = (query.get("role_name") or [""])[0]
        return (200, c1.TREES[role]) if role in c1.TREES \
            else (404, {"detail": "роль не найдена"})
    if path.endswith("/api/roles") and method == "POST":
        STATE["role_posts"] += 1
        if STATE["role_conflict"]:
            STATE["role_conflict"] = False
            return 409, {"detail": {
                "code": "conflict", "reason": "revision_mismatch",
                "current_revision": "rev-custom_used",
                "current": {"permissions": {"sections": ["limits"]},
                            "role_type": None, "is_custom": True}}}
        return 200, {"role_name": "custom_used",
                     "permissions": (body or {}).get("permissions", {}),
                     "is_custom": True, "role_type": None,
                     "revision": "rev-custom_used-2"}
    if path.endswith("/api/access/param_permissions") and method == "GET":
        if mode.get("matrix"):
            return mode["matrix"], {"detail": "stub matrix error"}
        return 200, MATRIX
    if "/api/access/param_permissions/" in path and method == "PUT":
        STATE["matrix_puts"] += 1
        key = urllib.parse.unquote(path.rsplit("/", 1)[-1])
        if STATE["conflict_once"]:
            STATE["conflict_once"] = False
            return 409, {"detail": {
                "code": "conflict", "reason": "revision_mismatch",
                "current_updated_at": "2026-11-22T13:00:00+00:00",
                "current": {"view_roles": ["local_admin"],
                            "edit_roles": ["local_admin"]}}}
        item = MATRIX["items"].get(key, {})
        item["view_roles"] = (body or {}).get("view_roles", [])
        item["edit_roles"] = (body or {}).get("edit_roles", [])
        item["default"] = False
        item["updated_at"] = "2026-11-22T13:%02d:00+00:00" % STATE["matrix_puts"]
        return 200, {"key": key, "view_roles": item["view_roles"],
                     "edit_roles": item["edit_roles"],
                     "updated_at": item["updated_at"]}
    if "/api/access/param_permissions/" in path and method == "DELETE":
        STATE["matrix_deletes"] += 1
        return 200, {"reset": True}
    if path.endswith("/api/access/audit") and method == "GET":
        STATE["audit_gets"] += 1
        if mode.get("audit"):
            return mode["audit"], {"detail": "stub audit error"}
        ent = (query.get("entity") or [""])[0]
        rows = [r for r in AUDIT if not ent or r["entity"] == ent]
        limit = int((query.get("limit") or ["50"])[0])
        return 200, {"scope": "global", "chat_id": None,
                     "items": rows[:limit], "has_more": len(rows) > limit}
    if "/api/access/chats/" in path and "/param_permissions" in path:
        if method == "DELETE":
            STATE["local_deletes"] += 1
            return 200, {"reset": True}
        return 200, {"chat_id": CHAT_ID, "profile_present": True,
                     "items": copy.deepcopy(LOCAL_OVERRIDES)}
    if path.endswith("/api/admins"):
        return 200, {"admins": c1.ADMINS}
    if path.endswith("/api/access/me"):
        return 200, c1.ACCESS_ME
    if path.endswith("/api/access/chats"):
        return 200, c1.ACCESS_CHATS
    if path.endswith("/api/config"):
        return 200, c1.CONFIG
    if path.endswith("/api/me"):
        return 200, base.ME_JSON
    if path.endswith("/api/chat_lore/admins"):
        return 200, [777000111]
    return 200, base._stub_for(path)


def _handler_for(page):
    def route_handler(route):
        req = route.request
        body = None
        try:
            body = req.post_data_json
        except Exception:  # noqa: BLE001
            body = None
        code, payload = _api_response(req.url, req.method, body)
        route.fulfill(status=code, content_type="application/json",
                      body=json.dumps(payload))
    return route_handler


def _open(browser, width, height, url="#/access/roles", chat_id=None):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    ctx.add_init_script(base.TMA_STUB)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())
    page.route("**/api/**", _handler_for(page))
    page.goto(BASE + "/" + url, wait_until="load")
    page.wait_for_selector(".app-shell", timeout=20000)
    page.wait_for_timeout(1200)
    if chat_id is not None:
        page.evaluate("(id) => { window.__adminbotVm.activeChatId = id; }",
                      chat_id)
    return ctx, page, errors


def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, name)
    page.screenshot(path=path, full_page=False)
    return path


class _Handler(base._Handler):
    """Статический стенд + GET /api/* из `_api_response` (Browser Use)."""

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0].startswith("/api/"):
            code, payload = _api_response(
                "http://127.0.0.1%s" % self.path)
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()


def _check(cond, name, detail, failures):
    if not cond:
        failures.append("%s: %s" % (name, detail))


def _open_matrix(page, key=MATRIX_KEY):
    page.wait_for_selector("[data-roles-page]", timeout=20000)
    page.click('[data-roles-tabs] button:nth-child(2)')
    page.wait_for_timeout(400)
    page.fill('[data-roles-matrix-search]', key)
    page.wait_for_timeout(400)
    # раскрыть все видимые группы (в фильтре обычно одна)
    page.evaluate("() => { document.querySelectorAll('.matrix-group')"
                  ".forEach(g => { if (!g.open) g.open = true; }); }")
    page.wait_for_timeout(250)


def _matrix_probe(page):
    return page.evaluate("""() => {
      const q = (s) => document.querySelector(s);
      const qa = (s) => Array.from(document.querySelectorAll(s));
      const rows = qa('[data-roles-matrix] tr').filter(
        r => r.querySelector('input[type=checkbox]'));
      return {
        scrollWidth: document.documentElement.scrollWidth,
        savebar: !!q('[data-matrix-savebar]'),
        draftCount: (q('[data-matrix-draft-count]') || {}).textContent || '',
        saveResult: (q('[data-matrix-save-result]') || {}).textContent || '',
        conflict: !!q('[data-matrix-conflict]'),
        dirty: qa('[data-matrix-dirty]').length,
        status: (q('[data-matrix-item-status]') || {}).textContent || '',
        rows: rows.length,
        putBtn: q('[data-matrix-save]') ? {
          w: q('[data-matrix-save]').getBoundingClientRect().width,
          h: q('[data-matrix-save]').getBoundingClientRect().height,
        } : null,
      };
    }""")


def run_playwright() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), base._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    failures = []
    report = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # ── Layout/dirty: 5 viewport ──────────────────────────────────
            for (vw, vh) in CHECK_VIEWPORTS:
                _reset_state()
                ctx, page, errors = _open(browser, vw, vh)
                key = "%dx%d" % (vw, vh)
                try:
                    _open_matrix(page)
                    d0 = _matrix_probe(page)
                    _check(d0["rows"] >= 1, key, "строка матрицы не найдена",
                           failures)
                    _check(d0["scrollWidth"] <= vw + 1, key,
                           "h-scroll %s > %s" % (d0["scrollWidth"], vw),
                           failures)
                    _check(not d0["savebar"], key,
                           "savebar показан без изменений", failures)
                    page.locator('[data-roles-matrix] input[type=checkbox]:visible').first.click()
                    page.wait_for_timeout(250)
                    d1 = _matrix_probe(page)
                    _check(d1["savebar"] and d1["dirty"] >= 1, key,
                           "draft не отмечен/savebar не появился", failures)
                    _check("Изменения: 1" in d1["draftCount"], key,
                           "счётчик draft: %r" % d1["draftCount"], failures)
                    _check(STATE["matrix_puts"] == 0, key,
                           "toggle сделал PUT", failures)
                    if vw < 768:
                        _check(d1["putBtn"] and d1["putBtn"]["h"] >= 44, key,
                               "save <44 px: %s" % d1["putBtn"], failures)
                    if (vw, vh) in SHOT_VIEWPORTS:
                        _shot(page, "c3-matrix-dirty-%dx%d.png" % (vw, vh))
                    report[key] = d1
                    _check(not errors, key, "JS errors: %s" % errors[:3],
                           failures)
                finally:
                    ctx.close()

            # ── Сценарий 1440: save/409/audit/role/local ─────────────────
            _reset_state()
            ctx, page, errors = _open(browser, 1440, 900)
            try:
                _open_matrix(page)
                page.locator('[data-roles-matrix] input[type=checkbox]:visible').first.click()
                page.wait_for_timeout(200)
                page.click('[data-matrix-save]')
                page.wait_for_timeout(800)
                d = _matrix_probe(page)
                _check(STATE["matrix_puts"] == 1, "save", "PUT count %s"
                       % STATE["matrix_puts"], failures)
                _check("Сохранено 1" in d["saveResult"], "save",
                       "итог: %r" % d["saveResult"], failures)
                _check(d["status"].startswith("Сохранено"), "save",
                       "per-item статус: %r" % d["status"], failures)

                # audit
                page.click('[data-access-audit-open]')
                page.wait_for_timeout(500)
                panel = page.evaluate("""() => {
                  const p = document.querySelector('[data-access-audit-panel]');
                  return { shown: !!p,
                    items: document.querySelectorAll(
                      '[data-access-audit-item]').length,
                    text: p ? p.textContent : '' };
                }""")
                _check(panel["shown"] and panel["items"] >= 2, "audit",
                       "панель/строки: %s" % panel, failures)
                _check("moderator" in panel["text"], "audit",
                       "audit не показывает diff", failures)
                page.select_option('[data-access-audit-entity]', "admin")
                page.wait_for_timeout(400)
                filtered = page.evaluate(
                    "() => document.querySelectorAll"
                    "('[data-access-audit-item]').length")
                _check(filtered == 1, "audit", "entity-фильтр: %s" % filtered,
                       failures)
                _shot(page, "c3-audit-1440.png")

                # 409 matrix + reapply
                page.select_option('[data-access-audit-entity]', "")
                page.wait_for_timeout(200)
                page.fill('[data-roles-matrix-search]', MATRIX_KEY)
                page.wait_for_timeout(300)
                STATE["conflict_once"] = True
                page.locator('[data-roles-matrix] input[type=checkbox]:visible').first.click()
                page.wait_for_timeout(200)
                page.click('[data-matrix-save]')
                page.wait_for_timeout(600)
                conflict = page.evaluate("""() => ({
                  card: !!document.querySelector('[data-matrix-conflict]'),
                  text: (document.querySelector('[data-matrix-conflict]')
                         || {}).textContent || '',
                })""")
                _check(conflict["card"], "409", "карточка конфликта не видна",
                       failures)
                _check("13:00:00" in conflict["text"], "409",
                       "current_updated_at не показан", failures)
                _shot(page, "c3-matrix-conflict-1440.png")
                page.click('[data-matrix-reapply]')
                page.wait_for_timeout(900)
                _check(page.locator('[data-matrix-conflict]').count() == 0,
                       "409", "reapply не убрал карточку", failures)

                # role 409
                page.click('[data-roles-tabs] button:nth-child(1)')
                page.wait_for_timeout(300)
                page.click('.roles-item:nth-child(2)')
                page.wait_for_timeout(500)
                page.fill('[data-roles-search]', "search_max_symbols")
                page.wait_for_timeout(200)
                page.click('[data-roles-pane="rights"] '
                           '.roles-tree__node input[type=checkbox]')
                page.wait_for_timeout(200)
                STATE["role_conflict"] = True
                page.click('[data-roles-save]')
                page.wait_for_timeout(600)
                role_conflict = page.evaluate("""() => ({
                  card: !!document.querySelector('[data-roles-conflict]'),
                  text: (document.querySelector('[data-roles-conflict]')
                         || {}).textContent || '',
                  saveDisabled: (document.querySelector('[data-roles-save]')
                                 || {}).disabled,
                })""")
                _check(role_conflict["card"], "role409",
                       "карточка роли не видна", failures)
                _check(role_conflict["saveDisabled"] is True, "role409",
                       "save не заблокирован", failures)
                _shot(page, "c3-role-conflict-1440.png")
                page.click('[data-roles-conflict-reload]')
                page.wait_for_timeout(700)
                _check(page.locator('[data-roles-conflict]').count() == 0,
                       "role409", "reload не убрал карточку", failures)

                # local overrides reset
                page.evaluate(
                    "(id) => { window.__adminbotVm.activeChatId = id;"
                    " window.__adminbotVm.navigateTo('#/access/local'); }",
                    CHAT_ID)
                page.wait_for_timeout(1200)
                local = page.evaluate("""() => {
                  const d = document.querySelector(
                    '[data-local-param-overrides]');
                  if (d && !d.open) d.open = true;
                  return { details: !!d,
                    rows: document.querySelectorAll(
                      '[data-local-override]').length };
                }""")
                _check(local["details"] and local["rows"] >= 1, "local",
                       "блок перекрытий: %s" % local, failures)
                page.click('[data-local-override-reset]')
                page.wait_for_timeout(700)
                local2 = page.evaluate("""() => ({
                  rows: document.querySelectorAll(
                    '[data-local-override]').length,
                  text: (document.querySelector(
                    '[data-local-param-overrides]') || {}).textContent || '',
                })""")
                _check(STATE["local_deletes"] == 1, "local",
                       "DELETE count %s" % STATE["local_deletes"], failures)
                _check(local2["rows"] == 0, "local",
                       "строка не исчезла после reset", failures)
                _shot(page, "c3-local-reset-1440.png")
                report["scenario1440"] = {
                    "puts": STATE["matrix_puts"],
                    "role_posts": STATE["role_posts"],
                    "audit_gets": STATE["audit_gets"],
                    "local_deletes": STATE["local_deletes"],
                }
                _check(not errors, "scenario1440", "JS errors: %s"
                       % errors[:3], failures)
            finally:
                ctx.close()

            # ── 403/503 карточки (без выдуманной пустой матрицы) ─────────
            for status in (403, 503):
                _reset_state()
                STATE["mode"]["matrix"] = status
                ctx, page, errors = _open(browser, 1440, 900)
                try:
                    page.wait_for_selector("[data-roles-page]", timeout=20000)
                    page.click('[data-roles-tabs] button:nth-child(2)')
                    page.wait_for_timeout(600)
                    d = page.evaluate("""() => ({
                      err: !!document.querySelector(
                        '[data-roles-matrix-error]'),
                      forbidden: !!document.querySelector(
                        '[data-roles-matrix-forbidden]'),
                      text: (document.querySelector(
                        '[data-roles-pane="matrix"]') || {}).textContent || '',
                    })""")
                    _check(d["err"] or d["forbidden"], "matrix%d" % status,
                           "нет карточки ошибки", failures)
                    _check("622" not in d["text"], "matrix%d" % status,
                           "ошибка выдана за матрицу 622", failures)
                finally:
                    ctx.close()

            # ── Mobile 390: local modal без h-scroll ────────────────────
            _reset_state()
            ctx, page, errors = _open(browser, 390, 844,
                                      url="#/access/roles")
            try:
                page.evaluate(
                    "(id) => { window.__adminbotVm.activeChatId = id;"
                    " window.__adminbotVm.navigateTo('#/access/local'); }",
                    CHAT_ID)
                page.wait_for_timeout(1000)
                sw = page.evaluate(
                    "() => document.documentElement.scrollWidth")
                _check(sw <= 391, "local390", "h-scroll %s" % sw, failures)
                _shot(page, "c3-local-390.png")
            finally:
                ctx.close()
            browser.close()
    finally:
        httpd.shutdown()
    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        for f in failures:
            print("FAIL: " + f)
        return 1
    print("MOD-ACL-UX-M4C3-E2E-OK")
    return 0


def _serve():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    print("[serve] %s (Browser Use stand), Ctrl+C to stop" % BASE)
    httpd.serve_forever()


if __name__ == "__main__":
    if "--serve" in sys.argv:
        _serve()
    else:
        raise SystemExit(run_playwright())
