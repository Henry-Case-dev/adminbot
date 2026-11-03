'use strict';
/* EVOL-COG-MAP (W7-S3, review-B2) — фокус после окна записи, открытого ИЗ карточки.
 *
 * TEST-LIFECYCLE: REGRESSION owner=EVOL-COG-MAP (W7-S3)
 * Контракт: `plans/current_task.md:79` (EVOL-003) — «корректный focus trap,
 * возврат фокуса на исходную строку»; карточка узла здесь играет роль
 * исходной строки: «Открыть источник» — та кнопка, из которой открыто окно.
 *
 * Поведение: настоящий код `web/app.js` (methods берутся из `Vue.createApp`)
 * прогоняется на поддельном DOM, который, как браузер, уводит фокус на BODY,
 * когда сфокусированный узел закрытого окна исчезает из документа.
 *   карточка → «Открыть источник» → Esc      → фокус на кнопке «Открыть источник»;
 *                                     крестик  → там же;
 *                                     Back     → там же.
 * Карточка при этом остаётся открытой и показывает ту же запись.
 *
 * Мутация (возврат дефекта — `cogCardAction(act.id)` без `$event`) краснит
 * проверку: `statusRecordReturnFocus === null`, фокус остаётся в закрытом окне
 * и в браузере уходит на BODY.
 *
 * Запуск: node tests/js/evol_cog_map_card_focus_test.js → EVOL-COG-MAP-CARD-FOCUS-OK
 */
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

let checks = 0;
function ok(cond, message) {
  assert.ok(cond, message);
  checks += 1;
}
function eq(actual, expected, message) {
  assert.deepStrictEqual(actual, expected, message);
  checks += 1;
}

// ── поддельный DOM: `document.activeElement` ведёт себя как в браузере ─────
const body = {
  __name: 'body',
  tagName: 'BODY',
  focus() { doc.activeElement = body; },
  querySelectorAll() { return []; },
  classList: { add() {}, remove() {} },
};

function makeEl(name, tag) {
  const el = {
    __name: name,
    tagName: tag || 'BUTTON',
    disabled: false,
    offsetParent: {},          // видимый узел (иначе drawer-проверки его пропустят)
    focus() { doc.activeElement = el; },
    querySelectorAll() { return []; },
  };
  return el;
}

const modalRoot = makeEl('record-dialog', 'DIV');
const modalFirst = makeEl('record-close');
const sourceBtn = makeEl('cog-action-source');
const cardRoot = makeEl('cog-card', 'DIV');
modalRoot.querySelectorAll = function () { return [modalFirst]; };
cardRoot.querySelectorAll = function () { return [sourceBtn]; };

