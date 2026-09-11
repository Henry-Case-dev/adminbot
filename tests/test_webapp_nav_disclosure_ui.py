"""Раунд 10 (F-11, T-909 E1) — фронт-аудит навигации/прогрессивного раскрытия.

Маркеры: menu:'home'|'chat_profile'|'modules'|'ai'|'access' (5 значений),
MENU_ORDER, active_chat_id + X-Chat-Id в api(), `<details class="advanced">`,
adminbot.expand, read-only-гейт canViewTab (user → только status|info).
Регресс-маркеры F-8 сохранены (pre code, main-header, chip-auto).
"""
import pytest

from services import param_catalog as pc


def _js() -> str:
    return open("web/app.js", encoding="utf-8").read()


def _html() -> str:
    return open("web/index.html", encoding="utf-8").read()


class TestMenu:
    def test_navbar_menu_tags_present(self):
        js = _js()
        for tag in ["'modules'", "'ai'", "'access'"]:
            assert "menu: %s" % tag in js, tag

    def test_no_sidebar_dead_menu(self):
        """A1/T-1157: sidebar, MENU_ORDER/MENU_LABELS/sidebarOpen удалены."""
        js, html = _js(), _html()
        for token in ("MENU_ORDER", "MENU_LABELS", "sidebarOpen"):
            assert token not in js, token
        assert "sidebar" not in html
        assert "☰" not in html

    def test_user_sees_only_home(self):
        js = _js()
        # read-only гейт в canViewTab (user → только always: status|info)
        assert "tab.always) return true;" in js

    def test_scroll_area_fullscreen(self):
        """A1/T-1161/T-1162: main.scroll-area + fullscreen-скролл."""
        html = _html()
        assert ".app-shell" in html
        assert ".fullscreen-mode .scroll-area" in html
        assert "overscroll-behavior: contain" in html
        assert ".nav-label" in html
        assert ".nav-link > span:not(.msr) { display: none; }" not in html


class TestSelector:
    def test_selector_local_storage_and_header(self):
        js = _js()
        assert "adminbot.active_chat_id" in js
        assert "X-Chat-Id" in js
        assert "loadAccessCtx" in js

    def test_selector_element_in_header(self):
        html = _html()
        # T-1127: кастомный a11y scope-dropdown (listbox) вместо <select>.
        assert "toggleScope()" in html
        assert 'role="listbox"' in html
        assert "activeChatTitle" in html
        assert "scopeTriggerTitle" in html

    def test_selector_visible_for_single_chat(self):
        """BUG-1 (рекон раунда 10): селектор виден глобальному админу УЖЕ
        при ≥1 чате (раньше v-if требовал accessChats.length > 1 для
        global admin) — кнопки «Выбери чат» нет на видном месте была
        жалоба владельца; «Весь бот» остаётся опцией глобального админа."""
        html = _html()
        assert 'v-if="accessChats.length"' in html
        assert 'aria-haspopup="listbox"' in html

    def test_single_chat_selector_only(self):
        """F-13 (AC-1): селектор чата в шапке — ЕДИНСТВЕННАЯ точка выбора.
        Кнопка «💬 Выбрать чат» + дропдаун (openChatPicker/chatPickerOpen/
        pickChat) удалены из web/; индикация выбора — бейдж
        #{{ activeChatId }}; setActiveChat-селектор и «Весь бот» на месте."""
        js, html = _js(), _html()
        # негатив: методов/стейта пикера больше нет
        assert "openChatPicker" not in js
        assert "chatPickerOpen" not in js
        assert "pickChat" not in js
        assert "💬 Выбрать чат" not in html
        # позитив: единый scope-dropdown + индикация выбора
        assert "pickScope(o)" in html
        assert 'v-if="accessChats.length"' in html
        assert 'role="listbox"' in html
        # F-14: бейдж-идентификатор (в ЛС-скоупе — «ЛС #<id>»)
        assert "isDmCtx() ? 'ЛС #' + activeChatId : '#' + activeChatId" in html
        assert "activeChatTitle" in html


class TestProgressiveDisclosure:
    def test_details_advanced_marker(self):
        html = _html()
        assert '<details class="advanced' in html
        assert "Расширенные настройки" in html

    def test_expand_localstorage(self):
        js = _js()
        assert "adminbot.expand:" in js
        assert "expandOpen" in js
        assert "toggleExpand" in js

    def test_basic_advanced_items_methods(self):
        """Hotfix-R10: шаблон звал basicItems/advancedItems (index.html
        v-for по группам) — методов не было → TypeError в рендере → Vue
        удалял всю конфиг-ветку (вкладки Промпты/Лимиты/LLM/Память/Реакции/
        Доступы пустые). Методы обязаны существовать (зеркало itemAdvanced)."""
        js = _js()
        assert "basicItems" in js
        assert "advancedItems" in js
        assert "itemAdvanced" in js
        html = _html()
        assert "basicItems(grp)" in html
        assert "advancedItems(grp)" in html

    def test_registry_has_progressive_level(self):
        assert hasattr(pc.ParamSpec, "progressive_level")

    def test_group_card_skipped_when_empty(self):
        """BUG-5 (ре-дизайн 10.2, spec §10 F-11): пустые подсекции не
        рендерятся — карточка группы только при basic|advanced > 0;
        «Расширенные» только при advancedItems > 0 (без «(0)»).
        F-13 (AC-3): v-if/v-for на ОДНОМ узле схлопывал ВСЕ группы (Vue 3
        считает v-if вне скоупа цикла) — v-for вынесен на <template>,
        v-if остался на дочернем div с тем же выражением."""
        html = _html()
        assert ('v-if="basicItems(grp).length || advancedItems(grp).length"'
                in html)
        assert 'v-if="basicItems(grp).length"' in html
        assert 'v-if="advancedItems(grp).length > 0"' in html
        # Раунд 10.4 (D-1, AC-A2): :open — ТОЛЬКО expandOpen (ТЗ п.5:
        # «Расширенные» свёрнуты по умолчанию всегда); эвристика
        # basicItems(...)===0 удалена
        assert ':open="expandOpen(activeTab)"' in html
        assert "basicItems(grp).length === 0 ||" not in html
        # AC-A1: итог анализа — комментарий над <details>
        assert "эвристика" in html or "УДАЛЕНА" in html
        # F-13 позитив: v-for на <template>; ключ — там же
        assert '<template v-for="grp in currentTabGroups" :key="grp.uid">' \
            in html
        # F-13 негатив: v-for НЕ на div (v-if больше не на узле цикла —
        # двухстрочная конкатенация v-for+v-if отсутствует)
        assert '<div v-for="grp in currentTabGroups"' not in html
        js = _js()
        assert "return result.filter" in js


