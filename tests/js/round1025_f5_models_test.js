'use strict';
/* F5 round1025 (ADR-1025-15 D4/§49) — «Модели и подключения».
 *
 * Проверяет РЕАЛЬНУЮ логику web/app.js:
 *   (a) 6 групп §49 покрывают КАЖДЫЙ блок-подключение ровно один раз
 *       (нет блока вне групп и нет дубля) — ни один провайдер не потерян;
 *   (b) advanced-блоки (guard/search_keys/media_share) остаются техническими;
 *   (c) workspace-модели модуля = его блоки в его группах;
 *   (d) «Проверить» reuse существующих эндпоинтов (spy /api/llm/test,
 *       /api/images/test); новых API нет;
 *   (e) §49 «не менять сохранённую модель при открытии формы»: форма только
 *       читает значение (blockFieldValue), 0 POST при открытии, значение не
 *       подменяется первым пунктом;
 *   (f) маска секрета в пробу не уходит (R17).
 *
 * Запуск: node tests/js/round1025_f5_models_test.js
 */
const path = require('path');
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
const data = captured.data();
const methods = captured.methods;
const computed = captured.computed;
const MODULES = data.modules;
const BLOCKS = data.providerBlocks;

function moduleById(id) {
  return MODULES.filter(function (m) { return m.id === id; })[0];
}
function groupedCtx() {
  const ctx = { providerBlocks: BLOCKS };
  ctx.providerConnectionBlocks = computed.providerConnectionBlocks.call(ctx);
  ctx.providerGrouped = computed.providerGrouped.call(ctx);
  return ctx;
}

