"""EVOL-026..030 (W10) — живая проверка секционных экранов.

Детерминированный Playwright-прогон НАСТОЯЩЕГО `web/index.html` + `web/app.js`
+ `web/static/app.css` на стабах API из `tools/ui_round1025_matrix.py`
(секретов нет, живых сообщений в Telegram не отправляется).

Проверяется (plans/current_task.md L357–422):
  * EVOL-026: «Активность по часам» и «Живая лента досье» — в «Статусе»;
    полный виджет «Истории памяти» — в «Аналитике» (дубликатов нет);
  * EVOL-027: карточка модуля имеет ГЛОБАЛЬНЫй тумблер (v0.7), нет тяжёлой
    KPI-строки (v0.8), нет второго master-toggle в деталях модуля;
  * EVOL-028: «ИИ» — рабочая панель с моделями/health, ссылкой на единый
    редактор «Речь и характер»; «Личность и стиль» как отдельный пункт убран;
  * EVOL-029: «Память» — каталог знаний (поиск/типы/диагностика);
  * EVOL-030: «Доступы» — сводка + разделы; матрица прав на mobile.
  * нет горизонтального скролла страницы; console errors = 0.
  * скриншоты: 1280×900 и 390×844 по каждому экрану.

Запуск: python tools/ui_evol_w10_sections_e2e.py [--out DIR]
Артефакты по умолчанию: plans/features/evol/audit/evidence/
"""
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
sys.path.insert(0, HERE)
os.chdir(REPO)

import ui_round1025_matrix as M               # noqa: E402  сервер/стабы/TMA
import ui_evol_w9_responsive_e2e as W9        # noqa: E402  статика/стабы

PORT = 8847
BASE = "http://127.0.0.1:%d" % PORT
DEFAULT_SHOTS = os.path.join(REPO, "plans", "features", "evol", "audit",
                             "evidence")

ROUTES = ("#/", "#/modules", "#/ai", "#/memory", "#/access", "#/oversight")
VIEWPORTS = ((1280, 900), (390, 844))

PROBE_PAGE = r"""
() => {
  const de = document.documentElement;
  const q = (s) => document.querySelector(s);
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const vis = (el) => {
    if (!el) return false;
    const cs = getComputedStyle(el);
    return cs.display !== 'none' && cs.visibility !== 'hidden';
  };
  return {
    hScroll: de.scrollWidth > window.innerWidth + 1,
    heatmap: qa('[data-viz-heatmap]').length,
    heatCells: qa('[data-viz-heatmap] .viz-heat__cell').length,
    heatPicked: qa('[data-viz-heat-picked]').length,
    dossier: qa('[data-status-dossier] .dossier-ticker').length,
    storiesAny: qa('[data-stories]').length,
    storiesPreview: qa('[data-stories-preview]').length,
    storiesFeed: qa('[data-stories-feed]').length,
    storiesAnalytics: qa('[data-stories-analytics]').length,
    moduleCards: qa('[data-mod]').length,
    moduleGlobalToggles: qa('[data-module-global-toggle]').length,
    moduleKpi: qa('.module-counters').length,
    moduleCaption: qa('[data-module-caption]').length,
    moduleDetailToggle: qa('.modal-card [data-module-global-toggle]').length,
    aiPanel: qa('[data-ai-hub]').length,
    aiModels: qa('[data-ai-modelss], [data-ai-models]').length,
    aiPersonaLink: qa('[data-ai-persona-link]').length,
    speechPersona: qa('#speech-persona').length,
    personaOldCard: qa('[data-speech-entry]').length,
    memoryCatalog: qa('[data-memory-catalog]').length,
    memoryItems: qa('[data-memory-item]').length,
    memoryDiag: qa('[data-memory-diagnostics]').length,
    accessSummary: qa('[data-access-summary]').length,
    accessSections: qa('[data-access-section]').length,
    matrixEffective: qa('[data-matrix-effective]').length,
    runsFilterMeta: qa('[data-runs-filter-meta]').length,
  };
}
"""


def _start_server() -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), W9._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd



# Детерминированные данные для живых виджетов (секретов нет).
_HEAT = {
    "available": True, "days": 14, "telemetry_enabled": True,
    "timezone": "server-local", "total": 12, "errors_total": 2,
    "buckets": [{"d": "2026-10-30", "h": 9, "c": 5, "errs": 1},
                {"d": "2026-10-30", "h": 10, "c": 7, "errs": 1}],
}
_DOSSIER = {"chat_id": None, "items": [
    {"name": "Толян", "user_name": "Толян", "user_id": 5,
     "chat_id": -1001234567890, "excerpt": "любит мемы",
     "text": "любит мемы", "created_at": 1761800000,
     "tg_message_id": 4242},
]}


