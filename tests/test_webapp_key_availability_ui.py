"""Редизайн 10.5 (T-1128/T-1129/T-1142) — UI-маркеры.

Key-availability: компактный список (модуль/провайдер/модель/код/индикатор),
график по времени + легенда, empty-state, leak-safe эндпоинт.
Роли: rename/delete с superuser-disabled.
"""
import re


def _js() -> str:
    return open("web/app.js", encoding="utf-8").read()


def _html() -> str:
    return open("web/index.html", encoding="utf-8").read()


class TestKeyAvailabilityUi:
    def test_compact_list_markers(self):
        html = _html()
        assert "Доступность ключей API" in html
        assert 'class="avail-list"' in html
        for col in ("Модуль", "Провайдер", "Модель", "Код", "Статус"):
            assert col in html
        assert "availabilityClass(latestSample(p))" in html
        assert "availabilityCode(latestSample(p))" in html
        # мелкий шрифт / плотный line-height
        assert "font-size: var(--tx-tiny)" in html
        assert "line-height: 1.25" in html

    def test_chart_and_legend(self):
        html = _html()
        assert 'ref="keyHistoryCanvas"' in html
        js = _js()
        assert "loadKeyHistory: async function" in js
        assert "renderKeyHistoryChart: function" in js
        assert "stepped: true" in js
        assert "legend: { display: true" in js

    def test_empty_state(self):
        assert "История появится после нескольких проверок" in _html()

    def test_endpoint_and_allowlist(self):
        routes = open("web/api/routes.py", encoding="utf-8").read()
        assert '@api_router.get("/status/key-history")' in routes
        assert "key_history.api_payload()" in routes
        # R17/leak-safety: эндпоинт отдаёт только api_payload() (allowlist),
        # без прямой работы с ключами/last4.
        body = routes[routes.index("async def get_status_key_history"):]
        body = body[:body.index("async def get_status_logs")]
        assert "return key_history.api_payload()" in body
        assert "last4(" not in body
        assert "keys." not in body

    def test_no_hardcoded_provider_markers_in_registry(self):
        html = _html()
        # Динамический провайдер/модель: карточки берут model/provider с сервера.
        assert "card.model" in html
        # нет хардкода провайдеров в рендере key-availability
        block = html[html.index("Доступность ключей API"):]
        block = block[:block.index("<!-- Логи -->")]
        for bad in ("Deepseek", "Groq", "OpenRouter"):
            assert bad not in block


class TestRoleRenameDeleteUi:
    def test_buttons_present(self):
        html = _html()
        # 10.8 (§4.5): явная секция определений ролей (id="sec-roles")
        # вместо хрупкого слайсинга по подписям.
        roles = html[html.index('id="sec-roles"'):]
        roles = roles[:roles.index('id="sec-matrix"')]
        assert ">Переименовать</button>" in roles
        assert ">Удалить</button>" in roles
        assert ":disabled=\"!canEditRole(role)\"" in roles
        assert "roleRestrictionHint(role)" in roles

    def test_superuser_disabled_and_hint(self):
        html = _html()
        assert "Роль суперпользователя защищена" in html
        js = _js()
        assert "isSuperuserRole: function" in js
        assert "'admin'" in js and "'global_admin'" in js and "'superuser'" in js
        assert "canEditRole: function" in js

    def test_rename_delete_methods(self):
        js = _js()
        assert "renameRole: async function" in js
        assert "/rename" in js
        assert "deleteRole: async function" in js
        assert "method: 'DELETE'" in js

    def test_roles_api_exposes_role_type(self):
        routes = open("web/api/routes.py", encoding="utf-8").read()
        body = routes[routes.index("async def get_roles("):]
        body = body[:body.index("async def post_roles")]
        assert '"role_type"' in body
