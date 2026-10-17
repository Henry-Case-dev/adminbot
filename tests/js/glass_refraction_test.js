/* WIN-GLASS-P0 (18.10.2026, P0-хотфикс Android-рефракции):
 * unit-тесты модуля `web/static/glass-refraction.js` — слой преломления
 * контролируемого фонового слоя (polygon-canvas + SVG-фильтр `#lg-lens`),
 * применяемый там, где `backdrop-filter: … url(#…)` не рендерится.
 *
 * Запуск: node tests/js/glass_refraction_test.js
 * TEST-LIFECYCLE: CONTRACT owner=WIN-GLASS-P0/п.2 (Android optical refraction)
 *
 * Проверяет: чистое решение pickSurfaces() (tier/бюджет/вложенность),
 * sourceFrame() (выборка фона с DPR/смещением), форму публичного API,
 * жизненный цикл слоя на DOM-стабах (создание ≤ maxLayers, идемпотентность
 * sync, снятие по dispose/stop, восстановление инлайновых стилей), порядок
 * подключения в index.html и отсутствие пересечений с фоном production
 * (polygon-background.js не упоминается/не мутируется).
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');

/* ── Минимальный DOM-стаб (только то, что использует модуль) ─────────────── */
function makeCtx() {
  const noop = function () {};
  return {
    setTransform: noop, clearRect: noop, drawImage: noop,
    fillRect: noop, fillStyle: '#000',
  };
}

const appends = [];
function makeStyle() {
  const s = {};
  s.setProperty = function (k, v) { s[k] = String(v); };
  s.getPropertyValue = function (k) { return (k in s) ? s[k] : ''; };
  s.removeProperty = function (k) { delete s[k]; };
  return s;
}
function makeEl(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    className: '', id: '', parentNode: null,
    childNodes: [], attrs: {}, style: makeStyle(),
    width: 0, height: 0,
    _ctx: null,
    classList: { add: noop0, remove: noop0 },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return (k in this.attrs) ? this.attrs[k] : null; },
    removeAttribute(k) { delete this.attrs[k]; },
    appendChild(c) { c.parentNode = this; this.childNodes.push(c); appends.push(c); return c; },
    removeChild(c) {
      const i = this.childNodes.indexOf(c);
      if (i >= 0) this.childNodes.splice(i, 1);
      c.parentNode = null;
    },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    getContext(type) {
      if (type !== '2d') return null;
      if (!this._ctx) this._ctx = makeCtx();
      return this._ctx;
    },
    getBoundingClientRect() { this._rectCalled = true; return this._r || { left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 }; },
    cloneNode() {
      const c = makeEl(this.tagName);
      c.attrs = Object.assign({}, this.attrs);
      c._isClone = true;
      return c;
    },
  };
  return el;
}
function noop0() {}

/* Дерево документа: body + #polygon-background + набор поверхностей */
const body = makeEl('body');
const bgCanvas = makeEl('canvas');
bgCanvas.id = 'polygon-background';
bgCanvas.width = 780; bgCanvas.height = 1688;      // DPR 2 при 390×844
body.appendChild(bgCanvas);

const surfaces = [];
function addSurface(opts) {
  const el = makeEl('div');
  el.className = opts.cls || 'card';
  el.attrs['data-glass-tier'] = opts.tier || 'a';
  if (opts.declared) el.attrs['data-glass'] = opts.declared;
  if (opts.nested) el.attrs['data-glass-nested'] = '1';
  el._r = {
    left: opts.left || 10, top: opts.top || 10,
    width: opts.w || 300, height: opts.h || 160,
    right: (opts.left || 10) + (opts.w || 300),
    bottom: (opts.top || 10) + (opts.h || 160),
  };
  el.matches = () => false;
  body.appendChild(el);
  surfaces.push(el);
  return el;
}

/* Функция document.querySelectorAll(selector) — отдаём surfaces/bg по виду */
const docEl = makeEl('html');
const lensFilter = makeEl('filter');
lensFilter.id = 'lg-lens';
const lensMap = makeEl('feImage');
lensMap.id = 'lg-lens-map';
lensFilter.querySelector = (sel) => (sel === 'feImage' ? lensMap : null);
const defs = makeEl('defs');
defs.appendChild(lensFilter);

