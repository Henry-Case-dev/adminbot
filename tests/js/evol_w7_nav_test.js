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

// ── 5b. Ревью F3: drawer держит Tab, Esc (фокус вне панели) и Back ────────
{
  const focusCalls = [];
  const mkItem = (tag) => ({ tag, disabled: false, offsetParent: {},
    focus() { focusCalls.push(tag); global.document.activeElement = this; } });
  const items = [mkItem('first'), mkItem('mid'), mkItem('last')];
  const panel = { querySelectorAll() { return items; } };
  const oldQ = global.document.querySelector;
  const hadActive = Object.prototype.hasOwnProperty
    .call(global.document, 'activeElement');
  const oldActive = global.document.activeElement;
  global.document.querySelector = function (sel) {
    return sel === '.app-drawer' ? panel : null;
  };
  const prevented = {};
  const keyEvent = (key, shift) => ({
    key, shiftKey: !!shift,
    preventDefault() { prevented.at = true; },
  });
  // 1) Tab с последнего пункта замыкается на первый (а не уходит на BODY).
  global.document.activeElement = items[2];
  prevented.at = false;
  methods.drawerOnKeydown.call({}, keyEvent('Tab', false));
  assert.strictEqual(prevented.at, true, 'F3: Tab с последнего пункта перехвачен');
  assert.deepStrictEqual(focusCalls, ['first'],
    'F3: фокус уходит на первый пункт drawer, а не на BODY/шапку');
  // 2) Shift+Tab с первого — на последний.
  global.document.activeElement = items[0];
  prevented.at = false;
  methods.drawerOnKeydown.call({}, keyEvent('Tab', true));
  assert.strictEqual(prevented.at, true, 'F3: Shift+Tab с первого перехвачен');
  assert.strictEqual(focusCalls[focusCalls.length - 1], 'last',
    'F3: Shift+Tab замыкается на последний пункт');
  // 3) В середине списка поведение браузера не перебивается.
  global.document.activeElement = items[1];
  prevented.at = false;
  methods.drawerOnKeydown.call({}, keyEvent('Tab', false));
  assert.strictEqual(prevented.at, false,
    'F3: штатный переход внутри панели не блокируется');
  // 4) Панели нет (юнит-стабы) — исключения нет.
  global.document.querySelector = oldQ;
  assert.doesNotThrow(function () {
    methods.drawerOnKeydown.call({}, keyEvent('Tab', false));
  }, 'F3: без DOM ловушка не падает');
  if (hadActive) global.document.activeElement = oldActive;
  else delete global.document.activeElement;
}

// ── 5c. Ревью F3: Esc закрывает открытый drawer при внешнем фокусе ────────
{
  const calls = [];
  const ctx = {
    drawerOpen: true,
    closeDrawer() { calls.push('drawer'); },
    closeMoreMenu() { calls.push('more'); },
  };
  methods.escClose.call(ctx);
  assert.deepStrictEqual(calls, ['drawer'],
    'F3: глобальный Esc закрывает drawer, даже если фокус вне панели');
  const src = methods.escClose.toString();
  assert.ok(src.indexOf('moreMenuOpen') < src.indexOf('drawerOpen'),
    'F3: порядок слоёв — «⋯» закрывается выше drawer');
  // goBack: Back закрывает панель, а не уводит страницу под ней.
  const nav = [];
  methods.goBack.call({
    drawerOpen: true, route: '#/memory/lore',
    closeDrawer() { nav.push('drawer'); },
    navigateTo(r) { nav.push('nav:' + r); },
  });
  assert.deepStrictEqual(nav, ['drawer'],
    'F3: Back при открытом drawer закрывает панель, маршрут не меняется');
  const noDrawer = [];
  methods.goBack.call({
    drawerOpen: false, route: '#/memory/lore',
    closeDrawer() { noDrawer.push('drawer'); },
    navigateTo(r) { noDrawer.push('nav:' + r); },
  });
  assert.deepStrictEqual(noDrawer, ['nav:#/memory'],
    'F3: закрытый drawer поведение Back не меняет');
}

// ── 5d. Ревью F2: «На весь экран» из «⋯» (узкий телефон) ──────────────────
{
  const calls = [];
  methods.moreMenuFullscreen.call({
    closeMoreMenu(refocus) { calls.push('close:' + refocus); },
    toggleFullscreen() { calls.push('fs'); },
  });
  assert.deepStrictEqual(calls, ['close:false', 'fs'],
    'F2: пункт «⋯» закрывает поповер без возврата фокуса и зовёт политику ⛶');
}

// ── 6. _focusOpenedDialog: мягкий no-op без диалога ───────────────────────
{  const ctx = { $nextTick(cb) { cb(); } };
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

// ── 7. closeScope: фокус возвращается в триггер (ревью F2) ────────────────
{
  const focusCalls = [];
  const trigger = { focus() { focusCalls.push('trigger'); } };
  const search = { tag: 'search' };
  const panel = { contains(el) { return el === search; } };
  const oldQ = global.document.querySelector;
  const hadActive = Object.prototype.hasOwnProperty
    .call(global.document, 'activeElement');
  const oldActive = global.document.activeElement;
  global.document.querySelector = function (sel) {
    if (sel === '.scope-panel') return panel;
    if (sel === '.scope-wrap > .scope-trigger') return trigger;
    if (sel === '.scope-trigger') return trigger;
    return null;
  };
  // 1) Esc из поиска внутри панели → фокус в триггер, панель закрыта.
  global.document.activeElement = search;
  const ctx = { scopeOpen: true, scopeFocus: 3 };
  methods.closeScope.call(ctx);
  assert.strictEqual(ctx.scopeOpen, false, 'F2: closeScope закрывает панель');
  assert.strictEqual(ctx.scopeFocus, -1, 'F2: активная опция сброшена');
  assert.deepStrictEqual(focusCalls, ['trigger'],
    'F2: фокус из поиска возвращается в .scope-trigger (не остаётся на BODY)');
  // 2) Повторное закрытие (панель уже закрыта) фокус не ворует.
  methods.closeScope.call(ctx);
  assert.deepStrictEqual(focusCalls, ['trigger'],
    'F2: повторный Esc по закрытой панели фокус не дёргает (idempotent)');
  // 3) Фокус на постороннем контроле не перебиваем.
  global.document.activeElement = { tag: 'other' };
  methods.closeScope.call({ scopeOpen: true, scopeFocus: 0 });
  assert.deepStrictEqual(focusCalls, ['trigger'],
    'F2: чужой фокус не отбирается');
  // 4) Панели нет в DOM (юнит-стабы) — исключения нет.
  global.document.querySelector = oldQ;
  assert.doesNotThrow(function () {
    methods.closeScope.call({ scopeOpen: true, scopeFocus: 0 });
  }, 'F2: без DOM closeScope не падает');
  if (hadActive) global.document.activeElement = oldActive;
  else delete global.document.activeElement;
}

console.log('JS-UNIT-OK');
