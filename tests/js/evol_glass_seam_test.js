'use strict';
/* EVOL-032 §6 (31.10.2026): внутренний прямой шов стекла.
 *
 * Дефект: `feImage` карты линзы объявлял подрегион в ФИКСИРОВАННЫХ px
 * (width="360" height="120"). За этим прямоугольником карта для
 * `feDisplacementMap` не определена (прозрачный чёрный ⇒ сдвиг −16px), поэтому
 * у любой поверхности шире 360px / выше 120px внутри карточки возникала резкая
 * прямая линия смены оттенка на 360px / 120px от её начала.
 *
 * Тест держит инварианты фикса и запрещает «лечение» дефекта:
 *   • подрегион карты покрывает регион фильтра (нет неопределённой зоны);
 *   • карта остаётся растянутой (preserveAspectRatio="none"), не letterbox;
 *   • сама оптика (карта, scale, каналы, blur/saturate, маска, alpha,
 *     z-index, слой преломления) НЕ менялась;
 *   • никаких новых overlay/градиентов/blur/утолщений не добавлено;
 *   • health-tint по-прежнему модулирует только заливку;
 *   • защищённые файлы байт-в-байт равны HEAD.
 *
 * Запуск: node tests/js/evol_glass_seam_test.js → EVOL-GLASS-SEAM-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { execFileSync } = require('child_process');
const crypto = require('crypto');

const ROOT = path.resolve(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const REFRACT = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'glass-refraction.js'), 'utf8');

/* ── Разбор #lg-lens ─────────────────────────────────────────────────────── */
const lensStart = INDEX.indexOf('<filter id="lg-lens"');
assert.ok(lensStart > 0, '#lg-lens must exist');
const lensBlock = INDEX.slice(lensStart, INDEX.indexOf('</filter>', lensStart));
assert.strictEqual(INDEX.split('<filter id="lg-lens"').length - 1, 1,
  'exactly one #lg-lens filter');

function attr(block, name) {
  const m = block.match(new RegExp(name + '="([^"]*)"'));
  return m ? m[1] : null;
}

const filterX = attr(lensBlock, 'x');
const filterY = attr(lensBlock, 'y');
const filterW = attr(lensBlock, 'width');
const filterH = attr(lensBlock, 'height');
assert.strictEqual(filterX, '-6%', 'filter region x unchanged');
assert.strictEqual(filterY, '-6%', 'filter region y unchanged');
assert.strictEqual(filterW, '112%', 'filter region width unchanged');
assert.strictEqual(filterH, '112%', 'filter region height unchanged');

const feImageTag = lensBlock.slice(lensBlock.indexOf('<feImage'),
  lensBlock.indexOf('/>', lensBlock.indexOf('<feImage')) + 2);
assert.ok(feImageTag.includes('id="lg-lens-map"'), 'feImage carries the frozen map id');
assert.ok(/href="data:image\/png;base64,/.test(feImageTag),
  'map stays a CSP-safe same-origin data:image/png (owner CORR-0/V07)');

const mapX = attr(feImageTag, 'x');
const mapY = attr(feImageTag, 'y');
const mapW = attr(feImageTag, 'width');
const mapH = attr(feImageTag, 'height');

/* ── ГЕОМЕТРИЧЕСКАЯ ПРОВЕРКА (ядро фикса) ────────────────────────────────── */
/* Подрегион feImage обязан покрывать регион фильтра целиком, иначе за его
 * границей карта смещения не определена и появляется прямой шов. Проценты
 * подрегиона примитива отсчитываются от региона фильтра, поэтому покрытие
 * выражается как x<=0, y<=0, x+w>=100, y+h>=100. */
function pct(v, name) {
  assert.ok(typeof v === 'string' && /^-?\d+(\.\d+)?%$/.test(v),
    name + ' must be a percentage of the filter region, got ' + v);
  return parseFloat(v);
}
const mx = pct(mapX, 'feImage@x');
const my = pct(mapY, 'feImage@y');
const mw = pct(mapW, 'feImage@width');
const mh = pct(mapH, 'feImage@height');
assert.ok(mx <= 0, 'map subregion starts at/before the filter region (x=' + mapX + ')');
assert.ok(my <= 0, 'map subregion starts at/before the filter region (y=' + mapY + ')');
assert.ok(mx + mw >= 100, 'map subregion covers the region horizontally (' +
  mx + '+' + mw + ')');
assert.ok(my + mh >= 100, 'map subregion covers the region vertically (' +
  my + '+' + mh + ')');

/* Никаких фиксированных px: именно они давали шов на 360/120. */
[['width', mapW], ['height', mapH]].forEach(function (pair) {
  assert.ok(!/px$/.test(pair[1]),
    'feImage@' + pair[0] + ' must not be a fixed pixel size (' + pair[1] + ')');
  assert.notStrictEqual(pair[1], '360', 'no 360px cut-off');
  assert.notStrictEqual(pair[1], '120', 'no 120px cut-off');
});
assert.ok(!/width="360"\s+height="120"/.test(lensBlock),
  'fixed 360x120 map subregion removed from the #lg-lens filter');

/* Карта растянута на регион (эллиптическая линза поверхности), не letterbox. */
assert.ok(/preserveAspectRatio="none"/.test(feImageTag),
  'map is still stretched over the surface (preserveAspectRatio="none")');

