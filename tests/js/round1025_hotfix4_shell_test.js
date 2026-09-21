'use strict';
/* hotfix4 round 10.25 (T-2514…T-2518, ADR-1025-8 D2) — нижняя панель mobile:
 *   * `telegram-init.js` РЕАЛЬНО исполняется в VM-стенде с подставным
 *     `window.Telegram.WebApp` → проверяем фактическое значение
 *     `--tg-viewport-bottom-offset` (не дублируем формулу): stable отсутствует/
 *     0/отрицательный/больше/меньше innerHeight (Scanner M10.25H4-1,
 *     L10.25H4-1);
 *   * CSS: `.bottom-nav`/`.more-sheet` используют переменную + безопасный
 *     резерв `bottom` (L10.25H4-2);
 *   * viewport meta `viewport-fit=cover`; touch ≥44px/safe-area (B);
 *   * матрица проверяет вертикаль `rect.bottom <= innerHeight/stableHeight`.
 *
 * Падает на старом коде: переменной/guard/фолбэка/cover-меты не было.
 * Запуск: node tests/js/round1025_hotfix4_shell_test.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const TG = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'telegram-init.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const MATRIX = fs.readFileSync(
  path.join(ROOT, 'tools', 'ui_round1025_matrix.py'), 'utf8');

// ── РЕАЛЬНЫЙ прогон telegram-init.js (VM) ────────────────────────────────
function runTelegramInit(innerHeight, stableHeight) {
  const vars = {};
  const style = { setProperty(k, v) { vars[k] = v; } };
  const wa = {
    themeParams: {}, ready() {}, expand() {},
    setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
    onEvent() {}, offEvent() {},
    safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
    contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
    BackButton: { hide() {}, show() {} },
  };
  if (stableHeight !== undefined) wa.viewportStableHeight = stableHeight;
  const tg = { WebApp: wa };
  const sandbox = {
    window: {
      innerHeight, Telegram: tg, addEventListener() {},
    },
    Telegram: tg,
    document: { documentElement: { style } },
  };
  vm.runInNewContext(TG, sandbox, { filename: 'telegram-init.js' });
  return vars;
}

function offsetFor(innerHeight, stableHeight) {
  const vars = runTelegramInit(innerHeight, stableHeight);
  const raw = vars['--tg-viewport-bottom-offset'];
  return raw === undefined ? undefined : parseFloat(raw);
}

// Системный бар 56px → панель поднимается на 56px.
assert.strictEqual(offsetFor(800, 744), 56, 'stable<layout → offset 56');
assert.strictEqual(offsetFor(700, 700), 0, 'stable==layout → offset 0');
assert.strictEqual(offsetFor(700, 800), 0, 'stable>layout → offset 0 (кламп)');
// Review L10.25H4-1: невалидный stable не даёт offset = layoutHeight.
assert.strictEqual(offsetFor(700, 0), 0, 'stable=0 → offset 0 (guard)');
assert.strictEqual(offsetFor(700, -50), 0, 'stable<0 → offset 0 (guard)');
assert.strictEqual(offsetFor(700, undefined), 0, 'stable отсутствует → offset 0');
// stable-высота прокидывается как есть.
assert.strictEqual(
  runTelegramInit(800, 744)['--tg-viewport-stable-height'], '744px',
  'stable-height пробрасывается в CSS-переменную');
// Старый код без guard: stable=0 → offset=700 (панель уезжает).
assert.notStrictEqual(offsetFor(700, 0), 700,
  'guard: невалидный stable не выставляет offset во всю высоту');

// ── CSS: offset-переменная + безопасный резерв ───────────────────────────
const navBlock = CSS.slice(CSS.indexOf('.bottom-nav {'));
assert.ok(navBlock.indexOf('bottom: var(--tg-viewport-bottom-offset,') >= 0,
  '.bottom-nav использует --tg-viewport-bottom-offset');
assert.ok(/\.bottom-nav \{[^}]*bottom:\s*0;/.test(CSS),
  '.bottom-nav имеет безопасный резерв bottom:0 (L10.25H4-2)');
assert.ok(/100dvh - var\(--tg-viewport-stable-height/.test(CSS),
  'CSS-фолбэк max(0px, 100dvh − stable-height) присутствует');
const moreBlock = CSS.slice(CSS.indexOf('.more-sheet {'));
assert.ok(moreBlock.slice(0, 800)
  .indexOf('--tg-viewport-bottom-offset') >= 0,
  '.more-sheet использует тот же offset');
assert.ok(/\.more-sheet \{[^}]*bottom:\s*calc\(52px \+ max\(env\(safe-area-inset-bottom/.test(CSS),
  '.more-sheet имеет безопасный резерв bottom (L10.25H4-2)');
assert.ok(/min-height:\s*44px/.test(CSS), 'touch ≥44px сохранён');
assert.ok(/env\(safe-area-inset-bottom/.test(CSS), 'safe-area сохранён');

// ── telegram-init.js: подписки на события (пересчёт) ─────────────────────
for (const ev of ['viewportChanged', 'safeAreaChanged', 'contentSafeAreaChanged']) {
  assert.ok(TG.indexOf(ev) >= 0, 'подписка на ' + ev);
}
assert.ok(/addEventListener\('resize'/.test(TG), 'пересчёт на resize');
assert.ok(TG.indexOf('eval(') < 0, 'telegram-init без eval');
assert.ok(TG.indexOf('.onclick =') < 0, 'telegram-init без inline-обработчиков');

// ── viewport meta ────────────────────────────────────────────────────────
assert.ok(/name="viewport"[^>]*viewport-fit=cover/.test(INDEX),
  'meta-viewport содержит viewport-fit=cover');

// ── матрица: вертикальный контроль ───────────────────────────────────────
assert.ok(MATRIX.indexOf('_vertical_failures') >= 0,
  'матрица содержит вертикальную проверку панели');
assert.ok(/rect\.bottom|bottom: Math\.round\(r\.bottom\)/.test(MATRIX),
  'probe отдаёт bottom элемента');
assert.ok(/innerHeight/.test(MATRIX) && /stableHeight/.test(MATRIX),
  'матрица сравнивает с innerHeight/stableHeight');

console.log('JS-UNIT-OK round1025_hotfix4_shell_test');
