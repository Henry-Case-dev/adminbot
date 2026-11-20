'use strict';
/* ═══ MOD-ACL-UX-01 M4B B1 — «пять лент» на «Статусе» ═══════════════════════
 * Контракт (requirements-map): MAC-S6-307, MAC-AC-16, MAC-S6-FEED-01,
 * MAC-S6-FEED-02, MAC-S6-FEED-03 (UI-часть), MAC-S15-03, MAC-S15-04,
 * MAC-S0-11 (частично), MAC-S15-15.
 *
 * Проверяется РЕАЛЬНЫЙ код `web/app.js`, `web/index.html`, `web/static/app.css`:
 *   1) ровно пять секций в одной карточке, «Досье» — пятая и последняя;
 *      нижней карточки/тикара досье больше нет (один источник, одно место);
 *   2) сетка 3+2 (≥1280), 2+2+1 (768–1279), 1 колонка + вкладки (≤767);
 *      пять одинаковых живых окон `.sfeed-viewport`, без h-скролла;
 *   3) a11y: tablist/tab, aria-selected/aria-current, roving tabindex,
 *      клавиатура (стрелки/Home/End без wrap), touch ≥44 px; память позиции
 *      скролла W2a не сломана;
 *   4) «Досье» — person-centric проекция ТОГО ЖЕ dossier_feed (один участник
 *      = одна строка), не 1:1 дубль «Новых фактов»; имя/чат/дата/число
 *      записей и provenance не выдумываются; пусто/ошибка честные;
 *   5) scope: запрос с chat_id, смена области отбрасывает in-flight ответ и
 *      очищает записи другого чата; второго API/store нет.
 *
 * Запуск: node tests/js/mod_acl_ux_m4b_feeds_test.js
 *         → MOD-ACL-UX-M4B-B1-FEEDS-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

/* ── 1. Разметка: пять секций, «Досье» последняя, нижней копии нет ───────── */
const cardStart = INDEX.indexOf('class="card p-4 sg-12 intel-card"');
const cardEnd = INDEX.indexOf('<!-- ═══ ASAP-UI-02 (§5.4', cardStart);
assert.ok(cardStart > 0 && cardEnd > cardStart, 'единая карточка найдена');
const CARD = INDEX.slice(cardStart, cardEnd);
assert.strictEqual(CARD.split('class="ribbon ').length - 1, 5,
  'ровно пять лент в одной карточке');
const SECTION_IDS = ['facts', 'beliefs', 'paradigms', 'traits', 'dossier'];
SECTION_IDS.forEach(function (id) {
  assert.ok(CARD.indexOf('data-intel-section="' + id + '"') >= 0, id);
  assert.ok(CARD.indexOf('data-ribbon="' + id + '"') >= 0,
    id + ': ключ секции для сохранения позиции');
  assert.ok(CARD.indexOf('ribbon--' + id) >= 0, id + ': класс секции');
});
// Порядок: досье — пятая, после эволюции.
assert.ok(CARD.indexOf('data-intel-section="traits"')
  < CARD.indexOf('data-intel-section="dossier"'),
  'досье — пятая секция после эволюции');
// Единый контроллер лент у всех пяти (второго механизма нет).
assert.strictEqual(CARD.split('v-sfeed="statusRecordOpen"').length - 1, 5,
  'все пять лент на одном контроллере v-sfeed');
assert.strictEqual(CARD.split('data-sfeed-viewport').length - 1, 5,
  'пять окон реальной прокрутки');
// Одна карточка = одно место; старой нижней копии/тикара нет.
assert.strictEqual(INDEX.split('data-status-dossier').length - 1, 0,
  'нижняя карточка «Живая лента досье» удалена');
assert.strictEqual(INDEX.split('dossier-ticker').length - 1, 0,
  'дублирующий тикер/клоны удалены');
assert.strictEqual(INDEX.split('dossierFeedLoop').length - 1, 0,
  'мёртвая модель тикера удалена');
assert.strictEqual(INDEX.split('DOSSIER_LIVE_FEED_ENABLED').length - 1, 0,
  'лента досье больше не скрывается старым kill-switch тикера');
// Пятая лента читает реальные поля (не выдуманные) и открывает существующее
// окно записи; вторичное действие — существующее «Досье субъекта».
assert.ok(CARD.indexOf('v-for="it in dossierPeopleFeed"') >= 0);
assert.ok(CARD.indexOf('data-sfeed-type="dossier"') >= 0);
assert.ok(CARD.indexOf("openStatusRecord('fact', it.latest, $event)") >= 0,
  'клик открывает существующее окно записи');
