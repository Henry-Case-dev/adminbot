'use strict';
/* ASAP 7 F2 (Wave 3) — Direct settings (L1 Planner) + Pipeline widget:
 * JS-харнесс (по образцу asap7_f8_cover_prompts_test.js).
 *
 * Проверяется рантайм-поведение SECTION-DIRECT-UI:
 *   1) directStageCards: честный effective provider/model/source —
 *      configured слот L1 → «Отдельный слот L1», пусто → inherit main (D-5);
 *   2) directL1PlannerCard: effective source/лимиты/фолбэк из configItems;
 *   3) REV-2 (б): requested/effective/следствие per-chat autonomous toggle —
 *      при «выключено» + L1 ON честно «бот может промолчать»;
 *   4) responseL1Rows: durable-оси 24ч/7д — строки при данных, [] без них;
 *   5) index.html маркеры (data-direct-l1-planner / data-l1-effective /
 *      data-l1-durable-axes / data-autonomous-*) + R17: в Direct-регионах
 *      нет include_prompt/полных промптов.
 *
 * Запуск: node tests/js/asap7_f2_direct_ui_test.js  → ASAP7-F2-DIRECT-UI-OK
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
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, focus() {}, select() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
  execCommand() { return true; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};
Object.defineProperty(global, 'navigator', {
  value: { clipboard: { writeText: async function () {} } },
  configurable: true,
});
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;

// (1) методы/computed существуют.
['directStageCards', 'directL1PlannerCard',
 'directAutonomousSemantics'].forEach(function (name) {
  assert.strictEqual(typeof methods[name], 'function', '1: ' + name);
});
['responseL1Rows', 'responseAggRows'].forEach(function (name) {
  assert.strictEqual(typeof captured.computed[name], 'function',
    '1: computed ' + name);
});
const responseL1Rows = captured.computed.responseL1Rows;

function itemsCtx(items) {
  return {
    configItems: items,
    blockFieldValue: function (f) {
      const it = (items || []).find(function (i) { return i.key === f.key; });
      if (!it) return '';
      if (it.value && typeof it.value === 'object') return '';
      return typeof it.value === 'string' ? it.value
        : (it.value == null ? '' : String(it.value));
    },
    configSourceLabel: function () { return 'Источник: глобальная настройка'; },
  };
}

// (2) D-5: configured слот L1 → честный «Отдельный слот L1»; пусто → inherit.
const CONFIGURED = [
  { key: 'models.direct_l1_model_name', value: 'planner-x', type: 'str' },
  { key: 'models.direct_l1_base_url', value: 'https://l1.example/v1', type: 'str' },
  { key: 'keys.direct_l1_api_key', value: { configured: true, last4: 'ab12' }, type: 'str', secret: true },
  { key: 'models.llm_model_name', value: 'main-model', type: 'str' },
  { key: 'models.llm_base_url', value: 'https://main.example/v1', type: 'str' },
  { key: 'prompts.direct_l1_planner_system_prompt', value: 'SYS', type: 'str' },
  { key: 'prompts.direct_chat_verbalizer_system_prompt', value: 'VB', type: 'str' },
];
let cards = methods.directStageCards.call(itemsCtx(CONFIGURED));
assert.strictEqual(cards.length, 2, '2: две карточки L1/L2');
const l1 = cards[0], l2 = cards[1];
assert.strictEqual(l1.id, 'l1');
assert.ok(l1.title.includes('L1'), '2: L1 title');
assert.strictEqual(l1.provider, 'https://l1.example/v1');
assert.strictEqual(l1.modelName, 'planner-x');
assert.strictEqual(l1.source, 'Отдельный слот L1 (configured)');
assert.strictEqual(l1.inheritsMain, false);
assert.strictEqual(l2.inheritsMain, true, '2: L2 честно на основной модели');

const EMPTY = [
  { key: 'models.llm_model_name', value: 'main-model', type: 'str' },
  { key: 'models.llm_base_url', value: 'https://main.example/v1', type: 'str' },
  { key: 'prompts.direct_l1_planner_system_prompt', value: 'SYS', type: 'str' },
  { key: 'prompts.direct_chat_verbalizer_system_prompt', value: 'VB', type: 'str' },
];
cards = methods.directStageCards.call(itemsCtx(EMPTY));
assert.strictEqual(cards[0].inheritsMain, true, '2: пустой слот → inherit');
assert.strictEqual(cards[0].modelName, 'main-model');
assert.ok(cards[0].source.includes('Наследует'),
  '2: honest inherit подпись');

// (3) directL1PlannerCard: effective source + лимиты.
const FULL = CONFIGURED.concat([
  { key: 'flags.direct_l1_enabled', value: true, type: 'bool' },
  { key: 'flags.direct_l1_fallback_enabled', value: false, type: 'bool' },
  { key: 'limits.direct_l1_temperature', value: 0.4, type: 'float' },
  { key: 'limits.direct_l1_timeout_seconds', value: 20, type: 'int' },
  { key: 'limits.direct_l1_max_output_tokens', value: 700, type: 'int' },
  { key: 'limits.direct_l1_context_tokens', value: 2400, type: 'int' },
  { key: 'flags.chat_autonomous_reply_enabled', value: false, type: 'bool' },
]);
const card = methods.directL1PlannerCard.call(itemsCtx(FULL));
assert.strictEqual(card.enabled, true);
assert.strictEqual(card.fallbackOn, false, '3: fallback toggled off');
assert.ok(card.effectiveSource.includes('planner-x'), '3: effective model');
assert.strictEqual(card.temperature, '0.4');
assert.strictEqual(card.timeout, '20 с');
assert.strictEqual(card.maxOutput, '700');
assert.strictEqual(card.context, '2400');
assert.strictEqual(card.autonomous, false);

// Дефолты (пустые поля) — честные подписи «по умолчанию»/«Авто».
const cardDef = methods.directL1PlannerCard.call(itemsCtx(EMPTY));
assert.strictEqual(cardDef.temperature, 'Авто (как у основного ответа)');
assert.strictEqual(cardDef.timeout, '15 с (по умолчанию)');
assert.strictEqual(cardDef.maxOutput, '512 (по умолчанию)');
assert.strictEqual(cardDef.context, '1600 (по умолчанию)');
assert.strictEqual(cardDef.inheritsMain, true);

// (4) REV-2 (б): autonomous OFF + L1 ON → честное «может промолчать».
const semCtx = itemsCtx(FULL);
semCtx.directL1PlannerCard = methods.directL1PlannerCard;
const sem = methods.directAutonomousSemantics.call(semCtx);
assert.strictEqual(sem.requested, false);
assert.strictEqual(sem.l1On, true);
assert.ok(sem.text.includes('промолчит'), '4: следствие — молчание возможен');
assert.ok(sem.text.includes('без 🗿'), '4: 🗿 не ставится');
// autonomous ON + L1 ON → свобода L1.
const FULL_ON = FULL.map(function (i) {
  return i.key === 'flags.chat_autonomous_reply_enabled'
    ? { key: i.key, value: true, type: 'bool' } : i;
});
const onCtx = itemsCtx(FULL_ON);
onCtx.directL1PlannerCard = methods.directL1PlannerCard;
const semOn = methods.directAutonomousSemantics.call(onCtx);
assert.strictEqual(semOn.requested, true);
assert.ok(semOn.text.includes('свободно выбирает'), '4: L1 свободен');
// L1 OFF → прежняя семантика.
const FULL_L1OFF = FULL.map(function (i) {
  return i.key === 'flags.direct_l1_enabled'
    ? { key: i.key, value: false, type: 'bool' } : i;
});
const offCtx = itemsCtx(FULL_L1OFF);
offCtx.directL1PlannerCard = methods.directL1PlannerCard;
const semOff = methods.directAutonomousSemantics.call(offCtx);
assert.strictEqual(semOff.l1On, false);
assert.ok(semOff.text.includes('прежняя'), '4: L1 OFF → прежняя семантика');

// (5) responseL1Rows: durable-оси — строки; пусто → [] (честно).
const summaryCtx = { responseSummary: { l1: {
  available: true, calls: 5, with_meta: 4,
  actions: { reply: 3, silent: 1 }, extents: { compact: 2 },
  tones: { inherit: 3 }, buckets: { high: 3, low: 1 },
  inherited_rate: 0.25, fallback_rate: 0.25,
  latency_ms: { p50: 640, p95: 1500.5 },
} } };
let rows = responseL1Rows.call(summaryCtx);
assert.ok(rows.length >= 7, '5: строки durable-осей L1');
assert.ok(rows.some(function (r) {
  return r.key === 'l1actions' && r.value.includes('ответ');
}), '5: распределение действий');
assert.ok(rows.some(function (r) {
  return r.key === 'l1latency' && r.value.includes('640');
}), '5: latency');
assert.deepStrictEqual(
  responseL1Rows.call({ responseSummary: null }),
  [], '5: нет данных → пусто');

// (6) index.html: маркеры Direct-регионов + Pipeline L1-блок; R17.
const html = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf-8');
['data-direct-l1-planner', 'data-l1-effective', 'data-l1-enabled',
 'data-effective-source', 'data-direct-autonomous-semantics',
 'data-autonomous-requested', 'data-autonomous-consequence',
 'data-l1-durable-axes'].forEach(function (marker) {
  assert.ok(html.includes(marker), '6: ' + marker);
});
// R17: в СВОИХ регионах нет include_prompt / exact-промптов
// (регионы короткие — проверяем ограниченные срезы, не весь файл).
function regionOf(marker, span) {
  const start = html.indexOf(marker);
  assert.ok(start !== -1, '6: регион ' + marker);
  return html.slice(start, start + span);
}
const regions = regionOf('data-direct-l1-planner', 2600)
  + regionOf('data-direct-autonomous-semantics', 1600)
  + regionOf('data-l1-durable-axes', 1600);
assert.ok(!/include_prompt/.test(regions),
  '6/R17: include_prompt только у F8');
assert.ok(!/SENT_TEXT|final_prompt/.test(regions),
  '6/R17: без exact-промптов');

console.log('ASAP7-F2-DIRECT-UI-OK');
