# -*- coding: utf-8 -*-
"""QRNG UI-08..10 — Playwright visual/behavior gate for «Случайность».

Загружает реальные `web/index.html` + `web/app.js` со статического сервера;
`/api/*` — детерминированные DTO существующих контрактов (без backend/DB).
Проверяет 1440/1280/390/320: overflow, page/console errors, один источник /
один тумблер / одна последовательность, три различимых состояния
(разрешён / проверен / используется), закрытые details, понятные действия
(правка резерва Save/Cancel, отключение резерва, смена источника).

Запуск:
  .venv\\Scripts\\python.exe tools/ui_qrng_ux0810_e2e.py
  .venv\\Scripts\\python.exe tools/ui_qrng_ux0810_e2e.py --serve
  --out DIR   сохранить скриншоты (viewport, jpeg q=70)

JSON-отчёт — stdout, exit 1 при провале любой проверки.
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

PORT = int(os.environ.get("QRNG_UX0810_PORT", "8798"))
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
window.__qrngErrors = [];
window.addEventListener('error', function (e) {
  window.__qrngErrors.push(String((e && e.message) || e));
});
window.addEventListener('unhandledrejection', function (e) {
  window.__qrngErrors.push('unhandledrejection: ' + String(e && e.reason));
});
"""

STATE = {
    "primary": "ibm_quantum",
    "order": ["anu", "lfdr"],
    "fallback": True,
    "inherit": False,
    "posts": [],
    "random_tests": 0,
}


