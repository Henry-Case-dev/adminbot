"""MOD-ACL-UX-01 M4C C1 — Playwright-приёмка страницы «Роли и права».

Реальные `web/index.html` / `web/app.js` / `web/static/app.css` на локальном
http-сервере; `/api/*` — детерминированные стабы (реальный param_catalog:
622 параметра, 121 группа; реальный module_registry: владельцы групп).
TMA — `TMA_STUB` из существующего M4A e2e (локальный стенд, НЕ live TMA).

Проверяется (контракт §7/§8):
  * #/access/roles — самостоятельная страница, не modal; роли 220–280 px;
    один основной scroll, h-scroll 0;
  * три зоны: права роли / доступ к параметрам / фактические гейты;
  * дерево Раздел→Модуль→Группа→Параметр; владельцы из boot-DTO;
  * поиск RU+key/group/module: 0 сетевых запросов на символ;
  * role switch — ровно один GET /api/roles/tree;
  * 401/403/404/503 разными карточками; 503 матрицы без дефолтной матрицы;
  * mobile: switcher/⋯, тач-цели ≥44, без h-overflow; группа одна открыта;
  * viewports 1920/1440/1280/768/390/360/320; скриншоты 1440/1920/390/360.

Запуск:
  py tools/ui_mod_acl_m4c1_roles_e2e.py            # Playwright-прогон
  py tools/ui_mod_acl_m4c1_roles_e2e.py --serve    # статический стенд для
                                                   # Browser Use (порт 8811)
Артефакты: MOD_ACL_M4C1_SHOTS (по умолчанию evidence/m4c/c1/shots).
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

PORT = int(os.environ.get("MOD_ACL_M4C1_PORT", "8811"))
SHOTS = os.environ.get(
    "MOD_ACL_M4C1_SHOTS",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4c", "c1", "shots"))
BASE = "http://127.0.0.1:%d" % PORT
CHECK_VIEWPORTS = [(1920, 1080), (1440, 900), (1280, 800), (768, 1024),
                   (390, 844), (360, 640), (320, 568)]
SHOT_VIEWPORTS = {(1440, 900), (1920, 1080), (390, 844), (360, 640)}

CHAT_ID = base.CHAT_ID
ROLES = {
    "admin": {"role_name": "admin", "is_custom": False,
              "permissions": {"wildcard": True}},
    "moderator": {"role_name": "moderator", "is_custom": False,
                  "permissions": {"sections": ["limits"],
                                  "actions": ["control.restart", "control.stop",
                                              "control.start"]}},
    "user": {"role_name": "user", "is_custom": False, "permissions": {}},
    "local_admin": {"role_name": "local_admin", "is_custom": False,
                    "permissions": {"sections": ["limits", "flags", "reactions",
                                                 "content", "chat_lore"],
                                    "actions": []}},
    # F02 fixture: custom-роль, назначенная одному админу (DELETE → 409).
    "custom_used": {"role_name": "custom_used", "is_custom": True,
                    "permissions": {"sections": [], "actions": []}},
}
ADMINS = [
    {"telegram_id": 5885953495, "role_name": "admin", "display_name": "Audit",
     "added_by": None, "created_at": "2026-11-17T10:00:00+00:00"},
    {"telegram_id": 1313107079, "role_name": "moderator",
     "display_name": "Mod", "added_by": 5885953495,
     "created_at": "2026-11-17T10:00:01+00:00"},
    {"telegram_id": 777000111, "role_name": "moderator", "display_name": None,
     "added_by": 5885953495, "created_at": "2026-11-17T10:00:02+00:00"},
    {"telegram_id": 777000222, "role_name": "custom_used", "display_name": None,
     "added_by": 5885953495, "created_at": "2026-11-17T10:00:03+00:00"},
]
ACCESS_ME = {
    "role_global": "global_admin", "role_chat": None, "is_global_admin": True,
    "is_local_admin": False, "rank": 4,
    "chats": [{"chat_id": CHAT_ID, "role": "global_admin"}],
}
ACCESS_ME_NON_GLOBAL = {
    "role_global": "local_admin", "role_chat": None, "is_global_admin": False,
    "is_local_admin": False, "rank": 3,
    "chats": [{"chat_id": CHAT_ID, "role": "local_admin"}],
}
ME_NON_GLOBAL = dict(base.ME_JSON, role_name="local_admin",
                     is_global_admin=False,
                     permissions={"sections": ["access"]})
ACCESS_CHATS = [{"chat_id": CHAT_ID, "title": base.CHAT_TITLE,
                 "photo_file_id": None, "is_active": True,
                 "access": "global_admin"}]

MODE = {"roles": 0, "tree": 0, "matrix": 0, "non_global": False}
COUNTS = {"roles": 0, "tree": 0, "matrix": 0}


def _matrix_payload():
    from services import access as access_srv
    from services.param_catalog import (
        CONFIG_TAB_TITLES, GROUPS, NAV_ORDER, NAV_TITLES, REGISTRY,
        group_tab, tab_nav,
    )
    groups_by_id = {g.id: (g.title_ru, g.category, g.order) for g in GROUPS}
    items = {}
    for key in sorted(REGISTRY):
        spec = REGISTRY[key]
        if spec.category is None:
            continue
        matrix = access_srv.effective_matrix(spec.pg_key, None)
        matrix["default"] = True
        gtitle, _gcat, gorder = groups_by_id.get(
            spec.group, (spec.group, spec.category, 999))
        tab = group_tab(spec.group)
        nav = tab_nav(tab)
        matrix.update({
            "category": spec.category, "group": spec.group,
            "group_title": gtitle, "group_order": gorder,
            "tab": tab, "tab_title": CONFIG_TAB_TITLES.get(tab) if tab else None,
            "nav": nav,
            "nav_title": NAV_TITLES.get(nav) if nav else None,
            "nav_order": NAV_ORDER.index(nav) if nav in NAV_ORDER else 999,
            "title": spec.title_ru, "secret": spec.secret,
        })
        items[spec.pg_key] = matrix
    return {"items": items}


MATRIX = _matrix_payload()


def _role_tree(role_name):
    from services.param_catalog import (
        CATEGORIES, CATEGORY_KEYS, by_category,
    )
    from services.permissions import (
        ACTIONS_TREE, Permissions, requires_permission as match_permission,
    )
    perms = Permissions.from_dict(ROLES[role_name]["permissions"])
    titles = {"prompts": "Промпты", "models": "Модели и провайдеры",
              "keys": "API-ключи", "limits": "Лимиты и кулдауны",
              "flags": "Флаги модулей", "reactions": "Реакции и персоны",
              "content": "Контент", "memory": "Память",
              "temporal": "Временной фактчек"}
    sections = []
    for category in CATEGORIES:
        specs = by_category(category)
        if not specs:
            continue
        params, keys = [], []
        for spec in sorted(specs, key=lambda s: s.pg_key):
            node = {"key": spec.pg_key, "title": spec.title_ru,
                    "type": spec.type, "secret": spec.secret,
                    "checked": match_permission(perms, f"param.{spec.pg_key}")}
            if category == CATEGORY_KEYS:
                node["checked"] = match_permission(perms, f"key.{spec.pg_key}")
                keys.append(node)
            else:
                params.append(node)
        sections.append({
            "id": category, "title": titles.get(category, category),
            "checked": match_permission(perms, f"section.{category}"),
            "params": params, "keys": keys,
        })
    sections.append({"id": "access", "title": "Доступы",
                     "checked": match_permission(perms, "section.access"),
                     "params": [], "keys": []})
    actions = [{"id": a["id"], "title": a["title"],
                "checked": match_permission(perms, f"action.{a['id']}")}
               for a in ACTIONS_TREE]
    return {"sections": sections, "actions": actions}


TREES = {name: _role_tree(name) for name in ROLES}
CONFIG = copy.deepcopy(base.CONFIG_GLOBAL)
CONFIG["modules"] = base._registry_payload(False)


def _reset_counts():
    for key in COUNTS:
        COUNTS[key] = 0


def _api_response(url, headers=None):
    """(status, payload) для /api/*; MODE — только для Playwright-сценариев."""
    headers = headers or {}
    path = url.split("?")[0]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    def status_for(key):
        return MODE.get(key) or 200

    if path.endswith("/api/config"):
        return 200, CONFIG
    if path.endswith("/api/me"):
        return 200, (ME_NON_GLOBAL if MODE.get("non_global") else base.ME_JSON)
    if path.endswith("/api/access/me"):
        return 200, (ACCESS_ME_NON_GLOBAL if MODE.get("non_global")
                     else ACCESS_ME)
    if path.endswith("/api/access/chats"):
        return 200, ACCESS_CHATS
    if path.endswith("/api/admins"):
        code = status_for("admins")
        return (code, {"detail": "stub denied"}) if code != 200 else \
            (200, {"admins": ADMINS})
    if path.endswith("/api/roles/tree"):
        code = status_for("tree")
        if code != 200:
            return code, {"detail": "stub tree error"}
        role = (query.get("role_name") or [""])[0]
        if role not in TREES:
            return 404, {"detail": "роль не найдена: %s" % role}
        return 200, TREES[role]
    if path.endswith("/api/roles"):
        code = status_for("roles")
        if code != 200:
            return code, {"detail": "stub roles error"}
        return 200, {"roles": [ROLES[n] for n in sorted(ROLES)]}
    if path.endswith("/api/access/param_permissions"):
        code = status_for("matrix")
        if code != 200:
            return code, {"detail": "stub matrix error"}
        return 200, MATRIX
    return 200, base._stub_for(path)


def _count(url):
    path = url.split("?")[0]
    if path.endswith("/api/access/param_permissions"):
        COUNTS["matrix"] += 1
    elif path.endswith("/api/roles/tree"):
        COUNTS["tree"] += 1
    elif path.endswith("/api/roles"):
        COUNTS["roles"] += 1


class _Handler(base._Handler):
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
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    print("[serve] %s (Browser Use stand), Ctrl+C to stop" % BASE)
    httpd.serve_forever()


PROBE_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {x: +r.x.toFixed(1), y: +r.y.toFixed(1),
            w: +r.width.toFixed(1), h: +r.height.toFixed(1),
            left: +r.left.toFixed(1), right: +r.right.toFixed(1),
            display: cs.display, visibility: cs.visibility};
  };
  const isVisible = (el) => !!(el && el.getClientRects().length
    && getComputedStyle(el).visibility !== 'hidden');
  const pageEl = q('[data-roles-page]');
  const main = q('[data-roles-main]');
  const aside = q('[data-roles-aside]');
  const scrollers = pageEl ? qa.call(document, '[data-roles-page] *')
    .filter((el) => {
      const cs = getComputedStyle(el);
      return (cs.overflowY === 'auto' || cs.overflowY === 'scroll')
        && el.scrollHeight > el.clientHeight + 1;
    }).map((el) => ({cls: el.className || el.tagName,
                     sh: el.scrollHeight, ch: el.clientHeight})) : [];
  const visibleNodes = qa('[data-roles-tree] .roles-tree__node')
    .filter(isVisible).length;
  const matrixRows = qa('[data-roles-matrix] .matrix-table tbody tr')
    .filter(isVisible).length;
  return {
    vw: window.innerWidth, vh: window.innerHeight,
    scrollWidth: document.documentElement.scrollWidth,
    hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
    page: rect(pageEl), main: rect(main), aside: rect(aside),
    pageInModal: !!(pageEl && pageEl.closest('.modal-backdrop')),
    pageInModalCard: !!(pageEl && pageEl.closest('.modal-card')),
    scrollers: scrollers,
    roles: qa('.roles-item').length,
    roleOptions: qa('#roles-mobile-select option').length,
    sections: qa('[data-roles-tree] .roles-tree__section').length,
    visibleNodes: visibleNodes,
    roleSearch: !!q('[data-roles-search]'),
    matrixGroups: qa('[data-roles-matrix] .matrix-group').length,
    matrixRowsVisible: matrixRows,
    matrixGroupOpen: qa('[data-roles-matrix] .matrix-group[open]').length,
    matrixEffective: qa('[data-roles-matrix] [data-matrix-effective]').length,
    matrixCountText: (q('[data-roles-pane="matrix"] p') || {}).textContent || '',
    rolesCount: q('[data-roles-count]')
      ? q('[data-roles-count]').textContent.trim() : null,
    matrixCount: q('[data-roles-matrix-count]')
      ? q('[data-roles-matrix-count]').textContent.trim() : null,
    deleteDisabled: (() => {
      const el = q('.roles-pane__actions [data-roles-delete]');
      return el ? el.disabled : null;
    })(),
    renameDisabled: (() => {
      const el = q('.roles-pane__actions [data-roles-rename]');
      return el ? el.disabled : null;
    })(),
    usageNote: (q('[data-roles-usage-note]') || {}).textContent || '',
    ownersFallback: qa('.roles-tree__owner').filter(
      (el) => el.textContent.indexOf('Общее / инфраструктура') >= 0).length,
    ownerLabels: qa('.roles-tree__owner').length,
    tabHeights: qa('.roles-tab').map((el) => rect(el).h),
    actionBtn: rect(q('[data-roles-actions]')),
    mobileSwitch: rect(q('[data-roles-mobile-switch]')),
    mobileSelect: rect(q('#roles-mobile-select')),
    backBtn: rect(q('[data-roles-back]')),
    rolesError: (q('[data-roles-error]') || {}).getAttribute
      ? q('[data-roles-error]').getAttribute('data-roles-error') : null,
    treeError: (q('[data-roles-tree-error]') || {}).getAttribute
      ? q('[data-roles-tree-error]').getAttribute('data-roles-tree-error') : null,
    matrixError: (q('[data-roles-matrix-error]') || {}).getAttribute
      ? q('[data-roles-matrix-error]').getAttribute('data-roles-matrix-error') : null,
    emptyRoles: !!q('[data-roles-empty]'),
    matrixBodyVisible: qa('[data-roles-matrix] .matrix-table').some(isVisible),
    gatesPane: !!q('[data-roles-pane="gates"]'),
    matrixPane: !!q('[data-roles-pane="matrix"]'),
    rightsPane: !!q('[data-roles-pane="rights"]'),
    title: (q('#acc-roles-title') || {}).textContent || '',
    titleCount: qa('#acc-roles-title').length,
  };
}
"""


def _assert(cond, name, detail, failures):
    if not cond:
        failures.append("%s: %s" % (name, detail))


def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, name)
    page.screenshot(path=path, full_page=False)
    return path


def _open(browser, width, height):
    from playwright.sync_api import sync_playwright  # noqa: F401
    ctx = browser.new_context(viewport={"width": width, "height": height})
    ctx.add_init_script(base.TMA_STUB)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console:" + m.text)
            if (m.type == "error"
                and "Failed to load resource" not in m.text) else None)
    page.route("**/api/**", lambda route: _route(route))
    page.goto(BASE + "/#/access/roles", wait_until="load")
    page.wait_for_selector(".app-shell", timeout=20000)
    page.wait_for_selector("[data-roles-page]", timeout=20000)
    page.wait_for_timeout(1200)
    return ctx, page, errors


def _route(route):
    _count(route.request.url)
    code, payload = _api_response(route.request.url,
                                  dict(route.request.headers))
    route.fulfill(status=code, content_type="application/json",
                  body=json.dumps(payload))


def _main_checks(page, vw, vh, failures, report):
    key = "%dx%d" % (vw, vh)
    d = page.evaluate(PROBE_JS)
    report[key] = d
    _assert(d["page"] is not None, key, "страница ролей не отрисована", failures)
    _assert(not d["pageInModal"] and not d["pageInModalCard"], key,
            "роли всё ещё в modal", failures)
    _assert(d["scrollWidth"] <= vw + 1, key,
            "horizontal overflow %s > %s" % (d["scrollWidth"], vw), failures)
    _assert(d["titleCount"] == 1 and "Роли и права" in d["title"], key,
            "один заголовок страницы", failures)
    _assert(d["roles"] == len(ROLES), key,
            "ролей %s, ожидалось %s" % (d["roles"], len(ROLES)), failures)
    _assert(d["sections"] >= 10, key,
            "секции прав не отрисованы (%s)" % d["sections"], failures)
    _assert(d["rightsPane"] and d["matrixPane"] and d["gatesPane"], key,
            "три зоны не отрисованы", failures)
    _assert(len(d["scrollers"]) == 0, key,
            "вложенный вертикальный скролл: %s" % d["scrollers"], failures)
    if vw >= 768:
        _assert(220 <= d["aside"]["w"] <= 280, key,
                "колонка ролей %s px вне 220–280" % d["aside"]["w"], failures)
        _assert(d["aside"]["display"] != "none", key,
                "desktop-список ролей скрыт", failures)
    else:
        _assert(d["aside"]["display"] == "none", key,
                "mobile: список ролей не заменён switcher", failures)
        _assert(d["mobileSwitch"]["display"] != "none", key,
                "mobile switcher скрыт", failures)
        _assert(d["actionBtn"] is not None and d["actionBtn"]["w"] >= 44
                and d["actionBtn"]["h"] >= 44, key,
                "mobile ⋯ меньше 44×44: %s" % d["actionBtn"], failures)
        _assert(all(h >= 44 for h in d["tabHeights"]), key,
                "mobile таб <44 px: %s" % d["tabHeights"], failures)
        _assert(d["actionBtn"]["right"] <= vw + 1
                and d["actionBtn"]["left"] >= -1, key,
                "mobile ⋯ обрезан: %s" % d["actionBtn"], failures)


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
            # ── Happy path: страница/дерево/поиск/матрица/роли ────────────
            for (vw, vh) in CHECK_VIEWPORTS:
                _reset_counts()
                MODE.update(roles=0, tree=0, matrix=0, non_global=False)
                ctx, page, errors = _open(browser, vw, vh)
                key = "%dx%d" % (vw, vh)
                try:
                    _main_checks(page, vw, vh, failures, report)
                    d0 = page.evaluate(PROBE_JS)
                    # initial auto-select: ровно один tree-запрос
                    _assert(COUNTS["tree"] == 1, key,
                            "initial tree requests %s != 1" % COUNTS["tree"],
                            failures)
                    # role switch: ровно один tree-запрос
                    if vw >= 768:
                        page.click('.roles-item:nth-child(2)')
                    else:
                        page.select_option('#roles-mobile-select', 'custom_used')
                    page.wait_for_timeout(700)
                    _assert(COUNTS["tree"] == 2, key,
                            "role switch tree %s != 2" % COUNTS["tree"],
                            failures)
                    # F02: custom_used назначена 1 админу — delete disabled,
                    # причина видима, rename остаётся доступным.
                    d2 = page.evaluate(PROBE_JS)
                    _assert(d2["deleteDisabled"] is True, key,
                            "F02: delete занятой роли включен", failures)
                    _assert(d2["renameDisabled"] is False, key,
                            "F02: rename занятой роли должен быть доступен",
                            failures)
                    _assert("назначена 1" in (d2["usageNote"] or ""), key,
                            "F02: нет видимой причины usage", failures)
                    if vw < 768:
                        page.click('[data-roles-actions]')
                        page.wait_for_timeout(250)
                        menu = page.evaluate(
                            "() => { const e = document.querySelector("
                            "'[data-roles-actions-menu] [data-roles-delete]');"
                            " return e ? {disabled: e.disabled,"
                            " h: e.getBoundingClientRect().height} : null; }")
                        _assert(menu is not None and menu["disabled"] is True
                                and menu["h"] >= 44, key,
                                "F02: mobile delete в ⋯ не disabled/44: %s"
                                % menu, failures)
                        page.click('[data-roles-actions]')
                        page.wait_for_timeout(150)
                    report["F02@" + key] = {
                        "role": "custom_used",
                        "deleteDisabled": d2["deleteDisabled"],
                        "renameDisabled": d2["renameDisabled"],
                        "usageNote": d2["usageNote"],
                    }
                    # поиск в правах — 0 запросов на символ
                    before = dict(COUNTS)
                    page.fill('[data-roles-search]', 'limits.search_max_symbols')
                    page.wait_for_timeout(350)
                    d1 = page.evaluate(PROBE_JS)
                    _assert(d1["visibleNodes"] >= 1, key,
                            "поиск по key не нашёл узел", failures)
                    _assert(COUNTS == before, key,
                            "поиск в правах сделал запросы: %s → %s"
                            % (before, COUNTS), failures)
                    page.fill('[data-roles-search]', '')
                    # матрица
                    page.click('[data-roles-tabs] button:nth-child(2)')
                    page.wait_for_timeout(500)
                    dm = page.evaluate(PROBE_JS)
                    _assert(dm["matrixGroups"] >= 100, key,
                            "групп матрицы %s < 100" % dm["matrixGroups"], failures)
                    _assert(dm["ownerLabels"] >= 60, key,
                            "владельцы групп не показаны (%s)" % dm["ownerLabels"],
                            failures)
                    _assert(dm["ownerLabels"] - dm["ownersFallback"] >= 50, key,
                            "owner-групп мало: %s/%s" % (
                                dm["ownerLabels"] - dm["ownersFallback"],
                                dm["ownerLabels"]), failures)
                    _assert('622' in dm["matrixCountText"], key,
                            "счётчик 622 не из данных: %r"
                            % dm["matrixCountText"][:80], failures)
                    # раскрыть первую группу
                    page.click('.roles-tree__group summary')
                    page.wait_for_timeout(350)
                    dm = page.evaluate(PROBE_JS)
                    _assert(dm["matrixRowsVisible"] >= 1, key,
                            "раскрытая группа не показывает строки", failures)
                    _assert(dm["matrixEffective"] >= 1, key,
                            "mobile-модель эффективных ролей отсутствует", failures)
                    before = dict(COUNTS)
                    page.fill('[data-roles-matrix-search]', 'keys.groq_api_key')
                    page.wait_for_timeout(450)
                    dm2 = page.evaluate(PROBE_JS)
                    _assert(dm2["matrixRowsVisible"] >= 1, key,
                            "поиск матрицы по key не нашёл строку", failures)
                    _assert(COUNTS == before, key,
                            "поиск матрицы сделал запросы: %s → %s"
                            % (before, COUNTS), failures)
                    page.fill('[data-roles-matrix-search]', '')
                    # mobile: ровно одна открытая группа
                    if vw < 768:
                        page.evaluate(
                            "() => { document.querySelectorAll('.matrix-group')"
                            ".forEach((d) => { d.open = false; }); }")
                        page.wait_for_timeout(250)
                        summaries = page.query_selector_all(
                            '.roles-tree__group summary')
                        if len(summaries) >= 2:
                            summaries[0].click()
                            page.wait_for_timeout(250)
                            summaries[1].click()
                            page.wait_for_timeout(250)
                            opened = page.evaluate(
                                "() => document.querySelectorAll("
                                "'.matrix-group[open]').length")
                            _assert(opened <= 1, key,
                                    "mobile открыто групп: %s > 1" % opened,
                                    failures)
                    # гейты
                    page.click('[data-roles-tabs] button:nth-child(3)')
                    page.wait_for_timeout(250)
                    dg = page.evaluate(PROBE_JS)
                    _assert(dg["gatesPane"], key, "вкладка гейтов пуста", failures)
                    _assert(not errors, key,
                            "JS-ошибки: %s" % errors[:3], failures)
                    if (vw, vh) in SHOT_VIEWPORTS:
                        page.click('[data-roles-tabs] button:nth-child(1)')
                        page.wait_for_timeout(250)
                        _shot(page, "roles-rights-%dx%d.png" % (vw, vh))
                        page.click('[data-roles-tabs] button:nth-child(2)')
                        page.wait_for_timeout(250)
                        _shot(page, "roles-matrix-%dx%d.png" % (vw, vh))
                finally:
                    ctx.close()

            # ── 401/403/404/503 разными карточками ───────────────────────
            scenarios = [
                ("roles", 401, "[data-roles-error]", "data-roles-error", "401"),
                ("roles", 403, "[data-roles-error]", "data-roles-error", "403"),
                ("tree", 404, "[data-roles-tree-error]", "data-roles-tree-error", "404"),
                ("matrix", 503, "[data-roles-matrix-error]", "data-roles-matrix-error", "503"),
                ("matrix", 403, "[data-roles-matrix-error]", "data-roles-matrix-error", "403"),
                ("roles", 503, "[data-roles-error]", "data-roles-error", "503"),
            ]
            for scope, code, selector, attr, expect in scenarios:
                _reset_counts()
                MODE.update(roles=0, tree=0, matrix=0, non_global=False)
                MODE[scope] = code
                ctx, page, errors = _open(browser, 1440, 900)
                key = "error-%s-%s" % (scope, code)
                try:
                    if scope == "matrix":
                        page.click('[data-roles-tabs] button:nth-child(2)')
                        page.wait_for_timeout(450)
                    else:
                        page.wait_for_timeout(450)
                    got = page.evaluate(
                        "() => { const el = document.querySelector('%s');"
                        " return el ? el.getAttribute('%s') : null; }"
                        % (selector, attr))
                    _assert(got == expect, key,
                            "карточка %s: получено %r" % (selector, got), failures)
                    body = page.evaluate(
                        "() => (document.querySelector('[data-roles-main]')"
                        " || document.body).innerText")
                    _assert("Нет данных" not in body or scope != "matrix", key,
                            "403/503 выдан за пустую матрицу", failures)
                    if scope == "matrix" and code in (403, 503):
                        d = page.evaluate(PROBE_JS)
                        _assert(not d["matrixBodyVisible"], key,
                                "при %s показана дефолтная матрица" % code,
                                failures)
                    # F01: error-состояние не сопровождается нулевым счётчиком.
                    df = page.evaluate(PROBE_JS)
                    if scope == "roles" and code in (401, 403, 503):
                        _assert(df["rolesCount"] is None, key,
                                "F01: в error-состоянии показан РОЛИ %r"
                                % df["rolesCount"], failures)
                    if scope == "matrix" and code in (403, 503):
                        _assert(df["matrixCount"] is None, key,
                                "F01: в error-состоянии показан '%s из %s'"
                                % (df["matrixCount"], "0"), failures)
                        _assert("0 из 0" not in body, key,
                                "F01: '0 из 0' виден рядом с error-карточкой",
                                failures)
                    report[key] = {
                        "error": got,
                        "rolesCount": df["rolesCount"],
                        "matrixCount": df["matrixCount"],
                        "has_0_iz_0": "0 из 0" in body,
                    }
                    # F03: 404 tree — primary action перезагружает СПИСОК ролей.
                    if scope == "tree" and code == 404:
                        _assert(page.query_selector('[data-roles-retry-list]')
                                is not None, key,
                                "F03: нет действия обновления списка ролей",
                                failures)
                        before_roles = COUNTS["roles"]
                        MODE["tree"] = 0
                        page.click('[data-roles-retry-list]')
                        page.wait_for_timeout(900)
                        _assert(COUNTS["roles"] == before_roles + 1, key,
                                "F03: список ролей не перезагружен (%s → %s)"
                                % (before_roles, COUNTS["roles"]), failures)
                        d_retry = page.evaluate(PROBE_JS)
                        _assert(d_retry["treeError"] is None, key,
                                "F03: после retry списка tree-error не снят",
                                failures)
                        report[key]["retryList"] = True
                        report[key]["retryRolesDelta"] = (
                            COUNTS["roles"] - before_roles)
                    _assert(not errors, key,
                            "JS-ошибки: %s" % errors[:2], failures)
                    if code in (401, 403, 404, 503):
                        _shot(page, "roles-error-%s-%s.png" % (scope, code))
                finally:
                    ctx.close()

            # ── F01: non-global 403 — матрица без числового счётчика ──────
            _reset_counts()
            MODE.update(roles=0, tree=0, matrix=0, non_global=True)
            ctx, page, errors = _open(browser, 1440, 900)
            key = "error-matrix-non-global"
            try:
                page.click('[data-roles-tabs] button:nth-child(2)')
                page.wait_for_timeout(450)
                d = page.evaluate(PROBE_JS)
                _assert(d["matrixCount"] is None, key,
                        "F01: non-global видит '%s из %s'"
                        % (d["matrixCount"], "0"), failures)
                body = page.evaluate(
                    "() => (document.querySelector('[data-roles-page]')"
                    " || document.body).innerText")
                _assert("0 из 0" not in body, key,
                        "F01: non-global '0 из 0' виден", failures)
                _assert(page.query_selector('[data-roles-matrix-forbidden]')
                        is not None, key,
                        "F01: non-global без карточки «только владельцу»",
                        failures)
                _assert(not errors, key,
                        "JS-ошибки: %s" % errors[:2], failures)
                report[key] = {
                    "matrixCount": d["matrixCount"],
                    "matrix_forbidden": page.query_selector(
                        '[data-roles-matrix-forbidden]') is not None,
                    "has_0_iz_0": "0 из 0" in body,
                }
                _shot(page, "roles-error-matrix-non-global.png")
            finally:
                ctx.close()
                MODE["non_global"] = False
            browser.close()
    finally:
        httpd.shutdown()

    out = {
        "ok": not failures,
        "failures": failures,
        "counts": dict(COUNTS),
        "report": report,
        "limitations": [
            "локальный стенд: API-стабы из реального param_catalog/"
            "module_registry, TMA_STUB; не live TMA",
            "живой non-global/TMA-сеанс — RFL (не owner QA)",
        ],
    }
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, "report.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("[m4c1] %s: %d failure(s)" % (
        "PASS" if out["ok"] else "FAIL", len(failures)))
    for f in failures:
        print("  -", f)
    print("[m4c1] report ->", path)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    if "--serve" in sys.argv:
        _serve()
    else:
        raise SystemExit(run_playwright())
