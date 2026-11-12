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
  // Свёрнутая строка не печатает коды: незнакомый код цепочки остаётся
  // только в раскрытой трассе. Знакомая причина — читаемой подписью.
  assert.strictEqual(
    view[0].chainReasonsText.indexOf('publication_deferred_conflict'), -1,
    'код причины из цепочки попал в свёрнутую строку: '
    + view[0].chainReasonsText);
  const knownChain = computed.iniPubRows.call({
    iniPub: { rows: [
      { attempt_id: 'meme:7', kind: 'meme', ts: 1800000001, stage: 'publish',
        outcome: 'deferred', reason_code: 'publication_conflict',
        reason_label: '', delivered: null, mode: 'auto',
        reason_codes: ['publication_conflict', 'in_flight'] },
    ] },
  });
  assert.ok(knownChain[0].chainReasonsText.indexOf('уже выполняется') >= 0,
    'знакомая причина цепочки не подписана: '
    + knownChain[0].chainReasonsText);
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

// ── 13. S4-TRACE: связная трасса одной попытки ──────────────────────────
// Проверяется маппинг: реальная попытка, ранний отказ, неизвестный код,
// историческая строка без идентификатора и «записей нет».
const T0 = NOW_TS - 300;
const T1 = NOW_TS - 260;
const T2 = NOW_TS - 200;
const T3 = NOW_TS - 140;
const T4 = NOW_TS - 60;

function traceStep(steps, key) {
  return steps.filter(function (s) { return s.key === key; })[0] || null;
}

function publishedMemeDetail(over) {
  const base = {
    attempt: {
      attempt_id: 'meme:job-1', kind: 'meme', job_id: 'job-1',
      mode: 'manual', ts: T4, stage: 'publish', outcome: 'published',
      reason_code: 'sent', delivered: true, message_id: 4321,
      incomplete_historical: false, chain_len: 4,
    },
    chain: [
      { stage: 'summary', ts: T1, outcome: 'passed', reason_code: '',
        facts: { chars: 41, source: 'chat' } },
      { stage: 'joke', ts: T2, outcome: 'passed', reason_code: '',
        facts: { chars: 6, limit: 395, template_chars: 5,
                 ceiling: 400, trimmed: false, source: 'chat',
                 speech: { composer: 'on', manifest: 'm1',
                           system_sha12: 'abc123', core: 'r21',
                           identity: 'a2', expression: 'e1',
                           style_policy: 'g5', humor: 'h1',
                           technique: 'literalism' } } },
      { stage: 'image_generation', ts: T3, outcome: 'passed', reason_code: '',
        facts: { chars: 23, template_source: 'chat',
                 template_revision: 't1', joke_chars: 6 } },
      { stage: 'publish', ts: T4, outcome: 'published', reason_code: 'sent',
        facts: { gate: 'open', manual: true,
                 source: { chat_id: CHAT, run_id: 'job-1',
                           mode: 'manual', request_ref: '1209864',
                           message_count: 42, first_id: 10,
                           last_id: 51, captured_at: T0 },
                 rights: { mode: 'permission_hook', ok: true, detail: '' },
                 claim: { granted: true, state: 'claimed' },
                 output: { ledger_id: 9, tg_message_id: 4321 } } },
    ],
    events: [
      { event_name: 'source_snapshot', ts: T0, detail: 'messages:42' },
      { event_name: 'digest_ready', ts: T1, detail: 'chars:41' },
      { event_name: 'joke_ready', ts: T2, detail: 'chars:6' },
      { event_name: 'image_ready', ts: T3, detail: 'prompt:23|bytes:1234' },
      { event_name: 'publication_requested', ts: T3 },
      { event_name: 'publication_sent', ts: T4, detail: 'tg:4321',
        delivered: true },
    ],
    delivery: { delivered: true, message_id: 4321 },
  };
  return Object.assign(base, over || {});
}

