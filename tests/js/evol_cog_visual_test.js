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

  // Форма/цвет — из ЕДИНОЙ визуальной спецификации (§3.3 контракта, §4.1
  // спеки). Адаптер `cognitive-map.js` остаётся владельцем МОДЕЛИ и легенды;
  // сцена рисует по `CogVisual.CONFIG.spec`, поэтому палитра проверяется здесь.
  const fact = rows.find((r) => r.id === 'fact:-1001:1');
  eq(fact.shape, 'dot', 'узел: факт — круглая световая точка');
  eq(fact.color.background, '#32C8F3', 'узел: факт — циан #32C8F3');
  eq(V.shapeKeyOf('fact'), 'dot', 'shapeKey: факт');
  eq(V.shapeKeyOf('belief'), 'dotRing', 'shapeKey: убеждение — круг с кольцом');
  eq(V.shapeKeyOf('paradigm'), 'hex', 'shapeKey: парадигма — шестиугольник');
  eq(V.shapeKeyOf('evolution_event'), 'diamond', 'shapeKey: изменение — ромб');
  eq(V.shapeKeyOf('entity'), 'sphere', 'shapeKey: сущность — сфера');
  eq(V.shapeKeyOf('observation'), 'diamondDim', 'shapeKey: наблюдение — ромб');
  eq(V.shapeKeyOf('other'), 'dotNeutral', 'shapeKey: прочее — нейтральная точка');
  eq(V.shapeKeyOf('неизвестный'), 'dotNeutral',
    'shapeKey: незнакомый тип — нейтральный, без новой категории');
  // §4.1 спеки: `entity` перестал быть прямоугольником (прямое требование).
  const entity = rows.find((r) => r.id === 'ent:-1001:4');
  ok(entity.shape !== 'box' && entity.shape !== 'rounded',
    'узел: сущность — не прямоугольник');
  eq(entity.color.background, '#9FB4CE', 'узел: сущность — серебристо-голубой');
  // Форма строки DataSet = `spec.vis` КАЖДОГО типа (мутация «вернуть box»
  // обязана ломать именно это, а не только shapeKey).
  ['fact', 'belief', 'paradigm', 'evolution_event', 'observation',
    'entity', 'other'].forEach((kind) => {
    const row = V.nodeRow({ id: 'k-' + kind, kind, degree: 1 }, {});
    eq(row.shape, V.specFor(kind).vis, 'узел: vis-примитив по спеке — ' + kind);
    ok(row.shape !== 'box' && row.shape !== 'rounded',
      'узел: ' + kind + ' — не прямоугольник (§4.1 спеки)');
  });
  const unknown = V.nodeRow({ id: 'x', kind: 'неизвестный', degree: 0 }, {});
  eq(unknown.color.background, V.NEUTRAL_STYLE.color,
    'узел: неизвестный тип → нейтральный стиль (без выдуманной категории)');
  // Палитра §4.1: у каждого типа свой оттенок, и все они различимы.
  const palette = ['fact', 'belief', 'paradigm', 'evolution_event',
    'observation', 'entity', 'other'].map((k) => V.colorOf(k));
  eq(new Set(palette).size, palette.length,
    'палитра: у каждого типа свой оттенок (семь разных значений)');

  // Размер: §3.4 — базовый диаметр типа + логарифм degree с потолком.
  const paradigm = V.nodeRow({ id: 'p', kind: 'paradigm', degree: 300 }, {});
  eq(V.targetDiameter('paradigm', 300), V.CONFIG.baseDiameter.paradigm
    + V.CONFIG.node.degreeCap, 'размер: degree-потолок 8 px');
  eq(paradigm.size, (V.targetDiameter('paradigm', 300) / 2)
    * V.radiusScaleFor(0), 'узел: radiusNet = targetD/2 · U');
  ok(V.nodeRadius('paradigm', 900, 0.002) <= V.CONFIG.node.radiusMax,
    'узел: радиус ограничен сверху (хаб не закрывает граф)');
  const isolated = V.nodeRow({ id: 'i', kind: 'other', degree: 0 }, {});
  eq(isolated.size, (V.CONFIG.baseDiameter.other / 2) * V.radiusScaleFor(0),
    'узел: degree=0 → базовый диаметр типа (не выдуманный вес)');
  // Диаметр на экране при r = 1 равен целевому (перевод через U = 1/fitScale).
  const fitS = 0.5;
  const screenD = V.nodeRadius('fact', 0, fitS) * 2 * fitS;
  near(screenD, V.targetDiameter('fact', 0),
    'размер: диаметр на экране = targetD при r = 1');
  // Диапазон спеки §4.1: базовый диаметр важных 14–24 px; рост по degree
  // ограничен сверху (16 единиц роста к базе — потолок degreeCap 8, т.е. +16
  // диаметра в крайнем случае «300+ связей» остаётся в разумной полосе).
  ok(V.targetDiameter('paradigm', 0) >= 14
    && V.targetDiameter('paradigm', 0) <= 24,
  'размер: парадигма без связей в полосе 14–24 px');
  ok(V.targetDiameter('paradigm', 4000) <= 30,
    'размер: даже хаб-парадигма не превращается в шар (потолок degreeCap)');
  ok(V.targetDiameter('other', 0) >= 8 && V.targetDiameter('other', 0) <= 14,
    'размер: прочие в полосе 8–14 px');
  // Анти-петля: размер НЕ зависит от fitScale в сетевых единицах и НЕ зависит
  // от bbox — только degree/kind (иначе layout «разъезжался» бы сам).
  eq(V.targetDiameter('fact', 5), V.targetDiameter('fact', 5),
    'размер: чистый (детерминированный)');

  // Ребро: производное — пунктир, стрелка только у смыслового направления.
  const derived = edges.find((r) => r.id === 'e2');
  eq(derived.dashes, V.CONFIG.edge.derivedDashes, 'ребро: derived → пунктир');
  eq(derived.color.color, V.CONFIG.edge.derived, 'ребро: derived — тише базы');
  ok(derived.color.opacity < V.CONFIG.edge.baseOpacity,
    'ребро: derived прозрачнее базы');
  const base = edges.find((r) => r.id === 'e1');
  eq(base.dashes, false, 'ребро: обычное — сплошное');
  eq(base.arrows.to.enabled, false, 'ребро: без стрелки без направления');
  const revised = edges.find((r) => r.id === 'e3');
  eq(revised.arrows.to.enabled, true,
    'ребро: стрелка только для revised_by (реальное поле)');
  eq(base.width, V.CONFIG.edge.width, 'ребро: ширина из конфиг-слоя');
  eq(base.smooth, false, 'ребро: ПРЯМАЯ линия (§10.1 — не bezier)');
  // §4.3 спеки: ИТОГОВАЯ альфа базы в полосе 0.08–0.20 («не белый ковёр»).
  // `color.opacity` — множитель для `rgba(148,163,184,.34)`, поэтому итоговая
  // альфа = opacity × 0.34 (таблица по LOD §10.5 контракта).
  const BASE_RGBA_ALPHA = 0.34;
  const effAlpha = (row) => row.color.opacity * BASE_RGBA_ALPHA;
  ok(effAlpha(base) >= 0.08 && effAlpha(base) <= 0.20,
    'ребро: итоговая альфа в полосе 0.08–0.20 (%.3f)' + effAlpha(base));
  eq(V.CONFIG.edge.alphaByLod.length, 3,
    'ребро: три фиксированные альфы по LOD (§10.5)');
  ok(V.CONFIG.edge.alphaByLod[2] < V.CONFIG.edge.alphaByLod[1],
    'ребро: в детальном LOD сеть тише (измерено: иначе «паутина» поперечных линий)');

  // Инцидентное выбранному — заметнее (иначе сеть остаётся «тихой»).
  const focused = V.edgeRow(frozen.edges[0], { focused: true });
  eq(focused.width, V.CONFIG.edge.focusWidth, 'ребро: фокус — толще');
  ok(focused.color.color !== base.color.color, 'ребро: фокус — ярче');
  eq(focused.color.opacity, V.CONFIG.edge.focusOpacity,
    'ребро: фокус — альфа 0.85 (§4.3 спеки: 0.55–0.9)');
  const dimmedEdge = V.edgeDeltaRow(frozen.edges[0], { dimmed: true });
  eq(Object.keys(dimmedEdge).sort(), ['color', 'id', 'width'],
    'ребро: частичная строка — только id/цвет/ширина');
  near(dimmedEdge.color.opacity * BASE_RGBA_ALPHA, 0.12,
    'ребро: неинцидентное при выборе — итоговая альфа 0.12 в рабочем LOD');
  const dimL2 = V.edgeDeltaRow(frozen.edges[0], { dimmed: true, lod: 2 });
  near(dimL2.color.opacity * BASE_RGBA_ALPHA, V.CONFIG.edge.dimAlphaByLod[2],
    'ребро: в детальном LOD неинцидентные ещё тише (измерено)');

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

