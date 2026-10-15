'use strict';
/* ASAP 8 v6.3 W3-MODULES-UI — B06 (переключатели управляют runtime),
 * B07 (Temporal — секция Фактчека, НЕ карточка), B01.4 (per-chat профиль
 * частоты Инициативы).
 *
 * TEST-LIFECYCLE: CONTRACT owner=REQ-B06/REQ-B07/REQ-B01-4 (UI-часть).
 *
 * Проверяет:
 *   B06.1: mod_summary runtimeGate='per_chat' (витрина = единому резолверу
 *          services/summary_scheduler.summary_effective_enabled); текст
 *          причины соответствует резолву — chat override ON при global OFF /
 *          chat override OFF / inherit; «не влияет; глобально» у Summary
 *          НЕТ ни в одном состоянии; setModuleState на chat-scope реально
 *          пишет per_chat-ключ;
 *   B06.2: global-only карточки (Direct/Фактчек/Поиск/Инициатива) на чате —
 *          read-only (moduleChatToggleReadonly), setModuleState отказывает
 *          БЕЗ серверной мутации (инертный override не создаётся); на
 *          global-области тумблер активен;
 *   B07:   TABS mod_factcheck содержит temporal-правило (зеркало TAB_RULES);
 *          группа temporal_factcheck рендерится на settings-вкладке
 *          workspace; человекочитаемые подписи (tool_enabled → «Проверять
 *          дату и актуальность», группа → «Время и источники»); карточка
 *          «Временная проверка» в витрине модулей ОТСУТСТВУЕТ (hidden
 *          реестра не добавляется);
 *   B01.4: карта модуля «Инициатива» подтягивает flags_intent/limits_intent
 *          (per-chat гейт initiative.enabled + тонкие лимиты); профиль
 *          частоты — select редко/нормально/активно (rare/normal/active);
 *          жаргонная подпись наблюдателя заменена display-оверрайдом.
 *
 * Запуск: node tests/js/asap8_v63_w3_modules_ui_test.js
 *         → W3-MODULES-UI-OK
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
const TABS = data.tabs;

function item(key, value, extra) {
  return Object.assign(
    { key: key, value: value, per_chat: true, global_value: value },
    extra || {});
}
function moduleById(id) {
  return MODULES.filter(function (m) { return m.id === id; })[0];
}
function mkCtx(overrides) {
  const calls = [];
  const ctx = Object.assign({}, methods, {
    modules: MODULES,
    tabs: TABS,
    configGroups: [],
    scopeKind: 'global',
    activeChatId: null,
    scopeEpoch: 0,
    configItems: [],
    moduleOptimistic: {},
    modulePending: {},
    moduleSaveError: {},
    moduleQuickpicks: null,
    moduleSearch: '',
    moduleFilter: 'all',
    stickyFailedKeys: [],
    me: null,
    _opSeq: 0,
    saving: new Set(),
    toasts: [],
    toast: function (t, k) { this.toasts.push(k || 'ok'); },
    uiFlag: function () { return true; },
    isGlobalAdmin: true,
    canEditConfig: function () { return true; },
    canEditModule: methods.canEditModule,
    _findConfigItem: methods._findConfigItem,
    _preserveScroll: function (fn) { return fn && fn.call(ctx); },
    loadConfig: async function () { calls.push({ load: true }); },
    posts: calls,
    persistItems: async function (items, opts) {
      calls.push({ items: items, opts: opts || {} });
      items.forEach(function (it) {
        const found = (ctx.configItems || []).filter(function (i) {
          return i.key === it.key;
        })[0];
        if (found) found.value = it.value;
      });
      return { saved: items.map(function (i) { return i.key; }), failed: [],
               skipped: [], revalidated: false, state: 'saved' };
    },
  });
  Object.assign(ctx, overrides || {});
  return ctx;
}
function writes(ctx) {
  return (ctx.posts || []).filter(function (x) { return x && x.items; });
}

(async function run() {
  // ═══ B06.1: Summary — per_chat, честный резолв ══════════════════════════
  {
    const sum = moduleById('mod_summary');
    assert.strictEqual(sum.runtimeGate, 'per_chat',
      'B06.1: витрина Summary = резолверу (per_chat)');
    const chatCtx = mkCtx({ scopeKind: 'chat', activeChatId: -100 });

    // (1) chat override ON при global OFF — работает (не «не работает»).
    let ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [item('flags.summary_enabled', true,
        { global_value: false, chat_source: 'chat' })] });
    assert.strictEqual(methods.moduleRuntimeNotice.call(ctx, sum),
      'Включено для этой области (глобально выключено)',
      'B06.1: chat ON / global OFF — резолв chat override');
    assert.strictEqual(
      methods.getModuleState.call(
        ctx, { type: 'chat', id: -100 }, 'mod_summary').runtime, 'on');
    assert.ok(methods.moduleRuntimeNotice.call(ctx, sum)
      .indexOf('не влияет') < 0, 'B06.1: лжи «не влияет» нет');

    // (2) chat override OFF — выключено в этом чате (глобальный ON).
    ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [item('flags.summary_enabled', false,
        { global_value: true, chat_source: 'chat' })] });
    assert.strictEqual(methods.moduleRuntimeNotice.call(ctx, sum),
      'Выключено в этом чате',
      'B06.1: chat OFF / global ON — локальный OFF глушит только чат');

    // (3) inherit OFF (без override) — без «отключён глобально» в чате.
    ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [item('flags.summary_enabled', false,
        { global_value: false, chat_source: '' })] });
    assert.strictEqual(methods.moduleRuntimeNotice.call(ctx, sum), '',
      'B06.1: inherit OFF — наследованное значение без шума');

    // (4) inherit ON — без пометки.
    ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [item('flags.summary_enabled', true,
        { global_value: true, chat_source: '' })] });
    assert.strictEqual(methods.moduleRuntimeNotice.call(ctx, sum), '',
      'B06.1: inherit ON — без пометки');

    // setModuleState на chat-scope пишет per_chat-ключ (тумблер активен).
    ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [item('flags.summary_enabled', true,
        { global_value: true, chat_source: '' })] });
    const res = await methods.setModuleState.call(
      ctx, { type: 'chat', id: -100 }, 'mod_summary', false);
    assert.strictEqual(res.ok, true, 'B06.1: chat-scope toggle активен');
    assert.strictEqual(writes(ctx).length, 1,
      'B06.1: ровно одна мутация');
    assert.strictEqual(writes(ctx)[0].items[0].key, 'flags.summary_enabled');
    assert.strictEqual(writes(ctx)[0].items[0].per_chat, true,
      'B06.1: пер-чат слой (X-Chat-Id)');

    // Тумблер read-only НЕ для Summary на чате.
    assert.strictEqual(
      methods.moduleChatToggleReadonly.call(chatCtx, sum), false,
      'B06.1: Summary chat-scope — тумблер не read-only');
  }

  // ═══ B06.2: global-only карточки — read-only на чате ════════════════════
  {
    const chatCtx = mkCtx({ scopeKind: 'chat', activeChatId: -100 });
    const globalOnly = ['mod_direct', 'mod_factcheck', 'mod_search',
                        'mod_transcribe', 'mod_video_summary',
                        'mod_media_download', 'mod_web', 'mod_checkup',
                        'mod_initiative'];
    globalOnly.forEach(function (id) {
      assert.strictEqual(
        methods.moduleChatToggleReadonly.call(chatCtx, moduleById(id)),
        true, 'B06.2: ' + id + ' на чате read-only');
    });
    const perChatCards = ['mod_summary', 'mod_sleep', 'mod_nostalgia',
                          'mod_budgets', 'mod_images', 'mod_vision'];
    perChatCards.forEach(function (id) {
      assert.strictEqual(
        methods.moduleChatToggleReadonly.call(chatCtx, moduleById(id)),
        false, 'B06.2: ' + id + ' на чате активен');
    });
    // На global-области все активны (для правящих).
    globalOnly.concat(perChatCards).forEach(function (id) {
      assert.strictEqual(
        methods.moduleChatToggleReadonly.call(
          mkCtx({ scopeKind: 'global' }), moduleById(id)),
        false, 'B06.2: ' + id + ' на global активен');
    });

    // setModuleState: инертный override не создаётся (нет серверной мутации).
    const ctx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      configItems: [item('flags.factcheck_enabled', true,
        { global_value: true, chat_source: '' })] });
    const res = await methods.setModuleState.call(
      ctx, { type: 'chat', id: -100 }, 'mod_factcheck', false);
    assert.strictEqual(res.ok, false, 'B06.2: global-only на чате — отказ');
    assert.strictEqual(res.error, 'global-only',
      'B06.2: причина отказа честная');
    assert.strictEqual(writes(ctx).length, 0,
      'B06.2: инертный override НЕ отправляется на сервер');

    // «Настроить глобально»: переход в «Весь бот» существующим каналом.
    const nav = [];
    const navCtx = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      setActiveChat: function (id) { nav.push(id); } });
    methods.configureModuleGlobally.call(navCtx, moduleById('mod_factcheck'));
    assert.deepStrictEqual(nav, [null],
      'B06.2: «Настроить глобально» → setActiveChat(null)');
    // Не глобальный админ: перехода нет, честное предупреждение.
    const den = mkCtx({ scopeKind: 'chat', activeChatId: -100,
      isGlobalAdmin: false,
      setActiveChat: function (id) { nav.push(id); } });
    methods.configureModuleGlobally.call(den, moduleById('mod_factcheck'));
    assert.strictEqual(nav.length, 1,
      'B06.2: без прав глобальной области перехода нет');
    assert.ok(den.toasts.indexOf('warn') >= 0,
      'B06.2: не глобальному админу — предупреждение');
    // Хинт без жаргона.
    assert.strictEqual(
      methods.moduleGlobalHint.call(chatCtx, moduleById('mod_factcheck')),
      'Управляется глобально — общий рубильник для всех чатов',
      'B06.2: хинт read-only человекочитаем');
    assert.strictEqual(
      methods.moduleGlobalHint.call(chatCtx, moduleById('mod_summary')), '',
      'B06.2: у per_chat карточек хинта нет');
  }

  // ═══ B07: Temporal — секция Фактчека, НЕ карточка ═══════════════════════
  {
    // Зеркало TAB_RULES: temporal-правило на вкладке Фактчека.
    const fctab = TABS.filter(function (t) { return t.id === 'mod_factcheck'; })[0];
    assert.ok(fctab, 'B07: вкладка mod_factcheck есть');
    const temporalRule = (fctab.sources || []).filter(function (s) {
      return s.category === 'temporal';
    })[0];
    assert.ok(temporalRule &&
      temporalRule.groups.indexOf('temporal_factcheck') >= 0,
      'B07: TABS mod_factcheck содержит temporal_factcheck (зеркало TAB_RULES)');

    // Группа рендерится на settings-вкладке workspace Фактчека.
    const m = moduleById('mod_factcheck');
    assert.strictEqual(
      methods.workspaceGroupTab.call({}, m,
        { id: 'temporal_factcheck', category: 'temporal' }),
      'settings', 'B07: temporal-группа → settings-вкладка workspace');
    const wsGroups = methods._workspaceGroupsFor.call(
      mkCtx({
        configItems: [
          item('temporal.tool_enabled', true, { per_chat: false,
            category: 'temporal', group: 'temporal_factcheck',
            title: 'Инструмент fact_check включён', type: 'bool' }),
          item('temporal.default_mode', 'contextual', { per_chat: false,
            category: 'temporal', group: 'temporal_factcheck',
            title: 'Режим проверки по умолчанию', type: 'str',
            widget: 'select',
            select_options: ['contextual', 'current', 'historical_truth',
                             'knowable_at_time'],
            select_labels: ['Контекстный (по умолчанию)', 'Актуальность сейчас',
                            'Как было тогда', 'Знание на момент'] }),
          item('flags.factcheck_enabled', true, { category: 'flags',
            group: 'flags_module_factcheck', title: 'Модуль Фактчек включён',
            type: 'bool' }),
        ],
        configGroups: [
          { id: 'temporal_factcheck', category: 'temporal',
            title: 'Временной фактчек', description: '', order: 1 },
          { id: 'flags_module_factcheck', category: 'flags',
            title: 'Модуль: Фактчек', description: '', order: 3 },
        ],
      }), m, 'settings');
    const groupIds = wsGroups.map(function (g) { return g.id; });
    assert.ok(groupIds.indexOf('temporal_factcheck') >= 0,
      'B07: temporal-группа присутствует на settings-вкладке Фактчека');
    assert.ok(groupIds.indexOf('flags_module_factcheck') >= 0,
      'B07: мастер-флаг Фактчека на той же вкладке');
    const tGroup = wsGroups.filter(function (g) {
      return g.id === 'temporal_factcheck';
    })[0];
    assert.strictEqual(tGroup.items.length, 2,
      'B07: в группе — режим и гейт (TTL в фикстуре не переданы)');

    // Человекочитаемые подписи (display-оверрайды, Δ каталога = 0).
    const normCtx = mkCtx({});
    const items = [
      item('temporal.tool_enabled', true, { title: 'Инструмент fact_check включён',
        description: 'старое', type: 'bool', widget: '' }),
      item('initiative.frequency_profile', 'normal', {
        title: 'Профиль частоты инициативы', type: 'str', widget: '' }),
      item('flags.initiative_observer_enabled', true, {
        title: 'Наблюдатель инициативы (обычный чат)', type: 'bool',
        widget: '' }),
    ];
    methods._normalizeConfigItems.call(normCtx, items);
    assert.strictEqual(items[0].title, 'Проверять дату и актуальность',
      'B07: гейт — «Проверять дату и актуальность» (без жаргона fact_check)');
    assert.ok(items[0].description.indexOf('не отключаются') > 0 &&
      items[0].description.indexOf('MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED') > 0,
      'B07: объяснение — что включает и что НЕ выключает + аварийная env-ось');
    // B01.4: профиль частоты — select редко/нормально/активно.
    assert.strictEqual(items[1].widget, 'select',
      'B01.4: профиль частоты — select');
    assert.deepStrictEqual(items[1].select_options,
      ['rare', 'normal', 'active'], 'B01.4: значения — канон резолвера');
    assert.deepStrictEqual(items[1].select_labels,
      ['Редко', 'Нормально', 'Активно'], 'B01.4: подписи по-русски');
    assert.strictEqual(items[2].title, 'Автономные реплики в обычных чатах',
      'B01.4: подпись наблюдателя без жаргона');
    // Ничего лишнего оверрайд не трогает.
    const plain = item('flags.factcheck_enabled', true,
      { title: 'Модуль Фактчек включён', type: 'bool', widget: '' });
    methods._normalizeConfigItems.call(normCtx, [plain]);
    assert.strictEqual(plain.title, 'Модуль Фактчек включён',
      'B07/B01: чужие подписи не меняются');

    // Название группы — «Время и источники» (раздел ТЗ).
    const gctx = mkCtx({});
    assert.strictEqual(
      methods.groupTitle.call(gctx, { id: 'temporal_factcheck', meta:
        { title: 'Временной фактчек' } }),
      'Время и источники', 'B07: группа называется «Время и источники»');
    assert.ok(
      methods.groupDescription.call(gctx,
        { id: 'temporal_factcheck', meta: { description: '' } })
        .indexOf('времени') >= 0,
      'B07: описание группы человекочитаемое');

    // Карточки «Временная проверка» в витрине НЕТ (backend hidden не отдаёт;
    // fallback-витрина тоже не создаёт её ни в каком виде).
    assert.ok(!moduleById('mod_factcheck_temporal'),
      'B07: карточки factcheck_temporal в витрине нет');
    assert.ok(MODULES.every(function (mm) {
      return String(mm.id).indexOf('temporal') < 0;
    }), 'B07: ни одной temporal-карточки в витрине модулей');
    // Реестр с hidden-спекой не добавляет карточку (fail-open-витрина).
    const regCtx = mkCtx({ modules: MODULES.slice(), _f4Registry: {} });
    methods.f3ApplyModuleRegistry.call(regCtx, [
      { id: 'factcheck_temporal', title: 'Временная проверка',
        description: 'x', master_param: 'temporal.tool_enabled',
        runtime_gate: 'global', visibility: 'hidden' },
      { id: 'experience', title: 'Опыт', description: 'x',
        master_param: 'memory.experience_learning_enabled',
        runtime_gate: 'per_chat', visibility: 'visible' },
    ]);
    assert.ok(!regCtx.modules.some(function (mm) {
      return mm.id === 'mod_factcheck_temporal';
    }), 'B07: hidden-спека не становится карточкой');
    assert.ok(regCtx.modules.some(function (mm) {
      return mm.id === 'mod_experience';
    }), 'B07: видимая спека реестра карточку создаёт (негатив-контроль)');
  }

  // ═══ B01.4: карта модуля «Инициатива» подтягивает группы ════════════════
  {
    const ini = moduleById('mod_initiative');
    assert.strictEqual(ini.tab, 'mod_initiative', 'B01.4: tab модуля');
    const iniTab = TABS.filter(function (t) { return t.id === 'mod_initiative'; })[0];
    const cats = {};
    (iniTab.sources || []).forEach(function (s) { cats[s.category] = s; });
    assert.ok(cats.flags && cats.flags.groups.indexOf('flags_intent') >= 0,
      'B01.4: flags_intent на карте модуля (per-chat гейт)');
    assert.ok(cats.limits && cats.limits.groups.indexOf('limits_intent') >= 0,
      'B01.4: limits_intent на карте модуля (тонкие лимиты + профиль)');
    // Per-chat гейт и тонкие лимиты реально рендерятся на вкладках.
    const wsCtx = mkCtx({
      configItems: [
        item('initiative.enabled', true, { category: 'flags',
          group: 'flags_intent', title: 'Инициатива в этом чате',
          type: 'bool' }),
        item('initiative.frequency_profile', 'normal', { category: 'limits',
          group: 'limits_intent', title: 'Профиль частоты инициативы',
          type: 'str' }),
        item('initiative.min_gap_seconds', 600, { category: 'limits',
          group: 'limits_intent', title: 'Мин. пауза между инициативами, с',
          type: 'int' }),
      ],
      configGroups: [
        { id: 'flags_intent', category: 'flags', title: 'Инициатива: флаги',
          description: '', order: 1 },
        { id: 'limits_intent', category: 'limits', title: 'Инициатива: лимиты',
          description: '', order: 37 },
      ],
    });
    const settingsGroups = methods._workspaceGroupsFor.call(
      wsCtx, ini, 'settings');
    const limitsGroups = methods._workspaceGroupsFor.call(wsCtx, ini, 'limits');
    assert.ok(settingsGroups.some(function (g) {
      return g.id === 'flags_intent'
        && g.items.some(function (i) { return i.key === 'initiative.enabled'; });
    }), 'B01.4: per-chat гейт «Инициатива в этом чате» на «Основных настройках»');
    assert.ok(limitsGroups.some(function (g) {
      return g.id === 'limits_intent' && g.items.some(function (i) {
        return i.key === 'initiative.frequency_profile';
      });
    }), 'B01.4: профиль частоты на вкладке «Лимиты»');
    assert.ok(limitsGroups.some(function (g) {
      return g.items.some(function (i) {
        return i.key === 'initiative.min_gap_seconds';
      });
    }), 'B01.4: тонкие лимиты рядом с профилем');
    // Витрина: мастер initiative_enabled — global (пер-чат гейт — отдельный
    // ключ внутри настроек, B01), поэтому read-only на чате честен.
    assert.strictEqual(ini.runtimeGate, 'global',
      'B01.4: мастер Инициативы global; per-chat — initiative.enabled');
  }

  console.log('W3-MODULES-UI-OK');
  process.exit(0);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
