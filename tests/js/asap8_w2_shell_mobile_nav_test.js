'use strict';
/* ═══ W2-SHELL / ASAP-UI-02 §2 — JS-контракт shell-навигации.
 *
 * TEST-LIFECYCLE: CONTRACT owner=ASAP-UI-02 §2 (slice FE-SHELL/NAV);
 *   REGRESSION owner=DROPDOWN-WG (валидный тап по опции dropdown поверх
 *   карточек рефракции WIN-GLASS-P0 2.58.85, см. U02.4 ниже)
 *
 * История: изначально файл фиксировал «row B» (постоянная нижняя панель
 * «Статус/Аналитика/Модули/Ещё»). Владелец это решение отверг (сокращает
 * полезную высоту, мешает Telegram Mini App), контракт
 * `docs/ui-navigation-contract.md` §1 запрещает постоянный нижний навбар в
 * любой ориентации. Тест переписан под действующий контракт: навигация =
 * ОДИН drawer, разделы в drawer, «⋯» — только второстепенные действия.
 *
 * Проверяет:
 *   1) реестр разделов/RBAC не изменился, но живёт в drawer (sidebarGroups);
 *      второго списка разделов в меню «⋯» нет;
 *   2) постоянной нижней панели НЕТ: ни разметки, ни CSS, ни метрики
 *      `--bottom-nav-h`, ни её компьютедов;
 *   3) §6.1 v2.1 (решение владельца 26905a89): app-level «…» удалён —
 *      единственная точка входа ⛶ — кнопка в шапке (одна, 44×44, по
 *      реальному режиму); второго входа (пункт меню) и dev-входа
 *      диагностики геометрии в prod-разметке нет;
 *   4) мобильная шапка: ОДНА строка, кнопка навигации (menu-глиф, 44×44),
 *      название раздела один раз, аватар+бейдж реальной роли видимы,
 *      ghost-⛶ остаётся в шапке на любой ширине (display:none не возвращён);
 *   5) U02: mobile dropdown «Раздел: [текущая ▾]» — ПОЛНЫЙ список без
 *      «Логи», выбор через существующий oversightSetTab (hash/deep-link не
 *      тронуты), ARIA selected, desktop ≥768 dropdown скрыт.
 *
 * Запуск: node tests/js/asap8_w2_shell_mobile_nav_test.js
 *         (печатает W2-SHELL-UNIT-OK)
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component(name, compOpts) {
        global.__components = global.__components || {};
        global.__components[name] = compOpts;
      },
      provide() {}, use() {}, mount() {},
    };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
const _bodyChildren = [];
global.document = {
  addEventListener() {}, getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() { const i = _bodyChildren.indexOf(this); if (i >= 0) _bodyChildren.splice(i, 1); },
    };
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) { const i = _bodyChildren.indexOf(el); if (i >= 0) _bodyChildren.splice(i, 1); return el; },
  },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('no'); } } },
});
global.sessionStorage = {
  _s: {},
  getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods || {};
const computed = captured.computed || {};
const data = captured.data();
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const JS_SRC = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

// ── 1. ASAP-UI-02 §2.1: разделы и RBAC живут в одном реестре (drawer) ─────
{
  const nav = computed.navItems.call({
    route: '#/', iaV2: true, canViewTab() { return true; },
    isGlobalAdmin: true,
  });
  const groups = computed.sidebarGroups.call({ navItems: nav });
  const ids = groups.pub.concat(groups.admin, groups.local)
    .map(function (n) { return n.id; });
  assert.deepStrictEqual(ids.slice().sort(),
    ['access', 'ai', 'how', 'memory', 'modules', 'oversight', 'permsoc', 'status'],
    'ASAP-UI-02: тот же реестр разделов доступен навигации (без второго меню)');

  // RBAC: скрытые права не попадают и в drawer-реестр.
  const navUser = computed.navItems.call({
    route: '#/', iaV2: true, canViewTab(id) { return id === 'status'; },
  });
  const userGroups = computed.sidebarGroups.call({ navItems: navUser });
  assert.deepStrictEqual(
    userGroups.pub.concat(userGroups.admin, userGroups.local)
      .map(function (n) { return n.id; }).sort(),
    ['how', 'status'],
    'ASAP-UI-02: RBAC — без прав остаются только «Статус» и «Справка»');

  // Drawer рендерит именно эти группы (единственный список разделов).
  assert.ok(INDEX.indexOf('v-for="n in sidebarGroups.pub"') >= 0
    && INDEX.indexOf('v-for="n in sidebarGroups.admin"') >= 0
    && INDEX.indexOf('v-for="n in sidebarGroups.local"') >= 0,
    'ASAP-UI-02: drawer выводит группы разделов из sidebarGroups');
  // Второго/третьего независимого механизма навигации нет: единственный
  // список разделов в IA v2 — drawer/sidebar; legacy navbar-band живёт только
  // при выключенном IA v2 (v-if="!iaV2") и в рабочем продукте не рендерится.
  assert.ok(INDEX.indexOf('v-for="n in mobileTopnavItems"') < 0
    && INDEX.indexOf('v-for="n in mobileMoreItems"') < 0,
    'ASAP-UI-02: кроме sidebar/drawer списков разделов НЕТ (нет row B, нет «Ещё»-списка)');
  assert.ok(/v-if="!iaV2" class="navbar-band/.test(INDEX),
    'ASAP-UI-02: legacy-лента разделов остаётся только за выключенным IA v2');

  // «⋯» открывает второстепенные действия, а не разделы.
  assert.strictEqual(computed.mobileMoreItems, undefined,
    'ASAP-UI-02: mobileMoreItems (список разделов в «Ещё») удалён');
  assert.strictEqual(computed.mobileTopnavItems, undefined,
    'ASAP-UI-02: mobileTopnavItems (row B) удалён');
}

// ── 2. ASAP-UI-02 §2.1: постоянной нижней панели нет ни в одной ориентации ─
{
  assert.ok(INDEX.indexOf('class="bottom-nav"') < 0
    && INDEX.indexOf('class="more-sheet"') < 0,
    'ASAP-UI-02: bottom-nav/more-sheet не возвращены');
  assert.ok(!/\.bottom-nav[\s{,:-]/.test(CSS)
    && !/\.more-sheet[\s{,:-]/.test(CSS),
    'ASAP-UI-02: CSS bottom-nav/more-sheet отсутствует');
  assert.strictEqual(computed.bottomNavItems, undefined,
    'ASAP-UI-02: computed bottomNavItems не возвращён');
  // Нижняя панель разделов (row B) удалена полностью.
  assert.ok(INDEX.indexOf('mobile-topnav') < 0,
    'ASAP-UI-02: разметки `.mobile-topnav` нет (нижней панели нет)');
  assert.ok(CSS.indexOf('mobile-topnav') < 0,
    'ASAP-UI-02: CSS `.mobile-topnav*` удалён (включая ландшафтный рейл)');
  assert.ok(!CSS.includes('var(--bottom-nav-h') && !CSS.includes('--bottom-nav-h:'),
    'ASAP-UI-02: метрика `--bottom-nav-h` удалена вместе с потребителем');
  assert.ok(methods._syncBottomNavMetric === undefined
    && JS_SRC.indexOf('_syncBottomNavMetric') < 0,
    'ASAP-UI-02: наблюдатель высоты нижней панели удалён');
  // Ландшафтный правый рейл тоже не возвращается (контент без резерва 58px).
  assert.ok(!/58px/.test(CSS), 'ASAP-UI-02: резерв 58px под рейл удалён');
}

// ── 3. §6.1 v2.1 (решение владельца): app-level «…» удалён, ⛶ один ───────
// 26905a89: меню второстепенных действий, дубль идентичности и отдельный
// пункт fullscreen удалены. Единственная точка входа ⛶ — кнопка в шапке
// (44×44, иконка по реальному режиму); вход в dev-диагностику геометрии в
// prod-разметке отсутствует.
{
  // РОВНО одна кнопка ⛶ и ровно один вход в переключение режима.
  const fsBtn = (INDEX.match(/class="[^"]*header-fs-btn[^"]*"/g) || []).length;
  assert.strictEqual(fsBtn, 1,
    '§6.1: в шапке РОВНО одна кнопка header-fs-btn (второго входа ⛶ нет)');
  assert.strictEqual((INDEX.match(/data-fs-toggle/g) || []).length, 1,
    '§6.1: ровно один вход ⛶ (data-fs-toggle)');
  assert.ok(/v-if="me && fsSlot !== 'hidden'"[^>]*\sdata-fs-toggle/.test(
    INDEX.replace(/\n\s+/g, ' ')),
    '§6.1: видимость ⛶ решает политика (fsSlot), а не второй пункт меню');
  assert.ok(/data-fs-toggle[\s\S]{0,300}@click="toggleFullscreen\(\)"/.test(INDEX),
    '§6.1: ⛶ вызывает тот же toggleFullscreen (один механизм)');
  assert.strictEqual((INDEX.match(/:aria-pressed="fsAriaPressed"/g) || []).length, 1,
    '§6.1: состояние ⛶ пробрасывается в aria-pressed');
  // App-level «…»: ни разметки, ни состояния, ни методов, ни CSS-замка скролла.
  for (const gone of ['class="more-menu-root"', 'more-menu-backdrop',
    'more-menu-panel', 'more-menu-profile', 'data-fs-menu-item',
    'more-menu-open', 'aria-label="Дополнительные действия"']) {
    assert.strictEqual(INDEX.indexOf(gone), -1,
      '§6.1: app-level «…» удалён из разметки: ' + gone);
  }
  for (const gone of ['moreMenuRoot', 'moreMenuBackdrop', 'moreMenuPanel',
    'moreMenuProfile', 'moreMenuOpen', 'toggleMoreMenu', 'openMoreMenu',
    'closeMoreMenu', 'moreMenuProfileId', 'moreMenuFullscreen']) {
    assert.strictEqual(JS_SRC.indexOf(gone), -1,
      '§6.1: механика «…» удалена из app.js: ' + gone);
  }
  assert.strictEqual(methods.toggleMoreMenu, undefined,
    '§6.1: метода toggleMoreMenu больше нет');
  assert.strictEqual(methods.moreMenuFullscreen, undefined,
    '§6.1: дублирующего входа ⛶ (moreMenuFullscreen) больше нет');
  assert.strictEqual(data.moreMenuOpen, undefined,
    '§6.1: состояния moreMenuOpen больше нет');
  // dev-диагностика геометрии: входа в prod-UI нет, панель — за флагом.
  assert.strictEqual(INDEX.indexOf('data-fs-geom-diag-entry'), -1,
    '§6.1: у dev-диагностики геометрии нет входа в prod-разметке');
  assert.ok(/v-if="fsGeomDevEnabled && fsGeomDiagOpen"/.test(INDEX),
    '§6.1: панель диагностики рендерится только по внутреннему dev-флагу');
  // ASAP-UI-02 §4.2/§11 (L01958): порядок Back/Esc — ОДИН список слоёв
  // (backStackLayers), а не if-чейн в каждом методе. Проверяем поведение
  // порядка, а не текст метода: верхний слой закрывается первым.
  const stack = methods.backStackLayers.call({
    paletteOpen: true, fsGeomDevEnabled: true, fsGeomDiagOpen: true,
    drawerOpen: true,
  });
  assert.deepStrictEqual(stack, ['palette', 'fs-geom', 'drawer'],
    '§6.1: порядок Back/Esc — палитра → dev-панель → drawer');
  const escCalls = [];
  methods.escClose.call({
    paletteOpen: true, drawerOpen: true,
    closePalette() { escCalls.push('palette'); },
    closeDrawer() { escCalls.push('drawer'); },
  });
  assert.deepStrictEqual(escCalls, ['palette'],
    '§6.1: один Esc закрывает РОВНО верхний слой');
  // Правило scroll-lock удалённого меню осталось в CSS, но стало инертным:
  // класс `more-menu-open` не применяется ни в одном месте разметки.
  assert.strictEqual((INDEX.match(/more-menu-open/g) || []).length, 0,
    '§6.1: scroll-lock-класс удалённого меню не применяется (правило инертно)');
}

// ── 4. ASAP-UI-02 §2.2: мобильная шапка — одна строка, всё обязательное ────
{
  // Логотипа Adminbot нет нигде (sidebar, шапка, drawer): без пустых слотов.
  assert.ok(INDEX.indexOf('mobile-brand') < 0 && INDEX.indexOf('sidebar-brand') < 0,
    'ASAP-UI-02: разметки бренда Adminbot нет');
  assert.ok(CSS.indexOf('mobile-brand') < 0 && CSS.indexOf('sidebar-brand') < 0,
    'ASAP-UI-02: CSS бренда Adminbot нет');
  assert.ok(INDEX.indexOf('class="sidebar-top"') >= 0
    && INDEX.indexOf('data-sidebar-collapse') >= 0,
    'ASAP-UI-02: верхняя строка sidebar — только функциональная кнопка');
  // Кнопка навигации: drawer на любом не-desktop shell, menu-глиф, 44×44.
  assert.ok(/v-if="iaV2 && hasDrawer"[\s\S]{0,220}data-drawer-trigger/.test(INDEX),
    'ASAP-UI-02: кнопка drawer рендерится на mobile и tablet (hasDrawer)');
  assert.strictEqual(computed.hasDrawer.call({ shellMode: 'mobile' }), true,
    'ASAP-UI-02: hasDrawer на телефоне');
  assert.strictEqual(computed.hasDrawer.call({ shellMode: 'compact' }), true,
    'ASAP-UI-02: hasDrawer на планшете');
  assert.strictEqual(computed.hasDrawer.call({ shellMode: 'desktop' }), false,
    'ASAP-UI-02: на desktop постоянный sidebar, drawer не нужен');
  assert.ok(INDEX.indexOf('aria-label="Открыть навигацию"') >= 0,
    'ASAP-UI-02: доступное имя кнопки навигации');
  // Иконки: menu у навигации; «второстепенных действий» в шапке больше нет
  // (единственная иконочная кнопка-действие — ⛶, см. блок 3).
  assert.ok(/data-drawer-trigger[\s\S]{0,400}class="ui-ic"/.test(INDEX),
    'ASAP-UI-02: кнопка навигации использует единый icon-контракт (ui-ic)');
  assert.strictEqual(INDEX.indexOf('data-more-trigger'), -1,
    '§6.1: кнопки «⋯» (data-more-trigger) в шапке больше нет');
  // Знак единственной иконочной кнопки-действия — SVG-⛶ (не PUA-троеточие
  // и не сетка из четырёх квадратов): два состояния, оба через class="fs-ic".
  assert.strictEqual((INDEX.match(/class="fs-ic"/g) || []).length, 2,
    '§6.1: у ⛶ ровно две иконки-состояния (войти/выйти, обе class="fs-ic")');
  assert.ok(/\.header-nav-btn,\s*\n?\.header-more-btn \{[^}]*min-width: 44px/.test(
    CSS.replace(/\r/g, '')), 'ASAP-UI-02: hit-цель иконочных кнопок ≥44×44');
  assert.ok(/\.ui-ic \{[^}]*width: 20px;[\s\S]{0,120}height: 20px;/.test(CSS),
    'ASAP-UI-02: оптический размер знака 20px');
  // Название раздела — ОДИН раз в шапке (не скрыто), крошка не второй ряд.
  assert.ok(!/\.app-shell\.shell-mobile header\.header-sticky\.header-compact-v2 \.header-title-wrap \{\s*\n\s*display: none;/.test(CSS),
    'ASAP-UI-02: название раздела видно в мобильной шапке');
  assert.ok(/\.app-shell\.shell-mobile header\.header-sticky\.header-compact-v2 \.breadcrumb \{\s*\n\s*display: none;/.test(CSS),
    'ASAP-UI-02: крошка не создаёт второй заголовок на телефоне');
  // РОВНО один раз: контентный дубль имени раздела скрыт на ВСЕХ ширинах
  // (ревью F1, 31.10.2026: пока правило жило в @media(≥768), на 390 имя
  // стояло и в шапке, и в контенте хаба).
  assert.ok(CSS.indexOf(
    '.app-shell.ia-v2 .hub-head .hub-title { display: none; }') >= 0,
    'ASAP-UI-02: контентный заголовок хаба скрыт — второго имени раздела нет');
  // Узкий телефон: имя выбранного чата остаётся в триггере, ⛶ уходит в «⋯»
  // (ревью F2: «ЧАТ ▾» без имени не идентифицировал чат).
  assert.ok(CSS.indexOf(
    '.app-shell.shell-mobile .scope-trigger .scope-name { display: none; }') < 0,
    'ASAP-UI-02: имя выбранного чата не скрывается на 320–419');
  // Микро-фикс F1 (31.10.2026) отменён решением владельца (§6.1 v2.1):
  // ⛶ больше НЕ уезжает в «…» — меню нет, и кнопка остаётся в шапке на
  // любой ширине. Правило display:none для неё не возвращено ни в одной
  // точке CSS (проверяем не только ≤519: любое правило с display:none).
  assert.ok(!/\.header-fs-btn[^{}]*\{[^}]*display:\s*none/.test(
    CSS.replace(/\n/g, ' ')),
    '§6.1: у ⛶ нет правила display:none (кнопка видима в шапке на любом ширине)');
  assert.strictEqual((CSS.match(
    /\.app-shell\.shell-mobile \.header-fs-btn \{ display: inline-flex; \}/g)
    || []).length, 1,
    '§6.1: на мобильном shell ⛶ явно остаётся видимым (inline-flex)');
  assert.ok(/\.header-fs-btn \{[^}]*min-width: 44px[^}]*min-height: 44px/.test(
    CSS.replace(/\n/g, ' ')),
    '§6.1: tap-цель ⛶ ≥44×44 (единственная иконочная кнопка шапки)');
  assert.strictEqual(INDEX.indexOf('data-fs-menu-item'), -1,
    '§6.1: пункта «на весь экран» в меню больше нет (data-fs-menu-item)');
  // Идентификация: имя скрыто, БЕЙДЖ РОЛИ виден (прежнее правило прятало оба).
  assert.ok(/\.app-shell\.shell-mobile \.header-user-name \{ display: none; \}/.test(CSS),
    'ASAP-UI-02: имя пользователя скрыто (полное — в title/«⋯»)');
  assert.ok(!/\.header-user span \{ display: none; \}/.test(CSS),
    'ASAP-UI-02: бейдж роли больше не скрывается целиком');
  assert.ok(/\.app-shell\.shell-mobile \.header-scope-row \.header-user-role \{[^}]*text-overflow: ellipsis/.test(
    CSS.replace(/\n/g, ' ')), 'ASAP-UI-02: бейдж роли компактный (ellipsis)');
  assert.ok(INDEX.indexOf('class="header-user-role') >= 0
    && INDEX.indexOf(':title="me.role_name"') >= 0,
    'ASAP-UI-02: фактическая роль видна и целиком доступна в title');
  assert.ok(computed.meInitial.call({ me: { first_name: 'Audit' } }) === 'A',
    'ASAP-UI-02: аватар-инициал при отсутствии фото');
  // ID области не в шапке; имя чата — ellipsis + полный текст в title.
  assert.ok(/\.app-shell\.shell-mobile \.scope-tech \{ display: none; \}/.test(CSS),
    'ASAP-UI-02: ID-чип скрыт в мобильной шапке');
  assert.ok(INDEX.indexOf(':title="scopeTriggerTitle"') >= 0,
    'ASAP-UI-02: полное имя чата — в title триггера');
  // Одна строка без переноса (второго ряда нет) и без «внахлёст».
  assert.ok(/\.app-shell\.shell-mobile header\.header-sticky\.header-compact-v2 \{[^}]*flex-wrap: nowrap/.test(
    CSS.replace(/\n/g, ' ')), 'ASAP-UI-02: мобильная шапка не переносится на второй ряд');
  // Микро-фикс F1 (31.10.2026): ряд области УЖИМАЕТСЯ (иначе резерв имени
  // раздела выталкивал «⋯» за вьюпорт: замер 375–430 — more.right 444 при
  // vw 420), но «внахлёст» не идёт: сжимается только внутренний триггер
  // области (и не ниже бейджа/▾), а идентификация пользователя — нет.
  assert.ok(/\.app-shell\.shell-mobile header\.header-sticky\.header-compact-v2 \.header-scope-row \{[\s\S]{0,600}flex: 0 1 auto/.test(
    CSS.replace(/\r/g, '')), 'ASAP-UI-02: ряд области ужимается вместе с именем раздела');
  assert.ok(/\.app-shell\.shell-mobile \.scope-wrap \{[\s\S]{0,600}flex: 0 1 auto[\s\S]{0,400}min-width: min-content/.test(
    CSS.replace(/\r/g, '')), 'ASAP-UI-02: ужимается имя области, но не ниже бейджа и ▾');
  assert.ok(/\.app-shell\.shell-mobile \.header-user \{ flex: 0 0 auto; \}/.test(
    CSS), 'ASAP-UI-02: блок идентификации пользователя не сжимается');
}

// ── 5. U02: мобильный dropdown суб-вкладок Аналитики ──────────────────────
{
  // Полный список БЕЗ «Логи» (якорь — не режим).
  const tabs = computed.oversightMobileTabs.call({ oversightTabs: data.oversightTabs });
  assert.deepStrictEqual(tabs.map(function (t) { return t.id; }),
    ['overview', 'processes', 'runs', 'incidents', 'memory', 'models', 'summary'],
    'U02.2: полный список 7 суб-вкладок');
  assert.ok(tabs.every(function (t) { return t.id !== 'logs'; }),
    'U02.2: «Логи» НЕ в списке (якорь, не режим)');
  assert.strictEqual(computed.oversightTabLabel.call(
    { oversightTab: 'memory', oversightTabs: data.oversightTabs }),
    'Память и интеллект', 'U02.2: подпись текущего раздела');
  assert.strictEqual(computed.oversightTabLabel.call(
    { oversightTab: 'nope', oversightTabs: data.oversightTabs }),
    'Обзор', 'U02.2: неизвестный таб → «Обзор»');
  // Разметка: триггер + listbox + ARIA selected; выбор через oversightSetTab.
  assert.ok(INDEX.indexOf('oversight-mobile-trigger') >= 0
    && INDEX.indexOf('role="listbox"') >= 0
    && INDEX.indexOf('role="option"') >= 0
    && INDEX.indexOf(':aria-selected="oversightTab === t.id') >= 0,
    'U02.2: ARIA listbox/option/selected в dropdown');
  assert.ok(INDEX.indexOf('oversightMobilePick(t.id)') >= 0
    && methods.oversightMobilePick.toString().indexOf('oversightSetTab') >= 0,
    'U02.3: выбор через существующий oversightSetTab (hash/фильтры целы)');
  assert.ok(INDEX.indexOf('ref="oversightMobileTrigger"') >= 0
    && methods.oversightMobileClose.toString().indexOf('oversightMobileTrigger') >= 0,
    'U02: возврат фокуса в триггер dropdown');
  assert.ok(INDEX.indexOf('@keydown.esc.prevent="oversightMobileClose()"') >= 0,
    'U02: Esc закрывает dropdown');
  // CSS: триггер — полноширинный, длинные метки — 2 строки, триггер ellipsis.
  assert.ok(/\.oversight-mobile-trigger \{[^}]*width: 100%/.test(CSS.replace(/\n/g, ' ')),
    'U02.2: триггер полноширинный');
  assert.ok(/\.oversight-mobile-option \{[^}]*white-space: normal/.test(CSS.replace(/\n/g, ' ')),
    'U02.2: длинные метки — до 2 строк в меню');
  assert.ok(/\.oversight-mobile-dd__current \{[^}]*text-overflow: ellipsis/.test(CSS.replace(/\n/g, ' ')),
    'U02.2: ellipsis на триггере');
  assert.ok(/\.oversight-mobile-panel \{[^}]*max-height: 60vh/.test(CSS.replace(/\n/g, ' ')),
    'U02.2: меню не больше viewport');
  // U02.1: desktop не изменён; на mobile pills скрыты.
  assert.ok(/@media \(min-width: 768px\) \{\s*\n\s*\.oversight-mobile-dd \{ display: none; \}/.test(CSS),
    'U02.1: на ≥768 dropdown скрыт');
  assert.ok(/@media \(max-width: 767px\) \{\s*\n\s*\.oversight-tabs__row \{ display: none; \}/.test(CSS),
    'U02.2: на <768 лента pills скрыта');
  // U02.4 (REGRESSION, DROPDOWN-WG 18.10.2026): WIN-GLASS-P0 2.58.85
  // (glass-refraction.js) инлайнит `overflow: clip` на карточку-поверхность
  // .oversight-tabs; открытая панель уходит НИЖЕ края карточки и обрезается —
  // elementFromPoint на опции = соседняя карточка, тап не доходит (мёртвый
  // dropdown 2.58.85/2.58.86). Пока список открыт, клип обязан сниматься
  // (!important — единственный способ перебить inline-стиль слоя рефракции).
  assert.ok(/\.oversight-tabs\.oversight-dd-open \{[^}]*overflow: visible !important/.test(CSS.replace(/\n/g, ' ')),
    'U02.4: открытый dropdown не обрезается поверхностью рефракции');
  assert.ok(INDEX.indexOf('v-for="t in oversightTabs"') >= 0,
    'U02.1: desktop-ряд табов сохранён в разметке');
}

// ── 6. Состояния оверлеев — в data(), методов достаточно ──────────────────
{
  assert.strictEqual(data.moreMenuOpen, undefined,
    '§6.1: состояния moreMenuOpen в data больше нет (меню удалено)');
  assert.strictEqual(data.oversightMobileOpen, false,
    'U02: oversightMobileOpen в data');
  for (const m of ['drawerOnKeydown',
    'oversightMobileToggle', 'oversightMobileClose', 'oversightMobilePick']) {
    assert.strictEqual(typeof methods[m], 'function', 'метод: ' + m);
  }
  // Удалённая механика «…» не должна вернуться под теми же именами.
  for (const gone of ['toggleMoreMenu', 'openMoreMenu', 'closeMoreMenu',
    'moreMenuProfileId', 'moreMenuFullscreen']) {
    assert.strictEqual(methods[gone], undefined, 'метод удалён: ' + gone);
  }
  // Ревью F3: Tab-ловушка drawer подключена к разметке панели.
  assert.ok(INDEX.indexOf('@keydown="drawerOnKeydown($event)"') >= 0,
    'ASAP-UI-02: Tab-ловушка подключена к drawer');
  // ASAP-UI-02 §4.2/§11: и глобальный Esc, и Back читают ОДИН Back-stack,
  // поэтому drawer закрывается обоими путями и маршрут не меняется.
  const drawerEsc = [];
  methods.escClose.call({
    drawerOpen: true,
    closeDrawer() { drawerEsc.push('drawer'); },
  });
  assert.deepStrictEqual(drawerEsc, ['drawer'],
    'ASAP-UI-02: глобальный Esc знает про открытый drawer');
  const drawerBack = [];
  methods.goBack.call({
    drawerOpen: true, route: '#/modules',
    closeDrawer() { drawerBack.push('drawer'); },
    navigateTo(r) { drawerBack.push('nav:' + r); },
  });
  assert.deepStrictEqual(drawerBack, ['drawer'],
    'ASAP-UI-02: Back закрывает открытый drawer, маршрут не меняется');
  // shellNavTo закрывает единственный оверлей навигации — drawer.
  const navTo = methods.shellNavTo.toString();
  assert.ok(navTo.indexOf('closeDrawer()') >= 0,
    'shellNavTo: shell-переход закрывает drawer');
  assert.strictEqual(navTo.indexOf('MoreMenu'), -1,
    '§6.1: shell-переход больше не закрывает удалённое меню «…»');
}

console.log('W2-SHELL-UNIT-OK');
