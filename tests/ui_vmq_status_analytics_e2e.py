"""VMQ-TIME-09 — Playwright e2e «покрытие памяти по годам» (детерминированный).

Рендерит РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css`
поверх deployed-базы 2.58.217; `/api/*` — стабы из реальных payload-схем
(`turn-diagnostics`), R17: только коды/числа. Проверяется:

  * Status `#/`: компактная секция после «Здоровья памяти» до «Инициативы»,
    годы Writer-блоков и причины исключений, без `%`, без canvas/svg,
    кнопка ⟳ 44 px;
  * Analytics `#/oversight?tab=memory`: карточка ровно между «Цикл памяти
    (24ч)» и «Embeddings», список вызовов (data-rc-run), пять подписей
    причин, «← предыдущий ход» (turn=2), без нового таба/dropdown-пункта;
  * 1280/390/320: `scrollWidth <= innerWidth + 1`, планшетные табы 44 px,
    на десктопе табы скрыты и видны 4 ленты;
  * состояния: empty (no_turn_traces), error (500), truncated (amber);
    non-admin — блока нет и запроса нет;
  * сеть: один GET диагностики на вход/⟳ (кэш общий для двух поверхностей),
    `/api/memory/retrieval-coverage` НЕ вызывается;
  * console/pageerror = 0.

Запуск:
  .venv\\Scripts\\python.exe tests\\ui_vmq_status_analytics_e2e.py
Артефакты: --out <json> и --shots <dir> (по умолчанию temp).
"""
import argparse
import copy
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402

PORT = 8841
CHAT = -1001234567890
NOW = 1795000000


def _selection(blocks, *, period=None, truncated=False):
    payload = {
        "policy_version": "alloc_v3",
        "counts": {"available_messages": 40, "included_messages": 12,
                   "window_messages": 25},
        "blocks": blocks,
        "dropped": [{"reason_code": "over_budget", "kind": "rag",
                     "count": 3}],
        "self_outputs": [],
    }
    if period is not None:
        payload["memory_period"] = period
    if truncated:
        payload["truncated"] = True
    return payload


PERIOD = {
    "policy": "auto", "replace_allowed": 1,
    "period_skipped": "auto_no_replace",
    "intent": {"kind": "historical", "years": [2023],
               "source": "memory_scope"},
    "intent_source": "memory_scope", "pool": 12, "kept": 3,
    "historical_quota": 2, "multi_year_quota": 1, "dropped_subject": 1,
    "dropped_budget": 2, "dropped_status": 1,
    "dropped_out_of_target_year": 0, "dropped_unknown_year": 0,
    "pool_status": {"confirmed": 2, "archived": 1}, "pool_expired": 0,
    "age_policy": "expiry", "vector_leg": "knn", "vector_rows": 12,
}

RUN_MAIN = {
    "ts": NOW,
    "outcome": "success",
    "reason_code": "episodes_used",
    "policy": "auto",
    "period": False,
    "years": {"2023": 2, "2026": 8},
    "years_present": True,
    "excluded": {"policy_operative": 4, "status": 3, "expired": 0,
                 "relevance": 1, "budget": 2},
    "excluded_present": True,
}
RUN_PERIOD = {
    "ts": NOW + 1,
    "outcome": "success",
    "reason_code": None,
    "policy": "auto",
    "period": True,
    "years": {"2023": 1},
    "years_present": True,
    "excluded": {"budget": 1},
    "excluded_present": True,
}


