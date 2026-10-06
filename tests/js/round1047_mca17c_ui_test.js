'use strict';
/* MCA-17c round 10.47 (ADR-1028-23, T-5180…T-5188/T-5190/T-5192 UI) —
 * поведенческий тест витрины наблюдаемости в СУЩЕСТВУЮЩЕЙ композиции.
 *
 * Проверяет:
 *   1) методы блока существуют + state-поля;
 *   2) deep link-парсер: `#/oversight?view=runs&run_id=X` (переживает F5,
 *      A54/T-5181);
 *   3) F14: severity сортируется ПО ЧИСЛОВОМУ ключу (не строково);
 *   4) A54: merge инцидентов/ранов без дублей по id, свежая версия строки
 *      побеждает; раскрытые узлы (mca17cRunOpen) при refresh не сбрасываются;
 *   5) честные подписи: silent → «валидное молчание»-семантика (succeeded),
 *      stalled — отдельный флаг, «пусто ≠ устарело» (F16), disabled с
 *      причиной, unknown ≠ провал/успех (A57), «эффект ещё не измерен»;
 *   6) экспорт очищенного trace — чистая сборка JSON БЕЗ fetch (D14/R17);
 *   7) L-3: unchanged-метка человекочитаема, raw различим;
 *   8) фуннель личности: три различных статуса, disabled → «нет данных»;
 *   9) структура index.html: маркеры data-mca17c, НЕТ нового маршрута
 *      (#/analytics), в новых блоках нет v-html (TH-7).
 *
 * Запуск: node tests/js/round1047_mca17c_ui_test.js
 *         → MCA17C-UI-OK
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
  history: { replaceState() {} },
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

// ── 0) методы/state существуют ──────────────────────────────────────────────
for (const name of ['oversightParseDeepLink', 'oversightApplyDeepLink',
  'oversightSetView', 'oversightRefreshView', 'oversightLoadProcesses',
  'mca17cProcessGroups', 'oversightProcessBadge', 'oversightDrillProcess',
  'oversightLoadRuns', 'oversightApplyRunFilters', 'oversightSetRunStatus',
  'oversightRunStatusLabel', 'oversightRunBadge', 'oversightFreshnessLabel',
  'oversightRunIsStale', 'oversightToggleRunNode', 'oversightOpenRun',
  'oversightCloseRun', 'oversightExportRunTrace', 'oversightDownloadRunTrace',
  'oversightJobAction', 'oversightSeveritySort', 'oversightSeverityLabel',
  'oversightMergeIncidents', 'oversightLoadIncidents', 'oversightPollIncidents',
  'oversightLoadFunnel', 'mca17cEffectState', 'oversightLoadLessons',
  'oversightLoadSelfModel', 'mca17cPersonaFunnel', 'oversightDeepReasonLabel',
  'oversightViewEnter', 'oversightLeave']) {
  assert.ok(methods[name], 'метод ' + name + ' есть');
}
const state = captured.data ? captured.data() : {};
for (const key of ['oversightView', 'mca17cProcesses', 'mca17cRuns',
  'mca17cRunF', 'mca17cRunDetail', 'mca17cRunOpen', 'mca17cIncidents',
  'mca17cIncCursor', 'mca17cFunnel', 'mca17cLessons', 'mca17cSelfModel']) {
  assert.ok(Object.prototype.hasOwnProperty.call(state, key),
    'state ' + key + ' есть');
}

const vm = Object.create(methods);
vm.toast = function () {};
vm.loreErrText = function (e) { return (e && e.detail) || 'ошибка'; };
vm.$nextTick = function (fn) { if (fn) fn(); };

// ── 1) deep link-парсер (T-5181: переживает обновление) ─────────────────────
{
  const link = methods.oversightParseDeepLink(
    '#/oversight?view=runs&run_id=abc123&status=failed&days=30');
  assert.strictEqual(link.view, 'runs');
  assert.strictEqual(link.params.run_id, 'abc123');
  assert.strictEqual(link.params.status, 'failed');
  assert.strictEqual(link.params.days, '30');
  const noQuery = methods.oversightParseDeepLink('#/oversight');
  assert.strictEqual(noQuery.view, null);
  const alien = methods.oversightParseDeepLink('#/status?view=runs');
  assert.strictEqual(alien.view, null);   // только внутри #/oversight
}

// ── 2) F14: severity — числовой порядок ─────────────────────────────────────
{
  const sorted = methods.oversightSeveritySort(
    [{ severity: '10' }, { severity: 2 }, { severity: 1 }, { severity: null }]);
  // null → Number(null)=0 (после числовых); строковая сортировка дала бы
  // 1,10,2 — проверяем именно числовой порядок
  assert.deepStrictEqual(sorted.map(function (x) { return Number(x.severity); }),
    [10, 2, 1, 0]);
}

// ── 3) A54: merge без дублей, свежая строка побеждает ───────────────────────
{
  const cur = [{ incident_id: 'a', severity: 1, count: 1 },
    { incident_id: 'b', severity: 3, count: 2 }];
  const inc = [{ incident_id: 'b', severity: 3, count: 5 },
    { incident_id: 'c', severity: 0, count: 1 }];
  const merged = methods.oversightMergeIncidents(cur, inc);
  assert.strictEqual(merged.length, 3);
  const b = merged.find(function (x) { return x.incident_id === 'b'; });
  assert.strictEqual(b.count, 5);        // обновлён, не задублирован
  assert.strictEqual(merged[0].incident_id, 'b');   // severity 3 сверху
}

// ── 4) честные статусы run (read-render контракта mca-17a) ──────────────────
{
  assert.strictEqual(methods.oversightRunStatusLabel('succeeded'), 'успешно');
  // silent — не отдельный статус списка: на событии даёт succeeded (см. API);
  // неизвестный код не маскируется (честный raw)
  assert.strictEqual(methods.oversightRunStatusLabel('weird'), 'weird');
  assert.strictEqual(methods.oversightRunBadge({ status: 'succeeded' }),
    'badge-ok');
  assert.strictEqual(methods.oversightRunBadge({ status: 'partial' }),
    'badge-warn');
  assert.strictEqual(methods.oversightRunBadge({ status: 'failed' }),
    'badge-err');
  // stalled — отдельный флаг, статус не подменяет
  assert.strictEqual(methods.oversightRunBadge({ status: 'running',
    stalled: true }), 'badge-info');
}

// ── 5) F16: «пусто ≠ устарело» + stale-детектор ─────────────────────────────
{
  assert.strictEqual(methods.oversightFreshnessLabel(null), 'нет данных');
  assert.strictEqual(methods.oversightFreshnessLabel(undefined), 'нет данных');
  const now = Math.floor(Date.now() / 1000);
  assert.ok(methods.oversightFreshnessLabel(now - 10).indexOf('10 с') >= 0);
  assert.strictEqual(methods.oversightRunIsStale(
    { status: 'running', updated_ts: now - 600 }), true);
  assert.strictEqual(methods.oversightRunIsStale(
    { status: 'running', updated_ts: now - 10 }), false);
  assert.strictEqual(methods.oversightRunIsStale(
    { status: 'failed', updated_ts: now - 600 }), false);
}

// ── 6) A54: раскрытые узлы не сбрасываются обновлением ──────────────────────
{
  vm.mca17cRunOpen = {};
  methods.oversightToggleRunNode.call(vm, '3:RUN_DONE');
  assert.strictEqual(vm.mca17cRunOpen['3:RUN_DONE'], true);
  // «обновление данных» не трогает mca17cRunOpen — эмулируем перезапись ранов
  vm.mca17cRuns = [{ pipeline_run_id: 'x' }];
  assert.strictEqual(vm.mca17cRunOpen['3:RUN_DONE'], true);
  methods.oversightToggleRunNode.call(vm, '3:RUN_DONE');
  assert.strictEqual(vm.mca17cRunOpen['3:RUN_DONE'], false);
}

// ── 7) экспорт очищенного trace — без fetch, только известные поля ──────────
{
  let fetchCalled = false;
  global.fetch = async function () { fetchCalled = true; };
  const run = {
    pipeline_run_id: 'r1', pipeline_type: 'summary.window',
    pipeline_version: '1', status: 'failed', stalled: false,
    started_ts: 1, updated_ts: 2, chat_id: -100500,
    component: 'summary', model: 'gpt-x', provider: 'openai',
    events: [{ event_name: 'E', outcome: 'failed', error_type: 'Timeout' }],
    usage_json: '{"secret_like":"x"}', source_ref_json: '{"raw":1}',
  };
  const payload = methods.oversightExportRunTrace.call(vm, run);
  assert.ok(payload && payload.run.pipeline_run_id === 'r1');
  assert.strictEqual(fetchCalled, false);   // D14: экспорт из полученного
  const str = JSON.stringify(payload);
  assert.ok(str.indexOf('usage_json') < 0, 'usage_json не экспортируется');
  assert.ok(str.indexOf('source_ref_json') < 0);
  assert.ok(str.indexOf('SECRET') < 0);
  global.fetch = async function () { throw new Error('no fetch in test'); };
}

// ── 8) A57: «Эффект» — honest, без выдуманного улучшения ────────────────────
{
  vm.mca17cFunnel = null;
  assert.strictEqual(methods.mca17cEffectState.call(vm).measured, false);
  vm.mca17cFunnel = { enabled: true,
    applications: { total: 0, success: 0, failure: 0, unknown: 0 } };
  let eff = methods.mca17cEffectState.call(vm);
  assert.strictEqual(eff.measured, false);
  assert.ok(eff.note.indexOf('ещё не измерен') >= 0);
  vm.mca17cFunnel = { enabled: true,
    applications: { total: 3, success: 0, failure: 0, unknown: 3,
      unique_lessons: 2 } };
  eff = methods.mca17cEffectState.call(vm);
  assert.strictEqual(eff.measured, false);   // unknown ≠ измеренный рост
  vm.mca17cFunnel = { enabled: true,
    applications: { total: 4, success: 3, failure: 1, unknown: 2,
      unique_lessons: 2 } };
  eff = methods.mca17cEffectState.call(vm);
  assert.strictEqual(eff.measured, true);
  assert.ok(eff.note.indexOf('unknown') >= 0);
}

// ── 9) фуннель личности: три различных статуса (D12) ────────────────────────
{
  vm.mca17cSelfModel = null;
  const off = methods.mca17cPersonaFunnel.call(vm);
  assert.strictEqual(off.enabled, false);
  vm.mca17cSelfModel = { enabled: true, frame_version: 'f1', version: 's2',
    stale: true,
    applied_now: [{ id: 1, dimension: 'd' }, { id: 2, dimension: 'd2' }],
    rejected_now: [{ id: 3, dimension: 'd3', reason: 'conflict' }] };
  const pf = methods.mca17cPersonaFunnel.call(vm);
  assert.strictEqual(pf.stages.length, 3);
  assert.ok(pf.stages[0].label.indexOf('передано') >= 0);
  assert.ok(pf.stages[1].label.indexOf('проявилось') >= 0);
  assert.ok(pf.stages[2].label.indexOf('эффект') >= 0);
  assert.notStrictEqual(pf.stages[0].value, pf.stages[1].value);
  assert.ok(pf.stages[1].value.indexOf('конфликт') >= 0); // причина видна
  assert.strictEqual(pf.stale, true);
}

// ── 10) L-3: unchanged-метка человекочитаема ────────────────────────────────
{
  assert.strictEqual(methods.oversightDeepReasonLabel('unchanged'),
    'без изменений');
  assert.strictEqual(methods.oversightDeepReasonLabel('budget_skip'),
    'пропущено по бюджету');
  // raw различим: неизвестный код не маскируется
  assert.strictEqual(methods.oversightDeepReasonLabel('weird_raw'),
    'weird_raw');
}

// ── 11) честный бейдж процессов (K-OFF/заготовка — не нули) ─────────────────
{
  assert.strictEqual(methods.oversightProcessBadge('disabled').label,
    'выключен');
  assert.strictEqual(methods.oversightProcessBadge('not_implemented').label,
    'заготовка (запусков нет)');
  assert.strictEqual(methods.oversightProcessBadge('not_run').label,
    'не запускался');
}

// ── 12) группировка карточек по widget_id (D2) + клиентский фильтр ─────────
{
  vm.mca17cProcesses = { processes: [
    { process_id: 'a.run', widget_id: 'Опыт и уроки', status: 'implemented',
      purpose: 'п', owner_feature: 'mca-16', settings_ref: ['MCA_X_ENABLED'] },
    { process_id: 'b.run', widget_id: 'Опыт и уроки', status: 'disabled',
      purpose: 'п2', owner_feature: 'mca-16', settings_ref: [] },
    { process_id: 'c.run', widget_id: 'Другое', status: 'not_run',
      purpose: 'п3', owner_feature: '', settings_ref: [] },
  ] };
  vm.mca17cProcessQuery = '';
  vm.mca17cProcessStatus = '';
  const groups = methods.mca17cProcessGroups.call(vm);
  assert.strictEqual(groups.length, 2);
  const exp = groups.find(function (g) {
    return g.widget_id === 'Опыт и уроки';
  });
  assert.ok(exp, 'группа «Опыт и уроки» есть');
  assert.strictEqual(exp.items.length, 2);
  vm.mca17cProcessStatus = 'disabled';
  assert.strictEqual(methods.mca17cProcessGroups.call(vm).length, 1);
  vm.mca17cProcessStatus = '';
  vm.mca17cProcessQuery = 'b.run';
  assert.strictEqual(methods.mca17cProcessGroups.call(vm)[0].items.length, 1);
  // гейт из settings_ref — честная причина выключения
  assert.strictEqual(methods.mca17cProcessGate.call(vm,
    { settings_ref: ['A', 'MCA_X_ENABLED'] }), 'MCA_X_ENABLED');
}

// ── 13) структура index.html: маркеры/без нового маршрута/без v-html ───────
{
  const html = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf-8');
  for (const marker of ['data-mca17c="root"', 'data-mca17c="processes"',
    'data-mca17c="runs"', 'data-mca17c="runs-list"', 'data-mca17c="incidents"',
    'data-mca17c="learning"', 'data-mca17c="funnel"',
    'data-mca17c="persona-funnel"', 'data-mca17c="effect"',
    'tab-processes', 'tab-runs', 'tab-incidents', 'tab-learning']) {
    assert.ok(html.indexOf(marker) >= 0, 'index.html: ' + marker + ' есть');
  }
  assert.ok(html.indexOf('#/analytics') < 0,
    'нового маршрута #/analytics НЕТ (REUSE #/oversight)');
  // v-html в новом блоке запрещён (TH-7): вырезаем блок data-mca17c="root"
  const start = html.indexOf('data-mca17c="root"');
  assert.ok(start > 0);
  const tail = html.slice(start, start + 22000);
  assert.ok(tail.indexOf('v-html') < 0, 'в новых блоках нет v-html');
  // секция «общесерверный» — граница scope (`:1370`)
  assert.ok(tail.indexOf('общесерверный') >= 0);
}

// ── 14) app.js: без нового верхнеуровневого маршрута аналитики ─────────────
{
  const appjs = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf-8');
  assert.ok(appjs.indexOf("'#/analytics'") < 0,
    'нового маршрута #/analytics в app.js нет');
  // интеграция в setTab: deep link + вход/выход
  assert.ok(appjs.indexOf('oversightApplyDeepLink()') >= 0);
  assert.ok(appjs.indexOf('this.oversightLeave()') >= 0);
}

console.log('MCA17C-UI-OK');
