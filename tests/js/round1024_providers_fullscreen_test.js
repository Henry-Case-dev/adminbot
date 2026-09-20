'use strict';
/* F24 round 10.24 (providers-fullscreen-advanced-fix-round1024, ADR-1024-24).
 *
 * Боевой дефект: в «Провайдерах» аккордеон «Расширенные системные» схлопывался
 * при переходе TMA в fullscreen. Две причины:
 *   1. `:open` вызывал expandOpen() → чтение localStorage вне реактивности;
 *   2. isFullscreen не синхронизировался с Telegram.WebApp.isFullscreen.
 *
 * Покрытие:
 *   1) реактивность `:open`: expandOpen читает this.expand (не localStorage);
 *   2) initExpandState + переживание ремаунта (модель перезагрузки WebView);
 *   3) initExpandState: скан length/key, '' игнорируется, чужие префиксы — нет;
 *   4) C2: toggleExpand синхронизирует из ev.target.open (идемпотентно, без
 *      осцилляции), а не инвертирует;
 *   5) C3: initFullscreen/события/teardownFullscreen с теми же fn-ссылками;
 *   6) безопасность вне TG / SDK без onEvent/offEvent;
 *   7) раздельные scope-ключи (регресс 10.11).
 *
 * Запуск: node tests/js/round1024_providers_fullscreen_test.js → PROVIDERS-FS-OK
 */
const path = require('path');
const assert = require('assert');

// localStorage-мок с length/key(i) — initExpandState сканирует хранилище;
// expandOpen localStorage НЕ читает (реактивный стейт).
const _ls = {};
global.localStorage = {
  get length() { return Object.keys(_ls).length; },
  key(i) { return Object.keys(_ls)[i]; },
  getItem(k) {
    return Object.prototype.hasOwnProperty.call(_ls, k) ? _ls[k] : null;
  },
  setItem(k, v) { _ls[k] = String(v); },
  removeItem(k) { delete _ls[k]; },
};

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
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() {
        if (_bodyChildren.indexOf(this) >= 0) {
          _bodyChildren.splice(_bodyChildren.indexOf(this), 1);
        }
      },
    };
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) {
      const i = _bodyChildren.indexOf(el);
      if (i >= 0) _bodyChildren.splice(i, 1);
      return el;
    },
  },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('x'); } } },
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

// В браузере `Telegram` — глобал от vendor-скрипта (=== window.Telegram).
// В Node-стабе держим оба синхронными, как в реальном окружении.
function setTelegram(v) {
  global.window.Telegram = v;
  global.Telegram = v;
}

// ── 1) Реактивность `:open`: expandOpen НЕ читает localStorage ──────────────
assert.strictEqual(typeof computed.advancedOpen, 'function',
  'F24: computed advancedOpen присутствует');
assert.strictEqual(typeof computed.chatLoreAdvancedOpen, 'function',
  'F24: computed chatLoreAdvancedOpen присутствует');
assert.strictEqual(typeof computed.provAdvancedOpen, 'function',
  'F24: computed provAdvancedOpen присутствует');
assert.ok(methods.expandOpen.toString().indexOf('localStorage') < 0,
  'F24: expandOpen не читает localStorage (реактивный стейт)');

{
  const ctx = { expand: {}, expandOpen: methods.expandOpen,
                toggleExpand: methods.toggleExpand };
  methods.toggleExpand.call(ctx, 'llm_providers', 'prov-advanced');
  assert.strictEqual(
    ctx.expand['adminbot.expand:llm_providers:prov-advanced'], true,
    'F24: toggleExpand пишет реактивный стейт');
  assert.strictEqual(
    localStorage.getItem('adminbot.expand:llm_providers:prov-advanced'), '1',
    'F24: toggleExpand персистит в localStorage');
  assert.strictEqual(
    methods.expandOpen.call(ctx, 'llm_providers', 'prov-advanced'), true,
    'F24: expandOpen читает реактивный стейт');
}

// ── 2) Переживание ремаунта: чистый ctx + initExpandState поверх того же LS ──
{
  const ctx2 = { expand: {}, expandOpen: methods.expandOpen,
                 initExpandState: methods.initExpandState };
  methods.initExpandState.call(ctx2);
  assert.strictEqual(
    ctx2.expand['adminbot.expand:llm_providers:prov-advanced'], true,
    'F24: initExpandState поднимает раскрытие из localStorage');
  assert.strictEqual(
    methods.expandOpen.call(ctx2, 'llm_providers', 'prov-advanced'), true,
    'F24: раскрытие переживает ремаунт (модель перезагрузки WebView)');
}

// ── 3) initExpandState: скан length/key, '' игнорируется, чужие префиксы — нет
{
  localStorage.setItem('adminbot.expand:some_tab', '');
  localStorage.setItem('adminbot.expand:other_tab', '1');
  localStorage.setItem('other.prefix:key', '1');
  const ctx3 = { expand: {}, initExpandState: methods.initExpandState };
  methods.initExpandState.call(ctx3);
  assert.strictEqual(ctx3.expand['adminbot.expand:other_tab'], true,
    'F24: значение «1» поднимается');
  assert.ok(!Object.prototype.hasOwnProperty.call(ctx3.expand,
    'adminbot.expand:some_tab'), 'F24: значение "" игнорируется');
  assert.ok(!Object.prototype.hasOwnProperty.call(ctx3.expand,
    'other.prefix:key'), 'F24: чужие префиксы игнорируются');
}

