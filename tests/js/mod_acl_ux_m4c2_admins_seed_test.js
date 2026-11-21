'use strict';
/* ═══ MOD-ACL-UX-01 M4C C2-R1-7 — noActor только после /api/admins ════════
 * RED-регресс: при свежей загрузке `admins=[]`, `adminsLoaded=false` preview
 * не должен показывать «Роль не назначена»/disabled; после завершения
 * `/api/admins` actor-list и seed обновляются, кнопка доступна, если роль
 * назначена.
 *
 * Запуск: node tests/js/mod_acl_ux_m4c2_admins_seed_test.js
 *         → MOD-ACL-UX-M4C2-ADMINS-SEED-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
global.Vue = {
  createApp: function (opts) {
    global.__opts = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  matchMedia: function () { return { matches: false, addEventListener() {} }; },
  innerWidth: 1280, innerHeight: 800,
  confirm: function () { return true; },
};
global.document = {
  documentElement: {
    setAttribute() {}, getAttribute() { return null; },
    classList: { toggle() {}, contains() { return false; } },
    style: { setProperty() {}, removeProperty() {} },
  },
  addEventListener() {}, getElementById() { return null; },
  createElement(tag) {
    return { tagName: tag, className: '', value: '', style: {},
             setAttribute() {}, focus() {}, select() {}, remove() {},
             getContext() { return null; } };
  },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
  querySelector() { return null; }, querySelectorAll() { return []; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('no'); } } },
});
global.sessionStorage = { _s: {}, getItem() { return null; },
                          setItem() {}, removeItem() {} };
global.localStorage = { _s: {}, getItem() { return null; },
                        setItem() {}, removeItem() {} };
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch'); };

require(path.join(ROOT, 'web', 'app.js'));
const methods = global.__opts.methods || {};

function vm(extra) {
  return Object.assign({}, methods, {
    me: { telegram_id: 5885953495, first_name: 'Audit' },
    isGlobalAdmin: true,
    admins: [],
    adminsLoaded: false,
    adminsLoading: true,
    adminsError: null,
    accessOpen: 'roles',
    roleEditor: { roleName: 'admin', tree: null, sections: [], actions: [] },
    preview: {
      actorValue: 'self', actorManual: '', scopeValue: 'global',
      resource: '', operation: 'view', loading: false, error: null,
      result: null, stale: false, noActor: false, chatAdmins: [],
      chatAdminsError: null, chatOverrides: null, chatOverridesError: null,
      _seq: 0, _adminsSeq: 0, _overridesSeq: 0,
    },
  }, extra || {});
}

(async function main() {
  let ctx = vm();
  // Свежая загрузка: назначения ещё неизвестны.
  methods.previewSeedActor.call(ctx);
  assert.strictEqual(ctx.preview.noActor, false,
    'noActor до /api/admins запрещён');
  assert.notStrictEqual(ctx.preview.actorValue, '',
    'actor остаётся выбираемым (Я)');
  assert.strictEqual(ctx.preview.actorValue, 'self');
  let opts = methods.previewActorOptions.call(ctx);
  assert.deepStrictEqual(opts.map(function (o) { return o.value; }),
    ['self', 'manual'], 'до admins — self + manual (admin)');

  // Загрузка /api/admins завершилась: роль admin назначена.
  const calls = [];
  ctx.api = async function (p, o) {
    calls.push(p);
    return { admins: [{ telegram_id: 5885953495, role_name: 'admin',
                        display_name: 'Audit' }] };
  };
  ctx.loadAvatar = async function () { return null; };
  await methods.loadAdmins.call(ctx);
  assert.strictEqual(calls.length, 1, 'loadAdmins сделал 1 запрос');
  assert.strictEqual(ctx.adminsLoaded, true, 'adminsLoaded после загрузки');
  assert.strictEqual(ctx.preview.noActor, false,
    'роль admin назначена — noActor нет');
  opts = methods.previewActorOptions.call(ctx);
  assert.ok(opts.some(function (o) { return o.value === '5885953495'; }),
    'actor-list содержит назначенного admin');
  assert.ok(require('fs').readFileSync(
    path.join(ROOT, 'web', 'index.html'), 'utf8')
    .indexOf(':disabled="preview.loading || preview.noActor"') >= 0,
    'run disabled только loading/noActor');

  // Известно пустые назначения → честный noActor.
  ctx = vm({
    adminsLoaded: true, adminsLoading: false,
    roleEditor: { roleName: 'local_admin', tree: null, sections: [],
                  actions: [] },
  });
  methods.previewSeedActor.call(ctx);
  assert.strictEqual(ctx.preview.noActor, true,
    'известно пустые назначения → noActor');
  assert.strictEqual(ctx.preview.actorValue, '');

  // Ошибка загрузки назначений: noActor не выставляется (неизвестно).
  ctx = vm({ adminsLoaded: true, adminsLoading: false,
             adminsError: { status: 503, message: 'down' } });
  methods.previewSeedActor.call(ctx);
  assert.strictEqual(ctx.preview.noActor, false,
    'adminsError ≠ «роль не назначена»');

  console.log('MOD-ACL-UX-M4C2-ADMINS-SEED-OK');
})().catch(function (e) {
  console.error(e && e.stack || e);
  process.exit(1);
});
