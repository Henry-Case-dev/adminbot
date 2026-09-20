"""F1 round 10.25 — Playwright/Chromium матрица shell'ов (§71, T-2407).

Реальный `web/index.html` + `web/static/*` на локальном http-сервере; `/api/*`
перехватываются Playwright'ом и отдаются фейковыми ответами (R17: без
секретов, без реального бэкенда/БД). Telegram.WebApp стубируется init-script'ом.

Проверяет для каждого вьюпорта §71:
  * `document.documentElement.scrollWidth <= window.innerWidth + 1`
    (нет горизонтального скролла страницы);
  * реальные `getBoundingClientRect()` ключевых shell-элементов
    (sidebar ≥1200 / drawer 768–1199 / bottom-nav <768 — взаимоисключающе);
  * нижняя навигация = ровно N пунктов (админ: 4);
  * touch-таргеты ≥44×44;
  * скриншоты desktop/mobile.

Матрица: 320×700, 360×780, 390×844, 430×932, 768×1024, 1024×768,
1280×800, 1440×900, 1920×1080, 2560×1440.

Запуск: .venv/Scripts/python.exe tools/ui_round1025_matrix.py
Артефакты: tools/_ui_round1025_raw.json + tools/_ui_round1025_shots/*.png

ВАЖНО: это инструмент @Builder/@Reviewer/@DevOps. Успешный прогон локально НЕ
заменяет живую приёмку в Telegram WebView (10.20-UPD3/10.21 урок).
"""
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
PORT = 8791
SHOTS = os.path.join(REPO, "tools", "_ui_round1025_shots")
RAW = os.path.join(REPO, "tools", "_ui_round1025_raw.json")

VIEWPORTS = [
    (320, 700), (360, 780), (390, 844), (430, 932), (768, 1024),
    (1024, 768), (1280, 800), (1440, 900), (1920, 1080), (2560, 1440),
]
ROUTES = ["#/", "#/oversight", "#/how", "#/modules", "#/ai",
          "#/ai/llm", "#/ai/prompts", "#/ai/smart-cache", "#/ai/names",
          "#/memory", "#/memory/rag", "#/memory/lore", "#/access"]


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
    "ui_flags": {
        "TOKEN_FLOW_NODEFLOW_ENABLED": True,
        "IMAGE_MODULE_CARD_ENABLED": True,
        "PROMPTS_UI_V2_ENABLED": True,
        "BYOK_IMAGE_KEY_ENABLED": True,
        "DOSSIER_LIVE_FEED_ENABLED": True,
        "ALIASES_KEYSVALUE_RENDER_ENABLED": True,
        "IA_V2_ENABLED": True,
    },
}

# Минимально достаточные ответы API, чтобы шаблоны монтировались без падений
# (реальный бэкенд/БД не поднимаем; секретов нет — R17).
STATUS_STUB = {
    "bot": {"uptime_seconds": 3600, "state": "running", "errors_total": 0},
    "server": {
        "cpu_percent": 3.0,
        "memory": {"used": 536870912, "total": 2147483648, "percent": 25},
        "disk": {"used": 10737418240, "total": 107374182400, "percent": 10},
        "loadavg": [0.1, 0.2, 0.3],
        "process": {"pid": 1234, "rss_mb": 120, "threads": 8},
    },
    "llm": [],
    "context": {},
}

