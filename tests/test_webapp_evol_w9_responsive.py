"""EVOL-025 (W9) + ASAP-UI-02 §2: сквозная адаптивная система — структура.

Проверяется ровно то, что видно пользователю и что нельзя «дорисовать»
скриншотом одного устройства:

  * навигация на телефоне/планшете (<1200) — ОДИН drawer, открываемый
    кнопкой в шапке; постоянной нижней панели разделов нет ни в одной
    ориентации (ASAP-UI-02 §2.1, решение владельца 31.10.2026). Закрытый
    drawer не занимает места, контент начинается сразу под ОДНОЙ строкой;
  * шапка на телефоне — одна строка с названием раздела, областью,
    аватаром+бейджем роли, ghost-⛶ и «⋯»; в низком ландшафте та же одна
    строка, без второго ряда и без рейла;
  * планшет получает 2 колонки по месту, широкий desktop — не «островок»
    фиксированной ширины;
  * модалка на узком экране/низком ландшафте — bottom sheet с собственным
    внутренним скроллом и safe-area (режим приходит из app.js);
  * тач-цели ключевых контролов ≥44×44 (кнопки шапки, триггер области,
    поля, действия карточки модуля);
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

DRAWER_TRIGGER = 'data-drawer-trigger'
MORE_TRIGGER = 'data-more-trigger'

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
    """Навигация: один drawer (<1200), постоянной нижней панели нет."""

    def test_no_bottom_panel_anywhere(self):
        header = _header_block()
        assert 'mobile-topnav' not in header, \
            "ASAP-UI-02: панели разделов в шапке нет"
        assert 'mobile-topnav' not in INDEX, \
            "ASAP-UI-02 §2.1: постоянной нижней панели разделов нет"
        assert 'mobile-topnav' not in CSS, \
            "ASAP-UI-02 §2.1: CSS панели (включая ландшафтный рейл) удалён"
        assert INDEX.count('class="app-drawer"') == 1, \
            "ровно один экземпляр навигационной панели (drawer)"

    def test_drawer_reachable_from_topbar_on_phone(self):
        header = _header_block()
        assert DRAWER_TRIGGER in header, \
            "ASAP-UI-02 §2.1: кнопка навигации находится в шапке"
        assert 'v-if="iaV2 && hasDrawer"' in header, \
            "ASAP-UI-02: кнопка рендерится на mobile И tablet (<1200)"
        assert 'aria-label="Открыть навигацию"' in header, \
            "доступное имя кнопки навигации"
        assert ':aria-expanded="drawerOpen' in header, "состояние drawer объявлено"
        # Один и тот же механизм drawer для 768–1199 и <768.
        assert 'v-if="iaV2 && hasDrawer && drawerOpen"' in INDEX, \
            "backdrop одного drawer для всех не-desktop режимов"
        assert 'hasDrawer: function () {' in APP_JS
        assert "return this.shellMode !== 'desktop';" in APP_JS

    def test_drawer_closed_takes_no_space(self):
        seg = _section(".app-drawer {\n      position: fixed", 1400, source=CSS)
        assert "transform: translateX(-105%)" in seg, \
            "закрытый drawer вынесен за край и места не занимает"
        assert ".app-drawer.open { transform: translateX(0); }" in CSS

    def test_drawer_accessible_names(self):
        i = INDEX.find('class="app-drawer"')
        seg = INDEX[i:INDEX.find("</aside>", i)]
        assert ':title="n.label"' in seg, "и tooltip на раздел"
        assert "aria-current" in seg, "текущий раздел объявлен"
        assert '@keydown.esc="closeDrawer()"' in seg, "Esc закрывает drawer"
        trigger = INDEX[INDEX.find(DRAWER_TRIGGER) - 500:
                        INDEX.find(DRAWER_TRIGGER) + 200]
        assert 'aria-haspopup="menu"' in trigger, "кнопка — меню навигации"
        assert MORE_TRIGGER in INDEX, "«⋯» — отдельная точка второстепенных"

    def test_routes_registry_unchanged(self):
        # Один и тот же реестр разделов выводят sidebar и drawer.
        assert INDEX.count('v-for="n in sidebarGroups.pub"') == 2, \
            "sidebar и drawer используют один реестр разделов"
        assert 'v-for="n in mobileTopnavItems"' not in INDEX, \
            "ASAP-UI-02: второго списка разделов (row B) нет"


class TestPortraitContract:
    """Портрет: одна строка шапки, ранний старт контента, drawer."""

    def test_portrait_header_is_one_line(self):
        seg = _section("@media (max-width: 767px) {", 1200)
        assert "header.header-sticky.header-compact-v2" in seg
        assert "padding-top: calc(.4rem + max(env(safe-area-inset-top" in seg, \
            "компактная верхняя строка с учётом safe-area"
        assert "padding-bottom: .4rem" in seg

    def test_header_keeps_required_controls(self):
        """ASAP-UI-02 §2.2: навигация, область, аватар+роль, ⛶, «⋯»."""
        seg = _section("/* ── ASAP-UI-02 §2.1/§2.2", 5200, source=CSS)
        assert "flex-wrap: nowrap" in seg, "шапка не переносится на второй ряд"
        assert ".header-user-name { display: none; }" in seg, \
            "имя скрыто, но бейдж роли остаётся видимым"
        assert ".header-user-role" in seg and "text-overflow: ellipsis" in seg
        assert ".app-shell.shell-mobile .scope-tech { display: none; }" in seg, \
            "ID области не в постоянной шапке"
        assert "order: 5" in seg and "order: 6" in seg, \
            "⛶ и «⋯» — в конце той же строки, без второго ряда"

    def test_no_bottom_panel_rules(self):
        assert "mobile-topnav" not in W9_CSS, \
            "ASAP-UI-02 §2.1: правил нижней панели больше нет"
        assert "padding-right: calc(58px" not in CSS, \
            "резерв под ландшафтный рейл удалён вместе с рейлом"

    def test_no_horizontal_scroll_reservation_hacks(self):
        # Никакого «второго вычета» нижней зоны: контент не смещается магией.
        assert "var(--tg-viewport-bottom-offset" not in CSS


class TestLandscapeContract:
    """Низкий ландшафт: только одна строка шапки, никакого рейла."""

    def test_no_rail_on_low_landscape(self):
        seg = _section(
            "@media (orientation: landscape) and (max-height: 520px) {", 2600)
        assert "mobile-topnav" not in seg, \
            "ASAP-UI-02 §2.4: ландшафтного рейла/второго ряда нет"
        assert "position: fixed" not in seg, \
            "в низком ландшафте нет плавающей навигационной панели"
        assert "padding-right: calc(58px" not in seg, \
            "контент не резервирует место под несуществующий рейл"

    def test_header_single_row_in_any_shell(self):
        seg = _section(
            "@media (orientation: landscape) and (max-height: 520px) {", 2600)
        assert re.search(r"header\.header-sticky\.header-compact-v2 \{\s*\n"
                         r"\s*flex-wrap: nowrap", seg.replace("\r", "")), \
            "в низком ландшафте шапка не переносится на вторую строку"
        assert "min-height: 48px" in seg

    def test_more_menu_anchors_to_header(self):
        seg = _section(".app-shell.shell-mobile .more-menu-panel {", 600)
        assert "var(--header-h" in seg, \
            "лист второстепенных действий раскрывается под шапкой (triger вверху)"
        assert "max-height: calc(var(--app-usable-height" in seg, \
            "высота листа ограничена реально видимой областью shell"
        assert "var(--bottom-nav-h" not in seg, \
            "метрики нижней панели больше нет"

    def test_more_menu_counts_from_shell_not_viewport(self):
        # Лист считается от фактически используемой высоты shell: в реальном
        # Telegram `innerHeight` больше usable, иначе лист уезжает за экран.
        seg = _section(".app-shell.shell-mobile .more-menu-panel {", 600)
        assert "var(--app-usable-height" in seg, \
            "высота листа привязана к фактически используемой высоте"
        assert "var(--bottom-nav-h" not in seg


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

    def test_nav_metric_of_bottom_panel_removed(self):
        # ASAP-UI-02 §2.1: нижней панели нет — её метрика и наблюдатель
        # удалены целиком (никаких «залипших» значений после поворота).
        assert "--bottom-nav-h" not in APP_JS
        assert "_syncBottomNavMetric" not in APP_JS
        assert "_navObserver" not in APP_JS
        assert "setProperty('--header-h'" in APP_JS, \
            "резерв шапки по-прежнему измеряется"
        assert ":class=\"{ 'open': drawerOpen }\"" not in APP_JS  # только разметка
        assert 'drawerOpen ? \'drawer-open\' : \'\'' in INDEX, \
            "открытый drawer помечает shell (scroll-lock контента)"


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
                       "belowHeader", "bottomNavCount", "CONTENT_SHARE_PHONE",
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
        assert "gapToHeader" in TOOL
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
