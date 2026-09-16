'use strict';
/* Раунд 10.20 / Фаза D (БЛОК 3) — поведенческие тесты UX-рефакторинга.
 *
 * Покрытие (T-1903):
 *   T-1895a  binding конфига (значение из БД попадает в инпут; секрет → маска)
 *   T-1895b  роутинг «Модули → Параметры» (модалка открывается, root cause)
 *   T-1895c  тумблер relations_enabled (оптимистичный + откат + 409-путь)
 *   T-1896   досье участника (open/load/save/close)
 *   T-1897   тикер «Живая лента досье» (loop, реактивность, polling)
 *   T-1900   sticky-save (dirty/cancel/save)
 *   T-1903   снимок навигации (меню НЕ изменено)
 *
 * Запуск: node tests/js/round1020_ui_test.js   (печатает JS-UNIT-OK)
 */
const path = require('path');
const fs = require('fs');
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

// ── T-1903: снимок навигации — состав/порядок разделов НЕ изменён ─────────
(function () {
  const expectedTabs = [
    'llm_providers', 'prompts',
    'mod_summary', 'mod_direct', 'mod_factcheck', 'mod_search',
    'mod_transcribe', 'mod_video_summary', 'mod_media_download', 'mod_web',
    'mod_checkup', 'mod_sleep', 'mod_nostalgia', 'mod_budgets',
    'modules', 'memory_rag', 'smart_cache', 'people_names', 'relations',
    'permsoc', 'access', 'chat_lore', 'status', 'info', 'oversight',
  ];
  assert.deepStrictEqual(data.tabs.map((t) => t.id), expectedTabs,
    'T-1903: состав/порядок вкладок (меню) не изменился');
  const nav = computed.navItems.call({ route: '#/', canViewTab() { return true; } });
  assert.deepStrictEqual(nav.map((n) => n.id),
    ['status', 'how', 'modules', 'ai', 'permsoc', 'access'],
    'T-1903: navbar — те же 6 пунктов');
  // Состав модулей (11 + «Бюджеты») тоже стабилен.
  assert.strictEqual(data.modules.length, 12, 'T-1903: карточек модулей — 12');
})();

// ── T-1895a: binding — значение из БД попадает в инпут; секрет → маска ────
(function () {
  const ctx = {
    blockDrafts: {},
    configItems: [
      { key: 'models.llm_base_url', type: 'str', value: 'https://db/v1' },
      { key: 'limits.llm_timeout', type: 'float', value: 12.5 },
      { key: 'flags.x', type: 'bool', value: false },
      { key: 'keys.llm_api_key', type: 'str',
        category: 'keys', secret: true,
        value: { configured: true, last4: '1234' } },
      { key: 'models.empty', type: 'str', value: null },
    ],
  };
  assert.strictEqual(
    methods.blockFieldValue.call(ctx, { key: 'models.llm_base_url' }),
    'https://db/v1', 'T-1895a: строка из БД попадает в инпут');
  assert.strictEqual(
    methods.blockFieldValue.call(ctx, { key: 'limits.llm_timeout' }),
    12.5, 'T-1895a: число из БД попадает в инпут');
  // UPD3 (T-1936/INV-3): секрет configured → инпут показывает МАСКУ, не ''.
  assert.strictEqual(
    methods.blockFieldValue.call(ctx, { key: 'keys.llm_api_key', secret: true }),
    '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022',
    'T-1895a: секрет префиллится маской');
  assert.strictEqual(
    methods.blockFieldValue.call(ctx, { key: 'models.empty' }), '',
    'T-1895a: пусто только при реальном null');
  // Маска «configured ••••1234» из placeholder.
  assert.ok(
    methods.blockFieldPlaceholder.call(ctx, { key: 'keys.llm_api_key', label: 'Ключ' })
      .indexOf('configured ••••1234') >= 0,
    'T-1895a: заглушка секрета = configured ••••1234');
  assert.strictEqual(
    methods.blockFieldConfigured.call(ctx, { key: 'keys.llm_api_key' }), true,
    'T-1895a: badge «configured» для сохранённого ключа');
  // Шаблон: generic-инпуты — two-way `v-model="item.value"`.
  assert.ok(INDEX.indexOf('v-model="item.value"') >= 0,
    'T-1895a: generic-инпуты конфига на two-way binding');
})();

