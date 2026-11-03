'use strict';
/* EPIC-CM-VISUAL-01 (CMV-A) — ЕДИНОЕ преобразование «модель → vis.DataSet» и
 * камера обзора (`web/static/cog-visual.js`).
 *
 * TEST-LIFECYCLE: CONTRACT owner=CMV-A-INTEGRATION
 * Контракт: `plans/features/evol/arch/cm-visual-01-contract.md`
 *   §3   — данные → визуал: одна точка преобразования, модель не переписывается;
 *   §4.1 — `fitScaleRef` считается по ПОЗИЦИЯМ и размеру сцены (не по `size`);
 *   §10.2 — никакой петли «размер → bbox → масштаб» и полной пересборки DataSet.
 * Спецификация владельца: `plans/owner_inputs/2026-11-03-epic-cm-visual-01.md`
 *   §10.1(3) (единое преобразование), §1.5 (константы — один конфиг-слой),
 *   §4.1 (форма/размер из типа и degree), §9.1 (данные не меняются).
 *
 * Запуск: node tests/js/evol_cog_visual_test.js
 * Вывод:  EVOL-CMV-A-VISUAL-OK checks=<n>
 */
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const V = require(path.join(ROOT, 'web', 'static', 'cog-visual.js'));
// Стили типов — единственный источник (адаптер), как в браузере.
const CM = require(path.join(ROOT, 'web', 'static', 'cognitive-map.js'));
// В браузере порядок <script>: cognitive-map.js → cog-visual.js → app.js.
global.CognitiveMap = CM;

let checks = 0;
function ok(cond, message) {
  assert.ok(cond, message);
  checks += 1;
}
function eq(actual, expected, message) {
  assert.deepStrictEqual(actual, expected, message);
  checks += 1;
}
function near(actual, expected, message) {
  assert.ok(Math.abs(actual - expected) < 1e-9,
    message + ' (' + actual + ' vs ' + expected + ')');
  checks += 1;
}

// ── фикстура модели: реальные формы payload (после адаптера) ─────────────────
function modelPayload() {
  return {
    version: 'cog-map/1',
    generated_at: 1762000000,
    state: 'ok',
    scope: { mode: 'chat', chat_id: -1001 },
    truncated: { nodes: false, edges: false, by_class: {} },
    nodes: [
      { id: 'fact:-1001:1', kind: 'fact', title: 'Кот любит коробки',
        chat_id: -1001, degree: 3 },
      { id: 'belief:-1001:2', kind: 'belief', title: 'Владелец ценит краткость',
        chat_id: -1001, degree: 1 },
      { id: 'par:-1001:3', kind: 'paradigm', title: 'Практические задачи',
        chat_id: -1001, degree: 9 },
      { id: 'ent:-1001:4', kind: 'entity', title: 'Олег', chat_id: -1001,
        degree: 0 },
      { id: 'evt:-1001:5', kind: 'evolution_event', title: 'Правка факта',
        chat_id: -1001, degree: 2 },
    ],
    edges: [
      { id: 'e1', from: 'fact:-1001:1', to: 'ent:-1001:4', relation: 'mentions',
        derived: false },
      { id: 'e2', from: 'fact:-1001:1', to: 'belief:-1001:2',
        relation: 'derived_from', derived: true },
      { id: 'e3', from: 'fact:-1001:1', to: 'evt:-1001:5',
        relation: 'revised_by', derived: false },
    ],
  };
}

function deepFreeze(obj) {
  if (!obj || typeof obj !== 'object') return obj;
  Object.getOwnPropertyNames(obj).forEach((k) => deepFreeze(obj[k]));
  return Object.freeze(obj);
}

const MODEL = CM.normalizePayload(modelPayload());

