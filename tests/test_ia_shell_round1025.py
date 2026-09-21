"""F1 round 10.25 — IA/app-shell (T-2391/T-2392/T-2395/T-2397/T-2398/T-2404).

Маркеры новой информационной архитектуры (ADR-1025-1 D1–D6) и kill-switch
`IA_V2_ENABLED` (OFF → legacy navbar). Поведение OFF/ON (`navItems`) реально
прогоняется в `tests/js/routing_test.js` / `round1025_ia_routing_test.js`.
"""
from pathlib import Path

from services import param_catalog as pc

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = ((ROOT / "web" / "index.html").read_text(encoding="utf-8")
        + (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8"))
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")
TG_INIT = (ROOT / "web" / "static" / "telegram-init.js").read_text(encoding="utf-8")


class TestBackendNav:
    def test_nav_memory_added(self):
        assert pc.NAV_MEMORY == "memory"
        assert pc.NAV_ORDER == ("modules", "ai", "memory", "permsoc")
        assert pc.NAV_TITLES["memory"] == "Память"
        assert set(pc.TAB_NAV.values()) == set(pc.NAV_ORDER)

    def test_memory_tabs_relocated(self):
        for tab in (pc.TAB_MEMORY_RAG, pc.TAB_CHAT_LORE, pc.TAB_RELATIONS):
            assert pc.tab_nav(tab) == pc.NAV_MEMORY
        for tab in (pc.TAB_LLM_PROVIDERS, pc.TAB_PROMPTS,
                    pc.TAB_SMART_CACHE, pc.TAB_PEOPLE_NAMES):
            assert pc.tab_nav(tab) == pc.NAV_AI


class TestKillSwitch:
    def test_settings_env_classvar_default_on(self):
        assert 'IA_V2_ENABLED: ClassVar[bool] = _env_bool("IA_V2_ENABLED", True)' \
            in SETTINGS
        # вне param_catalog (Δ каталога = 0).
        assert not hasattr(pc, "IA_V2_ENABLED")

    def test_ui_flags_delivery_bool_only(self):
        assert '"IA_V2_ENABLED": bool(settings.IA_V2_ENABLED)' in ROUTES

    def test_frontend_flag_branch(self):
        assert "iaV2: function ()" in JS
        assert "return this.uiFlag('IA_V2_ENABLED');" in JS
        # OFF → legacy navbar (полоса рендерится только при !iaV2).
        assert 'v-if="!iaV2" class="navbar-band' in HTML
        # legacy-константы сохранены литерально (гарант OFF байт-в-байт).
        assert "var NAV_ITEMS = [" in JS
        assert "var HUBS = {" in JS
        assert "var NAV_ITEMS_V2 = [" in JS
        assert "var HUBS_V2 = {" in JS


class TestShellMarkers:
    def test_sidebar_drawer_bottom_nav(self):
        assert 'class="app-sidebar"' in HTML
        assert 'class="app-drawer"' in HTML
        assert 'class="bottom-nav"' in HTML
        assert 'class="more-sheet"' in HTML
        # Постоянный sidebar — строго с 1200 px.
        assert "@media (min-width: 1200px)" in HTML
        assert ".app-shell.ia-v2 .app-sidebar" in HTML

    def test_mobile_shell_and_breakpoints(self):
        assert "isMobileShell: function ()" in JS
        assert "isCompactShell: function ()" in JS
        assert "bottomNavItems: function ()" in JS
        assert "mobileMoreItems: function ()" in JS
        # touch ≥44×44 + safe-area.
        assert "min-height: 44px" in HTML
        assert "env(safe-area-inset-bottom" in HTML

    def test_breadcrumb_nested(self):
        assert "breadcrumb: function ()" in JS
        assert 'class="breadcrumb"' in HTML

    def test_tma_integration(self):
        assert "safeAreaInset" in TG_INIT
        assert "contentSafeAreaInset" in TG_INIT
        assert "viewportStableHeight" in TG_INIT

    def test_hotfix4_bottom_nav_order_and_viewport_offset(self):
        """hotfix4 (T-2514/T-2516/T-2519, ADR-1025-8 D2/D3): offset-переменная + cover.
        C: `status`+`how` — первые два для всех ролей."""
        # B: viewport-fit=cover + CSS-компенсация нижнего бара (HTML = index + app.css).
        assert "viewport-fit=cover" in HTML
        assert "--tg-viewport-bottom-offset" in HTML
        assert "100dvh - var(--tg-viewport-stable-height" in HTML
        # C: порядок нижней навигации.
        seg = JS[JS.index("bottomNavItems: function"):
                 JS.index("mobileMoreItems: function")]
        assert "byId['status']" in seg
        assert "byId['how']" in seg
        assert "byId['modules'] || byId['ai']" in seg


class TestNoCompetingHome:
    def test_no_obzor_screen(self):
        # «Обзор» как конкурирующая главная запрещён (§4); есть «Аналитика».
        for forbidden in ("label: 'Обзор'", "label: 'Обор'",
                          "id: 'overview'"):
            assert forbidden not in JS, forbidden
        assert "label: 'Аналитика'" in JS
        assert "'#/oversight'" in JS
        # Статус — стартовая (#/ → status).
        assert "'#/': 'status'" in JS


class TestHelpAndAccessLayout:
    def test_help_layout_and_anchors(self):
        assert 'class="help-layout"' in HTML
        assert 'class="help-toc card p-4"' in HTML
        assert "helpContent: function ()" in JS
        assert "filteredHelpToc: function ()" in JS
        assert "scrollToAnchor: function (id)" in JS
        # тексты/стиль справки не меняем — контейнеры сохранены.
        assert 'class="info-html' in HTML
        assert 'class="guide-markdown' in HTML

    def test_access_mobile_sequential(self):
        assert 'class="avail-list matrix-table"' in HTML
        assert "data-label=" in HTML
        assert ".matrix-table thead { display: none; }" in HTML
