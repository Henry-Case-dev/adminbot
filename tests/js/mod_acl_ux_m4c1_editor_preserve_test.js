'use strict';
/* ═══ MOD-ACL-UX-01 M4C C1.2 — редактор роли: whole-object preservation ════
 * Контракт: MAC-S0-10, MAC-S8-501 (superuser read-only), MAC-S8-502.
 *
 * Проверяется РЕАЛЬНЫЙ web/app.js:
 *   1) saveRole отправляет ПОЛНЫЙ permissions: wildcard, пустые секции
 *      (access), chat_lore и неизвестные гранты не теряются;
 *   2) снятие известного узла удаляет только его, чужие гранты остаются;
 *   3) пустая секция не пересчитывается из детей (дефект 2.58.228);
 *   4) superuser — read-only, non-global — без записи;
 *   5) мутационные маркеры: без preservation-кода тест падает.
 *
 * Запуск: node tests/js/mod_acl_ux_m4c1_editor_preserve_test.js
 *         → MOD-ACL-UX-M4C1-EDITOR-PRESERVE-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');

function block(startMarker, endMarker) {
  const start = JS.indexOf(startMarker);
  assert.ok(start >= 0, 'маркер найден: ' + startMarker);
  const end = JS.indexOf(endMarker, start);
  assert.ok(end > start, 'конец блока: ' + endMarker);
  return JS.slice(start, end);
}

/* ── 1. Мутационные маркеры реализации ─────────────────────────────────── */
const apply = block('applyTree: function (tree)', '// F2 (REV-UI-D1213');
assert.ok(apply.indexOf('if (!children.length)') >= 0,
  'пустая секция обрабатывается отдельно');
assert.ok(apply.indexOf('s.checked = !!s.checked') >= 0,
  'пустая секция НЕ пересчитывается из детей');
assert.ok(apply.indexOf("id: 'chat_lore'") >= 0,
  'chat_lore добавляется из role.permissions');
const saveSrc = block('saveRole: async function', '// ═══ Статус ═══');
assert.ok(saveSrc.indexOf('Object.assign({}, raw)') >= 0,
  'whole-object: старт с полного raw permissions');
assert.ok(saveSrc.indexOf('var sections = arr(raw.sections).slice()') >= 0);
assert.ok(saveSrc.indexOf('permissions.wildcard = true') >= 0,
  'wildcard сохраняется');
assert.ok(saveSrc.indexOf('if (!this.isGlobalAdmin) return;') >= 0,
  'non-global не пишет');
assert.ok(saveSrc.indexOf('isSuperuserRole(role)') >= 0,
  'superuser не пишет');
const readOnly = block('isRoleReadOnly: function', 'roleEditDisabledReason: function');
assert.ok(readOnly.indexOf('this.isSuperuserRole(role)') >= 0,
  'superuser read-only');
assert.ok(INDEX.indexOf('data-roles-readonly') >= 0, 'read-only причина в UI');
assert.strictEqual(INDEX.indexOf('roleEditor.open'), -1,
  'редактор больше не модалка (open остаётся только состоянием)');

/* ── 2. Реальный код ───────────────────────────────────────────────────── */
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
const opts = global.__opts;
const methods = opts.methods || {};

function fixture(roleName, raw, opts2) {
  const calls = [];
  const ctx = Object.assign({}, methods, {
    isGlobalAdmin: (opts2 && opts2.global != null) ? opts2.global : true,
    roleEditor: {
      open: true, loading: false, saving: false,
      roleName: roleName, isCustom: true,
      wildcard: !!(raw && raw.wildcard),
      rawPermissions: JSON.parse(JSON.stringify(raw || {})),
      tree: null, error: null, saveError: '',
      sections: [], actions: [],
    },
    rolesList: [{
      role_name: roleName,
      is_custom: true,
      permissions: JSON.parse(JSON.stringify(raw || {})),
    }],
    newAdminRole: 'user',
    toast: function () {},
    api: async function (pathArg, req) {
      calls.push({ path: pathArg, req: req });
      const body = JSON.parse(req.body);
      return {
        role_name: body.role_name,
        permissions: body.permissions,
        is_custom: true,
      };
    },
    loadRoles: async function () { return []; },
    _roleEditorBaseline: null,
  });
  return { ctx, calls };
}

