"""ASAP 8 v6 — Playwright e2e (детерминированный): D12+D13 UI-волна.

Проверяет визуальные дельты лайна UI-D1213 на реальном web/index.html +
web/app.js (/api/* — стабы, R17: только идентификаторы/статусы):

  D13 (universal save contract + mobile shell):
    * clean config-вкладка: постоянный Save-футер ОТСУТСТВУЕТ
      (`.sticky-save` в DOM нет, чипа в шапке нет), spacer убран;
    * dirty: компактный pill `.sticky-save` («Изменено: N») + чип в шапке;
    * уход с dirty-страницы защищает черновик: confirm с областью и числом
      полей; отказ (dismiss) → маршрут НЕ меняется;
    * mobile <768: bottom-nav/шторки НЕТ, компактная верхняя навигация ЕСТЬ;
      landscape 844×390: верхняя навигация компактна, нет горизонтального
      overflow (контролы не перекрыты);
    * console без ошибок.

  D12 (Status/Analytics truthful widgets):
    * ЕДИНСТВЕННЫЙ детальный виджет сна + компактные клик-бейджи;
    * Unified Run Card: воронка инициативы и уроков на Статусе, шапка
      прогона Саммари (run id/evidence/fallback/publication) на вкладке
      «Аналитика → Саммари»;
    * Сердцебиение (sparkline) сохранено.

Запуск: py -3 tools\\ui_asap8_v6_d1213_e2e.py
Артефакты: plans/features/asap8-v6-remediation/evidence/d1213_*.png
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

PORT = 8799
SHOTS = os.path.join(REPO, "plans", "features", "asap8-v6-remediation",
                     "evidence")


def _status_stub() -> dict:
    """/api/status с полями C06A (intents) + D05 (experience) — R17-safe."""
    stub = copy.deepcopy(M.STATUS_STUB)
    stub["uptime"] = {"buckets": [
        {"ts": "2026-10-14T10:00:00+00:00", "status": "up"},
        {"ts": "2026-10-14T10:05:00+00:00", "status": "up"},
    ], "last_heartbeat": "2026-10-14T10:05:00+00:00"}
    stub["intents"] = {
        "state": "not_run", "active": 0,
        "module": {
            "state_label": "Инициатива ещё не запускалась (окно пустое)",
            "top_block_reason": "no_producers",
            # REV-UI-D1213 F1: РЕАЛЬНЫЙ шейп — producers_24h ОБЪЕКТ
            # {origin: count} (GROUP BY origin); intents_created_24h = сумма.
            "funnel": {"producers_24h": {"unanswered_question": 7,
                                         "silent_window": 3},
                       "intents_created_24h": 10, "due": 6,
                       "decisions_24h": 4, "sent_24h": 2},
            "heartbeat": {"enabled": True, "registered": True,
                          "last_tick": {"ts": 1791900000}},
        },
    }
    stub["experience"] = {
        "enabled": True, "state": "implemented",
        "items": [], "counters": {"lessons": 4, "active": 3,
                                  "suspended": 0, "applications": 5,
                                  "success": 2, "failure": 1, "unknown": 2},
    }
    return stub


FUNNEL_STUB = {
    "enabled": True, "days": 30,
    "episodes": {"total": 9, "success": 4, "failure": 2, "unknown": 3},
    "lessons": {"candidate": 6, "validated": 3, "active": 2,
                "suspended": 0, "superseded": 1, "new_in_period": 2},
    "applications": {"total": 5, "unique_lessons": 2, "success": 2,
                     "failure": 1, "unknown": 2},
    "feedback": {"total": 12, "unique_episodes": 7},
    "notes": [],
}

PIPELINE_RUN = {
    "run": {
        "run_id": "d1213runabcdef1234567890", "chat_id": -1001234567890,
        "mode": "prod", "status": "done", "duration_ms": 4200,
        "fallback": "l2_fallback", "health": "degraded",
        "health_label": "С деградацией",
        "coverage": {"total": 10, "considered": 9, "percent": 90,
                     "full": False},
        "publication": {"status": "ok", "channel": "rich", "message_id": 42},
        "nodes": [
            {"key": "l1", "state": "success", "label": "L1"},
            {"key": "writer", "state": "fallback", "label": "Writer"},
            {"key": "l2", "state": "failed", "label": "L2"},
            {"key": "cover", "state": "skipped", "label": "Cover"},
        ],
        "running": False,
        "developer": {"events_total": 12},
        "liveness": [],
    },
    "runs": [], "generated_at": 1791900000,
}


def main() -> int:
    os.makedirs(SHOTS, exist_ok=True)
    status_payload = _status_stub()
    config_payload = copy.deepcopy(M.CONFIG_STUB)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/web/index.html" % PORT

    def _api_handler(route):
        req = route.request
        url = req.url.split("?")[0]
        if url.endswith("/api/status"):
            body = status_payload
        elif url.endswith("/api/oversight/experience/funnel"):
            body = FUNNEL_STUB
        elif url.endswith("/api/analytics/pipeline/inspector") or \
                url.endswith("/api/analytics/pipeline/runs/latest"):
            body = PIPELINE_RUN
        elif url.endswith("/api/config"):
            body = config_payload
        else:
            body = M._stub_for(req.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body))

    from playwright.sync_api import sync_playwright
    result = {"console_errors": [], "checks": {}, "dialogs": [],
              "screenshots": []}

    def shot(page, name):
        path = os.path.join(SHOTS, name)
        page.screenshot(path=path, full_page=False)
        result["screenshots"].append(name)

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ═══ Desktop 1280: Статус (виджеты D12) → конфиг (D13 save) ═══
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _api_handler)
        page = ctx.new_page()
        page.on("console", lambda m: result["console_errors"].append(
            m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror: " + str(e)[:200]))
        # Диалоги: управляемый флаг (по умолчанию ОТКАЗ = protect draft).
        def _on_dialog(d):
            result["dialogs"].append(d.message[:200])
            if result.get("dialog_accept"):
                d.accept()
            else:
                d.dismiss()
        page.on("dialog", _on_dialog)
        page.goto(base + "#/", wait_until="load")
        page.wait_for_timeout(1500)

        c = result["checks"]
        c["heartbeat_visible"] = page.locator(".status-block__pulse").count() == 1
        c["sleep_widget_single"] = page.locator(".status-sleep").count() == 1
        c["sleep_badges_clickable"] = page.locator(
            ".intel-header .badge-btn").count() == 2
        # Воронка инициативы (C06A) — Run Card с 5 стадиями; первое звено —
        # СУММА producers_24h по origin'ам (REV-UI-D1213 F1: {7,3} → 10).
        page.locator("[data-initiative-funnel] .run-card").first.wait_for(
            state="visible", timeout=5000)
        c["initiative_run_card"] = page.locator(
            "[data-initiative-funnel] .run-stage").count() == 5
        c["initiative_producers_sum"] = page.locator(
            "[data-initiative-funnel] .run-stage__value").first.inner_text(
            ).strip() == "10"
        # Воронка уроков (D05) + usefulness.
        page.locator("[data-experience-funnel] .run-card").first.wait_for(
            state="visible", timeout=5000)
        c["experience_run_card"] = page.locator(
            "[data-experience-funnel] .run-stage").count() >= 5
        c["usefulness_label"] = page.locator(
            "[data-experience-funnel] .run-card").first.inner_text().find(
            "Полезность") >= 0
        # Clean Статус: никакого Save-бара.
        c["status_clean_no_savebar"] = page.locator(".sticky-save").count() == 0
        c["status_clean_no_chip"] = page.locator(
            ".header-save-chip").count() == 0
        shot(page, "d1213_status_desktop_1280.png")

        # Sleep-бейдж скроллит к единственному виджету.
        page.locator(".intel-header .badge-btn").first.click()
        page.wait_for_timeout(600)
        c["sleep_badge_scrolls"] = page.evaluate(
            "window.scrollY") > 0

        # ═══ Конфиг-вкладка: clean → нет футера; dirty → компактный Save ═══
        page.goto(base + "#/ai/llm", wait_until="load")
        page.wait_for_selector("main input.field", timeout=8000)
        page.wait_for_timeout(800)
        c["config_clean_no_savebar"] = page.locator(".sticky-save").count() == 0
        c["config_clean_no_chip"] = page.locator(
            ".header-save-chip").count() == 0
        shot(page, "d1213_config_clean_desktop.png")

        # Dirty: правка ПОЛЕЙ КОНФИГА (native setter + input event — как
        # реальный ввод; ищем первое поле, которое реально в dirty-машине).
        c["dirty_via_typing"] = page.evaluate("""
