'use strict';
/* UPD3 (T-1939) — поведенческие тесты доработки UI мини-аппа.
 *
 * Покрытие:
 *   * sentinel маски секретов SECRET_MASK / isSecretMask;
 *   * _seedSecretMasks: configured → маска, null/{configured:false} → пусто;
 *   * blockFieldValue: секрет {configured:true} → маска;
 *   * GUARD R31: маска НЕ уходит в POST (saveKeyItem / saveBlock → 0 запросов);
 *   * dirtyKeyItems/stickyDirtyCount считают маску не-изменением;
 *   * cancelModalEdits очищает черновики (F9/D1: маска — не значение);
 *   * grid-маркеры «ИИ» (prov-grid, без max-w-3xl) + снимок навигации.
 *
 * Запуск: node tests/js/round1020_ui_rework_test.js   (печатает JS-UNIT-OK)
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

const SECRET_MASK = '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022';

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
  value: { clipboard: { writeText: async function () { throw new Error('no'); } } },
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
const methods = captured.methods;
const computed = captured.computed;
const data = captured.data();

const INDEX = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
const CSS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'static', 'app.css'), 'utf8');

function makeSaveCtx(configItems, keyDrafts) {
  const calls = [];
  const ctx = {
    configItems: configItems || [],
    keyDrafts: keyDrafts || {},
    blockDrafts: {},
    saving: new Set(),
    configChatUpdatedAt: 7,
    toasts: [],
    toast(m, k) { this.toasts.push([m, k]); },
    _preserveScroll(fn) { return fn && fn.call(this); },
    loadConfig() {},
    async api(url, opts) { calls.push({ url, opts }); return {}; },
  };
  return { ctx, calls };
}

(async function main() {
  // ── T-1903: снимок навигации (меню НЕ изменено) ────────────────────────
  {
    const expectedTabs = [
      'llm_providers', 'prompts',
      'mod_summary', 'mod_direct', 'mod_factcheck', 'mod_search',
      'mod_transcribe', 'mod_video_summary', 'mod_media_download', 'mod_web',
      'mod_checkup', 'mod_sleep', 'mod_nostalgia', 'mod_budgets',
      'mod_images',
      'modules', 'memory_rag', 'smart_cache', 'people_names', 'relations',
      'permsoc', 'access', 'chat_lore', 'status', 'info', 'oversight',
    ];
    assert.deepStrictEqual(data.tabs.map((t) => t.id), expectedTabs,
      'меню: состав/порядок вкладок не изменён');
    assert.strictEqual(data.modules.length, 13, 'меню: 13 карточек модулей');
  }

  // ── sentinel: SECRET_MASK / isSecretMask ───────────────────────────────
  {
    assert.strictEqual(typeof methods.isSecretMask, 'function',
      'isSecretMask — метод');
    assert.strictEqual(methods.isSecretMask(SECRET_MASK), true);
    assert.strictEqual(methods.isSecretMask('real-secret'), false);
    assert.strictEqual(methods.isSecretMask(''), false);
    assert.strictEqual(methods.isSecretMask(null), false);
  }

  // ── F9/D1: _seedSecretMasks больше НЕ засеивает маску в keyDrafts ──────
  {
    const ctx = {
      isKeyConfigured: methods.isKeyConfigured,
      keyDrafts: { legacy: SECRET_MASK + 'typed' },
      configItems: [
        { key: 'CHECKUP_BETTERSTACK_SQL_PASSWORD', category: 'keys',
          secret: true, value: { configured: true, last4: 'FAKE' } },
        { key: 'CHECKUP_BETTERSTACK_SQL_USER', category: 'keys',
          secret: true, value: { configured: false, last4: null } },
        { key: 'keys.empty', category: 'keys', secret: true, value: null },
        { key: 'models.llm_base_url', value: 'https://real/v1' },
        { key: 'keys.keep_draft', category: 'keys', secret: true,
          value: { configured: true, last4: 'KEEP' } },
      ],
    };
    ctx.keyDrafts['keys.keep_draft'] = 'user-typed';
    methods._seedSecretMasks.call(ctx);
    assert.strictEqual(
      ctx.keyDrafts['CHECKUP_BETTERSTACK_SQL_PASSWORD'], undefined,
      'F9/D1: configured-секрет НЕ засеивается маской (поле пустое)');
    assert.strictEqual(ctx.keyDrafts['CHECKUP_BETTERSTACK_SQL_USER'], undefined,
      'configured:false → поле не засеяно (пусто)');
    assert.strictEqual(ctx.keyDrafts['keys.empty'], undefined,
      'null → поле пустое');
    assert.strictEqual(ctx.keyDrafts['models.llm_base_url'], undefined,
      'не-секрет не трогаем (two-way item.value)');
    assert.strictEqual(ctx.keyDrafts['keys.keep_draft'], 'user-typed',
      'реальный черновик не перетирается');
    assert.strictEqual(ctx.keyDrafts.legacy, undefined,
      'F9/D1: legacy/композитная маска вычищена (в API не уйдёт)');
  }

  // ── F9/D1: blockFieldValue для секрета → '' (маска — display) ──────────
  {
    const ctx = {
      blockDrafts: {},
      configItems: [
        { key: 'keys.llm_api_key', type: 'str', secret: true,
          category: 'keys', value: { configured: true, last4: '1234' } },
        { key: 'keys.off', type: 'str', secret: true, category: 'keys',
          value: { configured: false, last4: null } },
        { key: 'models.empty', type: 'str', value: null },
        { key: 'models.llm_base_url', type: 'str', value: 'https://db/v1' },
      ],
    };
    assert.strictEqual(
      methods.blockFieldValue.call(ctx, { key: 'keys.llm_api_key', secret: true }),
      '', 'F9/D1: секрет configured → пустое поле (не маска)');
    assert.strictEqual(
      methods.blockFieldValue.call(ctx, { key: 'keys.off', secret: true }), '',
      'configured:false → пусто');
    assert.strictEqual(
      methods.blockFieldValue.call(ctx, { key: 'models.empty' }), '',
      'пусто только при реальном null');
    assert.strictEqual(
      methods.blockFieldValue.call(ctx, { key: 'models.llm_base_url' }),
      'https://db/v1', 'не-секрет → фактическое значение');
    // F9/D3: display-индикатор несёт маску/«Ключ установлен».
    assert.strictEqual(
      methods.secretDisplay.call(ctx, { key: 'keys.llm_api_key' }).maskText,
      '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022' + '1234',
      'F9/D3: secretDisplay → ••••••••last4');
    assert.strictEqual(
      methods.secretDisplay.call(ctx, { key: 'keys.off' }).maskText,
      'Не настроен', 'F9/D3: не настроен → «Не настроен»');
  }

  // ── R31 GUARD: маска НЕ уходит в POST (saveKeyItem) ────────────────────
  {
    const { ctx, calls } = makeSaveCtx(
      [{ key: 'CHECKUP_BETTERSTACK_SQL_PASSWORD', title: 'Пароль',
         category: 'keys', secret: true, per_chat: false }],
      { 'CHECKUP_BETTERSTACK_SQL_PASSWORD': SECRET_MASK });
    const ok = await methods.saveKeyItem.call(
      ctx, ctx.configItems[0]);
    assert.strictEqual(calls.length, 0,
      'R31: маска → 0 POST-запросов (реальный секрет не перезаписан)');
    assert.strictEqual(ok, false, 'R31: маска → no-op');
  }
  {
    const { ctx, calls } = makeSaveCtx(
      [{ key: 'keys.x', title: 'X', category: 'keys', secret: true,
         per_chat: false }],
      { 'keys.x': 'brand-new-key' });
    await methods.saveKeyItem.call(ctx, ctx.configItems[0]);
    assert.strictEqual(calls.length, 1, 'реальное значение → POST');
    const body = JSON.parse(calls[0].opts.body);
    assert.strictEqual(body.items[0].value, 'brand-new-key',
      'в POST уходит реальный ключ');
  }

  // ── R31 GUARD: маска не создаёт items в saveBlock ──────────────────────
  {
    const calls = [];
    const block = { id: 'direct_main', title: 'Прямые ответы', fields: [
      { key: 'keys.llm_api_key', role: 'api_key', secret: true }] };
    const ctx = {
      blockSaving: {}, blockDrafts: { 'keys.llm_api_key': SECRET_MASK },
      configItems: [{ key: 'keys.llm_api_key', type: 'str', secret: true,
        value: { configured: true, last4: '1234' } }],
      blockFieldValue: methods.blockFieldValue,
      toasts: [], toast(m) { this.toasts.push(m); },
      _preserveScroll(fn) { return fn && fn.call(this); },
      loadConfig() {},
      async api(url, opts) { calls.push(opts); return {}; },
    };
    await methods.saveBlock.call(ctx, block);
    assert.strictEqual(calls.length, 0,
      'R31: маска в blockDrafts → 0 POST («Нет изменений»)');
  }

  // ── R31 GUARD (iter UPD3, Critical-1): КОМПОЗИТ `маска + ввод` ─────────
  // Реальный «клик в конец маски → ввод» даёт `••••••••••••<ввод>`. Такой
  // композит НЕ должен уходить ни в POST /api/config, ни в /api/llm/test.
  {
    assert.strictEqual(typeof methods.hasSecretMask, 'function',
      'hasSecretMask — метод (композит распознаётся)');
    assert.strictEqual(methods.hasSecretMask(SECRET_MASK), true,
      'точная маска → true');
    assert.strictEqual(methods.hasSecretMask(SECRET_MASK + 'X'), true,
      'композит mask+X → true');
    assert.strictEqual(methods.hasSecretMask('X' + SECRET_MASK), true,
      'композит X+mask → true');
    assert.strictEqual(methods.hasSecretMask('real-secret'), false,
      'реальный секрет → false');
    assert.strictEqual(methods.hasSecretMask(''), false);
    assert.strictEqual(methods.hasSecretMask(null), false);
    assert.strictEqual(methods.hasSecretMask(undefined), false);
  }

  // Точная маска → 0 POST (не регрессировать) + композит mask+'X' → 0 POST.
  for (const draft of [SECRET_MASK, SECRET_MASK + 'X']) {
    const { ctx, calls } = makeSaveCtx(
      [{ key: 'keys.auth', title: 'Auth', category: 'keys', secret: true,
         per_chat: false }],
      { 'keys.auth': draft });
    const ok = await methods.saveKeyItem.call(ctx, ctx.configItems[0]);
    assert.strictEqual(calls.length, 0,
      'saveKeyItem [' + draft.replace(SECRET_MASK, '<MASK>') + '] → 0 POST');
    assert.strictEqual(ok, false, 'saveKeyItem [' +
      draft.replace(SECRET_MASK, '<MASK>') + '] → no-op');

    const blockCalls = [];
    const block = { id: 'direct_main', title: 'Прямые ответы', fields: [
      { key: 'keys.auth', role: 'api_key', secret: true }] };
    const bctx = {
      blockSaving: {}, blockDrafts: { 'keys.auth': draft },
      configItems: [{ key: 'keys.auth', type: 'str', secret: true,
        value: { configured: true, last4: 'FAKE' } }],
      blockFieldValue: methods.blockFieldValue,
      toasts: [], toast(m) { this.toasts.push(m); },
      _preserveScroll(fn) { return fn && fn.call(this); },
      loadConfig() {},
      async api(url, opts) { blockCalls.push(opts); return {}; },
    };
    await methods.saveBlock.call(bctx, block);
    assert.strictEqual(blockCalls.length, 0,
      'saveBlock [' + draft.replace(SECRET_MASK, '<MASK>') + '] → 0 POST');
  }

  // testBlock/testField: композит маски НЕ уходит в /api/llm/test.
  {
    const calls = [];
    const block = { id: 'prov1', fields: [
      { key: 'keys.llm_api_key', role: 'api_key', secret: true }] };
    const ctx = {
      blockTesting: {}, blockResults: {},
      blockDrafts: { 'keys.llm_api_key': SECRET_MASK + 'X' },
      configItems: [{ key: 'keys.llm_api_key', type: 'str', secret: true,
        value: { configured: true, last4: 'FAKE' } }],
      blockFieldValue: methods.blockFieldValue,
      toast() {},
      async api(url, opts) { calls.push({ url, opts }); return { ok: true }; },
    };
    await methods.testBlock.call(ctx, block);
    assert.strictEqual(calls.length, 1, 'testBlock: запрос к /api/llm/test');
    const body = JSON.parse(calls[0].opts.body);
    assert.strictEqual(body.api_key, '',
      'testBlock: композит маски НЕ уходит в api_key');
    assert.ok(body.api_key.indexOf(SECRET_MASK) < 0, 'testBlock: маски нет в теле');
  }
  {
    const calls = [];
    const f = { key: 'keys.llm_api_key', probeTarget: 'prov1' };
    const ctx = {
      blockTesting: {}, blockResults: {},
      blockDrafts: { 'keys.llm_api_key': SECRET_MASK + 'X' },
      configItems: [{ key: 'keys.llm_api_key', type: 'str', secret: true,
        value: { configured: true, last4: 'FAKE' } }],
      blockFieldValue: methods.blockFieldValue,
      toast() {},
      async api(url, opts) { calls.push({ url, opts }); return { ok: true }; },
    };
    await methods.testField.call(ctx, {}, f);
    const body = JSON.parse(calls[0].opts.body);
    assert.strictEqual(body.api_key, '',
      'testField: композит маски → api_key "" (не уходит)');
  }

  // dirtyKeyItems: композит маски — не изменение.
  {
    const ctx = {
      canEditConfig() { return true; },
      configSnapshot: {},
      configItems: [{ key: 'keys.x', category: 'keys', secret: true,
        value: { configured: true, last4: 'FAKE' } }],
      keyDrafts: { 'keys.x': SECRET_MASK + 'X' },
      _serializeValue: methods._serializeValue,
    };
    assert.strictEqual(computed.dirtyKeyItems.call(ctx).length, 0,
      'композит маски не считается изменением');
  }

  // F9/D4 (ранее Critical-2 G3.6 + L-1): секрет-поля вынесены в единый
  // компонент `secret-field` — старые условные @focus select/@mouseup в
  // index.html отсутствуют (пароль-инпут + reveal внутри компонента).
  {
    assert.strictEqual(
      (INDEX.match(/@focus="f\.secret && \$event\.target\.select\(\)"/g) || []).length,
      0, 'F9/D4: условных secret @focus select в index.html больше нет');
    assert.strictEqual(
      (INDEX.match(/@mouseup="f\.secret && \$event\.preventDefault\(\)"/g) || []).length,
      0, 'F9/D4: mouseup-гард переехал в компонент secret-field');
    assert.strictEqual(
      (INDEX.match(/@focus="\$event\.target\.select\(\)" @mouseup\.prevent/g) || []).length,
      0, 'L-1: безусловных @focus select + @mouseup.prevent быть не должно');
    assert.ok(INDEX.indexOf('id="secret-field-tpl"') >= 0,
      'F9/D4: шаблон secret-field на месте');
  }

  // M-1: sticky-панель прилипает к самому низу скролл-порта — у скролл-
  // контейнера НЕТ собственного padding-bottom (он сужал content-box и
  // «подвешивал» панель). Место над панелью резервирует спейсер в потоке.
  {
    const m = CSS.match(/\.scroll-area:has\(> \.sticky-save\)\s*\{([^}]*)\}/);
    assert.ok(m, 'M-1: нет правила .scroll-area:has(> .sticky-save)');
    assert.ok(/scroll-padding-bottom/.test(m[1]),
      'M-1: scroll-padding-bottom остаётся (фокус не уезжает под панель)');
    const pb = m[1].match(/(?:^|[;\s])padding-bottom\s*:\s*([^;]+)/);
    assert.ok(!pb || /^0(px)?$/.test(pb[1].trim()),
      'M-1: padding-bottom контейнера не резервирует место (допустим только 0)');
    assert.ok(/\.sticky-spacer\s*\{[^}]*height:\s*var\(--sticky-save-h\)/.test(CSS),
      'M-1: .sticky-spacer резервирует место над панелью');
    assert.ok(/class="sticky-spacer[^"]*"[^>]*><\/div>\s*<sticky-save/.test(INDEX),
      'M-1: спейсер стоит непосредственно перед <sticky-save> в скролл-ветке');
    const fb = CSS.match(/@supports not \(selector\(:has\(\*\)\)\)\s*\{([^}]*)\}/);
    assert.ok(fb, 'M-1: нет @supports-фолбэка (selector(:has(*)))');
    assert.ok(!/(?:^|[;\s{])padding-bottom\s*:/.test(fb[1]),
      'M-1/L-3: @supports-фолбэк не добавляет padding-bottom');
  }

  // L-2: композит маски — сообщение объясняет, ЧТО делать (значение НЕ
  // сохранено; «Уже сохранено» вводит в заблуждение).
  {
    const { ctx, calls } = makeSaveCtx(
      [{ key: 'keys.x', title: 'X', category: 'keys', secret: true,
         per_chat: false }],
      { 'keys.x': SECRET_MASK + 'typed' });
    const ok = await methods.saveKeyItem.call(ctx, ctx.configItems[0]);
    assert.strictEqual(calls.length, 0, 'L-2: композит маски → 0 POST');
    assert.strictEqual(ok, false, 'L-2: композит маски → no-op');
    assert.strictEqual(ctx.toasts.length, 1, 'L-2: ровно один тост');
    const msg = ctx.toasts[0][0];
    const kind = ctx.toasts[0][1];
    assert.strictEqual(kind, 'warn', 'L-2: тост уровня warn');
    assert.ok(msg.indexOf('Уже сохранено') < 0,
      'L-2: тост не должен утверждать «Уже сохранено»');
    assert.ok(/маск/i.test(msg),
      'L-2: сообщение объясняет, что в поле маска сохранённого секрета');
    assert.ok(/введ/i.test(msg),
      'L-2: сообщение подсказывает ввести значение заново');
  }

  // ── dirty: маска — не изменение (sticky не активна) ───────────────────
  {
    const ctx = {
      canEditConfig() { return true; },
      configSnapshot: {},
      configItems: [
        { key: 'keys.x', category: 'keys', secret: true,
          value: { configured: true, last4: 'FAKE' } },
      ],
      keyDrafts: { 'keys.x': SECRET_MASK },
      _serializeValue: methods._serializeValue,
    };
    assert.strictEqual(computed.dirtyKeyItems.call(ctx).length, 0,
      'маска не считается изменением');
    assert.strictEqual(computed.stickyDirtyCount.call(ctx), 0,
      'stickyDirtyCount = 0 при только маске');
    // реальный ввод → dirty
    ctx.keyDrafts['keys.x'] = 'new-real-key';
    assert.strictEqual(computed.dirtyKeyItems.call(ctx).length, 1,
      'реальный ключ → dirty');
  }

  // ── F9/D1: «Отмена» очищает черновики (маска — display, не значение) ────
  {
    const ctx = {
      configSnapshot: {},
      configItems: [
        { key: 'keys.x', category: 'keys', secret: true,
          value: { configured: true, last4: 'FAKE' } },
      ],
      keyDrafts: { 'keys.x': 'typed' },
      canEditConfig() { return true; },
      isKeyConfigured: methods.isKeyConfigured,
      _seedSecretMasks: methods._seedSecretMasks,
      _serializeValue: methods._serializeValue,
      toast() {},
    };
    methods.cancelModalEdits.call(ctx);
    assert.strictEqual(ctx.keyDrafts['keys.x'], undefined,
      'F9/D1: «Отмена» возвращает ПУСТОЕ поле (маска — индикатор, не значение)');
  }

  // ── grid/маска-маркеры разметки и кода ─────────────────────────────────
  {
    assert.ok(APP_JS.indexOf('_seedSecretMasks') >= 0, '_seedSecretMasks есть');
    assert.ok(APP_JS.indexOf('isSecretMask') >= 0, 'isSecretMask есть');
    assert.ok(APP_JS.indexOf('hasSecretMask') >= 0, 'hasSecretMask есть');
    const branch = INDEX.slice(
      INDEX.indexOf("activeTab === 'llm_providers'"),
      INDEX.indexOf("activeTab === 'llm_providers'") + 1200);
    assert.ok(branch.indexOf('prov-grid') >= 0,
      'ветка «ИИ» использует prov-grid');
    assert.ok(INDEX.indexOf('max-w-3xl') < 0, 'max-w-3xl снят с prov-block');
    // F9/D4: единый компонент `secret-field` вместо копий инпутов; шаблон
    // вынесен в x-template `#secret-field-tpl`, привязок keyDrafts в
    // index.html больше нет (они внутри компонента).
    assert.ok(APP_JS.indexOf("component('secret-field'") >= 0,
      'F9/D4: компонент secret-field зарегистрирован');
    assert.ok(INDEX.indexOf('id="secret-field-tpl"') >= 0,
      'F9/D4: x-template #secret-field-tpl есть');
    assert.ok(INDEX.indexOf('update:draft="keyDrafts[item.key] = $event"') >= 0,
      'F9/D4: generic-ключи через secret-field (update:draft)');
    assert.strictEqual(
      (INDEX.match(/v-model="keyDrafts\[item\.key\]"/g) || []).length, 0,
      'F9/D4: прямых v-model keyDrafts в index.html нет');
  }

  console.log('JS-UNIT-OK');
})().catch(function (e) {
  console.error(e && e.stack || e);
  process.exit(1);
});