function treeOf(sectionDefs, actionDefs) {
  return {
    sections: sectionDefs.map(function (s) {
      return {
        id: s.id, title: s.title, checked: !!s.checked,
        params: (s.params || []).map(function (p) {
          return { key: p.key, title: p.title, checked: !!p.checked };
        }),
        keys: (s.keys || []).map(function (k) {
          return { key: k.key, title: k.title, checked: !!k.checked };
        }),
      };
    }),
    actions: (actionDefs || []).map(function (a) {
      return { id: a.id, title: a.title, checked: !!a.checked };
    }),
  };
}

async function save(fx) {
  await methods.saveRole.call(fx.ctx);
  assert.strictEqual(fx.calls.length, 1, 'ровно один POST /api/roles');
  const req = fx.calls[0];
  assert.strictEqual(req.path, '/api/roles');
  assert.strictEqual(req.req.method, 'POST');
  assert.strictEqual(req.req.global, true, 'глобальные ACL-вызовы без X-Chat-Id');
  const body = JSON.parse(req.req.body);
  assert.deepStrictEqual(Object.keys(body).sort(), ['permissions', 'role_name'],
    'никаких новых полей в POST');
  return body.permissions;
}

(async function () {
  /* ── 3. wildcard (custom-роль с полным доступом) ─────────────────────── */
  let fx = fixture('legacy_wild', {
    wildcard: true, sections: ['limits'],
    params: ['limits.a', 'limits.b'], keys: [], actions: ['edit_info'],
  });
  fx.ctx.applyTree(treeOf([
    { id: 'limits', title: 'Лимиты', checked: true,
      params: [{ key: 'limits.a', title: 'A', checked: true },
               { key: 'limits.b', title: 'B', checked: true }] },
    { id: 'access', title: 'Доступы', checked: false },
  ], [{ id: 'edit_info', title: 'Справка', checked: true }]));
  let perms = await save(fx);
  assert.strictEqual(perms.wildcard, true, 'wildcard сохранён');
  assert.ok(perms.sections.indexOf('limits') >= 0, 'секция сохранена');
  assert.deepStrictEqual(perms.actions, ['edit_info']);

  /* ── 4. custom-роль с section.access (пустая секция!) ────────────────── */
  fx = fixture('custom_access', {
    sections: ['access'], params: [], keys: [], actions: [],
  });
  fx.ctx.applyTree(treeOf([
    { id: 'access', title: 'Доступы', checked: true },
  ]));
  const accessSection = fx.ctx.roleEditor.sections.find(function (s) {
    return s.id === 'access';
  });
  assert.strictEqual(accessSection.checked, true,
    'applyTree НЕ сбрасывает пустую section.access из детей');
  perms = await save(fx);
  assert.deepStrictEqual(perms.sections, ['access'],
    'section.access не потерян');
  assert.ok(perms.params.indexOf('limits.a') < 0);

  /* ── 5. local_admin: chat_lore из role.permissions, не из tree ───────── */
  fx = fixture('local_admin', {
    sections: ['prompts', 'limits', 'chat_lore'],
    params: [], keys: [], actions: [],
  });
  fx.ctx.applyTree(treeOf([
    { id: 'prompts', title: 'Промпты', checked: true,
      params: [{ key: 'prompts.a', title: 'A', checked: true }] },
    { id: 'limits', title: 'Лимиты', checked: true,
      params: [{ key: 'limits.a', title: 'A', checked: true }] },
    { id: 'access', title: 'Доступы', checked: false },
  ]));
  const chatLore = fx.ctx.roleEditor.sections.find(function (s) {
    return s.id === 'chat_lore';
  });
  assert.ok(chatLore, 'chat_lore добавлена из permissions');
  assert.strictEqual(chatLore.checked, true, 'chat_lore отмечена');
  perms = await save(fx);
  assert.ok(perms.sections.indexOf('chat_lore') >= 0, 'chat_lore не потерян');
  assert.ok(perms.sections.indexOf('prompts') >= 0);
  assert.ok(perms.sections.indexOf('limits') >= 0);

  /* ── 6. Неизвестные гранты и верхнеуровневые ключи сохраняются ───────── */
  fx = fixture('future_role', {
    sections: ['future_section'], params: ['future.param'],
    keys: ['future.key'], actions: ['future.action'],
    page_permissions: { access_page: true },
    custom_meta: { note: 'keep-me' },
  });
  fx.ctx.applyTree(treeOf([
    { id: 'access', title: 'Доступы', checked: false },
  ]));
  perms = await save(fx);
  assert.deepStrictEqual(perms.sections, ['future_section']);
  assert.deepStrictEqual(perms.params, ['future.param']);
  assert.deepStrictEqual(perms.keys, ['future.key']);
  assert.deepStrictEqual(perms.actions, ['future.action']);
  assert.deepStrictEqual(perms.page_permissions, { access_page: true },
    'неизвестный верхнеуровневый grant сохранён');
  assert.deepStrictEqual(perms.custom_meta, { note: 'keep-me' });

  /* ── 7. Снятие известного узла удаляет только его ────────────────────── */
  fx = fixture('node_uncheck', {
    sections: ['limits'], params: ['limits.a', 'limits.b'],
    keys: ['keys.groq_api_key'], actions: ['edit_info'],
  });
  fx.ctx.applyTree(treeOf([
    { id: 'limits', title: 'Лимиты', checked: true,
      params: [{ key: 'limits.a', title: 'A', checked: true },
               { key: 'limits.b', title: 'B', checked: true }] },
  ], [{ id: 'edit_info', title: 'Справка', checked: true }]));
  const section = fx.ctx.roleEditor.sections.find(function (s) {
    return s.id === 'limits';
  });
  const nodeB = section.params.find(function (p) { return p.key === 'limits.b'; });
  fx.ctx.toggleNode(nodeB);
  perms = await save(fx);
  assert.ok(perms.sections.indexOf('limits') < 0, 'секция снята (частичный чек)');
  assert.ok(perms.params.indexOf('limits.a') >= 0, 'остальные параметры остались');
  assert.ok(perms.params.indexOf('limits.b') < 0, 'снятый узел удалён');
  assert.deepStrictEqual(perms.keys, ['keys.groq_api_key'],
    'чужая группа ключей не тронута');

  /* ── 8. Пустую секцию можно включить чекбоксом ───────────────────────── */
  fx = fixture('empty_toggle', { sections: [], params: [], keys: [], actions: [] });
  fx.ctx.applyTree(treeOf([
    { id: 'access', title: 'Доступы', checked: false },
  ]));
  const acc = fx.ctx.roleEditor.sections.find(function (s) { return s.id === 'access'; });
  fx.ctx.toggleSection(acc);
  assert.strictEqual(acc.checked, true);
  perms = await save(fx);
  assert.deepStrictEqual(perms.sections, ['access'], 'чекбокс пустой секции работает');

  /* ── 9. Superuser read-only: saveRole не делает запрос ────────────────── */
  fx = fixture('admin', { wildcard: true, sections: [], params: [], keys: [], actions: [] });
  fx.ctx.applyTree(treeOf([]));
  assert.strictEqual(methods.isRoleReadOnly.call(fx.ctx,
    { role_name: 'admin', permissions: { wildcard: true } }), true);
  await methods.saveRole.call(fx.ctx);
  assert.strictEqual(fx.calls.length, 0, 'superuser не сохраняется');

  /* ── 10. Non-global read-only: saveRole не делает запрос ─────────────── */
  fx = fixture('custom_ro', { sections: ['limits'], params: [], keys: [], actions: [] },
    { global: false });
  fx.ctx.applyTree(treeOf([
    { id: 'limits', title: 'Лимиты', checked: true,
      params: [{ key: 'limits.a', title: 'A', checked: true }] },
  ]));
  await methods.saveRole.call(fx.ctx);
  assert.strictEqual(fx.calls.length, 0, 'non-global не пишет');
  assert.strictEqual(methods.isRoleReadOnly.call(fx.ctx,
    { role_name: 'custom_ro', is_custom: true }), true);

  /* ── 11. 409/503 не теряют правки (saveError, baseline не сброшен) ───── */
  fx = fixture('custom_err', { sections: [], params: [], keys: [], actions: [] });
  fx.ctx.applyTree(treeOf([]));
  fx.ctx._roleEditorBaseline = fx.ctx._roleEditorSnapshot();
  fx.ctx.api = async function () {
    const err = new Error('нельзя удалить последнего админа');
    err.status = 409;
    throw err;
  };
  await methods.saveRole.call(fx.ctx);
  assert.ok(fx.ctx.roleEditor.saveError.indexOf('409') >= 0
    || fx.ctx.roleEditor.saveError.indexOf('последнего') >= 0,
    'причина 409 показана');
  assert.ok(Array.isArray(fx.ctx.roleEditor.sections), 'edits не потеряны');

  console.log('MOD-ACL-UX-M4C1-EDITOR-PRESERVE-OK');
})().catch(function (e) {
  console.error(e);
  process.exit(1);
});
