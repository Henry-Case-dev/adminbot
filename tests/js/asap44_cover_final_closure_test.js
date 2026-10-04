'use strict';
/* ASAP 4.4 (T-4868…T-4872) — MiniApp-контракт «Следующий номер»/draft snapshot:
 *   (a) редактор работает с `next_issue_number` (= counter_value+1 на сервере),
 *       старый raw `counter_value` не используется как «следующий»;
 *   (b) Test Style отправляет текущий draft style-affecting полей, а retry
 *       шлёт тот же draft (не сохранённую версию);
 *   (c) Save отправляет `next_issue_number`, а не raw counter_value.
 *
 * Запуск: node tests/js/asap44_cover_final_closure_test.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
const _storage = {
  _s: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; }, localStorage: _storage,
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
  querySelector() { return null; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;

// (a) «Следующий номер» = next_issue_number, raw counter_value — нет
{
  assert.ok(INDEX.indexOf(
    'v-model="coverStyles.current.next_issue_number"') >= 0,
    'a: input «Следующий номер» привязан к next_issue_number');
  assert.ok(INDEX.indexOf(
    'v-model="coverStyles.current.counter_value"') < 0,
    'a: raw counter_value не используется как «Следующий номер»');
  assert.ok(methods.coverStyleOpen.toString().indexOf('next_issue_number') >= 0,
    'a: open редактора читает next_issue_number');
  const meta = methods.coverStyleLoadMeta.toString();
  assert.ok(meta.indexOf('next_issue_number') >= 0,
    'a: meta-sync обновляет next_issue_number');
}

// (b) Test Style: draft snapshot текущего редактора + retry тем же draft
{
  const src = methods.coverStylePreview.toString();
  assert.ok(src.indexOf('draft') >= 0, 'b: POST несёт draft');
  const draftSrc = methods.coverStyleDraftSnapshot.toString();
  for (const field of ['instruction', 'next_issue_number', 'model_mode',
    'counter_format', 'pipeline_mode']) {
    assert.ok(draftSrc.indexOf(field) >= 0, 'b: draft.' + field);
  }
  const retry = methods.coverStyleRetryStart.toString();
  assert.ok(retry.indexOf('draft') >= 0, 'b: retry шлёт тот же draft');
}

// (c) Save: next_issue_number (не raw counter_value)
{
  const save = methods.coverStyleSave.toString();
  assert.ok(save.indexOf('coverStyleNextNumber') >= 0,
    'c: Save отправляет next number через helper');
  assert.ok(save.indexOf('counter_value') < 0,
    'c: Save не отправляет raw counter_value');
  const next = methods.coverStyleNextNumber.toString();
  assert.ok(next.indexOf('next_issue_number') >= 0,
    'c: helper читает next_issue_number');
}

// (d) §2 T-4873/T-4874: лимит промпта — source taxonomy в UI; «задано
// вручную» показывается только из server state (без оптимистичного показа
// до подтверждения сервером, как было в 4.3 при заблокированном 422).
{
  const limit = methods.coverLimitText.toString();
  assert.ok(limit.indexOf('coverLimitSourceLabel') >= 0,
    'd: UI различает taxonomy источника лимита');
  assert.ok(limit.indexOf('pl.mode') >= 0,
    'd: manual-состояние берётся из server state (prompt_limit.mode)');
  assert.ok(limit.indexOf("st.limitMode === 'manual' && st.limitValue") < 0,
    'd: нет оптимистичного «задано вручную» до серверного успеха');
  const labelSrc = methods.coverLimitSourceLabel.toString();
  assert.ok(labelSrc.indexOf('source_taxonomy') >= 0,
    'd: taxonomy берётся из server field source_taxonomy');
  assert.ok(labelSrc.indexOf('learned_safe_ceiling') >= 0,
    'd: learned safe ceiling подписан отдельно (не exact max)');
  const unknown = methods.coverBudgetUnknownText.toString();
  assert.ok(unknown.indexOf("st.limitMode === 'manual' && st.limitValue") < 0,
    'd: unknown-подсказка не зависит от локального draft-состояния');
  const metaSrc = methods.coverStyleLoadMeta.toString();
  assert.ok(metaSrc.indexOf('effective') >= 0,
    'd: meta тянет effective provider/model/route');
  const capLines = methods.coverCapabilityLines.toString();
  assert.ok(capLines.indexOf('Модель обработки') >= 0,
    'd: editor показывает effective provider/model/route');
}

console.log('asap44 cover final closure JS: OK');
