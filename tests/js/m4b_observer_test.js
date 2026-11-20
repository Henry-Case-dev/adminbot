'use strict';
/* ═══ MOD-ACL-UX-01 M4B B2 — наблюдатель на «Статусе» ═══════════════════════
 * Контракт (requirements-map): MAC-S6-306 (revision/checked-at), MAC-S6-309,
 * MAC-S6-331, MAC-S6-332, MAC-S6-333, MAC-S6-334, MAC-S6-335, MAC-S6-336,
 * MAC-S6-FUN-01, MAC-S6-FUN-02, MAC-AC-14, MAC-S15-02, MAC-S0-11.
 *
 * Проверяется РЕАЛЬНЫЙ код `web/app.js` и `web/index.html`:
 *   1) KPI ≤6 с подписью, окном, scope и снимком; никакой 8-стадийной
 *      «воронки» и `.funnel-grid`/`.funnel-cell`;
 *   2) явная строка «это независимые числа, а не конверсия»;
 *   3) две независимые сущности — активные намерения и публикации — с
 *      серверным объяснением доменов (D3) и честным fallback;
 *   4) «Почему сейчас ничего не опубликовано?»: title/warning/recommendation;
 *   5) топ причин 3–5 кликабельных строк + полный список в details;
 *   6) последние решения 3–5 строк с датой/action/причиной/доставкой, полный
 *      ledger — в раскрытии; «Проверить инициативу» объясняет mock vs real;
 *   7) health-лента показывает версию и момент наблюдения.
 *
 * Запуск: node tests/js/m4b_observer_test.js
 *         → MOD-ACL-UX-M4B-B2-OBSERVER-OK
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

/* ── 1. Разметка: KPI, две сущности, причины, решения, проверка ──────────── */
{
  const start = INDEX.indexOf('data-initiative-independent');
  const end = INDEX.indexOf('data-quantum-analytics', start);
  assert.ok(start > 0 && end > start, 'блок наблюдателя найден');
  const BLOCK = INDEX.slice(start, end);

  assert.strictEqual(INDEX.split('data-initiative-independent').length - 1, 1,
    'ровно одно место диагностики инициативы');
  assert.strictEqual(INDEX.split('data-initiative-check').length - 1, 1,
    'ровно одна кнопка проверки');
  assert.strictEqual(INDEX.indexOf('funnel-grid'), -1,
    'псевдо-воронка funnel-grid удалена из разметки');
  assert.strictEqual(CSS.indexOf('.funnel-grid'), -1,
    'CSS псевдо-воронки удалён');
  assert.strictEqual(CSS.indexOf('.funnel-cell'), -1,
    'CSS 8 ячеек воронки удалён');

  assert.ok(BLOCK.indexOf('data-observer-kpis') >= 0,
    'KPI-строка существует');
  assert.ok(BLOCK.indexOf('v-for="k in initiativeFunnel.kpis"') >= 0,
    'KPI строятся из серверных независимых счётчиков');
  assert.ok(BLOCK.indexOf('data-observer-kpi=') >= 0,
    'у каждой KPI-ячейки есть стабильный id');
  assert.ok(BLOCK.indexOf('data-observer-no-conversion') >= 0,
    'подпись «не конверсия» присутствует');
  assert.ok(BLOCK.indexOf('не конверсия') >= 0,
    'пользователь видит, что это не конверсия');

  assert.ok(BLOCK.indexOf('data-observer-entity="intents"') >= 0,
    'активные намерения — отдельная сущность');
  assert.ok(BLOCK.indexOf('data-observer-entity="publications"') >= 0,
    'публикации — отдельная сущность');
  assert.ok(BLOCK.indexOf('data-observer-domains-explain') >= 0,
    'объяснение разницы доменов выводится');
  assert.ok(BLOCK.indexOf('data-observer-why') >= 0,
    'блок «Почему сейчас ничего не опубликовано?» существует');
  assert.ok(BLOCK.indexOf('data-observer-why-heading') >= 0);
  assert.ok(BLOCK.indexOf('data-observer-health') >= 0);
  assert.ok(BLOCK.indexOf('data-observer-soft') >= 0);

  assert.ok(BLOCK.indexOf('data-observer-reasons') >= 0,
    'секция топ-причин существует');
  assert.ok(BLOCK.indexOf('v-for="r in w5Reasons"') >= 0,
    'топ-причины ограничены computed-лимитом');
  assert.ok(BLOCK.indexOf('data-observer-reason') >= 0,
    'каждая топ-причина — кликабельная строка');
  assert.ok(/<details[^>]*data-observer-reason/.test(BLOCK),
    'причина раскрывается (код/объяснение)');
  assert.ok(BLOCK.indexOf('data-observer-all-reasons') >= 0,
    'полный список причин — в раскрытии');

  assert.ok(BLOCK.indexOf('data-observer-decisions') >= 0,
    'последние решения существуют');
  assert.ok(BLOCK.indexOf('v-for="(d, i) in w5Decisions"') >= 0);
  assert.ok(BLOCK.indexOf('d.tsLabel') >= 0 && BLOCK.indexOf('d.action') >= 0,
    'у решения видны дата и action');
  assert.ok(BLOCK.indexOf('d.reason_label') >= 0, 'у решения видна причина');
  assert.ok(BLOCK.indexOf('d.deliveryLabel') >= 0,
    'у решения виден статус доставки');
  assert.ok(BLOCK.indexOf('data-observer-ledger') >= 0,
    'полный ledger — в раскрытии');
  assert.ok(BLOCK.indexOf('#/oversight') >= 0,
    'ссылка в существующую Аналитику сохранена');

  assert.ok(BLOCK.indexOf('data-initiative-help') >= 0,
    'пояснение «что проверяет» существует');
  const help = BLOCK.slice(BLOCK.indexOf('data-initiative-help'),
    BLOCK.indexOf('data-initiative-help') + 1200);
  assert.ok(/mock/i.test(help) && /реальн/i.test(help),
    'пояснение различает mock и реальную отправку');
  assert.ok(/dry-run/i.test(help) && /не выдаётся/i.test(help),
    'dry-run не выдаётся за отправку');
  assert.ok(/<details[^>]*data-initiative-trace/.test(BLOCK),
    'trace проверки остаётся в раскрытии');
}

