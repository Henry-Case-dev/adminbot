'use strict';
/* round 10.26 EXTRA `polygonal-luminescence-round1026` (ADR-1026-3) — реальный
 * unit-тест фонового модуля `web/static/polygon-background.js` (не grep):
 *   * контракт D4 `__PolygonBackground{start,stop,pause,resume,resize,
 *     getDiagnostics,mode}` + адаптер T-3171 `__AuroraFlow` / `__AuroraFlowLegacy`;
 *   * жизненный цикл: start → 'canvas2d' + rAF, кадры растут; pause/resume;
 *     stop() снимает canvas из DOM и освобождает сцену (режим 'none');
 *   * `getDiagnostics()` — все 11 полей §14.1; node-бюджеты §6.1 (desktop/mobile);
 *   * детерминизм-инварианты: фикс. SEED, mulberry32, НЕТ `Math.random()` в
 *     построении сцены/топологии; `resize()` seed не сбрасывает;
 *   * §13: топология ≤ 4 Гц, DPR-кап 2/1.5, амплитуда 4–18 px, offscreen-bloom
 *     (нет `ctx.filter`/`filter: blur` на полноэкранном canvas); §5 палитра (11);
 *   * CSP/zero-build: нет CDN, нет data-URI; порядок script (delaunator →
 *     polygon-background → app.js).
 *   * F: §8 «мерцание свечения» замедлено ровно ×2 (правка владельца,
 *     v2.58.20): PULSE_SPEED_MIN/MAX и GLOW_SHIMMER_SPEED = прежние / 2;
 *     движение §9 / morph §8.1 / дрейф §8.2 НЕ замедлены.
 * Запуск: node tests/js/round1026_polygon_background_test.js
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const POLY = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'polygon-background.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const VENDOR = path.join(ROOT, 'web', 'static', 'vendor',
  'delaunator.5.0.0.min.js');

/* ── stub DOM / Canvas2D ─────────────────────────────────────────────────── */
function makeCtx(cv) {
  const noop = function () {};
  const grad = { addColorStop: noop };
  const ctx = {
    canvas: cv,
    globalAlpha: 1, globalCompositeOperation: 'source-over',
    fillStyle: '#000', strokeStyle: '#000', lineWidth: 1,
    shadowBlur: 0, shadowColor: 'transparent', imageSmoothingEnabled: true,
    setTransform: noop, fillRect: noop, clearRect: noop, beginPath: noop,
    moveTo: noop, lineTo: noop, closePath: noop, fill: noop, stroke: noop,
    arc: noop, save: noop, restore: noop, translate: noop, scale: noop,
    createRadialGradient: () => grad, createLinearGradient: () => grad,
    drawImage: noop,
    getImageData: function (x, y, w, h) {
      return { data: new Uint8ClampedArray(Math.max(1, w * h * 4)) };
    },
  };
  return ctx;
}

const appended = [];
function makeCanvas() {
  const cv = {
    id: '', className: '', width: 0, height: 0, style: {},
    parentNode: null, _ctx: null, _listeners: {},
    setAttribute(k, v) { this[k] = v; },
    getAttribute(k) { return this[k]; },
    getContext(type) {
      if (type !== '2d') return null;
      if (!this._ctx) this._ctx = makeCtx(this);
      return this._ctx;
    },
    addEventListener(ev, fn) { this._listeners[ev] = fn; },
  };
  return cv;
}

const docEl = {
  clientWidth: 1440, clientHeight: 900,
  getBoundingClientRect: () => ({ width: 1440, height: 900 }),
  classList: {
    _s: {},
    toggle(n, on) { this._s[n] = !!on; },
    add(n) { this._s[n] = true; },
    remove(n) { this._s[n] = false; },
    contains(n) { return !!this._s[n]; },
  },
  style: { setProperty() {} },
};
const body = {
  firstChild: null,
  insertBefore(node) { node.parentNode = body; body.firstChild = node; return node; },
  appendChild(node) {
    node.parentNode = body;
    if (!body.firstChild) body.firstChild = node;
    return node;
  },
  removeChild(node) { node.parentNode = null; if (body.firstChild === node) body.firstChild = null; return node; },
};
const documentStub = {
  hidden: false, body, documentElement: docEl,
  addEventListener() {}, removeEventListener() {},
  createElement(tag) { return tag === 'canvas' ? makeCanvas() : {}; },
  getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};

