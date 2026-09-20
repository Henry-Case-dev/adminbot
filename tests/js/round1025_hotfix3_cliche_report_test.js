'use strict';
/* Хотфикс-3 round1025 (T-2492) — UI анти-клише: честный warn
 * «Сохранено N из M» + причины отброса; канон длины 120.
 *
 * Падает на старом коде: saveCliche всегда писал «Сохранено» и игнорировал
 * count/dropped; UI не знал про канон 120.
 *
 * Запуск: node tests/js/round1025_hotfix3_cliche_report_test.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const API = fs.readFileSync(
  path.join(ROOT, 'web', 'api', 'anticliche.py'), 'utf8');

// ── UI: честный отчёт ───────────────────────────────────────────────────────
assert.ok(JS.indexOf("'Сохранено '") >= 0,
  'UI умеет показать «Сохранено …»');
assert.ok(JS.indexOf('+ savedN + \' из \' + total') >= 0 ||
  /Сохранено '\s*\+\s*savedN\s*\+\s*'\s*из\s*'/.test(JS),
  'UI показывает «Сохранено N из M»');
assert.ok(JS.indexOf('resp.count') >= 0,
  'UI читает фактическое число сохранённых из ответа API');
assert.ok(JS.indexOf('resp.dropped') >= 0 || JS.indexOf('resp && resp.dropped') >= 0,
  'UI читает разбивку отброшенного из ответа API');
assert.ok(JS.indexOf('over_limit') >= 0 && JS.indexOf('duplicate') >= 0 &&
  JS.indexOf('invalid') >= 0 && JS.indexOf('hardcoded') >= 0,
  'UI перечисляет причины отброса (invalid/hardcoded/duplicate/over_limit)');
assert.ok(JS.indexOf('сверх лимита') >= 0 && JS.indexOf('дубли') >= 0,
  'UI даёт человекочитаемые причины');

// ── UI: канон длины 120 (понятная ошибка, не тихий дроп) ────────────────────
assert.ok(/var\s+maxLen\s*=\s*120/.test(JS),
  'UI знает канон длины фразы 120');
assert.ok(JS.indexOf('символов') >= 0,
  'UI предупреждает о слишком длинной фразе понятным текстом');
assert.ok(INDEX.indexOf('до 120 символов') >= 0,
  'подсказка в UI: до 120 символов на фразу');
// Review fix (L-7): кап 120 на КАЖДУЮ фразу (textarea многострочная —
// HTML maxlength ограничил бы весь черновик, поэтому режем по строкам).
assert.ok(/limitClicheDraft:\s*function/.test(JS),
  'есть per-line ограничитель длины фразы');
assert.ok(INDEX.indexOf('limitClicheDraft()') >= 0,
  'поле фразы вызывает per-line ограничитель');
assert.ok(INDEX.indexOf('обрезается') >= 0,
  'подсказка объясняет авто-обрезку строки');

// ── API: аддитивный контракт сохранения ─────────────────────────────────────
assert.ok(API.indexOf('DYNAMIC_PHRASE_MAX') >= 0,
  'API привязан к канону DYNAMIC_PHRASE_MAX (120), а не к 500');
assert.ok(API.indexOf('result.get("dropped")') >= 0 ||
  API.indexOf("result.get('dropped')") >= 0,
  'API логирует честную разбивку (saved/dropped)');

console.log('ROUND1025-HOTFIX3-CLICHE-REPORT-OK');