const doc = {
  activeElement: body,
  addEventListener() {}, getElementById() { return null; },
  createElement() {
    return { style: {}, setAttribute() {}, focus() {},
             select() {}, remove() {}, classList: { add() {}, remove() {} } };
  },
  body: body,
  execCommand() { return true; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = { location: { hash: '' }, addEventListener() {},
                  Telegram: null, document: doc };
global.document = doc;
Object.defineProperty(global, 'navigator', {
  value: { clipboard: { writeText: async function () {} } },
  configurable: true,
});
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;

// ── экземпляр: настоящие методы + минимальное состояние ────────────────────
function makeVm() {
  const vm = Object.assign({}, methods);
  vm.accessChats = [];
  vm.activeChatId = null;
  vm.statusRecord = null;
  vm.statusRecordExtra = null;
  vm.statusRecordExtraBusy = false;
  vm.toastLog = [];
  vm.toast = function (msg) { vm.toastLog.push(msg); };
  vm.api = async function () { throw new Error('сеть в тесте запрещена'); };
  vm.statusRecordDrill = function () {};     // drill — отдельный контракт
  vm.navigateTo = function () {};
  vm.$refs = { statusRecordDialog: modalRoot };
  vm.$nextTick = function (fn) { fn(); };    // как Vue: после текущего кадра
  vm.cogCard = {
    kind: 'node',
    id: 'fact:-1001:11',
    title: 'Аня любит утренний кофе',
    text: 'Аня любит утренний кофе',
    status: 'confirmed',
    scope: 'чат -1001',
    times: [],
    provenance: { origin: 'chat_history', messageId: 555 },
    actions: [
      { id: 'source', label: 'Открыть источник', enabled: true,
        target: { source: 'fact', factId: 11, chatId: -1001, messageId: 555 } },
      { id: 'history', label: 'История изменений', enabled: false,
        reason: 'версий не записано' },
    ],
  };
  Object.defineProperty(vm, 'statusRecordOpen', {
    get() { return this.statusRecord != null; },
  });
  Object.defineProperty(vm, 'cogCardOpen', {
    get() { return this.cogCard != null; },
  });
  return vm;
}

// Браузер убирает закрытое окно из документа: фокус, стоявший в нём, падает
// на BODY. Именно это и есть наблюдаемый дефект «фокус на BODY».
function settleRemovedNodes() {
  const act = doc.activeElement;
  if (act && (act === modalRoot || act === modalFirst)) doc.activeElement = body;
}

function open_source(vm) {
  doc.activeElement = body;
  // Vue передаёт в обработчик РОДНОЕ событие клика: `currentTarget` — кнопка.
  vm.cogCardAction('source', { type: 'click', currentTarget: sourceBtn });
  ok(vm.statusRecordOpen === true, 'окно записи не открылось из карточки');
  eq(vm.statusRecordReturnFocus, sourceBtn,
     'инициатор окна не запомнен: фокус некуда возвращать (в браузере — BODY)');
  eq(doc.activeElement, modalFirst,
     'первичный фокус окна не внутри окна — проверка Esc была бы не о том');
}

function assert_focus_back(vm, how) {
  settleRemovedNodes();
  ok(doc.activeElement === sourceBtn,
     'после ' + how + ' фокус не на кнопке «Открыть источник» (сейчас '
     + (doc.activeElement && doc.activeElement.__name) + ') — в браузере BODY');
  ok(vm.statusRecord === null, 'после ' + how + ' окно записи не закрыто');
  ok(vm.cogCard != null, 'после ' + how + ' закрылась и карточка (два слоя)');
  eq(vm.cogCard.id, 'fact:-1001:11', 'карточка после ' + how + ' — другая запись');
}

// (1) Esc в окне записи.
{
  const vm = makeVm();
  open_source(vm);
  eq(vm.statusRecord.id, 11, 'окно записи открыто не про ту запись');
  eq(vm.statusRecord.tg_message_id, 555, 'окно записи открыто не про то сообщение');
  let prevented = false;
  let stopped = false;
  vm.statusRecordKeydown({
    key: 'Escape',
    preventDefault() { prevented = true; },
    stopPropagation() { stopped = true; },
    currentTarget: modalRoot,
  });
  ok(prevented, 'Esc в окне записи не отменяет стандартное поведение');
  ok(stopped, 'Esc всплывает до глобального обработчика (два слоя за Esc)');
  assert_focus_back(vm, 'Esc');
}

// (2) Крестик окна записи (`closeStatusRecord` — та же кнопка разметки).
{
  const vm = makeVm();
  open_source(vm);
  vm.closeStatusRecord();
  assert_focus_back(vm, 'крестика');
}

// (3) Back: `goBack()` → общий back-стек → закрыватель окна записи.
{
  const vm = makeVm();
  vm.route = 'status';
  open_source(vm);
  vm.goBack();
  assert_focus_back(vm, 'Back');
}

// (4) Повторное открытие: тот же инициатор запоминается заново, а не протухает.
{
  const vm = makeVm();
  open_source(vm);
  vm.closeStatusRecord();
  assert_focus_back(vm, 'первого закрытия');
  vm.cogCardAction('source', { type: 'click', currentTarget: sourceBtn });
  eq(vm.statusRecordReturnFocus, sourceBtn,
     'повторное открытие источника потеряло инициатора');
  vm.closeStatusRecord();
  assert_focus_back(vm, 'повторного закрытия');
}

// (5) Неработающее действие не открывает окно и не подменяет инициатора.
{
  const vm = makeVm();
  vm.cogCardAction('history', { type: 'click', currentTarget: sourceBtn });
  ok(vm.statusRecord === null, 'недоступное действие открыло окно записи');
  eq(vm.statusRecordReturnFocus, undefined, 'инициатор записан без открытия окна');
  eq(vm.toastLog.length, 1, 'неработающее действие молчит о причине');
  eq(vm.toastLog[0], 'версий не записано', 'причина отказа не названа');
}

console.log('EVOL-COG-MAP-CARD-FOCUS-OK checks=' + checks);
