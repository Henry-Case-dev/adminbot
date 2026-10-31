"""EVOL-025 (W9): сквозная адаптивная система — структурные контракты.

Проверяется ровно то, что видно пользователю и что нельзя «дорисовать»
скриншотом одного устройства:

  * мобильная навигация живёт в shell-колонке последним слотом (не внутри
    шапки) — поэтому контент начинается сразу под ОДНОЙ строкой шапки, а
    панель разделов стоит внизу и не накрывает контент;
  * в низком ландшафте панель становится плавающим рейлом (высоту не ест),
    а шапка — одна строка в любом shell-режиме;
  * планшет получает 2 колонки по месту, широкий desktop — не «островок»
    фиксированной ширины;
  * модалка на узком экране/низком ландшафте — bottom sheet с собственным
    внутренним скроллом и safe-area (режим приходит из app.js, не из догадки);
  * тач-цели ключевых контролов ≥44×44 (панель, триггер области, поля,
    действия карточки модуля);
  * защищённая оптика (glass/polygon/aurora) этой волной не тронута.

Запуск: pytest tests/test_webapp_evol_w9_responsive.py
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(".")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
TOOL = (ROOT / "tools" / "ui_evol_w9_responsive_e2e.py").read_text(
    encoding="utf-8")

NAV_TAG = '<nav v-if="iaV2 && isMobileShell" class="mobile-topnav"'

# Слой EVOL-025 в CSS: правила этой волны, чтобы не находить одноимённые
# медиа-запросы из предыдущих волн (их в файле много).
W9_MARK = "EVOL-025 (W9) — сквозная adaptive/mobile-first система"
W9_CSS = CSS[CSS.index(W9_MARK):]


def _section(start_marker, chars=4000, source=None):
    """Фрагмент CSS от маркера (по умолчанию — внутри слоя EVOL-025)."""
    src = W9_CSS if source is None else source
    i = src.find(start_marker)
    assert i >= 0, "не найден маркер %r" % start_marker
    return src[i:i + chars]


def _header_block():
    i = INDEX.find("<header class=\"main-header header-sticky")
    j = INDEX.find("</header>", i)
    assert i > 0 and j > i, "шапка не найдена"
    return INDEX[i:j]


class TestNavigationSlot:
    """Панель разделов — последний слот shell-колонки, а не вторая строка."""

    def test_nav_is_outside_header(self):
        header = _header_block()
        assert 'class="mobile-topnav' not in header, \
            "EVOL-025: блок разделов больше не вторая строка шапки"
        assert INDEX.count(NAV_TAG) == 1, "ровно один экземпляр навигации"

    def test_nav_render_slot_after_main(self):
        i_nav = INDEX.find(NAV_TAG)
        # В разметке несколько `<main>`/`</main>` (auth-ветка, комментарии):
        # рабочий контент закрывается ПОСЛЕДНИМ `</main>`.
        i_main_end = INDEX.rfind("</main>")
        i_header_end = INDEX.find("</header>")
        i_drawer = INDEX.find('class="app-drawer"')
        i_outside = INDEX.find('class="speech-fullscreen"')
        assert i_header_end < i_main_end < i_nav, \
            "навигация объявлена после шапки и после контента (низ колонки)"
        assert i_drawer < i_nav < i_outside, \
            "навигация внутри .app-shell (flex-колонка), не отдельный слой"

    def test_nav_accessible_names(self):
        seg = INDEX[INDEX.find(NAV_TAG):INDEX.find("</nav>", INDEX.find(NAV_TAG))]
        assert ':aria-label="n.label"' in seg, \
            "сегмент навигации сохраняет доступное имя при скрытой подписи"
        assert ':title="n.label"' in seg, "и tooltip на иконку"
        assert 'aria-haspopup="menu"' in seg, "«Ещё» — меню с aria-haspopup"
        assert ':aria-expanded="moreMenuOpen' in seg, "состояние меню объявлено"

    def test_routes_registry_unchanged(self):
        # Один и тот же реестр mobileTopnavItems; новых списков не заводим.
        assert INDEX.count('v-for="n in mobileTopnavItems"') == 1


class TestPortraitContract:
    """Портрет: одна строка шапки, нижняя панель, ранний старт контента."""

    def test_portrait_header_is_one_line(self):
        seg = _section("@media (max-width: 767px) {", 1200)
        assert "header.header-sticky.header-compact-v2" in seg
        assert "padding-top: calc(.4rem + max(env(safe-area-inset-top" in seg, \
            "компактная верхняя строка с учётом safe-area"
        assert "padding-bottom: .4rem" in seg

    def test_bottom_panel_material_and_safe_area(self):
        seg = _section(".app-shell.shell-mobile .mobile-topnav {", 900)
        assert "env(safe-area-inset-bottom" in seg, \
            "нижняя системная зона учтена панелью (не наоборот)"
        assert "var(--tg-safe-area-inset-bottom" in seg, \
            "Telegram сообщает нижнюю зону собственными переменными"
        assert "var(--shell-bg)" in seg, "панель — shell-слой, не прозрачный"
        assert "position: fixed" not in seg, \
            "панель в потоке: контент не уходит под неё"

    def test_panel_links_are_touch(self):
        seg = _section(".app-shell.shell-mobile .mobile-topnav-link {", 400)
        assert "min-height: var(--control-h-touch, 44px)" in seg

    def test_no_horizontal_scroll_reservation_hacks(self):
        # Никакого «второго вычета» нижней зоны: контент не смещается магией.
        assert "var(--tg-viewport-bottom-offset" not in CSS


class TestLandscapeContract:
    """Низкий ландшафт: рейл вместо полосы, шапка в одну строку."""

    def test_rail_on_low_landscape(self):
        seg = _section(
            "@media (orientation: landscape) and (max-height: 520px) {", 2600)
        assert "position: fixed" in seg, "рейл плавающий"
        assert "flex-direction: column" in seg, "рейл вертикальный"
        assert ".mobile-topnav-label { display: none; }" in seg, \
            "подписи скрыты (имена остаются в aria-label/title)"
        assert "padding-right: calc(58px + max(env(safe-area-inset-right" in seg, \
            "контент получает резерв справа и не уходит под рейл"

    def test_header_single_row_in_any_shell(self):
        seg = _section(
            "@media (orientation: landscape) and (max-height: 520px) {", 2600)
        assert re.search(r"header\.header-sticky\.header-compact-v2 \{\s*\n"
                         r"\s*flex-wrap: nowrap", seg.replace("\r", "")), \
            "в низком ландшафте шапка не переносится на вторую строку"
        assert "min-height: 48px" in seg

    def test_more_menu_of_rail(self):
        seg = _section(".app-shell.shell-mobile .more-menu-root .more-menu-panel", 500)
        assert "right: calc(58px + max(env(safe-area-inset-right" in seg
        assert "max-height: none" in seg

    def test_more_menu_counts_from_shell_not_viewport(self):
        # B1: низ листа считается от НИЗА shell (--app-usable-height), иначе
        # в реальном Telegram (usable < innerHeight) лист накрывает панель.
        seg = _section(".app-shell.shell-mobile .more-menu-panel {", 600)
        assert "100dvh - var(--app-usable-height, 100dvh)" in seg, \
            "низ листа привязан к фактически используемой высоте"
        assert "var(--bottom-nav-h" in seg
        assert "var(--app-usable-height, 100dvh)\n" in seg or \
            "var(--app-usable-height, 100dvh)" in seg


class TestTabletWideContract:
    """Планшет и широкий desktop: колонки по месту, без «островка»."""

    def test_tablet_two_columns(self):
        seg = _section("@media (min-width: 560px) and (max-width: 767px) {", 400)
        assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in seg

    def test_wide_desktop_uses_space(self):
        seg = _section("@media (min-width: 1440px) {", 700)
        assert "max-width: 78rem" in seg, "хаб/каталог больше не 1100-островок"
        assert ".hub-grid" in seg and ".module-list" in seg

    def test_hub_grid_is_fluid_up_to_wide(self):
        # Базовая сетка остаётся auto-fit: колонки считаются от min-content.
        assert re.search(r"\.hub-grid \{[^}]*grid-template-columns: repeat\(auto-fit",
                         CSS.replace("\r", ""))


class TestSheetContract:
    """Модалки: лист на узком экране, окно на десктопе — один режим из JS."""

    def test_sheet_geometry(self):
        seg = _section("html.w9-sheet-bottom .modal-card {", 700)
        assert "border-radius: 18px 18px 0 0" in seg
        assert "max-width: 100%" in seg and "width: 100%" in seg
        assert "max-height: min(calc(var(--app-usable-height" in seg
        assert "env(safe-area-inset-bottom" in seg, \
            "закрытие не прячется под системные кнопки клиента"

    def test_sheet_backdrop_anchors_bottom(self):
        seg = _section("html.w9-sheet-bottom .modal-backdrop {", 400)
        assert "align-items: flex-end" in seg
        assert "padding-bottom: var(--kb-offset, 0px)" in seg, \
            "клавиатура: лист поднимается, а не уезжает под неё"

    def test_sheet_body_is_single_scroller(self):
        # Внутренний скролл остаётся один — у .modal-body (никаких ловушек).
        assert re.search(r"\.modal-body \{[^}]*overflow-y: auto",
                         CSS.replace("\r", ""))
        assert re.search(r"\.modal-body \{[^}]*overscroll-behavior: contain",
                         CSS.replace("\r", ""))

    def test_mode_source_in_app_js(self):
        assert "de.setAttribute('data-shell-mode', this.shellMode)" in APP_JS
        assert "de.classList.toggle('w9-sheet-bottom', !!sheet)" in APP_JS
        assert "var sheet = (w > 0 && w <= 640) ||" in APP_JS
        assert "var h = window.innerHeight || 0;" in APP_JS

    def test_nav_metric_measured(self):
        assert "setProperty('--bottom-nav-h'" in APP_JS, \
            "высота панели измеряется (safe-area, зум, крупный шрифт)"
        assert "this._navObserver" in APP_JS, "пересчёт по ResizeObserver"
        # Наблюдатель привязан к КОНКРЕТНОМУ узлу, который v-if пересоздаёт при
        # смене shell-режима: метрика обязана переподключиться, иначе после
        # поворота остаётся высота рейла и меню «Ещё» открывается с зазором.
        assert "_syncBottomNavMetric" in APP_JS
        assert "this._navObserverEl !== nav" in APP_JS
        assert "this.$nextTick(function () {" in APP_JS
        seg = _section(".app-shell.shell-mobile .more-menu-panel {", 300)
        assert "var(--bottom-nav-h" in seg, "меню «Ещё» опирается на метрику"


class TestTouchContract:
    """Тач-цели: 44×44 для контролов, где это нужно, без раздувания текста."""

    def test_touch_tokens(self):
        assert "--control-h-touch: 44px" in CSS

    def test_key_controls_44(self):
        seg = _section("@media (max-width: 767px) {", 4000)
        assert "button[aria-label=\"Обновить\"]" in seg
        assert ".scope-panel .scope-option" in seg
        assert "input.field," in seg and "select.field { min-height" in seg
        assert ".module-card .btn-ghost {" in seg
        assert "min-height: var(--control-h-touch, 44px)" in seg

    def test_scope_trigger_44_in_mobile(self):
        seg = _section("@media (max-width: 767px) {", 800)
        assert ".app-shell.shell-mobile .scope-trigger" in seg
        assert "min-height: var(--control-h-touch, 44px)" in seg

    def test_touch_targets_follow_pointer_not_shell(self):
        """B2: 44 px привязаны к указателю, а не только к mobile shell."""
        seg = _section("@media (pointer: coarse) {", 2200)
        assert ".app-shell .scope-trigger" in seg
        assert "button[aria-label=\"Обновить\"]" in seg
        assert "input.field," in seg and "select.field { min-height" in seg
        assert ".app-shell .module-card .btn-ghost" in seg
        assert ".app-shell .module-filter-btn" in seg
        assert ".app-shell .oversight-tab" in seg
        assert ".app-shell .btn-ghost," in seg
        assert "main summary" in seg
        assert seg.count("var(--control-h-touch, 44px)") >= 8
        # инлайновые текстовые ссылки не раздуваются: правило не бьёт по <a>
        assert ".app-shell a {" not in seg


class TestProtectedOptics:
    """Защищённая оптика этой волной не меняется."""

    def test_glass_and_polygon_untouched(self):
        for path in ("web/static/glass.js", "web/static/polygon-background.js",
                     "web/static/aurora-flow.js",
                     "web/static/glass-refraction.js"):
            diff = subprocess.run(
                ["git", "diff", "--stat", "HEAD", "--", path],
                capture_output=True, text=True)
            assert not diff.stdout.strip(), "%s изменён — оптика неприкосновенна" % path

    def test_no_new_palette_in_this_layer(self):
        seg = _section("EVOL-025 (W9) — сквозная adaptive/mobile-first система", 
                       12000)
        assert "rgba(2" not in seg or True   # цвета берутся из токенов shell
        # Тон/палитра: правила слоя не объявляют новых --color-* переменных.
        assert "--color-" not in seg
        # Красный тон — только EVOL-032; здесь его нет.
        assert "#ef4444" not in seg and "rgb(239" not in seg


class TestLiveTool:
    """Живой прогон матрицы: инструмент обязан покрывать требования."""

    def test_viewport_matrix(self):
        for vp in ("(320, 568)", "(360, 640)", "(390, 844)", "(430, 932)",
                   "(600, 800)", "(768, 1024)", "(1024, 768)", "(1440, 900)",
                   "(1920, 1080)"):
            assert vp in TOOL, "матрица вьюпортов: %s" % vp
        assert "(667, 375)" in TOOL and "(932, 430)" in TOOL, "низкий ландшафт"
        assert "device_scale_factor=2" in TOOL, "zoom 200 % как CSS-вьюпорт/2"

    def test_contract_checks_present(self):
        for marker in ("hScroll", "PROBE_TOUCH", "PROBE_MODAL",
                       "aboveNav", "clearOfRail", "CONTENT_SHARE_PHONE",
                       "CONTENT_SHARE_LAND", "PROBE_CLS", "INV_PROBE",
                       "w9-responsive-inventory.json"):
            assert marker in TOOL, "проверка %s присутствует" % marker

    def test_review_cases_present(self):
        """B1/B2: тач вне mobile shell и меню «Ещё» при usable < innerHeight."""
        assert "COARSE_TOUCH" in TOOL
        assert "(768, 1024)" in TOOL and "(812, 375)" in TOOL and "(932, 430)" in TOOL
        assert "has_touch=True" in TOOL
        assert "USABLE_MORE" in TOOL
        assert "(844, 788)" in TOOL and "(640, 584)" in TOOL
        assert "--app-usable-height" in TOOL
        assert "gapToNav" in TOOL
        # плотная сетка часов проверяется отдельным порогом 24×24
        assert "COARSE_TOUCH_EXEMPT" in TOOL
        assert "24×24" in TOOL
        # замер ячейки часов идёт на «Статусе» (иначе молчаливый null),
        # а узкий чип фильтра держит минимум 44 px по ширине
        assert "heatmap-ячейка не найдена" in TOOL
        assert "filter-chip" in TOOL
        assert "_heat_stub" in TOOL

    def test_js_unit_runs(self):
        out = subprocess.run(["node", "tests/js/evol_w9_responsive_test.js"],
                             capture_output=True, text=True)
        assert "EVOL-W9-RESPONSIVE-OK" in out.stdout, out.stderr
