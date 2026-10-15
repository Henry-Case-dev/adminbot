"""ASAP 8 v6.3 W3-MODULES-UI — Playwright e2e (детерминированный).

Проверяет UI-хвосты B06/B07/B01.4 на реальном web/index.html + web/app.js
(/api/* — стабы, R17: только идентификаторы/числа):

  * B06.1 (Summary per-chat): на области чата тумблер АКТИВЕН в трёх
    фикстурах резолва (chat override ON при global OFF / chat override OFF /
    inherit) и текст причины соответствует резолву; лжи «не влияет;
    глобально» нет; переключение реально шлёт POST /api/config с X-Chat-Id;
  * B06.2 (global-only): карточка «Фактчек» на чате — тумблер read-only,
    честный хинт, кнопка «Настроить глобально» переводит область в «Весь
    бот»; инертный override НЕ отправляется (0 POST);
  * B07 (Temporal — функция Фактчека): на Фактчек → Основные настройки
    секция «Время и источники» («Проверять дату и актуальность», режимы,
    TTL); значения сохраняются (POST → reload); карточки «Временная
    проверка» в витрине модулей нет; детализация проверок — на Обзоре
    Фактчека (runs → общий detail-modal); 403 без прав — честная подсказка;
  * B01.4: профиль частоты Инициативы — select редко/нормально/активно,
    меняется и сохраняется (POST → reload); per-chat гейт «Инициатива в
    этом чате» на основных настройках;
  * U08.4: тумблер не меняет hitbox (elementFromPoint в центре тумблера —
    его input), «Настроить» кликабелен; 320/390 без переполнения.

Запуск: .venv\\Scripts\\python.exe tools\\ui_asap8_w3_modules_e2e.py
Артефакты: plans/features/asap8-v6-3-live-correction/w3-evidence-modules/
"""
import copy
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (сервер/стабы/TMA — reuse)

PORT = 8837
SHOTS = os.path.join(REPO, "plans", "features", "asap8-v6-3-live-correction",
                     "w3-evidence-modules")
RAW = os.path.join(os.environ.get("OPENCODE_WORKFLOW_SCRATCH",
                                  os.path.join(REPO, "tools")),
                   "_ui_w3_modules.json")

CHAT_ID = -1001234567890
NOW = 1791900000

SUMMARY_KEY = "flags.summary_enabled"
FACTCHECK_KEY = "flags.factcheck_enabled"

TEMPORAL_RUNS = {
    "runs": [
        {"run_id": "tfr-w3-1", "created_at": NOW - 600, "chat_id": CHAT_ID,
         "assessment_mode": "contextual", "factual_verdict": "supported",
         "temporal_status": "fresh", "date_source": "telegram_origin",
         "cache_hit": False, "fallback_used": False},
        {"run_id": "tfr-w3-2", "created_at": NOW - 3600, "chat_id": CHAT_ID,
         "assessment_mode": "current", "factual_verdict": "old_but_valid",
         "temporal_status": "stale", "date_source": "repost_header",
         "cache_hit": True, "fallback_used": False},
    ],
}
TEMPORAL_DETAIL = {
    "run": {"run_id": "tfr-w3-1", "claim_text": "пример утверждения",
            "original_published_at": NOW - 86400 * 400,
            "repost_received_at": NOW - 600,
            "analysis_as_of": NOW, "date_source": "telegram_origin",
            "assessment_mode": "contextual", "factual_verdict": "supported",
            "temporal_status": "fresh", "fallback_used": False,
            "cache_hit": False, "stage_trace": []},
    "evidence": [{"url": "https://example.com/a", "relation": "supports"}],
}

# Не-владелец с доступом к модулям/конфиг-вкладкам (flags/limits): видит
# «Модули» и workspace Фактчека, но НЕ глобальный админ (is_global_admin
# False) → «Настроить глобально» скрыта, temporal-runs не запрашиваются.
LOCAL_MODULES_ME = dict(M.ME_JSON)
LOCAL_MODULES_ME.update({
    "username": "localflags", "first_name": "Local",
    "role_name": "local_admin",
    "permissions": {"sections": ["flags", "limits"]},
    "is_global_admin": False,
})

