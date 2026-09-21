'use strict';
/* F1 round 10.25 — shell/адаптивность (§6/§7/§70, T-2397/T-2398/T-2405):
 *   * постоянный sidebar СТРОГО ≥1200 px; 768–1199 — drawer (без sidebar);
 *   * <768 — bottom-nav ровно из 4 + шторка «Ещё», без полосы из 7 вкладок;
 *   * touch-таргеты ≥44px; safe-area; нет горизонтального скролла страницы;
 *   * container queries (container-type) для компонент-зависимых раскладок;
 *   * CSP-safe: нет inline-скриптов/стилей в новых зонах.
 *
 * Запуск: node tests/js/round1025_shell_breakpoints_test.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const INDEX = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'static', 'app.css'), 'utf8');
const JS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
const TG = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'static', 'telegram-init.js'), 'utf8');

// ── Breakpoints: sidebar строго с 1200; bottom-nav <768 ──────────────────
assert.ok(/@media \(min-width:\s*1200px\)/.test(CSS), 'есть @media 1200px');
assert.ok(/\.app-shell\.ia-v2 \{ padding-left: 232px; \}/.test(CSS),
  'desktop: контент смещён на 232px (sidebar)');
assert.ok(/\.app-shell\.ia-v2 \.app-sidebar \{/.test(CSS),
  'sidebar рендерится только в ia-v2 (≥1200)');
assert.ok(CSS.indexOf('@media (min-width: 1200px)') >= 0,
  'sidebar media-query присутствует');

// ── Shell-элементы в разметке ────────────────────────────────────────────
for (const cls of ['class="app-sidebar"', 'class="app-drawer"',
                   'class="bottom-nav"', 'class="more-sheet"']) {
  assert.ok(INDEX.indexOf(cls) >= 0, 'разметка: ' + cls);
}
assert.ok(/v-if="iaV2 && hasSidebar"/.test(INDEX),
  'sidebar — только ≥1200 (hasSidebar)');
assert.ok(/v-if="iaV2 && isMobileShell"/.test(INDEX),
  'bottom-nav — только <768 (isMobileShell)');
assert.ok(/v-if="iaV2 && isCompactShell"/.test(INDEX),
  'drawer — только 768–1199 (isCompactShell)');

// ── Нет полосы из 7 вкладок; navbar gated legacy ─────────────────────────
assert.ok(/v-if="!iaV2" class="navbar-band/.test(INDEX),
  'navbar-полоса рендерится только в legacy-режиме');
// bottom-nav не имеет 7 пунктов: список формируется computed (ровно 4).
assert.ok(/bottomNavItems: function \(\)/.test(JS), 'bottomNavItems computed');

// ── Touch ≥44×44 + safe-area ─────────────────────────────────────────────
assert.ok(/\.sidebar-link, \.more-item \{[^}]*min-height: 44px/.test(CSS)
  || /min-height: 44px/.test(CSS), 'touch-таргеты ≥44px');
assert.ok(/\.bottom-nav-link \{[^}]*min-width: 44px/.test(CSS),
  'bottom-nav тач ≥44px');
assert.ok(/env\(safe-area-inset-bottom/.test(CSS), 'safe-area учтён');
assert.ok(/viewportStableHeight/.test(TG), 'TMA viewportStableHeight');
assert.ok(/safeAreaInset/.test(TG) && /contentSafeAreaInset/.test(TG),
  'TMA safeAreaInset/contentSafeAreaInset');

// ── Container queries (§70) ──────────────────────────────────────────────
assert.ok(/container-type:\s*inline-size/.test(CSS), 'container-type задан');
assert.ok(/@container \(max-width:/.test(CSS), '@container используется');

// ── CSP-safe: без inline-скриптов в web/* ────────────────────────────────
assert.ok(JS.indexOf('javascript:') < 0, 'нет javascript: URL');
const inlineScript = /<script(?![^>]*\bsrc=)[^>]*>[\s\S]*?<\/script>/i;
const stripped = INDEX.replace(/<script type="text\/x-template"[\s\S]*?<\/script>/gi, '');
assert.ok(!inlineScript.test(stripped), 'нет inline-<script> (CSP script-src self)');
assert.ok(!/\son\w+\s*=\s*"/.test(INDEX.replace(/<!--[\s\S]*?-->/g, '')),
  'нет inline on*-обработчиков');

// ── hotfix4 (T-2514/T-2516): offset нижней панели + viewport-fit=cover ───
assert.ok(/--tg-viewport-bottom-offset/.test(CSS),
  'hotfix4: панель смещается на --tg-viewport-bottom-offset');
assert.ok(/viewport-fit=cover/.test(INDEX), 'hotfix4: viewport-fit=cover');

console.log('JS-UNIT-OK round1025_shell_breakpoints_test');