(async function run() {
  const ctx = groupedCtx();
  const connIds = ctx.providerConnectionBlocks.map(function (b) { return b.id; });

  // ── (a) 6 групп, каждый блок-подключение ровно один раз ──────────────
  {
    const seen = {};
    let dup = 0;
    ctx.providerGrouped.forEach(function (g) {
      g.blocks.forEach(function (b) {
        if (seen[b.id]) dup += 1;
        seen[b.id] = true;
      });
    });
    assert.strictEqual(dup, 0, 'a: ни одного дубля блока');
    const missing = connIds.filter(function (id) { return !seen[id]; });
    assert.deepStrictEqual(missing, [], 'a: нет блока вне групп');
    assert.deepStrictEqual(Object.keys(seen).sort(), connIds.slice().sort(),
      'a: объединение групп == все блоки-подключения');
    // Ровно 6 тематических групп §49 + (возможно) technical для остатка.
    const thematic = ctx.providerGrouped.filter(function (g) {
      return g.id !== 'technical';
    });
    assert.strictEqual(thematic.length, 6, 'a: 6 групп §49');
    assert.deepStrictEqual(thematic.map(function (g) { return g.title; }),
      ['Генерация текста', 'Распознавание речи', 'Видео', 'Эмбеддинги',
       'Фоновые задачи', 'Генерация изображений'],
      'a: порядок/названия групп §49');
  }

  // ── (b) advanced-блоки НЕ в группах подключений ───────────────────────
  {
    const all = {};
    ctx.providerGrouped.forEach(function (g) {
      g.blocks.forEach(function (b) { all[b.id] = true; });
    });
    ['llm_guard', 'search_keys', 'media_share'].forEach(function (id) {
      assert.ok(!all[id], 'b: advanced ' + id + ' вне групп §49');
    });
    const adv = computed.providerAdvancedBlocks.call({ providerBlocks: BLOCKS });
    assert.deepStrictEqual(adv.map(function (b) { return b.id; }),
      ['llm_guard', 'search_keys', 'media_share'],
      'b: advanced-блоки сохранены («Расширенные системные»)');
  }

  // ── (c) workspace-модели модуля ───────────────────────────────────────
  {
    const mctx = Object.assign(groupedCtx(), {
      workspaceModule: moduleById('mod_images'),
    });
    const wg = computed.workspaceModelGroups.call(mctx);
    assert.strictEqual(wg.length, 1, 'c: у mod_images одна группа моделей');
    assert.strictEqual(wg[0].id, 'prov_images', 'c: группа изображений');
    assert.deepStrictEqual(wg[0].blocks.map(function (b) { return b.id; }),
      ['image_generation'], 'c: блок генерации изображений');
    const mf = Object.assign(groupedCtx(), {
      workspaceModule: moduleById('mod_transcribe'),
    });
    assert.deepStrictEqual(
      computed.workspaceModelGroups.call(mf)[0].blocks.map(function (b) { return b.id; }),
      ['transcription'], 'c: транскрибация');
  }

  // ── (d) «Проверить» reuse существующих эндпоинтов (spy) ───────────────
  {
    const calls = [];
    const spy = {
      blockTesting: {}, blockResults: {}, blockDrafts: {},
      configItems: [],
      blockFieldValue: methods.blockFieldValue,
      toast() {},
      api: async function (url, opts) {
        calls.push({ url: url, body: JSON.parse(opts.body) });
        return { ok: true, http_status: 200, latency_ms: 3 };
      },
    };
    const imageBlock = BLOCKS.filter(function (b) { return b.id === 'image_generation'; })[0];
    await methods.testBlock.call(spy, imageBlock);
    assert.strictEqual(calls[0].url, '/api/images/test',
      'd: изображения → /api/images/test (reuse)');
    const directBlock = BLOCKS.filter(function (b) { return b.id === 'direct'; })[0];
    await methods.testBlock.call(spy, directBlock.subBlocks[0]);
    assert.strictEqual(calls[1].url, '/api/llm/test',
      'd: текст → /api/llm/test (reuse); новых API нет');
  }

  // ── (e) §49 «сохранённая модель не подменяется» + 0 POST ──────────────
  {
    const posts = [];
    const form = {
      blockDrafts: {}, blockSaving: {}, blockTesting: {}, blockResults: {},
      configItems: [
        { key: 'models.llm_model_name', type: 'str', value: 'saved-model-XYZ' },
        { key: 'models.llm_base_url', type: 'str', value: 'https://saved/v1' },
      ],
      configChatUpdatedAt: null,
      blockFieldValue: methods.blockFieldValue,
      blockFieldBool: methods.blockFieldBool,
      blockFieldPlaceholder: methods.blockFieldPlaceholder,
      blockFieldConfigured: methods.blockFieldConfigured,
      canEditConfig() { return true; },
      toast() {},
      loadConfig() {},
      api: async function () { throw new Error('открытие формы не должно писать'); },
    };
    const block = {
      id: 'direct_main', title: 'Основная модель',
      fields: [
        { key: 'models.llm_base_url', role: 'base_url' },
        { key: 'models.llm_model_name', role: 'model' },
      ],
    };
    // Открытие формы: только чтение значений (v-model), ни одной записи.
    assert.strictEqual(
      methods.blockFieldValue.call(form, block.fields[1]), 'saved-model-XYZ',
      'e: сохранённая модель прочитана как есть (не первый пункт списка)');
    assert.strictEqual(
      methods.blockFieldValue.call(form, block.fields[0]), 'https://saved/v1',
      'e: адрес тоже сохранённый');
    assert.strictEqual(posts.length, 0, 'e: 0 POST при открытии формы');
    // сохранённое значение НЕ подменяется первым пунктом (нет записи в item).
    assert.strictEqual(form.configItems[0].value, 'saved-model-XYZ',
      'e: configItems не мутирован');
    // Повторное «открытие» (повторное чтение) — значение неизменно.
    assert.strictEqual(
      methods.blockFieldValue.call(form, block.fields[1]), 'saved-model-XYZ',
      'e: повторное открытие не мутирует значение');
  }

  // ── (f) R17: маска секрета не уходит в пробу ──────────────────────────
  {
    const calls = [];
    const spy = {
      blockTesting: {}, blockResults: {}, blockDrafts: {},
      configItems: [
        { key: 'keys.llm_api_key', type: 'str',
          value: { configured: true, last4: 'abcd' } },
      ],
      blockFieldValue: methods.blockFieldValue,
      toast() {},
      api: async function (url, opts) {
        calls.push(JSON.parse(opts.body));
        return { ok: true, http_status: 200, latency_ms: 1 };
      },
    };
    const b = { id: 'direct_main', fields: [
      { key: 'keys.llm_api_key', role: 'api_key', secret: true }] };
    await methods.testBlock.call(spy, b);
    assert.strictEqual(calls[0].api_key, '',
      'f: сохранённый секрет не уходит с фронта (бэкенд резолвит ключ)');
  }

  // ── (g) §49/T-2714: карточка подключения (все поля, без секретов) ─────
  {
    const fromSaved = {
      blockDrafts: {}, blockResults: {}, blockTesting: {},
      configItems: [
        { key: 'models.llm_display_name', type: 'str', value: 'Saved Direct' },
        { key: 'models.llm_model_name', type: 'str', value: 'saved-model-XYZ' },
        { key: 'models.llm_fallback_model', type: 'str', value: 'fallback-model-ABC' },
        { key: 'models.llm_base_url', type: 'str', value: 'https://saved/v1' },
        { key: 'keys.llm_api_key', type: 'str',
          value: { configured: true, last4: 'a7F2' } },
      ],
      blockFieldValue: methods.blockFieldValue,
      blockDisplayName: methods.blockDisplayName,
    };
    const read = [];
    const cardCtx = Object.assign({}, fromSaved, {
      blockFieldValue: function (f) {
        read.push(f.key);
        return methods.blockFieldValue.call(this, f);
      },
    });
    const block = BLOCKS.filter(function (b) { return b.id === 'direct'; })[0];
    const card = methods.connectionCard.call(cardCtx, block);
    // Название / назначение / основная / резервная модель / статус.
    assert.strictEqual(card.title, 'Прямые ответы', 'g: название карточки');
    assert.ok(card.purpose, 'g: назначение заполнено (из существующей структуры)');
    assert.strictEqual(card.primary, 'saved-model-XYZ',
      'g: основная модель — сохранённое значение (без подстановки дефолта)');
    assert.strictEqual(card.fallback, 'fallback-model-ABC',
      'g: резервная модель — из существующего subBlock (Ф11)');
    assert.ok(card.hasFallback, 'g: фолбэк-подключение распознано');
    assert.strictEqual(card.status.text, 'Не проверено', 'g: честный статус до пробы');
    assert.strictEqual(card.testTarget.id, 'direct_main',
      'g: «Проверить» — основное подключение (reuse testBlock)');
    assert.strictEqual(card.canTest, true, 'g: «Проверить» доступна');
    // Ключи как ЗНАЧЕНИЯ не выводятся (F9/§46): секретные поля не читаются,
    // в значениях карточки нет ни маски, ни last4.
    const secretsRead = read.filter(function (k) { return k.indexOf('keys.') === 0; });
    assert.deepStrictEqual(secretsRead, [],
      'g: секреты карточкой не читаются (ключи — только раздел секретов)');
    assert.ok(read.indexOf('models.llm_model_name') >= 0,
      'g: читается именно сохранённая модель');
    const vals = [card.title, card.purpose, card.primary, card.fallback,
                  card.status.text].join('|');
    assert.ok(vals.indexOf('a7F2') < 0, 'g: last4 секрета не в значениях карточки');
    assert.ok(vals.indexOf('configured') < 0, 'g: объект секрета не в карточке');
    // Статус обновляется результатом существующей пробы.
    cardCtx.blockResults = { direct_main: { ok: true, text: 'OK 200 · 5 мс' } };
    assert.strictEqual(
      methods.connectionCard.call(cardCtx, block).status.ok, true,
      'g: статус обновляется по результату пробы');
    // Блок без subBlocks (изображения): нет резервной модели, но карточка есть.
    const imgCtx = Object.assign({}, fromSaved);
    const img = BLOCKS.filter(function (b) { return b.id === 'image_generation'; })[0];
    const imgCard = methods.connectionCard.call(imgCtx, img);
    assert.strictEqual(imgCard.hasFallback, false, 'g: у изображений нет фолбэка');
    assert.strictEqual(imgCard.primary, '', 'g: пустая модель → честно пусто');
    assert.strictEqual(imgCard.testTarget.id, 'image_generation', 'g: тест самого блока');
  }

  // ── (h) T-2714: «Настроить» — раскрытие формы, БЕЗ записи (§49) ────────
  {
    let wrote = 0;
    const ui = {
      connectionSettingsOpen: {},
      api: async function () { wrote += 1; throw new Error('не должно писать'); },
    };
    const block = BLOCKS.filter(function (b) { return b.id === 'direct'; })[0];
    assert.strictEqual(ui.connectionSettingsOpen[block.id], undefined,
      'h: форма закрыта до «Настроить»');
    methods.toggleConnectionSettings.call(ui, block);
    assert.strictEqual(ui.connectionSettingsOpen[block.id], true,
      'h: «Настроить» раскрывает существующую форму');
    methods.toggleConnectionSettings.call(ui, block);
    assert.strictEqual(ui.connectionSettingsOpen[block.id], false,
      'h: повторный клик сворачивает');
    assert.strictEqual(wrote, 0, 'h: раскрытие формы не пишет (0 POST)');
  }

  // ── (i) T-2714: «Проверить» карточки → существующий `testBlock` ────────
  {
    const targets = [];
    const ui = {
      connectionCard: function () { return { testTarget: { id: 'direct_main' } }; },
      testBlock: async function (t) { targets.push(t.id); },
    };
    const block = BLOCKS.filter(function (b) { return b.id === 'direct'; })[0];
    await methods.testConnection.call(ui, block);
    assert.deepStrictEqual(targets, ['direct_main'],
      'i: «Проверить» делегирует в testBlock (reuse существующего эндпоинта)');
  }

  console.log('MODELS-GROUPS-OK');
  process.exit(0);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