/* ── 2. Health: версия и момент наблюдения ──────────────────────────────── */
{
  const start = INDEX.indexOf('data-status-health');
  const BLOCK = INDEX.slice(start, start + 9000);
  assert.ok(BLOCK.indexOf('data-status-observed') >= 0,
    'health-лента содержит строку наблюдения');
  assert.ok(BLOCK.indexOf('data-status-version') >= 0,
    'deployed revision выводится');
  assert.ok(BLOCK.indexOf('statusData.bot.version') >= 0,
    'версия берётся из реального /api/status');
  assert.ok(BLOCK.indexOf('data-status-checked-at') >= 0,
    'момент наблюдения выводится');
  assert.ok(BLOCK.indexOf('statusCheckedAt') >= 0,
    'момент наблюдения — серверный generated_at');
}

/* ── 3. KPI ≤6, окна/scope/снимок; две сущности; D3 explain ──────────────── */
const FUNNELS = {
  available: true, now_ts: 1791900000, chat_scoped_events: true,
  initiative: {
    available: true,
    job: { status: 'completed', updated_at: 1791890000,
      counters: { passes: 3, observed: 900, eligible: 40, scan_skipped: 7,
        evals: 22, opportunities: 6, silent_decisions: 5, react_decisions: 2,
        intents_created: 2, sent: 4, writer_unavailable: 0, errors: 0,
        eval_skips: { budget: 3 } } },
    liveness: { ts: 1791899000, status: 'ok', observed: 42,
      opportunities: 1 },
    events: {
      '24h': { initiative_observer_scan: 70, initiative_opportunity: 3,
        initiative_decided: 4, initiative_writer_generated: 2,
        initiative_sent: 2, initiative_recheck_passed: 1 },
      '7d': { initiative_observer_scan: 260, initiative_opportunity: 4,
        initiative_decided: 5, initiative_writer_generated: 3,
        initiative_sent: 5, initiative_recheck_passed: 2 },
    },
    domains: {
      intents: { source: 'mca_intents', created_total: 2 },
      publications: { source: 'mca_events.initiative_sent', events_24h: 2,
        events_7d: 5 },
      same_cohort: false,
      explain: 'Намерения — долговременные обещания; публикации — события '
        + 'доставки. Повод «уместно сказать сейчас» эфемерный и намерения '
        + 'не создаёт, поэтому это не конверсия.',
    },
  },
  experience: { available: true, job: null, events: { '24h': {}, '7d': {} } },
};
const STATUS_CHAT = {
  intents: { state: 'not_run', active: 0, module: {} },
};