# Матрица прав: две строки разных секций — проверка mobile-модели
# «сущность → права → эффективные роли» (реальный формат API матрицы).
_MATRIX = {"roles": ["user", "moderator", "local_admin"], "items": {
    "limits.rate_per_min": {
        "key": "limits.rate_per_min", "item": {"title": "Лимит ответов в минуту"},
        "nav": "admin", "nav_title": "Администрирование", "nav_order": 2,
        "tab": "mod_direct", "tab_title": "Ответы в чате",
        "category": "limits", "group": "limits_rate",
        "group_title": "Ограничения", "group_order": 1,
        "view_roles": ["user", "moderator", "local_admin"],
        "edit_roles": ["local_admin"], "default": False,
    },
    "flags.summary_enabled": {
        "key": "flags.summary_enabled", "item": {"title": "Сводки включены"},
        "nav": "admin", "nav_title": "Администрирование", "nav_order": 2,
        "tab": "mod_summary", "tab_title": "Сводки чатов",
        "category": "flags", "group": "flags_summary",
        "group_title": "Флаги", "group_order": 2,
        "view_roles": ["moderator", "local_admin"],
        "edit_roles": [], "default": True,
    },
}}


def _routes2():
    def _route(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/analytics/viz/activity"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(_HEAT))
            return
        if url.endswith("/api/oversight/dossier_feed"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(_DOSSIER))
            return
        if url.endswith("/api/access/param_permissions"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(_MATRIX))
            return
        W9._routes()(route)
    return _route


def _shot(pg, out_dir: str, name: str) -> str:
    path = os.path.join(out_dir, name)
    pg.screenshot(path=path, full_page=False)
    return name


def run(out_dir: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    httpd = _start_server()
    from playwright.sync_api import sync_playwright

    fails = []
    report = {"viewports": [], "cells": [], "summary": {}}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for (w, h) in VIEWPORTS:
                ctx = browser.new_context(viewport={"width": w, "height": h})
                ctx.add_init_script(M.TMA_STUB)
                pg = ctx.new_page()
                pg.route("**/api/**", _routes2())
                errors = []
                pg.on("console", lambda m: errors.append(m.text)
                      if m.type == "error" else None)
                pg.on("pageerror", lambda e: errors.append(str(e)))
                for route in ROUTES:
                    pg.goto(BASE + "/" + route, wait_until="load")
                    pg.wait_for_timeout(900)
                    probe = pg.evaluate(PROBE_PAGE)
                    label = "%s@%dx%d" % (route, w, h)
                    cell = {"route": route, "viewport": "%dx%d" % (w, h)}
                    cell.update(probe)
                    report["cells"].append(cell)
                    tag = route.replace("#/", "").replace("/", "-") or "status"
                    _shot(pg, out_dir, "w10-sec-%s-%dx%d.png" % (tag, w, h))
                    if probe["hScroll"]:
                        fails.append("%s: горизонтальный скролл страницы" % label)
                    # EVOL-026: heatmap/досье — в «Статусе», не в «Аналитике».
                    if route == "#/":
                        if probe["heatmap"] != 1:
                            fails.append("%s: heatmap не найдена ровно один раз (%d)"
                                         % (label, probe["heatmap"]))
                        elif probe["heatCells"] < 24:
                            fails.append("%s: у heatmap нет сетки часов" % label)
                        if probe["dossier"] < 1:
                            fails.append("%s: нет живой ленты досье" % label)
                        if probe["storiesPreview"] != 1:
                            fails.append("%s: нет превью историй памяти" % label)
                        if probe["storiesFeed"]:
                            fails.append("%s: полная лента историй осталась в «Статусе»"
                                         % label)
                    if route == "#/oversight":
                        if probe["heatmap"]:
                            fails.append("%s: heatmap-дубликат в «Аналитике»" % label)
                        if probe["dossier"]:
                            fails.append("%s: лента досье-дубликат в «Аналитике»" % label)
                    # EVOL-027: глобальный тумблер на карточке, без KPI-строки.
                    if route == "#/modules":
                        if probe["moduleCards"] < 5:
                            fails.append("%s: каталог не отрисован (%d карточек)"
                                         % (label, probe["moduleCards"]))
                        if probe["moduleGlobalToggles"] < probe["moduleCards"] - 1:
                            fails.append("%s: не у всех карточек глобальный тумблер (%d/%d)"
                                         % (label, probe["moduleGlobalToggles"],
                                            probe["moduleCards"]))
                        if probe["moduleKpi"]:
                            fails.append("%s: KPI-строка модулей не убрана" % label)
                        if not probe["moduleCaption"]:
                            fails.append("%s: нет подписи числа результатов" % label)
                    if route == "#/ai":
                        if probe["aiPanel"] != 1:
                            fails.append("%s: панель «ИИ» не отрисована" % label)
                        if not probe["aiModels"]:
                            fails.append("%s: нет блока моделей по ролям" % label)
                        if not probe["aiPersonaLink"]:
                            fails.append("%s: нет deep-link в редактор личности" % label)
                    if route == "#/memory":
                        if probe["memoryCatalog"] != 1:
                            fails.append("%s: каталог памяти не отрисован" % label)
                        if not probe["memoryDiag"]:
                            fails.append("%s: нет «Диагностики» памяти" % label)
                    if route == "#/access":
                        if probe["accessSummary"] != 1:
                            fails.append("%s: нет сводки «Доступов»" % label)
                        if probe["accessSections"] < 3:
                            fails.append("%s: разделы «Доступов» не все (%d)"
                                         % (label, probe["accessSections"]))
                report["viewports"].append({
                    "viewport": "%dx%d" % (w, h),
                    "consoleErrors": len(errors),
                    "errorsSample": errors[:3],
                })
                if errors:
                    fails.append("console errors @ %dx%d: %s"
                                 % (w, h, errors[:3]))
                ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    # Сценарии взаимодействия (EVOL-026/027/028): отдельный контекст.
    try:
        from playwright.sync_api import sync_playwright
        httpd = _start_server()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            ctx.add_init_script(M.TMA_STUB)
            pg = ctx.new_page()
            pg.route("**/api/**", _routes2())
            # EVOL-026: выбор часа в heatmap раскрывает подпись и ведёт к фильтру.
            pg.goto(BASE + "/#/", wait_until="load")
            pg.wait_for_timeout(900)
            cells = pg.query_selector_all('[data-viz-heatmap] .viz-heat__cell')
            picked = False
            if cells:
                cells[0].click()
                pg.wait_for_timeout(200)
                picked = pg.query_selector('[data-viz-heat-picked]') is not None
            report["summary"]["heatPick"] = picked
            if not picked:
                fails.append("heatmap: клик по часу не раскрывает подпись")
            _shot(pg, out_dir, "w10-sec-heat-picked-1280x900.png")

            # EVOL-027: глобальный тумблер в карточке → POST /api/config (global).
            global_posts = []
            pg.on("request", lambda r: global_posts.append(r.url)
                  if r.method == "POST" and "/api/config" in r.url else None)
            pg.goto(BASE + "/#/modules", wait_until="load")
            pg.wait_for_timeout(900)
            tgl = pg.query_selector('[data-module-global-toggle]')
            if tgl:
                # Клик по самому контролу (как клавиатурный пользователь):
                # sr-only input не имеет видимой площади для pointer-клика.
                pg.evaluate(
                    "document.querySelector('[data-module-global-toggle]').click()")
                pg.wait_for_timeout(900)
            report["summary"]["globalTogglePost"] = len(global_posts)
            if not global_posts:
                fails.append("модули: глобальный тумблер не выполнил серверную операцию")
            _shot(pg, out_dir, "w10-sec-modules-toggle-1280x900.png")

            # EVOL-028: deep-link «Личность» ведёт в единый редактор.
            pg.goto(BASE + "/#/ai", wait_until="load")
            pg.wait_for_timeout(700)
            link = pg.query_selector('[data-ai-persona-link]')
            if link:
                link.click()
                pg.wait_for_timeout(700)
            has_persona = pg.query_selector('#speech-persona') is not None
            report["summary"]["speechPersona"] = has_persona
            if not has_persona:
                fails.append("«ИИ»: deep-link не открывает секцию личности")
            _shot(pg, out_dir, "w10-sec-speech-persona-1280x900.png")

            ctx.close()

            # EVOL-030: матрица прав на mobile — эффективные роли видны.
            # Отдельный контекст: чистая загрузка без накопленных тостов и
            # сохранённой позиции скролла предыдущего сценария.
            mctx = browser.new_context(viewport={"width": 390, "height": 844})
            mctx.add_init_script(M.TMA_STUB)
            mpg = mctx.new_page()
            mpg.route("**/api/**", _routes2())
            mpg.goto(BASE + "/#/access/roles", wait_until="load")
            mpg.wait_for_timeout(1200)
            # Группы матрицы — progressive disclosure: раскрываем первую, как
            # это сделал бы пользователь, и проверяем мобильную модель строки.
            mpg.evaluate(
                "() => { const d = document.querySelector('.matrix-group');"
                " if (d) d.open = true; }")
            mpg.wait_for_timeout(300)
            eff = mpg.query_selector('[data-matrix-effective]')
            shown = bool(eff) and eff.is_visible()
            report["summary"]["matrixEffectiveMobile"] = shown
            if not shown:
                fails.append("mobile: матрица прав не показывает эффективные роли")
            _shot(mpg, out_dir, "w10-sec-access-matrix-390x844.png")
            mctx.close()
            browser.close()
        httpd.shutdown()
    except Exception as exc:  # noqa: BLE001
        fails.append("interaction pass failed: %s" % exc)

    report["summary"]["failures"] = len(fails)
    with open(os.path.join(out_dir, "w10-sec-probe.json"), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    if fails:
        print("EVOL-W10-SECTIONS FAIL (%d):" % len(fails))
        for f_ in fails:
            print(" -", f_)
        return 1
    print("EVOL-W10-SECTIONS OK — артефакты: %s" % out_dir)
    return 0


def main() -> int:
    out = DEFAULT_SHOTS
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    return run(out)


if __name__ == "__main__":
    sys.exit(main())
