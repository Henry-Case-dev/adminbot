/* ASAP-3.1 rework (H-ASAP31-2) — регрессия «пустого экрана Аналитики».
 *
 * Баг (прод-симптом владельца 2.58.36, воспроизведён ревью): шаблон
 * oversight-ветки вызывает `execMetricsRows()` как функцию, а хелпер был
 * объявлен в `computed:`; внутри computed ещё и `self.execTokenPair(...)`
 * между computed-записями → Vue render TypeError → корень приложения
 * рендерит `<!---->` → полностью пустой экран.
 *
 * Харнесс ловит КЛАСС бага структурно (без DOM/Vue — Δ зависимостей = 0):
 *   1) каждая функция, вызываемая в oversight-шаблоне как `name(...)`,
 *      обязана быть в `methods:` (computed в шаблоне вызывается БЕЗ скобок);
 *   2) внутри ни одной computed-записи нет `this.name(...)`/`self.name(...)`,
 *      где name — другая computed-запись (только методы/локальные функции);
 *   3) прямой инвариант фикса: execMetricsRows/execTokenPair/execDuration/
 *      execCoverLabel/execPublicationLabel — в methods, НЕ в computed;
 *   4) ключевые секции oversight-шаблона присутствуют (заголовок,
 *      «Модели и автобюджеты», метрики прогона) — «не пустой экран».
 */
'use strict';
const fs = require('fs');
const assert = require('assert');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const INDEX_HTML = fs.readFileSync(path.join(ROOT, 'web', 'index.html'),
                                   'utf8');

/* ── Извлечение сбалансированного блока `{...}` от позиции открывающей ── */
function balancedBlock(text, openIdx) {
  let depth = 0;
  for (let i = openIdx; i < text.length; i++) {
    const ch = text[i];
    if (ch === '{') depth++;
    else if (ch === '}') {
      depth--;
      if (depth === 0) return text.slice(openIdx, i + 1);
    }
  }
  return text.slice(openIdx);
}

/* Основное Vue-приложение: блок опций от `Vue.createApp({` (первое вхождение
 * — второй createApp в файле не содержит computed/methods oversight'а). */
function optionBlock(name) {
  const anchor = 'Vue.createApp({';
  const start = APP_JS.indexOf(anchor);
  assert.ok(start >= 0, 'createApp не найден');
  const block = balancedBlock(APP_JS, start + anchor.length - 1);
  const keyIdx = block.indexOf(name + ': {');
  assert.ok(keyIdx >= 0, 'блок опций "%s" не найден'.replace('%s', name));
  return balancedBlock(block, keyIdx + name.length + 2);
}

const computedBlock = optionBlock('computed');
const methodsBlock = optionBlock('methods');

/* Ключи верхнего уровня записей (6-пробельный канон файла):
 * `      name: function (…)` / `      name(…) {` / `      name: …`. */
function entryKeys(block) {
  const keys = new Set();
  const re = /^ {6}([A-Za-z_$][\w$]*):\s*(?:async )?function\b|^ {6}([A-Za-z_$][\w$]*)\(/gm;
  let m;
  while ((m = re.exec(block)) !== null) {
    keys.add(m[1] || m[2]);
  }
  return keys;
}

const computedKeys = entryKeys(computedBlock);
const methodsKeys = entryKeys(methodsBlock);
assert.ok(computedKeys.size > 100, 'computed-ключи не распарсены');
assert.ok(methodsKeys.size > 100, 'methods-ключи не распарсены');

/* ── Проверка 3: прямой инвариант фикса ───────────────────────────────── */
const MOVED = ['execMetricsRows', 'execTokenPair', 'execDuration',
               'execCoverLabel', 'execPublicationLabel'];
for (const name of MOVED) {
  assert.ok(methodsKeys.has(name),
    'H-ASAP31-2: ' + name + ' обязан быть в methods');
  assert.ok(!computedKeys.has(name),
    'H-ASAP31-2: ' + name + ' не должен оставаться в computed');
}

/* ── Проверка 1: oversight-шаблон не вызывает computed как функции ────── */
function templateSlice(marker) {
  const start = INDEX_HTML.indexOf(marker);
  assert.ok(start >= 0, 'маркер oversight-шаблона не найден');
  // Баланс вложенных <template>…</template> от найденной точки.
  let depth = 0;
  let i = INDEX_HTML.indexOf('<template', start);
  let end = INDEX_HTML.length;
  while (i !== -1 && i < INDEX_HTML.length) {
    const open = INDEX_HTML.indexOf('<template', i);
    const close = INDEX_HTML.indexOf('</template>', i);
    if (close === -1) break;
    if (open !== -1 && open < close) {
      depth++;
      i = open + 9;
    } else {
      depth--;
      i = close + 11;
      if (depth === 0) { end = close + 11; break; }
    }
  }
  return INDEX_HTML.slice(start, end);
}

const oversightTpl = templateSlice(
  '<template v-else-if="activeTab === \'oversight\'">');

const JS_BUILTIN = new Set(['if', 'for', 'while', 'switch', 'catch',
  'function', 'return', 'typeof', 'String', 'Number', 'Boolean', 'Array',
  'Object', 'Math', 'JSON', 'Date', 'parseInt', 'parseFloat']);
/* Vue-выражения шаблона — только атрибуты директив/биндингов и mustache:
 * `v-…="expr"`, `:prop="expr"`, `@event="expr"`, `{{ expr }}`. Проза/JSON
 * в срезе не проверяются. */
const exprRe = /(?:\s(?:v-[\w:.-]+|:[\w:.-]+|@[\w.:-]+)="([^"]*)")|(?:\{\{([^}]*)\}\})/g;
/* Вызов интересует только как идентификатор в скоупе Vue (не member-call:
 * `.join(...)`/`.map(...)` — методы массивов — мимо). */
