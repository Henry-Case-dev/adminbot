'use strict';
/* ASAP-UI-02 — дельта §4.2/§10/§11: ОДИН Back-stack, ОДИН motion-масштаб,
 * палитра открывает конкретный объект.
 *
 * TEST-LIFECYCLE: CONTRACT owner=ASAP-UI-02 §4.2/§10/§11
 *   Строки карты: L01958/L01971 (Back закрывает вложенную область, а не всё
 *   Mini App), L01950 (единые motion-токены), L01940/L01943 (палитра ведёт к
 *   конкретному объекту, отсутствующий объект — честное состояние).
 *
 * Проверяется РЕАЛЬНЫЙ web/app.js (Vue-stub): методы вызываются на контексте,
 * как их вызывает шаблон/BackButton. Никаких «элемент существует» — только
 * наблюдаемое поведение: что именно закрылось, что осталось открытым,
 * изменился ли маршрут, какие значения движения реально применяются.
 *
 * Запуск: node tests/js/asap_ui02_delta_test.js
 * Успешный маркер: ASAP-UI02-DELTA-OK
 */
const path = require('path');
const assert = require('assert');

let captured = null;

// ── окружение ──────────────────────────────────────────────────────────────
global.Vue = {
  createApp(opts) { captured = opts; return { component() {}, provide() {}, use() {}, mount() {} }; },
};

const backBtn = {
  isVisible: false,
  shown: [],
  handler: null,
  show() { this.isVisible = true; this.shown.push('show'); },
  hide() { this.isVisible = false; this.shown.push('hide'); },
  onClick(fn) { this.handler = fn; },
};

