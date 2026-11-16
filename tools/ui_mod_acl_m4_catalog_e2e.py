"""MOD-ACL-UX-01 M4A (wave 1) — Playwright/Chromium приёмка каталога модулей.

Реальный `web/index.html` + `web/static/*` на локальном http-сервере; `/api/*`
перехватываются Playwright'ом. `/api/config.modules[]` строится из РЕАЛЬНОГО
`services.module_registry.registry_for_frontend()` (синтетические состояния
осей — honest-флаги, не секреты), поэтому проверяется фактический DTO, а не
рукописная копия каталога.

Проверки (design §4.1/§4.6/§11.2):
  * `#/modules`: 21 `[data-mod]` в порядке `catalog_order`; 5 групп; колонки
    4/3/2/1 (1440/1280/768/390/320); высота карточки 132–164; нет
    горизонтального скролла; caption `21 модуль · N требуют внимания`;
  * 1280×800: ≥8 карточек в первом viewport (baseline §2.4 — 4);
  * клик по телу карточки открывает `#/modules/<slug>`; клик по контролу не
    навигирует;
  * `#/modules/summary` (param-путь) и `#/modules/nostalgia` (gate-путь):
    крошка `Модули / …`, один H1, GLOBAL+CHAT одновременно, чипы осей,
    табы 38–44 px c `aria-current`, `role=tabpanel`, контент 16–24 px после
    табов; `#/modules/time` — без тумблера;
  * 409: POST-стаб отдаёт `{code:"conflict"}` → баннер «Настройка изменилась
    в другом окне», НЕТ тоста «Настройка сохранена», ровно 1 POST;
  * negative states: can_read=false → «Нет права смотреть», can_edit=false →
    disabled, desired=false → «Выключено», ready=false → причина, emergency.

Запуск: .venv/Scripts/python.exe tools/ui_mod_acl_m4_catalog_e2e.py
Артефакты: %MOD_ACL_M4A_SHOTS% (по умолчанию plans/features/mod-acl-ux-01/
evidence/m4a/shots) + JSON-отчёт в stdout.

ВАЖНО: успешный локальный прогон НЕ заменяет живой TMA (как и у остальных
ui_*_e2e инструментов).
"""
import copy
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
PORT = int(os.environ.get("MOD_ACL_M4A_PORT", "8795"))
SHOTS = os.environ.get(
    "MOD_ACL_M4A_SHOTS",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4a", "shots"))

VIEWPORTS = [(1440, 900), (1280, 800), (768, 1024), (390, 844), (320, 568)]
EXPECT_COLUMNS = {1440: 4, 1280: 3, 768: 2, 390: 1, 320: 1}

CHAT_ID = -1001234567890
CHAT_TITLE = "Audit Chat"


class _Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):  # noqa: N802
        p = path.split("?")[0]
        if p.startswith("/static/"):
            rel = "web/static/" + p[len("/static/"):]
        elif p.startswith("/web/"):
            rel = p[1:]
        elif p in ("/", "", "/index.html"):
            rel = "web/index.html"
        else:
            rel = p.lstrip("/")
        return os.path.join(REPO, rel.replace("/", os.sep))

    def log_message(self, *args):  # тишина
        pass


def _start_server() -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


ME_JSON = {
    "telegram_id": 5885953495,
    "username": "audit",
    "first_name": "Audit",
    "last_name": None,
    "photo_url": None,
    "role_name": "global_admin",
    "permissions": {"wildcard": True},
    "is_custom": False,
    "is_global_admin": True,
    "role_chat": "admin",
    "ui_flags": {
        "IMAGE_MODULE_CARD_ENABLED": True,
        "IA_V2_ENABLED": True,
        "UI_SHELL_GLASS_V2": True,
        "UI_SHELL_LAYOUT_V2": True,
        "UI_HEARTBEAT_PREMIUM": True,
        "UI_SHELL_V3": True,
        "UI_AURORA_BG_ENABLED": False,
        "UI_SHELL_FLEX_V3": True,
        "UI_SHELL_GRAPHITE_V3": True,
        "UI_LIQUID_GLASS_LIB": False,
        "UI_AURORA_FLOW_V2": False,
        "UI_POLYGON_BG_ENABLED": False,
        "UI_STATUS_GRID_V2": True,
    },
}

