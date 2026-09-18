'use strict';
/* F2 round1022 (urgent-summary-aliases-ui-round1022, ADR-1022-2) — РЕАЛЬНЫЙ
 * JS-тест KV-редактора `limits.summary_aliases` (widget='keyvalue').
 *
 * Проверяет, что `kv-editor.sync()` пересобирает пары «Telegram ID → имя» из
 * ЛЮБОЙ формы значения, которую может отдать backend:
 *   - объект (норма);
 *   - строка JSON (двойное кодирование jsonb) — распаковывается;
 *   - двойная строка JSON — распаковывается до 2 уровней;
 *   - пустой объект → 0 пар;
 *   - не-JSON строка / массив / null → безопасно 0 пар (без исключения).
 *
 * Запуск: node tests/js/round1022_aliases_test.js  (печатает ALIASES-UNIT-OK)
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
const _bodyChildren = [];
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    const el = {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() {
        const idx = _bodyChildren.indexOf(el);
        if (idx >= 0) _bodyChildren.splice(idx, 1);
        if (global.window.__adminbotClipGhost === el) {
          global.window.__adminbotClipGhost = null;
        }
      },
    };
    return el;
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) {
      const idx = _bodyChildren.indexOf(el);
      if (idx >= 0) _bodyChildren.splice(idx, 1);
      return el;
    },
  },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: {
    clipboard: { writeText: async function () { throw new Error('no clipboard'); } },
  },
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

const kv = (global.__components || {})['kv-editor'];
assert(kv && kv.methods && typeof kv.methods.sync === 'function',
  'не найден компонент kv-editor/sync (binding сломан)');

function syncPairs(value) {
  const ctx = { item: { value: value }, pairs: [] };
  kv.methods.sync.call(ctx);
  return ctx.pairs;
}

function pairsToObject(pairs) {
  const out = {};
  pairs.forEach(function (p) { out[p.id] = p.name; });
  return out;
}

// 1. Норма: объект → пары (порядок сохраняется).
(function () {
  const pairs = syncPairs({ '138811255': 'Леха', '350803143': 'Костик' });
  assert.strictEqual(pairs.length, 2, 'object: ожидалось 2 пары');
  assert.deepStrictEqual(pairsToObject(pairs),
    { '138811255': 'Леха', '350803143': 'Костик' });
})();

// 2. Строка JSON (двойное кодирование jsonb) → распаковка.
(function () {
  const raw = JSON.stringify({ '1': 'Иван' });
  const pairs = syncPairs(raw);
  assert.strictEqual(pairs.length, 1, 'string-JSON: ожидалась 1 пара');
  assert.strictEqual(pairs[0].id, '1');
  assert.strictEqual(pairs[0].name, 'Иван');
})();

// 3. Двойная строка JSON → распаковка до 2 уровней.
(function () {
  const raw = JSON.stringify(JSON.stringify({ '7': 'Пётр' }));
  const pairs = syncPairs(raw);
  assert.strictEqual(pairs.length, 1, 'double-encoded: ожидалась 1 пара');
  assert.strictEqual(pairs[0].id, '7');
  assert.strictEqual(pairs[0].name, 'Пётр');
})();

// 4. Пустой объект → 0 пар.
(function () {
  assert.strictEqual(syncPairs({}).length, 0, 'empty object → 0 пар');
  assert.strictEqual(syncPairs('{}').length, 0, 'empty string-object → 0 пар');
})();

// 5. Безопасный fallback: не-JSON / массив / null / undefined.
(function () {
  assert.strictEqual(syncPairs('не json').length, 0,
    'не-JSON строка → 0 пар без исключения');
  assert.strictEqual(syncPairs([1, 2]).length, 0, 'массив → 0 пар');
  assert.strictEqual(syncPairs(null).length, 0, 'null → 0 пар');
  assert.strictEqual(syncPairs(undefined).length, 0, 'undefined → 0 пар');
  assert.strictEqual(syncPairs(42).length, 0, 'число → 0 пар');
})();

// 6. Числовые значения → строковые имена (контракт UI).
(function () {
  const pairs = syncPairs({ '5': 10 });
  assert.strictEqual(pairs[0].name, '10', 'число-значение → строка');
})();

console.log('ALIASES-UNIT-OK');
