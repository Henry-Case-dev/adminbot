'use strict';
/* ═══ MOD-ACL-UX-01 M4B B3 — «Опыт»: компактная лента, 5 стадий, честные
 * состояния ═══════════════════════════════════════════════════════════════
 *
 * TEST-LIFECYCLE: CONTRACT owner=MAC-S7-FEED-01..04/MAC-AC-18/MAC-S6-3xx
 *
 * Проверяется РЕАЛЬНЫЙ код `web/app.js`, `web/index.html`, `web/static/app.css`:
 *   1) MAC-S7-FEED-04: на «Статусе» 5 КЛЮЧЕВЫХ стадий (порядок сервера),
 *      ссылка «Развернуть цепочку» → #/modules/experience; API — 8 стадий;
 *      полная 8-стадийная цепочка остаётся в аналитике «Опыта»;
 *   2) MAC-S7-FEED-01/03: одна лента в существующей карточке, фильтр
 *      Всё/Опыт/Уроки, тот же контроллер v-sfeed, окно 144 px (112–160),
 *      без горизонтального скролла; строки без дублей;
 *   3) MAC-S7-FEED-02/AC-18: поля строк обоих типов; «действует» — ТОЛЬКО
 *      серверное applied===true; unverified/гипотеза не становятся активными;
 *      опыт ≠ урок; backlog/причина нуля — серверными полями;
 *   4) MAC-S15-05/07/11: недостаток доказательств ≠ молчание worker; чужой
 *      урок не активен; 503 → unknown + последний успешный ответ, не нули;
 *   5) MAC-S6-308/MEM-01/REST-01/311/310: 5 индикаторов памяти + техсчётчики
 *      в <details>; «последний успех» QRNG честный; один экземпляр блоков;
 *      порядок сон → последний вызов → бюджеты;
 *   6) мутации: «всегда active» и «нулевой опыт при 503» ловятся.
 *
 * Запуск: node tests/js/m4b3_experience_feed_test.js
 *         → MOD-ACL-UX-M4B3-EXPERIENCE-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

function sliceBetween(src, startNeedle, endNeedle) {
  const at = src.indexOf(startNeedle);
  assert.ok(at > 0, 'не найден якорь: ' + startNeedle);
  const end = src.indexOf(endNeedle, at + startNeedle.length);
  assert.ok(end > at, 'не найден конец: ' + endNeedle);
  return src.slice(at, end);
}

/* ── 0. Разметка: стадии и полная цепочка ───────────────────────────────── */
{
  const statusSeg = INDEX.slice(INDEX.indexOf("activeTab === 'status'"));
  const block = sliceBetween(statusSeg, 'data-experience-pipeline',
    'data-experience-windows');
  assert.ok(block.indexOf('5 ключевых стадий') > 0,
    'MAC-S7-FEED-04: «Статус» называет 5 ключевых стадий');
  assert.ok(block.indexOf('v-for="st in expPipelineView.keyStages"') > 0,
    'MAC-S7-FEED-04: рендерятся 5 ключевых стадий, а не 8');
  assert.strictEqual(block.indexOf('v-for="st in expPipelineView.stages"'), -1,
    'MAC-S7-FEED-04: полный список 8 стадий на «Статусе» не рендерится');
  assert.ok(block.indexOf('data-experience-pipeline-expand') > 0
    && block.indexOf('Развернуть цепочку') > 0,
    'MAC-S7-FEED-04: ссылка «Развернуть цепочку» есть');
  assert.ok(block.indexOf(':href="expPipelineView.fullRoute"') > 0,
    'MAC-S7-FEED-04: ссылка ведёт на аналитику «Опыта»');
  // Аналитика «Опыта» несёт ПОЛНУЮ цепочку из той же проекции.
  const chain = sliceBetween(INDEX, 'data-experience-chain="full"',
    'data-module-history');
  assert.ok(chain.indexOf('v-for="st in expPipelineView.stages"') > 0,
    'MAC-S7-FEED-04: в аналитике — все стадии сервера');
  assert.ok(chain.indexOf('data-experience-chain-stage') > 0,
    'MAC-S7-FEED-04: стадии аналитики адресуемы в DOM');
  assert.strictEqual(JS.split("'/api/experience/pipeline'").length - 1, 1,
    'MAC-S7-FEED-04: второго API цепочки нет');
}

