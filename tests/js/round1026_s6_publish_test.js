'use strict';
/* S6 round1026 (ADR-1026-11 D6, §108–§112) — публикационная наблюдаемость
 * в существующем UI: маркеры `PUBLISH_*` в §110-фильтре «Саммари», понятные
 * подписи ошибок публикации и реальные статусы §112 (`execPublicationLabel`).
 *
 * Проверяем поведение (не grep): маркеры/`shownLogs`/формулировки и подписи
 * статусов; плюс adapter `fromExecution` — реальный `publicationStatus`
 * (нет данных → null, не 'gated').
 *
 * Запуск: node tests/js/round1026_s6_publish_test.js → S6-PUBLISH-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

// ── Минимальный stubbed-контекст (по образцу S7 log-summary теста) ─────────
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
const G = require(path.join(ROOT, 'web', 'static', 'execution_graph.js'));

// ── 1. §110: маркеры PUBLISH_* ловятся фильтром «Саммари» ──────────────────
{
  const ctx = { logSummaryMarkers: methods.logSummaryMarkers };
  const markers = methods.logSummaryMarkers.call(ctx);
  assert.ok(markers.indexOf('PUBLISH_') >= 0, 'маркер PUBLISH_ в фильтре');
  const lines = [
    'PUBLISH_RICH_START | run_id=x | chat_id=-1 | method=sendRichMessage',
    'PUBLISH_RICH_COMPLETE | run_id=x | chat_id=-1 | message_id=5',
    'PUBLISH_RICH_ERROR | run_id=x | code=RICH_MESSAGE_SEND_FAILED',
    'PUBLISH_TEXT_START | run_id=x | method=sendMessage',
    'PUBLISH_TEXT_COMPLETE | run_id=x | message_id=6',
    'PUBLISH_TEXT_ERROR | run_id=x | code=TEXT_FALLBACK_FAILED',
  ];
  lines.forEach(function (msg) {
    assert.ok(methods.isSummaryLog.call(ctx, { message: msg }),
      'маркер должен ловиться: ' + msg);
  });
  const logs = [
    { message: 'PUBLISH_TEXT_COMPLETE | run_id=x', level: 'INFO' },
    { message: 'heartbeat sample ok', level: 'INFO' },
  ];
  const shown = computed.shownLogs.call({
    logSummaryOnly: true, logs: logs,
    isSummaryLog: methods.isSummaryLog,
    logSummaryMarkers: methods.logSummaryMarkers,
  });
  assert.strictEqual(shown.length, 1, 'ON: публикационное событие видно');
  assert.ok(shown[0].message.indexOf('PUBLISH_TEXT_COMPLETE') >= 0);
}

// ── 2. §110: понятные формулировки ошибок публикации ──────────────────────
{
  const label = methods.summaryErrorLabel;
  const cases = [
    ['PUBLISH_RICH_ERROR | run_id=x | code=RICH_MESSAGE_SEND_FAILED',
      'Саммари: ошибка публикации (Rich)'],
    ['PUBLISH_TEXT_ERROR | run_id=x | code=TEXT_FALLBACK_FAILED',
      'Саммари: ошибка публикации (текст)'],
  ];
  cases.forEach(function (c) {
    assert.strictEqual(label.call({}, { message: c[0] }), c[1], c[0]);
  });
}

// ── 3. §112/D6: реальные подписи статусов публикации ──────────────────────
{
  const fn = computed.execPublicationLabel;
  assert.ok(fn, 'execPublicationLabel есть');
  assert.strictEqual(fn.call({}, 'published_rich'), 'опубликовано (статья)');
  assert.strictEqual(fn.call({}, 'published_text'), 'опубликовано (текст)');
  assert.strictEqual(fn.call({}, 'failed'), 'ошибка публикации');
  assert.strictEqual(fn.call({}, 'skipped'), 'не публиковалось');
  assert.strictEqual(fn.call({}, null), 'Нет данных');
  assert.strictEqual(fn.call({}, undefined), 'Нет данных');
  assert.notStrictEqual(fn.call({}, 'gated'), 'недоступна (гейт S6)');
}

// ── 4. Adapter: fromExecution — реальный publicationStatus (нет `gated`) ──
{
  const g = G.fromExecution({
    run_id: 'r1', publication_status: 'published_text', nodes: [
      { id: 'r1:publication', kind: 'publish', stageKey: 'publication',
        parentIds: [], status: 'ok', priceKnown: false, metrics: null,
        metadata: {} },
    ], edges: [],
  });
  assert.strictEqual(g.publicationStatus, 'published_text');
  assert.deepStrictEqual(g.nodes.map(function (n) { return n.kind; }),
    ['publish']);
  const empty = G.fromExecution({ run_id: 'r2', nodes: [] });
  assert.strictEqual(empty.publicationStatus, null, 'нет данных → null');
  assert.strictEqual(G.STEP_LABEL['publication'], 'Публикация');
}

// ── 5. Статика: viewer не переписан, маркер/подписи только аддитивны ──────
{
  assert.ok(APP.indexOf('toggleLogSummary: function') >= 0, 'чип сохранён');
  assert.ok(APP.indexOf('copyLogRow: function') >= 0, 'копирование сохранено');
  assert.ok(APP.indexOf('logText: function') >= 0, 'logText сохранён');
  assert.ok(APP.indexOf('недоступна (гейт S6)') < 0, 'нет S8-формулировки гейта');
  assert.ok(APP.indexOf('PUBLISH_RICH_ERROR') >= 0);
  assert.ok(APP.indexOf('PUBLISH_TEXT_ERROR') >= 0);
}

console.log('S6-PUBLISH-OK');