// ── T-1895b: роутинг «Модули → Параметры» у «Выжимки видео» ───────────────
(function () {
  // Root cause: карточка модуля видна по широкому предикату вкладки
  // «Модули», а старый гейт canViewTab(m.tab) требовал секцию конкретной
  // config-вкладки → модалка не открывалась. Фикс: гейт по 'modules'.
  const toasts = [];
  const ctx = {
    openModuleId: null,
    configItems: [{}],
    isGlobalAdmin: false,
    dreamBeliefs: [], nostalgiaLog: [], memoryRagBusy: false,
    canViewTab(id) { return id === 'modules'; },   // mod_video_summary НЕ виден
    toast(m, k) { toasts.push([m, k]); },
    loadConfig() {},
    _ensureModuleData: methods._ensureModuleData,
    _snapshotConfig() {},
  };
  const mod = data.modules.filter((m) => m.id === 'mod_video_summary')[0];
  assert.ok(mod, 'T-1895b: карточка «Выжимка видео» существует');
  methods.openModuleWindow.call(ctx, mod);
  assert.strictEqual(ctx.openModuleId, 'mod_video_summary',
    'T-1895b: модалка «Выжимка видео» открывается без права на config-вкладку');
  assert.strictEqual(toasts.length, 0, 'T-1895b: без ложного «нет доступа»');
  // Негатив: без права на «Модули» — отказ (RBAC сохранён).
  const ctx2 = Object.assign({}, ctx, {
    openModuleId: null, canViewTab() { return false; },
  });
  methods.openModuleWindow.call(ctx2, mod);
  assert.strictEqual(ctx2.openModuleId, null, 'T-1895b: без «Модулей» — отказ');
})();

// ── T-1895c: тумблер relations_enabled — оптимистично + откат + 409 ───────
(async function () {
  // Успех: мгновенный стейт + подтверждение сервера.
  const c = {
    activeTab: 'relations', activeChatId: -100, chatLoreProfile: null,
    relationsBusy: false, relationsEnabled: false, chatLore409: null,
    toasts: [],
    toast(m, k) { this.toasts.push([m, k]); },
    loreErrText() { return 'err'; },
    applyLoreProfile() {},
    async api() { return { relations_enabled: true, updated_at: 't1' }; },
  };
  await methods.toggleRelationsEnabled.call(c, true);
  assert.strictEqual(c.relationsEnabled, true, 'T-1895c: тумблер включён');
  assert.strictEqual(c.relationsBusy, false, 'T-1895c: busy сброшен');

  // 409 конкурентности: откат к прежнему + окно конфликта (без «залипания»).
  const c2 = {
    activeTab: 'relations', activeChatId: -100, chatLoreProfile: null,
    relationsBusy: false, relationsEnabled: false, chatLore409: null,
    toasts: [],
    toast(m, k) { this.toasts.push([m, k]); },
    loreErrText() { return 'err'; },
    applyLoreProfile() {},
    async api() {
      const e = new Error('conflict');
      e.status = 409; e.message = { code: 'conflict', current_updated_at: 'x' };
      throw e;
    },
  };
  await methods.toggleRelationsEnabled.call(c2, true);
  assert.strictEqual(c2.relationsEnabled, false,
    'T-1895c: 409 → откат к прежнему состоянию');
  assert.ok(c2.chatLore409 && c2.chatLore409.code === 'conflict',
    'T-1895c: 409 → окно конфликта заполнено');
  assert.strictEqual(c2.relationsBusy, false, 'T-1895c: busy сброшен и при 409');

  // Прочая ошибка: откат + тост.
  const c3 = {
    activeTab: 'relations', activeChatId: -100, chatLoreProfile: null,
    relationsBusy: false, relationsEnabled: true, chatLore409: null,
    toasts: [],
    toast(m, k) { this.toasts.push([m, k]); },
    loreErrText() { return 'boom'; },
    applyLoreProfile() {},
    async api() { const e = new Error('boom'); e.status = 500; throw e; },
  };
  await methods.toggleRelationsEnabled.call(c3, false);
  assert.strictEqual(c3.relationsEnabled, true,
    'T-1895c: ошибка → откат');
  assert.ok(c3.toasts.length >= 1, 'T-1895c: ошибка → тост');
  // onRelationsToggle: busy → визуальная синхронизация без запроса.
  const ev = { target: { checked: true } };
  methods.onRelationsToggle.call(
    { relationsBusy: true, relationsEnabled: false, toggleRelationsEnabled() {
      throw new Error('не должен звать');
    } }, ev);
  assert.strictEqual(ev.target.checked, false,
    'T-1895c: busy → чекбокс синхронизирован без запроса');
})();