# Состояние фикстур (мутирует тест между фазами; читает handler).
STATE = {
    "global_summary": True,          # global default Summary
    "chat_overrides": {},            # per-chat overrides активного чата
    "global_factcheck": True,
    "temporal_tool": True,
    "temporal_mode": "contextual",
    "initiative_profile": "normal",
    "initiative_enabled": True,
    "me": None,                      # None → M.ME_JSON; иначе LOCAL_ADMIN_ME
    "posts": [],                     # журнал POST /api/config
    "temporal_runs_status": 200,     # 403 → RBAC-ветка
}


def _stub_config(scope_chat: bool) -> dict:
    """/api/config: глобальный слой (матрица каталога) + per-chat overlay.

    Серверная семантика `web/api/routes.py::get_config`: value = global,
    если нет override; override (per_chat=True) → value/chat_source."""
    data = copy.deepcopy(M.CONFIG_STUB)
    items = data["items"]
    by_key = {it["key"]: it for it in items}
    by_key[SUMMARY_KEY]["value"] = STATE["global_summary"]
    by_key[SUMMARY_KEY]["global_value"] = STATE["global_summary"]
    by_key[FACTCHECK_KEY]["value"] = STATE["global_factcheck"]
    by_key["temporal.tool_enabled"]["value"] = STATE["temporal_tool"]
    by_key["temporal.default_mode"]["value"] = STATE["temporal_mode"]
    by_key["initiative.frequency_profile"]["value"] = STATE["initiative_profile"]
    by_key["initiative.enabled"]["value"] = STATE["initiative_enabled"]
    if scope_chat:
        for it in items:
            if not it.get("per_chat"):
                continue
            it["global_value"] = it["value"]
            ov = STATE["chat_overrides"].get(it["key"])
            if ov is not None:
                it["value"] = ov
                it["chat_source"] = "chat"
            else:
                it["chat_source"] = ""
        data["updated_at"] = NOW
        data["chat_updated_at"] = NOW
    return data


