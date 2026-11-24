'use strict';
/* QRNG P5B — IBM admin fields, read-only access check, explicit QPU smoke.
 *
 * Проверяет реальные методы web/app.js:
 *   (a) состояния IBM: не настроен / сохранён, не проверен / проверка /
 *       доступ подтверждён / получение подтверждено / ошибка стадии;
 *   (b) кнопки и поля: key/CRN — secret-field, instance/region — qrng-field,
 *       smoke требует подтверждения и шлёт confirm=true;
 *   (c) POST-body черновика не содержит маску; provider=ibm_quantum и CRN
 *       передаются отдельно; ответ не эхо-ится в шаблон;
 *   (d) «нет данных» вместо выдуманного «адаптер не реализован».
 *
 * Запуск: node tests/js/qrng_p5b_ibm_fields_test.js -> QRNG-P5B-OK
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
                 confirm: function () { return true; } };
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

function item(key, value, extra) {
  return Object.assign({ key: key, value: value, title: key,
                         type: 'str', secret: false }, extra || {});
}

function ctx(overrides) {
  return Object.assign({}, methods, {
    isGlobalAdmin: true,
    configItems: [
      item('keys.random_ibm_api_key',
           { configured: false, last4: null }, { secret: true }),
      item('keys.random_ibm_crn',
           { configured: false, last4: null }, { secret: true }),
      item('keys.random_ibm_instance', 'open-instance'),
      item('keys.random_ibm_region', 'us-east'),
      item('keys.random_ibm_channel', 'ibm_quantum_platform'),
    ],
    keyDrafts: {},
    randomCheck: null,
    randomIbmCheck: null,
    randomIbmCheckBusy: false,
    randomIbmSmoke: null,
    randomIbmSmokeBusy: false,
    fmtTs: function (v) { return 'T' + v; },
    loadStatus: async function () {},
    toast: function () {},
  }, overrides || {});
}

function withKey(entry) {
  return {
    configItems: [
      item('keys.random_ibm_api_key', { configured: true, last4: 'ABCD' },
           { secret: true }),
      item('keys.random_ibm_instance', 'open-instance'),
    ],
    randomActivityView: { providers: [entry] },
  };
}

function providerEntry(overrides) {
  return Object.assign({
    id: 'ibm_quantum', configured: false, state: 'provider_unconfigured',
    reserve: 0, consumable: false, quarantined: 0,
    last_error: null, last_failure_at: null, last_success_at: null,
    last_job: null, plan: null, usage: null,
  }, overrides || {});
}

// ── (a) состояния IBM ──────────────────────────────────────────────────────
{
  const c = ctx();
  assert.strictEqual(c.randomIbmStateInfo().key, 'unconfigured');
  const info = methods.randomProviderStateInfo.call(c, 'ibm_quantum',
                                                    false, '');
  assert.strictEqual(info.key, 'unconfigured');
  assert.strictEqual(info.label, 'не настроен');
}

{
  const c = ctx(withKey(providerEntry({ configured: true,
    state: 'unverified' })));
  assert.strictEqual(c.randomIbmStateInfo().key, 'saved_unverified');
  assert.strictEqual(c.randomIbmStateInfo().label, 'сохранён, не проверен');
}

{
  const c = ctx(withKey(providerEntry({ configured: true, state: 'active',
    last_job: { state: 'access_checked' } })));
  assert.strictEqual(c.randomIbmStateInfo().key, 'checked');
  assert.strictEqual(c.randomIbmStateInfo().label, 'доступ подтверждён');
}

{
  const c = ctx(withKey(providerEntry({ configured: true, state: 'active',
    last_job: { job_id: 'JOB1', backend: 'ibm_hw', state: 'completed' } })));
  assert.strictEqual(c.randomIbmStateInfo().key, 'measured');
  assert.strictEqual(c.randomIbmStateInfo().label, 'получение подтверждено');
}

{
  const c = ctx(withKey(providerEntry({ configured: true, state: 'degraded',
    last_error: 'invalid_instance' })));
  assert.strictEqual(c.randomIbmStateInfo().key, 'unavailable');
  assert(c.randomIbmStatusText().indexOf('instance/CRN') >= 0);
}

{
  const c = ctx({ randomIbmCheckBusy: true });
  assert.strictEqual(c.randomIbmStateInfo().key, 'checking');
  assert.strictEqual(c.randomIbmStateInfo().label, 'проверка выполняется');
}

async function main() {
  // ── (b) подтверждение платного измерения ────────────────────────────────
  {
    const calls = [];
    const c = ctx({
      api: async function (url, opts) {
        calls.push({ url: url, body: JSON.parse(opts.body) });
        return { healthy: true, job_id: 'JOB7', backend: 'ibm_hw',
                 shots: 256, bits: 128, usage_seconds: 0.5,
                 checked_at: 1700000000, deposited: false };
      },
    });
    global.window.confirm = function () { return false; };
    assert.strictEqual(await c.checkRandomIbmMeasurements(), null);
    assert.strictEqual(calls.length, 0, 'без подтверждения QPU job не ставится');
    global.window.confirm = function () { return true; };
    const res = await c.checkRandomIbmMeasurements();
    assert(res && res.healthy);
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].url, '/api/random/ibm/smoke');
    assert.strictEqual(calls[0].body.confirm, true);
    assert.strictEqual(calls[0].body.shots, 256);
    assert.strictEqual(Object.prototype.hasOwnProperty.call(
      calls[0].body, 'api_key'), false, 'секрет не попал в body');
    const view = c.randomIbmSmokeView();
    assert.strictEqual(view.ok, true);
    assert.strictEqual(view.jobId, 'JOB7');
    assert.strictEqual(view.bits, 128);
  }

  // ── (c) read-only проверка и черновики без маски ────────────────────────
  {
    const calls = [];
    const c = ctx({
      keyDrafts: {
        'keys.random_ibm_api_key': 'draft-ibm-key-1234567890',
        'keys.random_ibm_crn':
          'crn:v1:bluemix:public:quantum-compute:us-east:a/x:y::',
      },
      api: async function (url, opts) {
        calls.push({ url: url, body: JSON.parse(opts.body) });
        return { healthy: true, stage: null, blocker: null,
                 instance: 'open-instance', region: 'us-east',
                 selected_backend: 'ibm_hw', plan: 'Open',
                 backends: [], queue: { pending_jobs: 2 },
                 usage: { usage_remaining_ru: 590 }, persisted: false,
                 checked_at: 1700000001 };
      },
    });
    const res = await c.checkRandomIbmAccess();
    assert(res && res.healthy);
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].url, '/api/random/test');
    assert.strictEqual(calls[0].body.provider, 'ibm_quantum');
    assert.strictEqual(calls[0].body.key, 'draft-ibm-key-1234567890');
    assert(calls[0].body.crn.indexOf('quantum-compute') > 0);
    const view = c.randomIbmCheckView();
    assert.strictEqual(view.ok, true);
    assert.strictEqual(view.backend, 'ibm_hw');
    assert.strictEqual(view.plan, 'Open');
    assert.strictEqual(view.queue.pending_jobs, 2);
    assert.strictEqual(view.persisted, false);
  }

  {
    const calls = [];
    const c = ctx({
      keyDrafts: { 'keys.random_ibm_api_key': '••••••••••••ABCD' },
      api: async function (url, opts) {
        calls.push({ url: url, body: JSON.parse(opts.body) });
        return { healthy: false, blocker: 'provider_unconfigured',
                 stage: 'key', checked_at: 1 };
      },
    });
    await c.checkRandomIbmAccess();
    assert.strictEqual(calls[0].body.key, '', 'маска не передаётся как ключ');
    const err = c.randomIbmCheckView();
    assert.strictEqual(err.ok, false);
    assert.strictEqual(err.stageLabel, 'ключ');
  }

  // ── (d) шаблон: поля/кнопки/предупреждение; без выдуманного адаптера ────
  const markers = [
    'data-random-ibm-key', 'data-random-ibm-crn', 'data-random-ibm-save',
    'data-random-ibm-check', 'data-random-ibm-smoke',
    'data-random-ibm-check-result', 'data-random-ibm-smoke-result',
    'data-random-ibm-smoke-warning', 'data-random-ibm-details',
  ];
  markers.forEach(function (marker) {
    assert(INDEX.indexOf(marker) >= 0, 'нет маркера ' + marker);
  });
  assert(INDEX.indexOf('Проверка измерений ставит реальный QPU job') >= 0);
  assert(INDEX.indexOf('адаптер не реализован') < 0,
         'P5B больше не показывает «адаптер не реализован»');

  console.log('QRNG-P5B-OK');
}

main().catch(function (err) {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
