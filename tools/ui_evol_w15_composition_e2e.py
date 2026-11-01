"""EVOL-033 §D/§E.2 (W15) — поэкранная композиция и ЕДИНЫЕ компоненты.

Наследует измерительный стенд `tools/ui_round1025_matrix.py` (стабы API, TMA,
статика) и данные виджетов `tools/ui_evol_w10_sections_e2e.py` (тепловая карта,
лента досье, матрица прав). Нового фреймворка нет: настоящий `web/index.html`
+ `web/app.js` + `web/static/*`, реальные пиксели; измеряются вычисленные стили,
размеры и реальные состояния, а не разметка.

Контракт (plans/current_task.md §4.2/§12, строка L00478; §A/§B/§D/§E.2):

  1. ОДНА ВИЗУАЛЬНАЯ РОЛЬ = ОДИН ТИП КОМПОНЕНТА (§L01826). Для класса
     компонента собирается сигнатура каждого реально отрендеренного
     экземпляра: радиус, толщина/альфа границы, padding, gap, типографика
     заголовка/меты. Все экземпляры класса обязаны совпасть с токеном;
     разрешены только объявленные варианты плотности и состояния
     (hover/active/picked), которые из сравнения исключаются явно.
  2. ПОЭКРАННАЯ КОМПОЗИЦИЯ §D: обязательные блоки каждого раздела, включая
     под-вкладки «Аналитики» и разделы «Речи и характера», и запрет
     дублировать ленты/карту «Статуса» в «Аналитике».
  3. ГРАФИКИ (§B): у каждого блока — заголовок, единицы/период/зона времени,
     адресный drilldown либо честное пустое состояние; одна типографика меты.
  4. ТАБЛИЦЫ (§B): desktop — видимая шапка; телефон — список/detail
     (шапка скрыта, поля подписаны), без таблицы шириной в экран.
  5. РЕГРЕССИИ: горизонтальный скролл, обрезка текста, тач-цель компактной
     строки ≥44 px (coarse), ошибки консоли.

Запуск: py -3 tools/ui_evol_w15_composition_e2e.py [--out DIR] [--baseline]
  --baseline  прогон «до»: отказы фиксируются, код возврата 0 (они — то самое
              доказательство, что проверки не тавтологичны).
Выход по умолчанию: plans/features/evol/audit/evidence/w15-composition/
Печатает: EVOL-W15-COMPOSITION OK | FAIL
"""
import argparse
import io
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

import ui_round1025_matrix as M               # noqa: E402  стабы/статика/TMA
import ui_evol_w10_sections_e2e as W10        # noqa: E402  данные виджетов
import ui_evol_w9_responsive_e2e as W9        # noqa: E402  сервер статики
import ui_evol_s12_scenarios_e2e as S12       # noqa: E402  переход в GLOBAL

PORT = 8855
DEFAULT_OUT = os.path.join(REPO, "plans", "features", "evol", "audit",
                           "evidence", "w15-composition")

# Состояние экрана: (имя, адрес, драйвер под-состояния, комментарий).
# Драйверы: ("oversight", «подпись вкладки») — вкладка «Аналитики»;
# ("speech", «подпись раздела») — раздел «Речи и характера»; ("prompt-key", None)
# — открыть первый промпт в дереве; ("global", None) — верхний селектор в GLOBAL.
STATES = (
    ("status", "#/", None),
    ("analytics-overview", "#/oversight", ("oversight", "Обзор")),
    ("analytics-processes", "#/oversight", ("oversight", "Процессы")),
    ("analytics-runs", "#/oversight", ("oversight", "Запуски")),
    ("analytics-incidents", "#/oversight", ("oversight", "Инциденты")),
    ("analytics-memory", "#/oversight", ("oversight", "Память")),
    ("analytics-costs", "#/oversight", ("oversight", "Модели")),
    ("modules", "#/modules", ("global", None)),
    ("ai", "#/ai", None),
    ("ai-models", "#/modules/summary/models", None),
    ("prompts", "#/ai/prompts", None),
    ("prompts-sub", "#/ai/prompts/summary", None),
    ("prompts-editor", "#/ai/prompts/summary", ("prompt-key", None)),
    ("speech-persona", "#/ai/speech", ("speech", "Личность")),
    ("speech-style", "#/ai/speech", ("speech", "Речь и стиль")),
    ("speech-profanity", "#/ai/speech", ("speech", "Мат")),
    ("speech-examples", "#/ai/speech", ("speech", "Примеры")),
    ("speech-rules", "#/ai/speech", ("speech", "Правила")),
    ("memory", "#/memory", None),
    ("access", "#/access", None),
    ("access-roles", "#/access/roles", None),
)
VIEWPORTS = ((390, 844), (1280, 900))

# ── классы компонентов (одна визуальная роль) ───────────────────────────────
CARD_SEL = (".card", ".module-card", ".hub-card", ".prov-block", ".intel-card",
            ".story-card", ".speech-card", ".prompt-module-card",
            ".modal-card", ".ep-card", ".run-card", ".conn-card")
ROW_SEL = (".sfeed-item", ".mem-item", ".access-section-row",
           ".dossier-ticker__item")
