/* POLYGONAL LUMINESCENCE (round 10.26, ADR-1026-3 D1/D3/D4/D5/D7/D8).
 *
 * Единственный АКТИВНЫЙ фоновый рендерер проекта: полигональная сеть на
 * Canvas 2D (полупрозрачные грани, локальный свет, bloom-композиция,
 * детерминированное движение). При `UI_POLYGON_BG_ENABLED=OFF` выводится из
 * активного пути; `aurora-flow.js` (Dark Aurora Flow, OGL) сохранён как
 * soft-откат и НЕ удаляется. В DOM одновременно живёт ровно один рендерер.
 *
 *   * Delaunay-триангуляция — vendored Delaunator 5.0.0 (`window.Delaunator`).
 *   * Детерминизм: фиксированный SEED + собственный mulberry32; вызов
 *     Math.random в построении сцены/топологии запрещён (SC-12). `resize()`
 *     seed НЕ сбрасывает: базовые позиции хранятся в нормализованном
 *     пространстве [0..1].
 *   * CSP-safe / zero-build: same-origin файл, никакого inline/eval/CDN.
 *   * Бюджет mobile: меньше узлов, DPR-кап ≤1.5, уменьшенный offscreen-bloom,
 *     ориентир ~30 FPS. Desktop — DPR-кап ≤2, полная плотность.
 *   * `document.hidden` → stop rAF; `prefers-reduced-motion` → качественная
 *     статика; Canvas 2D недоступен/потерян → честный фолбэк (renderer='none',
 *     canvas снят, `html.polygon-bg` снят → активным остаётся legacy-путь).
 *
 * Публичный контракт D4 (app.js вызывает только его):
 *   window.__PolygonBackground = { start, stop, pause, resume, resize,
 *                                  getDiagnostics, mode }
 * Плюс адаптер совместимости T-3171: `window.__AuroraFlow` подменяется
 * фасадом {start,stop,resize,setPaused,sample,mode}, а исходный контракт
 * сохраняется как `window.__AuroraFlowLegacy` — вызовы app.js НЕ переписаны.
 */