{
  const f = computed.initiativeFunnel.call(
    vm({ intelFunnels: FUNNELS, statusData: STATUS_CHAT,
         activeChatId: -1001234567890 }));
  assert.ok(f, 'chat-scope: панель есть');
  assert.strictEqual(f.stages, undefined,
    'старый 8-стадийный массив не возвращается');
  assert.strictEqual(f.kpis.length, 6, 'KPI не больше шести');
  assert.deepStrictEqual(f.kpis.map(function (k) { return k.label; }),
    ['Входящие события', 'Реальные поводы', 'Решения', 'Написано',
     'Опубликовано', 'Активные намерения']);
  assert.deepStrictEqual(f.kpis.map(function (k) { return k.value; }),
    [900, 6, 7, 2, 4, 0],
    'KPI — независимые durable/24ч/снимок значения, не конверсия');
  assert.deepStrictEqual(f.kpis.map(function (k) { return k.window; }),
    ['всего (durable)', 'всего (durable)', 'всего (durable)', '24ч',
     'всего (durable)', 'сейчас (снимок)']);
  assert.ok(f.kpis.every(function (k) {
    return k.meta.indexOf('снимок') >= 0;
  }), 'у каждого KPI есть окно/scope/снимок');
  assert.strictEqual(f.scopeLabel.indexOf('чат'), 0,
    'scope явно назван');
  assert.ok(f.snapshotLabel, 'timestamp снимка присутствует');
  assert.ok(f.entities, 'сущности разведены');
  assert.strictEqual(f.entities.intents.value, 0,
    'chat-scope: активные намерения — снимок «сейчас»');
  assert.strictEqual(f.entities.publications.value, 4,
    'публикации — durable доставки');
  assert.strictEqual(f.entities.sameCohort, false,
    'когорта не заявляется без corr ID');
  assert.ok(f.entities.explain.indexOf('эфемерн') >= 0,
    'D3: серверное объяснение доменов используется');
  assert.ok(f.entities.explain.indexOf('не конверсия') >= 0);

  const globalVm = vm({ intelFunnels: FUNNELS,
    statusData: { intents: { state: 'no_chat', active: 0, module: {} } },
    activeChatId: null });
  const fg = computed.initiativeFunnel.call(globalVm);
  assert.ok(fg, 'global/no_chat: панель не исчезает');
  assert.strictEqual(fg.kpis[5].label, 'Создано намерений',
    'global: подпись «создано», не «активные»');
  assert.strictEqual(fg.kpis[5].value, 2);
  assert.strictEqual(fg.scopeLabel, 'global');
  assert.strictEqual(fg.entities.intents.value, 2);

  assert.strictEqual(computed.initiativeFunnel.call(vm({
    intelFunnels: FUNNELS,
    statusData: { intents: { state: 'disabled', module: {} } },
  })), null, 'disabled → панель не выдумывает данные');
  assert.strictEqual(computed.initiativeFunnel.call(vm({
    intelFunnels: FUNNELS,
    statusData: { intents: { state: 'restricted', module: {} } },
  })), null, 'restricted → данных нет');
  assert.strictEqual(computed.initiativeFunnel.call(vm({
    intelFunnels: null, statusData: STATUS_CHAT })), null,
  'нет funnels → нет нулей');
}

/* ── 4. Причины: лимит 5, полный список; решения 3–5 с датой/доставкой ───── */
{
  const reasons = [];
  for (let i = 1; i <= 7; i += 1) {
    reasons.push({ reason_code: 'r' + i, label: 'причина ' + i, count: i });
  }
  const decisions = [];
  for (let i = 1; i <= 6; i += 1) {
    decisions.push({ ts: 1791900000 + i, action: i % 2 ? 'say' : 'silent',
      reason_label: 'причина ' + i, delivery: i % 2 ? 'sent' : '',
      delivery_kind: i % 2 ? 'message' : 'none' });
  }
  const v = vm({
    intelFunnels: FUNNELS, statusData: STATUS_CHAT, activeChatId: -100,
    initiativeVitality: { available: true,
      activity: { title: 'Возможности есть, сообщений нет', warning: 'w',
        recommendation: 'r', counters: { delivered: 2 } },
      decisions: decisions,
      refusals: [{ ts: 1, reason_label: 'x', reason_code: 'x' }],
      sends: [{ ts: 2, message_id: 7, chars: 10 }],
    },
  });
  v.initiativeVitality.activity.reasons = reasons;
  const top = computed.w5Reasons.call(v);
  assert.strictEqual(top.length, 5, 'на экране не больше 5 причин');
  assert.deepStrictEqual(top.map(function (r) { return r.count; }),
    [1, 2, 3, 4, 5]);
  assert.strictEqual(computed.w5AllReasons.call(v).length, 7,
    'полный список причин доступен в раскрытии');
  const dec = computed.w5Decisions.call(v);
  assert.strictEqual(dec.length, 5, 'последние решения — не больше 5');
  assert.ok(dec[0].tsLabel, 'у решения есть дата');
  assert.ok(dec[0].action, 'у решения есть action');
  assert.ok(dec[0].reason_label, 'у решения есть причина');
  assert.ok(dec[0].deliveryLabel, 'у решения есть доставка');
  const why = computed.w5Why.call(v);
  assert.ok(why && why.heading.indexOf('публикац') >= 0,
    'блок «почему» называет публикации');
  assert.strictEqual(why.warning, 'w');
  assert.strictEqual(computed.w5AllSends.call(v).length, 1);
  assert.strictEqual(computed.w5AllRefusals.call(v).length, 1);
}

console.log('MOD-ACL-UX-M4B-B2-OBSERVER-OK');
