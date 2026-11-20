'use strict';
/* ═══ MOD-ACL-UX-01 M4B B2 — «Последний вызов» на «Статусе» ═════════════════
 * Контракт (requirements-map): MAC-S6-344, MAC-S6-345, MAC-S6-346, MAC-S6-347,
 * MAC-AC-15, MAC-S15-01, MAC-S0-11.
 *
 * Проверяется РЕАЛЬНЫЙ код `web/app.js` и `web/index.html`:
 *   1) нет данных → компактное состояние с checked-at и причиной, без
 *      min-height 300–500 px и без «Изображений 0/0»;
 *   2) при вызове — 1–2 строки время/модуль/модель/результат/латентность,
 *      токены, стоимость только при price_known, error и correlation_id;
 *   3) вызов изображения назван отдельно и не выдаётся за LLM-вызов;
 *   4) per-chat/global не смешиваются: источник — global analytics;
 *   5) 503 — unknown, не «нет последнего вызова»/ноль;
 *   6) D1: latency_ms/l1_failure_mode/l1_finish_reason читаются из API.
 *
 * Запуск: node tests/js/m4b_lastcall_test.js
 *         → MOD-ACL-UX-M4B-B2-LASTCALL-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');

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
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  matchMedia: function () { return { matches: false, addEventListener() {} }; },
  innerWidth: 1440, innerHeight: 900,
};
const _bodyChildren = [];
global.document = {
  addEventListener() {}, getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() { const i = _bodyChildren.indexOf(this); if (i >= 0) _bodyChildren.splice(i, 1); },
    };
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) { const i = _bodyChildren.indexOf(el); if (i >= 0) _bodyChildren.splice(i, 1); return el; },
  },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('no'); } } },
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

function vm(init) {
  const base = Object.create(methods);
  Object.keys(computed).forEach((k) => {
    Object.defineProperty(base, k, {
      configurable: true,
      get() { return computed[k].call(base); },
    });
  });
  Object.keys(init || {}).forEach((k) => {
    Object.defineProperty(base, k, {
      value: init[k], writable: true, configurable: true,
    });
  });
  return base;
}

/* ── 1. Статический контракт разметки/стилей ────────────────────────────── */
{
  const start = INDEX.indexOf('class="exec-preview card');
  const end = INDEX.indexOf('<!-- ASAP-UI-02 (§5.3', start);
  assert.ok(start > 0 && end > start, 'блок «Последний вызов» найден');
  const BLOCK = INDEX.slice(start, end);
  assert.ok(BLOCK.indexOf('data-exec-preview') >= 0);
  assert.ok(BLOCK.indexOf('data-exec-state') >= 0,
    'состояние (ok/empty/unavailable) выводится в DOM');
  assert.ok(BLOCK.indexOf('data-exec-checked') >= 0,
    'время проверки выводится');
  assert.ok(BLOCK.indexOf('data-exec-empty') >= 0,
    'компактное no-data состояние');
  assert.ok(BLOCK.indexOf('data-exec-unavailable') >= 0,
    '503/недоступность — отдельное unknown-состояние');
  assert.ok(BLOCK.indexOf('data-exec-technical') >= 0,
    'технические детали (correlation_id) в раскрытии');
  assert.ok(BLOCK.indexOf('data-exec-image') >= 0,
    'вызов изображения называется отдельно');
  assert.ok(BLOCK.indexOf('data-exec-scope') >= 0,
    'scope аналитики назван');
  assert.ok(BLOCK.indexOf('per-chat') < 0
    && BLOCK.indexOf('per-chat данные') < 0,
  'per-chat данные не смешиваются с global costs');
  assert.ok(BLOCK.indexOf('Глобальная аналитика') >= 0,
    'источник — глобальная аналитика, не чатовые бюджеты');
  assert.strictEqual(INDEX.indexOf('Изображений 0/0'), -1,
    '«Изображений 0/0» больше нет');
  assert.strictEqual(INDEX.indexOf('Изображений 0/0') < 0
    && INDEX.indexOf('0/0') < 0, true,
  'ноль изображений не подаётся как доказательство');
  assert.ok(BLOCK.indexOf('loadExecPreview(true)') >= 0,
    'кнопка обновления реально перезапрашивает данные');

  const rule = /\.exec-preview \{([^}]*)\}/.exec(CSS);
  assert.ok(rule, '.exec-preview правило найдено');
  assert.strictEqual(/min-height/.test(rule[1]), false,
    'у пустого блока нет min-height 300–500');
  assert.ok(/align-self:\s*start/.test(rule[1])
    || /\.status-grid > \.exec-preview \{[^}]*align-self:\s*start/.test(CSS),
  'блок не растягивается по высоте соседа');
  assert.ok(/\.status-grid > \.status-sleep[^}]*align-self:\s*start/.test(CSS)
    || /\.status-grid > \.exec-preview[^}]*align-self:\s*start/.test(CSS),
  'высоты «Сон»/«Последний вызов» независимы');
}

