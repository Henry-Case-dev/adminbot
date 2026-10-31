'use strict';
/* EVOL-032 / CONTRACT 2: адаптер здоровья, разметка двух карточек,
 * reduced-motion и refreshTint без пересоздания слоя.
 * Запуск: node tests/js/evol032_health_glass_test.js → EVOL032-OK
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const REFRACT = fs.readFileSync(path.join(ROOT, 'web', 'static', 'glass-refraction.js'), 'utf8');

function stateOf(subsystem, payload, scope) {
  return global.healthStateFrom(subsystem, payload, scope).state;
}

/* ── CSS: заливка только у состояний реальной проблемы ──────────────────── */
assert.ok(CSS.includes('[data-health-state="degraded"][data-health-material="bg"]'),
  'degraded+bg selector');
assert.ok(CSS.includes('background-color: rgba(91, 55, 67, 0.5);'),
  'degraded fill 32% --err, alpha 0.5');
assert.ok(CSS.includes('[data-health-state="failed"][data-health-material="bg"]'),
  'failed+bg selector');
assert.ok(CSS.includes('background-color: rgba(141, 74, 85, 0.5);'),
  'failed fill 55% --err, alpha 0.5');
assert.ok(CSS.includes('background-color: rgba(91, 55, 67, 0.85);'),
  'strong degraded keeps alpha 0.85');
assert.ok(CSS.includes('background-color: rgba(141, 74, 85, 0.85);'),
  'strong failed keeps alpha 0.85');
/* ASAP-UI-02 §6 (wave 2): `warning` — красное стекло МЕНЬШЕЙ интенсивности. */
assert.ok(CSS.includes('[data-health-state="warning"][data-health-material="bg"]'),
  'warning+bg selector');
assert.ok(CSS.includes('background-color: rgba(60, 43, 56, 0.5);'),
  'warning fill 18% --err, alpha 0.5 (мягче degraded)');
assert.ok(CSS.includes('background-color: rgba(60, 43, 56, 0.85);'),
  'strong warning keeps alpha 0.85');
assert.ok(CSS.includes('--health-fill-warning: rgba(60, 43, 56, 0.5);'),
  'warning в единой карте токенов');
(function () {
  // Интенсивность: warning < degraded < failed (красная составляющая растёт).
  const read = (stmt) => {
    const m = /rgba\((\d+),\s*(\d+),\s*(\d+),\s*0\.5\)/.exec(stmt);
    assert.ok(m, 'rgba разобран: ' + stmt);
    return Number(m[1]) + Number(m[2]) + Number(m[3]);
  };
  const warn = read('rgba(60, 43, 56, 0.5)');
  const degrad = read('rgba(91, 55, 67, 0.5)');
  const fail = read('rgba(141, 74, 85, 0.5)');
  assert.ok(warn < degrad && degrad < fail,
    'порядок интенсивности warning < degraded < failed');
})();
assert.ok(CSS.includes('--glass-bg: rgba(21, 27, 42, 0.5)'),
  'normal glass-bg unchanged');
