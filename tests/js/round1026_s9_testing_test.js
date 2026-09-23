'use strict';
/* S9 round1026 (ADR-1026-8 D1/D3/D8, §113) — UI-маркеры вкладки «Тестирование»
 * модуля «Сводки чатов».
 *
 * Проверяет РЕАЛЬНУЮ логику web/app.js (не grep):
 *   (a) data().summaryTest — форма состояния (available/chatId/hours/result…);
 *   (b) computed.summaryTestVisible: только mod_summary + tab testing +
 *       available===true (env-флаг OFF → probe 404 → available=false → скрыто);
 *   (c) пресеты окна 6/12/24/72/168;
 *   (d) методы dry-run-прогона существуют и используют API тест-контура;
 *   (e) маршрут `#/modules/summary/testing` валиден, tab-id УЖЕ объявлен
 *       (Δ каталога=0 — новый не вводится);
 *   (f) index.html содержит секцию/форму/метрики/обложку и dry-run-пометки;
 *   (g) B-R1026S9-2: guard error-пути — computed summaryTestMetrics/
 *       summaryTestArtifacts не роняют рендер на неполном payload;
 *   (h) §112: «Процент отсева» (summaryTestDropPercent: null → «Нет данных»).
 *
 * Запуск: node tests/js/round1026_s9_testing_test.js
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
const _storage = {
  _s: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
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
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const data = captured.data();
const methods = captured.methods;
const computed = captured.computed;
const MODULES = data.modules;
const TABS = data.tabs;

function moduleById(id) {
  return MODULES.filter(function (m) { return m.id === id; })[0];
}

(function run() {
  // ── (a) форма состояния ───────────────────────────────────────────────
  {
    const st = data.summaryTest;
    assert.ok(st && typeof st === 'object', 'a: summaryTest присутствует');
    assert.strictEqual(st.available, null, 'a: available=null до probe');
    assert.strictEqual(st.running, false, 'a: running=false');
    assert.strictEqual(st.result, null, 'a: result=null');
    assert.strictEqual(typeof st.hours, 'number', 'a: hours число');
  }

  // ── (b) видимость секции ──────────────────────────────────────────────
  {
    const base = { workspace: { module: moduleById('mod_summary'),
      tab: 'testing' }, summaryTest: { available: true } };
    assert.strictEqual(computed.summaryTestVisible.call(base), true,
      'b: mod_summary+testing+available → видно');

    const off = { workspace: { module: moduleById('mod_summary'),
      tab: 'testing' }, summaryTest: { available: false } };
    assert.strictEqual(computed.summaryTestVisible.call(off), false,
      'b: флаг OFF (404) → секция скрыта');

    const otherTab = { workspace: { module: moduleById('mod_summary'),
      tab: 'overview' }, summaryTest: { available: true } };
    assert.strictEqual(computed.summaryTestVisible.call(otherTab), false,
      'b: другая вкладка → скрыто');

    const otherModule = { workspace: { module: moduleById('mod_factcheck'),
      tab: 'testing' }, summaryTest: { available: true } };
    assert.strictEqual(computed.summaryTestVisible.call(otherModule), false,
      'b: другой модуль → скрыто');
  }

  // ── (c) пресеты окна ──────────────────────────────────────────────────
  {
    assert.deepStrictEqual(computed.summaryTestWindows.call({}),
      [6, 12, 24, 72, 168], 'c: пресеты 6/12/24/72/168');
  }

  // ── (d) методы dry-run-прогона ────────────────────────────────────────
  {
    ['maybeLoadSummaryTest', 'summaryTestRun', 'summaryTestPoll',
     'summaryTestConfirmCover'].forEach(function (name) {
      assert.strictEqual(typeof methods[name], 'function', 'd: метод ' + name);
    });
    const src = fs.readFileSync(
      path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
    assert.ok(src.indexOf('/api/summary/test/run') >= 0,
      'd: запуск через API тест-контура');
    assert.ok(src.indexOf('/api/summary/test/availability') >= 0,
      'd: probe доступности');
    assert.ok(src.indexOf('/cover') >= 0, 'd: подтверждение обложки');
    // probe идемпотентен (не дёргает API повторно при available!=null).
    const ctx = { workspace: { module: moduleById('mod_summary'),
      tab: 'testing' }, summaryTest: { available: true }, api() {
        throw new Error('не должен вызываться'); } };
    methods.maybeLoadSummaryTest.call(ctx);   // no-throw
    // default ON (D8): probe дёргается при available=null → API доступен →
    // секция видима без ручного включения флага.
    let probedUrl = null;
    const onCtx = { workspace: { module: moduleById('mod_summary'),
      tab: 'testing' },
      summaryTest: { available: null, _probing: false, chatId: null },
      accessChats: [],
      api(url) { probedUrl = url; return Promise.resolve({ enabled: true }); } };
    methods.maybeLoadSummaryTest.call(onCtx);
    assert.strictEqual(probedUrl, '/api/summary/test/availability',
      'd: default ON → probe доступности вызывается');
    assert.strictEqual(onCtx.summaryTest._probing, true, 'd: probe идёт');
  }

  // ── (e) маршрут и уже объявленный tab-id (Δ каталога=0) ───────────────
  {
    const tabs = moduleById('mod_summary').tabs;
    assert.ok(tabs.indexOf('testing') >= 0,
      'e: tab-id testing УЖЕ объявлен (новый не вводится)');
    const ws = captured.computed.workspace;
    const ctx = {
      route: '#/modules/summary/testing', iaV2: true, me: { role_name: 'admin' },
      activeTab: 'status', tabs: TABS, modules: MODULES,
      canViewTab() { return true; }, _flagTabHidden: methods._flagTabHidden,
      toast() {}, syncBackButton() {}, setTab(id) { this.activeTab = id; },
    };
    methods.applyRoute.call(ctx, '#/modules/summary/testing');
    assert.strictEqual(ctx.route, '#/modules/summary/testing',
      'e: маршрут принят');
    const parsed = ws.call(ctx);
    assert.strictEqual(parsed.module.id, 'mod_summary', 'e: модуль Сводок');
    assert.strictEqual(parsed.tab, 'testing', 'e: вкладка testing');
  }

  // ── (f) маркеры index.html ────────────────────────────────────────────
  {
    const html = fs.readFileSync(
      path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
    ['data-summary-test', 'data-summary-test-run',
     'data-summary-test-chat', 'data-summary-test-window',
     'data-summary-test-notice', 'data-summary-test-result',
     'data-summary-test-metrics', 'data-summary-test-diagnostics',
     'data-summary-test-cover', 'summaryTestRun', 'summaryTestVisible',
     'Проверить пайплайн', 'не публикуется', 'не изменяется'
    ].forEach(function (marker) {
      assert.ok(html.indexOf(marker) >= 0, 'f: маркер ' + marker);
    });
    // §112/B-R1026S9-1: «Процент отсева» реально рендерится в UI.
    assert.ok(html.indexOf('Процент отсева') >= 0, 'f: метрика «Процент отсева»');
    assert.ok(html.indexOf('data-summary-test-drop') >= 0,
      'f: маркер строки отсева');
    // B-R1026S9-2: метрики/артефакты обёрнуты в guard (v-if на computed).
    assert.ok(html.indexOf('v-if="summaryTestMetrics"') >= 0,
      'f: guard метрик на error-пути');
    assert.ok(html.indexOf('v-if="summaryTestArtifacts"') >= 0,
      'f: guard артефактов на error-пути');
  }

  // ── (g) B-R1026S9-2: guard error-пути ─────────────────────────────────
  {
    assert.strictEqual(typeof computed.summaryTestMetrics, 'function',
      'g: computed summaryTestMetrics');
    assert.strictEqual(typeof computed.summaryTestArtifacts, 'function',
      'g: computed summaryTestArtifacts');

    // error-путь: сервер отдал result без metrics/artifacts → guard = null,
    // шаблон не читает undefined.l1 (нет TypeError).
    const errCtx = { summaryTest: { result: { status: 'error',
      diagnostics: [{ stage: 'init', code: 'TEST_NO_GENERATOR' }] } } };
    assert.strictEqual(computed.summaryTestMetrics.call(errCtx), null,
      'g: error-payload без metrics → guard null (без падения)');
    assert.strictEqual(computed.summaryTestArtifacts.call(errCtx), null,
      'g: error-payload без artifacts → guard null');

    // неполные структуры (частичный payload) тоже безопасны.
    const partial = { summaryTest: { result: { status: 'error',
      metrics: { source_count: 0 }, artifacts: { source: [] } } } };
    assert.strictEqual(computed.summaryTestMetrics.call(partial), null,
      'g: частичные metrics → null');
    assert.strictEqual(computed.summaryTestArtifacts.call(partial), null,
      'g: частичные artifacts → null');

    // валидный полный payload (полные пустые структуры сервера) → не null.
    const full = { summaryTest: { result: { status: 'error',
      metrics: { tokens: { l1: {}, l2: {}, total: {} }, cost: {}, budget: {} },
      artifacts: { source: [], filtered: [], clusters: [] } } } };
    assert.ok(computed.summaryTestMetrics.call(full),
      'g: полные структуры → guard пропускает');
    assert.ok(computed.summaryTestArtifacts.call(full),
      'g: полные артефакты → guard пропускает');
  }

  // ── (h) §112: «Процент отсева» ────────────────────────────────────────
  {
    assert.strictEqual(typeof computed.summaryTestDropPercent, 'function',
      'h: computed summaryTestDropPercent');
    const noMetrics = { summaryTest: { result: { status: 'error' } } };
    assert.strictEqual(
      computed.summaryTestDropPercent.call(noMetrics), 'Нет данных',
      'h: нет метрик → «Нет данных»');
    const nullDrop = { summaryTest: { result: { metrics: {
      tokens: { l1: {}, l2: {}, total: {} }, cost: {}, budget: {},
      drop_percent: null } } } };
    assert.strictEqual(
      computed.summaryTestDropPercent.call(nullDrop), 'Нет данных',
      'h: drop_percent=null → «Нет данных» (без выдуманного 0)');
    const withDrop = { summaryTest: { result: { metrics: {
      tokens: { l1: {}, l2: {}, total: {} }, cost: {}, budget: {},
      drop_percent: 12.5 } } } };
    assert.strictEqual(
      computed.summaryTestDropPercent.call(withDrop), '12.5%',
      'h: drop_percent=12.5 → «12.5%»');
  }

  console.log('SUMMARY-TESTING-UI-OK');
  process.exit(0);
})();