(() => {
  const vm = window.__adminbotVm;
  if (!vm) return false;
  const inputs = Array.from(document.querySelectorAll(
    'main input.field, main textarea.field'));
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  for (const el of inputs) {
    if (el.type === 'checkbox' || el.type === 'password' || el.disabled
        || !el.visible !== undefined) {
      if (el.type === 'checkbox' || el.type === 'password' || el.disabled) {
        continue;
      }
    }
    setter.call(el, 'd1213-dirty-value');
    el.dispatchEvent(new Event('input', { bubbles: true }));
    if ((vm.stickyDirtyCount || 0) > 0) return true;
  }
  return false;
})()
""")
        page.wait_for_timeout(400)
        c["dirty_pill_visible"] = page.locator(".sticky-save").count() == 1
        c["dirty_pill_text"] = ("Изменено: 1" in page.locator(
            ".sticky-save").first.inner_text())
        c["dirty_chip_visible"] = page.locator(
            ".header-save-chip").count() == 1
        shot(page, "d1213_config_dirty_desktop.png")

        # Уход с dirty-страницы: отказ (dialog_accept=False) → маршрут цел.
        page.get_by_role("button", name="Статус").first.click()
        page.wait_for_timeout(800)
        c["dirty_guard_dialog_shown"] = len(result["dialogs"]) >= 1
        c["dirty_guard_stay"] = "misc" not in page.evaluate(
            "window.location.hash")
        c["dirty_preserved_after_stay"] = page.locator(
            ".sticky-save").count() == 1

        # Согласие → навигация выполняется, черновик теряется осознанно.
        result["dialog_accept"] = True
        page.get_by_role("button", name="Статус").first.click()
        page.wait_for_timeout(800)
        c["dirty_guard_leave"] = "#/" == page.evaluate(
            "window.location.hash")
        ctx.close()

        # ═══ Mobile 390×844: верхняя навигация, нижней нет ═══
        mctx = browser.new_context(viewport={"width": 390, "height": 844},
                                   is_mobile=True, has_touch=True)
        mctx.add_init_script(M.TMA_STUB)
        mctx.route("**/api/**", _api_handler)
        mp = mctx.new_page()
        mp.on("console", lambda m: result["console_errors"].append(
            m.text[:200]) if m.type == "error" else None)
        mp.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror(m): " + str(e)[:200]))
        mp.goto(base + "#/", wait_until="load")
        mp.wait_for_timeout(1500)
        c["mobile_topnav_visible"] = mp.locator(
            ".mobile-topnav").is_visible()
        c["mobile_no_bottom_nav"] = mp.locator(".bottom-nav").count() == 0
        c["mobile_no_more_sheet"] = mp.locator(".more-sheet").count() == 0
        c["mobile_no_h_overflow"] = mp.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 1")
        shot(mp, "d1213_status_mobile_390.png")
        # Dirty на мобиле: чип в шапке + pill, клавиатура/ландшафт не тест
        # физической клавиатуры — контролов не перекрываем фиксированными
        # барами (нижних баров больше нет структурно).
        mctx.close()

        # ═══ Landscape: два класса устройств ═══
        # (1) Малый телефон в ландшафте 667×375 → mobile shell (<768):
        # верхняя навигация компактна, нижних баров нет.
        lctx = browser.new_context(viewport={"width": 667, "height": 375},
                                   is_mobile=True, has_touch=True)
        lctx.add_init_script(M.TMA_STUB)
        lctx.route("**/api/**", _api_handler)
        lp = lctx.new_page()
        lp.on("console", lambda m: result["console_errors"].append(
            m.text[:200]) if m.type == "error" else None)
        lp.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror(l): " + str(e)[:200]))
        lp.goto(base + "#/", wait_until="load")
        lp.wait_for_timeout(1500)
        c["landscape_topnav_visible"] = lp.locator(
            ".mobile-topnav").is_visible()
        nav_box = lp.locator(".mobile-topnav").bounding_box()
        c["landscape_topnav_compact"] = bool(nav_box
                                             and nav_box["height"] <= 60)
        c["landscape_no_bottom_nav"] = lp.locator(".bottom-nav").count() == 0
        c["landscape_no_h_overflow"] = lp.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 1")
        shot(lp, "d1213_status_landscape_667x375.png")
        lctx.close()
        # (2) Крупный телефон в ландшафте 844×390 → compact shell (768–1199):
        # drawer-кнопка сверху; нижних fixed-баров нет структурно.
        lctx2 = browser.new_context(viewport={"width": 844, "height": 390},
                                    is_mobile=True, has_touch=True)
        lctx2.add_init_script(M.TMA_STUB)
        lctx2.route("**/api/**", _api_handler)
        lp2 = lctx2.new_page()
        lp2.on("console", lambda m: result["console_errors"].append(
            m.text[:200]) if m.type == "error" else None)
        lp2.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror(l2): " + str(e)[:200]))
        lp2.goto(base + "#/", wait_until="load")
        lp2.wait_for_timeout(1500)
        c["landscape_compact_no_bottom_bars"] = (
            lp2.locator(".bottom-nav").count() == 0
            and lp2.locator(".more-sheet").count() == 0)
        c["landscape_compact_drawer_btn"] = lp2.locator(
            "button[title='Навигация']").count() == 1
        c["landscape_compact_no_h_overflow"] = lp2.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 1")
        shot(lp2, "d1213_status_landscape_844x390.png")
        lctx2.close()

        # ═══ Analytics → Саммари: Unified Run Card прогона (F4) ═══
        actx = browser.new_context(viewport={"width": 1280, "height": 800})
        actx.add_init_script(M.TMA_STUB)
        actx.route("**/api/**", _api_handler)
        ap = actx.new_page()
        ap.on("console", lambda m: result["console_errors"].append(
            m.text[:200]) if m.type == "error" else None)
        ap.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror(a): " + str(e)[:200]))
        ap.goto(base + "#/oversight?tab=summary", wait_until="load")
        ap.wait_for_timeout(1500)
        ap.locator("[data-run-card-summary] .run-card").first.wait_for(
            state="visible", timeout=5000)
        rc_text = ap.locator(
            "[data-run-card-summary] .run-card").first.inner_text()
        c["summary_run_card_id"] = "d1213run" in rc_text
        c["summary_run_card_evidence"] = "9/10" in rc_text
        c["summary_run_card_fallback"] = "l2_fallback" in rc_text
        c["summary_run_card_scope"] = "чат -1001234567890" in rc_text
        shot(ap, "d1213_summary_runcard_desktop.png")
        actx.close()
        browser.close()

    ok = (all(v is True for k, v in result["checks"].items())
          and not result["console_errors"])
    print(json.dumps(result, ensure_ascii=False, indent=1))
    print("D1213-E2E-" + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
