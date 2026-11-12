'use strict';
/* SELF-DIAG-01 final-fixes (F3 visual follow-up) — «Жёсткие правила» матрицы
 * «Самодиагностики».
 *
 * Дефект: `hard_rules` приходят как [{rule, message}], а шаблон делал
 * `item.hard_rules.join('; ')` → в UI выводилось `[object Object]`.
 * Контракт: helper `diagHardRulesText(item)` отдаёт человекочитаемые тексты
 * (message, иначе rule), корректно обрабатывает строки/пустые/`null`, и
 * шаблон использует именно helper, а не сырой join.
 *
 * Запуск: node tests/js/self_diag_hard_rules_text_test.js
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = {
  location: { hash: '', pathname: '/web/index.html', search: '' },
  addEventListener() {},
  matchMedia: () => ({ matches: false }),
  Telegram: null,
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  innerWidth: 390,
  innerHeight: 844,
  devicePixelRatio: 2,
};
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() {
    return { getContext: () => ({}), clientWidth: 320, clientHeight: 56,
             style: {}, classList: { add() {}, remove() {}, toggle() {} } };
  },
  documentElement: {
    style: { setProperty() {} },
    classList: {
      _s: {},
      toggle(name, on) { this._s[name] = !!on; },
      contains(name) { return !!this._s[name]; },
      add() {}, remove() {},
    },
  },
  body: { classList: { add() {}, remove() {}, toggle() {} }, style: {} },
};
global.localStorage = global.window.localStorage;
global.sessionStorage = global.window.sessionStorage;
global.history = { replaceState() {}, pushState() {} };
global.fetch = async function () { throw new Error('no fetch in test'); };

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp не вызван — app.js не зарегистрировал приложение');
const methods = captured.methods || {};

// ── helper существует (на старом коде здесь падение) ────────────────────────
assert.strictEqual(typeof methods.diagHardRulesText, 'function',
  'methods.diagHardRulesText отсутствует — шаблон снова может печатать объект');

// ── реальный payload категории «Промпты» (matrix_snapshot) ──────────────────
const promptRule = {
  rule: 'denied_prompt_content_member',
  message: 'Текст промптов доступен только администратору этого чата по явному '
    + 'запросу; участникам он не выдаётся.',
};
const text = methods.diagHardRulesText({ hard_rules: [promptRule] });
assert.strictEqual(text, promptRule.message,
  'показан не message правила: ' + text);
assert.ok(text.indexOf('[object Object]') < 0, '[object Object] в выводе');
assert.ok(text.indexOf('denied_prompt_content_member') < 0,
  'в основной слой просочился внутренний код правила');

// ── fallback на код, если текста нет (данные защитно) ───────────────────────
assert.strictEqual(
  methods.diagHardRulesText({ hard_rules: [{ rule: 'only_code' }] }),
  'only_code');

// ── строки/смеси/пустые/null ───────────────────────────────────────────────
assert.strictEqual(
  methods.diagHardRulesText({ hard_rules: ['готовая строка'] }),
  'готовая строка');
assert.strictEqual(
  methods.diagHardRulesText({ hard_rules: ['a', { message: 'b' }, { rule: 'c' }] }),
  'a; b; c');
assert.strictEqual(methods.diagHardRulesText({ hard_rules: [] }), '');
assert.strictEqual(methods.diagHardRulesText({}), '');
assert.strictEqual(methods.diagHardRulesText(null), '');
assert.strictEqual(methods.diagHardRulesText(undefined), '');
assert.strictEqual(
  methods.diagHardRulesText({ hard_rules: [null, undefined, {}, 0] }), '');
// защитно: готовая строка вместо массива показывается, прочее — пусто
assert.strictEqual(
  methods.diagHardRulesText({ hard_rules: 'готовая строка' }), 'готовая строка');
assert.strictEqual(methods.diagHardRulesText({ hard_rules: 42 }), '');

// ── шаблон: helper в строке «Жёсткие правила», сырого join нет ─────────────
const marker = 'Жёсткие правила:';
const at = INDEX.indexOf(marker);
assert.ok(at >= 0, 'строка «Жёсткие правила» не найдена в index.html');
const row = INDEX.slice(at, at + 200);
assert.ok(row.indexOf('diagHardRulesText(item)') >= 0,
  'шаблон не использует diagHardRulesText(item): ' + row.slice(0, 120));
assert.ok(!/hard_rules\s*\.\s*join\s*\(/.test(INDEX),
  'в шаблоне остался сырой join по hard_rules');
assert.ok(!/hard_rules\s*\.\s*join\s*\(/.test(APP_JS),
  'сырой join по hard_rules остался в app.js');

console.log('SELF-DIAG-HARD-RULES-TEXT-OK');
