'use strict';
/* HOTFIX10 round 10.25 (ADR-1025-18) — регресс:
 *   A — откат стекла: `[data-glass-surface]` — единственная цель; `dispose`
 *       удаляет ВСЕ `.ps-glass*`/`data-lg-*` (идемпотентно), функциональные
 *       цели (селектор/⛶/карточка) стекло НЕ получают; честный режим
 *       `frosted` vs `refraction`.
 *   B — контракт GlassSurface в CSS (`isolation`, `contain`, декор ниже).
 *   C — единая рабочая поверхность Main (нет max-width:1440, токен
 *       `--work-surface-bg`, лимит 1100px сохранён); без отрицательных отступов.
 *   D — единая высота: второй вычет safe-area снят, `.more-sheet` — один offset.
 *   E — `.status-block` без стекла, дизайн сердцебиения не тронут.
 *   F — OGL-фон: экспорт `resize`, пересчёт по фактическому контейнеру,
 *       viewport/uniforms, вызовы из app.js (resize/fullscreen/visualViewport).
 *   G — APP_VERSION 2.58.14, env-only флаг default OFF.
 *
 * Запуск: node tests/js/round1025_hotfix10_glass_geometry_bg_test.js
 */
const path = require('path');
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const INDEX = read('web/index.html');
const APP_JS = read('web/app.js');
const CSS = read('web/static/app.css');
const AURORA = read('web/static/aurora-flow.js');
const GLASS = read('web/static/glass.js');
const SETTINGS = read('config/settings.py');
const ROUTES = read('web/api/routes.py');

function token(name) {
  const m = CSS.match(new RegExp(name.replace(/[-]/g, '\\-') + '\\s*:\\s*([^;]+);'));
  return m ? m[1].trim() : '';
}

