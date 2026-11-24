'use strict';
/* QRNG UI-07 — compact adaptive provider block.
 *
 * Проверяет реальные методы web/app.js:
 *   (a) три провайдера, фактическое состояние, остаток, последнее получение
 *       (или успешная проверка), последняя причина переключения (код + подпись);
 *   (b) IBM до P5B — adapter_not_implemented, без выдуманных чисел;
 *   (c) нет данных — честное «нет данных», не 0/зелёный;
 *   (d) причина переключения не приписывается провайдеру по draw-журналу:
 *       provider там — фактический источник draw, а не виновник переключения;
 *   (e) компактный summary не содержит секретов; ключи/диагностика находятся
 *       в свёрнутом details, по умолчанию закрытом.
 *
 * Запуск: node tests/js/qrng_ui07_provider_block_test.js -> QRNG-UI07-OK
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
global.window = { location: { hash: '' }, addEventListener() {},
                 Telegram: null, confirm: function () { return true; } };
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = { getItem() { return null; }, setItem() {},
                          removeItem() {} };
global.localStorage = { getItem() { return null; }, setItem() {},
                        removeItem() {} };
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
require(path.join(ROOT, 'web', 'app.js'));

assert(captured, 'Vue.createApp не вызван');
const methods = captured.methods || {};
const computed = captured.computed || {};

function providers(overrides) {
  const base = [
    { id: 'ibm_quantum', configured: false, state: 'provider_unconfigured',
      reserve: 0, consumable: false, quarantined: 0 },
    { id: 'anu', configured: true, state: 'active',
      reserve: 5, consumable: true, quarantined: 0 },
    { id: 'lfdr', configured: true, state: 'active',
      reserve: 7, consumable: true, quarantined: 0,
      last_success_at: 1700000000, last_failure_at: null,
      last_error: null, breaker: { open: false } },
  ];
  return base.map(function (p) {
    return Object.assign({}, p, (overrides || {})[p.id] || {});
  });
}

function status(overrides) {
  const base = {
    enabled: true, available: true, quantum_active: true,
    effective_source: 'quantum', effective_provider: 'anu',
    primary_provider: 'ibm_quantum', primary_setting_raw: 'ibm_quantum',
    primary_setting_state: 'set', resolved_primary: 'anu',
    fallback_enabled: true, fallback_order: ['anu', 'lfdr'],
    fallback_order_raw: null, fallback_order_state: 'absent',
    effective_order: ['ibm_quantum', 'anu', 'lfdr'],
    providers: providers(),
    provider_reserve: { ibm_quantum: 0, anu: 5, lfdr: 7 },
    provider_quarantined: { ibm_quantum: 0, anu: 0, lfdr: 0 },
    reserve_remaining: 12, reserve_quarantined: 0,
    buffer_max: 100, low_watermark: 10,
    last_batch: { provider_id: 'anu', provider: 'ANU Quantum Numbers',
                  created_at: 1700000200, length: 1024,
                  config_matches: true },
    draws: { quantum: 10, pseudorandom: 0 },
    recent_draws: [],
    recent_draws_scope: 'global',
    last_fallback_reason: null, last_fallback_at: null,
    blocker: null,
    anu_state: 'active', lfdr_state: 'active',
    key_present: true, key_fingerprint: 'test',
    prng_active: false, prng_setting: true,
    uses: { enabled: false }, plan: null,
  };
  return Object.assign(base, overrides || {});
}

function makeCtx(st) {
  const source = methods._randomSourceView.call({}, st);
  const activity = computed.randomActivityView.call({ randomSource: source });
  return Object.assign({}, methods, {
    randomActivityView: activity,
    randomCheck: null,
    fmtTs: function (v) { return 'T' + v; },
  });
}

function byId(rows, id) {
  return rows.filter(function (r) { return r.id === id; })[0];
}

function assertNoneData(row) {
  assert.strictEqual(row.lastSuccess.available, false, row.id + ': success');
  assert.strictEqual(row.lastSuccess.kind, 'none', row.id + ': success kind');
  assert.strictEqual(row.lastSwitch.code, null, row.id + ': switch');
}

// ── (a) три провайдера: state / reserve / last success / last switch ──────
{
  const ctx = makeCtx(status());
  const rows = methods.randomProviderSummaries.call(ctx);
  assert.deepStrictEqual(rows.map(function (r) { return r.id; }),
    ['ibm_quantum', 'anu', 'lfdr'], 'ровно три провайдера');

  const ibm = byId(rows, 'ibm_quantum');
  assert.strictEqual(ibm.stateKey, 'adapter_not_implemented');
  assert.strictEqual(ibm.stateLabel, 'адаптер не реализован');
  assert.strictEqual(ibm.reserveText, 'нет данных',
    'IBM резерв не выдумывается');
  assert.strictEqual(ibm.consumableText, 'адаптер не реализован');
  assert.strictEqual(ibm.lastSuccess.available, false);
  assert.strictEqual(ibm.lastSwitch.code, 'adapter_not_implemented');
  assert.strictEqual(ibm.lastSwitch.label, 'адаптер не реализован');
  assert.strictEqual(ibm.adapterNotImplemented, true);

  const anu = byId(rows, 'anu');
  assert.strictEqual(anu.stateLabel, 'проверено');
  assert.strictEqual(anu.reserveText, '5');
  assert.strictEqual(anu.consumableText, 'расходуется');
  assert.strictEqual(anu.lastSuccess.available, true);
  assert.strictEqual(anu.lastSuccess.kind, 'batch');
  assert.strictEqual(anu.lastSuccess.sourceLabel, 'ANU Quantum Numbers');
  assert.strictEqual(anu.lastSuccess.timeLabel, 'T1700000200');
  assert.strictEqual(anu.lastSuccess.length, 1024);
  assert.strictEqual(anu.lastSwitch.code, null,
    'нет last_fallback_reason — нет придуманной причины переключения');

  const lfdr = byId(rows, 'lfdr');
  assert.strictEqual(lfdr.stateLabel, 'проверено');
  assert.strictEqual(lfdr.reserveText, '7');
  assert.strictEqual(lfdr.lastSuccess.available, true);
  assert.strictEqual(lfdr.lastSuccess.kind, 'check',
    'last_success_at — успешная проверка/fetch, а не выдуманный batch');
  assert.strictEqual(lfdr.lastSuccess.timeLabel, 'T1700000000');
  assert.strictEqual(lfdr.lastSwitch.code, null);

  const globalSwitch = methods.randomLastSwitchView.call(ctx);
  assert.strictEqual(globalSwitch.code, null);
  assert.strictEqual(globalSwitch.label, 'нет данных');
}

// ── (b) last_batch управляет последним получением; draw-журнал — нет ──────
{
  const ctx = makeCtx(status({
    last_batch: { provider_id: 'lfdr', provider: 'LfDR QRNG',
                  created_at: 1700000400, length: 512,
                  config_matches: false },
    // Нелепая для реального backend строка: provider=ANU + fallback_reason.
    // UI-07 не имеет права приписывать причину ANU по draw-журналу.
    recent_draws: [{ provider: 'anu', created_at: 1700000600,
                     fallback_reason: 'provider_unconfigured' }],
  }));
  const rows = methods.randomProviderSummaries.call(ctx);
  const anu = byId(rows, 'anu');
  const lfdr = byId(rows, 'lfdr');
  assert.strictEqual(anu.lastSuccess.available, false,
    'ANU больше не последний batch');
  assert.strictEqual(anu.lastSwitch.code, null,
    'draw-журнал не является per-provider причиной переключения');
  assert.strictEqual(lfdr.lastSuccess.available, true);
  assert.strictEqual(lfdr.lastSuccess.kind, 'batch');
  assert.strictEqual(lfdr.lastSuccess.length, 512);
  assert.strictEqual(lfdr.lastSuccess.configMatches, false,
    'другая конфигурация не скрывается');

  const noBatch = makeCtx(status({
    providers: providers({ lfdr: { last_success_at: null } }),
    last_batch: null,
    recent_draws: [{ provider: 'anu', created_at: 1700000600,
                     fallback_reason: null }],
  }));
  const noRows = methods.randomProviderSummaries.call(noBatch);
  assertNoneData(byId(noRows, 'anu'));
  assertNoneData(byId(noRows, 'lfdr'));
}

// ── (c) пер-provider причина: ANU state-scoped, LfDR health, IBM adapter ──
{
  const ctx = makeCtx(status({
    providers: providers({
      anu: { configured: true, state: 'degraded',
             reserve: 0, consumable: false },
      lfdr: { configured: true, state: 'degraded',
              reserve: 7, consumable: true,
              last_error: 'provider_unavailable',
              last_failure_at: 1700000100 },
    }),
    resolved_primary: 'anu',
    blocker: 'provider_unavailable',
    last_batch: null,
    last_fallback_reason: 'provider_unavailable',
    last_fallback_at: 1700000250,
  }));
  const rows = methods.randomProviderSummaries.call(ctx);
  const anu = byId(rows, 'anu');
  assert.strictEqual(anu.lastSwitch.code, 'provider_unavailable');
  assert.strictEqual(anu.lastSwitch.label, 'источник недоступен');
  assert.strictEqual(anu.lastSwitch.timeLabel, 'T1700000250');
  assert.strictEqual(anu.lastSwitch.source, 'state');

  const lfdr = byId(rows, 'lfdr');
  assert.strictEqual(lfdr.lastSwitch.code, 'provider_unavailable');
  assert.strictEqual(lfdr.lastSwitch.label, 'источник недоступен');
  assert.strictEqual(lfdr.lastSwitch.timeLabel, 'T1700000100');
  assert.strictEqual(lfdr.lastSwitch.source, 'health');

  const globalSwitch = methods.randomLastSwitchView.call(ctx);
  assert.strictEqual(globalSwitch.code, 'provider_unavailable');
  assert.strictEqual(globalSwitch.label, 'источник недоступен');
  assert.strictEqual(globalSwitch.timeLabel, 'T1700000250');
}

// ── (d) глобальный fallback не приписывается активному ANU/LfDR ───────────
{
  const ctx = makeCtx(status({
    resolved_primary: 'lfdr',
    blocker: 'provider_unavailable',
    last_fallback_reason: 'circuit_open',
    last_fallback_at: 1700000300,
  }));
  const rows = methods.randomProviderSummaries.call(ctx);
  assert.strictEqual(byId(rows, 'anu').lastSwitch.code, null,
    'circuit_open относится к LfDR, не к ANU');
  const lfdr = byId(rows, 'lfdr');
  assert.strictEqual(lfdr.lastSwitch.code, 'provider_unavailable',
    'текущий blocker атрибутируется resolved_primary');
  assert.strictEqual(lfdr.lastSwitch.source, 'selection');
  assert.strictEqual(lfdr.lastSwitch.timeLabel, '—',
    'время текущего blocker не выдаётся за время исторического fallback');
  assert.strictEqual(methods.randomLastSwitchView.call(ctx).code,
    'circuit_open', 'глобальная строка показывает журнал как есть');
}

// ── (e) unknown code: код виден, перевод не выдумывается ──────────────────
{
  const ctx = makeCtx(status({
    providers: providers({
      anu: { configured: true, state: 'degraded' },
      lfdr: { configured: true, state: 'degraded',
              last_error: 'future_code', last_failure_at: 1700000500 },
    }),
    last_fallback_reason: 'future_code', last_fallback_at: 1700000500,
  }));
  const rows = methods.randomProviderSummaries.call(ctx);
  assert.strictEqual(byId(rows, 'lfdr').lastSwitch.code, 'future_code');
  assert.strictEqual(byId(rows, 'lfdr').lastSwitch.label,
    'причина не описана');
  assert.strictEqual(byId(rows, 'anu').lastSwitch.label,
    'причина не описана');
  assert.strictEqual(methods.randomLastSwitchView.call(ctx).label,
    'причина не описана');
  assert.strictEqual(methods.randomSwitchReasonLabel.call({}, ''), 'нет данных');
}

// ── (f) нет providers[]/status: честное «нет данных», не «не настроен» ────
{
  const noProviders = makeCtx(status({
    providers: [],
    last_batch: null,
    last_fallback_reason: null,
  }));
  const rows = methods.randomProviderSummaries.call(noProviders);
  const anu = byId(rows, 'anu');
  const lfdr = byId(rows, 'lfdr');
  ['anu', 'lfdr'].forEach(function (id) {
    const row = byId(rows, id);
    assert.strictEqual(row.stateKey, 'no_data', id + ': state');
    assert.strictEqual(row.stateLabel, 'нет данных', id + ': state label');
    assert.strictEqual(row.reserve, null, id + ': reserve');
    assert.strictEqual(row.reserveText, 'нет данных', id + ': reserve text');
    assert.strictEqual(row.consumableText, 'нет данных', id + ': consumable');
    assertNoneData(row);
  });
  assert.strictEqual(byId(rows, 'ibm_quantum').stateKey,
    'adapter_not_implemented', 'IBM adapter известен UI и без providers[]');

  const notReady = makeCtx(null);
  const nrRows = methods.randomProviderSummaries.call(notReady);
  nrRows.forEach(function (row) {
    assert.strictEqual(row.stateKey, 'no_data', row.id);
    assert.strictEqual(row.stateLabel, 'нет данных', row.id);
    assert.strictEqual(row.reserveText, 'нет данных', row.id);
    assertNoneData(row);
  });
  assert.strictEqual(methods.randomLastSwitchView.call(notReady).code, null);

  // ANU manual check в текущей сессии не подменяет durable last_batch.
  const withCheck = makeCtx(status({
    last_batch: null,
    randomCheck: { healthy: true, checked_at: 1700000700 },
  }));
  withCheck.randomCheck = { healthy: true, checked_at: 1700000700 };
  assert.strictEqual(
    byId(methods.randomProviderSummaries.call(withCheck), 'anu')
      .lastSuccess.available,
    false, 'draw/check этой сессии не выдаётся за последнее получение');
}

// ── (g) summary без секретов; ключи/диагностика — в закрытом details ──────
{
  assert(INDEX.indexOf('data-random-provider-summary-block') >= 0);
  assert(INDEX.indexOf('data-random-last-switch') >= 0);
  assert(INDEX.indexOf('data-random-provider-summary-state') >= 0);
  assert(INDEX.indexOf('data-random-provider-summary-reserve') >= 0);
  assert(INDEX.indexOf('data-random-provider-summary-success') >= 0);
  assert(INDEX.indexOf('data-random-provider-summary-switch') >= 0);
  assert(INDEX.indexOf('data-random-provider-details') >= 0,
    'подробности/ключи свёрнуты');
  assert(INDEX.indexOf('data-random-provider-details open') < 0,
    'details закрыт по умолчанию');
  const summaryAt = INDEX.indexOf('data-random-provider-summary-block');
  const detailsAt = INDEX.indexOf('data-random-provider-details');
  const cardsAt = INDEX.indexOf('data-random-cards');
  const secretAt = INDEX.indexOf('secret-field', detailsAt);
  assert(summaryAt >= 0 && detailsAt > summaryAt,
    'сначала компактный summary');
  assert(cardsAt > detailsAt, 'подробные карточки внутри details');
  assert(secretAt > detailsAt, 'ключ внутри свёрнутого details');
  const summaryChunk = INDEX.slice(summaryAt, detailsAt);
  ['secret-field', 'keyDrafts', 'randomAnuKeyItem', 'fingerprint',
   'CRN', 'api_key', 'keys.random_quantum_api_key'].forEach(function (needle) {
    assert(summaryChunk.indexOf(needle) < 0,
      'в компактном summary нет секрета: ' + needle);
  });
  assert.strictEqual((INDEX.match(/data-random-provider="/g) || []).length, 3,
    'три подробные карточки сохранены');
}

console.log('QRNG-UI07-OK');
