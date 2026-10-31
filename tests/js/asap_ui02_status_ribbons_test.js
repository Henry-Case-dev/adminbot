'use strict';
/* ASAP-UI-02 (§5.3, wave 2): ОДНА карточка «Мониторинг интеллекта» — четыре
 * секции и переключатель на телефоне. Проверяется РЕАЛЬНЫЙ код `web/app.js`:
 *   * на десктопе/планшете переключение ничего не скрывает и не теряет;
 *   * на телефоне активна одна секция, данные не перезапрашиваются (все
 *     четыре ленты отрисованы постоянно), позиции прокрутки сохраняются:
 *     скрытая секция не перезаписывает свою позицию нулём, а возвращённая —
 *     восстанавливает её и пересчитывается без скачка в начало;
 *   * неизвестный/повторный id — no-op (нет лишних перерисовок).
 * Запуск: node tests/js/asap_ui02_status_ribbons_test.js → ASAP-UI02-RIBBONS-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');

/* ── Разметка: ровно четыре секции в одной карточке ──────────────────────── */
const cardStart = INDEX.indexOf('class="card p-4 sg-12 intel-card"');
const cardEnd = INDEX.indexOf('<!-- ═══ ASAP-UI-02 (§5.4', cardStart);
assert.ok(cardStart > 0 && cardEnd > cardStart, 'единая карточка найдена');
const CARD = INDEX.slice(cardStart, cardEnd);
assert.strictEqual(CARD.split('class="ribbon ').length - 1, 4,
  'четыре секции в одной карточке');
['facts', 'beliefs', 'paradigms', 'traits'].forEach(function (id) {
  assert.ok(CARD.indexOf('data-intel-section="' + id + '"') >= 0, id);
  assert.ok(CARD.indexOf('data-ribbon="' + id + '"') >= 0,
    id + ': ключ секции для сохранения позиции');
});
assert.ok(CARD.indexOf('data-intel-switcher') >= 0, 'переключатель секций');
assert.ok(CARD.indexOf(':data-intel-tab="statusRibbonTab"') >= 0,
  'активная секция — в data-атрибуте контейнера');
assert.ok(CARD.indexOf('switchStatusRibbon(t.id)') >= 0, 'клик переключает секцию');
assert.ok(CARD.indexOf(':aria-pressed="statusRibbonTab === t.id') >= 0,
  'состояние переключателя доступно AT');
assert.ok(CARD.indexOf('ref="intelSections"') >= 0, 'корень для позиций прокрутки');
assert.ok(INDEX.indexOf('class="card p-4 status-facts') < 0,
  'отдельной нижней карточки «Новые факты» больше нет');
assert.ok(INDEX.indexOf('Что бот недавно запомнил') >= 0,
  'подзаголовок «Новых фактов» сохранён');

/* ── CSS: 4 / 2×2 / одна секция ──────────────────────────────────────────── */
assert.ok(/\.cognition-ribbons \{[\s\S]{0,200}repeat\(2, minmax\(0, 1fr\)\)/.test(CSS),
  'планшет: 2×2');
assert.ok(/@media \(min-width: 1100px\) \{\s*\.cognition-ribbons \{ grid-template-columns: repeat\(4, minmax\(0, 1fr\)\); \}/.test(CSS),
  'desktop: четыре колонки');
assert.ok(CSS.indexOf('.cognition-ribbons[data-intel-tab] .ribbon { display: none; }') >= 0,
  'телефон: одна секция на экране');
assert.ok(/@media \(max-width: 640px\) \{[^@]*\.cognition-ribbons\[data-intel-tab\]/.test(CSS),
  'правило одной секции действует только на телефоне');
['facts', 'beliefs', 'paradigms', 'traits'].forEach(function (id) {
  assert.ok(CSS.indexOf('.cognition-ribbons[data-intel-tab="' + id + '"] .ribbon--' + id) >= 0,
    'телефон: активная секция ' + id + ' видна');
});
assert.ok(/\.intel-tabs \{ display: none; \}/.test(CSS),
  'переключатель не тратит место на десктопе');

/* ── B1 (review-fix2): у секции «Сердцебиение» — СВОЯ тонируемая поверхность,
 * тот же механизм и тот же сигнал, что у видимой строки состояния. ────────── */
const hbIdx = INDEX.indexOf('class="hb-surface"');
assert.ok(hbIdx > 0, 'у «Сердцебиения» есть собственная поверхность');
const HB = INDEX.slice(hbIdx, hbIdx + 400);
assert.ok(HB.indexOf('subsystem="heartbeat"') >= 0, 'поверхность — подсистема heartbeat');
assert.ok(HB.indexOf(':source="heartbeatHealthSource"') >= 0,
  'состояние поверхности берётся из адаптера сердебиения (не второй сигнал)');
assert.ok(HB.indexOf(':status-line="false"') >= 0,
  'собственный инлайн-статус компонента отключён — текста-дубля нет');
assert.ok(INDEX.indexOf('data-health-inline="heartbeat"') >= 0,
  'каноническая строка состояния осталась');
assert.ok(INDEX.indexOf('class="card p-4 status-block"') > 0);

/* ── B2 (EVOL-033 §A): тач-цель переключателя — 44×44 в СОБСТВЕННОМ правиле,
 * а не только через `@media (pointer: coarse)` (узкое окно без touch). ───── */
const tabsRule = /\.intel-tabs \.intel-tabs__btn \{[^}]*\}/.exec(CSS);
assert.ok(tabsRule, 'правило тач-цели переключателя найдено');
assert.ok(/min-height:\s*var\(--control-h-touch,\s*44px\)/.test(tabsRule[0]),
  'высота тач-цели переключателя 44px');
assert.ok(/min-width:\s*var\(--control-h-touch,\s*44px\)/.test(tabsRule[0]),
  'ширина тач-цели переключателя 44px');
assert.ok(CSS.indexOf('.intel-tabs .intel-tabs__btn { min-height: 36px; }') < 0,
  'прежние 36px не возвращаются');

/* ── Реальный код app.js ─────────────────────────────────────────────────── */
global.Vue = { createApp(opts) {
  global.__opts = opts;
  return { component() {}, provide() {}, use() {}, mount() {} };
} };
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null,
  innerWidth: 390, innerHeight: 844 };
global.document = {
  documentElement: { setAttribute() {}, getAttribute() { return null; },
    classList: { toggle() {}, contains() { return false; } },
    style: { setProperty() {}, removeProperty() {} } },
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { tagName: 'div', className: '', value: '', style: {},
    setAttribute() {}, focus() {}, select() {}, remove() {} }; },
  querySelector() { return null; }, querySelectorAll() { return []; },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', { configurable: true,
  value: { clipboard: { writeText: async () => { throw new Error('no'); } } } });
