'use strict';
/* ASAP 8 v6 P1 — D09 (§18F, панели): «Последние сны» показывают
 * failure/deferred причины человекочитаемо (D09.5, минимально —
 * существующие поля UI).
 *
 * Контракт:
 * - dreamStatusLabel: известный статус → русская причина
 *   (cluster_deferred/budget_skip/window_skip/error/…); неизвестный —
 *   честный raw (не пустота и не «unknown»).
 * - dreamStatusBadgeClass: ok+distilled → badge-ok; нейтральные
 *   (unchanged/duplicate/disabled) → badge-muted; прочее (ошибки,
 *   скипы, очередь) → badge-warn.
 *
 * Запуск: node tests/js/asap8_v6_p1_d09_panels_test.js
 *         (печатает P1-D09-PANELS-UNIT-OK)
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
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; },
};
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {}, remove() {},
    };
  },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = {
  _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; },
};
global.localStorage = {
  _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured && captured.methods, 'Vue.createApp должен быть вызван');
const M = captured.methods;
const ctx = {
  dreamStatusLabel: M.dreamStatusLabel,
  dreamStatusBadgeClass: M.dreamStatusBadgeClass,
};

// deferred-очередь групп — человекочитаемая причина (M8-хвост виден)
assert(/отложен/i.test(ctx.dreamStatusLabel('cluster_deferred')),
  'cluster_deferred должен объясняться как отложенная группа');
// failure/deferred причины сна/глубокого сна
assert(/лимит/i.test(ctx.dreamStatusLabel('budget_skip')));
assert(/окна/i.test(ctx.dreamStatusLabel('window_skip')));
assert(/ошибка/i.test(ctx.dreamStatusLabel('error')));
assert(/дубликат/i.test(ctx.dreamStatusLabel('duplicate')));
assert(/опор/i.test(ctx.dreamStatusLabel('no_anchors')));
// нейтральные
assert(!ctx.dreamStatusLabel('ok'), 'ok — без причины (пусто)');
// неизвестный код — честный raw, не пустота
assert.strictEqual(ctx.dreamStatusLabel('some_new_code'), 'some_new_code');
assert.strictEqual(ctx.dreamStatusLabel(null), '');

// бейджи: успех/нейтральное/внимание
assert.strictEqual(ctx.dreamStatusBadgeClass(
  { kind: 'distilled', status: 'ok' }), 'badge-ok');
assert.strictEqual(ctx.dreamStatusBadgeClass(
  { kind: 'run', status: 'ok' }), 'badge-muted');
assert.strictEqual(ctx.dreamStatusBadgeClass(
  { kind: 'skipped', status: 'unchanged' }), 'badge-muted');
assert.strictEqual(ctx.dreamStatusBadgeClass(
  { kind: 'skipped', status: 'cluster_deferred' }), 'badge-warn');
assert.strictEqual(ctx.dreamStatusBadgeClass(
  { kind: 'deep_skip', status: 'error' }), 'badge-warn');

console.log('P1-D09-PANELS-UNIT-OK');