// ═══ A/B. Функциональная проверка glass.js на лёгком фейковом DOM ═══════════
{
  function matchOne(cls, one) {
    const sel = one.trim();
    if (sel === '[class*="ps-glass"]') return cls.indexOf('ps-glass') >= 0;
    const m = sel.match(/^\.([\w-]+)$/);
    return m ? cls.split(/\s+/).indexOf(m[1]) >= 0 : false;
  }
  function matchClass(cls, sel) {
    return sel.split(',').some((one) => matchOne(cls, one));
  }
  function makeNode(cls) {
    const node = {
      _cls: cls || '', attrs: {}, children: [], parentNode: null, isConnected: true,
      get className() { return node._cls; },
      getAttribute(n) { return Object.prototype.hasOwnProperty.call(node.attrs, n) ? node.attrs[n] : null; },
      setAttribute(n, v) { node.attrs[n] = String(v); },
      removeAttribute(n) { delete node.attrs[n]; },
      appendChild(c) { c.parentNode = node; node.children.push(c); return c; },
      removeChild(c) {
        const i = node.children.indexOf(c);
        if (i >= 0) node.children.splice(i, 1);
        c.parentNode = null; return c;
      },
      classList: {
        remove(c) { node._cls = node._cls.split(/\s+/).filter((x) => x && x !== c).join(' '); },
        add(c) { if (node._cls.indexOf(c) < 0) node._cls = (node._cls + ' ' + c).trim(); },
      },
      // L-1: минимальный инлайн-style, чтобы проверить снятие `--g-*`.
      style: {
        _p: {},
        get length() { return Object.keys(node.style._p).length; },
        item(i) { const k = Object.keys(node.style._p); return k[i] || ''; },
        setProperty(n, v) { node.style._p[n] = String(v); },
        removeProperty(n) { delete node.style._p[n]; },
        getPropertyValue(n) { return node.style._p[n] || ''; },
      },
      querySelectorAll(sel) {
        const out = [];
        (function walk(parent) {
          parent.children.forEach((ch) => { if (matchClass(ch._cls, sel)) out.push(ch); walk(ch); });
        })(node);
        return out;
      },
      querySelector(sel) { return node.querySelectorAll(sel)[0] || null; },
      getBoundingClientRect() { return { width: 100, height: 44 }; },
    };
    return node;
  }

  const surfaces = [];
  let mountCalls = 0;
  let disposeCalls = 0;
  let addRefract = false;

  const surface = makeNode('glass-surface');
  surface.attrs['data-glass-surface'] = '';
  surfaces.push(surface);

  const sandbox = {
    window: null, document: null, getComputedStyle: null, Object, Math, isFinite, parseFloat,
  };
  sandbox.window = sandbox;
  sandbox.document = {
    querySelectorAll(sel) { return sel === '[data-glass-surface]' ? surfaces : []; },
    documentElement: { contains() { return true; } },
  };
  sandbox.getComputedStyle = () => ({ borderTopLeftRadius: '12px' });
  sandbox.window.LiquidGlass = {
    mountGlass(root) {
      mountCalls++;
      const tint = makeNode('ps-glass__tint');
      root.appendChild(tint);
      root.classList.add('ps-glass');
      // L-1: библиотека ставит на root свои атрибуты и inline `--g-*`.
      root.setAttribute('data-glass', '');
      root.setAttribute('data-uid', 'ps-glass-abc123');
      root.style.setProperty('--g-radius', '12px');
      root.style.setProperty('--g-tint', '6');
      if (addRefract) root.appendChild(makeNode('ps-glass__refract'));
      return { dispose() { disposeCalls++; } };
    },
  };
  sandbox.window.requestAnimationFrame = () => 1;
  sandbox.window.cancelAnimationFrame = () => {};

  vm.createContext(sandbox);
  vm.runInContext(GLASS, sandbox, { filename: 'glass.js' });
  const LG = sandbox.window.__LiquidGlass;
  assert.ok(LG && typeof LG.sync === 'function' && typeof LG.dispose === 'function',
    'A: __LiquidGlass.sync/dispose');
  assert.strictEqual(LG.targets(), '[data-glass-surface]', 'A: единственная цель');

  // ON → монтируется только на surface; функциональных целей нет.
  LG.sync(true);
  assert.strictEqual(mountCalls, 1, 'A: mount только на [data-glass-surface]');
  assert.strictEqual(surface.getAttribute('data-lg-mounted'), '1', 'A: data-lg-mounted');
  assert.strictEqual(surface.getAttribute('data-lg-mode'), 'frosted',
    'A: без источника — честный frosted (не рефракция)');
  assert.strictEqual(LG.mode(), 'frosted', 'A: mode() = frosted');

  // Идемпотентность: повторный ON не дублирует mount.
  LG.sync(true);
  assert.strictEqual(mountCalls, 1, 'A: повторный sync идемпотентен');

  // OFF → полный cleanup: нет `.ps-glass*`, нет data-lg-*.
  LG.dispose();
  assert.strictEqual(surface.querySelectorAll('[class*="ps-glass"]').length, 0,
    'A: dispose удаляет ВСЕ .ps-glass*');
  assert.strictEqual(surface.getAttribute('data-lg-mounted'), null, 'A: data-lg-mounted снят');
  assert.strictEqual(surface.getAttribute('data-lg-mode'), null, 'A: data-lg-mode снят');
  assert.ok(surface.className.indexOf('ps-glass') < 0, 'A: класс ps-glass снят с root');
  // L-1: библиотечные атрибуты/инлайн-переменные тоже сняты.
  assert.strictEqual(surface.getAttribute('data-glass'), null,
    'L-1: data-glass снят');
  assert.strictEqual(surface.getAttribute('data-uid'), null,
    'L-1: data-uid снят');
  assert.strictEqual(surface.style.getPropertyValue('--g-radius'), '',
    'L-1: inline --g-radius снят');
  assert.strictEqual(surface.style.getPropertyValue('--g-tint'), '',
    'L-1: inline --g-tint снят');
  assert.strictEqual(disposeCalls, 1, 'A: inst.dispose вызван');
  LG.dispose();
  assert.strictEqual(disposeCalls, 1, 'A: повторный dispose идемпотентен');
  assert.strictEqual(surface.querySelectorAll('[class*="ps-glass"]').length, 0,
    'A: после повторного dispose чисто');

  // refraction маркируется только при реальном слое преломления.
  addRefract = true;
  LG.sync(true);
  assert.strictEqual(surface.getAttribute('data-lg-mode'), 'refraction',
    'A: слой .ps-glass__refract → refraction');
  LG.dispose();
}

// ═══ A. Статически: стекло не на функциональных целях ══════════════════════
{
  assert.ok(GLASS.indexOf("var SELECTOR = '[data-glass-surface]'") >= 0,
    'A: SELECTOR = [data-glass-surface]');
  for (const bad of ['.scope-trigger', '.header-fs-btn', '.status-block']) {
    assert.ok(!new RegExp("TARGETS[^;]*" + bad.replace('.', '\\.')).test(GLASS),
      'A: ' + bad + ' не в целях стекла');
  }
  assert.ok(/data-lg-failed/.test(GLASS), 'A: честный fallback при ошибке');
  assert.ok(/function purge/.test(GLASS) && /function disposeAll/.test(GLASS),
    'A: purge/disposeAll');
  assert.ok(/data-lg-mode/.test(GLASS), 'A: маркер честного режима');
  assert.ok(INDEX.indexOf('data-glass-surface') >= 0, 'A: разметка GlassSurface');
  assert.ok(INDEX.indexOf('glass-surface') >= 0, 'B: класс контейнера');
  // Стекло НЕ вешается на 3 функциональные цели разметкой.
  assert.ok(!/data-glass-surface[^>]*scope-trigger/.test(INDEX), 'A: не на селекторе');
}

