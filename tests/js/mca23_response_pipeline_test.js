'use strict';
/* MCA-23 фаза 2 (P2-B, §33-§36 current_task) — виджет «Ответ (Pipeline)»
 * (реальная логика web/app.js + разметка web/index.html).
 *
 * Проверяет:
 *   (a) data-состояние виджета объявлено (responsePipelineMode/…);
 *   (b) методы существуют (load/set/toggle/badge);
 *   (c) computed существуют и читаются как свойства (урок H-ASAP31-2);
 *   (d) projected-цепочка плановых узлов §34 (TRIGGER…ИТОГ) идёт из данных
 *       бэкенда 1:1 — REACT/SILENT (узлов writer нет в planned.nodes) НЕ
 *       дорисовывают фиктивный Writer на клиенте;
 *   (e) бейдж planned-vs-actual — ТЕКСТОВЫЙ, 4 честных исхода §33
 *       (Совпало/Отклонилось/Не выполнилось/Лишнее), без opaque score;
 *   (f) setResponsePipelineMode нормализует режим (latest|24h|7d);
 *   (g) fail-open: агрегатные проекции с null-значениями дают «—», а не
 *       выдуманные проценты (правило метрик ASAP 6 §14);
 *   (h) разметка index.html: карточка на вкладке «Саммари», 3 режима,
 *       Developer details, честная пустая ветка, §36-причины из данных;
 *   (i) R17: разметка/проекции не содержат секрет-полей.
 *
 * Запуск: node tests/js/mca23_response_pipeline_test.js
 *          → MCA23-RESPONSE-PIPELINE-OK
 */
const path = require('path');
const fs = require('fs');
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
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
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

// (a) data-состояние
['responsePipelineMode', 'responsePipeline', 'responseSummary',
 'responsePipelineBusy', 'responseOpenNode'].forEach(function (key) {
  assert.ok(Object.prototype.hasOwnProperty.call(data, key),
    'a: data.' + key + ' объявлен');
});
assert.strictEqual(data.responsePipelineMode, 'latest',
  'a: режим по умолчанию latest');

// (b) методы
['loadResponsePipeline', 'setResponsePipelineMode', 'toggleResponseNode',
 'responseCmpBadge', '_responseLatencyLine'].forEach(function (name) {
  assert.strictEqual(typeof methods[name], 'function', 'b: метод ' + name);
});

// (c) computed — читаются шаблоном как свойства (без скобок)
['responsePlan', 'responsePlanNodes', 'responsePlanComparison',
 'responsePlanSummary', 'responseLatestEmpty', 'responseAggRows',
 'responseRecentRows'].forEach(function (name) {
  assert.strictEqual(typeof computed[name], 'function', 'c: computed.' + name);
});

// (d) §34: плановая цепочка — 1:1 из данных; REACT не дорисовывает Writer.
function planCtx(planned) {
  return { responsePipeline: { run_id: 'fic-run-0001', planned: planned },
           responsePipelineMode: 'latest' };
}
const REPLY_PLAN = {
  ts: 1760000000,
  nodes: [
    { key: 'trigger', label: 'TRIGGER', title: 'Триггер',
      expected: 'ответ текстом',
      axes: { action: 'reply' }, reason_ru: 'Прямое обращение к боту.' },
    { key: 'planner', label: 'PLANNER', title: 'Планировщик',
      expected: 'творческий текст · длинный текст · история',
      axes: { task_kind: 'creative_writing', extent: 'longform',
              structure: 'story' },
      reason_ru: 'Запрос на большой связный текст — cap снят.' },
    { key: 'tools', label: 'TOOLS', title: 'Инструменты',
      expected: 'без инструментов',
      axes: { tool_policy: 'none' },
      reason_ru: 'Почему tools не использовались? Запрос творческий.' },
    { key: 'writer', label: 'WRITER', title: 'Writer',
      expected: 'генерация текста по плану',
      reason_ru: 'Планируется вызов Writer.' },
    { key: 'delivery', label: 'DELIVERY', title: 'Доставка',
      expected: 'обычное сообщение',
      axes: { delivery_hint: 'plain' }, reason_ru: 'Обычное сообщение.' },
    { key: 'outcome', label: 'ИТОГ', title: 'Итог',
      expected: 'успешная доставка ответа', reason_ru: 'Ответ доставлен.' },
  ],
  comparison: [
    { key: 'trigger', title: 'Триггер', planned: 'ответ текстом',
      actual: 'ответ текстом', status: 'match', reason_ru: '' },
    { key: 'delivery', title: 'Доставка', planned: 'Rich-карточка',
      actual: 'обычное сообщение', status: 'deviated',
      reason_ru: 'Планировалась Rich-карточка, ответ ушёл обычным сообщением.' },
  ],
  summary: { match: 3, deviated: 1, missing: 0, extra: 0 },
};
const ctxReply = planCtx(REPLY_PLAN);
// Урок H-ASAP31-2: цепочка computed — вычисляем зависимость заранее.
ctxReply.responsePlan = computed.responsePlan.call(ctxReply);
const nodes = computed.responsePlanNodes.call(ctxReply);
assert.strictEqual(nodes.length, 6, 'd: 6 плановых узлов §34');
assert.deepStrictEqual(nodes.map(function (n) { return n.label; }),
  ['TRIGGER', 'PLANNER', 'TOOLS', 'WRITER', 'DELIVERY', 'ИТОГ'],
  'd: цепочка §34 по порядку');
