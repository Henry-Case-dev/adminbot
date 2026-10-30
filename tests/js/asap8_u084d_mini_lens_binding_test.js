'use strict';
/* U08.4d/U08.5.1 (asap8-v6.3, слайс FE-GLASS-MINILENS) — REGRESSION.
 *
 * ПЕРЕКВАЛИФИЦИРОВАН 31.10.2026 (EVOL-023 §4, ревью W7 F1). Прежняя редакция
 * защищала ПОЛОЖИТЕЛЬНУЮ привязку: «кнопка ⛶ обязана нести .lg-mini-lens»
 * (REV-W2-N1 — линза вместо «64px затемнённого квадрата»). Владелец/ревью
 * EVOL-023 §4 требует обратное: ⛶ — компактный ghost-icon с прозрачной
 * областью нажатия и БЕЗ тяжёлой декоративной подложки; в шапке линза
 * читалась отдельным стеклянным объектом. Поэтому проверка стала
 * ОТРИЦАТЕЛЬНОЙ (материала на функциональной кнопке быть не должно), а
 * материал .lg-mini-lens остаётся в CSS/движке для изолированного
 * glass-тест-стенда. Контракт W2-GLASS не отменён — отменена только привязка
 * к функциональному контролу. Действие, слот-гвард и aria не менялись.
 *
 * Запуск: node tests/js/asap8_u084d_mini_lens_binding_test.js
 * → MINI-LENS-BINDING-OK
 * TEST-LIFECYCLE: REGRESSION owner=U08.4d/U08.5.1 → superseded-by EVOL-023 §4
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

/* ── 1. Разметка: кнопка ⛶ — только слот, БЕЗ декоративного материала ──── */
const btnMatch = INDEX.match(/<button[^>]*header-fs-btn[^>]*>/);
assert.ok(btnMatch, 'кнопка ⛶ (header-fs-btn) не найдена в index.html');
const btnTag = btnMatch[0];
assert.ok(!/class="[^"]*\blg-mini-lens\b[^"]*"/.test(btnTag),
  'EVOL-023 §4: на функциональной кнопке снова висит декоративная мини-линза');
assert.ok(!/class="[^"]*\blg-mini-lens\b/.test(INDEX),
  'lg-mini-lens не должен применяться ни к одному узлу разметки');
assert.ok(/\bheader-fs-btn\b/.test(btnTag), 'слот .header-fs-btn потерян');
assert.ok(/@click="toggleFullscreen\(\)"/.test(btnTag),
  'тап по ⛶ не привязан к toggleFullscreen()');
assert.ok(/v-if="me && fsSlot !== 'hidden'"/.test(btnTag),
  'слот-гвард v-if потерян (мёртвый контрол/скрытие политики)');
assert.ok(/:aria-pressed="fsAriaPressed"/.test(btnTag),
  'aria-pressed по ACK потерян (U07.2d)');

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

/* ── 4. Материал в CSS сохранён (тест-стенд), кнопка — ghost ───────────── */
assert.ok(/\.lg-mini-lens \{[^}]*border-radius:\s*50%/.test(CSS),
  'материал: .lg-mini-lens не круглый (нужен glass-тест-стенду)');
assert.ok(/\.lg-mini-lens::after \{[^}]*var\(--lg-rim\)/.test(CSS),
  'материал: rim (::after) потерян');
/* Кнопка: прозрачная hit-цель ≥44×44, объявленного материала нет. */
{
  const m = /\n\.header-fs-btn\s*\{([^}]*)\}/.exec(CSS);
  assert.ok(m, 'правило .header-fs-btn не найдено');
  const decl = m[1].replace(/\/\*[\s\S]*?\*\//g, '');
  assert.ok(/background:\s*transparent/.test(decl),
    'кнопка ⛶: прозрачная область нажатия не объявлена');
  assert.ok(!/radial-gradient|rgba\(|border-radius:\s*50%/.test(decl),
    'кнопка ⛶ снова несёт декоративный материал линзы');
}
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
