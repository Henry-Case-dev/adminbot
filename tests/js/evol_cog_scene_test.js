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
    querySelector() { return null; },
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
    _cogFallbackPosition: methods._cogFallbackPosition,
    _cogDrawLabels: methods._cogDrawLabels,
    // CMV-B: слой `fx` и его кадр (в песочнице без DOM он честно выключен).
    _cogEnsureFx: methods._cogEnsureFx,
    _cogSyncFxSize: methods._cogSyncFxSize,
    _cogSyncPositions: methods._cogSyncPositions,
    _cogApplyNodeSizes: methods._cogApplyNodeSizes,
    _cogBuildPulse: methods._cogBuildPulse,
    _cogNeighborIds: methods._cogNeighborIds,
    _cogSetHover: methods._cogSetHover,
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
  // 8 обычных обработчиков (кадр/выбор/снятие/hover/hover-out/клик/зум/перетаск)
  // + 2 `once` стабилизации + 1 `animationFinished` = 11 (CMV-B добавил hover
  // и `afterDrawing` как единый сигнал кадра §6 контракта).
  eq(listeners, 11, 'циклы: 8 обработчиков + 2 once + animationFinished');
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
  function stubCtx2d() {
    return {
      globalAlpha: 1, lineWidth: 1, fillStyle: '', strokeStyle: '', font: '',
      textAlign: '', textBaseline: '', lineJoin: '',
      createRadialGradient() {
        fxGradient.made += 1;
        return { addColorStop() {} };
      },
      clearRect() {}, fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {},
      quadraticCurveTo() {}, closePath() {}, arc() {}, stroke() {}, fill() {},
      save() {}, restore() {}, setTransform() {}, fillText() {},
      strokeText() {}, drawImage() {},
    };
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
    const canvas = {
      tagName: 'CANVAS', width: 300, height: 150, className: '',
      style: {}, parentNode: null,
      setAttribute() {},
      getContext() { return stubCtx2d(); },
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
  const spritesAfterFirst = afterSettle.fxSprites;
  const gradsAfterFirst = afterSettle.fxGradients;
  for (let i = 0; i < 5; i += 1) ctxFx._cogPaintStatic();
  const afterFrames = ctxFx._cogDebugCounters();
  eq(afterFrames.fxSprites, spritesAfterFirst,
    'fx: кэш спрайтов не растёт с кадрами (§10.2(5))');
  eq(afterFrames.fxGradients, gradsAfterFirst,
    'fx: в кадре градиенты не создаются');
  ok(afterFrames.fxDraws > spritesAfterFirst,
    'fx: спрайты реально компонуются (drawImage)');

  // Подписи: коллизии/приоритет из адаптера, но БЕЗ чёрной плашки (§4.4).
  methods.graphApplySelectionLabels.call(ctxFx, ['par:1:3']);
  ctxFx._cogPaintStatic();
  ok(ctxFx._cogLabels && ctxFx._cogLabels.shown >= 1,
    'подписи: слой отдал хотя бы одну подпись');
  ok(ctxFx._cogLabels.labels.some((l) => l.id === 'par:1:3'),
    'подписи: выбранный узел подписан всегда (приоритет 0)');
  const pulseIds = (ctxFx._cogScene.pulse || []).map((e) => e.id);
  ok(pulseIds.indexOf('par:1:3') >= 0,
    'пульс: выбранный узел входит в набор «живых»');
  ok(pulseIds.length <= 24, 'пульс: не более 24 узлов на 3-узловом наборе');

  // Hover: отдельное состояние + курсор + кадр запрошен (§7.2 спеки).
  ctxFx._cogSetHover('fact:1:1');
  eq(ctxFx._cogScene.hoverId, 'fact:1:1', 'hover: состояние записано');
  eq(fxEl.style.cursor, 'pointer', 'hover: курсор меняется на pointer');
  eq(ctxFx._cogDebugCounters().rafActive, true, 'hover: запрошен кадр реакции');
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

  console.log('EVOL-CMV-A-SCENE-OK checks=' + checks);
  console.log('EVOL-CMV-B-SCENE-OK checks=' + checks);
})();
