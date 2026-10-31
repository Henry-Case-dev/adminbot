"""EVOL-026..030 (W10) — живая проверка секционных экранов.

Детерминированный Playwright-прогон НАСТОЯЩЕГО `web/index.html` + `web/app.js`
+ `web/static/app.css` на стабах API из `tools/ui_round1025_matrix.py`
(секретов нет, живых сообщений в Telegram не отправляется).

Проверяется (plans/current_task.md L357–422):
  * EVOL-026: «Активность по часам» и «Живая лента досье» — в «Статусе»;
    полный виджет «Истории памяти» — в «Аналитике» (дубликатов нет);
    ячейка часа — настоящая кнопка: стрелки/Enter/Space двигают выбор по
    часам С ДАННЫМИ (реальный прогон, не проверка строки шаблона), уровни
    заливки и легенда различимы, на узком экране ячейка ≥24×24, а
    «Показать события →» открывает «Запуски» с подписью выбранного часа;
  * EVOL-029: карточка памяти показывает НАЗВАНИЕ чата, сырой chat_id —
    только в «Диагностике»;
  * EVOL-030: аудит прав («кто/когда/что и где») виден до изменений.
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
import datetime
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
    // EVOL-026 F2: уровни заливки реально различимы (сетка И легенда).
    heatLevels: [1, 2, 3, 4].map((l) => {
      const el = q('.viz-heat__row .viz-heat__cell--l' + l);
      return el ? getComputedStyle(el).backgroundColor : null;
    }),
    heatLegend: [0, 1, 2, 3, 4].map((l) => {
      const el = q('.viz-heat__legend-cell.viz-heat__cell--l' + l);
      return el ? getComputedStyle(el).backgroundColor : null;
    }),
    heatCellBox: (() => {
      const el = q('.viz-heat__row .viz-heat__cell');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {w: +r.width.toFixed(1), h: +r.height.toFixed(1)};
    })(),
    // F2: образцы легенды крупнее 14 px там, где включена тач-геометрия,
    // и подсказка о прокрутке видна только при реальном h-скролле.
    heatLegendBox: (() => {
      const el = q('.viz-heat__legend-cell');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {w: +r.width.toFixed(1), h: +r.height.toFixed(1)};
    })(),
    heatHintVisible: (() => {
      const el = q('.viz-heat__scroll-hint');
      if (!el) return false;
      const cs = getComputedStyle(el);
      return cs.display !== 'none' && el.getBoundingClientRect().height > 0;
    })(),
    heatScrolls: (() => {
      const el = q('.viz-heat');
      return el ? el.scrollWidth > el.clientWidth + 1 : false;
    })(),
    // EVOL-029 F5: в человеческой карточке — название чата, не сырой id.
    memFactMeta: (() => {
      const el = q('[data-memory-item="facts"] .mem-item__meta')
        || q('[data-memory-item] .mem-item__meta');
      return el ? el.textContent.replace(/\s+/g, ' ').trim() : null;
    })(),
    memDiagRaw: (() => {
      const el = q('[data-memory-diagnostics]');
      return !!el;
    })(),
    // EVOL-030 F4: аудит прав до изменений (сводка и редактор матрицы).
    accessAuditSummary: (() => {
      const el = q('[data-access-audit-summary]');
      return el ? el.textContent.replace(/\s+/g, ' ').trim() : null;
    })(),
    // ═══ ASAP-UI-02 §5.3/§6 (wave 2) ══════════════════════════════════════
    // Порядок «Статуса»: здоровье → карта (место EVOL-COG) → ЕДИНЫЙ виджет
    // четырёх лент → остальные виджеты (сон/превью/бюджеты/…) — ПОСЛЕ лент.
    statusOrder: (() => {
      const label = (el) => {
        const cl = el.classList || {contains() { return false; }};
        if (cl.contains('status-hero')) return 'hero';
        if (cl.contains('status-block')) return 'health';
        if (cl.contains('status-graph')) return 'map';
        if (cl.contains('intel-card')) return 'intel';
        if (cl.contains('status-sleep')) return 'sleep';
        if (cl.contains('exec-preview')) return 'preview';
        if (cl.contains('status-budgets')) return 'budgets';
        if (cl.contains('status-activity')) return 'activity';
        if (cl.contains('status-dossier')) return 'dossier';
        return 'other';
      };
      return qa('.status-grid > *').map(label).filter((x) => x !== 'other');
    })(),
    intelWidgets: qa('[data-intel-widget]').length,
    intelSections: qa('[data-intel-widget] [data-intel-section]')
      .map((el) => el.getAttribute('data-intel-section')),
    intelSwitcher: (() => {
      const el = q('[data-intel-switcher]');
      if (!el) return null;
      const cs = getComputedStyle(el);
      const btns = Array.from(el.querySelectorAll('[data-intel-tab-btn]'));
      const r = el.getBoundingClientRect();
      return {
        visible: cs.display !== 'none' && r.height > 0,
        buttons: btns.length,
        pressed: btns.filter((b) => b.getAttribute('aria-pressed') === 'true')
          .map((b) => b.getAttribute('data-intel-tab-btn')),
        labels: btns.map((b) => b.textContent.replace(/\s+/g, ' ').trim()),
        h: +r.height.toFixed(1),
      };
    })(),
    intelVisibleSections: qa('[data-intel-widget] [data-intel-section]')
      .filter((el) => {
        const cs = getComputedStyle(el);
        return cs.display !== 'none' && el.getBoundingClientRect().height > 0;
      })
      .map((el) => el.getAttribute('data-intel-section')),
    factRows: qa('[data-sfeed-type="fact"]').length,
    factCardLower: (() => {
      // Отдельной нижней карточки «Новые факты» быть не должно: единственный
      // контейнер — секция внутри единого виджета.
      const cards = qa('.card.status-facts');
      return cards.length;
    })(),
  };
}
"""


def _start_server() -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), W9._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd



