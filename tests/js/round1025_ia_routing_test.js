'use strict';
/* F1 round 10.25 — РЕАЛЬНЫЙ JS-тест новой IA/роутинга (T-2392/T-2393/T-2396):
 *   * navItems: legacy 6 (OFF) ↔ IA v2 7 (ON), «Память» отдельно;
 *   * bottom-nav ровно 4 (Статус/Модули/ИИ/Ещё), «Память» — в «Ещё»;
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

// ── bottom-nav ровно 4 (админ) + «Память» в «Ещё» ────────────────────────
{
  const ctx = {
    route: '#/', iaV2: true, canViewTab() { return true; },
    navItems: computed.navItems.call(
      { route: '#/', iaV2: true, canViewTab() { return true; } }),
  };
  assert.deepStrictEqual(computed.bottomNavItems.call(ctx).map((n) => n.id),
    ['status', 'modules', 'ai', 'more'],
    'bottom-nav админа = Статус/Модули/ИИ/Ещё');
  const moreIds = computed.mobileMoreItems.call(ctx).map((n) => n.id);
  assert.ok(moreIds.indexOf('memory') >= 0, '«Память» — внутри «Ещё»');
  assert.ok(moreIds.indexOf('how') >= 0 && moreIds.indexOf('access') >= 0,
    '«Ещё»: Справка/Доступы доступны');
  // Пользователь без прав: только Статус/Справка (≤4).
  const user = {
    route: '#/', iaV2: true, canViewTab(id) { return id === 'status' || id === 'info'; },
    navItems: computed.navItems.call({
      route: '#/', iaV2: true,
      canViewTab(id) { return id === 'status' || id === 'info'; } }),
  };
  assert.deepStrictEqual(computed.bottomNavItems.call(user).map((n) => n.id),
    ['status', 'how'], 'bottom-nav пользователя = Статус/Справка');
}

// ── H-1 (Scanner): «Ещё» обязателен при любом непубличном разделе ─────────
{
  const navFor = (canView) => computed.navItems.call(
    { route: '#/', iaV2: true, canViewTab: canView });
  const bottomFor = (canView) => computed.bottomNavItems.call(
    { iaV2: true, navItems: navFor(canView) }).map((n) => n.id);
  const moreFor = (canView) => computed.mobileMoreItems.call(
    { iaV2: true, navItems: navFor(canView) }).map((n) => n.id);

  const memoryOnly = (id) => id === 'status' || id === 'info' || id === 'chat_lore';
  assert.deepStrictEqual(navFor(memoryOnly).map((n) => n.id),
    ['status', 'how', 'memory'], 'роль «только Память»: раздел виден в nav');
  assert.ok(bottomFor(memoryOnly).indexOf('more') >= 0,
    'H-1: Память-only <768 → «Ещё» присутствует');
  assert.ok(moreFor(memoryOnly).indexOf('memory') >= 0,
    'H-1: Память-only → раздел достижим из «Ещё»');

  const accessOnly = (id) => id === 'status' || id === 'info' || id === 'access';
  assert.deepStrictEqual(navFor(accessOnly).map((n) => n.id),
    ['status', 'how', 'access'], 'роль «только Доступы»: раздел виден в nav');
  assert.ok(bottomFor(accessOnly).indexOf('more') >= 0,
    'H-1: Доступы-only <768 → «Ещё» присутствует');
  assert.ok(moreFor(accessOnly).indexOf('access') >= 0,
    'H-1: Доступы-only → раздел достижим из «Ещё»');

  const permsocOnly = (id) => id === 'status' || id === 'info' || id === 'permsoc';
  assert.ok(bottomFor(permsocOnly).indexOf('more') >= 0,
    'H-1: PERMsoc-only <768 → «Ещё» присутствует');
  assert.ok(moreFor(permsocOnly).indexOf('permsoc') >= 0,
    'H-1: PERMsoc-only → раздел достижим из «Ещё»');
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

// ── #/memory hub: 3 карточки; #/ai без memory/lore/relations ─────────────
{
  const mem = computed.hubCards.call(
    { route: '#/memory', iaV2: true, canViewTab() { return true; } });
  assert.ok(mem && mem.cards.length === 3, '#/memory hub = 3 карточки');
  assert.deepStrictEqual(mem.cards.map((c) => c.route),
    ['#/memory/rag', '#/memory/lore', '#/memory/relations'], 'карточки «Памяти»');
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
    'Память и RAG', 'M-1: подстраница Памяти — из карточки хаба');
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