/* ── 2. D1-поля: latency/failure/finish читаются из API ─────────────────── */
const TS = '2026-11-20T12:00:00+00:00';
function step(over) {
  return Object.assign({
    ts: TS, module: 'direct_chat', step: 'stage1', tool_name: '',
    source: 'global', model: 'deepseek-v4', input_tokens: 4000,
    output_tokens: 600, tokens_estimated: false, cost_usd: 0.00174,
    price_known: true, latency_ms: 820.5, l1_failure_mode: null,
    l1_finish_reason: 'stop',
  }, over || {});
}

{
  const v = vm({
    execPreviewCheckedAt: Date.UTC(2026, 10, 20, 12, 0, 5),
    tokenAnalyticsLatest: { correlation_id: 'corr-1', ts: TS,
      steps: [step()], total: { input_tokens: 4000, output_tokens: 600,
        cost_usd: 0.00174, calls: 1 } },
  });
  const p = computed.execPreview.call(v);
  assert.strictEqual(p.state, 'ok');
  assert.strictEqual(p.rows.length, 1, '1–2 строки, не полный ledger');
  const r = p.rows[0];
  assert.ok(r.ts, 'время вызова');
  assert.strictEqual(r.module, 'direct_chat');
  assert.strictEqual(r.model, 'deepseek-v4');
  assert.ok(r.latency.indexOf('820') >= 0, 'латентность из latency_ms');
  assert.strictEqual(r.inputTokens, '4 000');
  assert.strictEqual(r.outputTokens, '600');
  assert.strictEqual(r.cost, '$0.00174');
  assert.strictEqual(r.failed, false);
  assert.ok(r.result.indexOf('stop') >= 0, 'finish_reason показан');
  assert.ok(p.checkedAt, 'checked-at зафиксирован');
  assert.strictEqual(p.correlationId, 'corr-1');
  assert.strictEqual(p.scopeLabel, 'global');
  assert.strictEqual(p.allSteps.length, 1, 'полный набор — в деталях');
}

{
  const v = vm({ tokenAnalyticsLatest: { correlation_id: 'c2',
    steps: [step({ price_known: false, cost_usd: 0, latency_ms: null,
      l1_finish_reason: null, l1_failure_mode: 'timeout' })] } });
  const p = computed.execPreview.call(v);
  assert.strictEqual(p.rows[0].cost, 'нет данных',
    'unknown цена не превращается в $0');
  assert.strictEqual(p.rows[0].failed, true);
  assert.ok(p.rows[0].result.indexOf('timeout') >= 0,
    'error/failure_mode показан');
  assert.strictEqual(p.rows[0].latency, '—');
}

/* ── 3. No-data: компактный unknown с checked-at и причиной ─────────────── */
{
  const v = vm({ execPreviewCheckedAt: 1791900000000,
    tokenAnalyticsLatest: { correlation_id: '', ts: null, steps: [],
      total: { input_tokens: 0, output_tokens: 0, cost_usd: 0, calls: 0 } } });
  const p = computed.execPreview.call(v);
  assert.strictEqual(p.state, 'empty');
  assert.ok(p.checkedAt, 'время проверки показано');
  assert.ok(p.reason.indexOf('пустой ответ') >= 0,
    'причина названа честно (PG/телеметрия/история)');
  assert.strictEqual(p.rows.length, 0);
  assert.strictEqual(INDEX.indexOf('Нет данных: вызовов ещё не было'), -1,
    'старая большая пустая карточка удалена');
}

