'use strict';
/* F3 round1024 (token-metrics-nodeflow-round1024, ADR-1024-7) — РЕАЛЬНЫЙ
 * JS-тест визуального дерева вызова (Node Flow) в разделе «Сводка»:
 *   - детерминированная проекция `steps[]` → узлы/рёбра (tokenFlowTree());
 *   - двухслойный вызов (stage1+stage2) — линейная цепь, без ложной ветки;
 *   - tool-под-нода прикрепляется к Синтезатору (hasBranch=true);
 *   - single/image — линейная цепь без «Синтезатор→Вербализатор»;
 *   - пустой ответ API → пустое состояние (fail-open);
 *   - «оц.» (tokens_estimated) и «цена неизвестна» (price_known=false);
 *   - kill-switch uiFlag('TOKEN_FLOW_NODEFLOW_ENABLED') (OFF → бейджи);
 *   - статические инварианты нейминга (чистый русский, CSP/no-CDN).
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
assert(methods && methods.tokenFlowTree, 'root.methods.tokenFlowTree не найден');
assert(methods.uiFlag, 'root.methods.uiFlag не найден');

function tree(steps, total, ts) {
  return methods.tokenFlowTree.call({
    tokenAnalyticsLatest: { steps: steps, total: total || {}, ts: ts || null },
    _tokenFlowTimestamp: methods._tokenFlowTimestamp,
  });
}
function kinds(t) { return t.nodes.map(function (n) { return n.kind; }); }
function edgeSet(t) {
  return t.edges.map(function (e) { return e.from + '>' + e.to; });
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
  assert.strictEqual(t.nodes[0].title, 'Запрос юзера');
  assert.strictEqual(t.nodes[1].title, 'Синтезатор');
  assert.strictEqual(t.nodes[2].title, 'Вербализатор');
  assert.strictEqual(t.nodes[3].title, 'Итог');
  assert.deepStrictEqual(edgeSet(t),
    ['root>n-synth', 'n-synth>n-verb', 'n-verb>result'], 'рёбра двухслойного');
  assert.strictEqual(t.hasBranch, false, 'без tool — ветвления нет');
  // Итог = сумма total.
  const res = t.nodes[3];
  assert.strictEqual(res.input, 4500);
  assert.strictEqual(res.output, 700);
  assert.strictEqual(res.cost, 0.003);
  // Корень — без чисел.
  assert.strictEqual(t.nodes[0].kind, 'root');
  assert(t.nodes[0].note.indexOf('последний вызов') >= 0, 'подпись времени');
})();

// ── 2. Ветвление: tool-под-нода прикреплена к Синтезатору ──────────────────
(function () {
  const steps = [
    { step: 'stage1', input_tokens: 100, output_tokens: 10, cost_usd: 0.001 },
    { step: 'tool', tool_name: 'web_search', input_tokens: 200,
      output_tokens: 20, cost_usd: 0.0005 },
    { step: 'stage2', input_tokens: 300, output_tokens: 30, cost_usd: 0.002 },
  ];
  const t = tree(steps, { input_tokens: 600, output_tokens: 60, cost_usd: 0.0035 });
  assert.deepStrictEqual(kinds(t),
    ['root', 'synthesizer', 'tool', 'verbalizer', 'result']);
  assert(t.hasBranch === true, 'tool → hasBranch=true');
  const toolNode = t.nodes.find(function (n) { return n.kind === 'tool'; });
  assert(toolNode && toolNode.title === 'Инструмент: web_search',
    'подпись tool-ноды с именем инструмента');
  const toolEdge = t.edges.find(function (e) { return e.to === toolNode.id; });
  assert(toolEdge && toolEdge.from === 'n-synth',
    'tool-нода прикреплена к Синтезатору');
  // Спина всё равно доходит до result.
  assert(edgeSet(t).indexOf('n-verb>result') >= 0);
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
})();

// ── 5. Пустой ответ API → пустое состояние (fail-open) ──────────────────────
(function () {
  const t = tree([], {});
  assert.strictEqual(t.empty, true);
  assert.deepStrictEqual(t.nodes, []);
  assert.deepStrictEqual(t.edges, []);
  // null latest — тоже пусто, без исключений.
  const t2 = methods.tokenFlowTree.call({ tokenAnalyticsLatest: null });
  assert.strictEqual(t2.empty, true);
})();

// ── 6. tokens_estimated=true → пометка «оц.» ────────────────────────────────
(function () {
  const t = tree([{ step: 'single', input_tokens: 10, output_tokens: 2,
                    cost_usd: 0.00001, tokens_estimated: true }],
                 { input_tokens: 10, output_tokens: 2, cost_usd: 0.00001 });
  const node = t.nodes.find(function (n) { return n.kind === 'single'; });
  assert.strictEqual(node.estimated, true, 'оц. для estimated');
})();

// ── 7. Смешанный набор: нераспознанный step → отдельная плашка ──────────────
(function () {
  const t = tree([{ step: 'mystery_step', input_tokens: 1, output_tokens: 1,
                    cost_usd: 0 }], {});
  assert.deepStrictEqual(kinds(t), ['root', 'other', 'result']);
  assert(t.nodes[1].title.indexOf('mystery_step') >= 0,
    'неизвестный step выводится плашкой-заголовком');
})();

// ── 8. Kill-switch uiFlag (ADR-1024-13) ─────────────────────────────────────
(function () {
  // до загрузки /api/me — безопасный дефолт ON
  assert.strictEqual(methods.uiFlag.call({ me: null },
    'TOKEN_FLOW_NODEFLOW_ENABLED'), true);
  assert.strictEqual(methods.uiFlag.call({ me: {} },
    'TOKEN_FLOW_NODEFLOW_ENABLED'), true);
  // OFF → false (прежние бейджи)
  assert.strictEqual(methods.uiFlag.call(
    { me: { ui_flags: { TOKEN_FLOW_NODEFLOW_ENABLED: false } } },
    'TOKEN_FLOW_NODEFLOW_ENABLED'), false);
  // ON → true
  assert.strictEqual(methods.uiFlag.call(
    { me: { ui_flags: { TOKEN_FLOW_NODEFLOW_ENABLED: true } } },
    'TOKEN_FLOW_NODEFLOW_ENABLED'), true);
  // неизвестное имя флага → дефолт ON (не ломает рендер)
  assert.strictEqual(methods.uiFlag.call(
    { me: { ui_flags: {} } }, 'UNKNOWN_FLAG'), true);
})();

// ── 9. Статические инварианты: нейминг + CSP/no-CDN ─────────────────────────
(function () {
  const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
  assert(INDEX.indexOf('Аналитика токенов') !== -1, 'заголовок «Аналитика токенов»');
  assert(INDEX.indexOf('Последний запрос (Дерево вызова)') !== -1,
    'под-блок «Последний запрос (Дерево вызова)»');
  assert(INDEX.indexOf('График расходов') !== -1, 'заголовок «График расходов»');
  assert(INDEX.indexOf('Token Metrics') === -1,
    'англо-жаргон «Token Metrics» должен отсутствовать');
  assert(INDEX.indexOf("uiFlag('TOKEN_FLOW_NODEFLOW_ENABLED')") !== -1,
    'шаблон гейтится uiFlag');
  assert(APP_JS.indexOf('ui_flags') !== -1, 'uiFlag читает this.me.ui_flags');
  // Граф — чистый CSS: контейнер .token-flow, без граф-библиотек.
  assert(INDEX.indexOf('class="token-flow') !== -1, 'контейнер .token-flow в шаблоне');
  for (const lib of ['mermaid', 'cytoscape', 'd3.min.js', 'chart.js',
                     'unpkg.com', 'cdn.jsdelivr.net']) {
    assert(APP_JS.indexOf(lib) === -1, 'запрещена граф-библиотека: ' + lib);
    assert(INDEX.indexOf(lib) === -1, 'запрещена граф-библиотека: ' + lib);
  }
  assert(INDEX.indexOf('http://') === -1 && INDEX.indexOf('https://') === -1,
    'без внешних ресурсов (CSP/zero-build)');
})();

console.log('NODEFLOW-UNIT-OK');
