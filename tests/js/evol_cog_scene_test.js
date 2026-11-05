'use strict';
/* EPIC-CM-VISUAL-01 (CMV-A) — инварианты жизненного цикла карты в реальном
 * `web/app.js`: один логический граф, один владелец сцены, один RAF.
 *
 * TEST-LIFECYCLE: CONTRACT owner=CMV-A-INTEGRATION
 * Контракт: `plans/features/evol/arch/cm-visual-01-contract.md`
 *   §1   — один владелец сцены; снос в фиксированном порядке;
 *   §6.6 спеки / §10.2 — 20 переключений embedded↔fullscreen не копят
 *          обработчики, RAF, инстансы Network и канвасы;
 *   §7.3 — кадры останавливаются при скрытой вкладке и возвращаются ОДНОЙ
 *          копией; при `prefers-reduced-motion` непрерывных кадров нет;
 *   §8.5 — resize контейнера пересчитывает `fitScaleRef`, камера сохраняется.
 * Спецификация: `plans/owner_inputs/2026-11-03-epic-cm-visual-01.md`
 *   §1.7/§7.3 (анимация не разрушает интерактивность), §10.2 (накопление).
 *
 * Запуск: node tests/js/evol_cog_scene_test.js
 * Вывод:  EVOL-CMV-A-SCENE-OK checks=<n>
 */
const path = require('path');
const assert = require('assert');