def diagnostics_payload(*, turn=1, empty=False, truncated=False):
    if empty:
        return {"chat_id": CHAT, "available": False,
                "reason": "no_turn_traces", "turns": []}
    blocks = [
        {"kind": "global_tail", "role": "p1", "rendered": True,
         "source_ids": ["msg:1"], "tokens": 300, "years": {"2026": 3},
         "years_present": True},
    ]
    if not truncated:
        blocks.extend([
            {"kind": "rag", "role": "p2", "rendered": True,
             "source_ids": ["fact:1", "fact:2"], "tokens": 800,
             "years": {"2023": 2, "2026": 7}, "years_present": True},
            {"kind": "episode", "role": "p2", "rendered": True,
             "source_ids": ["episode:1"], "tokens": 200,
             "years": {"2023": 1}, "years_present": True},
        ])
    current = "trace-current" if turn == 1 else "trace-prev%d" % turn
    runs = [copy.deepcopy(RUN_MAIN), copy.deepcopy(RUN_PERIOD)]
    if turn > 1:
        runs = [copy.deepcopy(RUN_PERIOD)]
        runs[0]["ts"] = NOW - 60
    return {
        "chat_id": CHAT,
        "available": True,
        "trace_id": current,
        "ts": NOW if turn == 1 else NOW - 60,
        "turns": [
            {"trace_id": "trace-current", "ts": NOW, "trigger": "botword"},
            {"trace_id": "trace-prev2", "ts": NOW - 60,
             "trigger": "botword"},
        ],
        "selection": _selection(
            blocks, period=PERIOD if not truncated else None,
            truncated=truncated),
        "stages": {"context": True, "writer": True, "delivery": True,
                   "selection": True, "search": False, "tool_phase": False,
                   "style": False, "retrieval": True},
        "retrieval": runs,
    }


def _start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _safe_text(page, selector):
    try:
        el = page.query_selector(selector)
        return el.inner_text() if el else ""
    except Exception:  # noqa: BLE001
        return ""


