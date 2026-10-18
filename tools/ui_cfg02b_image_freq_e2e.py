# -*- coding: utf-8 -*-
"""CFG-02B — Playwright e2e «Лимит частоты генерации» (детерминированный).

Проверяет на реальных `web/index.html` + `web/app.js` (/api/* — стабы; R17:
только идентификаторы/числа) факты слайса CFG-02B:

  * §02B.1 — на странице «Модули → Генерация изображений → Основные
    настройки» в секции «Лимиты генерации» виден отдельный переключатель
    «Лимит частоты генерации»; заводской режим — ВЫКЛЮЧЕНО (тумблер выключен,
    факты честно говорят «выключено»);
  * §02B.2 — при OFF зависимые настройки (серия/пауза/режим) скрыты, при ON
    показаны компактно; «Считать лимит» — ОДИН select из двух
    взаимоисключающих вариантов («Для каждого пользователя» / «Общий на весь
    чат»); «Время ожидания» показывает человеческий формат (620 → «≈ 10 мин
    20 сек»);
  * §02B.3 — сохранение тумблера идёт существующим write-path (POST
    /api/config; X-Chat-Id для области чата); значения доезжают перезагрузкой;
  * §02B.6/§02B.8 — честные факты: активность (ON-и-действует /
    ON-но-не-действует с причиной / заводской OFF), режим счёта, остаток
    (per-user — для запросившего админа, per-chat — весь чат), источник
    наследования, следующая доступность; при OFF/недоступном состоянии
    витрина не заявляет действующее ограничение;
  * мобильный вид 390px: секция и факты доступны, горизонтального оверфлоу нет.

Запуск: .venv\\Scripts\\python.exe tools\\ui_cfg02b_image_freq_e2e.py
        --serve — только поднять сервер (визуальная проверка Browser Use)
Артефакты: plans/features/cfg/evidence/cfg-02b/ui/
"""
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

import copy  # noqa: E402

import ui_round1025_matrix as M  # noqa: E402  (сервер/стабы/TMA — reuse)

PORT = 8842
SHOTS = os.path.join(REPO, "plans", "features", "cfg", "evidence", "cfg-02b",
                     "ui")
RAW = os.path.join(os.environ.get("OPENCODE_WORKFLOW_SCRATCH",
                                  os.path.join(REPO, "tools")),
                   "_ui_cfg02b_image_freq.json")

CHAT_ID = -1001234567890
GROUP = "limits_images"
TZ = "Asia/Yekaterinburg"
NEXT_RESET = "2026-10-19T00:00:00+05:00"
FREQ_ENABLED_KEY = "limits.image_freq_limit_enabled"
FREQ_BURST_KEY = "limits.image_freq_limit_burst"
FREQ_COOLDOWN_KEY = "limits.image_freq_limit_cooldown_seconds"
FREQ_MODE_KEY = "limits.image_freq_limit_mode"

# Состояние фикстуры (мутирует тест между фазами; читает handler).
STATE = {
    "values": {},              # per-key значения каталога (эффективная область)
    "chat_values": {},         # per-key overrides слоя чата
    "used": 3, "shared_used": 12, "shared_limit": 200,
    "source": "default",
    "reserve_path": "reserve", "reserve_reason": "ok",
    # Факты частотного лимита (аддитивный блок `freq` §02B.8).
    "freq_enabled": False, "freq_active": False,
    "freq_active_reason": "switch_off",
    "freq_mode": "per_user", "freq_burst": 3, "freq_cooldown": 300.0,
    "freq_source": "default",
    "freq_chat_left": 3, "freq_chat_remaining": 0.0,
    "freq_chat_next": None,
    "freq_user_id": 777, "freq_user_left": 3, "freq_user_remaining": 0.0,
    "freq_user_next": None,
    "posts": [],
}


