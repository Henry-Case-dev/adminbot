'use strict';
/* F6 round 10.21 — регресс-зонды UI-аудита (T-1990…T-2000).
 *
 * Покрытие (соответствует UI_AUDIT_REPORT.md, spec §5):
 *   1. Liquid Glass: токены `--glass-bg`/`--glass-blur` + glass-set селекторы,
 *      sticky `--glass-bg-strong`; фолбэк `@supports not (backdrop-filter)`.
 *   2. CSS Grid: `.prov-grid/.module-list/.hub-grid` → `repeat(auto-fit,
 *      minmax(320px, 1fr))`; мобильный `@media (max-width:479px)` → 1fr.
 *   3. Data binding: `SECRET_MASK` (12×•), `isSecretMask/hasSecretMask`,
 *      `_seedSecretMasks`, `blockFieldValue` для configured-секрета.
 *   4. Градиент: `--grad-speed` ∈ [5,8]s, `--grad-d` оранжевый, reduced-motion
 *      глушит анимацию.
 *   5. Sticky (M-1): `.sticky-spacer` + `padding-bottom:0` у
 *      `.scroll-area:has(> .sticky-save)` (панель прижата к низу, не 88px),
 *      фолбэк `@supports not (selector(:has(*)))` без padding-bottom.
 *   6. Инвариант меню: 26 вкладок / 6 NAV_ITEMS / 13 модулей.
 *   7. РЕГРЕСС round 10.21 (T-1998): `_syntheticGroup` обязан быть МЕТОДОМ
 *      (ранее жил в `computed` → `TypeError ... is not a function` при
 *      открытии окна модуля «Выжимка видео»).
 *
 * Запуск: node tests/js/round1021_ui_audit_test.js   (печатает JS-UNIT-OK)
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

const SECRET_MASK = '\u2022'.repeat(12);

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component(name, compOpts) {
        global.__components = global.__components || {};
        global.__components[name] = compOpts;
      },
      provide() {}, use() {}, mount() {},
    };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
const _bodyChildren = [];
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    const el = {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() {
        const idx = _bodyChildren.indexOf(el);
        if (idx >= 0) _bodyChildren.splice(idx, 1);
      },
    };
    return el;
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) {
      const idx = _bodyChildren.indexOf(el);
      if (idx >= 0) _bodyChildren.splice(idx, 1);
      return el;
    },
  },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('no'); } } },
});
global.sessionStorage = {
  _s: {},
  getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;
const data = captured.data();

const INDEX = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
const CSS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'static', 'app.css'), 'utf8');

// ── 1. Liquid Glass: токены + glass-set ─────────────────────────────────────
{
  assert.ok(/--glass-bg\s*:\s*rgba\(21,\s*27,\s*42,\s*0?\.5\)/.test(CSS),
    'glass: токен --glass-bg = rgba(21,27,42,.5) (§8)');
  assert.ok(/--glass-blur\s*:\s*blur\(16px\)/.test(CSS),
    'glass: токен --glass-blur = blur(16px)');
  assert.ok(/--glass-bg-strong\s*:\s*rgba\(21,\s*27,\s*42,\s*0?\.85\)/.test(CSS),
    'glass: токен --glass-bg-strong = rgba(21,27,42,.85) (§8)');
  const glassSet = CSS.match(/\.card,\s*\.modal-card,[\s\S]*?\.oversight-panel\s*\{([^}]*)\}/);
  assert.ok(glassSet, 'glass: найдено правило glass-set');
  assert.ok(/background-color:\s*var\(--glass-bg\)/.test(glassSet[1]),
    'glass: набор использует var(--glass-bg)');
  assert.ok(/backdrop-filter:\s*var\(--glass-blur\)/.test(glassSet[1]),
    'glass: набор использует var(--glass-blur)');
  for (const sel of ['.modal-card', '.card', '.module-card', '.hub-card',
    '.prov-block', 'details.advanced', '.scope-panel', '.glass-panel',
    '.oversight-panel']) {
    assert.ok(glassSet[0].indexOf(sel) >= 0,
      'glass: селектор ' + sel + ' в наборе');
  }
  const stickyGlass = CSS.match(/\.sticky-save\s*\{([^}]*)\}/);
  assert.ok(stickyGlass &&
    /background-color:\s*var\(--glass-bg-strong\)/.test(stickyGlass[1]) &&
    /backdrop-filter:\s*var\(--glass-blur\)/.test(stickyGlass[1]),
    'glass: sticky-save — непрозрачный --glass-bg-strong + blur');
  const fb = CSS.match(
    /@supports not \(\(backdrop-filter:[\s\S]*?\)\)\s*\{([\s\S]*?)\n    \}/);
  assert.ok(fb, 'glass: фолбэк @supports not (backdrop-filter) есть');
  assert.ok(/--glass-bg-strong/.test(fb[1]),
    'glass: фолбэк переводит на --glass-bg-strong (не прозрачный)');
  assert.strictEqual(INDEX.indexOf('modal-card card card-solid'), -1,
    'glass: нет запретной пары modal-card + card-solid');
}

// ── 2. CSS Grid: единый контракт + мобильный вид ────────────────────────────
{
  const gridRule = CSS.match(
    /\.prov-grid,\s*\.module-list,\s*\.hub-grid\s*\{([^}]*)\}/);
  assert.ok(gridRule, 'grid: единое правило для prov/module/hub');
  assert.ok(/repeat\(auto-fit,\s*minmax\(320px,\s*1fr\)\)/.test(gridRule[1]),
    'grid: auto-fit minmax(320px,1fr)');
  const mobileBlocks = CSS.match(
    /@media \(max-width: 479px\)\s*\{[\s\S]*?\n    \}/g) || [];
  assert.ok(mobileBlocks.some((b) => b.indexOf('.prov-grid') >= 0 &&
    /grid-template-columns:\s*1fr/.test(b)),
    'grid: на ≤479px — одна колонка (1fr)');
  const branch = INDEX.slice(INDEX.indexOf("activeTab === 'llm_providers'"),
    INDEX.indexOf("activeTab === 'llm_providers'") + 1200);
  assert.ok(branch.indexOf('prov-grid') >= 0,
    'grid: ветка «ИИ» использует prov-grid');
  assert.ok(INDEX.indexOf('max-w-3xl') < 0,
    'grid: с .prov-block снят max-w-3xl');
}

// ── 3. Data binding: маска секретов (F9/ADR-1025-22 D1) ─────────────────────
{
  assert.strictEqual(SECRET_MASK.length, 12, 'маска: ровно 12 символов');
  assert.strictEqual(typeof methods._seedSecretMasks, 'function',
    'маска: _seedSecretMasks — метод (страховочная очистка)');
  assert.strictEqual(methods.isSecretMask(SECRET_MASK), true);
  assert.strictEqual(methods.isSecretMask('real'), false);
  assert.strictEqual(methods.hasSecretMask(SECRET_MASK + 'X'), true);
  assert.strictEqual(methods.hasSecretMask('X'), false);
  // F9/D1: _seedSecretMasks больше НЕ засеивает маску в keyDrafts.
  const ctx = {
    isKeyConfigured: methods.isKeyConfigured,
    keyDrafts: { legacy: SECRET_MASK + 'typed' },
    configItems: [
      { key: 'CHECKUP_BETTERSTACK_SQL_PASSWORD', category: 'keys', secret: true,
        value: { configured: true, last4: 'FAKE' } },
      { key: 'keys.none', category: 'keys', secret: true, value: null },
    ],
  };
  methods._seedSecretMasks.call(ctx);
  assert.strictEqual(ctx.keyDrafts['CHECKUP_BETTERSTACK_SQL_PASSWORD'], undefined,
    'F9/D1: configured-секрет НЕ засеивается маской');
  assert.strictEqual(ctx.keyDrafts['keys.none'], undefined,
    'маска: null → поле пустое');
  assert.strictEqual(ctx.keyDrafts.legacy, undefined,
    'F9/D1: legacy/композитная маска вычищена из черновиков');
  // F9/D1: blockFieldValue для секрета → '' (маска — display-индикатор).
  const bctx = {
    blockDrafts: {},
    configItems: [
      { key: 'keys.llm_api_key', type: 'str', secret: true, category: 'keys',
        value: { configured: true, last4: '1234' } },
      { key: 'models.empty', type: 'str', value: null },
    ],
  };
  assert.strictEqual(methods.blockFieldValue.call(
    bctx, { key: 'keys.llm_api_key', secret: true }), '',
    'F9/D1: provider-секрет → пустое поле (не маска)');
  assert.strictEqual(methods.blockFieldValue.call(
    bctx, { key: 'models.empty' }), '', 'маска: null → пусто');
  // F9/D3: display-индикатор отдаёт маску.
  assert.strictEqual(methods.secretDisplay.call(
    bctx, { key: 'keys.llm_api_key' }).maskText,
    '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022' + '1234',
    'F9/D3: secretDisplay → ••••••••last4');
}

// ── 4. Градиент: скорость, оранжевый, reduced-motion ───────────────────────
{
  const speed = CSS.match(/--grad-speed\s*:\s*([\d.]+)s/);
  assert.ok(speed, 'градиент: --grad-speed задан');
  const val = parseFloat(speed[1]);
  assert.ok(val >= 60 && val <= 90,
    'F2/T-2544: --grad-speed ∈ [60,90]s (получено ' + val + ')');
  const slow = CSS.match(/--grad-speed-slow\s*:\s*([\d.]+)s/);
  assert.ok(slow && parseFloat(slow[1]) >= 90 && parseFloat(slow[1]) <= 120,
    'F2/T-2544: --grad-speed-slow ∈ [90,120]s');
  const d = CSS.match(/--grad-d\s*:\s*(#[0-9A-Fa-f]{6})/);
  assert.ok(d, 'градиент: --grad-d задан');
  const rgb = [parseInt(d[1].slice(1, 3), 16), parseInt(d[1].slice(3, 5), 16),
    parseInt(d[1].slice(5, 7), 16)];
  // F2/T-2545: оранжевый стоп убран — --grad-d приглушённый синий (B ≥ R).
  assert.ok(rgb[2] > rgb[0] && rgb[1] > rgb[0],
    'F2/T-2545: --grad-d не оранжевый (' + d[1] + ')');
  const rmBlocks = CSS.match(
    /@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?\n    \}/g) || [];
  assert.ok(rmBlocks.some((b) => b.indexOf('body::before') >= 0 &&
    /animation:\s*none/.test(b)),
    'градиент: reduced-motion глушит body::before');
}

// ── 5. Sticky (M-1): панель прижата к низу, не «висит» на 88px ──────────────
{
  const m = CSS.match(/\.scroll-area:has\(> \.sticky-save\)\s*\{([^}]*)\}/);
  assert.ok(m, 'sticky: правило .scroll-area:has(> .sticky-save)');
  assert.ok(/scroll-padding-bottom:\s*var\(--sticky-save-h\)/.test(m[1]),
    'sticky: сохранён scroll-padding-bottom');
  const pb = m[1].match(/(?:^|[;\s])padding-bottom\s*:\s*([^;]+)/);
  assert.ok(!pb || /^0(px)?$/.test(pb[1].trim()),
    'sticky(M-1): padding-bottom контейнера = 0 (панель прижата к низу)');
  assert.ok(/\.sticky-spacer\s*\{[^}]*height:\s*var\(--sticky-save-h\)/.test(CSS),
    'sticky: .sticky-spacer резервирует место над панелью');
  assert.ok(/class="sticky-spacer[^"]*"[^>]*><\/div>\s*<sticky-save/.test(INDEX),
    'sticky: спейсер стоит непосредственно перед <sticky-save>');
  assert.strictEqual((INDEX.match(/<sticky-save/g) || []).length >= 2, true,
    'sticky: панель есть во всех ветках сохранения (config/modules/access)');
  const fb = CSS.match(/@supports not \(selector\(:has\(\*\)\)\)\s*\{([^}]*)\}/);
  assert.ok(fb, 'sticky: фолбэк @supports not (:has())');
  assert.ok(!/(?:^|[;\s{])padding-bottom\s*:/.test(fb[1]),
    'sticky(M-1/L-3): фолбэк НЕ добавляет padding-bottom');
}

// ── 6. Инвариант меню: 26 вкладок / 6 NAV_ITEMS / 13 модулей ────────────────
{
  assert.strictEqual(data.tabs.length, 26, 'меню: 26 вкладок');
  assert.strictEqual(data.modules.length, 13, 'меню: 13 модулей');
  const navBlock = APP_JS.slice(APP_JS.indexOf('var NAV_ITEMS = ['),
    APP_JS.indexOf('];', APP_JS.indexOf('var NAV_ITEMS = [')));
  const navCount = (navBlock.match(/route:\s*'#/g) || []).length;
  assert.strictEqual(navCount, 6, 'меню: legacy NAV_ITEMS = ровно 6 (OFF)');
  // F1 (T-2393, SUPERSEDE): новая IA — NAV_ITEMS_V2 = 7 пунктов.
  const v2Block = APP_JS.slice(APP_JS.indexOf('var NAV_ITEMS_V2 = ['),
    APP_JS.indexOf('];', APP_JS.indexOf('var NAV_ITEMS_V2 = [')));
  const v2Count = (v2Block.match(/route:\s*'#/g) || []).length;
  assert.strictEqual(v2Count, 7, 'меню: NAV_ITEMS_V2 = ровно 7 (ON)');
}

// ── 7. Регресс round 10.21 (T-1998): _syntheticGroup — метод, не computed ───
{
  assert.strictEqual(typeof methods._syntheticGroup, 'function',
    'T-1998: _syntheticGroup объявлен МЕТОДОМ (вызывается с аргументами)');
  assert.strictEqual(computed._syntheticGroup, undefined,
    'T-1998: в computed его больше нет (иначе TypeError в render)');
  const ctx = {
    configSearch: '',
    configItems: [
      { category: 'content', group: 'content_media', title: 'Медиа',
        key: 'content.media_enabled' },
      { category: 'content', group: 'other', title: 'X', key: 'content.x' },
    ],
    configGroups: [{ id: 'content_media', title: 'Медиа' }],
  };
  const grp = methods._syntheticGroup.call(ctx, 'content', 'content_media');
  assert.ok(grp && grp.items.length === 1,
    'T-1998: _syntheticGroup возвращает синтетическую группу');
  assert.strictEqual(
    methods._syntheticGroup.call(ctx, 'content', 'missing'), null,
    'T-1998: пустая группа → null');
}

// ── 8. L-4 round 10.21 (T-1993): панель контекста не уезжает за край ────────
{
  assert.strictEqual(typeof methods.positionScopePanel, 'function',
    'L-4: positionScopePanel — метод (коллизионная коррекция)');
  assert.ok(/scopePanelStyle/.test(INDEX),
    'L-4: панель использует :style="scopePanelStyle"');
  let applied = null;
  const ctx = {
    scopeOpen: true, scopePanelStyle: {},
    $nextTick(cb) { cb(); },
  };
  const oldDoc = global.document;
  global.document = Object.assign({}, oldDoc, {
    querySelector(sel) {
      if (sel !== '.scope-panel') return null;
      return {
        closest() { return { getBoundingClientRect: () => ({ left: 24, right: 214 }) }; },
        getBoundingClientRect: () => ({ left: -46, right: 214 }),
      };
    },
    documentElement: { clientWidth: 1440 },
  });
  methods.positionScopePanel.call(ctx);
  applied = ctx.scopePanelStyle;
  global.document = oldDoc;
  assert.strictEqual(applied.left, '0',
    'L-4: панель с левым клипом якорится влево');
  assert.strictEqual(applied.right, 'auto',
    'L-4: right сбрасывается');
  assert.ok(/px$/.test(applied.maxWidth) && parseInt(applied.maxWidth, 10) > 200,
    'L-4: maxWidth ограничивает панель вьюпортом');
}

console.log('JS-UNIT-OK');
