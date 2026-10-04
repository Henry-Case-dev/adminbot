'use strict';
/* ASAP 4.3 (T-4842…T-4854) — MiniApp-контракт хирургического corrective pass
 * (реальные web/index.html / web/app.js / app.css):
 *   (a) durable Test Style job: polling, no double paid job, no file picker;
 *   (b) honest errors: сетевой обрыв — человеческая фраза, не «Failed to fetch»;
 *   (c) before/after только из valid-пары, иначе placeholders;
 *   (d) prompt budget/лимит: счётчики + manual override;
 *   (e) mobile layout: header/body/footer контракт, SaveBar wrap, без bottom-Npx.
 *
 * Запуск: node tests/js/asap43_cover_style_surgical_test.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
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
assert(captured, 'Vue.createApp вызван');
const methods = captured.methods;

// (a) durable job: start + polling, без оплаты вторым тапом и без file picker
{
  const src = methods.coverStylePreview.toString();
  assert.ok(src.indexOf('/api/cover/test-style') >= 0, 'a: start endpoint');
  assert.ok(/job_id/.test(src), 'a: хранит job_id');
  assert.ok(src.indexOf('coverStylePollJob') >= 0, 'a: polling после start');
  assert.ok(src.indexOf('coverStyleJobActive') >= 0, 'a: double-tap guard');
  assert.ok(src.indexOf('fileToBase64') < 0, 'a: не читает файл');
  assert.ok(!/\.files/.test(src), 'a: не читает ev.target.files');
  assert.ok(src.indexOf('content_base64') < 0, 'a: не шлёт upload base64');
  const poll = methods.coverStylePollJob.toString();
  assert.ok(poll.indexOf('/api/cover/test-style/') >= 0, 'a: status-read');
  assert.ok(poll.indexOf('coverAssetBlob') < 0, 'a: polling не качает произвольные ассеты');
  assert.ok(poll.indexOf('setTimeout') >= 0, 'a: расписание следующего чтения');
  const active = methods.coverStyleJobActive.toString();
  assert.ok(active.indexOf('finished') >= 0, 'a: active = не finished');
  // stage-тексты (§11)
  const stages = methods.coverPreviewStageText.toString();
  for (const t of ['Генерируем базовую обложку', 'Применяем стиль',
    'Сохраняем результат']) {
    assert.ok(stages.indexOf(t) >= 0, 'a: ' + t);
  }
  assert.ok(INDEX.indexOf('data-cover-test-progress') >= 0, 'a: progress DOM');
  assert.ok(INDEX.indexOf('data-cover-test-stage') >= 0, 'a: stage DOM');
  // закрытие/возврат восстанавливает job state (не сбрасываем previewJob)
  const close = methods.coverStyleEditorClose.toString();
  assert.ok(close.indexOf('previewJob = null') < 0,
    'a: close НЕ теряет job state');
  const open = methods.coverStyleOpen.toString();
  assert.ok(open.indexOf('coverStylePollJob') >= 0,
    'a: возврат в редактор возобновляет polling');
}

// (b) honest errors: network-обрыв — типизированный, не Failed to fetch
{
  assert.ok(APP.indexOf("throw new ApiError(0, 'network')") >= 0,
    'b: fetch rejection → ApiError(0, network)');
  const lost = methods.coverPreviewConnectionLost.toString();
  assert.ok(lost.indexOf('Потеряно соединение с сервером') >= 0, 'b: фраза');
  assert.ok(lost.indexOf('пробуем восстановить состояние') >= 0, 'b: retry');
  const poll = methods.coverStylePollJob.toString();
  // временный обрыв не является финалом: ошибка ведёт к повторному poll
  assert.ok(poll.indexOf('coverPreviewConnectionLost()') >= 0, 'b: human msg');
  assert.ok(poll.indexOf('coverStylePollJob') >= 0, 'b: reconnect-дочитывание');
  // system-level provider reason — только в developer details
  assert.ok(INDEX.indexOf('data-cover-developer-toggle') >= 0, 'b: details');
  assert.ok(INDEX.indexOf('data-cover-developer-reason') >= 0, 'b: details');
  assert.ok(methods.coverStylePollJob.toString().indexOf(
    'machine_reason') >= 0, 'b: developer_reason из machine_reason');
}

// (c) before/after только из valid-пары; иначе placeholders
{
  assert.ok(INDEX.indexOf("coverPairAsset(coverStyles.current, 'before')") >= 0,
    'c: editor before из pair');
  assert.ok(INDEX.indexOf("coverPairAsset(coverStyles.current, 'after')") >= 0,
    'c: editor after из pair');
  assert.ok(INDEX.indexOf("coverPairAsset(s, 'before')") >= 0, 'c: list before');
  assert.ok(INDEX.indexOf("coverPairAsset(s, 'after')") >= 0, 'c: list after');
  const pair = methods.coverPairAsset.toString();
  assert.ok(pair.indexOf('placeholder_') >= 0, 'c: fallback placeholder');
  assert.ok(pair.indexOf('preview_before_asset_id') >= 0, 'c: pair first');
  assert.ok(APP.indexOf('/api/cover/placeholders/') >= 0, 'c: placeholder URL');
  assert.ok(INDEX.indexOf('data-cover-mini-before') >= 0, 'c: mini before');
  assert.ok(INDEX.indexOf('data-cover-mini-after') >= 0, 'c: mini after');
  // compact-группа: одна горизонтальная группа, msr-стрелка
  assert.ok(INDEX.indexOf('cover-preview-group') >= 0, 'c: compact group');
  assert.ok(INDEX.indexOf("iconGlyph('chevron_right')") >= 0, 'c: msr arrow');
  assert.ok(/\.cover-preview-group\s*\{[^}]*flex-wrap:\s*nowrap/.test(CSS),
    'c: группа не разваливается');
  assert.ok(/@media \(max-width: 639\.98px\)[\s\S]*?\.cover-preview[^{]*\{[^}]*max-width:\s*6\.5rem/.test(CSS),
    'c: mobile preview масштабируется');
}

// (d) prompt budget/лимит: счётчики + manual override
{
  const budget = methods.coverBudgetText.toString();
  assert.ok(budget.indexOf('Инструкция:') >= 0, 'd: счётчик инструкции');
  assert.ok(budget.indexOf('Лимит текущей модели') >= 0, 'd: лимит модели');
  const limit = methods.coverLimitText.toString();
  assert.ok(limit.indexOf('неизвестно') >= 0, 'd: честный unknown');
  const breakdown = methods.coverPromptBreakdownText.toString();
  for (const key of ['Style', 'Context', 'Refs/meta', 'System', 'Итого']) {
    assert.ok(breakdown.indexOf(key) >= 0, 'd: ' + key);
  }
  assert.ok(APP.indexOf('Провайдер не сообщил точный лимит') >= 0,
    'd: unknown-текст §9');
  assert.ok(INDEX.indexOf('data-cover-prompt-limit') >= 0, 'd: поле лимита');
  assert.ok(INDEX.indexOf('data-cover-limit-mode') >= 0, 'd: auto/manual');
  assert.ok(INDEX.indexOf('data-cover-limit-unit') >= 0, 'd: единица');
  assert.ok(INDEX.indexOf('data-cover-limit-value') >= 0, 'd: значение');
  const saveLimit = methods.coverStyleSavePromptLimit.toString();
  assert.ok(saveLimit.indexOf('/api/cover/prompt-limit') >= 0, 'd: persistence');
  assert.ok(saveLimit.indexOf("'manual'") >= 0, 'd: manual mode');
}

// (e) mobile layout: structural contract, без blind bottom-Npx
{
  assert.ok(INDEX.indexOf('class="cover-editor-head') >= 0, 'e: editor head');
  assert.ok(INDEX.indexOf('class="cover-editor-body') >= 0, 'e: editor body');
  assert.ok(INDEX.indexOf('class="cover-editor-foot') >= 0, 'e: editor foot');
  assert.ok(/\.cover-editor-body\s*\{[^}]*min-height:\s*0/.test(CSS),
    'e: body — единственный скроллер');
  assert.ok(/\.cover-editor-head\s*\{[^}]*flex:\s*0 0 auto/.test(CSS),
    'e: head не сжимается');
  assert.ok(/\.cover-editor-foot\s*\{[^}]*flex:\s*0 0 auto/.test(CSS),
    'e: footer всегда виден');
  assert.ok(/\.sticky-save\s*\{[^}]*flex-wrap:\s*wrap/.test(CSS),
    'e: SaveBar переносится, не обрезается');
  // no blind bottom-Npx patches in cover editor (structural contract only)
  const editorCss = CSS.slice(CSS.indexOf('.cover-editor {'),
    CSS.indexOf('.cover-menu'));
  assert.ok(!/bottom:\s*\d+px/.test(editorCss), 'e: без bottom:Npx костылей');
  assert.ok(INDEX.indexOf('data-cover-editor-footer') >= 0, 'e: footer DOM');
  assert.ok(INDEX.indexOf('data-cover-style-save') >= 0, 'e: save DOM');
  // more-sheet closed = unmount (регресс 4.2)
  assert.ok(INDEX.indexOf('<transition name="more-sheet">') >= 0,
    'e: more-sheet transition');
}

console.log('ASAP43-COVER-STYLE-SURGICAL-OK');