def _config_items():
    from services import param_catalog as pc
    items = []
    values = {
        "random.primary_provider": STATE["primary"],
        "random.fallback_order": list(STATE["order"]),
        "random.fallback_enabled": bool(STATE["fallback"]),        "keys.random_quantum_api_key": {"configured": True, "last4": "Lz5l"},
        "keys.random_ibm_api_key": {"configured": True, "last4": "AB12"},
        "keys.random_ibm_crn": {"configured": True, "last4": "XY99"},
        "keys.random_ibm_instance": "open-instance",
        "keys.random_ibm_region": "us-east",
        "keys.random_ibm_channel": "ibm_quantum_platform",
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
    """Честная семантика P3: IBM сохранён, но не настроен; ANU доступен и
    фактически используется; LfDR разрешён в резерве, но не проверен."""
    primary = STATE["primary"]
    order = [p for p in STATE["order"] if p != primary]
    fallback_on = bool(STATE["fallback"])
    effective_order = [primary] + (order if fallback_on else [])
    configured = {"ibm_quantum": False, "anu": True, "lfdr": True}
    reserve = {"ibm_quantum": 0, "anu": 512, "lfdr": 7}
    effective = None
    for pid in effective_order:
        if configured.get(pid) or reserve.get(pid, 0) > 0:
            effective = pid
            break
    quantum = effective is not None
    mode = "quantum" if quantum else ("pseudorandom" if fallback_on
                                      else "deferred")
    blocker = None if quantum else "no_eligible_alternative"
    providers = [
        {"id": "ibm_quantum", "title": "IBM Quantum",
         "entropy_class": "hardware_quantum", "requires_key": True,
         "configured": False, "reserve": 0, "consumable": False,
         "quarantined": 0, "config_matches": True,
         "state": "provider_unconfigured", "last_error": None,
         "last_failure_at": None, "last_success_at": None,
         "last_job": None},
        {"id": "anu", "title": "ANU Quantum Numbers",
         "entropy_class": "hardware_quantum", "requires_key": True,
         "configured": True, "reserve": 512, "consumable": True,
         "quarantined": 0, "config_matches": True, "state": "active",
         "last_error": None, "last_failure_at": None,
         "last_success_at": 1794909600, "last_job": None},
        {"id": "lfdr", "title": "LfDR QRNG",
         "entropy_class": "hardware_quantum", "requires_key": False,
         "configured": True, "reserve": 7, "consumable": True,
         "quarantined": 2, "config_matches": True, "state": "unverified",
         "last_error": None, "last_failure_at": None,
         "last_success_at": None, "last_job": None},
    ]
    return {
        "enabled": True, "available": quantum, "quantum_active": quantum,
        "effective_source": mode, "effective_provider": effective,
        "primary_provider": primary,
        "primary_setting_raw": "" if STATE["inherit"] else primary,
        "primary_setting_state": "absent" if STATE["inherit"] else "set",
        "resolved_primary": effective,
        "fallback_enabled": fallback_on,
        "fallback_order": order,
        "fallback_order_raw": list(STATE["order"]),
        "fallback_order_state": "set",
        "effective_order": effective_order,
        "providers": providers,
        "provider_reserve": {"ibm_quantum": 0, "anu": 512, "lfdr": 7},
        "provider_quarantined": {"ibm_quantum": 0, "anu": 0, "lfdr": 2},
        "reserve_remaining": 519 if quantum else 0,
        "reserve_quarantined": 2,
        "buffer_max": 8192, "low_watermark": 256,
        "last_batch": {"batch_id": "b1", "provider": "ANU Quantum Numbers",
                       "provider_id": "anu", "data_type": "uint16",
                       "length": 1024, "created_at": 1794909600,
                       "config_matches": True},
        "draws": {"quantum": 37 if quantum else 0,
                  "pseudorandom": 3 if mode == "pseudorandom" else 0},
        "last_fallback_reason": "provider_unconfigured",
        "last_fallback_at": 1794909900,
        "blocker": blocker,
        "anu_state": "active", "lfdr_state": "unverified",
        "key_present": True, "key_fingerprint": "test",
        "prng_active": mode == "pseudorandom",
        "prng_setting": True, "plan": "Trial",
        "policy_version": "ui0810-e2e",
        "recent_draws": [], "recent_draws_scope": "global",
        "uses": {"enabled": True, "events": [], "cursor": None,
                 "scope": "global"},
    }


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


_MIME = {
    ".html": "text/html", ".js": "application/javascript", ".css": "text/css",
    ".json": "application/json", ".woff2": "font/woff2",
    ".woff": "application/font-woff", ".ttf": "font/ttf", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, rel, ctype=None):
        p = os.path.join(REPO, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            self.send_error(404)
            return
        if ctype is None:
            ctype = _MIME.get(os.path.splitext(rel)[1].lower(),
                              "application/octet-stream")
        data = open(p, "rb").read()
        headers = ctype
        if ctype.startswith("text/") or "javascript" in ctype \
                or "json" in ctype:
            headers += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", headers)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        p = self.path.split("?")[0]
        q = self.path.split("?")[1] if "?" in self.path else ""
        if p == "/__state":
            if "reset=1" in q:
                STATE.update({"primary": "ibm_quantum",
                              "order": ["anu", "lfdr"], "fallback": True,
                              "inherit": False, "posts": []})
            if "inherit=1" in q:
                STATE.update({"primary": "ibm_quantum",
                              "order": ["lfdr", "anu"], "fallback": True,
                              "inherit": True})
            return self._json({"primary": STATE["primary"],
                               "order": STATE["order"],
                               "inherit": STATE["inherit"],
                               "fallback": STATE["fallback"]})
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
                "checked_at": 1794909600, "persisted": True,
                "deposited": False, "key_present": True,
            })
        if p == "/api/config":
            try:
                items = json.loads(raw).get("items") or []
            except Exception:  # noqa: BLE001
                items = []
            keys = [it.get("key") for it in items]
            STATE["posts"].append({"items": items, "keys": keys})
            for it in items:
                key = it.get("key")
                if key == "random.primary_provider":
                    STATE["primary"] = it.get("value")
                elif key == "random.fallback_order":
                    STATE["order"] = it.get("value") or []
                elif key == "random.fallback_enabled":
                    STATE["fallback"] = bool(it.get("value"))
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


