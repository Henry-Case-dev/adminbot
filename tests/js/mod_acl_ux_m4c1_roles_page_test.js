'use strict';
/* ═══ MOD-ACL-UX-01 M4C C1.1 — страница «Роли и права» ═════════════════════
 * Контракт: MAC-S0-10, MAC-S4-174/175, MAC-S5-293, MAC-S5-294, MAC-S8-501,
 * MAC-S8-502, MAC-S8-504, MAC-S8-521, MAC-S8-PAGE-01/02, MAC-S8-LAY-01,
 * MAC-S8-SEC-01 (UI-часть), MAC-S15-1-08.
 *
 * Проверяется РЕАЛЬНЫЙ код web/app.js + web/index.html + app.css:
 *   1) #/access/roles — самостоятельная страница (data-roles-page), не модалка;
 *      якоря #acc-roles-title/#sec-roles/#sec-matrix сохранены;
 *   2) desktop-сетка ролей 220–280 px; mobile switcher/⋯; нет второго скролла;
 *   3) дерево Раздел→Модуль→Группа→Параметр, владелец — из _f4Registry;
 *      поиск RU+key/group/module/nav; 0 сетевых запросов на символ;
 *   4) честные 401/403/404/503 (403 ≠ пустая БД) и count из данных;
 *   5) superuser/read-only политика (UI) и mobile-переключатель группы.
 *
 * Запуск: node tests/js/mod_acl_ux_m4c1_roles_page_test.js
 *         → MOD-ACL-UX-M4C1-ROLES-PAGE-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

/* ── 1. Страница, а не модалка; якоря сохранены ─────────────────────────── */
assert.ok(INDEX.indexOf('data-roles-page') >= 0, 'roles page marker');
assert.strictEqual(INDEX.indexOf("isAccessOpen('roles')"), -1,
  'roles больше не открываются как modal-backdrop');
assert.ok(INDEX.indexOf('id="acc-roles-title"') >= 0, 'заголовок сохранён');
assert.strictEqual(INDEX.split('id="acc-roles-title"').length - 1, 1,
  'ровно один заголовок страницы');
assert.ok(INDEX.indexOf('id="sec-roles"') >= 0, 'якорь sec-roles');
assert.ok(INDEX.indexOf('id="sec-matrix"') >= 0, 'якорь sec-matrix');
assert.ok(INDEX.indexOf('data-roles-tabs') >= 0, 'вкладки зон');
const rolesStart = INDEX.indexOf('data-roles-page');
const rolesEnd = INDEX.indexOf('<!-- Окно «Локальные админы»', rolesStart);
const PAGE = INDEX.slice(rolesStart, rolesEnd);
assert.strictEqual(PAGE.split('class="modal-backdrop"').length - 1, 0,
  'внутри страницы ролей нет modal-backdrop');
for (const tab of ['rights', 'matrix', 'gates']) {
  assert.ok(PAGE.indexOf('data-roles-pane="' + tab + '"') >= 0,
    'зона ' + tab);
}
assert.ok(PAGE.indexOf('data-roles-mobile-switch') >= 0, 'mobile switcher');
assert.ok(PAGE.indexOf('data-roles-actions') >= 0, 'mobile ⋯');
assert.ok(PAGE.indexOf('data-roles-back') >= 0, 'Back в шапке');
assert.ok(PAGE.indexOf('data-roles-aside') >= 0 && PAGE.indexOf('data-roles-main') >= 0,
  'роли слева, дерево справа');
assert.ok(PAGE.indexOf('Назад в Доступы') >= 0, 'явный Back');
assert.ok(PAGE.indexOf('Фактические гейты') >= 0, 'read-only гейты');
assert.ok(PAGE.indexOf('data-access-audit') >= 0, 'аудит матрицы сохранён');
assert.ok(PAGE.indexOf('data-roles-matrix-error') >= 0, 'карточка 503 матрицы');
assert.ok(PAGE.indexOf('data-roles-error') >= 0, 'карточка 401/403 ролей');
assert.ok(PAGE.indexOf('data-roles-tree-error') >= 0, 'карточка 404/403 дерева');

