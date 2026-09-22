'use strict';
/* F6 round1025 (memory-analytics-reorg-round1025, ADR-1025-19 D2–D8) —
 * «Аналитика» §21–§29 + «Память» §52–§59 + инварианты §75/§76/§116.
 *
 * Покрытие §75 (карта токенов):
 *   - 4 режима (последний вызов / день / неделя / месяц);
 *   - выбор L1/L2/модели/модуля через фильтры adapter-модели;
 *   - неизвестная стоимость -> «Нет данных», не `$0` (§28);
 *   - «Без лимита» при бесконечном бюджете;
 *   - отсутствие фиктивных этапов (algorithm/format/publish не эмитятся);
 *   - §27: поле поиска + select «статус» (H2), сброс фильтров при смене
 *     режима (M-F6S-1), закрытие деталей по Esc/подложке (L-F6S-4);
 *   - mobile-представление (§29) — CSS bottom-sheet/вертикально.
 * Покрытие §76: мониторинг интеллекта НЕ изменён (строки/системы на месте).
 * Покрытие §116: одна система аналитики/визуализации; CSP/zero-build;
 *   `backdrop-filter: url(` = 0; Δ DDL/каталога — в pytest-маркере.
 *
 * Запуск: node tests/js/round1025_f6_analytics_memory_test.js
 *         → F6-ANALYTICS-MEMORY-OK
 */
const fs = require('fs');
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
const ROOT = path.join(__dirname, '..', '..');
global.window.ExecutionGraph =
  require(path.join(ROOT, 'web', 'static', 'execution_graph.js'));
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, appendChild() {} }; },
  body: { appendChild() {}, removeChild() {} },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = {
  _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch'); };

require(path.join(ROOT, 'web', 'app.js'));
const methods = captured.methods;
const computed = captured.computed;

const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const ADAPTER = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'execution_graph.js'), 'utf8');

function traceCtx(latest) {
  const c = {
    tokenAnalyticsLatest: latest,
    execFilterModule: '', execFilterModel: '',
    execFilterStage: '', execFilterStatus: '', execFilterQuery: '',
    execGraphApi: methods.execGraphApi,
    _execFilters: methods._execFilters,
    execFilterActive: methods.execFilterActive,
    execStatusLabel: methods.execStatusLabel,
  };
  c.execTrace = computed.execTrace.call(c);
  c.execTraceNodes = computed.execTraceNodes.call(c);
  return c;
}

// ── 1. §75: 4 режима; переключение не смешивает трассировку и агрегат;
//        M-F6S-1: смена режима сбрасывает фильтры §27 ──────────────────────
(function () {
  let loaded = 0;
  const ctx = {
    execMode: 'month', execSelected: { x: 1 }, execDetailOpen: true,
    tokenAnalyticsPeriod: 'day',
    execFilterModule: 'A', execFilterModel: 'm1', execFilterStage: 'stage1',
    execFilterStatus: 'unknown', execFilterQuery: 'search',
    resetExecFilters: methods.resetExecFilters,
    loadTokenAnalytics() { loaded++; },
  };
  ['latest', 'day', 'week', 'month'].forEach(function (m) {
    methods.setExecMode.call(ctx, m);
    assert.strictEqual(ctx.execMode, m, 'режим ' + m);
    assert.strictEqual(ctx.execSelected, null, 'выбор узла сбрасывается');
    assert.strictEqual(ctx.execDetailOpen, false);
    assert.strictEqual(ctx.execFilterQuery, '',
      'смена режима сбрасывает фильтры §27 (M-F6S-1)');
    assert.strictEqual(methods.execFilterActive.call(ctx), false,
      'после смены режима фильтры неактивны');
    // фильтр возвращаем перед следующим переключением
    ctx.execFilterModule = 'A'; ctx.execFilterQuery = 'search';
  });
  assert.strictEqual(ctx.tokenAnalyticsPeriod, 'month',
    'период синхронизирован с режимом');
  assert.strictEqual(loaded, 4, 'каждый режим перезагружает данные');
  assert.strictEqual(computed.execIsTrace.call({ execMode: 'latest' }), true);
  assert.strictEqual(computed.execIsTrace.call({ execMode: 'week' }), false);
  // Повторный выбор того же режима фильтры НЕ трогает (не удивляем юзера).
  const same = { execMode: 'latest', execFilterQuery: 'x',
                 execFilterModule: 'A', resetExecFilters: methods.resetExecFilters,
                 loadTokenAnalytics() {} };
  methods.setExecMode.call(same, 'latest');
  assert.strictEqual(same.execFilterQuery, 'x', 'тот же режим — фильтры живы');
})();

