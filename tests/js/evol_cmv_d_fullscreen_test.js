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
 *   3) «Отображена часть графа» включается по факту усечения, объясняет его
 *      и названа требуемой формулировкой в обоих местах показа;
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
const fs = require('fs');
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

// extra-узлы/рёбра ДОБАВЛЯЮТСЯ к базовой витрине (payload(extra) заменяет).
function merged(extra) {
  const base = payload();
  return payload({
    nodes: base.nodes.concat((extra && extra.nodes) || []),
    edges: base.edges.concat((extra && extra.edges) || []),
  });
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

// ── 4. «Отображена часть графа» (CMV-LODB-03) ──────────────────────────────
{
  const vm = makeVm();
  ok(vm.cogTruncated.active === false,
     'без данных «Отображена часть графа» не показывается');
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
  // CMV-LODB-03: видимая формулировка — ровно из карты требований, в обоих
  // местах показа (виджет + полный экран); старой формулировки нет.
  const html = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  ok((html.match(/data-cog-truncated/g) || []).length >= 2,
     'метка усечения есть в обоих местах показа (виджет + полный экран)');
  ok((html.match(/Отображена часть графа/g) || []).length >= 2,
     'формулировка метки — «Отображена часть графа» (CMV-LODB-03)');
  ok(html.indexOf('Показана часть графа') === -1,
     'старой формулировки «Показана часть графа» в разметке нет');
  // CMV-CARD-07: шапка карточки рендерит title из адаптера («Без названия»
  // для узла без заголовка), а сырой ID остаётся раскрытым в деталях.
  ok(/data-cog-card-title>\{\{ cogCard\.title \}\}</.test(html),
     'шапка карточки рендерит title из адаптера');
  ok(/v-if="cogCard\.titleAbsent"[\s\S]{0,160}data-cog-card-id-row/
       .test(html)
     && /data-cog-card-id-row[\s\S]{0,200}\{\{ cogCard\.id \}\}/.test(html),
     'ID записи без заголовка раскрывается строкой в деталях карточки');
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

  // ── 11. CMV-NAV-02: список различимых результатов, БЕЗ автофокуса ─────────
  {
    // Три одноимённых узла разных типов (как в пробе batch-2): список
    // обязателен, автофокус на первом одноимённом объекте запрещён;
    // детерминированный порядок и цикл Enter сохранены после списка.
    function extraDup() {
      return {
        nodes: [
          nodeRow('ent:' + CHAT + ':93', 'entity',
                  'Узел с исключительно длинным названием для поиска'),
          nodeRow('ent:' + CHAT + ':94', 'entity', 'Дубль показателя'),
          nodeRow('fact:' + CHAT + ':95', 'fact', 'Дубль показателя'),
          nodeRow('obs:' + CHAT + ':96', 'observation', 'Дубль показателя'),
        ],
        edges: [
          { id: 'xd1', from: 'ent:' + CHAT + ':1',
            to: 'ent:' + CHAT + ':94', relation: 'обсуждали',
            derived: false, chat_id: CHAT, justification_recorded: true,
            provenance: { fact_id: 1 } },
        ],
      };
    }
    const vm = makeVm();
    const model = normalize(merged(extraDup()));
    vm.cognitionGraphData = model;
    const calls = { focus: [], select: [] };
    vm.cognitionNetwork = {
      focus(id, opts) { calls.focus.push([id, opts]); },
      selectNodes(ids) { calls.select.push(ids.slice()); },
    };
    vm._cogView = { nodes: model.nodes, edges: model.edges };
    vm.graphSearchQuery = 'Дубль показателя';
    await methods.searchCognitionGraph.call(vm);
    eq(calls.focus.length, 0, 'NAV-02: первый поиск без автофокуса');
    eq(calls.select.length, 0, 'NAV-02: до выбора сеть ничего не выбирает');
    eq(vm._sel, undefined, 'NAV-02: подсветка выбора не ставилась');
    eq(vm._graphDetailFor, undefined, 'NAV-02: панель подробностей пуста');
    eq(vm.graphSearchResults.length, 3, 'NAV-02: все три совпадения в списке');
    ok(vm.graphSearchResults.every(function (r) {
      return r.title === 'Дубль показателя' && r.kindLabel && r.id;
    }), 'NAV-02: каждый результат различим (полное имя + тип + ID)');
    eq(vm.graphSearchResults.map(function (r) { return r.id; }),
       ['ent:' + CHAT + ':94', 'fact:' + CHAT + ':95',
        'obs:' + CHAT + ':96'],
       'NAV-02: детерминированный порядок в списке (поиск, не случай)');
    eq(vm.graphSearchStatus, 'Найдено: 3 — выберите из списка',
       'NAV-02: статус зовёт выбрать из списка, а не «Найден (1/3)»');
    eq(vm._graphSearchMatchIds.length, 3,
       'NAV-02: совпадения закреплены в fx независимо от выбора');
    // Цикл Enter сохранён и детерминирован (после первого списка).
    await methods.searchCognitionGraph.call(vm);
    eq(calls.focus[0][0], 'ent:' + CHAT + ':94', 'NAV-02: Enter №2 — первый');
    ok(String(vm.graphSearchStatus).indexOf('(1/3)') >= 0,
       'NAV-02: счётчик 1/3 после начала цикла');
    await methods.searchCognitionGraph.call(vm);
    eq(calls.focus[1][0], 'fact:' + CHAT + ':95', 'NAV-02: Enter №3 — второй');
    await methods.searchCognitionGraph.call(vm);
    eq(calls.focus[2][0], 'obs:' + CHAT + ':96', 'NAV-02: Enter №4 — третий');
    await methods.searchCognitionGraph.call(vm);
    eq(calls.focus[3][0], 'ent:' + CHAT + ':94', 'NAV-02: Enter №5 — цикл');
    // Выбор из списка: конкретный результат, без перебора.
    calls.focus.length = 0;
    await methods.pickCogSearchResult.call(vm, 'fact:' + CHAT + ':95');
    eq(calls.focus.length, 1, 'NAV-02: выбор из списка — один фокус');
    eq(calls.focus[0][0], 'fact:' + CHAT + ':95',
       'NAV-02: фокус на выбранном, а не на первом');
    ok(String(vm.graphSearchStatus).indexOf('(2/3)') >= 0,
       'NAV-02: статус называет номер выбранного');
  }

  // ── 12. CMV-NAV-03: результат скрыт фильтром — конфликт, а не сброс ───────
  {
    const vm = makeVm();
    const model = normalize(payload());
    vm.cognitionGraphData = model;
    vm.cogHideDerived = false;
    const calls = { focus: [], select: [] };
    vm.cognitionNetwork = {
      focus(id) { calls.focus.push(id); },
      selectNodes(ids) { calls.select.push(ids.slice()); },
    };
    // Негатив: узел В наборе (fact при фильтре «Факты») — без конфликта.
    vm.graphFilterGroup = 'fact';
    vm._cogView = CM.applyFilters(model, { kinds: ['fact'] });
    vm.graphSearchQuery = 'утренний кофе';
    await methods.searchCognitionGraph.call(vm);
    eq(vm.graphSearchConflict, null, 'NAV-03: узел в наборе — без конфликта');
    eq(vm.graphFilterGroup, 'fact', 'NAV-03: узел в наборе — фильтр не тронут');
    eq(calls.focus.length, 1, 'NAV-03: узел в наборе — обычный фокус');
    // Конфликт: entity вне набора фактов — фильтры НЕ сбрасываются молча.
    const entityId = 'ent:' + CHAT + ':93';
    const modelX = normalize(merged({
      nodes: [nodeRow(entityId, 'entity',
             'Узел с исключительно длинным названием для поиска')],
    }));
    vm.cognitionGraphData = modelX;
    vm._cogView = CM.applyFilters(modelX, { kinds: ['fact'] });
    calls.focus.length = 0;
    vm.graphSearchQuery = 'исключительно';
    await methods.searchCognitionGraph.call(vm);
    eq(calls.focus.length, 0, 'NAV-03: скрытый результат не фокусируется');
    eq(vm.graphFilterGroup, 'fact',
       'NAV-03: молчаливого сброса фильтра больше нет');
    eq(vm.cogHideDerived, false, 'NAV-03: несвязанный переключатель не тронут');
    ok(vm.graphSearchConflict
       && String(vm.graphSearchConflict.id) === entityId
       && vm.graphSearchConflict.blocks.join(',') === 'type',
       'NAV-03: конфликт называет блокирующее ограничение (тип)');
    ok(vm.graphSearchConflict
       && String(vm.graphSearchConflict.blocksLabel).indexOf('по типу') >= 0,
       'NAV-03: ограничение названо словами для пользователя');
    ok(String(vm.graphSearchStatus).indexOf('скрыт фильтром') >= 0,
       'NAV-03: статус сообщает конфликт словами');
    // Действие «Показать результат»: снимает ТОЛЬКО типовой фильтр.
    await methods.showCogSearchResult.call(vm);
    eq(vm.graphFilterGroup, '', 'NAV-03: действие сняло только тип');
    eq(vm.graphSearchConflict, null, 'NAV-03: конфликт закрыт действием');
    eq(calls.focus.length, 1, 'NAV-03: после действия — фокус на результате');
    eq(calls.focus[0], entityId, 'NAV-03: фокус на найденном узле');

    // Кластерный блокер: изолированный узел вне выбранного кластера —
    // действие снимает только кластер, типовой фильтр не трогает.
    const islandId = 'ent:' + CHAT + ':98';
    const modelI = normalize(merged({
      nodes: [nodeRow(islandId, 'entity', 'Островной узел')],
    }));
    const vm2 = makeVm();
    vm2.cognitionGraphData = modelI;
    const calls2 = { focus: [] };
    vm2.cognitionNetwork = { focus(id) { calls2.focus.push(id); },
      selectNodes() {} };
    const hubCluster = CM.computeClusters(modelI).filter(function (c) {
      return c.nodeIds.indexOf('fact:' + CHAT + ':11') >= 0;
    })[0];
    vm2.graphFilterGroup = '';
    vm2.cognitionMapCluster = hubCluster.id;
    vm2._cogView = CM.applyFilters(modelI, { cluster: hubCluster.id });
    vm2.graphSearchQuery = 'Островной';
    await methods.searchCognitionGraph.call(vm2);
    ok(vm2.graphSearchConflict
       && vm2.graphSearchConflict.blocks.join(',') === 'cluster',
       'NAV-03: кластерный фильтр назван блокером');
    eq(vm2.cognitionMapCluster, hubCluster.id,
       'NAV-03: кластер не сбрасывается молча');
    await methods.showCogSearchResult.call(vm2);
    eq(vm2.cognitionMapCluster, '', 'NAV-03: действие сняло только кластер');
    eq(vm2.graphFilterGroup, '', 'NAV-03: типовой фильтр не при чём и цел');
    eq(calls2.focus[0], islandId, 'NAV-03: фокус на островном узле');
  }

  // ── 13. CMV-NAV-04: выбор снимается, когда узел вышел из витрины ──────────
  {
    const vm = makeVm();
    const model = normalize(payload());
    vm.cognitionGraphData = model;
    const selCalls = [];
    vm.cognitionNetwork = {
      selectNodes(ids) { selCalls.push(ids.slice()); },
      // Камера при снятии выбора не двигается (PASS-часть строки).
      focus() { throw new Error('NAV-04: снятие выбора не двигает камеру'); },
    };
    vm.openCogNodeCard('ent:' + CHAT + ':1');       // инспектор показывает «Аню»
    vm._cogSelectedId = 'ent:' + CHAT + ':1';
    vm._cogView = CM.applyFilters(model, { kinds: ['fact'] });  // Аня вышла
    const cleared = methods._cogSyncSelectionToView.call(vm, vm._cogView);
    eq(cleared, true, 'NAV-04: выход выбранного из набора обнаружен');
    eq(vm._cogSelectedId, null, 'NAV-04: выбор снят');
    eq(vm.cogCard, null, 'NAV-04: инспектор «Ани» закрыт');
    eq(selCalls[selCalls.length - 1], [], 'NAV-04: сеть сняла выделение');
    eq(vm._cleared, true, 'NAV-04: панель подробностей очищена');
    // Негатив: узел ОСТАЛСЯ в наборе — выбор сохраняется (CMV-LODB-04).
    const vm2 = makeVm();
    vm2.cognitionGraphData = model;
    vm2.cognitionNetwork = { selectNodes() {} };
    vm2._cogSelectedId = 'fact:' + CHAT + ':11';
    vm2._cogView = CM.applyFilters(model, { kinds: ['fact'] });
    const kept = methods._cogSyncSelectionToView.call(vm2, vm2._cogView);
    eq(kept, false, 'NAV-04: узел в наборе — ничего не снимается');
    eq(vm2._cogSelectedId, 'fact:' + CHAT + ':11', 'NAV-04: выбор сохранён');
    // Хук вызывается рендером на КАЖДОЙ новой витрине (иначе DEFECT жив).
    const src = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
    ok(/this\._cogView = view;\s*\n[\s\S]{0,400}?this\._cogSyncSelectionToView\(view\);/
       .test(src),
       'NAV-04: renderCognitionGraph синхронизирует выбор с новой витриной');
    // Разметка обоих мест показа: список результатов и конфликт (NAV-02/03).
    const html = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
    ok((html.match(/data-cog-search-list/g) || []).length >= 2,
       'NAV-02: список результатов есть в обоих местах показа');
    ok((html.match(/data-cog-search-conflict/g) || []).length >= 2,
       'NAV-03: конфликт с фильтром есть в обоих местах показа');
    ok((html.match(/Показать результат/g) || []).length >= 2,
       'NAV-03: действие «Показать результат» в обоих местах показа');
  }

  console.log('EVOL-CMV-D-OK checks=' + checks);
}()).catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
