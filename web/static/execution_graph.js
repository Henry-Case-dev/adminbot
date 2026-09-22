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
  // Сырой `step` -> kind. `algorithm`/`format`/`publish` — зарезервированы
  // под Эпик 2 (сейчас таких `step` нет, значит и узлов нет — §24).
  var STEP_KIND = {
    single: 'llm', stage1: 'llm', stage2: 'llm', image: 'llm',
    tool: 'tool',
    algorithm: 'algorithm', format: 'format', publish: 'publish',
  };
  // ru-словарь этапов (§24): Слой 1/Слой 2/Один вызов/Изображение/Инструмент.
  var STEP_LABEL = {
    single: 'Один вызов', stage1: 'Слой 1', stage2: 'Слой 2',
    image: 'Изображение', tool: 'Инструмент',
    algorithm: 'Алгоритм', format: 'Форматирование', publish: 'Публикация',
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
    var byModule = (s.by_module || []).map(function (m) {
      return {
        module: strOrNull(m.module),
        cost: num(m.cost_usd),        // агрегат: цена известна по построению
        inputTokens: num(m.input_tokens),
        outputTokens: num(m.output_tokens),
        calls: num(m.calls) || 0,
      };
    });
    var series = (s.series || []).map(function (b) {
      return {
        bucket: strOrNull(b.bucket),
        cost: num(b.cost_usd),
        inputTokens: num(b.input_tokens),
        outputTokens: num(b.output_tokens),
        calls: num(b.calls) || 0,
      };
    });
    var totals = {
      inputTokens: num((s.totals || {}).input_tokens) || 0,
      outputTokens: num((s.totals || {}).output_tokens) || 0,
      cost: num((s.totals || {}).cost_usd),
      costCurrency: 'USD',
      priceKnown: true,
      calls: num((s.totals || {}).calls) || 0,
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
        costCurrency: 'USD',
        priceKnown: true,
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
    filter: filter,
    detail: detail,
  };
});
