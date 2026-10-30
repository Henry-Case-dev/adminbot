'use strict';
/* EVOL-019/020/021/014 (Wave 4 UI) — JS-проекции витрин.
 *
 * Проверяется главное правило волны: витрина НЕ выдумывает «работает».
 *   * visionRecognitionView: 200 с неверной схемой/пустым содержимым →
 *     «не подтверждено»; зелёный статус — только при content_received +
 *     recognition_completed; платный вызов и покрытие медиа видны;
 *   * expPipelineView: 8 стадий в порядке СЕРВЕРА, подписи состояний
 *     серверные, ссылки на уроки — только при подтверждённых счётчиках;
 *   * episodeFeedView: смысловая лента + группа восстановления + честное
 *     пустое состояние с датой сборки;
 *   * memeSettingsView: квота «1 / 3», остаток/сброс/пояс, 0 = выключено,
 *     конкретная причина недоступности, отдельная ось от мастера модуля;
 *   * адресный переход «Открыть в памяти» (#/memory?episode=<id>).
 *
 * Запуск: node tests/js/evol_w4_diagnostics_ui_test.js → EVOL-W4-UI-OK
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
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const computed = captured.computed;
const methods = captured.methods;
for (const name of ['expPipelineView', 'visionRecognitionView',
                    'episodeFeedView', 'memeSettingsView']) {
  assert(computed && computed[name], 'computed.' + name + ' не найден');
}
for (const name of ['loadExperiencePipeline', 'toggleExpStage',
                    'runVisionRecognitionCheck', 'loadEpisodeFeed',
                    'loadEpisodeRecovery', 'toggleEpisodeRecovery',
                    'openEpisodeCard', 'openEpisodeInMemory',
                    'episodesApplyDeepLink', 'loadMemeSettings',
                    'saveMemeSettings', 'memeUnavailableLabel',
                    'memeStageLabel', 'memeSkipLabel',
                    'episodePeriodLabel']) {
  assert(methods && methods[name], 'methods.' + name + ' не найден');
}

// ── 1. EVOL-019: «не подтверждено» на 200 с неверной схемой ────────────────
(function () {
  assert.strictEqual(computed.visionRecognitionView.call({}), null);

  const broken = {
    state: 'schema_invalid', config_ok: true, provider_reachable: true,
    media_accepted: true, recognition_completed: false,
    content_received: false, content_sample: '', content_chars: 0,
    duration_ms: 12, model: 'm', provider: 'h', api_type: 'openai_compatible',
    source: 'dedicated', timestamp: '2026-10-31T00:00:00Z',
    terminal_reason: 'response_not_json',
    terminal_reason_label: 'Ответ провайдера не является JSON',
    http_class: 'http_200', paid_call: true, budget_note: 'платный',
    pipeline: { ready: false, reason: 'recognition_not_proven',
                label: 'Распознавание не подтверждено содержимым', note: 'n' },
    media_coverage: [{ type: 'photo_docs', label: 'фото', enabled: true,
                       tested_by_this_check: true, note: 'проверено' }],
    chat_id: null, fixture: {},
  };
  const view = computed.visionRecognitionView.call({ visionRecognition: broken });
  assert.strictEqual(view.ok, false);
  assert.ok(view.headline.indexOf('Не подтверждено') === 0, view.headline);
  const byKey = {};
  view.states.forEach(function (s) { byKey[s.key] = s; });
  assert.strictEqual(byKey.config.ok, true);
  assert.strictEqual(byKey.provider.value, 'да');
  assert.strictEqual(byKey.media.ok, true);
  assert.strictEqual(byKey.recognition.ok, false);
  assert.strictEqual(byKey.content.ok, false);
  assert.strictEqual(view.paidCall, true);
  assert.strictEqual(view.mediaCoverage[0].tested_by_this_check, true);
  assert.strictEqual(view.sample, '');

  const good = Object.assign({}, broken, {
    state: 'recognized', recognition_completed: true, content_received: true,
    content_sample: 'тёмный фон с панелью', content_chars: 42,
    terminal_reason: 'recognized', terminal_reason_label: 'Распознано',
    pipeline: { ready: true, reason: 'recognition_proven',
                label: 'Модуль включён', note: 'n' },
  });
  const okView = computed.visionRecognitionView.call({
    visionRecognition: good });
  assert.strictEqual(okView.ok, true);
  assert.ok(okView.headline.indexOf('подтверждено') >= 0);
  assert.strictEqual(okView.sample, 'тёмный фон с панелью');
  assert.strictEqual(okView.contentChars, 42);
})();

// ── 2. EVOL-020: 8 стадий, серверные подписи, ссылки по счётчикам ──────────
(function () {
  const stage = function (key, state, stateLabel, total, extra) {
    return Object.assign({
      stage: key, label: key, enabled: true, state: state,
      state_label: stateLabel, reason: '', reason_label: '',
      last_run_at: 1800000000, last_success_at: null, total: total,
      windows: { '24h': 0, '7d': total, '30d': total }, skip_reasons: [],
    }, extra || {});
  };
  const pipeline = {
    scope: 'chat:-100', chat_id: -100, generated_at: 1800000001,
    enabled: true, state: 'idle', state_label: 'Простаивает: проверка не была',
    reason: 'lessons_proposed_only', reason_label: 'Только кандидаты',
    cadence: { name: 'daily', seconds: 86400 },
    job: { active: false },
    order: ['observation', 'candidate', 'validation', 'activation',
            'retrieval', 'application', 'outcome', 'utility'],
    stages: {
      observation: stage('observation', 'idle', 'Простаивает', 0),
      candidate: stage('candidate', 'working', 'Работает', 2,
        { skip_reasons: [{ event: 'lesson_proposed',
                           reason_code: 'no_evidence',
                           last_ts: 1799999000, count_window: 2 }] }),
      validation: stage('validation', 'never_run', 'Не запускалось', 0),
      activation: stage('activation', 'never_run', 'Не запускалось', 0),
      retrieval: stage('retrieval', 'idle', 'Простаивает', 1,
        { excluded_reasons: [{ reason_code: 'retrieval_empty', count: 1 }] }),
      application: stage('application', 'idle', 'Простаивает', 2),
      outcome: stage('outcome', 'idle', 'Простаивает', 0),
      utility: stage('utility', 'never_run', 'Не запускалось', 0),
    },
    counters: {}, definitions: {}, reason_details: [],
  };
  const view = computed.expPipelineView.call({ expPipeline: pipeline });
  assert.strictEqual(view.stages.length, 8);
  assert.strictEqual(view.stages[0].key, 'observation');
  assert.strictEqual(view.stages[2].state, 'never_run');
  assert.strictEqual(view.stages[2].stateLabel, 'Не запускалось');
  // Подписи НЕ переписываются локально: «никогда» не становится «работает».
  assert.notStrictEqual(view.stages[2].stateLabel, 'Работает');
  assert.strictEqual(view.stages[1].w7, 2);
  assert.strictEqual(view.stages[1].skips.length, 1);
  assert.strictEqual(view.stages[1].skips[0].reason, 'no_evidence');
  // Ссылки — только там, где счётчики подтверждают наличие записей.
  assert.strictEqual(view.stages[2].links.length, 0);
  assert.strictEqual(view.stages[5].links.length, 1);
  assert.strictEqual(view.stages[4].links.length, 1);
  assert.strictEqual(view.stages[4].excluded[0].reason_code,
                     'retrieval_empty');
  assert.strictEqual(view.state, 'idle');
})();

// ── 3. EVOL-021: лента эпизодов и честное пустое состояние ─────────────────
(function () {
  assert.strictEqual(computed.episodeFeedView.call({}), null);
  const empty = computed.episodeFeedView.call({ episodeFeed: {
    state: 'empty', chat_id: -100, items: [], total_ready: 0,
    total_episodes: 3, requires_recovery: { count: 3, by_reason: [] },
    last_build: { last_build_at: 1799990000 },
    generated_at: 1800000000 } });
  assert.strictEqual(empty.items.length, 0);
  assert.strictEqual(empty.lastBuild.last_build_at, 1799990000);

  const feed = computed.episodeFeedView.call({ episodeFeed: {
    state: 'ok', chat_id: -100,
    items: [{
      episode_id: 'ep-1', chat_id: -100, title: 'Спор',
      what_happened: 'Обсуждали деплой',
      event_period: { start: 1799990000, end: 1799991000, known: true },
      discovered_at: 1799992000, discovery_label: 'новое',
      participants: { primary: ['1', '2'], others_count: 1, count: 3 },
      linked_messages: { count: 4, label: 'исходных сообщений: 4' },
      completeness: 'ready', completeness_label: 'полный',
      verification: { status: 'verified', label: 'История проверена' },
      story: { linked: true, title: 'Спор' },
      needs_recovery: false, recovery: null,
    }],
    total_ready: 1, total_episodes: 1,
    requires_recovery: { count: 0, by_reason: [] },
    last_build: null, generated_at: 1800000000 } });
  const it = feed.items[0];
  assert.strictEqual(it.id, 'ep-1');
  assert.strictEqual(it.happened, 'Обсуждали деплой');
  assert.strictEqual(it.linkedCount, 4);
  assert.strictEqual(it.othersCount, 1);
  assert.strictEqual(it.completenessLabel, 'полный');
  assert.strictEqual(it.needsRecovery, false);
})();

// ── 4. EVOL-014: квота, недоступность, отдельная ось ──────────────────────
(function () {
  const base = {
    chat_id: -100, generated_at: 1800000000,
    settings: { enabled: true, window_messages: 500, daily_limit: 3,
                cooldown_seconds: 21600, min_messages: 8,
                summarizer_model: '', quiet_hours: '', length_admin: null },
    availability: { available: true, reason: 'ok', initiative_enabled: true,
                    image: { available: true }, blocks_text_initiative: false },
    quota: { available: true, reason: 'ok', limit: 3, spent: 1, remaining: 2,
             day_bucket: '2026-10-31', timezone_name: 'Europe/Moscow',
             timezone_source: 'chat', next_reset: '2026-11-01T00:00:00+03:00' },
    analytics: { output_kind: 'meme_initiative', separate_from_initiative: true,
                 coverage: 'durable',
                 counters: { considered: 4, eligible: 2, summary: 2,
                             image_generation: 1, publish: 1, failed: 1,
                             skipped: 2 },
                 skip_reasons: { daily_quota_reached: 1, quiet_hours: 1 },
                 attempts: [] },
    day: { bucket: '2026-10-31', timezone_name: 'Europe/Moscow',
           timezone_source: 'chat', next_reset: '2026-11-01T00:00:00+03:00' },
    length_limit: { value: 1000, source: 'admin_setting', summary_target: 968,
                    known: true, prefix_chars: 31, candidates: [] },
    image_prefix: 'Создай мем с шрифтом импакт:',
    prompts: { image: { block_id: 'initiative.meme.image', text: 'шаблон',
                        source: 'factory', differs_from_factory: false,
                        factory_revision: 'fac-1', revision: 1 },
               summary: { block_id: 'initiative.meme.summary', text: 's',
                          differs_from_factory: false } },
    delivery: { output_kind: 'meme_initiative', blocks_text_initiative: false,
                publish_blocked_count: 1,
                skip_reasons: { publish_blocked: 1 },
                stages: ['considered', 'eligible', 'summary',
                         'image_generation', 'publish', 'failed', 'skipped'] },
    schema_present: true,
    defaults: { enabled: false, window_messages: 500, daily_limit: 3,
                cooldown_seconds: 21600, min_messages: 8,
                trigger_probability: 0.05 },
    master_key: 'flags.initiative_enabled',
    own_key: 'flags.meme_initiative_enabled',
  };
  const view = computed.memeSettingsView.call({ memeSettings: base });
  assert.strictEqual(view.quotaText, 'Генерации сегодня: 1 / 3');
  assert.strictEqual(view.remainingText, 'Осталось: 2');
  assert.strictEqual(view.timezone, 'Europe/Moscow');
  assert.strictEqual(view.resetAt, '2026-11-01T00:00:00+03:00');
  assert.strictEqual(view.counters.image_generation, 1);
  assert.strictEqual(view.skipRows[0].code, 'daily_quota_reached');
  assert.strictEqual(view.available, true);
  assert.strictEqual(view.quotaDisabled, false);
  assert.strictEqual(view.promptImage.differs_from_factory, false);
  assert.strictEqual(view.settings.daily_limit, 3);

  // Квота 0 = выключено (честная подпись, не «0 / 0»).
  const off = computed.memeSettingsView.call({ memeSettings: Object.assign(
    {}, base, {
      settings: Object.assign({}, base.settings, { daily_limit: 0 }),
      quota: { available: true, reason: 'daily_quota_reached', limit: 0,
               spent: 0, remaining: 0, timezone_name: 'UTC',
               next_reset: '2026-11-01T00:00:00+00:00' },
    }) });
  assert.strictEqual(off.quotaDisabled, true);
  assert.ok(off.quotaText.indexOf('выключено') >= 0, off.quotaText);

  // Недоступность: конкретная причина, а не «не работает».
  const unavailable = computed.memeSettingsView.call({ memeSettings:
    Object.assign({}, base, {
      availability: { available: false,
                      reason: 'image_provider_not_configured',
                      initiative_enabled: true, image: {} } }) });
  assert.strictEqual(unavailable.available, false);
  const label = methods.memeUnavailableLabel
    .call({}, unavailable.unavailableReason);
  assert.ok(label.indexOf('Image-провайдер не настроен') === 0, label);
  assert.strictEqual(methods.memeStageLabel.call({}, 'image_generation'),
                     'Генерация картинки');
  assert.strictEqual(methods.memeSkipLabel.call({}, 'quiet_hours'),
                     'тихие часы');
})();

// ── 5. Адресный переход «Открыть в памяти» ────────────────────────────────
(function () {
  const calls = [];
  const ctx = {
    episodeFocusId: '',
    route: '#/status',
    navigateTo: function (r) { calls.push(r); },
    $nextTick: function (fn) { fn(); },
    episodesApplyDeepLink: function () { calls.push('deep'); },
    openEpisodeCard: function (id) { calls.push('card:' + id); },
  };
  methods.openEpisodeInMemory.call(ctx, 'ep-9');
  assert.strictEqual(ctx.episodeFocusId, 'ep-9');
  assert.strictEqual(calls[0], '#/memory');
  assert.strictEqual(calls[1], 'deep');
  assert.strictEqual(calls[2], 'card:ep-9');

  // Ссылка читается из hash: ?episode=<id>.
  global.window.location.hash = '#/memory?episode=ep-42';
  const parsed = methods.episodesApplyDeepLink.call({
    episodeFocusId: '', episodeCard: null,
    openEpisodeCard: function (id) { calls.push('card:' + id); },
  });
  assert.strictEqual(parsed, 'ep-42');
  assert.ok(calls.indexOf('card:ep-42') >= 0);
  global.window.location.hash = '#/memory';
  assert.strictEqual(methods.episodesApplyDeepLink.call({
    episodeFocusId: 'x', episodeCard: null, openEpisodeCard() {},
  }), null);
})();

console.log('EVOL-W4-UI-OK');