// ═══ B. CSS-контракт GlassSurface ═══════════════════════════════════════════
{
  const block = CSS.match(/^    \.glass-surface \{([\s\S]*?)^    \}/m);
  assert.ok(block, 'B: правило .glass-surface');
  assert.ok(/isolation:\s*isolate/.test(block[1]), 'B: isolation:isolate');
  assert.ok(/contain:\s*layout paint/.test(block[1]), 'B: contain:layout paint');
  assert.ok(/pointer-events:\s*none/.test(block[1]), 'B: decor pointer-events:none');
  assert.ok(/--glass-paper:\s*var\(--surface-1\)/.test(block[1]),
    'B: тёмная paper (не белый frosted)');
  assert.strictEqual(token('--work-surface-bg').replace(/\s/g, ''),
    'rgba(9,13,23,0.62)', 'C: --work-surface-bg');
}

// ═══ C. Единая рабочая поверхность Main ════════════════════════════════════
{
  const main = CSS.match(/\.app-shell\.ia-v2 main\.scroll-area \{([\s\S]*?)\n      \}/);
  assert.ok(main, 'C: desktop main.scroll-area');
  assert.ok(/max-width:\s*none/.test(main[1]), 'C: max-width снят');
  assert.ok(!/1440/.test(main[1]), 'C: нет лимита 1440px');
  assert.ok(/margin-inline:\s*0/.test(main[1]), 'C: нет центрирования');
  assert.ok(/background:\s*var\(--work-surface-bg\)/.test(main[1]),
    'C: подложка работы на main.scroll-area');
  assert.ok(!/margin-left:\s*-/.test(CSS) && !/margin-inline:\s*-/.test(CSS),
    'C: без отрицательных отступов');
  // Лимит карточек 1100px сохранён.
  assert.ok(/\.module-list \{[\s\S]{0,160}max-width:\s*1100px/.test(CSS),
    'C: .module-list ≤1100px');
  assert.ok(/\.module-quick-wrap \{[\s\S]{0,120}max-width:\s*1100px/.test(CSS),
    'C: .module-quick-wrap ≤1100px');
  assert.ok(/\.module-toolbar \{[\s\S]{0,120}max-width:\s*1100px/.test(CSS),
    'C: .module-toolbar ≤1100px');
  // Слои 1–5: canvas позади, z-index:0.
  assert.ok(/\.aurora-flow-canvas \{[\s\S]{0,160}z-index:\s*0/.test(CSS),
    'C: фоновый canvas — слой 1 (z-index:0)');
}

// ═══ D. Единая высота, один safe-area ══════════════════════════════════════
{
  const stripCss = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
  const fsArea = CSS.match(/^    \.fullscreen-mode \.scroll-area \{([\s\S]*?)^    \}/m);
  assert.ok(fsArea, 'D: fullscreen scroll-area');
  assert.ok(!/env\(safe-area-inset-bottom/.test(stripCss(fsArea[1])),
    'D: второй вычет safe-area снят');
  assert.ok(/padding-bottom:\s*1rem/.test(fsArea[1]), 'D: базовый отступ fullscreen');
  const sheet = CSS.match(/^    \.more-sheet \{([\s\S]*?)^    \}/m);
  assert.ok(sheet, 'D: .more-sheet');
  const sheetCode = stripCss(sheet[1]);
  assert.ok(sheetCode.indexOf('--tg-viewport-bottom-offset') >= 0,
    'D: один учтённый offset');
  const bottoms = sheetCode.match(/bottom:\s*calc\(52px[^\n]*/g) || [];
  for (const b of bottoms) {
    assert.ok(!/\+\s*var\(--tg-viewport-bottom-offset[\s\S]*safe-area/.test(b),
      'D: offset НЕ складывается с safe-area');
  }
  // Источник высоты — единый.
  assert.ok(APP_JS.indexOf('_auroraResize') >= 0, 'D: app.js resize-хук');
}

// ═══ E. Карточка без стекла ════════════════════════════════════════════════
{
  const statusBlock = INDEX.slice(INDEX.indexOf('class="card p-4 status-block"'),
    INDEX.indexOf('class="card p-4 status-block"') + 200);
  assert.ok(statusBlock.indexOf('data-glass') < 0, 'E: .status-block без атрибутов стекла');
  assert.ok(/\.status-block \{ max-width: 100%; overflow: hidden; \}/.test(CSS),
    'E: контейнер карточки не изменён');
  assert.ok(/\.hb-wrap \{[^}]*min-height: 56px/.test(CSS), 'E: дизайн сердцебиения не тронут');
}

// ═══ F. OGL-фон: resize/геометрия/анимация ═════════════════════════════════
{
  assert.ok(/resize:\s*resize/.test(AURORA), 'F: __AuroraFlow экспортирует resize');
  assert.ok(/function measure/.test(AURORA), 'F: measure по контейнеру');
  assert.ok(/getBoundingClientRect\(\)/.test(AURORA), 'F: по rect контейнера');
  assert.ok(/gl\.viewport\(0, 0, bw, bh\)/.test(AURORA), 'F: gl.viewport обновляется');
  assert.ok(/uniforms\.uRes\.value = \[bw, bh\]/.test(AURORA), 'F: uRes из buffer');
  assert.ok(/ResizeObserver/.test(AURORA), 'F: ResizeObserver (опц.)');
  assert.ok(/ensureResizeObserver\(\)/.test(AURORA), 'F: observer поднимается в start');
  assert.ok(/de\.clientWidth/.test(AURORA) && /de\.clientHeight/.test(AURORA),
    'F: фактический размер контейнера (documentElement), не 300×150 OGL');
  // app.js: вызовы из resize/fullscreen/visualViewport.
  assert.ok(/_auroraResize\(\);/.test(APP_JS), 'F: вызов resize из app.js');
  assert.ok(/setFullscreenFromTma:[\s\S]{0,900}_auroraResize\(\)/.test(APP_JS),
    'F: resize после fullscreen');
  assert.ok(/visualViewport[\s\S]{0,200}_onVV/.test(APP_JS), 'F: visualViewport-хук');
  assert.ok(!/createLinearGradient\(0, 0[\s\S]{0,40}\);\s*\n\s*g\.addColorStop/.test(APP_JS),
    'F: без новых CSS-градиентов поверх WebGL (app.js)');
}

// ═══ G. Флаги / версия ═════════════════════════════════════════════════════
{
  assert.ok(/APP_VERSION = "2\.58\.25"/.test(SETTINGS), 'G: APP_VERSION 2.58.21');
  assert.ok(/UI_LIQUID_GLASS_LIB: ClassVar\[bool\] = _env_bool\(\s*"UI_LIQUID_GLASS_LIB", False\)/
    .test(SETTINGS), 'G: флаг default OFF');
  assert.ok(ROUTES.indexOf('UI_LIQUID_GLASS_LIB') >= 0, 'G: флаг доставлен');

  const CATALOG = read('services/param_catalog.py');
  assert.ok(CATALOG.indexOf('UI_LIQUID_GLASS_LIB') < 0, 'G: Δ каталога = 0');
}

// ═══ H. Review-фиксы round1025: H-1 / L-H10-1 / L-1 / L-2 ══════════════════
{
  // H-1: auto-строка grid'а с `overflow:hidden`-элементом не схлопывается —
  // карточка «Статус» целиком, без обрезки/перекрытия на mobile и fullscreen.
  assert.ok(/main\.scroll-area \{ grid-auto-rows: max-content; \}/.test(CSS),
    'H-1: main.scroll-area → grid-auto-rows:max-content');
  // L-H10-1: пустой декоративный контейнер не рендерится при OFF (v-if).
  assert.ok(/v-if="liquidGlassLib"[\s\S]{0,120}data-glass-surface/.test(INDEX),
    'L-H10-1: glass-surface только при UI_LIQUID_GLASS_LIB=ON');
  // L-1: диспоуз снимает и библиотечные атрибуты/inline `--g-*` с root.
  assert.ok(/data-uid/.test(GLASS) && /'data-glass'/.test(GLASS),
    'L-1: библиотечные атрибуты в clearAttrs');
  assert.ok(/indexOf\('--g-'\)/.test(GLASS), 'L-1: inline --g-* снимаются');
  // L-2: актуальный комментарий `.env.example` (default OFF, только декор).
  const ENV = read('.env.example');
  assert.ok(ENV.indexOf('только frost-fallback') < 0,
    'L-2: устаревший комментарий убран');
  assert.ok(/UI_LIQUID_GLASS_LIB \(default OFF\)/.test(ENV),
    'L-2: default OFF отражён');
}

console.log('HOTFIX10-GLASS-GEOMETRY-BG-OK');
