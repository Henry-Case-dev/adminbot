'use strict';
/* mca-17a round1027 (carry-over §94.5/SC-13/SC-14) — поведенческий тест
 * аддитивных фильтров связанных событий и компактного индикатора инцидентов
 * в СУЩЕСТВУЮЩЕМ viewer. Новых панелей/маршрутов/endpoint нет.
 *
 * Проверяет:
 *   1) `loadRelatedEvents()` формирует существующий `/api/status/logs` с
 *      фильтрами trace/chat/component/reason и читает аддитивное `events`;
 *   2) пустой фильтр → пустой список без запроса (empty state);
 *   3) `mcaIncidentLabel`/`incidentBadge` отражают unknown (не выдуманный 0);
 *   4) структура index.html содержит блоки mca-metrics/mca-log-filters.
 *
 * Запуск: node tests/js/round1027_mca17a_observability_ui_test.js
 *         → MCA17A-OBSERVABILITY-UI-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  matchMedia: function () { return { matches: false, addEventListener() {} }; },
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {}, remove() {},
      getContext() { return null; },
    };
  },
  body: { appendChild() {}, removeChild() {} },
  execCommand() { return true; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
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
const methods = captured.methods || {};

async function main() {
  assert.ok(methods.loadRelatedEvents, '§94.5: loadRelatedEvents есть');
  assert.ok(methods.clearMcaLogFilter, '§94.5: clearMcaLogFilter есть');
  assert.ok(methods.mcaIncidentLabel, '§27.6: mcaIncidentLabel есть');
  assert.ok(methods.incidentBadge, '§27.6: incidentBadge есть');

  // 1) Фильтр trace отправляет ОДИН запрос на существующий endpoint.
  const calls = [];
  const ctx = {
    mcaLogFilter: { trace_id: 'run_ab', chat_id: '', component: 'summary',
                    reason_code: 'provider_unavailable' },
    mcaEvents: [],
    api: function (url) {
      calls.push(url);
      return Promise.resolve({ count: 0, logs: [], events: [
        { level: 'ERROR', event_name: 'LLM_CALL', stage: 'llm',
          status: 'failed', pipeline_run_id: 'run_ab' }] });
    },
  };
  await methods.loadRelatedEvents.call(ctx);
  assert.strictEqual(calls.length, 1, '§94.5: один запрос');
  assert.ok(calls[0].indexOf('/api/status/logs') >= 0,
    '§94.5: REUSE существующего endpoint');
  assert.ok(calls[0].indexOf('trace_id=run_ab') >= 0,
    '§94.5: фильтр trace_id');
  assert.ok(calls[0].indexOf('reason_code=provider_unavailable') >= 0,
    '§94.5: фильтр reason_code');
  assert.strictEqual(ctx.mcaEvents.length, 1, '§94.5: связанные события из events');

  // 2) Пустой фильтр → без запроса, пустой список (empty state).
  const calls2 = [];
  const ctx2 = {
    mcaLogFilter: { trace_id: '', chat_id: '', component: '', reason_code: '' },
    mcaEvents: [{ x: 1 }],
    api: function (url) { calls2.push(url); return Promise.resolve({}); },
  };
  await methods.loadRelatedEvents.call(ctx2);
  assert.strictEqual(calls2.length, 0, '§94.5: пустой фильтр — без запроса');
  assert.deepStrictEqual(ctx2.mcaEvents, [], '§94.5: пустой — empty state');

  // 3) Сброс фильтра.
  const ctx3 = {
    mcaLogFilter: { trace_id: 'x', chat_id: '1', component: 'c',
                    reason_code: 'r' },
    mcaEvents: [{ x: 1 }],
  };
  methods.clearMcaLogFilter.call(ctx3);
  assert.strictEqual(ctx3.mcaLogFilter.trace_id, '', '§94.5: сброс trace');
  assert.deepStrictEqual(ctx3.mcaEvents, [], '§94.5: сброс events');

  // 4) Инциденты: unknown ≠ 0/«здоровье».
  assert.strictEqual(methods.mcaIncidentLabel.call({}, null), 'неизвестно',
    '§27.6: нет данных → «неизвестно»');
  assert.strictEqual(
    methods.mcaIncidentLabel.call({}, { available: false, active: null }),
    'неизвестно', '§27.6: unavailable → «неизвестно»');
  assert.strictEqual(
    methods.mcaIncidentLabel.call({}, { available: true, active: 3,
                                        unacknowledged: 2 }),
    '3 (2 не подтв.)', '§27.6: acknowledged ≠ resolved виден');
  assert.ok(methods.incidentBadge.call({}, { available: true, active: 0 })
              .indexOf('ok') >= 0, '§27.6: 0 активных → ok');
  assert.ok(methods.incidentBadge.call({}, { available: false })
              .indexOf('muted') >= 0, '§27.6: unavailable → muted');

  // 4b) F3/SC-13/§27.5: метрики недоступны → честный unknown/muted, НЕ зелёный.
  assert.ok(methods.mcaMetricsBadge, 'F3: mcaMetricsBadge есть');
  assert.ok(methods.mcaDegradedLabel, 'F3: mcaDegradedLabel есть');
  assert.ok(methods.mcaErrorsLabel, 'F3: mcaErrorsLabel есть');
  const mctx = { mcaMetricsAvailable: methods.mcaMetricsAvailable };
  assert.strictEqual(
    methods.mcaMetricsBadge.call(mctx, { available: false, degraded_share: null }),
    'badge-muted', 'F3: available=false → muted (не зелёный)');
  assert.strictEqual(
    methods.mcaDegradedLabel.call(mctx,
                                  { available: false, degraded_share: null }),
    'degraded: неизвестно', 'F3: available=false → «неизвестно»');
  assert.strictEqual(
    methods.mcaMetricsBadge.call(mctx, { available: true, degraded_share: null }),
    'badge-muted', 'F3: degraded_share=null → muted (недостаточно данных)');
  assert.strictEqual(
    methods.mcaMetricsBadge.call(
      mctx, { available: true, degraded_share: 0.0, telemetry_degraded: false }),
    'badge-ok', 'F3: реальный 0 → ok');
  assert.strictEqual(
    methods.mcaMetricsBadge.call(
      mctx, { available: true, degraded_share: 0.1, telemetry_degraded: true }),
    'badge-warn', 'F3: деградация → warn');
  assert.strictEqual(
    methods.mcaDegradedLabel.call(mctx,
                                  { available: true, degraded_share: 0.12 }),
    'degraded 0.12', 'F3: реальное значение отображается');
  assert.strictEqual(
    methods.mcaErrorsLabel.call({}, { available: false, errors_total: null }),
    'неизвестно', 'F3: errors_total=null → «неизвестно»');
  assert.strictEqual(
    methods.mcaErrorsLabel.call({}, { available: true, errors_total: 3 }), 3,
    'F3: реальное число ошибок');

  // 4c) F5/SC-16: refresh индикатора инцидентов через read-only
  // incident_changes с cursor (≤10с), паритет при enabled=false.
  assert.ok(methods.pollIncidentChanges && methods.startIncidentPolling
            && methods.stopIncidentPolling, 'F5: polling-методы инцидентов');
  const pcalls = [];
  const pctx = {
    incidentPushBusy: false, incidentCursor: 0, incidentInterval: 10,
    incidentPushError: '', oversightData: { mca_metrics: { incidents: {} } },
    api: function (url) {
      pcalls.push(url);
      return Promise.resolve({
        enabled: true, cursor: 42, changes: [{ incident_id: 'inc_1' }],
        indicator: { available: true, active: 2, unacknowledged: 1 },
        push_interval_seconds: 10,
      });
    },
  };
  await methods.pollIncidentChanges.call(pctx);
  assert.strictEqual(pcalls.length, 1, 'F5: один read-only запрос');
  assert.ok(pcalls[0].indexOf('/api/oversight/incidents/changes') >= 0,
    'F5: read-only endpoint incident_changes');
  assert.ok(pcalls[0].indexOf('since_ts=0') >= 0, 'F5: cursor-параметр');
  assert.strictEqual(pctx.incidentCursor, 42, 'F5: cursor обновлён');
  assert.strictEqual(pctx.oversightData.mca_metrics.incidents.active, 2,
    'F5: существующий индикатор обновлён');
  // reconnect: следующий запрос — с нового курсора
  await methods.pollIncidentChanges.call(pctx);
  assert.ok(pcalls[1].indexOf('since_ts=42') >= 0, 'F5: reconnect по cursor');
  // OFF-паритет: enabled=false → polling останавливается, обновлений нет
  let stopped = false;
  const pctx2 = {
    incidentPushBusy: false, incidentCursor: 7, incidentInterval: 10,
    incidentPushError: '',
    stopIncidentPolling: function () { stopped = true; },
    api: function () {
      return Promise.resolve({ enabled: false, cursor: 7, changes: [],
                               indicator: { available: false } });
    },
  };
  await methods.pollIncidentChanges.call(pctx2);
  assert.strictEqual(stopped, true, 'F5: OFF → polling остановлен');
  assert.strictEqual(pctx2.incidentCursor, 7, 'F5: OFF → без ложного cursor');

  // 5) Статическая структура index.html (REUSE viewer, без новых маршрутов).
  const html = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  assert.ok(html.indexOf('id="mca-metrics-block"') >= 0,
    '§94.5/SC-13: блок mca_metrics на существующей витрине');
  assert.ok(html.indexOf('id="mca-log-filters"') >= 0,
    '§94.5/SC-14: аддитивные фильтры в существующем log viewer');
  assert.ok(html.indexOf('id="mca-related-events"') >= 0,
    '§94.5/SC-14: связанные события trace');

  console.log('MCA17A-OBSERVABILITY-UI-OK');
}

main().catch(function (err) {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