// ── 4) C2: синхронизация из события (идемпотентность, без осцилляции) ───────
{
  const ctx4 = { expand: {}, toggleExpand: methods.toggleExpand };
  methods.toggleExpand.call(ctx4, 't', 's', { target: { open: true } });
  assert.strictEqual(ctx4.expand['adminbot.expand:t:s'], true,
    'C2: событие open=true → раскрыто');
  methods.toggleExpand.call(ctx4, 't', 's', { target: { open: true } });
  assert.strictEqual(ctx4.expand['adminbot.expand:t:s'], true,
    'C2: повторное open=true идемпотентно (нет осцилляции)');
  methods.toggleExpand.call(ctx4, 't', 's', { target: { open: false } });
  assert.strictEqual(ctx4.expand['adminbot.expand:t:s'], false,
    'C2: событие open=false → свёрнуто');
}

// ── 5) C3: fullscreen init / события / отписка ──────────────────────────────
const _events = {};
const _calls = { on: [], off: [] };
setTelegram({
  WebApp: {
    isFullscreen: true,
    onEvent(n, cb) { _calls.on.push(n); _events[n] = cb; },
    offEvent(n, cb) { _calls.off.push([n, cb]); },
  },
});
{
  const fctx = { isFullscreen: false,
                 initFullscreen: methods.initFullscreen,
                 setFullscreenFromTma: methods.setFullscreenFromTma,
                 teardownFullscreen: methods.teardownFullscreen };
  methods.initFullscreen.call(fctx);
  assert.strictEqual(fctx.isFullscreen, true,
    'C3: isFullscreen инициализируется из TMA');
  assert.ok(_calls.on.indexOf('fullscreenChanged') >= 0,
    'C3: подписка fullscreenChanged');
  assert.ok(_calls.on.indexOf('viewportChanged') >= 0,
    'C3: подписка viewportChanged');
  // Повторный init (из `ready`, контекст появился позже) не дублирует подписки.
  methods.initFullscreen.call(fctx);
  assert.strictEqual(
    _calls.on.filter((n) => n === 'fullscreenChanged').length, 1,
    'C3: guard _fsSubscribed — без двойных подписок');

  global.window.Telegram.WebApp.isFullscreen = false;
  _events.fullscreenChanged();
  assert.strictEqual(fctx.isFullscreen, false,
    'C3: fullscreenChanged → флаг производный от TMA');
  global.window.Telegram.WebApp.isFullscreen = true;
  _events.viewportChanged();
  assert.strictEqual(fctx.isFullscreen, true,
    'C3: viewportChanged → флаг производный от TMA');

  methods.teardownFullscreen.call(fctx);
  assert.strictEqual(_calls.off.length, 2, 'C3: offEvent для двух событий');
  assert.strictEqual(_calls.off[0][0], 'fullscreenChanged',
    'C3: offEvent — fullscreenChanged');
  assert.strictEqual(_calls.off[0][1], _events.fullscreenChanged,
    'C3: offEvent с ТОЙ ЖЕ fn-ссылкой (fullscreen)');
  assert.strictEqual(_calls.off[1][0], 'viewportChanged',
    'C3: offEvent — viewportChanged');
  assert.strictEqual(_calls.off[1][1], _events.viewportChanged,
    'C3: offEvent с ТОЙ ЖЕ fn-ссылкой (viewport)');
  // Повторный teardown безопасен.
  assert.doesNotThrow(() => methods.teardownFullscreen.call(fctx),
    'C3: повторный teardownFullscreen не бросает');
}

// ── 5b) review iter1: исключение на втором onEvent не оставляет подписку ─────
{
  const c2 = { off: [] };
  const wa = {
    isFullscreen: false,
    onEvent(n) { if (n === 'viewportChanged') throw new Error('boom'); },
    offEvent(n, cb) { c2.off.push([n, cb]); },
  };
  setTelegram({ WebApp: wa });
  const ectx = { isFullscreen: false,
                 initFullscreen: methods.initFullscreen,
                 setFullscreenFromTma: methods.setFullscreenFromTma,
                 teardownFullscreen: methods.teardownFullscreen };
  assert.doesNotThrow(() => methods.initFullscreen.call(ectx),
    'review: initFullscreen глотает исключение onEvent');
  assert.ok(c2.off.some((c) => c[0] === 'fullscreenChanged'),
    'review: первый листенер снят best-effort при сбое второго');
  // Guard сброшен → повторный init снова подписывается (не «залип»).
  let resub = 0;
  wa.onEvent = function () { resub++; };
  methods.initFullscreen.call(ectx);
  assert.strictEqual(resub, 2,
    'review: guard сброшен — повторный init подписывает заново');
  methods.teardownFullscreen.call(ectx);
}