# Детерминированные данные для живых виджетов (секретов нет).
# Даты считаются от сегодняшнего дня: окно heatmap строится по последним
# N суткам, поэтому «вчера/сегодня» — единственный надёжный способ получить
# заполненные часы (уровни l1..l4 = 1/18/36/70 при максимуме 70).
_TODAY = datetime.date.today()
_D1 = _TODAY.isoformat()
_D0 = (_TODAY - datetime.timedelta(days=1)).isoformat()
_HEAT = {
    "available": True, "days": 14, "telemetry_enabled": True,
    "timezone": "server-local", "total": 125, "errors_total": 2,
    "buckets": [
        {"d": _D0, "h": 9, "c": 1, "errs": 0},
        {"d": _D0, "h": 10, "c": 18, "errs": 1},
        {"d": _D1, "h": 9, "c": 36, "errs": 0},
        {"d": _D1, "h": 10, "c": 70, "errs": 1},
    ],
}
_DOSSIER = {"chat_id": None, "items": [
    {"name": "Толян", "user_name": "Толян", "user_id": 5,
     "chat_id": -1001234567890, "excerpt": "любит мемы",
     "text": "любит мемы", "created_at": 1761800000,
     "tg_message_id": 4242},
    # ASAP-UI-02 §5.3: несколько записей, чтобы секция «Новые факты» реально
    # прокручивалась (проверка сохранения позиции при переключении секций).
    {"name": "Марк", "user_name": "Марк", "user_id": 6,
     "chat_id": -1001234567890, "excerpt": "любит рыбалку",
     "text": "любит рыбалку", "created_at": 1761800100,
     "tg_message_id": 4243},
    {"name": "Аня", "user_name": "Аня", "user_id": 7,
     "chat_id": -1001234567890, "excerpt": "живёт в Казани",
     "text": "живёт в Казани", "created_at": 1761800200,
     "tg_message_id": 4244},
    {"name": "Игорь", "user_name": "Игорь", "user_id": 8,
     "chat_id": -1001234567890, "excerpt": "работает в банке",
     "text": "работает в банке", "created_at": 1761800300,
     "tg_message_id": 4245},
    {"name": "Света", "user_name": "Света", "user_id": 9,
     "chat_id": -1001234567890, "excerpt": "учится на врача",
     "text": "учится на врача", "created_at": 1761800400,
     "tg_message_id": 4246},
    {"name": "Пётр", "user_name": "Пётр", "user_id": 10,
     "chat_id": -1001234567890, "excerpt": "держит собаку",
     "text": "держит собаку", "created_at": 1761800500,
     "tg_message_id": 4247},
    {"name": "Лена", "user_name": "Лена", "user_id": 11,
     "chat_id": -1001234567890, "excerpt": "любит горы",
     "text": "любит горы", "created_at": 1761800600,
     "tg_message_id": 4248},
    {"name": "Костя", "user_name": "Костя", "user_id": 12,
     "chat_id": -1001234567890, "excerpt": "играет в шахматы",
     "text": "играет в шахматы", "created_at": 1761800700,
     "tg_message_id": 4249},
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


def _routes_status(overrides=None):
    """Стабы API, где `/api/status` отдаёт РЕАЛЬНЫЕ сигналы здоровья.

    `overrides` — точечные правки поверх `M.STATUS_STUB` в точечной нотации
    (`"server.cpu_percent"`, `"uptime.generated_at"`, `"bot.state"`,
    `"experience"`). Никакой подстановки `data-health-state` в DOM нет:
    состояние считает тот же код `web/app.js`, что и в проде
    (`heartbeatSample` → `_applyHeartbeatSample` → `heartbeatHealth`).
    """
    data = copy.deepcopy(M.STATUS_STUB)
    for path, value in (overrides or {}).items():
        node = data
        keys = path.split(".")
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

    def _route(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/status"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(data))
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
                        # ═══ ASAP-UI-02 §5.3 (wave 2): порядок «Статуса» ═══
                        # здоровье → карта (место EVOL-COG) → единый виджет
                        # четырёх лент → остальные виджеты.
                        expected_order = ["hero", "health", "map", "intel",
                                          "sleep", "budgets", "activity",
                                          "dossier"]
                        got_order = [x for x in probe.get("statusOrder") or []
                                     if x in expected_order]
                        # `preview` идёт между сном и бюджетами — порядок
                        # проверяем по подпоследовательности.
                        if got_order[:4] != expected_order[:4]:
                            fails.append("%s: порядок «Статуса» нарушен: "
                                         "здоровье→карта→ленты (%s)"
                                         % (label, probe.get("statusOrder")))
                        if "sleep" not in got_order:
                            fails.append("%s: панель сна пропала" % label)
                        elif got_order.index("sleep") < got_order.index("intel"):
                            fails.append("%s: сон оказался ВЫШЕ лент (%s)"
                                         % (label, probe.get("statusOrder")))
                        if probe.get("intelWidgets") != 1:
                            fails.append("%s: единый виджет «Мониторинга» не один "
                                         "(%s)" % (label, probe.get("intelWidgets")))
                        sections = probe.get("intelSections") or []
                        if sections != ["facts", "beliefs", "paradigms", "traits"]:
                            fails.append("%s: секции виджета не те (%s)"
                                         % (label, sections))
                        if probe.get("factCardLower"):
                            fails.append("%s: осталась отдельная нижняя карточка "
                                         "«Новые факты»" % label)
                        sw = probe.get("intelSwitcher") or {}
                        vis_sections = probe.get("intelVisibleSections") or []
                        if w <= 640:
                            if not sw.get("visible"):
                                fails.append("%s: на телефоне нет "
                                             "переключателя секций" % label)
                            if sw.get("buttons") != 4:
                                fails.append("%s: в переключателе %s кнопок"
                                             % (label, sw.get("buttons")))
                            if len(vis_sections) != 1:
                                fails.append("%s: на телефоне видно %s секций "
                                             "(должна одна): %s"
                                             % (label, len(vis_sections),
                                                vis_sections))
                            elif vis_sections[0] != "facts":
                                fails.append("%s: по умолчанию активна не "
                                             "«Факты» (%s)"
                                             % (label, vis_sections))
                            if sw.get("pressed") != ["facts"]:
                                fails.append("%s: переключатель не помечает "
                                             "активную секцию (%s)"
                                             % (label, sw.get("pressed")))
                        else:
                            if sw.get("visible"):
                                fails.append("%s: переключатель секций виден "
                                             "там, где видны все четыре ленты"
                                             % label)
                            if len(vis_sections) != 4:
                                fails.append("%s: на широком экране видно %s "
                                             "секций из 4: %s"
                                             % (label, len(vis_sections),
                                                vis_sections))
                        # heatmap
                        if probe["heatmap"] != 1:
                            fails.append("%s: heatmap не найдена ровно один раз (%d)"
                                         % (label, probe["heatmap"]))
                        elif probe["heatCells"] < 24:
                            fails.append("%s: у heatmap нет сетки часов" % label)
                        # F2: четыре уровня данных дают ЧЕТЫРЕ разных цвета,
                        # легенда показывает те же цвета (сетка и легенда).
                        levels = probe["heatLevels"]
                        legend = probe["heatLegend"]
                        if any(not c for c in levels):
                            fails.append("%s: в heatmap нет уровней l1..l4 "
                                         "(данные/классы): %s" % (label, levels))
                        elif len(set(levels)) != 4:
                            fails.append("%s: уровни heatmap одного цвета — "
                                         "заливка не видна: %s" % (label, levels))
                        if any(not c for c in legend):
                            fails.append("%s: легенда heatmap без образцов"
                                         % label)
                        elif legend[1:] != levels:
                            fails.append("%s: легенда heatmap не совпадает с "
                                         "сеткой: %s vs %s"
                                         % (label, legend[1:], levels))
                        elif len(set(legend)) < 5:
                            fails.append("%s: образцы легенды неразличимы: %s"
                                         % (label, legend))
                        box = probe["heatCellBox"] or {}
                        if w <= 430 and (box.get("w", 0) < 24
                                         or box.get("h", 0) < 24):
                            fails.append("%s: ячейка heatmap %s×%s < 24×24 "
                                         "(тач-минимум)" % (label, box.get("w"),
                                                            box.get("h")))
                        # F2: образцы легенды читаемы (16 px там, где включена
                        # тач-геометрия) и подсказка о прокрутке показывается
                        # ТОЛЬКО когда сетка реально шире окна.
                        lb = probe["heatLegendBox"] or {}
                        if w <= 430 and lb.get("w", 0) < 16:
                            fails.append("%s: образец легенды %s×%s < 16×16"
                                         % (label, lb.get("w"), lb.get("h")))
                        if probe["heatHintVisible"] != probe["heatScrolls"]:
                            fails.append("%s: подсказка прокрутки не совпадает с "
                                         "реальной прокруткой (hint=%s scroll=%s)"
                                         % (label, probe["heatHintVisible"],
                                            probe["heatScrolls"]))
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
                        # F5: человеческая карточка показывает НАЗВАНИЕ чата,
                        # сырой chat_id остаётся только в «Диагностике».
                        meta = probe["memFactMeta"] or ""
                        if "чат: Audit Chat" not in meta:
                            fails.append("%s: карточка памяти без названия чата "
                                         "(%s)" % (label, meta[:90]))
                        if "-1001234567890" in meta:
                            fails.append("%s: в карточке памяти сырой chat_id "
                                         "(%s)" % (label, meta[:90]))
                    if route == "#/access":
                        if probe["accessSummary"] != 1:
                            fails.append("%s: нет сводки «Доступов»" % label)
                        if probe["accessSections"] < 3:
                            fails.append("%s: разделы «Доступов» не все (%d)"
                                         % (label, probe["accessSections"]))
                        # F4: аудит прав виден ДО изменений (кто/область).
                        summ = probe["accessAuditSummary"] or ""
                        if "Права меняет" not in summ:
                            fails.append("%s: нет строки аудита прав в сводке "
                                         "(%s)" % (label, summ[:90]))
                        if "Audit" not in summ and "audit" not in summ:
                            fails.append("%s: строка аудита без реального "
                                         "пользователя (%s)" % (label, summ[:90]))
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
            pageerrors = []
            pg.on("pageerror", lambda e: pageerrors.append(str(e)[:200]))
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

            # ═══ F1 (review EVOL-026): клавиатура heatmap — РЕАЛЬНОЕ поведение.
            # Раньше проверялось лишь наличие строки `vizHeatStep` в шаблоне,
            # хотя самой функции не существовало (TypeError в Chromium).
            kbd_errors_before = len(pageerrors)
            pg.goto(BASE + "/#/", wait_until="load")
            pg.wait_for_timeout(900)
            keys = []
            start = '[data-viz-cell="%s:9"]' % _D1
            pg.focus(start)
            pg.wait_for_timeout(150)
            for keyname in ("ArrowRight", "ArrowRight", "ArrowDown", "ArrowUp"):
                pg.keyboard.press(keyname)
                pg.wait_for_timeout(200)
                keys.append(pg.evaluate(r"""() => {
                    const a = document.activeElement;
                    const pickedEl = document.querySelector(
                      '.viz-heat__row .viz-heat__cell.is-picked');
                    return {
                      cell: a && a.getAttribute ? a.getAttribute('data-viz-cell') : null,
                      pressed: a && a.getAttribute
                        ? a.getAttribute('aria-pressed') : null,
                      label: a && a.getAttribute
                        ? a.getAttribute('aria-label') : null,
                      picked: !!document.querySelector('[data-viz-heat-picked]'),
                      // F2: выбранная клетка реально помечена классом (одна
                      // привязка class — два `:class` затирали это состояние).
                      pickedClass: !!pickedEl
                        && pickedEl === a,
                      levelClass: a && a.className
                        ? /viz-heat__cell--l[0-4]/.test(a.className) : false,
                    };
                }"""))
            kbd = {"steps": keys,
                   "errors": pageerrors[kbd_errors_before:]}
            report["summary"]["heatKeyboard"] = kbd
            # Вправо: 09:00 → 10:00 (следующий час с данными), затем по кругу
            # 10:00 → 09:00; вниз за последний день окна — кламп (стоим),
            # вверх — предыдущий день, тот же час.
            expect = ["%s:10" % _D1, "%s:9" % _D1, "%s:9" % _D1,
                      "%s:9" % _D0]
            got = [s.get("cell") for s in keys]
            if got != expect:
                fails.append("heatmap: стрелки не ходят по часам с данными "
                             "(%s != %s)" % (got, expect))
            for st in keys:
                if st.get("pressed") != "true":
                    fails.append("heatmap: aria-pressed не обновлён после "
                                 "стрелки (%s)" % st)
                    break
                if not st.get("picked"):
                    fails.append("heatmap: подпись выбранного часа не появилась "
                                 "после стрелки")
                    break
                if not st.get("label"):
                    fails.append("heatmap: aria-label не обновлён (%s)" % st)
                    break
                if not st.get("levelClass"):
                    fails.append("heatmap: у выбранной клетки пропал класс "
                                 "уровня заливки (%s)" % st)
                    break
                if not st.get("pickedClass"):
                    fails.append("heatmap: выбранная клетка без класса "
                                 "is-picked — состояние не видно (%s)" % st)
                    break
                parts = (st.get("cell") or "").split(":")
                hh = ("0" + parts[1]) if parts[1:2] and int(parts[1]) < 10 \
                    else (parts[1] if parts[1:2] else "")
                if parts[0] not in st["label"] or (hh + ":00") not in st["label"]:
                    fails.append("heatmap: aria-label не соответствует "
                                 "выбранной ячейке (%s vs %s)"
                                 % (st.get("cell"), st.get("label")))
                    break
            if kbd["errors"]:
                fails.append("heatmap: ошибка JS при клавиатуре: %s"
                             % kbd["errors"][:2])
            # Enter/Space выбирают час так же, как клик.
            pg.focus('[data-viz-cell="%s:10"]' % _D1)
            pg.wait_for_timeout(120)
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(220)
            enter_ok = pg.evaluate(
                "() => !!document.querySelector('[data-viz-heat-picked]')")

            # ═══ F3 (review EVOL-026): «Показать события →» сохраняет час ═══
            # Кнопка живёт в подписи выбранного часа; переход обязан открыть
            # суб-вкладку «Запуски» (там подпись часа), а не «Обзор».
            pg.click("text=Показать события")
            pg.wait_for_timeout(1200)
            nav = pg.evaluate(r"""() => {
                const vm = window.__adminbotVm;
                const meta = document.querySelector('[data-runs-filter-meta]');
                const tab = document.querySelector('.oversight-tab.is-active');
                return {
                  route: location.hash,
                  tab: vm ? vm.oversightTab : null,
                  view: vm ? vm.oversightView : null,
                  activeTabText: tab ? tab.textContent.trim() : null,
                  meta: meta
                    ? meta.textContent.replace(/\s+/g, ' ').trim() : null,
                };
            }""")
            report["summary"]["eventsLink"] = nav
            if not enter_ok:
                fails.append("heatmap: Enter не выбирает час")
            if nav.get("tab") != "runs":
                fails.append("heatmap: «Показать события» не открыл «Запуски» "
                             "(tab=%s)" % nav.get("tab"))
            if not (nav.get("activeTabText") or "").startswith("Запуски"):
                fails.append("heatmap: активная вкладка не «Запуски» (%s)"
                             % nav.get("activeTabText"))
            if not nav.get("meta") or "Выбранный час" not in nav["meta"]:
                fails.append("heatmap: подпись выбранного часа не показана в "
                             "«Запусках» (%s)" % nav.get("meta"))
            _shot(pg, out_dir, "w10-sec-heat-events-1280x900.png")

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

            # ═══ EVOL-029 (review-fix2): карточка «Памяти» открывает ОКНО ЗАПИСИ.
            # Раньше окно жило в ветке «Статуса»: на `#/memory` клик ставил
            # только `sfeed-modal-open` (прокрутка заблокирована) — окна не
            # было. Проверяем реальный DOM: окно видно, в нём поля,
            # первоисточники и сырые id («Технические поля»), Esc снимает и
            # окно, и блокировку прокрутки; «Статус» открывает то же окно.
            # Отдельный контекст: после сценария «ИИ» остаётся черновик
            # личности, и штатная защита ухода со страницы отменяет навигацию
            # (проверка окна не должна зависеть от чужого состояния формы).
            rctx = browser.new_context(viewport={"width": 1280, "height": 900})
            rctx.add_init_script(M.TMA_STUB)
            pg = rctx.new_page()
            pg.route("**/api/**", _routes2())
            rec_errors = []
            pg.on("pageerror", lambda e: rec_errors.append(str(e)[:200]))
            pg.on("console", lambda m: rec_errors.append("console: " + m.text[:200])
                  if m.type == "error" else None)
            pg.goto(BASE + "/#/memory", wait_until="load")
            pg.wait_for_timeout(1000)
            mem_modal = {}
            mem_card = pg.query_selector('[data-memory-item="facts"]') \
                or pg.query_selector('[data-memory-item]')
            report["summary"]["memoryCardFound"] = bool(mem_card)
            if not mem_card:
                fails.append("«Память»: нет карточки каталога для проверки окна")
            else:
                mem_card.click()
                pg.wait_for_timeout(400)
                mem_modal = pg.evaluate(r"""() => {
                    const m = document.querySelector('[data-sfeed-modal]');
                    if (!m) return {present: false};
                    const cs = getComputedStyle(m);
                    const r = m.getBoundingClientRect();
                    const labels = Array.from(m.querySelectorAll('[data-rec-field]'))
                      .map((e) => {
                        const l = e.querySelector('.rec-label');
                        return l ? l.textContent.trim() : '';
                      });
                    return {
                      present: true,
                      visible: cs.display !== 'none' && cs.visibility !== 'hidden'
                        && r.width > 0 && r.height > 0,
                      count: document.querySelectorAll('[data-sfeed-modal]').length,
                      fields: labels,
                      sources: !!m.querySelector('[data-rec-section="sources"]'),
                      tech: !!m.querySelector('[data-rec-tech]'),
                      locked: !!document.querySelector('.app-shell.sfeed-modal-open'),
                    };
                }""")
                _shot(pg, out_dir, "w10-sec-memory-record-modal-1280x900.png")
                if not mem_modal.get("visible"):
                    fails.append("«Память»: клик по карточке не показывает окно "
                                 "записи (%s)" % mem_modal)
                if mem_modal.get("count", 0) > 1:
                    fails.append("«Память»: окон записи больше одного (%d)"
                                 % mem_modal["count"])
                need = ("Полный текст", "Тип записи", "Чат / область", "Субъект",
                        "Источники")
                missing = [n for n in need
                           if not any(n in f for f in mem_modal.get("fields") or [])]
                if missing:
                    fails.append("«Память»: в окне нет полей %s (%s)"
                                 % (missing, mem_modal.get("fields")))
                if not mem_modal.get("sources"):
                    fails.append("«Память»: в окне нет раздела «Первоисточники»")
                if not mem_modal.get("tech"):
                    fails.append("«Память»: в окне нет «Технических полей»")
                if not mem_modal.get("locked"):
                    fails.append("«Память»: окно открыто, а фон не заблокирован")
                # «Технические поля» раскрываются и показывают сырой chat_id.
                tech_rows = pg.evaluate(r"""() => {
                    const d = document.querySelector('[data-rec-tech]');
                    if (!d) return null;
                    d.open = true;
                    d.scrollIntoView({block: 'center'});
                    return Array.from(d.querySelectorAll('[data-rec-field]'))
                      .map((r) => r.textContent.replace(/\s+/g, ' ').trim());
                }""")
                pg.wait_for_timeout(250)
                report["summary"]["memoryModalTech"] = tech_rows
                if not tech_rows:
                    fails.append("«Память»: «Технические поля» пусты")
                elif not any("-1001234567890" in r for r in tech_rows):
                    fails.append("«Память»: в «Технических полях» нет сырого "
                                 "chat_id (%s)" % tech_rows)
                _shot(pg, out_dir, "w10-sec-memory-record-tech-1280x900.png")
                # Esc закрывает окно И снимает блокировку прокрутки.
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(350)
                closed = pg.evaluate(r"""() => ({
                    modal: !!document.querySelector('[data-sfeed-modal]'),
                    locked: !!document.querySelector('.app-shell.sfeed-modal-open'),
                    canScroll: (() => {
                      const m = document.querySelector('main.scroll-area');
                      return m ? getComputedStyle(m).overflowY : null;
                    })(),
                })""")
                report["summary"]["memoryModalClosed"] = closed
                if closed.get("modal"):
                    fails.append("«Память»: Esc не закрыл окно записи")
                if closed.get("locked"):
                    fails.append("«Память»: после Esc осталась блокировка "
                                 "прокрутки (sfeed-modal-open)")
                if closed.get("canScroll") == "hidden":
                    fails.append("«Память»: после Esc прокрутка фона всё ещё "
                                 "заблокирована (overflow-y: hidden)")

            # «Статус» по-прежнему открывает ТО ЖЕ окно (регрессия не внесена).
            pg.goto(BASE + "/#/", wait_until="load")
            pg.wait_for_timeout(1000)
            row = pg.query_selector('[data-sfeed-row][data-sfeed-type="fact"]')
            status_modal = {"present": False}
            if not row:
                fails.append("«Статус»: нет строки «Новых фактов» для проверки окна")
            else:
                row.click()
                pg.wait_for_timeout(400)
                status_modal = pg.evaluate(r"""() => {
                    const m = document.querySelector('[data-sfeed-modal]');
                    if (!m) return {present: false};
                    const r = m.getBoundingClientRect();
                    return {
                      present: true,
                      visible: r.width > 0 && r.height > 0,
                      count: document.querySelectorAll('[data-sfeed-modal]').length,
                      locked: !!document.querySelector('.app-shell.sfeed-modal-open'),
                    };
                }""")
                # Клик ВНЕ окна тоже закрывает и снимает блокировку.
                pg.mouse.click(4, 4)
                pg.wait_for_timeout(350)
                status_after = pg.evaluate(r"""() => ({
                    modal: !!document.querySelector('[data-sfeed-modal]'),
                    locked: !!document.querySelector('.app-shell.sfeed-modal-open'),
                })""")
                report["summary"]["statusModalAfterOutsideClick"] = status_after
                if status_after.get("modal") or status_after.get("locked"):
                    fails.append("«Статус»: клик вне окна не закрыл его/не снял "
                                 "блокировку (%s)" % status_after)
            report["summary"]["statusModal"] = status_modal
            if not status_modal.get("visible"):
                fails.append("«Статус»: строка «Новых фактов» не открывает окно (%s)"
                             % status_modal)
            if status_modal.get("count", 0) > 1:
                fails.append("«Статус»: окон записи больше одного (%d)"
                             % status_modal["count"])
            if not status_modal.get("locked"):
                fails.append("«Статус»: окно открыто, а фон не заблокирован")
            report["summary"]["recordModalErrors"] = rec_errors[:4]
            if rec_errors:
                fails.append("окно записи: ошибки JS/консоли: %s" % rec_errors[:3])

            rctx.close()

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
            # F4 (review EVOL-030): аудит «кто/когда/что» — в редакторе матрицы,
            # до изменения прав; значения реальные (профиль + отметка сессии).
            audit = mpg.evaluate(r"""() => {
                const el = document.querySelector('[data-access-audit]');
                return el ? el.textContent.replace(/\s+/g, ' ').trim() : null;
            }""")
            report["summary"]["matrixAudit"] = audit
            if not audit:
                fails.append("доступы: нет строки аудита в редакторе матрицы")
            else:
                for marker in ("Кто меняет", "Когда", "Что и где",
                               "5885953495"):
                    if marker not in audit:
                        fails.append("доступы: в аудите нет %r (%s)"
                                     % (marker, audit[:120]))
                        break
                if "правки не сохранялись" not in audit:
                    fails.append("доступы: аудит без честной отметки времени "
                                 "(%s)" % audit[:120])
            _shot(mpg, out_dir, "w10-sec-access-matrix-390x844.png")

            # EVOL-029 (review-fix2) mobile: то же окно записи — нижним листом
            # (существующее поведение модалок на узком экране не сломано
            # переносом разметки на уровень `#app`).
            mpg.goto(BASE + "/#/memory", wait_until="load")
            mpg.wait_for_timeout(900)
            mcard = mpg.query_selector('[data-memory-item="facts"]') \
                or mpg.query_selector('[data-memory-item]')
            sheet = {"present": False}
            if mcard:
                mcard.click()
                mpg.wait_for_timeout(400)
                sheet = mpg.evaluate(r"""() => {
                    const m = document.querySelector('[data-sfeed-modal]');
                    if (!m) return {present: false};
                    const r = m.getBoundingClientRect();
                    const cs = getComputedStyle(m);
                    return {
                      present: true,
                      w: +r.width.toFixed(1),
                      h: +r.height.toFixed(1),
                      bottom: +r.bottom.toFixed(1),
                      radius: cs.borderTopLeftRadius,
                      vw: window.innerWidth, vh: window.innerHeight,
                      locked: !!document.querySelector('.app-shell.sfeed-modal-open'),
                      hScroll: document.documentElement.scrollWidth
                        > window.innerWidth + 1,
                    };
                }""")
            else:
                fails.append("mobile «Память»: нет карточки для проверки окна")
            report["summary"]["memoryModalMobile"] = sheet
            if not sheet.get("present"):
                fails.append("mobile «Память»: окно записи не открылось")
            else:
                if sheet["w"] < sheet["vw"] - 4:
                    fails.append("mobile «Память»: окно не во всю ширину (%s из %s)"
                                 % (sheet["w"], sheet["vw"]))
                if sheet["bottom"] < sheet["vh"] - 6:
                    fails.append("mobile «Память»: окно не прижато к низу — "
                                 "это не нижний лист (bottom=%s, vh=%s)"
                                 % (sheet["bottom"], sheet["vh"]))
                if not sheet["radius"].startswith("18px"):
                    fails.append("mobile «Память»: у листа нет верхнего "
                                 "скругления (%s)" % sheet["radius"])
                if sheet["hScroll"]:
                    fails.append("mobile «Память»: с окном появился "
                                 "горизонтальный скролл")
                if not sheet["locked"]:
                    fails.append("mobile «Память»: окно открыто без блокировки фона")
            _shot(mpg, out_dir, "w10-sec-memory-record-390x844.png")
            mctx.close()

            # ═══ ASAP-UI-02 §5.3 (wave 2): телефон — одна секция + переключатель.
            # Данные не перезапрашиваются, позиция прокрутки секции сохраняется.
            sctx = browser.new_context(viewport={"width": 390, "height": 844})
            sctx.add_init_script(M.TMA_STUB)
            spg = sctx.new_page()
            spg.route("**/api/**", _routes2())
            serrors = []
            spg.on("pageerror", lambda e: serrors.append(str(e)[:200]))
            spg.on("console", lambda m: serrors.append("console: " + m.text[:200])
                  if m.type == "error" else None)
            spg.goto(BASE + "/#/", wait_until="load")
            spg.wait_for_timeout(1200)
            switch_before = spg.evaluate(r"""() => {
                const vis = () => Array.from(
                  document.querySelectorAll('[data-intel-section]'))
                  .filter((el) => getComputedStyle(el).display !== 'none')
                  .map((el) => el.getAttribute('data-intel-section'));
                const vp = document.querySelector('[data-ribbon="facts"]');
                let scrolled = null;
                if (vp) { vp.scrollTop = 40; scrolled = vp.scrollTop; }
                const btn = document.querySelector('[data-intel-tab-btn="beliefs"]');
                if (btn) btn.click();
                return {
                  vis: vis(),
                  rows: document.querySelectorAll('[data-sfeed-type="fact"]').length,
                  scrolled: scrolled,
                  switchable: !!btn,
                };
            }""")
            spg.wait_for_timeout(600)
            switch_after = spg.evaluate(r"""() => {
                const vis = Array.from(document.querySelectorAll('[data-intel-section]'))
                  .filter((el) => getComputedStyle(el).display !== 'none')
                  .map((el) => el.getAttribute('data-intel-section'));
                const pressed = Array.from(
                  document.querySelectorAll('[data-intel-tab-btn]'))
                  .filter((b) => b.getAttribute('aria-pressed') === 'true')
                  .map((b) => b.getAttribute('data-intel-tab-btn'));
                const factsBtn = document.querySelector('[data-intel-tab-btn="facts"]');
                if (factsBtn) factsBtn.click();
                return {vis: vis, pressed: pressed,
                        rows: document.querySelectorAll('[data-sfeed-type="fact"]').length};
            }""")
            spg.wait_for_timeout(600)
            switch_back = spg.evaluate(r"""() => {
                const vis = Array.from(document.querySelectorAll('[data-intel-section]'))
                  .filter((el) => getComputedStyle(el).display !== 'none')
                  .map((el) => el.getAttribute('data-intel-section'));
                const vp = document.querySelector('[data-ribbon="facts"]');
                const pressed = Array.from(
                  document.querySelectorAll('[data-intel-tab-btn]'))
                  .filter((b) => b.getAttribute('aria-pressed') === 'true')
                  .map((b) => b.getAttribute('data-intel-tab-btn'));
                return {vis: vis, pressed: pressed,
                        scroll: vp ? vp.scrollTop : null,
                        rows: document.querySelectorAll('[data-sfeed-type="fact"]').length};
            }""")
            _shot(spg, out_dir, "w10-sec-intel-switch-390x844.png")
            report["summary"]["intelSwitch"] = {
                "before": switch_before, "after": switch_after,
                "back": switch_back, "errors": serrors[:3],
            }
            if not switch_before.get("switchable"):
                fails.append("телефон: нет кнопки переключения секций «Убеждения»")
            if switch_before.get("vis") != ["facts"]:
                fails.append("телефон: по умолчанию видно не только «Факты» (%s)"
                             % switch_before.get("vis"))
            if switch_before.get("rows", 0) < 5:
                fails.append("телефон: «Новые факты» без записей (%s)"
                             % switch_before.get("rows"))
            if switch_before.get("scrolled") != 40:
                fails.append("телефон: секция «Факты» не прокручивается вручную "
                             "(scrollTop=%s)" % switch_before.get("scrolled"))
            if switch_after.get("vis") != ["beliefs"]:
                fails.append("телефон: после переключения видна не одна секция "
                             "(«Убеждения»): %s" % switch_after.get("vis"))
            if switch_after.get("pressed") != ["beliefs"]:
                fails.append("телефон: переключатель не помечает «Убеждения» (%s)"
                             % switch_after.get("pressed"))
            if switch_after.get("rows") != switch_before.get("rows"):
                fails.append("телефон: при переключении потерялись данные фактов "
                             "(%s → %s)" % (switch_before.get("rows"),
                                            switch_after.get("rows")))
            if switch_back.get("vis") != ["facts"]:
                fails.append("телефон: возврат на «Факты» не работает (%s)"
                             % switch_back.get("vis"))
            back_scroll = switch_back.get("scroll")
            if back_scroll is None or abs(back_scroll - 40) > 8:
                fails.append("телефон: позиция прокрутки секции не сохранилась "
                             "(было 40, стало %s)" % back_scroll)
            if switch_back.get("rows") != switch_before.get("rows"):
                fails.append("телефон: данные фактов изменились после возврата "
                             "(%s → %s)" % (switch_before.get("rows"),
                                            switch_back.get("rows")))
            if serrors:
                fails.append("телефон (§5.3): ошибки JS: %s" % serrors[:3])
            sctx.close()

            # ═══ ASAP-UI-02 §6 (wave 2, review-fix2): тонирование проверяется
            # НА РЕАЛЬНОМ СИГНАЛЕ. Ручная подстановка `data-health-state` в DOM
            # убрана: она доказывала лишь существование токенов, но НЕ то, что
            # состояние достижимо из телеметрии (замечание ревью B1).
            # Стенд отдаёт настоящий /api/status, а состояние считает тот же
            # код `web/app.js`, что в проде:
            #   `server.cpu_percent` + свежий `uptime.generated_at`
            #     → heartbeatSample → _applyHeartbeatSample → hbState='warning'
            #     → `heartbeatHealth` → заливка секции «Сердцебиение»;
            #   `bot.state='polling_error'` → 'failed' (секция + hero);
            #   `experience.state='degraded'` → 'degraded' (другая поверхность
            #     того же единственного механизма).
            def _now_iso():
                return datetime.datetime.now(datetime.timezone.utc).isoformat()

            tint_cases = (
                # имя, viewport, touch-эмуляция, правки /api/status
                ("warning", (1280, 900), False,
                 {"uptime.generated_at": _now_iso(), "server.cpu_percent": 75.0}),
                ("neutral", (1280, 900), False, {}),
                ("failed", (1280, 900), False,
                 {"uptime.generated_at": _now_iso(),
                  "bot.state": "polling_error"}),
                ("degraded", (1280, 900), False,
                 {"experience": {"state": "degraded"}}),
                ("warning390", (390, 844), True,
                 {"uptime.generated_at": _now_iso(), "server.cpu_percent": 75.0}),
                ("plain390", (390, 844), False, {}),
            )
            PROBE_TINT = r"""() => {
                const q = (s) => document.querySelector(s);
                const cs = (el) => el ? getComputedStyle(el) : null;
                const bg = (el) => (el ? cs(el).backgroundColor : null);
                const count = (c) => Array.from(
                  document.querySelectorAll('body *'))
                  .filter((el) => cs(el).backgroundColor === c).length;
                const box = (el) => {
                  if (!el) return null;
                  const r = el.getBoundingClientRect();
                  return {x: +r.x.toFixed(1), w: +r.width.toFixed(1),
                          h: +r.height.toFixed(1)};
                };
                const backdrop = (el) => {
                  if (!el) return '';
                  const v = cs(el).backdropFilter
                    || cs(el).webkitBackdropFilter || '';
                  return v === 'none' ? '' : v;
                };
                const hb = q('[data-health-subsystem="heartbeat"]');
                const hero = q('[data-health-subsystem="bot"]');
                const block = q('.status-block');
                const exp = q('[data-health-subsystem="experience"]');
                const inline = q('[data-health-inline="heartbeat"]');
                const pulse = q('.status-block__pulse');
                const titleRow = hb ? hb.firstElementChild : null;
                const tabs = Array.from(document.querySelectorAll(
                  '[data-intel-switcher] .intel-tabs__btn'));
                const label = inline
                  ? inline.querySelector('.health-status-line__label') : null;
                const reason = inline
                  ? inline.querySelector('.health-status-line__reason') : null;
                const switcher = q('[data-intel-switcher]');
                return {
                  hbState: hb ? hb.getAttribute('data-health-state') : null,
                  hbMaterial: hb ? hb.getAttribute('data-health-material') : null,
                  hbBg: bg(hb),
                  hbRadius: hb ? cs(hb).borderRadius : null,
                  hbBackdrop: backdrop(hb),
                  hbOwnStatusLine: hb
                    ? hb.querySelectorAll('.health-glass-status').length : null,
                  inlineState: inline
                    ? inline.getAttribute('data-health-indicator') : null,
                  inlineLabel: label ? (label.textContent || '').trim() : '',
                  inlineReason: reason ? (reason.textContent || '').trim() : '',
                  heroState: hero ? hero.getAttribute('data-health-state') : null,
                  heroBg: bg(hero),
                  heroRadius: hero ? cs(hero).borderRadius : null,
                  heroBackdrop: backdrop(hero),
                  blockBg: bg(block),
                  blockRadius: block ? cs(block).borderRadius : null,
                  blockMaterial: block
                    ? block.getAttribute('data-health-material') : null,
                  expState: exp ? exp.getAttribute('data-health-state') : null,
                  expBg: bg(exp),
                  counts: {
                    warning: count('rgba(60, 43, 56, 0.5)'),
                    degraded: count('rgba(91, 55, 67, 0.5)'),
                    failed: count('rgba(141, 74, 85, 0.5)'),
                  },
                  pulseBox: box(pulse),
                  hbBox: box(hb),
                  contentInset: (titleRow && block)
                    ? +(titleRow.getBoundingClientRect().x
                        - block.getBoundingClientRect().x).toFixed(1) : null,
                  tabsDisplay: switcher ? cs(switcher).display : null,
                  tabs: tabs.map((el) => {
                    const r = el.getBoundingClientRect();
                    return {w: +r.width.toFixed(1), h: +r.height.toFixed(1)};
                  }),
                };
            }"""

            tint = {}
            for name, (vw, vh), has_touch, overrides in tint_cases:
                tctx = browser.new_context(
                    viewport={"width": vw, "height": vh}, has_touch=has_touch)
                tctx.add_init_script(M.TMA_STUB)
                tpg = tctx.new_page()
                tpg.route("**/api/**", _routes_status(overrides))
                perrors = []
                tpg.on("pageerror", lambda e: perrors.append(str(e)[:200]))
                tpg.on("console", lambda m: perrors.append("console: " + m.text[:200])
                       if m.type == "error" else None)
                tpg.goto(BASE + "/#/", wait_until="load")
                tpg.wait_for_timeout(1200)
                got = tpg.evaluate(PROBE_TINT) or {}
                got["vp"] = [vw, vh]
                got["touch"] = has_touch
                got["errors"] = perrors[:3]
                tint[name] = got
                if name == "warning":
                    _shot(tpg, out_dir, "w10-sec-health-tint-1280x900.png")
                if name == "warning390":
                    _shot(tpg, out_dir, "w10-sec-health-tint-390x844.png")
                tctx.close()

            report["summary"]["healthTint"] = tint

            WARN_BG = "rgba(60, 43, 56, 0.5)"
            DEGRADED_BG = "rgba(91, 55, 67, 0.5)"
            FAILED_BG = "rgba(141, 74, 85, 0.5)"
            NEUTRAL_BG = "rgba(21, 27, 42, 0.5)"

            def _rgb(v):
                nums = [int(x) for x in
                        __import__("re").findall(r"\d+", str(v or ""))][:3]
                return nums if len(nums) == 3 else None

            def _alpha(v):
                nums = __import__("re").findall(r"[\d.]+", str(v or ""))
                return float(nums[3]) if len(nums) >= 4 else None

            def _case(name):
                data = tint.get(name) or {}
                if data.get("errors"):
                    fails.append("health tint %s: ошибки JS: %s"
                                 % (name, data["errors"]))
                return data

            warn = _case("warning")
            neutral = _case("neutral")
            failed = _case("failed")
            degrad = _case("degraded")
            w390 = _case("warning390")
            plain390 = _case("plain390")

            # 1) Реальный сигнал нагрузки → warning НА СЕКЦИИ «Сердцебиение».
            if warn.get("hbState") != "warning":
                fails.append("health tint: реальный сигнал cpu 75%% не даёт "
                             "warning на секции (state=%s, строка=%s)"
                             % (warn.get("hbState"), warn.get("inlineState")))
            if warn.get("hbState") != warn.get("inlineState"):
                fails.append("health tint: поверхность и строка состояния "
                             "разошлись (%s vs %s)"
                             % (warn.get("hbState"), warn.get("inlineState")))
            if warn.get("hbBg") != WARN_BG:
                fails.append("health tint: warning не окрашивает секцию (%s)"
                             % (warn.get("hbBg"),))
            if (warn.get("counts") or {}).get("warning") != 1:
                fails.append("health tint: warning-заливка не на ОДНОЙ "
                             "поверхности (%s)" % (warn.get("counts"),))
            if "повышенная нагрузка" not in (warn.get("inlineReason") or ""):
                fails.append("health tint: причина не совпадает с сигналом (%s)"
                             % (warn.get("inlineReason"),))
            if warn.get("hbOwnStatusLine") != 0:
                fails.append("health tint: у секции дублируется собственный "
                             "инлайн-статус компонента (%s)"
                             % (warn.get("hbOwnStatusLine"),))
            if warn.get("hbBackdrop"):
                fails.append("health tint: у секции появился второй blur (%s)"
                             % (warn.get("hbBackdrop"),))
            if not warn.get("heroBackdrop"):
                fails.append("health tint: у hero пропал существующий blur")
            # Соседние поверхности остаются нейтральными (EVOL-032).
            if warn.get("heroBg") != NEUTRAL_BG:
                fails.append("health tint: hero перекрашен чужим сигналом (%s)"
                             % (warn.get("heroBg"),))
            if warn.get("blockBg") != NEUTRAL_BG:
                fails.append("health tint: агрегатная карточка перекрашена "
                             "(EVOL-032) (%s)" % (warn.get("blockBg"),))
            if warn.get("blockMaterial"):
                fails.append("health tint: у `.status-block` появился "
                             "data-health-material")
            if warn.get("hbMaterial") != "bg":
                fails.append("health tint: материал секции не `bg` (%s)"
                             % (warn.get("hbMaterial"),))
            if (warn.get("heroRadius") != neutral.get("heroRadius")
                    or warn.get("blockRadius") != neutral.get("blockRadius")):
                fails.append("health tint: радиусы соседних поверхностей "
                             "изменились (%s/%s vs %s/%s)\n"
                             % (warn.get("heroRadius"), warn.get("blockRadius"),
                                neutral.get("heroRadius"),
                                neutral.get("blockRadius")))

            # 2) Без сигнала (нет `generated_at` → данных нет) заливки нет.
            if neutral.get("hbState") != "unknown":
                fails.append("health tint: без телеметрии ожидалось unknown (%s)"
                             % (neutral.get("hbState"),))
            if _alpha(neutral.get("hbBg")) != 0.0:
                fails.append("health tint: нейтральная секция залита (%s)"
                             % (neutral.get("hbBg"),))
            for key, val in (neutral.get("counts") or {}).items():
                if val:
                    fails.append("health tint: без сигнала есть %s-заливка (%s)"
                                 % (key, val))

            # 3) Реальный критический сигнал (`polling_error`) → failed.
            if failed.get("hbState") != "failed" or failed.get("hbBg") != FAILED_BG:
                fails.append("health tint: critical не даёт failed-заливку "
                             "секции (%s / %s)"
                             % (failed.get("hbState"), failed.get("hbBg")))
            if (failed.get("heroState") != "failed"
                    or failed.get("heroBg") != FAILED_BG):
                fails.append("health tint: hero не показал failed бота (%s / %s)"
                             % (failed.get("heroState"), failed.get("heroBg")))

            # 4) Реальный вердикт другой подсистемы → degraded, и только там.
            if (degrad.get("expState") != "degraded"
                    or degrad.get("expBg") != DEGRADED_BG):
                fails.append("health tint: degraded другой подсистемы не "
                             "окрашивает её поверхность (%s / %s)"
                             % (degrad.get("expState"), degrad.get("expBg")))
            if _alpha(degrad.get("hbBg")):
                fails.append("health tint: секция «Сердцебиение» покрашена "
                             "чужим состоянием (%s)" % (degrad.get("hbBg"),))

            # 5) Порядок интенсивности — по РЕАЛЬНО измеренным цветам.
            c_warn = _rgb(warn.get("hbBg"))
            c_deg = _rgb(degrad.get("expBg"))
            c_fail = _rgb(failed.get("hbBg"))
            if not (c_warn and c_deg and c_fail):
                fails.append("health tint: цвета не прочитаны (%s / %s / %s)"
                             % (c_warn, c_deg, c_fail))
            elif (len({tuple(c_warn), tuple(c_deg), tuple(c_fail)}) != 3
                    or not (sum(c_warn) < sum(c_deg) < sum(c_fail))):
                fails.append("health tint: warning<degraded<failed не по "
                             "порядку (%s / %s / %s)" % (c_warn, c_deg, c_fail))

            # 6) Поверхность не сдвигает содержимое и не зависит от состояния:
            #    inset 17px — прежняя геометрия секции (border 1 + padding 16),
            #    поверхность совпадает с секцией (padding/отступов не вводит).
            for name, data in tint.items():
                if data.get("contentInset") != 17:
                    fails.append("health tint %s: контент секции сместился "
                                 "(inset=%s)" % (name, data.get("contentInset")))
                hb_b = data.get("hbBox") or {}
                pu_b = data.get("pulseBox") or {}
                if (hb_b.get("x") is None or pu_b.get("x") is None
                        or abs((hb_b["x"] - pu_b["x"])) > 0.6
                        or abs((hb_b.get("w") or 0) - (pu_b.get("w") or 0)) > 0.6):
                    fails.append("health tint %s: поверхность не совпадает с "
                                 "секцией по геометрии (%s vs %s)"
                                 % (name, hb_b, pu_b))
                for other_name, other in tint.items():
                    if other.get("vp") != data.get("vp"):
                        continue
                    o_b = other.get("hbBox") or {}
                    if (abs((hb_b.get("x") or 0) - (o_b.get("x") or 0)) > 0.6
                            or abs((hb_b.get("w") or 0) - (o_b.get("w") or 0)) > 0.6):
                        fails.append("health tint: состояние двигает поверхность "
                                     "секции (%s vs %s: %s vs %s)"
                                     % (name, other_name, hb_b, o_b))

            # 7) B2: тач-цель переключателя секций = 44×44 на 390 — и с
            #    touch-эмуляцией, и в узком окне с «мышью» (без coarse-pointer).
            for name, data in (("warning390", w390), ("plain390", plain390)):
                if data.get("tabsDisplay") == "none":
                    fails.append("телефон %s: переключатель секций скрыт" % name)
                boxes = data.get("tabs") or []
                if len(boxes) != 4:
                    fails.append("телефон %s: кнопок переключателя %s"
                                 % (name, len(boxes)))
                for bx in boxes:
                    if (bx.get("h") or 0) < 43.5 or (bx.get("w") or 0) < 43.5:
                        fails.append("телефон %s: тач-цель переключателя < 44×44 "
                                     "(%s)" % (name, bx))

            # 8) warning на 390 — тот же реальный путь и та же одна поверхность.
            if w390.get("hbState") != "warning" or w390.get("hbBg") != WARN_BG:
                fails.append("телефон: реальный warning не окрасил секцию "
                             "(%s / %s)"
                             % (w390.get("hbState"), w390.get("hbBg")))
            if (w390.get("counts") or {}).get("warning") != 1:
                fails.append("телефон: warning-заливка не на одной поверхности "
                             "(%s)" % (w390.get("counts"),))

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
