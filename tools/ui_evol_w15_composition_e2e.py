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

# Состояние экрана: (имя, адрес, драйвер под-состояния).
# Драйверы: ("oversight", «подпись вкладки») — вкладка «Аналитики»;
# ("speech", «подпись раздела») — раздел «Речи и характера»; ("card", id) —
# карточка-витрина `[data-speech-card=id]`; ("prompt-key", None) — открыть
# первый промпт в дереве; ("global", None) — верхний селектор в GLOBAL.
STATES = (
    ("status", "#/", None),
    ("analytics-overview", "#/oversight", ("oversight", "Обзор")),
    ("analytics-processes", "#/oversight", ("oversight", "Процессы")),
    ("analytics-runs", "#/oversight",
     ("oversight", "Процессы>Запуски")),
    ("analytics-incidents", "#/oversight", ("oversight", "Инциденты")),
    ("analytics-memory", "#/oversight", ("oversight", "Память")),
    ("analytics-costs", "#/oversight", ("oversight", "Модели")),
    ("analytics-summary", "#/oversight", ("oversight", "Саммари")),
    ("modules", "#/modules", ("global", None)),
    ("ai", "#/ai", None),
    ("ai-models", "#/modules/summary/models", None),
    ("prompts", "#/ai/prompts", None),
    ("prompts-sub", "#/ai/prompts/summary", None),
    ("prompts-editor", "#/ai/prompts/summary", ("prompt-key", None)),
    ("speech-hub", "#/ai/speech", ("back", None)),
    ("speech-persona", "#/ai/speech", ("speech", "Личность")),
    ("speech-style", "#/ai/speech", ("speech", "Речь и стиль")),
    ("speech-profanity", "#/ai/speech", ("speech", "Мат")),
    ("speech-examples", "#/ai/speech", ("speech", "Примеры")),
    ("speech-rules", "#/ai/speech", ("speech", "Правила")),
    ("speech-core", "#/ai/speech", ("card", "core")),
    ("speech-inspector", "#/ai/speech", ("card+mode", "inspector|preview")),
    ("speech-capabilities", "#/ai/speech", ("card", "capabilities")),
    ("speech-blocks", "#/ai/speech", ("card", "all")),
    ("memory", "#/memory", None),
    ("access", "#/access", None),
    ("access-roles", "#/access/roles", None),
)

# Маршруты §D-7, которых нет в STATES: композицию они не утверждают, но
# компоненты/раскладка на них обязаны измеряться (ревью 5.2: «ни один экран не
# исключать»). Для каждого снимается та же сигнатура компонентов и регрессии.
COVERAGE_ROUTES = (
    ("#/how", "how"),
    ("#/permsoc", "permsoc"),
    ("#/status/graph", "status-graph"),
    ("#/ai/llm", "ai-llm"),
    ("#/ai/limits", "ai-limits"),
    ("#/ai/names", "ai-names"),
    ("#/ai/persona", "ai-persona"),
    ("#/ai/lore", "ai-lore"),
    ("#/ai/relations", "ai-relations"),
    ("#/ai/sleep", "ai-sleep"),
    ("#/ai/nostalgia", "ai-nostalgia"),
    ("#/ai/smart-cache", "ai-smart-cache"),
    ("#/memory/rag", "memory-rag"),
    ("#/memory/lore", "memory-lore"),
    ("#/memory/relations", "memory-relations"),
    ("#/access/admins", "access-admins"),
    ("#/access/local", "access-local"),
    ("#/modules/vision", "modules-vision"),
    ("#/modules/sleep", "modules-sleep"),
    ("#/modules/initiative", "modules-initiative"),
    ("#/modules/reactions", "modules-reactions"),
    ("#/modules/switches", "modules-switches"),
    ("#/modules/features", "modules-features"),
    ("#/modules/budgets", "modules-budgets"),
    ("#/modules/images", "modules-images"),
    ("#/modules/custom", "modules-custom"),
    ("#/modules/random", "modules-random"),
    ("#/modules/initiative/settings", "modules-initiative-settings"),
)
VIEWPORTS = ((390, 844), (1280, 900))

# ── классы компонентов (одна визуальная роль) ───────────────────────────────
# Карточка/панель. `.story-card` и `.ep-card` — детали внутри manage/feed
# (рендерятся только по клику в «Историях»): их CSS переведён на токены и
# удерживается структурным инвариантом, но в живой набор они НЕ входят —
# иначе объявленный класс молча проходил бы с нулём экземпляров (ревью 5.1/5.2).
CARD_SEL = (".card", ".module-card", ".hub-card", ".prov-block", ".intel-card",
            ".prompt-module-card", ".speech-card", ".modal-card", ".run-card",
            ".conn-card")
# Компактная строка-сущность (кликабельная запись/раздел/слой).
ROW_SEL = (".sfeed-item", ".mem-item", ".access-section-row",
           ".dossier-ticker__item", ".speech-layer-card")
# Строка-разделитель внутри таблицы/списка «ключ → значение».
DIVIDER_ROW_SEL = (".budget-row", ".conn-fact", ".pipe-run-row")
# Плотная строка таблицы/инспектора. `.speech-entity-row` удалён: класса нет в
# разметке (мёртвое правило) — объявленный-но-не-рендерящийся класс запрещён.
DENSE_ROW_SEL = (".speech-rule", ".speech-soft",
                 ".speech-layer-row", ".speech-cap-row", ".speech-trace-row",
                 ".speech-block-row", ".speech-skip-row", ".speech-conflict-row",
                 ".speech-hier-row", ".speech-limits", ".mem-kv")
# Уведомление/заметка: своя семантика цвета кромки, но геометрия роли — та же.
NOTICE_SEL = (".access-audit",)
CHART_SEL = ("[data-status-activity]", "[data-viz-flow]",
             "[data-viz-waterfall]", "[data-viz-route]")
TABLE_SEL = (".matrix-table", ".speech-table", ".avail-list")

# Состояния компонента, которые НЕ являются вариантом геометрии: это состояния
# (hover/picked/active). Из сравнения сигнатур они исключаются явно.
STATE_SKIP = ('[data-sfeed-active="1"]', '.is-active', '.is-picked', '.is-open',
              '[aria-pressed="true"]')
