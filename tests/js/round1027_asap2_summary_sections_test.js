'use strict';
/* ASAP-2 round1027 (mca-asap2-summary-pipeline, §13/DoD-11, T-3960) —
 * поведенческий тест двух workspace-секций Саммаризации в СУЩЕСТВУЮЩЕМ
 * мини-аппе (web/app.js). Новых маршрутов/endpoint/панелей нет.
 *
 * Проверяет:
 *   S1  карта вкладок mod_summary содержит ОТДЕЛЬНЫЕ 'hybrid'/'legacy';
 *       подписи вкладок — «HYBRID SUMMARY» / «LEGACY SUMMARY FALLBACK»;
 *   S2/S3/S4  маппинг групп (workspaceGroupTab): группы Hybrid → 'hybrid',
 *       группы Legacy → 'legacy'; id-маппинг важнее категории (модели
 *       hybrid НЕ уезжают на вкладку models); общие группы — ВНЕ секций
 *       (cross-isolation DOM-механики S4);
 *   S6  workspaceTabHasContent: 'hybrid'/'legacy' рендерятся только при
 *       наличии своих групп.
 *
 * Подпись MAX_SUMMARY_PARTS (verbatim §13) и состав секций по каталогу
 * сверяются python-тестом tests/test_summary_asap2_miniapp_round1027.py.
 *
 * Запуск: node tests/js/round1027_asap2_summary_sections_test.js
 *         → ASAP2-SUMMARY-SECTIONS-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const APP = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  matchMedia: function () { return { matches: false, addEventListener() {} }; },
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {}, remove() {},
      getContext() { return null; },
    };
  },
  body: { appendChild() {}, removeChild() {} },
  execCommand() { return true; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = {
  _s: {},
  getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods || {};

function main() {
  // ── S1: витрина (текст app.js: карта вкладок + подписи) ───────────────────
  assert.ok(/mod_summary: \[[^\]]*'hybrid'[^\]]*'legacy'[^\]]*\]/.test(APP),
    'S1: mod_summary tabs содержат отдельные hybrid и legacy');
  assert.ok(/hybrid: 'HYBRID SUMMARY'/.test(APP), 'S1: подпись HYBRID SUMMARY');
  assert.ok(/legacy: 'LEGACY SUMMARY FALLBACK'/.test(APP),
    'S1: подпись LEGACY SUMMARY FALLBACK');

  // ── S2/S3/S4: workspaceGroupTab — маппинг групп вкладки ──────────────────
  const wt = methods.workspaceGroupTab;
  assert.ok(typeof wt === 'function', 'workspaceGroupTab есть');
  const SUMMARY_TABS = ['overview', 'settings', 'prep', 'clusterizer',
                        'writer', 'hybrid', 'legacy', 'models', 'limits',
                        'testing'];
  const summary = { id: 'mod_summary', tab: 'mod_summary',
                    tabs: SUMMARY_TABS };
  const group = (id, category) => ({ id: id, category: category });
  const hybrid = [
    ['flags_summary_hybrid', 'flags'],
    ['models_summary_hybrid', 'models'],
    ['limits_summary_hybrid', 'limits'],
  ];
  const legacy = [
    ['flags_summary_legacy', 'flags'],
    ['limits_summary_legacy', 'limits'],
  ];
  hybrid.forEach(function (pair) {
    assert.strictEqual(wt.call({}, summary, group(pair[0], pair[1])), 'hybrid',
      'S2/S4: ' + pair[0] + ' → hybrid');
  });
  legacy.forEach(function (pair) {
    assert.strictEqual(wt.call({}, summary, group(pair[0], pair[1])), 'legacy',
      'S3/S4: ' + pair[0] + ' → legacy');
  });
  // S4 cross-isolation: ни одна hybrid-группа не попадает в legacy и наоборот
  // (проверено выше на полном составе групп) + общие группы ВНЕ секций:
  assert.strictEqual(wt.call({}, summary, group('limits_summary', 'limits')),
    'limits', 'S4: limits_summary — вне секций');
  assert.strictEqual(wt.call({}, summary, group('flags_summary', 'flags')),
    'settings', 'S4: flags_summary — вне секций');
  assert.strictEqual(wt.call(
    {}, summary, group('limits_summary_filter', 'limits')), 'prep',
    'S4: limits_summary_filter — prep (как раньше)');
  assert.strictEqual(wt.call({}, summary, group('models_main', 'models')),
    'models', 'S4: чужие модели — по-прежнему models');

  // ── S6: вкладка рендерится только при наличии своих групп ─────────────────
  const has = methods.workspaceTabHasContent;
  assert.ok(typeof has === 'function', 'workspaceTabHasContent есть');
  function ctx(groups) {
    return {
      tabs: ['overview', 'settings', 'prep', 'clusterizer', 'writer',
             'hybrid', 'legacy', 'models', 'limits', 'testing'],
      workspaceGroupTab: wt,
      groupedForTab: function () {
        return { groups: groups };
      },
      _workspaceGroupsFor: function (m, tabId) {
        const self = this;
        return groups.filter(function (g) {
          return self.workspaceGroupTab(m, g) === tabId;
        });
      },
      workspacePromptItems: function () { return []; },
      workspaceModelGroups: [],
      workspaceTestingBlocks: [],
    };
  }
  assert.strictEqual(
    has.call(ctx([group('flags_summary_hybrid', 'flags')]), summary, 'hybrid'),
    true, 'S6: hybrid с содержимым');
  assert.strictEqual(
    has.call(ctx([group('flags_summary_hybrid', 'flags')]), summary, 'legacy'),
    false, 'S6: legacy без своих групп — не рендерится');
  assert.strictEqual(
    has.call(ctx([group('limits_summary_legacy', 'limits')]), summary, 'legacy'),
    true, 'S6: legacy с содержимым');

  console.log('ASAP2-SUMMARY-SECTIONS-OK');
}

main();