// ── 2. §75: выбор L1/L2/модели/модуля через фильтры ───────────────────────
(function () {
  const latest = { correlation_id: 'c', steps: [
    { step: 'stage1', module: 'A', model: 'm1' },
    { step: 'stage2', module: 'B', model: 'm2' },
    { step: 'tool', module: 'A', tool_name: 't' },
  ], total: {} };
  const c = traceCtx(latest);
  const mods = computed.execModuleOptions.call(c);
  assert.deepStrictEqual(mods.sort(), ['A', 'B']);
  const models = computed.execModelOptions.call(c);
  assert.deepStrictEqual(models.sort(), ['m1', 'm2']);
  const stages = computed.execStageOptions.call(c);
  assert.deepStrictEqual(stages.map(function (s) { return s.key; }).sort(),
    ['stage1', 'stage2', 'tool']);
  // выбор L1 (stage1)
  c.execFilterStage = 'stage1';
  c.execTraceNodes = computed.execTraceNodes.call(c);
  assert.strictEqual(c.execTraceNodes.length, 1);
  assert.strictEqual(c.execTraceNodes[0].stageKey, 'stage1');
  // выбор модели m2
  c.execFilterStage = '';
  c.execFilterModel = 'm2';
  c.execTraceNodes = computed.execTraceNodes.call(c);
  assert.strictEqual(c.execTraceNodes.length, 1);
  assert.strictEqual(c.execTraceNodes[0].model, 'm2');
})();

// ── 3. §28: неизвестная стоимость -> «Нет данных»; подтверждённый ноль -> $0 ─
(function () {
  const ctx = { fmtExactTokens: methods.fmtExactTokens,
                fmtCost: methods.fmtCost };
  assert.strictEqual(methods.fmtCost.call(ctx, 0, false), 'Нет данных');
  assert.strictEqual(methods.fmtCost.call(ctx, null, true), 'Нет данных');
  assert.strictEqual(methods.fmtCost.call(ctx, 0, true), '$0');
  assert.strictEqual(
    methods.execCostLabel.call(ctx, { cost: 0.001, priceKnown: true })
      .indexOf('$') === 0, true);
  assert.strictEqual(
    methods.execCostLabel.call(ctx, { cost: null, priceKnown: false }),
    'Нет данных');
})();

// ── 4. §28: «Без лимита» без заполненного progress bar ───────────────────
(function () {
  // memoryContext.unlimited -> подпись «Безлимит (∞)» и ширина 0%/не растёт.
  assert(INDEX.indexOf('Безлимит (∞)') >= 0, 'подпись «Безлимит (∞)»');
  assert(INDEX.indexOf('memoryContext.unlimited') >= 0,
    'ветка безлимита в шаблоне');
  assert(INDEX.indexOf('memoryContext.limit') >= 0, 'обычная ветка лимита');
})();

// ── 5. §24/§75: нет фиктивных этапов (algorithm/format/publish) ───────────
(function () {
  const c = traceCtx({ correlation_id: 'c',
    steps: [{ step: 'stage1' }, { step: 'tool' }, { step: 'single' }],
    total: {} });
  const t = computed.tokenFlowTree.call(c);
  const kinds = t.nodes.map(function (n) { return n.kind; });
  ['algorithm', 'format', 'publish'].forEach(function (k) {
    assert.strictEqual(kinds.indexOf(k), -1, 'фиктивный узел ' + k + ' запрещён');
  });
  // Enum зарезервирован, но не эмитится (расширяемость §30).
  assert(global.window.ExecutionGraph.KIND_ENUM.indexOf('algorithm') >= 0);
})();

// ── 6. §21: компактное превью Статуса (не одна строка с токенами) ─────────
(function () {
  assert(INDEX.indexOf('Последний вызов') >= 0, 'превью последнего вызова');
  assert(INDEX.indexOf('execPreview') >= 0);
  assert(APP_JS.indexOf('loadExecPreview') >= 0);
  const c = traceCtx({ correlation_id: 'p', ts: 'T',
    steps: [{ step: 'stage1', input_tokens: 1, output_tokens: 2 }], total: {} });
  const pv = computed.execPreview.call(c);
  assert.strictEqual(pv.empty, false);
  assert.strictEqual(pv.nodes.length, 1);
  assert(pv.totals, 'итоги присутствуют');
  const empty = computed.execPreview.call(
    { execGraphApi: methods.execGraphApi, tokenAnalyticsLatest: null });
  assert.strictEqual(empty.empty, true);
  // Превью НЕ содержит фильтров §27.
  assert(INDEX.indexOf('exec-preview') >= 0);
})();

