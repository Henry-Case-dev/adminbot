'use strict';
/* MOD-ACL-UX-01 M1-C — UI-сторона MAC-S4-171 и MAC-S4-172.

 * MAC-S4-171 (UI): сервер различает 401 «missing init data», 401 «invalid
 *   init data», 403, 404 и 503 (locked в M1-B на отданных байтах). Здесь
 *   проверяется, что ОНИ ЖЕ различимы в пользовательском тексте Mini App, что
 *   403/404/503 не выглядят «проблемой сессии» (authError), а 401 — «нет
 *   доступа».
 * MAC-S4-172 (UI): объект `detail` из ответа API не является каналом
 *   «сырой payload → DOM». Положительный контроль: посаженный литерал реально
 *   присутствует в ответе (иначе отсутствие в DOM ничего не доказывает).
 *   Контроль чувствительности: известные поля (`code`, `message`) и строковый
 *   `detail` доходят до пользователя без маскировки. Консоль: ни один вызов
 *   console.* не получает payload ответа.

 * Все проверки выполняются ВСЕГДА (полный список различий), а не до первого
 * падения: RED-лог на базе показывает каждое исправленное поведение отдельно.

 * Запуск: node tests/js/mod_acl_ux_m1c_ui_states_test.js → MOD-ACL-M1C-UI-OK
 *
 * TEST-LIFECYCLE: CONTRACT owner=MOD-ACL-UX-01/M1-C (MAC-S4-171, MAC-S4-172)
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');

/* Посаженный секрет: без `sk-`, Bearer и URI-шаблона — иначе его скрыл бы
 * общий регэксп, и тест доказывал бы не то. */
const PLANT = 'M1C-PLANT-SECRET-7f3a91';
/* Контроль чувствительности: не секрет, обязан остаться видимым. */
const BENIGN = 'M1C-BENIGN-MARKER-2c5d';

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
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    return { tagName: tag, className: '', value: '', style: {},
             setAttribute() {}, focus() {}, select() {}, remove() {} };
  },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };
