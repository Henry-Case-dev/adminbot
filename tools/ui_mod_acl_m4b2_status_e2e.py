"""MOD-ACL-UX-01 M4B B2 — «Статус»: обзор наблюдателя и последний вызов.

Детерминированный Playwright e2e на РЕАЛЬНЫХ `web/index.html` + `web/app.js`
+ `web/static/app.css`; `/api/*` — синтетические стабы (R17: только
идентификаторы/числа/фикстура, без секретов).

Проверяет:
  * health-ленту: deployed revision + checked-at;
  * KPI ≤6 с окном/scope/снимком, без `.funnel-grid`/`.funnel-cell`;
  * независимые KPI + подпись «не конверсия»;
  * две сущности (активные намерения / публикации) и D3 explain;
  * топ-5 причин кликабельны, полный список — в details;
  * последние решения 3–5 строк с датой/action/причиной/доставкой,
    полный ledger — в details;
  * «Проверить инициативу»: mock, не реальная отправка;
  * «Последний вызов»: no-data/empty compact, data (latency/error/cost),
    503 unknown, image-only отдельно; без `Изображений 0/0`;
  * 1920/1440/1280/768/390/320: без горизонтального overflow;
  * «Сон» и «Последний вызов» имеют независимые высоты.

Запуск: py -3 tools/ui_mod_acl_m4b2_status_e2e.py
Артефакты: plans/features/mod-acl-ux-01/evidence/m4b/b2/shots/ + e2e-report.json
"""
import copy
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (сервер/TMA/конфиг — reuse)