TMA_STUB = """
try {
  sessionStorage.setItem(
    'adminbot.initData',
    'user=%7B%22id%22%3A5885953495%7D&hash=audit');
} catch (e) {}
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A5885953495%7D&hash=audit',
  initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
  themeParams: {}, colorScheme: 'dark',
  viewportStableHeight: window.innerHeight,
  isExpanded: true, ready: function () {}, expand: function () {},
  onEvent: function () {}, offEvent: function () {},
  setHeaderColor: function () {}, setBackgroundColor: function () {},
  HapticFeedback: { impactOccurred: function () {},
                    notificationOccurred: function () {} },
  showAlert: function () {}, openLink: function () {},
  disableVerticalSwipes: function () {},
} };
"""


def _state(module_id: str) -> dict:
    """Синтетическое состояние оси (honest: null = «не проверялось»)."""
    st = {
        "chat_state": "inherit", "desired": True, "source": "default",
        "global_value": True, "global_source": "default",
        "emergency_block": False, "effective_runtime": True,
        "ready": None, "authorized": None, "observed": None,
        "observed_at": "2026-11-17T10:00:00+00:00",
        "last_activity_at": None, "reason_code": None,
        "pending_restart": False, "version": None, "consent": None,
        "conflict": None, "checked_at": "2026-11-17T10:00:00+00:00",
    }
    if module_id == "summary":
        st.update(observed=True, last_activity_at="2026-11-17T09:58:00+00:00")
    if module_id == "web":
        st.update(desired=False, effective_runtime=False,
                  global_value=False, reason_code="capability_off")
    if module_id == "search":
        st.update(ready=False, reason_code="provider_missing:llm")
    if module_id == "checkup":
        st.update(emergency_block=True)
    return st


# Особые карточки: права и состояния для negative-проверок.
PERMISSIONS = {
    "budgets": {"can_read": False, "can_edit": False},
    "vision": {"can_read": True, "can_edit": False},
}


def _registry_payload(chat_scope: bool) -> list:
    from services import module_registry as mr
    states = {}
    for spec in mr.MODULE_REGISTRY.values():
        if spec.visibility == "hidden":
            continue
        st = _state(spec.id)
        perms = PERMISSIONS.get(spec.id, {"can_read": True, "can_edit": True})
        st["can_read"] = perms["can_read"]
        st["can_edit"] = perms["can_edit"]
        if chat_scope:
            st["chat_id"] = CHAT_ID
            st["source"] = "chat" if spec.id in ("summary", "nostalgia") else "global"
            if spec.id == "summary":
                st["chat_state"] = "on"
            if spec.id == "nostalgia":
                st["chat_state"] = "on"
        states[spec.id] = st
    return mr.registry_for_frontend(states)


def _config_stub(chat_scope: bool) -> dict:
    """`/api/config` из РЕАЛЬНОГО каталога (items — минимальные, для страниц)."""
    from services import param_catalog as pc
    items = []
    for key, spec in sorted(pc.REGISTRY.items()):
        if getattr(spec, "hidden", False):
            continue
        items.append({
            "key": getattr(spec, "pg_key", None) or key,
            "value": ({"configured": True, "last4": "0000"}
                      if bool(getattr(spec, "secret", False))
                      else (False if spec.type == "bool" else "")),
            "category": spec.category,
            "secret": bool(getattr(spec, "secret", False)),
            "chat_source": "",
            "global_value": None,
            "title": getattr(spec, "title_ru", key) or key,
            "type": spec.type, "updated_at": None,
            "group": getattr(spec, "group", "") or "",
            "description": getattr(spec, "description", "") or "",
            "per_chat": bool(getattr(spec, "per_chat", False)),
            "progressive_level": "basic",
            "view_roles": [], "edit_roles": [], "chat_updated_at": None,
        })
    present = {it["category"] for it in items}
    groups = [{"id": g.id, "category": g.category, "title": g.title_ru,
               "description": g.description, "order": g.order}
              for g in pc.GROUPS if g.category in present]
    groups.sort(key=lambda g: g["order"])
    out = {"items": items, "groups": groups,
           "modules": _registry_payload(chat_scope)}
    if chat_scope:
        out["chat_id"] = CHAT_ID
        out["updated_at"] = "ts-chat-1"
        out["ctx"] = {"role_chat": "local_admin", "is_local_admin": True,
                      "is_global_admin": True, "is_dm": False}
    return out


