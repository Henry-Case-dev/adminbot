"""EVOL-023 / EVOL-024 (W7) — навигация, topbar, единый scope-switcher.

Задачи: пересобрать архитектуру навигации (sidebar — только разделы,
компактный topbar с именем раздела + scope + пользователь/роль + действия),
ОДИН Chat/Scope switcher для всех разделов, свёртывание постоянной панели на
desktop, читаемый overlay-слой выпадающих меню, сквозная очистка дублей
заголовков и состояний.

Инварианты, которые НЕ меняются этой волной:
  * маршруты/разделы/RBAC (канонический реестр navItems — прежний);
  * двухстрочная компактная шапка 768–1199 (`header-compact-v2`, D5);
  * механизм fullscreen / safe-area / восстановление (U07) и материал ⛶
    (мини-линза U08.4d — защищённая оптика, EVOL-022);
  * резерв `--header-h` (контент структурно не под шапкой).
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _media_block(css: str, header: str, needle: str) -> str:
    """Тело @media-блока с точным заголовком, содержащее `needle`.

    В файле несколько блоков с одним и тем же заголовком (исторические волны),
    поэтому нужен именно тот, где живёт проверяемое правило.
    """
    start = 0
    while True:
        i = css.find(header, start)
        if i < 0:
            raise AssertionError(f"нет @media {header} с правилом {needle!r}")
        j = css.find("{", i + len(header))
        assert j >= 0, f"нет тела @media {header}"
        depth, k = 0, j
        while k < len(css):
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        body = css[j:k + 1]
        if needle in body:
            return body
        start = i + len(header)
    raise AssertionError("недостижимо")


def _brace_depth(css: str, idx: int) -> int:
    """Глубина вложенности правила: 0 — верхний уровень, >0 — внутри @media."""
    head = re.sub(r"/\*.*?\*/", "", css[:idx], flags=re.S)
    return head.count("{") - head.count("}")


class TestUnifiedScopeSwitcher:
    def test_single_switcher_markup(self):
        """ОДИН компонент области на всё приложение (в topbar)."""
        assert INDEX.count('data-nav-scope="unified"') == 1, \
            "должен быть ровно один переключатель области"
        assert INDEX.count('class="scope-trigger field text-xs"') == 1, \
            "триггер области — один экземпляр (без дублей в разделах)"
        assert INDEX.count('class="scope-panel') == 1, \
            "выпадающая панель — один экземпляр"

    def test_no_per_page_switcher(self):
        """Разделы читают activeChatId, а не рисуют свой селектор области."""
        # PERMsoc: явное требование «второй селектор области не создаётся».
        assert "Второй селектор области не создаётся" in INDEX
        assert "reuse F3 activeChatId" in INDEX
        # Ни одной второй привязки scope-компонента.
        assert "data-nav-scope" in INDEX
        assert INDEX.count('aria-label="Выбор контекста"') == 2, \
            "подпись есть только у триггера и у его listbox"

    def test_scope_trigger_anatomy(self):
        """Аватар + краткое имя + тип области; обрезка не наезжает на бейдж."""
        assert 'data-nav-scope="unified"' in INDEX
        assert 'class="scope-name truncate"' in INDEX
        assert "{{ scopeLabel }}" in INDEX, "тип области (глобально/чат/ЛС)"
        assert ":title=\"scopeTriggerTitle\"" in INDEX, "полное имя — в title"
        assert 'aria-controls="scope-panel"' in INDEX, "связь триггер↔listbox"
        assert 'id="scope-panel"' in INDEX
        # Бейдж и ▾ не сжимаются, имя обрезается (длинные названия, зум).
        assert ".scope-trigger .badge," in CSS
        assert ".scope-trigger .scope-name {" in CSS
        assert "min-width: 0; flex: 1 1 auto; max-width: 11rem;" in CSS

    def test_scope_panel_geometry_and_overlay(self):
        """Панель не уезжает под sidebar и читается на движущемся фоне."""
        block = _media_block(CSS, "@media (min-width: 768px)", ".scope-panel")
        assert ".scope-panel {" in block
        assert "left: 0; right: auto;" in block, \
            "якорь — левый край триггера (было right:0 → уезжала под sidebar)"
        assert "z-index: var(--overlay-z);" in CSS
        assert "--overlay-bg:" in CSS
        # Слой overlay: плотная подложка вместо «стекла в стекле» (.04).
        assert "[data-glass-nested=\"1\"].scope-panel," in CSS, \
            "исключение из nested-in-glass для плавающего меню"
        # Ревью F2 (31.10.2026): закрытие панели возвращает фокус в триггер —
        # Esc из поиска больше не оставляет клавиатурного пользователя на BODY.
        assert "closeScope: function () {" in JS
        seg = JS[JS.index("closeScope: function () {"):]
        seg = seg[:seg.index("\n      },")]
        assert "document.querySelector('.scope-panel')" in seg, \
            "closeScope не определяет, был ли фокус внутри панели"
        assert "document.querySelector('.scope-wrap > .scope-trigger')" in seg, \
            "нет цели возврата фокуса (.scope-trigger)"
        assert "trigger.focus()" in seg, "фокус не возвращается в триггер"


class TestTopbar:
    def test_desktop_single_row(self):
        """≥1200: заголовок/область/пользователь в одну компактную строку."""
        block = _media_block(CSS, "@media (min-width: 1200px)",
                             "header-scope-row { display: contents; }")
        assert ("header.header-sticky.header-compact-v2 .header-scope-row "
                "{ display: contents; }") in block
        assert ("header.header-sticky.header-compact-v2 .header-fs-btn "
                "{ order: 9; }") in block

    def test_two_row_kept_for_tablet(self):
        """768–1199 (D5/ADR-1025-12) — прежняя двухстрочная компактная шапка."""
        assert ".header-compact-v2 .header-scope-row" in CSS
        assert re.search(r"order: 10; flex: 1 1 100%;", CSS)

    def test_content_starts_below_header(self):
        """Контент структурно ниже шапки: flex-колонка + резерв --header-h."""
        assert "header.header-sticky { flex: 0 0 auto; }" in CSS
        assert "scroll-padding-top: calc(var(--header-h" in CSS
        assert ".app-shell {\n      display: flex; flex-direction: column;" in CSS
        # Механизм измерения резерва не менялся.
        assert "setProperty('--header-h'" in JS

    def test_section_title_not_config_tab(self):
        """Топбар называет раздел: на хабе «ИИ» — «ИИ», не «LLM Провайдеры»."""
        assert "return this.currentTabLabel;" in JS
        assert "var rl = this._routeLabel(r);" in JS

    def test_no_fake_parent_breadcrumb(self):
        """У верхнеуровневого раздела нет крошки-«Статуса»."""
        assert "if (!parent || parent === '#/') return null;" in JS

    def test_no_duplicate_hub_title(self):
        """Имя раздела не дублируется заголовком внутри контента (любая ширина).

        ASAP-UI-02 §2.2 вернул название раздела в МОБИЛЬНУЮ шапку (<768),
        поэтому контентный дубль `.hub-title` скрыт не только с ≥768, а
        всегда (ревью F1, 31.10.2026: на 390 в #/ai, #/modules, #/memory,
        #/access имя стояло дважды).
        """
        rule = ".app-shell.ia-v2 .hub-head .hub-title { display: none; }"
        assert rule in CSS
        assert _brace_depth(CSS, CSS.index(rule)) == 0, \
            "правило снова заперто в @media — на телефоне дубль вернётся"
        # Заголовок остаётся в разметке (legacy IA и контекст/подзаголовок).
        assert '<div class="hub-title">Модули</div>' in INDEX


class TestSidebar:
    def test_collapse_affordance(self):
        assert 'data-sidebar-collapse' in INDEX
        assert ':aria-expanded="sidebarCollapsed ? \'false\' : \'true\'"' in INDEX
        assert "toggleSidebarCollapse" in JS
        assert "adminbot.sidebar_collapsed" in JS, "состояние персистится"

    def test_rail_tokens_and_scope(self):
        assert "--sidebar-w:" in CSS and "--sidebar-w-rail:" in CSS
        assert ".app-shell.ia-v2.sidebar-collapsed { padding-left: var(--sidebar-w-rail); }" in CSS
        assert ".app-shell.ia-v2.sidebar-collapsed .sidebar-label { display: none; }" in CSS

    def test_routes_and_rbac_unchanged(self):
        """Разделы/маршруты не переизобретаются этой волной."""
        expected = [
            ("status", "#/"), ("how", "#/how"), ("modules", "#/modules"),
            ("ai", "#/ai"), ("memory", "#/memory"),
            ("oversight", "#/oversight"), ("access", "#/access"),
            ("permsoc", "#/permsoc"),
        ]
        seg = JS[JS.index("var NAV_ITEMS_V2 = ["):]
        seg = seg[:seg.index("];")]
        got = re.findall(r"id: '([a-z_]+)'[^}]*route: '([^']+)'", seg)
        assert got == expected, got
        assert "sidebarGroups.pub" in INDEX and "sidebarGroups.admin" in INDEX
        assert "sidebarGroups.local" in INDEX

    def test_drawer_focus_and_esc(self):
        assert "data-drawer-trigger" in INDEX
        assert '@keydown.esc="closeDrawer()"' in INDEX
        assert "document.querySelector('.app-drawer .sidebar-link')" in JS
        assert "document.querySelector('[data-drawer-trigger]')" in JS


class TestFullscreenContract:
    def test_mechanism_untouched(self):
        assert '@click="toggleFullscreen()"' in INDEX
        assert ':aria-pressed="fsAriaPressed"' in INDEX
        assert "v-if=\"me && fsSlot !== 'hidden'\"" in INDEX
        assert "toggleFullscreen: function" in JS

    def test_ghost_icon_with_hit_area(self):
        """⛶ — compact ghost-icon: прозрачная hit-цель 44×44, без материала.

        EVOL-023 §4 (ревью F1, 31.10.2026): декоративная Tier B мини-линза
        (`.lg-mini-lens`: радиальный градиент, рамка, rim `::after`,
        inset-блики, `backdrop-filter`, тень, скругление) с кнопки снята —
        в шапке она читалась как отдельный стеклянный объект, а §4 требует
        лаконичный иконочный контрол с прозрачной областью нажатия.
        Материал `.lg-mini-lens` в CSS остаётся (glass-тест-стенд), но на
        функциональной кнопке его быть не должно.
        """
        m = re.search(r"<button[^>]*header-fs-btn[^>]*>", INDEX)
        assert m, "кнопка ⛶ на месте"
        tag = m.group(0)
        assert "lg-mini-lens" not in tag, \
            "декоративная мини-линза снова привязана к функциональной кнопке"
        assert not re.search(r'class="[^"]*lg-mini-lens', INDEX), \
            "материал .lg-mini-lens не должен появляться в разметке ⛶"
        assert "background" not in tag.lower()
        assert ":title=" in tag or 'title="' in tag, "tooltip обязателен"
        assert ":aria-label=" in tag or 'aria-label="' in tag, \
            "доступное имя ⛶ обязательно"
        assert '@click="toggleFullscreen()"' in tag, "действие не потеряно"

        # Объявленный контракт: прозрачная подложка и полное отсутствие
        # декоративного материала (не «за счёт preflight tailwind»).
        rule = re.search(r"\n\.header-fs-btn\s*\{([^}]*)\}", CSS)
        assert rule, "правило .header-fs-btn не найдено"
        # Комментарии внутри правила не участвуют в оценке материала.
        body = re.sub(r"/\*.*?\*/", "", rule.group(1), flags=re.S)
        for decl in ("background: transparent;", "border: 0;",
                     "box-shadow: none;", "backdrop-filter: none;"):
            assert decl in body, "нет объявленного ghost-контракта: " + decl
        for bad in ("radial-gradient", "rgba(", "border-radius: 50%",
                    "inset 0 1px 0"):
            assert bad not in body, "в правиле кнопки остался материал: " + bad

        # Ни одно правило не навешивает материал на ⛶, включая hover/active.
        assert not re.search(r"\.header-fs-btn[^{,}]*\.lg-mini-lens", CSS), \
            "материал мини-линзы привязан к кнопке составным селектором"
        for pseudo in (":hover", ":active"):
            mm = re.search(r"\.header-fs-btn" + pseudo + r"\s*\{([^}]*)\}", CSS)
            if mm:
                for bad in ("background", "box-shadow", "backdrop-filter"):
                    assert bad not in mm.group(1), \
                        f"{pseudo} снова красит подложку: {bad}"

        # Прозрачная, но удобная область нажатия ≥44×44 (не менялась).
        assert re.search(r"\.header-fs-btn\s*\{[^}]*min-width:\s*44px", CSS)
        assert re.search(r"\.header-fs-btn\s*\{[^}]*min-height:\s*44px", CSS)


class TestOverlayLayer:
    def test_single_overlay_contract(self):
        """modal/drawer/context menu/scope-panel — один слой и одна подложка."""
        for tok in ("--overlay-bg:", "--overlay-border:", "--overlay-shadow:",
                    "--overlay-radius:", "--overlay-z:"):
            assert tok in CSS, tok
        assert ".scope-panel,\n.scope-tech-body,\n.more-menu-panel {" in CSS
        assert ".viz-ovpop,\n.cover-menu {" in CSS

    def test_focus_visible_tokens(self):
        assert "--focus-ring:" in CSS and "--focus-ring-offset:" in CSS
        for sel in (".sidebar-link:focus-visible",
                    ".scope-trigger:focus-visible",
                    ".scope-option:focus-visible",
                    ".breadcrumb-link:focus-visible"):
            assert sel in CSS, sel

    def test_modal_focus_helper(self):
        """Клавиатура: фокус входит в диалог, Esc/возврат — штатные."""
        assert "_focusOpenedDialog: function" in JS
        assert "this._focusOpenedDialog();" in JS
        assert '[role="dialog"][tabindex="-1"]' in JS

    def test_honest_empty_states_kept(self):
        """Пустые состояния объясняют причину (не «всё OK, но данных нет»)."""
        for marker in ("Бюджет недоступен.",
                       "Пока нечего показать — в графе памяти нет подтверждённых фактов.",
                       "PERMsoc работает только для конкретного чата. Выбери чат или ЛС"):
            assert marker in INDEX, marker

    def test_icon_only_refresh_labelled(self):
        """Иконочные ⟳ получили доступные подписи (клавиатура/скринридер)."""
        buttons = re.findall(r"<button[^>]*>⟳</button>", INDEX)
        assert len(buttons) >= 33, len(buttons)
        missing = [b for b in buttons if "aria-label=" not in b]
        assert not missing, ("иконочная ⟳ без доступного имени: "
                            + str(len(missing)))


class TestAsapUi02Navigation:
    """ASAP-UI-02 §2 (31.10.2026): навигация, шапка, идентификация, иконки.

    Действующий контракт — `docs/ui-navigation-contract.md`: постоянного
    нижнего навбара нет, на телефоне навигация в drawer, логотип Adminbot
    удалён, аватар и бейдж реальной роли остаются видимыми, «Ещё» —
    троеточие. Проверки структурные; поведение — в e2e
    `tools/ui_evol_w7_nav_e2e.py` и `ui_evol_w9_responsive_e2e.py`.
    """

    def test_no_persistent_bottom_nav(self):
        assert "mobile-topnav" not in INDEX, \
            "постоянной нижней панели разделов нет в разметке"
        assert "mobile-topnav" not in CSS, \
            "её CSS (и ландшафтный рейл) удалён"
        assert "--bottom-nav-h" not in JS, \
            "метрика панели удалена вместе с потребителем"
        assert "padding-right: calc(58px" not in CSS, \
            "резерв контента под рейл удалён"

    def test_single_drawer_reachable_on_phone(self):
        assert 'v-if="iaV2 && hasDrawer"' in INDEX
        assert 'data-drawer-trigger' in INDEX
        assert "return this.shellMode !== 'desktop';" in JS
        assert INDEX.count('class="app-drawer"') == 1, \
            "один drawer, без второй мобильной копии навигации"

    def test_brand_removed_without_empty_slot(self):
        for marker in ("mobile-brand", "sidebar-brand", "AdminBot</span>"):
            assert marker not in INDEX, marker
        assert "sidebar-brand" not in CSS and "mobile-brand" not in CSS
        assert 'class="sidebar-top"' in INDEX, \
            "верхняя строка панели занята функциональной кнопкой, не заглушкой"
        assert "data-sidebar-collapse" in INDEX

    def test_mobile_header_keeps_identity_and_role(self):
        assert "header-user-role" in INDEX and ":title=\"me.role_name\"" in INDEX
        assert ".app-shell.shell-mobile .header-user-name { display: none; }" in CSS
        assert ".header-user span { display: none; }" not in CSS, \
            "прежнее правило скрывало бейдж роли целиком"
        assert "header-user-initial" in INDEX, \
            "аватар не исчезает при отсутствии фото"

    def test_user_initial_styled_for_all_shells(self):
        """Инициал-аватар оформлен не только для `.shell-mobile`.

        Раньше правило жило под `.app-shell.shell-mobile` — на desktop и
        compact при отсутствии фото инициал выводился «голым» текстом.
        """
        assert "\n.header-user-initial {" in CSS
        assert ".app-shell.shell-mobile .header-user-initial {" not in CSS, \
            "правило снова заперто в мобильном shell"

    def test_title_once_and_single_row(self):
        assert ".app-shell.shell-mobile header.header-sticky.header-compact-v2 .header-title-wrap" in CSS
        assert not re.search(
            r"\.app-shell\.shell-mobile header\.header-sticky\.header-compact-v2 "
            r"\.header-title-wrap \{\s*\n\s*display: none;", CSS), \
            "название раздела не скрывается на телефоне"
        seg = CSS[CSS.index(".app-shell.shell-mobile header.header-sticky.header-compact-v2 {"):]
        seg = seg[:seg.index("}")]
        assert "flex-wrap: nowrap" in seg, "второго ряда шапки нет"
        # Ревью F1: имя раздела — РОВНО один раз и на телефоне. Пока правило
        # жило в @media (min-width:768), на 390 имя стояло и в шапке, и в
        # контентном заголовке хаба (#/ai, #/modules, #/memory, #/access).
        rule = ".app-shell.ia-v2 .hub-head .hub-title { display: none; }"
        assert rule in CSS, "контентный дубль заголовка не скрыт"
        assert _brace_depth(CSS, CSS.index(rule)) == 0, \
            "правило дубля снова заперто в @media — на <768 дубль вернётся"
        assert not re.search(r"\.hub-head \.hub-title \{[^}]*display:\s*"
                             r"(block|flex|inline|inline-block)", CSS), \
            "какое-то правило снова показывает заголовок хаба"
        # Единственный источник имени в контенте — тот же `.hub-title`, и он
        # скрыт; второго (видимого) имени раздел в контент не рисует.
        assert ".hub-head .hub-title { font-size" in CSS, \
            "`.hub-title` остаётся в разметке (legacy IA) — скрыт только дубль"

    def test_chat_name_stays_identifiable_on_narrow_phone(self):
        """Ревью F2: на 320–419 триггер области называет ВЫБРАННЫЙ чат.

        Было: `@media (max-width:419px)` прятал `.scope-name` и аватар чата —
        оставался только бейдж «ЧАТ ▾», и выбранный чат нельзя было опознать.
        Стало: имя чата остаётся (обрезается ellipsis, полное — в title и в
        панели), а место освобождает перенос ghost-⛶ в меню «⋯» (§2.3).
        """
        assert (".app-shell.shell-mobile .scope-trigger .scope-name "
                "{ display: none; }") not in CSS, \
            "имя выбранного чата снова скрывается на узком телефоне"
        block = _media_block(CSS, "@media (max-width: 419px)", ".scope-name")
        assert "display: inline-block" in block
        # Идентифицирует ИМЯ чата: аватар-инициал уступает ему место (двух
        # подсказок об одном чате на 320 px не хватает).
        assert (".scope-trigger > .scope-initial { display: none; }" in block), \
            "место освобождается не у аватара чата"
        # Место берётся из второстепенного действия, а не из идентификации.
        assert ("header.header-sticky.header-compact-v2 .header-fs-btn "
                "{\n    display: none;") in block, \
            "⛶ не убран из шапки на ≤419 — имя чата снова не поместится"
        assert ".app-shell.shell-mobile .more-menu-action { display: flex; }" in block
        assert ".app-shell.shell-mobile .more-menu-action { display: flex; }" in block
        assert "data-fs-menu-item" in INDEX
        assert '@click="moreMenuFullscreen()"' in INDEX
        assert "moreMenuFullscreen: function" in JS
        # Бейдж типа области (CHAT/GLOBAL) и ▾ по-прежнему не сжимаются.
        assert ".scope-trigger .badge," in CSS
        # Обрезка — только визуальная: полное имя в title и в опциях панели.
        assert ':title="scopeTriggerTitle"' in INDEX
        assert 'class="scope-name truncate"' in INDEX

    def test_drawer_keyboard_trap_esc_and_back(self):
        """Ревью F3: drawer держит Tab, Esc и Back.

        Было: после восьмого пункта Tab уходил на BODY/кнопки шапки при
        открытой панели; глобальный `escClose()` про drawer не знал (Esc не
        работал, если фокус уже вне панели); `goBack()` уводил маршрут под
        открытой панелью.
        """
        assert '@keydown="drawerOnKeydown($event)"' in INDEX
        assert 'drawerOpen ? \'drawer-open\' : \'\'' in INDEX
        trap = JS[JS.index("drawerOnKeydown: function"):]
        trap = trap[:trap.index("\n      },")]
        assert "e.key !== 'Tab'" in trap
        assert "preventDefault" in trap
        assert "shiftKey" in trap
        assert ".app-drawer" in trap and "offsetParent" in trap, \
            "ловушка считает реально фокусируемые узлы панели"
        esc = JS[JS.index("escClose: function () {"):]
        esc = esc[:esc.index("\n      },")]
        assert "if (this.drawerOpen) { this.closeDrawer(); return; }" in esc
        assert esc.index("moreMenuOpen") < esc.index("drawerOpen"), \
            "порядок слоёв: «⋯» выше открытого drawer"
        back = JS[JS.index("goBack: function () {"):]
        back = back[:back.index("\n      },")]
        assert "if (this.drawerOpen) { this.closeDrawer(); return; }" in back, \
            "Back не закрывает drawer перед переходом"
        # Возврат фокуса — в кнопку «Навигация» (тот же паттерн closeDrawer).
        assert "document.querySelector('[data-drawer-trigger]')" in JS

    def test_more_entry_is_ellipsis_not_grid(self):
        assert 'data-more-trigger' in INDEX
        i = INDEX.index("data-more-trigger")
        seg = INDEX[i - 400:i + 900]
        assert "grid_view" not in seg, "«Ещё» больше не четыре квадрата"
        assert "ui-ic" in seg, "единый icon-контракт"
        assert ".ui-ic {" in CSS and "width: 20px" in CSS

    def test_hit_areas(self):
        assert re.search(r"\.header-nav-btn,\s*\n?\.header-more-btn \{[^}]*"
                         r"min-width: 44px", CSS.replace("\r", ""))
        assert "min-height: 44px" in CSS

    def test_drawer_focus_and_esc(self):
        assert '@keydown.esc="closeDrawer()"' in INDEX
        assert ":inert=\"drawerOpen ? null : ''\"" in INDEX
        assert "document.querySelector('.app-drawer .sidebar-link')" in JS
        assert "document.querySelector('[data-drawer-trigger]')" in JS
        assert 'drawerOpen ? \'drawer-open\' : \'\'' in INDEX, \
            "открытый drawer помечает shell (scroll-lock под подложкой)"
        assert ".app-shell.drawer-open main.scroll-area { overflow: hidden; }" in CSS


class TestJsUnit:
    def test_js_unit_evol_w7_nav(self):
        node = _node()
        script = "tests/js/evol_w7_nav_test.js"
        res = subprocess.run([node, script], capture_output=True, text=True,
                             timeout=60, cwd=str(ROOT))
        assert res.returncode == 0, "JS-UNIT провалился:\n%s\n%s" % (
            res.stdout, res.stderr)
        assert "JS-UNIT-OK" in res.stdout


def _node() -> str:
    import os
    import shutil
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    return node
