'use strict';
/* D1/D2 regression (tma-relume-redesign) — РЕАЛЬНЫЙ JS-тест (не grep).
 *
 * Загружает web/app.js в stubbed-окружении (Vue.createApp перехватывает
 * options), затем проверяет:
 *   D1 — hub-роут #/ai НЕ гейтится одним representative-tab: доступен,
 *        если видна хотя бы одна карточка; редиректит только если ни одной;
 *        не-hub роуты по-прежнему гейтятся своим tab.
 *   D2 — scopeEpoch реально отбрасывает устаревший in-flight ответ.
 *
 * Запуск: node tests/js/routing_test.js
 */
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
global.document = { addEventListener() {}, getElementById() { return null; } };
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

function makeCtx(visible) {
  return {
    route: '#/__none__',
    me: { role_name: 'user' },
    activeTab: 'status',
    activeMenu: 'home',
    tabs: captured.data().tabs,
    toast() {},
    syncBackButton() {},
    canViewTab(id) { return visible.indexOf(id) >= 0; },
    setTab(id) { this.activeTab = id; },
  };
}

// ── D1 ─────────────────────────────────────────────────────────────────────
let ctx = makeCtx(['status', 'prompts']);
methods.applyRoute.call(ctx, '#/ai');
assert.strictEqual(ctx.route, '#/ai',
  'D1: hub #/ai должен открываться при частичных правах (только prompts)');

ctx = makeCtx(['status']);
methods.applyRoute.call(ctx, '#/ai');
assert.strictEqual(ctx.route, '#/',
  'D1: hub #/ai без видимых карточек → редирект на #/');

ctx = makeCtx(['status', 'modules']);
methods.applyRoute.call(ctx, '#/modules');
assert.strictEqual(ctx.route, '#/modules',
  'A2: список «Модули» — не hub, открывается по своему tab');

ctx = makeCtx(['status', 'prompts']);
methods.applyRoute.call(ctx, '#/ai/llm');
assert.strictEqual(ctx.route, '#/',
  'D1: не-hub роут запрещённой вкладки по-прежнему редиректит');

ctx = makeCtx(['status', 'prompts']);
methods.applyRoute.call(ctx, '#/ai/prompts');
assert.strictEqual(ctx.route, '#/ai/prompts',
  'D1: не-hub роут разрешённой вкладки открывается');

// ── D2 ─────────────────────────────────────────────────────────────────────
assert.strictEqual(methods._scopeGuard.call({ scopeEpoch: 7 }, 7), true);
assert.strictEqual(methods._scopeGuard.call({ scopeEpoch: 8 }, 7), false);

// ── R10.5-1: late-ready BackButton (initBackButton идемпотентен) ──────────
(function () {
  const bb = {
    isVisible: false, bindCount: 0, showCount: 0, hideCount: 0,
    onClick(cb) { this._cb = cb; this.bindCount += 1; },
    show() { this.showCount += 1; this.isVisible = true; },
    hide() { this.hideCount += 1; this.isVisible = false; },
  };
  const lateCtx = {
    route: '#/ai/prompts',   // depth 1 → нативный ← нужен
    backNative: false,
    syncBackButton() { return methods.syncBackButton.call(this); },
  };
  global.window.Telegram = null;               // контекста/BackButton ещё нет
  methods.initBackButton.call(lateCtx);
  assert.strictEqual(lateCtx.backNative, false,
    'R10.5-1: на BOOT BackButton отсутствует');
  global.window.Telegram = { WebApp: { BackButton: bb } };   // поздний ready
  methods.initBackButton.call(lateCtx);
  assert.strictEqual(lateCtx.backNative, true,
    'R10.5-1: поздний BackButton обнаружен');
  assert.strictEqual(bb.bindCount, 1,
    'R10.5-1: onClick привязан ровно один раз');
  assert.strictEqual(bb.showCount, 1,
    'R10.5-1: syncBackButton показал ← при depth>0');
  methods.initBackButton.call(lateCtx);        // повторный ready — без дублей
  assert.strictEqual(bb.bindCount, 1,
    'R10.5-1: повторный initBackButton не дублирует onClick');
  assert.strictEqual(bb.showCount, 1,
    'R10.5-1: повторный init не вызывает show() при уже видимой кнопке');
})();

