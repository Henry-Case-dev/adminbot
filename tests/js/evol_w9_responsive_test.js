'use strict';
/* EVOL-025 (W9): адаптивный режим каркаса и лист модалок — JS-юниты.
 *
 *   * `_syncShellMode` — единственный источник режима: shellMode по ширине,
 *     `data-shell-mode` для наблюдения, `w9-sheet-bottom` (узкий экран ИЛИ
 *     низкий ландшафт) для геометрии модалок;
 *   * пересчёт на resize/зуме/повороте идёт через ту же функцию (проверяется
 *     вызовом с разными размерами);
 *   * без DOM функция не падает (fallback/no-op вне браузера);
 *   * `_initHeaderHeight` измеряет ФАКТИЧЕСКУЮ высоту мобильной навигации
 *     (`--bottom-nav-h`), а не берёт CSS-константу.
 *
 * Запуск: node tests/js/evol_w9_responsive_test.js  (ожидается маркер
 * EVOL-W9-RESPONSIVE-OK)
 */
const path = require('path');
const assert = require('assert');

// ── DOM-заглушки: только то, что нужно shell-режиму и метрикам ─────────────
const attrs = {};
const classes = new Set();
const styleVars = {};
const rootEl = {
  setAttribute: (k, v) => { attrs[k] = v; },
  getAttribute: (k) => (Object.prototype.hasOwnProperty.call(attrs, k)
    ? attrs[k] : null),
  classList: {
    toggle: (name, on) => {
      if (on === undefined) on = !classes.has(name);
      if (on) classes.add(name); else classes.delete(name);
      return on;
    },
    contains: (name) => classes.has(name),
  },
  style: {
    setProperty: (k, v) => { styleVars[k] = v; },
    removeProperty: (k) => { delete styleVars[k]; },
  },
};

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
global.document = {
  documentElement: rootEl,
  addEventListener() {}, getElementById() { return null; },
  createElement() {
    return { tagName: 'div', className: '', value: '', style: {},
             setAttribute() {}, focus() {}, select() {}, remove() {} };
  },
  querySelector() { return null; },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('no'); } } },
});
global.sessionStorage = {
  _s: {},
  getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.localStorage = {
  _s: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван при загрузке app.js');
const methods = captured.methods || {};

function setViewport(w, h) {
  global.window.innerWidth = w;
  global.window.innerHeight = h;
}

function sync(w, h) {
  setViewport(w, h);
  const ctx = { shellMode: null };
  methods._syncShellMode.call(ctx);
  return {
    mode: ctx.shellMode,
    attr: attrs['data-shell-mode'],
    sheet: classes.has('w9-sheet-bottom'),
  };
}

// ── 1. Портрет телефона: mobile + лист (узкая ширина) ─────────────────────
[[320, 568], [360, 640], [390, 844], [430, 932], [600, 800]].forEach(([w, h]) => {
  const r = sync(w, h);
  assert.strictEqual(r.mode, 'mobile', `${w}x${h}: mobile shell (1 колонка)`);
  assert.strictEqual(r.attr, 'mobile', `${w}x${h}: data-shell-mode наблюдаем`);
  assert.ok(r.sheet, `${w}x${h}: модалка = bottom sheet (узкий экран)`);
});

// ── 2. Планшет/десктоп: compact/desktop, без sheet ────────────────────────
[[768, 1024], [1024, 768]].forEach(([w, h]) => {
  const r = sync(w, h);
  assert.strictEqual(r.mode, 'compact', `${w}x${h}: compact shell (drawer)`);
  assert.ok(!r.sheet, `${w}x${h}: на планшете модалка — окно, не лист`);
});
[[1440, 900], [1920, 1080]].forEach(([w, h]) => {
  const r = sync(w, h);
  assert.strictEqual(r.mode, 'desktop', `${w}x${h}: desktop shell`);
  assert.ok(!r.sheet, `${w}x${h}: desktop — окно по центру`);
});

// ── 3. Низкий ландшафт: лист независимо от ширины ─────────────────────────
[[667, 375], [812, 375], [932, 430], [1024, 400], [640, 400]].forEach(([w, h]) => {
  const r = sync(w, h);
  assert.ok(r.sheet, `${w}x${h}: низкий ландшафт → модалка-лист`);
});
// ... но не при обычной высоте того же ландшафта.
assert.ok(!sync(1024, 768).sheet, '1024x768: высота обычная — окно, не лист');
assert.ok(!sync(1440, 522).sheet, '1440x522: выше порога низкого ландшафта');

// ── 4. Пересчёт идемпотентен (resize/поворот туда-обратно) ────────────────
let r = sync(390, 844);
assert.strictEqual(r.mode, 'mobile');
r = sync(844, 390);
assert.strictEqual(r.mode, 'compact', 'landscape 844x390 — compact shell');
assert.ok(r.sheet, 'landscape 844x390 — лист модалки');
r = sync(390, 844);
assert.strictEqual(r.mode, 'mobile');
assert.ok(r.sheet);
r = sync(1440, 900);
assert.ok(!r.sheet, 'после возврата на desktop лист снят (нет залипания)');
assert.strictEqual(attrs['data-shell-mode'], 'desktop');

// ── 5. Без DOM / вне браузера — no-op, без исключений ────────────────────
{
  const saved = global.document;
  global.document = { querySelector() { return null; } };
  const ctx = { shellMode: null };
  methods._syncShellMode.call(ctx);   // documentElement отсутствует
  global.document = saved;
  assert.ok(true, 'A: _syncShellMode без documentElement не бросает');
}

// ── 6. Метрика шапки: измеряется; метрики нижней панели больше нет ────────
{
  const savedDoc = global.document;
  const headerRect = { height: 58 };
  global.document = {
    documentElement: rootEl,
    querySelector: (sel) => {
      if (sel === 'header.header-sticky') {
        return { getBoundingClientRect: () => headerRect };
      }
      return null;
    },
  };
  methods._initHeaderHeight.call({});
  assert.strictEqual(styleVars['--header-h'], '58px',
    'M: --header-h измеряется по шапке');
  // ASAP-UI-02 §2.1: нижней панели разделов нет — нет и её метрики/наблюдателя.
  assert.strictEqual(methods._syncBottomNavMetric, undefined,
    'ASAP-UI-02: наблюдатель высоты нижней панели удалён');
  assert.ok(!Object.prototype.hasOwnProperty.call(styleVars, '--bottom-nav-h'),
    'ASAP-UI-02: --bottom-nav-h не выставляется (панели нет)');
  global.document = savedDoc;
}

console.log('EVOL-W9-RESPONSIVE-OK');
