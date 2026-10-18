# -*- coding: utf-8 -*-
"""CFG-02C — Playwright e2e витрины «Пользовательские изображения» (§02C.5).

Проверяет на реальных `web/index.html` + `web/app.js` (/api/* — стабы; R17:
только идентификаторы/числа) факты слайса CFG-02C:

  * §02C.5 — секция «Лимиты генерации» ЯВНО обозначает «Пользовательские
    изображения» и поясняет «Обложки сводок здесь не учитываются» (видно на
    десктопе и на мобильном 390px; фон/дизайн не переделываются);
  * §02C.4/§02C.5 — агрегат общего технического бюджета показывает РАЗБИВКУ
    по источникам («в том числе обложки сводок: N»): один счётчик не
    выдаётся за другой; пользовательские used/остаток обложек не включают;
  * отсутствие ошибок консоли и горизонтального оверфлоу на мобильном.

Запуск: .venv\\Scripts\\python.exe tools\\ui_cfg02c_image_isolation_e2e.py
        --serve — только поднять сервер (визуальная проверка Browser Use)
Артефакты: plans/features/cfg/evidence/cfg-02c/ui/
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

import ui_round1025_matrix as M  # noqa: E402  (сервер/стабы/TMA — reuse)

PORT = 8843
SHOTS = os.path.join(REPO, "plans", "features", "cfg", "evidence", "cfg-02c",
                     "ui")
RAW = os.path.join(os.environ.get("OPENCODE_WORKFLOW_SCRATCH",
                                  os.path.join(REPO, "tools")),
                   "_ui_cfg02c_image_isolation.json")

CHAT_ID = -1001234567890
GROUP = "limits_images"
TZ = "Asia/Yekaterinburg"
NEXT_RESET = "2026-10-20T00:00:00+05:00"
QUOTA_KEY = "limits.image_daily_limit"

# Состояние фикстуры (мутирует тест между фазами; читает handler).
STATE = {
    "global_value": 60,        # глобальное значение каталога
    "chat_override": None,     # per-chat override (None → наследование)
    "used": 3,                 # пользовательский расход (без обложек)
    "shared_used": 12,         # общий технический расход (user + cover)
    "shared_limit": 200,
    "cover_used": 4,           # из shared_used — обложки Summary
    "source": "default",
    "reserve_path": "reserve",
    "reserve_reason": "ok",
    "posts": [],
    "phase": "",
}


def _config_items(scope_chat: bool) -> dict:
    """/api/config: глобальный слой (матрица каталога) + per-chat overlay."""
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
    it = by_key.get(QUOTA_KEY)
    if it is None:                                   # страховка стаба
        it = {"key": QUOTA_KEY, "title": "Изображений в сутки",
              "value": STATE["global_value"], "type": "int",
              "group": GROUP, "per_chat": True}
        items.append(it)
        by_key[QUOTA_KEY] = it
    it["value"] = STATE["global_value"]
    it["global_value"] = STATE["global_value"]
    if scope_chat:
        if STATE["chat_override"] is not None:
            it["value"] = STATE["chat_override"]
            it["chat_source"] = "chat"
        else:
            it["chat_source"] = ""
    data["chat_id"] = CHAT_ID if scope_chat else None
    data["updated_at"] = "2026-10-19T10:00:00+05:00" if scope_chat else None
    data["ctx"] = {"role_chat": "admin", "is_local_admin": True,
                   "is_global_admin": True, "is_dm": False}
    return data


def _budget_payload() -> dict:
    """GET /api/workers/budget: §27-врезка + CFG-02C-разбивка по источникам."""
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
                        "day": "2026-10-19", "timezone": TZ,
                        "next_reset_at": NEXT_RESET,
                        "source": effective_source},
        "image_usage": {
            "day": "2026-10-19", "timezone": TZ,
            "used": STATE["used"], "limit": effective_limit,
            "source": effective_source, "next_reset_at": NEXT_RESET,
            "reserve_path": STATE["reserve_path"],
            "reserve_reason": STATE["reserve_reason"],
            "shared_used": STATE["shared_used"],
            "shared_limit": STATE["shared_limit"],
            "requests": 4, "success": 3, "errors": 1, "denied": 1,
            "delivery_failed": 0, "expenses": "N/A",
            # CFG-02C: отдельный агрегат обложек (в user-счётчики не входит).
            "cover": {"requests": STATE["cover_used"],
                      "success": STATE["cover_used"],
                      "errors": 0, "denied": 0, "delivery_failed": 0},
        },
    }
    return {
        "day": "2026-10-19", "timezone": TZ,
        "global": {"calls": {"used": 7, "limit": 500},
                   "tokens": {"used": 1200, "limit": 500000},
                   "image_calls": {"used": STATE["shared_used"],
                                   "limit": STATE["shared_limit"],
                                   "day": "2026-10-19", "timezone": TZ,
                                   "next_reset_at": NEXT_RESET,
                                   "source": "env",
                                   # CFG-02C (§02C.4): разбивка агрегата.
                                   "cover_used": STATE["cover_used"]}},
        "chats": [entry], "priorities": [],
    }


def _api_handler(route):
    req = route.request
    url = req.url.split("?")[0]
    scope_chat = req.headers.get("x-chat-id") is not None
    if url.endswith("/api/_mark"):
        STATE["posts"].append({"mark": str(req.post_data or "")})
        route.fulfill(status=200, content_type="application/json", body="{}")
        return
    if req.method == "POST" and url.endswith("/api/config"):
        try:
            body = json.loads(req.post_data or "{}")
        except ValueError:
            body = {}
        for it in body.get("items", []):
            STATE["posts"].append({"key": it.get("key"), "value": it.get("value"),
                                   "chat": scope_chat})
            if it.get("key") == QUOTA_KEY:
                if scope_chat:
                    STATE["chat_override"] = it.get("value")
                else:
                    STATE["global_value"] = it.get("value")
        out = {"updated": [i.get("key") for i in body.get("items", [])]}
        if scope_chat:
            out["chat_id"] = CHAT_ID
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(out, ensure_ascii=False))
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
    body = M._stub_for(req.url)
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body, ensure_ascii=False))


def _serve_only() -> int:
    """Режим визуальной проверки (Browser Use): статика + серверные стабы."""
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
                for k in ("global_value", "chat_override", "used",
                          "shared_used", "shared_limit", "cover_used",
                          "source", "reserve_path", "reserve_reason"):
                    if k in patch:
                        STATE[k] = patch[k]
                return self._json({"ok": True})
            if path == "/api/config":
                return self._json({"updated": []})
            return self._json({}, status=404)

        def do_GET(self):                   # noqa: N802
            path = self.path.split("?")[0]
            if path == "/api/config":
                scope_chat = self.headers.get("X-Chat-Id") is not None
                return self._json(_config_items(scope_chat))
            if path == "/api/workers/budget":
                return self._json(_budget_payload())
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
    result = {"console_errors": [], "checks": {}, "screenshots": []}
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

        page.evaluate("window.__adminbotVm.setActiveChat(%d)" % CHAT_ID)
        page.wait_for_timeout(700)
        page.evaluate("window.location.hash = '#/modules/images/settings'")
        page.wait_for_timeout(1800)

        checks["section_visible"] = page.evaluate(
            "!!document.querySelector('[data-config-group=\"%s\"]')" % GROUP)
        checks["facts_visible"] = page.evaluate(
            "!!document.querySelector('[data-image-quota-facts]')")
        # §02C.5: подпись «Пользовательские изображения» + пояснение.
        checks["scope_label"] = page.evaluate(
            "(() => { const e = document.querySelector("
            "'[data-image-quota-scope-label]');"
            " return e ? e.textContent.replace(/\\s+/g, ' ').trim() : ''; })()")
        # §02C.4/.5: разбивка агрегата по источникам.
        checks["shared_breakdown"] = page.evaluate(
            "(() => { const e = document.querySelector("
            "'[data-image-quota-shared-breakdown]');"
            " return e ? e.textContent.replace(/\\s+/g, ' ').trim() : ''; })()")
        checks["shared_value"] = page.evaluate(
            "(() => { const e = document.querySelector("
            "'[data-image-quota-shared-value]');"
            " return e ? e.textContent.trim() : ''; })()")
        checks["chat_used"] = page.evaluate(
            "(() => { const e = document.querySelector("
            "'[data-image-quota-used]');"
            " return e ? e.textContent.trim() : ''; })()")
        checks["chat_remaining"] = page.evaluate(
            "(() => { const e = document.querySelector("
            "'[data-image-quota-remaining]');"
            " return e ? e.textContent.trim() : ''; })()")
        checks["group_description"] = page.evaluate(
            "(() => { const g = document.querySelector("
            "'[data-config-group=\"%s\"]'); if (!g) return '';"
            " const d = g.querySelector('.text-xs.text-gray-500');"
            " return d ? d.textContent.replace(/\\s+/g, ' ').trim() : ''; })()"
            % GROUP)
        shot = os.path.join(SHOTS, "01-desktop-user-images-label.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        # ── Мобильный вид (390px): подпись/пояснение/разбивка видны ─────────
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(900)
        checks["mobile_section_visible"] = page.evaluate(
            "!!document.querySelector('[data-config-group=\"%s\"]')" % GROUP)
        checks["mobile_label_visible"] = page.evaluate(
            "(() => { const e = document.querySelector("
            "'[data-image-quota-scope-label]'); if (!e) return false;"
            " const r = e.getBoundingClientRect();"
            " return r.width > 0 && r.height > 0; })()")
        checks["mobile_breakdown_visible"] = page.evaluate(
            "(() => { const e = document.querySelector("
            "'[data-image-quota-shared-breakdown]'); if (!e) return false;"
            " const r = e.getBoundingClientRect();"
            " return r.width > 0 && r.height > 0; })()")
        checks["mobile_no_overflow"] = page.evaluate(
            "document.documentElement.scrollWidth <= "
            "document.documentElement.clientWidth + 2")
        shot = os.path.join(SHOTS, "02-mobile-user-images-label.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        browser.close()

    os.makedirs(os.path.dirname(RAW), exist_ok=True)
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items()
                      if k != "screenshots"}, ensure_ascii=False, indent=2))
    label = str(checks.get("scope_label", ""))
    breakdown = str(checks.get("shared_breakdown", ""))
    ok = (not result["console_errors"]
          and checks.get("section_visible") is True
          and checks.get("facts_visible") is True
          and "Пользовательские изображения" in label
          and "Обложки сводок здесь не учитываются" in label
          and "Пользовательские изображения" in str(
              checks.get("group_description"))
          and "Обложки сводок" in str(checks.get("group_description"))
          and "обложки" in breakdown.lower()
          and str(STATE["cover_used"]) in breakdown
          and checks.get("shared_value") == "12 / 200"
          and checks.get("chat_used") == "3"        # user-only, без обложек
          and checks.get("mobile_section_visible") is True
          and checks.get("mobile_label_visible") is True
          and checks.get("mobile_breakdown_visible") is True
          and checks.get("mobile_no_overflow") is True)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--serve" in sys.argv:
        raise SystemExit(_serve_only())
    raise SystemExit(main())
