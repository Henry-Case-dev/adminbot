"""F3 round 10.25 `global-scope-selector-round1025` — глобальный селектор области.

Маркерные тесты ТЗ §5/§14/§42/§43/§70 (поверх реального JS-теста
`tests/js/round1025_scope_selector_test.js`, который запускается из
`test_webapp_js_unit.py`):

  * селектор области — постоянно доступный элемент (Глобально/Чат/ЛС),
    раскрытие: поиск + глобально + чаты + ЛС;
  * источник значения: «Источник: глобальная настройка» (наследование) vs
    «Источник: настройки чата» (локальный override, PERMsoc);
  * «Вернуть глобальное значение» — отдельное действие (DELETE override),
    НЕ заводской сброс;
  * переключение области: проверка несохранённых изменений (предупреждение);
  * §43 — фактическое состояние (расхождение локального/глобального);
  * §14 — серверные метрики относятся ко всему серверу;
  * §70 — mobile (<768): селектор отдельной строкой под заголовком, тач ≥44px;
  * ПОЛНЫЙ chat_id — только в «технических подробностях»;
  * backend-контракт: GET /api/config → chat_source/global_value; DELETE
    /api/config/chat/{key} (снятие override).
"""
from pathlib import Path

ROOT = Path(".")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")


def _block(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


class TestSelectorPersistent:
    def test_selector_is_single_listbox_with_search(self):
        # Фундаментальный элемент §5: раскрытие = поиск + опции.
        assert 'v-if="accessChats.length"' in HTML
        assert 'role="listbox"' in HTML
        assert 'placeholder="Поиск чата…"' in HTML
        assert "pickScope(o)" in HTML
        assert 'scope-panel card-solid' in HTML

    def test_three_modes_defined(self):
        # Глобально (null) / Чат (<0) / ЛС (>0 + isDmCtx).
        assert "scopeKind: function ()" in JS
        assert "return this.scopeKind === 'dm' ? 'ЛС' : 'ЧАТ';" in JS
        assert "if (this.activeChatId == null) return 'global';" in JS

    def test_search_always_available(self):
        # Ревью Low: поиск в селекторе доступен всегда, а не только при >8.
        assert 'v-if="scopeOptions.length > 8"' not in HTML
        assert 'placeholder="Поиск чата…"' in HTML

    def test_source_rendered_in_v2_and_advanced_prompt_cards(self):
        # §5/ревью Medium: источник наследования в ОБОИХ шаблонах «Промптов»
        # (V2-плоский + advanced-аккордеон) и в generic-карточках.
        assert HTML.count('v-if="configSourceLabel(item)"') >= 4

    def test_full_chat_id_only_in_tech_details(self):
        # §5: полный chat_id — только в «технических подробностях».
        assert 'class="scope-tech' in HTML
        assert ".scope-tech" in CSS
        # выражение сохранено (маркер F-14), но скрыто внутри <details>
        assert ("isDmCtx() ? 'ЛС #' + activeChatId : '#' + activeChatId"
                in HTML)


class TestValueSource:
    def test_source_labels_defined(self):
        body = _block(JS, "configSourceLabel: function",
                      "configItemNotice: function")
        assert "Источник: глобальная настройка" in body
        assert "Источник: настройки чата" in body
        assert "item.chat_source === 'chat'" in body

    def test_source_rendered_in_config_cards(self):
        # Основной generic-рендер карточек параметров показывает источник.
        assert "configSourceLabel(item)" in HTML
        assert "configSourceTitle(item)" in HTML

    def test_actual_state_notice(self):
        # §43: фактическое состояние / расхождение локального и глобального.
        body = _block(JS, "configItemNotice: function",
                      "resetChatOverride: async function")
        assert "item.global_value === false" in body
        assert "Локально включено, хотя глобально выключено" in body
        # ревью Medium: не шумим на per_chat===false (~101 параметр) —
        # пометка только при фактическом расхождении override.
        assert "item.per_chat === false" not in body


class TestReturnGlobal:
    def test_action_named_not_factory_reset(self):
        # Видимая подпись сокращена (mobile overflow), полный смысл — в
        # aria-label/title (ревью Critical).
        assert 'aria-label="Вернуть глобальное значение"' in HTML
        assert ">↪ Глобальное</button>" in HTML
        # «заводской сброс» — это отдельная семантика; кнопка возврата
        # вызывает ТОЛЬКО resetChatOverride (DELETE override).
        assert 'v-if="itemOverriddenByChat(item)' in HTML

    def test_return_global_allowed_for_local_admin(self):
        # Ревью Low/2: сервер разрешает снятие override и local_admin
        # (routes.py::delete_chat_param) — кнопка видна и ему, а JS-guard
        # НЕ блокирует. UI == права сервера.
        assert ("itemOverriddenByChat(item) && (isGlobalAdmin || isDmCtx() "
                "|| isLocalAdminCtx())" in HTML)
        body = _block(JS, "resetChatOverride: async function",
                      "applyRoute: function")
        assert ("if (!(this.isGlobalAdmin || this.isDmCtx() "
                "|| this.isLocalAdminCtx()))" in body)

    def test_return_button_class_stable(self):
        # Ревью 2: стиль не завязан на текст aria-label — стабильный класс.
        assert HTML.count("btn-reset-global") == 8
        assert ".btn-reset-global {" in CSS
        assert 'button[aria-label="Вернуть глобальное значение"] {' not in CSS

    def test_reset_uses_delete_override_endpoint(self):
        body = _block(JS, "resetChatOverride: async function",
                      "applyRoute: function")
        assert "this.api('/api/config/chat/' + encodeURIComponent(item.key)" in body
        assert "method: 'DELETE'" in body
        # Ровно одна мутация — снятие переопределения (не POST значения/
        # заводского сброса).
        assert body.count("this.api(") == 1

    def test_backend_delete_route_exists(self):
        assert '@api_router.delete("/config/chat/{key}")' in ROUTES
        assert "overrides.pop(key, None)" in ROUTES


class TestSwitchGuard:
    def test_unsaved_changes_helper(self):
        assert "hasUnsavedEdits: function ()" in JS
        assert "stickyDirtyCount" in JS

    def test_switch_warns_on_unsaved(self):
        body = _block(JS, "setActiveChat: function (chatId)",
                      "isChatContext: function ()")
        assert "this.hasUnsavedEdits()" in body
        assert "window.confirm" in body
        assert "Переключить область и потерять их?" in body
        # отказ → область НЕ меняем (черновик не теряем): guard стоит ДО
        # присваивания activeChatId.
        assert body.index("this.hasUnsavedEdits()") < body.index("this.activeChatId = id;")

    def test_stale_scope_guard_intact(self):
        # §42: отброс запоздавших ответов старого scope не сломан F3.
        assert "scopeEpoch++" in JS
        assert "_scopeGuard: function (epoch)" in JS


class TestResponsive:
    def test_mobile_selector_under_title(self):
        # Селектор отдельной строкой ПОД заголовком: flex-basis 100% + order.
        assert ".scope-wrap { flex: 1 1 100%; order: 5; max-width: 100%; }" in CSS

    def test_mobile_touch_target(self):
        # Тач-цель ≥44px (§70) и полная ширина триггера на мобильном.
        assert "min-height: 44px" in CSS
        assert ("width: 100%; max-width: 100%; min-height: 44px;"
                in CSS)

    def test_server_metrics_note(self):
        # §14: при выбранном чате явная пометка про весь сервер.
        assert "Метрики относятся ко всему серверу" in HTML


class TestBackendContract:
    def test_config_exposes_source_and_global_value(self):
        assert '"chat_source": chat_source' in ROUTES
        assert '"global_value": global_value' in ROUTES

    def test_app_version_bumped(self):
        # F5 (10.25) — bump 2.58.9 → 2.58.10 (workspace-табы §46).
        assert 'APP_VERSION = "2.58.10"' in SETTINGS
