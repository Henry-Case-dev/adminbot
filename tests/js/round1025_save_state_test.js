'use strict';
/* F0 round1025 (ревью) — РЕАЛЬНЫЙ JS-тест сохранения:
 *   * двойной тап по ключу → ровно 1 POST (guard in-flight, skipped не молчит);
 *   * 409 conflicting → черновик пользователя сохранён, один warn-тост;
 *   * устаревший scopeEpoch → ответ игнорируется;
 *   * null-токен не уходит в chat-scope (RC-6: сначала loadConfig);
 *   * notify идемпотентен (1 тост на операцию);
 *   * очередь тостов ≤3 и приоритет err>warn>ok;
 *   * _opNotified не растёт на повтор той же операции.
 *
 * Запуск: node tests/js/round1025_save_state_test.js
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
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;

function makeCtx(overrides) {
  const ctx = {
    scopeEpoch: 1,
    configChatUpdatedAt: 'tok1',
    saving: new Set(),
    configItems: [],
    _opSeq: 0,
    _opNotified: {},
    _toastSeq: 0,
    toasts: [],
    stickyConflict: [],
    stickyFailedKeys: [],
    loadConfigCalls: 0,
    apiCalls: [],
    _serializeValue: methods._serializeValue,
    _findConfigItem: methods._findConfigItem,
    _scopeGuard: methods._scopeGuard,
    persistItems: methods.persistItems,
    notify: methods.notify,
    toast: function (text, kind) {
      this.toasts.push({ text: text, kind: kind || 'ok' });
    },
    loadConfig: async function () { this.loadConfigCalls += 1; },
    api: async function (url, opts) {
      this.apiCalls.push({ url: url, opts: opts, body: opts && opts.body });
      return {};
    },
  };
  return Object.assign(ctx, overrides || {});
}

function item(key, value, perChat) {
  return { key: key, value: value, title: key,
           per_chat: perChat === undefined ? true : perChat };
}

(async function run() {
  // ── 1) Двойной тап по ключу → 1 POST ───────────────────────────────────
  {
    const ctx = makeCtx({});
    const it = item('limits.a', 5);
    ctx.configItems = [it];
    const p1 = methods.persistItems.call(ctx, [it], { silent: true });
    const p2 = methods.persistItems.call(ctx, [it], { silent: true });
    const [r1, r2] = await Promise.all([p1, p2]);
    assert.strictEqual(ctx.apiCalls.length, 1, 'двойной тап → ровно 1 POST');
    assert.strictEqual(r1.saved.length, 1, 'первый запрос сохранил ключ');
    assert.strictEqual(r2.inFlight, true, 'второй — in-flight (не молчит)');
    assert.deepStrictEqual(r2.skipped, ['limits.a'], 'skipped ключ отдан явно');
  }

  // ── 2) 409 conflicting → черновик сохранён, один warn/err ──────────────
  {
    const server = item('limits.a', 1);
    const serverItems = [server];
    const ctx = makeCtx({
      configItems: [item('limits.a', 7)],
      loadConfig: async function () {
        this.loadConfigCalls += 1;
        this.configItems = [item('limits.a', 1)];       // сервер: 1
      },
      api: async function () {
        this.apiCalls.push({});
        const e = { status: 409,
                    message: { code: 'conflict',
                               conflicting: [{ key: 'limits.a',
                                               your_value: 7,
                                               server_value: 1 }] } };
        throw e;
      },
    });
    const res = await methods.persistItems.call(ctx, [item('limits.a', 7)], {});
    const field = ctx.configItems.find(function (x) { return x.key === 'limits.a'; });
    assert.strictEqual(field.value, 7,
      'черновик пользователя НЕ уничтожен при конфликте');
    assert.ok(ctx.stickyConflict.indexOf('limits.a') >= 0,
      'ключ помечен как конфликт (подсветка)');
    assert.strictEqual(res.failed.length, 1, 'конфликт учтён как failed');
    assert.strictEqual(ctx.toasts.length, 1, 'ровно один тост на операцию');
    assert.notStrictEqual(ctx.toasts[0].kind, 'ok', 'без ложного успеха');
  }

  // ── 3) Устаревший scopeEpoch → ответ игнорируется ─────────────────────
  {
    const ctx = makeCtx({
      api: async function () {
        this.apiCalls.push({});
        ctx.scopeEpoch = 2;                       // scope сменился в полёте
        return {};
      },
    });
    const res = await methods.persistItems.call(
      ctx, [item('limits.a', 5)], { silent: true });
    assert.strictEqual(res.saved.length, 0, 'старый scope → не сохранено');
  }

  // ── 4) null-токен не уходит в chat-scope (сначала loadConfig) ──────────
  {
    let sentToken = 'unset';
    const ctx = makeCtx({
      configChatUpdatedAt: null,
      loadConfig: async function () {
        this.loadConfigCalls += 1;
        this.configChatUpdatedAt = 'tok2';
      },
      api: async function (url, opts) {
        this.apiCalls.push({});
        sentToken = JSON.parse(opts.body).updated_at;
        return {};
      },
    });
    await methods.persistItems.call(ctx, [item('limits.a', 5)], { silent: true });
    assert.ok(ctx.loadConfigCalls >= 1, 'null-токен → предварительный loadConfig');
    assert.strictEqual(sentToken, 'tok2', 'в POST ушёл актуальный токен');
  }

  // ── 5) notify идемпотентен (1 тост на операцию) ────────────────────────
  {
    const ctx = makeCtx({});
    methods.notify.call(ctx, 'op-same', { saved: ['limits.a'], failed: [] });
    methods.notify.call(ctx, 'op-same', { saved: ['limits.a'], failed: [] });
    assert.strictEqual(ctx.toasts.length, 1, 'повтор notify → без второго тоста');
  }

  // ── 6) Очередь ≤3 и приоритет err > warn > ok ──────────────────────────
  {
    const ctx = makeCtx({});
    ctx.toast = methods.toast;
    methods.toast.call(ctx, 'ok-1', 'ok');
    methods.toast.call(ctx, 'warn-1', 'warn');
    methods.toast.call(ctx, 'err-1', 'err');
    methods.toast.call(ctx, 'ok-2', 'ok');
    assert.ok(ctx.toasts.length <= 3, 'одновременно ≤3 тоста');
    assert.ok(ctx.toasts.some(function (t) { return t.kind === 'err'; }),
      'err сохраняется (высший приоритет)');
    assert.ok(!ctx.toasts.some(function (t) { return t.text === 'ok-2'; }),
      'лишний ok вытеснен');
  }

  // ── 7) _opNotified не растёт на повтор той же операции ────────────────
  {
    const ctx = makeCtx({});
    methods.notify.call(ctx, 'op-x', { saved: ['limits.a'] });
    methods.notify.call(ctx, 'op-x', { saved: ['limits.a'] });
    assert.strictEqual(Object.keys(ctx._opNotified).length, 1,
      '_opNotified: одна запись на операцию (ленивая очистка)');
  }

  console.log('ROUND1025-SAVE-STATE-OK');
  process.exit(0);          // не ждём setTimeout-очистку тостов/notify
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