CONFIG_GLOBAL = _config_stub(False)
CONFIG_CHAT = _config_stub(True)

API_STUBS = [
    ("/api/me", ME_JSON),
    ("/api/access/me", {"is_local_admin": True,
                        "permissions": {"sections": ["modules"]}}),
    ("/api/access/chats", [
        {"chat_id": CHAT_ID, "title": CHAT_TITLE, "is_dm": False,
         "photo_file_id": None, "access": "admin"},
    ]),
    ("/api/access/param_permissions", {"items": {}, "roles": []}),
    ("/api/roles", {"roles": [{"role_name": "user", "permissions": {}}]}),
    ("/api/admins", {"admins": []}),
    ("/api/status", {"bot": {"uptime_seconds": 3600, "state": "running"},
                     "server": {}, "llm": [], "context": {}}),
    ("/api/status/logs", {"logs": [], "levels": [], "counts": {}}),
    ("/api/status/key-history", {"providers": []}),
    ("/api/oversight/summary", {"chats": [], "totals": {}}),
    ("/api/oversight/dossier_feed", {"items": []}),
    ("/api/config/time", {"timezone": "Europe/Moscow", "chat_id": CHAT_ID,
                          "server_now": "2026-11-17T13:00:00+03:00",
                          "source": "chat"}),
    ("/api/config/timezones", {"timezones": ["UTC", "Europe/Moscow"]}),
    ("/api/workers/budget", {}),
    ("/api/info/guide", {"markdown": "", "updated_at": None}),
    ("/api/info", {"html": "", "updated_at": None, "canon_drift": False}),
]


def _stub_for(url: str):
    for marker, payload in API_STUBS:
        if url.split("?")[0].endswith(marker):
            return payload
    return {}


