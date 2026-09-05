"""Раунд 7 (chat-lore-management-v2, E2/C-часть) — статический аудит
TMA-фронта «Лор чатов» (web/app.js + web/index.html).

Проверки по spec §3.10/§6.1 (образец TestFrontFixes в test_webapp_deps.py —
JS-тестов в проекте нет, поэтому аудируем строки-маркеры кода):

  * TABS-запись chat_lore (id/label/type);
  * ветка видимости canViewTab для типа chat_lore (Q6: секция ИЛИ
    probe-список) и probe-загрузка списка без секции (mounted/retry);
  * ветка шаблона index.html `activeTab === 'chat_lore'` + ключевые блоки;
  * методы app.js (spec-имена + алиасы C-части);
  * 409-обработка optimistic-lock (Q8: «Профиль изменён — перезагрузить?»).
"""
import re


class TestChatLoreFrontAudit:
    def _js(self):
        return open("web/app.js", encoding="utf-8").read()

    def _html(self):
        return open("web/index.html", encoding="utf-8").read()

    @staticmethod
    def _body(src, method_name):
        """Тело метода (по имени, включая 'async function') до конца."""
        start = src.index(method_name + ":")
        end = src.index("\n      },", start)
        return src[start:end]

    @staticmethod
    def _has_method(src, name):
        return re.search(name + r":\s*(async\s+)?function", src) is not None

    # ── вкладка и видимость ────────────────────────────────────────────────

    def test_tab_declared_in_tabs(self):
        src = self._js()
        assert re.search(r"id: 'chat_lore', icon: '📜', label: 'Лор чатов', "
                         r"type: 'chat_lore'", src)

    def test_can_view_tab_branch_for_chat_lore(self):
        """Q6 (3.10): тип chat_lore → секция chat_lore ИЛИ непустой
        probe-список (per-chat админы без секции)."""
        body = self._body(self._js(), "canViewTab")
        assert "tab.type === 'chat_lore'" in body
        assert "hasPerm('section.chat_lore')" in body
        assert "this.chatLoreChats.length > 0" in body

    def test_probe_for_users_without_section(self):
        """3.10: юзеры без секции chat_lore проходят probe /chats при
        авторизации (вкладка видна per-chat админам только при непустом
        списке)."""
        src = self._js()
        assert "hasPerm('section.chat_lore')" in src
        assert src.count("self.loadChats(true)") >= 2   # mounted + retryInitData

    def test_settab_loads_chats_for_section(self):
        src = self._js()
        body = self._body(src, "setTab")
        assert "id === 'chat_lore'" in body
        assert "self.loadChats()" in body or "this.loadChats()" in body

    # ── шаблон index.html ──────────────────────────────────────────────────

    def test_template_branch_present(self):
        html = self._html()
        assert "v-else-if=\"activeTab === 'chat_lore'\"" in html

    def test_template_blocks_present(self):
        html = self._html()
        assert "v-model=\"loreManual\"" in html
        assert "v-model=\"loreAuto\"" in html
        assert "v-model=\"loreSettings.auto_enabled\"" in html
        assert "v-model.number=\"loreSettings.auto_period_hours\"" in html
        assert "v-model.number=\"loreSettings.auto_window_hours\"" in html
        assert "Сгенерировать сейчас" in html
        assert "Очистить авто-лор" in html
        assert "Сохранить настройки" in html
        assert "История изменений" in html
        assert "В память бота уходит" in html

    # ── методы app.js ──────────────────────────────────────────────────────

    def test_methods_present(self):
        """3.10/AC-12: методы лора в app.js (spec-имена и алиасы C-части)."""
        src = self._js()
        for name in ("loadChats", "loadProfile", "saveManual", "saveSettings",
                     "generateNow", "clearAuto", "loadHistory",
                     # алиасы имён C-части
                     "loadLoreChats", "selectLoreChat", "saveLoreManual",
                     "saveLoreSettings", "loreGenerate", "loreClearAuto",
                     "loreLoadHistory", "openLoreHistory", "closeLoreHistory"):
            assert self._has_method(src, name), f"метод {name} отсутствует"

    def test_save_manual_sends_updated_at_body(self):
        """Q8 (3.10): PUT manual несёт optimistic-метку updated_at в теле."""
        body = self._body(self._js(), "saveManual")
        assert "'/api/chat_lore/'" in body
        assert "updated_at: p.updated_at" in body
        assert "manual_lore: this.loreManual" in body

    def test_409_conflict_opens_reload_modal(self):
        """Q8/AC-12: 409 conflict (code='conflict', current_updated_at) в
        saveManual → модалка «Профиль изменён — перезагрузить?»."""
        body = self._body(self._js(), "saveManual")
        assert "e.status === 409" in body
        assert "e.message.code === 'conflict'" in body
        assert "this.chatLore409 = e.message" in body
        assert "confirmLoreReload: function" in self._js()
        # модалка в index.html с текстом подтверждения
        html = self._html()
        assert "Профиль изменён — перезагрузить?" in html
        assert "Перезагрузить" in html

    def test_settings_and_auto_ops_endpoints(self):
        src = self._js()
        assert "/settings" in self._body(src, "saveSettings")
        assert "/generate" in self._body(src, "generateNow")
        assert "/clear_auto" in self._body(src, "clearAuto")
        assert "/history?limit=100" in self._body(src, "loadHistory")

    def test_worker_skip_reasons_mapped(self):
        """После «Сгенерировать сейчас» перечитываем профиль (auto_lore/
        last_auto_at могли измениться) и различаем UNCHANGED/quiet_window."""
        body = self._body(self._js(), "generateNow")
        assert "quiet_window" in body
        assert "UNCHANGED" in body
        assert "auto_disabled" in body

    # ── C2: переезд чата (remap) и per-chat админы (глобальный admin) ─────

    def test_c2_global_admin_methods_present(self):
        """C2/AC: методы remap/админов в app.js (spec-имена)."""
        src = self._js()
        for name in ("remapChat", "loadChatAdmins", "addChatAdmin",
                     "removeChatAdmin"):
            assert self._has_method(src, name), f"метод {name} отсутствует"

    def test_c2_remap_endpoint_and_confirm(self):
        """C2: POST /chat_lore/{id}/remap c {new_chat_id}; confirm-текст
        «Перенести лор/админов…»; после успеха — reload списка + выбор нового."""
        body = self._body(self._js(), "remapChat")
        assert "'/api/chat_lore/'" in body and "/remap" in body
        assert "new_chat_id" in body
        assert "Перенести лор/админов на новый chat_id? Старый профиль будет удалён" in body
        assert "window.confirm" in body
        assert "this.loadChats()" in body
        assert "loadProfile(newId)" in body

    def test_c2_admin_endpoints(self):
        """C2: GET?chat_id / POST {chat_id, telegram_id} / DELETE?chat_id=
        &telegram_id= + confirm на удаление."""
        src = self._js()
        body = self._body(src, "loadChatAdmins")
        assert "admins?chat_id=" in body and "/api/chat_lore/admins" in body
        add = self._body(src, "addChatAdmin")
        assert "method: 'POST'" in add
        assert "chat_id: p.chat_id" in add
        assert "telegram_id: tid" in add
        rem = self._body(src, "removeChatAdmin")
        assert "method: 'DELETE'" in rem
        assert "&telegram_id=" in rem
        assert "window.confirm" in rem
        assert "loadChatAdmins" in rem

    def test_c2_profile_loads_admins_for_global_admin(self):
        """C2: выбор чата (loadProfile) тянет список админов при isGlobalAdmin
        и чистит его при ошибке профиля."""
        body = self._body(self._js(), "loadProfile")
        assert "isGlobalAdmin" in body
        assert "loadChatAdmins(p.chat_id)" in body

    def test_c2_template_remap_and_admin_sections(self):
        """C2: секции «Переезд чата» и «Администраторы чата» в карточке
        чата — только для глобального админа (v-if isGlobalAdmin)."""
        html = self._html()
        assert "Переезд чата" in html
        assert "Перепривязать" in html
        assert "Администраторы чата" in html
        assert "Добавить" in html
        assert "v-model.number=\"remapNewChatId\"" in html
        assert "v-model.number=\"newChatAdminId\"" in html
        assert html.count("v-if=\"isGlobalAdmin\"") >= 2
        assert "@click=\"removeChatAdmin(a)\"" in html
        assert "@click=\"addChatAdmin()\"" in html
