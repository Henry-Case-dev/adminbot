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

MOD-ACL-UX-01 M4A W2a (`MAC-S5-198`/`MAC-S5-OVW-01`/`MAC-AC-08`, 2.58.211):
  * дефолт bare-адреса: `search → settings`, `direct/sleep → overview`,
    явный `/overview` всегда уважается (К-1/К-2);
  * клавиатура: `ArrowRight/Left` без wrap, `Home/End`, ровно один
    `aria-current`, roving `tabindex`, `preventDefault` ТОЛЬКО обработанных
    ключей (записан `defaultPrevented`, Tab — false), фокус переезжает,
    контейнер не прокручивается, Tab выходит из полосы;
  * память: клик «Лимиты» → каталог → повторный вход и reload дают «Лимиты»;
    в localStorage только id (`scope|module → tab`); смена чата сохраняет
    вкладку, пишет ключ НОВОГО scope, не копирует чужие модули; у чата B
    своя вкладка, ключ чата A цел;
  * свежесть: футер карточки `[data-module-checked]` = `[data-workspace-checked]`
    страницы, нет «0 событий»/1970; на 320/390 футер не переполняется,
    «Открыть» не выезжает, высота карточки 132–164.

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
# W2a: второй чат — проверка изоляции памяти вкладок по scope
# (`chat:<id>|module`); сам каталог/страницы от числа чатов не зависят.
CHAT_ID2 = -1001234567891
CHAT_TITLE2 = "Second Chat"


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

# ── W2b-B1: журналы «Сна»/«Ностальгии» (существующие read-API) ─────────────
# 6 строк сна → «Обзор» показывает ровно 5, вкладка «История» — все 6.
# 3 строки ностальгии (sent/skipped/error) — фильтр по статусу сужает набор.
DREAM_ROWS = [
    {"id": 1, "chat_id": CHAT_ID, "run_at": 1794909600, "kind": "dream",
     "status": "ok", "tokens": 12},
    {"id": 2, "chat_id": CHAT_ID, "run_at": 1794909500, "kind": "deep",
     "status": "error", "tokens": 0},
    {"id": 3, "chat_id": CHAT_ID, "run_at": 1794909400, "kind": "dream",
     "status": "window_skip", "tokens": 0},
    {"id": 4, "chat_id": CHAT_ID2, "run_at": 1794909300, "kind": "dream",
     "status": "ok", "tokens": 8},
    {"id": 5, "chat_id": CHAT_ID2, "run_at": 1794909200, "kind": "dream",
     "status": "duplicate", "tokens": 0},
    {"id": 6, "chat_id": CHAT_ID, "run_at": 1794909100, "kind": "dream",
     "status": "budget_skip", "tokens": 0},
]
NOSTALGIA_ROWS = [
    {"id": 1, "chat_id": CHAT_ID, "ts": 1794909600, "kind": "nostalgia",
     "status": "sent", "fact_id": 11, "meta": {"reason": ""}},
    {"id": 2, "chat_id": CHAT_ID, "ts": 1794909500, "kind": "nostalgia",
     "status": "skipped", "fact_id": None, "meta": {"reason": "нет повода"}},
    {"id": 3, "chat_id": CHAT_ID2, "ts": 1794909400, "kind": "nostalgia",
     "status": "error", "fact_id": None, "meta": {"reason": "timeout"}},
    {"id": 4, "chat_id": CHAT_ID, "ts": 1794909300, "kind": "nostalgia",
     "status": "skipped", "fact_id": None, "meta": {"reason": "лимит"}},
]
# data | empty | denied | off | unavailable
HISTORY_MODE = {"dream": "data", "nostalgia": "data"}
HISTORY_GETS = {"dream": 0, "nostalgia": 0}
HISTORY_HOLD = {"dream": None, "nostalgia": None}


