'use strict';
/* ═══ W3-ANALYTICS (asap8-v6-3-live-correction) — JS-юнит-тесты U05/B08:
 *
 * U05.1 — прогрессивные Процессы/Запуски: человеческое имя, эффективный
 *   статус (работает с результатом / ошибка / не было условий / не
 *   запускался / выключен), последнее реальное действие, причина пустоты;
 *   human-метки типов прогонов.
 * U05.3 — 7 визуализаций D12 §18I.12 на РЕАЛЬНЫХ структурах данных:
 *   heatmap-бакеты, flow/sankey-модель, waterfall-раскладка, карта
 *   зависимостей из inputs/outputs реестра, timeline дат фактчека,
 *   popover overrides; честные пустые состояния (не нули-от-балды).
 * B08 UI — карточка истории: display-поля, три разные даты (null ≠ 1970),
 *   участники ≤5 + «ещё N», refs с url/null, insufficient_sources.
 *
 * Запуск: node tests/js/asap8_v63_w3_analytics_test.js
 *         (вывод: W3-ANALYTICS-UNIT-OK)
 * TEST-LIFECYCLE: CONTRACT owner=REQ-U05/REQ-B08 (slice W3-ANALYTICS)
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

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
  addEventListener() {}, getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() { const i = _bodyChildren.indexOf(this); if (i >= 0) _bodyChildren.splice(i, 1); },
    };
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) { const i = _bodyChildren.indexOf(el); if (i >= 0) _bodyChildren.splice(i, 1); return el; },
  },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('no'); } } },
});
global.sessionStorage = {
  _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp не перехвачен');
const methods = captured.methods || {};
const data = captured.data();
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');

// Контекст: методы app.js поверх общего state (data() + подмены).
function vm(extra) {
  const ctx = Object.create(methods);
  Object.assign(ctx, data, extra || {});
  return ctx;
}

function pad2(n) { return (n < 10 ? '0' : '') + n; }
function dayKey(offsetDays) {
  const d = new Date(Date.now() - offsetDays * 86400000);
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
}

let n = 0;
function ok(cond, label) {
  assert.ok(cond, label);
  n += 1;
}

/* ── U05.1: человеческие имена и эффективный статус процессов ── */
{
  const c = vm();
  ok(c.processHumanName({ process_id: 'ingestion.live', purpose: 'Приём живых сообщений' })
    === 'Приём сообщений чата', 'U05.1: словарное человеческое имя');
  ok(c.processHumanName({ process_id: 'unknown.one', purpose: 'Проверка фактов (CoVe/grounding)' })
    === 'Проверка фактов', 'U05.1: fallback — первая фраза назначения, не тех-id');
  ok(c.processHumanName({ process_id: 'unknown.two', purpose: '' })
    === 'unknown.two', 'U05.1: без назначения — честный id');
  ok(c.processHumanPurpose({ process_id: 'x', purpose: 'Сон: ночной пересмотр. Также сны.' })
    === 'Сон: ночной пересмотр.', 'U05.1: короткое назначение — одно предложение');

  // Сервис недоступен → честный статус реестра (не выдумка).
  const c0 = vm({ mca17cActivity: null });
  const reg = c0.processEff({ process_id: 'a', status: 'not_run' });
  ok(reg.label === 'не запускался', 'U05.1: сервис недоступен → статус реестра');

  const ACT = {
    available: true, events_available: true,
    processes: [
      { process_id: 'ingestion.live', status: 'implemented', effective: 'working',
        reason: 'работает, есть результат', last_ts: 1791900000, counts: { '24h': 40, '7d': 260 } },
      { process_id: 'self_learning.run', status: 'implemented', effective: 'error',
        reason: 'последний запуск с ошибкой', last_ts: 1791800000, last_error_type: 'TimeoutError',
        counts: { '24h': 1, '7d': 3 } },
      { process_id: 'random.uses', status: 'implemented', effective: 'no_conditions',
        reason: 'условий не было: no_trigger', last_ts: 1791000000, last_reason: 'no_trigger',
        counts: { '24h': 0, '7d': 2 } },
      { process_id: 'sleep.deep', status: 'implemented', effective: 'never_run',
        reason: 'запусков не было', last_ts: null, counts: { '24h': 0, '7d': 0 } },
      { process_id: 'goodmorning.run', status: 'disabled', effective: 'off',
        reason: 'выключен (гейт)', counts: { '24h': 0, '7d': 0 } },
    ],
  };
  const c1 = vm({ mca17cActivity: ACT });
  ok(c1.processEff({ process_id: 'ingestion.live', status: 'implemented' }).label
    === 'работает с результатом', 'U05.1: эффективный «работает с результатом»');
  ok(c1.processEff({ process_id: 'self_learning.run', status: 'implemented' }).label
    === 'ошибка', 'U05.1: эффективный «ошибка»');
  ok(c1.processEff({ process_id: 'random.uses', status: 'implemented' }).label
    === 'не было условий', 'U05.1: эффективный «не было условий»');
  ok(c1.processEff({ process_id: 'sleep.deep', status: 'implemented' }).label
    === 'не запускался', 'U05.1: «не запускался» не зелёный (badge-warn)');
  ok(c1.processEff({ process_id: 'sleep.deep', status: 'implemented' }).cls
    === 'badge-warn', 'U05.1: never_run не окрашен успехом');
  ok(c1.processEff({ process_id: 'goodmorning.run', status: 'disabled' }).label
    === 'выключен', 'U05.1: эффективный «выключен»');
  ok(String(c1.processLastAction({ process_id: 'goodmorning.run', status: 'disabled', settings_ref: ['GOODMORNING_ENABLED'] }))
    .indexOf('GOODMORNING_ENABLED') >= 0, 'U05.1: причина пустоты — гейт');
  ok(String(c1.processLastAction({ process_id: 'sleep.deep', status: 'implemented' }))
    .indexOf('запусков не было') >= 0, 'U05.1: причина пустоты для never_run');
  ok(String(c1.processLastAction({ process_id: 'ingestion.live', status: 'implemented' }))
    .indexOf('последнее действие:') === 0, 'U05.1: последнее реальное действие/время');
  ok(c1.processCountsLabel({ process_id: 'ingestion.live' })
    === 'события 24ч: 40 · 7д: 260', 'U05.1: счётчик окна честный');

  ok(c1.runTypeLabel('summary') === 'Сводка', 'U05.1: human-метка типа прогона');
  ok(c1.runTypeLabel('temporal_factcheck') === 'Временной фактчек',
    'U05.1: human-метка временного фактчека');
  ok(c1.runTypeLabel('weird_type') === 'weird_type', 'U05.1: неизвестный тип — как есть');

  // Developer-детали: process_id/стадии/события — в index.html только
  // внутри блока «Детали» (моноширинный код не доминирует по умолчанию).
  const procStart = INDEX.indexOf('data-mca17c="processes"');
  const procSeg = INDEX.slice(procStart, INDEX.indexOf('data-mca17c="runs"'));
  ok(procSeg.indexOf('processHumanName(p)') > 0, 'U05.1: по умолчанию человеческое имя');
  ok(procSeg.indexOf('data-viz-eff') > 0, 'U05.1: эффективный статус на строке');
  ok(procSeg.indexOf('processLastAction(p)') > 0, 'U05.1: последнее действие на строке');
  const detailsPos = procSeg.indexOf(':data-viz-details="p.process_id"');
  const pidPos = procSeg.indexOf('<code class="text-[10px]">{{ p.process_id }}</code>');
  ok(detailsPos > 0 && pidPos > detailsPos,
    'U05.1: developer-ID процесса — внутри «Детали» (после начала details)');
  ok(procSeg.indexOf('vizToggleDetails(p.process_id)') > 0,
    'U05.1: детали раскрываются явно');
}

