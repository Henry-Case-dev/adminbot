"""Раунд 10 (F-7, T-862 G5) — фронт-аудит RBAC/BYOK-маркеров.

app.js: activeChatId/X-Chat-Id в api(), роль-пикер-методы и элементы
(openPermPicker/savePermPicker/permPicker), BYOK-поля и статус-строки
(loadKeyStatus/saveOwnKey), access-карточки (loadLocalAdmins/addLocalAdmin),
сброс переопределения чата (resetChatOverride); index.html-ветки
(permPickerOpen, «Ваш ключ чата…», «Локальные админы чата»).
"""


def _js() -> str:
    return open("web/app.js", encoding="utf-8").read()


def _html() -> str:
    return open("web/index.html", encoding="utf-8").read()


class TestChatContext:
    def test_active_chat_id_and_persist(self):
        js = _js()
        assert "activeChatId" in js
        assert "adminbot.active_chat_id" in js
        assert "setActiveChat" in js

    def test_api_adds_x_chat_id_header(self):
        js = _js()
        assert "X-Chat-Id" in js
        assert "loadAccessCtx" in js
        assert "syncActiveChatTitle" in js

    def test_chat_badge_in_header(self):
        html = _html()
        assert "activeChatTitle" in html
        assert "Весь бот" in html


class TestRolePicker:
    def test_picker_methods(self):
        js = _js()
        assert "openPermPicker" in js
        assert "savePermPicker" in js
        assert "permPickerItem" in js
        # Ре-дизайн 10.2, BUG-6 (§3.2.1): флаги-чекбоксы «Чтение»/«Запись»;
        # сброс к дефолту — DELETE (resetPermPicker)
        assert "viewRoles" in js
        assert "editRoles" in js
        assert "resetPermPicker" in js
        assert "roleArr" in js

    def test_picker_elements_and_types(self):
        html = _html()
        assert "permPickerOpen" in html
        # BUG-6: две секции чекбоксов (Юзер/Модератор/Локальный админ)
        assert "Чтение" in html
        assert "Запись" in html
        assert "Юзер" in html
        assert "Модератор" in html
        assert "Локальный админ" in html
        assert "Сбросить на дефолт" in html
        assert "только\n            глобальному админу" in html or \
            "только глобальному админу" in html
        # gear возле каждого параметра (generic-рендер)
        assert "openPermPicker(item)" in html
        # бейдж «скрыт» и «чат», сброс на глобальное
        assert "скрыт" in html
        assert "resetChatOverride(item)" in html


class TestByokUi:
    def test_byok_methods(self):
        js = _js()
        assert "loadKeyStatus" in js
        assert "saveOwnKey" in js
        assert "deleteOwnKey" in js

    def test_byok_empty_fields_and_status(self):
        html = _html()
        assert "Ваш ключ чата…" in html
        assert "Использовать мой" in html
        assert "Глобальный ключ" in html  # статус-строка бюджета/запрета


class TestAccessCards:
    def test_access_methods(self):
        js = _js()
        assert "loadLocalAdmins" in js
        assert "addLocalAdmin" in js
        assert "removeLocalAdmin" in js
        assert "accessMy" in js

    def test_access_blocks(self):
        html = _html()
        assert "Локальные админы чата" in html
        assert "Мой доступ" in html


class TestChatOverrideIndicator:
    def test_reset_method_and_badge(self):
        js = _js()
        assert "itemOverriddenByChat" in js
        assert "chat_source" in js