const rafQueue = [];
global.window = {
  innerWidth: 1440, innerHeight: 900, devicePixelRatio: 2,
  matchMedia: () => ({ matches: false }),
  requestAnimationFrame(fn) { rafQueue.push(fn); return rafQueue.length; },
  cancelAnimationFrame() {},
  // legacy Aurora (реальный контракт) — должен быть сохранён адаптером.
  __AuroraFlow: {
    start() {}, stop() {}, resize() {}, setPaused() {},
    sample: () => [[1, 2, 3]], mode: () => 'webgl',
  },
  // Delaunator 5.0.0 (builder-контракт: `Delaunator.from` — функция).
  Delaunator: {
    from(points) {
      const n = points.length;
      const tris = [];
      for (let i = 0; i < n; i++) {
        let b1 = -1, b2 = -1, d1 = Infinity, d2 = Infinity;
        for (let j = 0; j < n; j++) {
          if (j === i) continue;
          const dx = points[j].nx - points[i].nx;
          const dy = points[j].ny - points[i].ny;
          const dd = dx * dx + dy * dy;
          if (dd < d1) { d2 = d1; b2 = b1; d1 = dd; b1 = j; }
          else if (dd < d2) { d2 = dd; b2 = j; }
        }
        if (b1 >= 0 && b2 >= 0) tris.push(i, b1, b2);
      }
      return { triangles: Uint32Array.from(tris) };
    },
  },
};
global.document = documentStub;

// Загрузка модуля: перехватываем legacy *до* подмены.
const legacyBefore = global.window.__AuroraFlow;
require(path.join(ROOT, 'web', 'static', 'polygon-background.js'));

const PB = global.window.__PolygonBackground;
const AF = global.window.__AuroraFlow;

/* ── A. Контракт модуля D4 + адаптер T-3171 ──────────────────────────────── */
{
  assert.ok(PB, 'window.__PolygonBackground должен быть определён');
  for (const m of ['start', 'stop', 'pause', 'resume', 'resize',
                   'getDiagnostics', 'mode']) {
    assert.strictEqual(typeof PB[m], 'function', 'A: __PolygonBackground.' + m);
  }
  assert.strictEqual(typeof AF, 'object', 'A: адаптер __AuroraFlow');
  for (const m of ['start', 'stop', 'resize', 'setPaused', 'sample', 'mode']) {
    assert.strictEqual(typeof AF[m], 'function', 'A: адаптер.' + m);
  }
  assert.strictEqual(global.window.__AuroraFlowLegacy, legacyBefore,
    'A: legacy Aurora сохранён как __AuroraFlowLegacy');
  assert.ok(AF.__polygonAdapter === true, 'A: фасад помечен как адаптер Polygon');
  assert.strictEqual(PB.mode(), 'none', 'A: до start — режим none');
  const d0 = PB.getDiagnostics();
  for (const f of ['renderer', 'canvasWidth', 'canvasHeight', 'devicePixelRatio',
                   'nodeCount', 'triangleCount', 'frameCount', 'lastFrameTime',
                   'isPaused', 'isReducedMotion', 'contextLost']) {
    assert.ok(f in d0, 'A: getDiagnostics поле ' + f);
  }
  assert.strictEqual(d0.renderer, 'none', 'A: без start renderer=none');
}

/* ── B. start() → Canvas2D, canvas в DOM первым, rAF, диагностика ────────── */
{
  PB.start();
  assert.strictEqual(PB.mode(), 'canvas2d', 'B: start → canvas2d');
  const cv = documentStub.body.firstChild;
  assert.ok(cv, 'B: canvas вставлен в body');
  assert.strictEqual(cv.id, 'polygon-background', 'B: id');
  assert.strictEqual(cv.className, 'polygon-background-canvas', 'B: класс');
  assert.strictEqual(cv.getAttribute('aria-hidden'), 'true', 'B: aria-hidden');
  assert.ok(cv.width > 0 && cv.height > 0, 'B: drawing buffer задан');
  let d = PB.getDiagnostics();
  assert.strictEqual(d.renderer, 'canvas2d', 'B: renderer');
  assert.ok(d.nodeCount >= 90 && d.nodeCount <= 140,
    'B: desktop узлов 90–140, факт ' + d.nodeCount);
  assert.ok(d.triangleCount > 0, 'B: грани построены');
  assert.ok(d.canvasWidth > 0 && d.canvasHeight > 0, 'B: размеры canvas');
  assert.ok(d.devicePixelRatio <= 2, 'B: DPR-кап desktop ≤2');
  // Прогоняем кадры через rAF-очередь.
  const frames = rafQueue.length;
  assert.ok(frames > 0, 'B: rAF запланирован');
  const fn = rafQueue.shift();
  fn(1000); const f1 = PB.getDiagnostics().frameCount;
  const fn2 = rafQueue.shift();
  fn2(2000); const f2 = PB.getDiagnostics().frameCount;
  assert.ok(f2 > f1, 'B: frameCount растёт (' + f1 + '→' + f2 + ')');
  assert.ok(PB.getDiagnostics().lastFrameTime > 0, 'B: lastFrameTime');
  assert.ok(d.frameCount >= 0, 'B: frameCount ≥0');

  // pause/resume — идемпотентны.
  PB.pause(); PB.pause();
  assert.strictEqual(PB.getDiagnostics().isPaused, true, 'B: pause');
  PB.resume(); PB.resume();
  assert.strictEqual(PB.getDiagnostics().isPaused, false, 'B: resume');
  assert.strictEqual(PB.mode(), 'canvas2d', 'B: canvas жив после resume');

  // resize без исключений, seed/сцена сохранены (nodeCount тот же).
  const before = PB.getDiagnostics().nodeCount;
  PB.resize();
  assert.strictEqual(PB.getDiagnostics().nodeCount, before,
    'B: resize не пересоздаёт сцену (seed стабилен)');
}