METRICS_JS = r"""() => {
  const main = document.querySelector('[data-random-summary]');
  const mainText = main ? main.innerText : '';
  const controls = document.querySelector('[data-random-controls]');
  const now = document.querySelector('[data-random-now]');
  const cr = controls ? controls.getBoundingClientRect() : null;
  const nr = now ? now.getBoundingClientRect() : null;
  const details = ['data-random-provider-details', 'data-random-diagnostics',
                   'data-random-uses', 'data-random-advanced']
    .map(k => {
      const d = document.querySelector('[' + k + ']');
      const body = d ? d.querySelector(':scope > div') : null;
      let bodyVisible = false;
      if (body) {
        bodyVisible = body.checkVisibility
          ? body.checkVisibility({checkOpacity: true,
                                  checkVisibilityCSS: true})
          : (body.getBoundingClientRect().height > 0
             && body.offsetParent !== null);
      }
      return {marker: k, present: !!d, open: !!(d && d.open),
              bodyVisible: bodyVisible};
    });
  const rows = Array.from(
    document.querySelectorAll('[data-random-provider-summary]'))
    .map(el => ({id: el.getAttribute('data-random-provider-summary'),
                 text: el.innerText,
                 used: !!el.querySelector(
                   '[data-random-provider-summary-used]'),
                 state: (el.querySelector(
                   '[data-random-provider-summary-state]') || {}).innerText,
                 reserve: (el.querySelector(
                   '[data-random-provider-summary-reserve]') || {}).innerText}));
  const seq = Array.from(
    document.querySelectorAll('[data-random-fallback]'))
    .map(el => ({id: el.getAttribute('data-random-fallback'),
                 checked: !!(el.querySelector(
                   '[data-random-fallback-include]') || {}).checked,
                 text: el.innerText}));
  const fonts = Array.from(main ? main.querySelectorAll('*') : [])
    .filter(el => (el.innerText || '').trim())
    .map(el => parseFloat(getComputedStyle(el).fontSize) || 0);
  return {
    vw: window.innerWidth,
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    pageErrors: (window.__qrngErrors || []).slice(),
    mainText: mainText,
    selectValue: (document.querySelector('[data-random-primary]') || {}).value,
    primaryHint: (document.querySelector('[data-random-setting-primary]') || {}).innerText || '',
    fallbackChip: (document.querySelector('[data-random-fallback-state]') || {}).innerText || '',
    fallbackNote: (document.querySelector('[data-random-fallback-note]') || {}).innerText || '',
    nowReason: (document.querySelector('[data-random-now-reason]') || {}).innerText || '',
    primaryCount: main ? main.querySelectorAll('[data-random-primary]').length : 0,
    toggleCount: main ? main.querySelectorAll(
      '[data-random-fallback-toggle]').length : 0,
    orderCount: main ? main.querySelectorAll(
      '[data-random-fallback-order]').length : 0,
    nowText: now ? now.innerText : '',
    controls: cr ? {x: cr.x, y: cr.y, w: cr.width, h: cr.height} : null,
    now: nr ? {x: nr.x, y: nr.y, w: nr.width, h: nr.height} : null,
    details: details,
    rows: rows,
    sequence: seq,
    minFont: fonts.length ? Math.min.apply(null, fonts) : 99,
    secretInputs: main ? main.querySelectorAll('input[type="password"]').length : 0,
    bodyText: document.body.innerText,
    workspaceChips: document.querySelectorAll('[data-workspace-chip]').length,
    workspaceStateVisible: !!document.querySelector('[data-workspace-state]'),
    usedOnPage: (document.body.innerText.match(/Сейчас используется/g) || []).length,
  };
}"""


FORBIDDEN = [
    "adapter_not_implemented", "адаптер не реализован", "P5B",
    "A. Источники", "B. Применения", "C. Активность", "D. Дополнительно",
    "Сохранённый:", "Заводской:", "Действующий резерв:",
    "Действующая цепочка:", "keys.random", "data-random",
]