PORT = int(os.environ.get("MOD_ACL_M4B2_STATUS_PORT", "8857"))
SHOTS = os.environ.get(
    "MOD_ACL_M4B2_STATUS_SHOTS",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4b", "b2", "shots"))
REPORT = os.environ.get(
    "MOD_ACL_M4B2_STATUS_REPORT",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4b", "b2", "e2e-report.json"))

NOW = 1791900000
CHAT = -1001234567890
CHAT_TITLE = "Audit Chat"
ADMIN_ID = 5885953495

STATUS = copy.deepcopy(M.STATUS_STUB)
STATUS["bot"] = {"uptime_seconds": 3600, "state": "running",
                 "errors_total": 0, "version": "2.58.233"}
STATUS["uptime"] = {"buckets": [], "last_heartbeat": NOW - 30,
                    "until": "2026-11-20T12:00:00+00:00",
                    "generated_at": "2026-11-20T12:00:00+00:00"}
STATUS["intents"] = {
    "enabled": True, "state": "not_run", "active": 3,
    "top": [{"intent_id": "i1", "kind": "open_topic",
             "goal": "вернуться к теме", "status": "pending",
             "priority": 1, "next_check_at": NOW + 600}],
    "last_action": {"ts": NOW - 500, "event": "initiative_decided",
                    "reason_code": "recent_reply"},
    "module": {
        "state_label": "Heartbeat работает, producers за 24ч создали 2 намерения",
        "top_block_reason": "min_gap",
        "funnel": {"producers_24h": {"chat": 2}, "intents_created_24h": 2,
                   "due": 1, "decisions_24h": 2, "sent_24h": 1},
        "heartbeat": {"enabled": True, "registered": True,
                      "last_tick": {"ts": NOW - 60}},
    },
}
STATUS["experience"] = {"enabled": True, "state": "not_run", "items": [],
                        "counters": {"lessons": 0, "active": 0,
                                     "suspended": 0, "applications": 0}}
STATUS["random"] = {"ready": True, "enabled": False}

COGNITION = {
    "dream": {"running": False, "enabled": True, "effective": True,
              "active": False, "active_until": None, "manual": False,
              "last_run_at": NOW - 7200, "next_wake_at": NOW + 3600,
              "state": "sleep",
              "budget": {"distilled_today": 1, "distilled_limit": 5,
                         "tokens_today": 100, "tokens_limit": 2000}},
    "deep_sleep": {"running": False, "enabled": True, "active": False,
                   "active_until": None, "manual": False,
                   "last_run_at": NOW - 3600, "next_run_at": NOW + 7200,
                   "paradigms_status": "ok"},
    "generated_at": NOW,
}
DEEP_SLEEP = {"paradigms_status": "ok", "gate": True, "effective": True}
HEALTH = {
    "beliefs_active": 3, "beliefs_archived": 0, "resurrections_total": 0,
    "decay_runs_total": 1, "last_decay_at": NOW - 4000,
    "facts_overdue": 0, "facts_unconfirmed": 0,
    "smart_messages_total": 42,
    "storage": {"db_size_bytes": 1048576, "db_size_mb": 1.0,
                "disk_free_bytes": 1073741824},
}
EXPIRED = {
    "available": True, "now_ts": NOW, "expired_total": 0,
    "expired_searchable": 0, "needs_recheck": 0,
    "superseded_total": 0, "infinite_retention": True,
}
FUNNELS = {
    "available": True, "now_ts": NOW, "chat_scoped_events": True,
    "initiative": {
        "available": True,
        "job": {"status": "completed", "updated_at": NOW - 1000,
                "counters": {"passes": 3, "observed": 420, "eligible": 25,
                             "scan_skipped": 7, "evals": 22,
                             "opportunities": 4, "silent_decisions": 2,
                             "react_decisions": 2, "intents_created": 0,
                             "sent": 2, "writer_unavailable": 0,
                             "errors": 0,
                             "eval_skips": {"budget": 3}}},
        "liveness": {"ts": NOW - 1100, "status": "ok", "observed": 42,
                     "opportunities": 1},
        "events": {
            "24h": {"initiative_observer_scan": 40,
                    "initiative_opportunity": 2, "initiative_decided": 4,
                    "initiative_writer_generated": 2,
                    "initiative_writer_unavailable": 0,
                    "initiative_recheck_passed": 1, "initiative_sent": 2,
                    "initiative_observer_diagnostic": 0},
            "7d": {"initiative_observer_scan": 260,
                   "initiative_opportunity": 4, "initiative_decided": 5,
                   "initiative_writer_generated": 3,
                   "initiative_writer_unavailable": 1,
                   "initiative_recheck_passed": 2, "initiative_sent": 5,
                   "initiative_observer_diagnostic": 1},
        },
        "domains": {
            "intents": {"source": "mca_intents", "created_total": 0,
                        "active_source": "status.intents.active"},
            "publications": {"source": "mca_events.initiative_sent",
                             "events_24h": 2, "events_7d": 5},
            "same_cohort": False,
            "explain": ("Намерения — долговременные обещания вернуться к теме "
                        "(снимок mca_intents). Публикации — доставленные "
                        "инициативные сообщения (события initiative_sent). "
                        "Повод «уместно сказать сейчас» эфемерный и намерения "
                        "не создаёт, поэтому 0 активных намерений при "
                        "публикациях — нормальное состояние, а не конверсия."),
        },
    },
    "experience": {
        "available": True, "job": {"status": "completed"},
        "semantic_lag": {"pending": 0, "lag_rows": 0},
        "events": {"24h": {}, "7d": {}},
    },
}
VITALITY = {
    "available": True,
    "activity": {
        "state": "opportunities_no_messages", "level": "warn",
        "title": "Возможности есть, сообщений нет",
        "warning": "За окно найдено возможностей: 4, доставлено: 2.",
        "recommendation": "Сверить причины ниже и проверить инициативу.",
        "health": {"heartbeat_ok": True, "jobs_processed": 7},
        "counters": {"delivered": 2},
        "reasons": [
            {"reason_code": "min_gap", "label": "пауза после реплики",
             "count": 12},
            {"reason_code": "recent_reply", "label": "бот недавно отвечал",
             "count": 8},
            {"reason_code": "silence_window", "label": "окно молчания",
             "count": 5},
            {"reason_code": "low_value", "label": "недостаточно ценности",
             "count": 3},
            {"reason_code": "budget", "label": "бюджет исчерпан",
             "count": 2},
            {"reason_code": "other", "label": "прочее", "count": 1},
        ],
    },
    "gates": {"items": [], "soft_targets": {"active": False,
                                            "bounds": "мягкая цель не обещание"}},
    "decisions": [
        {"ts": NOW - 100, "action": "say", "reason_label": "повод найден",
         "delivery": "sent", "delivery_kind": "message",
         "correlation_id": "corr-1"},
        {"ts": NOW - 200, "action": "silent", "reason_label": "пауза",
         "delivery": "", "delivery_kind": "none",
         "correlation_id": "corr-2"},
        {"ts": NOW - 300, "action": "say", "reason_label": "развитие темы",
         "delivery": "sent", "delivery_kind": "message",
         "correlation_id": "corr-3"},
        {"ts": NOW - 400, "action": "silent", "reason_label": "окно молчания",
         "delivery": "", "delivery_kind": "none",
         "correlation_id": "corr-4"},
        {"ts": NOW - 500, "action": "silent", "reason_label": "бюджет",
         "delivery": "", "delivery_kind": "none",
         "correlation_id": "corr-5"},
    ],
    "refusals": [
        {"ts": NOW - 600, "action": "say", "reason_code": "recheck_failed",
         "reason_label": "перепроверка не прошла"},
    ],
    "sends": [
        {"ts": NOW - 100, "message_id": 777, "chars": 48,
         "core_revision": "abc12345xyz", "style_policy_revision": "def45678xyz",
         "composer": "on"},
    ],
}
CHECK_RESULT = {
    "available": True, "published": False, "publish_mode": "mock",
    "publish_disabled_reason": "publish_axis_off", "llm_calls": 2,
    "trace": [
        {"stage": "observer_scan", "status": "ok", "reason_code": "",
         "label": "просканировано 40 сообщений"},
        {"stage": "mock_send", "status": "ok", "reason_code": "",
         "label": "готово к отправке: 42 символа"},
    ],
    "mock_send": {"attempted": True, "preview": "Реплика без публикации",
                  "published": False},
}

TS = "2026-11-20T12:00:00+00:00"
LATEST_DATA = {
    "correlation_id": "corr-b2", "ts": TS,
    "steps": [
        {"ts": TS, "module": "direct_chat", "step": "stage1",
         "tool_name": "", "source": "global", "model": "deepseek-v4",
         "input_tokens": 4000, "output_tokens": 600,
         "tokens_estimated": False, "cost_usd": 0.00174,
         "price_known": True, "latency_ms": 812.5,
         "l1_failure_mode": None, "l1_finish_reason": "stop"},
        {"ts": TS, "module": "direct_chat", "step": "stage2",
         "tool_name": "", "source": "global", "model": "deepseek-v4",
         "input_tokens": 600, "output_tokens": 200,
         "tokens_estimated": False, "cost_usd": 0.0003,
         "price_known": False, "latency_ms": None,
         "l1_failure_mode": "timeout", "l1_finish_reason": None},
    ],
    "total": {"input_tokens": 4600, "output_tokens": 800,
              "cost_usd": 0.00204, "calls": 2},
}
LATEST_EMPTY = {"correlation_id": "", "ts": None, "steps": [],
                "total": {"input_tokens": 0, "output_tokens": 0,
                          "cost_usd": 0, "calls": 0}}
LATEST_IMAGE = {
    "correlation_id": "img-b2", "ts": TS,
    "steps": [{"ts": TS, "module": "image", "step": "image",
               "tool_name": "", "source": "image", "model": "image-model",
               "input_tokens": 0, "output_tokens": 0,
               "tokens_estimated": False, "cost_usd": 0.04,
               "price_known": True, "latency_ms": 1200,
               "l1_failure_mode": None, "l1_finish_reason": None}],
    "total": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.04,
              "calls": 1},
}


def _api_handler(route, analytics_mode="data"):
    req = route.request
    parsed = urlparse(req.url)
    path = parsed.path
    method = req.method
    if path.endswith("/api/analytics/usage/latest"):
        if analytics_mode == "fail":
            route.fulfill(status=503, content_type="application/json",
                          body=json.dumps({"detail": "temporarily unavailable"}))
            return
        if analytics_mode == "empty":
            body = LATEST_EMPTY
        elif analytics_mode == "image":
            body = LATEST_IMAGE
        else:
            body = LATEST_DATA
    elif path.endswith("/api/memory/intel-funnels"):
        body = copy.deepcopy(FUNNELS)
    elif path.endswith("/api/memory/initiative-vitality"):
        body = copy.deepcopy(VITALITY)
    elif path.endswith("/api/memory/initiative-check") and method == "POST":
        body = copy.deepcopy(CHECK_RESULT)
    elif path.endswith("/api/access/chats"):
        body = [{"chat_id": CHAT, "title": CHAT_TITLE, "is_dm": False,
                 "photo_file_id": None, "access": "admin"}]
    elif path.endswith("/api/oversight/summary"):
        body = {"chats": [{"chat_id": CHAT, "title": CHAT_TITLE}],
                "totals": {}}
    elif path.endswith("/api/oversight/dossier_feed"):
        body = {"items": []}
    elif path.endswith("/api/memory/cognition/status"):
        body = COGNITION
    elif path.endswith("/api/memory/deep-sleep"):
        body = DEEP_SLEEP
    elif path.endswith("/api/memory/health"):
        body = HEALTH
    elif path.endswith("/api/memory/expired-overview"):
        body = EXPIRED
    elif path.endswith("/api/persona"):
        body = {"dynamic_traits": [], "traits_status": "ok"}
    elif path.endswith("/api/memory/dream/beliefs"):
        body = []
    elif path.endswith("/api/status/logs"):
        body = {"logs": [], "levels": [], "count": 0, "counts": {}}
    elif path.endswith("/api/status"):
        body = STATUS
    elif path.endswith("/api/config"):
        hdrs = {str(k).lower(): v for k, v in req.headers.items()}
        body = (M.CONFIG_STUB_CHAT if hdrs.get("x-chat-id") in
                (str(CHAT),) else M.CONFIG_STUB)
    else:
        body = M._stub_for(req.url)
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body, ensure_ascii=False))


