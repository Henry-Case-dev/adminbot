"""MOD-ACL-UX-01 M4C C2 — Playwright-приёмка блока «Проверить доступ».

Реальные `web/index.html` / `web/app.js` / `web/static/app.css` на локальном
http-сервере. Стенд импортирует C1-инструмент (`ui_mod_acl_m4c1_roles_e2e.py`)
и добавляет ТРИ read-only C2 endpoint'а: `/api/access/effective`,
`/api/access/chats/{id}/param_permissions`, `/api/access/chats/{id}/admins`.
C1-инструмент не изменяется; /api/roles|admins|roles/tree отвечают теми же
фикстурами C1 + custom_access (для сценария mixed).

Проверяется (контракт §6/§7.3):
  * preview внутри вкладки «Фактические гейты» (не новая вкладка), без
    чекбоксов, «Права не изменены»;
  * слои по порядку, mixed → «Частично», denied/allowed/DM/no-actor;
  * ошибки 401/403/404/422/503 разными карточками; 503 не «Запрещено»;
    чатовые перекрытия: 403 — скрыто с подписью, 503 — error-карточка;
  * mobile: одна колонка, тач-цели ≥44, h-scroll 0, без вложенных скроллов;
  * viewports 1920/1440/1280/768/390/320; скриншоты 1440/390.

Ограничение (честно): локальный стенд с детерминированными стабами, НЕ live
TMA и не production-БД; реальная семантика решения покрыта Python-тестами +
анти-дрейфом, здесь — UI/сеть/раскладка.

Запуск:
  py tools/ui_mod_acl_m4c2_preview_e2e.py          # Playwright
  py tools/ui_mod_acl_m4c2_preview_e2e.py --serve  # стенд для Browser Use
Артефакты: MOD_ACL_M4C2_SHOTS (evidence/m4c/c2/shots).
"""
import copy
import json
import os
import re
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

import ui_mod_acl_m4_catalog_e2e as base            # noqa: E402
import ui_mod_acl_m4c1_roles_e2e as c1             # noqa: E402

