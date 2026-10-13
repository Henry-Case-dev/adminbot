'use strict';
/* D07 (ASAP 8 v6, Wave C) — global-view popover переопределивших чатов.
 *
 * Контракт (v5 §9B.2/§9B.3, v6 §C D07):
 *   (a) карта overrides грузится в global view и гвардится scopeEpoch
 *       (D01: устаревший ответ не мутирует UI);
 *   (b) avatar stack mapping: overrideRowsFor группирует по ключу,
 *       extraCount = «+N» после первых двух аватаров;
 *   (c) формат значения popover: bool → ON/OFF, объект → JSON, обрезка 60;
 *   (d) «Вернуть глобальные» удаляет ТОЛЬКО chat override выбранного чата
 *       (DELETE /api/config/chat/<key> с явным X-Chat-Id); global-путь
 *       (POST /api/config без X-Chat-Id) НЕ вызывается — global value
 *       не меняется;
 *   (e) «Отключить в этом чате» пишет ТОЛЬКО chat override (POST
 *       /api/config с явным X-Chat-Id, value=false);
 *   (f) deep-link «Открыть настройки чата» переключает activeChatId;
 *   (g) bulk — ТОЛЬКО через explicit confirm с перечислением affected
 *       chats; смена scope посреди цикла прерывает остаток;
 *   (h) api(): явный chatIdpopover-действий старше активной области;
 *   (i) RBAC-гейт строки: moderator не получает кнопок записи.
 *
 * Запуск: node tests/js/asap8_v6_d07_override_stack_test.js
 */
const path = require('path');
const assert = require('assert');

let captured = null;
const components = {};
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component: function (name, def) { components[name] = def; },
      use() {}, provide() {}, directive() {}, mount() {},
    };
  },
};
const _storage = { _s: { 'adminbot.initData': 'test-init-data' },
  getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; } };
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; },
};
global.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };

// fetch-прокси: переключаемый обработчик (по умолчанию — ошибка сети).
let fetchHandler = null;
global.fetch = async function (path, init) {
  if (!fetchHandler) throw new Error('no fetch handler in test');
  return fetchHandler(path, init);
};

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
assert(components['override-stack'], 'компонент override-stack зарегистрирован');

// ── ctx: достаточный для вызова методов без полного стейта приложения ──
function makeCtx(overrides) {
  const calls = [];
  const ctx = {
    scopeEpoch: 3,
    activeChatId: null,
    overrideMap: [],
    overrideMapBusy: false,
    overrideBusy: {},
    saving: new Set(),
    authLocked: false,
    toasts: [],
    toast: function (text, kind) { calls.push(['toast', text, kind]); },
    _scopeGuard: methods._scopeGuard,
    overrideCanWriteRow: methods.overrideCanWriteRow,
    overrideRowBusy: methods.overrideRowBusy,
    hasInitData: function () { return true; },
    setActiveChat: function (id) { calls.push(['setActiveChat', id]); },
    loadOverrideMap: async function () { calls.push(['loadOverrideMap']); },
    api: async function (pathUrl, options) {
      calls.push(['api', pathUrl, options || {}]);
      return { items: [] };
    },
    calls: calls,
  };
  return Object.assign(ctx, overrides || {});
}

const MAP_ITEMS = [
  { key: 'limits.search_max_symbols', chat_id: -100, chat_title: 'Chat A',
    value: false, source: 'chat', access: 'global_admin', is_dm: false },
  { key: 'limits.search_max_symbols', chat_id: -200, chat_title: 'Chat B',
    value: 'gpt-x', source: 'chat', access: 'local_admin', is_dm: false },
  { key: 'memory.infinite_retention', chat_id: -300, chat_title: 'Chat C',
    value: true, source: 'chat', access: 'global_admin', is_dm: false },
  { key: 'memory.infinite_retention', chat_id: 777, chat_title: 'ЛС',
    value: 1, source: 'chat', access: 'dm', is_dm: true },
];