// ── T-1896: досье — open/load/save/close (аддитивный контракт) ────────────
(async function () {
  const calls = [];
  const c = {
    activeChatId: -100, dossierOpen: false, dossierBusy: false,
    dossierUserId: null, dossierName: '', dossierData: null,
    dossierDraft: '', dossierSaving: false,
    toasts: [], toast(m) { this.toasts.push(m); },
    loreErrText() { return 'err'; },
    resolveRelationName() { return 'Толян'; },
    loadDossier: methods.loadDossier,
    async api(url, opts) {
      calls.push({ url, opts });
      return { user_id: 5, name: 'Толян', extracted: '[Факты]\n1. x',
               manual_traits: 'любит мемы', facts: ['x'], links: [] };
    },
  };
  await methods.openDossier.call(c, { user_id: 5 });
  assert.strictEqual(c.dossierOpen, true, 'T-1896: модалка досье открыта');
  assert.strictEqual(c.dossierUserId, 5, 'T-1896: user_id — ключ (R16)');
  assert.ok(calls[0].url.indexOf('/chat_lore/-100/dossier/5') >= 0,
    'T-1896: GET досье по user_id');
  assert.strictEqual(c.dossierDraft, 'любит мемы', 'T-1896: черновик из API');

  calls.length = 0;
  c.dossierDraft = 'новые черты';
  await methods.saveDossier.call(c);
  assert.strictEqual(calls[0].opts.method, 'PUT', 'T-1896: сохранение — PUT');
  assert.deepStrictEqual(JSON.parse(calls[0].opts.body), { traits: 'новые черты' },
    'T-1896: аддитивное тело {traits}');
  methods.closeDossier.call(c);
  assert.strictEqual(c.dossierOpen, false, 'T-1896: модалка закрыта');
  assert.strictEqual(c.dossierDraft, '', 'T-1896: черновик сброшен');
  // Esc закрывает досье первым.
  let closed = 0;
  methods.escClose.call({ dossierOpen: true, closeDossier() { closed += 1; },
    openModuleId: null, accessOpen: null });
  assert.strictEqual(closed, 1, 'T-1896: Esc закрывает досье');
})();

// ── T-1897: «Живая лента досье» — модель/реактивность/polling ─────────────
(async function () {
  const loop = computed.dossierFeedLoop.call({
    dossierFeed: [
      { chat_id: -100, name: 'A', excerpt: 'факт A' },
      { chat_id: -200, name: 'B', excerpt: 'факт B' },
    ],
    oversightData: { chats: [{ chat_id: -100, title: 'Чат А' }] },
  });
  assert.strictEqual(loop.length, 4, 'T-1897: лента дублируется (2×2)');
  assert.strictEqual(loop[0].chatLabel, 'Чат А', 'T-1897: подпись чата из кэша');
  assert.strictEqual(loop[1].chatLabel, 'Чат -200',
    'T-1897: неизвестный чат → id');
  assert.ok(loop[0].key !== loop[2].key, 'T-1897: ключи дублей уникальны');

  const calls = [];
  const c = {
    activeChatId: -100, dossierFeedBusy: false, dossierFeed: [],
    dossierFeedError: '', dossierFeedTimer: null,
    loreErrText() { return 'err'; },
    stopDossierFeedPolling: methods.stopDossierFeedPolling,
    loadDossierFeed: methods.loadDossierFeed,
    async api(url) { calls.push(url); return { items: [{ chat_id: -100, name: 'A', excerpt: 'x' }] }; },
  };
  await methods.loadDossierFeed.call(c);
  assert.strictEqual(calls.length, 1, 'T-1897: один запрос ленты');
  assert.ok(calls[0].indexOf('chat_id=-100') >= 0,
    'T-1897: конкретный чат → фильтр chat_id в запросе');
  assert.strictEqual(c.dossierFeed.length, 1, 'T-1897: лента заполнена');
  // GLOBAL (нет чата) → без chat_id.
  calls.length = 0;
  c.activeChatId = null;
  await methods.loadDossierFeed.call(c);
  assert.ok(calls[0].indexOf('chat_id=') < 0, 'T-1897: GLOBAL → все чаты');

  // Polling lifecycle (setInterval stub).
  const realSet = global.setInterval, realClear = global.clearInterval;
  let intervalCalls = 0, cleared = 0;
  global.setInterval = function () { intervalCalls += 1; return 42; };
  global.clearInterval = function () { cleared += 1; };
  try {
    methods.startDossierFeedPolling.call(c);
    assert.strictEqual(intervalCalls, 1, 'T-1897: polling запущен');
    methods.stopDossierFeedPolling.call(c);
    assert.strictEqual(cleared, 1, 'T-1897: polling остановлен');
    assert.strictEqual(c.dossierFeedTimer, null, 'T-1897: таймер очищен');
  } finally {
    global.setInterval = realSet; global.clearInterval = realClear;
  }
})();

