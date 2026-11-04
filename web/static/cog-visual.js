'use strict';
/* EPIC-CM-VISUAL-01 (CMV-A/B) — ЕДИНАЯ точка преобразования «модель → строка
 * vis.DataSet», «позиции → камера обзора» и «состояние сцены → кадр слоя `fx`».
 *
 * TEST-LIFECYCLE: CONTRACT (owner=CMV-B-SCENE-PHYSICS)
 * Контракт: `plans/features/evol/arch/cm-visual-01-contract.md`
 *   §3   (данные → визуал: shapeKey/размер/альфа ребра),
 *   §4.1 (`fitScaleRef` без петли «размер→bbox→масштаб»),
 *   §5.1 (экранные координаты, кэш позиций), §6 (слой `fx`, спрайты, DPR),
 *   §7   (пульс/импульсы/сокращение движения), §8.1 (таблица итераций).
 * Спецификация: `plans/owner_inputs/2026-11-03-epic-cm-visual-01.md`
 *   §4.1 (формы/палитра/диаметры), §4.2 (три слоя свечения), §4.3 (рёбра),
 *   §4.4 (подписи без плашек), §7.1–§7.3 (мягкая жизнь, reduced-motion),
 *   §10.1(3)(5) (единое преобразование, один владелец кадра), §10.2 (FPS).
 *
 * Зачем отдельный файл, а не правка `cognitive-map.js`:
 *   1. §10.1(3) требует РОВНО ОДНОГО преобразования nodes/edges → DataSet;
 *      адаптер `cognitive-map.js` остаётся владельцем МОДЕЛИ (нормализация,
 *      поиск, карточки), а визуальная арифметика (форма/размер/цвет/альфа
 *      ребра/свечение/пульс) собирается здесь — в одном месте, доступном
 *      node-тестам без DOM и без canvas.
 *   2. `web/static/cognitive-map.js` — полоса CMV-C; этот файл её не трогает.
 *
 * ИНВАРИАНТЫ (§1 спеки, §3 контракта):
 *   * функции ЧИСТЫЕ: исходный узел/ребро не мутируется и не «дополняется»;
 *     строка DataSet содержит ТОЛЬКО визуальные поля (id + геометрия + цвет +
 *     форма + размер), ни одно поле модели (title/kind/degree/provenance/время)
 *     в строку не копируется и обратно в модель не пишется;
 *   * размер узла считается из `degree` и НЕ зависит от позиций/bbox —
 *     поэтому `fitScaleRef` (по позициям) не образует петлю обратной связи;
 *     допускается только ВЕРХНИЙ предел ЭКРАННОГО диаметра: потолок спеки
 *     24 px (§4.1) и локальная плотность кадра (`densityCaps`, §5.1 спеки);
 *   * `prefers-reduced-motion` убирает ТОЛЬКО время (пульс/импульсы/интерполяцию
 *     hover), но сохраняет формы, свечение, выделение и подписи (§7.3 спеки).
 *
 * Потребитель: `web/app.js` (`_cogNodeRow`/`_cogEdgeRow`/`_cogCreateNetwork`/
 * `_cogApplyFit`/`_cogPaintFx`). Тесты: `tests/js/evol_cog_visual_test.js`,
 * `tests/js/evol_cog_scene_test.js`.
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

  var VERSION = 'cog-visual/3';

  /* ── ЕДИНЫЙ конфигурационный слой визуала (INV-05) ─────────────────────
   * Геометрия, палитра, полупрозрачность, длительности и пороги — параметры, а
   * не смысловой хардкод. Формы/цвета — спека §4.1 (таблица типов), поэтому
   * палитра живёт здесь: адаптер `cognitive-map.js` остаётся владельцем модели
   * и легенды (легенда подписана ТЕМИ ЖЕ hex — см. `.cog-legend__swatch--*`). */
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
    /* §3.3 контракта: kind → (shapeKey, vis-примитив, декор, цвет ядра).
     * `anchor` — доля базового диаметра для внутреннего кольца/грани (декор
     * рисует слой `fx`, а не vis: иначе понадобился бы `ctxRenderer` и
     * `net.redraw()` на каждый импульс — §6 контракта). */
    spec: {
      fact: { key: 'dot', vis: 'dot', decor: null,
        color: '#32C8F3', rim: 0.55 },
      belief: { key: 'dotRing', vis: 'dot', decor: 'ring',
        color: '#A77BFF', rim: 0.60 },
      paradigm: { key: 'hex', vis: 'hexagon', decor: 'facet',
        color: '#728CFF', rim: 0.50 },
      evolution_event: { key: 'diamond', vis: 'diamond', decor: 'glint',
        color: '#FFB84D', rim: 0.60 },
      observation: { key: 'diamondDim', vis: 'diamond', decor: null,
        color: '#D97706', rim: 0.35 },
      entity: { key: 'sphere', vis: 'dot', decor: 'core',
        color: '#9FB4CE', rim: 0.50 },
      other: { key: 'dotNeutral', vis: 'dot', decor: null,
        color: '#64748B', rim: 0.40 },
    },
    /* §3.4 контракта: базовый диаметр типа в CSS-px при r = 1 (спека §4.1:
     * важные 14–24 px, менее значимые 8–14 px). */
    baseDiameter: {
      paradigm: 22, belief: 18, fact: 14, evolution_event: 13,
      entity: 11, observation: 10, other: 9,
    },
    node: {
      // targetD = kindBaseD + min(degreeCap, degreeK·log2(1+degree)).
      degreeK: 2.2,
      degreeCap: 8,
      // §4.1 спеки: важные узлы 14–24 px, менее значимые 8–14 px. База + degreeCap
      // могла дать 30 px (парадигма-хаб), поэтому потолок диаметра — 24 px.
      maxScreenDiameter: 24,
      /* §5.1 спеки: «содержимое сцены зависит от масштаба, ПЛОТНОСТИ НА ЭКРАНЕ и
       * выбранного узла», §4.1: «не рисовать огромные фигуры, которые закрывают
       * соседей». На приёмочном кадре 702/2400 суммарная площадь кругов по
       * спецификации втрое больше занятого раскладкой места — узлы стоят стеной
       * (замер CMV-B: 46 683 пересекающиеся пары, 19 % всех пар). Поэтому
       * экранный диаметр ограничен ЛОКАЛЬНОЙ плотностью:
       *   cap_i = clamp(densityFactor · d_rank(i), minScreenDiameter, maxScreenDiameter),
       * где d_rank(i) — расстояние при r = 1 до `densityRank`-го ближайшего соседа.
       * Свойство: и диаметр, и просветы масштабируются одинаково, поэтому
       * различимость сохраняется на любом зуме; уединённый узел остаётся в
       * полосе спеки, плотное ядро — различимые точки, а не «пыль».
       * Позиции от размера не зависят ⇒ петли «размер → bbox → масштаб» нет. */
      densityFactor: 0.9,
      densityRank: 3,
      minScreenDiameter: 5.5,
      /* §6.2 спеки/§8.1 контракта: «узлы не должны стоять точно один поверх
       * другого», «пересечение ядровых кругов запрещено». После ограничения
       * размера по плотности совпавшие центры всё равно надо развести: проход
       * `relaxOverlaps` расталкивает пары ближе «радиусы + gap» (детерминированно,
       * со смещением не больше `relaxMaxShift` CSS-px на узел). */
      relaxGap: 1.5,
      relaxIterations: 24,
      relaxMaxShift: 36,
      // radiusNet = clamp(targetD/2 · U, radiusMin, radiusMax), U = 1/fitScale.
      radiusMin: 4,
      radiusMax: 120,
      borderWidth: 1,
      borderWidthSelected: 2,
      hoverBorder: '#E6EDF8',
      dimOpacity: 0.25,
      boxRadius: 5,
      plainBoxRadius: 2,
      // Когда fitScale ещё неизвестен (первый кадр до стабилизации) считаем
      // обзор «нормальным»: размеры уточняются одним батчем после layout.
      assumedFitScale: 0.8,
      // Насколько светлее обод ядра относительно заливки (тонкий светлый rim).
      rimLighten: 0.45,
    },
    glow: {
      // §4.2 спеки: ближний ореол 1,3–1,8 радиуса ядра, дальний 2–3 радиуса.
      near: { ratio: 1.55, alpha: 0.22 },
      far: { ratio: 2.65, alpha: 0.10 },
      // Активный узел (выбран/hover): заметный устойчивый ореол.
      active: { ratio: 2.35, alpha: 0.50 },
      // Гранулярность кэша спрайтов по экранному радиусу, CSS-px.
      bucketPx: 2,
      minScreenRadius: 1.6,
      maxScreenRadius: 48,
      // Вне кадра + запас не считаем и не рисуем (§10.2 «только экранные»).
      margin: 56,
    },
    edge: {
      width: 0.7,
      focusWidth: 1.4,
      dimWidth: 0.5,
      /* §4.3/§12.2 спеки: реальные связи выбранного узла должны быть ВИДНЫ, а не
       * «утонуть» под слоем из 702 ядер. Слой `fx` лежит НАД vis-канвасом,
       * поэтому подсвеченные связи выбранного рисуются ещё раз — в экранных
       * координатах, поверх узлов: тонкая тёмная подложка (контраст на светлом
       * узле) + сигнальная линия оттенка типа. Альфа в полосе §4.3 (0.55–0.9),
       * ширина толще базовой 0.7 px. */
      activeAlpha: 0.9,
      activeWidth: 2,
      activeHalo: 'rgba(8,11,18,.55)',
      activeHaloWidth: 4,
      // Потолок одновременных подсвеченных связей (у хаба их может быть сотни:
      // кадр не должен рисовать тысячи линий).
      maxActive: 240,
      // §3.5 контракта: база 0.34 × opacity 0.38 ≈ 0.13 итоговой альфы
      // (спека §4.3: полоса 0.08–0.20 в плотных сценах — никакого ковра).
      base: 'rgba(148,163,184,.34)',
      derived: 'rgba(148,163,184,.26)',
      focus: 'rgba(203,213,225,.92)',
      dim: 'rgba(148,163,184,.30)',
      baseOpacity: 0.38,
      derivedOpacity: 0.30,
      focusOpacity: 0.85,
      dimOpacity: 0.12,
      /* §10.5 контракта: альфа рёбер — тремя фиксированными значениями по LOD,
       * одним батчем `eds.update` на пересечение порога (гистерезис §4.2 не даёт
       * колебаний). Значения ИЗМЕРЕНЫ на 702/2400 (CMV-B): на обзоре 0.10 —
       * сеть не образует ковра; в рабочем виде 0.13; в детальном (камера внутри
       * плотного кластера, 2400 рёбер в маленьком кадре) 0.07, иначе поперечные
       * линии дают «паутину», которую запрещает §4.3 спеки. */
      alphaByLod: [0.10, 0.13, 0.07],
      dimAlphaByLod: [0.08, 0.12, 0.05],
      highlight: 'rgba(226,232,240,.85)',
      hover: 'rgba(203,213,225,.60)',
      derivedDashes: [3, 4],
      selectionWidth: 1.6,
      hoverWidth: 1.5,
      // ПРЯМЫЕ линии: bezier на 2400 рёбрах — главный пожиратель кадра (§10.1).
      smooth: false,
      // Форма «мягкой» линии, если `smooth` когда-нибудь включат (константа —
      // в конфиг-слое, не в app.js: INV-05).
      smoothOptions: { type: 'continuous', roundness: 0.35 },
      // Единственное смысловое поле направления в payload (реальное отношение).
      arrowRelation: 'revised_by',
    },
    label: {
      // §4.4 спеки: мелкий светлый текст + лёгкий тёмный контур, БЕЗ плашек.
      fontPx: 11,
      offset: 13,
      color: '#E6EDF8',
      selectedColor: '#F8FAFC',
      stroke: 'rgba(8,11,18,.85)',
      // Контур: при кегле 11–12 px lineWidth 3 читался как тяжёлая тёмная полоса
      // (замечание ревью CMV-B) — 2.2 сохраняет контраст без «жирной обводки».
      strokeWidth: 2.2,
      dimAlpha: 0.45,
      maxChars: 30,
      // Пороги LOD по r = scale/fitScale (§4.2 контракта): подписи берут долю
      // бюджета от ОТНОСИТЕЛЬНОГО масштаба, а не от абсолютного vis-значения.
      t1: 0.952,
      t2: 2.016,
    },
    motion: {
      // §7.3 контракта: частотный потолок покоя (батарея и FPS без выгоды).
      idleFps: 24,
      // §7.1 спеки: период 3–5 s, фазы разнесены, амплитуда мала.
      pulseMinMs: 3000,
      pulseMaxMs: 5000,
      pulseBase: 0.82,
      pulseAmp: 0.18,
      pulseBudget: 24,
      // Реактивные состояния (§7.4 контракта).
      hoverMs: 180,
      clickMs: 600,
      searchMs: 900,
      searchBeats: 2,
      // Один оборот светового импульса по ребру.
      impulseMs: 1600,
      maxImpulses: 24,
    },
    /* §6.2 спеки: «узлы не должны визуально стоять точно один поверх другого;
     * между центральными элементами оставить разумный просвет для ореолов и
     * подписей», §12.1: обзор должен читаться как сцена. Силы vis ИЗОТРОПНЫ,
     * поэтому bbox раскладки почти квадратный, а кадр встроенной карты
     * (1252×318 по §2.1 спеки) вчетверо шире, чем выше: без нормализации
     * занято 23 % ширины, а всё ядро сжато в столб посреди пустого кадра.
     * Нормализация тянет ТОЛЬКО свободную ось кадра, один раз на раскладку. */
    layout: {
      /* Потолок растяжения. Не косметика: растянутая раскладка = длинные
       * рёбра, а их GPU-растеризация дорожает (замер CMV-B на 702/2400:
       * cap 3.9 — 40–43 FPS панорамирования, cap 3.0 — 46–48 FPS при
       * fillW 0.70 против 0.23 у изотропной раскладки). §10.2 спеки требует
       * ≥45 FPS, поэтому 3.0 — верхняя граница, а не «насколько хватит». */
      aspectCap: 2.8,
      // Мёртвая зона: ради 5 % разницы раскладку не трогаем (иначе любое
      // изменение размера контейнера дёргало бы узлы).
      aspectSlack: 1.08,
    },
    physics: {
      /* §8.1 контракта: итерации по размеру набора, а не константа 150.
       * Значения springLength/avoidOverlap доведены замером (см. отчёт
       * CMV-B: 702 узла, просвет связанных хабов ≥ 40 px при r = 1). */
      middleMax: 200,
      largeMax: 400,
      iterationsSmall: 150,
      iterationsMiddle: 90,
      iterationsLarge: 60,
      springBase: 70,
      springMin: 60,
      springMax: 220,
      avoidOverlap: 0.5,
      minVelocity: 2.5,
      centralGravity: 0.3,
      damping: 0.09,
      gravitationalConstant: -8000,
      springConstant: 0.04,
      adaptiveTimestep: true,
      // Страховка терминации (§8.2): события могут не прийти.
      watchdogMs: 3000,
    },
    fx: {
      // §6 контракта: `dpr = min(devicePixelRatio, 2)`.
      dprMax: 2,
    },
  };

  // Нейтральный стиль неизвестного типа (не новая категория онтологии, §4.1).
  var NEUTRAL_STYLE = { color: '#64748B', shape: 'dot', size: 10, legend: false };

  function adapter() {
    var A = root && root.CognitiveMap;
    // node-песочницы грузят app.js с `global.window`: адаптер ищем и там,
    // чтобы тесты видели те же стили, что браузер.
    if (!A && root && root.window && root.window.CognitiveMap) {
      A = root.window.CognitiveMap;
    }
    return A || null;
  }

  /* styleFor(kind) — стиль типа из адаптера (для легенды/карточек). Сама сцена
   * берёт форму/цвет из `spec` ниже: §3.3 контракта задаёт их для vis-примитива,
   * а адаптер описывает ещё и «box/rounded» для легенды. */
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

  function clamp(value, lo, hi) {
    if (value < lo) return lo;
    if (value > hi) return hi;
    return value;
  }

  /* ── визуальная спецификация типа ─────────────────────────────────────── */
  function specFor(kind) {
    var key = (typeof kind === 'string' && CONFIG.spec[kind]) ? kind : 'other';
    var spec = CONFIG.spec[key];
    if (spec) return spec;
    // Незнакомый тип — нейтральная световая сфера без новой категории (§4.1).
    return CONFIG.spec.other;
  }

  function shapeKeyOf(kind) { return specFor(kind).key; }
  function colorOf(kind) { return specFor(kind).color; }
  function decorOf(kind) { return specFor(kind).decor; }
  function baseDiameterOf(kind) {
    var d = CONFIG.baseDiameter[kind];
    // Неизвестный тип — диаметр нейтральной сферы, а не выдуманная категория.
    return (typeof d === 'number') ? d : CONFIG.baseDiameter.other;
  }

  /* targetDiameter(kind, degree) — целевой диаметр в CSS-px при r = 1.
   * Высокосвязный узел не превращается в гигантский шар (потолок degreeCap). */
  function targetDiameter(kind, degree) {
    var base = baseDiameterOf(kind);
    var deg = (typeof degree === 'number' && isFinite(degree) && degree > 0)
      ? degree : 0;
    if (!deg) return base;
    var growth = CONFIG.node.degreeK * (Math.log(1 + deg) / Math.LN2);
    return base + Math.min(CONFIG.node.degreeCap, growth);
  }

  /* radiusNet(kind, degree, fitScale) — радиус в СЕТЕВЫХ единицах (то, что
   * уходит в `row.size`). `U = 1/fitScale` переводит CSS-px в сетевые единицы,
   * поэтому на экране диаметр равен `targetDiameter` (при r = 1). Размер НЕ
   * зависит от позиций ⇒ петли «размер → bbox → масштаб» нет (§10.2). */
  function radiusScaleFor(fitScale) {
    var s = finite(fitScale);
    if (s === null || s <= 0) s = CONFIG.node.assumedFitScale;
    return 1 / s;
  }

  function nodeRadius(kind, degree, fitScale, opts) {
    var U = radiusScaleFor(fitScale);
    var target = targetDiameter(kind, degree);
    // Верхние пределы ЭКРАННОГО диаметра (при r = 1): глобальный потолок спеки
    // §4.1 и локальная плотность кадра (§5.1). Оба применяются ДО перевода в
    // сетевые единицы, поэтому зум увеличивает узлы пропорционально кадру.
    if (opts) {
      var cap = finite(opts.screenDiameter);
      if (cap !== null && cap > 0 && target > cap) target = cap;
      var maxD = finite(opts.maxScreenDiameter);
      if (maxD !== null && maxD > 0 && target > maxD) target = maxD;
    }
    return clamp((target / 2) * U, CONFIG.node.radiusMin, CONFIG.node.radiusMax);
  }

  function screenDiameter(kind, degree, scale) {
    var r = nodeRadius(kind, degree, null);
    var s = finite(scale);
    if (s === null || s <= 0) s = 1;
    return r * 2 * s;
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

  /* relativeScale(scale, fitScale) — `r` контракта §4.2 для слоя подписей:
   * бюджет подписей считается от ОТНОСИТЕЛЬНОГО масштаба, а не от абсолютного
   * vis-значения (иначе на большом графе LOD «залипал» бы в overview). */
  function relativeScale(scale, fitScale) {
    var s = finite(scale);
    var f = finite(fitScale);
    if (s === null || s <= 0) return 1;
    if (f === null || f <= 0) return 1;
    return s / f;
  }

  /* aspectStretch(bbox, width, height, cfg) → {kx, ky, ratio}
   *
   * Зачем: силы vis изотропны, поэтому bbox раскладки почти квадратный, а кадр
   * встроенной карты (1252×318) вчетверо шире, чем выше. `fitScaleRef` по §4.1
   * контракта берёт min(W-, H-ограничения) — на коротком кадре он упирается в
   * высоту, и сцена занимает 23 % ширины; при этом 702 узла с диаметрами по
   * спецификации физически не помещаются в узкий столб и стоят стеной (§6.2,
   * §12.1 спеки). Нормализация растягивает раскладку по СВОБОДНОЙ оси кадра
   * (второй axis не трогается), один раз на раскладку, с потолком `aspectCap`.
   *
   * Возвращает множители координат `x' = cx + (x-cx)·kx`, `y' = cy + (y-cy)·ky`.
   * Мёртвая зона `aspectSlack` не даёт дёргать раскладку на 3–5 % разницы. */
  function aspectStretch(bbox, width, height, cfg) {
    var c = (cfg && cfg.layout) || CONFIG.layout;
    var none = { kx: 1, ky: 1, ratio: 1 };
    if (!bbox) return none;
    var w = finite(width);
    var h = finite(height);
    if (w === null || h === null || w <= 2 || h <= 2) return none;
    if (!(bbox.spanX > 0) || !(bbox.spanY > 0)) return none;
    var ratio = (w / h) / (bbox.spanX / bbox.spanY);
    if (!isFinite(ratio) || ratio <= 0) return none;
    var cap = finite(c.aspectCap);
    var slack = finite(c.aspectSlack);
    if (cap === null || cap <= 1) cap = 4;
    if (slack === null || slack <= 1) slack = 1.08;
    if (ratio >= slack) {
      return { kx: Math.min(ratio, cap), ky: 1, ratio: ratio };
    }
    if (ratio <= 1 / slack) {
      return { kx: 1, ky: Math.min(1 / ratio, cap), ratio: ratio };
    }
    // Мёртвая зона: соотношение почти совпало — ничего не трогаем, но `ratio`
    // возвращаем для диагностики (по нему видно, что раскладка уже вписана).
    return { kx: 1, ky: 1, ratio: ratio };
  }

  /* densityCaps(nodes, positions, fitScale, opts) → {id: экранный диаметр}
   *
   * Верхний предел диаметра по ЛОКАЛЬНОЙ плотности (§5.1 спеки: содержимое
   * зависит от масштаба и плотности на экране; §4.1: фигура не закрывает
   * соседей):
   *   cap_i = clamp(densityFactor · d_rank(i), minScreenDiameter, maxScreenDiameter)
   * где `d_rank(i)` — расстояние при r = 1 до `densityRank`-го ближайшего
   * соседа. Позиции только ЧИТАЮТСЯ: размер по-прежнему не влияет на bbox и
   * `fitScaleRef` (петли §4.1 контракта нет). O(n) по сетке ячеек размера
   * `maxScreenDiameter`, поэтому вызов дешёвый (один батч на смену масштаба). */
  function densityCaps(nodes, positions, fitScale, opts) {
    var o = opts || {};
    var cfg = (o.cfg && o.cfg.node) || CONFIG.node;
    var list = nodes || [];
    var pos = positions || {};
    var out = Object.create(null);
    var scale = 1 / radiusScaleFor(fitScale);  // U = net/CSS-px → экранный масштаб
    if (!(scale > 0)) scale = CONFIG.node.assumedFitScale;
    var rank = Math.round(finite(cfg.densityRank));
    if (!(rank > 0)) rank = 3;
    var maxD = finite(cfg.maxScreenDiameter);
    if (!(maxD > 0)) maxD = 24;
    var minD = finite(cfg.minScreenDiameter);
    if (!(minD > 0)) minD = 5.5;
    var factor = finite(cfg.densityFactor);
    if (!(factor > 0)) factor = 0.9;
    var cell = Math.max(8, maxD);
    var grid = Object.create(null);
    var pts = [];
    var i;
    var j;
    for (i = 0; i < list.length; i += 1) {
      var node = list[i];
      if (!node || node.id === undefined || node.id === null) continue;
      var p = pos[node.id];
      if (!p) continue;
      var px = finite(p.x);
      var py = finite(p.y);
      if (px === null || py === null) continue;
      var sx = px * scale;
      var sy = py * scale;
      var gx = Math.floor(sx / cell);
      var gy = Math.floor(sy / cell);
      var key = gx + ':' + gy;
      var bucket = grid[key];
      if (!bucket) { bucket = grid[key] = []; }
      bucket.push(pts.length);
      pts.push({ id: String(node.id), x: sx, y: sy, gx: gx, gy: gy });
    }
    for (i = 0; i < pts.length; i += 1) {
      var pt = pts[i];
      var dists = [];
      var ring = 0;
      var reach = cell;
      while (ring < 64) {
        for (var cx = pt.gx - ring; cx <= pt.gx + ring; cx += 1) {
          for (var cy = pt.gy - ring; cy <= pt.gy + ring; cy += 1) {
            // Внутренние ячейки уже собраны на прошлых кольцах.
            var edge = (cx === pt.gx - ring || cx === pt.gx + ring
              || cy === pt.gy - ring || cy === pt.gy + ring);
            if (ring > 0 && !edge) continue;
            var cells = grid[cx + ':' + cy];
            if (!cells) continue;
            for (j = 0; j < cells.length; j += 1) {
              var other = pts[cells[j]];
              if (other === pt) continue;
              var dx = other.x - pt.x;
              var dy = other.y - pt.y;
              dists.push(Math.sqrt(dx * dx + dy * dy));
            }
          }
        }
        dists.sort(function (a, b) { return a - b; });
        reach = (ring + 1) * cell;
        // Все неисследованные точки не ближе `ring·cell`; как только rank-й
        // сосед ближе исследованной области — поиск завершён.
        if (dists.length >= rank && dists[rank - 1] <= reach) break;
        ring += 1;
      }
      var d = (dists.length >= rank) ? dists[rank - 1] : reach;
      out[pt.id] = clamp(factor * d, minD, maxD);
    }
    return out;
  }

  /* relaxOverlaps(nodes, positions, fitScale, opts) → {id: {x, y}} (сетевые)
   *
   * §6.2/§8.1 спеки и контракта: «узлы не должны визуально стоять точно один
   * поверх другого», «пересечение ядровых кругов запрещено». Сила vis при
   * 702 узлах оставляет десятки узлов почти в одной точке (замер CMV-B: 94
   * пары ближе 0.5 px). Ограничение размера по плотности уменьшает круги, но
   * не разводит совпавшие центры, поэтому здесь — детерминированный проход
   * разведения: пары ближе `радиусы + gap` расходятся по соединяющей линии
   * (для точного совпадения направление берётся из хеша id). Смещение каждой
   * точки ограничено `relaxMaxShift` CSS-px, итераций — `relaxIterations`,
   * Math.random не используется (кадр и прогон воспроизводимы).
   *
   * Позиции только ЧИТАЮТСЯ (вход), результат — новые координаты; решение
   * применять их остаётся за сценой. */
  function relaxOverlaps(nodes, positions, fitScale, opts) {
    var o = opts || {};
    var cfg = (o.cfg && o.cfg.node) || CONFIG.node;
    var list = nodes || [];
    var pos = positions || {};
    var caps = o.caps || null;
    var scale = 1 / radiusScaleFor(fitScale);     // CSS-px на сетевую единицу
    if (!(scale > 0)) scale = CONFIG.node.assumedFitScale;
    var gap = finite(cfg.relaxGap);
    if (gap === null || gap < 0) gap = 1.5;
    var iters = Math.round(finite(cfg.relaxIterations));
    if (!(iters > 0)) iters = 6;
    var maxShift = finite(cfg.relaxMaxShift);
    if (!(maxShift > 0)) maxShift = 10;
    var pts = [];
    var i;
    var j;
    for (i = 0; i < list.length; i += 1) {
      var node = list[i];
      if (!node || node.id === undefined || node.id === null) continue;
      var p = pos[node.id];
      if (!p) continue;
      var px = finite(p.x);
      var py = finite(p.y);
      if (px === null || py === null) continue;
      var capD = caps ? finite(caps[String(node.id)]) : null;
      var radius = nodeRadius(node.kind,
        (typeof node.degree === 'number') ? node.degree : 0, fitScale,
        { screenDiameter: capD,
          maxScreenDiameter: cfg.maxScreenDiameter });
      pts.push({
        id: String(node.id),
        x: px * scale, y: py * scale,        // экранные CSS-px при r = 1
        r: radius * scale,
        mx: 0, my: 0,
      });
    }
    if (pts.length < 2) return Object.create(null);
    var maxR = 0;
    for (i = 0; i < pts.length; i += 1) {
      if (pts[i].r > maxR) maxR = pts[i].r;
    }
    var cell = Math.max(4, 2 * maxR + gap);
    for (var it = 0; it < iters; it += 1) {
      var grid = Object.create(null);
      for (i = 0; i < pts.length; i += 1) {
        var a = pts[i];
        a.gx = Math.floor(a.x / cell);
        a.gy = Math.floor(a.y / cell);
        var key = a.gx + ':' + a.gy;
        (grid[key] || (grid[key] = [])).push(i);
      }
      var moved = 0;
      for (i = 0; i < pts.length; i += 1) {
        var pa = pts[i];
        for (var gx = pa.gx - 1; gx <= pa.gx + 1; gx += 1) {
          for (var gy = pa.gy - 1; gy <= pa.gy + 1; gy += 1) {
            var bucket = grid[gx + ':' + gy];
            if (!bucket) continue;
            for (j = 0; j < bucket.length; j += 1) {
              var bi = bucket[j];
              if (bi <= i) continue;         // каждая пара — один раз
              var pb = pts[bi];
              var dx = pb.x - pa.x;
              var dy = pb.y - pa.y;
              var need = pa.r + pb.r + gap;
              var dist = Math.sqrt(dx * dx + dy * dy);
              if (dist >= need) continue;
              var ux;
              var uy;
              if (dist < 1e-4) {
                // Точно совпали: направление из хеша пары (детерминированно).
                var angle = (hash31(pa.id + '|' + pb.id) % 6283) / 1000;
                ux = Math.cos(angle);
                uy = Math.sin(angle);
                dist = 0;
              } else {
                ux = dx / dist;
                uy = dy / dist;
              }
              var push = (need - dist) / 2;
              pa.x -= ux * push;
              pa.y -= uy * push;
              pb.x += ux * push;
              pb.y += uy * push;
              moved += 1;
            }
          }
        }
      }
      if (!moved) break;
    }
    var out = Object.create(null);
    for (i = 0; i < pts.length; i += 1) {
      var pt = pts[i];
      var x0 = pos[pt.id] ? pos[pt.id].x * scale : pt.x;
      var y0 = pos[pt.id] ? pos[pt.id].y * scale : pt.y;
      var dx2 = pt.x - x0;
      var dy2 = pt.y - y0;
      var shift = Math.sqrt(dx2 * dx2 + dy2 * dy2);
      if (shift > maxShift) {
        var k = maxShift / shift;
        pt.x = x0 + dx2 * k;
        pt.y = y0 + dy2 * k;
        shift = maxShift;
      }
      if (shift < 0.05) continue;
      out[pt.id] = { x: pt.x / scale, y: pt.y / scale };
    }
    return out;
  }

  /* ── модель → строка DataSet ────────────────────────────────────────────
   * nodeRow(node, opts):
   *   opts.pos        — {x,y} текущая позиция (не меняет модель);
   *   opts.fitScale   — `fitScaleRef` сцены (перевод CSS-px → сетевые единицы);
   *   opts.dim        — притушить (есть выбор, узел не в подсветке).
   * Возвращает ТОЛЬКО визуальные поля. */
  function nodeRow(node, opts) {
    var o = opts || {};
    var cfg = o.cfg || CONFIG;
    var kind = node && node.kind;
    var spec = specFor(kind);
    var degree = (node && typeof node.degree === 'number') ? node.degree : 0;
    var color = spec.color || NEUTRAL_STYLE.color;
    var row = {
      id: node ? node.id : undefined,
      label: '',
      shape: spec.vis,
      size: nodeRadius(kind, degree, o.fitScale, {
        screenDiameter: o.screenDiameter,
        maxScreenDiameter: o.maxScreenDiameter,
      }),
      borderWidth: cfg.node.borderWidth,
      borderWidthSelected: cfg.node.borderWidthSelected,
      color: {
        background: color,
        border: lighten(color, cfg.node.rimLighten),
        highlight: { background: color, border: cfg.node.hoverBorder },
        hover: { background: color, border: cfg.node.hoverBorder },
      },
      font: { size: 0 },
      opacity: o.dim ? cfg.node.dimOpacity : 1,
    };
    // `entity` перестал быть прямоугольником (§4.1 спеки): сфера — это `dot`
    // с декором-ядром в слое `fx`. Ветка `box` удалена: форма узла берётся
    // ТОЛЬКО из `spec` (§3.3 контракта), а не из «похожего vis-примитива»
    // адаптера — иначе крупные серые прямоугольники возвращались бы.
    var pos = o.pos;
    if (pos && finite(pos.x) !== null && finite(pos.y) !== null) {
      row.x = pos.x;
      row.y = pos.y;
    }
    return row;
  }

  /* edgeRow(edge, opts):
   *   opts.focused — ребро инцидентно выбранному/наведённому узлу;
   *   opts.dimmed  — есть выбор, ребро не инцидентно (сеть ослаблена).
   * Производное ребро (`derived`) — пунктир: это РЕАЛЬНАЯ ссылка из данных,
   * а не догадка. Стрелка только для смыслового направления payload. */
  function edgeState(opts) {
    var o = opts || {};
    var edge = o.cfg && o.cfg.edge ? o.cfg.edge : CONFIG.edge;
    var lod = (typeof o.lod === 'number') ? clamp(Math.round(o.lod), 0, 2) : 1;
    var baseAlpha = (edge.alphaByLod && edge.alphaByLod[lod] !== undefined)
      ? edge.alphaByLod[lod] : 0.13;
    var dimAlpha = (edge.dimAlphaByLod && edge.dimAlphaByLod[lod] !== undefined)
      ? edge.dimAlphaByLod[lod] : 0.12;
    // `row.color.opacity` — множитель для базового `rgba(148,163,184,.34)`:
    // целевая ИТОГОВАЯ альфа задана таблицей по LOD (§10.5 контракта).
    var baseOpacity = clamp(baseAlpha / 0.34, 0, 1);
    var dimOpacity = clamp(dimAlpha / 0.34, 0, 1);
    if (o.focused) {
      // Цвет подсвеченной связи — оттенок типа активного узла (сигнальная
      // линия), а не почти белый: длинное белое ребро к соседу за кадром
      // читается как «царапина» (§4.3 спеки — мягкие сигнальные линии).
      return { color: o.focusColor || edge.focus,
        opacity: edge.focusOpacity, width: edge.focusWidth };
    }
    if (o.dimmed) {
      return { color: edge.dim, opacity: dimOpacity, width: edge.dimWidth };
    }
    return {
      color: (o.edge && o.edge.derived === true) ? edge.derived : edge.base,
      opacity: (o.edge && o.edge.derived === true)
        ? baseOpacity * 0.8 : baseOpacity,
      width: edge.width,
    };
  }

  function edgeRow(edge, opts) {
    var o = opts || {};
    var cfg = (o.cfg && o.cfg.edge) || CONFIG.edge;
    var state = edgeState({
      focused: o.focused, dimmed: o.dimmed, edge: edge, cfg: o.cfg,
      lod: o.lod, focusColor: o.focusColor,
    });
    return {
      id: edge.id,
      from: edge.from,
      to: edge.to,
      label: '',
      color: {
        color: state.color,
        highlight: cfg.highlight,
        hover: cfg.hover,
        opacity: state.opacity,
      },
      width: state.width,
      dashes: edge.derived === true ? cfg.derivedDashes.slice() : false,
      arrows: { to: { enabled: edge.relation === cfg.arrowRelation } },
      smooth: cfg.smooth === true
        ? { type: cfg.smoothOptions.type, roundness: cfg.smoothOptions.roundness }
        : false,
      selectionWidth: cfg.selectionWidth,
      hoverWidth: cfg.hoverWidth,
    };
  }

  /* edgeDeltaRow(edge, opts) — ЧАСТИЧНАЯ строка для смены выбора (§10.2(4)):
   * DataSet получает только id + цвет/ширину, геометрия/форма не пересылаются. */
  function edgeDeltaRow(edge, opts) {
    var o = opts || {};
    var state = edgeState({ focused: o.focused,
      dimmed: o.dimmed, edge: edge, cfg: o.cfg, lod: o.lod,
      focusColor: o.focusColor });
    return {
      id: edge.id,
      // Цвет отправляется только для подсвеченной связи (оттенок типа
      // активного узла); остальным достаточно альфы — частичная строка §10.2(4).
      color: o.focused ? { color: state.color, opacity: state.opacity }
        : { opacity: state.opacity },
      width: state.width,
    };
  }

  /* Батч-преобразование: единственная точка для сцены. `opts` — состояние
   * отображения (позиции/подсветка/выбор/масштаб), модель только читается. */
  function nodeRows(nodes, opts) {
    var o = opts || {};
    var out = [];
    var list = nodes || [];
    var positions = o.positions || {};
    var highlighted = o.highlighted || null;
    var selectedId = (o.selectedId === undefined) ? null : o.selectedId;
    // Пер-узел верхний предел диаметра по локальной плотности (densityCaps).
    var caps = o.screenCaps || null;
    for (var i = 0; i < list.length; i += 1) {
      var node = list[i];
      if (!node || node.id === undefined || node.id === null) continue;
      out.push(nodeRow(node, {
        pos: positions[node.id] || null,
        fitScale: o.fitScale,
        dim: !!(selectedId != null && !(highlighted && highlighted[node.id])),
        screenDiameter: caps ? caps[String(node.id)] : null,
        maxScreenDiameter: o.maxScreenDiameter,
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
    var hasSelection = o.selectedId !== undefined && o.selectedId !== null;
    for (var i = 0; i < list.length; i += 1) {
      var edge = list[i];
      if (!edge || edge.id === undefined || edge.id === null) continue;
      var focused = !!(focus && focus[edge.id]);
      out.push(edgeRow(edge, {
        focused: focused,
        dimmed: hasSelection && !focused,
        lod: o.lod,
        cfg: o.cfg,
      }));
    }
    return out;
  }

  /* ── свечение: чистые спецификации (кэш спрайтов строится по ним) ─────── */
  function glowSpec(kind, layer) {
    var cfg = CONFIG.glow;
    var spec = cfg[layer] || cfg.near;
    return {
      layer: layer,
      ratio: spec.ratio,
      alpha: spec.alpha,
      color: colorOf(kind),
    };
  }

  /* spriteSpec(kind, layer, screenRadius, dpr) → {key,size,ratio,stops}
   * Радиус кэша квантуется по `bucketPx` (гранулярность 2 px): ограниченное
   * число канвасов вместо «градиент на каждый узел каждый кадр» (§6 контракта).
   * Центр спрайта прозрачен — ядро vis под ним видно. */
  function spriteSpec(kind, layer, screenRadius, dpr) {
    var cfg = CONFIG.glow;
    var glow = glowSpec(kind, layer);
    var r = finite(screenRadius);
    if (r === null || r <= 0) r = cfg.minScreenRadius;
    r = clamp(Math.round(r / cfg.bucketPx) * cfg.bucketPx,
      cfg.minScreenRadius, cfg.maxScreenRadius);
    var ratio = Math.max(1.05, glow.ratio);
    var size = Math.max(2, Math.ceil(r * ratio * 2));
    var core = 1 / ratio;
    var stops = [
      { at: 0, alpha: 0 },
      { at: clamp(core * 0.85, 0.02, 0.9), alpha: 0 },
      { at: clamp(core + (1 - core) * 0.38, 0.1, 0.97), alpha: glow.alpha },
      { at: 1, alpha: 0 },
    ];
    return {
      key: layer + '|' + kitKey(kind) + '|' + r + '|' + (dpr || 1),
      size: size,
      ratio: ratio,
      color: glow.color,
      stops: stops,
      alpha: glow.alpha,
      bucket: r,
    };
  }

  function kitKey(kind) { return specFor(kind).key; }

  /* pulsePlan(nodes, opts) — детерминированный набор «живых» узлов (§7.1):
   * центры/топ по degree + выбранный и его соседи, |P| = min(24, ⌈n/30⌉).
   * Период 3000–5000 ms и фаза берутся из хеша id ⇒ узлы не дышат синхронно,
   * Math.random не используется (кадр воспроизводим). */
  function hash31(str) {
    var h = 2166136261;
    var text = String(str);
    for (var i = 0; i < text.length; i += 1) {
      h ^= text.charCodeAt(i);
      h = (h * 16777619) >>> 0;
    }
    return h >>> 0;
  }

  function pulsePlan(nodes, opts) {
    var o = opts || {};
    var cfg = CONFIG.motion;
    var list = nodes || [];
    var budget = Math.min(cfg.pulseBudget,
      Math.max(1, Math.ceil(list.length / 30)));
    var forced = [];
    if (o.selectedId != null) forced.push(String(o.selectedId));
    var neighbors = o.neighborIds || [];
    for (var f = 0; f < neighbors.length && forced.length < budget; f += 1) {
      forced.push(String(neighbors[f]));
    }
    var picked = [];
    var seen = {};
    function push(id, kind, degree) {
      if (id == null || seen[id]) return;
      seen[id] = true;
      var h = hash31(id);
      var span = cfg.pulseMaxMs - cfg.pulseMinMs;
      picked.push({
        id: id,
        kind: kind,
        degree: degree,
        period: cfg.pulseMinMs + (span ? (h % (span + 1)) : 0),
        phase: h % 5000,
        amp: cfg.pulseAmp,
      });
    }
    var i;
    for (i = 0; i < forced.length; i += 1) push(forced[i], o.kindOf
      ? o.kindOf(forced[i]) : null, 0);
    // Топ по degree — «заметные реальные узлы», без выдуманных сущностей.
    var ranked = list.slice(0);
    ranked.sort(function (a, b) {
      var da = (a && typeof a.degree === 'number') ? a.degree : 0;
      var db = (b && typeof b.degree === 'number') ? b.degree : 0;
      if (da !== db) return db - da;
      return String(a && a.id) < String(b && b.id) ? -1 : 1;
    });
    for (i = 0; i < ranked.length && picked.length < budget; i += 1) {
      var node = ranked[i];
      if (!node) continue;
      push(String(node.id), node.kind,
        (typeof node.degree === 'number') ? node.degree : 0);
    }
    return picked;
  }

  /* pulseFactor(entry, nowMs) — множитель яркости ДАЛЬНЕГО ореола.
   * Геометрия ядра не меняется (§7.1): только альфа в полосе 0.82…1.0. */
  function pulseFactor(entry, nowMs) {
    var cfg = CONFIG.motion;
    if (!entry || !(entry.period > 0)) return 1;
    var t = finite(nowMs) || 0;
    var phase = (typeof entry.phase === 'number') ? entry.phase : 0;
    var amp = (typeof entry.amp === 'number') ? entry.amp : cfg.pulseAmp;
    var wave = Math.sin((2 * Math.PI * (t + phase)) / entry.period);
    return cfg.pulseBase + amp * (0.5 + 0.5 * wave);
  }

  /* ── вспомогательное: цвет ────────────────────────────────────────────── */
  function hexToRgb(hex) {
    var text = String(hex || '').replace('#', '');
    if (text.length === 3) {
      text = text[0] + text[0] + text[1] + text[1] + text[2] + text[2];
    }
    var num = parseInt(text, 16);
    if (!isFinite(num)) return { r: 148, g: 163, b: 184 };
    return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
  }

  function rgba(hex, alpha) {
    var c = hexToRgb(hex);
    var a = (typeof alpha === 'number' && isFinite(alpha)) ? alpha : 1;
    return 'rgba(' + c.r + ',' + c.g + ',' + c.b + ',' + a + ')';
  }

  // Светлее — для тонкого обода ядра (светлый rim факта/сферы).
  function lighten(hex, amount) {
    var c = hexToRgb(hex);
    var k = (typeof amount === 'number') ? amount : 0.4;
    function mix(v) { return Math.round(v + (255 - v) * k); }
    return 'rgb(' + mix(c.r) + ',' + mix(c.g) + ',' + mix(c.b) + ')';
  }

  /* ── слой `fx`: свечение, декор, импульсы, кольцо выбора ────────────────
   * Один объект на сцену. Спрайты кэшируются по (слой, kind, бакет, dpr).
   * В кадре НЕ создаются градиенты и канвасы: `paint` только композитит
   * готовые спрайты и рисует маленькие фигуры активного узла. */
  function createFx(opts) {
    var o = opts || {};
    var cfg = o.cfg || CONFIG;
    var makeCanvas = o.makeCanvas || defaultMakeCanvas;
    var dpr = 1;
    var sprites = Object.create(null);
    var spriteCount = 0;
    var gradients = 0;
    var paints = 0;
    var draws = 0;
    var edgeDraws = 0;
    var lastActiveEdges = 0;
    var pool = [];

    function defaultMakeCanvas(w, h) {
      if (typeof document === 'undefined'
          || typeof document.createElement !== 'function') return null;
      var cv = document.createElement('canvas');
      cv.width = w;
      cv.height = h;
      return cv;
    }

    function slot(index) {
      var s = pool[index];
      if (!s) {
        s = { id: '', kind: '', x: 0, y: 0, r: 0, sx: 0, sy: 0 };
        pool[index] = s;
      }
      return s;
    }

    function sprite(kind, layer, screenRadius) {
      var spec = spriteSpec(kind, layer, screenRadius, dpr);
      var cached = sprites[spec.key];
      if (cached) return cached;
      var px = Math.max(2, Math.round(spec.size * dpr));
      var canvas = makeCanvas(px, px);
      if (!canvas || typeof canvas.getContext !== 'function') return null;
      var sctx = canvas.getContext('2d');
      if (!sctx || typeof sctx.createRadialGradient !== 'function') return null;
      var half = px / 2;
      // Градиент строится ОДИН раз на спрайт, не на кадр (§10.2(5)).
      var grad = sctx.createRadialGradient(half, half, 0, half, half, half);
      gradients += 1;
      for (var i = 0; i < spec.stops.length; i += 1) {
        grad.addColorStop(spec.stops[i].at, rgba(spec.color, spec.stops[i].alpha));
      }
      sctx.clearRect(0, 0, px, px);
      sctx.fillStyle = grad;
      sctx.fillRect(0, 0, px, px);
      var spriteRec = {
        key: spec.key, canvas: canvas, cssSize: spec.size,
        ratio: spec.ratio, color: spec.color,
      };
      sprites[spec.key] = spriteRec;
      spriteCount += 1;
      return spriteRec;
    }

    function composite(ctx, kind, layer, screenRadius, alpha) {
      var rec = sprite(kind, layer, screenRadius);
      if (!rec || !(alpha > 0.002)) return null;
      ctx.globalAlpha = alpha > 1 ? 1 : alpha;
      return rec;
    }

    function drawGlow(ctx, kind, layer, sx, sy, screenRadius, alpha) {
      var rec = composite(ctx, kind, layer, screenRadius, alpha);
      if (!rec) return;
      var d = rec.cssSize;
      ctx.drawImage(rec.canvas, sx - d / 2, sy - d / 2, d, d);
      draws += 1;
    }

    /* Декор активного/видимого узла: внутреннее кольцо убеждения, грань
     * парадигмы, угловой блик изменения, светлое ядро сущности (§4.1 спеки). */
    function drawDecor(ctx, kind, sx, sy, r, alpha) {
      var decor = decorOf(kind);
      if (!decor || !(r > 1.2)) return;
      var color = colorOf(kind);
      ctx.globalAlpha = alpha;
      if (decor === 'ring') {
        ctx.beginPath();
        ctx.lineWidth = Math.max(0.7, r * 0.16);
        ctx.strokeStyle = rgba(lighten(color, 0.55), 0.85);
        ctx.arc(sx, sy, r * 0.55, 0, Math.PI * 2);
        ctx.stroke();
      } else if (decor === 'facet') {
        ctx.beginPath();
        ctx.lineWidth = Math.max(0.6, r * 0.12);
        ctx.strokeStyle = rgba(lighten(color, 0.5), 0.7);
        var inner = r * 0.52;
        ctx.moveTo(sx, sy - inner);
        ctx.lineTo(sx + inner * 0.86, sy + inner * 0.5);
        ctx.lineTo(sx - inner * 0.86, sy + inner * 0.5);
        ctx.closePath();
        ctx.stroke();
      } else if (decor === 'glint') {
        ctx.beginPath();
        ctx.lineWidth = Math.max(0.7, r * 0.18);
        ctx.strokeStyle = rgba('#FFF3D6', 0.85);
        ctx.arc(sx, sy, r * 0.68, -Math.PI * 0.75, -Math.PI * 0.25);
        ctx.stroke();
      } else if (decor === 'core') {
        ctx.beginPath();
        ctx.fillStyle = rgba(lighten(color, 0.75), 0.85);
        ctx.arc(sx, sy, Math.max(0.8, r * 0.34), 0, Math.PI * 2);
        ctx.fill();
      }
    }

    /* Кольцо активного узла + мягкий световой импульс (select/hover).
     * Радиус и толщина имеют НИЖНЮЮ границу: на обзоре узел 4–6 px, и кольцо
     * «по формуле» было бы толщиной в волос — выделение должно читаться. */
    function drawRing(ctx, sx, sy, r, ratio, color, alpha, now) {
      ctx.globalAlpha = alpha;
      ctx.beginPath();
      ctx.lineWidth = Math.max(1.6, r * 0.22);
      ctx.strokeStyle = rgba(color, 0.95);
      ctx.arc(sx, sy, Math.max(6.5, r * ratio + 1.5), 0, Math.PI * 2);
      ctx.stroke();
      // Мягкий «вдох» кольца: геометрия узла стабильна, дышит только свет.
      if (now > 0) {
        var wave = 0.5 + 0.5 * Math.sin(now / 420);
        ctx.globalAlpha = alpha * (0.35 + 0.25 * wave);
        ctx.beginPath();
        ctx.lineWidth = Math.max(1, r * 0.12);
        ctx.strokeStyle = rgba(color, 0.55);
        ctx.arc(sx, sy, Math.max(8.5, r * (ratio + 0.45) + 2), 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    /* Импульсы по РЕАЛЬНЫМ рёбрам активного узла (§4.3 спеки): координаты
     * концов берутся из кэша позиций, никаких «декоративных» линий. */
    function drawImpulses(ctx, frame, activeId, active, incident) {
      var max = cfg.motion.maxImpulses;
      var now = frame.now || 0;
      var scale = frame.camera.scale;
      var list = incident;
      var shown = 0;
      ctx.fillStyle = rgba('#E8F4FF', 0.9);
      for (var i = 0; i < list.length && shown < max; i += 1) {
        var edge = list[i];
        var otherId = (String(edge.from) === String(activeId))
          ? String(edge.to) : String(edge.from);
        var p = frame.positions[otherId];
        if (!p) continue;
        var ox = (p.x - frame.camera.x) * scale + frame.width / 2;
        var oy = (p.y - frame.camera.y) * scale + frame.height / 2;
        var phase = ((now / cfg.motion.impulseMs) + (i * 0.11)) % 1;
        var t = 0.18 + 0.64 * phase;
        var px = active.sx + (ox - active.sx) * t;
        var py = active.sy + (oy - active.sy) * t;
        var fade = Math.sin(Math.PI * t);
        ctx.globalAlpha = 0.25 + 0.6 * fade;
        ctx.beginPath();
        ctx.arc(px, py, Math.max(1.2, 1.6 + active.r * 0.08), 0, Math.PI * 2);
        ctx.fill();
        shown += 1;
      }
      return shown;
    }

    /* Подсвеченные связи активного узла — ПОВЕРХ слоя узлов (§4.3 спеки
     * «его реальные непосредственные связи подсветить до opacity 0.55–0.9,
     * соседние узлы выделить, прочую сеть ослабить»; §12.2 «ближайшие связи и
     * узлы подчёркнуты»). vis рисует рёбра ПОД ядрами узлов: на 702 узлах
     * линия 1.4 px исчезает под соседними кругами, поэтому те же РЕАЛЬНЫЕ
     * рёбра повторяются в слое `fx` (он выше vis-канваса): тонкая тёмная
     * подложка для контраста + сигнальная линия оттенка активного узла.
     * Координаты — из кэша позиций; выдуманных линий нет. */
    function drawActiveEdges(ctx, frame, activeId, active) {
      var eCfg = cfg.edge || CONFIG.edge;
      var list = frame.incident || [];
      var scale = (frame.camera && frame.camera.scale > 0)
        ? frame.camera.scale : 1;
      var camX = frame.camera ? frame.camera.x : 0;
      var camY = frame.camera ? frame.camera.y : 0;
      var W = frame.width || 0;
      var H = frame.height || 0;
      var margin = 40;
      var max = eCfg.maxActive || 240;
      var color = rgba(colorOf(active.kind),
        (typeof eCfg.activeAlpha === 'number') ? eCfg.activeAlpha : 0.9);
      var shown = 0;
      ctx.lineCap = 'round';
      ctx.globalAlpha = 1;
      for (var i = 0; i < list.length && shown < max; i += 1) {
        var edge = list[i];
        var otherId = (String(edge.from) === String(activeId))
          ? String(edge.to) : String(edge.from);
        var p = frame.positions[otherId];
        if (!p) continue;
        var ox = (p.x - camX) * scale + W / 2;
        var oy = (p.y - camY) * scale + H / 2;
        // Связь, оба конца которой вне кадра, не рисуется (§5.4 спеки).
        if (active.sx < -margin && ox < -margin) continue;
        if (active.sx > W + margin && ox > W + margin) continue;
        if (active.sy < -margin && oy < -margin) continue;
        if (active.sy > H + margin && oy > H + margin) continue;
        var dx = ox - active.sx;
        var dy = oy - active.sy;
        var len = Math.sqrt(dx * dx + dy * dy) || 1;
        // От активного узла линия начинается за его ядром: ядро уже нарисовано
        // под слоем `fx`, и линия поверх него читалась бы как шов.
        var k = Math.min(1, (active.r + 2.5) / len);
        var x1 = active.sx + dx * k;
        var y1 = active.sy + dy * k;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(ox, oy);
        ctx.strokeStyle = eCfg.activeHalo;
        ctx.lineWidth = eCfg.activeHaloWidth;
        ctx.stroke();
        ctx.strokeStyle = color;
        ctx.lineWidth = eCfg.activeWidth;
        ctx.stroke();
        shown += 1;
      }
      edgeDraws += shown;
      return shown;
    }

    var layerApi = {
      /* paint(ctx, frame) — один кадр слоя `fx` (CSS-px, transform уже
       * выставлен владельцем сцены). Порядок §2.1 спеки:
       * дальний ореол → ближний ореол → [связи активного узла, §4.3] →
       * кольцо/ореол активного → импульсы → декор → [подписи]. */
      paint: function (ctx, frame) {
        if (!ctx || !frame) return 0;
        paints += 1;
        var scale = frame.camera && frame.camera.scale > 0
          ? frame.camera.scale : 1;
        var camX = frame.camera ? frame.camera.x : 0;
        var camY = frame.camera ? frame.camera.y : 0;
        var W = frame.width || 0;
        var H = frame.height || 0;
        var margin = cfg.glow.margin;
        var nodes = frame.nodes || [];
        var positions = frame.positions || {};
        var lod = (typeof frame.lod === 'number') ? frame.lod : 1;
        var keyIds = frame.keyIds || null;
        var selectedId = (frame.selection == null) ? null : String(frame.selection);
        var hoverId = (frame.hover == null) ? null : String(frame.hover);
        var reduced = frame.reducedMotion === true;
        var now = reduced ? 0 : (frame.now || 0);
        var visible = 0;
        var activeEdges = 0;
        var i;
        var node;
        var p;
        // 1) проекция + отбор видимых (за кадром — не считаем вовсе).
        for (i = 0; i < nodes.length; i += 1) {
          node = nodes[i];
          if (!node || node.id === undefined) continue;
          p = positions[node.id];
          if (!p) continue;
          var sx = (p.x - camX) * scale + W / 2;
          var sy = (p.y - camY) * scale + H / 2;
          if (sx < -margin || sy < -margin || sx > W + margin || sy > H + margin) {
            continue;
          }
          var radiusNet = nodeRadius(node.kind,
            (typeof node.degree === 'number') ? node.degree : 0,
            frame.fitScale);
          var r = radiusNet * scale;
          if (!(r > 0)) continue;
          var slotRef = slot(visible);
          slotRef.id = node.id;
          slotRef.kind = node.kind;
          slotRef.x = p.x;
          slotRef.y = p.y;
          slotRef.r = r;
          slotRef.sx = sx;
          slotRef.sy = sy;
          visible += 1;
        }
        // 2) дальний ореол (LOD: L0 — только ключевые, L1 — ключевые,
        //    L2 — все в кадре), с мягкой пульсацией у набора `P`.
        var pulse = frame.pulse || null;
        for (i = 0; i < visible; i += 1) {
          var s = pool[i];
          var isKey = !keyIds || keyIds[s.id] === true;
          if (lod === 0 && !isKey) continue;
          if (lod === 1 && !isKey) continue;
          var f = 1;
          if (pulse && !reduced) {
            var entry = pulse[s.id];
            if (entry) f = pulseFactor(entry, now);
          }
          drawGlow(ctx, s.kind, 'far', s.sx, s.sy, s.r,
            cfg.glow.far.alpha * f);
        }
        // 3) ближний ореол: L1/L2 — у всех в кадре, L0 — только у ключевых.
        for (i = 0; i < visible; i += 1) {
          var sn = pool[i];
          if (lod === 0 && !(keyIds && keyIds[sn.id] === true)) continue;
          drawGlow(ctx, sn.kind, 'near', sn.sx, sn.sy, sn.r,
            cfg.glow.near.alpha);
        }
        // 4) активный узел: устойчивый ореол + кольцо выбора.
        var active = null;
        for (i = 0; i < visible; i += 1) {
          if (selectedId !== null && String(pool[i].id) === selectedId) {
            active = pool[i];
            break;
          }
        }
        if (!active) {
          for (i = 0; i < visible; i += 1) {
            if (hoverId !== null && String(pool[i].id) === hoverId) {
              active = pool[i];
              break;
            }
          }
        }
        if (active) {
          // §4.3/§12.2 спеки: сначала ВИДИМЫЕ связи выбранного (поверх узлов),
          // затем его ореол/кольцо — активный узел остаётся главным объектом.
          activeEdges = drawActiveEdges(ctx, frame, String(active.id), active);
          var hot = 1 + 0.6 * ((frame.flash > 0) ? frame.flash : 0);
          drawGlow(ctx, active.kind, 'active', active.sx, active.sy, active.r,
            cfg.glow.active.alpha * hot);
          drawRing(ctx, active.sx, active.sy, active.r,
            selectedId !== null ? 1.9 : 1.6, colorOf(active.kind),
            selectedId !== null ? 0.85 : 0.6, now);
        }
        // 5) импульсы — только по реальным рёбрам активного узла.
        var impulses = 0;
        if (active && !reduced && frame.incident && frame.incident.length) {
          impulses = drawImpulses(ctx, frame, String(active.id), {
            sx: active.sx, sy: active.sy, r: active.r,
          }, frame.incident);
        }
        // 6) декор форм: у активного всегда, у остальных — когда его видно.
        if (active) {
          drawDecor(ctx, active.kind, active.sx, active.sy, active.r, 0.95);
        }
        for (i = 0; i < visible; i += 1) {
          var sd = pool[i];
          if (active && String(sd.id) === String(active.id)) continue;
          if (sd.r < 3.2) continue;              // мелкое не различить
          drawDecor(ctx, sd.kind, sd.sx, sd.sy, sd.r, 0.7);
        }
        // 7) подписи — ПОСЛЕ свечения, но ДО кольца выделения (§2.1 спеки):
        //    вызывающий передаёт готовый планер в `frame.drawLabels`.
        if (typeof frame.drawLabels === 'function') frame.drawLabels(ctx);
        ctx.globalAlpha = 1;
        lastActiveEdges = activeEdges;
        return visible + impulses;
      },
      /* counters() — диагностика приёмки: спрайты создаются один раз,
       * в кадре градиенты НЕ создаются (§10.2(5)). */
      counters: function () {
        return {
          sprites: spriteCount, gradients: gradients, paints: paints,
          draws: draws, pooled: pool.length,
          edgeDraws: edgeDraws, activeEdges: lastActiveEdges,
        };
      },
      /* reuseOf() — тот же пул слотов между кадрами (нет аллокаций в кадре). */
      poolRef: function () { return pool; },
      resize: function (nextDpr) {
        var d = finite(nextDpr);
        if (d !== null && d > 0 && d !== dpr) {
          dpr = Math.min(d, cfg.fx.dprMax);
          // Спрайты привязаны к dpr (резкость при DPR 2) — кэш пересобирается.
          sprites = Object.create(null);
          spriteCount = 0;
        }
        return dpr;
      },
      dpr: function () { return dpr; },
      dispose: function () {
        sprites = Object.create(null);
        spriteCount = 0;
        pool.length = 0;
        paints = 0;
        draws = 0;
        edgeDraws = 0;
        lastActiveEdges = 0;
      },
    };
    layerApi.resize(o.dpr || 1);
    return layerApi;
  }

  /* physicsIterations(nodeCount) — таблица §8.1 контракта: 150 / 90 / 60,
   * чтобы синхронная стабилизация 702 узлов не блокировала поток на секунды. */
  function physicsIterations(nodeCount) {
    var cfg = CONFIG.physics;
    var n = finite(nodeCount) || 0;
    if (n <= cfg.middleMax) return cfg.iterationsSmall;
    if (n <= cfg.largeMax) return cfg.iterationsMiddle;
    return cfg.iterationsLarge;
  }

  /* springLengthFor(fitScale) — `70·U` (§8.1). U берём из текущего обзора или
   * из номинала 0.8 на первом layout (позиций ещё нет): просвет между
   * связанными хабами остаётся ≈ 40–90 CSS-px при r = 1. */
  function springLengthFor(fitScale) {
    var cfg = CONFIG.physics;
    var U = radiusScaleFor(fitScale);
    return clamp(cfg.springBase * U, cfg.springMin, cfg.springMax);
  }

  /* physicsOptions(nodeCount, fitScale) — структура §8.1 в одном месте. */
  function physicsOptions(nodeCount, fitScale) {
    var cfg = CONFIG.physics;
    return {
      solver: 'barnesHut',
      barnesHut: {
        gravitationalConstant: cfg.gravitationalConstant,
        centralGravity: cfg.centralGravity,
        springLength: springLengthFor(fitScale),
        springConstant: cfg.springConstant,
        damping: cfg.damping,
        avoidOverlap: cfg.avoidOverlap,
      },
      stabilization: {
        enabled: true,
        iterations: physicsIterations(nodeCount),
        updateInterval: 25,
        fit: false,
      },
      minVelocity: cfg.minVelocity,
      adaptiveTimestep: cfg.adaptiveTimestep,
    };
  }

  return {
    VERSION: VERSION,
    CONFIG: CONFIG,
    NEUTRAL_STYLE: NEUTRAL_STYLE,
    styleFor: styleFor,
    specFor: specFor,
    shapeKeyOf: shapeKeyOf,
    colorOf: colorOf,
    decorOf: decorOf,
    baseDiameterOf: baseDiameterOf,
    targetDiameter: targetDiameter,
    radiusScaleFor: radiusScaleFor,
    nodeRadius: nodeRadius,
    screenDiameter: screenDiameter,
    relativeScale: relativeScale,
    aspectStretch: aspectStretch,
    densityCaps: densityCaps,
    relaxOverlaps: relaxOverlaps,
    bboxOf: bboxOf,
    fitScaleFor: fitScaleFor,
    fitCamera: fitCamera,
    nodeRow: nodeRow,
    edgeRow: edgeRow,
    edgeDeltaRow: edgeDeltaRow,
    edgeState: edgeState,
    nodeRows: nodeRows,
    edgeRows: edgeRows,
    glowSpec: glowSpec,
    spriteSpec: spriteSpec,
    pulsePlan: pulsePlan,
    pulseFactor: pulseFactor,
    hash31: hash31,
    rgba: rgba,
    lighten: lighten,
    createFx: createFx,
    physicsIterations: physicsIterations,
    springLengthFor: springLengthFor,
    physicsOptions: physicsOptions,
  };
}));
