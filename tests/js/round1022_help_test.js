'use strict';
/* F7 help-ui-system2-round1022 — реальный JS-гейт рендера Справки.
 *
 * Проверяет:
 *   1) methods.sanitizeHtml делегирует в window.DOMPurify.sanitize с ОДНИМ
 *      аргументом (default-конфиг, без ALLOWED_TAGS-обрезки blockquote/h1/h2);
 *   2) computed.sanitizedInfoHtml санитайзит infoHtml (команды-цитаты живы);
 *   3) fail-closed: без DOMPurify теги экранируются, а не рендерятся сырыми.
 *
 * Запуск: node tests/js/round1022_help_test.js
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
global.window = {
  location: { hash: '' },
  addEventListener() {},
  Telegram: null,
  DOMPurify: {
    sanitize: function () {
      global.__purifyArgs = Array.prototype.slice.call(arguments);
      return '[purified]' + arguments[0];
    },
  },
};
const _bodyChildren = [];
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    const el = {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() {
        const idx = _bodyChildren.indexOf(el);
        if (idx >= 0) _bodyChildren.splice(idx, 1);
      },
    };
    return el;
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) {
      const idx = _bodyChildren.indexOf(el);
      if (idx >= 0) _bodyChildren.splice(idx, 1);
      return el;
    },
  },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: {
    clipboard: { writeText: async function () { throw new Error('no clipboard'); } },
  },
});
global.sessionStorage = {
  _s: {},
  getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.localStorage = global.sessionStorage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;

// ── F7-1: sanitizeHtml → DOMPurify default (один аргумент) ────────────────
(function () {
  global.__purifyArgs = null;
  const src = '<h1>Гайд</h1><h2>Раздел</h2>'
    + '<blockquote>Бот, транскрипт</blockquote>';
  const out = methods.sanitizeHtml(src);
  assert.strictEqual(out, '[purified]' + src,
    'F7: sanitizeHtml делегирует в DOMPurify.sanitize');
  assert.strictEqual(global.__purifyArgs.length, 1,
    'F7: DOMPurify.sanitize вызван с одним аргументом (default-конфиг)');
  assert.strictEqual(global.__purifyArgs[0], src,
    'F7: на вход DOMPurify идёт сырой html');
})();

// ── F7-2: computed.sanitizedInfoHtml санитайзит infoHtml ──────────────────
(function () {
  const src = '<blockquote>Бот, о чем видео</blockquote>';
  const out = computed.sanitizedInfoHtml.call({
    infoHtml: src, sanitizeHtml: methods.sanitizeHtml,
  });
  assert.strictEqual(out, '[purified]' + src,
    'F7: computed.sanitizedInfoHtml прогоняет infoHtml через санитайз');
})();

// ── F7-3: fail-closed без DOMPurify ───────────────────────────────────────
(function () {
  const saved = global.window.DOMPurify;
  delete global.window.DOMPurify;
  const warn = console.warn;
  console.warn = function () {};
  try {
    const out = methods.sanitizeHtml('<blockquote>x</blockquote>');
    assert.ok(out.indexOf('<blockquote>') < 0,
      'F7: без DOMPurify тег не проходит');
    assert.ok(out.indexOf('&lt;blockquote&gt;') >= 0,
      'F7: без DOMPurify тег экранирован');
  } finally {
    console.warn = warn;
    global.window.DOMPurify = saved;
  }
})();

console.log('round1022 help-ui JS gate: OK');
