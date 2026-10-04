'use strict';
/* EXTRA round1029 (extra-cover-style-pipeline, ADR-1028-4 D12;
 * spec §5/§56/§57/§75) — Style Editor UI (реальная логика web/app.js).
 *
 * Проверяет:
 *   (a) вкладка 'styles' объявлена у mod_summary + RU-подпись;
 *   (b) workspaceTabHasContent(mod_summary,'styles') === true;
 *   (c) данные coverStyles объявлены структурно;
 *   (d) методы редактора существуют и fail-open (budget без метаданных — без
 *       ложных чисел; RU-лейбл режимов пайплайна);
 *   (e) capability-строки содержат edit/limits/source (§37);
 *   (f) watch('workspaceTab') для 'styles' вызывает loadCoverStyles;
 *   (g) маршрут section — `#/modules/summary/styles`.
 *
 * Запуск: node tests/js/round1029_extra_cover_styles_test.js
 */
const path = require('path');
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
const MODULES = data.modules;

function moduleById(id) {
  return MODULES.filter(function (m) { return m.id === id; })[0];
}

// (a) вкладка + RU-подпись
const summary = moduleById('mod_summary');
assert.ok(summary.tabs.indexOf('styles') >= 0, 'a: mod_summary.tabs содержит styles');
assert.strictEqual(methods.workspaceTabLabel('styles'), 'Стили обложки',
  'a: RU-подпись вкладки');

// (b) применимость вкладки
assert.strictEqual(methods.workspaceTabHasContent.call({}, summary, 'styles'),
  true, 'b: вкладка styles применима');

// (c) данные coverStyles
const cs = data.coverStyles;
assert.ok(cs && typeof cs === 'object', 'c: coverStyles объявлен');
assert.strictEqual(cs.selectedStyleId, '', 'c: выбран пустой стиль по умолчанию');
assert.strictEqual(cs.noStyleLabel, 'Без дополнительного стиля', 'c: ярлык без стиля');
assert.ok(Array.isArray(cs.styles), 'c: styles — массив');

// (d) методы редактора
['loadCoverStyles', 'coverStyleOpen', 'coverStyleNew', 'coverStyleSave',
 'coverStyleDuplicate', 'coverStyleDelete', 'coverStyleUploadReference',
 'coverStyleRemoveReference', 'coverStyleReplaceReference', 'coverStylePreview',
 'coverStyleSetSelection', 'openCoverConnections', '_applyConfigFocus',
 'coverStyleRefreshExample', 'coverBudgetText', 'coverCapabilityLines',
 'coverPipelineModeLabel', 'coverAssetBlob', 'fileToBase64'
].forEach(function (name) {
  assert.strictEqual(typeof methods[name], 'function', 'd: метод ' + name);
});

// (d2) RU-лейбл режима пайплайна
assert.ok(methods.coverPipelineModeLabel('generate_then_edit').indexOf('обработка') >= 0,
  'd2: режим generate_then_edit — RU');
assert.ok(methods.coverPipelineModeLabel('generate_only').length > 0,
  'd2: режим generate_only — подпись есть');

// (d3) budget без метаданных — без ложных чисел + честный unknown (§9)
const budgetText = methods.coverBudgetText.call(
  { coverStyles: { meta: null, limitMode: 'auto', limitValue: null },
    coverLimitText: methods.coverLimitText });
assert.strictEqual(
  budgetText,
  'Инструкция: 0 символов · Лимит текущей модели: неизвестно',
  'd3: unknown-limit без ложного числа');

// (e) capability-строки (§37)
const ctxCaps = {
  coverStyles: {
    meta: {
      capabilities: {
        image_edit: 'yes', text_to_image: 'yes', max_input_images: 3,
        references_available: 2, async_jobs: false, source: 'provider_or_registry',
        prompt_limit: { value: 1000, unit: 'chars', source: 'internal_config' },
        supported_sizes: ['1024x1024'],
      },
    },
  },
};
const lines = methods.coverCapabilityLines.call(ctxCaps);
assert.ok(lines.some(function (l) { return l.indexOf('Редактирование') >= 0; }),
  'e: capability — edit');
assert.ok(lines.some(function (l) { return l.indexOf('Лимит инструкции') >= 0; }),
  'e: capability — prompt limit');
assert.ok(lines.some(function (l) { return l.indexOf('Источник capability') >= 0; }),
  'e: capability — source');
assert.ok(lines.some(function (l) { return l.indexOf('async') >= 0 || l.indexOf('sync') >= 0; }),
  'e: capability — sync/async');

// (f) watch: 'styles' → loadCoverStyles
const watchFn = captured.watch.workspaceTab;
let called = 0;
watchFn.call({ loadCoverStyles() { called += 1; },
               maybeLoadSummaryTest() {} }, 'styles');
assert.strictEqual(called, 1, 'f: watch(styles) вызывает loadCoverStyles');

// (g) deep-link §35: фокус на «Обработка стилей обложки» + контекст редактора
assert.strictEqual(cs._returnProfileId, '', 'g: return-контекст объявлен');
const dlCtx = {
  coverStyles: { current: { profile_id: 'csp_x' }, _returnProfileId: '' },
  configFocusGroup: '', toast() {}, _applyConfigFocus() {},
};
methods.openCoverConnections.call(dlCtx);
assert.strictEqual(dlCtx.configFocusGroup, 'models_images',
  'g: целевая группа — models_images');
assert.strictEqual(dlCtx.coverStyles._returnProfileId, 'csp_x',
  'g: контекст редактора сохранён');
assert.strictEqual(global.window.location.hash, '#/ai/llm',
  'g: маршрут подключений');

console.log('EXTRA-COVER-STYLES-UI-OK');