DIVIDER_ROW_SEL = (".rec-row", ".llm-row", ".prompt-history-row", ".budget-row",
                   ".timeline-row", ".pipe-run-row", ".log-row", ".meme-row",
                   ".conn-fact")
DENSE_ROW_SEL = (".speech-rule", ".speech-soft", ".speech-hist", ".speech-lesson",
                 ".speech-entity-row", ".speech-layer-row", ".speech-cap-row",
                 ".speech-trace-row", ".speech-block-row", ".speech-skip-row",
                 ".speech-conflict-row", ".speech-hier-row")
CHART_SEL = ("[data-status-activity]", ".card:has([data-viz-flow])",
             ".card:has([data-viz-route])", ".card:has([data-viz-waterfall])")
TABLE_SEL = (".matrix-table", ".speech-table", ".avail-list")

# Состояния компонента, которые НЕ являются вариантом геометрии: это состояния
# (hover/picked/active). Из сравнения сигнатур они исключаются явно.
STATE_SKIP = ('[data-sfeed-active="1"]', '.is-active', '.is-picked', '.is-open',
              '[aria-pressed="true"]')

CARD_TOKENS = ("--card-radius", "--card-hairline", "--card-pad")
ROW_TOKENS = ("--row-radius", "--row-hairline", "--row-pad", "--row-gap")
TABLE_TOKENS = ("--table-row-radius", "--table-hairline", "--table-row-pad")
CHART_TOKENS = ("--chart-title-size", "--chart-meta-size", "--chart-legend-gap")

# Как проверять разрешённое значение токена (свойство → CSS).
TOKEN_PROPS = {
    "--card-radius": "borderRadius",
    "--card-hairline": "border",
    "--card-pad": "padding",
    "--row-radius": "borderRadius",
    "--row-hairline": "border",
    "--row-pad": "padding",
    "--row-gap": "rowGap",
    "--table-row-radius": "borderRadius",
    "--table-hairline": "border",
    "--table-row-pad": "padding",
    "--chart-title-size": "fontSize",
    "--chart-meta-size": "fontSize",
    "--chart-legend-gap": "gap",
}

# Объявленные варианты (§L01826 разрешает отличия по размеру и состоянию).
CARD_PAD_VARIANTS = (8.0, 12.0, 16.0, 20.0)   # p-2/p-3/p-4/p-5 модалок
ROW_PAD_Y_VARIANTS = (6.0, 8.0)               # лента в жёстком слоте 64 px
MODAL_RADIUS_VARIANTS = (16.0, 18.0)          # 18 px — верхний радиус листа

PROBE_TOKENS = r"""
(spec) => {
  // Значения токенов разрешаются реальным применением свойства: getPropertyValue
  // вернул бы `var(--space-3)`, а нам нужны фактически вычисленные px.
  const host = document.createElement('div');
  host.style.position = 'absolute';
  host.style.visibility = 'hidden';
  host.style.left = '-9999px';
  document.body.appendChild(host);
  const out = {};
  for (const [name, prop] of Object.entries(spec)) {
    const probe = document.createElement('div');
    host.appendChild(probe);
    probe.style[prop] = 'var(' + name + ')';
    const cs = getComputedStyle(probe);
    if (prop === 'border') {
      out[name] = {w: parseFloat(cs.borderTopWidth) || 0,
                   color: cs.borderTopColor};
    } else if (prop === 'padding') {
      out[name] = {t: parseFloat(cs.paddingTop) || 0,
                   l: parseFloat(cs.paddingLeft) || 0};
    } else if (prop === 'borderRadius') {
      out[name] = parseFloat(cs.borderTopLeftRadius) || 0;
    } else if (prop === 'fontSize') {
      out[name] = parseFloat(cs.fontSize) || 0;
    } else {
      out[name] = parseFloat(cs[prop]) || 0;
    }
  }
  host.remove();
  return out;
}
"""

PROBE_COMPONENTS = r"""
(spec) => {
  const {sel, skip} = spec;
  const px = (v) => {
    const f = parseFloat(v);
    return Number.isFinite(f) ? Math.round(f * 100) / 100 : null;
  };
  const alpha = (c) => {
    if (!c) return null;
    const m = String(c).match(/rgba?\(([^)]+)\)/);
    if (m) {
      const parts = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
      return parts.length > 3 ? Math.round(parts[3] * 1000) / 1000 : 1;
    }
    const m2 = String(c).match(/color\(srgb ([^)]+)\)/);
    if (m2) {
      const parts = m2[1].split(/[ ,/]+/).filter(Boolean).map(Number);
      return parts.length > 3 ? Math.round(parts[3] * 1000) / 1000 : 1;
    }
    return null;
  };
  const visible = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width >= 24 && r.height >= 8;
  };
  const inState = (el) => {
    for (const s of skip) { if (el.matches(s) || el.closest(s)) return true; }
    return false;
  };
  const out = {classes: {}, tokensUsed: {}};
  for (const s of sel) {
    out.classes[s] = [];
    // Дедупликация ТОЛЬКО внутри селектора: один и тот же узел законно
    // принадлежит и общему классу (`.card`), и своей роли (`.module-card`) —
    // проверки идут по классам независимо.
    for (const el of document.querySelectorAll(s)) {
      if (!visible(el)) continue;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const bw = px(cs.borderTopWidth);
      out.classes[s].push({
        state: inState(el),
        glassA: el.getAttribute('data-glass') === 'a',
        radius: px(cs.borderTopLeftRadius),
        bw: bw,
        balpha: bw ? alpha(cs.borderTopColor) : null,
        padTop: px(cs.paddingTop),
        padLeft: px(cs.paddingLeft),
        gap: px(cs.rowGap) || 0,
        w: Math.round(r.width), h: Math.round(r.height),
      });
    }
  }
  return out;
}
"""