// ── T-1900: sticky-save — dirty/cancel/save (не перезатирает тумблеры) ────
(async function () {
  const ctx = {
    configSnapshot: {},
    configItems: [
      { key: 'models.llm_model_name', value: 'old', secret: false, per_chat: true },
      { key: 'keys.x_api_key', value: { configured: true }, secret: true },
    ],
    keyDrafts: {},
    toast() {},
    canEditConfig() { return true; },
    _serializeValue: methods._serializeValue,
    _snapshotConfig: methods._snapshotConfig,
  };
  methods._snapshotConfig.call(ctx);
  // Вычисляемые свойства в реальном Vue резолвятся через `this.dirtyItems`;
  // в стабе подставляем их явно (как это делает Vue-инстанс).
  const sync = () => {
    ctx.dirtyItems = computed.dirtyItems.call(ctx);
    ctx.dirtyKeyItems = computed.dirtyKeyItems.call(ctx);
  };
  sync();
  assert.strictEqual(ctx.dirtyItems.length, 0, 'T-1900: baseline чист');
  assert.strictEqual(computed.stickyDirtyCount.call(ctx), 0,
    'T-1900: dirty-count = 0');

  ctx.configItems[0].value = 'new';
  sync();
  assert.strictEqual(ctx.dirtyItems.length, 1, 'T-1900: правка инпута → dirty');
  assert.strictEqual(computed.stickyDirtyCount.call(ctx), 1,
    'T-1900: счётчик отражает правку');
  // Авто-сохранённый тумблер (value изменился ДО snapshot) НЕ перезатирается.
  ctx.configItems.push({ key: 'flags.toggle', value: true, secret: false });
  ctx.configSnapshot['flags.toggle'] = 'true';
  assert.strictEqual(computed.dirtyItems.call(ctx).length, 1,
    'T-1900: авто-сохранённый тумблер не попадает в dirty');

  // Отмена — возврат к baseline.
  methods.cancelModalEdits.call(ctx);
  assert.strictEqual(ctx.configItems[0].value, 'old', 'T-1900: «Отмена» откатывает');

  // Секрет: draft → dirtyKeyItems.
  ctx.keyDrafts['keys.x_api_key'] = 'secret123';
  assert.strictEqual(computed.dirtyKeyItems.call(ctx).length, 1,
    'T-1900: черновик секрета → dirtyKeyItems');

  // Сохранение: вызывает saveConfigItem/saveKeyItem по dirty-списку.
  const saved = [];
  const s = {
    stickySaving: false, keyDrafts: ctx.keyDrafts,
    configSnapshot: ctx.configSnapshot, configItems: ctx.configItems,
    canEditConfig() { return true; },
    _serializeValue: methods._serializeValue,
    _snapshotConfig: methods._snapshotConfig,
    toast() {},
    async saveConfigItem(it) { saved.push('cfg:' + it.key); },
    async saveKeyItem(it) { saved.push('key:' + it.key); },
  };
  s.configItems[0].value = 'new';        // правка инпута
  s.keyDrafts['keys.x_api_key'] = 'secret123';
  s.dirtyItems = computed.dirtyItems.call(s);
  s.dirtyKeyItems = computed.dirtyKeyItems.call(s);
  await methods.saveModalEdits.call(s);
  assert.ok(saved.indexOf('cfg:models.llm_model_name') >= 0,
    'T-1900: sticky-панель сохраняет dirty-инпуты');
  assert.ok(saved.indexOf('key:keys.x_api_key') >= 0,
    'T-1900: sticky-панель сохраняет черновики ключей');

  // Компонент зарегистрирован + разметка модалки/вкладки.
  assert.ok(global.__components && global.__components['sticky-save'],
    'T-1900: компонент sticky-save зарегистрирован');
  // S10.20-1 (High): панель обязана быть в КАЖДОЙ ветке, где убраны
  // точечные кнопки (config / modules / access) — иначе сохранение сломано.
  const branchStart = (m) => INDEX.indexOf(m);
  const configBranch = INDEX.slice(branchStart('currentTabIsConfig'),
    branchStart("activeTab === 'modules'"));
  const modulesBranch = INDEX.slice(branchStart("activeTab === 'modules'"),
    branchStart("activeTab === 'oversight'"));
  const accessBranch = INDEX.slice(branchStart("activeTab === 'access'"),
    branchStart("activeTab === 'relations'"));
  assert.ok(configBranch.indexOf('<sticky-save') >= 0,
    'S10.20-1: панель в config-ветке');
  assert.ok(modulesBranch.indexOf('<sticky-save') >= 0,
    'S10.20-1: панель в модалке «Модулей»');
  assert.ok(accessBranch.indexOf('<sticky-save') >= 0,
    'S10.20-1: панель во вкладке «Доступы»');

  // S10.20-6: ошибка сохранения НЕ сдвигает baseline (не «благословляется»).
  const failCtx = {
    stickySaving: false, stickyFailed: [], keyDrafts: {},
    configSnapshot: {}, configItems: [{ key: 'a', value: 'x' }],
    canEditConfig() { return true; },
    _serializeValue: methods._serializeValue,
    _snapshotConfig: methods._snapshotConfig,
    toast() {},
    async saveConfigItem() { return false; },
    async saveKeyItem() { return true; },
  };
  methods._snapshotConfig.call(failCtx);        // baseline: a='x'
  failCtx.configItems[0].value = 'y';
  failCtx.dirtyItems = computed.dirtyItems.call(failCtx);
  failCtx.dirtyKeyItems = [];
  await methods.saveModalEdits.call(failCtx);
  assert.strictEqual(failCtx.configSnapshot['a'], JSON.stringify('x'),
    'S10.20-6: baseline не сдвинулся при ошибке');
  assert.strictEqual(failCtx.stickyFailed.length, 1,
    'S10.20-6: провал записан для панели');
})();

