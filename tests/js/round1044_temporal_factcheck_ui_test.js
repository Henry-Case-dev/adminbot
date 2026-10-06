'use strict';
/* MCA-20 round 10.44 (ADR-1028-20 D14, T-5143) — поведенческий тест виджета
 * «Временной фактчек» в СУЩЕСТВУЮЩЕЙ «Аналитике» (#/oversight).
 *
 * Проверяет:
 *   1) loadTemporalRuns() запрашивает /api/factcheck/temporal/runs с limit
 *      и читает аддитивное `runs` (компакт: без claim-текста — R17);
 *   2) форматтеры enum-ов дают человеческие подписи и честный unknown
 *      (неизвестное значение → «неизвестно», не выдуманный статус);
 *   3) детали: openTemporalDetail тянет /api/factcheck/temporal/runs/{id};
 *   4) структура index.html содержит блок temporal-factcheck в oversight
 *      и НЕ добавляет новый пункт навигации (виджет — внутри «Аналитики»).
 *
 * Запуск: node tests/js/round1044_temporal_factcheck_ui_test.js
 *         → MCA20-TEMPORAL-UI-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

let captured = null;
let apiCalls = [];
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
assert.ok(captured, 'app.js должен создавать Vue-приложение');
const methods = captured.methods || {};
assert.ok(methods.loadTemporalRuns, 'loadTemporalRuns есть');
assert.ok(methods.openTemporalDetail, 'openTemporalDetail есть');
assert.ok(methods.temporalFactualLabel, 'форматтеры enum-ов есть');

// ── 1) loadTemporalRuns: URL + чтение `runs` ────────────────────────────────
const vm = Object.create(methods);
vm.isGlobalAdmin = true;
vm.temporalRuns = null;
vm.temporalRunsBusy = false;
vm.temporalRunsAt = 0;
vm.temporalDetail = null;
vm.temporalDetailBusy = false;
vm.api = async function (path) {
  apiCalls.push(path);
  if (path.startsWith('/api/factcheck/temporal/runs?')) {
    return { runs: [{
      run_id: 'tfr-1', created_at: 1760000000, chat_id: 42,
      assessment_mode: 'contextual', factual_verdict: 'old_but_valid',
      temporal_status: 'old_but_valid', date_source: 'telegram_origin',
      cache_hit: false, fallback_used: false,
      // R17: компакт — claim_text в списке НЕ приходит (список честный).
    }] };
  }
  if (path.startsWith('/api/factcheck/temporal/runs/tfr-1')) {
    return { run: { run_id: 'tfr-1', claim_text: 'в 2019 году всё было',
                    date_uncertainty: { conflicts: [{ kind: 'x' }] },
                    stage_trace: [{ stage: 'verdict', outcome: 'success' }] },
             evidence: [{ url: 'https://example.com', relation: 'supports' }] };
  }
  return {};
};

(async function main() {
  await vm.loadTemporalRuns(true);
  await new Promise(setImmediate);
  assert.ok(apiCalls.some(function (p) {
    return p === '/api/factcheck/temporal/runs?limit=20';
  }), 'loadTemporalRuns должен звать /api/factcheck/temporal/runs?limit=20');
  assert.strictEqual(vm.temporalRuns.length, 1);

  // ── 2) форматтеры: человеческие подписи + честный unknown ────────────────
  assert.strictEqual(vm.temporalFactualLabel('supported'), 'подтверждено');
  assert.strictEqual(vm.temporalFactualLabel('insufficient_evidence'),
                     'недостаточно данных');
  assert.strictEqual(vm.temporalFactualLabel('weird_value'), 'неизвестно');
  assert.strictEqual(vm.temporalStatusLabel('misleading_reuse'),
                     'подают как новое');
  assert.strictEqual(vm.temporalStatusLabel('totally_unknown'), 'неизвестно');
  assert.strictEqual(vm.temporalDateSourceLabel('telegram_origin'),
                     'дата оригинала (Telegram)');
  assert.strictEqual(vm.temporalDateSourceLabel('nope'), 'неизвестно');
  assert.strictEqual(vm.temporalModeLabel('knowable_at_time'),
                     'знание на момент');

  // ── 3) детали по run_id ──────────────────────────────────────────────────
  await vm.openTemporalDetail('tfr-1');
  await new Promise(setImmediate);
  assert.ok(apiCalls.some(function (p) {
    return p === '/api/factcheck/temporal/runs/tfr-1';
  }), 'openTemporalDetail должен звать /runs/{id}');
  assert.strictEqual(vm.temporalDetail.run.claim_text,
                     'в 2019 году всё было');
  assert.strictEqual(vm.temporalDateConflict(vm.temporalDetail.run), true);

  // ── 4) структура: виджет в oversight, навигация не разрослась ────────────
  const html = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf-8');
  assert.ok(html.includes('id="temporal-factcheck-block"'),
            'index.html: блок temporal-factcheck отсутствует');
  const oversightIdx = html.indexOf('activeTab === \'oversight\'');
  const widgetIdx = html.indexOf('temporal-factcheck-block');
  assert.ok(oversightIdx > 0 && widgetIdx > oversightIdx,
            'виджет должен жить внутри oversight-шаблона');
  assert.ok(!html.includes('#/factcheck-temporal'),
            'новый маршрут/раздел для виджета не нужен');
  const nav = vm.NAVIGATION || vm.NAV || [];
  const navIds = (Array.isArray(nav) ? nav : []).map(function (n) {
    return n && n.id;
  });
  assert.ok(!navIds.includes('factcheck_temporal'),
            'навигация не должна разрастись из-за виджета');

  console.log('MCA20-TEMPORAL-UI-OK');
  process.exit(0);
})().catch(function (err) {
  console.error('FAIL:', err && err.message);
  process.exit(1);
});
