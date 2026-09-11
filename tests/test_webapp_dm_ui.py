"""F-14 (dm-user-settings, T-958, spec §6/§7) — TMA-маркеры DM-скоупа.

Поверх F-13 (единый селектор): запись «Личные сообщения» приходит с
сервера (is_dm:true, title синтезирован) — фронт рендерит её как обычную
опцию единого селектора; бейдж «ЛС #{id}»; canViewTab-правило для
config-вкладок (permsoc скрыт); BYOK-блок (isChatContext && !isGlobalAdmin
уже покрывает DM-владельца); «↪ глобальное» — (isGlobalAdmin || isDmCtx());
empty-states «…или Личные сообщения…». Плюс маркеры S1/S2/S3 (саммари
DEFAULT-OFF): гейты конспекта зовут chat_summary_enabled, _tick
исключает положительные id.
"""
import re


def _js() -> str:
    return open("web/app.js", encoding="utf-8").read()


def _html() -> str:
    return open("web/index.html", encoding="utf-8").read()


class TestDmFrontend:
    def test_dm_row_renders_via_unified_selector(self):
        """DM-строка — обычная опция единого селектора F-13
        (title/chat_id приходят с сервера; is_dm флаг — для isDmCtx)."""
        html = _html()
        # единый scope-dropdown (T-1127) рендерит accessChats (вкл. DM-строку)
        assert "v-if=\"accessChats.length\"" in html
        assert "pickScope(o)" in html
        js = _js()
        assert "c.is_dm" in js              # isDmCtx ищет DM-флаг в accessChats

    def test_dm_models_readonly_matches_server(self):
        """R10.5-2: в DM per_chat=False (models.*/keys.*) — read-only,
        зеркалит серверный 422 ('ключ нельзя переносить на уровень чата')."""
        js = _js()
        body = js[js.index("canEditConfig: function (key)"):]
        body = body[:body.index("itemMatchesSource")] if "itemMatchesSource" in body else body
        assert "per_chat === false" in body
        assert "cat === 'models'" in body
        assert "return false" in body

    def test_is_dm_ctx_helper(self):
        js = _js()
        assert "isDmCtx: function" in js
        assert "this.activeChatId == null" in js
        assert "c.chat_id === self.activeChatId && c.is_dm" in js

    def test_can_view_tab_dm_config_rule(self):
        """DM: config-вкладки открыты (кроме permsoc) — правило ДО
        прав-матрицы; canViewTab другие ветки не тронуты."""
        js = _js()
        assert ("this.isDmCtx() && tab.type === 'config' "
                "&& tab.id !== 'permsoc'" in js)
        assert "if (tab.always) return true;" in js
        assert "permsoc" in js

    def test_dm_badge_ls_marker(self):
        html = _html()
        assert "isDmCtx() ? 'ЛС #' + activeChatId : '#' + activeChatId" in html

    def test_byok_block_covers_dm_owner(self):
        """BYOK-блок (isChatContext && !isGlobalAdmin) — DM-владелец уже
        покрыт (isDmCtx ⇒ isChatContext; DM-владелец не global admin)."""
        html = _html()
        assert "activeTab === 'llm_providers' && isChatContext() && !isGlobalAdmin" \
            in html

    def test_reset_override_visible_for_dm(self):
        """«↪ глобальное» — (isGlobalAdmin || isDmCtx()) во всех местах
        (basic/advanced generic-рендер + config-блок лора, 10.4 A-8) +
        гейт в методе."""
        html = _html()
        assert html.count("itemOverriddenByChat(item) && (isGlobalAdmin || isDmCtx())") >= 4
        js = _js()
        body = js[js.index("resetChatOverride: async function"):]
        assert "this.isGlobalAdmin || this.isDmCtx()" in body

    def test_empty_states_mention_dm(self):
        """10.9 (п.1): мастер-карта permsoc заменена owner-блоками; тумблер
        чата/ЛС — permsocOwnerOn/canToggleOwner (единый путь записи)."""
        html = re.sub(r"\s+", " ", _html())
        assert "owner-block" in html
        assert "permsocOwnerOn" in html
        js = _js()
        assert "toggleOwner: async function" in js
        assert "permsocOwnerOn: function" in js

    def test_chat_source_badge_text_kept(self):
        """badge item.chat_source === 'chat' — текст «чат» (без дифов)."""
        html = _html()
        assert 'v-if="item.chat_source === \'chat\'"' in html

    def test_can_edit_config_dm_enabled(self):
        """F-14 + R10.5-2: в DM-скоупе per-chat ключи редактируемы, а
        per_chat=False (models.*/keys.*) — read-only (зеркалит серверный
        422 «ключ нельзя переносить на уровень чата»; keys.* — BYOK-путь)."""
        js = _js()
        body = js[js.index("canEditConfig: function (key)"):]
        # DM-ветка — ПОСЛЕ wildcard (приоритет глобального админа сохранён)
        assert "if (p.wildcard) return true;" in body
        # R10.5-2: DM-ветка зеркалит сервер — per_chat=False (models.*/keys.*)
        # read-only; per-chat ключи по-прежнему редактируемы.
        assert "per_chat === false" in body
        assert "cat === 'models'" in body
        assert body.index("p.wildcard") < body.index("isDmCtx()")
        # keys-гейт (cat === 'keys') и массивный матчинг — прежние
        assert "cat === 'keys'" in body
        assert "arr(p.keys).indexOf(key) >= 0" in body


