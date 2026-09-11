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
        if (global.window.__adminbotClipGhost === el) {
          global.window.__adminbotClipGhost = null;
        }
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
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;

// ── 10.7 (1a): scope*-производные — computed, НЕ methods ──────────────────
(function () {
  const names = ['scopeKind', 'scopeLabel', 'scopeOptions',
    'scopeTriggerTitle', 'scopeTriggerInitial', 'scopeTriggerAvatar'];
  names.forEach((n) => {
    assert.strictEqual(typeof computed[n], 'function',
      '1a: computed.' + n + ' — функция');
    assert.strictEqual(methods[n], undefined,
      '1a: methods.' + n + ' отсутствует');
  });
  const opts = computed.scopeOptions.call(
    { isGlobalAdmin: true, scopeSearch: '', accessChats: [] });
  assert.ok(Array.isArray(opts), '1a: scopeOptions возвращает массив');
  assert.strictEqual(opts[0].key, 'global',
    '1a: global-опция присутствует для глобального админа');
})();

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

// ── 10.8 (§4, ADR-001): окно «Доступов» — производная hash ──────────────
(function () {
  const ctx = {
    route: '#/', me: { role_name: 'admin' },
    canViewTab() { return true; },
    activeTab: 'status', accessOpen: null,
    tabs: captured.data().tabs,
    syncBackButton() {}, setTab(id) { this.activeTab = id; },
  };
  methods.applyRoute.call(ctx, '#/access/roles');
  assert.strictEqual(ctx.accessOpen, 'roles',
    '10.8: #/access/roles → окно roles');
  methods.applyRoute.call(ctx, '#/ai');
  assert.strictEqual(ctx.accessOpen, null,
    '10.8: уход на другой раздел обнуляет accessOpen');
})();

// ── 10.8 (§3b): fmtLogTime возвращает дату+время DD.MM HH:MM:SS ──────────
(function () {
  const out = methods.fmtLogTime.call({}, new Date(2026, 8, 11, 14, 32, 7).getTime());
  assert.strictEqual(out, '11.09 14:32:07',
    '10.8: fmtLogTime = DD.MM HH:MM:SS, got ' + out);
})();