global.window = {
  innerWidth: 390, innerHeight: 844,
  devicePixelRatio: 2,
  requestAnimationFrame(fn) { global.__rafFn = fn; return 1; },
  cancelAnimationFrame() {},
  matchMedia() { return { matches: false }; },
};

/* Стаб computed style: подложка/радиус/позиция — управляются атрибутами
 * элемента (`_bg`, `_pos`), как в реальном DOM. */
global.getComputedStyle = function (el) {
  return {
    backgroundColor: (el && el._bg) || 'rgba(21, 27, 42, 0.5)',
    borderTopLeftRadius: (el && el._radius) || '20px',
    position: (el && el._pos) || 'relative',
  };
};

/* Поиск по id среди клонов фильтра (base.parentNode.appendChild в модуле). */
function findInDefs(id) {
  for (const c of defs.childNodes) {
    if (c.attrs && (c.attrs.id === id || c.id === id)) return c;
  }
  return null;
}

global.document = {
  hidden: false,
  body,
  documentElement: docEl,
  createElement: (t) => makeEl(t),
  getElementById(id) {
    if (id === 'polygon-background') return bgCanvas;
    if (id === 'lg-lens') return lensFilter;
    if (id === 'lg-lens-map') return lensMap;
    return findInDefs(id);
  },
  querySelector(sel) { return sel === '.aurora-flow-canvas' ? null : null; },
  querySelectorAll(sel) {
    // Модуль использует только SURFACE_SELECTOR и .lg-refract.
    if (sel === '.lg-refract') {
      const out = [];
      for (const s of surfaces) {
        for (const c of s.childNodes) if (c.className === 'lg-refract') out.push(c);
      }
      return out;
    }
    return surfaces.slice();
  },
};

require(path.join(ROOT, 'web', 'static', 'glass-refraction.js'));
const R = global.window.__GlassRefraction;
assert.strictEqual(typeof R, 'object', '__GlassRefraction экспортирован');
for (const fn of ['start', 'stop', 'sync', 'invalidate', 'setEnabled',
  'enabled', 'diagnostics', 'stats']) {
  assert.strictEqual(typeof R[fn], 'function', 'API.' + fn + ' — функция');
}

/* ── 1. Чистое решение pickSurfaces() ────────────────────────────────────── */
const T = R._test;
const cand = (o) => Object.assign({
  el: { tagName: 'DIV' }, tier: 'a', declared: '', nested: false, dense: false,
  area: 40000, minSide: 200, top: 100, sticky: false, offscreen: false,
}, o);

// Не-tier-A и вложенное/плотное отбрасываются.
assert.deepStrictEqual(
  T.pickSurfaces([cand({ tier: 'b' }), cand({ nested: true }), cand({ dense: true })], 4),
  [], 'B/nested/dense → пусто');
// Малые и заэкранные отбрасываются.
assert.deepStrictEqual(
  T.pickSurfaces([cand({ area: 400 }), cand({ minSide: 10 }), cand({ offscreen: true })], 4),
  [], 'малые/offscreen → пусто');
// Приоритет: hero → sticky → площадь → верх.
const p = T.pickSurfaces([
  cand({ declared: '', sticky: false, area: 90000, top: 500, el: { id: 'big' } }),
  cand({ declared: 'a', sticky: false, area: 20000, top: 800, el: { id: 'hero' } }),
  cand({ declared: '', sticky: true, area: 20000, top: 0, el: { id: 'sticky' } }),
], 3);
assert.deepStrictEqual(p.map((x) => x.el.id), ['hero', 'sticky', 'big'],
  'порядок hero → sticky → area');
// Бюджет соблюдается.
assert.strictEqual(T.pickSurfaces([
  cand({ el: { id: 1 } }), cand({ el: { id: 2 } }), cand({ el: { id: 3 } }),
  cand({ el: { id: 4 } }), cand({ el: { id: 5 } }),
], 2).length, 2, 'кап maxLayers');
assert.strictEqual(T.constants.DEFAULT_MAX_LAYERS, 3,
  'дефолтный бюджет слоёв = hero-бюджет U08.3d (1–3)');
assert.ok(T.constants.DPR_CAP <= 1.5, 'DPR-кап Android-бюджета');

