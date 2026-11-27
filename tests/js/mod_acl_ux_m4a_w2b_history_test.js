'use strict';
/* MOD-ACL-UX-01 M4A W2b (B1 2.58.212 + B2 2.58.213 + B3 2.58.214) — «История».

Предмет: B1 `memory.dream.log` + `memory.nostalgia.log`, B2
`factcheck.temporal.runs` + `memory.lessons`, B3 `oversight:summary` +
`oversight:random.uses` на СУЩЕСТВУЮЩИХ read-API (brief W2b §2–§3, контракты
H-1…H-7):
  1) presentation-map HISTORY_SOURCES: dream/nostalgia/factcheck/lessons/
     summary/random.uses; неизвестный source — ни запроса, ни вкладки
     (fail-closed); `summary.window` — НЕ источник (компонентные события окна
     без `pipeline_run_id`, F1);
  2) одно состояние на `scopeKey + moduleId` (`idle|loading|ready|empty|
     denied|off|unavailable|error`): 403 → denied, 503 → unavailable
     (сервис временно недоступен, журнал остаётся с повтором),
     available:false/enabled:false → off (функция выключена), сеть → error;
     никогда «0 событий» вместо 403; 503 и disabled различаются текстом;
  3) вкладка `history` видна ТОЛЬКО при `status==='ready' && rows>0`;
     объявлена у sleep/nostalgia/factcheck/experience/summary/random;
  4) `history` никогда не дефолт; pending не удаляет запомненный history,
     удаление — только при empty/denied/off;
  5) `moduleLastEventState` для этих модулей — max(ts) своего источника,
     `observed_at` активностью не становится, чужая область не подставляется;
  6) один автоматический фетч на источник (`_ensureModuleData`), без поллера;
     явное обновление остаётся возможным;
  7) B2/D2: конверт уроков `{enabled,state,count}` → строка
     «записей в журнале: N (<RU-состояние>)»,
     detail прогона фактчека — только по run_id (существующая модалка);
  8) B3: прогоны `summary`/`random.uses` через
     `GET /api/oversight/runs?pipeline_type=…&limit=20` (global admin),
     detail — существующий deep link `#/oversight?view=runs&run_id=`;
     30-с кэш scope-aware + epoch-guard; строки источников не смешиваются;
  9) статические срезы: панель `data-module-history`, фильтр, ровно один ряд
     `[data-workspace-chips]`, `[data-overview-chips]` удалён.

Всё проверяется на РЕАЛЬНОМ `web/app.js` (Vue-опции перехватываются),
каталог — из того же снимка DTO, что у остальных M4A-юнитов.

Запуск: node tests/js/mod_acl_ux_m4a_w2b_history_test.js
*/
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const INDEX_HTML = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_CSS = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
const _storage = {
  _s: {},
  getItem(k) {
    return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null;
  },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; }, localStorage: _storage,
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
  querySelector() { return null; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');

const { applyModuleDto } = require('./module_fixture.js');
const data = applyModuleDto(captured);
const methods = captured.methods;
const computed = captured.computed;
const MODULES = data.modules;
const TABS = data.tabs;
const MEMORY_KEY = 'adminbot.module_tab';

const SLEEP_SOURCE = 'memory.dream.log';
const NOSTALGIA_SOURCE = 'memory.nostalgia.log';
const SUMMARY_SOURCE = 'oversight:summary';
const LEGACY_SUMMARY_SOURCE = 'oversight:summary.window';   // НЕ источник
const RANDOM_SOURCE = 'oversight:random.uses';
const SLEEP = moduleById('mod_sleep');
const NOSTALGIA = moduleById('mod_nostalgia');
const FACTCHECK = moduleById('mod_factcheck');
const EXPERIENCE = moduleById('mod_experience');
const SUMMARY = moduleById('mod_summary');
const RANDOM = moduleById('mod_random');
const HISTORY_MODULES = ['mod_sleep', 'mod_nostalgia', 'mod_factcheck',
  'mod_experience', 'mod_summary', 'mod_random'];

function moduleById(id) {
  return MODULES.filter(function (m) { return m.id === id; })[0];
}
function clearStorage() {
  Object.keys(_storage._s).forEach(function (k) { delete _storage._s[k]; });
}
function memoryRaw() {
  const raw = _storage._s[MEMORY_KEY];
  return raw ? JSON.parse(raw) : null;
}
function deferred() {
  let resolve;
  let reject;
  const p = new Promise(function (res, rej) { resolve = res; reject = rej; });
  return { p: p, resolve: resolve, reject: reject };
}
function tick() {
  return new Promise(function (resolve) { setImmediate(resolve); });
}
function dreamRow(id, ts, status, kind) {
  return { id: id, chat_id: -100, run_at: ts, kind: kind || 'dream',
           status: status || 'ok' };
}
function nostalgiaRow(id, ts, status, reason) {
  return { id: id, chat_id: -100, ts: ts, kind: 'nostalgia',
           status: status || 'sent',
           meta: reason ? { reason: reason } : null };
}
// B2: компактный прогон временного фактчека / строка урока.
function temporalRow(id, ts, chat, mode, verdict) {
  return { run_id: id, created_at: ts,
           chat_id: (chat === undefined ? -100 : chat),
           assessment_mode: mode || 'contextual',
           factual_verdict: verdict || 'supported' };
}
function lessonRow(id, version, at, status, type, scope, scopeChat) {
  return { lesson_id: id, version: version || 1,
           created_at: at, updated_at: at,
           type: type || 'tool_usage', status: status || 'active',
           scope: scope || 'chat',
           scope_chat_id: (scopeChat === undefined ? -100 : scopeChat) };
}
// B3: хедер прогона oversight (`GET /api/oversight/runs` → runs[]).
// F1: реальный тип прогонов Summary — `summary` (pipeline_events.py несёт
// `span_fields(run_id, pipeline_type="summary")`); `summary.window` —
// компонентные события окна без `pipeline_run_id`, источником истории не
// является.
function runRow(id, ts, type, status, chat) {
  return { pipeline_run_id: id, pipeline_type: type || 'summary',
           pipeline_version: '1', status: status || 'succeeded',
           started_ts: ts, updated_ts: ts + 4,
           events_total: 3, stages_total: 2, stages_failed: 0, stages_ok: 2,
           chat_id: (chat === undefined ? -100 : chat) };
}

// Контекст «как на странице»: методы app.js + минимальные данные scope.
function mkCtx(overrides) {
  const ctx = Object.assign({}, methods, {
    modules: MODULES,
    tabs: TABS,
    route: '#/modules/sleep',
    activeTab: 'mod_sleep',
    activeChatId: -100,
    scopeKind: 'chat',
    scopeEpoch: 0,
    configItems: [{ key: 'stub.item', value: true }],
    configGroups: [],
    workspaceModelGroups: [],
    workspaceTestingBlocks: [],
    moduleTabMemory: {},
    historyMeta: {},
    historyFilter: '',
    dreamLog: [],
    nostalgiaLog: [],
    dreamBeliefs: [{ id: 1 }],
    memoryRagBusy: false,
    temporalRuns: [],
    temporalRunsBusy: false,
    temporalRunsAt: 0,
    temporalRunsScope: '',
    temporalRunsEpoch: null,
    temporalDetail: null,
    temporalDetailBusy: false,
    lessonsData: null,
    lessonsBusy: false,
    // B3: прогоны oversight по источнику + 30-с кэш своей области/epoch.
    moduleRuns: {},
    moduleRunsCache: {},
    moduleRunsBusy: {},
    // B3: словарь имён процессов (data() в app.js) — человеческий тип строки.
    vizProcessNames: {
      'summary.window': 'Окно и краткое резюме',
      'random.uses': 'Применения случайности',
    },
    mca17cFunnel: { enabled: false },
    lessonCard: null,
    lessonDraft: { applicability: '', exceptions: '' },
    isGlobalAdmin: true,
    toasts: [],
    toast: function (msg, kind) { this.toasts.push({ msg: msg, kind: kind }); },
    moduleScopeErrorFor: function () { return ''; },
    moduleHealthView: function () { return null; },
    navigateTo: function (r) { this.nav = r; },
    _dirtyLeaveGuard: function () { return true; },
    _memeDraftLeaveGuard: function () { return true; },
    syncActiveChatTitle: function () {},
    loadConfig: function () { this.loads = (this.loads || 0) + 1; },
    loadKeyStatus: function () {},
    iniResetChatScope: function () {},
    resetSpeechState: function () {},
    applyRoute: function (r) {
      this.applied = (this.applied || []).concat([r]);
    },
  }, overrides || {});
  ['workspace', 'workspaceTab', 'workspaceTabs'].forEach(function (name) {
    Object.defineProperty(ctx, name, {
      configurable: true,
      get: function () { return computed[name].call(this); },
    });
  });
  return ctx;
}
function setMeta(ctx, m, status, rows) {
  methods._wsHistoryMetaSet.call(ctx, m, status,
    (rows == null) ? undefined : { rows: rows });
}
function addRows(ctx, m, rows) {
  setMeta(ctx, m, rows.length ? 'ready' : 'empty', rows.length);
  if (m.id === 'mod_sleep') ctx.dreamLog = rows;
  else ctx.nostalgiaLog = rows;
}

let checks = 0;
function ok(cond, msg) {
  assert.ok(cond, msg);
  checks += 1;
}
function eq(a, b, msg) {
  assert.strictEqual(a, b, msg);
  checks += 1;
}

(async function run() {
  // ══ (1) Статические срезы W2b-B1/B2/B3 ═════════════════════════════════
  {
    // history объявлена ТОЛЬКО у модулей с поддержанным источником
    // B1/B2/B3 (шесть источников H-1).
    [SLEEP, NOSTALGIA, FACTCHECK, EXPERIENCE, SUMMARY, RANDOM]
      .forEach(function (m) {
        ok(m, m && m.id ? m.id + ': модуль отсутствует в DTO'
          : 'модуль отсутствует в DTO');
        ok((m.tabs || []).indexOf('history') >= 0,
          m.id + ': history не объявлена в tabs');
      });
    MODULES.forEach(function (m) {
      if (HISTORY_MODULES.indexOf(m.id) >= 0) return;
      ok((m.tabs || []).indexOf('history') < 0,
        m.id + ': history не должна быть объявлена');
    });
    ok(APP_JS.indexOf('history: \'История\'') >= 0,
      'подпись history: «История» отсутствует');
    ok(APP_JS.indexOf('historyMeta: {}') >= 0,
      'data(): historyMeta отсутствует');
    ok(APP_JS.indexOf('HISTORY_SOURCES') >= 0 &&
       APP_JS.indexOf('memory.dream.log') >= 0 &&
       APP_JS.indexOf('memory.nostalgia.log') >= 0 &&
       APP_JS.indexOf('factcheck.temporal.runs') >= 0 &&
       APP_JS.indexOf('memory.lessons') >= 0 &&
       APP_JS.indexOf("'oversight:summary'") >= 0 &&
       APP_JS.indexOf('oversight:random.uses') >= 0,
      'HISTORY_SOURCES не содержит все шесть источников H-1');
    // F1: старый синтетический ключ и его pipeline_type отсутствуют в карте.
    ok(APP_JS.indexOf("'oversight:summary.window'") < 0,
      'F1: HISTORY_SOURCES всё ещё содержит oversight:summary.window');
    ok(APP_JS.indexOf('pipeline_type=summary.window') < 0,
      'F1: в коде остался запрос pipeline_type=summary.window');
    // B2: журнал фактчека (detail по run_id) и конверт уроков.
    ['data-factcheck-temporal', 'data-experience-history',
     'data-module-history-count', 'записей в журнале: '].forEach(function (needle) {
      ok(APP_JS.indexOf(needle) >= 0 || INDEX_HTML.indexOf(needle) >= 0,
        'B2: нет «' + needle + '»');
    });
    // B3: адреса обзорных блоков сводок/случайности и deep link прогона.
    ['data-summary-runs', 'data-random-runs', 'data-history-run-link']
      .forEach(function (needle) {
        ok(INDEX_HTML.indexOf(needle) >= 0,
          'B3 index.html: нет «' + needle + '»');
      });
    ok(APP_JS.indexOf('#/oversight?view=runs&run_id=') >= 0,
      'B3: deep link прогона отсутствует');
    ok(APP_JS.indexOf('mod_random: [\'overview\', \'settings\', \'history\']')
       >= 0, 'B3: у mod_random нет собственной карты вкладок с history');
    // Панель Истории, фильтр, честные состояния, обзорный блок.
    ['data-module-history', 'data-module-history-filter',
     'data-module-history-row', 'data-module-history-state',
     'data-overview-history', 'data-overview-history-row',
     'Загружаем историю…'].forEach(function (needle) {
      ok(INDEX_HTML.indexOf(needle) >= 0,
        'index.html: нет «' + needle + '»');
    });
    // F3: один вход в Историю — generic `[data-overview-link]`, без
    // собственной CTA, дублирующей ссылку.
    ok(INDEX_HTML.indexOf('data-overview-history-open') < 0,
      'index.html: осталась дублирующая CTA Истории');
    // H-6: дубль ряда чипов удалён, авторитетный ряд — один.
    eq((INDEX_HTML.match(/data-workspace-chips/g) || []).length, 1,
      'должен остаться РОВНО один ряд [data-workspace-chips]');
    eq((INDEX_HTML.match(/data-overview-chips/g) || []).length, 0,
      'дубль [data-overview-chips] не удалён');
    // CSS журнала добавлен; сетка/плотность/бейджи wave 1 не переписаны.
    ['.module-history__row', '.module-history__filter',
     '.module-history__status'].forEach(function (sel) {
      ok(APP_CSS.indexOf(sel) >= 0, 'app.css: нет ' + sel);
    });
  }

  // ══ (2) H-1/H-3: state machine одного источника ═══════════════════════
  {
    clearStorage();
    const ctx = mkCtx();
    eq(methods.historyStateFor.call(ctx, SLEEP), 'idle',
      'начальное состояние должно быть idle');
    ok(!methods.workspaceTabHasContent.call(ctx, SLEEP, 'history'),
      'idle: вкладка истории не рендерится');

    const d = deferred();
    ctx.api = function () { return d.p; };
    const load = methods.loadDreamLog.call(ctx);
    eq(methods.historyStateFor.call(ctx, SLEEP), 'loading',
      'в полёте состояние должно быть loading');
    ok(!methods.workspaceTabHasContent.call(ctx, SLEEP, 'history'),
      'loading: вкладка истории не рендерится');

    d.resolve([dreamRow(1, 1700000000, 'ok'), dreamRow(2, 1700000100, 'error')]);
    await load;
    eq(methods.historyStateFor.call(ctx, SLEEP), 'ready',
      '200 с данными → ready');
    eq(methods.historyRowsFor.call(ctx, SLEEP).length, 2,
      'ready: строки своего журнала');
    ok(methods.workspaceTabHasContent.call(ctx, SLEEP, 'history'),
      'ready+rows: вкладка истории рендерится');
    eq(methods.historyStateFor.call(ctx, NOSTALGIA), 'idle',
      'чужой модуль/источник не получает состояние sleep');
    eq(methods.historyRowsFor.call(ctx, NOSTALGIA).length, 0,
      'чужой модуль не получает строки sleep');
  }

  {
    // H-3: поздний ответ ЧУЖОЙ области не применяется (scopeEpoch guard):
    // ключ `scope|module` сменился, старые строки не выдаются за новые.
    const ctx = mkCtx({ scopeEpoch: 0 });
    const d = deferred();
    ctx.api = function () { return d.p; };
    const load = methods.loadDreamLog.call(ctx);
    eq(methods.historyStateFor.call(ctx, SLEEP), 'loading',
      'старая область: loading');
    ctx.activeChatId = -200;
    ctx.scopeEpoch += 1;                 // как setActiveChat
    d.resolve([dreamRow(1, 1700000000, 'ok')]);
    await load;
    eq(methods.historyStateFor.call(ctx, SLEEP), 'idle',
      'поздний ответ старой области не применён к новой');
    eq(methods.historyRowsFor.call(ctx, SLEEP).length, 0,
      'строки чужой области не подставлены');
  }

  {
    // empty: пустой массив — вкладки нет, но это честное «записей нет».
    const ctx = mkCtx();
    ctx.api = async function () { return []; };
    await methods.loadDreamLog.call(ctx);
    eq(methods.historyStateFor.call(ctx, SLEEP), 'empty', '[] → empty');
    eq(methods.historyRowsFor.call(ctx, SLEEP).length, 0, 'empty: нет строк');
    ok(!methods.workspaceTabHasContent.call(ctx, SLEEP, 'history'),
      'empty: вкладки истории нет');
    eq(ctx.toasts.length, 0, 'empty не показывает тост');
  }

  {
    // 403 → denied (не «0 событий»), без тоста.
    const ctx = mkCtx();
    ctx.api = async function () {
      const e = new Error('forbidden');
      e.status = 403;
      throw e;
    };
    await methods.loadDreamLog.call(ctx);
    eq(methods.historyStateFor.call(ctx, SLEEP), 'denied', '403 → denied');
    ok(!methods.workspaceTabHasContent.call(ctx, SLEEP, 'history'),
      'denied: вкладки истории нет');
    eq(ctx.toasts.length, 0, '403 не показывает тост');
    ok(methods.historyStateText.call(ctx, SLEEP).indexOf('0 событий') < 0,
      '403 не превращается в выдуманные «0 событий»');
  }

  {
    // 503 → unavailable (сервис временно недоступен, НЕ «функция выключена»);
    // 200 available:false → off; сеть → error.
    const ctx = mkCtx();
    ctx.api = async function () {
      const e = new Error('unavailable');
      e.status = 503;
      throw e;
    };
    await methods.loadDreamLog.call(ctx);
    eq(methods.historyStateFor.call(ctx, SLEEP), 'unavailable',
      '503 → unavailable');
    ok(methods.historyStateText.call(ctx, SLEEP).indexOf('503') >= 0,
      '503: причина называет код (503): '
      + methods.historyStateText.call(ctx, SLEEP));
    eq(ctx.toasts.length, 0, '503 не показывает тост');

    const ctx2 = mkCtx();
    ctx2.api = async function () { return { available: false }; };
    await methods.loadDreamLog.call(ctx2);
    eq(methods.historyStateFor.call(ctx2, SLEEP), 'off',
      'available:false → off');
    ok(!methods.workspaceTabHasContent.call(ctx2, SLEEP, 'history'),
      'available:false: вкладки истории нет');

    const ctx3 = mkCtx();
    ctx3.api = async function () { throw new Error('network down'); };
    await methods.loadDreamLog.call(ctx3);
    eq(methods.historyStateFor.call(ctx3, SLEEP), 'error',
      'сеть → error');
    ok(!methods.workspaceTabHasContent.call(ctx3, SLEEP, 'history'),
      'error: вкладки истории нет');
    eq(ctx3.toasts.length, 1, 'сеть: остаётся честный тост ошибки');
  }

  {
    // Nostalgia-источник проходит ту же машину состояний.
    const ctx = mkCtx({ route: '#/modules/nostalgia', activeTab: 'mod_nostalgia' });
    ctx.api = async function () { return [nostalgiaRow(9, 1700000200, 'sent', '')]; };
    await methods.loadNostalgiaLog.call(ctx);
    eq(methods.historyStateFor.call(ctx, NOSTALGIA), 'ready',
      'nostalgia 200 → ready');
    ok(methods.workspaceTabHasContent.call(ctx, NOSTALGIA, 'history'),
      'nostalgia ready+rows: вкладка есть');
    eq(methods.historyRowsFor.call(ctx, NOSTALGIA)[0].id, 9,
      'nostalgia: строка своего журнала');
  }

  // ══ (3) H-1 fail-closed: неизвестный source — 0 запросов и 0 вкладок ══
  {
    const ghost = {
      id: 'mod_sleep', routeSlug: 'sleep', title: 'Сон',
      tabs: ['overview', 'settings', 'history'],
      historySource: 'memory.unknown',
    };
    const ctx = mkCtx({ modules: MODULES.concat([ghost]) });
    let calls = 0;
    ctx.api = async function () { calls += 1; return []; };
    ok(!methods.historySupported.call(ctx, ghost),
      'неизвестный source не поддержан');
    eq(methods.historyStateFor.call(ctx, ghost), 'idle',
      'неизвестный source остаётся idle');
    ok(!methods.workspaceTabHasContent.call(ctx, ghost, 'history'),
      'неизвестный source: вкладки нет');
    methods._ensureModuleData.call(ctx, ghost);
    eq(calls, 0, 'неизвестный source: ни одного запроса');
    // Валидный модуль без history_source — та же fail-closed ветка.
    const plain = Object.assign({}, SLEEP, { historySource: '' });
    eq(methods.historyStateFor.call(ctx, plain), 'idle',
      'пустой source — idle');
    ok(!methods.workspaceTabHasContent.call(ctx, plain, 'history'),
      'пустой source: вкладки нет');
  }

  // ══ (4) H-4: pending не стирает память, удаление — только empty/denied/off
  {
    clearStorage();
    const ctx = mkCtx();
    ctx._wsTabMemoryLoad();
    methods._wsTabMemorySet.call(ctx, 'chat:-100', SLEEP.id, 'history');
    eq(methods._wsTabMemoryGet.call(ctx, 'chat:-100', SLEEP), '',
      'idle: history не применяется');
    ok(!!memoryRaw()['chat:-100|mod_sleep'],
      'idle: запомненный history НЕ удалён');

    setMeta(ctx, SLEEP, 'loading');
    eq(methods._wsTabMemoryGet.call(ctx, 'chat:-100', SLEEP), '',
      'loading: history не применяется');
    ok(!!memoryRaw()['chat:-100|mod_sleep'],
      'loading: запомненный history НЕ удалён');

    setMeta(ctx, SLEEP, 'error');
    eq(methods._wsTabMemoryGet.call(ctx, 'chat:-100', SLEEP), '',
      'error: history не применяется');
    ok(!!memoryRaw()['chat:-100|mod_sleep'],
      'error: запомненный history НЕ удалён');

    addRows(ctx, SLEEP, [dreamRow(1, 1700000000, 'ok')]);
    eq(methods._wsTabMemoryGet.call(ctx, 'chat:-100', SLEEP), 'history',
      'ready+rows: запомненный history применяется');

    ['empty', 'denied', 'off'].forEach(function (state) {
      methods._wsTabMemorySet.call(ctx, 'chat:-100', SLEEP.id, 'history');
      setMeta(ctx, SLEEP, state);
      if (state === 'ready') ctx.dreamLog = [];
      eq(methods._wsTabMemoryGet.call(ctx, 'chat:-100', SLEEP), '',
        state + ': history не применяется');
      ok(!memoryRaw()['chat:-100|mod_sleep'],
        state + ': запись history удалена');
    });
    clearStorage();
  }

  // ══ (5) H-4: history никогда не дефолт ════════════════════════════════
  {
    clearStorage();
    const ctx = mkCtx({
      workspaceTabHasContent: function (m, tabId) {
        return (m.tabs || []).indexOf(tabId) >= 0 &&
          this._contentTabs.indexOf(tabId) >= 0;
      },
      _contentTabs: ['overview', 'settings', 'limits', 'history'],
    });
    ctx._wsTabMemoryLoad();
    addRows(ctx, SLEEP, [dreamRow(1, 1700000000, 'ok')]);
    addRows(ctx, NOSTALGIA, [nostalgiaRow(2, 1700000100, 'sent', '')]);
    eq(methods.workspaceDefaultTab.call(ctx, SLEEP), 'overview',
      'sleep: дефолт «Обзор», не history');
    eq(methods.workspaceDefaultTab.call(ctx, NOSTALGIA), 'settings',
      'nostalgia: дефолт «Основные настройки», не history');

    // Даже запомненный history не становится дефолтом bare-адреса.
    methods._wsTabMemorySet.call(ctx, 'chat:-100', SLEEP.id, 'history');
    methods._wsTabMemorySet.call(ctx, 'chat:-100', NOSTALGIA.id, 'history');
    eq(methods.workspaceDefaultTab.call(ctx, SLEEP), 'overview',
      'память history не делает её дефолтом (sleep)');
    eq(methods.workspaceDefaultTab.call(ctx, NOSTALGIA), 'settings',
      'память history не делает её дефолтом (nostalgia)');

    // Пустой settings → «Обзор», а не history (continue в резолвере).
    const narrow = mkCtx({
      workspaceTabHasContent: function (m, tabId) {
        return (m.tabs || []).indexOf(tabId) >= 0 &&
          this._contentTabs.indexOf(tabId) >= 0;
      },
      _contentTabs: ['overview', 'history'],
    });
    narrow._wsTabMemoryLoad();
    addRows(narrow, NOSTALGIA, [nostalgiaRow(2, 1700000100, 'sent', '')]);
    eq(methods.workspaceDefaultTab.call(narrow, NOSTALGIA), 'overview',
      'без settings history не подставляется первой');
    clearStorage();
  }

  // ══ (6) H-3/H-6: moduleLastEventState = max(ts) своего журнала ═════════
  {
    const ctx = mkCtx();
    addRows(ctx, SLEEP, [
      dreamRow(1, 1700000000, 'ok'),
      dreamRow(2, 1700000300, 'error'),
      dreamRow(3, 1700000200, 'window_skip'),
    ]);
    SLEEP.state = {
      observed_at: '2099-01-01T00:00:00+00:00',
      checked_at: '2026-11-17T10:00:00+00:00',
    };
    const st = methods.moduleLastEventState.call(ctx, SLEEP);
    eq(st.kind, 'event', 'sleep: состояние события, не «нет данных»');
    ok(st.text.indexOf(methods.fmtLogTs.call(ctx, 1700000300)) >= 0,
      'sleep: взята САМАЯ НОВАЯ строка run_at (300): ' + st.text);
    ok(st.text.indexOf(methods.fmtLogTs.call(ctx, 1700000000)) < 0,
      'sleep: старая строка журнала не выдана за последнюю');
    ok(st.text.indexOf(methods.fmtLogTs.call(ctx,
      '2099-01-01T00:00:00+00:00')) < 0,
    'observed_at не выдан за активность');

    const nctx = mkCtx({ route: '#/modules/nostalgia',
                         activeTab: 'mod_nostalgia' });
    addRows(nctx, NOSTALGIA, [
      nostalgiaRow(1, 1700000100, 'sent', ''),
      nostalgiaRow(2, 1700000500, 'skipped', 'нет повода'),
    ]);
    const nst = methods.moduleLastEventState.call(nctx, NOSTALGIA);
    ok(nst.text.indexOf(methods.fmtLogTs.call(nctx, 1700000500)) >= 0,
      'nostalgia: взята самая новая строка ts: ' + nst.text);
    ok(nst.text.indexOf('нет повода') >= 0,
      'nostalgia: причина строки сохранена');

    // Чужая область не подставляется: meta sleep не делает ready nostalgia.
    eq(methods.moduleHistoryLast.call(ctx, NOSTALGIA), null,
      'sleep-мета не подставлена ностальгии');
    eq(methods.moduleHistoryLast.call(nctx, SLEEP), null,
      'nostalgia-мета не подставлена сну');

    // F3: «Последние события» не повторяют строку, уже показанную в «Сейчас».
    const ovRows = methods.historyOverviewRows.call(ctx, SLEEP);
    const lastRow = methods.moduleHistoryLast.call(ctx, SLEEP);
    eq(ovRows.length, 2, 'Обзор: из 3 строк исключена строка «Сейчас»');
    ok(ovRows.every(function (r) { return r !== lastRow; }),
      'Обзор: строка «Сейчас» не дублирована в «Последних событиях»');
  }

  // ══ (7) H-7: один автоматический фетч на источник, без поллера ═════════
  {
    const ctx = mkCtx();
    let calls = 0;
    const d = deferred();
    ctx.api = function () { calls += 1; return d.p; };
    methods._ensureModuleData.call(ctx, SLEEP);
    methods._ensureModuleData.call(ctx, SLEEP);
    eq(calls, 1, '_ensureModuleData sleep: один запрос при повторном входе');
    eq(methods.historyStateFor.call(ctx, SLEEP), 'loading',
      '_ensureModuleData: состояние loading');
    d.resolve([dreamRow(1, 1700000000, 'ok')]);
    await Promise.resolve();
    await Promise.resolve();
    eq(methods.historyStateFor.call(ctx, SLEEP), 'ready',
      '_ensureModuleData: ответ применён');

    // Повторный вход после ready не порождает фонового поллера.
    methods._ensureModuleData.call(ctx, SLEEP);
    eq(calls, 1, 'повторный вход после ready — без нового запроса');

    // Явное обновление (кнопка) не блокируется мета-состоянием.
    ctx.api = async function () {
      calls += 1;
      return [dreamRow(4, 1700000400, 'ok')];
    };
    await methods.loadDreamLog.call(ctx, true);
    eq(calls, 2, 'явное обновление разрешено');

    // Ностальгия: тот же контракт одного автоматического запроса.
    const nctx = mkCtx({ route: '#/modules/nostalgia',
                         activeTab: 'mod_nostalgia' });
    let ncalls = 0;
    nctx.api = async function () { ncalls += 1; return []; };
    methods._ensureModuleData.call(nctx, NOSTALGIA);
    methods._ensureModuleData.call(nctx, NOSTALGIA);
    await Promise.resolve();
    await Promise.resolve();
    eq(ncalls, 1, '_ensureModuleData nostalgia: один запрос');
  }

  // ══ (8) H-5: deep link на history — предикат и состав вкладок ══════════
  {
    const ctx = mkCtx({ route: '#/modules/sleep/history' });
    addRows(ctx, SLEEP, [dreamRow(1, 1700000000, 'ok')]);
    eq(computed.workspaceTab.call(ctx), 'history',
      'явный /history — вкладка истории');
    ok(computed.workspaceTabs.call(ctx).some(function (t) {
      return t.id === 'history';
    }), 'ready: history присутствует в полосе');
    eq(computed.workspaceTabs.call(ctx).filter(function (t) {
      return t.id === 'history';
    })[0].label, 'История', 'подпись вкладки — «История»');

    const pending = mkCtx({ route: '#/modules/nostalgia/history' });
    eq(computed.workspaceTab.call(pending), 'history',
      'deep link валиден до загрузки');
    ok(!computed.workspaceTabs.call(pending).some(function (t) {
      return t.id === 'history';
    }), 'pending: вкладки в полосе ещё нет');

    // Bare-URL не канонизируется в /settings (W2a К-2 сохранён).
    const bare = mkCtx({ route: '#/modules/nostalgia' });
    eq(computed.workspace.call(bare).slug, 'nostalgia',
      'bare-адрес остаётся bare');
    ok(computed.workspaceTab.call(bare) !== 'history',
      'bare nostalgia не открывает history');
  }

  // ══ (9) F2: смена чата не залипает в loading; tab/refresh живы ═════════
  {
    clearStorage();
    const ctx = mkCtx({
      route: '#/modules/sleep/history',
      activeChatId: -100,
      scopeEpoch: 0,
      workspaceTabHasContent: function (m, tabId) {
        return (m.tabs || []).indexOf(tabId) >= 0 &&
          this._contentTabs.indexOf(tabId) >= 0;
      },
      _contentTabs: ['overview', 'settings', 'limits', 'history'],
    });
    ctx._wsTabMemoryLoad();
    setMeta(ctx, SLEEP, 'loading');       // запрос покинутой области
    let calls = 0;
    ctx.api = async function () {
      calls += 1;
      return [dreamRow(1, 1700000000, 'ok')];
    };
    methods.setActiveChat.call(ctx, -200);
    await tick();
    await tick();
    eq(ctx.activeChatId, -200, 'scope переключён на новый чат');
    eq(methods.historyStateFor.call(ctx, SLEEP), 'ready',
      'новый чат: история загружена, не loading');
    ok(methods.workspaceTabHasContent.call(ctx, SLEEP, 'history'),
      'новый чат: вкладка История восстановлена');
    ok(!(ctx.historyMeta || {})['chat:-100|mod_sleep'],
      'мета покинутого чата удалена');

    methods.setActiveChat.call(ctx, -100);
    await tick();
    await tick();
    eq(methods.historyStateFor.call(ctx, SLEEP), 'ready',
      'возврат: state ready, не залипший loading');
    ok(methods.workspaceTabHasContent.call(ctx, SLEEP, 'history'),
      'возврат: вкладка История восстановлена');
    eq(calls, 2, 'по одному запросу на каждый вход в чат');
    methods._ensureModuleData.call(ctx, SLEEP);
    await tick();
    eq(calls, 2, 'после возврата нет второго поллера');
    clearStorage();
  }

  // ══ (10) F4: фильтр журнала сбрасывается при смене module|tab ══════════
  {
    clearStorage();
    const ctx = mkCtx({ route: '#/modules/sleep/history' });
    ctx._wsTabMemoryLoad();
    ctx.historyFilter = 'duplicate';
    ctx.historyFilterKey = 'mod_sleep|history';
    methods._wsResetHistoryFilter.call(ctx, NOSTALGIA, 'history');
    eq(ctx.historyFilter, '', 'фильтр sleep не переехал на nostalgia');
    eq(ctx.historyFilterKey, 'mod_nostalgia|history',
      'ключ фильтра обновлён на новый module|tab');

    ctx.historyFilter = 'duplicate';
    ctx.historyFilterKey = 'mod_sleep|history';
    methods.openWorkspaceTab.call(ctx, 'limits');
    eq(ctx.historyFilter, '', 'openWorkspaceTab сбрасывает фильтр');
    eq(ctx.nav, '#/modules/sleep/limits',
      'openWorkspaceTab сохранил навигацию');
    clearStorage();
  }

  // ══ (11) B2: фактчек — state machine, detail по run_id, один запрос ═════
  {
    clearStorage();
    const ctx = mkCtx({ route: '#/modules/factcheck',
                         activeTab: 'mod_factcheck' });
    const urls = [];
    eq(methods.historyStateFor.call(ctx, FACTCHECK), 'idle',
      'factcheck: начальное состояние idle');
    ok(!methods.workspaceTabHasContent.call(ctx, FACTCHECK, 'history'),
      'factcheck idle: вкладки нет');
    ok(methods.historyRowHasDetail.call(ctx, FACTCHECK),
      'factcheck: detail объявлен');
    ok(!methods.historyRowHasDetail.call(ctx, EXPERIENCE),
      'experience: detail не объявлен');

    const d = deferred();
    ctx.api = function (u) { urls.push(u); return d.p; };
    const load = methods.loadTemporalRuns.call(ctx);
    eq(methods.historyStateFor.call(ctx, FACTCHECK), 'loading',
      'factcheck: в полёте loading');
    d.resolve({ runs: [temporalRow('tfr-1', 1700000100),
                       temporalRow('tfr-2', 1700000300, -200,
                                   'historical_truth', 'refuted')] });
    await load;
    eq(methods.historyStateFor.call(ctx, FACTCHECK), 'ready',
      'factcheck 200+runs → ready');
    eq(methods.historyRowsFor.call(ctx, FACTCHECK).length, 2,
      'factcheck: строки своего источника');
    ok(methods.workspaceTabHasContent.call(ctx, FACTCHECK, 'history'),
      'factcheck ready+rows: вкладка истории есть');
    eq(urls[0], '/api/factcheck/temporal/runs?limit=20',
      'factcheck: существующий API limit=20');

    // detail: строка без run_id — no-op; с run_id — модалка по id.
    methods.openHistoryRowDetail.call(ctx, FACTCHECK, { chat_id: -100 });
    eq(ctx.temporalDetail, null, 'detail без run_id — no-op');
    const detailCalls = [];
    ctx.api = async function (u) {
      detailCalls.push(u);
      return { run: { run_id: 'tfr-2', claim_text: 'x' }, evidence: [] };
    };
    methods.openHistoryRowDetail.call(ctx, FACTCHECK, { run_id: 'tfr-2' });
    await tick();
    eq(detailCalls[0], '/api/factcheck/temporal/runs/tfr-2',
      'detail: существующий эндпоинт run_id');
    eq(ctx.temporalDetail.run.run_id, 'tfr-2',
      'detail: модалка получила прогон');
    methods.openHistoryRowDetail.call(ctx, EXPERIENCE, { lesson_id: 'L1' });
    eq(detailCalls.length, 1, 'experience: detail не вызывается');
    // F2: кнопка деталей — row-level guard (нужен run_id), а не только
    // модульная возможность источника.
    ok(methods.historyRowCanDetail.call(ctx, FACTCHECK,
      { run_id: 'tfr-2' }), 'factcheck: строка с run_id открывает детали');
    ok(!methods.historyRowCanDetail.call(ctx, FACTCHECK, { chat_id: -100 }),
      'factcheck: строка без run_id не рендерит кнопку');
    ok(!methods.historyRowCanDetail.call(ctx, EXPERIENCE,
      { lesson_id: 'L1' }), 'experience: row-level detail отсутствует');
  }

  {
    // empty / malformed / 403 / 503 / available:false — честные состояния.
    const ctx = mkCtx({ route: '#/modules/factcheck',
                         activeTab: 'mod_factcheck' });
    ctx.api = async function () { return { runs: [] }; };
    await methods.loadTemporalRuns.call(ctx, true);
    eq(methods.historyStateFor.call(ctx, FACTCHECK), 'empty',
      'factcheck [] → empty');
    ok(!methods.workspaceTabHasContent.call(ctx, FACTCHECK, 'history'),
      'factcheck empty: вкладки нет');

    ctx.api = async function () { return {}; };
    await methods.loadTemporalRuns.call(ctx, true);
    eq(methods.historyStateFor.call(ctx, FACTCHECK), 'error',
      'factcheck битый конверт → error');

    ctx.api = async function () {
      const e = new Error('forbidden'); e.status = 403; throw e;
    };
    await methods.loadTemporalRuns.call(ctx, true);
    eq(methods.historyStateFor.call(ctx, FACTCHECK), 'denied',
      'factcheck 403 → denied');
    ok(!methods.workspaceTabHasContent.call(ctx, FACTCHECK, 'history'),
      'factcheck denied: вкладки нет');

    ctx.api = async function () {
      const e = new Error('unavailable'); e.status = 503; throw e;
    };
    await methods.loadTemporalRuns.call(ctx, true);
    eq(methods.historyStateFor.call(ctx, FACTCHECK), 'unavailable',
      'factcheck 503 → unavailable');

    ctx.api = async function () { return { available: false }; };
    await methods.loadTemporalRuns.call(ctx, true);
    eq(methods.historyStateFor.call(ctx, FACTCHECK), 'off',
      'factcheck available:false → off');
    eq(methods.historyRowsFor.call(ctx, FACTCHECK).length, 0,
      'factcheck off: строк не выдумано');
  }

  {
    // H-1: неизвестный/чужой source → 0 запросов; fail-closed вкладки.
    const ghost = {
      id: 'mod_factcheck', routeSlug: 'factcheck', title: 'Фактчек',
      tabs: ['overview', 'settings', 'history'],
      historySource: 'factcheck.unknown',
    };
    const ctx = mkCtx({ modules: MODULES.concat([ghost]) });
    let calls = 0;
    ctx.api = async function () { calls += 1; return { runs: [] }; };
    ok(!methods.historySupported.call(ctx, ghost),
      'factcheck: неизвестный source не поддержан');
    eq(methods.historyStateFor.call(ctx, ghost), 'idle',
      'factcheck: неизвестный source idle');
    ok(!methods.workspaceTabHasContent.call(ctx, ghost, 'history'),
      'factcheck: неизвестный source без вкладки');
    methods._ensureModuleData.call(ctx, ghost);
    eq(calls, 0, 'factcheck: неизвестный source — ни одного запроса');

    const wrong = Object.assign({}, EXPERIENCE, {
      historySource: 'factcheck.temporal.runs',
    });
    ok(!methods.historySupported.call(ctx, wrong),
      'чужой moduleId в строке источника не принимается');
    eq(calls, 0, 'чужой источник не делает запросов');
  }

  {
    // H-7: один автоматический фетч; кэш 30 с не плодит запросов,
    // смена области восстанавливает состояние из кэша без сети.
    const ctx = mkCtx({ route: '#/modules/factcheck',
                         activeTab: 'mod_factcheck' });
    let calls = 0;
    const d = deferred();
    ctx.api = function () { calls += 1; return d.p; };
    methods._ensureModuleData.call(ctx, FACTCHECK);
    methods._ensureModuleData.call(ctx, FACTCHECK);
    eq(calls, 1, 'factcheck: один запрос при повторном входе');
    d.resolve({ runs: [temporalRow('tfr-1', 1700000100)] });
    await tick();
    await tick();
    eq(methods.historyStateFor.call(ctx, FACTCHECK), 'ready',
      'factcheck: ответ применён');
    methods._ensureModuleData.call(ctx, FACTCHECK);
    eq(calls, 1, 'factcheck: ready не запускает новый запрос');

    // Смена области: pending-мета удалена, данные из кэша → ready без сети.
    ctx.historyMeta = {};
    methods._ensureModuleData.call(ctx, FACTCHECK);
    eq(calls, 1, 'factcheck: кэш 30 с не делает второй запрос');
    eq(methods.historyStateFor.call(ctx, FACTCHECK), 'ready',
      'factcheck: состояние новой области из кэша');
  }

  // ══ (12) B2: опыт — конверт уроков, URL, состояния, обзор ═══════════════
  {
    clearStorage();
    const ctx = mkCtx({ route: '#/modules/experience',
                         activeTab: 'mod_experience' });
    const urls = [];
    ctx.api = async function (u) {
      urls.push(u);
      return { enabled: true, state: 'implemented', count: 2,
               lessons: [lessonRow('L1', 1, 1700000100, 'active'),
                         lessonRow('L2', 2, 1700000300, 'candidate',
                                   'retrieval')] };
    };
    await methods.loadLessons.call(ctx, true);
    eq(methods.historyStateFor.call(ctx, EXPERIENCE), 'ready',
      'experience: конверт → ready');
    eq(methods.historyRowsFor.call(ctx, EXPERIENCE).length, 2,
      'experience: строки lessons');
    ok(methods.workspaceTabHasContent.call(ctx, EXPERIENCE, 'history'),
      'experience ready+rows: вкладка истории есть');
    eq(methods.historyEnvelopeText.call(ctx, EXPERIENCE),
      'записей в журнале: 2 (есть записи)',
      'experience: строка журнала уроков (RU-состояние, D2)');
    eq(urls[0], '/api/memory/lessons?chat_id=-100',
      'experience: чатовая область сохраняет прежний адрес');
    eq(methods.historyRowKey.call(ctx, EXPERIENCE,
      methods.historyRowsFor.call(ctx, EXPERIENCE)[1]), 'L2@2',
      'experience: ключ строки — lesson_id@version');
    eq(methods.historyRowStatusCode.call(ctx, EXPERIENCE,
      methods.historyRowsFor.call(ctx, EXPERIENCE)[1]), 'candidate',
      'experience: код статуса — status урока');
    eq(methods.historyRowChatText.call(ctx, EXPERIENCE,
      methods.historyRowsFor.call(ctx, EXPERIENCE)[0]), 'чат -100',
      'experience: чатовая область строки');
  }

  {
    // Глобальная область: limit=50 (H-1), пустой конверт → empty,
    // выключенная функция → off, без «0 событий».
    const ctx = mkCtx({ route: '#/modules/experience',
                         activeTab: 'mod_experience',
                         activeChatId: null });
    const urls = [];
    ctx.api = async function (u) {
      urls.push(u);
      return { enabled: true, state: 'not_run', count: 0, lessons: [] };
    };
    await methods.loadLessons.call(ctx, true);
    eq(urls[0], '/api/memory/lessons?limit=50',
      'experience: глобальная область limit=50');
    eq(methods.historyStateFor.call(ctx, EXPERIENCE), 'empty',
      'experience: пустой конверт → empty');
    eq(methods.historyEnvelopeText.call(ctx, EXPERIENCE),
      'записей в журнале: 0 (записей нет)',
      'experience: честное состояние not_run');
    ok(!methods.workspaceTabHasContent.call(ctx, EXPERIENCE, 'history'),
      'experience empty: вкладки нет');

    ctx.api = async function () {
      return { enabled: false, state: 'disabled', count: 0, lessons: [] };
    };
    await methods.loadLessons.call(ctx, true);
    eq(methods.historyStateFor.call(ctx, EXPERIENCE), 'off',
      'experience enabled:false → off');
    eq(methods.historyEnvelopeText.call(ctx, EXPERIENCE),
      'записей в журнале: 0 (функция выключена)',
      'experience: off показывает сырое состояние конверта');
    ok(!methods.workspaceTabHasContent.call(ctx, EXPERIENCE, 'history'),
      'experience off: вкладки нет');
    ok(methods.historyStateText.call(ctx, EXPERIENCE).indexOf('0 событий') < 0,
      'experience off не превращается в «0 событий»');

    ctx.api = async function () {
      const e = new Error('forbidden'); e.status = 403; throw e;
    };
    await methods.loadLessons.call(ctx, true);
    eq(methods.historyStateFor.call(ctx, EXPERIENCE), 'denied',
      'experience 403 → denied');
    ctx.api = async function () {
      const e = new Error('unavailable'); e.status = 503; throw e;
    };
    await methods.loadLessons.call(ctx, true);
    eq(methods.historyStateFor.call(ctx, EXPERIENCE), 'unavailable',
      'experience 503 → unavailable');
  }

  {
    // H-7: опыт — один автоматический запрос на область.
    const ctx = mkCtx({ route: '#/modules/experience',
                         activeTab: 'mod_experience' });
    let calls = 0;
    ctx.api = async function () {
      calls += 1;
      return { enabled: true, state: 'implemented', count: 1,
               lessons: [lessonRow('L1', 1, 1700000100, 'active')] };
    };
    methods._ensureModuleData.call(ctx, EXPERIENCE);
    methods._ensureModuleData.call(ctx, EXPERIENCE);
    await tick();
    eq(calls, 1, 'experience: повторный вход не дублирует запрос');
    methods._ensureModuleData.call(ctx, EXPERIENCE);
    await tick();
    eq(calls, 1, 'experience: ready не запускает новый запрос');

    const ghostExp = Object.assign({}, EXPERIENCE, {
      historySource: 'memory.unknown',
    });
    const ctx2 = mkCtx();
    let calls2 = 0;
    ctx2.api = async function () { calls2 += 1; return {}; };
    methods._ensureModuleData.call(ctx2, ghostExp);
    eq(calls2, 0, 'experience: неизвестный source — ни одного запроса');
  }

  // ══ (13) B2: H-4 — history не дефолт; pending не чистит память ═════════
  {
    clearStorage();
    const ctx = mkCtx({
      route: '#/modules/experience',
      workspaceTabHasContent: function (m, tabId) {
        return (m.tabs || []).indexOf(tabId) >= 0 &&
          this._contentTabs.indexOf(tabId) >= 0;
      },
      _contentTabs: ['overview', 'settings', 'limits', 'history'],
    });
    ctx._wsTabMemoryLoad();
    methods._wsHistoryMetaSet.call(ctx, EXPERIENCE, 'ready',
      { rows: 1, count: 1, state: 'implemented' });
    ctx.lessonsData = { enabled: true, state: 'implemented', count: 1,
                        lessons: [lessonRow('L1', 1, 1700000100, 'active')] };
    eq(methods.workspaceDefaultTab.call(ctx, EXPERIENCE), 'overview',
      'experience: дефолт «Обзор», не history');
    methods._wsTabMemorySet.call(ctx, 'chat:-100', EXPERIENCE.id, 'history');
    eq(methods.workspaceDefaultTab.call(ctx, EXPERIENCE), 'overview',
      'experience: память history не делает её дефолтом');

    // Фактчек: дефолт — «Основные настройки», не history.
    const fctx = mkCtx({
      route: '#/modules/factcheck',
      workspaceTabHasContent: function (m, tabId) {
        return (m.tabs || []).indexOf(tabId) >= 0 &&
          this._contentTabs.indexOf(tabId) >= 0;
      },
      _contentTabs: ['overview', 'settings', 'history'],
    });
    fctx._wsTabMemoryLoad();
    methods._wsHistoryMetaSet.call(fctx, FACTCHECK, 'ready', { rows: 1 });
    fctx.temporalRuns = [temporalRow('tfr-1', 1700000100)];
    eq(methods.workspaceDefaultTab.call(fctx, FACTCHECK), 'settings',
      'factcheck: дефолт «Основные настройки», не history');

    // Пустой settings → «Обзор», history первой не подставляется.
    const narrow = mkCtx({
      route: '#/modules/factcheck',
      workspaceTabHasContent: function (m, tabId) {
        return (m.tabs || []).indexOf(tabId) >= 0 &&
          this._contentTabs.indexOf(tabId) >= 0;
      },
      _contentTabs: ['overview', 'history'],
    });
    narrow._wsTabMemoryLoad();
    methods._wsHistoryMetaSet.call(narrow, FACTCHECK, 'ready', { rows: 1 });
    narrow.temporalRuns = [temporalRow('tfr-1', 1700000100)];
    eq(methods.workspaceDefaultTab.call(narrow, FACTCHECK), 'overview',
      'factcheck: без settings history не подставляется первой');

    // Pending (idle/loading/error) не стирает запомненный history.
    clearStorage();
    const pctx = mkCtx({ route: '#/modules/experience' });
    pctx._wsTabMemoryLoad();
    methods._wsTabMemorySet.call(pctx, 'chat:-100', EXPERIENCE.id, 'history');
    ['idle', 'loading', 'error'].forEach(function (state) {
      if (state !== 'idle') {
        methods._wsHistoryMetaSet.call(pctx, EXPERIENCE, state);
      }
      eq(methods._wsTabMemoryGet.call(pctx, 'chat:-100', EXPERIENCE), '',
        'experience ' + state + ': history не применяется');
      ok(!!memoryRaw()['chat:-100|mod_experience'],
        'experience ' + state + ': память не удалена');
    });
    methods._wsHistoryMetaSet.call(pctx, EXPERIENCE, 'ready',
      { rows: 1, count: 1, state: 'implemented' });
    pctx.lessonsData = { enabled: true, state: 'implemented', count: 1,
                         lessons: [lessonRow('L1', 1, 1700000100, 'active')] };
    eq(methods._wsTabMemoryGet.call(pctx, 'chat:-100', EXPERIENCE), 'history',
      'experience ready+rows: память применяется');
    methods._wsHistoryMetaSet.call(pctx, EXPERIENCE, 'empty');
    eq(methods._wsTabMemoryGet.call(pctx, 'chat:-100', EXPERIENCE), '',
      'experience empty: history не применяется');
    ok(!memoryRaw()['chat:-100|mod_experience'],
      'experience empty: запись удалена');
    clearStorage();
  }

  // ══ (14) B2: H-6 — max(ts) своего источника, без observed_at ═══════════
  {
    const ctx = mkCtx({ route: '#/modules/factcheck',
                         activeTab: 'mod_factcheck' });
    methods._wsHistoryMetaSet.call(ctx, FACTCHECK, 'ready', { rows: 3 });
    ctx.temporalRuns = [
      temporalRow('tfr-1', 1700000100, -100, 'contextual', 'supported'),
      temporalRow('tfr-2', 1700000500, -200, 'historical_truth', 'refuted'),
      temporalRow('tfr-3', 1700000300, -100, 'current', 'mixed'),
    ];
    FACTCHECK.state = {
      observed_at: '2099-01-01T00:00:00+00:00',
      checked_at: '2026-11-17T10:00:00+00:00',
    };
    const st = methods.moduleLastEventState.call(ctx, FACTCHECK);
    eq(st.kind, 'event', 'factcheck: состояние события');
    ok(st.text.indexOf(methods.fmtLogTs.call(ctx, 1700000500)) >= 0,
      'factcheck: взята самая новая строка created_at: ' + st.text);
    ok(st.text.indexOf('опровергнуто') >= 0,
      'factcheck: вердикт строки сохранён');
    ok(st.text.indexOf('чат -200') >= 0,
      'factcheck: чат строки сохранён');
    ok(st.text.indexOf(methods.fmtLogTs.call(ctx,
      '2099-01-01T00:00:00+00:00')) < 0,
    'factcheck: observed_at не выдан за активность');

    const ectx = mkCtx({ route: '#/modules/experience',
                         activeTab: 'mod_experience' });
    methods._wsHistoryMetaSet.call(ectx, EXPERIENCE, 'ready',
      { rows: 2, count: 2, state: 'implemented' });
    ectx.lessonsData = { enabled: true, state: 'implemented', count: 2,
      lessons: [
        lessonRow('L1', 1, 1700000100, 'active', 'tool_usage'),
        lessonRow('L2', 1, 1700000900, 'suspended', 'failure_pattern'),
      ] };
    EXPERIENCE.state = { observed_at: '2099-02-02T00:00:00+00:00' };
    const est = methods.moduleLastEventState.call(ectx, EXPERIENCE);
    eq(est.kind, 'event', 'experience: состояние события');
    ok(est.text.indexOf(methods.fmtLogTs.call(ectx, 1700000900)) >= 0,
      'experience: max(updated_at) строки урока');
    ok(est.text.indexOf('приостановлен') >= 0,
      'experience: статус урока сохранён');
    ok(est.text.indexOf(methods.fmtLogTs.call(ectx,
      '2099-02-02T00:00:00+00:00')) < 0,
    'experience: observed_at не активность');

    // Чужой источник не подставляется в опыт/фактчек наоборот.
    eq(methods.moduleHistoryLast.call(ectx, FACTCHECK), null,
      'мета опыта не подставлена фактчеку');
    eq(methods.moduleHistoryLast.call(ctx, EXPERIENCE), null,
      'мета фактчека не подставлена опыту');
  }

  // ══ (15) B2: клиентский фильтр по статусу источника ════════════════════
  {
    const ctx = mkCtx({ route: '#/modules/factcheck' });
    methods._wsHistoryMetaSet.call(ctx, FACTCHECK, 'ready', { rows: 3 });
    ctx.temporalRuns = [
      temporalRow('tfr-1', 1700000100, -100, 'contextual', 'supported'),
      temporalRow('tfr-2', 1700000300, -100, 'current', 'refuted'),
      temporalRow('tfr-3', 1700000200, -100, 'current', 'refuted'),
    ];
    const opts = methods.historyStatusOptions.call(ctx, FACTCHECK);
    eq(opts.length, 2, 'factcheck: фильтр по вердиктам (2 уникальных)');
    eq(methods.historyStatusLabel.call(ctx, FACTCHECK, 'refuted'),
      'опровергнуто', 'factcheck: подпись вердикта');
    ctx.historyFilter = 'refuted';
    eq(methods.historyFilteredRows.call(ctx, FACTCHECK).length, 2,
      'factcheck: фильтр сужает строки');
    ctx.historyFilter = '';

    const ectx = mkCtx({ route: '#/modules/experience' });
    methods._wsHistoryMetaSet.call(ectx, EXPERIENCE, 'ready',
      { rows: 3, count: 3, state: 'implemented' });
    ectx.lessonsData = { enabled: true, state: 'implemented', count: 3,
      lessons: [
        lessonRow('L1', 1, 1700000100, 'active'),
        lessonRow('L2', 2, 1700000300, 'candidate'),
        lessonRow('L3', 1, 1700000200, 'active'),
      ] };
    eq(methods.historyStatusLabel.call(ectx, EXPERIENCE, 'candidate'),
      'кандидат', 'experience: подпись статуса урока');
    ectx.historyFilter = 'candidate';
    eq(methods.historyFilteredRows.call(ectx, EXPERIENCE).length, 1,
      'experience: фильтр сужает строки урока');
    ectx.historyFilter = '';
    eq(methods.historyRowBadgeClass.call(ectx, EXPERIENCE,
      { status: 'active' }), 'badge-ok',
      'experience: badge активного урока');
  }

  // ══ (16) F1: cross-scope history — кэш/поздние ответы не текут ═════════
  {
    clearStorage();
    const mkF1 = function (route) {
      return mkCtx({
        route: route,
        activeChatId: -100,
        scopeEpoch: 0,
        workspaceTabHasContent: function (m, tabId) {
          return (m.tabs || []).indexOf(tabId) >= 0 &&
            this._contentTabs.indexOf(tabId) >= 0;
        },
        _contentTabs: ['overview', 'settings', 'history'],
      });
    };

    // F1-a: 30-с кэш области A не засевает область B.
    const ctx = mkF1('#/modules/factcheck/history');
    ctx._wsTabMemoryLoad();
    methods._wsHistoryMetaSet.call(ctx, FACTCHECK, 'ready', { rows: 1 });
    ctx.temporalRuns = [temporalRow('old-run', 1700000100)];
    ctx.temporalRunsAt = Date.now();
    ctx.temporalRunsScope = 'chat:-100';
    ctx.temporalRunsEpoch = 0;
    let calls = 0;
    ctx.api = async function () {
      calls += 1;
      return { runs: [temporalRow('new-run', 1700000200)] };
    };
    methods.setActiveChat.call(ctx, -200);
    await tick();
    await tick();
    eq(calls, 1,
      'F1 cache: область B делает свой запрос (кэш A не засевает)');
    eq(methods.historyStateFor.call(ctx, FACTCHECK), 'ready',
      'F1 cache: B получает своё ready');
    const brows = methods.historyRowsFor.call(ctx, FACTCHECK);
    eq(brows.length, 1, 'F1 cache: у B ровно свои строки');
    eq(brows[0].run_id, 'new-run',
      'F1 cache: B не получил old-run из области A');
    ok(brows.every(function (r) { return r.run_id !== 'old-run'; }),
      'F1 cache: строк области A в B нет');
    eq(ctx.temporalRunsScope, 'chat:-200',
      'F1 cache: кэш помечен областью B');
    eq(ctx.temporalRunsEpoch, 1, 'F1 cache: кэш помечен epoch B');

    // F1-b: пустой кэш A не даёт B ложный empty без запроса.
    const ectx = mkF1('#/modules/factcheck/history');
    ectx._wsTabMemoryLoad();
    methods._wsHistoryMetaSet.call(ectx, FACTCHECK, 'empty', { rows: 0 });
    ectx.temporalRuns = [];
    ectx.temporalRunsAt = Date.now();
    ectx.temporalRunsScope = 'chat:-100';
    ectx.temporalRunsEpoch = 0;
    let ecalls = 0;
    ectx.api = async function () {
      ecalls += 1;
      return { runs: [] };
    };
    methods.setActiveChat.call(ectx, -200);
    await tick();
    await tick();
    eq(ecalls, 1, 'F1 cache: пустой кэш A не отменяет запрос B');
    eq(methods.historyStateFor.call(ectx, FACTCHECK), 'empty',
      'F1 cache: B получает свой empty после запроса');

    // F1-c: поздний in-flight ответ A не перезаписывает фактчек B.
    const ictx = mkF1('#/modules/factcheck/history');
    ictx._wsTabMemoryLoad();
    let icalls = 0;
    const dA = deferred();
    ictx.api = function () {
      icalls += 1;
      if (icalls === 1) return dA.p;
      return Promise.resolve({ runs: [temporalRow('new-run', 1700000200)] });
    };
    const loadA = methods.loadTemporalRuns.call(ictx);
    methods.setActiveChat.call(ictx, -200);
    await tick();
    await tick();
    eq(methods.historyRowsFor.call(ictx, FACTCHECK)[0].run_id, 'new-run',
      'F1 inflight: B получил свои строки');
    dA.resolve({ runs: [temporalRow('old-run', 1700000100)] });
    await loadA;
    await tick();
    eq(ictx.temporalRuns[0].run_id, 'new-run',
      'F1 inflight: поздний ответ A не перезаписал temporalRuns');
    eq(methods.historyRowsFor.call(ictx, FACTCHECK)[0].run_id, 'new-run',
      'F1 inflight: строки B остались');
    eq((ictx.historyMeta || {})['chat:-200|mod_factcheck'].rows, 1,
      'F1 inflight: мета B не получила строк A');

    // F1-d: поздний in-flight ответ A не перезаписывает уроки B.
    const lctx = mkF1('#/modules/experience/history');
    lctx._wsTabMemoryLoad();
    let lcalls = 0;
    const dlA = deferred();
    lctx.api = function () {
      lcalls += 1;
      if (lcalls === 1) return dlA.p;
      return Promise.resolve({ enabled: true, state: 'implemented', count: 1,
        lessons: [lessonRow('B-lesson', 1, 1700000200, 'active')] });
    };
    const loadLA = methods.loadLessons.call(lctx);
    methods.setActiveChat.call(lctx, -200);
    await tick();
    await tick();
    eq(methods.historyRowsFor.call(lctx, EXPERIENCE)[0].lesson_id,
      'B-lesson', 'F1 lessons inflight: B получил свои уроки');
    dlA.resolve({ enabled: true, state: 'implemented', count: 1,
      lessons: [lessonRow('OLD', 1, 1700000100, 'active')] });
    await loadLA;
    await tick();
    eq(methods.historyRowsFor.call(lctx, EXPERIENCE)[0].lesson_id,
      'B-lesson', 'F1 lessons inflight: строки B остались');
    eq(lctx.lessonsData.lessons[0].lesson_id, 'B-lesson',
      'F1 lessons inflight: поздний A не перезаписал lessonsData');
    eq(methods.historyStateFor.call(lctx, EXPERIENCE), 'ready',
      'F1 lessons inflight: состояние B осталось ready');
    clearStorage();
  }

  {
    // B2: источник только для владельца — не-админ получает честный denied,
    // без запроса, без вкладки и без пустой панели deep link.
    const ctx = mkCtx({ route: '#/modules/factcheck/history',
                         activeTab: 'mod_factcheck', isGlobalAdmin: false });
    let calls = 0;
    ctx.api = async function () { calls += 1; return { runs: [] }; };
    eq(methods.historyStateFor.call(ctx, FACTCHECK), 'denied',
      'factcheck не-админ: честный denied');
    ok(!methods.workspaceTabHasContent.call(ctx, FACTCHECK, 'history'),
      'factcheck не-админ: вкладки нет');
    methods._ensureModuleData.call(ctx, FACTCHECK);
    eq(calls, 0, 'factcheck не-админ: ни одного запроса');
    methods._maybeExitHistory.call(ctx);
    eq((ctx.applied || [])[0], '#/modules/factcheck',
      'factcheck не-админ: deep link уведён на bare');
  }

  // ══ (17) B3: summary / random.uses через oversight/runs ════════════════
  {
    // H-1: карта источника — один эндпоинт, свой модуль, свой pipeline_type,
    // деталь — существующий deep link наблюдаемости.
    clearStorage();
    const ctx = mkCtx();
    ok(methods.historySupported.call(ctx, SUMMARY),
      'B3: summary не поддержан в HISTORY_SOURCES');
    ok(methods.historySupported.call(ctx, RANDOM),
      'B3: random не поддержан в HISTORY_SOURCES');
    eq(methods.historySourceLabel.call(ctx, SUMMARY), 'Прогоны сводок',
      'B3: подпись источника summary');
    eq(methods.historySourceLabel.call(ctx, RANDOM), 'Прогоны случайности',
      'B3: подпись источника random');
    // F1: `summary.window` — компонентные события окна БЕЗ pipeline_run_id,
    // источником истории не является: ни вкладки, ни запроса.
    ok(!methods.historySupported.call(ctx,
      { id: 'mod_summary', historySource: LEGACY_SUMMARY_SOURCE }),
      'F1: summary.window не должен поддерживаться как источник');
    ok(!methods.historySupported.call(ctx,
      { id: 'mod_summary', historySource: 'summary.window' }),
      'F1: голый summary.window тоже не источник');
    // Чужой источник не подставляется «по имени»: источник сна не делает
    // страницу сводок исторической.
    ok(!methods.historySupported.call(ctx,
      { id: 'mod_summary', historySource: SLEEP_SOURCE }),
      'B3: чужой source не поддержан у summary');

    const calls = [];
    ctx.api = function (path, opts) {
      calls.push({ path: path, opts: opts || {} });
      return Promise.resolve({ available: true, enabled: true, runs: [
        runRow('srun-1', 1700000200, 'summary', 'succeeded'),
        runRow('srun-2', 1700000100, 'summary', 'failed')] });
    };
    await methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    eq(calls.length, 1, 'B3 summary: должен быть ровно один запрос');
    eq(calls[0].path,
      '/api/oversight/runs?pipeline_type=summary&limit=20',
      'F1: summary обязан запрашивать РЕАЛЬНЫЙ pipeline_type=summary');
    ok(calls[0].path.indexOf('summary.window') < 0,
      'F1: синтетический pipeline_type=summary.window не запрашивается');
    eq(calls[0].opts.global, true,
      'B3: oversight-API вызывается как global (без X-Chat-Id)');
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'ready',
      'B3 summary: 200+runs → ready');
    eq(methods.historyRowsFor.call(ctx, SUMMARY).length, 2,
      'B3 summary: строки своего источника');
    ok(methods.workspaceTabHasContent.call(ctx, SUMMARY, 'history'),
      'B3 summary: вкладка истории при ready+rows');
    // Соседний источник НЕ получает строки summary (общий стор запрещён).
    eq(methods.historyStateFor.call(ctx, RANDOM), 'idle',
      'B3: random не получает состояние summary');
    eq(methods.historyRowsFor.call(ctx, RANDOM).length, 0,
      'B3: строки summary не текут в random');

    await methods.loadModuleRuns.call(ctx, RANDOM_SOURCE);
    eq(calls.length, 2, 'B3: второй источник — свой запрос');
    eq(calls[1].path,
      '/api/oversight/runs?pipeline_type=random.uses&limit=20',
      'B3 random: неверный адрес источника');
    eq(methods.historyStateFor.call(ctx, RANDOM), 'ready',
      'B3 random: 200+runs → ready');
    eq(methods.historyRowsFor.call(ctx, SUMMARY).length, 2,
      'B3: строки summary не затёрты загрузкой random');
    eq(methods.historyRowKey.call(ctx, SUMMARY,
      methods.historyRowsFor.call(ctx, SUMMARY)[0]), 'srun-1',
      'B3: ключ строки — pipeline_run_id');
    eq(methods.historyRowStatusText.call(ctx, SUMMARY, runRow('x', 1,
      'summary', 'failed')), 'неуспешно',
      'B3: статус прогона — существующая RU-подпись');
    eq(methods.historyRowBadgeClass.call(ctx, SUMMARY, runRow('x', 1,
      'summary', 'succeeded')), 'badge-ok',
      'B3: бейдж успешного прогона');
    eq(methods.historyRowKindText.call(ctx, SUMMARY, runRow('x', 1,
      'summary')), 'Сводки',
      'F1: тип строки summary — собственная подпись источника');
    // Random не изменился: человеческое имя из существующего словаря.
    eq(methods.historyRowKindText.call(ctx, RANDOM, runRow('x', 1,
      'random.uses')), 'Применения случайности',
      'B3 random: тип строки из словаря процессов');
    // F1: сама метка старого источника в карте отсутствует.
    ok(APP_JS.indexOf("'oversight:summary.window'") < 0,
      'F1: карта всё ещё содержит синтетический oversight:summary.window');
    ok(APP_JS.indexOf('pipeline_type=summary.window') < 0,
      'F1: синтетический pipeline_type=summary.window остался в коде');
  }

  {
    // H-3: переходы состояний — 403 → denied, 503 → unavailable,
    // available:false/enabled:false → off, битый конверт → error.
    clearStorage();
    const mk = function () {
      const ctx = mkCtx();
      ctx.api = async function () { return { available: true, enabled: true,
        runs: [] }; };
      return ctx;
    };
    let ctx = mk();
    await methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'empty',
      'B3: runs:[] → empty (не «ready» и не «0 событий» как ready)');
    ok(!methods.workspaceTabHasContent.call(ctx, SUMMARY, 'history'),
      'B3 empty: вкладки истории нет');
    eq(ctx.toasts.length, 0, 'B3 empty: без тоста');

    ctx = mk();
    ctx.api = async function () {
      const e = new Error('нет доступа'); e.status = 403; throw e;
    };
    await methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'denied',
      'B3: 403 → denied, а не «0 событий»');
    ok(!methods.workspaceTabHasContent.call(ctx, SUMMARY, 'history'),
      'B3 403: вкладки нет');
    eq(methods.historyStateText.call(ctx, SUMMARY),
      'нет доступа к журналу (403)', 'B3 403: честная причина');

    ctx = mk();
    ctx.api = async function () {
      const e = new Error('выключено'); e.status = 503; throw e;
    };
    await methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'unavailable',
      'B3: 503 → unavailable');

    ctx = mk();
    ctx.api = async function () { return { available: false }; };
    await methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'off',
      'B3: available:false → off (гейт наблюдаемости выключен)');

    ctx = mk();
    ctx.api = async function () { return { enabled: false, runs: [] }; };
    await methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'off',
      'B3: enabled:false → off');

    ctx = mk();
    ctx.api = async function () { return { unexpected: true }; };
    await methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'error',
      'B3: конверт без runs → error (не выдуманная пустота)');

    ctx = mk();
    ctx.api = async function () { throw new Error('network'); };
    await methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'error',
      'B3: сеть → error');
    eq(methods.historyRowsFor.call(ctx, SUMMARY).length, 0,
      'B3 error: строк нет');
  }

  {
    // H-2/H-3: пока запрос в полёте — loading и НЕТ вкладки; поздний ответ
    // применяется только своей областью.
    clearStorage();
    const ctx = mkCtx();
    const d = deferred();
    ctx.api = function () { return d.p; };
    const load = methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'loading',
      'B3: в полёте — loading');
    ok(!methods.workspaceTabHasContent.call(ctx, SUMMARY, 'history'),
      'B3 loading: вкладки нет');
    // H-7: повторный вход во время полёта не плодит запрос.
    await methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    d.resolve({ available: true, enabled: true,
      runs: [runRow('srun-1', 1700000200)] });
    await load;
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'ready',
      'B3: ответ применён к своей области');
  }

  {
    // H-3 (RBAC): oversight-API — только владелец. Не-админ: ноль запросов,
    // честный denied, вкладки нет, deep link уводится на bare один раз.
    clearStorage();
    const ctx = mkCtx({ route: '#/modules/summary/history',
                         activeTab: 'mod_summary', isGlobalAdmin: false });
    let calls = 0;
    ctx.api = async function () { calls += 1; return { runs: [] }; };
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'denied',
      'B3 не-админ: честный denied без запроса');
    eq(methods.historyStateFor.call(ctx, RANDOM), 'denied',
      'B3 не-админ: random тоже denied');
    methods._ensureModuleData.call(ctx, SUMMARY);
    methods._ensureModuleData.call(ctx, RANDOM);
    await methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    await methods.loadModuleRuns.call(ctx, RANDOM_SOURCE);
    eq(calls, 0, 'B3 не-админ: ни одного запроса к oversight API');
    ok(!methods.workspaceTabHasContent.call(ctx, SUMMARY, 'history'),
      'B3 не-админ: вкладки истории нет');
    ok(methods.historyNeedsOwner.call(ctx, SUMMARY),
      'B3: источник помечен «только владелец» (честная подсказка)');
    methods._maybeExitHistory.call(ctx);
    eq((ctx.applied || [])[0], '#/modules/summary',
      'B3 не-админ: deep link уведён на bare');
  }

  {
    // H-1 fail-closed: неизвестный источник — 0 запросов и НЕТ вкладки.
    clearStorage();
    const ctx = mkCtx();
    let calls = 0;
    ctx.api = async function () { calls += 1; return { runs: [] }; };
    await methods.loadModuleRuns.call(ctx, 'oversight:unknown.source');
    await methods.loadModuleRuns.call(ctx, 'nope');
    eq(calls, 0, 'B3: неизвестный source → ноль запросов');
    const unknownModule = { id: 'mod_summary', tabs: ['overview', 'settings',
      'history'], historySource: 'oversight:unknown.source' };
    ok(!methods.historySupported.call(ctx, unknownModule),
      'B3: неизвестная строка DTO не поддержана');
    eq(methods.historyStateFor.call(ctx, unknownModule), 'idle',
      'B3: неизвестный source остаётся idle');
    ok(!methods.workspaceTabHasContent.call(ctx, unknownModule, 'history'),
      'B3: неизвестный source не создаёт вкладку');
    methods._ensureModuleData.call(ctx, unknownModule);
    eq(calls, 0, 'B3: неизвестный source в _ensureModuleData — 0 запросов');
  }

  {
    // H-7: один фетч на источник; 30-с кэш СВОЕЙ области; force — повтор.
    clearStorage();
    const ctx = mkCtx();
    let calls = 0;
    ctx.api = async function () {
      calls += 1;
      return { available: true, enabled: true,
        runs: [runRow('srun-1', 1700000200)] };
    };
    methods._ensureModuleData.call(ctx, SUMMARY);
    await methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    eq(calls, 1, 'B3: первый вход на страницу — ровно один запрос');
    methods._ensureModuleData.call(ctx, SUMMARY);
    await methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    eq(calls, 1, 'B3: кэш 30 с — повторный вход не запрашивает');
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'ready',
      'B3: состояние из кэша своей области (ready)');
    methods.refreshHistory.call(ctx, SUMMARY);
    await tick();
    eq(calls, 2, 'B3: ⟳ (refresh) делает явный повторный запрос');
    // Кэш помечен СВОЕЙ областью и epoch.
    const cache = (ctx.moduleRunsCache || {})[SUMMARY_SOURCE];
    ok(cache && cache.scope === 'chat:-100' && cache.epoch === 0,
      'B3: кэш помечен scope/epoch');
    // Второй источник не засевается кэшем первого.
    let rcalls = 0;
    ctx.api = async function () {
      rcalls += 1;
      return { available: true, enabled: true,
        runs: [runRow('rrun-1', 1700000300, 'random.uses')] };
    };
    await methods.loadModuleRuns.call(ctx, RANDOM_SOURCE);
    eq(rcalls, 1, 'B3: random делает свой запрос (кэш summary не общий)');
    eq(methods.historyRowsFor.call(ctx, RANDOM)[0].pipeline_run_id, 'rrun-1',
      'B3: у random свои строки');
    eq(methods.historyRowsFor.call(ctx, SUMMARY)[0].pipeline_run_id,
      'srun-1', 'B3: у summary остались свои строки');
  }

  {
    // F1/B3: scope-aware кэш и epoch-guard. A→B→A: каждая область делает
    // свой запрос, чужие строки не показываются, поздний ответ A не
    // перезаписывает B.
    clearStorage();
    const mk = function () {
      return mkCtx({
        route: '#/modules/summary/history', activeTab: 'mod_summary',
        workspaceTabHasContent: function (m, tabId) {
          return (m.tabs || []).indexOf(tabId) >= 0 &&
            this._contentTabs.indexOf(tabId) >= 0;
        },
        _contentTabs: ['overview', 'settings', 'history'],
      });
    };
    const ctx = mk();
    ctx._wsTabMemoryLoad();
    let calls = 0;
    ctx.api = async function (path, opts) {
      calls += 1;
      const chat = (ctx.activeChatId === -200) ? -200 : -100;
      return { available: true, enabled: true,
        runs: [runRow('run-' + Math.abs(chat), 1700000200,
                      'summary', 'succeeded', chat)] };
    };
    methods._ensureModuleData.call(ctx, SUMMARY);
    await tick();
    eq(calls, 1, 'B3 A→B→A: область A сделала свой запрос');
    eq(methods.historyRowsFor.call(ctx, SUMMARY)[0].pipeline_run_id,
      'run-100', 'B3 A→B→A: строки области A');
    methods._ensureModuleData.call(ctx, SUMMARY);
    eq(calls, 1, 'B3 A→B→A: свежий кэш A повторно не запрашивает');

    let bcalls = 0;
    const dB = deferred();
    ctx.api = function () { bcalls += 1; return dB.p; };
    methods.setActiveChat.call(ctx, -200);
    await tick();
    eq(bcalls, 1, 'B3 A→B→A: область B делает свой запрос (кэш A не засевает)');
    // Поздний ответ B не смешивается с A: пока B в полёте строк нет.
    eq(methods.historyRowsFor.call(ctx, SUMMARY).length, 0,
      'B3 A→B→A: до ответа B строк области A не видно');
    dB.resolve({ available: true, enabled: true,
      runs: [runRow('run-200', 1700000300, 'summary', 'failed', -200)] });
    await tick();
    await tick();
    const brows = methods.historyRowsFor.call(ctx, SUMMARY);
    eq(brows.length, 1, 'B3 A→B→A: у B ровно свои строки');
    eq(brows[0].pipeline_run_id, 'run-200', 'B3 A→B→A: B — свои строки');
    ok(brows.every(function (r) { return r.pipeline_run_id !== 'run-100'; }),
      'B3 A→B→A: строк A в области B нет');
    const bmeta = (ctx.historyMeta || {})['chat:-200|mod_summary'];
    eq(bmeta && bmeta.rows, 1, 'B3 A→B→A: мета B помечена своими строками');

    let acalls = 0;
    ctx.api = async function () { acalls += 1;
      return { available: true, enabled: true,
        runs: [runRow('run-100b', 1700000400, 'summary', 'succeeded',
                      -100)] }; };
    methods.setActiveChat.call(ctx, -100);
    await tick();
    await tick();
    eq(acalls, 1, 'B3 A→B→A: возврат в A — свой запрос');
    const arows = methods.historyRowsFor.call(ctx, SUMMARY);
    eq(arows.length, 1, 'B3 A→B→A: в A одна своя строка');
    eq(arows[0].pipeline_run_id, 'run-100b',
      'B3 A→B→A: возврат в A показывает строки A');
    ok(arows.every(function (r) { return r.pipeline_run_id !== 'run-200'; }),
      'B3 A→B→A: строк B в A нет');
    clearStorage();
  }

  {
    // F1: поздний in-flight ответ старой области не перезаписывает новую.
    clearStorage();
    const ctx = mkCtx({ route: '#/modules/summary/history' });
    ctx._wsTabMemoryLoad();
    let calls = 0;
    const dA = deferred();
    ctx.api = function () {
      calls += 1;
      if (calls === 1) return dA.p;
      return Promise.resolve({ available: true, enabled: true,
        runs: [runRow('run-B', 1700000300, 'summary', 'succeeded',
                      -200)] });
    };
    const loadA = methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE);
    methods.setActiveChat.call(ctx, -200);
    await tick();
    await tick();
    eq(methods.historyRowsFor.call(ctx, SUMMARY)[0].pipeline_run_id, 'run-B',
      'B3 inflight: B получил свои строки');
    dA.resolve({ available: true, enabled: true,
      runs: [runRow('run-A', 1700000100, 'summary', 'succeeded',
                    -100)] });
    await loadA;
    await tick();
    eq(methods.historyRowsFor.call(ctx, SUMMARY)[0].pipeline_run_id, 'run-B',
      'B3 inflight: поздний ответ A не перезаписал строки B');
    eq(methods.historyStateFor.call(ctx, SUMMARY), 'ready',
      'B3 inflight: состояние B осталось ready');
    eq(((ctx.moduleRunsCache || {})[SUMMARY_SOURCE] || {}).scope, 'chat:-200',
      'B3 inflight: кэш остался помечен областью B');
    clearStorage();
  }

  {
    // H-6/B3: max(started_ts) СВОЕГО источника; `observed_at` — не событие.
    clearStorage();
    const ctx = mkCtx();
    const rows = [
      runRow('old', 1700000100, 'summary', 'succeeded'),
      runRow('new', 1700009000, 'summary', 'failed'),
      runRow('mid', 1700005000, 'summary', 'partial'),
    ];
    methods._wsHistoryMetaSet.call(ctx, SUMMARY, 'ready', { rows: 3 });
    ctx.moduleRuns = {}; ctx.moduleRuns[SUMMARY_SOURCE] = rows;
    const last = methods.moduleHistoryLast.call(ctx, SUMMARY);
    eq(last && last.pipeline_run_id, 'new',
      'B3: последнее событие — max(started_ts) своего источника');
    const state = methods.moduleLastEventState.call(ctx, SUMMARY);
    eq(state.kind, 'event', 'B3: последнее событие — реальный факт журнала');
    ok(state.text.indexOf('Последнее событие:') === 0,
      'B3: строка «Последнее событие» из журнала (' + state.text + ')');
    ok(state.text.indexOf('неуспешно') >= 0,
      'B3: строка несёт статус новейшего прогона');
    // Строка без started_ts (только observed_at) не выдумывает время.
    ctx.moduleRuns = {}; ctx.moduleRuns[SUMMARY_SOURCE] = [
      { pipeline_run_id: 'only-observed', observed_at: 1799999999,
        status: 'succeeded' }];
    eq(methods.moduleHistoryLast.call(ctx, SUMMARY), null,
      'B3: observed_at не является временем события');
    eq(methods.moduleLastEventState.call(ctx, SUMMARY).kind, 'unknown',
      'B3: без времени события — честное «нет данных», не выдумка');
  }

  {
    // H-4: history никогда не дефолт; pending не чистит память,
    // empty/denied/off — чистит.
    clearStorage();
    [['#/modules/summary', SUMMARY, 'mod_summary'],
     ['#/modules/random', RANDOM, 'mod_random']].forEach(function (pair) {
      const route = pair[0];
      const m = pair[1];
      const ctx = mkCtx({ route: route, activeTab: m.id });
      ctx._wsTabMemoryLoad();
      methods._wsTabMemorySet.call(ctx, 'chat:-100', m.id, 'history');
      methods._wsHistoryMetaSet.call(ctx, m, 'loading');
      eq(methods._wsTabMemoryGet.call(ctx, 'chat:-100', m), '',
        'B3 ' + m.id + ': pending не подставляет history');
      ok(memoryRaw() && memoryRaw()['chat:-100|' + m.id] === 'history',
        'B3 ' + m.id + ': pending НЕ стирает запомненный history');
      eq(methods.workspaceDefaultTab.call(ctx, m) === 'history', false,
        'B3 ' + m.id + ': history никогда не дефолт');
      methods._wsHistoryMetaSet.call(ctx, m, 'empty');
      eq(methods._wsTabMemoryGet.call(ctx, 'chat:-100', m), '',
        'B3 ' + m.id + ': empty не открывает history');
      ok(!memoryRaw() || memoryRaw()['chat:-100|' + m.id] === undefined,
        'B3 ' + m.id + ': empty стирает запись истории');
    });
    clearStorage();
  }

  {
    // H-1/B3: деталь прогона — существующий deep link по run_id; строки без
    // run_id не дают ссылки (никакой «пустой» детали).
    clearStorage();
    const ctx = mkCtx();
    const row = runRow('run /1', 1700000200);
    eq(methods.historyRowDetailHref.call(ctx, SUMMARY, row),
      '#/oversight?view=runs&run_id=run%20%2F1',
      'B3: deep link детали по run_id (с кодированием)');
    eq(methods.historyRowDetailHref.call(ctx, RANDOM,
      runRow('rrun-1', 1700000200, 'random.uses')),
      '#/oversight?view=runs&run_id=rrun-1',
      'B3 random: deep link детали по run_id');
    ok(methods.historyRowCanDetail.call(ctx, SUMMARY, row),
      'B3: строка с run_id открывает деталь');
    const noRun = { started_ts: 1700000200, status: 'succeeded' };
    eq(methods.historyRowDetailHref.call(ctx, SUMMARY, noRun), '',
      'B3: без pipeline_run_id ссылки нет');
    ok(!methods.historyRowCanDetail.call(ctx, SUMMARY, noRun),
      'B3: без pipeline_run_id деталь недоступна');
    // Источник без detail (сон/ностальгия/уроки) ссылки не получает.
    eq(methods.historyRowDetailHref.call(ctx, EXPERIENCE,
      lessonRow('L1', 1, 1700000200)), '',
      'B3: уроки не получают run-ссылку');
    eq(methods.historyRowDetailHref.call(ctx, SLEEP,
      dreamRow(1, 1700000200)), '', 'B3: сон не получает run-ссылку');
  }

  {
    // B3: фильтр по статусу прогона — чело­веческие подписи, клиентский
    // набор строк не запрашивается повторно.
    clearStorage();
    const ctx = mkCtx();
    const rows = [
      runRow('s1', 1700000200, 'summary', 'succeeded'),
      runRow('s2', 1700000100, 'summary', 'failed'),
      runRow('s3', 1700000050, 'summary', 'failed'),
    ];
    methods._wsHistoryMetaSet.call(ctx, SUMMARY, 'ready', { rows: 3 });
    ctx.moduleRuns = {}; ctx.moduleRuns[SUMMARY_SOURCE] = rows;
    const opts = methods.historyStatusOptions.call(ctx, SUMMARY);
    eq(opts.length, 2, 'B3: фильтр — два реальных статуса');
    eq(opts.filter(function (o) { return o.value === 'failed'; })[0].label,
      'неуспешно', 'B3: подпись статуса в фильтре');
    ctx.historyFilter = 'failed';
    eq(methods.historyFilteredRows.call(ctx, SUMMARY).length, 2,
      'B3: фильтр failed сужает до двух строк');
    ctx.historyFilter = '';
    eq(methods.historyFilteredRows.call(ctx, SUMMARY).length, 3,
      'B3: сброс фильтра возвращает все строки');
    // Строка события: дата · тип · чат · статус.
    const line = methods.historyRowLine.call(ctx, SUMMARY, rows[0]);
    ok(line.indexOf('Сводки') >= 0 &&
       line.indexOf('чат -100') >= 0 && line.indexOf('успешно') >= 0,
      'B3: строка события собрана из реальных полей (' + line + ')');
  }

  // ══ (18) MAC-S10-16 (W3/F-1): матрица причин пустоты — пять РАЗНЫХ UI ══
  {
    // 503 → unavailable ДЛЯ ВСЕХ ШЕСТИ источников H-1 (не off/disabled).
    clearStorage();
    const sources = [
      ['memory.dream.log', SLEEP, function (ctx) {
        return methods.loadDreamLog.call(ctx, true);
      }],
      ['memory.nostalgia.log', NOSTALGIA, function (ctx) {
        return methods.loadNostalgiaLog.call(ctx, true);
      }],
      ['factcheck.temporal.runs', FACTCHECK, function (ctx) {
        return methods.loadTemporalRuns.call(ctx, true);
      }],
      ['memory.lessons', EXPERIENCE, function (ctx) {
        return methods.loadLessons.call(ctx, true);
      }],
      [SUMMARY_SOURCE, SUMMARY, function (ctx) {
        return methods.loadModuleRuns.call(ctx, SUMMARY_SOURCE, true);
      }],
      [RANDOM_SOURCE, RANDOM, function (ctx) {
        return methods.loadModuleRuns.call(ctx, RANDOM_SOURCE, true);
      }],
    ];
    for (const [source, mod, load] of sources) {
      const ctx = mkCtx();
      ctx.api = async function () {
        const e = new Error('service unavailable'); e.status = 503; throw e;
      };
      await load(ctx);
      eq(methods.historyStateFor.call(ctx, mod), 'unavailable',
        source + ': HTTP 503 → unavailable (не off)');
      ok(methods.historyStateText.call(ctx, mod).indexOf('503') >= 0,
        source + ': текст 503 называет код');
      eq(ctx.toasts.length, 0, source + ': 503 без ложного тоста');
    }

    // Пять причин — пять разных состояний и текстов; «0 событий» нигде,
    // кроме настоящего empty. stale НЕ является состоянием журнала (в UI
    // его представляет существующий баннер 409 `[data-workspace-conflict]`).
    const ctx = mkCtx();
    const texts = {};
    [['empty', 'empty'], ['denied', 'denied'], ['unavailable', 'unavailable'],
     ['off', 'off'], ['error', 'error']].forEach(function (pair) {
      setMeta(ctx, SLEEP, pair[1]);
      texts[pair[0]] = methods.historyStateText.call(ctx, SLEEP);
    });
    eq(texts.empty, 'записей пока нет', 'empty: честный текст');
    eq(texts.denied, 'нет доступа к журналу (403)', 'denied: 403');
    eq(texts.unavailable, 'журнал временно недоступен (503) — повторите попытку',
      'unavailable: 503 + retry');
    eq(texts.off, 'журнал недоступен: функция выключена',
      'off: выключенная функция без 503');
    eq(texts.error, 'история недоступна: ошибка загрузки', 'error: ошибка');
    const uniqueTexts = Object.keys(texts).map(function (k) {
      return texts[k];
    });
    eq(new Set(uniqueTexts).size, 5,
      'пять причин должны давать пять разных текстов');
    ok(texts.off.indexOf('503') < 0,
      'off не притворяется 503: ' + texts.off);
    ok(texts.unavailable.indexOf('выключена') < 0,
      'unavailable не притворяется disabled: ' + texts.unavailable);
    ok(['denied', 'unavailable', 'off'].every(function (k) {
      return texts[k].indexOf('0 событий') < 0;
    }), '403/503/disabled не превращаются в «0 событий»');
    // stale — не состояние журнала: неизвестный код честно уходит в error,
    // а не в ready/empty (устаревшие данные не выдают себя за свежие).
    setMeta(ctx, SLEEP, 'stale');
    eq(methods.historyStateFor.call(ctx, SLEEP), 'error',
      'stale не маскируется под ready/empty в журнале');

    // Статический контракт index.html: обе поверхности (Обзор и История)
    // имеют отдельные ветки unavailable/off с разными честными текстами.
    eq((INDEX_HTML.match(/data-overview-history-state="unavailable"/g) || [])
      .length, 1, 'Обзор: ветка unavailable должна быть ровно одна');
    eq((INDEX_HTML.match(/data-module-history-state="unavailable"/g) || [])
      .length, 1, 'История: ветка unavailable должна быть ровно одна');
    ok(INDEX_HTML.indexOf('Журнал временно недоступен (503). Повторите попытку.')
       >= 0, 'Обзор: текст 503 с повтором отсутствует');
    ok(INDEX_HTML.indexOf('История временно недоступна (503). Повторите попытку.')
       >= 0, 'История: текст 503 с повтором отсутствует');
    ok(INDEX_HTML.indexOf('Журнал недоступен: функция выключена.') >= 0,
      'Обзор: текст disabled без 503 отсутствует');
    ok(INDEX_HTML.indexOf('История недоступна: функция выключена.') >= 0,
      'История: текст disabled без 503 отсутствует');
    ok(INDEX_HTML.indexOf('выключена (503)') < 0,
      'index.html: disabled всё ещё назван 503');
    // Существующий stale-маркер (design §4.6, 409) сохранён и отличен от
    // состояний журнала: отдельный DOM-маркер и отдельный текст.
    ok(INDEX_HTML.indexOf('data-workspace-conflict') >= 0 &&
       INDEX_HTML.indexOf('Настройка изменилась в другом окне') >= 0,
      'stale 409: существующий маркер/текст пропал');

    // 503 НЕ выкидывает из deep link журнала: панель остаётся с повтором.
    const ictx = mkCtx({ route: '#/modules/sleep/history' });
    setMeta(ictx, SLEEP, 'unavailable');
    methods._maybeExitHistory.call(ictx);
    eq((ictx.applied || []).length, 0,
      '503: deep link журнала не уводится на bare');
    setMeta(ictx, SLEEP, 'off');
    methods._maybeExitHistory.call(ictx);
    eq((ictx.applied || [])[0], '#/modules/sleep',
      'off: закрытый журнал по-прежнему уводит на bare');

    // Pending-память вкладки на 503 не стирается (как idle/loading/error):
    // временный отказ сервиса не отменяет выбор пользователя.
    clearStorage();
    const pctx = mkCtx({ route: '#/modules/sleep/history' });
    pctx._wsTabMemoryLoad();
    methods._wsTabMemorySet.call(pctx, 'chat:-100', SLEEP.id, 'history');
    setMeta(pctx, SLEEP, 'unavailable');
    eq(methods._wsTabMemoryGet.call(pctx, 'chat:-100', SLEEP), '',
      'unavailable: history не применяется');
    ok(!!memoryRaw()['chat:-100|mod_sleep'],
      'unavailable: запись истории НЕ удалена');
    clearStorage();
  }

  console.log('MOD-ACL-UX-M4A-W2B-HISTORY-OK — ' + checks + ' проверок');
  process.exit(0);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
