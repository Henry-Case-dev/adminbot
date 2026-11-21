'use strict';
/* ═══ MOD-ACL-UX-01 M4C C2 — «Проверить доступ» (effective preview) ════════
 * Контракт: plans/features/mod-acl-ux-01/evidence/m4c/c2-contract-2026-11-22.md
 * §4.8, §6, §7.2.
 *
 * Проверяется РЕАЛЬНЫЙ код web/app.js + web/index.html + web/static/app.css:
 *   1) блок внутри существующей вкладки gates, без новой вкладки/чекбоксов;
 *   2) 9 методов preview, 0 запросов на ввод символа, 1 запрос на «Проверить»;
 *      смена роли/scope пересчитывает результат, resource — только stale;
 *   3) explicit chat_id в query + global:true (НЕ X-Chat-Id шапки);
 *   4) слои рендерятся по порядку и не сворачиваются в один бейдж; mixed →
 *      «Частично»; 401/403/404/422/503 — разные подсказки, 503 не «Запрещено»;
 *   5) роль без назначений → no-actor, без симуляции; perevкрытия только
 *      admin+chat, 403 скрывается, 503 — карточка;
 *   6) исправленные строки гейтов и «автор не записан (audit — C3)»;
 *   7) CSS: stack на <768, тач ≥44, без горизонтального скролла.
 *
 * Запуск: node tests/js/mod_acl_ux_m4c2_preview_test.js
 *         → MOD-ACL-UX-M4C2-PREVIEW-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

/* ── 1. Статика: блок в gates, без новой вкладки/чекбоксов ──────────────── */
assert.ok(INDEX.indexOf('data-preview') >= 0, 'preview-блок отсутствует');
assert.ok(INDEX.indexOf('data-preview-title') >= 0, 'нет заголовка preview');
assert.ok(INDEX.indexOf('data-preview-note') >= 0, 'нет честной подписи');
assert.ok(INDEX.indexOf('Права не изменены') >= 0, 'note «Права не изменены»');
assert.ok(INDEX.indexOf('data-preview-form') >= 0, 'нет формы preview');
assert.ok(INDEX.indexOf('data-preview-actor') >= 0, 'нет селектора актора');
assert.ok(INDEX.indexOf('data-preview-scope') >= 0, 'нет селектора области');
assert.ok(INDEX.indexOf('data-preview-resource') >= 0, 'нет поля ресурса');
assert.ok(INDEX.indexOf('data-preview-op') >= 0, 'нет селектора операции');
assert.ok(INDEX.indexOf('data-preview-run') >= 0, 'нет кнопки «Проверить»');
assert.ok(INDEX.indexOf('data-preview-result') >= 0, 'нет контейнера результата');
assert.ok(INDEX.indexOf('data-preview-decision') >= 0, 'нет бейджа решения');
assert.ok(INDEX.indexOf('data-preview-layer') >= 0, 'нет маркера слоя');
assert.ok(INDEX.indexOf('data-preview-source') >= 0, 'нет источника/момента');
assert.ok(INDEX.indexOf('data-preview-chat-overrides') >= 0,
  'нет блока перекрытий чата');
assert.ok(INDEX.indexOf('data-preview-no-actor') >= 0, 'нет состояния no-actor');
assert.ok(INDEX.indexOf('data-preview-stale') >= 0, 'нет состояния stale');
assert.ok(INDEX.indexOf('data-preview-error') >= 0, 'нет карточки ошибки');
assert.strictEqual(INDEX.indexOf('data-preview-tab'), -1,
  'preview не должен быть новой вкладкой');

const gatesStart = INDEX.indexOf('data-roles-pane="gates"');
assert.ok(gatesStart >= 0, 'нет вкладки гейтов');
const gatesEnd = INDEX.indexOf('</section>', gatesStart);
const GATES = INDEX.slice(gatesStart, gatesEnd);
const previewStart = GATES.indexOf('data-preview');
const previewEnd = GATES.indexOf('Фактические гейты', previewStart);
const PREVIEW = GATES.slice(previewStart, previewEnd);
assert.ok(PREVIEW.indexOf('data-preview') >= 0, 'preview внутри gates');
assert.ok(PREVIEW.indexOf('Справочник гейтов') < 0,
  'preview не должен включать статический список гейтов');
