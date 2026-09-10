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
    def test_all_menu_tags_present(self):
        js = _js()
        for tag in ["'home'", "'chat_profile'", "'modules'", "'ai'", "'access'"]:
            assert "menu: %s" % tag in js, tag

    def test_menu_order_and_labels(self):
        js = _js()
        assert "MENU_ORDER" in js
        assert "['home', 'chat_profile', 'modules', 'ai', 'access']" in js

    def test_user_sees_only_home(self):
        js = _js()
        # read-only гейт в canViewTab (user → только always: status|info)
        assert "tab.always) return true;" in js

    def test_sidebar_scrollable(self):
        """BUG-2 (рекон раунда 10): сайдбар скроллится сам — десктоп
        md:sticky/md:h-screen/md:overflow-y-auto + scroll-thin на aside;
        мобильное media-правило — overflow-y:auto (+ webkit touch)."""
        html = _html()
        assert "md:sticky md:top-0 md:h-screen md:overflow-y-auto" in html
        assert "scroll-thin" in html
        assert "overflow-y: auto" in html
        assert "-webkit-overflow-scrolling: touch" in html


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


class TestModulesFeats:
    def test_memory_tabs_reorg_104(self):
        """Раунд 10.4 (C-1/C-2/C-4): «Память и RAG» → «Память»; отдельные
        вкладки «Сон»/«Ностальгия»; мини-блоки на своих вкладках."""
        js, html = _js(), _html()
        assert "label: 'Память'" in js
        assert "label: 'Память и RAG'" not in js
        assert "id: 'memory_dream'" in js and "label: 'Сон'" in js
        assert "id: 'memory_nostalgia'" in js and "label: 'Ностальгия'" in js
        assert "activeTab === 'memory_dream' && isGlobalAdmin" in html
        assert "activeTab === 'memory_nostalgia' && isGlobalAdmin" in html
        assert "activeTab === 'memory_rag' && isGlobalAdmin" not in html
        # каталог: memory-группы покрыты без дублей (C-2)
        import services.param_catalog as pc
        mem_groups = {g.id for g in pc.GROUPS if g.category == "memory"}
        groups = set()
        for tab in ("memory_rag", "memory_dream", "memory_nostalgia"):
            groups |= pc.tab_group_ids(tab)
        assert mem_groups <= groups
        assert len(mem_groups) == 3

    def test_modules_feats_tab(self):
        js = _js()
        assert "modules_feats" in js
        assert "type: 'modules'" in js

    def test_permsoc_tab_and_summary_card(self):
        """BUG-3 (ре-дизайн 10.2, spec §10 A/D) + раунд 10.4 (A-6):
        штатная вкладка «Функции PERMsoc» (config, menu modules, мастер-карта)
        остаётся; компактная summary-карточка в «Модулях» УДАЛЕНА (без
        setTab-перехода из modules_feats — вкладка в меню «Модули»)."""
        js, html = _js(), _html()
        assert "id: 'permsoc'" in js
        assert "type: 'config'" in js
        assert "Функции PERMsoc" in js
        assert "activeTab === 'permsoc'" in html
        assert "permsocModuleBadge" in js
        # A-6: сводка и переход убраны (негатив)
        assert "Открыть «Функции PERMsoc» 🎭" not in html
        assert "setTab('permsoc')" not in html
        # A-5: карточки-модули на месте (имя+описание)
        assert "Модули (вкл/выкл)" in html
        assert "Dead page" in html

    def test_modules_render_blocks(self):
        html = _html()
        assert "Тяжёлые фичи" in html
        assert "Функции PERMsoc" in html
        assert "Бюджет фона" in html

    def test_modules_budget_always_rendered(self):
        """Hotfix-R10 («Модули и Фичи» пустые при „Весь бот“): весь контент
        был за v-if='activeChatId == null' — global admin без выбранного чата
        видел только плейсхолдер. Бюджет фона (глобальный) теперь ВНЕ
        чатового гейта; тяжёлые фичи/PERMsoc — карточки всегда
        (без чата — заметка + сводка Opt-In)."""
        html = _html()
        assert "v-else-if=\"activeTab === 'modules_feats'\"" in html
        # комментарий ветки упоминает старый гейт — ищем РЕАЛЬНЫЙ v-if
        budget = html.index("📊 Бюджет фона — глобальная карточка")
        gate_at = html.rindex('v-if="activeChatId == null"')
        assert budget < gate_at, "бюджет должен рендериться до чатового гейта"
        assert "Выберите чат в шапке — тяжёлые модули" in html
        assert "optInCount()" in html
        assert "master" in html
        js = _js()
        assert "optInCount" in js


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
        assert html.count("item.widget === 'select'") == 2
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
        body = html[html.index("⚙️ Настройки отношений"):]
        assert '<details class="advanced mt-4"' in body
        assert "expandOpen(activeTab)" in body
        js = _js()
        assert "id === 'relations' && this.canViewTab('relations')" in js
        assert "loadRelations(this.activeChatId)" in js
