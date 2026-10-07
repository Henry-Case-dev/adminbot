'use strict';
/* P0 round1028 — таксономия секретов в группе keys_random (MiniApp).
 *
 * Покрытие:
 *   (a) index.html: три ветки рендера секрет-поля — строго `item.secret`
 *       (категория keys ≠ секрет); guard/панель «Проверить подключение»
 *       (data-random-check) и точка входа «Случайность» (data-random-entry)
 *       на месте;
 *   (b) dirtyItems включает изменённое НЕ-секретное поле категории keys;
 *       dirtyKeyItems — только настоящие секреты (spec.secret);
 *   (c) blockFieldValue/blockFieldPlaceholder: не-секретное поле группы
 *       keys_random показывает сохранённое значение/обычную подсказку;
 *   (d) isKeyConfigured не врёт: маска configured:false → false;
 *   (e) saveModalEdits: не-секретное поле → обычный POST /api/config
 *       (saveConfigItem/persistItems), секретный draft → saveKeyItem.
 *
 * Запуск: node tests/js/round1028_anu_taxonomy_p0_test.js → ANU-TAXONOMY-OK
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
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
const ROOT = path.join(__dirname, '..', '..');
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    return { tagName: tag, className: '', value: '', style: {},
             setAttribute() {}, focus() {}, select() {}, remove() {} };
  },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;

const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

// ── (a) Статика: ветки рендера строго по item.secret ────────────────────────
(function () {
  assert(!INDEX.includes("item.category === 'keys' || item.secret"),
    'условие `category === keys || secret` должно исчезнуть из index.html');
  assert(!/v-else-if="item\.category === 'keys'"/.test(INDEX),
    'не должно остаться веток рендера по категории целиком');
  // Группа keys_random рендерится (зеркало TABS) и панель проверки жива.
  assert(INDEX.includes("item.key === 'keys.random_quantum_api_key'"),
    'guard панели «Проверить подключение» должен остаться');
  assert(INDEX.includes('data-random-check'), 'панель проверки на месте');
  assert(INDEX.includes('data-random-entry'),
    'точка входа «Случайность» (карточка сна) на месте');
  assert(INDEX.includes('id="secret-field-tpl"'),
    'шаблон secret-field на месте');
  // app.js: category-keys гейтов секрет-логики больше нет.
  assert(!APP_JS.includes("it.category === 'keys'"),
    "в app.js не должно остаться гейтов `it.category === 'keys'`");
})();

// ── Общий стаб контекста конфиг-модалки ──────────────────────────────────────
function makeCtx(items, drafts) {
  return {
    configItems: items,
    keyDrafts: drafts || {},
    configSnapshot: {},
    canEditConfig() { return true; },
    saving: new Set(),
    stickySaving: false,
    stickyFailed: [], stickyFailedKeys: [], stickyConflict: [],
    toasts: [],
    toast(m, k) { this.toasts.push([m, k]); },
    _serializeValue: methods._serializeValue,
    _snapshotConfig: methods._snapshotConfig,
    cancelModalEdits: methods.cancelModalEdits,
  };
}

const NON_SECRET_ANU = { key: 'keys.random_quantum_endpoint',
  category: 'keys', secret: false, per_chat: false,
  title: 'Источник случайности: адрес ANU', type: 'str',
  value: 'https://api.quantumnumbers.anu.edu.au' };
const SECRET_ANU = { key: 'keys.random_quantum_api_key',
  category: 'keys', secret: true, per_chat: false,
  title: 'Источник случайности: ключ ANU', type: 'str',
  value: { configured: false, last4: null } };

// ── (b) dirty-дифференциация по it.secret ────────────────────────────────────
(function () {
  const ctx = makeCtx([
    { key: 'models.llm_model_name', secret: false, value: 'old' },
    JSON.parse(JSON.stringify(NON_SECRET_ANU)),
    JSON.parse(JSON.stringify(SECRET_ANU)),
  ]);
  methods._snapshotConfig.call(ctx);
  // Не-секретное поле категории keys изменено → обычный dirty.
  ctx.configItems[1].value = 'https://example.invalid';
  assert.strictEqual(computed.dirtyItems.call(ctx).length, 1,
    'P0: изменённое не-секретное поле keys_random → dirtyItems');
  assert.strictEqual(computed.dirtyItems.call(ctx)[0].key,
    'keys.random_quantum_endpoint');
  assert.strictEqual(computed.dirtyKeyItems.call(ctx).length, 0,
    'P0: не-секретное поле НЕ попадает в secret-write-трек');
  // Секрет с реальным draft → dirtyKeyItems, но НЕ dirtyItems.
  ctx.keyDrafts['keys.random_quantum_api_key'] = 'abcd1234';
  // В реальном Vue computed резолвится через `this`; в стабе подставляем
  // явно (паттерн round1020_ui_test.js).
  ctx.dirtyItems = computed.dirtyItems.call(ctx);
  ctx.dirtyKeyItems = computed.dirtyKeyItems.call(ctx);
  assert.strictEqual(computed.dirtyKeyItems.call(ctx).length, 1,
    'P0: секрет с черновиком → dirtyKeyItems');
  assert.strictEqual(computed.dirtyKeyItems.call(ctx)[0].key,
    'keys.random_quantum_api_key');
  assert.strictEqual(computed.dirtyItems.call(ctx).length, 1,
    'P0: секрет не попадает в dirtyItems');
  assert.strictEqual(computed.stickyDirtyCount.call(ctx), 2,
    'P0: sticky-счётчик видит оба трека');
  // Маска в черновике секрета — не изменение (R31-гард сохранён).
  ctx.keyDrafts['keys.random_quantum_api_key'] = '\u2022'.repeat(12);
  assert.strictEqual(computed.dirtyKeyItems.call(ctx).length, 0,
    'P0: маска — не изменение');
  // Дефолтное (не изменённое) не-секретное поле — чисто.
  ctx.configItems[1].value = 'https://api.quantumnumbers.anu.edu.au';
  assert.strictEqual(computed.dirtyItems.call(ctx).length, 0,
    'P0: baseline не-секретного поля чист');
})();

// ── (c) blockFieldValue/blockFieldPlaceholder ────────────────────────────────
(function () {
  const ctx = {
    configItems: [JSON.parse(JSON.stringify(NON_SECRET_ANU)),
                  JSON.parse(JSON.stringify(SECRET_ANU))],
    blockDrafts: {},
  };
  // Не-секретное поле возвращает сохранённое значение (не forcibly '').
  assert.strictEqual(
    methods.blockFieldValue.call(ctx, { key: 'keys.random_quantum_endpoint' }),
    'https://api.quantumnumbers.anu.edu.au',
    'P0: не-секретное поле keys_random показывает сохранённое значение');
  assert.strictEqual(
    methods.blockFieldPlaceholder.call(
      ctx, { key: 'keys.random_quantum_endpoint', label: 'Адрес ANU' }),
    'Адрес ANU', 'P0: обычная подсказка для не-секретного поля');
  // Секрет — значение input всегда пустое, подсказка «заменить/ввести».
  assert.strictEqual(
    methods.blockFieldValue.call(ctx, { key: 'keys.random_quantum_api_key' }),
    '', 'P0: секрет без черновика → пустой input');
  assert.strictEqual(
    methods.blockFieldPlaceholder.call(
      ctx, { key: 'keys.random_quantum_api_key', label: 'Ключ' }),
    'Ключ…', 'P0: подсказка секрета — «Ключ…» (не настроен)');
  const configuredCtx = {
    configItems: [Object.assign({}, SECRET_ANU,
      { value: { configured: true, last4: '1234' } })],
    blockDrafts: {},
  };
  assert.strictEqual(
    methods.blockFieldPlaceholder.call(
      configuredCtx, { key: 'keys.random_quantum_api_key', label: 'Ключ' }),
    'Новый ключ (заменить)…', 'P0: подсказка секрета — «заменить»');
})();

// ── (d) isKeyConfigured не врёт для секрета до сохранения ────────────────────
(function () {
  assert.strictEqual(methods.isKeyConfigured(
    { value: { configured: false, last4: null } }), false,
    'P0: configured=false до сохранения ключа — честное состояние');
  assert.strictEqual(methods.isKeyConfigured(
    { value: { configured: true, last4: '1234' } }), true);
  assert.strictEqual(methods.isKeyConfigured({ value: null }), false);
  assert.strictEqual(methods.isKeyConfigured({ value: '' }), false);
  // last4 строкой не раскрываем.
  assert.strictEqual(methods.last4({ value: { configured: true,
    last4: '1234' } }), '1234');
  assert.strictEqual(methods.last4({ value: 'abcd1234' }), '',
    'P0/R17: сырое значение секретом-строкой не раскрывается');
})();

// ── (e) saveModalEdits: маршрутизация треков сохранения ──────────────────────
(async function () {
  const savedPlain = [];
  const savedKeys = [];
  const ctx = makeCtx([
    JSON.parse(JSON.stringify(NON_SECRET_ANU)),
    JSON.parse(JSON.stringify(SECRET_ANU)),
  ]);
  methods._snapshotConfig.call(ctx);
  ctx.configItems[0].value = 'https://example.invalid';
  ctx.keyDrafts['keys.random_quantum_api_key'] = 'abcd1234';
  ctx.dirtyItems = computed.dirtyItems.call(ctx);
  ctx.dirtyKeyItems = computed.dirtyKeyItems.call(ctx);
  ctx.saveConfigItem = async function (it) { savedPlain.push(it.key); return true; };
  ctx.saveKeyItem = async function (it) { savedKeys.push(it.key); return true; };
  await methods.saveModalEdits.call(ctx);
  assert.deepStrictEqual(savedPlain, ['keys.random_quantum_endpoint'],
    'P0: не-секретное поле сохраняется обычным POST-треком');
  assert.deepStrictEqual(savedKeys, ['keys.random_quantum_api_key'],
    'P0: секрет сохраняется через keyDrafts/saveKeyItem');
  assert.strictEqual(ctx.stickyFailed.length, 0, 'P0: без провалов');
  console.log('ANU-TAXONOMY-OK');
})().catch(function (e) {
  console.error(e && e.stack || e);
  process.exit(1);
});
