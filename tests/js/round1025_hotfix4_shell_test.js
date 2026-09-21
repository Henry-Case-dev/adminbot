'use strict';
/* hotfix4 round 10.25 (T-2514…T-2518, ADR-1025-8 D2) — нижняя панель mobile:
 *   * `.bottom-nav`/`.more-sheet` смещаются на `--tg-viewport-bottom-offset`
 *     (JS из telegram-init.js) + CSS-фолбэк `max(0px, 100dvh − stable-height)`;
 *   * viewport meta содержит `viewport-fit=cover` (iOS safe-area);
 *   * touch ≥44px и safe-area-паддинг сохранены;
 *   * матрица проверяет вертикаль `rect.bottom <= innerHeight/stableHeight`.
 *
 * Падает на старом коде: переменной/фолбэка/cover-меты не было.
 * Запуск: node tests/js/round1025_hotfix4_shell_test.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const TG = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'telegram-init.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const MATRIX = fs.readFileSync(
  path.join(ROOT, 'tools', 'ui_round1025_matrix.py'), 'utf8');

// ── CSS: offset-переменная + фолбэк для панели и шторки ──────────────────
const navBlock = CSS.slice(CSS.indexOf('.bottom-nav {'));
assert.ok(navBlock.indexOf('bottom: var(--tg-viewport-bottom-offset,') >= 0,
  '.bottom-nav использует --tg-viewport-bottom-offset');
assert.ok(/100dvh - var\(--tg-viewport-stable-height/.test(CSS),
  'CSS-фолбэк max(0px, 100dvh − stable-height) присутствует');
const moreBlock = CSS.slice(CSS.indexOf('.more-sheet {'));
assert.ok(moreBlock.slice(0, 700)
  .indexOf('--tg-viewport-bottom-offset') >= 0,
  '.more-sheet использует тот же offset');
assert.ok(/min-height:\s*44px/.test(CSS), 'touch ≥44px сохранён');
assert.ok(/env\(safe-area-inset-bottom/.test(CSS), 'safe-area сохранён');

// ── telegram-init.js: вычисление offset + подписки на события ────────────
assert.ok(TG.indexOf('--tg-viewport-bottom-offset') >= 0,
  'telegram-init прокидывает --tg-viewport-bottom-offset');
assert.ok(/window\.innerHeight/.test(TG),
  'offset считается из window.innerHeight');
assert.ok(/viewportStableHeight/.test(TG), 'offset учитывает stable height');
for (const ev of ['viewportChanged', 'safeAreaChanged', 'contentSafeAreaChanged']) {
  assert.ok(TG.indexOf(ev) >= 0, 'подписка на ' + ev);
}
// CSP-safe: без eval/inline-обработчиков в новых зонах.
assert.ok(TG.indexOf('eval(') < 0, 'telegram-init без eval');
assert.ok(TG.indexOf('.onclick =') < 0, 'telegram-init без inline-обработчиков');

// ── Формула offset (повторяет telegram-init) ──────────────────────────────
function offset(layoutH, stableH) {
  return Math.max(0, Math.min(layoutH, layoutH - stableH));
}
assert.strictEqual(offset(800, 744), 56, 'системный бар → offset 56');
assert.strictEqual(offset(800, 800), 0, 'нет бара → offset 0');
assert.strictEqual(offset(700, 800), 0, 'stable>layout не даёт отрицательный');

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