/* ── U05.3 (4): heatmap — бакеты день × час ── */
{
  const today = dayKey(0);
  const yesterday = dayKey(1);
  const c = vm({
    vizActivityDays: 7,
    vizActivity: {
      available: true, total: 57, errors_total: 3,
      buckets: [
        { d: today, h: 9, c: 40, errs: 1 },
        { d: today, h: 23, c: 14, errs: 0 },
        { d: yesterday, h: 9, c: 3, errs: 2 },
      ],
    },
  });
  const cells = c.vizHeatCells();
  ok(cells.length === 7 * 24, 'Viz-heatmap: полная сетка дней × часов');
  const t9 = cells.find(function (x) { return x.d === today && x.h === 9; });
  ok(t9 && t9.c === 40 && t9.level === 4, 'Viz-heatmap: максимум → уровень 4');
  const y10 = cells.find(function (x) { return x.d === yesterday && x.h === 10; });
  ok(y10 && y10.c === 0 && y10.level === 0 && y10.has === false,
    'Viz-heatmap: пустой час в живом дне = честный 0');
  ok(c.vizHeatClass(t9).indexOf('viz-heat__cell--l4') >= 0, 'Viz-heatmap: класс уровня');
  ok(c.vizHeatClass(y10).indexOf('viz-heat__cell--l0') >= 0, 'Viz-heatmap: класс пустой ячейки');
  const rows = captured.computed.vizHeatRows.call(c);
  ok(rows.length === 7 && rows[rows.length - 1].day === today
    && rows[rows.length - 1].cells.length === 24,
    'Viz-heatmap: computed-строки по дням, сегодня последним');
  ok(c.vizHeatTitle({ d: today, h: 9, c: 40, errs: 1 }).indexOf('ошибок: 1') > 0,
    'Viz-heatmap: тултип с числом ошибок');
  // Честное пустое состояние — не нули.
  const off = vm({ vizActivity: { available: false, reason: 'telemetry_off (…)' } });
  ok(off.vizHeatCells().length === 0, 'Viz-heatmap: телеметрия OFF → ячеек нет');
  const idx = INDEX.indexOf('data-viz-heatmap');
  ok(idx > 0, 'Viz-heatmap: блок присутствует на «Обзоре»');
  ok(INDEX.slice(idx, idx + 3000).indexOf('empty_reason') > 0
    || INDEX.slice(idx, idx + 4000).indexOf('событий не было') > 0,
    'Viz-heatmap: честный empty-state в разметке');
}

