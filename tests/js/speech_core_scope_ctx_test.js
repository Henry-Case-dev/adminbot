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
  D. Поздняя авторизация (SAC-REV-R2-F1): после `lockAuth` + навигации в
     раздел и «Попробовать снова» первый Core/overview/persona запрос уходит
     ТОЛЬКО после применения области (`/api/access/*`), а не синхронно из
     `retryInitData`; цель сохранения — фактический чат.

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
  if (api) ctx.api = api;
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
    check(ctx.chatCtxReady === false,
      'C: lockAuth не объявляет контекст области известным');
  }

  // ── D. Поздняя авторизация: сначала область, потом раздел ───────────────
  {
    setLocalStorage({ 'adminbot.active_chat_id': String(CHAT_ID) });
    const order = [];
    const pending = {};
    function deferred(p, value) {
      order.push({ path: p, at: 'sent' });
      return new Promise(function (resolve) {
        pending[p] = function () { resolve(value); };
      });
    }
    function resolvePending(p) {
      if (pending[p]) {
        const fn = pending[p];
        pending[p] = null;
        fn();
      }
    }
    let ctx = null;
    // Управляемые промисы = честная сетевая задержка: видно, какие запросы
    // ушли ДО того, как область применена. Пока authLocked — как в жизни,
    // запросы не уходят, а падают в 401.
    ctx = makeCtx(function (apiPath) {
      if (ctx.authLocked) {
        order.push({ path: apiPath, at: '401' });
        const err = new Error('401');
        err.status = 401;
        return Promise.reject(err);
      }
      if (apiPath === '/api/access/me') {
        return deferred(apiPath, { is_global_admin: true, role_name: 'owner' });
      }
      if (apiPath === '/api/access/chats') {
        return deferred(apiPath, [{ chat_id: CHAT_ID, title: 'ЧАТ' }]);
      }
      if (apiPath === '/api/speech/overview') {
        return deferred(apiPath, { scope: 'chat', chat_id: CHAT_ID, sections: [] });
      }
      if (apiPath === '/api/persona') {
        return deferred(apiPath, {
          scope: 'chat', chat_id: CHAT_ID, is_global: false,
          values: { name: 'ИМЯ ЧАТА' },
        });
      }
      if (apiPath === '/api/speech/core') return corePayload();
      return Promise.resolve({});
    });
    // Граница сценария: вход/конфиг/прочие загрузчики не предмет проверки.
    ctx.hasInitData = function () { return true; };
    ctx.loadMe = async function () { this.me = { user_id: 1 }; };
    ctx.canViewTab = function () { return false; };
    ctx.hasPerm = function () { return true; };
    ctx.loadConfig = function () {};
    ctx.loadKeyStatus = function () {};
    ctx.loadAdmins = function () {};
    ctx.loadRoles = function () {};
    ctx.loadChats = function () {};
    ctx.applyRoute = function () {};

    ctx.chatCtxReady = false;
    ctx.lockAuth('нет контекста');
    // Пользователь открывает «Личность» при блокирующем баннере (навигация
    // живёт вне `<main v-else>`, гейта на setTab нет).
    ctx.setTab('speech');
    await tick(); await tick();

    // «Попробовать снова» — область ещё не получена.
    ctx.authLocked = false;
    ctx.retryInitData();
    await tick();
    const sentBeforeCtx = order.filter(function (e) { return e.at === 'sent'; })
      .map(function (e) { return e.path; });
    check(sentBeforeCtx.indexOf('/api/access/me') >= 0,
      'D: retry запрашивает область (/api/access/me)');
    ['/api/speech/overview', '/api/persona', '/api/speech/core'].forEach(function (p) {
      check(sentBeforeCtx.indexOf(p) < 0,
        'D: ' + p + ' не должен уходить до /api/access/* (ушло: '
        + JSON.stringify(sentBeforeCtx) + ')');
    });

    resolvePending('/api/access/me');
    await tick();
    const sentBeforeChats = order.filter(function (e) { return e.at === 'sent'; })
      .map(function (e) { return e.path; });
    check(sentBeforeChats.indexOf('/api/speech/overview') < 0,
      'D: overview ждёт полного разрешения области (/api/access/chats)');

    resolvePending('/api/access/chats');
    await tick(); await tick();

    const iChats = order.findIndex(function (e) {
      return e.path === '/api/access/chats' && e.at === 'sent';
    });
    const iOverview = order.findIndex(function (e) {
      return e.path === '/api/speech/overview' && e.at === 'sent';
    });
    const iPersona = order.findIndex(function (e) {
      return e.path === '/api/persona' && e.at === 'sent';
    });
    check(iChats >= 0, 'D: область запрошена');
    check(iOverview > iChats, 'D: overview только после области ('
      + JSON.stringify(order.map(function (e) { return e.path + '@' + e.at; }))
      + ')');
    check(iPersona > iChats, 'D: persona только после области');
    check(ctx.activeChatId === CHAT_ID, 'D: активный чат применён до раздела');

    resolvePending('/api/speech/overview');
    resolvePending('/api/persona');
    await tick(); await tick();
    check(ctx.speechScopeFor('core') === 'chat',
      'D: цель сохранения Core = фактический чат, не global (получено: '
      + ctx.speechScopeFor('core') + ')');
    check(ctx.speechScopeFor('style') === 'chat',
      'D: цель сохранения стиля = фактический чат (получено: '
      + ctx.speechScopeFor('style') + ')');
    check(ctx.personaMeta && ctx.personaMeta.scope === 'chat',
      'D: personaMeta из области чата');
    check(ctx.personaDraft && ctx.personaDraft.name === 'ИМЯ ЧАТА',
      'D: черновик личности заполнен данными чата, а не глобальными');
  }

  // ── E. Реальный api(): первый запрос раздела уже несёт X-Chat-Id ────────
  {
    setLocalStorage({ 'adminbot.active_chat_id': String(CHAT_ID) });
    sessionStorage.setItem('adminbot.initData', 'test-init');
    const savedFetch = global.fetch;
    const order = [];
    const pending = {};
    function defer(p, value) {
      return new Promise(function (resolve) {
        pending[p] = function () {
          resolve({ status: 200, ok: true, json: async function () { return value; } });
        };
      });
    }
    function resolvePending(p) {
      if (pending[p]) {
        const fn = pending[p];
        pending[p] = null;
        fn();
      }
    }
    global.fetch = function (p, init) {
      const headers = (init && init.headers) || {};
      order.push({ path: p, at: 'sent', chat: headers['X-Chat-Id'] || null });
      if (p === '/api/access/me') return defer(p, { is_global_admin: true });
      if (p === '/api/access/chats') return defer(p, [{ chat_id: CHAT_ID, title: 'ЧАТ' }]);
      if (p === '/api/speech/overview') {
        return defer(p, { scope: 'chat', chat_id: CHAT_ID, sections: [] });
      }
      if (p === '/api/persona') {
        return defer(p, {
          scope: 'chat', chat_id: CHAT_ID, is_global: false,
          values: { name: 'ИМЯ ЧАТА' },
        });
      }
      return Promise.resolve({
        status: 200, ok: true, json: async function () { return {}; },
      });
    };
    try {
      const ctx = makeCtx();
      ctx.hasInitData = function () { return true; };
      ctx.loadMe = async function () { this.me = { user_id: 1 }; };
      ctx.canViewTab = function () { return false; };
      ctx.hasPerm = function () { return true; };
      ctx.loadConfig = function () {};
      ctx.loadKeyStatus = function () {};
      ctx.loadAdmins = function () {};
      ctx.loadRoles = function () {};
      ctx.loadChats = function () {};
      ctx.applyRoute = function () {};

      ctx.lockAuth('нет контекста');
      ctx.setTab('speech');
      await tick(); await tick();

      ctx.authLocked = false;
      ctx.retryInitData();
      await tick();
      resolvePending('/api/access/me');
      await tick();
      resolvePending('/api/access/chats');
      await tick(); await tick();

      const iChats = order.findIndex(function (e) { return e.path === '/api/access/chats'; });
      const overview = order.find(function (e) { return e.path === '/api/speech/overview'; });
      const persona = order.find(function (e) { return e.path === '/api/persona'; });
      check(iChats >= 0, 'E: область чата запрошена');
      const iOverview = order.findIndex(function (e) {
        return e.path === '/api/speech/overview';
      });
      const iPersona = order.findIndex(function (e) { return e.path === '/api/persona'; });
      check(iOverview > iChats, 'E: overview уходит после области ('
        + JSON.stringify(order.map(function (e) { return e.path; })) + ')');
      check(iPersona > iChats, 'E: persona уходит после области');
      check(overview && overview.chat === String(CHAT_ID),
        'E: первый overview несёт X-Chat-Id активного чата (получено: '
        + JSON.stringify(overview && overview.chat) + ')');
      check(persona && persona.chat === String(CHAT_ID),
        'E: первый persona несёт X-Chat-Id активного чата (получено: '
        + JSON.stringify(persona && persona.chat) + ')');
      resolvePending('/api/speech/overview');
      resolvePending('/api/persona');
      await tick(); await tick();
      check(ctx.speechScopeFor('core') === 'chat',
        'E: цель сохранения Core = чат (получено: ' + ctx.speechScopeFor('core') + ')');
      check(ctx.personaDraft && ctx.personaDraft.name === 'ИМЯ ЧАТА',
        'E: личность прочитана в области чата');
    } finally {
      global.fetch = savedFetch;
      sessionStorage.removeItem('adminbot.initData');
    }
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
