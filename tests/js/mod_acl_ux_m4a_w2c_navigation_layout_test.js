'use strict';
/* MOD-ACL-UX-01 M4A W2c (2.58.221) — навигация/сетка/wireframe.
 *
 * Контракт (W2c brief §6, design §3.1/§3.3/§4.1–§4.6/§6.3/§8/§11.2):
 *   NAV-01: каталог → модуль → подраздел прямым deep link; подмодульный
 *      чип/ссылка на владельца по `parent_id` (stories/experience/random →
 *      #/memory/rag, character → #/permsoc); разные классы данных не
 *      смешиваются на родительской поверхности (группы владельца — одной
 *      ссылкой «Настраивается в …», без второго набора полей).
 *   LAY-01: sidebar 190–220; рабочая область 1440; 8/12+4/12 только через
 *      opt-in wrapper и только при двух sibling-блоках; простые вкладки
 *      900–1000; touch ≥44 на tablet/mobile; без горизонтального overflow.
 *   WF-01: три класса модулей (complex/small/infrastructure/maintenance)
 *      и одна шапка; «Расширенные» — одна подпись зоны.
 *
 * Запуск: node tests/js/mod_acl_ux_m4a_w2c_navigation_layout_test.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const INDEX_HTML = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_CSS = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
const _storage = {
  _s: {},
  getItem(k) {
    return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null;
  },
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
assert(captured, 'Vue.createApp должен быть вызван');

const { applyModuleDto } = require('./module_fixture.js');
const data = applyModuleDto(captured);
const methods = captured.methods;
const computed = captured.computed;
const MODULES = data.modules;
const TABS = data.tabs;

function byId(id) {
  return MODULES.filter(function (m) { return m.id === id; })[0];
}
function moduleBySlug(slug) {
  return MODULES.filter(function (m) {
    return m.routeSlug === slug;
  })[0] || null;
}
function mkCtx(overrides) {
  return Object.assign({}, methods, {
    modules: MODULES,
    tabs: TABS,
    activeChatId: -100,
    scopeKind: 'chat',
    configItems: [{ key: 'stub.item', value: true }],
    workspaceModule: null,
    route: '#/modules',
    activeTab: 'modules',
    _f3RegistryApplied: true,
    _f4Registry: {},
    toast: function () {},
    syncBackButton: function () {},
    setTab: function (id) { this.activeTab = id; },
    navigateTo: function (r) { this.nav = r; },
    moduleBySlug: moduleBySlug,
    canViewTab: function () { return true; },
    uiFlag: function () { return true; },
  }, overrides || {});
}
let checks = 0;
function ok(cond, msg) {
  assert.ok(cond, msg);
  checks += 1;
}
function eq(a, b, msg) {
  assert.strictEqual(a, b, msg);
  checks += 1;
}

// ── (1) NAV-01: parent_id → родительская поверхность/владелец ──────────────
{
  const ctx = mkCtx();
  const expected = {
    mod_stories: ['memory', 'Часть «Памяти»', '#/memory/rag'],
    mod_experience: ['memory', 'Часть «Памяти»', '#/memory/rag'],
    mod_random: ['memory', 'Часть «Памяти»', '#/memory/rag'],
    mod_character: ['persona', 'Часть «PERMsoc»', '#/permsoc'],
  };
  Object.keys(expected).forEach(function (id) {
    const m = byId(id);
    ok(m, '1: карточка ' + id + ' из DTO');
    const info = methods.moduleParentInfo.call(ctx, m);
    ok(info, '1: ' + id + ' — чип/ссылка владельца существует');
    eq(info.parentId, expected[id][0], '1: ' + id + ' parent_id из DTO');
    eq(info.label, expected[id][1], '1: ' + id + ' подпись чипа');
    eq(info.route, expected[id][2], '1: ' + id + ' deep link владельца');
    eq(info.href, '#/modules/' + m.routeSlug, '1: ' + id + ' ссылка на карточку');
  });
  ['mod_summary', 'mod_embeddings', 'mod_time'].forEach(function (id) {
    eq(methods.moduleParentInfo.call(ctx, byId(id)), null,
      '1: у ' + id + ' нет parent-чипа (фактический parent_id пуст)');
  });
  eq(methods.moduleParentInfo.call(ctx, {
    id: 'mod_unknown', parent_id: 'no_such_surface',
    routeSlug: 'unknown'}), null,
  '1: неизвестный parent_id не выдумывает ссылку (fail-closed)');
}

// ── (2) NAV-01: ссылки «Настраивается в …» на родительской поверхности ─────
{
  const ctx = mkCtx();
  const mem = methods.submoduleOwnerLinks.call(ctx, 'memory');
  eq(mem.map(function (l) { return l.id; }).join(','),
    'mod_stories,mod_experience,mod_random',
    '2: «Память» ссылается на три части в catalog_order');
  eq(mem.map(function (l) { return l.route; }).join(','),
    '#/modules/stories,#/modules/experience,#/modules/random',
    '2: deep links всех трёх частей');
  eq(mem[0].label, 'Настраивается в «' + byId('mod_stories').title + '» →',
    '2: подпись строки-ссылки (design §6.3)');
  const per = methods.submoduleOwnerLinks.call(ctx, 'persona');
  eq(per.map(function (l) { return l.id; }).join(','), 'mod_character',
    '2: «PERMsoc» ссылается на «Характер»');
  eq(per[0].route, '#/modules/character',
    '2: характер — отдельная страница владельца');

  const owned = methods.submoduleOwnedGroups.call(ctx, 'memory');
  eq(owned.flags_stories, true, '2: flags_stories принадлежит подмодулю');
  eq(owned.memory_experience, true, '2: memory_experience принадлежит подмодулю');
  eq(owned.memory_random, true, '2: memory_random принадлежит подмодулю');
  eq(!!owned.limits_graph, false, '2: graph-группа остаётся на «Памяти»');
  const ownedP = methods.submoduleOwnedGroups.call(ctx, 'persona');
  eq(ownedP.flags_character, true, '2: flags_character принадлежит «Характеру»');
}

// ── (3) NAV-01: группы владельца НЕ дублируются на родительском полотне ────
{
  const items = [
    { key: 'flags.stories_vitrina_enabled', group: 'flags_stories',
      category: 'flags', title: 'stories', progressive_level: 'basic' },
    { key: 'memory.experience_learning_enabled', group: 'memory_experience',
      category: 'memory', title: 'lessons', progressive_level: 'basic' },
    { key: 'limits.graph_hist_horizon_days', group: 'limits_graph',
      category: 'limits', title: 'graph', progressive_level: 'basic' },
  ];
  const ctx = mkCtx({
    currentTab: TABS.filter(function (t) { return t.id === 'memory_rag'; })[0],
    memorySubgroup: '',
    groupedForTab: function () {
      return [{ uid: 'x', id: 'x', category: '', items: items.slice() }];
    },
  });
  const groups = methods._memoryGroups.call(ctx);
  const keys = [];
  groups.forEach(function (g) {
    (g.items || []).forEach(function (it) { keys.push(it.key); });
  });
  eq(keys.indexOf('flags.stories_vitrina_enabled'), -1,
    '3: поле подмодуля «Истории» не рендерится на «Памяти» (только ссылка)');
  eq(keys.indexOf('memory.experience_learning_enabled'), -1,
    '3: поле подмодуля «Опыт» не рендерится на «Памяти» (только ссылка)');
  eq(keys.indexOf('limits.graph_hist_horizon_days') >= 0, true,
    '3: собственные поля «Памяти» сохранены');
  const chips = computed.memorySubgroupChips.call(ctx).map(function (s) {
    return s.id;
  });
  eq(chips.join(','), 'graph',
    '3: чипы подгрупп не показывают пустую подгруппу из полей владельца');
}

// ── (4) NAV-01/Lay: прямые deep links на подраздел ─────────────────────────
{
  const ctx = mkCtx({
    workspace: {
      module: byId('mod_summary'), slug: 'summary', tab: 'settings',
      door: 'modules',
    },
  });
  eq(methods.workspaceTabHref.call(ctx, 'overview'),
    '#/modules/summary', '4: «Обзор» — bare deep link');
  eq(methods.workspaceTabHref.call(ctx, 'settings'),
    '#/modules/summary/settings', '4: подраздел — прямой deep link');
  eq(methods.workspaceTabHref.call(ctx, 'history'),
    '#/modules/summary/history', '4: история — прямой deep link');
  ok(INDEX_HTML.indexOf(':href="workspaceTabHref(wt.id)"') >= 0,
    '4: ссылки «Обзора» — реальные <a href>, а не только JS-кнопки');
  ok(INDEX_HTML.indexOf('data-overview-link') >= 0,
    '4: прежний адрес [data-overview-link] сохранён (W2b-регрессии)');
}

// ── (5) LAY-01: классы модулей и opt-in 8/12 + 4/12 ────────────────────────
{
  const ctx = mkCtx();
  eq(methods.moduleClass.call(ctx, byId('mod_summary')), 'complex',
    '5: «Сводки» — сложный модуль');
  eq(methods.moduleClass.call(ctx, byId('mod_direct')), 'complex',
    '5: «Прямые ответы» — сложный модуль');
  eq(methods.moduleClass.call(ctx, byId('mod_factcheck')), 'complex',
    '5: «Фактчек» — сложный модуль');
  eq(methods.moduleClass.call(ctx, byId('mod_nostalgia')), 'small',
    '5: «Ностальгия» — малый модуль');
  eq(methods.moduleClass.call(ctx, byId('mod_experience')), 'small',
    '5: «Опыт» — малый модуль');
  eq(methods.moduleClass.call(ctx, byId('mod_embeddings')), 'infrastructure',
    '5: «Векторная память» — инфраструктурный модуль');
  eq(methods.moduleClass.call(ctx, byId('mod_time')), 'maintenance',
    '5: «Время» — maintenance/policy');

  const ws = mkCtx({
    workspace: { module: byId('mod_nostalgia'), slug: 'nostalgia',
                 tab: 'overview', door: 'modules' },
    workspaceModule: byId('mod_nostalgia'),
  });
  eq(computed.workspaceSurfaceClass.call(ws),
    'workspace-surface workspace-surface--small',
    '5: small-модуль получает opt-in класс поверхности');
  const lib = mkCtx({
    workspace: { module: byId('mod_summary'), slug: 'summary', tab: 'prompts',
                 door: 'library' },
    workspaceModule: byId('mod_summary'),
  });
  eq(computed.workspaceSurfaceClass.call(lib), '',
    '5: библиотека промптов не меняет ширину модульной поверхности');

  // 8/12+4/12 — только внутри явного wrapper и ровно с двумя блоками.
  eq((INDEX_HTML.match(
    /data-workspace-split data-workspace-split-blocks="2"/g) || []).length,
    1, '5: ровно один opt-in wrapper с двумя sibling-блоками');
  ok(INDEX_HTML.indexOf('data-workspace-split-main') >= 0,
    '5: main-блок 8/12 присутствует');
  ok(INDEX_HTML.indexOf('data-workspace-split-side') >= 0,
    '5: side-блок 4/12 присутствует');
  ok(!/data-workspace-split-blocks="[13]"/.test(INDEX_HTML),
    '5: wrapper не применяется к одному/трём блокам');
  eq(methods.submoduleOwnerLinksForTab.call(ctx, 'memory_rag').length, 3,
    '5: memory_rag → три ссылки владельца');
  eq(methods.submoduleOwnerLinksForTab.call(ctx, 'permsoc').length, 1,
    '5: permsoc → ссылка «Характер»');
  eq(methods.submoduleOwnerLinksForTab.call(ctx, 'mod_summary').length, 0,
    '5: обычная вкладка не получает owner-ссылки');
}

// ── (6) LAY-01: реальные пропорции/ширины и одна подпись «Расширенные» ─────
{
  ok(/--sidebar-w:\s*216px/.test(APP_CSS) ||
     /\.app-shell\.ia-v2 \{[^}]*padding-left:\s*216px/.test(APP_CSS),
    '6: desktop sidebar 216px');
  const side = APP_CSS.match(/\.app-sidebar \{[^}]*width:\s*(\d+)px/);
  const sideW = side ? parseInt(side[1], 10) : 216;
  ok(sideW >= 190 && sideW <= 220, '6: sidebar в диапазоне 190–220');
  ok(APP_CSS.indexOf('calc(100% - 1440px - 1rem)') >= 0,
    '6: рабочая область ограничена 1440px на широком desktop');
  ok(APP_CSS.indexOf('calc(100% - 1000px - 1rem)') >= 0,
    '6: простые вкладки ≤1000px (900–1000)');
  ok(/\.workspace-split\s*\{[^}]*grid-template-columns:\s*repeat\(12/.test(APP_CSS),
    '6: wrapper использует 12-колоночную сетку');
  ok(/\.workspace-split__main\s*\{[^}]*grid-column:\s*span 8/.test(APP_CSS),
    '6: main = 8/12');
  ok(/\.workspace-split__side\s*\{[^}]*grid-column:\s*span 4/.test(APP_CSS),
    '6: side = 4/12');
  ok(/@media \(max-width: 1023px\)[\s\S]{0,500}workspace-split__main/.test(APP_CSS),
    '6: на tablet/mobile 8/4 схлопывается в одну колонку');
  ok(/@media \(max-width: 1199px\), \(pointer: coarse\)[\s\S]{0,1200}min-height:\s*44px/.test(APP_CSS),
    '6: touch-цели ≥44 на tablet/mobile/coarse');
  ok(INDEX_HTML.indexOf('data-workspace-surface') >= 0,
    '6: поверхность модуля размечена для измерения пропорций');
  ok(INDEX_HTML.indexOf('data-workspace-class') >= 0,
    '6: класс модуля виден в DOM (wireframe-проверка)');
  eq(INDEX_HTML.indexOf('>Расширенные настройки<'), -1,
    '6: вторая подпись «Расширенные настройки» нормализована');
  ok((INDEX_HTML.match(/Расширенные системные/g) || []).length >= 3,
    '6: единая подпись зоны «Расширенные системные»');
}

// ── (7) WF-01: одна шапка модуля, каталог/классы не декоративны ────────────
{
  // В исходнике две ВЗАИМОИСКЛЮЧАЮЩИЕ ветки (config-модуль и policy
  // «Время»); в DOM рендерится ровно одна — это проверяет e2e.
  ok(INDEX_HTML.indexOf('data-workspace-head') >= 0,
    '7: шапка модуля размечена');
  ok(INDEX_HTML.indexOf('activeTab === \'mod_time\'') >= 0,
    '7: policy-страница «Время» имеет собственную ветку (design §4.5)');
  ok(INDEX_HTML.indexOf(':data-workspace-class="moduleClass(workspaceModule)"') >= 0,
    '7: класс модуля привязан к фактическому workspaceModule');
  ok(INDEX_HTML.indexOf('data-module-parent-route') >= 0,
    '7: parent-чип каталога несёт фактический route');
  ok(INDEX_HTML.indexOf('data-workspace-parent-route') >= 0,
    '7: parent-чип шапки несёт фактический route');
  ok(INDEX_HTML.indexOf('data-owner-links') >= 0 &&
     INDEX_HTML.indexOf('data-owner-link') >= 0,
    '7: родительская поверхность содержит строку-ссылки владельца');
}

console.log('OK mod-acl W2c navigation/layout: ' + checks + ' checks');
