'use strict';
/* F11 round1025 (status-showcase-dashboard-round1025, ADR-1025-23) —
 * unit/маркер-тесты композиции витрины «Статус» (§11–§21).
 *
 * Покрытие:
 *   D1 §12: 12-кол. сетка `.status-grid` + kill-switch `UI_STATUS_GRID_V2`
 *           (default ON; OFF → `.status-grid--legacy`); адаптив §70 (12/6/1).
 *   D2 §13/§14: Hero(5)/метрики+HB(7); честные `null` ≠ 0 (`statusSys`).
 *   D3 §17: `sleepWidget` — единый источник времени (cognition/generated_at),
 *           активность ТОЛЬКО с сервера; новых таймеров нет.
 *   D4 §16: поиск (имя/алиас), соседи (`graphNeighborsOf`), подробности
 *           (`graphSelectNode`), аддитивный маршрут `#/status/graph`.
 *   D5 §19: `factsFeed` — стабильный ключ, время/тип только если есть.
 *   D6 §15: heartbeat/`.status-block` контракт сохранён (не переписан).
 *
 * Запуск: node tests/js/round1025_f11_status_grid_test.js
 *          → F11-STATUS-GRID-OK / F11-HEARTBEAT-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf-8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf-8');
const JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf-8');

// ── Минимальный stubbed-контекст (по образцу routing_test.js) ──────────────
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
const computed = captured.computed || {};
const methods = captured.methods || {};

// ── §12/D1: 12-колоночный контейнер + спаны (статические маркеры) ──────────
(function () {
  assert.ok(INDEX.indexOf('class="status-grid"') >= 0, '§12: .status-grid');
  assert.ok(INDEX.indexOf("'status-grid--legacy': !statusGridV2") >= 0,
    '§12: kill-switch класс');
  for (const span of ['sg-5', 'sg-7', 'sg-8', 'sg-4', 'sg-12']) {
    assert.ok(INDEX.indexOf(span) >= 0, '§12: span ' + span);
  }
  // DOM-порядок §12: Hero → метрики(`status-block`) → граф → сон → мониторинг
  // → превью → факты → бюджеты → логи.
  const order = ['status-hero', 'class="card p-4 status-block"', 'status-graph',
    'status-sleep', 'Мониторинг Интеллекта', 'exec-preview', 'status-facts',
    'status-budgets', 'status-logs'];
  let prev = -1;
  order.forEach(function (m) {
    const i = INDEX.indexOf(m);
    assert.ok(i > prev, '§12: порядок DOM ' + m);
    prev = i;
  });
  // CSS: 12 → 6 → 1 и анти-overflow.
  assert.ok(/\.status-grid \{[\s\S]{0,220}repeat\(12, minmax\(0, 1fr\)\)/.test(CSS),
    '§12: 12 колонок');
  assert.ok(/@media \(max-width: 991px\)[\s\S]{0,220}repeat\(6, minmax\(0, 1fr\)\)/.test(CSS),
    '§12: 6 колонок на 768–991');
  assert.ok(/@media \(max-width: 767px\)[\s\S]{0,160}minmax\(0, 1fr\)/.test(CSS),
    '§12: 1 колонка на ≤767');
  assert.ok(CSS.indexOf('.status-grid--legacy') >= 0, '§12: legacy-откат');

  // kill-switch: default ON (uiFlag fallback true) / OFF → false.
  assert.strictEqual(computed.statusGridV2.call({ uiFlag: function () { return true; } }),
    true, 'D6: default ON');
  assert.strictEqual(
    computed.statusGridV2.call({ uiFlag: function (n) { return n !== 'UI_STATUS_GRID_V2'; } }),
    false, 'D6: OFF → legacy');
})();

// ── §13/§14/D2: Hero + честные `null` ≠ 0 ──────────────────────────────────
(function () {
  assert.ok(INDEX.indexOf('status-hero') >= 0, '§13: Hero');
  assert.ok(/class="card p-4 status-block"/.test(INDEX),
    '§14: `.status-block` контракт сохранён');
  // null → нет данных (не 0)
  let s = computed.statusSys.call({
    statusData: { server: { cpu_percent: null,
      memory: { used: null, total: null, percent: null }, disk: null } },
  });
  assert.strictEqual(s.ready, true);
  assert.strictEqual(s.cpu, null, 'null cpu ≠ 0');
  assert.strictEqual(s.mem.percent, null, 'null mem ≠ 0');
  // 0 сохраняется как 0
  s = computed.statusSys.call({
    statusData: { server: { cpu_percent: 0,
      memory: { used: 0, total: 100, percent: 0 },
      disk: { used: 0, total: 100, percent: 0 },
      loadavg: [0, 0, 0], process: { pid: 1, rss_mb: 2, threads: 3 } } },
  });
  assert.strictEqual(s.cpu, 0, '0 cpu остаётся 0');
  assert.strictEqual(s.mem.percent, 0);
  assert.strictEqual(s.disk.percent, 0);
  // нет секции server → not ready (нет данных)
  s = computed.statusSys.call({ statusData: {} });
  assert.strictEqual(s.ready, false);
  assert.strictEqual(s.cpu, null);
  // пометка «метрики всего сервера» при выбранном чате — существующая.
  assert.ok(INDEX.indexOf('Метрики относятся ко всему серверу') >= 0, '§14: пометка');
})();

// ── §17/D3: виджет сна — единый источник времени, активность с сервера ─────
(function () {
  const w = computed.sleepWidget.call({
    cognition: {
      generated_at: 1000,
      dream: { active: true, active_until: 1600, last_run_at: 900 },
      deep_sleep: { active: false, next_run_at: 1300, last_run_at: null },
      budget: { tokens_today: 5, tokens_limit: 100 },
    },
    fmtClock: methods.fmtClock,
    fmtCountdown: methods.fmtCountdown,
  });
  assert.strictEqual(w.ready, true);
  assert.strictEqual(w.dream.active, true, '§17: active с сервера');
  assert.strictEqual(w.dream.text.indexOf('до ') === 0, true, '§17: «Сон до…»');
  assert.strictEqual(w.deep.active, false);
  assert.strictEqual(w.deep.text.indexOf('через ') === 0, true,
    '§17: «Глубокий сон через…»');
  assert.strictEqual(w.dream.countdownSecs, null, '§17: активный — без countdown');
  assert.strictEqual(w.deep.countdownSecs, 300, '§17: countdown от generated_at');
  assert.strictEqual(computed.sleepWidget.call({ cognition: null }).ready, false,
    '§17: нет cognition → нет данных');
  // Единый источник: никаких новых таймеров (setTimeout/setInterval в §17 нет).
  assert.ok(JS.indexOf('sleepWidget: function') >= 0);
  assert.ok(INDEX.indexOf('dreamPhaseBadge') >= 0 && INDEX.indexOf('deepPhaseBadge') >= 0,
    '§17: reuse бейджей');
})();

// ── §16/D4: граф — соседи, подробности, алиас-поиск, маршрут ───────────────
(function () {
  const data = {
    nodes: [{ id: 1, label: 'Аня', group: 'user' },
            { id: 2, label: 'Борис', group: 'user' },
            { id: 3, label: 'Тема', group: 'topic' }],
    edges: [{ from: 1, to: 2, weight: 5 }, { from: 1, to: 3, weight: 1 }],
  };
  const nb = methods.graphNeighborsOf.call({ cognitionGraphData: data }, 1);
  assert.deepStrictEqual(nb.map(function (n) { return n.id; }).sort(), [2, 3],
    '§16: ближайшие связи');
  const ctx = { cognitionGraphData: data,
    graphNeighborsOf: methods.graphNeighborsOf };
  methods.graphSelectNode.call(ctx, 2);
  assert.strictEqual(ctx.graphDetail.label, 'Борис', '§16: подробности узла');
  assert.strictEqual(ctx.graphDetail.group, 'user', '§16: группа узла (реальная)');
  assert.strictEqual(ctx.graphDetail.degree, null, '§16: degree отсутствует → null');
  assert.deepStrictEqual(ctx.graphNeighbors.map(function (n) { return n.id; }), [1]);
  methods.graphClearDetail.call(ctx);
  assert.strictEqual(ctx.graphDetail, null);
  // витринный фильтр по group (клиентский, layout не меняется).
  const groups = computed.graphGroupOptions.call({ cognitionGraphData: data });
  assert.deepStrictEqual(groups.slice().sort(), ['topic', 'user']);
  // маршрут полного экрана (аддитивный, владелец F1).
  assert.ok(JS.indexOf("'#/status/graph': 'status'") >= 0, '§16: ROUTE_TO_TAB');
  assert.ok(JS.indexOf("'#/status/graph': '#/'") >= 0, '§16: ROUTE_PARENT');
  assert.ok(INDEX.indexOf('status-graph-full') >= 0, '§16: экран/шторка');
  assert.ok(INDEX.indexOf('graph-search__input') >= 0, '§16: поиск');
  // Семантика веса/layout не переопределена.
  assert.ok(JS.indexOf('barnesHut') >= 0, '§16: layout сохранён');
  assert.ok(JS.indexOf('_graphSignature') >= 0, '§16: lazy/diff сохранены');
})();

// ── §19/D5: «Новые факты» — стабильный ключ, время/тип только если есть ────
(function () {
  const f = computed.factsFeed.call({
    dossierFeed: [
      { chat_id: 1, name: 'A', excerpt: 'первый' },
      { chat_id: 1, name: 'B', excerpt: 'второй', created_at: 5, kind: 'belief' },
    ],
  });
  assert.strictEqual(f.length, 2);
  assert.strictEqual(f[0].time, null, '§19: времени нет — не выдумываем');
  assert.strictEqual(f[0].kind, null, '§19: типа нет — не выдумываем');
  assert.strictEqual(f[1].time, 5);
  assert.strictEqual(f[1].kind, 'belief');
  assert.ok(f[0].key.indexOf('|') >= 0, '§19: стабильный ключ');
  assert.ok(INDEX.indexOf('Что бот недавно запомнил') >= 0, '§19: подзаголовок');
  assert.ok(/\.status-facts \.facts-list \{[\s\S]{0,120}overflow-y: auto/.test(CSS),
    '§19: только вертикальный скролл');
})();

// ── §20/D5: счётчики + клик по скроллу (viewer не переписан) ───────────────
(function () {
  assert.ok(INDEX.indexOf('Ошибки:') >= 0 && INDEX.indexOf('Предупреждения:') >= 0,
    '§20: счётчики');
  assert.ok(INDEX.indexOf('scrollToLogs()') >= 0, '§20: клик → скролл');
  assert.ok(INDEX.indexOf('status-logs') >= 0, '§20: якорь логов');
  assert.ok(methods.loadLogCounts && methods.scrollToLogs, '§20: методы');
  // viewer не переписан: существующие маркеры/структура на месте.
  assert.ok(INDEX.indexOf('log-panel scroll-thin') >= 0, '§20: viewer сохранён');
  assert.ok(INDEX.indexOf('copyLogRow(log, i)') >= 0, '§20: копирование сохранено');
  assert.ok(INDEX.indexOf('ERROR+WARNING') >= 0, '§20: фильтры сохранены');
})();

// ── §15/D6: heartbeat/`.status-block` контракт НЕ переписан ────────────────
(function () {
  assert.ok(/\.status-block \{ max-width: 100%; overflow: hidden; \}/.test(CSS),
    '§15: контракт .status-block');
  assert.ok(/\.hb-wrap \{[^}]*min-height: 56px/.test(CSS), '§15: hb-wrap');
  assert.ok(INDEX.indexOf('status-block__pulse') >= 0, '§15: heartbeat на месте');
  assert.ok(INDEX.indexOf('hb-canvas') >= 0 && INDEX.indexOf('ekg-trace') >= 0,
    '§15: canvas/SVG-фолбэк сохранены');
  assert.ok(JS.indexOf('_applyHeartbeatSample') >= 0 &&
            JS.indexOf('heartbeatCanvasEnabled') >= 0,
    '§15: телеметрия/флаг не тронуты');
  assert.strictEqual(
    computed.heartbeatCanvasEnabled.call({ uiFlag: function () { return false; } }),
    false, '§15: OFF-откат работает');
})();

console.log('F11-STATUS-GRID-OK');
console.log('F11-HEARTBEAT-OK');