(function () {
  // 13.1 Опубликованный ручной мем: все шаги ручного словаря, факты реальные.
  const t = computed.iniTraceSteps.call({ iniTrace: publishedMemeDetail() });
  assert.strictEqual(t.kind, 'meme');
  assert.strictEqual(t.isManual, true);
  assert.strictEqual(t.noRows, false);
  assert.deepStrictEqual(t.steps.map(function (s) { return s.key; }),
    ['update', 'permission', 'command', 'priority', 'gates', 'messages',
     'summary', 'joke', 'image', 'claim', 'send', 'result']);
  assert.strictEqual(traceStep(t.steps, 'update').state, 'done');
  assert.ok(traceStep(t.steps, 'update').text.indexOf('1209864') > 0,
    'id команды не показан: ' + traceStep(t.steps, 'update').text);
  assert.strictEqual(traceStep(t.steps, 'permission').state, 'done');
  assert.strictEqual(traceStep(t.steps, 'command').state, 'unknown');
  assert.strictEqual(traceStep(t.steps, 'priority').state, 'unknown');
  assert.strictEqual(traceStep(t.steps, 'gates').state, 'inferred');
  const messages = traceStep(t.steps, 'messages');
  assert.strictEqual(messages.state, 'done');
  assert.ok(messages.text.indexOf('42') > 0, messages.text);
  assert.strictEqual(messages.at, T0);
  const summary = traceStep(t.steps, 'summary');
  assert.strictEqual(summary.state, 'done');
  assert.strictEqual(summary.at, T1);
  assert.ok(summary.text.indexOf('41 символов') === 0, summary.text);
  const joke = traceStep(t.steps, 'joke');
  assert.strictEqual(joke.state, 'done');
  assert.ok(joke.text.indexOf('предел 395') > 0, joke.text);
  assert.ok(joke.note.indexOf('манифест m1') > 0,
    'манифест сборки не показан: ' + joke.note);
  assert.ok(joke.note.indexOf('ревизии: core r21') > 0, joke.note);
  assert.ok(joke.note.indexOf('модель не записана') > 0,
    'отсутствие модели не названо: ' + joke.note);
  const image = traceStep(t.steps, 'image');
  assert.strictEqual(image.state, 'done');
  assert.ok(image.note.indexOf('1234') > 0, image.note);
  assert.strictEqual(traceStep(t.steps, 'claim').state, 'done');
  const send = traceStep(t.steps, 'send');
  assert.strictEqual(send.state, 'done');
  assert.strictEqual(send.at, T4);
  assert.ok(send.text.indexOf('4321') > 0, send.text);
  const result = traceStep(t.steps, 'result');
  assert.strictEqual(result.state, 'done');
  assert.ok(result.text.indexOf('сообщение 4321') === 0, result.text);
  assert.strictEqual(t.stopLabel, '', 'успешная попытка названа остановкой');
  assert.ok(t.statusLine.indexOf('опубликовано') > 0, t.statusLine);

  // 13.2 Автоматический мем: словарь БЕЗ шагов ручного /meme.
  const auto = computed.iniTraceSteps.call({
    iniTrace: publishedMemeDetail({
      attempt: Object.assign({}, publishedMemeDetail().attempt,
                             { attempt_id: 'meme:job-2', job_id: 'job-2',
                               mode: 'auto' }),
    }),
  });
  const autoKeys = auto.steps.map(function (s) { return s.key; });
  assert.ok(autoKeys.indexOf('update') < 0 && autoKeys.indexOf('permission') < 0
            && autoKeys.indexOf('priority') < 0,
    'автоматической попытке приписаны шаги ручного /meme: ' + autoKeys);
  assert.ok(autoKeys.indexOf('trigger') >= 0, autoKeys.join(','));
  assert.strictEqual(auto.modeLabel, 'автоматически');

  // 13.3 Ранний отказ на гейтах: стоп назван, дальнейшие шаги не выполнялись.
  const early = computed.iniTraceSteps.call({
    iniTrace: {
      attempt: { attempt_id: 'meme:job-3', kind: 'meme', job_id: 'job-3',
                 mode: 'auto', ts: T1, stage: 'skipped',
                 outcome: 'skipped', reason_code: 'cooldown_active',
                 delivered: false, message_id: null,
                 incomplete_historical: false },
      chain: [{ stage: 'skipped', ts: T1, outcome: 'skipped',
                reason_code: 'cooldown_active', facts: {} }],
      events: [],
      delivery: { delivered: false, message_id: null },
    },
  });
  const gates = traceStep(early.steps, 'gates');
  assert.strictEqual(gates.state, 'skipped');
  assert.strictEqual(gates.code, 'cooldown_active');
  assert.ok(gates.codeLabel.indexOf('кулдаун') >= 0, gates.codeLabel);
  assert.strictEqual(early.stopLabel, 'Обязательные гейты');
  assert.strictEqual(traceStep(early.steps, 'summary').state, 'not_run');
  assert.strictEqual(traceStep(early.steps, 'joke').state, 'not_run');
  assert.strictEqual(traceStep(early.steps, 'image').state, 'not_run');
  assert.strictEqual(traceStep(early.steps, 'send').state, 'not_run');
  assert.strictEqual(traceStep(early.steps, 'result').state, 'failed');
  assert.ok(early.statusLine.indexOf('остановилось на шаге «Обязательные гейты»') > 0,
    early.statusLine);
  assert.ok(early.statusLine.indexOf('кулдаун') > 0, early.statusLine);

  // 13.4 Неизвестный код: читаемый фолбэк, а не голый токен.
  const odd = computed.iniTraceSteps.call({
    iniTrace: {
      attempt: { attempt_id: 'meme:job-4', kind: 'meme', job_id: 'job-4',
                 mode: 'auto', ts: T1, stage: 'failed',
                 outcome: 'failed', reason_code: 'brand_new_gate',
                 delivered: false, message_id: null,
                 incomplete_historical: false },
      chain: [{ stage: 'failed', ts: T1, outcome: 'failed',
                reason_code: 'brand_new_gate', facts: {} }],
      events: [],
      delivery: { delivered: false, message_id: null },
    },
  });
  assert.ok(odd.reasonLabel.indexOf('код: brand_new_gate') === 0,
    'незнакомый код не подписан: ' + odd.reasonLabel);
  assert.strictEqual(odd.stopLabel, '',
    'незнакомый код не должен давать выдуманный шаг остановки');
  assert.ok(odd.statusLine.indexOf('код: brand_new_gate') > 0, odd.statusLine);
  assert.strictEqual(odd.steps.some(function (s) {
    return s.text.indexOf('brand_new_gate ') === 0;
  }), false, 'голый код попал в текст шага');

  // 13.5 Историческая строка без идентификатора: попытка есть, run id пуст.
  const hist = computed.iniTraceSteps.call({
    iniTrace: {
      attempt: { attempt_id: 'meme:row:abc', kind: 'meme', job_id: '',
                 mode: 'unknown', ts: T2, stage: 'skipped',
                 outcome: 'skipped', reason_code: 'no_random_hit',
                 delivered: false, message_id: null,
                 incomplete_historical: true },
      chain: [{ stage: 'skipped', ts: T2, outcome: 'skipped',
                reason_code: 'no_random_hit', facts: {} }],
      events: [],
      delivery: { delivered: false, message_id: null },
    },
  });
  assert.strictEqual(hist.noRows, false, 'историческая строка прочитана как «нет записей»');
  assert.strictEqual(hist.runId, '');
  assert.strictEqual(hist.modeLabel, 'способ не записан');
  assert.strictEqual(traceStep(hist.steps, 'gates').state, 'skipped');

  // 13.6 Записей нет: «не запускалась», все шаги не выполнялись.
  const empty = computed.iniTraceSteps.call({
    iniTrace: { attempt: null, chain: [], events: [], delivery: null },
  });
  assert.strictEqual(empty.noRows, true);
  assert.ok(empty.statusLine.indexOf('не запускалась') > 0, empty.statusLine);
  empty.steps.forEach(function (s) {
    assert.strictEqual(s.state, 'not_run',
      'шаг «' + s.label + '» выдуман без записей: ' + s.state);
    assert.strictEqual(s.at, null);
  });

  // 13.7 Текстовая инициатива: только её реальные шаги.
  const text = computed.iniTraceSteps.call({
    iniTrace: {
      attempt: { attempt_id: 'text:c1', kind: 'text_initiative', job_id: 'c1',
                 mode: 'auto', ts: T2, stage: 'decision', outcome: 'say',
                 reason_code: '', delivered: true, message_id: 777,
                 incomplete_historical: false },
      chain: [],
      events: [
        { event_name: 'initiative_decided', ts: T1, outcome: 'say',
          reason_code: '' },
        { event_name: 'initiative_sent', ts: T2, detail: 'tg:777' },
      ],
      delivery: { delivered: true, message_id: 777 },
    },
  });
  const textKeys = text.steps.map(function (s) { return s.key; });
  assert.deepStrictEqual(textKeys,
    ['trigger', 'gates', 'context', 'decision', 'send', 'result']);
  assert.ok(textKeys.indexOf('joke') < 0 && textKeys.indexOf('image') < 0,
    'текстовой инициативе приписаны шаги мема: ' + textKeys);
  assert.strictEqual(traceStep(text.steps, 'decision').state, 'done');
  assert.ok(traceStep(text.steps, 'decision').text.indexOf('бот решил ответить') > 0,
    traceStep(text.steps, 'decision').text);
  assert.strictEqual(traceStep(text.steps, 'context').state, 'unknown');
  assert.strictEqual(traceStep(text.steps, 'result').state, 'done');

  // 13.8 Строка списка: run id, чат, стадии, признак доставки, окно счётчиков.
  const rows = computed.iniPubRows.call({
    activeChatId: CHAT,
    iniActiveChatTitle: 'Чат A',
    iniPub: { rows: [
      { attempt_id: 'meme:job-1', kind: 'meme', job_id: 'job-1',
        mode: 'manual', ts: T4, stage: 'publish', outcome: 'published',
        reason_code: 'sent', delivered: true, message_id: 4321,
        chain_len: 2,
        stages: [{ stage: 'summary', outcome: 'passed', reason_code: '', at: T1 },
                 { stage: 'publish', outcome: 'published',
                   reason_code: 'sent', at: T4 }] },
      { attempt_id: 'meme:job-3', kind: 'meme', job_id: 'job-3',
        mode: 'auto', ts: T1, stage: 'failed', outcome: 'failed',
        reason_code: 'joke_generation_failed', delivered: false,
        message_id: null, chain_len: 2,
        stages: [{ stage: 'joke', outcome: 'failed',
                   reason_code: 'joke_generation_failed', at: T1 }] },
      { attempt_id: 'meme:row:abc', kind: 'meme', job_id: '', mode: 'unknown',
        ts: T2, stage: 'publish', outcome: 'skipped',
        reason_code: 'publication_stale', delivered: null, message_id: null,
        incomplete_historical: true, chain_len: 1,
        stages: [{ stage: 'publish', outcome: 'skipped',
                   reason_code: 'publication_stale', at: T2 }] },
    ] },
  });
  assert.strictEqual(rows[0].runId, 'job-1');
  assert.strictEqual(rows[0].chatLabel, 'Чат A');
  assert.strictEqual(rows[0].deliverySign, 'доставлено');
  assert.strictEqual(rows[0].modeLabel, 'ручной /meme');
  assert.ok(rows[0].stagesText.indexOf('Выжимка') === 0, rows[0].stagesText);
  assert.strictEqual(rows[1].failedStage.stage, 'joke');
  assert.strictEqual(rows[1].deliverySign, 'не доставлялось');
  assert.strictEqual(rows[1].outcomeLabel, 'ошибка');
  assert.strictEqual(rows[2].runLabel, 'без идентификатора');
  assert.strictEqual(rows[2].historical, true);
  assert.strictEqual(rows[2].deliverySign, 'не доставлялось',
    'пропуск без отправки назван «не подтверждено»');

  const counts = computed.iniPubCounts.call({
    iniPub: { filters: { days: '7' },
              window: { days: 7 },
              counts: { total: 5, checked: 5, decided: 4, published: 2,
                        delivered: 2, pending: 1, delivery_unknown: 1,
                        text: 1, meme: 4 } },
  });
  assert.strictEqual(counts.windowLabel, 'за 7 дн.');
  assert.strictEqual(counts.checked, 5);
  assert.strictEqual(counts.decided, 4);
  assert.strictEqual(counts.published, 2);
  assert.strictEqual(counts.delivered, 2);
  assert.strictEqual(counts.pending, 1);
  assert.strictEqual(counts.deliveryUnknown, 1);
  assert.ok(INDEX.indexOf('data-ini-pub-window') > 0,
    'окно счётчиков не выведено в разметку');
  assert.ok(INDEX.indexOf('проверено {{ iniPubCounts.checked == null') > 0,
    'счётчик «проверено» не показан отдельно от «решено»');
})();

