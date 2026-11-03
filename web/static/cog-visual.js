'use strict';
/* EPIC-CM-VISUAL-01 (CMV-A, пакет «интеграция/инварианты») — ЕДИНАЯ точка
 * преобразования «модель → строка vis.DataSet» и «позиции → камера обзора».
 *
 * TEST-LIFECYCLE: CONTRACT (owner=CMV-A-INTEGRATION)
 * Контракт: `plans/features/evol/arch/cm-visual-01-contract.md` §3 (данные →
 * визуал), §4.1 (`fitScaleRef`), §10.2 (никакой петли «размер → bbox → масштаб»),
 * спецификация: `plans/owner_inputs/2026-11-03-epic-cm-visual-01.md` §10.1 (3).
 *
 * Зачем отдельный файл, а не правка `cognitive-map.js`:
 *   1. §10.1(3) требует РОВНО ОДНОГО преобразования nodes/edges → DataSet;
 *      адаптер `cognitive-map.js` остаётся владельцем модели и стилей
 *      (`nodeStyle`), а визуальная арифметика (форма/размер/цвет/альфа ребра)
 *      собирается здесь — в одном месте, доступном node-тестам без DOM.
 *   2. `web/static/cognitive-map.js` — полоса CMV-C; этот файл её не трогает.
 *
 * ИНВАРИАНТЫ (§1 спеки, §3 контракта):
 *   * функции ЧИСТЫЕ: исходный узел/ребро не мутируется и не «дополняется»;
 *     строка DataSet содержит ТОЛЬКО визуальные поля (id + геометрия + цвет +
 *     форма + размер), ни одно поле модели (title/kind/degree/provenance/время)
 *     в строку не копируется и обратно в модель не пишется;
 *   * размер узла считается из `degree` и НЕ зависит от `fitScaleRef` — поэтому
 *     `fitScaleRef` (по позициям) не образует петлю обратной связи;
 *   * стили типов берутся из адаптера (`CognitiveMap.nodeStyle`), а не из
 *     собственной таблицы: цвета/формы остаются в `cognitive-map.js`.
 *
 * Потребитель: `web/app.js` (`_cogNodeRow`/`_cogEdgeRow`/`_cogCreateNetwork`/
 * `_cogApplyFit`). Тесты: `tests/js/evol_cog_visual_test.js`.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;                 // node unit-тесты
  } else if (root) {
    root.CogVisual = api;                 // браузер: window.CogVisual
  }
}(typeof globalThis !== 'undefined' ? globalThis
  : (typeof window !== 'undefined' ? window
    : (typeof self !== 'undefined' ? self : this)), function (root) {
  'use strict';

  var VERSION = 'cog-visual/1';

  /* ── ЕДИНЫЙ конфигурационный слой визуала (INV-05) ─────────────────────
   * Геометрия, цвета полупрозрачности, длительности и пороги — параметры, а не
   * смысловой хардкод. Пакет A фиксирует здесь ровно то, что уже работало в
   * S1–S3 (никакой визуальной драмы): формы/свечение/LOD меняют B/C/D.
   * Типографика слоя подписей (`COG_MAP_LABEL_*`) пока живёт в `app.js` —
   * её переносит пакет, который переписывает сам слой подписей. */
  var CONFIG = {
    fit: {
      // Множитель 1.1 и структура `min()` повторяют фактический vis.fit()
      // 9.1.9, чтобы кадр «обзор» совпадал с ожиданием пользователя (§4.1).
      padRatio: 1.1,
      // Номинальный радиус-паддинг в CSS-px → сетевые единицы (без него точки
      // на краю bbox упирались бы в границу сцены).
      nominalRadius: 12,
      // Вырожденный bbox (одна точка / линия) — фиксированный масштаб.
      fallbackScale: 0.8,
    },
    node: {
      // Прибавка к базовому размеру от degree: логарифм + потолок, чтобы хаб не
      // превращался в шар, закрывающий граф (§4.1 спеки).
      degreeGrowth: 5,
      borderWidth: 1,
      borderWidthSelected: 2,
      hoverBorder: '#e2e8f0',
      dimOpacity: 0.25,
      boxRadius: 5,
      plainBoxRadius: 2,
    },
    edge: {
      width: 0.7,
      focusWidth: 1.5,
      base: 'rgba(148,163,184,.34)',
      derived: 'rgba(148,163,184,.20)',
      focus: 'rgba(226,232,240,.80)',
      highlight: 'rgba(226,232,240,.85)',
      hover: 'rgba(203,213,225,.60)',
      derivedDashes: [3, 4],
      selectionWidth: 1.6,
      hoverWidth: 1.4,
      smooth: { type: 'continuous', roundness: 0.35 },
      // Единственное смысловое поле направления в payload (реальное отношение).
      arrowRelation: 'revised_by',
    },
  };

  // Нейтральный стиль неизвестного типа (не новая категория онтологии, §4.1).
  var NEUTRAL_STYLE = { color: '#64748b', shape: 'dot', size: 10, legend: false };

  function adapter() {
    var A = root && root.CognitiveMap;
    // node-песочницы грузят app.js с `global.window`: адаптер ищем и там,
    // чтобы тесты видели те же стили, что браузер.
    if (!A && root && root.window && root.window.CognitiveMap) {
      A = root.window.CognitiveMap;
    }
    return A || null;
  }

  /* styleFor(kind) — стиль типа из адаптера (единственный источник цветов). */
  function styleFor(kind) {
    var A = adapter();
    if (A && typeof A.nodeStyle === 'function') {
      var style = A.nodeStyle(kind);
      if (style && style.shape && style.color) return style;
    }
    return NEUTRAL_STYLE;
  }

  function finite(value) {
    return (typeof value === 'number' && isFinite(value)) ? value : null;
  }

  /* ── bbox по ПОЗИЦИЯМ (никогда по размерам узлов) ───────────────────────
   * bboxOf(positions, ids) → {minX,minY,maxX,maxY,spanX,spanY,cx,cy,count}|null
   * `positions` — как отдаёт vis (`{id: {x,y}}`); `ids` — ограничение набора
   * (например, видимая витрина), по умолчанию все ключи. */
  function bboxOf(positions, ids) {
    if (!positions || typeof positions !== 'object') return null;
    var list = (ids && ids.length) ? ids : Object.keys(positions);
    var minX = Infinity;
    var minY = Infinity;
    var maxX = -Infinity;
    var maxY = -Infinity;
    var count = 0;
    for (var i = 0; i < list.length; i += 1) {
      var p = positions[list[i]];
      if (!p) continue;
      var x = finite(p.x);
      var y = finite(p.y);
      if (x === null || y === null) continue;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
      count += 1;
    }
    if (!count) return null;
    return {
      minX: minX, minY: minY, maxX: maxX, maxY: maxY,
      spanX: maxX - minX, spanY: maxY - minY,
      cx: (minX + maxX) / 2, cy: (minY + maxY) / 2,
      count: count,
    };
  }

  /* fitScaleFor(bbox, width, height, cfg) — формула §4.1 контракта:
   *   fitScaleRef = (spanX<=0 || spanY<=0) ? 0.8
   *                 : min(W / (1.1·(spanX+2·R0)), H / (1.1·(spanY+2·R0)))
   * Верхнего зажима нет (у vis он `maxZoomLevel = 1`): маленький граф может
   * получить масштаб > 1 — это ожидаемо и одинаково для всех графов. */
  function fitScaleFor(bbox, width, height, cfg) {
    var c = (cfg && cfg.fit) || CONFIG.fit;
    if (!bbox) return c.fallbackScale;
    var w = finite(width);
    var h = finite(height);
    if (w === null || h === null || w <= 0 || h <= 0) return c.fallbackScale;
    if (!(bbox.spanX > 0) || !(bbox.spanY > 0)) return c.fallbackScale;
    var sx = c.padRatio * (bbox.spanX + 2 * c.nominalRadius);
    var sy = c.padRatio * (bbox.spanY + 2 * c.nominalRadius);
    var scale = Math.min(w / sx, h / sy);
    if (!isFinite(scale) || scale <= 0) return c.fallbackScale;
    return scale;
  }

  /* fitCamera(bbox, width, height) → {position:{x,y}, scale, bbox}|null
   * Одна камера обзора: центр bbox + собственный масштаб. Никакого `fit()`:
   * vis-овский fit зависит от размеров узлов (§2 контракта). */
  function fitCamera(bbox, width, height, cfg) {
    if (!bbox) return null;
    return {
      position: { x: bbox.cx, y: bbox.cy },
      scale: fitScaleFor(bbox, width, height, cfg),
      bbox: bbox,
    };
  }

  /* ── модель → строка DataSet ────────────────────────────────────────────
   * nodeRow(node, opts):
   *   opts.pos        — {x,y} текущая позиция (не меняет модель);
   *   opts.style      — стиль типа (по умолчанию `styleFor(node.kind)`);
   *   opts.dim        — притушить (есть выбор, узел не в подсветке).
   * Возвращает ТОЛЬКО визуальные поля. */
  function nodeRow(node, opts) {
    var o = opts || {};
    var style = o.style || styleFor(node && node.kind);
    var shape = style.shape;
    var cfg = (o.cfg && o.cfg.node) || CONFIG.node;
    var size = (typeof style.size === 'number') ? style.size : NEUTRAL_STYLE.size;
    var degree = (node && typeof node.degree === 'number') ? node.degree : 0;
    if (degree > 0) size += Math.min(cfg.degreeGrowth, Math.log(1 + degree));
    var row = {
      id: node.id,
      label: '',
      shape: shape,
      size: size,
      borderWidth: cfg.borderWidth,
      borderWidthSelected: cfg.borderWidthSelected,
      color: {
        background: style.color,
        border: style.color,
        highlight: { background: style.color, border: cfg.hoverBorder },
        hover: { background: style.color, border: cfg.hoverBorder },
      },
      font: { size: 0 },
      opacity: o.dim ? cfg.dimOpacity : 1,
    };
    if (shape === 'rounded' || shape === 'box') {
      row.shape = 'box';
      row.shapeProperties = {
        borderRadius: shape === 'rounded' ? cfg.boxRadius : cfg.plainBoxRadius,
      };
    }
    var pos = o.pos;
    if (pos && finite(pos.x) !== null && finite(pos.y) !== null) {
      row.x = pos.x;
      row.y = pos.y;
    }
    return row;
  }

  /* edgeRow(edge, opts):
   *   opts.focused — ребро инцидентно выбранному узлу.
   * Производное ребро (`derived`) — пунктир: это РЕАЛЬНАЯ ссылка из данных,
   * а не догадка. Стрелка только для смыслового направления payload. */
  function edgeRow(edge, opts) {
    var o = opts || {};
    var cfg = (o.cfg && o.cfg.edge) || CONFIG.edge;
    var focused = !!o.focused;
    var color = focused ? cfg.focus
      : (edge.derived ? cfg.derived : cfg.base);
    return {
      id: edge.id,
      from: edge.from,
      to: edge.to,
      label: '',
      color: {
        color: color,
        highlight: cfg.highlight,
        hover: cfg.hover,
        opacity: 1,
      },
      width: focused ? cfg.focusWidth : cfg.width,
      dashes: edge.derived === true ? cfg.derivedDashes.slice() : false,
      arrows: { to: { enabled: edge.relation === cfg.arrowRelation } },
      smooth: { type: cfg.smooth.type, roundness: cfg.smooth.roundness },
      selectionWidth: cfg.selectionWidth,
      hoverWidth: cfg.hoverWidth,
    };
  }

  /* Батч-преобразование: единственная точка для сцены. `opts` — состояние
   * отображения (позиции/подсветка/выбор), модель только читается. */
  function nodeRows(nodes, opts) {
    var o = opts || {};
    var out = [];
    var list = nodes || [];
    var positions = o.positions || {};
    var highlighted = o.highlighted || null;
    var selectedId = (o.selectedId === undefined) ? null : o.selectedId;
    for (var i = 0; i < list.length; i += 1) {
      var node = list[i];
      if (!node || node.id === undefined || node.id === null) continue;
      out.push(nodeRow(node, {
        pos: positions[node.id] || null,
        style: o.styleFor ? o.styleFor(node.kind) : styleFor(node.kind),
        dim: !!(selectedId != null && !(highlighted && highlighted[node.id])),
        cfg: o.cfg,
      }));
    }
    return out;
  }

  function edgeRows(edges, opts) {
    var o = opts || {};
    var out = [];
    var list = edges || [];
    var focus = o.edgeFocus || null;
    for (var i = 0; i < list.length; i += 1) {
      var edge = list[i];
      if (!edge || edge.id === undefined || edge.id === null) continue;
      out.push(edgeRow(edge, {
        focused: !!(focus && focus[edge.id]),
        cfg: o.cfg,
      }));
    }
    return out;
  }

  return {
    VERSION: VERSION,
    CONFIG: CONFIG,
    NEUTRAL_STYLE: NEUTRAL_STYLE,
    styleFor: styleFor,
    bboxOf: bboxOf,
    fitScaleFor: fitScaleFor,
    fitCamera: fitCamera,
    nodeRow: nodeRow,
    edgeRow: edgeRow,
    nodeRows: nodeRows,
    edgeRows: edgeRows,
  };
}));
