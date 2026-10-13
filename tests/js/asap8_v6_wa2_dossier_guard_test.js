'use strict';
/* ASAP 8 v6 Wave A2 — D01 (18A.1): stale-response guard досье.
 *
 * Контракт: каждый load/save/rebuild досье захватывает immutable
 * (chat_id, participant_id, session_token) ДО первого await; устаревший
 * ответ (сменили участника/чат, закрыли модалку) не мутирует editor и не
 * тостит success/error в новом контексте; save строит URL из захваченной
 * identity; rebuild-polling подчиняется токену; тост сохранения называет
 * цель («Сохранено для <участник> — <чат>»); dirty-черновик переживает
 * закрытие и возвращается при переоткрытии.
 *
 * Прецедент паттерна: settings epoch-guard (persistItems/scopeEpoch,
 * round1025_save_state_test.js).
 *
 * Запуск: node tests/js/asap8_v6_wa2_dossier_guard_test.js
 *         (печатает DOSSIER-GUARD-UNIT-OK)
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

// ── Хелперы ──────────────────────────────────────────────────────────────────

function deferred() {
  let resolve, reject;
  const promise = new Promise(function (res, rej) {
    resolve = res; reject = rej;
  });
  return { promise, resolve, reject };
}

// api-мок с очередью: каждый вызов ждёт ручного resolve/reject по порядку.
function queuedApi() {
  const api = function (url, opts) {
    return new Promise(function (resolve, reject) {
      api.queue.push({ url: url, opts: opts || null, resolve, reject });
    });
  };
  api.queue = [];
  return api;
}

function instantApi(handler) {
  const fn = async function (url, opts) { return handler(url, opts); };
  fn.queue = [];
  return fn;
}

function baseCtx(over) {
  const ctx = {
    activeChatId: -100,
    dossierOpen: false, dossierBusy: false,
    dossierUserId: null, dossierName: '', dossierData: null,
    dossierDraft: '', dossierSaving: false,
    dossierSessionToken: null, _dossierDrafts: null,
    // F8: пересборка
    dossierRebuildJob: null, dossierRebuildBusy: false,
    dossierRebuildTimer: null, dossierRebuildEnabled: true,
    dossierRebuildPeriod: '180',
    oversightData: { chats: [{ chat_id: -100, title: 'Чат А' }] },
    calls: [], toasts: [], pollStarts: 0,
    api: null,
    toast(msg, kind) { this.toasts.push({ msg: msg, kind: kind || '' }); },
    loreErrText(e) { return (e && e.message) || 'err'; },
    resolveRelationName(row) { return (row && row.name) || 'Участник'; },
    startDossierRebuildPolling() { this.pollStarts += 1; },
    stopDossierRebuildPolling() {},
    // реальные методы (гвард — файловые функции, не методы)
    openDossier: M.openDossier,
    loadDossier: M.loadDossier,
    saveDossier: M.saveDossier,
    closeDossier: M.closeDossier,
    resumeDossierRebuild: M.resumeDossierRebuild,
    loadDossierRebuild: M.loadDossierRebuild,
    pollDossierRebuild: M.pollDossierRebuild,
    startDossierRebuild: M.startDossierRebuild,
    dossierRebuildIsActive: M.dossierRebuildIsActive,
    dossierRollbackRetryable: M.dossierRollbackRetryable,
    _rememberDossierRebuild: M._rememberDossierRebuild,
  };
  Object.keys(over || {}).forEach(function (k) { ctx[k] = over[k]; });
  return ctx;
}

const DATA_A = { user_id: 5, manual_traits: 'черновик A', extracted: 'авто A' };
const DATA_B = { user_id: 7, manual_traits: 'черновик B', extracted: 'авто B' };

function okToast(ctx, needle) {
  return ctx.toasts.filter(function (t) {
    return t.kind === 'ok' && t.msg.indexOf(needle) >= 0;
  });
}
function anyToast(ctx, needle) {
  return ctx.toasts.filter(function (t) { return t.msg.indexOf(needle) >= 0; });
}

(async function run() {
  // 0. dossierTargetLabel недоступен как метод (файловый хелпер по дизайну —
  //    гвард работает и на фейках без новых полей); целевой лейбл проверяется
  //    ниже через тексты тостов (тесты 3 и 6b).

  // 1. Позитивный контроль: свежая загрузка применяется.
  {
    const ctx = baseCtx({ api: instantApi(function () { return DATA_A; }) });
    ctx.dossierSessionToken = 1; ctx.dossierUserId = 5; ctx.dossierOpen = true;
    await M.loadDossier.call(ctx, 5, 'Аня');
    assert.strictEqual(ctx.dossierData, DATA_A);
    assert.strictEqual(ctx.dossierDraft, 'черновик A');
    assert.strictEqual(ctx.toasts.length, 0, 'чистая загрузка — без тостов');
  }

  // 2. ГЛАВНАЯ РЕГРЕССИЯ 18A.1: A-load в полёте → открыт B → ответ A
  //    НЕ заменяет editor B и не тостит.
  {
    const ctx = baseCtx();
    const api = queuedApi(); ctx.api = api;
    ctx.dossierOpen = true; ctx.dossierSessionToken = 1;
    ctx.dossierUserId = 5; ctx.dossierName = 'Аня';
    const pA = M.loadDossier.call(ctx, 5, 'Аня');
    assert.strictEqual(api.queue.length, 1);
    assert.ok(api.queue[0].url.indexOf('/chat_lore/-100/dossier/5') >= 0,
      'запрос A — по identity A');
    // Переключение на B: новый инстанс модалки (токен 2), чужие данные.
    ctx.dossierSessionToken = 2; ctx.dossierUserId = 7; ctx.dossierName = 'Боря';
    ctx.dossierData = DATA_B; ctx.dossierDraft = 'правка B в полёте';
    api.queue[0].resolve(DATA_A);
    await pA;
    assert.strictEqual(ctx.dossierData, DATA_B, 'editor B не тронут ответом A');
    assert.strictEqual(ctx.dossierDraft, 'правка B в полёте',
      'черновик B не заменён A-текстом');
    assert.strictEqual(ctx.toasts.length, 0, 'stale-ответ не тостит');
  }

  // 2b. То же с закрытием модалки (токен погашен) — без переоткрытия.
  {
    const ctx = baseCtx();
    const api = queuedApi(); ctx.api = api;
    ctx.dossierOpen = true; ctx.dossierSessionToken = 1;
    ctx.dossierUserId = 5;
    const pA = M.loadDossier.call(ctx, 5, 'Аня');
    M.closeDossier.call(ctx);
    assert.strictEqual(ctx.dossierSessionToken, null, 'close гасит токен');
    assert.strictEqual(ctx.dossierOpen, false);
    api.queue[0].resolve(DATA_A);
    await pA;
    assert.strictEqual(ctx.dossierData, null, 'закрытая модалка не мутируется');
    assert.strictEqual(ctx.dossierDraft, '');
    assert.strictEqual(ctx.toasts.length, 0);
  }

  // 2c. Ошибка A-load после switch — не тостит ошибку в контексте B.
  {
    const ctx = baseCtx();
    const api = queuedApi(); ctx.api = api;
    ctx.dossierSessionToken = 1; ctx.dossierUserId = 5; ctx.dossierOpen = true;
    const pA = M.loadDossier.call(ctx, 5, 'Аня');
    ctx.dossierSessionToken = 2; ctx.dossierUserId = 7;
    ctx.dossierData = DATA_B; ctx.dossierDraft = 'B';
    const err = new Error('boom'); err.status = 500;
    api.queue[0].reject(err);
    await pA;
    assert.strictEqual(ctx.dossierData, DATA_B);
    assert.strictEqual(ctx.toasts.length, 0, 'stale-ошибка не тостит');
  }

  // 3. saveDossier: URL/PUT из захваченной identity, успешный ack →
  //    editor обновлён, тост называет цель.
  {
    const ctx = baseCtx();
    const api = queuedApi(); ctx.api = api;
    ctx.dossierOpen = true; ctx.dossierSessionToken = 3;
    ctx.dossierUserId = 5; ctx.dossierName = 'Аня'; ctx.dossierDraft = 'новый текст';
    const p = M.saveDossier.call(ctx);
    assert.strictEqual(api.queue[0].opts.method, 'PUT');
    assert.ok(api.queue[0].url.indexOf('/chat_lore/-100/dossier/5') >= 0);
    assert.deepStrictEqual(JSON.parse(api.queue[0].opts.body),
      { traits: 'новый текст' });
    api.queue[0].resolve({ manual_traits: 'новый текст' });
    await p;
    assert.strictEqual(ctx.dossierDraft, 'новый текст');
    const ok = okToast(ctx, 'Сохранено для Аня — Чат А');
    assert.strictEqual(ok.length, 1, 'тост называет <участник> и <чат>: '
      + JSON.stringify(ctx.toasts));
  }

  // 3b. ГЛАВНАЯ РЕГРЕССИЯ: A-save в полёте → switch B → A-completion
  //     НЕ тостит success в B и НЕ пишет A-ответ в editor B.
  //     Identity (chat/user) в URL — захваченная на клике.
  {
    const ctx = baseCtx();
    const api = queuedApi(); ctx.api = api;
    ctx.dossierOpen = true; ctx.dossierSessionToken = 4;
    ctx.dossierUserId = 5; ctx.dossierName = 'Аня'; ctx.dossierDraft = 'A-текст';
    const p = M.saveDossier.call(ctx);
    // Пользователь закрыл A и открыл B, начал править.
    ctx.dossierSessionToken = 5; ctx.dossierUserId = 7; ctx.dossierName = 'Боря';
    ctx.dossierData = DATA_B; ctx.dossierDraft = 'B-правка';
    api.queue[0].resolve({ manual_traits: 'A-сохранённый текст' });
    await p;
    assert.strictEqual(ctx.dossierData, DATA_B, 'A-ответ не переписал editor B');
    assert.strictEqual(ctx.dossierDraft, 'B-правка', 'черновик B не затёрт');
    assert.strictEqual(ctx.toasts.length, 0,
      'A-completion не тостит success в контексте B');
    assert.strictEqual(ctx.dossierSaving, false, 'кнопка B не залипла');
    // pending-черновик A снят (сервер принял) — тихо.
    assert.strictEqual(ctx._dossierDrafts && ctx._dossierDrafts['-100:5'],
      undefined, 'серверный ack снимает pending-черновик A');
  }

  // 3c. A-save с ошибкой после switch — не тостит error в B.
  {
    const ctx = baseCtx();
    const api = queuedApi(); ctx.api = api;
    ctx.dossierSessionToken = 6; ctx.dossierUserId = 5; ctx.dossierOpen = true;
    const p = M.saveDossier.call(ctx);
    ctx.dossierSessionToken = 7; ctx.dossierUserId = 7;
    ctx.dossierData = DATA_B; ctx.dossierDraft = 'B-правка';
    api.queue[0].reject(new Error('denied'));
    await p;
    assert.strictEqual(ctx.toasts.length, 0, 'stale-error не тостит');
    assert.strictEqual(ctx.dossierDraft, 'B-правка');
  }

  // 3d. Смена активного чата между кликом и ответом: URL остался A-чатом,
  //     ответ не применяется к модалке (уже другой контекст).
  {
    const ctx = baseCtx();
    const api = queuedApi(); ctx.api = api;
    ctx.dossierOpen = true; ctx.dossierSessionToken = 8;
    ctx.dossierUserId = 5;
    const p = M.saveDossier.call(ctx);
    assert.ok(api.queue[0].url.indexOf('/chat_lore/-100/') >= 0,
      'URL построен из захваченного chat_id ДО await');
    ctx.dossierSessionToken = 9; ctx.activeChatId = -200;
    api.queue[0].resolve({ manual_traits: 'x' });
    await p;
    assert.strictEqual(ctx.toasts.length, 0, 'нет success в новом чате');
  }

  // 4. ESC/close с dirty draft: черновик переживает закрытие, возвращается
  //    при переоткрытии того же досье; чистое закрытие ничего не хранит.
  {
    const ctx = baseCtx();
    const api = instantApi(function (url) {
      if (url.indexOf('/rebuild/latest') >= 0) return null;
      return DATA_A;
    });
    ctx.api = api;
    await M.openDossier.call(ctx, { user_id: 5, name: 'Аня' });
    assert.strictEqual(ctx.dossierDraft, 'черновик A');
    ctx.dossierDraft = 'несохранённые каракули';
    M.closeDossier.call(ctx);
    assert.strictEqual(ctx.dossierDraft, '', 'модалка закрыта чисто');
    assert.strictEqual(ctx.dossierSessionToken, null);
    // переоткрытие: pending-черновик важнее серверного значения.
    await M.openDossier.call(ctx, { user_id: 5, name: 'Аня' });
    assert.strictEqual(ctx.dossierDraft, 'несохранённые каракули',
      'dirty-черновик восстановлен при переоткрытии');
    // сохранение закрывает pending.
    let serverTraits = 'сохранили';
    ctx.api = instantApi(function () {
      return { manual_traits: serverTraits };
    });
    ctx.dossierDraft = 'сохранили';
    await M.saveDossier.call(ctx);
    assert.ok(okToast(ctx, 'Сохранено для Аня').length === 1);
    // чистое закрытие (draft === серверному значению) не оставляет pending.
    M.closeDossier.call(ctx);
    serverTraits = 'сервер-свежий';
    await M.openDossier.call(ctx, { user_id: 5, name: 'Аня' });
    assert.strictEqual(ctx.dossierDraft, 'сервер-свежий',
      'после серверного ack pending снят — черновик от сервера');
  }

  // 5. Stale openDossier не гасит спиннер (busy) новой сессии.
  {
    const ctx = baseCtx();
    const api = queuedApi(); ctx.api = api;
    // A: open → GET висит.
    const pA = M.openDossier.call(ctx, { user_id: 5, name: 'Аня' });
    assert.strictEqual(ctx.dossierSessionToken, 1);
    // закрыли, открыли B (токен 2, busy=true).
    M.closeDossier.call(ctx);
    const pB = M.openDossier.call(ctx, { user_id: 7, name: 'Боря' });
    assert.strictEqual(ctx.dossierSessionToken, 2);
    assert.strictEqual(ctx.dossierBusy, true);
    // A-dataset прибывает последним.
    api.queue[0].resolve(DATA_A);
    await pA;
    assert.strictEqual(ctx.dossierBusy, true,
      'stale openDossier не снимает busy сессии B');
    // B-dataset: queue[1] = GET досье B, queue[2] = GET rebuild/latest B.
    api.queue[1].resolve(DATA_B);
    for (let i = 0; i < 50 && api.queue.length < 3; i++) {
      await Promise.resolve();   // дать loadDossier применить и дойти до latest
    }
    api.queue[2].resolve(null);
    await pB;
    assert.strictEqual(ctx.dossierBusy, false, 'своя сессия busy снимает');
    assert.strictEqual(ctx.dossierData, DATA_B);
  }

  // 6. rebuild-polling: устаревший тик игнорируется после смены участника.
  {
    const ctx = baseCtx();
    const api = queuedApi(); ctx.api = api;
    ctx.dossierOpen = true; ctx.dossierSessionToken = 10;
    ctx.dossierUserId = 5; ctx.dossierName = 'Аня';
    ctx.dossierRebuildJob = { job_id: 'j1', status: 'running' };
    const p = M.pollDossierRebuild.call(ctx);
    assert.ok(api.queue[0].url.indexOf('/dossier/5/rebuild/j1') >= 0);
    ctx.dossierSessionToken = 11; ctx.dossierUserId = 7;
    ctx.dossierRebuildJob = { job_id: 'j2', status: 'running' };
    let reloaded = 0;
    ctx.loadDossier = async function () { reloaded += 1; };
    api.queue[0].resolve({ job_id: 'j1', status: 'done' });
    await p;
    assert.strictEqual(ctx.dossierRebuildJob.job_id, 'j2',
      'stale-тик не мутирует job нового участника');
    assert.strictEqual(reloaded, 0, 'stale-done не перезагружает editor');
    assert.strictEqual(ctx.toasts.length, 0, 'stale-done не тостит');
    assert.strictEqual(ctx.pollStarts, 0);
  }

  // 6b. Свежий poll done: перезагрузка + тост с target.
  {
    const ctx = baseCtx();
    const api = queuedApi(); ctx.api = api;
    ctx.dossierSessionToken = 12; ctx.dossierUserId = 5;
    ctx.dossierName = 'Аня'; ctx.dossierOpen = true;
    ctx.dossierRebuildJob = { job_id: 'j9', status: 'running' };
    let reloaded = 0;
    ctx.loadDossier = async function (uid) {
      reloaded += 1;
      assert.strictEqual(uid, 5, 'перезагрузка — по identity сессии');
    };
    const p = M.pollDossierRebuild.call(ctx);
    api.queue[0].resolve({ job_id: 'j9', status: 'done' });
    await p;
    assert.strictEqual(reloaded, 1);
    assert.ok(okToast(ctx, 'Досье пересобрано: Аня — Чат А').length === 1);
  }

  // 6c. loadDossierRebuild: устаревший latest не трогает job/enabled.
  {
    const ctx = baseCtx();
    const api = queuedApi(); ctx.api = api;
    ctx.dossierSessionToken = 13; ctx.dossierUserId = 5; ctx.dossierOpen = true;
    const p = M.loadDossierRebuild.call(ctx);
    ctx.dossierSessionToken = 14; ctx.dossierUserId = 7;
    ctx.dossierRebuildJob = { job_id: 'jB' };
    api.queue[0].resolve({ job_id: 'jA', status: 'done' });
    await p;
    assert.strictEqual(ctx.dossierRebuildJob.job_id, 'jB',
      'stale latest не мутирует job B');
    assert.strictEqual(ctx.dossierRebuildEnabled, true,
      'stale latest не переключает видимость блока');
  }

  // 7. startDossierRebuild: устаревший ответ не стартует polling и не тостит.
  {
    const ctx = baseCtx();
    const api = queuedApi(); ctx.api = api;
    ctx.dossierSessionToken = 15; ctx.dossierUserId = 5; ctx.dossierOpen = true;
    const p = M.startDossierRebuild.call(ctx);
    assert.ok(api.queue[0].url.indexOf('/dossier/5/rebuild') >= 0);
    ctx.dossierSessionToken = 16; ctx.dossierUserId = 7;
    api.queue[0].resolve({ job_id: 'jX', status: 'queued' });
    await p;
    assert.strictEqual(ctx.dossierRebuildJob, null,
      'stale-старт не пишет job новой сессии');
    assert.strictEqual(ctx.pollStarts, 0, 'stale-старт не запускает polling');
    assert.strictEqual(ctx.toasts.length, 0);
    assert.strictEqual(
      global.localStorage._s['adminbot.dossier_rebuild'], undefined,
      'stale-старт не пишет localStorage-подсказку');
  }

  // 8. loadDossier: pending-черновик НЕ подменяет данные при чистой паре.
  {
    const ctx = baseCtx();
    ctx._dossierDrafts = { '-100:5': 'хвост другой пары' };
    ctx.api = instantApi(function () { return DATA_B; });
    ctx.dossierSessionToken = 17; ctx.dossierUserId = 7; ctx.dossierOpen = true;
    await M.loadDossier.call(ctx, 7, 'Боря');
    assert.strictEqual(ctx.dossierDraft, 'черновик B',
      'pending чужой пары не применяется');
  }

  console.log('DOSSIER-GUARD-UNIT-OK');
})().catch(function (err) {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