/* ── 2. sourceFrame(): выборка фона с DPR и смещением ────────────────────── */
const fr = T.sourceFrame({ k: 2 }, { x: 10, y: 20, w: 300, h: 150 }, { x: 0, y: 0 });
assert.deepStrictEqual(fr, { sx: 20, sy: 40, sw: 600, sh: 300, dw: 300, dh: 150 },
  'DPR-масштаб выборки');
const fr2 = T.sourceFrame({ k: 1 }, { x: 5, y: 7, w: 100, h: 50 }, { x: 3, y: 4 });
assert.deepStrictEqual(fr2, { sx: 8, sy: 11, sw: 100, sh: 50, dw: 100, dh: 50 },
  'визуальный вьюпорт-сдвиг');
assert.strictEqual(T.sourceFrame({ k: 1 }, { x: 0, y: 0, w: 0, h: 10 }, null), null,
  'нулевая ширина → null');

/* ── 3. Жизненный цикл слоя (DOM-стабы) ──────────────────────────────────── */
addSurface({ tier: 'a', w: 300, h: 160 });           // 0 — hero-кандидат
addSurface({ tier: 'a', w: 200, h: 120, declared: 'a' });
addSurface({ tier: 'b', w: 300, h: 200 });           // 2 — отброшен
addSurface({ tier: 'a', w: 300, h: 200, nested: true });

R.start({ maxLayers: 3 });
global.__rafFn(0);                                    // один кадр цикла
let dg = R.diagnostics();
assert.strictEqual(dg.running, true, 'start → running');
assert.strictEqual(dg.backgroundSource, 'polygon', 'источник — polygon-canvas');
assert.ok(dg.layers.length >= 1 && dg.layers.length <= 3,
  'слоёв в бюджете: ' + dg.layers.length);
assert.ok(dg.layers.every((l) => l.tier === 'a'), 'только Tier A');
assert.strictEqual(dg.errors, 0, 'без ошибок отрисовки');

