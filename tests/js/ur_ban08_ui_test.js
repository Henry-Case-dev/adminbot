'use strict';
/* UR-BAN-08 (UNIFIED-REPLY) — РЕАЛЬНЫЙ JS-тест витрины «Прямых ответов».
 *
 * Требование карты: «UI — не панель из 30 огромных карточек со слегка
 * улучшенными подписями; приоритет — действие + правда об исполняемом
 * состоянии». Порога «сколько карточек = панель» контракт не задаёт, поэтому
 * проверяется СТРУКТУРА, которую нельзя получить переименованием карточек:
 *
 *   1. карточка модуля собирается боевым путём реестра
 *      (`f3ApplyModuleRegistry` → `WORKSPACE_TABS`) и открывается ТРЕМЯ
 *      смысловыми уровнями в фиксированном порядке overview → inspector →
 *      settings, а не одной поверхностью;
 *   2. подписи уровней — действие / правда об исполняемом состоянии /
 *      «Дополнительные настройки» (реальная `workspaceTabLabel`);
 *   3. параметры каталога НЕ вываливаются на посадочную вкладку: ни одна
 *      реальная группа «Прямых ответов» не раскладывается в overview, все они
 *      остаются в settings; overview — живая секция состояния, не сетка полей;
 *   4. legacy-ключи остаются read-only (переиспользован контракт UI-21:
 *      ось редактирования — из backend `item.eff.readonly`);
 *   5. вкладка inspector применима только к mod_direct — мёртвых вкладок в
 *      других модулях нет.
 *
 * Мутационная защита (RED, см. evidence): тест падает, если порядок вкладок
 * или подпись меняются (проверено копией app.js с переставленными вкладками
 * через UR_BAN08_APP_JS — продуктовый файл при этом не трогается).
 *
 * Запуск: node tests/js/ur_ban08_ui_test.js -> UR-BAN08-UI-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = { location: { hash: '' }, addEventListener() {},
                 Telegram: null, confirm: function () { return true; } };
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = { getItem() { return null; }, setItem() {},
                          removeItem() {} };
global.localStorage = { getItem() { return null; }, setItem() {},
                        removeItem() {} };
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

const ROOT = path.join(__dirname, '..', '..');
// UR_BAN08_APP_JS — только для мутационного RED-прогона (копия файла).
const APP_JS = process.env.UR_BAN08_APP_JS || path.join(ROOT, 'web', 'app.js');
require(APP_JS);

assert(captured, 'Vue.createApp не вызван');
const methods = captured.methods || {};

// ── 1. Карточка модуля боевым путём реестра ───────────────────────────────
const regCtx = Object.assign({}, methods, { modules: [], _f4Registry: {} });
methods.f3ApplyModuleRegistry.call(regCtx, [
  { id: 'direct', title: 'Прямые ответы', description: 'Прямые ответы',
    visibility: 'visible', permissions: {}, kind: 'product_module' },
]);
const card = (regCtx.modules || []).filter(function (m) {
  return m.id === 'mod_direct';
})[0];
assert(card, 'mod_direct не собран через реестр (f3ApplyModuleRegistry)');
assert(Array.isArray(card.tabs) && card.tabs.length > 0,
  'у карточки mod_direct нет объявленных workspace-вкладок');
assert.deepStrictEqual(card.tabs.slice(0, 3),
  ['overview', 'inspector', 'settings'],
  'UR-20.1/UR-BAN-08: первые три уровня модуля обязаны быть '
  + 'overview → inspector → settings, получено: ' + card.tabs.slice(0, 3));
assert(card.tabs.length > 3,
  'модуль не должен схлопываться в одну вкладку (редакторы/модели/лимиты '
  + 'остаются рабочими вкладками)');

// ── 2. Подписи уровней (реальная workspaceTabLabel) ──────────────────────
const labelCtx = Object.assign({}, methods, {
  workspace: { module: card, slug: 'direct', tab: 'overview', door: 'modules' },
});
assert.strictEqual(methods.workspaceTabLabel.call(labelCtx, 'overview'),
  'Как бот отвечает', 'подпись уровня «действие» изменена');
assert.strictEqual(methods.workspaceTabLabel.call(labelCtx, 'inspector'),
  'Что бот видел', 'подпись уровня «правда об исполняемом состоянии» изменена');
assert.strictEqual(methods.workspaceTabLabel.call(labelCtx, 'settings'),
  'Дополнительные настройки', 'подпись уровня «настройки» изменена');

// ── 3. Параметры не на посадочной вкладке ────────────────────────────────
// Группы — те же, что объявлены источниками mod_direct в app.js (11 групп
// флагов/лимитов/моделей/реакций). Категория важна: раскладку решает
// workspaceGroupTab по category/id, а не ручной список вкладок.
const GROUPS = [
  { id: 'flags_module_direct', category: 'flags', items: [] },
  { id: 'flags_chat_behavior', category: 'flags', items: [] },
  { id: 'flags_decision_making', category: 'flags', items: [] },
  { id: 'flags_direct_l1', category: 'flags', items: [] },
  { id: 'limits_chat', category: 'limits', items: [] },
  { id: 'limits_chat_behavior', category: 'limits', items: [] },
  { id: 'limits_chat_budgets', category: 'limits', items: [] },
  { id: 'limits_temperature', category: 'limits', items: [] },
  { id: 'limits_direct_l1', category: 'limits', items: [] },
  { id: 'models_direct_l1', category: 'models', items: [] },
  { id: 'reactions_chat', category: 'reactions', items: [] },
];
const descriptor = { id: 'mod_direct', type: 'config', menu: 'modules',
                     label: 'Прямые ответы', sources: [] };
const groupCtx = Object.assign({}, methods, {
  workspace: { module: card, slug: 'direct', tab: 'settings', door: 'modules' },
  tabs: [descriptor],
  groupedForTab: function () { return GROUPS; },
});
// Группы модуля распределены по рабочим вкладкам: флаги/реакции → settings,
// лимиты → limits, слот модели → models. Совокупно они покрывают все 11 групп
// (ничего не теряется), но НИ ОДНА не попадает на посадочную вкладку.
const byTab = {};
GROUPS.forEach(function (g) {
  const tab = methods.workspaceGroupTab.call(groupCtx, card, g);
  (byTab[tab] = byTab[tab] || []).push(g.id);
});
assert.deepStrictEqual(Object.keys(byTab).sort(), ['limits', 'models', 'settings'],
  'UR-BAN-08: параметры модуля живут в рабочих вкладках settings/limits/models, '
  + 'получено: ' + JSON.stringify(byTab));
assert.strictEqual(byTab.settings.length, 5,
  'settings: 4 группы флагов + реакции чата');
assert.strictEqual(byTab.limits.length, 5, 'limits: 5 групп лимитов');
assert.strictEqual(byTab.models.length, 1, 'models: слот L1-модели');
const overviewGroups = methods._workspaceGroupsFor.call(groupCtx, card, 'overview');
assert.deepStrictEqual(overviewGroups, [],
  'UR-BAN-08: на посадочной вкладке не должно быть сетки параметров '
  + '(это и есть запрещённая «панель карточек»)');
const inspectorGroups = methods._workspaceGroupsFor.call(groupCtx, card, 'inspector');
assert.deepStrictEqual(inspectorGroups, [],
  'inspector — трасса исполнения, а не поверхность редактирования');
// settings-вкладка получает ровно свои 5 групп, а не все 11 сразу.
assert.strictEqual(
  methods._workspaceGroupsFor.call(groupCtx, card, 'settings').length,
  byTab.settings.length,
  'вкладка настроек не должна рендерить группы лимитов/моделей');
// Ни одна объявленная вкладка модуля не является «всеми параметрами сразу»:
// groups рендерятся только в settings|limits|models (generic-сетка).
['synthesizer', 'verbalizer', 'testing', 'inspector', 'overview'].forEach(
  function (tabId) {
    const groups = methods._workspaceGroupsFor.call(groupCtx, card, tabId);
    assert.deepStrictEqual(groups, [],
      'на вкладке ' + tabId + ' не должно быть generic-сетки параметров');
  });

// ── 4. Legacy-ключи read-only (контракт UI-21, ось — из backend) ─────────
const LEGACY_ITEMS = [
  { key: 'GOODMORNING_TZ', value: 'Asia/Yekaterinburg', type: 'str',
    category: 'reactions', group: 'reactions_goodmorning',
    progressive_level: '', title: 'old', description: 'old',
    eff: { status: 'legacy', readonly: true,
      reason_inactive: 'Пояс рассылки — ChatClock чата.' } },
  { key: 'SUMMARY_TIMEZONE', value: 'Asia/Yekaterinburg', type: 'str',
    category: 'reactions', group: 'reactions_summary',
    progressive_level: '', title: 'old', description: 'old',
    eff: { status: 'legacy', readonly: true,
      reason_inactive: 'Пояс саммари — ChatClock чата.' } },
];
const legacyCtx = Object.assign({}, methods, {
  configItems: LEGACY_ITEMS, permissions: { wildcard: true },
  activeTab: 'mod_direct', isGlobalAdminEffective: true,
});
methods._normalizeConfigItems.call(legacyCtx, LEGACY_ITEMS);
LEGACY_ITEMS.forEach(function (it) {
  assert.strictEqual(it.__uiReadonly, true,
    it.key + ': legacy-ключ обязан быть read-only в витрине');
  assert.strictEqual(methods.canEditConfig.call(legacyCtx, it.key), false,
    it.key + ': legacy-ключ не должен редактироваться даже у админа');
});

// ── 5. inspector применим только к mod_direct ────────────────────────────
const contentCtx = Object.assign({}, methods, { configItems: [{}] });
assert.strictEqual(
  methods.workspaceTabHasContent.call(contentCtx, card, 'inspector'), true,
  'у mod_direct инспектор исполнения обязан существовать');
assert.strictEqual(
  methods.workspaceTabHasContent.call(contentCtx,
    { id: 'mod_factcheck', tabs: ['overview', 'inspector', 'settings'] },
    'inspector'), false,
  'inspector не должен появляться у модулей без своей трассы (мёртвая вкладка)');

console.log('UR-BAN-08: три уровня, порядок, подписи, раскладка групп и '
  + 'read-only legacy проверены на реальном web/app.js');
console.log('UR-BAN08-UI-OK');