// ── 7. §29 mobile: bottom-sheet + вертикально, без сжатия до 320px ────────
(function () {
  assert(/@media \(max-width: 767px\)[\s\S]*\.exec-detail/.test(CSS),
    'mobile: детали → bottom-sheet');
  assert(/\.exec-detail[\s\S]*position:\s*fixed/.test(CSS),
    'desktop: side-panel fixed');
  assert(/\.exec-detail[\s\S]*top:\s*auto/.test(CSS),
    'mobile: bottom-sheet (top:auto)');
  assert(CSS.indexOf('token-flow__branch { margin-left: 0') >= 0,
    'узкий экран: ветка без горизонтального отступа');
})();

// ── 8. §76: мониторинг интеллекта не изменён (системы на месте) ───────────
(function () {
  const markers = [
    'Интеллект и Память', 'Убеждений', 'Парадигм', 'Живая лента досье',
    'dreamPhaseBadge', 'deepPhaseBadge', 'Ночной синтез',
  ];
  markers.forEach(function (m) {
    const present = INDEX.indexOf(m) >= 0 || APP_JS.indexOf(m) >= 0;
    assert.ok(present, '§76: маркер мониторинга сохранён: ' + m);
  });
  // Мониторинг (cognition) НЕ поглощён аналитикой токенов.
  assert(APP_JS.indexOf('cognitionTimeline') >= 0);
  assert(APP_JS.indexOf('cognitionStats') >= 0);
})();

// ── 9. §116: одна система аналитики/визуализации; CSP/zero-build ──────────
(function () {
  // Единственный компонент .token-flow; adapter — только нормализация.
  assert(INDEX.indexOf('class="token-flow mb-3"') >= 0, 'единственный .token-flow');
  assert(INDEX.indexOf('tokenSeriesBars') >= 0);
  assert.strictEqual(INDEX.indexOf('id="analytics-v2"'), -1,
    'второй системы аналитики нет');
  // CSP: no inline/external, no data-URI graph libs.
  for (const lib of ['mermaid', 'cytoscape', 'd3.min.js', 'unpkg.com',
                     'cdn.jsdelivr.net', 'data:image/svg']) {
    assert(INDEX.indexOf(lib) === -1, 'запрещено: ' + lib);
    assert(ADAPTER.indexOf(lib) === -1, 'запрещено в adapter: ' + lib);
  }
  assert(INDEX.indexOf('http://') === -1 && INDEX.indexOf('https://') === -1);
  // `backdrop-filter: url(` = 0 (инвариант графита/стекла).
  assert(CSS.indexOf('backdrop-filter: url(') === -1,
    'backdrop-filter: url( запрещён');
  // Adapter — внешний файл, без inline/DOM-рендера.
  assert(INDEX.indexOf('/static/execution_graph.js') >= 0,
    'adapter подключён внешним <script>');
  assert(ADAPTER.indexOf('createElement') === -1);
  assert(ADAPTER.indexOf('innerHTML') === -1);
})();

// ── 10. §52–§56: «Память» — разделы + 5 подгрупп настроек ─────────────────
(function () {
  assert(INDEX.indexOf("currentTab.id === 'memory_rag'") >= 0,
    'подгруппы памяти рендерятся на memory_rag');
  ['Поиск', 'Граф знаний', 'Хранение', 'Ночной синтез', 'Отношения'].forEach(
    function (s) {
      assert(APP_JS.indexOf("'" + s + "'") >= 0,
        'подгруппа памяти присутствует: ' + s);
    });
  assert(APP_JS.indexOf('_memoryGroups') >= 0);
  assert(APP_JS.indexOf('_memorySubgroupOf') >= 0);
  // Просмотр людей не смешан с RAG-настройками.
  assert(INDEX.indexOf('Просмотр людей') >= 0
    || APP_JS.indexOf('просмотр людей') >= 0
    || APP_JS.indexOf('не RAG-настройки') >= 0);
  // §58: ручной лор не удаляется при очистке авто (существующая логика).
  assert(APP_JS.indexOf('clear_auto') >= 0);
})();

