'use strict';
/* HOTFIX9 round 10.25 (ADR-1025-17) — регресс flex-геометрии shell,
 * графитового shell без текстуры, vendored Liquid Glass и Dark Aurora Flow.
 *   A — единый источник `--app-usable-height` (+ `--shell-h` алиас), flex-колонка
 *       `shell-mobile`/fullscreen, scroll-area — единственный скроллер,
 *       `.bottom-nav` в потоке (не fixed), safe-area один раз.
 *   D — модалка `modal-card > modal-head/modal-body/modal-actions`.
 *   E/F — `--shell-texture` удалена; графитовые токены §8.
 *   G/H — vendored OGL/Liquid Glass (same-origin, CSP), модули aurora-flow/glass.
 *   J — точечный фикс сердцебиения (`_hbResize`).
 *
 * Падает на коде до HOTFIX9 (fixed nav/bottom-offset, текстура, старое стекло).
 * Запуск: node tests/js/round1025_hotfix9_shell_flex_glass_aurora_test.js
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
const TG = fs.readFileSync(path.join(ROOT, 'web', 'static',
  'telegram-init.js'), 'utf8');
const AURORA = fs.readFileSync(path.join(ROOT, 'web', 'static',
  'aurora-flow.js'), 'utf8');
const GLASS = fs.readFileSync(path.join(ROOT, 'web', 'static',
  'glass.js'), 'utf8');
const SETTINGS = fs.readFileSync(
  path.join(ROOT, 'config', 'settings.py'), 'utf8');
const ROUTES = fs.readFileSync(path.join(ROOT, 'web', 'api', 'routes.py'),
  'utf8');
const MATRIX = fs.readFileSync(
  path.join(ROOT, 'tools', 'ui_round1025_matrix.py'), 'utf8');
const ENV = fs.readFileSync(path.join(ROOT, '.env.example'), 'utf8');
const VENDOR_README = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'vendor', 'README.md'), 'utf8');

function token(name) {
  const m = CSS.match(new RegExp(name.replace(/[-]/g, '\\-') + '\\s*:\\s*([^;]+);'));
  return m ? m[1].trim() : '';
}

// ── A. Единый источник высоты + flex-колонка ──────────────────────────────
{
  assert.strictEqual(token('--app-usable-height'), '100vh', 'A: база 100vh');
  assert.strictEqual(token('--shell-h'), 'var(--app-usable-height)',
    'A: --shell-h — алиас');
  assert.ok(/@supports \(height: 100dvh\)[\s\S]{0,200}--app-usable-height:\s*100dvh/
    .test(CSS), 'A: dvh-апгрейд за @supports');
  assert.ok(/\.app-shell\.shell-mobile:not\(\.shell-layout-legacy\)[\s\S]{0,220}height:\s*var\(--app-usable-height/
    .test(CSS), 'A: shell-mobile — фикс. flex-колонка');
  assert.ok(/display:\s*flex;\s*flex-direction:\s*column/.test(CSS),
    'A: app-shell flex-column');
  // Скроллится только центр.
  assert.ok(/\.app-shell\.shell-mobile:not\(\.shell-layout-legacy\) > main\.scroll-area[\s\S]{0,220}overflow-y:\s*auto/
    .test(CSS), 'A: main.scroll-area — единственный скроллер');
  // Нижняя навигация — в потоке, не fixed.
  const nav = CSS.match(/\.bottom-nav \{([^}]*)\}/);
  assert.ok(nav, 'A: правило .bottom-nav');
  assert.ok(/position:\s*relative/.test(nav[1]), 'A: nav position:relative');
  assert.ok(/flex:\s*0 0 auto/.test(nav[1]), 'A: nav flex:0 0 auto');
  assert.ok(/width:\s*100%/.test(nav[1]), 'A: nav width:100%');
  assert.ok(!/position:\s*fixed/.test(nav[1]), 'A: nav не fixed');
  // Safe-area считается ровно один раз — на nav нет offset/padding.
  assert.ok(!/--tg-viewport-bottom-offset/.test(nav[1]),
    'A: nav не использует --tg-viewport-bottom-offset');
  assert.ok(!/padding-bottom/.test(nav[1]),
    'A: nav без дублирующего safe-area padding');
  // Единый источник задаётся в telegram-init.js.
  assert.ok(/--app-usable-height/.test(TG) && /computeBottomOffset/.test(TG),
    'A: telegram-init задаёт --app-usable-height');
  assert.ok(/visualViewport/.test(TG), 'A: пересчёт при клавиатуре (visualViewport)');
  assert.ok(computed.shellFlexV3.call({ uiFlag: () => true }) === true &&
    computed.shellFlexV3.call({ uiFlag: () => false }) === false,
    'A: UI_SHELL_FLEX_V3 флаг');
}

// ── C/D. Header/fullscreen + modal-actions ────────────────────────────────
{
  assert.ok(/header\.header-sticky \{ flex: 0 0 auto; \}/.test(CSS),
    'C: header flex:0 0 auto');
  assert.ok(/\.header-scope-row/.test(CSS), 'C: селектор — своя строка');
  assert.ok(/_hbResize: function/.test(APP_JS),
    'J: _hbResize — перерисовка после смены viewport/fullscreen');
  // Модалка: footer.modal-actions + SaveBar вне .modal-body.
  assert.ok(/\.modal-actions \{[\s\S]{0,200}flex: 0 0 auto/.test(CSS),
    'D: .modal-actions — flex:0 0 auto');
  assert.ok(/\.modal-actions > \.sticky-save \{[\s\S]{0,120}position: static/
    .test(CSS), 'D: SaveBar в footer — static (не поверх полей)');
  assert.ok(/\.modal-card \{[\s\S]{0,200}app-usable-height/.test(CSS),
    'D: max-height модалки от --app-usable-height');
  assert.ok(/<footer class="modal-actions[^"]*">[\s\S]{0,300}<sticky-save/
    .test(INDEX), 'D: <sticky-save> внутри footer.modal-actions');
  // F0/F9 логику не меняем: компонент/методы persistItems на месте.
  assert.ok(APP_JS.indexOf("app.component('sticky-save'") >= 0,
    'D: существующий компонент sticky-save переиспользован');
}

// ── E/F. Текстура удалена; графитовые токены ──────────────────────────────
{
  assert.ok(CSS.indexOf('--shell-texture:') < 0, 'E: --shell-texture удалена');
  assert.ok(!/var\(--shell-texture\)/.test(CSS), 'E: нигде не применяется');
  assert.ok(!/repeating-linear-gradient\(135deg/.test(
    CSS.match(/\[data-glass="shell"\] \{([^}]*)\}/)[1]),
    'E: shell без повторяющейся диагонали');
  assert.strictEqual(token('--shell-bg').replace(/\s/g, ''),
    'rgba(27,29,34,0.94)', 'F: --shell-bg .94');
  assert.strictEqual(token('--shell-bg-mobile').replace(/\s/g, ''),
    'rgba(27,29,34,0.96)', 'F: mobile .96');
  assert.strictEqual(token('--shell-border-color').replace(/\s/g, ''),
    'rgba(255,255,255,0.09)', 'F: border .09');
  assert.strictEqual(token('--shell-highlight').replace(/\s/g, ''),
    'rgba(255,255,255,0.055)', 'F: highlight .055');
  assert.strictEqual(token('--shell-shadow').replace(/\s/g, ''),
    '04px16pxrgba(0,0,0,0.16)', 'F: shadow');
  const blur = token('--shell-blur').replace(/\s/g, '');
  assert.ok(blur.indexOf('blur(14px)') >= 0 && blur.indexOf('saturate(105%)') >= 0,
    'F: blur(14px) saturate(105%)');
  assert.notStrictEqual(token('--shell-bg'), token('--glass-bg'),
    'F: shell ≠ карточки');
  assert.ok(computed.shellGraphiteV3.call({ uiFlag: () => true }) === true &&
    computed.shellGraphiteV3.call({ uiFlag: () => false }) === false,
    'F: UI_SHELL_GRAPHITE_V3 флаг');
}

// ── G/H. Гласс и фон: vendored + модули, CSP-safe ─────────────────────────
{
  for (const f of ['web/static/vendor/ogl.1.0.11.min.js',
                   'web/static/vendor/liquidglass.core.0.5.3.min.js',
                   'web/static/vendor/liquidglass.core.0.5.3.css']) {
    assert.ok(fs.existsSync(path.join(ROOT, f)), 'G: vendored ' + f);
  }
  assert.ok(/0\.5\.3/.test(VENDOR_README) && /1\.0\.11/.test(VENDOR_README) &&
    /sha256|SHA-256/i.test(VENDOR_README) && /npm/.test(VENDOR_README),
    'G: README vendored — версия/лицензия/хеш/сборка');
  assert.ok(INDEX.indexOf('src="/static/vendor/liquidglass.core.0.5.3.min.js') >= 0,
    'G: same-origin подключение Liquid Glass');
  assert.ok(INDEX.indexOf('src="/static/vendor/ogl.1.0.11.min.js') >= 0,
    'H: same-origin подключение OGL');
  assert.ok(INDEX.indexOf('src="/static/aurora-flow.js') >= 0 &&
    INDEX.indexOf('src="/static/glass.js') >= 0, 'G/H: модули подключены');
  // Никаких CDN/инлайнов.
  assert.ok(!/src="https?:\/\//.test(INDEX), 'CSP: нет внешних CDN');
  assert.ok(!/<script(?![^>]*\bsrc=)[^>]*>[\s\S]*?<\/script>/i.test(
    INDEX.replace(/<script type="text\/x-template"[\s\S]*?<\/script>/gi, '')),
    'CSP: нет inline-скриптов');
  // Стекло: mountGlass, честный frost-fallback, запреты §9.
  assert.ok(/mountGlass/.test(GLASS) && /LiquidGlass/.test(GLASS),
    'G: glass.js использует mountGlass');
  assert.ok(/data-lg-failed/.test(GLASS), 'G: честный fallback при ошибке');
  assert.ok(!/backdrop-filter\s*:\s*url\(/.test(CSS),
    '§9: авторский CSS без backdrop url()');
  assert.ok(/data-lg-mounted/.test(GLASS), 'G: маркер смонтированного стекла');
  // Фон: OGL shader + Canvas2D fallback + перф-контроль §10.
  assert.ok(/OGL/.test(AURORA), 'H: OGL-кандидат');
  assert.ok(/getContext\('2d'\)/.test(AURORA), 'H: Canvas2D-фолбэк');
  assert.ok(/prefers-reduced-motion/.test(AURORA) &&
    /document\.hidden/.test(AURORA), 'H: reduced-motion + стоп при hidden');
  assert.ok(/webglcontextlost/.test(AURORA), 'H: context-loss фолбэк');
  assert.ok(/dprCap/.test(AURORA), 'H: DPR-кап');
  assert.ok(/aurora-flow-canvas/.test(CSS) && /aurora-flow-v2/.test(CSS),
    'H: слой Dark Aurora Flow в CSS');
  assert.ok(computed.auroraFlowV2.call({ uiFlag: () => true }) === true &&
    computed.auroraFlowV2.call({ uiFlag: () => false }) === false,
    'H: UI_AURORA_FLOW_V2 флаг');
  assert.ok(computed.liquidGlassLib.call({ uiFlag: () => true }) === true &&
    computed.liquidGlassLib.call({ uiFlag: () => false }) === false,
    'G: UI_LIQUID_GLASS_LIB флаг');
}

// ── D. env-only флаги + матрица + версия ──────────────────────────────────
{
  for (const flag of ['UI_SHELL_FLEX_V3', 'UI_SHELL_GRAPHITE_V3',
                      'UI_LIQUID_GLASS_LIB', 'UI_AURORA_FLOW_V2']) {
    assert.ok(SETTINGS.indexOf(flag + ': ClassVar') >= 0, 'D: settings ' + flag);
    assert.ok(ROUTES.indexOf(flag) >= 0, 'D: ui_flags ' + flag);
    assert.ok(APP_JS.indexOf(flag) >= 0, 'D: фронт читает ' + flag);
    assert.ok(ENV.indexOf(flag) >= 0, 'D: .env.example ' + flag);
  }
  assert.ok(/APP_VERSION = "2\.58\.25"/.test(SETTINGS), 'D: APP_VERSION 2.58.21');
  for (const m of ['desktop_normal', 'desktop_fullscreen', 'tablet',
                   'mobile_regular', 'mobile_fullscreen']) {
    assert.ok(MATRIX.indexOf(m) >= 0, 'D: режим ' + m);
  }
  assert.ok(MATRIX.indexOf('H9_PROBE_JS') >= 0, 'D: H9-проба');
  assert.ok(MATRIX.indexOf('_h9_failures') >= 0, 'D: H9-failures');
  assert.ok(MATRIX.indexOf('_bg_motion') >= 0, 'D: кадры фона 0/5/10/20 с');
  assert.ok(MATRIX.indexOf('elementFromPoint') >= 0, 'D: нажимаемость');
  assert.ok(MATRIX.indexOf('H9_MODAL_PROBE_JS') >= 0, 'D: modal-проба');
  const CATALOG = fs.readFileSync(
    path.join(ROOT, 'services', 'param_catalog.py'), 'utf8');
  for (const flag of ['UI_SHELL_FLEX_V3', 'UI_SHELL_GRAPHITE_V3',
                      'UI_LIQUID_GLASS_LIB', 'UI_AURORA_FLOW_V2']) {
    assert.ok(CATALOG.indexOf(flag) < 0, 'D: Δ каталога = 0 (' + flag + ')');
  }
}

console.log('HOTFIX9-SHELL-FLEX-GLASS-AURORA-OK');
