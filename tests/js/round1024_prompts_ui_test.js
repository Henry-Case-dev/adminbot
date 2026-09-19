'use strict';
/* F6 round1024 (prompts-refactor-accordion-modes-round1024, ADR-1024-10) —
 * РЕАЛЬНЫЙ JS-тест вкладки «Промпты» после рефакторинга:
 *   - плоский grid: advanced-элемент доступен сразу (promptVisibleItems);
 *   - fallback-режим: битое/пустое значение → `casual`;
 *   - табы режимов внутри карточек модулей (общий selectPromptMode).
 *
 * Запуск: node tests/js/round1024_prompts_ui_test.js  → PROMPTS-UI-UNIT-OK
 */
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component(name, compOpts) {
        global.__components = global.__components || {};
        global.__components[name] = compOpts;
      },
      provide() {}, use() {}, mount() {},
    };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    return { tagName: tag, className: '', value: '', style: {},
             setAttribute() {}, focus() {}, select() {}, remove() {} };
  },
  body: { appendChild() {}, removeChild() {} },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('x'); } } },
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

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
assert(methods, 'root.methods не найден');

// ── 1. promptVisibleItems: плоский grid вместо аккордеона ────────────────────
(function () {
  const sec = {
    id: 'verbalizer',
    basic: [{ key: 'b1' }, { key: 'b2' }],
    advanced: [{ key: 'a1' }],
  };
  // V2 ON: basic + advanced в одном списке — одиночный advanced виден сразу.
  const on = methods.promptVisibleItems.call({ uiFlag: function () { return true; } }, sec);
  assert.strictEqual(on.length, 3);
  assert.deepStrictEqual(on.map(function (i) { return i.key; }), ['b1', 'b2', 'a1']);
  // V2 OFF: только basic (advanced остаётся под <details> 10.23).
  const off = methods.promptVisibleItems.call({ uiFlag: function () { return false; } }, sec);
  assert.deepStrictEqual(off.map(function (i) { return i.key; }), ['b1', 'b2']);
  // Нет секции — пусто (без падения).
  assert.strictEqual(methods.promptVisibleItems.call({ uiFlag: function () { return true; } }, null).length, 0);
})();

// ── 2. promptSections остаётся источником секций (flat-проекция работает) ────
(function () {
  const ctx = {
    itemAdvanced: function (it) { return !!it.advanced; },
    promptStageItems: methods.promptStageItems,
    promptOtherItems: methods.promptOtherItems,
  };
  const secs = methods.promptSections.call(ctx, { items: [
    { key: 'v', stage: 'verbalizer', advanced: true }] });
  assert.deepStrictEqual(secs.map(function (s) { return s.id; }), ['verbalizer']);
  const flat = methods.promptVisibleItems.call(
    { uiFlag: function () { return true; } }, secs[0]);
  assert.strictEqual(flat.length, 1);
  assert.strictEqual(flat[0].key, 'v');
})();

// ── 3. Fallback-режим: sync при пустом/битом значении → casual ───────────────
(function () {
  const tabs = captured.computed.promptModeTabs.call({});
  assert.deepStrictEqual(tabs.map(function (t) { return t.id; }),
    ['casual', 'serious', 'deep_research']);

  // 3.1 Валидное значение — приоритетно.
  const ctxValid = {
    promptMode: 'casual', promptModeTabs: tabs,
    configItems: [{ key: 'prompts.verbilizer_default_mode', value: 'deep_research' }],
    promptDefaultModeItem: methods.promptDefaultModeItem,
  };
  methods._syncPromptModeFromConfig.call(ctxValid);
  assert.strictEqual(ctxValid.promptMode, 'deep_research');

  // 3.2 Битое значение → casual (а не serious).
  const ctxBad = {
    promptMode: 'serious', promptModeTabs: tabs,
    configItems: [{ key: 'prompts.verbilizer_default_mode', value: 'bogus' }],
    promptDefaultModeItem: methods.promptDefaultModeItem,
  };
  methods._syncPromptModeFromConfig.call(ctxBad);
  assert.strictEqual(ctxBad.promptMode, 'casual');

  // 3.3 Пустое/отсутствующее значение → casual.
  const ctxEmpty = {
    promptMode: 'serious', promptModeTabs: tabs,
    configItems: [], promptDefaultModeItem: methods.promptDefaultModeItem,
  };
  methods._syncPromptModeFromConfig.call(ctxEmpty);
  assert.strictEqual(ctxEmpty.promptMode, 'casual');
})();

// ── 4. Табы в карточке: переключение режима + автосейв выбранного ────────────
(function () {
  const defaultItem = { key: 'prompts.verbilizer_default_mode', value: 'casual' };
  const saved = [];
  const ctx = {
    promptMode: 'casual',
    configItems: [defaultItem],
    canEditConfig: function () { return true; },
    saveConfigItem: function (it) { saved.push(it.value); },
    promptDefaultModeItem: methods.promptDefaultModeItem,
  };
  methods.selectPromptMode.call(ctx, 'serious');
  assert.strictEqual(ctx.promptMode, 'serious');
  assert.strictEqual(defaultItem.value, 'serious');
  assert.deepStrictEqual(saved, ['serious']);
  // Повторный клик по тому же табу — без повторного сохранения.
  methods.selectPromptMode.call(ctx, 'serious');
  assert.deepStrictEqual(saved, ['serious']);
})();

console.log('PROMPTS-UI-UNIT-OK');