// ── T-1901/T-1902/T-1898/T-1899: маркеры UI-канона ────────────────────────
(function () {
  const CSS = fs.readFileSync(
    path.join(__dirname, '..', '..', 'web', 'static', 'app.css'), 'utf8');
  assert.ok(CSS.indexOf('--glass-bg: rgba(20, 25, 30, 0.5)') >= 0,
    'T-1898/UPD3: токен --glass-bg');
  assert.ok(CSS.indexOf('--glass-border') >= 0, 'T-1898: токен --glass-border');
  assert.ok(CSS.indexOf('backdrop-filter: var(--glass-blur)') >= 0,
    'T-1898/UPD3: backdrop-filter: blur(16px)');
  assert.ok(CSS.indexOf('repeat(auto-fit, minmax(320px, 1fr))') >= 0,
    'T-1899/UPD3: CSS Grid auto-fit minmax(320px)');
  assert.ok(CSS.indexOf('justify-content: center') >= 0,
    'T-1899: центровка сетки');
  assert.ok(CSS.indexOf('details.advanced') >= 0, 'T-1902: рестайл аккордеона');
  assert.ok(CSS.indexOf('@media (prefers-reduced-motion: reduce)') >= 0,
    'T-1898: prefers-reduced-motion');
  assert.ok(INDEX.indexOf('Расширенные системные') >= 0,
    'T-1902: семантический заголовок Advanced');
  assert.ok(INDEX.indexOf('▶ Расширенные настройки') < 0,
    'T-1902: старый нативный «▶»-аккордеон заменён');
})();

console.log('JS-UNIT-OK');
