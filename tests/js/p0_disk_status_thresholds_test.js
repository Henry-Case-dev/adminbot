'use strict';
/* P0-PROD-DISK-01 — видимая классификация заполнения диска на «Статусе».
 *
 * Проблема: на deployed `bca18c1e` страница «Статус» не показывала порогов
 * диска — `_ctlProgressModel` отдавал `idle` (полоса без смысла), heartbeat
 * учитывал только состояние бота, единственное предупреждение жило в другой
 * карточке («<2 GiB свободно»). Мониторинг/`/api/status`/backend не меняются:
 * проверяется классификация СУЩЕСТВУЮЩЕЙ телеметрии.
 *
 * Контракт (P0-PROD-DISK-01):
 *   * `>= 90 %` → crit: красная полоса (`bar-red`) + текст «освободите место»;
 *   * `>= 85 %` → warn: янтарная полоса + текст «место заканчивается»;
 *   * `< 85 %` → ok: обычная полоса, предупреждения нет;
 *   * нет данных (`percent`/`used+total`) → unknown, НЕ ложное «здорово»;
 *   * пороги — именованные константы 85/90 (не магические числа в ветках);
 *   * цвет не единственный сигнал: текст + `role=status`/`aria-live`;
 *   * существующие бюджеты/CPU/RAM-полосы не переписаны.
 *
 * Запуск: node tests/js/p0_disk_status_thresholds_test.js
 * Ожидаемый маркер: P0-DISK-STATUS-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf-8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf-8');
const JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf-8');

// ── Минимальный stubbed-контекст (образец: round1025_f11_status_grid_test.js) ─
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
global.localStorage = {
  _s: {},
  getItem(k) {
    return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null;
  },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const computed = captured.computed || {};

/* Vue-семантика computed: `this.ctlDiskProg` — тот же computed. В тесте
   собираем такой контекст, чтобы проверять РЕАЛЬНУЮ цепочку
   statusSys → ctlDiskProg → ctlDiskAlert, а не подставной объект. */
function alertFor(disk) {
  const ctx = { statusSys: { disk: disk } };
  Object.defineProperty(ctx, 'ctlDiskProg', {
    get: () => computed.ctlDiskProg.call(ctx),
  });
  return computed.ctlDiskAlert.call(ctx);
}

function progFor(disk) {
  return computed.ctlDiskProg.call({ statusSys: { disk: disk } });
}

// ── 1. Пороги: 84/85/89/90/95 ──────────────────────────────────────────────
(function () {
  let a = alertFor({ used: 84, total: 100, percent: 84 });
  assert.strictEqual(a.level, 'ok', '84 % — обычное состояние');
  assert.strictEqual(a.percent, 84);
  assert.strictEqual(a.text, '', '84 % — предупреждения нет');

  a = alertFor({ used: 85, total: 100, percent: 85 });
  assert.strictEqual(a.level, 'warn', '85 % — warning (нижняя граница)');
  assert.ok(a.text.indexOf('85%') >= 0, 'текст называет цифру: ' + a.text);
  assert.ok(a.text.indexOf('место заканчивается') >= 0,
    'warning объясняет, что делать: ' + a.text);

  a = alertFor({ used: 89, total: 100, percent: 89 });
  assert.strictEqual(a.level, 'warn', '89 % — всё ещё warning (не red)');

  a = alertFor({ used: 90, total: 100, percent: 90 });
  assert.strictEqual(a.level, 'crit', '90 % — критично (нижняя граница)');
  assert.ok(a.text.indexOf('90%') >= 0, 'текст называет цифру: ' + a.text);
  assert.ok(a.text.indexOf('освободите место') >= 0,
    'crit объясняет, что делать: ' + a.text);
  assert.ok(/Критично/.test(a.text), 'уровень назван словом, а не только цветом');

  a = alertFor({ used: 95, total: 100, percent: 95 });
  assert.strictEqual(a.level, 'crit', '95 % — критично');
})();

// ── 2. Нет данных → unknown, не ложное «здорово» ───────────────────────────
(function () {
  let a = alertFor(null);
  assert.strictEqual(a.level, 'unknown', 'нет секции disk → unknown');
  assert.strictEqual(a.percent, null, 'процент не выдумывается');
  assert.strictEqual(a.text, '', 'unknown не показывает предупреждение');
  assert.notStrictEqual(a.level, 'ok', 'unknown ≠ healthy');
  assert.strictEqual(a.ariaText, 'Диск: нет данных');

  a = alertFor({ used: null, total: null, percent: null });
  assert.strictEqual(a.level, 'unknown', 'пустые поля → unknown');

  a = alertFor({ used: 0, total: 0, percent: null });
  assert.strictEqual(a.level, 'unknown', 'total=0 не даёт ложный процент');
})();

// ── 3. Источник: percent ИЛИ пара used/total (та же телеметрия) ────────────
(function () {
  let a = alertFor({ used: 90, total: 100, percent: null });
  assert.strictEqual(a.level, 'crit', 'пара used/total без percent классифицируется');
  assert.strictEqual(a.percent, 90);

  a = alertFor({ used: 1, total: 1000, percent: 77 });
  assert.strictEqual(a.level, 'ok', 'подтверждённый сервером percent имеет приоритет');
  assert.strictEqual(a.percent, 77);
})();

