'use strict';
/* CMV-D (EPIC-CM-VISUAL-01) — fullscreen, инспектор, мобильный лист, счётчики.
 *
 * TEST-LIFECYCLE: CONTRACT owner=EPIC-CM-VISUAL-01 (CMV-D)
 * Спека: `plans/current_task.md` §3.1/§3.2 (компоновка полного экрана и
 * телефона), §8.2 (инспектор в трёх местах показа), §9.9 (четыре счётчика),
 * §11 (ошибка/пусто/смена чата), §13 (визуальные и функциональные гейты).
 *
 * Берётся НАСТОЯЩИЙ код `web/app.js` (`methods`/`computed` из `Vue.createApp`)
 * и настоящий адаптер `web/static/cognitive-map.js`. DOM — минимальный, но
 * поведение то же: фокус уходит на BODY, если элемент отвязан от документа.
 *
 * Что доказывается:
 *   1) раскладка заглушек не сходится в одну точку («комок» мобильного
 *      `simple`-режима) и детерминирована;
 *   2) счётчики различают БД / API / на экране и не смешивают их;
 *   3) «Показана часть графа» включается по факту усечения и объясняет его;
 *   4) карточка переезжает в слот своего режима (колонка / панель под сценой);
 *   5) «Перейти» к соседу переводит камеру, обновляет выбор и карточку;
 *   6) жесты листа: вверх — раскрыть, вниз — свернуть/закрыть;
 *   7) смена чата гасит модель прежнего чата и отбрасывает его поздний ответ;
 *   8) отказ загрузки виден словами, сохраняет last-known-good и снимается
 *      успешным повтором;
 *   9) фокус после закрытия полного экрана возвращается на кнопку открытия.
 *
 * Мутации (`plans/features/epic-cm-visual-01/evidence/cmv-d/mutations.py`)
 * краснят эти проверки.
 *
 * Запуск: node tests/js/evol_cmv_d_fullscreen_test.js → EVOL-CMV-D-OK
 */
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

let checks = 0;
function ok(cond, message) {
  assert.ok(cond, message);
  checks += 1;
}
function eq(actual, expected, message) {
  assert.deepStrictEqual(actual, expected, message);
  checks += 1;
}

// ── минимальный DOM ────────────────────────────────────────────────────────
const body = {
  __name: 'body', tagName: 'BODY',
  focus() { doc.activeElement = body; },
  querySelectorAll() { return []; },
  classList: { add() {}, remove() {}, contains() { return false; } },
};

function makeEl(name, tag) {
  const el = {
    __name: name, tagName: tag || 'DIV', children: [],
    parentNode: null, isConnected: true,
    focus() {
      // Браузер уводит фокус на BODY, если элемент не в документе.
      doc.activeElement = el.isConnected === false ? body : el;
    },
    appendChild(child) {
      if (child.parentNode) {
        const list = child.parentNode.children;
        const idx = list.indexOf(child);
        if (idx >= 0) list.splice(idx, 1);
      }
      this.children.push(child);
      child.parentNode = this;
      child.isConnected = this.isConnected !== false;
      return child;
    },
    contains(other) {
      if (other === this) return true;
      return this.children.indexOf(other) >= 0;
    },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { width: 100, height: 100 }; },
    classList: { add() {}, remove() {}, contains() { return false; } },
  };
  return el;
}

