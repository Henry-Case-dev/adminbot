'use strict';
/* ASAP 4.2 Step 2c-2 (T-4819/T-4823/T-4825/T-4826) — MiniApp layout/Test Style
 * JS-контракт (реальные web/index.html / web/app.js / app.css):
 *   (a) Test Style НЕ открывает file picker и не шлёт upload (только profile_id);
 *   (b) `.more-sheet` closed = unmount (`v-if moreOpen`), не dormant overlay;
 *   (c) Quick Access панель отсутствует в DOM;
 *   (d) компактные before/after + Material arrow; editor preview ограничен.
 *
 * Запуск: node tests/js/asap42_step2c2_layout_test.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');

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
assert(captured, 'Vue.createApp вызван');
const methods = captured.methods;

// (a) Test Style — не file picker, только profile_id
{
  const src = methods.coverStylePreview.toString();
  assert.ok(src.indexOf('/api/cover/test-style') >= 0, 'a: endpoint test-style');
  assert.ok(/profile_id/.test(src), 'a: шлёт profile_id');
  assert.ok(src.indexOf('fileToBase64') < 0, 'a: не читает файл');
  assert.ok(!/\.files/.test(src), 'a: не читает ev.target.files');
  assert.ok(src.indexOf('content_base64') < 0, 'a: не шлёт upload base64');
  const refresh = methods.coverStyleRefreshExample.toString();
  assert.ok(refresh.indexOf('data-cover-test-input') < 0,
    'a: refresh не кликает file input');
  // В HTML нет file input для Test Style.
  assert.ok(INDEX.indexOf('data-cover-test-input') < 0,
    'a: нет data-cover-test-input');
  assert.ok(INDEX.indexOf('data-cover-test-button') >= 0,
    'a: есть кнопка «Проверить стиль»');
}

// (b) D13 (§18I.14): bottom-nav/шторка «Ещё» УДАЛЕНЫ полностью — ни
// разметки, ни CSS-правил, ни состояния moreOpen (unmount стал полным
// удалением).
{
  assert.ok(INDEX.indexOf('class="more-sheet"') < 0,
    'b: .more-sheet отсутствует в разметке (D13)');
  assert.ok(INDEX.indexOf('moreOpen') < 0,
    'b: состояние moreOpen удалено (D13)');
  assert.ok(INDEX.indexOf('class="bottom-nav"') < 0,
    'b: bottom-nav отсутствует (D13)');
  assert.ok(!/\.more-sheet[\s{,:-]/.test(CSS)
    && !/\.bottom-nav[\s{,:-]/.test(CSS),
    'b: CSS-правила more-sheet/bottom-nav удалены (D13)');
  // Мобильная навигация — компактная верхняя строка.
  assert.ok(INDEX.indexOf('class="mobile-topnav scroll-thin"') >= 0,
    'b: мобильная верхняя навигация присутствует (D13 §18I.14)');
}

// (c) Quick Access удалена
{
  const start = INDEX.indexOf("activeTab === 'modules'");
  const end = INDEX.indexOf("activeTab === 'oversight'", start);
  const branch = INDEX.slice(start, end);
  assert.strictEqual(branch.indexOf('module-quick-wrap'), -1,
    'c: панели нет');
  assert.strictEqual(branch.indexOf('quickpickVisible'), -1,
    'c: элементов панели нет');
}

// (d) компактные before/after + Material arrow + editor preview ограничен
{
  for (const marker of ['data-cover-mini-before', 'data-cover-mini-after',
    'data-cover-mini-arrow', 'data-cover-preview-source']) {
    assert.ok(INDEX.indexOf(marker) >= 0, 'd: ' + marker);
  }
  assert.ok(INDEX.indexOf("iconGlyph('chevron_right')") >= 0,
    'd: Material arrow (chevron_right), не текстовый →');
  assert.ok(INDEX.indexOf('text-gray-400 text-xl flex-none">→<') < 0,
    'd: текстовый → удалён');
  assert.ok(/\.cover-mini\s*\{/.test(CSS), 'd: .cover-mini CSS');
  assert.ok(/\.cover-mini-arrow\s*\{/.test(CSS), 'd: .cover-mini-arrow CSS');
  assert.ok(/\.cover-preview\s*\{[^}]*max-width:\s*11rem/.test(CSS),
    'd: editor preview max-width 11rem');
  assert.ok(/\.cover-preview\s*\{[^}]*max-height:\s*11rem/.test(CSS),
    'd: editor preview max-height 11rem');
}

console.log('ASAP42-STEP2C2-LAYOUT-OK');
