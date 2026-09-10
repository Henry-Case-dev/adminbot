"""Редизайн 10.5 (T-1099) — hash-роутинг + нативный BackButton.

Маркеры (design-project.md §6.2/§6.3/§6.4):
  * route — источник истины (hash '#/...'), vue-router НЕ используется;
  * initData читается/кэшируется ДО любой записи hash;
  * launch-hash (tgWebAppData) НЕ трактуется как маршрут;
  * hashchange — единственный «применитель» роута;
  * BackButton.onClick регистрируется ОДИН раз; goBack() → routeParent,
    БЕЗ history.back()/popstate (защита от петель);
  * depth>0 → show() (← вместо ✕), depth 0 → hide();
  * Bot API 6.1+ guard + in-app fallback при отсутствии нативного;
  * __TMA_BACK__=true, __TMA_DEEPLINK__=false (OD13, deep-link OFF).

Тестов на JS в проекте нет — это статические маркеры (как остальные
test_webapp_*_ui), + smoke-проверка чистых функций роутера.
"""
import re


def _js() -> str:
    return open("web/app.js", encoding="utf-8").read()


def _html() -> str:
    return open("web/index.html", encoding="utf-8").read()


class TestRoutePureFunctions:
    """§6.3: таблица роутов ↔ вкладки ↔ parent/depth."""

    def test_route_table_present(self):
        js = _js()
        assert "ROUTE_TO_TAB" in js
        assert "TAB_TO_ROUTE" in js
        for route in [
            "'#/'", "'#/oversight'", "'#/how'", "'#/modules'",
            "'#/modules/switches'", "'#/modules/reactions'",
            "'#/permsoc'", "'#/ai'", "'#/ai/llm'", "'#/ai/prompts'",
            "'#/ai/limits'", "'#/ai/memory'", "'#/ai/sleep'",
            "'#/ai/nostalgia'", "'#/ai/names'", "'#/ai/relations'",
            "'#/ai/lore'", "'#/access'", "'#/access/roles'",
            "'#/access/local'", "'#/access/admins'",
        ]:
            assert route in js, route

    def test_route_tab_roundtrip_markers(self):
        js = _js()
        # routeToTab/tabToRoute + parent/depth — чистые функции (покрыты).
        for fn in [
            "function normalizeRoute(hash)",
            "function routeToTab(route)",
            "function tabToRoute(tabId)",
            "function routeParent(route)",
            "function routeDepth(route)",
        ]:
            assert fn in js, fn
        assert "function initialRoute()" in js
        assert "function getInitData()" in js

    def test_depth_root_vs_nested(self):
        js = _js()
        assert "ROOT_ROUTES" in js
        # Корневые роуты эталона → depth 0 (нативный ✕), вложенные → 1.
        assert "routeParent(route) ? 1 : 0" in js


class TestBootInitDataBeforeHash:
    """§6.1/§6.2 п.1: сначала initData, только потом hash."""

    def test_get_init_data_before_hash(self):
        js = _js()
        # created(): сначала getInitData(), затем initialRoute()/hash.
        created = js[js.index("created: function ()"):]
        created = created[:created.index("mounted: function ()")]
        i_data = created.index("getInitData()")
        i_route = created.index("initialRoute()")
        assert i_data < i_route
        assert "adminbot.initData" in js
        assert "sessionStorage" in js

    def test_has_init_data_uses_cache(self):
        js = _js()
        body = js[js.index("hasInitData: function ()"):]
        body = body[:body.index("retryInitData: function ()")]
        assert "getInitData()" in body

    def test_launch_hash_ignored(self):
        js = _js()
        # Валиден ТОЛЬКО hash, начинающийся с '#/'.
        assert "hash.indexOf('#/') !== 0" in js
        assert "function normalizeRoute(hash)" in js
        # replaceState вместо «в лоб» (§6.2 п.4).
        assert "history.replaceState(null, '', r)" in js