class TestDmSummaryGateMarkers:
    """S1/S2/S3 (spec §4.2): бегущий конспект гейтится chat_summary_enabled;
    _tick исключает положительные chat_id (ЛС-рассылки нет)."""

    def test_s1_summary_memory_uses_chat_summary_enabled(self):
        src = open("services/summary_memory.py", encoding="utf-8").read()
        assert "await chat_summary_enabled(chat_id)" in src

    def test_s2_direct_chat_uses_chat_summary_enabled(self):
        src = open("services/direct_chat_service.py", encoding="utf-8").read()
        assert "await chat_summary_enabled(chat_id)" in src

    def test_s3_scheduler_skips_dm_positive_ids(self):
        src = open("services/summary_scheduler.py", encoding="utf-8").read()
        assert "int(chat_id) > 0" in src
        assert "continue" in src

    def test_s5_bot_router_gate_not_touched(self):
        """bot.py: гейт flags.summary_enabled (613-643) — без дифов
        (маркер: роутер-гейт жив и НЕ зовёт chat_summary_enabled)."""
        src = open("bot.py", encoding="utf-8").read()
        assert "flags.summary_enabled" in src
        assert "chat_summary_enabled" not in src

    def test_catalog_registry_unchanged(self):
        """Новых параметров каталога НЕТ (MED-017): саммари-флаг
        резолвится legacy-путём (Settings/категория flags), а НЕ новым
        ключом REGISTRY; dm-специфичных ключей в каталоге нет."""
        from services.param_catalog import REGISTRY, get_by_pg_key
        spec = get_by_pg_key("flags.chat_running_summary_enabled")
        assert spec is not None and spec.type == "bool"
        assert not any(k.startswith("dm_") or "direct_message" in k
                       for k in REGISTRY)


class TestDmSources:
    def test_no_ddl_for_dm(self):
        """Ноль DDL: dm-миграций/новых таблиц не добавляли."""
        ddl = open("services/pg_db.py", encoding="utf-8").read()
        assert "chat_profiles" in ddl
        assert re.search(r"CREATE TABLE IF NOT EXISTS dm_", ddl) is None

    def test_isolation_sql_filters_present(self):
        """6 точек изоляции: SQL-фильтры chat_id < 0 на местах."""
        access = open("web/api/access.py", encoding="utf-8").read()
        assert "WHERE p.chat_id < 0" in access
        store = open("services/chat_lore_store.py", encoding="utf-8").read()
        assert "chat_id < 0" in store
        oversight = open("services/oversight.py", encoding="utf-8").read()
        assert "WHERE p.chat_id < 0" in oversight
        chat_lore_api = open("web/api/chat_lore.py", encoding="utf-8").read()
        assert "is_dm_scope(resolved)" in chat_lore_api
        gates = open("web/api/gates.py", encoding="utf-8").read()
        assert "is_dm_scope(chat_id)" in gates