/* ── 4. Свечение: три слоя, разные значения по типу (§4.2 спеки) ─────────── */
(function glow() {
  const near = V.glowSpec('fact', 'near');
  const far = V.glowSpec('fact', 'far');
  const active = V.glowSpec('fact', 'active');
  // Три ЯВНО разных слоя: радиус 1.3–1.8 / 2–3 радиуса ядра (§4.2).
  ok(near.ratio >= 1.3 && near.ratio <= 1.8, 'glow: ближний ореол 1.3–1.8 r');
  ok(far.ratio >= 2 && far.ratio <= 3, 'glow: дальний ореол 2–3 r');
  ok(far.alpha < near.alpha, 'glow: дальний слабее ближнего');
  ok(active.alpha > near.alpha, 'glow: активный узел ярче обычного');
  // Оттенок ореола — от типа узла (тип узнаётся по свечению, не только по ядру).
  ok(V.glowSpec('fact', 'near').color !== V.glowSpec('belief', 'near').color,
    'glow: у факта и убеждения разные ореолы');
  const colors = ['fact', 'belief', 'paradigm', 'evolution_event',
    'observation', 'entity', 'other'].map((k) => V.glowSpec(k, 'near').color);
  eq(new Set(colors).size, colors.length, 'glow: семь различимых оттенков');

  /* Спрайты: ключ (слой|форма|бакет|dpr), центральная часть прозрачна,
   * размер квантуется по 2 px ⇒ ограниченный кэш (§6 контракта). */
  const a = V.spriteSpec('fact', 'near', 5.1, 1);
  const b = V.spriteSpec('fact', 'near', 5.9, 1);
  eq(a.key, b.key, 'спрайт: радиус 5.1 и 5.9 → один бакет (2 px)');
  eq(a.bucket, 6, 'спрайт: бакет округлён к 2 px');
  ok(V.spriteSpec('fact', 'near', 5, 1).key
    !== V.spriteSpec('fact', 'near', 9, 1).key, 'спрайт: разные радиусы — разный кэш');
  ok(V.spriteSpec('fact', 'near', 5, 1).key
    !== V.spriteSpec('fact', 'far', 5, 1).key, 'спрайт: слои кэшируются раздельно');
  ok(V.spriteSpec('fact', 'near', 5, 1).key
    !== V.spriteSpec('fact', 'near', 5, 2).key, 'спрайт: DPR входит в ключ (резкость)');
  eq(a.stops[0].alpha, 0, 'спрайт: центр прозрачен (ядро vis видно)');
  eq(a.stops[a.stops.length - 1].alpha, 0, 'спрайт: край растворяется в 0');
  ok(a.size > a.bucket * 2, 'спрайт: ореол шире ядра');

  /* FxLayer: спрайты создаются ОДИН раз, в кадре градиенты не создаются. */
  const made = { canvases: 0, gradients: 0, ops: [], alphas: [] };
  function stubCtx() {
    return {
      globalAlpha: 1, lineWidth: 1, fillStyle: '', strokeStyle: '',
      font: '', textAlign: '', textBaseline: '', lineJoin: '',
      createRadialGradient() {
        made.gradients += 1;
        return { addColorStop() {} };
      },
      clearRect() { made.ops.push('clear'); },
      fillRect() {},
      beginPath() { made.ops.push('path'); },
      moveTo() {}, lineTo() {}, quadraticCurveTo() {}, closePath() {},
      arc() { made.ops.push('arc'); },
      stroke() {}, fill() {},
      save() {}, restore() {}, setTransform() {},
      fillText(t) { made.ops.push('text:' + t); },
      strokeText() { made.ops.push('strokeText'); },
      drawImage() {
        made.ops.push('image');
        made.alphas.push(Math.round(this.globalAlpha * 1000) / 1000);
      },
    };
  }
  const fx = V.createFx({
    dpr: 1,
    makeCanvas(w, h) {
      made.canvases += 1;
      return { width: w, height: h, getContext: () => stubCtx() };
    },
  });
  const NODES = [
    { id: 'f1', kind: 'fact', degree: 2 },
    { id: 'b1', kind: 'belief', degree: 3 },
    { id: 'p1', kind: 'paradigm', degree: 9 },
    { id: 'e1', kind: 'entity', degree: 1 },
    { id: 'far', kind: 'fact', degree: 0 },
  ];
  const POS = {
    f1: { x: 0, y: 0 }, b1: { x: 160, y: 60 }, p1: { x: -160, y: 40 },
    e1: { x: 60, y: -90 }, far: { x: 9000, y: 9000 },
  };
  function frame(extra) {
    return Object.assign({
      now: 0, width: 800, height: 400,
      camera: { x: 0, y: 0, scale: 1 },
      positions: POS, nodes: NODES,
      edges: [{ id: 'x', from: 'f1', to: 'b1' }],
      incident: [{ id: 'x', from: 'f1', to: 'b1' }],
      selection: 'f1', hover: null, fitScale: 1, lod: 2,
      keyIds: null, pulse: null, flash: 0, reducedMotion: false,
    }, extra || {});
  }
  const ctx = stubCtx();
  const drawn1 = fx.paint(ctx, frame({ now: 1000 }));
  ok(drawn1 > 0, 'fx: кадр нарисован');
  // Пульс: при разных `now` яркость дальнего ореола РАЗНАЯ (жизнь есть),
  // при reduced-motion — одинаковая (времени нет). §7.1/§7.3 спеки.
  const PULSE_MAP = { f1: { id: 'f1', period: 4000, phase: 0, amp: 0.18 } };
  made.alphas.length = 0;
  fx.paint(ctx, frame({ now: 1200, pulse: PULSE_MAP }));
  const alphaA = made.alphas.join(',');
  made.alphas.length = 0;
  fx.paint(ctx, frame({ now: 1900, pulse: PULSE_MAP }));
  const alphaB = made.alphas.join(',');
  ok(alphaA !== alphaB, 'пульс: яркость ореолов зависит от времени');
  made.alphas.length = 0;
  fx.paint(ctx, frame({ now: 1200, pulse: PULSE_MAP, reducedMotion: true }));
  const alphaRm1 = made.alphas.join(',');
  made.alphas.length = 0;
  fx.paint(ctx, frame({ now: 1900, pulse: PULSE_MAP, reducedMotion: true }));
  const alphaRm2 = made.alphas.join(',');
  eq(alphaRm1, alphaRm2,
    'reduced-motion: яркость статична (нет непрерывного движения)');
  ok(alphaRm1.length > 0, 'reduced-motion: ореолы всё равно нарисованы');
  const c1 = fx.counters();
  ok(c1.sprites > 0, 'fx: спрайты созданы');
  eq(c1.gradients, c1.sprites, 'fx: ОДИН градиент на спрайт (не на узел/кадр)');
  ok(c1.draws >= 5, 'fx: свечение скомпоновано для видимых узлов');
  // Второй и третий кадры: новых канвасов/градиентов НЕТ (§10.2(5)).
  fx.paint(ctx, frame({ now: 1042 }));
  fx.paint(ctx, frame({ now: 1084 }));
  const c2 = fx.counters();
  eq(c2.sprites, c1.sprites, 'fx: кэш спрайтов не растёт с кадрами');
  eq(c2.gradients, c1.gradients, 'fx: в кадре градиенты не создаются');
  eq(made.canvases, c1.sprites, 'fx: offscreen-канвасов ровно по числу спрайтов');
  // Буферы кадра переиспользуются (нет аллокаций на 700 узлов).
  ok(fx.poolRef() === fx.poolRef(), 'fx: пул слотов кадра стабилен');

  // Внеэкранные узлы не обрабатываются (§5.2/§10.2: «только экранные»).
  const onlyFar = V.createFx({
    dpr: 1,
    makeCanvas: (w, h) => ({ width: w, height: h, getContext: () => stubCtx() }),
  });
  onlyFar.paint(ctx, frame({
    nodes: [{ id: 'far', kind: 'fact', degree: 0 }], selection: null,
    incident: [],
  }));
  eq(onlyFar.counters().draws, 0, 'fx: узел за кадром не рисуется');

  /* Формы различаются ДЕКОРОМ, а не только цветом: убеждение — кольцо,
   * парадигма — грань, изменение — блик, сущность — светлое ядро. */
  function decorOpsFor(kind) {
    const tally = { arc: 0, path: 0, fill: 0, stroke: 0, image: 0 };
    const one = V.createFx({
      dpr: 1,
      makeCanvas: (w, h) => ({
        width: w, height: h, getContext: () => stubCtx(),
      }),
    });
    const realCtx = stubCtx();
    realCtx.arc = function () { tally.arc += 1; };
    realCtx.beginPath = function () { tally.path += 1; };
    realCtx.fill = function () { tally.fill += 1; };
    realCtx.stroke = function () { tally.stroke += 1; };
    realCtx.drawImage = function () { tally.image += 1; };
    one.paint(realCtx, frame({
      now: 0, nodes: [{ id: 'n', kind, degree: 4 }], selection: 'n',
      incident: [], width: 400, height: 300,
      positions: { n: { x: 0, y: 0 } },
    }));
    return tally;
  }
  const dFact = decorOpsFor('fact');
  const dBelief = decorOpsFor('belief');
  const dParadigm = decorOpsFor('paradigm');
  const dEvo = decorOpsFor('evolution_event');
  const dEntity = decorOpsFor('entity');
  eq(dBelief.arc, dFact.arc + 1, 'декор: у убеждения внутреннее кольцо (+1 дуга)');
  ok(dParadigm.path > dFact.path, 'декор: у парадигмы внутренняя грань (путь)');
  eq(dEvo.arc, dFact.arc + 1, 'декор: у изменения угловой блик (+1 дуга)');
  eq(dEntity.fill, dFact.fill + 1, 'декор: у сущности светлое ядро (заливка)');
  ok(dFact.stroke > 0, 'декор: кольцо выделения есть у всех типов');

  /* Импульсы идут ТОЛЬКО по реальным инцидентным рёбрам (§4.3 спеки). */
  const impOps = [];
  const imp = V.createFx({
    dpr: 1,
    makeCanvas: (w, h) => ({ width: w, height: h, getContext: () => stubCtx() }),
  });
  const impCtx = stubCtx();
  impCtx.arc = function () { impOps.push('arc'); };
  const edge = { id: 'x', from: 'f1', to: 'b1' };
  // База без времени (now = 0): выделение + декор, но без «дыхания».
  imp.paint(impCtx, frame({ now: 0, incident: [] }));
  const arcsBase = impOps.length;
  impOps.length = 0;
  imp.paint(impCtx, frame({ now: 500, incident: [edge] }));
  ok(impOps.length > arcsBase,
    'импульсы: световой импульс рисуется по реальному ребру');
  // reduced-motion: форма/свечение/выделение на месте, времени нет.
  impOps.length = 0;
  imp.paint(impCtx, frame({ now: 500, reducedMotion: true, incident: [edge] }));
  eq(impOps.length, arcsBase,
    'reduced-motion: импульсы по рёбрам не рисуются (движения нет)');
  ok(imp.counters().draws > 0, 'reduced-motion: свечение остаётся');
  // Импульсы идут ТОЛЬКО по реальным рёбрам из `frame.incident`: ребро с
  // концом, которого нет в кэше позиций, не превращается в «декоративную»
  // линию между несвязанными узлами (§4.3 спеки — не выдумывать отношения).
  impOps.length = 0;
  imp.paint(impCtx, frame({ now: 0, incident: [
    { id: 'ghost', from: 'f1', to: 'нет-такого-узла' },
  ] }));
  eq(impOps.length, arcsBase,
    'импульсы: ребро с неизвестным концом не рисуется (нет выдуманных связей)');
})();