const healthMark = CSS.indexOf('EVOL-032 / CONTRACT 2 — тонирование');
// EVOL-023 (W7) добавила СВОЮ секцию в конец app.css, поэтому «до конца
// файла» больше не равно «правила здоровья». Границу секции задаём явно:
// от маркера до следующего баннера-раздела — инварианты (никакого внешнего
// glow/backdrop-filter именно в health-правилах) сохранены и стали точнее.
const _afterMark = CSS.slice(CSS.lastIndexOf('/*', healthMark));
const _nextSection = _afterMark.search(/\/\*\s*═+\s*EVOL-023/);
const healthCss = _nextSection >= 0 ? _afterMark.slice(0, _nextSection) : _afterMark;
const healthRules = healthCss.replace(/\/\*[\s\S]*?\*\//g, '');
assert.ok(!/\[data-health-state="normal"\]/.test(healthRules), 'normal has no fill rule');
assert.ok(!/\[data-health-state="unknown"\]/.test(healthRules), 'unknown has no fill rule');
assert.ok(!/\[data-health-state="disabled"\]/.test(healthRules), 'disabled has no fill rule');
assert.ok(!/box-shadow/.test(healthRules), 'no external glow on health rules');
assert.ok(!/backdrop-filter/.test(healthRules), 'health rules do not touch backdrop-filter');
assert.ok(healthCss.includes('transition: background-color'),
  'only background-color transitions');
assert.ok(/@media \(prefers-reduced-motion: reduce\)\s*\{\s*\[data-health-state\]\s*\{\s*transition: none;/.test(healthCss),
  'reduced-motion kills the health transition');
assert.ok(CSS.includes('--space-1: 4px') && CSS.includes('--space-8: 32px'),
  'EVOL-022 spacing rhythm');
assert.ok(CSS.includes('--border-hairline: 1px'), 'hairline token');
assert.ok(CSS.includes('--btn-h:') && CSS.includes('--toggle-hit:'),
  'EVOL-043 control tokens');

/* ── Разметка: стекло только у отдельных корней, агрегат не красится ────── */
assert.ok(INDEX.includes('subsystem="bot"'), 'bot hero is a health surface');
assert.ok(INDEX.includes('class="card p-4 status-hero sg-5"'), 'hero class kept');
assert.ok(INDEX.includes('class="card p-4 status-block"'), 'aggregate card kept');
assert.ok(!/class="card p-4 status-block"[\s\S]{0,80}data-health-material/.test(INDEX),
  'status-block root is not a tinted glass surface');
assert.ok(INDEX.includes('data-health-inline="heartbeat"'), 'heartbeat text inside aggregate');
assert.ok(INDEX.includes('data-health-inline="memory"'), 'memory text inside aggregate');
assert.ok(INDEX.includes('data-health-inline="vision"'), 'vision text, no new card');
assert.ok(INDEX.includes('subsystem="experience"'), 'experience card is a health surface');
assert.ok(INDEX.includes('aria-live="polite"'), 'status text is live for AT');
/* Защищённая оптика: байт-в-байт HEAD, не «похоже». */
const { execFileSync } = require('child_process');
const crypto = require('crypto');
const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const PROTECTED = [
  'web/static/glass.js',
  'web/static/polygon-background.js',
  'web/static/aurora-flow.js',
];
PROTECTED.forEach(function (rel) {
  const head = execFileSync('git', ['show', 'HEAD:' + rel], { cwd: ROOT });
  const disk = fs.readFileSync(path.join(ROOT, rel));
  assert.strictEqual(sha(disk), sha(head), rel + ' differs from HEAD (sha256)');
});

/* ── refreshTint не пересоздаёт слой ─────────────────────────────────────── */
const tintFn = REFRACT.slice(REFRACT.indexOf('function refreshTint'),
  REFRACT.indexOf('var api = {'));
assert.ok(tintFn.includes('rec.tint = surfaceTint(el)'), 'refreshTint rereads tint');
assert.ok(!/makeLayer|appendChild|removeLayer|canvas\.width|zIndex|applyRingMask|filter/.test(tintFn),
  'refreshTint does not rebuild the layer, mask, filter or z-index');

/* ── Адаптер из реального app.js ─────────────────────────────────────────── */
const BUNDLE = path.join(ROOT, 'web', 'static', 'vendor', 'vue.global.prod.min.js');
global.window = global;
vm.runInThisContext(fs.readFileSync(BUNDLE, 'utf8'), { filename: BUNDLE });
const comps = {};
Vue.createApp = function () {
  return {
    component(name, def) {
      if (name && def) { comps[name] = def; return this; }
      return comps[name];
    },
    mount() { return {}; },
    provide() { return this; },
    use() { return this; },
    directive() { return this; },
    config: { globalProperties: {}, compilerOptions: {} },
  };
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  querySelector() { return null; }, querySelectorAll() { return []; },
  createElement() {
    return { style: {}, appendChild() {}, setAttribute() {},
             addEventListener() {}, remove() {} };
  },
  createElementNS() { return this.createElement(); },
  head: { appendChild() {} }, body: { appendChild() {}, removeChild() {} },
  documentElement: { style: {} },
};
global.Document = function Document() {};
global.ShadowRoot = function ShadowRoot() {};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('x'); } } },
});
global.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.history = { replaceState() {} };
global.location = { hash: '', href: '', pathname: '/' };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch'); };
require(path.join(ROOT, 'web', 'app.js'));
assert.strictEqual(typeof global.healthStateFrom, 'function', 'healthStateFrom exported');

