'use strict';
/* F4 round1025 — ModuleConfigurationStore (§37–§45, ADR-1025-14):
 *   (a) ключ `scope_type|scope_id|module_id` — global/чат A/чат B = 3 ключа;
 *   (b) get/set/refresh/subscribe — контракт §39;
 *   (c) РОВНО одна серверная мутация на переключение (§40);
 *   (d) in-flight guard по ключу (двойной тап = 1 запрос, §41.2);
 *   (e) структурный откат при ошибке (§41): configItems не мутирован,
 *       overlay снят → UI возвращается к серверному значению; без ретраев;
 *   (f) stale-ответ не меняет чужой scope (§42/§73);
 *   (g) overlay не мутирует configItems;
 *   (h) счётчики §45 (неизвестное ≠ выключено, noToggle, uiFlag OFF);
 *   (i) поиск/синонимы §44 («Саммари»/«сводка» → «Сводки чатов»);
 *   (j) избранное в localStorage (save/restore/fail-open, §34–§36);
 *   (k) moduleRuntimeNotice по таблице §43;
 *   (l) §72 единый переключатель (три представления = одно состояние);
 *   (m) openModuleWorkspace → openModuleWindow (§D6);
 *   (o) F4-M1: gate='global' + глобально OFF + локально ON → runtime
 *       'blocked' («Включён, но не работает»), модуль в счётчике/фильтре
 *       «Есть проблемы» и НЕ в «Включено» (+ negative: глобально ON).
 *
 * Запуск: node tests/js/round1025_f4_module_store_test.js
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
const _storage = {
  _s: {},
  getItem(k) {
    return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null;
  },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; }, localStorage: _storage,
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
const data = captured.data();
const methods = captured.methods;
const computed = captured.computed;
const MODULES = data.modules;

function item(key, value, extra) {
  return Object.assign(
    { key: key, value: value, per_chat: true, global_value: value },
    extra || {});
}
function moduleById(id) {
  return MODULES.filter(function (m) { return m.id === id; })[0];
}

// Контекст, достаточный для store (server-состояние = configItems).
function mkCtx(overrides) {
  const calls = [];
  const ctx = Object.assign({}, methods, {
    modules: MODULES,
    scopeKind: 'global',
    activeChatId: null,
    scopeEpoch: 0,
    configItems: [],
    moduleOptimistic: {},
    modulePending: {},
    moduleSaveError: {},
    moduleQuickpicks: null,
    moduleQuickpicksOpen: false,
    moduleSearch: '',
    moduleFilter: 'all',
    stickyFailedKeys: [],
    me: null,
    _opSeq: 0,
    saving: new Set(),
    toasts: [],
    toast: function (t, k) { this.toasts.push(k || 'ok'); },
    uiFlag: function () { return true; },
    canEditConfig: function () { return true; },
    canEditModule: methods.canEditModule,
    _findConfigItem: methods._findConfigItem,
    _preserveScroll: function (fn) { return fn && fn.call(ctx); },
    loadConfig: async function () { calls.push({ load: true }); },
    // Транспорт-спай: считаем серверные мутации (persistItems = write-path F0).
    posts: calls,
    persistItems: async function (items, opts) {
      calls.push({ items: items, opts: opts || {} });
      if (ctx.__fail) {
        return { saved: [], skipped: [],
                 failed: [{ key: items[0].key,
                            reason: ctx.__failReason || 'error',
                            conflicting: ctx.__conflicting || [] }],
                 revalidated: false, state: 'error' };
      }
      // Успех: сервер применил значение → configItems обновлён (как loadConfig).
      items.forEach(function (it) {
        const found = (ctx.configItems || []).filter(function (i) {
          return i.key === it.key;
        })[0];
        if (found) found.value = it.value;
      });
      return { saved: items.map(function (i) { return i.key; }), failed: [],
               skipped: [], revalidated: false, state: 'saved',
               operationId: opts && opts.operationId };
    },
  });
  Object.assign(ctx, overrides || {});
  ctx.visibleModules = computed.visibleModules.call(ctx);
  ctx.quickpickCandidates = computed.quickpickCandidates.call(ctx);
  return ctx;
}

const SUM = 'flags.summary_enabled';
// Серверные мутации — только записи транспорта (загрузки конфига не считаем).
function writes(ctx) {
  return (ctx.posts || []).filter(function (x) { return x && x.items; });
}
function summaryItem(extra) {
  return item(SUM, true, Object.assign(
    { global_value: true, chat_source: '' }, extra || {}));
}

(async function run() {
  // ── (a) Ключ §38: три разных контекста ───────────────────────────────
  {
    const kG = methods.storeKey.call({}, { type: 'global', id: null }, 'mod_summary');
    const kA = methods.storeKey.call({}, { type: 'chat', id: 123 }, 'mod_summary');
    const kB = methods.storeKey.call({}, { type: 'chat', id: 456 }, 'mod_summary');
    assert.strictEqual(kG, 'global/null/mod_summary');
    assert.strictEqual(kA, 'chat/123/mod_summary');
    assert.strictEqual(kB, 'chat/456/mod_summary');
    assert.notStrictEqual(kA, kB, 'a: разные чаты — разные ключи');

    const sc = methods.storeScope.call({ scopeKind: 'chat', activeChatId: -100 });
    assert.deepStrictEqual(sc, { type: 'chat', id: -100 }, 'a: storeScope');
    assert.deepStrictEqual(
      methods.storeScope.call({ scopeKind: 'global', activeChatId: null }),
      { type: 'global', id: null }, 'a: global scope');
    assert.deepStrictEqual(
      methods.storeScope.call({ scopeKind: 'dm', activeChatId: 777 }),
      { type: 'dm', id: 777 }, 'a: dm scope');
  }

  // ── (b) getModuleState из configItems ────────────────────────────────
  {
    const ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [summaryItem({ chat_source: 'chat' })] });
    const st = methods.getModuleState.call(
      ctx, { type: 'chat', id: -100 }, 'mod_summary');
    assert.strictEqual(st.known, true);
    assert.strictEqual(st.effective, true);
    assert.strictEqual(st.globalValue, true);
    assert.strictEqual(st.hasOverride, true);
    assert.strictEqual(st.display, true);
    assert.strictEqual(st.runtime, 'on');
    assert.strictEqual(st.pending, false);
    // неизвестный модуль (нет элемента) → known=false, не выключено
    const un = methods.getModuleState.call(
      ctx, { type: 'chat', id: -100 }, 'mod_factcheck');
    assert.strictEqual(un.known, false);
    assert.strictEqual(un.runtime, 'unknown');
    assert.strictEqual(un.display, null);
  }

  // ── (c) setModuleState: ровно одна мутация (§40) ─────────────────────
  {
    const ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [summaryItem({ chat_source: 'chat' })] });
    const res = await methods.setModuleState.call(
      ctx, { type: 'chat', id: -100 }, 'mod_summary', false);
    assert.strictEqual(writes(ctx).length, 1, 'c: ровно один write');
    const sent = writes(ctx)[0].items;
    assert.strictEqual(sent.length, 1, 'c: один элемент пакета');
    assert.strictEqual(sent[0].key, SUM);
    assert.strictEqual(sent[0].value, false);
    assert.strictEqual(sent[0].per_chat, true);
    assert.strictEqual(res.ok, true, 'c: итог ok');
    assert.strictEqual(ctx.configItems[0].value, false,
      'c: после подтверждения серверное значение = false');
    assert.strictEqual(
      methods.getModuleState.call(ctx, { type: 'chat', id: -100 }, 'mod_summary').display,
      false, 'c: все представления видят новое состояние');
  }

  // ── (d) in-flight guard по ключу (§41.2) ─────────────────────────────
  {
    let resolveP;
    const ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [summaryItem()] });
    ctx.persistItems = function (items, opts) {
      ctx.posts.push({ items: items, opts: opts || {} });
      return new Promise(function (r) { resolveP = r; });
    };
    const p1 = methods.setModuleState.call(
      ctx, { type: 'chat', id: -100 }, 'mod_summary', false);
    const r2 = await methods.setModuleState.call(
      ctx, { type: 'chat', id: -100 }, 'mod_summary', true);
    assert.strictEqual(r2.skipped, true, 'd: повтор заблокирован');
    assert.strictEqual(writes(ctx).length, 1, 'd: одна мутация на двойной тап');
    resolveP({ saved: [SUM], failed: [], skipped: [], revalidated: false,
               state: 'saved' });
    await p1;
  }

  // ── (e) Структурный откат при ошибке (§41) ───────────────────────────
  {
    const ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [summaryItem()], __fail: true });
    const res = await methods.setModuleState.call(
      ctx, { type: 'chat', id: -100 }, 'mod_summary', false);
    assert.strictEqual(res.ok, false, 'e: провал');
    assert.strictEqual(writes(ctx).length, 1, 'e: без авто-ретраев');
    assert.strictEqual(ctx.configItems[0].value, true,
      'e: configItems — серверное значение (структурный откат)');
    assert.strictEqual(
      methods.getModuleState.call(ctx, { type: 'chat', id: -100 }, 'mod_summary').display,
      true, 'e: тумблер вернулся к подтверждённому сервером значению');
    const key = 'chat/-100/mod_summary';
    assert.ok(!ctx.moduleOptimistic[key], 'e: overlay снят');
    assert.strictEqual(ctx.modulePending[key], false, 'e: pending снят');
    assert.ok(methods.moduleSaveErrorFor.call(
      ctx, moduleById('mod_summary')), 'e: понятная ошибка по ключу');
  }

  // ── (f) Stale-ответ не меняет чужой scope (§42/§73) ──────────────────
  {
    let resolveP;
    const ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [summaryItem()] });
    ctx.persistItems = function (items, opts) {
      ctx.posts.push({ items: items, opts: opts || {} });
      return new Promise(function (r) { resolveP = r; });
    };
    const scopeA = { type: 'chat', id: -100 };
    const p = methods.setModuleState.call(ctx, scopeA, 'mod_summary', false);
    // Ответ чата A ещё в полёте — администратор ушёл в чат B.
    ctx.scopeEpoch += 1;
    ctx.activeChatId = -200;
    ctx.configItems = [summaryItem()];
    ctx.posts.push({ load: true });
    resolveP({ saved: [SUM], failed: [], skipped: [], revalidated: false,
               state: 'saved' });
    await p;
    const stB = methods.getModuleState.call(ctx, { type: 'chat', id: -200 },
      'mod_summary');
    assert.strictEqual(stB.display, true, 'f: чат B не изменён stale-ответом A');
    assert.ok(!ctx.moduleOptimistic['chat/-100/mod_summary'],
      'f: overlay чата A очищен');
    assert.ok(!ctx.moduleOptimistic['chat/-200/mod_summary'],
      'f: чужой scope не получил overlay');
    // ни одной лишней серверной мутации
    const writes = ctx.posts.filter(function (x) { return x && x.items; });
    assert.strictEqual(writes.length, 1, 'f: мутация ровно одна (scope A)');
  }

  // ── (g) overlay НЕ мутирует configItems (§D2) ────────────────────────
  {
    let resolveP;
    const ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [summaryItem()] });
    ctx.persistItems = function () {
      return new Promise(function (r) { resolveP = r; });
    };
    const p = methods.setModuleState.call(
      ctx, { type: 'chat', id: -100 }, 'mod_summary', false);
    assert.strictEqual(ctx.configItems[0].value, true,
      'g: configItems не тронут оптимистично');
    assert.strictEqual(methods.moduleEnabled.call(ctx, moduleById('mod_summary')),
      false, 'g: тумблер показывает оптимистичное значение (overlay)');
    resolveP({ saved: [SUM], failed: [], skipped: [], revalidated: false,
               state: 'saved' });
    await p;
  }

  // ── (h) Счётчики §45 ─────────────────────────────────────────────────
  {
    const items = MODULES.map(function (m) {
      return item(m.toggleKey, false,
        { global_value: false, chat_source: '' });
    });
    items.filter(function (i) { return i.key === SUM; })[0].value = true;
    items.filter(function (i) {
      return i.key === 'flags.search_enabled';
    })[0].value = null;
    const ctx = mkCtx({ configItems: items });
    const c = computed.moduleCounters.call(ctx);
    assert.strictEqual(c.total, 13, 'h: всего 13');
    assert.strictEqual(c.on, 1, 'h: включён ровно 1');
    assert.strictEqual(c.off, 11, 'h: выключено 11');
    assert.strictEqual(c.issues, 1, 'h: «Есть проблемы» = 1 (неизвестное)');
    assert.strictEqual(c.total, c.on + c.off + c.issues,
      'h: инвариант Всего = Вкл + Выкл + Проблемы (noToggle нет)');

    // noToggle: только в «Всего», не в on/off/issues
    const synth = MODULES.concat([{ id: 'mod_synthetic', title: 'Синтетика',
      subtitle: 'x', icon: 'grid_view', toggleKey: 'flags.nonexistent',
      noToggle: true }]);
    const ctx2 = mkCtx({ configItems: items, modules: synth });
    ctx2.visibleModules = computed.visibleModules.call(ctx2);
    ctx2.quickpickCandidates = computed.quickpickCandidates.call(ctx2);
    const c2 = computed.moduleCounters.call(ctx2);
    assert.strictEqual(c2.total, 14, 'h: noToggle входит только в «Всего»');
    assert.strictEqual(c2.on, 1, 'h: noToggle не в «Включено»');
    assert.strictEqual(c2.off, 11, 'h: noToggle не в «Выключено»');
    assert.strictEqual(c2.issues, 1, 'h: noToggle не в «Есть проблемы»');

    // uiFlag OFF → mod_images вне витрины, поиска, панели и ВСЕХ счётчиков
    const ctx3 = mkCtx({ configItems: items,
      uiFlag: function (n) { return n !== 'IMAGE_MODULE_CARD_ENABLED'; } });
    ctx3.visibleModules = computed.visibleModules.call(ctx3);
    ctx3.quickpickCandidates = computed.quickpickCandidates.call(ctx3);
    const c3 = computed.moduleCounters.call(ctx3);
    assert.strictEqual(c3.total, 12, 'h: uiFlag OFF убирает карточку из «Всего»');
    const visIds = ctx3.visibleModules.map(function (m) { return m.id; });
    assert.strictEqual(visIds.indexOf('mod_images'), -1,
      'h: uiFlag OFF — вне витрины');
    const candIds = ctx3.quickpickCandidates.map(function (m) { return m.id; });
    assert.strictEqual(candIds.indexOf('mod_images'), -1,
      'h: uiFlag OFF — вне панели избранного');
  }

  // ── (i) Поиск/синонимы §44 ───────────────────────────────────────────
  {
    const ctx = mkCtx({ configItems: [
      item(SUM, true), item('flags.direct_chat_botword_enabled', true)] });
    function found(q) {
      const c = Object.assign(mkCtx({ configItems: ctx.configItems }),
        { moduleSearch: q });
      c.visibleModules = computed.visibleModules.call(c);
      return computed.filteredModules.call(c).map(function (m) { return m.id; });
    }
    for (const q of ['Саммари', 'сводка', 'суммаризация', 'summary']) {
      assert.ok(found(q).indexOf('mod_summary') >= 0, 'i: «' + q + '» → Сводки чатов');
    }
    for (const q of ['ответы', 'direct', 'реплай']) {
      assert.ok(found(q).indexOf('mod_direct') >= 0, 'i: «' + q + '» → Ответы в чате');
    }
    assert.ok(found('фактчек').indexOf('mod_factcheck') >= 0, 'i: фактчек');
    assert.ok(found('youtube').indexOf('mod_video_summary') >= 0, 'i: ютуб/видео');
    // поиск не сбрасывает тумблеры: runtime состояния на месте
    const c2 = Object.assign(mkCtx({ configItems: ctx.configItems }),
      { moduleSearch: 'саммари' });
    c2.visibleModules = computed.visibleModules.call(c2);
    const only = computed.filteredModules.call(c2);
    assert.strictEqual(
      methods.getModuleState.call(c2, c2.storeScope(), 'mod_summary').display,
      true, 'i: поиск сохраняет генеральный тумблер');
    assert.ok(only.length >= 1);
    // пустой результат — empty-state (нулевой список, не падение)
    assert.deepStrictEqual(found('нет-такого-модуля-zzz'), [], 'i: пустой результат');
  }

  // ── (j) Избранное в localStorage (§34–§36) ───────────────────────────
  {
    _storage._s = {};
    const ctx = mkCtx();
    methods.initQuickpicks.call(ctx);
    assert.deepStrictEqual(ctx.moduleQuickpicks,
      ['mod_summary', 'mod_direct', 'mod_factcheck', 'mod_search'],
      'j: стартовый набор §34 (fail-open)');
    assert.ok(methods.isQuickpick.call(ctx, moduleById('mod_summary')),
      'j: isQuickpick');
    // Закрепление/открепление НЕ включает модуль (ноль мутаций).
    methods.toggleQuickpick.call(ctx, moduleById('mod_search'));
    assert.strictEqual(methods.isQuickpick.call(ctx, moduleById('mod_search')),
      false, 'j: открепление');
    assert.strictEqual(writes(ctx).length, 0, 'j: избранное — ноль мутаций');
    // Сохранение/восстановление
    const raw = _storage.getItem('adminbot.modules_quickpicks.v1');
    assert.ok(raw && raw.indexOf('mod_search') < 0, 'j: запись в localStorage');
    const ctx2 = mkCtx();
    methods.initQuickpicks.call(ctx2);
    assert.strictEqual(ctx2.moduleQuickpicks.indexOf('mod_search'), -1,
      'j: восстановлено из localStorage');
    // Битый JSON → стартовый набор (fail-open)
    _storage.setItem('adminbot.modules_quickpicks.v1', '{not json');
    const ctx3 = mkCtx();
    methods.initQuickpicks.call(ctx3);
    assert.ok(ctx3.moduleQuickpicks.length >= 1,
      'j: битый JSON → fail-open стартовый набор');
    // Неизвестные id игнорируются
    _storage.setItem('adminbot.modules_quickpicks.v1',
      JSON.stringify(['mod_summary', 'ghost', 'mod_summary']));
    const ctx4 = mkCtx();
    methods.initQuickpicks.call(ctx4);
    assert.deepStrictEqual(ctx4.moduleQuickpicks, ['mod_summary'],
      'j: неизвестные id отброшены, дубли удалены');
    _storage._s = {};
  }

  // ── (k) moduleRuntimeNotice §43 ──────────────────────────────────────
  {
    // gate='global': локально включено при глобально выключенном → не работает
    const ctxG = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [item('flags.direct_chat_botword_enabled', true,
        { global_value: false, chat_source: 'chat' })] });
    assert.strictEqual(
      methods.moduleRuntimeNotice.call(ctxG, moduleById('mod_direct')),
      'Не работает: отключён глобально (локальное значение сохранено)',
      'k: gate=global');
    // gate='per_chat': локально включено работает
    const ctxP = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [item('memory.dream_enabled', true,
        { global_value: false, chat_source: 'chat' })] });
    assert.strictEqual(
      methods.moduleRuntimeNotice.call(ctxP, moduleById('mod_sleep')),
      'Включено для этой области (глобально выключено)', 'k: gate=per_chat');
    // override выключения при gate='global' не влияет
    const ctxI = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [item('flags.search_enabled', false,
        { global_value: false, chat_source: 'chat' })] });
    assert.strictEqual(
      methods.moduleRuntimeNotice.call(ctxI, moduleById('mod_search')),
      'Отключение для этой области не влияет: модуль управляется глобально',
      'k: inert override');
    // глобальная область — без модульной пометки
    const ctxGlo = mkCtx({ configItems: [summaryItem()] });
    assert.strictEqual(
      methods.moduleRuntimeNotice.call(ctxGlo, moduleById('mod_summary')), '',
      'k: global scope — пусто');
    // родительский гейт выключен → «Не работает: отключён глобально»
    const ctxPar = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [
        item('flags.checkup_enabled', true,
          { global_value: true, chat_source: '' }),
        item(SUM, false, { global_value: false, chat_source: '' }),
      ] });
    assert.strictEqual(
      methods.moduleRuntimeNotice.call(ctxPar, moduleById('mod_checkup')),
      'Не работает: отключён глобально', 'k: родительский гейт');
    // родительский гейт — глобальный выключатель: виден и в глобальной области
    const ctxParG = mkCtx({ configItems: [
      item('flags.checkup_enabled', true,
        { global_value: true, chat_source: '' }),
      item(SUM, false, { global_value: false, chat_source: '' }),
    ] });
    assert.strictEqual(
      methods.moduleRuntimeNotice.call(ctxParG, moduleById('mod_checkup')),
      'Не работает: отключён глобально', 'k: родительский гейт (global)');
    assert.strictEqual(
      methods.moduleStateText.call(ctxParG, moduleById('mod_checkup')),
      'Включён, но не работает', 'k: фактическое состояние blocked');
  }

  // ── (l) §72 единый переключатель: одно состояние на 3 представления ──
  {
    const ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [summaryItem({ chat_source: 'chat' })] });
    const m = moduleById('mod_summary');
    // панель / карточка / головной тумблер страницы — все через один store
    assert.strictEqual(methods.moduleEnabled.call(ctx, m), true, 'l: до — вкл');
    const res = await methods.toggleModule.call(ctx, m, false);
    assert.strictEqual(res.ok, true, 'l: переключение ok');
    assert.strictEqual(writes(ctx).length, 1, 'l: ровно одна мутация');
    assert.strictEqual(methods.moduleEnabled.call(ctx, m), false, 'l: панель');
    assert.strictEqual(methods.moduleEnabled.call(ctx, m), false, 'l: карточка');
    assert.strictEqual(methods.moduleEnabled.call(ctx, m), false,
      'l: головной тумблер (тот же store)');
    // симуляция перезагрузки: configItems = серверное значение
    const after = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [summaryItem({ value: false, chat_source: 'chat' })] });
    assert.strictEqual(methods.moduleEnabled.call(after, m), false,
      'l: после перезагрузки сохранено');
  }

  // ── (m) refresh/subscribe/openModuleWorkspace ────────────────────────
  {
    const ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100 });
    const okA = await methods.refreshModuleState.call(
      ctx, { type: 'chat', id: -100 }, 'mod_summary');
    assert.strictEqual(okA, true, 'm: refresh активной области');
    const before = ctx.posts.filter(function (x) { return x.load; }).length;
    const okB = await methods.refreshModuleState.call(
      ctx, { type: 'chat', id: -999 }, 'mod_summary');
    assert.strictEqual(okB, false, 'm: refresh чужой области — no-op');
    assert.strictEqual(
      ctx.posts.filter(function (x) { return x.load; }).length, before,
      'm: чужой scope не читается');

    let watchGetter = null, watchCb = null, unsub = 0;
    const sctx = { $watch: function (g, c) { watchGetter = g; watchCb = c;
      return function () { unsub += 1; }; } };
    const off = methods.subscribeModuleState.call(
      sctx, { type: 'global', id: null }, 'mod_summary', function () {});
    assert.strictEqual(typeof off, 'function', 'm: subscribe → unsubscribe');
    assert.ok(watchGetter && watchCb, 'm: $watch зарегистрирован');
    off();
    assert.strictEqual(unsub, 1, 'm: отписка сработала');

    const octx = { openModuleWindow: function (m) { octx.opened = m.id; } };
    const r = methods.openModuleWorkspace.call(octx, moduleById('mod_summary'));
    assert.strictEqual(octx.opened, 'mod_summary',
      'm: openModuleWorkspace делегирует в openModuleWindow (§D6)');
    assert.strictEqual(r, undefined);
  }

  // ── (n) configItemNotice (F3) НЕ изменён ─────────────────────────────
  {
    const notice = methods.configItemNotice.call({ scopeKind: 'chat' },
      { per_chat: true, chat_source: 'chat', global_value: false, value: true });
    assert.strictEqual(notice, 'Локально включено, хотя глобально выключено',
      'n: формулировка F3 сохранена');
  }

  // ── (o) F4-M1: gate='global' + глобально OFF + локально ON → blocked ──
  {
    // Полный набор модулей: все выключены, summary — локально включён при
    // глобально выключенном (`gate='global'` → override не действует).
    const conflictItems = function () {
      const arr = MODULES.map(function (m) {
        return item(m.toggleKey, false,
          { global_value: false, chat_source: '' });
      });
      const s = arr.filter(function (i) { return i.key === SUM; })[0];
      s.value = true; s.global_value = false; s.chat_source = 'chat';
      return arr;
    };
    const mkConflict = function (overrides) {
      const c = Object.assign(mkCtx({ scopeKind: 'chat', activeChatId: -100,
        configItems: conflictItems() }), overrides || {});
      c.visibleModules = computed.visibleModules.call(c);
      return c;
    };

    const ctx = mkConflict();
    const st = methods.getModuleState.call(
      ctx, { type: 'chat', id: -100 }, 'mod_summary');
    assert.strictEqual(st.effective, true, 'o: эффективно включён локально');
    assert.strictEqual(st.globalValue, false, 'o: глобально выключен');
    assert.strictEqual(st.runtime, 'blocked',
      'o: F4-M1 — gate=global + global OFF + effective ON → blocked');
    assert.strictEqual(
      methods.moduleStateText.call(ctx, moduleById('mod_summary')),
      'Включён, но не работает', 'o: текст фактического состояния');
    // §43: подпись notice сохранена (не изменялась фиксом).
    assert.strictEqual(
      methods.moduleRuntimeNotice.call(ctx, moduleById('mod_summary')),
      'Не работает: отключён глобально (локальное значение сохранено)',
      'o: notice §43 без изменений');

    // §45: конфликт — в «Есть проблемы», НЕ в «Включено»/«Выключено».
    const c = computed.moduleCounters.call(ctx);
    assert.strictEqual(c.on, 0, 'o: конфликт не в «Включено»');
    assert.strictEqual(c.off, 12, 'o: конфликт не в «Выключено»');
    assert.strictEqual(c.issues, 1, 'o: конфликт в «Есть проблемы»');
    assert.strictEqual(c.total, c.on + c.off + c.issues,
      'o: инвариант Всего = Вкл + Выкл + Проблемы');

    // Фильтр «Есть проблемы» включает модуль; «Включённые» — исключает.
    const idsFor = function (f) {
      return computed.filteredModules.call(mkConflict({ moduleFilter: f }))
        .map(function (m) { return m.id; });
    };
    assert.ok(idsFor('issues').indexOf('mod_summary') >= 0,
      'o: фильтр «Есть проблемы» включает конфликт');
    assert.strictEqual(idsFor('on').indexOf('mod_summary'), -1,
      'o: фильтр «Включённые» исключает конфликт');
    assert.strictEqual(idsFor('off').indexOf('mod_summary'), -1,
      'o: фильтр «Выключенные» исключает конфликт');

    // Негативный кейс: глобально ON + локально ON → работает ('on'), не blocked.
    const itemsOn = conflictItems();
    const sOn = itemsOn.filter(function (i) { return i.key === SUM; })[0];
    sOn.global_value = true;
    const ok = Object.assign(mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: itemsOn }), {});
    ok.visibleModules = computed.visibleModules.call(ok);
    const stOk = methods.getModuleState.call(
      ok, { type: 'chat', id: -100 }, 'mod_summary');
    assert.strictEqual(stOk.runtime, 'on', 'o: глобально ON → on (не blocked)');
    assert.strictEqual(
      methods.moduleStateText.call(ok, moduleById('mod_summary')),
      'Включён', 'o: negative — текст «Включён»');
    const cOk = computed.moduleCounters.call(ok);
    assert.strictEqual(cOk.on, 1, 'o: negative — в «Включено»');
    assert.strictEqual(cOk.issues, 0, 'o: negative — нет проблем');

    // gate='per_chat': локальный override работает и при глобально OFF.
    const perChat = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [item('memory.dream_enabled', true,
        { global_value: false, chat_source: 'chat' })] });
    assert.strictEqual(
      methods.getModuleState.call(
        perChat, { type: 'chat', id: -100 }, 'mod_sleep').runtime,
      'on', 'o: per_chat override работает (не blocked)');

    // Глобальная область: effective === global_value → конфликта нет.
    const gctx = mkCtx({ configItems: [item(SUM, true,
      { global_value: true, chat_source: '' })] });
    assert.strictEqual(
      methods.getModuleState.call(
        gctx, { type: 'global', id: null }, 'mod_summary').runtime,
      'on', 'o: global scope — не blocked');
  }

  console.log('MODULE-STORE-OK');
  process.exit(0);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