/* ── 1. CSS/разметка ленты ──────────────────────────────────────────────── */
{
  const expCard = sliceBetween(INDEX, '<health-glass-surface class="card p-4 sg-12" data-experience',
    'id="status-logs"');
  assert.ok(expCard.indexOf('data-experience-feed') > 0,
    'MAC-S7-FEED-01: лента живёт в существующей карточке «Опыт»');
  assert.ok(expCard.indexOf('v-sfeed="statusRecordOpen"') > 0,
    'MAC-S7-FEED-03: тот же контроллер SFeed, окно записи как modal-гейт');
  assert.ok(expCard.indexOf('data-experience-sfeed') > 0
    && expCard.indexOf('data-sfeed-viewport') > 0,
    'MAC-S7-FEED-01: окно реальной прокрутки SFeed');
  assert.ok(expCard.indexOf('experienceTrackOptions') > 0
    && expCard.indexOf('data-experience-track') > 0,
    'MAC-S7-FEED-01: фильтр дорожек Всё / Опыт / Уроки');
  assert.ok(expCard.indexOf('setExperienceFeedTrack') > 0,
    'MAC-S7-FEED-01: фильтр переключает дорожку без нового запроса-состояния');
  // Высота окна — в требуемом диапазоне 112–160 px.
  const m = /\.sfeed-viewport--experience \{\s*--sfeed-h:\s*(\d+)px/.exec(CSS);
  assert.ok(m, 'MAC-S7-FEED-01: вариант окна ленты опыта объявлен');
  const h = Number(m[1]);
  assert.ok(h >= 112 && h <= 160, 'MAC-S7-FEED-01: высота 112–160 (получено '
    + h + ')');
  assert.ok(/\.sfeed-viewport \{[\s\S]{0,400}overflow-x: hidden/.test(CSS),
    'MAC-S7-FEED-01: горизонтального скролла нет');
  // Пустое состояние — честный текст, а не пустой контейнер.
  assert.ok(expCard.indexOf('data-experience-feed-empty') > 0);
}

/* ── 2. Реальный код app.js ─────────────────────────────────────────────── */
global.Vue = {
  createApp: function (opts) {
    global.__opts = opts;
    return { component() {}, provide() {}, use() {}, mount() {},
             directive() {} };
  },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  matchMedia: function () { return { matches: false, addEventListener() {} }; },
  innerWidth: 1440, innerHeight: 900,
};
global.document = {
  documentElement: {
    setAttribute() {}, getAttribute() { return null; },
    classList: { toggle() {}, contains() { return false; } },
    style: { setProperty() {}, removeProperty() {} },
  },
  addEventListener() {}, getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {}, remove() {},
      getContext() { return null; },
    };
  },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
  querySelector() { return null; }, querySelectorAll() { return []; },
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
global.localStorage = {
  _s: {},
  getItem(k) {
    return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null;
  },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
let fetchCalls = 0;
global.fetch = async function () { fetchCalls += 1; throw new Error('no fetch'); };

require(path.join(ROOT, 'web', 'app.js'));
const opts = global.__opts;
assert(opts, 'Vue.createApp должен быть вызван');
const computed = opts.computed || {};
const methods = opts.methods || {};
const data = opts.data.call({});

['expPipelineView', 'experienceFeedRows', 'experienceRows',
 'experienceLessonRows', 'memoryIndicators', 'randomLastSuccess',
 'statusUnknownView', 'expEmptyState'].forEach(function (name) {
  assert.strictEqual(typeof computed[name], 'function', 'computed ' + name);
});
['loadExperienceLessons', 'setExperienceFeedTrack', 'openExperienceFeedRow',
 'refreshExperienceFeed', 'experienceRowAria', 'experienceRowBadgeClass',
 'experienceOutcomeLabel'].forEach(function (name) {
  assert.strictEqual(typeof methods[name], 'function', 'method ' + name);
});
assert.strictEqual(data.experienceFeedTrack, 'all',
  'MAC-S7-FEED-01: по умолчанию показаны обе дорожки');
assert.strictEqual(data.statusLastOkAt, 0,
  'MAC-S15-11: последний успешный ответ экрана — явное состояние');

/* ── 3. 5 ключевых стадий (порядок сервера) и 8 у API ───────────────────── */
{
  const stage = function (key) {
    return {
      key: key, label: 'L:' + key, state: 'idle',
      state_label: 'Простаивает', enabled: true, reason: '', reason_label: '',
      last_run_at: null, last_success_at: null, windows: { '24h': 1, '7d': 2,
        '30d': 3 }, total: 4, skip_reasons: [], excluded_reasons: [], total_n: 4,
    };
  };
  const order = ['observation', 'candidate', 'validation', 'activation',
                 'retrieval', 'application', 'outcome', 'utility'];
  const p = {
    scope: 'global', chat_id: null, generated_at: 1791900000, enabled: true,
    state: 'idle', state_label: 'Простаивает', reason: '', reason_label: '',
    cadence: {}, job: {}, order: order,
    stages: order.reduce(function (acc, k) { acc[k] = stage(k); return acc; },
      {}),
    counters: {}, definitions: {}, reason_details: [],
  };
  const view = computed.expPipelineView.call({ expPipeline: p });
  assert.strictEqual(view.stages.length, 8, 'API-проекция: все 8 стадий');
  assert.strictEqual(view.totalStages, 8);
  assert.deepStrictEqual(view.keyStages.map(function (s) { return s.key; }),
    ['observation', 'candidate', 'validation', 'application', 'outcome'],
    'MAC-S7-FEED-04: ровно 5 ключевых стадий в порядке сервера');
  assert.strictEqual(view.fullRoute, '#/modules/experience',
    'MAC-S7-FEED-04: ссылка на аналитику «Опыта»');
  // Порядок ключевых стадий — из ответа сервера, а не из литерала UI.
  const reordered = Object.assign({}, p, {
    order: ['observation', 'candidate', 'validation', 'outcome',
            'application', 'retrieval', 'activation', 'utility'],
  });
  const view2 = computed.expPipelineView.call({ expPipeline: reordered });
  assert.deepStrictEqual(view2.keyStages.map(function (s) { return s.key; }),
    ['observation', 'candidate', 'validation', 'outcome', 'application'],
    'MAC-S7-FEED-04: UI не навязывает свой порядок стадий');
  // Явные метки состояний — серверные (не «работает» по умолчанию).
  assert.ok(view.keyStages.every(function (s) {
    return s.stateLabel === 'Простаивает';
  }));
}

/* ── 4. Строки ленты: опыт ≠ урок, честные статусы ──────────────────────── */
function lesson(over) {
  return Object.assign({
    lesson_id: 'L1', version: 2, type: 'tool_usage', scope: 'chat',
    scope_chat_id: -100, recommendation: 'Сначала проверять тип файла',
    status: 'active', applied: true, unverified: false, historical: false,
    grounds_count: 3, applications_count: 2,
    created_at: 1791800000, updated_at: 1791850000,
  }, over || {});
}
function applied(over) {
  return Object.assign({
    kind: 'applied', ts: 1791900000, lesson_id: 'L1', type: 'tool_usage',
    scope: 'chat', summary: 'Повторная попытка после сбоя', status: 'applied',
    outcome: 'success', label: 'урок применён',
  }, over || {});
}
{
const vmBase = {
  statusData: { experience: { enabled: true, state: 'implemented',
    items: [applied(), applied({ ts: 1791800000, outcome: 'unknown',
      lesson_id: 'L2' }),
      { kind: 'activated', ts: 1791700000, lesson_id: 'L3', status: 'active',
        summary: 'правило', scope: 'chat' }] } },
  experienceLessons: [
    lesson(),
    lesson({ lesson_id: 'L4', status: 'suspended', applied: false,
      updated_at: 1791750000, recommendation: 'Не отправлять ночью' }),
    // unverified — НЕ активное правило
    lesson({ lesson_id: 'L5', applied: false, unverified: true,
      updated_at: 1791700000 }),
    // гипотетический источник (llm_hypothesis) не становится активным
    lesson({ lesson_id: 'L6', applied: true, llm_hypothesis: true,
      updated_at: 1791600000 }),
    // историческое правило
    lesson({ lesson_id: 'L7', applied: false, historical: true,
      updated_at: 1791500000 }),
    // чужой чат — не виден (MAC-S15-07)
    lesson({ lesson_id: 'L8', scope_chat_id: -200, updated_at: 1791900000 }),
    // глобальное правило — видно в любом чате
    lesson({ lesson_id: 'L9', scope: 'global', scope_chat_id: null,
      updated_at: 1791400000 }),
  ],
  activeChatId: -100,
  experienceFeedTrack: 'all',
  isGlobalAdmin: true,
};
const ctxBase = Object.assign(Object.create(methods), vmBase);
const expRows = computed.experienceRows.call(ctxBase);
assert.strictEqual(expRows.length, 2,
  'MAC-AC-18: дорожка «Опыт» — только реальные применения (kind=applied)');
assert.strictEqual(expRows[0].ts, 1791900000, 'свежие сверху');
assert.strictEqual(expRows[0].outcome, 'success');
assert.ok(expRows[0].scope.indexOf('чат') === 0,
  'scope строки опыта — человеческая подпись');
const lessonRows = computed.experienceLessonRows.call(ctxBase);
assert.deepStrictEqual(lessonRows.map(function (r) { return r.id; }),
  ['L1', 'L4', 'L5', 'L6', 'L7', 'L9'],
  'MAC-S15-07: чужой урок (L8) в этом чате не показывается');
const byId = {};
lessonRows.forEach(function (r) { byId[r.id] = r; });
assert.strictEqual(byId.L1.status, 'действует',
  'MAC-S7-FEED-02: «действует» — только серверное applied===true');
assert.strictEqual(byId.L1.applied, true);
assert.strictEqual(byId.L4.status, 'приостановлен');
assert.strictEqual(byId.L5.status, 'не проверен',
  'MAC-S7-FEED-02: unverified не показан действующим правилом');
assert.strictEqual(byId.L5.applied, false);
assert.ok(byId.L6.status.indexOf('гипотеза') === 0,
  'MAC-S7-FEED-02: llm_hypothesis не получает активный бейдж');
assert.strictEqual(byId.L6.applied, false);
assert.strictEqual(byId.L7.status, 'исторический');
assert.strictEqual(byId.L9.scope, 'глобально');
assert.strictEqual(byId.L1.grounds, 3,
  'MAC-S7-FEED-02: число подтверждённых оснований');
assert.strictEqual(byId.L1.applications, 2);
assert.strictEqual(methods.experienceRowBadgeClass.call({}, byId.L1), 'badge-ok');
assert.strictEqual(methods.experienceRowBadgeClass.call({}, byId.L5),
  'badge-muted', 'неактивное правило — не зелёный бейдж');
// Мутация «всегда active» ловится: applied=false при unverified.
const mutated = computed.experienceLessonRows.call(Object.assign({}, vmBase, {
  experienceLessons: [lesson({ lesson_id: 'M1', applied: false,
    unverified: true })],
}));
assert.strictEqual(mutated[0].status, 'не проверен',
  'мутация «всегда active» не проходит');
// a11y/поля строк опыта.
const aria = methods.experienceRowAria.call({
  _shortText(s, n) { return String(s).slice(0, n); },
  statusRowTitle(ts, meaning) { return meaning + ': ' + ts; },
}, expRows[0]);
assert.ok(aria.indexOf('Опыт') === 0, 'a11y: тип строки');
assert.ok(aria.indexOf('область:') > 0 && aria.indexOf('время:') > 0,
  'a11y: scope и время');
// Дубли при обновлении не появляются (ключ строки стабилен).
const merged = computed.experienceFeedRows.call(Object.assign({}, vmBase, {
  experienceRows: [expRows[0], expRows[0]],
  experienceLessonRows: [byId.L1, byId.L1],
}));
assert.strictEqual(merged.length, 2, 'MAC-S7-FEED-03: строки без дублей');
const counts = computed.experienceFeedCounts.call(Object.assign({}, vmBase, {
  experienceRows: expRows, experienceLessonRows: lessonRows,
}));
assert.deepStrictEqual(counts, { all: 8, experience: 2, lesson: 6 });
// Фильтр: «Уроки» показывает только правила.
const onlyLessons = computed.experienceFeedRows.call(Object.assign({}, vmBase, {
  experienceFeedTrack: 'lesson', experienceRows: expRows,
  experienceLessonRows: lessonRows,
}));
assert.ok(onlyLessons.every(function (r) { return r.track === 'lesson'; }));
// Пустой урок без даты: честная подпись, не выдуманное «сейчас».
const noDate = computed.experienceLessonRows.call(Object.assign({}, vmBase, {
  experienceLessons: [lesson({ lesson_id: 'N1', created_at: null,
    updated_at: null })],
}));
assert.strictEqual(noDate[0].ts, null, 'нет даты — null, не 0');
assert.strictEqual(methods.experienceOutcomeLabel.call({},
  { outcome: 'unknown' }), 'неизвестен (не выдумывается)');
}

/* ── 5. Клик по строке — существующее окно записи, без записи на отрисовку */
{
  const calls = [];
  const ctx = {
    openStatusRecord(source, item, ev) { calls.push({ source, item, ev }); },
  };
  const raw = applied();
  methods.openExperienceFeedRow.call(ctx, {
    track: 'experience', status: 'применено', scope: 'чат -100', raw,
  }, { tag: 'ev' });
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].source, 'experience');
  assert.strictEqual(calls[0].item.summary, raw.summary);
  assert.strictEqual(calls[0].item._ui_status, 'применено');
  methods.openExperienceFeedRow.call(ctx, {
    track: 'lesson', status: 'действует', scope: 'чат -100',
    raw: lesson(),
  }, null);
  assert.strictEqual(calls[1].source, 'lesson');
  assert.strictEqual(calls[1].item.recommendation, 'Сначала проверять тип файла');
  assert.strictEqual(calls[1].item._ui_status, 'действует');
  // Ни один путь отрисовки/фильтра не делает POST/PUT.
  const loadSrc = methods.loadExperienceLessons.toString()
    + methods.refreshExperienceFeed.toString()
    + methods.setExperienceFeedTrack.toString();
  assert.strictEqual(/method:\s*'POST'|method:\s*'PUT'|method:\s*'DELETE'/
    .test(loadSrc), false, 'MAC-S7-FEED-03: лента ничего не пишет');
  assert.ok(loadSrc.indexOf('/api/memory/lessons') > 0,
    'MAC-S7-FEED-01: дорожка уроков — существующий endpoint');
  assert.strictEqual(JS.indexOf('/api/memory/lessons/feed'), -1,
    'MAC-S7-FEED-01: второго эндпоинта ленты нет');
  // Тот же существующий путь используют «Память» и лента — один контракт.
  assert.ok(JS.split("'/api/memory/lessons'").length - 1 >= 1);
  // Запрос уроков scoped активным чатом и read-only.
  assert.ok(loadSrc.indexOf('chat_id=') > 0);
}

