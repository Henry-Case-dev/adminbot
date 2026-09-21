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
    '--glass-displace'];
  const actual = tokensOf(CSS);
  const missing = expected.filter((t) => !actual.has(t));
  assert.deepStrictEqual(missing, [],
    'палитра §8: потеряны токены ' + missing.join(', '));
  assert.strictEqual(tokenValue('--surface-0').toUpperCase(), '#090D17');
  assert.strictEqual(tokenValue('--surface-1').toUpperCase(), '#151B2A');
  assert.strictEqual(tokenValue('--text-1').toUpperCase(), '#F4F7FB');
  assert.strictEqual(tokenValue('--text-2').toUpperCase(), '#AAB6C8');
  assert.strictEqual(tokenValue('--teal-500').toUpperCase(), '#42D6C4');
  assert.strictEqual(tokenValue('--purple-500').toUpperCase(), '#A78BFA');
  assert.strictEqual(tokenValue('--indigo-300').toUpperCase(), '#77A8FF');
  assert.strictEqual(tokenValue('--warn').toUpperCase(), '#F6C56F');
  assert.strictEqual(tokenValue('--err').toUpperCase(), '#F07178');
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
  assert.ok(/--glass-displace\s*:\s*url\(#lg-displace\)/.test(CSS),
    'glass: --glass-displace → url(#lg-displace)');
  const a = CSS.match(
    /\[data-glass="a"\]\s*\{([^}]*var\(--glass-displace\)[^}]*)\}/);
  assert.ok(a, 'glass A: применение преломления через токен --glass-displace');
  assert.ok(a[1].indexOf('var(--glass-blur)') >= 0, 'glass A: blur + преломление');
  const c = CSS.match(
    /\[data-glass="c"\][^{]*\{([^}]*backdrop-filter:\s*none[^}]*)\}/);
  assert.ok(c, 'glass C: deny-list без blur (backdrop-filter: none)');
  assert.ok(/textarea[^{]*\{[^}]*backdrop-filter:\s*none/.test(CSS) ||
    /textarea,\s*[\s\S]*?backdrop-filter:\s*none/.test(CSS),
    'glass C: textarea в deny-list');
  assert.ok(CSS.indexOf('@supports not ((backdrop-filter: blur(1px))') >= 0,
    'glass: @supports-фолбэк (уровень C)');
  assert.ok(CSS.indexOf('@supports not ((backdrop-filter: url(#lg-displace))') >= 0,
    'glass: @supports-фолбэк уровня A');
  assert.ok(!/animation:[^;}]*filter/.test(CSS),
    'T-2541: blur/viewport не анимируется');
  assert.ok(CSS.indexOf('.lg-bg-paused') >= 0 &&
    CSS.indexOf('animation-play-state: paused') >= 0,
    'T-2547: пауза фона при document.hidden');
}

// ── 5. Инлайн SVG-фильтр: ровно один, CSP-safe ─────────────────────────────
{
  const count = (INDEX.match(/id="lg-displace"/g) || []).length;
  assert.strictEqual(count, 1, 'SVG: должен быть ровно один фильтр #lg-displace');
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
  // Не нагромождаем обработчиков: visibilitychange объявлен ровно один раз.
  assert.strictEqual((APP_JS.match(/addEventListener\('visibilitychange'/g) || []).length,
    1, 'T-2547: один обработчик visibilitychange');

  // setBgPaused реально переключает класс.
  methods.setBgPaused.call({}, true);
  assert.strictEqual(global.document.documentElement.classList.contains('lg-bg-paused'),
    true, 'setBgPaused(true) → html.lg-bg-paused');
  methods.setBgPaused.call({}, false);
  assert.strictEqual(global.document.documentElement.classList.contains('lg-bg-paused'),
    false, 'setBgPaused(false) → класс снят');

  // Без поддержки url-фильтра (Node — нет window.CSS) уровень A понижается до B.
  const fake = { attr: 'a', setAttribute(k, v) { this.attr = v; } };
  const oldQSA = global.document.querySelectorAll;
  global.document.querySelectorAll = (sel) =>
    sel === '[data-glass="a"]' ? [fake] : [];
  methods.reconcileLiquidGlass.call({ _liquidGlassSupported: methods._liquidGlassSupported });
  global.document.querySelectorAll = oldQSA;
  assert.strictEqual(fake.attr, 'b', 'reconcile: без поддержки → уровень B');
}

console.log('JS-UNIT-OK');
