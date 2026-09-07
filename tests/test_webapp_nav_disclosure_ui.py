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


class TestModulesFeats:
    def test_modules_feats_tab(self):
        js = _js()
        assert "modules_feats" in js
        assert "type: 'modules'" in js

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
