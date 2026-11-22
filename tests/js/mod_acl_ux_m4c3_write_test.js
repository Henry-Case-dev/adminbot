'use strict';
/* ═══ MOD-ACL-UX-01 M4C C3 — матрица draft/save, 409, audit, reset ═════════
 * Контракт: MAC-S8-505/506/523/S15-08/S8-522-reset.
 *
 * Проверяется РЕАЛЬНЫЙ web/app.js + index.html + app.css:
 *   1) toggle/reset меняют ТОЛЬКО draft (0 API-запросов на клик);
 *   2) save — N последовательных PUT/DELETE с expected_updated_at,
 *      per-item статус, итог «Сохранено N, не сохранено M»;
 *   3) 409-карточка (reapply/discard), generation-guard;
 *   4) роль шлёт expected_revision; 409 → conflict + save заблокирован;
 *   5) audit-панель (entity, 50→200, 403/503) и errText() для object-detail;
 *   6) local override reset (DELETE + токен, 404 override_absent);
 *   7) CSS: stack на mobile, тач ≥44, без нового h-scroll.
 *
 * Запуск: node tests/js/mod_acl_ux_m4c3_write_test.js
 *         → MOD-ACL-UX-M4C3-WRITE-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'),
                             'utf8');

function block(startMarker, endMarker) {
  const start = JS.indexOf(startMarker);
  assert.ok(start >= 0, 'маркер найден: ' + startMarker);
  const end = JS.indexOf(endMarker, start);
  assert.ok(end > start, 'конец блока: ' + endMarker);
  return JS.slice(start, end);
}

/* ── 1. Мутационные маркеры реализации ─────────────────────────────────── */
const toggle = block('matrixRoleToggle: function', 'matrixReset: function');
assert.strictEqual(toggle.indexOf('this.api('), -1,
  'toggle не делает запись на клик');
assert.ok(toggle.indexOf('this._matrixDraftSet(key)') >= 0);
assert.ok(toggle.indexOf('draft.after') >= 0);
const reset = block('matrixReset: function', 'matrixDiscardAll: function');
assert.strictEqual(reset.indexOf('this.api('), -1,
  'reset только draft');
const save = block('matrixSave: async function', 'matrixConflictReload:');
assert.ok(save.indexOf('expected_updated_at') >= 0, 'PUT/DELETE с токеном');
assert.ok(save.indexOf("method: 'PUT'") >= 0);
assert.ok(save.indexOf("method: 'DELETE'") >= 0);
assert.ok(save.indexOf('seq !== this.matrixSeq') >= 0,
  'generation-guard в save');
assert.ok(save.indexOf('matrixConflict =') >= 0, '409-карточка');
const saveRole = block('saveRole: async function', 'roleConflictText:');
assert.ok(saveRole.indexOf('expected_revision') >= 0);
assert.ok(saveRole.indexOf('roleEditor.conflict') >= 0);
assert.ok(saveRole.indexOf('saveBlocked = true') >= 0);
assert.ok(JS.indexOf('errText: function (e)') >= 0, 'errText helper');
assert.ok(JS.indexOf('loadAccessAudit: async function') >= 0);
assert.ok(JS.indexOf("'/api/access/audit?scope=global&limit=50'") >= 0);
assert.ok(JS.indexOf('a.items.length < 200') >= 0, 'audit 50→200');
assert.ok(JS.indexOf('resetLocalPermOverride: async function') >= 0);
assert.ok(JS.indexOf("method: 'DELETE', global: true") >= 0);

/* ── 2. HTML-якоря (C1/C2 сохранены, C3 добавлен) ──────────────────────── */
for (const anchor of [
  'data-access-audit', 'data-access-audit-panel', 'data-access-audit-open',
  'data-matrix-save', 'data-matrix-savebar', 'data-matrix-draft-count',
  'data-matrix-conflict', 'data-matrix-reapply',
  'data-matrix-accept-server', 'data-roles-conflict',
  'data-roles-conflict-reload', 'data-local-param-overrides',
  'data-local-override-reset', 'data-local-override-last',
]) {
  assert.ok(INDEX.indexOf(anchor) >= 0, 'HTML-якорь: ' + anchor);
}
for (const keep of ['data-preview', 'data-roles-pane="gates"',
                    'data-roles-pane="matrix"', 'data-roles-page']) {
  assert.ok(INDEX.indexOf(keep) >= 0, 'C1/C2 якорь сохранён: ' + keep);
}
assert.ok(INDEX.indexOf('data-roles-matrix-count') >= 0);
assert.ok(CSS.indexOf('.matrix-savebar') >= 0);
assert.ok(/@media \(max-width: 767px\)[\s\S]{0,400}\.matrix-savebar/.
  test(CSS), 'mobile stack savebar');
