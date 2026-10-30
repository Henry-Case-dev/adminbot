'use strict';
/* EVOL-023 (W7): навигация/топбар/единый scope-switcher — JS-юниты.
 *
 *   * topbar называет РАЗДЕЛ, а не config-вкладку (#/ai → «ИИ», не
 *     «LLM Провайдеры»);
 *   * крошки только на реально вложенных маршрутах (у верхнеуровневого
 *     раздела нет фиктивного родителя «Статус»);
 *   * rail-состояние sidebar: инициализация из localStorage, переключение,
 *     персист (настройка плотности, а не разовый оверлей);
 *   * drawer: фокус входит в панель и возвращается в кнопку шапки;
 *   * `_focusOpenedDialog` — мягкий no-op без DOM (unit-стабы/file://).
 *
 * Запуск: node tests/js/evol_w7_nav_test.js   (ожидается маркер JS-UNIT-OK)
 */
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component() {}, provide() {}, use() {}, mount() {},
    };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
global.document = {
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
const computed = captured.computed || {};
const methods = captured.methods || {};
const data = typeof captured.data === 'function' ? captured.data() : captured.data;

// ── 1. data: новое состояние объявлено ─────────────────────────────────────
assert.strictEqual(data.sidebarCollapsed, false,
  'she: sidebarCollapsed объявлен в data (false по умолчанию)');

// ── 2. крошки: только на вложенных маршрутах ──────────────────────────────
{
  const ctxTop = { route: '#/oversight', _routeLabel: methods._routeLabel };
  assert.strictEqual(computed.breadcrumb.call(ctxTop), null,
    'C: у верхнеуровневого раздела нет крошки (фиктивный «Статус» убран)');
  const ctxAi = { route: '#/ai', _routeLabel: methods._routeLabel };
  assert.strictEqual(computed.breadcrumb.call(ctxAi), null,
    'C: хаб-раздел тоже без крошки');
  const ctxDeep = { route: '#/memory/lore', iaV2: true,
                    _routeLabel: methods._routeLabel };
  const bc = computed.breadcrumb.call(ctxDeep);
  assert.ok(bc && bc.mid && bc.mid.route === '#/memory',
    'C: вложенный маршрут сохраняет путь назад');
  assert.strictEqual(bc.root.route, '#/', 'C: корень пути — #/');
}

// ── 3. headerTitle: имя РАЗДЕЛА, а не config-вкладки ──────────────────────
{
  const mk = (route, tabLabel) => ({
    route: route,
    _routeLabel: methods._routeLabel,
    currentTabLabel: tabLabel,
    get breadcrumb() { return computed.breadcrumb.call(this); },
  });
  assert.strictEqual(
    computed.headerTitle.call(mk('#/ai', 'LLM Провайдеры')), 'ИИ',
    'H: на хабе «ИИ» топбар показывает раздел, а не «LLM Провайдеры»');
  assert.strictEqual(
    computed.headerTitle.call(mk('#/oversight', 'Аналитика')), 'Аналитика',
    'H: раздел «Аналитика»');
  assert.strictEqual(
    computed.headerTitle.call(mk('#/memory/lore', 'Лор чата')), 'Лор чата',
    'H: вложенная страница — своя подпись (из крошки)');
}

// ── 4. rail-состояние sidebar ─────────────────────────────────────────────
{
  global.localStorage._s['adminbot.sidebar_collapsed'] = '1';
  const ctx = { sidebarCollapsed: false };
  methods.initSidebarCollapsed.call(ctx);
  assert.strictEqual(ctx.sidebarCollapsed, true,
    "S: '1' в localStorage разворачивается в collapsed-состояние");
  global.localStorage._s['adminbot.sidebar_collapsed'] = '';
  methods.initSidebarCollapsed.call(ctx);
  assert.strictEqual(ctx.sidebarCollapsed, false, 'S: пустое значение → полная панель');
  // Переключение персистится (пользовательская настройка плотности).
  const ctx2 = { sidebarCollapsed: false };
  methods.toggleSidebarCollapse.call(ctx2);
  assert.strictEqual(ctx2.sidebarCollapsed, true, 'S: toggle сворачивает');
  assert.strictEqual(global.localStorage._s['adminbot.sidebar_collapsed'], '1',
    'S: состояние сохранено');
  methods.toggleSidebarCollapse.call(ctx2);
  assert.strictEqual(ctx2.sidebarCollapsed, false, 'S: toggle разворачивает');
  assert.strictEqual(global.localStorage._s['adminbot.sidebar_collapsed'], '',
    'S: сброс сохранён');
}

// ── 5. drawer: фокус входит/возвращается, Esc-закрытие idempotent ─────────
{
  const focusCalls = [];
  const firstLink = { focus() { focusCalls.push('link'); } };
  const trigger = { focus() { focusCalls.push('trigger'); } };
  const oldQ = global.document.querySelector;
  global.document.querySelector = function (sel) {
    if (sel === '.app-drawer .sidebar-link') return firstLink;
    if (sel === '[data-drawer-trigger]') return trigger;
    return null;
  };
  const ctx = { drawerOpen: false, $nextTick(cb) { cb(); } };
  methods.toggleDrawer.call(ctx);
  assert.strictEqual(ctx.drawerOpen, true, 'D: toggle открывает drawer');
  assert.deepStrictEqual(focusCalls, ['link'], 'D: фокус внутри панели при открытии');
  methods.closeDrawer.call(ctx);
  assert.strictEqual(ctx.drawerOpen, false, 'D: closeDrawer закрывает');
  assert.deepStrictEqual(focusCalls, ['link', 'trigger'],
    'D: фокус возвращается в кнопку шапки');
  focusCalls.length = 0;
  methods.closeDrawer.call(ctx);
  assert.deepStrictEqual(focusCalls, [],
    'D: повторное закрытие не дёргает фокус (idempotent)');
  global.document.querySelector = oldQ;
}

// ── 6. _focusOpenedDialog: мягкий no-op без диалога ───────────────────────
{
  const ctx = { $nextTick(cb) { cb(); } };
  assert.doesNotThrow(function () {
    methods._focusOpenedDialog.call(ctx);
  }, 'F: без диалога нет исключения (unit-стаб/file://)');
  const first = { focus() { this.focused = true; }, disabled: false };
  const oldQ = global.document.querySelector;
  global.document.querySelector = function (sel) {
    if (sel !== '[role="dialog"][tabindex="-1"]') return null;
    return { focus() {}, querySelectorAll() { return [first]; } };
  };
  methods._focusOpenedDialog.call(ctx);
  assert.strictEqual(first.focused, true,
    'F: фокус входит в первый элемент управления диалога');
  global.document.querySelector = oldQ;
}

console.log('JS-UNIT-OK');
