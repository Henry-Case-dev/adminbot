'use strict';
/* MOD-ACL-UX-01 M4A (wave 1) — каталог из DTO + CHAT tri-state.

Предмет (design D2/D8/И-1/И-2/И-5/И-6):
  1) JS-копии каталога нет: `MODULES` в web/app.js отсутствует, 21 карточка
     применяется из DTO и совпадает с ним по title/description/order/group;
  2) 5 групп каталога в нормативном порядке, caption `21 модуль · N …`;
  3) CHAT tri-state пишет ОДИН endpoint: gate → PUT /api/chat/{id}/gates,
     param → POST /api/config (mode="inherit" | value), operation_id есть,
     scope+epoch фиксируются ДО await, двойной клик = один POST;
  4) 409 → stickyConflict + перечитывание, ВТОРОГО POST нет, черновик
     (серверное значение) не уничтожается;
  5) unknown ≠ OFF; desired=false → «Выключено»; ready=false → причина;
     can_edit=false → отказ с ролью; can_read=false → «Нет права смотреть».

Запуск: node tests/js/mod_acl_ux_m4_catalog_test.js
*/
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

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
  querySelector() { return null; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');

const { SPECS, applyModuleDto } = require('./module_fixture.js');
const data = applyModuleDto(captured);
const methods = captured.methods;
const computed = captured.computed;
const MODULES = data.modules;

(async function run() {
  try {
  let checks = 0;
  function ok(cond, msg) {
    assert.ok(cond, msg);
    checks += 1;
  }
  function eq(a, b, msg) {
    assert.strictEqual(a, b, msg);
    checks += 1;
  }

  function stateOf(patch) {
    return Object.assign({
      chat_state: 'inherit', desired: true, source: 'global',
      effective_runtime: true, ready: null, observed: null,
      observed_at: null, last_activity_at: null, emergency_block: false,
      reason_code: null, pending_restart: false, conflict: null,
      checked_at: '2026-11-17T00:00:00+00:00',
    }, patch || {});
  }
  function byId(id) {
    return MODULES.filter(function (m) { return m.id === id; })[0];
  }
  function withState(m, patch, perms) {
    return Object.assign({}, m, {
      state: stateOf(patch),
      permissions: perms || { can_read: true, can_edit: true },
    });
  }
  function mkCtx(overrides) {
    const apiCalls = [];
    const toasts = [];
    const loads = [];
    const ctx = Object.assign({}, methods, {
      modules: MODULES,
      scopeKind: 'chat',
      activeChatId: -100,
      scopeEpoch: 7,
      configChatUpdatedAt: 'ts-1',
      moduleChatPending: {},
      moduleChatError: {},
      moduleGlobalPending: {},
      moduleGlobalOptimistic: {},
      moduleGlobalError: {},
      me: { role_name: 'local_admin' },
      _opSeq: 0,
      apiCalls: apiCalls,
      toast: function (m, k) { toasts.push([m, k]); this._toasts = toasts; },
      loadConfig: async function () { loads.push(1); },
      _preserveScroll: async function (fn) { return fn && fn.call(this); },
      api: async function (url, opts) {
        apiCalls.push({ url: url, opts: opts || {} });
        if (ctx.__apiImpl) return ctx.__apiImpl(url, opts);
        return {};
      },
    });
    ctx.loads = loads;
    Object.assign(ctx, overrides || {});
    ctx.visibleModules = computed.visibleModules.call(ctx);
    return ctx;
  }

  // ── (1) Один источник: JS-каталога нет, карточки == DTO ────────────────
  {
    eq(APP_JS.indexOf('var MODULES = ['), -1,
      '1: JS-массив MODULES удалён (design D2)');
    eq(APP_JS.indexOf('var WS_MODULES = [];') >= 0, true,
      '1: рантайм-кэш DTO (не каталог)');
    eq(MODULES.length, 21, '1: 21 карточка из DTO');
    eq(SPECS.length, 21, '1: снимок DTO — 21 запись');
    const specById = {};
    SPECS.forEach(function (s) { specById['mod_' + s.id] = s; });
    MODULES.forEach(function (m) {
      const spec = specById[m.id];
      ok(spec, '1: карточка из DTO (' + m.id + ')');
      eq(m.title, spec.title, '1: title из DTO (' + m.id + ')');
      eq(m.subtitle, spec.description, '1: description из DTO (' + m.id + ')');
      eq(m.catalogOrder, spec.catalog_order, '1: order из DTO (' + m.id + ')');
      eq(m.catalogGroup, spec.catalog_group, '1: group из DTO (' + m.id + ')');
      eq(m.runtimeGate, spec.runtime_gate, '1: runtime_gate из DTO');
    });
    const ids = MODULES.map(function (m) { return m.id; });
    eq(ids.length, new Set(ids).size, '1: без дублей');
    eq(ids[0], 'mod_summary', '1: первая по catalog_order');
    eq(ids[ids.length - 1], 'mod_time', '1: последняя по catalog_order');
  }

  // ── (2) 5 групп 5/5/3/5/3 + caption ────────────────────────────────────
  {
    // Живой DTO всегда несёт state; юнит подаёт его явно (без осей unknown
    // обязан считаться «требует внимания» — И-2).
    const dtoMods = MODULES.map(function (m) { return withState(m, {}); });
    const ctx = mkCtx({ modules: dtoMods });
    ctx.filteredModules = computed.filteredModules.call(ctx);
    ctx.moduleAttentionCount = computed.moduleAttentionCount.call(ctx);
    eq(computed.moduleAttentionCount.call(ctx), 0,
      '2: observed=null само по себе не «проблема»');
    const groups = computed.moduleGroups.call(ctx);
    eq(groups.map(function (g) { return g.id; }).join(','),
      'communication,memory,autonomy,media,system',
      '2: порядок групп каталога');
    eq(groups.map(function (g) { return g.items.length; }).join(','),
      '5,5,3,5,3', '2: распределение 5/5/3/5/3');
    eq(computed.moduleCatalogCaption.call(ctx), '21 модуль',
      '2: caption без проблем');
    const opts = computed.moduleFilterOptions.call(ctx).map(function (o) {
      return o.label;
    });
    eq(opts.join('|'), 'Все|Включены|Выключены|Требуют внимания',
      '2: подписи фильтров §7.4');
  }

  // ── (3) Строка состояния: unknown ≠ OFF, причины, права ────────────────
  {
    const ctx = mkCtx();
    const summary = byId('mod_summary');
    eq(methods.moduleStateText.call(ctx, withState(summary, {})),
      'Включено · измерение не подтверждено',
      '3: observed=null — нейтрально, не «Работает»');
    eq(methods.moduleStateText.call(ctx,
      withState(summary, { desired: false, effective_runtime: false })),
      'Выключено', '3: desired=false → «Выключено»');
    eq(methods.moduleStateText.call(ctx,
      withState(summary, { desired: null, source: null,
        effective_runtime: null })),
      'Состояние неизвестно', '3: unknown ≠ OFF');
    eq(methods.moduleStateText.call(ctx,
      withState(summary, { ready: false,
        reason_code: 'provider_missing:llm' })),
      'Включено · сейчас не работает: нет провайдера',
      '3: ready=false → человеческая причина');
    eq(methods.moduleStateText.call(ctx,
      withState(summary, { emergency_block: true })),
      'Включено, но заблокировано аварийным переключателем сервера',
      '3: emergency ≠ OFF');
    eq(methods.moduleStateText.call(ctx,
      withState(summary, {}, { can_read: false, can_edit: false })),
      'Нет права смотреть', '3: can_read=false → отказ, не OFF');
    eq(methods.moduleStateText.call(ctx,
      withState(summary, { observed: true, effective_runtime: true })),
      'Работает', '3: observed=true → «Работает»');
    // Чипы осей: иконка И текст (WCAG 1.4.1).
    const chips = methods.moduleStateChips.call(ctx, withState(summary, {}));
    eq(chips.length, 5, '3: пять чипов осей');
    chips.forEach(function (c) {
      ok(c.icon && c.text && c.label, '3: чип с иконкой и текстом');
    });
    ok(chips.some(function (c) {
      return c.id === 'observed' && c.text === 'Измерение не подтверждено';
    }), '3: observed=null — «Измерение не подтверждено»');
    // observed=false — «нет подтверждённой активности» (не «Норма»).
    const chipsFalse = methods.moduleStateChips.call(ctx,
      withState(summary, { observed: false }));
    ok(chipsFalse.some(function (c) {
      return c.id === 'observed' &&
        c.text === 'Нет подтверждённой активности';
    }), '3: observed=false — «Нет подтверждённой активности»');
  }

  // ── (4) CHAT tri-state: param-путь — один POST на ключ ─────────────────
  {
    const ctx = mkCtx();
    const m = withState(byId('mod_summary'), {});
    let res = await methods.setModuleChatTriState.call(ctx, m, 'on');
    eq(res.ok, true, '4: ON записан');
    eq(ctx.apiCalls.length, 1, '4: ровно ОДИН POST');
    const call = ctx.apiCalls[0];
    eq(call.url, '/api/config', '4: param-путь → POST /api/config');
    eq(call.opts.method, 'POST', '4: метод POST');
    eq(call.opts.chatId, -100, '4: X-Chat-Id этой области');
    const body = JSON.parse(call.opts.body);
    eq(body.items.length, 1, '4: один элемент (одна группа)');
    eq(body.items[0].key, 'flags.summary_enabled', '4: ключ мастера');
    eq(body.items[0].value, true, '4: ON → explicit bool');
    ok(body.operation_id, '4: operation_id есть');
    eq(body.updated_at, 'ts-1', '4: optimistic token передан');
    eq(ctx.loads.length, 1, '4: после ответа — перечитывание');
    ok(ctx._toasts.some(function (t) { return t[0] === 'Настройка сохранена'; }),
      '4: успех — только после ответа');

    const offCtx = mkCtx();
    await methods.setModuleChatTriState.call(offCtx, m, 'off');
    const offBody = JSON.parse(offCtx.apiCalls[0].opts.body);
    eq(offBody.items[0].value, false, '4: OFF → explicit false');

    const inhCtx = mkCtx();
    await methods.setModuleChatTriState.call(inhCtx, m, 'inherit');
    const inhBody = JSON.parse(inhCtx.apiCalls[0].opts.body);
    eq(inhBody.items[0].mode, 'inherit',
      '4: INHERIT → mode="inherit" (снятие override)');
    eq(inhBody.items[0].value, undefined, '4: inherit не пишет значение');
  }

  // ── (5) CHAT tri-state: gate-путь — PUT /gates, без второго эндпоинта ──
  {
    const m = withState(byId('mod_nostalgia'), {});
    for (const pair of [['inherit', 'inherit'], ['on', true], ['off', false]]) {
      const ctx = mkCtx();
      await methods.setModuleChatTriState.call(ctx, m, pair[0]);
      eq(ctx.apiCalls.length, 1, '5: один вызов на ' + pair[0]);
      eq(ctx.apiCalls[0].url, '/api/chat/-100/gates',
        '5: gate → PUT /api/chat/{id}/gates');
      eq(ctx.apiCalls[0].opts.method, 'PUT', '5: PUT');
      const body = JSON.parse(ctx.apiCalls[0].opts.body);
      eq(body.feature, 'nostalgia', '5: feature из DTO');
      eq(body.enabled, pair[1], '5: enabled ' + pair[0]);
    }
  }

  // ── (6) epoch ДО await: поздний ответ чужой области не применяется ─────
  {
    let release;
    const gate = new Promise(function (res) { release = res; });
    const ctx = mkCtx();
    ctx.__apiImpl = function () { return gate; };
    const m = withState(byId('mod_summary'), {});
    const p = methods.setModuleChatTriState.call(ctx, m, 'on');
    ctx.scopeEpoch = 99;                 // «переключили чат», пока летит POST
    release({});
    const res = await p;
    eq(res.stale, true, '6: поздний ответ помечен stale');
    eq(ctx.loads.length, 0, '6: чужой scope не перечитывается');
    eq((ctx._toasts || []).filter(function (t) {
      return t[0] === 'Настройка сохранена';
    }).length, 0, '6: ложного «Настройка сохранена» нет');
  }

  // ── (7) Двойной клик = один POST; 409 = stickyConflict, без повтора ────
  {
    let release;
    const gate = new Promise(function (res) { release = res; });
    const ctx = mkCtx();
    ctx.__apiImpl = function () { return gate; };
    const m = withState(byId('mod_summary'), {});
    const p1 = methods.setModuleChatTriState.call(ctx, m, 'on');
    const r2 = await methods.setModuleChatTriState.call(ctx, m, 'on');
    eq(r2.skipped, true, '7: повторный тап — skipped');
    eq(ctx.apiCalls.length, 1, '7: двойной клик не создаёт второй POST');
    release({});
    await p1;

    const c409 = mkCtx();
    c409.__apiImpl = function () {
      const err = new Error('409');
      err.status = 409;
      err.message = { code: 'conflict', conflicting: ['flags.summary_enabled'] };
      throw err;
    };
    const res = await methods.setModuleChatTriState.call(
      c409, m, 'inherit');
    eq(res.error, 'conflict', '7: 409 распознан');
    const posts409 = c409.apiCalls.filter(function (c) {
      return (c.opts || {}).method === 'POST';
    });
    eq(posts409.length, 1, '7: автоповтора/второго POST нет');
    eq(c409.stickyConflict.length, 1, '7: stickyConflict заполнен');
    eq(c409.stickyConflict[0], 'flags.summary_enabled',
      '7: конфликтующий ключ — в баннере');
    // D4 (review): 409 не перезагружает состояние автоматически; только
    // отдельный GET для diff «на сервере» и явный выбор пользователя.
    eq(c409.loads.length, 0, '7: 409 без авто-loadConfig (D4)');
    ok(methods.moduleConflictFor.call(c409, m), '7: diff сохранён (D4)');
    ok(c409._toasts.some(function (t) {
      return t[0] === 'Настройка изменилась в другом окне';
    }), '7: человеческий баннер 409');
    ok(c409._toasts.every(function (t) {
      return t[0] !== 'Настройка сохранена';
    }), '7: ложного «Сохранено» при 409 нет');
  }

  // ── (8) Права: can_edit=false → disabled + роль, запроса нет ───────────
  {
    const ctx = mkCtx();
    const m = withState(byId('mod_summary'), {},
      { can_read: true, can_edit: false });
    const res = await methods.setModuleChatTriState.call(ctx, m, 'on');
    eq(res.error, 'forbidden', '8: без права — отказ');
    eq(ctx.apiCalls.length, 0, '8: запрос не отправлен');
    ok(ctx._toasts.some(function (t) {
      return t[0].indexOf('Только просмотр') < 0 &&
        t[0].indexOf('Нет права изменить') >= 0 && t[0].indexOf('local_admin') >= 0;
    }), '8: отказ называет роль');
    eq(methods.moduleChatCanEdit.call(ctx, m), false,
      '8: контрол disabled (can_edit=false)');
    eq(methods.moduleChatReadonlyReason.call(ctx, m),
      'Только просмотр. Ваша роль: local_admin',
      '8: read-only причина по роли');
    // can_read=false → отказ, не пустая таблица.
    const denied = withState(byId('mod_summary'), {},
      { can_read: false, can_edit: false });
    eq(methods.modulePermissions.call(ctx, denied).can_read, false,
      '8: can_read=false приходит из DTO');
    eq(methods.moduleStateText.call(ctx, denied), 'Нет права смотреть',
      '8: отказ вместо пустой таблицы');
  }

  // ── (9) Глагольные подписи CHAT (copy-inventory §3.1) ──────────────────
  {
    const ctx = mkCtx();
    eq(methods.moduleChatLabel.call(ctx, byId('mod_summary')),
      'Формировать сводки в этом чате', '9: подпись Summary');
    eq(methods.moduleChatLabel.call(ctx, byId('mod_nostalgia')),
      'Возвращать прошлые события в этом чате', '9: подпись Nostalgia');
    eq(methods.moduleChatLabel.call(ctx, byId('mod_time')),
      'Часовой пояс этого чата', '9: подпись Time');
    const noToggle = byId('mod_time');
    eq(methods.moduleChatControlAvailable.call(ctx, noToggle), false,
      '9: «Время» без тумблера');
  }

  console.log('MOD-ACL-UX-01 M4A CATALOG OK — ' + checks + ' проверок');
  } catch (e) {
    console.error(e && e.stack ? e.stack : e);
    process.exit(1);
  }
})();