// ── R10.5-2: DM read-only для per_chat=False (models.*) ───────────────────
(function () {
  const dm = {
    permissions: {},
    configItems: [
      { key: 'models.groq_base_url', per_chat: false },
      { key: 'limits.chat_cooldown_seconds', per_chat: true },
    ],
    isDmCtx: () => true,
  };
  assert.strictEqual(methods.canEditConfig.call(dm, 'models.groq_base_url'),
    false, 'R10.5-2: models.groq_base_url read-only в DM');
  assert.strictEqual(methods.canEditConfig.call(dm, 'models.groq_transcribe_model'),
    false, 'R10.5-2: models.groq_transcribe_model read-only в DM');
  assert.strictEqual(methods.canEditConfig.call(dm, 'models.openrouter_base_url'),
    false, 'R10.5-2: models.openrouter_base_url read-only в DM');
  assert.strictEqual(methods.canEditConfig.call(dm, 'limits.chat_cooldown_seconds'),
    true, 'R10.5-2: per_chat-ключ остаётся редактируемым в DM');
})();

// ── BLOCKER-1: navItems = ровно 6 пунктов, включая modules (wildcard) ─────
(function () {
  const ctx = { route: '#/', canViewTab() { return true; } };
  const nav = captured.computed.navItems.call(ctx);
  const ids = nav.map((n) => n.id);
  assert.deepStrictEqual(
    ids, ['status', 'how', 'modules', 'ai', 'permsoc', 'access'],
    'BLOCKER-1: navbar = ровно 6 пунктов, включая modules');
})();

// ── BLOCKER-1 (негатив): без права modules пункт скрыт ───────────────────
(function () {
  const ctx = {
    route: '#/',
    canViewTab(id) { return id === 'status'; },
  };
  const ids = captured.computed.navItems.call(ctx).map((n) => n.id);
  assert.ok(ids.indexOf('modules') < 0,
    'BLOCKER-1: modules скрыт без права');
  assert.ok(ids.indexOf('status') >= 0, 'status всегда виден');
})();

// ── MAJOR-2: открытие модалки Сон грузит beliefs/лог ─────────────────────
(function () {
  let beliefs = 0, log = 0;
  const ctx = {
    openModuleId: null,
    isGlobalAdmin: true,
    dreamBeliefs: [], nostalgiaLog: [],
    memoryRagBusy: false,
    configItems: [{}],
    canViewTab() { return true; },
    loadDreamBeliefs() { beliefs += 1; },
    loadDreamLog() { log += 1; },
    loadNostalgiaLog() {},
    loadConfig() {},
    _ensureModuleData: methods._ensureModuleData,
  };
  methods.openModuleWindow.call(ctx, { id: 'mod_sleep', tab: 'mod_sleep' });
  assert.strictEqual(ctx.openModuleId, 'mod_sleep',
    'MAJOR-2: модалка Сон открыта');
  assert.strictEqual(beliefs, 1, 'MAJOR-2: loadDreamBeliefs вызван');
  assert.strictEqual(log, 1, 'MAJOR-2: loadDreamLog вызван');
})();

// ── MINOR-1: legacy-алиасы нормализуются ─────────────────────────────────
(function () {
  const ctx = {
    route: '#/', me: { role_name: 'admin' },
    canViewTab() { return true; },
    activeTab: 'status', accessOpen: null,
    tabs: captured.data().tabs,
    syncBackButton() {}, setTab(id) { this.activeTab = id; },
  };
  methods.applyRoute.call(ctx, '#/ai/limits');
  assert.strictEqual(ctx.route, '#/ai', 'MINOR-1: #/ai/limits → #/ai');
  ctx.route = '#/';
  methods.applyRoute.call(ctx, '#/ai/sleep');
  assert.strictEqual(ctx.route, '#/modules', 'MINOR-1: #/ai/sleep → #/modules');
})();

// ── MODERATE-2: closeModule сбрасывает openModuleId ──────────────────────
(function () {
  const ctx = { openModuleId: 'mod_sleep' };
  methods.closeModule.call(ctx);
  assert.strictEqual(ctx.openModuleId, null,
    'MODERATE-2: closeModule закрывает модалку');
})();

