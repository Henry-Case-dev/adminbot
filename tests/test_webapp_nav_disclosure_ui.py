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
        assert "setActiveChat($event.target.value)" in html
        assert "activeChatTitle" in html
        assert "Весь бот" in html

    def test_selector_visible_for_single_chat(self):
        """BUG-1 (рекон раунда 10): селектор виден глобальному админу УЖЕ
        при ≥1 чате (раньше v-if требовал accessChats.length > 1 для
        global admin) — кнопки «Выбери чат» нет на видном месте была
        жалоба владельца; «Весь бот» остаётся опцией глобального админа."""
        html = _html()
        assert 'v-if="accessChats.length"' in html
        assert ">Весь бот</option>" in html

    def test_chat_picker_button_and_dropdown(self):
        """BUG-1: заметная кнопка «Выбрать чат» + дропдаун пикера
        (accessChats + «Весь бот»), синхрон с setActiveChat."""
        js, html = _js(), _html()
        assert "openChatPicker" in js
        assert "chatPickerOpen" in js
        assert "pickChat" in js
        assert "💬 Выбрать чат" in html
        assert "pickChat('')" in html
        assert "pickChat(c.chat_id)" in html


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
        «Расширенные» только при advancedItems > 0 (без «(0)»)."""
        html = _html()
        assert ('v-if="basicItems(grp).length || advancedItems(grp).length"'
                in html)
        assert 'v-if="basicItems(grp).length"' in html
        assert 'v-if="advancedItems(grp).length > 0"' in html
        assert ':open="basicItems(grp).length === 0 || expandOpen(activeTab)"' \
            in html
        js = _js()
        assert "return result.filter" in js


class TestModulesFeats:
    def test_modules_feats_tab(self):
        js = _js()
        assert "modules_feats" in js
        assert "type: 'modules'" in js

    def test_permsoc_tab_and_summary_card(self):
        """BUG-3 (ре-дизайн 10.2, spec §10 A/D): штатная вкладка
        «Функции PERMsoc» (config, menu modules) + массив-карта модулей +
        компактная summary-карточка в «Модулях и Фичах» с переходом."""
        js, html = _js(), _html()
        assert "id: 'permsoc'" in js
        assert "type: 'config'" in js
        assert "Функции PERMsoc" in js
        assert "activeTab === 'permsoc'" in html
        assert "permsocModuleBadge" in js
        assert "Открыть «Функции PERMsoc» 🎭" in html
        assert "setTab('permsoc')" in html

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
