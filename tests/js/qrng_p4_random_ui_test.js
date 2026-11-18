'use strict';
/* QRNG P4 — «Модули → Случайность»: карта вкладок, настоящий селектор,
 * fallback-порядок, честная активность, перенос keys_random с LLM.
 *
 * Проверяет РЕАЛЬНУЮ логику web/app.js (require), не grep:
 *   (a) TABS: +mod_random; keys_random НЕТ на llm_providers; memory_random
 *       НЕТ на mod_sleep; источники mod_random = memory_random + keys_random;
 *   (b) WORKSPACE_TABS.mod_random — B3-совместимая строка (overview/settings/
 *       history); MODULE_MODEL_BLOCKS.mod_random — без моделей (generic не
 *       дублирует страницу);
 *   (c) селектор пишет РЕАЛЬНЫЙ provider id через persistItems (POST /api/config
 *       items[].key=random.primary_provider), а не меняет только текст;
 *   (d) fallback-порядок: без дублей, без primary, включение/исключение/выше/
 *       ниже сохраняют тот же параметр random.fallback_order;
 *   (e) Activity честная: нет данных/PRNG → НЕ badge-ok, квантовый → badge-ok;
 *   (f) «Проверить подключение» использует существующий /api/random/test и
 *       честную подсказку (draft: значения НЕ зачисляются);
 *   (g) ровно три карточки/три провайдера; Lizaonair отсутствует в бандле;
 *   (h) «Время ответа и защита» — последняя группа витрины моделей.
 *
 * Запуск: node tests/js/qrng_p4_random_ui_test.js -> QRNG-P4-UI-OK
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
const APP_PATH = path.join(ROOT, 'web', 'app.js');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(APP_PATH, 'utf8');
require(APP_PATH);

assert(captured, 'Vue.createApp не вызван');
const data = captured.data();
const methods = captured.methods || {};
const computed = captured.computed || {};

function tab(id) {
  return (data.tabs || []).filter(function (t) { return t.id === id; })[0];
}
function srcGroups(t) {
  const out = [];
  ((t && t.sources) || []).forEach(function (s) {
    (s.groups || []).forEach(function (g) { out.push(g); });
  });
  return out;
}
function srcText() { return fs.readFileSync(APP_PATH, 'utf8'); }

// ── (a) карта вкладок: перенос, не копия ──────────────────────────────────
{
  const ids = (data.tabs || []).map(function (t) { return t.id; });
  assert.strictEqual(ids.length, 29, 'вкладок 29 (28 + mod_random)');
  assert(ids.indexOf('mod_random') >= 0, 'mod_random объявлена');
  const rt = tab('mod_random');
  assert(rt && rt.type === 'config' && rt.menu === 'modules',
    'mod_random — config-вкладка раздела «Модули»');
  assert.strictEqual(rt.label, 'Случайность', 'подпись вкладки');
  assert.deepStrictEqual(srcGroups(rt).sort(), ['keys_random', 'memory_random'],
    'источники mod_random — обе существующие группы');
  const llm = tab('llm_providers');
  assert(srcGroups(llm).indexOf('keys_random') < 0,
    'keys_random НЕ остаётся на llm_providers (перенос)');
  const sleep = tab('mod_sleep');
  assert(srcGroups(sleep).indexOf('memory_random') < 0,
    'memory_random НЕ остаётся на mod_sleep (перенос)');
  assert.strictEqual(srcGroups(sleep).indexOf('memory_dream') >= 0, true,
    'memory_dream остаётся на «Сне»');
  const opts = computed.randomPrimaryOptions.call({});
  assert.deepStrictEqual(opts.map(function (o) { return o.id; }),
    ['ibm_quantum', 'anu', 'lfdr'],
    'ровно 3 опции селектора (real provider ids)');
}

// ── (b) B3-совместимая строка workspace + отсутствие моделей ──────────────
{
  assert(/mod_random:\s*\['overview',\s*'settings',\s*'history'\]/
    .test(APP_JS), 'WORKSPACE_TABS.mod_random совместим с B3 (history)');
  const block = APP_JS.slice(APP_JS.indexOf('var MODULE_MODEL_BLOCKS = {'),
    APP_JS.indexOf('};', APP_JS.indexOf('var MODULE_MODEL_BLOCKS = {')));
  assert(/mod_random:\s*\[\]/.test(block),
    'MODULE_MODEL_BLOCKS.mod_random = [] (generic-модели не дублируются)');
}

// ── (c) настоящий селектор: реальный provider id в POST /api/config ───────
const p1 = (async function () {
  const item = { key: 'random.primary_provider', value: 'ibm_quantum',
                 per_chat: false };
  const order = { key: 'random.fallback_order',
                  value: ['ibm_quantum', 'anu'], per_chat: false };
  const posts = [];
  const ctx = {
    isGlobalAdmin: true,
    configItems: [item, order],
    randomCfg: methods.randomCfg,
    randomFallbackValue: methods.randomFallbackValue,
    randomFallbackOrderItem: methods.randomFallbackOrderItem,
    randomPrimaryValue: methods.randomPrimaryValue,
    qrngPersist: methods.qrngPersist,
    persistItems: async function (items) {
      posts.push(items);
      return { saved: items.map(function (it) { return it.key; }) };
    },
    loadConfig: async function () {},
    loadStatus: async function () {},
    toast: function () {},
  };
  const ok = await methods.saveRandomPrimary.call(ctx, 'anu');
  assert.strictEqual(ok, true, 'селектор сохранился');
  assert.strictEqual(posts.length, 1, 'ровно один POST-батч');
  const sent = posts[0];
  assert.deepStrictEqual(sent.map(function (x) { return x.key; }),
    ['random.primary_provider', 'random.fallback_order'],
    'пишется реальный ключ + очищенный порядок');
  assert.strictEqual(sent[0].value, 'anu', 'сохранён provider id, не текст');
  assert.deepStrictEqual(sent[1].value, ['ibm_quantum'],
    'primary исключён из fallback_order (серверный guard 422 не срабатывает)');
  // И никакой «декоративной» подмены: неизвестный id не уходит.
  const badPosts = [];
  ctx.persistItems = async function (items) {
    badPosts.push(items); return { saved: items.map(function (it) { return it.key; }) };
  };
  assert.strictEqual(await methods.saveRandomPrimary.call(ctx, 'lizaonair'),
    false, 'снятый/неизвестный id не сохраняется');
  assert.strictEqual(badPosts.length, 0, 'dummy-id не дошёл до POST');
})();

// ── (d) fallback-порядок: без дублей, без primary, up/down ────────────────
const p2 = (async function () {
  const order = { key: 'random.fallback_order', value: ['anu', 'lfdr'],
                  per_chat: false };
  const ctx = {
    isGlobalAdmin: true,
    configItems: [order],
    randomCfg: methods.randomCfg,
    randomFallbackValue: methods.randomFallbackValue,
    randomFallbackOrderItem: methods.randomFallbackOrderItem,
    randomPrimaryValue: function () { return 'ibm_quantum'; },
    randomFallbackRows: methods.randomFallbackRows,
    saveRandomFallbackOrder: async function (value) {
      this.saved = value; return true;
    },
    setRandomFallbackIncluded: methods.setRandomFallbackIncluded,
    moveRandomFallback: methods.moveRandomFallback,
  };
  const rows = methods.randomFallbackRows.call(ctx);
  assert.deepStrictEqual(rows.map(function (r) { return r.id; }),
    ['anu', 'lfdr'], 'в списке нет primary и нет дублей');
  await methods.setRandomFallbackIncluded.call(ctx, 'lfdr', false);
  assert.deepStrictEqual(ctx.saved, ['anu'], 'исключение из резерва');
  await methods.setRandomFallbackIncluded.call(ctx, 'lfdr', true);
  assert.deepStrictEqual(ctx.saved, ['anu', 'lfdr'], 'включение в конец');
  await methods.moveRandomFallback.call(ctx, 'lfdr', -1);
  assert.deepStrictEqual(ctx.saved, ['lfdr', 'anu'], 'перемещение выше');
  await methods.moveRandomFallback.call(ctx, 'anu', 1);
  assert.deepStrictEqual(ctx.saved, ['lfdr', 'anu'], 'ниже последнего — no-op');
  // Серверный guard 422: primary не может попасть в fallback_order — даже
  // если пришёл в списке, проверка сохранения его вычищает.
  const cleanPosts = [];
  const cleanCtx = {
    isGlobalAdmin: true,
    configItems: [order],
    randomCfg: methods.randomCfg,
    randomFallbackOrderItem: methods.randomFallbackOrderItem,
    randomPrimaryValue: function () { return 'ibm_quantum'; },
    qrngPersist: async function (items) {
      cleanPosts.push(items);
      return { saved: items.map(function (it) { return it.key; }) };
    },
  };
  await methods.saveRandomFallbackOrder.call(
    cleanCtx, ['anu', 'ibm_quantum', 'lfdr']);
  assert.deepStrictEqual(cleanPosts[0][0].value, ['anu', 'lfdr'],
    'primary вычищается из fallback_order перед POST');
})();

// ── (e) Activity: no fake green ───────────────────────────────────────────
{
  const view = function (r) {
    return computed.randomActivityView.call({
      randomSource: methods._randomSourceView.call({}, r),
    });
  };
  const none = view(null);
  assert.strictEqual(none.stateCls, 'badge-muted', 'нет данных — не зелёный');
  assert.strictEqual(none.ready, false, 'нет данных — ready=false');
  const prng = view({ enabled: true, available: true, ready: true,
    quantum_active: false, effective_source: 'pseudorandom',
    effective_provider: null, prng_active: true, prng_setting: true,
    providers: [], provider_reserve: {}, provider_quarantined: {},
    reserve_remaining: 0, last_batch: null, draws: {}, recent_draws: [] });
  assert.strictEqual(prng.stateCls, 'badge-warn',
    'PRNG-откат — предупреждение, не «работает»');
  assert(prng.stateLabel.indexOf('псевдослучайный') >= 0,
    'PRNG назван честно');
  assert.strictEqual(prng.quantum, false);
  const q = view({ enabled: true, available: true, ready: true,
    quantum_active: true, effective_source: 'quantum', effective_provider: 'anu',
    entropy_class: 'hardware_quantum', primary_provider: 'anu',
    providers: [{ id: 'anu', configured: true, reserve: 5, consumable: true,
                  quarantined: 0, state: 'active' }],
    provider_reserve: { anu: 5 }, provider_quarantined: { anu: 0 },
    reserve_remaining: 5, last_batch: { length: 5, provider_id: 'anu',
      created_at: 1794909600, config_matches: true },
    draws: { quantum: 5, pseudorandom: 0 }, recent_draws: [] });
  assert.strictEqual(q.stateCls, 'badge-ok', 'подтверждённый quantum — зелёный');
  assert.strictEqual(q.entropyClass, 'hardware_quantum');
}

// ── (f) draft-подсказка: значения НЕ зачисляются ──────────────────────────
{
  const hint = methods.randomDraftHint.call({});
  assert.strictEqual(hint,
    'Проверка черновым ключом расходует квоту провайдера; значения не '
    + 'зачисляются в рабочий запас. Сохранённый ключ при проверке '
    + 'активируется.');
  assert(INDEX.indexOf('data-random-draft-hint') >= 0);
  assert(INDEX.indexOf('зачисляет полученную партию') < 0,
    'старая подсказка про зачисление удалена');
  assert(INDEX.indexOf('data-random-check') >= 0 &&
    INDEX.indexOf('Проверить подключение') >= 0,
    'ANU «Проверить подключение» на месте');
}

// ── (g) ровно 3 карточки/провайдера; Lizaonair отсутствует ────────────────
{
  ['ibm_quantum', 'anu', 'lfdr'].forEach(function (id) {
    assert(INDEX.indexOf('data-random-provider="' + id + '"') >= 0,
      'карточка ' + id + ' на месте');
  });
  assert.strictEqual((INDEX.match(/data-random-provider="/g) || []).length, 3,
    'ровно 3 карточки провайдеров');
  assert.strictEqual((INDEX.match(/data-random-primary/g) || []).length, 1,
    'один настоящий селектор');
  const bundle = (APP_JS + '\n' + INDEX).toLowerCase();
  assert.strictEqual(bundle.indexOf('lizaonair'), -1,
    'Lizaonair отсутствует во всём UI/JS-бандле');
  ['data-random-sources', 'data-random-uses', 'data-random-activity',
   'data-random-advanced'].forEach(function (marker) {
    assert(INDEX.indexOf(marker) >= 0, 'блок ' + marker + ' на месте');
  });
}

// ── (h) «Время ответа и защита» — последняя группа моделей ────────────────
{
  const ctx = { providerBlocks: data.providerBlocks };
  ctx.providerConnectionBlocks =
    computed.providerConnectionBlocks.call(ctx);
  const grouped = computed.providerGrouped.call(ctx);
  const thematic = grouped.filter(function (g) { return g.id !== 'technical'; });
  assert.strictEqual(thematic[thematic.length - 1].title,
    'Время ответа и защита', 'таймауты — последняя расширенная группа');
  assert.deepStrictEqual(
    thematic[thematic.length - 1].blocks.map(function (b) { return b.id; }),
    ['llm_guard'], 'llm_guard не потерян');
}

Promise.all([p1, p2]).then(function () {
  console.log('QRNG-P4-UI-OK');
}).catch(function (e) {
  console.error(e && e.stack || e);
  process.exit(1);
});
