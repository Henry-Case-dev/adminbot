'use strict';
/* F9 round1025 (ADR-1025-22 D1/D2/D3/D4) — секрет-поле и жизненный цикл ключа.
 *
 * Покрытие (§50/§78, R17):
 *   * secretDisplay: ••••••••last4 / «Ключ установлен» / «Не настроен»;
 *   * _seedSecretMasks больше НЕ засеивает маску в keyDrafts (D1);
 *   * blockFieldValue для секрета → '' (маска — display, не значение input);
 *   * GUARD R31: маска/композит НЕ уходит в POST/PUT и в /api/llm/test;
 *   * «Заменить»: реальный ключ уходит в POST (новая маска после reload);
 *   * пустое поле НЕ удаляет старый секрет (saveKeyItem guard);
 *   * «Удалить» (D2): image-ключ → DELETE /api/config/keys/own/{key};
 *     прочий глобальный → F0 empty-write (persistItems value:'') — НЕ
 *     DELETE /api/config/chat/{key}; confirm-гейт;
 *   * сохранение несекретных не трогает секрет (dirtyKeyItems пуст);
 *   * компонент `secret-field` зарегистрирован, x-template на месте;
 *   * index.html: нет прямых `v-model="keyDrafts[...]"` (единый компонент).
 *
 * Запуск: node tests/js/round1025_f9_secret_field_test.js  (F9-SECRET-OK)
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

const SECRET_MASK = '\u2022'.repeat(12);

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
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null,
                  confirm: function () { return true; } };
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {}, focus() {} }; },
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
const computed = captured.computed;

const INDEX = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
const CSS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'static', 'app.css'), 'utf8');

function makeCtx(overrides) {
  const calls = [];
  const ctx = {
    configItems: [],
    keyDrafts: {},
    blockDrafts: {},
    saving: new Set(),
    _opSeq: 0,
    configChatUpdatedAt: 'tok1',
    stickyFailed: [], stickyFailedKeys: [], stickyConflict: [],
    toasts: [],
    toast(m, k) { this.toasts.push([m, k]); },
    uiFlag() { return true; },
    _findConfigItem: methods._findConfigItem,
    _serializeValue: methods._serializeValue,
    _preserveScroll(fn) { return fn && fn.call(this); },
    loadConfig() {},
    async api(url, opts) { calls.push({ url, opts }); return {}; },
  };
  return { ctx: Object.assign(ctx, overrides || {}), calls };
}

(async function main() {
  // ── D3: secretDisplay — единый display-индикатор ────────────────────────
  {
    assert.strictEqual(typeof methods.secretDisplay, 'function',
      'secretDisplay — метод');
    const ctx = {
      configItems: [
        { key: 'k.last4', value: { configured: true, last4: 'a7F2' } },
        { key: 'k.nolast', value: { configured: true, last4: null } },
        { key: 'k.off', value: { configured: false, last4: null } },
        { key: 'k.null', value: null },
      ],
    };
    assert.strictEqual(methods.secretDisplay.call(ctx, 'k.last4').maskText,
      '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022a7F2', 'last4 → маска');
    assert.strictEqual(methods.secretDisplay.call(ctx, 'k.nolast').maskText,
      'Ключ установлен', 'configured без last4 → «Ключ установлен»');
    assert.strictEqual(methods.secretDisplay.call(ctx, 'k.off').maskText,
      'Не настроен', 'configured:false → «Не настроен»');
    assert.strictEqual(methods.secretDisplay.call(ctx, 'k.null').maskText,
      'Не настроен', 'null → «Не настроен»');
    assert.strictEqual(
      methods.secretDisplay.call(ctx, { key: 'k.last4' }).maskText,
      '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022a7F2',
      '{key}-поле блока резолвится по configItems');
    // R17: сырое значение наружу не отдаётся.
    assert.strictEqual(methods.secretDisplay.call(ctx, 'k.last4').maskText
      .indexOf('raw'), -1, 'R17: сырой секрет не в индикаторе');
  }

  // ── D1: _seedSecretMasks НЕ засеивает маску; чистит остатки ─────────────
  {
    const ctx = {
      isKeyConfigured: methods.isKeyConfigured,
      keyDrafts: { legacy: SECRET_MASK + 'typed' },
      configItems: [
        { key: 'k1', category: 'keys', secret: true,
          value: { configured: true, last4: 'FAKE' } },
      ],
    };
    methods._seedSecretMasks.call(ctx);
    assert.strictEqual(ctx.keyDrafts['k1'], undefined,
      'D1: configured-секрет НЕ засеян маской (поле пустое)');
    assert.strictEqual(ctx.keyDrafts.legacy, undefined,
      'D1: композит/legacy-маска вычищена');
  }

  // ── D1: blockFieldValue для секрета → '' ────────────────────────────────
  {
    const ctx = {
      blockDrafts: {},
      configItems: [
        { key: 'keys.llm_api_key', type: 'str', secret: true, category: 'keys',
          value: { configured: true, last4: '1234' } },
      ],
    };
    assert.strictEqual(methods.blockFieldValue.call(
      ctx, { key: 'keys.llm_api_key', secret: true }), '',
      'D1: секрет-поле пустое (маска не значение input)');
  }

  // ── §78/R31: маска/композит НЕ уходит в API ─────────────────────────────
  for (const draft of [SECRET_MASK, SECRET_MASK + 'X']) {
    const { ctx, calls } = makeCtx({
      configItems: [{ key: 'keys.auth', title: 'Auth', category: 'keys',
                      secret: true, per_chat: false }],
      keyDrafts: { 'keys.auth': draft },
    });
    const ok = await methods.saveKeyItem.call(ctx, ctx.configItems[0]);
    assert.strictEqual(calls.length, 0,
      'R31: маска/композит → 0 запросов ([' +
      draft.replace(SECRET_MASK, '<MASK>') + '])');
    assert.strictEqual(ok, false, 'R31: маска/композит → no-op');
    assert.strictEqual(ctx.toasts.length, 1, 'R31: ровно один warn-тост');
    assert.strictEqual(ctx.toasts[0][1], 'warn', 'R31: тост warn');
  }

  // ── §78: «Заменить» — реальный ключ уходит в POST ───────────────────────
  {
    const { ctx, calls } = makeCtx({
      configItems: [{ key: 'keys.auth', title: 'Auth', category: 'keys',
                      secret: true, per_chat: false }],
      keyDrafts: { 'keys.auth': 'brand-new-key' },
    });
    await methods.saveKeyItem.call(ctx, ctx.configItems[0]);
    assert.strictEqual(calls.length, 1, 'replace → ровно 1 POST');
    const body = JSON.parse(calls[0].opts.body);
    assert.strictEqual(body.items[0].value, 'brand-new-key',
      'replace: в POST реальный ключ');
    assert.strictEqual(body.items[0].value.indexOf(SECRET_MASK), -1,
      'replace: маски нет в теле');
  }

  // ── §78: пустое поле НЕ удаляет старый секрет ───────────────────────────
  {
    const { ctx, calls } = makeCtx({
      configItems: [{ key: 'keys.auth', title: 'Auth', category: 'keys',
                      secret: true, per_chat: false }],
      keyDrafts: { 'keys.auth': '' },
    });
    const ok = await methods.saveKeyItem.call(ctx, ctx.configItems[0]);
    assert.strictEqual(calls.length, 0, 'пустое поле → 0 запросов');
    assert.strictEqual(ok, false, 'пустое поле → no-op (не удаляет)');
    assert.ok(ctx.toasts.some((t) => /Введите новый ключ/.test(t[0])),
      'пустое поле → «Введите новый ключ»');
  }

  // ── D2: «Удалить» глобального НЕ-image секрета → F0 empty-write ─────────
  {
    const persistCalls = [];
    const { ctx, calls } = makeCtx({
      configItems: [{ key: 'TAVILY_API_KEY', title: 'Ключ Tavily',
                      category: 'keys', secret: true, per_chat: false }],
      persistItems: async function (items, opts) {
        persistCalls.push({ items, opts });
        return { saved: [items[0].key], failed: [], skipped: [],
                 state: 'saved' };
      },
    });
    const ok = await methods.deleteKeyItem.call(ctx, 'TAVILY_API_KEY');
    assert.strictEqual(ok, true, 'D2: удаление выполнено');
    assert.strictEqual(calls.length, 0,
      'D2: НЕ вызывается DELETE /api/config/chat/{key}');
    assert.strictEqual(persistCalls.length, 1, 'D2: ровно один empty-write');
    assert.strictEqual(persistCalls[0].items[0].value, '',
      'D2: пустая запись = «не настроен»');
    assert.strictEqual(persistCalls[0].items[0].per_chat, false,
      'D2: global (per_chat:false)');
  }

  // ── D2: image-ключ при BYOK ON → DELETE /api/config/keys/own/{key} ──────
  {
    const { ctx, calls } = makeCtx({
      configItems: [{ key: 'keys.image_api_key', title: 'Ключ картинок',
                      category: 'keys', secret: true, per_chat: false }],
      uiFlag() { return true; },
      persistItems: async function () {
        throw new Error('D2: image-ключ не должен идти empty-write');
      },
    });
    const ok = await methods.deleteKeyItem.call(ctx, 'keys.image_api_key');
    assert.strictEqual(ok, true, 'D2: image-ключ удалён');
    assert.strictEqual(calls.length, 1, 'D2: один DELETE own');
    assert.ok(calls[0].url.indexOf('/api/config/keys/own/keys.image_api_key') >= 0,
      'D2: DELETE /api/config/keys/own/{key}');
    assert.strictEqual(calls[0].opts.method, 'DELETE', 'D2: метод DELETE');
    // H-F9S-1: без `global:true` `api()` добавит `X-Chat-Id` → сервер уйдёт
    // в chat-ветку (`delete_chat_key`, whitelist llm-only) → 422.
    assert.strictEqual(calls[0].opts.global, true,
      'D2: DELETE own идёт global:true (иначе chat-scope → 422)');
  }

  // ── D2: BYOK OFF → empty-write (не safe-эндпоинт) ───────────────────────
  {
    const persistCalls = [];
    const { ctx, calls } = makeCtx({
      configItems: [{ key: 'keys.image_api_key', title: 'Ключ картинок',
                      category: 'keys', secret: true, per_chat: false }],
      uiFlag() { return false; },
      persistItems: async function (items) {
        persistCalls.push(items);
        return { saved: [items[0].key], failed: [], skipped: [], state: 'saved' };
      },
    });
    await methods.deleteKeyItem.call(ctx, 'keys.image_api_key');
    assert.strictEqual(calls.length, 0, 'D2/OFF: без safe-эндпоинта');
    assert.strictEqual(persistCalls.length, 1, 'D2/OFF: empty-write');
  }

  // ── D2: confirm=false → ничего не удаляем ───────────────────────────────
  {
    const { ctx, calls } = makeCtx({
      configItems: [{ key: 'TAVILY_API_KEY', title: 'T', per_chat: false }],
      persistItems: async function () { return { state: 'saved' }; },
    });
    const realConfirm = global.window.confirm;
    global.window.confirm = function () { return false; };
    const ok = await methods.deleteKeyItem.call(ctx, 'TAVILY_API_KEY');
    global.window.confirm = realConfirm;
    assert.strictEqual(ok, false, 'D2: отмена confirm → false');
    assert.strictEqual(calls.length, 0, 'D2: отмена → без запросов');
  }

  // ── §50: сохранение несекретных не трогает секрет ───────────────────────
  {
    const ctx = {
      canEditConfig() { return true; },
      configSnapshot: { 'keys.old': 'x' },
      configItems: [
        { key: 'keys.old', category: 'keys', secret: true,
          value: { configured: true, last4: 'OLD' } },
        { key: 'limits.a', category: 'limits', value: 5 },
      ],
      keyDrafts: {},
      _serializeValue: methods._serializeValue,
    };
    assert.strictEqual(computed.dirtyKeyItems.call(ctx).length, 0,
      'не тронутый секрет не попадает в dirtyKeyItems');
    ctx.keyDrafts['limits.a'] = 9;                 // несекретное
    assert.strictEqual(computed.dirtyKeyItems.call(ctx).length, 0,
      'несекретное изменение не делает секрет dirty');
  }

  // ── D4: компонент secret-field + x-template + разметка ──────────────────
  {
    assert.ok(APP_JS.indexOf("component('secret-field'") >= 0,
      'D4: компонент secret-field зарегистрирован');
    const comp = global.__components && global.__components['secret-field'];
    assert.ok(comp, 'D4: компонент доступен');
    assert.strictEqual(comp.template, '#secret-field-tpl',
      'D4: template — x-template');
    assert.ok(comp.props.configured && comp.props.last4 && comp.props.draft,
      'D4: props configured/last4/draft');
    assert.ok(comp.props.scope, 'D4: prop scope (BYOK chat)');
    assert.ok(INDEX.indexOf('id="secret-field-tpl"') >= 0,
      'D4: x-template #secret-field-tpl в index.html');
    assert.ok(INDEX.indexOf('class="secret-field__mask"') >= 0,
      'D4: display-индикатор маски в шаблоне');
    assert.strictEqual(
      (INDEX.match(/v-model="keyDrafts\[item\.key\]"/g) || []).length, 0,
      'D4: прямых v-model keyDrafts в index.html нет');
    assert.ok(INDEX.indexOf('@delete="deleteKeyItem(item)"') >= 0,
      'D4: «Удалить» привязано к deleteKeyItem');
    assert.ok(INDEX.indexOf('scope="chat"') >= 0,
      'D4: BYOK использует scope="chat"');
  }

  // ── D3: byokSecret из keyStatusOwn ──────────────────────────────────────
  {
    assert.strictEqual(typeof computed.byokSecret, 'function',
      'D3: byokSecret — computed');
    const on = computed.byokSecret.call({
      keyStatusOwn: { own: { 'keys.llm_api_key': { last4: 'WXYZ' } } },
    });
    assert.strictEqual(on.configured, true, 'D3: BYOK configured');
    assert.strictEqual(on.last4, 'WXYZ', 'D3: BYOK last4');
    const off = computed.byokSecret.call({ keyStatusOwn: null });
    assert.strictEqual(off.configured, false, 'D3: BYOK не настроен');
  }

  // ── R17: нет записи маски в keyDrafts в коде ────────────────────────────
  {
    assert.strictEqual(
      /keyDrafts\[[^\]]+\]\s*=\s*SECRET_MASK/.test(APP_JS), false,
      'R17/D1: SECRET_MASK не присваивается в keyDrafts');
    assert.strictEqual(
      /value\s*:\s*SECRET_MASK/.test(APP_JS), false,
      'R17: SECRET_MASK не уходит в значение/тело');
    assert.ok(/hasSecretMask\(drafts\[it\.key\]\)/.test(APP_JS),
      'R31: guard dirtyKeyItems сохранён');
    assert.ok(/hasSecretMask\(draft\)/.test(APP_JS),
      'R31: guard saveBlock сохранён');
  }

  console.log('F9-SECRET-OK');
  process.exit(0);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
