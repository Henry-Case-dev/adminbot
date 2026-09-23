/* F6 round1025 (memory-analytics-reorg-round1025, ADR-1025-19 D1/D2/D7).
 *
 * ExecutionGraph — чистый КЛИЕНТСКИЙ adapter-слой
 *   Backend metrics -> Normalized execution graph -> UI
 * (ТЗ §22–§25). Лежит МЕЖДУ ответами /api/analytics/* и рендером
 * (`tokenFlowTree` в app.js), а не внутри SVG/компонента дерева (§25).
 *
 * Zero-build / CSP `script-src 'self'`: обычный внешний файл, без inline,
 * без CDN/data-URI/WebGL/сборщика. Не источник данных — только
 * нормализация/фильтрация/детализация существующих плоских ответов
 * (`/analytics/usage/latest`, `/analytics/usage/summary`).
 *
 * Честность модели (ADR-1025-19 D1/D2, ТЗ §24/§25/§28):
 *  - `id = correlation_id + ':' + index`, `runId = correlation_id`;
 *  - `parentIds` — ТОЛЬКО подтверждённая линейная последовательность того же
 *    `correlation_id` по `ts`; для `tool` и первого узла — `[]` (в БД нет
 *    `parent_id` — связь не выдумывается);
 *  - `status` всегда `'unknown'` (в данных нет статуса);
 *  - `durationMs`/`finishedAt`/`provider` — `null`;
 *  - `cost`/`costCurrency` — `null`, если `price_known !== true` (не `$0`);
 *  - `algorithm`/`format`/`publish` зарезервированы контрактом, но из текущих
 *    данных (`step`) НЕ эмитятся: в `llm_usage_events` таких шагов нет.
 *    LLM-токены для `algorithm` не подставляются никогда.
 *
 * S8 round1026 (ADR-1026-10 D2/D3/D4/D6): добавлены реальные этапы Эпика 2
 * (`filter`→algorithm, `l1_clusterizer`/`l2_writer`→llm, `formatting`→format;
 * `publication`→publish ЗАРЕЗЕРВИРОВАН, GATED) и `fromExecution(payload)` —
 * проекция backend-нормализованного графа одного прогона (узлы + §112).
 * Publish-узлы отбрасываются (S6/D4); связи — подтверждённая линейная
 * последовательность одного `run_id` (D6), ветвление не достраивается.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;           // node unit-тесты
  }
  if (root) {
    root.ExecutionGraph = api;      // браузер: window.ExecutionGraph
  }
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  // kind-enum расширяемый (§22/§30): неизвестный stage -> other + label из
  // payload. Новые узлы Эпика 2 принимаются без рефакторинга рендера.
  var KIND_ENUM = ['llm', 'algorithm', 'tool', 'format', 'publish', 'other'];
  var KIND_LABELS = {
    llm: 'LLM', algorithm: 'Алгоритм', tool: 'Инструмент',
    format: 'Форматирование', publish: 'Публикация', other: 'Шаг',
  };
  // Сырой `step` -> kind (§111/D2). Реальные этапы Эпика 2: filter ->
  // algorithm, l1_clusterizer/l2_writer -> llm, formatting/format -> format.
  // `publication` -> publish — ЗАРЕЗЕРВИРОВАН, но GATED (S6/D4): источник
  // данных отсутствует, поэтому publish-узлы не активируются.
  var STEP_KIND = {
    single: 'llm', stage1: 'llm', stage2: 'llm', image: 'llm',
    tool: 'tool',
    filter: 'algorithm',
    l1_clusterizer: 'llm', l2_writer: 'llm',
    formatting: 'format', format: 'format',
    algorithm: 'algorithm', publish: 'publish', publication: 'publish',
  };
  // ru-словарь этапов (§24): Слой 1/Слой 2/Один вызов/Изображение/Инструмент
  // + реальные этапы Эпика 2.
  var STEP_LABEL = {
    single: 'Один вызов', stage1: 'Слой 1', stage2: 'Слой 2',
    image: 'Изображение', tool: 'Инструмент',
    filter: 'Алгоритмический фильтр',
    l1_clusterizer: 'L1 Кластеризатор', l2_writer: 'L2 Писатель',
    formatting: 'Форматирование', format: 'Форматирование',
    algorithm: 'Алгоритм', publish: 'Публикация', publication: 'Публикация',
  };

  function has(obj, key) {
    return Object.prototype.hasOwnProperty.call(obj, key);
  }

  function kindOf(step) {
    if (step && has(STEP_KIND, step)) return STEP_KIND[step];
    return 'other';
  }

  function stageLabelOf(step, toolName) {
    var base;
    if (step && has(STEP_LABEL, step)) base = STEP_LABEL[step];
    else if (step) base = 'Шаг: ' + step;
    else base = KIND_LABELS.other;
    if (step === 'tool' && toolName) return base + ': ' + toolName;
    return base;
  }

  function num(value) {
    if (value === null || value === undefined) return null;
    var n = Number(value);
    return isNaN(n) ? null : n;
  }

  function strOrNull(value) {
    if (value === null || value === undefined) return null;
    var s = String(value);
    return s === '' ? null : s;
  }

  // Один `step` -> канонический ExecutionNode. Значения только из payload.
  function normalizeStep(step, index, runId, prevId) {
    var s = step || {};
    var kind = kindOf(s.step);
    var priceKnown = s.price_known === true;   // строго подтверждённый ноль/цена
    var isTool = kind === 'tool';
    var parentIds = (!isTool && prevId) ? [prevId] : [];
    return {
      id: (runId == null ? 'run' : String(runId)) + ':' + index,
      runId: runId == null ? null : String(runId),
      parentIds: parentIds,
      kind: kind,
      kindLabel: KIND_LABELS[kind] || KIND_LABELS.other,
      stageKey: (s.step || 'other'),
      stageLabel: stageLabelOf(s.step, s.tool_name),
      moduleId: strOrNull(s.module),
      status: 'unknown',                 // в данных нет статуса — не выдумываем
      provider: null,                    // нет в данных (source != provider)
      model: strOrNull(s.model),
      inputTokens: num(s.input_tokens),
      outputTokens: num(s.output_tokens),
      cost: priceKnown ? num(s.cost_usd) : null,
      costCurrency: priceKnown ? 'USD' : null,
      priceKnown: priceKnown,
      durationMs: null,                  // нет в данных
      startedAt: strOrNull(s.ts),
      finishedAt: null,                  // нет в данных
      metrics: null,                     // algorithm: только реальные метрики
      metadata: {
        toolName: strOrNull(s.tool_name),
        source: strOrNull(s.source),
        tokensEstimated: !!s.tokens_estimated,
        priceKnown: priceKnown,
      },
      children: [],
    };
  }

  // Итоги вызова: цена честна только если ВСЕ шаги с подтверждённой ценой.
  function traceTotals(total, steps) {
    var anyUnknown = false;
    for (var i = 0; i < steps.length; i++) {
      if ((steps[i] || {}).price_known !== true) anyUnknown = true;
    }
    var t = total || {};
    return {
      inputTokens: num(t.input_tokens) || 0,
      outputTokens: num(t.output_tokens) || 0,
      cost: anyUnknown ? null : num(t.cost_usd),
      costCurrency: anyUnknown ? null : 'USD',
      priceKnown: !anyUnknown,
      calls: num(t.calls) || steps.length,
      tokensEstimated: steps.some(function (s) {
        return !!(s && s.tokens_estimated);
      }),
    };
  }

  // РЕЖИМ 1 — трассировка последнего вызова. Только реальные узлы (без
  // синтетических root/result): итоги отдаются отдельным полем `totals`.
  function fromTrace(latest) {
    var steps = (latest && latest.steps) || [];
    var runId = (latest && latest.correlation_id != null
                 && latest.correlation_id !== '')
      ? String(latest.correlation_id) : null;
    var nodes = [];
    var edges = [];
    var prevId = null;
    for (var i = 0; i < steps.length; i++) {
      var node = normalizeStep(steps[i], i, runId, prevId);
      if (node.parentIds.length) {
        edges.push({ from: node.parentIds[0], to: node.id });
      }
      if (node.kind !== 'tool') prevId = node.id;   // спина = не-tool
      nodes.push(node);
    }
    return {
      runId: runId,
      startedAt: strOrNull(latest && latest.ts),
      nodes: nodes,
      edges: edges,
      main: nodes,                 // вертикальная последовательность (§29)
      hasBranch: false,            // parent_id нет -> ветвление не изобретаем
      empty: nodes.length === 0,
      totals: traceTotals(latest && latest.total, steps),
    };
  }

  // РЕЖИМ 2 — агрегат периода. Узлы несут только реальные суммы из API;
  // временных/иерархических связей не изобретаем (parentIds=[]).
  function fromSummary(summary) {
    var s = summary || {};
    // `L-F6S-1` (S8/D4): агрегат честен по `price_known` (BOOL_AND на сервере).
    // Отсутствие поля (старый ответ) → true (обратная совместимость).
    function known(flag) { return flag !== false; }
    var byModule = (s.by_module || []).map(function (m) {
      var k = known(m.price_known);
      return {
        module: strOrNull(m.module),
        cost: k ? num(m.cost_usd) : null,
        inputTokens: num(m.input_tokens),
        outputTokens: num(m.output_tokens),
        calls: num(m.calls) || 0,
        priceKnown: k,
      };
    });
    var series = (s.series || []).map(function (b) {
      var k = known(b.price_known);
      return {
        bucket: strOrNull(b.bucket),
        cost: k ? num(b.cost_usd) : null,
        inputTokens: num(b.input_tokens),
        outputTokens: num(b.output_tokens),
        calls: num(b.calls) || 0,
        priceKnown: k,
      };
    });
    var t = s.totals || {};
    var totalsKnown = known(t.price_known);
    var totals = {
      inputTokens: num(t.input_tokens) || 0,
      outputTokens: num(t.output_tokens) || 0,
      cost: totalsKnown ? num(t.cost_usd) : null,
      costCurrency: totalsKnown ? 'USD' : null,
      priceKnown: totalsKnown,
      calls: num(t.calls) || 0,
    };
    var aggregate = byModule.map(function (m, i) {
      return {
        id: 'agg:' + i,
        runId: null,
        parentIds: [],               // агрегат не трассировка (§26)
        kind: 'other',
        kindLabel: KIND_LABELS.other,
        stageKey: 'aggregate',
        stageLabel: m.module || 'Модуль',
        moduleId: m.module,
        status: 'unknown',
        provider: null,
        model: null,
        inputTokens: m.inputTokens,
        outputTokens: m.outputTokens,
        cost: m.cost,
        costCurrency: m.priceKnown ? 'USD' : null,
        priceKnown: m.priceKnown,
        durationMs: null,
        startedAt: null,
        finishedAt: null,
        metrics: null,
        metadata: { calls: m.calls, aggregate: true },
        children: [],
      };
    });
    return {
      period: strOrNull(s.period),
      byModule: byModule,
      series: series,
      aggregate: aggregate,
      totals: totals,
      empty: aggregate.length === 0 && series.length === 0
             && !totals.calls,
    };
  }

  // S8 (ADR-1026-10 D3/D4/D6): backend-нормализованный ExecutionNode-shape ->
  // клиентская модель. Только реальные поля; publish GATED (узел
  // kind='publish' отбрасывается — S6/D4, вторая визуализация не создаётся).
  function normalizeExecutionNode(n, runId, index) {
    if (!n || typeof n !== 'object') return null;
    var kind = (n.kind && KIND_ENUM.indexOf(n.kind) >= 0) ? n.kind : 'other';
    if (kind === 'publish') return null;   // GATED: publish-узлы не активируются
    var meta = (n.metadata && typeof n.metadata === 'object') ? n.metadata : {};
    var rid = (n.runId != null && n.runId !== '') ? String(n.runId)
              : (runId != null ? runId : null);
    var priceKnown = n.priceKnown === true;
    return {
      id: strOrNull(n.id) || ((rid == null ? 'run' : rid) + ':' + index),
      runId: rid,
      parentIds: Array.isArray(n.parentIds) ? n.parentIds.slice() : [],
      kind: kind,
      kindLabel: KIND_LABELS[kind] || KIND_LABELS.other,
      stageKey: strOrNull(n.stageKey) || kind,
      stageLabel: strOrNull(n.stageLabel) || stageLabelOf(n.stageKey, null),
      moduleId: strOrNull(meta.module),
      status: strOrNull(n.status) || 'unknown',
      provider: strOrNull(n.provider),
      model: strOrNull(n.model),
      inputTokens: num(n.inputTokens),
      outputTokens: num(n.outputTokens),
      cost: priceKnown ? num(n.cost) : null,
      costCurrency: priceKnown ? (strOrNull(n.costCurrency) || 'USD') : null,
      priceKnown: priceKnown,
      durationMs: num(n.durationMs),
      startedAt: strOrNull(n.startedAt),
      finishedAt: strOrNull(n.finishedAt),
      metrics: n.metrics || null,
      metadata: {
        toolName: strOrNull(meta.toolName),
        source: strOrNull(meta.source),
        tokensEstimated: !!meta.tokensEstimated,
        priceKnown: priceKnown,
      },
      children: [],
    };
  }

  // Итоги прогона: честны только при подтверждённой цене (§28/D4).
  function executionTotals(nodes, metrics) {
    var inTok = 0, outTok = 0, calls = 0, anyUnknown = false, estimated = false;
    nodes.forEach(function (n) {
      if (n.kind !== 'llm') return;
      inTok += n.inputTokens || 0;
      outTok += n.outputTokens || 0;
      calls += 1;
      if (!n.priceKnown) anyUnknown = true;
      if (n.metadata.tokensEstimated) estimated = true;
    });
    var totalUsage = (metrics && metrics.tokens && metrics.tokens.total) || null;
    var costTotal = (metrics && metrics.cost) ? metrics.cost.total : null;
    var known = totalUsage ? totalUsage.price_known === true : !anyUnknown;
    return {
      inputTokens: inTok,
      outputTokens: outTok,
      cost: known ? num(costTotal) : null,
      costCurrency: known ? 'USD' : null,
      priceKnown: !!known,
      calls: calls,
      tokensEstimated: estimated,
    };
  }

  // РЕЖИМ 3 (S8/§29): граф ОДНОГО прогона Саммари — конкретная вертикальная
  // последовательность этапов filter → L1 → L2 → formatting (подтверждённый
  // порядок пайплайна, D6). Агрегат периода сюда не подмешивается (fromSummary).
  function fromExecution(payload) {
    var p = payload || {};
    var rawNodes = Array.isArray(p.nodes) ? p.nodes : [];
    var runId = (p.run_id != null && p.run_id !== '') ? String(p.run_id) : null;
    var nodes = [];
    for (var i = 0; i < rawNodes.length; i++) {
      var node = normalizeExecutionNode(rawNodes[i], runId, i);
      if (node) nodes.push(node);
    }
    var allowed = {};
    nodes.forEach(function (n) { allowed[n.id] = true; });
    var edges = [];
    (Array.isArray(p.edges) ? p.edges : []).forEach(function (e) {
      if (!e || !allowed[e.from] || !allowed[e.to]) return;
      edges.push({ from: String(e.from), to: String(e.to) });
    });
    var metrics = (p.metrics && typeof p.metrics === 'object') ? p.metrics : null;
    return {
      runId: runId,
      startedAt: strOrNull(p.started_at),
      nodes: nodes,
      edges: edges,
      main: nodes,                 // вертикальная последовательность (§29)
      hasBranch: false,            // ветвление не достраивается (§25/D6)
      empty: nodes.length === 0,
      totals: executionTotals(nodes, metrics),
      metrics: metrics,
      publicationStatus: (p.publication_status != null)
        ? String(p.publication_status) : 'gated',
    };
  }

  // Поиск по строке (§27): подстрока без регистра по РЕАЛЬНЫМ полям узла.
  // Ничего не выдумываем: ищем только то, что реально присутствует в модели.
  function searchHaystack(node) {
    var m = node.metadata || {};
    return [node.stageLabel, node.stageKey, node.kindLabel, node.model,
            node.moduleId, m.toolName, m.source]
      .map(function (v) { return v == null ? '' : String(v); })
      .join(' ').toLowerCase();
  }

  // Фильтры витрины §27 (только «Аналитика»). Работают на нормализованной
  // модели; пустой фильтр = без ограничения. Неизвестный статус не скрывает
  // узлы (все они и так 'unknown' — сравниваем строкой). `query` — строка
  // поиска (подстрока без регистра по label/этапу/module/model/tool).
  function matches(node, f, q) {
    f = f || {};
    if (f.module && node.moduleId !== f.module) return false;
    if (f.model && node.model !== f.model) return false;
    if (f.stage && node.stageKey !== f.stage) return false;
    if (f.status && node.status !== f.status) return false;
    if (q && searchHaystack(node).indexOf(q) === -1) return false;
    return true;
  }

  function filter(nodes, f) {
    var list = nodes || [];
    if (!f) return list.slice();
    var q = (f.query == null ? '' : String(f.query)).trim().toLowerCase();
    return list.filter(function (n) { return matches(n, f, q); });
  }

  // Детали узла: только реально доступные поля; отсутствующие -> null
  // (UI рендерит «Нет данных»). Провайдер/длительность/финиш не выдумываем.
  function detail(node) {
    if (!node) return null;
    return {
      id: node.id,
      runId: node.runId,
      stageKey: node.stageKey,
      stageLabel: node.stageLabel,
      kind: node.kind,
      kindLabel: node.kindLabel,
      moduleId: node.moduleId,
      model: node.model,
      provider: node.provider,
      status: node.status,
      inputTokens: node.inputTokens,
      outputTokens: node.outputTokens,
      cost: node.cost,
      costCurrency: node.costCurrency,
      durationMs: node.durationMs,
      startedAt: node.startedAt,
      finishedAt: node.finishedAt,
      metrics: node.metrics,
      metadata: node.metadata,
    };
  }

  return {
    KIND_ENUM: KIND_ENUM,
    KIND_LABELS: KIND_LABELS,
    STEP_LABEL: STEP_LABEL,
    kindOf: kindOf,
    stageLabelOf: stageLabelOf,
    fromTrace: fromTrace,
    fromSummary: fromSummary,
    fromExecution: fromExecution,
    filter: filter,
    detail: detail,
  };
});
