"""CFG-02A вЂ” Playwright e2e В«Р›РёРјРёС‚С‹ РіРµРЅРµСЂР°С†РёРёВ» (РґРµС‚РµСЂРјРёРЅРёСЂРѕРІР°РЅРЅС‹Р№).

РџСЂРѕРІРµСЂСЏРµС‚ РЅР° СЂРµР°Р»СЊРЅС‹С… `web/index.html` + `web/app.js` (/api/* вЂ” СЃС‚Р°Р±С‹;
R17: С‚РѕР»СЊРєРѕ РёРґРµРЅС‚РёС„РёРєР°С‚РѕСЂС‹/С‡РёСЃР»Р°) С„Р°РєС‚С‹ СЃР»Р°Р№СЃР° CFG-02A:

  * В§02A.1 вЂ” РЅР° СЃС‚СЂР°РЅРёС†Рµ В«РњРѕРґСѓР»Рё в†’ Р“РµРЅРµСЂР°С†РёСЏ РёР·РѕР±СЂР°Р¶РµРЅРёР№ в†’ РћСЃРЅРѕРІРЅС‹Рµ РЅР°СЃС‚СЂРѕР№РєРёВ»
    РІРёРґРЅР° СЃРµРєС†РёСЏ В«Р›РёРјРёС‚С‹ РіРµРЅРµСЂР°С†РёРёВ» СЃ РїРѕР»РµРј `limits.image_daily_limit`
    (Р±РµР· РѕР±С…РѕРґРЅС‹С… СЂР°Р·РґРµР»РѕРІ/РїРѕРёСЃРєР°) Рё С„Р°РєС‚РёС‡РµСЃРєРёРј Р·РЅР°С‡РµРЅРёРµРј РѕР±Р»Р°СЃС‚Рё;
  * В§02A.2 вЂ” РЅР°Р·РІР°РЅРёРµ В«РР·РѕР±СЂР°Р¶РµРЅРёР№ РІ СЃСѓС‚РєРёВ», РµРґРёРЅРёС†С‹ В«РіРµРЅРµСЂР°С†РёР№/СЃСѓС‚РєРёВ»,
    РёСЃС‚РѕС‡РЅРёРє (С‡Р°С‚/РіР»РѕР±Р°Р»СЊРЅРѕ/Р·Р°РІРѕРґСЃРєРѕР№), СЂР°СЃС…РѕРґ, РѕСЃС‚Р°С‚РѕРє, TZ, Р±Р»РёР¶Р°Р№С€РёР№ СЃР±СЂРѕСЃ,
    РїРѕРґСЃРєР°Р·РєР° РїСЂРѕ СЃРїРёСЃР°РЅРёРµ (РЅРµСЃРєРѕР»СЊРєРѕ РєР°СЂС‚РёРЅРѕРє / РїРѕРІС‚РѕСЂРЅР°СЏ РґРѕСЃС‚Р°РІРєР°);
  * В§02A.3 вЂ” Р·РЅР°С‡РµРЅРёРµ СЂРµРґР°РєС‚РёСЂСѓРµС‚СЃСЏ Рё СЃРѕС…СЂР°РЅСЏРµС‚СЃСЏ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёРј write-path
    (POST /api/config; X-Chat-Id РґР»СЏ РѕР±Р»Р°СЃС‚Рё С‡Р°С‚Р°); РЅРµРІР°Р»РёРґРЅС‹Р№ РІРІРѕРґ
    (в€’7 / РЅРµ С‡РёСЃР»Рѕ) РќР• РѕС‚РїСЂР°РІР»СЏРµС‚СЃСЏ Рё РѕР±СЉСЏСЃРЅСЏРµС‚СЃСЏ; В«в†Є Р“Р»РѕР±Р°Р»СЊРЅРѕРµВ» РІРѕР·РІСЂР°С‰Р°РµС‚
    РЅР°СЃР»РµРґРѕРІР°РЅРёРµ;
  * В§02A.4 вЂ” С‡РµСЃС‚РЅС‹Р№ СЂРµР¶РёРј РїСЂРёРјРµРЅРµРЅРёСЏ: reserve / legacy (kill-switch OFF) /
    master-СЂСѓР±РёР»СЊРЅРёРє OFF / РЅРµРёР·РІРµСЃС‚РЅРѕ вЂ” UI РЅРµ Р·Р°СЏРІР»СЏРµС‚ В«Р»РёРјРёС‚ РїСЂРёРјРµРЅС‘РЅВ»,
    РєРѕРіРґР° С„Р°РєС‚РёС‡РµСЃРєРѕРµ РѕРіСЂР°РЅРёС‡РµРЅРёРµ РґСЂСѓРіРѕРµ.

Р—Р°РїСѓСЃРє: .venv\\Scripts\\python.exe tools\\ui_cfg02a_image_quota_e2e.py
        (РёР»Рё py -3 -m tools.ui_cfg02a_image_quota_e2e)
        --serve вЂ” С‚РѕР»СЊРєРѕ РїРѕРґРЅСЏС‚СЊ СЃРµСЂРІРµСЂ (РІРёР·СѓР°Р»СЊРЅР°СЏ РїСЂРѕРІРµСЂРєР° Browser Use)
РђСЂС‚РµС„Р°РєС‚С‹: plans/features/cfg/evidence/cfg-02a/ui/
"""
import copy
import json
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (СЃРµСЂРІРµСЂ/СЃС‚Р°Р±С‹/TMA вЂ” reuse)