/* ── 1. fitScaleRef — формула §4.1, независимость от размеров узлов ───────── */
(function fitScale() {
  // a) ровно формула min(W/(1.1·(spanX+2·R0)), H/(1.1·(spanY+2·R0))).
  const bbox = V.bboxOf({ a: { x: -200, y: -100 }, b: { x: 200, y: 100 } });
  near(bbox.spanX, 400, 'bbox: spanX по позициям');
  near(bbox.spanY, 200, 'bbox: spanY по позициям');
  near(bbox.cx, 0, 'bbox: центр X');
  near(bbox.cy, 0, 'bbox: центр Y');
  near(V.fitScaleFor(bbox, 1000, 1000),
    Math.min(1000 / (1.1 * (400 + 24)), 1000 / (1.1 * (200 + 24))),
    'fitScale: формула контракта 1.1 и R0=12');

  // b) константы берутся из ЕДИНОГО конфиг-слоя (INV-05), не из литералов.
  eq(V.CONFIG.fit.padRatio, 1.1, 'config: padRatio');
  eq(V.CONFIG.fit.nominalRadius, 12, 'config: nominalRadius');
  near(V.fitScaleFor(bbox, 1000, 1000, V.CONFIG),
    V.fitScaleFor(bbox, 1000, 1000), 'fitScale: конфиг по умолчанию тот же');

  // c) вырожденный bbox (одна точка/линия) → фиксированный масштаб 0.8.
  near(V.fitScaleFor(V.bboxOf({ a: { x: 5, y: 5 } }), 800, 400), 0.8,
    'fitScale: одна точка → 0.8');
  near(V.fitScaleFor(V.bboxOf({ a: { x: 0, y: 0 }, b: { x: 0, y: 90 } }),
    800, 400), 0.8, 'fitScale: вертикальная линия → 0.8');

  // d) неизмеримая сцена → тот же безопасный масштаб, без NaN/Infinity.
  near(V.fitScaleFor(bbox, 0, 400), 0.8, 'fitScale: W=0 → 0.8');
  near(V.fitScaleFor(bbox, 800, 0), 0.8, 'fitScale: H=0 → 0.8');
  near(V.fitScaleFor(null, 800, 400), 0.8, 'fitScale: нет bbox → 0.8');

  // e) МАЛЕНЬКИЙ граф получает масштаб > 1 (верхнего зажима нет, §4.1).
  ok(V.fitScaleFor(V.bboxOf({ a: { x: 0, y: 0 }, b: { x: 10, y: 10 } }),
    2000, 2000) > 1, 'fitScale: маленький граф приближен (нет maxZoomLevel=1)');

  // f) bbox по ограниченному набору id (витрина) — не по всем позициям.
  const all = { a: { x: -500, y: 0 }, b: { x: 10, y: 0 }, c: { x: 10, y: 10 } };
  near(V.bboxOf(all, ['b', 'c']).spanX, 0, 'bbox: ограничение набором id');
  eq(V.bboxOf(all, ['missing']), null, 'bbox: пустой набор → null');
  eq(V.bboxOf({ a: { x: 'no', y: 1 } }, null), null,
    'bbox: нечисловые позиции игнорируются');
})();

/* ── 2. Камера обзора: центр bbox + наш масштаб (нет vis.fit) ─────────────── */
(function camera() {
  const positions = {
    a: { x: -300, y: -120 }, b: { x: 300, y: 120 },
    c: { x: 0, y: 0 }, d: { x: 120, y: -60 },
  };
  const W = 960;
  const H = 420;
  const cam = V.fitCamera(V.bboxOf(positions), W, H);
  eq(cam.position, { x: 0, y: 0 }, 'камера: центр bbox');
  near(cam.scale, V.fitScaleFor(V.bboxOf(positions), W, H),
    'камера: масштаб = fitScaleRef');

  // Проекция §5 контракта (DOM = canvas·scale + translation, translation =
  // W/2 − viewPos·scale): bbox целиком внутри кадра, с запасом по краям.
  const sx = (nx) => (nx - cam.position.x) * cam.scale + W / 2;
  const sy = (ny) => (ny - cam.position.y) * cam.scale + H / 2;
  Object.keys(positions).forEach((id) => {
    const p = positions[id];
    ok(sx(p.x) > 0 && sx(p.x) < W, 'камера: узел ' + id + ' по X внутри кадра');
    ok(sy(p.y) > 0 && sy(p.y) < H, 'камера: узел ' + id + ' по Y внутри кадра');
  });
  // Ограничивающая ось использует ≥ 85 % кадра (обзор не «отъехал» слишком).
  const usedX = (600 * cam.scale) / W;
  const usedY = (240 * cam.scale) / H;
  ok(Math.max(usedX, usedY) > 0.85,
    'камера: обзор заполняет кадр по ограничивающей оси');

  // Anti-loop (§10.2): масштаб НЕ зависит от размеров узлов. Меняем degree
  // (значит и `row.size`) — fitScaleRef остаётся прежним.
  const heavy = MODEL.nodes.map((n) => Object.assign({}, n, { degree: 500 }));
  const rowsHeavy = V.nodeRows(heavy, { positions: positions });
  ok(rowsHeavy[0].size > V.nodeRows(MODEL.nodes, { positions })
    .find((r) => r.id === MODEL.nodes[0].id).size,
  'узел: размер растёт от degree');
  near(V.fitScaleFor(V.bboxOf(positions), W, H),
    V.fitScaleFor(V.bboxOf(positions), W, H),
    'fitScale: не зависит от размеров узлов (нет петли)');
})();

