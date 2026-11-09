'use strict';
/* MOD-ACL-UX-01 M3 — страницы модулей реестра и честный отказ.
 *
 * Проверяет РЕАЛЬНУЮ логику web/app.js (не grep):
 *   (1) каждый модуль реестра (snapshot от services/module_registry.py —
 *       передаётся первым аргументом) открывается своей страницей у
 *       глобального админа: `canViewTab('mod_<slug>') === true` и applyRoute
 *       сохраняет `#/modules/<slug>`;
 *   (2) тот же модуль НЕ открывается обычному пользователю (нет раздела
 *       «Модули») — отказ «Нет доступа к разделу» + редирект на `#/`;
 *   (3) неизвестный `mod_*` (нет такого модуля) — отказ даже админу;
 *   (4) `isGlobalAdmin` доверяет серверному `me.is_global_admin` при
 *       не-legacy имени роли и остаётся false для обычного юзера; legacy-
 *       эвристика работает только когда поля нет;
 *   (5) у панели векторной памяти три РАЗНЫХ состояния: отказ (403) / ошибка /
 *       данные (пустые индексы), а не одно «Панель недоступна».
 *
 * Запуск: node tests/js/mod_acl_ux_m3_module_routes_test.js <snapshot.json>
 * (snapshot готовит tests/test_mod_acl_ux_01_m3_module_routes.py из живого
 *  реестра — второй копии списка модулей нет).
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

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');

const data = captured.data();
const methods = captured.methods;
const computed = captured.computed;
const MODULES = data.modules;
const TABS = data.tabs;

// ── snapshot реестра (единственный источник — services/module_registry.py) ──
// Аргумент задаёт живой snapshot из Python-теста; без него берём сохранённый
// снимок (его соответствие реестру проверяет тот же Python-тест).
const snapshotPath = process.argv[2]
  || path.join(__dirname, '..', 'fixtures', 'module_registry_visible.json');
assert.ok(fs.existsSync(snapshotPath), 'нет snapshot реестра: ' + snapshotPath);
const specs = JSON.parse(fs.readFileSync(snapshotPath, 'utf8'));
assert.ok(Array.isArray(specs) && specs.length >= 9,
  'snapshot реестра должен содержать все видимые модули');

// Реестр доливается в тот же список модулей, что и в проде (loadConfig).
// Мутация глобального списка — как в production-коде (data.modules === MODULES).
// Снимок ДО merge нужен для холодного старта (адрес модуля реестра приходит
// раньше, чем `loadConfig` доливает реестр).
const PRE_MERGE = JSON.parse(JSON.stringify(MODULES));
methods.f3ApplyModuleRegistry.call({
  modules: MODULES, _f4Registry: {}, workspaceModule: null,
}, specs);

function mkCtx(me) {
  const ctx = {
    me: me,
    tabs: TABS,
    modules: MODULES,
    route: '#/__none__',
    activeTab: 'status',
    accessOpen: null,
    iaV2: true,
    activeChatId: null,
    chatLoreChats: [],
    _toasts: [],
    // Production-состояние после `loadConfig`: реестр уже долит.
    _f3RegistryApplied: true,
    _f4Registry: {},
  };
  ctx.toast = function (m, k) { ctx._toasts.push([m, k]); };
  ctx.syncBackButton = function () {};
  ctx.setTab = function (id) { ctx.activeTab = id; };
  ctx._flagTabHidden = methods._flagTabHidden;
  ctx.isDmCtx = function () { return false; };
  ctx.isLocalAdminCtx = methods.isLocalAdminCtx;
  ctx.canViewTab = methods.canViewTab;
  ctx.hasPerm = methods.hasPerm;
  ctx.moduleBySlug = methods.moduleBySlug;
  ctx.moduleByTab = methods.moduleByTab;
  ctx._isModuleTab = methods._isModuleTab;
  ctx._tabDescriptorFor = methods._tabDescriptorFor;
  ctx.applyRoute = function (h) { return methods.applyRoute.call(ctx, h); };
  ctx.f3ApplyModuleRegistry = function (mods) {
    return methods.f3ApplyModuleRegistry.call(ctx, mods);
  };
  Object.defineProperty(ctx, 'permissions', {
    get: function () { return computed.permissions.call(this); },
  });
  Object.defineProperty(ctx, 'isGlobalAdmin', {
    get: function () { return computed.isGlobalAdmin.call(this); },
  });
  return ctx;
}

const ADMIN = {
  // Авторизованный глобальный админ: сервер говорит is_global_admin=true,
  // имя роли — НЕ legacy «admin» (кастомная роль role_type=global_admin).
  role_name: 'куратор проекта', is_global_admin: true,
  permissions: { wildcard: true },
};
// Админ БЕЗ полного wildcard: раздел «Модули» доступен (секция reactions),
// но config-секций модулей нет — так проверяется именно новый путь
// «страница модуля = раздел Модули», без поблажек wildcard.
const MODULES_ADMIN = {
  role_name: 'куратор проекта', is_global_admin: true,
  permissions: { sections: ['reactions'] },
};
const PLAIN = {
  role_name: 'участник', is_global_admin: false,
  permissions: { sections: ['status'] },
};

let checks = 0;
function ok(cond, msg) {
  assert.ok(cond, msg);
  checks += 1;
}
function eq(a, b, msg) {
  assert.strictEqual(a, b, msg);
  checks += 1;
}

function tabOf(spec) {
  return spec.parent_id
    ? (spec.config_tab || ('mod_' + spec.id))
    : ('mod_' + spec.id);
}
function hasStaticTab(tab) {
  return TABS.some(function (t) { return t.id === tab; });
}
// Рендер страницы: активная вкладка разрешается в config-дескриптор.
// (`currentTab` — computed; в живом Vue он уже развёрнут, в юните — нет.)
function rendersAsConfig(ctx) {
  const tab = computed.currentTab.call(ctx);
  return computed.currentTabIsConfig.call({ currentTab: tab });
}

// ── (1) авторизованный глобальный админ: каждый модуль реестра открывается ──
{
  const admin = mkCtx(ADMIN);
  eq(computed.isGlobalAdmin.call(admin), true,
    'admin: isGlobalAdmin=true по серверному is_global_admin');
  specs.forEach(function (spec) {
    const tab = tabOf(spec);
    eq(methods.canViewTab.call(admin, tab), true,
      'admin: страница модуля «' + spec.id + '» (' + tab + ') доступна');
    const ctx = mkCtx(ADMIN);
    methods.applyRoute.call(ctx, '#/modules/' + spec.id);
    eq(ctx.route, '#/modules/' + spec.id,
      'admin: #/modules/' + spec.id + ' остаётся открытым');
    eq(ctx.activeTab, tab,
      'admin: #/modules/' + spec.id + ' → вкладка ' + tab);
    eq(ctx._toasts.length, 0,
      'admin: без тоста отказа на #/modules/' + spec.id);
    // Страница модуля РЕНДЕРИТСЯ: активная вкладка — config (не пустой экран).
    eq(rendersAsConfig(ctx), true,
      'admin: страница модуля «' + spec.id + '» рендерится как config');
  });
}

// ── (1c) ХОЛОДНЫЙ deep-link: адрес модуля реестра до merge ────────────────
// Реестр приходит асинхронно (loadConfig). Пока merge нет, адрес
// `#/modules/<slug>` НЕ считается неизвестным: никакого «Модуль не найден»,
// адрес держится и разрешается после merge обычным гейтом.
// `_wsModuleById` читает ОДИН общий список модулей (как в проде), поэтому
// холодный старт воспроизводится возвратом списка к состоянию до merge.
function resetModulesToPreMerge() {
  MODULES.length = 0;
  PRE_MERGE.forEach(function (m) { MODULES.push(JSON.parse(JSON.stringify(m))); });
}
function coldCtx(me) {
  const ctx = mkCtx(me);
  ctx.route = '#/';
  delete ctx._f3RegistryApplied;      // реестр ещё не долит (как на boot)
  ctx._f4Registry = {};
  return ctx;
}
{
  // (1c-1) глобальный админ: страница открывается, тостов НЕТ
  resetModulesToPreMerge();
  const coldAdmin = coldCtx(ADMIN);
  methods.applyRoute.call(coldAdmin, '#/modules/embeddings');
  eq(coldAdmin._toasts.length, 0,
    'cold admin: до merge нет ложного «Модуль не найден»');
  eq(coldAdmin._pendingModuleRoute, '#/modules/embeddings',
    'cold admin: заявленный адрес модуля сохранён до merge');
  eq(coldAdmin.route, '#/',
    'cold admin: до merge адрес не переписывается на витрину');
  coldAdmin.f3ApplyModuleRegistry(specs);
  eq(coldAdmin.route, '#/modules/embeddings',
    'cold admin: после merge страница модуля открыта');
  eq(coldAdmin.activeTab, 'mod_embeddings',
    'cold admin: активная вкладка — страница модуля');
  eq(rendersAsConfig(coldAdmin), true,
    'cold admin: страница модуля рендерится');
  eq(coldAdmin._toasts.length, 0,
    'cold admin: ни одного тоста за всю холодную загрузку');
  eq(coldAdmin._pendingModuleRoute, null,
    'cold admin: отложенный адрес снят после разрешения');

  // (1c-2) пользователь без раздела «Модули»: ровно один честный отказ
  resetModulesToPreMerge();
  const coldPlain = coldCtx(PLAIN);
  methods.applyRoute.call(coldPlain, '#/modules/embeddings');
  eq(coldPlain._toasts.length, 0,
    'cold plain: до merge нет ложного «Модуль не найден»');
  eq(coldPlain._pendingModuleRoute, '#/modules/embeddings',
    'cold plain: адрес держится до merge');
  coldPlain.f3ApplyModuleRegistry(specs);
  eq(coldPlain._toasts.length, 1,
    'cold plain: ровно ОДИН тост (без дубля «не найден» + «нет доступа»)');
  eq(coldPlain._toasts[0][0], 'Нет доступа к разделу',
    'cold plain: сообщение — честный отказ прав');
  eq(coldPlain.route, '#/',
    'cold plain: конечный адрес — #/');

  // (1c-3) действительно неизвестный адрес ПОСЛЕ merge остаётся неизвестным
  resetModulesToPreMerge();
  const coldTypo = coldCtx(ADMIN);
  methods.applyRoute.call(coldTypo, '#/modules/нет_такого_модуля_x');
  eq(coldTypo._toasts.length, 0, 'cold typo: до merge молчим');
  coldTypo.f3ApplyModuleRegistry(specs);
  eq(coldTypo._toasts.length, 1,
    'cold typo: после merge — один честный «Модуль не найден»');
  eq(coldTypo._toasts[0][0], 'Модуль не найден',
    'cold typo: именно «Модуль не найден»');
  eq(coldTypo.route, '#/modules',
    'cold typo: неизвестный адрес → витрина «Модули»');

  // production-состояние для остальных блоков: реестр долит
  resetModulesToPreMerge();
  methods.f3ApplyModuleRegistry.call({
    modules: MODULES, _f4Registry: {}, workspaceModule: null,
  }, specs);
}

// ── (1b) админ без wildcard: новый путь «модуль без своей config-вкладки» ──
// До фикса такие модули не открывались НИКОМУ (id не находился в TABS).
{
  const weak = mkCtx(MODULES_ADMIN);
  eq(methods.canViewTab.call(weak, 'modules'), true,
    'modules-admin: раздел «Модули» доступен');
  let generated = 0;
  specs.forEach(function (spec) {
    const tab = tabOf(spec);
    if (hasStaticTab(tab)) {
      // Статические config-вкладки НЕ ослаблены: их гейт — свои секции.
      return;
    }
    generated += 1;
    eq(methods.canViewTab.call(weak, tab), true,
      'modules-admin: страница модуля «' + spec.id + '» (' + tab
      + ') доступна по разделу «Модули»');
    const ctx = mkCtx(MODULES_ADMIN);
    methods.applyRoute.call(ctx, '#/modules/' + spec.id);
    eq(ctx.route, '#/modules/' + spec.id,
      'modules-admin: #/modules/' + spec.id + ' открывается');
    eq(rendersAsConfig(ctx), true,
      'modules-admin: страница «' + spec.id + '» рендерится');
  });
  ok(generated >= 1,
    'реестр содержит хотя бы один модуль без статической config-вкладки');
  // Контроль направления отказа: модуль со СВОЕЙ config-вкладкой (секции
  // flags/limits) этому админу по-прежнему не открыт — гейт не ослаблен.
  eq(methods.canViewTab.call(weak, 'mod_initiative'), false,
    'modules-admin: статическая вкладка модуля не открывается «за компанию»');
}

// ── (2) обычный пользователь: отказ по каждому модулю ─────────────────────
{
  const plain = mkCtx(PLAIN);
  eq(computed.isGlobalAdmin.call(plain), false,
    'plain: isGlobalAdmin=false');
  specs.forEach(function (spec) {
    const tab = tabOf(spec);
    eq(methods.canViewTab.call(plain, tab), false,
      'plain: страница модуля «' + spec.id + '» (' + tab + ') запрещена');
    const ctx = mkCtx(PLAIN);
    methods.applyRoute.call(ctx, '#/modules/' + spec.id);
    eq(ctx.route, '#/',
      'plain: #/modules/' + spec.id + ' редиректит на #/');
    eq(ctx._toasts.length, 1,
      'plain: ровно один тост отказа на #/modules/' + spec.id);
    eq(ctx._toasts[0][0], 'Нет доступа к разделу',
      'plain: честное сообщение об отказе');
  });
}

// ── (3) неизвестный mod_* — отказ даже админу ────────────────────────────
{
  const admin = mkCtx(ADMIN);
  const unknown = 'mod_нет_такого_модуля';
  eq(methods.canViewTab.call(admin, unknown), false,
    'admin: неизвестный mod_* запрещён');
  const ctx = mkCtx(ADMIN);
  methods.applyRoute.call(ctx, '#/modules/нет_такого_модуля');
  eq(ctx.route, '#/modules', 'admin: неизвестный slug → витрина «Модули»');
  const ctx2 = mkCtx(ADMIN);
  ctx2.activeTab = unknown;
  eq(computed.currentTab.call(ctx2), null,
    'неизвестный mod_* не даёт дескриптор вкладки');
}

// ── (4) isGlobalAdmin: сервер > legacy-эвристика ─────────────────────────
{
  eq(computed.isGlobalAdmin.call(mkCtx(ADMIN)), true,
    'server-truth: is_global_admin=true с не-legacy ролью → админ');
  eq(computed.isGlobalAdmin.call(mkCtx(PLAIN)), false,
    'server-truth: is_global_admin=false → не админ');
  // Сервер говорит «нет» — не повышаем по имени роли (направление отказа).
  eq(computed.isGlobalAdmin.call(mkCtx({
    role_name: 'admin', is_global_admin: false,
    permissions: { wildcard: true },
  })), false,
  'server-truth: явный is_global_admin=false старше legacy-имени/wildcard');
  // Поле отсутствует (старый сервер/стенд) — работает прежняя эвристика.
  eq(computed.isGlobalAdmin.call(mkCtx({ role_name: 'admin' })), true,
    'legacy-fallback: роль admin без поля → админ');
  eq(computed.isGlobalAdmin.call(mkCtx({
    role_name: 'user', permissions: { wildcard: true },
  })), true, 'legacy-fallback: wildcard без поля → админ');
  eq(computed.isGlobalAdmin.call(mkCtx({ role_name: 'user' })), false,
    'legacy-fallback: обычный юзер без поля → не админ');
}

// ── (5) панель векторной памяти: отказ ≠ ошибка ≠ пустые данные ──────────
(async function panelStates() {
  const ApiError = function (status, message) {
    this.status = status;
    this.message = message;
  };

  function base() {
    return {
      embeddingsPanel: null, embeddingsBusy: false,
      embeddingsDenied: false, embeddingsError: '',
      me: ADMIN,
    };
  }

  // отказ прав
  let ctx = base();
  ctx.api = async function () { throw new ApiError(403, 'permission denied'); };
  await methods.loadEmbeddingsPanel.call(ctx);
  eq(ctx.embeddingsDenied, true, 'panel: 403 → состояние «нет доступа»');
  eq(ctx.embeddingsError, '', 'panel: 403 не выдаётся за ошибку');
  eq(ctx.embeddingsPanel, null, 'panel: 403 не подменяется данными');

  // техническая ошибка
  ctx = base();
  ctx.api = async function () { throw new ApiError(500, 'HTTP 500'); };
  await methods.loadEmbeddingsPanel.call(ctx);
  eq(ctx.embeddingsDenied, false, 'panel: ошибка ≠ отказ прав');
  eq(ctx.embeddingsError, 'HTTP 500', 'panel: ошибка с причиной');
  eq(ctx.embeddingsPanel, null, 'panel: ошибка не подменяется данными');

  // сеть
  ctx = base();
  ctx.api = async function () { throw new ApiError(0, 'network'); };
  await methods.loadEmbeddingsPanel.call(ctx);
  eq(ctx.embeddingsError, 'нет связи с сервером', 'panel: обрыв сети — своя причина');
  eq(ctx.embeddingsDenied, false, 'panel: обрыв сети ≠ отказ прав');

  // успех с пустыми индексами
  const empty = { indexes: [], lease: null, provider: {}, vector_memory: {} };
  ctx = base();
  ctx.api = async function () { return empty; };
  await methods.loadEmbeddingsPanel.call(ctx);
  eq(ctx.embeddingsPanel, empty, 'panel: данные показаны');
  eq(ctx.embeddingsDenied, false, 'panel: данные ≠ отказ');
  eq(ctx.embeddingsError, '', 'panel: данные ≠ ошибка');

  // 403 не должен оставлять «хвост» ошибки от прошлой загрузки
  ctx = base();
  ctx.embeddingsError = 'старая ошибка';
  ctx.api = async function () { throw new ApiError(403, 'permission denied'); };
  await methods.loadEmbeddingsPanel.call(ctx);
  eq(ctx.embeddingsError, '', 'panel: повторная загрузка сбрасывает прошлую причину');

  console.log('MOD-ACL-UX-01 M3 MODULE ROUTES OK — ' + checks + ' проверок, модулей в реестре: ' + specs.length);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
