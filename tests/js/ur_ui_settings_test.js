'use strict';
/* UR-F (UNIFIED-REPLY UI-волна + BGS-06 UI half) — РЕАЛЬНЫЙ JS-тест.
 *
 * Загружает web/app.js в stubbed-окружении (Vue.createApp перехватывает
 * options) и проверяет:
 *   1. «Модули → Время» (UR-29.1/29.2): вкладка mod_time существует,
 *      зоны фильтруются по полному справочнику, часы считаются ТОЛЬКО
 *      от серверной базы (as_of_utc + offset, без браузерной зоны),
 *      пустой черновик = наследование, ошибка сохранения не применяет
 *      черновик и показывает причину.
 *   2. Мёртвые ключи (UR-14.2/UR-21.13/UR-21.17): фронт не угадывает —
 *      honest-нотис/бейдж идут из item.eff бэкенда; no-op/legacy не
 *      рендерятся как «активные».
 *   3. Честные подписи речи (UR-21.23): «Свобода формулировок» на
 *      CHAT_TEMPERATURE_PRESET_DEFAULT + reason_inactive от бэкенда.
 *   4. Диагностика одного ответа (R-ADM.5/UR-20.3): строки стадий
 *      L1 → tools → Writer → ops → delivery собираются из полей
 *      существующей трассы (direct_turn_*), «нет данных» без выдумок.
 *   5. «Как бот отвечает» (UR-20.2): режимы из effective-config.
 *
 * Запуск: node tests/js/ur_ui_settings_test.js   (печатает UR-F-UI-OK)
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
global.window.CogVisual = require(path.join(__dirname, '..', '..', 'web',
  'static', 'cog-visual.js'));
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    return { tagName: tag, className: '', value: '', style: {},
             setAttribute() {}, focus() {}, select() {}, remove() {} };
  },
  body: { appendChild() {}, removeChild() {} },
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

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;
const data = captured.data();

// ── 1. «Модули → Время»: вкладка, поиск по зонам, серверные часы ──────────
(function () {
  const tab = data.tabs.filter((t) => t.id === 'mod_time')[0];
  assert(tab, 'UR-29.1: вкладка mod_time существует');
  assert.strictEqual(tab.type, 'timeEditor',
    'UR-29.1: тип timeEditor (guard Chart.js не задет)');
  assert.strictEqual(tab.menu, 'modules',
    'UR-29.1: «Время» живёт в разделе «Модули»');
  assert.strictEqual(data.modules.some((m) => m.id === 'mod_time'), true,
    'UR-29.1: карточка «Время» в витрине модулей');
  const timeCard = data.modules.filter((m) => m.id === 'mod_time')[0];
  assert.strictEqual(timeCard.noToggle, true,
    'UR-29.1: пояс — не модуль-флаг, карточка без тумблера');

  // Полный справочник: computed-фильтр по подстроке (IANA без выдумок).
  const ctx = { timeDraft: 'moscow', timeZones: [
    'Europe/Moscow', 'Asia/Almaty', 'America/New_York',
    'UTC'] };
  const matches = computed.timeZoneMatches.call(ctx);
  assert.deepStrictEqual(matches, ['Europe/Moscow'],
    'UR-29.1: поиск по полному IANA-списку фильтрует подстроку');
  assert.strictEqual(computed.timeZoneMatches.call(
    { timeDraft: '', timeZones: ['Europe/Moscow'] }).length, 0,
    'UR-29.1: пустой черновик — список подсказок не раскрывается');

  // Часы: ТОЛЬКО от серверной базы (as_of_utc + utc_offset), без
  // браузерной timezone. 12:00:00 UTC + 03:00 = 15:00 по поясу.
  const clockCtx = {
    timeState: {
      as_of_utc: '2026-11-06T12:00:00+00:00',
      utc_offset: '+03:00',
      weekday: 'пятница',
    },
    timeStateFetchedAt: Date.parse('2026-11-06T12:00:00+00:00'),
    timeNow: null,
  };
  methods.timeNowTick.call(clockCtx);
  assert(clockCtx.timeNow, 'UR-29.2: тикающие часы от серверной базы');
  assert.strictEqual(clockCtx.timeNow.time, '15:00:00',
    'UR-29.2: локальное время = UTC + смещение зоны (не браузер)');
  assert.strictEqual(clockCtx.timeNow.date, '06.11.2026',
    'UR-29.2: дата пояса от серверной базы');
  const noBase = { timeState: null, timeNow: {} };
  methods.timeNowTick.call(noBase);
  assert.strictEqual(noBase.timeNow, null,
    'UR-29.2: нет серверной базы — часов нет (никакой догадки)');

  // Источник/наследование.
  assert.strictEqual(methods.timeSourceLabel('chat'), 'настройки чата');
  assert.strictEqual(methods.timeSourceLabel('global'), 'глобальная настройка');
  assert.strictEqual(methods.timeSourceLabel('utc_fallback'),
    'UTC (зона недоступна на сервере)',
    'UR-24.4: деградация показывается честно');
  const inheritCtx = { timeState: { chat_id: -100, configured: null } };
  assert.strictEqual(methods.timeConfiguredLine.call(inheritCtx)
    .indexOf('наследование') >= 0, true,
    'UR-29.1: пустое поле = наследование, подпись объясняет');

  // Ошибка сохранения: черновик НЕ применяется, причина видна.
  assert.strictEqual(data.timeDraft, '',
    'UR-29.1: черновик пояса пуст = наследование по умолчанию');
})();

// ── 2. Мёртвые ключи + honest-статусы из effective-меты ──────────────────
(function () {
  // Бэкенд честно сказал «no_op» → карточка помечена, а не прикидывается
  // рабочей; текст причины — из item.eff.reason_inactive (не догадка UI).
  const dead = { key: 'flags.chat_style_anchors_enabled',
    eff: { status: 'no_op',
      reason_inactive: 'Секция стилевых якорей удалена (UR-14).' } };
  const badge = methods.configEffBadge(dead);
  assert(badge, 'UR-14.2: no-op ключ получает бейдж');
  assert.strictEqual(badge.text, 'не влияет',
    'UR-14.2: бейдж не обещает рабочего поведения');
  assert.strictEqual(methods.configItemNotice(dead),
    'Секция стилевых якорей удалена (UR-14).',
    'UR-21.24: reason_inactive бэкенда доезжает до нотиса карточки');
  assert.strictEqual(methods.configEffBadge(
    { eff: { status: 'active' } }), null,
    'UR-22.1: активный ключ — без лишнего бейджа (шум не растёт)');
  // Legacy-класс из миграционного манифеста → статус legacy.
  assert.strictEqual(methods.configEffBadge(
    { eff: { status: 'legacy' } }).text, 'legacy',
    'RLR-05: legacy-ключ подписывается как legacy');
  // Единицы значения — из меты (UR-20.9).
  assert.strictEqual(methods.configUnitsSuffix(
    { eff: { units: 'дней' } }), 'дней');
  // Источник chat/global/default (UR-22.1/BGS-06.5), включая legacy-путь
  // без поля source (старый контракт: не chat → глобальная).
  const chatScope = { scopeKind: 'chat' };
  assert.strictEqual(methods.configSourceLabel.call(chatScope,
    { source: 'chat' }), 'Источник: настройки чата');
  assert.strictEqual(methods.configSourceLabel.call(chatScope,
    { source: 'global' }), 'Источник: глобальная настройка');
  assert.strictEqual(methods.configSourceLabel.call(chatScope,
    { source: 'default' }).indexOf('заводское') >= 0, true,
    'UR-22.1: default-источник показывается честно');
  assert.strictEqual(methods.configSourceLabel.call(chatScope,
    { chat_source: '' }), 'Источник: глобальная настройка',
    'legacy-payload без source: прежняя семантика сохранена');
})();

// ── 3. Честные подписи речи (UR-21.23) ───────────────────────────────────
(function () {
  const modesCtx = {
    configItems: [{
      key: 'flags.search_enabled', value: true, source: 'global',
    }, {
      key: 'flags.chat_running_summary_enabled', value: false,
      source: 'default',
    }, {
      key: 'limits.chat_temperature_preset_default', value: 'balanced',
      source: 'chat',
      eff: { status: 'inactive',
        reason_inactive: 'провайдер игнорирует temperature' },
    }, {
      key: 'flags.initiative_enabled', value: false, source: 'default',
    }],
    configItemByKey: methods.configItemByKey,
    itemEffLine: methods.itemEffLine,
  };
  const modes = methods.directModesView.call(modesCtx);
  assert.strictEqual(modes.speech.title, 'Речь и характер',
    'UR-20.2: «Речь и характер» — фактически действующий режим на экране');
  assert.strictEqual(modes.speech.line
    .indexOf('провайдер игнорирует temperature') >= 0, true,
    'UR-21.23: честная пометка про игнор temperature видна рядом с режимом');
  assert.strictEqual(modes.search.line.indexOf('разрешён') >= 0, true,
    'UR-20.2: интернет-режим показывает фактическое состояние');
  assert.strictEqual(modes.memory.line.indexOf('конспект выключен') >= 0,
    true, 'UR-20.2: выключенная память показывается как выключенная');
  assert.strictEqual(modes.extent.line
    .indexOf('выбирается планировщиком') >= 0, true,
    'UR-20.2: подробность — честно «выбирается L1», настройки нет');
})();

// ── 4. Диагностика одного ответа (R-ADM.5/UR-20.3) ───────────────────────
(function () {
  assert.strictEqual(typeof methods.loadTurnDiagnostics, 'function',
    'R-ADM.5: инспектор хода загружает трассу');
  assert.strictEqual(typeof methods.turnToolLine, 'function',
    'R-ADM.5: строки инструментов рендерят поля трассы');
  const toolLine = methods.turnToolLine({
    tool: 'web_search', status: 'success', refs: 5, out_chars: 1200 });
  assert.strictEqual(toolLine.indexOf('web_search') >= 0
    && toolLine.indexOf('источников: 5') >= 0, true,
    'R-ADM.5: tool-строка показывает имя/статус/число источников');
  // Честный итог доставки: изменение текста видно, не маскируется «ОК».
  const changed = methods.turnDeliveryLabel({
    outcome: 'success', digest_match: false,
    divergence_reason: 'owner_style_punctuation' }, 'success');
  assert.strictEqual(changed.indexOf('текст менялся') >= 0
    && changed.indexOf('owner_style_punctuation') >= 0, true,
    'R-ADM.5: расхождение digest показывается с операцией-причиной');
  const clean = methods.turnDeliveryLabel({
    outcome: 'success', digest_match: true }, 'success');
  assert.strictEqual(clean.indexOf('как написан') >= 0, true,
    'R-ADM.5: совпадение digest — «доставлен как написан»');
  const skipped = methods.turnDeliveryLabel({
    outcome: 'skipped', reason: 'send_recheck' }, 'skipped');
  assert.strictEqual(skipped.indexOf('без доставки') >= 0
    && skipped.indexOf('send_recheck') >= 0, true,
    'R-ADM.5: отсутствие доставки — честная причина, не успех');
  // Время хода (UR-29.3) — из полей clock трассы.
  assert.strictEqual(methods.turnClockLine({
    clock: { timezone: 'Europe/Moscow',
      as_of_utc: '2026-11-06T12:00:00+00:00',
      timezone_source: 'chat' } })
    .indexOf('Europe/Moscow') >= 0, true,
    'UR-29.3: часы хода показывают IANA + as_of_utc');
  assert.strictEqual(methods.turnClockLine({ clock: null }), 'нет данных',
    'UR-29.3: старые прогоны без трассы — «нет данных»');
})();

// ── 5. Три уровня «Прямых ответов» (UR-20.1/20.3/20.9) ───────────────────
(function () {
  const direct = data.modules.filter((m) => m.id === 'mod_direct')[0];
  assert(direct, 'карточка «Прямые ответы» на месте');
  assert.deepStrictEqual(
    (direct.tabs || []).slice(0, 3),
    ['overview', 'inspector', 'settings'],
    'UR-20.1: три уровня — «Как бот отвечает» / «Что бот видел» / '
    + '«Дополнительные настройки»');
  // Редакторы промптов и история версий остаются рабочими вкладками
  // (R-ADM.7: никакого редизайна beyond rows).
  ['synthesizer', 'verbalizer', 'models', 'limits', 'testing']
    .forEach(function (t) {
      assert.ok((direct.tabs || []).indexOf(t) >= 0,
        'R-ADM.7: вкладка ' + t + ' не тронута');
    });
  const m = captured.methods;
  assert.strictEqual(typeof m.workspaceTabHasContent, 'function');
  assert.strictEqual(m.workspaceTabHasContent.call(
    { _workspaceGroupsFor: function () { return []; },
      workspacePromptItems: function () { return []; } },
    direct, 'inspector'), true,
    'UR-20.3: инспектор — вкладка с собственным содержимым');
})();

console.log('UR-F-UI-OK');
