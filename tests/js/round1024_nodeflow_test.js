'use strict';
/* F3 round1024 (token-metrics-nodeflow-round1024, ADR-1024-7), review iter1 —
 * РЕАЛЬНЫЙ JS-тест визуального дерева вызова (Node Flow) в «Сводке»:
 *   - детерминированная проекция `steps[]` единым проходом (tokenFlowTree);
 *   - двухслойный вызов (stage1+stage2) — спина, без ложной ветки;
 *   - tool-под-нода — в `.children` Синтезатора (ветка), НЕ на спине;
 *   - смешанные наборы: `[stage1, stage2, single]` и дубликат `stage1` не
 *     теряются (регресс High #2);
 *   - `single`/`image` — линейно, без «Синтезатор→Вербализатор»;
 *   - пустой ответ → пустое состояние; «оц.»/«цена неизвестна»;
 *   - агрегация price_known/estimated в ноду «Итог» (Medium #3);
 *   - computed (не methods) + single-eval в шаблоне (Medium #4);
 *   - wiring: шаблон рендерит ветку из `.children`, `edges`/`hasBranch` живы;
 *   - kill-switch uiFlag('TOKEN_FLOW_NODEFLOW_ENABLED');
 *   - статика: нейминг, CSP/no-CDN.
 *
 * Запуск: node tests/js/round1024_nodeflow_test.js  → NODEFLOW-UNIT-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component(name, compOpts) {
        global.__components = global.__components || {};
        global.__components[name] = compOpts;
      },
      provide() {}, use() {}, mount() {},
    };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
const _bodyChildren = [];
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() {
        const idx = _bodyChildren.indexOf(this);
        if (idx >= 0) _bodyChildren.splice(idx, 1);
      },
    };
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) {
      const idx = _bodyChildren.indexOf(el);
      if (idx >= 0) _bodyChildren.splice(idx, 1);
      return el;
    },
  },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('x'); } } },
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

const ROOT = path.join(__dirname, '..', '..');
require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;
assert(methods && methods.uiFlag, 'root.methods.uiFlag не найден');
assert(computed && computed.tokenFlowTree,
  'tokenFlowTree должен быть computed (не method) — Medium #4');
assert(computed && computed.tokenSeriesBars,
  'tokenSeriesBars должен быть computed (не method) — Medium #4');
assert(!methods.tokenFlowTree && !methods.tokenSeriesBars,
  'дубли methods.tokenFlowTree/tokenSeriesBars должны быть удалены');

function tree(steps, total, ts) {
  return computed.tokenFlowTree.call({
    tokenAnalyticsLatest: { steps: steps, total: total || {}, ts: ts || null },
    _tokenFlowTimestamp: methods._tokenFlowTimestamp,
  });
}
function kinds(t) { return t.nodes.map(function (n) { return n.kind; }); }
function edgeSet(t) {
  return t.edges.map(function (e) { return e.from + '>' + e.to; });
}
function findNode(t, kind) {
  return t.nodes.find(function (n) { return n.kind === kind; });
}

// ── 1. Двухслойный вызов: root → synthesizer → verbalizer → result ──────────
(function () {
  const steps = [
    { step: 'stage1', module: 'direct_chat', input_tokens: 4000,
      output_tokens: 100, cost_usd: 0.001, price_known: true },
    { step: 'stage2', module: 'direct_chat', input_tokens: 500,
      output_tokens: 600, cost_usd: 0.002, price_known: true },
  ];
  const t = tree(steps, { input_tokens: 4500, output_tokens: 700,
                          cost_usd: 0.003, calls: 2 }, '2026-09-19T12:00:00+00:00');
  assert.deepStrictEqual(kinds(t),
    ['root', 'synthesizer', 'verbalizer', 'result'], 'порядок узлов двухслойного');
  assert.deepStrictEqual(t.main.map(function (n) { return n.kind; }),
    ['root', 'synthesizer', 'verbalizer', 'result'], 'спина двухслойного');
  assert.strictEqual(t.nodes[0].title, 'Запрос юзера');
  assert.strictEqual(t.nodes[1].title, 'Синтезатор');
  assert.strictEqual(t.nodes[2].title, 'Вербализатор');
  assert.strictEqual(t.nodes[3].title, 'Итог');
  assert.deepStrictEqual(edgeSet(t),
    ['root>n-0', 'n-0>n-1', 'n-1>result'], 'рёбра двухслойного');
  assert.strictEqual(t.hasBranch, false, 'без tool — ветвления нет');
  const res = t.nodes[3];
  assert.strictEqual(res.input, 4500);
  assert.strictEqual(res.output, 700);
  assert.strictEqual(res.cost, 0.003);
  assert(t.nodes[0].note.indexOf('последний вызов') >= 0, 'подпись времени');
})();

// ── 2. Ветвление: tool-под-нода — в children Синтезатора, НЕ на спине ───────
(function () {
  const steps = [
    { step: 'stage1', input_tokens: 100, output_tokens: 10, cost_usd: 0.001 },
    { step: 'tool', tool_name: 'web_search', input_tokens: 200,
      output_tokens: 20, cost_usd: 0.0005 },
    { step: 'stage2', input_tokens: 300, output_tokens: 30, cost_usd: 0.002 },
  ];
  const t = tree(steps, { input_tokens: 600, output_tokens: 60, cost_usd: 0.0035 });
  assert(t.hasBranch === true, 'tool → hasBranch=true');
  // Плоский контракт §5 не изменился.
  assert.deepStrictEqual(kinds(t),
    ['root', 'synthesizer', 'tool', 'verbalizer', 'result']);
  // tool НЕ звено спины.
  assert(!t.main.some(function (n) { return n.kind === 'tool'; }),
    'tool-нода не должна быть на спине (регресс High #1)');
  const synth = t.main[1];
  assert.strictEqual(synth.kind, 'synthesizer');
  assert.strictEqual(synth.children.length, 1, 'ветка Синтезатора: 1 под-нода');
  assert.strictEqual(synth.children[0].kind, 'tool');
  assert.strictEqual(synth.children[0].title, 'Инструмент: web_search');
  // Рёбра: ветка synth→tool, спина synth→verb→result; БЕЗ tool→verb.
  assert(edgeSet(t).indexOf('n-0>tool-1') >= 0, 'ребро Синтезатор→Инструмент');
  assert(edgeSet(t).indexOf('n-0>n-2') >= 0, 'ребро Синтезатор→Вербализатор');
  assert(edgeSet(t).indexOf('tool-1>n-2') === -1,
    'ложного ребра tool→verbalizer быть не должно');
})();

// ── 3. single: линейная цепочка без ложного Вербализатора ───────────────────
(function () {
  const t = tree([{ step: 'single', input_tokens: 50, output_tokens: 5,
                    cost_usd: 0.0001 }],
                 { input_tokens: 50, output_tokens: 5, cost_usd: 0.0001 });
  assert.deepStrictEqual(kinds(t), ['root', 'single', 'result']);
  assert.deepStrictEqual(edgeSet(t), ['root>n-0', 'n-0>result']);
  assert.strictEqual(t.hasBranch, false);
  assert(!kinds(t).includes('verbalizer') && !kinds(t).includes('synthesizer'),
    'у single нет ложной ветки Синтезатор→Вербализатор');
  assert.strictEqual(t.nodes[1].title, 'Один вызов');
})();

// ── 4. image: линейно, price_known=false → «цена неизвестна» ────────────────
(function () {
  const t = tree([{ step: 'image', input_tokens: 0, output_tokens: 0,
                    cost_usd: 0, price_known: false }],
                 { input_tokens: 0, output_tokens: 0, cost_usd: 0 });
  assert.deepStrictEqual(kinds(t), ['root', 'image', 'result']);
  assert.strictEqual(t.nodes[1].title, 'Изображение');
  assert.strictEqual(t.nodes[1].price_known, false, 'цена неизвестна');
  assert.strictEqual(t.hasBranch, false);
  // Medium #3: агрегат «Итог» тоже «цена неизвестна».
  assert.strictEqual(t.main[t.main.length - 1].price_known, false,
    'Итог наследует price_known=false');
})();

// ── 5. Пустой ответ API → пустое состояние (fail-open) ──────────────────────
(function () {
  const t = tree([], {});
  assert.strictEqual(t.empty, true);
  assert.deepStrictEqual(t.nodes, []);
  assert.deepStrictEqual(t.edges, []);
  assert.deepStrictEqual(t.main, []);
  const t2 = computed.tokenFlowTree.call({ tokenAnalyticsLatest: null });
  assert.strictEqual(t2.empty, true);
})();

// ── 6. tokens_estimated=true → пометка «оц.» ────────────────────────────────
(function () {
  const t = tree([{ step: 'single', input_tokens: 10, output_tokens: 2,
                    cost_usd: 0.00001, tokens_estimated: true }],
                 { input_tokens: 10, output_tokens: 2, cost_usd: 0.00001 });
  const node = findNode(t, 'single');
  assert.strictEqual(node.estimated, true, 'оц. для estimated');
  assert.strictEqual(t.main[t.main.length - 1].estimated, true,
    'Итог наследует estimated');
})();

// ── 7. Смешанный набор: нераспознанный step → отдельная плашка ──────────────
(function () {
  const t = tree([{ step: 'mystery_step', input_tokens: 1, output_tokens: 1,
                    cost_usd: 0 }], {});
  assert.deepStrictEqual(kinds(t), ['root', 'other', 'result']);
  assert(t.nodes[1].title.indexOf('mystery_step') >= 0,
    'неизвестный step выводится плашкой-заголовком');
})();

// ── 8. High #2: смешанный набор [stage1, stage2, single] не теряет single ───
(function () {
  const t = tree([
    { step: 'stage1' }, { step: 'stage2' }, { step: 'single' },
  ], {});
  assert.deepStrictEqual(kinds(t),
    ['root', 'synthesizer', 'verbalizer', 'single', 'result'],
    'single в двухслойном наборе не должен выпадать');
  assert(edgeSet(t).indexOf('n-1>n-2') >= 0, 'спина продолжается на single');
})();

// ── 9. High #2: дубликат stage1 → отдельные ноды (ретрай) ───────────────────
(function () {
  const t = tree([
    { step: 'stage1', output_tokens: 1 }, { step: 'stage1', output_tokens: 2 },
    { step: 'stage2' },
  ], {});
  assert.deepStrictEqual(kinds(t),
    ['root', 'synthesizer', 'synthesizer', 'verbalizer', 'result'],
    'повторный stage1 сохраняется отдельной нодой');
  assert.strictEqual(t.nodes[1].id !== t.nodes[2].id, true, 'уникальные id');
})();

// ── 10. Medium #3: агрегация price_known/estimated в «Итог» ─────────────────
(function () {
  const ok = tree([
    { step: 'stage1', price_known: true, tokens_estimated: false },
    { step: 'stage2', price_known: true, tokens_estimated: false },
  ], {});
  const r1 = ok.main[ok.main.length - 1];
  assert.strictEqual(r1.price_known, true);
  assert.strictEqual(r1.estimated, false);

  const mixed = tree([
    { step: 'stage1', price_known: false, tokens_estimated: true },
    { step: 'stage2', price_known: true, tokens_estimated: false },
  ], {});
  const r2 = mixed.main[mixed.main.length - 1];
  assert.strictEqual(r2.price_known, false, 'любой шаг без цены → Итог без цены');
  assert.strictEqual(r2.estimated, true, 'любой шаг-оценка → Итог с «оц.»');
})();

// ── 11. tokenSeriesBars — computed (Medium #4) ──────────────────────────────
(function () {
  const bars = computed.tokenSeriesBars.call({
    tokenAnalyticsSummary: { series: [
      { bucket: '2026-09-19T12:00:00+00:00', cost_usd: 1, calls: 2 },
      { bucket: '2026-09-19T13:00:00+00:00', cost_usd: 0, calls: 0 },
    ] },
  });
  assert.strictEqual(bars.length, 2);
  assert.strictEqual(bars[0].height, 100, 'первый бакет — максимум');
  assert(bars[0].label.indexOf('2026-09-19 12:00') === 0, 'человекочитаемая метка');
  assert.strictEqual(
    computed.tokenSeriesBars.call({ tokenAnalyticsSummary: null }).length, 0);
})();

// ── 12. Kill-switch uiFlag (ADR-1024-13) ────────────────────────────────────
(function () {
  assert.strictEqual(methods.uiFlag.call({ me: null },
    'TOKEN_FLOW_NODEFLOW_ENABLED'), true);
  assert.strictEqual(methods.uiFlag.call({ me: {} },
    'TOKEN_FLOW_NODEFLOW_ENABLED'), true);
  assert.strictEqual(methods.uiFlag.call(
    { me: { ui_flags: { TOKEN_FLOW_NODEFLOW_ENABLED: false } } },
    'TOKEN_FLOW_NODEFLOW_ENABLED'), false);
  assert.strictEqual(methods.uiFlag.call(
    { me: { ui_flags: { TOKEN_FLOW_NODEFLOW_ENABLED: true } } },
    'TOKEN_FLOW_NODEFLOW_ENABLED'), true);
  assert.strictEqual(methods.uiFlag.call(
    { me: { ui_flags: {} } }, 'UNKNOWN_FLAG'), true);
})();

// ── 13. Wiring: шаблон РЕНДЕРИТ ветку (edges/children), не линейный список ──
(function () {
  const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
  // Ветка — отдельный контейнер с под-нодами из `.children` (High #1).
  assert(INDEX.indexOf('class="token-flow__branch"') !== -1,
    'шаблон должен иметь контейнер ветки .token-flow__branch');
  assert(INDEX.indexOf('v-for="child in node.children"') !== -1,
    'ветка рендерится из node.children (производное от edges)');
  assert(INDEX.indexOf('node.kind === \'result\'') === -1,
    'старый линейный коннектор «после каждой ноды» должен быть удалён');
  // Коннектор только к следующей ноде спины.
  assert(INDEX.indexOf('idx < tokenFlowTree.main.length - 1') !== -1,
    'коннектор ↓ гейтится наличием следующей ноды спины');
  // Computed-использование (без вызовов-функций).
  assert(INDEX.indexOf('tokenFlowTree.main') !== -1 &&
    INDEX.indexOf('tokenFlowTree().nodes') === -1,
    'шаблон использует computed tokenFlowTree.main');
  assert(INDEX.indexOf('tokenSeriesBars.length') !== -1 &&
    INDEX.indexOf('tokenSeriesBars()') === -1,
    'шаблон использует computed tokenSeriesBars');
  // OFF-ветка: заголовок «График расходов» и ось — внутри ON-гейта.
  assert(INDEX.indexOf('График расходов') !== -1);
  assert(/uiFlag\('TOKEN_FLOW_NODEFLOW_ENABLED'\) && tokenSeriesBars\.length/
    .test(INDEX), 'ось графика гейтится флагом (OFF = 10.23)');
  // app.js: hasBranch/edges живы и участвуют в построении.
  assert(APP_JS.indexOf('hasBranch') !== -1 && APP_JS.indexOf('edges') !== -1);
  assert(APP_JS.indexOf('children.push') !== -1, 'ветки строятся из edges');
})();

// ── 14. Статические инварианты: нейминг + CSP/no-CDN ────────────────────────
(function () {
  const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
  assert(INDEX.indexOf('Аналитика токенов') !== -1, 'заголовок «Аналитика токенов»');
  assert(INDEX.indexOf('Последний запрос (Дерево вызова)') !== -1);
  assert(INDEX.indexOf('Token Metrics') === -1, 'англо-жаргон «Token Metrics»');
  assert(INDEX.indexOf("uiFlag('TOKEN_FLOW_NODEFLOW_ENABLED')") !== -1);
  assert(APP_JS.indexOf('ui_flags') !== -1, 'uiFlag читает this.me.ui_flags');
  for (const lib of ['mermaid', 'cytoscape', 'd3.min.js', 'chart.js',
                     'unpkg.com', 'cdn.jsdelivr.net']) {
    assert(APP_JS.indexOf(lib) === -1, 'запрещена граф-библиотека: ' + lib);
    assert(INDEX.indexOf(lib) === -1, 'запрещена граф-библиотека: ' + lib);
  }
  assert(INDEX.indexOf('http://') === -1 && INDEX.indexOf('https://') === -1,
    'без внешних ресурсов (CSP/zero-build)');
})();

console.log('NODEFLOW-UNIT-OK');
