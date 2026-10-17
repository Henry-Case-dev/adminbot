'use strict';
/* ═══ W2-SHELL (asap8-v6-3-live-correction) — JS-контракт мобильной
 * навигации: U01 (row A/row B + меню «Ещё») и U02 (мобильный dropdown
 * суб-вкладок Аналитики).
 *
 * TEST-LIFECYCLE: CONTRACT owner=REQ-U01/U02 (slice FE-SHELL);
 *   REGRESSION owner=DROPDOWN-WG (валидный тап по опции dropdown поверх
 *   карточек рефракции WIN-GLASS-P0 2.58.85, см. U02.4 ниже)
 *
 * Проверяет (по ТЗ U01 §137–143, U02 §147–149, requirements-map
 * REQ-U01-BASE / U01.1–U01.5 / REQ-U02 / U02.1–U02.3):
 *   1) mobileTopnavItems = РОВНО [status, oversight, modules] (RBAC-фильтр);
 *      mobileMoreItems = остальное; триггер «Ещё • …» для активного раздела;
 *   2) нижний navbar/bottom-nav НЕ возвращён (REQ-U01-BASE);
 *   3) меню «Ещё» — popover поверх контента: role="menu", aria-expanded,
 *      Esc/outside-click/focus-return, body-scroll-lock, z-index выше шапки,
 *      профиль/ID области в меню (ID не в постоянной шапке);
 *   4) row B CSS: равные сегменты, тач ≥44px, БЕЗ горизонтального скролла;
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

// ── 1. U01.1: row B — ровно 3 фиксированных пункта + «Ещё» ────────────────
{
  const nav = computed.navItems.call({
    route: '#/', iaV2: true, canViewTab() { return true; },
    isGlobalAdmin: true,
  });
  const ctx = {
    route: '#/', iaV2: true, activeNav: '',
    canViewTab() { return true; },
    navItems: nav,
    mobileTopnavItems: computed.mobileTopnavItems.call({ navItems: nav }),
    mobileMoreItems: computed.mobileMoreItems.call({
      navItems: nav,
      mobileTopnavItems: computed.mobileTopnavItems.call({ navItems: nav }),
    }),
  };
  assert.deepStrictEqual(
    ctx.mobileTopnavItems.map(function (n) { return n.id; }),
    ['status', 'oversight', 'modules'],
    'U01.1: row B = Статус/Аналитика/Модули, строго этот порядок');
  assert.deepStrictEqual(
    ctx.mobileMoreItems.map(function (n) { return n.id; }).sort(),
    ['access', 'ai', 'how', 'memory', 'permsoc'],
    'U01.1: ИИ/Память/Справка/Доступы/PERMsoc — только в меню «Ещё»');
  assert.strictEqual(ctx.mobileTopnavItems.length + ctx.mobileMoreItems.length,
    nav.length, 'U01.1: row B + «Ещё» = весь доступный реестр');

  const ctxAi = Object.assign({}, ctx, { activeNav: 'ai' });
  assert.strictEqual(computed.moreMenuTriggerLabel.call(ctxAi), 'Ещё • ИИ',
    'U01.1: активный раздел «Ещё» отражён в триггере «Ещё • …»');
  assert.strictEqual(computed.moreMenuActive.call(ctxAi), true,
    'U01.1: триггер подсвечен, пока активен раздел из меню');
  assert.strictEqual(computed.moreMenuTriggerLabel.call(ctx), 'Ещё',
    'U01.1: на фиксированном разделе триггер — просто «Ещё»');

  // RBAC: скрытые права не показываются ни в row B, ни в «Ещё».
  const navUser = computed.navItems.call({
    route: '#/', iaV2: true, canViewTab(id) { return id === 'status'; },
  });
  const userTop = computed.mobileTopnavItems.call({ navItems: navUser });
  const userMore = computed.mobileMoreItems.call({
    navItems: navUser,
    mobileTopnavItems: computed.mobileTopnavItems.call({ navItems: navUser }),
  });
  assert.deepStrictEqual(userTop.map(function (n) { return n.id; }),
    ['status'], 'U01: RBAC — row B без прав только «Статус»');
  assert.deepStrictEqual(userMore.map(function (n) { return n.id; }),
    ['how'], 'U01: скрытые права не показываются в «Ещё»');
}

// ── 2. REQ-U01-BASE: нижний navbar НЕ возвращён ───────────────────────────
{
  assert.ok(INDEX.indexOf('class="bottom-nav"') < 0
    && INDEX.indexOf('class="more-sheet"') < 0,
    'REQ-U01-BASE: bottom-nav/more-sheet не возвращены');
  assert.ok(!/\.bottom-nav[\s{,:-]/.test(CSS)
    && !/\.more-sheet[\s{,:-]/.test(CSS),
    'REQ-U01-BASE: CSS bottom-nav/more-sheet отсутствует');
  assert.strictEqual(computed.bottomNavItems, undefined,
    'REQ-U01-BASE: computed bottomNavItems не возвращён');
  // U01: без горизонтальной прокрутки всех пунктов (старый канон удалён).
  assert.ok(!/\.mobile-topnav \{[^}]*overflow-x:\s*auto/.test(CSS),
    'U01: .mobile-topnav без overflow-x скролла');
  assert.ok(INDEX.indexOf('class="mobile-topnav scroll-thin"') < 0,
    'U01: scroll-thin-лента удалена из разметки');
}

// ── 3. U01.4: меню «Ещё» — popover/sheet поверх контента ──────────────────
{
  assert.ok(INDEX.indexOf('class="more-menu-root"') >= 0
    && INDEX.indexOf('more-menu-backdrop') >= 0
    && INDEX.indexOf('more-menu-panel') >= 0,
    'U01.4: overlay + панель меню «Ещё» в разметке');
  assert.ok(INDEX.indexOf('role="menu"') >= 0
    && INDEX.indexOf('role="menuitem"') >= 0,
    'U01.4: ARIA menu/menuitem');
  assert.ok(/aria-haspopup="menu"/.test(INDEX)
    && INDEX.indexOf(':aria-expanded="moreMenuOpen') >= 0,
    'U01.4: триггер — aria-haspopup + aria-expanded');
  // Esc: и локально на панели, и глобальный escClose (guard первым).
  assert.ok(INDEX.indexOf('@keydown="moreMenuOnKeydown($event)"') >= 0,
    'U01.4: Esc/Tab-ловушка на панели');
  const esc = methods.escClose.toString();
  assert.ok(esc.indexOf('moreMenuOpen') < esc.indexOf('graphFullVisible'),
    'U01.4: Esc закрывает «Ещё» первым (верхний оверлей)');
  // Outside click: закрытие по клику в backdrop.
  assert.ok(/more-menu-backdrop[^>]+@click="closeMoreMenu\(\)"/.test(
    INDEX.replace(/\n\s+/g, ' ')),
    'U01.4: outside click (backdrop) закрывает меню');
  // Focus management: refs триггера/панели + возврат фокуса.
  assert.ok(INDEX.indexOf('ref="moreMenuTrigger"') >= 0
    && INDEX.indexOf('ref="moreMenuPanel"') >= 0
    && methods.closeMoreMenu.toString().indexOf('moreMenuTrigger') >= 0,
    'U01.4: возврат фокуса в кнопку при закрытии');
  assert.ok(methods.moreMenuOnKeydown.toString().indexOf("'Tab'") >= 0,
    'U01.4: Tab-ловушка внутри панели');
  // Body-scroll-lock без прыжков — класс на shell, блок main.scroll-area.
  assert.ok(INDEX.indexOf("moreMenuOpen ? 'more-menu-open' : ''") >= 0,
    'U01.4: класс more-menu-open на .app-shell');
  assert.ok(/\.app-shell\.more-menu-open\.shell-mobile main\.scroll-area \{ overflow: hidden; \}/.test(CSS),
    'U01.4: body-scroll-lock единственного скроллера');
  // z-index: выше шапки (40) и drawer (40), ниже модалок (59+).
  assert.ok(/\.more-menu-root \{ position: fixed; inset: 0; z-index: 55; \}/.test(CSS),
    'U01.4: popover z-index 55 (выше шапки, ниже модалок)');
  // Панель под шапкой с safe-area и без обрезки (max-height + scroll).
  assert.ok(/\.more-menu-panel \{[^}]*--header-h/.test(CSS.replace(/\n/g, ' ')),
    'U01.4: панель позиционируется от измеренной высоты шапки');
  assert.ok(/\.more-menu-panel \{[^}]*max-height:/.test(CSS.replace(/\n/g, ' ')),
    'U01.4: панель не выше viewport (внутренний скролл)');
  // Deep links: пункт меню идёт через shellNavTo (hash-роутинг).
  assert.ok(methods.moreMenuPick.toString().indexOf('shellNavTo') >= 0,
    'U01.4: deep links — пункты меню через shellNavTo');
  // Скрытые права: список меню — RBAC-computed (mobileMoreItems).
  assert.ok(INDEX.indexOf('v-for="n in mobileMoreItems"') >= 0,
    'U01.4: меню строится из RBAC-отфильтрованного mobileMoreItems');
  // Профиль/ID области — в меню (U01.2: ID не в постоянной шапке).
  assert.ok(INDEX.indexOf('more-menu-profile') >= 0
    && methods.moreMenuProfileId.toString().indexOf('activeChatId') >= 0,
    'U01.2: ID области доступен в меню «Ещё» (профиль)');
}

// ── 4. U01.2/U01.3: row A компакт + row B геометрия ───────────────────────
{
  // NOTE (FS-HOTFIX FOLLOW-UP, директива владельца 18.10, §4.1.2/§5.5/§10):
  // логотип AdminBot — декоративный элемент и СОЗНАТЕЛЬНО скрыт в mobile-
  // shell («Главный визуальный приоритет — убрать логотип…»); его место
  // отдано функциональной компоновке row A (селектор чата + кнопка ⛶ в той
  // же строке). Разметка слота сохранена (v-if), desktop/compact не затронут.
  assert.ok(INDEX.indexOf('class="mobile-brand') >= 0
    && /v-if="iaV2 && isMobileShell && !\(routeDepth > 0 && !backNative\)"/.test(INDEX),
    'U01: разметка слота [←/AdminBot] сохранена');
  assert.ok(/\.app-shell\.shell-mobile \.mobile-brand \{ display: none; \}/.test(CSS),
    'FS-HOTFIX: логотип скрыт в .shell-mobile (директива 18.10, §4.1.2/§10)');
  // ID из шапки скрыт на mobile (desktop <details> сохранён).
  assert.ok(/\.app-shell\.shell-mobile \.scope-tech \{ display: none; \}/.test(CSS),
    'U01.2: ID-чип скрыт в мобильной шапке');
  // chat-селектор: ellipsis/clamp, полное имя в title (scopeTriggerTitle).
  assert.ok(/\.app-shell\.shell-mobile \.scope-trigger \{[^}]*max-width: clamp\(/.test(CSS.replace(/\n/g, ' ')),
    'U01.2: ширина селектора по clamp()/flex');
  assert.ok(INDEX.indexOf(':title="scopeTriggerTitle"') >= 0,
    'U01.2: полное имя чата — в title триггера');
  // Заголовок/крошки не второй строкой в мобильной шапке (U01.5).
  assert.ok(/\.app-shell\.shell-mobile header\.header-sticky\.header-compact-v2 \.header-title-wrap \{\s*\n\s*display: none;/.test(CSS),
    'U01.5: без второго заголовка/крошек в мобильной шапке');
  // Row B: равные сегменты, тач-цели, нет третьей строки.
  assert.ok(/\.mobile-topnav-link \{[^}]*flex: 1 1 0/.test(CSS.replace(/\n/g, ' ')),
    'U01.3: равные сегменты row B (flex: 1 1 0)');
  assert.ok(/\.mobile-topnav-link \{[^}]*min-width: 44px; min-height: 44px;/.test(CSS.replace(/\n/g, ' ')),
    'U01.3: тач-цели row B ≥44×44');
  assert.ok(/\.mobile-topnav \{[^}]*flex: 0 0 auto; width: 100%;/.test(CSS.replace(/\n/g, ' ')),
    'U01.3: row B — одна полная строка (без третьей строки)');
  assert.ok(INDEX.indexOf('mobile-topnav-more') >= 0,
    'U01.3: 4-я кнопка «Ещё ▾» в row B');
  // 4 сегмента в разметке: v-for фиксированных + триггер «Ещё».
  assert.ok(INDEX.indexOf('v-for="n in mobileTopnavItems"') >= 0,
    'U01.3: фиксированные пункты row B из mobileTopnavItems');
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
    'moreMenuPick', 'moreMenuOnKeydown', 'moreMenuProfileId',
    'oversightMobileToggle', 'oversightMobileClose', 'oversightMobilePick']) {
    assert.strictEqual(typeof methods[m], 'function', 'метод: ' + m);
  }
  // shellNavTo закрывает «Ещё» (навигация из любого пункта).
  assert.ok(methods.shellNavTo.toString().indexOf('closeMoreMenu') >= 0,
    'U01.4: shell-переход закрывает меню «Ещё»');
}

console.log('W2-SHELL-UNIT-OK');