assert.ok(CARD.indexOf('statusRowDateLabel(it.last_at)') >= 0,
  'дата записи — общий формат лент');
assert.ok(CARD.indexOf('dossierFeedStamp()') >= 0,
  'честная подпись свежести сохранена');
assert.ok(INDEX.indexOf('data-rec-dossier') >= 0,
  'существующее «Досье субъекта» в окне записи не удалено');
assert.ok(INDEX.indexOf('Мониторинг Интеллекта') >= 0);
assert.ok(INDEX.indexOf('пять лент: факты · убеждения · парадигмы · эволюция · досье') >= 0,
  'заголовок называет пять лент');

/* ── 2. CSS: 3+2 / 2+2+1 / 1, без 4-колоночной сетки и старых правил ────── */
assert.ok(/\.cognition-ribbons \{[\s\S]{0,120}grid-template-columns:\s*minmax\(0, 1fr\)/.test(CSS),
  'база: одна колонка (mobile)');
assert.ok(/@media \(min-width: 768px\) \{\s*\.cognition-ribbons \{ grid-template-columns: repeat\(2, minmax\(0, 1fr\)\); \}/.test(CSS),
  '768–1279: две колонки (2+2+1)');
assert.ok(/@media \(min-width: 1280px\) \{\s*\.cognition-ribbons \{ grid-template-columns: repeat\(3, minmax\(0, 1fr\)\); \}/.test(CSS),
  '≥1280: три колонки (3+2, не пять узких)');
assert.ok(/@media \(max-width: 767px\) \{[^@]*\.cognition-ribbons\[data-intel-tab\]/.test(CSS),
  'правило одной ленты действует на mobile ≤767');
['facts', 'beliefs', 'paradigms', 'traits', 'dossier'].forEach(function (id) {
  assert.ok(CSS.indexOf('.cognition-ribbons[data-intel-tab="' + id + '"] .ribbon--' + id) >= 0,
    'mobile: активная секция ' + id + ' видна');
});
assert.ok(CSS.indexOf('.cognition-ribbons { grid-template-columns: repeat(4') < 0,
  'прежняя 4-колоночная сетка лент не возвращается');
assert.strictEqual(CSS.indexOf('@media (min-width: 1100px) {\n      .cognition-ribbons'), -1,
  'прежний breakpoint 1100 для лент удалён');
assert.ok(/\.intel-tabs \{ display: none; \}/.test(CSS),
  'переключатель не тратит место на десктопе/планшете');
const tabsRule = /\.intel-tabs \.intel-tabs__btn \{[^}]*\}/.exec(CSS);
assert.ok(tabsRule, 'правило тач-цели переключателя найдено');
assert.ok(/min-height:\s*var\(--control-h-touch,\s*44px\)/.test(tabsRule[0]),
  'высота тач-цели переключателя 44px');
assert.ok(/min-width:\s*var\(--control-h-touch,\s*44px\)/.test(tabsRule[0]),
  'ширина тач-цели переключателя 44px');
assert.ok(/\.sfeed-viewport \{[\s\S]{0,800}overflow-y: auto/.test(CSS),
  'ленты — только вертикальный скролл');
assert.strictEqual(CSS.indexOf('.dossier-ticker'), -1,
  'CSS мёртвого тикера досье удалён');
assert.strictEqual(CSS.indexOf('.status-dossier__track'), -1,
  'CSS нижней карточки досье удалён');
assert.ok(CSS.indexOf('.sfeed-item__badge--dossier') >= 0,
  'пятая лента использует общий слой строк с собственным бейджем');
assert.ok(/@media \(prefers-reduced-motion: reduce\)[\s\S]{0,200}\.sfeed/.test(CSS)
  || /prefers-reduced-motion: reduce/.test(CSS),
  'reduced-motion сохранён');

/* ── 3. Реальный код app.js ─────────────────────────────────────────────── */
global.Vue = {
  createApp: function (opts) {
    global.__opts = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
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
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
let fetchCalls = 0;
global.fetch = async function () { fetchCalls += 1; throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
const opts = global.__opts;
assert(opts, 'Vue.createApp должен быть вызван');
const computed = opts.computed || {};
const methods = opts.methods || {};
['dossierPeopleFeed'].forEach(function (name) {
  assert.strictEqual(typeof computed[name], 'function', 'computed ' + name);
});
['onStatusRibbonKeydown', 'statusRibbonKeyTarget', 'switchStatusRibbon',
 'loadDossierFeed', '_resetDossierFeedScope', 'dossierFeedEmptyTitle',
 'dossierFeedEmptyText', 'dossierFeedEmptyReason', 'dossierPeopleAriaLabel',
 'openStatusRecord', 'statusRowDateLabel', 'dossierFeedStamp'].forEach(function (name) {
  assert.strictEqual(typeof methods[name], 'function', 'method ' + name);
});
assert.strictEqual(computed.dossierFeedLoop, undefined,
  'мёртвая 1:1-модель тикера удалена');
assert.strictEqual(computed.dossierFeedSpeed, undefined,
  'мёртвая скорость тикера удалена');

const data = opts.data.call({});
assert.strictEqual(data.statusRibbonTabs.length, 5, 'пять секций в переключателе');
assert.deepStrictEqual(data.statusRibbonTabs.map(function (t) { return t.id; }),
  SECTION_IDS, 'id и порядок секций');
assert.strictEqual(data.statusRibbonTab, 'facts', 'по умолчанию — «Факты»');

/* ── 4. A11y-разметка и клавиатура ──────────────────────────────────────── */
assert.ok(CARD.indexOf('role="tablist"') >= 0, 'полоса секций — tablist');
assert.ok(CARD.indexOf('role="tab"') >= 0, 'кнопки — tab');
assert.ok(CARD.indexOf(':aria-selected="statusRibbonTab === t.id') >= 0,
  'выбранный таб доступен AT');
assert.ok(CARD.indexOf(':aria-current="statusRibbonTab === t.id') >= 0,
  'aria-current на активной секции');
assert.ok(CARD.indexOf(':tabindex="statusRibbonTab === t.id ? 0 : -1"') >= 0,
  'roving tabindex');
assert.ok(CARD.indexOf('@keydown="onStatusRibbonKeydown($event)"') >= 0,
  'клавиатура на полосе');
assert.ok(CARD.indexOf('ref="intelTabs"') >= 0, 'корень полосы для фокуса');

const tabs = data.statusRibbonTabs;
assert.strictEqual(methods.statusRibbonKeyTarget('facts', 'ArrowRight', tabs), 'beliefs');
assert.strictEqual(methods.statusRibbonKeyTarget('traits', 'ArrowRight', tabs), 'dossier');
assert.strictEqual(methods.statusRibbonKeyTarget('dossier', 'ArrowRight', tabs), 'dossier',
  'правый край — без wrap');
assert.strictEqual(methods.statusRibbonKeyTarget('dossier', 'ArrowLeft', tabs), 'traits');
assert.strictEqual(methods.statusRibbonKeyTarget('facts', 'ArrowLeft', tabs), 'facts',
  'левый край — без wrap');
assert.strictEqual(methods.statusRibbonKeyTarget('dossier', 'Home', tabs), 'facts');
assert.strictEqual(methods.statusRibbonKeyTarget('facts', 'End', tabs), 'dossier');
assert.strictEqual(methods.statusRibbonKeyTarget('traits', 'ArrowDown', tabs), 'dossier');
assert.strictEqual(methods.statusRibbonKeyTarget('traits', 'ArrowUp', tabs), 'paradigms');
assert.strictEqual(methods.statusRibbonKeyTarget('facts', 'Tab', tabs), '',
  'Tab не перехватывается');
assert.strictEqual(methods.statusRibbonKeyTarget('facts',
  { key: 'ArrowRight', ctrlKey: true }, tabs), '',
  'Ctrl+→ не перехватывается');
assert.strictEqual(methods.statusRibbonKeyTarget('unknown', 'Home', tabs), 'facts',
  'устаревший id → первый таб');

// Реальная активация: стрелка вправо с «Фактов» → «Убеждения», фокус после
// перерисовки; данные не перезапрашиваются.
const focusCalls = [];
const keyVm = {
  statusRibbonTab: 'facts',
  statusRibbonTabs: tabs,
  _intelRibbonPos: undefined,
  $refs: { intelTabs: { querySelector(sel) {
    focusCalls.push(sel);
    return { focus() { focusCalls.push('focused'); } };
  } } },
  $nextTick(fn) { fn(); return Promise.resolve(); },
  captureStatusRibbonPositions() { return {}; },
  restoreStatusRibbonPositions() {},
};
keyVm.switchStatusRibbon = methods.switchStatusRibbon;
keyVm.statusRibbonKeyTarget = methods.statusRibbonKeyTarget;
keyVm.onStatusRibbonKeydown = methods.onStatusRibbonKeydown;
keyVm._focusStatusRibbonTab = methods._focusStatusRibbonTab;
let prevented = 0;
methods.onStatusRibbonKeydown.call(keyVm, {
  key: 'ArrowRight', target: {
    closest(sel) {
      return sel === '[data-intel-tab-btn]'
        ? { getAttribute() { return 'facts'; } } : null;
    },
  },
  preventDefault() { prevented += 1; },
});
assert.strictEqual(keyVm.statusRibbonTab, 'beliefs', 'стрелка переключила секцию');
assert.strictEqual(prevented, 1, 'обработанная стрелка подавляет скролл страницы');
assert.ok(focusCalls.indexOf('focused') >= 0, 'фокус переведён на новый таб');
assert.strictEqual(fetchCalls, 0, 'переключение не перезапрашивает данные');

/* ── 5. Досье: person-centric проекция, не 1:1 ──────────────────────────── */
function feedRow(over) {
  return Object.assign({
    chat_id: -100, name: 'A', user_name: 'Аня', user_id: 5,
    excerpt: 'любит кофе', text: 'Аня любит кофе', created_at: 100,
    message_timestamp: 999, last_confirmed_at: 120, origin: 'chat_history',
    id: 1, tg_message_id: 11, kind: 'preference',
  }, over || {});
}
const people = computed.dossierPeopleFeed.call({
  dossierFeed: [
    feedRow({ id: 1, created_at: 100, excerpt: 'любит кофе', text: 'Аня любит кофе' }),
    feedRow({ id: 2, chat_id: -200, excerpt: 'переехала', text: 'Аня переехала',
      created_at: 200, origin: 'summary', tg_message_id: null }),
    feedRow({ id: 3, name: 'B', user_name: 'B', user_id: null,
      excerpt: 'факт B', text: 'факт B', created_at: 150, origin: null }),
    feedRow({ id: 4, name: null, user_name: null, user_id: null,
      excerpt: 'неизвестный', text: 'неизвестный', created_at: 120,
      origin: 'voice_transcript' }),
  ],
  chatTitleFor(id) { return String(id) === '-100' ? 'Чат А' : ''; },
});
assert.strictEqual(people.length, 3,
  'четыре записи → три человека (досье — не 1:1 копия «Фактов»)');
assert.deepStrictEqual(people.map(function (p) { return p.name; }),
  ['Аня', 'B', 'Участники не определены'],
  'сортировка по последней дате записи; неизвестные — честной строкой');
const anya = people[0];
assert.strictEqual(anya.count, 2, 'число записей участника');
assert.strictEqual(anya.key, 'u:5', 'identity по user_id');
assert.strictEqual(anya.latest.id, 2, 'последняя запись — по created_at');
assert.strictEqual(anya.last_at, 200, 'дата записи, а не события/подтверждения');
assert.strictEqual(anya.latest.event_at, 999,
  'дата события сохранена в записи отдельно и не подменяет дату записи');
assert.strictEqual(anya.event_at, undefined, 'строке не подменяют дату события');
assert.strictEqual(anya.chatLabel, 'разные чаты',
  'один человек в разных чатах — честная подпись');
assert.strictEqual(anya.scopePrefix, 'разные чаты · ');
assert.ok(anya.originLabel.indexOf('chat_history') >= 0
  && anya.originLabel.indexOf('summary') >= 0, 'оба источника видны');
assert.strictEqual(anya.user_id, 5);
const b = people[1];
assert.strictEqual(b.count, 1);
assert.strictEqual(b.key, 'n:B', 'fallback identity — имя при отсутствии user_id');
assert.strictEqual(b.user_id, null, 'user_id не выдумывается');
assert.strictEqual(b.chatLabel, 'Чат А', 'человеческое имя чата из общего резолвера');
assert.strictEqual(b.scopePrefix, 'Чат А · ');
assert.ok(b.known, 'имя без user_id — известная (но не кликабельная в досье) строка');
const unknown = people[2];
assert.strictEqual(unknown.key, 'unknown');
assert.strictEqual(unknown.count, 1);
assert.strictEqual(unknown.known, false);
assert.strictEqual(unknown.scopePrefix, '', 'без имени чат-префикс не притворяется');
assert.strictEqual(unknown.chatLabel, 'Чат А');
assert.ok(unknown.latest.text.indexOf('неизвестный') >= 0);

// Имя без user_id группируется; одинаковые записи не размножаются.
const byName = computed.dossierPeopleFeed.call({
  dossierFeed: [
    feedRow({ id: 5, name: 'C', user_name: 'C', user_id: null, created_at: 10 }),
    feedRow({ id: 6, name: 'C', user_name: 'C', user_id: null, created_at: 11 }),
  ],
  chatTitleFor() { return ''; },
});
assert.strictEqual(byName.length, 1, 'две записи одного имени — одна строка');
assert.strictEqual(byName[0].count, 2);
assert.strictEqual(byName[0].chatLabel, 'Чат -100', 'нет названия → честный id');

// Пусто и детерминизм.
assert.deepStrictEqual(computed.dossierPeopleFeed.call({
  dossierFeed: [], chatTitleFor() { return ''; },
}), [], 'пустая лента → пусто');
const twice = computed.dossierPeopleFeed.call({
  dossierFeed: [feedRow({ id: 7 })],
  chatTitleFor() { return 'Чат А'; },
});
assert.deepStrictEqual(twice.map(function (p) { return p.key; }),
  ['u:5'], 'уникальные ключи строк');

// factsFeed не изменился: те же поля/ключ/даты, что и раньше.
const fact = computed.factsFeed.call({ dossierFeed: [feedRow({ id: 8 })] })[0];
assert.strictEqual(fact.key, 'ff|-100|A|любит кофе');
assert.strictEqual(fact.name, 'Аня');
assert.strictEqual(fact.text, 'любит кофе');
assert.strictEqual(fact.time, 100);
assert.strictEqual(fact.kind, 'preference');
assert.strictEqual(fact.full, 'Аня любит кофе');
assert.strictEqual(fact.event_at, 999);
assert.strictEqual(fact.confirmed_at, 120);

/* ── 6. Пустые состояния и a11y-подпись ─────────────────────────────────── */
assert.strictEqual(methods.dossierFeedEmptyTitle.call({ activeChatId: null }),
  'Досье пусто');
assert.strictEqual(methods.dossierFeedEmptyTitle.call({ activeChatId: -100 }),
  'В выбранном чате досье пусто');
assert.ok(methods.dossierFeedEmptyText.call({ activeChatId: -100 })
  .indexOf('Данные других чатов не подставляются') >= 0,
  'чат без досье не показывает чужие данные');
assert.strictEqual(methods.dossierFeedEmptyReason.call({
  activeChatId: null, dossierFeedLoaded: false,
  statusFeedEmptyReason() { return 'no'; },
}), 'лента ещё не запрашивалась');
assert.strictEqual(methods.dossierFeedEmptyReason.call({
  activeChatId: -100, dossierFeedLoaded: true,
  statusFeedEmptyReason() { return 'no'; },
}), '', 'для выбранного чата причина уже в тексте');
assert.strictEqual(methods.dossierFeedEmptyReason.call({
  activeChatId: null, dossierFeedLoaded: true,
  statusFeedEmptyReason() { return 'экстракция не передаёт причину'; },
}), 'экстракция не передаёт причину');
const aria = methods.dossierPeopleAriaLabel.call({
  fmtTs(ts) { return 'T' + ts; },
}, anya);
assert.ok(aria.indexOf('Досье, Аня') === 0, 'a11y: субъект');
assert.ok(aria.indexOf('записей: 2') >= 0, 'a11y: число записей');
assert.ok(aria.indexOf('чат: разные чаты') >= 0, 'a11y: scope');
assert.ok(aria.indexOf('последняя запись: T200') >= 0, 'a11y: дата записи');
assert.ok(aria.indexOf('источник:') >= 0, 'a11y: provenance');
assert.ok(methods.dossierPeopleAriaLabel.call({}, unknown)
  .indexOf('дата последней записи неизвестна') >= 0,
  'нет даты — честная подпись, не выдуманная');

/* ── 7. Scope/загрузка: chat_id, epoch, сброс области ──────────────────── */
(async function () {
  // 7a. Конкретный чат → chat_id в запросе; global → без chat_id.
  {
    const calls = [];
    const ctx = {
      activeChatId: -100, dossierFeedBusy: false, dossierFeed: [],
      dossierFeedError: '', dossierFeedLoaded: false, dossierFeedAt: 0,
      scopeEpoch: 1,
      _scopeGuard(ep) { return ep === this.scopeEpoch; },
      loreErrText(e) { return String(e); },
      async api(url) {
        calls.push(url);
        return { items: [{ chat_id: -100, name: 'A', excerpt: 'x' }] };
      },
    };
    await methods.loadDossierFeed.call(ctx);
    assert.strictEqual(calls.length, 1, 'один запрос ленты');
    assert.ok(calls[0].indexOf('chat_id=-100') >= 0,
      'выбранный чат реально фильтрует запрос (S15-03)');
    assert.strictEqual(ctx.dossierFeed.length, 1);
    assert.strictEqual(ctx.dossierFeedLoaded, true);
    ctx.activeChatId = null;
    await methods.loadDossierFeed.call(ctx);
    assert.strictEqual(calls[1].indexOf('chat_id'), -1,
      'global-область не отправляет chat_id');
  }

  // 7b. Смена области во время запроса → старый ответ отброшен.
  {
    let resolveApi;
    const ctx = {
      activeChatId: -100, dossierFeedBusy: false, dossierFeed: [],
      dossierFeedError: '', dossierFeedLoaded: false, dossierFeedAt: 0,
      scopeEpoch: 1,
      _scopeGuard(ep) { return ep === this.scopeEpoch; },
      loreErrText(e) { return String(e); },
      api() { return new Promise(function (r) { resolveApi = r; }); },
    };
    const load = methods.loadDossierFeed.call(ctx);
    ctx.scopeEpoch = 2;                 // чат сменился до ответа
    resolveApi({ items: [{ chat_id: -100, name: 'A', excerpt: 'stale' }] });
    await load;
    assert.strictEqual(ctx.dossierFeed.length, 0,
      'ответ прошлой области не попадает в новый чат');
    assert.strictEqual(ctx.dossierFeedLoaded, false,
      'stale-ответ не выдаёт себя за загруженную ленту');
    assert.strictEqual(ctx.dossierFeedBusy, false, 'busy снят');
  }

  // 7c. Ошибка текущей области — честный error, не нули/чужие данные.
  {
    const ctx = {
      activeChatId: -100, dossierFeedBusy: false, dossierFeed: [],
      dossierFeedError: '', dossierFeedLoaded: false, dossierFeedAt: 0,
      scopeEpoch: 3,
      _scopeGuard(ep) { return ep === this.scopeEpoch; },
      loreErrText(e) { return 'HTTP ' + e.status; },
      async api() { throw Object.assign(new Error('x'), { status: 503 }); },
    };
    await methods.loadDossierFeed.call(ctx);
    assert.strictEqual(ctx.dossierFeedError, 'HTTP 503',
      '503 назван причиной, а не пустой лентой');
    assert.deepStrictEqual(ctx.dossierFeed, []);
  }

  // 7d. Сброс области очищает снимок и останавливает прежний поллер.
  {
    let stopped = 0;
    const ctx = {
      dossierFeed: [{ name: 'A' }], dossierFeedLoaded: true,
      dossierFeedAt: 123, dossierFeedError: 'old', dossierFeedBusy: true,
      stopDossierFeedPolling() { stopped += 1; },
    };
    methods._resetDossierFeedScope.call(ctx);
    assert.deepStrictEqual(ctx.dossierFeed, []);
    assert.strictEqual(ctx.dossierFeedLoaded, false);
    assert.strictEqual(ctx.dossierFeedAt, 0);
    assert.strictEqual(ctx.dossierFeedError, '');
    assert.strictEqual(ctx.dossierFeedBusy, false);
    assert.strictEqual(stopped, 1, 'старый поллер остановлен');
  }

  // 7e. Тот же endpoint; второго API/store нет.
  assert.strictEqual(JS.split("'/api/oversight/dossier_feed?limit=16'").length - 1, 1,
    'единственный запрос ленты досье');
  assert.strictEqual(JS.split('function _dossierPeopleRows').length - 1, 1,
    'одна проекция, без второго store');
  assert.ok(JS.indexOf('this.dossierFeed = (data && data.items) || []') >= 0,
    'данные берутся из существующего ответа dossier_feed');

  console.log('MOD-ACL-UX-M4B-B1-FEEDS-OK');
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
