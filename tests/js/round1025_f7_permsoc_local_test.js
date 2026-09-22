'use strict';
/* F7 (10.25, ADR-1025-20) — PERMsoc как локальное пространство чата.
 *
 * Реальные поведенческие проверки (загрузка web/app.js в stubbed-окружении):
 *   A. scope/guard — без чата блоков нет; PERMsoc-ключ не пишется в global;
 *   B. 6 блоков + partition «ключ ровно в одном блоке»; «Общее» не свалка;
 *   C. OFF блока сохраняет дочерние (одна мутация — только toggleKey);
 *   D. блок-гейты «Общие реакции»/«Расписания» + kill-switch read-only;
 *   E. единицы: kostik_reply_probability round-trip 0–1 ↔ 0–100 %.
 *
 * Запуск: node tests/js/round1025_f7_permsoc_local_test.js
 */
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
    const el = {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() {
        const idx = _bodyChildren.indexOf(el);
        if (idx >= 0) _bodyChildren.splice(idx, 1);
      },
    };
    return el;
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

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;

// ── Ожидаемое key-level владение (§62–§67, ADR-1025-20 D2) ─────────────────
const EXPECT = {
  slavik: [
    'reactions.slavik_user_id', 'reactions.dead_page_relay_channel_id',
    'reactions.dead_page_source_channel_id',
    'reactions.dead_page_source_channel_username', 'reactions.dead_page_dir',
    'reactions.slavic_random_dir', 'reactions.gif_path',
    'limits.slavik_mimic_cooldown', 'limits.slavik_mimic_min_words',
    'limits.gif_interval', 'limits.slavic_photo_interval',
    'limits.dead_page_cooldown', 'limits.dead_page_caption_max_chars',
    'limits.dead_page_max_forward_retries', 'reactions.slavic_photo_path'],
  kostik: ['reactions.kostik_user_id', 'reactions.kostik_replies',
           'limits.kostik_reply_probability'],
  olya: ['reactions.olya_user_id', 'reactions.olya_saveasbot_channel_ids',
         'reactions.olya_saveasbot_user_ids', 'reactions.olya_media_base',
         'reactions.olya_caption_text', 'reactions.olya_media_type',
         'flags.olya_caption_enabled', 'flags.olya_repost_enabled',
         'flags.olya_always_send', 'flags.olya_caption_mention_enabled',
         'limits.olya_cooldown'],
  mimic: ['reactions.mimic_victim_user_ids', 'reactions.alan_mimic_enabled',
          'reactions.kucha_enabled', 'flags.mimic_forwards_enabled',
          'limits.mimic_cooldown', 'limits.mimic_min_words'],
  reactions: ['reactions.alan_user_id', 'reactions.alan_username',
              'reactions.alan_greeting_dir', 'reactions.war_channel_ids',
              'reactions.war_channel_usernames', 'reactions.war_replies',
              'reactions.danger_words', 'reactions.vasya_enabled',
              'flags.alan_replies_enabled', 'flags.dead_page_post_on_join',
              'reactions.admin_user_id', 'reactions.common_media_base',
              'flags.common_media_enabled', 'flags.common_work_media_enabled'],
  schedule: ['reactions.goodmorning_time', 'reactions.goodmorning_media_dir',
             'reactions.goodmorning_target_chat_ids',
             'reactions.goodmorning_tz', 'limits.alan_reply_interval',
             'limits.alan_greeting_cooldown',
             'limits.alan_silence_greeting_hours', 'limits.danger_cooldown',
             'limits.selfdev_cooldown', 'limits.work_cooldown',
             'limits.common_cooldown'],
};

function blocksOf(isChat) {
  const ctx = {
    isChatContext: function () { return isChat; },
    groupedForTab: function () { return []; },
    _ownerDescription: methods._ownerDescription,
  };
  return methods._permsocOwnerGroups.call(ctx);
}

// ── A1. Без выбранного чата блоков НЕТ (§60) ───────────────────────────────
assert.deepStrictEqual(blocksOf(false), [],
  'A1: без чата PERMsoc-блоки не рендерятся');
