"""mca-17a round 10.27 — Browser-Verification carry-over §94.5 (SC-13/SC-14).

Расширение существующего харнесса `tools/ui_round1025_matrix.py` (тот же
локальный http-сервер + `Telegram.WebApp`-stub + перехват `/api/*`), реальный
`web/index.html` + `web/app.js`. Новых библиотек/второго dev-стека нет.

Проверяется (витрина — СУЩЕСТВУЮЩИЙ viewer, без новых панелей/маршрутов):
  * SC-13: на `#/oversight` аддитивный блок `mca_metrics` отображает метрики
    §17.4 + компактный индикатор инцидентов; группа без продюсера — честно
    «нет данных», не 0/«здоровье»;
  * SC-14: в СУЩЕСТВУЮЩЕМ log viewer (`#/`) доступны фильтры
    trace_id/chat_id/component/reason_code; переход «Связанные события» отдаёт
    связанные `mca_events` (deep link на trace); пустой результат — honest empty;
  * console/pageerror пусты.

Запуск: .venv/Scripts/python.exe tools/ui_round1027_mca17a_observability.py
Артефакты: tools/_ui_round1027_mca17a.json (+ PNG).
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_round1025_matrix as M  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = M.REPO
PORT = M.PORT + 7
RAW = os.path.join(REPO, "tools", "_ui_round1027_mca17a.json")
SHOT = os.path.join(REPO, "tools", "_ui_round1027_mca17a.png")

# Витринные данные: одна группа без продюсера (`cache` → unknown) + инцидент.
MCA_METRICS = {
    "available": True,
    "source": "mca_events",
    "events_total": 12,
    "errors_total": 1,
    "degraded_total": 0,
    "dropped_total": 0,
    "spooled_total": 0,
    "gaps_total": 2,
    "telemetry_degraded": True,
    "degraded_share": None,
    "unknown": ["cache", "runtime", "provenance"],
    "metrics": {},
    "incidents": {"available": True, "active": 3, "unacknowledged": 2,
                  "by_severity": {"ERROR": 2, "WARN": 1}},
}

RELATED_EVENTS = [
    {"level": "ERROR", "event_name": "LLM_CALL", "stage": "llm",
     "status": "failed", "trace_id": "run_ab", "pipeline_run_id": "run_ab",
     "component": "direct.reply", "reason_code": "provider_unavailable"},
    {"level": "INFO", "event_name": "PIPELINE_START", "stage": "queued",
     "status": "queued", "trace_id": "run_ab", "pipeline_run_id": "run_ab",
     "component": "direct.reply", "reason_code": None},
]


# Pre-existing baseline-особенность token-flow (`execMetricsRows` в
# `computed`, а вызван как функция) не относится к mca-17a; в харнессе
# отключаем авто-ветку токен-флоу гейтом, чтобы избежать чужого render-error
# и проверить именно carry-over SC-13/SC-14. Продуктовые файлы не меняются.
def _me_stub():
    me = json.loads(json.dumps(M.ME_JSON))
    me.setdefault("ui_flags", {})["TOKEN_FLOW_NODEFLOW_ENABLED"] = False
    return me


UNAVAILABLE = {"on": False}
CHANGES_CALLS = []      # since_ts каждого запроса incident_changes (SC-16)

PROXY_JS = """
(() => {
  const el = document.querySelector('#app');
  const app = el && el.__vue_app__;
  const inst = (app && app._instance)
    || (el && el._vnode && el._vnode.component);
  return inst && (inst.proxy || inst.ctx) || null;
})()
"""


def _api_handler(route):
    req = route.request
    path = req.url.split("?")[0]
    if path.endswith("/api/me"):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_me_stub()))
        return
    if path.endswith("/api/oversight/summary"):
        metrics = ({"available": False, "degraded_share": None,
                    "errors_total": None, "gaps_total": None,
                    "spooled_total": None, "telemetry_degraded": False,
                    "unknown": [], "metrics": {},
                    "incidents": {"available": False, "active": None,
                                  "unacknowledged": None}}
                   if UNAVAILABLE["on"] else MCA_METRICS)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "generated_at": "2026-09-27T00:00:00Z", "chats": [], "errors": [],
            "global_budget": {}, "cached": "60s-server-cache",
            "mca_metrics": metrics,
        }))
        return
    if path.endswith("/api/oversight/incidents/changes"):
        qs = req.url.split("?", 1)[1] if "?" in req.url else ""
        since = 0
        for part in qs.split("&"):
            if part.startswith("since_ts="):
                try:
                    since = int(part.split("=", 1)[1] or 0)
                except Exception:  # noqa: BLE001
                    since = 0
        CHANGES_CALLS.append(since)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "available": True, "enabled": True, "cursor": since + 1,
            "changes": [], "push_interval_seconds": 1,
            "indicator": {"available": True, "active": 3, "unacknowledged": 2,
                          "by_severity": {"ERROR": 2, "WARN": 1}},
        }))
        return
    if path.endswith("/api/status/logs"):
        qs = req.url.split("?", 1)[1] if "?" in req.url else ""
        has_filter = any(k in qs for k in
                         ("trace_id=", "chat_id=", "component=", "reason_code="))
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "count": 0, "counts": {"ERROR": 1, "WARNING": 0}, "logs": [],
            "events": RELATED_EVENTS if has_filter else [],
        }))
        return
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(M._stub_for(req.url)))


def _run():
    from playwright.sync_api import sync_playwright

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    result = {"meta": {}, "sc13": {}, "sc14": {}, "failures": []}
    failures = result["failures"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _api_handler)
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append("%s: %s" % (m.type, m.text[:160]))
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)[:200]))
        url = "http://127.0.0.1:%d/web/index.html" % PORT

        # ── SC-13: mca_metrics на #/oversight ────────────────────────────
        page.goto(url + "#/oversight", wait_until="load")
        try:
            page.wait_for_selector(".app-shell", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1000)
        page.evaluate("() => { window.location.hash = '#/oversight'; }")
        page.wait_for_timeout(900)
        block = page.query_selector("#mca-metrics-block")
        result["sc13"]["block_present"] = block is not None
        if block is None:
            failures.append("SC-13: блок #mca-metrics-block не найден")
        else:
            text = block.inner_text()
            result["sc13"]["text"] = text[:300]
            for needle, key in (("Наблюдаемость (mca)", "title"),
                                ("инциденты", "incidents")):
                if needle not in text:
                    failures.append("SC-13: нет '%s' в блоке" % needle)
            # индикатор инцидентов: acknowledged ≠ resolved
            if "3" not in text or "не подтв" not in text:
                failures.append("SC-13: инциденты отображены неверно: %s" % text)
            # degraded=unknown (не 0/не «здоровье»)
            if "degraded: неизвестно" not in text:
                failures.append("SC-13: degraded не показан как «неизвестно»")
            # gaps/spool видны; unknown-группы перечислены
            if "gaps" not in text or "spool" not in text:
                failures.append("SC-13: gaps/spool не показаны")
            if "cache" not in text:
                failures.append("SC-13: список unknown-групп пуст")
            page.screenshot(path=SHOT)

        # ── SC-16 (F5/D16): refresh индикатора инцидентов через read-only
        # `incident_changes` с cursor, интервал ≤10с; reconnect-догон ─────────
        page.wait_for_timeout(3400)
        result["sc16"] = {"changes_calls": list(CHANGES_CALLS)}
        if len(CHANGES_CALLS) < 2:
            failures.append(
                "SC-16: polling incident_changes не повторяется (<2 запросов "
                "за 3.4с): %s" % CHANGES_CALLS)
        elif CHANGES_CALLS[1] <= CHANGES_CALLS[0]:
            failures.append(
                "SC-16: cursor не продвигается (reconnect-догон): %s"
                % CHANGES_CALLS)

        # ── SC-13b: недоступная телеметрия → honest unknown (не зелёный) ────
        UNAVAILABLE["on"] = True
        page.evaluate("() => { window.location.hash = '#/'; }")
        page.wait_for_timeout(500)
        page.evaluate("() => { window.location.hash = '#/oversight'; }")
        page.wait_for_timeout(500)
        # Принудительный рефетч (кнопка ⟳/метод loadOversight) — иначе Vue
        # держит прежний oversightData и недоступность не проверить.
        page.evaluate(
            "() => { const p = %s; if (p && p.loadOversight) "
            "return p.loadOversight(); }" % PROXY_JS)
        page.wait_for_timeout(1200)
        block2 = page.query_selector("#mca-metrics-block")
        result["sc13b"] = {"block_present": block2 is not None}
        if block2 is None:
            failures.append("SC-13b: блок не отрендерен при available=false")
        else:
            text2 = block2.inner_text()
            result["sc13b"]["text"] = text2[:300]
            classes = block2.query_selector_all(".badge")
            class_str = " ".join((c.get_attribute("class") or "")
                                 for c in classes)
            result["sc13b"]["badge_classes"] = class_str
            if "badge-ok" in class_str:
                failures.append("SC-13b: ложный зелёный badge-ok при "
                                "available=false")
            if "неизвестно" not in text2:
                failures.append("SC-13b: нет honest «неизвестно»: %s" % text2)
        UNAVAILABLE["on"] = False

        # ── SC-14: фильтры связанных событий в существующем log viewer ────
        page.evaluate("() => { window.location.hash = '#/'; }")
        page.wait_for_timeout(1000)
        filters = page.query_selector("#mca-log-filters")
        result["sc14"]["filters_present"] = filters is not None
        if filters is None:
            failures.append("SC-14: #mca-log-filters не найден")
        else:
            # заполняем фильтр trace_id и жмём «Связанные события»
            inp = page.query_selector("#mca-log-filters input")
            if inp is None:
                failures.append("SC-14: поле trace_id не найдено")
            else:
                inp.fill("run_ab")
                page.wait_for_timeout(150)
                btn = page.query_selector("#mca-log-filters button")
                if btn is None:
                    failures.append("SC-14: кнопка «Связанные события» не найдена")
                else:
                    btn.click()
                    page.wait_for_timeout(700)
            related = page.query_selector("#mca-related-events")
            result["sc14"]["related_present"] = related is not None
            if related is None:
                failures.append("SC-14: #mca-related-events не появился")
            else:
                rtext = related.inner_text()
                result["sc14"]["text"] = rtext[:300]
                if "LLM_CALL" not in rtext or "run_ab" not in rtext:
                    failures.append("SC-14: связанные события не отображены: %s"
                                    % rtext)
                page.screenshot(path=SHOT)

        # Известный baseline-дефект чужой фичи (token-flow): `execMetricsRows`
        # объявлен в `computed`, но вызван как функция — воспроизводится на
        # ЧИСТЫХ baseline web-файлах (проверено отдельным прогоном харнесса
        # против откаченных `web/app.js`/`web/index.html`), к mca-17a не
        # относится. Не считаем его за mca-17a-регресс; любой ДРУГОЙ console/
        # pageerror — провал.
        known_baseline = [e for e in errors if "execMetricsRows is not a function"
                          in e]
        result["baseline_console_errors"] = len(known_baseline)
        for m in errors:
            if "execMetricsRows is not a function" in m:
                continue
            failures.append("console/pageerror: %s" % m)
        result["meta"] = {"port": PORT, "url": url}
        ctx.close()
        browser.close()
    httpd.shutdown()

    result["failures"] = failures
    with open(RAW, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("[mca17a-ui] failures:", len(failures))
    for x in failures:
        print("  !", x)
    print("[mca17a-ui] sc13 block=%s; sc14 filters=%s related=%s"
          % (result["sc13"].get("block_present"),
             result["sc14"].get("filters_present"),
             result["sc14"].get("related_present")))
    print("[mca17a-ui] артефакт:", RAW)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run())
