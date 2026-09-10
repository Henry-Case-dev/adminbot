"""Раунд 9 (AGI Memory, F-задачи, T-828…T-831) — статический аудит
web-api relations/memory_agi (F2/F3) и TMA-фронта «Участники и отношения» /
«Синтез (сон)»/«Ностальгия» (F4).

Проверки по spec §3.6.1–3.6.3 (образец TestChatLoreFrontAudit в
tests/test_webapp_lore_ui.py — JS-тестов в проекте нет, поэтому аудируем
строки-маркеры кода):

  * backend: relations-эндпоинты в web/api/chat_lore.py (GET список,
    PUT/DELETE ручной пометки — тело и сегментная форма, тумблер
    relations_enabled через PUT settings и dedicated-роут), модуль
    web/api/memory_agi.py (dream run/beliefs/log + DELETE/protect +
    nostalgia log), include в web/app.py, runtime-геттеры воркеров;
  * app.js: методы loadRelations/saveRelation/resetRelation/saveRelationsToggle
    (alias-имена F4-сессии) и memory-блоков (runDreamNow/dreamDelete/
    dreamProtect/loadDreamBeliefs/loadNostalgiaLog), 409-флоу через
    chatLore409-модалку, права isGlobalAdmin;
  * index.html: блок «Участники и отношения» в chat_lore-ветке (после
    «Настройки автогенерации», до «В память бота уходит») и мини-блоки
    «Синтез (сон)»/«Ностальгия» ПОД generic-рендером (activeTab ===
    'memory_rag').
"""
import re
import os