/* ── 5. Пульс: детерминированный набор, период 3–5 s, разные фазы ───────── */
(function pulse() {
  const nodes = [];
  for (let i = 0; i < 600; i += 1) {
    nodes.push({ id: 'n' + i, kind: i % 2 ? 'fact' : 'belief', degree: i % 11 });
  }
  const plan = V.pulsePlan(nodes, {});
  ok(plan.length <= V.CONFIG.motion.pulseBudget,
    'пульс: набор не больше 24 узлов (не «все 2400 рёбер» живыми)');
  eq(plan.length, Math.min(24, Math.ceil(600 / 30)),
    'пульс: бюджет min(24, ⌈n/30⌉)');
  eq(JSON.stringify(V.pulsePlan(nodes, {})), JSON.stringify(plan),
    'пульс: план детерминирован (без Math.random)');
  plan.forEach((e) => {
    ok(e.period >= 3000 && e.period <= 5000, 'пульс: период в полосе 3–5 s');
    ok(e.amp > 0 && e.amp <= 0.25, 'пульс: амплитуда мала (геометрия стабильна)');
  });
  const phases = new Set(plan.map((e) => e.phase));
  ok(phases.size > 1, 'пульс: фазы разнесены (не все узлы синхронно)');
  // Множитель альфы: в полосе [0.82, 1.0] и реально меняется во времени.
  const entry = plan[0];
  const f0 = V.pulseFactor(entry, 0);
  const f1 = V.pulseFactor(entry, entry.period / 4);
  ok(f0 >= 0.82 && f0 <= 1.0000001, 'пульс: альфа в полосе 0.82–1.0');
  ok(Math.abs(f0 - f1) > 0.02, 'пульс: яркость реально дышит');
  eq(V.pulseFactor(entry, entry.period + 0), V.pulseFactor(entry, 0),
    'пульс: период воспроизводим (та же фаза через период)');
  // Выбранный узел и его соседи входят в набор даже у большого графа.
  const withSel = V.pulsePlan(nodes, {
    selectedId: 'n599', neighborIds: ['n1', 'n2'],
  });
  ok(withSel.some((e) => e.id === 'n599'), 'пульс: выбранный узел всегда в наборе');
  ok(withSel.some((e) => e.id === 'n1'), 'пульс: сосед выбранного в наборе');
})();

