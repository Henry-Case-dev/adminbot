'use strict';
/* ═══ W3-STATUS (asap8-v6-3-live-correction) — JS-контракт Статуса:
 * U03 (без дубликатов, фикс 22.01.1970, читаемость), U04 (логи — только
 * в Статусе), B03 (блок «Просрочено N» с честной раскладкой).
 *
 * TEST-LIFECYCLE: CONTRACT owner=REQ-U03/U04 (slice FE-STATUS)
 *
 * Проверяет (по ТЗ U03 §151–156, U04 §158–161; CORR-1 — фон не тронут):
 *   1) U03.1: ровно одна каноническая панель «Сон / Глубокий сон»
 *      (последний запуск / стадия / результат / следующий запуск);
 *      второй ряд sleep-бейджей из «Мониторинга Интеллекта» удалён;
 *      ленты убеждений/парадигм/характера сохранены; данные из ОДНОГО
 *      источника (cognition), новых таймеров нет;
 *   2) U03.2: normalizeTsMs/statusTsLabel — seconds/millis/None/0/старые
 *      импорты/мусор-1970 → «ещё не выполнялось / нет данных», не дата;
 *   3) U03.3: «Здоровье памяти» — смысловые (data-expired-block) и
 *      технические (data-memory-tech) счётчики раздельно; подложки
 *      карточек (CORR-1: фон не меняется); CSS-классы W3-STATUS;
 *   4) U03.4: initiativeFunnel — независимая воронка наблюдателя
 *      (8 стадий, окна 24ч/7д, честная причина пустоты, liveness);
 *      disabled/restricted → воронки нет; expWindows 24ч/7д;
 *   5) U04: {id:'logs'} отсутствует; блок #status-logs — последний в
 *      .status-grid Статуса; в Аналитике блока нет; вход в Аналитику не
 *      грузит логи; _consumeLogsScrollLink нормализует канон и легаси;
 *      scrollToLogs вне Статуса ведёт на `#/?scroll=logs`.
 *
 * Запуск: node tests/js/asap8_v63_w3_status_logs_test.js
 *         (печатает W3-STATUS-UNIT-OK)
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
const methods = captured.methods || {};
const computed = captured.computed || {};
const data = captured.data();
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');

// ── 1. U03.1: ровно одна каноническая панель сна ───────────────────────────
{
  const statusStart = INDEX.indexOf("activeTab === 'status'");
  const statusEnd = INDEX.indexOf("activeTab === 'persona'", statusStart);
  const statusSeg = INDEX.slice(statusStart, statusEnd);
  assert.strictEqual(statusSeg.split('data-status-sleep').length - 1, 1,
    'U03.1: панель сна одна (data-якорь единственный: ' +
    (statusSeg.split('data-status-sleep').length - 1) + ')');
  assert.strictEqual((statusSeg.match(/class="card p-4 status-sleep sg-4"/g) || []).length, 1,
    'U03.1: ровно одна карточка сна');
  assert.ok(statusSeg.indexOf('Сон / Глубокий сон') > 0,
    'U03.1: каноническое название «Сон / Глубокий сон»');
  // Стадия/результат/последний запуск/следующий запуск — в разметке.
  assert.ok(statusSeg.indexOf('dreamStageLabel()') > 0, 'U03.1: стадия сна');
  assert.ok(statusSeg.indexOf('deepStageLabel()') > 0, 'U03.1: стадия глубокого сна');
  assert.ok(statusSeg.indexOf('dreamResultLabel()') > 0, 'U03.1: результат сна');
  assert.ok(statusSeg.indexOf('deepResultLabel()') > 0, 'U03.1: результат глубокого сна');
  assert.ok(statusSeg.indexOf("statusTsLabel(sleepWidget.dream.lastRun, 'ещё не выполнялся')") > 0,
    'U03.1: последний запуск — честная метка «ещё не выполнялся»');
  assert.strictEqual(statusSeg.indexOf('scrollToSleepWidget()'), -1,
    'U03.1: второй ряд бейджей/скролл-хелпер удалены');
  const intelHeader = statusSeg.slice(statusSeg.indexOf('class="intel-header mb-2"'),
    statusSeg.indexOf('cognition-ribbons'));
  assert.ok(intelHeader.indexOf('dreamPhaseBadge') < 0
    && intelHeader.indexOf('deepPhaseBadge') < 0,
    'U03.1: в шапке «Мониторинга Интеллекта» нет sleep-бейджей');
  // Содержательные карточки сохранены: убеждения/парадигмы/характер.
  for (const m of ['Убеждения', 'Парадигмы', 'Эволюция характера']) {
    assert.ok(statusSeg.indexOf(m) > 0, 'U03.1: лента «' + m + '» сохранена');
  }
  // Стадии/результаты из ОДНОГО источника (cognition), без таймеров.
  const stageSrc = methods.dreamStageLabel.toString()
    + methods.deepStageLabel.toString();
  assert.ok(stageSrc.indexOf('this.cognition') >= 0,
    'U03.1: стадии читают cognition (один источник)');
  assert.ok(methods.dreamStageLabel.toString().indexOf('setInterval') < 0
    && methods.dreamStageLabel.toString().indexOf('setTimeout') < 0,
    'U03.1: новых таймеров нет');
  // Поведение лейблов.
  const vmS = Object.create(methods);
  vmS.cognition = {
    generated_at: 1791900000,
    dream: { running: false, enabled: true, state: 'sleep',
      budget: { distilled_today: 2, distilled_limit: 5,
        tokens_today: 900, tokens_limit: 2000 } },
    deep_sleep: { running: false, enabled: true },
  };
  vmS.cognitionLastAttemptResult = null;
  assert.strictEqual(methods.dreamStageLabel.call(vmS),
    'ожидание окна расписания');
  assert.strictEqual(methods.dreamResultLabel.call(vmS),
    'синтезов сегодня: 2/5 · токенов: 900/2000');
  assert.strictEqual(methods.deepResultLabel.call(vmS), 'ещё не выполнялся');
  vmS.cognition.dream = { running: true, enabled: true, manual: true,
    state: 'synthesizing', budget: null };
  assert.strictEqual(methods.dreamStageLabel.call(vmS),
    'синтез (ручной прогон)');
  assert.strictEqual(methods.dreamResultLabel.call(vmS), '—',
    'U03.1: нет данных бюджета → «—», нули не выдумываем');
  vmS.cognition.dream.state = 'limit_exhausted';
  vmS.cognition.dream.running = false;
  assert.strictEqual(methods.dreamStageLabel.call(vmS), 'лимит сна исчерпан');
}

// ── 2. U03.2: честные timestamps (seconds/millis/None/0/импорты/TZ) ───────
{
  const vm = Object.create(methods);
  // seconds → дата
  const ms = methods.normalizeTsMs.call(vm, 1791900000);
  assert.strictEqual(ms, 1791900000000, 'seconds → ms');
  // millis → как есть
  assert.strictEqual(methods.normalizeTsMs.call(vm, 1791900000123),
    1791900000123, 'millis сохраняются');
  // None/null/undefined/''/0
  for (const v of [null, undefined, '', 0, '0', NaN, 'abc', -5]) {
    assert.strictEqual(methods.normalizeTsMs.call(vm, v), null,
      'U03.2: ' + String(v) + ' → null (не дата)');
  }
  // 22.01.1970-класс мусора: durations/заглушки (1.8e6 s; 1.8e8 ms-ish)
  assert.strictEqual(methods.normalizeTsMs.call(vm, 1800000), null,
    'U03.2: 1800000 s (≈22.01.1970) → null');
  assert.strictEqual(methods.normalizeTsMs.call(vm, 1.8e8), null,
    'U03.2: мелкий «ms»-мусор → после ×1000 всё равно 1970 → null');
  // 1.8e9 — авто-detect как СЕКУНДЫ (правдоподобная дата 2027); не 1970.
  assert.strictEqual(methods.normalizeTsMs.call(vm, 1.8e9), 1.8e12,
    'U03.2: <1e11 — seconds-домен (auto-detect), не ms');
  // старые импорты (2016) — настоящая дата, показывается
  assert.strictEqual(methods.normalizeTsMs.call(vm, 1460000000),
    1460000000000, 'старый импорт 2016 → дата');
  // строки: ISO и числовые
  assert.strictEqual(methods.normalizeTsMs.call(vm, '1460000000'),
    1460000000000, 'числовая строка → seconds');
  const iso = methods.normalizeTsMs.call(vm, '2026-01-02T03:04:05Z');
  assert.ok(iso && Math.abs(iso - Date.parse('2026-01-02T03:04:05Z')) < 1,
    'ISO-строка парсится');
  // далеко за границей — мусор
  assert.strictEqual(methods.normalizeTsMs.call(vm, 5e12), null,
    '2286 год → мусор');
  // time zone: рендер совпадает с локальным Date (день/час из Date)
  const d = new Date(1791900000000);
  const expected = d.toLocaleString('ru-RU', { hour12: false });
  assert.strictEqual(methods.statusTsLabel.call(vm, 1791900000), expected,
    'U03.2: seconds → локальный ru-рендер (TZ-корректно)');
  // статусные фразы вместо даты
  assert.strictEqual(methods.statusTsLabel.call(vm, null, 'ещё не выполнялся'),
    'ещё не выполнялся');
  assert.strictEqual(methods.statusTsLabel.call(vm, 0), 'нет данных');
  // fmtTs/fmtLogTs/fmtLogTime — честные заглушки
  assert.strictEqual(methods.fmtTs.call(vm, 0), '—');
  assert.strictEqual(methods.fmtTs.call(vm, 1800000), '—',
    'U03.2: fmtTs мусора → «—» (не 22.01.1970)');
  assert.strictEqual(methods.fmtLogTs.call(vm, 1.8e8), '');
  assert.strictEqual(methods.fmtLogTime.call(vm, 1800000), '');
  const good = methods.fmtLogTime.call(
    vm, new Date(2026, 8, 11, 14, 32, 7).getTime());
  assert.strictEqual(good, '11.09 14:32:07');
  // botLastActivity — «нет данных» вместо фальшивой даты
  const bl = computed.botLastActivity.call({ statusData: {
    uptime: { last_heartbeat: 1800000 } } });
  assert.strictEqual(bl, 'нет данных',
    'U03.2: botLastActivity мусора → «нет данных»');
}

// ── 3. U03.3: «Здоровье памяти» — смысловые/технические раздельно ─────────
{
  const statusStart = INDEX.indexOf("activeTab === 'status'");
  const statusSeg = INDEX.slice(statusStart);
  const expStart = statusSeg.indexOf('data-expired-block');
  const techStart = statusSeg.indexOf('data-memory-tech');
  assert.ok(expStart > 0 && techStart > expStart,
    'U03.3/B03: блок «Просрочено» и тех-счётчики есть, в этом порядке');
  assert.ok(statusSeg.indexOf('доступно поиску') > expStart
    && statusSeg.indexOf('требует перепроверки') > expStart
    && statusSeg.indexOf('вытеснено новыми версиями') > expStart
    && statusSeg.indexOf('режим хранения') > expStart,
    'B03: честная раскладка «Просрочено N»');
  assert.ok(statusSeg.slice(techStart, techStart + 2200)
    .indexOf('не подтверждено') > 0,
    'U03.3: технические счётчики отдельным блоком');
  // CSS: подложки — слои карточек; фон не тронут (CORR-1).
  assert.ok(CSS.indexOf('W3-STATUS') > 0, 'CSS: блок W3-STATUS добавлен');
  assert.ok(CSS.indexOf('.mem-kv {') > 0 && CSS.indexOf('.mem-kv__row') > 0,
    'U03.3: раскладка строками «имя → значение»');
  assert.ok(CSS.indexOf('.intel-card .ribbon { background:') > 0,
    'U03.3: подложка лент — слой карточки (фон не менялся)');
  const w3Block = CSS.slice(CSS.indexOf('W3-STATUS'),
    CSS.indexOf('/W3-STATUS'));
  assert.ok(w3Block.indexOf('body::before') < 0
    && w3Block.indexOf('polygon') < 0 && w3Block.indexOf('aurora') < 0,
    'CORR-1: блок W3-STATUS не содержит правил фона');
  // expiredBlock computed.
  const vm = Object.create(methods);
  const b = computed.expiredBlock.call({
    expiredOverview: { available: true, expired_total: 3584,
      expired_searchable: 3500, needs_recheck: 1200, superseded_total: 210,
      infinite_retention: true },
  });
  assert.deepStrictEqual(b, { ready: true, totalLabel: '3584',
    searchable: 3500, needsRecheck: 1200, superseded: 210,
    modeLabel: 'бессрочный' });
  const b2 = computed.expiredBlock.call({ expiredOverview: null });
  assert.strictEqual(b2.ready, false, 'unavailable → честная метка');
  assert.ok(b2.emptyLabel.indexOf('недоступны') >= 0);
  const b3 = computed.expiredBlock.call({
    expiredOverview: { available: false } });
  assert.strictEqual(b3.ready, false);
}

// ── 4. U03.4: независимая воронка Инициативы + окна Опыта ──────────────────
{
  const statusStart = INDEX.indexOf("activeTab === 'status'");
  const statusSeg = INDEX.slice(statusStart);
  assert.ok(statusSeg.indexOf('data-initiative-independent') > 0,
    'U03.4: independent-воронка в разметке');
  assert.ok(statusSeg.indexOf('data-experience-windows') > 0,
    'U03.4: окна 24ч/7д опыта в разметке');
  assert.ok(/funnel-grid/.test(CSS) && /exp-windows/.test(CSS),
    'U03.4: CSS воронок');

  const intelFunnels = {
    available: true, now_ts: 1791900000, chat_scoped_events: false,
    initiative: {
      available: true,
      job: { status: 'completed', updated_at: 1791890000,
        counters: { passes: 3, observed: 420, eligible: 25,
          scan_skipped: 7, evals: 22, opportunities: 4,
          silent_decisions: 2, intents_created: 2, sent: 1,
          react_decisions: 1, writer_unavailable: 1,
          eval_unavailable: 0, errors: 0,
          eval_skips: { budget: 3, silence_window: 2 } } },
      liveness: { ts: 1791889000, status: 'ok', observed: 42,
        opportunities: 1 },
      events: {
        '24h': { initiative_observer_scan: 40, initiative_opportunity: 2,
          initiative_decided: 2, initiative_writer_generated: 2,
          initiative_writer_unavailable: 0, initiative_recheck_passed: 1,
          initiative_sent: 1, initiative_observer_diagnostic: 0 },
        '7d': { initiative_observer_scan: 260, initiative_opportunity: 4,
          initiative_decided: 3, initiative_writer_generated: 3,
          initiative_writer_unavailable: 1, initiative_recheck_passed: 2,
          initiative_sent: 2, initiative_observer_diagnostic: 1 },
      },
    },
    experience: {
      available: true,
      job: { status: 'completed', updated_at: 1791880000,
        counters: { semantic_scanned: 300, semantic_selected: 40,
          semantic_extracted: 12, semantic_candidates: 9,
          semantic_rejected: 3, semantic_duplicates: 2,
          semantic_llm_unavailable: 1, semantic_reject_reasons: {
            hearsay: 2, short: 1 } },
        semantic_watermark: 15000, semantic_pending: 3 },
      semantic_lag: { watermark: 15000, max_message_id: 15200, pending: 3 },
      last_application: { ts: 1791800000, outcome: 'success' },
      events: {
        '24h': { semantic_extract: 3, detector_signal: 2, applied: 1,
          retrieved: 4 },
        '7d': { semantic_extract: 8, detector_signal: 5, applied: 3,
          retrieved: 11 },
      },
    },
  };
  const mk = function (state) {
    return Object.create(methods, {
      intelFunnels: { value: intelFunnels },
      intelFunnelsBusy: { value: false },
      statusData: { value: { intents: { state: state, module: {} } } },
      expWindow24h: { value: { available: true, enabled: true,
        feedback: { total: 3 }, lessons: { new_in_period: 1 },
        applications: { total: 2, success: 1, failure: 0, unknown: 1 } } },
      expWindow7d: { value: { available: true, enabled: true,
        feedback: { total: 9 }, lessons: { new_in_period: 4 },
        applications: { total: 5, success: 2, failure: 1, unknown: 2 } } },
    });
  };
  const f = computed.initiativeFunnel.call(mk('not_run'));
  assert.ok(f, 'not_run → воронка есть');
  const labels = f.stages.map(function (s) { return s.label; });
  assert.deepStrictEqual(labels,
    ['Наблюдено', 'Квалифицировано', 'Возможности', 'Намерения', 'Решения',
     'Текст', 'Перепроверка', 'Отправлено'],
    'U03.4: полная цепочка observed→…→sent');
  const values = f.stages.map(function (s) { return s.value; });
  assert.deepStrictEqual(values, [420, 25, 4, 2, 3, 3, 2, 1],
    'U03.4: значения — durable counters + события 7д (writer/recheck)');
  assert.strictEqual(f.stages[4].sub, 'реакций: 1',
    'U03.4: реакции видны отдельной подписью');
  assert.ok(f.emptyReason.indexOf('отправлено 1') >= 0,
    'U03.4: непустая воронка — честный итог');
  assert.ok(f.liveLabel.indexOf('последний тик') === 0,
    'U03.4: liveness-штамп показан');
  // Пустая панель ≠ «работает»: нули → причина пустоты, не «работает».
  const emptyFunnels = JSON.parse(JSON.stringify(intelFunnels));
  emptyFunnels.initiative.job = null;
  emptyFunnels.initiative.liveness = { ts: null, status: null,
    observed: null, opportunities: null };
  emptyFunnels.initiative.events = {
    '24h': {}, '7d': {} };
  const vmE = Object.create(methods);
  vmE.intelFunnels = emptyFunnels;
  vmE.statusData = { intents: { state: 'not_run', module: {} } };
  const fE = computed.initiativeFunnel.call(vmE);
  assert.ok(fE.emptyReason.indexOf('не выполнялось') >= 0,
    'U03.4: пустая воронка — «наблюдение не выполнялось»');
  assert.strictEqual(fE.liveLabel, 'наблюдение ещё не выполнялось',
    'U03.4: liveness отсутствует — не «работает»');
  // disabled/restricted → воронки нет (честная строка состояния).
  assert.strictEqual(computed.initiativeFunnel.call(mk('disabled')), null,
    'U03.4: disabled → воронки нет');
  assert.strictEqual(computed.initiativeFunnel.call(mk('restricted')), null);
  assert.strictEqual(computed.initiativeFunnel.call({
    intelFunnels: null, statusData: { intents: { state: 'ok' } } }), null,
    'U03.4: нет данных → нет воронки (не нули)');
  // Опыт: окна и причины пустоты.
  const w = computed.expWindows.call(mk('ok'));
  assert.ok(w && w.length === 2, 'U03.4: два окна 24ч/7д');
  assert.deepStrictEqual(w.map(function (x) { return x.title; }), ['24ч', '7д']);
  assert.deepStrictEqual(w.map(function (x) { return x.applied; }), [2, 5]);
  assert.ok(computed.expLastAppliedLabel.call(mk('ok'))
    .indexOf('последнее применение:') === 0);
  const emptyExp = Object.create(methods);
  emptyExp.intelFunnels = null;
  emptyExp.expWindow24h = null;
  assert.strictEqual(computed.expWindows.call(emptyExp), null);
  assert.strictEqual(computed.expEmptyReason.call(emptyExp),
    'семантический обзор ещё не выполнялся — durable-задачи нет',
    'U03.4: причина пустоты честная');
  const offExp = Object.create(methods);
  offExp.intelFunnels = null;
  offExp.expWindow24h = { available: true, enabled: false };
  assert.ok(computed.expEmptyReason.call(offExp).indexOf('выключено') >= 0,
    'U03.4: kill-switch назван честно');
  const scanExp = Object.create(methods);
  scanExp.expWindow24h = { available: true, enabled: true,
    applications: { total: 0 } };
  scanExp.intelFunnels = { experience: { job: { counters: {
    semantic_scanned: 300, semantic_extracted: 0, semantic_candidates: 0,
    semantic_rejected: 3, semantic_duplicates: 2,
    semantic_llm_unavailable: 1 } },
    semantic_lag: { watermark: 15000 } } };
  assert.ok(computed.expEmptyReason.call(scanExp)
    .indexOf('кандидатов не отобрано') >= 0);
}

// ── 5. U04: логи — только в Статусе ────────────────────────────────────────
{
  assert.strictEqual(data.oversightTabs.some(function (t) {
    return t.id === 'logs'; }), false,
    'U04: {id:"logs"} удалён из oversightTabs');
  const statusStart = INDEX.indexOf("activeTab === 'status'");
  const statusEnd = INDEX.indexOf("activeTab === 'persona'", statusStart);
  const statusSeg = INDEX.slice(statusStart, statusEnd);
  const oversSeg = INDEX.slice(INDEX.indexOf("activeTab === 'oversight'"),
    statusStart);
  assert.strictEqual((statusSeg.match(/id="status-logs"/g) || []).length, 1,
    'U04: ровно один блок логов в Статусе');
  assert.strictEqual(oversSeg.indexOf('<div class="card p-4 status-logs'), -1,
    'U04: в Аналитике блока логов нет');
  // Блок — последняя карточка .status-grid.
  const gridEnd = statusSeg.indexOf('/F11 §12 .status-grid');
  const tail = statusSeg.slice(statusSeg.indexOf('id="status-logs"'), gridEnd);
  assert.ok(tail.indexOf('v-model="logLevel"') > 0
    && tail.indexOf('toggleLogSummary()') > 0
    && tail.indexOf('copyAllLogs()') > 0
    && tail.indexOf('id="mca-log-filters"') > 0,
    'U04: фильтры/копирование/уровень в перенесённом доме');
  assert.ok(statusSeg.indexOf('status-counts') > 0
    && statusSeg.indexOf('scrollToLogs()') > 0,
    'U04: счётчики вверху Статуса скроллят к логам');
  // consumer-нормализация.
  {
    const written = [];
    const vm = Object.create(methods);
    global.window = { location: { hash: '' },
      history: { replaceState: function (s, t, u) { written.push(u); } } };
    assert.strictEqual(vm._consumeLogsScrollLink('#/?scroll=logs'), true);
    assert.strictEqual(vm._consumeLogsScrollLink('#/oversight?scroll=logs'),
      true, 'U04.2: легаси oversight?scroll=logs нормализуется');
    assert.strictEqual(vm._consumeLogsScrollLink('#/oversight?tab=logs'),
      true, 'U04.2: легаси ?tab=logs нормализуется');
    assert.strictEqual(vm._consumeLogsScrollLink('#/oversight?view=runs'),
      false, 'U04.2: чужой контекст ссылок не тронут');
    assert.deepStrictEqual(written, ['#/', '#/', '#/'],
      'U04.2: адрес нормализован к канону #/');
  }
  // Клик вне Статуса → канон Статуса.
  {
    const vm = Object.create(methods);
    vm.activeTab = 'oversight';
    global.window = { location: { hash: '#/oversight' }, location_set: null };
    Object.defineProperty(global.window.location, 'hash', {
      configurable: true,
      get: function () { return '#/oversight'; },
      set: function (v) { global.window.location_set = v; },
    });
    methods.scrollToLogs.call(vm);
    assert.strictEqual(global.window.location_set, '#/?scroll=logs',
      'U04.2: ссылка «Логи» ведёт на Статус (канон), не в Аналитику');
  }
  // Вход в Аналитику не грузит логи (контракт заглушён выше — здесь
  // сверяем исходник: вызов loadLogs из oversightTabEnter удалён).
  const tEnter = methods.oversightTabEnter.toString();
  assert.strictEqual(tEnter.indexOf('this.loadLogs()'), -1,
    'U04.1: loadLogs() на входе в Аналитику убран');
  // Вход в Статус грузит логи лениво (источник данных единственный).
  assert.ok(/id === 'status'[\s\S]{0,600}this\.loadLogs\(\)/.test(
    fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8')),
    'U04.1: viewer в Статусе лениво догружается при входе');
}

console.log('W3-STATUS-UNIT-OK');
