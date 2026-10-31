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
 *   3) меню второстепенных действий («⋯») — popover поверх контента:
 *      role="menu", aria-expanded, Esc/outside-click/focus-return,
 *      body-scroll-lock, z-index выше шапки, профиль/ID области;
 *   4) мобильная шапка: ОДНА строка, кнопка навигации (menu-глиф, 44×44),
 *      название раздела один раз, аватар+бейдж реальной роли видимы,
 *      ghost-⛶ и троеточие (не сетка из четырёх квадратов);
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

// ── 3. ASAP-UI-02 §2.3: меню второстепенных действий — popover ────────────
{
  assert.ok(INDEX.indexOf('class="more-menu-root"') >= 0
    && INDEX.indexOf('more-menu-backdrop') >= 0
    && INDEX.indexOf('more-menu-panel') >= 0,
    'ASAP-UI-02: overlay + панель меню второстепенных действий в разметке');
  assert.ok(INDEX.indexOf('role="menu"') >= 0,
    'ASAP-UI-02: ARIA menu');
  assert.ok(INDEX.indexOf('aria-label="Дополнительные действия"') >= 0,
    'ASAP-UI-02: доступное имя меню');
  assert.ok(/aria-haspopup="menu"/.test(INDEX)
    && INDEX.indexOf(':aria-expanded="moreMenuOpen') >= 0,
    'ASAP-UI-02: триггер — aria-haspopup + aria-expanded');
  // Esc: и локально на панели, и глобальный escClose (guard первым).
  assert.ok(INDEX.indexOf('@keydown="moreMenuOnKeydown($event)"') >= 0,
    'ASAP-UI-02: Esc/Tab-ловушка на панели');
  const esc = methods.escClose.toString();
  assert.ok(esc.indexOf('moreMenuOpen') < esc.indexOf('graphFullVisible'),
    'ASAP-UI-02: Esc закрывает «⋯» первым (верхний оверлей)');
  // Outside click: закрытие по клику в backdrop.
  assert.ok(/more-menu-backdrop[^>]+@click="closeMoreMenu\(\)"/.test(
    INDEX.replace(/\n\s+/g, ' ')),
    'ASAP-UI-02: outside click (backdrop) закрывает меню');
  // Focus management: refs триггера/панели + возврат фокуса.
  assert.ok(INDEX.indexOf('ref="moreMenuTrigger"') >= 0
    && INDEX.indexOf('ref="moreMenuPanel"') >= 0
    && methods.closeMoreMenu.toString().indexOf('moreMenuTrigger') >= 0,
    'ASAP-UI-02: возврат фокуса в кнопку при закрытии');
  assert.ok(methods.moreMenuOnKeydown.toString().indexOf("'Tab'") >= 0,
    'ASAP-UI-02: Tab-ловушка внутри панели');
  // Body-scroll-lock без прыжков — класс на shell, блок main.scroll-area.
  assert.ok(INDEX.indexOf("moreMenuOpen ? 'more-menu-open' : ''") >= 0,
    'ASAP-UI-02: класс more-menu-open на .app-shell');
  assert.ok(/\.app-shell\.more-menu-open\.shell-mobile main\.scroll-area \{ overflow: hidden; \}/.test(CSS),
    'ASAP-UI-02: body-scroll-lock единственного скроллера');
  // z-index: выше шапки (40) и drawer (40), ниже модалок (59+).
  assert.ok(/\.more-menu-root \{ position: fixed; inset: 0; z-index: 55; \}/.test(CSS),
    'ASAP-UI-02: popover z-index 55 (выше шапки, ниже модалок)');
  // Панель под шапкой с safe-area и без обрезки (max-height + scroll).
  assert.ok(/\.more-menu-panel \{[^}]*--header-h/.test(CSS.replace(/\n/g, ' ')),
    'ASAP-UI-02: панель позиционируется от измеренной высоты шапки');
  assert.ok(/\.more-menu-panel \{[^}]*max-height:/.test(CSS.replace(/\n/g, ' ')),
    'ASAP-UI-02: панель не выше viewport (внутренний скролл)');
  // Профиль/ID области — в меню (ID не в постоянной шапке).
  assert.ok(INDEX.indexOf('more-menu-profile') >= 0
    && methods.moreMenuProfileId.toString().indexOf('activeChatId') >= 0,
    'ASAP-UI-02: ID области доступен в меню второстепенных (профиль)');
  // Служебное действие (админ-диагностика) остаётся единственным пунктом.
  assert.ok(INDEX.indexOf('data-fs-geom-diag-entry') >= 0,
    'ASAP-UI-02: служебные действия доступны из «⋯»');
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
  // Иконки: menu у навигации, троеточие у «второстепенных» (не grid_view).
  assert.ok(/data-drawer-trigger[\s\S]{0,400}class="ui-ic"/.test(INDEX),
    'ASAP-UI-02: кнопка навигации использует единый icon-контракт (ui-ic)');
  assert.ok(INDEX.indexOf('data-more-trigger') >= 0
    && /data-more-trigger[\s\S]{0,400}class="ui-ic"/.test(INDEX),
    'ASAP-UI-02: «второстепенные действия» — троеточие (ui-ic)');
  const moreTag = INDEX.slice(INDEX.indexOf('data-more-trigger') - 400,
    INDEX.indexOf('data-more-trigger') + 900);
  assert.ok(moreTag.indexOf('grid_view') < 0,
    'ASAP-UI-02: «⋯» больше не подменяется сеткой из четырёх квадратов');
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
  // Микро-фикс F1 (31.10.2026): ⛶ уезжает в «⋯» не только на ≤419, а до
  // 519 px включительно — на 420 кнопка возвращалась в шапку (+44 px) и
  // выдавливала имя раздела в 0 px.
  assert.ok(/@media \(max-width: 519px\) \{[\s\S]{0,900}\.app-shell\.shell-mobile header\.header-sticky\.header-compact-v2 \.header-fs-btn \{\s*\n\s*display: none;/.test(CSS),
    'ASAP-UI-02: на ≤519 ghost-⛶ не занимает место в шапке');
  assert.ok(INDEX.indexOf('data-fs-menu-item') >= 0
    && methods.moreMenuFullscreen.toString().indexOf('toggleFullscreen') >= 0,
    'ASAP-UI-02: «на весь экран» доступно из «⋯» тем же механизмом');
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
  assert.strictEqual(data.moreMenuOpen, false, 'U01.4: moreMenuOpen в data');
  assert.strictEqual(data.oversightMobileOpen, false,
    'U02: oversightMobileOpen в data');
  for (const m of ['toggleMoreMenu', 'openMoreMenu', 'closeMoreMenu',
    'moreMenuOnKeydown', 'moreMenuProfileId', 'moreMenuFullscreen',
    'drawerOnKeydown',
    'oversightMobileToggle', 'oversightMobileClose', 'oversightMobilePick']) {
    assert.strictEqual(typeof methods[m], 'function', 'метод: ' + m);
  }
  // Ревью F3: Tab-ловушка drawer подключена к разметке панели.
  assert.ok(INDEX.indexOf('@keydown="drawerOnKeydown($event)"') >= 0,
    'ASAP-UI-02: Tab-ловушка подключена к drawer');
  const esc = methods.escClose.toString();
  assert.ok(esc.indexOf('this.drawerOpen') >= 0,
    'ASAP-UI-02: глобальный Esc знает про открытый drawer');
  assert.ok(methods.goBack.toString().indexOf('this.drawerOpen') >= 0,
    'ASAP-UI-02: Back закрывает открытый drawer');
  // shellNavTo закрывает «Ещё» (навигация из любого пункта).
  assert.ok(methods.shellNavTo.toString().indexOf('closeMoreMenu') >= 0,
    'U01.4: shell-переход закрывает меню «Ещё»');
}

console.log('W2-SHELL-UNIT-OK');