(function () {
  'use strict';

  /* ── D7: обязательные численные параметры (константы модуля) ─────────── */
  var SEED = 20260923;            // фиксированный seed сцены (детерминизм)
  var NODES_DESKTOP = 110;        // диапазон §6.1: 90–140 (цель ~110)
  var NODES_MOBILE = 55;          // диапазон §6.1: 45–75 (цель ~55)
  var TOPO_HZ = 4;                // §6.4: топология пересчитывается ≤ 4 Гц
  var TOPO_FADE_MS = 320;         // плавное смешивание при смене топологии
  var AMP_MIN_PX = 4;             // §9: амплитуда движения узлов 4–18 CSS px
  var AMP_MAX_PX = 18;
  var DPR_CAP_DESKTOP = 2;
  var DPR_CAP_MOBILE = 1.5;
  var BLOOM_SCALE_DESKTOP = 4;    // §7.5: offscreen уменьшенного разрешения
  var BLOOM_SCALE_MOBILE = 6;
  var MAX_EDGE_NORM = 0.30;       // §6.3: фильтр длинных линий (в scaled-норм.)
  var MIN_TRI_AREA = 0.00004;     // отсев вырожденных граней
  var MAX_TRI_AREA = 0.030;       // отсев «плит»
  var TAU = Math.PI * 2;

  /* ── D: палитра §5/§9 — ЕДИНЫЕ константы (11 цветов, без разбросанных RGB) */
  var PAL = [
    '#090D17', // 0 deep indigo space (подложка)
    '#16125A', // 1 indigo глубокий
    '#3030C8', // 2 indigo
    '#355CFF', // 3 blue
    '#7C3AED', // 4 electric violet
    '#A78BFA', // 5 lilac
    '#C4B5FD', // 6 lavender
    '#C026D3', // 7 magenta-violet
    '#42D6C4', // 8 teal / cyan
    '#9AEAFF', // 9 ice blue
    '#F2F7FF', // 10 near white
  ];
  var RGB = PAL.map(hexToRgb);

  /* Зоны композиции §4: A — индиго-пространство, B — сиреневое облако,
   * C — циановый кристаллический кластер, D — соединительные нити (§4 zone D:
   * разреженные `uniform`-узлы + тонкие батч-линии, без плотной паутины).
   * Каждому кластеру — центр, разброс, цвета (индексы PAL) и тип света. */
  var CLUSTERS = [
    { id: 'A',  zone: 'A', cx: 0.20, cy: 0.74, spread: 0.30, colors: [1, 2, 3],
      light: 2, glow: 0.30, ph: 0.0 },
    { id: 'A2', zone: 'A', cx: 0.63, cy: 0.88, spread: 0.24, colors: [1, 2, 3],
      light: 2, glow: 0.22, ph: 2.1 },
    { id: 'B',  zone: 'B', cx: 0.31, cy: 0.30, spread: 0.27, colors: [4, 5, 6, 7],
      light: 5, glow: 0.34, ph: 1.2 },
    { id: 'B2', zone: 'B', cx: 0.50, cy: 0.16, spread: 0.20, colors: [5, 6, 7],
      light: 6, glow: 0.24, ph: 3.4 },
    { id: 'C',  zone: 'C', cx: 0.74, cy: 0.50, spread: 0.26, colors: [3, 8, 9, 10],
      light: 9, glow: 0.40, ph: 4.2 },
    { id: 'C2', zone: 'C', cx: 0.58, cy: 0.66, spread: 0.20, colors: [4, 8, 9],
      light: 8, glow: 0.30, ph: 5.1 },
  ];
  // Зона D — соединительные нити: доля узлов раскладывается равномерно
  // (`uniform`) и связывается тонкими рёбрами; отдельного «кластера-ядра» нет.
  var ZONE_D_UNIFORM_SHARE = 0.12;

  /* ── состояние модуля ─────────────────────────────────────────────────── */
  var st = {
    canvas: null, ctx: null, off: null, offCtx: null,
    cssW: 0, cssH: 0, dpr: 1,
    raf: 0, running: false, paused: false, visPaused: false, reduced: false,
    mode: 'none', contextLost: false, drawErrors: 0,
    frameCount: 0, lastFrameTime: 0, lastFrameTs: 0, startTime: 0,
    ro: null, visBound: false,
    nodes: null, nodeCount: 0,
    triIdx: null, triColA: null, triColB: null, triPh: null,
    triAlpha: null, triPass: null, triCount: 0,
    edgeA: null, edgeB: null, edgeGlow: null, edgeCount: 0,
    topologyDirty: true, lastTopoAt: -1e9, topoFade: 1, topoBlend: 0,
  };

  /* ── мелкие утилиты ───────────────────────────────────────────────────── */
  function hexToRgb(h) {
    var n = parseInt(h.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function mix(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t];
  }
  function rgba(c, a) {
    return 'rgba(' + (c[0] | 0) + ',' + (c[1] | 0) + ',' + (c[2] | 0) +
      ',' + a + ')';
  }
  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }
  function nowMs() {
    return (window.performance && window.performance.now)
      ? window.performance.now() : Date.now();
  }
  function raf(fn) { return window.requestAnimationFrame(fn); }
  function caf(id) {
    if (id && window.cancelAnimationFrame) window.cancelAnimationFrame(id);
  }
  function isMobile() {
    try { return (window.innerWidth || 9999) < 768; } catch (e) { return false; }
  }
  function dprCap() { return isMobile() ? DPR_CAP_MOBILE : DPR_CAP_DESKTOP; }
  function reducedMotion() {
    try {
      return !!(window.matchMedia &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) { return false; }
  }
  function hiddenNow() {
    try { return !!(typeof document !== 'undefined' && document.hidden); }
    catch (e) { return false; }
  }
  /* Детерминированный ГПСЧ (mulberry32) — единственный источник случайности
   * построения сцены. Вызов Math.random здесь запрещён (SC-12). */
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* ── canvas lifecycle (переиспользует семантику aurora-flow.js T-3172) ── */
  function ensureCanvas() {
    if (st.canvas && st.canvas.parentNode) return st.canvas;
    var cv = document.createElement('canvas');
    cv.id = 'polygon-background';
    cv.className = 'polygon-background-canvas';
    cv.setAttribute('aria-hidden', 'true');
    // Прямой потомок body, первым — ВНЕ max-width/scroll-контейнеров (D5).
    if (document.body && document.body.firstChild) {
      document.body.insertBefore(cv, document.body.firstChild);
    } else if (document.body) {
      document.body.appendChild(cv);
    }
    st.canvas = cv;
    return cv;
  }

  /* D5: размер — по ФАКТИЧЕСКОМУ размеру контейнера (`documentElement`), та же
   * семантика, что в `aurora-flow.js::measure()`; второй механизм высоты не
   * создаётся. */
  function measure() {
    var de = document.documentElement;
    var w = de && de.clientWidth, h = de && de.clientHeight;
    if (!(w >= 1) || !(h >= 1)) {
      try {
        var r = (de && typeof de.getBoundingClientRect === 'function')
          ? de.getBoundingClientRect() : null;
        if (r && r.width >= 1 && r.height >= 1) { w = r.width; h = r.height; }
      } catch (e) { /* fallback ниже */ }
    }
    if (!(w >= 1)) w = window.innerWidth || 1;
    if (!(h >= 1)) h = window.innerHeight || 1;
    return { w: w, h: h };
  }

  function ensureResizeObserver() {
    if (typeof window.ResizeObserver === 'undefined' || st.ro) return;
    var de = document.documentElement;
    if (!de) return;
    try {
      st.ro = new window.ResizeObserver(function () { resize(); });
      st.ro.observe(de);
    } catch (e) { st.ro = null; }
  }

  function ensureVisibilityListener() {
    if (st.visBound) return;
    if (typeof document === 'undefined' ||
        typeof document.addEventListener !== 'function') return;
    try {
      document.addEventListener('visibilitychange', function () {
        if (hiddenNow()) {
          if (st.running && !st.paused) {
            st.visPaused = true;
            caf(st.raf); st.raf = 0;
          }
        } else if (st.visPaused) {
          st.visPaused = false;
          if (st.running && !st.paused && !st.raf) {
            st.lastFrameTs = 0;
            st.raf = raf(loop);
          }
        }
      });
      st.visBound = true;
    } catch (e) { /* no-op */ }
  }

  /* ── построение сцены (C: узлы/кластеры/seed) ─────────────────────────── */
  function buildScene() {
    var rng = mulberry32(SEED);
    var n = isMobile() ? NODES_MOBILE : NODES_DESKTOP;
    var nodes = new Array(n);
    // Вес кластеров: плотные ядра + разреженные нити (D). Неравномерная
    // плотность, без равномерной сетки.
    var wsum = 0, i;
    var weights = [0.20, 0.10, 0.24, 0.10, 0.22, 0.14];
    for (i = 0; i < weights.length; i++) wsum += weights[i];
    for (i = 0; i < n; i++) {
      var r = rng() * wsum, ci = 0, acc = 0;
      for (var j = 0; j < weights.length; j++) {
        acc += weights[j];
        if (r <= acc) { ci = j; break; }
      }
      var cl = CLUSTERS[ci];
      var spread = cl.spread;
      var uniform = rng() < ZONE_D_UNIFORM_SHARE;   // D: разреженные «нити»
      var gx = uniform ? (rng() * 2 - 1) : (rng() + rng() - 1);
      var gy = uniform ? (rng() * 2 - 1) : (rng() + rng() - 1);
      var bx = clamp(cl.cx + gx * spread, 0.03, 0.97);
      var by = clamp(cl.cy + gy * spread, 0.03, 0.97);
      var dC = Math.sqrt((bx - cl.cx) * (bx - cl.cx) +
                         (by - cl.cy) * (by - cl.cy));
      var tier = dC < spread * 0.35 ? 2 : (dC < spread * 0.75 ? 1 : 0);
      var ca = RGB[cl.colors[Math.floor(rng() * cl.colors.length)]];
      var cb = RGB[cl.colors[Math.floor(rng() * cl.colors.length)]];
      nodes[i] = {
        bx: bx, by: by,
        nx: bx, ny: by, x: 0, y: 0,
        ampPx: AMP_MIN_PX + rng() * (AMP_MAX_PX - AMP_MIN_PX),
        sp1: 0.10 + rng() * 0.22, sp2: 0.08 + rng() * 0.18,
        ph1: rng() * TAU, ph2: rng() * TAU,
        cluster: ci, tier: tier,
        colA: ca, colB: cb, colPh: rng() * TAU,
        pulsePh: rng() * TAU, pulseSp: 0.05 + rng() * 0.10,
        baseAlpha: tier === 2 ? 0.95 : (tier === 1 ? 0.7 : 0.42),
      };
    }
    st.nodes = nodes;
    st.nodeCount = n;
    st.triIdx = new Int32Array(n * 7);
    st.triColA = new Float32Array(n * 7 * 3);
    st.triColB = new Float32Array(n * 7 * 3);
    st.triPh = new Float32Array(n * 7);
    st.triAlpha = new Float32Array(n * 7);
    st.triPass = new Uint8Array(n * 7);
    st.triCount = 0;
    st.edgeA = new Int32Array(n * 5);
    st.edgeB = new Int32Array(n * 5);
    st.edgeGlow = new Uint8Array(n * 5);
    st.edgeCount = 0;
    st.topologyDirty = true;
    st.lastTopoAt = -1e9;
  }

  /* C: триангуляция + §6.3 фильтр граней + §7 признаки света/яркости. */
  function rebuildTopology() {
    var nodes = st.nodes;
    var n = st.nodeCount;
    if (!nodes || n < 3) return;
    var D = window.Delaunator;
    if (!D || typeof D.from !== 'function') return;
    var tri;
    try {
      tri = D.from(nodes, function (p) { return p.nx; },
                       function (p) { return p.ny; });
    } catch (e) { st.drawErrors++; return; }
    if (!tri || !tri.triangles) return;
    var t3 = tri.triangles;
    var aspect = st.cssH > 0 ? st.cssW / st.cssH : 1;
    var maxEdge = MAX_EDGE_NORM;
    var ti = 0, ec = 0, k;
    st.triCount = 0;
    st.edgeCount = 0;
    for (k = 0; k + 2 < t3.length; k += 3) {
      var a = t3[k], b = t3[k + 1], c = t3[k + 2];
      var na = nodes[a], nb = nodes[b], nc = nodes[c];
      var e1 = edgeLen(na, nb, aspect), e2 = edgeLen(nb, nc, aspect),
          e3 = edgeLen(nc, na, aspect);
      if (e1 > maxEdge || e2 > maxEdge || e3 > maxEdge) continue;
      var area = triArea(na, nb, nc, aspect);
      if (area < MIN_TRI_AREA || area > MAX_TRI_AREA) continue;
      // Кластерный разброс: грань из сильно разных зон — прозрачнее.
      var spreadMix = (na.cluster === nb.cluster ? 0 : 1) +
                      (nb.cluster === nc.cluster ? 0 : 1) +
                      (nc.cluster === na.cluster ? 0 : 1);
      var bright = (na.tier + nb.tier + nc.tier) / 3;
      var light = lightFactor(na, nb, nc);
      var alpha = (0.10 - Math.min(0.06, area * 2.0)) +
                  0.05 * bright - 0.02 * spreadMix + 0.05 * light;
      alpha = clamp(alpha, 0.015, 0.20);
      var ca = mix3(na.colA, nb.colA, nc.colA);
      var cb = mix3(na.colB, nb.colB, nc.colB);
      var pass = 0;
      if (light > 0.55) pass = 2;          // локальный яркий акцент (зона C)
      else if (bright > 1.35) pass = 1;    // мягкая подсветка ярких граней
      var o3 = st.triCount * 3;
      st.triIdx[ti++] = a; st.triIdx[ti++] = b; st.triIdx[ti++] = c;
      st.triColA[o3] = ca[0]; st.triColA[o3 + 1] = ca[1]; st.triColA[o3 + 2] = ca[2];
      st.triColB[o3] = cb[0]; st.triColB[o3 + 1] = cb[1]; st.triColB[o3 + 2] = cb[2];
      st.triPh[st.triCount] = (na.colPh + nb.colPh + nc.colPh) / 3;
      st.triAlpha[st.triCount] = alpha;
      st.triPass[st.triCount] = pass;
      st.triCount++;
      ec = addEdge(ec, a, b, nodes);
      ec = addEdge(ec, b, c, nodes);
      ec = addEdge(ec, c, a, nodes);
    }
    st.edgeCount = ec;
    st.lastTopoAt = nowMs();
    st.topologyDirty = false;
    st.topoFade = 0;
  }

  function edgeLen(a, b, aspect) {
    var dx = (b.nx - a.nx) * aspect, dy = b.ny - a.ny;
    return Math.sqrt(dx * dx + dy * dy);
  }
  function triArea(a, b, c, aspect) {
    var ax = a.nx * aspect, bx = b.nx * aspect, cx = c.nx * aspect;
    return Math.abs((bx - ax) * (c.ny - a.ny) -
                    (cx - ax) * (b.ny - a.ny)) * 0.5;
  }
  function mix3(a, b, c) {
    return [(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3,
            (a[2] + b[2] + c[2]) / 3];
  }
  /* §7.2/§6.3: близость грани к световому центру (яркость от расстояния). */
  function lightFactor(a, b, c) {
    var best = 0;
    for (var i = 0; i < CLUSTERS.length; i++) {
      var cl = CLUSTERS[i];
      var dx = ((a.nx + b.nx + c.nx) / 3 - cl.cx);
      var dy = ((a.ny + b.ny + c.ny) / 3 - cl.cy);
      var d = Math.sqrt(dx * dx + dy * dy);
      var v = 1 - clamp(d / 0.42, 0, 1);
      if (v > best) best = v;
    }
    return best;
  }
  function addEdge(ec, a, b, nodes) {
    var lo = a < b ? a : b, hi = a < b ? b : a;
    for (var i = 0; i < ec; i++) {
      if (st.edgeA[i] === lo && st.edgeB[i] === hi) return ec;
    }
    if (ec >= st.edgeA.length) return ec;
    var glow = (nodes[lo].tier === 2 && nodes[hi].tier === 2) ? 1 : 0;
    st.edgeA[ec] = lo; st.edgeB[ec] = hi; st.edgeGlow[ec] = glow;
    return ec + 1;
  }

  /* F: движение узлов — детерминированная функция времени (4–18 px, своя
   * фаза/скорость), плюс дрейф световых центров. */
  function computePositions(t) {
    var nodes = st.nodes, n = st.nodeCount;
    var mn = Math.min(st.cssW, st.cssH) || 1;
    for (var i = 0; i < n; i++) {
      var nd = nodes[i];
      var ampN = nd.ampPx / mn;
      var nx = nd.bx + ampN * Math.sin(t * nd.sp1 + nd.ph1);
      var ny = nd.by + ampN * Math.cos(t * nd.sp2 + nd.ph2) * 0.85;
      nd.nx = clamp(nx, 0.02, 0.98);
      nd.ny = clamp(ny, 0.02, 0.98);
      // Редкий плавный импульс на пересечениях (§8.3): не синхронный.
      nd.pulse = 0.5 + 0.5 * Math.sin(t * nd.pulseSp + nd.pulsePh);
      nd.x = nd.nx * st.cssW;
      nd.y = nd.ny * st.cssH;
    }
  }

  /* ── отрисовка ────────────────────────────────────────────────────────── */
  function radial(x, y, r, col, a) {
    var g = st.ctx.createRadialGradient(x, y, 0, x, y, Math.max(1, r));
    g.addColorStop(0, rgba(col, a));
    g.addColorStop(0.55, rgba(col, a * 0.35));
    g.addColorStop(1, rgba(col, 0));
    return g;
  }

  function drawRadiation(t) {
    var ctx = st.ctx;
    for (var i = 0; i < CLUSTERS.length; i++) {
      var cl = CLUSTERS[i];
      var cx = (cl.cx + 0.035 * Math.sin(t * 0.045 + cl.ph)) * st.cssW;
      var cy = (cl.cy + 0.03 * Math.cos(t * 0.038 + cl.ph * 1.3)) * st.cssH;
      var r = (cl.glow + 0.04 * Math.sin(t * 0.06 + cl.ph)) *
              Math.min(st.cssW, st.cssH) * 1.6;
      ctx.fillStyle = radial(cx, cy, r, RGB[cl.light], 0.16);
      ctx.fillRect(0, 0, st.cssW, st.cssH);
    }
  }

  function morphPhase(t, ph) { return 0.5 + 0.5 * Math.sin(t * 0.06 + ph); }

  function fillTri(ia, ib, ic, col, alpha) {
    var ctx = st.ctx, nodes = st.nodes;
    ctx.globalAlpha = alpha;
    ctx.fillStyle = rgba(col, 1);
    ctx.beginPath();
    ctx.moveTo(nodes[ia].x, nodes[ia].y);
    ctx.lineTo(nodes[ib].x, nodes[ib].y);
    ctx.lineTo(nodes[ic].x, nodes[ic].y);
    ctx.closePath();
    ctx.fill();
  }

  function drawFacets(t) {
    var ctx = st.ctx;
    var fade = 0.55 + 0.45 * st.topoFade;
    var i, idx, pass, ca, cb, col, ph;
    // Проход 1 — полупрозрачная заливка всех отфильтрованных граней.
    for (i = 0; i < st.triCount; i++) {
      idx = i * 3;
      ca = [st.triColA[idx], st.triColA[idx + 1], st.triColA[idx + 2]];
      cb = [st.triColB[idx], st.triColB[idx + 1], st.triColB[idx + 2]];
      ph = morphPhase(t, st.triPh[i]);
      col = mix(ca, cb, ph);
      fillTri(st.triIdx[idx], st.triIdx[idx + 1], st.triIdx[idx + 2],
              col, st.triAlpha[i] * fade);
    }
    ctx.globalAlpha = 1;
    // Проход 2 — мягкая подсветка ярких граней (screen/lighter).
    for (pass = 1; pass <= 2; pass++) {
      for (i = 0; i < st.triCount; i++) {
        if (st.triPass[i] !== pass) continue;
        idx = i * 3;
        ca = [st.triColA[idx], st.triColA[idx + 1], st.triColA[idx + 2]];
        cb = [st.triColB[idx], st.triColB[idx + 1], st.triColB[idx + 2]];
        col = mix(ca, cb, morphPhase(t, st.triPh[i]));
        if (pass === 2) col = mix(col, RGB[10], 0.5);   // акценты почти белые
        fillTri(st.triIdx[idx], st.triIdx[idx + 1], st.triIdx[idx + 2],
                col, (pass === 1 ? 0.10 : 0.13) * fade);
      }
    }
    ctx.globalAlpha = 1;
  }

  function drawLines(t) {
    var ctx = st.ctx, nodes = st.nodes;
    var i, a, b;
    // Тонкие линии — один батч-путь (без «плотной паутины»).
    ctx.globalAlpha = 0.10;
    ctx.strokeStyle = 'rgba(154,190,255,0.9)';
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    for (i = 0; i < st.edgeCount; i++) {
      a = st.edgeA[i]; b = st.edgeB[i];
      ctx.moveTo(nodes[a].x, nodes[a].y);
      ctx.lineTo(nodes[b].x, nodes[b].y);
    }
    ctx.stroke();
    // Выборочное свечение — только яркие рёбра (не на всех).
    ctx.globalAlpha = 0.35;
    ctx.strokeStyle = 'rgba(196,181,253,0.85)';
    ctx.lineWidth = 1.1;
    ctx.shadowColor = 'rgba(167,139,250,0.75)';
    ctx.shadowBlur = isMobile() ? 5 : 8;
    ctx.beginPath();
    for (i = 0; i < st.edgeCount; i++) {
      if (!st.edgeGlow[i]) continue;
      a = st.edgeA[i]; b = st.edgeB[i];
      ctx.moveTo(nodes[a].x, nodes[a].y);
      ctx.lineTo(nodes[b].x, nodes[b].y);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.globalAlpha = 1;
  }

  function drawNodes(t) {
    var ctx = st.ctx, nodes = st.nodes, i;
    // Рассеяние (только desktop, не у слабых узлов).
    if (!isMobile()) {
      for (i = 0; i < st.nodeCount; i++) {
        var ns = nodes[i];
        if (ns.tier === 0) continue;
        ctx.globalAlpha = 0.05 * ns.baseAlpha;
        ctx.fillStyle = rgba(mix(ns.colA, ns.colB, 0.5), 1);
        ctx.beginPath();
        ctx.arc(ns.x, ns.y, 14 + 4 * ns.pulse, 0, TAU);
        ctx.fill();
      }
    }
    // Ореол — радиальный градиент только у ярких (локальность яркости §5).
    for (i = 0; i < st.nodeCount; i++) {
      var nd = nodes[i];
      if (nd.tier !== 2) continue;
      var col = mix(nd.colA, nd.colB, morphPhase(t, nd.colPh));
      ctx.globalAlpha = (0.22 + 0.12 * nd.pulse) * nd.baseAlpha;
      ctx.fillStyle = radial(nd.x, nd.y, 22 + 8 * nd.pulse, col, 1);
      ctx.fillRect(nd.x - 30, nd.y - 30, 60, 60);
    }
    // Умеренные — мягкий флэт-ореол (без градиента: бюджет mobile).
    for (i = 0; i < st.nodeCount; i++) {
      var nm = nodes[i];
      if (nm.tier !== 1) continue;
      ctx.globalAlpha = 0.10 * nm.baseAlpha;
      ctx.fillStyle = rgba(mix(nm.colA, nm.colB, 0.5), 1);
      ctx.beginPath();
      ctx.arc(nm.x, nm.y, 6 + 2 * nm.pulse, 0, TAU);
      ctx.fill();
    }
    // Центры узлов — тиры слабые/умеренные/яркие (не все белые).
    for (i = 0; i < st.nodeCount; i++) {
      var nc = nodes[i];
      var c2 = mix(nc.colA, nc.colB, morphPhase(t, nc.colPh));
      if (nc.tier === 2) c2 = mix(c2, RGB[10], 0.45);
      ctx.globalAlpha = (0.55 + 0.35 * nc.pulse) * nc.baseAlpha;
      ctx.fillStyle = rgba(c2, 1);
      ctx.beginPath();
      ctx.arc(nc.x, nc.y,
              nc.tier === 2 ? 2.2 : (nc.tier === 1 ? 1.6 : 1.1), 0, TAU);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  /* §7.5 bloom — offscreen уменьшенного разрешения; НЕ CSS-фильтр размытия на
   * полноэкранном canvas и не на интерфейсе. */
  function drawBloom() {
    var off = st.off, octx = st.offCtx;
    if (!off || !octx) return;
    var scale = isMobile() ? BLOOM_SCALE_MOBILE : BLOOM_SCALE_DESKTOP;
    var ow = Math.max(1, Math.round(st.canvas.width / scale));
    var oh = Math.max(1, Math.round(st.canvas.height / scale));
    if (off.width !== ow) off.width = ow;
    if (off.height !== oh) off.height = oh;
    octx.setTransform(1, 0, 0, 1, 0, 0);
    octx.globalCompositeOperation = 'source-over';
    octx.clearRect(0, 0, ow, oh);
    try { octx.drawImage(st.canvas, 0, 0, ow, oh); } catch (e) { return; }
    var ctx = st.ctx;
    ctx.imageSmoothingEnabled = true;
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = isMobile() ? 0.20 : 0.26;
    ctx.drawImage(off, 0, 0, st.cssW, st.cssH);
    if (!isMobile()) {
      ctx.globalAlpha = 0.12;
      ctx.drawImage(off, -6, -6, st.cssW + 12, st.cssH + 12);
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
  }

  function draw(t) {
    var ctx = st.ctx;
    if (!ctx) return;
    var w = st.cssW, h = st.cssH;
    if (!(w > 0 && h > 0)) return;
    try {
      ctx.setTransform(st.dpr, 0, 0, st.dpr, 0, 0);
      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = 1;
      ctx.fillStyle = PAL[0];
      ctx.fillRect(0, 0, w, h);

      var tms = nowMs();
      if (st.topologyDirty || (tms - st.lastTopoAt) >= (1000 / TOPO_HZ)) {
        rebuildTopology();
      }
      if (st.topoFade < 1) {
        st.topoFade = clamp(st.topoFade +
          (tms - (st.topoBlend || tms)) / TOPO_FADE_MS, 0, 1);
      }
      st.topoBlend = tms;
      computePositions(t);

      ctx.globalCompositeOperation = 'lighter';
      drawRadiation(t);
      drawFacets(t);
      drawLines(t);
      drawNodes(t);
      drawBloom();

      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = 1;
      st.frameCount++;
      st.lastFrameTime = tms;
      st.drawErrors = 0;
    } catch (e) {
      st.drawErrors++;
      if (st.drawErrors >= 3) fallbackNone();
    }
  }

  function loop(now) {
    st.raf = 0;
    if (!st.running) return;
    if (st.paused || hiddenNow()) return;   // rAF не переподписывается
    var minDelta = isMobile() ? 33 : 0;     // mobile ~30 FPS
    if (!st.lastFrameTs || (now - st.lastFrameTs) >= minDelta) {
      st.lastFrameTs = now;
      draw((now - st.startTime) / 1000);
    }
    st.raf = raf(loop);
  }

  /* ── контракт жизненного цикла ────────────────────────────────────────── */
  function initCanvas2d(cv) {
    try {
      var ctx = cv.getContext('2d');
      if (!ctx) return false;
      st.ctx = ctx;
      st.off = document.createElement('canvas');
      st.offCtx = st.off.getContext('2d') || null;
      st.mode = 'canvas2d';
      st.contextLost = false;
      // Canvas2D `contextlost` (поддерживается Chromium/WebKit) → честный фолбэк.
      try {
        cv.addEventListener('contextlost', function (e) {
          if (e && e.preventDefault) e.preventDefault();
          st.contextLost = true;
          fallbackNone();
        });
      } catch (e2) { /* no-op */ }
      return true;
    } catch (e3) { return false; }
  }

  /* Честный фолбэк §4.3: canvas снят, класс снят → активным остаётся
   * legacy-путь; сцена не «замирает белым экраном». */
  function fallbackNone() {
    st.mode = 'none';
    st.contextLost = true;
    caf(st.raf); st.raf = 0;
    st.running = false;
    detachCanvas();
    try {
      if (document.documentElement && document.documentElement.classList) {
        document.documentElement.classList.remove('polygon-bg');
      }
    } catch (e) { /* no-op */ }
  }

  function detachCanvas() {
    if (st.ro) {
      try { st.ro.disconnect(); } catch (e0) { /* no-op */ }
      st.ro = null;
    }
    var cv = st.canvas;
    if (cv && cv.parentNode) {
      try { cv.parentNode.removeChild(cv); } catch (e) { /* no-op */ }
    }
    st.canvas = null; st.ctx = null; st.off = null; st.offCtx = null;
    // Освобождение буферов (T-3173): пересборка при start() — из того же SEED.
    st.nodes = null; st.nodeCount = 0;
    st.triIdx = null; st.triColA = null; st.triColB = null;
    st.triPh = null; st.triAlpha = null; st.triPass = null; st.triCount = 0;
    st.edgeA = null; st.edgeB = null; st.edgeGlow = null; st.edgeCount = 0;
  }

  function start() {
    if (typeof document === 'undefined' || !document.body) return;
    if (st.running) return;
    var cv = ensureCanvas();
    if (!st.nodes) buildScene();
    if (!st.ctx && !initCanvas2d(cv)) { fallbackNone(); return; }
    st.reduced = reducedMotion();
    st.contextLost = false;
    resize();
    ensureResizeObserver();
    ensureVisibilityListener();
    st.running = true;
    st.paused = false;
    st.visPaused = false;
    if (st.reduced) {
      draw(4);              // один качественный статичный кадр
      st.running = false;   // затем без rAF
      return;
    }
    st.startTime = nowMs();
    st.lastFrameTs = 0;
    st.raf = raf(loop);
  }

  function stop() {
    st.running = false;
    st.paused = false;
    st.visPaused = false;
    caf(st.raf); st.raf = 0;
    detachCanvas();
    st.mode = 'none';
  }

  function pause() {
    st.paused = true;
    caf(st.raf); st.raf = 0;
  }

  function resume() {
    if (!st.running || !st.paused) return;
    st.paused = false;
    if (st.raf) return;
    st.lastFrameTs = 0;
    st.raf = raf(loop);
  }

  /* resize = CSS-размер + drawing buffer + scale (без скачка, без сброса seed);
   * переиспользует существующие точки вызова app.js (`_auroraResize`). */
  function resize() {
    var cv = st.canvas;
    if (!cv) return;
    var m = measure();
    var w = Math.max(1, Math.round(m.w)), h = Math.max(1, Math.round(m.h));
    var dpr = Math.min(window.devicePixelRatio || 1, dprCap());
    var bw = Math.max(1, Math.round(w * dpr));
    var bh = Math.max(1, Math.round(h * dpr));
    cv.style.width = w + 'px';
    cv.style.height = h + 'px';
    if (cv.width !== bw) cv.width = bw;      // сброс состония контекста → ниже transform
    if (cv.height !== bh) cv.height = bh;
    st.cssW = w; st.cssH = h; st.dpr = dpr;
    if (st.ctx) st.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    st.topologyDirty = true;
    if (!st.running || st.paused || st.reduced) {
      draw(st.startTime ? (nowMs() - st.startTime) / 1000 : 4);
    }
  }

  function mode() { return st.mode; }

  function getDiagnostics() {
    return {
      renderer: st.mode === 'canvas2d' ? 'canvas2d' : 'none',
      canvasWidth: st.canvas ? (st.canvas.width || 0) : 0,
      canvasHeight: st.canvas ? (st.canvas.height || 0) : 0,
      devicePixelRatio: st.dpr || (window.devicePixelRatio || 1),
      nodeCount: st.nodeCount || 0,
      triangleCount: st.triCount || 0,
      frameCount: st.frameCount || 0,
      lastFrameTime: st.lastFrameTime || 0,
      isPaused: !!st.paused,
      isReducedMotion: !!st.reduced,
      contextLost: !!st.contextLost,
    };
  }

  /* 8×8 RGB-сетка из фактического canvas (совместимо с прежней проверкой). */
  function sample() {
    var cv = st.canvas;
    if (!cv || !st.ctx) return null;
    var N = 8, out = [];
    try {
      var iw = cv.width, ih = cv.height;
      var img = st.ctx.getImageData(0, 0, iw, ih).data;
      for (var yy = 0; yy < N; yy++) {
        for (var xx = 0; xx < N; xx++) {
          var qx = Math.min(iw - 1, Math.floor((xx + 0.5) * iw / N));
          var qy = Math.min(ih - 1, Math.floor((yy + 0.5) * ih / N));
          var ii = (qy * iw + qx) * 4;
          out.push([img[ii], img[ii + 1], img[ii + 2]]);
        }
      }
    } catch (e) { return null; }
    return out;
  }

  /* ── адаптер совместимости T-3171 (app.js не переписывается) ──────────── */
  var legacy = (typeof window !== 'undefined' && window.__AuroraFlow) || null;
  window.__AuroraFlowLegacy = legacy;

  function legacyFlow() {
    if (legacy && typeof legacy.start === 'function') return legacy;
    return null;
  }

  window.__PolygonBackground = {
    start: start, stop: stop, pause: pause, resume: resume,
    resize: resize, getDiagnostics: getDiagnostics, mode: mode,
  };

  window.__AuroraFlow = {
    start: start,
    stop: stop,
    resize: function () {
      if (st.canvas) resize();
      else { var l = legacyFlow(); if (l && l.resize) l.resize(); }
    },
    setPaused: function (p) {
      if (st.canvas) { if (p) pause(); else resume(); }
      else { var l = legacyFlow(); if (l && l.setPaused) l.setPaused(!!p); }
    },
    sample: function () {
      if (st.canvas) return sample();
      var l = legacyFlow();
      return (l && l.sample) ? l.sample() : null;
    },
    mode: function () {
      if (st.canvas) return st.mode;
      var l = legacyFlow();
      return (l && l.mode) ? l.mode() : 'none';
    },
    // Маркер: это фасад Polygon, а не исходный Aurora (legacyFlow()).
    __polygonAdapter: true,
  };
})();