const doc = {
  activeElement: body,
  addEventListener() {}, removeEventListener() {},
  getElementById() { return null; },
  createElement(tag) { return makeEl('created-' + tag, String(tag).toUpperCase()); },
  body: body,
  execCommand() { return true; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, removeEventListener() {},
  Telegram: null, document: doc, innerWidth: 1280, innerHeight: 900,
  requestAnimationFrame() { return 1; }, cancelAnimationFrame() {},
};
global.document = doc;
Object.defineProperty(global, 'navigator', {
  value: { clipboard: { writeText: async function () {} } },
  configurable: true,
});
global.localStorage = {
  getItem() { return null; }, setItem() {}, removeItem() {},
};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;

// Адаптер карты — настоящий (не подделка): модель/карточки/счётчики.
const CM = require(path.join(ROOT, 'web', 'static', 'cognitive-map.js'));
global.window.CognitiveMap = CM;

const CHAT = -1001234567890;
const FAN = 5;

function nodeRow(id, kind, title) {
  const tail = String(id).split(':').pop();
  return {
    id: id, kind: kind, scope: 'chat', chat_id: CHAT, title: title,
    text: title, status: null, isolated: false,
    time: {}, provenance: { fact_id: Number(tail) || 1 },
    metrics: {}, refs: {},
  };
}

function payload(extra) {
  // Хаб `fact:11` соединён с FAN фактами: у всех «новых» узлов есть
  // РАЗМЕЩЁННЫЙ сосед — именно этот путь давал «центроид + 22» всем сразу.
  const nodes = [
    nodeRow('ent:' + CHAT + ':1', 'entity', 'Аня'),
    nodeRow('fact:' + CHAT + ':11', 'fact', 'Аня любит утренний кофе'),
    nodeRow('belief:' + CHAT + ':21', 'belief', 'Утро начинается с кофе'),
    nodeRow('obs:' + CHAT + ':41', 'observation', 'Любит сарказм'),
  ];
  const edges = [
    { id: 'e1', from: 'ent:' + CHAT + ':1', to: 'fact:' + CHAT + ':11',
      relation: 'обсуждали', derived: false, chat_id: CHAT,
      justification_recorded: true, provenance: { fact_id: 11 } },
    { id: 'e2', from: 'belief:' + CHAT + ':21', to: 'fact:' + CHAT + ':11',
      relation: 'derived_from', derived: true, chat_id: CHAT,
      justification_recorded: true, provenance: { fact_id: 11 } },
  ];
  for (let i = 0; i < FAN; i += 1) {
    const id = 'fact:' + CHAT + ':' + (300 + i);
    nodes.push(nodeRow(id, 'fact', 'Фан ' + i));
    edges.push({ id: 'fan' + i, from: 'fact:' + CHAT + ':11', to: id,
                 relation: 'обсуждали', derived: false, chat_id: CHAT,
                 justification_recorded: true, provenance: {} });
  }
  const total = nodes.length;
  const base = {
    version: 'cog-map/1', generated_at: Math.floor(Date.now() / 1000) - 5,
    state: 'partial', scope: { mode: 'chat', chat_id: CHAT },
    degraded: { active: false, not_loaded: [] },
    sources: { facts: 'loaded', graph: 'loaded' },
    caps: { nodes: 800, edges: 2400 },
    shown_of: {
      nodes: total, edges: edges.length,
      totals: { nodes: 320, edges: 40 }, unresolved_refs: 0,
      by_kind: {
        fact: { shown: FAN + 1, total: 300, truncated: true },
        entity: { shown: 1, total: 20, truncated: true },
      },
    },
    truncated: { nodes: true, edges: true, by_class: {} },
    nodes: nodes, edges: edges,
  };
  return Object.assign(base, extra || {});
}

function makeVm() {
  const vm = Object.assign({}, methods);
  Object.keys(computed).forEach(function (key) {
    Object.defineProperty(vm, key, {
      get: function () { return computed[key].call(vm); },
      configurable: true,
    });
  });
  // Часть computed выводится из серверного профиля — в тесте задаём факт.
  Object.defineProperty(vm, 'isGlobalAdmin', {
    get: function () { return true; }, configurable: true,
  });
  vm.activeChatId = CHAT;
  vm.activeTab = 'status';
  vm.reducedMotion = false;
  vm.toastLog = [];
  vm.toast = function (msg) { vm.toastLog.push(String(msg)); };
  vm.summaryAliasesMap = function () { return {}; };
  vm.apiCalls = [];
  vm.apiCtx = [];
  vm.api = async function (url) {
    vm.apiCalls.push(url);
    vm.apiCtx.push(vm.activeChatId);
    if (vm.apiFails) throw vm.apiFails;
    if (vm.apiHangs) {
      return new Promise(function (resolve, reject) {
        vm.release = function () { resolve(payload()); };
        vm.releaseErr = function (e) { reject(e); };
      });
    }
    return payload();
  };
  vm.$nextTick = function (fn) { if (fn) fn(); };
  vm.$refs = {};
  vm.cognitionGraphData = null;
  vm.cognitionNetwork = null;
  vm._cogScene = null;
  vm.cogCard = null;
  vm.cogCardLinksExpanded = false;
  vm.cogCardEmbedExpanded = true;
  vm.cogCardSheetExpanded = false;
  vm.cogCounts = null;
  vm._cogCountsSig = null;
  vm.cogLoadError = null;
  vm.cogViewNodes = 0;
  vm.cogViewEdges = 0;
  vm._cogView = null;
  vm.graphFullOpen = false;
  vm.route = '#/';
  vm.graphSearchStatus = '';
  vm.renderCalls = 0;
  vm.renderCognitionGraph = async function () { vm.renderCalls += 1; };
  vm.graphClearDetail = function () { vm._cleared = true; };
  vm.graphSelectNode = function (id) { vm._graphDetailFor = id; };
  vm.graphApplySelectionLabels = function (ids) { vm._sel = ids.slice(); };
  vm._cogPulseSelected = function () { vm._pulsed = (vm._pulsed || 0) + 1; };
  vm._cogFitScale = 2;
  return vm;
}

function normalize(p) {
  return CM.normalizePayload(p, { aliases: {} });
}

// ── 1. раскладка заглушек: «комок» не воспроизводится ──────────────────────
{
  const vm = makeVm();
  vm.cognitionGraphData = normalize(payload());
  const hubId = 'fact:' + CHAT + ':11';
  const positions = {};
  positions[hubId] = { x: 100, y: 40 };
  const placed = [];
  for (let i = 0; i < FAN; i += 1) {
    const id = 'fact:' + CHAT + ':' + (300 + i);
    const p = vm._cogFallbackPosition({ id: id }, positions);
    positions[id] = p;
    placed.push(p);
  }
  let min = Infinity;
  for (let i = 0; i < placed.length; i += 1) {
    for (let j = i + 1; j < placed.length; j += 1) {
      const d = Math.hypot(placed[i].x - placed[j].x, placed[i].y - placed[j].y);
      if (d < min) min = d;
    }
  }
  ok(min > 20, 'новые узлы с общим соседом встают в разные точки (' + min + ')');
  ok(placed.every(function (p) { return p.x !== 122 || p.y !== 62; }),
     'катастрофическая точка «центроид + 22/+22» больше не используется');

  // Детерминизм: тот же вход — тот же кадр (Math.random нет).
  const positions2 = {};
  positions2[hubId] = { x: 100, y: 40 };
  const again = [];
  for (let i = 0; i < FAN; i += 1) {
    const id = 'fact:' + CHAT + ':' + (300 + i);
    positions2[id] = vm._cogFallbackPosition({ id: id }, positions2);
    again.push(positions2[id]);
  }
  eq(again, placed, 'раскладка заглушек детерминирована');

  const orphan = vm._cogFallbackPosition({ id: 'fact:' + CHAT + ':999' }, {});
  ok(Math.hypot(orphan.x, orphan.y) > 30,
     'сирота не встаёт в центр кадра (' + JSON.stringify(orphan) + ')');
}

// ── 2. счётчики: БД / API / на экране раздельно ────────────────────────────
{
  const vm = makeVm();
  vm.cognitionGraphData = normalize(payload());
  vm._cogView = { nodes: vm.cognitionGraphData.nodes,
                  edges: vm.cognitionGraphData.edges };
  vm.cogViewNodes = vm._cogView.nodes.length;
  vm.cogViewEdges = vm._cogView.edges.length;
  vm.cogCounts = vm._cogCounts();
  const byKey = {};
  vm.cogCounterParts.forEach(function (p) { byKey[p.key] = p.text; });
  ok(byKey.db && byKey.db.indexOf('320') >= 0,
     'счётчики: «в базе» из серверного итога (' + byKey.db + ')');
  ok(byKey.api && byKey.api.indexOf((FAN + 4) + ' узлов') >= 0,
     'счётчики: «из API» — принятые узлы (' + byKey.api + ')');
  ok(byKey.db !== byKey.api, 'счётчики не смешивают БД и API');
  eq(vm.cogCounters.indexOf('в базе'), 0,
     'счётчики начинаются с «в базе», когда сервер его прислал');

  // Сервер не отдал итог — «в базе» не выдумывается.
  const unknown = payload();
  delete unknown.shown_of.totals;
  delete unknown.shown_of.by_kind;
  vm.cognitionGraphData = normalize(unknown);
  vm.cognitionGraphData.shownOf.totals = {};
  vm._cogCountsSig = null;
  vm.cogCounts = vm._cogCounts();
  const keys2 = vm.cogCounterParts.map(function (p) { return p.key; });
  eq(keys2.indexOf('db'), -1, 'без серверного итога «в базе» не показывается');

  // Свёрнутые в районы узлы: «на экране» — отдельная величина.
  const withAgg = makeVm();
  withAgg.cognitionGraphData = normalize(payload());
  withAgg._cogView = { nodes: withAgg.cognitionGraphData.nodes, edges: [] };
  withAgg.cogViewNodes = 11;
  withAgg.cogViewEdges = 0;
  withAgg._cogScene = { lod: 0, aggregates: [
    { apexId: 'a', memberIds: ['m1', 'm2'], count: 2, hideMembers: true },
    { apexId: 'b', memberIds: ['m3'], count: 1, hideMembers: true },
  ] };
  withAgg.cogCounts = withAgg._cogCounts();
  const screenPart = withAgg.cogCounterParts
    .filter(function (p) { return p.key === 'screen'; })[0];
  ok(screenPart && screenPart.text.indexOf('районов') >= 0,
     'счётчики: «на экране» с районами (' + (screenPart && screenPart.text) + ')');
  ok(screenPart.text.indexOf('3') >= 0,
     'счётчики: число свёрнутых записей честное (' + screenPart.text + ')');
  eq(withAgg.cogCounterParts.filter(function (p) {
    return p.key === 'screen';
  }).length, 1, '«на экране» показывается один раз, а не дублируется');
}

// ── 3. подсказка жестов: строка 4 §2.2 (CMV-HDR-04) ────────────────────────
{
  const vm = makeVm();
  vm.cognitionGraphData = normalize(payload());
  eq(vm.cogHintText,
     'Колесо/щипок — масштаб · Перетаскивание — перемещение · Нажатие — связи',
     'текст подсказки ровно из спеки');
  ok(vm.cogHintVisible === true, 'при входе подсказка показана');
  vm._cogHintDone();
  ok(vm.cogHintVisible === false,
     'после первого действия подсказка не занимает место');
  vm._cogHintDone();
  ok(vm.cogHintVisible === false, 'повторный вызов идемпотентен');
}

// ── 4. «Показана часть графа» ──────────────────────────────────────────────
{
  const vm = makeVm();
  ok(vm.cogTruncated.active === false,
     'без данных «Показана часть графа» не показывается');
  vm.cognitionGraphData = normalize(payload());
  ok(vm.cogTruncated.active === true, 'усечённый ответ помечается');
  ok(vm.cogTruncated.hint.indexOf('сервер не отдал') >= 0,
     'усечение объяснено словами (' + vm.cogTruncated.hint + ')');
  ok(vm.cogTruncated.hint.indexOf((FAN + 4) + ' из 320') >= 0,
     'в объяснении реальные числа (' + vm.cogTruncated.hint + ')');
  const complete = payload({
    truncated: { nodes: false, edges: false, by_class: {} },
    shown_of: { nodes: 9, edges: 6, totals: { nodes: 9, edges: 6 },
                by_kind: {} },
  });
  vm.cognitionGraphData = normalize(complete);
  ok(vm.cogTruncated.active === false,
     'полный ответ не помечается как усечённый');
}

// ── 4. место показа карточки (телепорт в слот своего режима) ───────────────
{
  const vm = makeVm();
  vm.cogCard = { kind: 'node', id: 'fact:' + CHAT + ':11' };
  eq(vm.cogCardPlacement, 'embed', 'встроенная карта — панель под сценой');
  eq(vm.cogCardSlot, '#cog-embed-inspector', 'слот встроенной карты');
  ok(vm.cogCardClasses['cog-card--embed'] === true,
     'класс места показа выставлен');
  ok(!vm.cogCardClasses['cog-card--dock'],
     'во встроенной карте карточка не стыкуется колонкой');

  vm.graphFullOpen = true;
  eq(vm.cogCardPlacement, 'full', 'полный экран — колонка справа');
  eq(vm.cogCardSlot, '#cog-inspector-slot', 'слот колонки полного экрана');
  ok(vm.cogCardClasses['cog-card--dock'] === true,
     'в полном экране карточка стыкуется колонкой');
  // Второй карточки нет: перенос делает разметка (`<teleport :to="cogCardSlot">`),
  // поэтому ручного переноса DOM в модели не остаётся.
  eq(typeof vm._cogMountCard, 'undefined', 'ручной перенос узла не нужен');
  eq(typeof vm._cogRetargetCard, 'undefined', 'переустановки слота нет');
}

// ── 5. «Снять выбор» (CMV-CARD-06): снимает ВЫБОР, не камеру ───────────────
{
  const vm = makeVm();
  vm.cognitionGraphData = normalize(payload());
  const selCalls = [];
  vm.cognitionNetwork = {
    selectNodes(ids) { selCalls.push(ids.slice()); },
    focus() { throw new Error('«Снять выбор» не двигает камеру'); },
  };
  vm.openCogNodeCard('fact:' + CHAT + ':11');
  vm._cogSelectedId = 'fact:' + CHAT + ':11';
  vm._cogEdgeFocus = 'edge:1';
  vm._cogHighlight = { nodes: ['fact:' + CHAT + ':11'] };
  vm.clearCogSelection();
  eq(vm.cogCard, null, 'карточка закрыта после «Снять выбор»');
  eq(vm._cogSelectedId, null, 'выбор снят');
  eq(vm._cogEdgeFocus, null, 'фокус ребра снят');
  eq(vm._sel, [], 'подсветка снята');
  ok(selCalls.length >= 1 && selCalls[selCalls.length - 1].length === 0,
     'сеть больше не считает узел выбранным');
  ok(vm._cleared === true, 'детали выбранной записи очищены');
}

// ── 6. «Перейти» к соседу ──────────────────────────────────────────────────
{
  const vm = makeVm();
  vm.cognitionGraphData = normalize(payload());
  const calls = [];
  vm.cognitionNetwork = {
    focus(id, opts) { calls.push(['focus', id, opts && opts.scale]); },
    selectNodes(ids) { calls.push(['select', ids.slice()]); },
  };
  const target = 'ent:' + CHAT + ':1';
  vm.openCogNodeCard('fact:' + CHAT + ':11');
  const card = vm.cogFocusNeighbor(target);
  ok(calls.length >= 2, 'переход к соседу трогает камеру и выбор');
  eq(calls[0][0], 'focus', 'сначала фокус камеры');
  eq(calls[0][1], target, 'камера переводится к выбранному соседу');
  ok(calls[0][2] > vm._cogFitScale,
     'масштаб фокуса взят от обзора (' + calls[0][2] + ')');
  eq(vm._sel, [target], 'подсветка обновлена на соседа');
  eq(vm._graphDetailFor, target, 'панель подробностей — про соседа');
  ok(card && card.kind === 'node' && String(card.id) === String(target),
     'карточка показывает соседа');
  ok(vm._pulsed >= 1, 'выбор соседа даёт импульс (§7.2 спеки)');
}

// ── 7. жесты листа ─────────────────────────────────────────────────────────
{
  const vm = makeVm();
  vm.cognitionGraphData = normalize(payload());
  vm.openCogNodeCard('fact:' + CHAT + ':11');
  let prevented = 0;
  vm.cogSheetTouchStart({ touches: [{ clientY: 400 }] });
  vm.cogSheetTouchMove({ touches: [{ clientY: 300 }],
                         preventDefault() { prevented += 1; } });
  vm.cogSheetTouchEnd();
  ok(vm.cogCardSheetExpanded === true, 'свайп вверх раскрывает лист');
  ok(prevented === 1, 'движение пальца по ручке не прокручивает страницу');

  vm.cogSheetTouchStart({ touches: [{ clientY: 300 }] });
  vm.cogSheetTouchMove({ touches: [{ clientY: 420 }], preventDefault() {} });
  vm.cogSheetTouchEnd();
  ok(vm.cogCardSheetExpanded === false, 'свайп вниз сворачивает раскрытый лист');
  ok(vm.cogCardOpen === true, 'сворачивание не закрывает карточку');

  vm.cogSheetTouchStart({ touches: [{ clientY: 300 }] });
  vm.cogSheetTouchMove({ touches: [{ clientY: 460 }], preventDefault() {} });
  vm.cogSheetTouchEnd();
  eq(vm.cogCard, null, 'свайп вниз по свёрнутому листу закрывает карточку');
  ok(vm.cogCardEmbedExpanded === true,
     'следующая запись открывается в развёрнутой панели');
}

// ── 8. смена чата ──────────────────────────────────────────────────────────
{
  const vm = makeVm();
  vm._cogChatId = undefined;
  vm.activeChatId = CHAT;
  vm._cogInvalidateForChatSwitch();
  vm.cognitionGraphData = normalize(payload());
  vm.openCogNodeCard('fact:' + CHAT + ':11');
  const callsBefore = vm.apiCalls.length;
  vm.activeChatId = CHAT;
  vm._cogInvalidateForChatSwitch();
  eq(vm.apiCalls.length, callsBefore,
     'тот же чат не перезапрашивает карту');
  vm.activeChatId = -1009999999999;
  vm._cogInvalidateForChatSwitch();
  eq(vm.cognitionGraphData, null, 'модель прежнего чата сброшена сразу');
  eq(vm.cogCard, null, 'карточка прежнего чата закрыта');
  eq(vm.cogViewNodes, 0, 'видимый набор прежнего чата обнулён');
  ok(vm.apiCalls.length > callsBefore, 'карта перезапрошена для нового чата');
  ok(vm.apiCalls[vm.apiCalls.length - 1].indexOf('-1009999999999') >= 0,
     'запрос ушёл с новым chat_id (' + vm.apiCalls[vm.apiCalls.length - 1] + ')');
  ok(vm.renderCalls >= 1, 'сцена перерисована (старый граф не остаётся)');
}

// ── 9. отказ загрузки + поздний ответ прежнего чата (async) ────────────────
(async function asyncPart() {
  {
    const vm = makeVm();
    vm._cogChatId = CHAT;
    vm.apiHangs = true;
    const pending = vm.loadCognitionGraph();
    vm._cogChatGen = (vm._cogChatGen || 0) + 1;   // чат сменился, пока шёл запрос
    vm.release();
    await pending;
    eq(vm.cognitionGraphData, null,
       'ответ прошлого чата не применён к новому контексту');
  }
  {
    const vm = makeVm();
    vm._cogChatId = CHAT;
    vm.cognitionGraphData = normalize(payload());
    const keep = vm.cognitionGraphData;
    vm.apiFails = new Error('сеть недоступна');
    await vm.loadCognitionGraph();
    ok(vm.cogLoadError && vm.cogLoadError.message === 'сеть недоступна',
       'ошибка загрузки запоминается (' + JSON.stringify(vm.cogLoadError) + ')');
    ok(vm.cogLoadErrorLabel.indexOf('сеть недоступна') >= 0,
       'ошибка названа в интерфейсе (' + vm.cogLoadErrorLabel + ')');
    eq(vm.cognitionGraphData, keep,
       'исправный last-known-good граф не стирается из-за отказа сети');
    ok(vm.toastLog.length >= 1, 'отказ не молчит (тост с причиной)');
    vm.apiFails = null;
    await vm.loadCognitionGraph();
    eq(vm.cogLoadError, null, 'успешный повтор снимает ошибку');
  }

  // ── 9. возврат фокуса на кнопку «Полный экран» ───────────────────────────
  {
    const vm = makeVm();
    const btn = makeEl('cog-open-full', 'BUTTON');
    vm.$refs.cogFullBtn = btn;
    vm._cogReturnFocusToFullBtn();
    eq(doc.activeElement, btn, 'фокус вернулся на кнопку открытия');
  }
  {
    // Ссылка появилась не сразу (маршрут/рендер): попытка повторяется.
    const vm = makeVm();
    const btn = makeEl('cog-open-full', 'BUTTON');
    let reads = 0;
    Object.defineProperty(vm, '$refs', {
      get: function () {
        reads += 1;
        return reads < 3 ? {} : { cogFullBtn: btn };
      },
    });
    const timers = [];
    const realSetTimeout = global.setTimeout;
    global.setTimeout = function (fn) { timers.push(fn); return timers.length; };
    try {
      vm._cogReturnFocusToFullBtn();
      while (timers.length) timers.shift()();
    } finally {
      global.setTimeout = realSetTimeout;
    }
    eq(doc.activeElement, btn,
       'фокус возвращается, если ссылка появилась на следующем кадре');
  }
  {
    // Ссылка ведёт на ОТВЯЗАННЫЙ узел (Vue уже заменил кнопку): фокус уходит
    // в BODY. Успех обязан проверяться, иначе попытки прекращаются и фокус
    // остаётся на BODY — а на следующем кадре живая кнопка уже есть.
    const vm = makeVm();
    const stale = makeEl('stale-btn', 'BUTTON');
    stale.isConnected = false;
    const live = makeEl('cog-open-full', 'BUTTON');
    let reads = 0;
    Object.defineProperty(vm, '$refs', {
      get: function () {
        // Выражение `self.$refs ? self.$refs.cogFullBtn : null` читает свойство
        // ДВА раза за попытку: поэтому первые две читки — отвязанный узел.
        reads += 1;
        return reads <= 2 ? { cogFullBtn: stale } : { cogFullBtn: live };
      },
    });
    doc.activeElement = body;
    const timers = [];
    const realSetTimeout = global.setTimeout;
    global.setTimeout = function (fn) { timers.push(fn); return timers.length; };
    try {
      vm._cogReturnFocusToFullBtn();
      let guard = 0;
      while (timers.length && guard < 20) { timers.shift()(); guard += 1; }
    } finally {
      global.setTimeout = realSetTimeout;
    }
    eq(doc.activeElement, live,
       'фокус на отвязанном узле не считается успехом — попытка повторяется');
  }
  {
    // Реально недостижимая кнопка: повторов ограниченное число (6), вечного
    // таймера не заводится.
    const vm = makeVm();
    const nowhere = makeEl('hidden-btn', 'BUTTON');
    nowhere.focus = function () { /* фокус не берётся (скрытый элемент) */ };
    vm.$refs.cogFullBtn = nowhere;
    const timers = [];
    const realSetTimeout = global.setTimeout;
    global.setTimeout = function (fn) { timers.push(fn); return timers.length; };
    let fired = 0;
    try {
      vm._cogReturnFocusToFullBtn();
      let guard = 0;
      while (timers.length && guard < 40) { timers.shift()(); fired += 1; guard += 1; }
    } finally {
      global.setTimeout = realSetTimeout;
    }
    ok(fired <= 6, 'повторы возврата фокуса ограничены (' + fired + ')');
  }

  // ── 10. нет модели — прежний граф снимается со сцены ─────────────────────
  {
    const vm = makeVm();
    const el = makeEl('cog-scene');
    el.closest = function () { return {}; };
    el.getBoundingClientRect = function () { return { width: 400, height: 300 }; };
    el.querySelector = function () { return null; };
    el.clientWidth = 400;
    el.clientHeight = 300;
    vm.$refs.cognitionGraph = el;
    vm.cognitionNetwork = { destroy() {} };
    vm._cogScene = { lod: 1 };
    let destroyed = 0;
    vm.destroyCognitionGraph = function () { destroyed += 1; };
    vm.cognitionGraphData = null;
    await methods.renderCognitionGraph.call(vm);
    eq(destroyed, 1,
       'без модели сцена сносится (граф прошлого чата не остаётся на экране)');
  }

  // ── 11. «Сбросить вид» — только камера, состояние выбора не рушится ───────
  // ЧТО ДОКАЗЫВАЕТСЯ: сброс кадра возвращает обзор, но НЕ снимает фильтр,
  // НЕ чистит запрос поиска, НЕ сбрасывает выделение/подсветку и НЕ меняет
  // число показанных узлов. Фильтры снимает отдельная кнопка.
  {
    const vm = makeVm();
    vm.cognitionGraphData = normalize(payload());
    // Рендер считает витрину из ТЕКУЩИХ фильтров — как настоящий
    // `renderCognitionGraph` через `CognitiveMap.applyFilters`.
    vm.renderCognitionGraph = async function () {
      const view = CM.applyFilters(vm.cognitionGraphData, {
        kinds: vm.graphFilterGroup ? [vm.graphFilterGroup] : [],
        cluster: vm.cognitionMapCluster || '',
        hideDerived: vm.cogHideDerived === true,
      });
      vm._cogView = view;
      vm.cogViewNodes = (view.nodes || []).length;
      vm.cogViewEdges = (view.edges || []).length;
    };
    let fits = 0;
    let fitAnim = null;
    vm._cogApplyFit = function (animate) { fits += 1; fitAnim = animate; return true; };
    let cardCloses = 0;
    vm.closeCogCard = function () { cardCloses += 1; };
    let detailClears = 0;
    vm.graphClearDetail = function () { detailClears += 1; };

    // Состояние пользователя: фильтр типа + поиск + выделение с подсветкой.
    vm.graphFilterGroup = 'fact';
    vm.cognitionMapCluster = '';
    vm.cogHideDerived = false;
    vm.graphSearchQuery = 'кофе';
    vm.graphSearchStatus = 'Найден: Любит утренний кофе без сахара';
    const selId = 'fact:' + CHAT + ':1';
    vm._cogSelectedId = selId;
    vm._cogHighlight = {};
    vm._cogHighlight[selId] = 1;
    await vm.renderCognitionGraph();
    const filteredNodes = vm.cogViewNodes;
    ok(filteredNodes > 0 && filteredNodes < vm.cognitionGraphData.nodes.length,
       'фикстура: фильтр типа реально сужает витрину (' + filteredNodes + ')');

    await methods.graphResetView.call(vm);
    await new Promise(function (r) { setImmediate(r); });

    eq(fits, 1, 'сброс вида ставит обзор кадра (_cogApplyFit)');
    eq(fitAnim, true, 'кадр возвращается анимацией общего вида');
    eq(vm.graphFilterGroup, 'fact', '«Сбросить вид» не снимает фильтр типа');
    eq(vm.cognitionMapCluster, '', '«Сбросить вид» не трогает фильтр кластера');
    eq(vm.cogHideDerived, false, '«Сбросить вид» не включает/не снимает производные');
    eq(vm.graphSearchQuery, 'кофе', '«Сбросить вид» сохраняет запрос поиска');
    eq(vm._cogSelectedId, selId, '«Сбросить вид» сохраняет выбранный узел');
    eq(vm._cogHighlight, (function () { const h = {}; h[selId] = 1; return h; })(),
       '«Сбросить вид» сохраняет подсветку связей');
    eq(vm.cogViewNodes, filteredNodes,
       'число узлов под фильтром после сброса вида не изменилось');
    eq(cardCloses, 0, '«Сбросить вид» не закрывает карточку выбранного узла');
    eq(detailClears, 0, '«Сбросить вид» не чистит подробности выбора');

    // Отдельная кнопка фильтров по-прежнему снимает фильтр и поиск.
    await methods.graphResetFilters.call(vm);
    await new Promise(function (r) { setImmediate(r); });
    eq(vm.graphFilterGroup, '', '«Сбросить фильтры» снимает фильтр типа');
    eq(vm.graphSearchQuery, '', '«Сбросить фильтры» чистит запрос поиска');
    eq(vm.cogViewNodes, vm.cognitionGraphData.nodes.length,
       'после снятия фильтра витрина снова показывает все узлы');
    ok(fits >= 1, '«Сбросить фильтры» тоже возвращает обзор кадра');
  }

  console.log('EVOL-CMV-D-OK checks=' + checks);
}()).catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