/* ── Оптика не изменилась ────────────────────────────────────────────────── */
const disp = lensBlock.slice(lensBlock.indexOf('<feDisplacementMap'));
assert.ok(disp.includes('in="SourceGraphic"'), 'displacement input unchanged');
assert.ok(disp.includes('in2="lg-map"'), 'displacement map link unchanged');
assert.ok(/scale="32"/.test(disp), 'displacement scale stays 32 (= ±16px)');
assert.ok(/xChannelSelector="R"/.test(disp), 'x channel stays R');
assert.ok(/yChannelSelector="G"/.test(disp), 'y channel stays G');
assert.ok(/color-interpolation-filters="sRGB"/.test(lensBlock),
  'sRGB interpolation kept');
assert.ok(!/feTurbulence|feGaussianBlur|feColorMatrix/.test(lensBlock),
  'no new filter primitives (no extra blur/overlay in the lens chain)');

/* ── Слой преломления (мобильный носитель) не тронут ─────────────────────── */
assert.ok(REFRACT.includes("var BASE_FILTER_ID = 'lg-lens';"),
  'refraction layer still clones #lg-lens (inherits the fix)');
assert.ok(REFRACT.includes("var LAYER_FILTER_MID = 'blur(5px) saturate(140%) url(#';"),
  'layer recipe blur(5px) saturate(140%) + lens unchanged');
assert.ok(/var RING_SOLID_PX = 20;/.test(REFRACT) &&
  /var RING_FADE_PX = 46;/.test(REFRACT),
  'ring-mask constants unchanged');
assert.ok(/stp\.zIndex = '-1';/.test(REFRACT), 'layer z-index stays -1');
assert.ok(/stp\.pointerEvents = 'none';/.test(REFRACT), 'layer stays decorative');
assert.ok(!/360|120/.test(
  REFRACT.slice(REFRACT.indexOf('function makeLayer'),
    REFRACT.indexOf('function radiusRectW'))),
  'layer does not hardcode the old 360/120 box');

/* Один canvas на поверхность — никаких новых overlay-слоёв. */
const makeLayerFn = REFRACT.slice(REFRACT.indexOf('function makeLayer'),
  REFRACT.indexOf('function radiusRectW'));
assert.strictEqual((makeLayerFn.match(/createElement\('canvas'\)/g) || []).length, 1,
  'exactly one decorative canvas per surface');
assert.ok(!/createElement\('div'\)|createElement\('span'\)|createElement\('img'\)/
  .test(REFRACT), 'no extra DOM overlay elements in the refraction module');

/* ── CSS: носитель оптики и материал не менялись ─────────────────────────── */
assert.ok(CSS.includes('--lg-frost-hero: blur(5px) saturate(140%);'),
  'frost-hero recipe unchanged');
assert.ok(CSS.includes('--glass-bg: rgba(21, 27, 42, 0.5)'),
  'glass alpha unchanged');
assert.ok(CSS.includes('--lg-radius-hero: 22px'), 'radius unchanged');
assert.ok(/\[data-glass="a"\]\[data-glass-tier="a"\]\s*\{[^}]*backdrop-filter:\s*var\(--lg-frost-hero\)\s+url\(#lg-lens\)/
  .test(CSS), 'tier-A backdrop carrier still uses url(#lg-lens)');
assert.ok(/\[data-refract-layer="on"\]\[data-glass-tier="a"\]/.test(CSS),
  'mobile carrier rule still drops url() from backdrop-filter');
assert.ok(!/\.lg-refract\s*::?(before|after)/.test(CSS),
  'no pseudo-element overlay added to the refraction layer');
assert.ok(!/\.lg-refract\s*\{[^}]*background/.test(CSS),
  'no background/gradient added to the refraction layer');

/* ── Health-tint по-прежнему модулирует ТОЛЬКО заливку ──────────────────── */
const healthMark = CSS.indexOf('[data-health-state="failed"][data-health-material="bg"]');
assert.ok(healthMark > 0, 'health tint rules exist');
const healthRules = CSS.slice(healthMark, healthMark + 900)
  .replace(/\/\*[\s\S]*?\*\//g, '');
assert.ok(/background-color: rgba\(141, 74, 85, 0\.5\);/.test(healthRules),
  'alert tint is still a plain fill');
assert.ok(!/filter:|backdrop-filter|box-shadow|transform|clip-path/.test(healthRules),
  'tint path does not touch filter/backdrop-filter/box-shadow/transform');

/* ── Защищённые файлы: байт-в-байт HEAD ─────────────────────────────────── */
const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const PROTECTED = [
  'web/static/glass.js',
  'web/static/polygon-background.js',
  'web/static/aurora-flow.js',
  'web/static/vendor/liquidglass.core.0.5.3.css',
  'web/static/vendor/liquidglass.core.0.5.3.min.js',
];
PROTECTED.forEach(function (rel) {
  const head = execFileSync('git', ['show', 'HEAD:' + rel], { cwd: ROOT });
  const disk = fs.readFileSync(path.join(ROOT, rel));
  assert.strictEqual(sha(disk), sha(head), rel + ' differs from HEAD (sha256)');
});

/* ── Только web/index.html меняется в оптике ────────────────────────────── */
const changed = execFileSync('git', ['diff', '--name-only', 'HEAD', '--', 'web/'],
  { cwd: ROOT }).toString().split('\n').filter(Boolean);
changed.forEach(function (rel) {
  assert.ok(['web/index.html', 'web/static/app.css', 'web/app.js'].indexOf(rel) >= 0,
    'unexpected optics file changed: ' + rel);
});

console.log('EVOL-GLASS-SEAM-OK');