const hs = global.healthStateFrom;
assert.strictEqual(stateOf('bot', { state: 'polling' }), 'normal');
assert.strictEqual(stateOf('bot', { state: 'running' }), 'normal');
assert.strictEqual(hs('bot', { state: 'polling', errors_total: 40 }).state, 'normal',
  'errors_total alone is not red');
assert.strictEqual(stateOf('bot', { state: 'polling_error' }), 'failed');
assert.strictEqual(stateOf('bot', { state: 'stopped' }), 'disabled');
assert.strictEqual(stateOf('bot', { state: 'starting' }), 'unknown');
assert.strictEqual(stateOf('bot', {}), 'unknown');
assert.strictEqual(stateOf('bot', { http_status: 200 }), 'unknown');
assert.strictEqual(stateOf('bot', { state: 'polling_error', stale: true }), 'unknown',
  'stale clears red');
assert.strictEqual(hs('bot', { state: 'polling_error', stale: true }).reason,
  'данные устарели');

assert.strictEqual(stateOf('heartbeat', { hbState: 'healthy' }), 'normal');
assert.strictEqual(stateOf('heartbeat', { hbState: 'warning' }), 'warning',
  'ASAP-UI-02 §6: предупреждение сердцебиения — собственное состояние warning');
assert.strictEqual(stateOf('heartbeat', { hbState: 'critical' }), 'failed');
assert.strictEqual(stateOf('heartbeat', { hbState: 'unknown' }), 'unknown');
assert.strictEqual(stateOf('heartbeat', { hbState: 'healthy', cpu: 0.99 }), 'normal',
  'a percent does not override hbState');
assert.strictEqual(stateOf('heartbeat', { cpu: 0.99, mem: 0.8 }), 'unknown',
  'raw metrics are not a verdict');

assert.strictEqual(stateOf('experience', { enabled: false, state: 'disabled' }), 'disabled');
assert.strictEqual(stateOf('experience', { enabled: true, state: 'not_run', items: [] }),
  'unknown');
assert.notStrictEqual(stateOf('experience', { enabled: true, state: 'not_run', items: [] }),
  'failed');
assert.strictEqual(stateOf('experience', { enabled: true, state: 'implemented', items: [] }),
  'normal');
assert.strictEqual(stateOf('memory', {
  beliefs_active: 0, facts_overdue: 0, smart_messages_total: 0,
}), 'unknown', 'counters are not a failure');
assert.notStrictEqual(stateOf('memory', { facts_overdue: 12 }), 'failed');
assert.strictEqual(stateOf('memory', { request_error: true }), 'unknown');
assert.strictEqual(stateOf('vision', { http_status: 200, effective_enabled: true }),
  'unknown', 'HTTP 200 is not a recognition verdict');
assert.strictEqual(stateOf('vision', {
  requested: true, capability: 'access_error', queue: { failed: 4 },
}), 'unknown');
assert.strictEqual(stateOf('vision', { requested: false, reason: 'vision_disabled' }),
  'disabled');
assert.strictEqual(stateOf('vision', { recognition_verdict: 'failed' }), 'failed');
assert.strictEqual(stateOf('sleep', { dream: { enabled: false, effective: false } }),
  'disabled');