API_STUBS = [
    ("/api/me", ME_JSON),
    ("/api/access/me", {"is_local_admin": True,
                        "permissions": {"sections": ["modules"]}}),
    ("/api/access/chats", [
        {"chat_id": CHAT_ID, "title": CHAT_TITLE, "is_dm": False,
         "photo_file_id": None, "access": "admin"},
        {"chat_id": CHAT_ID2, "title": CHAT_TITLE2, "is_dm": False,
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
        if url.endswith("/api/memory/dream/log") \
                or url.endswith("/api/memory/nostalgia/log"):
            kind = "dream" if url.endswith("/api/memory/dream/log") \
                else "nostalgia"
            HISTORY_GETS[kind] += 1
            mode = HISTORY_MODE[kind]
            if mode == "denied":
                route.fulfill(status=403, content_type="application/json",
                              body=json.dumps({"detail": "нет доступа"}))
                return
            if mode == "off":
                route.fulfill(status=503, content_type="application/json",
                              body=json.dumps({"detail": "журнал выключен"}))
                return
            if mode == "unavailable":
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"available": False}))
                return
            if mode == "hold":
                HISTORY_HOLD[kind] = route
                return
            if mode == "hold_once":
                HISTORY_HOLD[kind] = route
                HISTORY_MODE[kind] = "data"
                return
            rows = [] if mode == "empty" else (
                DREAM_ROWS if kind == "dream" else NOSTALGIA_ROWS)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(rows))
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
            # MOD-ACL-UX-01 M4A W2a (К-2): bare `#/modules/<slug>` больше не
            # гарантирует «Обзор» (у summary/nostalgia дефолт — «Основные
            # настройки»). Панель/чипы/gap проверяются на ЯВНОМ `/overview`,
            # иначе проверка молча уехала бы на другую вкладку/исчезла.
            route = ("#/modules/%s" % slug) if slug == "time" \
                else ("#/modules/%s/overview" % slug)
            page.goto("http://127.0.0.1:%d/web/index.html%s"
                      % (PORT, route), wait_until="load")
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

        # ═══ W2a (MAC-S5-198 / MAC-S5-OVW-01 / MAC-AC-08) ═══════════════════
        # К-1/К-2: явный hash (включая `/overview`) побеждает; bare-адрес —
        # память → живой Обзор → «Основные настройки» → первый содержательный
        # → «Обзор». Предикат «живого Обзора» статический (без async-данных).
        WBASE = "http://127.0.0.1:%d/web/index.html" % PORT

        def _wstate(pg):
            return pg.evaluate(
                "() => { const cur = document.querySelector("
                "'[data-workspace-tabs] [data-workspace-tab][aria-current=page]');"
                "return {hash: location.hash,"
                " tab: cur ? cur.getAttribute('data-workspace-tab') : null,"
                " current: document.querySelectorAll("
                "'[data-workspace-tabs] [aria-current=page]').length}; }")

        def _wfocus(pg):
            return pg.evaluate(
                "() => { const a = document.activeElement;"
                "return {tab: a && a.getAttribute"
                " ? a.getAttribute('data-workspace-tab') : null,"
                " inStrip: !!(a && a.closest && a.closest('[data-workspace-tabs]')),"
                " scroll: window.scrollY}; }")

        def _wopen(pg, route, wait_head=True):
            pg.goto(WBASE + route, wait_until="load")
            if wait_head:
                pg.wait_for_selector("[data-workspace-head]", timeout=9000)
                pg.wait_for_timeout(420)

        wctx = browser.new_context(viewport={"width": 390, "height": 844})
        wctx.add_init_script(TMA_STUB)
        wctx.route("**/api/**", _route)
        wpage = wctx.new_page()
        werrs = []
        wpage.on("pageerror", lambda e, b=werrs: b.append(str(e)[:300]))
        report["flows"]["w2a_pageerrors"] = werrs
        wfails = []          # локальный bucket: check() не дублирует

        # ── W2a-1: дефолт (К-2) ──────────────────────────────────────────
        for wroute, want in [
                ("#/modules/search", "settings"),
                ("#/modules/direct", "overview"),
                ("#/modules/sleep", "overview"),
                ("#/modules/search/overview", "overview")]:
            _wopen(wpage, wroute)
            st = _wstate(wpage)
            report["flows"]["w2a_default_" + wroute] = st
            check(st["tab"] == want and st["current"] == 1,
                  f"W2a {wroute}: вкладка {st['tab']} вместо {want}"
                  f" (aria-current={st['current']})", wfails)

        # ── W2a-2: клавиатура (К-6) ──────────────────────────────────────
        _wopen(wpage, "#/modules/search/overview")
        strip_ids = wpage.evaluate(
            "() => Array.from(document.querySelectorAll("
            "'[data-workspace-tabs] [data-workspace-tab]'))"
            ".map(b => b.getAttribute('data-workspace-tab'))")
        k0 = wpage.evaluate(
            "() => { const a = document.querySelector("
            "'[data-workspace-tabs] [data-workspace-tab][aria-current=page]');"
            "a.focus();"
            "window.__w2aKeys = [];"
            "document.addEventListener('keydown', function (e) {"
            "  setTimeout(function () { window.__w2aKeys.push({"
            "    k: e.key, prevent: e.defaultPrevented}); }, 0);"
            "}, false);"
            "const scrollers = [document.querySelector('.scroll-area'),"
            " document.querySelector('main'), document.documentElement,"
            " document.body].filter(Boolean);"
            "let sc = scrollers.filter(function (e) {"
            "  return e.scrollHeight > e.clientHeight + 4; })[0] || null;"
            "if (!sc) {"
            "  const host = document.querySelector('main.scroll-area')"
            "    || document.querySelector('main') || null;"
            "  if (host) {"
            "    const spacer = document.createElement('div');"
            "    spacer.style.height = '2400px';"
            "    spacer.setAttribute('data-w2a-scroll-spacer', '1');"
            "    host.appendChild(spacer);"
            "    sc = host;"
            "  }"
            "}"
            "window.__w2aScroller = sc;"
            "if (sc) sc.scrollTop = Math.min(120, sc.scrollHeight - sc.clientHeight);"
            "return {h: a.getBoundingClientRect().height,"
            " scroll: sc ? sc.scrollTop : null,"
            " scroller: sc ? sc.tagName + '.' + (sc.className || '') : null,"
            " tabindex: a.getAttribute('tabindex')}; }")
        wpage.keyboard.press("ArrowRight")
        wpage.wait_for_timeout(260)
        k1 = _wfocus(wpage)
        st1 = _wstate(wpage)
        scroll1 = wpage.evaluate(
            "() => window.__w2aScroller ? window.__w2aScroller.scrollTop"
            " : null")
        report["flows"]["w2a_keyboard_right"] = {"k0": k0, "k1": k1, "st": st1,
                                                 "scroll_after": scroll1,
                                                 "strip": strip_ids}
        check(len(strip_ids) >= 2, "W2a: полоса без вкладок", wfails)
        check(k0["tabindex"] == "0", "W2a: активный таб без tabindex=0", wfails)
        check(38 <= k0["h"] <= 44,
              f"W2a: высота таба {round(k0['h'], 1)}", wfails)
        check(st1["tab"] == strip_ids[1] and k1["tab"] == strip_ids[1],
              f"W2a →: активный/фокус {st1['tab']}/{k1['tab']} "
              f"вместо {strip_ids[1]}", wfails)
        # preventDefault доказуем: прокрутка контейнера не сдвинулась.
        check(k0["scroller"] is not None and scroll1 == k0["scroll"],
              f"W2a: стрелка прокрутила страницу "
              f"({k0['scroll']}→{scroll1}) — нет preventDefault", wfails)
        # Tab-порядок: полоса — ОДНА остановка (roving tabindex).
        others = wpage.evaluate(
            "() => Array.from(document.querySelectorAll("
            "'[data-workspace-tabs] [data-workspace-tab]'))"
            ".filter(b => b.getAttribute('tabindex') !== '0').length")
        check(others == len(strip_ids) - 1,
              f"W2a: roving tabindex не у одного таба "
              f"({others}/{len(strip_ids)})", wfails)
        # End → последний; → на последнем не меняет; ← назад; Home → первый.
        wpage.keyboard.press("End")
        wpage.wait_for_timeout(240)
        end_st = _wstate(wpage)
        end_focus = _wfocus(wpage)
        check(end_st["tab"] == strip_ids[-1]
              and end_focus["tab"] == strip_ids[-1],
              f"W2a End: {end_st['tab']}/{end_focus['tab']}", wfails)
        # На краю стрелка не навигирует → контейнер не должен прокрутиться.
        scroll_before_edge = wpage.evaluate(
            "() => window.__w2aScroller ? window.__w2aScroller.scrollTop"
            " : null")
        wpage.keyboard.press("ArrowRight")
        wpage.wait_for_timeout(240)
        no_wrap = _wstate(wpage)
        no_wrap_focus = _wfocus(wpage)
        check(no_wrap["tab"] == strip_ids[-1]
              and no_wrap_focus["tab"] == strip_ids[-1],
              f"W2a: wrap на последнем табе ({no_wrap['tab']})", wfails)
        scroll_edge = wpage.evaluate(
            "() => window.__w2aScroller ? window.__w2aScroller.scrollTop"
            " : null")
        check(scroll_before_edge is not None
              and scroll_edge == scroll_before_edge,
              f"W2a: стрелка на краю прокрутила страницу "
              f"({scroll_before_edge}→{scroll_edge})", wfails)
        wpage.keyboard.press("ArrowLeft")
        wpage.wait_for_timeout(240)
        left_st = _wstate(wpage)
        check(left_st["tab"] == strip_ids[-2],
              f"W2a ←: {left_st['tab']} вместо {strip_ids[-2]}", wfails)
        wpage.keyboard.press("Home")
        wpage.wait_for_timeout(240)
        home_st = _wstate(wpage)
        home_focus = _wfocus(wpage)
        check(home_st["tab"] == strip_ids[0]
              and home_focus["tab"] == strip_ids[0],
              f"W2a Home: {home_st['tab']}/{home_focus['tab']}", wfails)
        # Tab выходит из полосы (не «застревает» во вкладках).
        wpage.keyboard.press("Tab")
        wpage.wait_for_timeout(200)
        tab_out = _wfocus(wpage)
        report["flows"]["w2a_tab_exit"] = tab_out
        check(not tab_out["inStrip"],
              "W2a: Tab остался внутри полосы вкладок", wfails)
        keys_seen = wpage.evaluate("() => window.__w2aKeys || []")
        report["flows"]["w2a_keys"] = keys_seen
        prevented = {k["k"]: k["prevent"] for k in keys_seen}
        for key in ("ArrowRight", "End", "ArrowLeft", "Home"):
            check(prevented.get(key) is True,
                  f"W2a: {key} не помечен preventDefault ({prevented})",
                  wfails)
        check(prevented.get("Tab") is False,
              f"W2a: Tab перехвачен (preventDefault) — вне набора"
              f" ({prevented})", wfails)
        wpage.screenshot(path=os.path.join(SHOTS, "w2a-keyboard-390.png"))

        # ── W2a-3: память вкладок (К-3/К-4/К-5) ──────────────────────────
        # Дальше — селектор области и каталог: desktop-ширина как у остальных
        # сценариев этого e2e (клавиатура уже проверена на 390).
        wpage.set_viewport_size({"width": 1280, "height": 800})
        _wopen(wpage, "#/modules/search")
        wpage.click('[data-workspace-tabs] [data-workspace-tab=limits]')
        wpage.wait_for_timeout(420)
        picked = _wstate(wpage)
        check(picked["tab"] == "limits" and picked["hash"].endswith("/limits"),
              f"W2a: клик «Лимиты» → {picked}", wfails)
        wpage.goto(WBASE + "#/modules", wait_until="load")
        wpage.wait_for_selector(".module-catalog [data-mod]", timeout=9000)
        wpage.wait_for_timeout(320)
        wpage.click(".module-catalog [data-mod=mod_search] .module-card-head")
        wpage.wait_for_selector("[data-workspace-head]", timeout=9000)
        wpage.wait_for_timeout(420)
        reopened = _wstate(wpage)
        check(reopened["tab"] == "limits",
              f"W2a: повторное открытие «Поиска» → {reopened['tab']} "
              f"(ожидалось limits)", wfails)
        wpage.reload(wait_until="load")
        wpage.wait_for_selector("[data-workspace-head]", timeout=9000)
        wpage.wait_for_timeout(520)
        reloaded = _wstate(wpage)
        check(reloaded["tab"] == "limits",
              f"W2a: после reload → {reloaded['tab']} (ожидалось limits)",
              failures)
        mem_raw = wpage.evaluate(
            "() => localStorage.getItem('adminbot.module_tab')")
        mem = json.loads(mem_raw or "{}")
        report["flows"]["w2a_memory"] = {"raw": mem_raw, "state": reloaded}
        key_a = "chat:%d|mod_search" % CHAT_ID
        check(mem.get(key_a) == "limits",
              f"W2a: память чата A {mem.get(key_a)} вместо limits", wfails)
        # Хранятся ТОЛЬКО id (scope|mod_* → tab id), без контента/названий.
        bad_keys = [k for k in mem
                    if not k.startswith(("chat:%d|" % CHAT_ID, "global|"))]
        check(not bad_keys, f"W2a: посторонние ключи памяти {bad_keys}",
              failures)
        check(all(isinstance(v, str) and v and " " not in v
                  for v in mem.values()),
              f"W2a: в памяти не id таба: {mem}", wfails)

        # Смена scope: та же вкладка, данные перечитаны, ключ нового scope.
        gets.clear()
        pre_scope = _wstate(wpage)
        wpage.click(".scope-trigger")
        wpage.click(".scope-option:has-text('%s')" % CHAT_TITLE2)
        wpage.wait_for_timeout(950)
        post_scope = _wstate(wpage)
        mem2 = json.loads(wpage.evaluate(
            "() => localStorage.getItem('adminbot.module_tab')") or "{}")
        key_b = "chat:%d|mod_search" % CHAT_ID2
        report["flows"]["w2a_scope"] = {
            "before": pre_scope, "after": post_scope,
            "gets": len(gets), "memory": mem2}
        check(post_scope["tab"] == pre_scope["tab"],
              f"W2a: смена чата увела вкладку "
              f"({pre_scope['tab']}→{post_scope['tab']})", wfails)
        check(len(gets) >= 1, "W2a: данные нового scope не перечитаны",
              failures)
        check(mem2.get(key_b) == post_scope["tab"],
              f"W2a: ключ нового scope {key_b}={mem2.get(key_b)} "
              f"вместо {post_scope['tab']}", wfails)
        check(mem2.get(key_a) == "limits",
              f"W2a: память чата A перезаписана ({mem2.get(key_a)})",
              failures)
        check(not [k for k in mem2 if k.startswith("chat:%d|" % CHAT_ID2)
                   and not k.endswith("|mod_search")],
              "W2a: память чужих модулей скопирована в новый scope", wfails)

        # Своя вкладка чата B: seed → reload → «models» (не «limits» чата A).
        seeded = {"chat:%d|mod_search" % CHAT_ID: "limits",
                  key_b: "models"}
        wpage.evaluate(
            "(raw) => localStorage.setItem('adminbot.module_tab', raw)",
            json.dumps(seeded))
        wpage.reload(wait_until="load")
        wpage.wait_for_selector("[data-workspace-head]", timeout=9000)
        wpage.wait_for_timeout(550)
        own_b = _wstate(wpage)
        mem3 = json.loads(wpage.evaluate(
            "() => localStorage.getItem('adminbot.module_tab')") or "{}")
        report["flows"]["w2a_scope_own_tab"] = {"state": own_b, "memory": mem3}
        check(own_b["tab"] == "models",
              f"W2a: чат B показал {own_b['tab']} вместо своей models",
              failures)
        check(mem3.get(key_a) == "limits",
              f"W2a: ключ чата A пострадал ({mem3.get(key_a)})", wfails)
        # Возврат в A: страница НЕ прыгает (pin текущей вкладки в новом scope).
        wpage.click(".scope-trigger")
        wpage.click(".scope-option:has-text('%s')" % CHAT_TITLE)
        wpage.wait_for_timeout(950)
        back_a = _wstate(wpage)
        mem4 = json.loads(wpage.evaluate(
            "() => localStorage.getItem('adminbot.module_tab')") or "{}")
        report["flows"]["w2a_scope_back"] = {"state": back_a, "memory": mem4}
        check(back_a["tab"] == "models",
              f"W2a: возврат в чат A прыгнул в {back_a['tab']}", wfails)
        check(mem4.get(key_a) == "models",
              f"W2a: pin в чат A не записан ({mem4.get(key_a)})", wfails)
        wctx.close()

        # ── W2a-4: свежесть ≠ активность (К-7/К-8) ───────────────────────
        fctx = browser.new_context(viewport={"width": 1280, "height": 900})
        fctx.add_init_script(TMA_STUB)
        fctx.route("**/api/**", _route)
        fpage = fctx.new_page()
        fpage.goto(WBASE + "#/modules", wait_until="load")
        fpage.wait_for_selector(".module-catalog [data-mod]", timeout=9000)
        fpage.wait_for_timeout(420)
        card_fresh = fpage.evaluate(
            "() => { const c = document.querySelector("
            "'[data-mod=mod_summary] [data-module-checked]');"
            "return c ? {text: c.innerText.trim(),"
            " title: c.getAttribute('title'),"
            " sw: c.scrollWidth, cw: c.clientWidth} : null; }")
        catalog_text = fpage.evaluate(
            "() => (document.querySelector('.module-catalog') || {})"
            ".innerText || ''")
        report["flows"]["w2a_fresh_card"] = card_fresh
        check(card_fresh and card_fresh["text"].startswith("Проверено:"),
              f"W2a: футер карточки без «Проверено:» ({card_fresh})", wfails)
        check(card_fresh and card_fresh["title"] == card_fresh["text"],
              "W2a: title не равен тексту свежести", wfails)
        fpage.goto(WBASE + "#/modules/summary/overview", wait_until="load")
        fpage.wait_for_selector("[data-workspace-head]", timeout=9000)
        fpage.wait_for_timeout(420)
        page_fresh = fpage.evaluate(
            "() => (document.querySelector('[data-workspace-checked]') || {})"
            ".innerText || ''")
        page_text = fpage.evaluate("() => document.body.innerText")
        report["flows"]["w2a_fresh_page"] = page_fresh.strip()
        check(page_fresh.strip() == (card_fresh or {}).get("text"),
              f"W2a: свежесть каталога «{card_fresh and card_fresh['text']}» "
              f"!= страницы «{page_fresh.strip()}»", wfails)
        check("0 событий" not in catalog_text + page_text,
              "W2a: выдуманные «0 событий»", wfails)
        check("1970" not in catalog_text + page_text,
              "W2a: выдуманное время (1970)", wfails)
        fpage.screenshot(path=os.path.join(SHOTS, "w2a-freshness-1280.png"))
        fctx.close()

        # 320/390: футер не переполняется, карточка остаётся 132–164.
        for nw, nh in [(390, 844), (320, 568)]:
            nctx = browser.new_context(viewport={"width": nw, "height": nh})
            nctx.add_init_script(TMA_STUB)
            nctx.route("**/api/**", _route)
            npage = nctx.new_page()
            npage.goto(WBASE + "#/modules", wait_until="load")
            npage.wait_for_selector(".module-catalog [data-mod]", timeout=9000)
            npage.wait_for_timeout(500)
            meas = npage.evaluate(
                "() => { const cards = Array.from(document.querySelectorAll("
                "'.module-catalog [data-mod]'));"
                "const foot = cards.map(c => c.querySelector("
                "'.module-card-footer')).filter(Boolean);"
                "const over = foot.filter(f => f.scrollWidth > f.clientWidth + 1);"
                "const open = foot.map(f => { const b = f.querySelector("
                "'[data-module-open]');"
                "return b ? Math.round(b.getBoundingClientRect().right"
                " - f.getBoundingClientRect().right) : null; });"
                "return {cards: cards.length,"
                " maxCard: Math.max.apply(null, cards.map(c => "
                "c.getBoundingClientRect().height)),"
                " minCard: Math.min.apply(null, cards.map(c => "
                "c.getBoundingClientRect().height)),"
                " overflow: over.length,"
                " openOut: open.filter(x => x !== null && x > 1).length,"
                " scrollWidth: document.documentElement.scrollWidth,"
                " vw: window.innerWidth,"
                " fresh: !!document.querySelector("
                "'[data-module-checked]')}; }")
            report["flows"]["w2a_narrow_%d" % nw] = meas
            check(meas["fresh"], f"W2a {nw}: футер без свежести", wfails)
            check(meas["overflow"] == 0,
                  f"W2a {nw}: футер переполнен у {meas['overflow']} карточек",
                  failures)
            check(meas["openOut"] == 0,
                  f"W2a {nw}: «Открыть» выходит за футер", wfails)
            check(131 <= meas["minCard"] and meas["maxCard"] <= 165,
                  f"W2a {nw}: высота карточки "
                  f"{meas['minCard']:.1f}–{meas['maxCard']:.1f}", wfails)
            check(meas["scrollWidth"] <= meas["vw"] + 1,
                  f"W2a {nw}: горизонтальный скролл страницы", wfails)
            npage.screenshot(path=os.path.join(
                SHOTS, f"w2a-cards-{nw}.png"))
            nctx.close()
        failures.extend(wfails)

        # ═══ W2b-B1 (2.58.212): «История» для «Сна»/«Ностальгии» ══════════
        # Контракты H-2…H-7 брифа W2b: вкладка только при 200+rows, один ряд
        # чипов, 5 событий в Обзоре, фильтр, deep link и его возврат при
        # empty/403/503/available:false, отсутствие горизонтального скролла.
        HISTORY_MODE.update({"dream": "data", "nostalgia": "data"})
        hctx = browser.new_context(viewport={"width": 1280, "height": 800})
        hctx.add_init_script(TMA_STUB)
        hctx.route("**/api/**", _route)
        hpage = hctx.new_page()
        herrs = []
        hpage.on("pageerror", lambda e, b=herrs: b.append(str(e)[:300]))
        hfails = []

        def _hopen(pg, route):
            # Смена HISTORY_MODE должна попадать в НОВЫЙ документ: навигация
            # только по hash не перезагружает приложение (и не делает запрос).
            pg.goto("about:blank")
            pg.goto(WBASE + route, wait_until="load")
            pg.wait_for_selector("[data-workspace-head]", timeout=9000)
            pg.wait_for_timeout(520)

        def _hprobe(pg):
            return pg.evaluate(
                "() => {"
                " const tab = document.querySelector("
                "  '[data-workspace-tabs] [data-workspace-tab=history]');"
                " const hist = document.querySelector('[data-module-history]');"
                " const st = document.querySelector("
                "  '[data-overview-history-state]');"
                " return {hash: location.hash,"
                "  tab: !!tab,"
                "  panel: !!hist,"
                "  rows: document.querySelectorAll("
                "   '[data-module-history-row]').length,"
                "  ovRows: document.querySelectorAll("
                "   '[data-overview-history-row]').length,"
                "  ovBlocks: document.querySelectorAll("
                "   '[data-overview-history]').length,"
                "  chipsRows: document.querySelectorAll("
                "   '[data-workspace-chips]').length,"
                "  dupChips: document.querySelectorAll("
                "   '[data-overview-chips]').length,"
                "  state: st ? st.getAttribute("
                "   'data-overview-history-state') : null,"
                "  filter: !!document.querySelector("
                "   '[data-module-history-filter]'),"
                "  filterValue: (document.querySelector("
                "   '#module-history-filter') || {}).value || '',"
                "  lastAction: !!document.querySelector("
                "   '[data-module-last-action]'),"
                "  histLink: document.querySelectorAll("
                "   '[data-overview-link=history]').length,"
                "  histCta: document.querySelectorAll("
                "   '[data-overview-history-open]').length,"
                "  refreshDisabled: (() => {"
                "    const b = hist ? hist.querySelector('button') : null;"
                "    return b ? b.disabled : null; })(),"
                "  scrollWidth: document.documentElement.scrollWidth,"
                "  vw: window.innerWidth}; }")

        # ── Сон: вкладка есть при 200+rows; Обзор = «Сейчас» + 5 событий.
        _hopen(hpage, "#/modules/sleep")
        sp = _hprobe(hpage)
        report["flows"]["w2b_sleep_overview"] = sp
        check(sp["tab"], "W2b sleep: нет вкладки history при 200+rows", hfails)
        check(sp["ovRows"] == 5,
              f"W2b sleep: в Обзоре {sp['ovRows']} событий вместо 5", hfails)
        check(sp["ovBlocks"] == 1,
              f"W2b sleep: блоков событий {sp['ovBlocks']} вместо 1", hfails)
        check(sp["chipsRows"] == 1 and sp["dupChips"] == 0,
              f"W2b sleep: рядов чипов "
              f"{sp['chipsRows']} (+дубль {sp['dupChips']})", hfails)
        check(not sp["panel"], "W2b sleep: панель истории видна на Обзоре", hfails)
        check(not sp["lastAction"] and sp["histLink"] == 1
              and sp["histCta"] == 0,
              f"W2b sleep: дубли факта/CTA (last={sp['lastAction']}, "
              f"link={sp['histLink']}, cta={sp['histCta']})", hfails)
        check(sp["scrollWidth"] <= sp["vw"] + 1,
              f"W2b sleep: горизонтальный скролл ({sp['scrollWidth']})", hfails)

        # ── История сна: deep link, все строки, клиентский фильтр.
        _hopen(hpage, "#/modules/sleep/history")
        hh = _hprobe(hpage)
        report["flows"]["w2b_sleep_history"] = hh
        check(hh["hash"].endswith("/sleep/history") and hh["panel"],
              f"W2b sleep/history: панель не открылась ({hh})", hfails)
        check(hh["rows"] == 6,
              f"W2b sleep/history: строк {hh['rows']} вместо 6", hfails)
        check(hh["filter"], "W2b sleep/history: фильтр не отрендерен", hfails)
        if hh["filter"]:
            hpage.select_option("#module-history-filter", "error")
            hpage.wait_for_timeout(260)
            flt = _hprobe(hpage)
            report["flows"]["w2b_sleep_filter"] = flt
            check(flt["rows"] == 1,
                  f"W2b sleep: фильтр error дал {flt['rows']} строк вместо 1",
                  hfails)
            hpage.select_option("#module-history-filter", "")
            hpage.wait_for_timeout(200)
            check(_hprobe(hpage)["rows"] == 6,
                  "W2b sleep: сброс фильтра не вернул все строки", hfails)
        # Один автоматический запрос на источник; вкладка не плодит запросы.
        HISTORY_GETS.update({"dream": 0, "nostalgia": 0})
        _hopen(hpage, "#/modules/sleep")
        try:
            hpage.wait_for_selector(
                "[data-workspace-tabs] [data-workspace-tab=history]",
                timeout=6000)
        except Exception:  # noqa: BLE001
            pass
        n1 = HISTORY_GETS["dream"]
        if hpage.query_selector(
                "[data-workspace-tabs] [data-workspace-tab=history]"):
            hpage.click("[data-workspace-tabs] [data-workspace-tab=history]")
        hpage.wait_for_timeout(420)
        n2 = HISTORY_GETS["dream"]
        report["flows"]["w2b_one_fetch"] = {"before": n1, "after": n2}
        check(n1 == 1 and n2 == 1,
              f"W2b sleep: запросов журнала {n1}→{n2} (ожидался 1)", hfails)

        # ── Ностальгия: вкладка/Обзор/история.
        _hopen(hpage, "#/modules/nostalgia/overview")
        np = _hprobe(hpage)
        report["flows"]["w2b_nostalgia_overview"] = np
        check(np["tab"], "W2b nostalgia: нет вкладки history", hfails)
        check(np["ovRows"] == 3 and np["ovBlocks"] == 1,
              f"W2b nostalgia: Обзор {np['ovRows']} строк/{np['ovBlocks']} "
              f"блоков", hfails)
        check(np["chipsRows"] == 1 and np["dupChips"] == 0,
              f"W2b nostalgia: рядов чипов {np['chipsRows']}", hfails)
        check(not np["lastAction"] and np["histLink"] == 1
              and np["histCta"] == 0,
              f"W2b nostalgia: дубли факта/CTA (last={np['lastAction']}, "
              f"link={np['histLink']}, cta={np['histCta']})", hfails)
        _hopen(hpage, "#/modules/nostalgia/history")
        nh = _hprobe(hpage)
        report["flows"]["w2b_nostalgia_history"] = nh
        check(nh["panel"] and nh["rows"] == 4,
              f"W2b nostalgia/history: {nh}", hfails)

        # ── F2: смена чата не оставляет loading; возврат восстанавливает
        # вкладку/refresh, без второго поллера.
        HISTORY_MODE["dream"] = "hold_once"
        hpage.goto("about:blank")
        hpage.goto(WBASE + "#/modules/sleep/history", wait_until="load")
        try:
            hpage.wait_for_selector("[data-module-history-state=loading]",
                                    timeout=6000)
            stalled = True
        except Exception:  # noqa: BLE001
            stalled = False
        held_old = HISTORY_HOLD["dream"]
        report["flows"]["w2b_chat_switch"] = {"stalled": stalled,
                                              "held": held_old is not None}
        check(stalled and held_old is not None,
              "W2b F2: запрос покидаемого чата не удержан", hfails)
        hpage.click(".scope-trigger")
        hpage.click(".scope-option:has-text('%s')" % CHAT_TITLE2)
        hpage.wait_for_timeout(950)
        if held_old is not None:
            held_old.fulfill(status=200, content_type="application/json",
                             body=json.dumps(DREAM_ROWS))
        hpage.wait_for_timeout(500)
        after_b = _hprobe(hpage)
        report["flows"]["w2b_chat_switch_new"] = after_b
        check(after_b["tab"] and after_b["state"] != "loading",
              f"W2b F2: новый чат залип в loading ({after_b})", hfails)
        hpage.click(".scope-trigger")
        hpage.click(".scope-option:has-text('%s')" % CHAT_TITLE)
        hpage.wait_for_timeout(1000)
        after_a = _hprobe(hpage)
        report["flows"]["w2b_chat_switch_back"] = after_a
        check(after_a["tab"] and after_a["state"] != "loading",
              f"W2b F2: возврат залип в loading ({after_a})", hfails)
        check(after_a["refreshDisabled"] is False,
              f"W2b F2: refresh недоступен ({after_a})", hfails)
        poll_before = HISTORY_GETS["dream"]
        hpage.wait_for_timeout(900)
        poll_after = HISTORY_GETS["dream"]
        check(poll_after == poll_before,
              f"W2b F2: фоновый поллер ({poll_before}->{poll_after})", hfails)
        HISTORY_HOLD["dream"] = None
        HISTORY_MODE["dream"] = "data"

        # ── F4: активный фильтр не переезжает на другой модуль.
        if hpage.query_selector("#module-history-filter"):
            hpage.select_option("#module-history-filter", "duplicate")
            hpage.wait_for_timeout(260)
            before_f4 = _hprobe(hpage)
            report["flows"]["w2b_filter_before_switch"] = before_f4
            check(before_f4["rows"] == 1,
                  f"W2b F4: фильтр duplicate дал {before_f4['rows']} строк",
                  hfails)
        else:
            report["flows"]["w2b_filter_before_switch"] = _hprobe(hpage)
            check(False, "W2b F4: фильтр журнала не отрендерен", hfails)
        hpage.evaluate(
            "() => { location.hash = '#/modules/nostalgia/history'; }")
        hpage.wait_for_timeout(1000)
        after_f4 = _hprobe(hpage)
        report["flows"]["w2b_filter_after_switch"] = after_f4
        check(after_f4["panel"] and after_f4["filterValue"] == ""
              and after_f4["rows"] == 4,
              f"W2b F4: фильтр не сброшен при смене модуля ({after_f4})",
              hfails)

        # ── Loading: deep link показывает «Загружаем историю…» (H-5).
        HISTORY_MODE["dream"] = "hold"
        hpage.goto("about:blank")
        hpage.goto(WBASE + "#/modules/sleep/history", wait_until="load")
        try:
            hpage.wait_for_selector(
                "[data-module-history-state=loading]", timeout=6000)
            loading_seen = True
        except Exception:  # noqa: BLE001
            loading_seen = False
        held = HISTORY_HOLD["dream"]
        report["flows"]["w2b_loading"] = {"seen": loading_seen,
                                          "held": held is not None}
        check(loading_seen, "W2b: deep link не показал «Загружаем историю…»",
              hfails)
        if held is not None:
            held.fulfill(status=200, content_type="application/json",
                         body=json.dumps(DREAM_ROWS))
        HISTORY_HOLD["dream"] = None
        HISTORY_MODE["dream"] = "data"
        try:
            hpage.wait_for_selector("[data-module-history-row]", timeout=6000)
        except Exception:  # noqa: BLE001
            pass
        check(_hprobe(hpage)["rows"] == 6,
              "W2b: после загрузки deep link не показал строки", hfails)

        # ── Empty deep link: однократный возврат на bare, без пустой панели.
        HISTORY_MODE["nostalgia"] = "empty"
        hpage.goto("about:blank")
        hpage.goto(WBASE + "#/modules/nostalgia/history", wait_until="load")
        hpage.wait_for_selector("[data-workspace-head]", timeout=9000)
        hpage.wait_for_timeout(900)
        ep = _hprobe(hpage)
        report["flows"]["w2b_empty_deeplink"] = ep
        check(ep["hash"] == "#/modules/nostalgia",
              f"W2b empty: deep link не вернул bare ({ep['hash']})", hfails)
        check(not ep["panel"], "W2b empty: осталась пустая панель истории",
              hfails)
        check(not ep["tab"], "W2b empty: вкладка history появилась при []",
              hfails)

        # ── 403: вкладки нет, честная причина в Обзоре (не «0 событий»).
        HISTORY_MODE["dream"] = "denied"
        _hopen(hpage, "#/modules/sleep")
        dp = _hprobe(hpage)
        body_403 = hpage.evaluate("() => document.body.innerText")
        report["flows"]["w2b_denied"] = dict(dp, body=body_403[:400])
        check(not dp["tab"], "W2b 403: вкладка history показана", hfails)
        check(dp["state"] == "denied",
              f"W2b 403: причина {dp['state']} вместо denied", hfails)
        check("0 событий" not in body_403,
              "W2b 403: выдуманные «0 событий»", hfails)

        # ── 503 и available:false: вкладки нет, состояние off.
        HISTORY_MODE["dream"] = "off"
        _hopen(hpage, "#/modules/sleep")
        offp = _hprobe(hpage)
        report["flows"]["w2b_off_503"] = offp
        check(not offp["tab"] and offp["state"] == "off",
              f"W2b 503: {offp}", hfails)
        HISTORY_MODE["nostalgia"] = "unavailable"
        _hopen(hpage, "#/modules/nostalgia/overview")
        offp2 = _hprobe(hpage)
        report["flows"]["w2b_unavailable"] = offp2
        check(not offp2["tab"] and offp2["state"] == "off",
              f"W2b available:false: {offp2}", hfails)
        HISTORY_MODE.update({"dream": "data", "nostalgia": "data"})

        # ── 390: вкладка/история без горизонтального скролла.
        hctx2 = browser.new_context(viewport={"width": 390, "height": 844})
        hctx2.add_init_script(TMA_STUB)
        hctx2.route("**/api/**", _route)
        hp2 = hctx2.new_page()
        hp2.goto(WBASE + "#/modules/sleep", wait_until="load")
        hp2.wait_for_selector("[data-workspace-head]", timeout=9000)
        hp2.wait_for_timeout(520)
        m1 = _hprobe(hp2)
        report["flows"]["w2b_390_overview"] = m1
        check(m1["tab"], "W2b 390: нет вкладки history", hfails)
        check(m1["scrollWidth"] <= m1["vw"] + 1,
              f"W2b 390: скролл Обзора ({m1['scrollWidth']})", hfails)
        if hp2.query_selector(
                "[data-workspace-tabs] [data-workspace-tab=history]"):
            hp2.click("[data-workspace-tabs] [data-workspace-tab=history]")
            hp2.wait_for_timeout(520)
        m2 = _hprobe(hp2)
        report["flows"]["w2b_390_history"] = m2
        check(m2["panel"] and m2["rows"] == 6,
              f"W2b 390: история {m2}", hfails)
        check(m2["scrollWidth"] <= m2["vw"] + 1,
              f"W2b 390: скролл Истории ({m2['scrollWidth']})", hfails)
        hp2.screenshot(path=os.path.join(SHOTS, "w2b-history-390.png"))
        hctx2.close()

        report["flows"]["w2b_pageerrors"] = herrs
        failures.extend(hfails)
        if herrs:
            failures.extend(["W2b pageerror: " + e for e in herrs])
        HISTORY_MODE.update({"dream": "data", "nostalgia": "data"})
        HISTORY_HOLD.update({"dream": None, "nostalgia": None})
        hctx.close()

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