def _check(checks, name, value):
    checks[name] = bool(value)
    return bool(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--shots", default="")
    args = parser.parse_args()
    shots = args.shots or os.path.join(tempfile.gettempdir(),
                                       "time09-shots")
    os.makedirs(shots, exist_ok=True)
    httpd = _start_server()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    result = {"checks": {}, "console_errors": [], "screenshots": [],
              "routes": {"diagnostics": [], "retrieval_coverage": 0},
              "ok": False}
    checks = result["checks"]

    from playwright.sync_api import sync_playwright

    def scenario_context(browser, *, width, height, mode="normal",
                         touch=False):
        ctx = browser.new_context(viewport={"width": width, "height": height},
                                  reduced_motion="reduce",
                                  has_touch=bool(touch),
                                  is_mobile=bool(touch))
        ctx.add_init_script(M.TMA_STUB)

        def handler(route):
            url = route.request.url.split("?")[0]
            if url.endswith("/api/direct/turn-diagnostics"):
                result["routes"]["diagnostics"].append(route.request.url)
                if mode == "error":
                    route.fulfill(status=500, content_type="text/plain",
                                  body="diagnostics unavailable")
                    return
                turn = 1
                for part in route.request.url.split("?")[-1].split("&"):
                    if part.startswith("turn="):
                        try:
                            turn = int(part[5:])
                        except ValueError:
                            turn = 1
                body = diagnostics_payload(
                    turn=turn, empty=(mode == "empty"),
                    truncated=(mode == "truncated"))
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(body, ensure_ascii=False))
                return
            if url.endswith("/api/memory/retrieval-coverage"):
                result["routes"]["retrieval_coverage"] += 1
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"available": True}))
                return
            if url.endswith("/api/me") and mode == "nonadmin":
                me = copy.deepcopy(M.ME_JSON)
                me.update({"role_name": "user", "permissions": {},
                           "is_global_admin": False,
                           "is_local_admin": False})
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(me, ensure_ascii=False))
                return
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(M._stub_for(route.request.url),
                                ensure_ascii=False))

        ctx.route("**/api/**", handler)
        page = ctx.new_page()
        if mode != "error":
            # Намеренный 500 в сценарии ошибки — не JS-ошибка страницы.
            page.on("console", lambda m: result["console_errors"].append(
                m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror: " + str(e)[:200]))
        page.on("dialog", lambda d: d.accept())
        return ctx, page

    def no_overflow(page, tag):
        return _check(
            checks, "no_overflow_" + tag,
            page.evaluate("document.documentElement.scrollWidth"
                          " <= window.innerWidth + 1"))

    def block_shape(page, tag):
        block = "[data-retrieval-coverage-status]"
        _check(checks, "status_block_present_" + tag,
               page.evaluate("!!document.querySelector('%s')" % block))
        text = _safe_text(page, block)
        _check(checks, "status_years_" + tag, "2023 — 2" in text)
        _check(checks, "status_exclusions_" + tag, "квота 4" in text)
        _check(checks, "status_no_percent_" + tag, "%" not in text)
        _check(checks, "status_no_canvas_" + tag,
               page.evaluate("(document.querySelector('%s')"
                             "||{querySelectorAll:()=>[]})"
                             ".querySelectorAll('canvas,svg').length === 0"
                             % block))
        _check(checks, "status_refresh_44_" + tag, page.evaluate(
            "(() => { const b = document.querySelector('%s button');"
            " if (!b) return false; const r = b.getBoundingClientRect();"
            " return r.width >= 44 && r.height >= 44; })()" % block))
        _check(checks, "status_after_memory_before_intents_" + tag,
               page.evaluate(
                   "(() => { const m = document.querySelector("
                   "'[data-memory-tech]'); const b = document.querySelector("
                   "'[data-retrieval-coverage-status]'); const i ="
                   " document.querySelector('[data-intents]');"
                   " if (!m || !b || !i) return false;"
                   " return !!(m.compareDocumentPosition(b) & 4)"
                   " && !!(b.compareDocumentPosition(i) & 4); })()"))

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()

            # ── 1280: Status + Analytics, общий кэш/сеть ────────────────
            ctx, page = scenario_context(browser, width=1280, height=900)
            page.goto(base, wait_until="load")
            page.wait_for_timeout(2200)
            block_shape(page, "1280")
            no_overflow(page, "1280")
            _check(checks, "status_tabs_hidden_desktop",
                   page.evaluate("(() => { const t = document.querySelector("
                                 "'.intel-tabs'); if (!t) return false;"
                                 " const s = getComputedStyle(t);"
                                 " return s.display === 'none'"
                                 " || t.offsetParent === null; })()"))
            _check(checks, "status_ribbons_desktop",
                   page.evaluate("document.querySelectorAll("
                                 "'.cognition-ribbons [data-intel-section]')"
                                 ".length") >= 4)
            _check(checks, "diag_one_request_on_entry",
                   len(result["routes"]["diagnostics"]) == 1)
            shot = os.path.join(shots, "time09_status_1280.png")
            page.screenshot(path=shot, full_page=True)
            result["screenshots"].append(shot)

            page.evaluate("window.location.hash ="
                          " '#/oversight?tab=memory'")
            page.wait_for_timeout(1800)
            _check(checks, "analytics_card_present", page.evaluate(
                "!!document.querySelector("
                "'[data-retrieval-coverage-analytics]')"))
            analytics = _safe_text(
                page, "[data-retrieval-coverage-analytics]")
            _check(checks, "analytics_runs_count", page.evaluate(
                "document.querySelectorAll("
                "'[data-retrieval-coverage-analytics] [data-rc-run]')"
                ".length") == 2)
            _check(checks, "analytics_five_reasons",
                   all(label in analytics for label in
                       ("квота", "статус", "давность", "релевантность",
                        "бюджет")))
            _check(checks, "analytics_no_percent", "%" not in analytics)
            _check(checks, "analytics_between_flow_and_embeddings",
                   page.evaluate(
                       "(() => { const a = document.querySelector("
                       "'[data-viz-flow]'); const b = document.querySelector("
                       "'[data-retrieval-coverage-analytics]');"
                       " const c = document.querySelector("
                       "'#embeddings-inspector-block');"
                       " if (!a || !b || !c) return false;"
                       " return !!(a.compareDocumentPosition(b) & 4)"
                       " && !!(b.compareDocumentPosition(c) & 4); })()"))
            _check(checks, "analytics_no_new_tab",
                   page.evaluate("document.querySelectorAll("
                                 "'.oversight-tab').length") == 7)
            _check(checks, "analytics_shared_cache_no_second_request",
                   len(result["routes"]["diagnostics"]) == 1)
            prev = page.query_selector(
                "[data-retrieval-coverage-analytics] [data-rc-prev]")
            _check(checks, "analytics_prev_present", prev is not None)
            if prev is not None:
                prev.click()
                page.wait_for_timeout(1200)
                _check(checks, "analytics_prev_requests_turn2",
                       any("turn=2" in url for url in
                           result["routes"]["diagnostics"]))
                next_btn = page.query_selector(
                    "[data-retrieval-coverage-analytics] [data-rc-next]")
                _check(checks, "analytics_next_appears", next_btn is not None)
            shot = os.path.join(shots, "time09_analytics_1280.png")
            page.screenshot(path=shot, full_page=True)
            result["screenshots"].append(shot)
            ctx.close()

            # ── 390/320: реальные мобильные ширины ──────────────────────
            for width in (390, 320):
                ctx, page = scenario_context(browser, width=width,
                                             height=844, touch=True)
                page.goto(base, wait_until="load")
                page.wait_for_timeout(2200)
                block_shape(page, str(width))
                no_overflow(page, str(width))
                _check(checks, "mobile_tabs_44_" + str(width),
                       page.evaluate(
                           "(() => { const t = Array.from(document"
                           ".querySelectorAll('.intel-tabs__btn'));"
                           " return t.length === 4 && t.every(function (x) {"
                           " const r = x.getBoundingClientRect();"
                           " return r.width >= 44 && r.height >= 44; });"
                           " })()"))
                shot = os.path.join(shots,
                                    "time09_status_%d.png" % width)
                page.screenshot(path=shot, full_page=True)
                result["screenshots"].append(shot)
                block_shot = os.path.join(
                    shots, "time09_block_%d.png" % width)
                el = page.query_selector(
                    "[data-retrieval-coverage-status]")
                if el is not None:
                    el.screenshot(path=block_shot)
                    result["screenshots"].append(block_shot)
                ctx.close()

            # ── empty / error / truncated / non-admin ───────────────────
            ctx, page = scenario_context(browser, width=1280, height=900,
                                         mode="empty")
            page.goto(base, wait_until="load")
            page.wait_for_timeout(1800)
            empty_text = _safe_text(page, "[data-retrieval-coverage-status]")
            _check(checks, "empty_reason_honest",
                   "Ходов этого чата ещё нет" in empty_text)
            _check(checks, "empty_no_numbers", "нет фактов" not in empty_text)
            ctx.close()

            ctx, page = scenario_context(browser, width=1280, height=900,
                                         mode="error")
            page.goto(base, wait_until="load")
            page.wait_for_timeout(1800)
            err_text = _safe_text(page, "[data-retrieval-coverage-status]")
            _check(checks, "error_reason_honest",
                   "Не удалось загрузить покрытие" in err_text)
            _check(checks, "error_page_alive",
                   page.evaluate("!!document.querySelector("
                                 "'[data-memory-tech]')"))
            ctx.close()

            ctx, page = scenario_context(browser, width=1280, height=900,
                                         mode="truncated")
            page.goto(base, wait_until="load")
            page.wait_for_timeout(1800)
            trunc_text = _safe_text(page,
                                    "[data-retrieval-coverage-status]")
            _check(checks, "truncated_warning_present",
                   "усечена" in trunc_text)
            _check(checks, "truncated_no_zero_for_missing",
                   "RAG" not in trunc_text or "не зафиксировано" in trunc_text)
            ctx.close()

            before = len(result["routes"]["diagnostics"])
            ctx, page = scenario_context(browser, width=1280, height=900,
                                         mode="nonadmin")
            page.goto(base, wait_until="load")
            page.wait_for_timeout(1800)
            _check(checks, "nonadmin_block_absent",
                   not page.evaluate("!!document.querySelector("
                                     "'[data-retrieval-coverage-status]')"))
            _check(checks, "nonadmin_no_request",
                   len(result["routes"]["diagnostics"]) == before)
            ctx.close()

            _check(checks, "aggregate_endpoint_not_called",
                   result["routes"]["retrieval_coverage"] == 0)
            _check(checks, "console_errors_zero",
                   len(result["console_errors"]) == 0)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        result["fatal"] = repr(exc)
    finally:
        try:
            httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass

    result["ok"] = bool(result["checks"]) and all(result["checks"].values()) \
        and "fatal" not in result
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"ok": result["ok"],
                      "failed": [name for name, value in checks.items()
                                 if not value],
                      "fatal": result.get("fatal", ""),
                      "routes": result["routes"],
                      "console_errors": result["console_errors"]},
                     ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