assert.strictEqual(stateOf('sleep', {
  dream: { enabled: true, effective: true, state: 'sleep' },
}), 'unknown', 'enabled is not proof of a working run');
assert.ok(hs('sleep', { dream: { enabled: true } }).reason
  .indexOf('прогонов') >= 0);
assert.strictEqual(stateOf('sleep', {
  dream: { enabled: true, last_run_at: 1750000000 },
}), 'normal', 'confirmed run → normal');
assert.strictEqual(stateOf('sleep', { dream: { enabled: true, running: true } }),
  'normal');
assert.strictEqual(stateOf('sleep', {
  dream: { enabled: false }, deep_sleep: { enabled: true, last_run_at: 1750000000 },
}), 'normal', 'deep sleep alive — not disabled');
assert.strictEqual(stateOf('process', { health_status: 'failed' }), 'unknown');
assert.strictEqual(hs('process', { health_status: 'failed' }).paints, false);
assert.strictEqual(stateOf('bot', { level: 'WARN' }), 'unknown');
assert.strictEqual(stateOf('bot', { level: 'WARN', state: 'polling' }), 'normal');
/* §6: сам по себе WARN в журнале состояния не создаёт (нет перекраски);
   явный вердикт подсистемы `warning` — создаёт. */
assert.strictEqual(stateOf('bot', { level: 'WARNING', warn: true }), 'unknown');
assert.strictEqual(stateOf('experience', { health_status: 'warning' }), 'warning',
  'явный вердикт подсистемы warning доходит до карты');
assert.strictEqual(stateOf('bot', { problem: true }), 'degraded');
assert.strictEqual(stateOf('experience', {
  state: 'failed', chat_id: 2,
}, 1), 'unknown', 'other chat does not paint');
assert.strictEqual(stateOf('experience', {
  state: 'failed', chat_id: 2, affected_chats: 'чат 2',
}, 'global'), 'unknown');
assert.ok(hs('experience', {
  state: 'failed', chat_id: 2, affected_chats: 'чат 2',
}, 'global').reason.indexOf('чат 2') >= 0);

const failed = hs('bot', { state: 'polling_error' });
const normal = hs('bot', { state: 'polling' });
assert.strictEqual(failed.label, 'Сбой');
assert.strictEqual(failed.badge, 'badge-err');
assert.strictEqual(normal.label, 'Норма');
assert.ok(failed.ariaLabel.indexOf('Бот') >= 0 && failed.ariaLabel.indexOf('Сбой') >= 0);
assert.strictEqual(hs('heartbeat', { hbState: 'warning' }).label, 'Внимание');
assert.strictEqual(hs('heartbeat', { hbState: 'warning' }).badge, 'badge-warn');
assert.strictEqual(hs('heartbeat', { hbState: 'warning' }).paints, true,
  'warning красит стекло (мягче degraded/failed)');
assert.strictEqual(hs('heartbeat', { hbState: 'warning' }).icon, 'bolt',
  'иконка дублирует состояние, а не только цвет');
assert.strictEqual(hs('bot', { state: 'stopped' }).label, 'Выключено');
assert.strictEqual(hs('bot', { state: 'stopped' }).badge, 'badge-muted');
assert.strictEqual(hs('memory', { missing: true }).badge, 'badge-warn');

/* ── Две карточки: тонируется только проблемная ──────────────────────────── */
const def = comps['health-glass-surface'];
assert.ok(def && def.inheritAttrs === true, 'component inheritAttrs');
assert.ok(def.template.indexOf('role="status"') >= 0, 'inline status has role');
assert.ok(def.template.indexOf('aria-live="polite"') >= 0, 'inline status is live');
assert.ok(def.template.indexOf('role="group"') >= 0, 'root carries aria-label role');
/* Единственный механизм состояния — data-атрибуты; дублирующего класса нет. */
assert.ok(def.template.indexOf('data-health-state') >= 0);
assert.ok(def.template.indexOf('health-tint') < 0, 'no second (class) mechanism');
const compiled = Vue.compile(def.template);
const Comp = Object.assign({}, def, { render: compiled });

