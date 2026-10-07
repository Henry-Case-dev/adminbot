'use strict';
/* ASAP 5 (ADR-1028-25, D1/D6) — JS unit-тест Decision Trace + L1
 * трёхуровневой семантики в Run Inspector (реальная логика web/app.js +
 * разметка web/index.html).
 *
 * Проверяет:
 *  (1) computed pipelineDecisionTrace существует и читается как свойство;
 *  (a) D6: 5 секций трассы (L1 / Writer / Reviewer-итерации /
 *      Revision-итерации / Final policy) из существующих stage_events;
 *  (b) D5: честная RU-подпись final policy + reason;
 *  (c) D1: L1 degraded_map_fallback ≠ красный крест («Writer продолжил»),
 *      failed_terminal → «не выполнено» (совместимость со старым failed);
 *  (d) разметка index.html: карточка decision trace + отсутствие
 *      секретов/R17-мусора в блоке;
 *  (e) trace без данных → computed отдаёт null (не падает).
 *
 * Запуск: node tests/js/asap5_decision_trace_test.js
 *          → ASAP5-DECISION-TRACE-OK
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
const methods = captured.methods;
const computed = captured.computed;

function withView(run) {
  var ctx = { pipelineData: run ? { run } : null,
              pipelineSelectedRunId: '' };
  ctx.pctLabel = methods.pctLabel;
  ctx.fmtSec = methods.fmtSec;
  ctx.pipelineRunView = computed.pipelineRunView.call(ctx);
  ctx.pipelineBusy = false;
  ctx.pipelineMode = 'latest';
  return ctx;
}

// (1) computed существует — читается шаблоном как свойство.
assert.strictEqual(typeof computed.pipelineDecisionTrace, 'function',
  '1: computed pipelineDecisionTrace');

// Fixture — shape /api/analytics/pipeline/inspector (D6-трасса прогона с
// unusable-gate даунгрейдом, стагнацией и Legacy-финалом).
const RUN_TRACE = {
  run_id: 'run-asap5',
  decision_trace: {
    l1: { stage: 'l1', status: 'degraded_map_fallback',
          reason_code: 'semantic_map_unavailable',
          reason_ru: 'Карта тем недоступна — писатель читал оригинал напрямую.' },
    writer: { stage: 'l2', status: 'ok', reason_code: null },
    review_stage: { stage: 'l2_review', status: 'failed',
                    reason_code: 'l2_review_rejected' },
    review_iterations: [
      { stage: 'l2_reviewer', attempt: 1, status: 'needs_fixes',
        verdict: 'unusable', finding_codes: ['unsupported_number'],
        blocking_count: 1, paragraph_ids: [0],
        reason_code: 'l2_unusable_gate',
        reason_ru: 'Reviewer вернул unusable без достаточной доказательной базы — понижено до правок.' },
      { stage: 'l2_reviewer', attempt: 2, status: 'needs_fixes',
        verdict: 'needs_fixes', finding_codes: ['unsupported_number'],
        blocking_count: 1, paragraph_ids: [0] },
    ],
    revision_iterations: [
      { stage: 'revision', attempt: 1, status: 'ok',
        repair_target: 'patch', revision_result: 'ok' },
      { stage: 'revision', attempt: 1, status: 'stagnated',
        reason_code: 'l2_stagnation_fingerprint',
        reason_ru: 'Правки не исправляют те же hard-находки — цикл остановлен без прогресса.',
        revision_result: 'stagnated' },
    ],
    final_policy: { status: 'LEGACY_FALLBACK',
                    reason_code: 'l2_review_rejected' },
  },
  nodes: [],
};

const ctx = withView(RUN_TRACE);
const trace = computed.pipelineDecisionTrace.call(ctx);

// (a) 5 секций из существующих stage_events.
assert.ok(trace, 'a: trace построен');
assert.strictEqual(trace.l1.status, 'degraded_map_fallback');
assert.ok(trace.writer && trace.writer.status === 'ok', 'a: writer-секция');
assert.strictEqual(trace.reviewRows.length, 2, 'a: reviewer-итерации');
assert.strictEqual(trace.reviewRows[0].codes, 'unsupported_number');
assert.strictEqual(trace.reviewRows[0].blocking, 1);
assert.strictEqual(trace.reviewRows[0].reason_code, 'l2_unusable_gate',
  'a: unusable-gate виден в трассе (D3)');
assert.strictEqual(trace.revisionRows.length, 2, 'a: revision-итерации');
assert.strictEqual(trace.revisionRows[1].reason_code,
  'l2_stagnation_fingerprint', 'a: stagnation fingerprint виден (D4)');
assert.ok(!/\{\s*\{/.test(JSON.stringify(trace)), 'a: без vue-мусора');

// (b) честная RU-подпись final policy.
assert.strictEqual(trace.policy.status, 'LEGACY_FALLBACK');
assert.ok(trace.policy.ru.indexOf('Legacy') >= 0
  || trace.policy.ru.indexOf('резервн') >= 0, 'b: честный RU-итог');

// (e) без данных — null (не падает).
const ctxEmpty = withView({ run_id: 'x', nodes: [] });
assert.strictEqual(computed.pipelineDecisionTrace.call(ctxEmpty), null,
  'e: нет данных → null');

// (c) D1: coverage-строки — трёхуровневая семантика L1.
const RUN_DEGRADED = {
  run_id: 'r-deg',
  coverage_breakdown: {
    source: { total: 874, considered: 874, percent: 100.0 },
    l1: { input_total: 874, input_mode: 'WHOLE_WINDOW',
          input_requests: 1, result: 'degraded_map_fallback',
          map_degraded: true },
    writer: { total: 874, percent: 100.0, result: 'ok' },
  },
  nodes: [],
};
const ctxD = withView(RUN_DEGRADED);
const covRows = computed.pipelineCoverageRows.call(ctxD);
const byKey = {};
covRows.forEach(function (r) { byKey[r.key] = r; });
assert.strictEqual(byKey.l1.state, 'warn',
  'c: L1 degraded — предупреждение, НЕ красный крест');
assert.ok(byKey.l1.value.indexOf('Writer продолжил от полного окна') >= 0,
  'c: явная пометка продолжения Writer\'а');
assert.ok(byKey.l1.value.indexOf('не выполнено') < 0,
  'c: degraded не подписан «не выполнено»');

// legacy-данные со старым result='failed' остаются честно «не выполнено».
const RUN_TERMINAL = {
  run_id: 'r-term',
  coverage_breakdown: {
    l1: { input_total: 10, input_mode: 'WHOLE_WINDOW',
          input_requests: 1, result: 'failed', map_degraded: false },
  },
  nodes: [],
};
const ctxT = withView(RUN_TERMINAL);
const covT = computed.pipelineCoverageRows.call(ctxT);
assert.strictEqual(covT[0].state, 'failed',
  'c: failed_terminal/failed — красный крест честно');
assert.ok(covT[0].value.indexOf('не выполнено') >= 0,
  'c: terminal — «не выполнено»');

// (d) разметка index.html: карточка + R17-гигиена блока.
const html = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf-8');
assert.ok(html.includes('id="pipeline-decision-trace"'),
  'd: карточка Decision Trace в разметке');
assert.ok(html.includes('Решение по прогону (Decision Trace)'),
  'd: подпись карточки');
assert.ok(html.includes('pipelineDecisionTrace.reviewRows'),
  'd: секция Reviewer-итераций рендерится');
assert.ok(html.includes('pipelineDecisionTrace.policy'),
  'd: final policy рендерится');
const start = html.indexOf('id="pipeline-decision-trace"');
const end = html.indexOf('Developer details', start);
assert.ok(start > 0 && end > start, 'd: блок ограничен');
const block = html.slice(start, end);
['api_key', 'apiKey', 'secret', 'token', 'password'].forEach(function (bad) {
  assert.ok(!block.toLowerCase().includes(bad),
    'd: R17 — нет ключей/секретов в блоке трассы');
});

console.log('ASAP5-DECISION-TRACE-OK');