def _check_page(page, viewport, shots_dir, report):
    prefix = "%sx%s" % (viewport["width"], viewport["height"])
    page.goto(BASE + "/__state?reset=1")
    page.goto(BASE + "/web/index.html#/modules/random")
    page.wait_for_selector("[data-random-summary]", timeout=20000)
    page.wait_for_timeout(900)
    m = page.evaluate(METRICS_JS)
    checks = report["checks"]
    checks[prefix + "_no_page_errors"] = not m["pageErrors"]
    checks[prefix + "_no_overflow"] = m["scrollW"] <= m["clientW"] + 1
    checks[prefix + "_one_primary"] = m["primaryCount"] == 1
    checks[prefix + "_one_toggle"] = m["toggleCount"] == 1
    checks[prefix + "_one_sequence"] = m["orderCount"] == 1
    checks[prefix + "_no_secret_on_main"] = m["secretInputs"] == 0
    checks[prefix + "_min_font_11_5"] = m["minFont"] >= 11.5
    checks[prefix + "_details_closed"] = all(
        (not d["open"]) and (not d["bodyVisible"])
        for d in m["details"] if d["present"])
    checks[prefix + "_details_present"] = all(d["present"] for d in m["details"])
    checks[prefix + "_primary_once"] = m["mainText"].count("Основной источник") == 1
    checks[prefix + "_toggle_once"] = (
        m["mainText"].count("Автоматическое резервирование") == 1)
    checks[prefix + "_sequence_once"] = (
        m["mainText"].count("Резервные источники") == 1)
    checks[prefix + "_used_once"] = m["mainText"].count("Сейчас используется") == 1
    checks[prefix + "_last_draw_once"] = (
        m["mainText"].count("Последнее успешное получение") == 1)
    checks[prefix + "_no_forbidden_main"] = all(
        needle not in m["mainText"] for needle in FORBIDDEN)
    checks[prefix + "_reason_attributed"] = (
        "переключение с IBM Quantum:" in m["nowReason"])
    checks[prefix + "_reason_not_unanchored"] = (
        m["nowReason"].strip() != "источник не настроен")
    checks[prefix + "_no_workspace_duplicate_chips"] = (
        m["workspaceChips"] == 0 and not m["workspaceStateVisible"])
    checks[prefix + "_used_once_on_page"] = m["usedOnPage"] == 1
    checks[prefix + "_no_factory_label_on_page"] = (
        "заводское значение" not in m["bodyText"])
    # Three distinct states: ANU used+verified, LfDR allowed but unverified,
    # IBM unconfigured.
    by_id = {r["id"]: r for r in m["rows"]}
    checks[prefix + "_three_provider_rows"] = (
        set(by_id) == {"ibm_quantum", "anu", "lfdr"})
    checks[prefix + "_anu_used_verified"] = (
        by_id.get("anu", {}).get("used") is True
        and "проверено" in (by_id.get("anu", {}).get("state") or ""))
    checks[prefix + "_lfdr_allowed_unverified"] = (
        by_id.get("lfdr", {}).get("used") is False
        and "не проверено" in (by_id.get("lfdr", {}).get("state") or ""))
    checks[prefix + "_ibm_not_used"] = (
        by_id.get("ibm_quantum", {}).get("used") is False)
    ibm_state = by_id.get("ibm_quantum", {}).get("state") or ""
    checks[prefix + "_ibm_not_verified"] = (
        ibm_state in ("не проверено", "не настроен"))
    checks[prefix + "_reserve_values"] = (
        "512" in (by_id.get("anu", {}).get("reserve") or "")
        and "7" in (by_id.get("lfdr", {}).get("reserve") or ""))
    seq = {r["id"]: r for r in m["sequence"]}
    checks[prefix + "_sequence_has_both"] = (
        seq.get("anu", {}).get("checked") is True
        and seq.get("lfdr", {}).get("checked") is True)
    # Desktop: two columns; mobile: stacked.
    if viewport["width"] >= 768:
        checks[prefix + "_two_columns"] = bool(
            m["controls"] and m["now"]
            and abs(m["controls"]["x"] - m["now"]["x"]) > 50
            and abs(m["controls"]["y"] - m["now"]["y"]) < 40)
    else:
        checks[prefix + "_stacked"] = bool(
            m["controls"] and m["now"]
            and m["now"]["y"] >= m["controls"]["y"] + m["controls"]["h"] - 4)
        checks[prefix + "_controls_fit"] = bool(
            m["controls"] and m["controls"]["w"] <= m["vw"] - 20)
    report["viewports"][prefix] = {
        "scrollW": m["scrollW"], "clientW": m["clientW"],
        "minFont": round(m["minFont"], 1),
        "rows": m["rows"], "sequence": m["sequence"],
        "details": m["details"], "now": m["nowText"][:300],
        "pageErrors": m["pageErrors"][:5],
    }
    if shots_dir:
        page.screenshot(path=os.path.join(
            shots_dir, "playwright-%s.jpg" % prefix),
            type="jpeg", quality=65)


