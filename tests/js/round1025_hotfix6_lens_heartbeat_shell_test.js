'use strict';
/* hotfix6 round 10.25 (T-2583…T-2613, ADR-1025-12) — регресс областей A/B/C/D:
 *   A  — преломление на foreground-линзе (#lg-lens, ::before), БЕЗ
 *        backdrop url-фильтра; tier по feature-detect + перф-кап UI_LENS_MAX_NODES.
 *   B  — нижний offset = max(A,B,C) (contentSafeAreaInset/safeAreaInset) — в
 *        round1025_hotfix4_shell_test.js (здесь — сквозной инвариант).
 *   C  — §15: чистая машина состояний (гистерезис/UNKNOWN/reduced-motion),
 *        телеметрия отделена от рендера, Canvas 2D (не WebGL).
 *   D  — двухстрочная шапка (headerCompactV2), резерв --header-h, fullscreen.
 *
 * Падает на старом коде (backdrop url-фильтр, SVG-heartbeat, однорядная шапка).
 * Запуск: node tests/js/round1025_hotfix6_lens_heartbeat_shell_test.js
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
  matchMedia: () => ({ matches: false }),
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

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const CSS = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const TG_INIT = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'telegram-init.js'), 'utf8');

function firstPartyWeb() {
  const root = path.join(ROOT, 'web');
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

// ── A. Преломление без backdrop url-фильтра ─────────────────────────────────
{
  const files = firstPartyWeb();
  const offenders = Object.entries(files).filter(([, t]) =>
    /backdrop-filter\s*:\s*url\(/.test(t));
  assert.deepStrictEqual(offenders.map(([p]) => p), [],
    'A: нигде нет backdrop url-фильтра (§9)');
  assert.ok(/id="lg-lens"/.test(INDEX), 'A: inline-фильтр #lg-lens');
  assert.ok(/--glass-displace\s*:\s*url\(#lg-lens\)/.test(CSS),
    'A: --glass-displace → url(#lg-lens)');
  const lens = CSS.match(/\[data-glass="a"\]::before\s*\{([^}]*)\}/);
  assert.ok(lens, 'A: foreground-линза ::before');
  assert.ok(lens[1].indexOf('var(--glass-displace)') >= 0, 'A: filter линзы');
  assert.ok(/radial-gradient/.test(lens[1]) && /mask-image/.test(lens[1]),
    'A: edge-weighted радиальная маска');
  // HOTFIX8 (ADR-1025-16 D2): панели выведены из цветной allow-линзы A →
  // нейтральный `data-glass="shell"` (без teal/blue/violet ореола). Уровень A
  // остаётся у контентных карточек (allow-list непуст).
  for (const sel of ['class="app-sidebar" data-glass="shell"',
                     'class="app-drawer" :class',
                     'class="bottom-nav" data-glass="shell"',
                     'class="more-sheet" data-glass="shell"']) {
    assert.ok(INDEX.indexOf(sel) >= 0, 'A2: панель в shell-слое: ' + sel);
  }
  assert.ok(/header class="main-header header-sticky[^>]*\n[^>]*data-glass="shell"/.test(INDEX),
    'A2: шапка в shell-слое');
  assert.ok(INDEX.indexOf('data-glass="a"') >= 0,
    'A: контентный allow-list A сохранён');
  // Перф-кап + override.
  assert.strictEqual(methods._lensMaxNodes.call({ me: null }), 6,
    'A: дефолт UI_LENS_MAX_NODES=6');
  assert.strictEqual(
    methods._lensMaxNodes.call({ me: { ui_flags: { UI_LENS_MAX_NODES: 3 } } }), 3,
    'A: кап из ui_flags');
  assert.strictEqual(
    methods._glassTierOverride.call({ me: { ui_flags: { UI_GLASS_TIER_OVERRIDE: 'b' } } }),
    'b', 'A: override=b');
  assert.strictEqual(
    methods._glassTierOverride.call({ me: { ui_flags: { UI_GLASS_TIER_OVERRIDE: 'wat' } } }),
    'auto', 'A: невалидный override → auto');
}

// ── B. Сквозной инвариант нижнего offset (детали — hotfix4-тест) ────────────
{
  assert.ok(TG_INIT.indexOf('__computeTgBottomOffset') >= 0,
    'B: чистая функция offset экспонирована');
  assert.ok(/Math\.max\(a, b, c\)/.test(TG_INIT), 'B: offset = max(A,B,C)');
  assert.ok(/contentSafeAreaInset/.test(TG_INIT), 'B: учтён contentSafeAreaInset');
}

// ── C. §15: машина состояний / телеметрия / Canvas ─────────────────────────
{
  const tr = methods._heartbeatTransition;
  assert.strictEqual(typeof tr, 'function', 'C: _heartbeatTransition — метод');

  // Нет данных / устарело → UNKNOWN (не «0»).
  assert.strictEqual(tr({ missing: true }, { state: 'healthy' }).state, 'unknown',
    'C: нет данных → UNKNOWN');
  assert.strictEqual(tr({ cpu: 0.1, stale: true }, { state: 'healthy' }).state,
    'unknown', 'C: устаревшая телеметрия → UNKNOWN');
  // Спокойно.
  assert.strictEqual(tr({ cpu: 0.2, mem: 0.1, disk: 0.1, botOk: true },
    { state: 'unknown', ema: null }).state, 'healthy', 'C: низкая нагрузка → HEALTHY');
  // Вход в WARNING на 0.70 (первый сэмпл ema = m).
  const w = tr({ cpu: 0.70, botOk: true }, { state: 'healthy', ema: null });
  assert.strictEqual(w.state, 'warning', 'C: enter WARNING @0.70');
  // Гистерезис: на 0.68 из WARNING НЕ выходим (exit 0.65).
  let keep = { state: 'warning', ema: 0.70 };
  keep = tr({ cpu: 0.68, botOk: true }, keep);
  assert.strictEqual(keep.state, 'warning', 'C: гистерезис WARNING (0.68 держит)');
  // Ниже 0.65 → HEALTHY (с учётом EMA: берём несколько шагов).
  let drop = { state: 'warning', ema: 0.70 };
  for (let i = 0; i < 6; i++) drop = tr({ cpu: 0.30, botOk: true }, drop);
  assert.strictEqual(drop.state, 'healthy', 'C: exit WARNING <0.65 → HEALTHY');
  // Вход в CRITICAL на 0.90.
  assert.strictEqual(tr({ cpu: 0.92, botOk: true },
    { state: 'healthy', ema: null }).state, 'critical', 'C: enter CRITICAL @0.90');
  // Гистерезис CRITICAL: 0.86 держит, ниже 0.85 → WARNING.
  let cr = { state: 'critical', ema: 0.92 };
  cr = tr({ cpu: 0.86, botOk: true }, cr);
  assert.strictEqual(cr.state, 'critical', 'C: гистерезис CRITICAL (0.86 держит)');
  let cr2 = { state: 'critical', ema: 0.84 };
  cr2 = tr({ cpu: 0.80, botOk: true }, cr2);
  assert.strictEqual(cr2.state, 'warning', 'C: exit CRITICAL <0.85 → WARNING');
  // Бот не running → CRITICAL.
  assert.strictEqual(tr({ cpu: 0.1, botOk: false },
    { state: 'healthy' }).state, 'critical', 'C: bot.state ≠ running → CRITICAL');
  // Никаких «BPM»/выдуманных производных в коде §15.
  assert.ok(!/bpm\s*[:=]/i.test(APP_JS), 'C: без выдуманного BPM');
  // Телеметрия ОТДЕЛЕНА от рендера: сеть только в loadStatus, не в кадре.
  assert.ok(APP_JS.indexOf('this._applyHeartbeatSample(this.heartbeatSample())') >= 0,
    'C: телеметрия обновляет снимок из /api/status');
  const dStart = APP_JS.indexOf('_hbDraw: function');
  const dEnd = APP_JS.indexOf('loadStatus: async function', dStart);
  const drawBody = APP_JS.slice(dStart, dEnd > dStart ? dEnd : dStart + 4000);
  assert.ok(drawBody.indexOf('fetch(') < 0 && drawBody.indexOf('this.api(') < 0,
    'C: рендер-кадр без сети');
  // Canvas 2D, НЕ WebGL.
  assert.ok(APP_JS.indexOf("getContext('2d')") >= 0, 'C: Canvas 2D');
  assert.ok(!/getContext\(['"]webgl/i.test(APP_JS), 'C: WebGL запрещён');
  assert.ok(/requestAnimationFrame/.test(APP_JS), 'C: цикл rAF');
  // Разметка: canvas под флагом, legacy SVG под v-else (откат байт-в-байт).
  assert.ok(/class="hb-canvas"/.test(INDEX), 'C: <canvas class="hb-canvas">');
  assert.ok(/v-if="heartbeatCanvasEnabled"/.test(INDEX), 'C: флаг UI_HEARTBEAT_CANVAS_ENABLED');
  assert.ok(/class="ekg"/.test(INDEX), 'C: legacy SVG сохранён (v-else)');
  assert.ok(/class="hb-tip"/.test(INDEX), 'C: тултип hover/tap');
  assert.ok(INDEX.indexOf('heartbeatTip.cpu') >= 0 &&
    INDEX.indexOf('heartbeatTip.disk') >= 0, 'C: тултип: CPU/RAM/диск');
  // C1: overflow-инвариант контейнера.
  assert.ok(/\.status-block \{ max-width: 100%; overflow: hidden; \}/.test(CSS),
    'C1: .status-block ограничен');
  assert.ok(/\.hb-canvas \{[^}]*width: 100%/.test(CSS), 'C1: canvas width:100%');
  assert.ok(/radial-gradient\(ellipse at center/.test(CSS), 'A: edge-маска');
  // reduced-motion → статичный кадр.
  assert.ok(/prefers-reduced-motion: reduce[\s\S]{0,260}\.hb-canvas/.test(CSS),
    'C: reduced-motion правило для canvas');
  assert.ok(/_prefersReducedMotion\(\)\) \{ (this|self)\._hbDraw\(0\); return; \}/
    .test(APP_JS.replace(/\s+/g, ' ')) ||
    /_prefersReducedMotion\(\)\) \{ (this|self)\._hbDraw\(0\)/.test(APP_JS),
    'C: reduced-motion → один статичный кадр');

  // heartbeatCanvasEnabled учитывает ui_flags + canvas-окружение.
  const enabled = captured.computed.heartbeatCanvasEnabled.call({
    uiFlag: () => true,
  });
  assert.strictEqual(enabled, true, 'C: canvas-флаг ON + ctx доступен');
  assert.strictEqual(captured.computed.heartbeatCanvasEnabled.call({
    uiFlag: () => false,
  }), false, 'C: OFF → SVG (откат)');

  // ── Dwell (MEDIUM/T-2601): одиночный выброс не меняет tier, N подряд — меняет.
  {
    let dwell = { state: 'healthy', ema: 0.88 };
    dwell = tr({ cpu: 1.0, botOk: true }, dwell);
    assert.strictEqual(dwell.state, 'healthy',
      'C: одиночный выброс НЕ эскалирует (dwell)');
    assert.strictEqual(dwell.dwellPending, 'critical', 'C: pending tier = critical');
    assert.strictEqual(dwell.dwellCount, 1, 'C: счётчик подтверждений = 1');
    dwell = tr({ cpu: 1.0, botOk: true }, dwell);
    assert.strictEqual(dwell.state, 'critical', 'C: 2 подтверждающих подряд → CRITICAL');
    // Возврат к норме сбрасывает pending (счётчик заново).
    let reset = { state: 'healthy', ema: 0.88 };
    reset = tr({ cpu: 1.0, botOk: true }, reset);
    reset = tr({ cpu: 0.2, botOk: true }, reset);
    assert.strictEqual(reset.dwellPending, null,
      'C: возврат к норме сбрасывает pending');
    reset = tr({ cpu: 1.0, botOk: true }, reset);
    assert.strictEqual(reset.state, 'healthy',
      'C: после сброса одиночный выброс снова не эскалирует');
  }

  // ── UNKNOWN-семантика (MEDIUM/T-2603): missing ≠ bad; polling_error → CRITICAL.
  {
    const hs = methods.heartbeatSample;
    assert.strictEqual(hs.call({ statusData: null }).missing, true,
      'C: нет statusData → missing');
    assert.strictEqual(hs.call({ statusData: { server: {} } }).reason,
      'нет состояния бота', 'C: нет bot.state → missing/UNKNOWN (не CRITICAL)');
    const noGen = hs.call({ statusData: {
      bot: { state: 'running' },
      server: { cpu_percent: 10, memory: { percent: 20 }, disk: { percent: 5 } } } });
    assert.strictEqual(noGen.stale, true, 'C: нет generated_at → stale (UNKNOWN)');
    assert.strictEqual(noGen.reason, 'нет отметки времени',
      'C: причина «нет отметки времени» (не «свежо»/не «0»)');
    const perr = hs.call({ statusData: {
      bot: { state: 'polling_error' },
      uptime: { generated_at: new Date().toISOString() },
      server: { cpu_percent: 10, memory: { percent: 20 }, disk: { percent: 5 } } } });
    assert.strictEqual(perr.botOk, false, 'C: polling_error → botOk=false (CRITICAL)');
    const fresh = hs.call({ statusData: {
      bot: { state: 'running' },
      uptime: { generated_at: new Date().toISOString() },
      server: { cpu_percent: 10, memory: { percent: 20 }, disk: { percent: 5 } } } });
    assert.strictEqual(fresh.stale, false, 'C: свежая телеметрия → not stale');
    assert.strictEqual(
      tr({ missing: true, reason: 'нет отметки времени' },
        { state: 'healthy' }).reason,
      'нет отметки времени', 'C: причина UNKNOWN пробрасывается в состояние');
  }

  // ── C2-OFF (HIGH/T-2599): OFF-путь реально откатывает семантику heartbeat.
  {
    const legacy = captured.computed.heartbeatLegacy;
    assert.strictEqual(typeof legacy, 'function',
      'C2-OFF: heartbeatLegacy — computed');
    const lo = legacy.call({ statusData: {
      server: { cpu_percent: 10, memory: { percent: 20 } } } });
    assert.strictEqual(lo.badge, 'badge-ok', 'C2-OFF: <0.5 → badge-ok');
    assert.strictEqual(lo.label, 'спокойный 20%', 'C2-OFF: метка «спокойный N%»');
    assert.strictEqual(lo.period, 2.4, 'C2-OFF: период 2.4s');
    const mid = legacy.call({ statusData: { server: { cpu_percent: 60 } } });
    assert.strictEqual(mid.badge, 'badge-warn', 'C2-OFF: 0.5..0.8 → badge-warn');
    assert.strictEqual(mid.period, 1.4, 'C2-OFF: период 1.4s');
    const hi = legacy.call({ statusData: { server: { cpu_percent: 90 } } });
    assert.strictEqual(hi.badge, 'badge-err', 'C2-OFF: >0.8 → badge-err');
    assert.strictEqual(hi.period, 0.8, 'C2-OFF: период 0.8s');
    const la = legacy.call({ statusData: { server: {
      loadavg: [2, 1, 0.5], cpu_count: 4, cpu_percent: 5 } } });
    assert.strictEqual(la.label, 'повышен 50%',
      'C2-OFF: ratio = loadavg[0]/cpu_count (приоритет над CPU%)');
    const none = legacy.call({ statusData: { server: {} } });
    assert.strictEqual(none.label, 'спокойный',
      'C2-OFF: нет метрик → «спокойный» (метрик нет — нейтраль)');
    const zero = legacy.call({ statusData: { server: { cpu_percent: 0 } } });
    assert.strictEqual(zero.label, 'спокойный 0%',
      'C2-OFF: cpu=0 — это метрика, «спокойный 0%»');
    // Флаг OFF → heartbeat возвращает legacy; ON → семантика состояний.
    const on = captured.computed.heartbeat.call({
      heartbeatCanvasEnabled: true, hbState: 'critical', hbReason: 'x' });
    assert.strictEqual(on.label, 'критично', 'C2-ON: семантика состояний');
    const off = captured.computed.heartbeat.call({
      heartbeatCanvasEnabled: false, heartbeatLegacy: lo });
    assert.deepStrictEqual(off, lo, 'C2-OFF: heartbeat === heartbeatLegacy');
    assert.ok(/'ekg-' \+ heartbeat\.level/.test(INDEX),
      'C2-OFF: legacy ekg-класс уровня применяется при OFF');
  }

  // ── a11y (LOW/T-2602): тултип имеет id, canvas — aria-describedby.
  assert.ok(/id="hb-tip"/.test(INDEX), 'C: тултип имеет id="hb-tip"');
  assert.ok(/aria-describedby="hb-tip"/.test(INDEX),
    'C: canvas aria-describedby → тултип');

  // ── reduced-motion → tier B (осознанное решение, ADR-1025-12 D1).
  assert.ok(/reduced\) reason = 'reduced-motion'/.test(APP_JS),
    'A: reduced-motion уводит tier A → B (осознанное решение)');
}

// ── D. Двухстрочная шапка / резерв высоты / fullscreen ─────────────────────
{
  assert.strictEqual(typeof captured.computed.headerCompactV2, 'function',
    'D: headerCompactV2 — computed');
  assert.strictEqual(captured.computed.headerCompactV2.call({
    iaV2: true, uiFlag: () => true,
  }), true, 'D: iaV2 + флаг ON → компактная шапка');
  assert.strictEqual(captured.computed.headerCompactV2.call({
    iaV2: false, uiFlag: () => true,
  }), false, 'D: IA legacy → legacy-шапка (байт-в-байт)');
  assert.strictEqual(captured.computed.headerCompactV2.call({
    iaV2: true, uiFlag: () => false,
  }), false, 'D: UI_HEADER_COMPACT_V2=OFF → legacy');
  // Разметка: строка 2 обёрнута в .header-scope-row; ⛶ — правый верхний угол.
  assert.ok(INDEX.indexOf('header-scope-row') >= 0, 'D: обёртка строки 2 шапки');
  assert.ok(/class="btn-ghost text-xs px-1.5 py-1 shrink-0 header-fs-btn"/
    .test(INDEX), 'D: ⛶ помечен header-fs-btn');
  assert.ok(/\.header-compact-v2 \.header-scope-row \{[\s\S]{0,120}flex: 1 1 100%/
    .test(CSS), 'D: строка 2 — flex-basis 100% (новая строка)');
  assert.ok(/header\.header-sticky\.header-compact-v2 \.header-fs-btn \{[\s\S]{0,120}min-height: 44px/
    .test(CSS), 'D: тач-цель ⛶ ≥44×44');
  // Legacy: обёртка display:contents → однорядный вид без дублирования.
  assert.ok(/\.header-scope-row \{ display: contents; \}/.test(CSS),
    'D: legacy display:contents (сохранение раскладки)');
  // Селектор области — ровно один экземпляр (F3-инвариант).
  assert.strictEqual((INDEX.match(/\{\{ scopeLabel \}\}/g) || []).length, 1,
    'F3: один селектор области (без дублирования)');
  // Резерв высоты: токен + scroll-padding.
  assert.ok(APP_JS.indexOf('_initHeaderHeight') >= 0, 'D: _initHeaderHeight');
  assert.ok(/setProperty\('--header-h'/.test(APP_JS), 'D: --header-h из замера');
  assert.ok(/scroll-padding-top: calc\(var\(--header-h/.test(CSS),
    'D: резерв контента (--header-h)');
  // fullscreen: устойчивый toggle (камел-варианты имени метода), контракт
  // ADR-1024-24 не отменён.
  assert.ok(/requestFullScreen/.test(APP_JS) && /requestFullscreen/.test(APP_JS),
    'D: toggleFullscreen устойчив к вариантам метода');
  assert.ok(typeof methods.toggleFullscreen === 'function' &&
    typeof methods.setFullscreenFromTma === 'function',
    'D: fullscreen-sync (ADR-1024-24) сохранён');
}

console.log('HOTFIX6-LENS-HEARTBEAT-SHELL-OK');
