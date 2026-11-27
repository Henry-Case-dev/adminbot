'use strict';
/* SAC-REV-R1-F1 (28.11.2026) — первый вход в чат: цель сохранения Core.

Что проверяем (поведение, не grep):
  A. Чатовая область. Loader Core вызван ДО разрешения области
     (`chatCtxReady=false`) -> запрос `/api/speech/core` НЕ уходит, пока
     `loadAccessCtx` не применит `activeChatId`; после готовности
     select «Куда сохранить» = чат и реальный Save уходит `scope:"chat"`.
     На базовом app.js (до фикса) Core грузится сразу без контекста, и Save
     пишет `scope:"global"` — тест красный.
  B. Негативный контроль: глобальная область (`activeChatId == null`,
     inheritance=global) -> цель остаётся глобальной, Save уходит
     `scope:"global"`; фикс не «прибивает» чат везде.
  C. Без авторизации (`lockAuth`) ожидание не зависает: загрузка доходит до
     401-заглушки, а не остаётся в «Загружаем…» навсегда.

Запуск: node tests/js/speech_core_scope_ctx_test.js
        APP_JS=<path> node tests/js/speech_core_scope_ctx_test.js   # RED-прогон
*/
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component() {}, provide() {}, use() {}, mount() {},
    };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
global.window.CogVisual = require(path.join(__dirname, '..', '..', 'web',
  'static', 'cog-visual.js'));
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() {
    return { style: {}, setAttribute() {}, remove() {}, focus() {} };
  },
  body: { appendChild() {}, removeChild() {} },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: {
    clipboard: { writeText: async function () { throw new Error('no clipboard'); } },
  },
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

function setLocalStorage(map) {
  global.localStorage = {
    _s: Object.assign({}, map),
    getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k)
      ? this._s[k] : null; },
    setItem(k, v) { this._s[k] = String(v); },
    removeItem(k) { delete this._s[k]; },
  };
}
setLocalStorage({});

const APP_JS = process.env.APP_JS
  ? path.resolve(process.env.APP_JS)
  : path.join(__dirname, '..', '..', 'web', 'app.js');
require(APP_JS);
assert(captured, 'Vue.createApp должен быть вызван (web/app.js)');
const methods = captured.methods;

const CHAT_ID = -100500;

function makeCtx(api) {
  const ctx = Object.assign({}, captured.data());
  Object.keys(methods).forEach(function (k) {
    if (typeof methods[k] === 'function') ctx[k] = methods[k];
  });
  ctx.api = api;
  ctx.$nextTick = function () {};
  ctx.toast = function () {};
  return ctx;
}

function corePayload(overrides) {
  return Object.assign({
    scope: 'chat',
    chat_id: CHAT_ID,
    inheritance: 'chat',
    can_edit: true,
    block_ids: { full: 'core.personality', compact: 'core.personality.compact' },
    selection: { level: 'compact', reason: 'owner_setting', revision: 'r7' },
    editions: {
      full: { text: 'ПОЛНАЯ', differs_from_factory: true },
      compact: { text: 'КОМПАКТНАЯ', differs_from_factory: true },
    },
    permanent_note: '',
    history: [],
    diff: {},
  }, overrides || {});
}

function makeApi(log, core) {
  return async function (apiPath, options) {
    log.push({ path: apiPath, options: options || {} });
    if (apiPath === '/api/access/me') {
      return { is_global_admin: true, role_name: 'owner' };
    }
    if (apiPath === '/api/access/chats') {
      return [{ chat_id: CHAT_ID, title: 'ЧАТ' }];
    }
    if (apiPath === '/api/speech/core') return core;
    if (apiPath.indexOf('/api/speech/block/') === 0) {
      return { result: { applied: true } };
    }
    return {};
  };
}

const tick = function () {
  return new Promise(function (resolve) { setImmediate(resolve); });
};

// Все проверки собираются: RED должен показать и порядок загрузки, и сам
// ушедший scope, а не падать на первой строке.
const failures = [];
function check(cond, msg) { if (!cond) failures.push(msg); }

function lastPost(log) {
  const posts = log.filter(function (e) {
    return e.options && e.options.method === 'POST';
  });
  return posts.length ? posts[posts.length - 1] : null;
}

function saveBody(post) {
  assert(post, 'Save обязан отправить POST');
  return JSON.parse(post.options.body);
}