// ── 11b. Ответы для «Публикаций» и «Диагностики» привязаны к чату ────────
// Поздний ответ другого чата не может стать содержимым карточек: применяем
// только при совпадении epoch И `payload.chat_id`, иначе отбрасываем.
const OTHER_CHAT = -100999;
function diagStub(chatId, runId, tz) {
  return {
    schema_version: 1, generated_at: NOW_TS, chat_id: chatId, degraded: [],
    // P0IM-S6-TZ: пояс чата приходит в самом ответе вместе со слоем.
    time: {
      generated_at: NOW_TS, basis: 'server_snapshot',
      timezone: (tz === undefined
        ? { name: 'Europe/Moscow', source: 'chat', offset_seconds: 10800,
            default_name: 'UTC', reason: '' }
        : tz),
    },
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
  assert.strictEqual(scopeOther.chatTitle, 'Чат A');
  // Пояс берётся ТОЛЬКО из ответа сервера: список глобальных параметров
  // (`configItems`) поясом чата больше не является (P0IM-S6-TZ).
  assert.strictEqual(scopeOther.timezone, 'UTC');
  assert.ok(scopeOther.timezoneLabel.indexOf('не прочитан') >= 0,
    'отсутствие серверного пояса не названо: ' + scopeOther.timezoneLabel);
  const scopeOwn = computed.iniOverviewScope.call({
    activeChatId: CHAT,
    accessChats: [{ chat_id: CHAT, title: 'Чат A' }],
    // Глобальный список ДРУГОЙ зоны: он не должен подменять пояс чата.
    configItems: [{ key: 'limits.chat_timezone', value: 'America/New_York' }],
    memeDiag: diagStub(CHAT, 'r'),
  });
  assert.ok(scopeOwn.snapshotLabel.indexOf('снимок: ') === 0,
    'снимок своего чата не показан: ' + scopeOwn.snapshotLabel);
  assert.strictEqual(scopeOwn.timezone, 'Europe/Moscow',
    'пояс чата взят не из серверного ответа: ' + scopeOwn.timezone);
  assert.strictEqual(scopeOwn.timezoneSource, 'chat');
  assert.ok(scopeOwn.snapshotLabel.indexOf('(сервер)') > 0,
    'штамп снимка не назван серверным: ' + scopeOwn.snapshotLabel);
  // Пояс не задан → честный UTC, а не выдуманная зона.
  const scopeNoTz = computed.iniOverviewScope.call({
    activeChatId: CHAT, accessChats: [], configItems: [],
    memeDiag: null,
  });
  assert.strictEqual(scopeNoTz.timezone, 'UTC');
  assert.ok(scopeNoTz.timezoneLabel.indexOf('UTC') > 0,
    'отсутствие пояса не названо: ' + scopeNoTz.timezoneLabel);
  // Явный «пояс чата не задан» от сервера читается именно так, а НЕ как
  // «пояс чата: UTC»: подставлять заводской пояс за настройку нельзя.
  const scopeFallback = computed.iniOverviewScope.call({
    activeChatId: CHAT, accessChats: [{ chat_id: CHAT, title: 'Чат A' }],
    configItems: [],
    memeDiag: diagStub(CHAT, 'r', { name: 'UTC', source: 'utc_fallback',
                                    offset_seconds: 0, default_name: 'UTC',
                                    reason: '' }),
  });
  assert.strictEqual(scopeFallback.timezone, 'UTC');
  assert.strictEqual(scopeFallback.timezoneSource, 'utc_fallback');
  assert.ok(scopeFallback.timezoneLabel.indexOf('не задан') > 0,
    'отсутствие пояса чата не названо: ' + scopeFallback.timezoneLabel);
  assert.ok(scopeFallback.timezoneLabel.indexOf('заводское') > 0,
    'заводской пояс не назван: ' + scopeFallback.timezoneLabel);
  // Сбой чтения пояса: время печатается как UTC с пометкой, а не как пояс чата.
  const scopeFailed = computed.iniOverviewScope.call({
    activeChatId: CHAT, accessChats: [{ chat_id: CHAT, title: 'Чат A' }],
    configItems: [{ key: 'limits.chat_timezone', value: 'Europe/Moscow' }],
    memeDiag: diagStub(CHAT, 'r', { name: null, source: 'read_failed',
                                    offset_seconds: null, default_name: 'UTC',
                                    reason: 'timezone_read_failed' }),
  });
  assert.strictEqual(scopeFailed.timezone, 'UTC');
  assert.strictEqual(scopeFailed.timezoneKnown, false);
  assert.strictEqual(scopeFailed.timezoneSource, 'read_failed');
  assert.ok(scopeFailed.timezoneLabel.indexOf('не прочитан') >= 0,
    'сбой чтения пояса не назван: ' + scopeFailed.timezoneLabel);

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

// ── 12. P0IM-OV-HEADER: «этот чат / другой чат / сравнить чаты» ─────────
// Три состояния обзора. Второй чат читается ТЕМ ЖЕ эндпоинтом со своим
// `X-Chat-Id`; сравнение — две подписанные колонки из двух payload'ов, без
// третьего «вычислительного» набора.
const OTHER_TITLE = 'Чат B';

function peekPayload(chatId, msgId, runId) {
  const p = axesPayload({
    last_delivery: { status: 'confirmed', at: NOW_TS - 60,
                     destination: chatId, message_id: msgId,
                     run_id: runId || 'corr-x' },
    last_attempt: { at: NOW_TS - 60, mode: 'auto', run_id: runId || 'corr-x',
                    outcome: 'say', stop_stage: '', incomplete_historical: false },
  }, {
    last_delivery: { status: 'confirmed', at: NOW_TS - 60,
                     destination: chatId, message_id: msgId,
                     run_id: runId || 'job-x' },
    last_attempt: { at: NOW_TS - 60, mode: 'auto', run_id: runId || 'job-x',
                    outcome: 'published', stop_stage: 'publish',
                    incomplete_historical: false },
  });
  p.chat_id = chatId;
  return p;
}

function peekCtx(extra) {
  const ctx = Object.assign({
    activeChatId: CHAT,
    accessChats: [{ chat_id: CHAT, title: 'Чат A' },
                  { chat_id: OTHER_CHAT, title: OTHER_TITLE }],
    scopeEpoch: 3,
    memeDiag: null,
    memeDiagError: '',
    iniPeekMode: 'self',
    iniPeek: null,
    iniPeekChatId: null,
    iniPeekBusy: false,
    iniPeekQueued: false,
    iniPeekError: '',
    iniPeekSeq: 0,
    calls: [],
    canEditConfig: function () { return true; },
    memeSettingsView: { memeEnabled: true, initiativeEnabled: true,
                        quotaText: '1 / 3', remainingText: 'осталось 2',
                        resetAt: '' },
  }, extra || {});
  ctx.api = async function (path, options) {
    ctx.calls.push({ path: path, chatId: options && options.chatId });
    return ctx.apiResult ? ctx.apiResult(options) : null;
  };
  ctx._scopeGuard = methods._scopeGuard;
  ctx._iniPeekOk = methods._iniPeekOk;
  ctx.loadIniPeek = methods.loadIniPeek;
  ctx.iniSetPeekMode = methods.iniSetPeekMode;
  return ctx;
}

(function () {
  // 12.1 «Другой чат»: чужой payload читается своим X-Chat-Id и рендерит
  // свои значения — без цифр своего чата.
  const other = peekPayload(OTHER_CHAT, 987654);
  const own = peekPayload(CHAT, 777);
  const view = computed.iniOtherDiagView.call({
    iniPeek: other, iniPeekChatId: OTHER_CHAT, activeChatId: CHAT,
    accessChats: [{ chat_id: CHAT, title: 'Чат A' },
                  { chat_id: OTHER_CHAT, title: OTHER_TITLE }],
  });
  assert.ok(view, 'снимок другого чата не построен');
  assert.ok(view.meme.axes.deliveryText.indexOf('987654') > 0,
    'в карточке другого чата нет ЕГО message_id: ' + view.meme.axes.deliveryText);
  assert.strictEqual(view.meme.axes.deliveryText.indexOf('777'), -1,
    'в карточку другого чата попало значение своего чата');
  const cards = computed.initiativeMemeCard.call({
    activeChatId: CHAT,
    iniViewMode: 'other',
    accessChats: [{ chat_id: CHAT, title: 'Чат A' },
                  { chat_id: OTHER_CHAT, title: OTHER_TITLE }],
    iniOtherDiagView: view,
    iniOtherChat: { chatId: OTHER_CHAT, title: OTHER_TITLE },
    iniOverviewTimezone: TZ,
    canEditConfig: function () { return true; },
    memeSettingsView: null,
    memeDiagView: null,
  });
  assert.ok(cards.deliveryText.indexOf('987654') > 0,
    'карточка в режиме «другой чат» не показывает его доставку: '
    + cards.deliveryText);
  assert.strictEqual(cards.attemptRef, '',
    'в чужом чате появилась ссылка на попытку своего журнала');
  assert.strictEqual(cards.sourceChatTitle, OTHER_TITLE);

  // 12.2 Режим переключается, целевой чат уходит в запрос, снимок чист.
  const ctx = peekCtx();
  ctx.apiResult = function () { return other; };
  methods.iniSetPeekMode.call(ctx, 'other');
  assert.strictEqual(ctx.iniPeekMode, 'other');
  assert.strictEqual(ctx.calls.length, 1, 'второй чат не запрошен');
  assert.strictEqual(ctx.calls[0].chatId, OTHER_CHAT,
    'запрос ушёл не за вторым чатом: ' + JSON.stringify(ctx.calls[0]));
  assert.strictEqual(ctx.calls[0].path,
    '/api/initiative/mechanism-diagnostics',
    'использован не существующий эндпоинт диагностики');

  // 12.3 «Сравнить»: две колонки, каждая со своим payload'ом.
  const cmpCtx = peekCtx({
    iniPeekMode: 'compare',
    memeDiag: own,
    iniPeek: other,
    iniPeekChatId: OTHER_CHAT,
  });
  const cmp = computed.iniCompare.call(cmpCtx);
  assert.strictEqual(cmp.visible, true);
  assert.strictEqual(cmp.ready, true, 'сравнение не собралось: ' + JSON.stringify(cmp.error));
  assert.strictEqual(cmp.groups.length, 2, 'сравнение не по механизмам');
  const memeGroup = cmp.groups.filter(function (g) {
    return g.key === 'meme';
  })[0];
  assert.strictEqual(memeGroup.leftTitle, 'Чат A');
  assert.strictEqual(memeGroup.rightTitle, OTHER_TITLE);
  const del = memeGroup.rows.filter(function (r) { return r.key === 'delivery'; })[0];
  assert.ok(del.leftText.indexOf('777') > 0, del.leftText);
  assert.ok(del.rightText.indexOf('987654') > 0, del.rightText);
  assert.strictEqual(del.leftText, del.leftText,
    'левая колонка не является значением своего payload');
  // Никаких производных чисел: у строки ровно два значения и признак
  // расхождения, третьего «общего» числа нет.
  const keys = Object.keys(del).sort().join(',');
  assert.strictEqual(keys,
    'differs,key,label,leftState,leftText,rightState,rightText',
    'в сравнении появились лишние/вычисленные поля: ' + keys);
  assert.strictEqual(String(del.leftText).indexOf('|'), -1);
  // Каждая ось обеих карточек присутствует.
  const axisKeys = memeGroup.rows.map(function (r) { return r.key; });
  assert.deepStrictEqual(axisKeys,
    ['config', 'now', 'next', 'attempt', 'delivery']);
  // Время в обеих колонках — UTC, чтобы значения были сравнимы без пересчёта.
  assert.ok(del.leftText.indexOf('UTC') > 0, del.leftText);
  assert.ok(del.rightText.indexOf('UTC') > 0, del.rightText);
})();

// 12.4 Честная деградация: один чат — ни «другого», ни «сравнить».
(function () {
  const ctx = peekCtx({ accessChats: [{ chat_id: CHAT, title: 'Чат A' }] });
  assert.strictEqual(computed.iniOtherChat.call(ctx), null,
    'второй чат выдуман при одном доступном');
  methods.iniSetPeekMode.call(ctx, 'compare');
  assert.strictEqual(ctx.iniPeekMode, 'self',
    'режим «сравнить» включился без второго чата');
  assert.strictEqual(ctx.calls.length, 0, 'сделан запрос без второго чата');
  assert.strictEqual(computed.iniViewMode.call(ctx), 'self');
  const cmp = computed.iniCompare.call(ctx);
  assert.strictEqual(cmp.available, false);
  assert.strictEqual(cmp.visible, false);
  assert.deepStrictEqual(cmp.groups, []);
  // Разметка: переключатель и «сравнить» условны (без второго чата их нет).
  assert.ok(/v-if="iniOtherChat"[\s\S]{0,200}data-ini-switch/.test(INDEX),
    'переключатель не скрывается при одном чате');
  assert.ok(INDEX.indexOf('data-ini-switch-mode-btn="compare"') > 0,
    'кнопки «Сравнить чаты» нет в разметке обзора');
  assert.ok(INDEX.indexOf('>Этот чат</button>') > 0
            && INDEX.indexOf('>Другой чат</button>') > 0,
    'в переключателе нет «этого»/«другого» чата');
})();

// 12.5 Устаревшие ответы отбрасываются в КАЖДОМ состоянии.
async function peekStaleSuite() {
  // (а) Ответ пришёл не для того чата, который просили.
  const ctx2 = peekCtx({ iniPeekMode: 'other' });
  ctx2.apiResult = function () { return peekPayload(CHAT, 777); };
  await ctx2.loadIniPeek.call(ctx2);
  assert.strictEqual(ctx2.iniPeek, null,
    'ответ своего чата применён как снимок другого');
  assert.strictEqual(ctx2.iniPeekChatId, null);
  assert.ok(String(ctx2.iniPeekError).length > 0,
    'отброс чужого ответа не объяснён');

  // (б) Шапка сменилась, пока шёл запрос второго чата.
  let release = null;
  const ctx3 = peekCtx({ iniPeekMode: 'compare' });
  ctx3.api = function (path, options) {
    ctx3.calls.push({ path: path, chatId: options && options.chatId });
    return new Promise(function (res) { release = res; });
  };
  const pending = ctx3.loadIniPeek.call(ctx3);
  ctx3.scopeEpoch += 1;                 // смена шапки
  release(peekPayload(OTHER_CHAT, 987654));
  await pending;
  assert.strictEqual(ctx3.iniPeek, null,
    'ответ второго чата применён после смены шапки');
  assert.strictEqual(ctx3.iniPeekBusy, false,
    'загрузчик второго чата залип после смены шапки');

  // (в) Режим вернули на «этот чат», ответ пришёл позже — отброшен.
  let release2 = null;
  const ctx4 = peekCtx({ iniPeekMode: 'other' });
  ctx4.api = function (path, options) {
    ctx4.calls.push({ path: path, chatId: options && options.chatId });
    return new Promise(function (res) { release2 = res; });
  };
  const pending2 = ctx4.loadIniPeek.call(ctx4);
  methods.iniSetPeekMode.call(ctx4, 'self');
  release2(peekPayload(OTHER_CHAT, 987654));
  await pending2;
  assert.strictEqual(ctx4.iniPeek, null,
    'поздний ответ применился после возврата к своему чату');
  assert.strictEqual(computed.iniOtherDiagView.call({
    iniPeek: ctx4.iniPeek, iniPeekChatId: ctx4.iniPeekChatId,
    activeChatId: CHAT,
    accessChats: [{ chat_id: CHAT, title: 'Чат A' },
                  { chat_id: OTHER_CHAT, title: OTHER_TITLE }],
  }), null);

  // (г) Смена активного чата очищает режим и снимок второго чата.
  const ctx5 = peekCtx({
    iniPeekMode: 'compare',
    iniPeek: peekPayload(OTHER_CHAT, 987654),
    iniPeekChatId: OTHER_CHAT,
  });
  methods.iniResetChatScope.call(ctx5);
  assert.strictEqual(ctx5.iniPeekMode, 'self', 'режим пережил смену чата');
  assert.strictEqual(ctx5.iniPeek, null, 'снимок второго чата пережил смену чата');

  // (д) Снимок второго чата не подменяет карточки, если его чат перестал
  //     быть «другим» (шапка ушла на него).
  const foreign = computed.iniOtherDiagView.call({
    iniPeek: peekPayload(OTHER_CHAT, 987654),
    iniPeekChatId: OTHER_CHAT,
    activeChatId: OTHER_CHAT,
    accessChats: [{ chat_id: CHAT, title: 'Чат A' },
                  { chat_id: OTHER_CHAT, title: OTHER_TITLE }],
  });
  assert.strictEqual(foreign, null,
    'снимок показан как «другой чат», хотя он теперь выбранный');
}

// ── 14. P0IM-BAN-NOETA: граница «не раньше», а не «следующая проверка» ───
// Значение `next_check_ts` — вычисленная нижняя граница (провайдер + кулдаун),
// а не расписание. Проверяется и текст, и сама разметка поверхности.
(function () {
  function memeView(over) {
    const payload = {
      schema_version: 1, generated_at: NOW_TS, chat_id: CHAT,
      text_initiative: null,
      meme: Object.assign({
        mechanism: 'meme', output_kind: 'meme_initiative', available: true,
        data_state: 'ok', no_data_reasons: [], ready: false,
        last_check_ts: NOW_TS - 60, next_check_ts: null,
        next_check_basis: 'unknown', random: null, conditions: null,
        stages: null, skip: null, skip_recorded: null,
        cooldown: { own_seconds: 21600, remaining_seconds: 0,
                    basis: 'no_prior_provider_call', basis_ts: null,
                    scope: 'mechanism_own' },
        quota: { available: true, limit: 3, used: 1, remaining: 2,
                 limit_reached: false, unlimited: false, next_reset: '' },
        publication: null, blocking: null,
      }, over || {}),
      degraded: [],
    };
    const view = computed.memeDiagView.call({
      memeDiag: payload, activeChatId: CHAT, iniOverviewTimezone: TZ,
    });
    return view.meme;
  }

  // 14.1 Граница есть: «не раньше …» + НАЗВАННОЕ основание расчёта.
  const bound = memeView({
    next_check_ts: NOW_TS + 600, next_check_basis: 'cooldown',
    cooldown: { own_seconds: 21600, remaining_seconds: 600,
                basis: 'last_provider_call', basis_ts: NOW_TS,
                scope: 'mechanism_own' },
  });
  assert.strictEqual(bound.nextCheckTs, NOW_TS + 600);
  assert.ok(bound.nextCheckBoundText.indexOf('не раньше ') === 0,
    'граница не названа «не раньше»: ' + bound.nextCheckBoundText);
  assert.ok(bound.nextCheckBasisLabel.indexOf('кулдаун') > 0
            && bound.nextCheckBasisLabel.indexOf('провайдер') > 0,
    'основание расчёта не названо: ' + bound.nextCheckBasisLabel);
  assert.strictEqual(bound.nextCheckUnknownReason, '');

  // 14.2 Основания нет (провайдера ещё не вызывали): «нет данных» + причина,
  // никакого нуля и никакого выдуманного времени.
  const unknown = memeView({ next_check_ts: null, next_check_basis: 'unknown' });
  assert.strictEqual(unknown.nextCheckTs, null);
  assert.strictEqual(unknown.nextCheckBoundText, 'нет данных');
  assert.ok(unknown.nextCheckUnknownReason.indexOf('провайдер') > 0,
    'причина «нет данных» не названа: ' + unknown.nextCheckUnknownReason);
  assert.ok(String(unknown.nextCheckBoundText).indexOf('1970') < 0);
  assert.strictEqual(/\d/.test(String(unknown.nextCheckBoundText)), false,
    'в «нет данных» попало число: ' + unknown.nextCheckBoundText);

  // 14.3 Кулдаун не задан — тоже «нет данных», но с другой причиной.
  const noCooldown = memeView({
    next_check_ts: null, next_check_basis: 'unknown',
    cooldown: { own_seconds: 0, remaining_seconds: 0,
                basis: 'no_prior_publication', basis_ts: null,
                scope: 'mechanism_own' },
  });
  assert.ok(noCooldown.nextCheckUnknownReason.indexOf('кулдаун не задан') >= 0,
    'причина не названа: ' + noCooldown.nextCheckUnknownReason);

  // 14.4 Проверок не было — отдельная причина, а не «следующая проверка».
  const never = memeView({
    last_check_ts: null, next_check_ts: null,
    next_check_basis: 'never_checked',
  });
  assert.ok(never.nextCheckUnknownReason.indexOf('проверок ещё не было') >= 0,
    never.nextCheckUnknownReason);

  // 14.5 Разметка поверхности: строки «Следующая проверка» больше нет, а
  // вычисленная граница подписана как расчёт с основанием.
  assert.strictEqual(INDEX.indexOf('Следующая проверка'), -1,
    'в разметке осталась строка «Следующая проверка»');
  assert.strictEqual(APP_JS.indexOf('Следующая проверка'), -1,
    'в коде остался заголовок «Следующая проверка»');
  assert.ok(INDEX.indexOf('Не раньше (расчёт)') > 0,
    'нет строки «Не раньше (расчёт)»');
  assert.ok(INDEX.indexOf('item.block.nextCheckBoundText') > 0,
    'граница не выводится через nextCheckBoundText');
  assert.ok(INDEX.indexOf('item.block.nextCheckBasisLabel') > 0,
    'основание расчёта не выводится рядом с границей');
  assert.ok(INDEX.indexOf('data-meme-diag-next') > 0
            && INDEX.indexOf('item.block.nextCheckUnknownReason') > 0,
    'нет честного «нет данных» с причиной');
})();

// ── 15. Дефекты ревью на 430703be (трасса, журнал, строка списка) ────────
(function () {
  // 15.1 Отсутствие факта этапа ≠ «не выполнялось», если позже есть факты.
  // Прикол без своей записи, но картинка собрана ИЗ него → косвенный факт.
  const noJokeFacts = computed.iniTraceSteps.call({
    iniTrace: {
      attempt: { attempt_id: 'meme:j1', kind: 'meme', job_id: 'j1',
                 mode: 'auto', ts: T4, stage: 'publish',
                 outcome: 'published', reason_code: 'sent', delivered: true,
                 message_id: 555, incomplete_historical: false },
      chain: [
        { stage: 'summary', ts: T1, outcome: 'passed', reason_code: '',
          facts: { chars: 41, source: 'chat' } },
        // Строки прикола нет вовсе.
        { stage: 'image_generation', ts: T3, outcome: 'passed',
          reason_code: '',
          facts: { chars: 20, template_source: 'chat',
                   template_revision: 't1', joke_chars: 7 } },
        { stage: 'publish', ts: T4, outcome: 'published',
          reason_code: 'sent',
          facts: { manual: false, gate: 'open',
                   output: { tg_message_id: 555, ledger_id: 3 } } },
      ],
      events: [
        { event_name: 'digest_ready', ts: T1, detail: 'chars:41' },
        { event_name: 'image_ready', ts: T3, detail: 'prompt:20|bytes:900' },
        { event_name: 'publication_sent', ts: T4, detail: 'tg:555',
          delivered: true },
      ],
      delivery: { delivered: true, message_id: 555 },
    },
  });
  const jokeStep = noJokeFacts.steps.filter(function (s) {
    return s.key === 'joke';
  })[0];
  assert.notStrictEqual(jokeStep.state, 'not_run',
    'прикол назван «не выполнялось», хотя картинка собрана из него');
  assert.strictEqual(jokeStep.state, 'inferred', jokeStep.state);
  assert.ok(jokeStep.text.indexOf('7') > 0,
    'косвенный факт не назван числом: ' + jokeStep.text);
  assert.strictEqual(noJokeFacts.stopLabel, '',
    'успешная попытка получила место остановки');
  assert.ok(noJokeFacts.statusLine.indexOf('опубликовано') > 0,
    noJokeFacts.statusLine);

  // Без косвенного признака, но с фактом более позднего шага — «нет данных»,
  // а не «не выполнялось».
  const lateOnly = computed.iniTraceSteps.call({
    iniTrace: {
      attempt: { attempt_id: 'meme:j2', kind: 'meme', job_id: 'j2',
                 mode: 'auto', ts: T4, stage: 'publish',
                 outcome: 'published', reason_code: 'sent', delivered: true,
                 message_id: 556, incomplete_historical: false },
      chain: [
        { stage: 'image_generation', ts: T3, outcome: 'passed',
          reason_code: '', facts: {} },
        { stage: 'publish', ts: T4, outcome: 'published',
          reason_code: 'sent', facts: {} },
      ],
      events: [{ event_name: 'publication_sent', ts: T4, detail: 'tg:556' }],
      delivery: { delivered: true, message_id: 556 },
    },
  });
  const jokeLate = lateOnly.steps.filter(function (s) {
    return s.key === 'joke';
  })[0];
  assert.notStrictEqual(jokeLate.state, 'not_run',
    'прикол назван «не выполнялось» при доказанном более позднем шаге');
  assert.strictEqual(jokeLate.state, 'unknown', jokeLate.state);

  // 15.2 Неизвестный код НЕ выбирает шаг остановки, даже если этап записан.
  const unknownStop = computed.iniTraceSteps.call({
    iniTrace: {
      attempt: { attempt_id: 'meme:j3', kind: 'meme', job_id: 'j3',
                 mode: 'auto', ts: T2, stage: 'joke', outcome: 'failed',
                 reason_code: 'zz_not_in_any_dict', delivered: false,
                 message_id: null, incomplete_historical: false },
      chain: [{ stage: 'joke', ts: T2, outcome: 'failed',
                reason_code: 'zz_not_in_any_dict', facts: {} }],
      events: [],
      delivery: { delivered: false, message_id: null },
    },
  });
  assert.strictEqual(unknownStop.stopLabel, '',
    'неизвестный код выбрал шаг остановки: ' + unknownStop.stopLabel);
  assert.ok(unknownStop.statusLine.indexOf('код: zz_not_in_any_dict') > 0,
    'читаемая подпись кода потерялась: ' + unknownStop.statusLine);
  assert.ok(unknownStop.statusLine.indexOf('этап остановки не определён') > 0,
    unknownStop.statusLine);
  assert.strictEqual(unknownStop.steps.some(function (s) {
    return s.state === 'failed' && s.key === 'joke'
      && unknownStop.stopLabel === 'Прикол (LLM B)';
  }), false, 'шаг остановки выдуман по этапу');

  // 15.3 Журнал: чужой чат и чужое окно не применяются; нет счётчиков — «нет
  // данных», а не нули.
  async function pubSuite() {
    // (а) Ответ другого чата отбрасывается.
    const foreign = {
      activeChatId: CHAT, scopeEpoch: 4, iniPub: {
        rows: [{ attempt_id: 'meme:old' }], counts: null, window: null,
        notes: [], busy: false, error: '', nextOffset: null, loaded: true,
        filters: { days: 7, kind: 'all', mode: 'all', outcome: 'all',
                   reason: '' },
      },
      iniPubDetail: null, iniPubFocus: '',
      api: async function () {
        return { schema_version: 1, chat_id: -100999, available: true,
                 notes: [], window: { days: 7 }, rows: [{ attempt_id: 'meme:x' }],
                 counts: { checked: 1 }, next_offset: null };
      },
      _scopeGuard: methods._scopeGuard,
      _payloadChatMatches: methods._payloadChatMatches,
    };
    foreign.loadInitiativePublications = methods.loadInitiativePublications;
    await methods.loadInitiativePublications.call(foreign, true);
    assert.strictEqual(foreign.iniPub.rows.length, 0,
      'строки чужого чата попали в журнал');
    assert.strictEqual(foreign.iniPub.loaded, false);
    assert.strictEqual(foreign.iniPub.counts, null,
      'счётчики чужого чата применены');
    assert.ok(String(foreign.iniPub.error).indexOf('другого чата') >= 0,
      'отброс чужого ответа не объяснён');

    // (б) Поздний ответ на «7 дней» не подписывается текущими «30 днями».
    const late = {
      activeChatId: CHAT, scopeEpoch: 5, iniPub: {
        rows: [], counts: null, window: null, notes: [], busy: false,
        error: '', nextOffset: null, loaded: false,
        filters: { days: 7, kind: 'all', mode: 'all', outcome: 'all',
                   reason: '' },
      },
      iniPubDetail: null, iniPubFocus: '',
      api: async function () {
        // Пока шёл запрос, пользователь переключил период на 30 дней.
        late.iniPub.filters.days = '30';
        return { schema_version: 1, chat_id: CHAT, available: true,
                 notes: [], window: { days: 7 },
                 rows: [{ attempt_id: 'meme:late' }],
                 counts: { checked: 2 }, next_offset: null };
      },
      _scopeGuard: methods._scopeGuard,
      _payloadChatMatches: methods._payloadChatMatches,
    };
    late.loadInitiativePublications = methods.loadInitiativePublications;
    await methods.loadInitiativePublications.call(late, true);
    assert.strictEqual(late.iniPub.rows.length, 0,
      'ответ, снятый при другом фильтре, применён к новому окну');

    // (в) Окно подписи — из серверного `window`, а не из фильтров.
    const counts = computed.iniPubCounts.call({
      iniPub: { filters: { days: '30' }, window: { days: 7 },
                counts: { checked: 2, published: 1 } },
    });
    assert.strictEqual(counts.windowLabel, 'за 7 дн.',
      'подпись окна взята из фильтров: ' + counts.windowLabel);
    // (г) Нет счётчиков вовсе — «нет данных», а не нули.
    const emptyCounts = computed.iniPubCounts.call({
      iniPub: { filters: { days: '7' }, window: { days: 7 }, counts: null },
    });
    assert.strictEqual(emptyCounts.hasCounts, false);
    assert.strictEqual(emptyCounts.checked, null);
    assert.strictEqual(emptyCounts.published, null);
    assert.ok(INDEX.indexOf('нет данных: счётчики не пришли') > 0,
      'нет честной строки «нет данных» для счётчиков');
    assert.ok(INDEX.indexOf("iniPubCounts.checked == null ? 'нет данных'") > 0,
      'нулевое значение печатается вместо «нет данных»');
  }

  // 15.4 Строка списка: никакого сырого кода в свёрнутом слое.
  assert.strictEqual(INDEX.indexOf('ini-row__code'), -1,
    'в строке списка остался сырой код причины');
  assert.strictEqual(INDEX.indexOf('row.reason_code'), -1,
    'шаблон строки печатает reason_code');
  assert.strictEqual(INDEX.indexOf('код: ') < 0
                     || INDEX.indexOf('ini-row__code') < 0, true);
  // Код причины цепочки не выводится и текстом строки.
  const chainRow = computed.iniPubRows.call({
    iniPub: { rows: [
      { attempt_id: 'meme:9', kind: 'meme', ts: 1800000002, stage: 'publish',
        outcome: 'deferred', reason_code: 'publication_conflict',
        reason_label: '', delivered: null, mode: 'auto',
        reason_codes: ['publication_conflict', 'publication_deferred_conflict'] },
    ] },
  });
  assert.strictEqual(chainRow[0].chainReasonsText.indexOf('код: '), -1,
    'в свёрнутой строке остался префикс «код: »: '
    + chainRow[0].chainReasonsText);
  // Код остаётся в раскрытой трассе — рядом с русской подписью.
  assert.ok(INDEX.indexOf('data-ini-step-code') > 0,
    'код пропал и из раскрытой трассы');
  assert.ok(APP_JS.indexOf('codeLabel') > 0);

  // 15.5 Сервер кладёт КОД в `reason_label`, а сырые имена незнакомых событий
  // — в `other_events`. В СВЁРНУТОЙ строке — только человеческий текст.
  function rowText(row) {
    return [row.timeText, row.kindLabel, row.runLabel, row.chatLabel,
            row.stagesText, row.modeLabel, row.reasonText, row.outcomeLabel,
            row.deliveryLabel, row.deliverySign, row.messageIdText,
            row.chainReasonsText, row.otherText,
            row.failedStage ? row.failedStage.label : '']
      .filter(Boolean).join(' ');
  }

  // (а) `reason_label` равен коду → ни кода, ни пустоты, а честная подпись.
  const codeAsLabel = computed.iniPubRows.call({
    iniPub: { rows: [
      { attempt_id: 'meme:raw1', kind: 'meme', ts: 1800000010,
        stage: 'publish', outcome: 'failed', reason_code: 'zz_raw_code',
        reason_label: 'zz_raw_code', delivered: false, message_id: null,
        mode: 'auto', reason_codes: ['zz_raw_code'] },
    ] },
  })[0];
  assert.strictEqual(codeAsLabel.reasonText.indexOf('zz_raw_code'), -1,
    'код попал в подпись причины: ' + codeAsLabel.reasonText);
  assert.ok(codeAsLabel.reasonText.length > 0,
    'у строки нет человеческой подписи причины');
  assert.strictEqual(rowText(codeAsLabel).indexOf('zz_raw_code'), -1,
    'код попал в свёрнутую строку: ' + rowText(codeAsLabel));

  // (б) Машинный токен в `reason_label` + сырое имя события: в строке нет ни
  // того, ни другого — оба живут в раскрытой трассе.
  const tokenRow = computed.iniPubRows.call({
    iniPub: { rows: [
      { attempt_id: 'text:raw2', kind: 'text_initiative', ts: 1800000011,
        stage: 'claim', outcome: 'other', reason_code: '',
        reason_label: 'publication_pending', delivered: null,
        message_id: null, mode: 'auto',
        reason_codes: ['publication_pending'],
        other_events: [{ name: 'publication_pending', outcome: 'pending' }] },
    ] },
  })[0];
  assert.strictEqual(tokenRow.reasonText.indexOf('publication_pending'), -1,
    'машинный токен попал в подпись причины: ' + tokenRow.reasonText);
  assert.strictEqual(rowText(tokenRow).indexOf('publication_pending'), -1,
    'сырое имя события попало в свёрнутую строку: ' + rowText(tokenRow));
  assert.strictEqual(rowText(tokenRow).indexOf('pending'), -1,
    'сырой исход события попал в свёрнутую строку: ' + rowText(tokenRow));
  assert.strictEqual(INDEX.indexOf('data-ini-pub-other'), -1,
    'в свёрнутой строке осталась плашка сырых событий');

  // (в) Этап текстовой инициативы тоже читается по-русски, а не «claim».
  const textStage = computed.iniPubRows.call({
    iniPub: { rows: [
      { attempt_id: 'text:raw5', kind: 'text_initiative', ts: 1800000014,
        stage: 'claim', outcome: 'other', reason_code: '', reason_label: '',
        delivered: null, message_id: null, mode: 'auto',
        reason_codes: [], other_events: [] },
    ] },
  })[0];
  assert.strictEqual(textStage.stageLabel, 'захват брони', textStage.stageLabel);
  assert.strictEqual(rowText(textStage).indexOf('claim'), -1,
    'сырое имя этапа попало в свёрнутую строку: ' + rowText(textStage));

  // (в) Код известен словарю → строка подписана по-русски, а не «код: …».
  const knownCode = computed.iniPubRows.call({
    iniPub: { rows: [
      { attempt_id: 'meme:raw3', kind: 'meme', ts: 1800000012,
        stage: 'publish', outcome: 'skipped', reason_code: 'publication_stale',
        reason_label: 'publication_stale', delivered: false,
        message_id: null, mode: 'auto',
        reason_codes: ['publication_stale'] },
    ] },
  })[0];
  assert.ok(knownCode.reasonText.indexOf('устаревшая') >= 0,
    'известный код не получил человеческую подпись: ' + knownCode.reasonText);

  // (г) Обычная человеческая подпись не подменяется словарной.
  const humanLabel = computed.iniPubRows.call({
    iniPub: { rows: [
      { attempt_id: 'meme:raw4', kind: 'meme', ts: 1800000013,
        stage: 'publish', outcome: 'deferred',
        reason_code: 'publication_conflict',
        reason_label: 'публикацию отложил конфликт с другим механизмом',
        delivered: null, message_id: null, mode: 'auto',
        reason_codes: ['publication_conflict'] },
    ] },
  })[0];
  assert.strictEqual(humanLabel.reasonText,
    'публикацию отложил конфликт с другим механизмом');

  return pubSuite();
})();

// 3.4b P0IM-S5B-DELIVERY-FACT: «не доставлено» ≠ «ещё не доставлял».
(function () {
  const notDelivered = axesCard('meme', axesPayload({}, {
    last_delivery: { status: 'not_delivered', at: NOW_TS - 60,
                     destination: CHAT, message_id: null, run_id: 'run-s5b',
                     reason_code: 'publisher_not_bound' },
  }));
  assert.strictEqual(notDelivered.deliveryStatus, 'not_delivered');
  assert.strictEqual(notDelivered.deliveryBadge, 'не доставлено');
  assert.ok(notDelivered.deliveryText.indexOf('не доставлено') === 0,
    'закрытие без отправки не названо: ' + notDelivered.deliveryText);
  assert.ok(notDelivered.deliveryText.indexOf('отправитель не привязан') > 0,
    'причина не названа по-русски: ' + notDelivered.deliveryText);
  assert.strictEqual(notDelivered.deliveryMessageId, '',
    'изображение выдано за сообщение с id: ' + notDelivered.deliveryText);
  assert.strictEqual(notDelivered.deliveryReasonCode, 'publisher_not_bound');

  // Незнакомая причина деградирует в «код: …», а не в голый токен.
  const unknownCode = axesCard('meme', axesPayload({}, {
    last_delivery: { status: 'not_delivered', at: NOW_TS - 60,
                     destination: CHAT, message_id: null, run_id: 'run-x',
                     reason_code: 'brand_new_reason' },
  }));
  assert.ok(unknownCode.deliveryText.indexOf('код: brand_new_reason') > 0,
    'незнакомая причина выведена голым токеном: ' + unknownCode.deliveryText);

  const noReason = axesCard('meme', axesPayload({}, {
    last_delivery: { status: 'not_delivered', at: NOW_TS - 60,
                     destination: CHAT, message_id: null, run_id: 'run-y',
                     reason_code: '' },
  }));
  assert.ok(noReason.deliveryText.indexOf('причина не записана') > 0,
    'отсутствие причины выдано за причину: ' + noReason.deliveryText);
})();

// 3.7b P0IM-S5B-QUOTA: «израсходовано» ≠ «отправлено».
(function () {
  function settingsView(quota) {
    return computed.memeSettingsView.call({
      memeSettings: {
        settings: { enabled: true, daily_limit: 3 },
        quota: quota,
        day: {}, availability: {}, analytics: {}, defaults: {},
        length_limit: {}, prompts: {}, template: {},
      },
    });
  }
  function memeCard(st) {
    const payload = axesPayload({}, {});
    const view = computed.memeDiagView.call({
      memeDiag: payload, activeChatId: CHAT, iniOverviewTimezone: TZ,
    });
    return computed.initiativeMemeCard.call({
      activeChatId: CHAT, iniViewMode: 'self',
      accessChats: [{ chat_id: CHAT, title: 'Чат A' }],
      iniOtherDiagView: null, iniOtherChat: null,
      iniOverviewTimezone: TZ, canEditConfig: function () { return true; },
      memeSettingsView: st, memeDiagView: view,
    });
  }
  const spent = settingsView({ available: true, limit: 3, spent: 1,
                               remaining: 2, delivered: 0, not_delivered: 1,
                               not_delivered_reasons: {
                                 publisher_not_bound: 1 } });
  assert.strictEqual(spent.notDelivered, 1);
  assert.deepStrictEqual(spent.notDeliveredReasons,
                         { publisher_not_bound: 1 });
  const cardSpent = memeCard(spent);
  assert.ok(cardSpent.quotaText.indexOf('израсходовано без отправки: 1') > 0,
    'слот без отправки не показан: ' + cardSpent.quotaText);
  assert.ok(cardSpent.quotaText.indexOf('отправитель не привязан') > 0,
    'причина слота без отправки не названа: ' + cardSpent.quotaText);
  assert.ok(cardSpent.quotaText.indexOf('Генерации сегодня: 1 / 3') === 0,
    'базовая квота подменена припиской: ' + cardSpent.quotaText);

  const delivered = settingsView({ available: true, limit: 3, spent: 1,
                                   remaining: 2, delivered: 1,
                                   not_delivered: 0,
                                   not_delivered_reasons: {} });
  assert.strictEqual(memeCard(delivered).quotaText.indexOf('без отправки'),
                     -1,
                     'доставленный слот показан как неотправленный');

  // Нет данных — это НЕ «ноль неотправленных»: приписки нет.
  const noData = settingsView({ available: true, limit: 3, spent: 2,
                                remaining: 1, delivered: null,
                                not_delivered: null,
                                not_delivered_reasons: {} });
  assert.strictEqual(noData.notDelivered, null);
  assert.strictEqual(memeCard(noData).quotaText.indexOf('без отправки'), -1,
    'отсутствие данных выдано за факт: ' + memeCard(noData).quotaText);
})();

// ═══ P0IM-S6-FRESH: слой решения, пояс из ответа, штамп сервера ════════════
// Три вопроса среза проверяются на реальных вычисляемых свойствах `web/app.js`:
//  1) EFFECTIVE — подпись слоя берётся из `configuration.layers` сервера;
//  2) TIME — пояс форматирования берётся из `time.timezone`, а не из списка
//     глобальных параметров;
//  3) SCOPE — поздний ответ другого чата не применяется, а штамп свежести —
//     серверный `time.generated_at`.
async function s6FreshSuite() {
  assert.ok(typeof computed.iniOverviewTz === 'function',
    'iniOverviewTz не объявлен: пояс нельзя прочитать из ответа');

  const SERVER_TZ = { name: 'Europe/Moscow', source: 'chat',
                      offset_seconds: 10800, default_name: 'UTC',
                      reason: '' };
  const LAYERS = {
    enabled: true, source: 'meme_settings', scope: 'mixed', reason: '',
    layers: [
      { gate: 'module_gate', layer: 'global', enabled: true,
        source: 'product', reason: '' },
      { gate: 'chat_toggle', layer: 'factory', enabled: true,
        source: 'global', reason: '' },
      { gate: 'meme_settings', layer: 'chat', enabled: true,
        source: 'meme_settings', reason: '' },
    ],
  };

  // 1) Слои решения: заводское значение названо заводским, а не «общим».
  const view = computed.memeDiagView.call({
    activeChatId: CHAT,
    memeDiag: {
      schema_version: 1, generated_at: NOW_TS, chat_id: CHAT, degraded: [],
      time: { generated_at: NOW_TS, basis: 'server_snapshot',
              timezone: SERVER_TZ },
      text_initiative: { mechanism: 'text_initiative', available: true,
                         data_state: 'ok', no_data_reasons: [],
                         configuration: LAYERS },
      meme: { mechanism: 'meme', available: true, data_state: 'ok',
              no_data_reasons: [], configuration: LAYERS },
    },
  });
  assert.ok(view, 'оси карточки не собраны');
  assert.strictEqual(view.text.axes.configLayersCount, 3);
  const layersText = view.text.axes.configLayersText || '';
  assert.ok(layersText.indexOf('заводское значение') > 0,
    'заводский слой не назван: ' + layersText);
  assert.ok(layersText.indexOf('слой чата') > 0,
    'слой чата не назван: ' + layersText);
  assert.ok(layersText.indexOf('общий слой') > 0,
    'общий слой не назван: ' + layersText);
  // Разрешающий гейт не пересказывает «разрешает» — только слой.
  assert.strictEqual(layersText.indexOf('разрешает'), -1,
    'разрешающий гейт пересказан словами: ' + layersText);
  // Агрегат прежний: новая строка не подменяет «Разрешено».
  assert.strictEqual(view.text.axes.configState, 'true');

  // Слоёв нет — подпись не выдумывается вовсе.
  const noLayers = computed.memeDiagView.call({
    activeChatId: CHAT,
    memeDiag: {
      schema_version: 1, generated_at: NOW_TS, chat_id: CHAT, degraded: [],
      text_initiative: { mechanism: 'text_initiative', available: true,
                         data_state: 'ok', no_data_reasons: [],
                         configuration: { enabled: true, source: 'product',
                                          scope: 'global', reason: '' } },
      meme: { mechanism: 'meme', available: true, data_state: 'ok',
              no_data_reasons: [],
              configuration: { enabled: true, source: 'product',
                               scope: 'global', reason: '' } },
    },
  });
  assert.strictEqual(noLayers.text.axes.configLayersText, '',
    'слои нарисованы без данных сервера');

  // 2) Пояс карточки берётся из ответа сервера, а не из configItems.
  const tzCtx = {
    activeChatId: CHAT,
    configItems: [{ key: 'limits.chat_timezone', value: 'America/New_York' }],
    memeDiag: {
      schema_version: 1, generated_at: NOW_TS, chat_id: CHAT, degraded: [],
      time: { generated_at: NOW_TS, basis: 'server_snapshot',
              timezone: SERVER_TZ },
      text_initiative: {}, meme: {},
    },
  };
  assert.strictEqual(computed.iniOverviewTimezone.call(tzCtx),
    'Europe/Moscow', 'пояс взят не из ответа сервера');

  // 3) Штамп свежести серверный и печатается в поясе чата.
  const scope = computed.iniOverviewScope.call({
    activeChatId: CHAT,
    accessChats: [{ chat_id: CHAT, title: 'Чат A' }],
    configItems: [],
    memeDiag: {
      schema_version: 1, generated_at: NOW_TS - 999, chat_id: CHAT,
      degraded: [],
      time: { generated_at: NOW_TS, basis: 'server_snapshot',
              timezone: SERVER_TZ },
      text_initiative: {}, meme: {},
    },
  });
  assert.strictEqual(scope.timezone, 'Europe/Moscow');
  assert.strictEqual(scope.timezoneSource, 'chat');
  assert.strictEqual(scope.timeBasisLabel, 'штамп снимка — сервер');
  assert.ok(scope.snapshotLabel.indexOf('(сервер)') > 0,
    'штамп снимка не назван серверным: ' + scope.snapshotLabel);
  // Штамп напечатан В ПОЯСЕ ЧАТА (а не в UTC и не в поясе устройства).
  assert.ok(scope.generatedText, 'штамп снимка не показан');
  assert.strictEqual(scope.generatedText.indexOf(' UTC'), -1,
    'штамп напечатан в UTC, хотя пояс чата известен: ' + scope.generatedText);
  // Тот же момент в другом поясе печатается иначе → пояс реально из payload.
  const sameForTokyo = computed.iniOverviewScope.call({
    activeChatId: CHAT,
    accessChats: [{ chat_id: CHAT, title: 'Чат A' }],
    configItems: [],
    memeDiag: {
      schema_version: 1, generated_at: NOW_TS, chat_id: CHAT, degraded: [],
      time: { generated_at: NOW_TS, basis: 'server_snapshot',
              timezone: { name: 'Asia/Tokyo', source: 'chat',
                          offset_seconds: 32400, default_name: 'UTC',
                          reason: '' } },
      text_initiative: {}, meme: {},
    },
  });
  assert.notStrictEqual(sameForTokyo.generatedText, scope.generatedText,
    'пояс из ответа не влияет на напечатанное время');
  // Штамп берётся из БЛОКА ВРЕМЕНИ, а не из тела ответа: меняем только его.
  const timeStepped = computed.iniOverviewScope.call({
    activeChatId: CHAT,
    accessChats: [{ chat_id: CHAT, title: 'Чат A' }],
    configItems: [],
    memeDiag: {
      schema_version: 1, generated_at: NOW_TS, chat_id: CHAT, degraded: [],
      time: { generated_at: NOW_TS - 7200, basis: 'server_snapshot',
              timezone: SERVER_TZ },
      text_initiative: {}, meme: {},
    },
  });
  assert.notStrictEqual(timeStepped.generatedText, scope.generatedText,
    'штамп взят не из time.generated_at');
  // Пояс не прочитан → время печатается как UTC с ЯВНОЙ пометкой.
  const tzFailed = computed.iniOverviewScope.call({
    activeChatId: CHAT,
    accessChats: [{ chat_id: CHAT, title: 'Чат A' }],
    configItems: [{ key: 'limits.chat_timezone', value: 'Europe/Moscow' }],
    memeDiag: {
      schema_version: 1, generated_at: NOW_TS, chat_id: CHAT, degraded: [],
      time: { generated_at: NOW_TS, basis: 'server_snapshot',
              timezone: { name: null, source: 'read_failed',
                          offset_seconds: null, default_name: 'UTC',
                          reason: 'timezone_read_failed' } },
      text_initiative: {}, meme: {},
    },
  });
  assert.strictEqual(tzFailed.timezoneKnown, false);
  assert.ok(tzFailed.generatedText.indexOf(' UTC') > 0,
    'неизвестный пояс не помечен как UTC: ' + tzFailed.generatedText);
  assert.ok(tzFailed.timezoneLabel.indexOf('не прочитан') >= 0,
    'неизвестный пояс не назван: ' + tzFailed.timezoneLabel);

  // 2b) Время событий на том же экране — тоже в поясе чата, с годом.
  function evCtx(memeDiag) {
    return {
      memeDiag: memeDiag,
      activeChatId: CHAT,
      initiativeVitality: { decisions: [{ ts: NOW_TS, action: 'say',
                                          reason_code: '', reason_label: '' }] },
      memeSettings: null,
      // В живом приложении это computed-СВОЙСТВО; здесь тот же доступ по
      // имени, чтобы проверялся реальный путь рендера.
      get iniOverviewTimezone() {
        return computed.iniOverviewTimezone.call(this);
      },
    };
  }
  const evMoscow = computed.initiativeRecentEvents.call(evCtx({
    chat_id: CHAT, generated_at: NOW_TS, degraded: [],
    time: { generated_at: NOW_TS, timezone: SERVER_TZ },
    text_initiative: {}, meme: {},
  }));
  const evTokyo = computed.initiativeRecentEvents.call(evCtx({
    chat_id: CHAT, generated_at: NOW_TS, degraded: [],
    time: { generated_at: NOW_TS,
            timezone: { name: 'Asia/Tokyo', source: 'chat',
                        offset_seconds: 32400, default_name: 'UTC',
                        reason: '' } },
    text_initiative: {}, meme: {},
  }));
  const evNone = computed.initiativeRecentEvents.call(evCtx(null));
  assert.ok(evMoscow.length && evMoscow[0].timeText,
    'время события не показано');
  assert.ok(evMoscow[0].timeText.indexOf(',') > 0,
    'в метке события нет года: ' + evMoscow[0].timeText);
  assert.notStrictEqual(evMoscow[0].timeText, evTokyo[0].timeText,
    'пояс не влияет на время события (часы устройства): '
    + evMoscow[0].timeText);
  assert.ok(evNone[0].timeText.indexOf(' UTC') > 0,
    'без пояса событие подписано не UTC: ' + evNone[0].timeText);

  // 3) Поздний ответ другого чата не применяется и не подписывает снимок.
  const late = loaderCtx(async function () {
    late.calls++;
    return diagStub(OTHER_CHAT, 'run-foreign');
  });
  late.memeDiag = diagStub(CHAT, 'run-current');
  await late.loadMemeDiagnostics();
  assert.strictEqual(late.memeDiag, null,
    'поздний ответ другого чата применён к карточкам этого чата');
  assert.ok(String(late.memeDiagError).indexOf('другого чата') >= 0,
    'отброс чужого ответа не объяснён: ' + late.memeDiagError);

  // 3) Приоритет ручного /meme без серверного штампа не объявляется живым:
  //    часы браузера в решении не участвуют (P0IM-S6-SCOPE/EXPIRED).
  const coord = computed.initiativeCoordination.call({
    memeDiagView: {
      degraded: [],
      text: { publication: { manualPriorityActive: false,
                             manualPriorityUntilText: '',
                             claimedBy: '', otherKind: '', checkedAtText: '',
                             conflict: false, intervalText: '' } },
      meme: { publication: { manualPriorityActive: false,
                             manualPriorityUntilText: '',
                             claimedBy: '', otherKind: '', checkedAtText: '',
                             conflict: false, intervalText: '' } },
    },
  });
  assert.notStrictEqual(coord.state, 'deferred',
    'ожидание нарисовано без серверного штампа приоритета');
  // Сырой дедлайн в будущем сам по себе ожиданием НЕ становится: сервер уже
  // посчитал `manual_priority_active=false` (истёкший маркер).
  const coordExpired = computed.initiativeCoordination.call({
    memeDiagView: {
      degraded: [],
      text: { publication: { manualPriorityActive: false,
                             manualPriorityUntilText: '01.01 00:00',
                             claimedBy: '', otherKind: '', checkedAtText: '',
                             conflict: false, intervalText: '' } },
      meme: { publication: { manualPriorityActive: false,
                             manualPriorityUntilText: '01.01 00:00',
                             claimedBy: '', otherKind: '', checkedAtText: '',
                             conflict: false, intervalText: '' } },
    },
  });
  assert.notStrictEqual(coordExpired.state, 'deferred',
    'истёкший маркер нарисован как живое ожидание');
}

// ── §P0IM-PB-VOCAB / PB-COUNT / PB-STEP / PB-LLM: витрина новых полей ──
// Проверяется ровно то, где витрина могла соврать: «устарело» как «нет данных»,
// неразделённые «проверено/сгенерировано», выдуманная длительность шага,
// модель из настроек вместо записи.
function productGapsSuite() {
  // 1) «Данные устарели» — третье состояние, а не «нет данных».
  const view = computed.memeDiagView.call({
    memeDiag: axesPayload({ data_state: 'stale', stale: true,
                            stale_reason: 'snapshot_older_than_window',
                            stale_age_seconds: 7 * 3600,
                            stale_window_seconds: 6 * 3600,
                            stale_window_basis: 'cooldown' },
                          { data_state: 'no_data', available: false,
                            no_data_reasons: ['never_checked'] }),
    activeChatId: CHAT,
    iniOverviewTimezone: TZ,
  });
  assert.strictEqual(view.text.isStale, true, 'устаревание не распознано');
  assert.strictEqual(view.text.isNoData, false,
    'устаревание выдано за «нет данных»');
  assert.strictEqual(view.text.stateLabel, 'данные устарели',
    'подпись состояния неверна: ' + view.text.stateLabel);
  assert.ok(view.text.staleNote.indexOf('старше своего окна') >= 0,
    'окно свежести не названо: ' + view.text.staleNote);
  assert.ok(view.text.staleNote.indexOf('6 ч') > 0,
    'величина окна не показана: ' + view.text.staleNote);
  assert.strictEqual(view.meme.isStale, false,
    'блок без данных объявлен устаревшим');
  assert.strictEqual(view.meme.isNoData, true);
  assert.strictEqual(view.meme.stateLabel, 'нет данных');
  // Окно не записано — порог не выдумывается.
  const noWindow = computed.memeDiagView.call({
    memeDiag: axesPayload({ data_state: 'ok', stale: false,
                            stale_reason: 'window_not_recorded',
                            stale_age_seconds: 7 * 3600,
                            stale_window_seconds: null,
                            stale_window_basis: '' }, {}),
    activeChatId: CHAT,
    iniOverviewTimezone: TZ,
  });
  assert.strictEqual(noWindow.text.isStale, false,
    'без записанного окна объявлено устаревание');
  assert.ok(noWindow.text.staleNote.indexOf('не записано') > 0,
    'отсутствие окна не объяснено: ' + noWindow.text.staleNote);

  // 2) Счётчики: «сгенерировано», LLM-вызовы и изображения — отдельные числа.
  const counts = computed.iniPubCounts.call({
    iniPub: { counts: { checked: 10, decided: 10, generated: 4, published: 2,
                        delivered: 3, pending: 1, delivery_unknown: 2,
                        text: 3, meme: 7, llm_calls: 14, images: 7 },
              window: { days: 7 } },
  });
  assert.strictEqual(counts.generated, 4, 'счётчик «сгенерировано» потерян');
  assert.notStrictEqual(counts.generated, counts.published,
    '«сгенерировано» слито с «опубликовано»');
  assert.strictEqual(counts.llmCalls, 14, 'LLM-вызовы не показаны');
  assert.strictEqual(counts.images, 7, 'изображения не показаны');
  const partial = computed.iniPubCounts.call({
    iniPub: { counts: { checked: 1, decided: 1 }, window: { days: 7 } },
  });
  assert.strictEqual(partial.generated, null,
    'отсутствующее число выдано за ноль');
  assert.strictEqual(partial.llmCalls, null);
  assert.strictEqual(partial.images, null);

  // 3) Шаг трассы: длительность из записи (или честный null с причиной),
  //    ID запроса, модель/провайдер/слот.
  const trace = computed.iniPubDetailTrace.call({
    iniPubFocus: 'meme:job-1',
    iniPubDetail: {
      available: true,
      attempt: { attempt_id: 'meme:job-1', kind: 'meme', job_id: 'job-1',
                 mode: 'auto', ts: NOW_TS, stage: 'publish',
                 outcome: 'published', reason_code: 'sent', delivered: true,
                 message_id: 4321 },
      chain: [
        { stage: 'summary', ts: NOW_TS - 30, outcome: 'passed',
          reason_code: '', reason_label: '', facts: { chars: 41 },
          duration_ms: 1200, duration_reason: '',
          request_id: 'job-1', request_id_source: 'journal_job_id',
          llm: { provider: null, model: null, slot: null,
                 recorded_keys: [], reason: 'not_recorded_in_stage_record' } },
        { stage: 'joke', ts: NOW_TS - 20, outcome: 'passed',
          reason_code: '', reason_label: '', facts: { chars: 6 },
          duration_ms: null, duration_reason: 'step_timing_not_recorded',
          request_id: 'job-1', request_id_source: 'journal_job_id',
          llm: { provider: 'cx', model: 'cx/gpt-5', slot: 'writer',
                 recorded_keys: ['provider', 'model', 'slot'], reason: '' } },
        { stage: 'image_generation', ts: NOW_TS - 10, outcome: 'passed',
          reason_code: '', reason_label: '', facts: { chars: 23 },
          duration_ms: null, duration_reason: 'step_timing_not_recorded',
          request_id: 'job-1', request_id_source: 'journal_job_id',
          llm: { provider: null, model: null, slot: null,
                 recorded_keys: [], reason: 'not_recorded_in_stage_record' } },
        { stage: 'publish', ts: NOW_TS, outcome: 'published',
          reason_code: 'sent', reason_label: 'отправлено', facts: {},
          duration_ms: null, duration_reason: 'step_timing_not_recorded',
          request_id: 'job-1', request_id_source: 'journal_job_id',
          llm: { provider: null, model: null, slot: null,
                 recorded_keys: [], reason: 'not_recorded_in_stage_record' } },
      ],
      events: [],
      delivery: { delivered: true, message_id: 4321 },
    },
  });
  const summaryStep = (trace.steps || []).filter(function (s) {
    return s.key === 'summary';
  })[0];
  const jokeStep = (trace.steps || []).filter(function (s) {
    return s.key === 'joke';
  })[0];
  assert.ok(summaryStep, 'шаг «Выжимка» отсутствует');
  assert.strictEqual(summaryStep.durationMs, 1200,
    'измеренная длительность шага потеряна');
  assert.ok(summaryStep.durationText.indexOf('1') === 0,
    'длительность не подписана: ' + summaryStep.durationText);
  assert.strictEqual(summaryStep.requestId, 'job-1',
    'ID запроса шага не показан');
  assert.ok(summaryStep.modelText.indexOf('не записаны') > 0,
    'незаписанная модель не названа: ' + summaryStep.modelText);
  assert.strictEqual(jokeStep.durationMs, null,
    'неизмеренная длительность превращена в число');
  assert.ok(jokeStep.durationText.indexOf('не записана') > 0,
    'неизмеренная длительность не объяснена: ' + jokeStep.durationText);
  assert.ok(jokeStep.modelText.indexOf('cx/gpt-5') > 0,
    'записанная модель не показана: ' + jokeStep.modelText);
}

chatBoundSuite().then(peekStaleSuite).then(s6FreshSuite).then(productGapsSuite)
  .then(function () {
  console.log('INITIATIVE-UI-OK');
}).catch(function (err) {
  console.error(err && err.stack || err);
  process.exitCode = 1;
});