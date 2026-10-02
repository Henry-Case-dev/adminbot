'use strict';
/* ASAP-4 волна E (T-4441–T-4446, spec §5 E.2/E.3, §61/§62/§63/§76) —
 * Run Inspector «Пайплайн саммари» + Embedding Inspector (реальная логика
 * web/app.js + разметка web/index.html).
 *
 * Проверяет:
 *   (a) data-состояние виджетов объявлено (pipeline…/embeddings…);
 *   (b) методы существуют (load/set/open/clear/toggle/badge/fmt/polling);
 *   (c) computed существуют и читаются как свойства (урок H-ASAP31-2);
 *   (d) health-бейдж — ТЕКСТОВЫЙ, без opaque score (§61.13):
 *       healthy→«Здоров»/badge-ok, degraded→«С деградацией»/badge-warn,
 *       failed→«Не издано»/badge-err, прочее→«Не завершён»;
 *   (e) ветки ТЕКСТ/ОБЛОЖКА раздельны в проекции (§61.8);
 *   (f) setPipelineMode нормализует режим; drill-down run_id; tap-узел;
 *   (g) live polling (§61.15): 15с, только latest и без drill-down;
 *   (h) fail-open: ошибка API → pipelineData null, не бросает;
 *   (i) разметка index.html: три режима (§61.4), coverage-карточка (§61.6),
 *       значки ✓/⚠/✕/○/… с текстовым label (§61.2), RU-переводы причин,
 *       «Обложка — отдельная ветка», developer details, список runs
 *       (§61.10), Embedding Inspector с «только алиасы» (§63);
 *   (j) R17: в блоке виджетов нет ключей/значений секретов.
 *
 * Запуск: node tests/js/round1030_pipeline_inspector_test.js
 *          → PIPELINE-INSPECTOR-OK
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
const _storage = {
  _s: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; }, localStorage: _storage,
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const data = captured.data();
const methods = captured.methods;
const computed = captured.computed;

// (a) data-состояние
['pipelineMode', 'pipelineData', 'pipelineBusy', 'pipelineTimer',
 'pipelineOpenNode', 'pipelineSelectedRunId', 'embeddingsPanel',
 'embeddingsBusy'].forEach(function (key) {
  assert.ok(Object.prototype.hasOwnProperty.call(data, key),
    'a: data.' + key + ' объявлен');
});
assert.strictEqual(data.pipelineMode, 'latest', 'a: режим по умолчанию latest');

// (b) методы
['loadPipelineInspector', 'setPipelineMode', 'openPipelineRun',
 'clearPipelineRunSelection', 'togglePipelineNode', 'pipelineHealthBadge',
 'fmtSec', 'pctLabel', 'startPipelinePolling', 'stopPipelinePolling',
 'loadEmbeddingsPanel'].forEach(function (name) {
  assert.strictEqual(typeof methods[name], 'function', 'b: метод ' + name);
});

// (c) computed — читаются шаблоном как свойства (без скобок)
['pipelineRunView', 'pipelineAggregate', 'pipelineRuns', 'pipelineNodesText',
 'pipelineNodesCover', 'pipelineCoverageLine', 'pipelinePublicationLine',
 'pipelineRunShortId', 'pipelineRunDuration', 'embeddingsAliases']
  .forEach(function (name) {
    assert.strictEqual(typeof computed[name], 'function',
      'c: computed.' + name);
  });

// (d) health-бейдж — текстовый, без score (§61.13)
const badge = methods.pipelineHealthBadge;
assert.deepStrictEqual(badge('healthy'),
  { cls: 'badge-ok', text: 'Здоров' }, 'd: healthy');
assert.deepStrictEqual(badge('degraded'),
  { cls: 'badge-warn', text: 'С деградацией' }, 'd: degraded');
assert.deepStrictEqual(badge('failed'),
  { cls: 'badge-err', text: 'Не издано' }, 'd: failed');
assert.deepStrictEqual(badge('incomplete'),
  { cls: 'badge-muted', text: 'Не завершён' }, 'd: incomplete');
assert.deepStrictEqual(badge(undefined),
  { cls: 'badge-muted', text: 'Не завершён' }, 'd: unknown → не завершён');
Object.values({}).forEach(function () {});
['Здоров', 'С деградацией', 'Не издано', 'Не завершён'].forEach(
  function (label) {
    assert.ok(!/\d/.test(label), 'd: бейдж без числового score: ' + label);
  });

// (e) ветки раздельны (§61.8). NB: computed'ы цепочатся через
// this.pipelineRunView → на тестовом ctx вычисляем его заранее.
function withView(pipelineData, pipelineSelectedRunId) {
  var ctx = { pipelineData: pipelineData,
              pipelineSelectedRunId: pipelineSelectedRunId || '' };
  ctx.pipelineRunView = computed.pipelineRunView.call(ctx);
  return ctx;
}
const ctxNodes = withView({ run: { nodes: [
  { key: 'source', branch: 'text' },
  { key: 'l1', branch: 'text' },
  { key: 'base_cover', branch: 'cover' },
  { key: 'style_edit', branch: 'cover' },
] } });
const textKeys = computed.pipelineNodesText.call(ctxNodes)
  .map(function (n) { return n.key; });
const coverKeys = computed.pipelineNodesCover.call(ctxNodes)
  .map(function (n) { return n.key; });
assert.deepStrictEqual(textKeys, ['source', 'l1'], 'e: текстовая ветка');
assert.deepStrictEqual(coverKeys, ['base_cover', 'style_edit'],
  'e: ветка обложки');
assert.strictEqual(
  computed.pipelineNodesText.call(ctxNodes).length
  + computed.pipelineNodesCover.call(ctxNodes).length, 4, 'e: без потерь');

// (e2) coverage/publication строки (§61.6/§61.1)
const ctxLines = withView({ run: {
  coverage: { total: 688, considered: 307, percent: 44.6, full: false },
  publication: { status: 'ok', channel: 'rich', message_id: 777 },
} });
assert.ok(computed.pipelineCoverageLine.call(ctxLines)
  .indexOf('307 / 688') >= 0, 'e2: coverage 307/688');
assert.ok(computed.pipelineCoverageLine.call(ctxLines)
  .indexOf('44.6%') >= 0, 'e2: coverage 44.6%');
assert.ok(computed.pipelinePublicationLine.call(ctxLines)
  .indexOf('RichMessage') >= 0, 'e2: публикация rich');
assert.ok(computed.pipelinePublicationLine.call(ctxLines)
  .indexOf('777') >= 0, 'e2: message id виден');

// (e3) drill-down: selected_run приоритетнее run
const ctxSel = withView(
  { run: { run_id: 'latest' }, selected_run: { run_id: 'r-9' } }, 'r-9');
assert.strictEqual(computed.pipelineRunView.call(ctxSel).run_id, 'r-9',
  'e3: drill-down карта выбранного run');

// (f) setPipelineMode / drill-down / tap
const ctxMode = {
  pipelineSelectedRunId: 'r-old', loadPipelineInspector() { this._loaded = 1; },
};
methods.setPipelineMode.call(ctxMode, '7d');
assert.strictEqual(ctxMode.pipelineMode, '7d', 'f: режим 7d');
assert.strictEqual(ctxMode.pipelineSelectedRunId, '', 'f: сброс drill-down');
methods.setPipelineMode.call(ctxMode, 'мусор');
assert.strictEqual(ctxMode.pipelineMode, 'latest', 'f: неизвестный → latest');
assert.strictEqual(ctxMode._loaded, 1, 'f: перезагрузка после смены режима');

const ctxTap = { pipelineOpenNode: '' };
methods.togglePipelineNode.call(ctxTap, 'l2');
assert.strictEqual(ctxTap.pipelineOpenNode, 'l2', 'f: tap раскрывает узел');
methods.togglePipelineNode.call(ctxTap, 'l2');
assert.strictEqual(ctxTap.pipelineOpenNode, '', 'f: повторный tap закрывает');

// fmtSec/pctLabel — человекочитаемо
assert.strictEqual(methods.fmtSec(42000), '42.0с');
assert.strictEqual(methods.fmtSec(900), '900 мс');
assert.strictEqual(methods.fmtSec(null), '—');
assert.strictEqual(methods.pctLabel(87.5), '87.5%');
assert.strictEqual(methods.pctLabel(null), '—');

// (g) live polling (§61.15): 15с, только latest и без активного drill-down
let intervalMs = null;
let intervalFn = null;
let cleared = 0;
const _realSetInterval = global.setInterval;
const _realClearInterval = global.clearInterval;
global.setInterval = function (fn, ms) { intervalFn = fn; intervalMs = ms; return 1; };
global.clearInterval = function () { cleared += 1; };
try {
  const ctxPoll = {
    pipelineTimer: null, pipelineMode: 'latest',
    pipelineBusy: false, pipelineSelectedRunId: '',
    _calls: 0,
    loadPipelineInspector() { this._calls += 1; },
  };
  methods.startPipelinePolling.call(ctxPoll);
  assert.strictEqual(intervalMs, 15000, 'g: интервал 15с');
  assert.ok(ctxPoll.pipelineTimer, 'g: таймер установлен');
  intervalFn.call(ctxPoll);
  assert.strictEqual(ctxPoll._calls, 1, 'g: latest обновляется');
  ctxPoll.pipelineMode = '24h';
  intervalFn.call(ctxPoll);
  assert.strictEqual(ctxPoll._calls, 1, 'g: агрегатные режимы не поллерятся');
  ctxPoll.pipelineMode = 'latest';
  ctxPoll.pipelineBusy = true;
  intervalFn.call(ctxPoll);
  assert.strictEqual(ctxPoll._calls, 1, 'g: busy — без запроса');
  ctxPoll.pipelineBusy = false;
  ctxPoll.pipelineSelectedRunId = 'r-9';
  intervalFn.call(ctxPoll);
  assert.strictEqual(ctxPoll._calls, 1, 'g: drill-down — без поллинга');
  methods.stopPipelinePolling.call(ctxPoll);
  assert.strictEqual(ctxPoll.pipelineTimer, null, 'g: стоп очищает таймер');
  assert.strictEqual(cleared, 1, 'g: clearInterval вызван');
  // повторный старт без утечки таймеров
  methods.startPipelinePolling.call(ctxPoll);
  intervalMs = null;
  methods.startPipelinePolling.call(ctxPoll);
  assert.strictEqual(intervalMs, null, 'g: повторный старт — no-op');
} finally {
  global.setInterval = _realSetInterval;
  global.clearInterval = _realClearInterval;
}

// (h) fail-open: ошибка API не бросает
(async function () {
  const ctxFail = {
    pipelineMode: 'latest', pipelineData: { old: true },
    pipelineSelectedRunId: '',
    pipelineBusy: true,
    async api() { throw new Error('boom'); },
  };
  await methods.loadPipelineInspector.call(ctxFail);
  assert.strictEqual(ctxFail.pipelineData, null, 'h: ошибка → null');
  assert.strictEqual(ctxFail.pipelineBusy, false, 'h: busy снят');

  // успешная загрузка latest
  const ctxOk = {
    pipelineMode: 'latest', pipelineData: null,
    pipelineSelectedRunId: '', pipelineBusy: true,
    async api(url) {
      assert.ok(url.indexOf('/api/analytics/pipeline/inspector') === 0,
        'h: endpoint inspector');
      return { mode: 'latest', run: { run_id: 'r1' }, runs: [] };
    },
  };
  await methods.loadPipelineInspector.call(ctxOk);
  assert.strictEqual(ctxOk.pipelineData.run.run_id, 'r1', 'h: данные в state');

  // embeddings: endpoint + alias-only алиасы (§63)
  const ctxEmb = {
    embeddingsPanel: null, embeddingsBusy: true,
    async api(url) {
      assert.strictEqual(url, '/api/memory/embeddings', 'h: endpoint panel');
      return { vector_memory: { indexes: [], lease: null },
               provider: { credential_aliases: ['primary', 'fallback_1'] } };
    },
  };
  await methods.loadEmbeddingsPanel.call(ctxEmb);
  assert.strictEqual(ctxEmb.embeddingsBusy, false, 'h: busy снят');
  const ctxAlias = { embeddingsPanel: ctxEmb.embeddingsPanel };
  assert.strictEqual(computed.embeddingsAliases.call(ctxAlias),
    'primary, fallback_1', 'h: алиасы через запятую');
  const ctxNoAlias = { embeddingsPanel: { provider: null } };
  assert.strictEqual(computed.embeddingsAliases.call(ctxNoAlias), '—',
    'h: без ключей — прочерк');

  console.log('PIPELINE-INSPECTOR-OK');
})().catch(function (e) {
  console.error('FAIL:', e && e.message);
  process.exit(1);
});

// (i) разметка index.html
const INDEX = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');

function mustContain(needle, what) {
  assert.ok(INDEX.indexOf(needle) >= 0, 'i: ' + what + ' (' + needle + ')');
}
mustContain('pipeline-inspector-block', 'блок Run Inspector');
mustContain('Пайплайн саммари', 'заголовок виджета');
mustContain('Последний запуск', 'режим §61.4: последний запуск');
mustContain('За 24 часа', 'режим §61.4: 24 часа');
mustContain('7 дней', 'режим §61.4: 7 дней');
mustContain('Обложка — отдельная ветка', 'ветка обложки отдельна (§61.8)');
mustContain('Неполное саммари', 'coverage-деградация видна (§61.6)');
mustContain('Developer details', 'developer collapsible (§76)');
mustContain('Последние запуски', 'список runs (§61.10)');
mustContain('← к последнему', 'выход из drill-down');
mustContain('embeddings-inspector-block', 'блок Embedding Inspector');
mustContain('только алиасы, без ключей', '§63: алиасы, не ключи');
mustContain('Квота-группы', '§62: квота-группы');
mustContain('429 за 10 мин', '§62: 429-счётчик');
mustContain('Кулдаун до', '§62: cooldown');
mustContain('pipe-timeline', 'вертикальный timeline (§61.14)');
mustContain('pipe-node__icon', 'значки статусов');
// Значки ✓/⚠/✕/○/… присутствуют (цвет не единственный носитель, §61.2).
['✓', '⚠', '✕', '○'].forEach(function (icon) {
  assert.ok(INDEX.indexOf(icon) >= 0, 'i: значок ' + icon);
});

// (j) R17: в блоке виджетов нет ключей/секретов
const start = INDEX.indexOf('pipeline-inspector-block');
const end = INDEX.indexOf('embeddings-inspector-block');
assert.ok(start > 0 && end > start, 'j: блоки найдены');
const widgetHtml = INDEX.slice(start, end + 800);
['api_key', 'apikey', 'secret_value', 'credential_value'].forEach(
  function (bad) {
    assert.ok(widgetHtml.toLowerCase().indexOf(bad) < 0,
      'j: нет ' + bad + ' в разметке виджетов');
  });

console.log('PIPELINE-INSPECTOR-STATIC-OK');
