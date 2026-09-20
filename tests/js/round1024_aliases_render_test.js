'use strict';
/* F10 round 10.24 (aliases-render-real-fix-round1024, ADR-1024-11) —
 * РЕАЛЬНЫЙ render-тест KV-редактора `limits.summary_aliases`.
 *
 * В отличие от 10.22 (`round1022_aliases_test.js` вызывал `sync()` вручную,
 * вне реактивного жизненного цикла), здесь `kv-editor` **реально монтируется**
 * через настоящий Vue-runtime (self-host full-сборка) на in-memory renderer
 * (без DOM/jsdom). Проверяем именно поведение binding:
 *   1) значение из ответа API отрисовывается СРАЗУ при монтировании (input-ы
 *      со значениями, без ручного вызова sync) — главный критерий приёмки;
 *   2) глубокая мутация `item.value` после монтирования → повторный sync
 *      (регресс shallow-бага: старый `watch:'item.value'` вложенное не видит);
 *   3) замена `item`-объекта → повторный sync;
 *   4) эмуляция reload: замена `configItems` + `configVersion++` (re-mount
 *      через :key) → новые значения в DOM;
 *   5) массив пар `[[k,v], …]` → пары;
 *   6) пусто/не-объект → Empty State, без исключений;
 *   7) индикатор источника: «значение чата» / «глобально»;
 *   8) kill-switch OFF → прежний (сломанный) watcher по пути;
 *   9) wiring: `:key` c configVersion, `root.iconGlyph` (регресс TypeError
 *      рендера при наличии пар), доставка флага через /api/me.ui_flags.
 *
 * Запуск: node tests/js/round1024_aliases_render_test.js → ALIASES-RENDER-OK
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
const BUNDLE = path.join(ROOT, 'web', 'static', 'vendor',
                         'vue.global.prod.min.js');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_SRC = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

// ── Реальный Vue-runtime (как в браузере) ───────────────────────────────────
global.window = global;
vm.runInThisContext(fs.readFileSync(BUNDLE, 'utf8'), { filename: BUNDLE });
assert.strictEqual(typeof Vue, 'object', 'Vue не загружен');
assert.strictEqual(typeof Vue.createRenderer, 'function',
                   'нужен createRenderer (полная сборка)');

// Перехватываем регистрацию компонентов, корень не монтируем (нет DOM).
const comps = {};
const realCreateApp = Vue.createApp.bind(Vue);
Vue.createApp = function (opts) {
  const app = realCreateApp(opts);
  const realComponent = app.component.bind(app);
  app.component = function (name, def) {
    if (name && def && typeof def === 'object') {
      comps[name] = def;
      return app;
    }
    return realComponent(name);
  };
  app.mount = function () { return {}; };
  return app;
};

// Минимальные браузерные заглушки (модуль app.js грузится целиком).
global.document = {
  addEventListener() {}, getElementById() { return null; },
  querySelector() { return null; },
  createElement() {
    return { style: {}, appendChild() {}, setAttribute() {},
             addEventListener() {}, remove() {} };
  },
  createElementNS() { return this.createElement(); },
  head: { appendChild() {} }, body: { appendChild() {}, removeChild() {} },
  documentElement: { style: {} }, execCommand() { return true; },
  activeElement: null,
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('x'); } } },
});
global.sessionStorage = {
  _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; },
};
global.localStorage = {
  _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.location = { hash: '', href: '', pathname: '/' };
global.Chart = function () {};
// vModelText.beforeUpdate делает `getRootNode() instanceof Document/ShadowRoot`
// (Vue 3.5) — нужны глобальные конструкторы (наши in-memory-узлы ими не являются).
global.Document = function Document() {};
global.ShadowRoot = function ShadowRoot() {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
const kvDef = comps['kv-editor'];
assert(kvDef, 'не найден компонент kv-editor');
assert(kvDef.watch && kvDef.watch.item &&
       kvDef.watch.item.deep === true &&
       kvDef.watch.item.immediate === true,
       'kv-editor.watch.item обязан быть {deep:true, immediate:true}');

// Шаблон kv-editor — из index.html; компилируем реальным Vue-компилятором.
const tplMatch = INDEX.match(
  /<script type="text\/x-template" id="kv-editor-tpl">([\s\S]*?)<\/script>/);
assert(tplMatch, 'не найден шаблон #kv-editor-tpl');
const KV = Object.assign({}, kvDef, { render: Vue.compile(tplMatch[1]) });

// ── Мини-рендерер (in-memory) ───────────────────────────────────────────────
function createNode(tag) {
  return {
    nodeType: 1, tagName: tag, parentNode: null, childNodes: [],
    props: {}, listeners: {}, value: '', textContent: '', style: {},
    setAttribute(k, v) { this.props[k] = v; },
    getAttribute(k) { return this.props[k]; },
    addEventListener(t, f) {
      (this.listeners[t] = this.listeners[t] || []).push(f);
    },
    removeEventListener() {},
    getRootNode() { return this; },
    contains() { return false; },
    remove() { removeNode(this); },
  };
}
function removeNode(el) {
  if (!el.parentNode) return;
  const arr = el.parentNode.childNodes;
  const i = arr.indexOf(el);
  if (i >= 0) arr.splice(i, 1);
  el.parentNode = null;
}
const nodeOps = {
  insert(el, parent, anchor) {
    // Как DOM.insertBefore: узел ПЕРЕМЕЩАЕТСЯ, а не дублируется.
    if (el.parentNode) removeNode(el);
    el.parentNode = parent;
    if (anchor == null) parent.childNodes.push(el);
    else {
      const i = parent.childNodes.indexOf(anchor);
      if (i < 0) parent.childNodes.push(el);
      else parent.childNodes.splice(i, 0, el);
    }
  },
  remove(el) { removeNode(el); },
  createElement(tag) { return createNode(tag); },
  createText(t) { return { nodeType: 3, text: t, parentNode: null }; },
  createComment(t) { return { nodeType: 8, text: t, parentNode: null }; },
  setText(n, t) { n.text = t; },
  setElementText(n, t) { n.textContent = t; n.childNodes = []; },
  parentNode(n) { return n.parentNode; },
  nextSibling(n) {
    const p = n.parentNode;
    if (!p) return null;
    const i = p.childNodes.indexOf(n);
    return i >= 0 ? (p.childNodes[i + 1] || null) : null;
  },
  patchProp(el, key, prev, next) {
    if (key === 'value') el.value = next;
    else el.props[key] = next;
  },
};
const renderer = Vue.createRenderer(nodeOps);

function findAll(node, tag, out) {
  out = out || [];
  if (node.nodeType === 1 && node.tagName === tag) out.push(node);
  (node.childNodes || []).forEach(function (c) { findAll(c, tag, out); });
  return out;
}
function collectText(node, out) {
  out = out || [];
  if (node.nodeType === 3 && node.text) out.push(node.text);
  if (node.nodeType === 1 && typeof node.textContent === 'string' &&
      node.textContent) {
    out.push(node.textContent);
  }
  (node.childNodes || []).forEach(function (c) { collectText(c, out); });
  return out;
}
function aliasesItem(value, extra) {
  return Object.assign({
    key: 'limits.summary_aliases', value: value, title: 'Словарь алиасов имён',
    chat_source: '', global_value: null,
  }, extra || {});
}
function mount(items, enabled) {
  const root = createNode('root');
  const Host = {
    data() { return { items: items, configVersion: 0 }; },
    render() {
      const self = this;
      return Vue.h('div', self.items.map(function (it) {
        return Vue.h(KV, {
          key: it.key + ':' + self.configVersion, item: it, canEdit: true,
        });
      }));
    },
  };
  const app = renderer.createApp(Host);
  app.provide('root', {
    uiFlag: function () { return enabled !== false; },
    saving: new Set(), toast() {}, api() {}, loadConfig() {},
    iconGlyph: function () { return '*'; },
  });
  const vmInst = app.mount(root);
  return { root: root, vm: vmInst };
}
function inputValues(root) {
  return findAll(root, 'input').map(function (i) { return i.value; });
}
const tick = function () { return Vue.nextTick(); };

async function main() {
  // 1. Значение из ответа API отрисовывается СРАЗУ при монтировании.
  const st = mount([aliasesItem(
    { '138811255': 'Леха', '350803143': 'Костик' })]);
  await tick();
  assert.deepStrictEqual(inputValues(st.root),
    ['138811255', 'Леха', '350803143', 'Костик'],
    'при монтировании должны быть input-ы со значениями (без sync())');

  // 2. Глубокая мутация item.value → повторный sync (deep-watch).
  // (Числоподобные ключи объекта JS упорядочивает по возрастанию: 99 идёт первым.)
  st.vm.items[0].value['99'] = 'Новый';
  await tick();
  assert.deepStrictEqual(inputValues(st.root),
    ['99', 'Новый', '138811255', 'Леха', '350803143', 'Костик'],
    'вложенная мутация должна ре-синкаться (deep-watch)');

  // 3. Замена item-объекта (тот же ключ/позиция) → повторный sync.
  st.vm.items[0] = aliasesItem({ '1': 'Иван', '2': 'Пётр' });
  await tick();
  assert.deepStrictEqual(inputValues(st.root), ['1', 'Иван', '2', 'Пётр'],
    'замена item-объекта должна ре-синкаться');

  // 4. reload: новый массив configItems + configVersion++ (re-mount через :key).
  st.vm.items = [aliasesItem({ '7': 'Семён' })];
  st.vm.configVersion++;
  await tick();
  assert.deepStrictEqual(inputValues(st.root), ['7', 'Семён'],
    'reload (:key/configVersion) должен показать новые значения');

  // 5. Массив пар [[k,v]] → пары.
  const stArr = mount([aliasesItem([['1', 'Иван'], ['2', 'Пётр']])]);
  await tick();
  assert.deepStrictEqual(inputValues(stArr.root), ['1', 'Иван', '2', 'Пётр'],
    'массив пар должен отрисоваться');

  // 6. Пусто/не-объект → Empty State, без исключений.
  const stEmpty = mount([aliasesItem({})]);
  const stBad = mount([aliasesItem('не json')]);
  await tick();
  assert.strictEqual(findAll(stEmpty.root, 'input').length, 0,
    'пустой объект → 0 input-ов');
  assert.strictEqual(findAll(stBad.root, 'input').length, 0,
    'не-JSON строка → 0 input-ов (без исключения)');
  assert(collectText(stEmpty.root).join(' ').indexOf('словарь пуст') >= 0,
    'должен быть понятный Empty State (не «сломано»)');

  // 7. Индикатор источника.
  const stChat = mount([aliasesItem({ '5': 'Петя' }, { chat_source: 'chat' })]);
  const stGlob = mount([aliasesItem({ '5': 'Петя' })]);
  await tick();
  assert(collectText(stChat.root).join(' ').indexOf('значение чата') >= 0,
    'per-chat override → бейдж «значение чата»');
  assert(collectText(stGlob.root).join(' ').indexOf('глобально') >= 0,
    'global → бейдж «глобально»');

  // 8. Kill-switch OFF → прежний (сломанный) watcher по пути.
  const stOff = mount([aliasesItem({ '1': 'A' })], false);
  await tick();
  assert.deepStrictEqual(inputValues(stOff.root), ['1', 'A'],
    'OFF: created()-sync всё равно даёт первичный рендер');
  stOff.vm.items[0].value['2'] = 'B';
  await tick();
  assert.deepStrictEqual(inputValues(stOff.root), ['1', 'A'],
    'OFF: deep-watch отключён (аварийное прежнее поведение)');
  stOff.vm.items[0].value = { '3': 'C' };
  await tick();
  assert.deepStrictEqual(inputValues(stOff.root), ['3', 'C'],
    'OFF: path-watcher по-прежнему работает');

  // 9. Wiring-маркеры (регрессы).
  assert(INDEX.indexOf(":key=\"item.key + ':' + configVersion\"") !== -1,
    'на <kv-editor> должен быть :key с configVersion (re-mount при reload)');
  assert(INDEX.indexOf("root.iconGlyph('delete')") !== -1,
    'kv-шаблон обязан звать root.iconGlyph (TypeError рендера при парах)');
  assert(!/\{\{\s*iconGlyph\s*\(/.test(tplMatch[1]),
    'в kv-шаблоне не должно остаться unqualified iconGlyph (падал рендер)');
  assert(APP_SRC.indexOf('configVersion++') !== -1,
    'loadConfig должен инкрементить configVersion');
  assert(APP_SRC.indexOf('ALIASES_KEYSVALUE_RENDER_ENABLED') !== -1,
    'kill-switch ALIASES_KEYSVALUE_RENDER_ENABLED должен читаться на фронте');

  console.log('ALIASES-RENDER-OK');
}

main().catch(function (err) {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