/* ── U05.3 (1)+(2): цикл памяти + маршрут обработки ── */
{
  const ACT = {
    available: true, events_available: true,
    processes: [
      { process_id: 'ingestion.live', effective: 'working', counts: { '24h': 100, '7d': 600 }, last_ts: 1791900000 },
      { process_id: 'facts.extract', effective: 'working', counts: { '24h': 30, '7d': 210 }, last_ts: 1791890000 },
      { process_id: 'retrieval.query', effective: 'working', counts: { '24h': 22, '7d': 150 }, last_ts: 1791895000 },
      { process_id: 'direct.reply', effective: 'working', counts: { '24h': 8, '7d': 60 }, last_ts: 1791899000 },
      { process_id: 'intent.initiative', effective: 'no_conditions', counts: { '24h': 0, '7d': 4 }, last_ts: null },
      { process_id: 'summary.publish', effective: 'error', counts: { '24h': 1, '7d': 2 }, last_ts: 1791800000 },
    ],
  };
  const c = vm({ mca17cActivity: ACT });
  const flow = c.vizFlowNodes();
  const ingest = flow.find(function (x) { return x.key === 'ingest'; });
  const facts = flow.find(function (x) { return x.key === 'facts'; });
  const init = flow.find(function (x) { return x.key === 'initiative'; });
  ok(ingest && ingest.total === 100 && ingest.seen, 'Viz-flow: приём = реальный счётчик');
  ok(facts && facts.total === 30, 'Viz-flow: группа фактов суммирует процессы');
  ok(init && init.total === 0 && init.seen, 'Viz-flow: инициатива с нулём за окно видна');
  ok(c.vizFlowNote() === '', 'Viz-flow: при живых данных заметки пустоты нет');
  const empty = vm({ mca17cActivity: { available: true, events_available: false, processes: [] } });
  ok(String(empty.vizFlowNote()).indexOf('событий телеметрии пока нет') >= 0,
    'Viz-flow: честное пустое состояние без выдуманных нулей');

  const route = c.vizRouteRows();
  ok(route.root.total === 100 && route.root.seen, 'Viz-route: корень = входящий поток');
  const reply = route.rows.find(function (r) { return r.key === 'reply'; });
  const memory = route.rows.find(function (r) { return r.key === 'memory'; });
  const initiative = route.rows.find(function (r) { return r.key === 'initiative'; });
  ok(reply && reply.total === 8 && reply.width > 0, 'Viz-route: ширина от счётчика');
  ok(memory && memory.total === 52 && memory.width === 100,
    'Viz-route: максимум = 100% ширины');
  ok(initiative && initiative.width === 0, 'Viz-route: пустая ветка — без полосы');
}