assert.ok(blocksOf(true).length > 0, 'A1: с чатом блоки есть');

// ── B1. Ровно 6 блоков и мастер — отдельный уровень (нет блока common) ─────
const owners = blocksOf(true);
assert.strictEqual(owners.length, 6, 'B1: 6 функциональных блоков');
assert.deepStrictEqual(owners.map((o) => o.id).sort(),
  ['kostik', 'mimic', 'olya', 'reactions', 'schedule', 'slavik'],
  'B1: состав блоков');
assert.strictEqual(owners.filter((o) => o.id === 'common').length, 0,
  'B1: «Общее/Мастер» больше не блок (отдельный уровень §61)');

// ── B2. Partition: каждый ключ §62–§67 ровно в одном блоке ─────────────────
const seen = {};
owners.forEach((o) => {
  (o.owner.keys || []).forEach((k) => {
    assert.ok(!seen[k], 'B2: ключ дублирован: ' + k);
    seen[k] = o.id;
  });
});
Object.keys(EXPECT).forEach((id) => {
  EXPECT[id].forEach((k) => {
    assert.strictEqual(seen[k], id, 'B2: ключ ' + k + ' → блок ' + id);
  });
});
assert.strictEqual(Object.keys(seen).length, 60,
  'B2: покрытие всех ключей §62–§67');

// ── E1. deprecated slavic_photo_path видим (Славик/Дополнительно) ──────────
assert.strictEqual(seen['reactions.slavic_photo_path'], 'slavik',
  'E1: deprecated в блоке Славика');
assert.strictEqual(seen['reactions.kostik_replies'], 'kostik',
  'E1: фразы Костика построчно (widget=list, каталог)');

// ── E2. Единицы: kostik_reply_probability round-trip ──────────────────────
assert.strictEqual(methods.permsocProbToPercent(0), 0, 'E2: 0.0 → 0 %');
assert.strictEqual(methods.permsocProbToPercent(0.5), 50, 'E2: 0.5 → 50 %');
assert.strictEqual(methods.permsocProbToPercent(1), 100, 'E2: 1.0 → 100 %');
assert.strictEqual(methods.permsocPercentToProb('0'), 0, 'E2: 0 % → 0.0');
assert.strictEqual(methods.permsocPercentToProb('50'), 0.5, 'E2: 50 % → 0.5');
assert.strictEqual(methods.permsocPercentToProb('100'), 1, 'E2: 100 % → 1.0');
assert.strictEqual(methods.permsocProbToPercent(1.5), 100, 'E2: клип >1 → 100');
assert.strictEqual(methods.permsocPercentToProb('-5'), 0, 'E2: клип <0 % → 0');