global.sessionStorage = { _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; } };
global.localStorage = { _s: {}, getItem(k) {
    return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; } };
global.history = { replaceState() {} };
global.Chart = function () {};
let fetchCalls = 0;
global.fetch = async function () { fetchCalls += 1; throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
const methods = (global.__opts && global.__opts.methods) || {};
['switchStatusRibbon', 'captureStatusRibbonPositions',
 'restoreStatusRibbonPositions', 'refreshIntelWidget'].forEach(function (m) {
  assert.strictEqual(typeof methods[m], 'function', 'метод ' + m);
});

/* Данные карточки: список секций объявлен явно (не выводится из DOM). */
const dataFn = global.__opts.data;
assert.strictEqual(typeof dataFn, 'function', 'data() есть');
const data = dataFn.call({});
assert.strictEqual(data.statusRibbonTabs.length, 4, 'четыре секции в переключателе');
assert.deepStrictEqual(data.statusRibbonTabs.map((t) => t.id),
  ['facts', 'beliefs', 'paradigms', 'traits']);
assert.strictEqual(data.statusRibbonTab, 'facts', 'по умолчанию — «Факты»');

/* ── Поведение переключателя (fake DOM, реальные методы) ─────────────────── */
function mkEl(name, visible) {
  return {
    name: name, clientHeight: visible ? 168 : 0, scrollTop: 0,
    getAttribute(k) { return k === 'data-ribbon' ? name : null; },
    __sfeed: { refreshes: 0, refresh() { this.refreshes += 1; } },
  };
}
const els = {
  facts: mkEl('facts', true),
  beliefs: mkEl('beliefs', false),
  paradigms: mkEl('paradigms', false),
  traits: mkEl('traits', false),
};
const root = { querySelectorAll() { return [els.facts, els.beliefs, els.paradigms, els.traits]; } };

function makeVm() {
  const vm = {
    statusRibbonTab: 'facts',
    statusRibbonTabs: data.statusRibbonTabs,
    $refs: { intelSections: root },
    $nextTick(fn) { fn(); return Promise.resolve(); },
    _intelRibbonPos: undefined,
  };
  vm.switchStatusRibbon = methods.switchStatusRibbon;
  vm.captureStatusRibbonPositions = methods.captureStatusRibbonPositions;
  vm.restoreStatusRibbonPositions = methods.restoreStatusRibbonPositions;
  return vm;
}

/* 1) Позиция активной секции снимается и НЕ теряется при уходе в другую. */
const vm = makeVm();
els.facts.scrollTop = 46;
vm.switchStatusRibbon('beliefs');
assert.strictEqual(vm.statusRibbonTab, 'beliefs', 'секция переключилась');
assert.strictEqual(vm._intelRibbonPos.facts, 46, 'позиция «Фактов» сохранена');
assert.strictEqual(fetchCalls, 0, 'переключение не перезапрашивает данные');

/* 2) Возврат: скрытая секция не перезаписала позицию нулём, при показе —
      позиция восстановлена и контроллер пересчитан без скачка. */
els.facts.clientHeight = 0;                 // «Факты» скрыты CSS
els.beliefs.clientHeight = 168;             // видимая теперь «Убеждения»
els.beliefs.scrollTop = 12;
vm.switchStatusRibbon('facts');
assert.strictEqual(vm._intelRibbonPos.beliefs, 12, 'позиция «Убеждений» сохранена');
assert.strictEqual(vm._intelRibbonPos.facts, 46, 'позиция «Фактов» не сброшена');
assert.strictEqual(els.facts.scrollTop, 46, 'позиция восстановлена при показе');
assert.ok(els.facts.__sfeed.refreshes >= 1,
  'контроллер ленты пересчитан — движение продолжится с текущей позиции');
assert.strictEqual(fetchCalls, 0, 'данные не перезапрашивались и на возврате');

/* 3) Неизвестная секция и повторный выбор — no-op (нет лишних перерисовок). */
const before = JSON.stringify(vm._intelRibbonPos);
vm.switchStatusRibbon('unknown');
vm.switchStatusRibbon('facts');
assert.strictEqual(vm.statusRibbonTab, 'facts', 'неизвестный id игнорируется');
assert.strictEqual(JSON.stringify(vm._intelRibbonPos), before, 'состояние не дрогнуло');

/* 4) «Обновить» единого виджета дёргает ОБА существующих запроса. */
let cognition = 0;
let dossier = 0;
methods.refreshIntelWidget.call({
  loadCognition() { cognition += 1; },
  loadDossierFeed() { dossier += 1; },
});
assert.strictEqual(cognition, 1, 'cognition обновляется');
assert.strictEqual(dossier, 1, 'dossier_feed обновляется');

console.log('ASAP-UI02-RIBBONS-OK');
