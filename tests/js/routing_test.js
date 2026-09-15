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

// ── F3 (10.14 persona-ui-tab-round1014): special-screen #/ai/persona ───────
(function () {
  // routeToTab('#/ai/persona') == 'persona' (через applyRoute).
  const ctx = makeCtx(['status', 'persona']);
  ctx.personaLoading = false;
  methods.applyRoute.call(ctx, '#/ai/persona');
  assert.strictEqual(ctx.route, '#/ai/persona',
    'F3: маршрут #/ai/persona открывается');
  assert.strictEqual(ctx.activeTab, 'persona',
    'F3: routeToTab(#/ai/persona) == persona');
  assert.strictEqual(ctx.accessOpen, null,
    'F3: persona-роут не трогает accessOpen');

  // routeParent('#/ai/persona') == '#/ai' (через goBack).
  const back = { route: '#/ai/persona', navigateTo(r) { this._nav = r; } };
  methods.goBack.call(back);
  assert.strictEqual(back._nav, '#/ai',
    'F3: routeParent(#/ai/persona) == #/ai');

  // setTab('persona') триггерит loadPersona (по образцу info).
  let loaded = 0;
  const st = {
    copiedTimer: null, copiedIndex: null, activeTab: 'llm_providers',
    configSearch: '', currentTab: null, gateInfo: null,
    canViewTab() { return true; },
    loadPersona() { loaded += 1; },
    stopStatusPolling() {}, stopCognitionPolling() {},
    destroyCognitionGraph() {},
    $nextTick(cb) { if (cb) cb(); },
  };
  methods.setTab.call(st, 'persona');
  assert.strictEqual(st.activeTab, 'persona', 'F3: setTab(persona) переключил');
  assert.strictEqual(loaded, 1, 'F3: setTab(persona) → loadPersona()');

  // canViewTab('persona'): global admin видит; без чата у обычного юзера — нет.
  assert.strictEqual(methods.canViewTab.call({
    isGlobalAdmin: true, activeChatId: null,
    permissions: {}, hasPerm: methods.hasPerm,
    isLocalAdminCtx() { return false; },
  }, 'persona'), true, 'F3: global admin видит «Личность»');
  assert.strictEqual(methods.canViewTab.call({
    isGlobalAdmin: false, activeChatId: null,
    permissions: {}, hasPerm: methods.hasPerm,
    isLocalAdminCtx() { return false; },
  }, 'persona'), false, 'F3: глобальный скоуп без прав — скрыт');
  assert.strictEqual(methods.canViewTab.call({
    isGlobalAdmin: false, activeChatId: -100,
    permissions: { actions: ['edit_persona'] }, hasPerm: methods.hasPerm,
    isLocalAdminCtx() { return false; },
  }, 'persona'), true, 'F3: chat-scope + edit_persona — виден');
  // R10.14-1: глобальный экран доступен роли-редактору без выбранного чата.
  assert.strictEqual(methods.canViewTab.call({
    isGlobalAdmin: false, activeChatId: null,
    permissions: { actions: ['edit_persona'] }, hasPerm: methods.hasPerm,
    isLocalAdminCtx() { return false; },
  }, 'persona'), true, 'R10.14-1: global + edit_persona — виден');
})();

// ── F3: loadPersona scope-реактивность (устаревший ответ отброшен) ────────
(async function () {
  let resolvePersona;
  const c = {
    scopeEpoch: 1, personaLoading: false, personaMeta: null, personaDraft: null,
    toast() {},
    api: () => new Promise((res) => { resolvePersona = res; }),
    _scopeGuard: methods._scopeGuard,
  };
  const p = methods.loadPersona.call(c);
  c.scopeEpoch = 2;   // смена чата, ответ в полёте
  resolvePersona({ scope: 'chat', chat_id: -100, is_global: true,
    values: { name: 'old', biography: '', system_prompt_overrides: '',
              is_aware_ai: false } });
  await p;
  assert.strictEqual(c.personaDraft, null,
    'F3: устаревший persona-ответ не применён');
  assert.strictEqual(c.personaMeta, null,
    'F3: устаревший persona-meta не применён');

  let resolve2;
  const c2 = {
    scopeEpoch: 5, personaLoading: false, personaMeta: null, personaDraft: null,
    toast() {},
    api: () => new Promise((res) => { resolve2 = res; }),
    _scopeGuard: methods._scopeGuard,
  };
  const p2 = methods.loadPersona.call(c2);
  resolve2({ scope: 'chat', chat_id: -100, is_global: false,
    values: { name: 'Костик', biography: 'био',
              system_prompt_overrides: 'характер', is_aware_ai: true } });
  await p2;
  assert.deepStrictEqual(c2.personaDraft, {
    name: 'Костик', biography: 'био',
    system_prompt_overrides: 'характер', is_aware_ai: true,
  }, 'F3: актуальный persona-ответ применён в свой скоуп');
  assert.strictEqual(c2.personaLoading, false, 'F3: loading сброшен');
})();

// ── F6 (help-guide-integration-round1014): Markdown-гайд ──────────────────
(function () {
  const md = methods.renderGuideMarkdown;
  assert.strictEqual(typeof md, 'function', 'F6: renderGuideMarkdown есть');
  assert.strictEqual(md('# Привет'), '<h1>Привет</h1>', 'F6: заголовок');
  assert.strictEqual(md('**жирный**'), '<p><b>жирный</b></p>', 'F6: жирный');
  assert.strictEqual(md('*курсив*'), '<p><i>курсив</i></p>', 'F6: курсив');
  assert.strictEqual(md('`код`'), '<p><code>код</code></p>', 'F6: код');
  assert.strictEqual(md('- раз\n- два'),
    '<ul><li>раз</li><li>два</li></ul>', 'F6: список');
  assert.strictEqual(md('[ok](https://example.com)'),
    '<p><a href="https://example.com" target="_blank" rel="noopener">ok</a></p>',
    'F6: http(s)-ссылка');
  // javascript:-ссылка НЕ превращается в <a>
  const jsLink = md('[x](javascript:alert(1))');
  assert.ok(jsLink.indexOf('<a ') < 0, 'F6: javascript: — не ссылка');
  // HTML экранируется — теги не проходят
  const xss = md('<script>alert(1)</script>');
  assert.ok(xss.indexOf('<script') < 0, 'F6: script не проходит');
  assert.ok(xss.indexOf('&lt;script&gt;') >= 0, 'F6: script как текст');
  const img = md('<img src=x onerror=alert(1)>');
  assert.ok(img.indexOf('<img') < 0, 'F6: img/onerror не проходит');
})();

// ── F6: sanitizeHtml fail-closed (без DOMPurify → экранированный текст) ───
(function () {
  const out = methods.sanitizeHtml('<b>ok</b><script>alert(1)</script>');
  assert.ok(out.indexOf('<script') < 0,
    'F6: sanitize без DOMPurify экранирует');
  assert.ok(out.indexOf('&lt;script&gt;') >= 0, 'F6: script как текст');
})();