PROBE_CHARTS = r"""
(spec) => {
  const out = [];
  for (const s of spec) {
    for (const el of document.querySelectorAll(s)) {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const cs = getComputedStyle(el);
      const txt = (el.textContent || '').replace(/\s+/g, ' ').trim();
      const titleEl = el.querySelector(
        '.text-sm.font-bold, .font-bold, .text-sm.font-semibold, h3, h4, ' +
        '[class*="title"]');
      const metaEls = Array.from(el.querySelectorAll(
        '.text-xs, .text-\\[10px\\], .text-\\[11px\\], [class*="caption"], ' +
        '[class*="legend"], [class*="meta"], [class*="note"]'));
      const metaTxt = metaEls.map((n) => n.textContent.replace(/\s+/g, ' ').trim())
        .filter((x) => x.length > 1);
      out.push({
        sel: s,
        title: titleEl ? titleEl.textContent.replace(/\s+/g, ' ').trim()
          .slice(0, 90) : '',
        meta: metaTxt.slice(0, 8),
        metaSize: metaEls.length ? parseFloat(getComputedStyle(metaEls[0]).fontSize)
          : null,
        radius: parseFloat(cs.borderTopLeftRadius) || 0,
        padTop: parseFloat(cs.paddingTop) || 0,
        drill: el.querySelectorAll('a[href^="#/"], [data-viz-heat-picked] button, ' +
                                   '[data-viz-ovcell], [data-viz-heatmap] button, ' +
                                   'button[data-viz-cell], [title]').length,
        empty: /данных нет|нет данных|недоступн|не было|честное пустое|появ/i
          .test(txt),
        len: txt.length,
      });
    }
  }
  return out;
}
"""