/* ── C. stop() снимает canvas и отменяет rAF (ровно один рендерер) ────────── */
{
  PB.stop();
  assert.strictEqual(PB.mode(), 'none', 'C: stop → none');
  assert.strictEqual(documentStub.body.firstChild, null,
    'C: canvas снят из DOM');
  const d = PB.getDiagnostics();
  assert.strictEqual(d.renderer, 'none', 'C: renderer=none');
  assert.strictEqual(d.triangleCount, 0, 'C: буферы освобождены');
  // Идемпотентность без canvas.
  PB.stop(); PB.pause(); PB.resume(); PB.resize();
  assert.strictEqual(PB.mode(), 'none', 'C: повторные вызовы безопасны');
  // Адаптер при отсутствии Polygon-канваса проксирует legacy Aurora.
  assert.strictEqual(AF.mode(), 'webgl', 'C: адаптер → legacy mode');
  assert.deepStrictEqual(AF.sample(), [[1, 2, 3]], 'C: адаптер → legacy sample');
  AF.setPaused(true); AF.setPaused(false); AF.resize();
  // Повторный start после stop — тот же seed → тот же nodeCount.
  PB.start();
  assert.strictEqual(PB.getDiagnostics().nodeCount, 110,
    'C: повторный start — фиксированное число узлов (детерминизм)');
}