// ── E3. saveKostikProbability конвертирует на границе ─────────────────────
(async function () {
  const item = { key: 'limits.kostik_reply_probability', value: 1.0 };
  const ctx = {
    permsocPercentToProb: methods.permsocPercentToProb,
    saveConfigItem: async function (it) { ctx.saved = it.value; },
  };
  await methods.saveKostikProbability.call(ctx, item, '30');
  assert.strictEqual(item.value, 0.3, 'E3: UI 30 % → сервер 0.3');
  assert.strictEqual(ctx.saved, 0.3, 'E3: сохранён серверный формат');

  // ── A2. persistItems: PERMsoc-ключ при scope=global не пишется ──────────
  let apiCalled = 0;
  const pctx = {
    activeChatId: null,
    saving: new Set(),
    _opSeq: 0,
    _scopeGuard: function () { return true; },
    _serializeValue: JSON.stringify,
    configChatUpdatedAt: 5,
    toast: function () {},
    notify: function () {},
    api: async function () { apiCalled++; return {}; },
  };
  const res = await methods.persistItems.call(pctx,
    [{ key: 'reactions.slavik_user_id', value: 42 }]);
  assert.strictEqual(apiCalled, 0,
    'A2: PERMsoc-ключ при scope=global → запроса НЕТ');
  assert.ok(res.failed.some((f) => f.key === 'reactions.slavik_user_id'
    && f.reason === 'permsoc-global'), 'A2: провал помечен явно');

  // ── A3. saveConfigItem: guard от global-записи ─────────────────────────
  let api2 = 0;
  let toasted = '';
  const sctx = {
    activeChatId: null,
    saving: new Set(),
    toast: function (m) { toasted = m; },
    api: async function () { api2++; return {}; },
  };
  const ok = await methods.saveConfigItem.call(sctx,
    { key: 'flags.slavik_enabled', type: 'bool', value: true });
  assert.strictEqual(ok, false, 'A3: global-запись PERMsoc → отказ');
  assert.strictEqual(api2, 0, 'A3: сетевого запроса нет');
  assert.ok(toasted.indexOf('PERMsoc') >= 0, 'A3: понятный текст');

  // ── C1. OFF блока пишет ТОЛЬКО toggleKey, дочерние не тронуты ──────────
  const slavikOwner = owners.filter((o) => o.id === 'slavik')[0].owner;
  const child = { key: 'reactions.slavik_user_id', value: 479167456 };
  const toggle = { key: 'flags.slavik_enabled', value: true };
  const savedItems = [];
  const tctx = {
    configItems: [toggle, child],
    canToggleOwner: function () { return true; },
    toggleGate: async function () { throw new Error('не должен вызываться'); },
    saveConfigItem: async function (it) { savedItems.push(it); },
  };
  await methods.toggleOwner.call(tctx, slavikOwner, false);
  assert.strictEqual(savedItems.length, 1, 'C1: ровно одна мутация');
  assert.strictEqual(savedItems[0].key, 'flags.slavik_enabled',
    'C1: записан только toggleKey');
  assert.strictEqual(toggle.value, false, 'C1: тумблер выключен');
  assert.strictEqual(child.value, 479167456,
    'C1: дочернее значение не сброшено (байт-в-байт)');

  // ── D1. Блок-гейт: тумблер пишет gates.permsoc_*, не config ────────────
  const reactOwner = owners.filter((o) => o.id === 'reactions')[0].owner;
  assert.strictEqual(reactOwner.gate, 'permsoc_reactions', 'D1: gate feature');
  const gateCalls = [];
  const gctx = {
    isGlobalAdmin: true,
    configItems: [],
    uiFlag: function () { return true; },
    canToggleOwner: methods.canToggleOwner,
    _canEditConfig: function () { return true; },
    toggleGate: async function (f, e) { gateCalls.push([f, e]); },
    saveConfigItem: async function () { throw new Error('config не трогаем'); },
  };
  await methods.toggleOwner.call(gctx, reactOwner, false);
  assert.deepStrictEqual(gateCalls, [['permsoc_reactions', false]],
    'D1: «Общие реакции» → per-chat gate');
  assert.strictEqual(methods.canToggleOwner.call(gctx, reactOwner), true,
    'D1: global admin может');

  // ── D2. Kill-switch OFF → новые блок-тумблеры честно read-only ─────────
  const ksCtx = {
    isGlobalAdmin: true,
    uiFlag: function () { return false; },
  };
  assert.strictEqual(methods.canToggleOwner.call(ksCtx, reactOwner), false,
    'D2: PERMSOC_BLOCK_GATES_ENABLED=OFF → read-only');

  // ── B3. Мастер — отдельный уровень (тумблер не в owner-блоках) ─────────
  assert.ok(methods.canToggleMaster, 'B3: canToggleMaster существует');
  assert.strictEqual(methods.canToggleMaster.call({ isGlobalAdmin: false }),
    false, 'B3: мастер read-only для не-global-admin');

  // ── H-F7-1. Витринные подгруппы §62/§64/§66/§67 рендерятся с заголовками ──
  function mkItem(key) {
    return { key: key, progressive_level: 'basic', type: 'str' };
  }
  function renderRows(id) {
    const owner = owners.filter((o) => o.id === id)[0].owner;
    const grp = { owner: owner, items: EXPECT[id].map(mkItem) };
    const ctx = {
      basicItems: methods.basicItems,
      itemAdvanced: methods.itemAdvanced,
      isAdminIdHidden: function () { return false; },
      permsocOwnerSubgroups: methods.permsocOwnerSubgroups,
    };
    return methods.permsocRenderItems.call(ctx, grp);
  }
  function headersOf(rows) {
    return rows.filter((r) => r.__subheader).map((r) => r.__subheader);
  }
  assert.deepStrictEqual(headersOf(renderRows('slavik')),
    ['Основное', 'Контент', 'Мимикрия', 'Ограничения', 'Дополнительно'],
    'H1: подгруппы Славика (§62)');
  assert.deepStrictEqual(headersOf(renderRows('olya')),
    ['Основное', 'Источники', 'Ответы', 'Ограничения'],
    'H1: подгруппы Оли (§64)');
  assert.deepStrictEqual(headersOf(renderRows('reactions')),
    ['Приветствия', 'Оповещения', 'Триггеры', 'Медиа'],
    'H1: подгруппы «Общих реакций» (§66)');
  assert.deepStrictEqual(headersOf(renderRows('schedule')),
    ['Рассылка', 'Медиа', 'Доп. ограничения'],
    'H1: подгруппы «Расписаний» (§67)');
  // `olya_saveasbot_channel_ids`/`user_ids` — сразу после шапки «Источники».
  const olyaRows = renderRows('olya');
  const srcIdx = olyaRows.findIndex((r) => r.__subheader === 'Источники');
  assert.strictEqual(olyaRows[srcIdx + 1].key,
    'reactions.olya_saveasbot_channel_ids', 'H1: ID-каналы в «Источники»');
  assert.strictEqual(olyaRows[srcIdx + 2].key,
    'reactions.olya_saveasbot_user_ids', 'H1: user-ID в «Источники»');
  // Каждый элемент — ровно один раз; подгруппы покрывают блок без потерь.
  ['slavik', 'kostik', 'olya', 'mimic', 'reactions', 'schedule'].forEach((id) => {
    const rows = renderRows(id);
    const its = rows.filter((r) => !r.__subheader);
    assert.strictEqual(its.length, EXPECT[id].length,
      'H1: ' + id + ' — все элементы отрендерены');
    const seen2 = {};
    its.forEach((r) => {
      assert.ok(!seen2[r.key], 'H1: дубль ' + r.key);
      seen2[r.key] = true;
    });
    const sgKeys = [];
    methods.permsocOwnerSubgroups(
      owners.filter((o) => o.id === id)[0].owner)
      .forEach((sg) => sg.keys.forEach((k) => sgKeys.push(k)));
    const blockKeys = owners.filter((o) => o.id === id)[0].owner.keys.slice().sort();
    assert.deepStrictEqual(sgKeys.slice().sort(), blockKeys,
      'H1: подгруппы ' + id + ' покрывают блок ровно');
  });

  // ── M-F7-2. Списки ID Оли → list-виджет (структурированно, §64) ─────────
  const norm = methods._normalizeConfigItems.call({}, [
    { key: 'reactions.olya_saveasbot_channel_ids', type: 'json',
      widget: '', value: [-100123] },
    { key: 'reactions.olya_saveasbot_user_ids', type: 'json',
      widget: '', value: '["42"]' },
    { key: 'reactions.kostik_replies', type: 'json', widget: 'list',
      value: ['a'] },
    { key: 'reactions.danger_words', type: 'json', widget: '', value: { a: 1 } },
  ]);
  assert.strictEqual(norm[0].widget, 'list', 'M2: каналы Оли → list');
  assert.strictEqual(norm[1].widget, 'list', 'M2: user-ID Оли → list');
  assert.strictEqual(norm[2].widget, 'list', 'M2: Костик list не сломан');
  assert.strictEqual(norm[3].widget, '', 'M2: прочие json — textarea');
  assert.strictEqual(typeof norm[3].value, 'string',
    'M2: прочие json строкифаятся (textarea)');
  assert.strictEqual(methods.listEditorProps(
    { key: 'reactions.olya_saveasbot_user_ids' }).variant, 'ids',
    'M2: список ID Оли → variant=ids');
  assert.deepStrictEqual(
    methods.listEditorProps({ key: 'reactions.kostik_replies' }), {},
    'M2: Костик — дефолтный variant (фразы)');

  // ── H-F7-7. Списки ID Оли сохраняются ЧИСЛАМИ (round-trip типа) ─────────
  // Регрессия M-F7-2: `list-editor.save` коэрцировал всё в String → сервер
  // (`origin.chat.id: int in [...]`) не находил ID → Оля-SaveAsBot молча
  // перестаёт определяться. Фикс: для PERMSOC_LIST_WIDGET_KEYS чисто-числовые
  // строки возвращаются как Number (целое), нечисловые — строкой.
  const listComp = (global.__components || {})['list-editor'];
  assert.ok(listComp && listComp.methods && listComp.methods.save,
    'H7: компонент list-editor зарегистрирован');
  const saveM = listComp.methods.save;
  const syncM = listComp.methods.sync;
  const toStored = listComp.methods.toStoredValue;
  const numericList = listComp.methods._numericList;
  assert.ok(typeof toStored === 'function', 'H7: toStoredValue есть');

  // 1) Полный round-trip: value=числа → sync (строки для полей) → save (числа).
  const rt = {
    item: { key: 'reactions.olya_saveasbot_channel_ids', type: 'json' },
    _nextRowId: 1,
    root: { saveConfigItem: async function (it) { rt.saved = it.value; } },
    toStoredValue: toStored,
    _numericList: numericList,
  };
  syncM.call(rt);                       // value пока нет → rows []
  rt.item.value = [-100123, 523131145];
  syncM.call(rt);
  assert.deepStrictEqual(rt.rows, ['-100123', '523131145'],
    'H7: sync отдаёт строки для отображения');
  await saveM.call(rt);
  assert.deepStrictEqual(rt.saved, [-100123, 523131145],
    'H7: на сервер уходят числа (не строки)');
  assert.strictEqual(typeof rt.saved[0], 'number', 'H7: channel id — number');
  assert.strictEqual(typeof rt.saved[1], 'number', 'H7: user id — number');
  assert.ok(rt.saved.includes(-100123),
    'H7: серверное `-100123 in list` === true');
  assert.ok(!rt.saved.includes('-100123'),
    'H7: строкового совпадения нет (иначе мимо)');

  // 2) Нечисловые элементы остаются строками; тримм и пустые — как раньше.
  const mixed = {
    item: { key: 'reactions.olya_saveasbot_user_ids', type: 'json' },
    rows: ['523131145', 'not-an-id', ' 42 ', ''],
    root: { saveConfigItem: async function (it) { mixed.saved = it.value; } },
    toStoredValue: toStored,
    _numericList: numericList,
  };
  await saveM.call(mixed);
  assert.deepStrictEqual(mixed.saved, [523131145, 'not-an-id', 42],
    'H7: смешанный список — числа/строки по типу, пустая отброшена');

  // 3) Фразы Костика (не ID-ключ) остаются строками — регресс исключён.
  const krep = {
    item: { key: 'reactions.kostik_replies', type: 'json' },
    rows: ['привет', '42'],
    root: { saveConfigItem: async function (it) { krep.saved = it.value; } },
    toStoredValue: toStored,
    _numericList: numericList,
  };
  await saveM.call(krep);
  assert.deepStrictEqual(krep.saved, ['привет', '42'],
    'H7: фразы Костика не коэрцятся в числа');
  assert.strictEqual(typeof krep.saved[1], 'string',
    'H7: Костик «42» остаётся строкой');

  console.log('F7-PERMSOC-LOCAL-UNIT-OK');
})();
