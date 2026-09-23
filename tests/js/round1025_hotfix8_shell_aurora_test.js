'use strict';
/* hotfix8 round 10.25 (T-2748…T-2782, ADR-1025-16) — регресс shell v3/aurora:
 *   A/B — shell §4: `--shell-*` токены, `data-glass="shell"` на панелях,
 *         снятие цветной линзы `[data-glass="a"]::before` с shell, нейтральный
 *         бесцветный sheen ≤.05, радиусы, sidebar 208–224px.
 *   C   — aurora/mesh: отдельный задний слой (`body::before`/`body::after`/
 *         `.aurora-bg` 5 blob), палитра §8/§10 без оранжевого, пауза
 *         `lg-bg-paused`, reduced-motion, legacy conic → `bg-wash-legacy`.
 *   D   — env-only флаги `UI_SHELL_V3`/`UI_AURORA_BG_ENABLED` + матрица.
 *
 * Падает на коде до HOTFIX8 (панели `data-glass="a"`, мёртвый conic body::before).
 * Запуск: node tests/js/round1025_hotfix8_shell_aurora_test.js
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

function token(name) {
  const m = CSS.match(new RegExp(name.replace(/[-]/g, '\\-') + '\\s*:\\s*([^;]+);'));
  return m ? m[1].trim() : '';
}

// ── A/B. Shell §8 (HOTFIX9) + снятие цветной линзы ─────────────────────────
{
  // HOTFIX9 (ADR-1025-17 D4): графитовые токены §8 (UPD3 §8).
  assert.strictEqual(token('--shell-bg').replace(/\s/g, ''),
    'rgba(27,29,34,0.94)', 'B: §8 shell-bg .94');
  assert.strictEqual(token('--shell-bg-mobile').replace(/\s/g, ''),
    'rgba(27,29,34,0.96)', 'B: §8 mobile shell-bg .96');
  assert.strictEqual(token('--shell-border-color').replace(/\s/g, ''),
    'rgba(255,255,255,0.09)', 'B: §8 border .09');
  assert.strictEqual(token('--shell-highlight').replace(/\s/g, ''),
    'rgba(255,255,255,0.055)', 'B: §8 inner highlight .055');
  assert.strictEqual(token('--shell-shadow').replace(/\s/g, ''),
    '04px16pxrgba(0,0,0,0.16)', 'B: §8 shadow');
  const blur = token('--shell-blur').replace(/\s/g, '');
  assert.ok(blur.indexOf('blur(14px)') >= 0 && blur.indexOf('saturate(105%)') >= 0,
    'B: §8 backdrop blur(14px) saturate(105%)');
  // HOTFIX9 §7: диагональная текстура УДАЛЕНА полностью.
  assert.ok(CSS.indexOf('--shell-texture:') < 0, 'B: --shell-texture удалена');
  assert.ok(!/var\(--shell-texture\)/.test(CSS),
    'B: --shell-texture не применяется ни на одной поверхности');
  // Sheen ≤ .05, бесцветный (без радиальной цветной маски).
  assert.ok(/--shell-sheen-opacity:\s*\.05/.test(CSS), 'B: sheen ≤ .05');
  const shell = CSS.match(/\[data-glass="shell"\]\s*\{([^}]*)\}/);
  assert.ok(shell, 'B: правило [data-glass="shell"]');
  assert.ok(shell[1].indexOf('var(--shell-bg)') >= 0, 'B: shell на --shell-bg');
  assert.ok(shell[1].indexOf('var(--shell-blur)') >= 0, 'B: shell на --shell-blur');
  assert.ok(!/radial-gradient/.test(shell[1]), 'B: shell без цветной radial-линзы');
  const sheen = CSS.match(/\[data-glass="shell"\]::after\s*\{([^}]*)\}/);
  assert.ok(sheen, 'B: нейтральный sheen ::after');
  assert.ok(/linear-gradient/.test(sheen[1]), 'B: sheen — бесцветный linear');
  assert.ok(/opacity:\s*var\(--shell-sheen-opacity/.test(sheen[1]),
    'B: sheen opacity из токена');
  assert.ok(/z-index:\s*-1/.test(sheen[1]), 'B: sheen под контентом');
  assert.ok(!/mask-image/.test(sheen[1]), 'B: sheen без radial-mask-ореола');
  // Цветная линза A осталась только контенту; на shell не применяется.
  assert.ok(/\[data-glass="a"\]::before\s*\{/.test(CSS), 'B: линза A сохранена');
  // Панели в shell-слое.
  for (const sel of ['class="app-sidebar" data-glass="shell"',
                     'class="bottom-nav" data-glass="shell"',
                     'class="more-sheet" data-glass="shell"',
                     'data-glass="shell"\n']) {
    assert.ok(INDEX.indexOf(sel) >= 0, 'B: shell-слой: ' + sel);
  }
  // Sidebar 208–224px.
  const w = CSS.match(/\.app-shell\.ia-v2 \.app-sidebar\s*\{[\s\S]{0,200}width:\s*(\d+)px/);
  assert.ok(w, 'A: sidebar width правило');
  assert.ok(+w[1] >= 208 && +w[1] <= 224, 'A: sidebar 208–224px, факт ' + w[1]);
  const pad = CSS.match(/\.app-shell\.ia-v2 \{\s*padding-left:\s*(\d+)px/);
  assert.ok(pad && +pad[1] >= 208 && +pad[1] <= 224, 'A: padding-left 208–224px');
  // Радиусы §4.
  assert.ok(/\.more-sheet \{[\s\S]{0,1600}border-radius:\s*18px 18px 0 0/.test(CSS),
    'A: more-sheet радиус 18px');
  assert.ok(/\.bottom-nav \{[\s\S]{0,1200}border-radius:\s*18px 18px 0 0/.test(CSS),
    'A: bottom-nav радиус 18px');
  // UI_SHELL_GRAPHITE_V3=OFF (класс shell-v3-off) → hotfix8 значения, без
  // возврата линзы и БЕЗ возврата диагональной текстуры.
  assert.ok(/\.app-shell\.shell-v3-off\s*\{[\s\S]{0,900}--shell-bg:\s*rgba\(24, 28, 38, 0\.72\)/.test(CSS),
    'B-OFF: shell-v3-off → hotfix8 значения');
  assert.ok(INDEX.indexOf('shell-v3-off') >= 0 && INDEX.indexOf('shell-v3') >= 0,
    'B-OFF: класс shell-v3 в разметке');
  assert.ok(computed.shellV3.call({ uiFlag: () => true }) === true,
    'B: shellV3 default ON');
  assert.ok(computed.shellV3.call({ uiFlag: () => false }) === false,
    'B: UI_SHELL_V3=OFF');
}

// ── C. Aurora/mesh фон ─────────────────────────────────────────────────────
{
  // Отдельный задний слой с 5 blob + grain.
  const blobs = INDEX.match(/class="aurora-blob b[1-5]"/g) || [];
  assert.strictEqual(blobs.length, 5, 'C: 5 blob-слоёв');
  assert.ok(INDEX.indexOf('class="aurora-bg"') >= 0, 'C: контейнер aurora-bg');
  assert.ok(INDEX.indexOf('aurora-grain') >= 0, 'C: grain-слой');
  assert.ok(/\.aurora-bg \{[^}]*position:\s*fixed/.test(CSS),
    'C: aurora — отдельный фиксированный слой');
  assert.ok(/\.aurora-bg \{[^}]*z-index:\s*0/.test(CSS), 'C: z-index 0 (< #app)');
  assert.ok(/\.aurora-bg \{[^}]*pointer-events:\s*none/.test(CSS),
    'C: pointer-events none');
  // body::before — aurora, а не мёртвый conic.
  const before = CSS.match(/\n    body::before \{([^}]*)\}/);
  assert.ok(before, 'C: body::before');
  assert.ok(/radial-gradient/.test(before[1]), 'C: aurora radial blob-слои');
  assert.ok(before[1].indexOf('var(--surface-0)') >= 0, 'C: подложка surface-0');
  assert.ok(!/conic-gradient/.test(before[1]), 'C: прежний conic не в body::before');
  assert.ok(/aurora-flow var\(--grad-speed\)/.test(before[1]),
    'C: основной цикл на --grad-speed');
  assert.ok(/aurora-morph var\(--grad-speed-slow\)/.test(before[1]),
    'C: вторичный morph на --grad-speed-slow');
  // Разные фазы/длительности blob-слоёв.
  for (const d of ['34s', '46s', '40s', '52s', '58s']) {
    assert.ok(CSS.indexOf(d) >= 0, 'C: фаза blob ' + d);
  }
  // Палитра §8/§10, без оранжевого.
  assert.ok(CSS.indexOf('#FF8A3D') < 0, 'C: без оранжевого');
  assert.ok(/rgba\(66, 214, 196/.test(CSS) && /rgba\(167, 139, 250/.test(CSS)
    && /rgba\(119, 168, 255/.test(CSS) && /rgba\(92, 124, 250/.test(CSS),
    'C: палитра teal/violet/blue/indigo');
  // Пауза hidden + reduced-motion.
  assert.ok(/html\.lg-bg-paused \.aurora-blob/.test(CSS),
    'C: пауза aurora при hidden');
  assert.ok(/html\.lg-bg-paused body::before/.test(CSS) &&
    /animation-play-state:\s*paused/.test(CSS), 'C: пауза body::before');
  assert.ok(/@media \(prefers-reduced-motion: reduce\)[\s\S]{0,600}\.aurora-bg \.aurora-blob \{ animation: none/.test(CSS),
    'C: reduced-motion гасит aurora');
  // Legacy conic под флагом.
  assert.ok(/html\.bg-wash-legacy body::before \{[\s\S]{0,600}conic-gradient/.test(CSS),
    'C-OFF: legacy conic page-wash');
  assert.ok(/html\.bg-wash-legacy \.aurora-bg \{ display: none/.test(CSS),
    'C-OFF: aurora скрыта');
  // Механика §10 сохранена для кнопок/band.
  assert.ok(/@property --grad-angle/.test(CSS), 'C: @property --grad-angle');
  assert.ok(/@keyframes grad-spin/.test(CSS) && /@keyframes grad-drift/.test(CSS),
    'C: grad-spin/grad-drift сохранены');
  // Флаг + класс.
  assert.ok(computed.auroraBgEnabled.call({ uiFlag: () => true }) === true,
    'C: aurora default ON');
  assert.ok(computed.auroraBgEnabled.call({ uiFlag: () => false }) === false,
    'C: UI_AURORA_BG_ENABLED=OFF');
  assert.strictEqual(typeof methods._syncBgLayer, 'function',
    'C: _syncBgLayer — метод');
  methods._syncBgLayer.call({ auroraBgEnabled: false });
  assert.strictEqual(
    global.document.documentElement.classList.contains('bg-wash-legacy'), true,
    'C: OFF → html.bg-wash-legacy');
  methods._syncBgLayer.call({ auroraBgEnabled: true });
  assert.strictEqual(
    global.document.documentElement.classList.contains('bg-wash-legacy'), false,
    'C: ON → класс снят');
  // CSP/no-WebGL/no-assets/no-backdrop-url.
  assert.ok(!/getContext\(['"]webgl/i.test(APP_JS), 'C: без WebGL');
  assert.ok(!/backdrop-filter\s*:\s*url\(/.test(CSS), 'C: без backdrop url()');
  assert.ok(APP_JS.indexOf('data:image') < 0, 'C: без data-URI ассетов');
}

// ── D. env-only флаги + матрица ────────────────────────────────────────────
{
  for (const flag of ['UI_SHELL_V3', 'UI_AURORA_BG_ENABLED']) {
    assert.ok(SETTINGS.indexOf(flag + ': ClassVar') >= 0, 'D: settings ' + flag);
    assert.ok(ROUTES.indexOf(flag) >= 0, 'D: ui_flags доставка ' + flag);
    assert.ok(APP_JS.indexOf(flag) >= 0, 'D: фронт читает ' + flag);
  }
  // T-2864: HOTFIX10 bump 2.58.12 → 2.58.13 (cache-bust glass/geometry/bg).
  assert.ok(/APP_VERSION = "2\.58\.26"/.test(SETTINGS), 'D: APP_VERSION 2.58.21');
  for (const m of ['desktop_normal', 'desktop_fullscreen', 'tablet',
                   'mobile_regular', 'mobile_fullscreen']) {
    assert.ok(MATRIX.indexOf(m) >= 0, 'D: режим ' + m);
  }
  assert.ok(MATRIX.indexOf('_hotfix8_failures') >= 0, 'D: hotfix8-чекер');
  assert.ok(MATRIX.indexOf('shellGlass') >= 0 && MATRIX.indexOf('auroraAnim') >= 0,
    'D: пробы shell/aurora');
  const CATALOG = fs.readFileSync(
    path.join(ROOT, 'services', 'param_catalog.py'), 'utf8');
  assert.ok(CATALOG.indexOf('UI_SHELL_V3') < 0
    && CATALOG.indexOf('UI_AURORA_BG_ENABLED') < 0,
    'D: Δ каталога = 0 (флаги вне param_catalog)');
}

console.log('HOTFIX8-SHELL-AURORA-OK');
