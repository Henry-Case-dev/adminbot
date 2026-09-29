'use strict';
/* ASAP-3 round1028 (ADR-1028-2 D12/D17, §34/§35, T-4028/T-4029/T-4030) —
 * статический harness miniapp: Context Mode (derive −1/0/>0 от СУЩЕСТВУЮЩЕГО
 * ключа limits.chat_context_budget_tokens), секция DIRECT CONTEXT, force-
 * keywords read-only, диагностика (R17: только числа). Поведение рендера
 * веб-платформы не дублируется (см. python-инварианты каталога).
 *
 * Запуск: node tests/js/round1028_asap3_direct_context_test.js
 * Успех:  ASAP3-DIRECT-CONTEXT-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const APP = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const HTML = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  matchMedia: function () { return { matches: false, addEventListener() {} }; },
};
global.document = {
  getElementById: function () { return null; },
  addEventListener() {},
  documentElement: { style: { setProperty() {} } },
  body: { classList: { add() {}, remove() {}, toggle() {} } },
  createElement: function () {
    return { style: {}, setAttribute() {}, appendChild() {}, remove() {} };
  },
  head: { appendChild() {} },
  querySelector: function () { return null; },
  querySelectorAll: function () { return []; },
};
global.localStorage = {
  getItem: function () { return null; }, setItem() {}, removeItem() {},
};
global.fetch = function () {
  return Promise.resolve({ ok: true, status: 200, json: function () {
    return Promise.resolve({}); } });
};
try {
  global.navigator = { userAgent: 'node-harness' };
} catch (e) { /* Node >= 21: navigator — getter-only, пропускаем */ }

require(path.join(ROOT, 'web', 'app.js'));

const methods = captured.methods || {};

// ── 1. Context Mode: derive −1/0/>0 от chat_context_budget_tokens (D12) ────
function makeSelf(budgetValue, chatSource) {
  return Object.assign({}, methods, {
    configItems: [{
      key: 'limits.chat_context_budget_tokens',
      value: chatSource === 'chat' ? budgetValue : 16000,
      global_value: chatSource === 'chat' ? null : budgetValue,
      chat_source: chatSource,
    }],
    isChatContext: function () { return true; },
  });
}

assert.strictEqual(typeof methods.contextMode, 'function',
  'contextMode() должен существовать');
assert.strictEqual(typeof methods.setContextMode, 'function',
  'setContextMode() должен существовать');
assert.strictEqual(typeof methods.contextBudgetValue, 'function',
  'contextBudgetValue() должен существовать');

let self = makeSelf(-1, 'chat');
assert.strictEqual(methods.contextMode.call(self), 'unlimited',
  '−1 → Unlimited');
self = makeSelf(0, 'chat');
assert.strictEqual(methods.contextMode.call(self), 'dynamic',
  '0 → Dynamic');
self = makeSelf(null, 'chat');
assert.strictEqual(methods.contextMode.call(self), 'dynamic',
  'None → Dynamic (дефолт 16000)');
self = makeSelf(8000, 'chat');
assert.strictEqual(methods.contextMode.call(self), 'cap', '>0 → Cap');
assert.strictEqual(methods.contextBudgetValue.call(self), 8000);

// Глобальный слой (без per-chat override) — тоже derive от того же ключа.
self = makeSelf(-1, 'global');
assert.strictEqual(methods.contextMode.call(self), 'unlimited',
  'глобальный −1 → Unlimited');

// ── 2. loadDirectDiagnostics: существующий endpoint, fail-open ─────────────
assert.strictEqual(typeof methods.loadDirectDiagnostics, 'function',
  'loadDirectDiagnostics() должен существовать');

// ── 3. Шаблон: DIRECT CONTEXT card + описания §34 дословно ─────────────────
assert.ok(HTML.includes('data-direct-context'),
  'карточка DIRECT CONTEXT должна присутствовать');
assert.ok(HTML.includes('data-context-mode="dynamic"')
  && HTML.includes('data-context-mode="unlimited"'),
  'переключатель Dynamic/Unlimited должен присутствовать');
assert.ok(/не применять искусственные лимиты контекста/i.test(HTML),
  'описание Unlimited дословно §34');
assert.ok(HTML.includes('автоматически распределять доступный'),
  'описание Dynamic дословно §34');
assert.ok(HTML.includes('data-direct-diagnostics'),
  'диагностическая панель должна присутствовать');
assert.ok(HTML.includes('Model context window')
  && HTML.includes('Available for context')
  && HTML.includes('Current payload')
  && HTML.includes('Recent verbatim')
  && HTML.includes('Retrieved old episodes')
  && HTML.includes('Compressed background')
  && HTML.includes('Excluded low-priority'),
  '7 диагностических полей §34');

// ── 4. §35: force keywords read-only (D-PM-4: без force-toggle) ────────────
assert.ok(HTML.includes('data-force-keywords'),
  'force-keywords read-only блок должен присутствовать');
assert.ok(typeof methods.forceKeywordsDisplay === 'function',
  'forceKeywordsDisplay() должен существовать');
assert.ok(!HTML.includes('data-force-toggle'),
  'force-toggle НЕ вводится (гарантия §21 неотключаема)');

// 3 каталоговых тумблера группы «Принятие решений» — в каталоге (python-тесты
// T-4029), здесь — связка: autonomous/silent-ack/resolutions в app.js не
// дублируются (значения приходят из /api/config).

console.log('ASAP3-DIRECT-CONTEXT-OK');