def _check_interactions(page, report, api_requests):
    checks = report["checks"]
    posts_before = len(STATE["posts"])
    # Draft: down arrow changes only the draft; Save posts the full order.
    page.locator('[data-random-fallback="anu"] '
                 '[data-random-fallback-down]').click()
    page.wait_for_timeout(300)
    checks["draft_bar_visible"] = page.locator(
        "[data-random-fallback-draft-bar]").is_visible()
    checks["draft_no_post"] = len(STATE["posts"]) == posts_before
    page.locator("[data-random-fallback-cancel]").click()
    page.wait_for_timeout(200)
    checks["cancel_closes_draft"] = page.locator(
        "[data-random-fallback-draft-bar]").count() == 0
    page.locator('[data-random-fallback="anu"] '
                 '[data-random-fallback-down]').click()
    page.wait_for_timeout(200)
    page.locator("[data-random-fallback-save]").click()
    page.wait_for_timeout(900)
    order_posts = [it for post in STATE["posts"][posts_before:]
                   for it in post["items"]
                   if it.get("key") == "random.fallback_order"]
    checks["save_posts_full_order"] = bool(order_posts) and (
        order_posts[-1].get("value") == ["lfdr", "anu"])
    checks["draft_closed_after_save"] = page.locator(
        "[data-random-fallback-draft-bar]").count() == 0

    # Explicit fallback off is distinguishable from inheritance.
    posts_before = len(STATE["posts"])
    page.locator('.ctl-toggle:has([data-random-fallback-toggle])').click()
    page.wait_for_timeout(900)
    checks["fallback_off_posted"] = any(
        it.get("key") == "random.fallback_enabled"
        and it.get("value") is False
        for post in STATE["posts"][posts_before:] for it in post["items"])
    checks["fallback_off_label"] = "выключено" in page.locator(
        "[data-random-fallback-switch-state]").inner_text()
    checks["fallback_off_note"] = "отключён вручную" in page.locator(
        "[data-random-fallback-note]").inner_text()
    page.locator('.ctl-toggle:has([data-random-fallback-toggle])').click()
    page.wait_for_timeout(900)

    # Primary selector posts the real provider id.
    posts_before = len(STATE["posts"])
    page.select_option("[data-random-primary]", "lfdr")
    page.wait_for_timeout(900)
    primary_posts = [it for post in STATE["posts"][posts_before:]
                     for it in post["items"]
                     if it.get("key") == "random.primary_provider"]
    checks["primary_posts_real_id"] = bool(primary_posts) and (
        primary_posts[-1].get("value") == "lfdr")

    # Expanding keys does not make network requests and keeps secrets masked.
    page.wait_for_timeout(1200)  # let the post-save config/status reload settle
    requests_before = len(api_requests)
    page.locator("[data-random-provider-details] > summary").click()
    page.wait_for_timeout(400)
    checks["keys_open_on_demand"] = page.locator(
        '[data-random-provider="ibm_quantum"]').is_visible()
    checks["keys_expand_zero_network"] = (
        len(api_requests) == requests_before)
    report["keys_expand_request_delta"] = (
        len(api_requests) - requests_before)
    report["keys_expand_requests"] = list(api_requests[requests_before:])
    secret_values = page.locator(
        '[data-random-provider-details] input[type="password"]'
    ).evaluate_all("els => els.map(e => e.value)")
    checks["secrets_masked"] = all(
        (v or "").strip() == "" or "•" in v for v in secret_values)
    requests_before_collapse = len(api_requests)
    page.locator("[data-random-provider-details] > summary").click()
    page.wait_for_timeout(300)
    checks["keys_collapse_zero_network"] = (
        len(api_requests) == requests_before_collapse)
    report["keys_collapse_request_delta"] = (
        len(api_requests) - requests_before_collapse)

    page.locator("[data-random-diagnostics] > summary").click()
    page.wait_for_timeout(300)
    diag = page.locator("[data-random-diagnostics]").inner_text()
    checks["diagnostics_has_raw"] = (
        "provider_unconfigured" in diag
        and "Действующая цепочка:" in diag
        and "Сохранённый резерв:" in diag)
    page.locator("[data-random-diagnostics] > summary").click()
    report["interaction_posts"] = [
        {"keys": p.get("keys"), "items": p.get("items")}
        for p in STATE["posts"]]
    page.goto(BASE + "/__state?reset=1")


