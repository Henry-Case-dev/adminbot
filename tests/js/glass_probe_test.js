/* W2-GLASS U08.3 / REQ-U08-1-PROBE: unit-тесты render-probe Liquid Glass.
 *
 * Запуск: node tests/js/glass_probe_test.js
 * TEST-LIFECYCLE: CONTRACT owner=REQ-U08-1-PROBE (U08.3)
 *
 * Проверяет: чистую функцию решения decide() (матрица engine × capability),
 * форму публичного API window.__GlassProbe, порядок загрузки в index.html
 * (probe → glass.js → app.js, w2-contract §1.3.4) и наличие файлов стенда
 * + PNG-карты линзы. Рендер-часть пробы (canvas, пиксельная сверка)
 * проверяется в браузере (Playwright, см. w2-evidence-glass/).
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');

// ── 1. Модуль загружается в Node c window-стабом и отдаёт API ──────────────
global.window = {};
require(path.join(ROOT, 'web', 'static', 'glass-probe.js'));
const probe = global.window.__GlassProbe;
assert.strictEqual(typeof probe, 'object', '__GlassProbe экспортирован');
assert.strictEqual(typeof probe.probe, 'function', 'probe() — функция');
assert.strictEqual(typeof probe.cached, 'function', 'cached() — функция');
assert.strictEqual(typeof probe.reset, 'function', 'reset() — функция');
assert.strictEqual(typeof probe.details, 'function', 'details() — функция');
const decide = probe._test && probe._test.decide;
assert.strictEqual(typeof decide, 'function', '_test.decide — чистая функция');

// ── 2. Матрица решения decide() (WIN-GLASS-P0: + признак возможности слоя
//    преломления refractionLayer = svgRender && backdrop) ───────────────────
// Нет svg-рендера → честный B независимо от движка, слоя преломления нет.
assert.deepStrictEqual(
  decide({ svgRender: false, backdrop: true, engine: 'chromium' }),
  { tierA: false, reason: 'svg-render-failed', refractionLayer: false },
  'нет рендера → svg-render-failed');
assert.deepStrictEqual(
  decide({ svgRender: false, backdrop: true, engine: 'webkit' }),
  { tierA: false, reason: 'svg-render-failed', refractionLayer: false },
  'webkit+нет рендера → B');
// Есть рендер, нет backdrop-filter вообще → no-backdrop-filter.
assert.deepStrictEqual(
  decide({ svgRender: true, backdrop: false, engine: 'chromium' }),
  { tierA: false, reason: 'no-backdrop-filter', refractionLayer: false },
  'нет backdrop → no-backdrop-filter');
// Chromium + рендер + backdrop = доказанный url() в backdrop-filter: Tier A
// (desktop-путь сохранён).
assert.deepStrictEqual(
  decide({ svgRender: true, backdrop: true, engine: 'chromium' }),
  { tierA: true, reason: 'probe-chromium', refractionLayer: true },
  'chromium → Tier A (backdrop)');
// WebKit: bug 245510 — url() в backdrop-filter не рендерится; слой
// преломления (filter: url()) в WebKit рендерится → оптику даёт слой.
assert.deepStrictEqual(
  decide({ svgRender: true, backdrop: true, engine: 'webkit' }),
  { tierA: false, reason: 'engine-webkit-backdrop-url-no', refractionLayer: true },
  'webkit → честный B + слой возможен (bug 245510)');
// Gecko/unknown: рендер svg есть, но backdrop-url не доказан в целевых
// клиентах — ни Tier A, ни слой не заявляем.
assert.deepStrictEqual(
  decide({ svgRender: true, backdrop: true, engine: 'gecko' }),
  { tierA: false, reason: 'engine-unproven-backdrop-url', refractionLayer: false },
  'gecko → не доказан');
assert.deepStrictEqual(
  decide({ svgRender: true, backdrop: true, engine: 'unknown' }),
  { tierA: false, reason: 'engine-unproven-backdrop-url', refractionLayer: false },
  'unknown → не доказан');

// ── 3. probe() в DOM-меньшей среде → честный отказ, без исключений ─────────
probe.reset();
const res = probe.probe();
assert.ok(typeof res.then === 'function', 'probe() возвращает Promise');
res.then((r) => {
  assert.strictEqual(r.tierA, false, 'без DOM tierA=false');
  assert.strictEqual(r.reason, 'no-dom', 'без DOM reason=no-dom');
  assert.strictEqual(probe.cached().reason, 'no-dom', 'результат закэширован');

  // ── 4. index.html: порядок загрузки и файлы ─────────────────────────────
  const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const iProbe = INDEX.indexOf('/static/glass-probe.js');
  const iGlass = INDEX.indexOf('/static/glass.js');
  const iApp = INDEX.indexOf('/web/app.js');
  assert.ok(iProbe > 0, 'glass-probe.js подключён в index.html');
  assert.ok(iProbe < iGlass, 'glass-probe.js ДО glass.js (§1.3.4)');
  assert.ok(iGlass < iApp, 'glass.js ДО app.js (§1.3.4)');

  const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
  assert.ok(APP_JS.indexOf('__GlassProbe') >= 0,
    'app.js использует __GlassProbe (REQ-U08-1-PROBE)');
  assert.ok(APP_JS.indexOf('Math.min(this._lensMaxNodes(), 3)') >= 0,
    'U08.3d: жёсткий кап 3 hero-поверхности');

  const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
  for (const marker of ['.lg-panel', '.lg-panel--hero', '.lg-panel--soft',
    '.lg-panel--solid', '.lg-panel__backdrop', '.lg-panel__tint',
    '.lg-panel__rim', '.lg-panel__specular', '.lg-panel__content',
    '.lg-mini-lens']) {
    assert.ok(CSS.indexOf(marker) >= 0, 'app.css содержит ' + marker);
  }
  // Запрещённые места filter:url (U08.2/U08.3, w2-contract §3.2):
  // не на .lg-panel__content, не на корне карточки, не на header/html/body.
  const mContent = CSS.match(/\.lg-panel__content\s*{[^}]*}/g) || [];
  for (const block of mContent) {
    assert.ok(block.indexOf('filter:') < 0,
      '.lg-panel__content без filter (текст не искажается)');
  }
  const mRoot = CSS.match(/html[^{]*{[^}]*filter:\s*url/g) || [];
  assert.strictEqual(mRoot.length, 0, 'filter:url запрещён на html');
  // url(#lg-lens) встречается только в backdrop-filter-цепочках tier A
  // (сканируем код без комментариев — в них имя фильтра упоминаться может).
  const cssNoComments = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
  const urlUses = cssNoComments.match(/[a-z-]*filter:[^;]*url\(#lg-lens\)/g) || [];
  for (const u of urlUses) {
    assert.ok(/backdrop-filter/.test(u),
      'url(#lg-lens) только в backdrop-filter (не на форграунде): ' + u.trim());
  }

  // ── 5. Стенд (test-only) и карта линзы ──────────────────────────────────
  // SOUL-13.2 / v6.3 §14 (REV-W2-N3): стенд ВЫНЕСЕН из публично
  // смонтированного web/static в tests/glass-teststand (анонимный
  // /static|/web/static/glass-teststand.html → 404). Прод-ассеты
  // (glass-probe.js, lg-lens-map.png) остаются на месте.
  for (const f of ['tests/glass-teststand/glass-teststand.html',
    'tests/glass-teststand/glass-teststand.css',
    'tests/glass-teststand/glass-teststand.js',
    'web/static/glass-probe.js', 'web/static/vendor/lg-lens-map.png']) {
    assert.ok(fs.existsSync(path.join(ROOT, ...f.split('/'))), 'существует ' + f);
  }
  // Гард: возврат страницы стенда в публичный static снова валит тест
  // (страница анонимно отдаётся монтами /static и /web без auth).
  for (const f of ['web/static/glass-teststand.html',
    'web/static/glass-teststand.css', 'web/static/glass-teststand.js',
    'web/glass-teststand.html']) {
    assert.ok(!fs.existsSync(path.join(ROOT, ...f.split('/'))),
      'стенд НЕ в публичном static: ' + f);
  }

  console.log('JS-UNIT-OK glass-probe');
}).catch((e) => { console.error(e); process.exit(1); });