assert.strictEqual(PREVIEW.indexOf('<input type="checkbox"'), -1,
  'внутри preview нет чекбоксов (C1-утверждение сохраняется)');
assert.ok(GATES.indexOf('Справочник гейтов') >= 0,
  'подзаголовок статического списка отсутствует');
assert.ok(GATES.indexOf('Проверить доступ') >= 0, 'заголовок preview');
assert.ok(GATES.indexOf('Фактические гейты') >= 0, 'старый заголовок сохранён');
assert.ok(GATES.indexOf('data-roles-pane="gates"') === 0, 'срез начинается с зоны gates');

for (const tab of ['rights', 'matrix', 'gates']) {
  assert.ok(INDEX.indexOf('data-roles-pane="' + tab + '"') >= 0, 'зона ' + tab);
}
assert.strictEqual(INDEX.indexOf('data-roles-pane="preview"'), -1,
  'четвёртой вкладки нет');

/* ── 2. Реальный app.js ─────────────────────────────────────────────────── */
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

const REQUIRED_METHODS = [
  'previewRun', 'previewReset', 'previewActorOptions', 'previewScopeOptions',
  'previewResourceKind', 'previewDecisionLabel', 'previewLayerLabel',
  'previewLoadChatOverrides', 'previewSeedActor',
];
REQUIRED_METHODS.forEach(function (name) {
  assert.strictEqual(typeof methods[name], 'function', 'method ' + name);
});

/* ── 3. Дерево/лейблы/операции ──────────────────────────────────────────── */
assert.strictEqual(methods.previewResourceKind('section.access'), 'section');
assert.strictEqual(methods.previewResourceKind('action.edit_info'), 'action');
assert.strictEqual(methods.previewResourceKind('param.limits.x'), 'param');
assert.strictEqual(methods.previewResourceKind('key.keys.groq'), 'key');
assert.strictEqual(methods.previewResourceKind(''), '');
assert.strictEqual(methods.previewResourceKind('section.'), '');
assert.strictEqual(methods.previewResourceKind('bogus.x'), '');
assert.strictEqual(methods.previewDecisionLabel('allowed'), 'Разрешено');
assert.strictEqual(methods.previewDecisionLabel('denied'), 'Запрещено');
assert.strictEqual(methods.previewDecisionLabel('mixed'), 'Частично');
assert.strictEqual(methods.previewDecisionLabel('not_applicable'), 'Не применимо');
assert.strictEqual(methods.previewLayerLabel({ id: 'chat_matrix' }),
  'Матрица «Доступ к параметрам»');
assert.strictEqual(methods.previewLayerLabel({ id: 'role', label: 'x' }),
  'Права роли');

/* ── 4. Акторы/области/роль без назначений ──────────────────────────────── */
function baseState(extra) {
  const state = {
    me: { telegram_id: 5885953495, first_name: 'Audit' },
    isGlobalAdmin: true,
    admins: [
      { telegram_id: 1313107079, role_name: 'moderator', display_name: 'Mod' },
      { telegram_id: 777000111, role_name: 'moderator', display_name: null },
      { telegram_id: 5885953495, role_name: 'admin', display_name: 'Audit' },
    ],
    adminsError: null,
    accessChats: [
      { chat_id: -100123, title: 'Чат', is_dm: false },
      { chat_id: 5885953495, title: 'Личные сообщения', is_dm: true },
    ],
    roleEditor: { roleName: 'moderator', tree: null, sections: [], actions: [] },
    matrixItems: {},
    preview: {
      actorValue: 'self', actorManual: '', scopeValue: 'global',
      resource: '', operation: 'view', loading: false, error: null,
      result: null, stale: false, noActor: false, chatAdmins: [],
      chatAdminsError: null, chatOverrides: null, chatOverridesError: null,
      _seq: 0,
    },
  };
  return Object.assign(state, extra || {});
}
const vm = function (extra) { return Object.assign({}, methods, extra || {}); };