/* ── U05.3 (3): waterfall latency/cost ── */
{
  const c = vm({
    vizPipeline: { run: {
      run_id: 'r1', chat_id: -100500, duration_ms: 9000,
      health_label: 'здоров',
      capacity: { required_input_tokens: 4200, reserved_output_tokens: 900 },
      nodes: [
        { key: 'a', label: 'Источник', state: 'success', latency_ms: 1200 },
        { key: 'b', label: 'L1', state: 'success', latency_ms: 3000 },
        { key: 'c', label: 'L2', state: 'failed', latency_ms: 800 },
        { key: 'd', label: 'Публикация', state: 'success', latency_ms: null },
      ],
    } },
  });
  const wf = c.vizWaterfall();
  ok(wf && wf.items.length === 3, 'Viz-waterfall: узлы без latency не выдумываются');
  ok(wf.items[1].start === 1200 && wf.items[1].end === 4200,
    'Viz-waterfall: кумулятивная раскладка');
  ok(wf.total_ms === 9000, 'Viz-waterfall: общий итог = длительность прогона');
  ok(wf.items[2].width > 0 && wf.items[2].left > 0,
    'Viz-waterfall: полоса со сдвигом (waterfall, не столбики)');
  ok(wf.required_input_tokens === 4200, 'Viz-waterfall: план ёмкости из usage');
  ok(c.vizWaterfallClass('failed') === 'viz-wf__bar--err', 'Viz-waterfall: failed виден красным');
  const none = vm({ vizPipeline: { run: null } });
  ok(none.vizWaterfall() === null, 'Viz-waterfall: нет прогона → честный null');
}

/* ── U05.3 (5): карта зависимостей из реестра (inputs/outputs) ── */
{
  const c = vm({
    mca17cProcesses: { processes: [
      { process_id: 'ingestion.live', status: 'implemented',
        inputs: ['telegram update'], outputs: ['smart_messages'] },
      { process_id: 'summary.window', status: 'implemented',
        inputs: ['smart_messages'], outputs: ['chat_running_summary'] },
      { process_id: 'episodes.build', status: 'implemented',
        inputs: ['smart_messages'], outputs: ['mca_stories'] },
    ] },
  });
  const deps = c.vizDeps();
  const src = deps.layers.find(function (l) { return l.key === 'src'; });
  ok(src && src.chips.some(function (ch) { return ch.pid === 'ingestion.live'; }),
    'Viz-deps: процесс в своём слое');
  const edge = deps.edges.find(function (e) {
    return e.from === 'src' && e.to === 'memory' && e.sample.indexOf('smart_messages') >= 0;
  });
  ok(!!edge, 'Viz-deps: ребро по заявленному артефакту (smart_messages)');
  ok(deps.edges.every(function (e) { return e.from !== e.to; }),
    'Viz-deps: рёбра только между слоями');
  ok(c.layerLabel('src') === 'Источники', 'Viz-deps: человеческое имя слоя');
}

