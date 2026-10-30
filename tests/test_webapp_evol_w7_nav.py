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
        """Имя раздела не дублируется заголовком внутри контента (≥768)."""
        block = _media_block(CSS, "@media (min-width: 768px)",
                             ".hub-head .hub-title")
        assert ".app-shell.ia-v2 .hub-head .hub-title { display: none; }" in block
        # Заголовок остаётся в разметке (mobile <768 — единственный).
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
        """Лаконичный ghost-icon: подложку даёт только мини-линза (U08.4d)."""
        m = re.search(r"<button[^>]*header-fs-btn[^>]*>", INDEX)
        assert m, "кнопка ⛶ на месте"
        tag = m.group(0)
        assert "lg-mini-lens" in tag, "материал — защищённая мини-линза"
        assert "background" not in tag.lower()
        assert ":title=" in tag or 'title="' in tag, "tooltip обязателен"
        # Прозрачная, но удобная область нажатия ≥44×44 (не менялась).
        assert re.search(r"\.header-fs-btn\s*\{[^}]*min-width:\s*44px", CSS)
        assert re.search(r"\.header-fs-btn\s*\{[^}]*min-height:\s*44px", CSS)
        assert INDEX.count("lg-mini-lens") == 1


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