# Семантические варианты кромки (цвет = смысл: семантика памяти, diff before/
# after, insufficient-история): геометрия роли остаётся общей, альфа границы у
# них НЕ сравнивается с hairline роли.
SEMANTIC_BORDER = ('.mem-kv--semantic', '.story-card--insufficient',
                   '.speech-diff-line.before', '.speech-diff-line.after',
                   '.speech-preview-line.after', '.funnel-cell--warn')

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
CARD_PAD_VARIANTS = (8.0, 12.0, 16.0, 20.0, 24.0)  # p-2/3/4/5/6
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
  const {sel, skip, semantic} = spec;
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
      let semanticBorder = false;
      for (const sel2 of (semantic || [])) {
        if (el.matches(sel2)) { semanticBorder = true; break; }
      }
      out.classes[s].push({
        state: inState(el),
        semantic: semanticBorder,
        glassA: el.getAttribute('data-glass') === 'a',
        radius: px(cs.borderTopLeftRadius),
        bw: bw,
        balpha: (bw && !semanticBorder) ? alpha(cs.borderTopColor) : null,
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
  if (kind === 'back') {
    const btn = document.querySelector('.speech-back, [data-speech-editor-back]');
    if (!btn) return false;
    btn.click();
    return true;
  }
  if (kind === 'record') {
    const it = document.querySelector('[data-status-dossier] .dossier-ticker__item');
    if (!it) return false;
    it.click();
    return true;
  }
  if (kind === 'card') {
    const card = document.querySelector('[data-speech-card="' + needle + '"]');
    if (!card) return false;
    card.click();
    return true;
  }
  const nav = kind === 'oversight'
    ? document.querySelector('[data-oversight-tabs]')
    : document.querySelector('[data-speech-area-nav]');
  if (!nav) return false;
  const btns = Array.from(nav.querySelectorAll('button, a'))
    .filter((b) => !/Раздел:/.test(b.textContent || ''));
  const needles = String(needle).split('>');
  const hit = btns.find((b) => new RegExp(needles[needles.length - 1], 'i')
    .test((b.textContent || '').trim()));
  if (!hit) return false;
  if (needles.length > 1) {
    // Сначала промежуточная вкладка (её данные остаются в SPA-состоянии).
    const first = btns.find((b) => new RegExp(needles[0], 'i')
      .test((b.textContent || '').trim()));
    if (first) first.click();
  }
  hit.click();
  return true;
}
"""


# ── фикстуры «живых» блоков речи/аналитики ──────────────────────────────────
# Формы взяты из шаблонов `web/index.html` и чтения полей в `web/app.js`
# (не выдуманные проценты: все числа — счётчики/идентификаторы фикстуры).
SPEECH_OVERVIEW = {
    "sections": [
        {"id": "core", "title": "Личность", "subtitle": "Core, биография",
         "detail": "постоянная основа", "icon": "psychology", "ready": True},
        {"id": "style", "title": "Речь и стиль", "subtitle": "правила письма",
         "detail": "строгие и мягкие", "icon": "edit_note", "ready": True},
        {"id": "expression", "title": "Выражение", "subtitle": "тон, юмор",
         "detail": "эффективные значения", "icon": "record_voice_over",
         "ready": True},
        {"id": "examples", "title": "Примеры", "subtitle": "авторские образцы",
         "detail": "обучение на примерах", "icon": "menu_book", "ready": True},
    ],
    "advanced": [
        {"id": "learning", "title": "Обучение", "subtitle": "обратная связь",
         "icon": "school", "ready": True},
        {"id": "inspector", "title": "Инспектор", "subtitle": "слои сборки",
         "icon": "search", "ready": True},
        {"id": "capabilities", "title": "Возможности",
         "subtitle": "инструменты и права", "icon": "checklist", "ready": True},
        {"id": "all", "title": "Все инструкции", "subtitle": "блоки текста",
         "icon": "segment", "ready": True},
    ],
    "gates": {"character_core_enabled": True}, 
    "layers": {"l1": {"fallback": False}, "self_model": {"applied": 2,
                                                          "rejected": 1}},
}
SPEECH_CORE = {
    "block_ids": {"full": "core.full", "compact": "core.compact"},
    "doc_key": "content.core_doc",
    "scope": "global",
    "chat_id": None,
    "inheritance": "global",
    "global_present": True,
    "chat_present": False,
    "permanent_note": "Core — постоянный характер: он действует постоянно.",
    "selection": {"level": "global", "reason": "глобальная редакция"},
    "factory": {"full_text": "Ты — Админбот.", "compact_text": "Ты — Админбот.",
                "full_chars": 15, "compact_chars": 15,
                "full_revision": "f-12", "compact_revision": "f-12"},
    "document": {"revision": "r-13", "enabled": True, "detail_level": "compact",
                 "origin": "manual", "updated_at": "01.11.2026 12:00",
                 "present": True},
    "editions": {
        "global": {"differs_from_factory": True, "label": "ручная"},
        "full": {"text": "Ты — Админбот. Кратко.", "source": "global",
                 "scope_label": "все чаты", "revision": "r-13",
                 "factory_revision": "f-12", "differs_from_factory": True,
                 "withheld": False, "withheld_class": None,
                 "withheld_reason": None, "diagnostics": [], "chars": 22},
        "compact": {"text": "Ты — Админбот.", "source": "factory",
                    "scope_label": "заводская", "revision": "f-12",
                    "factory_revision": "f-12", "differs_from_factory": False,
                    "withheld": False, "withheld_class": None,
                    "withheld_reason": None, "diagnostics": [], "chars": 15},
    },
    "diff": {"full": {"added": 1, "removed": 0, "rows": []},
             "compact": {"added": 0, "removed": 0, "rows": []}},
    "history": [
        {"revision": "r-13", "kind": "manual", "scope": "global",
         "sha256_12": "abcdef012345", "chars": 22,
         "updated_at": "01.11.2026 12:00", "actor": "audit",
         "reason": "правка"},
        {"revision": "f-12", "kind": "factory", "scope": "global",
         "sha256_12": "fedcba654321", "chars": 15,
         "updated_at": "31.10.2026 09:30", "actor": "factory",
         "reason": "заводская"},
    ],
    "inspection": {},
    "gates": {"character_core_enabled": True},
    "can_edit": True,
}
SPEECH_STYLE = {
    "rules": [
        {"id": "r1", "title": "Без канцелярита", "strictness": "hard",
         "source": "owner", "enabled": True, "scope": "global",
         "reason": "живее"},
        {"id": "r2", "title": "Короткие абзацы", "strictness": "soft",
         "source": "factory", "enabled": True, "scope": "global"},
        {"id": "r3", "title": "Не повторять мысль", "strictness": "hard",
         "source": "owner", "enabled": True, "scope": "chat"},
        {"id": "r4", "title": "Без CAPS", "strictness": "hard",
         "source": "factory", "enabled": False, "scope": "global"},
        {"id": "r5", "title": "Мягкие связки", "strictness": "soft",
         "source": "owner", "enabled": True, "scope": "initiative"},
        {"id": "r6", "title": "Точные даты", "strictness": "hard",
         "source": "factory", "enabled": True, "scope": "global"},
    ],
    "soft_instructions": [
        {"id": "s1", "text": "Пиши дружелюбно", "scope": "global"},
        {"id": "s2", "text": "Не извиняйся без причины", "scope": "chat"},
    ],
    "quotes_mode": "strip",
}
SPEECH_CAPABILITIES = {
    "capabilities": [
        {"capability_id": "web_search", "title": "Поиск в интернете",
         "status": "ok", "reason_code": "", "reason": ""},
        {"capability_id": "images", "title": "Изображения",
         "status": "off", "reason_code": "key_missing",
         "reason": "ключ не настроен"},
        {"capability_id": "tts", "title": "Речь вслух",
         "status": "off", "reason_code": "disabled",
         "reason": "модуль выключен"},
    ],
    "trace": [
        {"stage": "L1", "event": "decision", "outcome": "silent",
         "reason_code": "", "status": "ok", "entity_id": "trace-1"},
        {"stage": "Writer", "event": "reply", "outcome": "public",
         "reason_code": "", "status": "ok", "entity_id": "trace-2"},
    ],
}
SPEECH_BLOCKS = {"blocks": [
    {"block_id": "core.identity", "purpose": "ядро личности",
     "effective": {"source": "factory", "differs_from_factory": False}},
    {"block_id": "style.rules", "purpose": "правила письма",
     "effective": {"source": "owner", "differs_from_factory": True}},
    {"block_id": "expression.tone", "purpose": "тон и юмор",
     "effective": {"source": "factory", "differs_from_factory": False}},
]}
SPEECH_INSPECTOR = {
    "preview": {
        "preview_note": "Предпросмотр сборки: маскированные значения.",
        "layers": [
            {"layer": "core", "label": "Core", "source": "factory",
             "revision": "r12", "rendered": True, "tokens": 210},
            {"layer": "style", "label": "Style", "source": "owner",
             "revision": "r3", "rendered": True, "tokens": 140},
            {"layer": "examples", "label": "Примеры", "source": "factory",
             "revision": "—", "rendered": False,
             "skip_reason_human": "не выбраны", "skip_reason_code": "empty"},
        ],
        "system_masked": "SYSTEM: ****",
    },
    "skip_reasons": [
        {"layer": "examples", "label": "Примеры", "code": "empty",
         "text": "примеров нет"},
    ],
    "hierarchy": [
        {"group": "core", "title": "Основа",
         "items": [{"layer": "core", "label": "Core", "rendered": True},
                   {"layer": "style", "label": "Style", "rendered": True}]},
    ],
    "core": {"level": "global", "reason": "глобальная редакция"},
    "trace_coverage": [],
    "conflicts_detail": {
        "coverage_note": "Проверено по действующим правилам.",
        "classes": [
            {"class": "length", "title": "Длина", "detected": 1,
             "items": [{"conflict_id": "c-1", "detail": "правило короче"}]},
            {"class": "tone", "title": "Тон", "detected": 0, "items": []},
        ],
    },
}
SPEECH_LEARNING = {
    "note": "",
    "lessons": {"state": "ok", "count": 0, "items": []},
    "humor_feedback": {
        "enabled": True, "available": True, "paused": False, "can_manage": True,
        "note": "", "reason": "", "sends": 12, "unknown_windows": 1,
        "policy": "balanced", "signals": {"laugh": 3, "ignore": 2},
        "decay_note": "Свежесть учитывается при выборе приёма.",
        "scenarios": [],
        "entries": [
        {"lesson_id": "l1", "technique": "ирония", "direction": "strengthen",
         "decay": "свежая", "influence": "чаще иронизирует"},
        {"lesson_id": "l2", "technique": "сарказм", "direction": "weaken",
         "decay": "стареет", "influence": "реже сарказм"},
    ]},
    "lessons": [],
}
PIPELINE_RUN = {
    "run": {
        "run_id": "w15-run-0001", "health": "ok", "health_label": "Норма",
        "duration_ms": 5200, "chat_id": -1001234567890, "mode": "hybrid",
        "nodes": [
            {"key": "l1", "label": "L1", "state": "success", "latency_ms": 900},
            {"key": "factcheck", "label": "Фактчек", "state": "success",
             "latency_ms": 1500},
            {"key": "writer", "label": "Writer", "state": "success",
             "latency_ms": 1800},
            {"key": "l2", "label": "L2 review", "state": "repaired",
             "latency_ms": 700},
            {"key": "publish", "label": "Публикация", "state": "success",
             "latency_ms": 300},
        ],
        "coverage": {"total": 12},
        "publication": {"status": "ok", "channel": "telegram"},
        "capacity": {"required_input_tokens": 900,
                     "reserved_output_tokens": 400},
    },
    "runs": [
        {"run_id": "w15-run-0001", "ts": 1761800000, "health": "ok",
         "health_label": "Норма", "source_count": 12},
        {"run_id": "w15-run-0000", "ts": 1761796400, "health": "warn",
         "health_label": "Деградация", "source_count": 8},
    ],
}
PROCESS_ACTIVITY = {
    "available": True, "events_available": True,
    "processes": [
        {"process_id": "ingestion.live", "counts": {"24h": 42, "7d": 210},
         "effective": "ok", "last_ts": 1761800000},
        {"process_id": "facts.extract", "counts": {"24h": 18, "7d": 96},
         "effective": "ok", "last_ts": 1761800100},
        {"process_id": "dossier.rebuild", "counts": {"24h": 6, "7d": 30},
         "effective": "ok", "last_ts": 1761800200},
        {"process_id": "summary.window", "counts": {"24h": 12, "7d": 60},
         "effective": "ok", "last_ts": 1761800300},
        {"process_id": "summary.hybrid", "counts": {"24h": 9, "7d": 41},
         "effective": "ok", "last_ts": 1761800400},
        {"process_id": "episodes.build", "counts": {"24h": 4, "7d": 20},
         "effective": "ok", "last_ts": 1761800500},
        {"process_id": "retrieval.query", "counts": {"24h": 30, "7d": 140},
         "effective": "ok", "last_ts": 1761800600},
        {"process_id": "direct.reply", "counts": {"24h": 21, "7d": 110},
         "effective": "ok", "last_ts": 1761800700},
        {"process_id": "intent.initiative", "counts": {"24h": 3, "7d": 12},
         "effective": "ok", "last_ts": 1761800800},
        {"process_id": "summary.publish", "counts": {"24h": 5, "7d": 25},
         "effective": "ok", "last_ts": 1761800900},
        {"process_id": "sleep.dream", "counts": {"24h": 2, "7d": 9},
         "effective": "ok", "last_ts": 1761801000},
    ],
}
EXTRA_STUBS = (
    ("/api/speech/overview", SPEECH_OVERVIEW),
    ("/api/speech/core", SPEECH_CORE),
    ("/api/speech/style", SPEECH_STYLE),
    ("/api/speech/expression", {"enabled": True, "tone": "dry", "wit": 3,
                                "sharpness": 2, "verbosity": 2,
                                "profanity": "occasional"}),
    ("/api/speech/humor", {"enabled": True, "level": "medium",
                           "techniques": [], "feedback": {}}),
    ("/api/roles", {"roles": [{"role_name": "user", "level": 10,
                               "permissions": {}}]}),
    ("/api/speech/examples", {"items": [], "deleted": [], "legacy": []}),
    ("/api/speech/learning", SPEECH_LEARNING),
    ("/api/speech/blocks", SPEECH_BLOCKS),
    ("/api/speech/capabilities", SPEECH_CAPABILITIES),
    ("/api/speech/inspector", SPEECH_INSPECTOR),
    ("/api/analytics/pipeline/inspector", PIPELINE_RUN),
    ("/api/analytics/pipeline/runs/latest", PIPELINE_RUN),
    ("/api/analytics/viz/process-activity", PROCESS_ACTIVITY),
)


def _routes(me=None):
    """Стабы W10 + фикстуры «живых» плотных строк/графиков этой волны.

    `me` — подмена ответа `/api/me` (нужна оптическому эксперименту: тот же
    экран с включённым и выключенным вендорным Liquid Glass).
    """
    base_route = W10._routes2()

    def _route(route):
        url = route.request.url.split("?")[0]
        if me is not None and url.endswith("/api/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(me))
            return
        for marker, payload in EXTRA_STUBS:
            if url.endswith(marker):
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(payload))
                return
        base_route(route)
    return _route


def _ctx(browser, w, h):
    phone = w <= 430
    ctx = browser.new_context(viewport={"width": w, "height": h},
                              device_scale_factor=2 if phone else 1,
                              is_mobile=phone, has_touch=phone)
    ctx.add_init_script(M.TMA_STUB)
    ctx.route("**/api/**", _routes())
    return ctx


# ═══ W16 (контракт владельца 02.11.2026): адаптивность узкого вьюпорта ═══════
# Три РАЗНЫХ режима масштаба измеряются отдельно, как требует §6 контракта:
#   normal       — обычный масштаб (опорные 320/360/390);
#   pagezoom200  — browser page zoom 200 %: CSS-вьюпорт = экран/2; ширина НЕ
#                  вычисляется делением — она читается из window.innerWidth и
#                  сверяется с rect'ами реальных элементов;
#   font200      — увеличенный СИСТЕМНЫЙ шрифт (root font-size 32 px, rem-
#                  масштаб): CSS-ширина окна не меняется, поэтому media-запросы
#                  по ширине молчат — проверяется фактический reflow;
#   telegram_kb  — Telegram WebView: открытая клавиатура уменьшает ВИДИМУЮ
#                  область (в приложении это существующий `--kb-offset`),
#                  проверяется доступность save/cancel в редакторе.
ADAPTIVE_MODES = (
    ("normal", "обычный масштаб"),
    ("pagezoom200", "browser page zoom 200 %"),
    ("font200", "системный шрифт 200 %"),
    ("telegram_kb", "Telegram WebView + клавиатура"),
)
ADAPTIVE_WIDTHS = (390, 360, 320)

# Экраны и их критические действия. Набор объявлен явно: «нет действия» —
# это факт экрана (на корне нечего «назад»), а не пропущенная проверка.
ADAPTIVE_SCREENS = (
    {
        "name": "status", "route": "#/",
        "need": ("nav", "scope", "fullscreen", "palette_via_drawer", "refresh"),
    },
    {
        "name": "modules", "route": "#/modules",
        "need": ("nav", "scope", "fullscreen", "palette_via_drawer"),
    },
    {
        "name": "oversight", "route": "#/oversight",
        "need": ("nav", "scope", "fullscreen", "palette_via_drawer", "refresh"),
    },
    {
        "name": "speech", "route": "#/ai/speech",
        "need": ("nav", "scope", "fullscreen", "palette_via_drawer", "back",
                 "save"),
    },
    {
        "name": "prompt-editor", "route": "#/ai/prompts/summary",
        "driver": ("prompt-key", None),
        "need": ("nav", "scope", "fullscreen", "palette_via_drawer", "back"),
    },
)

PROBE_ADAPTIVE = r"""
() => {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const de = document.documentElement;
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const vis = (el) => {
    if (!el) return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const inScroller = (el) => {
    let p = el.parentElement;
    while (p && p !== document.body) {
      const cs = getComputedStyle(p);
      if (cs.overflowX === 'auto' || cs.overflowX === 'scroll') return true;
      p = p.parentElement;
    }
    return false;
  };
  const outside = [];
  for (const el of qa('#app *')) {
    if (!vis(el) || inScroller(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 || r.left < -1) {
      outside.push({cls: (el.className || el.tagName).toString().slice(0, 50),
                    right: Math.round(r.right), left: Math.round(r.left)});
    }
  }
  const hdr = document.querySelector('header.header-sticky');
  // Прямые дети шапки: считаем РЯДЫ по их top (а не по всем потомкам).
  const direct = hdr ? Array.from(hdr.children).filter(vis) : [];
  // Ряд = группа элементов, чьи вертикальные диапазоны пересекаются.
  const boxes = direct.map((el) => el.getBoundingClientRect())
    .sort((a, b) => a.top - b.top);
  let lines = 0;
  let bottom = -1e9;
  for (const r of boxes) {
    if (r.top > bottom - 1) { lines += 1; bottom = r.bottom; }
    else { bottom = Math.max(bottom, r.bottom); }
  }
  let overlaps = 0;
  const rects = direct.map((el) => el.getBoundingClientRect());
  for (let i = 0; i < rects.length; i += 1) {
    for (let j = i + 1; j < rects.length; j += 1) {
      const ox = Math.min(rects[i].right, rects[j].right)
        - Math.max(rects[i].left, rects[j].left);
      const oy = Math.min(rects[i].bottom, rects[j].bottom)
        - Math.max(rects[i].top, rects[j].top);
      if (ox > 1 && oy > 1) overlaps += 1;
    }
  }
  // Видимая область: клавиатура в Telegram уменьшает именно её.
  const kb = parseFloat(getComputedStyle(de).getPropertyValue('--kb-offset')) || 0;
  const visibleBottom = Math.min(vh, vh - kb);
  const hit = (el) => {
    if (!el) return {found: false};
    el.scrollIntoView({block: 'center'});
    let r = el.getBoundingClientRect();
    // Если элемент оказался ниже видимой области (клавиатура уменьшила её),
    // пользователь докручивает — повторяем это и пересчитываем (§3: элемент
    // обязан быть ДОСТИЖИМ, а не «виден без прокрутки»).
    if (r.bottom > visibleBottom) {
      window.scrollBy(0, r.bottom - visibleBottom + 8);
      const sc = el.closest('.scroll-area, .modal-body, [class*="scroll"]');
      if (sc && sc.scrollBy) sc.scrollBy(0, r.bottom - visibleBottom + 8);
      r = el.getBoundingClientRect();
    }
    const cx = Math.min(Math.max(r.left + r.width / 2, 0), vw - 1);
    const cy = Math.min(Math.max(r.top + r.height / 2, 0), visibleBottom - 1);
    const top = document.elementFromPoint(cx, cy);
    return {
      found: true,
      cls: (el.className || el.tagName).toString().slice(0, 40),
      w: Math.round(r.width), h: Math.round(r.height),
      inside: r.left >= -1 && r.right <= vw + 1,
      inVisible: r.top >= -1 && r.bottom <= visibleBottom + 1,
      hittable: !!(top && (top === el || el.contains(top) || top.contains(el))),
    };
  };
  const pick = (sel) => qa(sel).find(vis) || null;
  const actions = {
    nav: hit(pick('[data-drawer-trigger]')),
    scope: hit(pick('.scope-trigger')),
    fullscreen: hit(pick('[data-fs-toggle]')),
    refresh: hit(pick('button[aria-label="Обновить"],'
                      + ' button[aria-label="Обновить данные"]')),
    back: hit(pick('.speech-back, [data-prompt-back], .breadcrumb-link')),
    save: hit(pick('[data-speech-save-primary], .speech-actions .btn-accent,'
                   + ' .sticky-save .btn-accent, .sticky-save button')
              || (qa('button').filter(vis)
                    .find((b) => /Сохранить/.test(b.textContent || '')) || null)),
  };
  // Тап-цели и шрифты: контракт §5 запрещает уменьшать их ради теста.
  const iconBtns = qa('[data-drawer-trigger], [data-fs-toggle], .breadcrumb-link,'
                      + ' .scope-trigger, .speech-area-nav__btn')
    .filter(vis).map((el) => {
      const r = el.getBoundingClientRect();
      return {cls: (el.className || '').toString().slice(0, 30),
              w: Math.round(r.width), h: Math.round(r.height),
              font: parseFloat(getComputedStyle(el).fontSize)};
    });
  // Доказательство reflow (а не сжатия): меняется состав/строки шапки,
  // профиль появляется в drawer, колонки контента перестраиваются.
  const moduleList = document.querySelector('.module-list');
  return {
    vw, vh, kb, visibleBottom,
    dpr: window.devicePixelRatio,
    rootFont: parseFloat(getComputedStyle(de).fontSize),
    docWidth: de.scrollWidth,
    hScroll: de.scrollWidth - vw,
    outsideCount: outside.length,
    outside: outside.slice(0, 6),
    fit: hdr ? hdr.getAttribute('data-header-fit') : null,
    headerHeight: hdr ? Math.round(hdr.getBoundingClientRect().height) : 0,
    headerLines: lines,
    headerOverlaps: overlaps,
    headerItems: direct.map((el) => (el.className || el.tagName).toString()
      .slice(0, 34)),
    scopeNameVisible: (() => {
      const el = document.querySelector('.scope-trigger .scope-name');
      return !!(el && vis(el));
    })(),
    roleVisible: (() => {
      const el = document.querySelector('.header-user-role');
      return !!(el && vis(el));
    })(),
    drawerProfile: qa('[data-drawer-profile]').length,
    actionHeights: iconBtns,
    moduleCols: moduleList
      ? getComputedStyle(moduleList).gridTemplateColumns.split(' ').length : null,
    actions,
    bottomNav: qa('.navbar-band, .bottom-nav, [data-bottom-nav]').filter(vis).length,
  };
}
"""

# Открыть drawer и проверить точку входа в поиск/палитру (реальный путь §2.3).
DRIVE_DRAWER = r"""
() => {
  const t = document.querySelector('[data-drawer-trigger]');
  if (!t) return {opened: false};
  t.click();
  return {opened: true};
}
"""
PROBE_DRAWER = r"""
() => {
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const vis = (el) => {
    if (!el) return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const drawer = document.querySelector('.app-drawer');
  const entry = qa('[data-palette-open-drawer]').find(vis);
  const profile = qa('[data-drawer-profile]').find(vis);
  const result = {drawerOpen: !!(drawer && drawer.classList.contains('open')),
                  entry: false, profile: false, drawerW: 0};
  if (!drawer) return result;
  result.drawerW = Math.round(drawer.getBoundingClientRect().width);
  const check = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(
      Math.min(Math.max(r.left + r.width / 2, 0), window.innerWidth - 1),
      Math.min(Math.max(r.top + r.height / 2, 0), window.innerHeight - 1));
    return !!(top && (top === el || el.contains(top)));
  };
  result.entry = check(entry);
  result.profile = !!(profile && check(profile));
  const close = document.querySelector('.drawer-backdrop');
  if (close) close.click();
  return result;
}
"""


def run_adaptive(report, fails, out_dir, port):
    """W16: адаптивность по контракту владельца (три режима масштаба).

    Возвращает словарь «режим/экран@ширина → измерение». Каждое утверждение
    привязано к пункту контракта (см. `clause` в отчёте и §1 контракта).
    """
    from playwright.sync_api import sync_playwright

    cells = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", port), W9._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/web/index.html" % port

    def screen_ctx(browser, css_w, css_h, mode):
        ctx = browser.new_context(viewport={"width": css_w, "height": css_h},
                                  device_scale_factor=2,
                                  is_mobile=True, has_touch=True)
        ctx.add_init_script(M.TMA_STUB)
        if mode == "font200":
            # Системное увеличение шрифта: rem-масштаб, ширина окна НЕ меняется.
            ctx.add_init_script(
                "document.addEventListener('DOMContentLoaded', () => {"
                " document.documentElement.style.fontSize = '32px'; });")
        ctx.route("**/api/**", _routes())
        return ctx

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for mode, mode_note in ADAPTIVE_MODES:
            for screen_w in ADAPTIVE_WIDTHS:
                # page zoom 200 % не вычисляется «делением» — это фактический
                # CSS-вьюпорт, который браузер отдаёт раскладке; ниже он
                # измеряется через window.innerWidth.
                css_w = screen_w // 2 if mode == "pagezoom200" else screen_w
                css_h = 640 if mode == "telegram_kb" else 800
                for screen in ADAPTIVE_SCREENS:
                    label = "adapt:%s/%s@%d" % (mode, screen["name"], css_w)
                    ctx = screen_ctx(browser, css_w, css_h, mode)
                    pg = ctx.new_page()
                    errs = []
                    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
                    pg.goto(base + "?ad=%s%d" % (mode, css_w) + screen["route"],
                            wait_until="load")
                    pg.wait_for_selector(".app-shell", timeout=25000)
                    pg.wait_for_timeout(1300)
                    if screen.get("driver"):
                        pg.evaluate(DRIVE, list(screen["driver"]))
                        pg.wait_for_timeout(1200)
                    if mode == "telegram_kb":
                        # Клавиатура Telegram уменьшает ВИДИМУЮ область: тот же
                        # существующий `--kb-offset`, что ставит
                        # `_syncKeyboardOffset` при реальной клавиатуре.
                        pg.evaluate("() => document.documentElement.style"
                                    ".setProperty('--kb-offset', '280px')")
                        pg.wait_for_timeout(250)
                    data = pg.evaluate(PROBE_ADAPTIVE)
                    # Палитра: реальный путь на телефоне — вход в drawer.
                    opened = pg.evaluate(DRIVE_DRAWER)
                    pg.wait_for_timeout(400)
                    drawer = pg.evaluate(PROBE_DRAWER)
                    pg.wait_for_timeout(200)
                    shot_name = "w16-adapt-%s-%s-%d.png" % (
                        mode, screen["name"], css_w)
                    try:
                        pg.screenshot(path=os.path.join(out_dir, shot_name))
                    except Exception:  # noqa: BLE001
                        shot_name = ""
                    cell = {"mode": mode, "modeNote": mode_note,
                            "screen": screen["name"], "screenWidth": screen_w,
                            "cssWidth": css_w, "cssHeight": css_h,
                            "need": list(screen["need"]),
                            "probe": data, "drawer": drawer,
                            "drawerOpened": opened,
                            "shot": shot_name,
                            "console": errs[-2:]}
                    cells[label] = cell

                    # ── §1/§2: нет обрезаний/overflow/наложений ────────────
                    if data["hScroll"] > 1:
                        fails.append("%s: горизонтальный overflow %d px"
                                     % (label, data["hScroll"]))
                    if data["outsideCount"] > 0:
                        fails.append("%s: за вьюпорт выходит %d элементов (%s)"
                                     % (label, data["outsideCount"],
                                        [o["cls"] for o in data["outside"][:3]]))
                    if data["headerOverlaps"]:
                        fails.append("%s: элементы шапки наложены (%d пар)"
                                     % (label, data["headerOverlaps"]))
                    # Измеренная ширина должна совпасть с заявленной (§6:
                    # никаких «рассчитали делением»).
                    if abs(data["vw"] - css_w) > 1:
                        fails.append("%s: измеренная ширина %d != ожидаемой %d"
                                     % (label, data["vw"], css_w))
                    if mode == "font200" and data["rootFont"] < 31:
                        fails.append("%s: системный шрифт не применён (%s)"
                                     % (label, data["rootFont"]))
                    # ── §4: никакого нижнего навбара ──────────────────────
                    if data["bottomNav"]:
                        fails.append("%s: появился нижний навбар" % label)
                    # ── §3: критические действия доступны ──────────────────
                    for act in screen["need"]:
                        if act == "palette_via_drawer":
                            if not (drawer.get("entry")
                                    or (opened and drawer.get("entry"))):
                                fails.append(
                                    "%s: вход в поиск/палитру недоступен через "
                                    "drawer (drawer=%s entry=%s)"
                                    % (label, drawer.get("drawerOpen"),
                                       drawer.get("entry")))
                            continue
                        info = data["actions"].get(act) or {}
                        if not info.get("found"):
                            fails.append("%s: критическое действие «%s» "
                                         "отсутствует" % (label, act))
                        elif not info.get("hittable"):
                            fails.append("%s: действие «%s» не нажимается"
                                         % (label, act))
                        elif not info.get("inside"):
                            fails.append("%s: действие «%s» вне вьюпорта"
                                         % (label, act))
                        elif mode == "telegram_kb" and not info.get("inVisible"):
                            fails.append("%s: действие «%s» скрыто клавиатурой"
                                         % (label, act))
                    # ── §5: тач-цели и шрифты не уменьшены ─────────────────
                    for el in data["actionHeights"]:
                        if el["h"] < 44:
                            fails.append("%s: тач-цель %s = %d px < 44"
                                         % (label, el["cls"], el["h"]))
                        if el["font"] < 11:
                            fails.append("%s: шрифт %s = %.1f px < 11 (не "
                                         "уменьшаем ради теста)"
                                         % (label, el["cls"], el["font"]))
                    # ── §2/§4: reflow реально произошёл, и на обычных
                    # мобильных размерах шапка остаётся ОДНОРЯДНОЙ ────────
                    if mode == "normal":
                        if (data["headerLines"] > 1
                                or (data["fit"] or "") == "stack"):
                            fails.append("%s: на обычном мобильном размере "
                                         "шапка стала многорядной (lines=%d "
                                         "fit=%s)" % (label, data["headerLines"],
                                                      data["fit"]))
                    if mode in ("pagezoom200", "font200"):
                        reflow = bool(data["fit"]) or data["headerLines"] > 1
                        if not reflow:
                            fails.append("%s: нет признаков reflow (fit=%s, "
                                         "рядов=%d) — проверка «сжатия»"
                                         % (label, data["fit"],
                                            data["headerLines"]))
                        if not data["drawerProfile"] and not data["roleVisible"]:
                            fails.append("%s: идентичность (имя/роль) недоступна "
                                         "ни в шапке, ни в drawer" % label)
                    if errs:
                        fails.append("%s: ошибка страницы: %s"
                                     % (label, errs[-1]))
                    ctx.close()
        browser.close()
    httpd.shutdown()
    report["adaptive"] = cells
    return cells


def run(out_dir, baseline=False, port=PORT):
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    fails = []
    report = {"states": {}, "tokens": {}, "screenshots": [], "fails": [],
              "coverage": {}}
    httpd = ThreadingHTTPServer(("127.0.0.1", port), W9._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/web/index.html" % port
    sel_all = list(CARD_SEL + ROW_SEL + DIVIDER_ROW_SEL + DENSE_ROW_SEL
                   + NOTICE_SEL)
    # что реально рендерилось хотя бы раз (по селектору) — для правила
    # «объявленный класс без экземпляров = отказ» (ревью 5.2).
    rendered = {sel: 0 for sel in sel_all}

    def shot(pg, name):
        path = os.path.join(out_dir, name + ".png")
        try:
            pg.screenshot(path=path, full_page=False)
            report["screenshots"].append(os.path.basename(path))
        except Exception:  # noqa: BLE001
            pass

    def measure(pg, label, name, route, drive, w, h, kind, errs,
                shot_prefix=None, extra=None):
        toks = pg.evaluate(PROBE_TOKENS, TOKEN_PROPS)
        comp = pg.evaluate(PROBE_COMPONENTS,
                           {"sel": sel_all, "skip": list(STATE_SKIP),
                            "semantic": list(SEMANTIC_BORDER)})
        charts = pg.evaluate(PROBE_CHARTS, list(CHART_SEL + TABLE_SEL))
        compos = pg.evaluate(PROBE_COMPOSITION)
        compos["sheetBottom"] = pg.evaluate(
            "() => document.documentElement.classList.contains('w9-sheet-bottom')")
        if not report["tokens"]:
            report["tokens"] = toks
        for sel, items in comp["classes"].items():
            rendered[sel] += sum(1 for it in items if not it["state"])
        cell = {"name": name, "route": route, "w": w, "h": h, "drive": drive,
                "kind": kind, "components": comp, "charts": charts,
                "composition": compos, "console": errs[-3:]}
        if extra:
            cell.update(extra)
        report["states"][label] = cell
        if shot_prefix:
            shot(pg, shot_prefix)
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
        return cell

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
                errs.clear()
                pg.goto(base + "?w15=%d" % idx + route, wait_until="load")
                pg.wait_for_selector(".app-shell", timeout=25000)
                pg.wait_for_timeout(1200)
                if drive and drive[0] == "global":
                    S12._to_global(pg, wait=1000)
                elif drive and drive[0] == 'card+mode':
                    card_id, mode = str(drive[1]).split('|')
                    pg.evaluate(DRIVE, ["back", None])
                    pg.wait_for_timeout(700)
                    pg.evaluate(DRIVE, ["card", card_id])
                    pg.wait_for_timeout(1600)
                    pg.click('[data-inspector-mode="%s"]' % mode, timeout=8000)
                    pg.wait_for_timeout(900)
                elif drive and drive[0] == 'card':
                    pg.evaluate(DRIVE, ["back", None])
                    pg.wait_for_timeout(700)
                    pg.evaluate(DRIVE, list(drive))
                    pg.wait_for_timeout(1900)
                elif drive and drive[0] == 'oversight' and '>' in str(drive[1]):
                    seq = str(drive[1]).split('>')
                    for part in seq:
                        pg.evaluate(DRIVE, ['oversight', part])
                        pg.wait_for_timeout(1500)
                elif drive:
                    pg.evaluate(DRIVE, list(drive))
                    # Разделы речи/вкладки подгружают данные по клику: пауза
                    # должна вмещать реальный запрос, иначе плотные строки
                    # «не рендерятся» ложно.
                    pg.wait_for_timeout(1900)
                cell = measure(pg, label, name, route, drive, w, h, "composition",
                               errs, shot_prefix="w15-%s-%d" % (name, w))
                if name == "status":
                    # Живая проверка графика сердцебиения: причина и свежесть
                    # доступны пользователю (tooltip по клику/Enter), а не
                    # только в разметке. Тот же путь, что у пользователя.
                    tip = ""
                    aria = cell["composition"].get("hbAria") or ""
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
                    cell["hb"] = {"tip": tip, "aria": aria}
                    if not tip:
                        fails.append("%s: tooltip сердцебиения не открывается"
                                     % label)
                    elif "Обновлено" not in tip:
                        fails.append("%s: в tooltip сердцебиения нет свежести "
                                     "измерения: %s" % (label, tip[:80]))
                    if not aria:
                        fails.append("%s: у графика сердцебиения нет aria-label"
                                     % label)
            # Маршруты §D-7 вне STATES: та же сигнатура компонентов и те же
            # регрессии; кадр — только 1280 (компактность доказательств).
            for idx, (route, name) in enumerate(COVERAGE_ROUTES):
                label = "%s@%d" % (name, w)
                errs.clear()
                pg.goto(base + "?w15c=%d" % idx + route, wait_until="load")
                pg.wait_for_selector(".app-shell", timeout=25000)
                pg.wait_for_timeout(1000)
                report["coverage"].setdefault(route, []).append(w)
                measure(pg, label, name, route, None, w, h, "coverage", errs,
                        shot_prefix=("w15-cov-%s" % name) if w >= 1280 else None)
            ctx.close()
        browser.close()
    httpd.shutdown()

    # ── W16: адаптивность узкого вьюпорта (контракт владельца 02.11.2026) ───
    run_adaptive(report, fails, out_dir, port + 9)

    # ── 0. Ни один объявленный класс не имеет права «молча» отсутствовать ───
    for sel, n in sorted(rendered.items()):
        if n == 0:
            fails.append("селектор %s: 0 экземпляров во всех %d состояниях — "
                         "объявленный компонент обязан рендериться (или быть "
                         "убраным из набора)" % (sel, len(report["states"])))
    report["rendered_counts"] = rendered

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
        if radii and radii != {row_r}:
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

    # Каждый объявленный график обязан хотя бы раз отрендериться С ДАННЫМИ, а не
    # только честным пустым состоянием (иначе проверка вакуумна — ревью 5.2).
    for sel in CHART_SEL:
        seen = 0
        with_data = 0
        for label, st in report["states"].items():
            for it in st["charts"]:
                if it["sel"] != sel:
                    continue
                seen += 1
                if not it["empty"] and it["drill"] > 0:
                    with_data += 1
        if seen == 0:
            fails.append("график %s: 0 экземпляров во всех состояниях" % sel)
        elif with_data == 0:
            fails.append("график %s: ни разу не отрендерился с данными "
                         "(только пустое состояние) — проверка вакуумна" % sel)
    for sel in TABLE_SEL:
        n = sum(1 for st in report["states"].values()
                for it in st["charts"] if it["sel"] == sel)
        if n == 0:
            fails.append("таблица %s: 0 экземпляров во всех состояниях" % sel)

    # ── 2b. Уведомления/заметки: геометрия роли, цвет кромки — семантический ─
    for sel in NOTICE_SEL:
        radii = set(collect(sel, "radius"))
        if radii and radii != {tbl_r}:
            fails.append("заметка %s: радиус %s != --table-row-radius %s"
                         % (sel, sorted(radii), tbl_r))
        padl = set(collect(sel, "padLeft"))
        if padl and padl != {tbl_pad["l"]}:
            fails.append("заметка %s: padding %s != --table-row-pad %s"
                         % (sel, sorted(padl), tbl_pad["l"]))

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
    report["summary"] = {
        "composition_states": len(STATES),
        "coverage_routes": len(COVERAGE_ROUTES),
        "viewports": len(VIEWPORTS),
        "measured_cells": len(report["states"]),
        "selectors": len(sel_all),
        "selectors_rendered": sum(1 for n in rendered.values() if n > 0),
        "instances": sum(rendered.values()),
        "chart_selectors": len(CHART_SEL),
        "table_selectors": len(TABLE_SEL),
        "adaptive_cells": len(report.get("adaptive") or {}),
        "adaptive_modes": len(ADAPTIVE_MODES),
        "adaptive_widths": len(ADAPTIVE_WIDTHS),
    }
    out_json = os.path.join(
        out_dir, "w15-composition%s.json" % ("-before" if baseline else ""))
    with io.open(out_json, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    print("W15 %s" % json.dumps(report["summary"], ensure_ascii=False))
    for f in fails[:40]:
        print(" -", f)
    if fails and not baseline:
        print("EVOL-W15-COMPOSITION FAIL")
        return 1
    print("EVOL-W15-COMPOSITION OK" if not fails else
          "EVOL-W15-COMPOSITION BASELINE (fails recorded: %d)" % len(fails))
    return 0


# ── короткие видео (§E.1/§E.4): переходы/анимации и преломление стекла ──────
VIDEO_SCENARIOS = (
    {
        "name": "w15-video-transitions-desktop-1280",
        "viewport": (1280, 900), "mobile": False, "seconds": 9,
        "steps": (
            ("goto", "#/"),
            ("wait", 1500),
            # палитра (Ctrl+K): открытие, ввод, Esc
            ("press", "Control+k"), ("wait", 700),
            ("type", "input[data-command-palette], .palette-panel input", "память"),
            ("wait", 500),
            ("press", "Escape"), ("wait", 500),
            # модалка записи досье на «Статусе» — открыть и закрыть
            ("click", "[data-status-dossier] .dossier-ticker__item"),
            ("wait", 1300),
            ("press", "Escape"), ("wait", 600),
            # ленты: ручная прокрутка вверх/вниз
            ("scroll", "[data-sfeed-viewport]", 260),
            ("wait", 900),
            ("scroll", "[data-sfeed-viewport]", -160),
            ("wait", 900),
        ),
    },
    {
        "name": "w15-video-transitions-mobile-390",
        "viewport": (390, 844), "mobile": True, "seconds": 9,
        "steps": (
            ("goto", "#/modules"),
            ("wait", 1500),
            # drawer: открыть, выбрать раздел, закрыть
            ("click", "[data-drawer-trigger]"),
            ("wait", 900),
            ("press", "Escape"), ("wait", 700),
            # каталог модулей: фильтр и один тумблер (в GLOBAL)
            ("click", ".module-filter-btn:nth-of-type(2)"),
            ("wait", 900),
            # раздел речи: переключение областей
            ("goto", "#/ai/speech"),
            ("wait", 1400),
            ("click", "[data-speech-area-nav] .speech-area-nav__btn:nth-of-type(2)"),
            ("wait", 1400),
        ),
    },
    {
        # Преломление видно там, где за стеклянной кромкой есть движущаяся сцена:
        # каталог модулей = две карточки над полигональным фоном. Ведём мышь по
        # кромке (specular/линза) и медленно прокручиваем сцену под стеклом.
        "name": "w15-video-refraction-desktop-1280",
        "viewport": (1280, 900), "mobile": False, "seconds": 9,
        "steps": (
            ("goto", "#/modules"),
            ("wait", 2600),
            ("move", 640, 300),
            ("wait", 900),
            ("move", 300, 360),
            ("wait", 900),
            ("move", 1000, 420),
            ("wait", 900),
            ("scroll", "main, .scroll-area", 140),
            ("wait", 1500),
            ("scroll", "main, .scroll-area", -140),
            ("wait", 1500),
        ),
    },
)


def run_refraction_probe(out_dir, port=PORT + 6):
    """Измерение преломления: один и тот же кадр с живым слоем и без него.

    Скриншот сам по себе ничего не доказывает (стекло может быть простым
    blur): сравниваем ОДИН участок сцены в двух прогонах — обычный материал и
    явно выключенный вендорный Liquid Glass (`ME_GLASS_OFF`). Разница пикселей
    в одном и том же регионе = слой реально влияет на картинку.
    """
    from playwright.sync_api import sync_playwright
    from PIL import Image, ImageChops

    os.makedirs(out_dir, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), W9._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/web/index.html" % port
    # Полоса по кромке карточки: линза работает на краю, а не в центре.
    clip = {"x": 240, "y": 170, "width": 720, "height": 60}
    shots = {}
    meta = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        for tag, me in (("on", M.ME_JSON), ("off", M.ME_JSON)):
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_init_script(M.TMA_STUB)
            ctx.route("**/api/**", _routes(me=me))
            pg = ctx.new_page()
            pg.goto(base + "#/modules", wait_until="load")
            pg.wait_for_selector(".app-shell", timeout=25000)
            pg.wait_for_timeout(3200)
            if tag == "off":
                # Контрольная проба: останавливаем СЛОЙ ПРЕЛОМЛЕНИЯ (не флаг
                # декоративной библиотеки — он гейтит другой модуль) и даём
                # кадру перерисоваться без линзы.
                pg.evaluate("() => { const g = window.__GlassRefraction;"
                            " if (g && g.stop) { g.stop(); return true; }"
                            " return false; }")
                pg.wait_for_timeout(1200)
            meta[tag] = {
                "lgRefractCanvases": pg.evaluate(
                    "() => document.querySelectorAll('canvas.lg-refract').length"),
                "liquidGlassLib": pg.evaluate(
                    "() => { const vm = window.__adminbotVm;"
                    " return vm ? !!vm.liquidGlassLib : null; }"),
                "glassStats": pg.evaluate(
                    "() => { const g = window.__GlassRefraction;"
                    " return g && typeof g.stats === 'function'"
                    " ? g.stats() : null; }"),
                "tierA": pg.evaluate(
                    "() => document.querySelectorAll("
                    "'[data-glass-tier=\"a\"]').length"),
                "refractLayer": pg.evaluate(
                    "() => document.documentElement.getAttribute("
                    "'data-refract-layer')"),
            }
            path = os.path.join(out_dir, "w15-refraction-%s.png" % tag)
            pg.screenshot(path=path, clip=clip)
            shots[tag] = path
            ctx.close()
        browser.close()
    httpd.shutdown()

    a = Image.open(shots["on"]).convert("RGB")
    b = Image.open(shots["off"]).convert("RGB")
    diff = ImageChops.difference(a, b)
    px = list(diff.getdata())
    total = len(px)
    changed = sum(1 for r, g, bl in px if max(r, g, bl) > 8)
    mean = sum((r + g + bl) / 3.0 for r, g, bl in px) / max(1, total)
    maxd = max((max(r, g, bl) for r, g, bl in px), default=0)
    stats = {
        "clip": clip, "viewport": {"width": 1440, "height": 900},
        "route": "#/modules",
        "materialOn": meta.get("on"), "materialOff": meta.get("off"),
        "changedPercent": round(100.0 * changed / max(1, total), 2),
        "meanDelta": round(mean, 2), "maxDelta": maxd,
        "shots": {k: os.path.basename(v) for k, v in shots.items()},
    }
    with io.open(os.path.join(out_dir, "w15-refraction.json"), "w",
                 encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=1)
    print("[refraction] %s" % json.dumps(stats, ensure_ascii=False))
    return stats


def run_videos(out_dir, port=PORT + 5):
    """Записывает короткие .webm тем же стендом (реальный Chromium, стабы API).

    Возвращает список путей. Кодирование — встроенный ffmpeg Playwright.
    """
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), W9._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/web/index.html" % port
    made = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for scen in VIDEO_SCENARIOS:
            w, h = scen["viewport"]
            vdir = os.path.join(out_dir, "_raw_" + scen["name"])
            ctx = browser.new_context(viewport={"width": w, "height": h},
                                      record_video_dir=vdir,
                                      record_video_size={"width": w, "height": h},
                                      device_scale_factor=1,
                                      is_mobile=scen["mobile"],
                                      has_touch=scen["mobile"])
            ctx.add_init_script(M.TMA_STUB)
            ctx.route("**/api/**", _routes())
            pg = ctx.new_page()
            try:
                frames = []
                for step in scen["steps"]:
                    kind = step[0]
                    try:
                        if kind == "goto":
                            pg.goto(base + step[1], wait_until="load")
                            pg.wait_for_selector(".app-shell", timeout=20000)
                        elif kind == "wait":
                            pg.wait_for_timeout(step[1])
                        elif kind == "press":
                            pg.keyboard.press(step[1])
                        elif kind == "type":
                            pg.fill(step[1], step[2], timeout=6000)
                        elif kind == "click":
                            pg.click(step[1], timeout=6000)
                        elif kind == "move":
                            pg.mouse.move(step[1], step[2], steps=12)
                        elif kind == "scroll":
                            pg.evaluate(
                                "(spec) => { const el = document.querySelector(spec[0]);"
                                " if (el) el.scrollTop += spec[1]; }",
                                [step[1], step[2]])
                        frame = os.path.join(
                            out_dir, "%s-step%02d.jpg" % (scen["name"], len(frames)))
                        pg.screenshot(path=frame, type="jpeg", quality=80)
                        frames.append(frame)
                    except Exception as exc:  # noqa: BLE001
                        print("[video] шаг %s пропущен: %s" % (kind, exc))
                pg.wait_for_timeout(800)
            finally:
                video = pg.video
                ctx.close()
                if video:
                    src = video.path()
                    dst = os.path.join(out_dir, scen["name"] + ".webm")
                    try:
                        os.replace(src, dst)
                    except Exception:  # noqa: BLE001
                        import shutil
                        shutil.move(src, dst)
                    made.append(dst)
                    print("[video] %s (viewport %dx%d, ~%d c), кадров %d"
                          % (dst, w, h, scen["seconds"], len(frames)))
        browser.close()
    httpd.shutdown()
    return made


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
    ap.add_argument("--video", action="store_true",
                    help="записать короткие видео (переходы/анимации и "
                         "преломление стекла) в <out>/video")
    args = ap.parse_args()
    if args.video:
        run_videos(os.path.join(args.out, "video"), port=args.port + 5)
        run_refraction_probe(os.path.join(args.out, "video"),
                             port=args.port + 7)
        return 0
    return run(args.out, baseline=args.baseline, port=args.port)


if __name__ == "__main__":
    sys.exit(main())
