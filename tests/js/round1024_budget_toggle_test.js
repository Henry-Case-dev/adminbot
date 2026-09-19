'use strict';
/* F21 round1024 (budget-global-toggle-round1024, ADR-1024-22 D7) — мастер-
 * рубильник бюджетов в карточке «Бюджеты» (раздел «Модули»).
 *
 * Покрытие:
 *   - в MODULES карточка mod_budgets содержит toggleKey 'flags.budgets_enabled'
 *     и НЕ содержит noToggle;
 *   - карточек модулей ровно 12 (tma-menu-freeze: состав не изменился);
 *   - в TABS источниках вкладки mod_budgets присутствует группа
 *     flags_module_budgets (зеркало Python-rule);
 *   - новых вкладок нет: число вкладок в TABS заморожено (25), а Python-
 *     инвариант TAB_RULES = 20 проверяется pytest-пинами.
 *
 * Запуск: node tests/js/round1024_budget_toggle_test.js → BUDGET-TOGGLE-OK
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

// 1) Карточка «Бюджеты» — рабочий мастер-тумблер.
const card = data.modules.filter((m) => m.id === 'mod_budgets')[0];
assert(card, 'карточка mod_budgets должна присутствовать');
assert.strictEqual(card.noToggle, undefined,
  'F21: у mod_budgets не должно быть noToggle');
assert.strictEqual(card.toggleKey, 'flags.budgets_enabled',
  'F21: toggleKey = flags.budgets_enabled');

// tma-menu-freeze: F5 (10.24) санкционировал +1 карточку → 12→13.
assert.strictEqual(data.modules.length, 13, 'карточек модулей — 13');

// 2) Вкладка mod_budgets получила источник flags_module_budgets.
const tab = data.tabs.filter((t) => t.id === 'mod_budgets')[0];
assert(tab, 'вкладка mod_budgets должна присутствовать');
const groups = [];
(tab.sources || []).forEach((src) => {
  (src.groups || []).forEach((g) => groups.push(g));
});
assert(groups.indexOf('flags_module_budgets') >= 0,
  'F21: источник flags_module_budgets во вкладке mod_budgets');
// прежние лимиты не потеряны
['limits_chat_key', 'limits_chat_context', 'limits_worker'].forEach((g) => {
  assert(groups.indexOf(g) >= 0, 'лимит-группа на месте: ' + g);
});

// 3) tma-menu-freeze: F5 (10.24, ADR-1024-9) санкционировал РОВНО +1 вкладку
// (mod_images) → 25→26. Python-инвариант TAB_RULES = 21 проверяется
// pytest-пинами.
assert.strictEqual(data.tabs.length, 26, 'tma-menu-freeze: вкладок 26');
const ids = data.tabs.map((t) => t.id);
assert.strictEqual(ids.length, ids.filter((v, i) => ids.indexOf(v) === i).length,
  'дубли вкладок недопустимы');
assert(ids.indexOf('mod_budgets') >= 0, 'вкладка mod_budgets на месте');

console.log('BUDGET-TOGGLE-OK');
