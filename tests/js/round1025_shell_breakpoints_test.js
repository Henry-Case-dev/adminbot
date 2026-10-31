'use strict';
/* F1 round 10.25 — shell/адаптивность (§6/§7/§70, T-2397/T-2398/T-2405):
 *   * постоянный sidebar СТРОГО ≥1200 px; 768–1199 — drawer (без sidebar);
 *   * D13 (§18I.14): <768 — КОМПАКТНАЯ ВЕРХНЯЯ навигация (mobile-topnav,
 *     тот же реестр navItems); bottom-nav/шторка «Ещё» УДАЛЕНЫ владельцем;
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

// ── Breakpoints: sidebar строго с 1200; mobile — верхняя навигация ────────
assert.ok(/@media \(min-width:\s*1200px\)/.test(CSS), 'есть @media 1200px');
assert.ok(/\.app-shell\.ia-v2 \{ padding-left: 216px; \}/.test(CSS),
  'desktop: контент смещён на 216px (sidebar 208–224)');
assert.ok(/\.app-shell\.ia-v2 \.app-sidebar \{/.test(CSS),
  'sidebar рендерится только в ia-v2 (≥1200)');
assert.ok(CSS.indexOf('@media (min-width: 1200px)') >= 0,
  'sidebar media-query присутствует');

// ── Shell-элементы в разметке ────────────────────────────────────────────
for (const cls of ['class="app-sidebar"', 'class="app-drawer"']) {
  assert.ok(INDEX.indexOf(cls) >= 0, 'разметка: ' + cls);
}
// D13 (§18I.14) + ASAP-UI-02 §2.1: нижней навигации, шторки «Ещё» и
// постоянной мобильной панели разделов НЕТ нигде.
assert.ok(INDEX.indexOf('class="bottom-nav"') < 0,
  'D13: bottom-nav удалён из разметки');
assert.ok(INDEX.indexOf('class="more-sheet"') < 0,
  'D13: more-sheet удалён из разметки');
assert.ok(/v-if="iaV2 && hasSidebar"/.test(INDEX),
  'sidebar — только ≥1200 (hasSidebar)');
assert.ok(INDEX.indexOf('mobile-topnav') < 0,
  'ASAP-UI-02: постоянной мобильной панели разделов нет (ни портрет, ни ландшафт)');
assert.ok(/v-if="iaV2 && hasDrawer"/.test(INDEX),
  'ASAP-UI-02: drawer — один механизм на <1200 (mobile + compact)');
assert.ok(/hasDrawer: function \(\)/.test(JS)
  && /return this\.shellMode !== 'desktop';/.test(JS),
  'ASAP-UI-02: hasDrawer = всё, кроме desktop');

// ── Нет полосы из 7 вкладок; navbar gated legacy ─────────────────────────
assert.ok(/v-if="!iaV2" class="navbar-band/.test(INDEX),
  'navbar-полоса рендерится только в legacy-режиме');

// ── Touch ≥44×44 + safe-area ─────────────────────────────────────────────
assert.ok(/min-height: 44px/.test(CSS), 'touch-таргеты ≥44px');
assert.ok(/\.header-nav-btn,\s*\n?\.header-more-btn \{[^}]*min-width: 44px/.test(
  CSS.replace(/\r/g, '')), 'иконочные кнопки шапки ≥44px');
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

// ── hotfix4 (T-2514/T-2516) + D13: нижней панели больше нет — токен
// `--tg-viewport-bottom-offset` остаётся только для legacy/Telegram-слоёв;
// viewport-fit=cover сохранён (safe-area без обрезки).
assert.ok(/viewport-fit=cover/.test(INDEX), 'hotfix4: viewport-fit=cover');

console.log('JS-UNIT-OK round1025_shell_breakpoints_test');
