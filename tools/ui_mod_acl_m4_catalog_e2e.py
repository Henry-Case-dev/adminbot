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
    gets = []
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
            gets.append((req.headers or {}).get("x-chat-id"))
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
                # D2: подпись CHAT читаема — без ellipsis-обрезки до 1–3
                # символов; перенос разрешён, overflow запрещён.
                labels = page.evaluate(
                    "() => Array.from(document.querySelectorAll("
                    "'.module-catalog .module-control-row__label'))"
                    ".map(el => ({w: el.clientWidth, sw: el.scrollWidth,"
                    " t: (el.textContent || '').trim()}))")
                bad_labels = [l for l in labels
                              if l["t"] and (l["sw"] > l["w"] + 1
                                             or l["w"] < 60)]
                check(not bad_labels,
                      f"{w}: подпись CHAT обрезана: {bad_labels[:2]}", bucket)
                # D3: can_read=false — карточка только с отказом.
                denied = page.evaluate(
                    "() => { const c = document.querySelector("
                    "'.module-catalog [data-mod=\"mod_budgets\"]');"
                    "return c ? {denied: !!c.querySelector("
                    "'[data-module-denied]'), ctrl: !!c.querySelector("
                    "'[data-module-global-toggle], [data-module-chat-tristate]')}"
                    " : null; }")
                check(denied and denied["denied"] and not denied["ctrl"],
                      f"{w}: can_read=false карточка показывает контрол", bucket)
                # Тексты состояний из осей DTO (negative states).
                by_id = {c["id"]: c for c in probe["cards"]}
                check("Нет доступа к этому модулю"
                      in by_id["mod_budgets"]["state"],
                      f"{w}: can_read=false отказ не показан", bucket)
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
                check(probe["tabpanel"],
                      f"{slug}: role=tabpanel только у Обзора", bucket)
            # D7: no-master — без фиктивного GLOBAL switch.
            if slug == "time":
                check(not probe["hasGlobal"] and not probe["hasChat"],
                      "time: не должно быть switch/tri-state", bucket)
                no_toggle_n = page.evaluate(
                    "() => (document.querySelector('[data-workspace-head]')"
                    ".innerText.match(/Без тумблера/g) || []).length")
                check(no_toggle_n == 1,
                      f"time: «Без тумблера» встречается {no_toggle_n} раз",
                      bucket)
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
        page.click('.module-catalog [data-mod=mod_summary] '
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
        page.click('.module-catalog [data-mod=mod_summary] .module-card-head')
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
        gets.clear()
        page.click("[data-workspace-chat-tristate='off']")
        page.wait_for_timeout(900)
        conflict = page.evaluate(
            "() => { const b = document.querySelector("
            "'[data-workspace-conflict]');"
            "return b ? {text: b.innerText,"
            " apply: !!b.querySelector('[data-workspace-conflict-apply]'),"
            " load: !!b.querySelector('[data-workspace-conflict-server-load]')}"
            " : null; }")
        toasts = page.evaluate(
            "() => Array.from(document.querySelectorAll('.toast, [data-toast]'))"
            ".map(t => t.textContent || '')")
        report["flows"]["409"] = {"conflict": conflict, "toasts": toasts,
                                  "posts": list(posts), "gets": len(gets)}
        check(conflict and "Настройка изменилась в другом окне"
              in conflict["text"], f"409: нет баннера diff ({conflict})",
              failures)
        check(conflict and conflict["apply"] and conflict["load"],
              "409: нет обеих кнопок выбора", failures)
        check(conflict and "Ваше: Выключить" in conflict["text"]
              and "На сервере: Включить" in conflict["text"],
              "409: diff «ваше/на сервере» не показан", failures)
        check(len(posts) == 1, f"409: POST-ов {len(posts)} вместо 1", failures)
        check(len(gets) == 1,
              f"409: авто-перезагрузок {len(gets) - 1} (ожидался только diff-GET)",
              failures)
        check(not any("Настройка сохранена" in t for t in toasts),
              "409: ложный тост «Настройка сохранена»", failures)
        page.screenshot(path=os.path.join(SHOTS, "page-chat-1280.png"))

        # D4 «Применить свою» → ровно один явный повтор.
        conflict_mode["on"] = False
        posts.clear()
        page.click("[data-workspace-conflict-apply]")
        page.wait_for_timeout(900)
        applied = page.evaluate(
            "() => !document.querySelector('[data-workspace-conflict]')")
        toasts = page.evaluate(
            "() => Array.from(document.querySelectorAll('.toast, [data-toast]'))"
            ".map(t => t.textContent || '')")
        report["flows"]["409_apply"] = {"posts": len(posts),
                                        "cleared": applied}
        check(len(posts) == 1, f"409 apply: POST-ов {len(posts)} вместо 1",
              failures)
        check(applied, "409 apply: конфликт не снят", failures)
        check(any("Настройка сохранена" in t for t in toasts),
              "409 apply: нет подтверждения сохранения", failures)

        # D4 «Загрузить серверное» → без POST, один reload.
        page.click("[data-workspace-chat-tristate='inherit']")
        page.wait_for_timeout(500)
        conflict_mode["on"] = True
        posts.clear()
        gets.clear()
        page.click("[data-workspace-chat-tristate='on']")
        page.wait_for_timeout(700)
        check(bool(page.query_selector("[data-workspace-conflict]")),
              "409 load: конфликт не показан", failures)
        conflict_mode["on"] = False
        posts.clear()
        gets.clear()
        page.click("[data-workspace-conflict-server-load]")
        page.wait_for_timeout(800)
        check(len(posts) == 0, "409 load: отправлен лишний POST", failures)
        check(len(gets) >= 1, "409 load: нет перечитывания серверного",
              failures)
        check(not page.query_selector("[data-workspace-conflict]"),
              "409 load: конфликт не снят", failures)

        # D3: страница модуля с can_read=false — только отказ.
        page.goto("http://127.0.0.1:%d/web/index.html#/modules/budgets"
                  % PORT, wait_until="load")
        page.wait_for_selector("[data-workspace-head]", timeout=9000)
        page.wait_for_timeout(400)
        denied_page = page.evaluate(
            "() => ({denied: !!document.querySelector('[data-workspace-denied]'),"
            " chips: document.querySelectorAll("
            "'[data-workspace-chips] .workspace-chip').length,"
            " ctrl: !!document.querySelector("
            "'[data-workspace-global-toggle], [data-workspace-chat-tristate]')})")
        report["flows"]["denied_page"] = denied_page
        check(denied_page["denied"] and denied_page["chips"] == 0
              and not denied_page["ctrl"],
              f"403: страница модуля показывает данные ({denied_page})",
              failures)

        # D7: embeddings в GLOBAL scope — без фиктивного master-switch.
        page.click(".scope-trigger")
        page.click(".scope-option:has-text('Весь бот')")
        page.wait_for_timeout(600)
        page.goto("http://127.0.0.1:%d/web/index.html#/modules/embeddings"
                  % PORT, wait_until="load")
        page.wait_for_selector("[data-workspace-head]", timeout=9000)
        page.wait_for_timeout(400)
        emb = page.evaluate(
            "() => ({global: !!document.querySelector("
            "'[data-workspace-global-toggle]'),"
            " chat: !!document.querySelector('[data-workspace-chat-tristate]'),"
            " noMaster: !!document.querySelector('[data-workspace-no-toggle]')})")
        report["flows"]["embeddings_global"] = emb
        check(not emb["global"], "embeddings: фиктивный GLOBAL switch",
              failures)
        check(emb["chat"], "embeddings: chat-use tri-state должен быть виден",
              failures)

        # ── D1: touch 390 — hit-area НЕ перекрывает соседнюю кнопку ──────
        tctx = browser.new_context(viewport={"width": 390, "height": 844},
                                   has_touch=True)
        tctx.add_init_script(TMA_STUB)
        tctx.route("**/api/**", _route)
        tpage = tctx.new_page()
        tpage.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
                   wait_until="load")
        tpage.wait_for_selector(".module-catalog [data-mod]", timeout=9000)
        tpage.wait_for_timeout(500)

        def _btn_rect(kind):
            return tpage.evaluate(
                "() => { const b = document.querySelector("
                "'.module-catalog [data-mod=\"mod_summary\"] "
                "[data-module-chat-tristate=\"%s\"]');"
                "const r = b.getBoundingClientRect();"
                "return {l: r.left, r: r.right, y: r.top + r.height / 2}; }"
                % kind)

        posts.clear()
        on_rect = _btn_rect("on")
        tpage.touchscreen.tap(on_rect["r"] - 2, on_rect["y"])
        tpage.wait_for_timeout(800)
        vals = []
        for item in posts:
            try:
                vals.append(json.loads(item["body"])["items"][0]["value"])
            except Exception:  # noqa: BLE001
                pass
        report["flows"]["touch_on_right_edge"] = {"posts": len(posts),
                                                  "values": vals}
        check(len(posts) == 1 and vals == [True],
              f"D1: тап у правого края «Включить» → {vals} (ожидалось [true])",
              failures)

        posts.clear()
        off_rect = _btn_rect("off")
        tpage.touchscreen.tap(off_rect["l"] + 2, off_rect["y"])
        tpage.wait_for_timeout(800)
        vals = []
        for item in posts:
            try:
                vals.append(json.loads(item["body"])["items"][0]["value"])
            except Exception:  # noqa: BLE001
                pass
        report["flows"]["touch_off_left_edge"] = {"posts": len(posts),
                                                  "values": vals}
        check(len(posts) == 1 and vals == [False],
              f"D1: тап у левого края «Выключить» → {vals} (ожидалось [false])",
              failures)
        tctx.close()

        # ── D6: видимый badge GLOBAL◄►CHAT ──────────────────────────────
        def _variant(global_off):
            import copy
            cfg = copy.deepcopy(CONFIG_CHAT)
            for card in cfg["modules"]:
                if card.get("id") != "summary":
                    continue
                st = card.get("state") or {}
                st.update({"source": "chat", "chat_state":
                           "on" if global_off else "off",
                           "desired": bool(global_off),
                           "global_value": (not global_off),
                           "effective_runtime": bool(global_off)})
                card["state"] = st
            return cfg

        for global_off, want, fname in [
                (True, "Включено отдельно для этого чата",
                 "d6-global-off-chat-on"),
                (False, "Выключено в этом чате", "d6-global-on-chat-off")]:
            vctx = browser.new_context(viewport={"width": 1280, "height": 800})
            vctx.add_init_script(TMA_STUB)
            payload = _variant(global_off)

            def _make_vroute(vpayload):
                def _vroute(route):
                    url = route.request.url.split("?")[0]
                    if url.endswith("/api/config"):
                        route.fulfill(
                            status=200, content_type="application/json",
                            body=json.dumps(
                                vpayload if (route.request.headers or {})
                                .get("x-chat-id") else CONFIG_GLOBAL))
                        return
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps(_stub_for(url)))
                return _vroute

            vctx.route("**/api/**", _make_vroute(payload))
            vpage = vctx.new_page()
            _verrs = []
            vpage.on("pageerror", lambda e, b=_verrs: b.append(str(e)[:200]))
            vpage.goto("http://127.0.0.1:%d/web/index.html#/modules/summary"
                       % PORT, wait_until="load")
            vpage.wait_for_selector("[data-workspace-head]", timeout=9000)
            vpage.wait_for_timeout(400)
            badge = vpage.evaluate(
                "() => (document.querySelector("
                "'[data-workspace-effective]')||{}).innerText || ''")
            report["flows"][fname] = badge
            check(want in badge,
                  f"D6: badge «{want}» не показан («{badge.strip()}»)",
                  failures)
            vpage.screenshot(path=os.path.join(SHOTS, fname + ".png"))
            vctx.close()

        # ── D8: 403 каталога — отказ раздела, не пустой поиск ───────────
        cctx = browser.new_context(viewport={"width": 1280, "height": 800})
        cctx.add_init_script(TMA_STUB)

        def _route_403(route):
            url = route.request.url.split("?")[0]
            if url.endswith("/api/config") and route.request.method == "GET":
                route.fulfill(status=403, content_type="application/json",
                              body=json.dumps({"detail": "нет доступа"}))
                return
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(_stub_for(url)))

        cctx.route("**/api/**", _route_403)
        cpage = cctx.new_page()
        cpage.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
                   wait_until="load")
        cpage.wait_for_timeout(900)
        denied = cpage.evaluate(
            "() => { const e = document.querySelector('[data-module-empty]');"
            "return {text: e ? e.innerText : '',"
            " clear: !!document.querySelector('[data-module-clear-search]')}; }")
        report["flows"]["catalog_403"] = denied
        check("Нет доступа к разделу «Модули»" in denied["text"],
              f"D8: 403 текст неверный («{denied['text'].strip()}»)", failures)
        check(not denied["clear"], "D8: кнопка «Очистить поиск» при 403",
              failures)
        cctx.close()

        # ── R1: badge-state — карточка/ряд 132–164 ──────────────────────
        def _measure_cards(vpage):
            return vpage.evaluate(
                "() => { const cards = Array.from(document.querySelectorAll("
                "'.module-catalog [data-mod]'));"
                "const hs = cards.map(c => c.getBoundingClientRect().height);"
                "const tops = {}; cards.forEach(c => { const r = "
                "c.getBoundingClientRect(); const k = Math.round(r.top);"
                "tops[k] = Math.max(tops[k] || 0, r.height); });"
                "return {maxCard: Math.max.apply(null, hs),"
                " maxRow: Math.max.apply(null, Object.values(tops)),"
                " cards: hs.length}; }")

        badge_cfg = _variant(True)
        for bw, bh in [(1440, 900), (1280, 800), (390, 844), (320, 568)]:
            bctx = browser.new_context(viewport={"width": bw, "height": bh})
            bctx.add_init_script(TMA_STUB)

            def _make_badge_route(cfg):
                def _badge_route(route):
                    url = route.request.url.split("?")[0]
                    if url.endswith("/api/config"):
                        route.fulfill(
                            status=200, content_type="application/json",
                            body=json.dumps(
                                cfg if (route.request.headers or {})
                                .get("x-chat-id") else CONFIG_GLOBAL))
                        return
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps(_stub_for(url)))
                return _badge_route

            bctx.route("**/api/**", _make_badge_route(badge_cfg))
            bpage = bctx.new_page()
            bpage.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
                       wait_until="load")
            bpage.wait_for_selector(".module-catalog [data-mod]", timeout=9000)
            bpage.wait_for_timeout(500)
            badge_meas = _measure_cards(bpage)
            badge_badge = bpage.evaluate(
                "() => (document.querySelector("
                "'.module-catalog [data-mod=mod_summary] "
                "[data-module-effective]')||{}).innerText || ''")
            report["flows"]["r1_badge_%dx%d" % (bw, bh)] = badge_meas
            check(131 <= badge_meas["maxCard"] <= 165
                  and badge_meas["maxRow"] <= 165,
                  f"R1 {bw}: badge-state height card={badge_meas['maxCard']:.1f} "
                  f"row={badge_meas['maxRow']:.1f}", failures)
            check("Отдельно для чата" in badge_badge,
                  f"R1 {bw}: inline badge не показан («{badge_badge}»)",
                  failures)
            bctx.close()

        # ── R2: conflict-state карточки/ряда ≤164; diff — в workspace ────
        rctx = browser.new_context(viewport={"width": 1440, "height": 900})
        rctx.add_init_script(TMA_STUB)
        rctx.route("**/api/**", _route)
        rpage = rctx.new_page()
        rpage.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
                   wait_until="load")
        rpage.wait_for_selector(".module-catalog [data-mod]", timeout=9000)
        rpage.wait_for_timeout(400)
        conflict_mode["on"] = True
        posts.clear()
        rpage.click('.module-catalog [data-mod=mod_summary] '
                    '[data-module-chat-tristate="off"]')
        rpage.wait_for_timeout(900)
        r_meas = _measure_cards(rpage)
        r_conf = rpage.evaluate(
            "() => ({compact: !!document.querySelector("
            "'.module-catalog [data-mod=mod_summary] [data-module-conflict]'),"
            " link: !!document.querySelector("
            "'.module-catalog [data-mod=mod_summary] "
            "[data-module-conflict-open]'),"
            " diffInCard: !!document.querySelector("
            "'.module-catalog [data-mod=mod_summary] .module-conflict__diff')})")
        report["flows"]["r2_conflict_card"] = dict(r_meas, **r_conf,
                                                   posts=len(posts))
        check(r_meas["maxCard"] <= 164 and r_meas["maxRow"] <= 164,
              f"R2: conflict-state card={r_meas['maxCard']:.1f} "
              f"row={r_meas['maxRow']:.1f}", failures)
        check(r_conf["compact"] and r_conf["link"] and not r_conf["diffInCard"],
              f"R2: карточка не компактна ({r_conf})", failures)
        check(len(posts) == 1, f"R2: POST-ов {len(posts)} вместо 1", failures)
        rpage.click('.module-catalog [data-mod=mod_summary] '
                    '[data-module-conflict-open]')
        rpage.wait_for_timeout(700)
        r_ws = rpage.evaluate(
            "() => ({hash: location.hash,"
            " diff: !!document.querySelector('[data-workspace-conflict]'),"
            " apply: !!document.querySelector('[data-workspace-conflict-apply]'),"
            " load: !!document.querySelector("
            "'[data-workspace-conflict-server-load]')})")
        report["flows"]["r2_conflict_workspace"] = r_ws
        check(r_ws["hash"] == "#/modules/summary" and r_ws["diff"]
              and r_ws["apply"] and r_ws["load"],
              f"R2: diff/выбор недоступны в workspace ({r_ws})", failures)
        conflict_mode["on"] = False
        rctx.close()

        # R2/D2: мобильная 44-px hit-area «Разрешить» (390/320)
        for cw, ch in [(390, 844), (320, 568)]:
            c2 = browser.new_context(viewport={"width": cw, "height": ch},
                                     has_touch=True)
            c2.add_init_script(TMA_STUB)
            c2.route("**/api/**", _route)
            cp = c2.new_page()
            cp.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
                    wait_until="load")
            cp.wait_for_selector(".module-catalog [data-mod]", timeout=9000)
            cp.wait_for_timeout(400)
            conflict_mode["on"] = True
            posts.clear()
            cp.click('.module-catalog [data-mod=mod_summary] '
                     '[data-module-chat-tristate="off"]')
            cp.wait_for_timeout(900)
            m2 = cp.evaluate(
                "() => { const row = document.querySelector("
                "'.module-catalog [data-mod=mod_summary] [data-module-conflict]');"
                "const btn = document.querySelector("
                "'.module-catalog [data-mod=mod_summary] "
                "[data-module-conflict-open]');"
                "const cards = Array.from(document.querySelectorAll("
                "'.module-catalog [data-mod]'));"
                "const tops = {}; cards.forEach(c => { const r = "
                "c.getBoundingClientRect(); const k = Math.round(r.top);"
                "tops[k] = Math.max(tops[k] || 0, r.height); });"
                "if (!row || !btn) return null;"
                "const rb = row.getBoundingClientRect();"
                "const bb = btn.getBoundingClientRect();"
                "const hit = document.elementFromPoint("
                "bb.left + bb.width / 2, bb.top + bb.height / 2);"
                "return {rowH: rb.height, btnH: bb.height,"
                " visibleHit: !!(hit && (hit === btn || btn.contains(hit))),"
                " maxCard: Math.max.apply(null, cards.map(c => "
                "c.getBoundingClientRect().height)),"
                " maxRow: Math.max.apply(null, Object.values(tops))}; }")
            report["flows"]["r2_mobile_%d" % cw] = dict(
                m2 or {}, posts=len(posts))
            check(m2 and m2["btnH"] >= 44 and m2["rowH"] >= 44
                  and m2["visibleHit"],
                  f"D2 {cw}: hit-area «Разрешить» {m2}", failures)
            check(m2 and m2["maxCard"] <= 164 and m2["maxRow"] <= 164,
                  f"D2 {cw}: card/row {m2 and m2['maxCard']}/"
                  f"{m2 and m2['maxRow']}", failures)
            check(len(posts) == 1,
                  f"D2 {cw}: POST-ов {len(posts)} вместо 1", failures)
            cp.click('.module-catalog [data-mod=mod_summary] '
                     '[data-module-conflict-open]')
            cp.wait_for_timeout(700)
            ws = cp.evaluate(
                "() => ({hash: location.hash,"
                " diff: !!document.querySelector('[data-workspace-conflict]'),"
                " apply: !!document.querySelector("
                "'[data-workspace-conflict-apply]'),"
                " load: !!document.querySelector("
                "'[data-workspace-conflict-server-load]')})")
            report["flows"]["r2_mobile_ws_%d" % cw] = ws
            check(ws["hash"] == "#/modules/summary" and ws["diff"]
                  and ws["apply"] and ws["load"],
                  f"D2 {cw}: «Разрешить» не открыл diff/выбор ({ws})",
                  failures)
            conflict_mode["on"] = False
            c2.close()

        # ── R3: «Время» — один текст в карточке (chat и global) ─────────
        def _time_count(vpage):
            return vpage.evaluate(
                "() => { const c = document.querySelector("
                "'.module-catalog [data-mod=mod_time]');"
                "return c ? (c.innerText.match(/Без тумблера/g) || []).length"
                " : -1; }")

        tpage2 = page
        tpage2.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
                    wait_until="load")
        tpage2.wait_for_selector(".module-catalog [data-mod]", timeout=9000)
        tpage2.wait_for_timeout(400)
        chat_time_n = _time_count(tpage2)
        tpage2.click(".scope-trigger")
        tpage2.click(".scope-option:has-text('Весь бот')")
        tpage2.wait_for_timeout(600)
        global_time_n = _time_count(tpage2)
        report["flows"]["r3_time_labels"] = {"chat": chat_time_n,
                                             "global": global_time_n}
        check(chat_time_n == 1 and global_time_n == 1,
              f"R3: «Время» дублирует «Без тумблера» "
              f"(chat={chat_time_n}, global={global_time_n})", failures)

        # ── R4/D1: workspace tri-state — 44 px и полные подписи ─────────
        for mw, mh in [(1440, 900), (1280, 800), (390, 844), (320, 568)]:
            mctx = browser.new_context(viewport={"width": mw, "height": mh})
            mctx.add_init_script(TMA_STUB)
            mctx.route("**/api/**", _route)
            mpage = mctx.new_page()
            mpage.goto("http://127.0.0.1:%d/web/index.html#/modules/summary"
                       % PORT, wait_until="load")
            mpage.wait_for_selector("[data-workspace-head]", timeout=9000)
            mpage.wait_for_timeout(500)
            r4 = mpage.evaluate(
                "() => { const grp = document.querySelector("
                "'[data-workspace-chat-control] .module-tristate');"
                "const btns = Array.from(document.querySelectorAll("
                "'[data-workspace-chat-tristate]'));"
                "if (!grp || btns.length !== 3) return null;"
                "const on = btns.find(b => b.getAttribute("
                "'data-workspace-chat-tristate') === 'on');"
                "const off = btns.find(b => b.getAttribute("
                "'data-workspace-chat-tristate') === 'off');"
                "const a = on.getBoundingClientRect(), b = off.getBoundingClientRect();"
                "return {grpCW: grp.clientWidth, grpSW: grp.scrollWidth,"
                " onH: a.height, offH: b.height, overlapX: a.right - b.left,"
                " labels: btns.map(x => ({t: x.textContent.trim(),"
                " cw: x.clientWidth, sw: x.scrollWidth}))}; }")
            report["flows"]["r4_workspace_%dx%d" % (mw, mh)] = r4
            check(r4 and r4["grpSW"] <= r4["grpCW"] + 1,
                  f"D1 {mw}: tri-state обрезан "
                  f"(client={r4 and r4['grpCW']}, scroll={r4 and r4['grpSW']})",
                  failures)
            check(r4 and all(l["sw"] <= l["cw"] + 1
                             for l in r4["labels"]),
                  f"D1 {mw}: подписи кнопок обрезаны ({r4 and r4['labels']})",
                  failures)
            if mw <= 767:
                check(r4 and r4["onH"] >= 44 and r4["offH"] >= 44,
                      f"D1 {mw}: workspace tri-state height {r4}", failures)
                check(r4 and r4["overlapX"] <= 1,
                      f"D1 {mw}: кнопки перекрываются по X ({r4})", failures)
            mctx.close()

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