(async function () {
  // ── A. Чатовая область: первый вход, Core грузится ДО готовности области ──
  {
    setLocalStorage({ 'adminbot.active_chat_id': String(CHAT_ID) });
    const log = [];
    const core = corePayload();
    const ctx = makeCtx(makeApi(log, core));
    const loading = ctx._loadSpeechCore();
    await tick();
    check(
      log.some(function (e) { return e.path === '/api/speech/core'; }) === false,
      'A: /api/speech/core не должен уходить до разрешения области '
      + '(иначе target scope фиксируется как global)');

    await ctx.loadAccessCtx();
    await loading;

    const iChats = log.findIndex(function (e) {
      return e.path === '/api/access/chats';
    });
    const iCore = log.findIndex(function (e) {
      return e.path === '/api/speech/core';
    });
    check(iChats >= 0, 'A: список чатов запрошен');
    check(iCore > iChats, 'A: Core запрошен уже в контексте чата ('
      + JSON.stringify(log.map(function (e) { return e.path; })) + ')');
    check(ctx.activeChatId === CHAT_ID, 'A: активный чат применён');
    check(ctx.speechScopeFor('core') === 'chat',
      'A: «Куда сохранить» по умолчанию = этот чат, не «Глобально» '
      + '(получено: ' + ctx.speechScopeFor('core') + ')');

    // Реальный Save (не только чтение select): тело уходит scope="chat".
    ctx.speechCoreEdition = 'compact';
    ctx.speechDirty.coreCompact = true;
    ctx.speechDrafts = { core: { full: 'ПОЛНАЯ', compact: 'ПРАВКА В ЧАТЕ' } };
    await ctx.saveSpeechCore();
    const post = lastPost(log);
    check(!!post, 'A: Save обязан отправить POST');
    if (post) {
      const body = saveBody(post);
      check(body.scope === 'chat',
        'A: первый Save Core в чате уходит scope="chat" (получено: '
        + JSON.stringify(body.scope) + ')');
      check(body.text === 'ПРАВКА В ЧАТЕ',
        'A: сохраняется текст черновика');
    }
  }

  // ── B. Негативный контроль: глобальная область остаётся глобальной ──────
  {
    setLocalStorage({});
    const log = [];
    const core = corePayload({
      scope: 'global', chat_id: null, inheritance: 'global',
      editions: {
        full: { text: 'ПОЛНАЯ', differs_from_factory: true },
        compact: { text: 'КОМПАКТНАЯ', differs_from_factory: true },
      },
    });
    const ctx = makeCtx(makeApi(log, core));
    const loading = ctx._loadSpeechCore();
    await tick();
    check(
      log.some(function (e) { return e.path === '/api/speech/core'; }) === false,
      'B: ожидание области действует и без сохранённого чата');
    await ctx.loadAccessCtx();
    await loading;
    check(ctx.activeChatId === null, 'B: глобальная область');
    check(ctx.speechScopeFor('core') === 'global',
      'B: в глобальной области цель остаётся «для всех чатов»');
    ctx.speechCoreEdition = 'compact';
    ctx.speechDirty.coreCompact = true;
    ctx.speechDrafts = { core: { full: 'ПОЛНАЯ', compact: 'ГЛОБАЛЬНАЯ ПРАВКА' } };
    await ctx.saveSpeechCore();
    const post = lastPost(log);
    check(!!post, 'B: глобальное сохранение отправляет POST');
    if (post) {
      check(saveBody(post).scope === 'global',
        'B: глобальное сохранение не превращается в чатовое');
    }
  }

  // ── C. Без авторизации ожидание не зависает ─────────────────────────────
  {
    setLocalStorage({});
    const log = [];
    const ctx = makeCtx(async function (apiPath) {
      log.push({ path: apiPath });
      const err = new Error('401');
      err.status = 401;
      throw err;
    });
    ctx.chatCtxReady = false;
    ctx.lockAuth('нет контекста');
    const outcome = await Promise.race([
      ctx._loadSpeechCore().then(function () { return 'resolved'; },
        function () { return 'rejected'; }),
      new Promise(function (resolve) { setTimeout(function () { resolve('timeout'); }, 200); }),
    ]);
    assert.notStrictEqual(outcome, 'timeout',
      'C: lockAuth отпускает ожидание — загрузка не висит в «Загружаем…»');
    assert.strictEqual(outcome, 'rejected',
      'C: без авторизации загрузка честно упирается в 401, не «успех»');
  }

  if (failures.length) {
    throw new Error('SAC-REV-R1-F1 FAIL:\n - ' + failures.join('\n - '));
  }

  console.log('SPEECH-CORE-SCOPE-CTX-OK');
  process.exit(0);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