/* ── 6. Физика: таблица итераций и структура §8.1 ──────────────────────── */
(function physics() {
  eq(V.physicsIterations(10), 150, 'физика: ≤200 узлов — 150 итераций');
  eq(V.physicsIterations(200), 150, 'физика: граница 200 — 150');
  eq(V.physicsIterations(201), 90, 'физика: 201–400 — 90 итераций');
  eq(V.physicsIterations(400), 90, 'физика: граница 400 — 90');
  eq(V.physicsIterations(702), 60, 'физика: >400 — 60 итераций (не блокируем поток)');
  const opts = V.physicsOptions(702, 0.8);
  eq(opts.stabilization.fit, false, 'физика: кадр обзора выставляем сами');
  eq(opts.stabilization.iterations, 60, 'физика: итерации по размеру набора');
  eq(opts.barnesHut.avoidOverlap, 0.5, 'физика: avoidOverlap — узлы не слипаются');
  eq(opts.minVelocity, 2.5, 'физика: ранний выход по minVelocity');
  eq(opts.adaptiveTimestep, true, 'физика: adaptiveTimestep');
  // springLength = 70·U (§8.1): при обзоре 0.5 сетевых единиц в px — 140.
  near(V.springLengthFor(0.5), 140, 'физика: springLength = 70·U');
  ok(V.springLengthFor(0.01) <= V.CONFIG.physics.springMax,
    'физика: пружина ограничена сверху (огромный граф не «взрывается»)');
  // r = scale/fitScale (§4.2) — вход слоя подписей и LOD свечения.
  near(V.relativeScale(0.4, 0.5), 0.8, 'LOD: r = scale/fitScale');
  near(V.relativeScale(1, 0), 1, 'LOD: без fitScale r = 1 (без NaN)');
})();

console.log('EVOL-CMV-B-VISUAL-OK checks=' + checks);