PORT = 8841
SHOTS = os.path.join(REPO, "plans", "features", "cfg", "evidence", "cfg-02a",
                     "ui")
RAW = os.path.join(os.environ.get("OPENCODE_WORKFLOW_SCRATCH",
                                  os.path.join(REPO, "tools")),
                   "_ui_cfg02a_image_quota.json")

CHAT_ID = -1001234567890
KEY = "limits.image_daily_limit"
GROUP = "limits_images"
TZ = "Asia/Yekaterinburg"
NEXT_RESET = "2026-10-19T00:00:00+05:00"

# РЎРѕСЃС‚РѕСЏРЅРёРµ С„РёРєСЃС‚СѓСЂ (РјСѓС‚РёСЂСѓРµС‚ С‚РµСЃС‚ РјРµР¶РґСѓ С„Р°Р·Р°РјРё; С‡РёС‚Р°РµС‚ handler).
STATE = {
    "global_value": 60,        # РіР»РѕР±Р°Р»СЊРЅРѕРµ Р·РЅР°С‡РµРЅРёРµ (РєР°Рє РєР°С‚Р°Р»РѕРіРѕРІС‹Р№ РґРµС„РѕР»С‚)
    "chat_override": None,     # per-chat override (None в†’ РЅР°СЃР»РµРґРѕРІР°РЅРёРµ)
    "used": 3,
    "shared_used": 12,
    "shared_limit": 200,
    "source": "default",       # РёСЃС‚РѕС‡РЅРёРє per-chat Р·РЅР°С‡РµРЅРёСЏ (С‡Р°С‚/РіР»РѕР±Р°Р»СЊРЅРѕ/вЂ¦)
    "reserve_path": "reserve",
    "reserve_reason": "ok",
    "posts": [],
}


def _config_items(scope_chat: bool) -> dict:
    """/api/config: РіР»РѕР±Р°Р»СЊРЅС‹Р№ СЃР»РѕР№ (РјР°С‚СЂРёС†Р° РєР°С‚Р°Р»РѕРіР°) + per-chat overlay.

    РЎРµСЂРІРµСЂРЅР°СЏ СЃРµРјР°РЅС‚РёРєР° `web/api/routes.py::get_config`: value = global, РµСЃР»Рё
    РЅРµС‚ override; override (per_chat=True) в†’ value/chat_source='chat'."""
    data = copy.deepcopy(M.CONFIG_STUB)
    items = data["items"]
    by_key = {it["key"]: it for it in items}
    # Матрица ролей — как в реальном GET /api/config (access.default_matrix):
    # иначе витрина показывает ложный бейдж «скрыт» (stub-артефакт, не дефект).
    from services import access as _access
    for it in items:
        matrix = _access.default_matrix(it["key"], it.get("category"))
        it["view_roles"] = list(matrix["view_roles"])
        it["edit_roles"] = list(matrix["edit_roles"])
    it = by_key[KEY]
    it["value"] = STATE["global_value"]
    it["global_value"] = STATE["global_value"]
    if scope_chat:
        it["global_value"] = STATE["global_value"]
        if STATE["chat_override"] is not None:
            it["value"] = STATE["chat_override"]
            it["chat_source"] = "chat"
        else:
            it["chat_source"] = ""
    data["chat_id"] = CHAT_ID if scope_chat else None
    data["updated_at"] = "2026-10-18T10:00:00+05:00" if scope_chat else None
    data["ctx"] = {"role_chat": "admin", "is_local_admin": True,
                   "is_global_admin": True, "is_dm": False}
    return data


