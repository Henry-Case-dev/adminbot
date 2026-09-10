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

ctx = makeCtx(['status', 'reactions_triggers']);
methods.applyRoute.call(ctx, '#/modules');
assert.strictEqual(ctx.route, '#/modules',
  'D1: hub #/modules доступен при одной видимой карточке');

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

  console.log('JS-UNIT-OK');
})().catch((e) => {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