def _start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _probe(page):
    return page.evaluate(
        """() => {
          const panel = document.querySelector('[data-initiative-independent]');
          const exec = document.querySelector('[data-exec-preview]');
          const sleep = document.querySelector('.status-sleep');
          const rect = (el) => el ? el.getBoundingClientRect() : null;
          const er = rect(exec), sr = rect(sleep);
          return {
            kpis: document.querySelectorAll(
              '[data-observer-kpi]').length,
            funnels: document.querySelectorAll(
              '[data-initiative-independent] .funnel-grid, '
              + '[data-initiative-independent] .funnel-cell').length,
            entities: document.querySelectorAll(
              '[data-observer-entity]').length,
            reasons: document.querySelectorAll(
              '[data-observer-reason]').length,
            decisions: document.querySelectorAll(
              '[data-observer-decision]').length,
            noConversion: panel ? panel.textContent.indexOf('не конверсия') >= 0
              : false,
            explain: panel ? panel.textContent.indexOf('эфемерн') >= 0 : false,
            execState: exec ? exec.getAttribute('data-exec-state') : null,
            execHeight: er ? Math.round(er.height) : null,
            sleepHeight: sr ? Math.round(sr.height) : null,
            execText: exec ? exec.innerText : '',
            observerText: panel ? panel.innerText : '',
            pageNoH: document.documentElement.scrollWidth
              <= window.innerWidth + 1,
          };
        }""")


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    result = {"checks": {}, "viewports": {}, "console": [],
              "screenshots": [], "api_snapshot": {
                  "status_version": "2.58.233",
                  "status_checked_at": STATUS["uptime"]["generated_at"],
                  "intents_active": 3,
                  "funnels_domains": FUNNELS["initiative"]["domains"],
                  "usage_correlation_id": LATEST_DATA["correlation_id"],
                  "scope": "global + chat",
              }}
    failures = []

    def check(name, value):
        result["checks"][name] = bool(value)
        if not value:
            failures.append(name)

    def new_page(browser, width, height, analytics_mode="data"):
        ctx = browser.new_context(viewport={"width": width, "height": height},
                                  reduced_motion="reduce")
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**",
                  lambda route: _api_handler(route, analytics_mode))
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200])
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(
            "pageerror: " + str(e)[:200]))
        page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT,
                  wait_until="load")
        page.wait_for_selector('[data-initiative-independent]', timeout=12000)
        page.wait_for_selector('[data-exec-preview]', timeout=12000)
        page.wait_for_timeout(700)
        return ctx, page, errors

    httpd = _start_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # ── 1. Viewports: KPI/сущности/причины/решения/overflow ───────
            PLAN = [(1920, 1080, "desktop_1920"), (1440, 900, "desktop_1440"),
                    (1280, 800, "desktop_1280"), (768, 1024, "tablet_768"),
                    (390, 844, "mobile_390"), (320, 700, "mobile_320")]
            for width, height, name in PLAN:
                ctx, page, errors = new_page(browser, width, height)
                pr = _probe(page)
                result["viewports"][name] = pr
                check(name + "_six_kpis", pr["kpis"] == 6)
                check(name + "_no_funnel", pr["funnels"] == 0)
                check(name + "_two_entities", pr["entities"] == 2)
                check(name + "_top_reasons", 3 <= pr["reasons"] <= 5)
                check(name + "_recent_decisions", 3 <= pr["decisions"] <= 5)
                check(name + "_no_conversion_note", pr["noConversion"])
                check(name + "_domains_explain", pr["explain"])
                check(name + "_exec_state_ok", pr["execState"] == "ok")
                check(name + "_no_h_overflow", pr["pageNoH"])
                check(name + "_health_observed",
                      page.is_visible('[data-status-observed]')
                      and "2.58.233"
                      in page.inner_text('[data-status-observed]'))
                shot = os.path.join(SHOTS, "status-b2-%s.png" % name)
                page.screenshot(path=shot, full_page=True)
                result["screenshots"].append(shot)
                if errors:
                    result["console"].append({"viewport": name,
                                              "errors": errors[:8]})
                    failures.append(name + "_console_clean")
                ctx.close()

            # ── 2. Интерактивность: причина раскрывается; проверка = mock ──
            ctx, page, errors = new_page(browser, 1440, 900)
            first_reason = page.query_selector(
                '[data-observer-reason] summary')
            first_reason.click()
            page.wait_for_timeout(150)
            check("reason_click_shows_code",
                  page.is_visible('[data-observer-reason] code'))
            page.click('[data-initiative-check]')
            page.wait_for_selector('[data-initiative-trace]', timeout=5000)
            page.click('[data-initiative-trace] summary')
            page.wait_for_timeout(150)
            trace_text = page.inner_text('[data-initiative-trace]')
            result["check_trace_text"] = trace_text
            check("check_mock_note",
                  "Проверка без отправки" in trace_text
                  and "РЕАЛЬНАЯ отправка" not in trace_text)
            check("check_no_publication",
                  "прогон без публикации" in trace_text)
            check("check_console_clean", not errors)
            page.locator('[data-initiative-independent]').screenshot(
                path=os.path.join(SHOTS, "status-b2-observer-1440.png"))
            ctx.close()

            # ── 3. Последний вызов: data (latency/error/cost/tech) ────────
            ctx, page, errors = new_page(browser, 1440, 900)
            text = page.inner_text('[data-exec-preview]')
            check("data_latency", "812" in text or "0.81" in text)
            check("data_error", "timeout" in text)
            check("data_cost_known", "$0.00174" in text)
            check("data_cost_unknown", "нет данных" in text)
            check("data_tokens", "4 000" in text and "600" in text)
            check("data_model", "deepseek-v4" in text)
            check("data_scope_global", "Глобальная аналитика" in text)
            page.click('[data-exec-technical] summary')
            page.wait_for_timeout(150)
            tech = page.inner_text('[data-exec-technical]')
            check("data_correlation_id", "corr-b2" in tech)
            check("data_trace_gap_honest",
                  "Отдельной страницы полной трассы" in tech)
            check("data_console_clean", not errors)
            ctx.close()

            # ── 4. No-data: compact unknown + checked-at/reason ───────────
            ctx, page, errors = new_page(browser, 1440, 900, "empty")
            pr = _probe(page)
            result["no_data"] = pr
            check("empty_state", pr["execState"] == "empty")
            check("empty_checked_at",
                  page.is_visible('[data-exec-checked]')
                  and "—" not in page.inner_text('[data-exec-checked]'))
            check("empty_reason", "Причина" in pr["execText"]
                  and "пустой ответ" in pr["execText"])
            check("empty_compact", pr["execHeight"] is not None
                  and pr["execHeight"] <= 150)
            check("empty_not_stretched",
                  pr["sleepHeight"] is None or pr["execHeight"] < pr["sleepHeight"])
            check("empty_no_zero_zero", "0/0" not in pr["execText"])
            page.locator('[data-exec-preview]').screenshot(
                path=os.path.join(SHOTS, "status-b2-lastcall-empty.png"))
            check("empty_console_clean",
                  not [e for e in errors if "503" not in e])
            ctx.close()

            # ── 5. 503: unknown, не «нет вызова», checked-at есть ─────────
            ctx, page, errors = new_page(browser, 1440, 900, "fail")
            pr = _probe(page)
            result["unavailable"] = pr
            check("fail_state", pr["execState"] == "unavailable")
            check("fail_checked_at", page.is_visible('[data-exec-checked]'))
            check("fail_reason_honest", "503" in pr["execText"])
            check("fail_no_zero_zero", "0/0" not in pr["execText"])
            page.locator('[data-exec-preview]').screenshot(
                path=os.path.join(SHOTS, "status-b2-lastcall-503.png"))
            ctx.close()

            # ── 6. Только изображение: названо отдельно, не LLM-вызов ─────
            ctx, page, errors = new_page(browser, 1440, 900, "image")
            pr = _probe(page)
            result["image_only"] = pr
            check("image_state_ok", pr["execState"] == "ok")
            check("image_named_separately",
                  page.is_visible('[data-exec-image]')
                  and "не текстовый LLM-вызов" in pr["execText"])
            check("image_cost_visible", "$0.04" in pr["execText"])
            check("image_no_zero_zero", "0/0" not in pr["execText"])
            page.locator('[data-exec-preview]').screenshot(
                path=os.path.join(SHOTS, "status-b2-lastcall-image.png"))
            ctx.close()

            # ── 7. Scope: переключение на чат не смешивает global KPI ─────
            ctx, page, errors = new_page(browser, 1440, 900)
            page.click(".scope-trigger")
            page.click(".scope-option:has-text('%s')" % CHAT_TITLE)
            page.wait_for_timeout(1200)
            scoped = page.evaluate(
                """() => {
                  const snap = document.querySelector('[data-observer-snapshot]');
                  const panel = document.querySelector(
                    '[data-initiative-independent]');
                  return {snap: snap ? snap.innerText : '',
                          text: panel ? panel.innerText : '',
                          active: document.querySelectorAll(
                            '[data-observer-kpi="intents"]').length};
                }""")
            result["scope"] = scoped
            check("scope_chat_named", "чат" in scoped["snap"])
            check("scope_active_intents",
                  "Активные намерения" in scoped["text"])
            check("scope_console_clean", not errors)
            page.screenshot(path=os.path.join(SHOTS, "status-b2-chat-scope.png"),
                            full_page=True)
            ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    result["failures"] = failures
    result["ok"] = not failures
    result["limitations"] = [
        "Synthetic Playwright API stub; production bytes of the candidate "
        "are served locally, not a live TMA session.",
        "D1 latency appears only when plan_meta exists; image-only/503 are "
        "deterministic stubs, not natural production events.",
        "No backend/DDL/flags/prompts changed beyond D1/D3 read-only fields.",
    ]
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": result["ok"], "checks": len(result["checks"]),
                      "failures": failures}, ensure_ascii=False))
    print("report:", REPORT)
    print("M4B-B2-STATUS-E2E-OK" if result["ok"] else "M4B-B2-STATUS-E2E-FAIL")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