// ── 5c) review iter1: toggleFullscreen не фиксирует устаревшее состояние ────
{
  const savedRaf = global.window.requestAnimationFrame;
  let flushed = null;
  global.window.requestAnimationFrame = (cb) => { flushed = cb; return 1; };
  setTelegram({
    WebApp: {
      isFullscreen: false,
      requestFullscreen() { this.isFullscreen = true; },
      exitFullscreen() { this.isFullscreen = false; },
    },
  });
  const tctx = { isFullscreen: false,
                 toggleFullscreen: methods.toggleFullscreen,
                 setFullscreenFromTma: methods.setFullscreenFromTma };
  methods.toggleFullscreen.call(tctx);
  // requestFullscreen уже сменил wa.isFullscreen на true, но синхронно флаг
  // НЕ фиксируем — ждём событие/отложенный re-read (иначе UI врёт).
  assert.strictEqual(tctx.isFullscreen, false,
    'review: без синхронной фиксации устаревшего значения');
  assert.strictEqual(typeof flushed, 'function',
    'review: запланирован отложенный re-read (rAF)');
  flushed();
  assert.strictEqual(tctx.isFullscreen, true,
    'review: отложенный re-read берёт фактический режим TMA');

  // Legacy-фолбэк: SDK без boolean → прежняя инверсия (сразу).
  setTelegram({ WebApp: { requestFullscreen() {}, exitFullscreen() {} } });
  const lctx = { isFullscreen: false, toggleFullscreen: methods.toggleFullscreen };
  methods.toggleFullscreen.call(lctx);
  assert.strictEqual(lctx.isFullscreen, true,
    'review: legacy-фолбэк (нет boolean) — инверсия');
  methods.toggleFullscreen.call(lctx);
  assert.strictEqual(lctx.isFullscreen, false,
    'review: legacy-фолбэк — обратная инверсия');

  if (savedRaf === undefined) delete global.window.requestAnimationFrame;
  else global.window.requestAnimationFrame = savedRaf;
}

// ── 6) Безопасность вне TG / SDK без методов ────────────────────────────────
{
  setTelegram(null);
  const nctx = { isFullscreen: false,
                 initFullscreen: methods.initFullscreen,
                 setFullscreenFromTma: methods.setFullscreenFromTma,
                 teardownFullscreen: methods.teardownFullscreen,
                 toggleFullscreen: methods.toggleFullscreen };
  assert.doesNotThrow(() => methods.initFullscreen.call(nctx),
    'F24: initFullscreen вне TG не бросает');
  assert.doesNotThrow(() => methods.setFullscreenFromTma.call(nctx),
    'F24: setFullscreenFromTma вне TG не бросает');
  assert.doesNotThrow(() => methods.teardownFullscreen.call(nctx),
    'F24: teardownFullscreen вне TG не бросает');
  assert.doesNotThrow(() => methods.toggleFullscreen.call(nctx),
    'F24: toggleFullscreen вне TG не бросает');
  // SDK без onEvent/offEvent.
  setTelegram({ WebApp: { isFullscreen: false } });
  assert.doesNotThrow(() => methods.initFullscreen.call(nctx),
    'F24: initFullscreen (нет onEvent) не бросает');
  assert.doesNotThrow(() => methods.teardownFullscreen.call(nctx),
    'F24: teardownFullscreen (нет offEvent) не бросает');
}

// ── 7) Раздельные scope-ключи (регресс 10.11) ───────────────────────────────
{
  const ctx7 = { expand: {}, expandOpen: methods.expandOpen,
                 toggleExpand: methods.toggleExpand };
  methods.toggleExpand.call(ctx7, 'llm_providers', 'prov-advanced');
  assert.strictEqual(methods.expandOpen.call(ctx7, 'llm_providers'), false,
    'F24: inner bare-ключ не пересекается с outer scope');
  assert.strictEqual(
    methods.expandOpen.call(ctx7, 'llm_providers', 'prov-advanced'), true,
    'F24: outer scope-ключ отдельный');
}

// ── computed-аксессоры: значения из реактивного стейта ──────────────────────
assert.strictEqual(computed.advancedOpen.call(
  { expand: { 'adminbot.expand:status': true }, activeTab: 'status' }), true,
  'F24: advancedOpen читает bare-ключ активной вкладки');
assert.strictEqual(computed.advancedOpen.call(
  { expand: {}, activeTab: 'status' }), false,
  'F24: advancedOpen по умолчанию свёрнут');
assert.strictEqual(computed.provAdvancedOpen.call(
  { expand: { 'adminbot.expand:llm_providers:prov-advanced': true } }), true,
  'F24: provAdvancedOpen читает scope-ключ');
assert.strictEqual(computed.chatLoreAdvancedOpen.call(
  { expand: { 'adminbot.expand:chat_lore': true } }), true,
  'F24: chatLoreAdvancedOpen фиксирует tabId chat_lore');
assert.strictEqual(computed.chatLoreAdvancedOpen.call(
  { expand: { 'adminbot.expand:other': true } }), false,
  'F24: chatLoreAdvancedOpen не заглядывает в чужие ключи');

console.log('PROVIDERS-FS-OK');
