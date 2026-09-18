'use strict';
/* F8 round1022 (dossier-rebuild-async-ui-round1022, ADR-1022-8) — РЕАЛЬНЫЙ
 * JS-тест фронта пересборки досье.
 *
 * Проверяет:
 *   - классификацию статусов job'а (активные/терминальные) и текст стадии;
 *   - POST /rebuild с выбранным периодом (default 180) и name;
 *   - 409 → подхват существующего job'а через GET latest;
 *   - POST cancel → статус cancelling + продолжение опроса;
 *   - polling: старт/стоп таймера;
 *   - localStorage-подсказку {chat_id, user_id, job_id}.
 *
 * Запуск: node tests/js/round1022_dossier_rebuild_test.js  (печатает
 * DOSSIER-REBUILD-UNIT-OK)
 */
const path = require('path');
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
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; },
};
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {}, remove() {},
    };
  },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
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
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured && captured.methods, 'Vue.createApp должен быть вызван');
const M = captured.methods;

function baseCtx(over) {
  const ctx = {
    activeChatId: -100, dossierUserId: 5, dossierName: 'Аня',
    dossierRebuildBusy: false, dossierRebuildJob: null,
    dossierRebuildPeriod: '180', dossierRebuildTimer: null,
    calls: [], toasts: [], pollStarts: 0,
    api: async function (url, opts) { this.calls.push({ url, opts }); return this.apiResult; },
    toast: function (msg) { this.toasts.push(msg); },
    startDossierRebuildPolling: function () { this.pollStarts += 1; },
    stopDossierRebuildPolling: function () {},
    loadDossier: async function () {},
    dossierRebuildIsActive: M.dossierRebuildIsActive,
    dossierRollbackRetryable: M.dossierRollbackRetryable,
    _rememberDossierRebuild: M._rememberDossierRebuild,
  };
  Object.keys(over || {}).forEach(function (k) { ctx[k] = over[k]; });
  return ctx;
}