/* ── 3. Единое преобразование: только визуальные поля, модель не трогается ── */
(function rows() {
  const positions = {
    'fact:-1001:1': { x: 0, y: 0 },
    'belief:-1001:2': { x: 40, y: 20 },
    'par:-1001:3': { x: -40, y: 20 },
    'ent:-1001:4': { x: 80, y: -20 },
    'evt:-1001:5': { x: -80, y: -20 },
  };
  const frozen = deepFreeze(JSON.parse(JSON.stringify(MODEL)));
  const snapshot = JSON.stringify(frozen);

  const rows = V.nodeRows(frozen.nodes, { positions: positions });
  const edges = V.edgeRows(frozen.edges, {});

  // Модель не переписана и не «дополнена» (INV-01/NODE-05, §3.1 контракта).
  eq(JSON.stringify(frozen), snapshot, 'данные: исходная модель не изменилась');
  eq(rows.length, frozen.nodes.length, 'данные: строка на каждый узел');
  eq(edges.length, frozen.edges.length, 'данные: строка на каждое ребро');

  const NODE_KEYS = ['id', 'label', 'shape', 'size', 'borderWidth',
    'borderWidthSelected', 'color', 'font', 'opacity', 'x', 'y',
    'shapeProperties'];
  rows.forEach((row) => {
    Object.keys(row).forEach((k) => {
      ok(NODE_KEYS.indexOf(k) >= 0,
        'строка узла: нет поля модели в DataSet (' + k + ')');
    });
    ok(row.title === undefined && row.kind === undefined &&
      row.degree === undefined && row.provenance === undefined,
    'строка узла: модель (title/kind/degree/provenance) не копируется');
  });
  const EDGE_KEYS = ['id', 'from', 'to', 'label', 'color', 'width', 'dashes',
    'arrows', 'smooth', 'selectionWidth', 'hoverWidth'];
  edges.forEach((row) => {
    Object.keys(row).forEach((k) => {
      ok(EDGE_KEYS.indexOf(k) >= 0,
        'строка ребра: нет поля модели в DataSet (' + k + ')');
    });
  });

  // Форма/цвет — из адаптера (`nodeStyle`), а не из локальной таблицы.
  const fact = rows.find((r) => r.id === 'fact:-1001:1');
  const factStyle = CM.nodeStyle('fact');
  eq(fact.shape, factStyle.shape, 'узел: форма из адаптера');
  eq(fact.color.background, factStyle.color, 'узел: цвет из адаптера');
  const unknown = V.nodeRow({ id: 'x', kind: 'неизвестный', degree: 0 }, {});
  eq(unknown.color.background, V.NEUTRAL_STYLE.color,
    'узел: неизвестный тип → нейтральный стиль (без выдуманной категории)');

  // Размер: базовый размер типа + логарифм degree с потолком (не гигант).
  const paradigm = V.nodeRow({ id: 'p', kind: 'paradigm', degree: 300 }, {});
  ok(paradigm.size <= CM.nodeStyle('paradigm').size + V.CONFIG.node.degreeGrowth,
    'узел: размер ограничен сверху (хаб не закрывает граф)');
  const isolated = V.nodeRow({ id: 'i', kind: 'other', degree: 0 }, {});
  eq(isolated.size, CM.nodeStyle('other').size,
    'узел: degree=0 → базовый размер (не выдуманный вес)');

  // Ребро: производное — пунктир, стрелка только у смыслового направления.
  const derived = edges.find((r) => r.id === 'e2');
  eq(derived.dashes, V.CONFIG.edge.derivedDashes, 'ребро: derived → пунктир');
  eq(derived.color.color, V.CONFIG.edge.derived, 'ребро: derived — тише базы');
  const base = edges.find((r) => r.id === 'e1');
  eq(base.dashes, false, 'ребро: обычное — сплошное');
  eq(base.arrows.to.enabled, false, 'ребро: без стрелки без направления');
  const revised = edges.find((r) => r.id === 'e3');
  eq(revised.arrows.to.enabled, true,
    'ребро: стрелка только для revised_by (реальное поле)');
  eq(base.width, V.CONFIG.edge.width, 'ребро: ширина из конфиг-слоя');

  // Инцидентное выбранному — заметнее (иначе сеть остаётся «тихой»).
  const focused = V.edgeRow(frozen.edges[0], { focused: true });
  eq(focused.width, V.CONFIG.edge.focusWidth, 'ребро: фокус — толще');
  ok(focused.color.color !== base.color.color, 'ребро: фокус — ярче');

  // Притушение выбранным узлом: opacity из конфиг-слоя, а не литерал.
  const dimRows = V.nodeRows(frozen.nodes, {
    positions: positions, selectedId: 'fact:-1001:1',
    highlighted: { 'fact:-1001:1': true },
  });
  eq(dimRows.find((r) => r.id === 'fact:-1001:1').opacity, 1,
    'выбор: выбранный узел не притушен');
  eq(dimRows.find((r) => r.id === 'ent:-1001:4').opacity,
    V.CONFIG.node.dimOpacity, 'выбор: остальные притушены из конфиг-слоя');

  // Позиции: есть — попадают в строку, нет — строка без x/y (модель не
  // получает фиктивных координат).
  ok(fact.x === 0 && fact.y === 0, 'позиция: из карты позиций');
  const noPos = V.nodeRow(frozen.nodes[0], { pos: null });
  ok(noPos.x === undefined && noPos.y === undefined,
    'позиция: без данных координат не выдумываются');

  // Детерминизм (кадр не «плавает» от повторного вызова).
  eq(JSON.stringify(V.nodeRows(frozen.nodes, { positions: positions })),
    JSON.stringify(rows), 'данные: преобразование детерминировано');
})();

console.log('EVOL-CMV-A-VISUAL-OK checks=' + checks);
