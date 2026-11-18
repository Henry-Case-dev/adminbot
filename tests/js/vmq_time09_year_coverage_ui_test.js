'use strict';
/* VMQ-TIME-09 — unit-тест UI «покрытие памяти по годам» (per-run).
 *
 * Проверяет ЧИСТУЮ арифметику helper'а `web/static/status-analytics.js`
 * (UMD, как execution_graph.js/cognitive-map.js) и render-маркеры
 * `web/index.html`:
 *
 *  * годы: сортировка, отбрасывание мусора, текст `2023 — 2 · 2026 — 7`;
 *    измеренный пустой словарь → «нет фактов», отсутствие данных →
 *    «нет данных» (ноль ≠ неизвестно);
 *  * исключения: закрытый набор из пяти категорий в фиксированном порядке,
 *    отсутствующие категории = 0; `excluded_present=false` → нет данных,
 *    все нули при present=true → «исключений не было»;
 *  * Writer-блоки: только rag/episode; `rendered=false` НЕ «дошло» и
 *    сохраняет `skip_reason`; global_tail/global_middle — история чата,
 *    не память;
 *  * primary run — первый НЕ-периодный (не `runs[0]`/последний);
 *    latestRun — максимум `ts` (stale run не выдаётся за текущий);
 *  * view: состояния ready/empty/no_chat/no_selection/truncated/
 *    no_retrieval/error; нигде нет процентов/доната/KPI;
 *  * в блоках Статуса/Аналитики нет canvas/svg-графика;
 *  * app.js НЕ обращается к aggregate `/api/memory/retrieval-coverage`.
 *
 * Запуск: node tests/js/vmq_time09_year_coverage_ui_test.js
 *         (ожидаемый вывод: VMQ-TIME09-UNIT-OK)
 * TEST-LIFECYCLE: CONTRACT owner=VMQ-TIME-09 (slice vmq-time09)
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

function loadHelper() {
  const file = path.join(ROOT, 'web', 'static', 'status-analytics.js');
  assert.ok(fs.existsSync(file),
    'web/static/status-analytics.js обязателен для VMQ-TIME-09');
  return require(file);
}

function read(file) {
  return fs.readFileSync(path.join(ROOT, file), 'utf8');
}

function blockWindow(html, marker, endMarker, size) {
  const start = html.indexOf(marker);
  assert.ok(start >= 0, 'render-маркер отсутствует: ' + marker);
  let end = html.length;
  if (endMarker) {
    const stop = html.indexOf(endMarker, start);
    assert.ok(stop > start, 'конец блока не найден: ' + endMarker);
    end = stop;
  }
  return html.slice(start, Math.min(end, start + (size || 12000)));
}

function hasPercent(text) {
  return String(text).indexOf('%') >= 0;
}

function main() {
  const A = loadHelper();
  assert.ok(A && typeof A === 'object', 'helper должен экспортировать объект');
  ['sortedYears', 'yearsText', 'exclusionRows', 'exclusionText',
    'writerBlocks', 'primaryRun', 'latestRun', 'sortRuns', 'view',
  ].forEach(function (name) {
    assert.strictEqual(typeof A[name], 'function', 'нет функции ' + name);
  });
  assert.ok(Array.isArray(A.EXCLUSION_KEYS), 'EXCLUSION_KEYS обязателен');
  assert.deepStrictEqual(A.EXCLUSION_KEYS,
    ['policy_operative', 'status', 'expired', 'relevance', 'budget']);

  // ── годы: сортировка/мусор/текст ────────────────────────────────────────
  assert.deepStrictEqual(A.sortedYears({ '2026': 7, '2023': 2 }),
    [{ year: 2023, count: 2 }, { year: 2026, count: 7 }]);
  const junk = A.sortedYears({
    '0': 5, '-1': 4, 'abc': 3, '2024': '2', '2025': -3, '2026': null,
  });
  assert.deepStrictEqual(junk, [{ year: 2024, count: 2 }],
    'мусорные годы/счётчики отбрасываются, а не превращаются в 0: '
    + JSON.stringify(junk));
  assert.strictEqual(A.yearsText({ '2026': 7, '2023': 2 }),
    '2023 — 2 · 2026 — 7');
  assert.strictEqual(A.yearsText({}), 'нет фактов',
    'измеренный пустой набор — «нет фактов» (не процент)');
  assert.strictEqual(A.yearsText(null), 'нет данных',
    'отсутствие данных — «нет данных», не 0');

  // ── исключения: закрытый набор пяти категорий ──────────────────────────
  const rows = A.exclusionRows({ budget: 1, status: 3 }, true);
  assert.deepStrictEqual(rows.map(function (r) { return r.key; }),
    ['policy_operative', 'status', 'expired', 'relevance', 'budget'],
    'фиксированный порядок пяти категорий');
  assert.deepStrictEqual(rows.map(function (r) { return r.count; }),
    [0, 3, 0, 0, 1], 'отсутствующие в событии категории = 0');
  assert.strictEqual(rows[0].label, 'квота оперативного набора');
  assert.strictEqual(A.exclusionRows({}, false), null,
    'excluded_present=false — нет данных, а не пять нулей');
  assert.strictEqual(A.exclusionText({}, false), 'нет данных');
  assert.strictEqual(A.exclusionText({}, true), 'исключений не было',
    'измеренный пустой набор — «исключений не было», не пять нулей');
  assert.strictEqual(
    A.exclusionText({ policy_operative: 4, status: 3, expired: 0,
      relevance: 1, budget: 2 }, true),
    'квота 4 · статус 3 · давность 0 · релевантность 1 · бюджет 2');

  // ── Writer-блоки: rendered=false не доставлено ─────────────────────────
  const skipped = A.writerBlocks([
    { kind: 'rag', rendered: false, skip_reason: 'budget', years: {},
      years_present: true },
  ]);
  assert.ok(skipped.facts, 'Writer-блок rag обязан быть виден');
  assert.strictEqual(skipped.facts.delivered, false,
    'rendered=false не считается доставленным до Writer');
  assert.strictEqual(skipped.facts.skipReason, 'budget',
    'skip_reason сохраняется для честной причины');
  assert.strictEqual(skipped.facts.yearsText, 'нет фактов');
  assert.strictEqual(skipped.episodes, null);
  const delivered = A.writerBlocks([
    { kind: 'global_tail', rendered: true, years: { '2023': 9 } },
    { kind: 'global_middle', rendered: true, years: { '2024': 4 } },
    { kind: 'rag', rendered: true, years: { '2023': 2, '2026': 7 },
      years_present: true },
    { kind: 'episode', rendered: true, years: { '2023': 1 },
      years_present: true },
  ]);
  assert.strictEqual(delivered.facts.delivered, true);
  assert.strictEqual(delivered.facts.yearsText, '2023 — 2 · 2026 — 7');
  assert.strictEqual(delivered.episodes.yearsText, '2023 — 1',
    'эпизоды — отдельная строка, не смешиваются с фактами');
  assert.strictEqual(delivered.ignoredHistory, 2,
    'global_tail/global_middle — история чата, не память');
  assert.deepStrictEqual(A.writerBlocks([]),
    { facts: null, episodes: null, ignoredHistory: 0 });

  // ── primary/latest run ─────────────────────────────────────────────────
  const runs = [{ ts: 300, period: false }, { ts: 100, period: false }];
  assert.strictEqual(A.primaryRun(runs).ts, 300,
    'primaryRun — первый, а не последний элемент');
  assert.strictEqual(A.latestRun(runs).ts, 300,
    'latestRun — максимум ts, а не порядок массива');
  assert.strictEqual(A.latestRun([{ ts: 100 }, { ts: 300 }]).ts, 300);
  assert.strictEqual(A.primaryRun(
    [{ ts: 50, period: true }, { ts: 40, period: false }]).ts, 40,
    'primary — первый НЕ-периодный вызов, не runs[0]');
  assert.strictEqual(A.primaryRun([{ ts: 5, period: true }]).period, true,
    'если не-периодных нет — первый (периодный) как есть');
  assert.deepStrictEqual(A.sortRuns([{ ts: 9 }, { ts: 3 }]).map(function (r) {
    return r.ts;
  }), [3, 9]);

  // ── view: состояния и отсутствие процентов ─────────────────────────────
  const basePayload = {
    available: true,
    trace_id: 'trace-1',
    ts: 1795000000,
    selection: {
      policy_version: 'alloc_v3',
      blocks: [
        { kind: 'rag', rendered: true, years: { '2023': 2, '2026': 7 },
          years_present: true },
        { kind: 'episode', rendered: true, years: { '2023': 1 },
          years_present: true },
      ],
      memory_period: { policy: 'auto', period_skipped: 'auto_no_replace',
        pool: 12, kept: 3, dropped_status: 1, pool_expired: 0,
        dropped_budget: 2, dropped_out_of_target_year: 0,
        dropped_unknown_year: 0 },
      truncated: false,
    },
    retrieval: [
      { ts: 1795000001, outcome: 'success', reason_code: 'episodes_used',
        policy: 'auto', period: false, years: { '2023': 2, '2026': 8 },
        years_present: true,
        excluded: { policy_operative: 4, status: 3, expired: 0,
          relevance: 1, budget: 2 }, excluded_present: true },
      { ts: 1795000002, outcome: 'success', reason_code: null,
        policy: 'auto', period: true, years: { '2023': 1 },
        years_present: true,
        excluded: { budget: 1 }, excluded_present: true },
    ],
  };
  const ready = A.view(basePayload);
  assert.strictEqual(ready.state, 'ready');
  assert.strictEqual(ready.runs.length, 2);
  assert.strictEqual(ready.primary.period, false,
    'Status показывает основной вызов, а не периодный добор');
  assert.strictEqual(ready.writer.facts.yearsText, '2023 — 2 · 2026 — 7',
    'годы Writer-фактов видны в Статусе');
  assert.ok(ready.primary.exclusionText.indexOf('квота 4') >= 0,
    'исключения основного вызова видны в Статусе');
  assert.strictEqual(ready.writer.episodes.yearsText, '2023 — 1',
    'эпизоды — отдельная строка, не смешиваются с фактами');
  assert.strictEqual(ready.extraRuns, 1,
    'второй вызов хода не теряется: в Аналитике он отдельной строкой');

  assert.strictEqual(A.view({ no_chat: true }).state, 'no_chat');
  assert.ok(A.view({ no_chat: true }).text.indexOf('Выберите чат') >= 0);
  assert.strictEqual(A.view({ error: 'timeout' }).state, 'error');
  assert.ok(A.view({ error: 'timeout' }).text.indexOf('timeout') >= 0);
  const noTurns = A.view({ available: false, reason: 'no_turn_traces' });
  assert.strictEqual(noTurns.state, 'empty');
  assert.ok(noTurns.text.indexOf('Ходов этого чата ещё нет') >= 0);
  assert.strictEqual(A.view({ available: true, selection: null }).state,
    'no_selection');
  const truncated = A.view({
    available: true, selection: { truncated: true, blocks: [] },
    retrieval: [],
  });
  assert.strictEqual(truncated.state, 'truncated');
  assert.ok(truncated.limitations.join(' ').indexOf('усечена') >= 0,
    'усечение selection обязано быть предупреждением');
  assert.ok(truncated.writerNote.indexOf('не зафиксировано') >= 0,
    'отсутствующий блок при усечении — «не зафиксировано», не 0');
  const noRetrieval = A.view({
    available: true,
    selection: { blocks: [{ kind: 'rag', rendered: true,
      years: { '2023': 2 } }], truncated: false },
    retrieval: [],
  });
  assert.strictEqual(noRetrieval.state, 'no_retrieval');
  assert.ok(noRetrieval.text.indexOf('Событий retrieval') >= 0,
    'нет вызовов retrieval — честная причина, Writer-часть показана');
  assert.strictEqual(noRetrieval.writer.facts.delivered, true);

  // ── TIME-09 corrective R1: presence/unknown/zero, turn label (F1-F4) ───
  const f1 = A.view({
    available: true, selection: { blocks: [], truncated: false },
    retrieval: [
      { ts: 1, years: { '2023': 2 }, years_present: true,
        excluded: { budget: 1 }, excluded_present: true },
      { ts: 2, years: null, years_present: true,
        excluded: {}, excluded_present: true },
      { ts: 3, years: null, years_present: false,
        excluded: null, excluded_present: false },
    ],
  });
  assert.strictEqual(f1.runs[0].yearsPresent, true,
    'F1: view model обязан нести yearsPresent (его читает шаблон)');
  assert.strictEqual(f1.runs[0].yearsText, '2023 — 2');
  assert.strictEqual(f1.runs[1].yearsPresent, true);
  assert.strictEqual(f1.runs[1].yearsText, 'нет фактов',
    'F3: измеренный ноль — «нет фактов», не «нет данных»');
  assert.strictEqual(f1.runs[2].yearsPresent, false);
  assert.strictEqual(f1.runs[2].yearsText, 'нет данных');
  assert.strictEqual(f1.runs[0].excludedPresent, true);
  assert.strictEqual(f1.runs[2].excludedPresent, false);
  assert.strictEqual(f1.runs[2].exclusionText, 'нет данных',
    'F2: excluded_present=false — честное «нет данных»');
  assert.strictEqual(f1.runs[1].exclusionText, 'исключений не было');
  assert.strictEqual(f1.runs[0].emptyText, '');
  assert.strictEqual(f1.runs[1].emptyText, 'нет фактов');

  const f3 = A.writerBlocks([
    { kind: 'rag', rendered: true, years: null, years_present: true },
    { kind: 'episode', rendered: true, years: null,
      years_present: false },
  ]);
  assert.strictEqual(f3.facts.yearsText, 'нет фактов',
    'F3: Writer measured zero — «нет фактов»');
  assert.strictEqual(f3.episodes.yearsText, 'нет данных',
    'F3: Writer unknown — «нет данных»');

  const withReason = A.view({
    available: true, selection: { blocks: [], truncated: false },
    retrieval: [{ ts: 1, years: null, years_present: true,
      reason_code: 'retrieval_empty', excluded_present: true,
      excluded: {} }],
  });
  assert.ok(withReason.runs[0].emptyText.indexOf('retrieval_empty') >= 0,
    'B8: причина retrieval_empty видна при измеренном нуле');

  assert.strictEqual(A.turnLabel(1, 2), 'последний ход');
  assert.strictEqual(A.turnLabel(2, 2), 'ход 2 из 2',
    'F4: метка обязана отражать выбранный ход');
  assert.strictEqual(A.turnLabel(3, 8), 'ход 3 из 8');
  assert.ok(A.view({ available: true, selection: null }).text
    .indexOf('последнего') < 0,
    'F4: no_selection не называет выбранный ход последним');

  [ready, noTurns, truncated, noRetrieval].forEach(function (v) {
    const dump = JSON.stringify(v);
    assert.ok(!hasPercent(dump), 'в view не должно быть процентов: ' + dump);
    assert.ok(!/pct|percent/i.test(dump), 'нет процентных полей: ' + dump);
  });

  // ── render-маркеры и запрет графика/процентов в блоках ─────────────────
  const html = read('web/index.html');
  const statusWin = blockWindow(html, 'data-retrieval-coverage-status',
    'data-intents');
  const analyticsWin = blockWindow(html, 'data-retrieval-coverage-analytics',
    '<!-- mca-17c');
  assert.ok(statusWin.indexOf('data-rc-writer-block') >= 0,
    'Status: строка Writer-блоков');
  assert.ok(statusWin.indexOf('data-rc-exclusions') >= 0,
    'Status: строка исключений');
  assert.ok(analyticsWin.indexOf('data-rc-run') >= 0,
    'Analytics: список вызовов (не таблица)');
  assert.ok(analyticsWin.indexOf('run.emptyText') >= 0,
    'B8: причина пустой выдачи берётся из view, не захардкожена');
  assert.ok(statusWin.indexOf('.excludedPresent') >= 0,
    'F2: Status различает excluded_present=false');
  assert.ok(statusWin.indexOf('memoryYearCoverageTurnLabel') >= 0,
    'F4: подпись хода динамическая');
  assert.ok(analyticsWin.indexOf('memoryYearCoverageTurnLabel') >= 0,
    'F4: Analytics не называет выбранный ход последним');
  assert.ok(analyticsWin.indexOf('[data-rc-run]') < 0, 'служебный маркер');
  [statusWin, analyticsWin].forEach(function (win) {
    assert.ok(win.toLowerCase().indexOf('<canvas') < 0,
      'в блоке покрытия нет canvas');
    assert.ok(win.toLowerCase().indexOf('<svg') < 0,
      'в блоке покрытия нет svg-графика');
    assert.ok(win.toLowerCase().indexOf('донат') < 0, 'нет доната');
    assert.ok(win.toLowerCase().indexOf('radial') < 0, 'нет radial');
  });
  assert.ok(html.indexOf('/static/status-analytics.js') >= 0,
    'index.html обязан подключать status-analytics.js');
  const app = read('web/app.js');
  assert.ok(app.indexOf('/api/memory/retrieval-coverage') < 0,
    'UI не вызывает aggregate /api/memory/retrieval-coverage');
  assert.ok(app.indexOf('status-analytics.js') < 0,
    'helper подключается из index.html, а не из app.js');

  console.log('VMQ-TIME09-UNIT-OK');
}

main();
