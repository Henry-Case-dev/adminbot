'use strict';
/* F11 round1024 (byok-image-key-round1024, ADR-1024-12) — безопасное
 * сохранение ГЛОБАЛЬНОГО ключа изображений.
 *
 * Покрытие:
 *   - saveBlock для `keys.image_api_key` отправляет PUT на
 *     `/api/config/keys/own` (`global:true`, scope:'global'), и НИКОГДА не
 *     кладёт секрет в общий POST /api/config;
 *   - маска/композит `маска+ввод` → 0 запросов (R31 guard сохранён);
 *   - GET-режим (`models.image_get_mode`): поле disabled (blockDependsOn),
 *     черновик ключа очищается, ключ не уходит в тело и не удаляется из БД
 *     (нет DELETE);
 *   - выключение GET-режима возвращает поле к значению из БД (маской);
 *   - поле-ключ помечено `globalSecret:true` (бейдж «Ключ установлен»).
 *
 * Запуск: node tests/js/round1024_image_key_test.js → IMAGE-KEY-OK
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
const methods = captured.methods;
assert(methods && methods.saveBlock, 'methods.saveBlock не найден');
assert(typeof methods.saveProviderSecret === 'function',
  'methods.saveProviderSecret не найден');
assert(typeof methods.setBlockBool === 'function',
  'methods.setBlockBool не найден');
const SECRET_MASK = data.secretMask;
assert.strictEqual(typeof SECRET_MASK, 'string', 'data.secretMask не найден');

// ── 0) Поле image-ключа помечено глобальным секретом (F11 D4) ─────────────
const imageBlock = data.providerBlocks.filter((b) => b.id === 'image_generation')[0];
assert(imageBlock, 'провайдер-блок image_generation не найден');
const keyField = imageBlock.fields.filter((f) => f.key === 'keys.image_api_key')[0];
assert(keyField, 'поле keys.image_api_key не найдено');
assert.strictEqual(keyField.globalSecret, true,
  'F11: image-ключ — globalSecret (бейдж «Ключ установлен»)');
assert.strictEqual(keyField.dependsOn, 'models.image_get_mode',
  'F11: ключ зависит от GET-режима');

// ── Общий контекст блока ──────────────────────────────────────────────────
function imageConfigItems() {
  return [
    { key: 'models.image_base_url', type: 'str', per_chat: false },
    { key: 'models.image_get_mode', type: 'bool', per_chat: false, value: false },
    { key: 'keys.image_api_key', type: 'str', secret: true, category: 'keys',
      per_chat: false, value: { configured: true, last4: 'abcd' } },
  ];
}
function makeBlockCtx(drafts, opts) {
  opts = opts || {};
  const calls = [];
  const ctx = {
    calls: calls,
    blockSaving: {},
    blockDrafts: drafts,
    configItems: imageConfigItems(),
    configChatUpdatedAt: 42,
    toasts: [],
    toast(m) { this.toasts.push(m); },
    loadConfig() {},
    _preserveScroll(fn) { return fn && fn.call(this); },
    blockFieldValue: methods.blockFieldValue,
    blockDependsOn: methods.blockDependsOn,
    saveProviderSecret: methods.saveProviderSecret,
    activeChatId: opts.activeChatId != null ? opts.activeChatId : null,
    uiFlag(name) {
      if (opts.uiFlags && Object.prototype.hasOwnProperty.call(opts.uiFlags, name)) {
        return !!opts.uiFlags[name];
      }
      return true;
    },
    async api(url, opts2) { calls.push({ url: url, opts: opts2 || {} }); return {}; },
  };
  return ctx;
}

// ── 1) Новый image-ключ → PUT /api/config/keys/own (global), НЕ /api/config ─
(async function run() {
  {
    const ctx = makeBlockCtx({
      'models.image_base_url': 'https://img.example/v1',
      'keys.image_api_key': 'sk-image-REAL-VALUE',
    });
    await methods.saveBlock.call(ctx, imageBlock);

    const keyCalls = ctx.calls.filter((c) => c.url === '/api/config/keys/own');
    assert.strictEqual(keyCalls.length, 1,
      'F11: image-ключ → ровно один PUT на safe-эндпоинт');
    const kc = keyCalls[0];
    assert.strictEqual(kc.opts.method, 'PUT', 'F11: safe-эндпоинт — PUT');
    assert.strictEqual(kc.opts.global, true,
      'F11: global:true (без X-Chat-Id)');
    const kbody = JSON.parse(kc.opts.body);
    assert.deepStrictEqual(kbody, {
      key_name: 'keys.image_api_key', value: 'sk-image-REAL-VALUE',
      scope: 'global',
    }, 'F11: тело safe-запроса {key_name,value,scope:global}');

    // секрет НЕ попал ни в один общий POST /api/config.
    const configCalls = ctx.calls.filter((c) => c.url === '/api/config');
    configCalls.forEach((c) => {
      assert.strictEqual(c.opts.body.indexOf('keys.image_api_key'), -1,
        'F11: keys.image_api_key НЕ в общем POST');
      assert.strictEqual(c.opts.body.indexOf('sk-image-REAL-VALUE'), -1,
        'F11: raw-значение НЕ в общем POST');
    });
    // непустой общий POST всё же ушёл (base_url — глобальный не-секрет).
    assert.ok(configCalls.length >= 1, 'F11: не-секретные поля сохраняются');
    assert.strictEqual(ctx.calls.length, 2,
      'F11: ровно 2 запроса — safe-ключ + общий конфиг');
  }

  // ── 2) Маска/композит → 0 запросов (R31 guard) ──────────────────────────
  for (const draft of [SECRET_MASK, SECRET_MASK + 'X']) {
    const ctx = makeBlockCtx({ 'keys.image_api_key': draft });
    await methods.saveBlock.call(ctx, imageBlock);
    assert.strictEqual(ctx.calls.length, 0,
      'F11/R31: маска [' + draft.replace(SECRET_MASK, '<MASK>') + '] → 0 запросов');
  }

  // ── 3) GET-режим: disable + очистка черновика (UI-only, без DELETE) ──────
  {
    const block = { id: 'image_generation', fields: imageBlock.fields };
    const ctx = makeBlockCtx({ 'keys.image_api_key': 'sk-image-DRAFT' });
    // Включаем GET-режим.
    methods.setBlockBool.call(ctx, block,
      { key: 'models.image_get_mode' }, true);
    assert.strictEqual(ctx.blockDrafts['models.image_get_mode'], true,
      'F11: GET-режим включён в черновике');
    assert.strictEqual(ctx.blockDrafts['keys.image_api_key'], '',
      'F11: черновик ключа очищен при включении GET-режима');
    // Поле заблокировано (blockDependsOn → true).
    const ctx2 = {
      blockDrafts: ctx.blockDrafts,
      configItems: ctx.configItems,
    };
    assert.strictEqual(methods.blockDependsOn.call(ctx2, keyField), true,
      'F11: поле ключа disabled в GET-режиме');
    assert.strictEqual(
      methods.blockFieldValue.call(ctx2, keyField), '',
      'F11: очищенный черновик → пустое поле');
    // Очистка — только UI: setBlockBool НЕ дёргает API (в т.ч. DELETE).
    assert.strictEqual(ctx.calls.length, 0,
      'F11: очистка UI-only (0 запросов, ключ в БД не удаляется)');

    // Сохранение в GET-режиме: ключ не уходит никуда.
    const saveCtx = makeBlockCtx({
      'models.image_get_mode': true,
      'keys.image_api_key': '',
    });
    await methods.saveBlock.call(saveCtx, imageBlock);
    assert.strictEqual(
      saveCtx.calls.filter((c) => c.url === '/api/config/keys/own').length, 0,
      'F11: в GET-режиме ключ на safe-эндпоинт не отправляется');
    saveCtx.calls.forEach((c) => {
      assert.strictEqual(c.opts.body.indexOf('keys.image_api_key'), -1,
        'F11: в GET-режиме ключ не в теле запроса');
    });
  }

  // ── 4) Выключение GET-режима → снова маска из БД ────────────────────────
  {
    const block = { id: 'image_generation', fields: imageBlock.fields };
    const ctx = makeBlockCtx({ 'models.image_get_mode': true,
                               'keys.image_api_key': '' });
    methods.setBlockBool.call(ctx, block,
      { key: 'models.image_get_mode' }, false);
    assert.strictEqual(ctx.blockDrafts['models.image_get_mode'], false,
      'F11: GET-режим выключен');
    assert.ok(!Object.prototype.hasOwnProperty.call(
      ctx.blockDrafts, 'keys.image_api_key'),
      'F11: черновик ключа снят при выключении GET-режима');
    assert.strictEqual(
      methods.blockFieldConfigured.call(ctx, keyField), true,
      'F11: ключ в БД виден как configured');
    assert.strictEqual(
      methods.blockFieldValue.call(ctx, keyField), SECRET_MASK,
      'F11: поле снова показывает заглушку из БД');
  }

  // ── 5) saveKeyItem (карточка-модалка): image-ключ → safe-эндпоинт ────────
  {
    const calls = [];
    const ctx = {
      keyDrafts: { 'keys.image_api_key': 'sk-modal-image' },
      saving: new Set(),
      configChatUpdatedAt: 7,
      toasts: [],
      toast(m) { this.toasts.push(m); },
      loadConfig() {},
      _preserveScroll(fn) { return fn && fn.call(this); },
      saveProviderSecret: methods.saveProviderSecret,
      saveImageKeyItem: methods.saveImageKeyItem,
      async api(url, opts) { calls.push({ url: url, opts: opts || {} }); return {}; },
    };
    const ok = await methods.saveKeyItem.call(ctx,
      { key: 'keys.image_api_key', title: 'Ключ', per_chat: false });
    assert.strictEqual(ok, true, 'F11: saveKeyItem image → успех');
    assert.strictEqual(calls.length, 1,
      'F11: saveKeyItem image → ровно 1 запрос');
    assert.strictEqual(calls[0].url, '/api/config/keys/own',
      'F11: saveKeyItem image → safe-эндпоинт');
    assert.strictEqual(JSON.parse(calls[0].opts.body).scope, 'global',
      'F11: saveKeyItem image → scope global');
    assert.strictEqual(ctx.keyDrafts['keys.image_api_key'], '',
      'F11: черновик очищен');
  }

  // ── 6) Kill-switch OFF → прежняя (сбойная) маршрутизация секрета ────────
  {
    const ctx = makeBlockCtx({ 'keys.image_api_key': 'sk-off-flag' },
      { uiFlags: { BYOK_IMAGE_KEY_ENABLED: false } });
    await methods.saveBlock.call(ctx, imageBlock);
    assert.strictEqual(
      ctx.calls.filter((c) => c.url === '/api/config/keys/own').length, 0,
      'F11 OFF: safe-эндпоинт не вызывается');
    const cfg = ctx.calls.filter((c) => c.url === '/api/config');
    assert.strictEqual(cfg.length, 1,
      'F11 OFF: прежний POST /api/config');
    assert.ok(cfg[0].opts.body.indexOf('keys.image_api_key') >= 0,
      'F11 OFF: прежняя маршрутизация секрета');
  }

  // ── 7) Контракт saveProviderSecret: scope:'chat' → per-chat BYOK ────────
  {
    const calls = [];
    const ctx = {
      activeChatId: -100500,
      uiFlag() { return true; },
      async api(url, opts) { calls.push({ url: url, opts: opts || {} }); return {}; },
    };
    await methods.saveProviderSecret.call(ctx, 'keys.llm_api_key', 'llm-secret',
      { scope: 'chat' });
    assert.strictEqual(calls.length, 1, 'llm chat → 1 запрос');
    assert.strictEqual(calls[0].url, '/api/config/keys/own',
      'llm chat → BYOK-эндпоинт');
    assert.strictEqual(calls[0].opts.method, 'PUT', 'llm chat → PUT');
    assert.notStrictEqual(calls[0].opts.global, true,
      'llm chat → с X-Chat-Id (не global)');
    assert.strictEqual(JSON.parse(calls[0].opts.body).scope, 'chat',
      'llm chat → scope:chat');
  }

  // ── 8) Паритет прав UI↔бэкенд для globalSecret (Finding H1/M1) ──────────
  // `isGlobalAdminEffective` — computed (ЗНАЧЕНИЕ), как в рантайме; раньше
  // тест подменял его МЕТОДОМ и из-за этого не ловил TypeError.
  {
    function editCtx(permissions, effective, legacy) {
      return {
        permissions: permissions,
        configItems: imageConfigItems(),
        isGlobalAdminEffective: effective,
        isGlobalAdmin: (legacy === undefined ? effective : legacy),
        isDmCtx() { return false; },
      };
    }
    // Все 4 комбинации wildcard × effective — без исключений.
    assert.strictEqual(
      methods.canEditConfig.call(editCtx({ sections: ['keys'] }, false),
        'keys.image_api_key'), false,
      'F11: роль с секцией keys НЕ правит глобальный image-ключ');
    assert.strictEqual(
      methods.canEditConfig.call(editCtx({ sections: ['keys'] }, true),
        'keys.image_api_key'), true,
      'F11: эффективный global admin (custom role_type) правит image-ключ');
    assert.strictEqual(
      methods.canEditConfig.call(editCtx({ wildcard: true }, false),
        'keys.image_api_key'), true,
      'F11: wildcard правит image-ключ (ранний return)');
    assert.strictEqual(
      methods.canEditConfig.call(editCtx({ wildcard: true }, true),
        'keys.image_api_key'), true,
      'F11: wildcard + effective true');
    // Регресс H1: роль `admin` без wildcard (effective=true, wildcard=false)
    // раньше бросала `TypeError: this.isGlobalAdmin is not a function`.
    assert.doesNotThrow(() => {
      const r = methods.canEditConfig.call(
        editCtx({ sections: ['keys'] }, true, true), 'keys.image_api_key');
      assert.strictEqual(r, true, 'admin без wildcard → правит');
    }, 'F11: computed как значение — без TypeError в рендере');
  }

  // ── 9) isGlobalAdminEffective — источник истины с сервера ──────────────
  {
    const computed = captured.computed;
    assert(computed && computed.isGlobalAdminEffective,
      'computed.isGlobalAdminEffective не найден');
    const eff = computed.isGlobalAdminEffective;
    // Сервер отдал эффективный флаг — он приоритетнее legacy-эвристики.
    assert.strictEqual(eff.call({
      me: { role_name: 'admin', is_global_admin: false },
      isGlobalAdmin: true,
    }), false, 'M1: серверный false приоритетнее role_name=admin');
    assert.strictEqual(eff.call({
      me: { role_name: 'ga_custom', is_global_admin: true },
      isGlobalAdmin: false,
    }), true, 'M1: custom role_type=global_admin → эффективный true');
    // Старый сервер (нет поля) → legacy-фолбэк.
    assert.strictEqual(eff.call({
      me: { role_name: 'admin', permissions: {} },
      isGlobalAdmin: true,
    }), true, 'M1: без поля — fallback на legacy isGlobalAdmin');
  }

  console.log('IMAGE-KEY-OK');
})().catch((e) => {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