PORT = int(os.environ.get("MOD_ACL_M4C2_PORT", "8812"))
SHOTS = os.environ.get(
    "MOD_ACL_M4C2_SHOTS",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4c", "c2", "shots"))
BASE = "http://127.0.0.1:%d" % PORT
CHECK_VIEWPORTS = [(1920, 1080), (1440, 900), (1280, 800), (768, 1024),
                   (390, 844), (320, 568)]
SHOT_VIEWPORTS = {(1440, 900), (390, 844)}

CHAT_ID = c1.CHAT_ID
DM_ID = 999999999                 # fallback-актор стаба (не владелец ЛС сценария)
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
LOCAL_ID = 700000002
CUSTOM_ACCESS_ID = 424242424

ROLES = copy.deepcopy(c1.ROLES)
ROLES["custom_access"] = {
    "role_name": "custom_access", "is_custom": True,
    "permissions": {"sections": ["access"]},
}
ROLES = dict(sorted(ROLES.items()))
ADMINS = list(c1.ADMINS) + [
    {"telegram_id": CUSTOM_ACCESS_ID, "role_name": "custom_access",
     "display_name": None, "added_by": ADMIN_ID,
     "created_at": "2026-11-22T00:00:10+00:00"},
]
CHAT_ADMINS = [
    {"telegram_id": LOCAL_ID, "role_name": "local_admin",
     "added_by": ADMIN_ID, "created_at": "2026-11-22T01:00:00+00:00",
     "display_name": "Local"},
    {"telegram_id": MODERATOR_ID, "role_name": "moderator",
     "added_by": ADMIN_ID, "created_at": "2026-11-22T01:00:01+00:00",
     "display_name": "Mod"},
]
CHAT_ROLES = {LOCAL_ID: "local_admin", MODERATOR_ID: "moderator"}

ACTORS = {
    ADMIN_ID: {"role_name": "admin", "role_type": "global_admin",
               "is_global_admin": True, "rank": 4, "sections": ["*"]},
    MODERATOR_ID: {"role_name": "moderator", "role_type": "moderator",
                   "is_global_admin": False, "rank": 2,
                   "sections": ["limits"], "actions": [
                       "control.restart", "control.stop", "control.start"]},
    LOCAL_ID: {"role_name": "local_admin", "role_type": "local_admin",
               "is_global_admin": False, "rank": 3,
               "sections": ["limits", "flags", "reactions", "content",
                            "chat_lore"]},
    CUSTOM_ACCESS_ID: {"role_name": "custom_access", "role_type": "custom",
                       "is_global_admin": False, "rank": 2,
                       "sections": ["access"]},
    777000222: {"role_name": "custom_used", "role_type": "custom",
                "is_global_admin": False, "rank": 1, "sections": []},
    DM_ID: {"role_name": "user", "role_type": "user",
            "is_global_admin": False, "rank": 1, "sections": []},
}

MODE = {"effective": 0, "chat_overrides": 0, "chat_admins": 0}


def _tree_for(role_name):
    if role_name in c1.TREES:
        return copy.deepcopy(c1.TREES[role_name])
    perms = (ROLES.get(role_name) or {}).get("permissions") or {}
    sections = []
    for sid, title in (("access", "Доступы"), ("chat_lore", "Лор чата")):
        sections.append({"id": sid, "title": title,
                         "checked": sid in (perms.get("sections") or []),
                         "params": [], "keys": []})
    actions = [{"id": a, "title": a,
                "checked": a in (perms.get("actions") or [])}
               for a in ("edit_info", "edit_persona", "edit_humor_library",
                         "control.restart", "control.stop", "control.start",
                         "debug.config")]
    return {"sections": sections, "actions": actions}


def _layer(layer_id, label, decision, applies_to, reason, *,
           required=None, matched=None, guard=None, consumers=(),
           hard=False, source=None):
    return {"id": layer_id, "label": label, "decision": decision,
            "hard": hard, "applies_to": applies_to, "reason": reason,
            "required": required, "matched": matched, "guard": guard,
            "consumers": list(consumers), "source": source}


def _effective_payload(query):
    actor_id = int((query.get("telegram_id") or [DM_ID])[0])
    chat_raw = (query.get("chat_id") or [None])[0]
    chat_id = int(chat_raw) if chat_raw not in (None, "") else None
    resource = (query.get("resource") or [""])[0]
    operation = (query.get("operation") or ["view"])[0]
    actor = ACTORS.get(actor_id, ACTORS[DM_ID])
    is_admin = bool(actor.get("is_global_admin"))
    kind, rest = (resource.split(".", 1) + [""])[:2]
    sections = actor.get("sections") or []
    chat_role = CHAT_ROLES.get(actor_id) if (chat_id or 0) < 0 else None
    is_dm_owner = bool(chat_id is not None and chat_id > 0
                       and chat_id == actor_id)
    layers = []
    overrides = None

    if kind == "section":
        allowed_role = "*" in sections or rest in sections
        if chat_id is None and rest == "access":
            layers.append(_layer(
                "role", "Права роли",
                "allowed" if allowed_role else "denied", "guard",
                "section" if allowed_role else "no_match",
                required="section.access", matched="section.access"
                if allowed_role else None,
                guard='web.api.deps.requires_permission("access")',
                consumers=("GET /api/roles", "POST /api/roles")))
            layers.append(_layer(
                "global_admin_ceiling", "Потолок: global admin",
                "allowed" if is_admin else "denied", "guard",
                "role_type" if is_admin else "no_match",
                required="global_admin",
                matched="role_type:global_admin" if is_admin else None,
                guard="is_global_admin (inline)",
                consumers=("GET/PUT/DELETE /api/access/param_permissions",)))
            if allowed_role and is_admin:
                decision = "allowed"
            elif not allowed_role and not is_admin:
                decision = "denied"
            else:
                decision = "mixed"
        elif chat_id is not None and chat_id < 0 and rest == "chat_lore":
            guard_ok = is_admin or chat_role in ("local_admin", "moderator")
            layers.append(_layer(
                "role", "Права роли", "allowed" if rest in sections else "denied",
                "ui_visibility", "section" if rest in sections else "no_match",
                required="section.chat_lore"))
            layers.append(_layer(
                "chat_access", "Доступ к чату",
                "allowed" if guard_ok else "denied", "guard",
                "global_admin_rank" if is_admin else (chat_role or "no_grant"),
                required="chat_admins", hard=not guard_ok,
                guard="web.api.chat_lore.can_access_chat"))
            decision = "allowed" if guard_ok else "denied"
        else:
            layers.append(_layer(
                "role", "Права роли",
                "allowed" if allowed_role else "denied", "coverage",
                "section" if allowed_role else "no_match",
                required="section." + rest))
            decision = "allowed" if allowed_role else "denied"
    elif kind == "action":
        action_ok = is_admin or rest in (actor.get("actions") or [])
        layers.append(_layer(
            "role", "Права роли", "allowed" if action_ok else "denied",
            "guard", "role_type" if is_admin else
            ("action" if action_ok else "no_match"),
            required="action." + rest,
            guard='web.api.deps.requires_permission("%s")' % rest,
            consumers=("POST /api/control/*",)))
        decision = "allowed" if action_ok else "denied"
    elif kind in ("param", "key"):
        overrides = {
            "global": {"present": False, "updated_at": None,
                       "author_recorded": False},
            "chat": {"present": bool(chat_id is not None and chat_id < 0),
                     "updated_at": "2026-11-22T10:00:00+00:00"
                     if (chat_id is not None and chat_id < 0) else None,
                     "author_recorded": False},
        }
        if kind == "key":
            if chat_id is not None:
                layers.append(_layer(
                    "scope_capability", "Ключи в чате", "not_applicable",
                    "guard", "keys_via_byok"))
                decision = "not_applicable"
            else:
                ok = is_admin if operation == "view" else (
                    is_admin or "keys" in sections)
                layers.append(_layer(
                    "secret_policy", "Секреты",
                    "allowed" if ok else "denied", "guard",
                    "secret_admin_only" if not ok else "role_type",
                    required="key." + rest, hard=not ok,
                    guard="web.api.routes.get_config (secret mask)"))
                decision = "allowed" if ok else "denied"
        elif chat_id is not None:
            chat_ok = is_dm_owner or is_admin or chat_role is not None
            if is_dm_owner:
                access_reason = "dm_owner"
            elif is_admin:
                access_reason = "global_admin_rank"
            elif chat_role:
                access_reason = chat_role
            else:
                access_reason = "no_match"
            layers.append(_layer(
                "chat_access", "Доступ к чату",
                "allowed" if chat_ok else "denied", "guard", access_reason,
                required="chat:%s" % chat_id, hard=not chat_ok,
                guard="access.can_access_chat(ctx, chat_id)"))
            matrix_ok = bool(is_admin or is_dm_owner
                             or chat_role in ("local_admin", "moderator"))
            if operation == "edit":
                layers.append(_layer(
                    "chat_grant", "Грант чата",
                    "allowed" if matrix_ok else "denied", "guard",
                    "dm_owner" if is_dm_owner else (
                        "global_admin_rank" if is_admin else
                        (chat_role or "no_grant")),
                    required="chat_admins"))
            matrix_allowed = matrix_ok and (
                is_admin or is_dm_owner or chat_role == "local_admin"
                or (operation == "view" and chat_role == "moderator"))
            layers.append(_layer(
                "chat_matrix", "Матрица «Доступ к параметрам»",
                "allowed" if matrix_allowed else "denied", "guard",
                "chat_override" if chat_id < 0 else "default",
                required="param." + rest,
                source="chat_override" if chat_id < 0 else "default"))
            decision = ("allowed" if (chat_ok and matrix_allowed) else "denied")
        elif operation == "edit":
            ok = is_admin or bool(set(sections) & {rest.split(".")[0], "*"})
            layers.append(_layer(
                "role", "Права роли", "allowed" if ok else "denied", "guard",
                "wildcard" if is_admin else ("section" if ok else "no_match"),
                required="param." + rest,
                guard="web.api.deps.can_edit_param"))
            decision = "allowed" if ok else "denied"
        else:
            layers.append(_layer(
                "role", "Права роли", "not_applicable", "guard",
                "no_backend_guard", required="param." + rest))
            layers.append(_layer(
                "config_surface", "Глобальное чтение", "allowed", "guard",
                "global_config_all", required="param." + rest,
                source="default"))
            decision = "allowed"
    else:
        decision = "denied"

    scope_kind = "global" if chat_id is None else (
        "dm" if chat_id > 0 else "chat")
    return {
        "mode": "self", "preview": True,
        "note": "Предварительная проверка. Права не изменены.",
        "decision": decision,
        "evaluated_at": "2026-11-22T10:00:00Z",
        "resolver": "roles.access_for(strict)+access.effective_matrix+"
                    "permissions.requires_permission+chat_params.strict/v1",
        "actor": {
            "telegram_id": actor_id, "display_name": None,
            "role_name": actor["role_name"], "role_type": actor["role_type"],
            "is_global_admin": bool(is_admin),
            "is_local_admin": chat_role == "local_admin",
            "rank": actor["rank"], "is_dm_owner": is_dm_owner,
        },
        "scope": {"kind": scope_kind, "chat_id": chat_id,
                  "title": "Личные сообщения" if scope_kind == "dm" else None,
                  "chat_role": chat_role,
                  "profile_present": True if chat_id is not None else None},
        "resource": {"namespace": resource, "kind": kind,
                     "title": None, "secret": None, "hidden": None},
        "operation": operation,
        "layers": layers,
        "overrides": overrides,
    }


def _chat_overrides_payload(chat_id):
    return {
        "chat_id": chat_id, "profile_present": True,
        "updated_at": "2026-11-22T10:00:00+00:00",
        "items": {"limits.search_max_symbols": {
            "view_roles": ["user", "moderator", "local_admin"],
            "edit_roles": [], "legacy": True}},
        "filtered_out": 1,
    }


def _chat_admins_payload(chat_id):
    return {"chat_id": chat_id, "admins": [dict(r) for r in CHAT_ADMINS]}


def _api_response(url, headers=None):
    path = url.split("?")[0]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if re.search(r"/api/access/chats/-?\d+/param_permissions$", path):
        code = MODE.get("chat_overrides") or 200
        if code != 200:
            return code, {"detail": {"code": "stub",
                                     "message": "chat overrides %s" % code}}
        return 200, _chat_overrides_payload(
            int(re.search(r"/chats/(-?\d+)/", path).group(1)))
    if re.search(r"/api/access/chats/-?\d+/admins$", path):
        code = MODE.get("chat_admins") or 200
        if code != 200:
            return code, {"detail": "chat admins %s" % code}
        return 200, _chat_admins_payload(
            int(re.search(r"/chats/(-?\d+)/", path).group(1)))
    if path.endswith("/api/access/effective"):
        code = MODE.get("effective") or 200
        if code != 200:
            return code, {"detail": {"code": "stub", "message": "eff %s" % code}}
        return 200, _effective_payload(query)
    if path.endswith("/api/admins"):
        return 200, {"admins": ADMINS}
    if path.endswith("/api/roles"):
        return 200, {"roles": [ROLES[n] for n in sorted(ROLES)]}
    if path.endswith("/api/roles/tree"):
        role = (query.get("role_name") or [""])[0]
        if role not in ROLES:
            return 404, {"detail": "роль не найдена: %s" % role}
        return 200, _tree_for(role)
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
        return base._Handler.do_GET(self)


def _serve():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    print("[serve] %s (Browser Use stand), Ctrl+C to stop" % BASE)
    httpd.serve_forever()


PREVIEW_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {x: +r.x.toFixed(1), y: +r.y.toFixed(1), w: +r.width.toFixed(1),
            h: +r.height.toFixed(1), left: +r.left.toFixed(1),
            right: +r.right.toFixed(1)};
  };
  const visible = (el) => !!(el && el.getClientRects().length
    && getComputedStyle(el).visibility !== 'hidden');
  const prev = q('[data-preview]');
  const pane = q('[data-roles-pane="gates"]');
  const form = q('[data-preview-form]');
  return {
    previewVisible: visible(prev),
    insideGates: !!(prev && pane && pane.contains(prev)),
    title: (q('[data-preview-title]') || {}).textContent || '',
    note: (q('[data-preview-note]') || {}).textContent || '',
    actor: rect(q('[data-preview-actor]')),
    actorValues: qa('[data-preview-actor] option').map((e) => e.value),
    scope: rect(q('[data-preview-scope]')),
    resource: rect(q('[data-preview-resource]')),
    op: rect(q('[data-preview-op]')),
    run: rect(q('[data-preview-run]')),
    runDisabled: q('[data-preview-run]')
      ? q('[data-preview-run]').disabled : null,
    formCols: form ? getComputedStyle(form).gridTemplateColumns : '',
    decision: (q('[data-preview-decision]') || {}).textContent || '',
    decisionAttr: q('[data-preview-decision]')
      ? q('[data-preview-decision]').getAttribute('data-decision') : null,
    layers: qa('[data-preview-layer]').map((el) => ({
      id: el.getAttribute('data-preview-layer'),
      decision: el.getAttribute('data-decision'),
      hasGuard: !!el.querySelector('.roles-preview__guard'),
    })),
    error: q('[data-preview-error]')
      ? q('[data-preview-error]').getAttribute('data-preview-error') : null,
    noActor: visible(q('[data-preview-no-actor]')),
    stale: visible(q('[data-preview-stale]')),
    overrides: visible(q('[data-preview-chat-overrides]')),
    overrideRows: qa('.roles-preview__override-row').length,
    overridesError: !!q('.roles-preview__chat-overrides .roles-state--err'),
    overridesSuppressed: !!(q('[data-preview-chat-overrides]')
      && q('[data-preview-chat-overrides]').textContent.indexOf('403') >= 0),
    checkboxesInGates:
      qa('[data-roles-pane="gates"] input[type="checkbox"]').length,
    previewText: (prev || {}).innerText || '',
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
    nestedScrollers: qa('[data-roles-page] *').filter((el) => {
      const cs = getComputedStyle(el);
      return (cs.overflowY === 'auto' || cs.overflowY === 'scroll')
        && el.scrollHeight > el.clientHeight + 1;
    }).length,
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


def _open(browser, width, height, *, admins_delay_ms=0):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    if admins_delay_ms:
        # C2-R1-7 e2e: задержать ТОЛЬКО /api/admins на клиенте (не блокируя
        # драйвер Playwright), чтобы проверить состояние до завершения загрузки.
        ctx.add_init_script(
            "(() => {\n"
            "  const orig = window.fetch;\n"
            "  window.fetch = function (u, i) {\n"
            "    const url = String((u && u.url) || u);\n"
            "    if (url.indexOf('/api/admins') >= 0) {\n"
            "      return new Promise(function (res, rej) {\n"
            "        setTimeout(function () { orig(u, i).then(res, rej); },\n"
            "          %d);\n"
            "      });\n"
            "    }\n"
            "    return orig(u, i);\n"
            "  };\n"
            "})();" % int(admins_delay_ms))
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
    page.click('[data-roles-tabs] button:nth-child(3)')
    page.wait_for_timeout(300)
    return ctx, page, errors


def _route(route):
    code, payload = _api_response(route.request.url,
                                  dict(route.request.headers))
    route.fulfill(status=code, content_type="application/json",
                  body=json.dumps(payload))


def _select_role(page, name):
    display = page.eval_on_selector(
        '[data-roles-aside]', 'el => getComputedStyle(el).display')
    if display == 'none':
        page.select_option('#roles-mobile-select', name)
    else:
        page.click('.roles-item:has-text("%s")' % name)
    page.wait_for_timeout(700)


def _run(page, *, actor=None, scope=None, resource, operation=None):
    # Scope сперва: чатовые гранты догружаются и добавляют акторов роли.
    if scope is not None:
        page.select_option('[data-preview-scope]', str(scope))
        page.wait_for_timeout(650)      # догрузка чатовых грантов
    if actor is not None:
        page.select_option('[data-preview-actor]', str(actor))
        page.wait_for_timeout(250)
    page.fill('[data-preview-resource]', resource)
    if operation is not None:
        page.select_option('[data-preview-op]', operation)
    page.click('[data-preview-run]')
    page.wait_for_function(
        "() => !!document.querySelector('[data-preview-result]')"
        " || !!document.querySelector('[data-preview-error]')",
        timeout=10000)
    page.wait_for_timeout(350)


def _main_checks(page, vw, vh, failures, report):
    key = "%dx%d" % (vw, vh)
    d = page.evaluate(c1.PROBE_JS)
    p = page.evaluate(PREVIEW_JS)
    report[key] = {"base": {k: d[k] for k in
                            ("roles", "sections", "rightsPane", "matrixPane",
                             "gatesPane", "scrollWidth", "hScroll",
                             "scrollers", "tabHeights", "aside",
                             "mobileSwitch")},
                   "preview": p}
    _assert(p["previewVisible"], key, "preview не виден в gates", failures)
    _assert(p["insideGates"], key, "preview вне вкладки gates", failures)
    _assert("Проверить доступ" in p["title"], key, "нет заголовка", failures)
    _assert("Права не изменены" in p["note"], key, "нет note", failures)
    _assert(p["checkboxesInGates"] == 0, key,
            "в gates/preview появились чекбоксы", failures)
    _assert(p["hScroll"] is False and p["scrollWidth"] <= vw + 1, key,
            "h-overflow %s > %s" % (p["scrollWidth"], vw), failures)
    _assert(p["nestedScrollers"] == 0, key,
            "вложенный вертикальный скролл: %s" % p["nestedScrollers"],
            failures)
    for field in ("actor", "scope", "resource", "op", "run"):
        _assert(p[field] is not None and p[field]["h"] >= 30, key,
                "поле %s не отрисовано/низкое: %s" % (field, p[field]),
                failures)
        _assert(p[field]["right"] <= vw + 1, key,
                "поле %s обрезано: %s" % (field, p[field]), failures)
    if vw < 768:
        _assert(p["actor"]["h"] >= 44 and p["scope"]["h"] >= 44
                and p["resource"]["h"] >= 44 and p["op"]["h"] >= 44
                and p["run"]["h"] >= 44, key,
                "mobile тач-цель <44: %s" % {
                    "actor": p["actor"], "scope": p["scope"],
                    "resource": p["resource"], "op": p["op"],
                    "run": p["run"]}, failures)
        _assert(len(p["formCols"].split()) == 1, key,
                "mobile форма не в одну колонку: %r" % p["formCols"],
                failures)
    else:
        _assert(len(p["formCols"].split()) == 2, key,
                "desktop форма не в 2 колонки: %r" % p["formCols"],
                failures)
    return p


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
            # ── 1. Happy path по viewport'ам: allowed/mixed/no-actor ──────
            for (vw, vh) in CHECK_VIEWPORTS:
                MODE.update(effective=0, chat_overrides=0, chat_admins=0)
                ctx, page, errors = _open(browser, vw, vh)
                key = "%dx%d" % (vw, vh)
                try:
                    p0 = _main_checks(page, vw, vh, failures, report)
                    # default role = admin (sorted), actor seeded = admin id
                    _run(page, resource="section.access")
                    d = page.evaluate(PREVIEW_JS)
                    _assert(d["decisionAttr"] == "allowed", key,
                            "admin section.access: %r" % d["decisionAttr"],
                            failures)
                    _assert([l["id"] for l in d["layers"]]
                            == ["role", "global_admin_ceiling"], key,
                            "слои admin: %s" % d["layers"], failures)
                    _assert(all(l["hasGuard"] for l in d["layers"]), key,
                            "у слоёв нет guard", failures)
                    if (vw, vh) in SHOT_VIEWPORTS:
                        _shot(page, "preview-allowed-%dx%d.png" % (vw, vh))
                    # custom section.access → mixed/«Частично»
                    _select_role(page, "custom_access")
                    _run(page, actor=CUSTOM_ACCESS_ID,
                         resource="section.access")
                    d = page.evaluate(PREVIEW_JS)
                    _assert(d["decisionAttr"] == "mixed", key,
                            "custom_access: %r" % d["decisionAttr"], failures)
                    _assert("Частично" in d["decision"], key,
                            "mixed не «Частично»: %r" % d["decision"],
                            failures)
                    # роль без назначений → no-actor (local_admin не назначен)
                    _select_role(page, "local_admin")
                    page.wait_for_timeout(300)
                    d = page.evaluate(PREVIEW_JS)
                    _assert(d["noActor"] is True, key,
                            "роль без назначений без no-actor", failures)
                    _assert(d["runDisabled"] is True, key,
                            "кнопка активна без актора", failures)
                    if (vw, vh) in SHOT_VIEWPORTS:
                        _shot(page, "preview-no-actor-%dx%d.png" % (vw, vh))
                    # moderator: chat view allowed / edit denied
                    _select_role(page, "moderator")
                    _run(page, actor=MODERATOR_ID, scope=CHAT_ID,
                         resource="param.limits.search_max_symbols")
                    d = page.evaluate(PREVIEW_JS)
                    _assert(d["decisionAttr"] == "allowed", key,
                            "moderator chat view: %r" % d["decisionAttr"],
                            failures)
                    _assert(d["overrides"] is True and d["overrideRows"] >= 1,
                            key, "чатовые перекрытия не показаны", failures)
                    _run(page, scope=CHAT_ID,
                         resource="param.limits.search_max_symbols",
                         operation="edit")
                    d = page.evaluate(PREVIEW_JS)
                    _assert(d["decisionAttr"] == "denied", key,
                            "moderator chat edit: %r" % d["decisionAttr"],
                            failures)
                    _assert("Запрещено" in d["decision"], key,
                            "denied не «Запрещено»", failures)
                    if (vw, vh) in SHOT_VIEWPORTS:
                        _shot(page, "preview-denied-%dx%d.png" % (vw, vh))
                    # local_admin с грантом чата → allowed (роль уже с scope=chat)
                    _select_role(page, "local_admin")
                    _run(page, actor=LOCAL_ID, scope=CHAT_ID,
                         resource="param.limits.search_max_symbols",
                         operation="edit")
                    d = page.evaluate(PREVIEW_JS)
                    _assert(d["decisionAttr"] == "allowed", key,
                            "local_admin edit: %r" % d["decisionAttr"],
                            failures)
                    _assert([l["id"] for l in d["layers"]]
                            == ["chat_access", "chat_grant", "chat_matrix"],
                            key, "слои local_admin: %s" % d["layers"], failures)
                    # DM владелец: self + dm → allowed (dm-опция только self)
                    page.select_option('[data-preview-actor]', 'self')
                    page.wait_for_timeout(250)
                    _run(page, scope="dm",
                         resource="param.limits.search_max_symbols",
                         operation="edit")
                    d = page.evaluate(PREVIEW_JS)
                    _assert(d["decisionAttr"] == "allowed", key,
                            "DM owner: %r" % d["decisionAttr"], failures)
                    _assert(not errors, key, "JS-ошибки: %s" % errors[:3],
                            failures)
                finally:
                    ctx.close()

            # ── 2. Честные ошибки ─────────────────────────────────────────
            scenarios = [
                ("effective", 401, "401"),
                ("effective", 403, "403"),
                ("effective", 404, "404"),
                ("effective", 422, "422"),
                ("effective", 503, "503"),
            ]
            for scope, code, expect in scenarios:
                MODE.update(effective=0, chat_overrides=0, chat_admins=0)
                MODE[scope] = code
                ctx, page, errors = _open(browser, 1440, 900)
                key = "error-%s-%s" % (scope, code)
                try:
                    _run(page, resource="section.access")
                    d = page.evaluate(PREVIEW_JS)
                    _assert(d["error"] == expect, key,
                            "карточка %s: %r" % (code, d["error"]), failures)
                    _assert(d["decisionAttr"] is None, key,
                            "при ошибке показано решение", failures)
                    _assert("Запрещено" not in d["previewText"], key,
                            "ошибка выдана за «Запрещено»", failures)
                    if code == 503:
                        _assert("временно" in d["previewText"], key,
                                "503 без подсказки о недоступности", failures)
                        _shot(page, "preview-error-503.png")
                    if code == 403:
                        _assert("не означает" in d["previewText"], key,
                                "403 выдан за пустоту", failures)
                        _shot(page, "preview-error-403.png")
                    _assert(not errors, key, "JS-ошибки: %s" % errors[:2],
                            failures)
                finally:
                    ctx.close()

            # ── 3. Перекрытия чата: 403 скрыто, 503 — карточка ────────────
            for code in (403, 503):
                MODE.update(effective=0, chat_overrides=code, chat_admins=0)
                ctx, page, errors = _open(browser, 1440, 900)
                key = "overrides-%s" % code
                try:
                    _select_role(page, "moderator")
                    _run(page, actor=MODERATOR_ID, scope=CHAT_ID,
                         resource="param.limits.search_max_symbols")
                    d = page.evaluate(PREVIEW_JS)
                    _assert(d["decisionAttr"] == "allowed", key,
                            "решение не должно страдать от ошибки перекрытий",
                            failures)
                    if code == 403:
                        _assert(d["overridesSuppressed"] is True, key,
                                "403 перекрытий не скрыт с подписью", failures)
                        _assert(d["overridesError"] is False, key,
                                "403 перекрытий показан как error-карточка",
                                failures)
                    else:
                        _assert(d["overridesError"] is True, key,
                                "503 перекрытий без error-карточки", failures)
                        _shot(page, "preview-overrides-503.png")
                finally:
                    ctx.close()
                    MODE["chat_overrides"] = 0
            # ── 4. C2-R1-7: admins in-flight на 1440/1280 ────────────────
            for (vw, vh) in ((1440, 900), (1280, 800)):
                MODE.update(effective=0, chat_overrides=0, chat_admins=0)
                ctx, page, errors = _open(browser, vw, vh,
                                          admins_delay_ms=2500)
                key = "admins-inflight-%dx%d" % (vw, vh)
                try:
                    d = page.evaluate(PREVIEW_JS)
                    _assert(d["noActor"] is False, key,
                            "noActor показан до завершения /api/admins",
                            failures)
                    _assert(d["runDisabled"] is False, key,
                            "кнопка disabled до завершения /api/admins",
                            failures)
                    page.wait_for_timeout(2400)
                    d = page.evaluate(PREVIEW_JS)
                    _assert(d["noActor"] is False, key,
                            "noActor после загрузки назначенной роли", failures)
                    _assert("5885953495" in d["actorValues"], key,
                            "actor-list не обновлён после /api/admins: %s"
                            % d["actorValues"], failures)
                    _assert(d["runDisabled"] is False, key,
                            "кнопка disabled при назначенной роли", failures)
                    _run(page, resource="section.access")
                    d = page.evaluate(PREVIEW_JS)
                    _assert(d["decisionAttr"] == "allowed", key,
                            "admin section.access после reseed: %r"
                            % d["decisionAttr"], failures)
                    _assert(not errors, key, "JS-ошибки: %s" % errors[:2],
                            failures)
                    report[key] = {"noActor": d["noActor"],
                                   "actorValues": d["actorValues"],
                                   "runDisabled": d["runDisabled"],
                                   "decision": d["decisionAttr"]}
                    if vw == 1440:
                        _shot(page, "preview-admins-inflight-1440x900.png")
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
            "локальный стенд: /api/access/* — детерминированные стабы, "
            "TMA_STUB; НЕ live TMA и не production-БД",
            "реальная семантика решения покрыта Python-тестами и анти-дрейфом; "
            "здесь UI/сеть/раскладка",
            "живой non-global/TMA-сеанс — RFL (не owner QA)",
        ],
    }
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, "report.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("[m4c2] %s: %d failure(s)" % (
        "PASS" if out["ok"] else "FAIL", len(failures)))
    for f in failures:
        print("  -", f)
    print("[m4c2] report ->", path)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    if "--serve" in sys.argv:
        _serve()
    else:
        raise SystemExit(run_playwright())