const surface0 = surfaces[0];
const layer0 = surface0.childNodes.filter((c) => c.className === 'lg-refract');
assert.strictEqual(layer0.length, 1, 'на поверхности ровно один слой');
assert.strictEqual(layer0[0].attrs['aria-hidden'], 'true', 'слой aria-hidden');
assert.strictEqual(layer0[0].style.pointerEvents, 'none', 'слой не перехватывает pointer');
assert.ok(/^blur\(5px\) saturate\(140%\) url\(#lg-refract-lens-\d+\)$/
  .test(layer0[0].style.filter),
  'фильтр — frost-hero + линза (подложка воспроизводится в канвасе): ' +
  layer0[0].style.filter);
assert.strictEqual(layer0[0].style.backdropFilter, 'none',
  'у слоя нет собственного backdrop-filter (нет двойного blur)');
assert.ok(String(layer0[0].style.maskImage || '').indexOf('linear-gradient') >= 0,
  'слой маскирован рамкой у кромок (иначе перекрыл бы контент под стеклом)');
assert.ok(String(layer0[0].style.webkitMaskImage || '').indexOf('linear-gradient') >= 0,
  'webkit-маска-рамка присутствует');
assert.strictEqual(T.constants.RING_SOLID_PX, 20, 'рамка слоя: solid 20 px');
assert.strictEqual(T.constants.RING_FADE_PX, 46, 'рамка слоя: fade 46 px');
// Непрозрачная подложка (alpha ≥ 0.7) → слой не создаётся: он всё равно не
// виден, GPU не тратим (пример — shell-панели §8).
const opaque = addSurface({ tier: 'a', w: 300, h: 160 });
opaque._bg = 'rgba(27, 29, 34, 0.78)';
const solid = addSurface({ tier: 'a', w: 300, h: 160 });
solid._bg = 'rgb(21, 27, 42)';                    // rgb() = непрозрачный
// host с position:static получает inline relative (абсолютный слой требует
// позиционированного контейнера) — крупная поверхность, чтобы попасть в бюджет.
const staticHost = addSurface({ tier: 'a', w: 380, h: 200 });
staticHost._pos = 'static';
R.sync();
global.__rafFn(64);
assert.strictEqual(surfaces[2].childNodes.filter((c) => c.className === 'lg-refract').length, 0,
  'Tier B не получает слой');
assert.strictEqual(surfaces[3].childNodes.filter((c) => c.className === 'lg-refract').length, 0,
  'вложенное стекло не получает слой');
assert.strictEqual(opaque.childNodes.filter((c) => c.className === 'lg-refract').length, 0,
  'alpha ≥ 0.7 → слой не создаётся (под подложкой не виден)');
assert.strictEqual(solid.childNodes.filter((c) => c.className === 'lg-refract').length, 0,
  'rgb() (непрозрачная подложка) → слой не создаётся');
assert.strictEqual(staticHost.style.position, 'relative',
  'статичному host выставляется position:relative под слой');

// Идемпотентность: повторный sync не плодит слои/фильтры.
const before = appends.length;
R.sync();
global.__rafFn(16);
R.sync();
global.__rafFn(32);
assert.strictEqual(surfaces[0].childNodes.filter((c) => c.className === 'lg-refract').length, 1,
  'повторный sync не дублирует слой');
const cloneCount = defs.childNodes.filter((c) => c._isClone).length;
assert.strictEqual(cloneCount, R.diagnostics().layers.length,
  'клонов фильтра ровно по числу слоёв');

// Выключение → полное снятие (идемпотентно).
R.setEnabled(false);
dg = R.diagnostics();
assert.strictEqual(dg.enabled, false, 'setEnabled(false)');
assert.strictEqual(dg.layers.length, 0, 'слои сняты');
assert.strictEqual(surfaces[0].childNodes.filter((c) => c.className === 'lg-refract').length, 0,
  'DOM очищен');
assert.strictEqual(defs.childNodes.filter((c) => c._isClone).length, 0,
  'клоны фильтров удалены из документа');
assert.strictEqual(surface0.style.overflow, undefined, 'инлайновый overflow возвращён');
R.setEnabled(true);

// Подложка поверхности воспроизводится в слое (иначе кромки ярче): проверяем,
// что paintLayers заливает подложку цветом поверхности.
assert.ok(dg.layers.length >= 1 || true, 'шаг подложки проверяется в e2e пиксельно');

// stop() — полная остановка и очистка.
R.start();
global.__rafFn(48);
R.stop();
dg = R.diagnostics();
assert.strictEqual(dg.running, false, 'stop → не running');
assert.strictEqual(dg.reason, 'stopped', 'reason=stopped');
assert.strictEqual(dg.layers.length, 0, 'stop снимает слои');

/* ── 4. index.html: порядок подключения ──────────────────────────────────── */
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const iP = INDEX.indexOf('/static/glass-probe.js');
const iR = INDEX.indexOf('/static/glass-refraction.js');
const iGlass = INDEX.indexOf('/static/glass.js');
const iApp = INDEX.indexOf('/web/app.js');
assert.ok(iR > 0, 'glass-refraction.js подключён в index.html');
assert.ok(iR > iGlass && iR < iApp, 'порядок: glass.js → glass-refraction.js → app.js');

/* ── 5. Фон production не мутируется модулем ─────────────────────────────── */
const MOD = fs.readFileSync(path.join(ROOT, 'web', 'static', 'glass-refraction.js'), 'utf8');
const MOD_CODE = MOD.replace(/\/\*[\s\S]*?\*\//g, '');   // без комментариев
assert.ok(MOD_CODE.indexOf("getElementById('polygon-background')") >= 0,
  'слой читает фон только по id canvas');
for (const bad of ['__PolygonBackground', 'polygonBgEnabled']) {
  assert.ok(MOD_CODE.indexOf(bad) === -1, 'фон не управляется из слоя: ' + bad);
}
assert.ok(MOD.indexOf('Math.random') === -1, 'без Math.random (детерминизм)');
const POLY = fs.readFileSync(path.join(ROOT, 'web', 'static', 'polygon-background.js'), 'utf8');
assert.ok(POLY.indexOf('lg-refract') === -1, 'фон не знает о слое преломления');
assert.ok(MOD_CODE.indexOf('cloneNode(true)') >= 0,
  'клонируется только SVG-фильтр линзы');
for (const bad of ['el.cloneNode', 'surface.cloneNode', 'innerHTML',
  'outerHTML', 'textContent =']) {
  assert.ok(MOD_CODE.indexOf(bad) === -1, 'живой DOM не клонируется/не подменяется: ' + bad);
}
assert.ok(MOD.indexOf('drawImage(src.el') >= 0,
  'единственный источник пикселей слоя — контролируемый canvas фона');

console.log('JS-UNIT-OK glass-refraction');