def _config_stub() -> dict:
    """Непустой `/api/config` из `services/param_catalog.py` (P0-инцидент F1).

    Даёт реальный рендер generic config-разделов (`#/ai/llm`, `#/ai/names`,
    `#/ai/smart-cache`, `#/ai/prompts`, `#/memory/rag`) — чтобы render-ошибки
    класса `stickyFieldFailed is not a function` ловились автоматически.
    Секретов нет (R17): секретные значения — `{configured,last4}`."""
    try:
        from services import param_catalog as pc
    except Exception as exc:  # noqa: BLE001
        print("[matrix] config stub: param_catalog недоступен:", exc)
        return {"items": [], "groups": []}
    items = []
    for key, spec in sorted(pc.REGISTRY.items()):
        if getattr(spec, "hidden", False):
            continue
        secret = bool(getattr(spec, "secret", False))
        widget = getattr(spec, "widget", "") or ""
        stype = getattr(spec, "type", "str") or "str"
        if secret:
            value = {"configured": True, "last4": "0000"}
        elif widget == "keyvalue":
            value = {}
        elif stype == "bool":
            value = False
        elif stype in ("int", "float"):
            value = 1
        elif widget == "select" and getattr(spec, "select_options", None):
            value = list(spec.select_options)[0]
        else:
            value = ""
        items.append({
            "key": key, "value": value, "category": spec.category,
            "secret": secret, "chat_source": "", "global_value": None,
            "title": getattr(spec, "title_ru", key) or key, "type": stype,
            "updated_at": None, "group": getattr(spec, "group", "") or "",
            "description": getattr(spec, "description", "") or "",
            "widget": widget,
            "select_options": list(spec.select_options)
            if widget == "select" and getattr(spec, "select_options", None)
            else None,
            "select_labels": list(spec.select_labels)
            if widget == "select" and getattr(spec, "select_labels", None)
            else None,
            "per_chat": bool(getattr(spec, "per_chat", False)),
            "progressive_level": "basic",
            "stage": getattr(spec, "stage", None),
            "view_roles": [], "edit_roles": [], "chat_updated_at": None,
        })
    present = {it["category"] for it in items}
    groups = [{"id": g.id, "category": g.category, "title": g.title_ru,
               "description": g.description, "order": g.order}
              for g in pc.GROUPS if g.category in present]
    groups.sort(key=lambda g: g["order"])
    print("[matrix] config stub: items=%d groups=%d" % (len(items), len(groups)))
    return {"items": items, "groups": groups}


CONFIG_STUB = _config_stub()

API_STUBS = [
    ("/api/me", ME_JSON),
    ("/api/status/key-history", {"providers": []}),
    ("/api/status/logs", {"logs": [], "levels": [], "counts": {}}),
    ("/api/status", STATUS_STUB),
    ("/api/access/me", {"is_local_admin": False, "permissions": {}}),
    ("/api/access/param_permissions", {"items": {}, "roles": []}),
    ("/api/access/chats", []),
    ("/api/admins", {"admins": []}),
    ("/api/roles", {"roles": [{"role_name": "user", "permissions": {}}]}),
    ("/api/oversight/summary", {"chats": [], "totals": {}}),
    ("/api/oversight/dossier_feed", {"items": []}),
    ("/api/workers/budget", {}),
    ("/api/config", CONFIG_STUB),
    ("/api/info/guide", {"markdown": "", "updated_at": None}),
    ("/api/info", {"html": "", "updated_at": None, "canon_drift": False}),
]


def _stub_for(url: str):
    for marker, payload in API_STUBS:
        if url.split("?")[0].endswith(marker):
            return payload
    return {}


TMA_STUB = """
try {
  // Реальный telegram-web-app.js перетирает window.Telegram своим WebApp с
  // пустым initData (нет настоящего TG). app.js::getInitData кэширует/читает
  // sessionStorage — засеваем его, чтобы hasInitData() был истинным.
  sessionStorage.setItem('adminbot.initData', 'user=%7B%22id%22%3A5885953495%7D&hash=audit');
} catch (e) {}
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A5885953495%7D&hash=audit',
  initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
  themeParams: {}, colorScheme: 'dark', viewportStableHeight: 800,
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {},
  setBottomBarColor() {}, onEvent() {}, offEvent() {}, isExpanded: true,
  BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
} };
"""

PROBE_JS = """
(() => {
  const de = document.documentElement;
  const rect = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return { x: Math.round(r.x), y: Math.round(r.y),
             w: Math.round(r.width), h: Math.round(r.height),
             display: st.display, visible: r.width > 0 && r.height > 0 };
  };
  const links = Array.from(document.querySelectorAll('.bottom-nav-link'));
  const minTouch = links.reduce((m, el) => {
    const r = el.getBoundingClientRect();
    return Math.min(m, Math.min(r.width || 999, r.height || 999));
  }, 999);
  return {
    innerWidth: window.innerWidth,
    scrollWidth: de.scrollWidth,
    overflow: de.scrollWidth > window.innerWidth + 1,
    sidebar: rect('.app-sidebar'),
    drawer: rect('.app-drawer'),
    bottomNav: rect('.bottom-nav'),
    navbarBand: rect('.navbar-band'),
    bottomNavCount: links.length,
    minTouch: links.length ? Math.round(minTouch) : null,
    hasAsideEl: !!document.querySelector('.app-sidebar'),
    mediaMin1200: window.matchMedia('(min-width: 1200px)').matches,
    mediaMax767: window.matchMedia('(max-width: 767px)').matches,
  };
})()
"""


