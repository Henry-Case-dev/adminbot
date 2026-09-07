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


class TestF8Regression:
    def test_f8_markers_kept(self):
        js, html = _js(), _html()
        assert "main-header" in html
        assert "log-panel" in html
        assert "chip-auto" in html
        assert "resolveRelationName" in js