const callRe = /(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(/g;
let expr, call;
while ((expr = exprRe.exec(oversightTpl)) !== null) {
  const source = expr[1] || expr[2] || '';
  while ((call = callRe.exec(source)) !== null) {
    const name = call[1];
    if (JS_BUILTIN.has(name)) continue;
    assert.ok(methodsKeys.has(name),
      'oversight-шаблон вызывает "' + name + '(...)" как функцию, но она не '
      + 'в methods (' + (computedKeys.has(name)
        ? 'она COMPUTED — вызывай без скобок или перенеси в methods'
        : 'не найдена в methods/computed — опечатка?') + ')');
  }
}

/* ── Проверка 2: computed не вызывает computed как функцию ────────────── */
/* Разбиение computed-блока на записи верхнего уровня и скан тела каждой. */
function entries(block) {
  const re = /^ {6}([A-Za-z_$][\w$]*):\s*(?:async )?function\b/gm;
  const starts = [];
  let mm;
  while ((mm = re.exec(block)) !== null) starts.push({ name: mm[1], at: mm.index });
  const out = [];
  for (let i = 0; i < starts.length; i++) {
    const bodyEnd = (i + 1 < starts.length) ? starts[i + 1].at : block.length;
    out.push({ name: starts[i].name, body: block.slice(starts[i].at, bodyEnd) });
  }
  return out;
}

const SELF_CALL = /(?:this|self)\.([A-Za-z_$][\w$]*)\s*\(/g;
for (const entry of entries(computedBlock)) {
  // Локальные функции записи (function name(…) { … }) — не методы Vue.
  const local = new Set();
  const localRe = /\bfunction\s+([A-Za-z_$][\w$]*)\s*\(/g;
  let lm;
  while ((lm = localRe.exec(entry.body)) !== null) local.add(lm[1]);
  let cm;
  SELF_CALL.lastIndex = 0;
  while ((cm = SELF_CALL.exec(entry.body)) !== null) {
    const name = cm[1];
    if (local.has(name)) continue;          // локальный хелпер записи
    assert.ok(!computedKeys.has(name),
      'computed "' + entry.name + '" вызывает "' + name + '(...)" как '
      + 'функцию, но "' + name + '" — тоже COMPUTED (Vue проксирует как '
      + 'свойство → TypeError → пустой экран). Перенеси в methods.');
  }
}

/* ── Проверка 4: ключевые секции Аналитики присутствуют ───────────────── */
assert.ok(oversightTpl.includes('Аналитика'),
  'oversight: заголовок «Аналитика» отсутствует — пустой экран');
assert.ok(oversightTpl.includes('Модели и автобюджеты'),
  'oversight: секция «Модели и автобюджеты» отсутствует');
assert.ok(oversightTpl.includes('autobudget-block'),
  'oversight: autobudget-блок (§99) отсутствует');
assert.ok(oversightTpl.includes('execMetricsRows()'),
  'oversight: метрики прогона (execMetricsRows) не рендерятся');

console.log('ASAP31-OVERSIGHT-RENDER-OK');