/* ── U05.3 (6): timeline дат источников фактчека ── */
{
  const c = vm({
    temporalRuns: [
      { run_id: 'r1', created_at: 1791900000, original_published_at: 1790000000,
        repost_received_at: 1790100000, date_source: 'telegram_origin',
        factual_verdict: 'supported', temporal_status: 'current' },
      { run_id: 'r2', created_at: 1791900100, original_published_at: null,
        date_source: 'unknown' },
    ],
  });
  const fd = c.vizFactDates();
  ok(fd.dist.telegram_origin === 1 && fd.dist.unknown === 1,
    'Viz-factdates: распределение по date_source');
  ok(fd.items[0].span_days === Math.round((1791900000 - 1790000000) / 86400),
    'Viz-factdates: разброс публикация → проверка');
  ok(fd.items[1].span_days == null && fd.items[1].spanWidth === 0,
    'Viz-factdates: без даты — честная пустая полоса');
  ok(c.vizDateSourceLabel('unknown').indexOf('неизвестна') >= 0,
    'Viz-factdates: unknown подписан честно');
}

/* ── U05.3 (7): popover overrides ── */
{
  const c = vm({
    overrideMap: [
      { key: 'flags.summary_enabled', chat_id: -100500, value: false, access: 'global_admin' },
      { key: 'model', chat_id: -100600, value: 'x', access: 'global_admin' },
    ],
  });
  ok(c.overridesForChat(-100500).length === 1, 'Viz-ovpop: фильтр по чату');
  ok(c.overridesForChat(-100999).length === 0, 'Viz-ovpop: нет override — пусто (честно)');
  c.overridesTogglePop(-100500);
  ok(c.overridesPopChat === -100500, 'Viz-ovpop: поповер открывается');
  c.overridesTogglePop(-100500);
  ok(c.overridesPopChat === null, 'Viz-ovpop: повторный клик закрывает');
  ok(INDEX.indexOf('data-viz-ovpop') > 0, 'Viz-ovpop: поповер в разметке «Обзора»');
}

