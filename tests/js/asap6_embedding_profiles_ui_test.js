'use strict';
/* ASAP 5 §13C / ASAP 6 §7 (embeddings-ui, W2-D): три НЕЗАВИСИМЫХ профиля
 * эмбеддингов (Primary / Запасная 1 / Запасная 2) в UI настроек.
 *
 * Дефект (ASAP 6 §7): web/app.js рендерил Запасную 2 через СТАРЫЕ общие
 * поля models.embedding_fallback_base_url / models.embedding_fallback_model
 * (зеркало с Запасной 1) с пометкой «адрес и модель общие» — incomplete
 * migration после появления каталога models.embedding_fallback{1,2}_*.
 *
 * Покрытие:
 *   (a) F1 и F2 рендерят РАЗНЫЕ привязки: множества ключей полей не
 *       пересекаются, секреты свои; черновик (draft) одного профиля не
 *       виден другому (blockFieldValue по своим ключам) → saveBlock не
 *       может тронуть чужой профиль;
 *   (b) поле «Квота-группа ключа» присутствует у обеих запасных с
 *       человеческим пояснением; raw alias-строка квот — в
 *       Developer-подблоке, не как основное поле профиля;
 *   (c) наследование честное: пустое поле модели/адреса запасной даёт
 *       подпись «Настроено: наследовать · Фактически: …» (F2 резолвит из
 *       Запасной 1, F1 — из легаси-общего; без выдуманных имён), непустое
 *       своё значение — подписи нет;
 *   (d) blockFieldPlaceholder отдаёт честный placeholder наследования;
 *   (e) index.html реально подключает hint/effective-подпись в ОБОИХ
 *       subBlocks-шаблонах и guard testable для Developer-подблока.
 *
 * Запуск: node tests/js/asap6_embedding_profiles_ui_test.js
 *          → EMBEDDING-PROFILES-UI-OK
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

// ── моки окружения (паттерн round1024_providers_fullscreen_test.js) ─────────
const _ls = {};
global.localStorage = {
  get length() { return Object.keys(_ls).length; },
  key(i) { return Object.keys(_ls)[i]; },
  getItem(k) {
    return Object.prototype.hasOwnProperty.call(_ls, k) ? _ls[k] : null;
  },
  setItem(k, v) { _ls[k] = String(v); },
  removeItem(k) { delete _ls[k]; },
};
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
        const i = _bodyChildren.indexOf(this);
        if (i >= 0) _bodyChildren.splice(i, 1);
      },
    };
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) {
      const i = _bodyChildren.indexOf(el);
      if (i >= 0) _bodyChildren.splice(i, 1);
      return el;
    },
  },
  execCommand() { return true; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
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

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const data = captured.data();

// ── добываем блок embeddings из боевой конфигурации PROVIDER_BLOCKS ─────────
const blocks = data.providerBlocks;
assert.ok(Array.isArray(blocks) && blocks.length, 'providerBlocks в data()');
const emb = blocks.find((b) => b.id === 'embeddings');
assert.ok(emb && emb.subBlocks, 'блок embeddings с subBlocks');

const sbMain = emb.subBlocks.find((s) => s.id === 'embeddings_main');
const sb1 = emb.subBlocks.find((s) => s.id === 'embeddings_fallback1');
const sb2 = emb.subBlocks.find((s) => s.id === 'embeddings_fallback2');
const sbDev = emb.subBlocks.find((s) => s.id === 'embeddings_developer');
assert.ok(sbMain && sb1 && sb2 && sbDev, 'все 4 подблока на месте');

// ── (a) НЕЗАВИСИМЫЕ привязки F1/F2: без скрытого зеркала ────────────────────
const keys1 = sb1.fields.map((f) => f.key);
const keys2 = sb2.fields.map((f) => f.key);
const shared = keys1.filter((k) => keys2.indexOf(k) >= 0);
assert.deepStrictEqual(shared, [],
  '(a) F1 и F2 не имеют общих полей (зеркало models.embedding_fallback_* '
  + 'запрещено — изменение одного профиля не пишет другой)');

const LEGACY_SHARED = ['models.embedding_fallback_base_url',
  'models.embedding_fallback_model'];
for (const sb of [sb1, sb2]) {
  for (const f of sb.fields) {
    assert.ok(LEGACY_SHARED.indexOf(f.key) < 0,
      `(a) ${sb.id}: поле ${f.key} не легаси-общее (incomplete migration)`);
  }
}

const f1model = sb1.fields.find((f) => f.role === 'model');
const f2model = sb2.fields.find((f) => f.role === 'model');
const f1base = sb1.fields.find((f) => f.role === 'base_url');
const f2base = sb2.fields.find((f) => f.role === 'base_url');
assert.strictEqual(f1model.key, 'models.embedding_fallback1_model',
  '(a) F1: собственная модель (каталог ASAP 5)');
assert.strictEqual(f2model.key, 'models.embedding_fallback2_model',
  '(a) F2: собственная модель, НЕ наследует поле F1');
assert.strictEqual(f1base.key, 'models.embedding_fallback1_base_url',
  '(a) F1: собственный адрес');
assert.strictEqual(f2base.key, 'models.embedding_fallback2_base_url',
  '(a) F2: собственный адрес');
const f1key = sb1.fields.find((f) => f.secret);
const f2key = sb2.fields.find((f) => f.secret);
assert.strictEqual(f1key.key, 'keys.embedding_fallback_api_key',
  '(a) F1: свой ключ');
assert.strictEqual(f2key.key, 'keys.embedding_fallback_api_key_2',
  '(a) F2: свой ключ');

// черновик одного профиля не виден другому (механика blockFieldValue)
function mkCtx(configItems, drafts) {
  const ctx = {
    configItems: configItems || [],
    blockDrafts: drafts || {},
  };
  ctx.blockFieldValue = methods.blockFieldValue.bind(ctx);
  return ctx;
}
{
  const ctx = mkCtx(
    [{ key: 'models.embedding_fallback2_model', value: '' }],
    { 'models.embedding_fallback1_model': 'fb1-draft' });
  assert.strictEqual(ctx.blockFieldValue(f1model), 'fb1-draft',
    '(a) draft F1 виден в F1');
  assert.strictEqual(ctx.blockFieldValue(f2model), '',
    '(a) draft F1 НЕ протекает в F2 (разные ключи привязки)');
  ctx.blockDrafts['models.embedding_fallback2_model'] = 'fb2-draft';
  assert.strictEqual(ctx.blockFieldValue(f1model), 'fb1-draft',
    '(a) правка F2 не меняет F1');
  assert.strictEqual(ctx.blockFieldValue(f2model), 'fb2-draft',
    '(a) правка F2 видна в F2');
}

// ── (b) квота-группа: человеческое поле с пояснением; raw — в Developer ─────
const QUOTA_RE = /quota_group/;
for (const sb of [sb1, sb2]) {
  const q = sb.fields.find((f) => QUOTA_RE.test(f.key));
  assert.ok(q, `(b) ${sb.id}: поле квота-группы присутствует`);
  assert.ok(!q.secret, '(b) квота-группа — не секрет');
  assert.ok(q.hint && q.hint.indexOf('одинаковой группой') >= 0
    && q.hint.indexOf('общий реальный лимит') >= 0
    && /2 независимые квоты/.test(q.hint),
    '(b) пояснение: одинаковая группа = общий лимит, пример с 2 квотами');
  // поле стоит рядом с credential (сразу после ключа в списке полей)
  const keyIdx = sb.fields.indexOf(f1key && sb === sb1 ? f1key
    : sb.fields.find((f) => f.secret));
  assert.ok(sb.fields.indexOf(q) > keyIdx,
    '(b) квота-группа идёт после ключа (возле credential)');
}
{
  const devFields = sbDev.fields.map((f) => f.key);
  assert.deepStrictEqual(devFields, ['keys.embedding_quota_group_labels'],
    '(b) raw alias-строка — единственное поле Developer-подблока');
  assert.strictEqual(sbDev.testable, false,
    '(b) Developer-подблок без «Проверить» (нет подключения)');
  const mainKeys = sbMain.fields.map((f) => f.key);
  assert.ok(mainKeys.indexOf('keys.embedding_quota_group_labels') < 0,
    '(b) raw alias-строка больше НЕ основное поле Primary');
}

// ── (c) честное наследование: blockEffectiveNote ─────────────────────────────
function mkNoteCtx(configItems, drafts) {
  const ctx = mkCtx(configItems, drafts);
  ctx.cfgStrValue = methods.cfgStrValue.bind(ctx);
  ctx.embeddingResolvedFor = methods.embeddingResolvedFor.bind(ctx);
  ctx.blockEffectiveNote = methods.blockEffectiveNote.bind(ctx);
  return ctx;
}
{
  // F2 пусто, F1 задана → «Фактически: <модель F1> (из «Запасной 1»)»
  const ctx = mkNoteCtx([
    { key: 'models.embedding_fallback1_model', value: ' emb-f1-real ' },
  ]);
  const note = ctx.blockEffectiveNote(f2model);
  assert.ok(note.indexOf('Настроено: наследовать') >= 0,
    '(c) F2 пусто: «Настроено: наследовать»');
  assert.ok(note.indexOf('emb-f1-real') >= 0 && note.indexOf('Запасной 1') >= 0,
    '(c) F2 резолвит из Запасной 1: ' + note);
  // у F1 в этом ctx СВОЁ значение → режима наследования нет
  assert.strictEqual(ctx.blockEffectiveNote(f1model), '',
    '(c) F1 настроена явно — подписи наследования нет');
  // resolved берётся ТОЛЬКО из реальных конфиг-значений (не выдуман)
  assert.strictEqual(ctx.embeddingResolvedFor('fallback_2', 'model'),
    'emb-f1-real', '(c) embeddingResolvedFor зеркалит resolve_embedding_profiles');
  // всё пусто (ни своего, ни легаси, ни F1) → честные фразы без выдумки
  const ctx0 = mkNoteCtx([]);
  const note1 = ctx0.blockEffectiveNote(f1model);
  assert.ok(note1.indexOf('Настроено: наследовать') >= 0,
    '(c) F1 пусто: «Настроено: наследовать»');
  assert.ok(note1.indexOf('легаси') >= 0,
    '(c) F1 без резолва — честная generic-фраза: ' + note1);
  const note2 = ctx0.blockEffectiveNote(f2model);
  assert.ok(note2.indexOf('Настроено: наследовать') >= 0
    && note2.indexOf('Запасной 1') >= 0,
    '(c) F2 без резолва — честная фраза про Запасную 1: ' + note2);
  // F1 резолвит из легаси-общего поля
  const ctx2 = mkNoteCtx([
    { key: 'models.embedding_fallback_model', value: 'legacy-shared-m' },
  ]);
  const note1b = ctx2.blockEffectiveNote(f1model);
  assert.ok(note1b.indexOf('legacy-shared-m') >= 0
    && note1b.indexOf('общее поле запасных') >= 0,
    '(c) F1 резолвит из легаси-общего: ' + note1b);
  // непустое своё значение → подписи нет
  const ctx3 = mkNoteCtx([], { 'models.embedding_fallback2_model': 'own-m' });
  assert.strictEqual(ctx3.blockEffectiveNote(f2model), '',
    '(c) своё значение — режим наследования не показываем');
  // черновик-ввод (непустой после trim) скрывает подпись; пробельный
  // черновик = effectively пустое поле → подпись честно остаётся
  // (бэкенд strip'ит значения, так что ' ' реально означает наследование).
  const ctx4 = mkNoteCtx([
    { key: 'models.embedding_fallback1_model', value: 'emb-f1-real' },
  ], { 'models.embedding_fallback2_model': '  ' });
  assert.ok(ctx4.blockEffectiveNote(f2model).indexOf('наследовать') >= 0,
    '(c) пробельный черновик = effectively пусто, подпись остаётся');
  ctx4.blockDrafts['models.embedding_fallback2_model'] = 'typed-m';
  assert.strictEqual(ctx4.blockEffectiveNote(f2model), '',
    '(c) реальный ввод скрывает подпись (draft-приоритет)');
  // Primary/Developer не имеют effectiveAlias
  for (const f of sbMain.fields.concat(sbDev.fields)) {
    assert.ok(!f.effectiveAlias, '(c) Primary/Developer без effectiveAlias');
  }
  // база F2 резолвит адрес F1
  const ctx5 = mkNoteCtx([
    { key: 'models.embedding_fallback1_base_url', value: 'https://fb1.example' },
  ]);
  const noteBase = ctx5.blockEffectiveNote(f2base);
  assert.ok(noteBase.indexOf('https://fb1.example') >= 0,
    '(c) адрес F2 резолвит адрес Запасной 1: ' + noteBase);
}

// ── (d) placeholder-подсказки наследования ───────────────────────────────────
{
  const ctx = { configItems: [] };
  ctx.blockFieldPlaceholder = methods.blockFieldPlaceholder.bind(ctx);
  assert.ok(ctx.blockFieldPlaceholder(f2model).indexOf('Запасной 1') >= 0,
    '(d) F2 placeholder честно говорит про наследование');
  assert.ok(ctx.blockFieldPlaceholder(f1model).indexOf('запасных') >= 0,
    '(d) F1 placeholder честно говорит про легаси-общее');
  const plain = sbMain.fields.find((f) => f.role === 'model');
  assert.strictEqual(ctx.blockFieldPlaceholder(plain), 'Модель',
    '(d) обычное поле — прежний placeholder (label)');
}

// ── (e) index.html: wiring в ОБОИХ subBlocks-шаблонах ────────────────────────
{
  const INDEX = fs.readFileSync(
    path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
  const noteCount = INDEX.split('data-effective-note').length - 1;
  assert.strictEqual(noteCount, 2,
    '(e) effective-подпись подключена в обоих subBlocks-шаблонах '
    + '(подключения + llm_providers)');
  const hintCount = INDEX.split('v-if="f.hint && !f.secret"').length - 1;
  assert.strictEqual(hintCount, 2,
    '(e) пояснение hint рендерится в обоих subBlocks-шаблонах');
  const guardCount =
    INDEX.split('v-if="sb.testable !== false"').length - 1;
  assert.strictEqual(guardCount, 2,
    '(e) guard testable скрывает «Проверить» у Developer-подблоков');
  assert.ok(INDEX.indexOf('Адрес и модель общие') < 0,
    '(e) старая пометка о зеркале убрана из шаблона');
  assert.ok(
    methods.blockEffectiveNote.toString().indexOf('effectiveAlias') >= 0,
    '(e) blockEffectiveNote живёт в app.js (не дублируется в шаблоне)');
}

console.log('EMBEDDING-PROFILES-UI-OK');
