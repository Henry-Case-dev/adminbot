'use strict';
/* F3 round1024 (token-metrics-nodeflow-round1024, ADR-1024-7) — AMEND
 * F6 round1025 (ADR-1025-19 D1/D2): визуальное дерево вызова (Node Flow) в
 * «Аналитике» теперь строит adapter `window.ExecutionGraph`, а `tokenFlowTree`
 * — только view-проекция нормализованных узлов.
 *
 * Обновление маркер-теста (атомарно, ADR-1025-19 AMEND/SUPERSEDE-карта):
 *   - синтетические узлы root/result БОЛЬШЕ не создаются (§24);
 *   - kind больше не `synthesizer/verbalizer/single/image`, а канонический
 *     enum `llm/tool/algorithm/format/publish/other` (§24);
 *   - tool больше НЕ привязывается к ближайшему Синтезатору: parentIds=[] и
 *     ветки не выдумываются (§25, SUPERSEDE прежнего инференса);
 *   - `$0` больше не подставляется вместо неизвестной цены (§28).
 *
 * Покрытие: одно-/двухслойный вызов, tool, single/image, пустой ответ,
 * «оц.»/«нет данных», фильтры, kill-switch uiFlag, wiring шаблона, CSP.
 *
 * Запуск: node tests/js/round1024_nodeflow_test.js  → NODEFLOW-UNIT-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

// ── Vue/document(window) заглушки (как в прежнем тесте) ─────────────────────
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
const ROOT = path.join(__dirname, '..', '..');
global.window.ExecutionGraph = require(
  path.join(ROOT, 'web', 'static', 'execution_graph.js'));
const _bodyChildren = [];
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() {
        const idx = _bodyChildren.indexOf(this);
        if (idx >= 0) _bodyChildren.splice(idx, 1);
      },
    };
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
  value: { clipboard: { writeText: async function () { throw new Error('x'); } } },
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

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;
assert(methods && methods.uiFlag, 'root.methods.uiFlag не найден');
assert(methods && methods.execGraphApi, 'methods.execGraphApi не найден (F6 adapter)');
assert(computed && computed.tokenFlowTree,
  'tokenFlowTree должен быть computed (не method)');
assert(computed && computed.tokenSeriesBars,
  'tokenSeriesBars должен быть computed (не method)');
assert(!methods.tokenFlowTree && !methods.tokenSeriesBars,
  'дубли methods.tokenFlowTree/tokenSeriesBars должны быть удалены');

// Контекст-подставка для computed-цепочки adapter-проекции.
function ctx(latest) {
  const c = {
    tokenAnalyticsLatest: latest,
    execFilterModule: '', execFilterModel: '',
    execFilterStage: '', execFilterStatus: '',
    execGraphApi: methods.execGraphApi,
    _execFilters: methods._execFilters,
    execFilterActive: methods.execFilterActive,
  };
  c.execTrace = computed.execTrace.call(c);
  c.execTraceNodes = computed.execTraceNodes.call(c);
  return c;
}
function tree(latest) { return computed.tokenFlowTree.call(ctx(latest)); }
function kinds(t) { return t.nodes.map(function (n) { return n.kind; }); }
function edgeSet(t) {
  return t.edges.map(function (e) { return e.from + '>' + e.to; });
}

function latest(steps, total, ts) {
  return { correlation_id: 'RUN', ts: ts || null,
           steps: steps, total: total || {} };
}

// ── 1. Двухслойный вызов: два llm-узла, линейная спина, без root/result ─────
(function () {
  const t = tree(latest([
    { step: 'stage1', module: 'direct_chat', input_tokens: 4000,
      output_tokens: 100, cost_usd: 0.001, price_known: true },
    { step: 'stage2', module: 'direct_chat', input_tokens: 500,
      output_tokens: 600, cost_usd: 0.002, price_known: true },
  ], { input_tokens: 4500, output_tokens: 700, cost_usd: 0.003, calls: 2 },
     '2026-09-19T12:00:00+00:00'));
  assert.strictEqual(t.empty, false);
  assert.deepStrictEqual(kinds(t), ['llm', 'llm'],
    'синтетические root/result больше не создаются');
  assert.strictEqual(t.nodes[0].title, 'Слой 1');
  assert.strictEqual(t.nodes[1].title, 'Слой 2');
  assert.deepStrictEqual(t.nodes[0].parentIds, []);
  assert.deepStrictEqual(t.nodes[1].parentIds, ['RUN:0']);
  assert.deepStrictEqual(edgeSet(t), ['RUN:0>RUN:1']);
  assert.strictEqual(t.hasBranch, false);
  assert.strictEqual(t.totals.cost, 0.003);
})();

// ── 2. tool: НЕ привязан к Синтезатору, parentIds=[], ветки не выдуманы ────
(function () {
  const t = tree(latest([
    { step: 'stage1', input_tokens: 100, output_tokens: 10,
      cost_usd: 0.001, price_known: true },
    { step: 'tool', tool_name: 'web_search', input_tokens: 200,
      output_tokens: 20, cost_usd: 0.0005, price_known: true },
    { step: 'stage2', input_tokens: 300, output_tokens: 30,
      cost_usd: 0.002, price_known: true },
  ], { input_tokens: 600, output_tokens: 60, cost_usd: 0.0035 }));
  assert.deepStrictEqual(kinds(t), ['llm', 'tool', 'llm']);
  assert.deepStrictEqual(t.nodes[1].parentIds, [],
    'tool без parent_id — связь не выдумывается (§25)');
  assert.strictEqual(t.nodes[1].title, 'Инструмент: web_search');
  assert.strictEqual(t.hasBranch, false, 'ложного ветвления нет');
  assert(!t.main.some(function (n) { return n.children.length; }),
    'tool не привязан к Синтезатору (SUPERSEDE)');
  assert.strictEqual(edgeSet(t).indexOf('RUN:1>RUN:2'), -1,
    'tool не является родителем других узлов');
})();

// ── 3. single / image: линейно, без ложных этапов ─────────────────────────
(function () {
  const t = tree(latest([{ step: 'single', input_tokens: 50,
    output_tokens: 5, cost_usd: 0.0001, price_known: true }]));
  assert.deepStrictEqual(kinds(t), ['llm']);
  assert.strictEqual(t.nodes[0].title, 'Один вызов');
  assert.deepStrictEqual(edgeSet(t), []);
  const ti = tree(latest([{ step: 'image', input_tokens: 0, output_tokens: 0,
    cost_usd: 0, price_known: false }]));
  assert.deepStrictEqual(kinds(ti), ['llm']);
  assert.strictEqual(ti.nodes[0].title, 'Изображение');
  assert.strictEqual(ti.nodes[0].cost, null, '$0 при неизвестной цене запрещён');
})();

// ── 4. Пустой ответ → пустое состояние ────────────────────────────────────
(function () {
  const t = tree(latest([], {}));
  assert.strictEqual(t.empty, true);
  assert.deepStrictEqual(t.nodes, []);
  assert.deepStrictEqual(t.edges, []);
  const t2 = tree(null);
  assert.strictEqual(t2.empty, true);
})();

// ── 5. tokens_estimated → «оц.» в view-проекции; цены честны ───────────────
(function () {
  const t = tree(latest([{ step: 'single', input_tokens: 10, output_tokens: 2,
    cost_usd: 0.00001, tokens_estimated: true, price_known: true }]));
  assert.strictEqual(t.nodes[0].estimated, true);
  assert.strictEqual(t.nodes[0].priceKnown, true);
  assert.strictEqual(t.totals.tokensEstimated, true);
  const unknown = tree(latest([{ step: 'single', input_tokens: 1,
    output_tokens: 1, cost_usd: 0, price_known: false }]));
  assert.strictEqual(unknown.nodes[0].priceKnown, false);
  assert.strictEqual(unknown.nodes[0].cost, null);
  assert.strictEqual(unknown.totals.priceKnown, false);
})();

// ── 6. Неизвестный step → other + label из payload ────────────────────────
(function () {
  const t = tree(latest([{ step: 'mystery_step', input_tokens: 1,
    output_tokens: 1, price_known: true }]));
  assert.deepStrictEqual(kinds(t), ['other']);
  assert(t.nodes[0].title.indexOf('mystery_step') >= 0);
})();

// ── 7. Фильтры §27 фильтруют узлы трассировки ─────────────────────────────
(function () {
  const c = ctx(latest([
    { step: 'stage1', module: 'A', model: 'm1' },
    { step: 'stage2', module: 'B', model: 'm2' },
  ]));
  c.execFilterModule = 'A';
  c.execTraceNodes = computed.execTraceNodes.call(c);
  const t = computed.tokenFlowTree.call(c);
  assert.strictEqual(t.nodes.length, 1);
  assert.strictEqual(t.nodes[0].moduleId, 'A');
  assert.strictEqual(t.filtered, true);
})();

// ── 8. tokenSeriesBars — computed (не менялся) ─────────────────────────────
(function () {
  const bars = computed.tokenSeriesBars.call({
    tokenAnalyticsSummary: { series: [
      { bucket: '2026-09-19T12:00:00+00:00', cost_usd: 1, calls: 2 },
      { bucket: '2026-09-19T13:00:00+00:00', cost_usd: 0, calls: 0 },
    ] },
  });
  assert.strictEqual(bars.length, 2);
  assert.strictEqual(bars[0].height, 100, 'первый бакет — максимум');
  assert(bars[0].label.indexOf('2026-09-19 12:00') === 0);
  assert.strictEqual(
    computed.tokenSeriesBars.call({ tokenAnalyticsSummary: null }).length, 0);
})();

// ── 9. Kill-switch uiFlag (ADR-1024-13, сохранён ADR-1025-19) ──────────────
(function () {
  assert.strictEqual(methods.uiFlag.call({ me: null },
    'TOKEN_FLOW_NODEFLOW_ENABLED'), true);
  assert.strictEqual(methods.uiFlag.call(
    { me: { ui_flags: { TOKEN_FLOW_NODEFLOW_ENABLED: false } } },
    'TOKEN_FLOW_NODEFLOW_ENABLED'), false);
  assert.strictEqual(methods.uiFlag.call(
    { me: { ui_flags: {} } }, 'UNKNOWN_FLAG'), true);
})();

// ── 10. fmtCost §28: $0 только при подтверждённом нуле ─────────────────────
(function () {
  assert.strictEqual(methods.fmtCost(0, true), '$0');
  assert.strictEqual(methods.fmtCost(0, false), 'Нет данных');
  assert.strictEqual(methods.fmtCost(null, true), 'Нет данных');
  assert.strictEqual(methods.fmtCost(null, false), 'Нет данных');
  assert.strictEqual(methods.fmtCost(0.001, true).indexOf('$') === 0, true);
})();

// ── 11. Wiring: шаблон рендерит adapter-узлы + ветку из children ───────────
(function () {
  const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
  assert(INDEX.indexOf('class="token-flow__branch"') !== -1,
    'контейнер ветки сохранён (только подтверждённые рёбра)');
  assert(INDEX.indexOf('v-for="child in node.children"') !== -1);
  assert(INDEX.indexOf('tokenFlowTree.main') !== -1);
  assert(INDEX.indexOf('idx < tokenFlowTree.main.length - 1') !== -1);
  assert(INDEX.indexOf('node.kind === \'result\'') === -1,
    'синтетический result-узел удалён');
  assert(INDEX.indexOf('tokenFlowTree().nodes') === -1);
  assert(INDEX.indexOf('tokenSeriesBars.length') !== -1);
  assert(INDEX.indexOf('tokenSeriesBars()') === -1);
  assert(INDEX.indexOf('График расходов') !== -1);
  assert(/uiFlag\('TOKEN_FLOW_NODEFLOW_ENABLED'\) && tokenSeriesBars\.length/
    .test(INDEX), 'ось графика гейтится флагом (OFF = 10.23)');
  // Два несмешиваемых режима §26.
  assert(INDEX.indexOf("setExecMode('latest')") !== -1);
  assert(INDEX.indexOf("setExecMode('month')") !== -1);
  assert(APP_JS.indexOf('execIsTrace') !== -1);
  assert(APP_JS.indexOf('hasBranch') !== -1 && APP_JS.indexOf('edges') !== -1);
  assert(APP_JS.indexOf('children.push') !== -1, 'ветки из подтверждённых рёбер');
  assert(APP_JS.indexOf('ExecutionGraph') !== -1, 'app.js читает adapter');
})();

// ── 12. Статические инварианты: нейминг + CSP/no-CDN ───────────────────────
(function () {
  const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
  assert(INDEX.indexOf('Аналитика токенов') !== -1);
  assert(INDEX.indexOf('Последний запрос (Дерево вызова)') !== -1);
  assert(INDEX.indexOf('Token Metrics') === -1);
  assert(INDEX.indexOf("uiFlag('TOKEN_FLOW_NODEFLOW_ENABLED')") !== -1);
  assert(APP_JS.indexOf('ui_flags') !== -1);
  for (const lib of ['mermaid', 'cytoscape', 'd3.min.js', 'chart.js',
                     'unpkg.com', 'cdn.jsdelivr.net']) {
    assert(APP_JS.indexOf(lib) === -1, 'запрещена граф-библиотека: ' + lib);
    assert(INDEX.indexOf(lib) === -1, 'запрещена граф-библиотека: ' + lib);
  }
  assert(INDEX.indexOf('http://') === -1 && INDEX.indexOf('https://') === -1);
})();

console.log('NODEFLOW-UNIT-OK');
