'use strict';
/* P1 «Инициатива» (2026-11-03) — контракт рекомпоновки страницы
 * «Модули → Инициатива» на реальном `web/app.js` + `web/index.html`.
 *
 * Проверяется то, что нельзя увидеть на одном скриншоте:
 *   1. Пять смысловых вкладок и СТАРЫЕ адреса (`settings`/`limits`) как
 *      псевдонимы — закладки не ломаются, параметры на месте.
 *   2. Группы каталога (`flags_intent`/`limits_intent`) рендерятся на вкладке
 *      «Текстовая инициатива», покрытие вкладки (workspaceCoverage) не теряет
 *      ни одной группы.
 *   3. «Обзор» собирает состояние механизма ИЗ ЕГО ГЕЙТА (ready/skip), а не из
 *      одного мастер-флага: выключенный механизм = «выключена/выключены».
 *   4. «Публикации»: строки журнала декорируются без подмены исхода,
 *      доставка различает true/false/null, режим показывает ручной /meme.
 *   5. «Диагностика»: группы трассы одной попытки (включая события), итог
 *      «генерация успешна, отправка отменена» выводится из цепочки этапов.
 *   6. Один save: карточка мемов по-прежнему читает и пишет только
 *      существующие `/api/initiative/meme-settings` (+ diagnostics), второго
 *      save-эндпоинта нет.
 *
 * Запуск: node tests/js/initiative_ui_rework_test.js → INITIATIVE-UI-OK
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
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');

// ── 1. Вкладки и псевдонимы старых адресов ───────────────────────────────
(function () {
  assert.ok(/mod_initiative: \['overview', 'text', 'memes', 'publications',\n\s+'diagnostics'\]/
    .test(APP_JS), 'пять вкладок страницы «Инициатива» не объявлены');
  const mods = captured.data ? captured.data() : {};
  assert.ok(mods, 'data() недоступен');
  // Псевдонимы: старый адрес ведёт в «Текстовую инициативу», а не на «Обзор».
  const wsCtx = {
    workspaceModule: {
      id: 'mod_initiative',
      tabs: ['overview', 'text', 'memes', 'publications', 'diagnostics'],
    },
    route: '#/modules/initiative/settings',
    moduleBySlug: null,
  };
  const ws = computed.workspace.call(wsCtx);
  assert.ok(ws, 'workspace не построен для старого адреса');
  assert.strictEqual(ws.tab, 'text',
    'старый адрес settings обязан открывать «Текстовую инициативу»');
  wsCtx.route = '#/modules/initiative/limits';
  assert.strictEqual(computed.workspace.call(wsCtx).tab, 'text',
    'старый адрес limits обязан открывать «Текстовую инициативу»');
})();

// ── 2. Раскладка групп каталога по вкладкам ──────────────────────────────
(function () {
  const ini = { id: 'mod_initiative', tab: 'mod_initiative',
                tabs: ['overview', 'text', 'memes', 'publications',
                       'diagnostics'] };
  ['flags_intent', 'limits_intent'].forEach(function (gid) {
    assert.strictEqual(
      methods.workspaceGroupTab.call({}, ini, { id: gid, category: 'flags' }),
      'text', 'группа ' + gid + ' не на вкладке «Текстовая инициатива»');
  });
  // Другие модули не задеты.
  assert.strictEqual(
    methods.workspaceGroupTab.call({}, { id: 'mod_sleep' },
                                   { id: 'limits_memory', category: 'limits' }),
    'limits', 'раскладка чужих модулей изменилась');
  // Покрытие вкладки: ни одна группа не потеряна.
  const cov = computed.workspaceCoverage.call({
    workspaceModule: ini,
    tabs: [{ id: 'mod_initiative',
             sources: [{ category: 'flags', groups: ['flags_intent'] },
                       { category: 'limits', groups: ['limits_intent'] }] }],
    _syntheticGroup: function () { return null; },
    _workspaceGroupsFor: function () {
      return [{ id: 'flags_intent', items: [{}] },
              { id: 'limits_intent', items: [{}] }];
    },
  });
  assert.deepStrictEqual(cov.missing, [],
    'инвариант покрытия вкладки «Инициатива» нарушен');
})();

// ── 3. «Обзор»: пять независимых осей (P0-INIT-MEME-UX-DIAG §1/§5) ───────
// Карточка читает оси, посчитанные сервером. Проверяются ровно те случаи, где
// прежняя витрина лгала: кулдаун/мало сообщений как «выключено», 0 вместо
// «неизвестно», «доставка неизвестна» как «не доставлял», готовность как
// обещание публикации.
const NOW_TS = 1792200300;
const CHAT = -100123;
const TZ = 'Europe/Moscow';

function axesPayload(textOver, memeOver) {
  function block(mechanism, over) {
    return Object.assign({
      mechanism: mechanism,
      output_kind: mechanism,
      source: 'stub',
      available: true,
      data_state: 'ok',
      no_data_reasons: [],
      ready: true,
      ready_reason: '',
      last_check_ts: NOW_TS - 120,
      next_check_ts: null,
      next_check_basis: 'unknown',
      random: null,
      conditions: null,
      stages: null,
      skip: null,
      skip_recorded: null,
      cooldown: { own_seconds: 21600, remaining_seconds: 0,
                  basis: 'last_initiative_publication',
                  basis_ts: NOW_TS - 7200, scope: 'mechanism_own' },
      quota: { available: true, limit: 3, used: 1, remaining: 2,
               limit_reached: false, unlimited: false, next_reset: '' },
      publication: null,
      blocking: null,
      configuration: { enabled: true, source: 'chat', scope: 'chat',
                       reason: '' },
      health: { state: 'ok',
                dependencies: [{ name: 'event_log', state: 'ok',
                                 source: 'stub' }] },
      readiness: { state: 'ready', reason: '', reason_class: '',
                   next_eligible_at: null, next_basis: 'none' },
      last_attempt: { at: NOW_TS - 120, mode: 'auto', run_id: 'run-1',
                      outcome: 'published', stop_stage: 'publish',
                      incomplete_historical: false },
      last_delivery: { status: 'confirmed', at: NOW_TS - 120,
                       destination: CHAT, message_id: 777, run_id: 'run-1' },
    }, over || {});
  }
  return {
    schema_version: 1,
    generated_at: NOW_TS,
    chat_id: CHAT,
    text_initiative: block('text_initiative', textOver),
    meme: block('meme', memeOver),
    degraded: [],
  };
}

function axesCard(kind, payload, extra) {
  const ctx = Object.assign({
    memeDiag: payload,
    activeChatId: CHAT,
    iniOverviewTimezone: TZ,
  }, extra || {});
  const view = computed.memeDiagView.call(ctx);
  const cardCtx = Object.assign({}, ctx, {
    memeDiagView: view,
    canEditConfig: function () { return true; },
    memeSettingsView: { memeEnabled: true, initiativeEnabled: true,
                        quotaText: 'Генерации сегодня: 1 / 3',
                        remainingText: 'осталось 2', resetAt: '' },
  });
  const fn = kind === 'text' ? computed.initiativeTextCard
    : computed.initiativeMemeCard;
  return fn.call(cardCtx);
}

// 3.1 Кулдаун: «Разрешено: ВКЛ» + ожидание, НЕ «выключено».
(function () {
  const card = axesCard('meme', axesPayload({}, {
    ready: false,
    skip: { code: 'cooldown_active', label: 'кулдаун', origin: 'cooldown' },
    cooldown: { own_seconds: 21600, remaining_seconds: 3600,
                basis: 'last_provider_call', basis_ts: NOW_TS - 18000,
                scope: 'mechanism_own' },
    readiness: { state: 'waiting', reason: 'cooldown_active',
                 reason_class: 'cooldown',
                 next_eligible_at: NOW_TS + 3600, next_basis: 'cooldown' },
  }));
  assert.strictEqual(card.configEnabled, true,
    'кулдаун превратил разрешённый механизм в «выключено»');
  assert.strictEqual(card.configBadge, 'ВКЛ');
  assert.strictEqual(card.configState, 'true');
  assert.ok(card.configText.indexOf('включено') === 0,
    'источник разрешения не назван: ' + card.configText);
  assert.ok(card.configText.indexOf('настройка этого чата') > 0,
    'эффективный источник не назван по-русски: ' + card.configText);
  assert.strictEqual(card.readinessState, 'waiting');
  assert.ok(card.nowText.indexOf('кулдаун') > 0,
    'причина ожидания не названа: ' + card.nowText);
  assert.ok(card.nowText.indexOf('осталось 1 ч') > 0,
    'остаток кулдауна не из серверного факта: ' + card.nowText);
  assert.ok(card.nextText.indexOf('не раньше') === 0,
    'доказанное время не показано: ' + card.nextText);
  assert.ok(card.nextText.indexOf('по собственному кулдауну') > 0,
    'основание времени не названо: ' + card.nextText);
  // Ни одно поле карточки не выдаёт «выключено» при cooldown.
  assert.strictEqual(JSON.stringify(card).indexOf('ВЫКЛ'), -1,
    'кулдаун отрисован как ВЫКЛ: ' + JSON.stringify(card));
})();

// 3.2 Мало сообщений: тоже ожидание, а не «выключено»; ready=false само по
// себе НЕ даёт «выключено».
(function () {
  const text = axesCard('text', axesPayload({
    ready: false,
    skip: { code: 'not_enough_messages', label: 'мало сообщений',
            origin: 'gate' },
    readiness: { state: 'waiting', reason: 'not_enough_messages',
                 reason_class: 'not_enough_messages',
                 next_eligible_at: null, next_basis: 'unknown' },
  }, {}));
  assert.strictEqual(text.configBadge, 'ВКЛ');
  assert.ok(text.nowText.indexOf('мало сообщений') > 0, text.nowText);
  assert.ok(text.nextText.indexOf('точное время не назначено') === 0,
    'выдуманное время прохода показано как факт: ' + text.nextText);
  assert.strictEqual(text.nextAt, null);
})();

// 3.3 Истёкший маркер приоритета / брони не превращается в ожидание.
(function () {
  const card = axesCard('meme', axesPayload({}, {
    publication: { available: true, coordination: 'ok', degraded: false,
                   conflict: false, conflict_state: 'none', ok: true,
                   reason: '', reason_label: '', detail: '', state: 'released',
                   holder_kind: 'meme', claimed_by: '', other_kind: '',
                   other_age_seconds: null, interval_seconds: 900,
                   manual_priority_until: NOW_TS - 600,
                   manual_priority_active: false,
                   manual_priority_expired: true,
                   claim_expires_at: NOW_TS - 900, checked_at: NOW_TS },
    readiness: { state: 'ready', reason: '', reason_class: '',
                 next_eligible_at: null, next_basis: 'none' },
  }));
  assert.strictEqual(card.readinessState, 'ready',
    'истёкший маркер превратил готовность в блок');
  assert.ok(card.nowText.indexOf('приоритет') < 0,
    'истёкший приоритет показан как действующий: ' + card.nowText);
  assert.ok(card.nowText.indexOf('публикация уже идёт') < 0,
    'истёкшая бронь показана как текущая публикация: ' + card.nowText);
})();

// 3.4 «Доставка неизвестна» ≠ «ещё не доставлял»; id не подменяется нулём.
(function () {
  const unknown = axesCard('meme', axesPayload({}, {
    last_delivery: { status: 'unknown', at: NOW_TS - 60, destination: CHAT,
                     message_id: null, run_id: 'run-9' },
  }));
  const never = axesCard('meme', axesPayload({}, {
    last_delivery: { status: 'never', at: null, destination: null,
                     message_id: null, run_id: '' },
  }));
  assert.strictEqual(unknown.deliveryStatus, 'unknown');
  assert.strictEqual(unknown.deliveryBadge, 'доставка неизвестна');
  assert.strictEqual(never.deliveryStatus, 'never');
  assert.strictEqual(never.deliveryBadge, 'ещё не доставлял');
  assert.notStrictEqual(unknown.deliveryText, never.deliveryText,
    'неизвестная доставка схлопнута в «ещё не доставлял»');
  assert.strictEqual(unknown.deliveryMessageId, '');
  assert.strictEqual(unknown.deliveryText.indexOf(' сообщение 0'), -1,
    'неизвестный id напечатан нулём: ' + unknown.deliveryText);
  const confirmed = axesCard('meme', axesPayload({}, {}));
  assert.strictEqual(confirmed.deliveryStatus, 'confirmed');
  assert.ok(confirmed.deliveryText.indexOf('сообщение 777') > 0,
    'id подтверждённого сообщения не показан: ' + confirmed.deliveryText);
  assert.ok(confirmed.deliveryText.indexOf(String(CHAT)) > 0,
    'адресат подтверждённой отправки не показан: ' + confirmed.deliveryText);
})();

// 3.5 Неизвестный код деградирует в читаемый «код: …», а не в голый токен.
(function () {
  const card = axesCard('meme', axesPayload({}, {
    configuration: { enabled: true, source: 'mystery_layer', scope: 'chat',
                     reason: '' },
    readiness: { state: 'waiting', reason: 'brand_new_gate',
                 reason_class: 'brand_new_class',
                 next_eligible_at: null, next_basis: 'unknown' },
    last_attempt: { at: NOW_TS - 60, mode: 'weird', run_id: 'r', outcome: '',
                    stop_stage: 'unheard_stage', incomplete_historical: false },
  }));
  assert.ok(card.configText.indexOf('код: mystery_layer') > 0,
    'незнакомый слой источника выведен голым токеном: ' + card.configText);
  assert.ok(card.nowText.indexOf('код: brand_new_class') > 0,
    'незнакомый класс причины выведен голым токеном: ' + card.nowText);
  assert.ok(card.nowCodeText.indexOf('код: brand_new_gate') === 0,
    'незнакомый код причины не подписан: ' + card.nowCodeText);
  assert.ok(card.attemptText.indexOf('код: weird') > 0,
    'незнакомый способ попытки выведен голым токеном: ' + card.attemptText);
  assert.ok(card.attemptText.indexOf('код: unheard_stage') > 0,
    'незнакомый этап выведен голым токеном: ' + card.attemptText);
})();

// 3.6 Нечитаемая настройка = «неизвестно», а не ВЫКЛ. Нет попыток — нет нулей.
(function () {
  const card = axesCard('text', axesPayload({
    configuration: { enabled: null, source: 'read_failed', scope: 'global',
                     reason: 'read_failed' },
    readiness: { state: 'unknown', reason: 'read_failed',
                 reason_class: 'unknown',
                 next_eligible_at: null, next_basis: 'unknown' },
    last_attempt: { at: null, mode: 'unknown', run_id: '', outcome: '',
                    stop_stage: '', incomplete_historical: true },
    last_delivery: { status: 'never', at: null, destination: null,
                     message_id: null, run_id: '' },
    quota: { available: false, limit: null, used: null, remaining: null,
             limit_reached: false, unlimited: false, next_reset: '' },
    available: false, data_state: 'no_data',
    no_data_reasons: ['read_failed'],
  }, {}));
  assert.strictEqual(card.configEnabled, null);
  assert.strictEqual(card.configBadge, 'НЕИЗВЕСТНО');
  assert.ok(card.configText.indexOf('неизвестно') === 0, card.configText);
  assert.strictEqual(JSON.stringify(card).indexOf('ВЫКЛ'), -1,
    'нечитаемая настройка отрисована как ВЫКЛ');
  assert.strictEqual(card.attemptText, 'попыток ещё не было');
  assert.strictEqual(card.deliveryBadge, 'ещё не доставлял');
  assert.strictEqual(card.nextAt, null);
  assert.ok(card.quotaText.indexOf('неизвест') >= 0,
    'неизвестная квота выдана числом: ' + card.quotaText);
})();

// 3.7 Цифры квоты и времени берутся только из серверных полей.
(function () {
  const card = axesCard('text', axesPayload({
    quota: { available: true, limit: 0, used: null, remaining: null,
             limit_reached: false, unlimited: true, next_reset: '' },
  }, {}));
  assert.strictEqual(card.quotaText, 'без предела (0 = без капа)',
    'текстовая квота 0 = без лимита не отделена от «нет данных»: '
    + card.quotaText);
})();

// ── 4. «Публикации»: строки и доставка ───────────────────────────────────
(function () {
  const view = computed.iniPubRows.call({
    iniPub: { rows: [
      { attempt_id: 'meme:1', kind: 'meme', ts: 1800000000, stage: 'publish',
        outcome: 'published', reason_code: 'sent', reason_label: 'отправлено',
        delivered: true, message_id: 4321, mode: 'manual' },
      { attempt_id: 'meme:2', kind: 'meme', ts: 1799999999, stage: 'publish',
        outcome: 'skipped', reason_code: 'publication_stale',
        reason_label: '', delivered: false, mode: 'auto' },
      { attempt_id: 'text:3', kind: 'text_initiative', ts: 1799999998,
        stage: 'send', outcome: 'delivery_unknown', reason_code: '',
        reason_label: '', delivered: null, mode: 'auto' },
      { attempt_id: 'text:4', kind: 'text_initiative', ts: 1799999997,
        stage: 'decision', outcome: 'silent', reason_code: '',
        reason_label: '', delivered: null, mode: 'auto' },
    ] },
  });
  assert.strictEqual(view.length, 4);
  // Блокер 5: три РАЗНЫХ состояния доставки, ни одного схлопывания.
  assert.strictEqual(view[0].deliveryLabel, 'доставлено · сообщение 4321');
  assert.strictEqual(view[0].deliveryState, 'confirmed');
  assert.strictEqual(view[1].deliveryLabel,
    'отправки не было: бот решил не публиковать');
  assert.strictEqual(view[1].deliveryState, 'never');
  assert.strictEqual(view[2].deliveryLabel, 'доставка неизвестна');
  assert.strictEqual(view[2].deliveryState, 'unknown');
  assert.strictEqual(view[3].deliveryLabel,
    'отправки не было: бот решил не публиковать');
  assert.strictEqual(view[3].deliveryState, 'never');
  assert.notStrictEqual(view[2].deliveryLabel, view[3].deliveryLabel,
    '«доставка неизвестна» и «отправки не было» схлопнуты');
  assert.strictEqual(view[0].modeLabel, 'ручной /meme');
  assert.ok(view[1].reasonText.indexOf('устаревшая') >= 0,
    'код причины без текста не превращается в человеческий: '
    + view[1].reasonText);
  assert.strictEqual(view[0].outcomeOk, true);
  // Ни одного голого машинного слова в исходе строки.
  assert.strictEqual(view[3].outcomeLabel, 'бот решил промолчать');
  assert.strictEqual(view[2].outcomeLabel, 'доставка неизвестна');
  // `0` — не id сообщения.
  const zero = computed.iniPubRows.call({
    iniPub: { rows: [
      { attempt_id: 'meme:9', kind: 'meme', ts: 1800000099, stage: 'publish',
        outcome: 'published', reason_code: '', reason_label: '',
        delivered: true, message_id: 0, mode: 'auto' },
    ] },
  });
  assert.strictEqual(zero[0].deliveryLabel, 'доставлено',
    'нулевой id напечатан как сообщение: ' + zero[0].deliveryLabel);
})();

// ── 5. «Диагностика»: группы и итог «генерация/отправка» ─────────────────
(function () {
  const speech = {
    composer: 'on', core: 'r21', expression: 'e1', humor: 'h1',
    manifest: 'm1', system_sha12: 'sha', humor_status: 'rendered',
    technique: 'literalism',
    layers: [{ layer: 'core', revision: 'r21', chars: 10, rendered: true,
               skip: '' }],
  };
  const chain = [
    { stage: 'summary', ts: 1, outcome: 'passed', reason_code: '',
      facts: { chars: 41 } },
    { stage: 'joke', ts: 2, outcome: 'passed', reason_code: '',
      facts: { limit: 395, template_chars: 5, chars: 6, speech: speech } },
    { stage: 'image_generation', ts: 3, outcome: 'passed', reason_code: '',
      facts: { chars: 23, joke_chars: 6 } },
    { stage: 'publish', ts: 4, outcome: 'skipped',
      reason_code: 'publication_stale', facts: { publish: {} } },
  ];
  const groups = computed.iniTraceGroups.call({
    iniTrace: {
      attempt: { attempt_id: 'meme:1', kind: 'meme', stage: 'publish',
                 outcome: 'skipped', delivered: false, message_id: null },
      chain: chain, events: [],
    },
  });
  const keys = groups.map(function (g) { return g.key; });
  ['conditions', 'random', 'context', 'stages', 'speech', 'send', 'events']
    .forEach(function (k) {
      assert.ok(keys.indexOf(k) >= 0, 'нет группы ' + k + ': ' + keys.join(','));
    });
  assert.strictEqual(keys.length, new Set(keys).size,
    'группы трассы дублируются');
  const speechGroup = groups.filter(function (g) { return g.key === 'speech'; })[0];
  assert.ok(speechGroup.manifest === 'm1', 'манифест сборки не передан');
  assert.ok(speechGroup.rows.length === 1
    && speechGroup.rows[0].value.indexOf('вошёл') >= 0,
    'слой не помечен как вошедший');
  const stages = groups.filter(function (g) { return g.key === 'stages'; })[0];
  assert.ok(stages.rows.some(function (r) {
    return r.value.indexOf('бюджет прикола 395') >= 0;
  }), 'факты этапов потерялись в трассе');
  // Итог детали: генерация прошла, отправка отменена.
  const summary = computed.iniPubDetailSummary.call({
    iniPubDetail: { chain: chain, events: [] },
  });
  assert.ok(summary.indexOf('генерация успешна, отправка отменена') === 0,
    'итог не различает генерацию и отправку: ' + summary);
})();

// ── 6. Один save и никаких копий эндпоинтов ──────────────────────────────
(function () {
  assert.strictEqual((APP_JS.match(/\/api\/initiative\/meme-settings/g) || [])
    .length >= 2, true, 'save-эндпоинт настроек мемов не найден');
  assert.strictEqual(APP_JS.indexOf('/api/initiative/meme-settings/'), -1,
    'появился второй save-эндпоинт настроек мемов');
  assert.strictEqual((INDEX.match(/data-meme-save(?=[\s>])/g) || []).length, 1,
    'кнопок сохранения настроек мемов не одна');
  // «Обзор» тяжёлый журнал не грузит: загрузчик вызывается только на своей
  // вкладке (и только если журнал ещё не прочитан).
  const loadIdx = APP_JS.indexOf('loadInitiativePublications: async function');
  assert.ok(loadIdx > 0, 'нет загрузчика журнала публикаций');
  const tabEnter = APP_JS.slice(
    APP_JS.indexOf('initiativeTabEnter: function'), loadIdx);
  assert.ok(tabEnter.indexOf("tab === 'publications'") >= 0,
    'журнал не привязан к своей вкладке');
  const overviewBranch = tabEnter.slice(tabEnter.indexOf("tab === 'overview'"),
                                        tabEnter.indexOf("tab === 'text'"));
  assert.strictEqual(overviewBranch.indexOf('loadInitiativePublications'), -1,
    '«Обзор» запрашивает журнал публикаций (тяжёлые данные на первом экране)');
})();

// ── 7. F3: несохранённый черновик промптов не теряется ───────────────────
(function () {
  const settings = {
    settings: { enabled: true, window_messages: 300, daily_limit: 3,
                cooldown_seconds: 21600, min_messages: 8,
                summarizer_model: '', quiet_hours: '', length_admin: null },
    prompts: {
      joke: { text: 'Серверный прикол', source: 'chat' },
      image: { text: 'Мем: {joke}', source: 'chat' },
    },
  };
  const clean = methods.memeDraftFromSettings(settings);
  const view = computed.memeSettingsView.call({ memeSettings: settings });
  const ctx = {
    memeSettings: settings, memeSettingsView: view,
    memeDraft: Object.assign({}, clean),
    memeDraftFromSettings: methods.memeDraftFromSettings,
    _memeDraftChangedFields: methods._memeDraftChangedFields,
  };
  assert.strictEqual(computed.memeDraftDirty.call(ctx), false,
    'чистый черновик помечен как изменённый');
  assert.strictEqual(computed.memeDraftDirtyCount.call(ctx), 0,
    'у чистого черновика счётчик не 0');
  ctx.memeDraft = Object.assign({}, clean, { prompt_joke: 'ЧЕРНОВИК 123' });
  assert.strictEqual(computed.memeDraftDirty.call(ctx), true,
    'набранный текст не помечается как несохранённая правка');
  // Правдивый счётчик: одно изменённое поле — «1», а не «0».
  assert.strictEqual(computed.memeDraftDirtyCount.call(ctx), 1,
    'счётчик изменённых полей неверен');
  ctx.memeDraft = Object.assign({}, clean, { prompt_joke: 'Серверный прикол',
                                             daily_limit: '5' });
  assert.strictEqual(computed.memeDraftDirtyCount.call(ctx), 1,
    'изменение числового поля не считается правкой');
  // FIX 2: маршрутный guard (переключение вкладки) НЕ поднимается черновиком
  // мемов — иначе модалка лгала бы «потерять их?» на каждый клик по вкладке.
  const guardCtx = {
    stickyDirtyCount: 0, dirtyItems: [], dirtyKeyItems: [],
    saving: { size: 0 }, blockDrafts: {}, ownKeyDraft: '',
    personaDraft: null, speechDirty: {}, speechSampleDraft: null,
    dossierData: null, dossierDraft: '',
    memeDraftDirty: true,
  };
  assert.strictEqual(methods.hasUnsavedEdits.call(guardCtx), false,
    'черновик мемов поднимает маршрутный guard (ложное подтверждение вкладки)');
  // А собственный guard мемов спрашивает ИМЕННО там, где правки теряются,
  // и говорит правду: число полей + реальное имя кнопки сохранения.
  let asked = [];
  const memoCtx = {
    memeDraftDirty: true, memeDraftDirtyCount: 2,
    activeChatTitle: 'Чат A',
    window: undefined,
  };
  const realWindow = global.window;
  global.window = { confirm: function (msg) { asked.push(msg); return false; } };
  try {
    assert.strictEqual(methods._memeDraftLeaveGuard.call(
      memoCtx, 'Переключение чата заменит их данными другого чата.'), false,
      'отказ в подтверждении не остановил смену области');
    assert.strictEqual(asked.length, 1, 'guard спросил не один раз');
    const msg = asked[0];
    assert.ok(msg.indexOf('(2)') >= 0, 'в подтверждении нет числа правок: ' + msg);
    assert.ok(msg.indexOf('(0)') < 0, 'в подтверждении ложный «(0)»: ' + msg);
    assert.ok(msg.indexOf('Сохранить настройки мемов') >= 0,
      'подтверждение не называет реальную кнопку: ' + msg);
    assert.ok(msg.indexOf('Чат A') >= 0,
      'подтверждение не называет область: ' + msg);
    memoCtx.memeDraftDirty = false;
    asked = [];
    assert.strictEqual(methods._memeDraftLeaveGuard.call(memoCtx, 'x'), true,
      'чистый черновик не должен спрашивать');
    assert.strictEqual(asked.length, 0, 'чистый черновик всё равно спросил');
  } finally {
    global.window = realWindow;
  }
  // Смена области вызывает guard мемов, а не только общий.
  const setChatSrc = APP_JS.slice(APP_JS.indexOf('setActiveChat: function'),
                                  APP_JS.indexOf('setActiveChat: function')
                                  + 3000);
  assert.ok(setChatSrc.indexOf('_memeDraftLeaveGuard') >= 0,
    'смена чата не проверяет черновик мемов собственным guard-ом');
  // Закрытие страницы предупреждает (единственный случай безвозвратной потери).
  assert.ok(APP_JS.indexOf('beforeunload') >= 0
            && APP_JS.indexOf('_bindMemeDraftUnloadGuard') >= 0,
    'нет предупреждения при закрытии/перезагрузке страницы');
  // Повторный вход на вкладку не перезаписывает изменённый черновик.
  const src = APP_JS.slice(APP_JS.indexOf('loadMemeSettings: async function'),
                           APP_JS.indexOf('loadMemeDiagnostics: async function'));
  assert.ok(src.indexOf('memeDraftDirty') >= 0
            && src.indexOf('keepDraft') >= 0,
    'перечитывание настроек не учитывает изменённый черновик');
})();

// ── 8. P0.5 (2.58.152): пустой потолок = АВТО, без 0/800/NaN ─────────────
(function () {
  function view(len) {
    return computed.memeSettingsView.call({
      memeSettings: {
        settings: { enabled: true }, quota: {}, analytics: {},
        availability: {}, defaults: {}, day: {}, template: {},
        prompts: {}, delivery: { stages: [] }, length_limit: len,
      },
    });
  }
  // Развёрнутая семантика P0.5: пусто/не задано → «не задан» и
  // «определяет провайдер»; режим приходит с сервера (`mode`), а не
  // угадывается по нулю.
  const auto = view({ ceiling: null, source: 'auto', mode: 'auto',
                      template_chars: 5, joke_budget: null, known: false,
                      placeholder: 'slot' });
  assert.strictEqual(auto.ceilingMode, 'auto');
  assert.strictEqual(auto.ceilingModeText, 'автоматически');
  assert.strictEqual(auto.ceilingText, 'не задан');
  assert.strictEqual(auto.jokeBudgetText, 'определяет провайдер');
  assert.strictEqual(auto.templateCharsText, '5');
  // Никаких подставных чисел в режиме авто.
  ['0', '800', 'NaN', 'undefined', 'неизвестен'].forEach(function (bad) {
    assert.notStrictEqual(auto.ceilingText, bad,
      'потолок в авто не должен показывать ' + bad);
    assert.notStrictEqual(auto.jokeBudgetText, bad,
      'бюджет прикола в авто не должен показывать ' + bad);
  });
  // Подпись источника — ровно выпущенная формулировка (P0.5).
  assert.strictEqual(methods.memeLengthSourceLabel.call({}, 'auto'),
                     'не задан (авто)');
  assert.strictEqual(methods.memeLengthSourceLabel.call({}, 'unknown'),
                     'не задан (авто)');
  assert.strictEqual(methods.memeLengthSourceLabel.call({}, ''),
                     'не задан (авто)');
  // Фиксированный потолок → числа (режим fixed).
  const fixed = view({ ceiling: 400, source: 'model_capability', mode: 'fixed',
                       template_chars: 5, joke_budget: 395, known: true });
  assert.strictEqual(fixed.ceilingMode, 'fixed');
  assert.strictEqual(fixed.ceilingModeText, 'фиксированный');
  assert.strictEqual(fixed.ceilingText, '400');
  assert.strictEqual(fixed.jokeBudgetText, '395');
  // Три состояния ПОЛЯ ввода — из выпущенного `memeLengthError` (P0.5).
  assert.strictEqual(methods.memeLengthError.call({}, ''), '');
  assert.strictEqual(methods.memeLengthError.call({}, '   '), '');
  assert.strictEqual(methods.memeLengthError.call({}, null), '');
  assert.strictEqual(methods.memeLengthError.call({}, '400'), '');
  assert.ok(String(methods.memeLengthError.call({}, '12.5')).indexOf('целое')
            >= 0, 'дробный потолок должен давать точную ошибку поля');
  assert.ok(String(methods.memeLengthError.call({}, '9000')).indexOf('8000')
            >= 0, 'слишком большой потолок должен давать точную ошибку поля');
  // Блок бюджета берёт режим с сервера и не выдумывает «неизвестно».
  const budgetCtx = {
    memeSettingsView: computed.memeSettingsView.call({
      memeSettings: { settings: {}, quota: {}, analytics: {},
                      availability: {}, defaults: {}, day: {}, template: {},
                      prompts: {}, delivery: { stages: [] },
                      length_limit: { ceiling: null, source: 'auto',
                                      mode: 'auto', template_chars: 5,
                                      joke_budget: null, known: false } },
    }),
    memeAttemptStages: [],
    memeLengthSourceLabel: methods.memeLengthSourceLabel,
  };
  const budget = computed.memeBudgetBlock.call(budgetCtx);
  assert.strictEqual(budget.autoMode, true);
  assert.strictEqual(budget.modeText, 'автоматически');
  assert.strictEqual(budget.ceilingText, 'не задан');
  assert.strictEqual(budget.jokeBudgetText, 'определяет провайдер');
  assert.strictEqual(budget.sourceLabel, 'не задан (авто)');
  assert.strictEqual(budget.unknownMode, undefined,
    'состояние «unknown» больше не существует (P0.5: fixed|auto)');
})();

// ── 9. Публикации: отложенный конфликт не выдаётся за ошибку ─────────────
(function () {
  const view = computed.iniPubRows.call({
    iniPub: { rows: [
      { attempt_id: 'meme:5', kind: 'meme', ts: 1800000000, stage: 'publish',
        outcome: 'deferred', reason_code: 'publication_conflict',
        reason_label: '', delivered: null, mode: 'auto',
        reason_codes: ['publication_conflict', 'publication_deferred_conflict'] },
      { attempt_id: 'text:6', kind: 'text_initiative', ts: 1799999999,
        stage: 'send', outcome: 'delivery_unknown',
        reason_code: 'delivery_unknown', reason_label: '', delivered: null,
        mode: 'auto', reason_codes: [] },
    ] },
  });
  assert.strictEqual(view[0].outcomeLabel, 'отложено');
  assert.strictEqual(view[0].outcomeClass, 'badge-info',
    'отложенный конфликт подан как ошибка');
  // Блокер 5: у отложенной строки — «отправки не было», а не глухое «неизвестно».
  assert.strictEqual(view[0].deliveryLabel,
    'отправки не было: попытка отложена');
  assert.strictEqual(view[0].deliveryState, 'never');
  assert.ok(view[0].chainReasonsText.indexOf('конфликт') >= 0
            || view[0].chainReasonsText.length > 0,
    'причины цепочки не дошли до строки журнала');
  assert.strictEqual(view[1].outcomeLabel, 'доставка неизвестна');
  // Фильтр «причина» на сервере использует и причины цепочки — код должен
  // присутствовать в разметке как подсказка строки.
  assert.ok(INDEX.indexOf('data-ini-pub-chain-reason') >= 0,
    'в строке журнала нет подсказки причин цепочки');
  ['deferred', 'delivery_unknown'].forEach(function (v) {
    assert.ok(new RegExp('<option value="' + v + '"').test(INDEX),
      'в фильтре исхода нет «' + v + '»');
  });
})();

// ── 10. Честная подпись источника «вошёл/пропущен» ───────────────────────
(function () {
  const speech = {
    composer: 'on', system_sha12: 'abc', manifest: 'm1', core: 'r21',
    expression: 'e1', humor: 'h1', humor_status: 'rendered',
    layers: [{ layer: 'core', revision: 'r21', chars: 10, rendered: true,
               skip: '' }],
    skipped: {},
  };
  const view = computed.memeSpeechView.call({
    memeSettings: { analytics: { last_joke: { chars: 6, limit: 395,
                                              speech: speech } } },
  });
  assert.ok(view.sourceNote.indexOf('запись пайплайна') >= 0,
    'источник факта не назван честно: ' + view.sourceNote);
  assert.ok(view.sourceNote.indexOf('sha12') >= 0,
    'подпись не привязывает факт к отправленному payload');
  assert.ok(INDEX.indexOf('data-meme-speech-source') >= 0
            && INDEX.indexOf('data-ini-trace-speech-source') >= 0,
    'подпись источника не выведена в UI');
})();

// ── 10.6 Блокеры независимого ревью на d58fbb56 ─────────────────────────
// 2) истёкший приоритет ручного /meme — не живой блок, 3) время только с
// названным основанием, 4) ссылка на попытку из карточки, 5) исходы и
// доставка — по-человечески, без голых токенов.
(function () {
  function pubView(over) {
    return {
      available: true, coordination: 'ok', degraded: false, conflict: false,
      conflict_state: 'none', ok: true, reason: '', reason_label: '',
      detail: '', state: 'released', holder_kind: 'meme', claimed_by: '',
      other_kind: '', other_age_seconds: null, interval_seconds: 900,
      manual_priority_until: null, manual_priority_active: false,
      manual_priority_expired: false, checked_at: NOW_TS,
    };
  }
  function coordOf(pubOver) {
    const view = computed.memeDiagView.call({
      memeDiag: axesPayload({}, { publication: Object.assign(
        pubView(), pubOver || {}) }),
      activeChatId: CHAT, iniOverviewTimezone: TZ,
    });
    return computed.initiativeCoordination.call({ memeDiagView: view });
  }

  // 2) Истёкший дедлайн — полосы нет и он не назван «отложено».
  const expired = coordOf({ manual_priority_until: NOW_TS - 600,
                            manual_priority_active: false,
                            manual_priority_expired: true });
  assert.strictEqual(expired.visible, false,
    'истёкший приоритет ручного /meme показан как живой блок: '
    + JSON.stringify(expired));
  assert.strictEqual(String(expired.label).indexOf('приоритет'), -1,
    'истёкший приоритет назван действующим: ' + expired.label);
  // Без флага бэкенда, но дедлайн в прошлом — тоже не блок (часы сервера).
  const expiredNoFlag = coordOf({ manual_priority_until: NOW_TS - 600 });
  assert.strictEqual(expiredNoFlag.visible, false,
    'прошлый дедлайн без флага нарисован блоком');
  // Живой приоритет — блок с конкретным сроком.
  const live = coordOf({ manual_priority_until: NOW_TS + 600,
                         manual_priority_active: true });
  assert.strictEqual(live.visible, true,
    'живой приоритет ручного /meme не показан');
  assert.strictEqual(live.state, 'deferred');
  assert.ok(String(live.event).indexOf('до ') === 0,
    'срок живого приоритета не назван: ' + live.event);
  // Флаг бэкенда главнее: активный=true даже при «прошлом» штампе.
  const flagWins = coordOf({ manual_priority_until: NOW_TS - 600,
                             manual_priority_active: true });
  assert.strictEqual(flagWins.visible, true,
    'флаг manual_priority_active проигнорирован');

  // 3) Штамп без основания не печатается как «не раньше».
  const noBasis = axesCard('meme', axesPayload({}, {
    readiness: { state: 'waiting', reason: 'cooldown_active',
                 reason_class: 'cooldown',
                 next_eligible_at: NOW_TS + 3600, next_basis: '' },
  }));
  assert.strictEqual(noBasis.nextAt, null,
    'время без основания отдано как обещание');
  assert.strictEqual(String(noBasis.nextText).indexOf('не раньше'), -1,
    'время без основания напечатано как «не раньше»: ' + noBasis.nextText);
  assert.ok(noBasis.nextText.indexOf('основание срока не записано') > 0,
    'отсутствие основания не объяснено: ' + noBasis.nextText);
  assert.strictEqual(noBasis.nextBasisMissing, true);
  const withBasis = axesCard('meme', axesPayload({}, {
    readiness: { state: 'waiting', reason: 'cooldown_active',
                 reason_class: 'cooldown',
                 next_eligible_at: NOW_TS + 3600, next_basis: 'cooldown' },
  }));
  assert.ok(withBasis.nextText.indexOf('не раньше') === 0, withBasis.nextText);
  assert.ok(withBasis.nextText.indexOf('по собственному кулдауну') > 0);
  assert.ok(withBasis.nextAt > 0);

  // 4) Попытка открывается в существующей «Диагностике» по своему родителю.
  const memeCard = axesCard('meme', axesPayload({}, {}));
  assert.strictEqual(memeCard.attemptRef, 'meme:run-1',
    'ссылка на попытку мемов не собрана: ' + memeCard.attemptRef);
  const textCard = axesCard('text', axesPayload({}, {}));
  assert.strictEqual(textCard.attemptRef, 'text:run-1',
    'ссылка на попытку текста не собрана: ' + textCard.attemptRef);
  const noRun = axesCard('meme', axesPayload({}, {
    last_attempt: { at: NOW_TS, mode: 'auto', run_id: '', outcome: 'skipped',
                    stop_stage: 'publish', incomplete_historical: true },
  }));
  assert.strictEqual(noRun.attemptRef, '',
    'ссылка на попытку без родителя выдумана');
  const navCtx = {
    iniPubFocus: '',
    tab: '',
    openWorkspaceTab: function (t) { this.tab = t; },
    initiativeOpenTrace: methods.initiativeOpenTrace,
  };
  methods.iniOpenAttempt.call(navCtx, memeCard.attemptRef);
  assert.strictEqual(navCtx.tab, 'diagnostics',
    'действие карточки не ведёт в существующую «Диагностику»');
  assert.strictEqual(navCtx.iniPubFocus, 'meme:run-1',
    'фокус попытки не передан: ' + navCtx.iniPubFocus);
  methods.iniOpenAttempt.call(navCtx, '');
  assert.strictEqual(navCtx.iniPubFocus, 'meme:run-1',
    'пустая ссылка сбросила фокус попытки');
  assert.ok(INDEX.indexOf('data-ini-open-attempt="text"') > 0
            && INDEX.indexOf('data-ini-open-attempt="meme"') > 0,
    'в карточках нет действия «Показать попытку»');
  assert.ok(INDEX.indexOf('initiativeTextCard.attemptRef') > 0,
    'кнопка не несёт ссылку на попытку');

  // 5) Исходы — по-человечески; молчание — решение, а не остановка.
  const silent = axesCard('text', axesPayload({
    last_attempt: { at: NOW_TS - 60, mode: 'auto', run_id: 'tr-1',
                    outcome: 'silent', stop_stage: 'initiative_decided',
                    incomplete_historical: false },
  }, {}));
  assert.ok(silent.attemptText.indexOf('бот решил промолчать') > 0,
    'молчание не названо решением: ' + silent.attemptText);
  assert.strictEqual(silent.attemptText.indexOf('остановилось'), -1,
    'молчание подано как остановка: ' + silent.attemptText);
  const sentRow = axesCard('meme', axesPayload({}, {
    last_attempt: { at: NOW_TS - 60, mode: 'auto', run_id: 'j-1',
                    outcome: 'sent', stop_stage: 'publish',
                    incomplete_historical: false },
  }));
  assert.ok(sentRow.attemptText.indexOf('отправлено') > 0,
    'исход «sent» не переведён: ' + sentRow.attemptText);
  assert.strictEqual(sentRow.attemptText.indexOf('sent'), -1,
    'в карточке остался голый токен «sent»: ' + sentRow.attemptText);
  const oddRow = axesCard('meme', axesPayload({}, {
    last_attempt: { at: NOW_TS - 60, mode: 'auto', run_id: 'j-2',
                    outcome: 'weird_outcome', stop_stage: 'publish',
                    incomplete_historical: false },
  }));
  assert.ok(oddRow.attemptText.indexOf('код: weird_outcome') > 0,
    'незнакомый исход выведен голым токеном: ' + oddRow.attemptText);

  // 5) Список значимых событий: без голых `silent`/`sent`/`reply.text`.
  const events = computed.initiativeRecentEvents.call({
    initiativeVitality: { decisions: [
      { ts: NOW_TS - 10, action: 'silent', outcome: 'silent',
        reason_code: 'no_random_hit', reason_label: 'порог не пройден' },
      { ts: NOW_TS - 20, action: 'reply.text', outcome: 'say',
        reason_code: '', reason_label: '' },
      { ts: NOW_TS - 30, action: 'nudge', outcome: '', reason_code: '',
        reason_label: '' },
    ] },
    memeSettings: { analytics: { attempts: [
      { ts: NOW_TS - 5, job_id: 'job-9', stage: 'publish', outcome: 'sent',
        reason_code: '' },
    ] } },
  });
  const texts = events.map(function (e) { return e.text; }).join(' | ');
  assert.ok(texts.indexOf('бот решил промолчать') > 0,
    'в списке событий молчание не названо: ' + texts);
  assert.ok(texts.indexOf('ответ текстом') > 0,
    'действие «reply.text» осталось токеном: ' + texts);
  assert.ok(texts.indexOf('отправлено') > 0,
    'исход «sent» остался токеном в списке: ' + texts);
  assert.ok(texts.indexOf('код: nudge') > 0,
    'незнакомое действие не подписано: ' + texts);
  assert.strictEqual(/\bsilent\b/.test(texts.replace('код: ', '')), false,
    'в списке событий остался голый `silent`: ' + texts);
  assert.strictEqual(/(^|[^:]) sent\b/.test(texts), false,
    'в списке событий остался голый `sent`: ' + texts);
})();

// ── 11. Ответ привязан к выбранному чату (P0-INIT-MEME-UX-DIAG §4) ────────
// Поздний ответ другого чата не может стать содержимым карточек: применяем
// только при совпадении epoch И `payload.chat_id`, иначе отбрасываем.
const OTHER_CHAT = -100999;
function diagStub(chatId, runId) {
  return {
    schema_version: 1, generated_at: NOW_TS, chat_id: chatId, degraded: [],
    text_initiative: {
      mechanism: 'text_initiative', available: true, data_state: 'ok',
      no_data_reasons: [], last_attempt: { at: NOW_TS, mode: 'auto',
                                           run_id: runId || 'r', outcome: 'say',
                                           stop_stage: '', incomplete_historical: false },
    },
    meme: { mechanism: 'meme', available: true, data_state: 'ok',
            no_data_reasons: [], last_attempt: { at: NOW_TS, mode: 'auto',
                                                 run_id: runId || 'r', outcome: 'published',
                                                 stop_stage: 'publish', incomplete_historical: false } },
  };
}

function loaderCtx(apiImpl) {
  const ctx = {
    activeChatId: CHAT,
    scopeEpoch: 5,
    memeDiag: null,
    memeDiagBusy: false,
    memeDiagQueued: false,
    memeDiagError: '',
    calls: 0,
    api: apiImpl,
  };
  ctx._scopeGuard = methods._scopeGuard;
  ctx._chatBound = methods._chatBound;
  ctx._payloadChatMatches = methods._payloadChatMatches;
  ctx.loadMemeDiagnostics = methods.loadMemeDiagnostics;
  return ctx;
}

async function chatBoundSuite() {
  // a) Ответ того же чата и того же scope применяется.
  let ctx = loaderCtx(async function () {
    ctx.calls++;
    return diagStub(CHAT, 'run-7');
  });
  await ctx.loadMemeDiagnostics();
  assert.strictEqual(ctx.calls, 1);
  assert.ok(ctx.memeDiag, 'ответ своего чата не применён');
  assert.strictEqual(ctx.memeDiag.text_initiative.last_attempt.run_id,
    'run-7');

  // b) Ответ ДРУГОГО чата отбрасывается, а не подписывает карточки.
  ctx = loaderCtx(async function () {
    ctx.calls++;
    return diagStub(OTHER_CHAT, 'run-foreign');
  });
  await ctx.loadMemeDiagnostics();
  assert.strictEqual(ctx.memeDiag, null,
    'поздний ответ чужого чата применён к выбранному чату');
  assert.ok(String(ctx.memeDiagError).indexOf('другого чата') >= 0,
    'отброс чужого ответа не объяснён: ' + ctx.memeDiagError);

  // c) Смена epoch во время запроса: ответ не применяется, шина не залипает.
  ctx = loaderCtx(async function () {
    ctx.calls++;
    ctx.scopeEpoch += 1;
    return diagStub(CHAT, 'run-late');
  });
  ctx.memeDiag = diagStub(CHAT, 'run-kept');
  await ctx.loadMemeDiagnostics();
  assert.strictEqual(ctx.memeDiag.text_initiative.last_attempt.run_id,
    'run-kept', 'устаревший ответ переписал снимок');
  assert.strictEqual(ctx.memeDiagBusy, false,
    'после смены scope загрузчик остался «занятым» навсегда');

  // d) Занятый загрузчик не теряет вызов: один in-flight + один хвост.
  let release = null;
  ctx = loaderCtx(function () {
    ctx.calls++;
    if (ctx.calls === 1) {
      return new Promise(function (res) { release = res; });
    }
    return Promise.resolve(diagStub(CHAT, 'run-tail'));
  });
  const first = ctx.loadMemeDiagnostics();
  const second = ctx.loadMemeDiagnostics();
  assert.strictEqual(ctx.memeDiagQueued, true,
    'вызов во время чтения потерян (останется старый снимок)');
  release(diagStub(CHAT, 'run-head'));
  await first;
  await second;
  for (let i = 0; i < 5; i++) {
    await new Promise(function (r) { setImmediate(r); });
  }
  assert.strictEqual(ctx.calls, 2, 'хвостовой вызов не выполнен: ' + ctx.calls);
  assert.strictEqual(ctx.memeDiag.text_initiative.last_attempt.run_id,
    'run-tail', 'последний запрос не заменил снимок');

  // e) Шапка не подписывается снимком другого чата.
  const scopeOther = computed.iniOverviewScope.call({
    activeChatId: CHAT,
    accessChats: [{ chat_id: CHAT, title: 'Чат A' }],
    configItems: [{ key: 'limits.chat_timezone', value: 'Europe/Moscow' }],
    memeDiag: diagStub(OTHER_CHAT, 'r'),
  });
  assert.strictEqual(scopeOther.generatedText, '',
    'снимок чужого чата подписал шапку');
  assert.strictEqual(scopeOther.timezone, 'Europe/Moscow');
  assert.strictEqual(scopeOther.chatTitle, 'Чат A');
  const scopeOwn = computed.iniOverviewScope.call({
    activeChatId: CHAT,
    accessChats: [{ chat_id: CHAT, title: 'Чат A' }],
    configItems: [{ key: 'limits.chat_timezone', value: 'Europe/Moscow' }],
    memeDiag: diagStub(CHAT, 'r'),
  });
  assert.ok(scopeOwn.snapshotLabel.indexOf('снимок: ') === 0,
    'снимок своего чата не показан: ' + scopeOwn.snapshotLabel);
  // Пояс не задан → честный UTC, а не выдуманная зона.
  const scopeNoTz = computed.iniOverviewScope.call({
    activeChatId: CHAT, accessChats: [], configItems: [],
    memeDiag: null,
  });
  assert.strictEqual(scopeNoTz.timezone, 'UTC');
  assert.ok(scopeNoTz.timezoneLabel.indexOf('UTC') > 0,
    'отсутствие пояса не названо: ' + scopeNoTz.timezoneLabel);

  // f) Настройки мемов тоже привязаны к чату ответа.
  const settingsCtx = {
    activeChatId: CHAT, scopeEpoch: 7, memeSettings: null,
    memeSettingsBusy: false, memeSettingsError: '', memeFieldErrors: {},
    memeDraftDirty: false, memeDraftChat: null,
    api: async function () { return { chat_id: OTHER_CHAT, settings: {} }; },
    memeDraftFromSettings: function () { return {}; },
    loadMemeDiagnostics: function () { settingsCtx.diagCalls++; },
    diagCalls: 0,
    _scopeGuard: methods._scopeGuard,
    _chatBound: methods._chatBound,
    _payloadChatMatches: methods._payloadChatMatches,
  };
  await methods.loadMemeSettings.call(settingsCtx);
  assert.strictEqual(settingsCtx.memeSettings, null,
    'настройки чужого чата применены к выбранному');
  assert.ok(String(settingsCtx.memeSettingsError).indexOf('другого чата') >= 0,
    'отброс настроек чужого чата не объяснён');

  // g) Смена чата очищает снимок, а чужой payload не рендерится вообще.
  const switchCtx = {
    activeChatId: OTHER_CHAT,
    memeDiag: diagStub(CHAT, 'run-old'),
    memeDiagError: '',
    memeDiagQueued: true,
    memeSettings: { chat_id: CHAT, settings: {} },
    memeSettingsError: '',
    memeFieldErrors: {},
    memeDraft: { prompt_joke: 'чужой черновик' },
    memeDraftChat: CHAT,
    initiativeVitality: { decisions: [{}] },
    iniPubFocus: 'meme:old',
    iniPubDetail: { attempt_id: 'meme:old' },
    iniPubDetailError: '',
    iniTrace: { attempt: {} },
    iniTraceError: '',
    iniTraceOpen: { stages: true },
    iniPub: { rows: [{ attempt_id: 'meme:old' }], counts: { total: 1 },
               notes: ['x'], nextOffset: 2, loaded: true, error: '' },
  };
  methods.iniResetChatScope.call(switchCtx);
  assert.strictEqual(switchCtx.memeDiag, null,
    'смена чата не очистила снимок диагностики');
  assert.strictEqual(switchCtx.memeSettings, null,
    'смена чата не очистила настройки прежнего чата');
  assert.strictEqual(switchCtx.memeDraft, null,
    'черновик прежнего чата переехал в новый');
  assert.strictEqual(switchCtx.iniPub.rows.length, 0,
    'журнал прежнего чата остался на экране');
  assert.strictEqual(switchCtx.iniPub.loaded, false);
  assert.strictEqual(switchCtx.iniPubFocus, '');
  assert.strictEqual(switchCtx.iniTrace, null);
  assert.strictEqual(switchCtx.memeDiagQueued, false);
  // И рендер: снимок чужого чата не даёт карточку даже если он в состоянии.
  const foreignView = computed.memeDiagView.call({
    memeDiag: diagStub(CHAT, 'run-foreign'),
    activeChatId: OTHER_CHAT,
    iniOverviewTimezone: TZ,
  });
  assert.strictEqual(foreignView, null,
    'снимок чужого чата отрендерен для выбранного чата');
  const cardForeign = computed.initiativeMemeCard.call({
    memeDiagView: foreignView,
    activeChatId: OTHER_CHAT,
    iniOverviewTimezone: TZ,
    canEditConfig: function () { return true; },
    memeSettingsView: null,
  });
  assert.strictEqual(cardForeign.deliveryStatus, '',
    'карточка показала доставку из чужого снимка');
  assert.strictEqual(cardForeign.attemptText, 'попыток ещё не было');
  assert.strictEqual(JSON.stringify(cardForeign).indexOf('111'), -1,
    'чужой message_id попал в карточку выбранного чата');
}

chatBoundSuite().then(function () {
  console.log('INITIATIVE-UI-OK');
}).catch(function (err) {
  console.error(err && err.stack || err);
  process.exitCode = 1;
});
