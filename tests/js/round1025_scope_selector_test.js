'use strict';
/* F3 round1025 — глобальный селектор области (§5/§42/§43/§70):
 *   (a) переключение Глобально → Чат → ЛС → Глобально НЕ смешивает значения
 *       и НЕ переносит черновики предыдущей области;
 *   (b) устаревший ответ старого scope (scopeEpoch) НЕ применяется;
 *   (c) источник значения: глобальное наследование vs локальное
 *       переопределение; фактическое состояние §43;
 *   (d) «Вернуть глобальное значение» снимает ТОЛЬКО override (DELETE
 *       /api/config/chat/<key>), не трогая заводское значение;
 *   (e) несохранённые правки при переключении области — предупреждение;
 *       отказ → область НЕ меняется (черновик сохранён).
 *
 * Запуск: node tests/js/round1025_scope_selector_test.js
 */
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component() {}, provide() {}, use() {}, mount() {},
    };
  },
};
const _storage = { _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; } };
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; },
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;

// ── ctx, достаточный для setActiveChat (без полного стейта приложения) ──
function makeCtx(overrides) {
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
    isGlobalAdmin: true,
    scopeKind: 'global',
    syncActiveChatTitle() {},
    hasUnsavedEdits: methods.hasUnsavedEdits,
    loadConfig() { calls.push('config'); },
    loadKeyStatus() { calls.push('keys'); },
    loadGateInfo() { calls.push('gate'); },
    loadLocalAdmins() { calls.push('admins'); },
    loadPersona() { calls.push('persona'); },
    loadRelations() { calls.push('relations'); },
    calls: calls,
  };
  return Object.assign(ctx, overrides || {});
}