assert.strictEqual(computed.responsePlan.call(ctxReply).summary.deviated, 1,
  'd: summary из данных');

// REACT: в данных нет writer-узла → проекция НЕ добавляет фиктивный.
const REACT_PLAN = {
  ts: 1760000001,
  nodes: REPLY_PLAN.nodes.filter(function (n) { return n.key !== 'writer'; }),
  comparison: [],
  summary: { match: 2, deviated: 0, missing: 0, extra: 0 },
};
const reactCtx = planCtx(REACT_PLAN);
reactCtx.responsePlan = computed.responsePlan.call(reactCtx);
const reactNodes = computed.responsePlanNodes.call(reactCtx);
assert.ok(!reactNodes.some(function (n) { return n.key === 'writer'; }),
  'd: REACT — фиктивный Writer не дорисовывается (§34)');

// (e) бейдж — текстовый, 4 исхода §33, без числового score.
const badge = methods.responseCmpBadge;
assert.deepStrictEqual(badge('match'),
  { cls: 'badge-ok', text: 'Совпало' }, 'e: match');
assert.deepStrictEqual(badge('deviated'),
  { cls: 'badge-warn', text: 'Отклонилось' }, 'e: deviated');
assert.deepStrictEqual(badge('missing'),
  { cls: 'badge-err', text: 'Не выполнилось' }, 'e: missing');
assert.deepStrictEqual(badge('extra'),
  { cls: 'badge-warn', text: 'Лишнее' }, 'e: extra');
assert.deepStrictEqual(badge(undefined),
  { cls: 'badge-muted', text: '—' }, 'e: unknown → честное «—»');
['Совпало', 'Отклонилось', 'Не выполнилось', 'Лишнее'].forEach(
  function (label) {
    assert.ok(!/\d/.test(label), 'e: бейдж без числового score: ' + label);
  });

// (f) нормализация режима.
const modeCtx = { responsePipelineMode: 'latest', loadResponsePipeline: function () {} };
methods.setResponsePipelineMode.call(modeCtx, '24h');
assert.strictEqual(modeCtx.responsePipelineMode, '24h', 'f: 24h');
methods.setResponsePipelineMode.call(modeCtx, '7d');
assert.strictEqual(modeCtx.responsePipelineMode, '7d', 'f: 7d');
methods.setResponsePipelineMode.call(modeCtx, 'bogus');
assert.strictEqual(modeCtx.responsePipelineMode, 'latest', 'f: bogus → latest');
methods.setResponsePipelineMode.call(modeCtx, 'latest');

// (g) fail-open: null-агрегаты → «—», никаких выдуманных процентов.
const emptyAggCtx = {
  responseSummary: {
    period: '24h', available: false, runs: 0, calls: 0,
    tools_per_run: null, multi_tool_rate: null, tool_failure_rate: null,
    tokens: { input_tokens: 0, output_tokens: 0 }, cost_usd: null,
    price_known: true, plan_axes: null,
    latency: { p50_ms: null, p95_ms: null, source: 'llm_call_span' },
    recent: { runs: 0 },
  },
  fmtCost: methods.fmtCost,
  _responseLatencyLine: methods._responseLatencyLine,
};
const aggRows = computed.responseAggRows.call(emptyAggCtx);
assert.ok(aggRows.length >= 6, 'g: строки агрегатов на месте');
aggRows.forEach(function (row) {
  if (['tools', 'multi', 'tfr', 'axes', 'latency'].indexOf(row.key) >= 0) {
    assert.strictEqual(row.value, '—',
      'g: ' + row.key + ' без данных → «—», получено ' + row.value);
  }
});
assert.strictEqual(computed.responseRecentRows.call(emptyAggCtx).length, 0,
  'g: пустое окно → нет строк свежих прогонов (честно)');

