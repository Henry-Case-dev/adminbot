'use strict';
/* MOD-ACL-UX-01 M4A W2a (2.58.211) — вкладки страницы модуля.

Предмет (MAC-S5-198 / MAC-S5-OVW-01 / MAC-AC-08), контракты брифа W2a
(ARCH_DECISION §1, К-1…К-8):
  1) `workspaceTabKeyTarget` — чистая клавиатурная арифметика: стрелки/Home/End
     без wrap, модификаторы/composition не перехватываются;
  2) статические срезы `index.html`/`app.css`: `@keydown` на полосе,
     roving `:tabindex`, сохранённые `role/aria-selected/aria-current`,
     `[data-module-checked]` + `.module-card-checked`;
  3) память вкладок: roundtrip, изоляция scope, невалидные записи,
     битый JSON, исключение `setItem`, лимит 60;
  4) `workspaceDefaultTab`: память → живой Обзор → settings → первый → overview;
  5) `workspace` computed: явный hash всегда побеждает, bare-адрес = дефолт;
  6) `openWorkspaceTab` пишет память и навигирует;
  7) `setActiveChat`: вкладка сохраняется, пишется ключ НОВОГО scope, память
     чужого чата не копируется, при возврате — своя вкладка;
  8) свежесть: `checked_at` → «Проверено:», `observed_at` НИКОГДА не
     активность, `observed=null` — честное «Измерение не подтверждено».

Всё проверяется на РЕАЛЬНОМ `web/app.js` (Vue-опции перехватываются), каталог
карточек — из того же снимка DTO, что у остальных M4A-юнитов.

Запуск: node tests/js/mod_acl_ux_m4a_w2a_tabs_freshness_test.js
*/
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const INDEX_HTML = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_CSS = fs.readFileSync(
  path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');

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

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');

const { applyModuleDto } = require('./module_fixture.js');
const data = applyModuleDto(captured);
const methods = captured.methods;
const computed = captured.computed;
const MODULES = data.modules;
const TABS = data.tabs;
const MEMORY_KEY = 'adminbot.module_tab';

function moduleById(id) {
  return MODULES.filter(function (m) { return m.id === id; })[0];
}
function clearStorage() {
  Object.keys(_storage._s).forEach(function (k) { delete _storage._s[k]; });
}
function memoryRaw() {
  const raw = _storage._s[MEMORY_KEY];
  return raw ? JSON.parse(raw) : null;
}

// Контекст «как в проде»: методы app.js + данные активного scope.
// `_contentTabs` — данные конфига, которых в node нет: предикат содержимого
// подменён ЯВНЫМ набором (сама формула `workspaceTabHasContent` проверяется
// отдельно — round1025 d2 и Playwright), контракт W2a — ПОРЯДОК разрешения.
function mkCtx(overrides) {
  const ctx = Object.assign({}, methods, {
    modules: MODULES,
    tabs: TABS,
    route: '#/modules/search',
    activeTab: 'mod_search',
    activeChatId: -100,
    scopeKind: 'chat',
    scopeEpoch: 0,
    // «Данные scope загружены» (W2a: только тогда судим о содержимом).
    configItems: [{ key: 'stub.item', value: true }],
    configGroups: [],
    moduleTabMemory: {},
    _contentTabs: ['overview', 'settings', 'limits', 'models'],
    workspaceTabHasContent: function (m, tabId) {
      if ((m.tabs || []).indexOf(tabId) < 0) return false;
      return this._contentTabs.indexOf(tabId) >= 0;
    },
    navigateTo: function (r) { this.nav = r; },
    scopeOpen: false,
    syncActiveChatTitle: function () {},
    loadConfig: function () { this.loads = (this.loads || 0) + 1; },
    loadKeyStatus: function () {},
    canViewTab: function () { return false; },
    isGlobalAdmin: false,
  }, overrides || {});
  // computed-свойства app.js читаются тем же путём, что в шаблоне.
  ['workspace', 'workspaceTab', 'workspaceTabs'].forEach(function (name) {
    Object.defineProperty(ctx, name, {
      configurable: true,
      get: function () { return computed[name].call(this); },
    });
  });
  return ctx;
}

let checks = 0;
function ok(cond, msg) {
  assert.ok(cond, msg);
  checks += 1;
}
function eq(a, b, msg) {
  assert.strictEqual(a, b, msg);
  checks += 1;
}

(function run() {
  // ══ (1) workspaceTabKeyTarget: клавиатура без DOM ═══════════════════════
  {
    const tabs = [{ id: 'overview' }, { id: 'settings' }, { id: 'limits' }];
    const target = function (cur, key) {
      return methods.workspaceTabKeyTarget.call(mkCtx(), cur, key, tabs);
    };
    eq(target('overview', 'ArrowRight'), 'settings', '→ сдвиг вправо');
    eq(target('settings', 'ArrowRight'), 'limits', '→ второй шаг');
    eq(target('limits', 'ArrowRight'), 'limits', '→ на краю без wrap');
    eq(target('overview', 'ArrowLeft'), 'overview', '← на краю без wrap');
    eq(target('limits', 'ArrowLeft'), 'settings', '← сдвиг влево');
    eq(target('settings', 'Home'), 'overview', 'Home → первый');
    eq(target('limits', 'End'), 'limits', 'End → последний');
    eq(target('overview', 'End'), 'limits', 'End из начала');
    // Одиночный таб: стрелки никуда не уводят.
    eq(methods.workspaceTabKeyTarget.call(mkCtx(), 'overview', 'ArrowRight',
      [{ id: 'overview' }]), 'overview', 'один таб: → остаётся');
    eq(methods.workspaceTabKeyTarget.call(mkCtx(), 'overview', 'ArrowLeft',
      [{ id: 'overview' }]), 'overview', 'один таб: ← остаётся');
    // Необработанные клавиши — не наша забота (Tab/Enter/буквы).
    ['Tab', 'Enter', ' ', 'a', 'ArrowUp', 'ArrowDown', ''].forEach(function (k) {
      eq(target('settings', k), '', '«' + k + '» не перехватывается');
    });
    // Модификаторы и composition — не перехватываются.
    [{ key: 'ArrowRight', ctrlKey: true },
     { key: 'ArrowRight', altKey: true },
     { key: 'ArrowRight', metaKey: true },
     { key: 'ArrowRight', shiftKey: true },
     { key: 'ArrowRight', isComposing: true }].forEach(function (ev) {
      eq(target('overview', ev), '', 'модификатор/composition: ' +
        JSON.stringify(Object.keys(ev).filter(function (k) {
          return ev[k] === true;
        })));
    });
    // Неизвестный текущий → первый таб (не «сдвиг на соседа»).
    eq(target('ghost', 'Home'), 'overview', 'неизвестный текущий → первый');
    eq(target('ghost', 'End'), 'limits', 'End всё равно ведёт к последнему');
    eq(methods.workspaceTabKeyTarget.call(mkCtx(), 'x', 'ArrowRight', []), '',
      'пустая полоса → ""');
  }

  // ══ (2) Статические срезы разметки/CSS ═════════════════════════════════
  {
    const stripStart = INDEX_HTML.indexOf(
      'workspace-tabs workspace-tabs--scroll');
    const strip = INDEX_HTML.slice(stripStart, stripStart + 1400);
    ok(/@keydown="onWorkspaceTabsKeydown\(\$event\)"/.test(strip),
      'полоса табов обрабатывает клавиатуру');
    ok(/role="tablist"/.test(strip), 'role=tablist сохранён');
    ok(/:tabindex="workspaceTab === wt\.id \? 0 : -1"/.test(strip),
      'roving tabindex (0 у активного, -1 у остальных)');
    ok(/:aria-selected="workspaceTab === wt\.id"/.test(strip),
      'aria-selected сохранён');
    ok(/:aria-current="workspaceTab === wt\.id \? 'page' : null"/.test(strip),
      'aria-current сохранён');
    ok(/@click="openWorkspaceTab\(wt\.id\)"/.test(strip),
      'клик по табу идёт через openWorkspaceTab');
    // Роль tabpanel у <main> не перестраивается (BACKLOG_ONLY, W2a §2.1).
    ok(/:role="workspaceModule && workspace\.door === 'modules' \? 'tabpanel' : null"/.test(INDEX_HTML),
      'role=tabpanel у main сохранён');

    const footer = INDEX_HTML.slice(INDEX_HTML.indexOf('<div class="module-card-footer">'));
    const footerBlock = footer.slice(0, footer.indexOf('</article>'));
    ok(/data-module-checked="m\.id"/.test(footerBlock),
      'футер карточки несёт [data-module-checked] (m.id)');
    ok(/moduleFreshness\(m\)\.checked/.test(footerBlock),
      'футер читает единый helper свежести');
    ok(/data-module-open/.test(footerBlock),
      'кнопка «Открыть» осталась в футере');
    ok(APP_CSS.indexOf('.module-card-checked {') >= 0,
      'стиль .module-card-checked добавлен');
    const cssRule = APP_CSS.slice(APP_CSS.indexOf('.module-card-checked {'),
      APP_CSS.indexOf('.module-card-checked {') + 260);
    ['font-size: 10px', 'color: var(--text-3)', 'white-space: nowrap',
     'overflow: hidden', 'text-overflow: ellipsis', 'min-width: 0'].forEach(
      function (decl) {
        ok(cssRule.indexOf(decl) >= 0, 'CSS: ' + decl);
      });
    // Фонтан свежести в шапке/Обзоре/Времени уже существует — не дублируем.
    const checkedHooks = INDEX_HTML.split('moduleCheckedAt(workspaceModule)')
      .length - 1;
    ok(checkedHooks >= 3, 'шапка/Обзор/Время используют moduleCheckedAt');
  }

  // ══ (3) Память вкладок: запись, изоляция, валидация, лимит ═════════════
  {
    clearStorage();
    const mSearch = moduleById('mod_search');
    const ctx = mkCtx();
    ctx._wsTabMemoryLoad();

    // roundtrip: set → get (значение — ТОЛЬКО id таба).
    ctx._wsTabMemorySet('chat:-100', mSearch.id, 'limits');
    eq(ctx._wsTabMemoryGet('chat:-100', mSearch), 'limits',
      'roundtrip: память вернула «limits»');
    const stored = memoryRaw();
    eq(Object.keys(stored).length, 1, 'один ключ localStorage');
    ok(Object.keys(stored)[0].indexOf('|mod_search') > 0,
      'ключ = scope|module');
    eq(stored['chat:-100|mod_search'], 'limits', 'в JSON только id таба');
    // Ничего, кроме id: нет названий/значений/контента пользователя.
    Object.keys(stored).forEach(function (k) {
      ok(/^(global|chat:-?\d+)\|mod_[a-z_]+$/.test(k), 'ключ только из id');
      ok(/^[a-z_]+$/.test(stored[k]), 'значение только id таба: ' + stored[k]);
    });

    // Изоляция scope: global / чат A / чат B не смешиваются.
    ctx._wsTabMemorySet('global', mSearch.id, 'overview');
    ctx._wsTabMemorySet('chat:-1001', mSearch.id, 'settings');
    ctx._wsTabMemorySet('chat:-1002', mSearch.id, 'models');
    eq(ctx._wsTabMemoryGet('global', mSearch), 'overview', 'global отдельно');
    eq(ctx._wsTabMemoryGet('chat:-1001', mSearch), 'settings', 'чат A отдельно');
    eq(ctx._wsTabMemoryGet('chat:-1002', mSearch), 'models', 'чат B отдельно');

    // Невалидный таб: игнорируется И удаляется из хранилища.
    ctx._wsTabMemorySet('chat:-555', mSearch.id, 'nope_tab');
    eq(ctx._wsTabMemoryGet('chat:-555', mSearch), '', 'невалидный таб → ""');
    ok(!memoryRaw()['chat:-555|mod_search'], 'невалидный таб удалён');

    // Невалидный модуль (реестр загружен): запись удаляется.
    ctx._wsTabMemorySet('chat:-555', 'mod_ghost', 'overview');
    eq(ctx._wsTabMemoryGet('chat:-555', 'mod_ghost'), '', 'нет модуля → ""');
    ok(!memoryRaw()['chat:-555|mod_ghost'], 'устаревший модуль удалён');

    // Реестр ещё НЕ пришёл (modules пуст) → значение не применяется, но и
    // НЕ удаляется: иначе холодный старт стирал бы валидную память до DTO.
    ctx._wsTabMemorySet('chat:-555', 'mod_ghost', 'overview');
    const cold = mkCtx({ modules: [], configItems: [] });
    cold.moduleTabMemory = ctx._wsTabMemoryRead();
    eq(cold._wsTabMemoryGet('chat:-555', 'mod_ghost'), '',
      'без реестра значение не применяется');
    ok(!!memoryRaw()['chat:-555|mod_ghost'],
      'без реестра запись НЕ удаляется (холодный старт)');

    // Вкладка без содержимого: НЕ применяется, но и не удаляется (данные
    // scope могли ещё не прийти — К-5/W2a-комментарий в коде).
    ctx._wsTabMemorySet('chat:-100', mSearch.id, 'prompts');
    eq(ctx._wsTabMemoryGet('chat:-100', mSearch), '',
      'вкладка без содержимого не применяется');
    ok(!!memoryRaw()['chat:-100|mod_search'],
      'запись без содержимого не удаляется (не «устаревшая»)');

    // Битый JSON → {}, без исключения.
    _storage._s[MEMORY_KEY] = '{oops';
    const broken = mkCtx();
    assert.doesNotThrow(function () { broken._wsTabMemoryLoad(); },
      'битый JSON не бросает');
    eq(Object.keys(broken._wsTabMemoryLoad()).length, 0, 'битый JSON → {}');
    _storage._s[MEMORY_KEY] = '["a","b"]';
    eq(Object.keys(mkCtx()._wsTabMemoryLoad()).length, 0, 'массив → {}');
    _storage._s[MEMORY_KEY] = '{"chat:-100|mod_search": 5}';
    eq(Object.keys(mkCtx()._wsTabMemoryLoad()).length, 0,
      'нестроковое значение → {}');

    // private mode: setItem бросает — память живёт в стейте, падения нет.
    clearStorage();
    const priv = mkCtx();
    const origSet = _storage.setItem;
    _storage.setItem = function () { throw new Error('QuotaExceeded'); };
    assert.doesNotThrow(function () {
      priv._wsTabMemorySet('chat:-100', mSearch.id, 'limits');
    }, 'исключение setItem не пробрасывается');
    _storage.setItem = origSet;
    eq(priv._wsTabMemoryGet('chat:-100', mSearch), 'limits',
      'память доступна из стейта при запрещённом localStorage');

    // Лимит 60: переполнение вытесняет самые старые записи.
    clearStorage();
    const lim = mkCtx();
    lim._wsTabMemoryLoad();
    for (let i = 0; i < 65; i++) {
      lim._wsTabMemorySet('global', 'mod_x' + i, 'limits');
    }
    const limRaw = memoryRaw();
    eq(Object.keys(limRaw).length, 60, 'лимит 60 записей');
    ok(!limRaw['global|mod_x0'], 'самая старая запись вытеснена');
    ok(!!limRaw['global|mod_x64'], 'самая новая запись сохранена');
    ok(!limRaw['global|mod_x4'] && !!limRaw['global|mod_x5'],
      'граница вытеснения точная (5…64)');
    clearStorage();
  }

  // ══ (4) workspaceDefaultTab: память → Обзор → settings → первый ═══════
  {
    clearStorage();
    const ctx = mkCtx({ _contentTabs: ['overview', 'settings', 'limits'] });
    ctx._wsTabMemoryLoad();
    const def = function (id, c) {
      return methods.workspaceDefaultTab.call(c || ctx, moduleById(id));
    };

    // «Живой Обзор» (WS_OVERVIEW_LIVE) — статический набор из брифа.
    ['mod_direct', 'mod_initiative', 'mod_sleep'].forEach(function (id) {
      eq(def(id), 'overview', id + ': дефолт «Обзор» (живой контент)');
    });
    eq(methods._moduleHasLiveOverview.call(ctx, { id: 'mod_experience' }), true,
      'mod_experience в наборе живого Обзора');
    eq(methods._moduleHasLiveOverview.call(ctx, { id: 'mod_vision' }), true,
      'mod_vision в наборе живого Обзора');
    eq(methods._moduleHasLiveOverview.call(ctx, moduleById('mod_factcheck')),
      false, 'factcheck НЕ живой Обзор (history не делает живым, W2b)');

    // settings выигрывает у «прокладки».
    ['mod_search', 'mod_budgets', 'mod_web'].forEach(function (id) {
      eq(def(id), 'settings', id + ': дефолт «Основные настройки»');
    });

    // «Время» — policy-экран: только Обзор, память игнорируется.
    ctx._wsTabMemorySet('chat:-100', 'mod_time', 'settings');
    eq(def('mod_time'), 'overview', 'mod_time → «Обзор» всегда');

    // Память выигрывает у дефолта.
    ctx._wsTabMemorySet('chat:-100', 'mod_search', 'limits');
    eq(def('mod_search'), 'limits', 'память выигрывает у settings');

    // Память другого scope НЕ применяется.
    const other = mkCtx({ activeChatId: -200,
                          _contentTabs: ['overview', 'settings'] });
    other.moduleTabMemory = ctx.moduleTabMemory;
    eq(methods.workspaceDefaultTab.call(other, moduleById('mod_search')),
      'settings', 'память чужого чата не применяется');

    // Пустой settings → первый содержательный таб (не overview-заглушка).
    const narrow = mkCtx({ _contentTabs: ['overview', 'limits'] });
    narrow.moduleTabMemory = {};
    eq(methods.workspaceDefaultTab.call(narrow, moduleById('mod_search')),
      'limits', 'пустой settings → первый содержательный');
    const none = mkCtx({ _contentTabs: [] });
    none.moduleTabMemory = {};
    eq(methods.workspaceDefaultTab.call(none, moduleById('mod_search')),
      'overview', 'совсем пустой модуль → «Обзор»');

    // Дефолт НЕ пишется в память (К-4).
    const rawBefore = JSON.stringify(memoryRaw());
    const fresh = mkCtx();
    fresh.moduleTabMemory = {};              // чистая память, без localStorage
    methods.workspaceDefaultTab.call(fresh, moduleById('mod_search'));
    eq(Object.keys(fresh.moduleTabMemory).length, 0,
      'дефолт не создаёт запись памяти');
    eq(JSON.stringify(memoryRaw()), rawBefore,
      'дефолт не переписывает localStorage');
    clearStorage();
  }

  // ══ (5) workspace computed: hash → память/дефолт ═══════════════════════
  {
    clearStorage();
    const withRoute = function (route, overrides) {
      const c = mkCtx(Object.assign({ route: route }, overrides || {}));
      c._wsTabMemoryLoad();
      return c;
    };
    // К-1: явный таб (включая overview) всегда побеждает память/дефолт.
    eq(computed.workspaceTab.call(withRoute('#/modules/search')), 'settings',
      'bare #/modules/search → settings (W2a)');
    eq(computed.workspaceTab.call(withRoute('#/modules/search/overview')),
      'overview', 'явный /overview уважается');
    eq(computed.workspaceTab.call(withRoute('#/modules/search/limits')),
      'limits', 'явный /limits побеждает');
    eq(computed.workspaceTab.call(withRoute('#/modules/direct')),
      'overview', 'bare #/modules/direct → overview');
    const remembered = withRoute('#/modules/search');
    remembered._wsTabMemorySet('chat:-100', 'mod_search', 'limits');
    eq(computed.workspaceTab.call(remembered), 'limits',
      'bare-адрес применяет память');
    eq(computed.workspaceTab.call(
      withRoute('#/modules/search/overview', { activeChatId: -100 })),
      'overview',
      'явный /overview игнорирует память «limits»');

    // Вторая дверь (библиотека промптов) не изменилась.
    const lib = withRoute('#/ai/prompts/factcheck');
    eq(computed.workspace.call(lib).door, 'library', 'дверь библиотеки цела');
    eq(computed.workspace.call(lib).tab, 'synthesizer',
      'библиотека открывает промпт-вкладку модуля');
    clearStorage();
  }

  // ══ (6) openWorkspaceTab: запись памяти + навигация ═══════════════════
  {
    clearStorage();
    const ctx = mkCtx({ route: '#/modules/search' });
    ctx._wsTabMemoryLoad();
    methods.openWorkspaceTab.call(ctx, 'limits');
    eq(ctx.nav, '#/modules/search/limits', 'навигация на выбранный таб');
    eq(ctx._wsTabMemoryGet('chat:-100', 'mod_search'), 'limits',
      'память записана в текущий scope');
    ok(!ctx._wsTabMemoryGet('global', 'mod_search'), 'чужой scope не тронут');

    methods.openWorkspaceTab.call(ctx, 'overview');
    eq(ctx.nav, '#/modules/search', '«Обзор» = bare-адрес');
    eq(ctx._wsTabMemoryGet('chat:-100', 'mod_search'), 'overview',
      'явный выбор «Обзора» тоже запоминается');

    // Память пишется и в global-scope (activeChatId == null).
    const glob = mkCtx({ activeChatId: null, scopeKind: 'global',
                         route: '#/modules/web' });
    glob._wsTabMemoryLoad();
    methods.openWorkspaceTab.call(glob, 'settings');
    eq(glob._wsTabMemoryGet('global', 'mod_web'), 'settings',
      'global scope пишется отдельным ключом');
    clearStorage();
  }

  // ══ (7) setActiveChat: вкладка переживает смену scope ═════════════════
  {
    clearStorage();
    const ctx = mkCtx({
      route: '#/modules/search',
      activeChatId: -1001,
      _contentTabs: ['overview', 'settings', 'limits'],
    });
    ctx._wsTabMemoryLoad();
    ctx._wsTabMemorySet('chat:-1001', 'mod_search', 'limits');
    ctx._wsTabMemorySet('chat:-1001', 'mod_web', 'settings');
    ctx._wsTabMemorySet('chat:-1002', 'mod_search', 'models');
    eq(computed.workspaceTab.call(ctx), 'limits', 'чат A: своя вкладка');

    methods.setActiveChat.call(ctx, -1002);
    eq(ctx.activeChatId, -1002, 'scope переключён на B');
    eq(computed.workspaceTab.call(ctx), 'limits',
      'после смены чата страница осталась на той же вкладке');
    eq(ctx._wsTabMemoryGet('chat:-1002', 'mod_search'), 'limits',
      'вкладка запинена в память НОВОГО scope');
    eq(ctx._wsTabMemoryGet('chat:-1001', 'mod_search'), 'limits',
      'память чата A не перезаписана');
    ok(!ctx._wsTabMemoryGet('chat:-1002', 'mod_web'),
      'память других модулей чужого чата не копируется');
    eq(ctx.loads, 1, 'данные/права перечитываются штатным loadConfig');

    // Возврат в A: восстанавливается СВОЯ вкладка A.
    ctx.route = '#/modules/search';
    methods.setActiveChat.call(ctx, -1001);
    eq(computed.workspaceTab.call(ctx), 'limits', 'чат A: своя вкладка на месте');

    // Явный таб в hash: пин не нужен (hash побеждает и без него).
    const explicit = mkCtx({ route: '#/modules/search/overview',
                             activeChatId: -1001 });
    explicit._wsTabMemoryLoad();
    explicit._wsTabMemorySet('chat:-1002', 'mod_search', 'models');
    methods.setActiveChat.call(explicit, -1002);
    eq(explicit._wsTabMemoryGet('chat:-1002', 'mod_search'), 'models',
      'явный таб в hash память не переписывает');
    eq(computed.workspaceTab.call(explicit), 'overview',
      'явный таб остаётся активным после смены чата');
    clearStorage();
  }

  // ══ (8) Свежесть ≠ активность (К-7/К-8) ═══════════════════════════════
  {
    const CHECKED = '2026-11-17T10:00:00+00:00';
    const OBSERVED_AT = '2026-11-17T11:11:00+00:00';   // момент снимка
    const ACTIVITY = '2026-11-17T09:58:00+00:00';

    const ctx = mkCtx();
    const mSummary = moduleById('mod_summary');
    function withState(patch, gpatch) {
      const st = Object.assign({
        chat_state: 'inherit', desired: true, source: 'global',
        effective_runtime: true, ready: null, observed: null,
        observed_at: OBSERVED_AT, last_activity_at: null,
        emergency_block: false, reason_code: null, pending_restart: false,
        conflict: null, checked_at: CHECKED,
      }, patch || {});
      return Object.assign({}, mSummary, {
        state: st, gate: gpatch === undefined ? null : gpatch,
        permissions: { can_read: true, can_edit: true },
      });
    }
    const checkedLabel = 'Проверено: ' + methods.fmtLogTs.call(ctx, CHECKED);
    const observedLabel = methods.fmtLogTs.call(ctx, OBSERVED_AT);

    // (8a) observed=null (провайдера активности нет): checked есть,
    // активности НЕТ, observed_at нигде не выводится.
    const mNull = withState({});
    const freshNull = methods.moduleFreshness.call(ctx, mNull);
    eq(freshNull.checked, checkedLabel, 'freshness.checked = «Проверено: …»');
    eq(freshNull.activity, '', 'провайдера нет → activity пусто');
    eq(freshNull.observed, null, 'observed=null остаётся null (не false)');
    eq(methods.moduleCheckedAt.call(ctx, mNull), checkedLabel,
      'moduleCheckedAt читает тот же helper');
    eq(methods.moduleActivityText.call(ctx, mNull), '',
      'activity-строка честно пуста');
    const stateNull = methods.moduleStateText.call(ctx, mNull);
    ok(stateNull.indexOf('измерение не подтверждено') >= 0,
      'observed=null → «измерение не подтверждено»: ' + stateNull);
    ok(stateNull.indexOf('работа') < 0,
      'observed=null не утверждает про «работу» (D5): ' + stateNull);
    ok(stateNull.indexOf('Последняя активность') < 0,
      'observed=null не печатает активность');
    const chipsNull = methods.moduleStateChips.call(ctx, mNull);
    const observedChip = chipsNull.filter(function (c) {
      return c.id === 'observed';
    })[0];
    eq(observedChip.text, 'Измерение не подтверждено',
      'чип «Измерение» честен');
    // observed_at — момент снимка: НИГДЕ не подставляется как активность.
    const produced = [stateNull, methods.moduleCheckedAt.call(ctx, mNull),
      methods.moduleActivityText.call(ctx, mNull)]
      .concat(chipsNull.map(function (c) { return c.label + ': ' + c.text; }));
    produced.forEach(function (line) {
      ok(line.indexOf(observedLabel) < 0 && line.indexOf('11:11') < 0,
        'observed_at не выведен как активность: ' + line);
    });

    // (8b) observed=true + провайдер: реальное время активности.
    const mTrue = withState({ observed: true, last_activity_at: ACTIVITY });
    const freshTrue = methods.moduleFreshness.call(ctx, mTrue);
    eq(freshTrue.observed, true, 'observed=true');
    eq(freshTrue.activity,
      'Последняя активность: ' + methods.fmtLogTs.call(ctx, ACTIVITY),
      'activity = last_activity_at (реальная активность)');
    eq(methods.moduleStateText.call(ctx, mTrue), 'Работает',
      'observed=true → «Работает»');
    const chipTrue = methods.moduleStateChips.call(ctx, mTrue)
      .filter(function (c) { return c.id === 'observed'; })[0];
    eq(chipTrue.text,
      'Подтверждено: ' + methods.fmtLogTs.call(ctx, ACTIVITY),
      'чип несёт реальное время активности');

    // (8c) observed=false без провайдера: «нет подтверждённой активности»,
    // не «0 событий» и не «—».
    const mFalse = withState({ observed: false });
    eq(methods.moduleStateText.call(ctx, mFalse),
      'Включено · нет подтверждённой активности',
      'observed=false: честная формулировка');
    eq(methods.moduleStateChips.call(ctx, mFalse)
      .filter(function (c) { return c.id === 'observed'; })[0].text,
      'Нет подтверждённой активности', 'чип observed=false');

    // (8d) старый payload без state: checked из m.gate.checked_at.
    const legacy = Object.assign({}, mSummary, {
      state: null, gate: { checked_at: CHECKED },
      permissions: { can_read: true, can_edit: true },
    });
    eq(methods.moduleCheckedAt.call(ctx, legacy),
      'Проверено: ' + methods.fmtLogTs.call(ctx, CHECKED),
      'fallback m.gate.checked_at сохранён');
    eq(methods.moduleFreshness.call(ctx, legacy).activity, '',
      'без state активности нет');

    // (8e) совсем пустые данные: пустые строки, без «unknown» и падений.
    const empty = Object.assign({}, mSummary, { state: null, gate: null });
    const freshEmpty = methods.moduleFreshness.call(ctx, empty);
    eq(freshEmpty.checked, '', 'нет checked_at → ""');
    eq(freshEmpty.activity, '', 'нет активности → ""');
    eq(freshEmpty.observed, null, 'нет данных → observed=null');
    assert.doesNotThrow(function () {
      methods.moduleFreshness.call(ctx, null);
      methods.moduleCheckedAt.call(ctx, null);
    }, 'moduleFreshness(null) не бросает');
    eq(methods.moduleFreshness.call(ctx, null).checked, '',
      'null-модуль → пустая свежесть');

    // (8f) разные checked_at/observed_at не путаются (защита от подмены).
    const distinct = withState({ checked_at: CHECKED });
    eq(methods.moduleFreshness.call(ctx, distinct).checked, checkedLabel,
      'checked_at — момент снимка');
    ok(methods.moduleFreshness.call(ctx, distinct).activity !== observedLabel,
      'observed_at не стал активностью');
  }

  // ══ (9) W2b-B1: history не дефолт; pending не чистит память ═══════════
  {
    clearStorage();
    const W2B_SLEEP = moduleById('mod_sleep');
    const ctx = mkCtx({
      _contentTabs: ['overview', 'settings', 'limits', 'history'],
    });
    ctx._wsTabMemoryLoad();
    ctx._wsTabMemorySet('chat:-100', W2B_SLEEP.id, 'history');
    // Pending (idle/loading) не применяет память, но и НЕ удаляет её.
    eq(ctx._wsTabMemoryGet('chat:-100', W2B_SLEEP), '',
      'pending history не применяется');
    ok(!!memoryRaw()['chat:-100|mod_sleep'],
      'pending history НЕ удалён из памяти');
    // Даже готовый history не делает bare-адрес «историей».
    ctx.historyMeta = {
      'chat:-100|mod_sleep': {
        source: 'memory.dream.log', status: 'ready', at: 0,
      },
    };
    ctx.dreamLog = [{ id: 1, chat_id: -100, run_at: 1700000000,
                      kind: 'dream', status: 'ok' }];
    eq(methods.workspaceDefaultTab.call(ctx, W2B_SLEEP), 'overview',
      'history никогда не дефолт');
    clearStorage();
  }

  console.log('MOD-ACL-UX-M4A-W2A-TABS-FRESHNESS-OK — ' + checks
    + ' проверок');
  process.exit(0);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
