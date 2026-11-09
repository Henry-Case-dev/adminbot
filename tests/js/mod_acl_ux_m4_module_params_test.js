'use strict';
/* MOD-ACL-UX-01 M4 — страница модуля реестра показывает РЕАЛЬНЫЕ параметры
 * каталога, а пустой блок честно называет свою причину.
 *
 * TEST-LIFECYCLE: CONTRACT owner=MOD-ACL-UX-01/M4 (§5 ТЗ владельца).
 *
 * Проверяется РЕАЛЬНЫЙ web/app.js (не grep) на ЖИВОМ контракте сервера:
 * снимок готовит tests/test_mod_acl_ux_01_m4_module_params.py — ответ
 * `GET /api/config` для глобального админа и для обычного пользователя плюс
 * `registry_for_frontend()`.
 *
 *   (1) у глобального админа страница «Векторная память» (`mod_embeddings`,
 *       инфраструктурный модуль без своей config-вкладки) отдаёт НЕПУСТОЙ
 *       набор реальных параметров — группы каталога, объявленные реестром
 *       (models_embeddings + keys_llm), с каталоговыми заголовками и в
 *       каталоговом порядке; вкладка «Настройки» существует, вкладки
 *       «Лимиты» (пустой) нет, ложного пустого блока на «Обзоре» нет;
 *   (2) поиск фильтрует ВНУТРИ этого набора (не по всему каталогу);
 *   (3) обычный пользователь по-прежнему получает отказ на уровне маршрута;
 *   (4) текст пустого блока выбирается по ФАКТИЧЕСКОЙ причине:
 *       нет параметров каталога ≠ отфильтровано по правам; «по правам»
 *       невозможно у глобального админа и не заявляется без реального
 *       фильтра.
 *
 * Запуск (стандартный прогон — без аргументов):
 *   node tests/js/mod_acl_ux_m4_module_params_test.js
 *   → берёт закоммиченный снимок `tests/fixtures/mod_acl_m4_embeddings_payload.json`
 *     (путь относительно файла; drift-guard в
 *     `tests/test_mod_acl_ux_01_m4_module_params.py`).
 * Аргумент-путь (необязательный) — живой снимок из python-обёртки:
 *   node tests/js/mod_acl_ux_m4_module_params_test.js <snapshot.json>
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
const _storage = {
  _s: {},
  getItem(k) {
    return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null;
  },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; }, localStorage: _storage,
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
  querySelector() { return null; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

const ROOT = path.join(__dirname, '..', '..');
require(path.join(ROOT, 'web', 'app.js'));
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
assert(captured, 'Vue.createApp должен быть вызван');

const data = captured.data();
const methods = captured.methods;
const computed = captured.computed;
const MODULES = data.modules;
const TABS = data.tabs;

// Снимок контракта: аргумент (живой, из python-обёртки) ИЛИ закоммиченный
// снимок рядом с тестом. Стандартный прогон `node tests/js/*.js` идёт БЕЗ
// аргументов — файл обязан быть самодостаточным, иначе он валит весь набор.
const snapshotPath = process.argv[2]
  || path.join(__dirname, '..', 'fixtures', 'mod_acl_m4_embeddings_payload.json');
assert.ok(fs.existsSync(snapshotPath),
  'нет снимка контракта M4: ' + snapshotPath
  + ' (его пересобирает tests/test_mod_acl_ux_01_m4_module_params.py)');
const SNAP = JSON.parse(fs.readFileSync(snapshotPath, 'utf8'));
const REGISTRY = SNAP.registry;
const CATALOG_ADMIN = SNAP.admin;    // GET /api/config для глобального админа
const CATALOG_USER = SNAP.user;      // GET /api/config для обычного пользователя

// Реестр доливается в тот же список модулей, что и в проде (loadConfig).
methods.f3ApplyModuleRegistry.call({
  modules: MODULES, _f4Registry: {}, workspaceModule: null,
}, REGISTRY);

const ADMIN = {
  role_name: 'куратор проекта', is_global_admin: true,
  permissions: { wildcard: true },
};
const PLAIN = {
  role_name: 'участник', is_global_admin: false,
  permissions: { sections: ['status'] },
};

const SPEC = REGISTRY.filter(function (s) { return s.id === 'embeddings'; })[0];
assert.ok(SPEC, 'в реестре есть модуль embeddings');

let checks = 0;
function ok(cond, msg) {
  assert.ok(cond, msg);
  checks += 1;
}
function eq(a, b, msg) {
  assert.strictEqual(a, b, msg);
  checks += 1;
}
function eqJson(a, b, msg) {
  assert.deepStrictEqual(JSON.parse(JSON.stringify(a)),
                         JSON.parse(JSON.stringify(b)), msg);
  checks += 1;
}

// Один контекст «как в проде»: real computed-свойства читаются лениво.
function mkCtx(me, catalog, opts) {
  const o = opts || {};
  const ctx = Object.assign({}, methods, {
    me: me,
    tabs: TABS,
    modules: MODULES,
    route: o.route || '#/modules/embeddings',
    activeTab: o.activeTab || 'mod_embeddings',
    accessOpen: null,
    iaV2: true,
    activeChatId: null,
    chatLoreChats: [],
    scopeKind: o.scopeKind || 'global',
    configItems: catalog.items,
    configGroups: catalog.groups,
    configSearch: o.search || '',
    _f4Registry: {},
    _toasts: [],
    _f3RegistryApplied: false,
  });
  ctx.toast = function (m, k) { ctx._toasts.push([m, k]); };
  ctx.syncBackButton = function () {};
  ctx.setTab = function (id) { ctx.activeTab = id; };
  ctx.navigateTo = function (h) { ctx.route = h; };
  ctx._flagTabHidden = methods._flagTabHidden;
  ctx.isDmCtx = function () { return false; };
  ctx.isLocalAdminCtx = methods.isLocalAdminCtx;
  ctx.canViewTab = methods.canViewTab;
  ctx.hasPerm = methods.hasPerm;
  ctx.moduleBySlug = methods.moduleBySlug;
  ctx.moduleByTab = methods.moduleByTab;
  ctx._isModuleTab = methods._isModuleTab;
  ctx._tabDescriptorFor = methods._tabDescriptorFor;
  ctx._registryPageSources = methods._registryPageSources;
  ctx._registryPageGroupIds = methods._registryPageGroupIds;
  ctx._isDerivedModulePage = methods._isDerivedModulePage;
  ctx.workspaceGroupTab = methods.workspaceGroupTab;
  ctx._workspaceGroupsFor = methods._workspaceGroupsFor;
  ctx._moduleViewGroup = methods._moduleViewGroup;
  ctx.isModuleMasterItem = methods.isModuleMasterItem;
  ctx.flatGroupRank = methods.flatGroupRank;
  ctx.tabSourceForItem = methods.tabSourceForItem;
  ctx.itemMatchesSource = methods.itemMatchesSource;
  ctx.tabItemCount = methods.tabItemCount;
  ctx.groupedForTab = methods.groupedForTab;
  ctx.basicItems = methods.basicItems;
  ctx.advancedItems = methods.advancedItems;
  ctx.isGlobalAdminEffective = methods.isGlobalAdminEffective;
  ctx.applyRoute = function (h) { return methods.applyRoute.call(ctx, h); };
  if (o.dropRegistry) {
    ctx._f4Registry = {};
  } else {
    methods.f3ApplyModuleRegistry.call(ctx, REGISTRY);
  }
  ctx._f3RegistryApplied = true;
  ['permissions', 'isGlobalAdmin', 'currentTab', 'workspaceModule',
   'workspaceTab', 'workspace', 'currentTabIsConfig', 'currentTabGroups',
   'currentTabItemCount', 'workspaceTabs', 'emptyTabReason', 'emptyTabTitle',
   'emptyTabCause'].forEach(function (k) {
    Object.defineProperty(ctx, k, {
      configurable: true,
      get: function () { return computed[k].call(this); },
    });
  });
  return ctx;
}

function itemsOfGroup(catalog, gid) {
  return catalog.items.filter(function (it) { return it.group === gid; });
}
function groupMeta(catalog, gid) {
  return catalog.groups.filter(function (g) { return g.id === gid; })[0];
}

const DECLARED = (SPEC.settings_groups || []).concat(SPEC.model_slots || []);
const embItems = itemsOfGroup(CATALOG_ADMIN, 'models_embeddings');
const keyItems = itemsOfGroup(CATALOG_ADMIN, 'keys_llm');

// ── (1) реальный набор параметров страницы у глобального админа ────────────
{
  ok(DECLARED.length >= 2,
    'реестр объявляет группы параметров модуля (settings_groups+model_slots)');
  // Контракт владельца: 16 параметров эмбеддингов + 9 ключей = 25 на странице.
  eq(embItems.length, 16,
    'каталог отдаёт админу 16 параметров models_embeddings (без фильтра прав)');
  eq(keyItems.length, 9,
    'каталог отдаёт админу 9 ключей keys_llm (паритет с витриной провайдеров)');
  eq(embItems.length + keyItems.length, 25,
    'страница «Основные настройки» показывает 25 параметров');
  ok(itemsOfGroup(CATALOG_ADMIN, 'models_main').length > 0,
    'в снимке есть соседняя группа models_main (для проверки поиска)');

  const ctx = mkCtx(ADMIN, CATALOG_ADMIN, { route: '#/modules/embeddings/settings' });
  const desc = computed.currentTab.call(ctx);
  ok(desc && desc.type === 'config', 'страница модуля — config-вкладка');
  ok(Array.isArray(desc.sources) && desc.sources.length > 0,
    'источники вкладки выведены из каталога, а НЕ пустой список');
  eqJson((ctx._f4Registry.embeddings || {}).settings_groups,
    SPEC.settings_groups || [], 'реестр даёт объявление групп этому модулю');
  eqJson((ctx._f4Registry.embeddings || {}).model_slots,
    SPEC.model_slots || [], 'реестр даёт слоты моделей/ключей модуля');

  // Группы «Настроек» — ровно объявленные каталогом, в порядке каталога.
  const groups = computed.currentTabGroups.call(ctx);
  const ids = groups.map(function (g) { return g.id; });
  const want = DECLARED.slice().sort(function (a, b) {
    return (groupMeta(CATALOG_ADMIN, a) || {}).order
      - (groupMeta(CATALOG_ADMIN, b) || {}).order;
  });
  eqJson(ids, want, 'порядок групп = порядок каталога, набор = объявленный');
  groups.forEach(function (g) {
    const meta = groupMeta(CATALOG_ADMIN, g.id);
    ok(g.items.length > 0, 'группа «' + g.id + '» не пустая');
    eq(g.meta && g.meta.title, meta.title,
      'заголовок группы — каталоговый: ' + meta.title);
    eqJson(g.items.map(function (it) { return it.key; }),
      itemsOfGroup(CATALOG_ADMIN, g.id).map(function (it) { return it.key; }),
      'в группе «' + g.id + '» все параметры сервера, без умолчаний');
  });
  const shown = groups.reduce(function (n, g) { return n + g.items.length; }, 0);
  eq(shown, embItems.length + keyItems.length,
    'страница показывает ВЕСЬ объявленный набор параметров');

  // Вкладки: «Настройки» существует, пустых («Лимиты») нет.
  const tabs = computed.workspaceTabs.call(ctx);
  const tabIds = tabs.map(function (t) { return t.id; });
  eqJson(tabIds, ['overview', 'settings'],
    'вкладки страницы: Обзор + Настройки (пустая «Лимиты» не рисуется)');
  ok(computed.currentTabItemCount.call(ctx) > 0,
    'у страницы непустой счётчик — ложный пустой блок невозможен');

  // Переход на «Обзор»: пустого блока с ложной причиной нет.
  const overview = mkCtx(ADMIN, CATALOG_ADMIN, { route: '#/modules/embeddings' });
  eq(computed.workspaceTab.call(overview), 'overview', 'дефолт — «Обзор»');
  ok(computed.currentTabItemCount.call(overview) > 0,
    '«Обзор» не показывает «нет параметров» при реальных параметрах');
}

// ── (2) поиск работает ВНУТРИ набора страницы ─────────────────────────────
{
  const keyItem = keyItems[0];
  const embItem = embItems[0];

  // Запрос по ключу параметра ключей: остаётся только группа ключей.
  const ctx1 = mkCtx(ADMIN, CATALOG_ADMIN,
                     { route: '#/modules/embeddings/settings', search: keyItem.key });
  const groups1 = computed.currentTabGroups.call(ctx1);
  eqJson(groups1.map(function (g) { return g.id; }), ['keys_llm'],
    'поиск по ключу параметра оставляет только группу ключей');
  eq(groups1[0].items.length, 1, 'найдено ровно то значение, что искали');
  eq(groups1[0].items[0].key, keyItem.key, 'найденный параметр — реальный');

  // Запрос по фрагменту ключей эмбеддингов — только их группа, не все страницы.
  const ctx2 = mkCtx(ADMIN, CATALOG_ADMIN,
                     { route: '#/modules/embeddings/settings', search: 'fallback' });
  const groups2 = computed.currentTabGroups.call(ctx2);
  ok(groups2.length >= 1, 'поиск «fallback» что-то находит');
  groups2.forEach(function (g) {
    ok(DECLARED.indexOf(g.id) >= 0,
      'поиск не вытаскивает параметры чужих групп каталога: ' + g.id);
  });
  ok(groups2.some(function (g) { return g.id === 'models_embeddings'; }),
    'поиск по эмбеддингам находит их группу (' + embItem.key + ')');

  // Поиск по параметру вне набора модуля (models_main) — здесь его НЕТ.
  const ctx2b = mkCtx(ADMIN, CATALOG_ADMIN,
                      { route: '#/modules/embeddings/settings', search: 'main_model' });
  eq(computed.currentTabGroups.call(ctx2b).length, 0,
    'параметры чужой группы (models_main) на этой странице не находятся');

  // Мусорный запрос — пусто (и это НЕ «нет параметров каталога»).
  const ctx3 = mkCtx(ADMIN, CATALOG_ADMIN,
                     { route: '#/modules/embeddings/settings', search: 'zzz-' + keyItem.key });
  eq(computed.currentTabGroups.call(ctx3).length, 0, 'нерелевантный запрос → пусто');
  ok(computed.currentTabItemCount.call(ctx3) > 0,
    'счётчик вкладки не зависит от поиска (пустой блок не подменяет поиск)');
}

// ── (3) обычный пользователь: отказ на уровне маршрута сохранён ───────────
{
  const plain = mkCtx(PLAIN, CATALOG_USER, { route: '#/' });
  eq(computed.isGlobalAdmin.call(plain), false, 'plain: не админ');
  eq(methods.canViewTab.call(plain, 'mod_embeddings'), false,
    'plain: страница модуля запрещена (раздел «Модули» недоступен)');
  plain._toasts.length = 0;
  plain.applyRoute('#/modules/embeddings');
  eq(plain.route, '#/', 'plain: адрес модуля редиректит на #/');
  eq(plain._toasts.length, 1, 'plain: ровно один тост отказа');
  eq(plain._toasts[0][0], 'Нет доступа к разделу', 'plain: честный отказ прав');
  // Настоящий серверный фильтр для не-админа подтверждён снимком: секретные
  // ключи группа объявляет, но не-админу они не приходят (несекретные
  // участники группы — например «Квоты: группы ключей» — остаются, поэтому
  // проверяем именно секреты и реальную убыль набора).
  eq(itemsOfGroup(CATALOG_USER, 'keys_llm')
      .filter(function (it) { return it.secret; }).length, 0,
    'не-админу сервер НЕ отдаёт секретные ключи (реальный фильтр прав)');
  ok(itemsOfGroup(CATALOG_USER, 'keys_llm').length < keyItems.length,
    'набор keys_llm у не-админа реально меньше, чем у админа');
  ok(keyItems.filter(function (it) { return it.secret; }).length > 0,
    'у админа те же секреты присутствуют (маскированно)');
  ok(itemsOfGroup(CATALOG_USER, 'models_embeddings').length === 16,
    'не-админ видит те же 16 несекретных параметров того же модуля');

  // Глобальный админ по-прежнему открывает страницу без отказа.
  const admin = mkCtx(ADMIN, CATALOG_ADMIN, { route: '#/' });
  eq(methods.canViewTab.call(admin, 'mod_embeddings'), true,
    'admin: страница модуля открыта');
  admin.applyRoute('#/modules/embeddings');
  eq(admin.route, '#/modules/embeddings', 'admin: адрес сохранён');
  eq(admin._toasts.length, 0, 'admin: без тостов отказа');
}

// ── (4) честная причина пустого блока ─────────────────────────────────────
{
  const KEYS_ONLY = { sources: [{ category: 'keys', groups: ['keys_llm'] }] };
  const NO_SOURCES = { sources: [] };

  function emptyCtx(me, catalog, desc, extra) {
    const ctx = mkCtx(me, catalog, extra || {});
    Object.defineProperty(ctx, 'currentTab', {
      configurable: true, get: function () { return desc; },
    });
    Object.defineProperty(ctx, 'currentTabIsConfig', {
      configurable: true, get: function () { return true; },
    });
    return ctx;
  }

  // 4a. Ничего не пришло вообще (сервер/база) — «не загружены», не «права».
  const noData = emptyCtx(ADMIN, { items: [], groups: [] }, KEYS_ONLY);
  eq(computed.emptyTabCause.call(noData), 'no-data', 'пустой ответ → no-data');
  eq(computed.emptyTabTitle.call(noData), 'Параметры не загружены',
    'заголовок честно говорит о загрузке');
  ok(computed.emptyTabReason.call(noData).indexOf('по правам') < 0,
    'админу не приписывается фильтр прав при пустом ответе');

  // 4b. Каталог действительно не назначает параметров вкладке — «нет
  //     параметров», без обвинения прав.
  const noneCtx = emptyCtx(ADMIN, CATALOG_ADMIN, NO_SOURCES);
  eq(computed.emptyTabCause.call(noneCtx), 'none',
    'нет объявленных параметров → причина «none»');
  eq(computed.emptyTabTitle.call(noneCtx), 'На этой вкладке нет параметров',
    'заголовок: параметров нет');
  const noneReason = computed.emptyTabReason.call(noneCtx);
  ok(noneReason.indexOf('по правам') < 0,
    'без реального фильтра слова «по правам» НЕ появляются: ' + noneReason);
  ok(noneReason.indexOf('не назначает') >= 0,
    'честная формулировка «каталог не назначает»');

  // 4c. Реальный фильтр прав (не-админ + вкладка секретных ключей, которых
  //     сервер не отдал) — именно здесь «по правам» правомерно.
  const filtered = emptyCtx(PLAIN, CATALOG_USER, KEYS_ONLY);
  eq(computed.emptyTabCause.call(filtered), 'filtered',
    'секретная вкладка не-админа → причина «filtered»');
  eq(computed.emptyTabTitle.call(filtered),
    'На этой вкладке нет доступных параметров', 'заголовок: нет доступных');
  ok(computed.emptyTabReason.call(filtered).indexOf(
    'сервер отфильтровал их по правам') >= 0,
    '«фильтр прав» назван только когда он реально сработал');

  // 4d. Та же вкладка у глобального админа: фильтра нет — и обвинения нет.
  const adminKeys = emptyCtx(ADMIN, CATALOG_USER, KEYS_ONLY);
  eq(computed.emptyTabCause.call(adminKeys), 'none',
    'у админа права не могут быть причиной пустоты');

  // 4e. Область (чат) — отдельная честная причина, не «права».
  const scope = emptyCtx(ADMIN, CATALOG_ADMIN, NO_SOURCES, { scopeKind: 'chat' });
  eq(computed.emptyTabCause.call(scope), 'scope', 'чат-скоуп → причина «scope»');
  ok(computed.emptyTabReason.call(scope).indexOf('Весь бот') >= 0,
    'чат-скоуп: честный совет переключить область');

  // 4f. Страница модуля БЕЗ объявления групп (реестр не пришёл) — «нет
  //     параметров», а не «права»: это и был дефект владельца.
  const noDecl = mkCtx(ADMIN, CATALOG_ADMIN,
                       { route: '#/modules/embeddings', dropRegistry: true });
  eqJson(computed.currentTab.call(noDecl).sources, [],
    'без реестра источников нет (объявление неизвестно)');
  eq(computed.emptyTabCause.call(noDecl), 'none',
    'unknown declaration → «нет параметров», не «права»');
  ok(computed.emptyTabReason.call(noDecl).indexOf('по правам') < 0,
    'ложное обвинение прав убрано с пустой страницы модуля');
}

// ── (5) шаблон: заголовок и причина приходят из вычисляемых полей ─────────
{
  ok(INDEX.indexOf('data-empty-tab') >= 0, 'блок пустой вкладки на месте');
  ok(INDEX.indexOf('{{ emptyTabTitle }}') >= 0,
    'заголовок пустого блока — из emptyTabTitle (не хардкод)');
  ok(INDEX.indexOf(':data-empty-cause="emptyTabCause"') >= 0,
    'причина пустоты видна в DOM (data-empty-cause) для проверок');
  ok(INDEX.indexOf('На этой вкладке нет доступных параметров\n') < 0,
    'старый хардкод заголовка удалён');
}

console.log('MOD-ACL-UX-01 M4 MODULE PARAMS OK — ' + checks
  + ' проверок; групп объявлено: ' + DECLARED.length
  + '; параметров у админа: ' + (embItems.length + keyItems.length));
