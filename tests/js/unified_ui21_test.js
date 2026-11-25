'use strict';
/* UI-21 (UR-21.02–21.18 + UI-часть UR-12.1/12.4) — РЕАЛЬНЫЙ JS-тест.
 *
 * Проверяет существующий web/app.js в stubbed-окружении:
 *   1. presentation-оверрайды UI-21: fill ratio скрыт, legacy/read-only поля
 *      не редактируются, debug/safety-ключи уходят в «Расширенные»;
 *   2. used-vs-setting, фактическая глубина ветки, фактический резерв и
 *      покрытие/watermark конспекта — из существующих turnDiag/config;
 *   3. причина сокращения (код + человеческая подпись), неизвестный код —
 *      «код: …», отсутствие данных — словом, не нулём;
 *   4. статическая разметка инспектора/статуса и отсутствие секретов.
 *
 * Запуск: node tests/js/unified_ui21_test.js -> UNIFIED-UI21-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = { location: { hash: '' }, addEventListener() {},
                 Telegram: null, confirm: function () { return true; } };
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = { getItem() { return null; }, setItem() {},
                          removeItem() {} };
global.localStorage = { getItem() { return null; }, setItem() {},
                        removeItem() {} };
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
require(path.join(ROOT, 'web', 'app.js'));

assert(captured, 'Vue.createApp не вызван');
const methods = captured.methods || {};

function byKey(items, key) {
  return items.filter(function (it) { return it.key === key; })[0];
}

const ITEMS = [
  { key: 'limits.chat_global_context_limit', value: 200, type: 'int',
    category: 'limits', group: 'limits_chat', progressive_level: '',
    title: 'old', description: 'old' },
  { key: 'limits.chat_context_fill_ratio', value: 0.8, type: 'float',
    category: 'limits', group: 'limits_chat', progressive_level: '',
    title: 'old', description: 'old',
    eff: { status: 'no_op', readonly: true,
      reason_inactive: 'Не действует как триггер.' } },
  { key: 'limits.chat_global_context_max_chars', value: 4000, type: 'int',
    category: 'limits', group: 'limits_chat', progressive_level: '',
    title: 'old', description: 'old',
    eff: { status: 'legacy', readonly: true,
      reason_inactive: 'Legacy-кап фона.' } },
  { key: 'limits.chat_thread_max_depth', value: 6, type: 'int',
    category: 'limits', group: 'limits_chat', progressive_level: '',
    title: 'old', description: 'old' },
  { key: 'limits.chat_running_summary_tail', value: 30, type: 'int',
    category: 'limits', group: 'limits_chat', progressive_level: '',
    title: 'old', description: 'old' },
  { key: 'limits.chat_level2_max_chars', value: 4000, type: 'int',
    category: 'limits', group: 'limits_chat', progressive_level: '',
    title: 'old', description: 'old',
    eff: { status: 'legacy', readonly: true,
      reason_inactive: 'Legacy-кап конспекта.' } },
  { key: 'limits.running_summary_ttl_minutes', value: 60, type: 'int',
    category: 'limits', group: 'limits_chat', progressive_level: '',
    title: 'old', description: 'old' },
  { key: 'limits.chat_map_participants_hours', value: 24, type: 'int',
    category: 'limits', group: 'limits_chat', progressive_level: '',
    title: 'old', description: 'old' },
  { key: 'limits.chat_budget_map_ratio', value: 0.1, type: 'float',
    category: 'limits', group: 'limits_chat_budgets',
    progressive_level: '', title: 'old', description: 'old',
    eff: { status: 'legacy', readonly: true,
      reason_inactive: 'Legacy/fail-open.' } },
  { key: 'limits.chat_budget_reserve_ratio', value: 0.1, type: 'float',
    category: 'limits', group: 'limits_chat_budgets',
    progressive_level: '', title: 'old', description: 'old',
    eff: { status: 'legacy', readonly: true,
      reason_inactive: 'Fallback-доля.' } },
];

const normCtx = Object.assign({}, methods, {
  configItems: ITEMS,
  permissions: { wildcard: true },
  activeTab: 'mod_direct',
  isGlobalAdminEffective: true,
  isDmCtx: function () { return false; },
  isLocalAdminCtx: function () { return false; },
});
methods._normalizeConfigItems.call(normCtx, ITEMS);

// ── 1. remo/legacy/read-only/advanced semantics ──────────────────────────
{
  const fill = byKey(ITEMS, 'limits.chat_context_fill_ratio');
  // UR-22: применимость — из backend-меты. no_op → только чтение; список
  // ключей в JS больше не решает, что скрывать/запрещать.
  assert.strictEqual(fill.__uiReadonly, true,
    'UR-22: readonly — из item.eff.readonly');
  assert.strictEqual(fill.__uiHidden, undefined,
    'UR-22: клиент не прячет ключи сам — скрытие делает backend');
  assert.strictEqual(methods.canEditConfig.call(normCtx,
    'limits.chat_context_fill_ratio'), false,
    'UR-21.08/12.1: fill ratio не редактируется (мета no_op)');
  assert.strictEqual(fill.title, 'Порог заполнения окна (снято)',
    'подпись снятого поля не обещает рабочий триггер');
  assert.strictEqual(byKey(ITEMS, 'limits.chat_global_context_limit').title,
    'Сколько последних сообщений читать первично',
    'UR-21.02: 200 — не «память», а мягкая граница чтения');
  assert.strictEqual(byKey(ITEMS, 'limits.running_summary_ttl_minutes').title,
    'TTL хранения конспекта (технический), минут',
    'UR-21.12/12.4: TTL — не «время жизни памяти»');
  assert.strictEqual(byKey(ITEMS, 'limits.chat_budget_map_ratio').title,
    'Legacy-доля: MAP (только чтение)',
    'UR-21.16: legacy-доля честно названа');
  assert.strictEqual(
    byKey(ITEMS, 'limits.chat_budget_reserve_ratio').title,
    'Fallback-доля резерва вывода (только чтение)',
    'UR-21.18: доля — только fallback, не активная формула резерва');

  const group = { items: ITEMS };
  const basic = methods.basicItems.call(normCtx, group);
  const advanced = methods.advancedItems.call(normCtx, group);
  assert.strictEqual(basic.some(function (it) {
    return it.key === 'limits.chat_context_fill_ratio';
  }), true, 'fill ratio виден как read-only (hidden делает backend)');
  assert.strictEqual(advanced.some(function (it) {
    return it.key === 'limits.chat_context_fill_ratio';
  }), false, 'fill ratio — не «расширенный» ключ');
  assert.strictEqual(basic.some(function (it) {
    return it.key === 'limits.chat_global_context_limit';
  }), true, 'основная граница чтения остаётся в базовых');
  ['limits.chat_running_summary_tail', 'limits.chat_level2_max_chars',
   'limits.chat_budget_map_ratio', 'limits.chat_budget_reserve_ratio']
    .forEach(function (key) {
      assert.strictEqual(basic.some(function (it) { return it.key === key; }),
        false, key + ': debug/legacy уходит из базовых');
      assert.strictEqual(advanced.some(function (it) {
        return it.key === key;
      }), true, key + ': debug/legacy доступен в расширенных');
    });

  assert.strictEqual(methods.canEditConfig.call(normCtx,
    'limits.chat_global_context_max_chars'), false,
    'UR-21.04: legacy-потолок только читается');
  assert.strictEqual(methods.canEditConfig.call(normCtx,
    'limits.chat_budget_map_ratio'), false,
    'UR-21.16: legacy-доля только читается');
  assert.strictEqual(methods.canEditConfig.call(normCtx,
    'limits.chat_budget_reserve_ratio'), false,
    'UR-21.18: fallback-доля только читается');
  assert.strictEqual(methods.canEditConfig.call(normCtx,
    'limits.chat_level2_max_chars'), false,
    'UR-21.11: legacy-потолок только читается');
  assert.strictEqual(methods.canEditConfig.call(normCtx,
    'limits.chat_global_context_limit'), true,
    'активная граница чтения остаётся редактируемой');
  const searchCtx = Object.assign({}, normCtx, { configSearch: 'fill',
                                                configGroups: [] });
  const searchGrp = methods._syntheticGroup.call(searchCtx, 'limits',
    'limits_chat');
  assert(searchGrp && searchGrp.items.some(function (it) {
    return it.key === 'limits.chat_context_fill_ratio';
  }), 'поиск находит поле, применимость решает backend-мета');

  const legacy = { key: 'limits.chat_global_context_max_chars',
    eff: { status: 'legacy',
           reason_inactive: 'Legacy-кап фона; composer-ON режет allocator.' } };
  assert.strictEqual(methods.configEffBadge(legacy).text, 'legacy',
    'legacy-статус по-прежнему приходит из effective_meta');
  assert.strictEqual(methods.configItemNotice(legacy),
    'Legacy-кап фона; composer-ON режет allocator.',
    'причина legacy не подменяется UI');
}

// ── 2. used-vs-setting / глубина / резерв / покрытие ────────────────────
const TURN = {
  trace_id: 'ur21-turn',
  available: true,
  clock: { timezone: 'UTC' },
  selection: {
    counts: { available_messages: 25, included_messages: 12,
              window_messages: 40 },
    budget: { window: 128000, output_reserve: 12800, available: 110000,
              budget: 16000, policy_mode: 'dynamic', payload_tokens: 5400 },
    blocks: [
      { kind: 'thread', role: 'p1', rendered: true,
        source_ids: ['msg:1', 'msg:2', 'msg:3'] },
      { kind: 'global_head', rendered: true, first_ts: 1700000000,
        last_ts: 1700003600, tokens: 512 },
      { kind: 'global_tail', rendered: true, first_ts: 1700007200,
        last_ts: 1700007600, tokens: 800 },
      { kind: 'global_middle', rendered: false,
        skip_reason: 'budget_exceeded' },
    ],
    dropped: [{ reason_code: 'budget_exceeded', kind: 'global_middle',
                count: 3 }],
    dropped_total: 3,
    truncated: false,
  },
};
const turnCtx = Object.assign({}, methods, {
  turnDiag: TURN,
  configItems: [
    { key: 'limits.chat_global_context_limit', value: 200 },
    { key: 'limits.chat_thread_max_depth', value: 6 },
    { key: 'limits.chat_budget_reserve_ratio', value: 0.1 },
    { key: 'limits.running_summary_ttl_minutes', value: 60 },
  ],
});

{
  const used = methods.ur21UsedVsSettingLine.call(turnCtx);
  assert(used.indexOf('настройка 200') >= 0, used);
  assert(used.indexOf('доступно 25') >= 0, used);
  assert(used.indexOf('в окне 40') >= 0, used);
  assert(used.indexOf('вошло 12') >= 0, used);

  const depth = methods.ur21ThreadDepthLine.call(turnCtx);
  assert(depth.indexOf('настройка глубины 6') >= 0, depth);
  assert(depth.indexOf('в трассе 3 сообщ.') >= 0, depth);

  const reserve = methods.ur21ReserveLine.call(turnCtx);
  assert(reserve.indexOf('фактически 12 800') >= 0, reserve);
  assert(reserve.indexOf('источник не зафиксирован') >= 0, reserve);
  assert(reserve.indexOf('доступно контексту 110 000') >= 0, reserve);

  // UR-21.18: при model_capability доля не выдаётся за активную формулу.
  const capCtx = Object.assign({}, turnCtx, {
    turnDiag: { available: true, selection: { budget: {
      window: 131072, output_reserve: 4352, available: 110000,
      output_reserve_source: 'model_capability',
      model_max_output_tokens: 8192, reserve_target_tokens: 4096,
    } } },
  });
  const capLine = methods.ur21ReserveLine.call(capCtx);
  assert(capLine.indexOf('предел вывода модели (8 192)') >= 0, capLine);
  assert(capLine.indexOf('настройка доли') < 0, capLine);
  // Fallback-путь честно показывает долю.
  const fbCtx = Object.assign({}, turnCtx, {
    turnDiag: { available: true, selection: { budget: {
      window: 131072, output_reserve: 13107, available: 100000,
      output_reserve_source: 'ratio_fallback',
      model_max_output_tokens: null, reserve_target_tokens: 4096,
    } } },
  });
  const fbLine = methods.ur21ReserveLine.call(fbCtx);
  assert(fbLine.indexOf('fallback-доля 0.1') >= 0, fbLine);
  assert(fbLine.indexOf('предел вывода модели') < 0, fbLine);

  const summary = methods.ur21SummaryCoverageLine.call(turnCtx);
  assert(summary.indexOf('TTL хранения 60 мин (технический)') >= 0, summary);
  assert(summary.indexOf('в окне 40 сообщ.') >= 0, summary);
  assert(summary.indexOf('есть реплики после конспекта') >= 0, summary);
  assert(summary.indexOf('покрытие') >= 0, summary);

  const reduction = methods.ur21ReductionLine.call(turnCtx);
  assert(reduction.indexOf('budget_exceeded') >= 0, reduction);
  assert(reduction.indexOf('не поместилось в окно модели') >= 0, reduction);
  assert(reduction.indexOf('3 шт.') >= 0, reduction);
}

// ── 3. отсутствие данных — словом, не нулём ─────────────────────────────
{
  const emptyCtx = Object.assign({}, methods, {
    turnDiag: { available: true, selection: null },
    configItems: [{ key: 'limits.chat_global_context_limit', value: 200 }],
  });
  assert(methods.ur21UsedVsSettingLine.call(emptyCtx)
    .indexOf('доступно нет данных') >= 0);
  assert(methods.ur21ThreadDepthLine.call(emptyCtx)
    .indexOf('в трассе нет данных') >= 0);
  assert(methods.ur21ReserveLine.call(emptyCtx)
    .indexOf('фактически нет данных') >= 0);
  assert(methods.ur21SummaryCoverageLine.call(emptyCtx)
    .indexOf('наличие новых реплик: нет данных') >= 0);
  assert.strictEqual(methods.ur21ReductionLine.call(emptyCtx),
    'Сокращение: не зафиксировано');

  const unknownCtx = Object.assign({}, turnCtx, {
    turnDiag: { available: true, selection: {
      dropped: [{ reason_code: 'mystery_reason', count: 1 }],
    } },
  });
  assert(methods.ur21ReductionLine.call(unknownCtx)
    .indexOf('код: mystery_reason') >= 0,
  'неизвестный код не исчезает и не переводится выдумкой');
}

// ── 4. статус-блок ответов в чате: настройка vs факт + резерв ────────────
{
  const directCtx = Object.assign({}, turnCtx, {
    directDiagnostics: {
      available: true, recent_verbatim_messages: 12,
      output_reserve: 12800, excluded_low_priority: 2,
    },
  });
  const line = methods.directUsedSettingLine.call(directCtx);
  assert(line.indexOf('настройка первичного чтения: 200 сообщ.') >= 0
    || line.indexOf('Настройка первичного чтения: 200 сообщ.') >= 0, line);
  assert(line.indexOf('фактически использовано: 12') >= 0, line);
  assert(line.indexOf('резерв вывода: 12 800') >= 0, line);
  assert(line.indexOf('сокращено: 2') >= 0, line);
  assert.strictEqual(methods.directUsedSettingLine.call(
    Object.assign({}, methods, { directDiagnostics: null })), '',
  'нет прогона — пусто, без ложного нуля');

  // UR-21.11: legacy-карточка читает reason_code; известный код — из
  // существующего словаря drop_reason, неизвестный — сам код, пустой —
  // честное «причина не зафиксирована».
  const knownReason = methods.directDiagnosticsReasonLine.call(
    Object.assign({}, directCtx, {
      directDiagnostics: { available: true, reason_code: 'budget_exceeded' },
    }));
  assert(knownReason.indexOf('не поместилось в окно модели') >= 0,
    knownReason);
  assert(knownReason.indexOf('budget_exceeded') >= 0, knownReason);
  const unknownReason = methods.directDiagnosticsReasonLine.call(
    Object.assign({}, directCtx, {
      directDiagnostics: { available: true, reason_code: 'mystery_reason' },
    }));
  assert(unknownReason.indexOf('код: mystery_reason') >= 0, unknownReason);
  assert(unknownReason.indexOf('default') < 0, unknownReason);
  assert.strictEqual(methods.directDiagnosticsReasonLine.call(
    Object.assign({}, directCtx, {
      directDiagnostics: { available: true, reason_code: '' },
    })), 'причина не зафиксирована');
  assert.strictEqual(methods.directDiagnosticsReasonLine.call(
    Object.assign({}, methods, { directDiagnostics: null })), '');
}

// ── 5. статическая разметка и отсутствие секретов ───────────────────────
{
  ['data-ur21-inspector', 'data-ur21-used-setting', 'data-ur21-thread',
   'data-ur21-reserve', 'data-ur21-summary', 'data-ur21-reduction',
   'data-ur21-identity', 'data-ur21-summary-trigger',
   'data-direct-used-setting', 'data-direct-reason'].forEach(
    function (sel) {
      assert(INDEX.indexOf(sel) >= 0, 'нет разметки ' + sel);
    });
  assert(INDEX.indexOf('CHAT_CONTEXT_FILL_RATIO') < 0,
    'fill ratio не возвращается в шаблон');
  assert(INDEX.indexOf(':disabled="!canEditConfig(item.key)"') >= 0,
    'legacy/read-only числовые поля действительно disabled в форме');
  const inspectorAt = INDEX.indexOf('data-ur21-inspector');
  const identityAt = INDEX.indexOf('data-ur21-identity');
  assert(inspectorAt > 0 && identityAt > inspectorAt,
    'identity-пояснение находится в инспекторе');
  const newChunk = INDEX.slice(inspectorAt, identityAt + 600);
  ['api_key', 'secret-field', 'Authorization', 'token='].forEach(function (s) {
    assert(newChunk.indexOf(s) < 0, 'секрет в UI-21: ' + s);
  });
}

console.log('UNIFIED-UI21-OK');