def _check_inherited_saved(page, prefix, report):
    """F-UI0810-R1-01: наследуемый primary + явный непустой резерв."""
    page.goto(BASE + "/__state?reset=1&inherit=1")
    page.goto(BASE + "/web/index.html#/modules/random")
    page.wait_for_selector("[data-random-summary]", timeout=20000)
    page.wait_for_timeout(900)
    m = page.evaluate(METRICS_JS)
    checks = report["checks"]
    checks[prefix + "_inherited_select_factory"] = (
        m["selectValue"] == "ibm_quantum"
        and "По умолчанию" in m["primaryHint"])
    checks[prefix + "_inherited_saved_chip"] = (
        m["fallbackChip"].strip() == "сохранено вручную")
    by_id = {r["id"]: r for r in m["rows"]}
    checks[prefix + "_inherited_saved_effective"] = (
        "LfDR" in (m["nowText"].splitlines()[1] if m["nowText"] else "")
        and by_id.get("lfdr", {}).get("used") is True
        and by_id.get("anu", {}).get("used") is False)
    checks[prefix + "_inherited_saved_note"] = (
        "Сохранён ваш порядок" in m["fallbackNote"]
        and "заводская цепочка" not in m["fallbackNote"])
    checks[prefix + "_inherited_reason_attributed"] = (
        "переключение с IBM Quantum:" in m["nowReason"])
    report["inherited_saved"] = {
        "viewport": prefix, "select": m["selectValue"],
        "hint": m["primaryHint"], "chip": m["fallbackChip"],
        "note": m["fallbackNote"], "reason": m["nowReason"],
        "rows": m["rows"],
    }
    page.goto(BASE + "/__state?reset=1")


def run(shots_dir=None) -> dict:
    from playwright.sync_api import sync_playwright

    report = {"checks": {}, "viewports": {}, "api_requests": 0}
    if shots_dir:
        os.makedirs(shots_dir, exist_ok=True)
    httpd = _start_server()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for viewport in ({"width": 1440, "height": 900},
                             {"width": 1280, "height": 800},
                             {"width": 390, "height": 844},
                             {"width": 320, "height": 700}):
                ctx = browser.new_context(viewport=viewport)
                ctx.add_init_script(TMA_STUB)
                page = ctx.new_page()
                errors = []
                console_errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda msg: console_errors.append(msg.text)
                        if msg.type == "error" else None)
                api = []
                page.on("request", lambda r: api.append(r.url)
                        if "/api/" in r.url else None)
                _check_page(page, viewport, shots_dir, report)
                report["api_requests"] = max(report["api_requests"], len(api))
                report["checks"]["viewport_%sx%s_no_console_errors" % (
                    viewport["width"], viewport["height"])] = (
                        not errors and not console_errors)
                report["viewports"]["%sx%s" % (
                    viewport["width"], viewport["height"])]["consoleErrors"] = (
                        errors + console_errors)[:5]
                ctx.close()
            # Interactions once at desktop width.
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            ctx.add_init_script(TMA_STUB)
            page = ctx.new_page()
            errors = []
            console_errors = []
            interaction_api = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda msg: console_errors.append(msg.text)
                    if msg.type == "error" else None)
            page.on("request", lambda r: interaction_api.append(r.url)
                    if "/api/" in r.url else None)
            page.goto(BASE + "/__state?reset=1")
            page.goto(BASE + "/web/index.html#/modules/random")
            page.wait_for_selector("[data-random-summary]", timeout=20000)
            page.wait_for_timeout(900)
            report["checks"]["interaction_no_page_errors"] = not errors
            report["checks"]["interaction_no_console_errors"] = (
                not console_errors)
            report["interaction_errors"] = (errors + console_errors)[:5]
            _check_interactions(page, report, interaction_api)
            ctx.close()
            # F-01 fixed-state render at desktop and mobile.
            for viewport in ({"width": 1440, "height": 900},
                             {"width": 390, "height": 844}):
                vctx = browser.new_context(viewport=viewport)
                vctx.add_init_script(TMA_STUB)
                vpage = vctx.new_page()
                _check_inherited_saved(
                    vpage, "%sx%s" % (viewport["width"], viewport["height"]),
                    report)
                vctx.close()
            browser.close()
    finally:
        httpd.shutdown()
    report["ok"] = all(report["checks"].values())
    return report


if __name__ == "__main__":
    shots = None
    if "--out" in sys.argv:
        shots = sys.argv[sys.argv.index("--out") + 1]
    if "--serve" in sys.argv:
        httpd = _start_server()
        print("QRNG UX-08..10 serve:", BASE + "/web/index.html#/modules/random")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            httpd.shutdown()
    else:
        result = run(shots)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("ok") else 1)