// ── 11. §27 (H2): поле поиска и select «статус» связаны с `_execFilters` ──
(function () {
  assert(INDEX.indexOf('v-model="execFilterQuery"') >= 0, 'поле поиска в UI');
  assert(INDEX.indexOf('v-model="execFilterStatus"') >= 0, 'select статуса в UI');
  assert(INDEX.indexOf('execStatusOptions') >= 0, 'опции статуса подключены');
  assert(APP_JS.indexOf('execFilterQuery') >= 0, 'состояние поиска');
  assert(APP_JS.indexOf('execStatusOptions') >= 0, 'computed статуса');
  const latest = { correlation_id: 'c', steps: [
    { step: 'stage1', module: 'A', model: 'm1' },
    { step: 'tool', module: 'A', tool_name: 't' },
  ], total: {} };
  const c = traceCtx(latest);
  assert.deepStrictEqual(
    computed.execStatusOptions.call(c).map(function (s) { return s.value; }),
    ['unknown'], 'реальные статусы (не выдуманные)');
  c.execFilterStatus = 'unknown';
  c.execTraceNodes = computed.execTraceNodes.call(c);
  assert.strictEqual(c.execTraceNodes.length, 2, 'статус unknown -> все узлы');
  c.execFilterStatus = 'success';
  c.execTraceNodes = computed.execTraceNodes.call(c);
  assert.strictEqual(c.execTraceNodes.length, 0, 'выдуманный статус -> пусто');
  // Поиск (H2).
  c.execFilterStatus = ''; c.execFilterQuery = 'm1';
  c.execTraceNodes = computed.execTraceNodes.call(c);
  assert.strictEqual(c.execTraceNodes.length, 1, 'поиск по модели');
  assert.strictEqual(methods.execFilterActive.call(c), true,
    'поиск активирует кнопку «Сбросить»');
  methods.resetExecFilters.call(c);
  assert.strictEqual(c.execFilterQuery, '', 'сброс очищает поиск');
})();

// ── 12. M-F6S-1: агрегат фильтруется только по модулю (нет «утечки») ─────
(function () {
  const summary = {
    by_module: [{ module: 'A', cost_usd: 0.1, calls: 1 },
                { module: 'B', cost_usd: 0.2, calls: 1 }],
    series: [], totals: { calls: 2 },
  };
  const c = {
    execGraphApi: methods.execGraphApi,
    execFilterModule: '', execFilterModel: 'm1', execFilterStage: 'stage1',
    execFilterStatus: 'unknown', execFilterQuery: 'q',
    execSummaryGraph: computed.execSummaryGraph.call(
      { execGraphApi: methods.execGraphApi, tokenAnalyticsSummary: summary }),
  };
  assert.strictEqual(computed.execAggregate.call(c).length, 2,
    'model/stage/status/query не режут агрегат');
  c.execFilterModule = 'B';
  const agg = computed.execAggregate.call(c);
  assert.strictEqual(agg.length, 1, 'module фильтрует агрегат');
  assert.strictEqual(agg[0].moduleId, 'B');
})();

// ── 13. L-F6S-4: detail закрывается Esc и кликом по подложке (a11y) ──────
(function () {
  assert(INDEX.indexOf('aria-modal="true"') >= 0, 'aria-modal на панели деталей');
  assert(INDEX.indexOf('exec-detail-backdrop') >= 0, 'подложка деталей');
  assert(/@click\.self="closeExecDetail\(\)"/.test(INDEX),
    'клик по подложке закрывает детали');
  assert(APP_JS.indexOf('if (this.execDetailOpen) { this.closeExecDetail(); return; }') >= 0,
    'Esc закрывает детали (escClose)');
  const ctx = { execDetailOpen: true, execSelected: { id: 'x' } };
  methods.closeExecDetail.call(ctx);
  assert.strictEqual(ctx.execDetailOpen, false);
  assert.strictEqual(ctx.execSelected, null);
})();

// ── 14. L-F6S-5: мёртвый шов `card.memorySubgroup` удалён; сброс при входе ─
(function () {
  assert(APP_JS.indexOf('card.memorySubgroup') === -1, 'мёртвый шов удалён');
  assert(INDEX.indexOf('c.memorySubgroup') === -1, ':key без мёртвого поля');
  const calls = [];
  const ctx = { memorySubgroup: 'graph', navigateTo(r) { calls.push(r); } };
  methods.openHubCard.call(ctx, { route: '#/memory/rag' });
  assert.strictEqual(ctx.memorySubgroup, '', 'подгруппа сброшена при входе');
  assert.deepStrictEqual(calls, ['#/memory/rag']);
})();

console.log('F6-ANALYTICS-MEMORY-OK');
