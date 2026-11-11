'use strict';
/* P0IM-OV-HONEST (2026-11-12) — две честности обзора инициативы.
 *
 * 1. Строка «последнее действие» шапки обзора. На проде 2.58.192 она печатала
 *    «Последних действий в журнале нет» при 327 строках журнала у того же чата:
 *    ветка `v-else` зависела от `moduleLastEventLine`, который для
 *    `mod_initiative` возвращал '' (у `moduleHealthView` нет оси инициативы).
 *    Контракт: журнал НЕ пуст → называется реальный факт; состояние неизвестно →
 *    НИКАКОГО утверждения об отсутствии действий.
 *
 * 2. Подпись времени в карточках механизмов. Тест закрепляет, какое ПОЛЕ кормит
 *    какую подпись: «Последняя попытка» ← `last_attempt.at`,
 *    «Последняя проверка» ← `last_check_ts`, `readiness.next_eligible_at` —
 *    только «Дальше». Сдвиг любого из полей в чужую подпись валит тест.
 *
 * Запуск: node tests/js/p0im_ov_honesty_test.js → P0IM-OV-HONESTY-OK
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
             setAttribute() {}, focus() {}, select() {}, remove() {},
             click() {}, appendChild() {} };
  },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = {
  _s: {},
  getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.localStorage = global.sessionStorage;
global.history = { replaceState() {}, pushState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };
global.Blob = function () {};
global.URL = { createObjectURL() { return 'blob:x'; }, revokeObjectURL() {} };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');

// Реальные значения из среза прода 2.58.191 (см. release-258192/deploy.md §6):
// попытка текста 16:27:40Z, попытка мемов 16:28:16Z, граница текста 16:41:54Z,
// проверка прохода 16:42:07Z, попытка мемов позже — 16:42:00Z.
const CHAT = -1004482340693;
const TS_TEXT_ATTEMPT = 1794414460;   // 2026-11-11T16:27:40Z
const TS_MEME_ATTEMPT = 1794414496;   // 2026-11-11T16:28:16Z
const TS_TEXT_NEXT = 1794415314;      // 2026-11-11T16:41:54Z
const TS_CHECK = 1794415327;          // 2026-11-11T16:42:07Z
const TS_MEME_ATTEMPT_LATER = 1794415320; // 2026-11-11T16:42:00Z
const FALSE_EMPTY = 'Последних действий в журнале нет';

function diagPayload(opts) {
  const o = opts || {};
  const payload = {
    chat_id: CHAT,
    generated_at: 1794415330,
    text_initiative: {
      mechanism: 'text_initiative',
      available: o.textAvailable !== false,
      configuration: { enabled: true, source: 'chat' },
      health: { state: 'ok', dependencies: [] },
      readiness: {
        state: 'waiting', reason: 'eval_not_due', reason_class: 'schedule',
        next_eligible_at: TS_TEXT_NEXT, next_basis: 'eval_interval',
      },
      last_attempt: {
        at: TS_TEXT_ATTEMPT, mode: 'auto', outcome: 'skipped',
        stop_stage: 'lease_held',
        run_id: 'init:-1004482340693:20261111:9926b6d84a',
      },
      last_delivery: { status: 'never' },
      last_check_ts: TS_CHECK,
    },
    meme: {
      mechanism: 'meme',
      available: true,
      configuration: { enabled: true, source: 'chat' },
      health: { state: 'ok', dependencies: [] },
      readiness: {
        state: 'waiting', reason: 'daily_quota_reached', reason_class: 'quota',
        next_eligible_at: 1794438000, next_basis: 'quota_next_reset',
      },
      last_attempt: {
        at: o.memeAttemptAt || TS_MEME_ATTEMPT,
        mode: 'auto', outcome: 'skipped', stop_stage: 'gates',
        run_id: 'meme:-1004482340693:2026-11-11:8fae1f157347',
      },
      last_delivery: {
        status: 'confirmed', at: 1794412512, destination: CHAT,
        message_id: 10472,
      },
      last_check_ts: TS_CHECK,
    },
  };
  if (o.noAttempts) {
    payload.text_initiative.last_attempt = {};
    payload.meme.last_attempt = {};
    payload.text_initiative.available = false;
    payload.meme.available = false;
  }
  if (o.memeNoAttempt) payload.meme.last_attempt = {};
  return payload;
}

// Контекст «как на странице»: снимок диагностики строится тем же computed, что
// и в бою (`memeDiagView`), а не подставляется готовым объектом осей.
function viewCtx(payload) {
  const ctx = {
    memeDiag: payload,
    activeChatId: CHAT,
    iniOverviewTimezone: '',
    moduleScopeErrorFor: function () { return ''; },
    moduleHealthView: function () { return null; },
    fmtLogTs: function (ts) { return 'fmt:' + ts; },
  };
  ctx.memeDiagView = computed.memeDiagView.call(ctx);
  ctx.moduleLastEventState = methods.moduleLastEventState;
  ctx.moduleLastEventLine = methods.moduleLastEventLine;
  ctx.initiativeLastActionFact = methods.initiativeLastActionFact;
  return ctx;
}

// ─── 1. Пустое состояние: журнал не пуст → никакого «нет действий» ──────────
(function emptyStateSuite() {
  // (а) В журнале ЕСТЬ строки (попытка мемов 16:42 позже попытки текста 16:27):
  //     строка называет реальный факт и никогда — отсутствие действий.
  const rows = viewCtx(diagPayload({ memeAttemptAt: TS_MEME_ATTEMPT_LATER }));
  const line = methods.moduleLastEventLine.call(rows, { id: 'mod_initiative' });
  assert.ok(line.indexOf('16:42') >= 0,
    'при живых строках журнала строка не назвала реальное действие: ' + line);
  assert.ok(line.indexOf('Мемы') >= 0,
    'строка не назвала механизм новейшей попытки: ' + line);
  assert.strictEqual(line.indexOf(FALSE_EMPTY), -1,
    'строка утверждает пустоту журнала при существующих строках: ' + line);
  assert.strictEqual(line.indexOf('нет данных'), -1,
    'известный факт показан как «нет данных»: ' + line);
  const state = methods.moduleLastEventState.call(rows, { id: 'mod_initiative' });
  assert.strictEqual(state.kind, 'event', 'вид состояния: ' + state.kind);

  // (а2) Механизм НЕДОСТУПЕН (`available:false`), но попытка записана, а у
  //      второго механизма попытки нет: карточка рядом показывает эту же
  //      попытку, поэтому шапка обязана назвать действие, а не «нет данных».
  //      Недоступность ≠ пустой журнал.
  const unavailable = viewCtx(diagPayload({
    textAvailable: false, memeNoAttempt: true,
  }));
  const unavailableLine = methods.moduleLastEventLine.call(unavailable,
    { id: 'mod_initiative' });
  assert.ok(unavailableLine.indexOf('16:27') >= 0,
    'недоступный механизм с записанной попыткой не назвал действие: '
    + unavailableLine);
  assert.ok(unavailableLine.indexOf('Текстовая инициатива') >= 0,
    'назван не тот механизм: ' + unavailableLine);
  assert.strictEqual(unavailableLine.indexOf('нет данных'), -1,
    'записанная попытка спрятана за «нет данных»: ' + unavailableLine);
  // Та же попытка в карточке того же ответа — поверхности не расходятся.
  const unavailableCard = computed.initiativeTextCard.call({
    iniViewMode: 'self',
    memeDiagView: unavailable.memeDiagView,
    iniOverviewTimezone: '',
    canEditConfig: function () { return true; },
    memeSettingsView: null,
    accessChats: [],
    activeChatId: CHAT,
  });
  assert.ok(unavailableCard.attemptText.indexOf('11.11 16:27 UTC') === 0,
    'карточка потеряла попытку недоступного механизма: '
    + unavailableCard.attemptText);

  // (а3) Попыток нет НИ У ОДНОГО механизма → честное «нет данных»:
  //      времени не выдумываем и не подменяем границей срока.
  const noAttempts = viewCtx(diagPayload({ noAttempts: true }));
  const noAttemptsLine = methods.moduleLastEventLine.call(noAttempts,
    { id: 'mod_initiative' });
  assert.strictEqual(noAttemptsLine, 'нет данных',
    'при отсутствии попыток названо что-то ещё: ' + noAttemptsLine);

  // (б) Источник молчит (снимка диагностики нет) → честное «неизвестно»:
  //     ни «нет действий», ни пустая строка.
  const unknown = viewCtx(null);
  const unknownLine = methods.moduleLastEventLine.call(unknown,
    { id: 'mod_initiative' });
  assert.strictEqual(unknownLine, 'нет данных',
    'неизвестное состояние не названо честно: ' + unknownLine);
  assert.strictEqual(
    methods.moduleLastEventState.call(unknown, { id: 'mod_initiative' }).kind,
    'unknown', 'молчание источника выдано за факт');
  assert.ok(unknownLine.length > 0, 'неизвестное состояние не оставило строки');

  // (в) Модуль без health-оси (нет журнала у клиента) — тоже «нет данных»,
  //     а не «действий не было».
  const plain = viewCtx(null);
  const plainLine = methods.moduleLastEventLine.call(plain, { id: 'mod_memes' });
  assert.strictEqual(plainLine, 'нет данных', plainLine);

  // (г) Подтверждённое наблюдение health по-прежнему называется (не сломано).
  const observed = viewCtx(null);
  observed.moduleHealthView = function () {
    return { observedAt: TS_CHECK, label: 'исправно', reason: '' };
  };
  const observedLine = methods.moduleLastEventLine.call(observed,
    { id: 'mod_sleep' });
  assert.strictEqual(observedLine,
    'Последнее подтверждённое наблюдение: fmt:' + TS_CHECK, observedLine);

  // (д) Шаблон: ложной ветки пустоты нет ни на одной поверхности, и обе
  //     поверхности печатают ОДНУ строку состояния.
  assert.strictEqual(INDEX.indexOf(FALSE_EMPTY), -1,
    'в шаблоне осталась ложная строка «нет действий»');
  const anchors = INDEX.match(/data-module-last-action/g) || [];
  assert.strictEqual(anchors.length, 2,
    'ожидались ровно 2 поверхности строки последнего действия: '
    + anchors.length);
})();

// ─── 2. Поле → подпись: попытка ≠ проверка ≠ граница срока ─────────────────
(function fieldLabelSuite() {
  const ctx = viewCtx(diagPayload());
  assert(ctx.memeDiagView, 'снимок диагностики не собран (chat_id)');
  const cardCtx = {
    iniViewMode: 'self',
    memeDiagView: ctx.memeDiagView,
    iniOverviewTimezone: '',
    canEditConfig: function () { return true; },
    memeSettingsView: null,
    accessChats: [],
    activeChatId: CHAT,
  };
  const textCard = computed.initiativeTextCard.call(cardCtx);
  const memeCard = computed.initiativeMemeCard.call(cardCtx);

  // (а) «Последняя попытка» ← last_attempt.at (два механизма по отдельности).
  assert.ok(textCard.attemptText.indexOf('11.11 16:27 UTC') === 0,
    'подпись попытки текста не из last_attempt.at: ' + textCard.attemptText);
  assert.ok(memeCard.attemptText.indexOf('11.11 16:28 UTC') === 0,
    'подпись попытки мемов не из last_attempt.at: ' + memeCard.attemptText);

  // (б) «Последняя проверка» ← last_check_ts (не попытка и не граница).
  assert.strictEqual(textCard.checkText, '11.11 16:42 UTC',
    'подпись проверки не из last_check_ts: ' + textCard.checkText);
  assert.ok(textCard.checkText.indexOf('16:27') === -1,
    'в «проверку» попало время попытки: ' + textCard.checkText);

  // (в) next_eligible_at живёт ТОЛЬКО в «Дальше» и не протекает в попытку.
  assert.ok(textCard.nextText.indexOf('11.11 16:41 UTC') >= 0,
    'граница срока не попала в «Дальше»: ' + textCard.nextText);
  assert.strictEqual(textCard.attemptText.indexOf('16:41'), -1,
    'граница срока выдана за попытку: ' + textCard.attemptText);
  assert.strictEqual(textCard.attemptText.indexOf('16:42'), -1,
    'время проверки выдано за попытку: ' + textCard.attemptText);
})();

console.log('P0IM-OV-HONESTY-OK');