function createNode(tag) {
  return {
    nodeType: 1, tagName: String(tag).toUpperCase(), parentNode: null,
    childNodes: [], props: {}, style: {}, textContent: '',
    setAttribute(k, v) { this.props[k] = v; },
    getAttribute(k) { return this.props[k]; },
    addEventListener() {}, removeEventListener() {},
    getRootNode() { return this; }, contains() { return false; },
    remove() {},
  };
}
function removeNode(el) {
  if (!el || !el.parentNode) return;
  const arr = el.parentNode.childNodes;
  const i = arr.indexOf(el);
  if (i >= 0) arr.splice(i, 1);
  el.parentNode = null;
}
const renderer = Vue.createRenderer({
  insert(el, parent, anchor) {
    if (!parent) return;
    if (el.parentNode) removeNode(el);
    el.parentNode = parent;
    if (anchor == null) parent.childNodes.push(el);
    else {
      const i = parent.childNodes.indexOf(anchor);
      if (i < 0) parent.childNodes.push(el);
      else parent.childNodes.splice(i, 0, el);
    }
  },
  remove: removeNode,
  createElement: createNode,
  createText(t) { return { nodeType: 3, text: String(t), parentNode: null }; },
  createComment(t) { return { nodeType: 8, text: t, parentNode: null }; },
  setText(n, t) { n.text = t; },
  setElementText(n, t) { n.textContent = t; },
  parentNode(n) { return n.parentNode; },
  nextSibling(n) {
    const p = n.parentNode;
    if (!p) return null;
    const i = p.childNodes.indexOf(n);
    return i >= 0 ? (p.childNodes[i + 1] || null) : null;
  },
  patchProp(el, key, prev, next) { el.props[key] = next; },
});

function collect(node, out) {
  out = out || [];
  if (node && node.nodeType === 1) out.push(node);
  (node && node.childNodes || []).forEach(function (c) { collect(c, out); });
  return out;
}
function textOf(node, out) {
  out = out || [];
  if (node && node.nodeType === 3 && node.text) out.push(node.text);
  if (node && node.textContent) out.push(node.textContent);
  (node && node.childNodes || []).forEach(function (c) { textOf(c, out); });
  return out.join(' ');
}

const host = createNode('div');
const app = renderer.createApp({
  render() {
    return Vue.h('div', [
      Vue.h(Comp, {
        class: 'card status-hero',
        'data-glass': 'a',
        subsystem: 'bot',
        scope: 'global',
        material: 'bg',
        source: { state: 'polling_error', reason: 'polling_error' },
      }),
      Vue.h(Comp, {
        class: 'card',
        subsystem: 'experience',
        scope: 'global',
        material: 'bg',
        source: { enabled: true, state: 'implemented' },
      }),
    ]);
  },
});
app.mount(host);
const roots = host.childNodes[0].childNodes.filter(function (n) {
  return n.props && n.props['data-health-subsystem'];
});
assert.strictEqual(roots.length, 2, 'two glass roots rendered');
const bad = roots[0];
const ok = roots[1];
assert.strictEqual(bad.props['data-health-state'], 'failed');
assert.strictEqual(bad.props['data-health-material'], 'bg');
assert.ok(String(bad.props.class).indexOf('status-hero') >= 0,
  'card classes fall through to the same root');