/* ── 2. Layout/scroll: 220–280 px, один основной scroll ─────────────────── */
assert.ok(/\.roles-page__grid \{[\s\S]{0,220}grid-template-columns:\s*clamp\(220px,\s*22vw,\s*280px\)\s+minmax\(0,\s*1fr\)/
  .test(CSS), 'desktop: роли clamp(220–280) + pane');
assert.ok(/@media \(min-width: 768px\) and \(max-width: 1199px\) \{[\s\S]{0,160}\.roles-page__grid \{ grid-template-columns: 220px minmax\(0, 1fr\)/
  .test(CSS), 'tablet: роли 220 px');
assert.ok(/@media \(max-width: 767px\) \{[\s\S]{0,300}\.roles-page__aside \{ display: none; \}/
  .test(CSS), 'mobile: список ролей заменён switcher');
assert.ok(/@media \(max-width: 767px\) \{[\s\S]{0,400}\.roles-page__mobile-switch \{ display: flex; \}/
  .test(CSS), 'mobile switcher виден');
assert.ok(/@media \(max-width: 767px\) \{[\s\S]{0,260}\.roles-tab \{ min-height: 44px; \}/
  .test(CSS), 'mobile: тач-цель вкладок 44');
assert.ok(/\.roles-page__main \{[^}]*min-width: 0/.test(CSS),
  'pane участвует в minmax(0,1fr) без h-overflow');
assert.ok(INDEX.indexOf('class="modal-body"') >= 0, 'существующие модалки не тронуты');
assert.strictEqual(PAGE.indexOf('class="modal-body"'), -1,
  'страница ролей не использует modal-body (нет вложенного скролла)');
assert.strictEqual(PAGE.indexOf('max-h-[85vh]'), -1,
  'страница ролей не ограничена высотой модалки');
assert.ok(CSS.indexOf('.roles-tree__group') >= 0, 'progressive disclosure групп');

/* ── 3. Реальный app.js ─────────────────────────────────────────────────── */
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
let fetchCalls = 0;
global.fetch = async function () { fetchCalls += 1; throw new Error('no fetch'); };

require(path.join(ROOT, 'web', 'app.js'));
const opts = global.__opts;
const methods = opts.methods || {};
function vm(extra) {
  // Vue-компонент вызывает методы через this; в юните собираем тот же
  // контракт (все методы доступны как this.<method>).
  return Object.assign({}, methods, extra || {});
}
['matrixTree', 'matrixOwnerIndex', 'matrixOwnerFor', 'matrixOwnerLabel',
 'matrixVisibleCount', 'matrixTotalCount', 'matrixGroupOpen',
 'onMatrixGroupToggle', 'matrixSearchActive', 'roleSectionVisible',
 'roleSectionParams', 'roleSectionKeys', 'roleActionVisible',
 'roleSearchEmpty', 'accessErrorTitle', 'accessErrorHint',
 'accessErrorPayload', 'gatesList', '_autoSelectRole', '_ensureRolesPage',
 'rolesPageTabs', 'selectedRole', 'roleUsageCount', 'rolesCounterText',
 'matrixCounterText', 'canDeleteRole', 'roleDeleteHint',
 'roleDeleteBlockedReason', 'retryRolesList'].forEach(
  function (name) {
    assert.strictEqual(typeof methods[name], 'function', 'method ' + name);
  });

/* ── 4. Дерево nav→module→group→param и владельцы ──────────────────────── */
const items = {
  'limits.search_max_symbols': {
    title: 'Максимум символов поиска', group: 'limits_search',
    group_title: 'Поиск', group_order: 2, nav: 'modules',
    nav_title: 'Модули', nav_order: 0, tab: 'mod_search',
    tab_title: 'Поиск', default: true, view_roles: ['moderator', 'local_admin'],
    edit_roles: ['local_admin'],
  },
  'limits.chat_cooldown_seconds': {
    title: 'Кулдаун', group: 'limits_search', group_title: 'Поиск',
    group_order: 2, nav: 'modules', nav_title: 'Модули', nav_order: 0,
    tab: 'mod_search', tab_title: 'Поиск', default: true,
    view_roles: [], edit_roles: [],
  },
  'prompts.summary_system_prompt': {
    title: 'Системный промпт', group: 'prompts_summary',
    group_title: 'Саммари', group_order: 1, nav: 'ai', nav_title: 'ИИ',
    nav_order: 1, tab: 'prompts', tab_title: 'Промпты', default: true,
    view_roles: [], edit_roles: [],
  },
  'keys.groq_api_key': {
    title: 'Groq ключ', group: 'keys_groq', group_title: 'Ключи Groq',
    group_order: 3, nav: null, nav_title: null, nav_order: 999,
    tab: 'llm_providers', tab_title: 'LLM', default: true,
    secret: true, view_roles: [], edit_roles: [],
  },
};
const ctx = vm({
  matrixItems: items,
  matrixSearch: '',
  matrixGroupState: {},
  _f4Registry: {
    search: { title: 'Поиск', settings_groups: ['limits_search'], model_slots: [] },
    summary: { title: 'Саммари', settings_groups: ['prompts_summary'], model_slots: [] },
    groq: { title: 'Groq', settings_groups: [], model_slots: ['keys_groq'] },
  },
  isGlobalAdmin: true,
});
assert.strictEqual(methods.matrixOwnerLabel.call(ctx, 'limits_search'), 'Поиск');
assert.strictEqual(methods.matrixOwnerLabel.call(ctx, 'keys_groq'), 'Groq',
  'model_slots тоже дают владельца');
assert.strictEqual(methods.matrixOwnerLabel.call(ctx, 'unknown_group'),
  'Общее / инфраструктура');
assert.strictEqual(methods.matrixTotalCount.call(ctx), 4);

let tree = methods.matrixTree.call(ctx);
assert.strictEqual(methods.matrixVisibleCount.call(ctx, tree), 4, 'все пункты');
assert.deepStrictEqual(tree.map(function (n) { return n.id; }), ['modules', 'ai', 'other'],
  'nav-порядок: Модули → ИИ → Прочее');
assert.deepStrictEqual(tree[0].modules.map(function (m) { return m.title; }),
  ['Поиск'], 'модуль-владелец группы');
assert.deepStrictEqual(tree[2].modules.map(function (m) { return m.title; }),
  ['Groq'], 'ключи — через model_slots');
assert.strictEqual(tree[0].modules[0].groups[0].items.length, 2, 'группа параметров');
assert.strictEqual(tree[0].modules[0].groups[0].ownerLabel, 'Поиск');
assert.strictEqual(fetchCalls, 0, 'построение дерева не делает запросов');

/* Поиск: key/title/group/module/nav — 0 запросов на символ. */
const probes = [
  ['search_max', 1], ['Максимум', 1], ['Поиск', 2], ['Саммари', 1],
  ['keys_groq', 1], ['Модули', 2], ['НИЧЕГО-НЕТ', 0],
];
probes.forEach(function (probe) {
  ctx.matrixSearch = probe[0];
  const t = methods.matrixTree.call(ctx);
  assert.strictEqual(methods.matrixVisibleCount.call(ctx, t), probe[1],
    'поиск "' + probe[0] + '"');
});
ctx.matrixSearch = '';
assert.strictEqual(fetchCalls, 0, '0 запросов на ввод символа');

/* Collapsed by default; поиск раскрывает; mobile — ровно одна группа. */
const uidA = 'modules|search|limits_search';
const uidB = 'ai|summary|prompts_summary';
assert.strictEqual(methods.matrixGroupOpen.call(ctx, uidA), false,
  'группы свёрнуты по умолчанию');
ctx.matrixSearch = 'Максимум';
assert.strictEqual(methods.matrixGroupOpen.call(ctx, uidA), true,
  'при поиске совпавшая группа раскрыта');
ctx.matrixSearch = '';
ctx.matrixGroupState[uidA] = true;
ctx.matrixGroupState[uidB] = true;
global.window.innerWidth = 390;
methods.onMatrixGroupToggle.call(ctx, uidB, { target: { open: true } });
assert.strictEqual(ctx.matrixGroupState[uidB], true);
assert.strictEqual(ctx.matrixGroupState[uidA], false,
  'mobile: раскрыта ровно одна группа');
global.window.innerWidth = 1440;
ctx.matrixGroupState[uidA] = true;
ctx.matrixGroupState[uidB] = true;
methods.onMatrixGroupToggle.call(ctx, uidB, { target: { open: true } });
assert.strictEqual(ctx.matrixGroupState[uidA], true,
  'desktop: несколько групп могут быть раскрыты');
ctx.matrixGroupState = {};

/* ── 5. Честные состояния 401/403/404/503 ≠ пустая БД ───────────────────── */
assert.strictEqual(methods.accessErrorTitle(401), 'Сессия устарела');
assert.strictEqual(methods.accessErrorTitle(403), 'Нет доступа');
assert.strictEqual(methods.accessErrorTitle(404), 'Не найдено');
assert.strictEqual(methods.accessErrorTitle(503), 'Сервис временно недоступен');
assert.notStrictEqual(methods.accessErrorTitle(403), methods.accessErrorTitle(503));
assert.ok(methods.accessErrorHint(403, 'roles').indexOf('не означает, что база пуста') >= 0,
  '403 не выдаётся за пустой список');
assert.ok(methods.accessErrorHint(503, 'matrix').indexOf('Дефолтная') >= 0,
  '503 матрицы не подставляет дефолт');
assert.ok(methods.accessErrorHint(404, 'tree').indexOf('Обновите') >= 0);
const payload = methods.accessErrorPayload.call({}, { status: 503, message: 'x' });
assert.deepStrictEqual(payload, { status: 503, message: 'x' });
assert.strictEqual(methods.accessErrorPayload.call({}, new Error('net')).status, 0);
assert.ok(INDEX.indexOf('data-roles-empty') >= 0, 'честное 200 []');
assert.ok(INDEX.indexOf('data-roles-matrix-empty') >= 0, 'честная пустая матрица');

/* ── 5b. F01: счётчики только из успешных данных ────────────────────────── */
const counterCtx = vm({
  isGlobalAdmin: true,
  rolesLoading: false, rolesError: null, rolesList: [{}, {}, {}, {}],
  matrixItems: items, matrixSearch: '', matrixLoading: false,
  matrixErrorStatus: 0,
  _f4Registry: ctx._f4Registry,
});
assert.strictEqual(methods.rolesCounterText.call(counterCtx), '4');
assert.strictEqual(methods.matrixCounterText.call(counterCtx), '4 из 4');
counterCtx.rolesLoading = true;
assert.strictEqual(methods.rolesCounterText.call(counterCtx), '…');
counterCtx.rolesLoading = false;
counterCtx.rolesError = { status: 403, message: 'denied' };
assert.strictEqual(methods.rolesCounterText.call(counterCtx), '',
  'F01: 403 не показывает РОЛИ 0');
counterCtx.rolesError = { status: 503, message: 'down' };
assert.strictEqual(methods.rolesCounterText.call(counterCtx), '',
  'F01: 503 не показывает РОЛИ 0');
counterCtx.matrixLoading = true;
assert.strictEqual(methods.matrixCounterText.call(counterCtx), '…');
counterCtx.matrixLoading = false;
counterCtx.matrixErrorStatus = 503;
assert.strictEqual(methods.matrixCounterText.call(counterCtx), '',
  'F01: 503 не показывает 0 из 0');
counterCtx.matrixErrorStatus = 403;
assert.strictEqual(methods.matrixCounterText.call(counterCtx), '',
  'F01: 403 не показывает 0 из 0');
counterCtx.matrixErrorStatus = 0;
counterCtx.isGlobalAdmin = false;
assert.strictEqual(methods.matrixCounterText.call(counterCtx), '',
  'F01: non-global не получает числовой counter');
assert.ok(INDEX.indexOf('data-roles-count') >= 0);
assert.ok(INDEX.indexOf('data-roles-matrix-count') >= 0);
assert.ok(INDEX.indexOf('matrixCounterText()') >= 0);
assert.ok(INDEX.indexOf('rolesCounterText()') >= 0);

/* ── 6. Поиск в правах роли ─────────────────────────────────────────────── */
const roleCtx = vm({
  roleSearch: '',
  roleEditor: {
    sections: [
      { id: 'limits', title: 'Лимиты', checked: true, indeterminate: false,
        params: [{ key: 'limits.a', title: 'Первый' },
                 { key: 'limits.b', title: 'Второй' }],
        keys: [] },
      { id: 'access', title: 'Доступы', checked: true, indeterminate: false,
        params: [], keys: [], service: true },
    ],
    actions: [{ id: 'edit_info', title: 'Редактировать справку' }],
  },
});
assert.strictEqual(methods.roleSectionVisible.call(roleCtx, roleCtx.roleEditor.sections[0]), true);
assert.strictEqual(methods.roleSectionVisible.call(roleCtx, roleCtx.roleEditor.sections[1]), true);
roleCtx.roleSearch = 'второй';
assert.strictEqual(methods.roleSectionVisible.call(roleCtx, roleCtx.roleEditor.sections[1]), false,
  'пустая секция не матчится выдуманно');
assert.deepStrictEqual(
  methods.roleSectionParams.call(roleCtx, roleCtx.roleEditor.sections[0])
    .map(function (p) { return p.key; }),
  ['limits.b'], 'фильтр параметров');
assert.strictEqual(methods.roleSearchEmpty.call(roleCtx), false);
roleCtx.roleSearch = 'ничего';
assert.strictEqual(methods.roleSearchEmpty.call(roleCtx), true);
assert.strictEqual(methods.roleActionVisible.call({}, { id: 'edit_info', title: 'x' }), true,
  'без поиска действие видно');

/* ── 7. Superuser/read-only (UI-политика, не серверная граница) ─────────── */
const policy = {
  isGlobalAdmin: true,
  isSuperuserRole: methods.isSuperuserRole,
  canEditRole: methods.canEditRole,
  roleUsageCount: function () { return 0; },
};
assert.strictEqual(methods.isRoleReadOnly.call(policy, { role_name: 'admin' }), true,
  'superuser read-only');
assert.strictEqual(methods.isRoleReadOnly.call(policy, { role_name: 'local_admin' }), false);
assert.strictEqual(methods.canEditRole.call(policy,
  { role_name: 'custom', is_custom: true }), true);
assert.strictEqual(methods.canEditRole.call(policy,
  { role_name: 'admin', is_custom: false }), false);
policy.isGlobalAdmin = false;
assert.strictEqual(methods.canEditRole.call(policy,
  { role_name: 'custom', is_custom: true }), false,
  'non-global не получает rename/delete');
assert.strictEqual(methods.isRoleReadOnly.call(policy, { role_name: 'moderator' }), true);
assert.ok(methods.roleEditDisabledReason.call(policy, { role_name: 'moderator' })
  .indexOf('Только просмотр') >= 0);
assert.ok(methods.isSuperuserRole({ role_name: 'global_admin' }));
assert.ok(methods.isSuperuserRole({ role_name: 'x', role_type: 'global_admin' }));

/* ── 7b. F02: занятая custom-роль — delete disabled, rename разрешён ────── */
const usedCtx = vm({
  isGlobalAdmin: true,
  adminsLoading: false,
  adminsError: null,
  admins: [{ role_name: 'custom_used' }, { role_name: 'admin' }],
});
const usedRole = { role_name: 'custom_used', is_custom: true };
const unusedRole = { role_name: 'custom_free', is_custom: true };
assert.strictEqual(methods.canEditRole.call(usedCtx, usedRole), true,
  'rename занятой роли разрешён');
assert.strictEqual(methods.canDeleteRole.call(usedCtx, usedRole), false,
  'F02: delete занятой роли disabled');
assert.ok(methods.roleRestrictionHint.call(usedCtx, usedRole)
  .indexOf('Переименовать можно') >= 0,
  'rename hint не запрещает rename');
assert.ok(methods.roleDeleteHint.call(usedCtx, usedRole)
  .indexOf('назначена 1') >= 0,
  'delete hint называет usage');
assert.ok(methods.roleDeleteBlockedReason.call(usedCtx, usedRole)
  .indexOf('назначена 1') >= 0,
  'F02: причина видима, не только title');
assert.strictEqual(methods.canDeleteRole.call(usedCtx, unusedRole), true);
assert.strictEqual(methods.roleDeleteBlockedReason.call(usedCtx, unusedRole), '');
assert.strictEqual(methods.canDeleteRole.call(usedCtx,
  { role_name: 'admin', permissions: { wildcard: true } }), false);
usedCtx.adminsError = { status: 503, message: 'down' };
assert.strictEqual(methods.canDeleteRole.call(usedCtx, unusedRole), false,
  'неизвестные назначения → delete disabled');
assert.ok(methods.roleDeleteBlockedReason.call(usedCtx, unusedRole)
  .indexOf('не загружены') >= 0);
usedCtx.adminsError = null;
usedCtx.adminsLoading = true;
assert.strictEqual(methods.canDeleteRole.call(usedCtx, unusedRole), false,
  'пока назначения грузятся — delete disabled');
usedCtx.adminsLoading = false;
assert.ok(INDEX.indexOf('data-roles-delete') >= 0);
assert.ok(INDEX.indexOf('data-roles-usage-note') >= 0);
assert.ok(INDEX.indexOf('canDeleteRole(selectedRole())') >= 0);

/* ── 7c. F03: 404 retry перезагружает СПИСОК, не повторяет tree ─────────── */
const retryCtx = vm({
  _roleEditorBaseline: [],
  roleEditor: {
    open: true, roleName: 'gone', error: { status: 404 },
    rawPermissions: {}, tree: {}, sections: [{ id: 'x' }],
    actions: [{ id: 'a' }], saveError: 'x',
  },
  rolesCalls: 0,
  treeCalls: 0,
  loadRoles: async function () { this.rolesCalls += 1; },
  openRoleEditor: async function () { this.treeCalls += 1; },
});
methods.retryRolesList.call(retryCtx);
assert.strictEqual(retryCtx.rolesCalls, 1,
  'F03: retry вызывает loadRoles (список)');
assert.strictEqual(retryCtx.treeCalls, 0, 'F03: tree повторно не вызывается');
assert.strictEqual(retryCtx.roleEditor.error, null);
assert.strictEqual(retryCtx.roleEditor.roleName, '');
assert.strictEqual(retryCtx.roleEditor.tree, null);
assert.ok(INDEX.indexOf('data-roles-retry-list') >= 0);
assert.ok(INDEX.indexOf('retryRolesList()') >= 0);

/* ── 8. Фактические гейты: только реальные id, без выдуманных чекбоксов ─── */
const gates = methods.gatesList.call({});
const flat = gates.map(function (g) { return g.items.join('\n'); }).join('\n');
for (const marker of ['access', 'edit_info', 'edit_persona',
                      'edit_humor_library', 'control.restart', 'control.stop',
                      'control.start', 'debug.config', 'chat_lore']) {
  assert.ok(flat.indexOf(marker) >= 0, 'реальный гейт ' + marker);
}
assert.ok(flat.indexOf('Только владелец') >= 0 || gates[1].group.indexOf('владелец') >= 0);
assert.ok(PAGE.indexOf('data-roles-pane="gates"') >= 0);
assert.strictEqual(PAGE.slice(PAGE.indexOf('data-roles-pane="gates"')).includes('<input type="checkbox"'), false,
  'в гейтах нет чекбоксов');

console.log('MOD-ACL-UX-M4C1-ROLES-PAGE-OK');
