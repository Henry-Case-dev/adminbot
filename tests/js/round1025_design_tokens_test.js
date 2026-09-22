'use strict';
/* F2 round 10.25 — регресс-зонды дизайн-системы: палитра §8, Liquid Glass
 * A/B/C §9, фон §10 (T-2531…T-2550, ADR-1025-9).
 *
 * Покрытие:
 *   1. Палитра §8: токены (множество имён) + значения surface/text/accents/status.
 *   2. Отсутствие OD4-литералов в first-party web/** (vendor исключён).
 *   3. Фон §10: --grad-speed ∈ [60,90]s, --grad-speed-slow ∈ [90,120]s, нет 6s.
 *   4. Liquid Glass: --glass-displace → url(#lg-displace); [data-glass="a"]
 *      allow, [data-glass="c"]/textarea deny; @supports-фолбэки; нет анимации blur.
 *   5. Инлайн SVG-фильтр: ровно один id="lg-displace" + feDisplacementMap.
 *   6. app.js: reconcileLiquidGlass (min-сторона ≥240), setBgPaused (класс).
 *
 * Запуск: node tests/js/round1025_design_tokens_test.js   (печатает JS-UNIT-OK)
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component() {}, provide() {}, use() {}, mount() {},
    };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
global.document = {
  addEventListener() {}, getElementById() { return null; },
  querySelectorAll() { return []; },
  documentElement: {
    classList: {
      _s: {},
      toggle(name, on) { this._s[name] = !!on; },
      contains(name) { return !!this._s[name]; },
    },
  },
};
global.history = { replaceState() {} };
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;

const INDEX = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
const CSS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'static', 'app.css'), 'utf8');

function tokensOf(css) {
  const out = new Set();
  const re = /(--[\w-]+)\s*:/g;
  let m;
  while ((m = re.exec(css))) out.add(m[1]);
  return out;
}
function tokenValue(name) {
  const m = CSS.match(new RegExp(name + '\\s*:\\s*([^;]+);'));
  return m ? m[1].trim() : '';
}
function firstPartyWeb() {
  const root = path.join(__dirname, '..', '..', 'web');
  const out = {};
  (function walk(dir) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== 'vendor') walk(p); continue; }
      if (!/\.(css|js|html)$/i.test(e.name)) continue;
      out[p] = fs.readFileSync(p, 'utf8');
    }
  })(root);
  return out;
}

const OD4 = ['#0E0E0E', '#161616', '#1F1F1F', '#262626', '#F5F5F5', '#BABABA',
  '#9E9E9E', '#14CBB6', '#12B7A4', '#664EA0', '#8D6BDC', '#A78DE4', '#A91443',
  '#C25879', '#D9CDF3', '#16B364', '#EAAA08', '#FF4848', '#FF8A3D',
  'rgba(20, 25, 30', 'rgba(20,25,30', 'rgba(22, 22, 22', 'rgba(22,22,22',
  'rgba(20, 203, 182', 'rgba(20,203,182'];

// ── 1. Палитра §8 (множество + значения) ───────────────────────────────────
{
  const expected = ['--surface-0', '--surface-1', '--surface-2', '--surface-3',
    '--text-1', '--text-2', '--text-3', '--teal-500', '--purple-500',
    '--indigo-300', '--ok', '--warn', '--err', '--grad-a', '--grad-b',
    '--grad-c', '--grad-d', '--grad-speed', '--grad-speed-slow',
    '--glass-bg', '--glass-bg-strong', '--glass-blur', '--glass-border',
    '--glass-displace', '--err-text'];
  const actual = tokensOf(CSS);
  const missing = expected.filter((t) => !actual.has(t));
  assert.deepStrictEqual(missing, [],
    'палитра §8: потеряны токены ' + missing.join(', '));
  assert.strictEqual(tokenValue('--surface-0').toUpperCase(), '#090D17');
  assert.strictEqual(tokenValue('--surface-1').toUpperCase(), '#151B2A');
  assert.strictEqual(tokenValue('--text-1').toUpperCase(), '#F4F7FB');
  assert.strictEqual(tokenValue('--text-2').toUpperCase(), '#AAB6C8');
  assert.strictEqual(tokenValue('--text-3').toUpperCase(), '#A2B0C6');
  assert.strictEqual(tokenValue('--glass-bg').replace(/\s/g, ''),
    'rgba(21,27,42,0.5)');
  assert.strictEqual(tokenValue('--teal-500').toUpperCase(), '#42D6C4');
  assert.strictEqual(tokenValue('--purple-500').toUpperCase(), '#A78BFA');
  assert.strictEqual(tokenValue('--indigo-300').toUpperCase(), '#77A8FF');
  assert.strictEqual(tokenValue('--warn').toUpperCase(), '#F6C56F');
  assert.strictEqual(tokenValue('--err').toUpperCase(), '#F07178');
  assert.strictEqual(tokenValue('--err-text').toUpperCase(), '#FCA5A5');
}

// ── 1a. D-1/@Reviewer: Tailwind-утилиты 12px в стекле ≥4.5:1 ────────────────
{
  const map = { '.text-gray-500': '--text-3', '.text-gray-600': '--text-3',
    '.text-gray-400': '--text-2', '.text-red-400': '--err-text' };
  for (const [cls, tok] of Object.entries(map)) {
    const re = new RegExp(cls.replace(/\./g, '\\.') +
      '\\s*(?:,[^{]*)?\\{[^}]*color:\\s*var\\(' + tok + '\\)');
    assert.ok(re.test(CSS), 'D-1: ' + cls + ' → var(' + tok + ')');
  }
  // app.css идёт после tailwind.css → равная специфичность, выигрывает наше правило.
  assert.ok(INDEX.indexOf('/static/app.css') > INDEX.indexOf('tailwind.css'),
    'D-1: app.css после tailwind.css');
}

// ── 1b. Симметричный инвентарь (D5/@Reviewer): пропажи И лишние маркеры ─────
{
  const prefixes = ['--surface-', '--text-', '--grad-', '--glass-', '--teal-',
    '--purple-', '--indigo-', '--magenta-', '--lilac-'];
  const status = ['--ok', '--warn', '--err', '--err-text', '--ok-bg',
    '--warn-bg', '--err-bg'];
  const expectedInv = new Set(['--surface-0', '--surface-1', '--surface-2',
    '--surface-3', '--surface-border', '--surface-glass', '--text-1', '--text-2',
    '--text-3', '--grad-a', '--grad-b', '--grad-c', '--grad-d', '--grad-angle',
    '--grad-ease', '--grad-speed', '--grad-speed-slow', '--glass-bg',
    '--glass-bg-strong', '--glass-blur', '--glass-border',
    '--glass-border-color', '--glass-displace', '--glass-highlight',
    '--glass-highlight-soft', '--glass-shadow',
    // HOTFIX10 (ADR-1025-18 D1): тема frosted-слоя GlassSurface (dark paper/ink
    // вместо белого дефолта библиотеки) — контракт, не новая палитра.
    '--glass-paper', '--glass-ink', '--teal-500', '--teal-600',
    '--purple-400', '--purple-500', '--indigo-300', '--magenta-400',
    '--magenta-600', '--lilac-200', ...status]);
  const actualInv = new Set([...tokensOf(CSS)].filter((t) =>
    prefixes.some((p) => t.indexOf(p) === 0) || status.indexOf(t) >= 0));
  const extra = [...actualInv].filter((t) => !expectedInv.has(t));
  const missing = [...expectedInv].filter((t) => !actualInv.has(t));
  assert.deepStrictEqual({ extra, missing }, { extra: [], missing: [] },
    'инвентарь: лишние=' + extra.join(',') + ' пропавшие=' + missing.join(','));
}

// ── 2. Отсутствие OD4-литералов (absence, сравнение множеств) ──────────────
{
  const files = firstPartyWeb();
  const found = {};
  for (const [p, text] of Object.entries(files)) {
    const hits = OD4.filter((lit) => text.indexOf(lit) >= 0);
    if (hits.length) found[p] = hits;
  }
  assert.deepStrictEqual(found, {},
    'остаточные OD4-литералы: ' + JSON.stringify(found));
}

// ── 3. Фон §10: длительности и отсутствие оранжевой зоны ───────────────────
{
  const m = CSS.match(/--grad-speed\s*:\s*([\d.]+)s/);
  assert.ok(m && +m[1] >= 60 && +m[1] <= 90,
    'F2/T-2544: --grad-speed ∈ [60,90]s (' + (m && m[1]) + ')');
  const s = CSS.match(/--grad-speed-slow\s*:\s*([\d.]+)s/);
  assert.ok(s && +s[1] >= 90 && +s[1] <= 120,
    'F2/T-2544: --grad-speed-slow ∈ [90,120]s (' + (s && s[1]) + ')');
  assert.ok(CSS.indexOf('--grad-speed:6s') < 0, 'фон: 6s заменён');
  assert.ok(CSS.indexOf('grad-drift var(--grad-speed-slow)') >= 0,
    'фон: вторичный слой на --grad-speed-slow');
  assert.ok(CSS.indexOf('#FF8A3D') < 0, 'фон: оранжевый стоп удалён');
  assert.ok(CSS.indexOf('@property --grad-angle') >= 0 &&
    CSS.indexOf('@keyframes grad-spin') >= 0 &&
    CSS.indexOf('@keyframes grad-drift') >= 0,
    'фон: механика угла сохранена (D3)');
  assert.ok(/animation:[^;}]*grad-spin var\(--grad-speed\) linear infinite/.test(CSS),
    'фон: grad-spin на основном токене');
}

// ── 4. Liquid Glass A/B/C + фолбэки + нет анимации blur ────────────────────
{
  assert.ok(CSS.indexOf('--glass-bg: rgba(21, 27, 42, 0.5)') >= 0,
    'glass: --glass-bg §8');
  // AMEND ADR-1025-12 D1: токен указывает на foreground-фильтр линзы #lg-lens.
  assert.ok(/--glass-displace\s*:\s*url\(#lg-lens\)/.test(CSS),
    'glass: --glass-displace → url(#lg-lens)');
  // A: базовая подложка — blur (без url()), линза — отдельный ::before.
  const a = CSS.match(/\[data-glass="a"\]\s*\{([^}]*)\}/);
  assert.ok(a, 'glass A: базовое правило [data-glass="a"]');
  assert.ok(a[1].indexOf('var(--glass-blur)') >= 0, 'glass A: blur-подложка');
  assert.ok(!/url\(#lg-lens\)/.test(a[1]), 'glass A: url() НЕ на backdrop');
  const lens = CSS.match(/\[data-glass="a"\]::before\s*\{([^}]*)\}/);
  assert.ok(lens, 'glass A: foreground-линза ::before');
  assert.ok(lens[1].indexOf('var(--glass-displace)') >= 0,
    'линза: filter → --glass-displace');
  assert.ok(/radial-gradient/.test(lens[1]) && /mask-image/.test(lens[1]),
    'edge-weighted: радиальная маска линзы');
  assert.ok(/z-index:\s*-1/.test(lens[1]), 'линза под контентом (z-index:-1)');
  // §9/инвариант: нигде в web/** не опираемся на backdrop url-фильтр.
  assert.ok(!/backdrop-filter\s*:\s*url\(/.test(CSS),
    'нет backdrop url-фильтра (инвариант §9)');
  const c = CSS.match(
    /\[data-glass="c"\][^{]*\{([^}]*backdrop-filter:\s*none[^}]*)\}/);
  assert.ok(c, 'glass C: deny-list без blur (backdrop-filter: none)');
  assert.ok(/textarea[^{]*\{[^}]*backdrop-filter:\s*none/.test(CSS) ||
    /textarea,\s*[\s\S]*?backdrop-filter:\s*none/.test(CSS),
    'glass C: textarea в deny-list');
  assert.ok(CSS.indexOf('@supports not ((backdrop-filter: blur(1px))') >= 0,
    'glass: @supports-фолбэк (уровень C)');
  // A2/T-2591: панели входят в fallback-набор (непрозрачная подложка).
  assert.ok(/\.app-sidebar[^{]*\.bottom-nav[\s\S]{0,400}backdrop-filter:\s*none/
    .test(CSS) || (CSS.indexOf('.app-sidebar, .app-drawer') >= 0),
    'панели в fallback-наборе уровня C');
  assert.ok(!/animation:[^;}]*filter/.test(CSS),
    'T-2541: blur/viewport не анимируется');
  assert.ok(CSS.indexOf('.lg-bg-paused') >= 0 &&
    CSS.indexOf('animation-play-state: paused') >= 0,
    'T-2547: пауза фона при document.hidden');
}

// ── 5. Инлайн SVG-фильтр: ровно один, CSP-safe ─────────────────────────────
{
  const count = (INDEX.match(/id="lg-lens"/g) || []).length;
  assert.strictEqual(count, 1, 'SVG: должен быть ровно один фильтр #lg-lens');
  assert.ok(INDEX.indexOf('feDisplacementMap') >= 0, 'SVG: feDisplacementMap');
  assert.ok(INDEX.indexOf('feTurbulence') >= 0 && INDEX.indexOf('feGaussianBlur') >= 0,
    'SVG: оптическая карта (turbulence + blur), не чистый шум');
  assert.ok(INDEX.indexOf('data-glass="a"') >= 0, 'allow-list: data-glass="a"');
  assert.ok(INDEX.indexOf('data-glass="c"') >= 0, 'deny-list: data-glass="c"');
}

// ── 6. app.js: reconcileLiquidGlass + setBgPaused ──────────────────────────
{
  assert.strictEqual(typeof methods.reconcileLiquidGlass, 'function',
    'T-2540: reconcileLiquidGlass — метод');
  assert.strictEqual(typeof methods.setBgPaused, 'function',
    'T-2547: setBgPaused — метод');
  assert.strictEqual(typeof methods._liquidGlassSupported, 'function',
    'T-2540: _liquidGlassSupported — метод');
  assert.strictEqual(typeof methods._initLiquidGlassObserver, 'function',
    'T-2540/@Reviewer: _initLiquidGlassObserver — метод (транзитивность)');
  // D-2/@Reviewer: троттлинг + ранний выход + scope + ResizeObserver.
  assert.strictEqual(typeof methods._lgSchedule, 'function',
    'D-2: _lgSchedule — метод (троттлинг)');
  assert.ok(APP_JS.indexOf('250') >= 0, 'D-2: троттлинг ≥250 мс');
  assert.ok(/getElementById\('app'\)/.test(APP_JS), 'D-2: observer на #app');
  assert.ok(APP_JS.indexOf('ResizeObserver') >= 0, 'D-2: ResizeObserver на allow');
  assert.ok(/document\.hidden\)\s*return/.test(APP_JS), 'D-2: ранний выход при hidden');
  // Не нагромождаем обработчиков: visibilitychange объявлен ровно один раз.
  assert.strictEqual((APP_JS.match(/addEventListener\('visibilitychange'/g) || []).length,
    1, 'T-2547: один обработчик visibilitychange');
  // reconcile не переписывает opt-in-декларацию data-glass (обратимость b→a).
  assert.ok(APP_JS.indexOf("setAttribute('data-glass', 'b')") < 0,
    'reconcile: data-glass (opt-in) не переписывается');
  // AMEND ADR-1025-12 D1: tier — feature-detect `filter:url(#lg-lens)` + перф-кап;
  // UA-gate Blink-only и min-240 сняты.
  assert.ok(APP_JS.indexOf("css.supports('filter', 'url(#lg-lens)')") >= 0,
    'feature-detect filter:url(#lg-lens)');
  assert.ok(APP_JS.indexOf('AppleWebKit') < 0, 'UA-gate снят (AMEND ADR-1025-12)');
  assert.ok(APP_JS.indexOf('data-glass-tier') >= 0 &&
    APP_JS.indexOf('data-glass-reason') >= 0,
    'T-2583: R17-safe маркер tier/reason');
  assert.strictEqual(typeof methods._lensMaxNodes, 'function',
    'T-2585: перф-кап UI_LENS_MAX_NODES');

  // setBgPaused реально переключает класс.
  methods.setBgPaused.call({}, true);
  assert.strictEqual(global.document.documentElement.classList.contains('lg-bg-paused'),
    true, 'setBgPaused(true) → html.lg-bg-paused');
  methods.setBgPaused.call({}, false);
  assert.strictEqual(global.document.documentElement.classList.contains('lg-bg-paused'),
    false, 'setBgPaused(false) → класс снят');

  // T-2585: tier-лестница feature-detect + кап (без min-стороны), обратимо.
  const mkEl = (w, h) => ({
    _attrs: {},
    getBoundingClientRect: () => ({ width: w, height: h }),
    setAttribute(k, v) { this._attrs[k] = v; },
    removeAttribute(k) { delete this._attrs[k]; },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k); },
  });
  const oldQSA = global.document.querySelectorAll;
  const el1 = mkEl(320, 400), el2 = mkEl(200, 300);
  global.document.querySelectorAll = (sel) =>
    sel === '[data-glass="a"]' ? [el1, el2] : [];
  const fake = (sup, cap, ovr, rm) => ({
    _liquidGlassSupported: () => sup,
    _glassTierOverride: () => ovr || 'auto',
    _lensMaxNodes: () => cap,
    _prefersReducedMotion: () => !!rm,
  });
  methods.reconcileLiquidGlass.call(fake(true, 6));
  assert.strictEqual(el1.hasAttribute('data-glass-downgraded'), false,
    'поддержка+бюджет → A (без min-стороны)');
  assert.strictEqual(el1._attrs['data-glass-tier'], 'a', 'маркер tier=a');
  assert.strictEqual(el2._attrs['data-glass-tier'], 'a', 'оба в капе → A');
  // Нет поддержки → честный B (не «пустое стекло»).
  methods.reconcileLiquidGlass.call(fake(false, 6));
  assert.strictEqual(el1.hasAttribute('data-glass-downgraded'), true,
    'нет поддержки filter:url() → B');
  assert.strictEqual(el1._attrs['data-glass-reason'], 'filter-unsupported',
    'причина: filter-unsupported');
  // Перф-кап: maxNodes=1 → второй узел в B.
  methods.reconcileLiquidGlass.call(fake(true, 1));
  assert.strictEqual(el1.hasAttribute('data-glass-downgraded'), false, 'кап: 1-й = A');
  assert.strictEqual(el2.hasAttribute('data-glass-downgraded'), true, 'кап: 2-й = B');
  assert.strictEqual(el2._attrs['data-glass-reason'], 'budget', 'причина: budget');
  // reduced-motion → B.
  methods.reconcileLiquidGlass.call(fake(true, 6, 'auto', true));
  assert.strictEqual(el1._attrs['data-glass-reason'], 'reduced-motion',
    'reduced-motion → B');
  // override=b → все B (ручной откат).
  methods.reconcileLiquidGlass.call(fake(true, 6, 'b'));
  assert.strictEqual(el1.hasAttribute('data-glass-downgraded'), true, 'override=b → B');
  assert.strictEqual(el1._attrs['data-glass-reason'], 'override-b', 'override-b');
  global.document.querySelectorAll = oldQSA;

  // Feature-detect: WebKit-подобный движок тоже получает A, если умеет
  // filter:url() — UA-gate Blink-only снят.
  const oldWin = global.window;
  try {
    global.window = { CSS: { supports: (prop) => prop === 'filter' } };
    assert.strictEqual(methods._liquidGlassSupported.call({}), true,
      'feature-detect: filter:url() поддержан → A (без UA-gate)');
    global.window = { CSS: { supports: () => false } };
    assert.strictEqual(methods._liquidGlassSupported.call({}), false,
      'feature-detect: нет поддержки → B');
    global.window = {};
    assert.strictEqual(methods._liquidGlassSupported.call({}), false,
      'нет CSS.supports → B (guard)');
  } finally {
    global.window = oldWin;
  }
}

console.log('JS-UNIT-OK');
