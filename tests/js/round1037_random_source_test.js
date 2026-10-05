'use strict';
/* MCA-10a (round 10.37, ADR-1028-14 D8/D9, T-4977/T-4979) — JS-проверки:
 *   * computed `randomSource` — проекция аддитивного /api/status.random;
 *     при фактическом PRNG quantum-статус НЕ показывается (честная подпись
 *     «псевдослучайный» + точный блокер); K1 OFF → disabled;
 *   * «Проверить подключение» ANU: draft-ключ уходит ТОЛЬКО в POST-body
 *     `/api/random/test` (не в URL), маска-композит не отправляется,
 *     повторный клик не дублируется (busy), ошибка → client_error;
 *   * раскрытие «Последние решения» — клиентское (данных уже в /api/status);
 *   * wiring index.html: карточка Статуса, кнопка проверки, раскрытие;
 *   * зеркало TABS (mod_sleep→memory_random, llm_providers→keys_random).
 *
 * Запуск: node tests/js/round1037_random_source_test.js → MCA10A-RANDOM-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component() {}, provide() {}, use() {}, mount() {},
    };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
const ROOT = path.join(__dirname, '..', '..');
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    return { tagName: tag, className: '', value: '', style: {},
             setAttribute() {}, focus() {}, select() {}, remove() {} };
  },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
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
const methods = captured.methods;
const computed = captured.computed;
assert(computed && computed.randomSource, 'computed.randomSource не найден');
assert(methods && methods.checkRandomConnection,
  'methods.checkRandomConnection не найден');
assert(methods && methods.randomCheckStatus,
  'methods.randomCheckStatus не найден');
assert(methods && methods.onKeyDraft, 'methods.onKeyDraft не найден');

function ctx(statusData) { return { statusData: statusData }; }
function rs(statusData) {
  return computed.randomSource.call(ctx(statusData));
}

// ── 1. Нет данных / K1 OFF → honest disabled ──────────────────────────────
(function () {
  const empty = rs(null);
  assert.strictEqual(empty.ready, false);
  assert.strictEqual(empty.quantum, false);
  const off = rs({ random: { enabled: false, available: false,
                             state: 'disabled' } });
  assert.strictEqual(off.ready, true);
  assert.strictEqual(off.enabled, false);
  assert.strictEqual(off.quantum, false);
  assert.strictEqual(off.stateLabel, 'выключено');
})();

// ── 2. Фактический PRNG → quantum-статус НЕ показывается ─────────────────
(function () {
  const r = rs({ random: {
    enabled: true, available: true,
    selected_source: 'quantum', effective_source: 'pseudorandom',
    quantum_active: false, anu_state: 'active',
    blocker: 'provider_unavailable', key_present: true,
    reserve_remaining: 0, buffer_max: 2048, low_watermark: 256,
    last_batch: null, draws: { quantum: 3, pseudorandom: 7 },
    last_fallback_reason: 'provider_unavailable', last_fallback_at: 1000,
    plan: 'Trial', recent_draws: [], recent_draws_scope: 'chat',
  } });
  assert.strictEqual(r.quantum, false);
  assert.strictEqual(r.stateLabel, 'псевдослучайный (локальный)');
  assert(r.stateLabel.indexOf('ANU') === -1,
    'quantum-статус не должен показываться при фактическом PRNG');
  assert.strictEqual(r.blockerLabel, 'провайдер недоступен');
  assert.strictEqual(r.draws.pseudorandom, 7);
  assert.strictEqual(r.reserve, 0);
})();

// ── 3. Фактический quantum → честный ANU-статус ───────────────────────────
(function () {
  const r = rs({ random: {
    enabled: true, available: true, quantum_active: true,
    selected_source: 'quantum', effective_source: 'quantum',
    anu_state: 'active', blocker: null, key_present: true,
    reserve_remaining: 512, buffer_max: 2048, low_watermark: 256,
    last_batch: { length: 1024, created_at: 1000 },
    draws: { quantum: 9, pseudorandom: 1 },
    recent_draws: [{ draw_id: 'd1', source: 'quantum', purpose: 'p',
                     selected_id: '3', candidates: ['1', '3'] }],
    recent_draws_scope: 'chat', plan: 'Trial',
  } });
  assert.strictEqual(r.quantum, true);
  assert.strictEqual(r.stateLabel, 'ANU активен (квантовые числа)');
  assert.strictEqual(r.blockerLabel, null);
  assert.strictEqual(r.recent.length, 1);
})();

// ── 4. «Проверить подключение»: draft только в body, маска не уходит ──────
(async function () {
  const calls = [];
  const c = {
    keyDrafts: { 'keys.random_quantum_api_key': 'draft-key-1' },
    randomCheck: null, randomCheckBusy: false,
    api: async function (url, opts) {
      calls.push({ url: url, opts: opts });
      return { healthy: true, length: 8, latency_ms: 12,
               checked_at: 1700000000, persisted: false,
               key_present: true };
    },
  };
  await methods.checkRandomConnection.call(
    c, { key: 'keys.random_quantum_api_key' });
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].url, '/api/random/test');
  assert(calls[0].url.indexOf('draft-key-1') === -1,
    'ключ не должен попадать в URL');
  assert.strictEqual(calls[0].opts.method, 'POST');
  assert.strictEqual(calls[0].opts.global, true);
  const body = JSON.parse(calls[0].opts.body);
  assert.strictEqual(body.key, 'draft-key-1');
  assert.strictEqual(c.randomCheck.healthy, true);
  assert.strictEqual(c.randomCheckBusy, false);
  assert.strictEqual(methods.randomCheckStatus.call(c).cls, 'badge-ok');

  // Маска/композит → пустой draft (проверяется сохранённый ключ).
  const calls2 = [];
  const c2 = {
    keyDrafts: { 'keys.random_quantum_api_key':
      '\u2022'.repeat(12) + 'tail' },
    randomCheck: null, randomCheckBusy: false,
    api: async function (url, opts) {
      calls2.push(opts);
      return { healthy: false, blocker: 'auth_failed' };
    },
  };
  await methods.checkRandomConnection.call(
    c2, { key: 'keys.random_quantum_api_key' });
  assert.strictEqual(JSON.parse(calls2[0].body).key, '');
  assert.strictEqual(methods.randomCheckStatus.call(c2).cls, 'badge-err');
  assert.strictEqual(methods.randomCheckStatus.call(c2).label,
                     'ключ отклонён (401/403)');

  // Ошибка клиента → очищенная причина, ключ не течёт.
  const c3 = {
    keyDrafts: { 'keys.random_quantum_api_key': 'k3' },
    randomCheck: null, randomCheckBusy: false,
    api: async function () { throw new Error('boom'); },
  };
  await methods.checkRandomConnection.call(
    c3, { key: 'keys.random_quantum_api_key' });
  assert.strictEqual(c3.randomCheck.blocker, 'client_error');
  assert(String(c3.randomCheck.reason).indexOf('k3') === -1);

  // Повторный клик, пока busy → не дублируется.
  const c4 = {
    keyDrafts: {}, randomCheck: null, randomCheckBusy: true,
    api: async function () { throw new Error('must not call'); },
  };
  await methods.checkRandomConnection.call(
    c4, { key: 'keys.random_quantum_api_key' });
  assert.strictEqual(c4.randomCheck, null);

  // Черновик изменился → прошлый результат проверки сброшен.
  const c5 = { keyDrafts: {}, randomCheck: { healthy: true } };
  methods.onKeyDraft.call(c5, { key: 'keys.random_quantum_api_key' }, 'new');
  assert.strictEqual(c5.keyDrafts['keys.random_quantum_api_key'], 'new');
  assert.strictEqual(c5.randomCheck, null);

  // ── 5. Wiring index.html + зеркало TABS ─────────────────────────────────
  const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
  assert(INDEX.indexOf('data-random-source') !== -1,
    'карточка «Источник случайности» не найдена');
  assert(INDEX.indexOf('data-random-check') !== -1, 'блок проверки не найден');
  assert(INDEX.indexOf('data-random-draws') !== -1, 'раскрытие решений не найдено');
  assert(INDEX.indexOf('Проверить подключение') !== -1);
  assert(INDEX.indexOf('Последние решения') !== -1);
  assert(INDEX.indexOf("item.key === 'keys.random_quantum_api_key'") !== -1);
  assert(INDEX.indexOf('randomSource.quantum ?') !== -1,
    'quantum-бейдж должен зависеть от фактического источника');
  assert(INDEX.indexOf('randomDrawsOpen') !== -1);
  assert(APP_JS.indexOf("groups: ['memory_dream']") !== -1);
  assert(APP_JS.indexOf("groups: ['memory_random']") !== -1,
    'зеркало TABS: memory_random на mod_sleep');
  assert(APP_JS.indexOf("'keys_random'") !== -1,
    'зеркало TABS: keys_random на llm_providers');
  assert(APP_JS.indexOf("'/api/random/test'") !== -1);
  // R17: ключ ANU (значение) не пишется в localStorage/sessionStorage —
  // черновик живёт только в in-memory keyDrafts.
  assert(!/localStorage[^\n]*random_quantum_api_key/.test(APP_JS),
    'ключ ANU не должен попадать в localStorage');
  assert(!/sessionStorage[^\n]*random_quantum_api_key/.test(APP_JS),
    'ключ ANU не должен попадать в sessionStorage');

  console.log('MCA10A-RANDOM-OK');
})().catch(function (e) {
  console.error(e && e.stack || e);
  process.exit(1);
});
