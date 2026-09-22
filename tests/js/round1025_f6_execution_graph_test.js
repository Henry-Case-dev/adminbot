'use strict';
/* F6 round1025 (memory-analytics-reorg-round1025, ADR-1025-19 D1/D2/D7/D8) —
 * unit-тесты adapter-слоя `web/static/execution_graph.js`
 * (`window.ExecutionGraph`): Backend metrics -> Normalized execution graph.
 *
 * Покрытие §75/§24/§25/§28 (D8):
 *   - однослойный вызов (`single`);
 *   - двухслойный (`stage1` -> `stage2`) — линейная последовательность;
 *   - ветка `tool` (parentIds=[] — parent_id в БД нет);
 *   - неизвестный шаг -> kind 'other' + label из payload;
 *   - неизвестные поля -> null, status='unknown', duration/finished/provider=null;
 *   - price_known=false -> cost=null + «Нет данных» (не $0);
 *   - `algorithm`/`format`/`publish` в enum, но из текущих данных не эмитятся;
 *   - агрегатный ответ (`by_module`/`series`) -> aggregate, parentIds=[];
 *   - два режима не смешиваются (fromTrace != fromSummary);
 *   - фильтры модуль/модель/этап/статус;
 *   - отсутствие второй визуализации: adapter — единственный источник узлов.
 *
 * Запуск: node tests/js/round1025_f6_execution_graph_test.js → F6-EXECGRAPH-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const G = require(path.join(ROOT, 'web', 'static', 'execution_graph.js'));

function kinds(g) { return g.nodes.map(function (n) { return n.kind; }); }
function node(g, id) { return g.nodes.find(function (n) { return n.id === id; }); }

// ── 1. Однослойный вызов: single -> один llm-узел, итог известен ───────────
(function () {
  const g = G.fromTrace({
    correlation_id: 'c1', ts: '2026-09-19T12:00:00+00:00',
    steps: [{ step: 'single', module: 'direct_chat', model: 'm1',
              input_tokens: 50, output_tokens: 5,
              cost_usd: 0.0001, price_known: true }],
    total: { input_tokens: 50, output_tokens: 5, cost_usd: 0.0001, calls: 1 },
  });
  assert.strictEqual(g.empty, false);
  assert.deepStrictEqual(kinds(g), ['llm']);
  assert.strictEqual(g.runId, 'c1');
  const n = g.nodes[0];
  assert.strictEqual(n.id, 'c1:0');
  assert.strictEqual(n.stageKey, 'single');
  assert.strictEqual(n.stageLabel, 'Один вызов');
  assert.deepStrictEqual(n.parentIds, [], 'первый узел без parentIds');
  assert.strictEqual(n.status, 'unknown', 'статус не выдумывается');
  assert.strictEqual(n.durationMs, null);
  assert.strictEqual(n.finishedAt, null);
  assert.strictEqual(n.provider, null);
  assert.strictEqual(n.cost, 0.0001);
  assert.strictEqual(n.costCurrency, 'USD');
  assert.strictEqual(g.totals.priceKnown, true);
  assert.strictEqual(g.totals.cost, 0.0001);
})();

// ── 2. Двухслойный вызов: stage1 -> stage2 (спина по времени) ───────────────
(function () {
  const g = G.fromTrace({
    correlation_id: 'c2', ts: '2026-09-19T12:00:00+00:00',
    steps: [
      { step: 'stage1', module: 'direct_chat', model: 'm1',
        input_tokens: 4000, output_tokens: 100, cost_usd: 0.001,
        price_known: true },
      { step: 'stage2', module: 'direct_chat', model: 'm2',
        input_tokens: 500, output_tokens: 600, cost_usd: 0.002,
        price_known: true },
    ],
    total: { input_tokens: 4500, output_tokens: 700, cost_usd: 0.003,
             calls: 2 },
  });
  assert.deepStrictEqual(kinds(g), ['llm', 'llm']);
  assert.deepStrictEqual(g.nodes[0].parentIds, []);
  assert.deepStrictEqual(g.nodes[1].parentIds, ['c2:0'],
    'линейная связь по ts подтверждена');
  assert.deepStrictEqual(g.edges, [{ from: 'c2:0', to: 'c2:1' }]);
  assert.strictEqual(g.nodes[0].stageLabel, 'Слой 1');
  assert.strictEqual(g.nodes[1].stageLabel, 'Слой 2');
  assert.strictEqual(g.hasBranch, false);
  assert.strictEqual(g.main.length, 2, 'main — вертикальная последовательность');
})();

// ── 3. Ветка tool: kind 'tool', parentIds=[] (parent_id в БД нет) ──────────
(function () {
  const g = G.fromTrace({
    correlation_id: 'c3',
    steps: [
      { step: 'stage1', input_tokens: 100, output_tokens: 10,
        cost_usd: 0.001, price_known: true },
      { step: 'tool', tool_name: 'web_search', input_tokens: 200,
        output_tokens: 20, cost_usd: 0.0005, price_known: true },
      { step: 'stage2', input_tokens: 300, output_tokens: 30,
        cost_usd: 0.002, price_known: true },
    ],
    total: { input_tokens: 600, output_tokens: 60, cost_usd: 0.0035,
             calls: 3 },
  });
  assert.deepStrictEqual(kinds(g), ['llm', 'tool', 'llm']);
  const tool = node(g, 'c3:1');
  assert.deepStrictEqual(tool.parentIds, [],
    'tool без подтверждённого parent_id -> []');
  assert.strictEqual(tool.stageLabel, 'Инструмент: web_search');
  assert.strictEqual(tool.metadata.toolName, 'web_search');
  assert.strictEqual(tool.kindLabel, 'Инструмент');
  // Спина не рвётся: stage2 связан со stage1 (не с tool).
  assert.deepStrictEqual(g.nodes[2].parentIds, ['c3:0']);
  assert(!g.edges.some(function (e) { return e.from === 'c3:1'; }),
    'ложного ребра tool за tool быть не должно');
})();

// ── 4. Неизвестный шаг -> 'other' + label из payload ──────────────────────
(function () {
  const g = G.fromTrace({
    correlation_id: 'c4',
    steps: [{ step: 'mystery_step', input_tokens: 1, output_tokens: 1,
              cost_usd: 0, price_known: true }],
    total: { calls: 1 },
  });
  assert.deepStrictEqual(kinds(g), ['other']);
  assert.strictEqual(g.nodes[0].kindLabel, 'Шаг');
  assert(g.nodes[0].stageLabel.indexOf('mystery_step') >= 0,
    'неизвестный этап подписывается сырым ключом (§30 fallback)');
})();

// ── 5. Отсутствие полей -> null (не выдумываем) ───────────────────────────
(function () {
  const g = G.fromTrace({
    correlation_id: 'c5', steps: [{ step: 'single' }], total: {},
  });
  const n = g.nodes[0];
  assert.strictEqual(n.moduleId, null);
  assert.strictEqual(n.model, null);
  assert.strictEqual(n.inputTokens, null);
  assert.strictEqual(n.outputTokens, null);
  assert.strictEqual(n.cost, null, 'нет price_known=true -> cost=null');
  assert.strictEqual(n.costCurrency, null);
  assert.strictEqual(n.priceKnown, false);
})();

// ── 6. Неизвестная цена -> cost=null, итог без цены («Нет данных») ────────
(function () {
  const g = G.fromTrace({
    correlation_id: 'c6',
    steps: [{ step: 'image', input_tokens: 0, output_tokens: 0,
              cost_usd: 0, price_known: false }],
    total: { input_tokens: 0, output_tokens: 0, cost_usd: 0, calls: 1 },
  });
  assert.strictEqual(g.nodes[0].priceKnown, false);
  assert.strictEqual(g.nodes[0].cost, null, '$0 запрещён при неизвестной цене (§28)');
  assert.strictEqual(g.totals.priceKnown, false);
  assert.strictEqual(g.totals.cost, null);
})();

// ── 7. Подтверждённый ноль -> cost=0 (не «Нет данных») ────────────────────
(function () {
  const g = G.fromTrace({
    correlation_id: 'c7',
    steps: [{ step: 'single', cost_usd: 0, price_known: true }],
    total: { cost_usd: 0, calls: 1 },
  });
  assert.strictEqual(g.nodes[0].priceKnown, true);
  assert.strictEqual(g.nodes[0].cost, 0, 'реально 0 отличается от неизвестной');
  assert.strictEqual(g.totals.priceKnown, true);
  assert.strictEqual(g.totals.cost, 0);
})();

// ── 8. algorithm/format/publish в enum, но не эмитятся из текущих данных ──
(function () {
  ['algorithm', 'format', 'publish'].forEach(function (k) {
    assert(G.KIND_ENUM.indexOf(k) >= 0, 'kind-enum содержит ' + k);
  });
  // Из текущих реальных шагов algorithm не появляется (§24).
  const g = G.fromTrace({
    correlation_id: 'c8',
    steps: [{ step: 'stage1' }, { step: 'tool' }, { step: 'single' }],
    total: {},
  });
  assert(kinds(g).indexOf('algorithm') === -1,
    'алгоритмические узлы из текущих данных не выдумываются');
  // Резервный маппинг готов (Эпик 2): algorithm -> kind 'algorithm'.
  assert.strictEqual(G.kindOf('algorithm'), 'algorithm');
  // LLM-токены для algorithm не подставляются: metrics=null по умолчанию.
  assert.strictEqual(G.fromTrace({ correlation_id: 'x',
    steps: [{ step: 'algorithm' }] }).nodes[0].metrics, null);
})();

// ── 9. Пустые ответы (fail-open kill-switch) ──────────────────────────────
(function () {
  const g = G.fromTrace({ correlation_id: '', ts: null, steps: [],
                          total: { input_tokens: 0, output_tokens: 0,
                                   cost_usd: 0, calls: 0 } });
  assert.strictEqual(g.empty, true);
  assert.deepStrictEqual(g.nodes, []);
  assert.strictEqual(g.runId, null, 'пустой correlation_id -> null');
  assert.strictEqual(G.fromTrace(null).empty, true);
  assert.strictEqual(G.fromTrace(undefined).empty, true);
})();

// ── 10. Агрегат периода: by_module/series, parentIds=[], не смешивается ───
(function () {
  const g = G.fromSummary({
    period: 'week',
    totals: { input_tokens: 100, output_tokens: 20, cost_usd: 0.5,
              calls: 4 },
    by_module: [
      { module: 'direct_chat', cost_usd: 0.4, input_tokens: 90,
        output_tokens: 18, calls: 3 },
      { module: 'summary', cost_usd: 0.1, input_tokens: 10,
        output_tokens: 2, calls: 1 },
    ],
    series: [{ bucket: '2026-09-19T00:00:00+00:00', cost_usd: 0.5,
               calls: 4 }],
  });
  assert.strictEqual(g.period, 'week');
  assert.strictEqual(g.empty, false);
  assert.strictEqual(g.aggregate.length, 2);
  assert.strictEqual(g.aggregate[0].moduleId, 'direct_chat');
  assert.deepStrictEqual(g.aggregate[0].parentIds, [],
    'агрегатные узлы без связей (§26)');
  assert.strictEqual(g.aggregate[0].status, 'unknown');
  assert.strictEqual(g.aggregate[0].model, null);
  assert.strictEqual(g.totals.calls, 4);
  assert.strictEqual(g.series.length, 1);
  // Режимы не смешиваются: у агрегата нет полей трассировки.
  assert.strictEqual(g.aggregate[0].runId, null);
  const t = G.fromTrace({ correlation_id: 'c', steps: [{ step: 'single' }],
                          total: {} });
  assert(!Object.prototype.hasOwnProperty.call(t, 'aggregate'),
    'fromTrace не отдаёт aggregate');
})();

// ── 11. Фильтры §27: модуль/модель/этап/статус + поиск (query) ────────────
(function () {
  const g = G.fromTrace({
    correlation_id: 'c11',
    steps: [
      { step: 'stage1', module: 'A', model: 'm1' },
      { step: 'stage2', module: 'B', model: 'm2' },
      { step: 'tool', module: 'A', tool_name: 'web_search' },
    ],
    total: {},
  });
  assert.strictEqual(G.filter(g.nodes, {}).length, 3, 'пустой фильтр — все');
  assert.strictEqual(G.filter(g.nodes, { module: 'A' }).length, 2);
  assert.strictEqual(G.filter(g.nodes, { model: 'm2' }).length, 1);
  assert.strictEqual(G.filter(g.nodes, { stage: 'tool' }).length, 1);
  assert.strictEqual(G.filter(g.nodes, { status: 'unknown' }).length, 3);
  assert.strictEqual(G.filter(g.nodes, { status: 'success' }).length, 0,
    'выдуманный статус не существует');
  // §27 поиск (H2): подстрока без регистра по реальным полям узла.
  assert.strictEqual(G.filter(g.nodes, { query: 'web_search' }).length, 1,
    'поиск по инструменту');
  assert.strictEqual(G.filter(g.nodes, { query: 'M2' }).length, 1,
    'поиск по модели без регистра');
  assert.strictEqual(G.filter(g.nodes, { query: 'слой' }).length, 2,
    'поиск по русскому label этапа');
  assert.strictEqual(G.filter(g.nodes, { query: 'неттакого' }).length, 0,
    'нет совпадений -> пусто (honest empty-state)');
  // Пустая строка поиска = без ограничения.
  assert.strictEqual(G.filter(g.nodes, { query: '   ' }).length, 3);
  // Комбинация фильтров работает конъюнктивно.
  assert.strictEqual(G.filter(g.nodes, { module: 'A', query: 'инструмент' }).length, 1);
})();

// ── 12. detail(): только реальные поля, отсутствующие -> null ─────────────
(function () {
  const g = G.fromTrace({
    correlation_id: 'c12',
    steps: [{ step: 'stage1', module: 'A', model: 'm1', input_tokens: 5,
              output_tokens: 6, cost_usd: 0.1, price_known: true }],
    total: {},
  });
  const d = G.detail(g.nodes[0]);
  assert.strictEqual(d.stageLabel, 'Слой 1');
  assert.strictEqual(d.moduleId, 'A');
  assert.strictEqual(d.model, 'm1');
  assert.strictEqual(d.provider, null, 'провайдер не выдуман');
  assert.strictEqual(d.durationMs, null);
  assert.strictEqual(d.status, 'unknown');
  assert.strictEqual(G.detail(null), null);
})();

// ── 13. Статические инварианты §116: одна визуализация, zero-build ────────
(function () {
  const SRC = fs.readFileSync(
    path.join(ROOT, 'web', 'static', 'execution_graph.js'), 'utf8');
  for (const lib of ['mermaid', 'cytoscape', 'd3.min.js', 'chart.js',
                     'unpkg.com', 'cdn.jsdelivr.net', 'http://', 'https://']) {
    assert(SRC.indexOf(lib) === -1, 'запрещён внешний ресурс: ' + lib);
  }
  // Не второй визуализации: модуль не рисует DOM (нет createElement/innerHTML).
  assert(SRC.indexOf('createElement') === -1, 'adapter не рисует DOM');
  assert(SRC.indexOf('innerHTML') === -1, 'adapter не рисует DOM');
  // Контракт §25: не выдумываем parent_id / status success.
  assert(SRC.indexOf("status: 'unknown'") !== -1);
})();

console.log('F6-EXECGRAPH-OK');
