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
  eq(listeners, 8, 'циклы: 6 обработчиков + 2 once-слушателя стабилизации');
  eq(baseline.rafActive, false, 'циклы: кадров в покое нет');

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
    eq(counters.canvases, 0, 'цикл ' + i + ': наших канвасов нет (fx = CMV-B)');
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

  /* ── 2. Один RAF-владелец: single-flight, пауза, возврат ─────────────────── */
  const ctx2 = newCtx();
  await methods.renderCognitionGraph.call(ctx2);
  // После создания сети кадр не запрошен: покой — это ноль кадров.
  eq(ctx2._cogDebugCounters().rafActive, false, 'RAF: в покое кадров нет');
  eq(ctx2._cogRequestFrame(), true, 'RAF: первый кадр запланирован');
  eq(ctx2._cogRequestFrame(), false, 'RAF: второй кадр не дублируется');
  eq(ctx2._cogDebugCounters().rafActive, true, 'RAF: кадр активен');
  let painted = 0;
  ctx2._cogScene.onFrame = function () { painted += 1; };
  eq(flushFrames(16), 1, 'RAF: исполнен ровно один кадр');
  eq(painted, 1, 'RAF: хук кадра вызван один раз');
  eq(ctx2._cogDebugCounters().rafActive, false,
    'RAF: цикл не продолжает сам себя (в пакете A анимации нет)');

  ctx2._cogRequestFrame();
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
  flushFrames(32);
  eq(ctx2._cogDebugCounters().rafActive, false,
    'RAF: после кадра снова покой (нет второго цикла)');

  // reduced-motion: непрерывных кадров нет вовсе (читаемость остаётся).
  const ctxRm = newCtx({ reducedMotion: true });
  await methods.renderCognitionGraph.call(ctxRm);
  eq(ctxRm._cogRequestFrame(), false, 'RAF: reduced-motion не запускает кадры');
  eq(ctxRm._cogDebugCounters().rafActive, false, 'RAF: reduced-motion — покой');
  ok(ctxRm.cognitionNetwork, 'reduced-motion: сцена и выбор доступны');

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

  console.log('EVOL-CMV-A-SCENE-OK checks=' + checks);
})();