/* ── B08 UI: карточка истории ── */
{
  const READY = { story: {
    story_id: 's1', content_status: 'ready',
    display_title: 'Спор о сроках ремонта', display_summary: 'Участники обсуждали…',
    title: 'Спор о сроках ремонта', summary: 'Участники обсуждали…',
    primary_participants: ['7', '9', '3'],
    participants: ['7', '9', '3'],
    event_start_ts: 1790000000, event_end_ts: 1790003600,
    discovered_at: 1790100000, rebuilt_at: 1790200000,
    outcome: 'исход неизвестен', open_questions: ['кто прав?'],
  },
  timeline: [
    { ts: 1790000000, episode_id: 'e1', text: 'первый факт',
      refs: [{ message_key: '-100500:tg:10', tg_message_id: 10,
               url: 'https://t.me/c/500/10' }] },
    { ts: 1790000500, episode_id: 'e1', text: 'второй факт',
      refs: [{ message_key: '-100500:tg:11', tg_message_id: 11, url: null }] },
  ] };
  const c = vm();
  ok(c.storyIsInsufficient(READY) === false, 'B08: ready ≠ insufficient');
  ok(c.storyCardTitle(READY) === 'Спор о сроках ремонта', 'B08: display_title');
  ok(c.storyCardSummary(READY).indexOf('Участники') === 0, 'B08: synopsis');
  const rows = c.storyDatesRows(READY);
  ok(rows.length === 3, 'B08: три РАЗНЫЕ даты раздельно');
  ok(rows[0].label === 'События' && rows[0].value.indexOf('—') > 0,
    'B08: период событий');
  ok(rows[1].label === 'Обнаружена' && rows[2].label === 'Пересобрана',
    'B08: обнаружена/пересобрана раздельно');
  ok(c.storyPrimaryNames(READY).length === 3, 'B08: ключевые участники');
  ok(c.storyOpenQuestions(READY).length === 1, 'B08: нерешённый вопрос не теряется');
  ok(c.storyRefHref(READY.timeline[0].refs[0]) === 'https://t.me/c/500/10',
    'B08: валидированный t.me/c — clickable');
  ok(c.storyRefHref(READY.timeline[1].refs[0]) === null,
    'B08: archive_only → без ссылки (url: null)');

  // insufficient: честные поля, «нет источников», без success-раскраски.
  const INSUF = { story: {
    story_id: 's2', content_status: 'insufficient_sources',
    display_title: 'Не удалось восстановить сюжет',
    display_summary: 'Не удалось восстановить сюжет: нет источников',
    primary_participants: [], participants: [],
    event_start_ts: null, event_end_ts: null,
    discovered_at: null, rebuilt_at: null,
  }, timeline: [] };
  ok(c.storyIsInsufficient(INSUF) === true, 'B08: insufficient распознаётся');
  ok(c.storyCardTitle(INSUF) === 'Не удалось восстановить сюжет',
    'B08: честный заголовок, не «история №17800000»');
  ok(c.storyCardSummary(INSUF).indexOf('нет источников') > 0,
    'B08: честное сообщение о недостаче');
  const irows = c.storyDatesRows(INSUF);
  ok(irows.every(function (r) { return r.value === 'нет данных'; }),
    'B08: null-даты = «нет данных», никогда 1970');
  ok(c.storyPrimaryNames(INSUF).length === 0, 'B08: участники пусты честно');

  // Участники ≤5 + «ещё N».
  const MANY = { story: {
    story_id: 's3', content_status: 'ready', display_title: 'T', display_summary: 'S',
    primary_participants: ['1', '2', '3', '4', '5'],
    participants: ['1', '2', '3', '4', '5', '6', '7'],
    display_names: { '6': 'Аня', '7': 'Борис' },
  } };
  ok(c.storyPrimaryNames(MANY).length === 5, 'B08: не более 5 ключевых');
  ok(c.storyOthersCount(MANY) === 2, 'B08: others_count = 2');
  ok(c.storyOtherNames(MANY).join(',') === 'Аня,Борис',
    'B08: раскрытие «ещё N» по display_names');
  c.storiesToggleOthers('s3');
  ok(c.vizStoriesOthers['s3'] === true, 'B08: экспандер участников переключается');
  c.storiesToggleTimeline('s3');
  ok(c.storyTimelineOpen('s3') === true, 'B08: хронология раскрывается');

  // Разметка: успех-раскраски нет у insufficient; refs и toggle на месте.
  const cardSeg = INDEX.slice(INDEX.indexOf('data-stories-manage'),
    INDEX.indexOf('data-stories-dev'));
  ok(cardSeg.indexOf("story-card--insufficient") > 0,
    'B08: insufficient → нейтральная раскраска карточки');
  ok(cardSeg.indexOf('data-story-timeline-toggle') > 0,
    'B08: раскрываемая хронология');
  ok(cardSeg.indexOf('storyRefHref(r)') > 0 && cardSeg.indexOf('в архиве') > 0,
    'B08: refs по правам (url / «в архиве»)');
  ok(cardSeg.indexOf('data-story-dates') > 0, 'B08: блок трёх дат');
  ok(cardSeg.indexOf('data-story-questions') > 0, 'B08: блок нерешённого вопроса');
  // Таблица: display_title + честный бейдж insufficient.
  const tablePos = INDEX.indexOf('data-stories-table');
  ok(INDEX.slice(tablePos, tablePos + 4000).indexOf('s.display_title') > 0,
    'B08: таблица использует display_title');
  ok(INDEX.slice(tablePos, tablePos + 4000).indexOf('нет источников') > 0,
    'B08: в таблице честная метка insufficient');
}

/* ── CSS: маркер блока и мобильные правила (V05) ── */
{
  ok(CSS.indexOf('/* ═══ W3-ANALYTICS ═══ */') > 0
    && CSS.indexOf('/* ═══ /W3-ANALYTICS ═══ */') > 0,
    'CSS: append-блок W3-ANALYTICS присутствует целиком');
  ok(CSS.indexOf('.viz-heat__cell--err') > 0, 'CSS: ошибки на heatmap видимы');
  ok(CSS.indexOf('@media (max-width: 380px)') > 0, 'CSS: адаптация 320px');
  ok(CSS.indexOf('@media (max-height: 480px) and (orientation: landscape)') > 0,
    'CSS: landscape-адаптация');
}

console.log('W3-ANALYTICS-UNIT-OK: ' + n + ' checks passed');