/* ── 4. 503/недоступность: unknown, не «нет вызова» ─────────────────────── */
{
  const v = vm({ execPreviewError: 'HTTP 503',
    execPreviewCheckedAt: 1791900000000, tokenAnalyticsLatest: null });
  const p = computed.execPreview.call(v);
  assert.strictEqual(p.state, 'unavailable');
  assert.ok(p.reason.indexOf('503') >= 0);
  assert.ok(p.checkedAt);
}

/* ── 5. Изображение отдельно; не доказательство LLM-вызова ──────────────── */
{
  const img = step({ step: 'image', source: 'image', model: 'image-model',
    input_tokens: 0, output_tokens: 0, cost_usd: 0.04, price_known: true,
    latency_ms: 1200, l1_finish_reason: null });
  const v = vm({ tokenAnalyticsLatest: { correlation_id: 'img-1',
    steps: [img], total: { calls: 1, cost_usd: 0.04 } } });
  const p = computed.execPreview.call(v);
  assert.strictEqual(p.kind, 'image');
  assert.strictEqual(p.rows.length, 1);
  assert.strictEqual(p.rows[0].cost, '$0.04');
  assert.ok(p.rows[0].latency.indexOf('1200') >= 0
    || p.rows[0].latency.indexOf('1.2') >= 0);
  assert.ok(p.imageNote.indexOf('не текстовый LLM-вызов') >= 0,
    'изображение явно отделено от LLM');
}

{
  const v = vm({ tokenAnalyticsLatest: { correlation_id: 'mix-1',
    steps: [step(), step({ step: 'image', source: 'image',
      model: 'image-model', input_tokens: 0, output_tokens: 0,
      cost_usd: 0.04, price_known: true })],
    total: { calls: 2 } } });
  const p = computed.execPreview.call(v);
  assert.strictEqual(p.kind, 'llm');
  assert.strictEqual(p.imageRows.length, 1);
  assert.ok(p.imageNote.indexOf('изображени') >= 0,
    'вызов изображения назван отдельно и не смешан со стоимостью LLM');
  assert.strictEqual(p.tokensEstimated, false);
}

{
  const v = vm({ tokenAnalyticsLatest: { correlation_id: 'est-1',
    steps: [step({ tokens_estimated: true, cost_usd: null,
      price_known: false })], total: { calls: 1 } } });
  const p = computed.execPreview.call(v);
  assert.strictEqual(p.rows[0].tokensEstimated, true,
    'оценка токенов помечена');
  assert.strictEqual(p.rows[0].cost, 'нет данных');
}

/* ── 6. Загрузка: checked-at и force-refresh; ошибка не маскируется ─────── */
(async function () {
  {
    let calls = 0;
    const v = vm({ execPreviewBusy: false, execPreviewError: '',
      execPreviewCheckedAt: null, tokenAnalyticsLatest: null });
    v.api = async function () {
      calls += 1;
      return { correlation_id: 'c', steps: [step()], total: { calls: 1 } };
    };
    await methods.loadExecPreview.call(v, true);
    assert.strictEqual(calls, 1);
    assert.ok(v.execPreviewCheckedAt, 'время проверки установлено');
    assert.strictEqual(v.execPreviewError, '');
    await methods.loadExecPreview.call(v);
    assert.strictEqual(calls, 1, 'без force повторно не грузит');
    await methods.loadExecPreview.call(v, true);
    assert.strictEqual(calls, 2, 'кнопка обновления действительно грузит');
  }
  {
    const v = vm({ execPreviewBusy: false, execPreviewError: '',
      execPreviewCheckedAt: null, tokenAnalyticsLatest: null });
    v.api = async function () {
      const err = new Error('fail');
      err.status = 503;
      throw err;
    };
    await methods.loadExecPreview.call(v, true);
    assert.strictEqual(v.tokenAnalyticsLatest, null);
    assert.strictEqual(v.execPreviewError, 'HTTP 503');
    assert.ok(v.execPreviewCheckedAt, 'unknown тоже имеет время проверки');
    const p = computed.execPreview.call(v);
    assert.strictEqual(p.state, 'unavailable');
  }
  console.log('MOD-ACL-UX-M4B-B2-LASTCALL-OK');
})();