PROBE_COMPOSITION = r"""
() => {
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const vis = (el) => {
    if (!el) return false;
    const cs = getComputedStyle(el);
    return cs.display !== 'none' && cs.visibility !== 'hidden' &&
           el.getBoundingClientRect().height > 0;
  };
  const de = document.documentElement;
  let clipped = 0;
  const samples = [];
  for (const el of qa('#app *')) {
    if (el.children.length) continue;
    const txt = (el.textContent || '').trim();
    if (txt.length < 2) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (cs.overflowX !== 'hidden' && cs.overflowX !== 'clip') continue;
    if (cs.textOverflow === 'ellipsis') continue;
    if (el.scrollWidth > el.clientWidth + 1) {
      clipped += 1;
      if (samples.length < 5) {
        samples.push((el.className || el.tagName) + ' ' +
                     el.clientWidth + '<' + el.scrollWidth);
      }
    }
  }
  const openAdvanced = qa('details.advanced, [data-memory-tech], [data-viz-details]')
    .filter((d) => d.open === true).length;
  return {
    hScroll: de.scrollWidth - window.innerWidth,
    clipped: clipped, clippedSamples: samples,
    // Статус
    segs: qa('[data-status-seg]').filter(vis).length,
    health: qa('[data-status-health]').filter(vis).length,
    activity: qa('[data-status-activity]').filter(vis).length,
    dossier: qa('[data-status-dossier]').filter(vis).length,
    sleep: qa('[data-status-sleep]').filter(vis).length,
    experience: qa('[data-experience]').filter(vis).length,
    botControls: qa('.status-health__bot-actions button').filter(vis).length,
    logRows: qa('.log-row, .log-code').filter(vis).length,
    // Аналитика
    ovHealth: qa('[data-oversight-health]').filter(vis).length,
    ovTabs: qa('[data-oversight-tabs]').filter(vis).length,
    ovSelects: qa('[data-oversight-tab-panel] select, .oversight-mobile-trigger')
      .filter(vis).length,
    vizFlow: qa('[data-viz-flow]').filter(vis).length,
    vizRoute: qa('[data-viz-route]').filter(vis).length,
    vizDeps: qa('[data-viz-deps]').filter(vis).length,
    vizWaterfall: qa('[data-viz-waterfall]').filter(vis).length,
    storiesAnalytics: qa('[data-stories-analytics]').filter(vis).length,
    stories: qa('[data-stories]').filter(vis).length,
    heatmapHere: qa('[data-viz-heatmap]').filter(vis).length,
    dossierHere: qa('[data-status-dossier]').filter(vis).length,
    advancedOpen: openAdvanced,
    // Модули
    modCards: qa('[data-mod]').filter(vis).length,
    modSearch: qa('input.module-search, input[type="search"]').filter(vis).length,
    modFilters: qa('.module-filter-btn').filter(vis).length,
    modMaster: qa('.module-control-row__state, .module-state-value').filter(vis)
      .length,
    modTogglesPerCard: qa('[data-mod]').filter(vis).map((c) => c.querySelectorAll(
      '.ctl-toggle').length),
    modNoToggle: qa('[data-mod]').filter(vis).filter((c) => /без тумблера/
      .test(c.textContent || '')).length,
    modCardsCount: qa('[data-mod]').filter(vis).length,
    scopeKind: (() => {
      const vm = window.__adminbotVm;
      return vm ? (vm.scopeKind || null) : null;
    })(),
    // Сердцебиение: причина/свежесть в канонической строке здоровья
    hbInline: qa('[data-health-inline="heartbeat"]').filter(vis).length,
    hbReason: (() => {
      const el = document.querySelector('[data-health-inline="heartbeat"]');
      return el ? (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80)
        : '';
    })(),
    hbAria: (() => {
      const el = document.querySelector('.hb-canvas, .ekg');
      return el ? (el.getAttribute('aria-label') || '').slice(0, 120) : '';
    })(),
    // ИИ
    aiHub: qa('[data-ai-hub]').filter(vis).length,
    aiModels: qa('[data-ai-models]').filter(vis).length,
    aiPrompts: qa('[data-ai-prompts]').filter(vis).length,
    aiSpeech: qa('[data-ai-speech]').filter(vis).length,
    aiNames: qa('[data-ai-names]').filter(vis).length,
    aiPromptCounts: qa('[data-ai-prompt-counts]').filter(vis).length,
    connCard: qa('[data-connection-card]').filter(vis).length,
    connStatus: qa('[data-connection-status]').filter(vis).length,
    connCheck: qa('[data-conn-check]').filter(vis).length,
    connCheckFunc: qa('[data-conn-check-function]').filter(vis).length,
    connTest: qa('[data-conn-test]').filter(vis).length,
    connConfigure: qa('[data-conn-configure]').filter(vis).length,
    // Промпты
    promptCatalog: qa('[data-prompt-catalog]').filter(vis).length,
    promptTree: qa('[data-prompt-tree]').filter(vis).length,
    promptSearch: qa('[data-prompt-tree-search]').filter(vis).length,
    promptLibrary: qa('[data-prompt-library]').filter(vis).length,
    promptCards: qa('.prompt-module-card').filter(vis).length,
    promptEditor: qa('[data-prompt-editor]').filter(vis).length,
    promptHistory: qa('[data-prompt-history]').filter(vis).length,
    // Речь
    speechNav: qa('[data-speech-area-nav]').filter(vis).length,
    speechAreas: qa('[data-speech-area]').filter(vis).length,
    speechPersona: qa('[data-speech-persona]').filter(vis).length,
    speechLimits: qa('[data-speech-hint-limits]').filter(vis).length,
    speechProfanity: qa('[data-speech-profanity]').filter(vis).length,
    speechExamples: qa('[data-speech-examples-list]').filter(vis).length,
    speechRules: qa('[data-speech-rules]').filter(vis).length,
    // Память
    memSearch: qa('[data-memory-search]').filter(vis).length,
    memList: qa('[data-memory-list]').filter(vis).length,
    memItems: qa('[data-memory-item], .mem-item').filter(vis).length,
    memDiag: qa('[data-memory-diagnostics]').filter(vis).length,
    memTech: qa('[data-memory-tech], .mem-tech').filter(vis).length,
    // Доступы
    accSummary: qa('[data-access-summary]').filter(vis).length,
    accSections: qa('[data-access-section]').filter(vis).length,
    accAuditSummary: qa('[data-access-audit-summary]').filter(vis).length,
    accAudit: qa('[data-access-audit]').filter(vis).length,
    // Таблицы
    tables: qa('table').length,
    tableHeadVisible: qa('table thead').filter(vis).length,
    tableCellsLabeled: qa('table td[data-label]').length,
    matrixRows: qa('.matrix-table tbody tr').length,
    matrixSummary: qa('.matrix-perm-summary').filter(vis).length,
    matrixCells: qa('.matrix-table td').length,
    // Тач-цель компактных строк
    rowHeights: qa('.sfeed-item, .mem-item, .access-section-row')
      .filter(vis).map((el) => Math.round(el.getBoundingClientRect().height)),
  };
}
"""

DRIVE = r"""
(spec) => {
  const [kind, needle] = spec;
  if (kind === 'prompt-key') {
    const it = document.querySelector('[data-prompt-key]');
    if (!it) return false;
    it.click();
    return true;
  }
  const nav = kind === 'oversight'
    ? document.querySelector('[data-oversight-tabs]')
    : document.querySelector('[data-speech-area-nav]');
  if (!nav) return false;
  const btns = Array.from(nav.querySelectorAll('button, a'))
    .filter((b) => !/Раздел:/.test(b.textContent || ''));
  const hit = btns.find((b) => new RegExp(needle, 'i')
    .test((b.textContent || '').trim()));
  if (!hit) return false;
  hit.click();
  return true;
}
"""


def _ctx(browser, w, h):
    phone = w <= 430
    ctx = browser.new_context(viewport={"width": w, "height": h},
                              device_scale_factor=2 if phone else 1,
                              is_mobile=phone, has_touch=phone)
    ctx.add_init_script(M.TMA_STUB)
    ctx.route("**/api/**", W10._routes2())
    return ctx


