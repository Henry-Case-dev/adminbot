'use strict';
/* EVOL-043/044/045 (W11) — юниты контракта контролов, клавиатуры и прогресса.
 *
 * Проверяется поведение, а не строки CSS:
 *   * единственный источник видимой области (`_ctlViewport`): Android (resize
 *     layout и visual viewport вместе) и iOS (клавиатура накрывает страницу —
 *     visualViewport уменьшается, innerHeight/offsetTop дают перекрытие);
 *   * `_syncKeyboardOffset` выставляет `--kb-offset`, `--vv-h` (только при
 *     открытой клавиатуре) и наблюдаемые классы `kb-open`/`kb-tight`;
 *   * поле в фокусе не переставляется, а прокручивается ровно на перекрытие
 *     (`_ctlRevealFocusedField` через `_ctlApplyKeyboardMetrics`);
 *   * `ctlProgress` не выдумывает данные: нет пары done/total → unknown,
 *     done>total и отрицательные значения диагностируются, stale/error видны,
 *     единицы и период попадают в подпись;
 *   * `ctlPlacePopover` переворачивает панель вверх, когда снизу нет места, и
 *     отдаёт лист (`sheet`), когда не помещается ни снизу, ни сверху.
 *
 * Запуск: node tests/js/evol_w11_controls_test.js
 * Ожидаемый маркер: EVOL-W11-CONTROLS-OK
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

// ── DOM-заглушки ────────────────────────────────────────────────────────────
const styleVars = {};
const classes = new Set();
const rootEl = {
  style: {
    setProperty: (k, v) => { styleVars[k] = v; },
    removeProperty: (k) => { delete styleVars[k]; },
  },
  classList: {
    add: (n) => classes.add(n),
    remove: (n) => classes.delete(n),
    contains: (n) => classes.has(n),
    toggle: (n, on) => {
      if (on === undefined) on = !classes.has(n);
      if (on) classes.add(n); else classes.delete(n);
      return on;
    },
  },
  setAttribute() {},
  getAttribute() { return null; },
};

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};

function makeWindow() {
  return {
    innerWidth: 390,
    innerHeight: 844,
    location: { hash: '' },
    addEventListener() {},
    removeEventListener() {},
    Telegram: null,
    visualViewport: null,
    getComputedStyle: null,
    requestAnimationFrame: null,
    scrollBy() {},
    matchMedia: () => ({ matches: false, addEventListener() {} }),
  };
}

global.window = makeWindow();
global.document = {
  documentElement: rootEl,
  activeElement: null,
  hidden: false,
  addEventListener() {},
  getElementById() { return null; },
  querySelector() { return null; },
  createElement() {
    return { tagName: 'div', className: '', value: '', style: {},
             setAttribute() {}, focus() {}, select() {}, remove() {} };
  },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
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
global.localStorage = {
  _s: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван при загрузке app.js');
const methods = captured.methods || {};
const computed = captured.computed || {};

function resetViewport() {
  global.window.innerHeight = 844;
  global.window.visualViewport = null;
  Object.keys(styleVars).forEach((k) => { delete styleVars[k]; });
  classes.clear();
  global.document.activeElement = null;
}

// ── 1. Источник видимой области: iOS (overlay) vs Android (resize) ─────────
{
  resetViewport();
  // iOS: layout viewport не сжимается, visualViewport уменьшается и сдвигается.
  global.window.visualViewport = { height: 500, offsetTop: 0, width: 390 };
  let m = methods._ctlViewport.call({});
  assert.strictEqual(m.source, 'visualViewport', 'источник — visualViewport');
  assert.strictEqual(m.visibleH, 500, 'видимая высота — из visualViewport');
  assert.strictEqual(m.keyboard, 344, 'перекрытие = innerHeight − vv.height');

  // iOS со сдвигом visual viewport (страница прокручена вверх под клавиатуру).
  global.window.visualViewport = { height: 500, offsetTop: 120, width: 390 };
  m = methods._ctlViewport.call({});
  assert.strictEqual(m.keyboard, 224, 'offsetTop учитывается (не двойной счёт)');

  // Android: visual viewport уменьшается вместе с layout — перекрытия нет.
  global.window.innerHeight = 500;
  global.window.visualViewport = { height: 500, offsetTop: 0, width: 390 };
  m = methods._ctlViewport.call({});
  assert.strictEqual(m.keyboard, 0, 'Android resize: клавиатура не «добавляется» дважды');

  // Клавиатура закрыта, visualViewport отсутствует — layout viewport.
  resetViewport();
  m = methods._ctlViewport.call({});
  assert.strictEqual(m.source, 'layout', 'без visualViewport — layout viewport');
  assert.strictEqual(m.visibleH, 844);
  assert.strictEqual(m.keyboard, 0);

  // TMA-фолбэк: Mini App сообщает свою высоту, когда visualViewport нет.
  global.window.Telegram = { WebApp: { viewportHeight: 600 } };
  m = methods._ctlViewport.call({});
  assert.strictEqual(m.source, 'tma', 'TMA viewport API как фолбэк');
  assert.strictEqual(m.visibleH, 600);
  global.window.Telegram = null;
}

// ── 2. Применение метрик: переменные и наблюдаемые классы ─────────────────
{
  resetViewport();
  global.window.visualViewport = { height: 500, offsetTop: 0, width: 390 };
  methods._syncKeyboardOffset.call({});
  assert.strictEqual(styleVars['--kb-offset'], '344px', '--kb-offset из метрик');
  assert.strictEqual(styleVars['--vv-h'], '500px', '--vv-h выставлен при клавиатуре');
  assert.ok(classes.has('kb-open'), 'html.kb-open при открытой клавиатуре');
  assert.ok(!classes.has('kb-tight'), '500px — панель действий ещё помещается');

  // Слишком низкая видимая область (landscape + клавиатура) → не липнем.
  global.window.visualViewport = { height: 200, offsetTop: 0, width: 667 };
  methods._syncKeyboardOffset.call({});
  assert.ok(classes.has('kb-tight'), 'низкая видимая область → kb-tight');

  // Клавиатура закрыта: переменная снята, классы сняты.
  resetViewport();
  methods._syncKeyboardOffset.call({});
  assert.strictEqual(styleVars['--kb-offset'], '0px', '--kb-offset сброшен');
  assert.ok(!Object.prototype.hasOwnProperty.call(styleVars, '--vv-h'),
    '--vv-h снят: работает --app-usable-height (TMA-высота не подменяется)');
  assert.ok(!classes.has('kb-open'), 'kb-open снят');
  assert.ok(!classes.has('kb-tight'), 'kb-tight снят');
}

// ── 3. Поле в фокусе: прокрутка вместо перестановки поля ─────────────────
{
  resetViewport();
  // Клавиатура открыта: видимая область 500 из 844.
  global.window.visualViewport = { height: 500, offsetTop: 0, width: 390 };
  const scroller = {
    scrollTop: 0,
    scrollHeight: 4000,
    clientHeight: 600,
    nodeType: 1,
    parentElement: null,
  };
  const wrapper = {
    nodeType: 1,
    scrollHeight: 600,
    clientHeight: 600,
    parentElement: scroller,
  };
  const field = {
    tagName: 'TEXTAREA',
    parentElement: wrapper,
    value: 'черновик',
    selectionStart: 7,
    selectionEnd: 7,
    closest: () => ({}),
    getBoundingClientRect: () => ({ top: 620, bottom: 700, left: 0, right: 300 }),
  };
  global.window.getComputedStyle = () => ({ overflowY: 'auto' });
  global.document.activeElement = field;
  methods._syncKeyboardOffset.call({});
  // Видимая область 500 → перекрытие 344; поле до низа 700 → нужен сдвиг.
  assert.ok(scroller.scrollTop > 0, 'контейнер прокручен, поле выведено из-под клавиатуры');
  assert.strictEqual(field.value, 'черновик', 'черновик не тронут');
  assert.strictEqual(field.selectionStart, 7, 'каретка/selection не сброшены');

  // Поле уже видно — прокрутка НЕ меняется (иначе «дёрганье» при вводе).
  const before = scroller.scrollTop;
  field.getBoundingClientRect = () => ({ top: 100, bottom: 160, left: 0, right: 300 });
  global.window.visualViewport = { height: 500, offsetTop: 0, width: 390 };
  methods._syncKeyboardOffset.call({});
  assert.strictEqual(scroller.scrollTop, before,
    'видимое поле не вызывает прокрутку (нет reflow при вводе)');

  // Без клавиатуры — никакой прокрутки вообще.
  resetViewport();
  global.document.activeElement = field;
  field.getBoundingClientRect = () => ({ top: 620, bottom: 700, left: 0, right: 300 });
  scroller.scrollTop = 0;
  methods._syncKeyboardOffset.call({});
  assert.strictEqual(scroller.scrollTop, 0, 'без клавиатуры прокрутка не выполняется');
  global.window.getComputedStyle = null;
}

// ── 4. Достоверность прогресса ───────────────────────────────────────────
{
  // Нет пары → «нет данных», никакой заливки.
  let p = methods.ctlProgress.call({}, null, 100, { unit: '%' });
  assert.strictEqual(p.state, 'unknown', 'null → unknown');
  assert.strictEqual(p.percent, null, 'процент не выдумывается');
  assert.strictEqual(p.ratio, 0, 'заливки нет');
  assert.ok(p.ariaText.length > 0, 'текстовое состояние есть (a11y fallback)');

  // Устаревшие данные видны отдельным состоянием.
  p = methods.ctlProgress.call({}, 3, 10, { stale: true, unit: 'задач' });
  assert.strictEqual(p.state, 'stale', 'stale виден как stale');

  // Ошибка запроса данных — не маскируется «живым» баром.
  p = methods.ctlProgress.call({}, null, null, { error: true });
  assert.strictEqual(p.state, 'error');

  // Нормальный determinate: единицы, период и валидный aria.
  p = methods.ctlProgress.call({}, 3, 10, { unit: 'задач', period: 'за сутки', label: 'Очередь' });
  assert.strictEqual(p.state, 'working');
  assert.strictEqual(p.percent, 30);
  assert.strictEqual(p.ariaNow, 30);
  assert.ok(/задач/.test(p.ariaText) && /за сутки/.test(p.ariaText),
    'подпись содержит единицы и период');
  assert.ok(/Очередь/.test(p.ariaText), 'подпись содержит название показателя');

  // Завершено.
  p = methods.ctlProgress.call({}, 10, 10, { unit: 'шт' });
  assert.strictEqual(p.state, 'done');
  assert.strictEqual(p.percent, 100);

  // 0 из 0 не превращается в «100 % успеха» без смысла: явное завершение.
  p = methods.ctlProgress.call({}, 0, 0, {});
  assert.strictEqual(p.percent, 100);
  assert.strictEqual(p.state, 'done');

  // Невозможное done>total диагностируется, а не скрывается.
  p = methods.ctlProgress.call({}, 12, 10, { unit: 'шагов' });
  assert.strictEqual(p.anomaly, 'done>total', 'аномалия названа');
  assert.strictEqual(p.ratio, 1, 'полоса не уезжает за 100 %');
  assert.ok(p.ariaText.indexOf('больше лимита') >= 0, 'аномалия видна в тексте');

  // Отрицательные значения — ошибка, а не «0 %».
  p = methods.ctlProgress.call({}, -5, 10, {});
  assert.strictEqual(p.anomaly, 'negative');
  assert.strictEqual(p.state, 'error');

  // Indeterminate только по явному сигналу «работает».
  p = methods.ctlProgress.call({}, null, null, { indeterminate: true, state: 'checking' });
  assert.strictEqual(p.indeterminate, true);
  assert.strictEqual(p.state, 'checking');

  // Ресурсная полоса: статичная, без «ожидания очереди».
  p = methods.ctlProgress.call({}, 0, 100, { unit: '%', state: 'idle' });
  assert.strictEqual(p.state, 'idle', 'CPU 0 % — статичная полоса, не «waiting»');
}

// ── 5. Размещение выпадающей панели ──────────────────────────────────────
{
  // Снизу места достаточно → панель под триггером.
  let box = methods.ctlPlacePopover.call({}, { top: 100, bottom: 140, left: 40, right: 200 },
    { height: 200, width: 240 }, { visibleH: 844, width: 390 });
  assert.strictEqual(box.placement, 'bottom');
  assert.ok(box.maxHeight >= 200, 'высота ограничена доступным местом');

  // Снизу мало, сверху достаточно → flip ВВЕРХ.
  box = methods.ctlPlacePopover.call({}, { top: 700, bottom: 740, left: 40, right: 200 },
    { height: 300, width: 240 }, { visibleH: 844, width: 390 });
  assert.strictEqual(box.placement, 'top', 'flip вверх при нехватке места снизу');

  // Ни снизу, ни сверху (низкий ландшафт + клавиатура) → лист.
  box = methods.ctlPlacePopover.call({}, { top: 180, bottom: 220, left: 40, right: 200 },
    { height: 320, width: 240 }, { visibleH: 260, width: 667 });
  assert.strictEqual(box.sheet, true, 'короткая видимая область → sheet');
  assert.strictEqual(box.placement, 'sheet');

  // Нет метрик (юнит-стаб/нет layout) → безопасный дефолт без исключения.
  box = methods.ctlPlacePopover.call({}, {}, {}, {});
  assert.strictEqual(box.placement, 'bottom');
  assert.strictEqual(box.maxHeight, null);
}

// ── 6. Ресурсная пара used/total без `percent` ────────────────────────────
{
  // Сервер прислал пару, но не процент: считаем сами (не «нет данных»).
  let p = computed.ctlMemProg.call({
    statusSys: { mem: { used: 536870912, total: 2147483648, percent: null } },
  });
  assert.strictEqual(p.percent, 25, 'процент считается из пары used/total');
  assert.strictEqual(p.state, 'idle', 'полоса ресурса остаётся статичной');
  assert.strictEqual(p.ariaNow, 25, 'aria отражает ту же цифру');

  // Процент сервера имеет приоритет (не пересчитываем «на глаз»).
  p = computed.ctlMemProg.call({
    statusSys: { mem: { used: 1, total: 1000000, percent: 77 } },
  });
  assert.strictEqual(p.percent, 77, 'подтверждённый сервером процент не подменяется');

  // Нет пары и нет процента → честное «нет данных».
  p = computed.ctlDiskProg.call({
    statusSys: { disk: { used: null, total: null, percent: null } },
  });
  assert.strictEqual(p.state, 'unknown', 'без чисел — unknown');
  assert.strictEqual(p.percent, null, 'процент не выдумывается');

  // Нулевой знаменатель не превращается в 100 %.
  p = computed.ctlDiskProg.call({
    statusSys: { disk: { used: 0, total: 0, percent: null } },
  });
  assert.strictEqual(p.state, 'unknown', 'total=0 не даёт «завершено»');

  // Переполнение пары не уезжает за 100 %.
  p = computed.ctlDiskProg.call({
    statusSys: { disk: { used: 900, total: 100, percent: null } },
  });
  assert.strictEqual(p.percent, 100, 'percent не больше 100');
}

// ── 7. Тумблер: контейнер контракта ↔ селектор состояния ─────────────────
// Регрессия: CSS ждал контейнер `.ctl-toggle`, а метки несли только трек —
// включённое и выключенное состояния рисовались одинаково.
{
  const WEB = path.join(__dirname, '..', '..', 'web');
  const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  const css = fs.readFileSync(path.join(WEB, 'static', 'app.css'), 'utf8');

  // Разбор РЕАЛЬНОЙ разметки: метки, внутри которых есть трек тумблера.
  const toggles = [];
  const labelRe = /<label\b[^>]*>[\s\S]*?<\/label>/g;
  let m;
  while ((m = labelRe.exec(html))) {
    const block = m[0];
    if (block.indexOf('ctl-toggle__track') < 0) continue;
    const tagEnd = block.indexOf('>') + 1;
    const cls = (block.slice(0, tagEnd).match(/class="([^"]*)"/) || [null, ''])[1];
    const inner = block.slice(tagEnd);
    const inAt = inner.indexOf('<input');
    const inEnd = inAt >= 0 ? inner.indexOf('>', inAt) : -1;
    const trackAt = inner.indexOf('ctl-toggle__track');
    const trackTag = inner.lastIndexOf('<', trackAt);
    const between = (inEnd >= 0 && trackTag > inEnd)
      ? inner.slice(inEnd + 1, trackTag) : null;
    toggles.push({
      line: html.slice(0, m.index).split('\n').length,
      classes: cls.split(/\s+/).filter(Boolean),
      siblingAfterInput: between !== null && /^\s*$/.test(between),
    });
  }
  assert.strictEqual(toggles.length, 15, 'тумблеров контракта должно быть 15');
  const orphan = toggles.filter((t) => t.classes.indexOf('ctl-toggle') < 0);
  assert.deepStrictEqual(orphan.map((t) => t.line), [],
    'метка без контейнера .ctl-toggle — CSS состояния не совпадёт');
  const notSibling = toggles.filter((t) => !t.siblingAfterInput);
  assert.deepStrictEqual(notSibling.map((t) => t.line), [],
    'input должен стоять до трека у того же родителя (селектор `~`)');

  // Селектор состояния называет ИМЕННО этот контейнер.
  const onSel = /(\.[\w-]+)\s+input:checked\s*~\s*\.ctl-toggle__track\s*\{([^}]*)\}/
    .exec(css);
  assert.ok(onSel, 'нет правила включённого состояния трека');
  const container = onSel[1].replace('.', '');
  toggles.forEach((t) => assert.ok(t.classes.indexOf(container) >= 0,
    'контейнер .' + container + ' отсутствует в строке ' + t.line));

  // Значения состояний РАЗНЫЕ (и включённое — акцентный токен, не серый).
  const offBody = /\.ctl-toggle__track\s*\{([^}]*)\}/.exec(css)[1];
  const onBody = onSel[2];
  const offBg = (/background:\s*([^;]+);/.exec(offBody) || [null, ''])[1].trim();
  const onBg = (/background:\s*([^;]+);/.exec(onBody) || [null, ''])[1].trim();
  assert.ok(offBg && onBg, 'у состояний есть явный цвет заливки');
  assert.notStrictEqual(offBg, onBg, 'состояния объявлены одинаково');
  const token = /--purple-400:\s*#([0-9A-Fa-f]{6})/.exec(css);
  assert.ok(token, 'нет токена --purple-400');
  const accent = [0, 2, 4].map((i) => parseInt(token[1].slice(i, i + 2), 16));
  const offRgb = /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/.exec(offBg);
  assert.ok(offRgb, 'выключенный трек имеет явный цвет');
  assert.notDeepStrictEqual(
    accent, [1, 2, 3].map((i) => parseInt(offRgb[i], 10)),
    'включённый и выключенный трек одного цвета');
  assert.ok(onBg.indexOf('var(--purple-400)') >= 0,
    'включённое состояние берёт акцент из токена');

  // Бегунок едет внутри трека: 44 − 20 − 2 = 22 ≥ сдвиг.
  const thumbShift =
    /\.ctl-toggle\s+input:checked\s*~\s*\.ctl-toggle__track\s+\.ctl-toggle__thumb\s*\{([^}]*)\}/
      .exec(css);
  assert.ok(thumbShift, 'нет правила сдвига бегунка для включённого состояния');
  const shift = /translateX\((\d+)px\)/.exec(thumbShift[1]);
  assert.ok(shift, 'бегунок не сдвигается во включённом состоянии');
  const trackW = parseFloat((/width:\s*(\d+)px/.exec(offBody) || [null, 0])[1]);
  const thumbRule = /\.ctl-toggle__thumb\s*\{([^}]*)\}/.exec(css)[1];
  const thumbW = parseFloat((/width:\s*(\d+)px/.exec(thumbRule) || [null, 0])[1]);
  const left = parseFloat((/left:\s*(\d+)px/.exec(thumbRule) || [null, 0])[1]);
  assert.ok(trackW > 0 && thumbW > 0, 'геометрия трека/бегунка найдена');
  assert.strictEqual(trackW - (left + thumbW + Number(shift[1])), left,
    'во включённом состоянии бегунок остаётся внутри трека с тем же отступом');

  // Недоступный тумблер виден как недоступный.
  assert.ok(/\.ctl-toggle\s+input:disabled\s*~\s*\.ctl-toggle__track\s*\{[^}]*opacity/
    .test(css), 'нет визуального признака недоступности');

  // Одна реализация состояния: Tailwind peer-checked не вернулся.
  assert.strictEqual(html.indexOf('peer-checked:'), -1,
    'вернулась вторая (Tailwind) реализация состояния тумблера');
}

console.log('EVOL-W11-CONTROLS-OK');