// ── 4. Классификация по показанной цифре (цвет не расходится с текстом) ────
(function () {
  // 84.9 % показывается как 85 % (округление `_ctlProgressModel`): подпись,
  // цвет и порог обязаны говорить одно и то же.
  let a = alertFor({ used: 849, total: 1000, percent: 84.9 });
  assert.strictEqual(a.percent, 85, 'показанная цифра — 85 %');
  assert.strictEqual(a.level, 'warn', 'порог применяется к показанной цифре');

  a = alertFor({ used: 896, total: 1000, percent: 89.6 });
  assert.strictEqual(a.percent, 90);
  assert.strictEqual(a.level, 'crit', '89.6 % показывается как 90 % → crit');
})();

// ── 5. Пороговые константы: именованные, не магические ─────────────────────
(function () {
  assert.ok(/var STATUS_DISK_WARN_PERCENT = 85;/.test(JS),
    'порог warning — именованная константа 85');
  assert.ok(/var STATUS_DISK_CRIT_PERCENT = 90;/.test(JS),
    'порог crit — именованная константа 90');

  const start = JS.indexOf('ctlDiskAlert: function');
  assert.ok(start > 0, 'computed ctlDiskAlert найден');
  const end = JS.indexOf('ctlContextProg: function', start);
  assert.ok(end > start, 'границы computed определены');
  const body = JS.slice(start, end);
  assert.ok(body.indexOf('pct >= STATUS_DISK_CRIT_PERCENT') >= 0,
    'crit сравнивает с константой');
  assert.ok(body.indexOf('pct >= STATUS_DISK_WARN_PERCENT') >= 0,
    'warn сравнивает с константой');
  assert.ok(!/pct\s*(>=|>)\s*(85|90)\b/.test(body),
    'в ветках нет магического числа порога');
  // Пороги не повышены: 85/90 остаются заводскими значениями.
  assert.ok(JS.indexOf('STATUS_DISK_WARN_PERCENT = 85') > 0);
  assert.ok(JS.indexOf('STATUS_DISK_CRIT_PERCENT = 90') > 0);
})();

// ── 6. Доступность и разметка: текст + aria-live, bar-red на crit ──────────
(function () {
  assert.ok(INDEX.indexOf(':data-disk-level="ctlDiskAlert.level"') >= 0,
    'уровень классификации — в data-атрибуте блока диска');
  assert.ok(INDEX.indexOf(':data-disk-alert="ctlDiskAlert.level"') >= 0,
    'уровень предупреждения — в data-атрибуте строки');
  assert.ok(INDEX.indexOf("'bar-red': ctlDiskAlert.level === 'crit'") >= 0,
    'crit красит заливку существующим bar-red');
  assert.ok(INDEX.indexOf('<span>{{ ctlDiskAlert.text }}</span>') >= 0,
    'предупреждение несёт текст (не только цвет)');
  assert.ok(/role="status" aria-live="polite" aria-atomic="true"/.test(INDEX),
    'предупреждение объявляется скринридером (aria-live)');
  assert.ok(INDEX.indexOf(':aria-label="ctlDiskAlert.ariaText"') >= 0,
    'прогрессбар озвучивает классификацию вместе с цифрой');
  assert.ok(INDEX.indexOf(':data-state="ctlDiskProg.state"') >= 0,
    'честное состояние полосы (unknown/error) не потеряно');

  // CSS: уровни различимы правилами, а не только текстом.
  assert.ok(/\.status-disk\[data-disk-level="warn"\] \.ctl-progress__fill/.test(CSS),
    'warn — янтарная полоса');
  assert.ok(/\.status-disk\[data-disk-level="crit"\] \.ctl-progress__fill/.test(CSS),
    'crit — красная полоса');
  assert.ok(CSS.indexOf('.status-disk__alert--crit') >= 0, 'crit-текст стилизован');
})();

// ── 7. Существующие полосы/бюджеты не переписаны ───────────────────────────
(function () {
  const p = progFor({ used: 50, total: 100, percent: 50 });
  assert.strictEqual(p.state, 'idle', 'диск остаётся статичной ресурсной полосой');
  assert.strictEqual(p.percent, 50);
  assert.strictEqual(p.ratio, 0.5);
  assert.strictEqual(p.ariaNow, 50);

  const unknown = progFor({ used: null, total: null, percent: null });
  assert.strictEqual(unknown.state, 'unknown', 'нет данных — штриховка, не заливка');
  assert.strictEqual(unknown.percent, null);

  const overflow = progFor({ used: 900, total: 100, percent: null });
  assert.strictEqual(overflow.percent, 100, 'переполнение не уезжает за 100 %');

  // CPU/RAM-модели — та же `_ctlProgressModel`, не отдельный рецепт.
  const ctx = { statusSys: { cpu: 3, mem: { used: 512, total: 2048, percent: 25 } } };
  Object.defineProperty(ctx, 'ctlCpuProg', {
    get: () => computed.ctlCpuProg.call(ctx),
  });
  Object.defineProperty(ctx, 'ctlMemProg', {
    get: () => computed.ctlMemProg.call(ctx),
  });
  assert.strictEqual(ctx.ctlCpuProg.percent, 3, 'CPU-полоса не изменилась');
  assert.strictEqual(ctx.ctlMemProg.percent, 25, 'RAM-полоса не изменилась');

  // Бюджет контекста по-прежнему считается из memoryContext.
  const budget = computed.ctlContextProg.call({
    memoryContext: { used: 1000, limit: 4000 },
  });
  assert.strictEqual(budget.percent, 25, 'бюджет контекста не переписан');
})();

console.log('P0-DISK-STATUS-OK');