assert.strictEqual(ok.props['data-health-state'], 'normal');
assert.strictEqual(ok.props['data-health-material'], 'bg');
assert.notStrictEqual(ok.props['data-health-state'], 'failed');
assert.notStrictEqual(ok.props['data-health-state'], 'degraded');
const badText = textOf(bad);
const okText = textOf(ok);
assert.ok(badText.indexOf('Сбой') >= 0, 'text status next to color');
assert.ok(okText.indexOf('Норма') >= 0, 'neighbor text is normal');
assert.ok(bad.props['aria-label'] && bad.props['aria-label'].indexOf('Сбой') >= 0);
/* Нейтральные состояния без аварийной заливки — проверено правилами CSS выше
   (нет правил для normal/unknown/disabled) и paints=false у адаптера. */
const neutral = comps['health-glass-surface'].computed.view.call({
  subsystem: 'memory', source: { missing: true }, scope: 'global',
});
assert.strictEqual(neutral.state, 'unknown');
assert.strictEqual(neutral.paints, false, 'unknown has no red fill');
const off = comps['health-glass-surface'].computed.view.call({
  subsystem: 'bot', source: { state: 'stopped' }, scope: 'global',
});
assert.strictEqual(off.state, 'disabled');
assert.strictEqual(off.paints, false, 'disabled is not an alarm');
/* Переход: только background-color; reduced-motion → мгновенно. */
assert.ok(/transition:\s*background-color/.test(healthCss));
assert.ok(!/transition:[^;]*(filter|backdrop-filter|transform|box-shadow|width|height)/.test(healthCss),
  'health transition touches fill color only');
assert.strictEqual(typeof def.methods.transitionMs, 'function');
global.getComputedStyle = function () { return { transitionDuration: '0.42s' }; };
assert.strictEqual(def.methods.transitionMs.call({}, { nodeType: 1 }), 420);
global.getComputedStyle = function () { return { transitionDuration: '0s' }; };
assert.strictEqual(def.methods.transitionMs.call({}, { nodeType: 1 }), 0,
  'reduced-motion (transition:none) → no eased loop');
/* syncGlassTint перечитывает подложку существующего слоя. */
let tintCalls = 0;
global.window.__GlassRefraction = { refreshTint: function () { tintCalls++; return true; } };
const fakeSelf = { $el: { nodeType: 1 }, _healthTintRaf: 0,
  cancelGlassTint: def.methods.cancelGlassTint,
  transitionMs: def.methods.transitionMs };
def.methods.syncGlassTint.call(fakeSelf);
assert.strictEqual(tintCalls, 1, 'instant refresh with transition:none');
assert.strictEqual(fakeSelf._healthTintRaf, 0, 'no rAF loop under reduced motion');
/* Обычный режим: canvas догоняет интерполяцию кадр за кадром. */
global.getComputedStyle = function () { return { transitionDuration: '0.42s' }; };
let frames = 0;
global.requestAnimationFrame = function () { frames++; return 7; };
global.cancelAnimationFrame = function () {};
const eased = { $el: { nodeType: 1 }, _healthTintRaf: 0,
  cancelGlassTint: def.methods.cancelGlassTint,
  transitionMs: def.methods.transitionMs };
def.methods.syncGlassTint.call(eased);
assert.strictEqual(frames, 1, 'eased path schedules rAF');
assert.strictEqual(eased._healthTintRaf, 7, 'raf handle stored for cancel');
delete global.requestAnimationFrame;
delete global.cancelAnimationFrame;
delete global.window.__GlassRefraction;

/* refreshTint no-op without a layer, and the public API exists. */
global.document.hidden = false;
global.getComputedStyle = function () { return { backgroundColor: 'rgba(21, 27, 42, 0.5)' }; };
delete require.cache[require.resolve(path.join(ROOT, 'web', 'static', 'glass-refraction.js'))];
require(path.join(ROOT, 'web', 'static', 'glass-refraction.js'));
const R = global.window.__GlassRefraction;
assert.strictEqual(typeof R.refreshTint, 'function');
assert.strictEqual(R.refreshTint({ nodeType: 1 }), false);
assert.strictEqual(R.diagnostics().layers.length, 0);

console.log('EVOL032-OK');