(async function () {
  let resolveApi;
  const c = {
    scopeEpoch: 1,
    api: () => new Promise((res) => { resolveApi = res; }),
    configItems: [], configGroups: [], configError: '',
    configLoading: false, configChatUpdatedAt: null,
    toast() {},
    _scopeGuard: methods._scopeGuard,
  };
  const p = methods.loadConfig.call(c);
  c.scopeEpoch = 2;   // scope сменился, пока запрос в полёте
  resolveApi({ items: [{ key: 'k', type: 'str', value: 'v' }], groups: [] });
  await p;
  assert.strictEqual(c.configItems.length, 0,
    'D2: устаревший config-ответ должен быть отброшен после смены scope');

  // non-stale — применяется
  let resolve2;
  const c2 = {
    scopeEpoch: 5,
    api: () => new Promise((res) => { resolve2 = res; }),
    configItems: [], configGroups: [], configError: '',
    configLoading: false, configChatUpdatedAt: null,
    toast() {},
    _scopeGuard: methods._scopeGuard,
  };
  const p2 = methods.loadConfig.call(c2);
  resolve2({ items: [{ key: 'k2', type: 'str', value: 'v2' }], groups: [] });
  await p2;
  assert.strictEqual(c2.configItems.length, 1,
    'D2: актуальный config-ответ применяется');

  // ── R1: устаревшее состояние chat-scoped НЕ применяется ────────────────
  let resolveKey;
  const k = {
    scopeEpoch: 1, activeChatId: 5, keyStatusOwn: 'old',
    api: () => new Promise((res) => { resolveKey = res; }),
    _scopeGuard: methods._scopeGuard,
  };
  const pk = methods.loadKeyStatus.call(k);
  k.scopeEpoch = 2;
  resolveKey({ own: { x: 1 } });
  await pk;
  assert.strictEqual(k.keyStatusOwn, 'old',
    'R1: устаревший loadKeyStatus не должен применяться');

  let resolveAdmins;
  const ca = {
    scopeEpoch: 1, adminsBusy: false, chatAdmins: ['old'],
    api: () => new Promise((res) => { resolveAdmins = res; }),
    toast() {}, loreErrText() { return ''; },
    _scopeGuard: methods._scopeGuard,
  };
  const pca = methods.loadChatAdmins.call(ca, -100);
  ca.scopeEpoch = 2;
  resolveAdmins([111, 222]);
  await pca;
  assert.deepStrictEqual(ca.chatAdmins, ['old'],
    'R1: устаревший loadChatAdmins не должен применяться');

  // ── R2/R3: устаревшая ОШИБКА не пишет configError/toast и не сбрасывает busy
  let rejectApi;
  const e1 = {
    scopeEpoch: 1,
    api: () => new Promise((_, rej) => { rejectApi = rej; }),
    configItems: [], configGroups: [], configError: '',
    configLoading: false, configChatUpdatedAt: null,
    _toasts: 0,
    toast() { this._toasts += 1; },
    _scopeGuard: methods._scopeGuard,
  };
  const pe = methods.loadConfig.call(e1);
  e1.scopeEpoch = 2;                 // scope сменился, запрос всё ещё в полёте
  const err = new Error('boom'); err.status = 500;
  rejectApi(err);
  await pe;
  assert.strictEqual(e1.configError, '',
    'R2: устаревшая ошибка не должна выставлять configError');
  assert.strictEqual(e1._toasts, 0,
    'R2: устаревшая ошибка не должна тостить');
  assert.strictEqual(e1.configLoading, true,
    'R3: устаревший finally не должен сбрасывать configLoading (владеет новый запрос)');

  // ── MINOR-3: saveBlock умеет ОЧИЩАТЬ поле (draft === '') ────────────────
  {
    const calls = [];
    const ctx = {
      blockSaving: {},
      blockDrafts: {
        'models.llm_base_url': 'https://new.example/v1',
        'models.llm_model_name': '',        // явная очистка
      },
      configItems: [
        { key: 'models.llm_base_url', type: 'str' },
        { key: 'models.llm_model_name', type: 'str' },
      ],
      configChatUpdatedAt: null,
      toast() {},
      loadConfig() {},
      async api(url, opts) { calls.push(JSON.parse(opts.body)); return {}; },
    };
    const b = {
      id: 'direct_main', title: 'T',
      fields: [
        { key: 'models.llm_base_url', role: 'base_url' },
        { key: 'models.llm_model_name', role: 'model' },
      ],
    };
    await methods.saveBlock.call(ctx, b);
    assert.strictEqual(calls.length, 1, 'MINOR-3: POST /api/config вызван');
    const items = calls[0].items;
    const byKey = {};
    items.forEach((i) => { byKey[i.key] = i.value; });
    assert.strictEqual(byKey['models.llm_model_name'], '',
      'MINOR-3: пустой draft очищает поле (не пропускается)');
    assert.strictEqual(byKey['models.llm_base_url'], 'https://new.example/v1',
      'MINOR-3: непустой draft сохраняется');
  }

  // ── MINOR-3 (негатив): draft == null → поле НЕ трогаем ───────────────────
  {
    const calls = [];
    const ctx = {
      blockSaving: {},
      blockDrafts: {},                      // ничего не введено
      configItems: [{ key: 'models.llm_base_url', type: 'str' }],
      configChatUpdatedAt: null,
      toast() {},
      loadConfig() {},
      async api(url, opts) { calls.push(JSON.parse(opts.body)); return {}; },
    };
    const b = { id: 'direct_main', title: 'T',
      fields: [{ key: 'models.llm_base_url', role: 'base_url' }] };
    await methods.saveBlock.call(ctx, b);
    assert.strictEqual(calls.length, 0,
      'MINOR-3: без правок POST не отправляется');
  }

  // ── MINOR-2: testField шлёт search_keys:tavily/exa ──────────────────────
  {
    const calls = [];
    const ctx = {
      blockTesting: {}, blockResults: {},
      blockFieldValue() { return 'tvly-key'; },
      toast() {},
      async api(url, opts) { calls.push(JSON.parse(opts.body)); return { ok: true, http_status: 200, latency_ms: 1 }; },
    };
    const b = { id: 'search_keys' };
    await methods.testField.call(ctx, b, { key: 'keys.tavily_api_key', probeTarget: 'search_keys:tavily' });
    await methods.testField.call(ctx, b, { key: 'keys.exa_api_key', probeTarget: 'search_keys:exa' });
    assert.deepStrictEqual(calls.map((c) => c.block),
      ['search_keys:tavily', 'search_keys:exa'],
      'MINOR-2: каждый поисковый ключ тестируется отдельным target');
  }

  // ── R10.6-1: generic-редакторы не дублируют поля блоков ─────────────────
  {
    const ctx = {
      configSearch: '',
      configGroups: [],
      activeTab: 'llm_providers',
      providerBlocks: captured.data().providerBlocks,
      providerCoveredKeys: methods.providerCoveredKeys,
      tabSourceForItem() { return true; },
      basicItems(g) { return g.items; },
      advancedItems() { return []; },
      flatGroupRank() { return 0; },
      configItems: [
        { key: 'models.llm_base_url', category: 'models',
          group: 'models_main', title: 'base', progressive_level: '' },
        { key: 'models.llm_cb_failure_threshold', category: 'models',
          group: 'models_llm_guard', title: 'cb', progressive_level: '' },
        { key: 'models.llm_fallback_max_retries', category: 'models',
          group: 'models_fallback', title: 'ret', progressive_level: '' },
      ],
    };
    const groups = methods.groupedForTab.call(ctx,
      { id: 'llm_providers', sources: [{}] });
    const keys = groups.reduce((a, g) => a.concat(g.items.map((i) => i.key)), []);
    assert.ok(keys.indexOf('models.llm_base_url') < 0,
      'R10.6-1: ключ блока скрыт из generic-рендера');
    assert.ok(keys.indexOf('models.llm_cb_failure_threshold') >= 0,
      'R10.6-1: не-блоковый ключ остаётся в generic-рендере');
    assert.ok(keys.indexOf('models.llm_fallback_max_retries') >= 0,
      'R10.6-1: не-блоковый ключ fallback остаётся');
    // Другой tab (модуль) не фильтруется.
    const modGroups = methods.groupedForTab.call(ctx,
      { id: 'mod_checkup', sources: [{}] });
    const modKeys = modGroups.reduce((a, g) => a.concat(g.items.map((i) => i.key)), []);
    assert.ok(modKeys.indexOf('models.llm_base_url') >= 0,
      'R10.6-1: фильтр только для llm_providers');
  }

  console.log('JS-UNIT-OK');
})().catch((e) => {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
