'use strict';
/* F5 round1025 (ADR-1025-15 D1/D2/D6, §46) — рабочее пространство модуля.
 *
 * Проверяет РЕАЛЬНУЮ логику web/app.js (не grep):
 *   (a) витрина: у каждого модуля есть routeSlug (id без `mod_`) и tabs[];
 *   (b) динамический резолвер `#/modules/<slug>[/<wt>[/<stage>/<key>]]`:
 *       routeToTab = m.tab (RBAC + kill-switch работают как были), depth 0/1/2;
 *   (c) неизвестный slug → `#/modules` + toast (не белый экран);
 *   (d) неприменимая вкладка → дефолт «Обзор»; существующие
 *       `#/modules/budgets|images` совместимы;
 *   (e) шов: openModuleWorkspace → navigateTo (страница), fallback →
 *       openModuleWindow (file:///unit-стаб); точка входа не меняется;
 *   (f) генеральный переключатель = store F4 (нет локального boolean);
 *   (g) инвариант покрытия §9.3: все группы старой вкладки модуля есть на
 *       его странице (missing = []).
 *
 * Запуск: node tests/js/round1025_f5_workspace_route_test.js
 */
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
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
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

function moduleById(id) {
  return MODULES.filter(function (m) { return m.id === id; })[0];
}
function mkCtx(overrides) {
  const toasts = [];
  const ctx = Object.assign({
    route: '#/', iaV2: true, me: { role_name: 'admin' },
    activeTab: 'status', accessOpen: null, tabs: TABS,
    modules: MODULES,
    canViewTab() { return true; },
    _flagTabHidden: methods._flagTabHidden,
    toast(m, k) { toasts.push([m, k]); },
    syncBackButton() {},
    setTab(id) { this.activeTab = id; },
    _toasts: toasts,
  }, overrides || {});
  return ctx;
}
// §9.3: контекст для инварианта покрытия (реальная логика app.js + витрина
// источников TABS[m.tab]).
function mkCoverageCtx(m) {
  const promptGid = {
    mod_factcheck: 'prompts_factcheck', mod_search: 'prompts_search',
    mod_checkup: 'prompts_checkup', mod_direct: 'prompts_direct_chat',
    mod_summary: 'prompts_summary', mod_video_summary: 'prompts_youtube',
    mod_web: 'prompts_web', mod_sleep: 'prompts_memory',
  }[m.id];
  return {
    modules: MODULES, tabs: TABS,
    workspaceModule: m, workspaceTab: 'settings',
    _workspaceGroupsFor: methods._workspaceGroupsFor,
    workspaceGroupTab: methods.workspaceGroupTab,
    _workspacePromptGroup: methods._workspacePromptGroup,
    workspacePromptItems: methods.workspacePromptItems,
    promptStageItems: methods.promptStageItems,
    groupedForTab(t) {
      if (t && t.id === 'prompts') {
        return promptGid
          ? [{ id: promptGid, category: 'prompts', items: [] }] : [];
      }
      const out = [];
      (t && t.sources ? t.sources : []).forEach(function (s) {
        (s.groups || []).forEach(function (gid) {
          out.push({ id: gid, category: s.category, items: [] });
        });
      });
      return out;
    },
    _syntheticGroup: function () { return { id: 'content_media' }; },
  };
}

