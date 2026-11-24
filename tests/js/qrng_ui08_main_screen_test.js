'use strict';
/* QRNG UI-08..10 (25.11.2026) — основной экран «Случайность» без инспектора.
 *
 * Проверяет РЕАЛЬНУЮ логику web/app.js (require), не grep:
 *   (a) на основном экране ровно один селектор источника, один тумблер
 *       автоматического резерва и ОДНА редактируемая последовательность;
 *   (b) заводское значение — значение самого контрола; сохранённый/заводской/
 *       действующий порядок и действующая цепочка вынесены в диагностику;
 *   (c) наследование заводского порядка, намеренное отключение резерва и
 *       сохранённый пустой резерв — разные состояния; явный пустой резерв при
 *       явном основном источнике не выдаётся за заводскую цепочку;
 *   (d) «разрешён / проверен / используется» — разные признаки: наличие ключа
 *       не равно проверке, effective-провайдер помечен один раз;
 *   (e) на основном экране только человеческие причины, без сырых кодов,
 *       adapter_not_implemented, этапов P5B и внутренних имён ключей;
 *   (f) ключи, диагностика, применения и дополнительные параметры — в
 *       закрытых по умолчанию <details>; дублирующихся карточек нет.
 *
 * RED: на базе до UI-08..10 методы randomPrimaryHint/randomFallbackStateChip/
 * randomFallbackNote/randomNowView/randomProviderMainRows отсутствуют, а
 * параллельные представления одной конфигурации находятся на основном экране.
 *
 * Запуск: node tests/js/qrng_ui08_main_screen_test.js -> QRNG-UI08-10-OK
 * Base-root для RED: QRNG_UI_TEST_ROOT=<dir> node tests/js/...
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

const ROOT = process.env.QRNG_UI_TEST_ROOT
  ? path.resolve(process.env.QRNG_UI_TEST_ROOT)
  : path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
require(path.join(ROOT, 'web', 'app.js'));

assert(captured, 'Vue.createApp не вызван');
const data = captured.data();
const methods = captured.methods || {};
const computed = captured.computed || {};

function count(text, needle) {
  return (text.match(new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
    'g')) || []).length;
}

function slice(text, from, to) {
  const start = text.indexOf(from);
  assert(start >= 0, 'нет маркера ' + from);
  const end = text.indexOf(to, start);
  assert(end > start, 'нет маркера ' + to + ' после ' + from);
  return text.slice(start, end);
}

const MAIN = slice(INDEX, 'data-random-summary', 'data-random-provider-details');
const DIAG = slice(INDEX, 'data-random-diagnostics', 'data-random-uses');
const KEYS = slice(INDEX, 'data-random-provider-details', 'data-random-diagnostics');
const USES = slice(INDEX, 'data-random-uses', 'data-random-advanced');
const ADV = INDEX.slice(INDEX.indexOf('data-random-advanced'));

function providers(overrides) {
  const base = [
    { id: 'ibm_quantum', configured: false, state: 'provider_unconfigured',
      reserve: 0, consumable: false, quarantined: 0, last_error: null,
      last_failure_at: null, last_success_at: null, last_job: null },
    { id: 'anu', configured: true, state: 'active',
      reserve: 5, consumable: true, quarantined: 0 },
    { id: 'lfdr', configured: true, state: 'unverified',
      reserve: 7, consumable: true, quarantined: 0 },
  ];
  return base.map(function (p) {
    return Object.assign({}, p, (overrides || {})[p.id] || {});
  });
}

function status(overrides) {
  const base = {
    enabled: true,
    available: true,
    quantum_active: true,
    effective_source: 'quantum',
    effective_provider: 'anu',
    primary_provider: 'ibm_quantum',
    primary_setting_raw: 'ibm_quantum',
    primary_setting_state: 'set',
    resolved_primary: 'anu',
    fallback_enabled: true,
    fallback_order: ['anu', 'lfdr'],
    fallback_order_raw: null,
    fallback_order_state: 'absent',
    effective_order: ['ibm_quantum', 'anu', 'lfdr'],
    providers: providers(),
    provider_reserve: { ibm_quantum: 0, anu: 5, lfdr: 7 },
    provider_quarantined: { ibm_quantum: 0, anu: 0, lfdr: 0 },
    reserve_remaining: 12,
    reserve_quarantined: 0,
    buffer_max: 100,
    low_watermark: 10,
    last_batch: { provider_id: 'anu', provider: 'ANU Quantum Numbers',
                  created_at: 1700000200, length: 1024,
                  config_matches: true },
    draws: { quantum: 10, pseudorandom: 0 },
    recent_draws: [],
    recent_draws_scope: 'global',
    last_fallback_reason: 'provider_unconfigured',
    last_fallback_at: 1700000100,
    blocker: 'provider_unconfigured',
    anu_state: 'active',
    lfdr_state: 'unverified',
    key_present: true,
    key_fingerprint: 'test',
    prng_active: false,
    prng_setting: true,
    uses: { enabled: false },
  };
  return Object.assign(base, overrides || {});
}

function cfg(key, value, source) {
  return { key: key, value: value, per_chat: false,
           source: source, updated_at: null };
}

function makeCtx(st, configItems, extra) {
  const source = methods._randomSourceView.call({}, st);
  const activity = computed.randomActivityView.call({ randomSource: source });
  return Object.assign({}, methods, {
    isGlobalAdmin: true,
    configItems: configItems || [],
    randomActivityView: activity,
    randomFallbackDraft: null,
    randomFallbackSaveBusy: false,
    randomCheck: null,
    randomIbmCheck: null,
    randomIbmSmoke: null,
    randomIbmCheckBusy: false,
    randomIbmSmokeBusy: false,
    randomIbmStale: false,
    randomIbmProbeSeq: 0,
    keyDrafts: {},
    fmtTs: function (v) { return 'T' + v; },
    toast: function () {},
  }, extra || {});
}

function byId(rows, id) {
  return rows.filter(function (r) { return r.id === id; })[0];
}

function label(id) {
  return methods.randomProviderLabel.call({}, id);
}

(function () {
  // ── (a) один селектор, один тумблер, одна последовательность ────────────
  assert.strictEqual(count(INDEX, 'data-random-primary'), 1,
    'ровно один основной селектор (без параллельных data-random-primary-*)');
  assert.strictEqual(count(MAIN, 'data-random-primary'), 1,
    'селектор находится на основном экране');
  assert.strictEqual(count(INDEX, 'data-random-fallback-toggle'), 1,
    'ровно один тумблер автоматического резерва');
  assert.strictEqual(count(INDEX, 'data-random-fallback-order'), 1,
    'ровно один редактор последовательности резерва');
  assert.strictEqual(count(INDEX, 'data-random-fallback="'), 1,
    'ровно один шаблон строки последовательности');
  assert.strictEqual(count(INDEX, 'data-random-fallback-include'), 1,
    'один чекбокс включения на строку');
  assert.strictEqual(count(INDEX, 'data-random-summary-effective'), 1,
    'фактически используемый источник показан один раз');
  assert.strictEqual(count(INDEX, 'data-random-provider-summary-block'), 1,
    'одна компактная таблица провайдеров');
  assert.strictEqual(count(INDEX, 'data-random-last-batch'), 1,
    'одно последнее успешное получение');

  // ── (b) заводское — значение контрола, параллельные виды — в диагностике ─
  ['Сохранённый резерв:', 'Заводской резерв:',
   'Действующий резерв:', 'Действующая цепочка:'].forEach(function (needle) {
    assert.strictEqual(MAIN.indexOf(needle), -1,
      'на основном экране нет параллельного представления: ' + needle);
    assert(DIAG.indexOf(needle) >= 0,
      'параллельное представление доступно в диагностике: ' + needle);
  });
  assert(MAIN.indexOf('Основной источник') >= 0);
  assert(MAIN.indexOf('Автоматическое резервирование') >= 0);
  assert(MAIN.indexOf('Резервные источники') >= 0);
  assert(MAIN.indexOf('Сейчас используется') >= 0);
  assert(MAIN.indexOf('Последнее успешное получение') >= 0);
  assert(MAIN.indexOf('Провайдеры') >= 0);
  assert.strictEqual(MAIN.indexOf('data-random-fallback-saved>'), -1);
  assert.strictEqual(MAIN.indexOf('data-random-fallback-factory>'), -1);
  assert.strictEqual(MAIN.indexOf('data-random-fallback-effective>'), -1);
  assert.strictEqual(MAIN.indexOf('data-random-effective-chain'), -1);
  assert(DIAG.indexOf('data-random-fallback-saved') >= 0);
  assert(DIAG.indexOf('data-random-fallback-factory') >= 0);
  assert(DIAG.indexOf('data-random-fallback-effective') >= 0);
  assert(DIAG.indexOf('data-random-effective-chain') >= 0);
  assert(DIAG.indexOf('data-random-setting-primary-raw') >= 0,
    'происхождение основного источника видно в диагностике');
  assert(DIAG.indexOf('data-random-fallback-raw') >= 0,
    'сырое сохранённое значение видно в диагностике');

  // ── (c) без служебной терминологии/дублей на основном экране ────────────
  ['adapter_not_implemented', 'адаптер не реализован', 'stageLabel',
   'data-random-activity', 'data-random-uses', 'data-random-advanced',
   'data-random-provider-summary-success', 'data-random-provider-summary-switch',
   'data-random-provider-diagnostics', 'secret-field', 'tech-key',
   'keys.random', 'A. Источники', 'B. Применения', 'C. Активность',
   'D. Дополнительно', 'Настройка:', 'Псевдослучайный откат',
   'Решений на случайности'].forEach(function (needle) {
    assert.strictEqual(MAIN.indexOf(needle), -1,
      'основной экран не содержит: ' + needle);
  });
  assert(MAIN.indexOf('data-random-now') >= 0,
    'снимок фактического источника и причины на месте');

  // ── (d) ключи/диагностика/применения/параметры — закрытые details ───────
  [['data-random-provider-details', 'Ключи'],
   ['data-random-diagnostics', 'Диагностика'],
   ['data-random-uses', 'Где используется'],
   ['data-random-advanced', 'Дополнительные параметры']].forEach(function (x) {
    assert.strictEqual(INDEX.indexOf(x[0] + ' open'), -1,
      'раздел «' + x[1] + '» закрыт по умолчанию');
    assert(INDEX.indexOf('<' + 'details class="card p-4 col-span-full min-w-0" ' + x[0]) >= 0
      || INDEX.indexOf(x[0]) >= 0, x[0] + ' существует');
  });
  assert.strictEqual(count(INDEX, 'data-random-provider="'), 3,
    'ровно три подробные карточки, и они внутри ключей');
  assert.strictEqual(count(KEYS, 'data-random-provider="'), 3,
    'подробные карточки находятся в свёрнутом разделе ключей');
  assert.strictEqual(MAIN.indexOf('data-random-provider="'), -1,
    'подробных карточек нет на основном экране');
  assert(KEYS.indexOf('data-random-ibm-key') >= 0);
  assert(KEYS.indexOf('data-random-ibm-crn') >= 0);
  assert(KEYS.indexOf('data-random-ibm-check') >= 0);
  assert(KEYS.indexOf('data-random-check') >= 0);
  assert(USES.indexOf('data-random-use=') >= 0);
  assert(ADV.indexOf('data-random-prng-mode') >= 0);
})();

// ── (e) модель: заводское значение как контрол, наследование vs отключение ─
(function () {
  const inherited = makeCtx(status({
    primary_setting_raw: '', primary_setting_state: 'absent',
  }), [
    cfg('random.primary_provider', '', 'default'),
    cfg('random.fallback_order', null, 'default'),
    cfg('random.fallback_enabled', true, 'default'),
  ]);
  assert.strictEqual(methods.randomPrimaryHint.call(inherited), 'По умолчанию');
  assert.strictEqual(methods.randomPrimaryValue.call(inherited), 'ibm_quantum',
    'заводской основной источник показан как значение селектора');
  assert.strictEqual(methods.randomFallbackStateChip.call(inherited).label,
    'по умолчанию');
  assert(methods.randomFallbackNote.call(inherited)
    .indexOf('заводской порядок') >= 0);
  assert.strictEqual(methods.randomFallbackStateChip.call(inherited).cls,
    'badge-info');

  const saved = makeCtx(status({
    fallback_order: ['lfdr', 'anu'],
    fallback_order_raw: ['lfdr', 'anu'],
    fallback_order_state: 'set',
    effective_order: ['ibm_quantum', 'lfdr', 'anu'],
  }), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', ['lfdr', 'anu'], 'global'),
    cfg('random.fallback_enabled', true, 'global'),
  ]);
  assert.strictEqual(methods.randomPrimaryHint.call(saved), 'Выбрано вручную');
  assert.strictEqual(methods.randomFallbackStateChip.call(saved).label,
    'сохранено вручную');
  assert(methods.randomFallbackNote.call(saved)
    .indexOf('Сохранён ваш порядок') >= 0);

  const disabled = makeCtx(status({
    fallback_enabled: false,
    fallback_order_raw: null,
    fallback_order_state: 'absent',
    effective_order: ['ibm_quantum'],
    effective_provider: 'ibm_quantum',
    resolved_primary: 'ibm_quantum',
    blocker: null,
    last_fallback_reason: null,
    providers: providers({
      ibm_quantum: { configured: true, state: 'active', reserve: 0,
                     consumable: false },
    }),
  }), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', null, 'default'),
    cfg('random.fallback_enabled', false, 'global'),
  ]);
  assert.strictEqual(methods.randomFallbackStateChip.call(disabled).label,
    'резерв отключён');
  assert.strictEqual(methods.randomFallbackStateChip.call(disabled).cls,
    'badge-muted');
  assert(methods.randomFallbackNote.call(disabled)
    .indexOf('отключён вручную') >= 0);
  assert(methods.randomFallbackNote.call(disabled)
    .indexOf('заводская цепочка') < 0,
    'выключенный резерв не выдаётся за заводскую цепочку');
  assert.strictEqual(methods.randomNowView.call(disabled).sourceLabel,
    'IBM Quantum');
  assert.strictEqual(methods.randomNowView.call(disabled).reasonLabel,
    'основной источник доступен');

  const inheritedEmpty = makeCtx(status({
    primary_setting_raw: '', primary_setting_state: 'absent',
    fallback_order: [],
    fallback_order_raw: [], fallback_order_state: 'set',
    effective_order: ['ibm_quantum'],
    effective_provider: null,
    resolved_primary: 'anu',
    blocker: null,
  }), [
    cfg('random.primary_provider', '', 'default'),
    cfg('random.fallback_order', [], 'global'),
    cfg('random.fallback_enabled', true, 'default'),
  ]);
  assert.strictEqual(methods.randomFallbackStateChip.call(inheritedEmpty).label,
    'сохранено пустым');
  assert(methods.randomFallbackNote.call(inheritedEmpty)
    .indexOf('переключений не будет') >= 0);
  assert(methods.randomFallbackNote.call(inheritedEmpty)
    .indexOf('заводская цепочка') < 0,
    'явный пустой резерв больше не подменяется заводской цепочкой');
  assert.deepStrictEqual(methods.randomFallbackBaseValue.call(inheritedEmpty),
    [], 'контрол показывает явное пустое решение');
  const emptyRows = methods.randomFallbackRows.call(inheritedEmpty);
  assert.strictEqual(byId(emptyRows, 'anu').enabled, false,
    'ANU не выглядит выбранным при сохранённом пустом резерве');
  assert.strictEqual(byId(emptyRows, 'lfdr').enabled, false);
  assert.strictEqual(byId(emptyRows, 'anu').statusLabel, 'не в резерве');

  const explicitEmpty = makeCtx(status({
    fallback_order_raw: [], fallback_order_state: 'set',
    effective_order: ['ibm_quantum'],
  }), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', [], 'global'),
    cfg('random.fallback_enabled', true, 'global'),
  ]);
  assert.strictEqual(methods.randomFallbackStateChip.call(explicitEmpty).label,
    'сохранено пустым');
  assert(methods.randomFallbackNote.call(explicitEmpty)
    .indexOf('переключений не будет') >= 0,
    'явный пустой резерв при явном primary не подменяется заводской цепочкой');
  assert(methods.randomFallbackNote.call(explicitEmpty)
    .indexOf('заводская цепочка') < 0);
  assert.deepStrictEqual(methods.randomFallbackBaseValue.call(explicitEmpty),
    [], 'сохранённое пустое решение — это и есть значение контрола');
  const explicitRows = methods.randomFallbackRows.call(explicitEmpty);
  assert.strictEqual(byId(explicitRows, 'anu').enabled, false);
  assert.strictEqual(byId(explicitRows, 'lfdr').enabled, false);
  assert.strictEqual(byId(explicitRows, 'anu').statusLabel, 'не в резерве');

  const invalid = makeCtx(status({
    primary_setting_raw: 'retired_provider',
    primary_setting_state: 'requires_resolution',
    blocker: 'provider_unavailable',
    last_fallback_reason: 'provider_unavailable',
  }), [
    cfg('random.primary_provider', 'retired_provider', 'global'),
    cfg('random.fallback_order', null, 'default'),
    cfg('random.fallback_enabled', true, 'default'),
  ]);
  assert(methods.randomPrimaryHint.call(invalid).indexOf('не действует') >= 0);
  assert.strictEqual(methods.randomFallbackStateChip.call(invalid).label,
    'не применяется');
  assert(methods.randomFallbackNote.call(invalid).indexOf('не применяется') >= 0);
  assert.strictEqual(MAIN.indexOf('retired_provider'), -1,
    'недействительный raw не показывается на основном экране');
  assert(DIAG.indexOf('randomPrimarySettingView().raw') >= 0,
    'raw доступен в диагностике');
})();

// ── (f) разрешён / проверен / используется; ключ ≠ проверка ───────────────
(function () {
  const ctx = makeCtx(status(), [
    cfg('keys.random_ibm_api_key', { configured: true, last4: 'ABCD' },
        'global'),
    cfg('keys.random_ibm_instance', 'open-instance', 'global'),
  ]);
  const rows = methods.randomProviderMainRows.call(ctx);
  assert.deepStrictEqual(rows.map(function (r) { return r.id; }),
    ['ibm_quantum', 'anu', 'lfdr']);
  const ibm = byId(rows, 'ibm_quantum');
  assert.strictEqual(ibm.stateLabel, 'не проверено',
    'наличие key/CRN не равно проверке');
  assert.strictEqual(ibm.used, false);
  const anu = byId(rows, 'anu');
  assert.strictEqual(anu.stateLabel, 'проверено');
  assert.strictEqual(anu.used, true, 'фактически используется только ANU');
  assert.strictEqual(anu.reserveText, '5');
  const lfdr = byId(rows, 'lfdr');
  assert.strictEqual(lfdr.stateLabel, 'не проверено');
  assert.strictEqual(lfdr.used, false);
  assert.strictEqual(lfdr.reserveText, '7');
  const fallbackRows = methods.randomFallbackRows.call(ctx);
  assert.strictEqual(byId(fallbackRows, 'lfdr').enabled, true,
    'LfDR разрешён в резерве, хотя ещё не проверен');
  assert.strictEqual(byId(fallbackRows, 'anu').enabled, true,
    'ANU разрешён и используется');

  const checkedCtx = makeCtx(status(), [
    cfg('keys.random_ibm_api_key', { configured: true, last4: 'ABCD' },
        'global'),
    cfg('keys.random_ibm_instance', 'open-instance', 'global'),
  ], {
    randomIbmCheck: { healthy: true, checked_at: 1700000001 },
  });
  assert.strictEqual(
    byId(methods.randomProviderMainRows.call(checkedCtx), 'ibm_quantum')
      .stateLabel,
    'проверено', 'подтверждённый доступ — «проверено»');

  const none = makeCtx(status({ providers: [] }));
  methods.randomProviderMainRows.call(none).forEach(function (r) {
    assert.strictEqual(r.stateLabel, 'нет данных', r.id + ': нет providers[]');
    assert.strictEqual(r.reserveText, 'нет данных');
  });

  const prng = makeCtx(status({
    quantum_active: false,
    effective_source: 'pseudorandom',
    effective_provider: null,
    resolved_primary: null,
    blocker: 'provider_unavailable',
    prng_active: true,
    last_batch: null,
  }));
  const now = methods.randomNowView.call(prng);
  assert.strictEqual(now.sourceLabel, 'псевдослучайный (локальный)');
  assert.strictEqual(now.reasonLabel, 'источник недоступен');
  assert.strictEqual(now.reasonLabel.indexOf('provider_unavailable'), -1,
    'сырой код причины не попадает на основной экран');
})();

// ── (f2) F-UI0810-R1-02: нет «используется» + «не настроен» ───────────────
(function () {
  const ctx = makeCtx(status());
  const now = methods.randomNowView.call(ctx);
  assert.strictEqual(now.sourceLabel, 'ANU Quantum Numbers');
  assert(now.reasonLabel.indexOf('переключение с IBM Quantum') === 0,
    'причина fallback атрибутирована источнику, а не фактическому ANU');
  assert(now.reasonLabel.indexOf('источник не настроен') >= 0);
  methods.randomProviderMainRows.call(ctx).forEach(function (r) {
    assert(!(r.used && r.stateLabel === 'не настроен'),
      r.id + ': нельзя одновременно «используется» и «не настроен»');
    assert(!(r.used && r.stateLabel === 'недоступен'), r.id);
  });

  const contradiction = makeCtx(status({
    providers: providers({
      anu: { configured: false, state: 'provider_unconfigured',
             reserve: 0, consumable: false },
    }),
  }));
  assert.strictEqual(methods.randomMainEffectiveProvider.call(contradiction),
    null, 'противоречивый DTO не даёт права называть ANU используемым');
  const cRows = methods.randomProviderMainRows.call(contradiction);
  assert.strictEqual(byId(cRows, 'anu').used, false);
  assert.strictEqual(byId(cRows, 'anu').stateLabel, 'не настроен');
  assert(cRows.every(function (r) {
    return !(r.used && (r.stateLabel === 'не настроен'
      || r.stateLabel === 'недоступен' || r.stateLabel === 'выключен'));
  }), 'ни одна строка не «используется» с нерабочим состоянием');
  const cNow = methods.randomNowView.call(contradiction);
  assert.strictEqual(cNow.sourceLabel, 'нет подтверждённого источника');
  assert(cNow.reasonLabel.indexOf('переключение с IBM Quantum') === 0);
})();

// ── (f3) F-UI0810-R1-03: IBM error — человеческая подпись, стадия в keys ──
(function () {
  const errCtx = makeCtx(status({
    providers: providers({
      ibm_quantum: { configured: true, state: 'provider_unconfigured',
                     last_error: 'invalid_instance', last_failure_at: 1700000001 },
    }),
  }), [
    cfg('keys.random_ibm_api_key', { configured: true, last4: 'ABCD' },
        'global'),
    cfg('keys.random_ibm_instance', 'open-instance', 'global'),
  ]);
  const ibm = byId(methods.randomProviderMainRows.call(errCtx), 'ibm_quantum');
  assert.strictEqual(ibm.stateLabel, 'ошибка подключения',
    'основной экран не показывает «ошибка стадии»');
  assert.strictEqual(ibm.used, false);
})();

// ── (f4) F-UI0810-R1-01: явный порядок при наследуемом primary действует ──
(function () {
  const inheritedSaved = makeCtx(status({
    primary_setting_raw: '',
    primary_setting_state: 'absent',
    fallback_order: ['lfdr', 'anu'],
    fallback_order_raw: ['lfdr', 'anu'],
    fallback_order_state: 'set',
    effective_order: ['ibm_quantum', 'lfdr', 'anu'],
  }), [
    cfg('random.primary_provider', '', 'default'),
    cfg('random.fallback_order', ['lfdr', 'anu'], 'global'),
    cfg('random.fallback_enabled', true, 'default'),
  ]);
  const ov = methods.randomFallbackOrderView.call(inheritedSaved);
  assert.strictEqual(ov.effectiveLabel,
    label('lfdr') + ' → ' + label('anu'),
    'действующий резерв совпадает с сохранённым порядком');
  assert.strictEqual(ov.effectiveChainLabel,
    label('ibm_quantum') + ' → ' + label('lfdr') + ' → ' + label('anu'));
  assert.strictEqual(methods.randomFallbackStateChip.call(inheritedSaved).label,
    'сохранено вручную');
  assert.strictEqual(methods.randomFallbackEffectiveMismatch.call(
    inheritedSaved), false);
  assert(methods.randomFallbackNote.call(inheritedSaved)
    .indexOf('Сохранён ваш порядок') >= 0);
  assert.deepStrictEqual(
    methods.randomFallbackRows.call(inheritedSaved)
      .filter(function (r) { return r.enabled; })
      .map(function (r) { return r.id; }),
    ['lfdr', 'anu'], 'строки идут в сохранённом порядке');

  const mismatched = makeCtx(status({
    fallback_order: ['lfdr', 'anu'],
    fallback_order_raw: ['lfdr', 'anu'],
    fallback_order_state: 'set',
    effective_order: ['ibm_quantum', 'anu', 'lfdr'],
  }), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', ['lfdr', 'anu'], 'global'),
    cfg('random.fallback_enabled', true, 'global'),
  ]);
  assert.strictEqual(methods.randomFallbackEffectiveMismatch.call(mismatched),
    true, 'расхождение сохранённого и действующего порядка обнаружено');
  assert.strictEqual(methods.randomFallbackStateChip.call(mismatched).label,
    'сохранено, не применяется');
  assert(methods.randomFallbackNote.call(mismatched)
    .indexOf('ещё не действует') >= 0,
    'расхождение не прячется: основной экран предупреждает');

  // R2-01: пустой сохранённый выбор против непустого effective — это тоже
  // расхождение, а не «переключений не будет».
  const emptyVsEffective = makeCtx(status({
    fallback_order: ['anu', 'lfdr'],
    fallback_order_raw: [],
    fallback_order_state: 'set',
    effective_order: ['ibm_quantum', 'anu', 'lfdr'],
  }), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', [], 'global'),
    cfg('random.fallback_enabled', true, 'global'),
  ]);
  assert.strictEqual(
    methods.randomFallbackEffectiveMismatch.call(emptyVsEffective), true,
    'saved=[] против effective != [] — расхождение');
  assert.strictEqual(
    methods.randomFallbackStateChip.call(emptyVsEffective).label,
    'сохранено, не применяется');
  assert(methods.randomFallbackNote.call(emptyVsEffective)
    .indexOf('ещё не действует') >= 0);
  assert(methods.randomFallbackNote.call(emptyVsEffective)
    .indexOf('переключений не будет') < 0,
    'нельзя утверждать «переключений не будет» при непустом effective');

  // R2-01: непустой сохранённый выбор против пустого effective.
  const effectiveVsEmpty = makeCtx(status({
    fallback_order: [],
    fallback_order_raw: ['lfdr'],
    fallback_order_state: 'set',
    effective_order: ['ibm_quantum'],
  }), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', ['lfdr'], 'global'),
    cfg('random.fallback_enabled', true, 'global'),
  ]);
  assert.strictEqual(
    methods.randomFallbackEffectiveMismatch.call(effectiveVsEmpty), true);
  assert.strictEqual(
    methods.randomFallbackStateChip.call(effectiveVsEmpty).label,
    'сохранено, не применяется');
  assert(methods.randomFallbackNote.call(effectiveVsEmpty)
    .indexOf('Сохранён ваш порядок') < 0);

  // R2-01: старый/смешанный DTO без effective_order — сравнение идёт по
  // фактическому fallback_order, а не молчит.
  const mixedDto = makeCtx(status({
    fallback_order: ['anu', 'lfdr'],
    fallback_order_raw: [],
    fallback_order_state: 'set',
    effective_order: [],
  }), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', [], 'global'),
    cfg('random.fallback_enabled', true, 'global'),
  ]);
  assert.strictEqual(methods.randomFallbackEffectiveMismatch.call(mixedDto),
    true, 'old/mixed DTO с непустым fallback_order не считается пустым');
  assert(methods.randomFallbackNote.call(mixedDto)
    .indexOf('переключений не будет') < 0);
})();

// ── (g) причина переключения — человеческая; неизвестный код без raw ──────
(function () {
  const unknown = makeCtx(status({
    blocker: 'future_code',
    last_fallback_reason: 'future_code',
    last_fallback_at: 1700000500,
    resolved_primary: 'lfdr',
    effective_provider: 'lfdr',
  }));
  const now = methods.randomNowView.call(unknown);
  assert.strictEqual(now.sourceLabel, 'LfDR QRNG');
  assert.strictEqual(now.reasonLabel,
    'переключение с IBM Quantum: причина не описана');
  assert.strictEqual(now.reasonLabel.indexOf('future_code'), -1);
  assert.strictEqual(now.timeLabel, 'T1700000500');
  assert.strictEqual(methods.randomLastSwitchView.call(unknown).code,
    'future_code', 'сырой код остаётся доступным для диагностики');

  const batch = methods.randomLastBatchLabel.call(makeCtx(status()));
  assert(batch.indexOf('ANU Quantum Numbers') >= 0);
  assert(batch.indexOf('1024') >= 0);
  assert(batch.indexOf('T1700000200') >= 0);
})();

// ── (h) data: черновик живёт отдельно, ничего не сохраняется само ────────
(function () {
  assert.strictEqual(data.randomFallbackDraft, null);
  assert.strictEqual(count(INDEX, 'data-random-fallback-save\n'), 1);
  assert.strictEqual(count(INDEX, 'data-random-fallback-cancel'), 1);
})();

console.log('QRNG-UI08-10-OK');
