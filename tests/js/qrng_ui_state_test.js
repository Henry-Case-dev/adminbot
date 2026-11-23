'use strict';
/* QRNG UI-06 (24.11.2026) — selected/effective/saved/factory fallback state.
 *
 * Проверяет РЕАЛЬНУЮ логику web/app.js (require), не grep:
 *   (a) сохранённый primary/order, заводское значение, effective route из
 *       /api/status различимы; отсутствие строки — не пустой резерв;
 *   (b) ни один провайдер effective chain не получает «не в резерве»;
 *   (c) toggle/стрелки меняют только черновик; Save отправляет полный
 *       порядок и не теряет LfDR; Cancel не пишет;
 *   (d) invalid saved primary/order инициализируют редактор effective/factory
 *       цепочкой, а не недействительной сохранённой строкой;
 *   (e) выключенный авторезерв — «резерв выключен», не «не в резерве»;
 *   (f) состояние провайдера отделено от key presence; «проверено» только
 *       для реального active/checked.
 *
 * Запуск: node tests/js/qrng_ui_state_test.js -> QRNG-UI06-OK
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

const ROOT = path.join(__dirname, '..', '..');
const APP_PATH = path.join(ROOT, 'web', 'app.js');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(APP_PATH, 'utf8');
require(APP_PATH);

assert(captured, 'Vue.createApp не вызван');
const data = captured.data();
const methods = captured.methods || {};
const computed = captured.computed || {};

function label(id) {
  return methods.randomProviderLabel.call({}, id);
}

function providers(overrides) {
  const base = [
    { id: 'ibm_quantum', configured: false, state: 'provider_unconfigured',
      reserve: 0, consumable: false, quarantined: 0 },
    { id: 'anu', configured: true, state: 'unverified',
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
    last_batch: null,
    draws: { quantum: 12, pseudorandom: 0 },
    recent_draws: [],
    recent_draws_scope: 'global',
    anu_state: 'active',
    lfdr_state: 'active',
    key_present: true,
    key_fingerprint: 'test',
    prng_active: false,
    prng_setting: true,
  };
  return Object.assign(base, overrides || {});
}

function cfg(key, value, source) {
  return { key: key, value: value, per_chat: false,
           source: source, updated_at: null };
}

function makeCtx(st, configItems) {
  const source = methods._randomSourceView.call({}, st);
  const activity = computed.randomActivityView.call({ randomSource: source });
  const ctx = Object.assign({}, methods, {
    isGlobalAdmin: true,
    configItems: configItems || [],
    randomActivityView: activity,
    randomFallbackDraft: null,
    randomFallbackSaveBusy: false,
    randomCheck: null,
    posts: [],
    toast: function () {},
    fmtTs: function (v) { return String(v); },
    loadConfig: async function () {},
    loadStatus: async function () {},
    persistItems: async function (items) {
      ctx.posts.push(items);
      return { saved: items.map(function (it) { return it.key; }) };
    },
  });
  return ctx;
}

function row(rows, id) {
  return rows.filter(function (r) { return r.id === id; })[0];
}

function count(text, needle) {
  return (text.match(new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
    'g')) || []).length;
}

(async function () {
// ── (a) сохранённое/заводское/effective: владелец видит IBM, ANU в резерве ─
{
  const ctx = makeCtx(status(), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', null, 'default'),
    cfg('random.fallback_enabled', true, 'default'),
  ]);
  const pview = methods.randomPrimarySettingView.call(ctx);
  assert.strictEqual(pview.state, 'set', 'primary — сохранён');
  assert.strictEqual(pview.selected, 'ibm_quantum');
  assert.strictEqual(pview.stateLabel, 'сохранён');
  assert.strictEqual(methods.randomEffectiveUsedLabel.call(ctx),
    label('anu'), 'фактически используется ANU (runtime)');

  const ov = methods.randomFallbackOrderView.call(ctx);
  assert.strictEqual(ov.state, 'absent', 'строки fallback_order нет');
  assert.strictEqual(ov.savedHint, 'наследуется заводское');
  assert.strictEqual(ov.savedLabel, label('anu') + ' → ' + label('lfdr'),
    'сохранённый = заводской хвост, не пустой');
  assert.strictEqual(ov.effectiveLabel, label('anu') + ' → ' + label('lfdr'));

  const rows = methods.randomFallbackRows.call(ctx);
  assert.deepStrictEqual(rows.map(function (r) { return r.id; }),
    ['anu', 'lfdr'], 'primary в резерв не входит');
  assert.strictEqual(row(rows, 'anu').enabled, true,
    'ANU в действующем резерве — checked');
  assert.strictEqual(row(rows, 'anu').effective, true);
  assert.strictEqual(row(rows, 'lfdr').enabled, true,
    'LfDR не потерян при отсутствии сохранённой строки');
  assert.strictEqual(row(rows, 'lfdr').effective, true);
  assert.strictEqual(row(rows, 'anu').statusLabel, 'по умолчанию');
  assert(!rows.some(function (r) { return r.statusLabel === 'не в резерве'; }),
    'ни один effective-провайдер не помечен «не в резерве»');

  // Falsifiable: меняем сохранённое/effective — подписи обязаны измениться.
  const ctx2 = makeCtx(status({
    fallback_order: ['lfdr'],
    fallback_order_raw: ['lfdr'],
    fallback_order_state: 'set',
    effective_order: ['ibm_quantum', 'lfdr'],
  }), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', ['lfdr'], 'global'),
    cfg('random.fallback_enabled', true, 'global'),
  ]);
  const ov2 = methods.randomFallbackOrderView.call(ctx2);
  assert.notStrictEqual(ov2.savedLabel, ov.savedLabel,
    'сохранённый порядок меняет подпись');
  assert.notStrictEqual(ov2.effectiveLabel, ov.effectiveLabel,
    'effective order меняет подпись');
  const rows2 = methods.randomFallbackRows.call(ctx2);
  assert.strictEqual(row(rows2, 'lfdr').enabled, true);
  assert.strictEqual(row(rows2, 'anu').enabled, false);
  assert.strictEqual(row(rows2, 'anu').statusLabel, 'не в резерве',
    'только реально исключённый получает badge');
}

// ── (a2) live raw = [] при наследуемом primary: это не пустой резерв ──────
{
  const ctx = makeCtx(status({
    primary_provider: 'ibm_quantum',
    primary_setting_raw: '',
    primary_setting_state: 'absent',
    fallback_order: ['anu', 'lfdr'],
    fallback_order_raw: [],
    fallback_order_state: 'set',
    effective_order: ['ibm_quantum', 'anu', 'lfdr'],
  }), [
    cfg('random.primary_provider', '', 'default'),
    cfg('random.fallback_order', [], 'global'),
    cfg('random.fallback_enabled', true, 'default'),
  ]);
  const ov = methods.randomFallbackOrderView.call(ctx);
  assert.strictEqual(ov.state, 'set');
  assert.strictEqual(ov.savedLabel, 'пусто (резерв не выбран)',
    'сохранённая пустая строка показана как есть');
  assert.strictEqual(ov.savedHint, 'сохранён пустой; действует заводская цепочка',
    'пустая строка при наследуемом primary не выдаётся за выключенный резерв');
  assert.strictEqual(ov.effectiveLabel, label('anu') + ' → ' + label('lfdr'));
  assert.deepStrictEqual(methods.randomFallbackBaseValue.call(ctx),
    ['anu', 'lfdr'], 'редактор инициализирован действующей цепочкой');
  const rows = methods.randomFallbackRows.call(ctx);
  assert.strictEqual(row(rows, 'anu').enabled, true);
  assert.strictEqual(row(rows, 'lfdr').enabled, true);
  assert.strictEqual(row(rows, 'anu').statusLabel, 'действует');
  assert(!rows.some(function (r) { return r.statusLabel === 'не в резерве'; }),
    'live-случай [] не помечает ANU/LfDR «не в резерве»');
  methods.randomFallbackToggleDraft.call(ctx, 'anu', true);
  assert.deepStrictEqual(ctx.randomFallbackDraft, ['lfdr', 'anu'],
    'включение ANU из live [] сохраняет LfDR в черновике');
}

// ── (b) опасный toggle из «пустого» состояния: LfDR не выбрасывается ──────
{
  const ctx = makeCtx(status(), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', null, 'default'),
    cfg('random.fallback_enabled', true, 'default'),
  ]);
  const ok = methods.randomFallbackToggleDraft.call(ctx, 'anu', true);
  assert.strictEqual(ok, true);
  assert.strictEqual(ctx.posts.length, 0, 'toggle не делает POST');
  assert.deepStrictEqual(ctx.randomFallbackDraft, ['lfdr', 'anu'],
    'черновик содержит оба провайдера, а не только ANU');
  assert.notDeepStrictEqual(ctx.randomFallbackDraft, ['anu'],
    'старый опасный путь Save(["anu"]) невозможен');

  // Save из нетронутой заводской цепочки отправляет полный порядок.
  ctx.randomFallbackDraft = null;
  methods.randomFallbackBeginEdit.call(ctx);
  assert.deepStrictEqual(ctx.randomFallbackDraft, ['anu', 'lfdr'],
    'редактор инициализирован заводским/effective хвостом');
  const saved = await methods.randomFallbackSaveDraft.call(ctx);
  assert.strictEqual(saved, true);
  assert.strictEqual(ctx.posts.length, 1, 'ровно один POST на Save');
  assert.deepStrictEqual(ctx.posts[0][0].value, ['anu', 'lfdr'],
    'Save отправляет полный порядок, LfDR не выброшен');
  assert.strictEqual(ctx.randomFallbackDraft, null,
    'успешный Save закрывает черновик');

  // Cancel не пишет и возвращает сохранённое/заводское состояние.
  methods.randomFallbackToggleDraft.call(ctx, 'lfdr', false);
  assert.deepStrictEqual(ctx.randomFallbackDraft, ['anu']);
  methods.randomFallbackCancelDraft.call(ctx);
  assert.strictEqual(ctx.randomFallbackDraft, null, 'Cancel закрывает черновик');
  assert.strictEqual(ctx.posts.length, 1, 'Cancel не сделал второй POST');
}

// ── (c) invalid primary/order: редактор берёт effective/factory цепочку ───
{
  const ctx = makeCtx(status({
    primary_provider: 'ibm_quantum',
    primary_setting_raw: 'lizaonair',
    primary_setting_state: 'requires_resolution',
    fallback_order: ['lfdr', 'anu'],
    fallback_order_raw: ['lfdr', 'anu'],
    fallback_order_state: 'set',
    effective_order: ['ibm_quantum', 'anu', 'lfdr'],
  }), [
    cfg('random.primary_provider', 'lizaonair', 'global'),
    cfg('random.fallback_order', ['lfdr', 'anu'], 'global'),
    cfg('random.fallback_enabled', true, 'global'),
  ]);
  const pview = methods.randomPrimarySettingView.call(ctx);
  assert.strictEqual(pview.invalid, true);
  assert.strictEqual(pview.stateLabel, 'требует разрешения');
  assert(pview.label.indexOf('lizaonair') >= 0,
    'недействительное сохранённое значение показано как есть');
  const ov = methods.randomFallbackOrderView.call(ctx);
  assert.strictEqual(ov.savedLabel, label('lfdr') + ' → ' + label('anu'),
    'сохранённая строка всё ещё видна отдельно');
  assert(ov.savedHint.indexOf('не применяется') >= 0,
    'сохранённая строка не выдаётся за действующую');
  assert.deepStrictEqual(methods.randomFallbackBaseValue.call(ctx),
    ['anu', 'lfdr'], 'редактор инициализирован effective цепочкой');
  const rows = methods.randomFallbackRows.call(ctx);
  assert.strictEqual(row(rows, 'anu').enabled, true);
  assert.strictEqual(row(rows, 'lfdr').enabled, true);
  assert(!rows.some(function (r) { return r.statusLabel === 'не в резерве'; }),
    'effective-провайдеры не помечены «не в резерве» даже при invalid primary');

  const saved = await methods.randomFallbackSaveDraft.call(
    Object.assign({}, ctx, { randomFallbackDraft: ['anu', 'lfdr'] }));
  assert.strictEqual(saved, true);
  assert.deepStrictEqual(ctx.posts[0][0].value, ['anu', 'lfdr'],
    'Save полного effective-порядка не теряет LfDR');
}

{
  const ctx = makeCtx(status({
    fallback_order: ['anu'],
    fallback_order_raw: 'not-json',
    fallback_order_state: 'requires_resolution',
    effective_order: ['ibm_quantum', 'anu', 'lfdr'],
  }), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', 'not-json', 'global'),
    cfg('random.fallback_enabled', true, 'global'),
  ]);
  const ov = methods.randomFallbackOrderView.call(ctx);
  assert.strictEqual(ov.state, 'requires_resolution');
  assert.strictEqual(ov.savedHint, 'требует разрешения');
  assert.deepStrictEqual(methods.randomFallbackBaseValue.call(ctx),
    ['anu', 'lfdr'], 'invalid saved order не превращает резерв в пустой');
  const rows = methods.randomFallbackRows.call(ctx);
  assert(!rows.some(function (r) { return r.statusLabel === 'не в резерве'; }));
}

// ── (d) выключенный авторезерв ≠ «не в резерве» ──────────────────────────
{
  const ctx = makeCtx(status({
    fallback_enabled: false,
    fallback_order: [],
    fallback_order_raw: null,
    fallback_order_state: 'absent',
    effective_order: ['ibm_quantum'],
  }), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', null, 'default'),
    cfg('random.fallback_enabled', false, 'global'),
  ]);
  const sv = methods.randomFallbackSettingView.call(ctx);
  assert.strictEqual(sv.enabled, false);
  assert.strictEqual(sv.stateLabel, 'отключена');
  assert(sv.label.indexOf('выключена') >= 0);
  const ov = methods.randomFallbackOrderView.call(ctx);
  assert.strictEqual(ov.effectiveLabel, 'автоматический резерв выключен');
  const rows = methods.randomFallbackRows.call(ctx);
  assert.strictEqual(row(rows, 'anu').enabled, true,
    'сохранённый/заводской резерв остаётся видимым');
  assert.strictEqual(row(rows, 'lfdr').enabled, true);
  assert.strictEqual(row(rows, 'anu').statusLabel, 'резерв выключен');
  assert(!rows.some(function (r) { return r.statusLabel === 'не в резерве'; }),
    'выключенный резерв не называется «не в резерве»');
  assert.deepStrictEqual(methods.randomFallbackBaseValue.call(ctx),
    ['anu', 'lfdr'], 'при выключенном резерве редактор не пуст');

  const inh = makeCtx(status(), [
    cfg('random.primary_provider', 'ibm_quantum', 'global'),
    cfg('random.fallback_order', null, 'default'),
    cfg('random.fallback_enabled', true, 'default'),
  ]);
  const isv = methods.randomFallbackSettingView.call(inh);
  assert.strictEqual(isv.inherited, true);
  assert.strictEqual(isv.stateLabel, 'наследуется');
  assert(isv.label.indexOf('наследуется по умолчанию') >= 0);
}

// ── (e) provider state отдельно от key presence ───────────────────────────
{
  const ctx = makeCtx(status({
    providers: providers({
      anu: { configured: true, state: 'unverified' },
      lfdr: { configured: true, state: 'unverified' },
    }),
  }), []);
  const anu = methods.randomProviderCard.call(ctx, 'anu');
  assert.strictEqual(anu.keyPresent, true, 'ключ ANU присутствует');
  assert.strictEqual(anu.checked, false, 'key presence ≠ проверка');
  assert.strictEqual(anu.stateLabel, 'сохранён, не проверен');
  assert.notStrictEqual(anu.stateCls, 'badge-ok');
  const lfdr = methods.randomProviderCard.call(ctx, 'lfdr');
  assert.strictEqual(lfdr.stateLabel, 'не проверено');
  assert.notStrictEqual(lfdr.stateCls, 'badge-ok');

  const activeCtx = makeCtx(status({
    providers: providers({ anu: { configured: true, state: 'active' } }),
  }), []);
  const active = methods.randomProviderCard.call(activeCtx, 'anu');
  assert.strictEqual(active.stateLabel, 'проверено');
  assert.strictEqual(active.checked, true);
  assert.strictEqual(active.stateCls, 'badge-ok');

  const noneCtx = makeCtx(status({
    providers: providers({ anu: { configured: false,
                                  state: 'provider_unconfigured' } }),
  }), []);
  assert.strictEqual(methods.randomProviderCard.call(noneCtx, 'anu').stateLabel,
    'не настроен');

  const ibm = methods.randomProviderCard.call(ctx, 'ibm_quantum');
  assert.strictEqual(ibm.stateLabel, 'адаптер не реализован');
  assert.strictEqual(ibm.checked, false);

  const badCtx = makeCtx(status({
    providers: providers({ lfdr: { configured: true, state: 'degraded' } }),
  }), []);
  assert.strictEqual(methods.randomProviderCard.call(badCtx, 'lfdr').stateLabel,
    'недоступен');

  const activityRows = methods.randomActivityRows.call(activeCtx);
  const anuRow = activityRows.filter(function (r) { return r.id === 'anu'; })[0];
  assert.strictEqual(anuRow.state, 'проверено');
}

// ── (f) index/data: явный Save/Cancel, никакого «не в резерве» в шаблоне ──
{
  assert.strictEqual(data.randomFallbackDraft, null,
    'черновик живёт в data и по умолчанию отсутствует');
  assert(APP_JS.indexOf('randomFallbackSaveDraft: async function') >= 0);
  assert(INDEX.indexOf('data-random-fallback-save') >= 0, 'кнопка Save');
  assert(INDEX.indexOf('data-random-fallback-cancel') >= 0, 'кнопка Cancel');
  assert(INDEX.indexOf('data-random-fallback-status') >= 0,
    'статус каждого провайдера виден');
  assert(INDEX.indexOf('data-random-fallback-effective-state') >= 0,
    'effective-флаг строки виден в DOM');
  assert(INDEX.indexOf('setRandomFallbackIncluded(') < 0,
    'шаблон не вызывает старый persist-on-toggle');
  assert(INDEX.indexOf('не в резерве') < 0,
    'статический badge «не в резерве» удалён');
  assert.strictEqual(count(INDEX, 'data-random-primary'), 1,
    'ровно один настоящий primary-селектор');
  assert.strictEqual(count(INDEX, 'data-random-provider-badge'), 3,
    'три карточки используют stateLabel');
  assert(INDEX.indexOf('randomProviderCard(\'anu\').stateLabel') >= 0,
    'ANU badge — состояние, не key presence');
  assert(INDEX.indexOf('randomProviderCard(\'anu\').configured ? \'ключ сохранён\'') < 0,
    'наличие ключа больше не рисуется как успех');
}

console.log('QRNG-UI06-OK');
})().catch(function (e) {
  console.error(e && e.stack || e);
  process.exit(1);
});