(async function run() {
  // ── (0) Три режима: Глобально / Чат / ЛС ─────────────────────────────
  {
    const kind = function (activeChatId, isDm) {
      return computed.scopeKind.call({ activeChatId: activeChatId,
        isDmCtx: function () { return isDm; } });
    };
    assert.strictEqual(kind(null, false), 'global', 'null → global');
    assert.strictEqual(kind(-100123, false), 'chat', '<0 → chat');
    assert.strictEqual(kind(777888, true), 'dm', '>0 + isDm → dm');
  }

  // ── (a) Глобально → Чат → ЛС → Глобально: без смешивания черновиков ──
  {
    const ctx = makeCtx({ activeChatId: null });
    methods.setActiveChat.call(ctx, -100500);       // → ЧАТ
    assert.strictEqual(ctx.activeChatId, -100500, 'a: переключено на чат');
    assert.deepStrictEqual(ctx.keyDrafts, {}, 'a: черновики ключей не едут');
    assert.deepStrictEqual(ctx.blockDrafts, {}, 'a: черновики блоков сброшены');
    assert.deepStrictEqual(ctx.blockResults, {}, 'a: результаты блоков сброшены');
    assert.strictEqual(ctx.personaDraft, null, 'a: persona-черновик сброшен');
    assert.strictEqual(ctx.configChatUpdatedAt, null, 'a: токен чата сброшен');
    assert.strictEqual(ctx.configItems.length, 0, 'a: конфиг очищен до загрузки');
    assert.ok(ctx.calls.indexOf('config') >= 0, 'a: значения новой области грузятся');
    const ep1 = ctx.scopeEpoch;

    ctx.isDmCtx = function () { return true; };
    methods.setActiveChat.call(ctx, 777888);        // → ЛС
    assert.strictEqual(ctx.activeChatId, 777888, 'a: переключено на ЛС');
    assert.ok(ctx.scopeEpoch > ep1, 'a: epoch инкрементнут (отброс stale)');
    assert.deepStrictEqual(ctx.blockDrafts, {}, 'a: черновик чата не в ЛС');

    methods.setActiveChat.call(ctx, null);          // → ГЛОБАЛЬНО
    assert.strictEqual(ctx.activeChatId, null, 'a: вернулись в Глобально');
    assert.strictEqual(global.localStorage.getItem('adminbot.active_chat_id'), null,
      'a: GLOBAL не персистится в localStorage');
  }

  // ── (b) Устаревший ответ старого scope НЕ применяется ────────────────
  {
    const ctx = {
      scopeEpoch: 1,
      configLoading: false,
      configVersion: 0,
      configItems: [],
      configGroups: [],
      configChatUpdatedAt: 'old',
      blockDrafts: {},
      activeTab: 'status',
      api: async function () {
        // пока ответ в полёте — пользователь сменил область
        ctx.scopeEpoch = 2;
        return { items: [{ key: 'limits.stale', value: 999 }],
                 groups: [], updated_at: 'new-token' };
      },
      _scopeGuard: methods._scopeGuard,
      _snapshotConfig: function () {},
      _syncPromptModeFromConfig: function () {},
      maybeLoadCliche: function () {},
      toast: function () {},
    };
    await methods.loadConfig.call(ctx);
    assert.strictEqual(ctx.configItems.length, 0,
      'b: запоздавший ответ старого scope не применён');
    assert.strictEqual(ctx.configChatUpdatedAt, 'old',
      'b: токен старого ответа не применён');
    assert.strictEqual(ctx.configLoading, true,
      'b: stale-ответ НЕ снимает loading чужого scope (владелец — новый load)');

    // актуальный ответ применяется
    const ctx2 = {
      scopeEpoch: 5, configLoading: false, configVersion: 0,
      configItems: [], configGroups: [], configChatUpdatedAt: null,
      blockDrafts: {}, activeTab: 'status',
      api: async function () {
        return { items: [{ key: 'limits.fresh', value: 7 }],
                 groups: [], updated_at: 'tok' };
      },
      _scopeGuard: methods._scopeGuard,
      _snapshotConfig: function () {},
      _syncPromptModeFromConfig: function () {},
      maybeLoadCliche: function () {},
      toast: function () {},
    };
    await methods.loadConfig.call(ctx2);
    assert.strictEqual(ctx2.configItems.length, 1, 'b: актуальный ответ применён');
    assert.strictEqual(ctx2.configItems[0].key, 'limits.fresh', 'b: верный ключ');
  }

  // ── (c) Источник значения: global vs local override (+ §43) ──────────
  {
    const chatSrc = methods.configSourceLabel.call({ scopeKind: 'chat' },
      { chat_source: '' });
    assert.strictEqual(chatSrc, 'Источник: глобальная настройка',
      'c: наследование из глобального');
    const localSrc = methods.configSourceLabel.call({ scopeKind: 'chat' },
      { chat_source: 'chat' });
    assert.strictEqual(localSrc, 'Источник: настройки чата',
      'c: локальное переопределение');
    const glob = methods.configSourceLabel.call({ scopeKind: 'global' },
      { chat_source: '' });
    assert.strictEqual(glob, '', 'c: в глобальной области источник не дублируем');

    const notice = methods.configItemNotice.call({ scopeKind: 'chat' },
      { per_chat: true, chat_source: 'chat', global_value: false, value: true });
    assert.strictEqual(notice, 'Локально включено, хотя глобально выключено',
      'c/§43: расхождение локального и глобального');
    const noticeGlobal = methods.configItemNotice.call({ scopeKind: 'chat' },
      { per_chat: true, chat_source: '', global_value: false, value: false });
    assert.strictEqual(noticeGlobal, '', 'c: при согласии значений — без пометки');
    // Ревью Medium: per_chat===false (~101 параметр) больше не шумит —
    // пометка только при фактическом расхождении override.
    const noticeNonPerChat = methods.configItemNotice.call({ scopeKind: 'chat' },
      { per_chat: false });
    assert.strictEqual(noticeNonPerChat, '',
      'c/§43: без фактического расхождения — без пометки (нет шума)');
    const noticeNoOverride = methods.configItemNotice.call({ scopeKind: 'chat' },
      { per_chat: true, chat_source: '', global_value: true, value: true });
    assert.strictEqual(noticeNoOverride, '',
      'c/§43: наследование (нет override) — без пометки');
  }

  // ── (d) «Вернуть глобальное значение» = DELETE override (не сброс) ───
  {
    const apiCalls = [];
    let reload = 0;
    const ctx = {
      isGlobalAdmin: true, scopeKind: 'chat',
      isDmCtx: function () { return false; },
      saving: new Set(),
      toast: function () {},
      api: async function (url, opts) {
        apiCalls.push({ url: url, method: opts && opts.method });
        return {};
      },
      _preserveScroll: function (fn) { return fn && fn.call(this); },
      loadConfig: function () { reload += 1; },
      loadKeyStatus: function () {},
    };
    const item = { key: 'limits.pause_seconds', title: 'Пауза',
                   chat_source: 'chat', value: 180 };
    global.window.confirm = function () { return true; };
    await methods.resetChatOverride.call(ctx, item);
    assert.strictEqual(apiCalls.length, 1, 'd: ровно одна мутация');
    assert.strictEqual(apiCalls[0].method, 'DELETE', 'd: DELETE, не POST');
    assert.strictEqual(apiCalls[0].url,
      '/api/config/chat/' + encodeURIComponent('limits.pause_seconds'),
      'd: снятие override конкретного ключа чата');
    assert.ok(reload >= 1, 'd: значения перечитаны после возврата к глобальному');
    assert.strictEqual(ctx.saving.size, 0, 'd: in-flight снят');

    // Отмена пользователя → НИ одной мутации (сброс не выполняется).
    const apiCalls2 = [];
    const ctx2 = Object.assign({}, ctx, {
      api: async function (url, opts) { apiCalls2.push(url); return {}; },
    });
    global.window.confirm = function () { return false; };
    await methods.resetChatOverride.call(ctx2, item);
    assert.strictEqual(apiCalls2.length, 0, 'd: отмена → без мутации');

    // Ревью 2 (UI↔сервер): локальный админ имеет право снять override
    // (routes.py разрешает is_local_admin) — guard НЕ блокирует.
    const apiLa = [];
    const ctxLa = {
      isGlobalAdmin: false, isDmCtx: function () { return false; },
      isLocalAdminCtx: function () { return true; },
      scopeKind: 'chat', saving: new Set(), toast: function () {},
      api: async function (url, opts) { apiLa.push({ url: url }); return {}; },
      _preserveScroll: function (fn) { return fn && fn.call(this); },
      loadConfig: function () {}, loadKeyStatus: function () {},
    };
    global.window.confirm = function () { return true; };
    await methods.resetChatOverride.call(ctxLa, item);
    assert.strictEqual(apiLa.length, 1,
      'd: local_admin → DELETE выполняется (паритет с сервером)');

    // Без прав (не global/DM/local admin) → отказ, без мутации.
    const apiDenied = [];
    const ctxDenied = {
      isGlobalAdmin: false, isDmCtx: function () { return false; },
      isLocalAdminCtx: function () { return false; },
      scopeKind: 'chat', saving: new Set(),
      toasts: [],
      toast: function (t, k) { this.toasts.push(k || 'ok'); },
      api: async function () { apiDenied.push(1); return {}; },
      _preserveScroll: function (fn) { return fn && fn.call(this); },
      loadConfig: function () {}, loadKeyStatus: function () {},
    };
    global.window.confirm = function () { return true; };
    await methods.resetChatOverride.call(ctxDenied, item);
    assert.strictEqual(apiDenied.length, 0, 'd: нет прав → без мутации');
    assert.ok(ctxDenied.toasts.indexOf('err') >= 0, 'd: нет прав → err-тост');
  }

  // ── (e) Несохранённые правки при переключении области ────────────────
  {
    // (e1) отказ → область НЕ меняется, черновик цел
    const ctx = makeCtx({ activeChatId: -100, stickyDirtyCount: 2 });
    global.window.confirm = function () { return false; };
    const ep = ctx.scopeEpoch;
    methods.setActiveChat.call(ctx, 777888);
    assert.strictEqual(ctx.activeChatId, -100,
      'e: отказ → область не изменена (черновик не потерян)');
    assert.strictEqual(ctx.scopeEpoch, ep, 'e: отказ → epoch не растёт');
    assert.deepStrictEqual(ctx.blockDrafts, { 'models.llm_model_name': 'draft-A' },
      'e: черновик сохранён');

    // (e2) согласие → переключение выполняется
    const ctx2 = makeCtx({ activeChatId: -100, stickyDirtyCount: 2 });
    global.window.confirm = function () { return true; };
    methods.setActiveChat.call(ctx2, 777888);
    assert.strictEqual(ctx2.activeChatId, 777888, 'e: согласие → область сменена');
    assert.deepStrictEqual(ctx2.blockDrafts, {}, 'e: черновик сброшен после согласия');

    // (e3) чистая форма → без подтверждения (все черновики пусты)
    let asked = 0;
    global.window.confirm = function () { asked += 1; return true; };
    const ctx3 = makeCtx({ activeChatId: -100, blockDrafts: {},
      keyDrafts: {}, ownKeyDraft: '', personaDraft: null, personaMeta: null });
    methods.setActiveChat.call(ctx3, 777888);
    assert.strictEqual(asked, 0, 'e: без правок подтверждение не запрашивается');
    assert.strictEqual(ctx3.activeChatId, 777888, 'e: чистая форма → переключение');

    // hasUnsavedEdits устойчив к минимальному контексту
    assert.strictEqual(methods.hasUnsavedEdits.call({}), false,
      'e: пустой контекст → чисто (без падения)');
    assert.strictEqual(methods.hasUnsavedEdits.call({ stickyDirtyCount: 1 }), true,
      'e: dirty>0 → есть правки');
    assert.strictEqual(
      methods.hasUnsavedEdits.call({ saving: new Set(['k']) }), true,
      'e: in-flight сохранение → считаем правки');

    // Ревью High: state, который setActiveChat() молча чистит, тоже
    // блокирует переключение (иначе потеря ввода).
    assert.strictEqual(
      methods.hasUnsavedEdits.call({ blockDrafts: { 'keys.llm_api_key': 'sk-x' } }),
      true, 'e: введённый API-ключ в blockDrafts → есть правки');
    assert.strictEqual(
      methods.hasUnsavedEdits.call({ blockDrafts: {} }), false,
      'e: пустой blockDrafts → не правка');
    assert.strictEqual(
      methods.hasUnsavedEdits.call({ ownKeyDraft: '  sk-bot  ' }), true,
      'e: BYOK-черновик чата → есть правки');
    assert.strictEqual(
      methods.hasUnsavedEdits.call({ ownKeyDraft: '   ' }), false,
      'e: пустой BYOK-черновик → не правка');
    // persona: baseline-сравнение (черновик инициализируется сервером).
    const pBase = { name: 'A', biography: '', system_prompt_overrides: '',
                    is_aware_ai: false };
    assert.strictEqual(
      methods.hasUnsavedEdits.call({
        personaDraft: Object.assign({}, pBase),
        personaMeta: { values: pBase },
      }), false, 'e: persona без изменений (== baseline) → чисто');
    assert.strictEqual(
      methods.hasUnsavedEdits.call({
        personaDraft: Object.assign({}, pBase, { name: 'B' }),
        personaMeta: { values: pBase },
      }), true, 'e: persona изменена → есть правки');
    assert.strictEqual(
      methods.hasUnsavedEdits.call({ personaDraft: Object.assign({}, pBase) }),
      true, 'e: persona без baseline → консервативно считаем правкой');
    // dossier: baseline manual_traits.
    assert.strictEqual(
      methods.hasUnsavedEdits.call({
        dossierDraft: 'x', dossierData: { manual_traits: 'x' },
      }), false, 'e: досье без изменений → чисто');
    assert.strictEqual(
      methods.hasUnsavedEdits.call({
        dossierDraft: 'y', dossierData: { manual_traits: 'x' },
      }), true, 'e: досье изменено → есть правки');
    // Ревью 2: ОЧИСТКА поля (было непустое → стало '') тоже правка.
    assert.strictEqual(
      methods.hasUnsavedEdits.call({
        dossierDraft: '', dossierData: { manual_traits: 'x' },
      }), true, 'e: очистка досье до пустой строки → есть правки');

    // Интеграция: введённый API-ключ блокирует смену области.
    const ctxB = makeCtx({ activeChatId: -100,
      blockDrafts: { 'keys.llm_api_key': 'sk-typed' } });
    let askedB = 0;
    global.window.confirm = function () { askedB += 1; return false; };
    methods.setActiveChat.call(ctxB, 777888);
    assert.strictEqual(askedB, 1, 'e: blockDrafts → запрос подтверждения');
    assert.strictEqual(ctxB.activeChatId, -100, 'e: отказ → область не меняется');
  }

  console.log('SCOPE-SELECTOR-OK');
  process.exit(0);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