def _budget_payload() -> dict:
    """GET /api/workers/budget: Р°РґРґРёС‚РёРІРЅР°СЏ image-РІСЂРµР·РєР° В§27 + С„Р°РєС‚С‹ СЂРµР¶РёРјР°."""
    effective_limit = (STATE["chat_override"]
                       if STATE["chat_override"] is not None
                       else STATE["global_value"])
    effective_source = ("chat" if STATE["chat_override"] is not None
                        else STATE["source"])
    entry = {
        "scope": "chat:%d" % CHAT_ID,
        "calls": {"used": 7, "limit": 500},
        "tokens": {"used": 1200, "limit": 500000},
        "image_calls": {"used": STATE["used"], "limit": effective_limit,
                        "day": "2026-10-18", "timezone": TZ,
                        "next_reset_at": NEXT_RESET,
                        "source": effective_source},
        "image_usage": {
            "day": "2026-10-18", "timezone": TZ,
            "used": STATE["used"], "limit": effective_limit,
            "source": effective_source, "next_reset_at": NEXT_RESET,
            "reserve_path": STATE["reserve_path"],
            "reserve_reason": STATE["reserve_reason"],
            "shared_used": STATE["shared_used"],
            "shared_limit": STATE["shared_limit"],
            "requests": 4, "success": 3, "errors": 1, "denied": 1,
            "delivery_failed": 0, "expenses": "N/A",
        },
    }
    return {
        "day": "2026-10-18", "timezone": TZ,
        "global": {"calls": {"used": 7, "limit": 500},
                   "tokens": {"used": 1200, "limit": 500000},
                   "image_calls": {"used": STATE["shared_used"],
                                   "limit": STATE["shared_limit"],
                                   "day": "2026-10-18", "timezone": TZ,
                                   "next_reset_at": NEXT_RESET,
                                   "source": "env"}},
        "chats": [entry], "priorities": [],
    }


def _api_handler(route):
    req = route.request
    url = req.url.split("?")[0]
    scope_chat = req.headers.get("x-chat-id") is not None
    if url.endswith("/api/_mark"):
        STATE["posts"].append({"mark": str(req.post_data or "")})
        route.fulfill(status=200, content_type="application/json",
                      body="{}")
        return
    if req.method == "POST" and url.endswith("/api/config"):
        try:
            body = json.loads(req.post_data or "{}")
        except ValueError:
            body = {}
        for it in body.get("items", []):
            key, value = it.get("key"), it.get("value")
            STATE["posts"].append({"key": key, "value": value,
                                   "chat": scope_chat,
                                   "phase": STATE.get("phase", "")})
            if key == KEY:
                if scope_chat:
                    STATE["chat_override"] = value
                else:
                    STATE["global_value"] = value
        body_out = {"updated": [i.get("key") for i in body.get("items", [])]}
        if scope_chat:
            body_out["chat_id"] = CHAT_ID
            body_out["updated_at"] = "2026-10-18T10:00:01+05:00"
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body_out, ensure_ascii=False))
        return
    if req.method == "DELETE" and "/api/config/chat/" in url:
        STATE["posts"].append({"key": url.rsplit("/", 1)[-1], "value": None,
                               "chat": True, "reset": True})
        STATE["chat_override"] = None
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"removed": True}, ensure_ascii=False))
        return
    if url.endswith("/api/config"):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_config_items(scope_chat),
                                      ensure_ascii=False))
        return
    if url.endswith("/api/workers/budget"):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_budget_payload(), ensure_ascii=False))
        return
    if url.endswith("/api/config/overrides-map"):
        rows = []
        if STATE["chat_override"] is not None:
            rows = [{"key": KEY, "chat_id": CHAT_ID,
                     "chat_title": "Audit Chat", "value": STATE["chat_override"],
                     "source": "chat", "access": "global_admin",
                     "is_dm": False}]
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"items": rows}, ensure_ascii=False))
        return
    body = M._stub_for(req.url)
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body, ensure_ascii=False))