class TestMemoryFrontAudit:
    def _js(self):
        return open("web/app.js", encoding="utf-8").read()

    def _html(self):
        return open("web/index.html", encoding="utf-8").read()

    def _chat_lore_py(self):
        return open("web/api/chat_lore.py", encoding="utf-8").read()

    def _memory_api_py(self):
        return open("web/api/memory_agi.py", encoding="utf-8").read()

    def _app_py(self):
        return open("web/app.py", encoding="utf-8").read()

    def _runtime_py(self):
        return open("services/lore_runtime.py", encoding="utf-8").read()

    @staticmethod
    def _body(src, method_name):
        start = src.index(method_name + ":")
        end = src.index("\n      },", start)
        return src[start:end]

    @staticmethod
    def _has_method(src, name):
        return re.search(name + r":\s*(async\s+)?function", src) is not None

    # ── backend: relations (spec §3.6.1) ───────────────────────────────────

    def test_chat_lore_relations_endpoints_present(self):
        src = self._chat_lore_py()
        assert re.search(r"@chat_lore_router\.get\(\"/chat_lore/\{chat_id\}/"
                         r"relations\"\)", src)
        assert re.search(r"@chat_lore_router\.put\(\"/chat_lore/\{chat_id\}/"
                         r"relations\"\)", src)
        assert re.search(r"@chat_lore_router\.put\(\"/chat_lore/\{chat_id\}/"
                         r"relations/\{user_id\}\"\)", src)
        assert re.search(r"@chat_lore_router\.delete\(\"/chat_lore/\{chat_id\}"
                         r"/relations\"\)", src)
        assert re.search(r"@chat_lore_router\.delete\(\"/chat_lore/\{chat_id\}"
                         r"/relations/\{user_id\}\"\)", src)
        assert re.search(r"@chat_lore_router\.put\(\"/chat_lore/\{chat_id\}"
                         r"/relations_enabled\"\)", src)

    def test_chat_lore_relations_uses_runtime_db_and_409(self):
        """F2/Q2: SQLite-скоры — только через lore_runtime (get_lore_db/
        get_relations_service); 409-паттерн _conflict + can_access_chat."""
        src = self._chat_lore_py()
        assert "lore_runtime.get_lore_db()" in src or \
            "get_lore_db(), lore_runtime.get_relations_service()" in src
        assert "_require_chat" in src
        assert "ChatLoreConflict as exc" in src
        assert "_conflict(exc)" in src
        # форма списка: relations_enabled + users
        assert '"relations_enabled": bool(profile.relations_enabled)' in src
        assert '"users": users[:_RELATIONS_LIST_MAX]' in src
        # сброс на авто: stage 'auto' → store.put_relation без стадии
        assert 'stage_manual in (None, "auto")' in src

    def test_settings_route_carries_relations_enabled(self):
        """§3.6.1: тумблер per-chat доступен и через PUT /settings
        (relations_enabled: bool|null) — серверная часть update_settings."""
        src = self._chat_lore_py()
        assert "relations_enabled: bool | None = None" in src
        assert "store.update_settings(" in src
        assert "relations_enabled=payload.relations_enabled" in src
        store = open("services/chat_lore_store.py", encoding="utf-8").read()
        assert '("relations_enabled", relations_enabled)' in store
        assert 'if name == "relations_enabled":' in store

    # ── backend: memory_agi (spec §3.6.2) ──────────────────────────────────

    def test_memory_router_registered(self):
        app = self._app_py()
        assert "from web.api.memory_agi import memory_router" in app
        assert "app.include_router(memory_router, prefix=\"/api\")" in app

    def test_memory_endpoints_present(self):
        src = self._memory_api_py()
        assert 'memory_router.post("/memory/dream/run")' in src
        assert 'memory_router.get("/memory/dream/beliefs")' in src
        assert 'memory_router.delete("/memory/dream/beliefs/{fact_id}")' in src
        assert 'memory_router.post("/memory/dream/beliefs/{fact_id}/protect")' \
            in src
        assert 'memory_router.get("/memory/dream/log")' in src
        assert 'memory_router.get("/memory/nostalgia/log")' in src

    def test_memory_202_409_run_contract(self):
        """POST run: 202 {status: started} / 409 {code: already_running} /
        503 воркер недоступен; 404 для DELETE не-belief."""
        src = self._memory_api_py()
        assert "status_code=202" in src
        assert '"status": "started"' in src
        assert '"code": "already_running"' in src
        assert "status_code=409" in src
        assert "status_code=503" in src
        assert "worker.run_once(chat_id)" in src
        assert "asyncio.create_task(worker.run_once(chat_id))" in src
        assert "status_code=404" in src
        assert "soft_delete_belief(fact_id)" in src
        assert "protect_belief_text" in src

    def test_memory_only_global_admin(self):
        """§3.6.2: ручной запуск/удаление/GET-логи — только глобальный
        admin (паттерн chat_lore remap: роль admin/wildcard/ADMIN_USER_ID)."""
        src = self._memory_api_py()
        assert "role admin" in src or "роль admin" in src
        assert "_is_global_admin" in src
        assert "settings.ADMIN_USER_ID" in src
        assert 'status_code=403, detail="permission denied"' in src
        assert "_require_global_admin(request, user)" in src

    def test_runtime_worker_getters(self):
        """§3.6.2: lore_runtime расширен геттерами get_dream_worker()/
        get_nostalgia_worker() + set-параметрами (включены в reset)."""
        src = self._runtime_py()
        assert "def get_dream_worker" in src
        assert "def get_nostalgia_worker" in src
        assert "set_lore_components(store=None, cache=None, notify=None, " \
            "worker=None," in src
        assert "db=None, relations=None, dream=None, nostalgia=None)" in src
        assert "_dream = _nostalgia = None" in src

    def test_database_read_helpers_for_api(self):
        """F2/F3: read/удаление-хелперы DatabaseService для API-блоков
        (список beliefs, логи, мягкое удаление, protect)."""
        db = open("services/database.py", encoding="utf-8").read()
        assert "async def list_recent_beliefs" in db
        assert "async def soft_delete_belief" in db
        assert "async def protect_belief_text" in db
        assert "async def recent_dream_log" in db
        assert "async def recent_nostalgia_log" in db
        assert "async def get_graph_fact" in db
        assert "status = 'unconfirmed'" in db and "kind = 'belief'" in db

    # ── frontend app.js (spec §3.6.3) ──────────────────────────────────────

    def test_js_relations_data_and_methods(self):
        src = self._js()
        assert "relationsEnabled: false" in src
        assert "chatRelations: []," in src
        assert "relationDraft: null," in src
        assert "relationsBusy: false," in src
        for name in ("loadRelations", "saveRelation", "resetRelation",
                     "saveRelationsToggle", "saveRelationManual",
                     "toggleRelationsEnabled", "removeRelationManual",
                     "onRelationsToggle"):
            assert self._has_method(src, name), f"метод {name} отсутствует"

    def test_js_relations_endpoints_and_409(self):
        src = self._js()
        body = self._body(src, "loadRelations")
        assert "'/api/chat_lore/'" in body and "/relations'" in body
        save = self._body(src, "saveRelationManual")
        assert "method: 'PUT'" in save
        assert "user_id: row.user_id" in save
        assert "stage_manual: this.relationDraft.stage_manual" in save
        assert "(p && p.updated_at) || null" in save       # F-5: лор-профиль или активный чат
        assert "chatLore409 = e.message" in save
        toggle = self._body(src, "toggleRelationsEnabled")
        assert "relations_enabled" in toggle
        assert "(p && p.updated_at) || null" in toggle
        assert "chatLore409 = e.message" in toggle
        reset = self._body(src, "removeRelationManual")
        assert "method: 'DELETE'" in reset
        assert "user_id: row.user_id" in reset

    def test_js_profile_reload_after_409(self):
        """409-флоу: модалка «Перезагрузить?» → confirmLoreReload →
        loadProfile (который тянет и relations)."""
        src = self._js()
        assert "confirmLoreReload: function" in src
        body = self._body(src, "loadProfile")
        assert "this.loadRelations(p.chat_id)" in body

    def test_js_memory_methods_and_data(self):
        src = self._js()
        assert "dreamBusy: false," in src
        assert "memoryRagBusy: false," in src
        assert "dreamBeliefs: []," in src
        assert "dreamLog: []," in src
        assert "nostalgiaLog: []," in src
        for name in ("loadDreamBeliefs", "runDreamNow", "dreamDelete",
                     "dreamProtect", "loadDreamLog", "loadNostalgiaLog"):
            assert self._has_method(src, name), f"метод {name} отсутствует"

    def test_js_memory_endpoints(self):
        src = self._js()
        assert "'/api/memory/dream/run'" in self._body(src, "runDreamNow")
        assert "'/api/memory/dream/beliefs?limit=20'" in \
            self._body(src, "loadDreamBeliefs")
        assert "'/api/memory/dream/beliefs/'" in \
            self._body(src, "dreamDelete")
        assert "already_running" in self._body(src, "runDreamNow")
        assert "'/api/memory/dream/beliefs/'" in \
            self._body(src, "dreamProtect")
        assert "loadDreamBeliefs()" in self._body(src, "dreamProtect")
        assert "'/api/memory/nostalgia/log?limit=20'" in \
            self._body(src, "loadNostalgiaLog")

    # ── frontend index.html (spec §3.6.3) ─────────────────────────────────

    def test_html_relations_block_on_relations_tab(self):
        """Раунд 10.4 (F-5): блок участников переехал на вкладку relations
        (кастом-шаблон activeTab === 'relations'); из chat_lore удалён."""
        html = self._html()
        assert "activeTab === 'relations'" in html
        assert "Влиять на тон бота" in html
        assert "stageRu(u.stage_auto)" in html
        assert "draft_stage" in html
        assert "draft_note" in html
        assert "@click=\"saveRelationManual(u)\"" in html
        assert "@click=\"removeRelationManual(u)\"" in html
        assert "@change=\"onRelationsToggle($event)\"" in html
        assert 'value="auto">авто</option>' in html
        # негатив: в лоре участниковского блока больше нет
        assert "авто-стадии (SQLite-скоры)" not in html
        # тексты-хелперы: «В память бота уходит» остался в лоре
        assert "В память бота уходит" in html

    def test_html_memory_blocks_under_generic(self):
        html = self._html()
        # MAJOR-2 (ревью): мини-блоки Сон/Ностальгия перенесены в МОДАЛКУ
        # модуля и рендерятся по activeModule.id (не по activeTab).
        assert "activeModule && activeModule.id === 'mod_sleep' && isGlobalAdmin" in html
        assert "activeModule && activeModule.id === 'mod_nostalgia' && isGlobalAdmin" in html
        assert "activeTab === 'mod_sleep'" not in html
        assert "activeTab === 'mod_nostalgia'" not in html
        assert "Синтез (сон)" in html
        assert "Запустить синтез сейчас" in html
        assert "Последние убеждения" in html
        assert "@click=\"runDreamNow()\"" in html
        assert "@click=\"dreamProtect(b)\"" in html
        assert "@click=\"dreamDelete(b)\"" in html
        assert "Последние сны (лог дистилляций)" in html
        assert "Ностальгия" in html
        assert "@click=\"loadNostalgiaLog()\"" in html
        assert "причина:" in html
        # блок физически внутри модалки модуля (после modal-body)
        assert html.index("modal-body") < html.index("Синтез (сон)")

    def test_html_no_relations_leak_into_config(self):
        """«Участники и отношения» — только в chat_lore-ветке; в generic
        конфиге рендерятся только memory-мини-блоки (v-if memory_rag)."""
        html = self._html()
        chat = html.index("Участники и отношения")
        config_start = html.index("currentTabIsConfig")
        assert chat > config_start  # chat_lore-ветка идёт ПОСЛЕ generic

    def test_bot_wires_runtime_components(self):
        """F1: bot.py создаёт RelationsService(db, aliases, store, cache) и
        кладёт db/relations/воркеры в set_lore_components."""
        bot = open("bot.py", encoding="utf-8").read()
        assert "RelationsService(" in bot
        assert "from services.user_relations import RelationsService" in bot
        assert "set_lore_components(" in bot
        assert "relations=_relations_service" in bot
        assert "dream=_dream_worker" in bot
        assert "nostalgia=_nostalgia_worker" in bot
        assert "db=db, relations=_relations_service" in bot
