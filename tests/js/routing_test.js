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

  // ── 10.11 (п.3, ADR-1011-3): keyHistoryChartModel — точки {x,y} (ms),
  //    spanGaps:true + stepped:true, xMin/xMax; дорожки и сетка сохранены ──
  {
    // 1700000100 делится на 300 нацело (бакет ring).
    const base = 1700000100;
    const model = methods.keyHistoryChartModel.call({}, [
      { module_id: 'a', module_title: 'A', samples: [{ ts: base, ok: true }] },
      { module_id: 'b', module_title: 'B',
        samples: [{ ts: base + 300, ok: false }] },
    ]);
    assert.ok(model, 'п.3: модель построена');
    assert.ok(model.labels.length >= 12,
      'п.3: временная сетка не короче MIN_BUCKETS (1 час)');
    assert.strictEqual(model.laneCount, 2, 'п.3: две дорожки');
    assert.strictEqual(model.height, Math.max(120, 44 + 2 * 22),
      'п.3: высота = max(120, 44 + laneCount*22)');
    // Данные — точки {x: ms, y: lane|null}.
    assert.ok(Array.isArray(model.datasets[0].data), 'п.3: data — массив');
    assert.strictEqual(typeof model.datasets[0].data[0].x, 'number',
      'п.3: точка содержит числовой x (ms)');
    assert.strictEqual(model.datasets[0].data[0].x, model.xMin,
      'п.3: первый x = xMin (ms)');
    assert.strictEqual(
      model.datasets[0].data[1].x - model.datasets[0].data[0].x,
      300 * 1000, 'п.3: шаг сетки 300с в ms');
    // Дорожки не пересекаются: lane0 < 1, lane1 >= 1.
    const aVals = model.datasets[0].data
      .filter((d) => d.y != null).map((d) => d.y);
    const bVals = model.datasets[1].data
      .filter((d) => d.y != null).map((d) => d.y);
    assert.deepStrictEqual(aVals, [0.75], 'п.3: lane0 ok = 0.75');
    assert.deepStrictEqual(bVals, [1.25], 'п.3: lane1 err = 1.25');
    assert.ok(Math.max.apply(null, aVals) < Math.min.apply(null, bVals),
      'п.3: дорожки не сливаются');
    // Пропущенный слот = {x, y:null} (spanGaps тянет шаг).
    const nullSlots = model.datasets[0].data.filter((d) => d.y == null);
    assert.ok(nullSlots.length > 0, 'п.3: пропущенные слоты представлены');
    assert.strictEqual(typeof nullSlots[0].x, 'number',
      'п.3: у пропуска есть x');
    // ≤1 сэмпла → точка видна.
    assert.strictEqual(model.datasets[0].pointRadius, 3,
      'п.3: pointRadius=3 при 1 сэмпле');
    assert.strictEqual(model.datasets[1].pointRadius, 3,
      'п.3: pointRadius=3 при 1 сэмпле');
    // 10.11: непрерывная ступенчатая линия + честная время-ось.
    assert.strictEqual(model.datasets[0].stepped, true, 'п.3: stepped');
    assert.strictEqual(model.datasets[0].spanGaps, true, 'п.3: spanGaps=true');
    assert.strictEqual(model.xMin, model.datasets[0].data[0].x,
      'п.3: xMin = первый x');
    assert.strictEqual(model.xMax,
      model.datasets[0].data[model.datasets[0].data.length - 1].x,
      'п.3: xMax = последний x');

    // Больше сэмплов → точка скрыта.
    const many = methods.keyHistoryChartModel.call({}, [
      { module_id: 'a', samples: [
        { ts: base, ok: true }, { ts: base + 300, ok: true }] },
    ]);
    assert.strictEqual(many.datasets[0].pointRadius, 0,
      'п.3: pointRadius=0 при >1 сэмпле');

    // Пусто / нет сэмплов → null (чарт не строится).
    assert.strictEqual(methods.keyHistoryChartModel.call({}, []), null,
      'п.3: пустой вход → null');
    assert.strictEqual(methods.keyHistoryChartModel.call({},
      [{ module_id: 'a', samples: [] }]), null,
      'п.3: провайдеры без сэмплов → null');
  }

  // ── 10.11 (п.3): рендер-конфиг — linear-time без date-adapter ───────────
  {
    const src = require('fs').readFileSync(
      path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
    assert.ok(src.indexOf("type: 'linear'") >= 0,
      'п.3: X-ось — linear (без adapter)');
    assert.ok(src.indexOf('parsing: false') >= 0,
      'п.3: parsing:false (явные {x,y})');
    assert.ok(src.indexOf("type: 'time'") < 0,
      'п.3: type:time не используется (нет адаптера)');
    assert.ok(src.indexOf("return pad(d.getHours()) + ':' + pad(d.getMinutes());") >= 0,
      'п.3: ticks.callback HH:MM');
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
    assert.strictEqual(last.y, 0.25,
      'HIGH-1: новейший сэмпл (endBucket) присутствует ПОСЛЕДНИМ');
    // Старый сэмпл за пределами окна-cap в сетку не попадает.
    assert.ok(span.datasets[0].data.every((d) => d.y !== 0.75),
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

  // ── 10.11 (п.1, ADR-1011-1): R17-индикатор + testBlock не шлёт секрет ──
  {
    const ctx = { configItems: [
      { key: 'keys.llm_api_key', type: 'str',
        value: { configured: true, last4: '9xyz' } },
      { key: 'k2', type: 'str', value: '' },
    ] };
    assert.strictEqual(
      methods.blockFieldConfigured.call(ctx, { key: 'keys.llm_api_key' }), true,
      'п.1: сохранённый ключ → configured=true');
    assert.strictEqual(methods.last4ByKey.call(ctx, 'keys.llm_api_key'),
      '9xyz', 'п.1: last4ByKey из маски');
    assert.strictEqual(methods.blockFieldConfigured.call(ctx, { key: 'k2' }),
      false, 'п.1: пустое значение → configured=false');
    assert.strictEqual(methods.last4ByKey.call(ctx, 'k2'), '',
      'п.1: нет маски → пустой last4');

    const calls = [];
    const makeBlockCtx = (drafts) => ({
      blockTesting: {}, blockResults: {}, blockDrafts: drafts,
      configItems: ctx.configItems,
      blockFieldValue: methods.blockFieldValue,
      api: async (url, opts) => {
        calls.push(JSON.parse(opts.body));
        return { ok: true, http_status: 200, latency_ms: 1 };
      },
    });
    const b = { id: 'direct_main', fields: [
      { key: 'keys.llm_api_key', role: 'api_key', secret: true }] };
    // Пустой черновик + сохранённый секрет → api_key пустой (резолв бэкенд).
    await methods.testBlock.call(makeBlockCtx({}), b);
    assert.strictEqual(calls[0].api_key, '',
      'п.1: сохранённый секрет не уходит с фронта');
    // Новый черновик → уходит именно он (тест до сохранения).
    await methods.testBlock.call(
      makeBlockCtx({ 'keys.llm_api_key': 'new-key-abc' }), b);
    assert.strictEqual(calls[1].api_key, 'new-key-abc',
      'п.1: явный черновик уходит в probe');
  }

  // ── 10.11 (пп.2.2–2.5): зоны, подблоки, порядок видео-фоллбэка ─────────
  {
    // Reviewer CRITICAL/HIGH: зоны ОБЯЗАНЫ быть computed (шаблон использует
    // их как bare-ref: `v-for="b in providerConnectionBlocks"` и
    // `providerAdvancedBlocks.length`). Метод в этом месте рендерил бы `[]`
    // → все блоки 2.2–2.5 исчезали. Тест — жёсткий гейт против регресса.
    assert.strictEqual(typeof computed.providerConnectionBlocks, 'function',
      '2.2: providerConnectionBlocks — computed-функция');
    assert.strictEqual(typeof computed.providerAdvancedBlocks, 'function',
      '2.2: providerAdvancedBlocks — computed-функция');
    assert.strictEqual(methods.providerConnectionBlocks, undefined,
      '2.2: providerConnectionBlocks НЕ в methods (иначе bare-ref → [])');
    assert.strictEqual(methods.providerAdvancedBlocks, undefined,
      '2.2: providerAdvancedBlocks НЕ в methods (иначе bare-ref → [])');
    // Исходник: определения лежат в секции `computed:` (между computed: и
    // methods:), а не в `methods:`.
    const src = require('fs').readFileSync(
      path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
    const computedAt = src.indexOf('computed:');
    const methodsAt = src.indexOf('methods:');
    const connAt = src.indexOf('providerConnectionBlocks: function');
    const advAt = src.indexOf('providerAdvancedBlocks: function');
    assert.ok(computedAt >= 0 && methodsAt > computedAt,
      '2.2: секция computed: идёт перед methods:');
    assert.ok(connAt > computedAt && connAt < methodsAt,
      '2.2: providerConnectionBlocks определён ВНУТРИ computed:');
    assert.ok(advAt > computedAt && advAt < methodsAt,
      '2.2: providerAdvancedBlocks определён ВНУТРИ computed:');
    // Шаблон использует bare-ref (computed), а не вызов () — вызывать
    // computed как функцию нельзя.
    const html = require('fs').readFileSync(
      path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
    assert.ok(html.indexOf('v-for="b in providerConnectionBlocks"') >= 0,
      '2.2: шаблон итерирует computed providerConnectionBlocks');
    assert.ok(html.indexOf('v-for="b in providerAdvancedBlocks"') >= 0,
      '2.2: шаблон итерирует computed providerAdvancedBlocks');
    assert.ok(html.indexOf('providerConnectionBlocks()') < 0
      && html.indexOf('providerAdvancedBlocks()') < 0,
      '2.2: computed не вызывается как функция в шаблоне');

    const blocks = captured.data().providerBlocks;
    const conn = computed.providerConnectionBlocks.call(
      { providerBlocks: blocks });
    const adv = computed.providerAdvancedBlocks.call(
      { providerBlocks: blocks });
    assert.ok(conn.length > 0 && conn.every((b) => b.zone !== 'advanced'),
      '2.2: «Подключения» — без advanced-блоков');
    assert.deepStrictEqual(adv.map((b) => b.id),
      ['llm_guard', 'search_keys', 'media_share'],
      '2.2/2.5: в «Расширенных» — guard/search/media_share');
    const ids = blocks.map((b) => b.id);
    assert.strictEqual(ids[ids.indexOf('video_summary_openrouter') + 1],
      'video_fallback', '2.4: запасная видео-модель сразу под основной');
    const emb = blocks.filter((b) => b.id === 'embeddings')[0];
    assert.ok(emb && emb.subBlocks, '2.3: блок эмбеддингов — subBlocks');
    assert.deepStrictEqual(emb.subBlocks.map((sb) => sb.id),
      ['embeddings_main', 'embeddings_fallback1', 'embeddings_fallback2'],
      '2.3: ровно 3 подблока в порядке Основная/Ф1/Ф2');
    emb.subBlocks.forEach((sb) => {
      const roles = sb.fields.map((f) => f.role);
      assert.ok(roles.indexOf('base_url') >= 0 && roles.indexOf('model') >= 0
        && roles.indexOf('api_key') >= 0,
        '2.3: у подблока есть Base URL + Модель + Ключ');
    });
    const media = blocks.filter((b) => b.id === 'media_share')[0];
    assert.strictEqual(media.zone, 'advanced', '2.5: media_share — advanced');
    assert.ok(media.note && media.note.indexOf('Секретный токен') >= 0,
      '2.5: media_share с human-subtext');
    // providerCoveredKeys рекурсивно покрывает subBlocks (нет generic-дублей).
    const covered = methods.providerCoveredKeys.call({ providerBlocks: blocks });
    assert.ok(covered['models.embedding_fallback_base_url'],
      '2.3: subBlock-ключи скрыты из generic-рендера');
    assert.ok(covered['keys.embedding_fallback_api_key_2'],
      '2.3: второй ключ фоллбэка скрыт из generic-рендера');
  }

  // ── 10.11 Scanner LOW: отдельные localStorage-ключи outer advanced-зоны и
  //    inner group-аккордеонов («Провайдеры») — не открывают друг друга ───
  {
    const store = {};
    const savedLocalStorage = global.localStorage;
    global.localStorage = {
      getItem(k) {
        return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
      },
      setItem(k, v) { store[k] = String(v); },
    };
    try {
      const ctx = { expandOpen: methods.expandOpen,
                    toggleExpand: methods.toggleExpand };
      // Открываем ТОЛЬКО внешнюю зону (scope='prov-advanced').
      methods.toggleExpand.call(ctx, 'llm_providers', 'prov-advanced');
      assert.strictEqual(
        methods.expandOpen.call(ctx, 'llm_providers', 'prov-advanced'), true,
        'LOW: outer advanced-зона открыта');
      assert.strictEqual(
        methods.expandOpen.call(ctx, 'llm_providers'), false,
        'LOW: inner group-аккордеон НЕ раскрыт вместе с outer');
      // Ключи действительно разные.
      assert.ok(store['adminbot.expand:llm_providers:prov-advanced'] === '1',
        'LOW: outer-ключ отдельный');
      assert.strictEqual(store['adminbot.expand:llm_providers'], undefined,
        'LOW: inner-ключ не тронут outer-тоглом');
      // Исторический bare-ключ работает как раньше (обратная совместимость).
      methods.toggleExpand.call(ctx, 'llm_providers');
      assert.strictEqual(methods.expandOpen.call(ctx, 'llm_providers'), true,
        'LOW: inner-ключ открывается отдельно');
      assert.strictEqual(
        methods.expandOpen.call(ctx, 'llm_providers', 'prov-advanced'), true,
        'LOW: outer при этом остаётся открытым (независимость)');
    } finally {
      if (savedLocalStorage === undefined) {
        delete global.localStorage;
      } else {
        global.localStorage = savedLocalStorage;
      }
    }
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