def _serve_only() -> int:
    """Режим визуальной проверки (Browser Use): статика + JSON-стабы /api/*.

    Отличие от Playwright-прогона: роутинг API выполняется СЕРВЕРОМ (не
    context.route), поэтому страницу можно открыть любым браузером. Плюс
    управление фикстурами через `POST /api/_serve` (harness-only)."""
    from http.server import SimpleHTTPRequestHandler

    class _ServeHandler(M._Handler):
        def log_message(self, *args):      # тишина
            pass

        def _json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):                  # noqa: N802
            path = self.path.split("?")[0]
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            if path == "/api/_serve":
                try:
                    patch = json.loads(raw or "{}")
                except ValueError:
                    patch = {}
                for k in ("global_value", "chat_override", "used", "shared_used",
                          "shared_limit", "source", "reserve_path",
                          "reserve_reason"):
                    if k in patch:
                        STATE[k] = patch[k]
                return self._json({"ok": True})
            if path == "/api/config":
                try:
                    body = json.loads(raw or "{}")
                except ValueError:
                    body = {}
                scope_chat = self.headers.get("X-Chat-Id") is not None
                for it in body.get("items", []):
                    STATE["posts"].append({"key": it.get("key"),
                                           "value": it.get("value"),
                                           "chat": scope_chat})
                    if it.get("key") == KEY:
                        if scope_chat:
                            STATE["chat_override"] = it.get("value")
                        else:
                            STATE["global_value"] = it.get("value")
                out = {"updated": [i.get("key") for i in body.get("items", [])]}
                if scope_chat:
                    out["chat_id"] = CHAT_ID
                    out["updated_at"] = "2026-10-18T10:00:01+05:00"
                return self._json(out)
            return self._json({}, status=404)

        def do_GET(self):                   # noqa: N802
            path = self.path.split("?")[0]
            if path == "/api/config":
                scope_chat = self.headers.get("X-Chat-Id") is not None
                return self._json(_config_items(scope_chat))
            if path == "/api/workers/budget":
                return self._json(_budget_payload())
            if path == "/api/config/overrides-map":
                rows = []
                if STATE["chat_override"] is not None:
                    rows = [{"key": KEY, "chat_id": CHAT_ID,
                             "chat_title": "Audit Chat",
                             "value": STATE["chat_override"],
                             "source": "chat", "access": "global_admin",
                             "is_dm": False}]
                return self._json({"items": rows})
            if path.startswith("/api/"):
                return self._json(M._stub_for(self.path))
            return super().do_GET()

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _ServeHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    print("SERVE %s#/modules/images/settings" % base, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:      # pragma: no cover
        return 0


def main() -> int:
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    os.makedirs(SHOTS, exist_ok=True)

    from playwright.sync_api import sync_playwright
    result = {"console_errors": [], "checks": {}, "screenshots": [],
              "posts": STATE["posts"]}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000},
                                  reduced_motion="reduce")
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _api_handler)
        page = ctx.new_page()
        page.on("console", lambda m: result["console_errors"].append(
            m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror: " + str(e)[:200]))
        page.on("dialog", lambda d: d.accept())
        page.goto(base, wait_until="load")
        page.wait_for_timeout(1600)
        checks = result["checks"]

        def mark(name):
            """Граница фазы в журнале запросов (детерминированная атрибуция)."""
            page.evaluate(
                "fetch('/api/_mark', {method: 'POST', body: %r})"
                % name)
            page.wait_for_timeout(150)

        # Трассировка write-path: кто вызывает saveConfigItem/persistItems
        # (детерминированная атрибуция POST'ов; поведение не меняется).
        page.evaluate(
            "(() => { const vm = window.__adminbotVm;"
            " window.__cfgTraces = [];"
            " const wrap = (name) => { const orig = vm[name];"
            "  if (typeof orig !== 'function') return;"
            "  const bound = orig.bind(vm);"
            "  vm[name] = function () {"
            "   try { const a = arguments[0] || {};"
            "    window.__cfgTraces.push({fn: name,"
            "     key: (a.key || (a.items && a.items[0] && a.items[0].key) || ''),"
            "     value: (a.value !== undefined ? a.value"
            "             : (a.items && a.items[0] && a.items[0].value)),"
            "     scope: (vm.activeChatId == null ? 'global' : 'chat'),"
            "     stack: (new Error().stack || '').split('\\n')"
            "               .slice(1, 6).join(' <- ')}); } catch (e) {}"
            "   return bound.apply(vm, arguments); }; };"
            " ['saveConfigItem', 'persistItems', 'saveImageDailyLimit',"
            "  'saveModalEdits'].forEach(wrap); })()")

        # в”Ђв”Ђ Р¤Р°Р·Р° A: РіР»РѕР±Р°Р»СЊРЅР°СЏ РѕР±Р»Р°СЃС‚СЊ, В«РћСЃРЅРѕРІРЅС‹Рµ РЅР°СЃС‚СЂРѕР№РєРёВ» РјРѕРґСѓР»СЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        mark('A-global')
        page.evaluate("window.__adminbotVm.setActiveChat(null)")
        page.wait_for_timeout(900)
        page.evaluate("window.location.hash = '#/modules/images/settings'")
        page.wait_for_timeout(1800)
        checks["settings_section_visible"] = page.evaluate(
            "!!document.querySelector('[data-config-group=\"%s\"]')" % GROUP)
        checks["section_title"] = page.evaluate(
            "(() => { const g = document.querySelector("
            "'[data-config-group=\"%s\"]'); if (!g) return '';"
            " const t = g.querySelector('.text-sm.font-bold');"
            " return t ? t.textContent.trim() : ''; })()" % GROUP)
        checks["facts_visible"] = page.evaluate(
            "!!document.querySelector('[data-image-quota-facts]')")
        checks["facts_value"] = page.evaluate(
            "(document.querySelector('[data-image-quota-value]')||{}).textContent"
            " ? document.querySelector('[data-image-quota-value]').textContent.trim() : ''")
        checks["facts_input_present"] = page.evaluate(
            "(() => { const i = document.querySelector("
            "'[data-image-quota-input]'); if (!i) return null;"
            " return { value: i.value, min: i.getAttribute('min'),"
            "  step: i.getAttribute('step') }; })()")
        checks["facts_hint"] = page.evaluate(
            "(() => { const h = document.querySelector('[data-image-quota-hint]');"
            " return h ? h.textContent.replace(/\\s+/g, ' ').trim() : ''; })()")
        checks["facts_mode"] = page.evaluate(
            "(() => { const m = document.querySelector('[data-image-quota-mode]');"
            " return m ? m.textContent.replace(/\\s+/g, ' ').trim() : ''; })()")
        checks["facts_tz"] = page.evaluate(
            "(() => { const t = document.querySelector('[data-image-quota-tz]');"
            " return t ? t.textContent.trim() : ''; })()")
        checks["facts_reset"] = page.evaluate(
            "(() => { const r = document.querySelector('[data-image-quota-reset]');"
            " return r ? r.textContent.trim() : ''; })()")
        checks["no_limits_tab_for_module"] = page.evaluate(
            "(() => { const tabs = Array.from(document.querySelectorAll("
            "'[data-workspace-tab]')).map(e => e.getAttribute("
            "'data-workspace-tab'));"
            " return tabs.length > 0 && tabs.indexOf('limits') < 0"
            " && tabs.indexOf('settings') >= 0; })()")
        shot = os.path.join(SHOTS, "01-settings-global.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        # в”Ђв”Ђ Р¤Р°Р·Р° B: СЃРѕС…СЂР°РЅРµРЅРёРµ Р·РЅР°С‡РµРЅРёСЏ (СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёР№ write-path) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        mark('B-save')
        before = len(STATE["posts"])
        page.fill("[data-image-quota-input]", "2")
        page.dispatch_event("[data-image-quota-input]", "change")
        page.wait_for_timeout(1200)
        posts = [p for p in STATE["posts"]
                 if p.get("key") == KEY]
        checks["save_post"] = posts[-1] if posts else None
        checks["save_posts_count"] = len(STATE["posts"]) - before
        page.evaluate("window.__adminbotVm.loadConfig()")
        page.wait_for_timeout(900)
        checks["facts_value_after_save"] = page.evaluate(
            "(document.querySelector('[data-image-quota-value]')||{})"
            ".textContent ? document.querySelector('[data-image-quota-value]')"
            ".textContent.trim() : ''")

        # в”Ђв”Ђ Р¤Р°Р·Р° C: РЅРµРІР°Р»РёРґРЅС‹Р№ РІРІРѕРґ РќР• РѕС‚РїСЂР°РІР»СЏРµС‚СЃСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        mark('C-invalid')
        before = len(STATE["posts"])
        page.fill("[data-image-quota-input]", "-7")
        page.dispatch_event("[data-image-quota-input]", "change")
        page.wait_for_timeout(800)
        checks["invalid_posts_count"] = len(STATE["posts"]) - before
        checks["invalid_error_visible"] = page.evaluate(
            "(() => { const e = document.querySelector("
            "'[data-image-quota-input-error]');"
            " return e ? e.textContent.replace(/\\s+/g, ' ').trim() : ''; })()")
        shot = os.path.join(SHOTS, "02-invalid-input.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        # ── Фаза C2 (B1, ревью 10c15cf5): ПУСТОЙ ввод не отправляется ───────
        # `Number('') === 0` — без явной проверки «очистить поле» молча
        # сохраняло бы 0 («генерация запрещена»).
        mark('C2-empty')
        before = len(STATE["posts"])
        page.fill("[data-image-quota-input]", "")
        page.dispatch_event("[data-image-quota-input]", "change")
        page.wait_for_timeout(800)
        checks["empty_posts_count"] = len(STATE["posts"]) - before
        checks["empty_error_visible"] = page.evaluate(
            "(() => { const e = document.querySelector("
            "'[data-image-quota-input-error]');"
            " return e ? e.textContent.replace(/\\s+/g, ' ').trim() : ''; })()")
        checks["empty_input_value"] = page.evaluate(
            "(document.querySelector('[data-image-quota-input]')||{})"
            ".value != null ? document.querySelector("
            "'[data-image-quota-input]').value : ''")
        shot = os.path.join(SHOTS, "06-empty-input.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        # в”Ђв”Ђ Р¤Р°Р·Р° D: С‡РµСЃС‚РЅС‹Р№ СЂРµР¶РёРј (kill-switch OFF) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        mark('D-legacy')
        STATE["reserve_path"] = "legacy"
        STATE["reserve_reason"] = "kill_switch_off"
        STATE["global_value"] = 2
        STATE["used"] = 2
        page.evaluate("window.__adminbotVm._imageQuotaAt = 0;"
                      "window.__adminbotVm.maybeLoadImageQuota()")
        page.wait_for_timeout(1200)
        checks["legacy_mode_notice"] = page.evaluate(
            "(() => { const m = document.querySelector('[data-image-quota-mode]');"
            " return m ? m.textContent.replace(/\\s+/g, ' ').trim() : ''; })()")
        checks["legacy_notice_is_warn"] = page.evaluate(
            "(() => { const m = document.querySelector('[data-image-quota-mode]');"
            " return !!m && m.className.indexOf('amber') >= 0; })()")
        checks["remaining_after_used"] = page.evaluate(
            "(() => { const r = document.querySelector("
            "'[data-image-quota-remaining]');"
            " return r ? r.textContent.trim() : ''; })()")
        shot = os.path.join(SHOTS, "03-legacy-mode.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        STATE["reserve_path"] = "legacy"
        STATE["reserve_reason"] = "budgets_off"
        page.evaluate("window.__adminbotVm._imageQuotaAt = 0;"
                      "window.__adminbotVm.maybeLoadImageQuota()")
        page.wait_for_timeout(1000)
        checks["budgets_off_notice"] = page.evaluate(
            "(() => { const m = document.querySelector('[data-image-quota-mode]');"
            " return m ? m.textContent.replace(/\\s+/g, ' ').trim() : ''; })()")

        # в”Ђв”Ђ Р¤Р°Р·Р° E: РѕР±Р»Р°СЃС‚СЊ Р§РђРўРђ вЂ” override + РёСЃС‚РѕС‡РЅРёРє + СЃР±СЂРѕСЃ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        mark('E-chat')
        STATE["reserve_path"] = "reserve"
        STATE["reserve_reason"] = "ok"
        STATE["global_value"] = 60
        STATE["chat_override"] = 1
        STATE["source"] = "chat"
        STATE["used"] = 1
        page.evaluate("window.__adminbotVm.setActiveChat(%d)" % CHAT_ID)
        page.wait_for_timeout(1800)
        page.evaluate("window.__adminbotVm._imageQuotaAt = 0;"
                      "window.__adminbotVm.maybeLoadImageQuota()")
        page.wait_for_timeout(1200)
        checks["chat_scope_source"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-quota-facts]');"
            " return n ? n.textContent.replace(/\\s+/g, ' ').trim() : ''; })()")
        checks["chat_scope_value"] = page.evaluate(
            "(document.querySelector('[data-image-quota-value]')||{})"
            ".textContent ? document.querySelector('[data-image-quota-value]')"
            ".textContent.trim() : ''")
        checks["chat_scope_override_applied"] = page.evaluate(
            "(() => { const i = document.querySelector("
            "'[data-image-quota-input]');"
            " return i ? i.value : ''; })()")
        checks["chat_scope_source_is_chat"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-quota-current]');"
            " return n ? n.textContent.indexOf('Локальный (чат)') >= 0 : false;"
            " })()")
        before = len(STATE["posts"])
        page.fill("[data-image-quota-input]", "3")
        page.dispatch_event("[data-image-quota-input]", "change")
        page.wait_for_timeout(1200)
        chat_posts = [p for p in STATE["posts"][before:] if p["key"] == KEY]
        checks["chat_save_post"] = chat_posts[-1] if chat_posts else None
        checks["reset_button_present"] = page.evaluate(
            "!!document.querySelector('.btn-reset-global')")
        shot = os.path.join(SHOTS, "04-chat-scope.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        # в”Ђв”Ђ Р¤Р°Р·Р° F: РјРѕР±РёР»СЊРЅС‹Р№ РІРёРґ (390px) вЂ” СЃРµРєС†РёСЏ Рё РїРѕР»Рµ РґРѕСЃС‚СѓРїРЅС‹ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(900)
        checks["mobile_section_visible"] = page.evaluate(
            "!!document.querySelector('[data-config-group=\"%s\"]')" % GROUP)
        checks["mobile_no_overflow"] = page.evaluate(
            "document.documentElement.scrollWidth <= "
            "document.documentElement.clientWidth + 2")
        shot = os.path.join(SHOTS, "05-mobile-chat.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        result["traces"] = page.evaluate("window.__cfgTraces || []")
        browser.close()

    result["posts"] = STATE["posts"]
    os.makedirs(os.path.dirname(RAW), exist_ok=True)
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("screenshots",)}, ensure_ascii=False,
                     indent=2))
    ok = (not result["console_errors"]
          and checks.get("settings_section_visible")
          and checks.get("section_title") == "Лимиты генерации"
          and checks.get("facts_visible")
          and "60" in str(checks.get("facts_value"))
          and checks.get("save_post", {}).get("value") == 2
          and checks.get("save_post", {}).get("chat") is False
          and checks.get("invalid_posts_count") == 0
          and "Допустимо целое число" in str(
              checks.get("invalid_error_visible"))
          and checks.get("empty_posts_count") == 0          # B1 (10c15cf5)
          and "Допустимо целое число" in str(
              checks.get("empty_error_visible"))
          and "IMAGE_DAILY_LIMIT_ENABLED" in str(
              checks.get("legacy_mode_notice"))
          and checks.get("legacy_notice_is_warn") is True
          and "НЕ ограничивает" in str(checks.get("budgets_off_notice"))
          and checks.get("chat_save_post", {}).get("chat") is True
          and checks.get("chat_scope_value") == "1 генераций/сутки"
          and checks.get("chat_scope_source_is_chat") is True
          and checks.get("reset_button_present") is True
          and checks.get("facts_reset") == "19.10.2026, 00:00"
          and "не списывают" in str(checks.get("facts_hint"))
          and checks.get("mobile_section_visible")
          and checks.get("mobile_no_overflow"))
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--serve" in sys.argv:
        raise SystemExit(_serve_only())
    raise SystemExit(main())
