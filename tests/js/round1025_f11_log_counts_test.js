'use strict';
/* F11 round1025 (§20/D5, H-F11S-1) — поведенческий тест счётчиков
 * «Ошибки: N · Предупреждения: N».
 *
 * Регресс-защита: счётчики НЕ ограничены limit (раньше при limit=1 максимум
 * был 1) и считаются по аддитивному `counts` сервера, где ERROR и WARNING —
 * независимые (не «warn и выше») числа. Тест требует count > 1.
 *
 * Запуск: node tests/js/round1025_f11_log_counts_test.js → F11-LOG-COUNTS-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

// ── Минимальный stubbed-контекст (по образцу round1025_f11_status_grid_test.js)
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

async function main() {
  assert.ok(methods.loadLogCounts, '§20: loadLogCounts есть');

  // 1) Реальные числа (count > 1) + WARNING не вбирает ERROR.
  const calls = [];
  const ctx = {
    logErrorCount: null, logWarnCount: null,
    api: function (url) {
      calls.push(url);
      return Promise.resolve({
        count: 1, logs: [],
        counts: { ERROR: 5, WARNING: 2, INFO: 9 },
      });
    },
  };
  await methods.loadLogCounts.call(ctx);
  assert.strictEqual(calls.length, 1, '§20: один лёгкий запрос за счётчики');
  assert.ok(calls[0].indexOf('level=ALL') >= 0, '§20: запрос без лимитной фильтрации');
  assert.strictEqual(ctx.logErrorCount, 5, '§20: реальное число ошибок (count > 1)');
  assert.strictEqual(ctx.logWarnCount, 2, '§20: реальное число WARN (count > 1)');
  assert.notStrictEqual(ctx.logWarnCount, 7,
    '§20: «Предупреждения» — только WARNING, ошибки не вбирает');

  // 2) Нет `counts` (старый/недоступный ответ) → «—», не выдуманный 0.
  const ctx2 = {
    logErrorCount: null, logWarnCount: null,
    api: function () { return Promise.resolve({ count: 1, logs: [] }); },
  };
  await methods.loadLogCounts.call(ctx2);
  assert.strictEqual(ctx2.logErrorCount, null, '§20: нет counts → «—»');
  assert.strictEqual(ctx2.logWarnCount, null, '§20: нет counts → «—»');

  // 3) Ошибка сети → «—» (не падаем, не врём нулём).
  const ctx3 = {
    logErrorCount: 9, logWarnCount: 9,
    api: function () { return Promise.reject(new Error('offline')); },
  };
  await methods.loadLogCounts.call(ctx3);
  assert.strictEqual(ctx3.logErrorCount, null, '§20: fail-open → «—»');
  assert.strictEqual(ctx3.logWarnCount, null, '§20: fail-open → «—»');

  console.log('F11-LOG-COUNTS-OK');
}

main().catch(function (err) {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