/* ── 6. SFeed: ядро не изменено, окно — реальный вертикальный скролл ────── */
{
  assert.ok(JS.indexOf("app.directive('sfeed'") > 0,
    'MAC-S7-FEED-03: директива sfeed — общий контроллер');
  const core = sliceBetween(JS, 'function step(prev, dtMs) {',
    'var viewports = [];');
  assert.ok(core.indexOf('s.moving = Math.abs(s.y - before) > 0.001') > 0,
    'MAC-S7-FEED-03: ядро шага движения не переписано');
  assert.ok(/\.sfeed-viewport \{[\s\S]{0,700}overflow-y: auto/.test(CSS),
    'MAC-S7-FEED-03: окно ленты — вертикальная прокрутка');
  assert.ok(CSS.indexOf('.ribbon-track.sfeed-track { animation: none !important; }') > 0,
    'MAC-S7-FEED-03: legacy-marquee отключён (ручной скролл не конкурирует)');
}

/* ── 7. MAC-S15-05: доказательства ≠ молчание worker ────────────────────── */
{
  const state = function (ctx) { return computed.expEmptyState.call(ctx); };
  // (a) 1000 эпизодов, 0 кандидатов, отклонения/дубли есть, backlog пуст.
  const a = state({
    expWindow24h: { available: true, enabled: true,
      applications: { total: 0 } },
    intelFunnels: { experience: {
      job: { status: 'completed', counters: {
        semantic_scanned: 1000, semantic_extracted: 0,
        semantic_candidates: 0, semantic_rejected: 40,
        semantic_duplicates: 12, semantic_llm_unavailable: 0 } },
      semantic_lag: { watermark: 900, pending: 0 },
    } },
  });
  assert.strictEqual(a.kind, 'evidence');
  assert.ok(a.text.indexOf('недостаточно доказательств') >= 0
    && a.text.indexOf('отклонено: 40') >= 0,
    'MAC-S15-05(a): недостаток доказательств назван, а не «нет опыта»');
  assert.ok(a.text.indexOf('нулев') === -1);
  // (b) backlog > 0, задача упала → техническое молчание worker.
  const b = state({
    expWindow24h: { available: true, enabled: true, applications: { total: 0 } },
    intelFunnels: { experience: {
      job: { status: 'failed', reason_code: 'llm_timeout', counters: {
        semantic_scanned: 1000, semantic_extracted: 0,
        semantic_candidates: 0, semantic_rejected: 0 } },
      semantic_lag: { watermark: 900, pending: 250 },
    } },
  });
  assert.strictEqual(b.kind, 'worker');
  assert.ok(b.text.indexOf('semantic backlog 250') >= 0
    && b.text.indexOf('worker') >= 0
    && b.text.indexOf('llm_timeout') >= 0,
    'MAC-S15-05(b): backlog+worker — техническая причина, не доказательства');
  // (b2) backlog есть, задачи нет вовсе.
  const b2 = state({
    expWindow24h: { available: true, enabled: true },
    intelFunnels: { experience: { job: null,
      semantic_lag: { pending: 7 } } },
  });
  assert.strictEqual(b2.kind, 'worker');
  assert.ok(b2.text.indexOf('задача не создана') > 0);
  // (c) null ≠ []: нет ответа ≠ измеренный ноль.
  const c = state({ expWindow24h: null, intelFunnels: null });
  assert.strictEqual(c.kind, 'unknown');
  assert.ok(c.text.indexOf('durable-задачи нет') > 0);
  assert.strictEqual(state({ expWindow24h: { available: true, enabled: true,
    applications: { total: 0 } }, intelFunnels: { experience: {
    job: { status: 'completed', counters: { semantic_scanned: 0 } },
    semantic_lag: { watermark: 15000, pending: 0 } } } }).kind, 'unknown');
  // Выключено — честная отдельная причина.
  assert.strictEqual(state({ expWindow24h: { available: true, enabled: false },
    intelFunnels: null }).kind, 'disabled');
  // Пусто и без причины — kind none (никакого «работает»).
  assert.strictEqual(state({ expWindow24h: { available: true, enabled: true,
    applications: { total: 2 } }, intelFunnels: { experience: {
    job: { status: 'completed', counters: { semantic_scanned: 500,
      semantic_extracted: 5, semantic_candidates: 3 } },
    semantic_lag: { pending: 0 } } } }).kind, 'none');
}

/* ── 8. MAC-S15-07/11: 503 → unknown + последний успешный ответ ─────────── */
{
  const ctx = {
    statusData: null, statusError: 'Не удалось получить статус сервера (HTTP 503).',
    statusLastOkAt: 1791890000, experienceFeedTrack: 'all',
    experienceLessonsLoaded: false, experienceLessonsError: '',
  };
  ctx.statusUnknownView = computed.statusUnknownView.call(ctx);
  const unknown = computed.statusUnknownView.call(ctx);
  assert.strictEqual(unknown.unknown, true);
  assert.ok(unknown.lastOkText.indexOf('последний успешный ответ экрана') === 0,
    'MAC-S15-11: подпись времени честная');
  assert.ok(unknown.lastOkText.indexOf('503') === -1);
  const reason = computed.experienceFeedEmptyReason.call(ctx);
  assert.ok(reason.indexOf('неизвестно') === 0
    && reason.indexOf('503') > 0
    && reason.indexOf('последний успешный ответ экрана') > 0,
    'MAC-S15-11: 503 не превращается в «нулевой опыт»');
  assert.ok(reason.indexOf('записей нет') === -1);
  const title = computed.experienceFeedEmptyTitle.call(ctx);
  assert.strictEqual(title, 'Состояние опыта неизвестно');
  // Уроки 503 — честная причина, не «уроков нет».
  const lctx = Object.assign({}, ctx, {
    statusData: { experience: { enabled: true, items: [] } },
    statusError: null, experienceLessonsError: 'HTTP 503',
    experienceFeedTrack: 'lesson',
  });
  lctx.statusUnknownView = computed.statusUnknownView.call(lctx);
  assert.ok(computed.experienceFeedEmptyReason.call(lctx)
    .indexOf('уроки недоступны (HTTP 503)') >= 0);
  // Локальное время последнего успеха не подменяется серверным generated_at.
  assert.strictEqual(methods.loadStatus.toString().indexOf('statusLastOkAt') > 0,
    true, 'MAC-S15-11: успешный ответ фиксирует время');
}

/* ── 8b. B3-R1-01: «Уроков пока нет» — только после успешного пустого ──── */
{
  const title = function (ctx) {
    return computed.experienceFeedEmptyTitle.call(ctx);
  };
  const kindOf = function (ctx) {
    return computed.experienceFeedEmptyKind.call(ctx);
  };
  const reason = function (ctx) {
    return computed.experienceFeedEmptyReason.call(ctx);
  };
  const base = {
    statusData: { experience: { enabled: true, items: [] } },
    statusError: null, experienceFeedTrack: 'lesson',
    experienceLessons: [], experienceLessonsLoaded: false,
    experienceLessonsError: '', experienceLessonsBusy: false,
    experienceLessonsAt: 0,
    statusUnknownView: { unknown: false, error: '', lastOkText: '' },
    expEmptyReason: '',
  };
  const withAt = Object.assign({}, base, { experienceLessonsAt: 1791890000000 });

  // (a) 503/недоступность: заголовок НЕ утверждает «нет уроков»; причина
  // несёт ошибку и время последнего успешного ответа (или его отсутствие).
  const unavailable = Object.assign({}, withAt, {
    experienceLessonsError: 'HTTP 503',
  });
  assert.strictEqual(kindOf(unavailable), 'unavailable');
  assert.strictEqual(title(unavailable), 'Состояние уроков неизвестно');
  assert.notStrictEqual(title(unavailable), 'Уроков пока нет');
  const reason503 = reason(unavailable);
  assert.ok(reason503.indexOf('уроки недоступны (HTTP 503)') >= 0,
    'B3-R1-01: причина называет ошибку');
  assert.ok(reason503.indexOf('последний успешный ответ ленты уроков:') >= 0,
    'B3-R1-01: время последнего успешного ответа выводится');
  assert.ok(reason503.indexOf('это не «уроков нет»') >= 0,
    'B3-R1-01: причина прямо отрицает «уроков нет»');
  const neverOk = Object.assign({}, base, {
    experienceLessonsError: 'HTTP 503',
  });
  assert.ok(reason(neverOk).indexOf(
    'успешных ответов ленты уроков ещё не было') >= 0,
  'B3-R1-01: без успехов — честная подпись, не выдуманное время');

  // (b) загрузка (busy, данных ещё нет): «загружаются», не «нет уроков».
  const loading = Object.assign({}, base, { experienceLessonsBusy: true });
  assert.strictEqual(kindOf(loading), 'loading');
  assert.strictEqual(title(loading), 'Уроки загружаются…');
  assert.ok(reason(loading).indexOf('идёт запрос ленты уроков') >= 0);
  assert.ok(reason(loading).indexOf('успешных ответов ленты уроков ещё не было')
    >= 0);

  // (c) успешный ПУСТОЙ ответ: только здесь «Уроков пока нет».
  const emptyOk = Object.assign({}, base, { experienceLessonsLoaded: true });
  assert.strictEqual(kindOf(emptyOk), 'empty');
  assert.strictEqual(title(emptyOk), 'Уроков пока нет');
  assert.strictEqual(reason(emptyOk),
    'активных или проверенных уроков нет — это не ошибка');

  // (d) дорожка ещё не запрашивалась: честное «не загружались».
  assert.strictEqual(kindOf(base), 'idle');
  assert.strictEqual(title(base), 'Уроки ещё не загружались');
  assert.ok(reason(base).indexOf('лента уроков ещё не запрашивалась') >= 0);

  // (e) «Всё»: недоступность уроков — «состояние ленты неизвестно», не
  // «записей нет»; и последний успех всё равно называется.
  const allUnavailable = Object.assign({}, withAt, {
    experienceFeedTrack: 'all', experienceLessonsError: 'HTTP 503',
  });
  assert.strictEqual(kindOf(allUnavailable), 'partial_unavailable');
  assert.strictEqual(title(allUnavailable), 'Состояние ленты неизвестно');
  assert.ok(reason(allUnavailable).indexOf(
    'последний успешный ответ ленты уроков:') >= 0);

  // (f) глобальный 503 (status) остаётся «Состояние опыта неизвестно».
  const statusFail = Object.assign({}, base, {
    statusData: null, statusError: 'HTTP 503',
    statusUnknownView: { unknown: true, error: 'HTTP 503',
      lastOkText: 'последний успешный ответ экрана: T' },
  });
  assert.strictEqual(kindOf(statusFail), 'unknown');
  assert.strictEqual(title(statusFail), 'Состояние опыта неизвестно');

  // Мутация: подставить «Уроков пока нет» при ошибке нельзя.
  assert.notStrictEqual(title(unavailable), title(emptyOk));
  assert.strictEqual(title(unavailable) === 'Уроков пока нет', false);
}

/* ── 9. MAC-S6-REST-01: «последний успех» QRNG без выдумок ──────────────── */
{
  const mk = function (act) {
    return computed.randomLastSuccess.call({
      randomActivityView: act, fmtTs(ts) { return 'T' + ts; },
    });
  };
  const withBatch = mk({ ready: true, lastBatch: { created_at: 1791900000,
    length: 8, provider_id: 'anu' }, fallbackAt: 1791800000,
    fallbackReasonLabel: 'провайдер недоступен' });
  assert.strictEqual(withBatch.kind, 'batch');
  assert.strictEqual(withBatch.label, 'последний квантовый батч');
  assert.strictEqual(withBatch.text, 'T1791900000');
  const fallbackOnly = mk({ ready: true, lastBatch: null,
    fallbackAt: 1791800000, fallbackReasonLabel: 'провайдер недоступен' });
  assert.strictEqual(fallbackOnly.kind, 'fallback');
  assert.strictEqual(fallbackOnly.label, 'последний откат');
  assert.strictEqual(fallbackOnly.label.indexOf('успех'), -1,
    'MAC-S6-REST-01: при откате слово «успех» не показывается');
  assert.strictEqual(fallbackOnly.text.indexOf('успех'), -1);
  const none = mk({ ready: true, lastBatch: null, fallbackAt: null });
  assert.strictEqual(none.kind, 'none');
  assert.strictEqual(none.text, '—', 'MAC-S6-REST-01: нет батча → «—»');
  const notReady = mk(null);
  assert.strictEqual(notReady.ready, false);
  // Детали MCA-10a/10b не удалены; добавлена ссылка в «Случайность».
  const card = sliceBetween(INDEX, 'data-random-source', 'data-quantum-ritm');
  assert.ok(card.indexOf('data-random-details') > 0
    && card.indexOf('data-random-uses') > 0,
    'MAC-S6-REST-01: data-random-details/uses (MCA-10a/10b) сохранены');
  assert.ok(card.indexOf('data-random-last-success') > 0
    && card.indexOf('data-random-details-link') > 0,
    'MAC-S6-REST-01: «последний успех» и ссылка на детали');
  assert.ok(card.indexOf('href="#/modules/random"') > 0);
}

/* ── 10. MAC-S6-308/MEM-01: индикаторы памяти ──────────────────────────── */
{
  const htmlMem = sliceBetween(INDEX, 'data-memory-indicators', 'data-memory-tech');
  assert.ok(htmlMem.indexOf('v-for="ind in memoryIndicators"') > 0);
  assert.ok(htmlMem.indexOf('<details') > 0,
    'MAC-S6-308: раскладка просроченного — в <details>');
  assert.ok(htmlMem.indexOf('data-memory-link') > 0,
    'MAC-S6-308: ссылки к причинам/истории');
  const techAt = INDEX.indexOf('data-memory-tech');
  const techOpen = INDEX.lastIndexOf('<details', techAt);
  assert.ok(techOpen > 0 && (techAt - techOpen) < 160,
    'MAC-S6-308: техсчётчики в <details>');
  assert.ok(techOpen > INDEX.indexOf('data-memory-indicators'),
    'MAC-S6-308: теха подробности — отдельный <details> памяти');
  const tiles = computed.memoryIndicators.call({
    expiredOverview: { available: true, facts_confirmed: 0,
      facts_last_24h: 0, facts_last_7d: 0, needs_recheck: 0,
      expired_total: 0, facts_last_created_at: null },
    memoryHealth: { beliefs_active: 0, last_decay_at: 1791000000 },
    fmtTs(ts) { return 'T' + ts; },
  });
  assert.strictEqual(tiles.length, 5);
  assert.strictEqual(tiles[0].value, '0',
    'MAC-S6-MEM-01: измеренный ноль — 0, а не «неизвестно»');
  assert.strictEqual(tiles[4].value, '—');
  assert.ok(tiles[4].sub.indexOf('последний прогон памяти') === 0,
    'MAC-S6-MEM-01: время прогона памяти подписано отдельно');
  const links = computed.memoryLinks.call({});
  assert.deepStrictEqual(links.map(function (l) { return l.route; }),
    ['#/memory/rag', '#/oversight?tab=runs']);
}

/* ── 11. MAC-S6-311: один экземпляр каждого блока ───────────────────────── */
{
  const countExactAttr = function (attr) {
    const re = new RegExp(attr + '(?=[\\s=>])', 'g');
    return (INDEX.match(re) || []).length;
  };
  assert.strictEqual(countExactAttr('data-experience'), 1,
    'MAC-S6-311: ровно одна карточка «Опыт»');
  assert.strictEqual(countExactAttr('data-random-source'), 1,
    'MAC-S6-311: ровно один блок «Источник случайности»');
  assert.strictEqual(countExactAttr('data-expired-block'), 1,
    'MAC-S6-311: ровно один блок «Просрочено»');
  // «Статус»: один viewer логов и один блок историй (те же якоря, что
  // проверяет W3-контракт; комментарии/ссылки не считаются).
  const statusSeg2 = INDEX.slice(INDEX.indexOf("activeTab === 'status'"),
    INDEX.indexOf("activeTab === 'persona'"));
  assert.strictEqual((statusSeg2.match(/id="status-logs"/g) || []).length, 1,
    'MAC-S6-311: один viewer логов на «Статусе»');
  assert.strictEqual((statusSeg2.match(/data-stories(?=[\s=>])/g) || []).length,
    1, 'MAC-S6-311: на «Статусе» один stories-блок');
  assert.strictEqual(countExactAttr('data-experience-feed'), 1,
    'MAC-S6-311: одна живая лента опыта');
  // Второй ленты/списка тех же событий нет.
  assert.strictEqual(INDEX.split('data-experience-feed-row').length - 1, 1);
  assert.strictEqual(INDEX.split('data-experience-chain="full"').length - 1, 1,
    'MAC-S6-311: полная цепочка — ровно в одном месте (аналитика)');
}

/* ── 12. MAC-S6-310: порядок сон → последний вызов → бюджеты ───────────── */
{
  const statusSeg = INDEX.slice(INDEX.indexOf("activeTab === 'status'"),
    INDEX.indexOf("activeTab === 'persona'"));
  const s = statusSeg.indexOf('data-status-sleep');
  const e = statusSeg.indexOf('data-exec-preview');
  const b = statusSeg.indexOf('Бюджеты интеллекта');
  assert.ok(s > 0 && e > s && b > e,
    'MAC-S6-310: порядок карточек сон → последний LLM-вызов → бюджеты');
  // Высота последнего вызова — динамическая (не инлайн-фикс высоты сна).
  assert.strictEqual(/data-status-sleep[^>]*style="[^"]*height:/.test(statusSeg),
    false, 'MAC-S6-310: высота карточек не задана инлайном');
  assert.ok(statusSeg.indexOf('data-exec-state') > 0,
    'MAC-S6-310: состояние последнего вызова адресуемо (динамическая высота)');
}

console.log('MOD-ACL-UX-M4B3-EXPERIENCE-OK');