// ── 10.8 (R10.8-1): Esc закрывает окно «Доступов» ───────────────────────
(function () {
  let closed = 0;
  const ctx = {
    openModuleId: null,
    accessOpen: 'roles',
    closeModule() { throw new Error('модуль закрывать не нужно'); },
    closeAccessWindow() { closed += 1; this.accessOpen = null; },
  };
  methods.escClose.call(ctx);
  assert.strictEqual(closed, 1, '10.8: Esc закрывает access-окно');
  assert.strictEqual(ctx.accessOpen, null, '10.8: accessOpen сброшен');

  // Окно модуля приоритетнее окна «Доступов».
  const ctx2 = {
    openModuleId: 'mod_sleep', accessOpen: 'roles',
    closeModule() { this.openModuleId = null; },
    closeAccessWindow() { throw new Error('access не трогаем при модуле'); },
  };
  methods.escClose.call(ctx2);
  assert.strictEqual(ctx2.openModuleId, null,
    '10.8: Esc сначала закрывает модуль');

  // Ничего не открыто — no-op.
  const ctx3 = { openModuleId: null, accessOpen: null,
    closeModule() { throw new Error('no-op'); },
    closeAccessWindow() { throw new Error('no-op'); } };
  methods.escClose.call(ctx3);
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

  // ── 10.7 (3a): ghost-textarea не остаётся в DOM ─────────────────────────
  {
    const toasts = [];
    const stub = { toast(m, k) { toasts.push([m, k]); } };
    await methods.copyText.call(stub, 'hello');
    assert.strictEqual(_bodyChildren.length, 0,
      '3a: clipboard-ghost удалён из DOM');
    assert.ok(!global.window.__adminbotClipGhost,
      '3a: window.__adminbotClipGhost сброшен');
    assert.deepStrictEqual(toasts, [['Скопировано', 'ok']],
      'DEF-2: execCommand=true → ok-тост');
  }

  // ── 10.7 (DEF-2): execCommand=false → err-тост, без ложного «Скопировано»
  {
    const toasts = [];
    const stub = { toast(m, k) { toasts.push([m, k]); } };
    const orig = global.document.execCommand;
    global.document.execCommand = function () { return false; };
    try {
      await methods.copyText.call(stub, 'x');
    } finally {
      global.document.execCommand = orig;
    }
    assert.deepStrictEqual(toasts, [['Не удалось скопировать', 'err']],
      'DEF-2: false-execCommand → err-тост');
  }

  // ── 10.7 (3c): copyLogRow ставит copiedIndex и копирует строку ──────────
  {
    const stub = {
      copiedIndex: null, copiedTimer: null, lastCopy: null,
      logText(l) { return 'LOG:' + l.message; },
      copyText(t) { this.lastCopy = t; },
    };
    methods.copyLogRow.call(stub, { message: 'm1' }, 2);
    assert.strictEqual(stub.copiedIndex, 2, '3c: copiedIndex выставлен');
    assert.strictEqual(stub.lastCopy, 'LOG:m1', '3c: строка скопирована');
    clearTimeout(stub.copiedTimer);
  }

  // ── 10.9 (LOW-7): _preserveScroll сохраняет оба скроллера ─────────────
  {
    const scroller = { scrollTop: 777 };
    const area = { scrollTop: 333 };
    const savedScrolling = global.document.scrollingElement;
    const savedQuery = global.document.querySelector;
    global.document.scrollingElement = scroller;
    global.document.querySelector = function (sel) {
      return sel === '.scroll-area' ? area : null;
    };
    try {
      const ctx = { calls: 0, tick: null,
        $nextTick(cb) { this.tick = cb; } };
      const p = methods._preserveScroll.call(ctx, async function () {
        this.calls += 1;
        scroller.scrollTop = 0;   // имитируем ре-рендер
        area.scrollTop = 0;
        return 'R';
      });
      await p;
      assert.strictEqual(ctx.calls, 1, '10.9: fn вызвана один раз');
      assert.ok(ctx.tick, '10.9: восстановление отложено в $nextTick');
      ctx.tick();
      assert.strictEqual(scroller.scrollTop, 777,
        '10.9: document scrollTop восстановлен');
      assert.strictEqual(area.scrollTop, 333,
        '10.9: main.scroll-area scrollTop восстановлен');
    } finally {
      global.document.scrollingElement = savedScrolling;
      global.document.querySelector = savedQuery;
    }
  }

  // ── 10.9 (LOW-7): спиннер конфига — только на ПЕРВОЙ загрузке ─────────
  {
    const fs = require('fs');
    const htmlPath = path.join(__dirname, '..', '..', 'web', 'index.html');
    const html = fs.readFileSync(htmlPath, 'utf8');
    assert.ok(html.indexOf('v-if="configLoading && !configItems.length"') >= 0,
      '10.9: большой спиннер только при пустом configItems');
  }

  // ── 10.10 (п.2): keyHistoryChartModel — дорожки + временная сетка ──────
  {
    // 1700000100 делится на 300 нацело (бакет ring).
    const base = 1700000100;
    const model = methods.keyHistoryChartModel.call({}, [
      { module_id: 'a', module_title: 'A', samples: [{ ts: base, ok: true }] },
      { module_id: 'b', module_title: 'B',
        samples: [{ ts: base + 300, ok: false }] },
    ]);
    assert.ok(model, 'п.2: модель построена');
    assert.ok(model.labels.length >= 12,
      'п.2: временная сетка не короче MIN_BUCKETS (1 час)');
    assert.strictEqual(model.laneCount, 2, 'п.2: две дорожки');
    assert.strictEqual(model.height, Math.max(120, 44 + 2 * 22),
      'п.2: высота = max(120, 44 + laneCount*22)');
    // Дорожки не пересекаются: lane0 < 1, lane1 >= 1.
    const aVals = model.datasets[0].data.filter((v) => v != null);
    const bVals = model.datasets[1].data.filter((v) => v != null);
    assert.deepStrictEqual(aVals, [0.75], 'п.2: lane0 ok = 0.75');
    assert.deepStrictEqual(bVals, [1.25], 'п.2: lane1 err = 1.25');
    assert.ok(Math.max.apply(null, aVals) < Math.min.apply(null, bVals),
      'п.2: дорожки не сливаются');
    // Пропущенный слот = null (spanGaps:false).
    assert.strictEqual(model.datasets[0].data[0], null,
      'п.2: пропущенный слот = null');
    // ≤1 сэмпла → точка видна.
    assert.strictEqual(model.datasets[0].pointRadius, 3,
      'п.2: pointRadius=3 при 1 сэмпле');
    assert.strictEqual(model.datasets[1].pointRadius, 3,
      'п.2: pointRadius=3 при 1 сэмпле');
    // Сохранённые маркеры рендера.
    assert.strictEqual(model.datasets[0].stepped, true, 'п.2: stepped');
    assert.strictEqual(model.datasets[0].spanGaps, false, 'п.2: spanGaps');

    // Больше сэмплов → точка скрыта.
    const many = methods.keyHistoryChartModel.call({}, [
      { module_id: 'a', samples: [
        { ts: base, ok: true }, { ts: base + 300, ok: true }] },
    ]);
    assert.strictEqual(many.datasets[0].pointRadius, 0,
      'п.2: pointRadius=0 при >1 сэмпле');

    // Пусто / нет сэмплов → null (чарт не строится).
    assert.strictEqual(methods.keyHistoryChartModel.call({}, []), null,
      'п.2: пустой вход → null');
    assert.strictEqual(methods.keyHistoryChartModel.call({},
      [{ module_id: 'a', samples: [] }]), null,
      'п.2: провайдеры без сэмплов → null');
  }

  // ── 10.10 (HIGH-1/LOW-5): разброс > MAX_HISTORY_POINTS бакетов — окно
  //    строится ОТ КОНЦА, новейший сэмпл обязан быть ПОСЛЕДНИМ ────────────
  {
    const BUCKET = 300;
    const MAXPTS = 288;                       // MAX_HISTORY_POINTS
    const endTs = 1700000100;                 // делится на 300 нацело
    const earlyTs = endTs - 900 * BUCKET;     // разброс 900 > 2*288
    const span = methods.keyHistoryChartModel.call({}, [
      { module_id: 'a', module_title: 'A', samples: [
        { ts: earlyTs, ok: true },
        { ts: endTs, ok: false },             // НОВЕЙШИЙ
      ] },
    ]);
    assert.ok(span, 'HIGH-1: модель построена');
    assert.ok(span.labels.length <= MAXPTS,
      'HIGH-1: окно не длиннее MAX_HISTORY_POINTS');
    assert.strictEqual(span.labels.length, MAXPTS,
      'HIGH-1: окно ровно MAX_HISTORY_POINTS (от конца)');
    const last = span.datasets[0].data[span.datasets[0].data.length - 1];
    assert.strictEqual(last, 0.25,
      'HIGH-1: новейший сэмпл (endBucket) присутствует ПОСЛЕДНИМ');
    // Старый сэмпл за пределами окна-cap в сетку не попадает.
    assert.ok(span.datasets[0].data.indexOf(0.75) < 0,
      'HIGH-1: древний сэмпл вне окна (окно не «середина» старого)');
  }

  // ── 10.10 (п.3): blockFieldValue — реальные значения configItems ───────
  {
    const ctx = {
      blockDrafts: {},
      configItems: [
        { key: 'models.llm_base_url', type: 'str', value: 'https://real/v1' },
        { key: 'models.llm_model_name', type: 'str', value: 'real-model' },
        { key: 'keys.groq_api_key', type: 'str',
          value: { configured: true, last4: '1234' } },
      ],
    };
    // Нет черновика → реальное значение из configItems.
    assert.strictEqual(
      methods.blockFieldValue.call(ctx, { key: 'models.llm_base_url' }),
      'https://real/v1', 'п.3: fallback на configItems');
    // Секрет (объект-маска) → пусто (placeholder-маска).
    assert.strictEqual(
      methods.blockFieldValue.call(ctx, { key: 'keys.groq_api_key' }),
      '', 'п.3: секрет не префиллится');
    // Явная очистка (''), НЕ откат к старому значению.
    ctx.blockDrafts = { 'models.llm_model_name': '' };
    assert.strictEqual(
      methods.blockFieldValue.call(ctx, { key: 'models.llm_model_name' }),
      '', 'п.3: пустой черновик = очистка, не откат');
    // Заданный черновик — приоритетнее.
    ctx.blockDrafts = { 'models.llm_base_url': 'https://draft/v1' };
    assert.strictEqual(
      methods.blockFieldValue.call(ctx, { key: 'models.llm_base_url' }),
      'https://draft/v1', 'п.3: черновик приоритетнее');
  }

  // ── 10.10 (п.5): adminInitial переиспользует avatarInitial ────────────
  {
    const initCtx = {
      avatarInitial: methods.avatarInitial,
      resolveRelationName: methods.resolveRelationName,
      summaryAliasesMap() { return {}; },
    };
    assert.strictEqual(
      methods.adminInitial.call(initCtx,
        { display_name: 'Иван', telegram_id: 1 }),
      'И', 'п.5: инициал из display_name (через avatarInitial)');
    assert.strictEqual(
      methods.adminInitial.call(initCtx,
        { display_name: 'Bob', telegram_id: 1 }),
      'B', 'п.5: инициал из display_name (лат.)');
    assert.strictEqual(
      methods.adminInitial.call(initCtx, { telegram_id: 12345 }),
      '1', 'п.5: фолбэк — первый символ ID');
    assert.strictEqual(methods.adminInitial.call(initCtx, null), '?',
      'п.5: null → ?');
    // Нет дубля графем-логики: adminInitial не использует Array.from сам.
    const src = require('fs').readFileSync(
      path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
    const adminBlock = src.slice(src.indexOf('adminInitial: function'),
      src.indexOf('loadRoles: async function'));
    assert.ok(adminBlock.indexOf('Array.from') < 0,
      'п.5: adminInitial не дублирует графем-логику (reuse avatarInitial)');
  }

  // ── Scanner LOW: renderKeyHistoryChart рвёт stale Chart при пустой истории
  {
    let destroyed = 0;
    const ctx = {
      keyHistory: null,
      keyHistoryChart: { destroy() { destroyed += 1; } },
      keyHistoryChartHeight: 999,
      $refs: {},
      $nextTick(cb) { cb(); },
      keyHistoryChartModel: methods.keyHistoryChartModel,
    };
    methods.renderKeyHistoryChart.call(ctx);
    assert.strictEqual(destroyed, 1,
      'LOW: stale chart.destroy() вызван при keyHistory == null');
    assert.strictEqual(ctx.keyHistoryChart, null,
      'LOW: ссылка keyHistoryChart очищена');
    assert.strictEqual(ctx.keyHistoryChartHeight, 120,
      'LOW: высота сброшена при пустой истории');
  }

  console.log('JS-UNIT-OK');
})().catch((e) => {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