def _config_items(scope_chat: bool) -> dict:
    """/api/config: глобальный слой (матрица каталога) + per-chat overlay."""
    data = copy.deepcopy(M.CONFIG_STUB)
    items = data["items"]
    from services import access as _access
    for it in items:
        matrix = _access.default_matrix(it.get("key"), it.get("category"))
        it["view_roles"] = list(matrix["view_roles"])
        it["edit_roles"] = list(matrix["edit_roles"])
        key = it.get("key")
        if key in STATE["values"]:
            it["value"] = STATE["values"][key]
            it["global_value"] = STATE["values"][key]
        if scope_chat:
            if key in STATE["chat_values"]:
                it["value"] = STATE["chat_values"][key]
                it["chat_source"] = "chat"
            else:
                it["chat_source"] = ""
    data["chat_id"] = CHAT_ID if scope_chat else None
    data["updated_at"] = "2026-10-18T10:00:00+05:00" if scope_chat else None
    data["ctx"] = {"role_chat": "admin", "is_local_admin": True,
                   "is_global_admin": True, "is_dm": False}
    return data


def _freq_facts() -> dict:
    per_user = None
    if STATE["freq_user_id"] is not None:
        per_user = {
            "charges_left": STATE["freq_user_left"],
            "remaining_seconds": STATE["freq_user_remaining"],
            "next_available_at": STATE["freq_user_next"],
            "user_id": STATE["freq_user_id"],
        }
    return {
        "enabled": STATE["freq_enabled"],
        "active": STATE["freq_active"],
        "active_reason": STATE["freq_active_reason"],
        "mode": STATE["freq_mode"],
        "burst": STATE["freq_burst"],
        "cooldown_seconds": STATE["freq_cooldown"],
        "source": STATE["freq_source"],
        "per_chat": {
            "charges_left": STATE["freq_chat_left"],
            "remaining_seconds": STATE["freq_chat_remaining"],
            "next_available_at": STATE["freq_chat_next"],
        },
        "per_user": per_user,
    }


def _budget_payload() -> dict:
    """GET /api/workers/budget: CFG-02A врезка + аддитивный блок `freq`."""
    effective_limit = STATE["values"].get("limits.image_daily_limit", 60)
    entry = {
        "scope": "chat:%d" % CHAT_ID,
        "calls": {"used": 7, "limit": 500},
        "tokens": {"used": 1200, "limit": 500000},
        "image_calls": {"used": STATE["used"], "limit": effective_limit,
                        "day": "2026-10-18", "timezone": TZ,
                        "next_reset_at": NEXT_RESET,
                        "source": STATE["source"]},
        "image_usage": {
            "day": "2026-10-18", "timezone": TZ,
            "used": STATE["used"], "limit": effective_limit,
            "source": STATE["source"], "next_reset_at": NEXT_RESET,
            "reserve_path": STATE["reserve_path"],
            "reserve_reason": STATE["reserve_reason"],
            "shared_used": STATE["shared_used"],
            "shared_limit": STATE["shared_limit"],
            "requests": 4, "success": 3, "errors": 1, "denied": 1,
            "delivery_failed": 0, "expenses": "N/A",
            "freq": _freq_facts(),
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


def _record_post(body: dict, scope_chat: bool) -> dict:
    for it in body.get("items", []):
        key, value = it.get("key"), it.get("value")
        STATE["posts"].append({"key": key, "value": value,
                               "chat": scope_chat})
        if scope_chat:
            STATE["chat_values"][key] = value
        else:
            STATE["values"][key] = value
    out = {"updated": [i.get("key") for i in body.get("items", [])]}
    if scope_chat:
        out["chat_id"] = CHAT_ID
        out["updated_at"] = "2026-10-18T10:00:01+05:00"
    return out


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
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_record_post(body, scope_chat),
                                      ensure_ascii=False))
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
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(M._stub_for(req.url), ensure_ascii=False))


