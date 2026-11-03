'use strict';
/* P4 `MEME-UI-FIELDS` (карта memory: MEME-PROMPT-JOKE-FIELD, -IMAGE-FIELD,
 * -THREE-LAYER-UI, MEME-LEN-UI-DIAG, MEME-JOKE-DIAG-UI, MEME-IIC-DIAG-UI,
 * MEME-ACC-03/04/05/12) — ПОВЕДЕНЧЕСКИЕ проверки карточки
 * «Модули → Инициатива → Мемы» на реальном `web/app.js`:
 *
 *   1. Три числа бюджета читаются из КАНОНИЧЕСКИХ имён (`ceiling`,
 *      `template_chars`, `joke_budget`); `known === false` → «неизвестен», не 0.
 *   2. Оба промпта — поля черновика из эффективного текста; сохранение уходит
 *      в существующий POST только изменёнными полями, пустая строка снимает
 *      переопределение, «ничего не менялось» не отправляет запрос.
 *   3. 422 показывается У ПОЛЯ (гейт шаблона и Pydantic-список), а не молча.
 *   4. Ярлыки: стадия `joke` и коды причин (включая причины речевых слоёв).
 *   5. Видимая аналитика по стадиям (MEME-ACC-12): выжимка/прикол/картинка/
 *      публикация различимы, с причиной, шаблоном, бюджетом и длиной прикола.
 *   6. Диагностика прикола (речевые ревизии/manifest) — без текстов и персоны.
 *   7. Два блока диагностики механизмов НЕ склеиваются: null ≠ 0,
 *      `last_check_ts=null` = «никогда», конфликт только из `publication`,
 *      `degraded` → «координация недоступна», `performed=false` = не было
 *      жеребьёвки.
 *   8. Разметка: реальные textarea вместо пассивного текста, три числа,
 *      оба блока, стадии — в `web/index.html`.
 *
 * Запуск: node tests/js/meme_ui_fields_test.js → MEME-UI-FIELDS-OK
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

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;

['memeSettingsView', 'memeSpeechView', 'memeAttemptStages', 'memeDiagView',
 'memeDiagBlocks'].forEach(function (name) {
  assert(computed && computed[name], 'computed.' + name + ' не найден');
});
['memeDraftFromSettings', 'saveMemeSettings', 'memeFieldErrorsFrom',
 'memeStageLabel', 'memeSkipLabel', 'memePromptSourceLabel',
 'memeLengthSourceLabel', 'memePromptEmptyHint', 'loadMemeDiagnostics',
 'loadMemeSettings'].forEach(function (name) {
  assert(methods && methods[name], 'methods.' + name + ' не найден');
});

const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS_SRC = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
// Карточка мемов: от `data-meme-settings` до явного маркера конца карточки
// (P1 2026-11-03: карточка живёт на СВОЕЙ вкладке «Мемы», поэтому границы
// задаёт собственный маркер, а не следующий блок другой вкладки).
const CARD_START = INDEX.indexOf('data-meme-settings');
const CARD_END = CARD_START < 0 ? -1 : INDEX.indexOf('data-ini-memes-end',
                                                    CARD_START);
const CARD = CARD_START < 0 ? null : INDEX.slice(CARD_START, CARD_END);
assert(CARD && CARD.length > 2000, 'карточка data-meme-settings не найдена');

function settingsPayload(extra) {
  const base = {
    chat_id: -100, generated_at: 1800000000,
    settings: { enabled: true, window_messages: 500, daily_limit: 3,
                cooldown_seconds: 21600, min_messages: 8,
                summarizer_model: '', quiet_hours: '', length_admin: null },
    availability: { available: true, reason: 'ok', initiative_enabled: true,
                    image: { available: true }, blocks_text_initiative: false },
    quota: { available: true, reason: 'ok', limit: 3, spent: 1, remaining: 2,
             timezone_name: 'Europe/Moscow', next_reset: '2026-11-01T00:00:00+03:00' },
    day: { bucket: '2026-10-31', timezone_name: 'Europe/Moscow',
           timezone_source: 'chat', next_reset: '2026-11-01T00:00:00+03:00' },
    // ТОЛЬКО канонические имена: алиасы (value/prefix_chars/summary_target)
    // удалены из ответа — карточка обязана работать без них.
    length_limit: { ceiling: 400, source: 'model_capability',
                    template_chars: 5, joke_budget: 395, known: true,
                    placeholder: 'slot', candidates: [] },
    template: { text: 'Мем: {joke}', source: 'chat', placeholders: 1,
                valid: true, error: '' },
    prompts: {
      image: { block_id: 'initiative.meme.image', text: 'Мем: {joke}',
               source: 'chat', differs_from_factory: true,
               factory_revision: 'fac-img', revision: 4,
               setting_key: 'prompts.meme_image' },
      joke: { block_id: 'initiative.meme.joke', text: 'Придумай прикол',
              source: 'factory', differs_from_factory: false,
              factory_revision: 'fac-joke', revision: 1,
              setting_key: 'prompts.meme_joke' },
      summary: { block_id: 'initiative.meme.summary', text: 's',
                 differs_from_factory: false },
    },
    analytics: { output_kind: 'meme_initiative', separate_from_initiative: true,
                 coverage: 'durable',
                 counters: { considered: 4, eligible: 2, summary: 2, joke: 2,
                             image_generation: 1, publish: 1, failed: 0,
                             skipped: 2 },
                 skip_reasons: { daily_quota_reached: 1 },
                 last_joke: {}, attempts: [] },
    delivery: { output_kind: 'meme_initiative', blocks_text_initiative: false,
                publish_blocked_count: 1, skip_reasons: { publish_blocked: 1 },
                stages: ['considered', 'eligible', 'summary', 'joke',
                         'image_generation', 'publish', 'failed', 'skipped'] },
    schema_present: true,
    defaults: { enabled: false, window_messages: 500, daily_limit: 3,
                cooldown_seconds: 21600, min_messages: 8, trigger_probability: 0.05 },
    master_key: 'flags.initiative_enabled',
    own_key: 'flags.meme_initiative_enabled',
  };
  return Object.assign({}, base, extra || {});
}

// ── 1. Три числа бюджета: канонические имена, честное «неизвестен» ────────
(function () {
  const view = computed.memeSettingsView.call({
    memeSettings: settingsPayload() });
  assert.strictEqual(view.ceilingText, '400');
  assert.strictEqual(view.templateCharsText, '5');
  assert.strictEqual(view.jokeBudgetText, '395');
  assert.strictEqual(view.placeholderLabel, 'подстановка {joke}');
  assert.strictEqual(view.templateValid, true);
  assert.strictEqual(view.promptJoke.text, 'Придумай прикол');
  assert.strictEqual(view.promptImage.source, 'chat');

  // Потолок не задан (режим АВТО) → «не задан»/«определяет провайдер» ДЛЯ
  // обоих производных чисел, а длина шаблона остаётся фактом (она считается
  // всегда). Никаких «0 символов», NaN и подставных 771/800.
  const unknown = computed.memeSettingsView.call({
    memeSettings: settingsPayload({
      length_limit: { ceiling: null, source: 'auto', mode: 'auto',
                      template_chars: 5, joke_budget: null, known: false,
                      placeholder: 'append' },
    }) });
  assert.strictEqual(unknown.ceilingText, 'не задан');
  assert.strictEqual(unknown.jokeBudgetText, 'определяет провайдер');
  assert.strictEqual(unknown.ceilingModeText, 'автоматически');
  assert.strictEqual(unknown.ceilingMode, 'auto');
  assert.strictEqual(unknown.templateCharsText, '5');
  assert.strictEqual(view.ceilingModeText, 'фиксированный');
  assert.strictEqual(view.ceilingMode, 'fixed');
  // Ни одного обращения к удалённым алиасам в коде карточки.
  assert.strictEqual(APP_JS_SRC.indexOf('lengthLimit.value'), -1);
  assert.strictEqual(APP_JS_SRC.indexOf('summary_target'), -1);
  assert.strictEqual(CARD.indexOf('summary_target'), -1);
  assert.strictEqual(CARD.indexOf('lengthLimit.value'), -1);
})();

// ── 2. Черновик промптов и сохранение только изменённого ─────────────────
(async function () {
  const draft = methods.memeDraftFromSettings.call({}, settingsPayload());
  assert.strictEqual(draft.prompt_joke, 'Придумай прикол');
  assert.strictEqual(draft.prompt_image, 'Мем: {joke}');
  assert.strictEqual(draft.daily_limit, 3);

  // Правка обоих промптов → ровно два поля в теле существующего POST.
  let calls = [];
  let ctx = {
    activeChatId: -100, memeSettingsSaving: false, memeFieldErrors: {},
    memeSettings: settingsPayload(),
    memeDraft: Object.assign({}, draft, { prompt_joke: 'Новый прикол',
                                          prompt_image: 'Кадр: {joke}' }),
    api: async function (url, opts) { calls.push({ url, opts }); return settingsPayload(); },
    toast: function () {},
    _scopeGuard: function () { return true; },
    memeDraftFromSettings: methods.memeDraftFromSettings,
    memeFieldErrorsFrom: methods.memeFieldErrorsFrom,
    loadMemeDiagnostics: function () {},
    memeSettingsError: '',
  };
  await methods.saveMemeSettings.call(ctx);
  assert.strictEqual(calls.length, 1, 'ожидался один POST');
  assert.strictEqual(calls[0].url, '/api/initiative/meme-settings');
  let body = JSON.parse(calls[0].opts.body);
  assert.deepStrictEqual(Object.keys(body).sort(), ['prompt_image', 'prompt_joke']);
  assert.strictEqual(body.prompt_joke, 'Новый прикол');
  assert.strictEqual(body.prompt_image, 'Кадр: {joke}');

  // Пустая строка уходит как есть — сервер снимет чатовое переопределение.
  calls = [];
  const removal = {
    activeChatId: -100, memeSettingsSaving: false, memeFieldErrors: {},
    memeSettings: settingsPayload(),
    memeDraft: Object.assign({}, draft, { prompt_joke: '' }),
    api: async function (url, opts) { calls.push({ url, opts }); return settingsPayload(); },
    toast: function () {}, _scopeGuard: function () { return true; },
    memeDraftFromSettings: methods.memeDraftFromSettings,
    memeFieldErrorsFrom: methods.memeFieldErrorsFrom,
    loadMemeDiagnostics: function () {}, memeSettingsError: '',
  };
  await methods.saveMemeSettings.call(removal);
  assert.strictEqual(calls.length, 1);
  body = JSON.parse(calls[0].opts.body);
  assert.deepStrictEqual(Object.keys(body), ['prompt_joke']);
  assert.strictEqual(body.prompt_joke, '');

  // Ничего не менялось → запроса нет (сервер вернул бы 422 «нет изменений»).
  calls = [];
  const same = Object.assign({}, removal, {
    memeDraft: Object.assign({}, draft),
    api: async function (url, opts) { calls.push({ url, opts }); return {}; },
  });
  const toasts = [];
  same.toast = function (msg) { toasts.push(msg); };
  await methods.saveMemeSettings.call(same);
  assert.strictEqual(calls.length, 0, 'при отсутствии изменений POST не нужен');
  assert.ok(toasts.pop().indexOf('не изменены') >= 0);
})();

// ── 2b. P0.5: пустой потолок = АВТО (три состояния поля) ────────────────
(async function () {
  // Разбор ввода: пусто = авто (без ошибки), целое > 0 = фиксированный,
  // дробное/текст/отрицательное = ТОЧНАЯ ошибка поля.
  assert.strictEqual(methods.memeLengthError.call({}, ''), '');
  assert.strictEqual(methods.memeLengthError.call({}, '   '), '');
  assert.strictEqual(methods.memeLengthError.call({}, null), '');
  assert.strictEqual(methods.memeLengthError.call({}, 0), '');
  assert.strictEqual(methods.memeLengthError.call({}, '400'), '');
  assert.strictEqual(methods.memeLengthError.call({}, 400), '');
  assert.ok(methods.memeLengthError.call({}, '12.5').indexOf('целое') >= 0);
  assert.ok(methods.memeLengthError.call({}, 'abc').indexOf('целое') >= 0);
  assert.ok(methods.memeLengthError.call({}, '-5').indexOf('целое') >= 0);
  assert.ok(methods.memeLengthError.call({}, '9000').indexOf('8000') >= 0);

  const draft = methods.memeDraftFromSettings.call({}, settingsPayload());
  // Снятие чатового потолка уходит ЯВНЫМ null: сервер снимет переопределение
  // (наследование/авто), а не запишет 0. Потолок чата задан (400) — иначе
  // «очистить» действительно ничего не меняло бы.
  const withCeiling = settingsPayload();
  withCeiling.settings = Object.assign({}, withCeiling.settings,
                                       { length_admin: 400 });
  let calls = [];
  const cleared = {
    activeChatId: -100, memeSettingsSaving: false, memeFieldErrors: {},
    memeSettings: withCeiling,
    memeDraft: Object.assign({}, methods.memeDraftFromSettings.call(
      {}, withCeiling), { length_limit: '' }),
    api: async function (url, opts) {
      calls.push({ url, opts }); return settingsPayload();
    },
    toast: function () {}, _scopeGuard: function () { return true; },
    memeDraftFromSettings: methods.memeDraftFromSettings,
    memeFieldErrorsFrom: methods.memeFieldErrorsFrom,
    memeLengthError: methods.memeLengthError,
    loadMemeDiagnostics: function () {}, memeSettingsError: '',
  };
  await methods.saveMemeSettings.call(cleared);
  assert.strictEqual(calls.length, 1);
  let body = JSON.parse(calls[0].opts.body);
  assert.deepStrictEqual(Object.keys(body), ['length_limit']);
  assert.strictEqual(body.length_limit, null);

  // Фиксированное значение уходит числом (auto → fixed).
  calls = [];
  const fixed = Object.assign({}, cleared, {
    memeFieldErrors: {},
    memeDraft: Object.assign({}, cleared.memeDraft, { length_limit: '512' }),
  });
  await methods.saveMemeSettings.call(fixed);
  assert.strictEqual(calls.length, 1);
  body = JSON.parse(calls[0].opts.body);
  assert.strictEqual(body.length_limit, 512);

  // Некорректный ввод НЕ отправляется и даёт точную ошибку, а не тихий null.
  let badCalls = 0;
  const toasts = [];
  const bad = Object.assign({}, cleared, {
    memeFieldErrors: {}, memeSettingsError: '',
    memeDraft: Object.assign({}, draft, { length_limit: '12.5' }),
    api: async function () { badCalls += 1; return {}; },
    toast: function (msg) { toasts.push(String(msg)); },
  });
  await methods.saveMemeSettings.call(bad);
  assert.strictEqual(badCalls, 0, 'некорректное значение не уходит на сервер');
  assert.ok(String(bad.memeFieldErrors.length_limit).indexOf('целое') >= 0);
  assert.ok(toasts.pop().indexOf('целое') >= 0, 'ошибка видна пользователю');
})();

// ── 3. 422 показывается У ПОЛЯ (громко, а не молча) ──────────────────────
(async function () {
  // Гейт шаблона: `detail` строкой с ключом каталога.
  const guard = new Error('шаблон: допускается не более одного {joke}');
  guard.status = 422;
  guard.message = 'prompts.meme_image: шаблон: допускается не более одного {joke}';
  let ctx = {
    activeChatId: -100, memeSettingsSaving: false, memeFieldErrors: {},
    memeSettings: settingsPayload(),
    memeDraft: Object.assign({}, methods.memeDraftFromSettings.call(
      {}, settingsPayload()), { prompt_image: 'x {joke} y {joke}' }),
    api: async function () { throw guard; },
    toast: function () {}, _scopeGuard: function () { return true; },
    memeDraftFromSettings: methods.memeDraftFromSettings,
    memeFieldErrorsFrom: methods.memeFieldErrorsFrom,
    memeSettingsError: 'было',
  };
  await methods.saveMemeSettings.call(ctx);
  const fieldError = methods.memeFieldError.call(ctx, 'prompt_image');
  assert.ok(fieldError.indexOf('Шаблон картинки не сохранён') === 0, fieldError);
  assert.ok(fieldError.indexOf('одного {joke}') >= 0, fieldError);
  assert.strictEqual(ctx.memeSettingsError, '',
    'причина 422 живёт у поля, а не в общей строке');
  assert.strictEqual(methods.memeFieldError.call(ctx, 'prompt_joke'), '');

  // Pydantic-список: имя поля берётся из `loc`, ошибка тоже видна у поля.
  const pyd = new Error('validation');
  pyd.status = 422;
  pyd.message = [{ loc: ['body', 'prompt_joke'], msg: 'слишком длинное' }];
  const ctx2 = Object.assign({}, ctx, {
    memeFieldErrors: {}, memeSettingsError: '',
    memeDraft: Object.assign({}, methods.memeDraftFromSettings.call(
      {}, settingsPayload()), { prompt_joke: 'x'.repeat(10) }),
    api: async function () { throw pyd; },
  });
  await methods.saveMemeSettings.call(ctx2);
  assert.ok(methods.memeFieldError.call(ctx2, 'prompt_joke')
    .indexOf('слишком длинное') > 0);

  // Неизвестное имя поля (клиент собрал по другому имени) НЕ выдаётся за
  // успех: ошибка видна в общей строке карточки.
  const unknownField = new Error('validation');
  unknownField.status = 422;
  unknownField.message = [{ loc: ['body', 'joke_prompt'], msg: 'extra_forbidden' }];
  const ctx3 = Object.assign({}, ctx, {
    memeFieldErrors: {}, memeSettingsError: '',
    memeDraft: Object.assign({}, methods.memeDraftFromSettings.call(
      {}, settingsPayload()), { prompt_joke: 'y' }),
    api: async function () { throw unknownField; },
  });
  await methods.saveMemeSettings.call(ctx3);
  assert.strictEqual(ctx3.memeFieldErrors.prompt_joke, undefined,
    'чужое имя поля не приписывается нашему');
  assert.ok(ctx3.memeSettingsError.length > 0, '422 обязан быть видимым');
})();

// ── 4. Ярлыки: стадия `joke` и коды причин ───────────────────────────────
(function () {
  assert.strictEqual(methods.memeStageLabel.call({}, 'joke'),
                     'Генерация прикола');
  assert.strictEqual(methods.memeStageLabel.call({}, 'summary'), 'Выжимка');
  assert.strictEqual(methods.memeStageLabel.call({}, 'image_generation'),
                     'Генерация картинки');
  assert.strictEqual(methods.memeStageLabel.call({}, 'publish'), 'Публикация');
  const codes = ['joke_generation_failed', 'joke_empty', 'no_joke_budget',
                 'template_empty', 'no_l1_plan_in_genre',
                 'self_model_folded_into_identity',
                 'expression_examples_absent', 'channel_output_not_required',
                 'initiative_disabled', 'schema_absent', 'cooldown_active',
                 'daily_quota_reached', 'quiet_hours', 'publication_conflict'];
  codes.forEach(function (code) {
    const label = methods.memeSkipLabel.call({}, code);
    assert.notStrictEqual(label, code, 'нет человеческого ярлыка для ' + code);
    assert.ok(label.length > 2);
  });
  // Неизвестный код честно отдаётся кодом (не выдуманная подпись).
  assert.strictEqual(methods.memeSkipLabel.call({}, 'some_new_code'),
                     'some_new_code');
  assert.strictEqual(methods.memeSkipLabel.call({}, ''), '—');
})();

// ── 5. Видимая аналитика по стадиям (MEME-ACC-12) ────────────────────────
(function () {
  const facts = function (obj) { return JSON.stringify(obj); };
  const attempts = [
    { job_id: 'job-1', stage: 'publish', outcome: 'published',
      reason_code: '', detail: '{}', limit_value: 400,
      limit_source: 'model_capability', ts: 1800000300 },
    { job_id: 'job-1', stage: 'image_generation', outcome: 'passed',
      reason_code: '', detail: facts({ chars: 12, template_chars: 5,
                                       joke_chars: 6 }), limit_value: 400,
      limit_source: 'model_capability', ts: 1800000300 },
    { job_id: 'job-1', stage: 'joke', outcome: 'passed', reason_code: '',
      detail: facts({ limit: 395, template_chars: 5, chars: 6, trimmed: false }),
      limit_value: 400, limit_source: 'model_capability', ts: 1800000300 },
    { job_id: 'job-1', stage: 'summary', outcome: 'passed', reason_code: '',
      detail: facts({ chars: 40 }), limit_value: 400,
      limit_source: 'model_capability', ts: 1800000300 },
    // Прошлая (более старая) попытка — в таблицу НЕ попадает.
    { job_id: 'job-0', stage: 'joke', outcome: 'skipped',
      reason_code: 'no_joke_budget', detail: '{}', limit_value: 400, ts: 1799999000 },
  ];
  const ctx = { memeSettings: settingsPayload({
    analytics: Object.assign({}, settingsPayload().analytics,
                             { attempts: attempts }) }) };
  const rows = computed.memeAttemptStages.call(ctx);
  assert.deepStrictEqual(rows.map(function (r) { return r.stage; }),
    ['summary', 'joke', 'image_generation', 'publish']);
  assert.deepStrictEqual(rows.map(function (r) { return r.stageLabel; }),
    ['Выжимка', 'Генерация прикола', 'Генерация картинки', 'Публикация']);
  const joke = rows[1];
  assert.strictEqual(joke.jokeLimit, 395);
  assert.strictEqual(joke.templateChars, 5);
  assert.strictEqual(joke.jokeChars, 6);
  // «Символы» не путаются между этапами: у выжимки это её длина, у картинки —
  // итоговый промпт, и только у прикола — длина прикола.
  assert.strictEqual(rows[0].summaryChars, 40);
  assert.strictEqual(rows[0].jokeChars, null);
  assert.strictEqual(rows[2].promptChars, 12);
  assert.strictEqual(rows[2].jokeChars, 6);
  assert.strictEqual(rows[2].jokeLimit, null);
  assert.strictEqual(rows[3].hasFacts, false);
  assert.strictEqual(rows[3].outcomeLabel, 'опубликовано');
  assert.strictEqual(rows[3].outcomeOk, true);
  // Журнала нет → [] (не «нули» и не выдуманные стадии).
  assert.deepStrictEqual(computed.memeAttemptStages.call({
    memeSettings: settingsPayload() }), []);

  // Пропуск этапа виден как пропуск со своей причиной.
  const skipRows = computed.memeAttemptStages.call({
    memeSettings: settingsPayload({ analytics: Object.assign(
      {}, settingsPayload().analytics, { attempts: [
        { job_id: 'j2', stage: 'joke', outcome: 'skipped',
          reason_code: 'no_joke_budget', detail: '{}', limit_value: 400, ts: 5 },
        { job_id: 'j2', stage: 'summary', outcome: 'passed',
          detail: facts({ chars: 40 }), limit_value: 400, ts: 5 },
      ] }) }) });
  assert.strictEqual(skipRows[1].stage, 'joke');
  assert.strictEqual(skipRows[1].outcomeLabel, 'пропуск');
  assert.strictEqual(methods.memeSkipLabel.call({}, skipRows[1].reasonCode),
                     'бюджета для прикола не осталось');
})();

// ── 6. Диагностика прикола: ревизии/manifest, БЕЗ текстов ────────────────
(function () {
  // Нет попытки → null («приколов ещё не было»), без нулей.
  assert.strictEqual(computed.memeSpeechView.call({
    memeSettings: settingsPayload() }), null);

  const speech = {
    composer: 'on', system_sha12: 'f0c2695c31ca', manifest: '62aaae1adf259de9',
    core: 'r21.848ba4c426b8', core_detail: 'compact:document_default',
    identity: 'a227bfbefc8732fb', expression: '386f4ac001c1',
    style_policy: 'g5.6aff783e44a7', humor: '402b6636e025',
    technique: 'deadpan', humor_status: 'rendered',
    off_axes: ['humor_library_enabled'],
    layers: [
      { layer: 'core', block: 'core', revision: 'r21.848ba4c426b8', chars: 900,
        rendered: true, skip: '' },
      { layer: 'response_plan', block: 'plan', revision: '', chars: 0,
        rendered: false, skip: 'no_l1_plan_in_genre' },
    ],
    skipped: { response_plan: 'no_l1_plan_in_genre' },
  };
  const view = computed.memeSpeechView.call({ memeSettings: settingsPayload({
    analytics: Object.assign({}, settingsPayload().analytics, {
      last_joke: { limit: 395, template_chars: 5, chars: 6, trimmed: true,
                   source: 'chat', speech: speech },
    }) }) });
  assert.strictEqual(view.composerLabel, 'собран единым композером');
  assert.strictEqual(view.systemSha, 'f0c2695c31ca');
  assert.strictEqual(view.manifest, '62aaae1adf259de9');
  const revs = {};
  view.revisions.forEach(function (r) { revs[r.key] = r.value; });
  assert.strictEqual(revs.core, 'r21.848ba4c426b8');
  assert.strictEqual(revs.identity, 'a227bfbefc8732fb');
  assert.strictEqual(revs.expression, '386f4ac001c1');
  assert.strictEqual(revs.style_policy, 'g5.6aff783e44a7');
  assert.strictEqual(revs.humor, '402b6636e025');
  assert.strictEqual(view.humorRendered, true);
  assert.strictEqual(view.technique, 'deadpan');
  assert.deepStrictEqual(view.offAxes, ['humor_library_enabled']);
  assert.strictEqual(view.layers.length, 2);
  assert.strictEqual(view.layers[1].rendered, false);
  assert.strictEqual(view.skipped[0].code, 'no_l1_plan_in_genre');
  assert.strictEqual(view.jokeChars, 6);
  assert.strictEqual(view.jokeLimit, 395);
  assert.strictEqual(view.jokeTrimmed, true);

  // Приём выключен владельцем → честная причина, а не пустая подпись.
  const off = computed.memeSpeechView.call({ memeSettings: settingsPayload({
    analytics: Object.assign({}, settingsPayload().analytics, {
      last_joke: { chars: 6, speech: Object.assign({}, speech, {
        humor_status: 'skip:humor_disabled', humor: '', technique: '' }) },
    }) }) });
  assert.strictEqual(off.humorRendered, false);
  assert.strictEqual(off.humorSkip, 'humor_disabled');
  assert.strictEqual(methods.memeSkipLabel.call({}, off.humorSkip),
                     'юмор выключен');

  // Композер не собрался → legacy payload назван честно.
  const legacy = computed.memeSpeechView.call({ memeSettings: settingsPayload({
    analytics: Object.assign({}, settingsPayload().analytics, {
      last_joke: { chars: 6, speech: { composer: 'failed',
                                       system_sha12: 'abc123abc123' } },
    }) }) });
  assert.strictEqual(legacy.composerLabel,
                     'композер недоступен — payload прежней сборки');
  assert.strictEqual(legacy.layers.length, 0);

  // Текст прикола в журнале (гипотетическая утечка) НЕ выводится в карточку.
  const leaky = computed.memeSpeechView.call({ memeSettings: settingsPayload({
    analytics: Object.assign({}, settingsPayload().analytics, {
      last_joke: { chars: 6, joke: 'СЕКРЕТНЫЙ_ТЕКСТ_ПРИКОЛА', summary: 'СЕКРЕТ',
                   speech: Object.assign({}, speech,
                                         { layer_text: 'СЕКРЕТ_СЛОЯ' }) },
    }) }) });
  const dump = JSON.stringify(leaky);
  assert.strictEqual(dump.indexOf('СЕКРЕТНЫЙ_ТЕКСТ_ПРИКОЛА'), -1);
  assert.strictEqual(dump.indexOf('СЕКРЕТ_СЛОЯ'), -1);
})();

// ── 7. Два блока диагностики: раздельность и честность ──────────────────
(function () {
  function block(mechanism, extra) {
    return Object.assign({
      mechanism: mechanism,
      output_kind: mechanism === 'meme' ? 'meme_initiative' : 'initiative_reply',
      source: 'journal', available: true, data_state: 'ok',
      no_data_reasons: [], ready: true, ready_reason: '',
      last_check_ts: 1800000000, next_check_ts: 1800003600,
      next_check_basis: 'cooldown',
      random: { performed: true, outcome: 'draw', value: 0.07, hit: true,
                probability: 0.05, source: 'pseudorandom',
                selected_source: 'quantum', fallback: false, purpose: 'trigger' },
      conditions: { messages: 12, activity_ok: true },
      stages: mechanism === 'meme' ? { summary: 1, joke: 1 } : null,
      skip: null, skip_recorded: { code: 'cooldown_active', label: 'кулдаун',
                                   origin: 'journal' },
      cooldown: { scope: 'mechanism_own', own_seconds: 21600,
                  remaining_seconds: 0, basis: 'last_provider_call',
                  basis_ts: 1799999000 },
      quota: { scope: 'day', limit: 3, used: 1, remaining: 2, unlimited: false,
               limit_reached: false, available: true, next_reset: '2026-11-01' },
      publication: { available: true, coordination: 'ok', degraded: false,
                     conflict: false, conflict_state: 'clear', ok: true,
                     reason: '', reason_label: '', state: 'idle',
                     holder_kind: mechanism, claimed_by: '', other_kind: '',
                     other_age_seconds: null, interval_seconds: 600,
                     manual_priority_until: null, checked_at: 1800000000 },
      blocking: mechanism === 'meme' ? null : { blocked: [], warned: [] },
    }, extra || {});
  }
  const payload = {
    schema_version: 1, generated_at: 1800000000, chat_id: -100,
    text_initiative: block('text_initiative', {
      last_check_ts: null, next_check_ts: null, random: null,
      conditions: null, publication: null,
      cooldown: { scope: 'mechanism_own', own_seconds: null,
                  remaining_seconds: null, basis: 'no_prior_publication',
                  basis_ts: null },
      quota: { limit: null, used: null, remaining: null, unlimited: false,
               limit_reached: false, available: false },
      skip: { code: 'initiative_disabled', label: 'инициатива выключена',
              origin: 'gate' },
    }),
    meme: block('meme', {
      skip: null,
      random: { performed: false, outcome: 'no_draw', value: null, hit: null,
                probability: 1.0, source: '', selected_source: 'quantum',
                no_draw_reason: 'probability_one', purpose: 'trigger' },
    }),
    degraded: [],
  };
  const view = computed.memeDiagView.call({ memeDiag: payload });
  assert.strictEqual(view.text.mechanism, 'text_initiative');
  assert.strictEqual(view.meme.mechanism, 'meme');
  // Блоки не склеены: у текста «никогда» и нет данных, у мема — свои числа.
  assert.strictEqual(view.text.lastCheckText, 'никогда');
  assert.strictEqual(view.meme.lastCheckText !== 'никогда', true);
  assert.strictEqual(view.text.random, null);
  assert.strictEqual(view.meme.random.performed, false);
  assert.ok(view.meme.random.decisionLabel.indexOf('жеребьёвка не выполнялась') === 0);
  assert.strictEqual(view.text.skip.code, 'initiative_disabled');
  assert.strictEqual(view.meme.skip, null);
  // Законный ноль остатка кулдауна ≠ «неизвестно», у текста — «неизвестен».
  assert.strictEqual(view.meme.cooldown.remainingText, '0 с');
  assert.ok(view.meme.cooldown.basisLabel.indexOf('последнего вызова') > 0);
  assert.strictEqual(view.text.cooldown.remainingText, 'неизвестен');
  assert.strictEqual(view.text.cooldown.ownText,
                     'неизвестен (настройка не прочитана)');
  // Квота: неизвестный лимит — «неизвестен», не 0.
  assert.strictEqual(view.text.quota.limitText, 'неизвестен');
  assert.strictEqual(view.meme.quota.limitText, '3');
  // conditions {} / null = «нет данных» (rows = null), а не пустая строка.
  assert.strictEqual(view.text.conditionsRows, null);
  assert.ok(view.meme.conditionsRows.length === 2);
  // Конфликт только из publication; бронь не проверялась — так и сказано.
  assert.strictEqual(view.text.publication, null);
  assert.strictEqual(view.text.publicationConflictLabel, undefined);
  assert.strictEqual(view.meme.publication.conflict, false);
  assert.strictEqual(view.meme.publication.conflictLabel, 'конфликта нет');
  // Запись прошлого прохода отделена от текущей причины.
  assert.strictEqual(view.meme.skipRecorded.code, 'cooldown_active');
  assert.strictEqual(view.meme.skipRecorded.originLabel, 'журнал попыток');

  // Деградация координации → «координация недоступна», конфликт неизвестен.
  const degraded = computed.memeDiagView.call({ memeDiag: Object.assign(
    {}, payload, {
      degraded: ['meme'],
      meme: block('meme', {
        publication: { available: false, coordination: 'degraded',
                       degraded: true, degraded_reason: 'claim_absent',
                       conflict: null, conflict_state: 'unknown', ok: null,
                       state: '', holder_kind: 'meme', claimed_by: '',
                       checked_at: 1800000000 },
        skip: { code: 'schema_absent', label: 'схемы нет', origin: 'publication' },
        ready: false, ready_reason: 'schema_absent',
      }),
    }) });
  assert.strictEqual(degraded.meme.publication.degraded, true);
  assert.strictEqual(degraded.meme.publication.conflict, null);
  assert.strictEqual(degraded.meme.publication.conflictLabel,
                     'координация недоступна');
  assert.notStrictEqual(degraded.meme.publication.conflictLabel, 'конфликта нет');
  assert.deepStrictEqual(degraded.degraded, ['meme']);

  // Конфликт рисуется только когда его подтвердила бронь.
  const conflicted = computed.memeDiagView.call({ memeDiag: Object.assign(
    {}, payload, { meme: block('meme', {
      publication: Object.assign({}, payload.meme.publication, {
        conflict: true, conflict_state: 'conflict', ok: false,
        claimed_by: 'text_initiative', other_kind: 'meme',
        other_age_seconds: 30 }) }) }) });
  assert.strictEqual(conflicted.meme.publication.conflictLabel,
                     'конфликт: сейчас публикует другой механизм');
  assert.strictEqual(conflicted.meme.publication.claimedBy, 'text_initiative');

  // Записанный в payload `publication_conflict` сам конфликт не создаёт.
  const recorded = computed.memeDiagView.call({ memeDiag: Object.assign(
    {}, payload, { meme: block('meme', {
      skip_recorded: { code: 'publication_conflict',
                       label: 'конфликт публикаций', origin: 'payload_state' },
      publication: Object.assign({}, payload.meme.publication, {
        conflict: false, conflict_state: 'clear' }) }) }) });
  assert.strictEqual(recorded.meme.publication.conflict, false);
  assert.strictEqual(recorded.meme.skipRecorded.code, 'publication_conflict');

  // Пустой ответ целиком = «нет данных», а не нули.
  const empty = computed.memeDiagView.call({ memeDiag: {
    schema_version: 1, text_initiative: null, meme: null, degraded: [],
  } });
  assert.strictEqual(empty.text.isNoData, true);
  assert.strictEqual(empty.meme.isNoData, true);
  assert.strictEqual(empty.text.lastCheckText, 'никогда');
  assert.strictEqual(empty.text.ready, null);
  // Нет ответа вообще → null (карточка пишет «диагностика недоступна»).
  assert.strictEqual(computed.memeDiagView.call({ memeDiag: null }), null);
  assert.deepStrictEqual(computed.memeDiagBlocks.call({ memeDiag: null }), []);

  // Список блоков: ровно два отдельных элемента с ключами контракта.
  const blocks = computed.memeDiagBlocks.call({ memeDiag: payload });
  assert.deepStrictEqual(blocks.map(function (b) { return b.key; }),
                         ['text_initiative', 'meme']);
})();

// ── 8. Разметка карточки: реальные поля, числа, оба блока ────────────────
(function () {
  // Оба промпта — РЕАЛЬНЫЕ поля ввода (v-model на черновик), не пассивный текст.
  const textareas = CARD.match(/<textarea[\s\S]*?<\/textarea>/g) || [];
  assert.strictEqual(textareas.length, 2, 'в карточке ровно два поля промптов');
  const taJoke = textareas.filter(function (t) {
    return t.indexOf('data-meme-prompt-joke') >= 0;
  })[0];
  const taImage = textareas.filter(function (t) {
    return t.indexOf('data-meme-prompt-image') >= 0;
  })[0];
  assert.ok(taJoke, 'нет поля промпта прикола');
  assert.ok(taImage, 'нет поля шаблона картинки');
  assert.ok(taJoke.indexOf('v-model="memeDraft.prompt_joke"') >= 0,
    'поле прикола не связано с черновиком');
  assert.ok(taImage.indexOf('v-model="memeDraft.prompt_image"') >= 0,
    'поле шаблона не связано с черновиком');
  // Пассивный текст шаблона убран.
  assert.strictEqual(CARD.indexOf('data-meme-prompt-text'), -1);
  // Три числа §3 ТЗ.
  ['data-meme-limit-ceiling', 'data-meme-limit-template',
   'data-meme-limit-joke'].forEach(function (attr) {
    assert.ok(CARD.indexOf(attr) >= 0, 'нет узла ' + attr);
  });
  assert.ok(CARD.indexOf('Потолок итогового промпта') >= 0);
  assert.ok(CARD.indexOf('Длина шаблона картинки') >= 0);
  assert.ok(CARD.indexOf('Доступно для прикола') >= 0);
  // Устаревшая подпись «цель выжимки» больше не показывается.
  assert.strictEqual(CARD.indexOf('цель выжимки'), -1);
  assert.strictEqual(CARD.indexOf('считается ДО выжимки'), -1);
  // Диагностика прикола, стадии; ДВА блока механизмов живут в «Диагностике»
  // (P1 2026-11-03: полный debug — на своей вкладке, в карточке мемов его нет).
  assert.ok(CARD.indexOf('data-meme-speech') >= 0);
  assert.ok(CARD.indexOf('data-meme-attempt-stages') >= 0);
  assert.ok(INDEX.indexOf('data-meme-diag="') >= 0
            || INDEX.indexOf('data-meme-diag>') >= 0
            || INDEX.indexOf('data-meme-diag ') >= 0,
            'нет блока диагностики механизма');
  assert.ok(INDEX.indexOf('data-meme-diag-degraded') >= 0);
  assert.ok(INDEX.indexOf('координация недоступна') >= 0);
  assert.strictEqual(CARD.indexOf('data-meme-diag="'), -1,
    'полный блок диагностики не дублируется в карточке «Мемов»');
  // Ошибка 422 у поля (оба поля).
  assert.ok(CARD.indexOf('data-meme-prompt-error-joke') >= 0);
  assert.ok(CARD.indexOf('data-meme-prompt-error-image') >= 0);
  // Запросы: карточка читает оба источника.
  assert.ok(APP_JS_SRC.indexOf("'/api/initiative/meme-settings'") >= 0);
  assert.ok(APP_JS_SRC.indexOf("'/api/initiative/mechanism-diagnostics'") >= 0);
  // R17: тексты прикола/выжимки не выводятся и не запрашиваются отдельно.
  assert.strictEqual(CARD.indexOf('joke_text'), -1);
  assert.strictEqual(CARD.indexOf('summary_text'), -1);
})();

console.log('MEME-UI-FIELDS-OK');