def run(out_dir, baseline=False, port=PORT):
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    fails = []
    report = {"states": {}, "tokens": {}, "screenshots": [], "fails": []}
    httpd = ThreadingHTTPServer(("127.0.0.1", port), W9._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/web/index.html" % port
    sel_all = list(CARD_SEL + ROW_SEL + DIVIDER_ROW_SEL + DENSE_ROW_SEL)

    def shot(pg, name):
        path = os.path.join(out_dir, name + ".png")
        try:
            pg.screenshot(path=path, full_page=False)
            report["screenshots"].append(os.path.basename(path))
        except Exception:  # noqa: BLE001
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (w, h) in VIEWPORTS:
            ctx = _ctx(browser, w, h)
            pg = ctx.new_page()
            errs = []
            pg.on("console", lambda m: errs.append(m.text[:160])
                  if m.type == "error" else None)
            pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
            for idx, (name, route, drive) in enumerate(STATES):
                label = "%s@%d" % (name, w)
                pg.goto(base + "?w15=%d" % idx + route, wait_until="load")
                pg.wait_for_selector(".app-shell", timeout=25000)
                pg.wait_for_timeout(1200)
                if drive and drive[0] == "global":
                    S12._to_global(pg, wait=1000)
                elif drive:
                    pg.evaluate(DRIVE, list(drive))
                    pg.wait_for_timeout(900)
                toks = pg.evaluate(PROBE_TOKENS, TOKEN_PROPS)
                comp = pg.evaluate(PROBE_COMPONENTS,
                                   {"sel": sel_all, "skip": list(STATE_SKIP)})
                charts = pg.evaluate(PROBE_CHARTS, list(CHART_SEL + TABLE_SEL))
                compos = pg.evaluate(PROBE_COMPOSITION)
                compos["sheetBottom"] = pg.evaluate(
                    "() => document.documentElement.classList.contains('w9-sheet-bottom')")
                if not report["tokens"]:
                    report["tokens"] = toks
                report["states"][label] = {
                    "name": name, "route": route, "w": w, "h": h,
                    "drive": drive, "components": comp, "charts": charts,
                    "composition": compos, "console": errs[-3:],
                }
                shot(pg, "w15-%s-%d" % (name, w))
                if name == "status":
                    # Живая проверка графика сердцебиения: причина и свежесть
                    # доступны пользователю (tooltip по клику/Enter), а не
                    # только в разметке. Тот же путь, что у пользователя.
                    tip = ""
                    aria = compos.get("hbAria") or ""
                    try:
                        # Наведение — штатный путь для мыши (mouseenter), клик —
                        # для тача; проверяем оба, чтобы не подменять механизм.
                        pg.hover(".hb-canvas", timeout=4000)
                        pg.wait_for_timeout(200)
                        tip = pg.evaluate(
                            "() => { const t = document.querySelector('.hb-tip');"
                            " return t ? t.textContent.replace(/\\s+/g, ' ')"
                            ".trim().slice(0, 160) : ''; }")
                        pg.keyboard.press("Escape")
                    except Exception:  # noqa: BLE001
                        tip = ""
                    report["states"][label]["hb"] = {"tip": tip, "aria": aria}
                    if not tip:
                        fails.append("%s: tooltip сердцебиения не открывается"
                                     % label)
                    elif "Обновлено" not in tip:
                        fails.append("%s: в tooltip сердцебиения нет свежести "
                                     "измерения: %s" % (label, tip[:80]))
                    if not aria:
                        fails.append("%s: у графика сердцебиения нет aria-label"
                                     % label)
                if compos["hScroll"] > 1:
                    fails.append("%s: горизонтальный скролл %d px"
                                 % (label, compos["hScroll"]))
                if compos["clipped"] > 0:
                    fails.append("%s: обрезанный текст в %d узлах (%s)"
                                 % (label, compos["clipped"],
                                    compos["clippedSamples"][:3]))
                if errs:
                    fails.append("%s: ошибка консоли: %s" % (label, errs[-2:]))
                if w <= 430:
                    small = [hh for hh in compos["rowHeights"] if hh < 44]
                    if small:
                        fails.append("%s: компактная строка <44 px (%s)"
                                     % (label, small[:4]))
            ctx.close()
        browser.close()
    httpd.shutdown()

    toks = report["tokens"]

    # ── 1. Каркас карточки: один радиус/граница на все панели ───────────────
    card_r = toks["--card-radius"]
    card_b = toks["--card-hairline"]["w"]
    card_ba = _alpha_of(toks["--card-hairline"]["color"])
    row_r = toks["--row-radius"]
    row_b = toks["--row-hairline"]
    row_pad = toks["--row-pad"]
    row_gap = toks["--row-gap"]
    tbl_r = toks["--table-row-radius"]
    tbl_b = toks["--table-hairline"]
    tbl_pad = toks["--table-row-pad"]

    def collect(sel, field, skip_glass_a=False):
        vals = {}
        for label, st in report["states"].items():
            for it in st["components"]["classes"].get(sel, []):
                if it["state"]:
                    continue
                # Tier A — утверждённая оптика (L00552/E.6): её кромка живёт по
                # своим правилам материала и не переопределяется этой волной.
                if skip_glass_a and it.get("glassA"):
                    continue
                vals.setdefault(it[field], set()).add(label)
        return vals

    for sel in CARD_SEL:
        # В режиме нижнего листа (mobile sheet) верхний радиус панели — 18 px:
        # это объявленное платформенное поведение листа, а не вариант карточки.
        allowed = {card_r}
        sheet_states = {label for label, st in report["states"].items()
                        if st["composition"].get("sheetBottom")}
        radii = {}
        for label, st in report["states"].items():
            for it in st["components"]["classes"].get(sel, []):
                if it["state"]:
                    continue
                if label in sheet_states and it["radius"] == 18:
                    continue
                radii.setdefault(it["radius"], set()).add(label)
        bad = {r: sorted(v)[:3] for r, v in radii.items() if r not in allowed}
        if bad:
            fails.append("карточка %s: радиус вне --card-radius(%s): %s"
                         % (sel, card_r, bad))
        bw = {v for v in collect(sel, "bw", True) if v}
        if bw and bw != {card_b}:
            fails.append("карточка %s: толщина границы %s != %s"
                         % (sel, sorted(bw), card_b))
        ba = set(collect(sel, "balpha", True))
        if ba and ba != {card_ba}:
            fails.append("карточка %s: альфа границы %s != %s"
                         % (sel, sorted(ba), card_ba))
        pt = collect(sel, "padTop")
        off = {p: sorted(v)[:3] for p, v in pt.items()
               if p not in CARD_PAD_VARIANTS}
        if off:
            fails.append("карточка %s: padding вне шкалы %s: %s"
                         % (sel, CARD_PAD_VARIANTS, off))

    for sel in ROW_SEL:
        radii = set(collect(sel, "radius"))
        if radii != {row_r}:
            fails.append("строка %s: радиус %s != --row-radius %s"
                         % (sel, sorted(radii), row_r))
        padt = set(collect(sel, "padTop"))
        bad_y = {p for p in padt if p not in ROW_PAD_Y_VARIANTS}
        if padt and bad_y:
            fails.append("строка %s: вертикальный padding %s вне вариантов %s"
                         % (sel, sorted(bad_y), ROW_PAD_Y_VARIANTS))
        padl = set(collect(sel, "padLeft"))
        if padl and padl != {row_pad["l"]}:
            fails.append("строка %s: горизонтальный padding %s != --row-pad %s"
                         % (sel, sorted(padl), row_pad["l"]))
        ba = {v for v in collect(sel, "balpha") if v is not None}
        # Строка движущейся ленты досье не имеет рамки по замыслу (движущийся
        # текст в маскированной полосе); сравнение идёт только если рамка есть.
        if ba and ba != {_alpha_of(row_b["color"])}:
            fails.append("строка %s: альфа границы %s != %s"
                         % (sel, sorted(ba), _alpha_of(row_b["color"])))

    for sel in DENSE_ROW_SEL:
        radii = set(collect(sel, "radius"))
        if radii and radii != {tbl_r}:
            fails.append("строка-таблица %s: радиус %s != --table-row-radius %s"
                         % (sel, sorted(radii), tbl_r))
        bw = {v for v in collect(sel, "bw") if v}
        if bw and bw != {tbl_b["w"]}:
            fails.append("строка-таблица %s: толщина границы %s != %s"
                         % (sel, sorted(bw), tbl_b["w"]))
        ba = {v for v in collect(sel, "balpha") if v is not None}
        if ba and ba != {_alpha_of(tbl_b["color"])}:
            fails.append("строка-таблица %s: альфа границы %s != %s"
                         % (sel, sorted(ba), _alpha_of(tbl_b["color"])))
        padl = set(collect(sel, "padLeft"))
        if padl and padl != {tbl_pad["l"]}:
            fails.append("строка-таблица %s: padding %s != --table-row-pad %s"
                         % (sel, sorted(padl), tbl_pad["l"]))

    for sel in DIVIDER_ROW_SEL:
        ba = {v for v in collect(sel, "balpha") if v is not None}
        if len(ba) > 1:
            fails.append("строка-разделитель %s: разные альфы линии %s"
                         % (sel, sorted(ba)))

    # ── 2. Графики: каркас, мета, drilldown ─────────────────────────────────
    chart_title = toks["--chart-title-size"]
    chart_meta = toks["--chart-meta-size"]
    meta_sizes = set()
    for label, st in report["states"].items():
        for it in st["charts"]:
            if it["sel"] in TABLE_SEL:
                continue
            if not it["title"]:
                fails.append("график %s %s: нет заголовка" % (it["sel"], label))
            if not it["meta"] and not it["empty"]:
                fails.append("график %s %s: нет единиц/периода/зоны времени и "
                             "нет честного пустого состояния"
                             % (it["sel"], label))
            if it["drill"] < 1 and not it["empty"]:
                fails.append("график %s %s: нет адресного drilldown"
                             % (it["sel"], label))
            if it["metaSize"]:
                meta_sizes.add(round(it["metaSize"], 2))
    if len(meta_sizes) > 2:
        fails.append("графики: %d разных размеров меты %s"
                     % (len(meta_sizes), sorted(meta_sizes)))
    if chart_meta and meta_sizes and chart_meta not in meta_sizes:
        fails.append("графики: мета %s не использует --chart-meta-size %s"
                     % (sorted(meta_sizes), chart_meta))
    if not chart_title:
        fails.append("графики: --chart-title-size не объявлен")

    # ── 3. Таблицы: desktop-шапка / mobile-модель ───────────────────────────
    for label, st in report["states"].items():
        c = st["composition"]
        if not c["tables"]:
            continue
        w = st["w"]
        if w >= 1280:
            if c["tableHeadVisible"] < c["tables"]:
                fails.append("%s: шапка таблицы скрыта на desktop (%d/%d)"
                             % (label, c["tableHeadVisible"], c["tables"]))
        else:
            if c["tableHeadVisible"] > 0:
                fails.append("%s: на телефоне видна desktop-шапка таблицы"
                             % label)
            if c["matrixRows"] and not c["tableCellsLabeled"]:
                fails.append("%s: mobile-строки матрицы без подписей полей"
                             % label)

    # ── 4. Поэкранная композиция §D ─────────────────────────────────────────
    def st(name, w):
        return report["states"].get("%s@%d" % (name, w)) or {"composition": {}}

    def c(name, w):
        return st(name, w)["composition"]

    for w in (390, 1280):
        s = c("status", w)
        if s.get("segs", 0) < 3:
            fails.append("Статус@%d: сегментов здоровья %d < 3 (бот/сердце/сервер)"
                         % (w, s.get("segs", 0)))
        for key, human in (("activity", "«Активность по часам»"),
                           ("dossier", "«Живая лента досье»"),
                           ("experience", "показатели опыта"),
                           ("sleep", "панель сна")):
            if not s.get(key):
                fails.append("Статус@%d: нет блока «%s»" % (w, human))
        if s.get("logRows"):
            fails.append("Статус@%d: «Статус» превращён в дамп логов (%d)"
                         % (w, s["logRows"]))
        if not s.get("botControls"):
            fails.append("Статус@%d: нет управления ботом" % w)

        ov = c("analytics-overview", w)
        if not ov.get("ovHealth"):
            fails.append("Аналитика@%d: нет KPI/сводки здоровья" % w)
        if not ov.get("ovTabs"):
            fails.append("Аналитика@%d: нет вкладок разделов" % w)
        if not (c("analytics-processes", w).get("vizDeps")
                or c("analytics-processes", w).get("vizFlow")):
            fails.append("Аналитика@%d: «Процессы» без разреза по зависимостям" % w)
        if not c("analytics-runs", w).get("vizRoute"):
            fails.append("Аналитика@%d: «Запуски» без маршрута/воронки" % w)
        if not c("analytics-memory", w).get("stories"):
            fails.append("Аналитика@%d: «Истории памяти/эпизоды» не в «Памяти и "
                         "интеллекте»" % w)
        if not c("analytics-costs", w).get("vizWaterfall"):
            fails.append("Аналитика@%d: «Модели и расходы» без waterfall" % w)
        for tab in ("analytics-overview", "analytics-processes", "analytics-runs",
                    "analytics-incidents", "analytics-memory", "analytics-costs"):
            cc = c(tab, w)
            if cc.get("heatmapHere") or cc.get("dossierHere"):
                fails.append("Аналитика@%d (%s): дублирует ленты/карту «Статуса»"
                             % (w, tab))

        md = c("modules", w)
        if not md.get("modCards"):
            fails.append("Модули@%d: нет карточек модулей" % w)
        if not md.get("modSearch"):
            fails.append("Модули@%d: нет поиска по каталогу" % w)
        if not md.get("modFilters"):
            fails.append("Модули@%d: нет фильтров каталога" % w)
        if not md.get("modMaster"):
            fails.append("Модули@%d: нет текстового состояния области на карточке"
                         % w)
        # §D-3/§5 v2.1: в GLOBAL-области у каждой карточки РОВНО ОДИН тумблер;
        # модуль без тумблера обязан быть явно помечен, а не молча пустым.
        if md.get("scopeKind") != "global":
            fails.append("Модули@%d: не удалось переключить область в GLOBAL (%s)"
                         % (w, md.get("scopeKind")))
        toggles = md.get("modTogglesPerCard") or []
        cards = md.get("modCardsCount") or 0
        no_toggle = md.get("modNoToggle") or 0
        with_toggle = [n for n in toggles if n]
        if len(with_toggle) + no_toggle < cards:
            fails.append("Модули@%d: у %d из %d карточек нет ни тумблера, ни "
                         "пометки «без тумблера»"
                         % (w, cards - len(with_toggle) - no_toggle, cards))
        bad = [n for n in toggles if n > 1]
        if bad:
            fails.append("Модули@%d: в карточке %d тумблеров (нужен один)"
                         % (w, bad[0]))

        ai = c("ai", w)
        for key, human in (("aiHub", "центр ИИ"), ("aiModels", "провайдеры/модели"),
                           ("aiPrompts", "промпты"), ("aiSpeech", "речь"),
                           ("aiNames", "имена")):
            if not ai.get(key):
                fails.append("ИИ@%d: нет блока «%s»" % (w, human))

        # «ИИ → подключения»: тот же каркас карточки для блока провайдеров и
        # реальная проверка ключей (график истории = график с метой и drilldown).
        ac_ = c("ai-models", w)
        if not ac_.get("connCard"):
            fails.append("ИИ(модели)@%d: нет карточек подключений" % w)

        mdl = c("ai-models", w)
        if not mdl.get("connCard"):
            fails.append("Модели@%d: нет карточек подключений" % w)
        if not (mdl.get("connCheck") and mdl.get("connCheckFunc")):
            fails.append("Модели@%d: проверка соединения и функции не разделены"
                         % w)
        if not (mdl.get("connTest") and mdl.get("connConfigure")):
            fails.append("Модели@%d: нет действий «Проверить»/«Настроить»" % w)

        pr = c("prompts", w)
        for key, human in (("promptCatalog", "каталог промптов"),
                           ("promptLibrary", "библиотека по модулям")):
            if not pr.get(key):
                fails.append("Промпты@%d: нет блока «%s»" % (w, human))
        if not pr.get("promptCards"):
            fails.append("Промпты@%d: нет карточек модулей" % w)
        psub = c("prompts-sub", w)
        for key, human in (("promptTree", "дерево промптов"),
                           ("promptSearch", "поиск по промптам")):
            if not psub.get(key):
                fails.append("Промпты(модуль)@%d: нет блока «%s»" % (w, human))
        ped = c("prompts-editor", w)
        for key, human in (("promptEditor", "редактор промпта"),
                           ("promptHistory", "история версий")):
            if not ped.get(key):
                fails.append("Промпты(редактор)@%d: нет блока «%s»" % (w, human))

        hb = c("status", w)
        if not hb.get("hbInline") or not (hb.get("hbReason") or "").strip():
            fails.append("Статус@%d: у графика сердцебиения нет канонической "
                         "строки состояния/причины" % w)

        sp = c("speech-persona", w)
        if not sp.get("speechNav"):
            fails.append("Речь@%d: нет навигации разделов" % w)
        if sp.get("speechAreas", 0) < 5:
            fails.append("Речь@%d: разделов речи %d < 5"
                         % (w, sp.get("speechAreas", 0)))
        if not sp.get("speechPersona"):
            fails.append("Речь@%d: раздел «Личность» пуст" % w)
        for area, key, human in (("speech-style", "speechLimits",
                                  "лимиты/подсказки"),
                                 ("speech-profanity", "speechProfanity", "мат"),
                                 ("speech-examples", "speechExamples", "примеры"),
                                 ("speech-rules", "speechRules",
                                  "правила и источники")):
            if not c(area, w).get(key):
                fails.append("Речь@%d: раздел «%s» не отрендерен" % (w, human))

        me = c("memory", w)
        for key, human in (("memSearch", "поиск человеческим текстом"),
                           ("memList", "список знаний"),
                           ("memDiag", "диагностика/состояние FTS/vector")):
            if not me.get(key):
                fails.append("Память@%d: нет блока «%s»" % (w, human))
        if not me.get("memItems"):
            fails.append("Память@%d: список знаний пуст при непустых данных" % w)

        ac = c("access", w)
        for key, human in (("accSummary", "сводка ролей"),
                           ("accSections", "разделы прав"),
                           ("accAuditSummary", "аудит изменений")):
            if not ac.get(key):
                fails.append("Доступы@%d: нет блока «%s»" % (w, human))
        ar = c("access-roles", w)
        if not ar.get("matrixRows"):
            fails.append("Доступы(роли)@%d: матрица прав пуста" % w)
        if not ar.get("accAudit"):
            fails.append("Доступы(роли)@%d: нет audit trail изменения прав" % w)

    report["fails"] = fails
    out_json = os.path.join(
        out_dir, "w15-composition%s.json" % ("-before" if baseline else ""))
    with io.open(out_json, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    print("W15 %s" % json.dumps({"states": len(report["states"]),
                                 "shots": len(report["screenshots"]),
                                 "fails": len(fails)}, ensure_ascii=False))
    for f in fails[:40]:
        print(" -", f)
    if fails and not baseline:
        print("EVOL-W15-COMPOSITION FAIL")
        return 1
    print("EVOL-W15-COMPOSITION OK" if not fails else
          "EVOL-W15-COMPOSITION BASELINE (fails recorded: %d)" % len(fails))
    return 0


def _alpha_of(color):
    """Альфа из computed border-color (rgb/rgba/color(srgb ...))."""
    if not color:
        return None
    s = str(color)
    if s.startswith("rgb("):
        return 1.0
    if s.startswith("rgba("):
        try:
            return round(float(s[s.rindex(",") + 1:s.rindex(")")].strip()), 3)
        except Exception:  # noqa: BLE001
            return None
    if s.startswith("color("):
        try:
            tail = s[s.index("(") + 1:s.rindex(")")].split("/")
            if len(tail) == 2:
                return round(float(tail[1].strip()), 3)
            return 1.0
        except Exception:  # noqa: BLE001
            return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    return run(args.out, baseline=args.baseline, port=args.port)


if __name__ == "__main__":
    sys.exit(main())
