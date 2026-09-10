"""Редизайн 10.5 (T-1100/T-1130/T-1131/T-1133/T-1127/T-1112) — UI-маркеры.

Hub-экраны (6 navbar + карточные сетки), визуальная матрица ролей
(все параметры по секциям + read/write), кастомный a11y scope-dropdown
с аватарами, адаптив ≤991/≤479.
"""
_JS = open("web/app.js", encoding="utf-8").read()
_HTML = open("web/index.html", encoding="utf-8").read()


class TestNavbarAndHubs:
    def test_six_nav_items(self):
        assert "var NAV_ITEMS = [" in _JS
        for label in ("Статус", "Как это работает", "Модули", "Настройки AI",
                      "Функции PERMsoc", "Доступы и Роли"):
            assert label in _JS, label
        assert "navTo(n.route)" in _HTML
        assert "activeNav === n.id" in _HTML

    def test_hub_rendering(self):
        assert "var HUBS = {" in _JS
        assert "hubCards: function ()" in _JS
        assert 'v-if="hubCards"' in _HTML
        assert 'class="hub-card"' in _HTML
        assert "openHubCard(c)" in _HTML
        assert "openHubCard: function (card)" in _JS
        # конфиг-ветка стала else-if (hub — первая)
        assert "v-else-if=\"currentTabIsConfig\"" in _HTML

    def test_hubs_have_children(self):
        for route in ("'#/modules'", "'#/ai'", "'#/access'"):
            assert route in _JS
        assert "'#/modules/features'" in _JS
        assert "sec-matrix" in _HTML
        assert "sec-local" in _HTML
        assert "sec-admins" in _HTML

    def test_oversight_card_on_dashboard(self):
        assert "navTo('#/oversight')" in _HTML


class TestRoleMatrixUi:
    def test_matrix_block_present(self):
        assert 'id="sec-matrix"' in _HTML
        assert "Матрица ролей" in _HTML
        assert "iconGlyph('admin_panel_settings')" in _HTML
        assert "matrixSections()" in _HTML
        assert "matrixRoleToggle(row.key, fld, r)" in _HTML
        assert "matrixReset(row.key)" in _HTML

    def test_matrix_grouped_by_sections(self):
        js = _JS
        assert "matrixSections: function ()" in js
        assert "matrixCategoryTitle: function (cat)" in js
        # D4: секция = config-вкладка мини-аппа (tab), fallback — категория.
        assert "it.tab ||" in js
        assert "TAB_SECTION_ORDER" in js
        assert "tab_title" in js
        # read/write по каждому параметру
        assert "['view_roles', 'edit_roles']" in _HTML
        assert "['user','moderator','local_admin']" in _HTML

    def test_matrix_methods(self):
        for fn in ("loadMatrix: async function", "matrixChecked: function",
                   "matrixRoleToggle: async function", "matrixReset: async function"):
            assert fn in _JS, fn
        assert "/api/access/param_permissions/" in _JS
        assert "loadMatrix()" in _JS  # вызов из setTab('access')

    def test_role_management_present(self):
        assert "createRole()" in _HTML
        assert ">Переименовать</button>" in _HTML
        # delete-кнопка с disabled по правам
        assert ":disabled=\"!canEditRole(role)\"" in _HTML


class TestScopeDropdownA11y:
    def test_listbox_markup(self):
        assert 'role="listbox"' in _HTML
        assert 'role="option"' in _HTML
        assert ':aria-expanded="scopeOpen' in _HTML
        assert ':aria-selected="isScopeSelected(o)' in _HTML
        assert "aria-haspopup=\"listbox\"" in _HTML

    def test_avatars_inside_options(self):
        assert "scopeTriggerAvatar" in _HTML
        assert "o.avatarUrl" in _HTML
        assert "scope-initial" in _HTML        # fallback-инициал
        js = _JS
        assert "ensureScopeAvatars: function ()" in js
        assert "loadAvatar('chat', c.chat_id, c)" in js

    def test_pick_and_reset(self):
        assert "pickScope(o)" in _HTML
        assert "pickScope: function (o)" in _JS
        assert "toggleScope: function ()" in _JS
        assert "closeScope: function ()" in _JS
        # Esc закрывает
        assert '@keydown.esc="closeScope()"' in _HTML

    def test_arrow_key_navigation(self):
        # M2: стрелки/Enter переводят фокус по listbox.
        assert "@keydown.down.prevent=\"scopeMove(1)\"" in _HTML
        assert "@keydown.up.prevent=\"scopeMove(-1)\"" in _HTML
        assert "@keydown.enter.prevent=\"scopePickFocused()\"" in _HTML
        assert "scopeMove: function (delta)" in _JS
        assert "scopePickFocused: function ()" in _JS
        assert "scopeFocus === idx" in _HTML


class TestReviewerMinorsR1R4:
    def test_r1_scope_guards_on_extra_loaders(self):
        # R1: loadKeyStatus + loadChatAdmins (и остальные) снимают epoch.
        assert _JS.count("R1: снимок scope") >= 2
        assert "loadKeyStatus: async function" in _JS
        assert "loadChatAdmins: async function" in _JS

    def test_r2_catch_guards(self):
        # R2: устаревшие ошибки не пишут состояние (>= 6 catch-веток).
        assert _JS.count("R2: устаревшая ошибка") >= 6

    def test_r3_finally_guards(self):
        # R3: busy-флаги не сбрасываются устаревшим finally (>= 5 мест).
        assert _JS.count("// R3") >= 5

    def test_r4_custom_modules_removed(self):
        # A2/T-1187: «Кастомные модули» удалены (B2 остаётся OUT).
        assert "Кастомные модули" not in _JS
        assert "Кастомные модули" not in _HTML
        assert "var MODULES = [" in _JS
        assert "openModuleWindow" in _JS


class TestSanitizerSecurityM1:
    def test_dompurify_self_hosted_pinned(self):
        import os
        assert "/static/vendor/dompurify-3.4.15.min.js" in _HTML
        # нет range-CDN '@3' (fail-risk) и нет внешнего cdn.jsdelivr для purify
        assert "dompurify@3/dist" not in _HTML
        assert os.path.exists(
            "web/static/vendor/dompurify-3.4.15.min.js")

    def test_sanitize_fail_closed(self):
        # M1: нет санитайзера → экранирование как текст, НЕ сырой HTML.
        body = _JS[_JS.index("sanitizeHtml: function (html)"):]
        body = body[:body.index("saveInfo: async function")]
        assert "&amp;" in body and "&lt;" in body and "&gt;" in body
        assert "return html || ''" not in body   # старый fail-open


class TestResponsive:
    def test_breakpoints(self):
        assert "@media (max-width: 991px)" in _HTML
        assert "@media (max-width: 479px)" in _HTML
        assert ".hub-grid { grid-template-columns: 1fr; }" in _HTML or \
            "grid-template-columns: 1fr" in _HTML

    def test_compact_nav_on_mobile(self):
        # A1/T-1158: подписи видны и на мобилке (правило скрытия удалено).
        assert ".nav-label" in _HTML
        assert ".nav-link > span:not(.msr)" not in _HTML

    def test_scope_panel_scrollable(self):
        assert ".scope-panel" in _HTML
        assert "max-height: 60vh" in _HTML