class TestBackButtonIntegration:
    """§6.4.4: конечный автомат back-навигации."""

    def test_hashchange_single_applier(self):
        js = _js()
        assert "window.addEventListener('hashchange'" in js
        assert "_appVm.applyRoute(normalizeRoute(window.location.hash) || '#/')" in js
        # ❌ отдельный popstate рядом с hashchange (двойное применение).
        assert "addEventListener('popstate'" not in js

    def test_backbutton_onclick_registered_once(self):
        js = _js()
        assert "initBackButton: function ()" in js
        assert "_backApi.onClick(" in js
        # один обработчик на BOOT, не перерегистрируется на смене роута.
        assert js.count("_backApi.onClick(") == 1

    def test_backbutton_reinit_on_ready(self):
        """R10.5-1: late-ready Telegram-контекст → initBackButton() снова,
        с guard'ом на повторную привязку onClick."""
        js = _js()
        assert "_boundBackApi" in js                 # guard ровно-один-раз
        assert "_boundBackApi !== _backApi" in js
        ready = js[js.index("onEvent('ready'"):]
        ready = ready[:ready.index("});", ready.index("retryInitData"))]
        assert "self.initBackButton()" in ready
        assert "self.retryInitData()" in ready

    def test_goback_uses_parent_not_history(self):
        js = _js()
        body = js[js.index("goBack: function ()"):]
        body = body[:body.index("initBackButton: function ()")]
        assert "routeParent(this.route)" in body
        assert "navigateTo(p)" in body
        # ❌ history.back() как основная реализация — нет (в т.ч. вне goBack).
        assert "history.back()" not in body
        assert "history.back();" not in js
        assert "history.go(" not in js

    def test_sync_visibility_by_depth(self):
        js = _js()
        body = js[js.index("syncBackButton: function ()"):]
        body = body[:body.index("setTab: function (id)")]
        assert "routeDepth(this.route) > 0" in body
        assert ".show()" in body and ".hide()" in body
        assert "window.__TMA_BACK__ !== false" in body

    def test_bot_api_61_guard_and_fallback(self):
        js = _js()
        assert "wa.BackButton" in js
        assert "typeof bb.show === 'function'" in js
        html = _html()
        # in-app fallback ← только при depth>0 И отсутствии нативного.
        assert "routeDepth > 0 && !backNative" in html
        assert '@click="goBack()"' in html
        assert 'aria-label="Назад"' in html

    def test_toggles(self):
        js = _js()
        assert "window.__TMA_BACK__ = true" in js
        assert "window.__TMA_DEEPLINK__ = false" in js      # OD13: OFF
        # deep-link OFF → start_param НЕ вовлекается в маршрутизацию.
        assert "mapStartParam" not in js

    def test_no_vue_router(self):
        js = _js()
        html = _html()
        assert "createRouter" not in js
        assert "VueRouter" not in js
        # Нет подключения vue-router (zero-build, OD3).
        assert "vue-router" not in html

    def test_nav_uses_hash_route(self):
        html = _html()
        # A1/T-1157: sidebar-меню удалено; навигация — navbar navTo → hash.
        assert '@click="navTo(n.route)"' in html
        assert '@click="openTab(tab.id)"' not in html
        assert '@click="setTab(tab.id)"' not in html


class TestScopeSwitcherT1127:
    """§15.1: scopeKind GLOBAL/ЧАТ/ЛС + сброс chat-scoped состояния."""

    def test_scope_kind_and_label(self):
        js = _js()
        assert "scopeKind: function ()" in js
        assert "return this.isDmCtx() ? 'dm' : 'chat';" in js
        assert "scopeLabel: function ()" in js
        assert "scopeEpoch" in js

    def test_scope_reset_broadens_r104_2(self):
        js = _js()
        body = js[js.index("setActiveChat: function (chatId)"):]
        body = body[:body.index("isChatContext: function ()")]
        assert "this.scopeEpoch++" in body
        for marker in [
            "this.chatLoreProfile = null;",
            "this.chatLoreSelectedId = null;",
            "this.chatLoreHistory = [];",
            "this.gateInfo = null;",
            "this.chatAdmins = [];",
        ]:
            assert marker in body, marker


class TestAnimatedGradientTokensT1098:
    """OD4/T-1091: токены эталона + анимированные градиенты, a11y."""

    def test_property_inherits_false(self):
        html = _html()
        assert "@property --grad-angle" in html
        assert "inherits: false" in html
        assert "initial-value: 135deg" in html

    def test_gradient_surfaces_and_contain(self):
        html = _html()
        assert ".grad-band, .btn-accent, .tab-btn.active" in html
        assert "conic-gradient(from var(--grad-angle)" in html
        assert "animation: grad-spin var(--grad-speed) linear infinite" in html
        assert "contain: paint" in html

    def test_reduced_motion_off(self):
        html = _html()
        assert "@media (prefers-reduced-motion: reduce)" in html
        assert "animation: none !important" in html
        assert ".page-wash" in html or "body::before" in html

    def test_hardcode_removed(self):
        html = _html()
        js = _js()
        for bad in ["#8b5cf6", "#3b82f6", "#2b2b40"]:
            assert bad not in html, bad
        assert "#8b5cf6" not in js
        # Tailwind accent/card/accent2 удалены.
        assert "accent2:" not in html
        assert "card: '#" not in html