/* ── D. Source-инварианты (детерминизм/палитра/перф/CSP) ─────────────────── */
{
  // Детерминизм §5.
  assert.ok(/var SEED = 20260923/.test(POLY), 'D: фиксированный SEED');
  assert.ok(/function mulberry32/.test(POLY), 'D: собственный ГПСЧ mulberry32');
  assert.ok(!/Math\.random\s*\(/.test(POLY), 'D: Math.random() запрещён');
  assert.ok(POLY.indexOf('SEED') >= 0 && POLY.indexOf('mulberry32(SEED)') >= 0,
    'D: сцена строится из SEED');
  // Бюджеты узлов §6.1 + топология/амплитуда/DPR §6.4/§9/§13.
  assert.ok(/NODES_DESKTOP = 110/.test(POLY), 'D: desktop 110 (90–140)');
  assert.ok(/NODES_MOBILE = 55/.test(POLY), 'D: mobile 55 (45–75)');
  assert.ok(/TOPO_HZ = 4/.test(POLY), 'D: топология ≤4 Гц');
  assert.ok(/AMP_MIN_PX = 4/.test(POLY) && /AMP_MAX_PX = 18/.test(POLY),
    'D: амплитуда 4–18 px');
  assert.ok(/DPR_CAP_DESKTOP = 2/.test(POLY) && /DPR_CAP_MOBILE = 1\.5/.test(POLY),
    'D: DPR-кап 2 / 1.5');
  assert.ok(/isMobile\(\) \? 33 : 0/.test(POLY), 'D: mobile ~30 FPS (minDelta 33)');
  assert.ok(/BLOOM_SCALE_DESKTOP/.test(POLY) && /drawImage\(st\.canvas/.test(POLY),
    'D: offscreen-bloom уменьшенного разрешения');
  assert.ok(!/ctx\.filter\s*=/.test(POLY) && !/filter\s*:\s*['"]?blur/.test(POLY),
    'D: нет filter:blur на полноэкранном canvas');
  assert.ok(!/getContext\(['"]webgl/.test(POLY),
    'D: Polygon — Canvas2D, без WebGL-контекста');
  // Палитра §5 — 11 единых констант.
  const pal = POLY.match(/var PAL = \[([\s\S]*?)\];/);
  assert.ok(pal, 'D: PAL');
  const colors = pal[1].match(/#[0-9A-Fa-f]{6}/g) || [];
  assert.strictEqual(colors.length, 11, 'D: 11 цветов §5');
  for (const c of ['#090D17', '#16125A', '#3030C8', '#355CFF', '#7C3AED',
                   '#A78BFA', '#C4B5FD', '#C026D3', '#42D6C4', '#9AEAFF',
                   '#F2F7FF']) {
    assert.ok(colors.indexOf(c) >= 0, 'D: палитра содержит ' + c);
  }
  // Композиция A–D (4 зоны). A/B/C — кластеры, D — «нити» (uniform-share).
  for (const z of ['A', 'B', 'C']) {
    assert.ok(new RegExp("zone: '" + z + "'").test(POLY), 'D: zone ' + z);
  }
  assert.ok(/ZONE_D_UNIFORM_SHARE/.test(POLY) && /Зона D/.test(POLY),
    'D: zone D (соединительные нити)');
  // CSP/zero-build.
  assert.ok(POLY.indexOf('eval(') < 0, 'D: без eval');
  assert.ok(POLY.indexOf('data:image') < 0, 'D: без data-URI');
}

/* ── E. Подключение: vendor-порядок script, no-CDN, app.js-интеграция ────── */
{
  const iDel = INDEX.indexOf('/static/vendor/delaunator.5.0.0.min.js');
  const iPoly = INDEX.indexOf('/static/polygon-background.js');
  const iApp = INDEX.indexOf('/web/app.js');
  const iAurora = INDEX.indexOf('/static/aurora-flow.js');
  assert.ok(iDel >= 0, 'E: delaunator подключён');
  assert.ok(iPoly >= 0, 'E: polygon-background подключён');
  assert.ok(iDel < iPoly && iPoly < iApp, 'E: delaunator → polygon → app.js');
  assert.ok(iAurora >= 0 && iAurora < iPoly,
    'E: aurora-flow.js сохранён (загружается до polygon — legacy-контракт)');
  assert.ok(fs.existsSync(VENDOR), 'E: vendored delaunator на месте');
  assert.ok(INDEX.indexOf('delaunator.5.0.0.min.js?v=__APP_VERSION__') >= 0,
    'E: delaunator с cache-bust ?v=__APP_VERSION__');
  // Никаких CDN-хостов в script src.
  const srcs = INDEX.match(/<script[^>]*\ssrc="([^"]+)"/g) || [];
  for (const s of srcs) {
    assert.ok(s.indexOf('http') < 0, 'E: script без CDN: ' + s);
  }
  // app.js: один активный рендерер (polygon vs legacy Aurora), класс.
  assert.ok(/polygonBgEnabled:\s*function/.test(APP_JS),
    'E: computed polygonBgEnabled');
  assert.ok(/UI_POLYGON_BG_ENABLED/.test(APP_JS), 'E: UI_POLYGON_BG_ENABLED');
  assert.ok(/__PolygonBackground/.test(APP_JS), 'E: app.js → __PolygonBackground');
  assert.ok(/__AuroraFlowLegacy/.test(APP_JS), 'E: app.js → __AuroraFlowLegacy');
  assert.ok(/classList\.toggle\('polygon-bg'/.test(APP_JS),
    'E: html.polygon-bg');
  assert.ok(/__polygonAdapter/.test(APP_JS) || /_legacyAuroraFlow/.test(APP_JS),
    'E: выбор активного рендерера');
  // CSS: единый canvas + вывод Aurora из активного пути.
  assert.ok(/\.polygon-background-canvas \{[\s\S]{0,200}position:\s*fixed/
    .test(CSS), 'E: canvas fixed');
  assert.ok(/\.polygon-background-canvas \{[\s\S]{0,260}pointer-events:\s*none/
    .test(CSS), 'E: pointer-events none');
  assert.ok(/html\.polygon-bg \.aurora-flow-canvas \{ display: none/.test(CSS),
    'E: Aurora-канвас скрыт при polygon-bg');
  assert.ok(/html\.polygon-bg \.aurora-bg \{ display: none/.test(CSS),
    'E: legacy aurora скрыта при polygon-bg');
}

/* ── F. §8 «мерцание свечения» замедлено ровно ×2 (правка владельца) ─────── */
{
  const TAU_STUB = Math.PI * 2;
  const pm = POLY.match(/PULSE_SPEED_MIN\s*=\s*([0-9.]+)/);
  const px = POLY.match(/PULSE_SPEED_MAX\s*=\s*([0-9.]+)/);
  const gs = POLY.match(/GLOW_SHIMMER_SPEED\s*=\s*([0-9.]+)/);
  assert.ok(pm && px && gs,
    'F: константы мерцания свечения (PULSE_SPEED_MIN/MAX, GLOW_SHIMMER_SPEED)');
  const PULSE_SPEED_MIN = parseFloat(pm[1]);
  const PULSE_SPEED_MAX = parseFloat(px[1]);
  const GLOW_SHIMMER_SPEED = parseFloat(gs[1]);
  // Прежние (до правки) базовые скорости: новые РОВНО вдвое медленнее.
  const BASE_PULSE_MIN = 0.05, BASE_PULSE_MAX = 0.15, BASE_SHIMMER = 0.06;
  assert.strictEqual(PULSE_SPEED_MIN * 2, BASE_PULSE_MIN,
    'F: pulse min ×2 == прежние 0.05 rad/s (' + PULSE_SPEED_MIN + ')');
  assert.strictEqual(PULSE_SPEED_MAX * 2, BASE_PULSE_MAX,
    'F: pulse max ×2 == прежние 0.15 rad/s (' + PULSE_SPEED_MAX + ')');
  assert.strictEqual(GLOW_SHIMMER_SPEED * 2, BASE_SHIMMER,
    'F: shimmer ×2 == прежние 0.06 rad/s (' + GLOW_SHIMMER_SPEED + ')');
  // Период = TAU / скорость → удвоился ровно вдвое.
  assert.strictEqual(TAU_STUB / PULSE_SPEED_MIN / (TAU_STUB / BASE_PULSE_MIN), 2,
    'F: период импульсов ×2');
  assert.strictEqual(
    TAU_STUB / GLOW_SHIMMER_SPEED / (TAU_STUB / BASE_SHIMMER), 2,
    'F: период «дыхания» свечения ×2');
  // Использование — через именованные константы (значение явное).
  assert.ok(
    /pulseSp:\s*PULSE_SPEED_MIN\s*\+\s*rng\(\)\s*\*\s*\(PULSE_SPEED_MAX\s*-\s*PULSE_SPEED_MIN\)/
      .test(POLY), 'F: pulseSp вычисляется из констант');
  assert.ok(/Math\.sin\(t \* GLOW_SHIMMER_SPEED \+ cl\.ph\)/.test(POLY),
    'F: «дыхание» свечения использует константу');
  // Прежние «магические» скорости удалены — откат скорости уронит тест.
  assert.ok(!/pulseSp:\s*0\.05\s*\+/.test(POLY),
    'F: прежняя скорость импульсов (0.05) удалена');
  assert.ok(!/Math\.sin\(t \* 0\.06 \+ cl\.ph\)/.test(POLY),
    'F: прежняя скорость «дыхания» (0.06) удалена');
  // НЕ мерцание свечения — НЕ замедлено: движение узлов §9, morph §8.1,
  // дрейф световых центров §8.2.
  assert.ok(/sp1: 0\.10 \+ rng\(\) \* 0\.22/.test(POLY),
    'F: движение узлов §9 (sp1) не тронуто');
  assert.ok(/sp2: 0\.08 \+ rng\(\) \* 0\.18/.test(POLY),
    'F: движение узлов §9 (sp2) не тронуто');
  assert.ok(/return 0\.5 \+ 0\.5 \* Math\.sin\(t \* 0\.06 \+ ph\);/.test(POLY),
    'F: цветовой morph §8.1 не тронут');
  assert.ok(/Math\.sin\(t \* 0\.045 \+ cl\.ph\)/.test(POLY),
    'F: дрейф световых центров §8.2 (x) не тронут');
  assert.ok(/Math\.cos\(t \* 0\.038 \+ cl\.ph \* 1\.3\)/.test(POLY),
    'F: дрейф световых центров §8.2 (y) не тронут');
  // §6.4/SC-15: топология остаётся ≤4 Гц (не часть «мерцания свечения»).
  assert.ok(/TOPO_HZ = 4/.test(POLY), 'F: топология ≤4 Гц не изменена');
}

console.log('POLYGON-LUMINESCENCE-OK');
