'use strict';
/* ASAP 4.1 волна 7 (зона G: T-4621/T-4622/T-4623) — JS unit-тест Inspector
 * карточек (реальная логика web/app.js + разметка web/index.html).
 *
 * Проверяет:
 *  (1) computed'ы существуют и читаются как свойства (урок H-ASAP31-2);
 *  (a) §38 honest coverage: L1 failed НЕ смешивается с source 100% —
 *      отдельные строки, state='failed' у L1 при полном источнике;
 *  (b) §39 capacity-карточка: provider/model/effective window/serialized
 *      input/output reserve/mode + человеческая причина, числа с пробелами;
 *  (c) §40 liveness: строки «жива/завершена/ждёт», честный sync-режим
 *      (не «stream ✓» при sync-транспорте);
 *  (d) §41 cover style: base ✓/✕, style/provider/model, capability,
 *      Published = styled|base_fallback|no_cover + точная причина RU;
 *  (e) разметка index.html: блоки карточек + подпись «Покрытие источника
 *      — по стадиям» (+ отсутствие слияния единой coverage-строкой);
 *  (f) R17: в блоке зоны G нет ключей/секретов.
 *
 * Запуск: node tests/js/asap41_zone_g_inspector_test.js
 *          → ZONE-G-INSPECTOR-OK
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

// fmt helpers, используемые computed'ами зоны G.
assert.strictEqual(methods.pctLabel(87.5), '87.5%');
assert.strictEqual(methods.pctLabel(null), '—');

function withView(run) {
  var ctx = { pipelineData: run ? { run } : null,
              pipelineSelectedRunId: '' };
  // Методы Vue-компонента — на this (как в прод-инстансе); тест-контекст
  // подмешивает fmt-хелперы, чтобы computed вызывался как в рантайме.
  ctx.pctLabel = methods.pctLabel;
  ctx.fmtSec = methods.fmtSec;
  ctx.pipelineRunView = computed.pipelineRunView.call(ctx);
  ctx.pipelineBusy = false;
  ctx.pipelineMode = 'latest';
  return ctx;
}

// (1) computed'ы существуют — читаются шаблоном как свойства.
['pipelineCoverageRows', 'pipelineCapacityCard',
 'pipelineLivenessRows', 'pipelineCoverStyleCard'].forEach(function (name) {
  assert.strictEqual(typeof computed[name], 'function', '1: computed ' + name);
});

// Fixture-данные — shape ответа /api/analytics/pipeline/inspector
// (T-4621: L1 failed; source 839/839 100%).
const RUN_L1_FAILED = {
  run_id: 'run-g1',
  coverage: { total: 839, considered: 839, percent: 100.0, full: true },
  coverage_breakdown: {
    source: { total: 839, considered: 839, percent: 100.0 },
    l1: { input_total: 839, input_mode: 'WHOLE_WINDOW',
          input_requests: 1, result: 'failed', map_degraded: false },
    writer: { total: 839, percent: 100.0, result: 'ok' },
    final: { total: 839, considered: 839, percent: 100.0 },
  },
  capacity: {
    provider: 'api.test.host', model: 'm1',
    effective_window: 400000, required_input_tokens: 96120,
    reserved_output_tokens: 4000,
    mode: 'WHOLE_WINDOW', mode_ru: 'один запрос на всё окно',
    reason: 'fits_effective_context',
    reason_ru: 'Полное окно вмещается в контекст модели — отправлено одним запросом.',
    window_source: 'runtime', window_source_ru: 'Обнаружено у работающего провайдера.',
    replans: 0, segments: null,
  },
  liveness: [
    { stage: 'l1', label: 'L1 · Структурирование', mode: 'sync',
      mode_ru: 'синхронный вызов (живой запрос)', status_ru: 'завершена',
      live: false, provider: 'api.test.host', model: 'm1' },
    { stage: 'l2', label: 'Writer · Писатель', mode: 'sync',
      mode_ru: 'синхронный вызов (живой запрос)', status_ru: 'жива',
      live: true, provider: 'api.test.host', model: 'm1',
      reason_ru: '' },
  ],
  cover_style: {
    base_cover_ok: true, selected_style: 'medved_press',
    style_provider: 'nano-gpt.com', style_model: 'painter-x',
    capability_edit: true, reference_assets: 2, style_edit_ok: true,
    result: 'styled', resolve_source_ru: 'наследование от глобального '
      + 'image-провайдера',
  },
  nodes: [],
};

const ctxG = withView(RUN_L1_FAILED);

// (a) §38: честные раздельные строки.
const covRows = computed.pipelineCoverageRows.call(ctxG);
assert.ok(Array.isArray(covRows), 'a: coverage rows массив');
const byKey = {};
covRows.forEach(function (r) { byKey[r.key] = r; });
assert.strictEqual(byKey.source.state, 'ok', 'a: source 100% — ok');
assert.ok(byKey.source.value.indexOf('839') >= 0, 'a: 839 в source');
assert.strictEqual(byKey.l1.state, 'failed',
  'a: L1 result=failed — ОТДЕЛЬНАЯ строка (не маскируется source 100%)');
assert.ok(byKey.l1.value.indexOf('не выполнено') >= 0,
  'a: честный человеческий результат L1');
assert.ok(!/\{\s*\{/.test(JSON.stringify(covRows)), 'a: без vue-мусора');
assert.ok(byKey.final.value.indexOf('100%') >= 0, 'a: финальнаяcoverage');
assert.ok(byKey.writer.total_undefined !== true, 'a: writer строка есть');

// (a2) overflow-строка (segments 4/4 + covered 839/839).
ctxG.pipelineRunView.coverage_breakdown.overflow = {
  segments: 4, segments_failed: 0, messages_covered: 839,
  messages_total: 839, lossless: true };
const rowsOv = computed.pipelineCoverageRows.call(ctxG);
const ov = rowsOv.filter(function (r) { return r.key === 'overflow'; })[0];
assert.ok(ov, 'a2: overflow строка есть');
assert.ok(ov.value.indexOf('сегментов') >= 0, 'a2: сегменты названы');
assert.ok(ov.value.indexOf('839 / 839') >= 0
  || ov.value.indexOf('839') >= 0, 'a2: covered числа');
assert.strictEqual(ov.state, 'ok', 'a2: без падений → ok');
// упавший сегмент → warn (честный degraded).
ctxG.pipelineRunView.coverage_breakdown.overflow.segments_failed = 1;
assert.strictEqual(
  computed.pipelineCoverageRows.call(ctxG)
    .filter(function (r) { return r.key === 'overflow'; })[0].state,
  'warn', 'a2: failed-сегмент → warn не ok');

// (b) §39: capacity-карточка.
const cap = computed.pipelineCapacityCard.call(ctxG);
assert.ok(cap, 'b: capacity карта');
assert.strictEqual(cap.provider, 'api.test.host');
assert.strictEqual(cap.model, 'm1');
assert.strictEqual(cap.effective_window, '400 000', 'b: пробелы чисел');
assert.strictEqual(cap.required_input_tokens, '96 120');
assert.strictEqual(cap.reserved_output_tokens, '4 000');
assert.strictEqual(cap.mode, 'WHOLE_WINDOW');
assert.ok(cap.reason_ru.indexOf('окно') >= 0, 'b: человеческая причина');
assert.ok(cap.window_source_ru, 'b: источник окна (§5-цепочка)');
assert.strictEqual(cap.replans, 0, 'b: replans null→0');

// (c) §40: liveness — честные режимы («синхронн», не stream).
const lv = computed.pipelineLivenessRows.call(ctxG);
assert.ok(Array.isArray(lv) && lv.length >= 2, 'c: liveness rows');
lv.forEach(function (row) {
  assert.ok(/синхрон/.test(row.mode) || /стрим/.test(row.mode)
    || /фонов/.test(row.mode), 'c: человеческий режим: ' + row.mode);
});
assert.strictEqual(lv[0].live, false, 'c: завершённая стадия не live');
assert.strictEqual(lv[1].live, true, 'c: живая стадия live=true');
assert.ok(lv[1].status_ru.indexOf('жива') >= 0, 'c: честный «жива»');

// (c2) без liveness-данных — пустой список (не выдумка).
assert.deepStrictEqual(
  computed.pipelineLivenessRows.call(withView({ run_id: 'r2' })), [],
  'c2: нет данных → пустая витрина');

// (d) §41: cover style карточка.
const cs = computed.pipelineCoverStyleCard.call(ctxG);
assert.ok(cs, 'd: cover style карта');
assert.strictEqual(cs.base_cover, '✓');
assert.strictEqual(cs.capability_edit, '✓');
assert.strictEqual(cs.style_edit, '✓');
assert.strictEqual(cs.result, 'styled');
assert.ok(cs.result_ru.indexOf('styled') >= 0
  || cs.result_ru.indexOf('стиль') >= 0, 'd: человеческий результат');
assert.strictEqual(cs.selected_style, 'medved_press');
// base_fallback ✕ + точная причина.
ctxG.pipelineRunView.cover_style = {
  base_cover_ok: true, selected_style: 'medved_press',
  style_provider: 'nano-gpt.com', style_model: 'painter-old',
  capability_edit: false, reference_assets: 2, style_edit_ok: false,
  result: 'base_fallback', fallback_reason: 'edit_unsupported',
  fallback_reason_ru: 'Модель не умеет редактировать готовые изображения.',
};
const cs2 = computed.pipelineCoverStyleCard.call(ctxG);
assert.strictEqual(cs2.base_cover, '✓', 'd2: base обложка есть');
assert.strictEqual(cs2.style_edit, '✕', 'd2: style edit провалился');
assert.strictEqual(cs2.capability_edit, '✕');
assert.strictEqual(cs2.result, 'base_fallback');
assert.ok(cs2.fallback_reason_ru && cs2.fallback_reason_ru.length > 8,
  'd2: точная причина fallback, не generic');
// сбой base: published no_cover.
ctxG.pipelineRunView.cover_style = {
  base_cover_ok: false, result: 'no_cover' };
const cs3 = computed.pipelineCoverStyleCard.call(ctxG);
assert.strictEqual(cs3.base_cover, '✕', 'd3: base failed → ✕');
assert.strictEqual(cs3.result, 'no_cover');

// (d4) нет карточки — null (не «пустая» выдумка).
assert.strictEqual(
  computed.pipelineCoverStyleCard.call(withView(null)), null,
  'd4: нет run → null');
assert.strictEqual(
  computed.pipelineCapacityCard.call(withView({})), null,
  'd4: нет capacity-данных → null');

// (e) разметка index.html: блоки зоны G присутствуют.
const INDEX = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
[[
  'pipelineCoverageRows.length', '(e) coverage breakdown подписка'],
  ['Покрытие источника — по стадиям', '(e) подпись карточки покрытия'],
  ['pipeline-capacity-card', '(e) id capacity-карточки'],
  ['Контекст модели', '(e) заголовок capacity-карточки'],
  ['Serialized input', '(e) Serialized input (§39)'],
  ['Output reserve', '(e) Output reserve (§39)'],
  ['pipeline-liveness-card', '(e) id liveness-карточки'],
  ['Активность стадий', '(e) заголовок liveness-карточки'],
  ['pipeline-cover-style-card', '(e) id cover style'],
  ['Reference assets', '(e) Reference assets (§41)'],
  ['Published cover', '(e) Published cover (§41)'],
  ['Capability image-edit', '(e) capability image-edit (§41)'],
  ['Обложка — отдельная ветка', '(e) ветка обложки — существующая (§61.8)'],
].forEach(function (pair) {
  assert.ok(INDEX.indexOf(pair[0]) >= 0, pair[1] + ' (' + pair[0] + ')');
});

// (f) R17: в зоне-блоках нет ключей/секретов.
const startG = INDEX.indexOf('pipeline-inspector-block');
const endG = INDEX.indexOf('embeddings-inspector-block');
assert.ok(startG > 0 && endG > startG, 'f: границы блока');
const zoneHtml = INDEX.slice(startG, endG + 800);
['api_key', 'apikey', 'secret_value', 'credential_value'].forEach(
  function (bad) {
    assert.ok(zoneHtml.toLowerCase().indexOf(bad) < 0, 'f: нет ' + bad);
  });

console.log('ZONE-G-INSPECTOR-OK');