/* ── песочница браузера (как в routing_test.js, минимум для карты) ────────── */
let captured = null;
global.Vue = {
  markRaw: (v) => v,
  createApp: function (opts) {
    captured = opts;
    return {
      component() {}, provide() {}, use() {}, mount() {},
    };
  },
};
global.window = {
  location: { hash: '' },
  addEventListener() {},
  Telegram: null,
  matchMedia: () => ({ matches: false, addEventListener() {} }),
};
global.document = {
  hidden: false,
  addEventListener() {},
  removeEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, style: {}, className: '',
      setAttribute() {}, appendChild() {}, remove() {},
    };
  },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  head: { appendChild() {} },
  body: { appendChild() {}, removeChild() {} },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async () => {} } },
});
global.sessionStorage = {
  _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

const ROOT = path.join(__dirname, '..', '..');
// Порядок браузера: адаптер модели → визуальный преобразователь → app.js.
global.window.CognitiveMap = require(
  path.join(ROOT, 'web', 'static', 'cognitive-map.js'));
global.window.CogVisual = require(
  path.join(ROOT, 'web', 'static', 'cog-visual.js'));

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;

let checks = 0;
function ok(cond, message) {
  assert.ok(cond, message);
  checks += 1;
}
function eq(actual, expected, message) {
  assert.deepStrictEqual(actual, expected, message);
  checks += 1;
}

/* ── поддельный vis-network: те же члены, которыми пользуется карта ───────── */
const liveNets = [];
function FakeDataSet(rows) {
  this.rows = rows || [];
  this.clear = function () { this.rows = []; };
  this.add = function (list) { this.rows = this.rows.concat(list || []); };
  this.update = function (list) {
    (list || []).forEach((row) => {
      for (let i = 0; i < this.rows.length; i += 1) {
        if (this.rows[i].id === row.id) {
          this.rows[i] = Object.assign({}, this.rows[i], row);
          return;
        }
      }
    });
  };
}
function FakeNetwork(el, data, options) {
  const self = this;
  this.el = el;
  this.data = data;
  this.options = options;
  this.handlers = {};
  this.onceEvents = [];
  this.moveToCalls = [];
  this.fitCalls = [];
  this.setOptionsCalls = [];
  this.destroyed = false;
  this.on = function (ev, cb) {
    (self.handlers[ev] = self.handlers[ev] || []).push(cb);
  };
  this.once = function (ev, cb) {
    self.onceEvents.push(ev);
    (self.handlers[ev] = self.handlers[ev] || []).push(cb);
  };
  this.emit = function (ev, arg) {
    (self.handlers[ev] || []).forEach((cb) => cb(arg));
  };
  this.setOptions = function (o) { self.setOptionsCalls.push(o); };
  this.moveTo = function (o) { self.moveToCalls.push(o); };
  this.fit = function (a) { self.fitCalls.push(a); };
  this.redraw = function () {};
  this.stopSimulation = function () {};
  this.getPositions = function () {
    return {
      'fact:1:1': { x: -100, y: -50 },
      'belief:1:2': { x: 100, y: 50 },
      'par:1:3': { x: 0, y: 0 },
    };
  };
  this.getScale = function () { return 1.25; };
  this.getViewPosition = function () { return { x: 3, y: -4 }; };
  this.destroy = function () {
    self.destroyed = true;
    self.handlers = {};
  };
  liveNets.push(this);
}
global.window.vis = { DataSet: FakeDataSet, Network: FakeNetwork };

/* ── наблюдатели: считаем observe/disconnect, чтобы видеть утечки ─────────── */
let roMade = 0;
let roAlive = 0;
global.ResizeObserver = function (cb) {
  this.cb = cb;
  roMade += 1;
  roAlive += 1;
  this.observed = 0;
  this.observe = function () { this.observed += 1; };
  this.disconnect = function () {
    if (this.observed) { this.observed = 0; roAlive -= 1; }
  };
};
let ioMade = 0;
let ioAlive = 0;
global.IntersectionObserver = function (cb) {
  this.cb = cb;
  ioMade += 1;
  ioAlive += 1;
  this.observed = 0;
  this.observe = function () { this.observed += 1; };
  this.disconnect = function () {
    if (this.observed) { this.observed = 0; ioAlive -= 1; }
  };
};

/* ── RAF-стенд: планировщик, который исполняем вручную ────────────────────── */
let rafSeq = 0;
let rafScheduled = 0;
const rafQueue = new Map();
global.window.requestAnimationFrame = function (cb) {
  const id = ++rafSeq;
  rafScheduled += 1;
  rafQueue.set(id, cb);
  return id;
};
global.window.cancelAnimationFrame = function (id) { rafQueue.delete(id); };
function flushFrames(t) {
  const cbs = Array.from(rafQueue.values());
  rafQueue.clear();
  cbs.forEach((cb) => cb(t || 16));
  return cbs.length;
}

/* ── модель и контекст (как живой экземпляр Vue для карты) ───────────────── */
const MODEL = global.window.CognitiveMap.normalizePayload({
  version: 'cog-map/1', generated_at: 1762000000, state: 'ok',
  scope: { mode: 'chat', chat_id: 1 },
  truncated: { nodes: false, edges: false, by_class: {} },
  nodes: [
    { id: 'fact:1:1', kind: 'fact', title: 'a', chat_id: 1, degree: 2 },
    { id: 'belief:1:2', kind: 'belief', title: 'b', chat_id: 1, degree: 1 },
    { id: 'par:1:3', kind: 'paradigm', title: 'c', chat_id: 1, degree: 4 },
  ],
  edges: [
    { id: 'e1', from: 'fact:1:1', to: 'belief:1:2', relation: 'supports' },
    { id: 'e2', from: 'fact:1:1', to: 'par:1:3', relation: 'refines' },
  ],
});

function sceneEl(tag) {
  const el = {
    tag: tag || 'embedded',
    clientWidth: 800, clientHeight: 400, isConnected: true,
    listeners: {},
    querySelector() { return null; },
    // CMV-C: контейнер сцены реального DOM умеет слушать клики (раскрытие
    // района). Песочница повторяет эту поверхность, чтобы проверять и её снос.
    addEventListener(name, cb) {
      (this.listeners[name] = this.listeners[name] || []).push(cb);
    },
    removeEventListener(name, cb) {
      const list = this.listeners[name] || [];
      const idx = list.indexOf(cb);
      if (idx >= 0) list.splice(idx, 1);
    },
    listenerCount() {
      let n = 0;
      Object.keys(this.listeners).forEach((k) => { n += this.listeners[k].length; });
      return n;
    },
  };
  return el;
}

function newCtx(extra) {
  const ctx = {
    isGlobalAdmin: true, activeTab: 'status', reducedMotion: false,
    cognitionGraphData: MODEL,
    cognitionNetwork: null, _cognitionGraphSig: null,
    cognitionMapFailed: false, cognitionMapVisMissing: false,
    cogViewNodes: 0, cogViewEdges: 0,
    _cogDeferCount: 0,
    graphFilterGroup: '', cognitionMapCluster: '', cogHideDerived: false,
    $refs: {},
    toast() {},
    graphSelectNode() {}, graphClearDetail() {},
    graphApplySelectionLabels() {}, graphNeighborsOf() { return []; },
    graphPinNeighborhoodLabels: methods.graphPinNeighborhoodLabels,
    graphApplyZoomLevel: methods.graphApplyZoomLevel,
    _graphZoomModeOf: methods._graphZoomModeOf,
    ensureVisNetwork: methods.ensureVisNetwork,
    // реальные методы карты (как на живом vm)
    _graphSignature: methods._graphSignature,
    _cogGraphEl: methods._cogGraphEl,
    renderCognitionGraph: methods.renderCognitionGraph,
    _cogApplyData: methods._cogApplyData,
    _cogCreateNetwork: methods._cogCreateNetwork,
    _cogNodeRow: methods._cogNodeRow,
    _cogEdgeRow: methods._cogEdgeRow,
    _cogFocusColor: methods._cogFocusColor,
    _cogRowOpts: methods._cogRowOpts,
    _cogRedraw: methods._cogRedraw,
    _cogCaptureCamera: methods._cogCaptureCamera,
    _cogCameraOf: methods._cogCameraOf,
    _cogRestoreCamera: methods._cogRestoreCamera,
    _cogApplyFit: methods._cogApplyFit,
    _cogComputeFit: methods._cogComputeFit,
    _cogRefreshFitScale: methods._cogRefreshFitScale,
    _cogAttachSceneObservers: methods._cogAttachSceneObservers,
    _cogOnSceneResize: methods._cogOnSceneResize,
    _cogPauseScene: methods._cogPauseScene,
    _cogResumeScene: methods._cogResumeScene,
    _cogRequestFrame: methods._cogRequestFrame,
    _cogPaintFrame: methods._cogPaintFrame,
    _cogDebugCounters: methods._cogDebugCounters,
    _cogApplyHighlight: methods._cogApplyHighlight,
    // CMV-NAV-04: выбор синхронизируется с новой витриной (часть рендера).
    _cogViewHasId: methods._cogViewHasId,
    _cogSyncSelectionToView: methods._cogSyncSelectionToView,
    clearCogSelection: methods.clearCogSelection,
    _cogFallbackPosition: methods._cogFallbackPosition,
    _cogDrawLabels: methods._cogDrawLabels,
    // CMV-B: слой `fx` и его кадр (в песочнице без DOM он честно выключен).
    _cogEnsureFx: methods._cogEnsureFx,
    _cogSyncFxSize: methods._cogSyncFxSize,
    _cogSyncPositions: methods._cogSyncPositions,
    _cogApplyNodeSizes: methods._cogApplyNodeSizes,
    _cogFitLayoutToFrame: methods._cogFitLayoutToFrame,
    _cogRelaxOverlaps: methods._cogRelaxOverlaps,
    _cogBuildPulse: methods._cogBuildPulse,
    _cogNeighborIds: methods._cogNeighborIds,
    // CMV-C: LOD/агрегаты/подписи в экранных координатах (полный набор, чтобы
    // песочница вела себя как живая сцена, а не «урезанный» поднабор).
    _cogPinnedIds: methods._cogPinnedIds,
    _cogPinnedSet: methods._cogPinnedSet,
    _cogLodKeys: methods._cogLodKeys,
    _cogBuildAggregates: methods._cogBuildAggregates,
    _cogApplyLodVisibility: methods._cogApplyLodVisibility,
    _cogLodVisibilityHash: methods._cogLodVisibilityHash,
    _cogExpandAggregate: methods._cogExpandAggregate,
    _cogOnSceneClick: methods._cogOnSceneClick,
    _cogCounts: methods._cogCounts,
    _cogSetHover: methods._cogSetHover,
    // CMV-PHY-04: dblclick-фокус, pinch и прерывание твина камеры.
    _cogInterruptCameraAnim: methods._cogInterruptCameraAnim,
    _cogDblClickFocus: methods._cogDblClickFocus,
    _cogPinchFrame: methods._cogPinchFrame,
    _cogPinchStep: methods._cogPinchStep,
    _cogFocusTargetScale: methods._cogFocusTargetScale,
    _cogPulseSelected: methods._cogPulseSelected,
    _cogPaintFromVis: methods._cogPaintFromVis,
    _cogPaintStatic: methods._cogPaintStatic,
    _cogPaintFx: methods._cogPaintFx,
    _cogFrameState: methods._cogFrameState,
    _cogResolveLod: methods._cogResolveLod,
    _cogPaintLabels: methods._cogPaintLabels,
    destroyCognitionGraph: methods.destroyCognitionGraph,
  };
  Object.assign(ctx, extra || {});
  // Контейнер сцены: в «живом» DOM его находит `_cogGraphEl` через $refs.
  ctx.$refs.cognitionGraph = ctx._el || sceneEl();
  return ctx;
}

/* ── 1. Один граф: 20 переключений embedded↔fullscreen без накопления ─────── */
(async function cycles() {
  const ctx = newCtx();
  const elA = sceneEl('embedded');
  const elB = sceneEl('fullscreen');
  await methods.renderCognitionGraph.call(ctx);
  ok(ctx.cognitionNetwork, 'циклы: сеть создана');
  const firstNet = ctx.cognitionNetwork;
  const baseline = ctx._cogDebugCounters();
  eq(baseline.netCount, 1, 'циклы: ровно один живой vis.Network');
  eq(baseline.observerCount, 2, 'циклы: два наблюдателя (размер + видимость)');
  eq(roAlive, 1, 'циклы: один ResizeObserver');
  eq(ioAlive, 1, 'циклы: один IntersectionObserver');
  const listeners = baseline.listeners;
  // 10 обычных обработчиков (кадр/выбор/снятие/hover/hover-out/клик/зум/
  // перетаск/dblclick-фокус/прерывание твина на dragStart)
  // + 2 `once` стабилизации + 1 `animationFinished` = 13 (CMV-B добавил hover
  // и `afterDrawing` как единый сигнал кадра §6 контракта).
  // CMV-C добавил ОДИН слушатель контейнера сцены («Раскрыть» по району,
  // bubble-фаза, §6 контракта).
  // CMV-PHY-04 добавил 6 слушателей контейнера: wheel (снятие твина) и
  // 4 touch-фазы pinch + click района — итого 19; все снимаются в destroy.
  eq(listeners, 19,
    'циклы: 10 обработчиков + 2 once + animationFinished + 6 слушателей сцены');
  eq(baseline.rafActive, false, 'циклы: кадров до стабилизации нет');
  eq(baseline.fxCanvas, false, 'циклы: в песочнице без DOM слоя `fx` нет');

  let steady = null;
  for (let i = 0; i < 20; i += 1) {
    // Смена режима = другой контейнер DOM (как embedded ↔ полный экран).
    ctx.$refs.cognitionGraph = (i % 2 === 0) ? elB : elA;
    await methods.renderCognitionGraph.call(ctx);
    ok(ctx._cogScene && ctx._cogScene.net === ctx.cognitionNetwork,
      'цикл ' + i + ': сцена принадлежит текущей сети');
    const counters = ctx._cogDebugCounters();
    // Переключение режима сохраняет раскладку (§1.4 контракта): стабилизации
    // нет, значит once-слушателей тоже нет — набор обработчиков стабилен.
    if (steady === null) steady = counters.listeners;
    eq(counters.netCount, 1, 'цикл ' + i + ': один инстанс');
    eq(counters.listeners, steady, 'цикл ' + i + ': обработчики не выросли');
    ok(counters.listeners <= listeners,
      'цикл ' + i + ': обработчиков не больше, чем на первом кадре');
    eq(counters.observerCount, 2, 'цикл ' + i + ': наблюдатели не выросли');
    eq(counters.canvases, 0,
      'цикл ' + i + ': чужих канвасов в песочнице нет');
    eq(counters.fxCanvas, false, 'цикл ' + i + ': слоя `fx` без DOM нет');
    eq(counters.rafActive, false, 'цикл ' + i + ': лишних RAF нет');
    eq(roAlive, 1, 'цикл ' + i + ': один ResizeObserver на карту');
    eq(ioAlive, 1, 'цикл ' + i + ': один IntersectionObserver на карту');
  }
  eq(ctx._cogDebugCounters().netTotal, 21,
    'циклы: 21 создание сети (переключения реально пересоздают инстанс)');
  ok(ctx.cognitionNetwork !== firstNet, 'циклы: инстанс действительно новый');
  // Прошлые инстансы уничтожены (нет «шлейфа зависших канвасов»).
  liveNets.forEach((net) => {
    if (net !== ctx.cognitionNetwork) {
      ok(net.destroyed, 'циклы: прежний инстанс уничтожен');
    }
  });
  // Снос в конце: ни одного живого инстанса/наблюдателя.
  methods.destroyCognitionGraph.call(ctx);
  eq(ctx._cogDebugCounters().netCount, 0, 'циклы: после destroy инстансов 0');
  eq(ctx._cogScene, null, 'циклы: сцена снята');
  eq(roAlive, 0, 'циклы: ResizeObserver отключён');
  eq(ioAlive, 0, 'циклы: IntersectionObserver отключён');
  eq(ctx._cogFitScale, 0, 'циклы: геометрия кадра сброшена вместе со сценой');
  // Повторный destroy безопасен (unmount + смена вкладки могут идти подряд).
  methods.destroyCognitionGraph.call(ctx);
  eq(ctx._cogDebugCounters().netCount, 0, 'циклы: повторный destroy безопасен');

  /* ── 2. Один RAF-владелец: single-flight, потолок 24 fps, пауза ─────────── */
  const ctx2 = newCtx();
  await methods.renderCognitionGraph.call(ctx2);
  // До стабилизации кадр не запрошен: покой — это ноль кадров.
  eq(ctx2._cogDebugCounters().rafActive, false, 'RAF: до стабилизации кадров нет');
  eq(ctx2._cogRequestFrame(), true, 'RAF: первый кадр запланирован');
  eq(ctx2._cogRequestFrame(), false, 'RAF: второй кадр не дублируется');
  eq(ctx2._cogDebugCounters().rafActive, true, 'RAF: кадр активен');
  let painted = 0;
  ctx2._cogScene.onFrame = function () { painted += 1; };
  eq(flushFrames(16), 1, 'RAF: исполнен ровно один кадр');
  eq(painted, 1, 'RAF: хук кадра вызван один раз');
  // CMV-B: кадры продолжаются (пульс), но не чаще 24 fps: тик 32 ms после
  // 16 ms пропускается по частотному потолку, следующий рисует.
  eq(ctx2._cogDebugCounters().rafActive, true,
    'RAF: цикл продолжается сам себя (мягкая жизнь §7.1)');
  eq(rafQueue.size, 1, 'RAF: в очереди ровно один кадр');
  flushFrames(32);
  eq(painted, 1, 'RAF: 32 ms < порога 24 fps — кадр не рисуется');
  flushFrames(48);
  eq(painted, 1, 'RAF: 48 ms — ещё в пределах потолка 24 fps');
  flushFrames(64);
  eq(painted, 2, 'RAF: следующий тик после порога — кадр нарисован');
  // Скрытый vis-кадр в этом же тике: `fx` уже нарисован из `afterDrawing`,
  // второй проход не делается (§6 контракта — один кадр).
  ctx2._cogScene.visPaintedAt = 100;
  flushFrames(104);
  eq(painted, 2, 'RAF: кадр vis не дублируется своим RAF (один кадр)');
  ctx2._cogScene.visPaintedAt = 0;
  flushFrames(140);
  eq(painted, 3, 'RAF: после vis-кадра свой цикл продолжает рисовать');

  ctx2._cogPauseScene();
  eq(ctx2._cogDebugCounters().rafActive, false, 'RAF: пауза снимает кадр');
  eq(rafQueue.size, 0, 'RAF: отменённый кадр не висит в очереди');
  eq(ctx2._cogRequestFrame(), false, 'RAF: на паузе новый кадр не идёт');
  ctx2._cogResumeScene();
  eq(ctx2._cogDebugCounters().rafActive, true, 'RAF: возврат даёт ОДИН кадр');
  eq(rafQueue.size, 1, 'RAF: в очереди ровно один кадр');
  ctx2._cogResumeScene();
  eq(rafQueue.size, 1, 'RAF: повторный resume не плодит копий');

  // Скрытая вкладка: кадры не идут и не запускаются на возврате «второй раз».
  global.document.hidden = true;
  ctx2._cogPauseScene();
  ctx2._cogResumeScene();
  eq(ctx2._cogDebugCounters().rafActive, false,
    'RAF: в скрытой вкладке кадры не идут');
  eq(ctx2._cogRequestFrame(), false, 'RAF: hidden → кадр не планируется');
  global.document.hidden = false;
  ctx2._cogResumeScene();
  eq(rafQueue.size, 1, 'RAF: после возврата ровно один кадр');
  // На возврате цикл снова живёт ровно одной копией (утечки нет).
  flushFrames(1024);
  eq(rafQueue.size, 1, 'RAF: после возврата одна копия цикла');

  // reduced-motion: непрерывных кадров нет вовсе (читаемость остаётся).
  const ctxRm = newCtx({ reducedMotion: true });
  await methods.renderCognitionGraph.call(ctxRm);
  eq(ctxRm._cogRequestFrame(), false, 'RAF: reduced-motion не запускает кадры');
  eq(ctxRm._cogDebugCounters().rafActive, false, 'RAF: reduced-motion — покой');
  ok(ctxRm.cognitionNetwork, 'reduced-motion: сцена и выбор доступны');
  // Статический кадр всё равно рисуется: формы/свечение/выделение (§7.3).
  eq(ctxRm._cogPaintStatic(), undefined,
    'reduced-motion: статический кадр вызывается без кадрового цикла');

  /* ── 3. Данные: смена набора не переписывает модель и не двигает камеру ──── */
  const frozenView = {
    nodes: JSON.parse(JSON.stringify(MODEL.nodes)),
    edges: JSON.parse(JSON.stringify(MODEL.edges)),
  };
  Object.freeze(frozenView.nodes);
  frozenView.nodes.forEach((n) => Object.freeze(n));
  frozenView.edges.forEach((e) => Object.freeze(e));
  const before = JSON.stringify(frozenView);
  const ctx3 = newCtx();
  await methods.renderCognitionGraph.call(ctx3);
  const net3 = ctx3.cognitionNetwork;
  const moveToBefore = net3.moveToCalls.length;
  ctx3._cogApplyData(frozenView, {});
  eq(JSON.stringify(frozenView), before,
    'данные: применение набора не изменило модель');
  eq(net3.moveToCalls.length, moveToBefore,
    'данные: обновление набора не двигает камеру (нет «прыжка в центр»)');
  const dsRows = ctx3._cognitionNodesDS.rows;
  eq(dsRows.length, frozenView.nodes.length,
    'данные: по строке на узел (набор не потерян)');
  dsRows.forEach((row) => {
    ok(row.title === undefined && row.kind === undefined,
      'данные: строка DataSet — только визуальные поля');
  });
  ok(ctx3._cogFitScale > 0, 'данные: fitScaleRef известен после обновления');

  /* ── 4. Resize: пересчёт fitScaleRef, камера та же ──────────────────────── */
  const ctx4 = newCtx();
  await methods.renderCognitionGraph.call(ctx4);
  const net4 = ctx4.cognitionNetwork;
  // Первый кадр = конец стабилизации: камера обзора уже поставлена.
  net4.emit('stabilizationIterationsDone');
  const fitBefore = ctx4._cogFitScale;
  ok(fitBefore > 0, 'resize: fitScaleRef посчитан на первом кадре');
  eq(net4.moveToCalls.length, 1, 'resize: первый кадр — один moveTo');
  // Камеру пользователя снимает кадр/жест (в браузере — afterDrawing).
  net4.emit('zoom', { scale: 1.6 });
  const camBefore = JSON.stringify(ctx4._cogCamera);
  ok(camBefore && camBefore !== 'null', 'resize: камера снята с инстанса');
  ctx4._el = ctx4.$refs.cognitionGraph;
  ctx4.$refs.cognitionGraph.clientWidth = 1400;
  ctx4.$refs.cognitionGraph.clientHeight = 900;
  const moveToBefore4 = net4.moveToCalls.length;
  ctx4._cogOnSceneResize();
  ok(ctx4._cogFitScale > fitBefore,
    'resize: fitScaleRef пересчитан от нового размера сцены');
  eq(JSON.stringify(ctx4._cogCamera), camBefore,
    'resize: камера пользователя не потеряна');
  ok(net4.moveToCalls.length > moveToBefore4,
    'resize: камера восстановлена тем же moveTo');
  const restored = net4.moveToCalls[net4.moveToCalls.length - 1];
  eq(restored.scale, JSON.parse(camBefore).scale,
    'resize: масштаб камеры сохранён (не fit-масштаб)');

  /* ── 5. Камера обзора не зажимается программным минимумом ───────────────── */
  // Обзор 702 узлов даёт scale < 0.15; адаптерный `cameraToNetwork` зажимал её
  // к `DEFAULTS.minScale`, и r = 1 превращался в r ≈ 1.4 на смене режима
  // (спека §6.6 «камера пересчитывается без смещения»).
  const smallCam = ctx4._cogCameraOf({ x: 5, y: 7 }, 0.09);
  eq(smallCam.scale, 0.09, 'камера: масштаб обзора не зажимается к 0.15');
  ctx4._cogCamera = smallCam;
  ctx4._cogRestoreCamera(false);
  const lastMove = net4.moveToCalls[net4.moveToCalls.length - 1];
  eq(lastMove.scale, 0.09, 'камера: восстановление сохраняет масштаб обзора');
  eq(lastMove.position, { x: 5, y: 7 }, 'камера: позиция восстановлена');
  eq(ctx4._cogCameraOf({ x: 'нет', y: null }, NaN).scale, 1,
    'камера: битые значения не дают NaN');

  /* ── 6. reduced-motion: раскладка считается, движения нет ──────────────── */
  // Раньше при `prefers-reduced-motion` физика отключалась ДО раскладки: узлы
  // стояли кольцом, все 2400 рёбер шли через центр — «белый ковёр» (§12.1).
  const ctxRm2 = newCtx({ reducedMotion: true });
  await methods.renderCognitionGraph.call(ctxRm2);
  const rmNet = ctxRm2.cognitionNetwork;
  ok(rmNet.options.physics && rmNet.options.physics.stabilization,
    'reduced-motion: раскладка считается (physics не false)');
  eq(rmNet.options.physics.stabilization.fit, false,
    'reduced-motion: кадр обзора выставляем сами, не vis.fit');
  rmNet.emit('stabilizationIterationsDone');
  eq(rmNet.setOptionsCalls, [{ physics: { enabled: false } }],
    'reduced-motion: физика гасится сразу после расстановки');
  eq(rmNet.moveToCalls.length, 1, 'reduced-motion: один кадр обзора');
  eq(rmNet.moveToCalls[0].animation, false,
    'reduced-motion: без анимации камеры');
  eq(ctxRm2._cogRequestFrame(), false,
    'reduced-motion: кадровый цикл не запускается');
  eq(ctxRm2._cogDebugCounters().settled, true,
    'reduced-motion: сцена стабилизирована и готова к выбору');

  /* ── 7. Слой `fx`: один canvas на сцену, спрайты кэшируются, снос полный ─── */
  // Песочница с минимальным DOM: проверяем РЕАЛЬНУЮ проводку слоя (создание
  // канваса, размер по DPR, кэш спрайтов, пауза, снос), а не только математику.
  const fxGradient = { made: 0, canvases: 0 };
  /* Заглушка 2d-контекста ЗАПИСЫВАЕТ операции, а не только считает вызовы.
   * Без записи мутации «чёрная плашка вернулась» (fillRect под подписью) или
   * «выбранный узел потерял подпись» не падают: тест видел бы только факт
   * вызова. `ops` — единый журнал кадра: тип + аргументы + стиль на момент
   * вызова; `measureText` отдаёт правдоподобную ширину кириллицы, чтобы слой
   * подписей считал боксы как в браузере. */
  function makeCtx(log, canvas) {
    const rec = {
      __ops: log,
      canvas: canvas || null,
      globalAlpha: 1, lineWidth: 1, fillStyle: '', strokeStyle: '', font: '',
      textAlign: '', textBaseline: '', lineJoin: '', lineCap: '',
      createRadialGradient() {
        fxGradient.made += 1;
        return { addColorStop() {} };
      },
      measureText(text) {
        const size = parseFloat(String(rec.font).replace(/[^0-9.]/g, '')) || 12;
        return { width: String(text).length * size * 0.62 };
      },
      clearRect(x, y, w, h) {
        log.push({ op: 'clearRect', x, y, w, h });
      },
      fillRect(x, y, w, h) {
        log.push({ op: 'fillRect', x, y, w, h, style: rec.fillStyle,
                   alpha: rec.globalAlpha });
      },
      beginPath() { log.push({ op: 'beginPath' }); },
      moveTo(x, y) { log.push({ op: 'moveTo', x, y }); },
      lineTo(x, y) { log.push({ op: 'lineTo', x, y }); },
      quadraticCurveTo(x1, y1, x2, y2) {
        log.push({ op: 'quadraticCurveTo', x1, y1, x2, y2 });
      },
      closePath() { log.push({ op: 'closePath' }); },
      arc(x, y, r) { log.push({ op: 'arc', x, y, r }); },
      stroke() {
        log.push({ op: 'stroke', style: rec.strokeStyle,
                   width: rec.lineWidth, alpha: rec.globalAlpha });
      },
      fill() {
        log.push({ op: 'fill', style: rec.fillStyle, alpha: rec.globalAlpha });
      },
      save() { log.push({ op: 'save' }); },
      restore() { log.push({ op: 'restore' }); },
      setTransform(a, b, c, d, e, f) {
        log.push({ op: 'setTransform', a, b, c, d, e, f });
      },
      fillText(text, x, y) {
        log.push({ op: 'fillText', text, x, y, style: rec.fillStyle,
                   font: rec.font, alpha: rec.globalAlpha });
      },
      strokeText(text, x, y) {
        log.push({ op: 'strokeText', text, x, y, style: rec.strokeStyle,
                   width: rec.lineWidth, font: rec.font,
                   alpha: rec.globalAlpha });
      },
      drawImage(img, x, y, w, h) {
        log.push({ op: 'drawImage', x, y, w, h, alpha: rec.globalAlpha });
      },
    };
    return rec;
  }
  function stubCtx2d() {
    return makeCtx([], null);
  }
  function domSceneEl() {
    const children = [];
    const el = {
      clientWidth: 900, clientHeight: 480, isConnected: true,
      style: {}, children,
      appendChild(node) { children.push(node); node.parentNode = el; return node; },
      removeChild(node) {
        const at = children.indexOf(node);
        if (at >= 0) children.splice(at, 1);
        node.parentNode = null;
        return node;
      },
      querySelector() { return null; },
    };
    return el;
  }
  const prevCreate = global.document.createElement;
  function elCount(el) { return el.children.length; }
  global.document.createElement = function (tag) {
    if (tag !== 'canvas') return prevCreate(tag);
    fxGradient.canvases += 1;
    const log = [];
    const canvas = {
      tagName: 'CANVAS', width: 300, height: 150, className: '',
      style: {}, parentNode: null,
      // Журнал операций ЭТОГО канваса: по нему видно, ЧТО нарисовано, а не
      // только сколько раз вызвали метод (иначе мутации подписей/плашек живы).
      __ops: log,
      setAttribute() {},
      getContext() {
        if (!this.__ctx) this.__ctx = makeCtx(log, canvas);
        return this.__ctx;
      },
    };
    return canvas;
  };
  global.window.devicePixelRatio = 2;

  const ctxFx = newCtx();
  const fxEl = domSceneEl();
  ctxFx.$refs.cognitionGraph = fxEl;
  await methods.renderCognitionGraph.call(ctxFx);
  eq(ctxFx._cogDebugCounters().fxCanvas, true, 'fx: слой создан вместе со сценой');
  eq(fxEl.children.length, 1, 'fx: на сцену ровно один canvas');
  eq(fxEl.children[0].className, 'cog-fx', 'fx: класс слоя (CSS pointer-events)');
  eq(fxEl.children[0].width, 900 * 2, 'fx: ширина canvas = W · dpr (≤ 2)');
  eq(fxEl.children[0].height, 480 * 2, 'fx: высота canvas = H · dpr');
  eq(ctxFx._cogScene.fxDpr, 2, 'fx: DPR = min(devicePixelRatio, 2)');
  // Стабилизация: кэш позиций + первый кадр декора.
  ctxFx.cognitionNetwork.emit('stabilizationIterationsDone');
  const afterSettle = ctxFx._cogDebugCounters();
  ok(afterSettle.fxPaints >= 1, 'fx: первый кадр нарисован по завершении layout');
  ok(afterSettle.fxSprites > 0, 'fx: спрайты свечения построены');
  eq(afterSettle.positions, 3, 'fx: позиции всех узлов в кэше (§5.1)');
  // CMV-C: районы уровня 0 достраиваются на ПЕРВОМ кадре с готовыми позициями
  // (догоняющая сборка), поэтому спрайты центров появляются один раз — после
  // этого кэш обязан быть стабильным. Проверяем именно стабильность кэша,
  // а не «счастливое совпадение» первого кадра.
  ctxFx._cogPaintStatic();
  ctxFx._cogPaintStatic();
  const stableSprites = ctxFx._cogDebugCounters().fxSprites;
  const stableGrads = ctxFx._cogDebugCounters().fxGradients;
  for (let i = 0; i < 5; i += 1) ctxFx._cogPaintStatic();
  const afterFrames = ctxFx._cogDebugCounters();
  eq(afterFrames.fxSprites, stableSprites,
    'fx: кэш спрайтов не растёт с кадрами (§10.2(5))');
  eq(afterFrames.fxGradients, stableGrads,
    'fx: в кадре градиенты не создаются');
  eq(afterFrames.fxGradients, afterFrames.fxSprites,
    'fx: один градиент на спрайт, а не на узел');
  ok(afterFrames.fxDraws > stableSprites,
    'fx: спрайты реально компонуются (drawImage)');

  // Подписи: коллизии/приоритет из адаптера, но БЕЗ чёрной плашки (§4.4).
  methods.graphApplySelectionLabels.call(ctxFx, ['par:1:3']);
  ctxFx._cogPaintStatic();
  ok(ctxFx._cogLabels && ctxFx._cogLabels.shown >= 1,
    'подписи: слой отдал хотя бы одну подпись');
  ok(ctxFx._cogLabels.labels.some((l) => l.id === 'par:1:3'),
    'подписи: выбранный узел подписан всегда (приоритет 0)');
  const fxCanvas = fxEl.children[0];
  const fxOps = fxCanvas.__ops || [];
  const texts = fxOps.filter((o) => o.op === 'strokeText');
  const fills = fxOps.filter((o) => o.op === 'fillText');
  ok(texts.length > 0, 'подписи: текст РЕАЛЬНО нарисован контуром (strokeText)');
  eq(texts.length, fills.length,
    'подписи: у каждого текста есть и контур, и заливка (без плашки)');
  // §4.4 спеки: «никаких чёрных прямоугольников под каждой подписью».
  // Проверяем не отсутствие метода, а ОПЕРАЦИИ: под подписью не должно быть
  // закрашенного прямоугольника (мутация «вернуть плашку» это ломает).
  const labelBoxes = texts.map((t) => ({
    text: t.text,
    x: t.x,
    y: t.y,
    width: Math.max(12, String(t.text).length * 12 * 0.55) + 6,
    height: 17,
  }));
  const plates = fxOps.filter((o) => o.op === 'fillRect'
    && o.w > 8 && o.h > 6 && o.h < 60
    && labelBoxes.some((b) => Math.abs((o.x + o.w / 2) - b.x) < b.width / 2
      && Math.abs((o.y + o.h / 2) - b.y) < b.height / 2 + 4));
  eq(plates.map((o) => o.style), [],
    'подписи: ни одной закрашенной плашки под текстом (§4.4)');
  // Ширина контура: замечание ревью — при кегле 11–12 px lineWidth 3 читался
  // как тяжёлая тёмная полоса (стало 2.2; у принудительной подписи +0.6).
  ok(texts.every((t) => t.width <= 3.0) && texts.some((t) => t.width <= 2.6),
    'подписи: контур не толще 2.6 px при кегле 11–12 (замечание ревью)');

  /* ── forced-подпись: выбранный подписан ДАЖЕ если аллокатор его отсёк ───── */
  // Мутация B11 («выбранный теряет подпись») выживала, потому что аллокатор в
  // песочнице и так отдавал выбранный узел. Здесь аллокатор его ЯВНО отсекает
  // (как на краю кадра/при коллизии с престижной парадигмой) — слой обязан
  // дорисовать подпись сам (§4.4 спеки, §5.5 контракта).
  const realAllocate = global.window.CognitiveMap.allocateLabels;
  let allocCalls = 0;
  let lastAllocOpts = null;
  global.window.CognitiveMap.allocateLabels = function (items, opts) {
    allocCalls += 1;
    lastAllocOpts = opts;
    const plan = realAllocate(items, opts);
    // Отсекаем ВЫБРАННЫЙ из плана аллокатора: подпись должна прийти из
    // принудительного слоя, а не из плана.
    plan.labels = plan.labels.filter((l) => String(l.id) !== 'par:1:3');
    return plan;
  };
  try {
    ctxFx._cogScene.labelKey = null;      // пересчитать план заново
    ctxFx._cogScene.labelPlan = null;
    fxCanvas.__ops.length = 0;
    ctxFx._cogPaintStatic();
    ok(allocCalls > 0, 'forced: аллокатор вызван (план посчитан)');
    const planHasSelected = (ctxFx._cogLabels.labels || []).some(
      (l) => String(l.id) === 'par:1:3');
    eq(planHasSelected, false,
      'forced: аллокатор действительно отсёк выбранный узел (предусловие)');
    const forcedOne = (ctxFx._cogLabels.forced || []).find(
      (l) => String(l.id) === 'par:1:3');
    ok(forcedOne, 'forced: подпись выбранного в списке принудительных');
    ok((fxCanvas.__ops || []).some(
      (o) => o.op === 'fillText' && o.text === forcedOne.text),
      'forced: текст принудительной подписи реально нарисован (fillText)');
    // §5.1 спеки: LOD подписей считается от ОТНОСИТЕЛЬНОГО r = scale/fitScale,
    // а не от абсолютного vis-масштаба (мутация B15 «scale: cam.scale»).
    ok(lastAllocOpts && typeof lastAllocOpts.scale === 'number',
      'LOD: аллокатор получил масштаб подписей');
    const relScale = global.window.CogVisual.relativeScale(
      1.25, ctxFx._cogFitScale);
    ok(Math.abs(lastAllocOpts.scale - relScale) < 1e-9,
      'LOD: в аллокатор уходит ОТНОСИТЕЛЬНЫЙ масштаб r = scale/fitScale');
    ok(Math.abs(lastAllocOpts.scale - 1.25) > 1e-6,
      'LOD: абсолютный vis-масштаб в аллокатор не уходит');
  } finally {
    global.window.CognitiveMap.allocateLabels = realAllocate;
  }
  const pulseIds = (ctxFx._cogScene.pulse || []).map((e) => e.id);
  ok(pulseIds.indexOf('par:1:3') >= 0,
    'пульс: выбранный узел входит в набор «живых»');
  ok(pulseIds.length <= 24, 'пульс: не более 24 узлов на 3-узловом наборе');

  // Hover: отдельное состояние + курсор + кадр запрошен (§7.2 спеки).
  ctxFx._cogSetHover('fact:1:1');
  eq(ctxFx._cogScene.hoverId, 'fact:1:1', 'hover: состояние записано');
  eq(fxEl.style.cursor, 'pointer', 'hover: курсор меняется на pointer');
  eq(ctxFx._cogDebugCounters().rafActive, true, 'hover: запрошен кадр реакции');
  // CMV-AI-01: рампа проходит через ЖИВОЙ кадр сцены — `hoverAt` из
  // `_cogSetHover` доходит до слоя `fx`, активное свечение в начале ярко
  // НЕ вспыхивает, а после рампы яркость ровно прежняя. Активное свечение
  // опознаём по альфе 0.50: дальний ≤0.10, ближний 0.22, центры районов
  // ≤0.348 — только активный узел даёт 0.50.
  {
    const savedSel = ctxFx._cogSelectedId;
    ctxFx._cogSelectedId = null;            // активным будет hover, не выбор
    const tHover = ctxFx._cogScene.hoverAt;
    ok(tHover > 0, 'hover: момент наведения записан (hoverAt)');
    const fxOps = fxEl.children[0].__ops;
    function glowAlphas(extraMs) {
      const at = fxOps.length;
      ctxFx._cogPaintFx(tHover + extraMs);
      return fxOps.slice(at).filter((o) => o.op === 'drawImage')
        .map((o) => o.alpha);
    }
    const midAlphas = glowAlphas(30);       // 30 ms < hoverMs
    const endAlphas = glowAlphas(400);      // рампа давно завершена
    ok(midAlphas.length > 0, 'hover-рампа: кадр с hover реально нарисован');
    const midMax = midAlphas.reduce((m, a) => Math.max(m, a), 0);
    ok(midMax < 0.45,
      'hover-рампа: в начале яркость заметно меньше финальной (' + midMax + ')');
    ok(endAlphas.some((a) => Math.abs(a - 0.5) < 1e-6),
      'hover-рампа: после рампы яркость ровно прежняя (0.50 на кадре)');
    ctxFx._cogSelectedId = savedSel;
  }
  ctxFx._cogSetHover(null);
  eq(fxEl.style.cursor, '', 'hover: уход сбрасывает курсор');
  ctxFx._cogPaintStatic();

  // Клик: один световой импульс (в reduced-motion не заводится).
  ctxFx._cogPulseSelected('click', 'fact:1:1');
  ok(ctxFx._cogScene.pulseHit && ctxFx._cogScene.pulseHit.duration > 0,
    'клик: импульс заведён на выбранный узел');
  const rmCtx = newCtx({ reducedMotion: true });
  const rmEl = domSceneEl();
  rmCtx.$refs.cognitionGraph = rmEl;
  await methods.renderCognitionGraph.call(rmCtx);
  rmCtx.cognitionNetwork.emit('stabilizationIterationsDone');
  eq(rmCtx._cogDebugCounters().rafActive, false,
    'reduced-motion: кадрового цикла нет');
  ok(rmCtx._cogDebugCounters().fxPaints >= 1,
    'reduced-motion: статический кадр со свечением и подписями есть');
  rmCtx._cogPulseSelected('click', 'fact:1:1');
  rmCtx._cogPaintStatic();
  eq(rmCtx._cogDebugCounters().rafActive, false,
    'reduced-motion: клик не запускает кадровый цикл');

  /* ── 8. Раскладка на коротком кадре: нормализация, плотность, разведение ── */
  // §6.2/§12.1 спеки: на встроенной карте (широкий короткий кадр) изотропная
  // раскладка vis занимала 23 % ширины, а 702 узла стояли стеной. Проверяем
  // три механизма на реальном контексте, а не только чистые функции.
  const ctxFit = newCtx();
  const fitEl = sceneEl('embedded');
  fitEl.clientWidth = 1200;
  fitEl.clientHeight = 320;
  ctxFit.$refs.cognitionGraph = fitEl;
  await methods.renderCognitionGraph.call(ctxFit);
  ctxFit.cognitionNetwork.emit('stabilizationIterationsDone');
  const fitScene = ctxFit._cogScene;
  ok(fitScene.frameFit && fitScene.frameFit.kx > 1.2,
    'раскладка: свободная ось кадра растянута (kx > 1.2)');
  eq(fitScene.frameFit.ky, 1, 'раскладка: ограничивающая ось не тронута');
  eq(ctxFit._cogFitLayoutToFrame(), fitScene.frameFit,
    'раскладка: нормализация выполняется ровно один раз');
  ok(ctxFit._cogFitScale > 0,
    'раскладка: fitScaleRef пересчитан после нормализации');
  // §5.1 спеки: экранный диаметр ограничен локальной плотностью — предел
  // обязан быть посчитан для всех узлов витрины и лежать в полосе спеки.
  const caps = fitScene.caps || {};
  eq(Object.keys(caps).length, 3,
    'плотность: предел посчитан для всех узлов витрины');
  ok(Object.keys(caps).every((id) => caps[id] >= 5.5 && caps[id] <= 24),
    'плотность: пределы в полосе [min, max] экранного диаметра');
  // §6.2 спеки/§8.1 контракта: разведение совпавших ядер.
  const fakeFit = ctxFit.cognitionNetwork;
  const savedPos = fakeFit.getPositions;
  fakeFit.getPositions = function () {
    return {
      'fact:1:1': { x: 10, y: 10 },
      'belief:1:2': { x: 10, y: 10 },     // точное совпадение центров
      'par:1:3': { x: 400, y: 120 },
    };
  };
  ctxFit._cogSyncPositions();
  const movedCount = ctxFit._cogRelaxOverlaps();
  fakeFit.getPositions = savedPos;
  ok(movedCount > 0, 'разведение: совпавшие узлы сдвинуты');
  const movedRows = (ctxFit._cognitionNodesDS.rows || [])
    .filter((r) => typeof r.x === 'number' && typeof r.y === 'number');
  ok(movedRows.length >= 2,
    'разведение: новые координаты ушли в DataSet (батч, не на кадр)');
  const rowA = movedRows.find((r) => r.id === 'fact:1:1');
  const rowB = movedRows.find((r) => r.id === 'belief:1:2');
  ok(rowA && rowB && (rowA.x !== rowB.x || rowA.y !== rowB.y),
    'разведение: центры совпавших узлов больше не совпадают');
  methods.destroyCognitionGraph.call(ctxFit);

  // Снос: canvas снят, спрайты освобождены, повторный destroy безопасен.
  methods.destroyCognitionGraph.call(ctxFx);
  eq(fxEl.children.length, 0, 'fx: canvas удалён вместе со сценой');
  eq(ctxFx._cogDebugCounters().fxCanvas, false, 'fx: сцена снесена');
  methods.destroyCognitionGraph.call(ctxFx);
  eq(elCount(rmEl), 1, 'fx: у второй сцены свой единственный canvas');
  methods.destroyCognitionGraph.call(rmCtx);
  eq(elCount(rmEl), 0, 'fx: reduced-motion сцена снесена так же');

  global.document.createElement = prevCreate;
  delete global.window.devicePixelRatio;

  /* ── CMV-AI-01: рампа hover-свечения 150–220 ms (§7.2 спеки) ───────────────
   * Прямо через слой `fx` (реальный код кадра): множитель нарастает плавно
   * от 0 до 1 за CONFIG.motion.hoverMs, и после рампы яркость ТОЧНО прежняя.
   * Мутация «мгновенное свечение одним кадром» красит aThird/aHalf. */
  {
    const Vr = global.window.CogVisual;
    const opsR = [];
    const ctxR = {
      globalAlpha: 1, lineWidth: 1, fillStyle: '', strokeStyle: '',
      font: '', lineJoin: '', lineCap: '', textAlign: '', textBaseline: '',
      createRadialGradient() { return { addColorStop() {} }; },
      clearRect() {}, fillRect() {}, save() {}, restore() {},
      setTransform() {}, measureText: () => ({ width: 90 }),
      beginPath() {}, moveTo() {}, lineTo() {}, closePath() {},
      arc() {}, stroke() {}, fill() {}, fillText() {}, strokeText() {},
      drawImage(img, x, y, w, h) {
        opsR.push({ op: 'drawImage', x, y, w, h, alpha: ctxR.globalAlpha });
      },
    };
    const fxR = Vr.createFx({
      dpr: 1,
      makeCanvas: (w, h) => ({ width: w, height: h, getContext: () => ctxR }),
    });
    const RNODES = [{ id: 'n1', kind: 'fact', degree: 2 }];
    const RPOS = { n1: { x: 0, y: 0 } };
    function rFrame(extra) {
      return Object.assign({
        now: 0, width: 400, height: 300,
        camera: { x: 0, y: 0, scale: 1 },
        positions: RPOS, nodes: RNODES, edges: [], incident: [],
        selection: null, hover: 'n1', hoverAt: 1000,
        fitScale: 1, lod: 2, keyIds: null, pulse: null, flash: 0,
        reducedMotion: false,
      }, extra || {});
    }
    const hoverMs = Vr.CONFIG.motion.hoverMs;
    ok(hoverMs >= 150 && hoverMs <= 220,
      'AI-01: hoverMs подключён и в полосе 150–220 ms (' + hoverMs + ')');
    // Базовый кадр без hover: ровно 2 drawImage (дальний + ближний ореолы).
    opsR.length = 0;
    fxR.paint(ctxR, rFrame({ now: 999, hover: null }));
    eq(opsR.filter((o) => o.op === 'drawImage').length, 2,
      'AI-01: база — дальний и ближний ореолы без активного');
    function activeAlphaAt(t, extra) {
      opsR.length = 0;
      fxR.paint(ctxR, rFrame(Object.assign({ now: t }, extra || {})));
      const di = opsR.filter((o) => o.op === 'drawImage');
      // Активное свечение — ПОСЛЕДНИЙ drawImage кадра (порядок §2.1); когда
      // рампа ещё = 0, активного спрайта нет вовсе → на кадре их 2, не 3.
      return di.length > 2 ? di[di.length - 1].alpha : 0;
    }
    const T = 1000;
    const aStart = activeAlphaAt(T);
    const aThird = activeAlphaAt(T + hoverMs / 3);
    const aHalf = activeAlphaAt(T + hoverMs / 2);
    const aFull = activeAlphaAt(T + hoverMs);
    const aStable = activeAlphaAt(T + hoverMs * 3);
    const aPast = activeAlphaAt(9999, { hoverAt: T - 100000 });
    const aLegacy = activeAlphaAt(T + 10, { hoverAt: undefined });
    const aReduced = activeAlphaAt(T + 10, { reducedMotion: true });
    const aStatic = activeAlphaAt(0);
    eq(aStart, 0, 'AI-01: в момент наведения усиления ещё нет');
    ok(aThird > 0.03 && aThird < 0.45 * aFull,
      'AI-01: на 1/3 рампы яркость заметно меньше финала (' + aThird + ')');
    ok(aHalf > aThird && aHalf < 0.9 * aFull,
      'AI-01: рампа монотонна и на половине ещё не завершена (' + aHalf + ')');
    ok(Math.abs(aFull - 0.5) < 1e-9,
      'AI-01: в конце рампы яркость ровно прежняя (' + aFull + ')');
    eq(aStable, aFull, 'AI-01: после рампы состояние стабильно');
    eq(aPast, aFull, 'AI-01: hoverAt в прошлом — тот же финал');
    eq(aLegacy, aFull,
      'AI-01: кадр без hoverAt (старые вызовы) — финал, не ноль');
    eq(aReduced, aFull, 'AI-01: reduced-motion — конечное состояние (§7.3)');
    eq(aStatic, aFull, 'AI-01: вневременный статичный кадр — финал');
  }

  /* ── CMV-PHY-04a: double-click → плавный твин камеры на узел ──────────────
   * Обработчика doubleClick не было (камера стояла 0 кадров). Твин обязан
   * идти 350–500 ms с easing и заканчиваться ЦЕНТРОМ НА УЗЛЕ.
   * Мутация «обработчик удалён» красит проверку события. */
  {
    const ctxD = newCtx();
    const elD = sceneEl('embedded');
    ctxD.$refs.cognitionGraph = elD;
    await methods.renderCognitionGraph.call(ctxD);
    ctxD.cognitionNetwork.emit('stabilizationIterationsDone');
    const netD = ctxD.cognitionNetwork;
    // ГЛАВНАЯ проверка — через реальное vis-событие doubleClick.
    const beforeEmit = netD.moveToCalls.length;
    netD.emit('doubleClick', { nodes: ['par:1:3'] });
    eq(netD.moveToCalls.length, beforeEmit + 1,
      'dblclick: vis-событие doubleClick двигает камеру ровно один раз');
    const mv = netD.moveToCalls[netD.moveToCalls.length - 1];
    ok(mv.animation && mv.animation.duration >= 350
        && mv.animation.duration <= 500,
      'dblclick: длительность твина в полосе 350–500 ms');
    eq(mv.animation.easingFunction, 'easeInOutQuad',
      'dblclick: easing есть (§6(4) спеки)');
    eq(mv.position, { x: 0, y: 0 },
      'dblclick: твин заканчивается центром на узле (позиция par:1:3)');
    ok(mv.scale > 0, 'dblclick: масштаб фокуса положительный');
    // Тап по пустоте камеру не трогает.
    eq(methods._cogDblClickFocus.call(ctxD, { nodes: [] }), null,
      'dblclick: тап по пустоте фокус не двигает');
    eq(netD.moveToCalls.length, beforeEmit + 1, 'dblclick: лишних moveTo нет');
    // reduced-motion: прыжок без анимации (§7.3).
    const ctxRmD = newCtx({ reducedMotion: true });
    ctxRmD.$refs.cognitionGraph = sceneEl('embedded');
    await methods.renderCognitionGraph.call(ctxRmD);
    ctxRmD.cognitionNetwork.emit('stabilizationIterationsDone');
    const rmBefore = ctxRmD.cognitionNetwork.moveToCalls.length;
    const rmInfo = methods._cogDblClickFocus.call(ctxRmD,
      { nodes: ['par:1:3'] });
    ok(rmInfo && rmInfo.duration === 0,
      'dblclick: reduced-motion без анимации');
    eq(ctxRmD.cognitionNetwork.moveToCalls[rmBefore].animation, false,
      'dblclick: reduced-motion — animation:false');
    methods.destroyCognitionGraph.call(ctxD);
    methods.destroyCognitionGraph.call(ctxRmD);
  }

  /* ── CMV-PHY-04b: pinch зумится вокруг точки жеста (±20 px) ───────────────
   * Проба batch3: vis якорил зум в центр полотна (дрейф 428–443 px). Наш
   * перехват держит мировую точку под ЦЕНТРОМ ЖЕСТА. Мутация «якорь в
   * центре полотна» даёт дрейф ~440 px и красит тест. */
  {
    const ctxP = newCtx();
    const elP = sceneEl('embedded');
    elP.clientWidth = 800;
    elP.clientHeight = 400;
    elP.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 400 });
    ctxP.$refs.cognitionGraph = elP;
    await methods.renderCognitionGraph.call(ctxP);
    ctxP.cognitionNetwork.emit('stabilizationIterationsDone');
    const netP = ctxP.cognitionNetwork;
    const sceneP = ctxP._cogScene;
    sceneP.width = 800;
    sceneP.height = 400;
    function touch(type, pts) {
      const ev = { touches: pts };
      ev.preventDefault = () => { ev.prevented = true; };
      ev.stopPropagation = () => { ev.stopped = true; };
      (elP.listeners[type] || []).forEach((cb) => cb(ev));
      return ev;
    }
    const W = 800;
    const H = 400;
    // Жест: центр (600, 120) — НЕ центр полотна (400, 200); щипок ×2.2.
    const g0 = { x: 600, y: 120 };
    const cam0 = netP.getViewPosition();
    const s0 = netP.getScale();
    const w0x = cam0.x + (g0.x - W / 2) / s0;
    const w0y = cam0.y + (g0.y - H / 2) / s0;
    touch('touchstart', [
      { clientX: g0.x - 50, clientY: g0.y },
      { clientX: g0.x + 50, clientY: g0.y },
    ]);
    ok(sceneP.pinch && sceneP.pinch.spread0 === 100,
      'pinch: сессия начата со вторым пальцем');
    const moveEv = touch('touchmove', [
      { clientX: g0.x - 110, clientY: g0.y },
      { clientX: g0.x + 110, clientY: g0.y },
    ]);
    ok(moveEv.stopped && moveEv.prevented,
      'pinch: жест не доходит до vis (stopPropagation), страница не зумится');
    const mvP = netP.moveToCalls[netP.moveToCalls.length - 1];
    ok(mvP && mvP.animation === false,
      'pinch: шаг применяется мгновенно (без твина)');
    const s1 = mvP.scale;
    ok(Math.abs(s1 - s0 * 2.2) < 1e-9,
      'pinch: масштаб по размаху пальцев (×2.2)');
    // ЯКОРЬ: мировая точка w0 осталась под центром жеста (±20 px экранных).
    const w1x = mvP.position.x + (g0.x - W / 2) / s1;
    const w1y = mvP.position.y + (g0.y - H / 2) / s1;
    const driftPx = Math.hypot(w1x - w0x, w1y - w0y) * s1;
    ok(driftPx <= 20,
      'pinch: точка под пальцами не уплывает (' + driftPx.toFixed(1) + ' px)');
    ok(Math.abs(mvP.position.x - (w0x - (g0.x - W / 2) / s1)) < 1e-9
        && Math.abs(mvP.position.y - (w0y - (g0.y - H / 2) / s1)) < 1e-9,
      'pinch: камера = якорь минус смещение центра жеста (точная формула)');
    // Одиночный палец (жест завершён) камеру не двигает.
    const cntP = netP.moveToCalls.length;
    sceneP.pinch = null;
    (elP.listeners['touchmove'] || []).forEach((cb) => cb({
      touches: [{ clientX: 10, clientY: 10 }],
      preventDefault() {}, stopPropagation() {},
    }));
    eq(netP.moveToCalls.length, cntP,
      'pinch: одиночный палец камеру не двигает');
    // Сессия закрывается, когда отпущены все пальцы; «хвостовой» палец
    // между делом не создаёт новую сессию и не дёргает камеру.
    touch('touchstart', [
      { clientX: g0.x - 50, clientY: g0.y },
      { clientX: g0.x + 50, clientY: g0.y },
    ]);
    touch('touchend', [{ clientX: g0.x - 110, clientY: g0.y }]);
    ok(sceneP.pinch, 'pinch: сессия живёт до отпускания всех пальцев');
    const cntP2 = netP.moveToCalls.length;
    touch('touchmove', [{ clientX: g0.x - 130, clientY: g0.y }]);
    eq(netP.moveToCalls.length, cntP2,
      'pinch: после снятия одного пальца камера не двигается');
    touch('touchend', []);
    eq(sceneP.pinch, null, 'pinch: сессия закрыта по отпускании всех пальцев');
    // Клампы масштаба как у vis (1e-5…10): чудовищный щипок не ломает камеру.
    touch('touchstart', [
      { clientX: g0.x - 10, clientY: g0.y },
      { clientX: g0.x + 10, clientY: g0.y },
    ]);
    touch('touchmove', [
      { clientX: 0, clientY: g0.y },
      { clientX: 9000, clientY: g0.y },
    ]);
    const mvQ = netP.moveToCalls[netP.moveToCalls.length - 1];
    ok(mvQ.scale > 0 && mvQ.scale <= 10,
      'pinch: масштаб ограничен потолком 10');
    methods.destroyCognitionGraph.call(ctxP);
    eq((elP.listeners['touchmove'] || []).length, 0,
      'pinch: touch-слушатели сняты вместе со сценой');
  }

  /* ── CMV-PHY-04c: wheel/drag немедленно прерывают анимацию камеры ─────────
   * Проба batch3: wheel во время фокуса глотался ~660 ms. vis ведёт твин
   * функцией `viewFunction` на `initRedraw` — снимаем её тем же способом,
   * что и сам vis; финальная камера = цель колеса, а не цель твина.
   * Мутация «wheel-слушатель не подключён» красит проверку off-вызова. */
  {
    const ctxI = newCtx();
    const elI = sceneEl('embedded');
    ctxI.$refs.cognitionGraph = elI;
    await methods.renderCognitionGraph.call(ctxI);
    ctxI.cognitionNetwork.emit('stabilizationIterationsDone');
    const netI = ctxI.cognitionNetwork;
    const tween = function fakeTween() {};
    const offCalls = [];
    function fakeView(t) {
      return {
        viewFunction: t, easingTime: 0.4,
        body: { emitter: { off(ev, fn) { offCalls.push([ev, fn]); } } },
      };
    }
    // Прямое прерывание: твин снят тем же способом, что и сам vis.
    netI.view = fakeView(tween);
    ok(methods._cogInterruptCameraAnim.call(ctxI) === true,
      'interrupt: запущенный твин обнаружен');
    eq(offCalls, [['initRedraw', tween]],
      'interrupt: твин снят ровно тем же способом, что и в самом vis');
    eq(netI.view.viewFunction, undefined, 'interrupt: viewFunction снята');
    eq(netI.view.easingTime, 0, 'interrupt: easingTime сброшен');
    // Wheel: capture-слушатель сцены снимает твин ДО vis-шага колеса —
    // финальная камера будет целью колеса, а не целью твина.
    netI.view = fakeView(tween);
    const wheelListeners = elI.listeners['wheel'] || [];
    eq(wheelListeners.length, 1,
      'interrupt: wheel-слушатель на сцене ровно один');
    wheelListeners.forEach((cb) => cb({ deltaY: -120 }));
    eq(offCalls.length, 2, 'interrupt: колесо сняло твин немедленно');
    eq(netI.view.viewFunction, undefined,
      'interrupt: после колеса кадр твина не перезапишет жест');
    // dragStart — тот же немедленный контроль (§6(3) спеки).
    netI.view = fakeView(tween);
    netI.emit('dragStart', {});
    eq(offCalls.length, 3, 'interrupt: drag тоже снимает твин');
    // Когда твина нет — прерывание честно false и не падает.
    netI.view = null;
    eq(methods._cogInterruptCameraAnim.call(ctxI), false,
      'interrupt: без vis-view — false, без исключений');
    const ctxI2 = newCtx();
    ctxI2.cognitionNetwork = { getScale: () => 1 };
    eq(methods._cogInterruptCameraAnim.call(ctxI2), false,
      'interrupt: сеть без view — false');
    methods.destroyCognitionGraph.call(ctxI);
    eq((elI.listeners['wheel'] || []).length, 0,
      'снос: wheel-слушатель снят вместе со сценой');
    eq((elI.listeners['touchstart'] || []).length, 0,
      'снос: touch-слушатели сняты вместе со сценой');
  }

  console.log('EVOL-CMV-A-SCENE-OK checks=' + checks);
  console.log('EVOL-CMV-B-SCENE-OK checks=' + checks);

  /* ── CMV-C: LOD-гистерезис в сцене, видимость L0, раскрытие, счётчики ─── */
  const C = global.window.CognitiveMap;
  const V = global.window.CogVisual;

  // LOD через метод сцены: делегирует чистой функции адаптера и не мигает.
  {
    const ctx = newCtx();
    ctx.cognitionNetwork = { getScale: () => 1 };
    ctx._cogScene = { lod: null, width: 800, height: 400, keyLod: null };
    ctx._cogView = { nodes: [] };
    ctx._cogFitScale = 1;
    const lods = [];
    // Монотонный проход масштаба: 0.5 → 2.6 и обратно.
    for (let r = 0.5; r <= 2.6; r += 0.01) {
      lods.push(methods._cogResolveLod.call(ctx, r));
    }
    let backwards = 0;
    for (let i = 1; i < lods.length; i += 1) {
      if (lods[i] < lods[i - 1]) backwards += 1;
    }
    eq(backwards, 0, 'LOD: на увеличении сцена не откатывает уровень');
    eq(lods[lods.length - 1], 2, 'LOD: при r≈2.6 сцена в детальном уровне');
    for (let r = 2.6; r >= 0.5; r -= 0.01) {
      lods.push(methods._cogResolveLod.call(ctx, r));
    }
    let forwards = 0;
    for (let i = lods.length - Math.round(2.1 / 0.01) + 1; i < lods.length; i += 1) {
      if (lods[i] > lods[i - 1]) forwards += 1;
    }
    eq(forwards, 0, 'LOD: на уменьшении сцена не прыгает уровнем вверх');
    eq(lods[lods.length - 1], 0, 'LOD: обратно к r≈0.5 уровень обзорный');
    // Плотный кадр при r=1: уровень 0 (агрегаты), а не «стена ядер».
    const denseCtx = newCtx();
    denseCtx.cognitionNetwork = { getScale: () => 1 };
    denseCtx._cogScene = {
      lod: 1, width: 1252, height: 318, keyLod: null, pos: {},
    };
    denseCtx._cogView = { nodes: new Array(702).fill(0).map((x, i) => ({ id: 'n' + i })) };
    denseCtx._cogFitScale = 1;
    denseCtx._cogInFrameCount = () => 702;
    eq(methods._cogResolveLod.call(denseCtx, 1), 0,
      '§5.2: плотный набор при r=1 — уровень 0 (районы)');
    const sparseCtx = newCtx();
    sparseCtx.cognitionNetwork = { getScale: () => 1 };
    sparseCtx._cogScene = { lod: 1, width: 1252, height: 318, keyLod: null, pos: {} };
    sparseCtx._cogView = { nodes: new Array(10).fill(0).map((x, i) => ({ id: 'n' + i })) };
    sparseCtx._cogFitScale = 1;
    eq(methods._cogResolveLod.call(sparseCtx, 1), 1,
      '§5.2: мелкий набор при r=1 — рабочий вид, без районов');
  }

  // Видимость уровня 0: участники свёрнутых районов скрыты, якоря и
  // закреплённые узлы — видны; возврат на L1 показывает всех.
  {
    const view = { nodes: [], edges: [] };
    for (let i = 0; i < 40; i += 1) {
      view.nodes.push({ id: 'n' + i, kind: 'fact', degree: i, title: 't' + i });
    }
    const ds = new FakeDataSet(view.nodes.map((n) => ({ id: n.id, hidden: false })));
    const pos = {};
    view.nodes.forEach((n, i) => { pos[n.id] = { x: i * 10, y: i * 6 }; });
    const scene = {
      lod: 0, viewRev: 3, selectionRev: 0, pos: pos, aggregates: [],
      pulse: [], pulseMap: {}, width: 800, height: 400,
      aggregates: [
        { id: 'agg:A', apexId: 'n0', count: 20, hideMembers: true,
          memberIds: new Array(20).fill(0).map((x, i) => 'n' + i) },
        { id: 'agg:B', apexId: 'n20', count: 20, hideMembers: true,
          memberIds: new Array(20).fill(0).map((x, i) => 'n' + (20 + i)) },
      ],
    };
    const visCtx = newCtx({
      _cognitionNodesDS: ds,
      _cogScene: scene,
      _cogView: view,
      _cogFitScale: 1,
      _cogSelectedId: 'n25',
      _cogHighlight: { n25: true, n26: true },
      _graphSearchMatchIds: ['n7'],
    });
    visCtx._cogLodKeys = () => ({});
    const shown = methods._cogApplyLodVisibility.call(visCtx, 0);
    const hiddenRows = ds.rows.filter((r) => r.hidden === true).map((r) => r.id);
    ok(shown <= 5, 'L0: поштучно видны якоря районов и закреплённые (' + shown + ')');
    ok(hiddenRows.length >= 30, 'L0: участники районов свёрнуты');
    ok(!hiddenRows.includes('n0') && !hiddenRows.includes('n20'),
      'L0: якоря районов остаются видимыми');
    ok(!hiddenRows.includes('n25'),
      '§5.5: выбранный узел не скрывается даже в свёрнутом районе');
    ok(!hiddenRows.includes('n7'),
      '§5.5: найденный поиском узел не скрывается LOD-ом');
    // Повторный вызов с тем же ключом не гоняет батч по всем узлам.
    const visKey = scene.lodVisKey;
    methods._cogApplyLodVisibility.call(visCtx, 0);
    eq(scene.lodVisKey, visKey, 'L0: видимость пересчитывается только по ключу');
    // Возврат на L1: все узлы снова видны, данные не потеряны.
    const restored = methods._cogApplyLodVisibility.call(visCtx, 1);
    eq(restored, view.nodes.length, 'L1: видимость возвращается всем узлам');
    eq(ds.rows.filter((r) => r.hidden === true).length, 0,
      'L1: скрытых узлов не остаётся');
    ok(ds.rows.length === view.nodes.length,
      'LOD не удаляет строки DataSet (данные не теряются)');
    // Без агрегатов скрывать нельзя: иначе сцена стала бы пустой (и
    // getPositions в vis не вернул бы позиции скрытых узлов).
    const guardScene = {
      lod: 0, viewRev: 1, selectionRev: 0,
      // Позиции ЕСТЬ, районов НЕТ: именно этот случай раньше скрывал всё.
      pos: (function () {
        const out = {};
        view.nodes.forEach((n, i) => { out[n.id] = { x: i * 4, y: i * 3 }; });
        return out;
      })(),
      aggregates: [],
      width: 800, height: 400,
    };
    const guardDs = new FakeDataSet(view.nodes.map((n) => ({ id: n.id })));
    const guardCtx = newCtx({
      _cognitionNodesDS: guardDs, _cogScene: guardScene, _cogView: view,
      _cogFitScale: 1, _cogSelectedId: null, _cogHighlight: null,
    });
    guardCtx._cogLodKeys = () => ({});
    eq(methods._cogApplyLodVisibility.call(guardCtx, 0), view.nodes.length,
      'L0 без посчитанных районов не скрывает узлы (защита от пустой сцены)');
  }

  // Кэш позиций не теряет скрытые узлы (vis 9.1.9 не отдаёт их в getPositions).
  {
    const view = { nodes: [{ id: 'a' }, { id: 'b' }, { id: 'c' }], edges: [] };
    const scene = { pos: {}, posRev: 0, viewRev: 1 };
    const net = {
      getPositions: () => ({ a: { x: 1, y: 2 } }),   // b,c скрыты LOD-ом
    };
    const posCtx = newCtx({
      cognitionNetwork: net, _cogScene: scene, _cogView: view,
    });
    scene.pos = {
      a: { x: 1, y: 2 }, b: { x: 3, y: 4 }, c: { x: 5, y: 6 },
    };
    const count = methods._cogSyncPositions.call(posCtx);
    eq(count, 1, 'позиции: синхронизация берёт то, что отдаёт vis');
    eq(Object.keys(scene.pos).sort(), ['a', 'b', 'c'],
      'позиции: геометрия скрытых узлов СОХРАНЯЕТСЯ (иначе районы терялись бы)');
    view.nodes.push({ id: 'd' });
    scene.viewRev = 2;
    scene.pos.d = { x: 9, y: 9 };
    scene.pos.stale = { x: 0, y: 0 };          // нет ни в наборе, ни в позициях vis
    methods._cogSyncPositions.call(posCtx);
    eq(Object.keys(scene.pos).sort(), ['a', 'b', 'c', 'd'],
      'позиции: узел вне набора вычищается, а скрытые в наборе — остаются');
  }

  // Раскрытие района: камера к его участникам, выбор — реальный якорь.
  {
    const positions = {};
    const nodes = [];
    for (let i = 0; i < 12; i += 1) {
      nodes.push({ id: 'g' + i, kind: 'fact', degree: i, title: 'g' + i });
      // Район занимает почти весь кадр: его собственный fit ≈ 0.86, и без
      // нижней границы масштаба камера осталась бы в обзоре (r ≈ 1).
      positions['g' + i] = { x: -400 + i * 72, y: -190 + i * 34 };
    }
    const net = {
      moveToCalls: [], selectCalls: [],
      moveTo(o) { this.moveToCalls.push(o); },
      selectNodes(ids) { this.selectCalls.push(ids); },
      getScale: () => 1, getPositions: () => positions,
      on() {}, once() {}, destroy() {}, redraw() {},
    };
    const scene = {
      lod: 0, width: 800, height: 400, pos: positions, cam: { x: 0, y: 0, scale: 1 },
      aggregates: [{
        id: 'agg:g0:0:0', apexId: 'g3', count: 12, radius: 20,
        sx: 200, sy: 100, hideMembers: true,
        memberIds: nodes.map((n) => n.id),
      }],
    };
    const expandCtx = newCtx({
      cognitionNetwork: net, _cogScene: scene, _cogView: { nodes, edges: [] },
      _cogFitScale: 0.5,
    });
    const res = methods._cogExpandAggregate.call(expandCtx, 'agg:g0:0:0');
    ok(res && res.apexId === 'g3', 'раскрытие: возвращает реальный якорь района');
    eq(res.memberIds.length, 12, 'раскрытие: отдаёт всех реальных участников');
    ok(net.moveToCalls.length === 1, 'раскрытие: один программный moveTo');
    ok(net.moveToCalls[0].scale >= 0.5 * 2.2 - 1e-9,
      'раскрытие: масштаб уводит с уровня 0 (r ≥ 2.2)');
    ok(net.moveToCalls[0].scale <= 0.5 * 3.4 + 1e-9,
      'раскрытие: и не проваливается глубже допустимого (r ≤ 3.4)');
    ok(net.selectCalls.length === 1 && net.selectCalls[0][0] === 'g3',
      'раскрытие: выбирается реальный узел-якорь');
    eq(scene.aggregates, null, 'раскрытие: районы снимаются до пересчёта LOD');
    eq(methods._cogExpandAggregate.call(expandCtx, 'нет-такого'), null,
      'раскрытие: неизвестный район не двигает камеру');
  }

  // Клик по контейнеру: hit-test в экранных координатах, узел важнее района.
  {
    const scene = {
      lod: 0, hoverId: null, width: 800, height: 400,
      el: {
        getBoundingClientRect: () => ({ left: 10, top: 20 }),
      },
      aggregates: [
        { id: 'agg:1', apexId: 'x1', count: 30, radius: 20, sx: 100, sy: 60 },
        { id: 'agg:2', apexId: 'x2', count: 30, radius: 20, sx: 400, sy: 200 },
      ],
    };
    const clickCtx = newCtx({ _cogScene: scene, cognitionNetwork: {} });
    const expanded = [];
    clickCtx._cogExpandAggregate = (id) => { expanded.push(id); return { id }; };
    const hit = methods._cogOnSceneClick.call(clickCtx,
      { clientX: 110, clientY: 80, preventDefault() {} });
    ok(hit && hit.id === 'agg:1', 'клик: попадание в центр района раскрывает его');
    methods._cogOnSceneClick.call(clickCtx, { clientX: 300, clientY: 300 });
    eq(expanded.length, 1, 'клик: промах мимо центра ничего не раскрывает');
    // Реальный узел под курсором имеет приоритет над районом.
    scene.hoverId = 'real';
    methods._cogOnSceneClick.call(clickCtx, { clientX: 110, clientY: 80 });
    eq(expanded.length, 1, 'клик по реальному узлу не раскрывает район');
    scene.hoverId = null;
    scene.lod = 1;
    methods._cogOnSceneClick.call(clickCtx, { clientX: 110, clientY: 80 });
    eq(expanded.length, 1, 'вне уровня 0 клик по району ничего не делает');
  }

  // Подписи уровня 0: районы подписаны, выбранный/найденный — всегда, и
  // наложений в экранных координатах нет.
  {
    const nodes = [];
    const pos = {};
    for (let i = 0; i < 24; i += 1) {
      const id = 'k' + i;
      nodes.push({ id: id, kind: ['fact', 'belief', 'paradigm'][i % 3],
        degree: i % 5, title: 'Запись ' + i });
      pos[id] = { x: (i % 6) * 40, y: Math.floor(i / 6) * 40 };
    }
    const scene = {
      lod: 0, width: 800, height: 400, pos: pos,
      cam: { x: 0, y: 0, scale: 1 }, viewRev: 4, selectionRev: 1,
      aggregates: [
        { id: 'agg:k0:0:0', apexId: 'k0', count: 12, radius: 26,
          sx: 160, sy: 120, dominantKind: 'fact', hideMembers: true,
          label: 'Факты · 12', kinds: { fact: 10, belief: 2 },
          memberIds: nodes.slice(0, 12).map((n) => n.id) },
        { id: 'agg:k12:0:1', apexId: 'k12', count: 12, radius: 26,
          sx: 620, sy: 260, dominantKind: 'belief', hideMembers: true,
          label: 'Убеждения · 12', kinds: { belief: 12 },
          memberIds: nodes.slice(12).map((n) => n.id) },
      ],
      forcedLabels: [],
    };
    const ops = [];
    const fakeCtx = {
      font: '', textAlign: '', textBaseline: '', lineWidth: 1,
      fillStyle: '', strokeStyle: '', lineJoin: '', globalAlpha: 1,
      measureText: () => ({ width: 90 }),
      strokeText(t) { ops.push('stroke:' + t); },
      fillText(t) { ops.push('text:' + t); },
      save() {}, restore() {},
    };
    const labelCtx = newCtx({
      _cogScene: scene, _cogView: { nodes: nodes, edges: [] },
      _cogSelectedId: 'k20', _cogHighlight: { k20: true },
      _graphSearchMatchIds: ['k7'],
      _cognitionGraphMode: 'full',
    });
    const shownLabels = methods._cogPaintLabels.call(labelCtx, fakeCtx, 800, 400);
    const plan = labelCtx._cogLabels;
    const ids = plan.labels.map((l) => String(l.id)).concat(
      (plan.forced || []).map((l) => String(l.id)));
    ok4label: {
      var group = ids.filter((id) => id.indexOf('agg:') === 0);
      ok(group.length >= 1, 'L0: подписи районов нарисованы (' + group.length + ')');
      ok(ids.indexOf('k20') >= 0, '§4.4: выбранный узел подписан на уровне 0');
      ok(ids.indexOf('k7') >= 0, '§4.4: найденный поиском узел подписан на уровне 0');
      ok(shownLabels >= 3, 'L0: на кадре есть подписи');
      var overlaps = 0;
      var all = plan.labels.concat(plan.forced || []);
      for (var i2 = 0; i2 < all.length; i2 += 1) {
        for (var j2 = i2 + 1; j2 < all.length; j2 += 1) {
          if (String(all[i2].id) === String(all[j2].id)) continue;
          if (Math.abs(all[i2].x - all[j2].x) * 2 < (all[i2].width + all[j2].width)
              && Math.abs(all[i2].y - all[j2].y) * 2
                < (all[i2].height + all[j2].height)) overlaps += 1;
        }
      }
      eq(overlaps, 0, '§4.4: подписи уровня 0 не накладываются в экранных координатах');
      ok(ops.some((o) => o.indexOf('text:') === 0),
        '§4.4: текст реально нарисован (без плашек — только контур+заливка)');
      ok(ops.filter((o) => o.indexOf('stroke:') === 0).length >= 1,
        'подписи: тёмный контур нарисован strokeText, а не прямоугольником');
    }
  }

  // Счётчики §9.9: разные величины, не смешаны.
  {
    const countCtx = newCtx({
      cognitionGraphData: Object.assign({}, MODEL, {
        shownOf: { byKind: { fact: { shown: 3, total: 300 } }, totalEdges: 900 },
      }),
      _cogView: { nodes: MODEL.nodes.slice(0, 2), edges: MODEL.edges },
      _cogScene: {
        lod: 0, aggregates: [{ id: 'agg:z', apexId: 'fact:1:1', count: 3 }],
      },
    });
    const counts = methods._cogCounts.call(countCtx);
    eq(counts.api.nodes, MODEL.nodes.length, 'счётчики: «из API» = принятый набор');
    eq(counts.filter.nodes, 2, 'счётчики: «после фильтра» = витрина');
    eq(counts.screen.aggregated, 3, 'счётчики: «на экране» знает свёрнутое');
    eq(counts.db.nodes, 300, 'счётчики: «в БД» берётся из shown_of, если он есть');
    ok(counts.db.nodes !== counts.api.nodes,
      'счётчики: «в БД» не подменяется «из API»');
    const noAgg = methods._cogCounts.call(newCtx({
      cognitionGraphData: MODEL, _cogView: { nodes: MODEL.nodes, edges: [] },
      _cogScene: { lod: 1, aggregates: [{ id: 'agg:z', count: 3 }] },
    }));
    eq(noAgg.screen.aggregates, 0,
      'счётчики: вне уровня 0 агрегатов на экране нет');
    eq(noAgg.db.known, false, 'счётчики: без shown_of «в БД» неизвестно');
  }

  console.log('EVOL-CMV-C-SCENE-OK checks=' + checks);
})();
