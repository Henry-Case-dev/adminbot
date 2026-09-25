'use strict';
/* S8 round1026 (summary-analytics-adapter-round1026, ADR-1026-10
 * D2/D3/D4/D6/D8) — unit-тесты adapter-слоя `web/static/execution_graph.js`
 * для реальных этапов Эпика 2 и backend-графа одного прогона Саммари.
 *
 * Покрытие (S6/T-3446/T-3450 — перепрофилирование publish; не удаление):
 *   - маппинг реальных шагов (§111/D2): filter→algorithm, l1_clusterizer→llm,
 *     l2_writer→llm, formatting/format→format; publication→publish
 *     (**активирован в S6**);
 *   - `fromExecution` — вертикальная последовательность одного run_id
 *     (filter → L1 → L2 → format → publish), только реальные узлы;
 *   - publish-узлы рендерятся (не отбрасываются), `publicationStatus` —
 *     реальный, нет данных → null (не 'gated');
 *   - честная стоимость: неизвестная цена → null («Нет данных»), не $0;
 *   - `L-F6S-1`: fromSummary честен по `price_known`;
 *   - статика: одна визуализация, CSP/zero-build, §112-блок, интеграция app.js.
 *
 * Запуск: node tests/js/round1026_s8_execution_graph_test.js → S8-EXECGRAPH-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const G = require(path.join(ROOT, 'web', 'static', 'execution_graph.js'));

const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const ADAPTER = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'execution_graph.js'), 'utf8');

function kinds(g) { return g.nodes.map(function (n) { return n.kind; }); }

// ── 1. Маппинг реальных этапов Эпика 2 (§111/D2) ──────────────────────────
(function () {
  assert.strictEqual(G.kindOf('filter'), 'algorithm');
  assert.strictEqual(G.kindOf('l1_clusterizer'), 'llm');
  assert.strictEqual(G.kindOf('l2_writer'), 'llm');
  assert.strictEqual(G.kindOf('formatting'), 'format');
  assert.strictEqual(G.kindOf('format'), 'format');
  // publication активирован в S6 (ADR-1026-11 D6): маппинг/подпись есть.
  assert.strictEqual(G.kindOf('publication'), 'publish');
  assert.strictEqual(G.kindOf('publish'), 'publish');
  // Ни один реальный шаг Эпика 2 не попадает в other.
  ['filter', 'l1_clusterizer', 'l2_writer', 'formatting'].forEach(function (s) {
    assert.notStrictEqual(G.kindOf(s), 'other', 'реальный шаг в other: ' + s);
  });
  // ru-подписи реальных этапов.
  assert.strictEqual(G.STEP_LABEL['filter'], 'Алгоритмический фильтр');
  assert.strictEqual(G.STEP_LABEL['l1_clusterizer'], 'L1 Кластеризатор');
  assert.strictEqual(G.STEP_LABEL['l2_writer'], 'L2 Писатель');
  assert.strictEqual(G.STEP_LABEL['formatting'], 'Форматирование');
})();

// ── 2. fromExecution: реальный граф одного прогона (filter→L1→L2→format) ──
(function () {
  const payload = {
    run_id: 'r1', started_at: '2026-09-24T10:00:00+00:00',
    publication_status: 'published_rich',
    nodes: [
      { id: 'r1:filter', runId: 'r1', parentIds: [], kind: 'algorithm',
        stageKey: 'filter', stageLabel: 'Алгоритмический фильтр', status: 'ok',
        provider: null, model: null, inputTokens: null, outputTokens: null,
        cost: null, costCurrency: null, priceKnown: false, durationMs: 12.5,
        metrics: { source_count: 10, saved_count: 7, restored_count: 2,
                   drop_percent: 30.0, status: 'ok' },
        metadata: { kindGroup: 'algorithm' } },
      { id: 'r1:l1_clusterizer', runId: 'r1', parentIds: ['r1:filter'],
        kind: 'llm', stageKey: 'l1_clusterizer',
        stageLabel: 'L1 Кластеризатор', status: 'unknown', model: 'm1',
        inputTokens: 100, outputTokens: 20, cost: 0.001,
        costCurrency: 'USD', priceKnown: true, durationMs: null,
        metrics: null, metadata: { tokensEstimated: false } },
      { id: 'r1:l2_writer', runId: 'r1', parentIds: ['r1:l1_clusterizer'],
        kind: 'llm', stageKey: 'l2_writer', stageLabel: 'L2 Писатель',
        status: 'unknown', model: 'm1', inputTokens: 200, outputTokens: 80,
        cost: 0.002, costCurrency: 'USD', priceKnown: true, durationMs: null,
        metrics: null, metadata: { tokensEstimated: false } },
      { id: 'r1:formatting', runId: 'r1', parentIds: ['r1:l2_writer'],
        kind: 'format', stageKey: 'formatting', stageLabel: 'Форматирование',
        status: 'ok', model: null, inputTokens: null, outputTokens: null,
        cost: null, costCurrency: null, priceKnown: false, durationMs: 5.0,
        metrics: { channel: 'rich', paragraphs: 4, status: 'ok' },
        metadata: {} },
    ],
    edges: [
      { from: 'r1:filter', to: 'r1:l1_clusterizer' },
      { from: 'r1:l1_clusterizer', to: 'r1:l2_writer' },
      { from: 'r1:l2_writer', to: 'r1:formatting' },
    ],
    metrics: {
      source_count: 10, filtered_count: 7, restored_count: 2,
      drop_percent: 30.0, threads_count: 3,
      tokens: { l1: { input_tokens: 100, output_tokens: 20, price_known: true },
                l2: { input_tokens: 200, output_tokens: 80, price_known: true },
                total: { price_known: true } },
      cost: { l1: 0.001, l2: 0.002, total: 0.003 },
      duration_ms: 900.0, cover_status: 'ok',
      publication_status: 'published_rich',
    },
  };
  const g = G.fromExecution(payload);
  assert.strictEqual(g.empty, false);
  assert.strictEqual(g.runId, 'r1');
  assert.deepStrictEqual(kinds(g), ['algorithm', 'llm', 'llm', 'format']);
  assert.deepStrictEqual(g.nodes.map(function (n) { return n.stageKey; }),
    ['filter', 'l1_clusterizer', 'l2_writer', 'formatting']);
  assert.deepStrictEqual(g.nodes[0].parentIds, [], 'первый узел без связи');
  assert.deepStrictEqual(g.nodes[1].parentIds, ['r1:filter']);
  assert.deepStrictEqual(g.nodes[3].parentIds, ['r1:l2_writer']);
  assert.strictEqual(g.edges.length, 3);
  assert.strictEqual(g.hasBranch, false, 'ветвление не достраивается');
  // algorithm — только реальные метрики, БЕЗ LLM-токенов (§24).
  const alg = g.nodes[0];
  assert.strictEqual(alg.inputTokens, null);
  assert.strictEqual(alg.outputTokens, null);
  assert.strictEqual(alg.cost, null);
  assert.strictEqual(alg.metrics.source_count, 10);
  assert.strictEqual(alg.metrics.drop_percent, 30.0);
  // §112 пробрасывается как есть; публикация — реальный статус (S6).
  assert.strictEqual(g.metrics.publication_status, 'published_rich');
  assert.strictEqual(g.publicationStatus, 'published_rich');
  assert.strictEqual(g.totals.calls, 2);
  assert.strictEqual(g.totals.priceKnown, true);
  assert.strictEqual(g.totals.cost, 0.003);
})();

// ── 3. Publish активирован (S6): узел рендерится, статус реален ───────────
(function () {
  const g = G.fromExecution({
    run_id: 'r2', publication_status: 'published_text', nodes: [
      { id: 'r2:l2_writer', kind: 'llm', stageKey: 'l2_writer',
        parentIds: [], priceKnown: false, metrics: null, metadata: {} },
      { id: 'r2:publication', kind: 'publish', stageKey: 'publication',
        parentIds: ['r2:l2_writer'], status: 'ok', priceKnown: false,
        metrics: { channel: 'text', message_id: 7, status: 'ok' },
        metadata: {} },
    ], edges: [{ from: 'r2:l2_writer', to: 'r2:publication' }],
  });
  assert.deepStrictEqual(kinds(g), ['llm', 'publish'],
    'publish-узел активирован в S6 (не отбрасывается)');
  assert.strictEqual(g.edges.length, 1, 'ребро к publish сохранено');
  assert.strictEqual(g.publicationStatus, 'published_text');
  assert.strictEqual(g.nodes[1].metrics.message_id, 7);
  assert.strictEqual(g.nodes[1].stageLabel, 'Публикация');
  // Нет данных о публикации → null («Нет данных»), не 'gated'.
  const empty = G.fromExecution({ run_id: 'r3', nodes: [] });
  assert.strictEqual(empty.publicationStatus, null,
    'нет данных → null, не gated');
})();

// ── 4. Честная стоимость: неизвестная цена → null, не $0 (§28/D4) ────────
(function () {
  const g = G.fromExecution({
    run_id: 'r3', nodes: [
      { id: 'r3:l1_clusterizer', kind: 'llm', stageKey: 'l1_clusterizer',
        parentIds: [], priceKnown: false, cost: 0, costCurrency: 'USD',
        inputTokens: 5, outputTokens: 1, metrics: null, metadata: {} },
    ], metrics: null,
  });
  assert.strictEqual(g.nodes[0].cost, null, '$0 запрещён при неизвестной цене');
  assert.strictEqual(g.nodes[0].costCurrency, null);
  assert.strictEqual(g.totals.priceKnown, false);
})();

// ── 5. Пустой/отсутствующий ответ → пустой граф (fail-open) ───────────────
(function () {
  [null, undefined, {}, { nodes: [] }].forEach(function (p) {
    const g = G.fromExecution(p);
    assert.strictEqual(g.empty, true);
    assert.deepStrictEqual(g.nodes, []);
  });
})();

// ── 6. L-F6S-1: fromSummary честен по price_known (нет выдуманного $0) ────
(function () {
  const g = G.fromSummary({
    period: 'day',
    totals: { input_tokens: 10, output_tokens: 2, cost_usd: 0.5, calls: 1,
              price_known: false },
    by_module: [{ module: 'summary', cost_usd: 0.5, input_tokens: 10,
                  output_tokens: 2, calls: 1, price_known: false }],
    series: [],
  });
  assert.strictEqual(g.totals.priceKnown, false);
  assert.strictEqual(g.totals.cost, null, 'неизвестная цена → «Нет данных»');
  assert.strictEqual(g.aggregate[0].priceKnown, false);
  assert.strictEqual(g.aggregate[0].cost, null);
  // Обратная совместимость: без поля price_known агрегат остаётся известным.
  const old = G.fromSummary({ totals: { cost_usd: 1, calls: 1 },
    by_module: [{ module: 'm', cost_usd: 1, calls: 1 }] });
  assert.strictEqual(old.totals.priceKnown, true);
  assert.strictEqual(old.aggregate[0].priceKnown, true);
})();

// ── 7. Статика: одна визуализация, CSP/zero-build, §112, интеграция app.js ─
(function () {
  for (const lib of ['mermaid', 'cytoscape', 'd3.min.js', 'chart.js',
                     'unpkg.com', 'cdn.jsdelivr.net', 'http://', 'https://']) {
    assert(ADAPTER.indexOf(lib) === -1, 'запрещён внешний ресурс: ' + lib);
  }
  assert(ADAPTER.indexOf('fromExecution') !== -1, 'fromExecution отсутствует');
  assert(ADAPTER.indexOf('createElement') === -1, 'adapter не рисует DOM');
  assert(ADAPTER.indexOf('innerHTML') === -1, 'adapter не рисует DOM');
  // §116/§111: одна карта вызовов; literal 'algorithm' в шаблоне не появляется.
  assert.strictEqual(INDEX.split('class="token-flow mb-3"').length - 1, 1,
    'должна быть ровно одна карта вызовов');
  assert(INDEX.indexOf('execMetricsRows') !== -1, '§112-блок не подключён');
  assert(INDEX.indexOf('algorithm') === -1,
    'фиктивные kind-литералы в шаблоне запрещены');
  // Интеграция: app.js использует fromExecution через execGraph.
  assert(APP_JS.indexOf('execGraph: function') !== -1, 'execGraph не найден');
  assert(APP_JS.indexOf('EG.fromExecution') !== -1, 'fromExecution не вызван');
  assert(APP_JS.indexOf('/api/analytics/execution/latest') !== -1,
    'эндпоинт графа не запрашивается');
  assert(APP_JS.indexOf('execPublicationLabel') !== -1, 'честная подпись публикации');
  assert(APP_JS.indexOf('недоступна (гейт S6)') === -1,
    'S6: подписи гейта больше нет');
  assert(APP_JS.indexOf("'published_rich'") !== -1 &&
    APP_JS.indexOf("'published_text'") !== -1,
    'S6: подписи реальных статусов публикации');
})();

// ── 8. A9 (ADR-1026-22 D7/D10): 9 этапов §51 display-only ─────────────────
(function () {
  var expected = {
    decision: 'algorithm', memory_lookup: 'tool', rag: 'tool',
    web_extraction: 'tool', factcheck: 'tool', image_prompt: 'algorithm',
    image_generation: 'tool', reaction: 'tool', text_generation: 'llm',
  };
  Object.keys(expected).forEach(function (s) {
    assert.strictEqual(G.kindOf(s), expected[s], 'kind ' + s);
    assert(G.STEP_LABEL[s], 'label ' + s);
  });
  // fromExecution пропускает агентные узлы без изменений (только отображение):
  // algorithmic-узел честно без токенов, text_generation — реальные токены.
  var g = G.fromExecution({
    run_id: 'r9',
    nodes: [
      { id: 'r9:decision', kind: 'algorithm', stageKey: 'decision',
        parentIds: [], status: 'ok', priceKnown: false,
        metrics: { action: 'reply' }, metadata: { agentic: true } },
      { id: 'r9:text_generation', kind: 'llm', stageKey: 'text_generation',
        parentIds: ['r9:decision'], status: 'ok', model: 'm1',
        inputTokens: 10, outputTokens: 5, cost: 0.001, costCurrency: 'USD',
        priceKnown: true, metrics: null, metadata: {} },
    ],
    edges: [{ from: 'r9:decision', to: 'r9:text_generation' }],
    metrics: null,
  });
  assert.deepStrictEqual(g.nodes.map(function (n) { return n.stageKey; }),
    ['decision', 'text_generation']);
  assert.strictEqual(g.nodes[0].kind, 'algorithm');
  assert.strictEqual(g.nodes[0].status, 'ok');
  assert.strictEqual(g.nodes[0].inputTokens, null);
  assert.strictEqual(g.nodes[1].kind, 'llm');
  assert.strictEqual(g.nodes[1].inputTokens, 10);
  assert.strictEqual(g.edges.length, 1);
})();

console.log('S8-EXECGRAPH-OK');