(async function run() {
  // ── (a) loadOverrideMap: применение + D01-гвард устаревшего scope ──
  {
    const ctx = makeCtx({
      api: async function () { return { items: MAP_ITEMS }; },
    });
    const p = methods.loadOverrideMap.call(ctx);
    ctx.scopeEpoch = 9;                    // scope сменился ДО ответа
    await p;
    assert.strictEqual(ctx.overrideMap.length, 0,
      'устаревший (чужой scope) ответ карты не применяется (D01)');
    assert.strictEqual(ctx.overrideMapBusy, true,
      'stale-замыкание не трогает общий флаг (R3: владелец — актуальный scope)');
  }
  {
    const ctx = makeCtx({
      api: async function () { return { items: MAP_ITEMS }; },
    });
    await methods.loadOverrideMap.call(ctx);
    assert.strictEqual(ctx.overrideMap.length, 4);
    assert.strictEqual(ctx.overrideMapBusy, false);
  }
  {
    const ctx = makeCtx({
      api: async function () { throw { status: 403, message: 'нет' }; },
    });
    await methods.loadOverrideMap.call(ctx);
    assert.deepStrictEqual(ctx.overrideMap, [],
      '403/ошибка → честно пусто (стек не рендерится), без броска');

  }

  // ── (b) overrideRowsFor: группировка по ключу ──
  {
    const ctx = makeCtx({ overrideMap: MAP_ITEMS });
    const rows = methods.overrideRowsFor.call(ctx, 'memory.infinite_retention');
    assert.strictEqual(rows.length, 2);
    assert.deepStrictEqual(rows.map(function (r) { return r.chat_id; }),
                           [-300, 777]);
    assert.strictEqual(methods.overrideRowsFor.call(ctx, 'nope.key').length, 0);
  }

  // ── (c) formatOverrideValue: OFF/ON/JSON/обрезка ──
  {
    const ctx = makeCtx({});
    const f = function (v) { return methods.formatOverrideValue.call(ctx, v); };
    assert.strictEqual(f(false), 'OFF');
    assert.strictEqual(f(true), 'ON');
    assert.strictEqual(f('gpt-x'), 'gpt-x');
    assert.strictEqual(f({ a: 1 }), '{"a":1}');
    assert.strictEqual(f(null), '—');
    const long = 'y'.repeat(80);
    assert.strictEqual(f(long).length, 58,
      'длинное значение обрезается (57 + многоточие)');
    assert.ok(f(long).endsWith('…'));
  }

  // ── (d) resetOverrideInChat: DELETE только chat override ──
  {
    const ctx = makeCtx({ overrideMap: MAP_ITEMS.slice() });
    const row = { chat_id: -100, chat_title: 'Chat A', access: 'global_admin' };
    await methods.resetOverrideInChat.call(ctx, row,
                                          'limits.search_max_symbols', 'Лимит');
    const apiCalls = ctx.calls.filter(function (c) { return c[0] === 'api'; });
    assert.strictEqual(apiCalls.length, 1);
    const [, url, opts] = apiCalls[0];
    assert.strictEqual(url, '/api/config/chat/limits.search_max_symbols');
    assert.strictEqual(opts.method, 'DELETE');
    assert.strictEqual(opts.chatId, -100,
      'удаление адресует КОНКРЕТНЫЙ чат (явный X-Chat-Id)');
    assert.ok(!ctx.calls.some(function (c) {
      return c[0] === 'api' && c[1] === '/api/config' && (!c[2] || !c[2].chatId);
    }), 'global-путь (без X-Chat-Id) НЕ вызывается — global value не меняется');
    assert.ok(ctx.calls.some(function (c) {
      return c[0] === 'loadOverrideMap';
    }), 'карта перечитывается после сброса');
    assert.ok(ctx.calls.some(function (c) {
      return c[0] === 'toast' && c[2] === 'ok';
    }));
  }
  {
    // moderator-строка: кнопки записи недоступны → без confirm, без api
    const ctx = makeCtx({});
    const row = { chat_id: -100, chat_title: 'Chat A', access: 'moderator' };
    await methods.resetOverrideInChat.call(ctx, row, 'k.x', 'K');
    assert.strictEqual(ctx.calls.filter(function (c) {
      return c[0] === 'api';
    }).length, 0, 'moderator не получает действие сброса');
    assert.ok(ctx.calls.some(function (c) {
      return c[0] === 'toast' && c[2] === 'err';
    }));
  }
  {
    // отказ в confirm → ничего не пишется
    const origConfirm = global.window.confirm;
    global.window.confirm = function () { return false; };
    try {
      const ctx = makeCtx({});
      await methods.resetOverrideInChat.call(
        ctx, { chat_id: -100, chat_title: 'A', access: 'global_admin' },
        'k.x', 'K');
      assert.strictEqual(ctx.calls.filter(function (c) {
        return c[0] === 'api';
      }).length, 0, 'без explicit confirm записи нет');
    } finally {
      global.window.confirm = origConfirm;
    }
  }

  // ── (e) disableOverrideInChat: POST только chat override, value=false ──
  {
    const ctx = makeCtx({});
    await methods.disableOverrideInChat.call(
      ctx, { chat_id: -200, chat_title: 'Chat B', access: 'local_admin' },
      'limits.search_max_symbols', 'Лимит');
    const apiCalls = ctx.calls.filter(function (c) { return c[0] === 'api'; });
    assert.strictEqual(apiCalls.length, 1);
    const [, url, opts] = apiCalls[0];
    assert.strictEqual(url, '/api/config');
    assert.strictEqual(opts.method, 'POST');
    assert.strictEqual(opts.chatId, -200);
    const body = JSON.parse(opts.body);
    assert.deepStrictEqual(body.items,
      [{ key: 'limits.search_max_symbols', value: false }],
      'пишется ТОЛЬКО явный chat OFF');
  }

  // ── (f) deep-link: открыть настройки чата ──
  {
    const ctx = makeCtx({});
    methods.openOverrideChatSettings.call(
      ctx, { chat_id: -300, chat_title: 'Chat C' });
    assert.ok(ctx.calls.some(function (c) {
      return c[0] === 'setActiveChat' && c[1] === '-300';
    }), 'deep-link переключает область на чат');
  }

  // ── (g) bulk: confirm с перечислением; abort при смене scope ──
  {
    const seenConfirms = [];
    const origConfirm = global.window.confirm;
    global.window.confirm = function (msg) { seenConfirms.push(msg); return true; };
    try {
      const rows = [
        { chat_id: -100, chat_title: 'Chat A', access: 'global_admin' },
        { chat_id: -200, chat_title: 'Chat B', access: 'global_admin' },
        { chat_id: -300, chat_title: 'Chat C', access: 'moderator' },
      ];
      const ctx = makeCtx({});
      await methods.resetAllOverridesInChats.call(ctx, rows, 'k.x', 'Параметр');
      const msg = seenConfirms[seenConfirms.length - 1];
      assert.ok(msg.indexOf('Chat A') >= 0 && msg.indexOf('Chat B') >= 0,
        'confirm перечисляет affected chats');
      assert.ok(msg.indexOf('Chat C') < 0,
        'чаты без права записи не попадают в bulk');
      const deletes = ctx.calls.filter(function (c) {
        return c[0] === 'api' && c[2].method === 'DELETE';
      });
      assert.strictEqual(deletes.length, 2);
      assert.deepStrictEqual(deletes.map(function (c) { return c[2].chatId; }),
        [-100, -200]);
    } finally {
      global.window.confirm = origConfirm;
    }
  }
  {
    // отказ в bulk-confirm → ноль записей
    const origConfirm = global.window.confirm;
    global.window.confirm = function () { return false; };
    try {
      const ctx = makeCtx({});
      await methods.resetAllOverridesInChats.call(ctx, [
        { chat_id: -100, chat_title: 'A', access: 'global_admin' },
      ], 'k.x', 'K');
      assert.strictEqual(ctx.calls.filter(function (c) {
        return c[0] === 'api';
      }).length, 0, 'bulk без confirm не выполняется вовсе');
    } finally {
      global.window.confirm = origConfirm;
    }
  }
  {
    // смена scope посреди цикла: остаток чатов не трогается
    const origConfirm = global.window.confirm;
    global.window.confirm = function () { return true; };
    try {
      const ctx = makeCtx({});
      ctx.api = async function (url, opts) {
        ctx.calls.push(['api', url, opts || {}]);
        if (opts && opts.chatId === -100) ctx.scopeEpoch = 77;  // смена scope
        return {};
      };
      await methods.resetAllOverridesInChats.call(ctx, [
        { chat_id: -100, chat_title: 'A', access: 'global_admin' },
        { chat_id: -200, chat_title: 'B', access: 'global_admin' },
        { chat_id: -300, chat_title: 'C', access: 'global_admin' },
      ], 'k.x', 'K');
      const deleted = ctx.calls.filter(function (c) {
        return c[0] === 'api';
      }).map(function (c) { return c[2].chatId; });
      assert.deepStrictEqual(deleted, [-100],
        'после смены scope остаток цикла прерывается (D01)');
      assert.strictEqual(ctx.overrideBusy['all:k.x'], undefined,
        'bulk-флаг снимается даже при abort');
    } finally {
      global.window.confirm = origConfirm;
    }
  }

  // ── (h) api(): явный chatId старше активной области ──
  {
    const seen = [];
    const origFetch = global.fetch;
    global.fetch = async function (url, init) {
      seen.push({ url: url, headers: init.headers });
      return { ok: true, status: 200, json: async function () { return {}; } };
    };
    try {
      const ctx = makeCtx({ activeChatId: 5 });
      await methods.api.call(ctx, '/api/config/overrides-map',
                             { global: true });
      assert.strictEqual(seen[0].headers['X-Chat-Id'], undefined,
        'global:true — без X-Chat-Id');
      await methods.api.call(ctx, '/api/config/chat/k.x',
                             { method: 'DELETE', chatId: -100 });
      assert.strictEqual(seen[1].headers['X-Chat-Id'], '-100',
        'явный chatId popover-действия старше активной области');
      await methods.api.call(ctx, '/api/config');
      assert.strictEqual(seen[2].headers['X-Chat-Id'], '5',
        'без chatId — прежнее поведение (активная область)');
      const ctx2 = makeCtx({ activeChatId: null });
      await methods.api.call(ctx2, '/api/config');
      assert.strictEqual(seen[3].headers['X-Chat-Id'], undefined,
        'global scope — заголовка нет (не сломано)');
    } finally {
      global.fetch = origFetch;
    }
  }

  // ── (i) компонент override-stack: mapping/гейты ──
  {
    const comp = components['override-stack'];
    const moderatorRow = { key: 'k.x', chat_id: -400, chat_title: 'Chat M',
                           value: false, source: 'chat', access: 'moderator',
                           is_dm: false };
    const root = {
      overrideRowsFor: function (k) {
        return k === 'k.x'
          ? [MAP_ITEMS[0], MAP_ITEMS[1], moderatorRow] : [];
      },
      overrideCanWriteRow: methods.overrideCanWriteRow,
      formatOverrideValue: methods.formatOverrideValue,
      openOverrideChatSettings: function () {},
      disableOverrideInChat: function () {},
      resetOverrideInChat: function () {},
      resetAllOverridesInChats: function () {},
    };
    const vm = {
      root: root, itemKey: 'k.x', itemTitle: 'Параметр', itemType: 'bool',
      open: false, close: comp.methods.close,
    };
    // computed-цепочка: rows → shown/extraCount/writableRows
    Object.defineProperty(vm, 'rows', {
      get: function () { return comp.computed.rows.call(vm); },
      configurable: true,
    });
    Object.defineProperty(vm, 'shown', {
      get: function () { return comp.computed.shown.call(vm); },
      configurable: true,
    });
    const rows = comp.computed.rows.call(vm);
    assert.strictEqual(rows.length, 3);
    assert.strictEqual(comp.computed.shown.call(vm).length, 2,
      'в стеке первые 2 аватара');
    assert.strictEqual(comp.computed.extraCount.call(vm), 1,
      '«+N» = остальное');
    assert.strictEqual(comp.computed.canDisable.call(vm), true);
    assert.strictEqual(comp.computed.canDisable.call(
      Object.assign({}, vm, { itemType: 'str' })), false,
      '«Отключить в чате» — если применимо (bool)');
    const writable = comp.computed.writableRows.call(vm);
    assert.strictEqual(writable.length, 2,
      'moderator-строки не участвуют в bulk');
    // actions закрывают popover и делегируют в root
    let opened = null;
    vm.root.openOverrideChatSettings = function (r) { opened = r; };
    comp.methods.openChat.call(vm, rows[0]);
    assert.strictEqual(vm.open, false, 'popover закрывается перед действием');
    assert.strictEqual(opened.chat_id, -100);
    // fmt делегирует форматтеру root
    assert.strictEqual(comp.methods.fmt.call(vm, false), 'OFF');
    // пустой map → компонент не должен рендериться (v-if="rows.length");
    // фиксируем контракт вычисления rows для чужого ключа
    assert.strictEqual(comp.computed.rows.call(
      Object.assign({}, vm, { itemKey: 'other' })).length, 0);
  }

  console.log('D07-OVERRIDE-STACK-OK');
})().catch(function (e) {
  console.error('FAIL:', e && e.message);
  if (e && e.stack) console.error(e.stack);
  process.exit(1);
});
