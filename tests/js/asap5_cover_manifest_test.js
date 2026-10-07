'use strict';
/* ASAP 5 web-slice (T-5252/T-5253, D7/D17) — JS unit-тест блока
 * «Что отправилось модели» в карточке обложки (реальная логика web/app.js +
 * разметка web/index.html).
 *
 * Проверяет:
 *  (1) coverManifestVisible — fail-closed: нет манифеста/компонент → блок
 *      скрыт (не «пустая таблица»);
 *  (a) RU-подписи 6 компонент манифеста (source) + честные статусы
 *      kept/compacted/omitted;
 *  (b) attempts[]: попытка/chars/outcome/reason/hash;
 *  (c) поллер сохраняет prompt_manifest из job-snapshot (админ-ветка);
 *  (d) разметка index.html: admin-only гейт + таблица компонент + hash,
 *      R17-гигиена блока (нет ключей/секретов).
 *
 * Запуск: node tests/js/asap5_cover_manifest_test.js
 *          → ASAP5-COVER-MANIFEST-OK
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

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
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

const APP_SRC = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;

// Fixture — shape ответа сервера: manifest_public(include_prompt=True)
// (админ-авторизованный читатель job_manifest).
const MANIFEST = {
  schema: 'cover_prompt_manifest/1',
  operation: 'edit',
  components: [
    { key: 'RUNTIME_INVARIANTS', source: 'code', priority: 'P0',
      original_text: 'x', original_chars: 100, sent_text: 'x',
      sent_chars: 100, status: 'kept', reason: '' },
    { key: 'STYLE_PROFILE', source: 'style_profile', priority: 'P1',
      original_text: 'y', original_chars: 80, sent_text: 'y',
      sent_chars: 80, status: 'kept', reason: '' },
    { key: 'BASE_STYLE', source: 'settings', priority: 'P1',
      original_text: 'z', original_chars: 30, sent_text: 'z',
      sent_chars: 30, status: 'kept', reason: '' },
    { key: 'REFERENCES', source: 'style_profile', priority: 'P2',
      original_text: '', original_chars: 0, sent_text: '',
      sent_chars: 0, status: 'omitted', reason: 'empty' },
    { key: 'STORY_SCENE', source: 'summary_stage1', priority: 'P2',
      original_text: 's', original_chars: 640, sent_text: 's',
      sent_chars: 420, status: 'compacted', reason: 'story_minimum' },
    { key: 'SUMMARY_CONTEXT', source: 'final_summary', priority: 'P2',
      original_text: 'c', original_chars: 900, sent_text: '',
      sent_chars: 0, status: 'omitted', reason: 'squeezed' },
  ],
  provider: 'nano-gpt.com', model: 'seedream-4', route: 'style_edit',
  resolved_limit: 1000, limit_unit: 'chars',
  limit_source: 'capability_registry',
  attempts: [
    { attempt: 1, prompt: 'старая строка', chars: 500,
      prompt_hash: 'aaaa1111', outcome: 'retry_superseded',
      reason: 'prompt_limit' },
    { attempt: 2, prompt: 'итоговая строка', chars: 708,
      prompt_hash: 'bbbb2222', outcome: 'sent', reason: '' },
  ],
  final_prompt: 'итоговая строка',
  final_chars: 708,
  prompt_hash: 'bbbb2222',
};

// (1) fail-closed: нет данных — блок скрыт.
assert.strictEqual(typeof methods.coverManifestVisible, 'function',
  '1: coverManifestVisible существует');
assert.strictEqual(methods.coverManifestVisible(null), false,
  '1: null → скрыт');
assert.strictEqual(methods.coverManifestVisible(undefined), false,
  '1: undefined → скрыт');
assert.strictEqual(methods.coverManifestVisible({}), false,
  '1: пустой манифест → скрыт');
assert.strictEqual(methods.coverManifestVisible({ components: [] }), false,
  '1: без компонент → скрыт (не «пусто»)');
assert.strictEqual(methods.coverManifestVisible(MANIFEST), true,
  '1: валидный манифест → видим');

// (a) RU-подписи всех 6 компонент + честные статусы.
const six = ['RUNTIME_INVARIANTS', 'STYLE_PROFILE', 'BASE_STYLE',
  'REFERENCES', 'STORY_SCENE', 'SUMMARY_CONTEXT'];
six.forEach(function (k) {
  var row = MANIFEST.components.filter(function (c) { return c.key === k; })[0];
  var label = methods.coverManifestSourceLabel(row);
  assert.ok(label && label !== k && label !== '—',
    'a: RU-подпись для ' + k + ' (' + label + ')');
});
assert.strictEqual(methods.coverManifestStatusText(
  { status: 'kept' }), 'отправлено полностью', 'a: kept');
assert.strictEqual(methods.coverManifestStatusText(
  { status: 'compacted' }), 'сжато при сборке', 'a: compacted');
assert.strictEqual(methods.coverManifestStatusText(
  { status: 'omitted' }), 'не отправлено', 'a: omitted');
assert.strictEqual(methods.coverManifestStatusClass({ status: 'kept' }),
  'text-green-400', 'a: kept — зелёный');
assert.ok(methods.coverManifestStatusClass({ status: 'compacted' })
  .indexOf('amber') >= 0, 'a: compacted — жёлтый');

// (b) attempts[]: попытка/chars/outcome/reason/hash.
var att1 = methods.coverManifestAttemptLabel(MANIFEST.attempts[0]);
assert.ok(att1.indexOf('Попытка 1') === 0, 'b: номер попытки');
assert.ok(att1.indexOf('500') >= 0, 'b: chars');
assert.ok(att1.indexOf('заменён повторной попыткой') >= 0,
  'b: честный retry-исход');
assert.ok(att1.indexOf('prompt_limit') >= 0, 'b: reason');
assert.ok(att1.indexOf('aaaa1111') >= 0, 'b: hash попытки');
var att2 = methods.coverManifestAttemptLabel(MANIFEST.attempts[1]);
assert.ok(att2.indexOf('отправлен провайдеру') >= 0, 'b: sent-исход');

// (c) поллер сохраняет prompt_manifest из job-snapshot (обе ветки:
// completed и failed — манифест виден и у провала).
assert.ok((APP_SRC.match(/prompt_manifest: snap\.prompt_manifest \|\| null/g)
  || []).length >= 2, 'c: поллер читает манифест в completed и failed');

// (d) разметка index.html: admin-only + таблица + hash, R17-гигиена.
const html = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf-8');
assert.ok(html.includes('data-cover-manifest'),
  'd: блок манифеста в карточке обложки');
assert.ok(html.includes('Что отправилось модели'),
  'd: подпись блока');
var mStart = html.indexOf('data-cover-manifest');
var mEnd = html.indexOf('data-cover-manifest-limit');
assert.ok(mStart > 0 && mEnd > mStart, 'd: блок ограничен');
// гейт v-if стоит в <details> ДО атрибута data-cover-manifest —
// проверяем от начала карточки результата.
var block = html.slice(html.indexOf('data-cover-test-result'), mEnd + 200);
assert.ok(block.indexOf('coverStyles.isAdmin') >= 0,
  'd: admin-only гейт в разметке');
assert.ok(block.indexOf('data-cover-manifest-table') >= 0
  && block.indexOf('data-cover-manifest-row') >= 0,
  'd: таблица 6 компонент рендерится');
assert.ok(block.indexOf('data-cover-manifest-attempt') >= 0,
  'd: attempts[] рендерятся');
assert.ok(block.indexOf('prompt_hash') >= 0, 'd: hash виден');
assert.ok(block.indexOf('coverManifestVisible(') >= 0,
  'd: fail-closed v-if');
['api_key', 'apiKey', 'secret', 'token', 'password'].forEach(function (bad) {
  assert.ok(!block.toLowerCase().includes(bad),
    'd: R17 — нет ключей/секретов в блоке манифеста');
});

console.log('ASAP5-COVER-MANIFEST-OK');
