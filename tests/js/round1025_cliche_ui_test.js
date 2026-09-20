'use strict';
/* F0.3 round1025 (ревью) — UI анти-клише: отображение семантики
 * «сохранено N / вместимость M; за обновление ≤ K» и честные статусы.
 *
 * Запуск: node tests/js/round1025_cliche_ui_test.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const API = fs.readFileSync(
  path.join(ROOT, 'web', 'api', 'anticliche.py'), 'utf8');

// ── UI: обе величины (вместимость и размер партии) ─────────────────────────
assert.ok(INDEX.indexOf('вместимость') >= 0,
  'UI показывает вместимость (M)');
assert.ok(INDEX.indexOf('за обновление ≤') >= 0,
  'UI показывает размер партии (за обновление ≤ K)');
assert.ok(INDEX.indexOf('clichePerRun()') >= 0,
  'UI читает per_run через clichePerRun()');
assert.ok(INDEX.indexOf('clicheMeta.count') >= 0,
  'UI показывает сохранённое количество (N)');

// ── app.js: per_run + честные статусы ──────────────────────────────────────
assert.ok(/clichePerRun:\s*function/.test(JS), 'есть computed clichePerRun');
assert.ok(JS.indexOf('clicheMeta.per_run') >= 0,
  'clichePerRun читает per_run из меты');
assert.ok(JS.indexOf("llm_error: 'ошибка провайдера'") >= 0,
  'llm_error не выдаётся за обобщённую «ошибку модели»');
assert.ok(JS.indexOf("empty: 'новых нет (успех)'") >= 0,
  '«0 новых» = успех, не ошибка');
assert.ok(JS.indexOf('no_new') >= 0, 'есть статус no_new');

// ── API: GET отдаёт per_run/max_rounds (аддитивно) ─────────────────────────
assert.ok(API.indexOf('"per_run"') >= 0 || API.indexOf("'per_run'") >= 0,
  'GET /api/anticliche отдаёт per_run');
assert.ok(API.indexOf('max_patterns_per_run') >= 0,
  'per_run резолвится воркером (capacity vs per-run)');

console.log('ROUND1025-CLICHE-UI-OK');
