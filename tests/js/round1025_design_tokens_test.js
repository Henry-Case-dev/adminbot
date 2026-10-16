'use strict';
/* F2 round 10.25 — регресс-зонды дизайн-системы: палитра §8, Liquid Glass
 * A/B/C §9, фон §10 (T-2531…T-2550, ADR-1025-9).
 *
 * Покрытие:
 *   1. Палитра §8: токены (множество имён) + значения surface/text/accents/status.
 *   2. Отсутствие OD4-литералов в first-party web/** (vendor исключён).
 *   3. Фон §10: --grad-speed ∈ [60,90]s, --grad-speed-slow ∈ [90,120]s, нет 6s.
 *   4. Liquid Glass — re-pin v6.3 U08 (REQ-U08-*): Tier B — var(--lg-frost)/
 *      var(--lg-frost-hero); Tier A url(#lg-lens) только на probe-гейте
 *      [data-glass-tier="a"]; мёртвый --glass-displace удалён владельцем;
 *      [data-glass="a"] allow, [data-glass="c"]/textarea deny; нет анимации blur.
 *   5. Инлайн SVG-фильтр: ровно один id="lg-lens" (feImage PNG-карта +
 *      feDisplacementMap; feTurbulence/feGaussianBlur-вариант удалён U08).
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
    // re-pin v6.3 U08 (REQ-U08-2): --glass-displace удалён; канон смещения —
    // семейство --lg-* (presence-маркеры нового слоя).
    '--err-text', '--lg-frost', '--lg-frost-hero'];
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
  // re-pin v6.3 U08 (REQ-U08-2): семейство --lg-* — новый канон Liquid
  // Glass; инвентарь-симметрия покрывает и его (пропажи и лишние маркеры).
  const prefixes = ['--surface-', '--text-', '--grad-', '--glass-', '--lg-',
    '--teal-', '--purple-', '--indigo-', '--magenta-', '--lilac-'];
  const status = ['--ok', '--warn', '--err', '--err-text', '--ok-bg',
    '--warn-bg', '--err-bg'];
  const expectedInv = new Set(['--surface-0', '--surface-1', '--surface-2',
    '--surface-3', '--surface-border', '--surface-glass', '--text-1', '--text-2',
    '--text-3', '--grad-a', '--grad-b', '--grad-c', '--grad-d', '--grad-angle',
    '--grad-ease', '--grad-speed', '--grad-speed-slow', '--glass-bg',
    '--glass-bg-strong', '--glass-blur', '--glass-border',
    '--glass-border-color', '--glass-highlight',
    '--glass-highlight-soft', '--glass-shadow',
    // HOTFIX10 (ADR-1025-18 D1): тема frosted-слоя GlassSurface (dark paper/ink
    // вместо белого дефолта библиотеки) — контракт, не новая палитра.
    '--glass-paper', '--glass-ink', '--teal-500', '--teal-600',
    '--purple-400', '--purple-500', '--indigo-300', '--magenta-400',
    '--magenta-600', '--lilac-200',
    // re-pin v6.3 U08 (REQ-U08-2): канон Liquid Glass v2 (--lg-*).
    '--lg-fringe', '--lg-frost', '--lg-frost-hero', '--lg-radius',
    '--lg-radius-hero', '--lg-radius-solid', '--lg-rim', '--lg-ring-mask',
    '--lg-shadow', '--lg-specular-arc', '--lg-specular-soft',
    '--lg-tint-hero', '--lg-tint-soft', ...status]);
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
  // re-pin v6.3 U08 (REQ-U08-2): мёртвый --glass-displace удалён владельцем
  // (SUPERSEDE AMEND ADR-1025-12 D1); канон смещения — backdrop-слой Tier A
  // с url(#lg-lens) (ниже) и семейство --lg-*.
  assert.ok(CSS.indexOf('--glass-displace') < 0,
    'glass: --glass-displace удалён (U08)');
  assert.ok(/--lg-frost-hero\s*:\s*blur\(5px\)\s*saturate\(140%\)/.test(CSS),
    'glass: --lg-frost-hero объявлен (U08)');
  // W2-GLASS U08.3 (SUPERSEDE AMEND ADR-1025-12 D1): реальная рефракция —
  // backdrop-слой Tier A с url(#lg-lens); форграунд-линза ::before с
  // filter:url() удалена как декорация (U08.1). CSS-код без комментариев.
  const cssCode = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
  const aBlocks = CSS.match(/\[data-glass="a"\]\s*\{([^}]*)\}/g) || [];
  const a = aBlocks.map((b) => b).find((b) => b.indexOf('var(--lg-radius-hero)') >= 0);
  assert.ok(a, 'glass A: W2-рецепт [data-glass="a"] (radius-hero)');
  assert.ok(!/url\(#lg-lens\)/.test(a),
    'glass A (база): url() отсутствует - до пробы узел живет как Tier B');
  const aTier = CSS.match(/\[data-glass="a"\]\[data-glass-tier="a"\]\s*\{([^}]*)\}/);
  assert.ok(aTier, 'glass A: tier-вариант [data-glass-tier="a"]');
  assert.ok(/backdrop-filter:[^;]*url\(#lg-lens\)/.test(aTier[1]),
    'glass A: РЕАЛЬНАЯ edge-рефракция через backdrop-filter url(#lg-lens)');
  const aFrost = CSS.match(/\[data-glass="a"\]:not\(\[data-glass-tier="a"\]\)\s*\{([^}]*)\}/);
  assert.ok(aFrost && aFrost[1].indexOf('var(--lg-frost-hero)') >= 0,
    'glass A fallback: честный frost без url()');
  const lens = CSS.match(/\[data-glass="a"\]::before\s*\{([^}]*)\}/);
  assert.ok(lens, 'glass A: ::before = tint-слой');
  assert.ok(lens[1].indexOf('filter') < 0,
    'glass A: ::before БЕЗ filter (tint, не форграунд-линза)');
  assert.ok(/z-index:\s*-1/.test(lens[1]),
    'glass A: декор под контентом (z-index:-1)');
  // U08.3a: backdrop url-фильтр разрешён ТОЛЬКО в цепочках tier A
  // (проверка в glass_probe_test.js: url(#lg-lens) только с backdrop-filter).
  const aAfter = CSS.match(/\[data-glass="a"\]::after\s*\{([^}]*)\}/);
  assert.ok(aAfter && /var\(--lg-rim\)/.test(aAfter[1]),
    'glass A: ::after = rim-кромка (masked ring)');
  const miniLens = CSS.indexOf('.lg-mini-lens');
  assert.ok(miniLens >= 0, 'U08.4d: lg-mini-lens (круглый контрол U07)');

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
  // W2-GLASS (U08.3): канон карты смещения — feImage + PNG-карта линзы
  // (центр ~70% неподвижен, кромка ≈6px к центру). Прежний feTurbulence+
  // feGaussianBlur на ФОРГРАУНД-градиенте — заменён (это была декорация,
  // не рефракция подложки; замена маркера по правилу w2-contract §1.2).
  assert.ok(INDEX.indexOf('feImage') >= 0, 'SVG: feImage (карта смещения)');
  assert.ok(INDEX.indexOf('data:image/png;base64') >= 0,
    'SVG: PNG-карта линзы inline (data:, CSP img-src; feImage по внешнему URL в Chromium не резолвится — зафиксировано измерением сдвига)');
  assert.ok(INDEX.indexOf('glass-probe.js') >= 0,
    'W2-GLASS: render-probe загружается до app.js');
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
  // AMEND ADR-1025-12 D1 — SUPERSEDED W2-GLASS U08.3: tier решает
  // render-проба `window.__GlassProbe` (реальный canvas-тест displacement,
  // REQ-U08-1-PROBE), а не CSS.supports('filter','url(#…)') — тот давал
  // формальный true без рендера (WebKit bug 245510). Замена маркера по
  // правилу w2-contract §1.2 (старый канон → новый, не молча).
  assert.ok(APP_JS.indexOf('__GlassProbe') >= 0,
    'W2-GLASS: tier по render-probe (__GlassProbe), не CSS.supports');
  assert.ok(APP_JS.indexOf("css.supports('filter', 'url(#lg-lens)')") < 0,
    'W2-GLASS: CSS.supports-детект устранён');
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

  // W2-GLASS U08.3: tier-лестница probe + кап (без min-стороны), обратимо.
  const mkEl = (w, h) => ({
    _attrs: { 'data-glass': 'a' },
    getBoundingClientRect: () => ({ width: w, height: h }),
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; },
    setAttribute(k, v) { this._attrs[k] = v; },
    removeAttribute(k) { delete this._attrs[k]; },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k); },
  });
  const oldQSA = global.document.querySelectorAll;
  const el1 = mkEl(320, 400), el2 = mkEl(200, 300);
  // HOTFIX-TIERA (SOUL-1): reconcile ищет стекло КОМПАУНД-селектором
  // (`[data-glass], .card, …`) — мок отвечает на любой селектор, ведущий
  // `[data-glass]` (декларация hero остаётся в приоритете словаря tier).
  global.document.querySelectorAll = (sel) =>
    (typeof sel === 'string' && sel.indexOf('[data-glass]') === 0)
      ? [el1, el2] : [];
  const fake = (sup, cap, ovr, rm) => ({
    _probeTierA: () => ({ tierA: !!sup, reason: sup ? 'probe-chromium' : 'svg-render-failed' }),
    _glassTierOverride: () => ovr || 'auto',
    _lensMaxNodes: () => cap,
    _prefersReducedMotion: () => !!rm,
    _lowEndDevice: () => false,
    _syncLensFilters: () => {},
    // HOTFIX-TIERA (SOUL-1): классовые поверхности и вложенность — реальная
    // логика app.js (мок-узлы без parentElement → «не вложено»).
    _lgGlassSelector: methods._lgGlassSelector,
    _lgDenseSelector: methods._lgDenseSelector,
    _lgNestedInGlass: methods._lgNestedInGlass,
  });
  methods.reconcileLiquidGlass.call(fake(true, 6));
  assert.strictEqual(el1.hasAttribute('data-glass-downgraded'), false,
    'probe+бюджет → A (кап clamp до 3: 6→3, оба узла помещаются)');
  assert.strictEqual(el1._attrs['data-glass-tier'], 'a', 'маркер tier=a');
  assert.strictEqual(el2._attrs['data-glass-tier'], 'a', 'оба в капе → A');
  // Нет рендера (probe) → честный B (не «пустое стекло»).
  methods.reconcileLiquidGlass.call(fake(false, 6));
  assert.strictEqual(el1.hasAttribute('data-glass-downgraded'), true,
    'probe: svg-рендер не доказан → B');
  assert.strictEqual(el1._attrs['data-glass-reason'], 'svg-render-failed',
    'причина: svg-render-failed');
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
  // W2-GLASS U08.3d: жёсткий максимум 3 hero-поверхности (env 6 → clamp 3).
  // HOTFIX-TIERA (SOUL-1): кап действует ровно на HERO-декларации
  // `data-glass="a"`; массовые стеклянные поверхности (`.card` и др.) идут
  // без капа — приказ владельца «Tier A = основной материал».
  const many = [mkEl(320, 200), mkEl(320, 200), mkEl(320, 200), mkEl(320, 200)];
  global.document.querySelectorAll = (sel) =>
    (typeof sel === 'string' && sel.indexOf('[data-glass]') === 0) ? many : [];
  methods.reconcileLiquidGlass.call(fake(true, 6));
  const tiersA = many.filter((e) => e._attrs['data-glass-tier'] === 'a').length;
  assert.strictEqual(tiersA, 3, 'U08.3d: максимум 3 hero в Tier A (env-кап clamp)');
  global.document.querySelectorAll = oldQSA;

  // W2-GLASS U08.3: _liquidGlassSupported — sync-обёртка над кэшем пробы.
  const oldWin = global.window;
  try {
    global.window = { __GlassProbe: { cached: () => ({ tierA: true, reason: 'probe-chromium' }) } };
    assert.strictEqual(methods._liquidGlassSupported.call({}), true,
      'probe-кэш tierA=true → supported');
    global.window = { __GlassProbe: { cached: () => ({ tierA: false, reason: 'svg-render-failed' }) } };
    assert.strictEqual(methods._liquidGlassSupported.call({}), false,
      'probe-кэш tierA=false → not supported');
    global.window = {};
    assert.strictEqual(methods._liquidGlassSupported.call({}), false,
      'нет __GlassProbe → B (guard)');
  } finally {
    global.window = oldWin;
  }
}

console.log('JS-UNIT-OK');
