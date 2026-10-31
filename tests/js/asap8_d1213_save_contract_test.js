'use strict';
/* ASAP 8 v6 D12+D13 — universal save contract + mobile shell + Run Card.
 *
 * TEST-LIFECYCLE: CONTRACT owner=ASAP8-v6/D13 §18I.13/§18I.14
 * TEST-LIFECYCLE: CONTRACT owner=ASAP8-v6/D12 §18I.11/§18I.12
 *
 * Пинит ВЛАДЕЛЬЧЕСКИЙ контракт (v6 delta, решение владельца):
 *   D13.1  clean → Save-бара НЕТ нигде (v-if в компоненте; spacer удалён);
 *          dirty → компактная панель (pill, не full-width) + чип в шапке.
 *   D13.2  autosave по server-ack: неудача → baseline НЕ сдвигается,
 *          поля остаются dirty (stickyFailed), черновик жив.
 *   D13.4  уход с dirty-страницы/закрытие модалки защищают черновик
 *          (_dirtyLeaveGuard: область + число полей; отказ = stay).
 *   D13.5  mobile bottom-nav/more-sheet удалены; верхняя компактная
 *          навигация = канонический реестр navItems; landscape-правило.
 *   D12    Unified Run Card: честные проекции Summary(F4)/Initiative(C06A)/
 *          Experience(D05); sourceHint называет durable-источник;
 *          синтетические шкалы (IQ/score) запрещены.
 *
 * Запуск: node tests/js/asap8_d1213_save_contract_test.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

// Подхватываем приложение тем же способом, что round1025_save_state_test.
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
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; },
  localStorage: { _s: {}, getItem(k) { return this._s[k] || null; },
    setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; } },
  innerWidth: 1280,
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  querySelector() { return null; },
  body: { appendChild() {}, removeChild() {} },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = global.window.localStorage;
global.localStorage = global.window.localStorage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert.ok(captured, 'Vue.createApp вызван (captured экспортирован)');
const methods = captured.methods;
const computed = captured.computed;
const components = (global.__components) || {};

// ── D13.1: sticky-save монтируется только при dirty/saving/failed ──────────
{
  const comp = components['sticky-save'];
  assert.ok(comp, 'D13: компонент sticky-save зарегистрирован');
  assert.ok(comp.template.indexOf('v-if="visible"') >= 0,
    'D13 §18I.13: шаблон с v-if="visible" (clean → в DOM отсутствует)');
  function mount(root) {
    const vm = { root: root };
    Object.keys(comp.computed).forEach(function (k) {
      Object.defineProperty(vm, k, { get: comp.computed[k].bind(vm) });
    });
    return vm;
  }
  // clean → панели нет.
  assert.strictEqual(mount({ saveState: 'clean', stickyDirtyCount: 0,
    stickySaving: false, stickyFailed: [] }).visible, false,
    'D13: clean → visible=false (нет постоянного футера)');
  assert.strictEqual(mount({ saveState: 'loading', stickyDirtyCount: 0,
    stickySaving: false, stickyFailed: [] }).visible, false,
    'D13: loading → visible=false');
  // dirty/saving/failed/error/conflict → панель есть.
  for (const root of [
    { saveState: 'dirty', stickyDirtyCount: 2, stickySaving: false, stickyFailed: [] },
    { saveState: 'clean', stickyDirtyCount: 0, stickySaving: true, stickyFailed: [] },
    { saveState: 'clean', stickyDirtyCount: 0, stickySaving: false, stickyFailed: ['Поле X'] },
    { saveState: 'error', stickyDirtyCount: 0, stickySaving: false, stickyFailed: [] },
    { saveState: 'conflict', stickyDirtyCount: 0, stickySaving: false, stickyFailed: [] },
  ]) {
    assert.strictEqual(mount(root).visible, true,
      'D13: состояние ' + root.saveState
      + '/saving=' + !!root.stickySaving + '/failed='
      + (root.stickyFailed || []).length + ' → visible=true');
  }
  // Reserved spacer удалён ВЕЗДЕ.
  assert.ok(!/\.sticky-spacer\s*\{/.test(CSS), 'D13: .sticky-spacer CSS удалён');
  assert.ok(INDEX.indexOf('sticky-spacer') < 0,
    'D13: sticky-spacer отсутствует в разметке');
  // Панель — компактный pill, не full-width footer.
  const pill = CSS.match(/\.sticky-save\s*\{([^}]*)\}/);
  assert.ok(pill && /fit-content/.test(pill[1])
    && /margin-left:\s*auto/.test(pill[1]),
    'D13: .sticky-save — компактный pill (fit-content, справа)');
}

// ── D13.1: компактный счётчик в шапке (dirty-only) ─────────────────────────
// CFG-04B.1 (source-cfg-addendum L157) переопределяет роль чипа: он остаётся
// компактным ИНДИКАТОРОМ (не CTA), единственный основной сценарий сохранения —
// панель <sticky-save>. Защита черновика (_dirtyLeaveGuard), «clean → бара
// нет» и stickyFailed сохранены без изменений.
{
  assert.ok(INDEX.indexOf('header-save-chip') >= 0,
    'D13: индикатор Save в шапке присутствует в разметке');
  assert.ok(INDEX.indexOf('v-if="headerSaveChip.visible"') >= 0,
    'D13: индикатор рендерится только при visible (dirty/saving/failed)');
  assert.ok(INDEX.indexOf('data-save-indicator') >= 0,
    'CFG-04B.1: узел шапки помечен как индикатор');
  const chipMarkup = INDEX.slice(INDEX.indexOf('data-save-indicator') - 400,
    INDEX.indexOf('data-save-indicator') + 500);
  assert.strictEqual(/@click/.test(chipMarkup), false,
    'CFG-04B.1/L157: индикатор не является вторым сохранением');
  const chip = computed.headerSaveChip;
  assert.ok(chip, 'D13: computed headerSaveChip определён');
  assert.strictEqual(chip.call({ saveState: 'clean', stickyDirtyCount: 0,
    stickyFailed: [] }).visible, false, 'D13: clean → индикатора нет');
  const dirty = chip.call({ saveState: 'dirty', stickyDirtyCount: 3,
    stickyFailed: [] });
  assert.strictEqual(dirty.visible, true, 'D13: dirty → индикатор есть');
  assert.strictEqual(dirty.count, 3, 'D13: индикатор показывает dirty-count');
  assert.strictEqual(dirty.actionable, false,
    'CFG-04B.1/L157: dirty-индикатор не CTA');
  assert.strictEqual(dirty.label, 'не сохранено',
    'CFG-04B.1/L157: подпись индикатора не дублирует действие');
  const fail = chip.call({ saveState: 'error', stickyDirtyCount: 0,
    stickyFailed: ['A'] });
  assert.strictEqual(fail.visible, true, 'D13: error → индикатор остаётся с причиной');
}

// ── D13.2: неудачное сохранение НЕ сдвигает baseline (draft жив) ───────────
(async function () {
  const saved = [];
  const ctx = {
    stickySaving: false, stickyFailed: [], stickyFailedKeys: [],
    configSnapshot: { 'models.x': '"old"' },
    configItems: [{ key: 'models.x', value: 'new', title: 'Модель X' }],
    keyDrafts: {},
    dirtyItems: [{ key: 'models.x', value: 'new', title: 'Модель X' }],
    dirtyKeyItems: [],
    toast() {},
    _findConfigItem(k) { return this.configItems.find((i) => i.key === k); },
    // persistItems падает по server-ack (не по сети) → baseline НЕ сдвигается.
    async persistItems(items) {
      saved.push(items.map((i) => i.key));
      return { failed: [{ key: 'models.x' }], skipped: [] };
    },
    _opSeq: 0,
  };
  await methods.saveModalEdits.call(ctx);
  assert.strictEqual(saved.length, 1, 'D13.2: ровно одна попытка записи');
  assert.deepStrictEqual(ctx.configSnapshot, { 'models.x': '"old"' },
    'D13.2: baseline НЕ сдвинут после неудачи (черновик сохранён)');
  assert.deepStrictEqual(ctx.stickyFailed, ['Модель X'],
    'D13.2: провал подсвечен (failed-список)');
})();

// ── D13.4: уход с dirty-страницы защищает черновик ─────────────────────────
{
  let confirmMsg = '';
  global.window.confirm = function (m) { confirmMsg = m; return false; };
  const ctx = {
    hasUnsavedEdits: methods.hasUnsavedEdits,
    scopeTriggerTitle: 'PERMsoc',
    isChatContext() { return true; },
    stickyDirtyCount: 2, dirtyItems: [], dirtyKeyItems: [],
    saving: new Set(), blockDrafts: {}, ownKeyDraft: '',
    personaDraft: null, dossierData: null,
  };
  assert.strictEqual(methods._dirtyLeaveGuard.call(ctx, 'Уйти?'), false,
    'D13.4: отказ оператора → guard=false (stay, черновик цел)');
  assert.ok(confirmMsg.indexOf('PERMsoc') >= 0 && confirmMsg.indexOf('2') >= 0,
    'D13.4: confirm называет область и число изменённых полей (§18I.3)');
  // Чистая форма → guard=true без confirm.
  let asked = 0;
  global.window.confirm = function () { asked += 1; return true; };
  const clean = Object.assign({}, ctx, { stickyDirtyCount: 0 });
  assert.strictEqual(methods._dirtyLeaveGuard.call(clean, 'Уйти?'), true,
    'D13.4: clean → уход без подтверждения');
  assert.strictEqual(asked, 0, 'D13.4: clean → confirm не вызывался');
  // Источники ухода защищены: applyRoute (hash-навигация) + closeModule
  // (ESC/backdrop/✕ модуля) идут через guard.
  assert.ok(/_dirtyLeaveGuard\(/.test(JS.slice(
    JS.indexOf('applyRoute: function'), JS.indexOf('applyRoute: function') + 7000)),
    'D13.4: applyRoute защищён dirty-guard');
  assert.ok(/_dirtyLeaveGuard\(/.test(methods.closeModule.toString()),
    'D13.4: closeModule (ESC/backdrop) защищён dirty-guard');
}

// ── F2 (REV-UI-D1213): роль-эдитор — закрытие не молча теряет правки ───────
{
  const mkCtx = function () {
    return {
      _roleEditorBaseline: null,
      // F2: методы резолвятся через this — как в реальном vm.
      _roleEditorSnapshot: methods._roleEditorSnapshot,
      _roleEditorDirtyCount: methods._roleEditorDirtyCount,
      roleEditor: { open: true, roleName: 'moderator',
        sections: [
          { id: 'memory',
            params: [{ key: 'limits.pause_seconds', checked: true }],
            keys: [{ key: 'flags.x', checked: false }] },
        ],
        actions: [{ id: 'restart', checked: false }],
      },
    };
  };
  // baseline = состояние сразу после openRoleEditor→applyTree.
  let ctx = mkCtx();
  ctx._roleEditorBaseline = methods._roleEditorSnapshot.call(ctx);
  // Правка: включили ключ + action.
  ctx.roleEditor.sections[0].keys[0].checked = true;
  ctx.roleEditor.actions[0].checked = true;
  let msg = '';
  global.window.confirm = function (m) { msg = m; return false; };
  methods.closeRoleEditor.call(ctx);
  assert.strictEqual(ctx.roleEditor.open, true,
    'F2: отказ → модалка НЕ закрыта (правки живы)');
  assert.ok(msg.indexOf('moderator') >= 0 && msg.indexOf('2') >= 0,
    'F2: confirm называет роль и число изменений (§18I.4)');
  global.window.confirm = function () { return true; };
  methods.closeRoleEditor.call(ctx);
  assert.strictEqual(ctx.roleEditor.open, false,
    'F2: согласие → закрыто (сброс осознанный)');
  // Чистый редактор → закрытие без подтверждения.
  let asked = 0;
  global.window.confirm = function () { asked += 1; return true; };
  ctx = mkCtx();
  ctx._roleEditorBaseline = methods._roleEditorSnapshot.call(ctx);
  methods.closeRoleEditor.call(ctx);
  assert.strictEqual(asked, 0, 'F2: clean → без confirm');
  assert.strictEqual(ctx.roleEditor.open, false, 'F2: clean → закрыто');
  // dirty-подсчёт и сброс baseline после успешного saveRole.
  ctx = mkCtx();
  ctx._roleEditorBaseline = methods._roleEditorSnapshot.call(ctx);
  ctx.roleEditor.sections[0].keys[0].checked = true;
  assert.strictEqual(methods._roleEditorDirtyCount.call(ctx), 1,
    'F2: одна правка → dirty=1');
  ctx._roleEditorBaseline = methods._roleEditorSnapshot.call(ctx);
  assert.strictEqual(methods._roleEditorDirtyCount.call(ctx), 0,
    'F2: после saveRole (сервер подтвердил) → dirty=0');
  // Все пути закрытия (backdrop/«Закрыть») идут через guard; baseline
  // ставится строго после applyTree.
  assert.ok(/_roleEditorDirtyCount\(/.test(methods.closeRoleEditor.toString()),
    'F2: closeRoleEditor (backdrop/ESC/✕) защищён dirty-guard');
  assert.ok(
    methods.openRoleEditor.toString()
      .indexOf('_roleEditorBaseline = this._roleEditorSnapshot()') >= 0,
    'F2: baseline снапшот после applyTree (openRoleEditor)');
}

// ── D13.5 + ASAP-UI-02 §2.1: mobile shell — постоянной панели нет,
// навигация в drawer, «⋯» — только второстепенные действия.
{
  assert.ok(INDEX.indexOf('class="bottom-nav"') < 0,
    'D13 §18I.14: bottom-nav удалён');
  // Старая шторка-лента (moreOpen) не возвращена; меню второстепенных
  // действий — popover (more-menu), НЕ нижний navbar.
  assert.ok(INDEX.indexOf('moreOpen') < 0,
    'D13 §18I.14: шторка «Ещё» (moreOpen) удалена');
  assert.ok(INDEX.indexOf('class="more-sheet"') < 0
    && INDEX.indexOf('class="bottom-nav"') < 0,
    'U01: меню «⋯» — popover поверх контента, не ряд шапки/низ-бар');
  // ASAP-UI-02: «row B» (постоянная нижняя панель разделов) отменена.
  assert.ok(INDEX.indexOf('mobile-topnav') < 0,
    'ASAP-UI-02: постоянной мобильной панели разделов нет в разметке');
  assert.ok(CSS.indexOf('mobile-topnav') < 0,
    'ASAP-UI-02: её CSS (включая ландшафтный рейл) удалён');
  assert.ok(INDEX.indexOf('data-drawer-trigger') >= 0
    && INDEX.indexOf('v-if="iaV2 && hasDrawer"') >= 0,
    'ASAP-UI-02: навигация на телефоне/планшете — кнопка drawer в шапке');
  assert.ok(INDEX.indexOf('data-more-trigger') >= 0
    && INDEX.indexOf('more-menu-root') >= 0,
    'ASAP-UI-02: кнопка «⋯» + popover-меню второстепенных действий');
  assert.strictEqual(computed.mobileTopnavItems, undefined,
    'ASAP-UI-02: mobileTopnavItems удалён');
  assert.strictEqual(computed.bottomNavItems, undefined,
    'D13: bottomNavItems удалён');
  assert.strictEqual(computed.mobileMoreItems, undefined,
    'ASAP-UI-02: список разделов в «Ещё» (mobileMoreItems) удалён');
  // Ландшафт: шапка остаётся ОДНОЙ строкой, второй панели/рейла нет.
  assert.ok(/@media \(orientation: landscape\) and \(max-height: 520px\)[\s\S]{0,400}flex-wrap: nowrap/.test(CSS),
    'ASAP-UI-02: landscape — одна строка шапки без второго ряда');
  assert.ok(/@media \(prefers-reduced-motion: reduce\)/.test(CSS),
    '§18I.7: reduced-motion уважен в мобильной навигации');
}

// ── D12: Unified Run Card ──────────────────────────────────────────────────
{
  const comp = components['run-card'];
  assert.ok(comp, 'D12 §18I.11: компонент run-card зарегистрирован');
  for (const p of ['runId', 'scopeLabel', 'outcome', 'latency', 'evidence',
                   'fallback', 'sourceHint', 'stages', 'links']) {
    assert.ok(comp.props && comp.props[p],
      'D12 §18I.11: run-card prop ' + p);
  }
  // Источник данных обязан называться (durable-происхождение).
  assert.ok(comp.template.indexOf('sourceHint') >= 0,
    'D12: карточка показывает «откуда данные»');
  // Проекции зарегистрированы и честны.
  for (const name of ['runCardSummary', 'runCardInitiative',
                      'runCardExperience']) {
    assert.ok(computed[name], 'D12: computed ' + name);
  }

  // Initiative: воронка C06A на РЕАЛЬНОМ шейпе payload — producers_24h это
  // ОБЪЕКТ {origin: count} (status_service.intent_snapshot: GROUP BY origin,
  // intents_created_24h = сумма значений). REV-UI-D1213 F1.
  const ia = computed.runCardInitiative.call({
    statusData: { intents: { module: {
      state_label: 'Инициатива работает',
      top_block_reason: '',
      funnel: { producers_24h: { unanswered_question: 7, silent_window: 3 },
                intents_created_24h: 10, due: 6, decisions_24h: 4,
                sent_24h: 2 },
      heartbeat: { enabled: true, registered: true,
                   last_tick: { ts: 1728900000 } },
    } } },
    topBlockLabel: function (c) { return String(c); },
    fmtTs: function () { return 'T'; },
  });
  assert.ok(ia, 'D12: инициатива → карточка построена');
  assert.strictEqual(ia.stages.length, 5,
    'D12 §18I.12-E: воронка 5 стадий');
  assert.strictEqual(ia.stages[0].value, 10,
    'F1 REV-UI-D1213: «Возможности» = СУММА producers_24h по origin'
    + '-ам ({7,3} → 10), не NaN/0');
  assert.strictEqual(ia.stages[1].value, 10,
    'F1: «Намерения» = intents_created_24h (консистентно с суммой)');
  assert.ok(ia.stages.every((s) => s.state === 'ok'),
    'F1 recheck: без нулей после ненулевых нет ложной подсветки останова');
  assert.ok(/intent_snapshot/.test(ia.sourceHint)
    && /durable/i.test(ia.sourceHint),
    'D12: источник инициативы = durable intent_snapshot');
  // Подсветка стадии останова — от верных чисел (ревью REV-UI-D1213):
  // ноль ПОСЛЕ ненулевого звена → warn; пустое начало (0 возможностей) —
  // честная пустота, не «блокер».
  const iaStop = computed.runCardInitiative.call({
    statusData: { intents: { module: {
      state_label: 'Останов: нет решений',
      top_block_reason: 'no_decisions',
      funnel: { producers_24h: { unanswered_question: 5 },
                intents_created_24h: 5, due: 5, decisions_24h: 0,
                sent_24h: 0 },
      heartbeat: { enabled: true, registered: true,
                   last_tick: { ts: 1728900000 } },
    } } },
    topBlockLabel: function (c) { return String(c); },
    fmtTs: function () { return 'T'; },
  });
  assert.strictEqual(iaStop.stages[0].value, 5,
    'F1: одиночный origin → корректная сумма');
  assert.strictEqual(iaStop.stages[3].state, 'warn'
    && iaStop.stages[4].state, 'warn',
    'D12: стадия останова (Решения/Отправлено=0 после 5) подсвечена');
  assert.ok(iaStop.stages.slice(0, 3).every((s) => s.state === 'ok'),
    'D12: звенья до останова не подсвечены');
  assert.ok(iaStop.reason.indexOf('no_decisions') >= 0,
    'D12: top blocker назван человеческим текстом');
  // Честная пустота: producers пуст → без ложного warn.
  const iaEmpty = computed.runCardInitiative.call({
    statusData: { intents: { module: {
      state_label: 'Окно пустое', top_block_reason: 'no_producers',
      funnel: { producers_24h: {}, intents_created_24h: 0, due: 0,
                decisions_24h: 0, sent_24h: 0 },
    } } },
  });
  assert.strictEqual(iaEmpty.stages[0].value, 0,
    'F1: пустой объект producers → честный 0');
  assert.ok(iaEmpty.stages.every((s) => s.state === 'ok'),
    'D12: пустое окно не подсвечивается как останов');
  // funnelProducersLabel — та же семантика суммирования (ревью: соседний шов).
  assert.strictEqual(methods.funnelProducersLabel(
    { unanswered_question: 7, silent_window: 3 }),
    'unanswered_question: 7, silent_window: 3',
    'F1 recheck: label показывает разбивку по origin-ам');
  assert.strictEqual(methods.funnelProducersLabel(42), '42',
    'F1 recheck: число-шейп проходит как есть');
  assert.strictEqual(methods.funnelProducersLabel({ a: -5, b: 'x', c: 2 }),
    'c: 2',
    'F1 recheck: отрицательные/мусорные значения отфильтрованы');
  // Нет данных → карточки нет (без выдуманных нулей).
  assert.strictEqual(computed.runCardInitiative.call({ statusData: {} }), null,
    'D12: нет данных инициативы → карточки нет');

  // Experience: цепочка D05 + usefulness.
  const ex = computed.runCardExperience.call({
    mca17cFunnel: { enabled: true,
      feedback: { total: 12 },
      lessons: { candidate: 6, validated: 3, active: 2 },
      applications: { total: 5, success: 2, failure: 1, unknown: 2 } },
    d05ExperienceChain: methods.d05ExperienceChain,
    lessonUsefulness: methods.lessonUsefulness,
  });
  assert.ok(ex, 'D12: уроки → карточка построена');
  assert.strictEqual(ex.stages[0].value, 12, 'D12: «Замечено» из feedback.total');
  assert.strictEqual(ex.stages[4].value, 2, 'D12: «Помогло» = app.success');
  assert.ok(ex.stages.some((s) => s.label === 'Неизвестно' && s.value === 2),
    'D12 §18I.10: unknown ≠ провал — отдельная строка');
  assert.ok(/experience\/funnel/.test(ex.sourceHint),
    'D12: источник уроков = /api/oversight/experience/funnel (D05)');

  // Summary: F4-шапка прогона.
  const sum = computed.runCardSummary.call({
    pipelineRunView: {
      run_id: 'abcdef123456', chat_id: -100, health: 'degraded',
      health_label: 'С деградацией', duration_ms: 4200,
      fallback: 'l2_fallback',
      coverage: { total: 10, considered: 9, percent: 90 },
      publication: { status: 'ok', channel: 'rich' },
      nodes: [{ state: 'success' }, { state: 'fallback' }, { state: 'failed' },
              { state: 'skipped' }],
    },
    pipelineHealthBadge: methods.pipelineHealthBadge,
    fmtSec: methods.fmtSec,
  });
  assert.ok(sum, 'D12: summary → карточка построена');
  assert.strictEqual(sum.runId, 'abcdef123456', 'D12: run ID присутствует');
  assert.strictEqual(sum.scopeLabel, 'чат -100', 'D12: scope назван');
  assert.ok(sum.latency.indexOf('4.2с') >= 0, 'D12: latency человека-читаем');
  assert.ok(sum.evidence.indexOf('9/10') >= 0,
    'D12 §18I.11: evidence counts в карточке');
  assert.ok(sum.fallback.indexOf('l2_fallback') >= 0,
    'D12: fallback назван явно (не спрятан)');
  assert.ok(/pipeline_events/.test(sum.sourceHint),
    'D12: источник Summary = durable pipeline_events (F4)');
  assert.ok(sum.stages.some((s) => s.label === 'Публикация'
    && s.state === 'ok'), 'D12 §18I.10: published ≠ planned (стадия доставки)');

  // Запрет синтетических шкал: не в рендере (комментарии-запреты допустимы).
  assert.ok(!/AI IQ|iq_score|overallScore/.test(comp.template),
    'D12: run-card не рендерит синтетические IQ-шкалы');
  // Виджетные точки входа в разметке.
  assert.ok(INDEX.indexOf('data-run-card-summary') >= 0,
    'D12: Run Card на pipeline-вкладке (Summary)');
  assert.ok(INDEX.indexOf('data-initiative-funnel') >= 0,
    'D12: воронка инициативы на Статусе');
  assert.ok(INDEX.indexOf('data-experience-funnel') >= 0,
    'D12: воронка уроков на Статусе');
  // Сон: единственный детальный виджет. U03.1 (v6.3): каноническая панель
  // «Сон / Глубокий сон»; дублирующий ряд sleep-бейджей в шапке
  // «Мониторинга Интеллекта» удалён (скролл-хелпер больше не нужен).
  assert.strictEqual((INDEX.match(/class="card p-4 status-sleep sg-4"/g) || []).length, 1,
    'D12 §18I.12-D: ровно один детальный виджет сна');
  assert.ok(INDEX.indexOf('Сон / Глубокий сон') >= 0,
    'U03.1: каноническое название панели «Сон / Глубокий сон»');
  assert.strictEqual(INDEX.indexOf('scrollToSleepWidget()'), -1,
    'U03.1: дубль sleep-бейджей/скролл-хелпер удалены');
  // Heartbeat sparkline сохранён.
  assert.ok(INDEX.indexOf('Сердцебиение') >= 0
    && (INDEX.indexOf('hb-canvas') >= 0 || INDEX.indexOf('class="ekg"') >= 0),
    'D12 §18I.12-A: существующий виджет Сердцебиение сохранён');
}

console.log('ASAP8-D1213-SAVE-CONTRACT-OK');