global.fetch = async function () { throw new Error('fetch не ожидался в этом тесте'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;

/* ── Стенд: реальный api() + реальный разбор ошибки ─────────────────────── */
function makeCtx() {
  const toasts = [];
  // `this` в реальном компоненте — тот же объект methods, поэтому подписи
  // состояний доступны api() без отдельного дублирования.
  const ctx = Object.assign({}, methods, {
    authLocked: false,
    authError: null,
    activeChatId: null,
    hasInitData: function () { return true; },
    toast: function (m, k) { toasts.push([m, k]); },
  });
  ctx._toasts = toasts;
  return ctx;
}

function stubFetch(status, body) {
  const calls = [];
  global.fetch = async function (url, init) {
    calls.push({ url: url, init: init });
    return {
      status: status,
      ok: status >= 200 && status < 300,
      json: async function () {
        if (body === undefined) throw new Error('нет тела');
        return body;
      },
    };
  };
  return calls;
}

/* «Пользовательский текст» состояния доступа: у 401 это баннер сессии
 * (`authError`), у 403/404/503 — заголовок+подсказка существующей карточки
 * ошибки (`accessErrorTitle/Hint`, те же вызовы, что в index.html). */
function userText(ctx, err) {
  if (err.status === 401) return String(ctx.authError || '');
  return methods.accessErrorTitle.call(methods, err.status) + ' | '
    + methods.accessErrorHint.call(methods, err.status, 'roles');
}

async function probeAccessState(status, body) {
  const ctx = makeCtx();
  stubFetch(status, body);
  let err = null;
  try { await methods.api.call(ctx, '/api/admins', { global: true }); }
  catch (e) { err = e; }
  assert(err && err.status === status,
    'api() обязан бросать ApiError со статусом ' + status);
  return { ctx: ctx, err: err, text: userText(ctx, err) };
}

/* ── Сбор всех различий (а не первого падения) ──────────────────────────── */
const failures = [];
async function check(label, fn) {
  try { await fn(); } catch (e) {
    failures.push(label + ' :: ' + ((e && e.message) || String(e)));
  }
}

function must(cond, msg) { if (!cond) throw new Error(msg); }
function mustEq(a, b, msg) {
  if (a !== b) throw new Error(msg + ' (actual=' + JSON.stringify(a)
    + ', expected=' + JSON.stringify(b) + ')');
}

(async function () {
  /* ═══ A. MAC-S4-171: пять состояний различимы ═══════════════════════════ */
  const missing = await probeAccessState(401, { detail: 'missing init data' });
  const invalid = await probeAccessState(401, { detail: 'invalid init data' });
  const denied = await probeAccessState(403, { detail: 'permission denied' });
  const absent = await probeAccessState(404, { detail: 'Not Found' });
  const down = await probeAccessState(503, { detail: 'PostgreSQL недоступен (R6)' });

  const states = {
    '401/missing': missing, '401/invalid': invalid,
    '403': denied, '404': absent, '503': down,
  };
  const texts = {};
  Object.keys(states).forEach(function (k) { texts[k] = states[k].text; });

  await check('A1: каждое состояние имеет непустой пользовательский текст',
    function () {
      Object.keys(texts).forEach(function (k) {
        must(texts[k] && texts[k].length > 0, k + ': состояние без текста');
      });
    });

  await check('A2: пять состояний показываются РАЗНЫМ текстом (попарно)',
    function () {
      const seen = {};
      Object.keys(texts).forEach(function (k) {
        must(seen[texts[k]] === undefined,
          'состояния ' + seen[texts[k]] + ' и ' + k
          + ' показываются одинаково: ' + JSON.stringify(texts[k]));
        seen[texts[k]] = k;
      });
    });

  await check('A3: 401/missing называет отсутствие данных Telegram, не «устарело»',
    function () {
      must(/initData/i.test(texts['401/missing']),
        '401/missing: ' + JSON.stringify(texts['401/missing']));
      must(!/устарел/i.test(texts['401/missing']),
        '401/missing выдаёт отсутствие данных за устаревшую сессию: '
        + JSON.stringify(texts['401/missing']));
    });

  await check('A4: 401/invalid говорит про повторный вход/подпись',
    function () {
      must(/заново|устарел|подпис/i.test(texts['401/invalid']),
        '401/invalid: ' + JSON.stringify(texts['401/invalid']));
    });

  await check('A5: ApiError сохраняет серверную причину 401 (ui не выдумывает)',
    function () {
      mustEq(missing.err.message, 'missing init data', 'A5/missing');
      mustEq(invalid.err.message, 'invalid init data', 'A5/invalid');
    });

  await check('A6: 403 — «нет доступа», а не проблема сессии', function () {
    mustEq(denied.ctx.authError, null, '403 не должен ставить authError');
    mustEq(denied.err.message, 'permission denied', 'A6/detail');
    mustEq(denied.ctx._toasts.length, 1, 'A6/тост «Доступ запрещён»');
    mustEq(denied.ctx._toasts[0][0].indexOf('Доступ запрещён'), 0,
      'A6/текст тоста: ' + denied.ctx._toasts[0][0]);
  });

  await check('A7: 404 и 503 не выдают себя за 401/403', function () {
    [absent, down].forEach(function (s) {
      mustEq(s.ctx.authError, null,
        s.err.status + ' не должен ставить authError');
      mustEq(s.ctx._toasts.length, 0,
        s.err.status + ' не должен выдавать тост «Доступ запрещён»');
    });
    mustEq(methods.accessErrorTitle.call(methods, 404), 'Не найдено', 'A7/404');
    mustEq(methods.accessErrorTitle.call(methods, 503),
      'Сервис временно недоступен', 'A7/503');
  });

  await check('A8 (граница): 401 без разбираемого тела не выдумывает причину',
    async function () {
      const opaque = await probeAccessState(401, undefined);
      must(opaque.ctx.authError && opaque.ctx.authError.length > 0,
        '401 без тела всё равно даёт текст');
      must(!/нет данных Telegram/i.test(opaque.ctx.authError),
        'без доказательства причины нельзя утверждать «нет данных Telegram»: '
        + JSON.stringify(opaque.ctx.authError));
    });

  await check('A9: баннер авторизации — текст, без HTML-канала', function () {
    must(INDEX.indexOf('{{ authError }}') >= 0,
      'баннер выводит authError текстом');
    must(INDEX.indexOf('v-html="authError"') < 0,
      'authError не выводится как HTML');
  });

  /* ═══ B. MAC-S4-172: payload ответа не идёт в DOM/консоль ═══════════════ */
  const secretBody = { detail: { note: PLANT } };

  await check('B1 (положительный контроль): секрет есть в байтах ответа',
    function () {
      must(JSON.stringify(secretBody).indexOf(PLANT) >= 0,
        'секрета нет в ответе — отсутствие в DOM ничего бы не доказывало');
    });

  const ctxSecret = makeCtx();
  stubFetch(503, secretBody);
  let secretErr = null;
  try {
    await methods.api.call(ctxSecret, '/api/access/audit?scope=global&limit=50',
                           { global: true });
  } catch (e) { secretErr = e; }

  await check('B2: 503 с объектом detail доходит до панели', function () {
    must(secretErr && secretErr.status === 503, '503 не дошёл: ' + secretErr);
  });

  await check('B3: DOM-привязка карточки ошибки не содержит секрет', function () {
    const payload = methods.accessErrorPayload.call(methods, secretErr);
    must(payload.message && payload.message.length > 0,
      'карточка ошибки осталась без текста');
    must(payload.message.indexOf(PLANT) < 0,
      'неизвестное поле detail попало в DOM-привязку: ' + payload.message);
  });

  await check('B4: errText не сериализует произвольный объект', function () {
    must(methods.errText.call(methods, { message: { note: PLANT } })
      .indexOf(PLANT) < 0, 'errText отдал секрет из неизвестного поля');
  });

  await check('B5 (контроль чувствительности): известные поля не маскируются',
    function () {
      const benign = methods.errText.call(methods, {
        message: { code: 'revision_mismatch', message: BENIGN },
      });
      must(benign.indexOf(BENIGN) >= 0,
        'BENIGN-маркер исчез: ' + benign);
      must(benign.indexOf('revision_mismatch') >= 0,
        'код причины исчез: ' + benign);
      mustEq(methods.errText.call(methods,
        { message: 'нет права на prompts.meme_joke' }),
      'нет права на prompts.meme_joke',
      'строковый detail не переписывается');
    });

  await check('B6: ни один console.* не получает payload ответа',
    async function () {
      const consoleArgs = [];
      const originals = {};
      ['log', 'debug', 'info', 'warn', 'error'].forEach(function (name) {
        originals[name] = console[name];
        console[name] = function () {
          consoleArgs.push(Array.prototype.map.call(arguments, function (a) {
            try { return (typeof a === 'string') ? a : JSON.stringify(a); }
            catch (e) { return String(a); }
          }).join(' '));
        };
      });
      try {
        const ctx403 = makeCtx();
        stubFetch(403, { detail: 'permission denied', secret: PLANT });
        await methods.api.call(ctx403, '/api/admins', { global: true })
          .catch(function () {});
        const ctx503 = makeCtx();
        stubFetch(503, secretBody);
        await methods.api.call(ctx503, '/api/status', { global: true })
          .catch(function () {});
        await methods.loadLogs.call(Object.assign({}, methods, {
          logLevel: 'ERROR+WARNING', logs: [], logsLoading: false,
          api: async function () { throw secretErr; },
        }));
      } finally {
        Object.keys(originals).forEach(function (name) {
          console[name] = originals[name];
        });
      }
      consoleArgs.forEach(function (line) {
        must(line.indexOf(PLANT) < 0, 'payload ответа в консоли: ' + line);
      });
    });

  if (failures.length) {
    console.error('MOD-ACL-M1C-UI-FAILED (' + failures.length + ')');
    failures.forEach(function (f, i) {
      console.error(String(i + 1).padStart(2, ' ') + '. ' + f);
    });
    process.exit(1);
  }
  console.log('MOD-ACL-M1C-UI-OK');
})().catch(function (e) {
  console.error((e && e.stack) || e);
  process.exit(1);
});
