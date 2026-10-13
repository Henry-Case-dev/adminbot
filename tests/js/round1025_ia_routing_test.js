'use strict';
/* F1 round 10.25 — РЕАЛЬНЫЙ JS-тест новой IA/роутинга (T-2392/T-2393/T-2396):
 *   * navItems: legacy 6 (OFF) ↔ IA v2 7 (ON), «Память» отдельно;
 *   * bottom-nav админ ≤4 (Статус/Справка/Модули/Ещё; hotfix4), «Память» — в «Ещё»;
 *   * legacy-алиасы #/ai/{memory,lore,relations} → #/memory*;
 *   * мусорный hash → '#/' без падения;
 *   * #/memory — hub из 3 карточек; ROUTE_PARENT подстраниц → #/memory;
 *   * breadcrumb на вложенных (текущий раздел + путь назад).
 *
 * Запуск: node tests/js/round1025_ia_routing_test.js   (печатает JS-UNIT-OK)
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
  addEventListener() {}, getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() { const i = _bodyChildren.indexOf(this); if (i >= 0) _bodyChildren.splice(i, 1); },
    };
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) { const i = _bodyChildren.indexOf(el); if (i >= 0) _bodyChildren.splice(i, 1); return el; },
  },
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
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;

// ── navItems: OFF (legacy 6) ↔ ON (IA v2, 7) ─────────────────────────────
{
  const off = computed.navItems.call(
    { route: '#/', iaV2: false, canViewTab() { return true; } }).map((n) => n.id);
  assert.deepStrictEqual(off,
    ['status', 'how', 'modules', 'ai', 'permsoc', 'access'],
    'OFF: прежние 6 пунктов байт-в-байт');
  const on = computed.navItems.call(
    { route: '#/', iaV2: true, canViewTab() { return true; } }).map((n) => n.id);
  assert.deepStrictEqual(on,
    ['status', 'how', 'modules', 'ai', 'memory', 'access', 'permsoc'],
    'ON: 7 пунктов, «Память» отдельным разделом');
}

// ── activeNav: OFF-откат + #/memory* → «ИИ» (Reviewer M) ─────────────────
{
  assert.strictEqual(
    computed.activeNav.call({ route: '#/memory/rag', iaV2: false }), 'ai',
    'OFF + #/memory* → активный «ИИ» (в legacy NAV_ITEMS «Памяти» нет)');
  assert.strictEqual(
    computed.activeNav.call({ route: '#/memory/rag', iaV2: true }), 'memory',
    'ON + #/memory* → активный «Память»');
  assert.strictEqual(
    computed.activeNav.call({ route: '#/ai/prompts', iaV2: false }), 'ai',
    'OFF + #/ai* → активный «ИИ»');
}

// ── D13 (§18I.14): bottom-nav/«Ещё» УДАЛЕНЫ; мобильная верхняя навигация
// использует ТОТ ЖЕ канонический реестр navItems (все разделы, скрытых нет).
{
  const ctx = {
    route: '#/', iaV2: true, canViewTab() { return true; },
    navItems: computed.navItems.call(
      { route: '#/', iaV2: true, canViewTab() { return true; } }),
  };
  const topIds = computed.mobileTopnavItems.call(ctx).map((n) => n.id);
  assert.strictEqual(computed.bottomNavItems, undefined,
    'D13: computed bottomNavItems удалён');
  assert.strictEqual(computed.mobileMoreItems, undefined,
    'D13: computed mobileMoreItems («Ещё») удалён');
  assert.ok(topIds.indexOf('status') === 0 && topIds.indexOf('how') >= 0,
    'mobile-topnav: Статус/Справка присутствуют');
  assert.ok(topIds.indexOf('memory') >= 0 && topIds.indexOf('access') >= 0,
    'D13: Память/Доступы достижимы в верхней навигации без «Ещё»');
  assert.strictEqual(topIds.length, ctx.navItems.length,
    'D13: тот же канонический реестр, что и desktop sidebar');
  // Пользователь без прав: только доступные разделы (реестр один).
  const user = {
    route: '#/', iaV2: true, canViewTab(id) { return id === 'status' || id === 'info'; },
    navItems: computed.navItems.call({
      route: '#/', iaV2: true,
      canViewTab(id) { return id === 'status' || id === 'info'; } }),
  };
  assert.deepStrictEqual(computed.mobileTopnavItems.call(user).map((n) => n.id),
    ['status', 'how'], 'mobile-topnav пользователя = Статус/Справка');
}

// ── applyRoute: алиасы памяти + мусорный hash + nested parent ────────────
function applyOnce(route) {
  const ctx = {
    route: '#/', iaV2: true, me: { role_name: 'admin' },
    canViewTab() { return true; }, activeTab: 'status', accessOpen: null,
    tabs: captured.data().tabs,
    syncBackButton() {}, setTab(id) { this.activeTab = id; },
  };
  methods.applyRoute.call(ctx, route);
  return ctx.route;
}
assert.strictEqual(applyOnce('#/ai/memory'), '#/memory', '#/ai/memory → #/memory');
assert.strictEqual(applyOnce('#/ai/lore'), '#/memory/lore', '#/ai/lore → #/memory/lore');
assert.strictEqual(applyOnce('#/ai/relations'), '#/memory/relations',
  '#/ai/relations → #/memory/relations');
assert.strictEqual(applyOnce('#/memory/rag'), '#/memory/rag', 'канон #/memory/rag');
assert.strictEqual(applyOnce('#/garbage/route'), '#/', 'мусорный hash → #/');
assert.strictEqual(applyOnce(''), '#/', 'пустой hash → #/');

// ── #/memory hub: 3 раздела (F6 ADR-1025-19 D6/§52) ──────────────────────
{
  const mem = computed.hubCards.call(
    { route: '#/memory', iaV2: true, canViewTab() { return true; } });
  assert.ok(mem && mem.cards.length === 3, '#/memory hub = 3 раздела');
  assert.deepStrictEqual(mem.cards.map((c) => c.route),
    ['#/memory/rag', '#/memory/lore', '#/memory/relations'],
    'маршруты «Памяти» (рендеры сохранены)');
  assert.deepStrictEqual(mem.cards.map((c) => c.title),
    ['Настройки памяти', 'Лор чатов', 'Люди и связи'], 'разделы «Памяти» §52');
  const ai = computed.hubCards.call(
    { route: '#/ai', iaV2: true, canViewTab() { return true; } });
  const aiRoutes = ai.cards.map((c) => c.route);
  for (const gone of ['#/ai/memory', '#/ai/lore', '#/ai/relations']) {
    assert.ok(aiRoutes.indexOf(gone) < 0, '«ИИ» больше не содержит ' + gone);
  }
  assert.ok(aiRoutes.indexOf('#/ai/persona') >= 0, '«Личность» осталась в «ИИ»');
}

// ── breadcrumb (UPD §8.4): текущий раздел + путь назад ───────────────────
{
  const bc = computed.breadcrumb.call(
    { route: '#/memory/lore', _routeLabel: methods._routeLabel });
  assert.ok(bc, 'breadcrumb есть на вложенной');
  assert.strictEqual(bc.root.route, '#/');
  assert.strictEqual(bc.mid.route, '#/memory');
  assert.strictEqual(bc.mid.label, 'Память');
  assert.strictEqual(bc.current, 'Лор чата');
  assert.strictEqual(computed.breadcrumb.call(
    { route: '#/', _routeLabel: methods._routeLabel }), null,
    'на корне breadcrumb нет');
}

// ── M-1 (Scanner): подпись special-screen/подстраниц (не сырой hash) ──────
{
  assert.strictEqual(methods._routeLabel.call({ iaV2: true }, '#/ai/persona'),
    'Личность и стиль', 'M-1: #/ai/persona → человекочитаемая подпись');
  assert.strictEqual(methods._routeLabel.call({ iaV2: true }, '#/memory/rag'),
    'Настройки памяти', 'M-1: подстраница Памяти — из карточки хаба');
  const bc = computed.breadcrumb.call(
    { route: '#/ai/persona', iaV2: true, _routeLabel: methods._routeLabel });
  assert.strictEqual(bc.current, 'Личность и стиль',
    'M-1: breadcrumb «Личность» без сырого #/ai/persona');
  assert.strictEqual(bc.mid.label, 'ИИ', 'M-1: родитель — «ИИ»');
}

// ── shell-режимы по ширине: sidebar строго ≥1200 ─────────────────────────
{
  const mk = (w) => ({ shellMode: w >= 1200 ? 'desktop' : (w >= 768 ? 'compact' : 'mobile') });
  assert.strictEqual(computed.hasSidebar.call(mk(1200)), true, '≥1200 → sidebar');
  assert.strictEqual(computed.hasSidebar.call(mk(1199)), false, '1199 → без sidebar');
  assert.strictEqual(computed.isCompactShell.call(mk(768)), true, '768 → drawer');
  assert.strictEqual(computed.isMobileShell.call(mk(390)), true, '<768 → bottom-nav');
}

console.log('JS-UNIT-OK round1025_ia_routing_test');