PROBE_JS = r"""
() => {
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return {x: r.x, y: r.y, w: r.width, h: r.height, top: r.top,
            bottom: r.bottom, left: r.left};
  };
  const cards = Array.from(document.querySelectorAll('.module-catalog [data-mod]'));
  const catalog = document.querySelector('.module-catalog');
  const groups = Array.from(document.querySelectorAll('.module-catalog [data-module-group]'));
  const rows = {};
  cards.forEach((c) => { const r = rect(c); rows[r.top] = (rows[r.top] || 0) + 1; });
  const firstGroup = groups[0];
  const firstCards = firstGroup
    ? Array.from(firstGroup.querySelectorAll('[data-mod]')).map(rect) : [];
  const tabs = document.querySelector('[data-workspace-tabs]');
  const overview = document.querySelector('[data-workspace-overview]');
  const tabBtns = Array.from(document.querySelectorAll('[data-workspace-tabs] button'))
    .map((b) => ({id: b.getAttribute('data-workspace-tab'),
                  h: rect(b).h,
                  current: b.getAttribute('aria-current'),
                  selected: b.getAttribute('aria-selected')}));
  const viewportH = window.innerHeight;
  const vw = window.innerWidth;
  return {
    vw,
    catalogW: catalog ? Math.round(rect(catalog).w) : null,
    scrollWidth: document.documentElement.scrollWidth,
    cards: cards.map((c) => Object.assign(
      {id: c.getAttribute('data-mod'),
       order: c.getAttribute('data-module-order'),
       state: (c.querySelector('[data-module-state]') || {}).textContent || ''},
      rect(c))),
    groupIds: groups.map((g) => g.getAttribute('data-module-group')),
    groupTitles: groups.map((g) => (g.querySelector('.module-group-title') || {})
      .textContent || ''),
    firstRowColumns: firstCards.filter((r) => r.top === firstCards[0].top).length,
    visibleInViewport: cards.filter((c) => rect(c).bottom <= viewportH + 1).length,
    caption: (document.querySelector('[data-module-caption]') || {}).textContent || '',
    h1: Array.from(document.querySelectorAll('h1')).map((h) => h.textContent.trim()),
    breadcrumb: (document.querySelector('[data-workspace-breadcrumb]') || {})
      .textContent || '',
    tabs: tabBtns,
    tabsBox: tabs ? rect(tabs) : null,
    overviewBox: overview ? rect(overview) : null,
    hasGlobal: !!document.querySelector('[data-workspace-global-toggle]'),
    hasChat: !!document.querySelector('[data-workspace-chat-tristate]'),
    hasNoToggle: !!document.querySelector('[data-workspace-no-toggle]'),
    chips: Array.from(document.querySelectorAll('[data-workspace-chips] .workspace-chip'))
      .map((c) => (c.textContent || '').trim()),
    tabpanel: !!document.querySelector('[role="tabpanel"]'),
    globalDisabled: (() => {
      const el = document.querySelector('[data-module-global-toggle]');
      return el ? el.disabled : null;
    })(),
  };
}
"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    httpd = _start_server()
    failures = []
    report = {"viewports": {}, "pages": {}, "flows": {}, "shots": SHOTS}
    posts = []
    chat_scope = {"on": False}
    conflict_mode = {"on": False}

    def check(cond, msg, bucket):
        if not cond:
            failures.append(msg)
            bucket.append(msg)
        return cond

    def _route(route):
        req = route.request
        url = req.url.split("?")[0]
        if url.endswith("/api/config") and req.method == "POST":
            body = req.post_data or ""
            posts.append({"body": body,
                          "chat": (req.headers or {}).get("x-chat-id")})
            if conflict_mode["on"] and "flags.summary_enabled" in body:
                route.fulfill(
                    status=409, content_type="application/json",
                    body=json.dumps({"detail": {
                        "code": "conflict", "applied": [],
                        "conflicting": ["flags.summary_enabled"],
                        "current_updated_at": "ts-server-2"}}))
                return
            keys = []
            try:
                keys = [it.get("key") for it in
                        (json.loads(body).get("items") or [])]
            except Exception:  # noqa: BLE001
                pass
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"saved": keys,
                                           "updated_at": "ts-chat-2"}))
            return
        if url.endswith("/gates") and req.method == "PUT":
            posts.append({"body": req.post_data or "", "gates": True})
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True}))
            return
        if url.endswith("/api/config"):
            payload = CONFIG_CHAT if (req.headers or {}).get("x-chat-id") \
                else CONFIG_GLOBAL
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_stub_for(url)))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (w, h) in VIEWPORTS:
            ctx = browser.new_context(viewport={"width": w, "height": h})
            ctx.add_init_script(TMA_STUB)
            ctx.route("**/api/**", _route)
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e, b=errs: b.append(str(e)[:300]))
            page.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
                      wait_until="load")
            try:
                page.wait_for_selector(".module-catalog [data-mod]", timeout=9000)
            except Exception:  # noqa: BLE001
                failures.append(f"{w}: каталог не отрендерился")
            page.wait_for_timeout(500)
            probe = page.evaluate(PROBE_JS)
            vp = {"probe": probe, "errors": errs}
            report["viewports"][f"{w}x{h}"] = vp
            bucket = vp["errors"]
            try:
                check(len(probe["cards"]) == 21,
                      f"{w}: {len(probe['cards'])} карточек вместо 21", bucket)
                orders = [int(c["order"]) for c in probe["cards"]]
                check(orders == list(range(1, 22)),
                      f"{w}: DOM-порядок != catalog_order: {orders}", bucket)
                check(len(probe["groupIds"]) == 5,
                      f"{w}: групп {len(probe['groupIds'])} вместо 5", bucket)
                check(probe["groupIds"] == ["communication", "memory",
                                           "autonomy", "media", "system"],
                      f"{w}: порядок групп {probe['groupIds']}", bucket)
                want_cols = EXPECT_COLUMNS[w]
                check(probe["firstRowColumns"] == want_cols,
                      f"{w}: колонок {probe['firstRowColumns']} вместо "
                      f"{want_cols}", bucket)
                if w >= 390:
                    bad = [c for c in probe["cards"]
                           if not (131 <= c["h"] <= 165)]
                    check(not bad,
                          f"{w}: высота карточек вне 132–164: "
                          f"{[(c['id'], round(c['h'], 1)) for c in bad][:4]}",
                          bucket)
                check(probe["scrollWidth"] <= probe["vw"] + 1,
                      f"{w}: горизонтальный скролл "
                      f"({probe['scrollWidth']} > {probe['vw']})", bucket)
                if w == 1280:
                    check(probe["visibleInViewport"] >= 8,
                          f"1280: в первом viewport "
                          f"{probe['visibleInViewport']} карточек (<8)", bucket)
                check("21 модуль" in probe["caption"],
                      f"{w}: caption «{probe['caption'].strip()}»", bucket)
                # Тексты состояний из осей DTO (negative states).
                by_id = {c["id"]: c for c in probe["cards"]}
                check("Нет права смотреть" in by_id["mod_budgets"]["state"],
                      f"{w}: can_read=false не показан", bucket)
                check("Выключено" in by_id["mod_web"]["state"],
                      f"{w}: desired=false не «Выключено»", bucket)
                check("сейчас не работает: нет провайдера"
                      in by_id["mod_search"]["state"],
                      f"{w}: ready=false без причины", bucket)
                check("аварийным переключателем"
                      in by_id["mod_checkup"]["state"],
                      f"{w}: emergency_block не показан", bucket)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{w}: probe error {exc}")
            page.screenshot(path=os.path.join(SHOTS, f"catalog-{w}.png"),
                            full_page=False)
            ctx.close()

        # ── Страницы модулей (один shell) ────────────────────────────────
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script(TMA_STUB)
        ctx.route("**/api/**", _route)
        page = ctx.new_page()
        page.on("pageerror", lambda e: failures.append("pageerror: " + str(e)[:200]))
        for slug, expect in [
            ("summary", {"global": True, "chat": True, "no_toggle": False}),
            ("nostalgia", {"global": True, "chat": True, "no_toggle": False}),
            ("time", {"global": False, "chat": False, "no_toggle": True}),
        ]:
            page.goto("http://127.0.0.1:%d/web/index.html#/modules/%s"
                      % (PORT, slug), wait_until="load")
            try:
                page.wait_for_selector("[data-workspace-head]", timeout=9000)
            except Exception:  # noqa: BLE001
                failures.append(f"{slug}: шапка модуля не отрендерилась")
                continue
            page.wait_for_timeout(350)
            probe = page.evaluate(PROBE_JS)
            report["pages"][slug] = probe
            bucket = []
            check("Модули" in probe["breadcrumb"] and "/" in probe["breadcrumb"],
                  f"{slug}: нет крошки «Модули / …»", bucket)
            check(len(probe["h1"]) == 1,
                  f"{slug}: H1 не один ({probe['h1']})", bucket)
            check(probe["hasGlobal"] is expect["global"],
                  f"{slug}: GLOBAL-контрол {probe['hasGlobal']}", bucket)
            check(probe["hasChat"] is expect["chat"],
                  f"{slug}: CHAT tri-state {probe['hasChat']}", bucket)
            check(probe["hasNoToggle"] is expect["no_toggle"],
                  f"{slug}: «Без тумблера» {probe['hasNoToggle']}", bucket)
            if slug == "time":
                # Policy-экран: вкладок нет (design §2.4), роль tabpanel не
                # применяется — единственный экран редактора.
                check(len(probe["tabs"]) == 0,
                      f"time: у policy-экрана появились табы", bucket)
            else:
                check(len(probe["tabs"]) >= 2, f"{slug}: табов < 2", bucket)
                for t in probe["tabs"]:
                    check(38 <= t["h"] <= 44,
                          f"{slug}: таб {t['id']} высотой {round(t['h'], 1)}",
                          bucket)
                check(sum(1 for t in probe["tabs"]
                          if t["current"] == "page") == 1,
                      f"{slug}: aria-current не у одного таба", bucket)
                check(probe["tabpanel"], f"{slug}: нет role=tabpanel", bucket)
            if probe["tabsBox"] and probe["overviewBox"]:
                gap = probe["overviewBox"]["top"] - probe["tabsBox"]["bottom"]
                check(16 <= gap <= 24,
                      f"{slug}: контент через {round(gap, 1)} px от табов",
                      bucket)
            check(probe["scrollWidth"] <= probe["vw"] + 1,
                  f"{slug}: горизонтальный скролл", bucket)
            if slug != "time":
                check(len(probe["chips"]) >= 4,
                      f"{slug}: чипов осей {len(probe['chips'])}", bucket)
                for chip in probe["chips"]:
                    check(len(chip.strip()) > 6,
                          f"{slug}: чип без текста («{chip}»)", bucket)
            failures.extend(bucket)
            page.screenshot(path=os.path.join(SHOTS, f"page-{slug}-1280.png"))

        # ── Клик по телу vs контрол ─────────────────────────────────────
        page.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
                  wait_until="load")
        page.wait_for_selector(".module-catalog [data-mod]", timeout=9000)
        page.wait_for_timeout(300)
        before = page.evaluate("() => location.hash")
        # Начальный scope — чат (есть доступные чаты): карточка пишет ТОЛЬКО
        # свою область → CHAT tri-state, клик по нему не навигирует.
        page.click('.module-catalog [data-mod="mod_summary"] '
                   '[data-module-chat-tristate="inherit"]')
        page.wait_for_timeout(400)
        after_control = page.evaluate("() => location.hash")
        report["flows"]["control_click"] = {"before": before,
                                            "after": after_control}
        check(after_control == before,
              "клик по чатовому контролу навигирует "
              "(должен остаться в каталоге)", failures)
        # GLOBAL scope: карточка показывает ГЛОБАЛЬНЫЙ тумблер (И-1).
        page.click(".scope-trigger")
        page.click(".scope-option:has-text('Весь бот')")
        page.wait_for_timeout(600)
        has_global = page.evaluate(
            "() => !!document.querySelector("
            "'.module-catalog [data-module-global-toggle]')")
        report["flows"]["global_toggle"] = has_global
        check(has_global, "global scope: нет GLOBAL-тумблера в карточке",
              failures)
        page.click(".scope-trigger")
        page.click(".scope-option:has-text('%s')" % CHAT_TITLE)
        page.wait_for_timeout(500)
        page.click('.module-catalog [data-mod="mod_summary"] .module-card-head')
        page.wait_for_timeout(450)
        after_body = page.evaluate("() => location.hash")
        report["flows"]["body_click"] = after_body
        check(after_body == "#/modules/summary",
              f"клик по телу не открыл модуль ({after_body})", failures)

        # ── 409 на CHAT tri-state (param-путь) ──────────────────────────
        page.goto("http://127.0.0.1:%d/web/index.html#/modules/summary"
                  % PORT, wait_until="load")
        page.reload(wait_until="load")
        page.wait_for_selector("[data-workspace-head]", timeout=9000)
        page.wait_for_timeout(300)
        chat_scope["on"] = True
        conflict_mode["on"] = True
        posts.clear()
        page.click("[data-workspace-chat-tristate='off']")
        page.wait_for_timeout(900)
        banner = page.evaluate(
            "() => (document.querySelector('[data-workspace-save-error]')||{})"
            ".textContent || ''")
        toasts = page.evaluate(
            "() => Array.from(document.querySelectorAll('.toast, [data-toast]'))"
            ".map(t => t.textContent || '')")
        report["flows"]["409"] = {"banner": banner, "toasts": toasts,
                                  "posts": list(posts)}
        check("Настройка изменилась в другом окне" in banner,
              f"409: баннера нет («{banner.strip()}»)", failures)
        check(len(posts) == 1, f"409: POST-ов {len(posts)} вместо 1", failures)
        check(not any("Настройка сохранена" in t for t in toasts),
              "409: ложный тост «Настройка сохранена»", failures)
        page.screenshot(path=os.path.join(SHOTS, "page-chat-1280.png"))

        browser.close()
    httpd.shutdown()

    report["failures"] = failures
    try:
        with open(os.path.join(SHOTS, "m4a-e2e-report.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
    except Exception as exc:  # noqa: BLE001
        print("[e2e] report write failed:", exc)
    print(json.dumps({"failures": failures,
                      "flows": report["flows"]}, ensure_ascii=False,
                     indent=1)[:12000])
    print("M4A-CATALOG-E2E " + ("FAIL" if failures else "OK")
          + f" | failures={len(failures)} | shots={SHOTS}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