let ctx = vm(baseState());
assert.strictEqual(methods.previewSelfId.call(ctx), 5885953495);
assert.strictEqual(methods.previewActorId.call(ctx), 5885953495);
let actorOpts = methods.previewActorOptions.call(ctx);
assert.deepStrictEqual(actorOpts.map(function (o) { return o.value; }),
  ['self', '1313107079', '777000111', 'manual']);
ctx.preview.actorValue = 'manual';
ctx.preview.actorManual = '12345';
assert.strictEqual(methods.previewActorId.call(ctx), 12345);
ctx.preview.actorManual = 'abc';
assert.strictEqual(methods.previewActorId.call(ctx), null);
ctx.preview.actorValue = 'self';

let scopeOpts = methods.previewScopeOptions.call(ctx);
assert.deepStrictEqual(scopeOpts.map(function (o) { return o.value; }),
  ['global', '-100123', 'dm']);
ctx.preview.actorValue = '1313107079';
scopeOpts = methods.previewScopeOptions.call(ctx);
assert.strictEqual(scopeOpts.some(function (o) { return o.value === 'dm'; }), false,
  'DM-область только для self');
assert.strictEqual(methods.previewScopeChatId.call(ctx), null);
ctx.preview.scopeValue = '-100123';
assert.strictEqual(methods.previewScopeChatId.call(ctx), -100123);
ctx.preview.scopeValue = 'dm';
assert.strictEqual(methods.previewScopeChatId.call(ctx), 5885953495);

/* Роль без назначений → no-actor, без симуляции. */
const noActorCtx = vm(baseState({
  roleEditor: { roleName: 'local_admin', tree: null, sections: [], actions: [] },
}));
methods.previewSeedActor.call(noActorCtx);
assert.strictEqual(noActorCtx.preview.noActor, true, 'роль без назначений → no-actor');
assert.strictEqual(noActorCtx.preview.actorValue, '');
assert.ok(INDEX.indexOf('Роль не назначена') >= 0);

/* Роль с назначениями → актор сеется из назначенных, если не выбран явно. */
const assignedCtx = vm(baseState());
assignedCtx.preview.actorValue = '';
methods.previewSeedActor.call(assignedCtx);
assert.strictEqual(assignedCtx.preview.noActor, false);
assert.strictEqual(assignedCtx.preview.actorValue, '1313107079',
  'актор = реально назначенный админ роли');

/* ── 5. Запрос: 1 на «Проверить», 0 на символ, explicit chat_id ──────────── */
async function withApi(state, queue) {
  const calls = [];
  const local = vm(Object.assign({}, state, {
    api: async function (p, o) {
      calls.push({ path: p, options: o });
      return queue.length ? queue.shift() : {};
    },
    previewLoadChatOverrides: async function () {},
    previewLoadChatAdmins: async function () {},
  }));
  return { local, calls };
}