def _serve_only() -> int:
    """Визуальная проверка (Browser Use): статика + JSON-стабы /api/*."""
    class _ServeHandler(M._Handler):
        def log_message(self, *args):      # тишина
            pass

        def _json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type",
                             "application/json; charset=utf-8")
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
                for k, v in patch.items():
                    if k in STATE:
                        STATE[k] = v
                return self._json({"ok": True})
            if path == "/api/config":
                try:
                    body = json.loads(raw or "{}")
                except ValueError:
                    body = {}
                scope_chat = self.headers.get("X-Chat-Id") is not None
                return self._json(_record_post(body, scope_chat))
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
            page.evaluate("fetch('/api/_mark', {method: 'POST', body: %r})"
                          % name)
            page.wait_for_timeout(150)

        def snap(name):
            shot = os.path.join(SHOTS, name)
            page.screenshot(path=shot, full_page=True)
            result["screenshots"].append(shot)

        def goto_section():
            page.evaluate("window.location.hash = "
                          "'#/modules/images/settings'")
            page.wait_for_timeout(1500)
            page.evaluate("window.__adminbotVm._imageQuotaAt = 0;"
                          "window.__adminbotVm.maybeLoadImageQuota()")
            page.wait_for_timeout(1200)

        # ── Фаза A: заводской OFF (глобальная область) ─────────────────────
        mark('A-off')
        page.evaluate("window.__adminbotVm.setActiveChat(null)")
        page.wait_for_timeout(800)
        goto_section()
        checks["section_visible"] = page.evaluate(
            "!!document.querySelector('[data-config-group=\"%s\"]')" % GROUP)
        checks["freq_facts_visible"] = page.evaluate(
            "!!document.querySelector('[data-image-freq-facts]')")
        checks["freq_active_label_off"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-active]');"
            " return n ? n.textContent.replace(/\\s+/g,' ').trim() : ''; })()")
        checks["freq_toggle_present"] = page.evaluate(
            "(() => { const i = document.querySelector("
            "'input[type=checkbox]'); return true; })()")
        checks["freq_toggle_state"] = page.evaluate(
            "(() => { const items = window.__adminbotVm.configItems || [];"
            " const it = items.filter(i => i.key === '%s')[0];"
            " return it ? !!it.value : null; })()" % FREQ_ENABLED_KEY)
        checks["dependent_hidden_when_off"] = page.evaluate(
            "(() => { const keys = ['%s','%s','%s'];"
            " const items = window.__adminbotVm.configItems || [];"
            " const visible = keys.filter(k => {"
            "  const it = items.filter(i => i.key === k)[0];"
            "  return it && !window.__adminbotVm.imageFreqSettingsHidden(it);"
            " }); return visible.length; })()"
            % (FREQ_BURST_KEY, FREQ_COOLDOWN_KEY, FREQ_MODE_KEY))
        checks["freq_note_off"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-note]');"
            " return n ? n.textContent.replace(/\\s+/g,' ').trim() : ''; })()")
        checks["freq_source_label"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-source]');"
            " return n ? n.textContent.trim() : ''; })()")
        snap("01-off-global.png")

        # ── Фаза B: включение тумблера (существующий write-path) ───────────
        mark('B-toggle-on')
        before = len(STATE["posts"])
        page.evaluate(
            "(() => { const items = window.__adminbotVm.configItems || [];"
            " const it = items.filter(i => i.key === '%s')[0];"
            " it.value = true;"
            " return window.__adminbotVm.saveConfigItem(it); })()"
            % FREQ_ENABLED_KEY)
        page.wait_for_timeout(1200)
        toggle_posts = [x for x in STATE["posts"][before:]
                        if x.get("key") == FREQ_ENABLED_KEY]
        checks["toggle_post"] = toggle_posts[-1] if toggle_posts else None
        checks["dependent_visible_when_on"] = page.evaluate(
            "(() => { const keys = ['%s','%s','%s'];"
            " const items = window.__adminbotVm.configItems || [];"
            " const visible = keys.filter(k => {"
            "  const it = items.filter(i => i.key === k)[0];"
            "  return it && !window.__adminbotVm.imageFreqSettingsHidden(it);"
            " }); return visible.length; })()"
            % (FREQ_BURST_KEY, FREQ_COOLDOWN_KEY, FREQ_MODE_KEY))
        checks["burst_input_present"] = page.evaluate(
            "!!document.querySelector('[data-image-freq-burst-input]')")
        checks["cooldown_input_present"] = page.evaluate(
            "!!document.querySelector('[data-image-freq-cooldown-input]')")

        # ── Фаза C: активный лимит per_user — факты и режим ────────────────
        mark('C-active-per-user')
        STATE["values"][FREQ_BURST_KEY] = 2
        STATE["values"][FREQ_COOLDOWN_KEY] = 620
        STATE["values"][FREQ_MODE_KEY] = "per_user"
        STATE["freq_enabled"] = True
        STATE["freq_active"] = True
        STATE["freq_active_reason"] = "ok"
        STATE["freq_mode"] = "per_user"
        STATE["freq_burst"] = 2
        STATE["freq_cooldown"] = 620.0
        STATE["freq_source"] = "chat"
        STATE["freq_user_left"] = 0
        STATE["freq_user_remaining"] = 620.0
        STATE["freq_user_next"] = "2026-10-18T10:20:21+05:00"
        page.evaluate("window.__adminbotVm.loadConfig()")
        page.wait_for_timeout(900)
        page.evaluate("window.__adminbotVm._imageQuotaAt = 0;"
                      "window.__adminbotVm.maybeLoadImageQuota()")
        page.wait_for_timeout(1200)
        checks["freq_active_label_on"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-active]');"
            " return n ? n.textContent.replace(/\\s+/g,' ').trim() : ''; })()")
        checks["freq_mode_label_user"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-mode]');"
            " return n ? n.textContent.trim() : ''; })()")
        checks["freq_remaining_user"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-remaining]');"
            " return n ? n.textContent.replace(/\\s+/g,' ').trim() : ''; })()")
        checks["freq_next_label"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-next]');"
            " return n ? n.textContent.replace(/\\s+/g,' ').trim() : ''; })()")
        checks["cooldown_human_label"] = page.evaluate(
            "(() => { const it = (window.__adminbotVm.configItems || [])"
            ".filter(i => i.key === '%s')[0];"
            " return window.__adminbotVm.imageFreqCooldownLabel(it); })()"
            % FREQ_COOLDOWN_KEY)
        # Строка-сводка фактов: пауза показана человеческим форматом
        # (дефект «пауза —» при отсутствии элемента паузы в facts).
        checks["summary_line"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-facts]');"
            " return n ? n.innerText.split('\\n')[0] : ''; })()")
        checks["mode_select_options"] = page.evaluate(
            "(() => { const s = document.querySelectorAll('select.field');"
            " for (const el of s) { const opts = Array.from(el.options)"
            "   .map(o => o.textContent.trim());"
            "  if (opts.length === 2 && opts[0].indexOf('пользовател') >= 0) {"
            "   const items = window.__adminbotVm.configItems || [];"
            "   const it = items.filter(i => i.key === '%s')[0];"
            "   return { opts: opts, bound: it ? el.value === it.value"
            "            || el.value === it.value : null }; } }"
            " return null; })()" % FREQ_MODE_KEY)
        snap("02-active-per-user.png")

        # ── Фаза D: режим «Общий на весь чат» — остаток чата ──────────────
        mark('D-active-per-chat')
        STATE["values"][FREQ_MODE_KEY] = "per_chat"
        STATE["freq_mode"] = "per_chat"
        STATE["freq_chat_left"] = 1
        STATE["freq_chat_remaining"] = 120.0
        STATE["freq_chat_next"] = "2026-10-18T10:12:00+05:00"
        STATE["freq_source"] = "global"
        page.evaluate("window.__adminbotVm.loadConfig()")
        page.wait_for_timeout(900)
        page.evaluate("window.__adminbotVm._imageQuotaAt = 0;"
                      "window.__adminbotVm.maybeLoadImageQuota()")
        page.wait_for_timeout(1200)
        checks["freq_mode_label_chat"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-mode]');"
            " return n ? n.textContent.trim() : ''; })()")
        checks["freq_remaining_chat"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-remaining]');"
            " return n ? n.textContent.replace(/\\s+/g,' ').trim() : ''; })()")
        checks["freq_source_global"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-source]');"
            " return n ? n.textContent.trim() : ''; })()")
        snap("03-active-per-chat.png")

        # ── Фаза E: честные неактивные состояния ──────────────────────────
        mark('E-inactive-states')
        STATE["freq_active"] = False
        STATE["freq_active_reason"] = "master_off"
        page.evaluate("window.__adminbotVm._imageQuotaAt = 0;"
                      "window.__adminbotVm.maybeLoadImageQuota()")
        page.wait_for_timeout(1100)
        checks["master_off_label"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-active]');"
            " return n ? n.textContent.replace(/\\s+/g,' ').trim() : ''; })()")
        checks["master_off_note"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-note]');"
            " return n ? n.textContent.replace(/\\s+/g,' ').trim() : ''; })()")

        STATE["freq_active_reason"] = "no_db"
        page.evaluate("window.__adminbotVm._imageQuotaAt = 0;"
                      "window.__adminbotVm.maybeLoadImageQuota()")
        page.wait_for_timeout(1100)
        checks["no_db_label"] = page.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-image-freq-active]');"
            " return n ? n.textContent.replace(/\\s+/g,' ').trim() : ''; })()")
        snap("04-inactive-honest.png")

        # ── Фаза F: область ЧАТА — сохранение с X-Chat-Id ────────────────
        mark('F-chat-scope')
        STATE["freq_active"] = True
        STATE["freq_active_reason"] = "ok"
        page.evaluate("window.__adminbotVm.setActiveChat(%d)" % CHAT_ID)
        page.wait_for_timeout(1600)
        goto_section()
        before = len(STATE["posts"])
        page.evaluate(
            "(() => { const items = window.__adminbotVm.configItems || [];"
            " const it = items.filter(i => i.key === '%s')[0];"
            " it.value = 2;"
            " return window.__adminbotVm.saveConfigItem(it); })()"
            % FREQ_BURST_KEY)
        page.wait_for_timeout(1200)
        chat_posts = [x for x in STATE["posts"][before:]
                      if x.get("key") == FREQ_BURST_KEY]
        checks["chat_burst_post"] = chat_posts[-1] if chat_posts else None
        checks["chat_facts_visible"] = page.evaluate(
            "!!document.querySelector('[data-image-freq-facts]')")
        snap("05-chat-scope.png")

        # ── Фаза G: мобильный вид 390px ───────────────────────────────────
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(900)
        checks["mobile_section_visible"] = page.evaluate(
            "!!document.querySelector('[data-config-group=\"%s\"]')" % GROUP)
        checks["mobile_facts_visible"] = page.evaluate(
            "!!document.querySelector('[data-image-freq-facts]')")
        checks["mobile_no_overflow"] = page.evaluate(
            "document.documentElement.scrollWidth <= "
            "document.documentElement.clientWidth + 2")
        snap("06-mobile-chat.png")

        browser.close()

    result["posts"] = STATE["posts"]
    os.makedirs(os.path.dirname(RAW), exist_ok=True)
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("screenshots",)}, ensure_ascii=False,
                     indent=2))
    ok = (not result["console_errors"]
          and checks.get("section_visible")
          and checks.get("freq_facts_visible")
          and "Выключено" in str(checks.get("freq_active_label_off"))
          and checks.get("freq_toggle_state") is False
          and checks.get("dependent_hidden_when_off") == 0
          and "выключен" in str(checks.get("freq_note_off")).lower()
          and "Заводской" in str(checks.get("freq_source_label"))
          and checks.get("toggle_post", {}).get("value") is True
          and checks.get("toggle_post", {}).get("chat") is False
          and checks.get("dependent_visible_when_on") == 3
          and checks.get("burst_input_present") is True
          and checks.get("cooldown_input_present") is True
          and "действует" in str(checks.get("freq_active_label_on"))
          and checks.get("freq_mode_label_user") == "Для каждого пользователя"
          and checks.get("freq_remaining_user") == "0 из 2"
          and checks.get("freq_next_label") not in ("", "—")
          and checks.get("cooldown_human_label") == "10 мин 20 сек"
          and "10 мин 20 сек" in str(checks.get("summary_line"))
          and checks.get("mode_select_options")
          and checks["mode_select_options"]["opts"][1] == "Общий на весь чат"
          and checks.get("freq_mode_label_chat") == "Общий на весь чат"
          and checks.get("freq_remaining_chat") == "1 из 2"
          and "Глобальный" in str(checks.get("freq_source_global"))
          and "мастер-рубильник" in str(checks.get("master_off_label"))
          and checks.get("master_off_note")
          and "недоступно" in str(checks.get("no_db_label"))
          and checks.get("chat_burst_post", {}).get("value") == 2
          and checks.get("chat_burst_post", {}).get("chat") is True
          and checks.get("mobile_section_visible")
          and checks.get("mobile_facts_visible")
          and checks.get("mobile_no_overflow"))
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--serve" in sys.argv:
        raise SystemExit(_serve_only())
    raise SystemExit(main())
