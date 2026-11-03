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

// ── 3. «Обзор»: состояние из гейта механизма, не из мастера ──────────────
(function () {
  function card(block, extra) {
    const ctx = Object.assign({
      intentModuleStatus: function () {
        return { effective: true, sourceLabel: 'module_registry' };
      },
      memeDiagView: { text: block, meme: block },
      initiativeVitality: { sends: [{ ts: 1800000000 }], decisions: [] },
      memeSettings: { analytics: { attempts: [] } },
      memeSettingsView: null,
      initiativePerChatItem: null,
      initiativeFlagGroups: [],
      activeChatId: -100,
      canEditConfig: function () { return true; },
      fmtTs: function () { return 'x'; },
    }, extra || {});
    ctx.memeSettingsView = ctx.memeSettingsView
      || { memeEnabled: false, initiativeEnabled: false, quotaText: 'q',
           remainingText: 'r', resetAt: '', available: true,
           unavailableReason: '' };
    return ctx;
  }
  const off = {
    present: true, isNoData: false, ready: false,
    skip: { code: 'initiative_disabled', label: 'инициатива выключена',
            originLabel: 'гейт' },
    skipRecorded: null, lastCheckText: 'никогда',
    nextCheckText: 'не рассчитана', nextCheckBasisLabel: '',
    cooldown: { ownText: '6 ч', remainingText: '0 с' },
    quota: { unlimited: false, limitText: '3', usedText: '1',
             remainingText: '2' },
    publication: null, random: null, conditionsRows: null,
  };
  const on = Object.assign({}, off, {
    ready: true, skip: null, lastCheckText: '15.01.2027',
  });
  const textOff = computed.initiativeTextCard.call(card(off));
  assert.strictEqual(textOff.effective, false,
    'выключенный гейт механизма не превращается в «включено»');
  assert.strictEqual(textOff.effectiveLabel, 'выключена');
  assert.ok(textOff.sourceLabel.indexOf('гейт механизма') >= 0,
    'источник состояния не подписан: ' + textOff.sourceLabel);
  const textOn = computed.initiativeTextCard.call(card(on));
  assert.strictEqual(textOn.effectiveLabel, 'включена');
  // Без блока диагностики — честный фолбэк на оси, а не выдуманное «вкл».
  const noBlock = computed.initiativeTextCard.call(
    card(null, { memeDiagView: null }));
  assert.strictEqual(noBlock.effectiveLabel, 'состояние неизвестно',
    'без прочитанных осей состояние не должно заявлять «включена»');
})();

// ── 4. «Публикации»: строки и доставка ───────────────────────────────────
(function () {
  const view = computed.iniPubRows.call({
    iniPub: { rows: [
      { attempt_id: 'meme:1', kind: 'meme', ts: 1800000000, stage: 'publish',
        outcome: 'published', reason_code: 'sent', reason_label: 'отправлено',
        delivered: true, mode: 'manual' },
      { attempt_id: 'meme:2', kind: 'meme', ts: 1799999999, stage: 'publish',
        outcome: 'skipped', reason_code: 'publication_stale',
        reason_label: '', delivered: false, mode: 'auto' },
      { attempt_id: 'text:3', kind: 'text_initiative', ts: 1799999998,
        stage: 'decision', outcome: 'say', reason_code: '',
        reason_label: '', delivered: null, mode: 'auto' },
    ] },
  });
  assert.strictEqual(view.length, 3);
  assert.strictEqual(view[0].deliveryLabel, 'доставлено');
  assert.strictEqual(view[1].deliveryLabel, 'не доставлено');
  assert.strictEqual(view[2].deliveryLabel, 'неизвестно',
    'null-доставка не должна читаться как «нет»');
  assert.strictEqual(view[0].modeLabel, 'ручной /meme');
  assert.ok(view[1].reasonText.indexOf('устаревшая') >= 0,
    'код причины без текста не превращается в человеческий: '
    + view[1].reasonText);
  assert.strictEqual(view[0].outcomeOk, true);
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

// ── 8. F5 (fwd-compat): пустой потолок ≠ 0 и читается в двух режимах ─────
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
  // Сегодня backend присылает source="unknown" → прежняя подпись (поведение
  // не меняется до ребейза на P0).
  const unknown = view({ ceiling: null, source: 'unknown', known: false,
                         template_chars: 5, joke_budget: 0 });
  assert.strictEqual(unknown.ceilingText, 'неизвестен');
  assert.strictEqual(unknown.jokeBudgetText, 'неизвестен');
  assert.strictEqual(unknown.ceilingMode, 'unknown');
  // P0.5: пусто = автоматический режим. Тот же код читает новый шейп без
  // правок и НЕ показывает 0/NaN/800.
  const auto = view({ ceiling: null, source: 'auto', known: false,
                      template_chars: 5, joke_budget: 0 });
  assert.strictEqual(auto.ceilingText, 'Автоматически');
  assert.strictEqual(auto.ceilingMode, 'auto');
  assert.strictEqual(auto.jokeBudgetText, 'определяет провайдер');
  assert.ok(methods.memeLengthSourceLabel.call({}, 'auto').indexOf('автоматич')
            >= 0, 'источник «auto» не подписан как автоматический режим');
  const fixed = view({ ceiling: 400, source: 'model_capability',
                       template_chars: 5, joke_budget: 395, known: true });
  assert.strictEqual(fixed.ceilingText, '400');
  assert.strictEqual(fixed.jokeBudgetText, '395');
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
  assert.strictEqual(view[0].deliveryLabel, 'неизвестно');
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

console.log('INITIATIVE-UI-OK');