async function main() {
  /* 5a. Успешный прогон: param в чате, explicit chat_id + global:true. */
  let state = baseState();
  state.adminsError = null;
  state.preview.scopeValue = '-100123';
  state.preview.actorValue = '1313107079';
  state.preview.resource = 'param.limits.search max';
  state.preview.operation = 'edit';
  let bundle = await withApi(state, [{
    mode: 'delegated', decision: 'denied', preview: true,
    note: 'Предварительная проверка. Права не изменены.',
    evaluated_at: '2026-11-22T10:00:00Z',
    resolver: 'x', actor: { telegram_id: 1313107079, display_name: null,
      role_name: 'moderator', role_type: 'moderator', is_global_admin: false,
      is_local_admin: false, rank: 2, is_dm_owner: false },
    scope: { kind: 'chat', chat_id: -100123, title: null,
      chat_role: null, profile_present: true },
    resource: { namespace: 'param.limits.search max', kind: 'param',
      title: null, secret: null, hidden: null },
    operation: 'edit',
    layers: [{ id: 'role', label: 'Права роли', decision: 'denied',
      hard: false, applies_to: 'guard', reason: 'no_match',
      required: 'param.limits.search max', matched: null,
      guard: 'web.api.deps.can_edit_param(x)', consumers: ['POST /api/config'],
      source: 'role_permissions' }],
    overrides: { global: { present: false, updated_at: null,
      author_recorded: false },
      chat: { present: false, updated_at: null, author_recorded: false } },
  }]);
  await methods.previewRun.call(bundle.local);
  assert.strictEqual(bundle.calls.length, 1, '1 запрос на «Проверить»');
  const call = bundle.calls[0];
  assert.ok(call.path.indexOf('/api/access/effective?') === 0, 'effective URL');
  assert.ok(call.path.indexOf('telegram_id=1313107079') >= 0);
  assert.ok(call.path.indexOf('chat_id=-100123') >= 0, 'explicit chat_id в query');
  assert.ok(call.path.indexOf('resource=param.limits.search%20max') >= 0,
    'resource кодируется');
  assert.ok(call.path.indexOf('operation=edit') >= 0);
  assert.strictEqual(call.options.global, true,
    'preview не использует X-Chat-Id шапки (global:true)');
  assert.strictEqual(bundle.local.preview.result.decision, 'denied');
  assert.strictEqual(bundle.local.preview.loading, false);

  /* 5b. Section принудительно view; action — execute. */
  state = baseState();
  state.preview.resource = 'section.access';
  state.preview.operation = 'edit';
  bundle = await withApi(state, [{}]);
  await methods.previewRun.call(bundle.local);
  assert.ok(bundle.calls[0].path.indexOf('operation=view') >= 0,
    'section → view');
  state = baseState();
  state.preview.resource = 'action.edit_info';
  bundle = await withApi(state, [{}]);
  await methods.previewRun.call(bundle.local);
  assert.ok(bundle.calls[0].path.indexOf('operation=execute') >= 0,
    'action → execute');

  /* 5c. Ввод символа — 0 запросов и stale (не показываем устаревшее). */
  state = baseState();
  state.preview.result = { decision: 'allowed' };
  bundle = await withApi(state, []);
  methods.previewMarkStale.call(bundle.local);
  assert.strictEqual(bundle.calls.length, 0, '0 запросов на ввод символа');
  assert.strictEqual(bundle.local.preview.result, null,
    'старый результат очищен');
  assert.strictEqual(bundle.local.preview.stale, true, 'показан stale');
  assert.ok(INDEX.indexOf('Входные данные изменены') >= 0);

  /* 5d. Смена актора/области/роли при существующем результате — пересчёт. */
  state = baseState();
  state.preview.resource = 'section.access';
  state.preview.result = { decision: 'allowed' };
  state.preview.actorValue = 'self';
  bundle = await withApi(state, [{ decision: 'denied' }]);
  bundle.local.preview.actorValue = '1313107079';
  methods.previewOnActorChange.call(bundle.local);
  await new Promise(function (r) { setImmediate(r); });
  assert.strictEqual(bundle.calls.length, 1, 'смена актора пересчитывает');

  state = baseState();
  state.preview.resource = 'section.access';
  state.preview.result = { decision: 'allowed' };
  bundle = await withApi(state, [{ decision: 'allowed' }]);
  bundle.local.preview.scopeValue = '-100123';
  methods.previewOnScopeChange.call(bundle.local);
  await new Promise(function (r) { setImmediate(r); });
  assert.strictEqual(bundle.calls.length, 1, 'смена scope пересчитывает');

  state = baseState();
  state.preview.resource = 'section.access';
  state.preview.result = { decision: 'allowed' };
  bundle = await withApi(state, [{ decision: 'mixed' }]);
  methods.previewOnRoleChange.call(bundle.local);
  await new Promise(function (r) { setImmediate(r); });
  assert.strictEqual(bundle.calls.length, 1, 'смена роли пересчитывает');
  assert.strictEqual(bundle.local.preview.result.decision, 'mixed');

  /* 5e. Ошибка 503: не «Запрещено», решение не подставляется. */
  state = baseState();
  state.preview.resource = 'param.limits.x';
  bundle = await withApi(state, []);
  bundle.local.api = async function () {
    const err = new Error('PostgreSQL недоступен');
    err.status = 503;
    throw err;
  };
  await methods.previewRun.call(bundle.local);
  assert.strictEqual(bundle.local.preview.result, null, '503 без решения');
  assert.strictEqual(bundle.local.preview.error.status, 503);
  const hunts = [401, 403, 404, 422, 503].map(function (s) {
    return methods.previewErrorHint(s);
  });
  assert.strictEqual(new Set(hunts).size, 5, '401/403/404/422/503 различаются');
  assert.ok(methods.previewErrorHint(503).indexOf('временно') >= 0);
  assert.ok(methods.previewErrorHint(403).indexOf('не означает') >= 0);
  assert.strictEqual(INDEX.indexOf('data-preview-error'), INDEX.lastIndexOf('data-preview-error'),
    'одна карточка ошибки');

  /* 5f. Reset. */
  state = baseState();
  state.preview.result = { decision: 'allowed' };
  state.preview.error = { status: 503 };
  state.preview.stale = true;
  bundle = await withApi(state, []);
  methods.previewReset.call(bundle.local);
  assert.strictEqual(bundle.local.preview.result, null);
  assert.strictEqual(bundle.local.preview.error, null);
  assert.strictEqual(bundle.local.preview.stale, false);

  /* ── 6. Слои и перекрытия ─────────────────────────────────────────────── */
  assert.ok(INDEX.indexOf('v-for="layer in preview.result.layers"') >= 0,
    'слои рендерятся циклом');
  assert.ok(INDEX.indexOf(':data-preview-layer="layer.id"') >= 0);
  assert.ok(INDEX.indexOf('previewLayerDecisionLabel(layer)') >= 0);
  assert.ok(INDEX.indexOf('layer.guard') >= 0);
  assert.ok(INDEX.indexOf('layer.consumers') >= 0);
  assert.ok(INDEX.indexOf('layer.matched') >= 0);
  assert.ok(INDEX.indexOf('layer.required') >= 0);
  assert.strictEqual(INDEX.indexOf('preview.result.decision).slice'),
    -1, 'нет сворачивания слоёв в один текст');

  /* 6a. Перекрытия только admin + group chat. */
  state = baseState();
  state.preview.scopeValue = '-100123';
  bundle = await withApi(state, [{ items: {}, updated_at: 'x' }]);
  bundle.local.isGlobalAdmin = false;
  await methods.previewLoadChatOverrides.call(bundle.local);
  assert.strictEqual(bundle.calls.length, 0,
    'не-admin не запрашивает перекрытия чата');
  assert.strictEqual(bundle.local.preview.chatOverrides, null);

  state = baseState();
  state.preview.scopeValue = '-100123';
  bundle = await withApi(state, [{
    chat_id: -100123, profile_present: true, updated_at: 't',
    items: { 'limits.x': { view_roles: ['local_admin'], edit_roles: [],
      legacy: true } }, filtered_out: 2,
  }]);
  await methods.previewLoadChatOverrides.call(bundle.local);
  assert.strictEqual(bundle.calls.length, 1, 'admin+chat → 1 запрос перекрытий');
  assert.ok(bundle.calls[0].path.indexOf(
    '/api/access/chats/-100123/param_permissions') >= 0);
  assert.strictEqual(bundle.calls[0].options.global, true);
  assert.strictEqual(methods.previewOverridesCount.call(bundle.local), 1);
  const rows = methods.previewChatOverridesList.call(bundle.local);
  assert.strictEqual(rows[0].legacy, true);
  assert.ok(INDEX.indexOf('legacy') >= 0);

  /* 6b. 403 перекрытий — скрыто/подпись, не error-карточка; 503 — карточка. */
  bundle = await withApi(baseState(), []);
  bundle.local.preview.scopeValue = '-100123';
  bundle.local.api = async function () {
    const err = new Error('forbidden'); err.status = 403; throw err;
  };
  await methods.previewLoadChatOverrides.call(bundle.local);
  assert.strictEqual(bundle.local.preview.chatOverridesError.status, 403);
  assert.strictEqual(bundle.local.preview.chatOverridesError.suppressed, true);
  assert.ok(INDEX.indexOf('403) — блок скрыт') >= 0);

  bundle = await withApi(baseState(), []);
  bundle.local.preview.scopeValue = '-100123';
  bundle.local.api = async function () {
    const err = new Error('down'); err.status = 503; throw err;
  };
  await methods.previewLoadChatOverrides.call(bundle.local);
  assert.strictEqual(bundle.local.preview.chatOverridesError.suppressed, false);
  assert.ok(INDEX.indexOf('preview.chatOverridesError.status') >= 0,
    '503 перекрытий → error-карточка');

  /* 6c. Автор перекрытия не выдумывается. */
  assert.strictEqual(methods.previewOverrideAuthorText(true),
    'автор не записан (audit — C3)');
  assert.ok(INDEX.indexOf('previewOverrideAuthorText(') >= 0);

  /* ── 7. Исправленные строки гейтов (марка C1 сохранены) ────────────────── */
  const gates = methods.gatesList.call({});
  const flat = gates.map(function (g) { return g.items.join('\n'); }).join('\n');
  for (const marker of ['access', 'edit_info', 'edit_persona',
                        'edit_humor_library', 'control.restart', 'control.stop',
                        'control.start', 'debug.config', 'chat_lore']) {
    assert.ok(flat.indexOf(marker) >= 0, 'маркер C1 гейта ' + marker);
  }
  assert.ok(flat.indexOf('матрица и чатовые гранты — только global admin') >= 0,
    'access: точная формулировка');
  assert.ok(flat.indexOf('глобальная запись значения (/api/config)') >= 0,
    'param.<key>: глобальная запись, не матрица');
  assert.ok(flat.indexOf('проверяют членство в chat_admins') >= 0,
    'chat_lore: серверный guard = chat_admins');
  assert.ok(gates[1].group.indexOf('владелец') >= 0, 'owner-only группа');
  assert.strictEqual(gates[0].items.length, 8, '8 пунктов прав роли сохранены');
  assert.strictEqual(gates[1].items.length, 4, '4 owner-only пункта сохранены');
  assert.strictEqual(PREVIEW.indexOf('type="checkbox"'), -1);

  /* ── 8. CSS: stack на <768, тач ≥44, без h-scroll ──────────────────────── */
  assert.ok(/\.roles-preview__form \{[\s\S]{0,160}grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/
    .test(CSS), 'desktop: две колонки формы');
  assert.ok(/\.roles-preview__form \{ grid-template-columns: minmax\(0, 1fr\);/
    .test(CSS), 'mobile: одна колонка');
  assert.ok(/\.roles-preview__run \{ width: 100%; min-height: 44px; \}/
    .test(CSS), 'mobile: кнопка 44 и на всю ширину');
  assert.ok(/\.roles-preview__form \.field,[\s\S]{0,140}min-height: 44px/
    .test(CSS), 'mobile: тач-цели ≥44');
  assert.ok(/\.roles-preview__guard \{[\s\S]{0,160}overflow-wrap: anywhere/
    .test(CSS), 'guard переносится, без h-scroll');
  assert.ok(/\.roles-preview__wrap \{[\s\S]{0,120}overflow-wrap: anywhere/
    .test(CSS), 'длинные строки переносятся');
  assert.strictEqual(/\.roles-preview[\s\S]{0,2000}overflow-x:\s*auto/.test(CSS),
    false, 'нет горизонтального скролла в preview');

  /* ── 9. Только чтение: preview не шлёт write-запросов ──────────────────── */
  const previewSlice = JS.slice(JS.indexOf('// ═══ M4C C2: «Проверить доступ»'),
    JS.indexOf('// Подпись области для сводки «Доступов»'));
  assert.ok(previewSlice.indexOf('method: \'POST\'') < 0, 'нет POST в preview');
  assert.ok(previewSlice.indexOf('method: \'PUT\'') < 0, 'нет PUT в preview');
  assert.ok(previewSlice.indexOf('method: \'DELETE\'') < 0, 'нет DELETE в preview');
  assert.ok(previewSlice.indexOf('/api/access/effective') >= 0);
  assert.ok(previewSlice.indexOf('/param_permissions') >= 0);
  assert.ok(previewSlice.indexOf('/admins') >= 0);
  assert.strictEqual(fetchCalls, 0, 'юнит не ходил в сеть');

  console.log('MOD-ACL-UX-M4C2-PREVIEW-OK');
}

main().catch(function (e) {
  console.error(e && e.stack || e);
  process.exit(1);
});
