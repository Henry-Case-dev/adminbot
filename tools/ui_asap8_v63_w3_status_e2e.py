"""ASAP 8 v6.3 W3-STATUS — Playwright e2e (детерминированный): U03/U04/B03.

Проверяет визуальные дельты лайна W3-STATUS на реальном web/index.html +
web/app.js (/api/* — стабы, R17: только идентификаторы/числа):

  * U03.1: ровно одна каноническая панель «Сон / Глубокий сон» (стадия/
    результат/последний запуск); «ещё не выполнялся» вместо 22.01.1970
    (deep.last_run_at=null); в шапке «Мониторинга Интеллекта» нет дубля
    sleep-бейджей;
  * B03: блок «Просрочено N» — честная раскладка (всего/доступно поиску/
    требует перепроверки/вытеснено/режим) из /api/memory/expired-overview;
  * U03.4: independent-воронка «Инициативы» (8 стадий с durable-числами,
    причина пустоты, liveness); окна 24ч/7д «Опыта»;
  * U04: блок логов — в конце Статуса (фильтры/копирование/счётчики),
    в Аналитике вкладок «Логи» нет; легаси #/oversight?scroll=logs →
    канон #/ + скролл к блоку с offset sticky-шапки;
  * 320/390/1440: без горизонтального переполнения; console без ошибок.

Запуск: .venv\\Scripts\\python.exe tools\\ui_asap8_v63_w3_status_e2e.py
Артефакты: plans/features/asap8-v6-3-live-correction/w3-evidence-status/
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

PORT = 8833
SHOTS = os.path.join(REPO, "plans", "features", "asap8-v6-3-live-correction",
                     "w3-evidence-status")
RAW = os.path.join(os.environ.get("OPENCODE_WORKFLOW_SCRATCH",
                                  os.path.join(REPO, "tools")),
                   "_ui_w3_status.json")

NOW = 1791900000  # фиксированный «сейчас» (2026-10-15, seconds)

EXPIRED_OVERVIEW = {
    "available": True, "now_ts": NOW, "expired_total": 3584,
    "expired_searchable": 3500, "needs_recheck": 1200,
    "superseded_total": 210, "infinite_retention": True,
}

INTEL_FUNNELS = {
    "available": True, "now_ts": NOW, "chat_scoped_events": False,
    "initiative": {
        "available": True,
        "job": {"status": "completed", "updated_at": NOW - 10000,
                "counters": {"passes": 3, "observed": 420, "eligible": 25,
                             "scan_skipped": 7, "evals": 22,
                             "opportunities": 4, "silent_decisions": 2,
                             "intents_created": 2, "sent": 1,
                             "react_decisions": 1, "writer_unavailable": 1,
                             "eval_unavailable": 0, "errors": 0,
                             "eval_skips": {"budget": 3}}},
        "liveness": {"ts": NOW - 11000, "status": "ok", "observed": 42,
                     "opportunities": 1},
        "events": {
            "24h": {"initiative_observer_scan": 40,
                    "initiative_opportunity": 2, "initiative_decided": 2,
                    "initiative_writer_generated": 2,
                    "initiative_writer_unavailable": 0,
                    "initiative_recheck_passed": 1, "initiative_sent": 1,
                    "initiative_observer_diagnostic": 0},
            "7d": {"initiative_observer_scan": 260,
                   "initiative_opportunity": 4, "initiative_decided": 3,
                   "initiative_writer_generated": 3,
                   "initiative_writer_unavailable": 1,
                   "initiative_recheck_passed": 2, "initiative_sent": 2,
                   "initiative_observer_diagnostic": 1},
        },
    },
    "experience": {
        "available": True,
        "job": {"status": "completed", "updated_at": NOW - 20000,
                "counters": {"semantic_scanned": 300, "semantic_selected": 40,
                             "semantic_extracted": 12,
                             "semantic_candidates": 9, "semantic_rejected": 3,
                             "semantic_duplicates": 2,
                             "semantic_llm_unavailable": 1},
                "semantic_watermark": 15000, "semantic_pending": 3},
        "semantic_lag": {"watermark": 15000, "max_message_id": 15200,
                         "pending": 3},
        "last_application": {"ts": NOW - 100000, "outcome": "success"},
        "events": {
            "24h": {"semantic_extract": 3, "detector_signal": 2, "applied": 1,
                    "retrieved": 4},
            "7d": {"semantic_extract": 8, "detector_signal": 5, "applied": 3,
                   "retrieved": 11},
        },
    },
}

COGNITION = {
    "dream": {"running": False, "enabled": True, "effective": True,
              "active": False, "active_until": None, "manual": False,
              "last_run_at": NOW - 7200, "next_wake_at": NOW + 3600,
              "state": "sleep",
              "budget": {"distilled_today": 2, "distilled_limit": 5,
                         "tokens_today": 900, "tokens_limit": 2000}},
    # deep.last_run_at = null → честное «ещё не выполнялся» (U03.2)
    "deep_sleep": {"running": False, "enabled": True, "active": False,
                   "active_until": None, "manual": False,
                   "last_run_at": None, "next_run_at": NOW + 7200},
    "generated_at": NOW,
}

HEALTH = {
    "beliefs_active": 128, "beliefs_archived": 44, "resurrections_total": 6,
    "decay_runs_total": 18, "last_decay_at": NOW - 4000,
    "facts_overdue": 12, "facts_unconfirmed": 30,
    "smart_messages_total": 10500, "deep_sleep_runs_total": 9,
    "storage": {"db_size_bytes": 524288000, "db_size_mb": 500.0,
                "disk_free_bytes": 3221225472},
}

DEEP_SLEEP = {"paradigms_status": "empty", "paradigms_reason": None,
              "gate": True, "gate_source": "env",
              "effective": True, "scheduler_gate": None,
              "last_attempt_result": "empty",
              "last_attempt_retry_class": None,
              "next_auto_attempt_at": NOW + 3600}

# /api/status: базовый стаб матрицы + аддитивные блоки, читаемые Статусом
# (intents/experience/random) — честные not_run/незначащие нули.
STATUS_W3 = copy.deepcopy(M.STATUS_STUB)
STATUS_W3["intents"] = {
    "enabled": True, "state": "not_run", "active": 0, "top": [],
    "last_action": None,
    "module": {
        "state_label": ("Heartbeat ещё не запускался — тика инициативы "
                        "не было"),
        "top_block_reason": "heartbeat_not_run",
        "funnel": {"producers_24h": {}, "intents_created_24h": 0, "due": 0,
                   "decisions_24h": 0, "sent_24h": 0},
        "heartbeat": {"enabled": False, "registered": False,
                      "last_tick": None},
    },
}
STATUS_W3["experience"] = {"enabled": True, "state": "not_run",
                           "items": [],
                           "counters": {"lessons": 0, "active": 0,
                                        "suspended": 0, "applications": 0,
                                        "success": 0, "failure": 0,
                                        "unknown": 0}}
STATUS_W3["random"] = {"ready": True, "enabled": False}

LOG_ROWS = [
    {"level": "ERROR", "ts": NOW - 60, "logger": "services.dream",
     "message": "SUMMARY_FAILED пример ошибки для viewer"},
    {"level": "WARNING", "ts": NOW - 120, "logger": "services.observer",
     "message": "initiative writer_unavailable (таймаут)"},
    {"level": "INFO", "ts": NOW - 180, "logger": "services.summary",
     "message": "run_id=abc этап L1 завершён"},
]
LOGS_PAYLOAD = {"logs": LOG_ROWS, "levels": ["ERROR", "WARNING"],
                "count": 3, "counts": {"ERROR": 3, "WARNING": 5}}


def _funnel(days: int) -> dict:
    if days == 1:
        return {"available": True, "enabled": True,
                "period": {"since_ts": NOW - 86400, "until_ts": NOW,
                           "days": 1},
                "episodes": {"total": 4, "success": 3, "failure": 1,
                             "unknown": 0},
                "lessons": {"candidate": 2, "validated": 3, "active": 5,
                            "suspended": 0, "superseded": 0,
                            "new_in_period": 1, "scope": "current"},
                "applications": {"total": 2, "success": 1, "failure": 0,
                                 "unknown": 1, "unique_lessons": 2},
                "feedback": {"total": 3, "unique_episodes": 3},
                "notes": [], "generated_at": NOW}
    return {"available": True, "enabled": True,
            "period": {"since_ts": NOW - 7 * 86400, "until_ts": NOW,
                       "days": 7},
            "episodes": {"total": 11, "success": 8, "failure": 2,
                         "unknown": 1},
            "lessons": {"candidate": 6, "validated": 7, "active": 5,
                        "suspended": 1, "superseded": 0,
                        "new_in_period": 4, "scope": "current"},
            "applications": {"total": 5, "success": 2, "failure": 1,
                             "unknown": 2, "unique_lessons": 4},
            "feedback": {"total": 9, "unique_episodes": 8},
            "notes": [], "generated_at": NOW}


def _start_server() -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main() -> int:
    httpd = _start_server()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    os.makedirs(SHOTS, exist_ok=True)
    config_payload = copy.deepcopy(M.CONFIG_STUB)

    def _api_handler(route):
        req = route.request
        url = req.url.split("?")[0]
        if url.endswith("/api/memory/expired-overview"):
            body = EXPIRED_OVERVIEW
        elif url.endswith("/api/memory/intel-funnels"):
            body = INTEL_FUNNELS
        elif url.endswith("/api/oversight/experience/funnel"):
            days = 1
            for part in req.url.split("?")[-1].split("&"):
                if part.startswith("days="):
                    try:
                        days = int(part[5:])
                    except ValueError:
                        days = 1
            body = _funnel(days)
        elif url.endswith("/api/memory/cognition/status"):
            body = COGNITION
        elif url.endswith("/api/memory/deep-sleep"):
            body = DEEP_SLEEP
        elif url.endswith("/api/memory/health"):
            body = HEALTH
        elif url.endswith("/api/status/logs"):
            body = LOGS_PAYLOAD
        elif url.endswith("/api/status"):
            body = STATUS_W3
        elif url.endswith("/api/config"):
            body = config_payload
        else:
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
            m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror: " + str(e)[:200]))
        page.on("dialog", lambda d: d.accept())
        page.goto(base, wait_until="load")
        page.wait_for_timeout(2000)
        checks = result["checks"]

        # ── Статус: каноническая панель сна (U03.1) ──
        checks["sleep_panels_single"] = page.evaluate(
            "document.querySelectorAll('.status-sleep').length") == 1
        body = page.inner_text("body")
        checks["sleep_canonical_title"] = "Сон / Глубокий сон" in body
        checks["sleep_unknown_label"] = "ещё не выполнялся" in body
        checks["no_1970"] = "22.01.1970" not in body and "1970" not in body
        checks["no_dup_sleep_badges"] = page.evaluate(
            "(() => { const h = document.querySelector('.intel-header');"
            " return h ? (h.textContent.indexOf('Сон через') < 0 &&"
            " h.querySelectorAll('.badge-btn').length === 0) : false; })()")
        shot = os.path.join(SHOTS, "w3_status_desktop_1440.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        # ── B03: блок «Просрочено N» ──
        exp_text = page.inner_text("[data-expired-block]")
        checks["expired_total"] = "Просрочено: 3584" in exp_text
        checks["expired_layout"] = ("доступно поиску" in exp_text
                                    and "требует перепроверки" in exp_text
                                    and "вытеснено новыми версиями" in exp_text
                                    and "бессрочный" in exp_text)
        checks["mem_tech_present"] = page.evaluate(
            "!!document.querySelector('[data-memory-tech]')")

        # ── U03.4: воронки ──
        checks["initiative_funnel_stages"] = page.evaluate(
            "document.querySelectorAll('[data-initiative-independent] "
            ".funnel-cell').length") == 8
        funnel_text = page.inner_text("[data-initiative-independent]")
        checks["initiative_observed_420"] = "420" in funnel_text
        checks["initiative_liveness"] = "последний тик" in funnel_text
        checks["experience_windows"] = page.evaluate(
            "document.querySelectorAll('[data-experience-windows] "
            ".exp-window').length") == 2
        checks["exp_last_applied"] = page.evaluate(
            "document.querySelector('[data-experience-windows]')"
            ".textContent.indexOf('последнее применение:') >= 0")

        # ── U04: логи в Статусе ──
        checks["logs_in_status_grid"] = page.evaluate(
            "(() => { const grid = document.querySelector('.status-grid');"
            " const logs = document.getElementById('status-logs');"
            " return !!(grid && logs && grid.contains(logs));"
            " })()")
        checks["log_rows_rendered"] = page.evaluate(
            "document.querySelectorAll('#status-logs .log-row').length") == 3
        checks["log_counters"] = page.evaluate(
            "(() => { const t = document.getElementById('status-logs')"
            ".textContent; return t.indexOf('показано 3 из 3') >= 0 &&"
            " t.indexOf('ERROR 1') >= 0 && t.indexOf('WARN 1') >= 0; })()")
        checks["log_top_counts"] = page.evaluate(
            "(() => { const t = document.querySelector('.status-counts')"
            ".textContent; return t.indexOf('Ошибки: 3') >= 0 &&"
            " t.indexOf('Предупреждения: 5') >= 0; })()")
        checks["log_filters_present"] = page.evaluate(
            "!!document.getElementById('mca-log-filters')")
        # копирование строки (clipboard stub в TMA_STUB отсутствует —
        # проверяем вызов copyLogRow через vm-метод без падений)
        checks["copy_row_no_crash"] = page.evaluate(
            "(() => { const vm = window.__adminbotVm; if (!vm) return false;"
            " try { vm.copyLogRow(vm.shownLogs[0], 0); return true; }"
            " catch (e) { return false; } })()")
        shot = os.path.join(SHOTS, "w3_status_logs_desktop.png")
        el = page.query_selector("#status-logs")
        el.screenshot(path=shot)
        result["screenshots"].append(shot)

        # ── U04: в Аналитике вкладок «Логи» нет ──
        page.evaluate("window.location.hash = '#/oversight'")
        page.wait_for_timeout(1500)
        checks["analytics_no_logs_tab"] = page.evaluate(
            "(() => { const tabs ="
            " Array.from(document.querySelectorAll('.oversight-tab'));"
            " return tabs.length > 0 &&"
            " !tabs.some(function (t) { return t.textContent.trim()"
            " === 'Логи'; }); })()")
        checks["analytics_no_logs_block"] = page.evaluate(
            "(() => { const main = document.querySelector('.scroll-area');"
            " return main ? main.textContent.indexOf('Логи → Аналитика') < 0"
            " : false; })()")

        # ── U04.2: легаси-редирект → Статус + скролл к блоку (settle-доводка
        #      добивается после догрузки данных — ждём ~1.6с) ──
        page.evaluate(
            "window.location.hash = '#/oversight?scroll=logs'")
        page.wait_for_timeout(1800)
        checks["legacy_redirect_canon"] = page.evaluate(
            "window.location.hash") == "#/"
        checks["legacy_active_tab_status"] = page.evaluate(
            "window.__adminbotVm && window.__adminbotVm.activeTab"
            " === 'status'")
        scroll_pos = page.evaluate(
            "(() => { const el = document.getElementById('status-logs');"
            " if (!el) return null; const r = el.getBoundingClientRect();"
            " return { top: Math.round(r.top), bottom:"
            " Math.round(r.bottom), headerH: Math.round((document"
            ".querySelector('header.header-sticky')"
            "||{getBoundingClientRect:()=>({height:0})})"
            ".getBoundingClientRect().height),"
            " vh: window.innerHeight, maxed: (() => { const de ="
            " document.scrollingElement; return de.scrollTop >="
            " de.scrollHeight - de.clientHeight - 2; })() }; })()")
        # Блок — ПОСЛЕДНЯЯ карточка страницы: при достижении максимума
        # скролла он обязан быть полностью виден (top ≥ 0, bottom в кадре);
        # если контент ниже ещё есть — top должен встать под шапкой.
        checks["anchor_scroll_visible"] = bool(
            scroll_pos and scroll_pos["top"] is not None
            and scroll_pos["top"] >= 0
            and (scroll_pos["bottom"] <= scroll_pos["vh"] + 2
                 or scroll_pos["top"] <= scroll_pos["headerH"] + 140))

        # ── 390/320: без горизонтального переполнения ──
        for w, name in ((390, "mobile_390"), (320, "narrow_320")):
            page.set_viewport_size({"width": w, "height": 844})
            page.evaluate("window.location.hash = '#/'")
            page.wait_for_timeout(1400)
            checks["no_h_overflow_" + name] = page.evaluate(
                "document.documentElement.scrollWidth <="
                " window.innerWidth + 1")
            shot = os.path.join(SHOTS, "w3_status_%s.png" % name)
            page.screenshot(path=shot, full_page=True)
            result["screenshots"].append(shot)

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
    print("W3-STATUS-E2E-OK" if result["ok"] else "W3-STATUS-E2E-FAIL")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