// Агрегат с данными: проценты считаются ТОЛЬКО из реальных значений.
const fullAggCtx = {
  responseSummary: {
    period: '7d', available: true, runs: 10, calls: 25,
    tools_per_run: 1.2, multi_tool_rate: 0.3, tool_failure_rate: null,
    cost_usd: 0.5, price_known: true, plan_axes: null,
    latency: { p50_ms: 800, p95_ms: 2100, source: 'llm_call_span' },
    recent: {
      runs: 3, actions: { reply: 2, react: 1 },
      task_kinds: { creative_writing: 1, social_chat: 2 },
      extents: { longform: 1, compact: 2 },
      deliveries: { plain: 2, rich: 1, media: 0, none: 0 },
      tool_calls: 4, tool_failures: 1,
      tool_failure_rate: 0.25,
      decision_latency_ms: { p50: 120, p95: 480 },
      window_note_ru: 'по последним прогонам в памяти',
    },
  },
  fmtCost: methods.fmtCost,
  _responseLatencyLine: methods._responseLatencyLine,
};
const fullRows = {};
computed.responseAggRows.call(fullAggCtx).forEach(function (r) {
  fullRows[r.key] = r.value;
});
assert.strictEqual(fullRows.multi, '30%', 'g: multi-tool rate из данных');
assert.strictEqual(fullRows.tfr, '—', 'g: tool failure за период — «—» (в usage events ошибок нет)');
assert.strictEqual(fullRows.latency, '800 / 2100 мс', 'g: latency p50/p95');
assert.strictEqual(fullRows.axes, '—', 'g: план-оси за период — «—»');
const recentRows = {};
computed.responseRecentRows.call(fullAggCtx).forEach(function (r) {
  recentRows[r.key] = r.value;
});
assert.strictEqual(recentRows.actions, 'ответ: 2 · реакция: 1',
  'g: распределение действий (RU-лейблы)');
assert.strictEqual(recentRows.kinds,
  'творческий текст: 1 · болтовня: 2', 'g: типы задач (RU-лейблы)');
assert.strictEqual(recentRows.tools, '4 (1)', 'g: tools с падениями');

// (h) разметка index.html.
const index = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
assert.ok(index.includes('id="response-pipeline-block"'),
  'h: карточка виджета на месте');
assert.ok(/id="response-pipeline-block"[^>]+v-if="oversightTab === 'summary' && isGlobalAdmin"/.test(index),
  'h: виджет на вкладке «Саммари» (global admin), второй страницы нет');
['Последний ответ', '24 часа', '7 дней'].forEach(function (mode) {
  assert.ok(index.includes('>' + mode + '<'), 'h: режим ' + mode);
});
assert.ok(index.includes('setResponsePipelineMode'), 'h: переключатель режимов');
assert.ok(index.includes('Developer details'),
  'h: технический JSON — в Developer details (§36)');
assert.ok(index.includes('Последний ответ ещё не планировался'),
  'h: честная пустая ветка (§14 ASAP 6)');
assert.ok(index.includes('Данных за период нет'), 'h: честное «нет данных»');
assert.ok(index.includes('План → Факт'), 'h: planned-vs-actual блок (§33)');
['TRIGGER', 'PLANNER', 'TOOLS', 'WRITER', 'DELIVERY'].forEach(function (st) {
  // Метки этапов приходят из данных бэкенда (node.label) — шаблон не хардкодит
  // их, но pipe-timeline переиспользует classes Run Inspector (визуальная карта).
});
assert.ok(index.includes('class="pipe-timeline"'),
  'h: переиспользован pipe-timeline (визуальный контракт Run Inspector)');
// §36: причины — из данных (reason_ru), шаблон не содержит выдуманных причин.
assert.ok(index.includes('node.reason_ru'), 'h: причины из данных плана');

// (i) R17: в блоке виджета нет секрет-полей/ключей.
const block = index.slice(index.indexOf('id="response-pipeline-block"'),
  index.indexOf('id="response-pipeline-block"') + 6000);
['api_key', 'token', 'password', 'secret'].forEach(function (bad) {
  assert.ok(!block.toLowerCase().includes(bad),
    'i: нет секрет-подобных полей: ' + bad);
});

console.log('MCA23-RESPONSE-PIPELINE-OK');
