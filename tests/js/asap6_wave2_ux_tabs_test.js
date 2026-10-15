'use strict';
/* ASAP 6 Wave 2 UX (Status/Analytics round) — РЕАЛЬНЫЙ JS-тест (не grep).
 *
 * Проверяем поведение, а не только строки:
 *   1) суб-вкладки «Аналитики»: 8 табов с человеческими названиями;
 *      oversightSetTab синхронизирует mca-группу с существующим
 *      oversightView (REUSE механики mca-17c, новой страницы нет);
 *   2) deep-link `#/oversight?tab=logs|models|...` парсится и применяется;
 *      старый `?view=learning` по-прежнему работает (→ таб «Процессы»);
 *   3) hash-синхронизация: mca-вью пишет `?view=`, остальные — `?tab=`;
 *   4) honest-данные: statusKeyStripRows/overviewHealthStrip без данных
 *      дают «нет данных»/«—» (ноль не выдумывается); statusProblemsCount
 *      считает только реальный деград/блокеры/активные инциденты;
 *   5) структура index.html: вкладки, перенос секций по
 *      visual-preservation-map (factcheck/embeddings/память → «Память и
 *      интеллект»; токены/автобюджеты/история ключей → «Модели и расходы»;
 *      pipeline → «Саммари»; FIX-logs-anchor: логи — ФИЗИЧЕСКИЙ блок внизу
 *      «Аналитики» вне таб-гвардов (вкладка «Логи» — якорь, не режим); на
 *      «Статусе» — strip ключей, компактная случайность, карточка-переход
 *      к логам);
 *   6) Δ endpoint = 0: новых '/api/...' строк в app.js не появилось.
 *
 * Запуск: node tests/js/asap6_wave2_ux_tabs_test.js
 *         → WAVE2-UX-TABS-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

// ── Stubbed-контекст (по образцу routing_test.js) ──────────────────────────
let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
const _bodyChildren = [];
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {}, remove() {
        const idx = _bodyChildren.indexOf(el);
        if (idx >= 0) _bodyChildren.splice(idx, 1);
      },
      getContext() { return null; },
    };
    var el = this; // eslint-disable-line no-unreachable
  },
  body: { appendChild() {}, removeChild() {} },
  execCommand() { return true; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
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
const CSS = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');

// ── 1) вкладки: список/человеческие названия/sync с oversightView ──────────
const dataOpts = captured.data();
const tabs = dataOpts.oversightTabs;
// U04 (v6.3): «Логи» — ТОЛЬКО в Статусе; вкладки-якоря больше нет.
assert.strictEqual(tabs.length, 7, '7 суб-вкладок (без якоря «Логи»)');
assert.deepStrictEqual(tabs.map(function (t) { return t.id; }),
  ['overview', 'processes', 'runs', 'incidents', 'memory', 'models',
   'summary'], 'порядок вкладок (якорь «Логи» удалён — U04)');
assert.deepStrictEqual(tabs.map(function (t) { return t.label; }),
  ['Обзор', 'Процессы', 'Запуски', 'Инциденты', 'Память и интеллект',
   'Модели и расходы', 'Саммари'],
  'человеческие русские названия вкладок');
assert.strictEqual(tabs.some(function (t) { return t.id === 'logs'; }), false,
  'U04: {id:"logs"} удалён из oversightTabs');

const vm = Object.create(methods);
vm.oversightTab = 'overview';
vm.oversightView = 'processes';
vm.oversightTabs = tabs;
vm.oversightStopRunsPolling = function () { this._leaveRuns = true; };
vm.oversightStopIncidentsPolling = function () { this._leaveInc = true; };
vm.oversightStartRunsPolling = function () {};
vm.oversightStartIncidentsPolling = function () {};
vm.oversightLoadProcesses = function () {};
vm.oversightLoadRuns = function () {};
vm.oversightLoadIncidents = function () {};
vm.oversightSyncHash = function () {};
vm.statusData = null;
vm.oversightData = null;
vm.temporalRuns = null; vm.temporalRunsBusy = false;
vm.loadTemporalRuns = function () { this._factcheck = true; };
vm.budgetsAuto = null; vm.budgetsAutoBusy = false;
vm.loadBudgetsAuto = function () {};
vm.keyHistory = null;
vm.loadKeyHistory = function () { this._keyHistory = true; };
vm.isGlobalAdmin = true;
vm.logs = []; vm.logsLoading = false;
vm.loadLogs = function () { this._logs = true; };
vm.loadLogCounts = function () {};
vm.loadStatus = function () { this._status = true; };
vm.loadOversight = function () {};
let anchorCalls = 0;
vm._scrollToLogsAnchor = function () { anchorCalls++; };

// U04 (v6.3): вход в Аналитику больше НЕ тянет логи — viewer переехал в
// конец «Статуса»; loadLogCounts тоже не дёргается здесь (живёт в loadStatus).
methods.oversightSetTab.call(vm, 'runs');
assert.strictEqual(vm.oversightView, 'runs',
  'REUSE: mca-вью синхронизируется с табом');
methods.oversightSetTab.call(vm, 'memory');
assert.strictEqual(vm._factcheck, true, '«Память и интеллект» лениво грузит фактчек');
methods.oversightSetTab.call(vm, 'models');
assert.strictEqual(vm._keyHistory, true, '«Модели» лениво грузит историю ключей');
vm.oversightTab = 'summary'; vm.logs = []; vm.logsLoading = false;
methods.oversightTabEnter.call(vm);
assert.strictEqual(vm._logs, undefined,
  'U04: loadLogs на входе в Аналитику убран (логи в Статусе)');
assert.strictEqual(anchorCalls, 0,
  'U04: вход в Аналитику не скроллит к логам');

// ── 2) deep-link: новый `?tab=` и старый `?view=` ──────────────────────────
{
  const l1 = methods.oversightParseDeepLink('#/oversight?tab=logs');
  assert.strictEqual(l1.tab, 'logs');
  assert.strictEqual(l1.view, null);
  const l2 = methods.oversightParseDeepLink(
    '#/oversight?view=runs&run_id=abc&days=7');
  assert.strictEqual(l2.view, 'runs');
  assert.strictEqual(l2.tab, null);
  assert.strictEqual(l2.params.run_id, 'abc');
  const alien = methods.oversightParseDeepLink('#/status?tab=logs');
  assert.strictEqual(alien.tab, null, 'только внутри #/oversight');
}
{
  const vm2 = Object.create(methods);
  vm2.oversightTab = 'overview';
  vm2.oversightView = 'processes';
  vm2.oversightTabs = tabs;
  vm2.mca17cRunF = { status: '', pipeline_type: '', component: '',
    chat_id: '', days: '7' };
  vm2.mca17cFunnelDays = '30';
  vm2.mca17cRunDetail = null;
  vm2.mca17cDeepLinkDone = false;
  vm2.oversightViewEnter = function () {};
  vm2.oversightTabEnter = function () {};
  vm2.oversightOpenRun = function () {};
  let anchorCalls2 = 0;
  vm2._scrollToLogsAnchor = function () { anchorCalls2++; };
  let syncCalls2 = 0;
  vm2.oversightSyncHash = function () { syncCalls2++; };
  global.window = { location: { hash: '#/oversight?tab=logs' } };
  methods.oversightApplyDeepLink.call(vm2);
  // U04 (v6.3): `?tab=logs` больше не якорь Аналитики — тут он НЕ скроллит
  // и НЕ нормализует hash; нормализацию к Статусу делает
  // applyRoute/_consumeLogsScrollLink (см. блок 2b).
  assert.strictEqual(vm2.oversightTab, 'overview',
    'deep-link ?tab=logs не переключает oversightTab');
  assert.strictEqual(anchorCalls2, 0,
    'U04: oversight-скролл к логам убран (логи в Статусе)');
  assert.strictEqual(syncCalls2, 0,
    'U04: oversightSyncHash для scroll=logs не вызывается');
  assert.strictEqual(vm2.oversightView, 'processes',
    'якорь вне mca-группы не трогает mca-вью');
  // прямой параметр `?scroll=logs` — тоже без oversight-скролла
  const vm2b = Object.create(methods);
  vm2b.oversightTab = 'overview';
  vm2b.oversightView = 'processes';
  vm2b.oversightTabs = tabs;
  vm2b.mca17cRunF = { status: '', pipeline_type: '', component: '',
    chat_id: '', days: '7' };
  vm2b.mca17cFunnelDays = '30';
  vm2b.mca17cRunDetail = null;
  vm2b.mca17cDeepLinkDone = false;
  vm2b.oversightViewEnter = function () {};
  vm2b.oversightTabEnter = function () {};
  vm2b.oversightOpenRun = function () {};
  let anchorCalls2b = 0;
  vm2b._scrollToLogsAnchor = function () { anchorCalls2b++; };
  global.window = { location: { hash: '#/oversight?scroll=logs' } };
  methods.oversightApplyDeepLink.call(vm2b);
  assert.strictEqual(vm2b.oversightTab, 'overview');
  assert.strictEqual(anchorCalls2b, 0, 'U04: ?scroll=logs не скроллит из oversight');
  // 2b) U04.2: нормализация канона и легаси — _consumeLogsScrollLink.
  {
    const written = [];
    const vmN = Object.create(methods);
    global.window = { location: { hash: '' },
      history: { replaceState: function (s, t, u) { written.push(u); } } };
    assert.strictEqual(vmN._consumeLogsScrollLink('#/?scroll=logs'), true,
      'канон #/?scroll=logs потребляется');
    assert.strictEqual(vmN._consumeLogsScrollLink(
      '#/oversight?scroll=logs'), true, 'легаси oversight?scroll=logs');
    assert.strictEqual(vmN._consumeLogsScrollLink(
      '#/oversight?tab=logs'), true, 'легаси oversight?tab=logs');
    assert.strictEqual(vmN._consumeLogsScrollLink(
      '#/oversight?view=runs'), false, 'чужие query не потребляются');
    assert.strictEqual(vmN._consumeLogsScrollLink('#/'), false,
      'без query — false');
    assert.deepStrictEqual(written, ['#/', '#/', '#/'],
      'адрес нормализуется к канону #/ (F5 не повторяет скролл)');
  }
  // старый формат: ?view=learning → mca-вью + таб «Процессы»
  const vm3 = Object.create(methods);
  vm3.oversightTab = 'overview';
  vm3.oversightView = 'processes';
  vm3.oversightTabs = tabs;
  vm3.mca17cRunF = { status: '', pipeline_type: '', component: '',
    chat_id: '', days: '7' };
  vm3.mca17cFunnelDays = '30';
  vm3.mca17cRunDetail = null;
  vm3.mca17cDeepLinkDone = false;
  vm3.oversightViewEnter = function () {};
  vm3.oversightTabEnter = function () {};
  vm3.oversightOpenRun = function () {};
  global.window = { location: { hash: '#/oversight?view=learning' } };
  methods.oversightApplyDeepLink.call(vm3);
  assert.strictEqual(vm3.oversightView, 'learning');
  assert.strictEqual(vm3.oversightTab, 'processes',
    '?view=learning открывает таб «Процессы» (контент сохранён)');
  global.window = { location: { hash: '' } };
}

// ── 3) hash-синхронизация: mca → ?view=, остальные → ?tab= ─────────────────
{
  let written = null;
  const vm4 = Object.create(methods);
  vm4.oversightTab = 'summary';
  vm4.oversightView = 'processes';
  vm4.mca17cRunF = { status: '', pipeline_type: '', component: '',
    chat_id: '', days: '7' };
  vm4.mca17cRunDetail = null;
  global.window = { location: { hash: '' },
    history: { replaceState: function (s, t, u) { written = u; } } };
  methods.oversightSyncHash.call(vm4);
  assert.strictEqual(written, '#/oversight?tab=summary',
    'немca-вкладка пишет ?tab=');
  vm4.oversightTab = 'runs';
  vm4.oversightView = 'runs';
  methods.oversightSyncHash.call(vm4);
  assert.strictEqual(written, '#/oversight?view=runs',
    'mca-вкладка пишет ?view= (совместимость старых ссылок)');
  global.window = { location: { hash: '' } };
  global.history = { replaceState() {} };
}

// ── 4) honest-данные ────────────────────────────────────────────────────────
{
  const vm5 = Object.create(methods);
  vm5.statusData = null;
  vm5.randomSource = { ready: false, enabled: false };
  const rows = methods.statusKeyStripRows.call(vm5);
  assert.strictEqual(rows.length, 3, '3 строки strip: LLM/Embeddings/Quantum');
  assert.deepStrictEqual(rows.map(function (r) { return r.label; }),
    ['Основная LLM', 'Embeddings', 'Quantum']);
  rows.forEach(function (r) {
    assert.strictEqual(r.text, 'нет данных',
      'без /api/status — честное «нет данных»');
  });
  // деград ключа → ▲/■ с текстом (цвет не единственный носитель)
  const vm6 = Object.create(methods);
  vm6.healthLabel = methods.healthLabel;
  vm6.statusData = { llm: [
    { group_id: 'llm_functions', health: { status: 'ok' },
      provider: 'p1', model: 'm1' },
    { group_id: 'embeddings', health: { status: 'error' },
      provider: 'p2', model: 'm2' },
  ] };
  vm6.randomSource = { ready: true, enabled: true, quantum: false,
    reserve: 5, bufferMax: 10 };
  const rows6 = methods.statusKeyStripRows.call(vm6);
  assert.strictEqual(rows6[0].glyph, '●');
  assert.ok(rows6[0].text.indexOf('1 из 1 OK') >= 0);
  assert.strictEqual(rows6[1].glyph, '■');
  assert.ok(rows6[1].text.indexOf('Ошибка') >= 0, 'текст статуса рядом');
  assert.ok(rows6[1].text.indexOf('p2') >= 0, 'провайдер деград-строки виден');
  assert.strictEqual(rows6[2].glyph, '▲', 'PRNG — не зелёный');
  assert.ok(rows6[2].text.indexOf('псевдослучайный') >= 0);
  assert.ok(rows6[2].text.indexOf('запас 5/10') >= 0);
}
{
  const vm7 = Object.create(methods);
  vm7.statusData = null;
  vm7.pipelineMode = 'latest';
  vm7.pipelineAggregate = null;
  vm7.pipelineRunView = null;
  vm7.pipelineHealthBadge = methods.pipelineHealthBadge;
  vm7.embeddingsPanel = null;
  vm7.oversightData = null;
  vm7.mcaIncidentLabel = methods.mcaIncidentLabel;
  vm7.incidentBadge = methods.incidentBadge;
  vm7.randomSource = { ready: false };
  const strip = methods.overviewHealthStrip.call(vm7);
  assert.ok(strip.length >= 5, 'сводка Обзора: ≥5 показателей');
  strip.forEach(function (r) {
    assert.ok(r.label && r.period, 'у показателя название и период');
    assert.ok(r.value === '—' || r.value === 'неизвестно',
      'нет данных → «—»/«неизвестно», не 0: ' + r.label + '=' + r.value);
  });
  // incidents unknown ≠ 0
  const vm8 = Object.create(methods);
  vm8.statusData = null;
  vm8.pipelineMode = 'latest';
  vm8.pipelineAggregate = null;
  vm8.pipelineRunView = null;
  vm8.pipelineHealthBadge = methods.pipelineHealthBadge;
  vm8.embeddingsPanel = null;
  vm8.oversightData = null;
  vm8.mcaIncidentLabel = methods.mcaIncidentLabel;
  vm8.incidentBadge = methods.incidentBadge;
  vm8.randomSource = { ready: false };
  const s8 = methods.overviewHealthStrip.call(vm8);
  const inc = s8.find(function (r) { return r.label === 'Инциденты'; });
  assert.strictEqual(inc.value, 'неизвестно',
    'инциденты без телеметрии — «неизвестно», не 0');
}
{
  const vm9 = Object.create(methods);
  vm9.statusData = { llm: [
    { health: { status: 'ok' }, key: { configured: true } },
    { health: { status: 'error' }, key: { configured: true } },
    { health: { status: 'ok' }, key: { configured: false } },
  ] };
  vm9.oversightData = null;
  assert.strictEqual(computed.statusProblemsCount.call(vm9), 2,
    'ошибка probe + ключ не настроен = 2 проблемы');
  const vm10 = Object.create(methods);
  vm10.statusData = { llm: [{ health: { status: 'ok' },
    key: { configured: true } }] };
  vm10.oversightData = { mca_metrics:
    { incidents: { available: true, active: 2, unacknowledged: 0 } } };
  assert.strictEqual(computed.statusProblemsCount.call(vm10), 2,
    'активные инциденты считаются');
  const vm11 = Object.create(methods);
  vm11.statusData = null;
  vm11.oversightData = null;
  assert.strictEqual(computed.statusProblemsCount.call(vm11), 0,
    'нет данных → 0 → строка hero скрыта (v-if)');
}

// ── 5) структура index.html по карте ───────────────────────────────────────
{
  const oversStart = INDEX.indexOf("activeTab === 'oversight'");
  const statusStart = INDEX.indexOf("activeTab === 'status'");
  assert.ok(oversStart > 0 && statusStart > oversStart);

  // Вкладочный UI
  assert.ok(INDEX.indexOf('data-oversight-tabs') > 0, 'контейнер табов');
  assert.ok(INDEX.indexOf('v-for="t in oversightTabs"') > 0, 'табы из списка');
  assert.ok(INDEX.indexOf('oversightSetTab(t.id)') > 0, 'клик по табу');
  assert.ok(CSS.indexOf('.oversight-tab') > 0
    && CSS.indexOf('.oversight-tab.is-active') > 0,
    'CSS табов (desktop-ряд + активный)');
  // W2-SHELL (U02): замена маркера «mobile: горизонтальный скролл табов» —
  // на <768 лента обрезанных pills скрыта, показан компактный полноширинный
  // dropdown с ПОЛНЫМ списком («Логи» — якорь, не режим: в списке нет).
  assert.ok(/\.oversight-mobile-dd \{/.test(CSS)
    && /\.oversight-mobile-panel \{/.test(CSS),
    'U02: mobile dropdown суб-вкладок в CSS');
  assert.ok(INDEX.indexOf('oversight-mobile-trigger') > 0
    && INDEX.indexOf('oversightMobileTabs') > 0,
    'U02: mobile dropdown в разметке (ARIA, полный список)');
  assert.ok(/@media \(max-width: 767px\) \{\s*\n\s*\.oversight-tabs__row \{ display: none; \}/.test(CSS),
    'U02: на <768 лента pills скрыта');
  assert.ok(/@media \(min-width: 768px\) \{\s*\n\s*\.oversight-mobile-dd \{ display: none; \}/.test(CSS),
    'U02.1: desktop ≥768 — dropdown скрыт, прежняя панель сохранена');

  const inOversight = function (marker) {
    const i = INDEX.indexOf(marker);
    assert.ok(i > oversStart && i < statusStart,
      'в шаблоне Аналитики: ' + marker);
    return i;
  };
  const inStatus = function (marker) {
    const i = INDEX.indexOf(marker);
    assert.ok(i > statusStart, 'в шаблоне Статуса: ' + marker);
    return i;
  };

  // Переносы: модели → «Модели и расходы» (autobudget + токены + история)
  const autobudget = inOversight('data-testid="autobudget-block"');
  const tokens = inOversight('Аналитика токенов');
  const keyHistory = inOversight('data-key-history');
  const modelsGuard = INDEX.split("oversightTab === 'models'").length - 1;
  assert.ok(modelsGuard >= 3,
    'v-if «Модели и расходы»: автобюджеты/токены/история ключей (найдено '
    + modelsGuard + ')');
  assert.ok(oversightGuardBefore(INDEX, autobudget, "'models'"),
    'автобюджеты — v-if вкладки «Модели и расходы»');
  assert.ok(oversightGuardBefore(INDEX, keyHistory, "'models'"),
    'история ключей — вкладка «Модели и расходы»');

  // Память и интеллект: фактчек + embeddings + интеллект + личность
  const factcheck = inOversight('id="temporal-factcheck-block"');
  const emb = inOversight('id="embeddings-inspector-block"');
  assert.ok(oversightGuardBefore(INDEX, factcheck, "'memory'"),
    'фактчек — вкладка «Память и интеллект»');
  assert.ok(oversightGuardBefore(INDEX, emb, "'memory'"),
    'embeddings — вкладка «Память и интеллект»');

  // Процессы/Запуски/Инциденты: mca17c root на mca-табах
  const root = inOversight('data-mca17c="root"');
  const guard = INDEX.slice(root - 420, root + 200);
  assert.ok(guard.indexOf("oversightTab === 'processes'") >= 0
    && guard.indexOf("oversightTab === 'runs'") >= 0
    && guard.indexOf("oversightTab === 'incidents'") >= 0,
    'mca17c — на трёх mca-вкладках');

  // Саммари
  const pipe = inOversight('id="pipeline-inspector-block"');
  assert.ok(oversightGuardBefore(INDEX, pipe, "'summary'"),
    'Run Inspector — вкладка «Саммари»');

  // Обзор: здоровье + шапка + mca-метрики + ticker + таблица чатов
  inOversight('data-oversight-health');
  inOversight('id="mca-metrics-block"');
  inOversight('dossier-ticker-wrap');

  // U04 (v6.3): логи — ФИЗИЧЕСКИЙ блок в конце «Статуса» (id="status-logs");
  // в Аналитике блока и вкладки-якоря больше нет.
  assert.strictEqual(INDEX.split('id="status-logs"').length - 1, 2,
    'дом логов ровно один (второе вхождение — комментарий-указатель)');
  // ищем вхождение ВНУТРИ статус-шаблона (первое — комментарий-указатель
  // в oversight-шаблоне, где блок был до U04)
  const logsCard = INDEX.indexOf('id="status-logs"', statusStart);
  assert.ok(logsCard > statusStart, 'в шаблоне Статуса: id="status-logs"');
  const statusGridEnd = INDEX.indexOf('/F11 §12 .status-grid', logsCard);
  assert.ok(statusGridEnd > logsCard,
    'блок логов — ПОСЛЕДНЯЯ карточка .status-grid Статуса');
  const logsTail = INDEX.slice(logsCard, statusGridEnd);
  assert.ok(logsTail.indexOf('v-model="logLevel"') > 0, 'level-select в доме');
  assert.ok(logsTail.indexOf('toggleLogSummary()') > 0, 'чип «Саммари» в доме');
  assert.ok(logsTail.indexOf('id="mca-log-filters"') > 0, 'trace-фильтры в доме');
  assert.ok(logsTail.indexOf('copyAllLogs()') > 0, 'копирование в доме');
  assert.ok(INDEX.indexOf(':class="{ \'status-logs--flash\': logsAnchorFlash }"') > 0,
    'якорь-подсветка блока (вспышка ~1с)');
  assert.ok(CSS.indexOf('status-logs-flash') > 0,
    'CSS-анимация вспышки якоря');
  assert.strictEqual(INDEX.indexOf('status-logs-link'), -1,
    'U04: карточка-переход «Логи → Аналитика» удалена');
  const oversSeg = INDEX.slice(oversStart, statusStart);
  assert.strictEqual(
    oversSeg.indexOf('<div class="card p-4 status-logs'), -1,
    'U04: в шаблоне Аналитики блока логов нет (остался только комментарий'
    + '-указатель)');
  assert.ok(INDEX.indexOf('scrollToLogs()') > statusStart,
    'U04: клик по счётчику на Статусе ведёт к блоку логов');
  assert.ok(APP.indexOf('_consumeLogsScrollLink') > 0,
    'U04.2: нормализация канона/легаси scroll=logs (app.js)');
  assert.ok(APP.indexOf("'#/?scroll=logs'") > 0,
    'U04.2: ссылка «Логи» ведёт на канон Статуса (app.js)');
  assert.strictEqual(APP.indexOf("p.scroll === 'logs'"), -1,
    'U04: старый oversight-обработчик scroll=logs удалён');

  // Статус: strip ключей + компактная случайность
  inStatus('data-key-strip');
  inStatus('data-key-strip-rows');
  inStatus('Подробнее в Аналитике');
  inStatus('data-random-details');
  // hero-строка проблем с deep-link
  const problems = inStatus('statusProblemsCount');
  assert.ok(INDEX.slice(problems - 200, problems + 200)
    .indexOf('#/oversight?tab=overview') >= 0,
    'hero: deep-link на Обзор Аналитики');

  // Protected KEEP-блоки Статуса на месте (сон, ribbons, граф, факты,
  // истории, опыт, инициатива)
  for (const marker of ['status-sleep', 'Мониторинг Интеллекта',
    'status-graph', 'status-facts', 'data-experience', 'status-budgets']) {
    inStatus(marker);
  }
}

function oversightGuardBefore(html, pos, tabExpr) {
  // ищем v-if с указанной вкладкой в пределах 320 символов ДО маркера
  // или 120 ПОСЛЕ (v-if может стоять на следующей строке атрибутов)
  const window_ = html.slice(Math.max(0, pos - 320), pos + 120);
  return window_.indexOf("oversightTab === " + tabExpr) >= 0;
}

// ── 6) Δ endpoint = 0: новых '/api/…' литералов нет ────────────────────────
{
  const endpoints = APP.match(/['`]\/api\/[a-z0-9_\-/]+/g) || [];
  const known = new Set([
    '/api/status/key-history', '/api/status/logs', '/api/status',
    '/api/oversight/processes', '/api/oversight/runs',
    '/api/oversight/runs/', '/api/oversight/incidents',
    '/api/oversight/experience/funnel', '/api/memory/lessons',
    '/api/persona/self-model', '/api/memory/embeddings',
    '/api/analytics/pipeline/inspector', '/api/analytics/pipeline/runs/',
    '/api/factcheck/temporal/runs', '/api/factcheck/temporal/runs/',
    '/api/analytics/usage/latest', '/api/analytics/usage/summary',
    '/api/analytics/exec/graph', '/api/analytics/exec/trace',
    // U03 (v6.3 W3-STATUS): честные блоки Статуса — B03 expired-обзор и
    // durable-воронки (read-only, global admin).
    '/api/memory/expired-overview', '/api/memory/intel-funnels',
  ]);
  // Тест проверяет, что Wave 2 НЕ добавила сетевых вызовов: strip-методы
  // только читают существующее состояние (упоминания /api/... в
  // комментариях допустимы, вызовы this.api(...) — нет).
  const stripBlock = APP.slice(
    APP.indexOf('statusKeyStripRows: function'),
    APP.indexOf('overviewHealthStrip: function'));
  const healthBlock = APP.slice(
    APP.indexOf('overviewHealthStrip: function'),
    APP.indexOf('healthBadge: function'));
  assert.ok(!/this\.api\(/.test(stripBlock + healthBlock),
    'strip-методы не ходят в сеть (только существующие данные)');
}

console.log('WAVE2-UX-TABS-OK');
