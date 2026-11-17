'use strict';
/* MOD-ACL-UX-01 M4A W2b-B1 (2.58.212) — «История» для «Сна»/«Ностальгии».

Предмет: `memory.dream.log` + `memory.nostalgia.log` на СУЩЕСТВУЮЩИХ
read-API (brief W2b §2–§3, контракты H-1…H-7):
  1) presentation-map HISTORY_SOURCES: dream/nostalgia; неизвестный source —
     ни запроса, ни вкладки (fail-closed);
  2) одно состояние на `scopeKey + moduleId` (`idle|loading|ready|empty|
     denied|off|error`): 403 → denied, 503/available:false → off, сеть →
     error; никогда «0 событий» вместо 403;
  3) вкладка `history` видна ТОЛЬКО при `status==='ready' && rows>0`;
     у sleep/nostalgia объявлена, у остальных модулей — нет;
  4) `history` никогда не дефолт; pending не удаляет запомненный history,
     удаление — только при empty/denied/off;
  5) `moduleLastEventState` для sleep/nostalgia — max(ts) своего журнала,
     `observed_at` активностью не становится, чужая область не подставляется;
  6) один автоматический фетч на источник (`_ensureModuleData`), без поллера;
     явное обновление остаётся возможным;
  7) статические срезы: панель `data-module-history`, фильтр, ровно один ряд
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
const SLEEP = moduleById('mod_sleep');
const NOSTALGIA = moduleById('mod_nostalgia');

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
    moduleTabMemory: {},
    historyMeta: {},
    historyFilter: '',
    dreamLog: [],
    nostalgiaLog: [],
    dreamBeliefs: [{ id: 1 }],
    memoryRagBusy: false,
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
  // ══ (1) Статические срезы W2b-B1 ═══════════════════════════════════════
  {
    // history объявлена ТОЛЬКО у sleep/nostalgia.
    [SLEEP, NOSTALGIA].forEach(function (m) {
      ok((m.tabs || []).indexOf('history') >= 0,
        m.id + ': history не объявлена в tabs');
    });
    MODULES.forEach(function (m) {
      if (m.id === 'mod_sleep' || m.id === 'mod_nostalgia') return;
      ok((m.tabs || []).indexOf('history') < 0,
        m.id + ': history не должна быть объявлена');
    });
    ok(APP_JS.indexOf('history: \'История\'') >= 0,
      'подпись history: «История» отсутствует');
    ok(APP_JS.indexOf('historyMeta: {}') >= 0,
      'data(): historyMeta отсутствует');
    ok(APP_JS.indexOf('HISTORY_SOURCES') >= 0 &&
       APP_JS.indexOf('memory.dream.log') >= 0 &&
       APP_JS.indexOf('memory.nostalgia.log') >= 0,
      'HISTORY_SOURCES не содержит dream/nostalgia');
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
    // 503 → off; 200 available:false → off; сеть → error.
    const ctx = mkCtx();
    ctx.api = async function () {
      const e = new Error('unavailable');
      e.status = 503;
      throw e;
    };
    await methods.loadDreamLog.call(ctx);
    eq(methods.historyStateFor.call(ctx, SLEEP), 'off', '503 → off');
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

  console.log('MOD-ACL-UX-M4A-W2B-HISTORY-OK — ' + checks + ' проверок');
  process.exit(0);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