(async function run() {
  // ── (a) Витрина: routeSlug + tabs ────────────────────────────────────
  {
    assert.strictEqual(MODULES.length, 13, 'a: 13 модулей');
    MODULES.forEach(function (m) {
      assert.strictEqual(m.routeSlug, String(m.id).replace(/^mod_/, ''),
        'a: routeSlug = id без mod_ (' + m.id + ')');
      assert.ok(Array.isArray(m.tabs) && m.tabs.indexOf('overview') >= 0,
        'a: tabs[] с «Обзор» (' + m.id + ')');
    });
    assert.deepStrictEqual(moduleById('mod_factcheck').tabs,
      ['overview', 'settings', 'synthesizer', 'verbalizer', 'models',
       'limits', 'testing'], 'a: карта вкладок Фактчека (§4.2)');
    assert.deepStrictEqual(moduleById('mod_summary').tabs,
      ['overview', 'settings', 'prep', 'clusterizer', 'writer', 'models',
       'limits', 'testing'], 'a: карта вкладок Саммари (§85)');
  }

  // ── (b) Динамический резолвер + RBAC/kill-switch ─────────────────────
  {
    const ctx = mkCtx();
    methods.applyRoute.call(ctx, '#/modules/factcheck');
    assert.strictEqual(ctx.route, '#/modules/factcheck', 'b: маршрут открыт');
    assert.strictEqual(ctx.activeTab, 'mod_factcheck',
      'b: routeToTab(#/modules/factcheck) == m.tab');
    assert.strictEqual(computed.routeDepth.call(ctx), 1, 'b: depth 1');

    const ctx2 = mkCtx();
    methods.applyRoute.call(ctx2, '#/modules/factcheck/synthesizer');
    assert.strictEqual(ctx2.route, '#/modules/factcheck/synthesizer', 'b: вкладка');
    assert.strictEqual(ctx2.activeTab, 'mod_factcheck', 'b: tab тот же');
    assert.strictEqual(computed.routeDepth.call(ctx2), 2, 'b: depth 2');

    const ws = computed.workspace.call(ctx2);
    assert.strictEqual(ws.tab, 'synthesizer', 'b: workspaceTab из hash');
    assert.strictEqual(ws.module.id, 'mod_factcheck', 'b: workspaceModule');

    // routeParent по иерархии (нативная «назад»).
    const back1 = { route: '#/modules/factcheck/synthesizer',
      navigateTo(r) { this._nav = r; } };
    methods.goBack.call(back1);
    assert.strictEqual(back1._nav, '#/modules/factcheck',
      'b: parent вкладки = модуль');
    const back2 = { route: '#/modules/factcheck',
      navigateTo(r) { this._nav = r; } };
    methods.goBack.call(back2);
    assert.strictEqual(back2._nav, '#/modules', 'b: parent модуля = витрина');

    // RBAC: нет права на m.tab → штатный откат на #/.
    const noRbac = mkCtx({ canViewTab(id) { return id !== 'mod_factcheck'; } });
    methods.applyRoute.call(noRbac, '#/modules/factcheck');
    assert.strictEqual(noRbac.route, '#/', 'b: RBAC приоритетнее');

    // kill-switch mod_images: OFF → витрина; ON → mod_images.
    const off = mkCtx({ uiFlag(n) { return n !== 'IMAGE_MODULE_CARD_ENABLED'; } });
    methods.applyRoute.call(off, '#/modules/images');
    assert.strictEqual(off.route, '#/modules', 'b: mod_images OFF → витрина');
    const on = mkCtx({ uiFlag() { return true; } });
    methods.applyRoute.call(on, '#/modules/images');
    assert.strictEqual(on.route, '#/modules/images',
      'b: mod_images ON → mod_images (совместимо)');
  }

  // ── (c) Неизвестный slug → витрина + toast ────────────────────────────
  {
    const ctx = mkCtx();
    methods.applyRoute.call(ctx, '#/modules/unknown-module');
    assert.strictEqual(ctx.route, '#/modules', 'c: неизвестный → витрина');
    assert.ok(ctx._toasts.some(function (t) { return t[0] === 'Модуль не найден'; }),
      'c: понятное сообщение (не белый экран)');
  }

  // ── (b2) вторая дверь §48: #/ai/prompts/<slug>[/<stage>] ──────────────
  {
    const ctx = mkCtx();
    methods.applyRoute.call(ctx, '#/ai/prompts/factcheck');
    assert.strictEqual(ctx.route, '#/ai/prompts/factcheck',
      'b2: маршрут библиотеки сохранён');
    assert.strictEqual(ctx.activeTab, 'prompts',
      'b2: routeToTab(#/ai/prompts/<slug>) == prompts');
    const ws = computed.workspace.call(ctx);
    assert.strictEqual(ws.door, 'library', 'b2: дверь библиотеки');
    assert.strictEqual(ws.module.id, 'mod_factcheck', 'b2: тот же модуль');
    assert.strictEqual(ws.tab, 'synthesizer',
      'b2: библиотека открывает промпт-вкладку модуля');

    const ctx2 = mkCtx();
    methods.applyRoute.call(ctx2, '#/ai/prompts/factcheck/synthesizer');
    const ws2 = computed.workspace.call(ctx2);
    assert.strictEqual(ws2.stage, 'synthesizer',
      'b2: <stage> сохранён (не ушёл в promptKey)');
    assert.strictEqual(ws2.tab, 'synthesizer', 'b2: вкладка этапа');
    assert.strictEqual(ctx2.activeTab, 'prompts', 'b2: tab prompts');

    // Неизвестный slug → чистая библиотека + toast (не status/белый экран).
    const bad = mkCtx();
    methods.applyRoute.call(bad, '#/ai/prompts/unknown-module');
    assert.strictEqual(bad.route, '#/ai/prompts',
      'b2: неизвестный модуль → библиотека');
    assert.ok(bad._toasts.some(function (t) { return t[0] === 'Модуль не найден'; }),
      'b2: понятное сообщение');
  }

  // ── (b3) L-F5S-3: «пустая» библиотечная дверь без промптов ────────────
  {
    // mod_budgets не имеет MODULE_PROMPT_GROUPS → чистая библиотека.
    const ctx = mkCtx();
    methods.applyRoute.call(ctx, '#/ai/prompts/budgets');
    assert.strictEqual(ctx.route, '#/ai/prompts',
      'b3: модуль без промптов → #/ai/prompts (не пустая дверь)');
    assert.strictEqual(ctx.activeTab, 'prompts', 'b3: activeTab prompts');
  }

  // ── (d) Неприменимая вкладка → дефолт «Обзор» ─────────────────────────
  {
    const ctx = mkCtx();
    methods.applyRoute.call(ctx, '#/modules/factcheck/prep');
    assert.strictEqual(ctx.route, '#/modules/factcheck',
      'd: неприменимая вкладка → модуль');
    assert.strictEqual(computed.workspace.call(ctx).tab, 'overview',
      'd: дефолт «Обзор»');
    // Промпт-фокус глубины 2 резолвится в объект.
    const ctx2 = mkCtx();
    methods.applyRoute.call(ctx2, '#/modules/factcheck/synthesizer/foo');
    assert.strictEqual(computed.routeDepth.call(ctx2), 2,
      'd: prompt-фокус = depth 2');
  }

  // ── (d2) «Тестирование»: пустая вкладка не рендерится (T-2700) ────────
  {
    // У mod_checkup нет тестируемых подключений (MODULE_MODEL_BLOCKS = []),
    // deep-link на testing → неприменимая вкладка → дефолт «Обзор».
    const ctx = mkCtx();
    methods.applyRoute.call(ctx, '#/modules/checkup/testing');
    assert.strictEqual(ctx.route, '#/modules/checkup',
      'd2: testing без контента → модуль (не пустая вкладка)');

    // Предикат содержимого: пусто → false; есть блок → true.
    const base = mkCtx();
    base.workspaceTestingBlocks = [];
    assert.strictEqual(
      methods.workspaceTabHasContent.call(base, moduleById('mod_factcheck'), 'testing'),
      false, 'd2: пустое «Тестирование» скрыто');
    base.workspaceTestingBlocks = [{ id: 'direct_main', title: 'Основная модель' }];
    assert.strictEqual(
      methods.workspaceTabHasContent.call(base, moduleById('mod_factcheck'), 'testing'),
      true, 'd2: есть что тестировать → вкладка показана');
  }

  // ── (e) Шов openModuleWorkspace: страница + fallback + RBAC ───────────
  {
    let navTo = null;
    const pageCtx = {
      navigateTo(r) { navTo = r; },
      canViewTab() { return true; },
      openModuleWindow() { throw new Error('навигация не должна открывать модалку'); },
      toast() {},
    };
    methods.openModuleWorkspace.call(pageCtx, moduleById('mod_summary'));
    assert.strictEqual(navTo, '#/modules/summary',
      'e: «Настроить» → страница модуля (§46)');

    // fallback: hash-навигации нет (unit-стаб) → модалка (регресс-путь).
    const fallbackCtx = {
      canViewTab() { return true; },
      openModuleWindow(m) { fallbackCtx.opened = m.id; },
      toast() {},
    };
    methods.openModuleWorkspace.call(fallbackCtx, moduleById('mod_summary'));
    assert.strictEqual(fallbackCtx.opened, 'mod_summary',
      'e: fallback → openModuleWindow (регресс-путь)');

    // RBAC: нет права на «Модули» → ничего не открываем.
    const denied = {
      canViewTab() { return false; },
      navigateTo() { denied.nav = true; },
      openModuleWindow() { denied.opened = true; },
      toast() {},
    };
    methods.openModuleWorkspace.call(denied, moduleById('mod_summary'));
    assert.ok(!denied.nav && !denied.opened, 'e: без права — no-op');

    // Точка входа в шаблоне не меняется.
    const html = require('fs').readFileSync(
      path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
    assert.ok(html.indexOf('openModuleWorkspace(m)') >= 0,
      'e: кнопка «Настроить» вызывает тот же шов');
    assert.ok(html.indexOf('openModuleWindow(m)') < 0,
      'e: прямой вызов регресс-пути в шаблоне запрещён');
  }

  // ── (f) Тумблер = store F4 (нет локального boolean) ───────────────────
  {
    const ctx = mkCtx();
    Object.assign(ctx, {
      storeScope: methods.storeScope,
      storeKey: methods.storeKey,
      getModuleState: methods.getModuleState,
      _moduleById: methods._moduleById,
      _moduleConfigItem: methods._moduleConfigItem,
      _isActiveScope: methods._isActiveScope,
      _moduleRuntimeState: methods._moduleRuntimeState,
    });
    methods.applyRoute.call(ctx, '#/modules/factcheck');
    ctx.scopeKind = 'global';
    ctx.activeChatId = null;
    ctx.configItems = [
      { key: 'flags.factcheck_enabled', value: true, per_chat: false,
        global_value: true },
    ];
    ctx.moduleOptimistic = {};
    ctx.modulePending = {};
    ctx.moduleSaveError = {};
    const m = moduleById('mod_factcheck');
    assert.strictEqual(methods.moduleEnabled.call(ctx, m), true,
      'f: состояние из store');
    // В data() нет локального boolean тумблера workspace.
    assert.strictEqual(data.workspaceEnabled, undefined,
      'f: нет отдельного локального boolean');
  }

  // ── (g) Инвариант покрытия §9.3 ───────────────────────────────────────
  {
    MODULES.forEach(function (m) {
      const cov = computed.workspaceCoverage.call(mkCoverageCtx(m));
      assert.deepStrictEqual(cov.missing, [],
        'g: все группы вкладки модуля достижимы (' + m.id + ')');
    });
  }

  // ── (g2) инвариант покрытия ДОКАЗАТЕЛЕН (падает при потере вкладки) ──
  {
    const orig = moduleById('mod_checkup');
    // Регресс: модуль теряет вкладку «Модели», но её группа остаётся в
    // статических источниках → инвариант ОБЯЗАН это заметить.
    const broken = Object.assign({}, orig, {
      tabs: orig.tabs.filter(function (x) { return x !== 'models'; }),
    });
    const cov = computed.workspaceCoverage.call(mkCoverageCtx(broken));
    assert.ok(cov.missing.indexOf('models_checkup') >= 0,
      'g2: потеря вкладки «Модели» → параметр помечен потерянным');
    // Контроль: целый модуль — missing пусто.
    assert.deepStrictEqual(
      computed.workspaceCoverage.call(mkCoverageCtx(orig)).missing, [],
      'g2: целый модуль покрыт');
  }

  console.log('MODULE-WORKSPACE-OK');
  process.exit(0);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