// ── F6: guide state/computed/methods присутствуют ─────────────────────────
(function () {
  ['loadGuide', 'saveGuide', 'toggleGuideEditor'].forEach(function (n) {
    assert.strictEqual(typeof methods[n], 'function', 'F6: methods.' + n);
  });
  ['sanitizedGuideHtml', 'sanitizedGuidePreviewHtml'].forEach(function (n) {
    assert.strictEqual(typeof computed[n], 'function', 'F6: computed.' + n);
  });
})();

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
  // S10.18-22: closeModule вне «Статуса» зовёт stopCognitionPolling —
  // контекст даёт стаб (как реальный Vue-инстанс).
  let stops = 0;
  const ctx = { openModuleId: 'mod_sleep', activeTab: 'status',
    stopCognitionPolling() { stops += 1; } };
  methods.closeModule.call(ctx);
  assert.strictEqual(ctx.openModuleId, null,
    'MODERATE-2: closeModule закрывает модалку');
  assert.strictEqual(stops, 0,
    'S10.18-22: на «Статусе» closeModule polling не трогает');
  const ctxOff = { openModuleId: 'mod_sleep', activeTab: 'modules',
    stopCognitionPolling() { stops += 1; } };
  methods.closeModule.call(ctxOff);
  assert.strictEqual(stops, 1,
    'S10.18-22: вне «Статуса» closeModule останавливает polling');
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
    assert.deepStrictEqual(
      ids.filter((id) => id.indexOf('llm_guard') < 0
        && id.indexOf('search_keys') < 0 && id.indexOf('media_share') < 0),
      ['direct', 'transcription', 'video_summary', 'embeddings',
       'intel_history', 'intel_background', 'intel_reflection'],
      '10.13 (F4) + 10.14 (F8): merged intel-блоки в «Подключениях»');
    // 10.12: parent-блоки несут subBlocks; id'ы подблоков сохранены.
    const byId = {};
    blocks.forEach((b) => { byId[b.id] = b; });
    assert.deepStrictEqual(byId.direct.subBlocks.map((sb) => sb.id),
      ['direct_main', 'direct_fallback'],
      '10.12: direct = Основная/Запасная модель');
    assert.deepStrictEqual(byId.transcription.subBlocks.map((sb) => sb.id),
      ['transcribe_groq', 'transcribe_openrouter'],
      '10.12: transcription = Модель/Запасная транскрибации');
    assert.deepStrictEqual(byId.video_summary.subBlocks.map((sb) => sb.id),
      ['video_summary_openrouter', 'video_fallback'],
      '2.4: запасная видео-модель сразу под основной');
    assert.deepStrictEqual(byId.embeddings.subBlocks.map((sb) => sb.id),
      ['embeddings_main', 'embeddings_fallback1', 'embeddings_fallback2'],
      '2.3: ровно 3 подблока в порядке Основная/Ф1/Ф2');
    // 10.12: новый STT display-name (не общий с видео).
    assert.ok(byId.transcription.subBlocks[1].fields.some(
      (f) => f.key === 'models.openrouter_transcribe_display_name'),
      '10.12: резерв STT использует отдельный display-name');
    // 10.12 (OD-1): embeddings_main — СВОЙ base_url/ключ.
    const embMain = byId.embeddings.subBlocks[0];
    assert.ok(embMain.fields.some((f) => f.key === 'models.embedding_base_url'),
      '10.12: embeddings_main использует models.embedding_base_url');
    assert.ok(embMain.fields.some((f) => f.key === 'keys.embedding_api_key'),
      '10.12: embeddings_main использует keys.embedding_api_key');
    const emb = byId.embeddings;
    assert.ok(emb && emb.subBlocks, '2.3: блок эмбеддингов — subBlocks');
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
    assert.ok(covered['models.embedding_base_url'],
      '10.12: новый embed-base покрыт (нет generic-дубля)');
    assert.ok(covered['keys.embedding_api_key'],
      '10.12: новый embed-ключ покрыт (нет generic-дубля)');
    assert.ok(covered['models.openrouter_transcribe_display_name'],
      '10.12: новый STT display-name покрыт (нет generic-дубля)');
    // ── 10.13 (F4, ADR-1013-1 §2.3): два выделенных LLM Интеллекта ────────
    assert.deepStrictEqual(byId.intel_history.subBlocks.map((sb) => sb.id),
      ['intel_history_main'], 'F4: intel_history = один подблок');
    assert.deepStrictEqual(byId.intel_background.subBlocks.map((sb) => sb.id),
      ['intel_background_main'], 'F4: intel_background = один подблок');
    const intelHistory = byId.intel_history.subBlocks[0];
    const intelBg = byId.intel_background.subBlocks[0];
    assert.ok(intelHistory.fields.some(
      (f) => f.key === 'models.intel_history_display_name' && f.role === ''),
      'F4: display-name первым полем (role "")');
    assert.ok(intelHistory.fields.some(
      (f) => f.key === 'models.intel_history_base_url' && f.role === 'base_url'),
      'F4: base_url с ролью base_url');
    assert.ok(intelHistory.fields.some(
      (f) => f.key === 'models.intel_history_model_name' && f.role === 'model'),
      'F4: модель с ролью model');
    assert.ok(intelHistory.fields.some(
      (f) => f.key === 'keys.intel_history_api_key' && f.role === 'api_key'
        && f.secret === true),
      'F4: ключ — секрет с ролью api_key');
    assert.ok(intelBg.fields.some((f) => f.key === 'models.intel_bg_base_url'),
      'F4: bg base_url');
    assert.ok(intelBg.fields.some((f) => f.key === 'models.intel_bg_model_name'),
      'F4: bg model');
    assert.ok(intelBg.fields.some((f) => f.key === 'keys.intel_bg_api_key'
      && f.secret === true), 'F4: bg ключ');
    // parent modules ≠ title → blockDisplayName не дублирует заголовок.
    ['intel_history', 'intel_background'].forEach((id) => {
      const b = byId[id];
      assert.ok(b.modules && b.modules !== b.title,
        'F4: parent modules ≠ title (R10.12-5)');
      const dn = methods.blockDisplayName.call(
        { blockDrafts: {}, configItems: [], blockFieldValue: methods.blockFieldValue },
        b);
      assert.strictEqual(dn, b.modules,
        'F4: без display-значения подпись = modules (не title)');
    });
    // Все 8 новых ключей покрыты рекурсивным providerCoveredKeys.
    [
      'models.intel_history_display_name', 'models.intel_history_base_url',
      'models.intel_history_model_name', 'keys.intel_history_api_key',
      'models.intel_bg_display_name', 'models.intel_bg_base_url',
      'models.intel_bg_model_name', 'keys.intel_bg_api_key',
    ].forEach((k) => {
      assert.ok(covered[k], 'F4: ключ ' + k + ' покрыт (нет generic-дубля)');
    });
    // ── 10.14 (F8): третье подключение — LLM саморефлексии ────────────────
    assert.ok(byId.intel_reflection, 'F8: parent-блок intel_reflection есть');
    assert.deepStrictEqual(byId.intel_reflection.subBlocks.map((sb) => sb.id),
      ['intel_reflection_main'], 'F8: intel_reflection = один подблок');
    const reflection = byId.intel_reflection.subBlocks[0];
    assert.strictEqual(reflection.fields.length, 4,
      'F8: ровно 4 поля подключения');
    assert.ok(reflection.fields.some(
      (f) => f.key === 'models.intel_reflection_display_name'
        && f.role === ''),
      'F8: display-name первым полем (role "")');
    assert.ok(reflection.fields.some(
      (f) => f.key === 'models.intel_reflection_base_url'
        && f.role === 'base_url'),
      'F8: base_url с ролью base_url');
    assert.ok(reflection.fields.some(
      (f) => f.key === 'models.intel_reflection_model_name'
        && f.role === 'model'),
      'F8: модель с ролью model');
    assert.ok(reflection.fields.some(
      (f) => f.key === 'keys.intel_reflection_api_key' && f.role === 'api_key'
        && f.secret === true),
      'F8: ключ — секрет с ролью api_key');
    // parent modules ≠ title → blockDisplayName не дублирует заголовок.
    assert.ok(byId.intel_reflection.modules
      && byId.intel_reflection.modules !== byId.intel_reflection.title,
      'F8: parent modules ≠ title (R10.12-5)');
    const reflDn = methods.blockDisplayName.call(
      { blockDrafts: {}, configItems: [], blockFieldValue: methods.blockFieldValue },
      byId.intel_reflection);
    assert.strictEqual(reflDn, byId.intel_reflection.modules,
      'F8: без display-значения подпись = modules (не title)');
    [
      'models.intel_reflection_display_name', 'models.intel_reflection_base_url',
      'models.intel_reflection_model_name', 'keys.intel_reflection_api_key',
    ].forEach((k) => {
      assert.ok(covered[k], 'F8: ключ ' + k + ' покрыт (нет generic-дубля)');
    });
  }

  // ── 10.12 (ADR-1012-1 D2): глобальные provider-ключи → api global:true ──
  {
    const calls = [];
    const ctx = {
      blockSaving: {}, blockDrafts: { 'models.llm_base_url': 'https://new/v1' },
      configItems: [{ key: 'models.llm_base_url', type: 'str', per_chat: false }],
      configChatUpdatedAt: 123, toast() {}, loadConfig() {},
      async api(url, opts) { calls.push(opts); return {}; },
    };
    const b = { id: 'direct_main', title: 'T', fields: [
      { key: 'models.llm_base_url', role: 'base_url' }] };
    await methods.saveBlock.call(ctx, b);
    assert.strictEqual(calls.length, 1, '10.12: один POST');
    assert.strictEqual(calls[0].global, true,
      '10.12: per_chat=false → global:true (без X-Chat-Id)');
    assert.strictEqual(JSON.parse(calls[0].body).updated_at, null,
      '10.12: global-ветка без optimistic-метки чата');
  }
  // ── 10.12: смешанный блок → 2 запроса (chat + global) ──────────────────
  {
    const calls = [];
    const ctx = {
      blockSaving: {},
      blockDrafts: { 'models.llm_base_url': 'https://g/v1', 'flags.x': true },
      configItems: [
        { key: 'models.llm_base_url', type: 'str', per_chat: false },
        { key: 'flags.x', type: 'bool', per_chat: true },
      ],
      configChatUpdatedAt: 5, toast() {}, loadConfig() {},
      async api(url, opts) { calls.push(opts); return {}; },
    };
    const b = { id: 'mix', title: 'M', fields: [
      { key: 'models.llm_base_url', role: 'base_url' },
      { key: 'flags.x', role: '' }] };
    await methods.saveBlock.call(ctx, b);
    assert.strictEqual(calls.length, 2, '10.12: смешанный блок → 2 запроса');
    assert.ok(calls.some((c) => c.global === true), '10.12: есть global-запрос');
    assert.ok(calls.some((c) => c.global !== true), '10.12: есть chat-запрос');
  }
  // ── 10.12: saveConfigItem per_chat=false → global:true ──────────────────
  {
    const calls = [];
    const ctx = {
      saving: new Set(), configChatUpdatedAt: 7, toast() {}, loadConfig() {},
      async api(url, opts) { calls.push(opts); return {}; },
    };
    await methods.saveConfigItem.call(ctx,
      { key: 'models.llm_base_url', type: 'str', value: 'x', per_chat: false });
    assert.strictEqual(calls[0].global, true,
      '10.12: saveConfigItem per_chat=false → global:true');
    assert.strictEqual(JSON.parse(calls[0].body).updated_at, null,
      '10.12: global-ветка saveConfigItem без optimistic-метки');
  }
  // ── 10.12 Scanner LOW: saveKeyItem keys.* → global:true (не 422) ────────
  {
    const calls = [];
    const ctx = {
      keyDrafts: { 'keys.checkup_betterstack_sql_password': 'new-secret' },
      configChatUpdatedAt: 42, saving: new Set(),
      toast() {}, loadConfig() {},
      async api(url, opts) { calls.push(opts); return {}; },
    };
    await methods.saveKeyItem.call(ctx,
      { key: 'keys.checkup_betterstack_sql_password', title: 'Пароль',
        per_chat: false });
    assert.strictEqual(calls.length, 1, '10.12: saveKeyItem один POST');
    assert.strictEqual(calls[0].global, true,
      '10.12: keys.* (per_chat=false) → global:true (без X-Chat-Id)');
    assert.strictEqual(JSON.parse(calls[0].body).updated_at, null,
      '10.12: global-ветка saveKeyItem без optimistic-метки');
    assert.strictEqual(
      ctx.keyDrafts['keys.checkup_betterstack_sql_password'], '',
      '10.12: draft ключа очищается после успеха');
  }
  // ── F3/D-3 (ревью Батча C): OFF тумблера безлимита — явные дефолты ──────
  {
    const calls = [];
    const globalValues = {
      'limits.chat_global_key_budget_requests': 100,
      'limits.chat_global_key_budget_tokens': 500000,
      'limits.worker_daily_llm_calls_per_chat': 60,
      'limits.worker_daily_llm_tokens_per_chat': 300000,
      'limits.chat_global_context_max_tokens': null,
      'limits.chat_thread_max_tokens': null,
      'limits.chat_context_budget_tokens': 4000,
    };
    const ctx = {
      isChatContext() { return true; },
      budgetsUnlimitedKeys: methods.budgetsUnlimitedKeys,
      _budgetItem(key) { return { key: key, global_value: globalValues[key] }; },
      configChatUpdatedAt: 11,
      budgetsUnlimitedBusy: false,
      toast() {}, loadConfig() {}, loadKeyStatus() {},
      _preserveScroll(fn) { return fn && fn.call(this); },
      async api(url, opts) { calls.push({ url: url, opts: opts }); return {}; },
    };
    await methods.toggleBudgetsUnlimited.call(ctx, false);
    assert.strictEqual(calls.length, 1, 'D3: OFF — ровно один POST (не 7×DELETE)');
    assert.strictEqual(calls[0].url, '/api/config',
      'D3: OFF пишет через POST /api/config (meta сохраняется)');
    assert.ok(!calls.some((c) => c.opts && c.opts.method === 'DELETE'),
      'D3: DELETE не используется (иначе теряется meta.chat_settings_seed_version)');
    const body = JSON.parse(calls[0].opts.body);
    const byKey = {};
    body.items.forEach((i) => { byKey[i.key] = i.value; });
    assert.strictEqual(byKey['limits.chat_global_key_budget_requests'], 100,
      'D3: бюджет ключа → явный глобальный дефолт');
    assert.strictEqual(byKey['limits.worker_daily_llm_tokens_per_chat'], 300000,
      'D3: бюджет фона → явный глобальный дефолт');
    assert.strictEqual(byKey['limits.chat_global_context_max_tokens'], 0,
      'D3: null (не задано) → 0 = «не задано»');
    assert.strictEqual(JSON.parse(calls[0].opts.body).updated_at, 11,
      'D3: optimistic-метка чата сохранена');
  }
  // ── 10.12 (§2.3): blockDisplayName — трансляция «Название модели» ───────
  {
    const ctx = {
      blockDrafts: {},
      configItems: [{ key: 'models.llm_display_name', value: 'DeepSeek V4' }],
      blockFieldValue: methods.blockFieldValue,
    };
    assert.strictEqual(methods.blockDisplayName.call(ctx, {
      modules: 'Прямые ответы',
      fields: [{ key: 'models.llm_display_name', role: '' }],
    }), 'DeepSeek V4', '10.12: display-name транслируется');
    assert.strictEqual(methods.blockDisplayName.call(ctx, {
      modules: 'Прямые ответы',
      fields: [{ key: 'models.llm_timeout', role: '' }],
    }), 'Прямые ответы', '10.12: нет display-поля → modules');
    assert.strictEqual(methods.blockDisplayName.call(ctx, {
      modules: 'Общий',
      fields: [{ key: 'models.llm_fallback_display_name', role: '' }],
    }), 'Общий', '10.12: пустой display → fallback modules');
    // Scanner LOW follow-up: modules == title → подпись подавлена.
    assert.strictEqual(methods.blockDisplayName.call(ctx, {
      title: 'Прямые ответы', modules: 'Прямые ответы', fields: [],
    }), '', '10.12: modules==title → не дублируем заголовок');
    assert.strictEqual(methods.blockDisplayName.call(ctx, {
      title: 'Эмбеддинги', modules: 'Поиск по памяти', fields: [],
    }), 'Поиск по памяти', '10.12: modules!=title → подпись остаётся');
  }
  // ── 10.12 (ADR-1012-1 D4): list-editor add/remove/save + stable key ─────
  {
    const le = global.__components && global.__components['list-editor'];
    assert.ok(le, '10.12: list-editor зарегистрирован');
    const data = le.data.call({});
    assert.ok(Array.isArray(data.rows) && data.maxRows >= 10,
      '10.12: list-editor rows/maxRows');
    assert.ok(Array.isArray(data.rowIds),
      '10.12: list-editor rowIds (stable :key)');

    const inst = {
      rows: [], maxRows: 100,
      item: { key: 'reactions.kostik_replies',
              value: ['a', ' b ', '', null] },
      root: { toast() {}, saving: new Set(),
              saveConfigItem(item) { inst.saved = item.value; } },
    };
    le.methods.sync.call(inst);
    assert.deepStrictEqual(inst.rows, ['a', ' b ', '', ''],
      '10.12: sync нормализует массив строк');
    assert.strictEqual(inst.rowIds.length, 4, '10.12: rowIds выровнены с rows');
    assert.strictEqual(new Set(inst.rowIds).size, 4,
      '10.12: ключи строк уникальны');
    const beforeIds = inst.rowIds.slice();
    le.methods.addRow.call(inst);
    assert.strictEqual(inst.rows.length, 5, '10.12: addRow добавляет строку');
    assert.strictEqual(inst.rowIds.length, 5, '10.12: addRow добавляет ключ');
    le.methods.removeRow.call(inst, 0);
    assert.strictEqual(inst.rows.length, 4, '10.12: removeRow удаляет строку');
    assert.strictEqual(inst.rowIds.length, 4, '10.12: removeRow удаляет ключ');
    // Удаление НАЧАЛА не переназначает ключи оставшихся строк (стабильность).
    assert.strictEqual(inst.rowIds[0], beforeIds[1],
      '10.12: stable :key — оставшиеся строки сохраняют id');
    inst.rows = [' x ', '', 'y', null];
    inst.root.saveConfigItem = function (item) { inst.saved = item.value; };
    await le.methods.save.call(inst);
    assert.deepStrictEqual(inst.saved, ['x', 'y'],
      '10.12: save отбрасывает пустые и strip');
  }
  // ── 10.12 (ADR-1012-1 D3): owner-блок Костика с фразами/вероятностью ────
  {
    const ctx = {
      groupedForTab() {
        return [{ items: [
          { key: 'reactions.kostik_user_id', group: 'reactions_kostik' },
          { key: 'reactions.kostik_replies', group: 'reactions_kostik' },
          { key: 'limits.kostik_reply_probability', group: 'limits_kostik' },
        ] }];
      },
      _ownerDescription: methods._ownerDescription,
    };
    const owners = methods._permsocOwnerGroups.call(ctx);
    const kostik = owners.filter((o) => o.id === 'kostik')[0];
    assert.ok(kostik, '10.12: owner-блок kostik присутствует');
    assert.strictEqual(kostik.owner.toggleKey, 'flags.kostik_enabled',
      '10.12: тумблер Костика — flags.kostik_enabled');
    const owned = kostik.items.map((i) => i.key);
    assert.ok(owned.indexOf('reactions.kostik_replies') >= 0,
      '10.12: фразы в блоке Костика');
    assert.ok(owned.indexOf('limits.kostik_reply_probability') >= 0,
      '10.12: вероятность в блоке Костика');
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

  // ── F6 (T-1460): EKG-«сердцебиение» — computed, привязка к Load/CPU/RAM.
  {
    const hb = computed.heartbeat;
    assert.strictEqual(typeof hb, 'function', 'F6: heartbeat — computed');
    // Linux: loadavg[0]/cpu_count = 1.0/2 = 0.5 → повышён (оранжевый)
    const elev = hb.call({ statusData: { server: {
      loadavg: [1.0, 0.8, 0.6], cpu_count: 2, cpu_percent: 10,
      memory: { percent: 12 } } } });
    assert.strictEqual(elev.level, 'elev', 'F6: 0.5 → elev');
    assert.strictEqual(elev.badge, 'badge-warn', 'F6: elev → оранжевый');
    assert.strictEqual(elev.period, 1.4, 'F6: elev → период 1.4s');
    // >0.8 → пик (красный), учащённый пульс
    const high = hb.call({ statusData: { server: {
      loadavg: [3.2, 2.0, 1.0], cpu_count: 2 } } });
    assert.strictEqual(high.level, 'high', 'F6: >0.8 → high');
    assert.strictEqual(high.badge, 'badge-err', 'F6: high → красный');
    assert.strictEqual(high.period, 0.8, 'F6: high → период 0.8s');
    // Windows dev: loadavg = null → фолбэк max(CPU%, RAM%)
    const calm = hb.call({ statusData: { server: {
      loadavg: null, cpu_count: 8, cpu_percent: 20,
      memory: { percent: 30 } } } });
    assert.strictEqual(calm.level, 'calm', 'F6: CPU/RAM-фолбэк → calm');
    assert.strictEqual(calm.badge, 'badge-ok', 'F6: calm → зелёный');
    assert.strictEqual(calm.period, 2.4, 'F6: calm → период 2.4s');
    // всё None/нет данных → нейтральный спокойный (не падает)
    const neutral = hb.call({ statusData: { server: {} } });
    assert.strictEqual(neutral.level, 'calm', 'F6: метрик нет → нейтраль');
    assert.strictEqual(hb.call({ statusData: null }).level, 'calm',
      'F6: statusData=null → нейтраль');
  }

  // ── F6 (T-1461/1462): дефолт логов = ERROR+WARNING, единый источник.
  {
    const d = captured.data();
    assert.strictEqual(d.logLevel, 'ERROR+WARNING',
      'F6: дефолт logLevel = ERROR+WARNING (F6-Q4)');
    assert.ok(captured.watch && typeof captured.watch.logLevel === 'function',
      'F6: watch.logLevel — селектор == запрос == рендер');
  }

  // ── F5 (cognition-dashboard-round1013): ленты/бейджи/бюджет/граф ────────
  {
    // ribbonItemClass: центр → 100, край → 50 (opacity по позиции).
    const rc = methods.ribbonItemClass;
    assert.strictEqual(rc(2, 5), 'ribbon-op-100', 'F5: центр ленты op-100');
    assert.strictEqual(rc(0, 5), 'ribbon-op-50', 'F5: край ленты op-50');
    assert.strictEqual(rc(1, 5), 'ribbon-op-75', 'F5: середина op-75');
    assert.strictEqual(rc(0, 1), 'ribbon-op-100', 'F5: один элемент — центр');

    // Бейджи фаз из реального cognition/status (round1015: оконная семантика).
    const dream = computed.dreamPhaseBadge;
    assert.strictEqual(typeof dream, 'function', 'F5: dreamPhaseBadge computed');
    const dCtx = (d) => ({ cognition: { dream: d }, fmtClock: methods.fmtClock,
      fmtCountdown: methods.fmtCountdown });
    const dreamActive = dream.call(
      dCtx({ active: true, active_until: 1740000000 }));
    assert.strictEqual(dreamActive.cls, 'badge-ok glow',
      'F5: активная фаза сна → свечение');
    assert.ok(dreamActive.text.indexOf('🌙 Сон до ') === 0,
      'F5: активная фаза сна → «до HH:MM»');
    assert.strictEqual(dream.call(dCtx({ active: true })).text, '🌙 Сон идёт',
      'F5: активна без active_until → «идёт»');
    assert.strictEqual(
      dream.call(dCtx(
        { state: 'limit_exhausted', next_wake_at: 1740000000 })).cls,
      'badge-warn', 'F5: лимит сна исчерпан → warn');
    assert.strictEqual(
      dream.call({ cognition: null, fmtClock: methods.fmtClock,
        fmtCountdown: methods.fmtCountdown }).text,
      '—', 'F2/S10.17-2: нет данных → чистый «—»');
    const deep = computed.deepPhaseBadge;
    const deepActive = deep.call({
      cognition: { deep_sleep: { active: true, active_until: 1740000000 } },
      fmtClock: methods.fmtClock,
      fmtCountdown: methods.fmtCountdown });
    assert.strictEqual(deepActive.cls, 'badge-info glow',
      'F5: активный глубокий сон → свечение');
    assert.ok(deepActive.text.indexOf('🌌 Глубокий сон до ') === 0,
      'F5: активный глубокий сон → «до HH:MM»');
    assert.strictEqual(deep.call({
      cognition: { deep_sleep: { next_run_at: 1740000000 } },
      fmtClock: methods.fmtClock,
      fmtCountdown: methods.fmtCountdown }).cls, 'badge-muted',
      'F5: вне фазы глубокого сна → без свечения');
    // F3 (round1017): ветка enabled=false удалена; активная фаза — приоритетнее,
    // при enabled=false/active=false — остаток без свечения (UPD3).
    const dreamOff = dream.call(dCtx(
      { enabled: false, active: true, active_until: 1740000000 }));
    assert.ok(dreamOff.text.indexOf('🌙 Сон до ') === 0,
      'F3: активная фаза сна — приоритетнее enabled=false');
    assert.strictEqual(dreamOff.cls, 'badge-ok glow',
      'F3: активный сон светится даже при enabled=false (running)');
    const deepOff = deep.call({
      cognition: { deep_sleep: {
        enabled: false, active: true, active_until: 1740000000 } },
      fmtClock: methods.fmtClock,
      fmtCountdown: methods.fmtCountdown });
    assert.ok(deepOff.text.indexOf('🌌 Глубокий сон до ') === 0,
      'F3: активный глубокий сон — приоритетнее enabled=false');
    assert.strictEqual(deepOff.cls, 'badge-info glow',
      'F3: активный глубокий сон светится даже при enabled=false (running)');

    // Бюджет контекста (аддитивное /api/status.context).
    const mc = computed.memoryContext;
    assert.strictEqual(mc.call({ statusData: null }).used, null,
      'F5: нет данных → used=null');
    assert.strictEqual(mc.call({ statusData: { context: {
      used: 9500, limit: 10000, truncated: false } } }).red, true,
      'F5: >90% → красный');
    assert.strictEqual(mc.call({ statusData: { context: {
      used: 100, limit: 10000, truncated: true } } }).red, true,
      'F5: truncated → красный');
    assert.strictEqual(mc.call({ statusData: { context: {
      used: 100, limit: 10000, truncated: false } } }).red, false,
      'F5: заполнено — не красный');
    // D-7 (10.19): безлимит общего бюджета → «Безлимит (∞)», не 100%.
    const mcUnlimited = mc.call({ statusData: { context: {
      used: 12345, limit: null, unlimited: true, truncated: false } } });
    assert.strictEqual(mcUnlimited.unlimited, true,
      'D-7: безлимит → флаг unlimited');
    assert.strictEqual(mcUnlimited.limit, null,
      'D-7: безлимит → limit=null (не подставляем cap)');
    assert.strictEqual(mcUnlimited.red, false,
      'D-7: безлимит → не красный (нет ложных 100%)');

    // Модель ленты: дублируется для seamless-скролла + op-класс.
    const loop = computed.cognitionBeliefsLoop.call({
      cognitionBeliefs: [{ id: 1, fact: 'a', created_at: 100 },
                         { id: 2, fact: 'b', created_at: 200 }],
      _ribbonLoop: methods._ribbonLoop,
      ribbonItemClass: methods.ribbonItemClass,
    });
    assert.strictEqual(loop.length, 4, 'F5: лента дублируется (2×2)');
    assert.ok(loop[0].op.indexOf('ribbon-op-') === 0,
      'F5: op-класс в модели ленты');
    assert.strictEqual(loop[0].key !== loop[2].key, true,
      'F5: ключи дублей уникальны');

    // Форматтеры виджета.
    assert.strictEqual(methods.fmtTokens.call({}, 45000), '45k',
      'F5: токены → k');
    assert.strictEqual(methods.fmtTokens.call({}, 500), '500',
      'F5: токены < 1000');
    const sil = methods.nostalgiaLabel.call({ cognition: { nostalgia: {
      mode: 'silence', silence_left_min: 25, silence_min_total: 45 } } });
    assert.strictEqual(sil, 'Тишина: 25/45 мин', 'F5: таймер тишины');
    const cd = methods.nostalgiaLabel.call({ cognition: { nostalgia: {
      mode: 'cooldown', cooldown_left_h: 8 } } });
    assert.strictEqual(cd, 'Кулдаун: ещё 8 ч', 'F5: кулдаун');

    // Destroy инстанса vis до повторного рендера (R10.11-5).
    let destroyed = 0;
    const gctx = { cognitionNetwork: { destroy() { destroyed += 1; } } };
    methods.destroyCognitionGraph.call(gctx);
    assert.strictEqual(destroyed, 1, 'F5: network.destroy() вызван');
    assert.strictEqual(gctx.cognitionNetwork, null, 'F5: ссылка очищена');

    // Polling lifecycle (15с; стоп очищает таймер).
    const pctx = { isGlobalAdmin: true, cognitionTimer: null,
                   loadCognition() {}, reducedMotion: false,
                   _startCognitionTimer: methods._startCognitionTimer };
    methods.startCognitionPolling.call(pctx);
    assert.ok(pctx.cognitionTimer != null, 'F5: polling запущен');
    methods.stopCognitionPolling.call(pctx);
    assert.strictEqual(pctx.cognitionTimer, null, 'F5: polling остановлен');
  }

  // ── F3 (sleep-badge-countdown-round1017): fmtCountdown + бейджи
  //    «через остаток» / «до HH:MM» (UPD3; ADR-1017-3) ──────────────────────
  {
    const fc = methods.fmtCountdown;
    assert.strictEqual(typeof fc, 'function',
      'F3: fmtCountdown — метод');
    assert.strictEqual(fc.call({}, 8100), '2ч 15м',
      'F3: fmtCountdown(8100) == 2ч 15м');
    assert.strictEqual(fc.call({}, 900), '15м',
      'F3: fmtCountdown(900) == 15м');
    assert.strictEqual(fc.call({}, 3600), '1ч 0м',
      'F3: fmtCountdown(3600) == 1ч 0м');
    assert.strictEqual(fc.call({}, 0), '0м', 'F3: fmtCountdown(0) == 0м');
    assert.strictEqual(fc.call({}, -30), '0м',
      'F3: отрицательное → кламп 0м');
    assert.strictEqual(fc.call({}, 59), '0м', 'F3: <60с → 0м');
    assert.strictEqual(fc.call({}, 3599), '59м',
      'F3: 3599с → 59м (округление вниз)');
    assert.strictEqual(fc.call({}, null), '—', 'F3: null → —');
    assert.strictEqual(fc.call({}, 'abc'), '—', 'F3: не-число → —');
    assert.strictEqual(fc.call({}, NaN), '—', 'F3: NaN → —');

    const dream = computed.dreamPhaseBadge;
    const deep = computed.deepPhaseBadge;
    const NOW = 1740000000;
    const ctx = (cognition) => Object.assign({ cognition: cognition },
      { fmtClock: methods.fmtClock, fmtCountdown: methods.fmtCountdown });

    // Вне фазы: enabled=false, active=false → остаток, без свечения.
    const dOff = dream.call(ctx({
      generated_at: NOW,
      dream: { enabled: false, active: false, next_wake_at: NOW + 3600 } }));
    assert.strictEqual(dOff.text, '☀️ Сон через 1ч 0м',
      'F3: dream enabled=false вне фазы → «через остаток»');
    assert.strictEqual(dOff.cls, 'badge-muted',
      'F3: dream вне фазы без свечения (нет «выключен»)');
    // 15м при < часа.
    const dQ = dream.call(ctx({
      generated_at: NOW,
      dream: { active: false, next_wake_at: NOW + 900 } }));
    assert.strictEqual(dQ.text, '☀️ Сон через 15м',
      'F3: dream остаток 15м');
    assert.strictEqual(dQ.cls, 'badge-muted', 'F3: dream muted вне фазы');

    // В фазе: glow + «до HH:MM».
    const dA = dream.call(ctx({
      generated_at: NOW,
      dream: { active: true, active_until: NOW + 3600 } }));
    assert.ok(dA.text.indexOf('🌙 Сон до ') === 0,
      'F3: dream active → «до HH:MM»');
    assert.strictEqual(dA.cls, 'badge-ok glow', 'F3: dream active → glow');

    // «Лимит сна исчерпан» сохранён.
    const dL = dream.call(ctx({
      generated_at: NOW,
      dream: { active: false, state: 'limit_exhausted' } }));
    assert.strictEqual(dL.text, '☀️ Лимит сна исчерпан',
      'F3: лимит сна исчерпан сохранён');
    assert.strictEqual(dL.cls, 'badge-warn', 'F3: лимит → badge-warn');

    // deep вне фазы → остаток без свечения.
    const dsOff = deep.call(ctx({
      generated_at: NOW,
      deep_sleep: { enabled: false, active: false, next_run_at: NOW + 900 } }));
    assert.strictEqual(dsOff.text, '🌅 Глубокий сон через 15м',
      'F3: deep enabled=false → «через остаток»');
    assert.strictEqual(dsOff.cls, 'badge-muted',
      'F3: deep вне фазы без свечения (нет «выключен»)');
    // deep в фазе → glow + «до HH:MM».
    const dsA = deep.call(ctx({
      generated_at: NOW,
      deep_sleep: { active: true, active_until: NOW + 3600 } }));
    assert.ok(dsA.text.indexOf('🌌 Глубокий сон до ') === 0,
      'F3: deep active → «до HH:MM»');
    assert.strictEqual(dsA.cls, 'badge-info glow', 'F3: deep active → glow');

    // Нет данных → «—», badge-muted.
    const noData = { cognition: null, fmtClock: methods.fmtClock,
      fmtCountdown: methods.fmtCountdown };
    assert.strictEqual(dream.call(noData).text, '—',
      'F2/S10.17-2: cognition=null → «—»');
    assert.strictEqual(dream.call(noData).cls, 'badge-muted',
      'F2: нет данных → muted');
    assert.strictEqual(deep.call(noData).text, '—',
      'F2/S10.17-2: cognition=null deep → «—»');

    // Отсутствие generated_at → Date.now()/1000, без NaN.
    const noGen = dream.call(ctx({
      dream: { active: false,
        next_wake_at: Math.floor(Date.now() / 1000) + 3600 } }));
    assert.strictEqual(noGen.text, '☀️ Сон через 1ч 0м',
      'F3: нет generated_at → fallback Date.now()/1000, без NaN');

    // Эмодзи не изменены; «выключен» удалён.
    const src = require('fs').readFileSync(
      path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
    ['☀️', '🌙', '🌅', '🌌'].forEach((e) => {
      assert.ok(src.indexOf(e) >= 0, 'F3: эмодзи ' + e + ' присутствует');
    });
    assert.ok(src.indexOf('Сон выключен') < 0,
      'F3: «Сон выключен» удалён');
    assert.ok(src.indexOf('Глубокий сон выключен') < 0,
      'F3: «Глубокий сон выключен» удалён');
  }

  // ── F4 (persona-traits-ribbon-round1014): лента «Эволюция характера»
  //    + метрики Личности (UPD п.4) ─────────────────────────────────────────
  {
    // fmtDayMonth: unix-секунды → 'ДД.ММ' (F4-Q1).
    assert.strictEqual(methods.fmtDayMonth.call({}, 1757750400), '13.09',
      'F4: fmtDayMonth(1757750400) == 13.09');
    assert.strictEqual(methods.fmtDayMonth.call({}, 0), '—',
      'F4: пустой ts → —');

    // _traitsAdapter: {ts,text,source} → {id,fact,created_at}.
    const adapted = methods._traitsAdapter.call({}, [
      { ts: 1757750400, text: 'Стал более циничным', source: 'deep_sleep' },
    ]);
    assert.deepStrictEqual(adapted, [
      { id: 1757750400, fact: 'Стал более циничным', created_at: 1757750400 },
    ], 'F4: адаптер traits {ts,text}→{id,fact,created_at}');
    assert.deepStrictEqual(methods._traitsAdapter.call({}, null), [],
      'F4: не-массив → [] (fail-open)');

    // cognitionTraitsLoop — computed, переиспользует _ribbonLoop.
    assert.strictEqual(typeof computed.cognitionTraitsLoop, 'function',
      'F4: cognitionTraitsLoop — computed');
    const loop = computed.cognitionTraitsLoop.call({
      cognitionTraits: adapted,
      _ribbonLoop: methods._ribbonLoop,
      ribbonItemClass: methods.ribbonItemClass,
    });
    assert.strictEqual(loop.length, 2, 'F4: лента дублируется (1×2)');
    assert.strictEqual(loop[0].fact, 'Стал более циничным',
      'F4: факт в модели ленты');
    assert.ok(loop[0].op.indexOf('ribbon-op-') === 0,
      'F4: op-класс в модели ленты');
    // ribbonItemClass не изменён.
    assert.strictEqual(methods.ribbonItemClass.call({}, 2, 5), 'ribbon-op-100',
      'F4: ribbonItemClass переиспользован без изменений');

    // personaExtractorBadge: статус экстрактора → текст/класс.
    assert.strictEqual(computed.personaExtractorBadge.call(
      { personaHealth: { extractor_status: 'ok' } }).cls, 'badge-ok',
      'F4: экстрактор ok → зелёный');
    assert.strictEqual(computed.personaExtractorBadge.call(
      { personaHealth: { extractor_status: 'error' } }).cls, 'badge-err',
      'F4: экстрактор error → красный');
    assert.ok(computed.personaExtractorBadge.call(
      { personaHealth: null }).text.indexOf('не запускался') >= 0,
      'F4: нет данных → never (fail-open)');
  }

  // ── F5 (settings-persistence-audit-round1014, T-1514): смена scope
  //    сбрасывает optimistic-метку и черновики — не «переезжают» в чат B ──
  (function () {
    const savedLocalStorage = global.localStorage;
    global.localStorage = {
      _s: {},
      getItem(k) { return this._s[k] || null; },
      setItem(k, v) { this._s[k] = String(v); },
      removeItem(k) { delete this._s[k]; },
    };
    const calls = [];
    const ctx = {
      scopeOpen: true,
      activeChatId: 5,
      activeTab: 'status',
      accessChats: [],
      accessMy: null,
      scopeEpoch: 3,
      configItems: [{ key: 'limits.x', value: 1 }],
      configError: 'stale',
      configChatUpdatedAt: 'STALE-TOKEN',
      keyDrafts: { 'keys.llm_api_key': 'secret-from-chat-A' },
      ownKeyDraft: 'chat-A-byok',
      blockDrafts: { 'models.llm_model_name': 'draft-A' },
      blockResults: { direct_main: { ok: true, text: 'A' } },
      personaDraft: { name: 'A' },
      personaMeta: { scope: 'chat' },
      personaLoading: true,
      chatLoreProfile: { x: 1 }, chatLoreSelectedId: 7, chatLoreHistory: [1],
      chatLore409: { code: 'conflict' }, gateInfo: { y: 1 }, chatAdmins: [42],
      permPickerOpen: true, permPickerItem: { k: 1 }, chatRelations: [1],
      relationsEnabled: true, relationsBusy: false,
      canViewTab() { return false; },
      isDmCtx() { return false; },
      syncActiveChatTitle() {},
      loadConfig() { calls.push('config'); },
      loadKeyStatus() { calls.push('keys'); },
      loadGateInfo() { calls.push('gate'); },
      loadLocalAdmins() { calls.push('admins'); },
      loadPersona() { calls.push('persona'); },
      loadRelations() { calls.push('relations'); },
    };
    methods.setActiveChat.call(ctx, 99);
    assert.strictEqual(ctx.activeChatId, 99,
      'F5/T-1514: активный чат переключён');
    assert.strictEqual(ctx.configChatUpdatedAt, null,
      'F5/T-1514: optimistic updated_at сброшен при смене scope');
    assert.deepStrictEqual(ctx.keyDrafts, {},
      'F5/T-1514: черновики ключей не переезжают в другой чат');
    assert.strictEqual(ctx.ownKeyDraft, '',
      'F5/T-1514: BYOK-черновик не переезжает в другой чат');
    assert.deepStrictEqual(ctx.blockDrafts, {},
      'F5/T-1514: черновики блоков сброшены');
    assert.deepStrictEqual(ctx.blockResults, {},
      'F5/T-1514: результаты тестов блоков сброшены');
    assert.strictEqual(ctx.personaDraft, null,
      'F5/T-1514: persona-черновик сброшен');
    assert.strictEqual(ctx.personaMeta, null,
      'F5/T-1514: persona-meta сброшена');
    assert.strictEqual(ctx.scopeEpoch, 4,
      'F5/T-1514: scopeEpoch инкрементнут (отброс in-flight)');
    assert.ok(calls.indexOf('config') >= 0,
      'F5/T-1514: loadConfig вызван для нового скоупа');
    assert.ok(calls.indexOf('keys') >= 0,
      'F5/T-1514: loadKeyStatus вызван для нового скоупа');
    if (savedLocalStorage === undefined) delete global.localStorage;
    else global.localStorage = savedLocalStorage;
  })();

  // ── F2 (graph-frontend-physics-search-round1015, ТЗ §1): физика barnesHut
  //    и «Поиск по графу» ───────────────────────────────────────────────────
  {
    const fs = require('fs');
    const jsSrc = fs.readFileSync(
      path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf-8');
    assert.ok(jsSrc.indexOf("solver: 'barnesHut'") >= 0,
      'F2: physics.solver == barnesHut');
    assert.ok(jsSrc.indexOf('gravitationalConstant: -8000') >= 0,
      'F2: расталкивание gravitationalConstant=-8000');
    assert.ok(jsSrc.indexOf('avoidOverlap: 0.2') >= 0,
      'F2: avoidOverlap=0.2 (не слипаются)');

    // _graphSignature не изменилась: degree входит в подпись (ISSUE-4).
    const sA = methods._graphSignature.call({}, {
      nodes: [{ id: 1, label: 'a', group: 'user', degree: 5 }], edges: [] });
    const sB = methods._graphSignature.call({}, {
      nodes: [{ id: 1, label: 'a', group: 'user', degree: 6 }], edges: [] });
    assert.notStrictEqual(sA, sB, 'F2: degree по-прежнему в подписи');

    function makeNet() {
      const calls = { focus: [], select: [], fit: [] };
      return {
        calls,
        focus(id, opts) { calls.focus.push([id, opts]); },
        selectNodes(ids) { calls.select.push(ids); },
        fit(anim) { calls.fit.push(anim); },
      };
    }
    const nodes = [
      { id: 1, label: 'Олег' },
      { id: 2, label: 'олег_два' },
      { id: 3, label: 'Кот' },
    ];
    function baseCtx(net, extra) {
      return Object.assign({
        graphSearchQuery: '', graphSearchStatus: '',
        cognitionNetwork: net, cognitionGraphData: { nodes },
        reducedMotion: false, _graphSearchMatches: [], _graphSearchIdx: 0,
        _graphSearchLastQ: '',
        toast() {}, renderCognitionGraph: async function () {},
        clearCognitionGraphSearch: methods.clearCognitionGraphSearch,
      }, extra || {});
    }

    // Совпадение по подстроке без регистра + focus/selectNodes.
    let net = makeNet();
    let toasts = [];
    let ctx = baseCtx(net, { graphSearchQuery: 'ОЛЕГ',
      toast(t, k) { toasts.push([t, k]); } });
    await methods.searchCognitionGraph.call(ctx);
    assert.strictEqual(net.calls.focus.length, 1, 'F2: focus вызван');
    assert.strictEqual(net.calls.focus[0][0], 1, 'F2: первое совпадение');
    assert.strictEqual(net.calls.focus[0][1].scale, 1.1, 'F2: масштаб фокуса');
    assert.deepStrictEqual(net.calls.select[0], [1], 'F2: selectNodes');
    assert.strictEqual(ctx.graphSearchStatus.indexOf('Найден'), 0,
      'F2: статус «Найден…»');
    assert.ok(ctx.graphSearchStatus.indexOf('1/2') >= 0,
      'F2: счётчик 1/2');
    // Повторный Enter по тому же запросу → циклический перебор на 2-е.
    await methods.searchCognitionGraph.call(ctx);
    assert.strictEqual(net.calls.focus[1][0], 2, 'F2: перебор на 2-е');
    assert.ok(ctx.graphSearchStatus.indexOf('2/2') >= 0, 'F2: счётчик 2/2');
    // Следующий Enter → цикл замкнулся на первое.
    await methods.searchCognitionGraph.call(ctx);
    assert.strictEqual(net.calls.focus[2][0], 1, 'F2: цикл замкнулся');

    // Пустой ввод → без focus, сброс подсветки + fit().
    net = makeNet();
    ctx = baseCtx(net, { graphSearchQuery: '   ' });
    await methods.searchCognitionGraph.call(ctx);
    assert.strictEqual(net.calls.focus.length, 0, 'F2: пусто → без focus');
    assert.strictEqual(net.calls.fit.length, 1, 'F2: пусто → fit()');
    assert.strictEqual(ctx.graphSearchQuery, '', 'F2: пусто → сброс строки');

    // Нет совпадений → статус + toast(warn), сеть не ломается.
    net = makeNet(); toasts = [];
    ctx = baseCtx(net, { graphSearchQuery: 'зигфрид',
      toast(t, k) { toasts.push([t, k]); } });
    await methods.searchCognitionGraph.call(ctx);
    assert.strictEqual(net.calls.focus.length, 0, 'F2: нет hits → без focus');
    assert.strictEqual(ctx.graphSearchStatus, 'Ничего не найдено',
      'F2: статус «Ничего не найдено»');
    assert.ok(toasts.length === 1 && toasts[0][1] === 'warn',
      'F2: toast(warn) при отсутствии узла');

    // reducedMotion → focus/fit без анимации.
    net = makeNet();
    ctx = baseCtx(net, { graphSearchQuery: 'кот', reducedMotion: true });
    await methods.searchCognitionGraph.call(ctx);
    assert.strictEqual(net.calls.focus[0][1].animation, false,
      'F2: reducedMotion → focus без анимации');
    const rmNet = makeNet();
    methods.clearCognitionGraphSearch.call({
      graphSearchQuery: 'q', graphSearchStatus: '', _graphSearchMatches: [],
      _graphSearchIdx: 0, _graphSearchLastQ: 'q',
      cognitionNetwork: rmNet, reducedMotion: true });
    assert.strictEqual(rmNet.calls.fit[0], false,
      'F2: reducedMotion → fit без анимации');

    // clearCognitionGraphSearch: selectNodes([]) + fit + сброс полей.
    net = makeNet();
    methods.clearCognitionGraphSearch.call({
      graphSearchQuery: 'q', graphSearchStatus: 'old',
      _graphSearchMatches: [1], _graphSearchIdx: 3, _graphSearchLastQ: 'q',
      cognitionNetwork: net, reducedMotion: false });
    assert.deepStrictEqual(net.calls.select[0], [], 'F2: selectNodes([])');
    assert.strictEqual(net.calls.fit.length, 1, 'F2: fit при сбросе');

    // Гонка lazy-load: нет инстанса → дождаться рендера и повторить.
    let rendered = 0;
    const net2 = makeNet();
    ctx = baseCtx(null, {
      graphSearchQuery: 'кот',
      renderCognitionGraph: async function () {
        rendered += 1; this.cognitionNetwork = net2;
      },
    });
    await methods.searchCognitionGraph.call(ctx);
    assert.strictEqual(rendered, 1, 'F2: гонка до рендера → один повтор');
    assert.strictEqual(net2.calls.focus.length, 1, 'F2: поиск после рендера');
  }

  // ── F4 (graph-physics-stabilization-round1018, ADR-1018-4): 150 итераций
  //    стабилизации + авто-отключение physics по завершении расстановки ─────
  {
    const fs = require('fs');
    const jsSrc = fs.readFileSync(
      path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf-8');
    assert.ok(jsSrc.indexOf('GRAPH_PHYSICS_ITERATIONS = 150') >= 0,
      'F4: iterations=150 — код-константа');
    assert.ok(jsSrc.indexOf('GRAPH_PHYSICS_DISABLE_ON_STABILIZE = true') >= 0,
      'F4: флаг авто-отключения физики');
    assert.ok(jsSrc.indexOf('iterations: GRAPH_PHYSICS_ITERATIONS') >= 0,
      'F4: опции используют GRAPH_PHYSICS_ITERATIONS');
    assert.ok(jsSrc.indexOf('stabilizationIterationsDone') >= 0,
      'F4: слушатель stabilizationIterationsDone');
    assert.ok(jsSrc.indexOf("'stabilized'") >= 0,
      'F4: слушатель stabilized');
    assert.ok(jsSrc.indexOf('physics: { enabled: false }') >= 0,
      'F4: physics.enabled=false после расстановки');
    assert.ok(jsSrc.indexOf('net.once(') >= 0,
      'F4: once (не on) — обработчики не копятся');
    assert.ok(jsSrc.indexOf('physics: this.reducedMotion') >= 0,
      'F4: reducedMotion → physics:false сохранён');

    const FakeDataSet = function (rows) { this.rows = rows; };
    let netCreated = null;
    function FakeNetwork(el, data, options) {
      // B3-1: НЕ фабрикуем несуществующие члены vis-network
      // (`destroyed`/`isDestroyed` отсутствуют в self-host v9.1.9) —
      // guard обязан опираться только на тождество инстанса.
      const self = this;
      this.el = el; this.data = data; this.options = options;
      this.onceEvents = [];
      this.setOptionsCalls = [];
      this.destroy = function () {};
      this.once = function (ev, cb) {
        self.onceEvents.push(ev);
        self['cb_' + ev] = cb;
      };
      this.setOptions = function (o) { self.setOptionsCalls.push(o); };
      netCreated = self;
    }
    const prevVis = global.window.vis;
    global.window.vis = { DataSet: FakeDataSet, Network: FakeNetwork };
    const baseCtx = {
      isGlobalAdmin: true, activeTab: 'status', reducedMotion: false,
      cognitionGraphData: {
        nodes: [{ id: 1, label: 'a' }, { id: 2, label: 'b' }],
        edges: [{ from: 1, to: 2, label: 'r', weight: 1 }],
      },
      $refs: { cognitionGraph: {} },
      cognitionNetwork: null, _cognitionGraphSig: null,
      ensureVisNetwork: methods.ensureVisNetwork,
      _graphSignature: methods._graphSignature,
      destroyCognitionGraph: methods.destroyCognitionGraph,
    };
    await methods.renderCognitionGraph.call(baseCtx);
    assert.ok(netCreated, 'F4: сеть создана');
    assert.strictEqual(
      netCreated.options.physics.stabilization.iterations, 150,
      'F4: stabilization.iterations=150');
    assert.deepStrictEqual(netCreated.onceEvents,
      ['stabilizationIterationsDone', 'stabilized'],
      'F4: once-слушатели стабилизации');
    // событие завершения стабилизации → physics off
    netCreated.cb_stabilizationIterationsDone();
    assert.deepStrictEqual(netCreated.setOptionsCalls,
      [{ physics: { enabled: false } }],
      'F4: stabilizationIterationsDone → physics off');

    // B3-1: старый инстанс после destroy не получает setOptions (guard по
    // тождеству отсекает уничтоженную сеть), а НОВЫЙ инстанс — получает.
    const first = netCreated;
    const firstCalls = first.setOptionsCalls.length;
    methods.destroyCognitionGraph.call(baseCtx);
    assert.strictEqual(baseCtx.cognitionNetwork, null,
      'F4: destroy обнулил сеть');
    first.cb_stabilizationIterationsDone();  // старый инстанс: guard отсекает
    assert.strictEqual(first.setOptionsCalls.length, firstCalls,
      'B3-1: старый инстанс после destroy не получает setOptions');
    netCreated = null;
    await methods.renderCognitionGraph.call(baseCtx);
    assert.ok(netCreated && netCreated !== first, 'F4: пересоздание сети');
    assert.strictEqual(netCreated.onceEvents.length, 2,
      'F4: новый инстанс снова получает слушатели');
    netCreated.cb_stabilizationIterationsDone();
    assert.deepStrictEqual(netCreated.setOptionsCalls,
      [{ physics: { enabled: false } }],
      'B3-1: новый инстанс получает physics off');

    // reducedMotion → physics:false, слушатели не навешиваются.
    netCreated = null;
    const rmCtx = Object.assign({}, baseCtx, {
      reducedMotion: true, cognitionNetwork: null, _cognitionGraphSig: null });
    await methods.renderCognitionGraph.call(rmCtx);
    assert.strictEqual(netCreated.options.physics, false,
      'F4: reducedMotion → physics:false');
    assert.strictEqual(netCreated.onceEvents.length, 0,
      'F4: reducedMotion → без слушателей');
    global.window.vis = prevVis;
  }

  // ── F2 (sleep-manual-cascade-badges-round1018): реактивные бейджи ────────
  //    (T-1720/T-1721): cognition=null → «—»; ретраи после ручного POST;
  //    временное ускорение polling. WebSocket в проекте нет.
  {
    assert.strictEqual(typeof methods._retryCognition, 'function',
      'F2: _retryCognition — метод');
    assert.strictEqual(typeof methods.restartCognitionPolling, 'function',
      'F2: restartCognitionPolling — метод');

    // Пустые delays → без вызовов (нет лишних таймеров).
    let loads = 0;
    methods._retryCognition.call({ loadCognition() { loads += 1; } }, []);
    assert.strictEqual(loads, 0, 'F2: пустые delays → без вызовов');

    // restartCognitionPolling(5000) → таймер 5с; stop() очищает.
    const pctx = { isGlobalAdmin: true, activeTab: 'status', cognitionTimer: null,
                   _cognitionPollRestore: null, loadCognition() {},
                   stopCognitionPolling: methods.stopCognitionPolling,
                   _startCognitionTimer: methods._startCognitionTimer,
                   _restoreCognitionPolling: methods._restoreCognitionPolling };
    methods.restartCognitionPolling.call(pctx, 5000, 0);
    assert.ok(pctx.cognitionTimer != null, 'F2: polling перезапущен (5с)');
    methods.stopCognitionPolling.call(pctx);
    assert.strictEqual(pctx.cognitionTimer, null, 'F2: polling остановлен');

    // D2/R10.18 + R2-5: restore возвращает БАЗОВЫЕ 15с (не оставляет 5с
    // навсегда). setInterval/setTimeout стабим, чтобы дожать restore ЧЕРЕЗ
    // срабатывание таймера (не вызывая internal _restoreCognitionPolling
    // напрямую — иначе closure setTimeout(..., restoreMs) не покрыт).
    const seenMs = [];
    const restoreCbs = [];
    const realSet = global.setInterval;
    const realClear = global.clearInterval;
    const realSetTimeout = global.setTimeout;
    const realClearTimeout = global.clearTimeout;
    global.setInterval = function (fn, ms) { seenMs.push(ms); return { ms: ms }; };
    global.clearInterval = function () {};
    global.setTimeout = function (fn, ms) { restoreCbs.push({ fn: fn, ms: ms }); return { ms: ms }; };
    global.clearTimeout = function () {};
    try {
      methods.restartCognitionPolling.call(pctx, 5000, 120000);
      assert.deepStrictEqual(seenMs, [5000],
        'F2/D6: ускорение 5с на вкладке Статус');
      assert.strictEqual(restoreCbs.length, 1, 'F2: restore таймер armed');
      assert.strictEqual(restoreCbs[0].ms, 120000, 'F2: restore = 120с');
      assert.ok(pctx._cognitionPollRestore != null, 'F2: restore сохранён в state');
      // Дожим restore ЧЕРЕЗ срабатывание таймера (не вызовом internal).
      restoreCbs[0].fn();
      assert.strictEqual(pctx._cognitionPollRestore, null,
        'F2/R2-5: restore-таймер сброшен после срабатывания');
      assert.deepStrictEqual(seenMs, [5000, 15000],
        'F2/D2: базовый polling восстановлен 15с');
    } finally {
      global.setInterval = realSet;
      global.clearInterval = realClear;
      global.setTimeout = realSetTimeout;
      global.clearTimeout = realClearTimeout;
    }
    methods.stopCognitionPolling.call(pctx);

    // R2-1: кнопка «Запустить синтез сейчас» живёт на вкладке modules —
    // ускорение обязано стартовать и там (гейт по вкладке снят).
    {
      const seen2 = [];
      const cbs2 = [];
      const rs = global.setInterval, rc = global.clearInterval;
      const rst = global.setTimeout, rct = global.clearTimeout;
      global.setInterval = function (fn, ms) { seen2.push(ms); return { ms: ms }; };
      global.clearInterval = function () {};
      global.setTimeout = function (fn, ms) { cbs2.push({ fn: fn, ms: ms }); return { ms: ms }; };
      global.clearTimeout = function () {};
      try {
        const modTab = { isGlobalAdmin: true, activeTab: 'modules',
          cognitionTimer: null, _cognitionPollRestore: null, loadCognition() {},
          stopCognitionPolling: methods.stopCognitionPolling,
          _startCognitionTimer: methods._startCognitionTimer,
          _restoreCognitionPolling: methods._restoreCognitionPolling };
        methods.restartCognitionPolling.call(modTab, 5000, 120000);
        assert.deepStrictEqual(seen2, [5000],
          'F2/R2-1: на вкладке modules ускорение 5с стартует');
        assert.strictEqual(cbs2.length, 1,
          'F2/R2-1: restore-таймер armed вне Статуса');
        // S10.18-22: по истечении restore вне вкладки «Статус» базовый 15с
        // НЕ поднимается (инвариант F5/R10.11-5 «вне Статуса — стоп»).
        cbs2[0].fn();
        assert.deepStrictEqual(seen2, [5000],
          'S10.18-22: restore вне Статуса не стартует 15с');
        assert.strictEqual(modTab.cognitionTimer, null,
          'S10.18-22: после restore вне Статуса polling не создан');
        // Уход с вкладки (setTab → stopCognitionPolling) снимает ОБА таймера:
        // 5с-интервал и restore — «вечного 5с» вне вкладки нет.
        methods.restartCognitionPolling.call(modTab, 5000, 120000);
        methods.stopCognitionPolling.call(modTab);
        assert.strictEqual(modTab.cognitionTimer, null,
          'F2/R2-1: уход с вкладки снял 5с-интервал');
        assert.strictEqual(modTab._cognitionPollRestore, null,
          'F2/R2-1: уход с вкладки снял restore-таймер');
      } finally {
        global.setInterval = rs; global.clearInterval = rc;
        global.setTimeout = rst; global.clearTimeout = rct;
      }
    }

    // S10.18-26: ретраи _retryCognition сохраняются в state и снимаются
    // stopCognitionPolling (иначе 3 запроса уходили после ухода с вкладки).
    {
      const cleared = [];
      const handles = [];
      const rs = global.setInterval, rc = global.clearInterval;
      const rst = global.setTimeout, rct = global.clearTimeout;
      global.setTimeout = function (fn, ms) {
        const h = { ms: ms }; handles.push(h); return h;
      };
      global.clearTimeout = function (h) { cleared.push(h); };
      global.setInterval = function () { return { ms: 15000 }; };
      global.clearInterval = function () {};
      try {
        const retryCtx = { isGlobalAdmin: true, activeTab: 'modules',
          cognitionTimer: null, _cognitionPollRestore: null,
          _cognitionRetryTimers: [], loadCognition() {},
          _retryCognition: methods._retryCognition,
          stopCognitionPolling: methods.stopCognitionPolling };
        methods._retryCognition.call(retryCtx, [1000, 3000, 8000]);
        assert.strictEqual(retryCtx._cognitionRetryTimers.length, 3,
          'S10.18-26: ретраи сохранены в state');
        methods.stopCognitionPolling.call(retryCtx);
        assert.strictEqual(retryCtx._cognitionRetryTimers.length, 0,
          'S10.18-26: stop очистил список ретраев');
        assert.strictEqual(cleared.length, 3,
          'S10.18-26: все 3 setTimeout сняты clearTimeout');
      } finally {
        global.setInterval = rs; global.clearInterval = rc;
        global.setTimeout = rst; global.clearTimeout = rct;
      }
    }

    // S10.18-22: closeModule вне «Статуса» снимает polling (модалка «Сон»
    // живёт на вкладке modules).
    {
      let stopped = 0;
      const closeCtx = { openModuleId: 'mod_sleep', activeTab: 'modules',
        stopCognitionPolling: function () { stopped += 1; } };
      methods.closeModule.call(closeCtx);
      assert.strictEqual(closeCtx.openModuleId, null, 'S10.18-22: модалка закрыта');
      assert.strictEqual(stopped, 1, 'S10.18-22: closeModule вне Статуса → stop');
      const statusCtx = { openModuleId: 'mod_sleep', activeTab: 'status',
        stopCognitionPolling: function () { stopped += 1; } };
      methods.closeModule.call(statusCtx);
      assert.strictEqual(stopped, 1,
        'S10.18-22: на «Статусе» polling не трогаем');
    }

    // R2-1 (реальный путь): runDreamNow с вкладки modules (где живёт кнопка
    // «Запустить синтез сейчас») обязан включить ускорение 5с СРАЗУ после POST.
    {
      const seen3 = [];
      const timers3 = [];
      const rs = global.setInterval, rc = global.clearInterval;
      const rst = global.setTimeout, rct = global.clearTimeout;
      global.setInterval = function (fn, ms) { seen3.push(ms); return { ms: ms }; };
      global.clearInterval = function () {};
      global.setTimeout = function (fn, ms) { timers3.push({ fn: fn, ms: ms }); return { ms: ms }; };
      global.clearTimeout = function () {};
      try {
        const rctx = {
          isGlobalAdmin: true, activeTab: 'modules', dreamBusy: false,
          cognition: { dream: { active: false } },
          cognitionTimer: null, _cognitionPollRestore: null,
          api: async function () { return {}; },
          loadCognition() {}, loadDreamBeliefs() {}, loadDreamLog() {}, toast() {},
          _retryCognition: methods._retryCognition,
          restartCognitionPolling: methods.restartCognitionPolling,
          stopCognitionPolling: methods.stopCognitionPolling,
          _startCognitionTimer: methods._startCognitionTimer,
          _restoreCognitionPolling: methods._restoreCognitionPolling,
        };
        await methods.runDreamNow.call(rctx);
        assert.strictEqual(rctx.cognition.dream.active, true,
          'F2/R2-1: оптимистичная active после POST');
        assert.deepStrictEqual(seen3, [5000],
          'F2/R2-1: runDreamNow (modules) → ускоренный polling 5с стартует');
        assert.ok(timers3.some(function (t) { return t.ms === 120000; }),
          'F2/R2-1: restore-таймер 120с armed');
      } finally {
        global.setInterval = rs; global.clearInterval = rc;
        global.setTimeout = rst; global.clearTimeout = rct;
      }
    }

    // non-admin → no-op (не создаём таймер).
    const notAdmin = { isGlobalAdmin: false, cognitionTimer: null,
                       _cognitionPollRestore: null };
    methods.restartCognitionPolling.call(notAdmin, 5000, 0);
    assert.strictEqual(notAdmin.cognitionTimer, null,
      'F2: не global admin → polling не запускается');
  }

  console.log('JS-UNIT-OK');
})().catch((e) => {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
