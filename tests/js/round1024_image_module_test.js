'use strict';
/* F5 round1024 (image-module-toggle-round1024, ADR-1024-9) — отдельная
 * карточка «Генерация изображений» в разделе «Модули».
 *
 * Покрытие:
 *   - в MODULES есть карточка mod_images с toggleKey
 *     'flags.image_generation_module_enabled', tab 'mod_images', icon
 *     'grid_view'; карточка не дублируется;
 *   - карточек модулей ровно 13 (санкционированный menu-freeze +1);
 *   - в TABS есть config-вкладка mod_images с источником flags_module_images;
 *   - группы изображений НЕ в llm_providers и НЕ в mod_direct (один дом);
 *   - вкладок всего 26 (25 + 1), без дублей id;
 *   - computed visibleModules: OFF uiFlag('IMAGE_MODULE_CARD_ENABLED') →
 *     карточка скрыта, ON/неизвестно → видна.
 *
 * Запуск: node tests/js/round1024_image_module_test.js → IMAGE-MODULE-OK
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
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() {
        if (_bodyChildren.indexOf(this) >= 0) {
          _bodyChildren.splice(_bodyChildren.indexOf(this), 1);
        }
      },
    };
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) {
      const i = _bodyChildren.indexOf(el);
      if (i >= 0) _bodyChildren.splice(i, 1);
      return el;
    },
  },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('x'); } } },
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
const data = captured.data();
const computed = captured.computed;
const methods = captured.methods;
assert(computed && computed.visibleModules, 'computed.visibleModules не найден');
assert(methods && methods.uiFlag, 'methods.uiFlag не найден');

// 1) Карточка «Генерация изображений» — рабочий главный тумблер.
const cards = data.modules.filter((m) => m.id === 'mod_images');
assert.strictEqual(cards.length, 1, 'карточка mod_images должна быть ровно одна');
const card = cards[0];
assert.strictEqual(card.toggleKey, 'flags.image_generation_module_enabled',
  'F5: toggleKey = flags.image_generation_module_enabled');
assert.strictEqual(card.tab, 'mod_images', 'F5: карточка ведёт на вкладку mod_images');
assert.strictEqual(card.icon, 'grid_view', 'F5: иконка — переиспользуемый grid_view');
assert.strictEqual(card.title, 'Генерация изображений', 'F5: подпись карточки');

// tma-menu-freeze: ровно +1 санкционированная карточка (12→13).
assert.strictEqual(data.modules.length, 13, 'карточек модулей — 13');

// 2) Вкладка mod_images: ровно одна группа flags_module_images.
const tabs = data.tabs.filter((t) => t.id === 'mod_images');
assert.strictEqual(tabs.length, 1, 'вкладка mod_images должна быть ровно одна');
const tab = tabs[0];
assert.strictEqual(tab.label, 'Генерация изображений', 'F5: label вкладки');
assert.strictEqual(tab.type, 'config', 'F5: mod_images — config-вкладка');
assert.strictEqual(tab.menu, 'modules', 'F5: nav — «Модули»');
const groups = [];
(tab.sources || []).forEach((src) => {
  (src.groups || []).forEach((g) => groups.push(g));
});
assert.deepStrictEqual(groups, ['flags_module_images'],
  'F5: вкладка mod_images покрывает ровно flags_module_images');

// 3) Один дом: группа изображений НЕ в llm_providers и НЕ в mod_direct.
['llm_providers', 'mod_direct'].forEach((tid) => {
  const t = data.tabs.filter((x) => x.id === tid)[0];
  const gs = [];
  ((t && t.sources) || []).forEach((src) => {
    (src.groups || []).forEach((g) => gs.push(g));
  });
  assert.strictEqual(gs.indexOf('flags_module_images'), -1,
    'F5: flags_module_images не должен дублироваться в ' + tid);
});

// 4) Всего вкладок 26 (25 + 1), без дублей.
assert.strictEqual(data.tabs.length, 26, 'F5: вкладок 26');
const ids = data.tabs.map((t) => t.id);
assert.strictEqual(ids.length, ids.filter((v, i) => ids.indexOf(v) === i).length,
  'дубли вкладок недопустимы');

// 5) visibleModules: OFF-флаг прячет карточку, ON/неизвестно — показывает.
function visible(uiFlags) {
  const stub = {
    modules: data.modules,
    uiFlag: function (name) {
      return methods.uiFlag.call({ me: { ui_flags: uiFlags } }, name);
    },
  };
  return computed.visibleModules.call(stub);
}
assert.strictEqual(visible({ IMAGE_MODULE_CARD_ENABLED: true })
  .filter((m) => m.id === 'mod_images').length, 1,
'F5: при флаге ON карточка видна');
assert.strictEqual(visible({ IMAGE_MODULE_CARD_ENABLED: false })
  .filter((m) => m.id === 'mod_images').length, 0,
'F5: при флаге OFF карточка скрыта');
assert.strictEqual(visible({}).filter((m) => m.id === 'mod_images').length, 1,
  'F5: без данных /api/me — безопасный дефолт ON');

// 6) Kill-switch вкладки (review iter1): OFF → `_flagTabHidden` истинна;
// visibleTabs исключает mod_images; диплинк `#/modules/images` откатывается
// на витрину `#/modules`. ON — вкладка открывается штатно.
function flagCtx(uiFlags) {
  return {
    route: '#/__none__',
    me: { role_name: 'admin' },
    activeTab: 'status',
    tabs: data.tabs,
    toast() {},
    syncBackButton() {},
    canViewTab() { return true; },
    uiFlag: function (name) {
      return methods.uiFlag.call({ me: { ui_flags: uiFlags } }, name);
    },
    _flagTabHidden: function (tabId) {
      return methods._flagTabHidden.call(this, tabId);
    },
    setTab(id) { this.activeTab = id; },
  };
}

assert.strictEqual(
  methods._flagTabHidden.call(flagCtx({ IMAGE_MODULE_CARD_ENABLED: false }),
    'mod_images'), true, 'F5: OFF → вкладка скрыта');
assert.strictEqual(
  methods._flagTabHidden.call(flagCtx({ IMAGE_MODULE_CARD_ENABLED: true }),
    'mod_images'), false, 'F5: ON → вкладка доступна');
assert.strictEqual(
  methods._flagTabHidden.call(flagCtx({}), 'mod_images'), false,
  'F5: без данных /api/me — дефолт ON');

// диплинк при OFF → редирект на #/modules.
let off = flagCtx({ IMAGE_MODULE_CARD_ENABLED: false });
methods.applyRoute.call(off, '#/modules/images');
assert.strictEqual(off.route, '#/modules',
  'F5: OFF — диплинк #/modules/images редиректится на витрину');
assert.strictEqual(off.activeTab, 'modules', 'F5: OFF — активна витрина «Модули»');

// при ON — вкладка открывается.
let on = flagCtx({ IMAGE_MODULE_CARD_ENABLED: true });
methods.applyRoute.call(on, '#/modules/images');
assert.strictEqual(on.route, '#/modules/images',
  'F5: ON — диплинк открывает вкладку mod_images');
assert.strictEqual(on.activeTab, 'mod_images', 'F5: ON — активна mod_images');

// visibleTabs: OFF прячет вкладку mod_images, ON — показывает.
const tabIds = (uiFlags) => computed.visibleTabs.call(flagCtx(uiFlags))
  .map((t) => t.id);
assert.strictEqual(tabIds({ IMAGE_MODULE_CARD_ENABLED: false })
  .indexOf('mod_images'), -1, 'F5: OFF — вкладки нет в visibleTabs');
assert(tabIds({ IMAGE_MODULE_CARD_ENABLED: true }).indexOf('mod_images') >= 0,
  'F5: ON — вкладка есть в visibleTabs');

console.log('IMAGE-MODULE-OK');