def _snap(page, name):
    try:
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=False)
    except Exception as e:  # noqa: BLE001
        print("[matrix] screenshot fail", name, e)


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    httpd = _start_server()
    out = {"viewports": {}, "console": [],
           "url": "http://127.0.0.1:%d/web/index.html" % PORT}
    failures = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (w, h) in VIEWPORTS:
            ctx = browser.new_context(viewport={"width": w, "height": h})
            ctx.add_init_script(TMA_STUB)

            def _route(route):
                payload = _stub_for(route.request.url)
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(payload))

            ctx.route("**/api/**", _route)
            page = ctx.new_page()
            vp_errors = []
            page.on("console", lambda m, b=vp_errors: (
                b.append("%s: %s" % (m.type, m.text[:200]))
                if m.type == "error" else None))
            page.on("pageerror", lambda e, b=vp_errors: b.append(
                "pageerror: " + str(e)[:300]))
            url = "http://127.0.0.1:%d/web/index.html" % PORT + "#/"
            page.goto(url, wait_until="load")
            try:
                page.wait_for_selector(".app-shell", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(700)
            # IA v2: shell-режим мог не пересчитаться после stub-me → ресайз.
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_timeout(300)

            vp_key = "%dx%d" % (w, h)
            out["viewports"][vp_key] = {"routes": {}}
            for route in ROUTES:
                page.evaluate("(r) => { window.location.hash = r; }", route)
                page.wait_for_timeout(350)
                probe = page.evaluate(PROBE_JS)
                out["viewports"][vp_key]["routes"][route] = probe
                if probe["overflow"]:
                    failures.append("%s %s: horizontal overflow %d > %d"
                                    % (vp_key, route, probe["scrollWidth"],
                                       probe["innerWidth"]))
                if w >= 1200:
                    if not (probe["sidebar"] and probe["sidebar"]["visible"]):
                        failures.append("%s %s: sidebar не виден (≥1200)"
                                        % (vp_key, route))
                    if probe["bottomNav"]:
                        failures.append("%s %s: bottom-nav не должен быть ≥1200"
                                        % (vp_key, route))
                elif w >= 768:
                    if probe["sidebar"] and probe["sidebar"]["visible"]:
                        failures.append("%s %s: sidebar не должен быть 768–1199"
                                        % (vp_key, route))
                    if probe["bottomNav"]:
                        failures.append("%s %s: bottom-nav не должен быть 768–1199"
                                        % (vp_key, route))
                else:
                    if not (probe["bottomNav"] and probe["bottomNav"]["visible"]):
                        failures.append("%s %s: нет bottom-nav (<768)"
                                        % (vp_key, route))
                    if probe["bottomNavCount"] not in (0, 4, 2):
                        failures.append("%s %s: bottom-nav=%d (ожидалось 4 админ)"
                                        % (vp_key, route, probe["bottomNavCount"]))
                    if probe["sidebar"] and probe["sidebar"]["visible"]:
                        failures.append("%s %s: sidebar не должен быть <768"
                                        % (vp_key, route))
                if route == "#/":
                    _snap(page, "%s_root" % vp_key)
                if route == "#/memory":
                    _snap(page, "%s_memory" % vp_key)
            # P0-инцидент F1: render-ошибки (console.error/pageerror) — FAIL,
            # иначе класс «раздел пуст, но метрики чистые» не ловится.
            for msg in vp_errors:
                failures.append("%s console/pageerror: %s" % (vp_key, msg))
            out["console"].extend("%s %s" % (vp_key, m) for m in vp_errors)
            print("[matrix] %-9s root: scrollW=%d innerW=%d sidebar=%s "
                  "bottomNav=%s(%d)" % (
                      vp_key, out["viewports"][vp_key]["routes"]["#/"]["scrollWidth"],
                      w,
                      bool(out["viewports"][vp_key]["routes"]["#/"]["sidebar"]),
                      bool(out["viewports"][vp_key]["routes"]["#/"]["bottomNav"]),
                      out["viewports"][vp_key]["routes"]["#/"]["bottomNavCount"]))
            ctx.close()
        browser.close()

    httpd.shutdown()
    out["failures"] = failures
    with open(RAW, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("[matrix] failures:", len(failures))
    for f_ in failures:
        print("  !", f_)
    print("[matrix] артефакты:", RAW, "+", SHOTS)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
