'use strict';
/* D05 (ASAP 8 v6, §18E.7/U8) — UI полезности уроков и цепочки обучения.
 *
 * Контракт:
 *   (a) usefulness = known_pos/(known_pos+known_neg) с sample:
 *       8/10 → «80% · 10 известных»; unknown показывается отдельно;
 *   (b) мало известных исходов (< 5) → «Недостаточно данных», не 0%;
 *   (c) нет данных вовсе → null (строка не рендерится);
 *   (d) человеческая цепочка строится из read-only воронки oversight
 *       (feedback → candidates → проверил → сохранил → применил →
 *       помогло/не помогло/неизвестно) без «AI IQ»;
 *   (e) выключенная воронка (enabled=false) → chain = null (секции скрыты);
 *   (f) loadLessons у глобального админа подтягивает воронку (лениво,
 *       single-flight гвард), у не-админа — не вызывает oversight API.
 *
 * Запуск: node tests/js/asap8_v6_d05_experience_ui_test.js
 */
const path = require('path');
const assert = require('assert');

let captured = null;
const components = {};
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component: function (name, def) { components[name] = def; },
      use() {}, provide() {}, directive() {}, mount() {},
    };
  },
};
const _storage = { _s: { 'adminbot.initData': 'test-init-data' },
  getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; } };
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; },
};
global.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };

let fetchHandler = null;
global.fetch = function (url, opts) {
  if (fetchHandler) return fetchHandler(url, opts);
  return Promise.reject(new Error('network disabled'));
};
global.Telegram = { WebApp: null };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));

(async function () {
  assert.ok(captured, 'createApp захвачен');
  const methods = captured.methods;
  assert.strictEqual(typeof methods.lessonUsefulness, 'function',
    'lessonUsefulness определён');
  assert.strictEqual(typeof methods.d05ExperienceChain, 'function',
    'd05ExperienceChain определён');
  const vm = {
    mca17cFunnel: null,
    mca17cFunnelBusy: false,
    isGlobalAdmin: true,
    lessonUsefulness: methods.lessonUsefulness,
    d05ExperienceChain: methods.d05ExperienceChain,
    oversightLoadFunnel: function () {
      vm.funnelLoads++;
      vm.mca17cFunnelBusy = true;          // single-flight гвард, как в app
      Promise.resolve().then(function () {
        vm.mca17cFunnelBusy = false;
        vm.mca17cFunnel = { enabled: true };
      });
    },
    funnelLoads: 0,
    lessonsBusy: false,
    lessonsData: null,
    _cidQuery: function () { return ''; },
    api: async function () { return { enabled: true, count: 0, lessons: [] }; },
  };

  // (a) 8/10 → «80% · 10 известных», unknown отдельно
  const u = methods.lessonUsefulness.call(vm, 8, 2, 7);
  assert.strictEqual(u.ready, true);
  assert.strictEqual(u.pct, 80);
  assert.strictEqual(u.label, '80% · 10 известных');
  assert.strictEqual(u.unknown, 7, 'unknown виден отдельно');

  // (b) sample < минимума → «Недостаточно данных», не 0%
  const small = methods.lessonUsefulness.call(vm, 0, 2, 3);
  assert.strictEqual(small.ready, false);
  assert.strictEqual(small.label, 'Недостаточно данных');
  const smallOk = methods.lessonUsefulness.call(vm, 4, 0, 0);
  assert.strictEqual(smallOk.ready, false);
  assert.strictEqual(smallOk.label, 'Недостаточно данных');

  // отрицательная полезность честна, если sample достаточен
  const low = methods.lessonUsefulness.call(vm, 1, 9, 2);
  assert.strictEqual(low.ready, true);
  assert.strictEqual(low.pct, 10);
  assert.strictEqual(low.label, '10% · 10 известных');

  // (c) нет данных вовсе → null
  assert.strictEqual(methods.lessonUsefulness.call(vm, 0, 0, 0), null);

  // (e) воронка выключена/не загружена → цепочки нет
  assert.strictEqual(methods.d05ExperienceChain.call(vm), null);
  vm.mca17cFunnel = { enabled: false };
  assert.strictEqual(methods.d05ExperienceChain.call(vm), null);

  // (d) цепочка из воронки: полный проход
  vm.mca17cFunnel = {
    enabled: true,
    feedback: { total: 12, unique_episodes: 9 },
    lessons: { candidate: 3, validated: 1, active: 6, suspended: 1,
               superseded: 2, new_in_period: 8 },
    applications: { total: 10, success: 8, failure: 2, unknown: 7,
                    unique_lessons: 4 },
  };
  const chain = methods.d05ExperienceChain.call(vm);
  assert.strictEqual(chain.noticed, 12);
  assert.strictEqual(chain.candidates, 3);
  assert.strictEqual(chain.checked, 7, 'проверил = validated + active');
  assert.strictEqual(chain.saved, 6);
  assert.strictEqual(chain.applied, 10);
  assert.strictEqual(chain.helped, 8);
  assert.strictEqual(chain.notHelped, 2);
  assert.strictEqual(chain.unknownOutcomes, 7);
  assert.strictEqual(chain.usefulness.ready, true);
  assert.strictEqual(chain.usefulness.label, '80% · 10 известных');

  // (f) loadLessons: глобальный админ лениво тянет воронку (один раз)
  vm.mca17cFunnel = null;
  await methods.loadLessons.call(vm);
  await Promise.resolve();               // макет воронки завершается
  assert.ok(vm.funnelLoads >= 1, 'воронка запрошена для админа');
  const before = vm.funnelLoads;
  await methods.loadLessons.call(vm);
  assert.strictEqual(vm.funnelLoads, before,
    'уже загружена — повторного запроса нет');

  const nonAdmin = Object.assign({}, vm, { isGlobalAdmin: false,
    funnelLoads: 0, mca17cFunnel: null });
  await methods.loadLessons.call(nonAdmin);
  assert.strictEqual(nonAdmin.funnelLoads, 0,
    'не-админ не вызывает oversight API');

  console.log('D05-EXPERIENCE-UI-OK');
})().catch(function (e) {
  console.error('FAIL:', e && e.message);
  if (e && e.stack) console.error(e.stack);
  process.exit(1);
});