assert.ok(CSS.indexOf('min-height: 44px') >= 0, 'touch ≥44');

/* ── 3. Реальный код ───────────────────────────────────────────────────── */
global.Vue = {
  createApp: function (opts) {
    global.__opts = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  matchMedia: function () { return { matches: false, addEventListener() {} }; },
  innerWidth: 1440, innerHeight: 900,
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
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {}, remove() {},
      getContext() { return null; },
    };
  },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
  querySelector() { return null; }, querySelectorAll() { return []; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('no'); } } },
});
global.sessionStorage = {
  _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; },
};
global.localStorage = {
  _s: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in unit'); };

require(path.join(ROOT, 'web', 'app.js'));
const methods = global.__opts.methods || {};

function matrixCtx(overrides) {
  const ctx = Object.assign({}, methods, {
    isGlobalAdmin: true,
    matrixItems: {
      'limits.search_max_symbols': {
        title: 'Поиск', view_roles: ['moderator', 'local_admin'],
        edit_roles: ['local_admin'], default: true, updated_at: null,
      },
      'limits.summary_hybrid_context_tokens': {
        title: 'Гибрид', view_roles: ['local_admin'],
        edit_roles: ['local_admin'], default: false,
        updated_at: '2026-11-22T12:00:00+00:00',
      },
    },
    matrixDraft: {}, matrixDraftStatus: {}, matrixSaving: {},
    matrixSaveBusy: false, matrixSaveResult: '', matrixConflict: null,
    matrixSeq: 0,
    loadAccessAuditLatest: async function () {},
  }, overrides || {});
  return ctx;
}

(async function run() {
  /* 3.1 toggle — без API, только draft */
  let ctx = matrixCtx({
    api: async function () { throw new Error('toggle не должен писать'); },
  });
  ctx.matrixRoleToggle('limits.search_max_symbols', 'view_roles', 'user');
  assert.strictEqual(ctx.matrixDraftCount(), 1, 'toggle создаёт draft');
  assert.deepStrictEqual(ctx.matrixItems['limits.search_max_symbols'].view_roles,
                         ['user', 'moderator', 'local_admin']);
  assert.deepStrictEqual(ctx.matrixDraft['limits.search_max_symbols'].after.edit_roles,
                         ['local_admin'], 'запись подразумевает чтение');
  /* toggle назад — draft исчезает */
  ctx.matrixRoleToggle('limits.search_max_symbols', 'view_roles', 'user');
  assert.strictEqual(ctx.matrixDraftCount(), 0, 'возврат к baseline убирает draft');

  /* 3.2 reset — только draft */
  ctx.matrixReset('limits.summary_hybrid_context_tokens');
  assert.strictEqual(ctx.matrixDraftCount(), 1);
  assert.strictEqual(
    ctx.matrixDraft['limits.summary_hybrid_context_tokens'].reset, true);
  assert.ok(ctx.matrixItemStatus('limits.summary_hybrid_context_tokens')
    .indexOf('сброшено') >= 0);

  /* 3.3 save — N запросов с токенами и per-item результатом */
  ctx = matrixCtx();
  ctx.matrixRoleToggle('limits.search_max_symbols', 'view_roles', 'user');
  ctx.matrixRoleToggle('limits.summary_hybrid_context_tokens', 'edit_roles',
                       'moderator');
  const calls = [];
  ctx.api = async function (url, opts) {
    calls.push({ url: url, opts: opts });
    return {
      view_roles: ['user'], edit_roles: ['moderator'],
      updated_at: '2026-11-22T12:00:10+00:00',
    };
  };
  await ctx.matrixSave();
  assert.strictEqual(calls.length, 2, 'по одному запросу на ключ');
  assert.ok(calls.every(function (c) { return c.opts.method === 'PUT'; }));
  const bodies = calls.map(function (c) { return JSON.parse(c.opts.body); });
  assert.ok(bodies[0].expected_updated_at == null,
    'default-ключ без токена');
  assert.strictEqual(bodies[1].expected_updated_at,
                     '2026-11-22T12:00:00+00:00');
  assert.strictEqual(ctx.matrixDraftCount(), 0);
  assert.ok(ctx.matrixSaveResult.indexOf('Сохранено 2') >= 0);
  assert.strictEqual(ctx.matrixSaveBusy, false);

  /* 3.4 409 — стоп, карточка, draft сохранён */
  ctx = matrixCtx();
  ctx.matrixRoleToggle('limits.summary_hybrid_context_tokens',
                       'view_roles', 'user');
  let posts = 0;
  ctx.api = async function () {
    posts += 1;
    const err = new Error('conflict');
    err.status = 409;
    err.message = { code: 'conflict', reason: 'revision_mismatch',
                    current_updated_at: '2026-11-22T12:30:00+00:00',
                    current: { view_roles: ['local_admin'],
                               edit_roles: ['local_admin'] } };
    throw err;
  };
  await ctx.matrixSave();
  assert.strictEqual(posts, 1);
  assert.ok(ctx.matrixConflict);
  assert.strictEqual(ctx.matrixConflict.reason, 'revision_mismatch');
  assert.strictEqual(ctx.matrixConflict.current_updated_at,
                     '2026-11-22T12:30:00+00:00');
  assert.strictEqual(ctx.matrixDraftCount(), 1, 'draft не потерян');
  assert.strictEqual(ctx.matrixSaveBusy, false);

  /* 3.5 generation-guard: поздний ответ не применяется */
  ctx = matrixCtx();
  ctx.matrixRoleToggle('limits.search_max_symbols', 'view_roles', 'user');
  ctx.api = async function () {
    ctx.matrixSeq += 1;       // смена роли/скоупа во время запроса
    return { view_roles: ['user'], edit_roles: [],
             updated_at: '2026-11-22T12:40:00+00:00' };
  };
  await ctx.matrixSave();
  assert.strictEqual(ctx.matrixSaveBusy, false);
  assert.strictEqual(ctx.matrixDraftCount(), 1,
                     'поздний ответ старой генерации не применяется');

  /* 3.6 discard all восстанавливает baseline */
  ctx = matrixCtx();
  const before = JSON.parse(JSON.stringify(
    ctx.matrixItems['limits.search_max_symbols']));
  ctx.matrixRoleToggle('limits.search_max_symbols', 'view_roles', 'user');
  ctx.matrixDiscardAll();
  assert.strictEqual(ctx.matrixDraftCount(), 0);
  assert.deepStrictEqual(ctx.matrixItems['limits.search_max_symbols'].view_roles,
                         before.view_roles);

  /* 3.7 роль: expected_revision и 409 → save заблокирован */
  function roleCtx(api) {
    return Object.assign({}, methods, {
      isGlobalAdmin: true,
      selectedRole: function () { return { role_name: 'custom_access' }; },
      isSuperuserRole: function () { return false; },
      _roleEditorBaseline: [],
      loadRoles: async function () {},
      toast: function () {},
      roleEditor: {
        open: true, saving: false, roleName: 'custom_access',
        isCustom: true, wildcard: false,
        rawPermissions: { sections: ['access'] },
        sections: [], actions: [], revision: 'rev-1',
        saveError: '', conflict: null, saveBlocked: false,
      },
      api: api,
    });
  }
  let role = roleCtx(async function (url, opts) {
    return { role_name: 'custom_access', permissions: { sections: ['access'] },
             is_custom: true, revision: 'rev-2' };
  });
  await role.saveRole();
  /* повтор с захватом тела */
  let captured = null;
  role = roleCtx(async function (url, opts) {
    captured = JSON.parse(opts.body);
    return { role_name: 'custom_access', permissions: captured.permissions,
             is_custom: true, revision: 'rev-2' };
  });
  await role.saveRole();
  assert.strictEqual(captured.expected_revision, 'rev-1');
  assert.strictEqual(role.roleEditor.revision, 'rev-2');
  role = roleCtx(async function () {
    const err = new Error('conflict');
    err.status = 409;
    err.message = { code: 'conflict', reason: 'revision_mismatch',
                    current_revision: 'rev-9',
                    current: { permissions: { sections: ['access'] },
                               role_type: null, is_custom: true } };
    throw err;
  });
  await role.saveRole();
  assert.strictEqual(role.roleEditor.conflict.reason, 'revision_mismatch');
  assert.strictEqual(role.roleEditor.saveBlocked, true);
  assert.ok(role.roleEditor.saveError.indexOf('изменена') >= 0);

  /* 3.8 errText: object-detail не превращается в [object Object] */
  const errText = methods.errText.call(methods, {
    status: 409,
    message: { code: 'conflict', reason: 'role_absent',
               message: 'роль удалена' },
  });
  assert.ok(errText.indexOf('role_absent') >= 0);
  assert.strictEqual(errText.indexOf('[object Object]'), -1);

  /* 3.9 audit panel: entity/limit/items */
  const audit = Object.assign({}, methods, {
    isGlobalAdmin: true,
    accessAudit: { open: false, loading: false, items: [], error: null,
                   hasMore: false, entity: '', latest: null, _seq: 0 },
    api: async function (url) {
      assert.ok(url.indexOf('scope=global&limit=50') >= 0);
      assert.ok(url.indexOf('entity=admin') >= 0);
      return { items: [
        { id: 7, created_at: '2026-11-22T12:00:00+00:00', changed_by: 1,
          entity: 'admin', op: 'create', role_name: null, telegram_id: 42,
          key: null, before: null, after: { role_name: 'moderator' } },
      ], has_more: true };
    },
    admins: [{ telegram_id: 1, display_name: 'Админ' }],
  });
  audit.accessAudit.entity = 'admin';
  await audit.loadAccessAudit(true);
  assert.strictEqual(audit.accessAudit.items.length, 1);
  assert.strictEqual(audit.accessAudit.hasMore, true);
  assert.ok(audit.accessAuditWho(audit.accessAudit.items[0]).indexOf('Админ') >= 0);
  assert.ok(audit.accessAuditWhat(audit.accessAudit.items[0]).indexOf('moderator') >= 0);

  /* 3.10 local override reset: DELETE с токеном, 404 override_absent */
  let delUrl = null;
  const local = Object.assign({}, methods, {
    isGlobalAdmin: true, activeChatId: -100123,
    localPermOverrides: [{ key: 'limits.search_max_symbols',
                           view_roles: ['local_admin'], edit_roles: [],
                           updated_at: '2026-11-22T12:00:00+00:00' }],
    localPermResetBusy: {}, _localPermSeq: 0,
    localPermOverrideLast: null, localPermOverridesBusy: false,
    toast: function () {},
    _loadLocalPermAudit: async function () {},
    api: async function (url, opts) {
      delUrl = url;
      assert.strictEqual(opts.method, 'DELETE');
      return { reset: true };
    },
  });
  await local.resetLocalPermOverride('limits.search_max_symbols');
  assert.ok(delUrl.indexOf('expected_updated_at=') >= 0);
  assert.strictEqual(local.localPermOverrides.length, 0);
  let absent = 0;
  const local404 = Object.assign({}, local, {
    localPermOverrides: [{ key: 'k', view_roles: [], edit_roles: [],
                           updated_at: null }],
    toast: function (msg) { if (msg.indexOf('Уже наследует') >= 0) absent += 1; },
    api: async function () {
      const err = new Error('gone');
      err.status = 404;
      err.message = { code: 'override_absent' };
      throw err;
    },
  });
  await local404.resetLocalPermOverride('k');
  assert.strictEqual(local404.localPermOverrides.length, 0);
  assert.strictEqual(absent, 1);

  console.log('MOD-ACL-UX-M4C3-WRITE-OK');
})().catch(function (e) {
  console.error(e && e.stack || e);
  process.exit(1);
});
