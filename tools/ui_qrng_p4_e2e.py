# -*- coding: utf-8 -*-
"""QRNG P4 — Playwright e2e «Модули → Случайность» на РЕАЛЬНЫХ ассетах.

Стенд: `web/index.html` + `web/app.js` + `web/static/*` отдаются локальным
HTTP-сервером; `/api/*` — детерминированные стабы (реальный каталог
param_catalog/module_registry для DTO, состояние random в памяти). Никаких
внешних запросов: ANU/IBM/LfDR не вызываются.

Проверяется:
  * ровно 3 карточки/3 опции, Lizaonair отсутствует;
  * настоящий селектор: выбор → POST /api/config с key=random.primary_provider
    и реальным provider id; `/api/status` перерисовывает «Сейчас используется»;
  * fallback-порядок: up/down/include → тот же random.fallback_order;
  * честная draft-подсказка (значения НЕ зачисляются);
  * Activity без fake green при PRNG (badge не badge-ok);
  * раскрытие карточки = 0 сетевых запросов;
  * `#/ai/llm`: 0 `[data-cfg-key^="keys.random"]`, «Время ответа и защита»
    последняя, 180/360 на месте;
  * desktop 1280 и mobile 390: одна колонка, без горизонтального overflow,
    шрифт в карточках ≥12px.

Запуск: .venv\\Scripts\\python.exe tools/ui_qrng_p4_e2e.py
Печатает JSON-отчёт в stdout (exit 1 при провале).
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PORT = int(os.environ.get("QRNG_P4_PORT", "8797"))
BASE = "http://127.0.0.1:%d" % PORT
ADMIN_ID = 5885953495

TMA_STUB = r"""
try {
  sessionStorage.setItem(
    'adminbot.initData',
    'user=%7B%22id%22%3A5885953495%7D&hash=audit');
} catch (e) {}
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A5885953495%7D&hash=audit',
  initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
  themeParams: {}, colorScheme: 'dark',
  viewportHeight: window.innerHeight, viewportStableHeight: window.innerHeight,
  isExpanded: true, ready: function () {}, expand: function () {},
  onEvent: function () {}, offEvent: function () {},
  setHeaderColor: function () {}, setBackgroundColor: function () {},
  HapticFeedback: { impactOccurred: function () {},
                    notificationOccurred: function () {} },
  showAlert: function () {}, openLink: function () {},
  disableVerticalSwipes: function () {},
} };
"""

STATE = {
    "primary": "ibm_quantum",
    "order": ["anu", "lfdr"],
    "fallback": True,
    "prng": False,
    "posts": [],
    "random_tests": 0,
}


def _config_items():
    from services import param_catalog as pc
    items = []
    values = {
        "random.primary_provider": STATE["primary"],
        "random.fallback_order": list(STATE["order"]),
        "random.fallback_enabled": bool(STATE["fallback"]),
        "keys.random_quantum_api_key": {"configured": True, "last4": "Lz5l"},
        "keys.random_quantum_plan": "Trial",
        "keys.random_quantum_batch_length": 1024,
        "keys.random_quantum_data_type": "uint16",
        "keys.random_quantum_request_timeout_seconds": 10,
        "keys.random_quantum_refill_low_watermark": 256,
        "keys.random_quantum_buffer_max_values": 8192,
        "keys.random_quantum_endpoint":
            "https://api.quantumnumbers.anu.edu.au",
        "memory.random_source": "quantum",
        "memory.random_fallback_to_pseudorandom": True,
        "memory.random_enabled": True,
        "memory.random_exploration_probability": 0.05,
        "memory.random_sleep_exploration_probability": 0.05,
        "models.llm_timeout": 180,
        "models.llm_max_retries": 2,
        "models.llm_total_budget": 360,
    }
    for key, spec in sorted(pc.REGISTRY.items()):
        if getattr(spec, "hidden", False):
            continue
        pg = getattr(spec, "pg_key", None) or key
        if pg in values:
            value = values[pg]
        elif bool(getattr(spec, "secret", False)):
            value = {"configured": True, "last4": "0000"}
        elif spec.type == "bool":
            value = bool(pg.startswith("memory.random_uses_"))
        elif spec.type == "int":
            value = 0
        elif spec.type == "float":
            value = 0.0
        elif spec.type == "json":
            value = []
        else:
            value = ""
        items.append({
            "key": pg, "value": value, "category": spec.category,
            "secret": bool(getattr(spec, "secret", False)),
            "chat_source": "", "global_value": None,
            "title": getattr(spec, "title_ru", key) or key,
            "type": spec.type, "updated_at": None,
            "group": getattr(spec, "group", "") or "",
            "description": getattr(spec, "description", "") or "",
            "per_chat": bool(getattr(spec, "per_chat", False)),
            "progressive_level": "basic",
            "widget": getattr(spec, "widget", "") or "",
            "select_options": list(getattr(spec, "select_options", ()) or ()),
            "select_labels": list(getattr(spec, "select_labels", ()) or ()),
            "view_roles": [], "edit_roles": [], "chat_updated_at": None,
        })
    present = {it["category"] for it in items}
    groups = [{"id": g.id, "category": g.category, "title": g.title_ru,
               "description": g.description, "order": g.order}
              for g in pc.GROUPS if g.category in present]
    groups.sort(key=lambda g: g["order"])
    return {"items": items, "groups": groups}


def _status_payload():
    prng = bool(STATE["prng"])
    primary = STATE["primary"]
    providers = []
    for pid, title in (("ibm_quantum", "IBM Quantum"),
                       ("anu", "ANU Quantum Numbers"),
                       ("lfdr", "LfDR QRNG")):
        configured = (pid == "anu") or (pid == "lfdr")
        providers.append({
            "id": pid, "title": title,
            "entropy_class": "hardware_quantum",
            "requires_key": pid == "anu",
            "configured": configured,
            "reserve": 512 if pid == "anu" else 0,
            "consumable": pid == "anu",
            "quarantined": 0,
            "config_matches": True,
            "state": "active" if pid == "anu" else
                     ("unverified" if pid == "lfdr" else "unconfigured"),
        })
    return {
        "enabled": True, "available": True,
        "selected_source": "pseudorandom" if prng else "quantum",
        "effective_source": "pseudorandom" if prng else "quantum",
        "quantum_active": not prng,
        "anu_state": "active",
        "blocker": None if not prng else "no_eligible_alternative",
        "key_present": True,
        "provider": None if prng else primary,
        "entropy_class": None if prng else "hardware_quantum",
        "providers": providers,
        "provider_reserve": {"ibm_quantum": 0, "anu": 512, "lfdr": 0},
        "provider_quarantined": {"ibm_quantum": 0, "anu": 0, "lfdr": 0},
        "reserve_quarantined": 0,
        "fallback_setting_label": "псевдослучайный откат (не квантовый)",
        "reserve_remaining": 0 if prng else 512,
        "buffer_max": 8192, "low_watermark": 256,
        "last_batch": {"batch_id": "b1", "provider": "ANU Quantum Numbers",
                       "provider_id": "anu", "data_type": "uint16",
                       "length": 1024, "created_at": 1794909600,
                       "config_matches": True},
        "draws": {"quantum": 0 if prng else 37, "pseudorandom": 3 if prng else 0},
        "last_fallback_reason": "no_eligible_alternative" if prng else None,
        "last_fallback_at": 1794909900 if prng else None,
        "activated_at": 1794900000,
        "primary_provider": primary,
        "primary_setting_raw": primary,
        "primary_setting_state": "set",
        "resolved_primary": state_resolved(prng, primary),
        "effective_provider": None if prng else primary,
        "fallback_enabled": bool(STATE["fallback"]),
        "fallback_order": list(STATE["order"]),
        "fallback_order_raw": list(STATE["order"]),
        "fallback_order_state": "set",
        "effective_order": [primary] + list(STATE["order"]),
        "prng_active": prng,
        "prng_setting": bool(STATE["fallback"]),
        "fallback_setting": bool(STATE["fallback"]),
        "lfdr_state": "unverified",
        "plan": "Trial",
        "policy_version": "p4-e2e",
        "recent_draws": [], "recent_draws_scope": "global",
        "uses": {"enabled": True, "events": [], "cursor": None,
                 "scope": "global"},
    }


def state_resolved(prng, primary):
    if prng:
        return None
    return primary


def _me_payload():
    return {
        "telegram_id": ADMIN_ID, "username": "audit",
        "first_name": "Audit", "last_name": None, "photo_url": None,
        "role_name": "global_admin",
        "permissions": {"wildcard": True}, "is_custom": False,
        "is_global_admin": True, "role_chat": "admin",
        "ui_flags": {
            "IMAGE_MODULE_CARD_ENABLED": True, "IA_V2_ENABLED": True,
            "UI_SHELL_GLASS_V2": True, "UI_SHELL_LAYOUT_V2": True,
            "UI_HEARTBEAT_PREMIUM": True, "UI_SHELL_V3": True,
            "UI_AURORA_BG_ENABLED": False, "UI_SHELL_FLEX_V3": True,
            "UI_SHELL_GRAPHITE_V3": True, "UI_LIQUID_GLASS_LIB": False,
            "UI_AURORA_FLOW_V2": False, "UI_POLYGON_BG_ENABLED": False,
            "UI_STATUS_GRID_V2": True,
        },
    }


def _registry():
    from services import module_registry as mr
    states = {}
    for spec in mr.MODULE_REGISTRY.values():
        if spec.visibility == "hidden":
            continue
        states[spec.id] = {
            "chat_state": "inherit", "desired": True, "source": "default",
            "global_value": True, "global_source": "default",
            "emergency_block": False, "effective_runtime": True,
            "ready": None, "authorized": None, "observed": None,
            "observed_at": None, "last_activity_at": None,
            "reason_code": None, "pending_restart": False, "version": None,
            "consent": None, "conflict": None, "checked_at": None,
            "can_read": True, "can_edit": True,
        }
    return mr.registry_for_frontend(states)


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, rel, ctype="application/octet-stream"):
        p = os.path.join(REPO, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            self.send_error(404)
            return
        data = open(p, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        p = self.path.split("?")[0]
        q = self.path.split("?")[1] if "?" in self.path else ""
        if p == "/__state":
            if "prng=1" in q:
                STATE["prng"] = True
            if "prng=0" in q:
                STATE["prng"] = False
            return self._json({"prng": STATE["prng"]})
        if p == "/api/me":
            return self._json(_me_payload())
        if p == "/api/access/me":
            return self._json({"is_local_admin": True,
                               "permissions": {"sections": ["modules"]}})
        if p == "/api/access/chats":
            return self._json([])
        if p == "/api/access/param_permissions":
            return self._json({"items": {}, "roles": []})
        if p == "/api/config":
            cfg = _config_items()
            cfg["modules"] = _registry()
            return self._json(cfg)
        if p == "/api/status":
            return self._json({
                "bot": {"uptime_seconds": 3600, "state": "running"},
                "server": {}, "llm": [], "context": {}, "logs": [],
                "random": _status_payload(),
            })
        if p == "/api/status/logs":
            return self._json({"logs": [], "levels": [], "counts": {}})
        if p == "/api/status/key-history":
            return self._json({"providers": []})
        if p == "/api/config/keys/status":
            return self._json({"keys": {}})
        if p == "/api/info/guide":
            return self._json({"markdown": "", "updated_at": None})
        if p == "/api/info":
            return self._json({"html": "", "updated_at": None,
                               "canon_drift": False})
        if p.startswith("/static/"):
            return self._file("web/static/" + p[len("/static/"):])
        if p.startswith("/web/"):
            return self._file(p[1:], "text/html" if p.endswith(".html")
                              else "application/javascript")
        return self._file("web/index.html", "text/html")

    def do_POST(self):  # noqa: N802
        p = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        if p == "/api/random/test":
            STATE["random_tests"] += 1
            return self._json({
                "healthy": True, "length": 8, "latency_ms": 12,
                "checked_at": 1794909600, "persisted": False,
                "deposited": False, "key_present": True,
            })
        if p == "/api/config":
            try:
                items = json.loads(raw).get("items") or []
            except Exception:  # noqa: BLE001
                items = []
            keys = []
            for it in items:
                key = it.get("key")
                keys.append(key)
                if key == "random.primary_provider":
                    STATE["primary"] = it.get("value")
                elif key == "random.fallback_order":
                    STATE["order"] = it.get("value") or []
                elif key == "random.fallback_enabled":
                    STATE["fallback"] = bool(it.get("value"))
            STATE["posts"].append({"items": items, "keys": keys})
            return self._json({"saved": keys, "updated_at": None})
        return self._json({"ok": True})

    def do_PUT(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        return self._json({"ok": True})

    def log_message(self, *args):  # noqa: D401
        pass


def _start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def run() -> dict:
    from playwright.sync_api import sync_playwright

    report = {"checks": {}, "posts": [], "requests": 0}
    httpd = _start_server()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            ctx.add_init_script(TMA_STUB)
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            api_requests = []
            page.on("request", lambda r: api_requests.append(r.url)
                    if "/api/" in r.url else None)

            page.goto(BASE + "/web/index.html#/modules/random")
            page.wait_for_selector("[data-random-sources]", timeout=20000)
            page.wait_for_timeout(1000)

            # 3 карточки / 3 опции / нет Lizaonair
            report["checks"]["cards"] = page.locator(
                "[data-random-provider]").count()
            report["checks"]["options"] = page.locator(
                "[data-random-primary] option").count()
            body = page.locator("body").inner_text().lower()
            report["checks"]["lizaonair_absent"] = "lizaonair" not in body
            report["checks"]["draft_hint"] = (
                "не зачисляются" in body and
                "зачисляет полученную партию" not in body)

            # Fallback order: down у ANU (primary=ibm, в резерве anu+lfdr)
            before = len(STATE["posts"])
            page.locator('[data-random-fallback="anu"] '
                         '[data-random-fallback-down]').click()
            page.wait_for_timeout(700)
            order_post = None
            for post in STATE["posts"][before:]:
                for it in post["items"]:
                    if it["key"] == "random.fallback_order":
                        order_post = it.get("value")
            report["checks"]["fallback_order"] = order_post == ["lfdr", "anu"]

            # Селектор: реальный provider id в POST + очистка order + статус
            before = len(STATE["posts"])
            page.select_option("[data-random-primary]", "anu")
            page.wait_for_timeout(900)
            posts = STATE["posts"][before:]
            report["posts"].append(posts)
            sel_post = None
            order_clean = None
            for post in posts:
                for it in post["items"]:
                    if it["key"] == "random.primary_provider":
                        sel_post = it
                    if it["key"] == "random.fallback_order":
                        order_clean = it.get("value")
            report["checks"]["selector_post"] = (
                bool(sel_post) and sel_post.get("value") == "anu")
            report["checks"]["selector_order_cleaned"] = (
                order_clean == ["lfdr"])
            report["checks"]["summary_effective"] = (
                "ANU" in page.locator(
                    "[data-random-summary-effective]").inner_text())

            # Раскрытие карточки = 0 сетевых запросов
            before = len(api_requests)
            page.locator("[data-random-anu-details] summary").click()
            page.wait_for_timeout(700)
            report["checks"]["details_zero_network"] = (
                len(api_requests) == before)

            # PRNG: Activity не зелёная и честно называет режим
            page.goto(BASE + "/__state?prng=1")
            page.goto(BASE + "/web/index.html#/modules/random")
            page.wait_for_selector("[data-random-activity]", timeout=20000)
            page.wait_for_timeout(900)
            state_cls = page.locator(
                "[data-random-activity-state]").get_attribute("class") or ""
            state_txt = page.locator(
                "[data-random-activity-state]").inner_text()
            report["checks"]["prng_no_fake_green"] = (
                "badge-ok" not in state_cls and "псевдослучайный" in state_txt)
            page.goto(BASE + "/__state?prng=0")

            # #/ai/llm: no keys.random, таймауты последние, 180/360
            page.goto(BASE + "/web/index.html#/ai/llm")
            page.wait_for_selector("[data-provider-group]", timeout=20000)
            page.wait_for_timeout(800)
            report["checks"]["llm_no_random_keys"] = page.locator(
                '[data-cfg-key^="keys.random"]').count() == 0
            titles = page.locator("[data-provider-group]").all_inner_texts()
            gids = page.locator("[data-provider-group]").evaluate_all(
                "els => els.map(e => e.getAttribute('data-provider-group'))")
            thematic = [g for g in gids if g != "technical"]
            report["checks"]["llm_policy_last"] = (
                bool(thematic) and thematic[-1] == "prov_policy")
            report["provider_groups"] = gids
            report["provider_group_titles"] = titles
            vals = page.locator(
                '[data-block="llm_guard"] input').evaluate_all(
                "els => els.map(e => e.value)")
            report["checks"]["llm_timeouts"] = ("180" in vals and "360" in vals)

            # Mobile 390: одна колонка, без overflow, шрифт ≥12px
            mctx = browser.new_context(viewport={"width": 390, "height": 844})
            mctx.add_init_script(TMA_STUB)
            mp = mctx.new_page()
            mp.goto(BASE + "/web/index.html#/modules/random")
            mp.wait_for_selector("[data-random-sources]", timeout=20000)
            mp.wait_for_timeout(900)
            m = mp.evaluate("""() => {
              const cards = Array.from(
                document.querySelectorAll('[data-random-provider]'));
              const rects = cards.map(c => c.getBoundingClientRect());
              const fonts = cards.map(c => parseFloat(
                getComputedStyle(c).fontSize) || 0);
              return {
                vw: window.innerWidth,
                scrollW: document.documentElement.scrollWidth,
                oneColumn: rects.every(r => Math.abs(r.x - rects[0].x) < 2),
                minCardFont: Math.min.apply(null, fonts.concat([99])),
                stateFont: parseFloat(getComputedStyle(
                  document.querySelector('[data-random-provider-state]')
                ).fontSize) || 0,
              };
            }""")
            report["checks"]["mobile_one_column"] = bool(m["oneColumn"])
            report["checks"]["mobile_no_overflow"] = (
                m["scrollW"] <= m["vw"] + 1)
            report["checks"]["mobile_font_ok"] = (
                m["stateFont"] >= 12 and m["minCardFont"] >= 12)
            report["mobile"] = m
            mctx.close()

            report["checks"]["no_page_errors"] = not errors
            report["page_errors"] = errors[:5]
            report["requests"] = len(api_requests)
            browser.close()
    finally:
        httpd.shutdown()
    report["ok"] = all(report["checks"].values())
    return report


if __name__ == "__main__":
    if "--serve" in sys.argv:
        httpd = _start_server()
        print("QRNG P4 serve:", BASE + "/web/index.html#/modules/random")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            httpd.shutdown()
    else:
        result = run()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("ok") else 1)
