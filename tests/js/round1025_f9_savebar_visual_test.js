'use strict';
/* F9 round1025 (ADR-1025-22 D5/D6) — визуальный добор Sticky SaveBar.
 *
 * Покрытие (§69/§78):
 *   * клавиатура: `_syncKeyboardOffset` считает offset от visualViewport
 *     (`innerHeight − (vv.height + vv.offsetTop)`), пишет `--kb-offset` и
 *     докатывает активное поле модалки (`scrollIntoView block:'nearest'`);
 *   * safe-area РОВНО ОДИН РАЗ (§64 D3): `.modal-actions` не дублирует
 *     env(safe-area-inset-bottom); `.sticky-save` учитывает один раз;
 *   * последнее поле: `scroll-padding-bottom` + `.sticky-spacer` +
 *     `scroll-margin-bottom`;
 *   * SaveBar остаётся в `footer.modal-actions` ВНЕ `.modal-body`;
 *   * одно уведомление/«Подробнее» — reuse F0 (движок НЕ переписан);
 *   * состояния `saveState`/`stateLabel` (§51/§69) отображаются.
 *
 * Запуск: node tests/js/round1025_f9_savebar_visual_test.js  (F9-SAVEBAR-OK)
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
let scrolled = 0;
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  innerHeight: 800,
  visualViewport: { height: 400, offsetTop: 100, addEventListener() {} },
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  documentElement: { style: { setProperty(k, v) { styleSet[k] = v; } } },
  activeElement: {
    tagName: 'INPUT',
    closest(sel) { return /modal-body|scroll-area/.test(sel) ? {} : null; },
    scrollIntoView() { scrolled += 1; },
  },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;

const INDEX = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
const CSS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'static', 'app.css'), 'utf8');

(async function main() {
// ── 1. Клавиатура: keyboard-offset + scrollIntoView ─────────────────────────
{
  assert.strictEqual(typeof methods._syncKeyboardOffset, 'function',
    'D5: _syncKeyboardOffset — метод');
  methods._syncKeyboardOffset.call({});
  assert.strictEqual(styleSet['--kb-offset'], '300px',
    'D5: offset = innerHeight − (vv.height + vv.offsetTop) = 800−500');
  assert.ok(scrolled >= 1,
    'D5: активное поле модалки докатывается (scrollIntoView nearest)');
  assert.ok(/_syncKeyboardOffset/.test(APP_JS) &&
            /visualViewport/.test(APP_JS),
    'D5: _onVV связан с visualViewport');
  assert.ok(APP_JS.indexOf("addEventListener('scroll', _onVV)") >= 0,
    'D5: подписка на visualViewport scroll (iOS-клавиатура)');
  // Нет клавиатуры → offset 0.
  global.window.visualViewport = { height: 800, offsetTop: 0 };
  styleSet['--kb-offset'] = 'unset';
  methods._syncKeyboardOffset.call({});
  assert.strictEqual(styleSet['--kb-offset'], '0px',
    'D5: клавиатура закрыта → offset 0');
  global.window.visualViewport = { height: 400, offsetTop: 100 };
}

// ── 2. Safe-area РОВНО ОДИН РАЗ (§64 D3) ────────────────────────────────────
{
  const actions = CSS.match(/\.modal-actions\s*\{([^}]*)\}/);
  assert.ok(actions, 'D5: правило .modal-actions есть');
  assert.strictEqual(/env\(safe-area-inset-bottom/.test(actions[1]), false,
    'D5/§64: .modal-actions НЕ добавляет safe-area (нет двойного вычета)');
  const sticky = CSS.match(/\.sticky-save\s*\{([^}]*)\}/);
  assert.ok(sticky, 'D5: правило .sticky-save есть');
  const envCount = (sticky[1].match(/env\(safe-area-inset-bottom/g) || []).length;
  assert.strictEqual(envCount, 1,
    'D5/§64: .sticky-save учитывает safe-area ровно один раз');
  assert.ok(/\.modal-actions > \.sticky-save/.test(CSS) &&
            /position:\s*static/.test(
              CSS.match(/\.modal-footer > \.sticky-save,\s*\.modal-actions > \.sticky-save\s*\{([^}]*)\}/)[1]),
    'D5: в footer панель static (не overlay)');
}

// ── 3. Последнее поле: scroll-padding + spacer + scroll-margin ──────────────
{
  assert.ok(/\.modal-body\s*\{[^}]*scroll-padding-bottom/.test(CSS),
    'D5: .modal-body scroll-padding-bottom сохранён');
  const scrollArea = CSS.match(/\.scroll-area:has\(> \.sticky-save\)\s*\{([^}]*)\}/);
  assert.ok(scrollArea && /scroll-padding-bottom/.test(scrollArea[1]),
    'D5: .scroll-area:has(> .sticky-save) scroll-padding-bottom');
  assert.ok(/\.sticky-spacer\s*\{[^}]*height:\s*var\(--sticky-save-h\)/.test(CSS),
    'D5: .sticky-spacer резервирует место');
  assert.ok(/\.field,[\s\S]{0,80}scroll-margin-bottom/.test(CSS),
    'D5: scroll-margin-bottom на полях (последнее поле нажимаемо)');
  assert.ok(/--kb-offset\s*:/.test(CSS),
    'D5: токен --kb-offset определён');
  assert.ok(/padding-bottom:\s*calc\(1rem \+ var\(--kb-offset/.test(CSS),
    'D5: модалка поднимается над клавиатурой через --kb-offset');
}

// ── 4. SaveBar в footer.modal-actions ВНЕ .modal-body ───────────────────────
{
  const footerIdx = INDEX.indexOf('<footer class="modal-actions');
  assert.ok(footerIdx >= 0, 'D5: footer.modal-actions существует');
  const footerBlock = INDEX.slice(footerIdx, footerIdx + 300);
  assert.ok(footerBlock.indexOf('<sticky-save') >= 0,
    'D5: SaveBar внутри footer.modal-actions');
  // Ближайший закрывающий .modal-body — ДО footer (SaveBar вне скроллера).
  const before = INDEX.slice(0, footerIdx);
  const lastBodyOpen = before.lastIndexOf('<div class="modal-body">');
  const lastBodyClose = before.lastIndexOf('</div>', footerIdx);
  assert.ok(lastBodyOpen >= 0 && lastBodyClose > lastBodyOpen,
    'D5: footer стоит после закрытия .modal-body (вне скроллера)');
}

// ── 5. Одно уведомление + «Подробнее» — reuse F0 (движок не переписан) ──────
{
  assert.strictEqual(APP_JS.indexOf('persistItems: async function') >= 0, true,
    'D6: persistItems F0 на месте (движок не переписан)');
  assert.strictEqual((APP_JS.match(/persistItems: async function/g) || []).length,
    1, 'D6: единственный persistItems (нет дублей)');
  assert.ok(APP_JS.indexOf('notify: function (operationId') >= 0,
    'D6: notify F0 на месте');
  assert.ok(APP_JS.indexOf("_opNotified[operationId]") >= 0,
    'D6: дедуп уведомлений по operationId сохранён');
  assert.ok(INDEX.indexOf('class="toast-more"') >= 0,
    'D6: «Подробнее» в тосте (reuse F0)');
  assert.ok(/\.toast-text--long/.test(CSS) && /\.toast-more\s*\{/.test(CSS),
    'D6: длинная ошибка за «Подробнее» (CSS reuse)');
}

// ── 6. Состояния saveState/stateLabel (§51/§69) ─────────────────────────────
{
  assert.strictEqual(typeof computed.saveState, 'function',
    'D6: computed saveState F0');
  const comp = global.__components && global.__components['sticky-save'];
  assert.ok(comp, 'D6: sticky-save зарегистрирован');
  function mount(root) {
    const vm = { root: root };
    Object.keys(comp.computed).forEach(function (k) {
      Object.defineProperty(vm, k, { get: comp.computed[k].bind(vm) });
    });
    return vm;
  }
  assert.strictEqual(mount({ saveState: 'loading', stickyDirtyCount: 0 }).stateLabel,
    'Загрузка…', 'D6: loading отображается');
  assert.strictEqual(mount({ saveState: 'saving', stickyDirtyCount: 0 }).stateLabel,
    'Сохранение…', 'D6: saving отображается');
  // L-F9S-2: `saved` НЕ отдаёт root.saveState (после успеха → clean;
  // «Сохранено» доставляет тост F0) — мёртвая ветка убрана, подписи нет.
  assert.strictEqual(mount({ saveState: 'saved', stickyDirtyCount: 0 }).stateLabel,
    '', 'D6/L-F9S-2: недостижимый saved не подписывается');
  assert.strictEqual(mount({ saveState: 'clean', stickyDirtyCount: 0 }).stateLabel,
    '', 'D6: clean → без подписи');
  assert.strictEqual(mount({ saveState: 'conflict', stickyDirtyCount: 1 }).stateLabel,
    'Конфликт версии', 'D6: conflict — понятный текст');
  assert.strictEqual(mount({ saveState: 'dirty', stickyDirtyCount: 1 }).stateLabel,
    'Есть изменения', 'D6: dirty');
  assert.ok(comp.template.indexOf(':data-save-state="saveState"') >= 0,
    'D6: data-save-state привязан');
}

// ── 7. Серверная логика F0 не дублируется в F9 ──────────────────────────────
{
  // 409-обработка живёт в persistItems (F0), не в F9-компоненте.
  const persist = APP_JS.slice(APP_JS.indexOf('persistItems: async function'),
    APP_JS.indexOf('saveConfigItem: async function'));
  assert.ok(/status === 409/.test(persist),
    'D6: 409-обработка в persistItems (F0)');
  const comp = global.__components['secret-field'];
  assert.ok(comp && !/persistItems|api\(/.test(comp.template),
    'D6: secret-field — только UI (без серверной логики)');
  assert.ok(!/status === 409/.test(comp.template) &&
            !/412/.test(comp.template),
    'D6: F9-компонент не дублирует 409/412');
}

console.log('F9-SAVEBAR-OK');
process.exit(0);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