def main() -> int:
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    os.makedirs(SHOTS, exist_ok=True)

    def _api_handler(route):
        req = route.request
        url = req.url.split("?")[0]
        chat_hdr = req.headers.get("x-chat-id")
        scope_chat = chat_hdr is not None
        if req.method == "POST" and url.endswith("/api/config"):
            try:
                body = json.loads(req.post_data or "{}")
            except ValueError:
                body = {}
            for it in body.get("items", []):
                key, value = it.get("key"), it.get("value")
                STATE["posts"].append({"key": key, "value": value,
                                       "chat": scope_chat})
                spec_item = {i["key"]: i for i in M.CONFIG_STUB["items"]}.get(key)
                per_chat = bool(spec_item and spec_item.get("per_chat"))
                if scope_chat and per_chat:
                    STATE["chat_overrides"][key] = value
                elif key == SUMMARY_KEY:
                    STATE["global_summary"] = bool(value)
                elif key == FACTCHECK_KEY:
                    STATE["global_factcheck"] = bool(value)
                elif key == "temporal.tool_enabled":
                    STATE["temporal_tool"] = bool(value)
                elif key == "temporal.default_mode":
                    STATE["temporal_mode"] = value
                elif key == "initiative.frequency_profile":
                    STATE["initiative_profile"] = value
                elif key == "initiative.enabled":
                    STATE["initiative_enabled"] = bool(value)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "updated_at": NOW + 1},
                                          ensure_ascii=False))
            return
        if url.endswith("/api/config"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(_stub_config(scope_chat),
                                          ensure_ascii=False))
            return
        if url.endswith("/api/me"):
            me = STATE["me"] or M.ME_JSON
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(me, ensure_ascii=False))
            return
        if url.endswith("/api/factcheck/temporal/runs"):
            status = STATE["temporal_runs_status"]
            body = TEMPORAL_RUNS if status == 200 else {"detail": "нет прав"}
            route.fulfill(status=status, content_type="application/json",
                          body=json.dumps(body, ensure_ascii=False))
            return
        if url.endswith("/api/factcheck/temporal/runs/tfr-w3-1"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(TEMPORAL_DETAIL, ensure_ascii=False))
            return
        if url.endswith("/api/access/me"):
            local = STATE["me"] is not None
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"is_local_admin": local,
                                           "permissions": {}},
                                          ensure_ascii=False))
            return
        body = M._stub_for(req.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body, ensure_ascii=False))

    from playwright.sync_api import sync_playwright
    result = {"console_errors": [], "checks": {}, "screenshots": []}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  reduced_motion="reduce")
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _api_handler)
        page = ctx.new_page()
        page.on("console", lambda m: result["console_errors"].append(
            m.text[:200]) if m.type == "error"
            and "status of 403" not in m.text else None)
        page.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror: " + str(e)[:200]))
        page.on("dialog", lambda d: d.accept())
        page.goto(base, wait_until="load")
        page.wait_for_timeout(1800)
        checks = result["checks"]

        def card(mod):
            return page.query_selector('[data-mod="%s"]' % mod)

        # ── B07: карточки «Временная проверка» в витрине НЕТ (GLOBAL) ──
        page.evaluate("window.location.hash = '#/modules'")
        page.wait_for_timeout(1200)
        checks["no_temporal_card"] = page.evaluate(
            "document.querySelectorAll('[data-mod]').length > 0 &&"
            " !document.querySelector('[data-mod=\"mod_factcheck_temporal\"]')")
        checks["summary_card_present_global"] = card("mod_summary") is not None

        # ── U08.4: тумблер не меняет hitbox; «Настроить» кликабелен ──
        checks["toggle_hitbox"] = page.evaluate(
            "(() => { const c = document.querySelector("
            "'[data-mod=\"mod_factcheck\"]'); if (!c) return false;"
            " const input = c.querySelector('input[type=checkbox]');"
            " if (!input) return false;"
            " const r = input.getBoundingClientRect();"
            " const el = document.elementFromPoint("
            " r.x + r.width / 2, r.y + r.height / 2);"
            " return el === input || (el && input.contains(el)) ||"
            " (el && el.contains(input)); })()")
        checks["configure_btn_clickable"] = page.evaluate(
            "(() => { const b = document.querySelector("
            "'[data-mod=\"mod_factcheck\"] .module-params-btn');"
            " if (!b) return false; const r = b.getBoundingClientRect();"
            " const el = document.elementFromPoint("
            " r.x + r.width / 2, r.y + r.height / 2);"
            " return el === b || (el && b.contains(el)); })()")

        # ── B06.1: chat-scope Summary — три фикстуры резолва ──
        page.evaluate("window.__adminbotVm.setActiveChat('%d')" % CHAT_ID)
        page.wait_for_timeout(1500)

        # Фикстура 1: chat override ON при global OFF → работает, честный текст.
        STATE["global_summary"] = False
        STATE["chat_overrides"] = {SUMMARY_KEY: True}
        page.evaluate("window.__adminbotVm.loadConfig()")
        page.wait_for_timeout(1200)
        sc = card("mod_summary")
        checks["f1_toggle_enabled"] = page.evaluate(
            "(() => { const i = document.querySelector("
            "'[data-mod=\"mod_summary\"] input[type=checkbox]');"
            " return !!i && !i.disabled; })()")
        checks["f1_state_on"] = sc.query_selector(
            ".module-state-value").inner_text() == "Включён"
        checks["f1_notice_resolve"] = page.evaluate(
            "(() => { const el = document.querySelector("
            "'[data-mod=\"mod_summary\"] .module-problem');"
            " return el ? el.textContent.indexOf('Включено для этой области"
            " (глобально выключено)') >= 0 : false; })()")
        checks["f1_source_chat"] = page.evaluate(
            "(() => { const el = document.querySelector("
            "'[data-mod=\"mod_summary\"] .module-source');"
            " return el ? el.textContent.indexOf('настройки чата') >= 0"
            " : false; })()")

        # Фикстура 2: chat override OFF при global ON → «Выключено в этом чате».
        STATE["global_summary"] = True
        STATE["chat_overrides"] = {SUMMARY_KEY: False}
        page.evaluate("window.__adminbotVm.loadConfig()")
        page.wait_for_timeout(1200)
        checks["f2_notice_chat_off"] = page.evaluate(
            "(() => { const el = document.querySelector("
            "'[data-mod=\"mod_summary\"] .module-problem');"
            " return el ? el.textContent.indexOf('Выключено в этом чате') >= 0"
            " : false; })()")

        # Фикстура 3: inherit (без override) — без ⚠-строки; тумблер активен.
        STATE["chat_overrides"] = {}
        page.evaluate("window.__adminbotVm.loadConfig()")
        page.wait_for_timeout(1200)
        checks["f3_no_notice"] = page.evaluate(
            "document.querySelector('[data-mod=\"mod_summary\"]"
            " .module-problem') === null")
        checks["f3_toggle_enabled"] = page.evaluate(
            "(() => { const i = document.querySelector("
            "'[data-mod=\"mod_summary\"] input[type=checkbox]');"
            " return !!i && !i.disabled; })()")

        # Переключение реально пишет per-chat слой (POST с X-Chat-Id).
        n_posts = len(STATE["posts"])
        page.evaluate(
            "window.__adminbotVm.setModuleState("
            "window.__adminbotVm.storeScope(), 'mod_summary', false)")
        page.wait_for_timeout(1200)
        summary_posts = [p for p in STATE["posts"][n_posts:]
                         if p["key"] == SUMMARY_KEY]
        checks["f_toggle_posts_chat"] = bool(summary_posts) and \
            summary_posts[-1]["chat"] is True and \
            summary_posts[-1]["value"] is False

        # ── B06.2: global-only карточка на чате — read-only + кнопка ──
        fc = card("mod_factcheck")
        checks["b06_readonly_toggle"] = page.evaluate(
            "(() => { const i = document.querySelector("
            "'[data-mod=\"mod_factcheck\"] input[type=checkbox]');"
            " return !!i && i.disabled; })()")
        checks["b06_hint"] = page.evaluate(
            "(() => { const el = document.querySelector("
            "'[data-mod=\"mod_factcheck\"] .module-global-hint');"
            " return el ? el.textContent.indexOf('Управляется глобально') >= 0"
            " : false; })()")
        btn = fc.query_selector(".module-global-btn")
        checks["b06_global_btn"] = btn is not None and btn.is_visible()
        n_posts = len(STATE["posts"])
        if btn:
            btn.click()
            page.wait_for_timeout(1500)
        checks["b06_back_to_global"] = page.evaluate(
            "window.__adminbotVm.activeChatId === null") and page.evaluate(
            "window.__adminbotVm.scopeKind === 'global'")
        factcheck_posts = [p for p in STATE["posts"][n_posts:]]
        checks["b06_no_inert_override"] = len(factcheck_posts) == 0
        # На global-области тумблер Фактчека снова активен.
        checks["b06_global_toggle_active"] = page.evaluate(
            "(() => { const i = document.querySelector("
            "'[data-mod=\"mod_factcheck\"] input[type=checkbox]');"
            " return !!i && !i.disabled; })()")
        shot = os.path.join(SHOTS, "w3_modules_global_catalog.png")
        page.screenshot(path=shot, full_page=False)
        result["screenshots"].append(shot)

        # ── B07: Фактчек → Основные настройки → «Время и источники» ──
        page.evaluate("window.location.hash = '#/modules/factcheck/settings'")
        page.wait_for_timeout(1500)
        checks["b07_intro_block"] = page.evaluate(
            "(() => { const el = document.querySelector("
            "'[data-factcheck-temporal-intro]'); return !!el &&"
            " el.textContent.indexOf('Время и источники') >= 0; })()")
        checks["b07_group_title"] = page.evaluate(
            "(() => { const g = document.querySelector("
            "'[data-config-group=\"temporal_factcheck\"]');"
            " return !!g && g.textContent.indexOf('Время и источники') >= 0; })()")
        checks["b07_tool_label"] = page.evaluate(
            "(() => { const g = document.querySelector("
            "'[data-config-group=\"temporal_factcheck\"]');"
            " return !!g && g.textContent.indexOf("
            "'Проверять дату и актуальность') >= 0; })()")
        checks["b07_mode_select"] = page.evaluate(
            "(() => { const g = document.querySelector("
            "'[data-config-group=\"temporal_factcheck\"]');"
            " if (!g) return false;"
            " const sel = g.querySelector('select');"
            " return !!sel && sel.querySelectorAll('option').length === 4; })()")
        checks["b07_ttl_fields"] = page.evaluate(
            "(() => { const g = document.querySelector("
            "'[data-config-group=\"temporal_factcheck\"]');"
            " return !!g && g.textContent.indexOf('Срок свежих вердиктов') >= 0"
            " && g.textContent.indexOf('Срок исторических вердиктов') >= 0; })()")

        # Значение сохраняется: тумблер OFF → POST → reload → OFF.
        n_posts = len(STATE["posts"])
        page.evaluate(
            "(() => { const g = document.querySelector("
            "'[data-config-group=\"temporal_factcheck\"]');"
            " const i = g.querySelector('input[type=checkbox]');"
            " i.click(); })()")
        page.wait_for_timeout(1500)
        tool_posts = [p for p in STATE["posts"][n_posts:]
                      if p["key"] == "temporal.tool_enabled"]
        checks["b07_save_post"] = bool(tool_posts)
        checks["b07_persist_reload"] = page.evaluate(
            "(() => { const g = document.querySelector("
            "'[data-config-group=\"temporal_factcheck\"]');"
            " const i = g.querySelector('input[type=checkbox]');"
            " return !!i && i.checked === false; })()")

        # ── B07: детализация проверок на Обзоре Фактчека (runs + модалка) ──
        page.evaluate("window.location.hash = '#/modules/factcheck'")
        page.wait_for_timeout(1500)
        checks["b07_overview_runs_block"] = page.evaluate(
            "!!document.querySelector('[data-factcheck-temporal]')")
        checks["b07_runs_rendered"] = page.evaluate(
            "document.querySelectorAll("
            "'[data-factcheck-temporal] [data-temporal-run-btn]').length >= 2")
        page.evaluate(
            "(() => { const b = document.querySelector("
            "'[data-factcheck-temporal] [data-temporal-run-btn]');"
            " if (b) b.click(); })()")
        page.wait_for_timeout(1200)
        checks["b07_detail_modal"] = page.evaluate(
            "(() => { const m = document.querySelector('.modal-backdrop');"
            " return !!m && m.textContent.indexOf('пример утверждения') >= 0; })()")
        page.evaluate(
            "(() => { const m = document.querySelector('.modal-backdrop');"
            " if (!m) return; const b = Array.from(m.querySelectorAll('button'))"
            ".find(function (x) { return x.textContent.trim() === 'Закрыть'; });"
            " if (b) b.click(); })()")
        page.wait_for_timeout(600)
        checks["b07_detail_closed"] = page.evaluate(
            "document.querySelector('.modal-backdrop') === null")
        shot = os.path.join(SHOTS, "w3_factcheck_overview.png")
        page.screenshot(path=shot, full_page=False)
        result["screenshots"].append(shot)

        # ── B01.4: Инициатива — профиль частоты + per-chat гейт ──
        page.evaluate("window.location.hash = '#/modules/initiative/limits'")
        page.wait_for_timeout(1500)
        checks["b01_profile_select"] = page.evaluate(
            "(() => { const sel = Array.from(document.querySelectorAll("
            "'select')).find(function (s) { return"
            " Array.from(s.options).some(function (o) { return"
            " o.value === 'rare'; }); }); return !!sel &&"
            " sel.options.length === 3 && sel.value === 'normal'; })()")
        n_posts = len(STATE["posts"])
        page.evaluate(
            "(() => { const sel = Array.from(document.querySelectorAll("
            "'select')).find(function (s) { return"
            " Array.from(s.options).some(function (o) { return"
            " o.value === 'rare'; }); }); sel.value = 'active';"
            " sel.dispatchEvent(new Event('change')); })()")
        page.wait_for_timeout(1500)
        profile_posts = [p for p in STATE["posts"][n_posts:]
                         if p["key"] == "initiative.frequency_profile"]
        checks["b01_profile_post"] = bool(profile_posts) and \
            profile_posts[-1]["value"] == "active"
        checks["b01_profile_persist"] = page.evaluate(
            "(() => { const sel = Array.from(document.querySelectorAll("
            "'select')).find(function (s) { return"
            " Array.from(s.options).some(function (o) { return"
            " o.value === 'rare'; }); }); return !!sel &&"
            " sel.value === 'active'; })()")
        page.evaluate("window.location.hash = '#/modules/initiative/settings'")
        page.wait_for_timeout(1500)
        checks["b01_chat_gate_rendered"] = page.evaluate(
            "(() => { const el = Array.from(document.querySelectorAll("
            "'[data-config-group=\"flags_intent\"] .text-sm.font-semibold'))"
            ".find(function (e) { return e.textContent.trim() ==="
            " 'Инициатива в этом чате'; }); return !!el; })()")
        checks["b01_observer_label"] = page.evaluate(
            "(() => { const main = document.querySelector('.scroll-area');"
            " return !!main && main.textContent.indexOf("
            "'Автономные реплики в обычных чатах') >= 0; })()")

        # Инициатива-карточка на чате: мастер read-only + «Настроить
        # глобально»; per-chat гейт остаётся в настройках.
        page.evaluate("window.location.hash = '#/modules'")
        page.wait_for_timeout(800)
        page.evaluate("window.__adminbotVm.setActiveChat('%d')" % CHAT_ID)
        page.wait_for_timeout(1500)
        checks["b01_master_readonly_on_chat"] = page.evaluate(
            "(() => { const i = document.querySelector("
            "'[data-mod=\"mod_initiative\"] input[type=checkbox]');"
            " return !!i && i.disabled; })()")
        checks["b01_global_btn_present"] = page.evaluate(
            "(() => { const b = document.querySelector("
            "'[data-mod=\"mod_initiative\"] .module-global-btn');"
            " return !!b && b.is_visible !== undefined ? !!b : !!b; })()")
        shot = os.path.join(SHOTS, "w3_modules_chat_scope.png")
        page.screenshot(path=shot, full_page=False)
        result["screenshots"].append(shot)

        # ── 403 без прав (global admin, сервер отказал): fail-open честно
        #      «проверок пока нет» — без выдуманных данных (канон MCA-20). ──
        page.evaluate("window.location.hash = '#/modules/factcheck'")
        page.wait_for_timeout(1500)
        STATE["temporal_runs_status"] = 403
        page.evaluate("window.__adminbotVm.loadTemporalRuns(true)")
        page.wait_for_timeout(1200)
        checks["rbac_403_failopen_honest"] = page.evaluate(
            "(() => { const el = document.querySelector("
            "'[data-factcheck-temporal]'); return !!el &&"
            " el.textContent.indexOf('проверок пока нет') >= 0; })()")
        checks["rbac_403_no_fabricated_rows"] = page.evaluate(
            "document.querySelectorAll("
            "'[data-factcheck-temporal] [data-temporal-run-btn]').length") == 0
        STATE["temporal_runs_status"] = 200

        # ── Без прав владельца (локальный админ с секциями flags/limits):
        #      «Настроить глобально» нет, runs-запрос не делается, подсказка
        #      честная. ──
        STATE["me"] = LOCAL_MODULES_ME
        page.evaluate("window.location.reload()")
        page.wait_for_timeout(2200)
        checks["rbac_no_global_btn"] = page.evaluate(
            "document.querySelector('[data-mod=\"mod_factcheck\"]"
            " .module-global-btn') === null")
        page.evaluate("window.location.hash = '#/modules/factcheck'")
        page.wait_for_timeout(1500)
        checks["rbac_honest_hint"] = page.evaluate(
            "(() => { const el = document.querySelector("
            "'[data-factcheck-temporal]'); return !!el &&"
            " el.textContent.indexOf('доступен владельцу бота') >= 0; })()")
        checks["rbac_runs_block_empty"] = page.evaluate(
            "document.querySelectorAll("
            "'[data-factcheck-temporal] [data-temporal-run-btn]').length") == 0

        # ── 390/320: модули и фактчек-настройки без переполнения ──
        STATE["me"] = None
        page.evaluate("window.location.reload()")
        page.wait_for_timeout(2200)
        page.evaluate("window.location.hash = '#/modules'")
        page.wait_for_timeout(1000)
        for w, name in ((390, "mobile_390"), (320, "narrow_320")):
            page.set_viewport_size({"width": w, "height": 844})
            page.wait_for_timeout(1200)
            checks["no_h_overflow_modules_" + name] = page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth + 1")
            shot = os.path.join(SHOTS, "w3_modules_%s.png" % name)
            page.screenshot(path=shot, full_page=True)
            result["screenshots"].append(shot)
            page.evaluate(
                "window.location.hash = '#/modules/factcheck/settings'")
            page.wait_for_timeout(1200)
            checks["no_h_overflow_factcheck_" + name] = page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth + 1")
            page.evaluate("window.location.hash = '#/modules'")
            page.wait_for_timeout(800)

        browser.close()
    httpd.shutdown()
    result["ok"] = (all(v is True for v in result["checks"].values())
                    and not result["console_errors"])
    try:
        with open(RAW, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
    except Exception:
        pass
    print(json.dumps(result["checks"], ensure_ascii=False))
    print("console_errors:", result["console_errors"][:5])
    print("W3-MODULES-E2E-OK" if result["ok"] else "W3-MODULES-E2E-FAIL")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
