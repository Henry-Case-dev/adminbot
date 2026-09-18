'use strict';
/* F8 round1023 (ui-verbilizer-tabs-round1023, ADR-1023-8) — РЕАЛЬНЫЙ JS-тест
 * вкладки «Промпты»:
 *   - группировка элементов карточки по `stage` (Синтезатор/Вербализатор);
 *   - Tabs режимов Вербализатора (переключение + запись режима по умолчанию);
 *   - блок мониторинга анти-клише: force-refresh (POST), ручная правка (PUT),
 *     fail-open при недоступности F4-API.
 *
 * Запуск: node tests/js/round1023_verbilizer_tabs_test.js  → VERBILIZER-UNIT-OK
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
        const idx = _bodyChildren.indexOf(this);
        if (idx >= 0) _bodyChildren.splice(idx, 1);
      },
    };
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
const methods = captured.methods;
assert(methods, 'root.methods не найден');

// ── 1. stage-группировка ────────────────────────────────────────────────────
(function () {
  const grp = { items: [
    { key: 'a', stage: 'synthesizer' },
    { key: 'b', stage: 'verbalizer' },
    { key: 'c', stage: 'verbalizer' },
    { key: 'd' },
  ] };
  assert.strictEqual(methods.promptStageItems(grp, 'synthesizer').length, 1);
  assert.strictEqual(methods.promptStageItems(grp, 'verbalizer').length, 2);
  assert.strictEqual(methods.promptOtherItems(grp).length, 1);
  assert.strictEqual(methods.promptsHasSynthesizer(grp), true);
  assert.strictEqual(methods.promptsHasVerbalizer(grp), true);
  assert.strictEqual(methods.promptsHasSynthesizer({ items: [
    { key: 'x', stage: 'verbalizer' }] }), false);
  assert.strictEqual(methods.promptStageItems(null, 'verbalizer').length, 0);
})();

// ── 1b. promptSections: условные секции + basic/advanced split ──────────────
(function () {
  const itemAdvanced = function (it) { return !!it.advanced; };
  const ctx = { itemAdvanced: itemAdvanced,
                promptStageItems: methods.promptStageItems,
                promptOtherItems: methods.promptOtherItems };
  function call(grp) { return methods.promptSections.call(ctx, grp); }

  // Группа без staged-элементов (prompts_memory/prompts_checkup):
  // НЕТ ложной секции «Вербализатор» — только «Прочие промпты модуля».
  const only = call({ items: [
    { key: 'a' }, { key: 'b', advanced: true }, { key: 'c' }] });
  assert.deepStrictEqual(only.map(function (s) { return s.id; }), ['other']);
  assert.strictEqual(only[0].basic.length, 2);
  assert.strictEqual(only[0].advanced.length, 1);

  // Одностадийный модуль (search/youtube/web): verbalizer + пометка, без synth.
  const os = call({ items: [{ key: 'v', stage: 'verbalizer' }] });
  assert.deepStrictEqual(os.map(function (s) { return s.id; }), ['verbalizer']);
  assert(os[0].note && os[0].note.indexOf('одностадийный') >= 0);

  // Двухстадийный: synth + verbalizer + прочее; пометки об одностадийности нет.
  const two = call({ items: [
    { key: 's', stage: 'synthesizer' },
    { key: 'v', stage: 'verbalizer' }, { key: 'o' }] });
  assert.deepStrictEqual(two.map(function (s) { return s.id; }),
    ['synthesizer', 'verbalizer', 'other']);
  assert.strictEqual(two[1].note, '');
})();

// ── 2. Tabs режимов ─────────────────────────────────────────────────────────
(function () {
  const tabs = captured.computed.promptModeTabs.call({});
  assert.deepStrictEqual(tabs.map(function (t) { return t.id; }),
    ['casual', 'serious', 'deep_research']);

  // 2.1 Таб: смена режима сохраняется.
  const defaultItem = { key: 'prompts.verbilizer_default_mode', value: 'serious' };
  const saved = [];
  const ctx = {
    promptMode: 'serious',
    configItems: [defaultItem],
    canEditConfig: function () { return true; },
    saveConfigItem: function (it) { saved.push(it.value); },
    promptDefaultModeItem: methods.promptDefaultModeItem,
  };
  methods.selectPromptMode.call(ctx, 'casual');
  assert.strictEqual(ctx.promptMode, 'casual');
  assert.strictEqual(defaultItem.value, 'casual');
  assert.deepStrictEqual(saved, ['casual']);

  // 2.2 High-регресс: путь СЕЛЕКТА ($event.target.value). v-model уже
  // записал новое значение в item.value ДО @change — сохранение всё равно
  // должно произойти (раньше условие item.value !== mode было всегда false).
  const selItem = { key: 'prompts.verbilizer_default_mode', value: 'serious' };
  const savedSel = [];
  const ctxSel = {
    promptMode: 'serious',
    configItems: [selItem],
    canEditConfig: function () { return true; },
    saveConfigItem: function (it) { savedSel.push(it.value); },
    promptDefaultModeItem: methods.promptDefaultModeItem,
  };
  ctxSel.promptDefaultModeItem().value = 'deep_research';   // v-model
  methods.selectPromptMode.call(ctxSel, 'deep_research');    // @change
  assert.strictEqual(ctxSel.promptMode, 'deep_research');
  assert.deepStrictEqual(savedSel, ['deep_research']);

  // 2.3 Повторный выбор того же режима — без повторного сохранения.
  methods.selectPromptMode.call(ctxSel, 'deep_research');
  assert.deepStrictEqual(savedSel, ['deep_research']);

  // 2.4 sync из конфига.
  const ctx2 = { promptMode: 'serious', configItems: [defaultItem],
                 promptModeTabs: tabs,
                 promptDefaultModeItem: methods.promptDefaultModeItem };
  methods._syncPromptModeFromConfig.call(ctx2);
  assert.strictEqual(ctx2.promptMode, 'casual');

  // 2.5 Санитайз: неизвестное значение → 'serious' (таб подсвечен).
  const ctxBad = { promptMode: 'serious', promptModeTabs: tabs,
    configItems: [{ key: 'prompts.verbilizer_default_mode', value: 'bogus' }],
    promptDefaultModeItem: methods.promptDefaultModeItem };
  methods._syncPromptModeFromConfig.call(ctxBad);
  assert.strictEqual(ctxBad.promptMode, 'serious');
})();

// ── 3. Блок анти-клише: load (fail-open) / force / PUT ──────────────────────
(async function () {
  // 3.1 loadCliche — успех.
  const calls = [];
  const api = async function (url, opts) {
    calls.push({ url: url, method: (opts && opts.method) || 'GET' });
    if (url === '/api/anticliche' && (!opts || opts.method !== 'PUT')) {
      return { patterns: [{ code: 'dyn_a', phrase: 'фраза' }], count: 1,
               max_patterns: 20, last_status: 'ok',
               fetched_at: '2026-09-19T00:00:00+00:00' };
    }
    if (url === '/api/anticliche/refresh') return { status: 'ok', count: 2 };
    if (url === '/api/anticliche' && opts.method === 'PUT') {
      return { count: 1, version: 3 };
    }
    throw new Error('unexpected ' + url);
  };
  const ctx = {
    isGlobalAdmin: true, activeTab: 'prompts',
    clicheAvailable: false, clicheLoading: false, clicheBusy: false,
    clicheMeta: null, clicheEditing: false, clicheDraft: '',
    api: api, toast: function () {},
    loadCliche: methods.loadCliche,
  };
  await methods.loadCliche.call(ctx);
  assert.strictEqual(ctx.clicheAvailable, true);
  assert.strictEqual(ctx.clicheMeta.count, 1);
  assert.strictEqual(ctx.clicheLoading, false);

  // 3.2 forceRefresh → POST + перечитать.
  await methods.forceRefreshCliche.call(ctx);
  const refreshCall = calls.find(function (c) {
    return c.url === '/api/anticliche/refresh';
  });
  assert(refreshCall && refreshCall.method === 'POST', 'нужен POST refresh');

  // 3.3 ручное редактирование → черновик из фраз + PUT.
  methods.toggleClicheEdit.call(ctx);
  assert.strictEqual(ctx.clicheEditing, true);
  assert.strictEqual(ctx.clicheDraft, 'фраза');
  ctx.clicheDraft = 'новая фраза\n\n  вторая  ';
  await methods.saveCliche.call(ctx);
  const putCall = calls.find(function (c) { return c.method === 'PUT'; });
  assert(putCall, 'нужен PUT /api/anticliche');
  assert.strictEqual(ctx.clicheEditing, false);

  // 3.4 fail-open: API падает → блок скрыт, вкладка работает.
  const ctxFail = {
    isGlobalAdmin: true, activeTab: 'prompts',
    clicheAvailable: true, clicheLoading: false,
    clicheMeta: { patterns: [] },
    api: async function () { throw new Error('boom'); },
  };
  await methods.loadCliche.call(ctxFail);
  assert.strictEqual(ctxFail.clicheAvailable, false);
  assert.strictEqual(ctxFail.clicheMeta, null);

  // 3.5 не-глобальный админ → блок недоступен (без запроса).
  const ctxNoAdmin = { isGlobalAdmin: false, clicheAvailable: true,
                       api: async function () { throw new Error('no call'); } };
  await methods.loadCliche.call(ctxNoAdmin);
  assert.strictEqual(ctxNoAdmin.clicheAvailable, false);

  // 3.6 статус/дата.
  const st = { clicheMeta: { last_status: 'parse_error' } };
  assert.strictEqual(methods.clicheStatusLabel.call(st), 'ошибка разбора');
  assert.strictEqual(methods.formatClicheDate.call({}, null), '—');

  console.log('VERBILIZER-UNIT-OK');
})().catch(function (e) {
  console.error(e && e.stack || e);
  process.exit(1);
});
