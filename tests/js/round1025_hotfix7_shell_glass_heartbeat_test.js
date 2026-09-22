'use strict';
/* hotfix7 round 10.25 (T-2658…T-2694, ADR-1025-13) — регресс областей A/B/C/D:
 *   A (D1)  — единый сток высоты `--shell-h`, два явных режима normal/fullscreen,
 *             legacy-откат `shell-layout-legacy` (`UI_SHELL_LAYOUT_V2`).
 *   B (D2)  — premium ECG sweep-wipe (Canvas 2D), форма P/Q/R/S/T, свечение,
 *             отсутствие «плавающей точки»/`pulseX`; off-путь canvas-legacy.
 *   C (D3)  — серо-графитовые `--shell-*`-токены, specular/texture, глубина,
 *             удаление виньетки; `UI_SHELL_GLASS_V2` + `shell-glass-legacy`.
 *   D (D4)  — выравнивание shell; env-only флаги в settings/routes.
 *
 * Падает на коде до HOTFIX7 (нет --shell-*, pulseX, нет premium-рендера).
 * Запуск: node tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  matchMedia: () => ({ matches: false }), devicePixelRatio: 2,
  requestAnimationFrame: () => 1, cancelAnimationFrame() {},
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  querySelector() { return null; }, querySelectorAll() { return []; },
  createElement() {
    return { getContext: () => ({}), clientWidth: 320, clientHeight: 56,
             width: 0, height: 0 };
  },
  documentElement: {
    style: { setProperty() {} },
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
const computed = captured.computed;

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const SETTINGS = fs.readFileSync(
  path.join(ROOT, 'config', 'settings.py'), 'utf8');
const ROUTES = fs.readFileSync(path.join(ROOT, 'web', 'api', 'routes.py'),
  'utf8');
const MATRIX = fs.readFileSync(
  path.join(ROOT, 'tools', 'ui_round1025_matrix.py'), 'utf8');

function mockCtx() {
  const calls = { arc: 0, radial: 0, lineTo: 0, stroke: 0, moveTo: 0 };
  const grad = { addColorStop() {} };
  return {
    _calls: calls,
    clearRect() {}, save() {}, restore() {}, beginPath() {},
    moveTo() { calls.moveTo++; }, lineTo() { calls.lineTo++; },
    stroke() { calls.stroke++; }, closePath() {},
    arc() { calls.arc++; }, fill() {},
    createRadialGradient() { calls.radial++; return grad; },
    set strokeStyle(v) {}, get strokeStyle() { return ''; },
    set fillStyle(v) {}, get fillStyle() { return ''; },
    set lineWidth(v) {}, get lineWidth() { return 1; },
    set globalAlpha(v) {}, get globalAlpha() { return 1; },
    set shadowBlur(v) {}, get shadowBlur() { return 0; },
    set shadowColor(v) {}, get shadowColor() { return ''; },
    set lineJoin(v) {}, get lineJoin() { return ''; },
    set lineCap(v) {}, get lineCap() { return ''; },
  };
}

function canvasStub() {
  const ctx = mockCtx();
  return { cv: { getContext: () => ctx, clientWidth: 320, clientHeight: 56,
                 width: 0, height: 0 }, ctx };
}

// ── A. Единый сток высоты + два режима ─────────────────────────────────────
{
  // HOTFIX9 (ADR-1025-17 D1): единственный источник — `--app-usable-height`
  // (JS inline в TMA), всегда валидный CSS-фолбэк `100vh`; апгрейд до `100dvh`
  // строго за @supports; `--shell-h` — только алиас (второго источника нет).
  assert.ok(/--app-usable-height:\s*100vh;/.test(CSS),
    'A: базовый --app-usable-height = 100vh');
  assert.ok(/--shell-h:\s*var\(--app-usable-height\)/.test(CSS),
    'A: --shell-h — алиас --app-usable-height');
  assert.ok(!/--shell-h:\s*100dvh;/.test(CSS) && !/--shell-h:\s*100vh;/.test(CSS),
    'A: у --shell-h нет собственного значения (только алиас)');
  assert.ok(
    /@supports \(height: 100dvh\)[\s\S]{0,200}--app-usable-height:\s*100dvh/
      .test(CSS),
    'A: dvh-апгрейд только внутри @supports (реальный фолбэк)');
  assert.ok(/\.app-shell \{[\s\S]{0,700}min-height: var\(--shell-h\)/.test(CSS),
    'A: .app-shell min-height из --shell-h');
  assert.ok(
    /\.app-shell\.shell-mobile:not\(\.shell-layout-legacy\),[\s\S]{0,200}height:\s*var\(--app-usable-height/
      .test(CSS),
    'A: mobile flex-колонка height = --app-usable-height');
  assert.ok(
    /\.app-shell\.fullscreen-mode:not\(\.shell-layout-legacy\)[\s\S]{0,200}height:\s*var\(--app-usable-height/
      .test(CSS),
    'A: fullscreen height = --app-usable-height');
  // Конкурирующего min-height(stable) в базовом .app-shell больше нет.
  assert.ok(!/\.app-shell \{[\s\S]{0,400}min-height: var\(--tg-viewport-stable-height/
    .test(CSS), 'A: убран конкурирующий min-height(stable)');
  // Legacy-откат.
  assert.ok(/\.app-shell\.shell-layout-legacy\.fullscreen-mode \{[\s\S]{0,200}height: 100dvh/
    .test(CSS), 'A: legacy-fullscreen возвращает 100dvh');
  assert.ok(computed.shellLayoutV2 &&
    computed.shellLayoutV2.call({ uiFlag: () => true }) === true,
    'A: shellLayoutV2 default ON');
  assert.ok(computed.shellLayoutV2.call({ uiFlag: () => false }) === false,
    'A: UI_SHELL_LAYOUT_V2=OFF → legacy');
  assert.ok(computed.shellFlexV3 &&
    computed.shellFlexV3.call({ uiFlag: () => true }) === true,
    'A: shellFlexV3 default ON');
  assert.ok(computed.shellFlexV3.call({ uiFlag: () => false }) === false,
    'A: UI_SHELL_FLEX_V3=OFF → legacy');
  assert.ok(INDEX.indexOf('shell-layout-legacy') >= 0,
    'A: класс legacy привязан в разметке');
  // heartbeat не схлопывается (D1.6).
  assert.ok(/\.hb-wrap \{[^}]*min-height: 56px/.test(CSS),
    'A: hb-wrap min-height 56px');
}

// ── B. Premium ECG sweep-wipe ───────────────────────────────────────────────
{
  assert.strictEqual(typeof methods._hbEcg, 'function', 'B: _hbEcg — метод');
  // R-пик ~ +1.0, Q/S отрицательны, P/T положительны (не синусоида).
  assert.ok(methods._hbEcg(0.365) > 0.9, 'B: R-пик ≈ +1.0');
  assert.ok(methods._hbEcg(0.180) > 0.03 && methods._hbEcg(0.180) < 0.2,
    'B: P-зубец положительный малый');
  assert.ok(methods._hbEcg(0.340) < 0, 'B: Q-зубец отрицательный');
  assert.ok(methods._hbEcg(0.390) < 0, 'B: S-зубец отрицательный');
  assert.ok(methods._hbEcg(0.550) > 0.1, 'B: T-зубец положительный');
  // Изолиния между зубцами близка к нулю.
  assert.ok(Math.abs(methods._hbEcg(0.8)) < 0.01, 'B: изолиния ≈ 0');
  // Нет «плавающей точки»/горизонтального переноса в premium-коде.
  assert.ok(APP_JS.indexOf('pulseX') < 0, 'B: нет pulseX-паттерна');
  assert.ok(APP_JS.indexOf('translateX') < 0 || /drawer|sheet/.test(APP_JS),
    'B: нет CSS-translateX-анимации сердцебиения');
  assert.ok(/sweep/.test(APP_JS), 'B: sweep-wipe маркер');
  assert.ok(/_hbDrawPremium/.test(APP_JS), 'B: premium-рендер');
  assert.ok(/_hbDrawLegacy/.test(APP_JS), 'B: canvas-legacy откат');
  assert.ok(/createRadialGradient/.test(APP_JS), 'B: вспышка R-пика');
  assert.ok(/shadowBlur/.test(APP_JS), 'B: ограниченное свечение');
  assert.ok(/_hbDrawGrid/.test(APP_JS), 'B: бледная сетка монитора');
  assert.ok(!/getContext\(['"]webgl/i.test(APP_JS), 'B: WebGL запрещён');
  // Флаги.
  assert.strictEqual(computed.heartbeatPremium.call({ uiFlag: () => true }), true,
    'B: UI_HEARTBEAT_PREMIUM default ON');
  assert.strictEqual(computed.heartbeatPremium.call({ uiFlag: () => false }),
    false, 'B: OFF → canvas-legacy');
  // Premium-путь реально вызывается и рисует луч/вспышку.
  {
    const { cv, ctx } = canvasStub();
    const self = Object.assign(Object.create(null), {
      $refs: { hbCanvas: cv }, hbState: 'critical', heartbeatPremium: true,
      _hbEcg: methods._hbEcg, _hbRgba: methods._hbRgba,
      _hbPalette: methods._hbPalette, _hbDrawGrid: methods._hbDrawGrid,
      _hbDrawPremium: methods._hbDrawPremium,
      _hbDrawLegacy: methods._hbDrawLegacy, _hbDraw: methods._hbDraw,
      _hbPaletteState: null, _hbPaletteCache: null,
      _prefersReducedMotion: () => false,
    });
    self._hbDraw(1000);
    assert.ok(ctx._calls.stroke > 0, 'B: premium рисует трассу');
    assert.ok(ctx._calls.arc > 0, 'B: premium рисует «голову» луча');
  }
  // reduced-motion → статичный кадр (арк луча не рисуется).
  {
    const { cv, ctx } = canvasStub();
    const self = Object.assign(Object.create(null), {
      $refs: { hbCanvas: cv }, hbState: 'healthy', heartbeatPremium: true,
      _hbEcg: methods._hbEcg, _hbRgba: methods._hbRgba,
      _hbPalette: methods._hbPalette, _hbDrawGrid: methods._hbDrawGrid,
      _hbDrawPremium: methods._hbDrawPremium, _hbDraw: methods._hbDraw,
      _hbPaletteState: null, _hbPaletteCache: null,
      _prefersReducedMotion: () => true,
    });
    self._hbDraw(0);
    assert.ok(ctx._calls.stroke >= 1, 'B: reduced-motion рисует трассу');
    assert.strictEqual(ctx._calls.arc, 0, 'B: reduced-motion без луча');
    assert.strictEqual(ctx._calls.radial, 0, 'B: reduced-motion без вспышки');
  }
  // OFF → canvas-legacy (синусоида), premium helpers не вызываются.
  {
    const { cv, ctx } = canvasStub();
    let premium = 0;
    const realLegacy = methods._hbDrawLegacy;
    const self = Object.assign(Object.create(null), {
      $refs: { hbCanvas: cv }, hbState: 'healthy', heartbeatPremium: false,
      _hbDrawPremium: function () { premium++; },
      _hbDrawLegacy: function (ts, c, cvv, d, st) {
        return realLegacy.call(this, ts, c, cvv, d, st);
      },
      _hbDraw: methods._hbDraw,
    });
    self._hbDraw(0);
    assert.strictEqual(premium, 0, 'B-OFF: premium не вызван');
    assert.ok(ctx._calls.lineTo > 0, 'B-OFF: legacy canvas активен');
  }
  // F-3 (review): HEALTHY-трасса использует статус-токен --ok (как бейдж).
  {
    const pal = methods._hbPalette.call({
      _hbPaletteState: null, _hbPaletteCache: null, _hbRgba: methods._hbRgba,
    }, 'healthy');
    assert.strictEqual(String(pal.core).toLowerCase(), '#3dd68c',
      'F3: healthy core = --ok (#3DD68C)');
    assert.ok(/\.hb-healthy\s*\{\s*color:\s*var\(--ok\)/.test(CSS),
      'F3: бейдж .hb-healthy на --ok');
  }
  // F-4 (review): интенсивность свечения зависит от состояния.
  {
    const mk = () => ({ _hbPaletteState: null, _hbPaletteCache: null,
                        _hbRgba: methods._hbRgba });
    const h = methods._hbPalette.call(mk(), 'healthy');
    const w = methods._hbPalette.call(mk(), 'warning');
    const c = methods._hbPalette.call(mk(), 'critical');
    const u = methods._hbPalette.call(mk(), 'unknown');
    assert.ok(h.glowAlpha < w.glowAlpha && w.glowAlpha < c.glowAlpha,
      'F4: glowAlpha растёт healthy<warning<critical');
    assert.ok(c.glowAlpha >= 1.4 * h.glowAlpha,
      'F4: critical-свечение заметно сильнее healthy');
    assert.strictEqual(u.glowAlpha, 0, 'F4: unknown без свечения');
  }
  // Семантика не тронута.
  assert.ok(/_heartbeatTransition: function/.test(APP_JS),
    'B: state-machine на месте');
  assert.ok(/heartbeatSample: function/.test(APP_JS), 'B: телеметрия на месте');
  assert.ok(!/bpm\s*[:=]/i.test(APP_JS), 'B: без выдуманного BPM');
}

// ── C. Серо-графитовый shell-слой + глубина ────────────────────────────────
{
  // HOTFIX9 (ADR-1025-17 D4): `--shell-texture` УДАЛЕНА; `--shell-specular`
  // (не-repeating блик) сохранён.
  for (const tok of ['--shell-bg', '--shell-bg-strong', '--shell-border-color',
                     '--shell-highlight', '--shell-shadow', '--shell-blur',
                     '--shell-specular', '--card-shadow']) {
    assert.ok(CSS.indexOf(tok + ':') >= 0, 'C: токен ' + tok);
  }
  assert.ok(CSS.indexOf('--shell-texture:') < 0,
    'C: --shell-texture удалена (UPD3 §7)');
  assert.ok(/--shell-blur:\s*blur\(/.test(CSS), 'C: shell-blur = blur()');
  assert.ok(/--glass-shadow:[^;]*0\.55/.test(CSS),
    'C: --glass-shadow смягчён (.55)');
  assert.ok(/--card-shadow:/.test(CSS), 'C: отдельная card-shadow');
  // Карточки — card-shadow; модалки — glass-shadow.
  assert.ok(/box-shadow: var\(--card-shadow\)/.test(CSS),
    'C: карточки на --card-shadow');
  assert.ok(/\.modal-card \{\s*box-shadow: var\(--glass-shadow\)/.test(CSS),
    'C: модалки на --glass-shadow');
  // Shell-панели — shell-токены.
  for (const sel of ['.app-sidebar', '.app-drawer', 'header.header-sticky',
                     '.bottom-nav', '.more-sheet']) {
    assert.ok(CSS.indexOf(sel) >= 0, 'C: панель ' + sel);
  }
  assert.ok(/box-shadow: var\(--shell-shadow\)/.test(CSS),
    'C: shell-shadow применён');
  assert.ok(/background-image: var\(--shell-specular\);/
    .test(CSS), 'C: specular (без текстуры, CSS-градиент)');
  assert.ok(!/background-image: var\(--shell-specular\), var\(--shell-texture\)/
    .test(CSS), 'C: диагональная текстура снята со всех shell-поверхностей');
  // @supports-фолбэк shell → --shell-bg-strong.
  assert.ok(/@supports not \(\(backdrop-filter: blur\(1px\)\)[\s\S]{0,900}background-color: var\(--shell-bg-strong\)/
    .test(CSS), 'C: @supports фолбэк shell');
  // Legacy-откат.
  assert.ok(/shell-glass-legacy/.test(CSS), 'C: legacy-токены shell');
  assert.ok(computed.shellGlassV2.call({ uiFlag: () => false }) === false,
    'C: UI_SHELL_GLASS_V2=OFF');
  assert.ok(INDEX.indexOf('shell-glass-legacy') >= 0,
    'C: класс legacy в разметке');
  // §10/виньетка: opacity .30; механизм сохранён.
  assert.ok(/body::before \{[\s\S]{0,900}opacity: \.30;/.test(CSS),
    'C: body::before opacity .30');
  assert.ok(/@keyframes grad-spin/.test(CSS) &&
    /--grad-speed:75s/.test(CSS), 'C: фон §10 сохранён');
  // CSP/§9: без data-URI/внешних ассетов и backdrop url-фильтра.
  assert.ok(!/backdrop-filter\s*:\s*url\(/.test(CSS),
    'C: нет backdrop url-фильтра');
  assert.ok(!/--shell-texture:\s*url\(/.test(CSS) &&
    !/--shell-specular:\s*url\(/.test(CSS),
    'C: текстура/specular без data-URI/ассетов');
}

// ── D. Флаги env-only + матрица ────────────────────────────────────────────
{
  for (const flag of ['UI_SHELL_GLASS_V2', 'UI_HEARTBEAT_PREMIUM',
                      'UI_SHELL_LAYOUT_V2']) {
    assert.ok(SETTINGS.indexOf(flag + ': ClassVar') >= 0,
      'D: settings флаг ' + flag);
    assert.ok(ROUTES.indexOf(flag) >= 0, 'D: ui_flags доставка ' + flag);
    assert.ok(APP_JS.indexOf(flag) >= 0, 'D: фронт читает ' + flag);
  }
  // HOTFIX10 (10.25) — bump 2.58.12 → 2.58.13 (ADR-1025-18, T-2864).
  assert.ok(/APP_VERSION = "2\.58\.14"/.test(SETTINGS), 'D: APP_VERSION 2.58.14');
  // Матрица: 5 режимов + пробы shell/glass/heartbeat.
  for (const m of ['desktop_normal', 'desktop_fullscreen', 'tablet',
                   'mobile_regular', 'mobile_fullscreen']) {
    assert.ok(MATRIX.indexOf(m) >= 0, 'D: режим ' + m);
  }
  assert.ok(MATRIX.indexOf('F7_PROBE_JS') >= 0, 'D: F7-проба');
  assert.ok(MATRIX.indexOf('_hotfix7_failures') >= 0, 'D: F7-failures');
  assert.ok(MATRIX.indexOf('fullscreenChanged') >= 0,
    'D: матрица форсирует fullscreen');
  assert.ok(MATRIX.indexOf('f2ShellH') >= 0, 'D: F-2 проба фолбэка height');
  assert.ok(MATRIX.indexOf('__f2_broken') >= 0,
    'D: F-2 эмуляция старого WebView без dvh');
  const CATALOG = fs.readFileSync(
    path.join(ROOT, 'services', 'param_catalog.py'), 'utf8');
  assert.ok(CATALOG.indexOf('UI_SHELL_GLASS_V2') < 0 &&
    CATALOG.indexOf('UI_HEARTBEAT_PREMIUM') < 0 &&
    CATALOG.indexOf('UI_SHELL_LAYOUT_V2') < 0,
    'D: Δ каталога = 0 (флаги вне param_catalog)');
}

console.log('HOTFIX7-SHELL-GLASS-HEARTBEAT-OK');
