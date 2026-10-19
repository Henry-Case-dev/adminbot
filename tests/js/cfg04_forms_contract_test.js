'use strict';
/* CFG-04 — контракт мобильных форм: один save-сценарий, dirty-индикатор,
 * геометрия панели (safe-area/клавиатура), полный технический ключ, поворот.
 *
 * Источник: plans/features/cfg/source-cfg-addendum.md L149/L153/L157–L161;
 * карта CFG-04 (B.1/B.2/B.3/B.4/C.3/A.1). Подготовка: prep-cfg-04.md (Ф2).
 *
 * Запуск: node tests/js/cfg04_forms_contract_test.js   (CFG04-FORMS-OK)
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

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

const styleSet = {};
const clipboardWrites = [];
let scroller = { scrollTop: 120, scrollHeight: 1600, clientHeight: 600 };
let focusNode = null;
let queryMap = {};

global.window = {
  location: { hash: '#/memory/rag' },
  innerWidth: 390,
  innerHeight: 844,
  addEventListener() {},
  Telegram: null,
  visualViewport: { height: 844, offsetTop: 0, addEventListener() {} },
};
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  querySelector(sel) {
    if (Object.prototype.hasOwnProperty.call(queryMap, sel)) return queryMap[sel];
    if (sel === '.scroll-area') return scroller;
    return null;
  },
  documentElement: { style: { setProperty(k, v) { styleSet[k] = v; } } },
  activeElement: null,
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: {
    clipboard: {
      writeText: async function (t) { clipboardWrites.push(t); },
    },
  },
});
global.requestAnimationFrame = function (fn) { fn(); };
global.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;
const components = global.__components || {};

const INDEX = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'static', 'app.css'), 'utf8');

function mountComp(name, root, extra) {
  const comp = components[name];
  assert(comp, 'компонент ' + name + ' зарегистрирован');
  const vm = Object.assign({ root: root },
    (typeof comp.data === 'function' ? comp.data.call({}) : {}), extra || {});
  Object.keys(comp.computed || {}).forEach(function (k) {
    Object.defineProperty(vm, k, { get: comp.computed[k].bind(vm) });
  });
  Object.keys(comp.methods || {}).forEach(function (k) {
    vm[k] = comp.methods[k].bind(vm);
  });
  return vm;
}

(async function main() {
  // ── 1. B.1: чип шапки — индикатор, не второе сохранение ─────────────────
  {
    const chip = computed.headerSaveChip;
    assert.ok(chip, 'computed headerSaveChip определён');
    const clean = chip.call({ saveState: 'clean', stickyDirtyCount: 0, stickyFailed: [] });
    assert.strictEqual(clean.visible, false, 'B.1: clean → индикатора нет');
    const dirty = chip.call({ saveState: 'dirty', stickyDirtyCount: 3, stickyFailed: [] });
    assert.strictEqual(dirty.visible, true);
    assert.strictEqual(dirty.count, 3, 'B.1: счётчик изменённых полей');
    assert.strictEqual(dirty.actionable, false, 'B.1: dirty-индикатор не CTA');
    assert.ok(!/Сохранить/.test(dirty.label),
      'B.1: индикатор не подписан действием «Сохранить» (label=' + dirty.label + ')');
    assert.ok(/не сохранено/i.test(dirty.label));
    assert.ok(/3/.test(dirty.title || ''), 'B.1: title несёт счётчик');

    const panel = components['sticky-save'];
    assert.ok(panel, 'sticky-save зарегистрирован');
    assert.ok(panel.template.indexOf('save') >= 0);
    assert.strictEqual((panel.template.match(/@click="save"/g) || []).length, 1,
      'B.1: одно основное действие сохранения');
    assert.strictEqual((INDEX.match(/@click="saveModalEdits\(\)"/g) || []).length, 0,
      'B.1: в разметке страницы нет второго save-вызова');
  }

  // ── 2. B.2/B.3: фактическая высота панели → --sticky-save-h ─────────────
  {
    const panel = components['sticky-save'];
    assert.strictEqual(typeof panel.methods._syncPanelHeight, 'function',
      'B.3: _syncPanelHeight есть');
    const vm = mountComp('sticky-save', { stickyDirtyCount: 1, saveState: 'dirty' },
      { $el: { nodeType: 1, getBoundingClientRect: function () { return { height: 96.4 }; } } });
    vm._syncPanelHeight();
    assert.strictEqual(styleSet['--sticky-save-h'], '97px',
      'B.3: измеренная высота панели пишется в токен');
    // clean → панели нет → запас 0.
    const hidden = mountComp('sticky-save', { stickyDirtyCount: 0, saveState: 'clean' },
      { $el: null });
    hidden._syncPanelHeight();
    assert.strictEqual(styleSet['--sticky-save-h'], '0px',
      'B.3: clean → scroll-запас не резервируется');
    // CSS: fallback-токен и формула safe-area один раз.
    assert.ok(/--sticky-save-h:\s*4\.5rem/.test(CSS), 'B.3: fallback-токен');
    const sticky = CSS.match(/\.sticky-save\s*\{([^}]*)\}/);
    assert.ok(sticky, 'B.2: правило .sticky-save');
    assert.strictEqual((sticky[1].match(/env\(safe-area-inset-bottom/g) || []).length,
      1, 'B.2/§64 D3: safe-area ровно один раз');
    assert.ok(/max\(\s*env\(safe-area-inset-bottom[^)]*\)\s*,\s*var\(--tg-safe-area-inset-bottom/
      .test(sticky[1].replace(/\s+/g, ' ')), 'B.2: max(env, --tg-safe, --tg-content-safe)');
    assert.ok(/var\(--tg-content-safe-area-inset-bottom/.test(sticky[1]),
      'B.2: content-safe-area учтён');
    assert.ok(/bottom:\s*var\(--kb-offset/.test(sticky[1]),
      'B.2: клавиатура двигает геометрию панели');
  }

  // ── 3. C.3: полный технический ключ (раскрытие + копирование) ────────────
  {
    const tk = components['tech-key'];
    assert.ok(tk, 'tech-key зарегистрирован');
    assert.ok(tk.template.indexOf(':title="value"') >= 0,
      'C.3: полное значение в title (hover/скринридер)');
    assert.ok(/aria-expanded/.test(tk.template), 'C.3: раскрытие доступно');
    assert.ok(/показать/.test(tk.template),
      'C.3: affordance раскрытия полного ключа');
    const vm = mountComp('tech-key', {}, { value: 'limits.chat_burst_limit' });
    assert.strictEqual(vm.open, false);
    vm.toggle();
    assert.strictEqual(vm.open, true, 'C.3: клик раскрывает полный ключ');
    await vm.copy();
    assert.deepStrictEqual(clipboardWrites, ['limits.chat_burst_limit'],
      'C.3: копирование кладёт ПОЛНЫЙ ключ в clipboard');
    assert.strictEqual(vm.copied, true, 'C.3: обратная связь «Скопировано»');
  }

  // ── 4. A.1: поворот сохраняет скролл и активное поле ────────────────────
  {
    const node = {
      getAttribute: function (k) { return k === 'data-cfg-key' ? 'limits.x' : null; },
      focus: function () { focusNode = this; },
      setSelectionRange: function () {},
      selectionStart: 2, selectionEnd: 4,
    };
    global.document.activeElement = node;
    const snap = methods._captureEditViewport.call({});
    assert.strictEqual(snap.scrollTop, 120, 'A.1: скролл снят');
    assert.strictEqual(snap.key, 'limits.x', 'A.1: ключ поля снят');
    // DOM пересоздан: активного поля нет, скролл сброшен.
    scroller = { scrollTop: 0, scrollHeight: 1600, clientHeight: 600 };
    global.document.activeElement = null;
    const restored = {
      getAttribute: function () { return 'limits.x'; },
      focus: function () { focusNode = this; },
      setSelectionRange: function () {},
    };
    queryMap['[data-cfg-key="limits.x"]'] = restored;
    methods._restoreEditViewport.call({ $nextTick: function (f) { f(); } }, snap);
    assert.strictEqual(scroller.scrollTop, 120, 'A.1: скролл восстановлен');
    assert.strictEqual(focusNode, restored, 'A.1: фокус возвращён в то же поле');
    // Мутатор (смена shell-ветки) обёрнут: состояние сохраняется вокруг него.
    let mutated = false;
    methods._preserveEditViewport.call(
      { _captureEditViewport: methods._captureEditViewport,
        _restoreEditViewport: function (s) { this._snap = s; },
        $nextTick: function (f) { f(); } },
      function () { mutated = true; });
    assert.ok(mutated, 'A.1: мутатор выполнен внутри preserve');
  }

  // ── 5. B.4: dirty/save — без фальшивого успеха (регресс) ────────────────
  {
    const ctx = {
      configSnapshot: { 'limits.x': '1' },
      configItems: [
        { key: 'limits.x', value: 1, title: 'X' },
        { key: 'limits.y', value: 'b', title: 'Y' },
      ],
      keyDrafts: {}, stickySaving: false,
      canEditConfig() { return true; },
      _serializeValue(v) { return JSON.stringify(v); },
      _serializeConfigValue: function (v) { return JSON.stringify(v); },
      _findConfigItem(k) { return this.configItems.find(function (i) { return i.key === k; }); },
      toast() {},
      _opSeq: 0,
    };
    const dirty = computed.dirtyItems.call(ctx);
    assert.strictEqual(dirty.length, 0, 'B.4: baseline = исходные значения → clean');
    ctx.configItems[0].value = 2;
    assert.strictEqual(computed.dirtyItems.call(ctx).length, 1, 'B.4: изменение → dirty');
    ctx.configItems[0].value = 1;
    assert.strictEqual(computed.dirtyItems.call(ctx).length, 0,
      'B.4: возврат к исходному снимает dirty');
    ctx.dirtyItems = computed.dirtyItems.call(ctx);
    ctx.dirtyKeyItems = [];
    assert.strictEqual(computed.stickyDirtyCount.call(ctx), 0);
  }

  // ── 6. Guard: панель — единственное сохранение, шапка не переделана ─────
  {
    assert.ok(INDEX.indexOf('role="status"') >= 0, 'B.1: индикатор — статус');
    assert.ok(INDEX.indexOf('data-save-indicator') >= 0);
    assert.ok(INDEX.indexOf('<div v-if="headerSaveChip.visible"') >= 0,
      'B.1: индикатор рендерится только при непустом состоянии');
    assert.ok(INDEX.indexOf('mobile-topnav') >= 0, 'CFG-04.F: навигация не тронута');
    assert.ok(INDEX.indexOf('toggleFullscreen()') >= 0, 'ADD-1.C5: fullscreen цел');
  }

  console.log('CFG04-FORMS-OK');
  process.exit(0);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
