'use strict';
/* S7 round1026 (ADR-1026-9 D4, §110) — клиентский фильтр-чип «Саммари»
 * в СУЩЕСТВУЮЩЕМ log viewer (без нового endpoint/routes.py).
 *
 * Проверяем поведение (не grep): маркеры событий §108/§109, отображаемый
 * список `shownLogs`, понятные формулировки ошибок, переключение уровня
 * (ON → INFO, OFF → прежний), сохранность раскрытия/копирования и разметки.
 *
 * Запуск: node tests/js/round1026_s7_log_summary_filter_test.js
 *         → S7-LOG-SUMMARY-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

// ── Минимальный stubbed-контекст (по образцу round1025_f11_log_counts_test.js)
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
const computed = captured.computed || {};
const APP = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');

// ── 1. Маркеры событий Саммари ─────────────────────────────────────────────
{
  assert.ok(methods.logSummaryMarkers, '§110: logSummaryMarkers есть');
  assert.ok(methods.isSummaryLog, '§110: isSummaryLog есть');
  const ctx = { logSummaryMarkers: methods.logSummaryMarkers };
  const markers = [
    'SUMMARY_START | run_id=x', 'SUMMARY_COMPLETE | run_id=x',
    'SUMMARY_FAILED | run_id=x', 'FILTER_COMPLETE | run_id=x',
    'RESTORE_ERROR | run_id=x', 'L1_COMPLETE | run_id=x',
    'L2_ERROR | run_id=x', 'FORMAT_START | run_id=x',
    'COVER_COMPLETE | run_id=x', 'TEST_WINDOW_EMPTY | run_id=x',
    'L2_SKIPPED | run_id=abc',
  ];
  markers.forEach(function (msg) {
    assert.ok(methods.isSummaryLog.call(ctx, { message: msg }),
      'маркер должен ловиться: ' + msg);
  });
  assert.ok(!methods.isSummaryLog.call(ctx, { message: 'heartbeat sample ok' }),
    'чужой лог не проходит фильтр');
  assert.ok(!methods.isSummaryLog.call(ctx, { message: '' }),
    'пустая строка не проходит');
}

// ── 2. shownLogs: OFF → passthrough, ON → только Саммари ───────────────────
{
  assert.ok(computed.shownLogs, '§110: computed shownLogs есть');
  const logs = [
    { message: 'SUMMARY_START | run_id=x', level: 'INFO' },
    { message: 'heartbeat sample ok', level: 'INFO' },
    { message: 'L1_ERROR | run_id=x', level: 'ERROR' },
  ];
  let out = computed.shownLogs.call({
    logSummaryOnly: false, logs: logs,
    isSummaryLog: methods.isSummaryLog,
    logSummaryMarkers: methods.logSummaryMarkers,
  });
  assert.strictEqual(out, logs, 'OFF: исходный список без копии/фильтра');
  out = computed.shownLogs.call({
    logSummaryOnly: true, logs: logs,
    isSummaryLog: methods.isSummaryLog,
    logSummaryMarkers: methods.logSummaryMarkers,
  });
  assert.strictEqual(out.length, 2, 'ON: только события Саммари');
  assert.ok(out[0].message.indexOf('SUMMARY_START') >= 0);
  assert.ok(out[1].message.indexOf('L1_ERROR') >= 0);
  // Уровне-фильтр/счётчики считаются по полному this.logs (не сломаны).
  assert.ok(computed.errorLogs && computed.warnLogs, 'счётчики сохранены');
  const errors = computed.errorLogs.call({ logs: logs });
  assert.strictEqual(errors.length, 1, 'ERROR-счётчик по полному списку');
}

// ── 3. Понятные формулировки ошибок (§110) ────────────────────────────────
{
  const label = methods.summaryErrorLabel;
  assert.ok(label, '§110: summaryErrorLabel есть');
  const cases = [
    ['L1_ERROR | run_id=x | reason=llm_error', 'Саммари: ошибка кластеризации'],
    ['L2_ERROR | run_id=x | reason=invalid', 'Саммари: ошибка генерации статьи'],
    ['FORMAT_ERROR | run_id=x | reason=RuntimeError', 'Саммари: ошибка форматирования'],
    ['COVER_ERROR | run_id=x | provider=h', 'Саммари: ошибка обложки'],
    ['FILTER_ERROR | run_id=x', 'Саммари: ошибка фильтра'],
    ['RESTORE_ERROR | run_id=x', 'Саммари: ошибка восстановления контекста'],
    ['SUMMARY_FAILED | run_id=x | stage=l2', 'Саммари: прогон не удался'],
  ];
  cases.forEach(function (c) {
    assert.strictEqual(label.call({}, { message: c[0] }), c[1], c[0]);
  });
  assert.strictEqual(label.call({}, { message: 'heartbeat' }), '',
    'не-Саммари строка без формулировки');
}

// ── 4. toggleLogSummary: ON → INFO, OFF → прежний уровень ─────────────────
{
  assert.ok(methods.toggleLogSummary, '§110: toggleLogSummary есть');
  let reloads = 0;
  const ctx = {
    logSummaryOnly: false, logLevel: 'ERROR+WARNING',
    logLevelBeforeSummary: null,
    loadLogs: function () { reloads += 1; },
  };
  methods.toggleLogSummary.call(ctx);
  assert.strictEqual(ctx.logSummaryOnly, true, 'ON');
  assert.strictEqual(ctx.logLevel, 'INFO', 'ON → INFO (события этапов видны)');
  assert.strictEqual(reloads, 0, 'смена уровня → watcher перезагрузит');
  methods.toggleLogSummary.call(ctx);
  assert.strictEqual(ctx.logSummaryOnly, false, 'OFF');
  assert.strictEqual(ctx.logLevel, 'ERROR+WARNING', 'OFF → прежний уровень');
  // Уровень уже INFO: переключение не теряет текущий уровень и грузит сразу.
  const ctx2 = {
    logSummaryOnly: false, logLevel: 'INFO', logLevelBeforeSummary: null,
    loadLogs: function () { reloads += 1; },
  };
  methods.toggleLogSummary.call(ctx2);
  assert.strictEqual(ctx2.logLevel, 'INFO', 'уровень не менялся');
  assert.strictEqual(reloads, 1, 'без смены уровня → loadLogs()');
  // L-R1026S7-2: ручная смена уровня при активном чипе сохраняется при OFF
  // (не возвращаем «до-чиповый» уровень неожиданно).
  const ctx3 = {
    logSummaryOnly: false, logLevel: 'ERROR+WARNING',
    logLevelBeforeSummary: null,
    loadLogs: function () { reloads += 1; },
  };
  methods.toggleLogSummary.call(ctx3);              // ON → INFO
  assert.strictEqual(ctx3.logLevel, 'INFO', 'ON → INFO');
  ctx3.logLevel = 'ERROR';                          // ручной выбор при чипе
  methods.toggleLogSummary.call(ctx3);              // OFF
  assert.strictEqual(ctx3.logSummaryOnly, false, 'OFF после ручной смены');
  assert.strictEqual(ctx3.logLevel, 'ERROR',
    'L-R1026S7-2: текущий выбор пользователя сохранён');
  assert.ok(APP.indexOf("logLevel: function () {\n        this.loadLogs();") >= 0,
    'watcher logLevel сохранён');
}

// ── 5. Раскрытие/копирование/viewer не переписаны ─────────────────────────
{
  assert.ok(APP.indexOf('copyLogRow: function') >= 0, 'копирование строки сохранено');
  assert.ok(APP.indexOf('copyAllLogs: function') >= 0, 'копирование всех сохранено');
  assert.ok(APP.indexOf('logText: function') >= 0, 'logText сохранён');
  assert.ok(INDEX.indexOf('log.expanded = !log.expanded') >= 0,
    'раскрытие стека сохранено');
  assert.ok(INDEX.indexOf('toggleLogSummary()') >= 0, 'чип «Саммари» в viewer');
  assert.ok(INDEX.indexOf('shownLogs') >= 0, 'рендер по shownLogs');
  assert.ok(INDEX.indexOf('summaryErrorLabel(log)') >= 0,
    'понятная формулировка в раскрываемой строке');
  assert.ok(INDEX.indexOf('показано {{ shownLogs.length }} из {{ logsCount }}') >= 0,
    'счётчик показанных строк');
  // Без нового endpoint: используется существующий /api/status/logs.
  assert.ok(APP.indexOf("'/api/status/logs?level='") >= 0,
    'существующий endpoint логов');
  assert.ok(INDEX.indexOf('source=summary') < 0,
    'нового query-параметра/endpoint нет');
  assert.ok(INDEX.indexOf('log-chip') >= 0, 'класс чипа в разметке');
  const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
  assert.ok(CSS.indexOf('.btn-ghost.log-chip.active') >= 0,
    'стиль активного чипа (без переписывания viewer)');
}

console.log('S7-LOG-SUMMARY-OK');