class TestModulesRework106:
    """Раунд 10.6 (A2/A3): 11 модулей, «один дом», нет «Кастомных модулей»."""

    def test_11_modules_and_labels(self):
        js = _js()
        for label in ("Саммаризация", "Прямые ответы", "Фактчек", "Поиск",
                      "Транскрипт голосовых и видео", "Выжимка видео",
                      "Скачивание медиа", "Веб-страницы", "Диагностика",
                      "Сон", "Ностальгия"):
            assert label in js, label
        assert "var MODULES = [" in js
        assert "type: 'modules'" in js
        assert "modules_feats" not in js

    def test_memory_rag_and_sleep_tabs(self):
        js, html = _js(), _html()
        assert "id: 'memory_rag'" in js and "label: 'Память'" in js
        assert "id: 'mod_sleep'" in js and "label: 'Сон'" in js
        assert "id: 'mod_nostalgia'" in js and "label: 'Ностальгия'" in js
        assert "activeModule && activeModule.id === 'mod_sleep' && isGlobalAdmin" in html
        assert "activeModule && activeModule.id === 'mod_nostalgia' && isGlobalAdmin" in html
        import services.param_catalog as pc
        mem = {g.id for g in pc.GROUPS if g.category == "memory"}
        groups = set()
        for tab in ("memory_rag", "mod_sleep", "mod_nostalgia"):
            groups |= pc.tab_group_ids(tab)
        assert mem <= groups and len(mem) == 3

    def test_no_custom_modules(self):
        js, html = _js(), _html()
        assert "Кастомные модули" not in js
        # UI-карточка «Кастомные модули» отсутствует (роут-алиас допустим).
        assert "Кастомные модули" not in html
        assert "modules_feats" not in html

    def test_modules_ui_and_modal(self):
        html = _html()
        assert 'class="module-list ' in html
        assert "openModuleWindow(m)" in html
        assert "activeModule" in html
        assert "toggleModule(m, $event.target.checked)" in html
        assert "Параметры" in html

    def test_permsoc_kept(self):
        js, html = _js(), _html()
        assert "id: 'permsoc'" in js
        # 10.9 (п.1): вкладка PERMsoc — 4 owner-блока вместо мастер-карты.
        assert "owner-block" in html
        assert "PERMSOC_OWNER_BLOCKS" in js
        assert "permsocModuleBadge" in js


class TestF8Regression:
    def test_f8_markers_kept(self):
        js, html = _js(), _html()
        assert "main-header" in html
        assert "log-panel" in html
        assert "chip-auto" in html
        assert "resolveRelationName" in js


class TestRound104ReviewFixes:
    """Ревью-фиксы раунда 10.4: select-разметка, истории отношений
    (кросс-чатовая защита), advanced-аккордеон настроек отношений."""

    def test_select_widget_branch_present(self):
        """B-10: выпадающий список в generic-рендере (basic + advanced) —
        с опциями/подписями и автосейвом."""
        html = _html()
        assert html.count("item.widget === 'select'") >= 2
        assert "item.select_options" in html
        assert "item.select_labels && item.select_labels[i]" in html
        assert "@change=\"saveConfigItem(item)\"" in html

    def test_relations_cross_chat_guard(self):
        """Ревью-фикс (F): на вкладке relations всегда АКТИВНЫЙ чат;
        chatLoreProfile.chat_id — только на «Лоре»; сброс профиля при уходе."""
        js = _js()
        assert "var onLoreTab = this.activeTab === 'chat_lore';" in js
        assert "onLoreTab && p && p.chat_id != null" in js
        assert "? p.chat_id : this.activeChatId" in js
        body = js[js.index("setTab: function (id)"):]
        assert "prevTab === 'chat_lore' && id !== 'chat_lore'" in body
        assert "this.chatLoreProfile = null;" in body

    def test_relations_advanced_accordion(self):
        """Ревью-фикс (F): advanced-аккордеон в «Настройках отношений» —
        D-канон (expandOpen(activeTab)); autoload-ветка setTab."""
        html = _html()
        # 10.8 (§2): emoji ⚙️ заменён Material-иконкой settings.
        assert "iconGlyph('settings')" in html
        body = html[html.index("Настройки отношений"):]
        assert '<details class="advanced mt-4"' in body
        assert "expandOpen(activeTab)" in body
        js = _js()
        assert "id === 'relations' && this.canViewTab('relations')" in js
        assert "loadRelations(this.activeChatId)" in js
