'use strict';
/* MCA-12 round 10.46 (ADR-1028-21, T-5170-частично + T-5156…T-5169 UI) —
 * поведенческий тест блока «Истории чата» в СУЩЕСТВУЮЩЕЙ композиции.
 *
 * Проверяет:
 *   1) чистые хелперы ленты: merge с дедупом по id (A54 — без дублей),
 *      монотонный курсор, обе даты (A11);
 *   2) prepend БЕЗ сброса scroll (A26): scrollTop компенсируется на
 *      добавленную высоту;
 *   3) loadStoriesFeed: курсор в URL, чтение events/cursor, stale — честный
 *      fail-open (без выдуманных нулей), K1 OFF (enabled:false) → блок скрыт;
 *   4) честные состояния §16.3 (intentsStateLabel: disabled/not_run/
 *      restricted) и настройки-рендер (default/effective/источник; без
 *      configItems — честное «—»/«не загружено»);
 *   5) витрины T-5169: adjacent-линии честно null без данных (без выдумки);
 *   6) структура index.html: едиственная вставка data-stories на «Статусе»,
 *      таблица data-stories-manage внутри существующей memory_rag, НЕТ нового
 *      верхнеуровневого маршрута (#/stories), НЕТ html-вставок (v-html/
 *      innerHTML) в новых блоках (TH-3).
 *
 * Запуск: node tests/js/round1046_mca12_stories_ui_test.js
 *         → MCA12-STORIES-UI-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  matchMedia: function () { return { matches: false, addEventListener() {} }; },
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {}, remove() {},
      getContext() { return null; },
    };
  },
  body: { appendChild() {}, removeChild() {} },
  execCommand() { return true; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
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
assert.ok(captured, 'app.js должен создавать Vue-приложение');
const methods = captured.methods || {};
assert.ok(methods.storiesMergeEvents, 'storiesMergeEvents есть');
assert.ok(methods.loadStoriesFeed, 'loadStoriesFeed есть');
assert.ok(methods.loadStoriesTable, 'loadStoriesTable есть');
assert.ok(methods.storiesAction, 'storiesAction есть');
assert.ok(methods.intentsStateLabel, 'intentsStateLabel есть');
assert.ok(methods.storiesSettingsMeta, 'storiesSettingsMeta есть');

const vm = Object.create(methods);

// ── 1) merge/курсор/обе даты ────────────────────────────────────────────────
const a = { id: 5, ts: 100, event: 'story_discovered', story_id: 's1' };
const b = { id: 9, ts: 200, event: 'story_extended', story_id: 's1' };
const merged = vm.storiesMergeEvents([a], [b, a]);   // дубль a — не добавить
assert.strictEqual(merged.length, 2, 'дедуп по id');
assert.strictEqual(merged[0].id, 9, 'новые сверху');
assert.strictEqual(vm.storiesFeedCursorFrom(merged), 9);
assert.strictEqual(vm.storiesFeedCursorFrom([]), 0);
// A11: старая история, найденная сегодня — обе даты различаются
assert.strictEqual(vm.storiesHasBothDates({
  event_start: 1650000000, event_end: 1650000100, discovered_at: 1790000000,
}), true, 'обе даты: событие 2022 vs обнаружение сегодня');
assert.strictEqual(vm.storiesHasBothDates({
  event_start: 1790000000, event_end: 1790000100, discovered_at: 1790000100,
}), false, 'свежая история — вторая дата не шумит');
assert.strictEqual(vm.storiesHasBothDates({ discovered_at: null }), false);
assert.strictEqual(vm.storiesEventLabel('story_discovered'), 'новая история');
assert.strictEqual(vm.storiesStateRu('uncertain'), 'исход неизвестен');
assert.strictEqual(vm.storiesVerificationRu('tentative'), 'ожидает проверки');

// ── 2) scroll-устойчивость (A26) ────────────────────────────────────────────
const fakeEl = { scrollHeight: 100, scrollTop: 40 };
vm.storiesScrollPreserve(fakeEl, 100, 40);            // ничего не добавилось
assert.strictEqual(fakeEl.scrollTop, 40);
fakeEl.scrollHeight = 160;                            // +60 сверху
vm.storiesScrollPreserve(fakeEl, 100, 40);
assert.strictEqual(fakeEl.scrollTop, 100, 'scrollTop компенсирован (+60)');
// пользователь в начале ленты (prevTop=0) — не дёргаем
fakeEl.scrollTop = 0;
vm.storiesScrollPreserve(fakeEl, 100, 0);
assert.strictEqual(fakeEl.scrollTop, 0);

// ── 3) loadStoriesFeed: курсор + prepend + честный stale + K1 OFF ───────────
let apiCalls = [];
function freshVm() {
  const v = Object.create(methods);
  v.storiesFeed = [];
  v.storiesFeedCursor = 0;
  v.storiesFeedBusy = false;
  v.storiesFeedError = '';
  v.storiesFeedAt = 0;
  v.storiesFeedHasMore = false;
  v.storiesFeedSeq = 0;
  v.storiesEnabled = true;
  v.storiesFeedPaused = false;
  v.storiesSummary = null;
  v.storiesSummaryBusy = false;
  v.storiesSummaryError = '';
  v.storiesManageEnabled = true;
  v.$nextTick = function (fn) { fn(); };
  v.$refs = {};
  v.toast = function () {};
  return v;
}
const v1 = freshVm();
v1.api = async function (p) {
  apiCalls.push(p);
  if (p.startsWith('/api/stories/feed')) {
    return { enabled: true, state: 'ok', cursor: 12, has_more: true,
             events: [{ id: 12, ts: 300, event: 'story_rebuilt',
                        story_id: 's2', title: 'История', text: '',
                        event_start: 1650000000, event_end: 1650000100,
                        discovered_at: 1790000000, participants: ['7'] }] };
  }
  if (p === '/api/stories/summary') {
    return { enabled: true, state: 'ok', counters: { total: 3 }, window_hours: 24 };
  }
  return {};
};
(async function main() {
  await v1.loadStoriesFeed();
  assert.ok(apiCalls.some(function (p) {
    return p === '/api/stories/feed?cursor=0&limit=50';
  }), 'первый опрос — cursor=0');
  assert.strictEqual(v1.storiesFeed.length, 1);
  assert.strictEqual(v1.storiesFeedCursor, 12);
  assert.strictEqual(v1.storiesFeedHasMore, true, 'has_more прочитан');
  await v1.loadStoriesSummary();
  assert.ok(v1.storiesSummary && v1.storiesSummary.counters.total === 3);
  // reconnect (A54): сервер отдаёт только новые; merge не плодит дублей
  v1.api = async function (p) {
    apiCalls.push(p);
    return { enabled: true, state: 'ok', cursor: 14, has_more: false,
             events: [{ id: 14, ts: 400, event: 'source_linked',
                        story_id: 's2', title: 'История' }] };
  };
  await v1.loadStoriesFeed();
  assert.ok(apiCalls.some(function (p) {
    return p === '/api/stories/feed?cursor=12&limit=50';
  }), 'инкрементальный опрос — cursor=12');
  assert.strictEqual(v1.storiesFeed.length, 2, 'без дублей и потерь');
  // ошибка сети → честный stale (лента не обнуляется)
  v1.api = async function () { throw { status: 0 }; };
  await v1.loadStoriesFeed();
  assert.strictEqual(v1.storiesFeedError, 'stale');
  assert.strictEqual(v1.storiesFeed.length, 2, 'stale не подменяет данные нулём');
  // K1 OFF: enabled:false → storiesEnabled=false, блок скрыт
  const v2 = freshVm();
  v2.api = async function () {
    return { enabled: false, state: 'disabled', events: [] };
  };
  await v2.loadStoriesFeed();
  assert.strictEqual(v2.storiesEnabled, false, 'K1 OFF выучен с сервера');
  // 403 → honest restricted (без данных)
  const v3 = freshVm();
  v3.api = async function () { throw { status: 403 }; };
  await v3.loadStoriesSummary();
  assert.strictEqual(v3.storiesSummary.state, 'restricted');

  // ── 4) §16.3: честные состояния + настройки ──────────────────────────────
  assert.strictEqual(vm.intentsStateLabel('disabled'), 'выключено');
  assert.strictEqual(vm.intentsStateLabel('not_run'), 'не запускалось');
  assert.strictEqual(vm.intentsStateLabel('restricted'), 'нет разрешённого чата');
  assert.strictEqual(vm.intentsStateLabel('ok'), 'данные');
  v1.configItems = [];
  const meta = vm.storiesSettingsMeta();
  assert.ok(meta.length >= 9, 'рендер собственных настроек Initiative §16.3 (ASAP 7 F3)');
  for (const m of meta) {
    assert.ok(m.def, 'default указан: ' + m.key);
    assert.strictEqual(m.effective, '—', 'без configItems — честное «—»');
    assert.strictEqual(m.source, 'не загружено');
    assert.ok(m.hot, 'hot/restart указан');
  }
  v1.configItems = [{ key: 'limits.intent_heartbeat_batch_max', value: 7,
                      chat_source: 'chat' }];
  const meta2 = v1.storiesSettingsMeta();
  const rs = meta2.find(function (m) {
    return m.key === 'limits.intent_heartbeat_batch_max';
  });
  assert.strictEqual(rs.effective, '7');
  assert.strictEqual(rs.source, 'чат (override)');

  // ── 5) витрины T-5169: без данных — честно, без выдумки ──────────────────
  v1.adjacentVision = null;
  v1.adjacentFactcheck = null;
  v1.adjacentSelfModel = null;
  assert.strictEqual(vm.adjacentVisionLine.call(v1), null);
  assert.strictEqual(vm.adjacentFactcheckLine.call(v1), null);
  assert.strictEqual(vm.adjacentSelfModelLine.call(v1), null);
  v1.adjacentFactcheck = { temporal_status: 'old_but_valid',
                           factual_verdict: 'supported', created_at: 1790000000 };
  assert.ok(vm.adjacentFactcheckLine.call(v1).indexOf('было верно') >= 0);

  // ── 6) структура index.html ──────────────────────────────────────────────
  const indexHtml = fs.readFileSync(
    path.join(ROOT, 'web', 'index.html'), 'utf8');
  assert.ok(indexHtml.indexOf('data-stories') > 0, 'вставка витрины есть');
  assert.ok((indexHtml.match(/data-stories-feed/g) || []).length === 1,
            'лента историй — одна');
  assert.ok(indexHtml.indexOf('data-stories-manage') > 0,
            'таблица управления есть');
  assert.ok(!/#\/stories\b/.test(indexHtml),
            'нового верхнеуровневого маршрута историй нет (GEN-R12)');
  // блок таблицы — внутри существующей вкладки memory_rag (после lessons,
  // до PERMsoc-секции той же вкладки)
  const ragIdx = indexHtml.indexOf("currentTab.id === 'memory_rag'");
  const manageIdx = indexHtml.indexOf('data-stories-manage');
  const permsocIdx = indexHtml.indexOf("activeTab === 'permsoc'");
  assert.ok(ragIdx > 0 && manageIdx > ragIdx && permsocIdx > manageIdx,
            'data-stories-manage внутри memory_rag-вкладки');
  // позиция вставки витрины: после «Бюджетов интеллекта», до «Доступности ключей»
  const vitrinaIdx = indexHtml.indexOf('data-stories>');
  const budgetsIdx = indexHtml.indexOf('status-budgets');
  const keysIdx = indexHtml.indexOf('Доступность ключей');
  assert.ok(budgetsIdx > 0 && vitrinaIdx > budgetsIdx && vitrinaIdx < keysIdx,
            'вставка после зоны мониторинга интеллекта, до нижних логов (D3)');
  //TH-3: в новых блоках нет html-вставок
  const storiesZone = indexHtml.slice(
    indexHtml.indexOf('data-stories>'), indexHtml.indexOf('data-stories-manage'));
  assert.ok(!/v-html|innerHTML|dangerously|eval\(/.test(storiesZone),
            'без v-html/innerHTML/eval в новых блоках');
  const appJs = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
  // MCA-12-блок в app.js — без html-вставок (в легаси-комментариях F6/Sanitizer
  // v-html упоминается — проверяем именно НОВЫЙ блок методов).
  const jsBlockStart = appJs.indexOf('MCA-12 (round 10.46');
  const jsBlockEnd = appJs.indexOf('oversightRows:', jsBlockStart);
  assert.ok(jsBlockStart > 0 && jsBlockEnd > jsBlockStart,
            'блок методов MCA-12 найден');
  const jsBlock = appJs.slice(jsBlockStart, jsBlockEnd);
  assert.ok(!/v-html|innerHTML|dangerously|eval\(/.test(jsBlock),
            'MCA-12 методы без html-вставок/eval');
  // CSP zero-build: новых внешних скриптов/CDN нет
  assert.ok(!/<script/.test(storiesZone), 'без inline-скриптов');

  console.log('MCA12-STORIES-UI-OK');
})().catch(function (e) {
  console.error('MCA12-STORIES-UI-FAIL:', e && e.message);
  console.error(e);
  process.exit(1);
});