global.window = {
  innerWidth: 390, innerHeight: 844,
  location: { hash: '#/ai', search: '' },
  addEventListener() {}, removeEventListener() {},
  Telegram: { WebApp: { BackButton: backBtn, viewportHeight: 800 } },
  visualViewport: null,
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  requestAnimationFrame: null,
};
global.document = {
  documentElement: {
    setAttribute() {}, getAttribute() { return null; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    style: { setProperty() {}, removeProperty() {} },
  },
  activeElement: null,
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  addEventListener() {},
  getElementById() { return null; },
  querySelector() { return null; },
  createElement() { return { style: {}, setAttribute() {}, appendChild() {} }; },
};
global.history = { replaceState() {} };
global.sessionStorage = { _s: {}, getItem(k) { return this._s[k] || null; }, setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; } };
global.localStorage = { _s: {}, getItem(k) { return this._s[k] || null; }, setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; } };
global.Chart = function () {};
global.fetch = async () => { throw new Error('no fetch'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
const methods = captured.methods || {};
const computed = captured.computed || {};

// vm с методами на инстансе (как в реальном Vue), плюс явные overrides.
function vm(extra) {
  const base = {
    route: '#/ai', toast() {}, $nextTick(fn) { if (fn) fn(); },
    canViewTab() { return true; }, canEditConfig() { return true; },
    navigateTo(r) { this.__nav = r; },
  };
  const out = Object.assign(base, extra || {});
  Object.keys(methods).forEach((k) => {
    if (typeof methods[k] !== 'function') return;
    if (extra && Object.prototype.hasOwnProperty.call(extra, k)) return;
    out[k] = methods[k].bind(out);
  });
  Object.keys(computed).forEach((k) => {
    if (extra && Object.prototype.hasOwnProperty.call(extra, k)) return;
    Object.defineProperty(out, k, {
      configurable: true,
      get: () => computed[k].call(out),
    });
  });
  return out;
}

// ═══ 1. Один Back-stack: порядок и «ровно один слой за Back» ══════════════
(function () {
  const calls = [];
  const v = vm({
    paletteOpen: true,
    promptEditorFull: true,
    statusRecordOpen: true,
    scopeOpen: true,
    drawerOpen: true,
    openModuleId: 'mod_x',
    closePalette() { calls.push('palette'); this.paletteOpen = false; },
    closeStatusRecord() { calls.push('record'); this.statusRecordOpen = false; },
    closeScope() { calls.push('scope'); this.scopeOpen = false; },
    closeDrawer() { calls.push('drawer'); this.drawerOpen = false; },
    closeModule() { calls.push('module'); this.openModuleId = null; },
    navigateTo(r) { calls.push('nav:' + r); },
  });
  assert.deepStrictEqual(v.backStack,
    ['palette', 'prompt-editor', 'record', 'scope', 'drawer', 'module'],
    'Back-stack сверху вниз: поиск → редактор → деталь → scope → drawer → окно');

  // Один Back = РОВНО один слой; маршрут не меняется.
  v.goBack();
  assert.deepStrictEqual(calls, ['palette'], 'Back закрыл только палитру');
  assert.strictEqual(v.route, '#/ai', 'Back не увёл маршрут');

  v.escClose();
  assert.deepStrictEqual(calls, ['palette'],
    'Esc закрыл ровно один слой (палитра)');
  assert.strictEqual(v.promptEditorFull, false,
    'следующий по старшинству слой закрыт, пока палитра была верхней');
  assert.strictEqual(v.statusRecordOpen, true, 'деталь осталась открытой');
  assert.strictEqual(v.scopeOpen, true, 'dropdown области остался открытым');
  assert.strictEqual(v.drawerOpen, true, 'drawer остался открытым');

  v.promptEditorFull = false;           // редактор закрыт своим действием
  v.goBack();
  assert.deepStrictEqual(calls, ['palette', 'record'],
    'следующий Back закрыл деталь, палитра уже закрыта');
  v.goBack();
  v.goBack();
  v.goBack();
  assert.deepStrictEqual(calls,
    ['palette', 'record', 'scope', 'drawer', 'module'],
    'послойное закрытие в правильном порядке');
  assert.strictEqual(v.backStack.length, 0, 'стек пуст');

  // Вложенных слоёв нет → работает «назад по маршруту».
  v.goBack();
  assert.strictEqual(calls.length, 5,
    'на корневом маршруте Back без слоёв ничего не делает (не закрывает Mini App)');

  const nav = [];
  const deep = vm({
    route: '#/modules/initiative', drawerOpen: false,
    closeDrawer() { nav.push('drawer'); },
    navigateTo(r) { nav.push('nav:' + r); },
  });
  deep.goBack();
  assert.deepStrictEqual(nav, ['nav:#/modules'],
    'без вложенных слоёв Back идёт к родителю маршрута');
})();

// ═══ 2. Негатив: закрытый слой не попадает в стек ═════════════════════════
(function () {
  const v = vm({ drawerOpen: false, paletteOpen: false, scopeOpen: false });
  assert.deepStrictEqual(v.backStack, [], 'закрытые слои не в стеке');
  const done = [];
  v.closeDrawer = () => done.push('drawer');
  assert.strictEqual(v.backStackClose(), false,
    'нечего закрывать → false (дальше решает маршрут)');
  assert.deepStrictEqual(done, [], 'ни один закрыватель не вызван');

  const v2 = vm({ scopeOpen: true, closeScope() { this.scopeOpen = false; } });
  assert.deepStrictEqual(v2.backStack, ['scope'], 'только открытый scope');
  assert.strictEqual(v2.backStackClose(), true, 'закрыли ровно scope');
  assert.deepStrictEqual(v2.backStack, [], 'после закрытия стек пуст');
})();

// ═══ 3. BackButton доступен и на корневом маршруте, если слой открыт ══════
(function () {
  const v = vm({ route: '#/ai', statusRecordOpen: false }); // корень: depth = 0
  v.initBackButton();
  assert.strictEqual(backBtn.handler !== null, true, 'onClick привязан один раз');
  backBtn.shown.length = 0;
  v.syncBackButton();
  assert.deepStrictEqual(backBtn.shown, [],
    'корневой маршрут без слоёв: BackButton скрыт (состояние не меняется)');
  assert.strictEqual(backBtn.isVisible, false, 'BackButton не виден');
  v.statusRecordOpen = true;
  v.syncBackButton();
  assert.deepStrictEqual(backBtn.shown, ['show'],
    'открытая деталь делает Back доступным (иначе Back закрыл бы всё Mini App)');
  assert.strictEqual(backBtn.isVisible, true, 'BackButton показан');
  // Нажатие нативного Back закрывает РОВНО деталь.
  let closed = 0;
  v.closeStatusRecord = () => { closed += 1; v.statusRecordOpen = false; };
  backBtn.handler();
  assert.strictEqual(closed, 1, 'нативный Back закрыл деталь');
  assert.strictEqual(v.route, '#/ai', 'маршрут не изменился');
  v.syncBackButton();
  assert.deepStrictEqual(backBtn.shown, ['show', 'hide'],
    'после закрытия слоя BackButton снова скрыт');

  const deep = vm({ route: '#/memory/lore' });
  backBtn.shown.length = 0;
  deep.initBackButton();
  deep.syncBackButton();
  assert.strictEqual(backBtn.isVisible, true,
    'вложенный маршрут по-прежнему показывает Back');
})();

// ═══ 4. Один motion-масштаб: численные значения приходят из CSS-токенов ══
(function () {
  const S = global.window.__StatusFeed;
  const FALLBACK = S.FALLBACK;
  const css = {
    '--motion-feed-speed': ' 24px ',
    '--motion-feed-resume': '1.5s',
    '--motion-feed-end-hold': '800ms',
    '--motion-feed-rewind': '0',
    '--motion-feed-start-hold': 'мусор',
  };
  const got = S.resolveMotionTokens((name) => css[name] || '', FALLBACK);
  assert.strictEqual(got.speedPxS, 24, 'скорость ленты — из --motion-feed-speed');
  assert.strictEqual(got.resumeMs, 1500, '2.6s-формат переводится в мс');
  assert.strictEqual(got.endHoldMs, 800, 'ms читаются как мс');
  assert.strictEqual(got.rewindMs, FALLBACK.rewindMs,
    'ноль в токене не останавливает ленту — честный фолбэк');
  assert.strictEqual(got.startHoldMs, FALLBACK.startHoldMs,
    'мусор в токене → фолбэк, а не NaN');
  // Движок использует ИМЕННО разрешённые значения (шаг = speed × dt).
  assert.strictEqual(S.step({ y: 0, max: 1000, phase: 'run' }, 1000).y,
    S.DEFAULTS.speedPxS, 'шаг ленты берёт скорость из того же DEFAULTS');
  assert.strictEqual(S.DEFAULTS.speedPxS, FALLBACK.speedPxS,
    'без CSS (юнит-окружение) работает фолбэк, равный CSS-значениям');
})();

// ═══ 5. Палитра ведёт к конкретному объекту, а не к «верху раздела» ═══════
(function () {
  const v = vm({
    route: '#/modules',
    closePalette() { this.paletteOpen = false; },
    _applyRouteFocus() { this.__focusApplied = true; },
  });
  v.paletteSelect({ route: '#/modules/initiative', focus: 'module-card:mod_initiative' });
  assert.strictEqual(global.window.location.hash,
    '#/modules/initiative?focus=module-card%3Amod_initiative',
    'выбор результата открывает конкретный объект, а не общий раздел');
  assert.strictEqual(v.__focusApplied, undefined,
    'смена маршрута идёт обычным путём (фокус применит applyRoute)');

  // Тот же маршрут → фокус применяется сразу, без hashchange.
  const same = vm({
    route: '#/modules/initiative',
    closePalette() { this.paletteOpen = false; },
    _applyRouteFocus() { this.__focusApplied = true; },
  });
  global.window.location.hash = '#/modules/initiative';
  same.paletteSelect({ route: '#/modules/initiative', focus: 'module-card:x' });
  assert.strictEqual(same.__focusApplied, true,
    'на том же маршруте фокус применяется сразу');
})();

// ═══ 6. Fullscreen-граф: Back закрывает слой, а не уходит в рекурсию ══════
// Живой прогон §12 п.6 нашёл цикл: `goBack → верхний слой = граф →
// closeGraphFull → goBack`. Закрыватель больше не идёт общим Back-путём,
// а сам возвращает на родительский маршрут; плюс у стека есть guard от
// повторного входа.
(function () {
  const nav = [];
  const v = vm({
    route: '#/status/graph',
    graphFullVisible: true,
    navigateTo(r) {
      nav.push('nav:' + r);
      this.route = r;
      this.graphFullVisible = false;
    },
  });
  assert.deepStrictEqual(v.backStack, ['graph-full'], 'граф — верхний слой стека');
  v.goBack();
  assert.deepStrictEqual(nav, ['nav:#/'],
    'Back закрывает fullscreen-граф возвратом на родительский маршрут');
  assert.deepStrictEqual(v.backStack, [], 'после Back граф больше не слой');
  assert.strictEqual(v.route, '#/', 'маршрут — родитель графа (#/status/graph → #/)');

  // Guard от повторного входа: закрыватель, который сам зовёт backStackClose,
  // не должен уронить приложение в переполнение стека.
  let reentered = 0;
  const loop = vm({
    drawerOpen: true,
    closeDrawer() { reentered += 1; this.backStackClose(); },
  });
  loop.goBack();
  assert.strictEqual(reentered, 1,
    'вложенный вызов backStackClose из закрывателя не зацикливается');
})();

// ═══ 7. Комбобокс области: лист на телефоне, dropdown на широком экране ═══
(function () {
  const box = { placement: 'bottom', maxHeight: 240, sheet: false, pad: 8 };
  const view = { visibleH: 700 };

  const desktop = methods.ctlScopePlacement.call(
    { shellMode: 'desktop' }, box, { visibleH: 700, isPhone: false });
  assert.strictEqual(desktop.placement, 'bottom',
    'на desktop размещение остаётся якорным (flip), не листом');
  assert.strictEqual(desktop.sheet, false, 'на desktop лист не включается');

  const phone = methods.ctlScopePlacement.call(
    { shellMode: 'mobile' }, box, { visibleH: 700 });
  assert.strictEqual(phone.sheet, true, 'на телефоне панель области — лист');
  assert.strictEqual(phone.placement, 'sheet', 'placement = sheet');
  assert.strictEqual(phone.maxHeight, 684,
    'лист ограничен видимой областью (700 - 2*8)');

  const flip = methods.ctlScopePlacement.call(
    { shellMode: 'compact' }, { placement: 'top', maxHeight: 200, sheet: false },
    { visibleH: 600 });
  assert.strictEqual(flip.placement, 'top',
    'на планшете сохраняется flip вверх, когда снизу нет места');
  assert.strictEqual(flip.sheet, false, 'на планшете лист не включается');
})();

console.log('ASAP-UI02-DELTA-OK');