(async function run() {
  // 1. Классификация статусов (S10.22-5: `interrupted` НЕ активен — новый
  // старт разрешён; откат при этом доступен через dossierRebuildCancelable).
  ['queued', 'running', 'cancelling'].forEach(function (s) {
    assert.strictEqual(M.dossierRebuildIsActive.call({}, { status: s }), true,
      'статус ' + s + ' должен считаться активным');
  });
  ['done', 'failed', 'cancelled', 'interrupted', '', null].forEach(function (s) {
    assert.strictEqual(M.dossierRebuildIsActive.call({}, { status: s }), false,
      'статус ' + String(s) + ' не активен');
  });
  assert.strictEqual(M.dossierRebuildIsActive.call({}, null), false);

  // 1b. Отмена/откат доступны и для `interrupted`.
  assert.strictEqual(M.dossierRebuildCancelable.call(
    { dossierRebuildIsActive: M.dossierRebuildIsActive },
    { status: 'interrupted' }), true, 'interrupted → откат доступен');
  assert.strictEqual(M.dossierRebuildCancelable.call(
    { dossierRebuildIsActive: M.dossierRebuildIsActive },
    { status: 'running' }), true, 'running → отмена доступна');
  assert.strictEqual(M.dossierRebuildCancelable.call(
    { dossierRebuildIsActive: M.dossierRebuildIsActive },
    { status: 'done' }), false, 'done → отмены нет');

  // 2. Тексты стадий.
  assert.strictEqual(M.dossierRebuildStageText.call({}, { stage: 'extract' }),
    'Извлечение фактов');
  assert.strictEqual(M.dossierRebuildStageText.call({}, { stage: 'rollback' }),
    'Откат изменений');
  assert.strictEqual(M.dossierRebuildStageText.call({}, { stage: 'nope' }),
    'Выполняется');

  // 3. Старт: POST с периодом/именем, прогресс, polling, localStorage.
  let ctx = baseCtx({
    apiResult: { job_id: 'j1', status: 'queued', total: 9, processed: 0 },
  });
  global.localStorage._s = {};
  await M.startDossierRebuild.call(ctx);
  assert.strictEqual(ctx.calls.length, 1, 'должен быть один POST');
  assert.ok(ctx.calls[0].url.indexOf('/chat_lore/-100/dossier/5/rebuild') >= 0,
    'URL старта пересборки');
  assert.ok(ctx.calls[0].url.indexOf('name=') >= 0, 'name в query');
  assert.deepStrictEqual(JSON.parse(ctx.calls[0].opts.body), { period: '180' });
  assert.strictEqual(ctx.dossierRebuildJob.job_id, 'j1');
  assert.strictEqual(ctx.pollStarts, 1, 'polling запущен');
  const saved = JSON.parse(global.localStorage._s['adminbot.dossier_rebuild']);
  assert.strictEqual(saved.job_id, 'j1');
  assert.strictEqual(saved.user_id, 5);

  // 3b. Период «30» прокидывается как есть.
  ctx = baseCtx({ dossierRebuildPeriod: '30', apiResult: { job_id: 'j2' } });
  await M.startDossierRebuild.call(ctx);
  assert.deepStrictEqual(JSON.parse(ctx.calls[0].opts.body), { period: '30' });

  // 4. 409 → подхват существующего job'а (GET latest).
  ctx = baseCtx({ apiResult: null });
  ctx.api = async function (url) {
    this.calls.push({ url });
    if (url.indexOf('/latest') >= 0) {
      return { job_id: 'existing', status: 'running' };
    }
    const err = new Error('conflict'); err.status = 409; throw err;
  };
  ctx.loadDossierRebuild = async function () {
    const data = await this.api('/x/latest');
    this.dossierRebuildJob = data;
  };
  await M.startDossierRebuild.call(ctx);
  assert.strictEqual(ctx.dossierRebuildJob.job_id, 'existing');
  assert.strictEqual(ctx.pollStarts, 1);

  // 4b. 409 chat_locked (CLI-прогон) → НЕ подхватываем job и НЕ опрашиваем.
  ctx = baseCtx({ apiResult: null });
  ctx.api = async function (url) {
    this.calls.push({ url });
    const err = new Error('locked');
    err.status = 409;
    err.message = { code: 'chat_locked' };
    throw err;
  };
  let loaded = 0;
  ctx.loadDossierRebuild = async function () { loaded += 1; };
  await M.startDossierRebuild.call(ctx);
  assert.strictEqual(loaded, 0, 'chat_locked → без подхвата job');
  assert.strictEqual(ctx.pollStarts, 0, 'chat_locked → без polling');
  assert.ok(ctx.toasts.some(function (t) {
    return t.indexOf('занят') >= 0;
  }), 'chat_locked → корректный текст');

  // 5. Отмена: POST cancel, статус cancelling, polling продолжается.
  ctx = baseCtx({ dossierRebuildJob: { job_id: 'j1', status: 'running' } });
  ctx.apiResult = {};
  await M.cancelDossierRebuild.call(ctx);
  assert.ok(/\/rebuild\/j1\/cancel$/.test(ctx.calls[0].url), 'URL отмены');
  assert.strictEqual(ctx.calls[0].opts.method, 'POST');
  assert.strictEqual(ctx.dossierRebuildJob.status, 'cancelling');
  assert.strictEqual(ctx.pollStarts, 1);

  // 5b. Повторный клик при busy — no-op.
  ctx = baseCtx({ dossierRebuildJob: { job_id: 'j1', status: 'running' },
                  dossierRebuildBusy: true });
  await M.cancelDossierRebuild.call(ctx);
  assert.strictEqual(ctx.calls.length, 0, 'busy → без запроса');

  // 6. Polling-таймер: старт при активном, стоп очищает.
  const realSet = global.setInterval, realClear = global.clearInterval;
  let created = null, cleared = null;
  global.setInterval = function (fn, ms) { created = { fn: fn, ms: ms }; return 42; };
  global.clearInterval = function (id) { cleared = id; };
  ctx = baseCtx({ dossierRebuildJob: { job_id: 'j1', status: 'running' } });
  M.startDossierRebuildPolling.call(ctx);
  assert.ok(created && created.ms === 2000, 'интервал опроса 2с');
  assert.strictEqual(ctx.dossierRebuildTimer, 42);
  M.stopDossierRebuildPolling.call(ctx);
  assert.strictEqual(cleared, 42);
  assert.strictEqual(ctx.dossierRebuildTimer, null);
  // терминальный статус → таймер не стартует
  created = null;
  M.startDossierRebuildPolling.call(
    baseCtx({ dossierRebuildJob: { job_id: 'j1', status: 'done' } }));
  assert.strictEqual(created, null, 'done → polling не нужен');
  global.setInterval = realSet; global.clearInterval = realClear;

  // 7. localStorage-подсказка: запись и очистка.
  ctx = baseCtx();
  M._rememberDossierRebuild.call(ctx, 'job-9');
  assert.ok(global.localStorage._s['adminbot.dossier_rebuild']
    .indexOf('job-9') >= 0);
  M._rememberDossierRebuild.call(ctx, null);
  assert.strictEqual(
    global.localStorage._s['adminbot.dossier_rebuild'], undefined);

  // 8. Повторный откат: 'failed' + снапшот цел + откат ещё не сделан.
  const R = M.dossierRollbackRetryable;
  function failedJob(over) {
    const j = {
      status: 'failed', snapshot_ref: 'rollback_x.jsonl',
      rollback: { done: false }, error_code: 'rollback_failed',
      cleaned: 0, rebuilt: 0,
    };
    Object.keys(over || {}).forEach(function (k) { j[k] = over[k]; });
    return j;
  }
  assert.strictEqual(R.call({}, failedJob()), true, 'rollback_failed → retry');
  assert.strictEqual(R.call({}, failedJob({
    error_code: 'rebuild_failed', cleaned: 2 })), true, 'cleaned>0 → retry');
  assert.strictEqual(R.call({}, failedJob({
    error_code: 'rebuild_failed', rebuilt: 1 })), true, 'rebuilt>0 → retry');
  assert.strictEqual(R.call({}, failedJob({
    error_code: 'rebuild_failed' })), false, 'нечего откатывать');
  assert.strictEqual(R.call({}, failedJob({
    rollback: { done: true } })), false, 'уже откатано');
  assert.strictEqual(R.call({}, failedJob({
    snapshot_ref: '' })), false, 'нет снапшота');
  assert.strictEqual(R.call({}, failedJob({
    status: 'interrupted' })), false, 'не failed');
  assert.strictEqual(R.call({}, null), false);

  // 8b. S10.22-2: 'failed'/rebuild_empty с cleaned>0 → ручной откат доступен.
  assert.strictEqual(R.call({}, failedJob({
    error_code: 'rebuild_empty', cleaned: 1 })), true,
    'rebuild_empty + cleaned>0 → откат доступен');

  // 9. S10.22-6: kill-switch OFF (latest → 404) → блок скрывается.
  ctx = baseCtx({ dossierRebuildEnabled: true });
  ctx.api = async function () {
    const err = new Error('off'); err.status = 404; throw err;
  };
  await M.loadDossierRebuild.call(ctx);
  assert.strictEqual(ctx.dossierRebuildEnabled, false,
    '404 latest → dossierRebuildEnabled=false (кнопка скрыта)');
  assert.strictEqual(ctx.dossierRebuildJob, null);
  // ...а успешный latest (204/200) возвращает признак доступности.
  ctx = baseCtx({ dossierRebuildEnabled: false });
  ctx.api = async function () { return null; };
  await M.loadDossierRebuild.call(ctx);
  assert.strictEqual(ctx.dossierRebuildEnabled, true,
    'успешный latest → фича доступна');

  console.log('DOSSIER-REBUILD-UNIT-OK');
})().catch(function (err) {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
