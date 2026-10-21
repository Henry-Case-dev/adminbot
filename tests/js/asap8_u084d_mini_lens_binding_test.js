'use strict';
/* U08.4d/U08.5.1 (asap8-v6.3, слайс FE-GLASS-MINILENS) — REGRESSION.
 *
 * Дефект (REV-W2-N1; plans/features/asap8-v6-3-live-correction/
 * prep-rfl-binding.md §«REAL дефекты» #1): клауза ТЗ «маленький fullscreen
 * control U07 — круглая мини-линза с rim и одним бликом, не 64px затемнённый
 * квадрат» не была доставлена: класс .lg-mini-lens определён (app.css,
 * W2-GLASS) и входит в Tier-A селекторы движков (app.js::_lgGlassSelector,
 * glass-refraction.js::SURFACE_SELECTOR), но ни один коммит не привязывал
 * его к кнопке ⛶ — index.html нёс только .header-fs-btn, контрол рендерился
 * без линзового материала (has_mini_lens=false на 31c16555).
 *
 * Фикс: класс lg-mini-lens в разметке ЕДИНСТВЕННОЙ кнопки ⛶ (тот же узел =
 * то же действие: @click → toggleFullscreen → FullscreenPolicy.request/exit,
 * без нового состояния); hover/active не стирают материал плоским фоном.
 *
 * Запуск: node tests/js/asap8_u084d_mini_lens_binding_test.js
 * → MINI-LENS-BINDING-OK
 * TEST-LIFECYCLE: REGRESSION owner=U08.4d/U08.5.1
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const REFRACTION =
  fs.readFileSync(path.join(ROOT, 'web', 'static', 'glass-refraction.js'), 'utf8');

/* ── 1. Разметка: кнопка ⛶ несёт ОБА класса — слот + материал ──────────── */
const btnMatch = INDEX.match(/<button[^>]*header-fs-btn[^>]*>/);
assert.ok(btnMatch, 'кнопка ⛶ (header-fs-btn) не найдена в index.html');
const btnTag = btnMatch[0];
assert.ok(/class="[^"]*\blg-mini-lens\b[^"]*"/.test(btnTag),
  'U08.4d: кнопка ⛶ не несёт материал lg-mini-lens ' +
  '(дефект REV-W2-N1 воспроизведён)');
assert.ok(/\bheader-fs-btn\b/.test(btnTag), 'слот .header-fs-btn потерян');
assert.ok(/@click="toggleFullscreen\(\)"/.test(btnTag),
  'тап по мини-линзе не привязан к toggleFullscreen()');
assert.ok(/v-if="me && fsSlot !== 'hidden'"/.test(btnTag),
  'слот-гвард v-if потерян (мёртвый контрол/скрытие политики)');
assert.ok(/:aria-pressed="fsAriaPressed"/.test(btnTag),
  'aria-pressed по ACK потерян (U07.2d)');
/* Ровно один экземпляр класса в разметке — нет дублей/клонов контрола. */
assert.strictEqual((INDEX.match(/\blg-mini-lens\b/g) || []).length, 1,
  'lg-mini-lens должен применяться ровно к одному узлу (кнопка ⛶)');

/* ── 2. Действие: toggleFullscreen маршрутизирует в политику ───────────── */
const toggleFn =
  APP_JS.match(/toggleFullscreen: function \(\) \{[\s\S]{0,1400}?\n      \},/);
assert.ok(toggleFn, 'toggleFullscreen не найден в app.js');
assert.ok(/__FullscreenPolicy/.test(toggleFn[0]) &&
          /policy\.request\(\)/.test(toggleFn[0]) &&
          /policy\.exit\(\)/.test(toggleFn[0]),
  'toggleFullscreen не маршрутизирует в FullscreenPolicy.request/exit ' +
  '(тап по линзе обязан вести в ту же политику, без нового состояния)');

/* ── 3. Шов стекла: материал входит в Tier-A селекторы движков ─────────── */
assert.ok(/_lgGlassSelector: function \(\) \{[\s\S]{0,400}?\.lg-mini-lens/
  .test(APP_JS), 'app.js::_lgGlassSelector потерял .lg-mini-lens');
assert.ok(/SURFACE_SELECTOR = [^;]*\.lg-mini-lens/.test(REFRACTION),
  'glass-refraction.js::SURFACE_SELECTOR потерял .lg-mini-lens');

/* ── 4. Материал в CSS: круг + rim; hit-цель ≥44×44 сохранена ──────────── */
assert.ok(/\.lg-mini-lens \{[^}]*border-radius:\s*50%/.test(CSS),
  'материал: .lg-mini-lens не круглый');
assert.ok(/\.lg-mini-lens::after \{[^}]*var\(--lg-rim\)/.test(CSS),
  'материал: rim (::after) потерян');
assert.ok(/\.header-fs-btn\s*\{[^}]*min-width:\s*44px/.test(CSS) &&
          /\.header-fs-btn\s*\{[^}]*min-height:\s*44px/.test(CSS),
  'тач-цель ⛶ ≥44×44 потеряна (U07.2)');

/* ── 5. Hover/active НЕ стирают материал плоским фоном ─────────────────── */
assert.ok(!/\.header-fs-btn:hover[^{]*\{[^}]*\bbackground\s*:/.test(CSS) &&
          !/\.header-fs-btn:active[^{]*\{[^}]*\bbackground\s*:/.test(CSS),
  '.header-fs-btn:hover/:active снова красят плоский фон поверх линзы');
assert.ok(/\.header-fs-btn:hover\s*\{[^}]*filter:\s*brightness/.test(CSS),
  'hover-обратная связь линзы (brightness) потеряна');

console.log('MINI-LENS-BINDING-OK');
